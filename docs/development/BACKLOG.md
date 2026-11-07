# Proposed development tickets

For the current product shortlist, read [leading ideas](../ideas/LEADING_IDEAS.md). This backlog records the earlier manager-feature proposal. The user subsequently requested more ambitious capabilities and introduced an ETA-aware kitchen scheduling candidate; no replacement build is selected yet.

November 5, 2026. Local drafts for discussion; no GitHub issues have been created. Based on [the source/runtime audit](FUNCTIONALITY_AUDIT.md). Effort is a rough estimate of focused agent-assisted work, not a delivery promise. The selected project is Gondola; this ticket ordering is advisory.

November 6 update: the user's local Google key passed a real ADK Ask tool round trip and the running API returned `mode: adk`. OpenRouter support is now P2 for using event credits; it no longer blocks live model testing. Full live close quality remains unverified.

## Suggested next milestone

Demonstrate **one policy-bound manager responding to a changed supplier/staffing situation, completing supported changes, and asking one consequential owner question**. Preserve the existing analytics and UI. Avoid spending the next iteration on more charts or additional named specialists.

The compact path is TRUST-01, then POL-01 + AGENT-01 + EXEC-01 + EVAL-01. TASK-01 supplies restart/resumption depth if time permits. ENV-01 enables event credits when available; the other tickets strengthen generality and trust.

| Ticket | Priority | Effort | Purpose |
|---|---|---|---|
| ENV-01 | P2 | Small | Use the hackathon's OpenRouter key with the actual agent runtime |
| TRUST-01 | P0 | Small-medium | Make replay/observation/connection modes explicit and remove the recount oracle |
| POL-01 | P1 | Medium | Give the owner an editable operating mandate |
| AGENT-01 | P1 | Medium-large | Replan across dependent tasks when a new event changes the facts |
| EXEC-01 | P1 | Medium | Repair action retries, state transitions, and verified completion |
| EVAL-01 | P1 | Medium | Demonstrate useful autonomy against simple baselines |
| TASK-01 | P1 | Medium | Persist outstanding obligations and resume after updates/restarts |
| ATT-01 | P2 | Medium | Ask the owner only questions that change consequential decisions |
| PROOF-01 | P2 | Medium | Ground claims in the right metric, sign, units, and records |
| GEN-01 | P2 | Medium | Move merchant/item/economic assumptions out of code |
| ENV-02 | P2 | Small-medium | Reproduce the environment and address dependency advisories |
| ALLOC-01 | Research / later | Medium-large | Evaluate economically justified channel allocation without pretending 86ing is novel |

## ENV-01 - Add an OpenRouter-compatible model provider

**Problem:** The organizer's linked Tech Guide promises a team OpenRouter API key at event start; the application reads Google/Anthropic credentials only. Provider access is a setup gap, not a product differentiator.

**Scope:** Add server-only `OPENROUTER_API_KEY` and explicit model configuration using a supported ADK adapter. Preserve offline operation and direct providers. Select a tool-capable model from current provider metadata instead of inventing a model ID.

**Acceptance:** Both Ask and the close graph use the selected provider; status separates configured/requested from a verified model call; no key is exposed in browser responses/logs. Mocked provider/tool-call tests cover failures and fallback. When a key is available, record one successful real tool round trip and token/cost evidence separately from fake-model tests. Absence of a key must remain an honest unverified state.

## TRUST-01 - Distinguish simulated world state from agent observations

**Problem:** Live-paced replay and real local API responses can appear like live merchant data. In `guard_live.py`, an ignored count request becomes hidden simulator truth after a delay.

**Scope:** Show source/connection mode in the UI and trace. Keep simulator demand/outcomes separate from controller-accessible observations. Replace the no-response oracle with a defined uncertainty-preserving fallback or separately injected, labeled observation.

**Acceptance:** An unanswered recount never changes belief using `true_left`. A hidden-truth change alone does not become agent knowledge. The UI distinguishes replay, uploaded records, sandbox, and verified live data. Existing replay controls remain useful. A test compares requested, actually observed, and assumed counts.

## POL-01 - Owner mandate and constraint validation

**Problem:** Costs, cooks, tasks, commissions, and alert thresholds are embedded in code; no owner operating objective is represented.

**Scope:** Introduce a versioned merchant policy covering the chosen demo goal, purchasing allowance, staffing/working limits, service commitments, permitted actions, and escalation conditions. Start with explicit structured fields; natural-language preferences can be parsed into an editable proposal.

**Acceptance:** Every proposed action references the active policy version and validated preconditions. Conflicting constraints return a clear infeasible tradeoff. The agent cannot silently relax a budget or service commitment. Two merchant policies applied to the same inputs can produce appropriately different decisions. Show these decisions in the existing Tomorrow/Close workflow.

## AGENT-01 - Event-driven decision and replanning loop

**Problem:** The fixed close pipeline computes results before ADK wording; a supplier delay or roster change does not invalidate and repair the plan.

**Scope:** Add a small event/observation contract, initially a supplier-delay notice and staff-availability change. Let the agent gather relevant evidence, call analytical tools, compare feasible alternatives, propose a new plan, and execute supported actions under POL-01. Keep numerical optimization in code.

**Acceptance:** An event injected after planning invalidates only affected assumptions/tasks, produces a new plan version with a reasoned diff, and updates tool-backed state. A stale approval cannot authorize changed work. A held-out combination of events is handled through the same tools, rather than a canned scenario response. An impossible case produces an owner decision instead of a fictitious successful plan.

