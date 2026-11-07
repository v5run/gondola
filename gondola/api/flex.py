from fastapi import APIRouter, HTTPException, Request

from ..flex import agent, service
from ..flex.models import AcceptRequest, CartRequest, SessionRequest
from .rush import _origin, _start

router = APIRouter(prefix="/api/flex", tags=["Flexible pickup"])


def call(fn, *args):
    try: return fn(*args)
    except KeyError as exc: raise HTTPException(404, str(exc).strip("'"))
    except service.Conflict as exc: raise HTTPException(409, str(exc))
    except ValueError as exc: raise HTTPException(422, str(exc))


@router.post("/sessions")
def create(req: SessionRequest, request: Request):
    _origin(request)
    return call(service.create, req)


@router.get("/sessions/{ident}")
def get(ident: str): return call(service.get, ident)


@router.post("/sessions/{ident}/quotes")
def quote(ident: str, req: CartRequest, request: Request):
    _origin(request)
    return call(service.quote, ident, req)


@router.get("/sessions/{ident}/quotes/{qid}")
def get_quote(ident: str, qid: str): return call(service.get_quote, ident, qid)


@router.post("/sessions/{ident}/quotes/{qid}/accept")
def accept(ident: str, qid: str, req: AcceptRequest, request: Request):
    _origin(request)
    return call(service.accept, ident, qid, req.option_id)


@router.post("/sessions/{ident}/quotes/{qid}/decline")
def decline(ident: str, qid: str, request: Request):
    _origin(request)
    return call(service.decline, ident, qid)


@router.post("/sessions/{ident}/quotes/{qid}/compete")
def compete(ident: str, qid: str, req: AcceptRequest, request: Request):
    _origin(request)
    return call(service.compete, ident, qid, req.option_id)


@router.post("/sessions/{ident}/agent")
async def find(ident: str, req: CartRequest, request: Request):
    _origin(request)
    call(service.get, ident)
    return _start("flexible_pickup", {"session_id": ident, "cart": req.model_dump()}, lambda progress: agent.find_choices(ident, req, progress))
