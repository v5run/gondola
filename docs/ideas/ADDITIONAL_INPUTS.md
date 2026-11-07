# Additional inputs that change what the agent can decide

November 7, 2026. Follow-up to [judge pitch and capabilities](JUDGE_PITCH_AND_CAPABILITIES.md). These are proposed input assumptions and experiments, not implemented integrations, established novelty or a new build selection. Prefer information about intent, forthcoming work and transformations over adding unrelated forecast features.

## 1. Conditional purchase intentions before an order exists

Input: customers explicitly request a constraint set, for example two meals under a budget, several acceptable dishes and a pickup deadline, with permission to receive a proposal. First-party carts, requested slots and structured counteroffers can supply aggregate intent. This does not assume access to other platforms' browsing histories or exact willingness to buy.

New decision: an agent groups compatible requests, compares approved meal/time combinations against resource/ingredient constraints, and proposes a feasible offer to the appropriate customers. Customers still accept separately; intentions are not committed demand and proposals do not consume stock or count as sales. This extends P16 from a fixed one-item cart into useful negotiation over item/time/price, rather than simply adding a signal to a forecaster.

First test: a small synthetic pool of requests with different allowed items/deadlines, compared with fixed-menu offers. Measure conversion only from declared synthetic responses, incentive cost, feasible accepted work, customer wait and unserved requests; reserve atomically on acceptance. A web buyer form makes the input concrete and inspectable. Strong candidate for our visible differentiation; exclusivity is not established.

## 2. Kitchen work that exists but has not been fired

Input: seated party counts, held courses, reservations/check-ins and future catering commitments, separated by certainty. A quiet active ticket queue can coexist with substantial imminent demand. Held ordered entrees are stronger evidence than a seated party that has not ordered.

New decision: protect appropriate future station/cook/packing capacity before featuring an offer that would occupy it. Do not assume every reservation arrives or every seated guest chooses a known dish.

Grounding: [Toast course pacing](https://doc.toasttab.com/doc/platformguide/adminKitchenDiningRoomReference.html) describes held/fired courses; [selection schema](https://doc.toasttab.com/openapi/orders/tag/Data-definitions/schema/Selection/) documents fulfillment states. [OpenTable partner APIs](https://www.opentable.com/restaurant-solutions/api-partners/) describe reservation integrations and a request-access sandbox. These support plausible input routes, not our access or guaranteed arrival/order predictions.

First test: identical active delivery queues in two episodes, one with a large known held course. Compare accepted commitments/lateness/lost orders against a queue-only controller. The useful extra information should change the action. No new hardware or continuous staff entry is required for the fixture demo.

## 3. Progress of an event or journey, rather than its scheduled time

Input: match period/overtime, an actual venue release update, or predicted transit arrival with timestamp/uncertainty. A calendar only says an event exists; its changing progress can alter when demand arrives.

New decision: revise future capacity protection and proposals as the arrival window moves. An opted-in customer's pickup proposal can depend on a bounded arrival window; already accepted promises cannot be silently moved. Event/transit data does not establish that those people will purchase.

Grounding: [GTFS Realtime](https://gtfs.org/documentation/realtime/reference/) supports predicted stop arrival/departure, delays and freshness. It does not give restaurant purchase intent, guarantee an agency publishes every field or establish a sports/venue feed. Use labeled fixtures for unsupported event states.

First test: normal finish versus overtime/transit delay with the same scheduled event. Compare calendar-only, a simple event-adjustment rule and agent coordination, including cases where the event never produces demand. Attractive demonstration input; forecasting from it alone is not claimed novel.

## 4. The preparation state and remaining useful life of ingredients

Input: batch records distinguishing raw/preparing/ready items, expected readiness, remaining quantity and owner-configured holding/expiry limits; approved recipe dependency graph and shared prep components.

New decision: identify which approved menu combinations are feasible now or later, and which demand would use a ready component without worsening the binding resource. Equal stock counts can mean very different meal capacity. This can support feasible bundle proposals and selective preparation plans.

Grounding: [Square inventory webhooks](https://developer.squareup.com/docs/inventory-api/webhooks) report catalog-item quantity changes. They do not by themselves supply cooking-stage progress, batch age, recipe dependencies or food-safety limits. Those need existing prep records/configuration or labeled fixtures; no new sensor deployment is assumed.

First test: identical counts/queue with different batch readiness. Compare a count-only offer rule against resource-and-prep-aware choices. Preserve owner-defined product rules; do not invent safe holding times. Waste-based discounting is established in general; the hypothesis is better feasible commitments using preparation state.

## 5. Supply commitments and changes to those commitments

Input: approved purchase orders, supplier acknowledgments, promised arrival windows and notices of shortage/substitution. A purchase order is not proof ingredients have arrived. This can be represented as structured fixtures or permissioned supplier documents/messages; no account access is implied.

New decision: revise tomorrow's feasible menu/prep/offer plan when an expected component becomes unreliable; use only preapproved alternatives and preserve paid commitments. Agents can turn varied supplier language into a proposed constraint update, with confirmation where ambiguity matters.

First test: a delivery confirmation versus a delay notice with unchanged on-hand counts. Compare planning from stock plus expected deliveries with planning that distinguishes confirmed/uncertain/missing supply. Show changed recommendations and remaining unknowns, not an automatically solved physical shortage. This is a broader Future/Review direction and may dilute a short peak-hour demo.

## 6. Explicit reasons customers reject an offer

Input: optional structured feedback/counteroffers such as later time unacceptable, preferred item unavailable, saving insufficient, or no purchase today. Abstaining and silent abandonment remain unknown; do not infer a preference from silence.

New decision: revise the next proposal on the relevant dimension and evaluate which offers failed because of price, timing or item mismatch. Store what was offered and available, not merely final purchases.

First test: two customers decline the same offer for different declared reasons. A useful agent should ask/propose different things, while avoiding repeated contact and excessive discounting. Compare fixed next offers with bounded reasoning; no real outreach is sent. This complements conditional-intent inputs rather than constituting another independent product.

## Recommendation and stopping rule

For a visible web demo, prioritize conditional purchase intentions plus un-fired kitchen work: the agent negotiates demand into capacity that is actually available after protecting upcoming commitments. Event progress is a useful changing circumstance if one more input improves the story. Supplier planning is a separate broader direction.

Before choosing a new integration, ask whether removing this input changes a consequential action under identical circumstances. Compare with a simple rule; include missing/stale signals and customer rejection. These are differentiation hypotheses, not evidence of features DoorDash or another vendor lacks. Keep the operating controller blind to future simulator truth and disclose fixtures.
