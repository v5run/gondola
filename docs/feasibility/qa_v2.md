# Gondola QA pass 2 (V2: close card, Guard under count error, recount)

I worked only in `/home/claude/qa2`, a fresh copy of `gondola-test`. My scripts are in `/home/claude/qa2-scripts/`. They are the previous pass's scripts with paths updated, plus `guard_attack.py` and `guard_honest_threshold.py`. Copies of the claim artifacts are in `/home/claude/feas2/qa2_artifacts/` (`eval.json`, `pivot_sim.json`, `eval_rerun.json`).

## Verdict

**The demo is solid. 18 of the 23 previous issues are fixed and none regressed.**
- `pytest`: 28/28 pass.
- `run_demo.py`: the close is `done` in 7.7 s cold. The SMS is correct, and all 5 Ask answers check out.

**The Guard recount headline does not hold.** The claim is "0–6 cancellations in 90 days with recount vs 294 status quo". It depends on a recount trigger that reads the kitchen's *true* stock, which a real system can never know (`guard.py` `guarded_day`: `seen_left < recount_at or true_left < recount_at`). With the trigger fixed to use only what Gondola believes:
- 86–93 cancels at 5% count error.
- 370–371 cancels at 10% count error. That is worse than the 294 status quo.

An honest design does reach the target. Prompting a recount when Gondola *believes* 120 portions are left gives 5–6 cancels at 5–10% error, with about 0.8 prompts per night. So the claim can be rebuilt honestly, but only after the code and the grid are changed.

Do not present the 0–6 figure as it stands. The other headline claims reproduce.

## Previous issues (re-run of the last pass's repro steps)

| # | Issue | Status | Evidence now |
|---|---|---|---|
| 1 | Payouts verified before the report arrives | **Fixed** (in pipeline) | `step_books` now verifies only (date, channel) pairs that have arrived. Residual risk: `books.match_payouts(st, day)` with the default `channels=None` still reconciles every channel. Run directly on arrived-only data, it reports "Uber Eats −$1,434.54, 57 missing orders" for 11-03. Any agent tool that calls it without `channels` would repeat the old bug. |
| 2 | A second `--force` loses findings and sends a 2nd SMS | **Fixed** | Identical reruns give identical findings. The SMS is deduped per close date (`duplicate_suppressed`). Caveat: new low issue N14. |
| 3 | Ask gives confident wrong answers | **Fixed** (mostly) | All 62 adversarial questions: correct, or asks to clarify. Spot-checked against pandas: Oct cancels 142 / avoidable 101, last-30-days cancels 101. Residual: "sales on nov 6" says "only have data from Nov 6, 2025…" although Nov 6, 2025 is in range (N13). "what were sales last year" means the last 365 days (debatable). |
| 4 | Historical closes crash demand | **Fixed** | 07-04, 03-08 and 11-02 are all `done`. |
| 5 | Backtest cache truncated by other-date runs | **Fixed** | 11-05 before and after the other dates: P10/P50/P90 531.7/589.9/678.5 and MAPE 7.13% both times. |
| 6 | Guardrail not enforced, and leaky | **Partial** | Now wired into the SMS and report (`pipeline.py:416,432`). Still a bag of numbers. These still pass: "$30 short", "$5, $7, $14, $15", "Labour was 9%", "+9%" (sign), "$86.40 OVERPAID to us", "Uber Eats Wed: $86.40 recoverable" (wrong channel), "Cash drawer $25 short" (actual $23.50). Valid derived numbers still fail ("$1,556 below usual"). |
| 7 | Closed day crashes | **Fixed** | 12-25 gives status `closed`, a "Closed today" report and no SMS. Ask: "the store was closed (Christmas)". New, related: N2 (closed *tomorrow*). |
| 8 | Ask crashes on plausible input | **Fixed** | feb 30 / june 31 get a polite clarification. Labour by channel is handled. |
| 9 | Early-history closes fail demand | **Fixed** | 11-07, 12-24 and 12-26 are `done` with the naive model. But see N2 and N4. |
| 10 | Holidays and school breaks ignored | **Fixed** | 07-04: "Independence Day, Pirates home game, CMU/Pitt on break". Mar 8: "CMU/Pitt on break". |
| 11 | First days show nan | **Partial** | No "nan". The 11-07 report still shows "Usual $0" in every channel instead of "no baseline yet". |
| 12 | Cancel-rate alert mislabeled and noisy | **Fixed** | Named "store-caused". It alerts only on crossing 1.1% (rate 1.02%, previous 0.49%: no SMS). |
| 13 | Duplicate payout lines and adjustments | **Partial** | Duplicates are now deduped (diff unchanged at −$86.38). Adjustments are still ignored: a $31.20 reversal leaves the $31.20 charge "disputable" (recoverable stays $86.40, a double dispute). The −$40 adjustment produces no finding. |
| 14 | Cash drawer edge cases | **Fixed** | OPEN shift gives `drawer_not_closed` plus its own finding. Two shifts are summed (−$73.50). |
| 15 | Demo story missing | **Fixed** | SMS: "Chashu sold out 8:39 PM, still live on apps 45 min (12 cancels)". |
| 16 | Forecast misses tomorrow; in-sample interval | **Fixed** | Tomorrow actual 607 falls inside 531–678. 80% interval coverage over the last 60 days is 0.883 (no longer 0.80 by construction). |
| 17 | Circular detection | **Partial** | `holiday_factor` is now a hand-set prior (`HOLIDAY_PRIOR`), not the generator's truth. Error-charge recall dropped to 88.5% (over-refund FNs), which suggests noise was added. Still circular: event `lift` is read from `data/raw/events.csv` (the generator's multiplier). Missing orders are still joined on an echoed POS ID (289/289). Commission is still 5/5. |
| 18 | Stock misses noodle over-portioning | **Open** | `eval.json` stock: noodles 0 of 52 weeks flagged. |
| 19 | Leakage traps in raw data | **Fixed** (for prep_log) | `prep_log` ends at 2026-11-05. Payout availability is filtered in the pipeline. Not re-verified: Ask `error_charges` vs `available_at`. |
| 20 | Wrong generated date | **Fixed** | "Generated Nov 5 11:10 PM". |
| 21 | SMS wording | **Fixed** | "DoorDash Wed: $86.40 looks recoverable (3 charges to dispute)". |
| 22 | Timezone | **Fixed** | Data now uses −04:00 in summer. Ingest converts to America/New_York. Average order hour is flat across months (16.4–16.7). |
| 23 | Ask eval set too friendly | **Fixed** (partly) | There is now a 62-question adversarial set. It is only graded for crash/clarify, not for correctness. |

