"""Order workflow acceptance: capacity, consent, persistence and model failures.

All data and model responses are local fixtures. No merchant/provider calls.
"""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gondola.agents import order_manager
from gondola.orders import engine, service
from gondola.orders.models import Advance, ApplyPlan, CapacityChange, CreateSession, IncomingOrder, Intake, Session
from gondola.rush import store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "workflow.sqlite3")


def incoming(ident="A", channel="pickup", **overrides):
    return IncomingOrder.model_validate({"order_id": ident, "channel": channel, "received_minute": 0,
                 "requested_ready_minute": 15, "items": [{"item": "karaage", "quantity": 1}], **overrides})


def test_durable_sessions_and_other_workflows_do_not_pollute_rush_history():
    service.create(CreateSession())
    for kind in ("controller", "policy_lab", "order_manager", "flexible_pickup"):
        store.create(kind, {"events": []})
    assert {r["kind"] for r in store.recent()} == {"controller", "policy_lab"}


def test_session_connection_is_closed_after_transaction():
    import sqlite3
    with store._connect() as con:
        con.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute("SELECT 1")


def apply_best(session):
    plans = service.plans(session["id"])
    plan = next(p for p in plans["plans"] if p["strategy"] == plans["recommended"])
    return service.execute(session["id"], ApplyPlan(event_id="apply", revision=session["revision"],
                                                   strategy=plan["strategy"], plan_id=plan["plan_id"]))


def assert_resources(rows, cooks):
    for minute in range(max([r["end"] for r in rows] or [0])):
        active = [r for r in rows if r["start"] <= minute < r["end"]]
        assert len({r["station"] for r in active}) == len(active)
        assert sum(r["station"] != "packing" for r in active) <= cooks


@pytest.mark.parametrize("cooks", [1, 2, 3, 4])
def test_exact_burst_atomic_admission_and_complete_outcomes(cooks):
    session = service.create(CreateSession(demo_burst=True, policy={"cooks": cooks}))
    assert {ch: sum(o["channel"] == ch for o in session["orders"]) for ch in ("doordash", "ubereats", "dine_in", "pickup")} == {
        "doordash": 12, "ubereats": 8, "dine_in": 5, "pickup": 4}
    original_promises = {o["key"]: o["promise"] for o in session["orders"] if o["status"] == "accepted"}
    original_ready = {o["key"]: o["predicted_ready"] for o in session["orders"] if o["status"] == "accepted"}
    result = apply_best(session)
    final = result["session"]
    assert sum(final["counts"].values()) == 29 and not final["counts"]["pending"]
    assert final["counts"]["declined"] > 0
    assert len(result["receipt"]["decisions"]) == 24
    assert all(v >= 0 for v in final["stock"].values())
    for order in final["orders"]:
        if order["key"] in original_promises:
            assert order["promise"] == original_promises[order["key"]]
            assert max(0, order["predicted_ready"] - order["promise"]) <= max(0, original_ready[order["key"]] - order["promise"])
        elif order["status"] == "accepted":
            assert order["requested_ready_minute"] <= order["promise"] <= (order["latest_ready_minute"] or order["requested_ready_minute"])
            assert order["predicted_ready"] + final["policy"]["reserve_minutes"] <= order["promise"]
    assert_resources(final["plan"], cooks)
    assert not result["receipt"]["external_verified"]
    progressed = service.execute(final["id"], Advance(event_id="progress", revision=final["revision"], minute=120))["session"]
    assert progressed["counts"]["accepted"] == 0
    assert progressed["counts"]["completed"] + progressed["counts"]["declined"] == 29


def test_no_invented_consent_or_silent_change_to_confirmed_promise():
    state = Session()
    engine.receive(state, [incoming("FIXED", requested_ready_minute=4),
                           incoming("WINDOW", requested_ready_minute=4, latest_ready_minute=30)])
    _, selected = engine.proposal(state, "current")
    assert selected.orders[0].status == "declined"
    assert selected.orders[1].decision == "accept_later" and selected.orders[1].promise == 8
    confirmed = Session()
    engine.receive(confirmed, [incoming(commitment="confirmed", requested_ready_minute=4)])
    observed = engine.observe(confirmed)
    assert observed["orders"][0]["promise"] == 4 and observed["at_risk"] == 1
    assert engine.proposal(confirmed, "current")[1].orders[0].promise == 4


