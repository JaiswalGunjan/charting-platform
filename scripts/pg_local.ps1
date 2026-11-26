# The local PostgreSQL + TimescaleDB trial server (portable, in .tools\pgsql; data in .tools\pgdata; this PC only, port 5433).
#   powershell -ExecutionPolicy Bypass -File scripts\pg_local.ps1 start     # start it (a few seconds)
#   powershell -ExecutionPolicy Bypass -File scripts\pg_local.ps1 stop      # stop it: frees its memory
#   powershell -ExecutionPolicy Bypass -File scripts\pg_local.ps1 status
# Point the app at it with DATABASE_URL=postgresql+psycopg://charting@127.0.0.1:5433/charting (and back to SQLite by
# removing that line). Nothing is installed as a Windows service; deleting .tools\pgsql and .tools\pgdata removes it.
param([ValidateSet("start", "stop", "status")][string]$Do = "status")

$app = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $app ".tools\pgsql\bin"
$data = Join-Path $app ".tools\pgdata"
if (-not (Test-Path "$bin\pg_ctl.exe")) { throw "PostgreSQL is not in $bin" }
switch ($Do) {
    "start" {
        # started detached (no -Wait: PowerShell 5.1 would wait for the server itself), then wait until it answers
        Start-Process -FilePath "$bin\pg_ctl.exe" -ArgumentList @("-D", "`"$data`"", "-l", "`"$data\server.log`"", "start") `
            -WindowStyle Hidden
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            & "$bin\pg_isready.exe" -h 127.0.0.1 -p 5433 -q
            if ($LASTEXITCODE -eq 0) { "PostgreSQL is up on 127.0.0.1:5433"; return }
        }
        "PostgreSQL did not start within 30 s: see $data\server.log"
    }
    "stop" { & "$bin\pg_ctl.exe" -D $data -m fast stop }
    "status" { & "$bin\pg_ctl.exe" -D $data status }
}
