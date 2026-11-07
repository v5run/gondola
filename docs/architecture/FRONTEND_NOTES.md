# Frontend notes: contract mismatches and decisions

Checked against the running API (GONDOLA_NOW=2026-11-05T19:30:00) on 2026-11-07. The web client normalises all of these
in `web/src/api/tri.ts` (`normState`, `normSide`, `normAction`, `normToday`, `normDriver`, `normItem`, `normDay`), so
nothing below blocks the UI. Owners may want to align the contract or the code.

## Ledger / Past
- **Duplicate order events.** The ledger holds two writers for the same order: `source: "pos"` (order-level, with
  `order.handed_off` at receive time and `ready/handed/wait_min` all null) and `source: "present"` (timed). The feed
  dedupes per (type, order_id), preferring `present`, and drops untimed `pos` hand-offs. Suggest the ledger stop writing
  `pos` order lifecycle rows once Present has replayed the day, or mark them superseded.
- `/past/summary` adds `promises_met_pct` (0–1), `sales`, `late_orders`, `received`; fine (extra fields).

## Present
- `ladder.level` is `"promote"|"normal"|"quote"|"pause"|"busy"` (contract examples imply `pause_items`); `ladder.name`
  is just the title-cased level. `next_threshold` is an object `{tighten_below, relax_above, hysteresis_min}`, not a number.
- `actions[]` items carry `time:"HH:MM"` and `minute`, not `ts`, and are oldest first (last 12). Ladder moves are
  `action:"ladder"` with `from`/`value`. The UI sorts newest first.
- `compare.{fifo,gondola}.promises_met` is a **count** (`promises_met_pct` is percent); `hold` is total minutes
  (`avg_hold` is the average). The UI uses `promises_met_pct/100` and `avg_hold`.
- Ready rows have `slack_min: null` and `latest_start: null` (shown as "–").
- `POST /present/simulate` accepts only the agent's `ALLOWED` actions with specific args (quote needs `value` 5–20 and a
  delivery `channel`, pause_item needs `channel`+`item`); there is no `promote`. The ladder what-if maps rungs to
  busy/pause_item/quote/resume/offer accordingly.
- `settings.weights` also holds non-weight parameters (`courier_far_cap_min`, `rain_buffer_min`, ...) and `in_store`
  defaults to 4.0; settings also have `kitchen`, `pricing`, `agent` groups (passed through untouched on save).
- First `GET /present/state` for a day takes 10–30 s (engine build); subsequent calls are cached.

## Future
- `effect_pct`, `so_far.vs_expected_pct` and `window_effect_pct` are **percent** (10.9), not fractions.
- Past bins have `forecast_p50` + `actual` and no `p10/p50/p90`; future bins have both. Channels are
  `doordash/ubereats/grubhub/in_store` (no `pickup`, `in_store` instead of `dine_in`).
- `drivers[].window` is an object `{start, end}`; drivers carry `evidence` dates (shown as links).
- `/future/items` returns `prep` (amount made), unit singular (`portion`, `each`, `piece`, `L`), plus `per_order`;
  `/future/days` cards carry `per_order` (used for the drag-prep curve).
- Scope change: the Outlook agent UI and the 7-day horizon were removed; Future shows Rest of today and Tomorrow only.

## Review
- KB status `needs_approval` is a status value (not a flag). Exception ids look like `2026-11-05:payout:...`; resolve
  posts `{date}` too.
- Day review `evidence` is structured objects (nested numbers and date lists), not strings; the UI shows the dates found
  inside as links to that day. Action item `measure` is an object `{metric, direction, baseline, window_days, ...}`.
- Extra endpoint used: `POST /review/actions/{id}/status {status: done|not_working|open}`.
- `/review/digests` returns oldest first; the UI requests up to 400 and sorts newest first. Kinds include `shift`.
- `/review/context` returns `budget_tokens` and `dropped` (contract: token estimate only).

## UI decisions
- Sample mode (backend offline): `web/src/api/mockTri.ts`; outside service hours its clock starts at 7:30 pm on load
  and runs in real time.
- Old screens: Tonight became Past › Orders (ledger feed + KPIs, day curve kept), Tomorrow became Future › Tomorrow,
  Close shift's leftover counts moved into Review › Close run. Old URLs redirect.
