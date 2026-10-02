<#
.SYNOPSIS
  Register (or remove) an INDEPENDENT model-failover mover on THIS machine.

.DESCRIPTION
  Why this exists (item 349, measured 2026-10-02 by dsh-shift-20261002T0101Z).

  The fleet's model default is ONE literal, `agent-default-model` in
  settings/base.yaml, and the instrument that moves it when the tier dies is
  scripts/model-failover-watch.py. Until this file, that instrument was scheduled
  by exactly ONE node: secratary's crontab. ZABZ-TECH, ZABZ-YOGA, linux-pc and
  mac-mini ran it zero times. So "the fleet has multiple blocks" was half-built:
  there are three model routes, but one machine could turn the dial. If secratary
  is dark, nothing moves the fleet default and every node stays pinned to a dead
  tier with no upper bound on the outage.

  The prior shift made the mover NODE-PORTABLE (REPO now defaults to the checkout
  the script lives in, not the literal /home/zabz/harness-config) and installed it
  on ZABZ-TECH - but installing the file is not scheduling it, and an unscheduled
  mover is not a runner.

  This installer is the repo-native scheduler path for a WINDOWS node, and it is
  deliberately the same shape as Install-MetricsSampler.ps1 / Install-Autosync.ps1 /
  Install-DshArchive.ps1, because that shape is already proven on this estate:
  a repeating `-Once` trigger (NO -AtLogOn, which was MEASURED to fail with
  "Access is denied." for a non-elevated token), battery-safe settings, a
  StartWhenAvailable so a run missed while asleep is taken on wake, and the same
  account-resolution fallback for registration over SSH.

  It does NOT touch cron. cron is forbidden to shifts and is not the mechanism
  Windows nodes use; this estate schedules Windows work with Task Scheduler, and
  this installer is that mechanism for the mover.

  Guarded against a silent no-op: the script RE-READS the task after registering
  it and throws if the repetition, the battery settings or the action did not
  take, because "the installer ran" is not "the task changed".

.EXAMPLE
  pwsh -File scripts\Install-ModelFailoverWatch.ps1              # install or update
  pwsh -File scripts\Install-ModelFailoverWatch.ps1 -RunNow      # install, then prove a run landed
  pwsh -File scripts\Install-ModelFailoverWatch.ps1 -Remove
#>
[CmdletBinding()]
param(
  # Repo root. Defaults to the parent of this script's own folder.
  [string]$Repo = (Split-Path -Parent $PSScriptRoot),
  # How often the mover probes the tiers. Matches secratary's 5-minute cron line
  # so both movers use one cadence and one N=2 consecutive-probe rule.
  [int]$IntervalMinutes = 5,
  # Interpreter. Empty = resolve python3, then python, then py -3.
  [string]$Python = '',
  [switch]$RunNow,
  [switch]$Remove,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$taskName = 'DSH Model Failover Watch'
# A name this installer owns when the original cannot be written (see REGISTER below).
$watchdogName = 'DSH Model Failover Watch Watchdog'
$script = Join-Path $Repo 'scripts\model-failover-watch.py'
$statusFile = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.dsh-model-watch\status.json'
$logFile = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.dsh-model-watch\watch.log'

function Say($m) { if (-not $Quiet) { Write-Host $m } }

if ($Remove) {
  foreach ($n in @($taskName, $watchdogName)) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($t) {
      try { Unregister-ScheduledTask -TaskName $n -Confirm:$false; Say "removed task $n" }
      catch { Say ("could not remove '{0}' (needs elevation): {1}" -f $n, $_.Exception.Message) }
    } else { Say "task $n not present" }
  }
  exit 0
}

if (-not (Test-Path $script)) { throw "model-failover-watch.py not found at $script" }

