"""History backfill: the store has used Gondola for a while. Runs the REAL nightly close for each past night.

    python -m gondola.backfill --days 75            # ~2-4 min; rebuilds out/ history ending on the demo night
    python -m gondola.backfill --days 5 --out /tmp/x

For each night, as of 11:10 pm that night:
  - the database is cut to that night (connectors.ingest.cut, same result as ingest(upto=...)), so the close only sees
    data that existed then (payout reports by their available_at, as always);
  - pipeline.run_close runs with render=True, an offline Notifier writing to the app outbox (never real texts for
    past nights) and the app Bucket; the manager's confirmed chashu count varies 0-40 (0 on sell-out nights);
  - the card is approved (the final night stays for the manager to approve, unless --approve-final);
  - the bucket lifecycle runs (daily PDFs expire after 30 days; findings.json stays so they can be rebuilt);
  - on the 1st of a month: the previous month's summary JSON and a 2-page monthly report (HTML + PDF) go to the bucket.
PDFs are printed at the end in one browser session, and only for reports still stored (expired ones keep HTML-free
findings.json and rebuild on request). Everything is built in a staging folder and swapped into out/ at the end, so a
running API never sees half a history.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import NP
from .metrics import ROOT, Store

DB = ROOT / "data" / "gondola.duckdb"
OUT = ROOT / "out"
# what the backfill owns in out/ (everything else there, e.g. eval.json, is left alone)
HISTORY_ITEMS = ["closes.json", "approvals.json", "outbox.jsonl", "bucket", "reports", "forecasts", "backtest_cache.csv",
                 "history.json"]


def leftover_for(store: Store, date: str, rng: np.random.Generator) -> float | None:
    """A plausible count the manager confirms at close: 0 after a sell-out, otherwise 0-40 (never more than was left)."""
    p = store.df("SELECT par, used, sold_out FROM prep_log WHERE business_date = ?", [date])
    if p.empty:
        return None
    if bool(p.sold_out[0]):
        return 0.0
    left = max(float(p.par[0]) - float(p.used[0]), 0.0)
    return float(min(int(rng.integers(0, 41)), int(left)))


def _approve(approvals: dict, date: str, res: dict, as_of: datetime):
    card = (res.get("plan") or {}).get("card") or []
    if not card:
        return
    approvals[date] = {"card": card, "approved_at": (as_of + timedelta(minutes=4)).isoformat(timespec="seconds"),
                       "for_run": res.get("run_id"), "by": "manager (history)"}


def run(days: int = 75, end: str | None = None, out: Path | str = OUT, db: Path | str = DB, approve_final: bool = False,
        pdf_concurrency: int = 4, seed: int = 11, quiet: bool = False, pdf_all: bool = False) -> dict:
    from . import pipeline
    from .connectors.ingest import cut
    from .report import render
    from .storage import Bucket
    from .tools.sentinel import Notifier
    from .tools.summary import monthly_report_context, monthly_summary

    t_all = time.perf_counter()
    out, db = Path(out), Path(db)
    main = Store(db)
    last = str(main.last_date().date())
    main.con.close()
    end_ts = pd.Timestamp(end) if end else pd.Timestamp(last)
    nights = [str(d.date()) for d in pd.date_range(end_ts - pd.Timedelta(days=days - 1), end_ts)]
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))

    stage = out.parent / f".{out.name}_backfill"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    if (out / "backtest_cache.csv").exists():  # backtests are pure functions of the date: reuse them
        shutil.copy(out / "backtest_cache.csv", stage / "backtest_cache.csv")
    dbdir = stage / "_db"
    dbdir.mkdir()

    old_out, old_defer = pipeline.OUT, render.DEFER_PDF
    jobs: list = []
    pipeline.OUT, render.DEFER_PDF = stage, jobs
    bucket = Bucket(stage / "bucket")
    notifier = Notifier(stage / "outbox.jsonl")
    notifier.sms_live = notifier.email_live = notifier.live = False  # history never texts anyone for real
    approvals: dict = {}
    rows, monthly = [], []
    rng = np.random.default_rng(seed)
    timings = {"cut": 0.0, "close": 0.0, "monthly": 0.0}

    def night_db(ds: str) -> Path:
        if ds == last:
            return db  # tonight: the live database itself
        t0 = time.perf_counter()
        p = cut(ds, dbdir / f"night_{ds}.duckdb", src=db)
        timings["cut"] += time.perf_counter() - t0
        return p

    try:
        with ThreadPoolExecutor(max_workers=2) as pre:  # cut the next nights' databases while this one closes
            futs = {ds: pre.submit(night_db, ds) for ds in nights[:2]}
            for i, ds in enumerate(nights):
                if i + 2 < len(nights):
                    futs[nights[i + 2]] = pre.submit(night_db, nights[i + 2])
                ndb = futs.pop(ds).result()
                st = Store(ndb)
                as_of = (pd.Timestamp(ds) + pd.Timedelta(hours=23, minutes=10)).to_pydatetime()
                lo = leftover_for(st, ds, rng)
                t0 = time.perf_counter()
                res = pipeline.run_close(ds, db=ndb, as_of=as_of, force=True, notifier=notifier, bucket=bucket, render=True,
                                         portion_counts={"chashu": lo} if lo is not None else None, agent_model=False)
                timings["close"] += time.perf_counter() - t0
                if ds != nights[-1] or approve_final:
                    _approve(approvals, ds, res, as_of)
                bucket.apply_lifecycle(as_of)
                if pd.Timestamp(ds).day == 1:
                    t1 = time.perf_counter()
                    prev = (pd.Timestamp(ds) - pd.Timedelta(days=1)).strftime("%Y-%m")
                    state = json.loads((stage / "closes.json").read_text(encoding="utf-8"))
                    sm = monthly_summary(st, prev, state, out_dir=stage)
                    ctx = monthly_report_context(sm, pipeline.STORE_NAME, generated=pd.Timestamp(as_of).strftime(f"%b %{NP}d %{NP}I:%M %p"))
                    (stage / "reports" / "monthly").mkdir(parents=True, exist_ok=True)
                    (stage / "reports" / "monthly" / f"{prev}.context.json").write_text(json.dumps(ctx, default=str, indent=1), encoding="utf-8")
                    r = render.render_monthly(ctx, stage / "reports" / "monthly", prev)
                    bucket.put_monthly(prev, sm, as_of, html=Path(r["html"]))
                    monthly.append(prev)
                    timings["monthly"] += time.perf_counter() - t1
                st.con.close()
                if ndb != db:
                    try:
                        Path(ndb).unlink(missing_ok=True)
                    except OSError:  # Windows: a connection may still hold it; the folder is removed at the end
                        pass
                rows.append({"date": ds, "status": res["status"], "seconds": res["seconds"],
                             "urgent": sum(1 for f in res["findings"] if f.get("urgency") == "urgent"), "chashu_left": lo})
                say(f"  {ds}  {res['status']:<8} {res['seconds']:5.1f}s  urgent {rows[-1]['urgent']}"
                    + (f"  + monthly {monthly[-1]}" if pd.Timestamp(ds).day == 1 and monthly else ""))
        render.DEFER_PDF = old_defer

        # PDFs: one browser, only for reports the bucket still stores (expired ones rebuild on request)
        t2 = time.perf_counter()
        print_jobs, keys = [], []
        for hp, pp in jobs:
            hp, name = Path(hp), Path(hp).stem
            key = f"monthly/{name}" if len(name) == 7 else f"daily/{name}"
            rec = bucket.index.get(key)
            if rec is None or (rec["status"] not in ("stored", "rebuilt") and not pdf_all):
                continue
            print_jobs.append((hp, bucket.pdf_dest(key)))
            keys.append(key)
        render.render_pdfs(print_jobs, concurrency=pdf_concurrency)
        for k in keys:
            bucket.attach_pdf(k)
        timings["pdf"] = time.perf_counter() - t2

        # reports/ is the working copy of the latest renders: keep it for nights still stored, drop expired ones
        rep = stage / "reports"
        for k, rec in bucket.index.items():
            if rec["kind"] != "daily":
                continue
            d = rec["period"]
            if rec["status"] == "stored":
                if bucket.path(rec["uri"]).exists():
                    shutil.copy(bucket.path(rec["uri"]), rep / f"{d}.pdf")
            else:
                for suf in (".html", ".pdf", ".findings.json"):
                    (rep / f"{d}{suf}").unlink(missing_ok=True)
        (stage / "approvals.json").write_text(json.dumps(approvals, indent=1), encoding="utf-8")
        hist = {"nights": len(nights), "first": nights[0], "last": nights[-1], "built_at": datetime.now().isoformat(timespec="seconds"),
                "monthly": monthly, "rows": rows}
        (stage / "history.json").write_text(json.dumps(hist, indent=1), encoding="utf-8")
        shutil.rmtree(dbdir, ignore_errors=True)
    finally:
        pipeline.OUT, render.DEFER_PDF = old_out, old_defer

    _swap_in(stage, out)
    idx = Bucket(out / "bucket").index
    status = pd.Series([v["status"] for v in idx.values() if v["kind"] == "daily"]).value_counts().to_dict()
    total = round(time.perf_counter() - t_all, 1)
    summary = {"nights": len(nights), "first": nights[0], "last": nights[-1], "seconds": total,
               "timings": {k: round(v, 1) for k, v in timings.items()}, "pdfs_printed": len(print_jobs),
               "daily_status": status, "monthly": monthly, "statuses": pd.Series([r["status"] for r in rows]).value_counts().to_dict()}
    say(json.dumps(summary, indent=1))
    return summary


def _swap_in(stage: Path, out: Path):
    """Replace the history items in out/ with the staged ones (old ones moved aside, then deleted)."""
    out.mkdir(parents=True, exist_ok=True)
    trash = out.parent / f".{out.name}_old_history"
    if trash.exists():
        shutil.rmtree(trash)
    trash.mkdir()
    old_items = [out / n for n in HISTORY_ITEMS] + list(out.glob("close_*.json")) + [out / "rebuilt"]
    for p in old_items:
        if p.exists():
            shutil.move(str(p), str(trash / p.name))
    for p in stage.iterdir():
        shutil.move(str(p), str(out / p.name))
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(trash, ignore_errors=True)


def has_history(out: Path | str = OUT, min_nights: int = 30) -> bool:
    p = Path(out) / "closes.json"
    if not p.exists():
        return False
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return sum(1 for k in st if not k.startswith("_")) >= min_nights


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the real nightly close for past nights (history for the app).")
    ap.add_argument("--days", type=int, default=75)
    ap.add_argument("--end", default=None, help="last night (default: the last business date in the data)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--approve-final", action="store_true", help="also approve the final night's card")
    ap.add_argument("--pdf-all", action="store_true", help="print PDFs for expired nights too (slower)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    print(f"Backfilling {a.days} nights of closes into {a.out} ...", flush=True)
    run(a.days, a.end, Path(a.out), approve_final=a.approve_final, quiet=a.quiet, pdf_all=a.pdf_all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
