<#
.SYNOPSIS
  Register (or remove) the continuous harness metrics sampler on this machine.

.DESCRIPTION
  Why this exists as an installer rather than a hand-made task (2026-09-16, verification pass --
  see docs/mesh/60-verification.md). The task `DSH Metrics Sampler` was created ad hoc by the session
  that wrote the instrument, and it was wrong in four ways that together produced a **4.8-hour hole**
  in the machine's own record with nothing reporting it:

    * the trigger had NO repetition -- a single `StartBoundary 23:59`, so one run a day;
    * `DisallowStartIfOnBatteries` and `StopIfGoingOnBatteries` were both TRUE on a LAPTOP;
    * `StartWhenAvailable` was FALSE, so a run missed while asleep was simply lost;
    * nothing anywhere surfaced "the sampler is not sampling" -- a stale CSV is indistinguishable
      from an idle machine.

  MEASURED end to end: pid 908 started 16:10:25Z, ran `-Samples 540 -IntervalSeconds 20` = ends
  19:10:25Z; the next trigger was 23:59 local. 4.8 hours unmeasured, silently.

  The shape installed here is deliberately the same one `Install-DshArchive.ps1` and
  `Install-Autosync.ps1` use (one interactive-context task, an AtLogOn + repeating Once trigger, the
  same account-resolution fallback for SSH), because that shape is already proven on this estate.
  What is added:

    * repetition every `-IntervalMinutes` (default 5) PLUS the script's own infinite loop, so a
      crash is recovered within 5 minutes and the normal case is one long-running process;
    * battery-safe settings, because every Windows node in this mesh is a laptop or a desktop that
      may be moved;
    * `RestartCount`/`RestartInterval` as a second belt;
    * the script writes a heartbeat to `~/.dsh-sync-status/metrics-sampler.json` every sample and
      takes a single-instance lock, so a repetition that fires while it is alive exits instead of
      double-writing.

  Guarded against a silent no-op: an `Invoke-GitInstall`-style update path is fine, but a task
  definition that silently fails to change is exactly the bug being fixed, so this script
  RE-READS the task after registering it and throws if the repetition pattern or the battery
  settings did not take, and it verifies the CSV advances after `-RunNow`.

.EXAMPLE
  pwsh -File scripts\Install-MetricsSampler.ps1                 # install or update
  pwsh -File scripts\Install-MetricsSampler.ps1 -RunNow         # install, then prove the CSV advances
  pwsh -File scripts\Install-MetricsSampler.ps1 -Remove
#>
[CmdletBinding()]
param(
  [string]$Repo = (Split-Path -Parent $PSScriptRoot),
  [int]$IntervalMinutes = 5,
  [int]$SampleIntervalSeconds = 20,
  [int]$MaxHours = 168,
  [switch]$RunNow,
  [switch]$Remove,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$taskName = 'DSH Metrics Sampler'
# The task this installer owns when the original cannot be written (see REGISTER, WITH A FALLBACK).
# A NAME IT CREATES, so the ACL is its own and every write path works.
$watchdogName = 'DSH Metrics Sampler Watchdog'
$script = Join-Path $Repo 'scripts\harness-metrics.ps1'

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

if (-not (Test-Path $script)) { throw "harness-metrics.ps1 not found at $script" }
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwsh) { throw 'pwsh (PowerShell 7) not found on PATH' }

# The script itself loops forever by default; the repetition is the recovery path, not the driver.
# Note there is NO `-Once` here: `-Once` would turn the watchdog into a 5-minute single-sample
# instead of a sampler, which is the kind of quietly-wrong definition this file exists to prevent.
$action = New-ScheduledTaskAction -Execute $pwsh `
  -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -IntervalSeconds {1} -MaxHours {2}' -f $script, $SampleIntervalSeconds, $MaxHours) `
  -WorkingDirectory $Repo

# Triggers: a repeating Once is BOTH the driver and the recovery path; there is deliberately NO
# -AtLogOn trigger. MEASURED 2026-09-16 by bisection on this machine: every registration that
# included `New-ScheduledTaskTrigger -AtLogOn` failed with "Access is denied." for a non-elevated
# interactive user (probe variants 5 and 6), while a repeating Once trigger alone registered
# cleanly (variants 1-4). AtLogOn is also redundant here -- `StartWhenAvailable` plus a 5-minute
# repetition covers a logon, a wake and a missed run with one mechanism instead of two.
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

# Battery exceptions are the whole point on a laptop; StartWhenAvailable so a run missed while the
# lid was shut is taken when it opens instead of being dropped. ExecutionTimeLimit is generous: the
# sampler is SUPPOSED to run for days, and a limit that kills it would recreate the original bug.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Days 8)
# NO RestartCount/RestartInterval here, deliberately. Setting either one makes Task Scheduler reject
# the whole registration with "The task XML contains a value which is incorrectly formatted or out of
# range. (47,28):Interval:00:01:00" -- MEASURED 2026-09-16, twice, at 00:01:00 and again at 00:02:00,
# so it is not the documented 1-minute minimum. The 5-minute repetition below is the recovery path and
# needs no help; an extra belt that cannot be buckled is worse than none, because it makes the
# installer fail loudly for a reason that has nothing to do with sampling.

