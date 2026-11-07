"""Present: queue scoring, capacity/admission ladder, the deterministic world and replay, ledger idempotency,
Gondola vs FIFO on the demo night, the Rush agent (offline and with a fake ADK model) and the API contract.
Offline: no API keys, no network. All restaurant/courier/kitchen data is synthetic (gondola/present/world.py)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gondola.present import admission as adm  # noqa: E402
from gondola.present import capacity as cap  # noqa: E402
from gondola.present import queue as q  # noqa: E402
from gondola.present import service, world  # noqa: E402
from gondola.present.queue import QOrder, make_task  # noqa: E402
from gondola.present.settings import PresentSettings  # noqa: E402

DEMO = "2026-11-05"
SPEEDS = {s: 1.0 for s in world.STATIONS}
DRY = {"rain": False, "snow": False, "temp_c": 12.0}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for k in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "GONDOLA_AGENTS", "GONDOLA_WEATHER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GONDOLA_LEDGER_DB", str(tmp_path / "ledger.sqlite"))
    monkeypatch.setenv("GONDOLA_PRESENT_DB", str(tmp_path / "present.sqlite"))
    monkeypatch.setenv("GONDOLA_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("GONDOLA_PRESENT_DIR", str(tmp_path / "present"))
    service.reset_cache()
    yield
    service.reset_cache()


def order(oid, created, promise, items, channel="doordash", ful="delivery", **kw):
    o = QOrder(oid, channel, ful, float(created), float(promise), items=list(items), **kw)
    for i, it in enumerate(items):
        m = world.MENU[it]
        o.tasks.append(make_task(f"{oid}:{i}", it, m["station"], m["minutes"]))
    o.pack = make_task(f"{oid}:pack", None, "packing", 1.0)
    return o


def rank_ids(orders, now, settings=None, weather=DRY):
    return [r["order_id"] for r in q.rank(orders, now, SPEEDS, weather, settings or PresentSettings())]


# ------------------------------------------------------------------ queue scoring
def test_fifo_counterexample_from_order_scheduling_doc():
    """docs/ideas/ORDER_SCHEDULING.md: one cook at 12:01. A (12:00, 5 min, due 12:20), B (12:01, 4 min, due 12:06).
    FIFO cooks A first and B's courier waits; the slack queue cooks B first, then A just in time."""
    t = 12 * 60
    def mk():
        a = QOrder("A", "doordash", "delivery", t, t + 20)
        a.tasks = [make_task("A:0", "Chashu Don", "assembly", 5.0, hold=0.0, labour=1.0)]
        b = QOrder("B", "ubereats", "delivery", t + 1, t + 6)
        b.tasks = [make_task("B:0", "Chashu Don", "assembly", 4.0, hold=0.0, labour=1.0)]
        return [a, b]
    slots = {"noodles": 1, "fryer": 1, "assembly": 1, "packing": 1}
    orders = mk()
    s = PresentSettings()
    s.weights.hold = 0
    prio = rank_ids(orders, t + 1, s)
    assert prio == ["B", "A"]
    _, finish = cap.schedule(orders, prio, t + 1, SPEEDS, slots, 1, jit=True, buffer=0)
    assert finish["B"] <= t + 6 and finish["A"] <= t + 20
    rows, _ = cap.schedule(orders, prio, t + 1, SPEEDS, slots, 1, jit=True, buffer=0)
    start_a = next(r["start"] for r in rows if r["order_id"] == "A")
    assert start_a >= t + 10            # A waits instead of sitting cooked for 14 minutes
    _, fifo = cap.schedule(mk(), q.fifo_rank(mk()), t + 1, SPEEDS, slots, 1, jit=False)
    assert fifo["A"] == t + 6 and fifo["B"] == t + 10 > t + 6   # FIFO: B late, A holds 14 min


