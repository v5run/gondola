# New avenues after the Rush Control demo

November 6, 2026. Historical exploration in response to the user's request to keep ideating. P13-P15 remain unbuilt; the user subsequently selected P16 and its [bounded first-party demo](../development/FLEX_DEMO.md) is now working/tested. No real merchant benefit or DoorDash access is established. Current implementation is in [the feature tracker](../development/FEATURE_COVERAGE.md). Root source index S81-S88 records the primary checks.

We now have a reservation engine, intervention tools, a policy lab and explicit negative results. New directions can give agents responsibility for finding failure modes, acquiring decision-relevant evidence or constructing the operating model itself. They do not need hardware or mobile development. Three are different agent roles; the fourth is explicitly a refinement of an existing negotiation idea.

## P13 - Discover how tonight's plan fails, then prepare a conditional response

**Merchant responsibility:** Before service, identify plausible combinations that make an otherwise reasonable plan fail, and prepare checked responses. During service, activate a response only when its observable trigger occurs.

**Illustrative episode:** Normal staffing and a fryer slowdown each look manageable separately. A particular item mix plus packing congestion exposes a long pickup wait under the current policy. An agent searches variations, replays the failure, isolates the cause, and proposes a conditional reserve/offer/admission rule. A judge changes conditions; the plan changes with evidence. These outcomes are proposed demo cases, not results already found by an agent.

**Why an agent:** Choose the next experiment from prior failures, inspect traces, reduce a complicated failure to a small reproducible case, formulate a conditional repair and test whether it moves harm to other channels. Deterministic simulation and independent validators retain authority.

**First test:** Reuse the current engine. Give the search agent a bounded realistic scenario space and a fixed run budget. Compare failure-search coverage with random sampling and a conventional designed scenario grid under the same budget. Have a separate policy agent propose a bounded rule; freeze it before unseen evaluation. Measure discovery rate, plausibility, new failures, base promises, worst/percentile wait, contribution, intervention cost and runtime. Searching catastrophic impossible kitchens alone earns no credit; harmless/no-op cases matter too.

**Important boundary:** The adversary can choose evaluator conditions, but the operating controller sees only observations available at each minute. Test generation, operating policy and evaluation must not share hidden future truth. A contingency cannot assume staff/equipment that do not exist. A modeled robustness result is not a guarantee about real service.

