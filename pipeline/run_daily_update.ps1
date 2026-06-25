<#
  run_daily_update.ps1 — scheduler entry point for the automatic market-data job.

  Wraps pipeline/auto_data_update.py:
    * forces UTF-8 (the repo's ₹-sign / cp1252 gotcha)
    * runs the data-only maintenance pass
    * maps the orchestrator's exit code (0 OK / 1 WARNING / 2 HALT) to a clear
      console line and the task's last-run result
    * appends a one-line outcome to pipeline/logs/scheduler.log

  It does ONLY data maintenance: no portfolio generation, no rebalance, no trade.
#>
[CmdletBinding()]
param(
    [int]$MaxRetries = 5,
    [double]$BaseDelay = 60,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot          # pipeline\ -> repo root
$env:PYTHONUTF8 = '1'
$LogDir = Join-Path $RepoRoot 'pipeline\logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$SchedLog = Join-Path $LogDir 'scheduler.log'

# Resolve the python launcher: prefer `py`, fall back to `python`.
$Py = (Get-Command py -ErrorAction SilentlyContinue)
if ($null -eq $Py) { $Py = (Get-Command python -ErrorAction SilentlyContinue) }
if ($null -eq $Py) {
    "$(Get-Date -Format o)  FATAL  no python launcher found" | Add-Content $SchedLog
    exit 3
}

$ScriptPath = Join-Path $RepoRoot 'pipeline\auto_data_update.py'
$args = @($ScriptPath, '--max-retries', $MaxRetries, '--base-delay', $BaseDelay)
if ($DryRun) { $args += '--dry-run' }

Push-Location $RepoRoot
try {
    & $Py.Source @args
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}

switch ($code) {
    0 { $label = 'OK' }
    1 { $label = 'WARNING' }
    2 { $label = 'HALT' }
    default { $label = "UNKNOWN($code)" }
}
"$(Get-Date -Format o)  $label  (exit $code)" | Add-Content $SchedLog

# Exit non-zero on HALT so Task Scheduler surfaces a failed last-run result.
exit $code
