"""Review: digests and roll-ups, exception triggers on a crafted ledger, the Review agent (offline rules and ADK wiring
with a scripted fake model), agent context budgets, the Review API and the close pipeline's review step. Offline."""
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google.adk.models import BaseLlm, LlmRequest, LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

from gondola import pipeline  # noqa: E402
from gondola.agents.guardrails import check_numbers  # noqa: E402
from gondola.kb import KB, tokens  # noqa: E402
from gondola.ledger import Ledger  # noqa: E402
from gondola.review import context as C  # noqa: E402
from gondola.review import digests as D  # noqa: E402
from gondola.review import exceptions as X  # noqa: E402
from gondola.review.agent import run_review  # noqa: E402
from gondola.tools.sentinel import Notifier  # noqa: E402

DATE = "2026-11-05"
DAY = "2026-10-14"  # a quiet Wednesday for crafted ledgers
USAGE = types.GenerateContentResponseUsageMetadata(prompt_token_count=1, candidates_token_count=1, total_token_count=2)
NAME = re.compile(r'internal name is "([\w-]+)"')


class ScriptedLlm(BaseLlm):
    """Fake model (as in tests/test_agents.py): first turn calls tools, then replies with script[agent]['text'](responses)."""
    model: str = "fake-review"
    script: dict = {}

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        m = NAME.search(str(llm_request.config.system_instruction or ""))
        spec = self.script.get(m.group(1) if m else "?", {})
        last = llm_request.contents[-1] if llm_request.contents else None
        responses: dict = {}
        for p in (last.parts if last and last.parts else []):
            if p.function_response:
                responses.setdefault(p.function_response.name, []).append(p.function_response.response)
        if not responses and spec.get("calls") and llm_request.tools_dict:
            parts = [types.Part(function_call=types.FunctionCall(name=t, args=a)) for t, a in spec["calls"]]
            yield LlmResponse(content=types.Content(role="model", parts=parts), usage_metadata=USAGE)
            return
        t = spec.get("text", "{}")
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t(responses) if callable(t) else t)]),
                          usage_metadata=USAGE)


def _res(r, tool):
    v = r[tool][0]
    return v.get("result", v) if isinstance(v, dict) and set(v) == {"result"} else v


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    for k in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "GONDOLA_AGENTS", "GONDOLA_LEDGER_DB", "GONDOLA_KB_DB", "GONDOLA_DIGESTS_DB"):
        os.environ.pop(k, None)
    os.environ["GONDOLA_REVIEW_LOOP"] = "0"
    o = tmp_path_factory.mktemp("out_review")
    shutil.copytree(ROOT / "out" / "forecasts", o / "forecasts")
    for f in (ROOT / "out").glob("close_2026-1*.json"):
        shutil.copy(f, o / f.name)
    old = pipeline.OUT
    pipeline.OUT = o
    yield o
    pipeline.OUT = old


@pytest.fixture(scope="module")
def history(out):
    """Seven nights reviewed in order, so the last one has history (digests, open actions, knowledge)."""
    from gondola.review import history as H
    return H.build(days=7, end=DATE)


