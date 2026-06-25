<#
  register_task.ps1 - register (or refresh) the Windows Task Scheduler job that
  runs the automatic market-data maintenance every weekday evening.

  Default trigger: 19:00 LOCAL time, Mon-Fri. If this machine's clock is IST,
  that is 7:00 PM IST as specified. If the machine runs in another timezone,
  pass -LocalTime to match ~19:00 IST in local terms; the orchestrator itself is
  IST-cutoff-aware regardless, so a misaligned wall-clock only shifts *when* it
  checks, never *what* it considers published.

  Usage (from an elevated PowerShell, in the repo root):
    powershell -ExecutionPolicy Bypass -File pipeline\register_task.ps1
    powershell -ExecutionPolicy Bypass -File pipeline\register_task.ps1 -LocalTime 18:30
    powershell -ExecutionPolicy Bypass -File pipeline\register_task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'NSE_Market_Data_Daily_Maintenance',
    [string]$LocalTime = '19:00',
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Wrapper = Join-Path $RepoRoot 'pipeline\run_daily_update.ps1'

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Unregistered task '$TaskName'."
    } else {
        Write-Host "Task '$TaskName' not found - nothing to do."
    }
    return
}

if (-not (Test-Path $Wrapper)) { throw "Wrapper not found: $Wrapper" }

# Action: run the PS1 wrapper hidden, no profile, bypassing execution policy.
$psExe = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $psExe `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Wrapper`"" `
    -WorkingDirectory $RepoRoot

# Trigger: weekly, Mon-Fri, at the chosen local time.
$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At $LocalTime

# Settings: allow start on battery, retry the WHOLE task 3x/15-min if it fails
# to launch, and don't stop it prematurely. (Network/publication backoff is
# handled inside the orchestrator; this is a launch-level safety net.)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 15) -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# Run as the current user, in the user's logon session (no stored password).
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description ("Automatic NSE market-data maintenance (download/panels/adjust/" +
                  "validate/health). Data only - never trades or rebalances.") `
    -Force | Out-Null

Write-Host "Registered task '$TaskName' - Mon-Fri at $LocalTime local."
Write-Host "Run now to test:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Inspect result :  Get-ScheduledTaskInfo -TaskName '$TaskName'"
