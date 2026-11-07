# Future / Forecaster: presentation and technical guide

**Purpose:** Explain the baseline forecasting internals and the new agent-first demo. The original baseline descriptions and historical backtest came from the `v5run/gondola` main snapshot `60ec08b`; the Outlook agent was added on this working branch afterward. For what was implemented and freshly tested, see the [Outlook implementation and evidence](FUTURE_AGENT_IMPLEMENTATION.md). No real Outlook model call or live event feed was verified in this pass.

## The 30-second explanation

> “Future's Outlook agent investigates demand signals and can use our statistical forecast as one input. Its checked scenario updates the outlook, simulated item projections and prep plan; if the agent is unavailable, the statistical forecast remains the fallback. Our demo's events and restaurant data are fictional, and the event impact is an assumption—not a measured lift.”

### Important: what “agent” means here

The **Outlook agent** is now implemented as an ADK tool-using workflow started from Future. It can choose tools, inspect fictional event data, weather and historical analogs, consult the LightGBM baseline, and select a code-checked scenario. Its event adjustment is hypothetical, and its scenario bounds scale the existing baseline range. Without a configured, successful model run the UI explicitly falls back to the ML forecast. The new agent has been tested with a scripted fake model, **not yet a real model**. The endpoint and screen expose today and tomorrow only.

**Say:** “The agent investigates fictional event signals and can use our statistical forecast as an input; our current checks cover simulated data.”

**Don't say:** “The agent searches live events,” “its event lift is measured,” or “we verified it improves forecasting.”

## 1. Why the restaurant needs it

A kitchen needs to decide not only *how many* orders may arrive but *when*, *through which channels*, and whether it has enough limited ingredients. The same total can create very different pressure if orders arrive at once rather than spread over an evening.

Future produces three related outputs:

1. **Rest of today:** an updated estimate of completed orders still to come, a full-day estimate, an uncertainty range, and a 15-minute/channel breakdown.
2. **Limited items:** estimated stock remaining, a projected runout time, recount points and suggested app pause times for four ingredients.
3. **Tomorrow:** an expected order total and range, estimated rush window, historical context and suggested prep cards.

These are **estimates and recommendations**, not guarantees of customer behavior or direct live platform changes. Present's replay consumes some of the forecasts and may simulate actions; it is not a live merchant connection.

## 2. What to show in the demo

### Screen A — Future / Rest of today (`/future`)

- **Outlook agent:** click **Investigate signals**; see the selected scenario, its hypothetical assumption, evidence and data source—or the explicit ML fallback if the agent cannot run.
- **Expected orders:** the central full-day estimate and range. The full-day number is completed orders seen so far plus the predicted remainder. If an agent scenario is active, the bounds are scaled baseline bounds, not newly calibrated agent P10/P90.
- **So far:** completed orders in the data up to the current cut, compared with the baseline's expected pace by that time.
- **Still to come:** the forecast for the remaining part of the day, not another full-day total.
- **Chart and channel buttons:** historical/actual bars and forecasted 15-minute bins. Filter between all channels and individual channels. The past and future portions have different meanings; the current bin is partial.
- **Expected tonight:** clickable weather, sports, weekday or other context. The explanation cites historical examples where available. Those comparisons are **associations**, not causal proof or separate percentage adjustments to add together.
- **Limited items:** believed quantity left, projected runout and suggested app pause/recount points. These are modeled inventory and timings, not live sensor readings or confirmed app actions.

### Screen B — Future / Tomorrow (`/future/tomorrow`)

- The central estimate and range show tomorrow's forecast; the rush window comes from the predicted intraday shape.
- The cards show **target**, estimated **on hand**, and how much to **prep** for chashu, ajitama egg, gyoza and tonkotsu broth when they have usable history. The manager can edit prep amounts and see recalculated timings in the UI.
- **Approve** records a local prep card against an existing close run. It is a demo workflow and **not** authenticated authorization to change a real merchant platform. With no close record for today, the API returns an error rather than creating an approval.
- Weather marked “Forecast” can be the demo calendar's fixture for tomorrow; it is not necessarily a live weather feed. See §7.

