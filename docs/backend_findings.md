# Backend findings for the frontend (Nov 5 2026)

Smoke-tested against the running API (curl, every endpoint in docs/app_contract.md) and with `python3 web/scripts/e2e.py`: **9/9 steps pass**. docs/app_contract.md now lists the keys the API actually sends.

## Fixed from docs/frontend_findings.md

| # | Was | Now |
|---|---|---|
| 1 | SMS "why did we run out of chashu?" asked "Which day?" | "why…" / "what happened" questions without a date default to the latest close night, in `/ask` and SMS |
| 2 | "Why did we run out of chashu tonight?" gave the night summary | New sell-out intent: sell-out time, minutes live on the apps, cancels per app, missed portions, prep vs used, and tomorrow's card (prep, per-app pause times in 12-hour form, recount point) |
| 3 | Approvals survived a forced re-run | Each close has a `run_id`; an approval counts only for the run it was made on. After `POST /close {force:true}` you get the new card and `approved:false` |
| 4 | Suppressed alerts had no time | `{status:"duplicate_suppressed", key, channel, body, subject, sent_at, ts, original_status}` |
| 5 | Outbox mixed clocks, insertion order | Sorted by `ts`, newest first. Close messages keep the close time (11:10 pm demo night); inbound texts and replies are stamped close time + wall time elapsed since the close, so they sort after the alert |
| 6, 8, 10 | Contract drift (`vs_usual.*_pct`, outbox `to[]`/`from`/`direction`, guard `start`/`recount_done`/`sold_out`) | Contract doc updated to match the API (no API key renames, so nothing in web/ breaks) |
| 7 | Email `attachment` was an absolute server path | `attachment: "2026-11-05.pdf"` plus `attachment_url: "/api/reports/2026-11-05.pdf"`. Nothing stored in out/ has an absolute path any more |
| 9 | Disputes lacked `date`, `items` | Both added (`for_date` kept). Still uncapped (34 on the demo night) |
| 11 | ISO dates in finding titles | "DoorDash short $84.86 for Thu Oct 22" |
| 12 | SMS replies lacked thousands separators | "$1,115.03"; replies start with a capital |
| 13 | 24-hour times in email/report text | "rush 6:00 pm–7:30 pm", "~9:15 pm". Card fields (`pause_at`, `rush.start`) are still "HH:MM" for code |
| 14 | Report relied on a local Inter font | Inter (OFL, latin, variable weight) is embedded as a data URI in the report HTML; PDFs now embed Inter. Fallback stack adds Segoe UI for Windows |

## New things the frontend can use (optional)

- `GET /api/integrations` has `agents: {live, mode: "adk"|"offline", requested}`.
- Agent mode only (`GONDOLA_AGENTS=adk` plus a key): the close SSE stream sends extra `agent` events `{agent, status, seconds?, message?}`: `close_coordinator` first, then books, stock, demand, analyst, plan, report, sentinel, guard. EventSource ignores them unless you listen. `GET /api/closes/{date}` has `agents: {mode, model, outputs:{books, stock, demand, analyst, plan, report, sentinel, guard}, invoked, tool_calls, blocked, report_used, error}` (null offline). Each output already passed the number guardrail; a blocked one reads "I couldn't verify every number…".
- `POST /api/ask` returns `mode: "offline"|"adk"`.
- `sold_out` in close detail now also has `by_channel`, `portions_missed`, `prepped`, `used`.

## Things to know

- First close on a fresh checkout takes ~30 s (60 backtests, then cached in `out/backtest_cache.csv`); later closes take ~2–3 s.
- `cancels_pct` is a relative change (4.2 = +420%) because the usual Thursday has ~2.5 cancels. Show the absolute count next to it.
- `web/scripts/e2e.py` defaults `--chrome` to `/usr/bin/google-chrome`. It only uses it if the file exists, so it works on Windows with Playwright's Chromium, but `CHROME_PATH` or no default would be cleaner (web/ is yours).
- The server binds 127.0.0.1 by default (no Windows firewall prompt). Set `GONDOLA_HOST=0.0.0.0` to expose it.