# ---- RESOLVE AN INTERPRETER, AND PROVE IT CAN RUN THIS FILE ------------------
# Node-portable means the mover must not assume secratary's /usr/bin/python3.
# Candidates are tried in order and each one is asked to compile the script, so a
# Store-alias stub that cannot run python fails HERE rather than silently in a task.
function Resolve-Python {
  param([string]$Explicit, [string]$ScriptPath)
  $cands = @()
  if ($Explicit) { $cands += @{ exe = $Explicit; pre = @() } }
  else {
    $cands += @{ exe = 'python3'; pre = @() }
    $cands += @{ exe = 'python';  pre = @() }
    $cands += @{ exe = 'py';      pre = @('-3') }
  }
  $tried = @()
  foreach ($c in $cands) {
    $cmd = Get-Command $c.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { $tried += ("{0}: not on PATH" -f $c.exe); continue }
    try {
      $probe = & $cmd.Source @($c.pre) -c "import sys; print(sys.version.split()[0])" 2>&1
      if ($LASTEXITCODE -ne 0) { $tried += ("{0}: version probe rc={1}" -f $c.exe, $LASTEXITCODE); continue }
      # Compile-only check: does THIS interpreter accept THIS file, on THIS node?
      $null = & $cmd.Source @($c.pre) -m py_compile $ScriptPath 2>&1
      if ($LASTEXITCODE -ne 0) { $tried += ("{0}: py_compile failed" -f $c.exe); continue }
      return @{ exe = $cmd.Source; pre = @($c.pre); version = ("$probe").Trim() }
    } catch { $tried += ("{0}: {1}" -f $c.exe, $_.Exception.Message) }
  }
  throw ("no usable python interpreter for {0}. Tried: {1}" -f $ScriptPath, ($tried -join '; '))
}

$py = Resolve-Python -Explicit $Python -ScriptPath $script
Say ("interpreter: {0} {1} (python {2})" -f $py.exe, ($py.pre -join ' '), $py.version)

