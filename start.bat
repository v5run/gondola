@echo off
rem Gondola: one-command start on Windows (cmd). Double-click or run: start.bat
setlocal
cd /d "%~dp0"
if "%PORT%"=="" set PORT=8000
set PYTHONUTF8=1

if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
)
set PY=%~dp0.venv\Scripts\python.exe
if not exist "%PY%" ( echo Could not create .venv - install Python 3.11+ from python.org & exit /b 1 )

echo Installing Python packages ...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r requirements.txt --quiet || ( echo pip install failed & exit /b 1 )

echo Installing Playwright Chromium (PDF report) ...
"%PY%" -m playwright install chromium || echo WARNING: Playwright Chromium install failed; PDFs will use CHROME_PATH, Chrome or Edge.

if not exist ".env" if exist ".env.example" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example ^(everything optional; the app runs offline^).
)

if not exist "web\dist\index.html" (
  where npm >nul 2>nul && (
    echo Building the web app ...
    pushd web
    call npm install
    call npm run build
    popd
  ) || echo WARNING: web\dist is missing and npm isn't installed; the API runs without the UI.
)

echo Checking demo data ...
"%PY%" -m gondola.setup || ( echo data setup failed & exit /b 1 )

echo Starting Gondola on http://localhost:%PORT% (Ctrl+C to stop) ...
start "" cmd /c "timeout /t 4 >nul & start http://localhost:%PORT%"
"%PY%" -m gondola.api
