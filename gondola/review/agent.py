"""Review agent: at close, what went well and wrong, why, what to do next, and what to remember.

    python -m gondola.review.agent --date 2026-11-05

Order of work (`run_review`):
  1. ledger for the day (order-level build, idempotent) + a final exception scan (no texts) + shift logs
  2. day-digest inputs (code numbers only) and re-check of open action items against their measures
  3. the context, strictly within budget (review.context.review_context, design section 6.4)
  4. well / wrong / causes / actions / knowledge proposals:
       - agent mode (a model is configured or passed): an ADK LlmAgent with tools; every text is re-checked with
         agents.guardrails.check_numbers against the context and tool results, failing items are dropped and the
         deterministic version fills any empty section;
       - offline: ranked deterministic rules over the digest (same structure), so the demo works without a key.
  5. actions and knowledge proposals go through kb.propose (validation recomputes every number); decay + compaction
  6. the review, the day digest (shift logs folded in) and the roll-ups are stored; `review.completed` is written.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..agents.guardrails import check_numbers
from ..kb import KB, compact_item, kb as _kb
from ..kb import measures as M
from ..ledger import Ledger, ledger
from ..metrics import ROOT
from . import context as C
from . import digests as D

DB = ROOT / "data" / "gondola.duckdb"
CH = D.CH_NAME
MAX_ITEMS = 4
DISPUTE_ACTION_USD = 75  # same bar as the Sentinel text for a payout shortfall


def _txt(text: str, evidence: dict, score: float, topic: str) -> dict:
    return {"text": text, "evidence": evidence, "score": round(score, 2), "topic": topic}


def _when(date: str, days: int) -> str:
    return str((pd.Timestamp(date) + pd.Timedelta(days=days)).date())


# ------------------------------------------------------------------ action items: re-check at each close
def recheck_actions(date: str, kb: KB, db=DB, led: Ledger | None = None) -> list[dict]:
    """Every open action item: before check_on it stays open (with progress); on/after check_on its measure over the
    days since it was created decides done / not_working."""
    out = []
    for a in kb.list("active", "action_item"):
        if a.get("action_status") != "open" or (a.get("created") or "") >= date:
            continue
        m = a.get("measure") or {}
        res = {"id": a["id"], "text": a.get("statement"), "check_on": a.get("check_on"), "metric": m.get("metric")}
        if m.get("metric") in (None, "manual"):
            if a.get("expires_on") and date > a["expires_on"]:
                res.update(status="expired", outcome="not confirmed before it expired")
                a.update(action_status="expired", outcome={"checked_on": date, "note": res["outcome"]})
                kb.save(a, "check", date, res)
                kb.retire(a["id"], "expired without the manager confirming it", date)
            else:
                res.update(status="open", outcome="needs the manager to confirm" if date >= a.get("check_on", "9999") else None)
            out.append(res)
            continue
        start = _when(a["created"], 1)
        v = M.value(m["metric"], m.get("scope") or {}, None, date, db, led=led, start=start)
        base, val, n = m.get("baseline"), v.get("value"), v.get("n", 0)
        res.update(value=val, baseline=base, n=n)
        if date < a.get("check_on", date) or not n:
            res["status"] = "open"
            a["progress"] = {"as_of": date, "value": val, "n": n}
            kb.save(a, "progress", date, res)
            out.append(res)
            continue
        target = m.get("target")
        if m.get("direction", "down") == "down":
            ok = (target is not None and val <= target) or (base is not None and val <= base * 0.8)
        else:
            ok = (target is not None and val >= target) or (base is not None and val >= base * 1.1)
        status = "done" if ok else "not_working"
        res["status"] = status
        a.update(action_status=status, outcome={"checked_on": date, "value": val, "baseline": base, "n": n})
        kb.save(a, "check", date, res)
        kb.retire(a["id"], "done: the measure moved" if ok else "not working: the measure did not move", date)
        out.append(res)
    return out


# ------------------------------------------------------------------ the deterministic reviewer
def offline_review(date: str, inp: dict, checks: list[dict], db=DB, led: Ledger | None = None) -> dict:
    n, cond, fc, so, mon = inp["numbers"], inp["conditions"], inp.get("forecast"), inp.get("sold_out"), inp["money"]
    wd = inp["weekday"]
    wds = pd.Timestamp(date).day_name() + "s"  # "Thursdays"
    well, wrong, causes, actions, kbp = [], [], [], [], []
    sell = M.value("sellout_rate", {"weekday": wd}, None, date, db)
    reasons = n.get("cancels_by_reason") or {}

    # ---- went well
    if fc and fc.get("in_range") and fc.get("error_pct") is not None and abs(fc["error_pct"]) <= 5:
        well.append(_txt(f"Forecast was close: {fc['p50']:.0f} predicted, {fc['actual']} actual ({-fc['error_pct']:+.1f}% vs forecast).",
                         {"forecast": fc, "neg_err": -fc["error_pct"]}, 3, "forecast"))
    cd = mon.get("cash_diff")
    if cd is not None and abs(cd) <= 5:
        well.append(_txt(f"Cash drawer balanced (off ${abs(cd):.2f}).", {"cash_diff": cd, "abs": abs(cd)}, 2, "cash"))
    clean = [p for p in mon.get("payouts") or [] if p.get("difference") is not None and abs(p["difference"]) <= 1
             and not p.get("error_charges")]
    if clean:
        well.append(_txt(f"{' and '.join(CH.get(p['channel'], p['channel']) for p in clean)} payout"
                         f"{'s' if len(clean) > 1 else ''} matched what we expected.", {"payouts": clean}, 1.5, "payouts"))
    if n.get("vs_usual_pct") is not None and n["vs_usual_pct"] >= 5:
        well.append(_txt(f"Busy day: {n['orders']} orders, {n['vs_usual_pct']:+.1f}% vs a usual {wd}.",
                         {"orders": n["orders"], "vs_usual_pct": n["vs_usual_pct"]}, 2.5 + n["vs_usual_pct"] / 10, "demand"))
    if not so and sell.get("value") is not None and sell["value"] >= 0.25 and inp["prep"].get("sold_out") is False:
        well.append(_txt(f"Chashu lasted the night; it sold out on {sell['value']:.0%} of the last {sell['n']} {wds}.",
                         {"sellout_rate": sell}, 2.5, "sell-out"))
    if n.get("promises_met_pct") is not None and n["promises_met_pct"] >= 0.95:
        well.append(_txt(f"{n['promises_met_pct']:.1%} of {n['promises_total']} delivery promises met.",
                         {"promises_met_pct": n["promises_met_pct"], "promises_total": n["promises_total"]}, 3.5, "late orders"))
    if n["cancels"] == 0 and n["orders"]:
        well.append(_txt("No cancellations.", {}, 1, "cancellations"))
    elif n["cancels"] <= 3 and not reasons.get("item_unavailable") and n["orders"]:
        well.append(_txt(f"Only {n['cancels']} cancellations, none for unavailable items.", {"cancels": n["cancels"]}, 1, "cancellations"))
    for c in checks:
        if c.get("status") == "done":
            well.append(_txt(f"Action worked: \"{c['text']}\" ({c['metric']} {c['baseline']} → {c['value']}).", c, 4, "actions"))

    # ---- went wrong
    if so:
        wrong.append(_txt(f"Chashu sold out at {so['at']}; {so['app_cancels']} app orders were cancelled while it was still live "
                          f"({so['minutes_live']} min).", so, 5 + so["app_cancels"] / 2, "sell-out"))
    elif reasons.get("item_unavailable", 0) >= 3:
        wrong.append(_txt(f"{reasons['item_unavailable']} orders were cancelled for unavailable items.",
                          {"n": reasons["item_unavailable"]}, 3 + reasons["item_unavailable"] / 3, "cancellations"))
    if fc and not fc.get("in_range") and fc.get("error_pct") is not None:
        wrong.append(_txt(f"Forecast missed: {fc['p50']:.0f} predicted vs {fc['actual']} actual, outside the "
                          f"{fc['p10']:.0f}–{fc['p90']:.0f} range ({fc['error_pct']:+.1f}% vs actual).",
                          {"forecast": fc}, 3 + abs(fc["error_pct"]) / 5, "forecast"))
    if cd is not None and cd < -5:
        wrong.append(_txt(f"Cash drawer short ${-cd:.2f}.", {"cash_diff": cd, "short": -cd}, 2 + -cd / 10, "cash"))
    for p in mon.get("payouts") or []:
        if (p.get("recoverable_usd") or 0) >= 25 or (p.get("difference") or 0) < -25:
            wrong.append(_txt(f"{CH.get(p['channel'], p['channel'])} paid ${-(p.get('difference') or 0):,.2f} less than expected "
                              f"for {p['for_date']} ({p.get('n_disputable') or 0} disputable error charges, "
                              f"${p.get('recoverable_usd') or 0:,.2f} recoverable).",
                              {**p, "short": -(p.get("difference") or 0)}, 2 + (p.get("recoverable_usd") or 0) / 30, "payouts"))
    if n.get("vs_usual_pct") is not None and n["vs_usual_pct"] <= -10:
        wrong.append(_txt(f"Quiet day: {n['orders']} orders, {n['vs_usual_pct']:+.1f}% vs a usual {wd}.",
                          {"orders": n["orders"], "vs_usual_pct": n["vs_usual_pct"]}, 2 + abs(n["vs_usual_pct"]) / 10, "demand"))
    if n.get("promises_met_pct") is not None and n["promises_met_pct"] < 0.9:
        wrong.append(_txt(f"{n['late_orders']} of {n['promises_total']} orders were late; worst wait {n['worst_wait_min']} min.",
                          {k: n[k] for k in ("late_orders", "promises_total", "worst_wait_min")}, 4, "late orders"))
    if reasons.get("dasher_unavailable", 0) >= 3:
        wrong.append(_txt(f"{reasons['dasher_unavailable']} orders were cancelled because no courier was available.",
                          {"n": reasons["dasher_unavailable"]}, 2, "cancellations"))
    for x in inp.get("exceptions") or []:
        if x.get("kind") == "station_incident":
            wrong.append(_txt(f"Station incident: {x['title']}.", x, 3, "incidents"))
    for c in checks:
        if c.get("status") == "not_working":
            wrong.append(_txt(f"Action not working: \"{c['text']}\" ({c['metric']} {c['baseline']} → {c['value']}).", c, 3.5, "actions"))

    # ---- root causes (connect what went wrong to evidence)
    if so:
        par, used = inp["prep"].get("par"), inp["prep"].get("used")
        ev = {"par": par, "used": used, "sellout_rate": sell.get("value"), "n": sell.get("n")}
        t = f"Chashu prep ({par:.0f} portions) was fully used by {so['at']}" if par else f"Chashu ran out at {so['at']}"
        if sell.get("value"):
            t += f"; it sold out on {sell['value']:.0%} of the last {sell['n']} {wds}, so the par is too low for {wds}"
        if so.get("minutes_live"):
            t += f", and it stayed live on the apps {so['minutes_live']} min after"
        causes.append(_txt(t + ".", {**ev, **so}, 5, "sell-out"))
    if fc and not fc.get("in_range"):
        drivers = [M.event_family_name(e) for e in cond.get("events") or []] + [k for k in ("rain", "snow", "dd_promo") if cond.get(k)]
        for drv in drivers[:2]:
            e = M.effect("orders", {"event": drv}, None, date, db)
            if e.get("change_pct") is None:
                continue
            label = {"rain": "Rain", "snow": "Snow", "dd_promo": "The DoorDash promotion"}.get(drv, drv)
            causes.append(_txt(f"{label} usually moves orders {e['change_pct']:+.1f}% vs the same weekday without it "
                               f"({e['n']} past days); the forecast was {fc['direction']} by {abs(fc['error_pct']):.1f}%.",
                               {"effect": e, "forecast": fc, "abs_err": abs(fc["error_pct"])}, 4, "forecast"))
        if not drivers:
            causes.append(_txt(f"No event or weather on file explains the forecast miss ({fc['error_pct']:+.1f}%).",
                               {"forecast": fc}, 2, "forecast"))
    for p in mon.get("payouts") or []:
        if (p.get("n_disputable") or 0) > 0:
            causes.append(_txt(f"{p['n_disputable']} of the {p.get('error_charges') or 0} {CH.get(p['channel'], p['channel'])} "
                               f"error charges for {p['for_date']} are larger than any single item on the order.",
                               p, 3, "payouts"))
    if cd is not None and cd < -20:
        causes.append(_txt("No paid-out or refund in the ledger explains the cash gap.", {"cash_diff": cd}, 1.5, "cash"))

    # ---- action items (each with an owner, a check date and the measure that will show it worked)
    if so and so.get("app_cancels", 0) >= 5:
        actions.append({"kind": "action_item", "topic": "sell-out cancels", "scope": {"weekday": wd, "item": "chashu"},
                        "statement": f"Pause chashu on the delivery apps before it runs out on {wds} and recount at 6:30 pm",
                        "owner": "kitchen lead", "check_on": _when(date, 14),
                        "measure": {"metric": "unavailable_cancels", "scope": {"weekday": wd, "channel": "delivery"},
                                    "direction": "down", "window_days": 28}})
    if cd is not None and cd < -20:
        actions.append({"kind": "action_item", "topic": "cash", "scope": {}, "owner": "manager", "check_on": _when(date, 7),
                        "statement": "Count the cash drawer at every shift change for a week",
                        "measure": {"metric": "cash_short_rate", "scope": {}, "direction": "down", "window_days": 14}})
    for p in mon.get("payouts") or []:
        if (p.get("recoverable_usd") or 0) >= DISPUTE_ACTION_USD:  # smaller amounts stay on Books' dispute checklist
            nd, chn = p.get("n_disputable") or 0, CH.get(p["channel"], p["channel"])
            actions.append({"kind": "action_item", "topic": f"dispute {p['channel']} {p['for_date']}", "scope": {"channel": p["channel"]},
                            "owner": "manager", "check_on": _when(date, 3), "expires_on": _when(p["for_date"], 14),
                            "statement": f"Dispute ${p['recoverable_usd']:,.2f} with {chn} for {p['for_date']}"
                                         + (f" ({nd} error charge{'s' if nd != 1 else ''})" if nd else "")
                                         + " before the 14-day window closes",
                            "measure": {"metric": "manual"},
                            "params": {"n": nd, "usd": p["recoverable_usd"], "dispute_window_days": 14}})
    if n.get("promises_met_pct") is not None and n["promises_met_pct"] < 0.9:
        actions.append({"kind": "action_item", "topic": "late orders", "scope": {"weekday": wd}, "owner": "manager",
                        "check_on": _when(date, 7), "statement": f"Quote longer prep times on the delivery apps during the {wd} rush",
                        "measure": {"metric": "promises_met_pct", "scope": {"weekday": wd}, "direction": "up", "window_days": 14}})

    # ---- knowledge proposals (numbers from the same measures the validator recomputes)
    for drv in [M.event_family_name(e) for e in cond.get("events") or []]:
        for sc in ({"weekday": wd, "event": drv}, {"event": drv}, {"event": drv, "channel": "delivery"}):
            e = M.effect("orders", sc, None, date, db)
            if e.get("change_pct") is None or (sc.get("weekday") and e["n"] < 3):
                continue
            where = f"on {wds}" if sc.get("weekday") else ""
            kbp.append({"kind": "event_effect", "scope": {**sc}, "effect": {"metric": "orders", "change_pct": e["change_pct"]},
                        "statement": f"{drv}s move {'delivery ' if sc.get('channel') else ''}orders {e['change_pct']:+.0f}% "
                                     f"{where} vs the same weekday without one".replace("  ", " ")})
            if sc.get("weekday"):
                break  # the weekday-specific effect is enough when it has the evidence
    for k, label in (("rain", "Rain"), ("snow", "Snow")):
        if cond.get(k):
            for sc in ({"event": k}, {"event": k, "channel": "delivery"}):
                e = M.effect("orders", sc, None, date, db)
                if e.get("change_pct") is not None:
                    kbp.append({"kind": "event_effect", "scope": sc, "effect": {"metric": "orders", "change_pct": e["change_pct"]},
                                "statement": f"{label} moves {'delivery ' if sc.get('channel') else ''}orders {e['change_pct']:+.0f}% "
                                             "vs the same weekday when it's dry"})
    if cond.get("dd_promo"):
        e = M.effect("orders", {"event": "dd_promo", "channel": "doordash"}, None, date, db)
        if e.get("change_pct") is not None:
            kbp.append({"kind": "pricing", "scope": {"offer": "dd_promo", "channel": "doordash"},
                        "effect": {"metric": "orders", "change_pct": e["change_pct"]},
                        "statement": f"DoorDash promotion days move DoorDash orders {e['change_pct']:+.0f}% vs the same weekday without"})
    if sell.get("value") is not None and (so or sell["value"] >= 0.25):
        kbp.append({"kind": "item_behavior", "scope": {"item": "chashu", "weekday": wd},
                    "effect": {"metric": "sellout_rate", "value": sell["value"]},
                    "statement": f"Chashu sells out on {sell['value']:.0%} of {wds} (last {sell['n']} {wds})"})
        if sell["value"] >= 0.3 and sell["n"] >= 3:
            kbp.append({"kind": "ops_rule", "scope": {"item": "chashu", "weekday": wd},
                        "effect": {"metric": "sellout_rate", "value": sell["value"]},
                        "statement": f"On {wds} recount chashu at 6:30 pm and pause it on the apps early: it sells out on "
                                     f"{sell['value']:.0%} of {wds}"})
    peak = M.value("peak_orders_per_hour", {"weekday": wd}, None, date, db)
    if peak.get("value"):
        kbp.append({"kind": "capacity", "scope": {"weekday": wd}, "effect": {"metric": "peak_orders_per_hour", "value": peak["value"]},
                    "statement": f"{wd} peak hour runs about {peak['value']:.0f} orders"})
    try:
        from ..ledger.learning import learned_durations
        ld = learned_durations(date, led=led)["by_item"]
    except Exception:  # noqa: BLE001
        ld = {}
    for item, v in list(ld.items())[:4]:
        pm = M.value("prep_min", {"item": item}, None, date, db, led=led, lookback=28)
        if pm.get("value") is not None:
            kbp.append({"kind": "item_behavior", "scope": {"item": item, "station": v.get("station")},
                        "effect": {"metric": "prep_min", "value": pm["value"]},
                        "statement": f"{item} takes about {pm['value']:.1f} min at the {v.get('station')} station"})

    rank = lambda xs: sorted(xs, key=lambda x: -x["score"])[:MAX_ITEMS]
    return {"well": rank(well), "wrong": rank(wrong), "causes": rank(causes)[:3], "actions": actions, "kb": kbp}


# ------------------------------------------------------------------ agent mode
def llm_review(date: str, ctx: dict, offline: dict, model, db=DB, led: Ledger | None = None) -> dict:
    """The ADK Review agent. Returns sections whose every number passed the check, plus what was dropped."""
    from . import llm

    payload = ctx["payload"]

    def get_day_digest(date: str) -> dict:
        """Today's computed day-digest inputs (orders, sales, cancels, forecast check, sell-out, money, exceptions)."""
        return payload["today"]

    def get_history() -> dict:
        """What went wrong on the last 7 reviewed days, open action items, and knowledge items touched today."""
        return {k: payload.get(k) for k in ("recent_wrong", "open_actions", "kb")}

    def measure_effect(event: str, weekday: str = "", channel: str = "all", metric: str = "orders") -> dict:
        """Effect of an event or condition (e.g. 'Penguins home game', 'rain', 'dd_promo') on a metric: same weekday with
        vs without, over the last 120 days. Returns change_pct and n."""
        r = M.effect(metric, {"event": event, "weekday": weekday or None, "channel": channel}, None, date, db, led=led)
        return {k: r.get(k) for k in ("change_pct", "n", "evidence", "agreement")}

    def measure_value(metric: str, weekday: str = "", item: str = "", channel: str = "all") -> dict:
        """Recent average of a metric (sellout_rate, peak_orders_per_hour, unavailable_cancels, orders, ...) on matching days."""
        r = M.value(metric, {"weekday": weekday or None, "item": item or None, "channel": channel}, None, date, db, led=led)
        return {k: r.get(k) for k in ("value", "n")}

    instr = ("You review a ramen shop's closed day ({date?}). Call get_day_digest and get_history, and measure_effect / "
             "measure_value for any effect you want to claim. Reply ONLY with JSON: {\"well\": [{\"text\", \"evidence\"}], "
             "\"wrong\": [...], \"causes\": [...], \"actions\": [{\"statement\", \"owner\", \"check_on\": \"YYYY-MM-DD\", "
             "\"measure\": {\"metric\", \"scope\", \"direction\"}}], \"kb\": [{\"kind\", \"scope\", \"statement\", \"effect\"}]}. "
             "At most 4 items per list. Tie every item to numbers and times from the tools.")
    agent = llm.build_agent(model, "review", instr, [get_day_digest, get_history, measure_effect, measure_value], "review")
    out = llm.run(agent, {"date": date}, f"Review {date}.", max_llm_calls=16)
    parsed = llm.parse_json(out["state"].get("review") or out["finals"].get("review"))
    if not isinstance(parsed, dict):
        raise ValueError("review agent returned no JSON")
    facts = [payload] + llm.tool_facts(out["state"]) + [x.get("evidence") for k in ("well", "wrong", "causes") for x in offline[k]]
    res, dropped = {}, []
    for sec in ("well", "wrong", "causes"):
        keep = []
        for x in parsed.get(sec) or []:
            text = x.get("text") if isinstance(x, dict) else str(x)
            if not text:
                continue
            g = check_numbers(text, facts)
            if g["ok"]:
                keep.append({"text": text, "evidence": x.get("evidence") if isinstance(x, dict) else None, "by": "review-agent"})
            else:
                dropped.append({"section": sec, "text": text, "unsupported": g["unsupported"]})
        res[sec] = keep[:MAX_ITEMS] if keep else offline[sec]
    acts = []
    for a in parsed.get("actions") or []:
        if isinstance(a, dict) and a.get("statement"):
            acts.append({"kind": "action_item", "topic": a.get("topic") or a["statement"][:40], "scope": a.get("scope") or {},
                         **{k: a.get(k) for k in ("statement", "owner", "check_on", "measure")}})
    res["actions"] = acts or offline["actions"]
    res["kb"] = [k for k in parsed.get("kb") or [] if isinstance(k, dict)] or offline["kb"]
    return {**res, "dropped": dropped, "tool_calls": out["tool_calls"], "guardrail_blocked": out["guardrail_blocked"]}


