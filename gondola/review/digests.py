"""Episodic memory: shift logs, day digests and their weekly/monthly roll-ups (design section 6.1).

Every number is computed by code from the ledger (and the close's own results when it ran). SQLite at
out/digests.sqlite (override GONDOLA_DIGESTS_DB; follows gondola.pipeline.OUT like the ledger).

  shift  every 60 minutes while open, <= 5 bullets                     -> folded into the day digest at close
  day    at close, structured JSON (<= 1 page, MAX_DAY_CHARS)          -> kept DAY_TTL days, then only roll-ups
  week   ISO week (Mon-Sun) from its day digests, when the week ends
  month  from the weeks that end in the month, when the month ends
Reviews (well / wrong / causes / actions / kb changes) are kept in their own table for REVIEW_TTL days, like the
bucket keeps findings.json after the PDF expires.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
import threading
from datetime import datetime
from pathlib import Path
from statistics import mean

import pandas as pd

from ..ledger import Ledger, ledger, out_dir
from ..ledger.summary import hourly, summary
from ..metrics import ROOT

DB = ROOT / "data" / "gondola.duckdb"
DAY_TTL = 30          # same lifecycle as the reports bucket
REVIEW_TTL = 365
MAX_SHIFT_BULLETS = 5
MAX_DAY_CHARS = 4000  # ~1 page of JSON
MAX_LINE = 240
CH_NAME = {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub", "in_store": "In-store"}
_LOCK = threading.Lock()


def db_path() -> Path:
    p = os.getenv("GONDOLA_DIGESTS_DB")
    return Path(p) if p else out_dir() / "digests.sqlite"


def money(x) -> str:
    return f"${x:,.0f}" if x is not None else "n/a"


class Digests:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS digests (id TEXT PRIMARY KEY, kind TEXT NOT NULL, period TEXT NOT NULL,
                         date_start TEXT, date_end TEXT, created TEXT, body TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_kind ON digests(kind, date_end)")
            c.execute("CREATE TABLE IF NOT EXISTS reviews (date TEXT PRIMARY KEY, created TEXT, body TEXT NOT NULL)")

    @contextmanager
    def _con(self):
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            with c:  # Commit/rollback before releasing the Windows file handle.
                yield c
        finally:
            c.close()

    def put(self, d: dict) -> dict:
        with _LOCK, self._con() as c:
            c.execute("INSERT OR REPLACE INTO digests(id, kind, period, date_start, date_end, created, body) VALUES (?,?,?,?,?,?,?)",
                      (d["id"], d["kind"], d["period"], d.get("date_start"), d.get("date_end"),
                       d.get("created") or datetime.now().isoformat(timespec="seconds"), json.dumps(d, default=str)))
        return d

    def get(self, id: str) -> dict | None:
        with self._con() as c:
            r = c.execute("SELECT body FROM digests WHERE id = ?", (id,)).fetchone()
        return json.loads(r[0]) if r else None

    def list(self, kind: str | None = None, limit: int | None = None, before: str | None = None,
             start: str | None = None, end: str | None = None) -> list[dict]:
        """Newest first. before: date_end < before. start/end: date_end within [start, end]."""
        where, args = [], []
        if kind:
            where.append("kind = ?"); args.append(kind)
        if before:
            where.append("date_end < ?"); args.append(before)
        if start:
            where.append("date_end >= ?"); args.append(start)
        if end:
            where.append("date_end <= ?"); args.append(end)
        sql = "SELECT body FROM digests" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY date_end DESC, id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._con() as c:
            return [json.loads(r[0]) for r in c.execute(sql, args).fetchall()]

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        with _LOCK, self._con() as c:
            c.execute(f"DELETE FROM digests WHERE id IN ({','.join('?' * len(ids))})", ids)

    def put_review(self, date: str, review: dict) -> None:
        with _LOCK, self._con() as c:
            c.execute("INSERT OR REPLACE INTO reviews(date, created, body) VALUES (?,?,?)",
                      (date, datetime.now().isoformat(timespec="seconds"), json.dumps(review, default=str)))

    def review(self, date: str) -> dict | None:
        with self._con() as c:
            r = c.execute("SELECT body FROM reviews WHERE date = ?", (date,)).fetchone()
        return json.loads(r[0]) if r else None

    def review_dates(self) -> list[str]:
        with self._con() as c:
            return [r[0] for r in c.execute("SELECT date FROM reviews ORDER BY date").fetchall()]

    def clear(self) -> None:
        with _LOCK, self._con() as c:
            c.execute("DELETE FROM digests"); c.execute("DELETE FROM reviews")


_DEFAULT: Digests | None = None


def digests() -> Digests:
    global _DEFAULT
    if _DEFAULT is None or _DEFAULT.path != db_path():
        _DEFAULT = Digests()
    return _DEFAULT


# ------------------------------------------------------------------ shift log (hourly while open)
def shift_log(date: str, hour: int, led: Ledger | None = None) -> dict:
    """<= 5 code-computed bullets for the hour [hour:00, hour+1:00)."""
    led = led or ledger()
    lo, hi = f"{date}T{hour:02d}:00:00", f"{date}T{hour + 1:02d}:00:00" if hour < 23 else f"{date}T23:59:59"
    evs = led.query(date, start_ts=lo, end_ts=hi)
    evs = [e for e in evs if e.ts < hi]
    from ..ledger.summary import per_order
    po = per_order([e for e in evs if e.type.startswith("order.")])
    rec = [t["order.received"] for t in po.values() if "order.received" in t]
    hand = [t["order.handed_off"] for t in po.values() if "order.handed_off" in t]
    canc = [t["order.cancelled"] for t in po.values() if "order.cancelled" in t]
    reasons: dict[str, int] = {}
    for e in canc:
        reasons[e.payload.get("reason") or "unknown"] = reasons.get(e.payload.get("reason") or "unknown", 0) + 1
    bullets = [f"{hour:02d}:00–{hour + 1:02d}:00: {len(rec)} orders in, {len(hand)} out, {len(canc)} cancelled"
               + (f" ({', '.join(f'{k} {v}' for k, v in sorted(reasons.items()))})" if reasons else "") + "."]
    by: dict[str, int] = {}
    for e in rec:
        ch = e.payload.get("channel") or "unknown"
        by[ch] = by.get(ch, 0) + 1
    if by:
        bullets.append("Channels: " + ", ".join(f"{CH_NAME.get(k, k)} {v}" for k, v in sorted(by.items(), key=lambda x: -x[1])) + ".")
    waits = [float(e.payload["wait_min"]) for e in hand if e.payload.get("wait_min") is not None]
    lates = [float(e.payload["late_min"]) for e in hand if e.payload.get("late_min") is not None]
    if waits:
        bullets.append(f"Waits: average {mean(waits):.1f} min, worst {max(waits):.1f} min; "
                       f"{sum(1 for x in lates if x > 0)} late of {len(lates)}.")
    acts = [e for e in evs if e.type == "action.applied"]
    if acts:
        kinds: dict[str, int] = {}
        for e in acts:
            k = e.payload.get("action") or "action"
            kinds[k] = kinds.get(k, 0) + 1
        bullets.append("Actions: " + ", ".join(f"{k} ×{v}" for k, v in sorted(kinds.items())) + ".")
    exc = [e for e in evs if e.type == "exception.raised"]
    if exc:
        bullets.append("Exceptions: " + "; ".join(e.payload.get("title", "") for e in exc[:2]) + ".")
    numbers = {"received": len(rec), "handed_off": len(hand), "cancelled": len(canc), "by_channel": by,
               "avg_wait_min": round(mean(waits), 1) if waits else None, "worst_wait_min": round(max(waits), 1) if waits else None,
               "actions": len(acts), "exceptions": len(exc)}
    return {"id": f"shift-{date}T{hour:02d}", "kind": "shift", "period": f"{date}T{hour:02d}", "date_start": date,
            "date_end": date, "bullets": bullets[:MAX_SHIFT_BULLETS], "numbers": numbers}


def write_shift_logs(date: str, upto_hour: int, led: Ledger | None = None, dg: Digests | None = None) -> list[dict]:
    """Write the shift log of every completed hour from opening (11) up to `upto_hour` that isn't written yet."""
    dg = dg or digests()
    have = {d["id"] for d in dg.list("shift", start=date, end=date)}
    out = []
    for h in range(11, upto_hour):
        if f"shift-{date}T{h:02d}" in have:
            continue
        s = shift_log(date, h, led)
        dg.put(s)
        out.append(s)
    return out


