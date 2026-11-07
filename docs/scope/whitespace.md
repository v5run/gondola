# Gondola pivot white-space check: allocation (A), capacity throttling (B), autopilot (C)

Research date: 2026-11-05. Evidence levels: **[V]** = I read the vendor's help, press or product page. **[T]** = search-result title only; the page could not be read. **[P]** = from the earlier feasibility brief, not re-checked here. Every row except those marked [T] or [P] was checked against the page itself.

## Verdict

- **(A) Channel-aware allocation: PARTIALLY OCCUPIED by rules. The forecast-plus-optimization version is UNOCCUPIED.**
  - US POS stock sync is deliberately *global*:
    - Square: "Available and sold out status are updated across channels" [V].
    - Clover: the item leaves DoorDash "when inventory reaches zero" [V].
    - Toast: decrements stock and syncs it to every platform [V].
  - Per-channel hiding exists only as manual or permanent toggles:
    - Otter Channel Availability: the item "will never appear there" [V].
    - DoorDash Assistant marks items out of stock on DoorDash only, when told to [V].
    - Deliverect snooze is manual, and the docs don't say whether it can be limited to one channel [V].
  - **Closest competitor: Sinqro** (an EU/LatAm order hub). Its "stock soldouts" automation hides products "when stock falls" against a threshold you define. Rules can be scoped "by venue, channel, schedule, product". The page mentions no reserve/safety-stock logic and no prediction [V].
  - So "pause on DoorDash at 8 left, keep for dine-in" is possible as a fixed rule there, if Sinqro operates in your market. I did not confirm Sinqro serves the US.
  - Nobody I found does the parts that make A new:
    - a nightly *decision* on how much to prep and how to split it by channel margin and rating risk;
    - protection levels that adapt during service from the depletion forecast.
  - Documented pain: Toast users oversell on DoorDash/Grubhub when stock is low but positive, and the workaround is a manual buffer of "one or two units" [V].
- **(B) Capacity throttling: LARGELY TAKEN.**
  - Olo checks marketplace orders against throttling capacity automatically, and over-capacity orders "fail and are canceled" [V].
  - Deliverect extends prep time when orders, value or items in a time window cross a threshold. It is "not currently available for all customers" [V].
  - Sinqro order buffering can "open or close channels when kitchen pressure crosses the limits you define" [V].
  - Checkmate Dynamic Prep Time adds prep time on DoorDash, Uber Eats and Grubhub based on *order subtotal* [V]. Checkmate says plainly: "Orders cannot be throttled" [V].
  - Toast capacity caps cover its own online ordering only, "not through integration APIs" [V].
  - All of these are reactive or rule-based. Only a *forecast-triggered, pre-emptive* version is open, and incumbents can copy it cheaply.
  - Square sellers asked for "a customizable/optional AI throttle button" with dine-in priority (July 2025) [V]. That is real demand, but a thin wedge.
- **(C) Autopilot: PARTIAL. Its defensible core is the decision layer in A.** Lead with A's nightly allocation plan plus a live depletion forecast. Treat B only as a guardrail.
- **Sell-out prediction (feature 1) is unshipped everywhere I checked.**
  - Toast's Sold-Out Alert reports items that *already* sold out [V].
  - Toast IQ agents "will not make changes in Toast on their own" [V].
  - Managerbot's help article describes no shortage forecasting [V]; the "shortage flags" claim is from press coverage [P].
  - Forecasters (Lineup, ClearCOGS, PreciTaste) predict demand for prep and labor, not depletion during service [V].

## Feature matrix

Columns: (1) predicts sell-out time; (2) pauses an item per channel; (3) reserves stock dine-in vs. apps; (4) automatic capacity throttling; (5) works across several delivery apps; (6) price.

