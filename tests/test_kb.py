"""Knowledge base: validation recomputes numbers (accepts reproducible, rejects invented), n >= 3 gate, approval of
behavior-changing kinds, conflicts, decay/retire, compaction, and retrieval budgets."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gondola.kb import KB, compact_item, slot_of, tokens  # noqa: E402
from gondola.kb import measures as M  # noqa: E402

AS_OF = "2026-11-05"
PENS = {"kind": "event_effect", "scope": {"event": "Penguins home game"},
        "statement": "Penguins home games raise orders", "effect": {"metric": "orders", "change_pct": None}}


@pytest.fixture()
def kb(tmp_path):
    for k in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "GONDOLA_AGENTS"):
        os.environ.pop(k, None)
    return KB(tmp_path / "kb.sqlite")


def pens(change):
    return {**PENS, "effect": {"metric": "orders", "change_pct": change}}


def test_effect_matches_direct_computation():
    """measures.effect = same weekday with vs without, recomputed here by hand for one evidence day."""
    e = M.effect("orders", {"event": "Penguins home game"}, None, AS_OF)
    assert e["n"] >= 3 and e["change_pct"] is not None
    d = M.data()["days"]
    day = e["per_day"][-1]
    t = d[d.date == day["date"]].iloc[0]
    assert t.orders == day["value"]
    import pandas as pd
    base = d[(d.date < pd.Timestamp(day["date"])) & (d.date >= pd.Timestamp(day["date"]) - pd.Timedelta(weeks=8))
             & (d.weekday == t.weekday) & ~d.events.str.lower().str.contains("penguins") & d.holiday.isna() & (d.orders > 0)]
    assert day["baseline"] == pytest.approx(base.orders.mean(), abs=0.01)


def test_accepts_reproducible_and_stores_recomputed(kb):
    true = M.effect("orders", {"event": "Penguins home game"}, None, AS_OF)["change_pct"]
    r = kb.propose(pens(round(true + 1.5, 1)), AS_OF)
    assert r["ok"] and r["op"] == "add"
    it = r["item"]
    assert it["effect"]["change_pct"] == true  # the stored number is the recomputed one
    assert it["validation"]["claimed"] == round(true + 1.5, 1) and it["status"] == "active" and it["n"] >= 3
    assert it["confidence"] > 0.5 and it["evidence"] and it["id"].startswith("kb-")


def test_rejects_invented_numbers(kb):
    true = M.effect("orders", {"event": "Penguins home game"}, None, AS_OF)["change_pct"]
    r = kb.propose(pens(true + 40), AS_OF)
    assert not r["ok"] and r["op"] == "rejected" and "data gives" in r["reason"]
    r = kb.propose({**pens(true), "statement": "Penguins games raise orders by 61%"}, AS_OF)
    assert not r["ok"] and "61%" in r["reason"]
    r = kb.propose({**pens(true), "evidence": ["2026-10-09"]}, AS_OF)  # not a Penguins day
    assert not r["ok"] and "cited dates" in r["reason"]
    r = kb.propose({"kind": "item_behavior", "scope": {"item": "chashu", "weekday": "Thu"},
                    "statement": "Chashu almost never sells out on Thursdays", "effect": {"metric": "sellout_rate", "value": 0.01}}, AS_OF)
    assert not r["ok"]
    r = kb.propose({"kind": "event_effect", "scope": {"event": "Concert at the moon"}, "statement": "x",
                    "effect": {"metric": "orders", "change_pct": 5}}, AS_OF)
    assert not r["ok"] and "no matching days" in r["reason"]
    assert not kb.propose({"kind": "magic", "statement": "x"}, AS_OF)["ok"]
    assert kb.list() == []  # nothing rejected is stored as an item
    assert any(h["op"] == "rejected" for h in kb.history())


def test_n_gate_and_approval(kb):
    one = M.effect("orders", {"event": "Steelers home game", "weekday": "Thu"}, None, AS_OF)
    assert one["n"] < 3
    r = kb.propose({"kind": "event_effect", "scope": {"event": "Steelers home game", "weekday": "Thu"},
                    "statement": "Thursday night Steelers games raise orders", "effect": {"metric": "orders", "change_pct": one["change_pct"]}}, AS_OF)
    assert r["ok"] and r["item"]["status"] == "proposed" and r["item"]["estimate"] is True
    peak = M.value("peak_orders_per_hour", {"weekday": "Fri"}, None, AS_OF)
    r = kb.propose({"kind": "capacity", "scope": {"weekday": "Fri"}, "statement": "Friday peak hour",
                    "effect": {"metric": "peak_orders_per_hour", "value": peak["value"]}}, AS_OF)
    assert r["item"]["status"] == "needs_approval"
    assert kb.retrieve({"weekday": "Fri"}, as_of=AS_OF) == []  # not used until approved
    a = kb.approve(r["item"]["id"], AS_OF)
    assert a["status"] == "active" and a["approved_by"] == "manager"
    assert [x["id"] for x in kb.retrieve({"weekday": "Fri"}, as_of=AS_OF)] == [a["id"]]


def test_reconfirm_conflict_and_supersede(kb):
    true = M.effect("orders", {"event": "Penguins home game"}, None, AS_OF)["change_pct"]
    first = kb.propose(pens(true), "2026-10-31")["item"]  # as of an earlier night: fewer games
    again = kb.propose(pens(true), AS_OF)
    if again["op"] == "confirm":
        assert again["item"]["id"] == first["id"] and again["item"]["last_confirmed"] == AS_OF
    else:  # the number moved beyond tolerance with more evidence: the newer, larger-n item wins
        assert again["op"] == "supersede"
    # a stale item with a very different number and little evidence is superseded, with a pointer
    stale = {**pens(true + 30), "n": 2, "status": "active", "created": "2026-09-01", "last_confirmed": "2026-09-01",
             "confidence": 0.5, "evidence": []}
    kb2 = KB(kb.path.parent / "kb2.sqlite")
    kb2.save(stale, "add", "2026-09-01")
    r = kb2.propose(pens(true), AS_OF)
    assert r["op"] == "supersede"
    old = kb2.get(stale["id"])
    assert old["status"] == "retired" and old["superseded_by"] == r["item"]["id"] and r["item"]["supersedes"] == stale["id"]
    # the other way round: an existing item with more evidence keeps its place
    kb3 = KB(kb.path.parent / "kb3.sqlite")
    strong = {**pens(true + 30), "n": 99, "status": "active", "created": "2026-09-01", "last_confirmed": "2026-09-01",
              "confidence": 0.9, "evidence": []}
    kb3.save(strong, "add", "2026-09-01")
    r = kb3.propose(pens(true), AS_OF)
    assert r["op"] == "conflict_kept" and kb3.get(strong["id"])["status"] == "active" and len(kb3.list()) == 1


def test_decay_and_retire(kb):
    true = M.effect("orders", {"event": "Penguins home game"}, None, AS_OF)["change_pct"]
    it = kb.propose(pens(true), AS_OF)["item"]
    c0 = it["confidence"]
    assert kb.decay("2026-11-11")["changed"] == 0  # under a week: unchanged
    kb.decay("2026-11-20")  # two full weeks
    assert kb.get(it["id"])["confidence"] == pytest.approx(round(c0 * 0.85 ** 2, 3))
    r = kb.decay("2027-02-01")  # many weeks without fresh evidence
    assert it["id"] in r["retired"] and kb.get(it["id"])["status"] == "retired"
    # re-confirmation resets the clock
    it2 = kb.propose({**pens(true), "scope": {"event": "Penguins home game", "channel": "delivery"}}, AS_OF)["item"]
    assert kb.decay(AS_OF)["changed"] == 0 and kb.get(it2["id"])["confidence"] == it2["confidence"]


def test_compaction_merges_duplicates(kb):
    a = {"kind": "ops_rule", "scope": {"weekday": "Fri", "item": "chashu"}, "statement": "Recount chashu at 6:30 pm on Fridays",
         "effect": {"metric": "sellout_rate", "value": 0.3}, "n": 4, "status": "needs_approval", "evidence": ["2026-10-30"],
         "created": "2026-10-30", "last_confirmed": "2026-10-30", "confidence": 0.8}
    b = {**a, "statement": "On Fridays recount the chashu at 6:30", "n": 6, "evidence": ["2026-11-06"], "last_confirmed": "2026-11-06"}
    kb.save(dict(a), "add", "2026-10-30")
    kb.save(dict(b), "add", "2026-11-06")
    assert slot_of(a) == slot_of(b)
    r = kb.compact("2026-11-08")
    live = kb.list(["active", "needs_approval", "proposed"])
    assert len(r["merged"]) == 1 and len(live) == 1
    assert live[0]["n"] == 6 and set(live[0]["evidence"]) == {"2026-10-30", "2026-11-06"}
    gone = kb.get(r["merged"][0])
    assert gone["status"] == "retired" and gone["superseded_by"] == live[0]["id"]


def test_retrieval_ranks_and_never_exceeds_budget(kb):
    for ev in ("Penguins home game", "Steelers home game", "Pirates home game", "rain", "dd_promo"):
        for sc in ({"event": ev}, {"event": ev, "channel": "delivery"}):
            e = M.effect("orders", sc, None, AS_OF)
            if e["change_pct"] is not None and e["n"] >= 3:
                kb.propose({"kind": "event_effect", "scope": sc, "statement": f"{ev} effect", "effect": {"metric": "orders",
                                                                                                         "change_pct": e["change_pct"]}}, AS_OF)
    for wd in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
        v = M.value("sellout_rate", {"weekday": wd}, None, AS_OF)
        kb.propose({"kind": "item_behavior", "scope": {"item": "chashu", "weekday": wd}, "statement": f"Chashu on {wd}",
                    "effect": {"metric": "sellout_rate", "value": v["value"]}}, AS_OF)
    n_items = len(kb.list("active"))
    assert n_items >= 8
    sizes = [tokens(compact_item(i)) for i in kb.list("active")]
    for budget in list(range(0, 200, 7)) + [250, 400, 600, 1000, 5000]:
        for scope in ({}, {"weekday": "Thu", "event": ["Penguins home game", "rain"]}, {"item": "chashu"}):
            got = kb.retrieve(scope, None, 50, budget, as_of=AS_OF)
            assert sum(tokens(x) for x in got) <= budget
            assert all(set(x) >= {"id", "kind", "statement"} for x in got)  # whole items
            if budget >= max(sizes) and not scope:
                assert got
    got = kb.retrieve({"weekday": "Thu", "event": ["Penguins home game"]}, None, 3, 5000, as_of=AS_OF)
    assert got[0]["scope"].get("weekday") == "Thu" or "penguins" in got[0]["scope"].get("event", "").lower()
    assert all(x["scope"].get("weekday") in (None, "Thu") for x in kb.retrieve({"weekday": "Thu"}, None, 50, 5000, as_of=AS_OF))
    assert len(kb.retrieve({}, None, 2, 5000, as_of=AS_OF)) == 2


def test_action_items_validated(kb):
    base = {"kind": "action_item", "statement": "Pause chashu on the apps earlier on Thursdays", "owner": "kitchen lead",
            "measure": {"metric": "unavailable_cancels", "scope": {"weekday": "Thu", "channel": "delivery"}, "direction": "down"}}
    assert not kb.propose({**base, "check_on": "2026-11-01"}, AS_OF)["ok"]  # check date must be ahead
    assert not kb.propose({**base, "check_on": "2026-11-19", "owner": None}, AS_OF)["ok"]
    assert not kb.propose({**base, "check_on": "2026-11-19", "measure": {**base["measure"], "baseline": 99}}, AS_OF)["ok"]
    r = kb.propose({**base, "check_on": "2026-11-19"}, AS_OF)
    want = M.value("unavailable_cancels", {"weekday": "Thu", "channel": "delivery"}, None, AS_OF, lookback=14)
    assert r["ok"] and r["item"]["measure"]["baseline"] == want["value"] and r["item"]["action_status"] == "open"
    assert kb.propose({**base, "check_on": "2026-11-19"}, AS_OF)["op"] == "confirm"  # same action is not duplicated
