# Gondola test repo (V2)

A working prototype of Gondola's close pipeline, plus the demo dataset and the harness that scores every agent against ground truth.

## Quick start

```bash
pip install -r requirements.txt
python scripts/run_demo.py          # builds data, taps Close shift for Thu Nov 5 2026, prints the text, writes the PDF
python -m pytest -q tests           # 28 checks
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
  agents/adk_graph.py   the Google ADK graph (coordinator + specialists); needs GOOGLE_API_KEY + GONDOLA_MODEL to run
  agents/ask.py         Ask agent (offline router over the same typed tools)
  agents/guardrails.py  rejects any number an agent writes that no tool returned
  report/               Jinja2 template -> PDF (Playwright + Chrome)
  storage.py            report bucket with 30-day lifecycle, rebuild on demand
  pipeline.py           Close Coordinator (parallel phases, fail-soft, idempotent)
scripts/run_demo.py, scripts/evaluate.py
tests/test_gondola.py
```

## What's real and what's simulated here

Real: every calculation, the forecast and backtests, the optimizer, the coordinator, the PDF, the bucket lifecycle, the ADK graph definition.
Simulated: the POS/app connectors (files instead of APIs), SMS/email (written to `out/outbox.jsonl` unless Twilio/SendGrid keys are set), the LLM wording (templates; the ADK graph is built but not run without a key).

## What changed in V2

- Books checks cash tonight, estimates app payouts, and verifies each app when its report lands (DoorDash next evening, Grubhub ~2 days, Uber Eats up to 72 h). Disputes are a checklist the manager submits; charges get likely valid / review / disputable.
- Stock takes confirmed portion counts for limited items at close (`--chashu-left`); the ingredient ledger is optional.
- Plan produces tomorrow's card: prep per item and predicted pause time per app, with busy-night times (`tools/plan.py: close_card`).
- Guard asks for one recount at about 40 portions left; `tools/guard.py: guarded_day` tests it under count error and pause delay (`scripts/evaluate.py` -> `guard_errors`).
- Sentinel sends one bundled text per close, only when urgent. Every text and report passes the number guardrail.
