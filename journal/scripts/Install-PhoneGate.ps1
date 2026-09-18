<#
.SYNOPSIS
  Install (or remove) the scheduled task that keeps this node reachable from the owner's phone.

.DESCRIPTION
  Registers `DSH Phone Gate`: at logon, then every few minutes, run `phone-gate-ensure.ps1
  -Publish`. That script keeps `scripts/phone-gate.py` listening on a loopback port and
  re-asserts `tailscale serve` in front of it.

  WHY A TASK AND NOT A ONE-OFF. Everything this depends on can be lost silently:
    * the gate is an ordinary process and dies with a reboot or a crash;
    * the Serve config lives in the Tailscale daemon's state — with the daemon stopped the
      tailnet name does not resolve at all, and nothing says so;
    * the engine itself is watched by `ensure-mesh-prereqs.ps1` only indirectly.
  Measured 2026-09-16 on ZABZ-YOGA: Tailscale had already been found Stopped once, with every
  MagicDNS name dead as a result, so "the other machine is down" and "this machine is
  unpublished" look identical from the outside. The task makes the difference visible in
  `~/.dsh-sync-status/phone-gate.json` instead of guessed at.

  The task runs `-Publish` on purpose: the desired steady state is "published", so a reboot
  ends with the phone able to reach this node without anyone remembering anything. To stop
  being published, remove the task AND run `tailscale serve reset`.

.PARAMETER EnginePort
  The port this node's single engine already listens on (3099 is the launcher's default).

.PARAMETER EngineAuthority
  What the gate presents to the engine as Host and Origin. Defaults to `127.0.0.1:<EnginePort>`,
  which keeps the engine's `/api` fence closed: no network name is added to `trustedHosts`.

.EXAMPLE
  pwsh -File scripts\Install-PhoneGate.ps1 -RunNow
  pwsh -File scripts\Install-PhoneGate.ps1 -Status
  pwsh -File scripts\Install-PhoneGate.ps1 -Remove
#>
[CmdletBinding()]
param(
    [int]$ListenPort = 3086,
    [int]$EnginePort = 3099,
    [string]$EngineAuthority = "",
    [int]$IntervalMinutes = 5,
    [switch]$RunNow,
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
function Say($m) { Write-Host $m }

$taskName = 'DSH Phone Gate'
$ensure = Join-Path $PSScriptRoot 'phone-gate-ensure.ps1'
$statusFile = Join-Path $env:USERPROFILE '.dsh-sync-status\phone-gate.json'

if ($Status) {
    $t = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Say ("task '{0}': {1}" -f $taskName, $(if ($t) { $t.State } else { 'NOT installed' }))
    if ($t) {
        $i = Get-ScheduledTaskInfo -TaskName $taskName
        Say ("  last run {0}  result {1}  next {2}" -f $i.LastRunTime, $i.LastTaskResult, $i.NextRunTime)
    }
    if (Test-Path $statusFile) { Say 'last record:'; Get-Content $statusFile -Raw } else { Say 'no record yet' }
    Say ''
    & $ensure -ListenPort $ListenPort -EnginePort $EnginePort -Status
    exit 0
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Say "removed '$taskName'"
    } else { Say "'$taskName' is not installed" }
    Say "the gate process, if running, was NOT stopped - and Serve was NOT reset."
    Say "to go fully offline:  tailscale serve reset   then stop the python process on $ListenPort"
    exit 0
}

if (-not (Test-Path $ensure)) { throw "phone-gate-ensure.ps1 not found next to this script ($ensure)" }
if (-not (Get-Command python.exe -ErrorAction SilentlyContinue)) { throw 'python.exe not on PATH - the gate is a python program' }
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) { throw 'tailscale CLI not found - Serve is how the gate is published' }
if (-not $EngineAuthority) { $EngineAuthority = "127.0.0.1:$EnginePort" }

. (Join-Path $PSScriptRoot 'HiddenTaskAction.ps1')

$pwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshPath) { throw 'pwsh (PowerShell 7) not found on PATH' }

$argument = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ListenPort {1} -EnginePort {2} -EngineAuthority "{3}" -Publish' -f `
    $ensure, $ListenPort, $EnginePort, $EngineAuthority
$action = New-HiddenTaskAction -Execute $pwshPath -TaskName $taskName -Argument $argument

$atLogon = New-ScheduledTaskTrigger -AtLogOn
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# Over SSH, $env:USERDOMAIN/$env:USERNAME can be unset and Register-ScheduledTask then fails with
# "No mapping between account names and security IDs was done". Try every form we can obtain.
$userCandidates = @()
try { $userCandidates += [System.Security.Principal.WindowsIdentity]::GetCurrent().Name } catch { }
if ($env:USERDOMAIN -and $env:USERNAME) { $userCandidates += "$env:USERDOMAIN\$env:USERNAME" }
if ($env:COMPUTERNAME -and $env:USERNAME) { $userCandidates += "$env:COMPUTERNAME\$env:USERNAME" }
try { $w = (& whoami 2>$null); if ($w) { $userCandidates += $w.Trim() } } catch { }
$userCandidates = @($userCandidates | Where-Object { $_ -and $_ -match '\\' } | Select-Object -Unique)
if (-not $userCandidates) { throw 'could not determine the current user account for the scheduled task' }

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
    } catch {
        $lastErr = $_.Exception.Message
        Say ("  user '{0}' did not resolve: {1}" -f $u, $lastErr)
    }
}
if (-not $registered) { throw "could not register the task for any candidate account. Last error: $lastErr" }

$info = Get-ScheduledTask -TaskName $taskName
Say ("installed '{0}'  state={1}  every {2} min + at logon" -f $taskName, $info.State, $IntervalMinutes)
Say ("  runs: {0} {1}" -f $pwshPath, $argument)

if ($RunNow) {
    Say ''
    Say '--- running once now ---'
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 8
    $i = Get-ScheduledTaskInfo -TaskName $taskName
    Say ("last run {0}  result {1}" -f $i.LastRunTime, $i.LastTaskResult)
    & $ensure -ListenPort $ListenPort -EnginePort $EnginePort -Status
}
