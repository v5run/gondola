# Gondola "service protection": is the pain real, and does it fit DoorDash's incentives?

Researched 2026-11-05. **Coverage caveat:** the web page fetcher hit its usage limit partway through. Every claim in the table marked **Verified** comes from a page that was actually read. Items marked **Lead** are search-result titles or URLs that were *not* opened and need checking before anyone quotes them. Grubhub and the Reddit/forum threads were not read at all.

## Verdict

**The pain is real, and DoorDash measures it and penalizes it. The size of the dollar loss is moderate, not huge, and the control features already exist.**

- DoorDash names "items listed as available but out of stock" and "accepting orders when the store is too busy" as causes of *avoidable cancellations*. These are the two problems Gondola targets. The merchant is **not paid** for an order cancelled because an item was unavailable. Missing items cost the merchant 25–100% of the item price.
- The avoidable-cancellation goal of **under 1.1%** is real, but it appears in DoorDash's *Unhealthy Store Operations* help article (seen on the Canadian help site). DoorDash's Most Loved page publishes **no numeric thresholds**; it says the benchmarks are in the Merchant Portal. Pitch it as "DoorDash's stated goal is under 1.1%," not "the Most Loved cutoff is 1.1%."
- The best cost data comes from vendors (Otter): 1.5–3% of orders cancelled, about $150–300 a week for a restaurant doing $10k a week. That figure covers *all* cancellations, not just stockouts. Treat it as a ceiling on what Gondola can directly recover.
- **Skeptical point:** DoorDash already offers Busy mode, Pause, and out-of-stock toggles. Otter and Deliverect already sync 86s and pauses across apps. Gondola's edge has to be **prediction**: pausing *before* the sell-out or the overload, automatically. One-click control is already a solved problem.
- Off-hours and closing-time data fits a "stock runs out late in service" story: the last hour before closing has 18% of orders but 28.6% of cancellations. Otter does not split this by cause, so that link is our inference.

## Evidence table

