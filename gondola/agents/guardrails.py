"""Guardrail: every number an agent writes must come from a tool output.

Facts are the numeric fields of tool results (dates, IDs and free text are excluded). A number in the text
passes only if some fact, rounded to the precision the text uses, equals it. Percentages may match a
fraction (0.091 -> 9.1%) or a percent. "$15k" matches a fact that rounds to 15 thousand.

Used in two places: the close pipeline checks every summary and SMS before it is sent, and the ADK agents
get `after_model_callback`, which replaces a reply containing unsupported numbers with a safe fallback.
"""
from __future__ import annotations

import re
from datetime import date, datetime

TOKEN = re.compile(r"(?<![\w.:/-])(-|\+)?\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%|k\b)?")
SKIP_KEYS = re.compile(r"(id|date|_at|key|time|order|shift|evidence|uri|url|bin)$", re.I)
SMALL_INTS = set(range(0, 11))  # bare counts like "3 things", "2 cooks" are allowed


def facts_from(obj, out: list | None = None, key: str = "") -> list[float]:
    out = [] if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        if not SKIP_KEYS.search(key or "") and obj == obj:
            out.append(float(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            facts_from(v, out, str(k))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            facts_from(v, out, key)
    elif hasattr(obj, "to_dict"):
        facts_from(obj.to_dict("records") if hasattr(obj, "columns") else obj.to_dict(), out, key)
    return out


def _matches(v: float, decimals: int, kind: str, facts: list[float]) -> bool:
    for a in facts:
        cands = [a]
        if kind == "%":
            cands = [a * 100, a]
        if kind == "k":
            cands = [a / 1000]
        for c in cands:
            if round(abs(c), decimals) == round(v, decimals):
                return True
    return False


def check_numbers(text: str, tool_outputs: list) -> dict:
    facts = []
    for o in tool_outputs:
        facts_from(o, facts)
    # derived differences the templates may state (e.g. "$1,556 below usual") must be passed in as facts explicitly
    bad = []
    for m in TOKEN.finditer(text):
        sign, whole, frac, unit = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
        raw = m.group(0)
        v = float(whole.replace(",", "") + frac)
        decimals = len(frac) - 1 if frac else 0
        is_money = "$" in raw
        if not is_money and not unit and decimals == 0 and v in SMALL_INTS:
            continue
        if re.match(r"\d{1,2}:\d\d", text[m.start():m.start() + 5]):
            continue  # clock time
        if not _matches(v, decimals, unit.strip(), facts):
            bad.append(raw.strip())
    return {"ok": not bad, "unsupported": bad}


def enforce(text: str, tool_outputs: list, fallback: str) -> tuple[str, dict]:
    r = check_numbers(text, tool_outputs)
    return (text if r["ok"] else fallback), r


def after_model_callback(callback_context, llm_response):
    """ADK hook: block a model reply whose numbers aren't in this session's tool results."""
    try:
        parts = llm_response.content.parts if llm_response and llm_response.content else []
        text = " ".join(p.text for p in parts if getattr(p, "text", None))
        if not text:
            return None
        outputs = [v for v in callback_context.state.to_dict().values()]
        r = check_numbers(text, outputs)
        if r["ok"]:
            return None
        from google.genai import types
        msg = "I couldn't verify every number in that answer, so here is what the tools returned: " + \
              ", ".join(f"{k}" for k in callback_context.state.to_dict().keys())
        return type(llm_response)(content=types.Content(role="model", parts=[types.Part(text=msg)]))
    except Exception:
        return None
