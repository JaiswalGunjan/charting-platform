# Starts the backend (FastAPI :8000) and frontend (Vite :5173) in two windows, then opens the browser.
# Usage:  powershell -ExecutionPolicy Bypass -File .\run-demo.ps1
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$nodeDir = Join-Path $root ".tools\node"   # portable Node; falls back to a system install
if (Test-Path $nodeDir) { $env:Path = "$nodeDir;$env:Path" }

if (-not (Test-Path (Join-Path $root "backend\data\charting.db"))) {
    Write-Host "First run: seeding synthetic market data (~35s)..."
    Push-Location (Join-Path $root "backend"); & $py -m app.cli seed; Pop-Location
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Push-Location (Join-Path $root "frontend"); npm install; Pop-Location
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '$py' -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:Path='$nodeDir;'+`$env:Path; Set-Location '$root\frontend'; npm run dev"
Start-Sleep 4
Start-Process "http://localhost:5173"
