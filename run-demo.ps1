# Starts the backend (FastAPI :8000) and frontend (Vite :5173) in two windows, then opens the browser.
# Usage:  powershell -ExecutionPolicy Bypass -File .\run-demo.ps1
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$nodeDir = Join-Path $root ".tools\node"   # portable Node; falls back to a system install
if (Test-Path $nodeDir) { $env:Path = "$nodeDir;$env:Path" }

if (-not (Test-Path (Join-Path $root "backend\data\charting.db"))) {
    $envFile = Join-Path $root ".env"
    $eod = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*DATA_SOURCE\s*=\s*eod' -Quiet)
    Push-Location (Join-Path $root "backend")
    if ($eod) { Write-Host "First run: importing end-of-day CSVs from EOD_DIR (~1.5 min for NSE)..."; & $py -m app.cli import-eod }
    else { Write-Host "First run: seeding synthetic market data (~35s)..."; & $py -m app.cli seed }
    Pop-Location
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Push-Location (Join-Path $root "frontend"); npm install; Pop-Location
}

# minute bars in the local PostgreSQL + TimescaleDB (BAR_STORES=1m=timescale): that server must be up first
$envFile = Join-Path $root ".env"
if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*BAR_STORES\s*=.*timescale' -Quiet)) {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root "scripts\pg_local.ps1") start
}
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '$py' -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:Path='$nodeDir;'+`$env:Path; Set-Location '$root\frontend'; npm run dev"
Start-Sleep 4
Start-Process "http://localhost:5173"
