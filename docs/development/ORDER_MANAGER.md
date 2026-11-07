# Order Manager

Open **Present > Order manager**, `/present/orders`. `/rush/orders` redirects there. This workflow handles capacity admission and dispatch; capacity-aware discounts/promotions remain available in Present/Rush, and customer time-for-discount choices remain in Flexible Pickup.

## What works

The synthetic burst contains 29 observed orders: 12 DoorDash, 8 Uber Eats, 5 dine-in and 4 pickup. Five dine-in orders are already confirmed; the other 24 await admission. Menu lines and quantities consume real modeled station/shared-cook/finishing reservations.

One Order Manager specialist inspects observed work, compares four checked plans, and selects one. Code then revalidates the revision, commits the complete batch atomically, and verifies the persisted receipt. A model selection alone is not an order acceptance. Timeouts, stale state, duplicate IDs and invalid plans cannot silently create extra admissions. The explicit rules path remains usable without a model.

New requests can receive a later promise only within their explicitly authorized ready window and owner cap. Confirmed promises stay fixed, including when an incident makes them impossible. Reprioritization cannot increase estimated lateness for prior commitments; work in progress is frozen. Declines, expirations and quote extensions remain visible.

## Demo

1. Start the 29-order burst and inspect all four channel counts and four admission plans.
2. Apply a checked plan using rules or ask Order Manager to decide. Inspect accepted/later/declined decisions and the receipt.
3. Simulate a fryer slowdown or recovery, then advance service. Existing promises remain unchanged; estimates and next work update.
4. Reload or resume a saved session. Orders, progress, revisions and receipts persist.
5. Change the session in a second client before confirming a plan: the stale plan must fail and refresh.

## Implementation and boundaries

- `gondola/orders/`: typed requests, multi-line task dependencies, observed state, plan comparison, versioned commands and atomic SQLite persistence.
- `gondola/agents/order_manager.py`: one specialist with `inspect_demand`, `compare_admission_plans`, `select_checked_plan`; commit happens only after successful model completion.
- `gondola/rush/reservations.py`: minute-level station/cook/finishing kernel shared with Rush. Six complete Rush replay outputs were checked unchanged after extraction.
- `gondola/api/orders.py`: `/api/demand/config`, `/sessions`, session orders/plans/apply/capacity/advance/agent. Every mutation carries a version and event ID except creation; later-ready consent is an explicit input.
- React Order Manager and Present navigation; existing workflows and compatibility routes retained.

The prototype is bounded to 120 orders, 240 portions and 500 commands, four mapped menu items and four simulated service hours. It has a separate persisted session; it is not automatically the source of truth for the continuous Present replay or Flex ledger. Restaurant data, orders, progress and platform acceptance are simulated. Real model use does not grant merchant access. No external customer/merchant write or payment occurs.

## Verification

Production TypeScript/Vite build passed. Focused workflow/Rush/Flex run: 86 passed before the two additional persistence/history tests. Final full offline suite: **254 passed**, 227.59 seconds, with inherited deprecation warnings.

Seven integrated browser checks passed, including a **real Gemini** tool loop and a read-back-verified local commitment, rules/reload, disruption/progress, stale rejection, four existing workflows and 900/390 layouts. [Browser results](../demo/order-manager-browser.json), [live tool evidence](../demo/order-manager-live-evidence.json), [inbox](../demo/order-manager-inbox.png), [agent receipt](../demo/order-manager-agent.png), [unchanged Rush replay hashes](../demo/order-manager-kernel-regression.json).

The [eight-case evaluation](../demo/order-manager-evaluation.json) compares blind forwarding and four checked priorities. In the default three-cook case, the protected-current plan completes 27 of 29, declines 2 and uses 17 authorized later promises totaling 328 minutes of extension; zero misses against agreed promises must be reported with those tradeoffs. Simulation uses declared durations, not unseen actual restaurant performance. No universal optimality, causal demand effect or LLM superiority is established.

`tests/test_order_manager.py` covers multi-item capacity, consent/promise protection, disruptions, event deduplication, concurrent plans, restart, real ADK Runner wiring with a fake model, provider failure/stale selection and API constraints. Added integration checks keep durable sessions/unrelated model jobs out of Rush history and verify that store connections close explicitly.

## Reproduce

With installed dependencies, run `python -m pytest -q --disable-warnings` with provider configuration cleared in that test process. `python scripts/evaluate_order_manager.py --output docs/demo/order-manager-evaluation.json` is offline. `python web/scripts/order_manager_e2e.py` checks the running local app; `--live` intentionally makes one configured model request. `GONDOLA_BROWSER_URL` can select the local app address.

This feature includes advance-built work, integrated and verified on November 7. Preserve that distinction in organizer disclosure. No additional weather connector, marketing redesign or unrelated experimental agent was imported for this addition.