| Product | (1) Predict sell-out | (2) Per-channel item pause | (3) Allocate/reserve | (4) Auto capacity throttle | (5) Multi-app | (6) Price |
|---|---|---|---|---|---|---|
| Square Managerbot + item availability | Claimed shortage flags [P]; not in help doc [V] | No: global status [V] | No | 15-min order cap and item caps on own channels; 3P set per integration [V] | Yes, global sync | Managerbot free [P] |
| Toast IQ / inventory | No: Sold-Out Alert after the fact; Production Forecast = prep qty [V] | No, global sync [V] | No (manual buffers) [V] | Capacity caps, Toast OO only; SmartQuote excludes 3P [V] | Stock syncs to DD/UE/GH [V] | Bundled; not verified |
| Clover + DoorDash | No | Not documented [V] | No | Manual store pause [V] | Per integration | Not verified |
| DoorDash Portal / Assistant | None documented [V] | DD only; Assistant marks items OOS on request [V] | No | Busy/pause manual, per channel [V] | No | Not stated [V] |
| Uber Eats Orders | No | UE only | No | Busy Mode manual; auto-pause on unaccepted orders [V] | No | Included |
| Grubhub | No | GH only | No | Not checked | No | Included |
| Otter | No | Manual, permanent toggle [V] | No | Manual pause; AlwaysOn *auto-unpauses* after 5 min [V] | Yes | AlwaysOn is a paid add-on [V]; amount not verified |
| Deliverect | No; Apr 2026 AI agents do menu layout and outage repair [V] | Snooze manual; channel scope unstated [V] | No | **Yes**: threshold prep extension, limited rollout [V] | Yes | Not verified |
| **Sinqro** | No (forecast is a separate Analytics product) [V] | **Yes, rule-based thresholds by channel** [V] | Threshold only; no reserve logic [V] | **Yes**: load-based channel open/close [V] | Yes; markets unlisted | Not verified |
| Checkmate | No | Manual platform offline [V] | No | No throttling; subtotal-based prep time [V] | DD/UE/GH [V] | Not verified |
| Olo (Rails) | No | No | No | **Yes**, but cancels over-capacity orders [V] | Yes | Enterprise; not verified |
| Lunchbox | No | No evidence | No | Uses Toast delays; 3PD prep not imported [V] | Partial | Not verified |
| Chowly, Nextbite | No evidence | No evidence | No | No evidence | Yes (Chowly) | Not verified |
| Marble (YC S26) | Not mentioned; YC lists item-level demand forecasts [V] | No | No | No | No | Not stated |
| PreciTaste | Demand-for-prep only [V] | No | No | No | No | Not stated |
| Lineup.ai | Hourly forecast by channel; no item prep [V] | No | No | No | No | Not stated |
| ClearCOGS | Daily/shift forecasts; no stockout prediction [V] | No | No | No | No | Not disclosed |
| Tenzo | Forecast + EOD report [P] | No | No | No | No | Not verified |
| Loop / Voosh | Uptime/dispute tools [T][P] | No | No | No | Yes | Not verified |

No 2024–2026 company on YC's Restaurant Tech list mentions throttling or 86/sell-out prediction [V].

## White space

1. **Allocation as a decision, not a rule (core of A).** Sinqro proves threshold-per-channel hiding is buildable and sellable. It leaves the operator to guess the thresholds. Gondola's opening:
   - At close: "prep 30 brisket; protect 10 for dine-in."
   - Rank channels by net margin after commission and by rating/ranking sensitivity.
   - During service: move cutoffs as the live depletion forecast changes. For example, if dine-in pace runs hot at 7:30, pull brisket from Uber Eats now rather than at a fixed 8.

   I found this in no product.
2. **Time-to-sell-out estimates per item, per channel.** These don't exist anywhere checked. They are the input that makes (1) and A work.
3. **Oversell protection at low stock.** The Toast race condition [V] gives a simple, demo-able first feature: an automatic buffer per channel.
4. **US independents on DoorDash/Uber Eats/Grubhub.** The rule engines either target enterprise (Olo, Deliverect throttling in limited rollout) or are EU/LatAm (Sinqro). US small operators get manual toggles. Forecast-triggered B (raise prep time or snooze slow-to-cook items 20 minutes before a predicted peak) is a minor add-on, not the pitch.

**Risks:**
- Independents rarely keep portion counts. A needs an "I prepped N" step at close.
- Toggling items may hurt marketplace ranking. Unverified.
- Writing availability per app needs integration access. Mock it for the hackathon, or go through an aggregator API.
- Sinqro or Deliverect could add forecasting to their rules quickly.

