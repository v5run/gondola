# Gondola: Red-Team Feasibility Check (Competition, Novelty, Viability)

*Prepared 2026-11-04 for the DoorDash sponsor track, CMU.*

## Verdict

**Hackathon: a good demo, and a weak business as pitched.** Each of the 9 agents already exists as a funded product or as a free feature inside a POS or delivery platform. The one-tap "close shift" ritual and the cross-agent chaining are new. The parts are not.

The biggest problems:

1. **The platforms already give away a lot of this.** Square's Managerbot (free) does daily recaps, shortage warnings, availability changes and draft schedules. Toast IQ does Q&A and 86-ing items. DoorDash Assistant does sales reports, out-of-stock changes and error-charge advice.
2. **DoorDash's terms ban third-party dispute filing.** The "Books" agent can't simply auto-dispute.
3. **Independents don't spend much on software.** The average full-service operator spends about **$196/month on all tech combined**.

For a DoorDash-judged track, the pitch has to explain why DoorDash wouldn't just build this into the Merchant Portal.

## Competitive map

| Player | What it already does | Gondola overlap | Pricing (public?) |
|---|---|---|---|
| **Loop** (tryloop.ai) | "Agentic co-worker": reconciles 3P data into the ERP, chargeback recovery (~95% automated across DD/UE/GH), store uptime. $14M Series A Feb 2026, 300+ brands | Books, Sentinel, Analyst | Not public; enterprise |
| **Voosh** | Dispute manager (claims 60–70% win rate), unified fee/payout view, reviews, analytics | Books, Analyst | Flat fee, not published |
| **Otter** | Automated error/chargeback recovery; cross-platform analytics on payouts, commissions and promos | Books, Analyst | Demo-gated |
| **KoreFi / Deliverect Reclaim / Lunchbox / DTiQ** | Automated 3P dispute filing. KoreFi targets independents with 10 or fewer locations | Books | Not public |
| **Deliverect AI agents** (Apr 2026) | Autonomous menu agents; support agents that catch anomalies, unsynced menus and outages | Guard, Sentinel | Add-on |
| **DoorDash Assistant** | Sales reports by date/channel, marks items out of stock, advice on cutting error charges and cancellations, review summaries. Not yet POS-integrated | Ask, Analyst, Guard | Free |
| **Square Managerbot** (Apr 2026) | Daily sales and labor recap by location, flags shortages from sales speed vs stock, changes availability by voice, drafts schedules from projected sales | Analyst, Stock, Guard, Demand, Plan, Ask | **Free** (open beta) |
| **Toast IQ** | Conversational Q&A on sales, labor and menu, a "For you" insight feed, "86 all items with avocado", menu edits | Ask, Analyst, Guard | Bundled |
| **Tenzo** | **End-of-day report with tomorrow's forecast**, labour %, COGS, ratings; 120+ integrations | Report, Demand, Analyst | Quote |
| **MarginEdge** | Daily controllable P&L, invoices, inventory, recipe costing, unlimited AI | Books, Stock | $350/loc/mo |
| **Restaurant365** | Accounting, inventory, ops; Loop partner | Books, Stock | $435–635/loc/mo |
| **7shifts** | Scheduling; hourly labor forecast on Premium | Plan | $0–150/loc/mo |
| **ClearCOGS** | Item-level demand forecast that produces prep lists and purchase quantities. $3.8M seed; Jimmy John's | Demand, Plan | Quote |
| **Lineup.ai** (now TimeForge) | Sales and labor forecasts that build schedules | Demand, Plan | Quote |
| **WISK / Supy** | Inventory, recipe costing, ordering | Stock | WISK $125–199/mo; Supy quote ($$$$$ on G2) |
| **Marble** (YC S26, Jul 2026) | "AI operating system" for back of house: inventory, purchasing, invoices, prep, labor, using agents and computer vision | Nearly all | Not public; multi-unit |

*Crunchtime and Craftable weren't checked in depth here. Both are enterprise inventory/ops suites and fall in the same Stock/Plan bucket.*

