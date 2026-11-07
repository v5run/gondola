"""The ADK agent graph, run end to end with a scripted fake model (no API key, no network).

The fake (a google.adk BaseLlm subclass) plays each specialist: on its first turn it asks for the agent's tools with
real arguments; once the tool results come back it writes a reply quoting numbers from those results. The test
then checks that ADK's Runner really invoked every agent, the calls reached the real tool functions, each agent's
reply landed in session state under its output_key, and the guardrail callback replaced a reply with an invented
number. The same fake drives the Ask agent (integrations.llm.ask_llm) and the API in agent mode.
"""
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google.adk.models import BaseLlm, LlmRequest, LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

from gondola import pipeline  # noqa: E402
from gondola.agents import adk_graph, guardrails  # noqa: E402
from gondola.integrations import llm  # noqa: E402
from gondola.metrics import Store  # noqa: E402
from gondola.tools import analyst, books, demand, plan, sentinel, stock  # noqa: E402

DATE, TOMORROW = "2026-11-05", "2026-11-06"
USAGE = types.GenerateContentResponseUsageMetadata(prompt_token_count=1, candidates_token_count=1, total_token_count=2)
NAME = re.compile(r'internal name is "([\w-]+)"')


class ScriptedLlm(BaseLlm):
    """Fake model. script[agent] = {"calls": [(tool, args)] | fn(state) -> [...], "text": fn(responses) -> str}."""
    model: str = "fake-gondola"
    script: dict = {}
    requests: list = []

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        si = str(llm_request.config.system_instruction or "")
        m = NAME.search(si)
        agent = m.group(1) if m else "?"
        self.requests.append({"agent": agent, "tools": sorted(llm_request.tools_dict)})
        spec = self.script.get(agent, {})
        last = llm_request.contents[-1] if llm_request.contents else None
        responses: dict[str, list] = {}
        for p in (last.parts if last and last.parts else []):
            if p.function_response:
                responses.setdefault(p.function_response.name, []).append(p.function_response.response)
        calls = spec.get("calls") or []
        if not responses and calls and llm_request.tools_dict:
            parts = [types.Part(function_call=types.FunctionCall(name=t, args=a)) for t, a in calls]
            yield LlmResponse(content=types.Content(role="model", parts=parts), usage_metadata=USAGE)
            return
        text = spec.get("text", lambda r: f"{agent}: nothing to add.")
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text(responses) if callable(text) else text)]),
                          usage_metadata=USAGE)


def _one(r: dict, tool: str) -> Any:
    v = r[tool][0]
    return v.get("result", v) if isinstance(v, dict) and set(v) == {"result"} else v


def close_script(res: dict, overrides: dict | None = None) -> dict:
    """What a well-behaved model would do for each specialist, given the pipeline's results."""
    fc, p, b = res["demand"], res["plan"], res["books"]
    payout_dates = sorted({v["date"] for v in b["verified"]})

    def books_text(r):
        c = _one(r, "cash_variance")
        out = [f"Cash drawer ${abs(c['difference']):.2f} short (expected ${c['expected']:.2f}, counted ${c['counted']:.2f})."]
        for resp in r.get("match_payouts", []):
            for ch in resp["channels"]:
                if ch["difference"] is not None and ch["difference"] < -1:
                    out.append(f"{ch['channel']} paid ${-ch['difference']:.2f} less than expected for {resp['date']}.")
        return " ".join(out)

    def demand_text(r):
        f = _one(r, "forecast_day")
        return (f"Tomorrow looks like {f['p50']:.0f} orders (likely {f['p10']:.0f} to {f['p90']:.0f}), "
                f"rush {f['rush']['start']} to {f['rush']['end']}, like {_one(r, 'similar_days')[0]['date']}.")

    def analyst_text(r):
        c = _one(r, "compare_day")
        return f"Net sales were ${c['net_sales']['value']:,.2f} on {c['orders']['value']:.0f} orders ({c['net_sales']['change_pct']:+.1%} vs usual)."

    def plan_text(r):
        nv = _one(r, "newsvendor")
        return f"Prep {nv['chashu_portions']} chashu portions for about {nv['orders_planned']:.0f} planned orders."

    m = b["money"]
    s = {
        "books": {"calls": [("match_payouts", {"date": d}) for d in payout_dates] + [("cash_variance", {"date": DATE})],
                  "text": books_text},
        "stock": {"calls": [("update_ledger", {"date": DATE})], "text": lambda r: "Ledger is up to date; usage matches sales."},
        "demand": {"calls": [("forecast_day", {"date": TOMORROW}), ("similar_days", {"date": TOMORROW})], "text": demand_text},
        "analyst": {"calls": [("compare_day", {"date": DATE}), ("explain_day", {"date": DATE})], "text": analyst_text},
        "plan": {"calls": [("newsvendor", {"p10": fc["p10"], "p50": fc["p50"], "p90": fc["p90"],
                                           "portions_per_order": p["portions_per_order"]})], "text": plan_text},
        "report": {"text": f"A quieter Thursday: {m['orders']} orders and ${m['net_sales']:,.0f} in net sales. "
                           f"The cash drawer was ${-b['cash']['difference']:.2f} short. Tomorrow looks like {fc['p50']:.0f} orders."},
        "sentinel": {"text": f"Text the manager now: cash drawer ${-b['cash']['difference']:.2f} short, plus the payout disputes."},
        "guard": {"text": "Pause chashu on the apps when the safety-net trigger hits; keep it for dine-in."},
    }
    s.update(overrides or {})
    return s


