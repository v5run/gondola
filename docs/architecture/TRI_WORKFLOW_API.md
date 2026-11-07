# Tri-workflow: interfaces between teams

Design: `docs/architecture/TRI_WORKFLOW.md`. This file fixes the seams so the Ledger/Review, Present, Future and frontend work can be built in parallel. Keep Savvy's Rush Control (`gondola/rush/**`, `gondola/api/rush.py`, `web/src/screens/Rush.tsx`, `web/src/api/rush.ts`, `web/src/rush.css`) working and its tests green. Wrap or reuse it; don't rewrite it. If an additive change inside `gondola/rush` is unavoidable, keep the old behavior the default and note it in `docs/development/FEATURE_COVERAGE.md`.

## Decided defaults (from the design's open questions)
- Ladder thresholds, hysteresis and queue factor weights are **per-store settings** the manager can edit (stored in `out/settings.json`; defaults in code).
- Knowledge items that would **change behavior** (Present parameters, prep rules) need **manager approval** on the Review screen; pricing/queue *policies* still go through Savvy's strategy lab. Informational facts (event effects) go active automatically once validated.
- Weather/events: offline by default (the calendar and events tables). Optional live weather via Open-Meteo (no key) behind `GONDOLA_WEATHER=openmeteo`; must degrade to offline on any error. No other external calls in tests.
- LLM: Google ADK with the configured Gemini model when `GOOGLE_API_KEY` and `GONDOLA_AGENTS=adk` are set; otherwise a deterministic offline path that produces the same structured output from templates/rules. Tests run offline (clear GOOGLE_API_KEY/ANTHROPIC_API_KEY/GONDOLA_AGENTS) and prove LLM wiring with fake models as in `tests/test_agents.py`.
- Clock: always `gondola.now` (real time; `GONDOLA_NOW` only as a test hook). Never read data after "now" for today.

## Ownership
| Team | Owns | Must not edit |
|---|---|---|
| Ledger + Review + KB | `gondola/ledger/**` (extend the base already there; keep its API), `gondola/review/**`, `gondola/kb/**`, `gondola/api/tri_past.py`, `gondola/api/tri_review.py`, the close hook in `gondola/pipeline.py`, `tests/test_ledger*.py`, `tests/test_review*.py`, `tests/test_kb*.py` | other teams' packages, `web/**` |
| Present | `gondola/present/**`, `gondola/api/tri_present.py`, `tests/test_present*.py` | `gondola/rush/**` (read/reuse only), `web/**` |
| Future | `gondola/future/**`, `gondola/api/tri_future.py`, `tests/test_future*.py` | `web/**` |
| Frontend | `web/**` | Python |

Shared files (`gondola/api/app.py`, `gondola/api/tri.py`, `requirements.txt`, `README.md`, `docs/development/FEATURE_COVERAGE.md`): append-only edits, small and clearly marked.

## Ledger API (already implemented in `gondola/ledger/__init__.py`)
`from gondola.ledger import ledger` → `ledger().append(type, date, ts, payload, source, key)`, `.extend(rows)`, `.query(date, types, start_ts, end_ts, limit, newest_first)`, `.clear_date(date, sources)`. Always pass a stable `key` so replays are idempotent.

Payload conventions:
| type | payload |
|---|---|
| `order.received` | `{order_id, channel, items:[name], subtotal, promise:"HH:MM", fulfillment:"delivery"|"pickup"|"dine_in", customer_distance_km?, courier_eta?:"HH:MM"}` |
| `order.accepted / quoted / deferred / declined` | `{order_id, reason, quoted_ready?:"HH:MM", ladder_level}` |
| `task.started / task.finished` | `{order_id, task_id, item, station, planned_min, actual_min?}` |
| `courier.eta_updated / courier.arrived` | `{order_id, channel, eta:"HH:MM", distance_km?}` |
| `customer.arrived` | `{order_id}` |
| `order.handed_off` | `{order_id, channel, ready:"HH:MM", handed:"HH:MM", wait_min, hold_min, late_min}` |
| `order.cancelled / refunded` | `{order_id, channel, reason, amount}` |
| `action.applied` | `{action:"promote"|"quote"|"pause_item"|"busy"|"resume"|"offer"|..., channel?, item?, value?, ladder_level, headroom_pct, reason, by:"controller"|"rush-agent"|"manager"}` |
| `forecast.issued` | `{horizon:"rest_of_day"|"day", for_date, total:{p10,p50,p90}, bins?:[...]}` |
| `exception.raised / resolved` | `{id, kind, severity, title, decision:"alert"|"present"|"note", note}` |
| `review.completed` | `{date, digest_id}` |

## Python interfaces between teams
- **Future → Present:** `gondola.future.nowcast.arrivals(date: str, now: datetime | None = None) -> list[dict]` → `[{time:"HH:MM", channel, p10, p50, p90}]` for each remaining 15-minute bin of `date` (empty if closed). Present uses `p50` (and p90 for buffers) to reserve capacity.
- **Future → Present/Review:** `gondola.future.items.limited_items()` → config list `[{key, name, sku, unit, used_by:{menu_item: qty}, batch, hold_days, recount_at, buffer}]` (Chashu, Ajitama egg, Gyoza, Tonkotsu broth), and `gondola.future.items.runout(date, now)` → `[{key, believed_left, projected_runout:"HH:MM"|None, pause_at:{doordash, ubereats, grubhub}}]`.
- **KB → agents:** `gondola.kb.retrieve(scope: dict, kinds: list[str] | None = None, k: int = 8, budget_tokens: int = 600) -> list[dict]` (ranked by scope match, then confidence × recency; whole items only). Present and Future call it inside `try/except ImportError` until it exists.
- **Present → others:** `gondola.present.service.state(date: str, now: datetime | None = None) -> dict` (same shape as `GET /api/present/state`).

