# Feature coverage against the discussion

Checked November 6, 2026 against saved proposals and the implementation. This is a scope/status audit, not a new implementation or authorization to build every brainstormed alternative. [Demo guide](RUSH_DEMO.md) records verification and measurements.

The complete earlier vision is **not** implemented. The current new demo combines shared scheduling, capacity-aware first-party offers, bounded policy experiments and verified simulated actions. The inherited forecasting/close/planning screens remain available separately.

| Discussed feature | Status | Actual behavior / boundary |
|---|---|---|
| V's dynamic cross-channel order prioritization | Implemented in synthetic replay | Replans unstarted work using promises, courier estimates, remaining effort and shared cook/station/packing capacity. In-progress work remains assigned. Heuristic scheduling; no live order feed or globally optimal/just-in-time scheduling claim |
| Kitchen-aware promotions/demand steering | Implemented in synthetic replay | Checks approved items/discounts against reservations, stock, contribution, budget and reserve; features an item or pauses in the simulated first-party menu. No real DoorDash campaign writes or general base-price optimization |
| Demand forecast informing stocking and staffing | Existing prototype, partial integration | Inherited synthetic sales/weather/event data, LightGBM forecasting, prep/staff calculations and forecast caches. Rush reads an existing forecast artifact to set reserve uncertainty; it does not implement live external-signal collection or a unified forecast-to-staff/stock/rush feedback system |
| Learn when estimates miss | Partial | Completed simulated cooking tasks update effort estimates; policy trials return actual modeled feedback. No autonomous demand-miss investigation, causal attribution, customer-response learning or end-to-end stock/staff feedback |
| Agent develops better operating policies | Bounded initial implementation | Gemini tests distinct parameter sets and submits one for independent evaluation against default/conventional search. It does not generate new executable rules, invent new features or synthesize solvers. First real submission failed qualification; no demonstrated superiority over conventional tuning |
| Autonomous operations agent | Partial | Deterministic control adapts throughout replay. Real Gemini intervention and policy-lab jobs are started from UI/API and execute their tool loops autonomously. No continuous background LLM supervisor, ongoing live event subscriptions or scheduled daily mission |
| Explicit operating limits and verified follow-through | Partial, local demo | Typed offer limits/checks and durable jobs/action receipts are implemented. No general natural-language owner mandate, external acknowledgment/retry workflow, persistent cross-system obligations or supplier/staff recovery engine |
| Forecast/weather/event/traffic signal discovery | Unbuilt beyond inherited synthetic features | No agent discovers/connects/evaluates new external demand signals; no live Maps, traffic, weather or event API |
| Learn the owner's soft tradeoffs | Unbuilt proposal | Current objective weights/limits are configured. No preference elicitation, preference model or uncertainty-driven owner questions |
| Joint cooking/readiness/courier-dispatch feedback | Unbuilt proposal | Courier arrivals are external simulated inputs; no model of dispatch responding to our readiness estimates or approved outbound readiness updates |
| Agent creates a missing analytical tool | Unbuilt alternative | Capacity checker/scheduler are developer-authored. The running agent cannot create or install a new solver/tool |
| Negotiate feasible group orders / later pickup | Unbuilt alternative | No buyer negotiation, quote acceptance/expiration, counteroffer UI or admission/quote reservation workflow |
| Live merchant/platform integration | Not configured/tested | DoorDash/Uber/POS/KDS input/output adapters remain future work. Real Google model tool use is separately verified; it supplies no merchant API entitlement |

Broader supplier-delay/staffing-change recovery and selective owner escalation were earlier manager-package proposals; they were not built in this Rush milestone. Count Next, Close Detective and the earlier broad idea pool remain historical alternatives, not hidden implemented features.

## Largest remaining gap against the original baseline

The discussed autonomous loop was: gather merchant sales/customer data plus local signals, predict demand, update stock/staff plans, observe misses, investigate them and improve future plans. The repo has parts of forecasting/planning on synthetic data and the new operational replay, but that full continuously operating loop is not connected or verified.

The next scope decision should identify which missing outcome to demonstrate. Do not describe current parameter tuning as arbitrary policy invention, ordinary completion updates as causal demand learning, or local replay as a live always-on merchant agent.

## Evidence pointers

- [Current demo and verification](RUSH_DEMO.md)
- [Leading ideas and original alternatives](../ideas/LEADING_IDEAS.md)
- [Additional angles: preference learning, readiness coupling and intervention effects](../ideas/IDEA_POOL.md)
- [Inherited functionality audit](FUNCTIONALITY_AUDIT.md)

Implementation inspected: `gondola/rush/engine.py`, `agents.py`, `evaluation.py`, `models.py`; `gondola/api/rush.py`; and their browser/API contracts. No new model calls, tests, merchant actions or product code changes were needed for this documentation audit.
