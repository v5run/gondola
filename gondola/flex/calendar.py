"""Checked future allocations; no buyer utilities or future actual task durations."""
from __future__ import annotations

import math

from ..rush.engine import MENU, STATIONS, clock, snapshot
from ..rush.models import RushRequest
from .models import CartRequest, SessionRequest

NOW = 12
PEAK_END = NOW + 25
RELIEF_COST_LIMIT = 100  # modeled owner limit: cents per released cooking minute


def observed_kitchen(req: SessionRequest) -> dict:
    kitchen = snapshot(RushRequest(scenario=req.scenario, seed=req.seed, cooks=req.cooks,
                                   budget_cents=0, incident="fryer_slowdown" if req.scenario != "quiet" else "none"), NOW)
    obs = kitchen.observe()
    plan = kitchen._schedule()
    return {"minute": NOW, "clock": clock(NOW), "peak_end": PEAK_END, "cooks": req.cooks,
            "stock": obs["stock"], "estimates": obs["estimated_cook_minutes"],
            "speed": obs["station_speed"], "blocked_until": obs["blocked_until"], "base_plan": plan,
            "orders": [{k: o[k] for k in ("id", "channel", "item", "promise", "eta", "ready")} for o in obs["orders"]],
            "source_mode": "frozen_synthetic_snapshot"}


def allocations(session: dict) -> list[dict]:
    return session["observed"]["base_plan"] + [t for b in session["bookings"] for t in b["option"]["tasks"]]


def occupancy(session: dict):
    station = {s: [0] * 200 for s in STATIONS}
    cooks = [0] * 200
    for row in allocations(session):
        for m in range(max(NOW, row["start"]), min(200, row["end"])):
            station[row["station"]][m] += 1
            if row["station"] != "packing":
                cooks[m] += 1
    for s, until in session["observed"]["blocked_until"].items():
        for m in range(NOW, min(200, until)):
            station[s][m] = max(1, station[s][m])
    return station, cooks


def available_stock(session: dict, item: str) -> int:
    return session["observed"]["stock"][item] - sum(b["item"] == item for b in session["bookings"])


def can_place(session: dict, tasks: list[dict]) -> bool:
    station, cooks = occupancy(session)
    for row in tasks:
        if not NOW <= row["start"] < row["end"] < 200:
            return False
        for m in range(row["start"], row["end"]):
            if station[row["station"]][m] >= 1 or (row["station"] != "packing" and cooks[m] >= session["observed"]["cooks"]):
                return False
            station[row["station"]][m] += 1
            if row["station"] != "packing": cooks[m] += 1
    return True


def plan_at(session: dict, item: str, pickup: int) -> dict | None:
    obs = session["observed"]
    # Declared 20% work allowance, not access to the simulator's true duration.
    duration = max(1, math.ceil(obs["estimates"][item] * 1.2 / obs["speed"][MENU[item]["station"]]))
    # Ready exactly at pickup: moving pickup also moves production; no added food holding.
    tasks = [{"task_id": "candidate:cook", "order_id": "candidate", "station": MENU[item]["station"],
              "start": pickup - duration - 1, "end": pickup - 1, "item": item, "channel": "pickup"},
             {"task_id": "candidate:pack", "order_id": "candidate", "station": "packing",
              "start": pickup - 1, "end": pickup, "item": item, "channel": "pickup"}]
    if not can_place(session, tasks): return None
    return {"pickup_minute": pickup, "pickup_clock": clock(pickup), "tasks": tasks,
            "cook_minutes": duration, "holding_minutes": 0}


def regular_option(session: dict, cart: CartRequest) -> dict | None:
    if available_stock(session, cart.item) < 1: return None
    for minute in range(NOW + 2, cart.latest_pickup_minute + 1):
        plan = plan_at(session, cart.item, minute)
        if plan:
            return {**plan, "kind": "regular", "discount_cents": 0, "price_cents": MENU[cart.item]["price"],
                    "released_cook_minutes": 0, "score": 0, "reason": "Earliest currently reservable pickup; regular price"}
    return None


