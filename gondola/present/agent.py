"""The Rush agent: Savvy's intervention agent (gondola/rush/agents.py) generalized to the live Present service.

Called only on triggers (design section 3.5): headroom predicted below -10% within 20 minutes, an incident, a cluster
of courier delays, or a guard conflict (pricing promotes on the station the ladder is protecting). The controller
handles routine minutes without a model.

Tools: get_state, get_queue, simulate(action), apply(action), explain(order_id). It may only choose ladder actions
(quote / pause_item / busy / resume on delivery apps; never dine-in or pickup) or approved offers; Savvy's guard has
the final word on offers. Context is built by code within ~3k tokens (state, queue head, last 15 minutes, the current
shift log, up to 5 knowledge items from gondola.kb.retrieve). With ADK + Gemini configured (GOOGLE_API_KEY and
GONDOLA_AGENTS=adk) a real model chooses; otherwise a deterministic offline policy produces the same structured
output. Every run leaves a receipt (receipts.py, SQLite).
"""
from __future__ import annotations

import json
from datetime import datetime

from . import admission as adm
from .world import DELIVERY_APPS, MENU, hm

# Declared cost used to compare candidate actions: one turned-away order ~ 12 late minutes. An assumption, not a
# measured business cost (same spirit as Savvy's declared service score).
LOST_ORDER_MIN = 12.0
QUOTE_MIN_COST = 0.5   # each minute a customer is quoted longer counts half a late minute (also an assumption)
MIN_GAIN = 5.0
ALLOWED = ("quote", "pause_item", "busy", "resume", "pause_offer", "offer", "none")


def candidates(e, m: int) -> list[dict]:
    h = e.head
    bind = h.binding if h and h.binding in ("noodles", "fryer", "assembly") else "fryer"
    slow = adm.slow_items(bind, e.w.durations)
    cheap = adm.cheapest_first(e.w.contribution)[0]
    out = [{"action": "none", "reason": "keep the ladder's current plan"},
           {"action": "quote", "channel": "delivery", "value": 10, "reason": "quote +10 min on all delivery apps"},
           {"action": "pause_item", "channel": "grubhub", "items": slow,
            "reason": f"pause slow {bind} items on Grubhub first (slowest pause)"},
           {"action": "pause_item", "channel": "delivery", "items": slow,
            "reason": f"pause slow {bind} items on all delivery apps"},
           {"action": "busy", "channel": cheap, "reason": f"busy mode on {cheap} (cheapest contribution)"}]
    if e.offer:
        out.append({"action": "pause_offer", "reason": "stop the promotion on a congested kitchen"})
    return out


def _cost(p: dict) -> float:
    return p["late_minutes"] + LOST_ORDER_MIN * p["lost_orders"] + QUOTE_MIN_COST * p.get("quoted_minutes", 0)


def offline_decide(e, m: int, triggers: list[str]) -> dict:
    """Deterministic policy: simulate each bounded candidate on a projection (no future truth) and apply the one with
    the lowest declared cost if it beats doing nothing by MIN_GAIN late-minute equivalents."""
    from .service import project
    if any(t.startswith("guard conflict") for t in triggers) and e.offer:
        act = {"action": "pause_offer", "reason": "guard conflict: " + next(t for t in triggers if t.startswith("guard"))}
        return {"summary": "Stop the promotion: it sells the bottleneck station.", "action": act, "candidates": []}
    rows = []
    for c in candidates(e, m):
        if c["action"] == "pause_offer":
            continue
        p = project(e, c)
        rows.append({"action": c, "projected": p, "cost": round(_cost(p), 1)})
    base = rows[0]
    best = min(rows, key=lambda r: (r["cost"], rows.index(r)))
    if best is base or base["cost"] - best["cost"] < MIN_GAIN:
        return {"summary": f"Monitor: no candidate beats the current plan by {MIN_GAIN:.0f}+ late-minute equivalents "
                           f"(projected {base['projected']['late_orders']} late).",
                "action": {"action": "none", "reason": "monitor"}, "candidates": _brief(rows)}
    a = dict(best["action"])
    a["reason"] = (f"{a['reason']}: projected late {base['projected']['late_orders']}->{best['projected']['late_orders']} "
                   f"orders, {best['projected']['lost_orders']} turned away (trigger: {triggers[0]})")
    return {"summary": a["reason"], "action": a, "candidates": _brief(rows)}


