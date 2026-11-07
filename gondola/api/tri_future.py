"""Future API (docs/architecture/TRI_WORKFLOW_API.md): /api/future/today, /days (tomorrow only for now), /items,
plus /arrivals (the Present contract over HTTP) and /config (limited-item config). The Outlook agent
(POST /future/outlook) and the 2-7 day horizon are deferred (scope decision, Nov 7).

Clock: the store clock (gondola.now). Additive extra, as Present has: `at=HH:MM` on today/items/arrivals replays a
day at that time (never past now). Heavy pieces (morning forecast, error tables, drivers) are cached per date;
whole responses are cached per date and clock minute (days: per 15-minute bin) and per Outlook adjustment version.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from ..future import base as B
from ..future import drivers as DR
from ..future import horizon as H
from ..future import items as IT
from ..future import nowcast as N

router = APIRouter(prefix="/api/future", tags=["Future"])
_RESP = B.LRU(256)


def _db():
    from .v3 import DB
    return DB


def _date(d: str | None, default: str) -> str:
    if not d:
        return default
    try:
        return Date.fromisoformat(str(d)[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, f"bad date '{d}'")


def _moment(date: str, at: str | None) -> tuple[datetime | None, str]:
    """(now to use, cache stamp). at=HH:MM replays `date` at that time, never past the store clock."""
    db = _db()
    today = B.today_for(None, db)
    if date > today:
        raise HTTPException(400, f"{date} is after today ({today}); use /api/future/days for future dates")
    real_m = B.cut_minute(date, None, db)
    if at is None:
        return None, f"{date}:{min(real_m, B.FULL_DAY)}"
    try:
        h, m = (int(x) for x in at.split(":")[:2])
        if not (0 <= h < 28 and 0 <= m < 60):
            raise ValueError
    except ValueError:
        raise HTTPException(400, f"bad time '{at}' (HH:MM)")
    want = min(h * 60 + m, real_m)
    return datetime.combine(Date.fromisoformat(date), datetime.min.time()) + timedelta(minutes=want), f"{date}:{want}"


def _adj_stamp(*dates: str) -> tuple:
    return tuple(B._adj_version(d) for d in dates)


def _drivers(date: str, now) -> list[dict]:
    db = _db()
    return B.CACHE.get(("api_drivers", str(db), B.db_version(db), date, B.history_upto(date, now, db)),
                       lambda: DR.drivers(date, db, now=now))


def _today(date: str, now) -> dict:
    db = _db()
    v = N.today_view(date, now, db, issue=True)
    v["drivers"] = _drivers(date, now)
    v["adjustments"] = [{"driver": a["driver"], "pct": a["pct"], "evidence": a.get("evidence"), "by": a.get("by"),
                         "reason": a.get("reason")} for a in B.stored_adjustments(date)]  # Outlook agent deferred: []
    v["units"] = {"orders": "completed orders", "effect_pct": "percent", "bins": "15 minutes, store-local start time"}
    return B.json_safe(v)


@router.get("/today")
async def today(date: str | None = None, at: str | None = None):
    db = _db()
    d = _date(date, B.today_for(None, db))
    now, stamp = _moment(d, at)
    key = ("today", B.db_version(db), stamp, _adj_stamp(d))
    return await run_in_threadpool(_RESP.get, key, lambda: _today(d, now))


@router.get("/arrivals")
async def arrivals(date: str | None = None, at: str | None = None):
    """Present's contract over HTTP: [{time, channel, p10, p50, p90}] for the remaining bins."""
    db = _db()
    d = _date(date, B.today_for(None, db))
    now, stamp = _moment(d, at)
    key = ("arrivals", B.db_version(db), stamp, _adj_stamp(d))
    return await run_in_threadpool(_RESP.get, key, lambda: N.arrivals(d, now, db))


def _days(start: str | None, n: int) -> list[dict]:
    db = _db()
    rows = H.days(start, n, db=db)
    H.issue_events(rows, B.today_for(None, db))
    return B.json_safe(rows)


@router.get("/days")
async def days(start: str | None = None, n: int = 1):
    """Tomorrow only for now (the 2-7 day horizon is deferred): start must be tomorrow and n 1."""
    db = _db()
    today_ = B.today_for(None, db)
    tomorrow = B.ddate(Date.fromisoformat(today_) + timedelta(days=1))
    s = _date(start, tomorrow)
    if s != tomorrow:
        raise HTTPException(400, f"only tomorrow ({tomorrow}) is available; past days are not forecasts")
    if n != 1:
        raise HTTPException(400, "n must be 1 (the 2-7 day horizon is not enabled)")
    m = B.cut_minute(today_, None, db)
    key = ("days", B.db_version(db), today_, m // 15, s, n, _adj_stamp(s))
    return await run_in_threadpool(_RESP.get, key, lambda: _days(s, n))


def _items(date: str, now) -> dict:
    db = _db()
    rows = IT.runout(date, now, db)
    return B.json_safe({"date": date, "items": rows, "config": IT.limited_items(db)})


@router.get("/items")
async def items(date: str | None = None, at: str | None = None):
    db = _db()
    d = _date(date, B.today_for(None, db))
    now, stamp = _moment(d, at)
    key = ("items", B.db_version(db), stamp, _adj_stamp(d))
    return await run_in_threadpool(_RESP.get, key, lambda: _items(d, now))


@router.get("/config")
def config():
    return {"items": IT.limited_items(_db()), "pause_delay_min": dict(IT.plan.PAUSE_DELAY_MIN)}