def test_courier_arriving_now_jumps_ahead():
    t = 18 * 60
    far = order("far", t - 5, t + 15, ["Shoyu"], courier_eta=t + 18, courier_distance_km=4.0)
    near = order("near", t - 4, t + 15, ["Shoyu"], courier_eta=t + 1, courier_distance_km=0.3)
    ranked = q.rank([far, near], t, SPEEDS, DRY, PresentSettings())
    assert [r["order_id"] for r in ranked] == ["near", "far"]
    assert ranked[0]["factors"]["courier"] < 0 < ranked[1]["factors"]["courier"]
    assert "courier" in ranked[0]["reason"]


def test_fried_item_starts_later_than_rice_bowl_at_same_due():
    t = 17 * 60
    fried = order("fried", t, t + 25, ["Karaage"])
    rice = order("rice", t, t + 25, ["Chashu Don"])
    s = PresentSettings()
    ranked = q.rank([fried, rice], t, SPEEDS, DRY, s)
    assert ranked[0]["order_id"] == "rice" and ranked[1]["factors"]["hold"] > 0
    holds = {r["order_id"]: r["hold_tolerance"] for r in ranked}
    rows, finish = cap.schedule([fried, rice], [r["order_id"] for r in ranked], t, SPEEDS, s.kitchen.slots, 6,
                                jit=True, hold=holds, buffer=1)
    start = {r["order_id"]: r["start"] for r in rows if r["station"] != "packing"}
    assert start["fried"] > start["rice"]
    assert finish["fried"] <= t + 25 and finish["rice"] <= t + 25


def test_fairness_cap_moves_an_old_order_up():
    t = 19 * 60
    s = PresentSettings()
    old = order("old", t - 40, t + 30, ["Edamame"], channel="grubhub")       # a slow channel's order with slack
    new = order("new", t - 2, t + 8, ["Shoyu"])
    ranked = q.rank([new, old], t, SPEEDS, DRY, s)
    assert ranked[0]["order_id"] == "old"
    assert ranked[0]["factors"]["fairness"] < 0 and "fairness" in ranked[0]["reason"]


def test_channel_never_buys_priority():
    t = 18 * 60
    scores = set()
    for ch in ("doordash", "ubereats", "grubhub"):
        o = order(f"x-{ch}", t - 3, t + 15, ["Tonkotsu", "Gyoza"], channel=ch, courier_eta=t + 16,
                  customer_distance_km=4.0)
        s = q.score(o, t, SPEEDS, DRY, PresentSettings())
        scores.add((s["priority"], s["slack_min"], json.dumps(s["factors"], sort_keys=True)))
    assert len(scores) == 1
    # ties fall back to creation time and id, never the channel name
    a = order("b-ubereats", t - 3, t + 15, ["Shoyu"], channel="ubereats")
    b = order("a-grubhub", t - 2, t + 15, ["Shoyu"], channel="grubhub")
    assert rank_ids([b, a], t) == ["b-ubereats", "a-grubhub"]


def test_in_store_bump_but_never_past_an_at_risk_order():
    t = 18 * 60
    guest = order("guest", t - 2, t + 12, ["Shoyu"], channel="dine_in", ful="dine_in", customer_present=True)
    deliv = order("deliv", t - 2, t + 12, ["Shoyu"])
    ranked = q.rank([deliv, guest], t, SPEEDS, DRY, PresentSettings())
    assert ranked[0]["order_id"] == "guest" and ranked[0]["factors"]["in_store"] < 0
    # an order at its latest start (slack 0) still goes before a seated guest with slack
    risky = order("risky", t - 10, t + 6, ["Shoyu"])
    assert rank_ids([guest, risky], t)[0] == "risky"


def test_in_progress_work_is_frozen():
    t = 18 * 60
    a = order("a", t - 5, t + 30, ["Shoyu"])
    a.tasks[0].started, a.tasks[0].start = True, t - 1
    b = order("b", t - 1, t + 5, ["Shoyu"])
    rows, _ = cap.schedule([a, b], ["b", "a"], t, SPEEDS, {"noodles": 1, "fryer": 1, "assembly": 1, "packing": 1}, 3)
    ra = next(r for r in rows if r["task_id"] == "a:0")
    assert ra["frozen"] and ra["start"] == t - 1
    rb = next(r for r in rows if r["task_id"] == "b:0")
    assert rb["start"] >= ra["end"]          # one noodle slot: the urgent order waits, the running one isn't moved


