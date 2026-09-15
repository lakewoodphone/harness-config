# Register the manager workstation's recurring jobs on Windows.
#
# Adds to `install-manager-tasks.ps1`'s set:
#   PersonalSecretary-RepoSync   keeps lpt-hub and the secretary repo current AND makes sure work done
#                                here is committed and pushed (hourly)
#
# WHY A SEPARATE JOB FROM PersonalSecretary-HarnessSync
# They are different guarantees and fail for different reasons: HarnessSync applies configuration,
# RepoSync moves the shop's own content. A failure in one must not mask the other.
#
# WHY IT MATTERS MOST: her agent produced a real customer case file that was left UNTRACKED -- the work
# existed and nothing would ever have committed or pushed it. This job is what turns "her agent can
# write files" into "the customer's case is updated in the shop's repo".
#
# Usage: pwsh -File install-manager-repo-sync.ps1 [-User cheve] [-Minutes 60] [-RunNow] [-Remove] [-DryRun]
[CmdletBinding()]
param(
  [string]$User = $env:USERNAME,
  [int]$Minutes = 60,
  [switch]$RunNow,
  [switch]$Remove,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$taskName = 'PersonalSecretary-RepoSync'

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

if ($Remove) {
  if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "removed $taskName"
  } else { Write-Host "$taskName not present" }
  exit 0
}

if (-not (Test-Path $Repo)) { throw "harness-config not found at $Repo" }
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Logs | Out-Null }

# The wrapper carries the environment, and CRUCIALLY it sets USERPROFILE/HOME: repo-sync discovers the
# repositories from the user's home directory, and a task whose environment says otherwise finds
# nothing at all (measured -- it reported "no repositories found" from a SYSTEM context).
$wrapper = @"
@echo off
rem Shop repos: pull, commit work done here, push. Runs as $User so ~ resolves to that user's home.
set "DSH_HOME=$Dsh"
set "USERPROFILE=$Home_"
set "HOME=$Home_"
cd /d "$Repo"
node "$Repo\scripts\repo-sync.mjs" >> "$Logs\repo-sync.log" 2>&1
"@

$cmd = Join-Path $Repo 'scripts\repo-sync.cmd'

Write-Host "install-manager-repo-sync"
Write-Host "  user : $User"
Write-Host "  home : $Home_"
Write-Host "  repo : $Repo"
if ($DryRun) { Write-Host "  mode : DRY RUN" }
Write-Host ""

if (-not $DryRun) {
  Set-Content -Path $cmd -Value $wrapper -Encoding ASCII
  Write-Host "  wrapper written to $cmd"
}

if ($DryRun) { Write-Host "  ${taskName}: WOULD REGISTER every ${Minutes}m -> $cmd"; exit 0 }

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + $cmd + '"')
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $User
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(7) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon, $every) -Settings $settings -Principal $principal -Force | Out-Null
$ok = Get-ScheduledTask -TaskName $taskName
Write-Host "  ${taskName}: $($ok.State) every ${Minutes}m"

if ($RunNow) {
  Write-Host "  starting now..."
  Start-ScheduledTask -TaskName $taskName
  Start-Sleep -Seconds 25
  $i = Get-ScheduledTaskInfo -TaskName $taskName
  Write-Host "    result: $($i.LastTaskResult)"
  $log = Join-Path $Logs 'repo-sync.log'
  if (Test-Path $log) { Get-Content $log -Tail 12 | ForEach-Object { Write-Host "    $_" } }
}
