"""Observed-work admission and dispatch. No LLM, I/O or private simulator truth."""
from __future__ import annotations

import hashlib
import json
import math

from ..rush.engine import MENU, STATIONS
from ..rush.reservations import Reservations
from .models import IncomingOrder, ManagedOrder, Session, Task

STRATEGIES = {"current": "Protect current queue", "arrival": "Arrival order",
              "promise": "Earliest promise", "slack": "Least remaining slack"}


def tasks_for(order: IncomingOrder) -> list[Task]:
    tasks = [Task(id=f"{order.key}:{line.item}:{i}", station=MENU[line.item]["station"],
                  item=line.item, nominal=MENU[line.item]["minutes"])
             for line in order.items for i in range(line.quantity)]
    tasks.append(Task(id=order.key + ":finish", station="packing", item="finish", nominal=1))
    return tasks


def remaining(state: Session, order: ManagedOrder) -> float:
    return sum(max(0, t.nominal - t.progress) / state.speeds[t.station]
               for t in (order.tasks or tasks_for(order.request)) if t.end is None)


def priority_key(state: Session, order: ManagedOrder, strategy: str):
    due = order.promise if order.promise is not None else order.request.requested_ready_minute
    first = order.request.received_minute if strategy in {"current", "arrival"} else due
    if strategy == "slack":
        first -= remaining(state, order)
    ordinal = next(i for i, seen in enumerate(state.orders) if seen.request.key == order.request.key)
    return first, order.request.received_minute, ordinal


def schedule(state: Session) -> list[dict]:
    active = [o for o in state.orders if o.status == "accepted"]
    # Confirmed upstream work cannot disappear just because it exceeds a normal
    # quote horizon. A serialized upper bound keeps its risk visible.
    effort = sum(max(1, math.ceil((t.nominal - t.progress) / state.speeds[t.station]))
                 for o in active for t in o.tasks if t.end is None)
    downtime = sum(max(0, until - state.minute) for until in state.blocked_until.values())
    book = Reservations(state.minute, state.policy.cooks, STATIONS, state.blocked_until,
                        state.minute + max(480, effort + downtime))
    ends = {}
    for o in active:
        for task in o.tasks:
            if task.end is not None:
                ends[task.id] = task.end
            elif task.start is not None:
                duration = max(1, math.ceil((task.nominal - task.progress) / state.speeds[task.station]))
                duration += max(0, state.blocked_until.get(task.station, state.minute) - state.minute)
                row = book.reserve(task.id, o.request.key, task.station, state.minute, duration, task.item, True)
                ends[task.id] = row["end"]
    rank = {key: i for i, key in enumerate(state.priority)}
    for o in sorted(active, key=lambda o: (rank.get(o.request.key, len(rank)), o.request.received_minute, o.request.key)):
        for task in o.tasks:
            if task.id in ends:
                continue
            earliest = state.minute
            if task.station == "packing":
                earliest = max([earliest] + [ends[t.id] for t in o.tasks if t.station != "packing"])
            duration = max(1, math.ceil(task.nominal / state.speeds[task.station]))
            row = book.place(task.id, o.request.key, task.station, earliest, duration, task.item)
            ends[task.id] = row["end"]
    return book.rows


def finishes(rows: list[dict]) -> dict[str, int]:
    return {r["order_id"]: r["end"] for r in rows if r["station"] == "packing"}


def expire(state: Session):
    for o in state.orders:
        if o.status == "pending" and state.minute >= o.request.received_minute + state.policy.response_minutes:
            o.status, o.decision = "expired", "expired"
            o.reason = "Local response deadline passed; no acceptance was sent"


def commit_order(state: Session, order: ManagedOrder, promise: int, decision: str):
    order.status, order.promise, order.decision = "accepted", promise, decision
    order.tasks = tasks_for(order.request)
    order.reason = "Reserved shared cooks, stations and finishing capacity within the authorized ready window"
    state.priority.append(order.request.key)
    for line in order.request.items:
        state.stock[line.item] -= line.quantity


