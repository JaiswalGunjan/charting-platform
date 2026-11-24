# Runs every test suite: backend (pytest), frontend type check + unit tests (Vitest), browser end-to-end (Playwright).
# Usage:  powershell -ExecutionPolicy Bypass -File .\run-tests.ps1 [-SkipE2E]
# The end-to-end tests start their own seeded backend (:8010) and dev server (:5180); your servers are untouched.
param([switch]$SkipE2E)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$nodeDir = Join-Path $root ".tools\node"
if (Test-Path $nodeDir) { $env:Path = "$nodeDir;$env:Path" }
$failed = @()

function Step($name, [scriptblock]$cmd) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Host "FAILED: $name" -ForegroundColor Red }
}

Push-Location (Join-Path $root "backend")
Step "backend (pytest)" { & $py -m pytest -q }
Pop-Location

Push-Location (Join-Path $root "frontend")
Step "frontend type check" { npx tsc -b }
Step "frontend unit (vitest)" { npx vitest run }
if (-not $SkipE2E) { Step "browser end-to-end (playwright)" { npx playwright test } }
Pop-Location

if ($failed.Count) { Write-Host "`nFAILED: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "`nAll test suites passed." -ForegroundColor Green
