"""Gondola web API. Contract: docs/app_contract.md."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from .. import NP
from ..agents.ask import ask as ask_fn
from ..metrics import ROOT, Store
from ..tools import analyst, demand, sentinel
from . import guard_live, v3, rush, flex, orders
from .security import demo_security
from .runs import RUNS, new_run, stream

VERSION = "3.0.0"
DB = ROOT / "data" / "gondola.duckdb"
WEB = ROOT / "web" / "dist"
STORE_INFO = {"id": "hanabi-sqh", "name": "Hanabi Ramen", "address": "Murray Ave, Squirrel Hill, Pittsburgh PA",
              "limited_items": ["Chashu"]}
CLOSE_LOCK = threading.Lock()

app = FastAPI(title="Gondola", version=VERSION)
app.middleware("http")(demo_security)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(v3.router)  # /api/live/stream, /api/metrics/intraday|items|range, /api/day/{date}
app.include_router(rush.router)
from . import tri  # noqa: E402
app.include_router(tri.router)  # Past / Present / Future / Review
app.include_router(flex.router)
app.include_router(orders.router)


def out_dir() -> Path:
    from .. import pipeline
    return Path(pipeline.OUT)


def store() -> Store:
    """The database as of now (today cut at the current minute; gondola/now.py)."""
    return Store(DB, cut=v3.cut())


@app.on_event("startup")
def _startup():
    if not DB.exists():
        from ..setup import ensure_data
        ensure_data()


@app.exception_handler(HTTPException)
async def _http_err(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail if isinstance(exc.detail, str) else "error", "detail": exc.detail},
                        status_code=exc.status_code, headers=exc.headers)


def _date(d: str | None) -> str:
    if not d:
        return v3.today()
    try:
        return str(pd.Timestamp(d).date())
    except Exception:
        raise HTTPException(400, f"bad date '{d}'")


def _sse(run) -> StreamingResponse:
    return StreamingResponse(stream(run), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ basics
@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/api/now")
def now_info():
    """The store clock: real time in America/New_York mapped onto the data (gondola/now.py)."""
    from .. import now
    return now.info(DB)


@app.get("/api/store")
def store_info():
    st = store()
    today = pd.Timestamp(v3.today())
    first = pd.Timestamp(st.df("SELECT min(business_date) d FROM orders").d[0])
    return {**STORE_INFO, "today": str(today.date()), "tomorrow": str((today + pd.Timedelta(days=1)).date()),
            "first_date": str(first.date())}


@app.get("/api/integrations")
def integrations():
    try:  # the integrations module (if present) knows best
        from .. import config  # type: ignore
        if hasattr(config, "integrations_status"):
            return config.integrations_status()
    except Exception:
        pass
    env = os.getenv
    llm = bool(env("GOOGLE_API_KEY") or env("ANTHROPIC_API_KEY"))
    return {"twilio": {"live": bool(env("TWILIO_ACCOUNT_SID") and env("TWILIO_AUTH_TOKEN"))},
            "sendgrid": {"live": bool(env("SENDGRID_API_KEY"))},
            "llm": {"live": llm, "model": env("GONDOLA_MODEL") if llm else None},
            "square": {"live": bool(env("SQUARE_ACCESS_TOKEN"))},
            "doordash": {"live": bool(env("DOORDASH_DEVELOPER_ID") and env("DOORDASH_KEY_ID"))}}


# ------------------------------------------------------------------ overview and metrics
def _curve(st: Store, dates: list[str], slots=range(44, 92)) -> list[dict]:
    if not dates:
        return []
    q = """SELECT business_date, extract(hour FROM created_at)*4 + extract(minute FROM created_at)//15 AS slot, COUNT(*) n
           FROM orders WHERE business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1,2"""
    x = st.df(q, [dates])
    prof = x.groupby("slot").n.sum() / len(dates)
    prof = prof.reindex(slots, fill_value=0)
    return [{"time": f"{int(s)//4:02d}:{int(s)%4*15:02d}", "orders": round(float(v), 2)} for s, v in prof.items()]


def _last_close() -> dict | None:
    p = out_dir() / "closes.json"
    if not p.exists():
        return None
    st = json.loads(p.read_text(encoding="utf-8"))
    dates = sorted(k for k in st if not k.startswith("_"))
    if not dates:
        return None
    d = dates[-1]
    f = out_dir() / f"close_{d}.json"
    fin = datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds") if f.exists() else None
    return {"date": d, "status": st[d].get("status"), "finished_at": fin}


@app.get("/api/overview")
def overview(date: str | None = None):
    d = _date(date)
    return {**v3.cached("overview", _overview_core, d), "last_close": _last_close()}


def _overview_core(d: str) -> dict:
    st = store()
    daily = v3.daily_frame()
    row = daily[daily.business_date == pd.Timestamp(d)]
    slots, as_of = v3.slots_for(d)
    if row.empty or float(row.orders.iloc[0]) == 0:
        cal = st.df("SELECT holiday FROM calendar WHERE date = ?", [d])
        h = cal.holiday[0] if len(cal) and isinstance(cal.holiday[0], str) else None
        ni = now_info()
        not_open = d == ni["today"] and ni["phase"] == "before_open"
        return {"date": d, "closed": True, "not_open_yet": not_open, "opens": ni["open"] if not_open else None, "as_of": as_of, "kpis": None, "vs_usual": None, "context": {"rain": False, "events": [h] if h else []},
                "curve_today": [], "curve_usual": [], "channels": []}
    r = row.iloc[0]
    cmp_ = analyst.compare_periods(st, d, daily=daily)
    ex = analyst.explain_change(st, d)
    kpis = {"net_sales": round(float(r.net_sales), 2), "orders": int(r.orders), "avg_ticket": round(float(r.avg_ticket), 2),
            "labour_pct": round(float(r.labour_pct), 4) if r.labour_pct == r.labour_pct else None,
            "cancels": int(r.cancels), "avoidable_cancels": int(r.avoidable_cancels)}
    vs = {f"{m}_pct": (cmp_.get(m) or {}).get("change_pct") for m in ("net_sales", "orders", "avg_ticket", "labour_pct", "cancels")}
    return {"date": d, "closed": False, "as_of": as_of, "kpis": kpis, "vs_usual": vs, "baseline_dates": cmp_.get("baseline_dates", []),
            "context": {"rain": bool(ex["context"].get("rain")), "events": ex["context"].get("events", [])},
            "curve_today": _curve(st, [d], slots), "curve_usual": _curve(st, cmp_.get("baseline_dates", [])),
            "channels": ex.get("channel", [])}


@app.get("/api/metrics/daily")
def metrics_daily(start: str | None = None, end: str | None = None):
    e = _date(end)
    s = _date(start) if start else str((pd.Timestamp(e) - pd.Timedelta(days=89)).date())
    df = v3.daily_frame()
    df = df[(df.business_date >= pd.Timestamp(s)) & (df.business_date <= pd.Timestamp(e))]
    out = []
    for r in df.itertuples():
        out.append({"date": str(r.business_date.date()), "orders": int(r.orders), "net_sales": round(float(r.net_sales), 2),
                    "avg_ticket": round(float(r.avg_ticket), 2) if r.orders else None,
                    "labour_pct": round(float(r.labour_pct), 4) if r.labour_pct == r.labour_pct else None,
                    "cancels": int(r.cancels), "avoidable_cancels": int(r.avoidable_cancels), "rain": bool(r.rain),
                    "events": [x for x in str(r.events).split("; ") if x and x != "None" and x != "nan"]})
    return out


_FC_CACHE: dict = {}


@app.get("/api/forecast")
def forecast(date: str | None = None):
    st = Store(DB, cut=(v3.today(), None))  # the forecast plans from whole days: today counts in full
    d = _date(date) if date else str((pd.Timestamp(v3.today()) + pd.Timedelta(days=1)).date())
    if d in _FC_CACHE:
        return _FC_CACHE[d]
    bt = None
    cache = out_dir() / "backtest_cache.csv"
    if cache.exists():
        b = pd.read_csv(cache)
        b = b[b.date.astype(str) < d].tail(60)
        if len(b) >= 20:
            bt = b
    fc = demand.run_forecast(st, d, bt)
    res = {"date": d, "p10": fc["p10"], "p50": fc["p50"], "p90": fc["p90"], "rush": fc["rush"],
           "curve": [{"time": c["time"], "orders": c["orders"]} for c in fc["curve"]],
           "similar_days": [{"date": s["date"], "orders": s["orders"], "why": s["why"]} for s in fc["similar_days"]],
           "model": fc["model"]}
    _FC_CACHE[d] = res
    return res


# ------------------------------------------------------------------ close
@app.post("/api/close")
async def start_close(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    d = _date(body.get("date"))
    ni = now_info()
    if d > ni["today"]:
        raise HTTPException(400, f"{d} has not happened yet")
    if d == ni["today"] and ni["phase"] != "closed":
        h, m = int(ni["close"][:2]), int(ni["close"][3:])
        raise HTTPException(409, f"The store is open until {h % 12 or 12}:{m:02d} {'pm' if h >= 12 else 'am'}; "
                                 f"tonight's close unlocks then.")
    pc = body.get("portion_counts")
    force = bool(body.get("force", False))
    run = new_run("close")

    def work():
        from .. import pipeline
        with CLOSE_LOCK:
            try:
                res = pipeline.run_close(d, db=DB, force=force, portion_counts=pc, on_event=run.emit)
                if res.get("idempotent_hit"):
                    for s_ in res.get("log", []):
                        run.emit("step", {"step": s_["step"], "status": s_["status"], "seconds": s_.get("seconds"),
                                          "message": s_.get("error")})
                    for f in res.get("findings", []):
                        run.emit("finding", {"kind": f.get("kind"), "title": f.get("title") or f.get("kind"),
                                             "urgency": f.get("urgency") or sentinel.score_urgency(f)})
                run.emit("done", {"status": res.get("status"), "seconds": res.get("seconds"), "date": d,
                                  "idempotent": bool(res.get("idempotent_hit"))})
            except Exception:
                run.emit("done", {"status": "failed", "error": "Close failed", "date": d})

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run.id, "date": d}


@app.get("/api/close/{run_id}/events")
def close_events(run_id: str):
    run = RUNS.get(run_id)
    if not run or run.kind != "close":
        raise HTTPException(404, "unknown run")
    return _sse(run)


def _valid_approval(d: str, rec: dict, f: Path) -> dict | None:
    """The approval for this date, only if it was made for the current run of the close (a forced re-run makes a
    new plan, so the old approval and its card no longer apply)."""
    a = _approvals().get(d)
    if not a:
        return None
    if a.get("for_run") is not None or rec.get("run_id") is not None:
        return a if a.get("for_run") == rec.get("run_id") else None
    try:  # older approvals: valid only if made after the close file was written
        return a if datetime.fromisoformat(a["approved_at"]).timestamp() >= f.stat().st_mtime - 1 else None
    except Exception:  # noqa: BLE001
        return None


def _approvals() -> dict:
    p = out_dir() / "approvals.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@app.get("/api/closes")
def closes():
    p = out_dir() / "closes.json"
    if not p.exists():
        return []
    st = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for d in sorted((k for k in st if not k.startswith("_")), reverse=True):
        v = st[d]
        fs = v.get("findings", [])
        out.append({"date": d, "status": v.get("status"), "seconds": v.get("seconds"), "findings_count": len(fs),
                    "urgent_count": sum(1 for f in fs if f.get("urgency") == "urgent")})
    return out


@app.get("/api/closes/{date}")
def close_detail(date: str):
    d = _date(date)
    f = out_dir() / f"close_{d}.json"
    if not f.exists():
        raise HTTPException(404, f"no close for {d}")
    r = json.loads(f.read_text(encoding="utf-8"))
    state = json.loads((out_dir() / "closes.json").read_text(encoding="utf-8")).get(d, {}) if (out_dir() / "closes.json").exists() else {}
    books = r.get("books") or {}
    disputes = []
    for v in books.get("verified", []):
        for fd in v.get("findings", []):
            if fd.get("kind") == "error_charge_disputable":
                left = 14 - (pd.Timestamp(d) - pd.Timestamp(v["date"])).days
                disputes.append({"channel": fd.get("channel"), "order": (fd.get("evidence") or [None])[0],
                                 "amount": fd.get("impact_usd"), "reason": (fd.get("detail") or {}).get("reason"),
                                 "days_left": left, "for_date": v["date"]})
    disputes.sort(key=lambda x: (x["days_left"], -(x["amount"] or 0)))
    if disputes:  # what was on each order, for the copy-evidence text
        try:
            ids = [x["order"] for x in disputes if x["order"]]
            lines = store().df("SELECT order_id, item FROM order_lines WHERE order_id IN (SELECT unnest(?::VARCHAR[]))", [ids])
            items = lines.groupby("order_id").item.apply(list).to_dict()
        except Exception:  # noqa: BLE001
            items = {}
        for x in disputes:
            x["date"] = x["for_date"]
            x["items"] = items.get(x["order"], [])
    plan = r.get("plan") or {}
    appr = _valid_approval(d, r, f)
    fc = r.get("demand") or {}
    return {"date": d, "status": r.get("status", state.get("status")), "seconds": r.get("seconds", state.get("seconds")),
            "log": r.get("log", []), "findings": r.get("findings", []), "alerts": r.get("alerts", []),
            "card": (appr or {}).get("card") or plan.get("card", []),
            "books": {"cash": books.get("cash"), "verified": [{"date": v["date"], "channels": v["channels"]} for v in books.get("verified", [])],
                      "estimate_today": books.get("estimate_today", []), "money": books.get("money")},
            "disputes": disputes,
            "demand": {k: fc.get(k) for k in ("date", "p10", "p50", "p90", "rush")} if fc else None,
            "sold_out": r.get("sold_out"), "approved": bool(appr),
            "agents": _agents_view(r.get("agents"))}


def _agents_view(ag: dict | None) -> dict | None:
    """Agent mode only: what each ADK agent wrote (already number-checked), for the Close screen."""
    if not ag:
        return None
    return {"mode": ag.get("mode"), "model": ag.get("model"), "error": ag.get("error"), "outputs": ag.get("outputs") or {},
            "invoked": ag.get("invoked") or [], "tool_calls": len(ag.get("tool_calls") or []),
            "blocked": sorted((ag.get("guardrail_blocked") or {}).keys()),
            "report_used": bool((ag.get("report_check") or {}).get("ok"))}


@app.post("/api/closes/{date}/approve")
async def approve(date: str, request: Request):
    d = _date(date)
    try:
        body = await request.json()
    except Exception:
        body = {}
    f = out_dir() / f"close_{d}.json"
    if not f.exists():
        raise HTTPException(404, f"no close for {d}")
    rec = json.loads(f.read_text(encoding="utf-8"))
    card = body.get("card") or (rec.get("plan") or {}).get("card", [])
    for c in card:
        if "prep" in c and (not isinstance(c["prep"], (int, float)) or c["prep"] < 0):
            raise HTTPException(400, "prep must be a non-negative number")
    ap = _approvals()
    ap[d] = {"card": card, "approved_at": datetime.now().isoformat(timespec="seconds"), "for_run": rec.get("run_id")}
    (out_dir() / "approvals.json").write_text(json.dumps(ap, indent=1), encoding="utf-8")
    return {"approved": True, "card": card}


# ------------------------------------------------------------------ reports
REPORT_LOCK = threading.Lock()  # rebuilds write the bucket index: one at a time
_META_CACHE: dict = {}


def _bucket():
    from ..storage import Bucket
    return Bucket(out_dir() / "bucket")


def _json_cached(p: Path | None):
    """Parse a JSON file once per version (mtime)."""
    if p is None or not p.exists():
        return None
    k = (str(p), p.stat().st_mtime_ns)
    if k not in _META_CACHE:
        if len(_META_CACHE) > 2000:
            _META_CACHE.clear()
        try:
            _META_CACHE[k] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            _META_CACHE[k] = None
    return _META_CACHE[k]


def _close_state() -> dict:
    return _json_cached(out_dir() / "closes.json") or {}


def _daily_facts(d: str, ctx: dict | None, state: dict) -> dict:
    """headline, net_sales, orders, vs_usual_pct, urgent, texted, recoverable_usd for one night: from findings.json
    (meta, written by the close) or, for older reports, from closes.json and the close file."""
    ctx = ctx or {}
    m = dict(ctx.get("meta") or {})
    if not m:
        fs = (state.get(d) or {}).get("findings", [])
        rec = _json_cached(out_dir() / f"close_{d}.json") or {}
        money = (rec.get("books") or {}).get("money") or {}
        sent = lambda x: (x.get("original_status") if x.get("status") == "duplicate_suppressed" else x.get("status")) in ("sent", "dry_run")
        m = {"net_sales": money.get("net_sales"), "orders": money.get("orders"),
             "vs_usual_pct": (((rec.get("analyst") or {}).get("compare") or {}).get("net_sales") or {}).get("change_pct"),
             "urgent": sum(1 for f in fs if f.get("urgency") == "urgent"),
             "texted": any(x.get("channel", "sms") == "sms" and sent(x) for x in rec.get("alerts") or []),
             "recoverable_usd": round(sum(f.get("recoverable_usd") or 0 for f in fs if f.get("kind") == "payout_short"), 2)}
    return {"headline": ctx.get("headline"), "net_sales": m.get("net_sales"), "orders": m.get("orders"),
            "vs_usual_pct": m.get("vs_usual_pct"), "urgent": int(m.get("urgent") or 0), "texted": bool(m.get("texted")),
            "recoverable_usd": round(float(m.get("recoverable_usd") or 0), 2)}


def _monthly_facts(sm: dict | None) -> dict:
    from ..tools.summary import monthly_headline
    sm = sm or {}
    al = sm.get("alerts") or {}
    return {"headline": monthly_headline(sm) if sm else None, "net_sales": sm.get("net_sales"), "orders": sm.get("orders"),
            "vs_usual_pct": sm.get("vs_prev_month_pct"), "urgent": int(sm.get("urgent_alerts") or 0),
            "texted": bool(al.get("texts")), "recoverable_usd": round(float(sm.get("recoverable_flagged_usd") or 0), 2),
            "month_name": sm.get("month_name")}


def _daily_status(b, rec: dict) -> str:
    st = rec.get("status")
    if st in ("stored", "rebuilt") and not b.path(rec["uri"]).exists():
        return "expired"  # a pending or lost PDF rebuilds on request, like an expired one
    return st


@app.get("/api/reports")
def reports():
    """Every report the store has: dailies (stored / expired / rebuilt) and monthly summaries, newest first."""
    out, seen = [], set()
    b = _bucket()
    state = _close_state()
    for k, rec in b.index.items():
        d = rec["period"]
        if rec["kind"] == "daily":
            if rec.get("status") == "purged":
                continue
            row = {"date": d, "kind": "daily", "status": _daily_status(b, rec), "url": f"/api/reports/{d}.pdf",
                   "url_html": f"/api/reports/{d}.html", "url_pdf": f"/api/reports/{d}.pdf",
                   **_daily_facts(d, _json_cached(b.path(rec["findings"])), state), "_key": d}
            seen.add(d)
        else:
            row = {"date": d, "kind": "monthly", "status": rec.get("status", "stored"), "url": f"/api/reports/monthly/{d}.pdf",
                   "url_html": f"/api/reports/monthly/{d}.html", "url_pdf": f"/api/reports/monthly/{d}.pdf",
                   **_monthly_facts(b.monthly_summary(d)),
                   "_key": str((pd.Timestamp(d + "-01") + pd.offsets.MonthBegin(1)).date()) + "~"}  # above that 1st's daily
        out.append(row)
    rd = out_dir() / "reports"
    if rd.exists():  # reports rendered outside the bucket (older closes)
        for p in rd.glob("*.pdf"):
            if p.stem not in seen and len(p.stem) == 10:
                out.append({"date": p.stem, "kind": "daily", "status": "stored", "url": f"/api/reports/{p.stem}.pdf",
                            "url_html": f"/api/reports/{p.stem}.html", "url_pdf": f"/api/reports/{p.stem}.pdf",
                            **_daily_facts(p.stem, _json_cached(rd / f"{p.stem}.findings.json"), state), "_key": p.stem})
    out.sort(key=lambda x: x.pop("_key"), reverse=True)
    return out


def report_ref(d: str) -> dict | None:
    """{status, url_html, url_pdf} for a night's report, or None (used by /api/day)."""
    b = _bucket()
    rec = b.index.get(f"daily/{d}")
    if rec:
        return {"status": _daily_status(b, rec), "url_html": f"/api/reports/{d}.html", "url_pdf": f"/api/reports/{d}.pdf"}
    if (out_dir() / "reports" / f"{d}.pdf").exists():
        return {"status": "stored", "url_html": f"/api/reports/{d}.html", "url_pdf": f"/api/reports/{d}.pdf"}
    return None