| # | Claim | Number | Source | Strength |
|---|---|---|---|---|
| 1 | DoorDash avoidable-cancellation goal | under 1.1%; missing/incorrect under 1% | [DD Unhealthy Ops Rates (en-CA)](https://help.doordash.com/en-ca/merchants/article/unhealthy-store-operations-rate) | Verified, official. The US page was not checked. |
| 2 | Combined "unhealthy ops" rate (avoidable cancellations + missing/incorrect) | 15–25%: risk of ablation (removed from homepage); 25% or more: risk of deactivation; 80% or more: immediate deactivation. Judged over 7-day windows with warnings. | same | Verified. These thresholds only hit extreme stores. |
| 3 | Out-of-stock items and over-busy acceptance are named causes of avoidable cancellations | qualitative | [DD: How to Prevent Avoidable Cancellations](https://merchants.doordash.com/en-us/learning-center/most-loved-avoidable-cancellation) | Verified, official |
| 4 | DoorDash shows "Sales Lost" (subtotal of avoidable cancellations) to merchants | metric exists | same | Verified |
| 5 | Merchant not paid when an order is cancelled for an unavailable item or a closed store | 100% of the sale lost | [DD: Payment for Cancelled Orders](https://help.doordash.com/en-us/merchants/article/do-i-get-paid-for-cancelled-orders) | Verified, official |
| 6 | Error charges for missing/incorrect items | 25–100% of item price + tax; 100% of subtotal for a wrong order handed off; dispute within 14 days | [DD: Error Charges](https://help.doordash.com/en-us/merchants/article/what-are-order-error-adjustments) | Verified, official |
| 7 | Most Loved signals | missing/incorrect, cancellations, photo coverage, menu markup; evaluated monthly; no public thresholds | [DD: Road to Most Loved](https://merchants.doordash.com/en-us/learning-center/road-to-most-loved) | Verified. No sales-lift figure is published. |
| 8 | Most Loved benefits | homepage carousel, badge, "may" increase recommendations; "does not introduce a separate ranking system" | same | Verified. The upside is soft. |
| 9 | Avoidable Dasher wait | most stores under 3m24s; ideal under 2m; late orders → lower ratings → lower ranking | [DD: Avoidable Wait](https://merchants.doordash.com/en-us/learning-center/avoidable-wait) | Verified, official |
| 10 | DoorDash Busy mode adds prep time and paces orders; Pause can be set by channel and duration | feature exists | [DD Store Status](https://help.doordash.com/en-us/merchants/article/what-is-my-store-status), [DD Staffing tips](https://merchants.doordash.com/en-us/learning-center/restaurant-staffing-shortages) | Verified. This is the competing built-in control. |
| 11 | Uber Eats reduces visibility for missed, cancelled, or inaccurate orders; tracks an "inaccurate orders rate" | no thresholds published | [Uber: Restaurant visibility (NZ)](https://www.uber.com/nz/en/blog/understanding-your-restaurants-visibility/) | Verified, qualitative |
| 12 | Uber Eats passes order-error costs to merchants | part to full item cost + tax; 96-hour reporting cutoff | [Uber Eats: Order errors (NZ)](https://merchants.ubereats.com/nz/en/order-errors) | Verified |
| 13 | Average restaurant delivery cancellation rate (US/Canada) | 1.5–3% | [Otter 2024 report](https://tryotter.com/blog/case-study/otter-delivery-cancellation-report-2024), [BusinessWire](https://www.businesswire.com/news/home/20231212274071/en/Restaurant-Operating-System-Otter-Releases-Performance-Data-to-Help-Restaurants-Understand-Order-Cancellation-Trends-and-Mitigate-Holiday-Spike) | Vendor data from 1B+ orders; method undisclosed |
| 14 | Lost revenue from cancellations | $150–300/week per $10k weekly revenue | same | Vendor estimate (simple arithmetic) |
| 15 | Cancellations correlate with ratings | under 2% → 4.5 stars; over 8% → 4.0 | same | Correlation only, vendor data |
| 16 | Closing-time spike | last hour: 18% of orders, 28.6% of cancellations | same | Vendor data; no cause split |
| 17 | Out-of-stock share of cancellations | 27.9%, *convenience stores only*; dessert shops "most likely" to cancel for unavailable items | same | Vendor data. No restaurant-wide stockout share is published. |
| 18 | UK: lost sales to cancellations; last hour 1.74x rate; apps may auto-pause after 2 consecutive cancellations or misses | 0.66–1.33% of weekly sales | [Otter UK release](https://www.businesswire.com/news/home/20240311098079/en/Cancellation-of-Takeaway-Orders-Increases-in-the-Last-Hour-of-Restaurant-Operation) | Vendor data, about 30M orders |
| 19 | Aggregators already reduce cancellations | Otter claims −42% (Uber Eats, US) and −63% (UK) | same | Vendor marketing claim |
| 20 | Operator complaints about DoorDash/Uber Eats integrations | not read | [Toast Community thread](https://community.toasttab.com/t5/restaurant-operations/issues-with-doordash-amp-uber-integrations/m-p/16045) | Lead |
| 21 | Survey: "nearly 25% of third-party deliveries disappoint" | not read | [Restaurant Business](https://www.restaurantbusinessonline.com/topics/nearly-25-third-party-deliveries-disappoint-study-finds) | Lead (consumer side) |

**Gaps (no hard data found):** how often independents 86 items per shift; how often an 86 fails to sync to the apps; how often merchants use Busy mode or Pause; Grubhub's merchant penalty rules; Reddit and forum anecdotes (not read). The interview plan should fill these: ask 5–10 operators "how many 86s last Friday, and did you remember to toggle every app?"

## DoorDash incentives (why Gondola aligns)

1. **DoorDash publishes the target metric.** Avoidable cancellations (goal under 1.1%) and missing/incorrect items (goal under 1%) sit in the Merchant Portal under Operations Quality, next to a "Sales Lost" figure (rows 1, 3, 4). Gondola can report straight against these numbers.
2. **The penalties are graduated.** First comes loss of homepage visibility (ablation), then deactivation (row 2). Most Loved status, judged monthly, adds a badge and a carousel slot (rows 7–8). Be honest that DoorDash says these benefits "may" help and publishes no lift figures.
3. **DoorDash's own advice matches the product:** mark out-of-stock items, don't accept orders when too busy, use Busy mode, set accurate item-level prep times, review late orders by time of day (rows 3, 9, 10). Gondola automates that advice ahead of time. Framing: "Busy mode, but triggered before the rush instead of during it."
4. **Who absorbs the cost:** for a stockout cancellation, the merchant earns $0 (row 5). DoorDash also loses the order fee and the customer's trust, and missed orders hurt Dasher efficiency. The incentives point the same way for both sides, which suits a sponsor-track pitch.
5. **Uber Eats** uses the same logic (visibility hit, error charges), so the product is not DoorDash-only. **Grubhub** is unverified.

## Willingness to pay

- **No WTP data for independents was found or verified.** Analog pricing, all leads (search titles only, not read):
  - Otter is listed "starting at $89 per month per location" on [TrustRadius](https://trustradius.com/products/otter-order-manager/reviews).
  - Deliverect publishes pricing tiers at [deliverect.com/en-us/pricing](https://deliverect.com/en-us/pricing), amounts not checked.
- **Value-based ceiling (inference):** Otter's figure is $150–300 a week lost to *all* cancellations at $10k a week. If Gondola prevents half of the stockout and overload share, plausibly a third to a half of that, the recovered value is about $100–600 a month. Add avoided error charges and any Most Loved upside. That supports roughly **$30–100 per location per month**, or a bundle inside an existing aggregator.
- **Risk:** independents already pay for a POS and often an aggregator. The likely buyer is an aggregator or POS partner (or DoorDash itself, as a Merchant Portal feature), not the restaurant directly.

## Sources

- DoorDash: [Unhealthy Store Ops Rates](https://help.doordash.com/en-ca/merchants/article/unhealthy-store-operations-rate) · [Avoidable Cancellations](https://merchants.doordash.com/en-us/learning-center/most-loved-avoidable-cancellation) · [Payment for Cancelled Orders](https://help.doordash.com/en-us/merchants/article/do-i-get-paid-for-cancelled-orders) · [Error Charges](https://help.doordash.com/en-us/merchants/article/what-are-order-error-adjustments) · [Road to Most Loved](https://merchants.doordash.com/en-us/learning-center/road-to-most-loved) · [Avoidable Dasher Wait](https://merchants.doordash.com/en-us/learning-center/avoidable-wait) · [Store Status / Busy / Pause](https://help.doordash.com/en-us/merchants/article/what-is-my-store-status) · [Staffing tips / Busy Mode](https://merchants.doordash.com/en-us/learning-center/restaurant-staffing-shortages)
- Uber Eats: [Restaurant visibility](https://www.uber.com/nz/en/blog/understanding-your-restaurants-visibility/) · [Order errors](https://merchants.ubereats.com/nz/en/order-errors)
- Otter (vendor data): [2024 Cancellation Report](https://tryotter.com/blog/case-study/otter-delivery-cancellation-report-2024) · [US/Canada release](https://www.businesswire.com/news/home/20231212274071/en/Restaurant-Operating-System-Otter-Releases-Performance-Data-to-Help-Restaurants-Understand-Order-Cancellation-Trends-and-Mitigate-Holiday-Spike) · [UK release](https://www.businesswire.com/news/home/20240311098079/en/Cancellation-of-Takeaway-Orders-Increases-in-the-Last-Hour-of-Restaurant-Operation)
- Leads, not read: [Toast Community thread](https://community.toasttab.com/t5/restaurant-operations/issues-with-doordash-amp-uber-integrations/m-p/16045) · [Restaurant Business survey](https://www.restaurantbusinessonline.com/topics/nearly-25-third-party-deliveries-disappoint-study-finds) · [TrustRadius Otter](https://trustradius.com/products/otter-order-manager/reviews) · [Deliverect pricing](https://deliverect.com/en-us/pricing)
