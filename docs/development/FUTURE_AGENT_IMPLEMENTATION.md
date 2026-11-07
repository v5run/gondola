# Agent-first Future: implementation and evidence

**Integrated into main, November 7, 2026.** This is a synthetic, local demonstration. The agent integration was exercised with scripted ADK models; **no real-model or live event-provider call was verified in this environment**. See [the original plan](FUTURE_AGENT_PLAN.md) for intended direction and [feature coverage](FEATURE_COVERAGE.md#tri-workflow-future-added-november-7-2026) for current status.

## What is implemented

- The existing Future and Tomorrow screens have an **Outlook agent** panel. Clicking **Investigate signals** runs a Google ADK agent when `GONDOLA_AGENTS=adk` and a supported model are configured. The agent selects tools and a scenario; it is not merely asked to rewrite a precomputed result.
- Tools expose fictional nearby, cancelled and distant events; fixture weather; prior same-weekday totals; the existing LightGBM/nowcast estimate; and a code-controlled scenario calculator. Tomorrow may use the existing opt-in Open-Meteo adapter when it succeeds. Event records remain **mock**; there is no Google or real event API connection.
- The model can anchor its proposed scenario to ML or a historical analog and may choose which optional tools to inspect. A model-selected event adjustment is explicitly a **hypothetical assumption**, not a measured event effect. Code rejects non-finite/out-of-range assumptions, invalid anchors, cancelled/distant/ended events, nonzero adjustments with no event, and exact-name matches already in the ML event table. Other overlap and correlation are **not solved**.
- Code accepts only a scenario previously returned by the tool within that run and a small set of checked interpretation labels. The model cannot directly supply an unchecked published number. Successful output is a short-lived versioned snapshot; no model, a provider error, abstention or invalid output produces a clearly labeled ML fallback.
- While a valid snapshot is active, its checked factor updates the remaining-order curve and limited-item projections today, or the daily forecast and prep cards tomorrow. Present's simulated arrival forecast consumes that nowcast. Cache invalidation and snapshot expiry—including expiry within a 15-minute Present cache bin—are covered by tests. Earlier replays do not use snapshots from a later cut.
- Scenario bounds scale the existing ML/nowcast range and are **not calibrated agent P10/P90 estimates**. The intraday/channel shape still comes from the existing ML/similar-day pipeline, even when the agent selects an analog anchor. This is an agent-selected, code-calculated scenario, not an independent end-to-end generative demand model.
- All restaurant/order data, event records and merchant actions in this demo are synthetic or simulated. The local server is not a multi-tenant production system; there is no OS agent sandbox or authenticated live approval.

### Where to look

[`gondola/future/outlook.py`](../../gondola/future/outlook.py) contains the ADK agent, tools, validation and snapshots. The snapshot is applied in [`nowcast.py`](../../gondola/future/nowcast.py) and [`horizon.py`](../../gondola/future/horizon.py); Present and runout read those forecasts through [`present/service.py`](../../gondola/present/service.py) and [`items.py`](../../gondola/future/items.py). [`tri_future.py`](../../gondola/api/tri_future.py) exposes `GET` and `POST /api/future/outlook`, limited to today or tomorrow. The screen component is [`OutlookPanel.tsx`](../../web/src/components/OutlookPanel.tsx).

## Integration status

User accepted fixture-based signals for the hackathon demo; real internet event ingestion remains deferred. Integrated on current main while preserving synchronized Playback and hidden Alerts. Resolved both frontend API-client conflicts; preserved replay `at`/minute handling. Corrected daily agent forecast provenance, suppressed Outlook investigations in Playback on both Future tabs and made local snapshot ordering strict when wall-clock reads tie.

Focused integration selection: **39 passed, 2 platform skips**, 15.59s; TypeScript/Vite production build passed. No full-suite repeat or browser/live-model/provider call. Prior measurements and broader suite results below belong to the earlier source implementation, not this integration. See [security follow-up](SECURITY_AUDIT.md#outlook-specific-follow-up-integrated-demo).

## Fresh evidence

### 1. Scripted ADK episode, synthetic store

A fresh local run on the generated store used a **scripted fake ADK model**, a frozen November 5, 2026 19:30 store clock and fictional events. The scripted model selected the nearby fictional concert and a **+5% assumption**. This verifies the data flow and arithmetic; the 5% is not measured, and the scripted model does not prove that a live model would make the same choices.

| What was checked | ML/nowcast baseline | Checked agent scenario |
|---|---:|---:|
| Completed orders already observed | 396 | 396 (unchanged) |
| Remaining orders, central estimate | 99.8 | 104.8 |
| Full day, central estimate | 495.8 | 500.8 |
| Estimated remaining chashu demand | 110.1 portions | 115.6 portions |
| Tomorrow's central estimate | 590.6 | 620.2 |
| Tomorrow's chashu prep target | 770 portions | 810 portions |

Tomorrow's scenario curve summed to **620.1** orders versus the rounded total of **620.2**. The run recorded calls to `search_events`, `get_weather`, `get_historical_analogs`, `get_ml_forecast` and `calculate_scenario`. A separate test uses an analog anchor without calling the ML or weather tools, verifying that the agent plumbing permits a different selection. The calculator still uses ML-derived shape/range and a bounded comparison to the ML baseline for publication.

### 2. Automated checks

- **Targeted Future/Outlook suite:** `python -m pytest -q tests/test_outlook.py tests/test_future.py --disable-warnings` → **27 passed** in the current workspace. Covers scripted ADK tool loops, both anchor choices, today/tomorrow propagation, unchanged actual orders, chashu runout, prep targets and API → Present arrival handoff.
- The new tests also cover invalid/cancelled/distant/ended events, same-name event overlap, assumption limits, no-model/provider failure and error redaction, database-scope isolation, expiry and earlier replay, and Present cache behavior across mid-bin expiry. These are selected test cases, not a security certification or a proof that all correlated signals are de-duplicated.
- **Broader offline regression:** on an isolated copy, `python -m pytest -q tests --ignore=tests/test_api.py --ignore=tests/test_api_v3.py --disable-warnings` → **252 passed**. Model/weather credentials were removed from that process. Those two API test files were excluded because their close/report fixtures require a working sandboxed Chromium.
- **Full-suite attempt:** an earlier isolated run returned **262 passed, 4 failed, 12 errors**. Failures/errors were in `test_api.py` and `test_api_v3.py`, where missing Chromium made the PDF/close setup incomplete; it was run before the last small cache/overlap changes. No claim of a full-suite pass is made. Do not bypass the repository's required Chromium sandbox to make it pass.
- **Frontend:** `npm run build` passed TypeScript and Vite build. Vite warned that the main minified chunk exceeds 500 kB. No new browser-render test was completed here because Chromium and its system libraries were unavailable.

### 3. Outlook security follow-up

After the original tests above, a focused security review hardened request parsing, local run admission, tool-call limits, local snapshot permissions and retention, event-name minimization, and the optional weather adapter. The [security design](../strategy/AI_AGENT_SECURITY.md#outlook-agent-security-choices-and-remaining-gaps) explains what each control does and does not protect against. New offline tests cover malformed/oversized requests without model calls, concurrent/cooldown rejection, a scripted tool flood, untrusted configured-event text, local DB-scope status filtering, POSIX snapshot permissions, bounded replay history, weather redirect rejection and response-size limits.

With those changes, the isolated broader regression (same two browser/PDF-dependent API files excluded) passed **261 tests**. A first attempt at that isolated run omitted existing `out/` and built web assets and therefore had missing-fixture/static-route errors; copying those synthetic fixtures into the isolated copy and rerunning produced the 261-pass result. The frontend build passed with the same Vite chunk warning. No full suite, real provider, penetration or browser-render test is claimed for this follow-up.

### 4. What is not yet verified

- A real configured model choosing tools and producing a valid scenario in this new Outlook implementation. Historical Gemini tests for other agents do not establish that.
- Live Open-Meteo access in this environment, or any real events provider. The sandbox's network restrictions also prevent relying on those connections here.
- That an agent-selected hypothetical adjustment improves forecast accuracy or restaurant outcomes. No new held-out forecasting or business-impact evaluation was run; the prior synthetic nowcast backtest concerns the **baseline**, not this agent scenario.
- Generalized overlap detection: only an exact event-name match to the configured event table is rejected. Overlapping, renamed or correlated events/weather may still be double counted. No live-event discovery, arbitrary browsing or general search is implemented.
- Full production security, authenticated manager approvals, isolated agent workers, event-time-correct order-status replay, or real merchant actions. The full [security design](../strategy/AI_AGENT_SECURITY.md) remains a production target.

## How to try it locally

1. Follow [local setup](LOCAL_SETUP.md). Start with the generated demo DuckDB and a built frontend. Keep the API loopback-only.
2. To make a real model call, configure the supported provider in the local ignored `.env` or environment, set `GONDOLA_AGENTS=adk`, and select the appropriate configured model. Do not put credentials in source control or chat. A configured key is not proof of a successful run.
3. For the open-service fixture used above, set `GONDOLA_NOW=2026-11-05T19:30:00` and `GONDOLA_CLOCK=frozen` **before starting the API**. Remove them afterward. Without this hook, the store clock can map to a closed dataset day; today's remaining forecast can be empty.
4. Open **Future → Rest of today** or **Future → Tomorrow**. Click **Investigate signals**. If the agent succeeds, inspect the tools, selected mock event, hypothesis and ML reference. If it fails or is unconfigured, the panel says **ML fallback in use**. Tomorrow's prep cards and today's arrivals update only while the checked snapshot is active.
5. Present the event percentage as a **hypothetical demo scenario**, and the displayed range as a scaled scenario range—not measured uplift or newly validated confidence. Expiry is at most 60 store-clock minutes, sometimes sooner when the selected event ends. A frozen or mapped-closed clock does not advance, so this is not a real-time freshness guarantee.

For PowerShell, the clock variables are `$env:GONDOLA_NOW='2026-11-05T19:30:00'` and `$env:GONDOLA_CLOCK='frozen'`. `GONDOLA_WEATHER=openmeteo` is optional for tomorrow; if no successful response is returned, fixture weather is used. A live-model run using fixture events is still **not live event discovery**.
