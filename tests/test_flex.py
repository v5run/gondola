"""Resource, economic, consent and concurrency boundaries for flexible pickup."""
import asyncio
import copy
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gondola.flex import agent, calendar, service, store
from gondola.flex.models import CartRequest, SessionRequest


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "flex.sqlite3")


def setup(**kwargs):
    s = service.create(SessionRequest(**kwargs))
    return s["id"], CartRequest(cart_id="customer-one")


def assert_calendar(s):
    rows = calendar.allocations(s)
    # Independent interval counts, not a mirror call to can_place.
    for m in range(12, 200):
        active = [t for t in rows if t["start"] <= m < t["end"]]
        for station in ("fryer", "noodles", "assembly", "packing"):
            assert sum(t["station"] == station for t in active) <= 1
        assert sum(t["station"] != "packing" for t in active) <= s["config"]["cooks"]
    assert s["spent_cents"] == sum(b["option"]["discount_cents"] for b in s["bookings"])
    assert s["spent_cents"] <= s["config"]["budget_cents"]
    for b in s["bookings"]:
        cook, pack = b["option"]["tasks"]
        assert cook["end"] == pack["start"]
        assert pack["end"] == b["option"]["pickup_minute"]
        assert b["option"]["holding_minutes"] == 0


def test_later_pickup_moves_production_not_just_customer_arrival():
    ident, cart = setup()
    before = service.state(ident)
    q = service.quote(ident, cart)
    early, flex = q["options"][:2]
    assert (early["pickup_clock"], flex["pickup_clock"], flex["discount_cents"]) == ("17:53", "18:15", 200)
    assert flex["tasks"][0]["start"] > early["tasks"][0]["end"]
    assert flex["tasks"][1]["start"] > early["tasks"][1]["end"]
    assert flex["released_cook_minutes"] == 3
    unchanged = service.state(ident)
    assert not unchanged["bookings"] and unchanged["spent_cents"] == 0
    assert unchanged["observed"] == before["observed"]
    receipt = service.accept(ident, q["id"], flex["id"])
    after = service.state(ident)
    assert receipt["status"] == "reserved" and receipt["payment_mode"] == "no_charge"
    assert after["observed"] == before["observed"]
    assert calendar.available_stock(after, cart.item) == before["observed"]["stock"][cart.item] - 1
    assert receipt["comparison"]["allocations"] == calendar.allocations(before)
    assert_calendar(after)


@pytest.mark.parametrize("scenario", ["rush", "quiet", "overload"])
@pytest.mark.parametrize("cooks", [1, 2, 3, 4])
def test_every_published_choice_fits_resources_and_customer_limits(scenario, cooks):
    ident, cart = setup(scenario=scenario, cooks=cooks)
    cart = cart.model_copy(update={"latest_pickup_minute": 180})
    try: q = service.quote(ident, cart)
    except service.Conflict:
        assert calendar.regular_option(service.state(ident), cart) is None
        return
    for option in q["options"]:
        s = service.state(ident)
        assert calendar.can_place(s, option["tasks"])
        assert option["pickup_minute"] <= cart.latest_pickup_minute
        if option["kind"] == "flexible":
            assert option["discount_cents"] >= cart.minimum_saving_cents
            assert option["released_cook_minutes"] >= 2
            assert option["discount_cents"] <= option["released_cook_minutes"] * calendar.RELIEF_COST_LIMIT
    r = service.accept(ident, q["id"], q["options"][-1]["id"])
    assert r["consent"]
    assert_calendar(service.state(ident))


def test_quiet_budget_and_customer_minimum_produce_honest_regular_only():
    for kwargs, minimum, reason in [({"scenario": "quiet"}, 200, "kitchen has room"), ({"budget_cents": 0}, 200, "budget"), ({}, 400, "approved incentive limit")]:
        ident, cart = setup(**kwargs)
        q = service.quote(ident, cart.model_copy(update={"minimum_saving_cents": minimum}))
        assert len(q["options"]) == 1 and reason in q["no_deal_reason"]
        assert q["options"][0]["discount_cents"] == 0


def test_decline_and_unknown_option_create_no_obligation():
    ident, cart = setup()
    q = service.quote(ident, cart)
    with pytest.raises(ValueError, match="Unknown choice"):
        service.accept(ident, q["id"], "invented")
    service.decline(ident, q["id"])
    with pytest.raises(service.Conflict): service.accept(ident, q["id"], q["options"][1]["id"])
    assert not service.get(ident)["bookings"] and service.get(ident)["spent_cents"] == 0


def test_expiry_and_changed_assumptions(monkeypatch):
    ident, cart = setup()
    q = service.quote(ident, cart)
    with monkeypatch.context() as m:
        m.setattr(service, "time", SimpleNamespace(time=lambda: q["expires_at"] + 1))
        assert service.get_quote(ident, q["id"])["status"] == "expired"
        with pytest.raises(service.Conflict, match="expired"): service.accept(ident, q["id"], q["options"][1]["id"])
    with store.transaction() as con:
        s = store.read(con, ident); s["revision"] += 1; store.save(con, s)
    with pytest.raises(service.Conflict, match="assumptions changed"): service.accept(ident, q["id"], q["options"][1]["id"])
    assert not service.get(ident)["bookings"]