@pytest.fixture(scope="module")
def offline_res(tmp_path_factory):
    """One deterministic close (no agents) in a temp out/ folder, reused as the graph's facts."""
    out = tmp_path_factory.mktemp("out_agents")
    cache = ROOT / "out" / "backtest_cache.csv"
    if cache.exists():
        shutil.copy(cache, out / "backtest_cache.csv")  # skip re-running 60 backtests
    old = pipeline.OUT
    pipeline.OUT = out
    try:
        res = pipeline.run_close(DATE, render=False, agent_model=False, notifier=sentinel.Notifier(out / "outbox.jsonl"))
    finally:
        pipeline.OUT = old
    assert res["status"] == "done" and res["agents"] is None
    return res


@pytest.fixture
def spies(monkeypatch):
    """Count calls that reach the real tool functions (the wrappers call them through their modules)."""
    hits: dict[str, int] = {}

    def spy(mod, name):
        orig = getattr(mod, name)

        def wrapped(*a, **k):
            hits[name] = hits.get(name, 0) + 1
            return orig(*a, **k)
        monkeypatch.setattr(mod, name, wrapped)
    for mod, name in [(books, "match_payouts"), (books, "cash_variance"), (stock, "update_ledger"), (demand, "run_forecast"),
                      (analyst, "compare_periods"), (analyst, "explain_change"), (analyst, "find_similar_days"),
                      (plan, "newsvendor_par")]:
        spy(mod, name)
    return hits


