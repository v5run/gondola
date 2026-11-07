# Live integrations

> **Security update, 2026-11-07:** Application notification delivery, DoorDash writes, and Square writes/seeding are disabled, even with credentials. Configuration only indicates credentials are present; it does not enable these actions. Do not expose the unauthenticated demo through a tunnel. The setup and live-action claims below are historical and superseded by the [security audit](development/SECURITY_AUDIT.md). Low-level SMS/email adapters remain capable of sending if invoked directly by trusted code.

Gondola runs fully offline by default. Each integration switches on when its settings are in `.env` (copy `.env.example`). `GET /api/integrations` shows which are live.

| Integration | What it does | Live when | Without it |
|---|---|---|---|
| Twilio SMS | The one bundled urgent text per close; replies go to Ask | `TWILIO_*` and `ALERT_SMS_TO` set | Written to `out/outbox.jsonl` (`dry_run`) |
| SendGrid | Nightly email with the 2-page PDF attached | `SENDGRID_API_KEY`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` | Outbox (`dry_run`) |
| LLM (Gemini via ADK, or Anthropic) | Rephrases template messages; ADK Ask agent | `GOOGLE_API_KEY` (or `ANTHROPIC_API_KEY` for wording) | Templates and the offline Ask router |
| Agent mode (Google ADK) | The ADK Close Coordinator graph writes the close explanations and report summary; the Ask agent answers `/ask` and SMS questions | `GONDOLA_AGENTS=adk` plus `GOOGLE_API_KEY` (or `ANTHROPIC_API_KEY` with `pip install anthropic`) | Deterministic pipeline + templates + offline router |
| Square sandbox | Orders and cash drawer shifts for a date; sold-out write; demo order seeding | `SQUARE_ACCESS_TOKEN`, `SQUARE_LOCATION_ID` | Demo-year files in `data/raw` |
| DoorDash Marketplace | Pause one item on DoorDash only | `DOORDASH_*` set and Marketplace access granted | Logged to `out/actions_log.jsonl` (`dry_run`) |

Every message still passes the number guardrail: if the model changes or invents a number, the template is sent instead. Provider errors are logged (`failed: …`) and never stop the close.

## Setup

**Twilio (about 30 minutes, about $2 to start).**
1. Upgrade to a paid account. A trial can't send custom message text.
2. Buy a Canadian local number (about $1.15/month) and text the team's Canadian phones. US recipients need A2P 10DLC registration (vetting up to 5 business days), so don't promise texts to judges' US phones.
3. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `ALERT_SMS_TO`.
4. Replies: expose the server with `cloudflared tunnel --url http://localhost:8000` (or ngrok), set `PUBLIC_BASE_URL`, and set the number's "A message comes in" webhook to `POST {PUBLIC_BASE_URL}/api/sms/inbound`. Inbound requests are checked with `X-Twilio-Signature` (`integrations.twilio_sms.validate_signature`).
5. Send a test the day before. Have the on-screen outbox ready as a fallback.

**SendGrid (about 20 minutes, free trial 100 emails/day for 60 days).** Create an API key with Mail Send, authenticate a sending domain (a Gmail "From" often lands in spam), and set the three variables.

**Gemini (5 minutes).** Use a paid-tier key; free-tier inputs may be reviewed by people. Set `GONDOLA_MODEL` to a current model name (the 2.5 Flash line is being retired). Anthropic works for message wording through `ANTHROPIC_API_KEY`.

**Square sandbox (15 minutes, free).** In the Developer Dashboard, open the sandbox app and copy the sandbox access token and a location ID. `python -c "from gondola.integrations.square import SquareClient; print(SquareClient().seed_demo_orders(20))"` creates 20 demo-night orders paid with the sandbox test card. Cash drawer shifts can only be opened from a POS device, so the demo uses the demo-year shift unless one exists. Square's sold-out write (`set_sold_out`) removes an item on every channel, dine-in included; Gondola only uses it when `square_all_channels=True`.

**DoorDash (ask on day 1).** Create a developer account and a test store in the Developer Portal, and ask the DoorDash sponsor for Marketplace API access. The JWT (`HS256`, header `dd-ver: DD-JWT-V1`, claims `aud: doordash`, `iss` developer ID, `kid` key ID) is built by `integrations.doordash.make_jwt`; item pause is `PUT /marketplace/api/v1/stores/{store_id}/items/status`. Until access is granted, `AppPauseExecutor` logs a dry run, which the Service screen shows.

## Real vs mocked on demo day

- Real if configured: texts to the team's phones, the email with the PDF, LLM wording behind the guardrail, Square sandbox orders, DoorDash test-store item pause (if granted).
- Always mocked: Uber Eats and Grubhub pauses (partner-gated), app payout reports (CSV in the documented format), the live order stream (the demo night replayed from the database).

## Costs for the weekend

Twilio about $2 (number plus a few dozen texts), SendGrid free, Gemini a few cents per close, Square and DoorDash sandboxes free.