def receive(state: Session, requests: list[IncomingOrder]):
    known = {o.request.key: o for o in state.orders}
    for request in requests:
        if request.received_minute > state.minute:
            raise ValueError("Future orders cannot enter observed state")
        if request.key in known:
            if known[request.key].request != request:
                raise ValueError("Order identity already exists with different contents")
            continue
        if len(state.orders) >= 120:
            raise ValueError("This local service session is limited to 120 orders")
        if sum(line.quantity for o in state.orders for line in o.request.items) + sum(line.quantity for line in request.items) > 240:
            raise ValueError("This local service session is limited to 240 portions")
        order = ManagedOrder(request=request)
        state.orders.append(order); known[request.key] = order
        if request.commitment == "confirmed":
            commit_order(state, order, request.requested_ready_minute, "imported_commitment")
            order.reason = "Already confirmed upstream; promise preserved even if capacity or stock is insufficient"
    expire(state)


def proposal(state: Session, strategy: str) -> tuple[dict, Session]:
    if strategy not in STRATEGIES:
        raise ValueError("Unknown admission priority")
    proposed = state.model_copy(deep=True)
    expire(proposed)
    before = finishes(schedule(state))
    active = [o for o in proposed.orders if o.status == "accepted"]
    if strategy != "current":
        proposed.priority = [o.request.key for o in sorted(active, key=lambda o: priority_key(proposed, o, strategy))]
    after = finishes(schedule(proposed))
    worsened = [o.request.key for o in active
                if max(0, after[o.request.key] - o.promise) > max(0, before[o.request.key] - o.promise)]
    actions = []
    pending = sorted((o for o in proposed.orders if o.status == "pending"),
                     key=lambda o: priority_key(proposed, o, state.policy.default_priority if strategy == "current" else strategy))
    for o in pending if not worsened else []:
        request = o.request
        shortages = [line.item for line in request.items if proposed.stock[line.item] < line.quantity]
        reason = None
        predicted = None
        promise = None
        if shortages:
            reason = "Insufficient unreserved stock: " + ", ".join(shortages)
        else:
            probe = proposed.model_copy(deep=True)
            probe_order = next(x for x in probe.orders if x.request.key == request.key)
            commit_order(probe, probe_order, request.requested_ready_minute, "probe")
            try:
                predicted = finishes(schedule(probe))[request.key]
                promise = max(request.requested_ready_minute, predicted + state.policy.reserve_minutes)
                latest = min(request.latest_ready_minute or request.requested_ready_minute,
                             request.received_minute + state.policy.max_lead_minutes)
                if promise > latest:
                    reason = f"Capacity needs ready minute {promise}; authorized/owner limit is {latest}"
            except ValueError:
                reason = "Work exceeds the bounded planning horizon"
        decision = "decline" if reason else "accept_now" if promise == request.requested_ready_minute else "accept_later"
        if reason:
            o.status, o.decision, o.reason = "declined", decision, reason
        else:
            commit_order(proposed, o, promise, decision)
        actions.append({"order_key": request.key, "decision": decision, "promise": None if reason else promise,
                        "predicted_ready": predicted, "reason": o.reason})
    plan = schedule(proposed)
    projected = finishes(plan)
    existing_lateness = sum(max(0, after[o.request.key] - o.promise) for o in active)
    public = {"revision": state.revision, "strategy": strategy, "label": STRATEGIES[strategy],
              "allowed": not worsened, "worsened_orders": worsened,
              "reason": "Would worsen a confirmed order's estimated lateness" if worsened else
                        "Every committed order passes the lateness guard; only unstarted work may move",
              "actions": actions, "accepted_now": sum(a["decision"] == "accept_now" for a in actions),
              "accepted_later": sum(a["decision"] == "accept_later" for a in actions),
              "declined": sum(a["decision"] == "decline" for a in actions),
              "extension_minutes": sum((a["promise"] or o.request.requested_ready_minute) - o.request.requested_ready_minute
                                       for a, o in zip(actions, pending)),
              "existing_late_minutes": existing_lateness, "plan": plan}
    public["remaining_flow_minutes"] = sum(projected[o.request.key] - state.minute for o in proposed.orders if o.status == "accepted")
    public["commitment_forecast"] = [{"order_key": o.request.key, "promise": o.promise,
                                      "before_ready": before[o.request.key], "after_ready": after[o.request.key]}
                                     for o in active]
    public["next_work"] = sorted((r for r in plan if not r["frozen"]), key=lambda r: r["start"])[:6]
    fingerprint = {"state": state.model_dump(), "proposal": public}
    public["plan_id"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:24]
    return public, proposed


