"""The agent graph in Google ADK.

Close Coordinator = SequentialAgent:
  1. Reconcile (ParallelAgent): Books, Stock, Demand
  2. Understand and prepare (Sequential): Analyst, Plan
  3. Communicate (ParallelAgent): Report, Sentinel
  4. Protect: Guard
Ask runs on its own, outside the close.

Each specialist is an LlmAgent whose tools are the plain Python functions in gondola/tools (wrapped below with
simple typed signatures). Two callbacks are attached to every agent:
  - after_tool_callback (record_tool_result): copies each tool result into session state, so the guardrail can
    see it ("tool:<agent>:<tool>").
  - after_model_callback (guardrails.after_model_callback): a reply with a number that is not in session state
    (seeded pipeline facts + tool results) is replaced with a number-free fallback and flagged.

Agent mode (GONDOLA_AGENTS=adk plus a model key) is opt-in. The deterministic pipeline (gondola/pipeline.py) still
computes every number; `run_close_graph` runs this graph on top of those facts for the wording and explanations,
and the pipeline checks the wording against its own facts again before using it. Building the graph needs no key
(tests do this); tests run it end to end with a fake BaseLlm (tests/test_agents.py).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import uuid
import warnings
from datetime import date as _date, datetime
from typing import Any

with warnings.catch_warnings():  # ADK 2.x marks Sequential/ParallelAgent deprecated in favour of Workflow
    warnings.simplefilter("ignore", DeprecationWarning)
    from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from ..metrics import ROOT, Store
from ..tools import analyst, books, demand, plan, stock
from .guardrails import after_model_callback

MODEL = os.getenv("GONDOLA_MODEL", "gemini-flash-latest")
APP = "gondola"
RULES = ("Rules: every number you write must come from a tool result or the facts above; never estimate, round "
         "differently or do arithmetic of your own. You propose, code acts: never claim an action happened unless a "
         "tool returned status ok. Write for a busy restaurant manager: short, plain sentences.")
SPECIALISTS = ["books", "stock", "demand", "analyst", "plan", "report", "sentinel", "guard"]

# ------------------------------------------------------------------ tool context (which database, cached forecasts)
_CTX: dict[str, Any] = {"db": ROOT / "data" / "gondola.duckdb", "gen": 0, "forecasts": {}}
_CTX_LOCK = threading.Lock()
_LOCAL = threading.local()  # one read-only DuckDB connection per thread (ADK may run tools off the loop thread)


def set_context(db=None, forecasts: dict | None = None) -> None:
    """Point the tools at a database, and pre-load forecasts the pipeline already made (so the Demand agent
    quotes the same calibrated numbers the pipeline used)."""
    with _CTX_LOCK:
        if db is not None and str(db) != str(_CTX["db"]):
            _CTX["db"], _CTX["gen"] = db, _CTX["gen"] + 1
        _CTX["forecasts"] = dict(forecasts or {})


def _s() -> Store:
    with _CTX_LOCK:
        db, gen = _CTX["db"], _CTX["gen"]
    if getattr(_LOCAL, "gen", None) != gen or getattr(_LOCAL, "store", None) is None:
        _LOCAL.store, _LOCAL.gen = Store(db), gen
    return _LOCAL.store


def clean(obj):
    """JSON-safe copy of a tool result (numpy / pandas / dates -> plain types; NaN -> None)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if hasattr(obj, "to_dict") and hasattr(obj, "columns"):
        return clean(obj.to_dict("records"))
    if isinstance(obj, (datetime, _date)) or type(obj).__name__ == "Timestamp":
        return str(obj)[:19] if isinstance(obj, datetime) else str(obj)
    if hasattr(obj, "item") and not isinstance(obj, (int, float)):
        obj = obj.item()  # numpy scalar
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else float(obj)
    return str(obj)


# --- tool wrappers with simple typed signatures (ADK reads the signature + docstring) --------------
def match_payouts(date: str) -> dict:
    """Reconcile delivery-app payouts for a business date (YYYY-MM-DD) against POS orders and contract rates."""
    return clean(books.match_payouts(_s(), date))


def cash_variance(date: str) -> dict:
    """Compare the cash drawer's expected and counted cash for a business date (YYYY-MM-DD)."""
    return clean(books.cash_variance(_s(), date))


def update_ledger(date: str) -> dict:
    """Roll the ingredient ledger forward to a count date (YYYY-MM-DD) and report gaps against the count."""
    return clean(stock.update_ledger(_s(), date))


