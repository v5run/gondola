"""Build a day's ledger from the store database (deterministic, idempotent).

    python -m gondola.ledger.build --days 75          # history ending today (today only up to gondola.now)
    python -m gondola.ledger.build --date 2026-11-05  # one day

What it writes (every event has a stable key, so re-running a day adds nothing; today grows as the clock moves):
  order.received / order.accepted / order.handed_off / order.cancelled   from orders (+ order_lines)   source "pos"
  cash.counted                                                         from cash_drawer_shifts       source "books"
  payout.report_arrived (one per app report, dated the day it arrived) from payout_lines.available_at source "books"
  forecast.issued (horizon "day", dated the day it is for)             from out/forecasts/{date}.json source "forecast"

Order-level data has no kitchen timing: the order-level `order.handed_off` carries `basis: "order-level"` and no
wait/hold/late. Present writes richer live events (its own keys); summaries prefer those per order when they exist.
Keys here are prefixed by writer ("pos:order.received:o0123") so they never collide with Present's.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import Ledger, ledger, out_dir
from ..metrics import ROOT, Store

DB = ROOT / "data" / "gondola.duckdb"
DAY_CUTOFF_H = 4


def _ts(x) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%dT%H:%M:%S")


def horizon(date: str, db: Path | str = DB) -> datetime | None:
    """The latest instant of `date` the ledger may contain: None for a complete past day, the store clock for today,
    and the day start (nothing) for a future day."""
    from .. import now as clock
    info = clock.info(db)
    today = info["today"]
    if date < today:
        return None
    if date > today:
        return pd.Timestamp(date).to_pydatetime()
    if info["phase"] == "closed":
        return None
    w = clock.wall()
    return w if not info["mapped"] else None


def build_day(date: str, db: Path | str = DB, led: Ledger | None = None, until: datetime | None | str = "auto",
              store: Store | None = None) -> dict:
    """Write one business day's events. until="auto": gondola.now decides (complete for past days, cut at now for today).
    Returns {date, new, by_type}."""
    led = led or ledger()
    date = str(pd.Timestamp(date).date())
    if until == "auto":
        until = horizon(date, db)
    st = store or Store(db)
    own = store is None
    try:
        rows = day_rows(st, date, until)
    finally:
        if own:
            st.con.close()
    new = led.extend(rows)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    return {"date": date, "new": new, "rows": len(rows), "by_type": by_type,
            "until": until.isoformat(timespec="seconds") if isinstance(until, datetime) else None}


def day_rows(store: Store, date: str, until: datetime | None = None) -> list[dict]:
    """Build source events without persisting them."""
    return (_order_rows(store, date, until) + _cash_rows(store, date, until)
            + _payout_rows(store, date, until) + _forecast_rows(date))


def _order_rows(st: Store, date: str, until: datetime | None) -> list[dict]:
    args: list = [date]
    cond = ""
    if until is not None:
        cond = " AND o.created_at < ?"
        args.append(until)
    o = st.df(f"""SELECT o.order_id, o.created_at, o.channel, o.subtotal, o.status, o.cancel_reason, o.promo,
                         list(l.item ORDER BY l.item) AS items
                  FROM orders o LEFT JOIN order_lines l USING(order_id)
                  WHERE o.business_date = ?{cond} GROUP BY ALL ORDER BY o.created_at, o.order_id""", args)
    rows = []
    for r in o.itertuples(index=False):
        ts, oid, ch = _ts(r.created_at), r.order_id, r.channel
        items = [i for i in (list(r.items) if r.items is not None else []) if i is not None]
        ful = "dine_in" if ch == "in_store" else "delivery"
        rows.append({"type": "order.received", "date": date, "ts": ts, "source": "pos", "key": f"pos:order.received:{oid}",
                     "payload": {"order_id": oid, "channel": ch, "items": items, "subtotal": round(float(r.subtotal), 2),
                                 "fulfillment": ful, "promo": bool(r.promo)}})
        rows.append({"type": "order.accepted", "date": date, "ts": ts, "source": "pos", "key": f"pos:order.accepted:{oid}",
                     "payload": {"order_id": oid, "reason": "accepted (order-level: no admission data)", "ladder_level": None}})
        if r.status == "cancelled":
            rows.append({"type": "order.cancelled", "date": date, "ts": ts, "source": "pos", "key": f"pos:order.cancelled:{oid}",
                         "payload": {"order_id": oid, "channel": ch, "reason": r.cancel_reason or "unknown",
                                     "amount": round(float(r.subtotal), 2), "items": items}})
        else:
            rows.append({"type": "order.handed_off", "date": date, "ts": ts, "source": "pos", "key": f"pos:order.handed_off:{oid}",
                         "payload": {"order_id": oid, "channel": ch, "ready": None, "handed": None, "wait_min": None,
                                     "hold_min": None, "late_min": None, "basis": "order-level"}})
    return rows


def _cash_rows(st: Store, date: str, until: datetime | None) -> list[dict]:
    c = st.df("SELECT * FROM cash_drawer_shifts WHERE business_date = ? AND state = 'CLOSED'", [date])
    rows = []
    for r in c.itertuples(index=False):
        if not r.ended_at:
            continue
        ended = pd.Timestamp(r.ended_at)
        if until is not None and ended > pd.Timestamp(until):
            continue
        diff = round(float(r.closed_cash) - float(r.expected_cash), 2)
        rows.append({"type": "cash.counted", "date": date, "ts": _ts(ended), "source": "books", "key": f"books:cash:{r.shift_id}",
                     "payload": {"shift_id": r.shift_id, "expected": round(float(r.expected_cash), 2),
                                 "counted": round(float(r.closed_cash), 2), "difference": diff,
                                 "opening": float(r.opening_cash), "cash_payments": round(float(r.cash_payments), 2),
                                 "paid_out": round(float(r.paid_out), 2)}})
    return rows


def _payout_rows(st: Store, date: str, until: datetime | None) -> list[dict]:
    """App payout reports that arrived during business day `date` (4 am to 4 am), one event per (for_date, channel)."""
    lo = pd.Timestamp(date) + pd.Timedelta(hours=DAY_CUTOFF_H)
    hi = lo + pd.Timedelta(days=1)
    if until is not None:
        hi = min(hi, pd.Timestamp(until))
    if hi <= lo:
        return []
    p = st.df("""
        SELECT business_date, channel, min(available_at) AS arrived, COUNT(*) AS lines, SUM(net_payout) AS reported,
               SUM(CASE WHEN error_charge > 0 THEN 1 ELSE 0 END) AS n_err, SUM(error_charge) AS err_usd,
               SUM(adjustment) AS adj_usd
        FROM payout_lines WHERE CAST(available_at AS TIMESTAMP) >= ? AND CAST(available_at AS TIMESTAMP) < ?
        GROUP BY 1, 2 ORDER BY 1, 2""", [lo.to_pydatetime(), hi.to_pydatetime()])
    from ..tools import books  # the same reconciliation the close uses, so the numbers agree with Books
    rows = []
    for r in p.itertuples(index=False):
        fd = str(pd.Timestamp(r.business_date).date())
        m = books.match_payouts(st, fd, [r.channel])
        ch = (m["channels"] or [{}])[0]
        fnd = [f for f in m["findings"] if f["channel"] == r.channel]
        rows.append({"type": "payout.report_arrived", "date": date, "ts": _ts(r.arrived), "source": "books",
                     "key": f"books:payout:{fd}:{r.channel}",
                     "payload": {"for_date": fd, "channel": r.channel, "lines": int(r.lines), "orders": ch.get("orders"),
                                 "sales": ch.get("sales"), "reported": ch.get("reported", round(float(r.reported), 2)),
                                 "expected": ch.get("expected"), "difference": ch.get("difference"),
                                 "error_charges": int(r.n_err), "error_charge_usd": round(float(r.err_usd), 2),
                                 "adjustment_usd": round(float(r.adj_usd), 2),
                                 "recoverable_usd": round(sum(f["impact_usd"] for f in fnd if f["impact_usd"] > 0), 2),
                                 "n_disputable": sum(1 for f in fnd if f["kind"] == "error_charge_disputable"),
                                 "missing_orders": sum(1 for f in fnd if f["kind"] == "missing_from_payout"),
                                 "findings": [{"kind": f["kind"], "impact_usd": f["impact_usd"], "order_id": (f.get("evidence") or [None])[0]}
                                              for f in fnd][:20]}})
    return rows


def _forecast_rows(date: str) -> list[dict]:
    """The day forecast the close stored the night before (out/forecasts/{date}.json), dated the day it is for."""
    f = out_dir() / "forecasts" / f"{date}.json"
    if not f.exists():
        return []
    try:
        fc = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return []
    issued = pd.Timestamp(date) - pd.Timedelta(days=1) + pd.Timedelta(hours=23, minutes=10)
    return [{"type": "forecast.issued", "date": date, "ts": _ts(issued), "source": "forecast", "key": f"forecast:day:{date}",
             "payload": {"horizon": "day", "for_date": date, "issued_by": "close", "total": {k: fc.get(k) for k in ("p10", "p50", "p90")}}}]


def build_range(days: int = 75, end: str | None = None, db: Path | str = DB, led: Ledger | None = None,
                quiet: bool = True) -> dict:
    """Build the last `days` business days ending at `end` (default: today on the store clock)."""
    from .. import now as clock
    end = end or clock.info(db)["today"]
    dates = [str(d.date()) for d in pd.date_range(pd.Timestamp(end) - pd.Timedelta(days=days - 1), end)]
    st = Store(db)
    total = 0
    try:
        for d in dates:
            r = build_day(d, db, led, store=st)
            total += r["new"]
            if not quiet:
                print(f"  {d}  +{r['new']:5d} events", flush=True)
    finally:
        st.con.close()
    return {"days": len(dates), "first": dates[0], "last": dates[-1], "new": total}


def ensure_day(date: str, db: Path | str = DB, led: Ledger | None = None) -> None:
    """Build `date` if it has no order events yet, and keep today current (cheap: keys make it idempotent)."""
    led = led or ledger()
    from .. import now as clock
    today = clock.info(db)["today"]
    if date > today:
        return
    if date == today or not led.count(date, ["order.received"]):
        build_day(date, db, led)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the ledger from the store database (idempotent).")
    ap.add_argument("--days", type=int, default=75)
    ap.add_argument("--date", default=None, help="build only this business date")
    ap.add_argument("--end", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.date:
        print(json.dumps(build_day(a.date)))
    else:
        print(json.dumps(build_range(a.days, a.end, quiet=a.quiet)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