**Clock tip:** `gondola/now.py` uses America/New_York, with an 11 a.m. opening and 10 p.m. close (11 p.m. Friday/Saturday). If the actual business date is outside the dataset, the UI maps to the latest available dataset day and treats it as closed; the “still to come” forecast may then be empty. For an illustrative open-service view on a prepared local demo, run the API with `GONDOLA_NOW=2026-11-05T19:30:00` and `GONDOLA_CLOCK=frozen`. This is a **test/replay clock**, not a live store. On Windows PowerShell, set those with `$env:GONDOLA_NOW='2026-11-05T19:30:00'` and `$env:GONDOLA_CLOCK='frozen'` before starting the API; remove them afterward. See [local setup](LOCAL_SETUP.md).

**Recorded fixture example:** the checked-in `out/forecasts/2026-11-06.json` contains P10 **531.7**, P50 **589.9**, P90 **678.5** completed orders for the fictional store. These are a historical synthetic forecast, not a fresh result, real sales, or proof of accuracy. Current UI results can differ depending on clock and data state.

## 3. How the daily forecast is built

The primary implementation is [`gondola/tools/demand.py`](../../gondola/tools/demand.py) and [`gondola/future/horizon.py`](../../gondola/future/horizon.py).

1. **Start with the store history.** DuckDB combines order totals with the synthetic calendar, weather and event tables. The target is **completed orders**, not all requests, cancellations, or total customer demand.
2. **Construct features.** These include weekday, rain/snow, temperature, event signals, school in session, a DoorDash-promo flag, a holiday factor, time/seasonality, last week's count and the average of up to four same-weekday lags.
3. **Train a LightGBM regressor.** It fits on prior open days with enough lag history, using the log of completed orders adjusted for the calendar's holiday factor. The holiday multiplier is applied back to the prediction. The target date's actual orders are not part of training.
4. **Estimate a range from past errors.** Past night-before forecasts are replayed against later actuals. The ratios of actual to forecast provide multiplicative lower and upper bounds. The Future morning baseline uses a same-weekday fallback with a fixed ±20% range when there are fewer than 20 usable backtest rows. This fallback should not be described as a trained model.
5. **Build an intraday shape.** The analyst finds up to five similar prior days—prefer the same weekday when there are enough examples, then compare weather, events and calendar context, with a small recency preference. Future spreads the daily total across 15-minute bins using those days' profiles and smooths channel mix over five neighboring bins.

The forecast for tomorrow is trained on **complete days**. While today is still open, the horizon code appends today's expected P50 to the extended history used for constructing lag features, instead of treating a partial day as complete. Its current lag features look back 7, 14, 21 and 28 days, so this should not be pitched as a direct one-day lag from today's nowcast into tomorrow's P50. Tomorrow's calendar row is a fixture unless the optional weather feed is enabled and succeeds. Day-to-day refresh means the model can be refit with more historical data; it does **not** mean the agent has proven it autonomously learns causal lessons or improves itself.

### The range in plain English

For the **ML baseline**, P50 is the central estimate; P10 and P90 are the bounds produced by its historical error procedure. Treat this as an empirically estimated prediction interval, not a promise that the outcome will lie inside it 80% of the time for every store or every day. **When Outlook is active, the bounds are scaled to form a scenario range and have not been calibrated for the agent.** The code estimates total-rest-of-day uncertainty separately from each bin/channel's range; don't add per-bin P10s/P90s and present the result as a calibrated total interval. The chart's “all channels” band sums channel bounds within each bin, so it too should be treated as a visual summary, not independently verified aggregate coverage.

## 4. How the live-paced nowcast updates today

[`gondola/future/nowcast.py`](../../gondola/future/nowcast.py) takes the morning baseline and compares its expected pace with completed orders created before the selected time. It uses **cumulative evidence**, not just the last half-hour.

