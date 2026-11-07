"""Shared ADK plumbing for the Exceptions and Review agents.

Agent mode only when `agents.adk_graph.configured_model()` returns a model (GONDOLA_AGENTS=adk plus a key) or a model
is passed in (tests pass a fake BaseLlm). Tool results land in session state (the close graph's after_tool_callback); the
callers re-check every item's numbers against those results with agents.guardrails.check_numbers.
"""
from __future__ import annotations

import json
import re
import warnings

from ..agents import adk_graph
from ..agents.guardrails import after_model_callback


def configured_model():
    try:
        return adk_graph.configured_model()
    except Exception:  # noqa: BLE001
        return None


def build_agent(model, name: str, instruction: str, tools: list, output_key: str, whole_reply_guard: bool = False):
    """These agents answer in structured JSON, so their numbers are checked per item after the run (an item with an
    unsupported number is dropped and the rest kept). whole_reply_guard=True also attaches the close graph's
    after_model_callback, which replaces the entire reply when any number is unsupported."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from google.adk.agents import LlmAgent
    return LlmAgent(name=name, model=model, description=name, instruction=f"{instruction}\n\n{adk_graph.RULES}",
                    tools=tools, output_key=output_key, after_model_callback=after_model_callback if whole_reply_guard else None,
                    after_tool_callback=adk_graph.record_tool_result)


def run(agent, state: dict, message: str, max_llm_calls: int = 12) -> dict:
    return adk_graph.run_coro(adk_graph.run_agent(agent, state, message, max_llm_calls=max_llm_calls))


def parse_json(text: str | None):
    """The first JSON object/array in a model reply (fenced or bare), or None."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for open_, close in (("{", "}"), ("[", "]")):
        i, j = t.find(open_), t.rfind(close)
        if i != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except ValueError:
                continue
    return None


def tool_facts(state: dict) -> list:
    """Tool results the agent saw (for re-checking its numbers after the run)."""
    return [v for k, v in state.items() if str(k).startswith("tool:")]
