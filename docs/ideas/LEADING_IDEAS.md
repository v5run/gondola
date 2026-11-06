# Current leading ideas

Updated November 6, 2026. **The user authorized building Rush Control:** shared kitchen scheduling, station-aware demand steering, observed effort learning, a live intervention agent and bounded policy experiments. [Implemented demo, measurements and production path](../development/RUSH_DEMO.md) is now the current entry point. The shortlist below preserves research history; other ideas and the twelve-ticket manager backlog are not automatic build scope.

To generate more: [repeatable ideation playbook and reusable prompts](IDEATION_PLAYBOOK.md). [The wider idea pool](IDEA_POOL.md) records new angles and variants with first tests and evidence limits; entries there are not automatically leading candidates.

**Selected direction:** Station-aware demand steering integrated with forecasting and shared kitchen reservations. [Product/adoption research](DEMAND_STEERING.md) explains the hypothesis. The implemented simulation exposes measured service/revenue tradeoffs; it does not establish real merchant benefit or feature exclusivity.

**DoorDash track check:** Start with [native capabilities, API access, and sponsor fit](DOORDASH_FIT_AND_ACCESS.md). DoorDash already offers automated Smart Campaigns. Station-level coordination is unverified; our campaign API access and the required demo integration level are also unconfirmed.

## Existing foundation

Historical sales/guest counts plus weather, events, and other signals can inform demand, stocking/prep, and staffing. Updating forecasts as actuals arrive is already an established product category. Our repo has synthetic-data forecasting/backtests/calibrated ranges and prep/staff calculations; continuous live collection and autonomous production learning are not established. A real Gemini Ask tool round trip is verified.

Keep three kinds of learning distinct: updating forecasts, investigating useful new signals, and inventing/testing better decision policies.

## Candidates

| Idea | Proposed capability | Current judgment | First feasibility gate |
|---|---|---|---|
| **Station-aware demand steering** | Choose supported recommendations/offers using the same capacity, inventory, cost, and commitments model as scheduling | User-favored; DoorDash native Smart Campaigns overlap exists; exact controller/access unverified | Shared-state steering must improve defined outcomes over independent stock/margin-aware promotion and scheduling while protecting accepted commitments |
| **Agent develops better operating policies** | Generate executable decision rules, test them, inspect failures, revise, and independently evaluate | Preferred assistant technical investigation; user responded positively, not selected | Beat a tuned conventional rule and equal-budget search on unseen conditions without altering the evaluator or reading hidden truth |
| **Agent builds a missing analytical tool** | Formulate and validate a small solver for a previously unsupported business constraint | More technically ambitious | Solve an unseen bounded capacity case, satisfy independent feasibility/quality checks, and identify an impossible case |
| **Merchant agent negotiates feasible orders** | Negotiate approved menu, quantity, timing, and price while reserving committed capacity | Commercial alternative; closer quoting competition and buyer/access dependencies | Improve feasible completed orders over fixed quoting while preventing double booking and broken commitments |
| **Adaptive cross-channel kitchen scheduling** | Coordinate DoorDash/Uber/pickup preparation using promises, courier estimates, station capacity, and food-holding limits | Teammate idea the user likes; concrete demo candidate, with direct existing-product overlap | Beat FIFO **and** deadline/slack-based rules across varied scenarios while protecting fairness and in-progress work |

Kitchen scheduling and demand steering can provide concrete problems for policy development: an agent develops and tests policies while a fast engine runs validated decisions. These combinations are proposed, not implemented or proved novel. Do not build all candidates at once.

## What each could look like

**Policy development:** The agent proposes a rule, discovers that it reduces cancellations by withholding too many profitable orders, revises it, and faces a held-out rush. No guaranteed winning candidate. Agent-generated code/policies cannot modify the scorer or access future/evaluator truth. A simulator win is not observed merchant benefit.

**Missing tool:** The owner asks whether a large order can be fulfilled with a prep station unavailable. Given explicit recipe/station/task data, the agent builds and verifies the missing capacity model. Unknown physical facts cannot be invented. Reference: [ORAgentBench](https://oragentbench.github.io/).

**Negotiation:** A buyer requests 30 meals by noon. The merchant proposes a feasible approved alternative or later slot and reserves capacity after acceptance. Initial transactions would be clearly simulated. Quoting itself has existing competition; reservations and autonomous negotiation need independent evaluation.

**Kitchen scheduling:** Twenty-seven orders arrive across channels; an ETA changes or a station slows. The controller revises unstarted work, preserves existing promises and a maximum wait, and keeps food completion aligned with pickup. See [the full assessment, data requirements, and demo plan](ORDER_SCHEDULING.md).

## Competitive and evidence boundaries

- Demand forecasting and ordinary adaptive learning: [Fourth](https://uk.fourth.com/article/ai-forecasting-identify-the-insights-that-drive-profitable-actions), [ClearCOGS](https://hs.clearcogs.com/en-us/faq/does-clearcogs-work-for-restaurants-with-seasonal-or-event-driven-demand).
- Broad autonomous back-office/onboarding: [Marble](https://joinmarble.ai/).
- Driver-ETA-based cooking sequence/start times: [Captain](https://www.captain.ai/solutions/kitchen). Cross-channel aggregation: [Otter](https://www.tryotter.com/products/order-management).
- Algorithm-development inspiration: [AlphaEvolve](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/). We are not using its implementation or claiming its results.

Vendor descriptions establish overlap, not independently measured quality. No current candidate has a measured advantage or proven exclusivity. Real DoorDash/Uber merchant access remains unknown. No partner API scope is implied by possessing a Google model key.