# ------------------------------------------------------------------ ladder
def test_ladder_hysteresis_and_release_margin():
    lad = PresentSettings().ladder
    st = adm.LadderState(0, 0)
    assert st.update(1, -5, lad) is None          # one minute below 0: not yet
    assert st.update(2, 5, lad) is None           # back up: pending cleared
    assert st.update(3, -5, lad) is None
    assert st.update(4, -6, lad) is None
    assert st.update(5, -6, lad) == (0, -1)       # persisted 2 minutes -> quote
    for m in range(6, 12):
        st.update(m, 1.0, lad)                    # just above 0 but inside the release margin: stay
    assert st.level == -1
    st.update(12, 4, lad); st.update(13, 4, lad)
    assert st.update(14, 4, lad) == (-1, 0)
    # flapping around a threshold never moves
    st2 = adm.LadderState(0, 0)
    for m in range(1, 30):
        assert st2.update(m, -1 if m % 2 else 1, lad) is None
    # a sharp drop goes straight to the deeper level after the hysteresis
    st3 = adm.LadderState(0, 0)
    st3.update(1, -40, lad); st3.update(2, -40, lad)
    assert st3.update(3, -40, lad) == (0, -3)


def test_never_dine_in_or_pickup():
    ch = adm.channel_template()
    for app in world.DELIVERY_APPS:
        ch[app].update(busy=True, paused_items=["Tonkotsu"], quoted_extra_min=15)
    for own in ("dine_in", "pickup"):
        assert adm.decide(ch, own, ["Tonkotsu"], 1000)[0] == "accepted"
    assert adm.decide(ch, "grubhub", ["Shoyu"], 1000)[0] == "declined"
    e = service.Engine(DEMO, agent=False)
    for own in ("dine_in", "pickup"):
        for kind in ("busy", "quote", "pause_item"):
            r = e.apply_action(e.t, {"action": kind, "channel": own, "item": "Shoyu", "value": 10}, "manager")
            assert r["status"] == "rejected"
    assert adm.cheapest_first({"doordash": 0.74, "ubereats": 0.72, "grubhub": 0.79})[0] == "ubereats"


def test_busy_night_ladder_actions_skip_own_channels_and_have_reasons():
    e = service.run_day(DEMO, write=False)
    assert e.actions, "the demo night should move the ladder"
    for a in e.actions:
        assert a["reason"] and a["by"] in ("controller", "rush-agent", "manager")
        assert a.get("channel") not in ("dine_in",)
        if a["action"] in ("quote", "pause_item", "busy"):
            assert a["channel"] in world.DELIVERY_APPS
    assert all(x["channel"] in world.DELIVERY_APPS for x in e.declined)


# ------------------------------------------------------------------ world, replay, ledger
def test_world_is_deterministic_and_synthetic():
    w1 = world.build(DEMO)
    world.build.cache_clear()
    w2 = world.build(DEMO)
    assert len(w1.orders) == len(w2.orders) > 400
    for a, b in zip(w1.orders, w2.orders):
        assert (a.order_id, a.channel, a.promise, a.courier, a.tasks, a.customer_distance_km) == \
               (b.order_id, b.channel, b.promise, b.courier, b.tasks, b.customer_distance_km)
    assert w1.incidents == w2.incidents and w1.busy_night       # Penguins game + evening rain
    assert any("synthetic" in n for n in w1.notes)
    o = w1.orders[0]
    assert 15 <= o.promise - o.minute <= 25
    assert {x.fulfillment for x in w1.orders} == {"delivery", "pickup", "dine_in"}


