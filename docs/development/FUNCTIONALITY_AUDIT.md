# Functionality and differentiation audit

Audited November 5, 2026 at baseline `application-baseline`. Scope: source inspection, local offline execution, existing tests, browser interactions, isolated adversarial probes, and current public competitor documentation. No live model/merchant credentials or customer deployment was tested.

**November 6 verification update:** The user's locally configured Google key passed basic generation and a real ADK Ask tool round trip. The app endpoint returned `mode: adk` and the correct fixture order count in 5.36 seconds using `gemini-3.1-flash-lite`. The full live close graph and merchant integrations remain untested; the findings below describe the November 5 audit. See [local setup](LOCAL_SETUP.md) for configuration and evidence.

## Assessment

Gondola is a functioning, cohesive prototype with a strong demonstration surface. It has real analytics, forecasting, optimization, reporting, and simulation code. Its individual capabilities overlap established restaurant products. **The current close-out agents primarily explain a deterministic plan; they do not yet own an adaptive managerial objective.**

The most useful differentiation work is to connect the existing tools into a persistent, constrained decision-and-action loop that responds to changed facts, verifies outcomes, and asks the owner for judgment selectively. This is a proposed direction, not proof that competitors lack it.

## What was verified

| Capability | Observed state | Important boundary |
|---|---|---|
| Tonight / Insights | Working live-paced order replay, charts, date navigation, drill-down explanations | Generated Hanabi Ramen data; the displayed clock is a replay clock |
| Close shift | Fresh forced run completed through SSE and persisted findings | Fixed dependency graph in `pipeline.py`; no live LLM configured |
| Books | Cash variance, payout matching, evidence/draft dispute view | Fixture contracts/fees; no submitted disputes or bank connection |
| Stock | Recipe-based ledger and limited-item count input | Inferred inventory; not independent observation of physical stock |
| Demand | LightGBM forecasts, ranges, similar days, cached backtests | Synthetic store; source-generated weather/event data, not current external feeds |
| Tomorrow | Prep-card editing, pause-time preview, run-bound approval | Core limited-item path and economics are hard-coded to chashu |
| Prep/staff planning | Real newsvendor and OR-Tools calculations | Task list, cooks, costs, and staffing assumptions are largely fixed |
| Service | Interactive replay, recount prompt, simulated availability changes, comparison counters | Replay does not invoke `AppPauseExecutor`; reduction in fixture cancellations is not observed merchant benefit |
| Ask | Working offline intent router; ADK read-tool agent defined and fake-model tested | Real model quality untested; no durable conversation/case memory |
| Reports | History, filters, rebuild, fresh readable two-page PDF | Historical files are generated fixtures; rebuild verified locally |
| Alerts | Bundled outbox and simulated SMS reply workflow | Real messaging adapters exist but are unconfigured and untested |
| Integrations | Square/DoorDash adapters and mocked integration tests exist | Status reports credentials configured, not service reachability; API replay is not a live connector exercise |

Execution evidence: 86 Python tests passed; all 13 browser checks passed; frontend TypeScript/build passed; pip consistency passed. Screenshots of Tonight and Tomorrow were visually inspected. Fresh close and PDF smoke evidence is in `.local/audit-probes.json`. The full evaluation script was **not** rerun; checked-in `out/eval.json` is inherited evidence, not a newly measured result.

## Gaps and reproduced failures

### A1 - Fixed workflow agents, limited decision authority

`gondola/pipeline.py:431` computes the plan before `_agent_wording` is called. `gondola/agents/adk_graph.py:168` builds a fixed Sequential/Parallel graph. Plan exposes a newsvendor tool; Sentinel and Guard are instructed to explain/restatement rather than act. This is a valid architecture for reliable numbers, but eight specialist labels do not establish autonomous management or replanning. Ask uses read tools and a fresh in-memory session (`adk_graph.py:273`).

### A2 - Demonstrated availability changes are simulated

`gondola/api/app.py:699` starts `guard_live.run_replay`. That loop emits local pause/availability events without calling the DoorDash adapter. The adapter exists separately in `gondola/integrations/doordash.py:51`. A live UI connected to a real local API is still a synthetic replay, not a live merchant integration.

### A3 - Missing recount receives hidden simulator truth