def test_graph_shape_and_offline_default(monkeypatch):
    g = adk_graph.build_close_graph(ScriptedLlm())
    assert [a.name for a in g.sub_agents] == ["reconcile", "understand", "communicate", "guard"]
    leaves = [x.name for a in g.sub_agents for x in (a.sub_agents or [a])]
    assert leaves == adk_graph.SPECIALISTS
    for a in (x for s in g.sub_agents for x in (s.sub_agents or [s])):
        assert a.output_key and a.after_model_callback is guardrails.after_model_callback
        assert a.after_tool_callback is adk_graph.record_tool_result
    monkeypatch.setenv("GONDOLA_AGENTS", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    assert adk_graph.configured_model() is None  # agent mode is opt-in
    monkeypatch.setenv("GONDOLA_AGENTS", "adk")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    assert adk_graph.configured_model() is None  # no key: offline
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("GONDOLA_MODEL", "gemini-test")
    assert adk_graph.configured_model() == "gemini-test"


def test_close_graph_end_to_end(offline_res, spies):
    fake = ScriptedLlm(script=close_script(offline_res), requests=[])
    out = adk_graph.run_close_graph(offline_res, DATE, model=fake, db=offline_res["db"])
    # every specialist ran, through ADK's Runner
    assert set(adk_graph.SPECIALISTS) <= set(out["invoked"])
    assert {r["agent"] for r in fake.requests} == set(adk_graph.SPECIALISTS)
    # tool calls reached the real tools, with the arguments the model chose
    called = {(c["agent"], c["tool"]) for c in out["tool_calls"]}
    assert {("books", "match_payouts"), ("books", "cash_variance"), ("stock", "update_ledger"), ("demand", "forecast_day"),
            ("demand", "similar_days"), ("analyst", "compare_day"), ("analyst", "explain_day"), ("plan", "newsvendor")} <= called
    for name in ("match_payouts", "cash_variance", "update_ledger", "compare_periods", "explain_change", "find_similar_days",
                 "newsvendor_par"):
        assert spies.get(name, 0) >= 1, name
    assert spies.get("run_forecast", 0) == 0  # Demand quotes the pipeline's calibrated forecast, not a fresh one
    # tool results are in state (the guardrail's facts) and equal what the real tools return
    st = Store(offline_res["db"])
    cash = out["facts"]["tool:books:cash_variance"][0]["result"]
    assert cash == adk_graph.clean(books.cash_variance(st, DATE)) and cash["difference"] == -23.5
    fc = out["facts"]["tool:demand:forecast_day"][0]["result"]
    assert (fc["p10"], fc["p50"], fc["p90"]) == tuple(offline_res["demand"][k] for k in ("p10", "p50", "p90"))
    # each agent's reply landed in session state under its output_key
    assert set(out["outputs"]) == {"books", "stock", "demand", "analyst", "plan", "report", "sentinel", "guard"}
    assert "$23.50 short" in out["outputs"]["books"] and "orders" in out["outputs"]["demand"]
    assert out["outputs"]["plan"].startswith(f"Prep {offline_res['plan']['newsvendor']['chashu_portions']} chashu")
    assert not out["guardrail_blocked"]
    # nothing the agents wrote has an untraceable number
    srcs = [offline_res.get(k) for k in ("books", "analyst", "demand", "plan", "findings", "stock")]
    for k in ("books", "demand", "analyst", "report", "sentinel"):
        assert guardrails.check_numbers(out["outputs"][k], srcs)["ok"], (k, out["outputs"][k])


def test_guardrail_callback_blocks_invented_number(offline_res):
    bad = "Text the manager now: DoorDash shorted us $9,999.99 tonight."
    fake = ScriptedLlm(script=close_script(offline_res, {"sentinel": {"text": bad}}), requests=[])
    out = adk_graph.run_close_graph(offline_res, DATE, model=fake, db=offline_res["db"])
    assert out["outputs"]["sentinel"] == guardrails.FALLBACK  # replaced before it reached state
    assert set(out["guardrail_blocked"]) == {"sentinel"}
    assert out["guardrail_blocked"]["sentinel"]["unsupported"] == ["$9,999.99"]
    assert out["outputs"]["books"] != guardrails.FALLBACK  # the honest agents are untouched


def test_after_model_callback_unit():
    class Ctx:
        agent_name = "report"

        def __init__(self, state):
            self._s = state
            self.state = self

        def to_dict(self):
            return dict(self._s)

        def __setitem__(self, k, v):
            self._s[k] = v

    ok = LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Cash was $23.50 short.")]))
    ctx = Ctx({"tool:books:cash_variance": [{"result": {"difference": -23.5}}]})
    assert guardrails.after_model_callback(ctx, ok) is None
    bad = LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Cash was $24.00 short.")]))
    r = guardrails.after_model_callback(ctx, bad)
    assert r.content.parts[0].text == guardrails.FALLBACK and ctx._s["guardrail:report"]["unsupported"] == ["$24.00"]
    call = LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="x", args={}))]))
    assert guardrails.after_model_callback(ctx, call) is None


@pytest.fixture
def tmp_out(tmp_path):
    cache = ROOT / "out" / "backtest_cache.csv"
    if cache.exists():
        shutil.copy(cache, tmp_path / "backtest_cache.csv")
    old = pipeline.OUT
    pipeline.OUT = tmp_path
    yield tmp_path
    pipeline.OUT = old


