<#
.SYNOPSIS
  Register (or remove) the hourly DSH session archive push on this machine.

.DESCRIPTION
  Every DSH conversation on this machine gets shipped to the secretary's archive, so no session lives
  only on one laptop. This is the same idea as `PersonalSecretary-PushVSCodeChats`, which has run hourly
  for months, and it uses the same idiom: one task, in the interactive user's context, repeating.

  The worker is `scripts/push-dsh-sessions.mjs`. It keeps a cursor in `~/.dsh/dsh-archive-state.json` and
  only ships rows that are new, so an hourly run is normally seconds — the first run is the slow one
  (~3 minutes for 42 sessions / 73 MB on this machine).

  Deliberately a separate task from `PersonalSecretary-HarnessSync`: a failing archive push must not
  mark the configuration sync as failed, and vice versa. They are different guarantees.

.EXAMPLE
  pwsh -File scripts\Install-DshArchive.ps1            # install or update
  pwsh -File scripts\Install-DshArchive.ps1 -RunNow    # install, then ship once
  pwsh -File scripts\Install-DshArchive.ps1 -Remove
#>
[CmdletBinding()]
param(
  [string]$Repo = (Split-Path -Parent $PSScriptRoot),
  [int]$IntervalMinutes = 60,
  [switch]$RunNow,
  [switch]$Remove,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$taskName = 'PersonalSecretary-PushDSHSessions'
$script = Join-Path $Repo 'scripts\push-dsh-sessions.mjs'

function Say($m) { if (-not $Quiet) { Write-Host $m } }

if ($Remove) {
  $t = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($t) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false; Say "removed task $taskName" }
  else { Say "task $taskName not present" }
  exit 0
}

if (-not (Test-Path $script)) { throw "push-dsh-sessions.mjs not found at $script" }
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) { throw 'node not found on PATH' }

$action = New-ScheduledTaskAction -Execute $node -Argument ('"{0}"' -f $script) -WorkingDirectory $Repo

$atLogon = New-ScheduledTaskTrigger -AtLogOn
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Same account resolution as Install-Autosync: over SSH the usual env vars are not set the way an
# interactive logon sets them, and Register-ScheduledTask then fails with "No mapping between account
# names and security IDs".
$userCandidates = @()
try { $userCandidates += [System.Security.Principal.WindowsIdentity]::GetCurrent().Name } catch { }
if ($env:USERDOMAIN -and $env:USERNAME) { $userCandidates += "$env:USERDOMAIN\$env:USERNAME" }
if ($env:COMPUTERNAME -and $env:USERNAME) { $userCandidates += "$env:COMPUTERNAME\$env:USERNAME" }
try { $w = (& whoami 2>$null); if ($w) { $userCandidates += $w.Trim() } } catch { }
$userCandidates = @($userCandidates | Where-Object { $_ -and $_ -match '\\' } | Select-Object -Unique)

$registered = $false
$lastErr = $null
foreach ($u in $userCandidates) {
  try {
    $principal = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon, $every) `
      -Settings $settings -Principal $principal -Force | Out-Null
    Say ("installed as user {0}" -f $u)
    $registered = $true
    break
  } catch { $lastErr = $_.Exception.Message }
}
if (-not $registered) { throw "could not register the task. Last error: $lastErr" }

Say ("installed {0}  every {1} min + at logon" -f $taskName, $IntervalMinutes)
Say ("  runs: {0} ""{1}""" -f $node, $script)

if ($RunNow) {
  Say ''
  Say '--- running once now ---'
  & $node $script
  exit $LASTEXITCODE
}
