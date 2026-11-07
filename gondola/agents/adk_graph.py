"""The agent graph in Google ADK.

Close Coordinator = SequentialAgent:
  1. Reconcile (ParallelAgent): Books, Stock, Demand
  2. Understand and prepare (Sequential): Analyst, Plan
  3. Communicate (ParallelAgent): Report, Sentinel
  4. Protect: Guard
Ask runs on its own, outside the close.

Each specialist is an LlmAgent whose tools are the plain Python functions in gondola/tools. Building the
graph needs no API key (tests do this). Running it needs GOOGLE_API_KEY (or Vertex settings) and
GONDOLA_MODEL set to a current model; the offline pipeline in gondola/pipeline.py runs the same steps
without an LLM.
"""
from __future__ import annotations

import os

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from ..metrics import Store
from .guardrails import after_model_callback
from ..tools import analyst, books, demand, plan, stock

MODEL = os.getenv("GONDOLA_MODEL", "gemini-flash-latest")
RULES = ("Rules: every number you write must come from a tool result; never estimate. "
         "You propose, code acts: never claim an action happened unless a tool returned status ok. "
         "Write for a busy restaurant manager: short, plain sentences.")

_store: Store | None = None


def _s() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


# --- tool wrappers with simple typed signatures (ADK reads the signature + docstring) --------------
def match_payouts(date: str) -> dict:
    """Reconcile delivery-app payouts for a business date (YYYY-MM-DD) against POS orders and contract rates."""
    return books.match_payouts(_s(), date)


def cash_variance(date: str) -> dict:
    """Compare the cash drawer's expected and counted cash for a business date."""
    return books.cash_variance(_s(), date)


def update_ledger(date: str) -> dict:
    """Roll the ingredient ledger forward to a count date and report gaps against the count."""
    return stock.update_ledger(_s(), date)


def forecast_day(date: str) -> dict:
    """Forecast orders for a date: P10/P50/P90, 15-minute curve, item demand and similar past days."""
    return demand.run_forecast(_s(), date)


def compare_day(date: str) -> dict:
    """Compare a day with the average of the last 4 same weekdays."""
    return analyst.compare_periods(_s(), date)


def explain_day(date: str) -> dict:
    """Break a day's change into channels and dayparts, with weather and events."""
    return analyst.explain_change(_s(), date)


def similar_days(date: str) -> list:
    """Past days most like the given date (weekday, weather, events, school, promos)."""
    return analyst.find_similar_days(_s(), date)


def newsvendor(p10: float, p50: float, p90: float, portions_per_order: float) -> dict:
    """Chashu portions to prep given the forecast range."""
    return plan.newsvendor_par(p10, p50, p90, portions_per_order)


def build_close_graph(model: str = MODEL) -> SequentialAgent:
    mk = lambda name, desc, instr, tools, key: LlmAgent(name=name, model=model, description=desc,
                                                       instruction=f"{instr} {RULES}", tools=tools, output_key=key,
                                                       after_model_callback=after_model_callback)
    booksA = mk("books", "Did we get paid right?", "Reconcile tonight's money: call match_payouts for every date whose payout "
                "report arrived and cash_variance for today. List short payouts with evidence.", [match_payouts, cash_variance], "books")
    stockA = mk("stock", "What do we have left?", "Update the ledger and report ingredients whose usage is higher than sales explain.",
                [update_ledger], "stock")
    demandA = mk("demand", "What's coming tomorrow?", "Forecast tomorrow and name the similar past days.", [forecast_day, similar_days], "demand")
    analystA = mk("analyst", "How did today go?", "Compare today with a usual weekday and explain the biggest change. "
                  "Use {books} and {stock}.", [compare_day, explain_day, similar_days], "analyst")
    planA = mk("plan", "What should we do?", "Turn {demand} and {stock} into prep, a safety-net time and staffing gaps.", [newsvendor], "plan")
    reportA = mk("report", "Write it up.", "Write a 3-sentence summary and a 'needs your attention' list from {books}, {analyst}, {plan}.", [], "report")
    sentinelA = mk("sentinel", "Who needs to know, and how fast?", "From {books}, {stock}, {plan}, pick findings for SMS now "
                   "(payout short > $50, cash off > $20, run-out before the rush, failed close). Return them as a list.", [], "alerts")
    guardA = mk("guard", "Protect tomorrow's service.", "Restate the approved safety-net rule from {plan}. Do not execute it.", [], "guard")
    return SequentialAgent(name="close_coordinator", sub_agents=[
        ParallelAgent(name="reconcile", sub_agents=[booksA, stockA, demandA]),
        SequentialAgent(name="understand", sub_agents=[analystA, planA]),
        ParallelAgent(name="communicate", sub_agents=[reportA, sentinelA]),
        guardA,
    ])


def build_ask_agent(model: str = MODEL) -> LlmAgent:
    return LlmAgent(name="ask", model=model, description="Anything about the last 365 days",
                    instruction="Answer questions about the store using tools only. Say which dates and metrics you used. " + RULES,
                    tools=[compare_day, explain_day, similar_days, forecast_day], after_model_callback=after_model_callback)