def pressure(session: dict) -> dict:
    station, cooks = occupancy(session)
    span = PEAK_END - NOW
    loads = {s: round(sum(station[s][NOW:PEAK_END]) / span, 3) for s in STATIONS}
    labor = sum(cooks[NOW:PEAK_END]) / (span * session["observed"]["cooks"])
    return {"stations": loads, "shared_cooks": round(labor, 3),
            "congested": max(*loads.values(), labor) >= 0.7, "window_start": NOW, "window_end": PEAK_END}


def check_flex(session: dict, cart: CartRequest, pickup: int, discount: int) -> dict:
    if type(pickup) is not int or type(discount) is not int or discount not in (100, 200, 300):
        return {"allowed": False, "reason": "Use an integer pickup minute and an approved $1, $2 or $3 incentive"}
    base = regular_option(session, cart)
    reason = None
    if base is None: return {"allowed": False, "reason": "No regular option fits stock and your latest pickup; no bargain can be promised"}
    if type(discount) is not int or discount not in (100, 200, 300): reason = "Use an approved $1, $2 or $3 incentive"
    elif discount < cart.minimum_saving_cents: reason = "Saving is below this customer's declared minimum"
    elif discount > session["config"]["max_discount_cents"]: reason = "Incentive exceeds the owner's per-order limit"
    elif discount > session["config"]["budget_cents"] - session["spent_cents"]: reason = "Insufficient unspent incentive budget"
    elif pickup > cart.latest_pickup_minute: reason = "Pickup exceeds this customer's stated latest time"
    elif pickup < base["pickup_minute"] + 5: reason = "A flexibility offer must move pickup by at least five minutes"
    elif not pressure(session)["congested"]: reason = "No measured pressure in this frozen episode justifies an incentive"
    plan = plan_at(session, cart.item, pickup) if type(pickup) is int and NOW < pickup <= 180 else None
    if reason is None and plan is None: reason = "Those cooking/packing slots are not free"
    def near(tasks):
        return sum(max(0, min(PEAK_END, t["end"]) - max(NOW, t["start"])) for t in tasks if t["station"] != "packing")
    released = max(0, near(base["tasks"]) - near(plan["tasks"])) if plan else 0
    if reason is None and released < 2: reason = "This delay releases fewer than two near-term cooking minutes"
    if reason is None and discount > released * RELIEF_COST_LIMIT: reason = "Incentive costs too much for the modeled capacity relief"
    margin = MENU[cart.item]["price"] - MENU[cart.item]["cost"] - round(MENU[cart.item]["price"] * .03) - discount
    if reason is None and margin < 350: reason = "Contribution would fall below the fixed $3.50 floor"
    return {"allowed": reason is None, "reason": reason or "Moves production beyond pressure while preserving all existing allocations",
            "pickup_minute": pickup, "discount_cents": discount, "released_cook_minutes": released,
            "contribution_cents": margin, "regular_pickup_minute": base["pickup_minute"],
            "score": round(released * RELIEF_COST_LIMIT - discount - max(0, pickup - base["pickup_minute"]) * 2, 2),
            "plan": plan, "price_cents": MENU[cart.item]["price"] - discount,
            "limits": "Projected capacity relief in a frozen synthetic calendar; not measured conversion, profit or a real fulfillment guarantee"}


def candidates(session: dict, cart: CartRequest) -> list[dict]:
    regular = regular_option(session, cart)
    if regular is None: return []
    first = math.ceil((regular["pickup_minute"] + 5) / 5) * 5
    return [check_flex(session, cart, m, d) for m in range(first, min(cart.latest_pickup_minute, first + 35) + 1, 5) for d in (100, 200, 300)]


def make_option(check: dict) -> dict:
    return {**check["plan"], "kind": "flexible", "discount_cents": check["discount_cents"],
            "price_cents": check["price_cents"], "released_cook_minutes": check["released_cook_minutes"],
            "score": check["score"], "reason": check["reason"], "contribution_cents": check["contribution_cents"]}
