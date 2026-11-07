# Gondola: one-command start on Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
# Creates .venv, installs requirements, installs Playwright's Chromium (for the PDF report), builds the web app if
# needed, builds the demo data if needed, then runs the API + app on http://localhost:8000 and opens it.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$Port = if ($env:PORT) { $env:PORT } else { "8000" }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
}
$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Installing Python packages ..."
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "Installing Playwright Chromium (PDF report) ..."
& $Py -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Write-Warning "Playwright Chromium install failed: PDFs will use CHROME_PATH, Chrome or Edge if installed." }

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example (everything optional; the app runs offline)."
}

if (-not (Test-Path "web\dist\index.html")) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "Building the web app ..."
        Push-Location web
        npm install
        npm run build
        Pop-Location
    } else {
        Write-Warning "web\dist is missing and npm isn't installed: the API will run without the UI. Install Node.js 18+ and re-run."
    }
}

Write-Host "Checking demo data ..."
& $Py -m gondola.setup
if ($LASTEXITCODE -ne 0) { throw "data setup failed" }

Write-Host "Starting Gondola on http://localhost:$Port (Ctrl+C to stop) ..."
Start-Job -ScriptBlock { param($p) Start-Sleep -Seconds 4; Start-Process "http://localhost:$p" } -ArgumentList $Port | Out-Null
$env:PYTHONUTF8 = "1"
& $Py -m gondola.api