def compare_plans(state: Session) -> dict:
    plans = [proposal(state, strategy)[0] for strategy in STRATEGIES]
    best = min((p for p in plans if p["allowed"]),
               key=lambda p: (-(p["accepted_now"] + p["accepted_later"]), p["extension_minutes"],
                              p["existing_late_minutes"], p["remaining_flow_minutes"]))
    return {"revision": state.revision, "plans": plans, "recommended": best["strategy"],
            "scope": "Observed requests and commitments only; one atomic local plan, not a merchant API write"}


def advance(state: Session, minute: int):
    if not state.minute <= minute <= min(240, state.minute + 120):
        raise ValueError("Advance must be forward by at most 120 simulated minutes")
    while state.minute < minute:
        rows = schedule(state)
        starts = {r["task_id"] for r in rows if r["start"] == state.minute}
        for o in state.orders:
            if o.status != "accepted":
                continue
            for t in o.tasks:
                if t.start is None and t.id in starts:
                    t.start = state.minute
                if t.start is None or t.end is not None or state.blocked_until.get(t.station, 0) > state.minute:
                    continue
                t.progress += state.speeds[t.station]
                if t.progress + 1e-9 >= t.nominal:
                    t.end = state.minute + 1
            if o.tasks[-1].end is not None:
                o.status = "completed"
        state.minute += 1
        expire(state)


def observe(state: Session) -> dict:
    rows = schedule(state)
    projected = finishes(rows)
    now, horizon = state.minute, 15
    stations = []
    for station in STATIONS:
        occupied = {m for r in rows if r["station"] == station
                    for m in range(max(now, r["start"]), min(now + horizon, r["end"]))}
        occupied.update(range(now, min(now + horizon, state.blocked_until.get(station, now))))
        stations.append({"id": station, "load": round(len(occupied) / horizon, 3), "speed": state.speeds[station],
                         "blocked_until": state.blocked_until.get(station, 0)})
    orders = []
    for o in state.orders:
        ready = projected.get(o.request.key, o.tasks[-1].end if o.tasks else None)
        orders.append({"key": o.request.key, **o.request.model_dump(), "status": o.status, "decision": o.decision,
                       "promise": o.promise, "predicted_ready": ready, "reason": o.reason,
                       "response_deadline": o.request.received_minute + state.policy.response_minutes,
                       "at_risk": o.status == "accepted" and ready > o.promise,
                       "tasks": [t.model_dump() for t in o.tasks]})
    cook_minutes = sum(max(0, min(now + horizon, r["end"]) - max(now, r["start"]))
                       for r in rows if r["station"] != "packing")
    return {"revision": state.revision, "minute": now, "policy": state.policy.model_dump(),
            "source_mode": "local_simulation", "external_writes": False, "orders": orders, "plan": rows,
            "stations": stations, "stock": state.stock,
            "shared_cook_utilization": round(cook_minutes / (horizon * state.policy.cooks), 3),
            "counts": {s: sum(o["status"] == s for o in orders) for s in ("pending", "accepted", "declined", "expired", "completed")},
            "at_risk": sum(o["at_risk"] for o in orders),
            "stock_shortfalls": {k: -v for k, v in state.stock.items() if v < 0},
            "receipts": state.receipts[-20:],
            "limits": "Declared menu estimates and simulated completions, not live kitchen telemetry. Readiness estimates can change after a disruption."}
