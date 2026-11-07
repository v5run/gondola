# Gondola — ML / AI Feasibility Check (as of 2026-11-04)

## Verdict

**Feasible for a weekend, but only if the scope is cut.** The forecasting core (Chronos-2 with covariates, a LightGBM baseline, quantile intervals, newsvendor pars, CP-SAT, similar-day kNN, backtesting) uses mature, open tools. Three things are likely to break or lose credibility with judges:

1. Running Chronos-2 directly on 15-minute series, because the context window can't hold a year of 15-minute data.
2. Accuracy claims such as "6% MAPE" made at grains where that number isn't achievable, or measured on synthetic data.
3. The phone-video fill-% feature. I found no evidence that it can reach ±10%.

The "10 agents" design adds cost, latency and failure points without adding much. A deterministic Python pipeline with one or two LLM calls that write the narrative is more credible.

## What works

- **Chronos-2 is real, open and supports covariates.**
  - Announced Oct 20, 2025. It supports past-only, known-future and categorical covariates, such as holiday or promo types ([Amazon Science](https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting)).
  - About 120M parameters, Apache-2.0 licence, installed with `pip install "chronos-forecasting>=2.0"`. Covariates go in through `Chronos2Pipeline` with a `future_df` ([HF model card](https://huggingface.co/amazon/chronos-2/blob/main/README.md), [autogluon/chronos-2](https://huggingface.co/autogluon/chronos-2)).
  - A 28M "small" variant is about 2x faster and is the one the authors suggest for CPU-only use ([tech report](https://arxiv.org/pdf/2510.15821v1)).
- **CPU speed is fine for hundreds of series.** Decathlon runs Chronos-2 inference on CPU (m6i.8xlarge): about 40 s for 7,000 series ([AWS blog, Aug 2026](https://aws.amazon.com/blogs/machine-learning/how-decathlon-runs-demand-forecasting-at-scale-with-chronos-2/)). A few hundred store and item series should finish in seconds to tens of seconds on a laptop. The laptop figure is my extrapolation, not a measured number.
- **Some evidence the covariates help.** On the Rossmann sales case study, promo and holiday covariates produce a much better forecast than univariate mode ([tech report](https://arxiv.org/pdf/2510.15821v1)). Decathlon reports WAPE dropping from 39% to 28% on 12-week weekly forecasts after fine-tuning (vendor-coauthored, not independently verified).
- **LightGBM is a strong, safe fallback.** Gradient boosting was the best model family on hourly sales for four German restaurants. Zero-shot Chronos-Bolt matched it in 3 of the 4 restaurants but did worse on CPU ([Arab & Benitez 2025](https://www.arxiv.org/pdf/2502.03395)). The M5 winners in both the accuracy and uncertainty tracks were LightGBM-based ([PMC review](https://pmc.ncbi.nlm.nih.gov/articles/PMC9232271)).
- **The cost of the LLM layer is small.** Estimate for roughly 10 agent calls per night at about 25k input and 1.5k output tokens each (about 250k in and 15k out in total):
  - Gemini Flash-class at $0.30 in / $2.50 out per million tokens ([pricepertoken](https://pricepertoken.com/pricing-page/model/google-gemini-2.5-flash)): about **$0.11 per night**.
  - Sonnet-class at $3 / $15 ([pricepertoken](https://pricepertoken.com/pricing-page/model/anthropic-claude-sonnet-4.5)): about **$1 per night**.
  - Latency is roughly 1–2 minutes run sequentially, or about 30 s in parallel.
- **The OR and analytics pieces are low risk.** Newsvendor pars, CP-SAT scheduling and kNN similar-day search are standard, deterministic and easy to explain.

## Where it fails / risks (ranked)

1. **Data. This is the biggest risk.** You almost certainly won't have real DoorDash store data, and on synthetic data any accuracy number or Chronos-vs-LightGBM comparison means nothing to a skeptical judge. The Kaggle Recruit Restaurant Visitor dataset is daily visitor counts only, with no 15-minute or item detail ([overview](https://kmezhoud.github.io/learn_by_example/RestaurantEDA/RestaurantEDA.html)).
2. **Chronos-2 can't see a year of 15-minute data.** Context is capped at 8,192 steps ([HF card](https://huggingface.co/amazon/chronos-2/blob/main/README.md)). At 96 steps per day that is about 85 days, so yearly patterns such as last year's game day or holiday never reach the model. The paper also benchmarks only against other foundation models (TabPFN-TS, TiRex), not LightGBM, so "Chronos beats LightGBM on single-store restaurant data" is unproven.
3. **The 6% MAPE target is plausible only for daily store totals.** Operators self-report about 60% forecast "accuracy" on average, and the best Crunchtime customers reach 90–95% ([Crunchtime, Nov 2025](https://www.crunchtime.com/blog/new-research-forecasting-accuracy-averages-just-60-even-though-most-restaurants-use-tech)). So 6% daily MAPE is best-in-class, not a default. Finer grains are much worse:
   - **15-minute slots:** with about 9 expected orders per slot, Poisson noise alone gives a MAPE of roughly 27% (√(2/πλ)) even with a perfect model.
   - **Item by daypart:** demand is intermittent, so MAPE is undefined when actuals are zero. In M5, only 7.5% of teams beat simple bottom-up exponential smoothing ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9232271)).
   - **Published numbers:** both restaurant studies I found give only relative improvements (Elder Research: 16% lower error, daily forecasts broken into 15-minute slots, [link](https://www.elderresearch.com/?p=9557); Quantiphi: about 25% lower error, [link](https://www.casestudies.com/company/quantiphi/case-study/sales-forecasting-solution-for-a-fast-food-restaurant-chain-supporting-15-mins-daily-daypart-forecasts)). Neither publishes an absolute MAPE.
4. **Backtest leakage.** Backtests that feed in actual observed weather, instead of the forecast available the night before, will look better than live performance. Promos added after the fact cause the same problem.
5. **The LLM agents are unreliable without guardrails.**
   - On τ-bench, agents that succeeded on a task once often failed when it was rerun: GPT-4o in retail fell to about 25% at pass^8, roughly a 60% drop ([Sierra](https://sierra.ai/blog/benchmarking-ai-agents)). This is 2024 data; newer models are better, but the consistency gap remains.
   - Agents will state numbers they never computed, and it reads the same as a computed one ([write-up](https://tianpan.co/blog/2026-05-17-agent-narrated-a-number-it-should-have-computed)).
6. **Google model and ADK churn.**
   - Gemini 2.5 Flash is being retired: Vertex shutdown Oct 20, 2026, and new Gemini API projects can't access it ([tokencost](https://tokencost.app/blog/gemini-2-5-shutdown-october-20-migration-cost)). Users reported 404s months before the announced date ([forum](https://discuss.ai.google.dev/t/gemini-2-5-flash-and-gemini-2-5-flash-lite-returning-404-no-longer-available-today-july-9-contradicts-oct-16-2026-shutdown-date/174267)). These are third-party pages, so check the replacement model names on Google's official deprecations page.
   - ADK's templated Sequential and Parallel agents are "superseded" in ADK 2.0 for Python and Go, in favour of graph workflows. Parallel sub-agents also don't share state ([ADK docs](https://adk.dev/agents/workflow-agents/parallel-agents/)).
7. **MAPIE time-series intervals don't fit this plan as is.**
   - MAPIE's `TimeSeriesRegressor` only supports EnbPI (needs a `BlockBootstrap` cv) and ACI, which can produce infinite intervals. The docs state no coverage guarantee ([docs](https://mapie.readthedocs.io/en/stable/generated/mapie.regression.TimeSeriesRegressor.html)).
   - The class was renamed between v0.8 (`MapieTimeSeriesRegressor`) and v1, so older tutorials break.
   - It wraps scikit-learn estimators, so Chronos-2 can't use it directly.
   - Coverage is only marginal: intervals can be right on average yet under-cover rush hours, game days and holidays.
8. **Phone-video fill % (±10%) is unsupported.**
   - Frontier vision-language models struggle to read even simple gauges; their failure is in finding where the indicator is ([MeasureBench, 2025](https://www.emergentmind.com/papers/2510.26865)).
   - PreciTaste, the commercial example, uses fixed vision sensors and publishes no fill-accuracy figure ([Intel brief](https://builders.intel.com/docs/networkbuilders/precitaste-station-assistant-1736257450.pdf)).
   - A handheld phone adds glare, steam, changing angles, pan depth and food you can't see beneath the surface.
9. **Cold start.** A brand-new store has no history. Zero-shot Chronos with weeks of data, or borrowing the daily shape from similar stores, works only roughly.

## Fixes

- **Forecast top-down.** Run Chronos-2 on **daily** totals: 8,192 steps is about 22 years, and the covariates are included. Then split each day into 15-minute slots using day-of-week and event-type shapes from the history. This is the same method Elder Research describes.
- **Choose the model by backtest.** Run LightGBM (lags, calendar, weather, `is_game`, promo) beside Chronos and keep whichever wins a rolling-origin backtest. Report that comparison honestly instead of claiming Chronos is better.
- **Report the right metric at each grain:**
  - Daily: MAPE/WAPE.
  - 15-minute: WAPE, plus whether actuals fall inside the interval.
  - Items: WAPE/MASE, never MAPE.
  - State the targets (for example daily under 10%, 15-minute 25–35%), not 6% everywhere.
- **Intervals and pars.**
  - Use Chronos-2's own quantiles, then apply split-conformal correction on rolling backtest residuals for each horizon or daypart; use MAPIE only on the LightGBM path.
  - Show actual coverage on game days separately.
  - Feed item quantiles straight into the newsvendor critical ratio.
- **No leakage.** In backtests, use the weather forecast as it stood the night before, or say clearly that observed weather was used.
- **Make the LLM layer deterministic.**
  - Write the pipeline in Python with one ADK agent, or a short `SequentialAgent` chain, that calls typed tools.
  - Have the LLM output a structured JSON schema in which every number references a tool-output ID.
  - Add a post-check that extracts every number from the prose and rejects any that doesn't match a tool output.
  - Pin a currently supported Flash model.
- **Vision.** Cut it, or demo a single still photo per pan with 5 bins (empty, ¼, ½, ¾, full) and a manager-confirm button. Don't claim ±10%.
- **Data story.** Use a clearly labelled synthetic generator with real covariates (NOAA weather, actual Penguins/Steelers schedules, US holidays), plus a sanity check on the Recruit daily dataset.

**Minimal credible stack:** pandas, chronos-forecasting (chronos-2-small on CPU), LightGBM, a hand-rolled split-conformal step, scipy newsvendor, OR-Tools CP-SAT, scikit-learn NearestNeighbors, and one ADK agent with 5–6 typed tools on a pinned Gemini Flash model.

## Sources

- https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting
- https://huggingface.co/amazon/chronos-2/blob/main/README.md
- https://huggingface.co/autogluon/chronos-2
- https://arxiv.org/pdf/2510.15821v1
- https://aws.amazon.com/blogs/machine-learning/how-decathlon-runs-demand-forecasting-at-scale-with-chronos-2/
- https://www.arxiv.org/pdf/2502.03395
- https://pmc.ncbi.nlm.nih.gov/articles/PMC9232271
- https://www.crunchtime.com/blog/new-research-forecasting-accuracy-averages-just-60-even-though-most-restaurants-use-tech
- https://www.elderresearch.com/?p=9557
- https://www.casestudies.com/company/quantiphi/case-study/sales-forecasting-solution-for-a-fast-food-restaurant-chain-supporting-15-mins-daily-daypart-forecasts
- https://mapie.readthedocs.io/en/stable/generated/mapie.regression.TimeSeriesRegressor.html
- https://sierra.ai/blog/benchmarking-ai-agents
- https://tianpan.co/blog/2026-05-17-agent-narrated-a-number-it-should-have-computed
- https://adk.dev/agents/workflow-agents/parallel-agents/
- https://pricepertoken.com/pricing-page/model/google-gemini-2.5-flash
- https://pricepertoken.com/pricing-page/model/anthropic-claude-sonnet-4.5
- https://tokencost.app/blog/gemini-2-5-shutdown-october-20-migration-cost
- https://discuss.ai.google.dev/t/gemini-2-5-flash-and-gemini-2-5-flash-lite-returning-404-no-longer-available-today-july-9-contradicts-oct-16-2026-shutdown-date/174267
- https://www.emergentmind.com/papers/2510.26865
- https://builders.intel.com/docs/networkbuilders/precitaste-station-assistant-1736257450.pdf
- https://kmezhoud.github.io/learn_by_example/RestaurantEDA/RestaurantEDA.html
