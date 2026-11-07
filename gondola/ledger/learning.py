"""Prep-time learning: an exponential moving average of observed task durations per item and station.

Reads `task.finished` events ({order_id, task_id, item, station, planned_min, actual_min}) in time order, as Savvy's
engine does (new = (1 - alpha) * old + alpha * observed, seeded with the first observation). Present reads
`learned_durations()` to size its capacity model. Deterministic; recomputed from the ledger, cached per ledger size.
"""
from __future__ import annotations

from . import Ledger, ledger

ALPHA = 0.25  # same weight as gondola/rush/engine.py
_CACHE: dict = {}


def _ema(rows: list[tuple[str, float, float | None]], alpha: float) -> dict:
    """rows: (ts, actual, planned) in time order."""
    est, n, planned, last = None, 0, None, None
    for ts, actual, plan in rows:
        est = actual if est is None else (1 - alpha) * est + alpha * actual
        n += 1
        planned = plan if plan is not None else planned
        last = ts
    return {"ema_min": round(est, 2) if est is not None else None, "n": n, "planned_min": planned, "last_ts": last}


def learned_durations(upto_date: str | None = None, alpha: float = ALPHA, led: Ledger | None = None) -> dict:
    """{"by_item": {item: {station, ema_min, n, planned_min, last_ts}}, "by_station": {station: {...}},
    "by_item_station": {"item|station": {...}}, "alpha", "events"}. Empty dicts when nothing has been observed.
    upto_date: only events on or before this business date (no peeking past a replayed day)."""
    led = led or ledger()
    key = (str(led.path), upto_date, alpha, led.count(None, ["task.finished"]))
    if key in _CACHE:
        return _CACHE[key]
    evs = led.query(None, ["task.finished"])
    if upto_date:
        evs = [e for e in evs if e.date <= upto_date]
    seen: set = set()
    item_rows: dict[str, list] = {}
    st_rows: dict[str, list] = {}
    pair_rows: dict[str, list] = {}
    item_station: dict[str, str] = {}
    for e in evs:
        p = e.payload
        a = p.get("actual_min")
        if a is None or not p.get("item"):
            continue
        tid = p.get("task_id") or f"{p.get('order_id')}:{p.get('item')}:{p.get('station')}"
        if tid in seen:  # one observation per task even if two writers recorded it
            continue
        seen.add(tid)
        row = (e.ts, float(a), p.get("planned_min"))
        item_rows.setdefault(p["item"], []).append(row)
        if p.get("station"):
            st_rows.setdefault(p["station"], []).append(row)
            pair_rows.setdefault(f"{p['item']}|{p['station']}", []).append(row)
            item_station[p["item"]] = p["station"]
    out = {"by_item": {k: {"station": item_station.get(k), **_ema(v, alpha)} for k, v in sorted(item_rows.items())},
           "by_station": {k: _ema(v, alpha) for k, v in sorted(st_rows.items())},
           "by_item_station": {k: _ema(v, alpha) for k, v in sorted(pair_rows.items())},
           "alpha": alpha, "events": len(seen)}
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[key] = out
    return out