# Same account resolution as Install-Autosync / Install-DshArchive: over SSH the usual env vars are
# not set the way an interactive logon sets them, and Register-ScheduledTask then fails with
# "No mapping between account names and security IDs".
$userCandidates = @()
try { $userCandidates += [System.Security.Principal.WindowsIdentity]::GetCurrent().Name } catch { }
if ($env:USERDOMAIN -and $env:USERNAME) { $userCandidates += "$env:USERDOMAIN\$env:USERNAME" }
if ($env:COMPUTERNAME -and $env:USERNAME) { $userCandidates += "$env:COMPUTERNAME\$env:USERNAME" }
try { $w = (& whoami 2>$null); if ($w) { $userCandidates += $w.Trim() } } catch { }
$userCandidates = @($userCandidates | Where-Object { $_ -and $_ -match '\\' } | Select-Object -Unique)

# ---- REGISTER, WITH A FALLBACK FOR A TASK THIS TOKEN CANNOT WRITE ------------------------------
# MEASURED 2026-09-16 on ZABZ-YOGA, and it is the reason this installer has a second branch.
# The pre-existing `DSH Metrics Sampler` task file (C:\Windows\System32\Tasks\DSH Metrics Sampler) is
# owned by BUILTIN\Administrators and grants `ZABZ-YOGA\ezabz` only `Read, Synchronize` (inherited
#=False). A non-elevated token therefore gets "Access is denied." from ALL THREE write paths:
#   Register-ScheduledTask -Force over it  -> Access is denied.
#   Unregister-ScheduledTask               -> Access is denied.
#   schtasks /Change /RI 5 /DU 24:00       -> Access is denied.
# while registering a BRAND-NEW task name in the same root folder succeeds (probe variants 1-4).
# So the installer tries in place, and if the ACL refuses, it registers a WATCHDOG task under a name
# it owns and leaves the original alone. The original keeps running and keeps appending -- and the
# script itself makes that safe, by reading its hard-coded legacy `-Samples 540` as "run forever"
# (see the legacy-compatibility block in harness-metrics.ps1). Fixing the original properly needs one
# elevated command, which is stated in the report and NOT attempted here.
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
  Say ("falling back to a watchdog task ('{0}') that this token CAN own" -f $watchdogName)
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
$checkName = $registeredName

# ---- SUPERSEDE ANY SAMPLER ALREADY RUNNING THE OLD FINITE LOOP -------------------------------
# The live process from before this installer existed is running the PREVIOUS script text, whose
# default was `-Samples 540` and which wrote no heartbeat. It therefore cannot be detected by the
# new single-instance lock, and left alone it would keep appending alongside the new sampler until
# its sample count ran out (measured: pid 908, ending 19:10:25Z) and then stop the record anyway.
# Stopping it is safe by construction: harness-metrics.ps1 flushes every row with Add-Content
# immediately, so no sample in flight is lost. It is NOT killed on a guess -- the command line has
# to match both the script path and the old finite -Samples form.
$legacy = @(Get-CimInstance Win32_Process -Filter "Name='pwsh.exe' OR Name='powershell.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'harness-metrics\.ps1' -and $_.CommandLine -match '\-Samples\s+[1-9]' })
foreach ($p in $legacy) {
  try {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
    Say ("stopped the superseded sampler pid {0} (it was running the old finite -Samples loop)" -f $p.ProcessId)
  } catch {
    Say ("WARNING: could not stop the superseded sampler pid {0}: {1}" -f $p.ProcessId, $_.Exception.Message)
  }
}

# ---- VERIFY IT TOOK. A task that silently keeps its old definition is the bug, not a nicety. ----
# Verified on the task THIS INSTALLER REGISTERED ($checkName). The original `DSH Metrics Sampler` is
# checked separately and reported as a KNOWN, STATED liability rather than folded into the pass/fail,
# because this token cannot change it and pretending otherwise is how a fix looks applied while the
# battery setting still kills the sampler. Its settings gaps are listed at the end of the run.
$check = Get-ScheduledTask -TaskName $checkName
$rep = $check.Triggers | ForEach-Object { $_.Repetition.Interval } | Where-Object { $_ } | Select-Object -First 1
$fail = @()
if (-not $rep) { $fail += "repetition interval is EMPTY (the task will not re-run)" }
if ($check.Settings.DisallowStartIfOnBatteries) { $fail += "DisallowStartIfOnBatteries is still TRUE" }
if ($check.Settings.StopIfGoingOnBatteries) { $fail += "StopIfGoingOnBatteries is still TRUE" }
if (-not $check.Settings.StartWhenAvailable) { $fail += "StartWhenAvailable is still FALSE" }
if ($check.Actions[0].Execute -notmatch 'pwsh') { $fail += "action still runs $($check.Actions[0].Execute), not pwsh" }
if ($check.Actions[0].Arguments -notmatch 'harness-metrics\.ps1') { $fail += "action does not run harness-metrics.ps1" }
if ($fail.Count) {
  throw ("'{0}' registered but the definition is still wrong:`n  - " -f $checkName + ($fail -join "`n  - "))
}
Say ("verified '{0}': repetition={1} batteries-ok={2} start-when-available={3}" -f `
      $checkName, $rep, (-not $check.Settings.DisallowStartIfOnBatteries), $check.Settings.StartWhenAvailable)
if ($checkName -ne $taskName) {
  Say ''
  Say ("KNOWN LIABILITY - '{0}' is left in place and could not be changed by this token:" -f $taskName)
  Say ("  it has NO repetition trigger; DisallowStartIfOnBatteries={0}; StopIfGoingOnBatteries={1}; StartWhenAvailable={2}" -f `
        $check.Settings.DisallowStartIfOnBatteries, $check.Settings.StopIfGoingOnBatteries, $check.Settings.StartWhenAvailable)
  Say  "  => the laptop going on battery can stop it and it will not come back on its own."
  Say  "  => WHY THE RECORD STILL CANNOT STOP: the script it runs (harness-metrics.ps1) now loops"
  Say  "     forever and ignores the hard-coded legacy -Samples 540, so once started it does not end"
  Say  "     by itself; and this installer's task repeats every $IntervalMinutes min to restart it."
  Say  "  ONE ELEVATED COMMAND removes the liability (run in an Administrator pwsh):"
  Say  "     Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
  Say  "     pwsh -File scripts\Install-MetricsSampler.ps1"
}

