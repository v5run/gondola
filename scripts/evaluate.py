"""Score every agent against the ground truth in data/truth/ and write out/eval.json + out/eval.md.

    python scripts/evaluate.py            # everything (about 5-10 minutes on a laptop)
    python scripts/evaluate.py --quick    # skips the 47-night replay
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gondola.metrics import Store  # noqa: E402
from gondola.tools import books, demand, guard, plan, stock  # noqa: E402
from gondola.agents.ask import ask  # noqa: E402
from gondola.agents.guardrails import check_numbers  # noqa: E402

TRUTH = ROOT / "data" / "truth"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "out"
R: dict = {}


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(r, 4)}


def eval_books(st: Store):
    t0 = time.perf_counter()
    truth = pd.read_csv(TRUTH / "anomalies.csv")
    dates = st.df("SELECT DISTINCT business_date FROM payout_lines ORDER BY 1").business_date
    flagged = {"error": set(), "missing": set(), "commission_days": set(), "review": set()}
    total_rec = 0.0
    for d in dates:
        r = books.match_payouts(st, str(pd.Timestamp(d).date()))
        total_rec += r["recoverable_usd"]
        for f in r["findings"]:
            if f["kind"] == "error_charge_disputable":
                flagged["error"].add(f["evidence"][0])
            elif f["kind"] == "error_charge_review":
                flagged["review"].add(f["evidence"][0])
            elif f["kind"] == "missing_from_payout":
                flagged["missing"].add(f["evidence"][0])
            elif f["kind"] == "commission_overcharge":
                flagged["commission_days"].add((str(pd.Timestamp(d).date()), f["channel"]))
    t_err = set(truth[truth.type.str.startswith("error_charge")].order_id)
    t_miss = set(truth[truth.type == "missing_from_payout"].order_id)
    t_comm = set((d, c) for d, c in truth[truth.type == "commission_overcharge"][["business_date", "channel"]].drop_duplicates().itertuples(index=False))
    truth_usd = float(truth[truth.type.str.startswith("error_charge") | (truth.type == "missing_from_payout") | (truth.type == "commission_overcharge")].amount.sum())
    R["books"] = {
        "days_reconciled": int(len(dates)),
        "error_charges_disputable": prf(len(flagged["error"] & t_err), len(flagged["error"] - t_err), len(t_err - flagged["error"])),
        "missing_from_payout": prf(len(flagged["missing"] & t_miss), len(flagged["missing"] - t_miss), len(t_miss - flagged["missing"])),
        "commission_overcharge_days": prf(len(flagged["commission_days"] & t_comm), len(flagged["commission_days"] - t_comm), len(t_comm - flagged["commission_days"])),
        "error_charges_sent_to_review": len(flagged["review"]),
        "review_that_were_truly_disputable": len(flagged["review"] & t_err),
        "recoverable_flagged_usd": round(total_rec, 2), "recoverable_truth_usd": round(truth_usd, 2),
        "seconds": round(time.perf_counter() - t0, 1)}
    # cash
    cs = st.df("SELECT business_date, expected_cash, closed_cash FROM cash_drawer_shifts")
    flags = set(str(pd.Timestamp(d).date()) for d, e, c in cs.itertuples(index=False) if abs(c - e) > books.CASH_TOL)
    t_cash = set(truth[truth.type == "cash_short"].business_date)
    R["books"]["cash_short"] = prf(len(flags & t_cash), len(flags - t_cash), len(t_cash - flags))


def eval_stock(st: Store):
    vh = stock.variance_history(st)
    vh["flag"] = (vh.gap < 0) & (vh.gap.abs() / vh.used.clip(lower=1e-9) > stock.VARIANCE_FLAG) & (vh.gap.abs() >= stock.MIN_UNITS)
    sap = vh[vh.sku == "sapporo"]
    shrink_window = (sap.business_date >= "2026-03-02") & (sap.business_date <= "2026-03-29")
    nood = vh[vh.sku == "noodles"]
    other = vh[~vh.sku.isin(["sapporo", "noodles"])]
    R["stock"] = {
        "count_days": int(vh.business_date.nunique()),
        "sapporo_shrink_weeks_flagged": f"{int(sap[shrink_window].flag.sum())} of {int(shrink_window.sum())}",
        "sapporo_false_flags_outside_window": int(sap[~shrink_window].flag.sum()),
        "noodles_weeks_flagged": f"{int(nood.flag.sum())} of {len(nood)}",
        "noodles_median_gap_pct": round(float(nood.gap_pct.median()), 4),
        "other_sku_false_flag_rate": round(float(other.flag.mean()), 4),
    }


def eval_forecast(st: Store):
    t0 = time.perf_counter()
    bt = demand.rolling_backtest(st, days=120)
    bt.to_csv(OUT / "backtest_120d.csv", index=False)
    perfect = pd.DataFrame([demand.backtest_forecast(st, d, weather_noise=0.0) for d in bt.date.tail(60)])
    tom = pd.read_csv(TRUTH / "tomorrow_orders.csv")
    tom_actual = int((tom.status == "completed").sum())
    fc = demand.run_forecast(st, "2026-11-06", bt.tail(60))
    ratio = bt.actual / bt.predicted
    lo, hi = np.quantile(ratio.head(60), [0.1, 0.9])
    cov = float(((bt.actual.tail(60) >= bt.predicted.tail(60) * lo) & (bt.actual.tail(60) <= bt.predicted.tail(60) * hi)).mean())
    # intraday: compare forecast curve shape for tomorrow with truth at 15-min and hourly
    t = pd.to_datetime(tom[tom.status == "completed"].created_at)
    act15 = t.dt.hour * 4 + t.dt.minute // 15
    act15 = act15.value_counts().sort_index()
    curve = pd.DataFrame(fc["curve"]).set_index("bin").orders
    idx = sorted(set(curve.index) | set(act15.index))
    a, f = act15.reindex(idx, fill_value=0), curve.reindex(idx, fill_value=0) * tom_actual / fc["p50"]
    wape15 = float((a - f).abs().sum() / a.sum())
    ah, fh = a.groupby(np.array(idx) // 4).sum(), f.groupby(np.array(idx) // 4).sum()
    wapeh = float((ah - fh).abs().sum() / ah.sum())
    # item level for tomorrow
    tl = pd.read_csv(TRUTH / "tomorrow_order_lines.csv")
    ti = tl[tl.order_id.isin(tom[tom.status == "completed"].order_id)].item.value_counts()
    fi = pd.DataFrame(fc["items"]).groupby("item").units.sum()
    fi = fi * tom_actual / fc["p50"]
    ii = sorted(set(ti.index) | set(fi.index))
    wape_item = float((ti.reindex(ii, fill_value=0) - fi.reindex(ii, fill_value=0)).abs().sum() / ti.sum())
    R["forecast"] = {
        "backtest_days": int(len(bt)), "mape_daily": round(float(bt.error_pct.abs().mean()), 4),
        "mape_naive_same_weekday": round(float(bt.naive_error_pct.abs().mean()), 4),
        "mape_with_perfect_weather_last60": round(float(perfect.error_pct.abs().mean()), 4),
        "bias_daily": round(float(bt.error_pct.mean()), 4),
        "worst_days": bt.assign(a=bt.error_pct.abs()).nlargest(3, "a")[["date", "predicted", "actual", "error_pct"]].to_dict("records"),
        "interval_80_coverage_last60": round(cov, 3),
        "tomorrow": {"date": "2026-11-06", "p10": fc["p10"], "p50": fc["p50"], "p90": fc["p90"], "actual": tom_actual,
                     "error_pct": round((fc["p50"] - tom_actual) / tom_actual, 4), "rush": fc["rush"]},
        "tomorrow_wape_15min_shape": round(wape15, 4), "tomorrow_wape_hourly_shape": round(wapeh, 4),
        "tomorrow_wape_item_level": round(wape_item, 4), "seconds": round(time.perf_counter() - t0, 1)}


def eval_plan_and_guard(st: Store):
    """Replay the last 120 days: historical par (manager habit) vs newsvendor par from the backtest forecast."""
    bt = pd.read_csv(OUT / "backtest_120d.csv")
    lost = pd.read_csv(TRUTH / "lost_sales.csv")
    menu = st.df("SELECT item, chashu_portions FROM menu").set_index("item").chashu_portions
    lost["need"] = lost["items"].str.split("|").map(lambda xs: sum(menu.get(x, 0) for x in xs))
    lost_need = lost.groupby("business_date").need.sum()
    q = """SELECT o.business_date, SUM(m.chashu_portions) need, COUNT(DISTINCT o.order_id) n FROM orders o
           JOIN order_lines l USING(order_id) JOIN menu m ON m.item=l.item GROUP BY 1"""
    served = st.df(q).assign(business_date=lambda x: x.business_date.dt.strftime("%Y-%m-%d")).set_index("business_date")
    prep = st.df("SELECT business_date, par FROM prep_log").assign(business_date=lambda x: x.business_date.dt.strftime("%Y-%m-%d")).set_index("business_date").par
    rows = []
    for i, r in bt.iterrows():
        if i < 30:
            continue
        hist = bt.iloc[:i].tail(60)
        lo, hi = np.quantile(hist.actual / hist.predicted, [0.1, 0.9])
        d = r.date
        demand_portions = float(served.need.get(d, 0) + lost_need.get(d, 0))  # true (uncensored) chashu demand
        ppo_hist = float((served.need / served.n).loc[:d].tail(28).mean())
        nv = plan.newsvendor_par(r.predicted * lo, r.predicted, r.predicted * hi, ppo_hist)["chashu_portions"]
        for name, par in (("habit", prep.get(d, 0)), ("gondola", nv)):
            rows.append({"date": d, "policy": name, "par": par, "demand": demand_portions,
                         "short": max(demand_portions - par, 0), "left": max(par - demand_portions, 0)})
    df = pd.DataFrame(rows)
    summ = df.groupby("policy").agg(days=("date", "size"), stockout_days=("short", lambda s: int((s > 0).sum())),
                                    portions_short=("short", "sum"), portions_left=("left", "sum"), avg_par=("par", "mean")).round(1)
    cost = 7.80 / 7.0
    summ["leftover_cost_usd"] = (summ.portions_left * cost * 0.4).round(2)
    summ["lost_margin_usd"] = (summ.portions_short * plan.CHASHU_MARGIN).round(2)
    R["plan"] = summ.reset_index().to_dict("records")
    g = guard.replay_year(st)
    R["guard"] = {"days_replayed": int(len(g)), "historical_avoidable_cancels": int(g.historical_avoidable_cancels.sum()),
                  "avoided": int(g.avoided.sum()), "app_orders_held_back_for_dine_in": int(g.app_orders_held_back.sum()),
                  "app_sales_held_back_usd": round(float(g.app_sales_held_back.sum()), 2),
                  "days_with_pause": int(g.paused_at.notna().sum())}
    # sanity: schedule solves
    R["plan_schedule_example"] = plan.prep_schedule([{"name": "Braise chashu", "minutes": 150, "deadline": 17 * 60},
                                                      {"name": "Slice chashu", "minutes": 40, "deadline": 18 * 60, "needs": "Braise chashu"},
                                                      {"name": "Fold gyoza", "minutes": 90, "deadline": 17 * 60 + 30}])


def eval_guard_errors(st: Store):
    """Guard on the last 90 days under count error and pause delay, with and without the recount prompt."""
    days = [str(pd.Timestamp(d).date()) for d in st.df("SELECT business_date FROM prep_log WHERE par > 0 ORDER BY 1").business_date][-90:]
    base = int(st.df("SELECT COUNT(*) n FROM orders WHERE cancel_reason='item_unavailable' AND channel<>'in_store' AND business_date >= ?",
                     [days[0]]).n[0])
    rows = []
    for err in (0.0, 0.05, 0.10):
        for delay in (2, 5, 15):
            for rc in (False, True):
                c = h = n = 0
                for i, d in enumerate(days):
                    r = guard.guarded_day(st, d, count_error=err, delay_min=delay, recount=rc, seed=i)
                    c += r["cancels"]; h += r["held_back"]; n += r["recounts"]
                rows.append({"count_error": err, "pause_delay_min": delay, "recount": rc, "cancels_90d": c,
                             "portions_held_back": round(h), "recount_prompts": n})
    R["guard_errors"] = {"status_quo_cancels_90d": base, "grid": rows}


def eval_ask(st: Store):
    """25 questions. Ground truth is computed independently from the raw CSVs with pandas."""
    o = pd.read_csv(RAW / "pos_orders.csv", parse_dates=["business_date"])
    ln = pd.read_csv(RAW / "pos_order_lines.csv")
    lab = pd.read_csv(RAW / "labour_shifts.csv", parse_dates=["business_date"])
    c = o[o.status == "completed"]
    T = pd.Timestamp("2026-11-05")
    sales = lambda s, e, ch=None: float(c[(c.business_date >= s) & (c.business_date <= e) & ((c.channel == ch) if ch else True)].subtotal.sum())
    n = lambda s, e, ch=None: float(len(c[(c.business_date >= s) & (c.business_date <= e) & ((c.channel == ch) if ch else True)]))
    ts = pd.Timestamp
    lw_s, lw_e = T - pd.Timedelta(days=T.dayofweek + 7), T - pd.Timedelta(days=T.dayofweek + 1)
    daily = c.groupby("business_date").subtotal.sum()
    qs = [
        ("What were net sales yesterday?", sales(ts("2026-11-04"), ts("2026-11-04"))),
        ("How many orders did we do today?", n(T, T)),
        ("DoorDash sales last week?", sales(lw_s, lw_e, "doordash")),
        ("How many Uber Eats orders in October?", n(ts("2026-10-01"), ts("2026-10-31"), "ubereats")),
        ("What was our revenue in March?", sales(ts("2026-03-01"), ts("2026-03-31"))),
        ("Average ticket last month?", sales(ts("2026-10-01"), ts("2026-10-31")) / n(ts("2026-10-01"), ts("2026-10-31"))),
        ("Grubhub sales in the last 30 days", sales(T - pd.Timedelta(days=29), T, "grubhub")),
        ("How many orders on Oct 3?", n(ts("2026-10-03"), ts("2026-10-03"))),
        ("In-store sales on Feb 14?", sales(ts("2026-02-14"), ts("2026-02-14"), "in_store")),
        ("What was our best day this year?", float(daily[daily.index >= T - pd.Timedelta(days=364)].max())),
        ("What was the slowest day in the last 365 days?", float(daily[daily.index >= T - pd.Timedelta(days=364)].min())),
        ("Labour cost last week?", float((lab[(lab.business_date >= lw_s) & (lab.business_date <= lw_e)].hours * lab[(lab.business_date >= lw_s) & (lab.business_date <= lw_e)].wage).sum())),
        ("How many orders last Friday?", n(T - pd.Timedelta(days=6), T - pd.Timedelta(days=6))),
        ("Sales on 2026-07-04", sales(ts("2026-07-04"), ts("2026-07-04"))),
        ("DoorDash orders in the last 7 days", n(T - pd.Timedelta(days=6), T, "doordash")),
        ("How much did we make in December?", sales(ts("2025-12-01"), ts("2025-12-31"))),
        ("How many cancellations last month?", float(len(o[(o.status == "cancelled") & (o.business_date >= "2026-10-01") & (o.business_date <= "2026-10-31")]))),
        ("Avoidable cancellations in the last 30 days", float(len(o[(o.cancel_reason == "item_unavailable") & (o.business_date >= T - pd.Timedelta(days=29))]))),
        ("Uber Eats sales on Nov 1", sales(ts("2026-11-01"), ts("2026-11-01"), "ubereats")),
        ("How many orders in January?", n(ts("2026-01-01"), ts("2026-01-31"))),
    ]
    results = []
    for q, truth in qs:
        a = ask(st, q, "2026-11-05")
        nums = [float(x.replace(",", "").replace("$", "")) for x in __import__("re").findall(r"\$?[\d,]+\.?\d*", a.text.split(":")[-1])]
        ok = any(abs(v - truth) <= max(0.02, 0.0005 * abs(truth)) for v in nums)
        results.append({"q": q, "truth": round(truth, 2), "answer": a.text, "ok": ok})
    # explanation / similar-day / backtest questions: check they call the right tool and answer
    for q, tool in [("Why was last Thursday slow?", "explain_change"), ("Which past days were most like tomorrow?", "find_similar_days"),
                    ("How accurate was the forecast on Oct 31?", "backtest_forecast"), ("How good has the forecast been lately?", "backtest_forecast"),
                    ("Compare today vs a usual Thursday", "compare_periods")]:
        a = ask(st, q, "2026-11-05")
        results.append({"q": q, "truth": tool, "answer": a.text, "ok": a.calls and a.calls[0][0] == tool})
    sys.path.insert(0, str(ROOT / "tests" / "data"))
    from adversarial_questions import QS
    adv = {"questions": len(QS), "crashes": 0, "clarified": 0, "answered": 0, "answers": []}
    for q in QS:
        try:
            a = ask(st, q, "2026-11-05")
            adv["clarified" if a.clarify else "answered"] += 1
            adv["answers"].append({"q": q, "a": a.text, "clarify": a.clarify})
        except Exception as e:  # noqa: BLE001
            adv["crashes"] += 1
            adv["answers"].append({"q": q, "a": f"CRASH {e}"})
    R["ask_adversarial"] = adv
    R["ask"] = {"questions": len(results), "correct": sum(r["ok"] for r in results),
                "failures": [r for r in results if not r["ok"]], "sample": results[:3] + results[-5:]}


def eval_guardrails():
    tools = [{"net_sales": 15270.4, "orders": 470, "short": 86.34, "rate": 0.0102}]
    cases = [("Net sales were $15,270 on 470 orders.", True), ("DoorDash paid $86.34 short.", True),
             ("Cancellation rate is 1.0%.", True), ("Net sales were $16,100.", False), ("We lost $212.50 to fees.", False),
             ("470 orders, up 12% on last week.", False)]
    res = [{"text": t, "expected_ok": e, "got_ok": check_numbers(t, tools)["ok"]} for t, e in cases]
    R["guardrails"] = {"cases": len(res), "correct": sum(r["expected_ok"] == r["got_ok"] for r in res), "detail": res}


def eval_nightly_replay(nights: int = 47):
    """Run the full close every night for the last `nights` days, as of 11:10 pm each night."""
    from gondola import pipeline
    from gondola.connectors.ingest import ingest
    from gondola.storage import Bucket
    from gondola.tools.sentinel import Notifier
    from gondola.tools.summary import monthly_summary
    work = OUT / "replay"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    pipeline.OUT = work
    bucket = Bucket(work / "bucket")
    notifier = Notifier(work / "outbox.jsonl")
    end = pd.Timestamp("2026-11-05")
    days = pd.date_range(end - pd.Timedelta(days=nights - 1), end)
    rows = []
    for d in days:
        ds = str(d.date())
        db = work / f"night_{ds}.duckdb"
        ingest(db_path=db, upto=ds)  # the store's data as it existed that night
        r = pipeline.run_close(ds, db=db, notifier=notifier, bucket=bucket)
        bucket.apply_lifecycle(datetime.fromisoformat(r["as_of"]))
        if d.day == 1:  # monthly summary for the previous month
            prev = (d - pd.Timedelta(days=1)).strftime("%Y-%m")
            st = Store(db)
            bucket.put_monthly(prev, monthly_summary(st, prev, json.loads((work / "closes.json").read_text())), d.to_pydatetime())
        prev_db = work / f"night_{(d - pd.Timedelta(days=2)).date()}.duckdb"
        prev_db.unlink(missing_ok=True)
        rows.append({"date": ds, "status": r["status"], "seconds": r["seconds"],
                     "urgent": sum(1 for f in r["findings"] if f.get("urgency") == "urgent"),
                     "sms": len([a for a in r["alerts"] if a.get("status") in ("sent", "dry_run")]),
                     "failed_steps": [s["step"] for s in r["log"] if s["status"] == "failed"], "cross_check": r["cross_check"]})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "nightly_replay.csv", index=False)
    idx = bucket.index
    st_counts = pd.Series([v["status"] for k, v in idx.items() if v["kind"] == "daily"]).value_counts().to_dict()
    # retrieval
    old = str((end - pd.Timedelta(days=40)).date())
    from gondola.report.render import render_report
    rebuilt = bucket.get(old, rebuild=lambda ctx, d: Path(render_report({**ctx, "rebuilt": "Nov 5"}, work / "rebuilt", d)["pdf"]),
                         now=end.to_pydatetime())
    recent = bucket.get(str((end - pd.Timedelta(days=3)).date()))
    R["nightly_replay"] = {"nights": nights, "done": int((df.status == "done").sum()), "partial": int((df.status == "partial").sum()),
                           "seconds_median": float(df.seconds.median()), "seconds_max": float(df.seconds.max()),
                           "nights_with_sms": int((df.sms > 0).sum()), "sms_total": int(df.sms.sum()),
                           "cross_check_issues": int(df.cross_check.map(len).sum()),
                           "bucket_daily_status": st_counts, "bucket_bytes": bucket.usage_bytes(),
                           "monthly_summaries": [k for k in idx if k.startswith("monthly/")],
                           "retrieve_recent": recent["status"], "retrieve_40_days_old": rebuilt["status"]}
    pipeline.OUT = OUT


def eval_robustness():
    """Failure injection, idempotency, quiet hours, opt-out."""
    from gondola import pipeline
    from gondola.tools.sentinel import Notifier
    work = OUT / "robust"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    pipeline.OUT = work
    res = {}
    for step in ("books", "stock", "demand", "analyst", "report"):
        if (work / "closes.json").exists():
            (work / "closes.json").unlink()
        nt = Notifier(work / f"outbox_{step}.jsonl")
        r = pipeline.run_close("2026-11-05", fail={step}, notifier=nt, render=(step != "report"))
        sms = [a for a in r["alerts"]]
        res[step] = {"status": r["status"], "finished": r.get("report") is not None or step == "report",
                     "failure_text_sent": any("didn't finish" in (a.get("body") or "") for a in sms),
                     "other_steps_done": [s["step"] for s in r["log"] if s["status"] == "done"]}
    (work / "closes.json").unlink()
    nt = Notifier(work / "outbox_idem.jsonl")
    t0 = time.perf_counter(); r1 = pipeline.run_close("2026-11-05", notifier=nt, render=False)
    r2 = pipeline.run_close("2026-11-05", notifier=nt, render=False)
    res["idempotent_second_tap"] = {"hit": bool(r2.get("idempotent_hit")), "sms_after_two_taps": sum(1 for l in (work / "outbox_idem.jsonl").read_text().splitlines())}
    (work / "closes.json").unlink()
    nq = Notifier(work / "outbox_quiet.jsonl")
    r3 = pipeline.run_close("2026-11-05", notifier=nq, render=False, as_of=datetime(2026, 11, 6, 1, 40))
    res["close_at_1_40am"] = [a.get("status") for a in r3["alerts"]]
    (work / "closes.json").unlink()
    no = Notifier(work / "outbox_noopt.jsonl", opted_in=False)
    r4 = pipeline.run_close("2026-11-05", notifier=no, render=False)
    res["no_opt_in"] = [a.get("status") for a in r4["alerts"]]
    R["robustness"] = res
    pipeline.OUT = OUT


def eval_adk():
    try:
        from gondola.agents.adk_graph import build_close_graph, build_ask_agent
        g = build_close_graph()
        names = []
        def walk(a, depth=0):
            names.append(("  " * depth) + a.name)
            for s in getattr(a, "sub_agents", []) or []:
                walk(s, depth + 1)
        walk(g)
        build_ask_agent()
        R["adk_graph"] = {"built": True, "tree": names}
    except Exception as e:
        R["adk_graph"] = {"built": False, "error": str(e)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--quick", action="store_true"); a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    st = Store()
    data = {"orders": int(st.df("SELECT COUNT(*) n FROM orders").n[0]), "order_lines": int(st.df("SELECT COUNT(*) n FROM order_lines").n[0]),
            "payout_lines": int(st.df("SELECT COUNT(*) n FROM payout_lines").n[0]), "days": int(st.df("SELECT COUNT(DISTINCT business_date) n FROM orders").n[0]),
            "planted_anomalies": int(len(pd.read_csv(TRUTH / "anomalies.csv")))}
    R["data"] = data
    for name, fn in [("books", eval_books), ("stock", eval_stock), ("forecast", eval_forecast), ("plan", eval_plan_and_guard),
                     ("guard_errors", eval_guard_errors), ("ask", eval_ask)]:
        t = time.perf_counter(); fn(st); print(f"{name:10s} {time.perf_counter() - t:6.1f}s", flush=True)
    eval_guardrails(); eval_adk()
    t = time.perf_counter(); eval_robustness(); print(f"robustness {time.perf_counter() - t:6.1f}s", flush=True)
    (OUT / "eval.json").write_text(json.dumps(R, indent=1, default=str))
    if not a.quick:
        t = time.perf_counter(); eval_nightly_replay(); print(f"replay     {time.perf_counter() - t:6.1f}s", flush=True)
    (OUT / "eval.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps(R, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
