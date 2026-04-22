$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$manage = Join-Path $root "manage.py"

if (-not (Test-Path $python)) {
    throw "Virtual environment not found: $python"
}

if (-not (Test-Path $manage)) {
    throw "manage.py not found: $manage"
}

Write-Host "Applying PostgreSQL migrations..."
& $python $manage migrate

Write-Host "Starting Django with PostgreSQL on http://127.0.0.1:8000/ ..."
& $python $manage runserver
