"""Frozen-calendar feasibility comparisons, not conversion or revenue validation.

The strong fixed-delay comparator uses exactly the same safety checks. The
hypothetical future order is evaluated only after each choice has been selected.
No future order is exposed to the offer planner or model.
"""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gondola.flex import calendar
from gondola.flex.models import CartRequest, SessionRequest


def validate(session, option):
    """Independent interval counts, dependencies, stock, budget and base identity."""
    before = copy.deepcopy(session["observed"])
    result = copy.deepcopy(session)
    result["bookings"].append({"item": option["tasks"][0]["item"], "option": option})
    result["spent_cents"] += option["discount_cents"]
    rows = before["base_plan"] + [t for b in result["bookings"] for t in b["option"]["tasks"]]
    for minute in range(12, 200):
        active = [r for r in rows if r["start"] <= minute < r["end"]]
        assert all(sum(r["station"] == station for r in active) <= 1 for station in ("fryer", "noodles", "assembly", "packing"))
        assert sum(r["station"] != "packing" for r in active) <= before["cooks"]
    cook, pack = option["tasks"]
    assert cook["end"] == pack["start"] and pack["end"] == option["pickup_minute"]
    assert result["spent_cents"] <= result["config"]["budget_cents"]
    assert before["stock"][cook["item"]] - 1 >= 0 and result["observed"] == before
    return result


def describe(session, cart, option, regular):
    if not option: return {"status": "no_feasible_checkout"}
    committed = validate(session, option)
    # A separate, deliberately designed stress probe. This is a possible future
    # urgent bowl, not sampled merchant demand, conversion, or a training signal.
    probe = next((p for minute in range(20, 31)
                  if (p := calendar.plan_at(committed, "don", minute))
                  and p["tasks"][0]["start"] >= 18), None)
    cook, pack = option["tasks"]
    return {"status": "reservable", "kind": option["kind"], "pickup": option["pickup_clock"],
            "cook": [calendar.clock(cook["start"]), calendar.clock(cook["end"])],
            "pack": [calendar.clock(pack["start"]), calendar.clock(pack["end"])],
            "price_cents": option["price_cents"], "incentive_cost_cents": option["discount_cents"],
            "additional_customer_wait_minutes": option["pickup_minute"] - regular["pickup_minute"],
            "near_term_cook_minutes_released": option["released_cook_minutes"],
            "modeled_holding_minutes": option["holding_minutes"], "invariants_pass": True,
            "hypothetical_urgent_bowl_earliest_pickup": probe["pickup_clock"] if probe else None,
            "hypothetical_urgent_bowl_fits_by_17_54": bool(probe and probe["pickup_minute"] <= 24)}


def run():
    cases = [
        ("default_rush_bowl", {}, {}),
        ("different_seed_noodles", {"seed": 11}, {"item": "tonkotsu", "latest_pickup_minute": 90}),
        ("blocked_fryer", {}, {"item": "gyoza", "latest_pickup_minute": 120}),
        ("quiet_evening", {"scenario": "quiet"}, {}),
        ("one_cook_overload", {"scenario": "overload", "cooks": 1}, {"latest_pickup_minute": 120}),
        ("short_customer_deadline", {}, {"latest_pickup_minute": 25}),
        ("no_incentive_budget", {"budget_cents": 0}, {}),
        ("higher_minimum_saving", {"cooks": 4}, {"minimum_saving_cents": 300}),
    ]
    output = []
    for name, settings, preferences in cases:
        req = SessionRequest(**settings)
        cart = CartRequest(cart_id="evaluation-cart", **preferences)
        session = {"config": req.model_dump(), "observed": calendar.observed_kitchen(req), "bookings": [], "spent_cents": 0}
        regular = calendar.regular_option(session, cart)
        allowed = sorted((c for c in calendar.candidates(session, cart) if c["allowed"]), key=lambda c: (-c["score"], c["pickup_minute"], c["discount_cents"]))
        selected = calendar.make_option(allowed[0]) if allowed else regular
        # A credible simple rule: twenty minutes later, rounded to a five-minute
        # slot, $2 off, with the same constraints; fall back to regular if unsafe.
        fixed = None if not regular else calendar.check_flex(session, cart, math.ceil((regular["pickup_minute"] + 20) / 5) * 5, 200)
        fixed_option = calendar.make_option(fixed) if fixed and fixed["allowed"] else regular
        output.append({"case": name, "configuration": req.model_dump(), "customer": cart.model_dump(),
                       "regular": describe(session, cart, regular, regular),
                       "guarded_fixed_20_minute_rule": describe(session, cart, fixed_option, regular),
                       "checked_capacity_planner": describe(session, cart, selected, regular),
                       "fixed_rule_rejection": fixed["reason"] if fixed and not fixed["allowed"] else None})
    first = output[0]
    report = {"mode": "synthetic_frozen_calendar_reservations", "cases": output,
              "summary": {"cases": len(output), "invariant_failures": 0,
                          "planner_incentive_cases": sum(c["checked_capacity_planner"].get("kind") == "flexible" for c in output),
                          "guarded_fixed_incentive_cases": sum(c["guarded_fixed_20_minute_rule"].get("kind") == "flexible" for c in output)},
              "arrival_only_delay_diagnostic": {"case": first["case"], "cook": first["regular"]["cook"],
                                                "later_pickup": first["checked_capacity_planner"]["pickup"],
                                                "near_term_cook_minutes_released": 0,
                                                "holding_minutes": first["checked_capacity_planner"]["additional_customer_wait_minutes"]},
              "limits": ["Feasible reservations using observed estimates plus 20% allowance; no rest-of-dinner execution or future disruption model",
                         "The planner is deterministic. A separate real Gemini run selects proposals through these checked tools; no claim it outperforms the fixed rule",
                         "The urgent-bowl probe is a designed hypothetical future arrival at 17:48, tested only after selection; it does not estimate its probability",
                         "No customer adoption, causal sales uplift, actual fulfillment, profit or DoorDash integration is measured",
                         "$1 per released cooking minute is a stated owner-limit assumption; incentive cost and extra customer wait are reported explicitly"]}
    path = ROOT / "docs" / "demo" / "flex-evaluation.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "default": first}, indent=2))


if __name__ == "__main__": run()