# ------------------------------------------------------------------ day digest inputs (code numbers only)
def _close_result(date: str) -> dict | None:
    p = out_dir() / f"close_{date}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def day_inputs(date: str, led: Ledger | None = None, db: Path | str = DB, close_res: dict | None = None,
               dg: Digests | None = None) -> dict:
    """Everything the Review agent may say about a closed day, computed by code."""
    from ..kb import measures as M
    led = led or ledger()
    s = summary(date, None, led)
    cond = M.day_conditions(date, db)
    # usual: the same weekday over the previous 4 weeks (store data, as the Analyst compares)
    ser = M.series("orders", {}, None, date, db)
    prev = [d for d in ser.index if d < pd.Timestamp(date) and d.dayofweek == pd.Timestamp(date).dayofweek][-4:]
    usual = round(float(ser.loc[prev].mean()), 1) if prev else None
    vs = round((s["processed"] / usual - 1) * 100, 1) if usual else None
    hrs = hourly(date, None, led)
    peak = max(hrs, key=lambda h: h["received"]) if hrs else None
    # forecast check: the day forecast issued for this date vs what happened
    fc = None
    fcs = [e for e in led.query(date, ["forecast.issued"]) if (e.payload.get("horizon") == "day")]
    if fcs:
        t = fcs[-1].payload.get("total") or {}
        if t.get("p50"):
            act = s["processed"]
            fc = {"p10": t.get("p10"), "p50": t.get("p50"), "p90": t.get("p90"), "actual": act,
                  "error_pct": round((t["p50"] - act) / act * 100, 1) if act else None,
                  "in_range": bool(t.get("p10") is not None and t["p10"] <= act <= t["p90"]),
                  "direction": "over" if act and t["p50"] > act else "under"}
    close_res = close_res if close_res is not None else _close_result(date)
    so = (close_res or {}).get("sold_out")
    if so is None and cond.get("sold_out") and close_res is None:
        from ..metrics import Store
        from ..tools import stock
        st = Store(db)
        try:
            so = stock.sold_out_summary(st, date)
        finally:
            st.con.close()
    if so:
        so = {k: so.get(k) for k in ("at", "app_cancels", "minutes_live", "by_channel", "portions_missed", "prepped", "used")}
        so["item"] = "chashu"
    cash = [e.payload for e in led.query(date, ["cash.counted"])]
    payouts = [{k: e.payload.get(k) for k in ("for_date", "channel", "difference", "recoverable_usd", "n_disputable", "error_charges")}
               for e in led.query(date, ["payout.report_arrived"])]
    exc = [{k: e.payload.get(k) for k in ("id", "kind", "severity", "decision", "title")} for e in led.query(date, ["exception.raised"])]
    acts: dict[str, int] = {}
    for e in led.query(date, ["action.applied"]):
        k = e.payload.get("action") or "action"
        acts[k] = acts.get(k, 0) + 1
    shift = [b for d in sorted(digests_for_date(date, dg), key=lambda x: x["period"]) for b in d["bullets"][:1]]
    return {
        "date": date, "weekday": cond.get("weekday"),
        "numbers": {"orders": s["processed"], "sales": s["sales"], "received": s["received"], "cancels": s["cancels"],
                    "cancels_by_reason": s["cancels_by_reason"], "by_channel": s["by_channel"], "usual_orders": usual,
                    "vs_usual_pct": vs, "promises_met_pct": s["promises_met_pct"], "promises_total": s["promises_total"],
                    "late_orders": s["late_orders"], "avg_wait_min": s["avg_wait_min"], "worst_wait_min": s["worst_wait_min"],
                    "avg_hold_min": s["avg_hold_min"], "actions": s["actions_count"], "actions_by_kind": acts,
                    "peak_hour": peak["hour"] if peak else None, "peak_hour_orders": peak["received"] if peak else None,
                    "timing_source": s["timing_source"]},
        "conditions": {k: cond.get(k) for k in ("events", "rain", "evening_rain", "snow", "dd_promo", "holiday", "cold", "temp_high_c")},
        "prep": {"item": "chashu", "par": cond.get("par"), "used": cond.get("used"), "sold_out": cond.get("sold_out")},
        "forecast": fc, "sold_out": so,
        "money": {"cash_diff": cash[-1]["difference"] if cash else None, "payouts": payouts},
        "exceptions": exc, "shift_log": shift[:6],
    }


