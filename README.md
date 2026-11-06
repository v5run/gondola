# Gondola

Nightly close-out agents for a delivery-heavy restaurant. The manager taps **Close shift**; agents reconcile the
cash drawer and app payouts, update stock, forecast tomorrow, write tomorrow's prep card, send one bundled text
and a 2-page PDF, and arm a safety net that pauses the limited item on the apps before it runs out. Ask answers
questions about the last year, in the app or by text.

## Run the app

### Windows (PowerShell or cmd)

Needs Python 3.11+ (python.org, tick "Add to PATH"). Node.js 18+ only if `web\dist` is missing.

```powershell
cd C:\path\to\gondola
powershell -ExecutionPolicy Bypass -File .\start.ps1     # or double-click start.bat
```

The script creates `.venv`, installs `requirements.txt`, runs `python -m playwright install chromium` (the browser
that prints the PDF report), copies `.env.example` to `.env`, builds `web\dist` if missing (`npm install && npm run build`),
builds the demo data and the close history if missing (`python -m gondola.setup`, see "History" below), then runs `python -m gondola.api` and opens
http://localhost:8000.

By hand, in an activated venv (`.venv\Scripts\Activate.ps1`):

```powershell
pip install -r requirements.txt
python -m playwright install chromium
python -m gondola.setup               # data + 75 nights of close history (~1-3 min the first time; --skip-history for data only)
python -m gondola.api                 # http://localhost:8000  (PORT / GONDOLA_HOST to change)
python -m pytest -q tests             # 86 tests, about 2 minutes
```

If the PDF step says no browser was found, run `python -m playwright install chromium` again, or set
`CHROME_PATH` in `.env` to `C:\Program Files\Google\Chrome\Application\chrome.exe` (Gondola also tries
installed Chrome and Edge).

### macOS / Linux

```bash
./start.sh
```

### Environment (.env)

Copy `.env.example` to `.env` (the start scripts do it). **Everything is optional**: with an empty `.env` the
app runs fully offline (texts and emails go to `out/outbox.jsonl` and show on the Alerts screen, wording comes from
templates). Fill in what you have:

