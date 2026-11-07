# Flexible pickup build

November 6, 2026. User explicitly authorizes building/testing P16 and accepts absence of an equivalent native DoorDash feature as a **working assumption**, not evidence of absence. Existing public-feature/access research remains valid. Build a first-party browser checkout and merchant capacity view; do not write real DoorDash campaigns, contact customers or charge payment.

## Bounded complete workflow

- A labeled synthetic restaurant episode reuses Rush's observed kitchen snapshot/menu/shared-cook/station/packing reservations.
- One-meal cart, a customer's latest acceptable pickup and minimum worthwhile saving, and explicit owner incentive/budget/stock limits.
- Always calculate an independently feasible regular-price option. Later discounted options must move cooking/packing allocations out of the declared near-term pressure window, fit resources, satisfy customer limits and justify incentive against an explicit modeled relief-cost limit.
- Quotes expire and are proposals, not capacity guarantees. Customer acceptance revalidates and atomically reserves exact task slots, stock and discount budget. Concurrent overlap/stock/budget conflicts reject safely; replaying the same accepted quote returns its existing receipt. Declining creates no order or spend.
- SQLite session/order/quote/event state survives restart. Quote state version changes invalidate stale assumptions; never silently alter accepted prices/promises.
- Real Gemini tool loop reads the observed ledger, checks possible offers and publishes selected checked choices or a no-deal result. Deterministic planner remains an explicit usable mode; provider failures never become fake successful AI results.
- `/flex` shopper and merchant views show actual future preparation reservations, price/time choices, consent/receipt, changed allocations and modeled tradeoffs. Link from `/rush` without changing old benchmark behavior.
- Tests: resource/dependency/commitment protection, real work shifted (versus merely changing pickup label), cost/stock/budget, expiry/stale/replay/concurrent acceptance, impossible/quiet cases, independent baseline comparisons, real-model smoke and browser flow/errors/responsiveness with artifacts.

## Boundaries

No external platform access is assumed. A fixed synthetic service snapshot and future task reservations are planned state, not live kitchen telemetry or observed restaurant performance. Customer acceptance is an explicit browser action; simulated response in comparison cases must be separately labeled. A discount alone does not prove incremental revenue. New accepted orders are customer choices before purchase; renegotiating already paid Marketplace orders is outside this first build.

Keep existing uncommitted ideation docs and backup stash intact. Update feature coverage, disclosure, decisions/progress and the handoff as work lands. The bounded implementation and failure checks are complete; see [demo, measurements, limitations and remaining production work](FLEX_DEMO.md).
