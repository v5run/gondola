# Local development setup

Prepared November 5, 2026. Repository: `https://github.com/v5run/theProdigyProject`, cloned to `C:\Code\Novahacks\theProdigyProject`, branch `main`, baseline `afdb4ad4c4bfd22d51b84fd3f6772bb4dc57751c`.

**November 6 build update:** Current branch is `feat/rush-control`. [Rush Control](http://127.0.0.1:8000/rush) is implemented, with [recording, checks and production mapping](RUSH_DEMO.md). Port 8000 serves the entire demo; Vite is optional and need not be running. Google Gemini tool use is verified for the new intervention and policy lab. Merchant adapters remain simulated/unconfigured. The earlier setup results below are historical; see the latest parent progress ledger for build verification.

**New upstream integrated:** `feat/rush-control` is now rebased onto V's `origin/varun` (`300dd8d`), retaining his store-clock, time-aware dashboard and stream changes. [Integration report](VARUN_REBASE.md) records source conflict checks, recovery points and 127 passing tests. [Feature coverage](FEATURE_COVERAGE.md) is the current build checklist. Normal port 8000 uses the real clock; a temporary frozen-clock test server on port 8001 was stopped after validation.

## Open the app

- Full app/API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Frontend with hot reload: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- Interactive API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Both services were started and health-checked during setup. To restart from the repository root, use two terminals:

```powershell
.\scripts\dev.ps1 -Task api
.\scripts\dev.ps1 -Task web
```

The API also serves the built frontend, so port 8000 is sufficient for a demo. No database service or Docker installation is needed: this app uses a local DuckDB file.

## Installed and verified

| Tool | Role / status |
|---|---|
| Python 3.12.4 | Isolated `.venv`, created with `uv`; pip remains available for existing start scripts |
| uv 0.11.0 | Fast Python dependency installation; 78 requirement packages installed |
| Node 22.14.0 / npm 10.9.2 | Frontend toolchain; `npm ci` installed the existing lockfile |
| TypeScript / Vite | Existing project build and hot reload; build passed |
| pytest | Existing 86-test suite passed, including fake-model ADK tests |
| Playwright Chromium | Installed; 13 browser checks passed, with no console errors or external browser requests |
| FastAPI / Uvicorn | Backend health checked; API docs available locally |
| Git / GitHub CLI | Already installed; private repository read access verified using stored `SavvyLiu` credentials |
| py-spy through `uvx` | Used once to inspect the running test process; optional diagnostic tool, not an app dependency |

The default GitHub CLI account was not switched. A repo-local credential helper under `.git/` reads the existing `SavvyLiu` credential from GitHub CLI when Git needs it. No token is written into source files or Git config. A subsequent `git ls-remote origin HEAD` succeeded. This local helper path must be updated if the clone is moved.

## Checks

```powershell
.\scripts\dev.ps1 -Task doctor
.\scripts\dev.ps1 -Task build
.\scripts\dev.ps1 -Task test
.\scripts\dev.ps1 -Task e2e
```

The browser checks require the API running and built `web/dist`. They mutate demo approvals, outbox, reports, and screenshots. The recorded full test result was **86 passed, 1101 deprecation warnings, 129.25 seconds**. A fresh forced close completed and generated a readable **two-page PDF**. Dependency consistency check passed. Logs/probes and resolved Python versions are in ignored `.local/`.

Recreating the environment on this machine:

```powershell
uv venv --seed --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
npm.cmd --prefix web ci
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe -m gondola.setup
```

The current Python requirements use lower bounds rather than a shared exact lock; `.local/requirements-resolved.txt` records the working installation. See the environment reproducibility ticket before changing dependency versions.

## Model access and hackathon credits

The [organizer's linked Tech Guide](https://docs.google.com/document/d/e/2PACX-1vQ23oBFZ0mWiZ0exAmSPhdybzYUwyTXEW48iOTUnAyoLNMuEZD7s0safFPGlKPXsoWA7ucAhpb_zddV/pub) says every team will receive its own OpenRouter API key at the start of the hackathon. **No dollar allowance, spending limit, or actual key is included.** The guide documents provided access; it does not establish the available credit amount.

Current code supports Gemini directly and an optional Anthropic path. It does **not** yet consume `OPENROUTER_API_KEY`; copying an OpenRouter key into the Google key field will not work. OpenRouter support is the first environment/backlog ticket. [OpenRouter documentation](https://openrouter.ai/docs/quickstart), [ADK alternative-model guidance](https://adk.dev/agents/models/litellm/).

On November 6 the user supplied a Google key through the ignored local `.env`. Agent mode is now enabled with `GONDOLA_AGENTS=adk` and `GONDOLA_MODEL=gemini-3.1-flash-lite`. A real ADK run called `query_metric` and correctly returned 475 fixture orders for November 5. The running `/api/ask` endpoint then returned `mode: adk` with the same answer in 5.36 seconds. Evidence: ignored `.local/google-agent-lite-smoke.json` and `.local/google-api-ask-verified.json`. This verifies one real-model/tool round trip, not the full close graph or general agent quality.

The original `gemini-flash-latest` request received a provider 503/high-demand error and the app correctly fell back to offline text. A `gemini-3.8-flash` probe was canceled without completing; the model selected above completed successfully. Explicit model selection avoids depending on the availability of the moving default alias. No product code was changed. SMS, email, Square, and DoorDash remain unconfigured. Never put the key in chat, frontend code, or source control.

## Additional tools worth adding only when needed

- An ADK-compatible OpenRouter adapter (for example via the documented LiteLLM path), with a tool-capable model and explicit model selection. The adapter dependency is not installed because the current code does not use it yet.
- Structured agent traces for model/tool/action outcomes. Start with local persisted traces; an external observability service is optional.
- A tunnel only when testing actual inbound messaging webhooks. It is unnecessary for the current browser workflow.

The frontend dependency audit reported **4 advisories: 1 high, 3 moderate**, affecting Vite/esbuild and React Router packages. Suggested fixes include major-version changes. No forced upgrade was applied during setup; see ENV-02. The audit result is saved in `.local/npm-audit.json`.
