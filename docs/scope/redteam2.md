# Gondola Red-Team #2: Choosing a Redefinition

*2026-11-05 · DoorDash sponsor track, CMU · Written from the view of a skeptical advisor and judge.*

## Verdict

**Winner: "C′ Sell-out Guardrails."** This is a narrower version of C.

- **It keeps** forecast-based prep quantity and predictive per-item pausing on the apps.
- **Stretch goal:** forecast-quoted prep time.
- **It drops** A's channel-split optimizer.
- **The close-out stays, with a new job.** Instead of reporting on today, it becomes the moment the manager approves tomorrow's limits.

**Why the simulation favours this scope.** These figures come from the team's synthetic 90-day demo year and have not been independently verified.

| Policy | Store-caused cancellations (90 days) | Net value (90 days) |
|---|---|---|
| Status quo | 424 | baseline |
| Guard only (pause apps before sell-out, habitual prep) | 0 | +$2.6k |
| Forecast prep + Guard | 0 | **+$11.9k** |
| Adding dine-in vs app allocation on top | no change | ~$0 |

- **Most of the value comes from cooking the right amount**, not from pausing. The forecast prep plan accounts for about $9.3k of the $11.9k.
- **The allocation logic is redundant.** Pausing the apps before sell-out already leaves the last portions for dine-in, so A's optimizer adds nothing.

**Why it lands with DoorDash judges.**
- DoorDash's own guidance names "out of stock but still listed" and "too busy" as causes of avoidable cancellations [1].
- The goal for avoidable cancellations is under 1.1% [2].
- An unhealthy-operations rate of 15% or more risks reduced visibility; 25% or more risks deactivation [2].
- The team's pain research found that merchants receive $0 on item-unavailable cancellations (not verified by me).
- So both DoorDash and the merchant lose on every one of these orders. Gondola removes them *before* they happen.

**Gap check: today's tools are reactive.** DoorDash and Uber Busy/86 are manual [1][5][6]. Deliverect snoozes on all channels by hand [12]. Square and ChowNow sync at zero stock [8][9]. Toast needs a manual 86 and oversells on 3P [13][14]. **Nobody we checked pauses an item ahead of sell-out from a forecast.**

**Biggest copy threat:** Deliverect, which already has timed snooze and launched AI agents in April 2026 [12][15].

**Why not the others:** see the scorecard notes. In short, A adds ~$0, B is covered by Olo [3], Deliverect [4] and DoorDash's prep-time ML [7], D is commodity sync [8][9][10], and E is DoorDash Assistant plus a sprint [11].

## Scorecard

Scores run 1–5, where 5 is best for Gondola. For Overlap and Replication risk, 5 means the *least* overlap or risk.

| Option | Overlap | Novelty | Defensibility | Replication risk | Buyer | Pricing | Judge appeal | **Total /35** |
|---|---|---|---|---|---|---|---|---|
| A Channel allocation | 4 | 3 | 2 | 3 | 1 | 1 | 2 | 16 |
| B Capacity throttle | 2 | 2 | 1 | 1 | 3 | 2 | 4 | 15 |
| C Autopilot (A+B) | 3 | 3 | 2 | 2 | 4 | 3 | 4 | 21 |
| D Ghost-stock sync | 1 | 1 | 1 | 2 | 3 | 2 | 3 | 13 |
| E Thin Portal wrapper | 1 | 1 | 1 | 1 | 2 | 1 | 3 | 10 |
| **C′ Sell-out Guardrails** | **4** | **4** | **2** | **3** | **4** | **4** | **5** | **26** |

**Notes on the scores:**
- **A** is clever operations research, but the simulation says it adds about $0. Pitched around dine-in margin, it also sounds anti-DoorDash.
- **B** gets a judge-appeal bump from the team's sim: forecast-quoted prep time cut late app orders from 120 to 65 per day. That result is directional only, because kitchen capacity was assumed. B still overlaps heavily with existing tools.
- **Defensibility is weak for every option.** The only moats are each store's sell-out history, neutrality across apps, and being first to integrate with the POS.

## Recommended scope (C′)

1. **At close (about 60 s).** The manager confirms prepped-portion counts for 3–8 limited items, then approves tomorrow's card. For each item, the card shows:
   - how much to prep, from a newsvendor model on the forecast quantiles;
   - when each app is predicted to be paused.
2. **During service.** Guard compares sales velocity against the portions left. Once projected remaining portions minus the risk from in-flight orders hits a buffer, it pauses the item through each app's item-status API [16].
   - Hard caps limit how many items it can pause.
   - Items unpause automatically at close.
   - Every pause has a one-tap undo.
3. **Stretch: forecast-quoted prep time.** Instead of a fixed 15-minute quote, Gondola quotes the app a prep time from the expected backlog. It may *suggest* Busy mode, but it never pauses the whole store on its own.
4. **Messages.** At most two per day: the close card, plus a pre-service update if the forecast changed. Pause notices stay in-app to avoid alert fatigue. SMS is mocked in the demo because of Twilio registration delays.

## Cut list

| Item | Decision | Why |
|---|---|---|
| Books (payout/cash reconciliation) | **Cut** | Payout data arrives D+1 to 72h later. Loop, Voosh and Otter already cover it. The ToS bans third-party disputes. |
| Sentinel (disputes) | **Cut** | Same reasons as Books. |
| Analyst (recap) | **Cut** | Square Managerbot, Tenzo and DoorDash Assistant already do this. |
| Ask (Q&A) | **Cut** | Commodity. |
| Report (PDF) | **Cut** | Replaced by one approval card. |
| Staffing half of Plan | **Cut** | 7shifts covers it. |
| Ingredient-level Stock ledger | **Cut** | Replaced by counts of prepped portions, which sidesteps over-portioning and recipe costing. |
| Channel allocation optimizer | **Cut** | Adds about $0 in the simulation. |