def _rebuild_daily(d: str):
    """Rebuild an expired (or missing) daily PDF + HTML exactly from its findings.json; the bucket marks it rebuilt."""
    from ..report.render import render_report

    def build(ctx, dd):
        ctx = {k: v for k, v in ctx.items() if k != "font_face"}
        return Path(render_report({**ctx, "rebuilt": datetime.now().strftime(f"%b %{NP}d")}, out_dir() / "rebuilt", dd)["pdf"])
    with REPORT_LOCK:
        b = _bucket()  # re-read the index inside the lock: another request may have just rebuilt it
        rec = b.index.get(f"daily/{d}")
        if rec and b.path(rec["uri"]).exists() and rec.get("status") in ("stored", "rebuilt"):
            return b, rec
        r = b.get(d, rebuild=build)
        return b, b.index.get(f"daily/{d}") if r.get("status") == "rebuilt" else None


def _daily_file(d: str, kind: str) -> Path:
    b = _bucket()
    rec = b.index.get(f"daily/{d}")
    if rec:
        p = b.path(rec["uri"]) if kind == "pdf" else (b.path(rec["html"]) if rec.get("html") else None)
        if rec.get("status") in ("stored", "rebuilt") and p is not None and p.exists():
            return p
        b, rec = _rebuild_daily(d)
        if rec:
            p = b.path(rec["uri"]) if kind == "pdf" else (b.path(rec["html"]) if rec.get("html") else None)
            if p is not None and p.exists():
                return p
    p = out_dir() / "reports" / f"{d}.{kind}"
    if p.exists():
        return p
    raise HTTPException(404, f"no report for {d}")