| Setting | Turns on |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `ALERT_SMS_TO` | Real texts (replies need `PUBLIC_BASE_URL` + a tunnel, see docs/integrations.md) |
| `SENDGRID_API_KEY`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` | The nightly email with the PDF |
| `GOOGLE_API_KEY`, `GONDOLA_MODEL` | LLM wording behind the guardrail |
| `GONDOLA_AGENTS=adk` (with `GOOGLE_API_KEY`) | **Agent mode**: the Google ADK agent graph writes the close explanations and answers Ask |
| `SQUARE_*`, `DOORDASH_*` | Sandbox POS orders, DoorDash test-store item pause |
| `CHROME_PATH` | A specific browser for the PDF |

`GET /api/integrations` shows what is live. Restart the server after editing `.env`.

### Agent mode vs offline mode

- **Offline (default)**: `gondola/pipeline.py` runs the close as a dependency graph of the same tools the agents use;
  wording comes from templates; Ask uses a typed intent router.
- **Agent mode (`GONDOLA_AGENTS=adk` + a key)**: after the pipeline computes every number, the Close Coordinator runs the
  ADK graph (`gondola/agents/adk_graph.py`): Reconcile (Books, Stock, Demand in parallel) -> Analyst -> Plan ->
  Communicate (Report, Sentinel in parallel) -> Guard. Each specialist is an `LlmAgent` whose tools are the real
  Python functions; replies land in session state (`output_key`). The guardrail checks every reply against the tool
  results (ADK `after_model_callback`) and again against the pipeline's numbers before the Report summary is used;
  on any failure the template is kept. The numbered SMS stays the template, so replies "1"/"2"/"3" always match.
  The Close screen shows agent progress (`agent` SSE events) and `GET /api/closes/{date}` returns `agents.outputs`.
  `tests/test_agents.py` runs the whole graph with a fake model (no key needed).

## Demo script (2.5 minutes)

1. **0:00 Tonight.** Open http://localhost:8000. Thu Nov 5, rain and a Penguins game: 475 orders, $14,964 net sales,
   4% under a usual Thursday. Chashu sold out at 8:39 pm and stayed live on the apps for 45 minutes: 12 cancels.
2. **0:25 Close shift.** Tap it, confirm 0 chashu left. Steps light up (books, stock, demand in parallel, then
   analyst, plan, sentinel, report, guard) in about 30 s the first time (instant on a re-tap: it's idempotent).
3. **0:55 The text.** Alerts screen: one bundled SMS ("3 things need you": cash drawer $23.50 short, the DoorDash
   disputes, chashu). Reply `1` and `why did we run out of chashu?` (or POST /api/sms/inbound) to show replies routed to Ask.
4. **1:20 Money.** Cash drawer $23.50 short; Wednesday's DoorDash report with disputable charges and days left to
   dispute; copy-evidence checklist.
5. **1:40 Tomorrow.** 590 orders forecast (532-678), rush 6:00-7:30 pm, the prep card (chashu par vs the usual
   habit) and per-app pause times. Approve the card.
6. **2:00 Service.** Replay the night with the Guard: it asks for one recount around 7 pm (answer it, or the line's
   count is used), pauses chashu on the apps around 8:40 pm before it runs out and keeps it for dine-in.
   App cancels: 12 on the real night, 0 in the replay.
7. **2:20 Report.** Open the 2-page PDF. Close on: every number traces to a tool result, or it isn't sent.

Fallbacks: the Alerts screen is the SMS fallback if Twilio is down; the bundled `web/public/sample-report.pdf`
if the PDF can't render.

### The store clock

The dashboard runs on the real clock (America/New_York). The business day runs until 4 a.m. When the real business
date is in the data, Tonight is that day so far: only orders placed before the current minute count, the curve stops
at now, new orders arrive at their real times (no fast-forward), and Close shift unlocks at closing time (10 pm, 11 pm
Fri/Sat). Otherwise today is the latest day in the data, shown complete and closed (live dot off, "Closed"). Nothing
after today exists; past nights are a step back in the date control (← / the calendar). `GET /api/now` reports the clock.

Test hook (not for the demo): `GONDOLA_NOW=2026-11-05T19:30:00` starts the clock at that time and lets it run;
`GONDOLA_CLOCK=frozen` holds it there. The tests use it (`tests/conftest.py`, `tests/test_clock.py`), and so can
`web/scripts/e2e.py` to see orders arrive mid-service.

## What's live vs demo

| Live (real code, real results) | Demo / simulated |
|---|---|
| Every calculation, forecast + backtests, prep optimizer, coordinator, guardrail, PDF, report bucket lifecycle | The store: a generated year of Hanabi Ramen data (files instead of POS/app APIs) |
| Twilio SMS, SendGrid email, Gemini wording, ADK agent mode (when keys are set) | Texts/emails go to the outbox when keys aren't set |
| Square sandbox orders, DoorDash test-store pause (if Marketplace access is granted) | Uber Eats and Grubhub pauses (partner-gated), app payout reports (CSV), the live order stream (the data's orders released at their real times of day) |
| The Guard's rule and recount logic | "Now" is the last business date in the data (Nov 5 2026); close messages are stamped 11:10 pm that night |

## History (backfill)

The store has used Gondola for a while, so the app shows a history: `python -m gondola.setup` runs
`python -m gondola.backfill --days 75` when out/ has fewer than 30 closes. For each night from Aug 23 to Nov 5 2026 it
runs the **real** close as of 11:10 pm that night, on a copy of the database cut to that night
(`connectors.ingest.cut`, same result as `ingest(upto=...)`), with the confirmed chashu count varying 0-40 (0 after a
sell-out), an offline notifier (past nights never send real texts) and the app's report bucket. It approves each
night's card (not the final night's: the manager does that in the demo), applies the 30-day bucket lifecycle every
night, and on the 1st writes the previous month's summary and a 2-page monthly report (HTML + PDF). PDFs are printed at
the end in one browser session, only for reports still stored; the 45 expired ones keep findings.json and rebuild when
opened. Everything is staged in `.out_backfill/` and swapped into out/ at the end, so a running API never sees half a
history. Takes about 75 s here (75 nights, 33 PDFs); add ~60 s on a fresh clone for the forecast backtests.

```bash
python -m gondola.backfill --days 75                 # rebuild the history (keeps eval.json etc.)
python -m gondola.backfill --days 5 --out /tmp/out   # a small window somewhere else
python -m gondola.setup --history                    # same as the first line, via setup
```

## Command line

```bash
python scripts/run_demo.py          # builds data, taps Close shift for Thu Nov 5 2026, prints the text, writes the PDF
python -m gondola.pipeline --date 2026-11-05 --chashu-left 120 --force   # close with confirmed leftover portions
python scripts/pivot_sim.py         # policy and kitchen-load simulations -> out/pivot_sim.json
python scripts/evaluate.py          # full scoring (~5-10 min): writes out/eval.json
```

## The demo data

`python -m gondola.datagen` builds one year (Nov 6 2025 to Nov 5 2026) for a fictional store, Hanabi Ramen in Squirrel Hill, Pittsburgh:

| File (data/raw) | What it stands in for |
|---|---|
| pos_orders.csv, pos_order_lines.csv | Square/Toast orders from every channel (~173k orders, ~388k lines) |
| doordash/ubereats/grubhub_payout_report.csv | Report Builder / payout exports, with `available_at` (DoorDash D+1 evening, Uber up to 72 h) |
| cash_drawer_shifts.json | Square Cash Drawer Shifts (expected vs counted) |
| labour_shifts.csv, invoices.csv, waste_log.csv, counts.csv, prep_log.csv | Labour, deliveries, waste, weekly counts, chashu prep |
| weather_calendar.csv, events.csv | Weather, Penguins/Steelers/Pirates home games, holidays, CMU/Pitt semesters, promos |
| menu.csv, skus.csv, recipes.csv | 16 menu items, 17 ingredients, recipes |

`data/truth/` holds what the pipeline never sees: 2,300+ planted problems (disputable error charges, orders missing from payouts, commission overcharges, cash shortages, beer shrink in March, Friday noodle over-portioning, over-scheduled days), true inventory, lost sales during sell-outs, and tomorrow's actual orders.

Demo night (Thu Nov 5 2026): rain and a Penguins home game, 489 orders placed (475 completed, $14,964 net sales), chashu sells out at 8:39 pm and stays live on the apps for 45 minutes (12 cancels), the cash drawer is $23.50 short, and Wednesday's DoorDash report (arriving that night) has $86.40 in disputable charges. Tomorrow: 590 orders forecast (532–678).

## Layout

```
gondola/
  datagen.py            demo data + ground truth
  connectors/ingest.py  raw files -> one DuckDB database
  metrics.yaml/.py      one definition per number; typed metric API
  tools/                the agents' tools: books, stock, analyst, demand, plan, guard, sentinel, summary
  agents/adk_graph.py   the Google ADK graph (coordinator + specialists), agent mode runner, Ask agent
  agents/ask.py         Ask agent (offline router over the same typed tools)
  agents/guardrails.py  rejects any number an agent writes that no tool returned
  report/               Jinja2 templates (daily.html, monthly.html) -> PDF (Playwright Chromium, one browser per batch; Inter embedded)
  api/                  FastAPI app (docs/app_contract.md), SSE runs, Guard live replay, v3.py (live service stream, drill-down metrics, day detail)
  integrations/         Twilio, SendGrid, LLM (Gemini/Anthropic), Square, DoorDash
  setup.py              first-run data build + close history (python -m gondola.setup)
  backfill.py           runs the real close for past nights (python -m gondola.backfill --days 75)
  storage.py            report bucket (daily PDF+HTML+findings, monthly JSON+report), 30-day lifecycle, rebuild on demand
  pipeline.py           Close Coordinator (parallel phases, fail-soft, idempotent)
