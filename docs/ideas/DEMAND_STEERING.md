# Station-aware demand steering

November 6, 2026. The user favors the promotion idea from P01 and asks whether Open is popular and whether we can build a better-integrated version. This promotes the idea to a user-favored leading candidate. It is not yet a completed feature or an approved full implementation specification.

## What we can establish about Open

**Sponsor-first update:** [DoorDash native features and access](DOORDASH_FIT_AND_ACCESS.md) is the primary comparison for the track. DoorDash already offers Smart Campaigns with automated personalized promotions, schedules, budgets and BOGO item selection. Our station-aware controller remains a proposed extension; campaign API entitlement and mocked-connector acceptance are unconfirmed. The following Open research is secondary context.

Public research found a documented commercial footprint, but no reliable total customer count or market-share figure. The absence of a number in the reviewed sources is not evidence that adoption is low.

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| [Open homepage](https://www.getopen.com/) | Names/displayed customer sites include LOQUI, Square Pie Guys, HomeState, and others; markets an integrated ordering/marketing/CRM suite | Verified count of active/paying locations, market share, or independent product-performance results |
| [Toast's Open integration guide](https://support.toasttab.com/en/article/Get-Started-With-the-Open-Integration) | Official U.S.-only partner integration for orders, menus, loyalty/gift cards and associated ordering/marketing services | Wide adoption or direct kitchen-station scheduling integration; marketing growth figures are not an independent study |
| [KavehG's published policy](https://kavehg.com/privacy-policy/) | A merchant's own statement identifies GetOpen/Acelerate as its ordering/loyalty provider | Overall adoption or operation of the station-aware feature proposed here |
| [Open marketing decision-engine description](https://www.getopen.com/blog/restaurant-ai-decision-engine) | Explicitly claims kitchen load, backlog, stock, prep shifts, and environmental signals inform autonomous marketing | Independently verified implementation/performance or our exact shared station-by-station capacity/reservation model |

Open already presents itself as an integrated suite. We should not assume it has weak integration because the user has not heard of it. The exact depth of its kitchen/marketing coordination is unknown from the inspected public material. Its broad overlap is a baseline, not a reason to discard our candidate.

## Proposed Gondola responsibility

Use the same operational state to plan incoming demand and fulfill accepted work. Forecasting informs expected demand and resource needs; a kitchen scheduler reserves capacity for existing commitments; a demand agent selects supported recommendations/offers that fit the remaining capacity, stock, and owner policy. New orders update that state, and interventions are reviewed/revised as conditions change.

This connects the existing forecast foundation with the proposed scheduler and marketing capability. The real-time scheduler, station model, and demand steering are not yet implemented in the audited checkout.

**Illustrative episode:** The fryer is overloaded while another preparation station and sufficient shared labor have spare capacity. A generic popular-item promotion would add pressure to the fryer. Gondola considers featuring approved alternatives that use available resources, or doing nothing. If conditions recover or another station becomes constrained, it revises the recommendation. All examples and future demo response data must be labeled synthetic until actual evidence exists.

## Integration details worth demonstrating

- **Committed capacity first:** Preserve accepted orders, service promises, and maximum waits before considering new demand. Account for shared labor, packing, ingredients and dependencies, not just isolated equipment utilization.
- **Specific supported actions:** Start with first-party recommendations, featured approved items, and bounded offers. An available item need not be discounted to be featured. Marketplace menu/promotion publication depends on verified API scopes; no such entitlement is currently established.
- **Merchant economics and limits:** Use explicit ingredient/channel/discount costs, stock assumptions, budgets, eligibility and campaign limits. Revenue alone is insufficient. A valid plan can choose no promotion.
- **Reaction to changing facts:** New orders, station slowdown, stock changes and an ending rush invalidate an offer's assumptions. Avoid rapid menu/promo changes and protect already accepted terms.
- **Learn from interventions:** Track which actions were taken and distinguish modeled/customer-response assumptions from observed behavior. Ordinary sales feedback alone does not identify an offer's causal effect.

The agent can interpret changes, develop candidate interventions, and investigate their results; deterministic tools validate feasibility/costs and compute scheduling. Agent-generated policies remain a potential later extension rather than a prerequisite for every control decision.

## First browser test and fair comparison

Use a small approved menu, explicit item/station/labor/ingredient mappings, an order queue with pickup commitments, and a first-party menu preview. Inject a station slowdown or forecast change. Show evidence, candidate choices, the supported menu/offer update, and what remains reserved for accepted orders. No external campaign or purchase is required.

Compare: (1) scheduling alone, (2) independent stock/margin-aware promotion plus scheduling, and (3) shared-state steering plus scheduling. Vary modeled customer response, including weak conversion, cannibalization and no profitable intervention. Keep the evaluator's outcomes/held-out cases inaccessible to decision tools.

Report contribution after defined costs/discounts, on-time commitments, worst pickup wait, lost/unfinished orders, stock use and promotion spend. A simulator can test feasibility and behavior under its assumptions; it cannot establish real conversion uplift or claim we outperform Open. A credible merchant pilot/experiment would be required for business-impact claims.

## Current recommendation

Advance the integrated scheduling/steering candidate to a concrete scenario and data contract before building. The opportunity hypothesis is that coordinated decisions can improve contribution while preserving service. Open's actual adoption and the breadth/depth of competing implementations remain unknown; our demonstration should earn its value claim directly.
