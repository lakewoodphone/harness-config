# install-manager-tasks.ps1 — register the recurring jobs a manager workstation needs.
#
# WHY THIS IS A SCRIPT AND NOT AN INLINE COMMAND
# These jobs must run as the *user*, in their interactive context, because that is where `~/.dsh`,
# the credentials and the git checkout live. A task registered from SYSTEM runs with SYSTEM's home
# directory, and anything scoped to the user's profile then reports "no credential found" while the
# file it wants is sitting in the user's home, correctly, one directory away. That failure reads as a
# broken tool and is really a broken CONTEXT -- so the context is written down here once instead of
# being reconstructed by hand each time.
#
# TWO JOBS, DELIBERATELY SEPARATE, because they are different guarantees:
#   PersonalSecretary-PushDSHSessions  conversations reach the company archive (hourly)
#   PersonalSecretary-HarnessSync      settings, presets and journal stay current (15 min)
# A failure in one must not mark the other as failed.
#
# Both write logs under ~/.dsh/logs: a scheduled task that writes nowhere is indistinguishable from
# one that never ran, which this fleet has already paid for more than once.
#
# Usage:
#   pwsh -File install-manager-tasks.ps1                       # register/update as the current user
#   pwsh -File install-manager-tasks.ps1 -User cheve           # target another local user
#   pwsh -File install-manager-tasks.ps1 -RunNow               # register, then start once
#   pwsh -File install-manager-tasks.ps1 -Remove
[CmdletBinding()]
param(
  [string]$User = $env:USERNAME,
  [string]$Repo,
  [switch]$RunNow,
  [switch]$Remove,
  [switch]$DryRun,
  [int]$SessionIntervalMinutes = 60,
  [int]$SyncIntervalMinutes = 15
)

$ErrorActionPreference = 'Stop'

# Resolve the user's home from the account database rather than trusting env vars, because this may
# be run from SYSTEM's context (the remote exec service) where $env:USERPROFILE is NOT the target's.
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
if (-not $Repo) { $Repo = Join-Path $Home_ 'code\harness-config' }
$Dsh = Join-Path $Home_ '.dsh'
$Logs = Join-Path $Dsh 'logs'

$tasks = @(
  @{ Name = 'PersonalSecretary-PushDSHSessions'; Script = 'session-sync.cmd'; Minutes = $SessionIntervalMinutes; Why = 'conversations reach the company archive' },
  @{ Name = 'PersonalSecretary-HarnessSync';     Script = 'harness-sync.cmd'; Minutes = $SyncIntervalMinutes;   Why = 'settings, presets and journal stay current' }
)

if ($Remove) {
  foreach ($t in $tasks) {
    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
      Write-Host "removed $($t.Name)"
    } else { Write-Host "$($t.Name) not present" }
  }
  exit 0
}

if (-not (Test-Path $Repo)) { throw "repo not found: $Repo" }
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Logs | Out-Null }

# The wrappers carry the environment, so the scheduled task holds NO logic. When something breaks
# there is exactly one file to read, and the task definition never needs to change again.
$shipWrapper = @"
@echo off
rem Conversations -> the company archive. Runs as $User so ~/.dsh resolves to that user's home.
set "DSH_HOME=$Dsh"
set "USERPROFILE=$Home_"
set "HOME=$Home_"
cd /d "$Repo"
node "$Repo\scripts\push-dsh-sessions.mjs" >> "$Logs\session-sync.log" 2>&1
"@

$syncWrapper = @"
@echo off
rem Settings/presets/journal -> current. Same context rules as the shipper.
set "DSH_HOME=$Dsh"
set "USERPROFILE=$Home_"
set "HOME=$Home_"
cd /d "$Repo"
node "$Repo\scripts\harness-sync.mjs" >> "$Logs\harness-sync.log" 2>&1
"@

Write-Host "install-manager-tasks"
Write-Host "  user : $User"
Write-Host "  home : $Home_"
Write-Host "  repo : $Repo"
if ($DryRun) { Write-Host "  mode : DRY RUN" }
Write-Host ""

if (-not $DryRun) {
  Set-Content -Path (Join-Path $Repo 'scripts\session-sync.cmd') -Value $shipWrapper -Encoding ASCII
  Set-Content -Path (Join-Path $Repo 'scripts\harness-sync.cmd') -Value $syncWrapper -Encoding ASCII
  Write-Host "  wrappers written to $Repo\scripts"
}

foreach ($t in $tasks) {
  $cmd = Join-Path $Repo "scripts\$($t.Script)"
  if ($DryRun) { Write-Host "  $($t.Name): WOULD REGISTER every $($t.Minutes)m -> $cmd"; continue }
  if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
  }
  $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + $cmd + '"')
  $atLogon = New-ScheduledTaskTrigger -AtLogOn -User $User
  $every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(3) `
    -RepetitionInterval (New-TimeSpan -Minutes $t.Minutes)
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
  # RunLevel Highest + Interactive: her agent's work needs the real user context, and this is the
  # account type the launcher tasks already use successfully on this box.
  $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
  Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger @($atLogon, $every) `
    -Settings $settings -Principal $principal -Force | Out-Null
  $ok = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
  Write-Host "  $($t.Name): $($ok.State) every $($t.Minutes)m -- $($t.Why)"
}

if ($RunNow -and -not $DryRun) {
  Write-Host ""
  foreach ($t in $tasks) {
    Write-Host "  starting $($t.Name)..."
    Start-ScheduledTask -TaskName $t.Name
    Start-Sleep -Seconds 4
    $i = Get-ScheduledTaskInfo -TaskName $t.Name
    Write-Host "    last run: $($i.LastRunTime)  result: $($i.LastTaskResult)"
  }
}
Write-Host ""
Write-Host $(if ($DryRun) { 'dry run: nothing registered' } else { 'done.' })
