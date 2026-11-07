# Gondola app: API contract (shared by backend, frontend and integrations)

Run: `python -m gondola.api` → FastAPI + uvicorn on http://localhost:8000. The built frontend (web/dist) is served at `/`.
Dev: `cd web && npm run dev` (Vite on :5173, proxies `/api` to :8000).
Everything must work on Windows and macOS/Linux: no `%-d` strftime (use `gondola.NP`), pathlib paths, Chrome path from `CHROME_PATH` env or Playwright's bundled Chromium.
Demo "today" is the last business date in the data (2026-11-05). All money in USD, times store-local (America/New_York).

## Ownership (to avoid edit conflicts)
- Backend agent: `gondola/api/**`, small hooks in `gondola/pipeline.py` (progress callback), `tests/test_api.py`.
- Integrations agent: `gondola/integrations/**`, `gondola/config.py`, `.env.example`, Sentinel adapter wiring in `gondola/tools/sentinel.py`, `docs/integrations.md`, `tests/test_integrations.py`.
- Frontend agent: `web/**` only.

## Endpoints (JSON unless noted; all under /api)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /health | | `{ok, version}` |
| GET | /store | | `{id, name, address, today, tomorrow, first_date, limited_items:["Chashu"]}` |
| GET | /integrations | | `{twilio:{live, from}, sendgrid:{live}, llm:{live, provider, model}, square:{live, env}, doordash:{live}, agents:{live, mode:"adk"|"offline", requested}}` |
| GET | /overview | `date?` | `{date, kpis:{net_sales, orders, avg_ticket, labour_pct, cancels, avoidable_cancels}, vs_usual:{net_sales_pct, orders_pct, avg_ticket_pct, labour_pct_pct, cancels_pct} (fractions; null without a baseline), baseline_dates[], context:{rain, events[]}, curve_today:[{time, orders}], curve_usual:[{time, orders}], channels:[{key, today, usual}], last_close:{date, status, finished_at}|null}`; a closed day returns `{closed:true, kpis:null, ...}` |
| GET | /metrics/daily | `start, end` | `[{date, orders, net_sales, avg_ticket, labour_pct, cancels, avoidable_cancels, rain, events}]` |
| GET | /forecast | `date` (default tomorrow) | `{date, p10, p50, p90, rush:{start,end,peak_per_15min}, curve:[{time, orders}], similar_days:[{date, orders, why}], model}` |
| POST | /close | `{date?, portion_counts?:{chashu:number}, force?:bool}` | `{run_id, date}` (runs in a background thread) |
| GET | /close/{run_id}/events | | **SSE** stream. Events: `step` `{step, status:"running"|"done"|"failed"|"skipped", seconds?, message?}` (steps: books, stock, demand, analyst, plan, sentinel, report, guard); `finding` `{kind, title, urgency}`; `agent` `{agent, status:"running"|"done"|"failed", seconds?, message?}` (agent mode only: `close_coordinator` then each specialist); `done` `{status, seconds, date, idempotent}` |
| GET | /closes | | `[{date, status, seconds, findings_count, urgent_count}]` |
| GET | /closes/{date} | | `{date, status, seconds, log:[...], findings:[...], alerts:[...], card:[{item, target, on_hand, prep, pause_at:{doordash,ubereats,grubhub}, pause_if_busy:{...}, recount_at, warnings[]}], books:{cash, verified:[{date, channels:[...]}], estimate_today:[...]}, disputes:[{channel, order, amount, reason, days_left, for_date, date, items[]}], demand:{date,p10,p50,p90,rush}, sold_out:{at, app_cancels, minutes_live, by_channel, portions_missed, prepped, used}|null, approved:bool, agents:{mode, model, outputs:{books, stock, demand, analyst, plan, report, sentinel, guard}, invoked[], tool_calls, blocked[], report_used, error}|null}`. `alerts[]` are outbox records; a re-run's `{status:"duplicate_suppressed", key, channel, body, subject, sent_at, ts, original_status}` carries the original send. `approved` is true only for an approval of the current run: a forced re-run makes a new plan, so it returns the new card with `approved:false` |
| POST | /closes/{date}/approve | `{card?}` (edited prep numbers allowed) | `{approved:true, card}` |
| GET | /reports | | `[{date, kind:"daily"|"monthly", status:"stored"|"expired"|"rebuilt", url}]` |
| GET | /reports/{date}.pdf | | PDF (rebuilds if expired) |
| GET | /reports/{date}.html | | HTML |
| POST | /ask | `{question, today?}` | `{text, clarify:bool, calls:[...], chart:{type:"line"|"bar", x:[...], series:[{name, values}]}|null, mode:"offline"|"adk"}`. Questions without a date default to the latest close night for "why"/"what happened"; "why did we run out of chashu" answers with the sell-out time, minutes live on the apps, cancels per app, missed portions and tomorrow's card |
| GET | /outbox | | `[{channel:"sms"|"email", direction:"in"|"out", to:string[]|null, from:string|null, body, subject?, attachment:"<date>.pdf"|null, attachment_url:"/api/reports/<date>.pdf"|null, status, ts}]` sorted by `ts`, newest first. Close messages are stamped with the close time (`as_of`, 11:10 pm on the demo night); inbound texts and replies with that close time plus the wall-clock time since the close ran, so they sort after it |
| POST | /sms/inbound | Twilio form fields `From`, `Body` | TwiML `<Response><Message>…</Message></Response>` (routes to Ask; "1"/"2"/"3" return details of the bundled items) |
| POST | /guard/replay | `{date?, speed?:60, count_error?:0.05, recount?:true, start_time?:"17:00"}` | `{run_id}` |
| GET | /guard/{run_id}/events | | **SSE**: `start` `{date, par, start_time, close, speed, ...}`; `tick` `{t:"HH:MM", believed_left, sold:{in_store, doordash, ubereats, grubhub}, available:{in_store:bool, doordash:bool, ubereats:bool, grubhub:bool}, cancels, held_back}`; `recount_prompt` `{t, believed_left}`; `recount_done` `{t, count, source:"manager"|"line (no reply)"}`; `pause` `{app, t}`; `sold_out` `{t, where}`; `done` `{status, cancels, held_back, status_quo_cancels}` |
| POST | /guard/{run_id}/recount | `{count}` | `{ok}` (manager answers the prompt; if no answer within 20 simulated minutes, the true count ±2 is used) |