def test_multiple_lines_quantities_finish_only_after_all_cooking():
    state = Session()
    engine.receive(state, [incoming(items=[{"item": "karaage", "quantity": 2}, {"item": "tonkotsu", "quantity": 3}],
                                     latest_ready_minute=60)])
    _, accepted = engine.proposal(state, "current")
    rows = engine.schedule(accepted)
    assert len(rows) == 6  # Five cooking portions and one complete-order finish.
    assert next(r for r in rows if r["station"] == "packing")["start"] >= max(r["end"] for r in rows if r["station"] != "packing")
    assert_resources(rows, 3)


def test_stock_and_owner_lead_time_are_hard_limits():
    state = Session(policy={"max_lead_minutes": 15})
    state.stock["karaage"] = 1
    engine.receive(state, [incoming("TOO-MANY", items=[{"item": "karaage", "quantity": 2}], latest_ready_minute=60),
                           incoming("SLOW", items=[{"item": "tonkotsu", "quantity": 10}], latest_ready_minute=60)])
    _, result = engine.proposal(state, "current")
    assert all(o.status == "declined" for o in result.orders)
    assert result.stock["karaage"] == 1


def test_deadline_expiry_is_distinct_from_later_ready_time():
    state = Session()
    engine.receive(state, [incoming(latest_ready_minute=60)])
    engine.advance(state, 2)
    assert state.orders[0].status == "expired" and state.orders[0].promise is None
    assert not engine.proposal(state, "current")[0]["actions"]


def test_capacity_disruption_preserves_wip_promises_and_invalidates_plan():
    session = service.create(CreateSession(demo_burst=True))
    accepted = apply_best(session)["session"]
    progressed = service.execute(session["id"], Advance(event_id="start", revision=accepted["revision"], minute=1))["session"]
    before = service.load(session["id"])
    stale_plan = service.plans(session["id"])["plans"][0]
    changed = service.execute(session["id"], CapacityChange(event_id="incident", revision=before.revision,
                                                           station="fryer", speed=.5, unavailable_minutes=5))["session"]
    assert changed["at_risk"] > progressed["at_risk"]
    for old, new in zip(before.orders, service.load(session["id"]).orders):
        assert old.promise == new.promise
        assert [(t.start, t.end, t.progress) for t in old.tasks] == [(t.start, t.end, t.progress) for t in new.tasks]
    with pytest.raises(service.Conflict):
        service.execute(session["id"], ApplyPlan(event_id="stale", revision=changed["revision"], strategy="current", plan_id=stale_plan["plan_id"]))
    frozen = [r for r in changed["plan"] if r["frozen"]]
    for strategy in engine.STRATEGIES:
        plan, _ = engine.proposal(service.load(session["id"]), strategy)
        assert [r for r in plan["plan"] if r["frozen"]] == frozen


def test_overloaded_confirmed_work_is_visible_beyond_quote_horizon():
    state = Session()
    state.speeds["fryer"] = .25
    for i in range(3):
        engine.receive(state, [incoming(str(i), commitment="confirmed", items=[{"item": "karaage", "quantity": 10}, {"item": "gyoza", "quantity": 10}])])
    view = engine.observe(state)
    assert view["counts"]["accepted"] == 3 and view["at_risk"] == 3
    assert max(r["end"] for r in view["plan"]) > 480
    assert all(o["promise"] == 15 for o in view["orders"])


def test_guard_blocks_reprioritization_that_harms_prior_commitment():
    state = Session()
    engine.receive(state, [incoming("FIRST", commitment="confirmed", requested_ready_minute=6),
                           incoming("SECOND", commitment="confirmed", requested_ready_minute=7,
                                    items=[{"item": "gyoza", "quantity": 1}])])
    plan, _ = engine.proposal(state, "slack")
    # First has 6 minutes of work and is protected; shortening flow by moving
    # the second first is forbidden if it increases the first's lateness.
    assert plan["allowed"]  # Slack keeps FIRST here.
    state.priority.reverse()
    arrival, _ = engine.proposal(state, "arrival")
    assert not arrival["allowed"] and "pickup:SECOND" in arrival["worsened_orders"]


def test_can_safely_change_unstarted_priority_and_show_ready_time_difference():
    state = Session()
    engine.receive(state, [incoming("A", commitment="confirmed", requested_ready_minute=20),
                           incoming("B", commitment="confirmed", requested_ready_minute=10,
                                    items=[{"item": "gyoza", "quantity": 1}])])
    current, _ = engine.proposal(state, "current")
    plan, selected = engine.proposal(state, "promise")
    assert plan["allowed"] and plan["remaining_flow_minutes"] < current["remaining_flow_minutes"]
    assert plan["next_work"][0]["order_id"] == "pickup:B"
    assert next(o for o in plan["commitment_forecast"] if o["order_key"] == "pickup:B") == {
        "order_key": "pickup:B", "promise": 10, "before_ready": 9, "after_ready": 4}
    engine.advance(selected, 1)
    assert selected.orders[0].tasks[0].start is None and selected.orders[1].tasks[0].start == 0