# ------------------------------------------------------------------ digests
def test_digests_rollup_and_lifecycle(tmp_path):
    dg = D.Digests(tmp_path / "d.sqlite")
    import pandas as pd
    days = [str(d.date()) for d in pd.date_range("2026-09-28", "2026-11-08")]  # 6 full ISO weeks, Mon..Sun
    for i, d in enumerate(days):
        inp = {"weekday": pd.Timestamp(d).day_name()[:3], "numbers": {"orders": 400 + i, "sales": 1000.0 + i, "cancels": i % 3,
                                                                      "vs_usual_pct": 1.0},
               "conditions": {}, "prep": {}, "forecast": {"error_pct": 5.0 if i % 2 else -3.0}, "sold_out": {"at": "8:00 PM"} if i % 7 == 3 else None,
               "money": {"cash_diff": -10.0 if i == 4 else 0.0, "payouts": []}, "exceptions": [], "shift_log": []}
        dg.put(D.day_digest(d, inp, {"wrong": [{"text": "Chashu sold out"}] if i % 7 == 3 else [], "well": [], "causes": []}))
    dg.put({"id": f"shift-{days[-1]}T12", "kind": "shift", "period": f"{days[-1]}T12", "date_start": days[-1], "date_end": days[-1], "bullets": []})
    r = D.rollup("2026-11-08", dg)
    weeks = dg.list("week")
    assert len(weeks) == 6 and all(w["numbers"]["days"] == 7 for w in weeks)
    w = dg.get("week-2026-W40")
    assert w["numbers"]["orders"] == sum(400 + i for i in range(7)) and w["numbers"]["sellout_days"] == 1
    assert w["numbers"]["forecast_mape_pct"] == pytest.approx((5 * 3 + 3 * 4) / 7, abs=0.05)
    assert w["wrong_themes"] == {"sell-out": 1} and w["numbers"]["cash_short_days"] == 1
    m = dg.get("month-2026-10")
    assert m and m["numbers"]["orders"] == sum(x["numbers"]["orders"] for x in weeks if x["date_end"][:7] == "2026-10")
    assert dg.get("month-2026-11") is None  # November isn't over
    # day digests older than 30 days are gone once their week is rolled up; newer ones stay
    left = {d["period"] for d in dg.list("day")}
    assert min(left) >= "2026-10-09" and "2026-11-08" in left and "2026-10-01" not in left and r["expired_days"]
    assert dg.get(f"shift-{days[-1]}T12") is not None  # today's shift logs are folded by the review, not the roll-up


def test_shift_log_and_day_digest_caps(out):
    from gondola.ledger import ledger
    from gondola.ledger.build import build_day
    led = ledger()
    build_day(DATE, led=led)
    s = D.shift_log(DATE, 19, led)
    assert 1 <= len(s["bullets"]) <= D.MAX_SHIFT_BULLETS and s["numbers"]["received"] > 0
    assert check_numbers(" ".join(s["bullets"]), [s["numbers"]])["ok"]
    inp = D.day_inputs(DATE, led)
    d = D.day_digest(DATE, inp, {"well": [{"text": "x" * 300}] * 9, "wrong": [{"text": "y" * 300}] * 9, "causes": [], "actions": [],
                                 "kb_changes": []})
    assert len(json.dumps(d, default=str)) <= D.MAX_DAY_CHARS and len(d["well"]) <= 5 and d["wrong"]


# ------------------------------------------------------------------ exceptions on a crafted ledger
def _ev(t, ts, payload, key, source="present"):
    return {"type": t, "date": DAY, "ts": f"{DAY}T{ts}", "payload": payload, "source": source, "key": key}


