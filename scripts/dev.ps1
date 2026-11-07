param(
    [ValidateSet('api', 'web', 'build', 'test', 'e2e', 'doctor')]
    [string]$Task = 'api'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Local environment missing. Follow docs/development/LOCAL_SETUP.md first.'
}
$env:PYTHONUTF8 = '1'
Push-Location $projectRoot
try {
    $taskExitCode = 0
    switch ($Task) {
        'api' { & $projectPython -m gondola.api; $taskExitCode = $LASTEXITCODE }
        'web' {
            Push-Location (Join-Path $projectRoot 'web')
            try { & npm.cmd run dev -- --host 127.0.0.1; $taskExitCode = $LASTEXITCODE }
            finally { Pop-Location }
        }
        'build' {
            Push-Location (Join-Path $projectRoot 'web')
            try { & npm.cmd run build; $taskExitCode = $LASTEXITCODE }
            finally { Pop-Location }
        }
        'test' { & $projectPython -m pytest -q tests; $taskExitCode = $LASTEXITCODE }
        'e2e' {
            & $projectPython web/scripts/e2e.py --base http://127.0.0.1:8000
            $taskExitCode = $LASTEXITCODE
        }
        'doctor' {
            & $projectPython --version
            & node --version
            & $projectPython -m pip check
            $taskExitCode = $LASTEXITCODE
            try {
                $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3
                Write-Output "API health: $($health.ok), version $($health.version)"
            } catch { Write-Output 'API is not running on 127.0.0.1:8000.' }
        }
    }
    if ($taskExitCode -ne 0) { throw "Development task '$Task' exited with code $taskExitCode." }
} finally { Pop-Location }
