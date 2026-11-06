# Gondola development

The user selected this repository for the NOVA DoorDash project and authorized building/testing Rush Control. Start with `docs/development/RUSH_DEMO.md` for the implemented browser episode, measured tradeoffs and production path. Build plan: `RUSH_BUILD.md`. Branch: `feat/rush-control`. Preserve the inherited app and existing dirty setup/research/generated files.

Read `docs/development/LOCAL_SETUP.md`, `FUNCTIONALITY_AUDIT.md`, and `BACKLOG.md` in that order when resuming development. Parent research/continuity lives at `../docs/project/AFTER_COMPACTION.md`; its project skill is `../.agents/skills/hackathon-continuity/SKILL.md`.

For product direction, start at `docs/ideas/LEADING_IDEAS.md`. The selected episode combines shared kitchen scheduling, station-aware demand steering, observed effort learning, a real Gemini intervention and bounded policy experimentation. Its new synthetic fixture generator is in `gondola/rush/engine.py`; it does not establish merchant data or integration access. Existing aggregation/driver-ETA sequencing products are documented; do not claim broad uniqueness. The twelve-ticket backlog is supporting history, not an instruction to implement all tickets.

For further brainstorming, use `docs/ideas/IDEATION_PLAYBOOK.md` and record hypotheses in `IDEA_POOL.md`. Separate concrete situation/decision generation, counterexamples, evidence checks, and first tests. Mark variants instead of inflating the shortlist. No Claude/ChatGPT comparison has been run; the teammate's exact prompt/model/context are unknown. No model superiority or prompting-cause claim is established.

For DoorDash feature/API work, read `docs/ideas/DOORDASH_FIT_AND_ACCESS.md` first. Native Smart Campaigns already exist. Integrated Promotions means incoming discount data, not campaign writes. Public docs describe campaign-control access as a restricted new-2027 partner benefit; no team entitlement is verified. The user authorizes assuming the exact station-aware native loop is absent for prototyping and asking sponsors later. This is a working assumption. The simulated demo is authorized; sponsor acceptance/live API entitlement remain unknown.

Use the project `.venv`, not the system Python, for app work. `scripts/dev.ps1 -Task doctor|api|web|build|test|e2e` supplies the tested Windows commands. The backend is loopback port 8000; Vite is loopback port 5173. Secrets belong only in ignored `.env`. Since November 6, the user's local Google key has passed a real ADK Ask round trip with `gemini-3.1-flash-lite`; the full live close graph, messaging, and merchant connections remain unverified.

The original audited revision is `application-baseline`. The supplied synthetic store and historical output files are tracked. Tests/browser checks change some tracked demo outputs/screenshots, and building changes `web/dist`; review generated diffs before committing. `.local/` contains local logs, resolved dependency snapshot, and isolated audit probes and is ignored.

Preserve these non-obvious distinctions:

- The deterministic close pipeline computes plans; ADK close agents currently add tool-backed explanations afterward.
- Service replay simulates availability changes; it does not invoke the live DoorDash executor.
- Synthetic simulator truth is not a merchant observation. Its no-response recount fallback is specifically flagged in the audit.
- Configured credentials are not verified connectivity. Mock-model tests do not establish live model quality.
- Hackathon OpenRouter team keys are documented as being distributed at event start; the allowance is unspecified and the current code has no OpenRouter adapter.

Record meaningful changes/checks in the parent progress ledger and update its handoff. Add advance-built product code to the parent's disclosure ledger. No remote issues, PRs, or commits were created by the setup/audit pass; the backlog is local reviewable work.

Rush tests are offline. Clear `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY` and `GONDOLA_AGENTS` in the test process before running the whole inherited suite, or its old tests can consume a configured real model. The separately documented live smoke/browser scripts intentionally use the Google key via the API. Keep keys out of evidence. `docs/demo/` contains actual recordings, sanitized tool results and synthetic measurements; update their source/mode labels if behavior changes. Never let the agent edit scoring or read future simulator truth/held-out evaluation through its tools. Pre-minutes buyer response is private: the browser frame and agent snapshot share the decision boundary before that minute's response draw.