@pytest.fixture()
def crafted(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    rows = [
        _ev("order.received", "17:30:00", {"order_id": "p1", "channel": "doordash", "promise": "17:50", "items": ["Gyoza"]}, "r1"),
        _ev("order.received", "17:31:00", {"order_id": "p2", "channel": "ubereats", "promise": "17:52", "items": ["Karaage"]}, "r2"),
        _ev("order.received", "17:32:00", {"order_id": "p3", "channel": "grubhub", "promise": "17:55", "items": ["Tonkotsu"]}, "r3"),
        _ev("order.handed_off", "17:56:00", {"order_id": "p3", "channel": "grubhub", "wait_min": 24, "hold_min": 0, "late_min": 1}, "h3"),
    ]
    for i, m in enumerate(["18:00", "18:05", "18:12", "18:20"]):
        rows.append(_ev("order.cancelled", f"{m}:00", {"order_id": f"c{i}", "channel": "doordash", "reason": "item_unavailable",
                                                         "amount": 20.0, "items": ["Chashu Don"]}, f"c{i}", "pos"))
    rows += [
        _ev("action.applied", "18:00:00", {"action": "incident", "station": "fryer", "value": 0.5, "reason": "fryer at half speed"}, "i1"),
        _ev("action.applied", "18:25:00", {"action": "resume", "station": "fryer"}, "i2"),
        _ev("payout.report_arrived", "12:00:00", {"for_date": "2026-10-12", "channel": "doordash", "difference": -90.0, "error_charges": 3,
                                                   "recoverable_usd": 86.0, "n_disputable": 3}, "p", "books"),
        _ev("payout.report_arrived", "12:00:00", {"for_date": "2026-10-12", "channel": "grubhub", "difference": 0.0, "error_charges": 0,
                                                   "recoverable_usd": 0}, "p2", "books"),
        _ev("forecast.issued", "00:00:00", {"horizon": "day", "for_date": DAY, "total": {"p10": 900, "p50": 1000, "p90": 1100}}, "f", "forecast"),
    ]
    led.extend(rows)
    return led


def test_exception_triggers(crafted):
    now = datetime.fromisoformat(f"{DAY}T18:30:00")
    c = {x["kind"]: x for x in X.candidates(DAY, now, crafted)}
    assert set(c) == {"late_orders", "cancel_cluster", "payout_issue", "station_incident", "forecast_miss"}
    assert c["late_orders"]["evidence"]["orders"] == 2 and set(c["late_orders"]["evidence"]["order_ids"]) == {"p1", "p2"}
    assert c["cancel_cluster"]["evidence"]["cancels"] == 4 and c["cancel_cluster"]["evidence"]["with_chashu"] == 4
    assert c["station_incident"]["evidence"]["minutes"] == 25.0 and c["station_incident"]["evidence"]["station"] == "fryer"
    assert c["payout_issue"]["evidence"]["recoverable_usd"] == 86.0 and c["payout_issue"]["severity"] == "high"
    assert c["forecast_miss"]["evidence"]["side"] == "below"
    early = {x["kind"] for x in X.candidates(DAY, datetime.fromisoformat(f"{DAY}T17:59:00"), crafted)}
    assert "late_orders" not in early and "cancel_cluster" not in early  # p1 is only 9 min past its promise
    later = {x["kind"] for x in X.candidates(DAY, datetime.fromisoformat(f"{DAY}T18:01:00"), crafted)}
    assert "late_orders" in later and "station_incident" not in later  # the fryer has been slow 1 minute
    assert "forecast_miss" not in {x["kind"] for x in X.candidates(DAY, datetime.fromisoformat(f"{DAY}T16:00:00"), crafted)}


def test_scan_decides_records_and_bundles_alerts(crafted, tmp_path):
    nt = Notifier(outbox=tmp_path / "outbox.jsonl")
    nt.sms_live = nt.email_live = nt.live = False
    now = datetime.fromisoformat(f"{DAY}T18:30:00")
    new = X.scan(DAY, now, crafted, notifier=nt, model=False)
    assert len(new) == 5
    dec = {x["kind"]: x["decision"] for x in new}
    assert dec == {"late_orders": "present", "cancel_cluster": "present", "payout_issue": "note", "station_incident": "alert",
                   "forecast_miss": "present"}
    for x in new:
        assert check_numbers(x["note"], [x["evidence"]])["ok"], x["note"]
    sms = [json.loads(line) for line in (tmp_path / "outbox.jsonl").read_text().splitlines()]
    assert len(sms) == 1 and sms[0]["status"] == "dry_run" and "fryer" in sms[0]["body"]
    assert len(crafted.query(DAY, ["exception.raised"])) == 5
    assert X.scan(DAY, now, crafted, notifier=nt, model=False) == []  # raised once
    ids = [x["id"] for x in X.raised(DAY, crafted)]
    assert X.resolve(DAY, ids[0], led=crafted) and X.raised(DAY, crafted)[0]["resolved"]
    assert not X.resolve(DAY, "nope", led=crafted)
    # quiet hours: a 1:30 am alert is held for 8 am
    led2 = Ledger(tmp_path / "l2.sqlite")
    led2.extend([_ev("action.applied", "00:30:00", {"action": "incident", "station": "noodles"}, "q1")])
    X.scan(DAY, datetime.fromisoformat(f"{DAY}T01:30:00"), led2, notifier=nt, model=False)
    assert json.loads((tmp_path / "outbox.jsonl").read_text().splitlines()[-1])["status"] == "held_for_8am"


def test_exceptions_agent_fake_model(crafted):
    now = datetime.fromisoformat(f"{DAY}T18:30:00")
    cid = f"{DAY}:incident:fryer:1800"
    late_id = [c["id"] for c in X.candidates(DAY, now, crafted) if c["kind"] == "late_orders"][0]

    def text(r):
        t = _res(r, "get_trigger")
        return json.dumps([{"id": t["id"], "decision": "present", "note": f"Fryer slow for {t['evidence']['minutes']} min; pad times."},
                           {"id": late_id, "decision": "alert", "note": "37 orders late."}])  # invented number
    script = {"exceptions": {"calls": [("get_trigger", {"exception_id": cid})], "text": text}}
    new = {x["id"]: x for x in X.scan(DAY, now, crafted, model=ScriptedLlm(script=script), send=False)}
    assert new[cid]["by"] == "exceptions-agent" and new[cid]["decision"] == "present" and "25.0 min" in new[cid]["note"]
    late = new[late_id]
    assert late["by"] == "rules" and "37" not in late["note"]  # the unsupported number fell back to the rules


# ------------------------------------------------------------------ review agent
def test_review_offline_output(out, history):
    r = run_review(DATE, model=False)
    assert r["mode"] == "offline" and r["status"] == "done"
    wrong = " ".join(x["text"] for x in r["wrong"])
    assert "sold out at 8:39 PM" in wrong and "12 app orders" in wrong
    assert any("Cash drawer short $23.50" in x["text"] for x in r["wrong"])
    assert any("DoorDash" in x["text"] and "$86.40" in x["text"] for x in r["wrong"])
    assert r["causes"] and "Chashu" in r["causes"][0]["text"]
    for sec in ("well", "wrong", "causes"):
        for x in r[sec]:
            assert check_numbers(x["text"], [D.day_inputs(DATE), x["evidence"]])["ok"], x["text"]
    assert r["actions"] and all(a["owner"] and a["check_on"] > DATE and a["measure"]["metric"] for a in r["actions"])
    ops = {c["op"] for c in r["kb_changes"]}
    assert ops & {"add", "confirm", "supersede"}
    kb = KB()
    for c in r["kb_changes"]:
        if c["op"] in ("add", "confirm", "supersede") and c.get("kind") != "action_item":
            it = kb.get(c["id"])
            assert it["n"] and it["validation"]["recomputed"] is not None or it["kind"] == "ops_rule"
    assert r["context"]["tokens"] <= r["context"]["budget_tokens"] == 6000
    from gondola.ledger import ledger
    assert ledger().query(DATE, ["review.completed"])[0].payload["digest_id"] == f"day-{DATE}"
    dd = D.digests().get(f"day-{DATE}")
    assert dd["wrong"] and dd["shift_log"] and not D.digests().list("shift", start=DATE, end=DATE)  # folded


def test_action_items_rechecked(out, history):
    kb = KB()
    acts = kb.list(None, "action_item")
    assert acts
    closed = [a for a in acts if a.get("action_status") in ("done", "not_working", "expired")]
    for a in closed:
        assert a["status"] == "retired" and a["outcome"]["checked_on"] >= a["check_on"] or a["action_status"] == "expired"


def test_review_agent_fake_model(out, history):
    def text(r):
        dg = _res(r, "get_day_digest")
        n = dg["numbers"]
        eff = _res(r, "measure_effect")
        return json.dumps({
            "well": [{"text": f"Sales reached ${n['sales']:,.2f} on {n['orders']} orders.", "evidence": {}}],
            "wrong": [{"text": f"{dg['sold_out']['app_cancels']} app orders were cancelled after chashu sold out at {dg['sold_out']['at']}."},
                      {"text": "Waits averaged 31 min at the peak."}],  # invented: no such number anywhere
            "causes": [{"text": f"Rain usually moves orders {eff['change_pct']:+.1f}% ({eff['n']} past days)."}],
            "actions": [{"statement": "Recount chashu at 6:30 pm on Thursdays", "owner": "kitchen lead", "check_on": "2026-11-19",
                         "measure": {"metric": "unavailable_cancels", "scope": {"weekday": "Thu", "channel": "delivery"}, "direction": "down"}}],
            "kb": [{"kind": "event_effect", "scope": {"event": "rain"}, "statement": "Rain moves orders",
                    "effect": {"metric": "orders", "change_pct": eff["change_pct"]}},
                   {"kind": "event_effect", "scope": {"event": "Penguins home game"}, "statement": "Penguins games move orders",
                    "effect": {"metric": "orders", "change_pct": 55.0}}]})  # invented effect
    script = {"review": {"calls": [("get_day_digest", {"date": DATE}), ("measure_effect", {"event": "rain"})], "text": text}}
    r = run_review(DATE, model=ScriptedLlm(script=script))
    assert r["mode"] == "adk"
    assert {c["tool"] for c in r["tool_calls"]} >= {"get_day_digest", "measure_effect"}
    assert any("Sales reached" in x["text"] for x in r["well"])
    assert not any("31 min" in x["text"] for x in r["wrong"]) and any("31" in d["text"] for d in r["dropped"])
    assert any("12 app orders" in x["text"] for x in r["wrong"])
    kc = {c["statement"]: c for c in r["kb_changes"] if c.get("statement")}
    assert kc["Penguins games move orders"]["op"] == "rejected"
    assert kc["Rain moves orders"]["op"] in ("add", "confirm", "supersede")
    assert any(a["text"].startswith("Recount chashu") for a in r["actions"])


# ------------------------------------------------------------------ contexts (budgets)
@pytest.mark.parametrize("agent", ["rush", "outlook", "exceptions", "review"])
def test_contexts_within_budget(out, history, agent):
    c = C.build(agent, DATE)
    assert c["tokens"] == tokens(c["payload"]) <= c["budget_tokens"] == C.BUDGETS[agent]


def test_context_drops_whole_pieces_when_tight(out, history, monkeypatch):
    full = C.build("review", DATE)
    monkeypatch.setitem(C.BUDGETS, "review", full["tokens"] - 50)
    tight = C.build("review", DATE)
    assert tight["tokens"] <= tight["budget_tokens"] and tight["dropped"]
    kb_full = C.build("outlook", DATE)["payload"]["kb"]
    assert len(kb_full) <= 8 and all(x["kind"] == "event_effect" for x in kb_full)


# ------------------------------------------------------------------ API
def test_review_api(out, history):
    from fastapi.testclient import TestClient
    from gondola.api.app import app
    with TestClient(app) as c:
        d = c.get(f"/api/review/day/{DATE}").json()
        assert d["status"] == "done" and d["digest_id"] == f"day-{DATE}"
        assert {"well", "wrong", "causes", "actions", "kb_changes"} <= set(d)
        assert all({"id", "text", "owner", "check_on", "measure", "status"} <= set(a) for a in d["actions"])
        r = c.post("/api/review/run", json={"date": DATE}).json()
        assert r["status"] == "done" and r["mode"] == "offline"
        assert c.post("/api/review/run", json={"date": "2026-11-09"}).status_code == 409
        kb = c.get("/api/review/kb").json()
        assert kb and {"id", "kind", "statement", "status", "confidence"} <= set(kb[0])
        pend = c.get("/api/review/kb", params={"status": "needs_approval"}).json()
        assert pend and all(x["status"] == "needs_approval" for x in pend)
        a = c.post(f"/api/review/kb/{pend[0]['id']}/approve").json()
        assert a["ok"] and a["item"]["status"] == "active"
        t = c.post(f"/api/review/kb/{pend[0]['id']}/retire", json={"reason": "test"}).json()
        assert t["item"]["status"] == "retired" and t["item"]["retired_reason"] == "test"
        assert c.get("/api/review/kb", params={"kind": "nope"}).status_code == 400
        acts = c.get("/api/review/actions").json()
        assert acts and {"id", "text", "owner", "created", "check_on", "measure", "status"} <= set(acts[0])
        op = [x for x in acts if x["status"] == "open"]
        if op:
            s = c.post(f"/api/review/actions/{op[0]['id']}/status", json={"status": "done"}).json()
            assert s["item"]["action_status"] == "done"
        for kind in ("day", "week", "month"):
            dg = c.get("/api/review/digests", params={"kind": kind, "limit": 5}).json()
            assert all({"id", "kind", "period", "summary", "numbers"} <= set(x) for x in dg)
        assert c.get("/api/review/digests", params={"kind": "day"}).json()[0]["period"] == DATE
        for agent in ("rush", "outlook", "exceptions", "review"):
            cx = c.get("/api/review/context", params={"agent": agent, "date": DATE}).json()
            assert cx["tokens"] <= cx["budget_tokens"]
        assert c.get("/api/review/context", params={"agent": "nobody"}).status_code == 400
        ex = c.get("/api/review/exceptions", params={"date": DATE}).json()
        assert ex and {"id", "ts", "kind", "severity", "title", "decision", "note", "resolved"} <= set(ex[0])
        assert c.post(f"/api/review/exceptions/{ex[0]['id']}/resolve").json()["ok"]
        assert c.get("/api/review/exceptions", params={"date": DATE}).json()[0]["resolved"] in (True, False)
        assert c.post("/api/review/scan", json={"date": DATE}).json() == []  # already scanned at close
        assert "running" in c.get("/api/review/loop").json()


# ------------------------------------------------------------------ the close still works, and reviews last
def test_close_pipeline_runs_review_last(tmp_path):
    o = tmp_path / "out_close"
    o.mkdir()
    shutil.copy(ROOT / "out" / "backtest_cache.csv", o / "backtest_cache.csv")
    shutil.copytree(ROOT / "out" / "forecasts", o / "forecasts")
    old = pipeline.OUT
    pipeline.OUT = o
    try:
        nt = Notifier(outbox=o / "outbox.jsonl")
        nt.sms_live = nt.email_live = nt.live = False
        res = pipeline.run_close(DATE, render=False, notifier=nt, agent_model=False, portion_counts={"chashu": 0})
        steps = [s["step"] for s in res["log"]]
        assert steps[-1] == "review" and res["log"][-1]["status"] == "done"
        assert res["status"] == "done" and len([f for f in res["findings"] if f.get("urgency") == "urgent"]) == 3
        assert res["review"]["digest_id"] == f"day-{DATE}" and res["review"]["mode"] == "offline"
        assert (o / "kb.sqlite").exists() and (o / "digests.sqlite").exists() and (o / "ledger.sqlite").exists()
        # a failing review never changes the close's status
        res2 = pipeline.run_close(DATE, render=False, notifier=nt, agent_model=False, force=True, fail={"review"})
        assert res2["log"][-1] == {**res2["log"][-1], "step": "review", "status": "failed"} and res2["status"] == "done"
    finally:
        pipeline.OUT = old