def _brief(rows):
    return [{"action": r["action"]["action"], "channel": r["action"].get("channel"), "cost": r["cost"],
             "late_orders": r["projected"]["late_orders"], "lost_orders": r["projected"]["lost_orders"]} for r in rows]


# ------------------------------------------------------------------ context (~3k tokens, built by code)
def tokens(obj) -> int:
    return len(json.dumps(obj, default=str)) // 4


def context(e, m: int, triggers: list[str], budget: int = 3000) -> dict:
    h = e.head
    queue = [{k: q.get(k) for k in ("rank", "order_id", "channel", "items", "due", "slack_min", "station", "status", "reason")}
             for q in e.view()["queue"][:8]]
    recent = [{"time": a["time"], **{k: a.get(k) for k in ("action", "channel", "item", "value", "reason", "by")}}
              for a in e.actions if a["minute"] >= m - 15][-10:]
    recent += [{"time": hm(i["minute"]), "incident": i["text"]} for i in e.incident_log if i["minute"] >= m - 15]
    shift = []
    try:
        from ..review.digests import shift_log  # type: ignore
        shift = shift_log(e.d, max(11, m // 60))["bullets"]
    except Exception:
        shift = [f"{a['time']} {a.get('action')} {a.get('channel') or ''} {a.get('item') or ''}".strip()
                 for a in e.actions if a["minute"] >= (m // 60) * 60][-5:]
    kb_items = []
    try:
        from ..kb import retrieve  # type: ignore
        bind = h.binding if h else None
        scope = {"weekday": datetime.fromisoformat(e.d).strftime("%a"), "daypart": "dinner" if m >= 16 * 60 else "lunch",
                 "station": bind, "items": adm.slow_items(bind, e.w.durations) if bind in ("noodles", "fryer", "assembly") else []}
        try:
            kb_items = retrieve(scope, ["capacity", "pricing", "ops_rule"], 5, 600, as_of=e.d)
        except TypeError:
            kb_items = retrieve(scope, ["capacity", "pricing", "ops_rule"], 5, 600)
    except Exception:
        kb_items = []
    payload = {"store": "Hanabi Ramen (synthetic demo world)", "date": e.d, "now": hm(m), "triggers": triggers,
               "ladder": {"level": adm.LEVELS[e.ladder.level], "since": hm(e.ladder.since)},
               "headroom": h.to_dict() if h else None, "channels": e.channel_view(), "weather": e.weather(m),
               "cooks": e.cooks_at(m), "station_speed": dict(e.speeds), "queue_head": queue, "last_15_min": recent,
               "shift_log": shift[:5], "knowledge": kb_items,
               "allowed_actions": {"quote": "channel in doordash|ubereats|grubhub|delivery, value 5-20 min",
                                   "pause_item": "channel as above, item: kitchen menu item",
                                   "busy": "channel as above", "resume": "channel as above",
                                   "pause_offer": "stop the current promotion",
                                   "offer": "item in tonkotsu|karaage|gyoza|don, value = discount cents 0-200 (guard decides)"}}
    dropped = []
    while tokens(payload) > budget and payload["queue_head"]:
        payload["queue_head"].pop()
        dropped.append("queue_head")
    while tokens(payload) > budget and payload["last_15_min"]:
        payload["last_15_min"].pop(0)
        dropped.append("last_15_min")
    while tokens(payload) > budget and payload["knowledge"]:
        payload["knowledge"].pop()
        dropped.append("knowledge")
    return {"payload": payload, "tokens": tokens(payload), "budget_tokens": budget, "dropped": sorted(set(dropped))}


# ------------------------------------------------------------------ validation of a proposed action
def validate(e, m: int, a: dict) -> dict:
    """Bounded and guarded: returns {ok, reason, action} without changing the live engine."""
    kind = a.get("action")
    if kind not in ALLOWED:
        return {"ok": False, "reason": f"'{kind}' is not a ladder action or approved offer"}
    ch = a.get("channel")
    if kind in ("quote", "pause_item", "busy", "resume"):
        if ch not in DELIVERY_APPS and ch not in ("delivery", "all"):
            return {"ok": False, "reason": "only delivery apps can be throttled; never dine-in or pickup"}
    if kind == "quote" and not 5 <= int(a.get("value") or 0) <= 20:
        return {"ok": False, "reason": "quote must be 5-20 minutes"}
    if kind == "pause_item":
        items = a.get("items") or [i.strip() for i in str(a.get("item") or "").split(",") if i.strip()]
        if not items or any(i not in MENU or not MENU[i]["station"] for i in items):
            return {"ok": False, "reason": "unknown or non-kitchen item"}
    if kind == "offer":
        from . import capacity as cap
        if e.ladder.level < 1:
            return {"ok": False, "reason": "the ladder is not at promote: no offers while headroom is low"}
        key = a.get("item")
        if key not in cap.RUSH_TO_ITEM:
            return {"ok": False, "reason": "not an approved offer item"}
        check = cap.guard_offer(e.kitchen(m), key, int(a.get("value") or 0), e.s.kitchen.slots)
        if not check["allowed"]:
            return {"ok": False, "reason": "guard: " + check["reason"], "evidence": check}
        return {"ok": True, "reason": check["reason"], "evidence": check}
    return {"ok": True, "reason": "bounded ladder action"}


def expand(a: dict) -> list[dict]:
    """channel 'delivery'/'all' -> one action per delivery app."""
    if a.get("channel") in ("delivery", "all") and a.get("action") in ("quote", "pause_item", "busy", "resume"):
        return [{**a, "channel": app} for app in DELIVERY_APPS]
    return [a]


# ------------------------------------------------------------------ one agent run (API: POST /api/present/agent)
async def run(d: str, now: datetime | None = None, at: str | None = None, progress=None) -> dict:
    from . import receipts, service
    minute, phase = service._phase_minute(d, now, at)
    base = service.engine(d, minute)
    e = base.fork()
    m = e.t
    trig = e.triggers(m) + [f"handoff from Review: {h['title']}" for h in service.handoffs(d, e.ts(m))]
    trig = trig or ["manual request"]
    ctx = context(e, m, trig)
    trace: list[dict] = []
    applied: list[dict] = []
    live = phase == "open"

    def record(tool, args, result):
        if len(trace) >= 14:
            raise ValueError("Tool budget exhausted")
        trace.append({"tool": tool, "args": args, "result": result})
        if progress:
            progress({"kind": "tool", "tool": tool, "args": args, "result": result})
        return result

    def get_state() -> dict:
        """Current Present state: ladder, headroom per resource, channel states, weather, station speeds, cooks."""
        p = ctx["payload"]
        return record("get_state", {}, {k: p[k] for k in ("now", "ladder", "headroom", "channels", "weather", "cooks", "station_speed")})

    def get_queue(n: int = 8) -> dict:
        """The top n orders of the one queue with due time, slack and the reason for their rank."""
        q = e.view()["queue"][:max(1, min(20, int(n)))]
        return record("get_queue", {"n": n}, {"queue": [{k: x.get(k) for k in ("rank", "order_id", "channel", "items", "due",
                                                                                "slack_min", "status", "reason")} for x in q]})

    def simulate(action: str, channel: str = "", item: str = "", value: int = 0) -> dict:
        """Project the next 30 minutes with a candidate action (no future truth). action: quote|pause_item|busy|resume|none."""
        a = {"action": action, "channel": channel or None, "item": item or None, "value": value}
        v = validate(e, m, a)
        if not v["ok"]:
            return record("simulate", a, {"status": "rejected", "reason": v["reason"]})
        return record("simulate", a, {"before": service.project(e, None), "after": service.project(e, a)})

    def apply(action: str, channel: str = "", item: str = "", value: int = 0, reason: str = "") -> dict:
        """Apply one bounded action (ladder actions on delivery apps, or an approved offer the guard allows)."""
        a = {"action": action, "channel": channel or None, "item": item or None, "value": value, "reason": reason or "rush agent"}
        if applied:
            return record("apply", a, {"status": "rejected", "reason": "one applied intervention per agent run"})
        v = validate(e, m, a)
        if not v["ok"]:
            return record("apply", a, {"status": "rejected", "reason": v["reason"]})
        applied.append(a)
        return record("apply", a, {"status": "applied" if live else "recorded",
                                   "note": None if live else "day is not open: decision recorded, not applied"})

    def explain(order_id: str) -> dict:
        """Why an order holds its rank: due time, slack and each factor's contribution in minutes."""
        q = next((x for x in e.view()["queue"] if x["order_id"] == order_id), None)
        return record("explain", {"order_id": order_id}, q or {"error": "not in the current queue"})

    from ..agents.adk_graph import configured_model
    model = configured_model()
    if model is not None:
        from ..rush.agents import _run
        meta = await _run("rush_agent", "You are the Rush agent for a restaurant kitchen (synthetic demo world). You were called "
                          "because of the triggers in the context. Inspect state and queue, simulate at most three candidate "
                          "actions, then apply exactly one bounded action or 'none'. You may only use ladder actions on "
                          "delivery apps (quote, pause_item, busy, resume) or an approved offer; never throttle dine-in or "
                          "pickup. Accepted promises never move. A tool rejection is not success. Quote numbers only from "
                          "tool results. Keep your final explanation to two sentences.",
                          [get_state, get_queue, simulate, apply, explain], progress or (lambda ev: None),
                          "Context:\n" + json.dumps(ctx["payload"], default=str))
        mode = "live_model"
        summary = f"model chose: {applied[0]['action'] if applied else 'no action'}"
    else:
        dec = offline_decide(e, m, trig)
        get_state()
        get_queue(5)
        for c in (dec.get("candidates") or [])[:3]:
            trace.append({"tool": "simulate", "args": {"action": c["action"], "channel": c["channel"]}, "result": c})
        act = dec["action"]
        if act.get("action") != "none":
            apply(act["action"], act.get("channel") or "", act.get("item") or ", ".join(act.get("items") or []),
                  int(act.get("value") or 0), act.get("reason") or "")
        meta = {"model": None, "tool_calls": [{"tool": t["tool"], "args": t["args"]} for t in trace], "usage": []}
        mode = "offline_policy"
        summary = dec["summary"]
    actions = []
    status = "no_action"
    if applied:
        status = "applied" if live else "recorded"
        for a in expand(applied[0]):
            actions.append(a)
    payload = {"date": d, "minute": m, "time": hm(m), "phase": phase, "agent_mode": mode, "triggers": trig,
               "context_tokens": ctx["tokens"], "context_dropped": ctx["dropped"], "trace": trace,
               "model": meta.get("model"), "usage": meta.get("usage"), "decision": summary, "actions": actions,
               "data_mode": "synthetic", "write_mode": "simulation"}
    rid = receipts.save(d, m, "rush_agent", status, payload)
    if live and actions:
        for a in actions:
            receipts.add_override(d, m, a, "rush-agent", rid)
        service.invalidate(d)
    return {"decision": summary, "actions": actions, "status": status,
            "receipt": {"id": rid, "time": hm(m), "agent_mode": mode, "triggers": trig, "context_tokens": ctx["tokens"],
                        "trace": trace, "model": meta.get("model")}}
