"""Review: exceptions inbox, day review, knowledge base, action items, digests and agent contexts.
Contract: docs/architecture/TRI_WORKFLOW_API.md (all under /api/review)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Body, HTTPException

from .. import now as clock
from ..kb import KINDS, kb
from ..ledger.build import DB, ensure_day
from ..review import context as ctx
from ..review import digests as D
from ..review import exceptions as X

router = APIRouter(prefix="/api/review")


@router.on_event("startup")
def _start_loop():
    X.start_loop(60.0, DB)  # every minute while open; GONDOLA_REVIEW_LOOP=0 disables


def _date(d: str | None) -> str:
    if not d:
        return clock.info(DB)["today"]
    try:
        return str(pd.Timestamp(d).date())
    except Exception:  # noqa: BLE001
        raise HTTPException(400, f"bad date '{d}'")


def _closed(date: str) -> bool:
    i = clock.info(DB)
    return date < i["today"] or (date == i["today"] and i["phase"] == "closed")


# ------------------------------------------------------------------ exceptions
@router.get("/exceptions")
def exceptions(date: str | None = None):
    d = _date(date)
    return [{k: x.get(k) for k in ("id", "ts", "kind", "severity", "title", "decision", "note", "resolved", "by", "evidence", "alert")}
            for x in sorted(X.raised(d), key=lambda x: x["ts"], reverse=True)]


@router.post("/exceptions/{exc_id}/resolve")
def resolve(exc_id: str, body: dict | None = Body(None)):
    d = (body or {}).get("date") or exc_id.split(":")[0]
    d = _date(d)
    i = clock.info(DB)
    ts = f"{d}T{i['now']}" if d == i["today"] else datetime.now().isoformat(timespec="seconds")
    ok = X.resolve(d, exc_id, by=(body or {}).get("by", "manager"), ts=ts)
    if not ok:
        raise HTTPException(404, f"no exception '{exc_id}' on {d}")
    return {"ok": True}


@router.post("/scan")
def scan(body: dict | None = Body(None)):
    d = _date((body or {}).get("date"))
    ensure_day(d, DB)
    i = clock.info(DB)
    live = d == i["today"] and i["phase"] == "open"
    return X.scan(d, None, db=DB, send=live)


@router.get("/loop")
def loop():
    return X.loop_status()


# ------------------------------------------------------------------ day review
def _day(d: str) -> dict:
    r = D.digests().review(d)
    if not r:
        return {"date": d, "status": "not_run" if _closed(d) else "open", "well": [], "wrong": [], "causes": [], "actions": [],
                "kb_changes": [], "digest_id": None}
    acts = []
    for a in r.get("actions", []):
        it = kb().get(a["id"]) or {}
        acts.append({**a, "status": it.get("action_status", a.get("status")), "outcome": it.get("outcome")})
    return {**r, "actions": acts}


@router.get("/day/{date}")
def day(date: str):
    return _day(_date(date))


@router.post("/run")
def run(body: dict | None = Body(None)):
    d = _date((body or {}).get("date"))
    if not _closed(d):
        raise HTTPException(409, f"{d} is not closed yet")
    from ..review.agent import run_review
    run_review(d, db=DB)
    return _day(d)


# ------------------------------------------------------------------ knowledge base
@router.get("/kb")
def kb_list(status: str | None = None, kind: str | None = None):
    if kind and kind not in KINDS:
        raise HTTPException(400, f"unknown kind '{kind}'")
    st = [s for s in status.split(",") if s] if status else None
    items = kb().list(st, kind)
    return sorted(items, key=lambda x: (x.get("status") != "needs_approval", -(x.get("confidence") or 0), x["id"]))


@router.get("/kb/{item_id}")
def kb_item(item_id: str):
    it = kb().get(item_id)
    if not it:
        raise HTTPException(404, f"no item '{item_id}'")
    return {**it, "history": kb().history(item_id, limit=20)}


@router.post("/kb/{item_id}/approve")
def kb_approve(item_id: str, body: dict | None = Body(None)):
    it = kb().approve(item_id, clock.info(DB)["today"], by=(body or {}).get("by", "manager"))
    if not it:
        raise HTTPException(404, f"no item '{item_id}'")
    return {"ok": it["status"] == "active", "item": it}


@router.post("/kb/{item_id}/retire")
def kb_retire(item_id: str, body: dict | None = Body(None)):
    it = kb().retire(item_id, (body or {}).get("reason", "retired by manager"), clock.info(DB)["today"])
    if not it:
        raise HTTPException(404, f"no item '{item_id}'")
    return {"ok": True, "item": it}


# ------------------------------------------------------------------ action items
@router.get("/actions")
def actions(status: str | None = None):
    out = []
    for a in kb().list(None, "action_item"):
        if a.get("status") == "rejected":
            continue
        s = a.get("action_status") or "open"
        if status and s not in status.split(","):
            continue
        out.append({"id": a["id"], "text": a.get("statement"), "owner": a.get("owner"), "created": a.get("created"),
                    "check_on": a.get("check_on"), "measure": a.get("measure"), "status": s, "outcome": a.get("outcome"),
                    "progress": a.get("progress")})
    return sorted(out, key=lambda x: (x["status"] != "open", x["check_on"] or ""))


@router.post("/actions/{item_id}/status")
def action_status(item_id: str, body: dict = Body(...)):
    """The manager closes (or reopens) an action item: body {status: done|not_working|open, note?}."""
    st = body.get("status")
    if st not in ("done", "not_working", "open"):
        raise HTTPException(400, "status must be done, not_working or open")
    k = kb()
    it = k.get(item_id)
    if not it or it.get("kind") != "action_item":
        raise HTTPException(404, f"no action item '{item_id}'")
    today = clock.info(DB)["today"]
    it.update(action_status=st, outcome={"checked_on": today, "by": body.get("by", "manager"), "note": body.get("note")})
    if st == "open":
        it["status"] = "active"
    k.save(it, "manager_status", today, {"status": st})
    if st != "open":
        it = k.retire(item_id, f"{st} (manager)", today)
    return {"ok": True, "item": it}


# ------------------------------------------------------------------ digests and contexts
@router.get("/digests")
def digest_list(kind: str = "day", limit: int = 30):
    if kind not in ("shift", "day", "week", "month"):
        raise HTTPException(400, "kind must be shift, day, week or month")
    return [{"id": d["id"], "kind": d["kind"], "period": d["period"], "summary": d.get("summary") or " ".join(d.get("bullets") or []),
             "numbers": d.get("numbers"), **({"wrong": d.get("wrong"), "well": d.get("well")} if kind == "day" else {}),
             **({"wrong_themes": d.get("wrong_themes")} if kind in ("week", "month") else {}),
             **({"bullets": d.get("bullets")} if kind == "shift" else {})}
            for d in D.digests().list(kind, limit=max(1, min(int(limit), 400)))]


@router.get("/context")
def context(agent: str = "review", date: str | None = None):
    d = _date(date)
    ensure_day(d, DB)
    try:
        return ctx.build(agent, d)
    except KeyError as e:
        raise HTTPException(400, str(e).strip("'\""))
