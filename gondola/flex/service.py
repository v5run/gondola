from __future__ import annotations

import copy
import time
import uuid

from ..rush.engine import MENU
from . import calendar, store
from .models import CartRequest, SessionRequest


class Conflict(ValueError):
    pass


def create(req: SessionRequest) -> dict:
    session = {"id": uuid.uuid4().hex, "config": req.model_dump(), "observed": calendar.observed_kitchen(req),
               "revision": 1, "spent_cents": 0, "bookings": [], "quotes": {}, "events": []}
    with store.transaction() as con: store.save(con, session)
    return view(session)


def view(session: dict) -> dict:
    obs = session["observed"]
    return {"id": session["id"], "revision": session["revision"], "config": session["config"],
            "source_mode": "frozen_synthetic_snapshot", "payment_mode": "simulation_no_charge",
            "minute": obs["minute"], "clock": obs["clock"], "peak_end": obs["peak_end"],
            "menu": {k: {**v, "available": calendar.available_stock(session, k)} for k, v in MENU.items()},
            "base_orders": obs["orders"], "base_plan": obs["base_plan"], "pressure": calendar.pressure(session),
            "bookings": session["bookings"], "spent_cents": session["spent_cents"], "events": session["events"][-20:],
            "quote_summaries": [{"id": q["id"], "status": q["status"], "source": q["source"], "expires_at": q["expires_at"]} for q in list(session["quotes"].values())[-8:]],
            "assumptions": {"clock": "Service state is frozen at 17:42; quote expiry uses real elapsed time",
                            "capacity_value": "$1 per released near-term cooking minute is an owner-limit assumption, not measured value",
                            "duration": "Current observed estimate plus 20% allowance; future misses are possible",
                            "scope": "One meal/order. No payment or Marketplace modification. Existing allocations remain fixed."}}


def get(ident: str) -> dict:
    with store.transaction() as con: return view(store.read(con, ident))


def state(ident: str) -> dict:
    with store.transaction() as con: return store.read(con, ident)


def publish_locked(session: dict, cart: CartRequest, selections: list[tuple[int, int]], source: str) -> dict:
    if any(b["cart_id"] == cart.cart_id for b in session["bookings"]): raise Conflict("This checkout already has a confirmed order")
    regular = calendar.regular_option(session, cart)
    if regular is None: raise Conflict("No pickup fits this meal and your deadline. Choose another meal or a later deadline")
    options = [regular]
    if len(selections) > 2: raise ValueError("At most two flexible alternatives")
    for pickup, discount in selections:
        check = calendar.check_flex(session, cart, pickup, discount)
        if not check["allowed"]: raise Conflict(check["reason"])
        if any(o["pickup_minute"] == pickup for o in options): raise ValueError("Choose distinct pickup times")
        options.append(calendar.make_option(check))
    for a in options[1:]:
        if any(b is not a and b["pickup_minute"] <= a["pickup_minute"] and b["discount_cents"] >= a["discount_cents"] for b in options[1:]):
            raise ValueError("A later alternative must offer an additional saving")
    ident = uuid.uuid4().hex
    for i, option in enumerate(options): option["id"] = f"{ident}-{i}"
    rejected = calendar.candidates(session, cart)
    no_deal = None
    if not selections:
        if not calendar.pressure(session)["congested"]: no_deal = "The kitchen has room; an incentive is not justified in this episode"
        elif cart.minimum_saving_cents > session["config"]["max_discount_cents"]: no_deal = "Your minimum saving exceeds the owner's approved incentive limit"
        elif cart.minimum_saving_cents > session["config"]["budget_cents"] - session["spent_cents"]: no_deal = "The incentive budget cannot cover your minimum saving"
        else: no_deal = "No later choice meets the deadline and releases enough near-term cooking capacity"
    quote = {"id": ident, "cart": cart.model_dump(), "revision": session["revision"], "status": "open", "source": source,
             "created_at": time.time(), "expires_at": time.time() + session["config"]["quote_ttl_seconds"],
             "options": options, "no_deal_reason": no_deal,
             "baseline_allocations": copy.deepcopy(calendar.allocations(session)),
             "contract": "A proposal, not a hold. Choosing rechecks and reserves capacity, stock and budget atomically.",
             "source_mode": "simulation", "evidence": {"protected_existing_tasks": len(calendar.allocations(session)), "candidates_checked": len(rejected)}}
    session["quotes"][ident] = quote
    session["events"].append({"kind": "choices_published", "quote_id": ident, "source": source, "flexible_options": len(selections)})
    return copy.deepcopy(quote)


def publish(ident: str, cart: CartRequest, selections: list[tuple[int, int]], source="gemini") -> dict:
    with store.transaction() as con:
        session = store.read(con, ident)
        result = publish_locked(session, cart, selections, source)
        store.save(con, session)
        return result


def quote(ident: str, cart: CartRequest) -> dict:
    with store.transaction() as con:
        session = store.read(con, ident)
        allowed = sorted((c for c in calendar.candidates(session, cart) if c["allowed"]), key=lambda c: (-c["score"], c["pickup_minute"], c["discount_cents"]))
        picks = []
        for c in allowed:
            if not picks or (c["pickup_minute"] > picks[0][0] and c["discount_cents"] > picks[0][1]):
                picks.append((c["pickup_minute"], c["discount_cents"]))
            if len(picks) == 2: break
        result = publish_locked(session, cart, picks, "capacity_planner")
        store.save(con, session)
        return result