web/                    React app (built into web/dist, served at /)
scripts/run_demo.py, scripts/evaluate.py
tests/                  test_gondola.py, test_api.py, test_api_v3.py (live SSE, drill-down, reports, backfill), test_integrations.py, test_agents.py (ADK graph with a fake model)
```

## What's real and what's simulated here

Real: every calculation, the forecast and backtests, the optimizer, the coordinator, the PDF, the bucket lifecycle, the ADK graph definition.
Simulated: the POS/app connectors (files instead of APIs), SMS/email (written to `out/outbox.jsonl` unless Twilio/SendGrid keys are set), the LLM wording (templates unless agent mode or a key is set).

## What changed in V2

- Books checks cash tonight, estimates app payouts, and verifies each app when its report lands (DoorDash next evening, Grubhub ~2 days, Uber Eats up to 72 h). Disputes are a checklist the manager submits; charges get likely valid / review / disputable.
- Stock takes confirmed portion counts for limited items at close (`--chashu-left`); the ingredient ledger is optional.
- Plan produces tomorrow's card: prep per item and predicted pause time per app, with busy-night times (`tools/plan.py: close_card`).
- Guard asks for one recount at about 40 portions left; `tools/guard.py: guarded_day` tests it under count error and pause delay (`scripts/evaluate.py` -> `guard_errors`).
- Sentinel sends one bundled text per close, only when urgent. Every text and report passes the number guardrail.