Let:

- `F` = baseline completed orders expected by now;
- `A` = completed orders observed so far;
- `raw = A / F` (if `F` is zero, the correction stays neutral);
- `w = min(F / (F + 150), 0.5)`;
- `r = 1 + w × (clip(raw, 0.5, 2.0) − 1)`.

The remaining forecast is adjusted using `r`. The factor is **shrunk toward 1**: early evidence has little weight, and the weight is capped at 0.5. The code also calculates a separately shrunk channel tilt and rescales the channel factors so their total remains consistent with `r`. At a time inside a 15-minute bin, it keeps only the unexpired fraction of that bin in the remaining forecast.

**Simple hypothetical:** if the baseline expected 100 completed orders by now but observed 120, `raw = 1.20`, `w = 100 / 250 = 0.40`, and `r = 1.08`. In aggregate, the system raises the *remaining* baseline by about 8%, not the full 20%. Actual results also depend on channel mix. This example explains the calculation; it is not a measured demo outcome.

For the range, the code replays the nowcast on up to 60 earlier open days at hourly cut times, uses 10th/90th percentile **log errors** for the remaining total, interpolates between cut times, and adds a fitted count-noise/overdispersion term for individual bins. `arrivals()` returns each channel/bin's P10, P50 and P90; at close it returns no remaining bins. Heavy calculations and response payloads are cached.

**Time boundary:** the data access layer cuts orders by their `created_at` time and hides later business days. The tests check that deleting orders created after 19:30 does not change the 19:30 forecast. This is valuable but narrower than a full event-time guarantee: the fixture stores an order's final status, so this test does not prove that every status of an earlier-created order was observable at that historical moment.

## 5. How drivers and the “why” work

[`gondola/future/drivers.py`](../../gondola/future/drivers.py) builds human-readable **template explanations** from historical comparisons; an LLM is not writing these Future driver explanations.

- For many factors, it looks back up to 365 days of open, non-holiday history. With at least three same-weekday examples **and** three comparison examples, it compares their average completed orders.
- For thinner evidence it falls back to comparisons across weekdays normalized by each weekday's usual level and marks the result as an **estimate**. If there are no examples, an event can use its configured planned lift or report no history.
- Relevant drivers include sports/events, rain or snow, unusually cold/hot weather, holidays, school breaks, promotions, weekday and recent trend. An event's displayed time window is a heuristic around its start, not evidence of individual customer behavior.
- The model already uses many of the same inputs. These driver percentages are descriptive historical comparisons—not model feature attributions, not proven causes, and not independent effects that can safely be summed.

A rainy Penguins-game example is useful for explaining **why those signals were considered**, not for claiming that rain or the game caused a specific change in orders.

## 6. How the prep and runout recommendations work

The code is in [`gondola/future/items.py`](../../gondola/future/items.py) and [`gondola/tools/plan.py`](../../gondola/tools/plan.py).

1. **Map dishes to ingredients.** Recipe/SKU tables say how much chashu, egg, gyoza or broth each dish uses and what unit/shelf-life applies.
2. **Estimate usage per completed order.** Similar reference days supply the mix. Where possible, days with chashu sell-outs are excluded so suppressed sales do not directly define normal usage; if fewer than two clean reference days remain, the code falls back to the available days.
3. **Estimate today's remaining stock.** For chashu, the synthetic prep log supplies the starting quantity. The other items use a habit estimate: average usage over up to four prior matching weekdays, multiplied by 1.10 and rounded up to a batch. Subtract recipe-implied usage from completed orders so far. This is **believed stock**, not a real count.
4. **Project runout.** Apply usage-per-order to the remaining P50 order curve and find the first bin where the estimate reaches zero. The system also estimates a recount point and app-specific pause times. It assumes pause delays of 2 minutes for DoorDash/Uber Eats and 10 for Grubhub; these are model assumptions, not verified live API behavior.
5. **Recommend tomorrow's prep.** A *newsvendor* calculation balances the assumed cost of running short against the cost of leftovers. It fits a lognormal approximation to P10/P50/P90, uses each item's configured cost/margin/leftover assumptions to choose a target, caps the order quantile at 105% of P90, subtracts estimated on-hand stock and rounds prep up to batch size. The plan also shows a busier-curve scenario. These economics are assumptions, not measured restaurant costs or an optimized staffing plan.