Tally: 18 fixed (some with residuals), 4 partial (6, 11, 13, 17), 1 open (18), 0 regressed.

## New issues (ranked)

| # | Sev | Issue | Repro | Expected | Actual | Fix |
|---|---|---|---|---|---|---|
| N1 | **critical** | **The recount simulation reads true stock to decide when to recount.** All of the "with recount" benefit comes from this. | `python /home/claude/qa2-scripts/guard_attack.py`. It holds a verified copy of `guarded_day` (asserted equal on 15 days) with knobs. | A recount triggered only by what Gondola believes (POS-derived `seen_left`). | `guard.py:121`: `if recount and not counted and (seen_left < recount_at or true_left < recount_at)`. `pivot_sim.py:255` does the same; its comment admits it: "the line notices it running low". Over 90 days, 5% error: leaky 0 / 6 cancels (2 / 5 min delay), honest **86 / 93**. 10% error: leaky 1 / 4, honest **370 / 371** (status quo 294). The assumption "the line reliably notices at exactly 40" contradicts the team's own status-quo data: a 45-minute lag after sell-out on the demo night. | Drop the `true_left` clause. Trigger the recount on believed stock with headroom for the error: `recount_at=120` honest gives 5 / 6 cancels at 5% / 10% error (delay 5, recount sd 5), with 73 prompts in 90 days (`guard_honest_threshold.py`). Alternatively, schedule one count before the rush, or add an "86 button" for the line. Then re-run the grid and re-quote. |
| N2 | high | **A closed tomorrow is forecast as a normal day, and the card says prep 440.** The naive model path ignores `holiday_factor`. | `python -m gondola.pipeline --date 2025-12-24 --force` | Tomorrow (Christmas, closed): 0 orders, prep 0, no pause | Forecast P50 381 (305–458). Report: "Tomorrow looks like 381 orders". Card: Chashu prep 440. A new store runs on the naive model for its first ~70 days, so every early holiday (Thanksgiving prior 0.5) is affected. | Apply `holiday_factor` in the naive path. If the factor is 0, short-circuit to a "closed tomorrow" card. |
| N3 | high | **The close card accepts implausible leftover counts.** | `--chashu-left 1200`, `-50`, `nan` (CLI). Also `plan.close_card(...)` with `inf` / `nan`. | Reject, or ask to confirm, values outside about 0 to today's par. Expired portions don't count. | 1200 gives **prep 0** and "no pause", with no warning (a typo for 120 means a stock-out tomorrow). −50 is silently clamped to 0. NaN makes the plan step fail: close `partial`, card lost. `inf` raises OverflowError. Leftover counts as 100% usable: `CHASHU_HOLD_DAYS=3` is never used, and newsvendor's `leftover_value=0.6` contradicts it. | Validate 0 ≤ left ≤ today's par − used + tolerance. Reject non-finite values. Require a confirm above a threshold. Store the prep date with the leftover and age it out. |
| N4 | medium | **Portions per order come from censored sales, so prep is low after sell-out days.** | Look at `plan.portions_per_order` in the closes | About 1.08 | 2025-11-07 close: **0.568**, so target 370 for 636 planned orders. 12-25: 0.754. 12-26: 0.841. The similar days had sold out, so served portions understate demand. Separately, `pivot_sim` computes ppo from *uncensored* demand, including `data/truth/lost_sales.csv`. Its "forecast prep + guard/allocation" policies (+$11.9k) therefore use information production can't see and differ from production's prep. | Exclude sold-out days from ppo, or add item_unavailable cancels to demand. Make `pivot_sim` call the production `step_plan` logic. |
| N5 | medium | **The eval grid and pivot_sim disagree on the same scenario.** Status-quo baselines also differ. | Compare `eval.json` `guard_errors` with `pivot_sim.json` `guard_with_recount` | One number per scenario | 5% / 5 min / buffer 8: eval **6**, pivot **10**. 10%: eval **4**, pivot **13**. Status quo: eval 294 (observed cancels), pivot 424 (simulated lag on uncensored demand). The difference comes from a different buffer formula (`delay*0.6` vs EWMA rate) and seeds. | Keep one simulator. Quote one table, with seeds and confidence intervals over several seeds. |
| N6 | medium | **"Without recount" is compared to a status quo it cannot be compared to.** | `eval.json` grid | Like-for-like | No-recount Guard has no human fallback after a real sell-out, so its cancels can exceed reality: 404 at 5% error and 648 at 10%, vs 294. Cancels also *fall* as the pause delay grows (404 → 316 → 192), because the buffer scales with the delay. "5% error → 192–404" mixes three delay settings and reads as noise. | Model the manager's existing fallback (the observed lag distribution) in every arm. Report per-delay values. |
| N7 | medium | **The grid's "≤5-min pause delay" ignores Grubhub's own 10-minute lead time.** The buffer also assumes the actual delay equals the planned one. | `guard_attack.py` row F | The per-app delay from `PAUSE_DELAY_MIN` | `guarded_day` uses one delay for all apps. Honest trigger with the actual delay at 10 min (plan 2/5): 125–127 cancels at 5% error vs 86–93. | Simulate per-app delays with jitter, sized from the plan's `PAUSE_DELAY_MIN`. |
| N8 | medium | **`guarded_day` crashes on a day with no prep_log row** (closed day). | `guard.guarded_day(st, '2025-12-25')` | `{}` / skipped | `KeyError: 0` | Return early, as `replay_day` does. |
| N9 | low | **`pause_at: None` is ambiguous, and the card rarely shows anything useful.** | `plan.close_card(..., curve=[])`; the demo card | Distinguish "won't run out", "no forecast" and "closed" | An empty curve gives all None, the same as "no pause expected". At the newsvendor par (critical ratio 0.968, about 20% over P50 demand) every demo-range close shows "No pause expected". Only the busy line has times. Per-app times differ by at most one 15-minute slot (Grubhub 21:00 vs 21:15), so "per app" is mostly cosmetic. Target 0 or negative gives pause "11:00" for all apps. | Return explicit reasons. Show the minute, not the 15-minute slot. Validate the target. |
| N10 | low | **Recount noise of ±2 portions (uniform) is optimistic.** Rate and delay are not the problem. | `guard_attack.py` rows C, D, G | — | The effect is small: honest, 5% error: sd 5 gives 89–92, sd 10 gives 100–119 (vs 86–93). The rate estimate does **not** leak the future: a trailing 15-minute rate gives the same result (row G). The real flattering factor is N1. | Use sd ≈ 5–10 portions in the simulation and say so. |
| N11 | low | **True stock can go negative in the simulation.** | `guarded_day(st,'2026-11-05',count_error=1.5,seed=5)` | Clamp at 0 | `true_left` < 0. With the leaky recount it pauses at 11:01 with 3 cancels. Without recount: 273. | Clamp. Cap the error at about 3σ. |
| N12 | low | **`run_demo.py` deletes `out/`**, including `eval.json`, `pivot_sim.json` and `backtest_120d.csv` (the claim artifacts). | `python scripts/run_demo.py; ls out` | Claim files kept | Gone. I restored them from my backup. | Delete only `out/reports`, the outbox and `closes.json`, or write evals to `eval/`. |
| N13 | low | Ask: "sales on nov 6" refuses although Nov 6, 2025 has 451 orders. | `ask_qs.py` | The most recent past Nov 6 | "I only have data from Nov 6, 2025 to Nov 5, 2026." | Resolve a month+day without a year to the latest past occurrence. |
| N14 | low | Backfilling an earlier date's close changes a later close's report on re-run. | Run 11-05, then 11-02 (and others), then 11-05 again | Same 11-05 report | Findings drop from 30 to 10: the pairs verified by the later-run 11-02 close count as "earlier". | Key verification on the close date and `as_of`, not on run order, or make backfills read-only. |
| N15 | low | SMS templates are inconsistent. | `out/replay/outbox.jsonl` | One style | Two sold-out wordings: "Chashu sold out at 8:28 PM; 15 app orders were cancelled while it was still live" (no period before "Reply") and "…still live on apps 17 min (6 cancels)". Payout text uses an ISO date: "short $95.48 for 2026-10-10". | One formatter. Use "Sat Oct 10". |
| N16 | low | Cold start on a brand-new store is about 35 s, not 7 s. | `nightly_replay.csv` | — | The first replay night took 34.5 s (backtest fill on a fresh DB). The 7 s figure is the demo with existing history. 07-04 cold took 10.1 s. | Quote "about 2 s nightly; first night about 35 s". |