Notes
- SSE: `text/event-stream`, `event: <name>\ndata: <json>\n\n`; frontend uses `EventSource`.
- The Guard replay plays the demo night (or any date) order by order from the database, using the approved card (or the day's prep) as stock, at `speed`× real time (60 = one minute per second).
- Errors: `{error, detail}` with 4xx/5xx.
- Stored files (out/closes.json, out/close_<date>.json, out/outbox.jsonl, the bucket index) hold only relative paths.
- Times in generated text are 12-hour ("9:15 pm"); card fields (`pause_at`, `rush.start`) stay "HH:MM" 24-hour for code.
- Agent mode (`GONDOLA_AGENTS=adk` + `GOOGLE_API_KEY`): the ADK graph writes the report summary and per-agent explanations; numbers still come from the pipeline and pass the guardrail twice. The SMS stays the numbered template.

## V3 additions (live feel, drill-down, history)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /live/stream | `date?` (default today), `speed?` (sim seconds per real second, default 60; 400 if <= 0), `from?` "HH:MM" (default "11:00") | **SSE** replay of that day's service as if live, from the orders table. Starts with a `: gondola live` comment, then `start` `{date, from, speed, par, open:"11:00", close:"22:00"\|"23:00", orders_total, card_source:"approved"\|"plan"\|null, rush:{start, end, peak_per_15min}}`; `order` `{t:"HH:MM:SS", id, channel, items:[name], subtotal, status:"completed"\|"cancelled", cancel_reason, chashu (portions), held_by_gondola:bool}`; `tick` (every sim minute from `from` to close, totals of everything placed before that minute) `{t:"HH:MM", orders (completed), placed, net_sales, by_channel:{in_store, doordash, ubereats, grubhub} (completed orders), by_channel_sales:{...} ($), chashu_left, cancels}`; `event` `{t:"HH:MM", kind:"sold_out"\|"pause"\|"rush_start"\|"rush_end", text}` (+ `app`, `chashu_left`, `source` on pause; `live_on:[app]` on sold_out); `done` `{status:"done", date, t, ...final tick fields, sold_out_at:"HH:MM"\|null}` (`status:"closed"` for a closed day). Comment heartbeats (`: keepalive`) during gaps over 10 s. Pause = Guard's rule (pause an app when chashu left < 8 + its pause delay's sales); the text cites the previous night's approved card time if it had one. Rush = the day's own 15-min curve, dinner bins >= 75% of the peak |
| GET | /metrics/intraday | `date` | `{date, closed:bool, bins:[{time:"HH:MM", orders, by_channel:{in_store, doordash, ubereats, grubhub}, net_sales, placed, cancels}] (48 bins, 11:00-22:45; orders/by_channel/net_sales = completed), usual:[{time, orders}] (completed orders, mean of the usual-weekday baseline days; [] without a baseline), baseline_dates[]}` |
| GET | /metrics/items | `start, end` (default: the 30 days ending today) | `[{item, sold (lines on completed orders), net_sales, share (of item net sales)}]` sorted by net_sales desc |
| GET | /metrics/range | `start, end` (400 if start > end) | `{start, end, days (calendar days), open_days, net_sales, orders, avg_ticket, labour_pct, cancels, avoidable_cancels, by_channel:{in_store, doordash, ubereats, grubhub} (net sales $), by_channel_orders:{...}, vs_prev_pct:{net_sales, orders} (fractions vs the previous equal-length period; null if that period starts before the data), prev:{start, end, net_sales, orders}\|null, best_day, worst_day: {date, net_sales, orders, rain, events[]}\|null, explain (see below, vs the previous period)}` |
| GET | /day/{date} | | `{date, overview (as /overview), close (as /closes/{date}) or null, report:{status, url_html, url_pdf} or null, explain}` |
| GET | /reports | | the whole history, newest first (a monthly sorts just above the daily of the 1st it was written on): `[{date ("YYYY-MM-DD", or "YYYY-MM" for monthly), kind:"daily"\|"monthly", status:"stored"\|"expired"\|"rebuilt", url (= url_pdf, kept for older clients), url_html, url_pdf, headline, net_sales, orders, vs_usual_pct (monthly: per open day vs the previous month), urgent (count), texted:bool, recoverable_usd}]`; monthly rows also have `month_name` |
| GET | /reports/{date}.pdf / .html | | served from the bucket; an expired daily is rebuilt from its findings.json on request (~0.8 s) and becomes `rebuilt` (kept 7 days) |
| GET | /reports/monthly/{yyyy-mm}.html / .pdf | | monthly summary report (2 pages, same design as daily); 400 bad month, 404 none |

`explain` (in /day/{date} and /metrics/range):
```
{status:"ok"|"no_baseline"|"closed",
 vs_usual:{net_sales_pct, orders_pct, baseline_dates[]},          // day: last 4 same weekdays (no holidays); range: previous equal-length period (+ baseline:{start,end})
 vs_similar:{net_sales_pct, dates[]},                             // day: 5 most similar past days; range: always {null, []}
 drivers:{channel:[{key, today, usual, change}], daypart:[{key:"lunch"|"dinner"|"late", today, usual, change}]},   // $ net sales, biggest drop first
 context:{rain, snow, temp_high_c, events[]},                     // range: rain/snow = any day, temp = mean, events "Penguins home game (6)", + rain_days, snow_days
 items_up:[{item, today, usual, change}], items_down:[...]}       // units, top 3 by unit change vs the same baseline (day: per-day average)
```
Closed day: `status:"closed"`, empty drivers/items, null pcts, `context.events` holds the holiday ("Christmas (closed)").

History: the store has used Gondola for a while. `python -m gondola.backfill --days 75` runs the real close for each past night (as of 11:10 pm that night, on a database cut to that night, offline notifier, confirmed chashu 0-40), approves each card except the final night's, applies the 30-day bucket lifecycle and on the 1st writes the previous month's summary JSON + monthly report. Result for the demo: 75 nights (Aug 23 - Nov 5 2026), 30 stored dailies, 45 expired (rebuildable), monthlies 2026-08, 2026-09, 2026-10. The final night (2026-11-05) is the current close; its card waits for approval. `python -m gondola.setup` runs it if out/ has fewer than 30 closes (`--skip-history` to skip, `--history` to redo).