def forecast_day(date: str) -> dict:
    """Forecast orders for a date (YYYY-MM-DD): P10/P50/P90, rush window and similar past days."""
    fc = _CTX["forecasts"].get(date)
    if fc is None:
        fc = demand.run_forecast(_s(), date)
    fc = clean(fc)
    return {k: fc.get(k) for k in ("date", "p10", "p50", "p90", "rush", "similar_days", "model") if k in fc}


def compare_day(date: str) -> dict:
    """Compare a day (YYYY-MM-DD) with the average of the last 4 same weekdays."""
    return clean(analyst.compare_periods(_s(), date))


def explain_day(date: str) -> dict:
    """Break a day's (YYYY-MM-DD) change into channels and dayparts, with weather and events."""
    return clean(analyst.explain_change(_s(), date))


def similar_days(date: str) -> list:
    """Past days most like the given date (YYYY-MM-DD): weekday, weather, events, school, promos."""
    return clean(analyst.find_similar_days(_s(), date))


def newsvendor(p10: float, p50: float, p90: float, portions_per_order: float) -> dict:
    """Chashu portions to prep given the forecast range (P10/P50/P90 orders) and chashu portions per order."""
    return clean(plan.newsvendor_par(p10, p50, p90, portions_per_order))


def query_metric(metric: str, start: str, end: str, grain: str = "day", channel: str = "") -> list:
    """A metric (orders, net_sales, avg_ticket, cancellations, commission, labour_cost, ...) between two dates
    (YYYY-MM-DD, inclusive) at a grain (day, channel, hour, item, dow). channel: doordash, ubereats, grubhub,
    in_store or empty for all."""
    df = _s().query_metric(metric, start, end, grain, channel or None)
    return clean(df)


TOOLS = {f.__name__: f for f in (match_payouts, cash_variance, update_ledger, forecast_day, compare_day, explain_day,
                                 similar_days, newsvendor, query_metric)}


# ------------------------------------------------------------------ callbacks
def record_tool_result(tool, args, tool_context, tool_response):
    """ADK after_tool_callback: keep every tool result in session state (the guardrail's facts).
    Arguments are stored as a JSON string so numbers the model passed in never count as facts."""
    try:
        agent = getattr(tool_context, "agent_name", None) or "agent"
        key = f"tool:{agent}:{tool.name}"
        prev = tool_context.state.get(key) or []
        tool_context.state[key] = list(prev) + [{"args": json.dumps(args, default=str), "result": clean(tool_response)}]
    except Exception:  # noqa: BLE001 - bookkeeping must never break a tool call
        pass
    return None


def _agent(model, name: str, desc: str, instruction: str, tools: list, key: str) -> LlmAgent:
    return LlmAgent(name=name, model=model, description=desc, instruction=f"{instruction}\n\n{RULES}", tools=tools,
                    output_key=key, after_model_callback=after_model_callback, after_tool_callback=record_tool_result)


def build_close_graph(model=MODEL) -> SequentialAgent:
    """`model`: a model name (e.g. a Gemini model) or a google.adk BaseLlm instance."""
    head = "Tonight's close is for {date?}; tomorrow is {tomorrow?}. Pipeline facts: "
    booksA = _agent(model, "books", "Did we get paid right?",
                    head + "{facts_books?}\nCall match_payouts for each date in {payout_dates?} and cash_variance for "
                    "{date?}. In two or three sentences, name any short payout or cash gap and its evidence.",
                    [match_payouts, cash_variance], "books")
    stockA = _agent(model, "stock", "What do we have left?",
                    head + "{facts_stock?}\nCall update_ledger for {date?} and name ingredients whose usage is higher "
                    "than sales explain.", [update_ledger], "stock")
    demandA = _agent(model, "demand", "What's coming tomorrow?",
                     head + "{facts_demand?}\nCall forecast_day for {tomorrow?} and similar_days for {tomorrow?}. "
                     "State the range and why the similar days are similar.", [forecast_day, similar_days], "demand")
    analystA = _agent(model, "analyst", "How did today go?",
                      head + "{facts_analyst?}\nCall compare_day and explain_day for {date?}. Explain the biggest change "
                      "versus a usual weekday. Books said: {books?} Stock said: {stock?}",
                      [compare_day, explain_day, similar_days], "analyst")
    planA = _agent(model, "plan", "What should we do?",
                   head + "{facts_plan?}\nDemand said: {demand?}\nCall newsvendor with the forecast range and portions "
                   "per order from the facts, then explain the prep number, the safety-net time and staffing gaps.",
                   [newsvendor], "plan")
    reportA = _agent(model, "report", "Write it up.",
                     head + "{facts_summary?}\nWrite a three-sentence summary of tonight for the manager from: books "
                     "{books?}; analyst {analyst?}; plan {plan?}.", [], "report")
    sentinelA = _agent(model, "sentinel", "Who needs to know, and how fast?",
                       head + "{facts_findings?}\nIn one short paragraph, say which urgent findings go in tonight's text "
                       "and why (payout short over $75 recoverable, cash off over $20, run-out before the rush, failed "
                       "close). Do not send anything.", [], "alerts")
    guardA = _agent(model, "guard", "Protect tomorrow's service.",
                    head + "{facts_plan?}\nRestate the approved safety-net rule from the plan ({plan?}) in one sentence. "
                    "Do not execute it.", [], "guard")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return SequentialAgent(name="close_coordinator", sub_agents=[
            ParallelAgent(name="reconcile", sub_agents=[booksA, stockA, demandA]),
            SequentialAgent(name="understand", sub_agents=[analystA, planA]),
            ParallelAgent(name="communicate", sub_agents=[reportA, sentinelA]),
            guardA,
        ])


