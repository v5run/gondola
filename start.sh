#!/usr/bin/env bash
# Gondola: one-command start on macOS / Linux.   ./start.sh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv ..."
  python3 -m venv .venv
fi
PY=.venv/bin/python
echo "Installing Python packages ..."
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -r requirements.txt --quiet
echo "Installing Playwright Chromium (PDF report) ..."
"$PY" -m playwright install chromium || echo "WARNING: Playwright Chromium install failed; PDFs will use CHROME_PATH or an installed Chrome."
if [ ! -f .env ] && [ -f .env.example ]; then cp .env.example .env; echo "Created .env from .env.example (everything optional)."; fi
if [ ! -f web/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Building the web app ..."; (cd web && npm install && npm run build)
  else
    echo "WARNING: web/dist is missing and npm isn't installed; the API runs without the UI."
  fi
fi
echo "Checking demo data ..."
"$PY" -m gondola.setup
echo "Starting Gondola on http://localhost:$PORT (Ctrl+C to stop) ..."
( sleep 4; (command -v open >/dev/null && open "http://localhost:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://localhost:$PORT") || true ) &
exec "$PY" -m gondola.api