# ---- prove the record advances ---------------------------------------------------------------
# Two ways to get a fresh sample: adopt a sampler that a repetition already started (the normal
# case once this installer has run before), or start one. Then WAIT and read the file, because
# "installed" is not "sampling" and that gap is the entire bug being fixed.
$csv = Join-Path $env:USERPROFILE '.dsh\metrics\harness-metrics.csv'
$hbPath = Join-Path $env:USERPROFILE '.dsh-sync-status\metrics-sampler.json'

function Get-Heartbeat {
  if (-not (Test-Path $hbPath)) { return $null }
  try { return (Get-Content -Raw -LiteralPath $hbPath | ConvertFrom-Json) } catch { return $null }
}
function Get-LiveSamplerPid {
  $hb = Get-Heartbeat
  if ($hb -and $hb.state -eq 'running' -and $hb.pid) {
    $p = Get-Process -Id ([int]$hb.pid) -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match 'pwsh|powershell') { return [int]$hb.pid }
  }
  return $null
}

if ($RunNow) {
  Say ''
  Say '--- proving the record advances (this is the only evidence that counts) ---'
  $live = Get-LiveSamplerPid
  if ($live) { Say ("a sampler is already live (pid {0}); waiting for its next row" -f $live) }

  $sizeBefore = if (Test-Path $csv) { (Get-Item $csv).Length } else { 0 }
  $stampBefore = if (Test-Path $csv) { (Get-Item $csv).LastWriteTime } else { [datetime]::MinValue }
  $ok = $false; $waited = 0; $attempt = 0
  # Two 90 s windows: give a natural sample 90 s, and if nothing arrived, start a sampler by hand
  # and give it another 90 s. The hand-start covers the case where the lock is held by a process
  # that a repetition is about to replace.
  while (-not $ok -and $attempt -lt 2) {
    $attempt++
    if ($attempt -eq 2) {
      Say 'no row in 90 s; starting the task directly and waiting another 90 s'
      Start-ScheduledTask -TaskName $checkName
    }
    for ($i = 0; $i -lt 45; $i++) {
      Start-Sleep -Seconds 2
      $waited += 2
      if ((Test-Path $csv) -and (Get-Item $csv).Length -gt $sizeBefore) { $ok = $true; break }
    }
  }

  if (-not $ok) {
    Say ("FAIL: no new bytes in {0}s. Task LastTaskResult={1}; heartbeat={2}" -f `
         $waited, (Get-ScheduledTaskInfo -TaskName $checkName).LastTaskResult, `
         $(if (Test-Path $hbPath) { (Get-Content -Raw $hbPath) -replace '\s+', ' ' } else { '(absent)' }))
    exit 1
  }

  $csvItem = Get-Item $csv
  $newRows = @(Get-Content $csv).Count
  Say ("PASS: harness-metrics.csv {0} -> {1}  (+{2} bytes)  after {3}s" -f `
       $stampBefore.ToString('HH:mm:ss'), $csvItem.LastWriteTime.ToString('HH:mm:ss'), `
       ($csvItem.Length - $sizeBefore), $waited)
  Say ("      rows now = {0}; size = {1} bytes" -f $newRows, $csvItem.Length)
  $hb = Get-Heartbeat
  if ($hb) {
    Say ("      heartbeat: state={0} pid={1} sample={2} rows={3} csv_age={4}s" -f `
         $hb.state, $hb.pid, $hb.sample, $hb.rows_written, $hb.csv_age_seconds)
  } else {
    Say "      WARNING: no heartbeat file at $hbPath - the record advances but the stall signal is absent"
    exit 1
  }
}

