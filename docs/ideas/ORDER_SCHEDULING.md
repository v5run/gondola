# Adaptive cross-channel kitchen scheduling

November 6, 2026. Teammate-originated idea pasted by the user: combine DoorDash, Uber Eats, and pickup orders and choose preparation priorities using courier proximity/timing. The user likes its demo feasibility and asks whether it is useful and already done. This is an assessment, not implementation authorization. Current shortlist: [LEADING_IDEAS.md](LEADING_IDEAS.md).

## Assessment

Useful operational problem, a concrete browser demonstration, and a direct fit for the sponsor's peak-hour prompt. The broad idea already exists, including driver-ETA-aware sequencing. It is more precisely kitchen production scheduling than transferring orders between platforms. Accepted orders compete for the same kitchen resources.

**Direct comparison:** [Captain](https://www.captain.ai/solutions/kitchen) publicly describes driver ETAs driving cooking order and start times. [Otter](https://www.tryotter.com/products/order-management) describes consolidating delivery, pickup, and dine-in orders in one system. These are primary vendor descriptions checked November 6, not account tests or proof of performance; Captain's page does not establish every third-party Marketplace integration or ETA entitlement. Central aggregation and ETA priority are not new-market claims we should make.

## Why FIFO is not universally best

The useful objective combines meeting existing pickup/service promises, courier wait, food holding time, fairness, and feasible kitchen capacity. Creation time alone does not express all of those constraints.

Illustrative case, one free cook at 12:01, sequential non-preemptive tasks, exact pickup estimates for this example:

| Order | Placement | Prep duration | Promised pickup / courier arrival |
|---|---|---|---|
| A | 12:00 | 5 minutes | 12:20 |
| B | 12:01 | 4 minutes | 12:06 |

Immediate FIFO cooks A from 12:01-12:06, then B until 12:10: B's courier waits four minutes and A's food sits fourteen minutes. A feasible timed schedule cooks B from 12:01-12:05, then A from 12:15-12:20. Both promises are met; food holds one minute for B and zero for A. This is an illustrative counterexample, not a benchmark result or a recommendation to idle during an actual rush.

Nearest-courier-first is also insufficient: a slow dish needs an earlier start, already-present pickup customers need service, estimates can change, and old orders must not starve. Compare deadline-based and remaining-slack rules as well as FIFO. Latest feasible start depends on remaining task duration, dependencies, and resource availability.

## Proposed useful version

- Represent food tasks and shared stations, with explicit duration/dependency/capacity assumptions.
- Honor promised pickup windows and maximum waiting limits across channels. Channel identity alone should not buy priority.
- Coordinate finishing and packing; item holding times are modeled quality proxies, not measured food-quality claims.
- Replan when a courier estimate changes, a task finishes late, or a station slows. Freeze work already in progress and limit unnecessary queue reshuffling.
- Keep uncertainty and stale estimates visible; missing courier data falls back to the order's promise/configured rule instead of invented locations.
- Expose infeasible commitments rather than dropping orders from the score or moving promises silently.

Use platform adapters to normalize inputs, one fast scheduling engine to compute work, and an agent to interpret exceptions or develop/test better policies. Separate platform LLMs are not required by the dataflow. This problem could host the previously discussed policy-development agent, subject to independent evaluation; that agent role is proposed, not demonstrated.

## Where production data could come from

| Need | Documented source | Boundary |
|---|---|---|
| DoorDash order items, creation, fulfillment type, estimated pickup | [Marketplace order webhook](https://developer.doordash.com/en-US/docs/marketplace/how_to/order_integration/) | Partner access/configuration required. `estimated_pickup_time` is documented; verify exact integration version and interaction with merchant-confirmed prep time |
| DoorDash arrival/reassignment observations | [Dasher status webhook](https://developer.doordash.com/en-US/docs/marketplace/faq/dasher_status_webhook/) | Informational partner event; arriving-at-store is documented at 400 m. Not a promise of continuous GPS or a precise dynamic ETA stream; reassignment can repeat assignment events |
| Uber Eats order details and estimated pickup | [Get Order Details](https://developer.uber.com/docs/eats/references/api/v2/get-eats-order-orderid) and [order integration guide](https://developer.uber.com/docs/eats/guides/order-integration) | Approved OAuth scopes/test store required. Deliveries populate when scheduled; estimated pickup is distinct from predicted food-ready time. No guaranteed data before assignment |
| Pickup orders / customer promises / task progress | Existing POS/KDS or approved aggregator | Access and fields depend on provider. Staff completion signals must come from an actual supported workflow; no new hardware is needed for the demo |
| Cooking durations, station routing, capacities, batching rules | Merchant configuration and measured KDS history | Order feeds alone do not supply a full kitchen model. Missing operational facts must be configured or labeled assumptions |

Courier dispatch is affected by preparation estimates; courier ETA should not be treated as independent ground truth. The first simulation must state whether arrival updates are exogenous and test estimate noise/staleness. Drive access concerns deliveries booked through our app and does not grant an existing Marketplace order feed. No credentialed DoorDash/Uber call was performed.

## Existing fixture audit

The checked-out `data/raw/pos_orders.csv` has order IDs, dates/times, channels, prices, statuses/cancellation reasons, and promos. `pos_order_lines.csv` has order/item/price; `recipes.csv` has item/ingredient/quantity; `menu.csv` has price/category and limited-item portion fields. `labour_shifts.csv` has daily role/hours/wage totals.

Those files supply useful demand/menu history. They do **not** already provide courier ETA revisions, promised pickup windows, cooking start/finish timestamps, item-to-station durations, dependencies, or time-specific station availability. The teammate's statement that all data is mocked should not be read as proof those scheduling fixtures already exist in this checkout. Add them as explicitly synthetic data if this direction is selected.

## Small browser proof

Start with the suggested 12 DoorDash + 10 Uber Eats + 5 pickup orders, a small menu, two modeled cooking stations plus packing, and explicit operating limits. Treat all accepted orders identically across policy comparisons. Show tickets and a station timeline. Inject a driver delay, task overrun, or station slowdown and show the revised unstarted work and reasons.

Compare FIFO, earliest-deadline, remaining-slack, and the proposed controller on the same observations. Keep future actual arrivals/durations inaccessible to controllers. Include an orderly case where FIFO performs well and an overloaded case where every promise is impossible. Evaluate seeded scenario families and held-out combinations, not a single hand-picked rush.

Report on-time ready/pickup rates, courier waiting, food holding, worst customer wait and by-channel outcomes, unserved/late commitments, and schedule churn. Count all accepted orders and uncertainty. A controller that improves delivery metrics by starving pickup customers fails. A simple controller that performs as well as the agent is a valid result, not a reason to weaken the baseline.

**Recommendation:** Keep this as a concrete execution/demo candidate and a possible testbed for policy development. Broad novelty is low; useful adaptive behavior and measurable results can still make a strong hackathon project. No simulation, solver, product feature, or measured gain has been built in this assessment.