def test_event_idempotency_payload_conflicts_and_atomic_bad_batch():
    session = service.create(CreateSession())
    command = Intake(event_id="receive", revision=0, orders=[incoming()])
    first = service.execute(session["id"], command)
    duplicate = service.execute(session["id"], command)
    assert duplicate["duplicate"] and duplicate["receipt"] == first["receipt"]
    assert len(duplicate["session"]["orders"]) == 1
    with pytest.raises(service.Conflict, match="different command"):
        service.execute(session["id"], Intake(event_id="receive", revision=1, orders=[incoming("B")]))
    before = service.load(session["id"]).model_dump()
    with pytest.raises(ValueError, match="Future"):
        service.execute(session["id"], Intake(event_id="bad-batch", revision=1,
                      orders=[incoming("B"), incoming("FUTURE", received_minute=1)]))
    assert service.load(session["id"]).model_dump() == before
    with pytest.raises(ValueError, match="different contents"):
        service.execute(session["id"], Intake(event_id="edit-existing", revision=1,
                      orders=[incoming(requested_ready_minute=20)]))


def test_two_concurrent_plans_cannot_double_book():
    session = service.create(CreateSession(demo_burst=True))
    plan = service.plans(session["id"])["plans"][0]
    def attempt(i):
        try:
            service.execute(session["id"], ApplyPlan(event_id=f"race-{i}", revision=0, strategy="current", plan_id=plan["plan_id"]))
            return "applied"
        except service.Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [1, 2])) == ["applied", "conflict"]
    assert service.load(session["id"]).revision == 1


def test_restart_keeps_session_and_receipts_and_channel_ids_are_namespaced():
    session = service.create(CreateSession())
    service.execute(session["id"], Intake(event_id="two", revision=0, orders=[incoming(channel="pickup"), incoming(channel="doordash")]))
    done = apply_best(service.view(session["id"], service.load(session["id"])))
    store.recover()
    restored = service.load(session["id"])
    assert len(restored.orders) == 2 and restored.revision == 2
    assert restored.receipts[-1]["receipt_id"] == done["receipt"]["receipt_id"]


def test_plan_comparison_pure_deterministic_and_no_channel_preference():
    state = Session()
    engine.receive(state, [incoming("A", channel="pickup"), incoming("B", channel="doordash")])
    before = copy.deepcopy(state.model_dump())
    assert engine.compare_plans(state) == engine.compare_plans(state)
    assert state.model_dump() == before
    assert engine.proposal(state, "arrival")[0]["actions"][0]["order_key"] == "pickup:A"


def test_agent_uses_exact_tools_selects_then_commits_with_readback(monkeypatch):
    session = service.create(CreateSession(demo_burst=True))
    async def scripted(name, instruction, tools, progress, message):
        assert name == "order_manager"
        f = {t.__name__: t for t in tools}
        assert set(f) == {"inspect_demand", "compare_admission_plans", "select_checked_plan"}
        assert f["select_checked_plan"]("invented")["status"] == "rejected"
        assert "events" not in f["inspect_demand"]()
        compared = f["compare_admission_plans"]()
        plan = next(p for p in compared["plans"] if p["strategy"] == compared["recommended"])
        assert f["select_checked_plan"](plan["plan_id"])["status"] == "selected"
        assert service.load(session["id"]).revision == 0  # Selection is not execution.
        assert f["select_checked_plan"](plan["plan_id"])["status"] == "rejected"
        return {"model": "scripted-test", "tool_calls": [], "usage": [], "invoked": []}
    monkeypatch.setattr(order_manager, "_run", scripted)
    events = []
    result = asyncio.run(order_manager.run_order_management(session["id"], 0, events.append))
    assert result["local_receipt_verified"] and not result["external_verified"]
    assert result["receipt"]["decision_mode"] == "model_selected"
    assert service.load(session["id"]).revision == 1 and events[-1]["kind"] == "receipt"