## EXEC-01 - Transition-aware, retryable, verified actions

**Problem:** Audit probes reproduced failed writes being permanently deduplicated and pause/restock/pause leaving the item active. Service replay never calls the live adapter, so local animation is not action verification.

**Scope:** Separate an intended operation, individual attempts, desired state, and observed external state. Keep preview/replay distinct from executing an adapter. Use the existing executor boundary with appropriate retry/read-back semantics.

**Acceptance:** A transient failure can retry and succeed; replaying the same completed operation does not duplicate it; pause -> restock -> pause performs all three intended transitions. Provider acknowledgement without read-back is not labeled verified. Partial multi-channel failures remain open. Test entirely with fake adapters; test one real sandbox connector only when access and merchant/item mappings exist.

## EVAL-01 - Autonomy and owner-attention benchmark

**Problem:** Current tests prove many useful mechanics, but synthetic-year performance and scripted fake models do not establish adaptive manager quality.

**Scope:** Build a small independently specified scenario set: supplier delay, staff change, conflicting budget/service constraints, ambiguous record, failed write, and missing response. Compare a static plan, ask-on-ambiguity workflow, and candidate agent. Retain a held-out combination.

**Acceptance:** Report supported task completion, constraint violations, factual errors, unresolved commitments, action verification, owner questions/time, and model cost/latency. Include a necessary escalation case; an agent that never asks and silently violates constraints must fail. Controller tools cannot read evaluator truth. Publish measured results and source modes instead of inheriting checked-in `eval.json` as fresh evidence.

## TASK-01 - Durable cases, deadlines, and resumption

**Problem:** Runs and ADK sessions are in memory. `morning_pass` exists without an active scheduler. The app does not own unresolved obligations across time.

**Scope:** Persist the selected workflow's tasks, current evidence, deadlines, waiting conditions, action attempts, and owner decisions in a small durable store. Resume on a relevant observation or due follow-up. A separate cloud service is unnecessary for the local demo.

**Acceptance:** Restarting the process preserves waiting work and avoids duplicate actions. A new supplier confirmation or payout report resumes the affected case. Creating a draft is distinct from completing a task. Missed deadlines surface with reasons. The UI shows what is waiting, what was verified, and what still requires the owner.

## ATT-01 - Decision-value-based owner questions

**Problem:** Bundled threshold alerts reduce message volume but do not decide whether a question is worth the owner's attention.

**Scope:** Track uncertainty and competing feasible actions. Seek available digital evidence first; ask a targeted question only if the answer can materially change a consequential decision or is required by the mandate. Group related questions and support a configurable attention budget.

**Acceptance:** An ambiguous fact irrelevant to the chosen action does not trigger a question. A policy-changing tradeoff does. Ignored questions preserve uncertainty and leave work pending or use an allowed fallback. Evaluate questions jointly with errors and completion; fewer questions alone is not success. This evolves Count Next's useful principle within the broader manager.

## PROOF-01 - Semantic claim provenance

**Problem:** The numeric guardrail accepts a revenue claim backed only by an equal-magnitude negative cash variance.

**Scope:** Represent important claims with metric identity, signed value, currency/unit, store/channel/date, source rows, and any validated derivation. Render numeric factual statements from these records or validate structured model claims against them.

**Acceptance:** Swapped metrics, reversed signs, wrong channel/date, unsupported arithmetic, and causal assertions without appropriate evidence are rejected or labeled uncertain. The audit's `$23.50` counterexample fails. Each consequential decision can expose its supporting records without dumping an entire trace on the owner.

## GEN-01 - Merchant and recipe configuration

**Problem:** The coherent demo revolves around one item and a fictional store. The next menu or merchant needs code changes.

**Scope:** Move limited items, recipes, yields, task dependencies, capacity, fees, and risk assumptions into validated configuration. Provide one additional small merchant/menu fixture rather than attempting every POS format.

**Acceptance:** The same manager handles two merchants without item-name conditionals. Missing mappings are explicit; quantities and units are validated. Assumptions carry source/confidence. A physical count workflow is optional, and uncertainty must remain visible when no observation is available.

## ENV-02 - Reproducibility and dependency maintenance

**Problem:** Python dependencies use lower bounds; installed versions already emit deprecation warnings. The frontend audit reported 1 high and 3 moderate advisories, with suggested major upgrades.

**Scope:** Choose/pin a supported dependency set, document model/provider versions, update the frontend dependencies in a separate reviewable change, and keep development/build outputs distinct from source evidence.

**Acceptance:** A fresh environment reproduces build/tests; the browser flows still work after upgrades. Record advisory changes and remaining limitations. Do not use a forced package upgrade as a substitute for migration verification. Keep local secrets and virtual environments excluded.

## ALLOC-01 - Research dynamic channel allocation as a supported decision

**Problem:** The current replay pauses delivery apps to preserve stock for dine-in using fixed economics and assumed delays. Threshold 86ing is already offered by other products, including Sinqro; it is not a defensible novelty claim.

**Scope:** Investigate whether the manager can choose a better policy from confirmed stock, accepted commitments, demand uncertainty, channel contribution, and actual action latency. Include lost sales and excess withholding in evaluation, not only cancellation counts.

**Acceptance before promotion to a feature:** Beat fixed buffers and simple demand-aware rules on held-out scenarios without moving failures off the metric. Expose assumptions about contribution and risk. Establish whether the relevant connector can actually express/read back the chosen state. Present any advantage as measured in the test environment, not as proof of an unoccupied market.
