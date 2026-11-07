# Judge discussion: pitch, differentiation and useful operating assumptions

November 7, 2026. Formalization of the user's proposed pitch and concern about competing with DoorDash's own engineers. This is a discussion/research brief, not selection or implementation of additional features. Source inspection only; no new runtime/model experiment. Root source index S94-S96 adds the new DoorDash engineering evidence; S62-S65/S69/S76/S81 were refreshed.

## The coherent product

The user's four components fit: predict demand, shape incoming demand, schedule accepted kitchen work around readiness/pickup, and review outcomes for future decisions. Their connection through one model of capacity and commitments is the central hypothesis. Present scheduling and promotion decisions should be coordinated; Review should propose evidence-backed changes rather than declare a cause proved from one bad day.

Suggested reusable pitch (target product, not a statement that every production connector is implemented):

> We're building Gondola, an operating agent for a restaurant's shared kitchen. It combines demand forecasts with orders across delivery, pickup and dine-in, and the kitchen's actual constraints. It decides what the restaurant can safely promise, what to cook next, and when an approved deal or later-pickup offer could move demand into spare capacity. After service, it reviews decisions and outcomes, identifies possible causes of misses, and proposes testable improvements. Forecasting, offers and fulfillment all work from the same commitments, with owner limits and customer consent.

Demo qualification: restaurant/platform inputs and writes are simulated; identify each actual live feed separately. Real Gemini tool calls were verified on the original Rush/Flex branch. The newer tri-workflow's Review/Exceptions/Rush ADK paths have teammate fake-model tests, not a verified live Gemini run in our inspection. No general continuous live connector or guaranteed autonomous improvement is established.

