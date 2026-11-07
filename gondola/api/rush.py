from __future__ import annotations

import asyncio
from fastapi import APIRouter, HTTPException, Request

from ..rush import agents, store
from ..rush.engine import MENU, MODES, compare
from ..rush.models import AgentRequest, LabRequest, RushRequest

router = APIRouter(prefix="/api/rush", tags=["Rush Control"])
TASKS: set[asyncio.Task] = set()


@router.on_event("startup")
def recover():
    store.recover()


@router.get("/config")
def config():
    from ..config import get_settings, agents_status
    from ..metrics import ROOT
    import json
    s = get_settings()
    forecast = None
    path = ROOT / "out" / "forecasts" / "2026-11-06.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        forecast = {k: data[k] for k in ("date", "p10", "p50", "p90") if k in data}
        forecast["source"] = "Existing LightGBM forecast artifact; synthetic store history, not live weather"
    return {"menu": MENU, "modes": MODES, "data_mode": "synthetic", "campaign_mode": "simulation",
            "forecast": forecast,
            "agent_configured": agents_status()["live"], "model": s.gondola_model if s.google_api_key else None,
            "scenarios": [{"id": "rush", "name": "Event-night rush", "description": "27 accepted orders, three channels, a modeled local event and rain."},
                          {"id": "balanced", "name": "Balanced service", "description": "Varied menu demand; simpler rules may perform well."},
                          {"id": "overload", "name": "Beyond capacity", "description": "42 orders; expose commitments that cannot all be met."},
                          {"id": "quiet", "name": "Quiet evening", "description": "Ten initial orders; promotions may have more headroom."}]}


@router.post("/compare")
def comparison(req: RushRequest):
    result = compare(req)
    ident = store.create("comparison", {"request": req.model_dump()})
    store.update(ident, "done", {"request": req.model_dump(), "metrics": {k: v["metrics"] for k, v in result["runs"].items()}})
    return {"id": ident, **result}


def _origin(request: Request):
    from .security import allowed_origin
    if not allowed_origin(request):
        raise HTTPException(403, "Model jobs are limited to the local demo origin")


def _start(kind: str, inputs: dict, work) -> dict:
    if any(not t.done() for t in TASKS):
        raise HTTPException(409, "Another model job is running; wait for it to finish")
    ident = store.create(kind, {"inputs": inputs, "events": []})
    events = []

    def progress(event):
        events.append(event)
        store.update(ident, "running", {"inputs": inputs, "events": events})

    async def run():
        try:
            result = await work(progress)
            store.update(ident, "done", {"inputs": inputs, "events": events, "result": result})
        except Exception:  # provider responses may contain credentials or sensitive prompts
            store.update(ident, "failed", {"inputs": inputs, "events": events,
                         "error": "Agent job failed; no successful result is available."})
    task = asyncio.create_task(run())
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {"id": ident, "status": "running"}


@router.post("/agent")
async def start_agent(req: AgentRequest, request: Request):
    _origin(request)
    return _start("controller", req.model_dump(), lambda progress: agents.controller(req, progress))


@router.post("/lab")
async def start_lab(req: LabRequest, request: Request):
    _origin(request)
    return _start("policy_lab", req.model_dump(), lambda progress: agents.policy_lab(req.objective, progress))


@router.get("/history")
def history():
    return store.recent()


@router.get("/jobs/{ident}")
def job(ident: str):
    result = store.get(ident)
    if result is None:
        raise HTTPException(404, "Unknown Rush Control receipt")
    return result
