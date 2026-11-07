"""Past (the ledger): GET /api/past/summary, /api/past/ledger, /api/past/learned.
Contract: docs/architecture/TRI_WORKFLOW_API.md."""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException

from .. import now as clock
from ..ledger import ledger
from ..ledger.build import DB, ensure_day
from ..ledger.learning import learned_durations
from ..ledger.summary import summary

router = APIRouter(prefix="/api/past")


def _date(d: str | None) -> str:
    if not d:
        return clock.info(DB)["today"]
    try:
        return str(pd.Timestamp(d).date())
    except Exception:  # noqa: BLE001
        raise HTTPException(400, f"bad date '{d}'")


def _cutoff(date: str) -> str | None:
    i = clock.info(DB)
    return i["cutoff"] if date == i["today"] else None


@router.get("/summary")
def past_summary(date: str | None = None):
    d = _date(date)
    ensure_day(d, DB)
    return summary(d, _cutoff(d))


@router.get("/ledger")
def past_ledger(date: str | None = None, types: str | None = None, limit: int = 200, before_id: int | None = None):
    """Newest first (by timestamp, then id). before_id: the page after that event (from next_before_id)."""
    d = _date(date)
    ensure_day(d, DB)
    led = ledger()
    tl = [t.strip() for t in types.split(",") if t.strip()] if types else None
    limit = max(1, min(int(limit), 2000))
    end_ts, after = None, None
    if before_id is not None:
        ref = [e for e in led.query(d, tl, newest_first=True) if e.id == before_id]
        if not ref:
            raise HTTPException(400, f"before_id {before_id} is not an event of {d}")
        end_ts, after = ref[0].ts, ref[0]
    evs = led.query(d, tl, end_ts=end_ts, newest_first=True)
    if after is not None:
        evs = [e for e in evs if e.ts < after.ts or (e.ts == after.ts and e.id < after.id)]
    cut = _cutoff(d)
    if cut:  # today: never show the future, even if a writer recorded it early
        evs = [e for e in evs if e.ts[11:16] < cut or e.type in ("forecast.issued",)]
    page = evs[:limit]
    return {"date": d, "events": [e.to_dict() for e in page],
            "next_before_id": page[-1].id if len(evs) > limit else None}


@router.get("/learned")
def past_learned(date: str | None = None):
    """Prep-time learning (EMA per item and station) from task.finished events up to `date`."""
    return learned_durations(_date(date) if date else None)