## HTTP API (all under `/api`)
### Past (ledger)
| Method | Path | Returns |
|---|---|---|
| GET | `/past/summary?date=` | `{date, cutoff, processed, by_channel:{ch:{orders, sales}}, promises_met, promises_total, avg_wait_min, worst_wait_min, avg_hold_min, cancels, refunds, actions_count}` |
| GET | `/past/ledger?date=&types=a,b&limit=200&before_id=` | `{events:[Event], next_before_id}` newest first |

### Present
| Method | Path | Returns |
|---|---|---|
| GET | `/present/state?date=` | `{date, now, phase, headroom_pct, ladder:{level, name, since, next_threshold}, queue:[{rank, order_id, channel, items, fulfillment, promise, courier_eta, courier_distance_km, customer_distance_km, due, latest_start, slack_min, station, status:"queued"|"cooking"|"packing"|"ready", factors:{courier, distance, hold, weather, batch, fairness, in_store}, reason}], stations:[{key, name, speed, busy_until, tasks:[{order_id, item, start, end, frozen}]}], channels:{ch:{state:"open"|"quoted"|"paused_items"|"busy", quoted_extra_min, paused_items:[...]}} , actions:[recent action.applied], weather:{rain, temp_c, source}, compare?:{fifo:{promises_met, avg_wait, worst_wait, hold}, gondola:{...}}}` |
| GET (SSE) | `/present/stream?date=` | events `state` (full state on connect and every real minute or on change), `order` (new order with its rank), `action` (ladder/agent action), `done` when the day is closed |
| GET | `/present/compare?date=` | FIFO vs Gondola for the service so far (or the full day if closed): `{fifo:{...}, gondola:{...}, orders:n}` |
| POST | `/present/simulate` | body `{date, action:{...}}` → projected effect `{headroom_pct_before/after, late_orders_before/after, notes}` |
| POST | `/present/agent` | body `{date}` → runs the Rush agent now → `{decision, actions, receipt}` (offline rule path without a key) |
| GET/PUT | `/present/settings` | `{ladder:{promote_above, quote_below, pause_below, busy_below, hysteresis_min}, weights:{...}, max_wait_min}` |

### Future
| Method | Path | Returns |
|---|---|---|
| GET | `/future/today?date=` | `{date, now, so_far:{orders, expected_by_now, vs_expected_pct}, expected:{p10,p50,p90}, rest:{p10,p50,p90}, bins:[{time, channel, p10, p50, p90, actual?}], drivers:[{kind, label, time?, window?, effect_pct, channel_note?, why, estimate:bool}], adjustments:[{driver, pct, evidence, by}]}` |
| GET | `/future/days?start=&n=7` | `[{date, p10, p50, p90, rush:{start,end}, drivers:[...], weather_known:bool, cards:[{item, target, prep, on_hand, pause_at:{...}, pause_if_busy:{...}, recount_at}]}]` (start ≥ tomorrow) |
| GET | `/future/items?date=` | `{items:[{key, name, unit, believed_left, projected_runout, pause_at:{...}, recount_at}]}` |
| POST | `/future/outlook` | body `{date}` → Outlook agent run → `{adjustments:[...], notes:[...], receipt}` |

### Review
| Method | Path | Returns |
|---|---|---|
| GET | `/review/exceptions?date=` | `[{id, ts, kind, severity, title, decision, note, resolved}]` |
| POST | `/review/exceptions/{id}/resolve` | `{ok}` |
| POST | `/review/scan` | body `{date}` → run exception triggers now (normally automatic every minute while open) → new exceptions |
| GET | `/review/day/{date}` | `{date, status, well:[{text, evidence}], wrong:[{text, evidence}], causes:[{text, evidence}], actions:[{id, text, owner, check_on, measure, status}], kb_changes:[{id, op, statement, status}], digest_id}` |
| POST | `/review/run` | body `{date}` → run the Review agent for a closed day (also called by the close) |
| GET | `/review/kb?status=&kind=` | `[KB item]` (see design §6.2) |
| POST | `/review/kb/{id}/approve` / `/retire` | `{ok, item}` |
| GET | `/review/actions?status=` | `[{id, text, owner, created, check_on, measure, status, outcome?}]` |
| GET | `/review/digests?kind=day|week|month&limit=` | `[{id, kind, period, summary, numbers}]` |
| GET | `/review/context?agent=rush|outlook|exceptions|review&date=` | the exact context payload that agent would receive, with token estimate (for transparency and tests) |

## Demo world for Present
The demo store data (`data/raw`) has orders by channel and time but no promises, courier ETAs, distances or kitchen tasks. Present synthesizes them **deterministically per order id** (seeded hash) and labels them synthetic:
- Stations: `noodles` (Tonkotsu, Shoyu, Spicy Miso, Chicken Paitan, Veggie Miso, Tantanmen: 4–5 min), `fryer` (Gyoza, Karaage, Takoyaki: 3–6 min), `assembly` (Chashu Don, Chashu Bao, Edamame, Mochi Trio: 1–3 min), drinks pack only; then `packing` 1 min. Cooks per hour from the labour table; station speeds can drop on incidents.
- Promises: delivery = order time + app quote (15–25 min); pickup = order time + 15–20; dine-in = immediate (guest present).
- Courier ETA & distance: assigned a few minutes after order with drift updates; customer distance 0.5–7 km bands; rain adds noise.
- The replay of "today" up to now is deterministic, so every client sees the same state; the clock decides how far it has run.