def build_ask_agent(model=MODEL) -> LlmAgent:
    return LlmAgent(name="ask", model=model, description="Anything about the last 365 days",
                    instruction="Today is {today?}. Answer questions about the store using tools only (query_metric for "
                                "any metric over dates; compare_day / explain_day for one day; forecast_day for "
                                "tomorrow). Say which dates and metrics you used. " + RULES,
                    tools=[query_metric, compare_day, explain_day, similar_days, forecast_day],
                    output_key="answer", after_model_callback=after_model_callback, after_tool_callback=record_tool_result)


# ------------------------------------------------------------------ model selection
def configured_model(require_mode: bool = True):
    """The model agent mode should use, or None (offline).
    GONDOLA_AGENTS=adk turns agent mode on (unless require_mode=False). Then: GOOGLE_API_KEY (or Vertex settings)
    -> GONDOLA_MODEL (Gemini); else ANTHROPIC_API_KEY with the `anthropic` package -> Claude via ADK's AnthropicLlm."""
    from ..config import get_settings
    s = get_settings()
    if require_mode and os.getenv("GONDOLA_AGENTS", "").strip().lower() != "adk":
        return None
    if s.google_api_key or os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true"):
        if s.google_api_key:
            os.environ.setdefault("GOOGLE_API_KEY", s.google_api_key)
        return s.gondola_model
    if s.anthropic_api_key:
        try:
            from google.adk.models.anthropic_llm import AnthropicLlm
            import anthropic  # noqa: F401  (optional dependency)
            os.environ.setdefault("ANTHROPIC_API_KEY", s.anthropic_api_key)
            return AnthropicLlm(model=s.gondola_anthropic_model)
        except Exception:  # noqa: BLE001
            return None
    return None


def model_name(model) -> str | None:
    if model is None:
        return None
    return model if isinstance(model, str) else getattr(model, "model", type(model).__name__)


# ------------------------------------------------------------------ running
def run_coro(coro):
    """Run a coroutine from sync code, even if this thread already has a running loop (then use a helper thread)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def target():
        try:
            box["v"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=target, daemon=True)
    t.start(); t.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


async def run_agent(agent, state: dict, message: str, on_event=None) -> dict:
    """Run any ADK agent once with Runner + InMemorySessionService. Returns final texts, the agents that
    spoke, the tool calls they made, guardrail blocks and the final session state."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    svc = InMemorySessionService()
    runner = Runner(app_name=APP, agent=agent, session_service=svc)
    sid = uuid.uuid4().hex
    await svc.create_session(app_name=APP, user_id="manager", session_id=sid, state=clean(state))
    invoked: list[str] = []
    tool_calls: list[dict] = []
    finals: dict[str, str] = {}
    async for ev in runner.run_async(user_id="manager", session_id=sid,
                                     new_message=types.Content(role="user", parts=[types.Part(text=message)])):
        who = ev.author
        if who and who != "user" and who not in invoked:
            invoked.append(who)
            if on_event:
                on_event("agent", {"agent": who, "status": "running"})
        for fc in ev.get_function_calls() or []:
            tool_calls.append({"agent": who, "tool": fc.name, "args": dict(fc.args or {})})
        if ev.is_final_response() and ev.content and ev.content.parts:
            txt = "".join(p.text or "" for p in ev.content.parts if not getattr(p, "thought", False)).strip()
            if txt:
                finals[who] = txt
                if on_event:
                    on_event("agent", {"agent": who, "status": "done"})
    sess = await svc.get_session(app_name=APP, user_id="manager", session_id=sid)
    st = dict(sess.state) if sess else {}
    blocked = {k.split(":", 1)[1]: v for k, v in st.items() if k.startswith("guardrail:")}
    return {"finals": finals, "invoked": invoked, "tool_calls": tool_calls, "guardrail_blocked": blocked, "state": st}


