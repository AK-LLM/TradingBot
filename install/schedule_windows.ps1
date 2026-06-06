# schedule_windows.ps1 — register STP monitor as a scheduled task.
# Runs `python monitor.py --interval 60` continuously, restarting on failure.
# Idempotent: re-running unregisters + re-creates the task.

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$LogDir      = Join-Path $env:LOCALAPPDATA "SignalTradingPlatform\Logs"
$Folder      = "\SignalTradingPlatform"
$TaskName    = "STP-Monitor"

$Python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $Python) { $Python = (Get-Command py -ErrorAction SilentlyContinue)?.Source }
if (-not $Python) {
    Write-Error "Python not found on PATH. Install Python 3.10+ first."
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (Get-ScheduledTask -TaskName $TaskName -TaskPath "$Folder\" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath "$Folder\" -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "`"$ProjectRoot\monitor.py`" --interval 60" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger2 = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 999

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath "$Folder\" `
    -Action $action `
    -Trigger @($trigger, $trigger2) `
    -Settings $settings `
    -Description "STP monitor loop (V6.0)" | Out-Null

Write-Host "OK  STP monitor registered as scheduled task: $Folder\$TaskName"
Write-Host "    Logs (stdout/stderr): see $LogDir (monitor.py logs to its own files; task scheduler doesn't pipe by default)"
Write-Host "    Inspect: Get-ScheduledTask -TaskPath '$Folder\'"
Write-Host "    Uninstall: powershell -File `"$ProjectRoot\install\uninstall_windows.ps1`""