def test_duplicate_accept_is_idempotent_even_after_expiry(monkeypatch):
    ident, cart = setup()
    q = service.quote(ident, cart)
    selected = q["options"][1]
    first = service.accept(ident, q["id"], selected["id"])
    monkeypatch.setattr(service, "time", SimpleNamespace(time=lambda: q["expires_at"] + 1000))
    repeat = service.accept(ident, q["id"], selected["id"])
    assert repeat["id"] == first["id"] and repeat["replayed"]
    assert len(service.get(ident)["bookings"]) == 1
    with pytest.raises(service.Conflict): service.accept(ident, q["id"], q["options"][0]["id"])
    with pytest.raises(service.Conflict): service.decline(ident, q["id"])


def test_simultaneous_customers_cannot_overbook_or_double_spend():
    ident, cart = setup()
    a = service.quote(ident, cart)
    b = service.quote(ident, cart.model_copy(update={"cart_id": "customer-two"}))
    def accept(q):
        try: return service.accept(ident, q["id"], q["options"][1]["id"])
        except service.Conflict: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(accept, (a, b)))
    assert sum(r is not None for r in results) == 1
    s = service.state(ident)
    assert len(s["bookings"]) == 1 and s["spent_cents"] == 200
    assert_calendar(s)


def test_same_cart_cannot_be_accepted_through_different_quotes():
    ident, cart = setup()
    a, b = service.quote(ident, cart), service.quote(ident, cart)
    service.accept(ident, a["id"], a["options"][1]["id"])
    with pytest.raises(service.Conflict, match="already has"): service.accept(ident, b["id"], b["options"][2]["id"])


def test_stock_budget_and_earliest_counterfactual_are_rechecked():
    ident, cart = setup(budget_cents=300)
    a = service.quote(ident, cart)
    b = service.quote(ident, cart.model_copy(update={"cart_id": "other-cart"}))
    service.accept(ident, a["id"], a["options"][1]["id"])
    with pytest.raises(service.Conflict, match="budget"): service.accept(ident, b["id"], b["options"][2]["id"])
    ident, cart = setup()
    q = service.quote(ident, cart)
    service.compete(ident, q["id"], q["options"][0]["id"])
    with pytest.raises(service.Conflict, match="original earliest"): service.accept(ident, q["id"], q["options"][1]["id"])
    assert service.get(ident)["spent_cents"] == 0
    ident, cart = setup()
    with store.transaction() as con:
        s = store.read(con, ident); s["observed"]["stock"]["don"] = 1; store.save(con, s)
    a = service.quote(ident, cart); b = service.quote(ident, cart.model_copy(update={"cart_id": "last-portion"}))
    service.accept(ident, a["id"], a["options"][1]["id"])
    with pytest.raises(service.Conflict, match="sold out"): service.accept(ident, b["id"], b["options"][0]["id"])


def test_competing_booking_invalidates_slot_and_persists():
    ident, cart = setup()
    q = service.quote(ident, cart)
    service.compete(ident, q["id"], q["options"][1]["id"])
    with pytest.raises(service.Conflict, match="slot just filled"): service.accept(ident, q["id"], q["options"][1]["id"])
    assert service.state(ident)["bookings"][0]["source"] == "simulated_other_customer"
    assert service.state(ident)["spent_cents"] == 0
    assert_calendar(service.state(ident))


def test_agent_tools_publish_only_proposals_and_reject_invalid_bargains(monkeypatch):
    ident, cart = setup()
    async def scripted(name, instruction, tools, progress, message):
        f = {t.__name__: t for t in tools}
        f["inspect_checkout"]()
        allowed = f["compare_pickup_choices"]()["allowed"]
        assert f["publish_pickup_choices"](999, 900)["status"] == "rejected"
        best = allowed[0]
        assert f["publish_pickup_choices"](best["pickup_minute"], best["discount_cents"])["requires_customer_acceptance"]
        return {"model": "test-fake", "tool_calls": [], "usage": []}
    monkeypatch.setattr(agent, "_run", scripted)
    r = asyncio.run(agent.find_choices(ident, cart, lambda e: None))
    assert r["quote"]["source"] == "gemini" and r["action"] == "proposals_only_customer_consent_required"
    assert not service.get(ident)["bookings"] and service.get(ident)["spent_cents"] == 0


def test_narration_cannot_substitute_for_published_choices(monkeypatch):
    ident, cart = setup()
    async def fake(*args): return {"model": "test-fake"}
    monkeypatch.setattr(agent, "_run", fake)
    with pytest.raises(ValueError, match="did not publish"): asyncio.run(agent.find_choices(ident, cart, lambda e: None))


def test_api_consent_validation_origin_and_receipt_contract():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gondola.api.flex import router
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as c:
        assert c.post('/api/flex/sessions', json={"budget_cents": -1}).status_code == 422
        assert c.post('/api/flex/sessions', json={}, headers={"Origin": "https://outside.example"}).status_code == 403
        s = c.post('/api/flex/sessions', json={}).json()
        base = '/api/flex/sessions/' + s['id']
        q = c.post(base+'/quotes',json=CartRequest(cart_id='api-customer').model_dump()).json()
        assert c.get(base).json()['spent_cents'] == 0
        body={'option_id':q['options'][1]['id']}
        assert c.post(base+'/quotes/'+q['id']+'/accept',json={**body,'discount_cents':999}).status_code == 422
        response=c.post(base+'/quotes/'+q['id']+'/accept',json=body)
        assert response.status_code == 200 and response.json()['status'] == 'reserved'
        assert c.post(base+'/quotes/'+q['id']+'/accept',json=body).json()['replayed']
        assert c.get('/api/flex/sessions/unknown').status_code == 404
