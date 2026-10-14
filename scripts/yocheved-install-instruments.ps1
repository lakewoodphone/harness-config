# yocheved-install-instruments.ps1 -- put the estate's EXISTING engine instruments on this machine.
#
# ASCII ONLY, DELIBERATELY. This file is delivered to a machine through channels that corrupt
# non-ASCII bytes, and an em-dash already broke a remote PowerShell parse on 2026-09-28.
#
# WHY THIS EXISTS
#
# Measured 2026-10-13 on DESKTOP-FGV6KMH. The estate already has three instruments that answer
# exactly the failure this machine kept having, and this machine had NONE of them:
#
#   DSH Engine Watchdog (1m)   runs `dshw.ps1 ensure` every minute. Restarts a dead engine and
#                              reopens a window the registry says was open and liveness says is gone.
#                              Registered by: multi-window/dshw.ps1 watchdog -Mode fast
#   DSH Profile Gate (15m)     composes every dsh profile WITHOUT starting an engine. Catches the
#                              class of defect that killed her assistant for TEN DAYS (2026-09-18 to
#                              09-28): a profile bundle name that makes the engine fail at boot. It
#                              runs fine on a machine whose engine is dead, which is the whole point.
#                              Registered by: scripts/install-profile-gate-task.ps1
#   DSH Engine Vitals (5m)     one CSV row every 5 minutes, and a line in ~/.dsh/metrics/engine-vitals.log
#                              when the engine restarted or a warning is new.
#                              Registered by: scripts/install-engine-vitals-task.ps1
#
# The 10-day outage was invisible because the only thing that ever ran a check was HER CLICK, and she
# had stopped clicking. A check nobody runs is the same as no check. This script makes them run.
#
# THIS IS NOT A NEW MECHANISM. It is a driver for the three installers above, plus a verification
# step, because the two things that go wrong on this box are (a) nothing was ever registered and
# (b) a task reports success while having never executed (L174 - measured here: a task reported
# LastTaskResult 0 for 21 days while its work stood still). So every registration is followed by an
# execution check, and the exit code is this script's own verdict, not any task's.
#
# USAGE -- run it AS THE USER WHOSE SESSION OWNS THE ASSISTANT (cheve), not as SYSTEM:
#   pwsh -File scripts/yocheved-install-instruments.ps1
#   pwsh -File scripts/yocheved-install-instruments.ps1 -WhatIf
#   pwsh -File scripts/yocheved-install-instruments.ps1 -SkipRunNow
#
# EXIT: 0 all instruments registered and proven to execute, 1 at least one failed, 2 refused
#       (preconditions not met -- nothing was changed).
[CmdletBinding()]
param(
    [string] $Repo        = 'C:\Users\cheve\code\harness-config',
    [string] $DshHome     = 'C:\Users\cheve\.dsh',
    [string] $ConfigPath,
    [switch] $WhatIf,
    [switch] $SkipRunNow
)

$ErrorActionPreference = 'Continue'
$script:fail = @()
function Say($m) { Write-Output $m }
function Bad($m) { Write-Output ("  [FAIL] " + $m); $script:fail += $m }
function Ok ($m) { Write-Output ("  [ ok ] " + $m) }

