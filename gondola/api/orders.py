"""Nested order management workflow. All execution is local simulation."""
from fastapi import APIRouter, HTTPException, Request

from ..agents.order_manager import run_order_management
from ..orders import service
from ..orders.models import Advance, AgentCommand, ApplyPlan, CapacityChange, CreateSession, Intake
from ..rush.engine import MENU
from ..rush import store
from .rush import _origin, _start

router = APIRouter(prefix="/api/demand", tags=["Back House order management"])


def call(fn, *args):
    try:
        return fn(*args)
    except service.MissingSession as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/config")
def config():
    from ..config import agents_status
    return {"menu": MENU, "channels": ["doordash", "ubereats", "dine_in", "pickup"],
            "agent_configured": agents_status()["live"], "agent_count": 1,
            "source_mode": "local_simulation", "external_writes": False}


@router.get("/sessions")
def sessions():
    with store._connect() as con:
        rows = con.execute("SELECT id,created FROM artifacts WHERE kind='demand_session' ORDER BY created DESC LIMIT 20").fetchall()
    return [{"id": row[0], "created": row[1]} for row in rows]


@router.post("/sessions")
def create(req: CreateSession, request: Request):
    _origin(request)
    return call(service.create, req)


@router.get("/sessions/{ident}")
def session(ident: str):
    return call(lambda: service.view(ident, service.load(ident)))


@router.get("/sessions/{ident}/plans")
def plans(ident: str):
    return call(service.plans, ident)


@router.post("/sessions/{ident}/orders")
def intake(ident: str, req: Intake, request: Request):
    _origin(request)
    return call(service.execute, ident, req)


@router.post("/sessions/{ident}/apply")
def apply(ident: str, req: ApplyPlan, request: Request):
    _origin(request)
    return call(service.execute, ident, req)


@router.post("/sessions/{ident}/advance")
def advance(ident: str, req: Advance, request: Request):
    _origin(request)
    return call(service.execute, ident, req)


@router.post("/sessions/{ident}/capacity")
def capacity(ident: str, req: CapacityChange, request: Request):
    _origin(request)
    return call(service.execute, ident, req)


@router.post("/sessions/{ident}/agent")
async def agent(ident: str, req: AgentCommand, request: Request):
    _origin(request)
    state = call(service.load, ident)
    if state.revision != req.revision:
        raise HTTPException(409, "Kitchen state changed; refresh before starting the agent")
    return _start("order_manager", {"session_id": ident, "revision": req.revision},
                  lambda progress: run_order_management(ident, req.revision, progress))
