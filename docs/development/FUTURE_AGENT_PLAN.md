# Plan: make the Outlook agent the center of Future

**Original design plan.** A subset was subsequently implemented on the working branch; for actual behavior, tests and unresolved gaps, see [implementation and evidence](FUTURE_AGENT_IMPLEMENTATION.md). This document describes intentions and is not a claim that every proposed capability or acceptance criterion is complete.

## 1. The product idea

> “Future has an AI agent that investigates what could affect restaurant demand, weighs that evidence—including a separate statistical forecast—and produces an explainable outlook for today and tomorrow.”

The agent's job is to **gather, interpret and reconcile signals**, not just narrate a number an ML model already chose. For example, it can examine weather, nearby events, store context, historical comparisons, today's observed pace, and the LightGBM forecast. It decides which tools to use and what further evidence it needs. It produces a demand outlook, supporting evidence, assumptions, risks and uncertainty.

The existing forecast remains useful as **one tool-provided input**, and as a fallback if the agent cannot produce a valid result. The agent does not need to copy or agree with it. Numerical calculations and validation remain in code: an agent should be able to reason and propose, but not make unsupported facts true simply by saying them.

### Why we thought we already had this

The earlier [tri-workflow architecture](../architecture/TRI_WORKFLOW.md#4-future-the-rest-of-today-and-the-next-7-days) proposed an Outlook agent, but the [current feature record](FEATURE_COVERAGE.md#tri-workflow-future-added-november-7-2026) says it was deferred. Today, Future is LightGBM plus deterministic nowcasting and planning. It has an optional Open-Meteo weather adapter and a synthetic events table, but no running agent that discovers events. Outlook-related context and adjustment-reading scaffolding are not the agent itself.

## 2. Recommended hackathon scope

Build **one Outlook agent** inside the existing Future screens, for **rest of today and tomorrow**. Avoid building a swarm, expanding to seven days, or integrating merchant writes.

- **Events:** Use a purpose-built, explicitly labeled mock provider by default. It should return realistic event records—not canned agent conclusions—and support multiple scenarios, including a relevant event, a distant event, a cancellation and missing details. Align fixture dates/times with the selected demo/replay clock.
- **Weather:** The repo already has optional Open-Meteo code. Use fixture weather for reliable offline demonstration and optionally enable the existing adapter when the runtime can reach it. Label the actual source; the current adapter primarily feeds the tomorrow forecast, so today's agent weather needs an explicit source/tool too.
- **LLM:** Use the project's existing Google ADK agent plumbing and a configured model. A **real model using mock event data** is a valid agentic demo, but not live event discovery. A fake model is for offline tests and must not be displayed as a live agent run. If no model works, show the deterministic fallback, labeled as such.
- **Primary output:** The agent's checked outlook is the main Future result and, in the simulated demo, the intended planning input when its output and handoff pass the checks below. The ML forecast is available as one input and as a clearly labeled fallback—not the product's default protagonist.
- **Safety:** All downstream restaurant actions remain simulated/dry-run. This is not an authenticated production approval workflow or a real merchant integration.

### Is a real connection easy?

- **Weather:** Open-Meteo is promising because its official site says [1](https://open-meteo.com/) non-commercial access does not require an API key. There is already a repo adapter, but a real connection still needs a successful smoke test in the target runtime and appropriate attribution/terms review. This sandbox's outbound access is restricted, so do not promise a live call from here.
- **Events:** Ticketmaster's Discovery API documentation [1](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/) describes event search, requires an API key, and lists default limits. It is a plausible optional adapter if registration and access are quick; it will not represent every local event. Provider access, regional coverage, terms and an actual successful call remain unverified. No need to make this a blocker.

**Recommendation:** Build and demo the agent against mock events first. If time permits, try the existing weather connection and one event provider behind the same interface, with obvious source labels and a fixture fallback. No Google scraping or arbitrary browsing is needed.

## 3. How the workflow should work

```text
           Weather tool ─────────┐
           Event search/details ──┤   live OR labeled fixtures
           Store hours/location ──┤
           Historical analogs ────┤
           Today's actual pace ───┤
           Existing ML forecast ──┤   one estimate, not ground truth
                                  ▼
           Outlook agent chooses tools, investigates, compares,
           forms a structured forecast/scenario and explains why
                                  │
                                  ▼
           Independent validation + reproducible calculations
                                  │
                   ┌──────────────┴────────────────┐
                   ▼                               ▼
         Valid agent outlook                Agent unavailable / invalid
         main Future output                  labeled ML/code fallback
                   │                               │
                   └──────────────┬────────────────┘
                                  ▼
                 Versioned forecast for demo consumers
                 Today / Tomorrow / prep / Present replay
```

A successful agent run should have meaningful choices: it may inspect an event's timing and venue, compare similar historical nights, check whether the ML model already accounted for the event, and decide a purportedly relevant signal is actually weak or irrelevant. It can challenge the ML forecast, not merely endorse it.

**Important:** the agent and ML can share inputs. They are **not statistically independent** simply because one is an LLM and the other is LightGBM. The agent must not blindly add rain or event effects on top of an ML estimate that already includes them. If overlap is unknown, acknowledge it and don't claim an isolated incremental effect.

### Forecast and uncertainty

The agent produces structured inputs to a calculation tool, such as selected comparable days, relevant time window, signal identity, and an evidence-linked scenario. Code computes or reproducibly checks quantities. When evidence is thin, the agent can explain qualitative upside/downside, present clearly identified **assumption-based scenarios** where the parameters and origin are visible, or abstain; it must not invent a precise impact and present it as a historical fact.

The agent's central estimate and range are the **primary agent-informed demo forecast** when valid. A range derived from assumptions is labeled a *scenario range*, not a calibrated P10–P90 interval. A statistically calibrated interval requires historical evaluation; do not simply copy the ML interval or average two sets of quantiles. If consumers require P10/P50/P90, define an explicit versioned conversion and label its assumptions, or keep the existing forecast as fallback until a usable range exists.

## 4. Example interaction

**Entirely illustrative: the numbers and event below are made up, not a measured result.**

1. For tomorrow, the agent searches the **mock events** tool and finds a concert near the fictional store. It checks time, venue, distance and status; it also finds a second, cancelled event and excludes it.
2. The agent asks for weather and comparable historical dinner periods. It checks the statistical forecast: LightGBM estimates **600 completed orders**. Its feature record shows rain is already represented but this concert is not.
3. The agent asks an analytical tool for a relevant comparison. Suppose the tool returns an estimate consistent with an **additional 20 orders** in a particular dinner window, with small sample size and uncertainty. The agent proposes a scenario of **620 orders**, explains that it used the ML estimate as one anchor, and cites the comparison and mock event. Code verifies the arithmetic and links the quantities to the correct evidence.
4. The validated agent forecast appears as the main demo outlook; the UI also shows the 600-order ML input and why the agent differed. The updated forecast propagates consistently into the simulated prep and Present views, with uncertainty labeled honestly.
5. If the event was already in the ML features, the historical comparison did not isolate the effect, or the evidence was too thin to support that change, the agent must not claim an additional 20 orders as established fact. It can show an assumption-based scenario or abstain; the validator/fallback rules determine what planning uses.

A real run may make a different decision. The example illustrates the interaction, not a scripted answer or guaranteed causal effect.

## 5. Tools and records

### Read-only tools for the agent

| Proposed tool | Purpose and boundary |
|---|---|
| `search_events` / `get_event_details` | Return bounded mock or approved-provider records with IDs, source mode, location, local time, status and retrieval time. Detail calls take IDs returned by search, not arbitrary URLs. Empty results do not prove no events exist. |
| `get_weather` | Return the selected fixture or verified live forecast, source, issue/retrieval time, coverage and freshness; missing data stays missing. |
| `get_store_context` | Return the authorized store's configured location, time zone, hours and limited aggregate channel context—no customer records or secrets. |
| `get_historical_analogs` | Query bounded, store-scoped, pre-cutoff aggregates; return dates, sample sizes, comparison definition, order counts and stockout limitations. Associations are not causal proof. |
| `get_current_pace` | Return completed orders and expected pace available at the cutoff. Distinguish completed sales from received orders and hidden demand. |
| `get_ml_forecast` | Return the separate forecast, range, as-of time, version and the features/sources actually used. Unknown feature overlap must be explicit. |
| `calculate_scenario` | Compute quantities from referenced evidence and explicit assumptions under a versioned method; return derivation, limitations and uncertainty type. It cannot manufacture missing evidence. |

The agent should choose which calls are useful and may obtain the ML forecast at any point. To assess whether it is adding reasoning rather than automatically copying ML, test an **ablation without the ML tool** as well as the normal flow. That ablation is an evaluation, not a mandatory order of operations in the product.

### Proposed forecast record

Record a versioned snapshot containing store scope, business date and cutoff; selected observations and provider IDs; source mode (`fixture`, `live`, `cached`, `unavailable`) **and the original provenance of cached data**; timestamps/expiry; agent tool trace; ML reference if used; assumptions; evidence-linked signals; overlap assessment; calculated result and uncertainty type; validation outcome; and which forecast actually powers each demo consumer. Never put keys in the trace.

Distinguish **source facts** (“the event starts at 7”) from **model interpretations** (“it might affect dinner demand”) and **calculated or assumed quantities**. Validate IDs, dates, units and claim-to-source meaning—not just whether the same number appeared somewhere in a tool response. The existing numeric guard is not sufficient for semantic verification.

## 6. Demo handoff and fallback rules

1. Run the agent on demand or a defined refresh schedule; freeze a snapshot of its tool results, ML input, time cutoff and output version. Avoid rerunning it for every Present replay minute.
2. Validate the output schema, finite/non-negative numbers, range ordering, relevant date/time window, evidence references, overlap, policy bounds and calculation provenance. Distinguish evidence-backed values from explicit assumptions. Reject unsupported factual claims; do not silently convert a qualitative warning into a precise lift.
3. When a valid result supplies the required total, time/channel shape and usable uncertainty representation, publish it as the **primary agent forecast** for the simulated demo. The UI identifies its source, snapshot/version, assumptions and exactly what is used downstream. Start with a clear versioned rule for translating a daily result into bins; a day-total change must not be applied twice to the existing nowcast. Preserve completed actuals and the partial current bin.
4. Feed the same accepted snapshot into Future, prep cards and Present's `arrivals` path. Define when a new snapshot takes effect, invalidate the relevant caches, record issuance, and test that displayed totals and downstream bins reconcile. The scenario/range method must be explicit—do not label uncalibrated scenario bounds as measured coverage.
5. If the model/provider is unavailable, required evidence is missing, the output fails validation, or a necessary bin/range conversion is not available, show **“agent unavailable / unquantified; using ML fallback”** with the reason. A last valid snapshot may be used only within a defined freshness policy, with a stale badge. No silent substitution or invented default events.

This is a prototype/simulation rule, not permission to use an unvalidated forecast for a real restaurant. Before **real operational reliance**, require the evaluation and production controls in §§8–9. Suggestions, simulated prep and local approvals do not grant authority for real merchant changes.

## 7. Implementation stages

| Stage | Work | Acceptance |
|---|---|---|
| **1. Signals and fixtures** | Define an evidence schema and create the mock events adapter; connect it to explicit demo-clock scenarios. Wrap the existing weather adapter with a labeled fixture fallback. | Test time zones, relevance, cancelled/duplicate events, empty/stale data, source mode and provider failure. Real event-provider access is optional. |
| **2. Agent and calculations** | Add one ADK Outlook agent and typed read-only tools; implement an evidence-linked scenario calculator and independent validator. Include the existing ML forecast as a tool. | Fake-model tests prove wiring/validation; a separately recorded real-model run, when available, demonstrates unscripted tool choice and interpretation. Include an abstention case and a held-out event combination. |
| **3. Forecast handoff** | Publish a versioned agent result for today/tomorrow; explicitly map it to total, bins, channels and uncertainty. Preserve the ML fallback. | Future screens, prep and Present replay consume the same valid snapshot; outputs reconcile; invalid/stale results fall back visibly; no live merchant changes. |
| **4. Interface and demonstration** | Put the agent outlook first in Future; display signal evidence, trace, uncertainty, ML input, fallback and source mode. | A manager can trace why the result changed and distinguish real model calls, mock events, live weather and fallback. UI does not claim unmeasured model accuracy. |
| **5. Evaluation and optional live adapter** | Evaluate using the same as-of fixtures and try a read-only event provider only if access is quick. | Record results and any real request separately; provider unavailable is not a failed core demo. |

Likely touchpoints: `gondola/future/` for adapters/agent/scenario, `gondola/api/tri_future.py` for explicit run/status endpoints, `gondola/present/service.py` and cache logic for handoff, `web/src/screens/RestOfToday.tsx` / `Tomorrow.tsx` for presentation, and new focused tests. Reuse ADK patterns from `gondola/review/llm.py` and `gondola/agents/adk_graph.py`; the existing code does not implement this agent today. Update [feature coverage](FEATURE_COVERAGE.md) as implementation milestones are verified.

## 8. How to test that the agent helps

**Capability:** Fake-model tests exercise contracts and security, but don't prove reasoning. If a real model is available, record a sanitized tool-use run showing that it selects and uses tools, recognizes relevance/cancellation/overlap, cites evidence and can abstain. Include a scenario not scripted into the prompt. Test the same setup with the ML tool removed to see whether the agent can use other signals meaningfully.

**Forecast quality:** On the same time-cutoff snapshots, compare (A) existing ML/nowcast, (B) a straightforward deterministic rule using the same available signals, (C) the agent with ML as an input, and (D) the agent without ML. Report error, bias, range coverage and width where a statistical range exists, along with abstentions/fallbacks, latency and cost. Compare simulated prep/headroom outcomes as well. A compelling explanation or successful tool call is not proof of better forecasting.

**No look-ahead:** Replay must give the agent only signals available at that historical time. Save immutable event/weather snapshots and keep future orders and evaluator truth outside the agent's tools. An event or weather record obtained after an outcome is not necessarily what was knowable beforehand. Current demo filtering uses order creation time but may expose an earlier-created order's final status; this is not a complete event-time guarantee. Synthetic event fixtures and outcomes show behavior, not real-world predictive lift.

**Demo acceptance:** Agent-primary display and simulated handoff work; signals and sources are truthful; unsupported outputs fail safely; a cancelled or duplicate event is not presented as a real driver; overlapping ML inputs aren't double-counted; agent failure visibly falls back; no merchant writes are enabled. Before presenting a result as a proven improvement—or relying on it in a real restaurant—require a pre-declared, time-held-out evaluation against both ML and a simple same-input rule, plus measured calibration and operational tradeoffs. If it fails, revise the method rather than disguising the outcome.

## 9. Security and production boundary

For the demo, retain loopback-only serving, synthetic restaurant data, dry-run notifications and blocked merchant writes. Tool functions are read-only and narrowly scoped; no agent-selected URLs, shell, SQL, filesystem, keys, customer data or hidden simulator truth. Limit tool calls, execution time, tokens, cost and response size. Treat provider text as untrusted instructions; code—not the model—enforces the tool permissions and schema. A real provider adapter needs a fixed destination allowlist, redirect/address validation and protections against private-network/SSRF access. Test prompt injection, bad data, stale snapshots and cross-store attempts.

These controls are not an OS sandbox: ADK currently runs in the app process. Real deployment still needs authenticated store/tenant isolation, isolated short-lived agents, restricted egress, encrypted storage and transport, and a separately enforced manager approval/execution boundary for live changes. See the [security design](../strategy/AI_AGENT_SECURITY.md).

## 10. Remaining choices

- **Demo scenario:** Which event types best show relevance and a counterexample? Recommendation: one nearby concert, one distant or cancelled event, and a weather change, all clearly synthetic.
- **Agent run:** Which configured model and environment can execute a real tool-use run? If unavailable, keep the fake-model tests and label the offline fallback.
- **Forecast publication:** Agree on the first version's explicit scenario-to-bin and uncertainty method. When those inputs cannot be validated, the demo falls back visibly rather than pretending an agent scenario is fully operational.
- **Optional live events:** Try Ticketmaster only if a key and access are readily available; otherwise keep the mock. No key or provider approval is assumed.

## Repository pointers

- [Current Future presentation guide](FUTURE_PRESENTATION_GUIDE.md); [current feature coverage](FEATURE_COVERAGE.md#tri-workflow-future-added-november-7-2026).
- Existing forecasting: [`future/horizon.py`](../../gondola/future/horizon.py), [`future/nowcast.py`](../../gondola/future/nowcast.py), [`future/drivers.py`](../../gondola/future/drivers.py), [`future/weather.py`](../../gondola/future/weather.py), [`tools/demand.py`](../../gondola/tools/demand.py).
- Agent plumbing and guards: [`review/llm.py`](../../gondola/review/llm.py), [`agents/adk_graph.py`](../../gondola/agents/adk_graph.py), [`agents/guardrails.py`](../../gondola/agents/guardrails.py).
- Consumers and screens: [`api/tri_future.py`](../../gondola/api/tri_future.py), [`present/service.py`](../../gondola/present/service.py), [`RestOfToday.tsx`](../../web/src/screens/RestOfToday.tsx), [`Tomorrow.tsx`](../../web/src/screens/Tomorrow.tsx).