`gondola/api/guard_live.py:94` substitutes `true_left` plus small noise if the manager does not answer within 20 simulated minutes. Hidden world state is legitimate for simulating outcomes, but it is not an observation available to the controller. This fallback overstates performance under missing information. Keep belief uncertain, choose an explicit fallback, or model a separate staff observation as a labeled input.

### A4 - Failed writes cannot retry; pause/restock/pause is suppressed

`AppPauseExecutor._log` adds every key to `seen`, including failed attempts. Its key contains store/date/item/channel/active state. An isolated fake connector reproduced:

- Temporary failure -> retry returns `duplicate_ignored`; connector called only once.
- Pause -> restock -> pause returns `ok`, `ok`, `duplicate_ignored`; connector ends active although the desired final state is paused.

The probe used temporary files and a fake client; no external call occurred. Action identity needs to represent the intended transition/operation, and unsuccessful attempts must remain retryable. Add read-back before asserting final state.

### A5 - Numeric membership is not semantic evidence

An isolated probe passed `Revenue increased by $23.50.` with only `cash_difference: -23.50` as evidence. `guardrails.check_numbers` returned `ok: true`. The checker matches numeric magnitudes; it does not verify metric identity, sign, date, channel, units, or causality. Its current fallback is useful but cannot substantiate the broad claim that every statement is source-grounded.

### A6 - Readiness inputs and durable work are missing

No supplier-delay/staff-availability event intake, owner mandate, dependency invalidation/replanning, or persistent outstanding-obligation engine was found. `morning_pass` is defined but has no scheduler wiring in the audited app. Live runs and ADK sessions are in memory. These are the principal gaps relative to our owner-off-duty direction.

### A7 - Operational assumptions are embedded in code

Examples: `pipeline.py:188` fixed staff capacity, `pipeline.py:192` fixed prep tasks, `tools/plan.py:13` fixed chashu costs/risk, and `tools/books.py:15` fixed channel commissions. Porting to a second merchant requires configuration/data modeling rather than another dashboard.

## Current competitor comparison

These are primary vendor descriptions, not independent product tests. An undocumented feature is unknown, not absent.

| Area | Existing alternative | Consequence for Gondola |
|---|---|---|
| Forecast -> prep/order/labor | [ClearCOGS](https://www.clearcogs.com/) describes this daily workflow | Forecast charts plus prep sheets are category features |
| Predictive procurement | [Supy](https://supy.io/product-features/ai-predictive-ordering) describes forecast/stock/delivery-aware ordering | Adding a purchase-order generator alone is insufficient |
| Cross-channel rules, stock pauses, AI assistance | [Sinqro automations](https://www.sinqro.com/en-us/solutions/automations) describes rule execution, stock actions, prep guidance, AI Inventory/Pricing Agents, and historical testing | Manual-rule-only competitor assumptions are outdated; a US-language page exists, though actual merchant coverage was not tested |
| Connected restaurant agents / financial analysis | [Loop AI](https://www.loopai.com/) markets finance, marketing, operations, and connected business data | Generic "AI restaurant manager" positioning is occupied |
| Payout discrepancy analysis | [Otter reconciliation](https://helpdesk.tryotter.com/hc/en-us/articles/18163188728339-Financials-Reconciliation) has previously documented calculated versus paid amounts | Exact accounting/record reconciliation is useful infrastructure, not established uniqueness; direct refetch was access-redirected this session |

The inherited `docs/scope/whitespace.md` uses claims such as "UNOCCUPIED" and "unshipped everywhere". Those are too strong for the evidence. Preserve it as historical research; use this qualified comparison for current decisions.

## Differentiation to pursue

Keep the existing analytical tools and useful interface. Add one owner-mandated operating episode with changing facts and verified execution. The compelling claim to test is **fewer avoidable owner interventions while still meeting operating constraints**, rather than more agents or more feature screens.

Recommended episode: plan tomorrow, receive a supplier-delay message and a staffing change, gather missing evidence, revise dependent tasks and a purchase draft within policy, verify updates, and surface only a genuinely unresolved tradeoff. Tools should execute state changes; the model should choose a supported course of action. No automatic financial or messaging action is needed for the initial browser demo.

See [the proposed tickets](BACKLOG.md) for acceptance criteria and ordering. No claim of unique market functionality or commercial ROI is made from the local tests.