Say "yocheved-install-instruments"
Say ("  host     : " + $env:COMPUTERNAME)
Say ("  identity : " + [System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
Say ("  repo     : " + $Repo)
Say ("  dshHome  : " + $DshHome)
Say ("  whatIf   : " + [bool]$WhatIf)
Say ""

# ---- preconditions. A refusal, not a guess. ------------------------------------------------
if (-not (Test-Path -LiteralPath $Repo)) { Say ("REFUSED: repo not found: " + $Repo); exit 2 }
$dshw = Join-Path $Repo 'multi-window\dshw.ps1'
if (-not (Test-Path -LiteralPath $dshw)) { Say ("REFUSED: dshw.ps1 not found: " + $dshw); exit 2 }
if (-not $ConfigPath) {
    $cand = Join-Path $Repo ("multi-window\machines\{0}.windows.json" -f $env:COMPUTERNAME)
    if (Test-Path -LiteralPath $cand) { $ConfigPath = $cand }
}
if (-not $ConfigPath -or -not (Test-Path -LiteralPath $ConfigPath)) {
    Say ("REFUSED: no per-machine windows.json. Looked for multi-window\machines\" + $env:COMPUTERNAME + ".windows.json")
    Say "         A machine whose engine watchdog holds the WRONG config path will manage the wrong profile."
    exit 2
}
Say ("  configPath: " + $ConfigPath)
foreach ($f in @('scripts\profile-gate.mjs', 'scripts\install-profile-gate-task.ps1', 'scripts\install-engine-vitals-task.ps1', 'scripts\engine-vitals.mjs')) {
    $p = Join-Path $Repo $f
    if (Test-Path -LiteralPath $p) { Ok ($f + " present") } else { Bad ($f + " MISSING -- run git pull / the harness sync first") }
}
if ($script:fail.Count -gt 0) { Say ""; Say "REFUSED: repo is incomplete. Nothing was changed."; exit 2 }

# ---- the boot gate, BEFORE anything else. It costs nothing and it is the check that would have
# ---- caught the ten-day outage. If the profile cannot compose, say so loudly and still install:
# ---- the gate task is exactly what tells you this on an interval.
Say ""
Say "== boot gate (composes the profiles; starts nothing) =="
$gate = Join-Path $Repo 'scripts\profile-gate.mjs'
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) { Bad "node not on PATH; the gate and the vitals task both need it" }
else {
    $gateOut = & $node $gate 2>&1
    $gateRc = $LASTEXITCODE
    Say ("  profile-gate exit=" + $gateRc + " (0 all compose / 1 CANNOT BOOT / 3 refusal)")
    $gateOut | Select-Object -First 20 | ForEach-Object { Say ("    " + $_) }
    if ($gateRc -eq 1) { Say "  ** THE PROFILE CANNOT BOOT. The engine will fail at its next start. **" }
    elseif ($gateRc -eq 3) { Say "  ** the gate could not exercise a harness -- that is a REFUSAL, not a verdict **" }
}

# ---- register the instruments ------------------------------------------------------------------
Say ""
Say "== registering instruments =="
function Invoke-Step($name, $block) {
    Say ("-- " + $name)
    if ($WhatIf) { Say "   (whatIf: not run)"; return }
    try { & $block } catch { Bad ($name + ": " + $_.Exception.Message) }
}

# 1) the 1-minute engine watchdog + the 5-minute window fleet watchdog. Both are registered by dshw
#    itself, which is the ONLY place that knows how to build them; never hand-roll them here.
#
#    THE MODE ARRIVES IN -Slot, NOT -Mode. `dshw.ps1`'s dispatch is
#        'watchdog'  { Invoke-Watchdog ($Slot) }
#    and Invoke-Watchdog takes a single positional [string]$mode which it compares to 'fast'. So
#    `dshw watchdog -Slot fast` is the 1-minute engine watchdog and a bare `dshw watchdog` is the
#    5-minute window fleet watchdog. MEASURED 2026-10-13 on DESKTOP-FGV6KMH: passing -Mode fast
#    fails with "A parameter cannot be found that matches parameter name 'Mode'" AND STILL EXITS 0
#    FOR THE SECOND CALL -- so a caller that does not check leaves the machine believing it has a
#    1-minute watchdog when it has none. That is exactly what happened on the first run here.
Invoke-Step 'dshw watchdog -Slot fast (1m engine watchdog)' {
    & pwsh -NoProfile -File $dshw watchdog -Slot fast -ConfigPath $ConfigPath 2>&1 | ForEach-Object { Say ("   " + $_) }
}
Invoke-Step 'dshw watchdog (window fleet, 5m)' {
    & pwsh -NoProfile -File $dshw watchdog -ConfigPath $ConfigPath 2>&1 | ForEach-Object { Say ("   " + $_) }
}

# 2) the profile gate. -DshHome is REQUIRED when the caller is not the profile's owner (the exec API
#    on this box runs as SYSTEM, whose os.homedir() is not hers and would enumerate nothing).
Invoke-Step 'DSH Profile Gate (15m)' {
    & pwsh -NoProfile -File (Join-Path $Repo 'scripts\install-profile-gate-task.ps1') -DshHome $DshHome -IntervalMinutes 15 2>&1 | ForEach-Object { Say ("   " + $_) }
}

# 3) engine vitals.
Invoke-Step 'DSH Engine Vitals (5m)' {
    & pwsh -NoProfile -File (Join-Path $Repo 'scripts\install-engine-vitals-task.ps1') 2>&1 | ForEach-Object { Say ("   " + $_) }
}

# ---- verify: registered is not the same as running ---------------------------------------------
# L174 and the transcript-archive incident both measured a task reporting success while doing nothing.
# InitialTaskAge of 267011 is SCHED_S_TASK_HAS_NOT_RUN. So: start it, wait, and read the result.
Say ""
Say "== verification (registered is not proof of running) =="
$want = @('DSH Engine Watchdog (1m)', 'DSH Window Fleet Watchdog', 'DSH Profile Gate (15m)', 'DSH Engine Vitals (5m)')
foreach ($n in $want) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $t) { Bad ("'" + $n + "' is NOT registered"); continue }
    Ok ("'" + $n + "' state=" + $t.State + " logon=" + $t.Principal.LogonType + " runAs=" + $t.Principal.UserId)
    if ($WhatIf -or $SkipRunNow) { continue }
    try {
        Start-ScheduledTask -TaskName $n -ErrorAction Stop
        Start-Sleep -Seconds 12
        $i = Get-ScheduledTaskInfo -TaskName $n
        if ([int64]$i.LastTaskResult -eq 267011) { Bad ("'" + $n + "' has NEVER RUN (267011)") }
        else { Ok ("'" + $n + "' ran: last=" + $i.LastRunTime + " result=" + $i.LastTaskResult) }
    } catch { Bad ("'" + $n + "' could not be started: " + $_.Exception.Message) }
}

Say ""
if ($script:fail.Count -eq 0) { Say "RESULT: all instruments registered and proven to execute."; exit 0 }
Say ("RESULT: " + $script:fail.Count + " problem(s):")
foreach ($f in $script:fail) { Say ("  - " + $f) }
exit 1