def digests_for_date(date: str, dg: Digests | None = None) -> list[dict]:
    return (dg or digests()).list("shift", start=date, end=date)


def day_digest(date: str, inputs: dict, review: dict | None = None) -> dict:
    """The day digest: the inputs plus the review's conclusions, capped at ~1 page."""
    n = inputs["numbers"]
    line = (f"{n['orders']} orders, {money(n['sales'])} sales"
            + (f" ({n['vs_usual_pct']:+.1f}% vs a usual {inputs['weekday']})" if n.get("vs_usual_pct") is not None else "")
            + (f"; {n['cancels']} cancelled" if n.get("cancels") else "")
            + (f"; chashu sold out {inputs['sold_out']['at']}" if inputs.get("sold_out") else "") + ".")
    d = {"id": f"day-{date}", "kind": "day", "period": date, "date_start": date, "date_end": date, "summary": line,
         **{k: inputs[k] for k in ("weekday", "numbers", "conditions", "prep", "forecast", "sold_out", "money", "exceptions", "shift_log")}}
    if review:
        d.update({k: [(x.get("text") if isinstance(x, dict) else str(x))[:MAX_LINE] for x in review.get(k, [])][:5]
                  for k in ("well", "wrong", "causes")})
        d["actions"] = [a["id"] for a in review.get("actions", [])]
        d["kb_changes"] = [{"id": c.get("id"), "op": c.get("op")} for c in review.get("kb_changes", [])][:10]
    # hard cap: shed detail until it fits one page
    sheds = [("money", "payouts"), ("shift_log",), ("exceptions",), ("numbers", "cancels_by_reason"), ("numbers", "by_channel"),
             ("kb_changes",), ("causes",), ("well",), ("wrong",), ("causes",), ("well",), ("wrong",), ("shift_log",), ("exceptions",)]
    for shed in sheds:
        if len(json.dumps(d, default=str)) <= MAX_DAY_CHARS:
            break
        if shed[0] not in d:
            continue
        if len(shed) == 2:
            v = d[shed[0]].get(shed[1])
            d[shed[0]][shed[1]] = v[:2] if isinstance(v, list) else {}
        elif isinstance(d[shed[0]], list) and d[shed[0]]:
            d[shed[0]] = d[shed[0]][:max(0, min(len(d[shed[0]]) - 1, 3))]
    return d