def test_replay_is_deterministic():
    a = service.Engine(DEMO); a.run_until(19 * 60)
    b = service.Engine(DEMO); b.run_until(19 * 60)
    assert a.metrics() == b.metrics()
    assert [(r["key"], r["payload"]) for r in a.events] == [(r["key"], r["payload"]) for r in b.events]
    # incremental (cached) replay equals a straight run
    service.engine(DEMO, 18 * 60)
    c = service.engine(DEMO, 19 * 60)
    assert c.metrics() == a.metrics()


def test_replay_never_reveals_orders_after_now():
    e = service.Engine(DEMO)
    e.run_until(18 * 60 + 30)
    assert all(o.created < 18 * 60 + 30 for o in e.orders.values())
    assert all(r["ts"] <= f"{DEMO}T18:30:00" for r in e.events)


def test_ledger_events_idempotent_across_reruns():
    from gondola.ledger import ledger
    e = service.run_day(DEMO, write=True)
    led = ledger()
    n = len(led.query(DEMO))
    assert n == len(e.events) > 1000
    types = {ev.type for ev in led.query(DEMO)}
    assert {"order.received", "order.accepted", "task.started", "task.finished", "courier.eta_updated",
            "courier.arrived", "customer.arrived", "order.handed_off", "action.applied", "incident.started",
            "incident.ended"} <= types
    service.reset_cache()
    service.run_day(DEMO, write=True)
    assert len(led.query(DEMO)) == n
    fin = led.query(DEMO, ["task.finished"], limit=1)[0].payload
    assert fin["actual_min"] >= 1 and fin["planned_min"] > 0 and fin["synthetic"]
    h = led.query(DEMO, ["order.handed_off"], limit=1)[0].payload
    assert {"order_id", "channel", "ready", "handed", "wait_min", "hold_min", "late_min"} <= set(h)


def test_gondola_vs_fifo_on_the_demo_night(capsys):
    """Report honestly; no assertion that Gondola wins. Accounting must hold for every arm."""
    c = service.compare_at(DEMO, 10 ** 6)
    n = len(world.build(DEMO).orders)
    for arm in ("fifo", "queue_only", "gondola"):
        m = c[arm]
        assert m["accepted"] + m["declined"] == n
        assert m["orders"] == m["accepted"] and m["in_progress"] == 0
        assert m["promises_total"] == m["orders"]
    assert c["fifo"]["declined"] == c["queue_only"]["declined"] == 0
    with capsys.disabled():
        print("\nGondola vs FIFO, " + DEMO + ": " + json.dumps({k: {kk: c[k][kk] for kk in (
            "orders", "promises_met_pct", "avg_wait", "worst_wait", "avg_hold", "declined", "quoted")}
            for k in ("fifo", "queue_only", "gondola")}))


# ------------------------------------------------------------------ simulate, agent
def test_simulate_projection_shapes_and_limits():
    out = service.simulate(DEMO, {"action": "busy", "channel": "doordash"}, at="18:10")
    assert {"headroom_pct_before", "headroom_pct_after", "late_orders_before", "late_orders_after", "notes"} <= set(out)
    assert out["lost_orders"] > 0 and out["headroom_pct_after"] >= out["headroom_pct_before"]
    with pytest.raises(ValueError):          # never replay past the store clock
        service.simulate("2026-11-06", {"action": "none"}, at="12:00")


def test_agent_triggers_and_offline_policy_in_the_replay():
    e = service.run_day(DEMO, write=False)
    assert e.agent_runs
    assert any(t.startswith("incident") for r in e.agent_runs for t in r["triggers"])
    for r in e.agent_runs:
        a = r["action"] or {}
        assert a.get("action") in ("none", "quote", "pause_item", "busy", "resume", "pause_offer")


def test_agent_context_budget():
    from gondola.present.agent import context
    e = service.engine(DEMO, 18 * 60 + 10)
    ctx = context(e, e.t, ["test"])
    assert ctx["tokens"] <= 3000 and ctx["payload"]["queue_head"]