def get_quote(ident: str, quote_id: str) -> dict:
    with store.transaction() as con:
        session = store.read(con, ident)
        if quote_id not in session["quotes"]: raise KeyError("Unknown pickup quote")
        q = copy.deepcopy(session["quotes"][quote_id])
        if q["status"] == "open" and q["expires_at"] <= time.time(): q["status"] = "expired"
        return q


def accept(ident: str, quote_id: str, option_id: str) -> dict:
    with store.transaction() as con:
        session = store.read(con, ident)
        if quote_id not in session["quotes"]: raise KeyError("Unknown pickup quote")
        q = session["quotes"][quote_id]
        if q["status"] == "accepted":
            if q["receipt"]["option"]["id"] != option_id: raise Conflict("This checkout was already confirmed with a different choice")
            return {**q["receipt"], "replayed": True}
        if q["status"] != "open" or q["expires_at"] <= time.time(): raise Conflict("These choices expired or were declined. Refresh pickup options")
        if q["revision"] != session["revision"]: raise Conflict("Kitchen assumptions changed. Refresh pickup options")
        if any(b["cart_id"] == q["cart"]["cart_id"] for b in session["bookings"]): raise Conflict("This checkout already has a confirmed order")
        option = next((o for o in q["options"] if o["id"] == option_id), None)
        if option is None: raise ValueError("Unknown choice for this quote")
        cart = CartRequest.model_validate(q["cart"])
        if calendar.available_stock(session, cart.item) < 1: raise Conflict("That meal just sold out; no order or discount was created")
        if option["discount_cents"] > session["config"]["budget_cents"] - session["spent_cents"]: raise Conflict("Incentive budget changed; refresh pickup options")
        if not calendar.can_place(session, option["tasks"]): raise Conflict("That production slot just filled. Refresh options; no order or discount was created")
        if option["kind"] == "flexible":
            if not calendar.can_place(session, q["options"][0]["tasks"]):
                raise Conflict("The original earliest option changed. Refresh choices so the incentive still buys real capacity relief")
            check = calendar.check_flex(session, cart, option["pickup_minute"], option["discount_cents"])
            if not check["allowed"]: raise Conflict(check["reason"] + ". Refresh pickup choices")
        booking_id = "FLEX-" + uuid.uuid4().hex[:8].upper()
        saved = copy.deepcopy(option)
        for t in saved["tasks"]:
            t["task_id"] = booking_id + (":pack" if t["station"] == "packing" else ":cook")
            t["order_id"] = booking_id
        receipt = {"id": booking_id, "cart_id": cart.cart_id, "item": cart.item, "option": saved,
                   "regular_option": q["options"][0], "quote_id": quote_id, "accepted_at": time.time(),
                   "consent": "Customer explicitly selected this quoted time and price", "source": q["source"],
                   "status": "reserved", "source_mode": "simulation", "payment_mode": "no_charge", "replayed": False}
        receipt["comparison"] = {"allocations": q["baseline_allocations"], "regular": q["options"][0],
                                 "selected": saved, "peak_start": calendar.NOW, "peak_end": calendar.PEAK_END}
        session["spent_cents"] += saved["discount_cents"]
        session["bookings"].append(receipt)
        q["status"], q["receipt"] = "accepted", receipt
        session["events"].append({"kind": "customer_accepted", "order_id": booking_id, "quote_id": quote_id,
                                  "pickup_minute": saved["pickup_minute"], "discount_cents": saved["discount_cents"]})
        store.save(con, session)
        return receipt


def decline(ident: str, quote_id: str) -> dict:
    with store.transaction() as con:
        session = store.read(con, ident)
        if quote_id not in session["quotes"]: raise KeyError("Unknown pickup quote")
        q = session["quotes"][quote_id]
        if q["status"] == "accepted": raise Conflict("An accepted order cannot be silently cancelled")
        q["status"] = "declined"
        session["events"].append({"kind": "customer_declined", "quote_id": quote_id})
        store.save(con, session)
        return {"status": "declined", "orders_created": 0, "spend_cents": 0}


def compete(ident: str, quote_id: str, option_id: str) -> dict:
    """Explicit demo event: a different customer books an unheld proposal slot at full price."""
    with store.transaction() as con:
        session = store.read(con, ident)
        q = session["quotes"].get(quote_id)
        if q is None: raise KeyError("Unknown quote")
        option = next((o for o in q["options"] if o["id"] == option_id), None)
        if option is None: raise ValueError("Unknown option")
        if not calendar.can_place(session, option["tasks"]): raise Conflict("This slot is already occupied")
        if calendar.available_stock(session, q["cart"]["item"]) < 1: raise Conflict("Item unavailable")
        booking_id = "OTHER-" + uuid.uuid4().hex[:8].upper()
        saved = copy.deepcopy(option)
        saved.update(discount_cents=0, price_cents=MENU[q["cart"]["item"]]["price"], kind="regular", released_cook_minutes=0)
        for t in saved["tasks"]: t.update(order_id=booking_id, task_id=booking_id + (":pack" if t["station"] == "packing" else ":cook"))
        b = {"id": booking_id, "cart_id": uuid.uuid4().hex, "item": q["cart"]["item"], "option": saved,
             "regular_option": saved, "status": "reserved", "source": "simulated_other_customer", "accepted_at": time.time(),
             "consent": "Explicit demo event: another customer selected this slot", "source_mode": "simulation", "payment_mode": "no_charge"}
        session["bookings"].append(b)
        session["events"].append({"kind": "competing_booking", "order_id": booking_id})
        store.save(con, session)
        return b
