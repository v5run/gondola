"""One specialist inside the existing ADK orchestration runtime.

The model selects evidence-backed plans; the workflow commits only after the
model stops successfully. A timeout or narration cannot partially admit a batch.
"""
from __future__ import annotations

import uuid
from typing import Callable

from ..orders import engine, service
from ..orders.models import ApplyPlan
from ..rush.agents import _run


async def run_order_management(session_id: str, revision: int, progress: Callable) -> dict:
    state = service.load(session_id)
    if state.revision != revision:
        raise service.Conflict("Kitchen state changed before the agent started; refresh first")
    trace, selected = [], []
    inspected = False
    compared = {}

    def record(tool, args, result):
        if len(trace) >= 14:
            raise ValueError("Order Manager tool budget exhausted")
        trace.append({"tool": tool, "args": args, "result": result})
        progress({"kind": "tool", "tool": tool, "args": args, "result": result})
        return result

    def inspect_demand() -> dict:
        """Read only observed orders, accepted promises, station pressure, stock and owner policy."""
        nonlocal inspected
        inspected = True
        observed = engine.observe(state)
        # Receipts/history and complete task arrays are not needed by this
        # decision; preserve exact current readiness/stock/capacity evidence.
        observed.pop("receipts")
        observed.pop("plan")
        for order in observed["orders"]:
            order.pop("tasks")
        return record("inspect_demand", {}, observed)

    def compare_admission_plans() -> dict:
        """Compare protected current queue, arrival, promise and slack plans. Numbers are computed by code."""
        result = engine.compare_plans(state)
        compared.update({p["plan_id"]: p for p in result["plans"]})
        compact = {**result, "plans": [{k: v for k, v in p.items() if k != "plan"} for p in result["plans"]]}
        return record("compare_admission_plans", {}, compact)

    def select_checked_plan(plan_id: str) -> dict:
        """Select ONE compared plan by exact ID. Selection is not execution.

        The workflow rechecks the session version and atomically commits after
        the model stops. No external platform writes are available.
        """
        plan = compared.get(plan_id)
        if selected:
            result = {"status": "rejected", "reason": "One selection per workflow"}
        elif not inspected or plan is None:
            result = {"status": "rejected", "reason": "Inspect demand and compare the exact plan before selecting"}
        elif not plan["allowed"]:
            result = {"status": "rejected", "reason": plan["reason"]}
        else:
            selected.append(plan)
            result = {"status": "selected", "plan_id": plan_id, "strategy": plan["strategy"],
                      "execution": "Pending version check and atomic local commit after the model stops"}
        return record("select_checked_plan", {"plan_id": plan_id}, result)

    meta = await _run("order_manager",
                     "You are Gondola's sole Order Manager for the Back House capacity workflow. "
                     "Inspect current demand and compare checked admission plans, then select exactly one allowed plan by its exact ID. "
                     "Favor more feasible accepted orders, then shorter authorized extensions, less existing lateness and lower remaining flow time; use actual tool evidence. "
                     "All channels share cooks, stations and finishing capacity. Existing commitments and work in progress are protected. "
                     "A new order may have a later ready time only inside its explicit authorized window and owner lead-time cap. "
                     "Never change an accepted promise, invent consent, add cooks or claim an external acceptance. "
                     "A selection is not yet applied: stop after selecting so the workflow can revalidate and commit. "
                     "Rejected plans are not success. If overloaded, preserve truthful declines/risks. "
                     "This is a local synthetic/manual-input simulation, not live platform orders or kitchen telemetry.",
                     [inspect_demand, compare_admission_plans, select_checked_plan], progress,
                     "Manage this observed inbox and kitchen capacity under the supplied policy. Select one checked admission/priority plan.")
    if not selected:
        raise ValueError("No checked plan was selected; no admission plan was committed")
    plan = selected[0]
    event_id = "agent-" + uuid.uuid4().hex
    result = service.execute(session_id, ApplyPlan(event_id=event_id, revision=revision,
                                                  strategy=plan["strategy"], plan_id=plan["plan_id"]), actor="model_selected")
    persisted = service.load(session_id).events.get(event_id)
    if not persisted or persisted["receipt"]["receipt_id"] != result["receipt"]["receipt_id"]:
        raise ValueError("Local receipt read-back failed; inspect the persisted session before retrying")
    progress({"kind": "receipt", "result": result["receipt"]})
    return {**meta, "workflow": "order_management", "agent_mode": "live_model", "data_mode": "local_simulation",
            "trace": trace, "receipt": result["receipt"], "session_id": session_id,
            "revision": result["session"]["revision"], "local_receipt_verified": True, "external_verified": False}