## Sources

- Square Managerbot help: https://squareup.com/help/us/en/article/8617-use-managerbot-to-manage-business-tasks-and-insights
- Square item availability: https://squareup.com/help/us/en/article/8495-beta-item-availability
- Square community, throttling (Jul 2025): https://community.squareup.com/t5/Food-Beverage/How-is-everyone-dealing-with-order-throttling-kitchen-capacities/td-p/801595
- Toast quote time/throttling: https://support.toasttab.com/en/article/Managing-Your-Quote-Time-Strategy
- Toast IQ Agents: https://support.toasttab.com/zh-Hans/article/Toast-IQ-Agents-Overview
- Toast community, 3P overselling: https://community.toasttab.com/t5/restaurant-operations/3rd-party-apps-allow-for-customers-to-order-more-than-what-is-in/m-p/16695
- Clover–DoorDash: https://help.doordash.com/en-us/merchants/article/integrate-doordash-with-your-clover-pos
- DoorDash store status: https://help.doordash.com/en-us/merchants/article/what-is-my-store-status
- DoorDash Assistant: https://help.doordash.com/en-us/merchants/article/doordash-assistant
- DoorDash May 2026 AI tools: https://www.pymnts.com/news/retail/2026/doordash-ai-accelerates-local-commerce-growth/
- Uber Eats automatic pausing: https://www.uber.com/au/en/blog/automatic-pausing-for-merchants
- Otter glossary: https://helpdesk.tryotter.com/hc/en-us/articles/19695641159187
- Otter Channel Availability: https://helpdesk.tryotter.com/hc/en-us/articles/50530179484947-Channel-Availability
- Otter AlwaysOn: https://helpdesk.tryotter.com/hc/en-us/articles/26120291964435-AlwaysOn
- Deliverect order throttling: https://help.deliverect.com/en/articles/14622721-configure-order-throttling
- Deliverect channel busy mode: https://developers.deliverect.com/reference/channel_busy_mode
- Deliverect busy/snooze (Lightspeed): https://o-series-support.lightspeedhq.com/hc/en-us/articles/31329315466651-Managing-busy-times-with-Deliverect
- Deliverect snooze blog: https://www.deliverect.com/en/blog/deliverect/maximize-kitchen-efficiency-with-deliverect-s-snooze-feature-a-step-by-step-guide
- Deliverect AI agents (Apr 2026): https://www.fooddive.com/press-release/20260407-deliverect-launches-ai-agents-and-smart-assistants-to-supercharge-restauran-1/
- Sinqro stock soldouts: https://sinqro.com/en-es/solutions/automations/stock-soldouts
- Sinqro order buffering: https://sinqro.com/en-be/solutions/automations/order-buffering
- Olo Rails throttling: https://olosupport.zendesk.com/hc/en-us/articles/4403528824347-Rails-and-Order-Throttling
- Checkmate Dynamic Prep Time: https://support.itsacheckmate.com/hc/en-us/articles/26759613261595-Dynamic-Prep-Time
- Checkmate throttling: https://support.itsacheckmate.com/hc/en-us/articles/49390058099867-Can-I-throttle-my-orders
- Lunchbox prep/throttling: https://support.lunchbox.io/en/articles/8684461-2m-prep-times-order-throttling-times-order-firing-printing-behavior
- Marble (YC S26): https://runtimewire.com/article/marble-ai-restaurant-back-office-yc-s26
- YC Restaurant Tech: https://www.ycombinator.com/companies/industry/Restaurant%20Tech
- PreciTaste: https://www.qsrweb.com/news/precitaste-launches-ai-hub-to-help-mid-sized-restaurants-streamline-operations
- Lineup.ai–Toast: https://support.toasttab.com/en/article/Getting-Started-with-the-Lineup-ai-Integration
- ClearCOGS: https://restauranttechnologynews.com/2025/04/clearcogs-secures-3-8-million-to-help-restaurants-cut-waste-and-optimize-operations-with-ai-forecasting-engine/
