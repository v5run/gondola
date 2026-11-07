"""V3 endpoints: live service replay (SSE), drill-down metrics, day detail. Contract: docs/app_contract.md, "V3 additions".

Everything reads the real database (DuckDB, read-only). Results depend only on the data, so they are cached per
database file version (its mtime): the first call for a date computes, later calls are dictionary lookups.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from .. import clock
from .. import now as wallclock
from ..metrics import ROOT, Store
from ..tools import analyst, plan
from .runs import sse_format

router = APIRouter(prefix="/api")
DB = ROOT / "data" / "gondola.duckdb"
CHANNELS = ["in_store", "doordash", "ubereats", "grubhub"]
APPS = ["doordash", "ubereats", "grubhub"]
APP_NAME = {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub", "in_store": "In-store"}
SLOTS = range(44, 92)  # 15-minute bins 11:00 .. 22:45 (every order falls in service hours)
BUFFER, APP_SHARE = 8.0, 0.66  # same pause rule as Guard (api/guard_live.py, tools/guard.py)

# ------------------------------------------------------------------ cache
_CACHE: OrderedDict = OrderedDict()
_CLOCK = threading.Lock()
_INFLIGHT: dict = {}


def _db_version() -> int:
    try:
        return DB.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


UNCUT = {"timeline"}  # computed from the whole day (the live stream paces it in real time)


def cut() -> tuple[str, str | None]:
    """(today, cutoff) of the store clock (gondola/now.py)."""
    return wallclock.cut(DB)


def today() -> str:
    return cut()[0]


def _cut_key(name: str, args: tuple):
    """The clock only matters for results that can see today: no date args, or a date arg on/after today."""
    if name in UNCUT:
        return None
    t, hm = cut()
    if not args or any(isinstance(a, str) and len(a) == 10 and a[4] == "-" and a >= t for a in args):
        return (t, hm)
    return None


def cached(name: str, fn, *args, maxsize: int = 512):
    """fn(*args), memoized per database version (and per clock minute when today is involved). Concurrent first
    calls for one key compute once."""
    key = (name, _db_version(), _cut_key(name, args)) + tuple(args)
    with _CLOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        ev = _INFLIGHT.get(key)
        owner = ev is None
        if owner:
            ev = _INFLIGHT[key] = threading.Event()
    if not owner:
        ev.wait(120)
        with _CLOCK:
            if key in _CACHE:
                return _CACHE[key]
    try:
        val = fn(*args)
        with _CLOCK:
            _CACHE[key] = val
            while len(_CACHE) > maxsize:
                _CACHE.popitem(last=False)
        return val
    finally:
        if owner:
            with _CLOCK:
                _INFLIGHT.pop(key, None)
            ev.set()


def store() -> Store:
    """The database as of now: today cut at the current minute (see Store(cut=...))."""
    return Store(DB, cut=cut())


def daily_frame() -> pd.DataFrame:
    """The daily frame (one row per business day), computed once per database version. Treat as read-only."""
    return cached("daily_frame", lambda: store().daily_frame())


def _date(d: str | None) -> str:
    if not d:
        return today()
    try:
        return str(pd.Timestamp(d).date())
    except Exception:
        raise HTTPException(400, f"bad date '{d}'")


def _events(x) -> list[str]:
    return [e for e in str(x).split("; ") if e and e not in ("None", "nan")]


def _r2(x) -> float:
    return round(float(x), 2)


# ------------------------------------------------------------------ /metrics/intraday
def _baseline(d: str) -> list[str]:
    try:
        return analyst.compare_periods(store(), d, daily=daily_frame()).get("baseline_dates", [])
    except Exception:  # noqa: BLE001 - early history has no baseline
        return []


def _slot_frame(dates: list[str], source: Store | None = None) -> pd.DataFrame:
    if not dates:
        return pd.DataFrame(columns=["business_date", "slot", "channel", "status", "n", "s"])
    q = """SELECT business_date, CAST(extract(hour FROM created_at)*4 + extract(minute FROM created_at)//15 AS INT) AS slot,
              channel, status, COUNT(*) n, SUM(subtotal) s
           FROM orders WHERE business_date IN (SELECT unnest(?::DATE[])) GROUP BY ALL"""
    return (source or store()).df(q, [dates])


def slots_for(d: str) -> tuple[range, str | None]:
    """The 15-minute bins that exist for d: today stops at the bin in progress (later bins are absent, not zero)."""
    t, hm = cut()
    if d != t or hm is None:
        return SLOTS, None
    m = int(hm[:2]) * 60 + int(hm[3:5])
    return range(SLOTS.start, max(SLOTS.start, min(SLOTS.stop, m // 15 + 1 if m % 15 else m // 15))), hm


def playback_cutoff(d: str, at: str) -> str:
    """Validate the playback time against the store clock before querying historical data."""
    sec = _parse_hm(at)
    current, cutoff = cut()
    if d > current or (d == current and cutoff is not None and sec > _parse_hm(cutoff)):
        raise HTTPException(400, "cannot replay past the store clock")
    return _hms(sec)[:5]


def intraday(d: str, at: str | None = None) -> dict:
    if at is None:
        x = _slot_frame([d])
        slots, as_of = slots_for(d)
    else:
        source = Store(DB, cut=(d, at))
        try:
            x = _slot_frame([d], source)
        finally:
            source.con.close()
        minute = _parse_hm(at) // 60
        slots = range(SLOTS.start, min(SLOTS.stop, (minute + 14) // 15))
        as_of = at
    c = x[x.status == "completed"]
    bins = []
    for s in slots:
        cs = c[c.slot == s]
        bins.append({"time": f"{s // 4:02d}:{s % 4 * 15:02d}", "orders": int(cs.n.sum()),
                     "by_channel": {ch: int(cs[cs.channel == ch].n.sum()) for ch in CHANNELS},
                     "net_sales": _r2(cs.s.sum()), "placed": int(x[x.slot == s].n.sum()),
                     "cancels": int(x[(x.slot == s) & (x.status == "cancelled")].n.sum())})
    if at is not None:
        base = [str(day.date()) for day in analyst.usual_weekdays(daily_frame(), pd.Timestamp(d)).business_date]
    else:
        base = _baseline(d) if len(x) else []
    usual = []
    if base:
        u = _slot_frame(base)
        u = u[u.status == "completed"].groupby("slot").n.sum() / len(base)
        usual = [{"time": f"{s // 4:02d}:{s % 4 * 15:02d}", "orders": round(float(u.get(s, 0.0)), 2)} for s in SLOTS]
    return {"date": d, "closed": not len(x), "bins": bins, "usual": usual, "baseline_dates": base, "as_of": as_of}


@router.get("/metrics/intraday")
async def metrics_intraday(date: str | None = None, at: str | None = None):
    d = _date(date)
    cutoff = playback_cutoff(d, at) if at is not None else None
    return await run_in_threadpool(cached, "intraday", intraday, d, cutoff)


# ------------------------------------------------------------------ /metrics/items
def items(s: str, e: str) -> list[dict]:
    q = """SELECT l.item, COUNT(*) sold, SUM(l.price) net_sales FROM orders o JOIN order_lines l USING(order_id)
           WHERE o.status = 'completed' AND o.business_date BETWEEN ? AND ? GROUP BY 1 ORDER BY 3 DESC, 1"""
    x = store().df(q, [s, e])
    tot = float(x.net_sales.sum()) or 1.0
    return [{"item": r.item, "sold": int(r.sold), "net_sales": _r2(r.net_sales), "share": round(float(r.net_sales) / tot, 4)}
            for r in x.itertuples()]


def _range_args(start: str | None, end: str | None, default_days: int = 30) -> tuple[str, str]:
    e = _date(end)
    s = _date(start) if start else str((pd.Timestamp(e) - pd.Timedelta(days=default_days - 1)).date())
    if pd.Timestamp(s) > pd.Timestamp(e):
        raise HTTPException(400, "start must be on or before end")
    return s, e


@router.get("/metrics/items")
async def metrics_items(start: str | None = None, end: str | None = None):
    s, e = _range_args(start, end)
    return await run_in_threadpool(cached, "items", items, s, e)


# ------------------------------------------------------------------ /metrics/range
def _period(s: str, e: str) -> dict:
    df = daily_frame()
    m = df[(df.business_date >= pd.Timestamp(s)) & (df.business_date <= pd.Timestamp(e))]
    o = m[m.orders > 0]
    ns, n = float(o.net_sales.sum()), int(o.orders.sum())
    lab = float(o.labour_cost.fillna(0).sum())
    return {"net_sales": _r2(ns), "orders": n, "avg_ticket": _r2(ns / n) if n else None,
            "labour_pct": round(lab / ns, 4) if ns else None, "cancels": int(o.cancels.sum()),
            "avoidable_cancels": int(o.avoidable_cancels.sum()), "open_days": int(len(o)), "_frame": o}


def _day_row(r) -> dict:
    return {"date": str(r.business_date.date()), "net_sales": _r2(r.net_sales), "orders": int(r.orders),
            "rain": bool(r.rain) if r.rain == r.rain else False, "events": _events(r.events)}


def range_metrics(s: str, e: str) -> dict:
    days = (pd.Timestamp(e) - pd.Timestamp(s)).days + 1
    cur = _period(s, e)
    pe = pd.Timestamp(s) - pd.Timedelta(days=1)
    ps = pe - pd.Timedelta(days=days - 1)
    first = daily_frame().business_date.min()
    prev = _period(str(ps.date()), str(pe.date())) if ps >= first else None  # a partial earlier period would mislead
    ch = store().df("SELECT channel, COUNT(*) n, SUM(subtotal) s FROM orders WHERE status='completed' AND business_date "
                    "BETWEEN ? AND ? GROUP BY 1", [s, e]).set_index("channel")
    o = cur.pop("_frame")
    pct = lambda a, b: round(float(a / b - 1), 4) if (prev and b) else None
    return {"start": s, "end": e, "days": days, **cur,
            "by_channel": {c: _r2(ch.s.get(c, 0.0)) if len(ch) else 0.0 for c in CHANNELS},
            "by_channel_orders": {c: int(ch.n.get(c, 0)) if len(ch) else 0 for c in CHANNELS},
            "vs_prev_pct": {"net_sales": pct(cur["net_sales"], prev["net_sales"]) if prev else None,
                            "orders": pct(cur["orders"], prev["orders"]) if prev else None},
            "prev": {"start": str(ps.date()), "end": str(pe.date()), "net_sales": prev["net_sales"], "orders": prev["orders"]} if prev else None,
            "best_day": _day_row(o.loc[o.net_sales.idxmax()]) if len(o) else None,
            "worst_day": _day_row(o.loc[o.net_sales.idxmin()]) if len(o) else None,
            "explain": range_explain(s, e)}


@router.get("/metrics/range")
async def metrics_range(start: str | None = None, end: str | None = None):
    s, e = _range_args(start, end)
    return await run_in_threadpool(cached, "range", range_metrics, s, e)


# ------------------------------------------------------------------ explain ("Why" breakdown)
_DAYPART = """CASE WHEN extract(hour FROM o.created_at) < 15 THEN 'lunch'
                   WHEN extract(hour FROM o.created_at) < 21 THEN 'dinner' ELSE 'late' END"""


def _drivers(cur: list[str], base: list[str], base_div: float) -> dict:
    """Sales by channel and daypart: `cur` dates summed vs `base` dates summed / base_div. Biggest drop first."""
    q = f"""SELECT o.business_date IN (SELECT unnest(?::DATE[])) AS cur, o.channel, {_DAYPART} AS daypart, SUM(o.subtotal) s
            FROM orders o WHERE o.status='completed' AND o.business_date IN (SELECT unnest(?::DATE[])) GROUP BY ALL"""
    x = store().df(q, [cur, cur + base])
    out = {}
    for dim in ("channel", "daypart"):
        t = x[x.cur].groupby(dim).s.sum()
        u = x[~x.cur].groupby(dim).s.sum() / max(base_div, 1)
        keys = sorted(set(t.index) | set(u.index), key=lambda k: float(t.get(k, 0) - u.get(k, 0)))
        out[dim] = [{"key": k, "today": _r2(t.get(k, 0)), "usual": _r2(u.get(k, 0)), "change": _r2(t.get(k, 0) - u.get(k, 0))}
                    for k in keys]
    return out


def _items_moves(cur: list[str], base: list[str], base_div: float, n: int = 3) -> tuple[list, list]:
    """Units sold per item, `cur` vs `base` (/ base_div): the top n up and top n down by unit change."""
    q = """SELECT o.business_date IN (SELECT unnest(?::DATE[])) AS cur, l.item, COUNT(*) n FROM orders o JOIN order_lines l
           USING(order_id) WHERE o.status='completed' AND o.business_date IN (SELECT unnest(?::DATE[])) GROUP BY ALL"""
    x = store().df(q, [cur, cur + base])
    t = x[x.cur].groupby("item").n.sum()
    u = x[~x.cur].groupby("item").n.sum() / max(base_div, 1)
    rows = [{"item": k, "today": int(t.get(k, 0)), "usual": round(float(u.get(k, 0)), 2),
             "change": round(float(t.get(k, 0) - u.get(k, 0)), 2)} for k in sorted(set(t.index) | set(u.index))]
    up = sorted((r for r in rows if r["change"] > 0), key=lambda r: (-r["change"], r["item"]))[:n]
    down = sorted((r for r in rows if r["change"] < 0), key=lambda r: (r["change"], r["item"]))[:n]
    return up, down


def _empty_explain(status: str, context: dict) -> dict:
    return {"status": status, "vs_usual": {"net_sales_pct": None, "orders_pct": None, "baseline_dates": []},
            "vs_similar": {"net_sales_pct": None, "dates": []}, "drivers": {"channel": [], "daypart": []},
            "context": context, "items_up": [], "items_down": []}


def day_explain(d: str) -> dict:
    """Why a day went the way it did: vs the usual same weekday (last 4, no holidays) and vs similar days, the
    channel/daypart drivers and context (analyst.explain_change), and the items that moved most vs the usual days."""
    st, daily = store(), daily_frame()
    cp = analyst.compare_periods(st, d, daily=daily)
    if cp.get("status") == "no_data":
        cal = st.df("SELECT rain, snow, temp_high_c, holiday FROM calendar WHERE date = ?", [d])
        ev = st.df("SELECT event FROM events WHERE date = ?", [d]).event.tolist()
        c = cal.iloc[0] if len(cal) else None
        h = c.holiday if c is not None and isinstance(c.holiday, str) else None
        return _empty_explain("closed", {"rain": bool(c.rain) if c is not None else False, "snow": bool(c.snow) if c is not None else False,
                                         "temp_high_c": float(c.temp_high_c) if c is not None else None,
                                         "events": ([h] if h else []) + ev})
    ex = analyst.explain_change(st, d, daily=daily, cp=cp)
    sim = analyst.compare_periods(st, d, baseline="similar_days", daily=daily)
    base = cp.get("baseline_dates", [])
    up, down = _items_moves([d], base, len(base)) if base else ([], [])
    ctx = ex.get("context") or {}
    return {"status": "ok" if base else "no_baseline",
            "vs_usual": {"net_sales_pct": (cp.get("net_sales") or {}).get("change_pct"),
                         "orders_pct": (cp.get("orders") or {}).get("change_pct"), "baseline_dates": base},
            "vs_similar": {"net_sales_pct": (sim.get("net_sales") or {}).get("change_pct"), "dates": sim.get("baseline_dates", [])},
            "drivers": ({"channel": ex.get("channel", []), "daypart": ex.get("daypart", [])} if base else {"channel": [], "daypart": []}),
            "context": {"rain": bool(ctx.get("rain")), "snow": bool(ctx.get("snow")), "temp_high_c": ctx.get("temp_high_c"),
                        "events": ctx.get("events", [])},
            "items_up": up, "items_down": down}


def range_explain(s: str, e: str) -> dict:
    """The same breakdown for a date range, aggregated (totals) vs the previous equal-length period. vs_similar is
    empty for ranges (no comparable 'similar period' in one year of data)."""
    df = daily_frame()
    n = (pd.Timestamp(e) - pd.Timestamp(s)).days + 1
    pe = pd.Timestamp(s) - pd.Timedelta(days=1)
    ps = pe - pd.Timedelta(days=n - 1)
    cur = df[(df.business_date >= pd.Timestamp(s)) & (df.business_date <= pd.Timestamp(e)) & (df.orders > 0)]
    prev = df[(df.business_date >= ps) & (df.business_date <= pe) & (df.orders > 0)] if ps >= df.business_date.min() else df.iloc[0:0]
    cd = [str(x.date()) for x in cur.business_date]
    pdates = [str(x.date()) for x in prev.business_date]
    cal = store().df("SELECT * FROM calendar WHERE date BETWEEN ? AND ?", [s, e])
    evs = store().df("SELECT event FROM events WHERE date BETWEEN ? AND ?", [s, e]).event
    counts = evs.str.replace(r" \(.*\)$", "", regex=True).value_counts()
    events = [f"{k} ({v})" if v > 1 else k for k, v in counts.items()]
    events = [h for h in cal.holiday.dropna().tolist() if isinstance(h, str)] + events
    so = int(store().df("SELECT COUNT(*) n FROM prep_log WHERE sold_out AND business_date BETWEEN ? AND ?", [s, e]).n[0])
    if so:
        events.append(f"chashu sold out on {so} day{'s' if so != 1 else ''}")
    ctx = {"rain": bool(cal.rain.any()) if len(cal) else False, "snow": bool(cal.snow.any()) if len(cal) else False,
           "temp_high_c": round(float(cal.temp_high_c.mean()), 1) if len(cal) else None, "events": events,
           "rain_days": int(cal.rain.sum()) if len(cal) else 0, "snow_days": int(cal.snow.sum()) if len(cal) else 0}
    if not cd:
        return _empty_explain("closed", ctx)
    if not pdates:
        out = _empty_explain("no_baseline", ctx)
        return out
    pct = lambda a, b: round(float(a / b - 1), 4) if b else None
    up, down = _items_moves(cd, pdates, 1)
    return {"status": "ok",
            "vs_usual": {"net_sales_pct": pct(cur.net_sales.sum(), prev.net_sales.sum()),
                         "orders_pct": pct(cur.orders.sum(), prev.orders.sum()), "baseline_dates": pdates,
                         "baseline": {"start": str(ps.date()), "end": str(pe.date())}},
            "vs_similar": {"net_sales_pct": None, "dates": []},
            "drivers": _drivers(cd, pdates, 1), "context": ctx, "items_up": up, "items_down": down}


# ------------------------------------------------------------------ /day/{date}
@router.get("/day/{date}")
async def day_detail(date: str):
    from . import app as A
    d = _date(date)

    def build():
        ov = A.overview(d)
        try:
            t, hm = cut()
            # tonight's close (e.g. from an earlier run) stays hidden until the night is over
            close = None if (d == t and hm is not None) else A.close_detail(d)
        except HTTPException:
            close = None
        return {"date": d, "overview": ov, "close": close, "report": A.report_ref(d),
                "explain": cached("day_explain", day_explain, d)}
    return await run_in_threadpool(build)


# ------------------------------------------------------------------ /live/stream
def _hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _card_for(d: str) -> tuple[list, str | None]:
    """The card that was approved at the previous night's close (it planned this day), or that close's plan."""
    from . import app as A
    prev = str((pd.Timestamp(d) - pd.Timedelta(days=1)).date())
    f = A.out_dir() / f"close_{prev}.json"
    if not f.exists():
        return [], None
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return [], None
    appr = A._valid_approval(prev, rec, f)
    if appr and appr.get("card"):
        return appr["card"], "approved"
    return (rec.get("plan") or {}).get("card") or [], "plan"


def timeline(d: str) -> dict:
    """Every event of the day's service, in order, from the orders table. (sim_second, priority, name, payload).
    Reads the whole day (not cut at now): the stream releases each event at its own time."""
    st = Store(DB)
    o = st.df("""SELECT o.order_id AS id, o.created_at, o.channel, o.subtotal, o.status, o.cancel_reason,
                        list(l.item) FILTER (WHERE l.item IS NOT NULL) AS items, COALESCE(SUM(m.chashu_portions), 0) AS chashu
                 FROM orders o LEFT JOIN order_lines l USING(order_id) LEFT JOIN menu m ON m.item = l.item
                 WHERE o.business_date = ? GROUP BY ALL ORDER BY o.created_at, o.order_id""", [d])
    pr = st.df("SELECT par FROM prep_log WHERE business_date = ?", [d])
    par = float(pr.par[0]) if len(pr) else 0.0
    dow = pd.Timestamp(d).dayofweek
    close_s = (23 if dow in (4, 5) else 22) * 3600
    if len(o):
        o["sec"] = (o.created_at - pd.Timestamp(d)).dt.total_seconds()
        close_s = max(close_s, int(o.sec.max() // 60 + 1) * 60)
    open_s = 11 * 3600
    card, card_src = _card_for(d)
    card_pause = (card[0].get("pause_at") or {}) if card else {}

    # rush window from the day's own 15-minute curve (dinner, >= 75% of the peak), as Demand defines it
    rush = None
    if len(o):
        slot = (o.sec // 900).astype(int)
        cnt = slot.value_counts()
        curve = [{"bin": s, "time": f"{s // 4:02d}:{s % 4 * 15:02d}", "orders": float(cnt.get(s, 0))} for s in SLOTS]
        from ..tools.demand import rush_window
        rush = rush_window(curve)

    ev: list[tuple] = []
    tot = {"orders": 0, "placed": 0, "net_sales": 0.0, "cancels": 0, "by": {c: 0 for c in CHANNELS},
           "by_sales": {c: 0.0 for c in CHANNELS}}
    left = par
    rate, last_t = 0.0, None
    decided = {a: None for a in APPS}
    paused = {a: None for a in APPS}
    sold_out_at = None
    rows = list(o.itertuples()) if len(o) else []
    snaps: list[tuple[float, dict]] = []  # running totals after each order, for the ticks

    def emit_pause_until(t: float):
        for a in APPS:
            if decided[a] is not None and paused[a] is None and decided[a] + plan.PAUSE_DELAY_MIN[a] * 60 <= t:
                paused[a] = decided[a] + plan.PAUSE_DELAY_MIN[a] * 60
                pred = card_pause.get(a)
                txt = (f"Gondola paused Chashu on {APP_NAME[a]} with {max(round(left_at[a]), 0)} portions left, kept for dine-in"
                       + (f" (card said ~{clock(pred)})" if pred else ""))
                ev.append((paused[a], 2, "event", {"t": _hms(paused[a])[:5], "kind": "pause", "app": a, "chashu_left": max(round(left_at[a]), 0),
                                                   "source": card_src or "rule", "text": txt}))

    left_at = {a: 0.0 for a in APPS}
    for r in rows:
        t = float(r.sec)
        emit_pause_until(t)
        tot["placed"] += 1
        need = float(r.chashu)
        if r.status == "completed":
            tot["orders"] += 1
            tot["net_sales"] += float(r.subtotal)
            tot["by"][r.channel] += 1
            tot["by_sales"][r.channel] += float(r.subtotal)
            if need > 0:
                if last_t is not None and t > last_t:
                    rate = 0.8 * rate + 0.2 * (need / max((t - last_t) / 60, 0.5))
                last_t = t
                left -= need
        elif r.status == "cancelled":
            tot["cancels"] += 1
        held = bool(r.channel in APPS and need > 0 and paused.get(r.channel) is not None and t >= paused[r.channel])
        items = list(r.items) if r.items is not None else []
        ev.append((t, 1, "order", {"t": _hms(t), "id": r.id, "channel": r.channel, "items": items, "subtotal": _r2(r.subtotal),
                                   "status": r.status, "cancel_reason": r.cancel_reason if isinstance(r.cancel_reason, str) else None,
                                   "chashu": round(need, 2), "held_by_gondola": held}))
        if par > 0:
            for a in APPS:  # Guard's rule: pause when what's left covers only the buffer plus the app's pause delay
                if decided[a] is None and left < BUFFER + rate * APP_SHARE * plan.PAUSE_DELAY_MIN[a]:
                    decided[a] = t
                    left_at[a] = left
            if sold_out_at is None and (left <= 0.5 or r.cancel_reason == "item_unavailable"):
                sold_out_at = t
                live = [APP_NAME[a] for a in APPS if paused[a] is None]
                txt = f"Chashu sold out at {clock(_hms(t)[:5])}" + (
                    f"; still live on {', '.join(live)}" if live else "; the apps were already paused")
                ev.append((t, 3, "event", {"t": _hms(t)[:5], "kind": "sold_out", "text": txt, "live_on": [a for a in APPS if paused[a] is None]}))
        snaps.append((t, {"orders": tot["orders"], "placed": tot["placed"], "net_sales": _r2(tot["net_sales"]),
                          "by_channel": dict(tot["by"]), "by_channel_sales": {k: _r2(v) for k, v in tot["by_sales"].items()},
                          "chashu_left": max(round(left, 1), 0.0), "cancels": tot["cancels"]}))
    emit_pause_until(close_s + 3600)
    ev = [e for e in ev if not (e[2] == "event" and e[0] > close_s)]

    if rush:
        rs = int(rush["start"][:2]) * 3600 + int(rush["start"][3:]) * 60
        re_ = int(rush["end"][:2]) * 3600 + int(rush["end"][3:]) * 60
        n_rush = int(((o.sec >= rs) & (o.sec < re_)).sum())
        ev.append((rs, 0.5, "event", {"t": rush["start"], "kind": "rush_start",
                                      "text": f"Dinner rush starting (busiest 15 minutes tonight: {rush['peak_per_15min']:.0f} orders)"}))
        ev.append((re_, 0.5, "event", {"t": rush["end"], "kind": "rush_end",
                                       "text": f"Rush over: {n_rush} orders {clock(rush['start'])}–{clock(rush['end'])}"}))

    # ticks: one per simulated minute, with the totals of everything placed before it
    empty = {"orders": 0, "placed": 0, "net_sales": 0.0, "by_channel": {c: 0 for c in CHANNELS},
             "by_channel_sales": {c: 0.0 for c in CHANNELS}, "chashu_left": par, "cancels": 0}
    times = np.array([s[0] for s in snaps]) if snaps else np.array([])
    for m in range(open_s, close_s + 60, 60):
        k = int(np.searchsorted(times, m, side="left")) - 1  # orders strictly before minute m
        state = snaps[k][1] if k >= 0 else empty
        ev.append((m, 0, "tick", {"t": _hms(m)[:5], **state}))
    ev.sort(key=lambda e: (e[0], e[1]))
    final = snaps[-1][1] if snaps else empty
    return {"date": d, "par": par, "open": open_s, "close": close_s, "events": ev, "final": final, "rush": rush,
            "card": card, "card_source": card_src, "sold_out_at": _hms(sold_out_at)[:5] if sold_out_at is not None else None}


def _parse_hm(s: str) -> int:
    try:
        p = s.split(":")
        assert 2 <= len(p) <= 3
        h, m, sec = int(p[0]), int(p[1]), int(p[2]) if len(p) == 3 else 0
        assert 0 <= h < 24 and 0 <= m < 60 and 0 <= sec < 60
        return h * 3600 + m * 60 + sec
    except Exception:
        raise HTTPException(400, f"bad time '{s}' (use HH:MM or HH:MM:SS)")


async def _live_events(tl: dict, start: int, speed: float, request: Request, catchup: bool = False):
    """Pace the precomputed timeline in real time (absolute schedule, so no drift). One SSE message per event; a comment
    heartbeat during long gaps; stops when the client goes away. catchup: first send, at once, every order and event
    before `start` (flagged "catchup": true) and the last tick before it, so a client joining mid-service has the day
    so far without a second request."""
    loop = asyncio.get_running_loop()
    events = [e for e in tl["events"] if e[0] >= start]
    yield ": gondola live\n\n"
    yield sse_format("start", {"date": tl["date"], "from": _hms(start), "speed": speed, "par": tl["par"],
                               "open": _hms(tl["open"])[:5], "close": _hms(tl["close"])[:5], "orders_total": tl["final"]["placed"],
                               "card_source": tl["card_source"], "rush": tl["rush"], "catchup": catchup})
    if catchup:
        before = [e for e in tl["events"] if e[0] < start]
        last_tick = next((e for e in reversed(before) if e[2] == "tick"), None)
        for i, (_t, _p, name, payload) in enumerate(before):
            if name != "tick":
                yield sse_format(name, {**payload, "catchup": True})
            if i % 200 == 0:
                await asyncio.sleep(0)
        if last_tick:
            yield sse_format("tick", {**last_tick[3], "catchup": True})
    t0 = loop.time()
    sent = 0
    for sim_t, _p, name, payload in events:
        target = t0 + (sim_t - start) / speed
        while True:
            delay = target - loop.time()
            if delay <= 0:
                break
            if delay > 10:
                await asyncio.sleep(10)
                yield ": keepalive\n\n"
                if await request.is_disconnected():
                    return
            else:
                await asyncio.sleep(delay)
        yield sse_format(name, payload)
        sent += 1
        if sent % 50 == 0:
            await asyncio.sleep(0)  # let the server notice a disconnect even at very high speed
    yield sse_format("done", {"status": "done", "date": tl["date"], "t": _hms(tl["close"])[:5], **tl["final"],
                              "sold_out_at": tl["sold_out_at"]})


@router.get("/live/stream")
async def live_stream(request: Request, date: str | None = None, speed: float = 60.0, catchup: bool = False):
    d = _date(date)
    frm = request.query_params.get("from", "11:00")
    start = _parse_hm(frm)
    if not (speed > 0) or speed > 1e7:
        raise HTTPException(400, "speed must be a positive number of simulated seconds per real second")
    tl = await run_in_threadpool(cached, "timeline", timeline, d)
    if not tl["events"] or tl["final"]["placed"] == 0:
        async def closed():
            yield sse_format("start", {"date": d, "from": frm, "speed": speed, "par": tl["par"], "orders_total": 0, "closed": True})
            yield sse_format("done", {"status": "closed", "date": d, **tl["final"]})
        return StreamingResponse(closed(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return StreamingResponse(_live_events(tl, start, float(speed), request, catchup), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