**Closest overlap:** [SimWell](https://www.simwell.io/resources/case-studies/qsr-store-prototype-breaking-point) already describes restaurant simulation and AI staffing search. [Adaptive stress-testing research](https://arxiv.org/abs/2505.05665) already searches perturbed planner observations. The opportunity hypothesis is merchant-specific, automatically discovered failure → minimal explanation → conditional intervention → independent retest. It is not inventing simulation or adversarial testing.

**Relationship/effort:** Deepens our policy-lab direction (R04/R05); unimplemented. A bounded experiment can reuse most current simulator/evaluation infrastructure. Real operating envelopes and external validation are the larger dependency. Preferred near-term technical experiment, subject to the comparison actually supporting it.

## P14 - Decide which missing fact is worth finding out

**Merchant responsibility:** Prevent decisions from confidently relying on stale or uncertain operational facts, while avoiding endless polling or manager questions.

**Illustrative episode:** A station appears overloaded, but some accepted orders have ambiguous cancellation/completion state. Weather, courier updates and a fresh KDS/POS snapshot are available at different latencies/costs. The agent considers which answer could change a pending feature/admission decision, checks that source, updates uncertainty, and either acts or stays conservative. It does not guess a completion from an unobserved simulator field.

**Why an agent:** Frame hypotheses about incomplete heterogeneous records, choose queries that could change the action, compare their decision value to time/call/attention cost, and stop when further information is immaterial. Generic confidence scores or calling every API are insufficient evidence of value.

**First test:** Provide explicitly mocked read tools with known freshness/reliability and declared costs; the private evaluator alone knows what happened. Compare refresh-everything, fixed freshness rules, ask-on-uncertainty and a decision-aware policy under the same resource budget. Measure decision regret, wrong actions, latency, calls and owner interruptions. Include cases where no question is needed, the right source is unavailable, and fetching everything is cheap.

**Kill condition:** If inexpensive fixed polling gets equivalent decisions, use it. Do not manufacture an expensive-API problem solely to make the agent win. Source reliability must be calibrated rather than an LLM's invented confidence percentage.

**Evidence:** [Value-of-information research](https://arxiv.org/abs/2601.06407) formalizes the risk/user-cost tradeoff for agent questions. It does not prove this restaurant application. [Deliverect Autonomous Support](https://help.deliverect.com/en/articles/12960468-solve-order-issues-with-ai) already diagnoses failed orders and offers sync/snooze/republish permissions; do not repackage generic order repair as novel.

**Relationship/effort:** A more concrete decision-relevant evidence acquisition extension of the earlier attention/signal-investigation direction (R02/R03/R06), not an additional restaurant dashboard. Browser fixtures can test the mechanism; actual POS/KDS access remains separate. No new staff counting task or hardware assumed.

## P15 - Compile a restaurant's operating knowledge into an executable model

**Merchant responsibility:** Make the scheduler/offer checker usable for a second restaurant without a developer hard-coding its recipes and resource assumptions.

**Illustrative episode:** Upload a small menu, declared recipe/prep instructions and a few observed task traces. The agent derives a typed task/dependency/resource model, attaches evidence to each field, flags contradictions, and asks only for missing facts that change the answer. A recipe modification or unavailable resource produces a revised model and a tested schedule.

**Why an agent:** Interpret heterogeneous existing operating knowledge and construct an inspectable representation that tools can execute. A bounded model can express, for example, an occupied burner during an unattended stage while the cook becomes available elsewhere; the current one-cook-task-per-item model cannot express this.

**First test:** Two deliberately different restaurant fixtures, with the second held out until after initial implementation. No restaurant-specific code edits on the second case. The agent emits a restricted typed task graph with units, provenance, approved bounds and dependencies. Independent validators reject cycles, unsupported resources and missing critical facts; small hand-computed schedules test semantics. Compare hand-built configuration and straightforward extraction. Measure correct executable constraints, setup effort, question count and resulting scheduling/admission errors, not just document parsing accuracy.

**Important boundary:** A menu or food photo cannot establish real station capacity, durations or physical workflow. Supplied documents/traces must support those facts; otherwise they remain unknown. No generated arbitrary code runs with secrets or external write permissions. This proposal builds a declarative operational model first, not an unrestricted coding agent.

**Closest overlap:** [Kueso](https://www.kueso.ai/how.html) already ingests restaurant recipes/SOPs and creates operational knowledge; [Levee](https://levee.io/platform) markets computable operational models in hospitality. The specific hypothesis is a source-grounded model that passes independent execution checks and directly drives our resource decisions. Broad document onboarding and digital twins are established concepts.

**Relationship/effort:** Concretizes our earlier missing-tool/operating-model direction, rather than claiming a wholly unrelated discovery. More ambitious than P13; requires extending the task engine beyond its currently fixed schema. Browser-only demo is possible with labeled documents and no physical setup. Unimplemented.

## P16 - Buy back time through voluntary customer flexibility (existing-idea refinement)

**Latest user preference:** User says this is the best of the four avenues and asks whether it is already a DoorDash feature. [Native-feature, prior-art and integration assessment](PICKUP_FLEXIBILITY.md): the broad business idea is established, exact dynamic DoorDash pickup-incentive behavior is unverified, and the proposed customer offer/reservation workflow plus agent is unbuilt. Preference does not establish a selected build spec or API access.

**Merchant responsibility:** When capacity is genuinely insufficient, seek a feasible agreement with flexible first-party customers instead of silently moving their orders behind others.

**Illustrative episode:** Before accepting a new first-party order, offer a checked later window with a bounded benefit, or a feasible menu alternative. A declared customer preference determines acceptance; nothing is assumed from their spending or guessed urgency. For already accepted work, a separate explicit opt-in workflow can request a change; silence or rejection keeps the original commitment.

**Why an agent:** Explore feasible combinations of time/menu/incentive within owner limits, explain them and negotiate supported choices. Deterministic tools reserve approved capacity and money only on acceptance; they expire unused quotes and handle concurrent customers.

**First test:** A browser buyer view and a merchant view, plus configurable synthetic customer preferences. Compare fixed quotations, uniform delay offers and bounded negotiation. Measure feasible completed orders, consent/decline, incentives, original and revised commitment outcomes, fairness and buyer interaction burden. Count lateness against original promises separately so renegotiation cannot cosmetically erase failure. Include no-flexibility and no-affordable-solution cases.

**Overlap/relationship:** This is P05 and the earlier feasible-order negotiation direction made concrete for our current stress-case weakness, not a new independent idea. [Thanx RecoveryAI](https://www.thanx.com/blog/introducing-recoveryai) already automates contextual first-party guest recovery/credits; generic apologizing or refunds are not the distinction. The proposed capacity reservation and voluntary pre-commitment tradeoff need their own evidence. No Marketplace customer-contact or order-change permission is assumed.

## Current recommendation

The user selected P16, voluntary flexibility, and its [bounded demo is built and tested](../development/FLEX_DEMO.md). Exact native overlap and approved integration access remain unresolved. Earlier assistant recommendations were P13 for a near-term technical experiment, P15 for generalization and P14 for evidence acquisition; these remain alternatives. None is a promise of novelty, commercial demand or superiority to simpler methods.

Ideas screened out as standalone new pitches: generic causal promotion optimization (DoorDash already publishes it), generic AI order-repair support (Deliverect), generic guest recovery (Thanx), generic restaurant simulation (SimWell), and document Q&A alone (Kueso). Sources establish overlap in described capabilities; vendor descriptions were not product-tested.

No product code, fixtures, paid model runs, external messages, partner API calls, commit or push were performed in this ideation pass. Feasibility descriptions are proposed tests, not completed results.
