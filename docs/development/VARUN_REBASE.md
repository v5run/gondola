# Integration with V's newer branch

November 6, 2026. Requested by the user after the Rush demo. Remote refs were fetched and compared directly; no GitHub push or message was sent.

## Branch found and integrated

- Original starting point: `origin/main` at `afdb4ad4c4bfd22d51b84fd3f6772bb4dc57751c`.
- V's newer branch: [`varun`](https://github.com/v5run/theProdigyProject/tree/varun), commit `300dd8d7fb93b8f9e35d01526dfdfdde17878f78`, one commit ahead of that base.
- Author/commit subject: v5run, **purely live with scheduling, interactive graphs**, November 6, 2026 at 02:22:44 -05:00.
- Local branch remains `feat/rush-control`, now based on `origin/varun`.
- Our previously uncommitted source/docs/evidence were checkpointed as `9bb8843f254be96648a9cb7e669ac4e170f94675`, then rebased to `2494062`. The rebase completed with **zero source conflicts**. Later local maintenance/build commits sit above it.

## What V changed

The commit changes 59 paths, including source, tests, documentation, compiled assets, sample reports/screenshots and the repository's packaged app ZIP. Its main behavior changes are:

| Area | New behavior |
|---|---|
| Store/business clock | New `gondola/now.py`, America/New_York wall clock, business day ending at 4 a.m., open/closed phases and a frozen-clock test hook |
| Data visibility | `Store(cut=...)` filters orders to the current minute, hides future business days, prorates today's labor and hides the day's future sellout flag |
| Dashboard/API | New `/api/now`; current-day graphs stop at now, closed-day fallback when the real business date is outside the generated dataset, and date navigation cannot move into the future |
| Live stream | Catch-up sends already elapsed orders/events, then follows the remaining generated day's events at real-time speed. Client order IDs deduplicate reconnects; catch-up events do not create a burst of old toasts |
| Shift close | Closing today's shift is locked until configured closing time; future closes are rejected |
| Frontend | Clock-aware state/providers and Tonight page; replay-speed control removed from the dashboard and retained locally on the older Service replay |
| Checks | Six new clock/API/stream tests, shared frozen-clock test defaults and updated browser checks/screenshots |

The word “live” here means a real clock pacing orders from the synthetic dataset. This commit does **not** add a live DoorDash/Uber/POS connector, the cross-channel kitchen prioritizer, staffing scheduler, or station-aware promotions. Rush Control remains a separate labeled simulation and supplies the new kitchen/offer logic.

## Conflicts and resolution

A three-way merge probe used the original base and snapshots of both our authored work and the complete dirty working tree. It did not overwrite working files.

- **Authored source/docs:** zero conflicts. The only paths edited by both sides were `README.md` and `gondola/api/app.py`; Git combined both cleanly. The actual rebase tree matched the clean probe's predicted tree.
- **Including every local generated file:** 27 conflicts. They were entirely `out/` reports/index/approvals/outbox, `web/screenshots/` image captures and `web/dist/index.html`. Two local August 27 report files also collided with files newly tracked upstream.
- **Handling:** checkpoint source/docs/evidence separately, preserve all old generated changes in a named stash, rebase the source checkpoint onto V's commit, retain V's generated report/screenshot baseline, and rebuild the combined frontend. No old generated backup was dropped or force-applied over V's files.

The rebuilt `web/dist` includes both V's app changes and our `/rush` route. The original root research ZIP/PDF inputs and extracted `reference/Gondola/` are outside this rebase and remain untouched. V's separately tracked `_gondola-app.zip` update is inherited from his commit; it was not executed.

## Verification

- TypeScript/Vite production build passed on the combined source.
- Full Python suite: **127 passed**, 1119 existing deprecation warnings, 139.89 seconds. Ordinary tests ran with model keys/agent mode disabled in the test process.
- **Eight browser integration checks passed**, no JavaScript errors: combined APIs; Rush offer/reservation checks; courier-delay replay; pre-rebase real action-receipt reload; completed-day clock; open-service clock/catch-up count and close lock; future-date restriction; and Rush working during clock-aware service. Evidence: [browser results](../demo/varun-integration-browser.json).
- Open-service UI used a temporary **offline**, frozen November 5 19:30 API on port 8001. That test server was stopped. The normal demo uses the ordinary clock on port 8000 and keeps the existing configured Google access. No additional model calls or merchant operations were needed for this integration.
- The earlier recorded demo, live Gemini receipts and synthetic benchmark remain pre-integration evidence. The scheduling/offer engine was not changed by this rebase.

## Recovery and remaining work

- `backup/rush-before-varun` points to the pre-rebase authored checkpoint `9bb8843`.
- Generated backup stash object: `4e45dd8a82862062b6ec4f37027ddb1a8ebd131f`, message **pre-varun generated reports, screenshots and web build**. It is currently `stash@{0}`; use the object/message to identify it if later stashes change that number.
- Local raw merge probes/test logs are ignored under `.local/integration-varun/`. Do not apply the whole generated stash over the new baseline; inspect or recover individual artifacts when needed.
- [Feature coverage and remaining-work checks](FEATURE_COVERAGE.md) is the living tracker and now records V's clock contribution. Exploratory proposals remain separate from required work. Maintaining this tracker at meaningful implementation milestones is required in repo `AGENTS.md`.

No force-push, remote branch rewrite, PR or external message was performed. This integration creates local commits only.
