from __future__ import annotations

from collections import Counter

from ..rush.agents import _run
from . import calendar, service
from .models import CartRequest


async def find_choices(ident: str, cart: CartRequest, progress) -> dict:
    published = []
    calls = []

    def record(name, result):
        if len(calls) >= 14: raise ValueError("Tool budget exhausted")
        calls.append(name)
        progress({"kind": "tool", "tool": name, "result": result})
        return result

    def inspect_checkout() -> dict:
        """Read declared customer constraints, current observed reservations and owner limits. No future outcomes."""
        s = service.state(ident)
        return record("inspect_checkout", {"customer": cart.model_dump(), "owner_limits": s["config"],
                       "budget_remaining_cents": s["config"]["budget_cents"] - s["spent_cents"],
                       "pressure": calendar.pressure(s), "available_stock": calendar.available_stock(s, cart.item),
                       "menu_item": calendar.MENU[cart.item], "planned_allocations": calendar.allocations(s),
                       "source": "Frozen synthetic observation; no private future customer response"})

    def compare_pickup_choices() -> dict:
        """Run the actual calendar and economic checks for a regular option and approved flexible alternatives."""
        s = service.state(ident)
        checks = calendar.candidates(s, cart)
        allowed = sorted((c for c in checks if c["allowed"]), key=lambda c: (-c["score"], c["pickup_minute"]))[:12]
        return record("compare_pickup_choices", {"regular": calendar.regular_option(s, cart),
                      "allowed": [{k: v for k, v in c.items() if k not in ("plan", "limits")} for c in allowed],
                      "rejected_reasons": dict(Counter(c["reason"] for c in checks if not c["allowed"])),
                      "candidates_checked": len(checks), "meaning": "Owner-limit score and modeled released cook minutes, not measured customer value"})

    def check_pickup_choice(pickup_minute: int, discount_cents: int) -> dict:
        """Check an alternative without publishing. Discount must be 100, 200 or 300 cents."""
        return record("check_pickup_choice", calendar.check_flex(service.state(ident), cart, pickup_minute, discount_cents))

    def publish_pickup_choices(first_pickup_minute: int, first_discount_cents: int,
                               second_pickup_minute: int = 0, second_discount_cents: int = 0) -> dict:
        """Publish one or two checked alternatives plus regular pickup. Creates proposals only; never books for the customer."""
        if published: return record("publish_pickup_choices", {"status": "rejected", "reason": "Choices already published"})
        picks = [(first_pickup_minute, first_discount_cents)]
        if second_pickup_minute: picks.append((second_pickup_minute, second_discount_cents))
        try:
            q = service.publish(ident, cart, picks, "gemini")
        except ValueError as exc:
            return record("publish_pickup_choices", {"status": "rejected", "reason": str(exc)})
        published.append(q)
        return record("publish_pickup_choices", {"status": "published", "quote_id": q["id"], "options": q["options"], "requires_customer_acceptance": True})

    def publish_regular_only() -> dict:
        """Publish just the feasible regular-price option when no discounted delay is justified. Does not book an order."""
        if published: return {"status": "rejected", "reason": "Already published"}
        q = service.publish(ident, cart, [], "gemini")
        published.append(q)
        return record("publish_regular_only", {"status": "published", "quote_id": q["id"], "reason": q["no_deal_reason"], "requires_customer_acceptance": True})

    meta = await _run("pickup_flexibility", "Find voluntary pickup-time choices for one first-party meal. "
                      "Inspect checkout, compare actual options, then publish checked choices or regular only. "
                      "Respect the customer's stated latest time and minimum saving. Never infer their urgency or willingness. "
                      "Discounts buy actual shifted cooking allocations, not just later customer arrival. "
                      "Choose a useful time/saving tradeoff using tool evidence, at most two alternatives. "
                      "If two alternatives are offered, the later one must save more. Prefer economical incentives; no discount when unjustified. "
                      "Publishing creates proposals only. The customer must explicitly accept and the server rechecks resources. "
                      "Do not accept orders, spend money, change real DoorDash or claim actual business uplift. "
                      "A rejected tool call is not success. Stop after one published quote.",
                      [inspect_checkout, compare_pickup_choices, check_pickup_choice, publish_pickup_choices, publish_regular_only],
                      progress, "Find feasible pickup options for the declared customer and publish the checked choices.")
    if not published: raise ValueError("The agent did not publish supported choices. No successful agent action is claimed")
    return {**meta, "agent_mode": "live_model", "data_mode": "synthetic", "quote": published[-1],
            "session": service.get(ident), "tool_sequence": calls, "action": "proposals_only_customer_consent_required"}