@app.get("/api/reports/{date}.pdf")
def report_pdf(date: str):
    d = _date(date)
    return FileResponse(_daily_file(d, "pdf"), media_type="application/pdf", filename=f"Gondola close {d}.pdf")


@app.get("/api/reports/{date}.html")
def report_html(date: str):
    d = _date(date)
    return HTMLResponse(_daily_file(d, "html").read_text(encoding="utf-8"))


def _month(m: str) -> str:
    import re
    if not re.fullmatch(r"\d{4}-\d{2}", m or "") or not 1 <= int(m[5:]) <= 12:
        raise HTTPException(400, f"bad month '{m}' (use YYYY-MM)")
    return m


def _monthly_file(m: str, kind: str) -> Path:
    """The monthly report from the bucket; rendered from the stored summary if the file is missing."""
    b = _bucket()
    rec = b.index.get(f"monthly/{m}")
    if not rec:
        raise HTTPException(404, f"no monthly summary for {m}")
    p = b.path(rec["uri"]) if kind == "pdf" else (b.path(rec["html"]) if rec.get("html") else None)
    if p is not None and p.exists():
        return p
    sm = b.monthly_summary(m)
    if not sm:
        raise HTTPException(404, f"no monthly summary for {m}")
    from .. import pipeline
    from ..report.render import render_monthly
    from ..tools.summary import monthly_report_context
    with REPORT_LOCK:
        ctx = monthly_report_context(sm, pipeline.STORE_NAME, generated=datetime.now().strftime(f"%b %{NP}d %{NP}I:%M %p"))
        r = render_monthly(ctx, out_dir() / "rebuilt" / "monthly", m, pdf=(kind == "pdf"))
        b = _bucket()
        b.put_monthly(m, sm, datetime.fromisoformat(rec["created_at"]), html=Path(r["html"]),
                      pdf=Path(r["pdf"]) if r.get("pdf") else None)
        rec = b.index[f"monthly/{m}"]
    p = b.path(rec["uri"]) if kind == "pdf" else b.path(rec["html"])
    if p is None or not p.exists():
        raise HTTPException(500, f"could not render the {m} summary")
    return p