# ------------------------------------------------------------------ run
def run_review(date: str, db: Path | str = DB, led: Ledger | None = None, kb: KB | None = None,
               dg: D.Digests | None = None, close_res: dict | None = None, model=None, send: bool = False) -> dict:
    """Run the Review for a closed `date`. model=None: agent mode only when configured; False: never."""
    from ..ledger.build import build_day
    from .exceptions import scan
    led, kb, dg = led or ledger(), kb or _kb(), dg or D.digests()
    date = str(pd.Timestamp(date).date())
    build_day(date, db, led)
    end = datetime.fromisoformat(date) + timedelta(hours=23, minutes=59)
    scan(date, end, led, db, model=False, send=send)
    from ..now import close_min
    D.write_shift_logs(date, close_min(date) // 60, led, dg)
    inp = D.day_inputs(date, led, db, close_res, dg)
    checks = recheck_actions(date, kb, db, led)
    ctx = C.review_context(date, led, kb, dg, db, inputs=inp)
    off = offline_review(date, inp, checks, db, led)
    mode, extra = "offline", {}
    if model is None:
        from .llm import configured_model
        model = configured_model()
    if model is not None and model is not False:
        try:
            r = llm_review(date, ctx, off, model, db, led)
            extra = {"dropped": r.pop("dropped"), "tool_calls": r.pop("tool_calls"), "guardrail_blocked": r.pop("guardrail_blocked")}
            off, mode = r, "adk"
        except Exception as e:  # noqa: BLE001 - the deterministic review always stands
            extra = {"agent_error": str(e)[:300]}
    # final number check on everything we will show (the offline texts are template + code numbers; checked anyway)
    for sec in ("well", "wrong", "causes"):
        kept = []
        for x in off[sec]:
            g = check_numbers(x["text"], [inp, x.get("evidence") or {}])
            if g["ok"] or x.get("by") == "review-agent":
                kept.append(x)
            else:
                extra.setdefault("dropped", []).append({"section": sec, "text": x["text"], "unsupported": g["unsupported"]})
        off[sec] = kept
    kb_changes, actions = [], []
    for a in off["actions"]:
        r = kb.propose(a, date, db, led)
        it = r["item"]
        if r["ok"]:
            actions.append({"id": it["id"], "text": it["statement"], "owner": it.get("owner"), "check_on": it.get("check_on"),
                            "measure": it.get("measure"), "status": it.get("action_status"), "op": r["op"]})
        kb_changes.append({"id": it.get("id"), "op": r["op"], "kind": "action_item", "statement": it.get("statement"),
                           "status": it.get("status"), "reason": r.get("reason")})
    for p in off["kb"]:
        r = kb.propose(p, date, db, led)
        it = r["item"]
        kb_changes.append({"id": it.get("id"), "op": r["op"], "kind": it.get("kind"), "statement": it.get("statement"),
                           "status": it.get("status"), "effect": it.get("effect"), "n": it.get("n"), "reason": r.get("reason")})
    dec = kb.decay(date)
    comp = kb.compact(date) if pd.Timestamp(date).dayofweek == 6 else {"merged": []}
    for rid in dec["retired"] + comp["merged"]:
        kb_changes.append({"id": rid, "op": "retire", "statement": (kb.get(rid) or {}).get("statement"), "status": "retired",
                           "reason": (kb.get(rid) or {}).get("retired_reason")})
    open_now = [compact_item(a) for a in kb.list("active", "action_item") if a.get("action_status") == "open"]
    review = {"date": date, "status": "done", "mode": mode, "weekday": inp["weekday"],
              "well": [{"text": x["text"], "evidence": x.get("evidence")} for x in off["well"]],
              "wrong": [{"text": x["text"], "evidence": x.get("evidence")} for x in off["wrong"]],
              "causes": [{"text": x["text"], "evidence": x.get("evidence")} for x in off["causes"]],
              "actions": actions, "action_checks": checks, "open_actions": len(open_now), "kb_changes": kb_changes,
              "digest_id": f"day-{date}", "context": {"tokens": ctx["tokens"], "budget_tokens": ctx["budget_tokens"],
                                                       "dropped": ctx["dropped"]},
              "summary": None, **extra}
    dd = D.day_digest(date, inp, review)
    review["summary"] = dd["summary"]
    dg.put(dd)
    dg.put_review(date, review)
    dg.delete([s["id"] for s in dg.list("shift", start=date, end=date)])  # folded into the day digest
    review["rollup"] = D.rollup(date, dg)
    led.append("review.completed", date, f"{date}T23:59:00", {"date": date, "digest_id": dd["id"], "mode": mode},
               source="review", key=f"review:completed:{date}")
    return review


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the Review agent for a closed day.")
    ap.add_argument("--date", required=True)
    a = ap.parse_args(argv)
    r = run_review(a.date)
    print(json.dumps({k: r[k] for k in ("date", "mode", "well", "wrong", "causes", "actions", "kb_changes")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