# ------------------------------------------------------------------ roll-ups and lifecycle
def iso_week(date: str) -> tuple[str, str, str]:
    t = pd.Timestamp(date)
    y, w, _ = t.isocalendar()
    start = t - pd.Timedelta(days=t.dayofweek)
    return f"{y}-W{w:02d}", str(start.date()), str((start + pd.Timedelta(days=6)).date())


def week_digest(period: str, start: str, end: str, days: list[dict]) -> dict:
    days = sorted(days, key=lambda d: d["period"])
    open_days = [d for d in days if d["numbers"]["orders"]]
    orders = sum(d["numbers"]["orders"] for d in days)
    sales = round(sum(d["numbers"]["sales"] for d in days), 2)
    best = max(open_days, key=lambda d: d["numbers"]["orders"]) if open_days else None
    worst = min(open_days, key=lambda d: d["numbers"]["orders"]) if open_days else None
    errs = [abs(d["forecast"]["error_pct"]) for d in days if d.get("forecast") and d["forecast"].get("error_pct") is not None]
    wrong: dict[str, int] = {}
    for d in days:
        for w in d.get("wrong") or []:
            key = _theme(w)
            wrong[key] = wrong.get(key, 0) + 1
    nums = {"days": len(days), "orders": orders, "sales": sales, "avg_orders": round(orders / len(open_days), 1) if open_days else 0,
            "cancels": sum(d["numbers"]["cancels"] for d in days),
            "sellout_days": sum(1 for d in days if d.get("sold_out")),
            "forecast_mape_pct": round(mean(errs), 1) if errs else None,
            "cash_short_days": sum(1 for d in days if (d["money"].get("cash_diff") or 0) < -5),
            "recoverable_usd": round(sum(p.get("recoverable_usd") or 0 for d in days for p in d["money"].get("payouts") or []), 2),
            "best_day": best["period"] if best else None, "best_orders": best["numbers"]["orders"] if best else None,
            "worst_day": worst["period"] if worst else None, "worst_orders": worst["numbers"]["orders"] if worst else None,
            "exceptions": sum(len(d.get("exceptions") or []) for d in days)}
    summ = (f"{orders} orders, {money(sales)} over {len(open_days)} open days; {nums['sellout_days']} sell-out days"
            + (f"; forecast off {nums['forecast_mape_pct']}% on average" if errs else "") + ".")
    return {"id": f"week-{period}", "kind": "week", "period": period, "date_start": start, "date_end": end, "summary": summ,
            "numbers": nums, "wrong_themes": dict(sorted(wrong.items(), key=lambda x: -x[1])[:6]),
            "days": [d["period"] for d in days]}