@app.get("/api/reports/monthly/{month}.pdf")
def monthly_pdf(month: str):
    m = _month(month)
    return FileResponse(_monthly_file(m, "pdf"), media_type="application/pdf", filename=f"Gondola summary {m}.pdf")


@app.get("/api/reports/monthly/{month}.html")
def monthly_html(month: str):
    m = _month(month)
    return HTMLResponse(_monthly_file(m, "html").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ ask
def _chart_for(st: Store, a) -> dict | None:
    try:
        if not a.calls or a.clarify:
            return None
        call = a.calls[0]
        data = a.data
        if call[0] == "query_metric" and isinstance(data, dict) and "start" in data and data.get("start") != data.get("end"):
            m = data["metric"]
            if m in ("labour_pct", "card_fees", "tips"):
                return None
            df = st.query_metric(m, data["start"], data["end"], "day", data.get("channel"))
            return {"type": "line", "x": [str(pd.Timestamp(k).date()) for k in df.key],
                    "series": [{"name": m, "values": [round(float(v), 2) for v in df.value]}]}
        if call[0] == "query_metric" and isinstance(data, dict) and data and all(k in ("doordash", "ubereats", "grubhub", "in_store") for k in data):
            return {"type": "bar", "x": list(data.keys()), "series": [{"name": call[1], "values": [round(float(v), 2) for v in data.values()]}]}
        if call[0] == "run_forecast" and isinstance(data, dict) and "curve" in data:
            return {"type": "line", "x": [c["time"] for c in data["curve"]],
                    "series": [{"name": "forecast orders", "values": [round(c["orders"], 2) for c in data["curve"]]}]}
        if call[0] == "query_metric" and isinstance(data, list) and data and "key" in data[0] and isinstance(data[0]["key"], str) \
                and not data[0]["key"][:4].isdigit():
            return {"type": "bar", "x": [r["key"] for r in data], "series": [{"name": "sold", "values": [float(r["value"]) for r in data]}]}
    except Exception:
        return None
    return None


@app.post("/api/ask")
async def ask(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "send JSON {question}")
    q = (body.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "question is required")
    from starlette.concurrency import run_in_threadpool
    st = store()
    a, mode = await run_in_threadpool(_answer, st, q, body.get("today"))  # an agent-mode answer can take seconds
    return {"text": a.text, "clarify": a.clarify, "calls": [list(map(str, c)) for c in a.calls], "chart": _chart_for(st, a),
            "mode": mode}


def _answer(st: Store, q: str, today: str | None = None):
    """Offline router always runs (it gives the chart and the clarify decision). In agent mode the ADK Ask agent
    writes the text; if it fails or the guardrail blocks it, the router's text stays. Returns (Answer, mode)."""
    a = ask_fn(st, q, today)
    if a.clarify:
        return a, "offline"
    try:
        from ..config import agents_status
        if agents_status()["live"]:
            from ..integrations.llm import ask_llm
            txt = ask_llm(q, st, today=today, require_mode=True)
            if txt:
                a.text = txt
                return a, "adk"
    except Exception:  # noqa: BLE001
        pass
    return a, "offline"


# ------------------------------------------------------------------ outbox and SMS
def _outbox_path() -> Path:
    return out_dir() / "outbox.jsonl"


@app.get("/api/outbox")
def outbox():
    p = _outbox_path()
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        att = r.get("attachment")
        att_name = Path(str(att).replace("\\", "/")).name if att else None
        rows.append({"channel": r.get("channel"), "to": r.get("to"), "from": r.get("from"), "direction": r.get("direction", "out"),
                     "body": r.get("body"), "subject": r.get("subject"), "attachment": att_name,
                     "attachment_url": f"/api/reports/{att_name}" if att_name and att_name.endswith(".pdf") else None,
                     "status": r.get("status"), "ts": r.get("ts")})
    rows = list(reversed(rows))  # newest written first...
    rows.sort(key=lambda r: r.get("ts") or "", reverse=True)  # ...and newest by time (stable for equal ts)
    return rows


def _demo_now() -> str:
    """Timestamp for inbound texts and replies on the same clock as the close's messages. The close stamps its text
    with the close time (11:10 pm on the demo night, which may be in the future); a reply is stamped that close time
    plus the wall-clock time elapsed since the close ran, so the outbox reads in order. Without a close: now."""
    now = datetime.now()
    try:
        p = out_dir() / "closes.json"
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        dates = sorted(k for k in st if not k.startswith("_"))
        if dates:
            f = out_dir() / f"close_{dates[-1]}.json"
            as_of = datetime.fromisoformat(json.loads(f.read_text(encoding="utf-8"))["as_of"])
            elapsed = max(now.timestamp() - f.stat().st_mtime, 1.0)
            return datetime.fromtimestamp(as_of.timestamp() + elapsed).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        pass
    return now.isoformat(timespec="seconds")


def _append_outbox(rec: dict):
    p = _outbox_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _latest_urgent() -> list[dict]:
    p = out_dir() / "closes.json"
    if not p.exists():
        return []
    st = json.loads(p.read_text(encoding="utf-8"))
    dates = sorted(k for k in st if not k.startswith("_"))
    if not dates:
        return []
    return [f for f in st[dates[-1]].get("findings", []) if f.get("urgency") == "urgent"]


@app.post("/api/sms/inbound")
async def sms_inbound(request: Request, From: str = Form(""), Body: str = Form("")):
    from ..config import get_settings
    from ..integrations.twilio_sms import validate_signature
    s = get_settings()
    # Mock messages remain usable locally without credentials. A configured Twilio
    # webhook must use its fixed public HTTPS URL and an allowlisted sender.
    if s.twilio_auth_token:
        params = await request.form()
        url = s.public_base_url.rstrip("/") + "/api/sms/inbound"
        if (not s.public_base_url.startswith("https://") or request.url.query
                or any(len(params.getlist(k)) != 1 for k in params.keys())
                or From not in s.alert_sms_to
                or not validate_signature(s.twilio_auth_token, url, dict(params),
                                          request.headers.get("X-Twilio-Signature", ""))):
            raise HTTPException(403, "Invalid or unauthorized SMS webhook")
    body = (Body or "").strip()
    now = _demo_now()
    if body.isdigit() and 1 <= int(body) <= 3:
        urgent = _latest_urgent()
        k = int(body) - 1
        reply = (lambda s_: s_[:1].upper() + s_[1:])(sentinel.sms_text(urgent[k]).replace("Gondola: ", "")) if k < len(urgent) else "There's no item with that number in tonight's text."
    elif body.upper() in ("STOP", "HELP"):
        reply = "Gondola alerts: reply STOP to opt out. Questions: ask anything about your store, like 'sales yesterday'."
    else:
        try:
            reply = _answer(store(), body)[0].text if body else "Ask me anything about your store, like 'sales yesterday'."
        except Exception:
            reply = "Sorry, I couldn't answer that. Try 'sales yesterday'."
    _append_outbox({"key": f"in-{now}-{abs(hash(body)) % 10**8}", "channel": "sms", "direction": "in", "from": From, "to": None,
                    "body": body, "status": "received", "ts": now})
    _append_outbox({"key": f"reply-{now}-{abs(hash(reply)) % 10**8}", "channel": "sms", "direction": "out", "to": [From],
                    "body": reply, "status": "reply", "ts": now})
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(reply)}</Message></Response>'
    return Response(content=xml, media_type="application/xml")


