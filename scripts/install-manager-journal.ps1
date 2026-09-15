# Register the manager workstation's DAILY JOURNAL job on Windows.
#
# WHY THIS EXISTS (owner's requirement, 2026-09-15): her machines must keep their own journal, handoff
# notes and pain points, evolving, and hold whatever needs HER attention -- not just be able to read
# the owner's.
#
# WHAT IT WRITES: one handoff entry per day, answering the three questions the journal is built
# around -- what changed, what is next, what still hurts -- plus anything in her `attention/` folder,
# which is how work that needs HER (not the agent) gets surfaced instead of buried. Entries carry this
# hostname (the tool records it), so her notes and the owner's stay distinguishable.
#
# It is deliberately a JOB rather than something the agent must remember: a journal that depends on the
# model choosing to write it is a journal that stops existing the first busy day.
#
# Usage: pwsh -File install-manager-journal.ps1 [-User cheve] [-RunNow] [-Remove] [-DryRun]
[CmdletBinding()]
param(
  [string]$User = $env:USERNAME,
  [switch]$RunNow,
  [switch]$Remove,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$taskName = 'PersonalSecretary-Journal'

function Get-UserHome([string]$name) {
  try {
    $sid = (New-Object System.Security.Principal.NTAccount($name)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    $k = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid"
    if (Test-Path $k) {
      $p = (Get-ItemProperty $k -Name ProfileImagePath -ErrorAction Stop).ProfileImagePath
      if ($p) { return $p }
    }
  } catch { }
  return (Join-Path 'C:\Users' $name)
}

$Home_ = Get-UserHome $User
$Repo = Join-Path $Home_ 'code\harness-config'
$Dsh = Join-Path $Home_ '.dsh'
$Logs = Join-Path $Dsh 'logs'
$Script = Join-Path $Repo 'scripts\journal-daily.ps1'

if ($Remove) {
  if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "removed $taskName"
  } else { Write-Host "$taskName not present" }
  exit 0
}

if (-not (Test-Path $Repo)) { throw "harness-config not found at $Repo" }
if (-not (Test-Path $Script)) { throw "scripts/journal-daily.ps1 not found at $Script -- deliver the repo first" }
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Logs | Out-Null }

# The scheduled task carries NO logic: it invokes one wrapper that holds the environment. The
# environment matters -- the journal is found relative to USERPROFILE, and a task that runs with
# someone else's idea of HOME finds nothing (that is how this reported "not found" from a SYSTEM
# context, which looks like a missing file and is really a missing context).
$cmd = Join-Path $Repo 'scripts\journal-daily.cmd'
$wrapper = @"
@echo off
rem Daily journal entry for the manager workstation.
set "DSH_HOME=$Dsh"
set "USERPROFILE=$Home_"
set "HOME=$Home_"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$Script" >> "$Logs\journal.log" 2>&1
"@

Write-Host "install-manager-journal"
Write-Host "  user   : $User"
Write-Host "  repo   : $Repo"
Write-Host "  script : $Script"
if ($DryRun) { Write-Host "  mode   : DRY RUN"; Write-Host "  ${taskName}: WOULD REGISTER daily 09:00 + at logon"; exit 0 }

Set-Content -Path $cmd -Value $wrapper -Encoding ASCII
Write-Host "  wrapper: $cmd"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + $cmd + '"')
# Twice: at logon, and daily at 09:00 -- her day starts around 11, so the entry exists before she does.
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $User
$daily = New-ScheduledTaskTrigger -Daily -At 9:00am
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon, $daily) -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "  ${taskName}: $((Get-ScheduledTask -TaskName $taskName).State) daily 09:00 + at logon"

if ($RunNow) {
  Write-Host "  running now..."
  Start-ScheduledTask -TaskName $taskName
  Start-Sleep -Seconds 22
  Write-Host "    result: $((Get-ScheduledTaskInfo -TaskName $taskName).LastTaskResult)"
  $log = Join-Path $Logs 'journal.log'
  if (Test-Path $log) { Get-Content $log -Tail 15 | ForEach-Object { Write-Host "    $_" } }
}
