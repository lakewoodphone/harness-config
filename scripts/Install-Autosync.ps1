<#
.SYNOPSIS
  Register (or remove) the unattended harness-config sync on this machine.

.DESCRIPTION
  The repo is the source of truth and `autosync.ps1` is the worker; this file makes it run without
  anyone remembering. One task per machine, named `PersonalSecretary-HarnessSync`, at logon and every
  15 minutes, in the interactive user's context — the same idiom the rest of this fleet already uses
  (`PersonalSecretary-PushVSCodeChats` runs hourly on this pattern).

  Why logon+interval and not a service: the sync writes to `$env:LOCALAPPDATA` and `~/.dsh` for THIS
  user. A session-0 service could not reach them, and a machine-level task would need elevation for no
  benefit.

.EXAMPLE
  pwsh -File scripts\Install-Autosync.ps1              # install or update
  pwsh -File scripts\Install-Autosync.ps1 -RunNow      # install, then run once and show the result
  pwsh -File scripts\Install-Autosync.ps1 -Remove
#>
[CmdletBinding()]
param(
  [string]$Repo = (Split-Path -Parent $PSScriptRoot),
  [int]$IntervalMinutes = 15,
  [switch]$RunNow,
  [switch]$Remove,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$taskName = 'PersonalSecretary-HarnessSync'
$script = Join-Path $Repo 'scripts\autosync.ps1'

function Say($m) { if (-not $Quiet) { Write-Host $m } }

if ($Remove) {
  $t = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($t) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false; Say "removed task $taskName" }
  else { Say "task $taskName not present" }
  exit 0
}

if (-not (Test-Path $script)) { throw "autosync.ps1 not found at $script" }

$pwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshPath) { throw 'pwsh (PowerShell 7) not found on PATH — required by the autosync script' }

$action = New-ScheduledTaskAction -Execute $pwshPath `
  -Argument ('-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $script) `
  -WorkingDirectory $Repo

$atLogon = New-ScheduledTaskTrigger -AtLogOn
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(2) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
# -AtLogOn alone fires once per logon; the repeating trigger carries the interval. Both, so a machine
# that reboots is corrected within two minutes of someone logging in rather than at the next quarter hour.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon, $every) `
  -Settings $settings -Principal $principal -Force | Out-Null

$info = Get-ScheduledTask -TaskName $taskName
Say ("installed {0}  state={1}  every {2} min + at logon" -f $taskName, $info.State, $IntervalMinutes)
Say ("  runs: {0} -File ""{1}""" -f $pwshPath, $script)

if ($RunNow) {
  Say ''
  Say '--- running once now ---'
  Start-ScheduledTask -TaskName $taskName
  Start-Sleep -Seconds 6
  $i = Get-ScheduledTaskInfo -TaskName $taskName
  Say ("last run {0}  result {1}" -f $i.LastRunTime, $i.LastTaskResult)
  Say ''
  & $pwshPath -NoLogo -NoProfile -NonInteractive -File $script
  exit $LASTEXITCODE
}