def test_real_adk_runner_invokes_single_specialist_and_its_tools(monkeypatch):
    from google.adk.models import BaseLlm, LlmResponse
    from google.genai import types
    from gondola.agents import adk_graph

    class WorkflowLlm(BaseLlm):
        model: str = "offline-adk-order-manager-test"

        async def generate_content_async(self, llm_request, stream=False):
            responses = [part.function_response for content in llm_request.contents
                         for part in (content.parts or []) if part.function_response]
            last = responses[-1] if responses else None
            if last is None:
                name, args = "inspect_demand", {}
            elif last.name == "inspect_demand":
                name, args = "compare_admission_plans", {}
            elif last.name == "compare_admission_plans":
                data = last.response.get("result", last.response)
                plan = next(p for p in data["plans"] if p["strategy"] == data["recommended"])
                name, args = "select_checked_plan", {"plan_id": plan["plan_id"]}
            else:
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Checked plan selected for local validation.")]))
                return
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]))

    monkeypatch.setattr(adk_graph, "configured_model", lambda: WorkflowLlm())
    session = service.create(CreateSession(demo_burst=True))
    result = asyncio.run(order_manager.run_order_management(session["id"], 0, lambda e: None))
    assert result["local_receipt_verified"]
    assert result["invoked"] == ["order_manager"]
    assert [t["tool"] for t in result["tool_calls"]] == ["inspect_demand", "compare_admission_plans", "select_checked_plan"]


@pytest.mark.parametrize("failure", ["narration", "timeout_after_selection", "concurrent_change"])
def test_model_failures_and_stale_choices_never_admit_orders(monkeypatch, failure):
    session = service.create(CreateSession(demo_burst=True))
    async def scripted(name, instruction, tools, progress, message):
        if failure != "narration":
            f = {t.__name__: t for t in tools}
            f["inspect_demand"](); compared = f["compare_admission_plans"]()
            f["select_checked_plan"](compared["plans"][0]["plan_id"])
            if failure == "timeout_after_selection":
                raise TimeoutError("Simulated provider timeout after selection")
            service.execute(session["id"], CapacityChange(event_id="external-observation", revision=0, station="fryer", speed=.5))
        return {"model": "scripted-test", "tool_calls": [], "usage": [], "invoked": []}
    monkeypatch.setattr(order_manager, "_run", scripted)
    with pytest.raises((ValueError, TimeoutError)):
        asyncio.run(order_manager.run_order_management(session["id"], 0, lambda e: None))
    restored = service.load(session["id"])
    assert sum(o.status == "pending" for o in restored.orders) == 24
    assert not any(r["action"] == "admission_plan" for r in restored.receipts)


def test_api_validation_origins_conflicts_and_durable_job(monkeypatch):
    from gondola.api.orders import router
    from gondola.api.rush import router as jobs
    app = FastAPI(); app.include_router(router); app.include_router(jobs)
    async def scripted(*args):
        return {"model": "scripted-api", "local_receipt_verified": False}
    monkeypatch.setattr("gondola.api.orders.run_order_management", scripted)
    with TestClient(app, base_url="http://127.0.0.1:8768") as client:
        assert client.post("/api/demand/sessions", json={}, headers={"Origin": "https://outside.example"}).status_code == 403
        assert client.post("/api/demand/sessions", json={"policy": {"cooks": 0}}).status_code == 422
        s = client.post("/api/demand/sessions", json={"demo_burst": True}).json()
        ident = s["id"]; base = f"/api/demand/sessions/{ident}"
        assert client.get(base).json()["source_mode"] == "local_simulation"
        assert client.get("/api/demand/sessions/missing").status_code == 404
        p = client.get(base + "/plans").json()["plans"][0]
        payload = {"event_id": "apply", "revision": 0, "strategy": p["strategy"], "plan_id": p["plan_id"]}
        assert client.post(base + "/apply", json=payload).status_code == 200
        assert client.post(base + "/apply", json=payload).json()["duplicate"]
        assert client.post(base + "/agent", json={"revision": 0}).status_code == 409
        assert client.post(base + "/orders", json={"revision": 1, "event_id": "unknown", "orders": [{**incoming().model_dump(), "items": [{"item": "unknown", "quantity": 1}]}]}).status_code == 422
        job = client.post(base + "/agent", json={"revision": 1}).json()["id"]
        for _ in range(20):
            result = client.get(f"/api/rush/jobs/{job}").json()
            if result["status"] != "running":
                break
        assert result["kind"] == "order_manager" and result["status"] == "done"
        assert any(row["id"] == ident for row in client.get("/api/demand/sessions").json())


@pytest.mark.parametrize("patch", [{"items": [{"item": "don", "quantity": 0}]}, {"items": [{"item": "don", "quantity": True}]},
                                     {"requested_ready_minute": 0}, {"latest_ready_minute": 10},
                                     {"items": [{"item": "don", "quantity": 1}, {"item": "don", "quantity": 2}]}])
def test_invalid_capacity_inputs_are_rejected(patch):
    with pytest.raises(ValidationError):
        incoming(**patch)