## Claims check

| Claim | Reproduces? | Evidence | Note |
|---|---|---|---|
| Full close ~2 s warm / 7 s cold | **Yes, for the demo date** | Demo 7.67 s (demand 6.6 s). Warm reruns 1.2–2.3 s. Replay median 2.22 s. | Replay max is 34.5 s (first night, fresh store), and other cold dates take 6–10 s. Say "first night about 35 s" if asked (N16). `run_demo.py` wall time is 13 s including ingest. |
| 47/47 replay nights | **Yes** | Re-ran `eval_nightly_replay`: 47 done, 0 partial, 0 cross-check issues | Each night ingests `upto` that date, which is correct. |
| Texts on 14 of 47 nights | **Yes** | 14 nights / 14 SMS | 9 of the 14 are chashu sell-outs, 3 cash, 2 payouts. |
| Disputable error charges 95% precision / 88% recall | **Yes** | Re-run: TP 662 / FP 33 / FN 86 → 0.9525 / 0.885 | Add: 347 more charges go to "review", and only 47 of them are truly disputable. It is synthetic data, and missing-order and commission detection are still circular (#17). |
| Forecast 8.1% vs 9.1% naive | **Yes** | Re-run: 0.081 vs 0.0912 over 120 days | A 1-point gain. Event `lift` comes from the generator (#17), so the real gap is likely smaller. Ask shows 6.1% vs 7.1% (last 30 days), a different window; quote one. |
| Guard with recount: 0–6 cancels / 90 days at ≤5-min delay vs 294 | **Numbers reproduce, but the claim is misleading** | Grid: 0, 1, 0, 6, 1, 4 | Driven by the true-stock recount trigger (N1). Honest version: 86–93 (5% error) and 370–371 (10%). `pivot_sim.json` gives 10 and 13 for the same setting (N5). Grubhub's 10-minute delay is ignored (N7). A believed-stock trigger at 120 portions restores 5–6. Fix the code, then re-quote. |
| Without recount, 5% error → 192–404 | **Numbers reproduce, but the framing is misleading** | Grid: 404 (2 min), 316 (5), 192 (15) | The range spans delays, and it is non-monotone (N6). The top of the range is worse than the 294 status quo because the simulation has no manager fallback, so it is not like-for-like. |

## Run log

- `pytest -q`: 28 passed, 173 warnings (`demand.py:37` "Mean of empty slice"), 44.8 s.
- `python scripts/run_demo.py`: `done` in 7.67 s. SMS: "3 things need you. 1) Cash drawer $23.50 short 2) DoorDash Wed: $86.40 looks recoverable (3 charges to dispute) 3) Chashu sold out 8:39 PM, still live on apps 45 min (12 cancels)". The PDF is written. The 5 Ask answers are sensible.
- `multi.sh`: closes for 9 dates plus a no-force run, all exit 0. 12-25 is `closed`. A re-tap gives `duplicate_suppressed`.