def test_agent_offline_run_records_receipt_on_closed_day():
    import asyncio
    from gondola.present import agent, receipts
    out = asyncio.run(agent.run(DEMO, at="18:05"))
    assert {"decision", "actions", "receipt"} <= set(out)
    assert out["receipt"]["agent_mode"] == "offline_policy"
    assert out["status"] in ("recorded", "no_action")
    assert receipts.get(out["receipt"]["id"])["kind"] == "rush_agent"
    assert receipts.overrides(DEMO) == []       # a closed day is never rewritten


def test_agent_offline_run_applies_override_when_open(monkeypatch):
    import asyncio
    from gondola.present import agent, receipts
    monkeypatch.setattr(service, "_clock", lambda d, now=None: (18 * 60 + 5, "open"))
    before = service.state(DEMO)
    assert before["phase"] == "open"
    out = asyncio.run(agent.run(DEMO))
    if out["actions"]:
        assert out["status"] == "applied" and receipts.overrides(DEMO)
        after = service.engine(DEMO, 18 * 60 + 7)
        assert any(a["by"] == "rush-agent" and a["minute"] == 18 * 60 + 5 for a in after.actions)


def test_agent_with_fake_adk_model(monkeypatch):
    """The live path really goes through ADK tool calls (fake model, no network)."""
    import asyncio
    from test_agents import ScriptedLlm
    from gondola.agents import adk_graph
    from gondola.present import agent
    fake = ScriptedLlm(script={"rush_agent": {
        "calls": [("get_state", {}), ("simulate", {"action": "quote", "channel": "delivery", "value": 10}),
                  ("apply", {"action": "busy", "channel": "dine_in"}),
                  ("apply", {"action": "quote", "channel": "grubhub", "value": 10, "reason": "test"})],
        "text": "Quoted Grubhub longer."}})
    monkeypatch.setattr(adk_graph, "configured_model", lambda require_mode=True: fake)
    out = asyncio.run(agent.run(DEMO, at="18:05"))
    tools = [t["tool"] for t in out["receipt"]["trace"]]
    assert tools.count("apply") == 2 and "get_state" in tools and "simulate" in tools
    applies = [t for t in out["receipt"]["trace"] if t["tool"] == "apply"]
    assert applies[0]["result"]["status"] == "rejected"           # never dine-in
    assert applies[1]["result"]["status"] == "recorded"           # closed day: recorded, not applied
    assert out["receipt"]["agent_mode"] == "live_model"
    assert out["actions"] == [{"action": "quote", "channel": "grubhub", "item": None, "value": 10, "reason": "test"}]


# ------------------------------------------------------------------ API contract
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from gondola.api.app import app
    return TestClient(app)


def test_api_state_contract(client):
    r = client.get("/api/present/state", params={"date": DEMO, "at": "18:20"})
    assert r.status_code == 200
    s = r.json()
    assert {"date", "now", "phase", "headroom_pct", "ladder", "queue", "stations", "channels", "actions", "weather"} <= set(s)
    assert {"level", "name", "since", "next_threshold"} <= set(s["ladder"])
    assert s["queue"]
    for item in s["queue"]:
        assert {"rank", "order_id", "channel", "items", "fulfillment", "promise", "courier_eta", "courier_distance_km",
                "customer_distance_km", "due", "latest_start", "slack_min", "station", "status", "factors",
                "reason"} <= set(item)
        assert set(item["factors"]) == {"courier", "distance", "hold", "weather", "batch", "fairness", "in_store"}
        assert item["status"] in ("queued", "cooking", "packing", "ready")
    assert [x["rank"] for x in s["queue"]] == list(range(1, len(s["queue"]) + 1))
    for st in s["stations"]:
        assert {"key", "name", "speed", "busy_until", "tasks"} <= set(st)
    for ch in ("doordash", "ubereats", "grubhub", "pickup", "dine_in"):
        assert {"state", "quoted_extra_min", "paused_items"} <= set(s["channels"][ch])
    assert {"rain", "temp_c", "source"} <= set(s["weather"])
    assert client.get("/api/present/state", params={"date": DEMO}).json()["phase"] == "closed"
    assert client.get("/api/present/state", params={"date": "2026-11-05", "at": "25:99"}).status_code == 400
    assert client.get("/api/present/state", params={"date": "2026-11-06", "at": "12:00"}).status_code == 400


