"""Future API (docs/architecture/TRI_WORKFLOW_API.md): /api/future/today, /days (tomorrow only for now), /items,
plus /arrivals, /config and an explicitly run, agent-led demo Outlook. The 2-7 day horizon remains deferred.

Clock: the store clock (gondola.now). Additive extra, as Present has: `at=HH:MM` on today/items/arrivals replays a
day at that time (never past now). Heavy pieces (morning forecast, error tables, drivers) are cached per date;
whole responses are cached per date and clock minute (days: per 15-minute bin) and per Outlook adjustment version.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date as Date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from ..future import base as B
from ..future import drivers as DR
from ..future import horizon as H
from ..future import items as IT
from ..future import nowcast as N
from ..future import outlook as O

router = APIRouter(prefix="/api/future", tags=["Future"])
_RESP = B.LRU(256)
_OUTLOOK_ADMISSION = threading.Lock()
_OUTLOOK_RUNNING = False
_OUTLOOK_LAST_START: float | None = None
_OUTLOOK_COOLDOWN = 5.0  # per process, not authentication or a distributed quota
_MAX_OUTLOOK_BODY = 1024


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
    return tuple((B._adj_version(d), O.version(d)) for d in dates)


def _drivers(date: str, now) -> list[dict]:
    db = _db()
    return B.CACHE.get(("api_drivers", str(db), B.db_version(db), date, B.history_upto(date, now, db)),
                       lambda: DR.drivers(date, db, now=now))


def _today(date: str, now, issue: bool = True) -> dict:
    db = _db()
    v = N.today_view(date, now, db, issue=issue)
    v["drivers"] = _drivers(date, now)
    v["adjustments"] = [{"driver": a["driver"], "pct": a["pct"], "evidence": a.get("evidence"), "by": a.get("by"),
                         "reason": a.get("reason")} for a in B.stored_adjustments(date)]  # legacy adjustments, separate from Outlook
    v["units"] = {"orders": "completed orders", "effect_pct": "percent", "bins": "15 minutes, store-local start time"}
    return B.json_safe(v)


@router.get("/today")
async def today(date: str | None = None, at: str | None = None):
    db = _db()
    d = _date(date, B.today_for(None, db))
    now, stamp = _moment(d, at)
    key = ("today", B.db_version(db), stamp, _adj_stamp(d), at is None)
    return await run_in_threadpool(_RESP.get, key, lambda: _today(d, now, issue=at is None))


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
    key = ("days", B.db_version(db), today_, m, s, n, _adj_stamp(today_, s))
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


@router.get("/outlook")
def outlook_status(date: str | None = None):
    db = _db()
    today_ = B.today_for(None, db)
    target = _date(date, today_)
    tomorrow = B.ddate(Date.fromisoformat(today_) + timedelta(days=1))
    if target not in (today_, tomorrow):
        raise HTTPException(400, "Outlook is available for today or tomorrow only")
    return B.json_safe(O.status(target, db=db))


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


async def _outlook_request(request: Request) -> dict:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Expected application/json")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > _MAX_OUTLOOK_BODY:
            raise HTTPException(413, "Outlook request is too large")
        data.extend(chunk)
    try:
        body = json.loads(data, object_pairs_hook=_no_duplicate_keys)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(400, "Expected a valid JSON object")
    if not isinstance(body, dict) or set(body) - {"date"}:
        raise HTTPException(400, "Expected an object with an optional date")
    date = body.get("date")
    if "date" in body and (not isinstance(date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date)):
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    if date is not None:
        try:
            Date.fromisoformat(date)
        except ValueError:
            raise HTTPException(400, "Date must be YYYY-MM-DD")
    return body


@router.post("/outlook")
async def run_outlook(request: Request):
    global _OUTLOOK_RUNNING, _OUTLOOK_LAST_START
    body = await _outlook_request(request)
    db = _db()
    today_ = B.today_for(None, db)
    target = body.get("date", today_)
    tomorrow = B.ddate(Date.fromisoformat(today_) + timedelta(days=1))
    if target not in (today_, tomorrow):
        raise HTTPException(400, "Outlook is available for today or tomorrow only")
    # Local process-only guard: prevents accidental parallel calls and rapid repeats,
    # but cannot protect a public or multi-worker deployment.
    with _OUTLOOK_ADMISSION:
        now = time.monotonic()
        if _OUTLOOK_RUNNING:
            raise HTTPException(409, "An Outlook investigation is already running")
        if _OUTLOOK_LAST_START is not None and now - _OUTLOOK_LAST_START < _OUTLOOK_COOLDOWN:
            raise HTTPException(429, "Wait a few seconds before starting another Outlook investigation",
                                headers={"Retry-After": str(int(_OUTLOOK_COOLDOWN))})
        _OUTLOOK_RUNNING, _OUTLOOK_LAST_START = True, now
    try:
        return B.json_safe(await run_in_threadpool(O.run, target, db=db))
    except O.OutlookBusy:
        raise HTTPException(409, "An Outlook investigation is already running")
    finally:
        with _OUTLOOK_ADMISSION:
            _OUTLOOK_RUNNING = False


@router.get("/config")
def config():
    return {"items": IT.limited_items(_db()), "pause_delay_min": dict(IT.plan.PAUSE_DELAY_MIN)}
