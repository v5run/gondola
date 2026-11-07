"""Present API (docs/architecture/TRI_WORKFLOW_API.md): /api/present/state, /stream (SSE), /compare, /simulate,
/agent, /settings. All restaurant/courier/kitchen data is synthetic (gondola/present/world.py); writes to apps are
simulated. Additive extras: `at=HH:MM` on state/simulate/agent replays a closed day at that time (never past now).
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..present import service
from ..present import settings as pset

router = APIRouter(prefix="/api/present", tags=["Present"])


def _date(d: str | None) -> str:
    from .v3 import today
    if not d:
        return today()
    try:
        from datetime import date
        return date.fromisoformat(str(d)[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, f"bad date '{d}'")


def _at(at: str | None) -> str | None:
    if at is None:
        return None
    try:
        h, m = at.split(":")[:2]
        if not (0 <= int(h) < 30 and 0 <= int(m) < 60):
            raise ValueError
        return f"{int(h):02d}:{int(m):02d}"
    except ValueError:
        raise HTTPException(400, f"bad time '{at}' (HH:MM)")


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/state")
async def state(date: str | None = None, at: str | None = None, compare: bool = False):
    return await run_in_threadpool(_guard, service.state, _date(date), None, _at(at), None, True, compare)


@router.get("/compare")
async def compare(date: str | None = None, at: str | None = None):
    d = _date(date)
    if at:
        minute, _ = _guard(service._phase_minute, d, None, _at(at))
        return await run_in_threadpool(service.compare_at, d, minute)
    return await run_in_threadpool(service.compare, d)


@router.post("/simulate")
async def simulate(body: dict):
    action = body.get("action")
    if not isinstance(action, dict) or not action.get("action"):
        raise HTTPException(400, "body needs {date, action:{action, channel?, item?, value?}}")
    from ..present.agent import ALLOWED
    if action["action"] not in ALLOWED:
        raise HTTPException(400, f"action must be one of {', '.join(ALLOWED)}")
    return await run_in_threadpool(_guard, service.simulate, _date(body.get("date")), action, None, _at(body.get("at")))


@router.post("/agent")
async def agent(body: dict | None = None):
    body = body or {}
    from ..present import agent as ag
    try:
        return await ag.run(_date(body.get("date")), None, _at(body.get("at")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/agent/receipts")
def receipts(date: str | None = None):
    from ..present import receipts as rc
    return rc.recent(_date(date) if date else None)


@router.get("/agent/receipts/{ident}")
def receipt(ident: str):
    from ..present import receipts as rc
    r = rc.get(ident)
    if r is None:
        raise HTTPException(404, "unknown receipt")
    return r


@router.get("/settings")
def get_settings():
    return pset.load().model_dump()


@router.put("/settings")
def put_settings(body: dict):
    try:
        s = pset.merge(body)
    except Exception as e:  # pydantic ValidationError / ValueError
        raise HTTPException(400, str(e)[:500])
    return pset.save(s).model_dump()


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/stream")
async def stream(request: Request, date: str | None = None, max_s: float | None = None):
    """SSE: `state` on connect and whenever the store clock reaches a new minute (or something changed), `order` for
    each newly received order with its rank, `action` for each ladder/agent action, `done` once the day is closed.
    max_s bounds the stream's lifetime (tests)."""
    d = _date(date)

    async def gen():
        loop = asyncio.get_event_loop()
        start = loop.time()
        last_minute, seen_orders, seen_actions = None, None, None
        while True:
            st = await run_in_threadpool(service.state, d)
            if st.get("minute") != last_minute:
                ranks = {q["order_id"]: q["rank"] for q in st.get("queue") or []}
                if seen_orders is not None:
                    for q in st.get("queue") or []:
                        if q["order_id"] not in seen_orders:
                            yield _sse("order", {"order_id": q["order_id"], "channel": q["channel"], "items": q["items"],
                                                 "rank": ranks[q["order_id"]], "promise": q["promise"], "reason": q["reason"]})
                    for a in st.get("actions") or []:
                        k = (a.get("minute"), a.get("action"), a.get("channel"), a.get("item"))
                        if k not in seen_actions:
                            yield _sse("action", a)
                seen_orders = set(ranks) | (seen_orders or set())
                seen_actions = {(a.get("minute"), a.get("action"), a.get("channel"), a.get("item")) for a in st.get("actions") or []}
                yield _sse("state", st)
                last_minute = st.get("minute")
            if st.get("phase") in ("closed", "no_data"):
                yield _sse("done", {"date": d, "status": st.get("phase"), "metrics": st.get("metrics")})
                return
            if await request.is_disconnected():
                return
            if max_s is not None and loop.time() - start >= max_s:
                return
            await asyncio.sleep(1.0 if max_s is None else min(1.0, max_s))

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
