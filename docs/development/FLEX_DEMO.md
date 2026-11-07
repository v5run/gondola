# Flexible pickup: working demo

Built and verified November 6, 2026, before the hackathon. Open [Flexible pickup](http://127.0.0.1:8000/flex). It is a first-party merchant checkout prototype alongside Rush Control. Restaurant state, customer orders and payments are simulated; Gemini calls and the reservation ledger are real local software.

Current branch: `savvy/flexible-pickup` in `v5run/gondola`, stacked on `savvy/tri-workflow`, which includes `savvy/rush-control` and V's clock. [Migration order and verification](REPOSITORY_STACK.md) maps the old commits to this repository's history. The original standalone Flex recordings/model runs below predate the migration; they are retained as evidence from that version. The current UI adds Flexible pickup to Present while preserving the tri-workflow routes. Flex remains a separate frozen reservation ledger, not a continuous Present booking feed.

[Recorded walkthrough](../demo/flex-demo.webm) · [Customer choices](../demo/flex-checkout.png) · [Kitchen comparison](../demo/flex-kitchen.png) · [Actual Gemini tools](../demo/flex-gemini.png) · [Conflict case](../demo/flex-conflict.png)

## Show it in two minutes

1. Open **Demo setup**, choose **Event-night rush**, three cooks and $12 budget, then **Start new demo episode**. The service observation is frozen at 17:42; quote expiry uses real elapsed time. This creates another episode without deleting saved orders.
2. Keep the rice bowl, latest pickup 18:40 and minimum worthwhile saving $2. Click **Find my pickup options** for the deterministic planner, or **Let Gemini find options** for a real autonomous tool loop. Model output can vary; failures remain errors. The usual planner choices are regular pickup at 17:53 for $15.40, 18:15 for $13.40, and 18:20 for $12.40. None has created an order or spent incentive budget.
3. Choose 18:15 and **Confirm this pickup**. The server rechecks the exact proposal and commits capacity, stock and $2 incentive in one SQLite transaction. A receipt shows the reserved cooking/packing times. Reload preserves it; repeating the same acceptance does not duplicate the order.
4. Click **See what changed in the kitchen**. Cooking moves from 17:49–17:52 to 18:11–18:14, packing from 17:52–17:53 to 18:14–18:15. This releases three cooking minutes from the 17:42–18:07 window; existing allocations stay fixed. Food is planned to be ready at the selected pickup, rather than cooked early and held.
5. For the failure case, start another episode, find options, switch to **Kitchen & evidence**, and **Book this slot for another customer**. Return to checkout and confirm the old choice: it is rejected, no extra order/discount is created, and fresh options can be requested. The synthetic competing order is clearly labeled. Alternatively use **Open another customer checkout** to exercise separate browsers against the same ledger.

Try a quiet episode, zero budget, a short deadline or a minimum saving above the owner's cap: these produce regular-only choices or an honest no-feasible-checkout error. **Not now** creates no order. The **Quote life** control makes expiry easy to demonstrate.

## The feature and agent role

The proposed exchange is concrete: the customer voluntarily trades some timing flexibility for a saving; the kitchen buys a later production commitment within its limits. The regular option remains available when feasible. The agent reads declared customer constraints, owner limits, observed workload, stock and shared reservations; compares possible choices; checks alternatives; and publishes at most two approved discounted proposals. It cannot accept for the customer, take payment or alter an existing paid order.

Code controls arithmetic and resource feasibility. An offer must meet the deadline/minimum saving, owner discount/budget and modeled contribution floor, reserve a free station/shared cook/packing sequence, move pickup at least five minutes, and release at least two near-term cooking minutes. The modeled cost cap of $1 per released minute is an explicit owner-limit assumption, **not an estimated real economic value**. A later second option must offer a larger saving, so the menu does not include dominated alternatives.

Quotes are **proposals, not holds**. Confirmation revalidates stock, remaining budget, exact production slots and whether the incentive still buys relief relative to the original regular option. Changes can require a new quote. Atomic acceptance and quote/cart idempotency prevent duplicate commitments. Expiry, decline, invalid IDs, changed assumptions and competing bookings have explicit outcomes.

## Implementation

- `gondola/flex/calendar.py` reuses the Rush menu and observed synthetic snapshot at minute 12, including its existing schedule. It retains public observations, never the simulator's private future customer-response data. It adds future cook/pack reservations around existing work using observed effort plus a stated 20% allowance.
- `gondola/flex/service.py` / `store.py` manage sessions, quotes, acceptance, events and receipts in `.local/flex-pickup.sqlite3`. SQLite `BEGIN IMMEDIATE` serializes revalidation and commitment across requests. Quotes include their original comparison context so later bookings do not rewrite evidence.
- `gondola/flex/agent.py` uses the existing real ADK/Gemini runner. Tools inspect, compare, check and publish. A narrative without a successful publication is an error. The UI shows actual tool events and clearly distinguishes Gemini from the deterministic planner.
- `gondola/api/flex.py` exposes typed local endpoints; `web/src/screens/Flex.tsx`, `web/src/api/flex.ts` and `web/src/flex.css` provide shopper/merchant views, polling, receipts and production comparisons. Sidebar navigation and a link connect the new page to Rush Control.

The existing `/rush` replay and its benchmark engine are unchanged. Flex takes its starting observation from that engine; subsequent Flex bookings share their own durable ledger. They do **not** feed back into an independently running Rush replay. This is one frozen planning episode, not a continuous dinner-service simulation or production KDS.

## What passed and what the measurements mean

- Full offline Python suite: **151 passed**, including 24 new Flex checks; 1119 inherited deprecation warnings, 160.51 seconds. Tests cover independent per-minute resource counts/dependencies, preserved commitments, moving work, stock/budget/price boundaries, consent, expiry, stale assumptions, idempotency and actual simultaneous confirmations.
- Production TypeScript/Vite build passed. **12 browser checks passed**, with no JavaScript page errors: normal/regular/decline flows, durable reload, independent owner/customer views, expiry, conflict/re-quote, shared customer slots, no-deal/impossible cases, explicitly injected provider failure, real Gemini publication plus separate customer acceptance, and both views at 1440/900/390 pixels. [Check results](../demo/flex-browser-checks.json).
- [API restart check](../demo/flex-restart-check.json) restored the actual accepted browser order in the merchant view; repeating acceptance returned the same receipt with one booking and $2 total spend.
- [Final validation summary](../demo/flex-validation.json) records the build/tests and authored-link/secret/whitespace checks. Parent provenance also passed: three original hashes and 31 extracted reference files remain unchanged.
- Two actual Gemini runs succeeded with `gemini-3.1-flash-lite`: an API smoke and the recorded browser flow. [Sanitized tool evidence](../demo/flex-live-evidence.json) shows proposals alone created **zero bookings and zero spend**. [Browser receipt](../demo/flex-browser-live-receipt.json) shows the separately accepted simulated order. These verify real tool use, not optimal model choices.
- [Eight-case feasibility comparison](../demo/flex-evaluation.json) compares regular pickup, a guarded fixed 20-minute/$2 rule, and the deterministic checked planner under the same resource/customer/owner limits. There were zero invariant failures. The planner offers an incentive in two cases, the fixed rule in one; more incentives is **not** itself a success metric. The default case ties. These results do not demonstrate AI superiority.
- A separately evaluated hypothetical urgent bowl arriving at 17:48 can reserve pickup at 17:53 after the flexible choice, versus 17:57 if the first buyer takes the earliest slot. This is a deliberately designed possible arrival, evaluated only after selection, not a predicted or observed customer. Simply delaying arrival without moving cooking releases zero cooking minutes and adds 22 minutes of holding in the default example.

This demonstrates feasible consent and commitments with useful projected capacity relief. It does not measure customer adoption, causal revenue uplift, actual preparation completion, profit, disruption tolerance or universally better service. Existing commitments may already be late in the stress fixture; keeping their allocations fixed does not repair those misses.

## Hackathon fit and production path

The judge can see the complete decision: a congested multi-channel kitchen, a voluntary customer choice, a bounded real agent investigation, and an actual change to the production reservation. It fits the sponsor's peak-hour merchant problem and can be demonstrated in one browser without hardware or merchant credentials. The recording remains usable during a provider outage. All advance-built code and inherited assets must be disclosed.

For a real merchant pilot, start with a checkout the merchant controls and an approved POS/KDS order feed. Support multi-item recipes/modifiers, calibrated durations, moving service time, cancellation/refund rules and observed completion. Recompute offers from timestamped accepted work; expire/revise stale assumptions. Use short capacity/stock/budget holds during payment authorization, a durable order/discount commitment, idempotent external writes and acknowledgment/reconciliation before declaring success. Customer consent and original promises must persist across retries and failures.

Then test whether customers actually accept the exchange and whether the paid capacity improves service enough to justify the incentive. Use a controlled pilot with fixed-slot/fixed-discount comparators, incentive costs, opt-in rates, lateness, holding and contribution; do not infer business value from this synthetic calendar.

For DoorDash, the exact native absence remains the user's **working assumption**. Custom checkout offers, conditional discount funding and reservation/write permissions are unverified. Existing [feature/access research](../ideas/PICKUP_FLEXIBILITY.md) documents scheduling, promotions and Order Cart Validation; none grants our desired end-to-end interface. Ask the sponsor which surface is supported before building an adapter. The prototype is ready to show as a proposed native/approved-partner extension.

## Reproduce

From the repo, serve the existing build with `.venv/Scripts/python.exe -m gondola.api`, or `./scripts/dev.ps1 -Task api`. Build frontend changes from `web/` with `npm run build`.

```powershell
$env:GOOGLE_API_KEY=''; $env:ANTHROPIC_API_KEY=''; $env:GONDOLA_AGENTS=''
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/flex_evaluate.py
```

In a separate ordinary environment, `.venv/Scripts/python.exe scripts/flex_live_smoke.py` intentionally calls the configured model through the API. `.venv/Scripts/python.exe web/scripts/flex_e2e.py` verifies the running app, intentionally calls Gemini once, and refreshes the recording/screenshots. Never put the Google key in browser code or evidence.
