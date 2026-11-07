# Gondola: Data Access & Integrations Feasibility

Checked 2026-11-04 against current vendor docs. Where a doc did not say something, this report says "unverified".

## Verdict

**Feasible as a demo, but not as specified.** The in-store half (Square cash drawer, orders, catalog, inventory) is real and available in a sandbox. The delivery-app money half is not available on the night of the shift. DoorDash's official reporting data refreshes once a day for the previous day. Uber says its data takes up to 72h to settle. We found no public Grubhub financial API. So the "Close shift" reconciliation tonight has to be an **estimate**: POS order totals x contracted commission rates. True-up against real payout data happens 1-3 days later. Pitch it as two steps, "estimated tonight, verified on payout", and the core idea still holds.

## What works

- **Square Cash Drawer Shifts API (read-only).** `ListCashDrawerShifts`, `RetrieveCashDrawerShift` and `ListCashDrawerShiftEvents` take the `CASH_DRAWER_READ` scope. Fields include `opened_cash_money`, `cash_payment_money`, `cash_refunds_money`, `cash_paid_in/out_money`, `expected_cash_money` and `closed_cash_money` (the counted amount, set when an employee audits the drawer). Timestamps are `opened_at`, `ended_at` and `closed_at`. Note that `expected_cash_money` "can be negative if employees have not correctly recorded all the events".
- **Square sees DoorDash orders** when DoorDash is integrated directly with Square. Orders appear in Square reports, and `order.created`/`payment.created` fire with `source.name` ≈ "Doordash". "86-ing an item will make the item unavailable on DoorDash," and so does marking stock unavailable.
- **Square sold-out via API (indirect).** Set `track_inventory=true`, then use `BatchChangeInventory` to bring the count to 0, and `location_overrides.sold_out` flips to true. Changes arrive through the `catalog.version.updated` webhook.
- **Toast standard API access is real.** A restaurant employee with RMS Essentials+ and the Manage Integrations permission can mint credentials. Scopes include `orders:read`, `labor:read`, `cashmgmt:read`, `menus:read` and `stock:read`, all read-only. Cash entries include `CLOSE_OUT_EXACT/OVERAGE/SHORTAGE` and are filtered by `businessDate` (yyyyMMdd).
- **The DoorDash Reporting API has exactly the columns we want.** `TRANSACTION_DETAIL` v4 has `transaction_type`, `commission`, `commission_tax`, `error_charges`, `adjustments`, `marketing_fees_including_any_applicable_taxes`, `payout_id`, `payout_date`, `credit`, `doordash_order_id` and `external_id`. `PAYOUT_SUMMARY` adds `net_payout`. `ORDER_DETAIL` maps `dd_order_number` to `mx_order_number`/`external_order_id`, which is the join key to POS orders.
- **The DoorDash Marketplace item-status API** (`PUT /stores/{id}/items/status`, `is_active=false`) is documented as "immediate". Limits are 480 req/min and 40 items per call. DoorDash also polls the provider for 86'd items after every menu pull or push.
- **Twilio SMS, PDF generation and the LLM agents** are fully under our control.

## Where it fails / risks (ranked by severity)