def test_api_compare_simulate_agent_settings(client):
    c = client.get("/api/present/compare", params={"date": DEMO}).json()
    assert {"fifo", "gondola", "orders"} <= set(c)
    for arm in ("fifo", "gondola"):
        assert {"promises_met", "avg_wait", "worst_wait", "hold"} <= set(c[arm])
    sim = client.post("/api/present/simulate", json={"date": DEMO, "at": "18:10",
                                                     "action": {"action": "quote", "channel": "doordash", "value": 10}})
    assert sim.status_code == 200
    assert {"headroom_pct_before", "headroom_pct_after", "late_orders_before", "late_orders_after", "notes"} <= set(sim.json())
    assert client.post("/api/present/simulate", json={"date": DEMO, "action": {"action": "raise_prices"}}).status_code == 400
    ag = client.post("/api/present/agent", json={"date": DEMO, "at": "18:05"})
    assert ag.status_code == 200 and {"decision", "actions", "receipt"} <= set(ag.json())
    assert client.get(f"/api/present/agent/receipts/{ag.json()['receipt']['id']}").status_code == 200
    s = client.get("/api/present/settings").json()
    assert {"promote_above", "quote_below", "pause_below", "busy_below", "hysteresis_min"} <= set(s["ladder"])
    assert "weights" in s and "max_wait_min" in s
    r = client.put("/api/present/settings", json={"ladder": {"hysteresis_min": 3}, "max_wait_min": 30})
    assert r.status_code == 200 and r.json()["ladder"]["hysteresis_min"] == 3 and r.json()["max_wait_min"] == 30
    assert client.get("/api/present/settings").json()["ladder"]["promote_above"] == 20.0
    assert client.put("/api/present/settings", json={"ladder": {"promote_above": -50}}).status_code == 400
    assert client.put("/api/present/settings", json={"weights": {"channel_bonus": 5}}).status_code == 400


def test_review_handoffs_surface_in_state():
    from gondola.ledger import ledger
    ledger().append("exception.raised", DEMO, f"{DEMO}T18:00:00", {"id": "x1", "kind": "late", "severity": "high",
                    "title": "Fryer orders late", "decision": "present", "note": "pause karaage on Grubhub"},
                    source="review", key="test:x1")
    ledger().append("exception.raised", DEMO, f"{DEMO}T18:01:00", {"id": "x2", "title": "note only", "decision": "note"},
                    source="review", key="test:x2")
    s = service.state(DEMO, at="18:20", write=False)
    assert [h["id"] for h in s["handoffs"]] == ["x1"] and s["handoffs"][0]["note"]
    assert service.state(DEMO, at="17:30", write=False)["handoffs"] == []


def test_api_stream_closed_day(client):
    with client.stream("GET", "/api/present/stream", params={"date": DEMO}) as resp:
        body = "".join(resp.iter_text())
    events = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event:")]
    assert events == ["state", "done"]


def test_api_stream_open_day(client, monkeypatch):
    monkeypatch.setattr(service, "_clock", lambda d, now=None: (18 * 60 + 15, "open"))
    with client.stream("GET", "/api/present/stream", params={"date": DEMO, "max_s": 0.3}) as resp:
        body = "".join(resp.iter_text())
    lines = [line for line in body.splitlines() if line.startswith("event:") or line.startswith("data:")]
    assert lines[0] == "event: state"
    st = json.loads(lines[1][6:])
    assert st["phase"] == "open" and st["now"] == "18:15" and st["queue"]
