"""The store's clock: the real wall-clock time in America/New_York, mapped onto the data.

The business day runs until 4 a.m. "Today" is the real business date when the data has it: its data is cut at now
(only orders created before the current minute count, see Store(cut=...)); before opening it is empty, after close it
is the full day. When the data has no such day, today is the latest day in the data, shown complete and closed.

Test hook: GONDOLA_NOW="2026-11-05T19:30:00" sets the clock; it starts there when the process first reads it and then
runs in real time. GONDOLA_CLOCK=frozen keeps it at that instant.
"""
from __future__ import annotations

import os
import time
from datetime import date as Date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

TZ = "America/New_York"
OPEN_MIN = 11 * 60
_ANCHOR: dict[str, float] = {}


def wall() -> datetime:
    """Naive local datetime in TZ (or the GONDOLA_NOW clock)."""
    v = os.getenv("GONDOLA_NOW")
    if v:
        base = datetime.fromisoformat(v).replace(tzinfo=None)
        if os.getenv("GONDOLA_CLOCK", "").lower() == "frozen":
            return base
        a = _ANCHOR.setdefault(v, time.time())
        return base + timedelta(seconds=time.time() - a)
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)


@lru_cache(maxsize=8)
def _range(db: str, version: int) -> tuple[Date, Date]:
    import duckdb
    con = duckdb.connect(db, read_only=True)
    try:
        lo, hi = con.execute("SELECT min(business_date), max(business_date) FROM orders").fetchone()
    finally:
        con.close()
    return lo.date() if hasattr(lo, "date") else lo, hi.date() if hasattr(hi, "date") else hi


def data_range(db: Path | str) -> tuple[Date, Date]:
    p = Path(db)
    return _range(str(p), p.stat().st_mtime_ns if p.exists() else 0)


def close_min(d: str | Date) -> int:
    """Closing time in minutes: 11 pm on Friday and Saturday, else 10 pm (as the live timeline uses)."""
    dd = Date.fromisoformat(str(d)[:10]) if not isinstance(d, Date) else d
    return (23 if dd.weekday() in (4, 5) else 22) * 60


DAY_CUTOFF_H = 4  # the business day runs until 4 a.m.: 1:41 am Friday is still Thursday's business day


def info(db: Path | str) -> dict:
    """{today, now, tz, mapped, open, close, phase, cutoff}. phase: before_open | open | closed. cutoff: "HH:MM"
    (orders created before it count today), or None for the full day.

    The real business date (the date 4 hours ago) is today when the data has it, cut at now. Otherwise today is the
    latest day in the data, shown as a completed (closed) day: never a time-of-day cut on a day that isn't today."""
    w = wall()
    lo, hi = data_range(db)
    biz = (w - timedelta(hours=DAY_CUTOFF_H)).date()
    mapped = not (lo <= biz <= hi)
    today = hi if mapped else biz
    cm = close_min(today)
    m = w.hour * 60 + w.minute
    if mapped or w.date() != biz:  # a past data day, or after midnight before the 4 a.m. cutoff
        phase = "closed"
    else:
        phase = "before_open" if m < OPEN_MIN else ("open" if m < cm else "closed")
    cutoff = f"{w.hour:02d}:{w.minute:02d}" if phase != "closed" else None
    return {"today": today.isoformat(), "now": w.strftime("%H:%M:%S"), "tz": TZ, "mapped": mapped,
            "business_date": biz.isoformat(), "open": f"{OPEN_MIN // 60:02d}:00", "close": f"{cm // 60:02d}:{cm % 60:02d}",
            "phase": phase, "cutoff": cutoff}


def cut(db: Path | str) -> tuple[str, str | None]:
    """(today, cutoff "HH:MM" or None) for Store(cut=...)."""
    i = info(db)
    return i["today"], i["cutoff"]
