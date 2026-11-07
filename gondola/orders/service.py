"""Durable sessions and atomic commands in the existing Rush SQLite store."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from ..rush import store
from . import engine
from .models import Advance, ApplyPlan, CapacityChange, Command, CreateSession, IncomingOrder, Intake, Session


class Conflict(ValueError):
    pass


class MissingSession(ValueError):
    pass


def demo_orders() -> list[IncomingOrder]:
    """All requests are observed together at the start of a 15-minute burst.

    This adapter is synthetic. Latest-ready windows are explicit fixture consent,
    not inferred permission to change a customer's existing promise.
    """
    orders = []
    for i in range(12):
        for channel, count in (("doordash", 12), ("ubereats", 8), ("dine_in", 5), ("pickup", 4)):
            if i >= count:
                continue
            item = ("tonkotsu", "karaage", "gyoza", "don")[len(orders) % 4]
            orders.append(IncomingOrder(order_id=f"{channel.upper()}-{i + 1:02}", channel=channel,
                          received_minute=0, requested_ready_minute=20 if channel == "dine_in" else 15,
                          latest_ready_minute=20 if channel == "dine_in" else 60,
                          commitment="confirmed" if channel == "dine_in" else "request",
                          items=[{"item": item, "quantity": 2 if i % 5 == 0 else 1}]))
    return orders


def create(req: CreateSession) -> dict:
    state = Session(policy=req.policy)
    if req.demo_burst:
        engine.receive(state, demo_orders())
    ident = uuid.uuid4().hex
    with store._connect() as con:
        con.execute("INSERT INTO artifacts VALUES (?,?,?,?,?)",
                    (ident, "demand_session", "ready", datetime.now(timezone.utc).isoformat(), json.dumps({"state": state.model_dump()})))
    return view(ident, state)


def load(ident: str) -> Session:
    row = store.get(ident)
    if row is None or row["kind"] != "demand_session":
        raise MissingSession("Unknown order management session")
    return Session.model_validate(row["state"])


def view(ident: str, state: Session) -> dict:
    return {"id": ident, **engine.observe(state)}


def plans(ident: str) -> dict:
    return engine.compare_plans(load(ident))


def execute(ident: str, command: Command, actor: str = "rules") -> dict:
    # A session can be changed by a model job, UI or another process. Hold the
    # write lock through validation and commit, not just through the final write.
    payload = {"type": type(command).__name__, "actor": actor, **command.model_dump(exclude={"revision"})}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with store._connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT kind,payload FROM artifacts WHERE id=?", (ident,)).fetchone()
        if row is None or row[0] != "demand_session":
            raise MissingSession("Unknown order management session")
        state = Session.model_validate(json.loads(row[1])["state"])
        duplicate = state.events.get(command.event_id)
        if duplicate:
            if duplicate["digest"] != digest:
                raise Conflict("Event ID already used for a different command")
            return {"session": view(ident, state), "receipt": duplicate["receipt"], "duplicate": True}
        if state.revision != command.revision:
            raise Conflict("Kitchen state changed; refresh and compare a new plan")
        if len(state.events) >= 500:
            raise Conflict("Session command limit reached; start a new service session")
        receipt = {"event_id": command.event_id, "source_mode": "local_simulation", "external_verified": False,
                   "minute": state.minute, "before_revision": state.revision, "status": "applied", "decision_mode": actor}
        if isinstance(command, Intake):
            engine.receive(state, command.orders)
            receipt.update(action="receive_orders", observed_order_keys=[o.key for o in command.orders])
        elif isinstance(command, ApplyPlan):
            proposal, candidate = engine.proposal(state, command.strategy)
            if proposal["plan_id"] != command.plan_id:
                raise Conflict("Plan expired or does not match this state and strategy")
            if not proposal["allowed"]:
                raise Conflict(proposal["reason"])
            state = candidate
            receipt.update(action="admission_plan", strategy=command.strategy, plan_id=command.plan_id,
                           decisions=proposal["actions"], protected_order_keys=[o.request.key for o in state.orders
                                                                                 if o.status in {"accepted", "completed"} and
                                                                                 o.request.key not in {a["order_key"] for a in proposal["actions"]}],
                           guard="No increased estimated lateness for any prior commitment; frozen work preserved")
        elif isinstance(command, Advance):
            engine.advance(state, command.minute)
            receipt.update(action="simulate_progress", through_minute=state.minute)
        elif isinstance(command, CapacityChange):
            state.speeds[command.station] = command.speed
            state.blocked_until[command.station] = state.minute + command.unavailable_minutes
            receipt.update(action="observe_capacity", station=command.station, speed=command.speed,
                           unavailable_until=state.blocked_until[command.station])
        else:
            raise ValueError("Unsupported order workflow command")
        state.revision += 1
        receipt["after_revision"] = state.revision
        receipt["receipt_id"] = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()[:24]
        state.receipts.append(receipt)
        state.events[command.event_id] = {"digest": digest, "receipt": receipt}
        # Validate the observable plan before persisting so an error never leaves
        # a half-imported or half-accepted batch behind.
        result = view(ident, state)
        con.execute("UPDATE artifacts SET payload=? WHERE id=?", (json.dumps({"state": state.model_dump()}), ident))
    return {"session": result, "receipt": receipt, "duplicate": False}