Use **capacity-aware offers/demand shaping** for the implemented discount/recommendation mechanism. General personalized base-price changes or surge pricing are not established. Use **courier ETA/arrival signals** rather than continuous courier GPS: the [public Dasher event FAQ](https://developer.doordash.com/en-US/docs/marketplace/faq/dasher_status_webhook/) describes an arriving-at-store event at 400 m and limited API access; it does not establish a general live GPS feed for us.

Current-version boundaries: Future uses a conventional forecast plus intra-day correction; Outlook agent is deferred. Weather has an optional adapter, while events are supplied table data. Current Present replay does not model customer response to its offers. Review validates evidence/numbers and rechecks action-item measures; movement of a measure is not proof of causal learning. The separate tested Flex branch has quote/consent/atomic reservation; it is not yet merged into tri-workflow.

## What is and is not a defensible edge

Do not frame success as inventing weather-aware prediction, coupons or courier-aware preparation. DoorDash documents [real-time demand/preparation features](https://careersatdoordash.com/blog/supercharging-doordashs-marketplace-decision-making-with-real-time-knowledge/), [dynamic food release coordinated with Dasher arrival](https://careersatdoordash.com/blog/lifecycle-of-a-successful-ml-product-reducing-dasher-wait-times/), and [promotion response estimation/optimization](https://careersatdoordash.com/blog/doordash-smarter-promotions-with-causal-machine-learning/). Its [2026 supply/assignment work](https://careersatdoordash.com/blog/supercharging-doordash-logistics-through-causal-ml-and-joint-optimization/) already motivates joint optimization of previously separate decisions. These are evidence of overlap, not evidence the exact proposed merchant controller is implemented.

Likewise, [Otter](https://www.tryotter.com/products/order-management) markets cross-channel aggregation, [Captain](https://www.captain.ai/solutions/kitchen) markets ETA-driven cooking sequence/start times, and [Open](https://www.getopen.com/blog/restaurant-ai-decision-engine) describes kitchen-aware autonomous marketing. Merchant-wide integration or an observe/predict/act/learn diagram alone does not establish uniqueness.

There is no verified capability here that DoorDash's engineers are fundamentally unable to build. Our hackathon advantage is freedom to prototype a merchant-authorized combination of observations/actions before solving every real integration, rollout and commercial-coordination dependency. That is a research/demonstration advantage, not a durable moat. A future business edge would need real integration/distribution, calibrated operational data, trusted consent/commitment behavior and demonstrated outcomes; none is established yet.

Sponsor-friendly positioning: investigate how richer merchant-side state and authority could improve kitchen reliability, readiness estimates and customer/Dasher experience through an approved DoorDash integration. Do not assert DoorDash ignores merchants or lacks all cross-channel knowledge; its internal access is not known.

## The useful vocabulary and opportunity map

Follow-up: [additional inputs and experiments](ADDITIONAL_INPUTS.md) covers conditional purchase intent, un-fired kitchen work, event/journey progress, batch preparation state, supplier commitments and explicit offer-rejection reasons. No new feature is selected by that list.

The terms are **observability** (what the agent knows), **action space** (what it may change), **objective** (whose tradeoffs it optimizes), and **feedback** (what outcomes it can learn from). These are operating assumptions. For every relaxed constraint, name the additional decision it enables, its possible real source, and a test that could reject the idea.

| Assumption we can prototype | Additional decision enabled | Real route / first discriminating test |
|---|---|---|
| All accepted work and future commitments, including pickup, dine-in and catering, share one calendar | Reserve actual resources and refuse/re-quote incompatible new promises across channels | POS/KDS/direct-order adapters and merchant schedules. Hide one channel and compare lateness, lost orders and contribution; aggregation alone is not new |
| Observe station tasks, packing, available cooks and completion progress, not only order totals | Steer a specific menu/time combination away from the real binding resource | KDS task events plus recipe configuration, not assumed new hardware. Give the same order count two different bottlenecks; useful decisions should differ; include stale/missing telemetry |
| Customers explicitly state a latest pickup and minimum worthwhile saving before paying | Buy timing flexibility with a bounded incentive and reserve later production | First-party checkout; approved platform surface would be separate. Compare fixed-delay offers with checked alternatives; report cost/wait/consent/holding and failed quotes. P16 supplies a bounded starting point |
| Merchant authorizes coordinated control of quote times, first-party offers and supported channel availability | Compare small joint interventions against a blanket shutdown or independent optimizers | Per-action scopes/owner limits; do not assume campaign or dispatch authority. Compare under identical budgets and accepted promises, counting declines and displaced demand |
| Observe attempted purchases, unavailable-item requests, declined orders and our own actions separately from completed sales | Distinguish slow demand from demand hidden by stockouts/throttling, and avoid learning the wrong lesson | Order intake and permissioned first-party cart/unavailable-item events. Cannot observe every unexpressed desire; use uncertainty/bounds where intent is missing. Test against completed-sales-only learning |
| Fast replay of plausible futures, with the agent observing only present evidence | Let an agent investigate incidents, compare actions, test a conditional policy and reject a fragile plan | Existing simulator/tools, with separate hidden evaluation. Compare simple rules and equal-budget search; remove noisy data and change fixtures; never expose evaluator future truth |
| Owner supplies margins, quality tolerances, maximum waits and accepted commitments | Optimize a restaurant-specific objective across channels and preserve consent/fairness | Menu/cost/settings configuration. Change the owner's declared tradeoff while keeping the situation fixed; show appropriate decisions and hard constraints, not a universally winning score |

These are not claims of exclusive functionality. New observations without action relevance may add no value. More assumed powers can make a demo less credible: preserve uncertainty, incomplete inputs, asynchronous acknowledgments, consent and original promises. Do not assume future demand, exact customer willingness or an omniscient sensor. For each claimed improvement, remove the extra input/control and check whether the improvement disappears. A plausible KDS/POS/first-party source is preferable to a capability requiring universal platform cooperation.

## Three promising feature directions from those assumptions

### 1. Coordinate decisions before committing to orders

When a station slows, the agent compares bounded plans: change the featured item, buy later pickup capacity, quote a longer lead time, or pause a supported item. All use the same station/cook/packing reservations and owner limits. It chooses a checked plan, then verifies the resulting commitments. The hypothesis is that joint decisions beat independent forecast/promotion/queue tools; it is not that each lever is new.

First test: identical synthetic arrivals/preferences/uncertainty across independent controls, a strong conventional coordinated rule, and agent-assisted coordination. Count incentive cost, lost orders, contribution, holding, original promise misses and worst waits. Existing accepted work cannot be silently moved. No automatic win; Flex's current default fixed rule already ties the checked planner in its bounded example. The current tri-workflow still needs offer-response/consent integration before this is a complete test.

### 2. Review whether our own decisions caused the apparent demand miss

Illustrative case: fulfilled sales fall while a channel is paused or an item is unavailable. A sales-only learner may infer weaker demand and reduce tomorrow's prep, creating another stockout. A decision-aware agent reads action/availability/attempted-order evidence, identifies the observation as limited, and recommends a cautious update or experiment instead of treating missing sales as zero demand. It must admit when lost demand is not identifiable.

There is a concrete opening: `gondola/future/nowcast.py` explicitly uses completed orders and notes that evening sell-outs affect its synthetic evaluation. The ledger has some received/declined/incident/action events; it does not contain every unseen customer or automatically solve this problem. Review's checked comparisons do not establish causal identification.

First test: equal underlying synthetic interest in two cases, one with a known stockout/admission interruption. Keep hidden unconstrained demand evaluator-only. Compare forecasts and next-day prep/service under completed-only updates versus availability/action-aware bounds or estimates. Use matched comparisons/randomized pilots for real causal conclusions. This would give Review a substantive learning role beyond explaining charts. Proposed, not implemented/selected here.

### 3. Investigate the one missing fact that changes the action

If the queue is explained either by a slow fryer or delayed handoffs, the appropriate intervention differs. The agent requests the relevant existing telemetry/owner fact only when it would change the checked decision, then acts or uses a conservative fallback. This builds on the earlier decision-aware information-acquisition idea; no new physical interaction is required for the first demo.

First test: hide/delay one synthetic observation; compare fixed polling, fixed questions, automatic no-question control and bounded agent acquisition. Charge for calls/interruptions and count uncertainty/failed actions. Existing sensors/events or one explicit low-burden confirmation can supply the fact; unknown physical state cannot be invented. This is an alternative experiment, not required build scope.

## How to generate more useful ideas

Use this worksheet rather than asking for ten more AI features:

1. Which fact is currently invisible, or which decision currently belongs to another system?
2. What plausible permission/integration would expose it?
3. What specific merchant decision becomes possible because of it?
4. Why does an agent's investigation/tool use/memory help beyond a threshold or optimizer?
5. What simple baseline and missing-data case could disprove the benefit?

Prioritize a small number of assumptions that make one complete episode stronger. For the hackathon, recommend coordinating offers with executable commitments as the visible story, and intervention-aware learning as the more technical extension if time permits. This is a recommendation, not a user selection or statement of uniqueness.

## Questions to take to judges/mentors

- Which parts of this loop already exist natively: courier-aware food release, kitchen-load-based promotions, all-channel task capacity and intervention-aware post-service learning?
- Which merchant inputs do you actually receive today: item/station progress, dine-in/direct/catering work, stockouts, order attempts, cancellation reasons and the outcomes of your own controls?
- If reliable all-channel station state and explicit customer timing flexibility were available, which operational decision would gain the most value?
- Which actions could a partner actually test: prep-time quotes, supported item availability, first-party later-pickup offers or approved campaign control? What latency/acknowledgment/consent restrictions matter?
- For this track, would a clearly labeled merchant-state simulation plus a demonstrable decision/commitment/learning loop be compelling? Which assumption seems least credible?

No outreach has been sent. Do not pitch the judges a hypothetical capability as a live integration or claim our demo proves customer adoption or a defensible business moat.
