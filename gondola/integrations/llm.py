"""LLM wording, behind the number guardrail.

phrase(): the model may only rephrase a template sentence for a busy manager. Every number it writes is checked
against the facts (agents.guardrails); if anything fails, or no key is set, or the call errors, the template is used.
ask_llm(): runs the ADK Ask agent (agents.adk_graph) when a model is configured; returns None otherwise, or when
the guardrail blocked the reply, so callers fall back to the offline router.
All provider imports are lazy, so a missing package never breaks the close.
"""
from __future__ import annotations

import requests

from ..agents.guardrails import check_numbers
from ..config import Settings, get_settings

SYSTEM = ("You rewrite short restaurant operations messages for a busy manager reading at 11 pm. "
          "Keep it under 60 words, plain and direct. Do not add, remove, round or change any number, time, "
          "money amount or percentage. Do not add facts. Return only the rewritten text.")


def _gemini(s: Settings, prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=s.google_api_key)
    r = client.models.generate_content(model=s.gondola_model, contents=prompt,
                                       config={"system_instruction": SYSTEM, "temperature": 0.2})
    return (r.text or "").strip()


def _anthropic(s: Settings, prompt: str) -> str:
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=20,
                      headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": s.gondola_anthropic_model, "max_tokens": 300, "system": SYSTEM,
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()


def complete(prompt: str, s: Settings | None = None) -> str | None:
    """Raw model call; None when no provider is configured."""
    s = s or get_settings()
    if s.llm_provider == "gemini":
        return _gemini(s, prompt)
    if s.llm_provider == "anthropic":
        return _anthropic(s, prompt)
    return None


def phrase(summary_facts: dict, template_text: str, s: Settings | None = None) -> str:
    """Rephrase `template_text`; fall back to it unless every number is traceable to `summary_facts`."""
    try:
        out = complete(f"Facts (JSON): {summary_facts}\n\nRewrite this message:\n{template_text}", s)
    except Exception:  # noqa: BLE001 - provider errors never block a message
        return template_text
    if not out:
        return template_text
    if not check_numbers(out, [summary_facts])["ok"]:
        return template_text
    if not check_numbers(template_text, [summary_facts])["ok"]:
        return template_text  # facts don't cover the template: don't risk a rewrite
    return out


def ask_llm(question: str, store=None, s: Settings | None = None, model=None, today: str | None = None,
            require_mode: bool = False) -> str | None:
    """Answer with the ADK Ask agent. `model`: a model name or BaseLlm (tests pass a fake); default: Gemini when
    GOOGLE_API_KEY is set (or Claude via ADK with ANTHROPIC_API_KEY + the anthropic package).
    Returns None when no model is configured, the guardrail blocked the reply, or anything fails (the caller then
    uses the offline router)."""
    from ..agents import adk_graph
    if model is None:
        s = s or get_settings()
        if not (s.google_api_key or s.anthropic_api_key):
            return None
        model = adk_graph.configured_model(require_mode=require_mode)
        if model is None:
            return None
    try:
        db = getattr(store, "db_path", None)
        out = adk_graph.run_ask(question, model, today=today, db=db)
    except Exception:  # noqa: BLE001
        return None
    if out["blocked"] or not out["text"]:
        return None
    return out["text"]