def close_facts(res: dict, date: str) -> dict:
    """Session-state seed for the close graph: the deterministic pipeline's numbers, compact."""
    import pandas as pd
    b, s, fc, p, a = res.get("books") or {}, res.get("stock") or {}, res.get("demand") or {}, res.get("plan") or {}, res.get("analyst") or {}
    tomorrow = str((pd.Timestamp(date) + pd.Timedelta(days=1)).date())
    payouts = [{"date": v["date"], **{k: c.get(k) for k in ("channel", "sales", "expected", "reported", "difference")}}
               for v in b.get("verified", []) for c in v.get("channels", [])]
    findings = [{k: f.get(k) for k in ("kind", "title", "urgency", "impact_usd", "recoverable_usd", "channel_name", "time", "par")
                 if f.get(k) is not None} for f in res.get("findings", [])]
    return clean({
        "date": date, "tomorrow": tomorrow,
        "payout_dates": sorted({v["date"] for v in b.get("verified", [])}),
        "facts_books": {"cash": b.get("cash"), "money": b.get("money"), "payouts": payouts},
        "facts_stock": {"findings": (s.get("ledger") or {}).get("findings", []), "chashu": s.get("chashu")},
        "facts_demand": {k: fc.get(k) for k in ("date", "p10", "p50", "p90", "rush")} | {
            "similar_days": [{k: d.get(k) for k in ("date", "orders", "why")} for d in fc.get("similar_days", [])[:5]]},
        "facts_analyst": {"compare": a.get("compare"), "context": (a.get("explain") or {}).get("context")},
        "facts_plan": {"portions_per_order": p.get("portions_per_order"), "par": (p.get("newsvendor") or {}).get("chashu_portions"),
                       "newsvendor": p.get("newsvendor"), "old_par": p.get("old_par"), "safety_net": p.get("safety_net"),
                       "staff_gaps": p.get("staff_gaps"), "card": p.get("card")},
        "facts_findings": findings,
        "facts_summary": {"older_recoverable_usd": res.get("older_recoverable_usd"), "cancel_rate": res.get("cancel_rate")},
    })


def run_close_graph(res: dict, date: str, model=None, db=None, on_event=None) -> dict:
    """Run the close graph over the pipeline's results. Returns {mode, model, outputs:{output_key: text}, invoked,
    tool_calls, guardrail_blocked}. Raises on model/provider errors (the caller fails soft)."""
    model = model if model is not None else configured_model()
    if model is None:
        raise RuntimeError("agent mode needs GONDOLA_AGENTS=adk and a model key")
    fc = res.get("demand") or {}
    set_context(db=db or res.get("db"), forecasts={fc["date"]: fc} if fc.get("date") else None)
    graph = build_close_graph(model)
    facts = close_facts(res, date)
    out = run_coro(run_agent(graph, facts, f"Run tonight's close explanations for {date}.", on_event))
    keys = {"books": "books", "stock": "stock", "demand": "demand", "analyst": "analyst", "plan": "plan",
            "report": "report", "sentinel": "alerts", "guard": "guard"}
    outputs = {k: out["state"].get(v) for k, v in keys.items() if isinstance(out["state"].get(v), str)}
    return {"mode": "adk", "model": model_name(model), "outputs": outputs, "invoked": out["invoked"],
            "tool_calls": out["tool_calls"], "guardrail_blocked": out["guardrail_blocked"],
            "facts": {k: v for k, v in out["state"].items() if k.startswith("tool:")}}


def run_ask(question: str, model, today: str | None = None, db=None) -> dict:
    """Run the Ask agent once. Returns {text, blocked, tool_calls, invoked}."""
    set_context(db=db)
    if today is None:
        today = str(_s().last_date().date())
    out = run_coro(run_agent(build_ask_agent(model), {"today": today}, question))
    return {"text": out["state"].get("answer") or out["finals"].get("ask"), "blocked": bool(out["guardrail_blocked"]),
            "tool_calls": out["tool_calls"], "invoked": out["invoked"]}
