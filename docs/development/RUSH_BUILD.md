# Rush Control build

November 6, 2026. User authorizes building and testing a working demo, with implementation/hackathon/production explanation. User explicitly accepts the working assumption that DoorDash lacks our specific kitchen-aware promotion loop; confirm with sponsors later. This remains an assumption, not a researched absence claim.

## Selected bounded episode

One browser workspace connects order scheduling to demand steering. Preserve existing app screens. Add explicitly synthetic station/task/courier/promotion fixtures. Reserve resources for accepted work, compare FIFO and deadline/slack scheduling with a coordinated promotion controller, and expose overload rather than hiding orders. Distinguish real Gemini calls from simulated restaurant/platform actions.

## Implementation plan

1. Typed scenario/policy contracts and a reproducible event simulator. Model shared cooks, cooking stations, packing, fixed promises, courier estimate updates, and station incidents. Future truth stays evaluator-only.
2. Fast scheduling and offer evaluation using the same reservation model. Include budgets, stock, known-work feasibility, fairness/age, and a no-offer option.
3. A live tool-using Gemini controller and bounded policy-development loop with separate training/evaluation cases. Store policy/action receipts and model/tool evidence. Preserve a useful explicitly labeled deterministic mode.
4. Add `/rush` to the React app: scenario/replay controls, station timeline, current orders, first-party menu/offer preview, decision evidence, and comparison metrics. Responsive layout and clear source modes.
5. Meaningful invariant/failure/API tests, a real-model smoke, comparative evaluation including held-out/overload cases, and browser checks with screenshots/video.
6. Update continuity, disclosure, demo guide and production-integration map. No external messages, merchant writes, campaign spend, or push.

## Evidence rules

Every metric must identify its scenario/mode and whether it is a fresh measurement. Simulated customer response is an assumption, not conversion uplift. Stronger baselines remain visible even when they win. AI-authored policies cannot edit scoring or inspect held-out outcomes. Existing promises and all accepted orders remain in metrics. Real-world feasibility under uncertain durations differs from feasibility under the model.

## Current work

The bounded episode is implemented and verified. See [the demo guide](RUSH_DEMO.md) for actual behavior, recording, measured tradeoffs and production path. Branch `feat/rush-control`, based on the existing local checkout. Earlier setup/research/generated changes are retained. No core source changes existed before this build pass. Parent progress/handoff and disclosure record completed work.
