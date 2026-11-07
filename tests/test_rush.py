"""Rush Control invariants and honest failure modes. No real model/network calls."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gondola.rush import agents, store
from gondola.rush.engine import Kitchen, MENU, MODES, _world, simulate, snapshot
from gondola.rush.evaluation import HELD_OUT, TRAINING, evaluate, qualify
from gondola.rush.models import AgentRequest, OfferPolicy, RushRequest


def assert_resources(run, cooks):
    tasks = run["actual_tasks"]
    for m in range(len(run["frames"])):
        active = [t for t in tasks if t["start"] is not None and t["start"] <= m < (t["end"] or 350)]
        assert sum(t["station"] != "packing" for t in active) <= cooks
        for station in ("fryer", "noodles", "assembly", "packing"):
            assert sum(t["station"] == station for t in active) <= 1
    by_id = {t["task_id"]: t for t in tasks}
    for t in tasks:
        if t["station"] == "packing" and t["start"] is not None:
            assert t["start"] >= by_id[t["order_id"] + ":cook"]["end"]


@pytest.mark.parametrize("cooks", [1, 2, 3, 4])
@pytest.mark.parametrize("mode", list(MODES))
def test_actual_resources_dependencies_and_accounting(cooks, mode):
    req = RushRequest(scenario="overload", cooks=cooks, incident="station_outage")
    run = simulate(req, mode)
    assert_resources(run, cooks)
    m = run["metrics"]
    assert m["accepted"] == m["completed"] + m["unresolved"]
    assert m["existing_orders"] == 42
    assert m["promo_spend_cents"] <= req.budget_cents
    assert m["late"] + m["on_time"] == m["completed"]
    assert m["unresolved"] == 0


def test_deterministic_draws_and_observation_boundary():
    req = RushRequest(seed=45)
    other = req.model_copy(update={"policy": OfferPolicy(discount_cents=0)})
    assert _world(req) == _world(other)
    assert simulate(req) == simulate(req)
    a, b = Kitchen(req), Kitchen(other)
    data = _world(req)["orders"][0]
    b.estimates[data["item"]] = 88
    a._accept(data); b._accept(data)
    assert a._truth_work == b._truth_work  # estimator cannot change physical truth
    public = json.dumps(snapshot(req, 11).observe())
    for forbidden in ("utility", "sensitivity", "_truth", "_world", "fryer_slowdown"):
        assert forbidden not in public
    before, after = snapshot(req, 11), snapshot(req, 12)
    assert before.speed["fryer"] == 1
    assert after.speed["fryer"] == .5


def test_eta_update_never_rewrites_promises():
    a = snapshot(RushRequest(incident="none"), 12)
    b = snapshot(RushRequest(incident="courier_delay"), 12)
    for original, changed in zip(a.orders, b.orders):
        assert original.id == changed.id and original.promise == changed.promise
        if original.channel == "doordash" and original.ready is None:
            assert changed.eta == original.eta + 8


def test_browser_frame_and_agent_share_the_same_decision_boundary():
    req = RushRequest(forecast_pressure=1.15)
    run = simulate(req)
    for minute in (10, 12, 18, 30):
        k = snapshot(req, minute)
        frame = run["frames"][minute]
        obs = k.observe()
        assert frame["stock"] == obs["stock"]
        assert frame["spent_cents"] == req.budget_cents - obs["budget_remaining_cents"]
        assert [(o["id"], o["ready"], o["promise"], o["eta"]) for o in frame["orders"]] == [(o["id"], o["ready"], o["promise"], o["eta"]) for o in obs["orders"]]
        assert frame["offer_checks"] == k.offers()


def test_offer_guards_do_not_mutate_on_rejection_and_preserve_reservations():
    k = snapshot(RushRequest(), 12)
    assert not k.evaluate_offer("karaage")["allowed"]
    before = k.observe()
    for item, discount in (("unknown", 100), ("don", 201), ("don", -1), ("don", True)):
        assert k.publish_offer(item, discount)["status"] == "rejected"
        assert k.observe() == before
    check = k.evaluate_offer("don")
    assert check["allowed"] and not check["affected_commitments"]
    receipt = k.publish_offer("don")
    assert receipt["status"] == "applied" and receipt["receipt_id"]
    assert receipt["source_mode"] == "simulation"
    k.stock["don"] = 1
    assert "stock" in k.evaluate_offer("don")["reason"]
    k.stock["don"] = 10; k.spent = k.req.budget_cents
    assert "budget" in k.evaluate_offer("don")["reason"]


def test_zero_budget_and_learning_only_after_completions():
    run = simulate(RushRequest(budget_cents=0))
    assert run["metrics"]["promo_spend_cents"] == 0
    cook_ends = {(t["order_id"], t["end"]) for t in run["actual_tasks"] if t["station"] != "packing"}
    assert run["learning"]
    for sample in run["learning"]:
        assert any(end == sample["minute"] for _, end in cook_ends)
    k = Kitchen(RushRequest())
    original = dict(k.estimates)
    k.step()
    assert k.estimates == original and not k.errors


@pytest.mark.parametrize("values", [{"discount_cents": 201}, {"reserve_minutes": -1}, {"load_weight": float("nan")}, {"secret_evaluator": True}])
def test_policy_bounds(values):
    with pytest.raises(ValidationError):
        OfferPolicy(**values)


def test_bad_candidate_retains_default_and_training_is_separate():
    assert not {r.seed for r in TRAINING} & {r.seed for r in HELD_OUT}
    result = qualify(OfferPolicy(name="Bad policy", minimum_margin_cents=1500))
    assert not result["qualified"]
    assert result["selected_policy"] == OfferPolicy().model_dump()
    assert len(result["search_training"]) == 6
    assert len(result["candidate"]["cases"]) == 6
    assert evaluate(OfferPolicy(), TRAINING)["checks_pass"]


def test_agent_must_apply_tool_not_only_narrate(monkeypatch):
    async def narration(*args):
        return {"model": "fake-test-model", "tool_calls": [], "usage": [], "invoked": []}
    monkeypatch.setattr(agents, "_run", narration)
    with pytest.raises(ValueError, match="did not complete"):
        asyncio.run(agents.controller(AgentRequest(), lambda e: None))


def test_actual_agent_tools_block_bad_offer_then_apply_and_confirm(monkeypatch):
    async def scripted(name, instruction, tools, progress, message):
        f = {t.__name__: t for t in tools}
        assert "utility" not in json.dumps(f["inspect_kitchen"]())
        offers = f["compare_approved_offers"]()["offers"]
        assert any(o["allowed"] for o in offers)
        assert f["publish_simulated_offer"]("karaage", 100)["status"] == "rejected"
        assert f["publish_simulated_offer"]("don", 100)["status"] == "applied"
        assert f["publish_simulated_offer"]("don", 100)["status"] == "rejected"
        return {"model": "fake-test-model", "tool_calls": [], "usage": [], "invoked": []}
    monkeypatch.setattr(agents, "_run", scripted)
    events = []
    result = asyncio.run(agents.controller(AgentRequest(), events.append))
    assert result["receipt"]["source"] == "gemini"
    assert result["receipt"]["evidence"]["allowed"]
    assert len(events) == 5


def test_durable_receipts_and_restart_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "test.sqlite3")
    done = store.create("controller", {"events": []})
    store.update(done, "done", {"result": {"receipt_id": "verified"}})
    running = store.create("policy_lab", {})
    store.recover()
    assert store.get(done)["result"]["receipt_id"] == "verified"
    assert store.get(running)["status"] == "interrupted"
    assert store.get("missing") is None
    assert len(store.recent()) == 2
    for _ in range(25):
        store.create("comparison", {})
    assert {r["id"] for r in store.recent()} == {done, running}


def test_policy_agent_can_only_submit_distinct_tested_bounded_parameters(monkeypatch):
    async def scripted(name, instruction, tools, progress, message):
        f = {t.__name__: t for t in tools}
        assert set(f) == {"training_brief", "test_policy", "submit_policy"}
        brief = f["training_brief"]()
        assert len(brief["cases"]) == 3
        assert not any(str(r.seed) in json.dumps(brief["cases"]) for r in HELD_OUT)
        assert f["submit_policy"]("invented")["status"] == "rejected"
        values = OfferPolicy(name="First").model_dump()
        assert f["test_policy"](**{**values, "discount_cents": 999})["status"] == "rejected"
        f["test_policy"](**values)
        assert f["test_policy"](**{**values, "name": "Same parameters"})["status"] == "rejected"
        assert f["test_policy"](**{**values, "discount_cents": 50})["status"] == "rejected"
        f["test_policy"](**{**values, "name": "Second", "discount_cents": 50})
        assert f["submit_policy"]("Second")["status"] == "submitted"
        return {"model": "fake-test-model", "tool_calls": [], "usage": [], "invoked": []}
    monkeypatch.setattr(agents, "_run", scripted)
    result = asyncio.run(agents.policy_lab("Test objective", lambda e: None))
    assert len(result["trials"]) == 2
    assert result["proposed_policy"]["name"] == "Second"
    assert len(result["qualification"]["candidate"]["cases"]) == 6


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gondola.api.rush import router
    monkeypatch.setattr(store, "DB", tmp_path / "api.sqlite3")
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_api_contract_validation_origin_and_failure(client, monkeypatch):
    assert client.get("/api/rush/config").json()["data_mode"] == "synthetic"
    assert client.post("/api/rush/compare", json={"cooks": 0}).status_code == 422
    data = client.post("/api/rush/compare", json={}).json()
    assert set(data["runs"]) == set(MODES)
    assert client.get(f"/api/rush/jobs/{data['id']}").json()["status"] == "done"
    assert client.get("/api/rush/jobs/missing").status_code == 404
    assert client.post("/api/rush/agent", json={}, headers={"Origin": "https://outside.example"}).status_code == 403
    async def fail(req, progress):
        raise RuntimeError("Provider unavailable for test")
    monkeypatch.setattr(agents, "controller", fail)
    response = client.post("/api/rush/agent", json={}).json()
    for _ in range(30):
        result = client.get(f"/api/rush/jobs/{response['id']}").json()
        if result["status"] != "running": break
    assert result["status"] == "failed" and "result" not in result
    assert result["error"] == "Agent job failed; no successful result is available."
