# DoorDash sponsor fit, native features, and access

Checked November 6, 2026. The user asks whether DoorDash allows the proposed capacity-aware demand steering, emphasizing that DoorDash is the sponsor. Treat native product coverage, our API entitlement, and hackathon requirements as separate questions. No credentialed DoorDash call, account application, or external message was made.

## Direct answer

DoorDash supports merchant promotions and automated campaigns. We have not established that it exposes the exact station-aware shared scheduling/promotion controller, or that our team may programmatically control campaigns. The public sponsor brief fits peak-hour merchant operations, but does not establish campaign sandbox access or explicit acceptance of a mocked campaign connector.

DoorDash's own capabilities should be the first comparison for this track. Open and other vendors remain secondary context; their existence does not by itself settle sponsor fit or permission.

## What DoorDash already offers

[Smart Campaigns help](https://help.doordash.com/en-us/merchants/article/smart-campaigns) describes automated promotions using store data and customer behavior. Merchants can select eligible BOGO items or opt out, choose stores, schedules and duration, set an average weekly budget, and review/edit/end campaigns in Merchant Portal.

[DoorDash's product explanation](https://merchants.doordash.com/en-us/blog/behind-the-scenes-smart-campaigns) describes customer-specific incentives and continued learning from response. That establishes native overlap with generic autonomous marketing. The inspected material does not establish station-by-station kitchen constraints, reserved capacity for accepted orders, or cross-channel scheduling-driven item eligibility. Undocumented functionality remains unknown, not absent.

## What the public API documentation establishes

| Surface | Documented meaning | Implication |
|---|---|---|
| [Marketplace account approval](https://developer.doordash.com/en-US/docs/marketplace/overview/getting_started/setting_up_account/) | Approval-only integrations. Pending Activation is not approved to build; Development approves the specific integration type | Event sponsorship or a Google key does not establish our Marketplace permissions. Verify the actual environment/products/scopes before an adapter |
| [Integrated promotions](https://developer.doordash.com/en-US/docs/marketplace/how_to/integrated_promotions/) | Promotion redemption/funding data in incoming order payloads, including stacked discounts | Receiving this data is not campaign creation, item eligibility editing, or permission to change discounts |
| [Integrations Program](https://developer.doordash.com/en-US/docs/marketplace/overview/getting_started/preferred_integrations_new/) | Lists exclusive Campaign API creation/management/deletion access as a **new 2027** Marketplace Preferred benefit | Describes a restricted partner path, not a generally available campaign API or our current access on November 6, 2026. Special sponsor/private access remains unknown |

Restaurant campaign APIs must not be inferred from retail item-promotion endpoints. Merchant Portal controls also do not establish an API for arbitrary consumer-app recommendation slots or custom UI. Campaign update latency, cadence, propagation, and eligible item controls would need verification for a fast operational loop. Drive delivery booking does not grant Marketplace campaign/order access.

## How to position the proposed extension

An agent could use whole-kitchen commitments, station/labor capacity, stock and costs to recommend which supported offers/items are appropriate and when. DoorDash's existing campaign personalization could supply the customer-facing marketing foundation. The incremental proposed decision is which demand the kitchen can absorb while preserving current commitments.

Initial prototype options are a merchant approval/decision preview or clearly labeled simulated campaign adapter, with an explicit operational model and fair baselines. Whether that integration level meets the sponsor's expectations must be clarified. No existing native functionality should be presented as our invention, and no mock should appear as a live DoorDash campaign write.

The supplied guide describes front-house peak orders/pickups and back-house inventory/staffing/finance. Connecting a kitchen controller to capacity-aware demand is an inferred fit, not explicit sponsor approval of this detailed concept. The presentation also already demonstrated AI marketing, so generic AI offers alone would have weak differentiation.

## Questions to take to the sponsor

1. Does this track provide approved test-store access for restaurant orders/courier updates and campaign or eligible-item controls? Which products, environment, scopes and update limits are enabled?
2. If campaign writes are unavailable, is a merchant decision preview or clearly labeled simulated campaign connector acceptable for judging?
3. Does an existing DoorDash feature already use per-station kitchen constraints and commitments across ordering channels to adjust item-level promotion decisions?

These are prepared questions only; nothing has been sent. The development environment and live Gemini Ask remain usable independently of merchant API access. See [the demand-steering proposal](DEMAND_STEERING.md) and [current shortlist](LEADING_IDEAS.md).
