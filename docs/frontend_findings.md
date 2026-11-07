# Frontend findings: backend issues (Nov 5 2026)

Found while running `web/scripts/e2e.py` against the real API. The frontend works around each one where it can. None of them were fixed in Python.

## Behaviour

1. **SMS "why did we run out of chashu?" asks for clarification.** `POST /api/sms/inbound` with that body replies "Which day or period? For example 'yesterday'…". A text sent on the close night should default to tonight, like `/ask` does for "tonight". This is the reply most likely to be tapped in the demo.
2. **Ask: "Why did we run out of chashu tonight?" returns the general night summary.** It has nothing specific to chashu: no sell-out time, minutes live on the apps, par vs sold, or recount. The Tonight data already has this ("chashu sold out at 8:39 PM; 12 app orders were cancelled while it was still live").
3. **Approvals survive a forced re-run.** `approvals.json[date]` is keyed only by date, so after `POST /close {force:true}` the `GET /closes/{date}` endpoint still returns `approved: true` and the old approved `card` instead of the new plan's card. A re-run should either clear the approval or return the new card with `approved:false`. The frontend now offers "Edit plan" so the manager can re-approve.
4. **Suppressed alerts carry no time.** On a re-run, `alerts` is `[{status:"duplicate_suppressed", key}]`. The frontend has to search `/outbox` for the original text's `ts` to say "Text already sent at 11:10 pm". Please include `sent_at` (and `body`) of the original send in the suppressed record.
5. **Outbox timestamps mix two clocks.** The close's SMS and email are stamped with simulated close time (`2026-11-05T23:10:00`), but inbound and reply SMS use wall-clock time (`17:43`, `20:54`). Sorting by `ts` puts replies before the alert they answer. The list is also in insertion order, not newest first as the contract says.

## Data shape / contract drift

6. **`/overview.vs_usual` keys are `net_sales_pct`, `orders_pct`, `avg_ticket_pct`, …** The contract and the original frontend expected `net_sales`, `orders`, and so on, which is why Tonight showed "–". The frontend now reads both. `cancels_pct: 4.2` (+420%) is correct but easy to misread; consider sending absolute deltas for counts.
7. **The email `attachment` in `/outbox` is an absolute server path** (`/home/claude/gondola-test/out/reports/2026-11-05.pdf`, from a different checkout directory). The frontend now shows `Daily Close Report · <date>.pdf` and links to `/api/reports/<date>.pdf`. The API should return a URL or a date instead.
8. **Outbox `to` is an array and `from` is a phone number.** The contract says `to` is a string. The frontend handles both. A `direction` field exists and is useful but isn't in the contract.
9. **Disputes return `for_date` and no `items`.** The contract says `date` and `items[]`. Without items, the "copy evidence" text cannot list what was on the order. `GET /closes/{date}` also returns every disputable charge (34) with no cap. That's fine now that the frontend paginates, but it does make the response large.
10. **Guard SSE has events that aren't in the contract:** `start {par}`, `recount_done {count, source}` and `sold_out {t}`. The frontend now uses all three. Please add them to `docs/app_contract.md`.

## Wording in generated text

11. **Finding titles use ISO dates** ("DoorDash short $84.86 for 2026-10-22"). These show up on Close run and in the report. "Thu Oct 22" would read better.
12. **SMS replies lack thousands separators** ("expected $1115.03, counted $1091.53"). The same reply was lowercase ("cash drawer was…") in an earlier outbox entry, so capitalisation isn't consistent.
13. **The email body uses 24-hour times** ("rush 18:00–19:30", "~21:15"). The rest of the app uses "6:00 pm".

## Report

14. **The report HTML relies on a locally installed "Inter" font.** `gondola/report/templates/daily.html` uses `font-family: "Inter"` with no `@font-face`. In the app's iframe viewer and in the PDF it falls back to Helvetica/Arial on machines without Inter. To work offline, embed the font (for example, base64 `@font-face` from the woff2 in `web/node_modules/@fontsource-variable/inter/files/`).