**Commodity:** chat over metrics (Ask), the daily recap (Analyst/Report), next-day forecasting (Demand), schedule drafts (Plan), dispute detection (Books), manual sold-out toggles (Guard).

**Actually differentiated:**
- **Trigger and packaging.** The analysis runs when the shift closes, not on a dashboard you have to remember to open.
- **Reconciling across competing apps against in-store cash.** Toast, Square and DoorDash each see only their own slice.
- **Ingredient-level, forecast-timed pausing across channels.** Toast's own inventory depletion marks items "Out" on a reorder page, and the manager still has to 86 them by hand. Toast community posts also report 3P orders overselling stock counts. That's a real gap.

**Is "one-tap close that reconciles + forecasts + texts" novel?** As a bundle, slightly. Tenzo already sends an end-of-day report that includes tomorrow's forecast, and Managerbot is moving toward proactive daily recaps.

**Platform risk: high.** DoorDash Assistant, Toast IQ and Managerbot all shipped Q&A plus actions in 2025–26, at no extra charge. Adding "summarize my day at close" is a small sprint for any of them. The only lasting moat is neutrality across platforms, and middleware (Otter, Deliverect) is moving into the same space.

## Where it fails, ranked

1. **Free bundled versions beat a paid bundle.** Square already offers about 6 of the 9 agents for free. Toast IQ covers Ask and Guard. A manager won't pay for a tenth tab that repeats their POS.
2. **Willingness to pay is tiny.** Average restaurant margins are 3–5%, and full-service operators spend about $196/month on all technology. Gondola is competing for that budget with tools that cost $350–635 per location. Only Books has hard ROI (recovered dollars), and that market prices on contingency and is already crowded.
3. **Data access and ToS.** DoorDash says using a third party to file disputes violates its Portal terms. The dispute window is 14 days on DoorDash and 30 on UE/GH. Payout-level data usually comes through Otter or Deliverect, which compete with Gondola and can restrict access.
4. **The Stock ledger needs inputs that independents rarely keep.** Without recipe costing and real counts, ingredient depletion is guesswork. A wrong auto-86 on a Friday-night top seller costs more than a full year of the subscription.
5. **Too many agents, not enough trust.** Nine LLM agents means nine places to fail. Hallucinated numbers in a financial reconciliation can kill the product. A manager at 11pm wants a 20-second SMS, not a 4-page PDF. And when restaurants close or turn over owners, SMB churn follows (this point is an assumption; no number was sourced).

**What judges will poke at:**
1. "DoorDash Assistant already reports sales, marks items out of stock and advises on error charges. Why wouldn't we just ship this?"
2. "Is this real merchant data or synthetic? Which APIs give you DoorDash payout and error-charge data?"
3. "Show forecast accuracy compared with the naive baseline: same weekday last week."
4. "Why 9 agents instead of 1 good prompt plus SQL? What does each close cost, and how long does it take?"
5. "What happens when Guard is wrong? Who approves it? And how many dollars a month does an operator save?"

## How to sharpen

- **Lead with three outcomes instead of nine agents:** (a) **"$ found tonight"**: fee, error-charge and payout mismatches across the 3 apps compared with POS and cash; (b) **"what runs out tomorrow"**; (c) **"what to prep and order."** Keep the agents as architecture slides.
- **Make the one new thing the headline:** forecast-timed, ingredient-level pausing per channel. For example: "Brisket runs out around 7:40pm Friday. Pause it on DoorDash and Uber at 7:10 and keep it for dine-in." Neither Toast's depletion feature nor DoorDash's manual out-of-stock does this.
- **Line it up with DoorDash's incentives.** Out-of-stock cancellations and avoidable error charges hurt DoorDash too. Pitch Gondola as a Merchant Portal / Assistant extension that lowers cancellations, not as a neutral rival. Then the "why wouldn't DoorDash build it" question becomes "acquire or partner."
- **Use Managerbot's approval pattern.** The agent proposes and the manager approves. Disputes become a ready evidence packet the manager files with one click, which stays inside the ToS.
- **Bring proof:** a backtest slide (forecast error vs naive baseline; dollars of discrepancies found in the sample data) and cost per close.
- **Shrink the output.** One SMS plus a 1-page summary. Drop the 4-page PDF from the demo.
- **Pricing:** free close summary; $49–79/mo for Guard and Plan; or a percentage of recovered dollars for Books.

