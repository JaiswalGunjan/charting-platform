# Registers (or updates) the Windows Task Scheduler jobs that run scripts/daily_update.py:
#   "Charting Lab - NSE daily update"  weekdays (Mon-Fri) at 18:30 India time: today's NSE session
#   "Charting Lab - US daily update"   every day at 08:00 India time: the US session that closed overnight
#                                      (a New York weekend or US holiday is skipped by the script)
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_update.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_update.ps1 -NseAt 19:00 -UsAt 07:30
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_update.ps1 -Remove
# Each job runs as you while you are logged on (no stored password); a run missed while the PC was off or asleep starts
# when it is back. Logs: backend\data\logs\daily_<market>_<date>.log and daily_<market>_status.json.
param([string]$NseAt = "18:30", [string]$UsAt = "08:00", [switch]$Remove)

$app = Split-Path -Parent $PSScriptRoot
$jobs = @(
    @{ Name = "Charting Lab - NSE daily update"; Market = "NSE"; At = $NseAt; Days = "Weekdays" },
    @{ Name = "Charting Lab - US daily update"; Market = "US"; At = $UsAt; Days = "Daily" }
)
# the earlier NSE-only task (scripts\nse_daily.py) is replaced by the NSE job above
Unregister-ScheduledTask -TaskName "Charting Lab - NSE daily update" -Confirm:$false -ErrorAction SilentlyContinue
if ($Remove) {
    foreach ($j in $jobs) { Unregister-ScheduledTask -TaskName $j.Name -Confirm:$false -ErrorAction SilentlyContinue }
    "Removed the daily update jobs."
    return
}
$py = Join-Path $app ".venv\Scripts\python.exe"
$script = Join-Path $app "scripts\daily_update.py"
if (-not (Test-Path $py)) { throw "Python not found: $py" }

foreach ($j in $jobs) {
    $action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`" --market $($j.Market)" -WorkingDirectory $app
    if ($j.Days -eq "Weekdays") {
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $j.At
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $j.At
    }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 5) `
        -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "Downloads the $($j.Market) day (5 retries ~5 min apart, then 5 ~10 min apart, random timing; skips weekends and $($j.Market) holidays), then runs the setup scan and the pattern screens. scripts\daily_update.py --market $($j.Market)" `
        -Force | Out-Null
    "Registered '$($j.Name)': $($j.Days) at $($j.At). Next run: $((Get-ScheduledTaskInfo -TaskName $j.Name).NextRunTime)"
}