# -X utf8/-u: the estate's Windows checkouts are not guaranteed a UTF-8 default,
# and unbuffered output means ~/.dsh-model-watch/watch.log gets each line as it
# happens instead of at process exit - a crash must not swallow the reason.
$argList = @($py.pre) + @('-X', 'utf8', '-u', ('"{0}"' -f $script))
$action = New-ScheduledTaskAction -Execute $py.exe -Argument ($argList -join ' ') `
  -WorkingDirectory $Repo

# A repeating Once is BOTH the driver and the recovery path. There is deliberately
# NO -AtLogOn trigger: MEASURED 2026-09-16 on this estate, every registration that
# included one failed with "Access is denied." for a non-elevated interactive user,
# and StartWhenAvailable + the repetition already covers logon, wake and a missed run.
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

# Every Windows node in this mesh is a laptop or a desktop that may be moved, so
# battery exceptions are not optional. MultipleInstances IgnoreNew is the overlap
# guard: a repetition that fires while a probe cycle is still running exits instead
# of racing itself over ~/.dsh-model-watch/state.json. NO RestartCount/RestartInterval:
# MEASURED 2026-09-16, setting either makes Task Scheduler reject the whole
# registration with "The task XML contains a value which is incorrectly formatted or
# out of range", and the 5-minute repetition is the recovery path anyway.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

# Same account resolution as the other installers: over SSH the usual env vars are not
# set the way an interactive logon sets them, and Register-ScheduledTask then fails with
# "No mapping between account names and security IDs".
$userCandidates = @()
try { $userCandidates += [System.Security.Principal.WindowsIdentity]::GetCurrent().Name } catch { }
if ($env:USERDOMAIN -and $env:USERNAME) { $userCandidates += "$env:USERDOMAIN\$env:USERNAME" }
if ($env:COMPUTERNAME -and $env:USERNAME) { $userCandidates += "$env:COMPUTERNAME\$env:USERNAME" }
try { $w = (& whoami 2>$null); if ($w) { $userCandidates += $w.Trim() } } catch { }
$userCandidates = @($userCandidates | Where-Object { $_ -and $_ -match '\\' } | Select-Object -Unique)

# ---- REGISTER, WITH A FALLBACK FOR A TASK THIS TOKEN CANNOT WRITE -------------
$registered = $false
$registeredName = $null
$lastErr = $null
foreach ($u in $userCandidates) {
  try {
    $principal = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $every `
      -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
    Say ("installed '{0}' as user {1}" -f $taskName, $u)
    $registered = $true; $registeredName = $taskName
    break
  } catch { $lastErr = $_.Exception.Message }
}
if (-not $registered) {
  Say ("could not register '{0}' in place: {1}" -f $taskName, $lastErr)
  Say ("falling back to a task name this token CAN own ('{0}')" -f $watchdogName)
  foreach ($u in $userCandidates) {
    try {
      $principal = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited
      Register-ScheduledTask -TaskName $watchdogName -Action $action -Trigger $every `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
      Say ("installed watchdog '{0}' as user {1}" -f $watchdogName, $u)
      $registered = $true; $registeredName = $watchdogName
      break
    } catch { $lastErr = $_.Exception.Message }
  }
}
if (-not $registered) { throw "could not register either task. Last error: $lastErr" }

# ---- VERIFY IT TOOK. A task that silently keeps its old definition IS the bug. ----
$t = Get-ScheduledTask -TaskName $registeredName -ErrorAction Stop
$rep = $t.Triggers[0].Repetition.Interval
$expected = 'PT{0}M' -f $IntervalMinutes
Say ("verified '{0}': state={1} repetition={2} action={3}" -f `
  $registeredName, $t.State, $rep, $t.Actions[0].Execute)
if ($rep -ne $expected) { throw "repetition did not take: got '$rep', expected '$expected'" }
if ($t.Settings.DisallowStartIfOnBatteries) { throw "DisallowStartIfOnBatteries is still true" }
if ($t.Settings.StopIfGoingOnBatteries) { throw "StopIfGoingOnBatteries is still true" }
if (-not $t.Settings.StartWhenAvailable) { throw "StartWhenAvailable did not take" }
if ($t.Actions[0].Arguments -notlike '*model-failover-watch.py*') {
  throw "action does not run the mover: $($t.Actions[0].Arguments)"
}
Say 'task definition verified'

# ---- -RunNow: prove a real run lands, not just that a task exists ---------------
if ($RunNow) {
  $before = $null
  if (Test-Path $statusFile) {
    try { $before = (Get-Content $statusFile -Raw | ConvertFrom-Json).updated } catch { }
  }
  $linesBefore = 0
  if (Test-Path $logFile) { $linesBefore = @(Get-Content $logFile).Count }
  $beforeShown = if ($before) { $before } else { 'absent' }
  Say ("starting '{0}' (status before: {1})" -f $registeredName, $beforeShown)
  Start-ScheduledTask -TaskName $registeredName
  $after = $before
  $deadline = (Get-Date).AddSeconds(150)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    if (Test-Path $statusFile) {
      try { $after = (Get-Content $statusFile -Raw | ConvertFrom-Json).updated } catch { }
    }
    if ($after -and $after -ne $before) { break }
  }
  $info = Get-ScheduledTaskInfo -TaskName $registeredName
  $linesAfter = 0
  if (Test-Path $logFile) { $linesAfter = @(Get-Content $logFile).Count }
  Say ("run finished: lastResult={0} status.updated={1} log lines {2} -> {3}" -f `
    $info.LastTaskResult, $after, $linesBefore, $linesAfter)
  if (-not $after -or $after -eq $before) {
    throw ("the task did not produce a fresh status.json ({0}) - a scheduled mover that never runs is exactly the defect this item is about" -f $statusFile)
  }
  if ($linesAfter -le $linesBefore) { throw "watch.log did not grow; run produced no log line" }
  Say ("PROOF: run landed; status.updated advanced {0} -> {1}, lastResult={2}" -f $before, $after, $info.LastTaskResult)
}