## Sources

- Loop Series A: https://ascendants.in/business-stories/loop-ai-raises-14m-series-a-restaurant-back-office-ai/attachment/loop-ai/
- Loop on R365: https://www.restaurant365.com/partners/loop/
- Loop FAQ (dispute windows, 95% automation): https://loop.helpwise.help/articles/233813-faqs
- Voosh Dispute Manager: https://www.fsrmagazine.com/content/vooshai-launches-dispute-manager-solution-restaurant-profit-protection
- Voosh features/flat fee: https://restauranttechnologynews.com/2023/10/voosh-offers-30-day-free-trial-of-its-analytics-platform-that-helps-restaurants-reduce-order-issues-and-increase-sales/
- Commission-audit market gaps: https://liveinthefuture.org/startups/restaurant-delivery-commission-audit-saas.html
- Otter recovery: https://www.tryotter.com/signup/test
- Otter Analytics: https://www.tryotter.com/en-gb/blog/updates/restaurant-delivery-analytics
- Dispute tools roundup: https://neurohive.io/en/spotlight/top-doordash-error-charge-recovery-software-in-2026/
- Deliverect AI agents: https://restauranttechnologynews.com/2026/04/deliverect-launches-ai-agents-and-smart-assistants-to-boost-restaurant-sales-and-protect-digital-revenue/
- DoorDash Assistant: https://help.doordash.com/en-us/merchants/article/doordash-assistant
- DoorDash error charges and third-party ToS: https://help.doordash.com/en-us/merchants/article/what-are-order-error-adjustments
- DoorDash AI merchant suite: https://chainstoreage.com/doordash-unveils-ai-suite-restaurants-food-service-retailers
- Square Managerbot: https://squareup.com/us/en/press/managerbot-open-beta and https://www.pymnts.com/?p=3689889
- Toast IQ: https://pos.toasttab.com/news/toast-expands-toast-iq-smart-ai-assistant
- Toast depletion (manual 86): https://intercom.help/toast-central/en/articles/13793466-toast-inventory-stock-depletion-canada-ireland-and-uk
- Toast 3P oversell thread: https://community.toasttab.com/t5/restaurant-operations/3rd-party-apps-allow-for-customers-to-order-more-than-what-is-in/m-p/16695
- Tenzo end-of-day report: https://www.gotenzo.com/resources/insight/what-does-the-ideal-end-of-day-report-look-like-for-hospitality-businesses
- MarginEdge pricing: https://www.marginedge.com/pricing/
- R365 pricing: https://www.trustradius.com/products/restaurant365
- 7shifts pricing: https://costbench.com/software/employee-scheduling/7shifts/
- ClearCOGS: https://restaurantbusinessonline.com/technology/clearcogs-raises-38m-ai-powered-restaurant-forecasting
- AI tools roundup (ClearCOGS, Lineup/TimeForge): https://www.fast.io/resources/best-ai-for-restaurants-2026.md
- WISK pricing: https://www.softwaresuggest.com/wisk/pricing
- Supy pricing: https://www.g2.com/products/supy/pricing
- Marble (YC S26): https://runtimewire.com/article/marble-ai-restaurant-back-office-yc-s26
- YC restaurant tech list: https://www.ycombinator.com/companies/industry/restaurant-tech
- Tech spend ($196/mo, TouchBistro survey): https://www.fsrmagazine.com/feature/restaurants-reach-a-technology-turning-point-rooted-in-simplicity
- Margins 3–5%: https://pos.toasttab.com/blog/on-the-line/average-restaurant-profit-margin
