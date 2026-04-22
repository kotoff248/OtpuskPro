param(
    [switch]$SkipLoadData
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$appRoot = Join-Path $projectRoot "app"
$pythonPath = "C:\Users\Kotoff\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$packagePath = Join-Path $projectRoot ".python_packages"
$dumpPath = Join-Path $appRoot "backups\sqlite_dump.json"

if (-not (Test-Path $pythonPath)) {
    throw "Bundled Python not found: $pythonPath"
}

if (-not (Test-Path $packagePath)) {
    throw "Local package directory not found: $packagePath"
}

if (-not (Test-Path (Join-Path $appRoot ".env"))) {
    throw "Create app\.env from app\.env.example and fill in DB_* before running migration."
}

if (-not (Test-Path $dumpPath) -and -not $SkipLoadData) {
    throw "SQLite dump not found: $dumpPath"
}

$env:PYTHONPATH = $packagePath

Push-Location $appRoot
try {
    & $pythonPath manage.py migrate
    if (-not $SkipLoadData) {
        & $pythonPath manage.py loaddata backups\sqlite_dump.json
    }
    & $pythonPath manage.py check
}
finally {
    Pop-Location
}
