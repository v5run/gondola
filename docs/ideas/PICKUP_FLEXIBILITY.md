# Discounted later pickup: existing features versus our proposed extension

Checked November 6, 2026. User favors P16 and asks whether DoorDash already offers a discount in exchange for choosing a later pickup during high demand. This records the original research. The user subsequently authorized building it under a working assumption of native absence; [the tested first-party demo](../development/FLEX_DEMO.md) is complete within its stated limits. That does not change the research/access conclusions below.

## Direct answer

The broad idea of incentives for flexible/off-peak pickup is established. I did **not** verify an existing DoorDash restaurant feature that dynamically offers a specific later pickup window plus a discount because of current cross-channel kitchen commitments. Its absence is not established either; regional/account experiments and private capabilities remain unknown.

Our proposed implementation would include a customer-facing offer/acceptance/reservation mechanism and the agent's decision policy. It is not currently a verified wrapper around an existing DoorDash “later pickup discount” endpoint. It is also not a claim to have invented discounts, scheduled pickup or demand shifting.

## What primary sources establish

| Surface | Established behavior | Does not establish |
|---|---|---|
| [DoorDash pickup help](https://help.doordash.com/en-us/merchants/article/order-pickup) | Customer orders/pays, merchant accepts and sets readiness, customer collects | A benefit conditional on voluntarily choosing a later pickup window |
| [DoorDash scheduling help](https://help.doordash.com/en-us/consumers/article/can-i-schedule-a-delivery-in-advance) | Customers can choose a future delivery date/time | A conditional time-flexibility incentive or restaurant pickup-capacity negotiation |
| [Order Cart Validation](https://developer.doordash.com/en-US/docs/marketplace/how_to/order_cart_validation/) | Cart includes pickup/scheduled fulfillment data; responses support earliest pickup, capacity/slot failures, expiry and revalidation | An arbitrary customer-facing time/discount counteroffer widget, discount creation, or atomic resource reservation. Access/certification still required |
| [DoorDash Promotions](https://help.doordash.com/en-us/merchants/article/getting-started-with-doordash-promotions) | Item/order discounts and Happy Hour/Lunch offers can run on chosen schedules | A campaign schedule is not proof the discount is bound to the customer's chosen fulfillment slot or responds to shared station load |
| [Smart Campaigns](https://help.doordash.com/en-us/merchants/article/smart-campaigns) | Automated customer-behavior-based promotion optimization | Exact per-cart, kitchen-capacity-linked later-pickup bargains |
| [Sunday click-and-collect guidance](https://sundayapp.com/structuring-click-collect-to-prevent-kitchen-downtime/) | Explicitly advises nudging customers toward later pickup and offering off-peak discounts during peak pressure | Independent proof of its automated implementation or this exact DoorDash feature. It does establish prior art for the business idea |
| [Uber grocery guide](https://www.uber.com/us/en/blog/grocery-delivery-cost/) | Where offered, No Rush Delivery can reduce delivery fees for a flexible window | DoorDash functionality, restaurant self-pickup, or a kitchen-resource-aware negotiation agent |

Historical third-party/community references to DoorDash No Rush delivery also surfaced. They are adjacent leads, not sufficient verification of current official availability, a specific region, or pickup behavior. No signed-in checkout or merchant account was inspected and no order was placed.

## What we would actually add

An illustrative checkout might offer two independently feasible choices such as regular-price pickup at 18:40 or a bounded discount for pickup at 19:00. These times/prices are hypothetical; the reservation checker must derive actual feasible choices from the cart and commitments.

1. **Feasible choice and consent:** Present supported time/item/benefit choices before acceptance, with expiry. For an already accepted order, any change requires a separate explicit opt-in; silence is not acceptance and original-promise outcomes stay visible.
2. **Operational effect:** Choosing later must shift cooking/packing reservations and release useful capacity. Merely telling the customer to arrive later while preparing the food at the original time does not relieve the kitchen and can worsen holding/quality.
3. **Agent judgment:** Decide whether buying flexibility is useful, which feasible alternatives to offer and what approved incentive is justified. Include a no-incentive/no-feasible-option result; do not invent customer urgency or acceptance probabilities.
4. **Checked commitment:** On acceptance, atomically reserve the new resources and incentive budget, prevent concurrent overbooking, expire/release unused quotes, and verify the result. A queue display change or coupon alone does not implement this exchange.
5. **Learning/evaluation:** Compare fixed slot limits and fixed later-pickup discounts with the agent under the same budgets. Measure actual preparation shifts, service across channels, original/revised promises, incentives, contribution, holding, customer acceptance and interaction burden. Customer-response fixtures remain synthetic until measured.

This is a specific operational/customer workflow plus agent decision-making. Whether that exact combination is missing in DoorDash remains a sponsor question. Its individual components and general commercial idea are not new.

## Integration boundary and sponsor question

We have not verified permission or a public endpoint to insert our custom per-order bargain into DoorDash checkout, create the needed conditional discount, or renegotiate a paid Marketplace order. [Integrated Promotions](https://developer.doordash.com/en-US/docs/marketplace/how_to/integrated_promotions/) supplies received discount/funding data, not that action. The [Integrations Program](https://developer.doordash.com/en-US/docs/marketplace/overview/getting_started/preferred_integrations_new/) describes exclusive Campaign API control as a new-2027 Preferred benefit; it does not grant team access or custom checkout UI.

The credible prototype is a first-party merchant web checkout with labeled platform/campaign adapters, presented as a proposed DoorDash-integrated/native extension. Approved OCV capacity/timing data may eventually be one piece, not a confirmed end-to-end adapter. Its timeout behavior also permits checkout to proceed if validation has not returned, so it must not be treated as an unconditional reservation guarantee.

Prepared sponsor question: **“Do you already offer a customer a discount conditional on choosing a later restaurant pickup slot based on current kitchen load? If so, can partners set the eligible slots/incentive and reserve that capacity, and what checkout/order-change interface is available?”** No question/message has been sent.

## Current status

P16 is **implemented and verified in a bounded first-party web demo**: [walkthrough and evidence](../development/FLEX_DEMO.md), [remaining-work tracker](../development/FEATURE_COVERAGE.md). Regular/later quotes, declared customer constraints, real Gemini tools, moved production allocations, atomic customer acceptance, expiry/stale/concurrency/idempotency/decline checks and durable receipts work. No actual payment or external merchant connection. One-meal/frozen planning state, rather than continuous service or broad negotiation. Full Python suite: 151 passed; 12 browser checks and production build passed. Root source index S89-S93 plus S76/S78-S80 still govern prior-art/access claims. No live DoorDash entitlement or business uplift is established.