def month_digest(period: str, weeks: list[dict]) -> dict:
    weeks = sorted(weeks, key=lambda w: w["period"])
    num = lambda k: sum(w["numbers"].get(k) or 0 for w in weeks)
    themes: dict[str, int] = {}
    for w in weeks:
        for k, v in (w.get("wrong_themes") or {}).items():
            themes[k] = themes.get(k, 0) + v
    mapes = [w["numbers"]["forecast_mape_pct"] for w in weeks if w["numbers"].get("forecast_mape_pct") is not None]
    nums = {"weeks": len(weeks), "orders": num("orders"), "sales": round(num("sales"), 2), "cancels": num("cancels"),
            "sellout_days": num("sellout_days"), "cash_short_days": num("cash_short_days"),
            "recoverable_usd": round(num("recoverable_usd"), 2), "exceptions": num("exceptions"),
            "forecast_mape_pct": round(mean(mapes), 1) if mapes else None}
    summ = f"{nums['orders']} orders, {money(nums['sales'])} across {len(weeks)} weeks; {nums['sellout_days']} sell-out days."
    return {"id": f"month-{period}", "kind": "month", "period": period, "date_start": weeks[0]["date_start"] if weeks else None,
            "date_end": weeks[-1]["date_end"] if weeks else None, "summary": summ, "numbers": nums,
            "wrong_themes": dict(sorted(themes.items(), key=lambda x: -x[1])[:6]), "weeks": [w["period"] for w in weeks]}


def _theme(text: str) -> str:
    t = text.lower()
    for k, words in (("sell-out", ("sold out", "sell-out")), ("cancellations", ("cancel",)), ("cash", ("cash",)),
                     ("payouts", ("payout", "dispute", "error charge")), ("forecast", ("forecast",)),
                     ("late orders", ("late", "wait", "promise")), ("demand", ("below a usual", "quiet", "orders were"))):
        if any(w in t for w in words):
            return k
    return "other"


def rollup(as_of: str, dg: Digests | None = None) -> dict:
    """Build the week digest for every finished ISO week that has day digests and no roll-up yet (and the month digest
    for every finished month), then apply the lifecycle: shift logs of past days and day digests older than DAY_TTL
    days (once their week is rolled up) are deleted. Reviews older than REVIEW_TTL are deleted."""
    dg = dg or digests()
    made = []
    days = dg.list("day")
    weeks: dict[str, list] = {}
    for d in days:
        p, s, e = iso_week(d["period"])
        if e <= as_of:
            weeks.setdefault(p, []).append(d)
    for p, ds in weeks.items():
        _, s, e = iso_week(ds[0]["period"])
        old = dg.get(f"week-{p}")
        if old is None or len(old.get("days") or []) < len(ds):
            dg.put(week_digest(p, s, e, ds))
            made.append(f"week-{p}")
    # months end on their last day; a month is built from the weeks that END in it
    wk = dg.list("week")
    months: dict[str, list] = {}
    for w in wk:
        months.setdefault(w["date_end"][:7], []).append(w)
    for m, ws in months.items():
        last = str((pd.Timestamp(m + "-01") + pd.offsets.MonthEnd(0)).date())
        if last <= as_of:
            old = dg.get(f"month-{m}")
            if old is None or len(old.get("weeks") or []) < len(ws):
                dg.put(month_digest(m, ws))
                made.append(f"month-{m}")
    # lifecycle
    cutoff = str((pd.Timestamp(as_of) - pd.Timedelta(days=DAY_TTL)).date())
    expired = [d["id"] for d in dg.list("day", before=cutoff) if dg.get(f"week-{iso_week(d['period'])[0]}") is not None]
    shifts = [d["id"] for d in dg.list("shift", before=as_of)]
    dg.delete(expired + shifts)
    rcut = str((pd.Timestamp(as_of) - pd.Timedelta(days=REVIEW_TTL)).date())
    with _LOCK, dg._con() as c:
        c.execute("DELETE FROM reviews WHERE date < ?", (rcut,))
    return {"made": made, "expired_days": expired, "folded_shifts": len(shifts)}