The Tomorrow screen uses the Future curve and can recompute pause previews in the browser when a card is edited. Treat those times as planning estimates, not verified future inventory or external actions. The close pipeline also has separate prep-scheduling and staffing-gap calculations; do not imply that Future's item cards alone are a complete real staffing system.

## 7. Where the data comes from, and where the results go

| Input or output | What actually happens in this demo |
|---|---|
| Orders / recipes / prep | Generated Hanabi Ramen fixture data is ingested into local DuckDB. It is not a connected real restaurant. |
| Weather and events | Default: synthetic calendar and events tables. Optional Open-Meteo weather is enabled only with `GONDOLA_WEATHER=openmeteo`, caches for 30 minutes, and falls back if unavailable; tests do not make live weather calls. No autonomous discovery of new events. |
| Future → Present | Present calls Future's `arrivals(..., issue=False)` for 15-minute channel estimates and uses P50 forecast work in its capacity/headroom calculation. In-store is split into synthetic dine-in/pickup shares of 60/40. If Future fails or gives no arrivals, Present falls back to a same-weekday historical profile. Present also uses Future's chashu runout estimate where available. This is the **tri-workflow replay**, not the separate Order Manager/Flex ledger or a live KDS. |
| Future → ledger / Review | Future can issue local `forecast.issued` events; rest-of-day issuance uses an idempotent date/15-minute-bin key. Review has forecast-miss checks and digest information. The ledger is not an independently tamper-proof audit, and this does not prove causal learning or a single continuous cross-system production state. |
| Manager action | Tomorrow's approval is local demo state tied to a close run. Real merchant writes are blocked/dry-run; there is no production authentication or approval gate. |

The backend exposes the existing `GET /api/future/today`, `/arrivals`, `/items`, `/days` and `/config`, plus `GET` and `POST /api/future/outlook`; see [`tri_future.py`](../../gondola/api/tri_future.py). `at=HH:MM` is a replay/debug aid for the first three, capped at the store clock. `/days` accepts only tomorrow and `n=1`. The new Outlook snapshots are separate from the older adjustment-file scaffolding.

## 8. How well does it work? Recorded evidence and limitations

