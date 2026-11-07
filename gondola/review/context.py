"""What each agent gets, and when (design section 6.4). Code decides what enters a prompt; budgets are hard caps.

    rush        live state + last 15 min of events + current hour's shift log + <= 5 capacity/pricing/ops_rule items  ~3000
    outlook     today's/tomorrow's calendar + <= 8 event_effect items + yesterday's forecast error                   ~2000
    exceptions  the triggering events + related orders + <= 3 ops_rule items                                       ~2000
    review      today's day-digest inputs + last 7 day digests' "went wrong" + open action items + <= 10 KB items  ~6000

When a payload is over budget, whole pieces are dropped lowest-ranked first (oldest digests, last KB items, older
events), never cut mid-item. `build(agent, date)` returns {agent, date, budget_tokens, tokens, payload, dropped}.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from ..kb import KB, compact_item, kb as _kb, tokens
from ..ledger import Ledger, ledger
from ..metrics import ROOT
from . import digests as D

DB = ROOT / "data" / "gondola.duckdb"
BUDGETS = {"rush": 3000, "outlook": 2000, "exceptions": 2000, "review": 6000}
KB_BUDGET = {"rush": 600, "outlook": 900, "exceptions": 300, "review": 1500}


def _fit(payload: dict, budget: int, droppers: list) -> tuple[dict, list]:
    """Apply droppers (each removes one whole piece and returns a label, or None when it has nothing left) until the
    payload fits."""
    dropped = []
    for drop in droppers:
        while tokens(payload) > budget:
            lab = drop(payload)
            if lab is None:
                break
            dropped.append(lab)
        if tokens(payload) <= budget:
            break
    return payload, dropped


def _pop(path: list[str], from_end: bool = True):
    def f(p):
        x = p
        for k in path[:-1]:
            x = x.get(k) or {}
        lst = x.get(path[-1])
        if not isinstance(lst, list) or not lst:
            return None
        lst.pop(-1 if from_end else 0)
        return ".".join(path)
    return f


def _del(path: list[str]):
    def f(p):
        x = p
        for k in path[:-1]:
            x = x.get(k) or {}
        if path[-1] in x:
            del x[path[-1]]
            return ".".join(path)
        return None
    return f


def day_scope(date: str, db=DB) -> dict:
    from ..kb import measures as M
    c = M.day_conditions(date, db)
    ev = [M.event_family_name(e) for e in c.get("events") or []]
    ev += [k for k in ("rain", "snow", "dd_promo", "cold") if c.get(k)]
    return {"weekday": c["weekday"], "event": ev or None}


def review_context(date: str, led: Ledger | None = None, kb: KB | None = None, dg: D.Digests | None = None, db=DB,
                   inputs: dict | None = None) -> dict:
    led, kb, dg = led or ledger(), kb or _kb(), dg or D.digests()
    inputs = inputs or D.day_inputs(date, led, db, dg=dg)
    recent = [{"date": d["period"], "wrong": d.get("wrong") or []} for d in dg.list("day", before=date, limit=7)]
    recent = [r for r in recent if r["wrong"]]
    open_actions = [compact_item(a) for a in kb.list("active", "action_item") if a.get("action_status") == "open"]
    scope = day_scope(date, db)
    scope["item"] = "chashu"
    items = kb.retrieve(scope, [k for k in ("event_effect", "item_behavior", "capacity", "pricing", "ops_rule")], 10,
                        KB_BUDGET["review"], as_of=date)
    payload = {"today": inputs, "recent_wrong": recent, "open_actions": open_actions, "kb": items}
    payload, dropped = _fit(payload, BUDGETS["review"], [_pop(["recent_wrong"]), _pop(["kb"]), _del(["today", "shift_log"]),
                                                         _pop(["open_actions"])])
    return {"agent": "review", "date": date, "budget_tokens": BUDGETS["review"], "tokens": tokens(payload),
            "payload": payload, "dropped": dropped}


def outlook_context(date: str, led: Ledger | None = None, kb: KB | None = None, db=DB) -> dict:
    from ..kb import measures as M
    led, kb = led or ledger(), kb or _kb()
    tom = str((pd.Timestamp(date) + pd.Timedelta(days=1)).date())
    cal = {date: M.day_conditions(date, db), tom: M.day_conditions(tom, db)}
    for v in cal.values():
        for k in ("par", "used", "sold_out", "open"):
            v.pop(k, None)
    scopes = [day_scope(date, db), day_scope(tom, db)]
    seen, items = set(), []
    for sc in scopes:
        for it in kb.retrieve(sc, ["event_effect"], 8, KB_BUDGET["outlook"], as_of=date):
            if it["id"] not in seen and len(items) < 8:
                seen.add(it["id"]); items.append(it)
    y = str((pd.Timestamp(date) - pd.Timedelta(days=1)).date())
    err = None
    fc = [e for e in led.query(y, ["forecast.issued"]) if e.payload.get("horizon") == "day"]
    if fc:
        from ..ledger.summary import summary
        act = summary(y, None, led)["processed"]
        p50 = (fc[-1].payload.get("total") or {}).get("p50")
        if p50 and act:
            err = {"date": y, "p50": p50, "actual": act, "error_pct": round((p50 - act) / act * 100, 1)}
    payload = {"calendar": cal, "kb": items, "yesterday_forecast_error": err}
    payload, dropped = _fit(payload, BUDGETS["outlook"], [_pop(["kb"])])
    return {"agent": "outlook", "date": date, "budget_tokens": BUDGETS["outlook"], "tokens": tokens(payload),
            "payload": payload, "dropped": dropped}


def _now_for(date: str, db=DB) -> datetime:
    from ..ledger.build import horizon
    h = horizon(date, db)
    return h or datetime.fromisoformat(date) + timedelta(hours=23, minutes=59)


def exceptions_context(date: str, led: Ledger | None = None, kb: KB | None = None, db=DB) -> dict:
    from .exceptions import raised
    led, kb = led or ledger(), kb or _kb()
    exc = [x for x in raised(date, led) if not x["resolved"]][-5:]
    related = []
    for x in exc:
        for oid in (x.get("evidence") or {}).get("order_ids", [])[:5]:
            for e in led.query(date, ["order.received"]):
                if e.payload.get("order_id") == oid:
                    related.append({"order_id": oid, "ts": e.ts[11:16], "channel": e.payload.get("channel"),
                                    "items": e.payload.get("items")})
                    break
    topics = [t for x in exc for t in list(((x.get("evidence") or {}).get("top_items") or {}))[:1]] or ["chashu"]
    rules = kb.retrieve({"item": topics[0]}, ["ops_rule"], 3, KB_BUDGET["exceptions"], as_of=date)
    payload = {"triggers": [{k: x.get(k) for k in ("id", "ts", "kind", "severity", "title", "evidence")} for x in exc],
               "related_orders": related[:15], "rules": rules}
    payload, dropped = _fit(payload, BUDGETS["exceptions"], [_pop(["related_orders"]), _pop(["triggers"], from_end=False)])
    return {"agent": "exceptions", "date": date, "budget_tokens": BUDGETS["exceptions"], "tokens": tokens(payload),
            "payload": payload, "dropped": dropped}


def rush_context(date: str, led: Ledger | None = None, kb: KB | None = None, db=DB) -> dict:
    led, kb = led or ledger(), kb or _kb()
    now = _now_for(date, db)
    state = None
    try:  # Present owns the live state; trimmed to what the Rush agent needs
        from ..present import service  # type: ignore
        s = service.state(date, now)
        state = {k: s.get(k) for k in ("now", "phase", "headroom_pct", "ladder", "channels", "weather")}
        state["queue_head"] = [{k: q.get(k) for k in ("rank", "order_id", "channel", "items", "due", "slack_min", "station", "status")}
                               for q in (s.get("queue") or [])[:8]]
        state["stations"] = [{k: st.get(k) for k in ("key", "speed", "busy_until")} for st in s.get("stations") or []]
    except Exception:  # noqa: BLE001 - Present not built yet / not running: the context says so
        state = {"unavailable": "gondola.present.service.state not available"}
    lo = (now - timedelta(minutes=15)).isoformat(timespec="seconds")
    evs = [{"ts": e.ts[11:19], "type": e.type, **{k: v for k, v in e.payload.items() if k in
                                                   ("order_id", "channel", "action", "item", "station", "reason", "late_min")}}
           for e in led.query(date, start_ts=lo, end_ts=now.isoformat(timespec="seconds"))
           if e.type not in ("order.accepted",)][-40:]
    shift = D.shift_log(date, max(11, now.hour), led) if now.hour >= 11 else None
    items = kb.retrieve({"weekday": pd.Timestamp(date).day_name()[:3], "item": "chashu"},
                        ["capacity", "pricing", "ops_rule"], 5, KB_BUDGET["rush"], as_of=date)
    payload = {"state": state, "last_15_min": evs, "shift_log": shift["bullets"] if shift else [], "kb": items}
    payload, dropped = _fit(payload, BUDGETS["rush"], [_pop(["last_15_min"], from_end=False), _pop(["state", "queue_head"]),
                                                       _pop(["kb"])])
    return {"agent": "rush", "date": date, "now": now.isoformat(timespec="seconds"), "budget_tokens": BUDGETS["rush"],
            "tokens": tokens(payload), "payload": payload, "dropped": dropped}


def build(agent: str, date: str, **kw) -> dict:
    f = {"review": review_context, "outlook": outlook_context, "exceptions": exceptions_context, "rush": rush_context}.get(agent)
    if f is None:
        raise KeyError(f"unknown agent '{agent}' (rush, outlook, exceptions, review)")
    return f(date, **kw)