def test_pipeline_agent_mode_uses_checked_wording(offline_res, tmp_out):
    fake = ScriptedLlm(script=close_script(offline_res), requests=[])
    events = []
    res = pipeline.run_close(DATE, render=False, agent_model=fake, notifier=sentinel.Notifier(tmp_out / "outbox.jsonl"),
                             on_event=lambda n, p: events.append((n, p)))
    assert res["status"] == "done"
    ag = res["agents"]
    assert ag["mode"] == "adk" and ag["model"] == "fake-gondola" and not ag.get("error")
    assert set(adk_graph.SPECIALISTS) <= set(ag["invoked"])
    ctx = res["report"]["context"]
    assert ctx["wording"] == "agents" and ctx["summary"] == ag["outputs"]["report"]
    assert res["guardrail_report"]["ok"]
    # numbers are still the pipeline's: same findings and card as the offline close
    assert [f["kind"] for f in res["findings"]] == [f["kind"] for f in offline_res["findings"]]
    assert res["plan"]["card"] == offline_res["plan"]["card"]
    # the SMS stays the numbered template (replies "1"/"2"/"3" map to it)
    sms = [json.loads(x) for x in (tmp_out / "outbox.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(x["channel"] == "sms" and "1)" in x["body"] for x in sms)
    names = [p["agent"] for n, p in events if n == "agent" and p["status"] == "running"]
    assert names[0] == "close_coordinator" and set(adk_graph.SPECIALISTS) <= set(names)
    saved = json.loads((tmp_out / f"close_{DATE}.json").read_text(encoding="utf-8"))
    assert saved["agents"]["outputs"]["report"] == ag["outputs"]["report"] and "facts" not in saved["agents"]
    assert not Path(saved["db"]).is_absolute()


def test_pipeline_agent_invented_number_keeps_template(offline_res, tmp_out):
    bad = {"report": {"text": "Huge night: 9,876 orders and $123,456 in net sales."}}
    fake = ScriptedLlm(script=close_script(offline_res, bad), requests=[])
    res = pipeline.run_close(DATE, render=False, agent_model=fake, notifier=sentinel.Notifier(tmp_out / "outbox.jsonl"))
    ctx = res["report"]["context"]
    assert ctx.get("wording") != "agents" and "9,876" not in ctx["summary"]
    assert "report" in res["agents"]["guardrail_blocked"]


def test_pipeline_agent_failure_is_soft(offline_res, tmp_out):
    class Broken(ScriptedLlm):
        async def generate_content_async(self, llm_request, stream=False):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    res = pipeline.run_close(DATE, render=False, agent_model=Broken(), notifier=sentinel.Notifier(tmp_out / "outbox.jsonl"))
    assert res["status"] == "done" and res["agents"]["error"]
    assert res["report"]["context"].get("wording") != "agents"


# ------------------------------------------------------------------ Ask agent
def ask_script(value_fn: Callable[[dict], str]) -> dict:
    return {"ask": {"calls": [("query_metric", {"metric": "net_sales", "start": "2026-11-03", "end": "2026-11-03"})],
                    "text": value_fn}}


def test_ask_llm_with_fake_model(spies):
    st = Store()
    real = float(st.query_metric("net_sales", "2026-11-03", "2026-11-03").value.iloc[0])
    fake = ScriptedLlm(script=ask_script(lambda r: f"Net sales on Tue Nov 3 were ${_one(r, 'query_metric')[0]['value']:,.2f}."),
                       requests=[])
    txt = llm.ask_llm("sales on nov 3?", st, model=fake)
    assert txt == f"Net sales on Tue Nov 3 were ${real:,.2f}."
    assert fake.requests[0]["agent"] == "ask" and "query_metric" in fake.requests[0]["tools"]
    liar = ScriptedLlm(script=ask_script(lambda r: "Net sales on Nov 3 were $99,999.00."), requests=[])
    assert llm.ask_llm("sales on nov 3?", st, model=liar) is None  # guardrail blocked -> caller uses the offline router


def test_api_ask_in_agent_mode(monkeypatch):
    from fastapi.testclient import TestClient
    from gondola.api.app import app
    fake = ScriptedLlm(script=ask_script(lambda r: f"DoorDash and all: ${_one(r, 'query_metric')[0]['value']:,.2f} on Nov 3."),
                       requests=[])
    monkeypatch.setenv("GONDOLA_AGENTS", "adk")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(adk_graph, "configured_model", lambda require_mode=True: fake)
    with TestClient(app) as c:
        a = c.post("/api/ask", json={"question": "sales on nov 3"}).json()
        assert a["mode"] == "adk" and a["text"].endswith("on Nov 3.") and a["clarify"] is False
        assert c.get("/api/integrations").json()["agents"] == {"live": True, "mode": "adk", "requested": True}
        clar = c.post("/api/ask", json={"question": "asdf"}).json()
        assert clar["clarify"] is True and clar["mode"] == "offline"  # unclear questions never go to the model