# ------------------------------------------------------------------ guard live replay
@app.post("/api/guard/replay")
async def guard_replay(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    d = _date(body.get("date") or "2026-11-05")
    speed = float(body.get("speed", 60))
    err = float(body.get("count_error", 0.05))
    rc = bool(body.get("recount", True))
    start = body.get("start_time", "17:00")
    par = body.get("par")
    run = new_run("guard")
    threading.Thread(target=guard_live.run_replay, args=(run, DB, d, speed, err, rc, start, par), daemon=True).start()
    return {"run_id": run.id}


@app.get("/api/guard/{run_id}/events")
def guard_events(run_id: str):
    run = RUNS.get(run_id)
    if not run or run.kind != "guard":
        raise HTTPException(404, "unknown run")
    return _sse(run)


@app.post("/api/guard/{run_id}/recount")
async def guard_recount(run_id: str, request: Request):
    run = RUNS.get(run_id)
    if not run or run.kind != "guard":
        raise HTTPException(404, "unknown run")
    body = await request.json()
    try:
        c = float(body["count"])
    except Exception:
        raise HTTPException(400, "count must be a number")
    if c < 0:
        raise HTTPException(400, "count must be non-negative")
    run.inbox["recount"] = c
    return {"ok": True}


# ------------------------------------------------------------------ frontend
if WEB.exists():
    from fastapi.staticfiles import StaticFiles

    if (WEB / "assets").exists():
        app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        f = (WEB / path).resolve()
        if not f.is_relative_to(WEB.resolve()):
            raise HTTPException(404, "not found")
        if path and f.is_file():
            return FileResponse(f)
        index = (WEB / "index.html").resolve()
        if not index.is_relative_to(WEB.resolve()):
            raise HTTPException(404, "not found")
        return FileResponse(index)
else:
    @app.get("/")
    def root():
        return HTMLResponse("<p>Gondola API is running. Build the web app (cd web && npm run build) to serve the UI here.</p>")
