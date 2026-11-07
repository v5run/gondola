# Frontend findings: backend issues, V3 (Nov 5 2026)

Found while building the V3 frontend and running `web/scripts/e2e.py` against the real API (13/13 steps pass). Nothing here was changed in Python.

## Behaviour

1. **The Tomorrow card has no `portions_per_order`.** The frontend recomputes pause times while you drag prep, using the same rule as `plan.pause_times`. That rule needs portions per order, which is in `out/close_<date>.json` → `plan.portions_per_order` but not in `GET /closes/{date}` (on the card or at the top level). The frontend reads `card[0].portions_per_order ?? portions_per_order` and falls back to 1.082, the demo night's value. With 1.082 it matches the API card exactly (770 prep → busy pauses 21:15/21:15/21:00). Please add it to each card item.
2. **Guard trusts any manager recount.** If the manager types a count that's too high, Guard never pauses. In a replay where believed was 118 and the true count was about 89, typing 112 gave no pauses, an in-store sell-out at 8:40 pm, and 17 cancels, which is worse than the 12 cancels without Gondola. Typing the true count gives 0 cancels and all 3 apps paused. Consider a sanity check, for example re-asking when the count is above believed minus the expected error, or blending the count with the model. The e2e now types a realistic count.
3. **Rebuilding a report is a side effect of `GET /reports/{date}.pdf`.** There's no explicit rebuild call, so the frontend's Rebuild button fetches the PDF. Each e2e run therefore moves one expired night to `rebuilt` for good (2026-08-23 through 08-26 so far). A `POST /reports/{date}/rebuild`, or a way to reset, would keep demos repeatable.
4. **`/metrics/intraday.usual` has no channel split.** The 15-minute breakdown compares each channel with "usual", so the frontend estimates usual-by-channel from the usual day's channel mix. Please send `usual[].by_channel`.
5. **`explain.vs_similar` has no `orders_pct`.** The day breakdown shows "vs similar" only for net sales.

## Contract drift (the frontend already uses these; please add them to docs/app_contract.md)

- Live `tick`: `placed`, and `by_channel_sales` (money). `by_channel` is order **counts**. Tonight uses `by_channel_sales` for the channel bars.
- Live `order`: `chashu`, `cancel_reason`, `held_by_gondola`. Live `event`: `app`, `chashu_left`, `source`, `live_on`. `start` and `done` both carry totals and `sold_out_at`.
- Live `event.text` is a long sentence ("Gondola paused Chashu on DoorDash with 8 portions left, kept for dine-in"). Toasts and the agent rail shorten it using `kind` and `app`.
- `/metrics/intraday`: `closed`, `baseline_dates`, and per-bin `placed` and `cancels`.
- `/metrics/range`: `open_days`, `by_channel_orders`, `prev {start, end, net_sales, orders}`, and `best_day`/`worst_day` as objects with `orders`, `rain`, `events`.
- `/reports` monthly entries: `month_name`.
- `/day/{date}`: `date`, `explain`.