The [feature coverage record](FEATURE_COVERAGE.md#tri-workflow-future-added-november-7-2026) reports an earlier **synthetic**, 60-open-day nowcast comparison against the morning-only forecast. It was not rerun for this document:

| Forecast time | Morning-only rest-of-day MAE | Nowcast rest-of-day MAE | Takeaway |
|---|---:|---:|---|
| 13:00 | 23.9 orders | 22.8 | Slight improvement |
| 17:00 | 21.6 | 21.7 | Essentially tied on MAE |
| 19:00 | 13.8 | 15.1 | Nowcast worse |

The reported total-rest P10–P90 coverage was **75%, 75%, and 70%** at those times, below the nominal 80%; per-bin/channel coverage was reported as 85%, 82%, and 83%. The cap was added **after an initial look at the last-60-day result**, so do not call that window a fully untouched final holdout. These results are from one generated store, not a real-world accuracy guarantee or proof of superiority.

The main limitation is that **completed orders are not the same as unconstrained demand**. When an item sells out or orders are declined, completed sales can fall even if customers still want food. The existing record associates late-evening weakness partly with sell-outs; it does not establish causal identification. The current nowcast does not recover unseen lost demand.

[`tests/test_future.py`](../../tests/test_future.py) checks the arrival contract, no newly created orders after the replay cutoff, shrinkage, sensitivity to a slow half-hour, drivers against direct calculations, item usage, pause ordering, prep-card consistency and API limits. The recorded integrated suite result is in [security integration checks](../demo/security-integration-checks.json); that earlier run was offline. These tests establish selected code behavior, **not** production readiness, live model quality, or real-world business impact.

## 9. Questions you may get

**“Is this really AI?”**

“Yes: LightGBM is a machine-learning model, and an ADK Outlook agent can select tools and a demand scenario. The numerical checks and prep calculations remain in code. This new agent was tested with a scripted model; a real-model run remains to be verified.”

**“What does the model actually learn?”**

“It fits relationships between completed-order counts and features such as weekday, weather, events, promotions, seasonality and previous weeks' counts. It does not infer every customer's hidden intent, and our fixture data is synthetic.”

**“How does it adapt when today is different?”**

“It compares completed orders so far with what the morning baseline expected by that point, then applies a deliberately damped correction to the rest of the day. It adjusts the channel mix too.”

**“Can it see the future during replay?”**

“The baseline excludes the target day's order totals and the partial-day query filters out orders created at or after the cutoff; a test deletes later-created orders and checks the result doesn't change. That's not a complete proof of event-time fidelity, because earlier orders' final statuses are stored in the fixture.”

**“Why not just use the most recent hour?”**

“A single slow interval can be noisy. This version uses cumulative pace and shrinks the adjustment, so a brief lull cannot swing the whole evening as strongly. In the recorded synthetic test, one engineered slow half-hour moved the remaining estimate by less than 4%.”

**“Are those weather/game impacts causal?”**

“No. They are with/without historical comparisons; other factors can differ at the same time. The labels explain context, not a controlled experiment.”

**“Does it know real inventory or change DoorDash?”**

“No. Stock is estimated from synthetic prep/history and recipes. The displayed pause times are modeled; real merchant writes are disabled.”

**“What happens when the forecast is wrong?”**

“The interface shows uncertainty, the nowcast updates with observed pace, and Review has a forecast-miss path. But the recorded range missed its nominal coverage in this synthetic backtest and performance was worse at 19:00. We need more robust validation, availability-aware data and explicit human oversight before using real operations.”

**“What would change for a real deployment?”**

“Use authorized store-scoped POS/KDS and availability data, time-correct event histories, measured recipe/inventory and cost inputs, verified weather/event feeds, a rolling out-of-sample evaluation, and authenticated approvals for any live changes. The current LLM agent also needs encrypted storage, tenant isolation and an actual agent sandbox before production.”

## Source map

- Implemented scope and recorded evaluation: [feature coverage: Future](FEATURE_COVERAGE.md#tri-workflow-future-added-november-7-2026).
- Core: [`future/base.py`](../../gondola/future/base.py), [`nowcast.py`](../../gondola/future/nowcast.py), [`drivers.py`](../../gondola/future/drivers.py), [`horizon.py`](../../gondola/future/horizon.py), [`items.py`](../../gondola/future/items.py), [`weather.py`](../../gondola/future/weather.py).
- Daily ML and similar days: [`tools/demand.py`](../../gondola/tools/demand.py), [`tools/analyst.py`](../../gondola/tools/analyst.py), and prep math in [`tools/plan.py`](../../gondola/tools/plan.py).
- Integration: [`api/tri_future.py`](../../gondola/api/tri_future.py), [`present/service.py`](../../gondola/present/service.py), [`present/capacity.py`](../../gondola/present/capacity.py), [`review/exceptions.py`](../../gondola/review/exceptions.py), [`pipeline.py`](../../gondola/pipeline.py).
- Screens: [`RestOfToday.tsx`](../../web/src/screens/RestOfToday.tsx), [`Tomorrow.tsx`](../../web/src/screens/Tomorrow.tsx), [`components/future.tsx`](../../web/src/components/future.tsx).
- Earlier proposed architecture: [Tri-workflow design](../architecture/TRI_WORKFLOW.md#4-future-the-rest-of-today-and-the-next-7-days). The new Outlook implementation differs from that proposal; its longer horizon remains deferred.
