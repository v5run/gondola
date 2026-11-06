# Repeatable idea generation

November 6, 2026. User wants more useful ideas and a repeatable way to generate them, and asks whether a teammate's Claude prompts explain stronger suggestions. This is a proposed working method, not a tested creativity benchmark. No comparative model run, new paid model call, or interview was performed.

Use [the idea pool](IDEA_POOL.md) for raw hypotheses and [the leading shortlist](LEADING_IDEAS.md) for candidates that have earned discussion. A new brainstorm entry is not a build commitment.

## What the teammate example shows

The provided exchange connects a decision (what to cook next) with information outside the original queue (courier arrival). The user's FIFO objection exposes fairness and promised-time requirements. That observed sequence is useful to reproduce. The exchange does not reveal the teammate's exact model, prompt, context, number of attempts, or which suggestions were discarded. Do not conclude that Claude or ChatGPT is more creative from it, or that prompting alone caused the difference.

OpenAI's [prompt engineering guidance](https://developers.openai.com/api/docs/guides/prompt-engineering) supports giving relevant context and explicit instructions and evaluating variable model outputs. It does not establish a Claude/ChatGPT creativity ranking or prove this ideation workflow. The workflow below is our practical proposal.

## Run separate passes

1. **Collect situations.** Write concrete merchant moments, observed or explicitly hypothetical. Template: “When ___ happens, ___ goes wrong because ___ cannot see/decide ___.” Keep observations and inventions labeled. A useful example is enough; it need not be a whole product idea.
2. **Generate decision mechanisms.** Identify the action a merchant can actually control. Cross it with information, constraints, or consequences another system sees. Produce varied candidates before researching competition or polishing pitches.
3. **Explore different lenses.** Queueing/capacity, economics, uncertain observations, feedback from the agent's own actions, and learning human tradeoffs can produce different mechanisms. Analogies such as computing queues or appointment scheduling are prompts for exploration, not evidence of merchant fit.
4. **Challenge and consolidate.** Supply a tiny example where each candidate changes a decision, plus a counterexample where it fails or the simple rule is sufficient. Merge renamed versions of the same mechanism. Identify what an agent contributes beyond a conventional optimizer.
5. **Check evidence.** For the strongest distinct candidates, inspect current primary product/API documentation. Separate aggregation from sequencing, estimates from live tracking, and native features from proposed integrations. Mark exact overlap, adjacent overlap, or unknown. Competition can lower a novelty claim while leaving usefulness intact.
6. **Test the valuable claim.** Pick an observation-to-action boundary, strong baseline, independent scenario/validator, measurable result, and stop condition. A simulation result establishes performance only under its disclosed assumptions. Unsupported new fields remain proposed fixtures.

## Example combinations

| Decision | Additional consideration | Mechanism to investigate |
|---|---|---|
| Cooking sequence | Courier arrival and promised pickup | ETA-aware scheduling; already in the current shortlist and existing products |
| Which items to promote | Remaining capacity at each preparation station | Station-specific demand steering; commercial overlap exists |
| Kitchen start times / truthful readiness estimates | Courier dispatch responds to preparation estimates | Joint timing controller; extension of scheduling |
| Which rule to use under a tradeoff | The owner's choices in contrasting situations | Learn soft preferences from examples while preserving explicit hard constraints |
| Whether a forecast miss indicates changed demand | Prior discounts, stockouts, channel pauses, and scheduling actions | Intervention-aware learning; connected to the existing policy-development idea |

The extra ingredient must change a supported action. A data source by itself is not a complete idea. A new model, framework, or count of named agents is not automatically a new merchant capability.

## Reusable generation prompt

Copy the following into a separate idea-generation conversation. It is model-neutral; compare actual outputs rather than assuming a brand ranking.

```text
We are building Gondola for DoorDash's merchant hackathon track. We have a browser app and synthetic restaurant sales/menu data. Demand forecasting, staffing/prep recommendations, order aggregation, and courier-ETA-aware kitchen scheduling are known foundations. We want useful agent capabilities and can add explicitly labeled fixtures. Prefer software-only demos with little extra staff interaction. Production API access is unconfirmed.

Generate 12 concrete decision mechanisms across four lenses:
1. Information split across systems.
2. Shared resources and competing commitments.
3. Uncertainty and feedback caused by our own actions.
4. Agents learning judgment or constructing new capabilities.

For each, give the merchant's controllable action, the information that changes it, one small illustrative situation, the simplest credible baseline, the agent's specific contribution, required data, and one assumption that could kill the idea. Label variants of known foundations. Keep the mechanisms distinct.

This pass is generation. Leave market novelty unscored until primary-source research. Keep outcomes hypothetical and separate an input/API from an implemented integration.
```

## Reusable challenge prompt

```text
Review these candidates as an operator and an engineer. Group duplicates. For each distinct mechanism, write a concrete case where it helps and a case where a strong simple rule is enough or it fails. Check whether the input is observable at decision time and whether the action is actually permitted. Distinguish the agent's role from deterministic calculations. Retain the three most useful different candidates, with explicit unknowns; do not infer novelty from memory. Propose a fair first comparison and a stop condition for each.
```

## Reusable research prompt

```text
For these shortlisted mechanisms, find the closest existing capabilities in current primary product documentation and the exact data/action surfaces in official API docs. Compare mechanisms, not just product names. Record source URLs, what was inspected, access requirements, and what remains unknown. Existing competition is a baseline; explain its effect on our novelty and value claims separately. Do not claim integrations or measured results we have not tested.
```

## Comparing prompts or models

If the team chooses to compare Claude and ChatGPT, use the same brief and output requirements, preserve exact model/settings/prompts where available, and collect outputs before showing one system another's answers. Multiple separate samples can reveal more options; this is not a guarantee of independence or novelty. Remove model labels when reviewing candidates. Record which ideas survived real use cases, evidence checks, and first tests. A single attractive suggestion or an LLM's self-rating is insufficient to rank creativity.

The human contribution can be a friction, an exception, or a preference: “Would that punish the customer who ordered first?” provides an operating constraint. The agent can expand implications, locate related mechanisms, check sources, and build a test around it. Useful ideation does not require the human to propose a finished architecture.

## Keep records without inflating the shortlist

Every pool entry records origin, trigger, action, evidence status, relationship to current ideas, and the first test. Promote a candidate only after discussing its useful behavior and largest unknown. Archive failures and duplicate mechanisms so future rounds can build on them. User selection, implementation authorization, and measured results remain separate states.