1. **CRITICAL: No same-night DoorDash fee/payout data.** Reporting API reports "refresh once daily at 7 PM PST and cover the previous day". Monday's close-out can see Monday's DoorDash fees on Tuesday evening at the earliest. Error charges and adjustments can land in later payouts. Report Builder docs do not list columns or freshness (unverified). They only say Financial reports include "transactions, error charges/adjustments, and payouts".
2. **CRITICAL: The POS does not carry commissions.** A Square community thread (Aug–Sep 2025) says DoorDash told the merchant fee sync is "not possible" in the direct integration. Square docs don't mention fees. In the new integration, DoorDash orders come into the Orders API as PICKUP fulfillments, and delivery can only be spotted through a `Courier Name` in the fulfillment `note`. That is fragile parsing.
3. **HIGH: The Reporting API is gated.** It is "not yet generally available": you fill in an early-access form, wait for developer-account approval, map stores to a JWT, and then wait another 1-2 business days. The only partners named are ItsaCheckmate and Nextbite, plus US/CA/AU. This cannot be done in 36-48h.
4. **HIGH: Middleware financials are gated or missing.** Deliverect's order model has `deliveryCost`, `serviceCharge`, `tip`, `taxRemitted` and so on, but **no commission/payout fields**. Its Reporting Webhooks require a signed agreement with service charges. Otter lists Finance and Reports endpoints (payouts), but credentials and the base URL "are provisioned through an Otter account representative", and the API is flagged non-public. Neither gives instant access. Cuboh was acquired in 2024, so drop it from the deck.
5. **HIGH: Uber Eats and Grubhub.** Uber reporting (Payment Details CSV) "may require written approval", says data can take **up to 72h** to settle with disputes after 30 days, and recommends daily overnight polling. Grubhub's developer features cover orders, menu and 86-ing only. **We found no public payout API.**
6. **MEDIUM: Toast is a dead end for a hackathon.** The sandbox is limited to partner and custom integrations; standard-access users "can't use the sandbox". The sandbox also only runs 9am–6pm ET. The partner application goes through BD review ("it can take some time"). Standard access is read-only, so **Gondola cannot 86 items through Toast** without becoming a partner.
7. **MEDIUM: Square cash drawer.** There is **no webhook** (feature request Oct 2024, unanswered), so we have to poll. Shifts can only be opened on a POS device, not created through the API. In the sandbox the endpoints will probably return nothing unless we can open a drawer (unverified). `closed_cash_money` only exists once the drawer is audited (CLOSED). A manager who taps "Close shift" before counting gets no counted value.
8. **MEDIUM: Square sold-out has no direct write.** We could find no documented API to mark an item sold out while its count is > 0. Gondola has to drive inventory counts, and that interferes with stores that don't track inventory. A 2022 thread also reports that sold-out did not persist in the sandbox.
9. **LOW: The "one integration provider per store" rule is unverified.** DoorDash's POS overview describes direct vs middleware integrations but states no limit. It is plausible in practice; don't cite it as fact to judges.
10. **LOW: Latency of 86-ing through middleware to DoorDash isn't published.** DoorDash says "immediate"; no SLA figures exist.

## Fixes

- **Change "reconcile" into a two-step flow.** (a) Tonight: estimate each app's net from POS orders × the store's contracted commission %, and flag outliers such as voids, refunds and cash variance. (b) On the next refresh: ingest the DoorDash `TRANSACTION_DETAIL` CSV (or Uber Payment Details), join on `external_id` ↔ POS order ID, and surface error charges and adjustments. Report true-ups in the next day's report.
- **History and true-up:** the merchant uploads Report Builder CSVs manually. Build the parser against the documented Reporting API v4 schema and treat the Report Builder column names as needing confirmation. **Ask the DoorDash sponsor for a sample Financial export and a test store.**
- **Classify delivery orders in Square** by `source.name` first, then by `fulfillment.note` heuristics. Accept it as best-effort.
- **86-ing in the demo:** Square sandbox Inventory → count 0 → `sold_out=true`, shown in a mocked "DoorDash menu" panel. Say plainly that in production the propagation to DoorDash happens through Square's DoorDash integration.
- **Cash drawer:** poll `ListCashDrawerShifts` at "Close shift". If state ≠ CLOSED, prompt the manager to count the drawer, or have them type in the count.
- **Drop Toast, Grubhub and Cuboh from the live demo.** Show them as roadmap items with "partner-gated" labels.

### Demo: real vs mocked (36-48h)

| Component | Status |
|---|---|
| Square sandbox Orders/Catalog/Inventory/Labor + webhooks | **Real**, available right away |
| Square cash drawer shifts | Real API, **data likely mocked** (needs POS device) |
| DoorDash orders inside Square | **Mock**: create sandbox orders with source "DoorDash" |
| DoorDash fees/error charges/payouts | **Mock CSV** in documented v4 `TRANSACTION_DETAIL` schema |
| Uber Eats / Grubhub payouts | **Mock** |
| DoorDash/Uber/Grubhub 86 APIs | **Mock** (all partner-gated, no instant sandbox) |
| Toast, Deliverect, Otter | **Mock / slides only** |
| Forecast, prep plan, PDF, Twilio SMS | **Real** |