**What remains: four parts, of which only one is an LLM.**
- **Forecaster:** per-item hourly demand quantiles. Deterministic.
- **Prep planner:** a newsvendor model. Operations research, not an LLM.
- **Guard:** an event-driven control loop that runs during service.
- **Manager agent (LLM):** explains the card. It also turns spoken updates into bounded tool calls ("got 6 extra brisket", "86 ribs now").

**Why multiple parts, but not nine agents:** the planner runs nightly and Guard on every order, and they fail differently and need different safety. Line for judges: *"We kept LLMs out of the money path on purpose."*

## Pitch

**One sentence:** *"At close, Gondola sets tomorrow's guardrails: how much of each limited item to prep, and when to pull it from each delivery app. A DoorDash customer never orders food you've already run out of."*

**Metric to prove in the demo:** out-of-stock avoidable cancellations per 1,000 app orders, set against DoorDash's 1.1% goal [2]. Always pair it with net $ and delivery sales retained.
- Compare three policies: manual 86 at zero, a static "pause at 5 left" rule, and Gondola.
- Pausing everything at 6pm would score zero cancellations, so the cancellation number alone proves nothing.

**Fix before demo day:**
- **Reconcile 94% vs 0 of 424.** A perfect 0 is a red flag: the sim likely has no count error or pause latency.
- **Add a sensitivity chart:** ±20% forecast error, ±3-portion count error, 2-minute pause delay.
- **Scope the claim** to out-of-stock cancellations; Guard can't fix late confirmations [1].

## Judge Q&A

**1. "Why wouldn't DoorDash just build this?"**
- DoorDash sees only its own orders. Sell-out depends on dine-in, Uber and Grubhub demand, which only the POS side can see.
- DoorDash also can't credibly pause items on Uber.
- We build on DoorDash's item-status API [16], which makes us a natural partner for DashOS. DashOS runs through partner POS systems and middleware and doesn't cover inventory [17].

**2. "Isn't pausing items on DoorDash lost GOV?"**
- The order being paused isn't a sale. It would become a cancellation that pays the merchant nothing and wastes a Dasher trip.
- Most of our value comes from the prep plan, not from pausing: +$11.9k vs +$2.6k for Guard alone. In other words, mostly *more food available to sell on DoorDash*.
- Show delivery sales vs the status quo on a slide. Compute it; don't assert it.

**3. "It's synthetic data. Why believe it?"**
- Concede the point. Then show the baselines and the sensitivity chart.
- **Pilot:** one restaurant, two weeks in shadow mode. Guard logs the pauses it *would* have made, checked against POS exports and the Portal's Cancellations / Sales Lost card [1].

**Buyer and pricing:**
- **Buyer:** owner-operators with 1–10 locations selling limited-batch items (BBQ, bakery, ramen, specials) on 2+ apps.
- **Price:** free for one tracked item, then $49–79/location/month. Justified only if the simulated ~$4k/month holds up in a pilot. Distribution is likelier through middleware or DashOS than direct sales.

## Sources

\* marks pages fetched and read for this report. Unmarked entries were carried over from the first red-team or seen only as search results.

1. *https://merchants.doordash.com/en-us/learning-center/most-loved-avoidable-cancellation
2. *https://help.doordash.com/en-us/merchants/article/unhealthy-store-operations-rate
3. *https://olosupport.zendesk.com/hc/en-us/articles/4403528824347-Rails-and-Order-Throttling
4. *https://developers.deliverect.com/reference/post-busy-mode
5. *https://help.doordash.com/en-us/merchants/article/what-is-my-store-status
6. *https://www.uber.com/us/en/blog/time-saving-tools-holidays (Uber auto-pausing, search result only: https://www.uber.com/au/en/blog/automatic-pausing-for-merchants)
7. DoorDash prep-time ML (search result): https://careersatdoordash.com/?p=9157
8. https://squareup.com/help/us/en/article/8559-manage-your-doordash-integration-with-square
9. *https://get.chownow.com/restaurant-support/automatically-sync-square-inventory-updates/
10. *https://ea.salesvu.com/insights/marketplace-sync-truth/
11. https://help.doordash.com/en-us/merchants/article/doordash-assistant
12. *https://help.deliverect.com/en/articles/7979011-snooze-items-to-temporarily-remove-them-from-menus
13. https://intercom.help/toast-central/en/articles/13793466-toast-inventory-stock-depletion-canada-ireland-and-uk
14. https://community.toasttab.com/t5/restaurant-operations/3rd-party-apps-allow-for-customers-to-order-more-than-what-is-in/m-p/16695
15. https://restauranttechnologynews.com/2026/04/deliverect-launches-ai-agents-and-smart-assistants-to-boost-restaurant-sales-and-protect-digital-revenue/
16. https://developer.doordash.com/docs/marketplace/how_to/item_status
17. https://ir.doordash.com/news/news-details/2026/DoorDash-Introduces-DashOS-One-Platform-to-Help-Restaurants-Grow/default.aspx
18. *https://support.toasttab.com/en/article/Managing-Your-Quote-Time-Strategy (Toast's capacity limits don't apply to marketplaces)
19. *https://helpdesk.tryotter.com/hc/en-us/articles/26120291964435-AlwaysOn (only unpauses)
20. https://squareup.com/us/en/press/managerbot-open-beta