## Sources

- Square CashDrawerShift model: https://github.com/square/connect-javascript-sdk/blob/HEAD/docs/CashDrawerShift.md
- Square Cash Drawer reporting: https://developer.squareup.com/docs/cashdrawershift-api/reporting
- Square: no cash drawer webhook: https://developer.squareup.com/forums/t/feature-request-add-a-webhook-for-opening-and-closing-a-cash-drawer/19098
- Square: manage DoorDash orders: https://squareup.com/help/us/en/article/7148-manage-doordash-orders-with-square
- Square: DoorDash integration and sold-out: https://squareup.com/help/us/en/article/8559-manage-your-doordash-integration-with-square
- Square forum: DoorDash order webhooks/source.name: https://developer.squareup.com/forums/t/webhook-events-for-doordash-orders/11736
- Square forum: new DoorDash integration orders as PICKUP: https://developer.squareup.com/forums/t/new-doordash-integration-data/23865
- Square community: DoorDash fees don't sync: https://community.squareup.com/t5/Orders-Menu-Items-Catalog/Doordash-sync-fees-to-Square-for-accurate-reports/td-p/804744
- Square sold-out status: https://developer.squareup.com/docs/inventory-api/monitor-sold-out-status-on-item-variation
- Square sandbox sold-out bug: https://developer.squareup.com/forums/t/marking-a-variation-sku-as-sold-out-will-not-stick-in-sandbox/6414
- Toast standard API access requirements: https://doc.toasttab.com/doc/devguide/devApiAccessRequirements.html
- Toast standard access scopes: https://doc.toasttab.com/doc/devguide/devApiAccessScopes.html
- Toast environments/sandbox: https://doc.toasttab.com/doc/devguide/apiEnvironments.html
- Toast partner application: https://support.toasttab.com/en/article/Customer-Requesting-API-Credentials
- Toast cash management API: https://doc.toasttab.com/doc/devguide/apiUsingCashManagementApi.html
- DoorDash Reporting API: available reports: https://developer.doordash.com/docs/reporting/overview/available_reports
- DoorDash Merchant Pick report schemas: https://developer.doordash.com/docs/reporting/overview/reports/marketplace_merchant_pick
- DoorDash Reporting API access: https://developer.doordash.com/docs/reporting/how_to/get_access
- DoorDash Reporting API help (refresh 7 PM PST): https://help.doordash.com/en-ca/merchants/article/how-can-i-access-the-doordash-reporting-api
- DoorDash Reporting API announcement: https://about.doordash.com/en-us/news/doordash-reporting-api
- DoorDash Report Builder: https://help.doordash.com/en-ca/merchants/article/merchant-portal-reports
- DoorDash payout and statement: https://merchants.doordash.com/en-us/learning-center/payout-and-monthly-statement
- DoorDash POS integration overview: https://merchants.doordash.com/en-us/learning-center/pos-integrations
- DoorDash Marketplace item status: https://developer.doordash.com/docs/marketplace/how_to/item_status
- DoorDash Marketplace overview (not GA): https://developer.doordash.com/en-US/docs/marketplace/overview
- Deliverect channel order model: https://developers.deliverect.com/page/channel-orders
- Deliverect reporting webhooks: https://developers.deliverect.com/reference/reporting-webhooks
- Otter API catalog (third-party index): https://raw.githubusercontent.com/api-evangelist/otter/refs/heads/main/apis.yml
- Uber Eats reporting: https://developer.uber.com/docs/eats/guides/reporting
- Uber Eats API intro: https://developer.uber.com/docs/eats/introduction
- Grubhub developer feature overview: https://grubhub-developers.zendesk.com/hc/en-us/articles/115002660546-Feature-Overview
- Cuboh acquisition (2024): https://app.mergerlinks.com/transactions/2024-03-28-cuboh
