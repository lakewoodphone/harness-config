# switch-engine.ps1 — THE SWITCH.
#
# WHY THIS EXISTS, AND WHY IT IS ONE COMMAND AND NOT TWO
# =====================================================
# This deployment is moving from the 0.1.5 line to 0.1.7-rc.2, and part of that move is
# VERSION-COUPLED config. `@deepseek-ai/dsh-workflow-ptc`, `@deepseek-ai/dsh-agent-preset-registry`
# and `@deepseek-ai/dsh-agent-preset` exist ONLY on the 0.1.7 line;
# `@deepseek-ai/dsh-workflow-worker-thread` and `@deepseek-ai/dsh-agent-presets` exist ONLY on the
# 0.1.5 line. A composition row that names a package the RUNNING engine does not provide FAILS AT
# MOUNT: in a preset that breaks NEW SESSION CREATION, and in the mesh profile it can take the boot
# down. Existing sessions keep working, so the damage appears only the next time somebody starts a
# chat — the last place anyone would look.
#
# So neither half can be applied alone:
#   * the config alone, onto a running 0.1.5 engine — new sessions break NOW;
#   * the engine alone, with 0.1.5-shaped config   — new sessions break at the NEXT BOOT.
# This script is the single operation that changes both, in the safe order, with a tested way back.
#
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# WHY THIS FILE WAS REWRITTEN (2026-09-28, after a live incident at 15:32:08)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# The previous version was run against fixtures three times. During those runs it transiently set
# `dshInstall`, and at 15:32:08 — the same second the 15-minute `PersonalSecretary-HarnessSync` tick
# fired — the LIVE `~/.dsh` config was rewritten to the 0.1.7 package names while the OLD engine was
# still running. `dshInstall` was NOT set afterwards and `state/pin.json` still said 0.1.5-rc.1.
# Existing sessions were unaffected; the three presets would have failed to mount a row for any NEW
# session. It was restored by hand. Two defects in this script caused it, and both are fixed here:
#
#   DEFECT 1 — THE ROLL-BACK REVERTED THE ENGINE AND LEFT THE CONFIG BEHIND.
#     It recorded every config file (sha256 + a copy under `state\switch-<stamp>\config\...`, listed
#     in PRE-STATE.json's `recordedConfigFiles`) and then, on failure, restored only `pin.json` and
#     `windows.json` and re-ran sync.py. sync.py then correctly SKIPPED the version-coupled steps
#     (the old engine was back), so NOTHING ever reverted the config files the apply had written.
#     A roll-back that reverts only the engine is not a roll-back.
#     FIX 1: `Restore-FromRecord` restores pin.json, windows.json AND every entry in
#     `recordedConfigFiles` from its recorded copy, RE-HASHES each one against the recorded sha256,
#     treats any mismatch as a HARD FAILURE, re-checks the restored coupled names against the
#     pre-state, and MOVES ASIDE (never deletes) anything it overwrote that was not in the pre-state.
#
#   DEFECT 2 — NO DEFENCE AGAINST THE 15-MINUTE SYNC TIMER.
#     Task `PersonalSecretary-HarnessSync` runs `scripts/autosync.ps1`, which applies the repo's
#     committed config through `scripts/sync.py`. A switch that sets `dshInstall` even briefly opens
#     a window in which a concurrent sync believes the candidate engine is the running one and
#     installs version-coupled config onto a host still running the old engine.
#     FIX 2: `Test-SyncWindow` REFUSES (exit 2, nothing written) when a tick is due within
#     -SafetyMarginSeconds (default 180 s), and a switch-held LOCK FILE prevents two switches from
#     interleaving. After the writes the task info is read AGAIN, and a tick that ran mid-sequence
#     is reported plainly — not silently accepted. The guard's own hardening is separate work; this
#     script does not depend on it (defence in depth).
#
# AND THE GATE THE INCIDENT ASKED FOR. The old script's brief said "do not touch the live home" and
# the script had no mechanism that enforced it. A brief is not a mechanism. So the live home is now
# a NAMED, UNLOCKED TARGET: without `-IUnderstandThisWritesTheLiveHome` this script does every check,
# prints exactly what it would have written, and writes NOTHING — no pre-state directory, no lock,
# no pin, no launcher config, no live config file.
#
# WHAT IT NEVER DOES
# ------------------
# A live DSH engine serves the session that runs this script. So this script NEVER starts, stops or
# restarts an engine, never runs `dsh web`, and never touches the `DSH Engine Watchdog` task or
# `multi-window\dshw.ps1 up`/`down`. It never triggers `PersonalSecretary-HarnessSync`; it only
# READS that task's schedule. `promote` and rollback write state; the change lands at the NEXT boot,
# and step 4 proves by pid AND start time that nothing restarted.
# It never deletes anything. Quarantine is a MOVE.
#
# USAGE
#   pwsh -File tools/switch-engine.ps1 -Version <ver> -StagedHome <dir> -BackupDir <dir>
#                                      [-AcceptSessionFormatUpgrade] [-DryRun] [-Rollback]
#                                      [-IUnderstandThisWritesTheLiveHome]
#
#   WITHOUT -IUnderstandThisWritesTheLiveHome the script is a DRESS REHEARSAL for anything it would
#   do to the live home: it runs every check and prints the exact files and commands. -DryRun is the
#   strictly stronger promise (it writes nothing ANYWHERE, including under state\).
#
# EXIT CODES
#   0  the switch is applied (or -DryRun / -Rollback completed)
#   1  an unexpected internal error
#   2  a precondition refused, or the live-write gate was not unlocked — NOTHING was written,
#      not even the pre-state directory or a lock file
#   3  -Rollback could not proceed (no pre-state, or a restore failed to verify)
#   4  a step failed and the automatic roll-back RESTORED the previous state, verified by sha256
#   5  a step failed AND the automatic roll-back could not fully restore — attention required
#
# TEST-ONLY OVERRIDES AND INJECTION POINTS. These exist so the WRITE path can be proven against
# copies instead of the live deployment, and so the guards can be exercised without waiting on real
# clocks or a real task. Every one of them is printed loudly when it is in force.
#   DSH_UPDATE_WINDOWS_JSON / -WindowsJson   launcher config to read/write instead of the repo's
#   DSH_SWITCH_TARGET_HOME   / -TargetHome   DSH home whose config is installed, instead of ~\.dsh
#   -StateRoot                               this script's own state dir (pin.json, switch-*), instead
#                                            of dsh-update\state. A CONTAINMENT override: on a real
#                                            switch it must stay the default.
#   -InjectNextRunInSeconds                  fake the sync task's NextRunTime as now + N seconds
#   -InjectLastRunAt                         fake the sync task's LastRunTime (ISO 8601)
#   -InjectLastRunAfter                      fake LastRunTime to this ISO value AFTER the writes, i.e.
#                                            simulate a sync tick that landed mid-sequence
#   -InjectEngineJson                        fake the live-engine identity (pid/startedAt/version/...)
#   -InjectSyncOut                           use this file's text as sync.py's stdout instead of
#                                            running sync.py
#   -InjectPromoteScript                     run this .ps1 instead of bin\dsh-update.ps1 promote
#   -TestHookAfterWrite                      run this .ps1 AFTER the writes and BEFORE verification,
#                                            to force the mid-sequence failure the roll-back must undo
#   DSH_SWITCH_ENGINE_LOCK_STALE_SECONDS     age at which a foreign lock is treated as stale

[CmdletBinding()]
param(
  [string]$Version,
  [string]$StagedHome,
  [string]$BackupDir,
  [switch]$AcceptSessionFormatUpgrade,
  [switch]$DryRun,
  [switch]$Rollback,
  [switch]$IUnderstandThisWritesTheLiveHome,

  # containment (tests only — the defaults are the deployment)
  [string]$StateRoot,
  [string]$TargetHome,
  [string]$WindowsJson,

  # injection (tests only)
  [int]$InjectNextRunInSeconds = -2147483648,
  [string]$InjectLastRunAt,
  [string]$InjectLastRunAfter,
  [string]$InjectEngineJson,
  [string]$InjectSyncOut,
  [string]$InjectPromoteScript,
  [string]$TestHookAfterWrite,
  [ValidateSet('', 'GO', 'G8ACCEPTED', 'NOGO')][string]$InjectPreflightVerdict = '',
  [string]$InjectVerification = '',

  # policy
  [int]$SafetyMarginSeconds = 180,
  [int]$LockStaleSeconds = 300
)

$ErrorActionPreference = 'Continue'
$script:LockPath = $null    # the switch lock actually held right now, if any (released by Refuse too)

# ── fixed locations ──────────────────────────────────────────────────────────────────────────────
$ToolsDir   = $PSScriptRoot
$UpdRoot    = Split-Path -Parent $ToolsDir
$RepoRoot   = Split-Path -Parent $UpdRoot
$EntryPoint = Join-Path $UpdRoot 'bin\dsh-update.ps1'
$SyncPy     = Join-Path $RepoRoot 'scripts\sync.py'
$LiveHome   = Join-Path $env:USERPROFILE '.dsh'
$SyncTaskName = 'PersonalSecretary-HarnessSync'

if (-not $StateRoot) { $StateRoot = Join-Path $UpdRoot 'state' }
if ($env:DSH_SWITCH_ENGINE_LOCK_STALE_SECONDS -and -not $PSBoundParameters.ContainsKey('LockStaleSeconds')) {
  $envStale = 0
  $envOk = $false
  try { $envOk = [int]::TryParse($env:DSH_SWITCH_ENGINE_LOCK_STALE_SECONDS, [ref]$envStale) } catch { $envOk = $false }
  if ($envOk -and $envStale -gt 0) { $LockStaleSeconds = $envStale }
}

if (-not $WindowsJson) {
  $WindowsJson = if ($env:DSH_UPDATE_WINDOWS_JSON) { $env:DSH_UPDATE_WINDOWS_JSON }
                 else { Join-Path $RepoRoot 'multi-window\windows.json' }
}
if (-not $TargetHome) {
  $TargetHome = if ($env:DSH_SWITCH_TARGET_HOME) { $env:DSH_SWITCH_TARGET_HOME } else { $LiveHome }
}
$TargetIsLive   = ([System.IO.Path]::GetFullPath($TargetHome).TrimEnd('\') -ieq
                   [System.IO.Path]::GetFullPath($LiveHome).TrimEnd('\'))
$LauncherIsReal = ([System.IO.Path]::GetFullPath($WindowsJson).TrimEnd('\') -ieq
                   [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'multi-window\windows.json')).TrimEnd('\'))
$StateIsReal    = ([System.IO.Path]::GetFullPath($StateRoot).TrimEnd('\') -ieq
                   [System.IO.Path]::GetFullPath((Join-Path $UpdRoot 'state')).TrimEnd('\'))
$PinPath        = Join-Path $StateRoot 'pin.json'

# Name patterns. A QUOTED occurrence is a composition row; an unquoted one is prose in a comment.
# (Measured 2026-09-28: `cordis-bg/agent.cordis.yml` mentions the removed package name in a comment
# explaining the rename, and matching that would refuse a correct file.)
$Q       = '["'']'
$NEW_PTC = "$Q@deepseek-ai/dsh-workflow-ptc$Q"
$OLD_PTC = "$Q@deepseek-ai/dsh-workflow-worker-thread$Q"
$NEW_REG = "$Q@deepseek-ai/dsh-agent-preset-registry$Q"
$OLD_REG = "$Q@deepseek-ai/dsh-agent-presets$Q"
$G8_GUARD  = 'G8 session-format door'
$VER_GUARD = 'verify (gates G1-G8)'

# ── output helpers ───────────────────────────────────────────────────────────────────────────────
function Say  { param([string]$m = '') Write-Host $m }
function Head { param([string]$m) Write-Host ''; Write-Host "-- $m" }
function Warn { param([string]$m) Write-Host "  !   $m" }
function Ok   { param([string]$m) Write-Host "  ok  $m" }
function Bad  { param([string]$m) Write-Host "  NO  $m" }

function Refuse {
  param([string]$Why)
  Say ''
  Say "switch-engine: REFUSED — $Why"
  Say '               NOTHING WAS WRITTEN. No pre-state directory, no pin, no launcher config, no live'
  Say '               config file, and no engine was touched.'
  # If the lock was taken for the plan before the refusal (the sync window is checked FIRST, so the
  # lock exists from precondition 3 onward), it must not be left behind. A leaked lock would make every
  # later switch wait for it to go stale.
  if ($script:LockPath) {
    if (Get-Command Exit-SwitchLock -ErrorAction SilentlyContinue) { Exit-SwitchLock -LockPath $script:LockPath }
    $script:LockPath = $null
    Say '               The lock this run took for the plan was released.'
  }
  exit 2
}

function Stop-Hard {
  param([string]$Why, [int]$Code = 1)
  Say ''
  Say "switch-engine: STOPPED — $Why"
  exit $Code
}

# ── where this run may write ─────────────────────────────────────────────────────────────────────
# The live home is a NAMED target that needs a NAMED unlock. Everything else (a fixture home, a
# fixture launcher config, a fixture state root) is containment and is announced, not gated.
function Test-LiveWritesUnlocked {
  if ($TargetIsLive -or $LauncherIsReal -or $StateIsReal) { return [bool]$IUnderstandThisWritesTheLiveHome }
  return $true
}

function Get-GateRefusal {
  if ($IUnderstandThisWritesTheLiveHome) { return $null }
  $what = New-Object System.Collections.Generic.List[string]
  if ($TargetIsLive)   { $what.Add("the LIVE DSH home  $TargetHome") }
  if ($LauncherIsReal) { $what.Add("the LIVE launcher config  $WindowsJson") }
  if ($StateIsReal)    { $what.Add("the LIVE state root  $StateRoot   (pin.json, switch-<stamp>\)") }
  $list = ($what -join "`n               and ")
  return "-IUnderstandThisWritesTheLiveHome was NOT given, and this switch would write $list.`n               This is the gate that the 2026-09-28 incident asked for: the old script's brief said `"do not`n               touch the live home`" and had no mechanism that enforced it.`n               Run with -DryRun to see the whole sequence and write nothing at all, or with`n               -IUnderstandThisWritesTheLiveHome to actually perform it."
}

function Show-Containment {
  if (-not $TargetIsLive)   { Warn "TARGET HOME IS NOT THE LIVE HOME: $TargetHome   (containment override in force)" }
  if (-not $LauncherIsReal) { Warn "LAUNCHER CONFIG IS NOT THE REPO'S: $WindowsJson   (containment override in force)" }
  if (-not $StateIsReal)    { Warn "STATE ROOT IS NOT THE DEPLOYMENT'S: $StateRoot   (containment override in force)" }
}

# ── small utilities ──────────────────────────────────────────────────────────────────────────────
function Get-Sha {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
}

function Read-Json {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try { return (Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json) }
  catch { return $null }
}

function Write-Json {
  param([string]$Path, $Object)
  $Object | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Get-RelPosix {
  param([string]$Root, [string]$Path)
  return ([System.IO.Path]::GetRelativePath($Root, $Path) -replace '\\', '/')
}

function Count-Pattern {
  param([string]$Path, [string]$Pattern)
  $t = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
  if (-not $t) { return 0 }
  return ([regex]::Matches($t, $Pattern)).Count
}

function Get-IsoNow { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ') }

function Get-DtOrNull {
  param([string]$Text)
  if (-not $Text) { return $null }
  $d = [datetime]::MinValue
  $ok = [datetime]::TryParse([string]$Text, [cultureinfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor
        [System.Globalization.DateTimeStyles]::AssumeUniversal, [ref]$d)
  if ($ok) { return $d.ToUniversalTime() }
  return $null
}

# The live config files this switch can change. Enumerated BY NAME, never by a recursive walk:
# `profiles/node_modules` is a full engine tree and is deliberately not entered.
function Get-RecordedConfigFiles {
  param([string]$DshHome)
  $out = New-Object System.Collections.Generic.List[string]
  $presets = Join-Path $DshHome '.agent-presets'
  if (Test-Path -LiteralPath $presets) {
    foreach ($d in @(Get-ChildItem -LiteralPath $presets -Directory -ErrorAction SilentlyContinue)) {
      $f = Join-Path $d.FullName 'agent.cordis.yml'
      if (Test-Path -LiteralPath $f) { [void]$out.Add($f) }
    }
  }
  $profiles = Join-Path $DshHome 'profiles'
  if (Test-Path -LiteralPath $profiles) {
    foreach ($d in @(Get-ChildItem -LiteralPath $profiles -Directory -ErrorAction SilentlyContinue)) {
      $f = Join-Path $d.FullName 'cordis.patch.yml'
      if (Test-Path -LiteralPath $f) { [void]$out.Add($f) }
    }
  }
  $settings = Join-Path $DshHome 'settings.yaml'
  if (Test-Path -LiteralPath $settings) { [void]$out.Add($settings) }
  return @($out | Sort-Object -Unique)
}

# Every file under <home>\sessions right now: relative path + bytes. This list is what lets the
# roll-back identify EXACTLY which `session.v4.jsonl.zstd` siblings APPEARED after the switch.
function Get-SessionFileList {
  param([string]$DshHome)
  $root = Join-Path $DshHome 'sessions'
  if (-not (Test-Path -LiteralPath $root)) { return @() }
  $rows = New-Object System.Collections.Generic.List[object]
  foreach ($f in @(Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue)) {
    $rows.Add([pscustomobject]@{ rel = (Get-RelPosix -Root $root -Path $f.FullName); bytes = $f.Length })
  }
  return @($rows | Sort-Object rel)
}

function Read-SessionList {
  param([string]$ListPath)
  $set = @{}
  if (-not (Test-Path -LiteralPath $ListPath)) { return $null }
  foreach ($line in @(Get-Content -LiteralPath $ListPath)) {
    $line = $line -replace "^\uFEFF", ''
    if ($line -match '^relpath\s') { continue }
    $parts = $line -split "`t"
    if ($parts.Count -gt 0 -and $parts[0]) { $set[$parts[0]] = $true }
  }
  return $set
}

function Invoke-Captured {
  param(
    [string]$Exe,
    [string[]]$Arguments,
    [string]$OutFile,
    [string]$ErrFile,
    [hashtable]$SetEnv = @{}
  )
  $saved = @{}
  foreach ($k in $SetEnv.Keys) {
    $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process')
    [Environment]::SetEnvironmentVariable($k, [string]$SetEnv[$k], 'Process')
  }
  $code = $null
  try {
    & $Exe @Arguments 1> $OutFile 2> $ErrFile
    $code = $LASTEXITCODE
  } finally {
    foreach ($k in $SetEnv.Keys) {
      [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process')
    }
  }
  if ($null -eq $code) { $code = 0 }
  return [int]$code
}

function Get-Tail {
  param([string]$Path, [int]$Lines = 25)
  if (-not (Test-Path -LiteralPath $Path)) { return '(no output file)' }
  $t = @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -Last $Lines)
  if ($t.Count -eq 0) { return '(empty)' }
  return ($t -join "`n")
}

# ── the live engine ──────────────────────────────────────────────────────────────────────────────
#
# The engine that serves the session running this script: whatever owns the launcher's `primaryPort`.
# Its version is read from the `@deepseek-ai/dsh` package.json of the install root its OWN command
# line names — that is what that process is actually running, not what any config claims.
function Get-LiveEngine {
  if ($InjectEngineJson) {
    $j = Read-Json $InjectEngineJson
    if (-not $j) { return [pscustomobject]@{ ok = $false; reason = "the injected engine record $InjectEngineJson is absent or unparseable" } }
    return [pscustomobject]@{ ok = $true; port = [int]$j.port; pid = [int]$j.pid; startedAt = [string]$j.startedAt
      installRoot = [string]$j.installRoot; version = [string]$j.version; cmd = "$($j.cmd)   [INJECTED ENGINE RECORD: -InjectEngineJson]"; injected = $true }
  }

  $port = 3099
  $portSource = 'the built-in default 3099'
  $lc = Read-Json $WindowsJson
  if ($lc -and $lc.primaryPort) { $port = [int]$lc.primaryPort; $portSource = "primaryPort in $WindowsJson" }

  $listen = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
  if ($listen.Count -eq 0) {
    return [pscustomobject]@{ ok = $false; port = $port
      reason = "nothing is listening on port $port ($portSource), so no engine is serving this session" }
  }
  $owningPid = [int]$listen[0].OwningProcess
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$owningPid" -ErrorAction SilentlyContinue
  if (-not $proc) {
    return [pscustomobject]@{ ok = $false; port = $port
      reason = "port $port is owned by pid $owningPid but that process could not be read" }
  }
  $cmd = [string]$proc.CommandLine

  $binToken = $null
  foreach ($m in [regex]::Matches($cmd, '"[^"]*"|\S+')) {
    $tok = $m.Value.Trim('"')
    if ($tok -match '@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js$') { $binToken = $tok; break }
  }
  if (-not $binToken) {
    return [pscustomobject]@{ ok = $false; port = $port
      reason = "pid $owningPid owns port $port but its command line is not a DSH engine: $cmd" }
  }
  if ($cmd -notmatch '(^|\s)web(\s|$)') {
    return [pscustomobject]@{ ok = $false; port = $port
      reason = "pid $owningPid owns port $port and runs DSH, but not the web profile: $cmd" }
  }
  $installRoot = $binToken -replace '[\\/]node_modules[\\/]@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js$', ''
  $pkg = Join-Path $installRoot 'node_modules\@deepseek-ai\dsh\package.json'
  $version = $null
  if (Test-Path -LiteralPath $pkg) { $version = (Read-Json $pkg).version }
  if (-not $version) {
    return [pscustomobject]@{ ok = $false; port = $port
      reason = "the engine on port $port (pid $owningPid) points at $installRoot, but $pkg is absent or carries no version" }
  }
  return [pscustomobject]@{
    ok = $true; port = $port; pid = $owningPid; startedAt = ([string]$proc.CreationDate)
    installRoot = $installRoot; version = [string]$version; cmd = $cmd
  }
}

function Test-LiveEngineUnchanged {
  param($Before)
  $now = Get-LiveEngine
  if (-not $now.ok) {
    return [pscustomobject]@{ unchanged = $false; detail = "the engine can no longer be read: $($now.reason)" }
  }
  if ($now.pid -ne $Before.pid) {
    return [pscustomobject]@{ unchanged = $false
      detail = "the pid on port $($Before.port) CHANGED: was $($Before.pid), now $($now.pid)" }
  }
  if ([string]$now.startedAt -ne [string]$Before.startedAt) {
    return [pscustomobject]@{ unchanged = $false
      detail = "pid $($Before.pid) is the same but its start time CHANGED: was $($Before.startedAt), now $($now.startedAt)" }
  }
  return [pscustomobject]@{ unchanged = $true
    detail = "pid $($now.pid), started $($now.startedAt), still serving port $($Before.port)" }
}

# ── FIX 2 — the 15-minute sync window, and the switch lock ───────────────────────────────────────
#
# The task runs every 15 minutes. A switch needs the window to itself. WHY 180 SECONDS: the tick can
# land at any instant inside that window; the switch's own longest tail (preflight + promote + sync,
# measured 20-40 s on this host) plus task-scheduler latency and this file's own second reading of
# the task info all fit inside three minutes, and 180 s is 20 % of the interval — enough that the
# guard fires only when a tick really is close, rather than refusing most of the day.
function Get-SyncTaskState {
  $now = (Get-Date).ToUniversalTime()
  if ($InjectNextRunInSeconds -ne -2147483648) {
    return [pscustomobject]@{
      readable = $true; injected = $true; taskName = $SyncTaskName
      lastRunTime = (Get-DtOrNull $InjectLastRunAt); nextRunTime = $now.AddSeconds($InjectNextRunInSeconds)
      lastTaskResult = $null
      note = "INJECTED SCHEDULE: -InjectNextRunInSeconds $InjectNextRunInSeconds" +
             $(if ($InjectLastRunAt) { ", -InjectLastRunAt $InjectLastRunAt" } else { '' }) }
  }
  $info = $null
  try { $info = Get-ScheduledTaskInfo -TaskName $SyncTaskName -ErrorAction Stop } catch { $info = $null }
  if (-not $info) {
    return [pscustomobject]@{ readable = $false; injected = $false; taskName = $SyncTaskName
      lastRunTime = $null; nextRunTime = $null; lastTaskResult = $null
      note = "Get-ScheduledTaskInfo could not read the task '$SyncTaskName'" }
  }
  return [pscustomobject]@{
    readable = $true; injected = $false; taskName = $SyncTaskName
    lastRunTime = $info.LastRunTime; nextRunTime = $info.NextRunTime
    lastTaskResult = $info.LastTaskResult; note = '' }
}

function Show-SyncTaskState {
  param($S)
  if (-not $S.readable) { Warn $S.note; return }
  Say "  task        : $($S.taskName)$(if ($S.injected) { '   [INJECTED: the real task was not queried]' })"
  Say "  LastRunTime : $(if ($S.lastRunTime) { ([datetime]$S.lastRunTime).ToUniversalTime().ToString('o') } else { '(none)' })"
  Say "  NextRunTime : $(if ($S.nextRunTime) { ([datetime]$S.nextRunTime).ToUniversalTime().ToString('o') } else { '(none)' })"
  if ($S.lastTaskResult -ne $null) { Say "  LastResult  : $($S.lastTaskResult)" }
}

function Test-SyncWindow {
  param($S)
  if (-not $S.readable) {
    return [pscustomobject]@{ ok = $false; why = "the sync task's schedule cannot be read ($($S.note)), and a window that cannot be measured cannot be claimed" }
  }
  if (-not $S.nextRunTime) {
    return [pscustomobject]@{ ok = $false; why = "the sync task reports no NextRunTime, so the next tick is unknown" }
  }
  $next = ([datetime]$S.nextRunTime).ToUniversalTime()
  $secs = ($next - (Get-Date).ToUniversalTime()).TotalSeconds
  if ($secs -lt (-1 * $SafetyMarginSeconds)) {
    return [pscustomobject]@{ ok = $false; seconds = $secs
      why = ("the sync task's NextRunTime is {0:N0} s in the PAST ({1:o}); a stale schedule is not evidence that a tick is far away" -f $secs, $next) }
  }
  if ($secs -lt $SafetyMarginSeconds) {
    return [pscustomobject]@{ ok = $false; seconds = $secs
      why = ("a sync tick is due at {0:o}, {1:N0} s from now, inside the {2} s safety margin — a concurrent sync could see the new dshInstall and install version-coupled config onto a host still running the old engine" -f $next, $secs, $SafetyMarginSeconds) }
  }
  return [pscustomobject]@{ ok = $true; seconds = $secs; next = $next }
}

function Get-LockPath { return (Join-Path (Join-Path $StateRoot 'locks') 'switch-engine.lock.json') }

function Enter-SwitchLock {
  param([string]$PreDirPlanned)
  $lockDir = Join-Path $StateRoot 'locks'
  [void](New-Item -ItemType Directory -Path $lockDir -Force)
  $lockPath = Get-LockPath
  if (Test-Path -LiteralPath $lockPath) {
    $held = Read-Json $lockPath
    $ageSeconds = $null
    if ($held -and $held.startedAt) {
      $d = Get-DtOrNull ([string]$held.startedAt)
      if ($d) { $ageSeconds = ((Get-Date).ToUniversalTime() - $d).TotalSeconds }
    }
    $stale = ($ageSeconds -ne $null -and $ageSeconds -gt $LockStaleSeconds)
    if (-not $stale) {
      Say ''
      Say "switch-engine: REFUSED — another switch holds the lock: $lockPath"
      Say "               held by pid $($held.pid) on $($held.host)$(if ($held.startedAt) { ", started $($held.startedAt)" })"
      Say "               running: $($held.command)"
      Say "               Two switches must not interleave. Nothing was written by THIS run."
      Say "               If that run is gone, the lock goes stale after $LockStaleSeconds s"
      Say '               (DSH_SWITCH_ENGINE_LOCK_STALE_SECONDS), after which this run is allowed to take it.'
      exit 2
    }
    $moved = "$lockPath.stale-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
    Move-Item -LiteralPath $lockPath -Destination $moved
    Warn "a stale lock (age $(if ($ageSeconds -ne $null) { "{0:N0} s" -f $ageSeconds } else { 'unknown' }), pid $($held.pid)) was MOVED ASIDE, not deleted: $moved"
  }
  $rec = [ordered]@{
    schemaVersion = 1
    pid = $PID
    host = $env:COMPUTERNAME
    startedAt = (Get-IsoNow)
    command = ("pwsh -File `"$($MyInvocation.MyCommand.Path)`"" + (Get-ArgLine))
    plannedPreStateDir = $PreDirPlanned
    targetHome = $TargetHome
    targetIsLive = $TargetIsLive
    safetyMarginSeconds = $SafetyMarginSeconds
  }
  Write-Json -Path $lockPath -Object $rec
  return $lockPath
}

function Exit-SwitchLock {
  param([string]$LockPath)
  if (-not $LockPath) { return }
  if (-not (Test-Path -LiteralPath $LockPath)) { return }
  $held = Read-Json $LockPath
  if ($held -and [int]$held.pid -ne $PID) { return }
  Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

function Get-ArgLine {
  $parts = New-Object System.Collections.Generic.List[string]
  if ($Version) { $parts.Add("-Version $Version") }
  if ($StagedHome) { $parts.Add("-StagedHome `"$StagedHome`"") }
  if ($BackupDir) { $parts.Add("-BackupDir `"$BackupDir`"") }
  if ($AcceptSessionFormatUpgrade) { $parts.Add('-AcceptSessionFormatUpgrade') }
  if ($DryRun) { $parts.Add('-DryRun') }
  if ($Rollback) { $parts.Add('-Rollback') }
  if ($IUnderstandThisWritesTheLiveHome) { $parts.Add('-IUnderstandThisWritesTheLiveHome') }
  return (' ' + ($parts -join ' '))
}

# ── pre-state ────────────────────────────────────────────────────────────────────────────────────
function New-PreState {
  param([string]$Stamp, $EngineInfo, [string]$LockPath)
  $dir = Join-Path $StateRoot "switch-$Stamp"
  [void](New-Item -ItemType Directory -Path $dir -Force)
  [void](New-Item -ItemType Directory -Path (Join-Path $dir 'config') -Force)

  $pinExists = Test-Path -LiteralPath $PinPath
  if ($pinExists) { Copy-Item -LiteralPath $PinPath -Destination (Join-Path $dir 'pin.json') -Force }
  Copy-Item -LiteralPath $WindowsJson -Destination (Join-Path $dir 'windows.json') -Force

  $files = Get-RecordedConfigFiles -DshHome $TargetHome
  $recorded = New-Object System.Collections.Generic.List[object]
  foreach ($f in $files) {
    $rel = Get-RelPosix -Root $TargetHome -Path $f
    $dest = Join-Path (Join-Path $dir 'config') ($rel -replace '/', '\')
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force)
    Copy-Item -LiteralPath $f -Destination $dest -Force
    $recorded.Add([pscustomobject]@{ rel = $rel; sha256 = (Get-Sha $f); copy = "config/$rel" })
  }

  $sessions = Get-SessionFileList -DshHome $TargetHome
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add("relpath`tbytes")
  foreach ($s in $sessions) { $lines.Add("$($s.rel)`t$($s.bytes)") }
  Set-Content -LiteralPath (Join-Path $dir 'sessions-present.tsv') -Value ($lines -join "`n") -Encoding utf8

  $engineBlock = $null
  if ($EngineInfo) {
    $engineBlock = [ordered]@{ port = $EngineInfo.port; pid = $EngineInfo.pid
      startedAt = $EngineInfo.startedAt; version = $EngineInfo.version; installRoot = $EngineInfo.installRoot }
  }
  $pre = [ordered]@{
    schemaVersion = 1
    mode          = 'switch'
    createdAt     = (Get-IsoNow)
    host          = $env:COMPUTERNAME
    fromVersion   = (Read-Json $PinPath).version
    toVersion     = $Version
    acceptSessionFormatUpgrade = [bool]$AcceptSessionFormatUpgrade
    targetHome    = $TargetHome
    targetIsLive  = $TargetIsLive
    stateRoot     = $StateRoot
    lockFile      = $LockPath
    launcherConfig = [ordered]@{ path = $WindowsJson; sha256Before = (Get-Sha $WindowsJson) }
    pin           = [ordered]@{ path = $PinPath; existedBefore = $pinExists; sha256Before = (Get-Sha $PinPath) }
    # [object[]], NOT @($recorded): a `@(<a generic List>)` inside an [ordered]@{} literal throws
    # "Argument types do not match" in PowerShell 7 (measured 2026-09-28). The cast is the fix.
    recordedConfigFiles = [object[]]$recorded
    sessionFiles  = [ordered]@{ root = (Join-Path $TargetHome 'sessions'); count = $sessions.Count; list = 'sessions-present.tsv' }
    engine        = $engineBlock
    promote       = $null
    sync          = $null
  }
  Write-Json -Path (Join-Path $dir 'PRE-STATE.json') -Object $pre
  return $dir
}

# ── FIX 1 — restore the WHOLE pre-state, and prove it ────────────────────────────────────────────
#
# Nothing here re-runs sync.py to "make the config revert". sync.py would SKIP the version-coupled
# steps (the old engine is back) and leave the new-name config in place — which is exactly the defect
# that caused the incident. The config is restored BYTE FOR BYTE from the recorded copies, and every
# byte is RE-HASHED against the value recorded before the switch.
function Restore-FromRecord {
  param([string]$PreDir, [string]$QuarantineRoot, [switch]$WhatIf)
  $pre = Read-Json (Join-Path $PreDir 'PRE-STATE.json')
  if (-not $pre) {
    return [pscustomobject]@{ ok = $false; restored = @(); problems = @(); movedAside = @()
      problemsList = @("$PreDir\PRE-STATE.json is absent or unparseable") }
  }
  $problems = New-Object System.Collections.Generic.List[string]
  $restored = New-Object System.Collections.Generic.List[string]
  $movedAside = New-Object System.Collections.Generic.List[string]

  # Any file the restore is about to overwrite that is NOT in the pre-state is MOVED ASIDE first.
  # It is never deleted: an unexplained file beside a live config is evidence, not garbage.
  $known = @{}
  if ($pre.recordedConfigFiles) { foreach ($r in @($pre.recordedConfigFiles)) { $known[(Join-Path $pre.targetHome ($r.rel -replace '/', '\')).ToLower()] = $true } }
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $targets = New-Object System.Collections.Generic.List[object]
  $targets.Add([pscustomobject]@{ dest = [string]$pre.launcherConfig.path; src = (Join-Path $PreDir 'windows.json')
                                  sha = $pre.launcherConfig.sha256Before; label = 'the launcher config' })
  if ($pre.pin.existedBefore -ne $false) {
    $targets.Add([pscustomobject]@{ dest = [string]$pre.pin.path; src = (Join-Path $PreDir 'pin.json')
                                    sha = $pre.pin.sha256Before; label = 'pin.json' })
  }
  foreach ($r in @($pre.recordedConfigFiles)) {
    $targets.Add([pscustomobject]@{ dest = (Join-Path $pre.targetHome ($r.rel -replace '/', '\'))
                                    src = (Join-Path $PreDir ($r.copy -replace '/', '\'))
                                    sha = $r.sha256; label = $r.rel })
  }

  foreach ($t in $targets) {
    if (-not (Test-Path -LiteralPath $t.src)) { $problems.Add("the pre-state copy for $($t.label) is MISSING ($($t.src))"); continue }
    if ($t.sha -and (Get-Sha $t.src) -ne $t.sha) {
      $problems.Add("the pre-state copy for $($t.label) does not hash to the recorded value — the way back itself is corrupt ($($t.src))")
      continue
    }
    if (Test-Path -LiteralPath $t.dest) {
      $cur = Get-Sha $t.dest
      if ($cur -eq $t.sha) {
        $restored.Add("$($t.label) is ALREADY at the recorded sha256 $cur — left untouched")
        continue
      }
      # MOVED ASIDE, never deleted, and only for something the pre-state did NOT record. A file that
      # IS in recordedConfigFiles is simply overwritten by its own recorded copy — moving it aside
      # would itself be a write where none was wanted.
      if (-not $known.ContainsKey($t.dest.ToLower())) {
        $q = Join-Path $QuarantineRoot ('moved-aside/' + (Split-Path -Leaf $t.dest) + ".not-in-pre-state-$stamp")
        if ($WhatIf) { $movedAside.Add("WOULD MOVE ASIDE $($t.dest)  (sha256 $cur)  ->  $q") }
        else {
          [void](New-Item -ItemType Directory -Path (Split-Path -Parent $q) -Force)
          Move-Item -LiteralPath $t.dest -Destination $q
          $movedAside.Add("MOVED ASIDE $($t.dest)  (sha256 $cur)  ->  $q")
        }
      }
    }
    if ($WhatIf) { $restored.Add("WOULD RESTORE $($t.label)  <- $($t.src)") ; continue }
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $t.dest) -Force)
    Copy-Item -LiteralPath $t.src -Destination $t.dest -Force
    $now = Get-Sha $t.dest
    if ($now -ne $t.sha) { $problems.Add("$($t.label) restored but hashes $now, expected $($t.sha)") }
    else { $restored.Add("$($t.label)  <- $($t.src)`n              sha256 $now  MATCHES the value recorded before the switch") }
  }

  # The coupled names, read back out of the RESTORED bytes. This is the check the incident asked for:
  # "confirm the live config is consistent with the running engine again".
  $names = New-Object System.Collections.Generic.List[string]
  $ptcRows = 0; $newPtcRows = 0; $regRows = 0; $newRegRows = 0; $presetCount = 0; $patchCount = 0
  foreach ($r in @($pre.recordedConfigFiles)) {
    $dest = Join-Path $pre.targetHome ($r.rel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $dest)) { continue }
    if ($r.rel -like '*agent.cordis.yml') {
      $presetCount++
      $ptcRows    += (Count-Pattern -Path $dest -Pattern $OLD_PTC)
      $newPtcRows += (Count-Pattern -Path $dest -Pattern $NEW_PTC)
    }
    if ($r.rel -like '*cordis.patch.yml') {
      $patchCount++
      $regRows    += (Count-Pattern -Path $dest -Pattern $OLD_REG)
      $newRegRows += (Count-Pattern -Path $dest -Pattern $NEW_REG)
    }
  }
  $names.Add("preset files restored : $presetCount; rows naming the 0.1.5 name @deepseek-ai/dsh-workflow-worker-thread : $ptcRows; rows naming the 0.1.7 name @deepseek-ai/dsh-workflow-ptc : $newPtcRows")
  $names.Add("profile patches restored : $patchCount; rows naming the 0.1.5 name @deepseek-ai/dsh-agent-presets : $regRows; rows naming the 0.1.7 name @deepseek-ai/dsh-agent-preset-registry : $newRegRows")

  # What came from where, for the "whatever the pre-state recorded" report.
  foreach ($r in @($pre.recordedConfigFiles)) {
    $dest = Join-Path $pre.targetHome ($r.rel -replace '/', '\')
    $srcs = New-Object System.Collections.Generic.List[string]
    if ($r.rel -like '*agent.cordis.yml') { $srcs.Add('@deepseek-ai/dsh-workflow-worker-thread'); if ($newPtcRows -gt 0) { $srcs.Add('(the 0.1.7 name is ALSO present here)') } }
    if ($r.rel -like '*cordis.patch.yml') { $srcs.Add('@deepseek-ai/dsh-agent-presets') }
    if ($srcs.Count) { $names.Add("  $($r.rel): now names $($srcs -join ' ')") }
  }

  return [pscustomobject]@{ ok = ($problems.Count -eq 0); restored = @($restored); problems = @($problems)
    movedAside = @($movedAside); names = @($names); pre = $pre }
}

# ── preflight ────────────────────────────────────────────────────────────────────────────────────
function Invoke-Preflight {
  param([string]$OutFile, [string]$ErrFile)
  # TWO HOMES, NOT ONE. `DSH_HOME` is the CONFIG home under test — here, the staged one, because a
  # version-coupled config change cannot be judged against the live config. `DSH_STATE_HOME` is where
  # RUNTIME STATE lives — the model credential G4/G5 boot with, and the `sessions\` corpus G8 counts.
  #
  # WHY THIS IS SET EXPLICITLY (measured 2026-10-05). It was not, so preflight ran with only DSH_HOME
  # staged, and verify's staged-home detection did not fire for a deliberately-named staged home
  # (`C:\Users\ezabz\.dsh-staged\0.2.0-rc.2` is not under a temp root, which is exactly why it is a good
  # place to stage). The result was a NO-GO that said nothing about the candidate:
  #   * G4/G5 did not run at all — no credential could be resolved from the staged home;
  #   * G8 refused outright: "the live session files could not be counted (there is no sessions
  #     directory at <staged>\sessions), so there is no observed live format to compare against";
  #   * `settings-effective` could not find a credential and refused.
  # All three are the same mistake: asking a config question of a directory that deliberately holds no
  # state. G8 in particular exists to compare the candidate's format against the LIVE corpus, so reading
  # the staged home for it was never right.
  # `verify` already supports this (`--state-home`, default `$env:DSH_STATE_HOME`); this call simply
  # never passed it. See dsh-update/tests/guards/README.md for the same two-homes fix inside verify.mjs.
  $code = Invoke-Captured -Exe 'node' `
    -Arguments @((Join-Path $UpdRoot 'lib\cli.mjs'), 'preflight', $Version, '--json') `
    -OutFile $OutFile -ErrFile $ErrFile `
    -SetEnv @{ DSH_HOME = $StagedHome; DSH_STATE_HOME = $TargetHome }
  return [pscustomobject]@{ exitCode = $code; json = (Read-Json $OutFile) }
}

function Get-PreflightVerdict {
  param($Preflight)
  $j = $Preflight.json
  if (-not $j -or -not $j.guards) {
    return [pscustomobject]@{ usable = $false; detail = 'preflight produced no parseable JSON with a guards array' }
  }
  $failed = New-Object System.Collections.Generic.List[string]
  foreach ($g in @($j.guards)) { if ($g.blocking -and -not $g.ok) { $failed.Add([string]$g.name) } }

  $vj = Read-Json (Join-Path $StateRoot "candidates\$Version\verify.json")
  $otherFailing = New-Object System.Collections.Generic.List[string]
  $notRun = New-Object System.Collections.Generic.List[string]
  if ($vj -and $vj.gates) {
    foreach ($g in @($vj.gates)) {
      if ([string]$g.id -eq 'G8') { continue }
      if ($g.ran -eq $true -and $g.ok -eq $false) { $otherFailing.Add([string]$g.id) }
      if ($g.ran -eq $false) { $notRun.Add([string]$g.id) }
    }
  }
  $unexpected = New-Object System.Collections.Generic.List[string]
  foreach ($f in $failed) { if ($f -ne $G8_GUARD -and $f -ne $VER_GUARD) { $unexpected.Add($f) } }
  $notRunReal = New-Object System.Collections.Generic.List[string]
  foreach ($n in $notRun) { if ($n -ne 'GFULL') { $notRunReal.Add($n) } }

  $g8Only = ($failed -contains $G8_GUARD) -and ($unexpected.Count -eq 0) -and
            ($otherFailing.Count -eq 0) -and ($notRunReal.Count -eq 0)
  return [pscustomobject]@{
    usable = $true; go = [bool]$j.go
    failed = @($failed); unexpected = @($unexpected)
    g8Only = [bool]$g8Only; otherFailing = @($otherFailing); notRunReal = @($notRunReal)
    verifyFailed = ($failed -contains $VER_GUARD)
  }
}

# ── the plan printer, shared by -DryRun and by the locked gate ───────────────────────────────────
function Show-Plan {
  param([string]$Stamp, [string]$ExpectRoot, [string]$InstallAtPlan, $Engine, $PinVersion)
  $preDirPlan = Join-Path $StateRoot "switch-$Stamp"
  Say '  STEP 1  create the pre-state directory:'
  Say "            $preDirPlan\"
  Say '          containing:'
  Say "            pin.json                 sha256 $(Get-Sha $PinPath)"
  Say "            windows.json             sha256 $(Get-Sha $WindowsJson)"
  Say "            sessions-present.tsv     $((Get-SessionFileList -DshHome $TargetHome).Count) session file(s), relative to $TargetHome\sessions"
  Say '            PRE-STATE.json           the record above, plus the live engine identity'
  Say '            config\<relpath>         a copy of every live config file the switch may change:'
  foreach ($f in (Get-RecordedConfigFiles -DshHome $TargetHome)) {
    Say ("              {0}`n                sha256 {1}" -f (Get-RelPosix -Root $TargetHome -Path $f), (Get-Sha $f))
  }
  Say ''
  Say "  STEP 2  pwsh -NoProfile -File `"$EntryPoint`" promote $Version$(if ($AcceptSessionFormatUpgrade) { ' --accept-session-format-upgrade' })"
  if ($InjectPromoteScript) { Say "            [INJECTED: -InjectPromoteScript runs $InjectPromoteScript instead of the real promote]" }
  Say "            writes: $WindowsJson"
  Say "                      dshInstall -> $ExpectRoot   (after a timestamped .bak-dsh-update-* sibling)"
  Say "                    $PinPath"
  Say "                      version $PinVersion -> $Version, predecessor recorded"
  Say "                    $StateRoot\history\events.tsv   (one row appended)"
  Say ''
  Say "  STEP 3  python -X utf8 `"$SyncPy`" --engine-root `"$InstallAtPlan`""
  Say "            with DSH_HOME=$TargetHome — FOR REAL, so the coupled steps stop being SKIPPED"
  if ($InjectSyncOut) { Say "            [INJECTED: -InjectSyncOut reads $InjectSyncOut instead of running sync.py]" }
  Say ''
  Say '  STEP 4  verify:'
  Say "            dshInstall is set and equals $ExpectRoot"
  Say "            $TargetHome\.agent-presets\*\agent.cordis.yml now name @deepseek-ai/dsh-workflow-ptc"
  Say "            $TargetHome\profiles\*\cordis.patch.yml now name @deepseek-ai/dsh-agent-preset-registry"
  Say '            sync.py reported "version check passed" for BOTH coupled steps (a SKIPPED step is a FAILED switch)'
  Say "            the live engine pid $($Engine.pid) (started $($Engine.startedAt)) is UNCHANGED"
  Say "            POST-STATE.json records the sha256 of every file written"
  Say ''
  Say '  ON FAILURE ANYWHERE AFTER THE FIRST WRITE: restore pin.json, windows.json AND every recorded'
  Say '  config file from the pre-state, re-hash each one, quarantine anything unexplained, and report a'
  Say '  mismatch as a HARD FAILURE rather than a success. The engine is never started, stopped or restarted.'
  Say ''
  Say "  THE CHANGE LANDS AT THE NEXT BOOT. Nothing is restarted: pid $($Engine.pid) keeps serving this"
  Say '  session. To undo afterwards:'
  Say "            pwsh -File `"$PSCommandPath`" -Rollback -IUnderstandThisWritesTheLiveHome"
}

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# MODE: -Rollback
# ══════════════════════════════════════════════════════════════════════════════════════════════════
function Invoke-RollbackMode {
  Say 'switch-engine -Rollback — restore a switch pre-state, verify every byte, then quarantine v4 sessions.'
  Say ''
  if ($Version -or $StagedHome -or $BackupDir) {
    Warn '-Version / -StagedHome / -BackupDir are ignored in -Rollback mode: the pre-state directory is the input.'
  }
  Show-Containment
  Show-InjectionBanner

  $cands = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^switch-\d{8}T\d{6}Z$' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'PRE-STATE.json')) })
  if ($cands.Count -eq 0) {
    Say ''
    Say "switch-engine: REFUSED — there is no switch pre-state under $StateRoot"
    Say '               (no switch-<UTC stamp>\PRE-STATE.json). There is nothing to roll back TO, so'
    Say '               nothing was changed.'
    exit 3
  }
  $chosen = ($cands | Sort-Object Name | Select-Object -Last 1)
  $preDir = $chosen.FullName
  $pre = Read-Json (Join-Path $preDir 'PRE-STATE.json')
  $postPath = Join-Path $preDir 'POST-STATE.json'
  $post = Read-Json $postPath
  Say "  pre-state   : $preDir"
  Say "  taken       : $($pre.createdAt)   (host $($pre.host))"
  Say "  that switch : pin $($pre.fromVersion) -> $($pre.toVersion)"
  Say "  target home : $($pre.targetHome)$(if (-not $pre.targetIsLive) { '   [that switch did NOT target the live home]' })"
  Say "  restore set : pin.json + windows.json + $(@($pre.recordedConfigFiles).Count) recorded config file(s)"
  if ($post) {
    Say "  post-state  : $postPath"
    Say "                records $(@($post.written).Count) written file(s); it names exactly what that"
    Say '                switch changed, so this restore only touches what was actually written.'
  } else {
    Warn "no POST-STATE.json beside this pre-state, so this restore falls back to the pre-state alone."
  }
  if ($pre.targetIsLive -and -not $IUnderstandThisWritesTheLiveHome) {
    Say ''
    Say "switch-engine: REFUSED — restoring this pre-state writes THE LIVE HOME ($($pre.targetHome))."
    Say '               -IUnderstandThisWritesTheLiveHome was NOT given. Nothing was changed by this run.'
    exit 2
  }

  $engineBefore = Get-LiveEngine
  if ($engineBefore.ok) {
    Say "  live engine now : pid $($engineBefore.pid), started $($engineBefore.startedAt), version $($engineBefore.version)"
    if ($pre.engine) {
      $same = ($pre.engine.pid -eq $engineBefore.pid) -and ([string]$pre.engine.startedAt -eq [string]$engineBefore.startedAt)
      Say "  at the switch   : pid $($pre.engine.pid), started $($pre.engine.startedAt), version $($pre.engine.version)"
      if ($same) { Say '                    the same process — the switch never restarted anything, and neither has anything since' }
      else { Say '                    a DIFFERENT process: the engine has been restarted since the switch (that is when the'
             Say '                    new pin would have taken effect — check which version it booted with before rolling back)' }
    }
  } else {
    Warn "the live engine could not be read: $($engineBefore.reason)"
  }
  Say ''

  Head '1. restore pin.json, the launcher config and every recorded config file — then re-hash each one'
  $quarantineRoot = Join-Path $preDir 'quarantine'
  Say "  quarantine root (nothing is deleted): $quarantineRoot"
  $r = $null
  if ($DryRun) {
    $r = Restore-FromRecord -PreDir $preDir -QuarantineRoot $quarantineRoot -WhatIf
    Say ''
    Say '  DRY RUN — the restore below was NOT performed; this is exactly what it would do:'
  } else {
    $r = Restore-FromRecord -PreDir $preDir -QuarantineRoot $quarantineRoot
  }
  foreach ($line in $r.restored)  { Ok   $line }
  foreach ($line in $r.movedAside) { Warn $line }
  foreach ($p in $r.problems)     { Bad  $p }
  Say ''
  foreach ($n in $r.names) { Say "  $n" }
  if (-not $r.ok) {
    Say ''
    Say 'switch-engine: STOPPED — the restore did not verify. Every problem is listed above; nothing'
    Say '               further was attempted and nothing was deleted.'
    exit 3
  }
  Say ''
  Say '  Every restored file hashes to the sha256 recorded before that switch. The roll-back is complete'
  Say '  for pin.json, the launcher config and all config files — which is precisely what the 2026-09-28'
  Say '  version did NOT do: it restored the engine and left the config behind.'

  Head '2. cross-check against the recorded post-state'
  if (-not $post) {
    Say '  no POST-STATE.json: nothing to cross-check. The restore above stands on the pre-state alone.'
  } else {
    $preHash = @{}; $postHash = @{}
    foreach ($x in @($post.written))  { $postHash[[string]$x.path] = [string]$x.sha256 }
    foreach ($x in @($pre.recordedConfigFiles)) { $preHash[(Join-Path $pre.targetHome ($x.rel -replace '/', '\'))] = [string]$x.sha256 }
    $preHash[[string]$pre.launcherConfig.path] = [string]$pre.launcherConfig.sha256Before
    if ($pre.pin.existedBefore -ne $false) { $preHash[[string]$pre.pin.path] = [string]$pre.pin.sha256Before }
    $other = 0
    foreach ($x in @($post.written)) {
      $p = [string]$x.path
      if (-not (Test-Path -LiteralPath $p)) { Say "  $p  : written by that switch, now ABSENT (nothing in this roll-back deleted it)"; continue }
      $now = Get-Sha $p
      if ($now -eq $x.sha256) { Say "  $p`n      still exactly what that switch wrote (sha256 $now)" }
      elseif ($preHash.ContainsKey($p) -and $now -eq $preHash[$p]) { Say "  $p`n      back to its pre-switch sha256 — restored" }
      else { $other++; Warn "$p hashes $now, which is NEITHER what the switch wrote ($($x.sha256)) NOR its pre-state value — something else changed it; this restore did not" }
    }
    Say ''
    if ($other -eq 0) { Ok 'every file that switch wrote is accounted for: restored, or explained' }
    else { Warn "$other file(s) match neither record — read the lines above before trusting this state" }
  }

  Head '3. quarantine v4 session siblings that were not present before the switch'
  Say '  WHY THIS IS A REPAIR AND NOT A DELETION: `@deepseek-ai/dsh-session-persistence-jsonl` PREFERS the'
  Say '  `session.v4.jsonl.zstd` sibling once it exists (resolveGenerationInDirectory). A v4 log left in'
  Say '  the sessions tree makes the OLD engine HIDE or REFUSE that session even though the v3 original is'
  Say '  still there and still intact. So the file is MOVED out of the sessions tree: it is still readable,'
  Say '  still byte-identical, and no longer in the old engine''s way.'
  Say ''
  $listPath = Join-Path $preDir ([string]$pre.sessionFiles.list)
  $beforeSet = Read-SessionList -ListPath $listPath
  if (-not $beforeSet) {
    Warn "the pre-state has no readable $listPath, so it cannot say which v4 siblings APPEARED. Every v4"
    Warn 'file found will be REPORTED rather than moved, because a move without that list could hide a'
    Warn 'session that was already there.'
  }
  $sessionsRoot  = Join-Path $pre.targetHome 'sessions'
  $quarantineDir = Join-Path $quarantineRoot 'v4-sessions'
  $manifest = New-Object System.Collections.Generic.List[string]
  $manifest.Add("relpath`tbytes`tsha256`tmovedTo")
  $moved = 0; $leftAlone = 0
  $problems = New-Object System.Collections.Generic.List[string]
  $stampNow = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  if (Test-Path -LiteralPath $sessionsRoot) {
    foreach ($f in @(Get-ChildItem -LiteralPath $sessionsRoot -Recurse -File -Force -ErrorAction SilentlyContinue |
                     Where-Object { $_.Name -eq 'session.v4.jsonl.zstd' } | Sort-Object FullName)) {
      $rel = Get-RelPosix -Root $sessionsRoot -Path $f.FullName
      if ($beforeSet -and $beforeSet.ContainsKey($rel)) {
        $leftAlone++
        Say "  LEFT ALONE (it WAS in the pre-state list, so the old engine already knew about it):"
        Say "    $rel"
        continue
      }
      if (-not $beforeSet) {
        Say "  REPORTED, NOT MOVED (no pre-state list to compare against): $rel"
        continue
      }
      $bytes = $f.Length
      $hashBefore = Get-Sha $f.FullName
      $dest = Join-Path $quarantineDir ($rel -replace '/', '\')
      if (Test-Path -LiteralPath $dest) { $dest = "$dest.dup-$stampNow" }
      if ($DryRun) {
        Say "  WOULD MOVE  $rel  ($bytes B, sha256 $($hashBefore.Substring(0,16))...)  ->  $dest"
        $manifest.Add("$rel`t$bytes`t$hashBefore`t$dest")
        continue
      }
      [void](New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force)
      Move-Item -LiteralPath $f.FullName -Destination $dest
      $hashAfter = Get-Sha $dest
      if ($hashAfter -ne $hashBefore) {
        $problems.Add("$rel was moved but its hash CHANGED: $hashBefore -> $hashAfter")
        Bad "  $rel moved to $dest but the hash changed — investigate before trusting this"
      } else {
        $moved++
        Ok "moved  $rel  ($bytes B, sha256 $($hashBefore.Substring(0,16))...)  ->  $dest"
      }
      $manifest.Add("$rel`t$bytes`t$hashBefore`t$dest")
    }
  } else {
    Warn "there is no sessions directory at $sessionsRoot — nothing was inspected (that is a refusal to"
    Warn 'report, not a clean bill of health).'
  }
  $manifestPath = Join-Path $quarantineDir 'quarantine-manifest.tsv'
  if (-not $DryRun) {
    [void](New-Item -ItemType Directory -Path $quarantineDir -Force)
    Set-Content -LiteralPath $manifestPath -Value ($manifest -join "`n") -Encoding utf8
  }
  Say ''
  Say "  $(if ($DryRun) { 'would quarantine' } else { 'quarantined' }) : $moved file(s) $(if ($DryRun) { 'into' } else { 'moved into' }) $quarantineDir"
  Say "  left in place: $leftAlone file(s), because the pre-state list already named them"
  Say "  manifest    : $manifestPath$(if ($DryRun) { '   (would be written)' })"
  foreach ($p in $problems) { Bad $p }

  Head '4. the engine'
  if ($engineBefore.ok) {
    $chk = Test-LiveEngineUnchanged -Before $engineBefore
    if ($chk.unchanged) { Ok "untouched by this roll-back — $($chk.detail)" }
    else { Bad "the engine CHANGED during this roll-back: $($chk.detail)" }
  } else {
    Warn "before this run the engine could not be read ($($engineBefore.reason)), so there is no before/after to compare"
  }
  Say ''
  Say '  THE ENGINE WAS NOT RESTARTED, and this script cannot restart one. The restored dshInstall takes'
  Say '  effect at the NEXT boot, started by a human or by a reboot.'

  Say ''
  Say '-- SUMMARY'
  Say "  restored    : pin.json, the launcher config, and all $(@($pre.recordedConfigFiles).Count) recorded config file(s) — each re-hashed against its pre-switch value"
  Say "  post-state  : $(if ($post) { 'present and cross-checked' } else { 'absent — restored from the pre-state alone' })"
  Say "  quarantined : $moved v4 session file(s) $(if ($DryRun) { 'WOULD be moved' } else { 'MOVED' }) to $quarantineDir (nothing deleted)"
  Say "  engine      : $(if ($engineBefore.ok) { "pid $($engineBefore.pid), started $($engineBefore.startedAt) — unchanged" } else { 'not readable' })"
  exit 0
}

# ── the banner that names every injection in force ───────────────────────────────────────────────
function Show-InjectionBanner {
  if ($InjectNextRunInSeconds -ne -2147483648) { Warn "INJECTED TASK TIMING: the sync task's NextRunTime is faked ($InjectNextRunInSeconds s). The real task was NOT queried." }
  if ($InjectLastRunAt)    { Warn "INJECTED LastRunTime (before): $InjectLastRunAt" }
  if ($InjectLastRunAfter) { Warn "INJECTED LastRunTime (after the writes): $InjectLastRunAfter — simulates a tick that landed mid-sequence" }
  if ($InjectEngineJson)   { Warn "INJECTED ENGINE RECORD: $InjectEngineJson instead of the process on the launcher port" }
  if ($InjectSyncOut)      { Warn "INJECTED SYNC OUTPUT: $InjectSyncOut instead of running scripts/sync.py" }
  if ($InjectPromoteScript){ Warn "INJECTED PROMOTE: $InjectPromoteScript instead of bin\dsh-update.ps1 promote" }
  if ($InjectPreflightVerdict) { Warn "INJECTED PREFLIGHT VERDICT: '$InjectPreflightVerdict' — the pipeline's own GO/NO-GO is NOT what decides here. This exists so the WRITE path and the roll-back can be exercised without first making the repository's preflight pass." }
  if ($InjectVerification) { Warn "INJECTED VERIFICATION RESULT: '$InjectVerification' — step 4 is skipped, NOT passed. This exists to reach a LATER check (the mid-sequence sync-tick reading) that a name mismatch would otherwise mask. Any run that uses it CANNOT claim its outcome was verified." }
  if ($TestHookAfterWrite) { Warn "TEST HOOK IN FORCE: $TestHookAfterWrite runs after the writes and before verification" }
  if ($SafetyMarginSeconds -ne 180) { Warn "SAFETY MARGIN OVERRIDDEN: $SafetyMarginSeconds s (default 180)" }
  if ($LockStaleSeconds -ne 300)    { Warn "LOCK STALE THRESHOLD OVERRIDDEN: $LockStaleSeconds s (default 300)" }
}

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════════════════════════════════════════════
foreach ($exe in @('node', 'pwsh', 'python')) {
  if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
    Say "switch-engine: STOPPED — $exe is not on PATH; this script needs it."
    exit 1
  }
}

if ($Rollback) { Invoke-RollbackMode }

$writesAllowed = Test-LiveWritesUnlocked
$gateRefusal   = Get-GateRefusal

Say 'switch-engine — apply the engine pin and the version-coupled config as ONE operation.'
Say "  repo        : $RepoRoot"
Say "  mode        : $(if ($DryRun) { 'DRY RUN (writes nothing at all, anywhere)' } elseif ($writesAllowed) { 'APPLY (writes permitted)' } else { 'DRESS REHEARSAL (every check, no write)' })"
Say "  target home : $TargetHome$(if (-not $TargetIsLive) { '   [NOT the live home: containment override in force]' })"
Say "  launcher    : $WindowsJson$(if (-not $LauncherIsReal) { '   [NOT the repo''s own: containment override in force]' })"
Say "  state root  : $StateRoot$(if (-not $StateIsReal) { '   [NOT the deployment''s: containment override in force]' })"
Say "  live write  : $(if ($IUnderstandThisWritesTheLiveHome) { 'UNLOCKED by -IUnderstandThisWritesTheLiveHome' } else { 'LOCKED — no write to the live home, no pre-state directory, no lock file' })"
Say "  accept-G8   : $(if ($AcceptSessionFormatUpgrade) { 'GIVEN' } else { 'not given' })"
Show-InjectionBanner
Say ''

if (-not $Version -or -not $StagedHome -or -not $BackupDir) {
  Refuse '-Version, -StagedHome and -BackupDir are all required.'
}

# Snapshot this switch's OWN write surface BEFORE anything, so the proofs below mean something.
$preStateBefore = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like 'switch-*' } | ForEach-Object { $_.Name } | Sort-Object)
$pinBefore      = Get-Sha $PinPath
$launcherBefore = Get-Sha $WindowsJson
$lockBefore     = Get-Sha (Get-LockPath)
$cfgBefore = @{}
foreach ($f in (Get-RecordedConfigFiles -DshHome $TargetHome)) { $cfgBefore[$f] = Get-Sha $f }

# ── PRECONDITION 1 — a verified, recent backup ───────────────────────────────────────────────────
Head 'PRECONDITION 1 — the backup is verified and recent'
$reportPath = Join-Path $BackupDir 'BACKUP-REPORT.json'
if (-not (Test-Path -LiteralPath $reportPath)) {
  Refuse "there is no BACKUP-REPORT.json in $BackupDir — a backup directory that cannot show its own verdict is not a backup."
}
$report = Read-Json $reportPath
if (-not $report) { Refuse "$reportPath does not parse as JSON, so its verdict is unknown." }
if ($report.ok -ne $true) {
  $n = if ($report.problems) { @($report.problems).Count } else { 0 }
  Refuse "the backup at $BackupDir reports ok=$($report.ok) with $n problem(s). An unverified backup is a hope, not a backup."
}
if (-not $report.PSObject.Properties.Name.Contains('finishedAt') -or -not $report.finishedAt) {
  Refuse "$reportPath carries no finishedAt, so this backup's age cannot be established."
}
$finished = Get-DtOrNull ([string]$report.finishedAt)
if (-not $finished) { Refuse "$reportPath carries an unparseable finishedAt: $($report.finishedAt)" }
$ageHours = ([datetime]::UtcNow - $finished).TotalHours
$verifiedFiles = 0
foreach ($s in @($report.stores)) {
  if ($s.PSObject.Properties.Name -contains 'verified') { $verifiedFiles += [int]$s.verified }
}
if ($ageHours -gt 12) {
  Refuse ("the backup at $BackupDir finished at $($report.finishedAt), which is {0:N1} hours ago — older than 12 hours. A backup taken for an earlier step is not a backup for the step being taken now." -f $ageHours)
}
if ($ageHours -lt -0.25) {
  Refuse ("the backup at $BackupDir claims finishedAt $($report.finishedAt), which is {0:N1} hours in the FUTURE. A timestamp that cannot be true is not evidence." -f $ageHours)
}
Ok ("backup ok: finished {0} ({1:N1} h ago); totalFiles {2}; {3} file(s) verified individually" -f $report.finishedAt, $ageHours, $report.totalFiles, $verifiedFiles)
Say "  report      : $reportPath"
Say "  destination : $($report.destination)"

# ── PRECONDITION 2 — the staged home carries the migrated config ─────────────────────────────────
Head 'PRECONDITION 2 — the staged home carries the migrated config'
if (-not (Test-Path -LiteralPath $StagedHome -PathType Container)) {
  Refuse "the staged home does not exist: $StagedHome"
}
$stagedPresets = @()
$pdir = Join-Path $StagedHome '.agent-presets'
if (Test-Path -LiteralPath $pdir) {
  $stagedPresets = @(Get-ChildItem -LiteralPath $pdir -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'agent.cordis.yml' } | Where-Object { Test-Path -LiteralPath $_ })
}
$stagedPatches = @()
$prdir = Join-Path $StagedHome 'profiles'
if (Test-Path -LiteralPath $prdir) {
  $stagedPatches = @(Get-ChildItem -LiteralPath $prdir -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'cordis.patch.yml' } | Where-Object { Test-Path -LiteralPath $_ })
}
$missing = New-Object System.Collections.Generic.List[string]
if ($stagedPresets.Count -eq 0) { $missing.Add("no preset file exists at $StagedHome\.agent-presets\*\agent.cordis.yml") }
if ($stagedPatches.Count -eq 0) { $missing.Add("no profile patch exists at $StagedHome\profiles\*\cordis.patch.yml") }

$ptcRows = 0; $oldPtcRows = 0
foreach ($f in $stagedPresets) { $ptcRows += (Count-Pattern -Path $f -Pattern $NEW_PTC); $oldPtcRows += (Count-Pattern -Path $f -Pattern $OLD_PTC) }
$regRows = 0; $oldRegRows = 0
foreach ($f in $stagedPatches) { $regRows += (Count-Pattern -Path $f -Pattern $NEW_REG); $oldRegRows += (Count-Pattern -Path $f -Pattern $OLD_REG) }

if ($ptcRows -eq 0)    { $missing.Add("no preset names '@deepseek-ai/dsh-workflow-ptc' as a composition row") }
if ($regRows -eq 0)    { $missing.Add("no profile patch names '@deepseek-ai/dsh-agent-preset-registry' as a composition row") }
if ($oldPtcRows -gt 0) { $missing.Add("$oldPtcRows preset row(s) still name the REMOVED '@deepseek-ai/dsh-workflow-worker-thread'") }
if ($oldRegRows -gt 0) { $missing.Add("$oldRegRows profile patch row(s) still name the REMOVED '@deepseek-ai/dsh-agent-presets'") }
if ($missing.Count -gt 0) {
  Say '  what is missing or wrong in the staged home:'
  foreach ($m in $missing) { Say "    - $m" }
  Refuse "the staged home at $StagedHome is not the migrated config this switch installs. Fix the staged copy first."
}
Ok "$($stagedPresets.Count) preset file(s): $ptcRows row(s) name @deepseek-ai/dsh-workflow-ptc, $oldPtcRows row(s) name the removed worker-thread package"
Ok "$($stagedPatches.Count) profile patch(es): $regRows row(s) name @deepseek-ai/dsh-agent-preset-registry, $oldRegRows row(s) name the removed plural package"

# ── PRECONDITION 3 — FIX 2: the sync window, and the switch lock ─────────────────────────────────
#
# WHY THIS COMES BEFORE THE ENGINE AND PREFLIGHT CHECKS, and not just before the writes: reading the
# clock is the cheapest thing here and it is the one that must not be discovered late. The incident
# happened because the live config moved during a tick. If the window is not clear the answer must be
# known before preflight spends a minute of it, and before anything at all has been written.
Head 'PRECONDITION 3 — no sync tick inside this operation (FIX 2)'
Say "  guard : task '$SyncTaskName' runs every 15 minutes; a tick due within -SafetyMarginSeconds"
Say "          ($SafetyMarginSeconds s) refuses this switch, and a switch-held lock file keeps two"
Say '          switches from interleaving. This is defence in depth: it does not rely on the guard being'
Say '          hardened to resolve the RUNNING engine, because it does not have to.'
$stamp     = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$preDirPlan = Join-Path $StateRoot "switch-$stamp"
$taskBefore = Get-SyncTaskState
Show-SyncTaskState -S $taskBefore
$window = Test-SyncWindow -S $taskBefore
Say ''
if (-not $window.ok) {
  Say '  the window is NOT clear:'
  Say ''
  Say "  REFUSED — $($window.why)"
  Say ''
  Say '  NOTHING WAS WRITTEN. No pre-state directory, no lock file, no pin, no launcher config, no live'
  Say "  config file, and no engine was touched. The next tick is at $(if ($taskBefore.nextRunTime) { ([datetime]$taskBefore.nextRunTime).ToUniversalTime().ToString('HH:mm:ss') + ' local-host time (UTC ' + ([datetime]$taskBefore.nextRunTime).ToUniversalTime().ToString('HH:mm:ss') + ')' } else { '(unknown)' })."
  if ($DryRun) { Say '  (This is a -DryRun, so nothing would have been written anyway — but the window itself is not clear.)' }
  exit 2
}
Ok ("the next sync tick is {0:N0} s away ({1:o}), outside the {2} s margin — the window is clear" -f $window.seconds, $window.next, $SafetyMarginSeconds)

$lockPath = $null
if ($DryRun) {
  Say '  -DryRun: no lock file is written and none is held. (A dry run writes nothing at all.)'
} else {
  $lockPath = Enter-SwitchLock -PreDirPlanned $preDirPlan
  $script:LockPath = $lockPath
  Ok "lock taken: $lockPath"
}

# ── PRECONDITION 4 — a live engine, at the pin's version ──────────────────────────────────────────
Head 'PRECONDITION 4 — a live engine, at the pin version'
$pin = Read-Json $PinPath
if (-not $pin -or -not $pin.version) {
  Refuse "$PinPath is absent or carries no version, so there is no pin version to compare the live engine against."
}
$engine = Get-LiveEngine
if (-not $engine.ok) { Refuse "no live engine: $($engine.reason)" }
Say "  live engine : pid $($engine.pid), started $($engine.startedAt), port $($engine.port)"
Say "                $($engine.cmd)"
Say "                install root $($engine.installRoot)"
Say "  pin         : $($pin.version)   (from $PinPath)"
if ($engine.version -ne $pin.version) {
  Refuse "the live engine reports $($engine.version) but the pin says $($pin.version). They must agree: this switch is defined as a move FROM the pin, and a mismatch means the pin is not describing what is running."
}
Ok "the live engine runs $($engine.version), exactly the pin's version"

# ── PRECONDITION 5 — preflight says GO, or fails on G8 alone and that is accepted ─────────────────
Head "PRECONDITION 5 — preflight $Version with DSH_HOME=$StagedHome"
Say '  This runs the pipeline, and the pipeline keeps its own books: preflight re-runs analyze,'
Say '  patch-effect, preset-gate and verify, so it REFRESHES dsh-update\state\candidates\<ver>\*.json and'
Say '  appends one state\history row. That is the guard-runner reading. THIS SWITCH writes nothing until'
Say '  every precondition here has passed.'
$pfOut = Join-Path $env:TEMP "switch-engine-preflight-$([guid]::NewGuid().ToString('N')).json"
$pfErr = "$pfOut.err"
$pf = Invoke-Preflight -OutFile $pfOut -ErrFile $pfErr
Say "  exit: $($pf.exitCode)"
$verdict = Get-PreflightVerdict -Preflight $pf
if (-not $verdict.usable) {
  Refuse "preflight produced no readable verdict ($($verdict.detail)). Its stderr tail: $(Get-Tail -Path $pfErr -Lines 8)"
}
foreach ($g in @($pf.json.guards)) {
  $mark = if ($g.ok) { 'PASS' } elseif ($g.blocking) { 'FAIL' } else { 'GAP ' }
  Say "  $mark  $($g.name)"
  Say "        $([string]$g.detail)"
}
Say ''
if ($InjectPreflightVerdict) {
  Say "  >>> PREFLIGHT VERDICT INJECTED: $InjectPreflightVerdict (test only; the real verdict above is what the"
  Say '  >>> pipeline produced, and it is printed above so the decision cannot be confused with the reading)'
  if ($InjectPreflightVerdict -eq 'GO') {
    $verdict = [pscustomobject]@{ usable = $true; go = $true; failed = @(); unexpected = @()
      g8Only = $false; otherFailing = @(); notRunReal = @(); verifyFailed = $false }
  } elseif ($InjectPreflightVerdict -eq 'G8ACCEPTED') {
    # The shape the ORIGINAL run relied on: the only substantive failure is G8. Nothing else about the
    # run changes — in particular the real guards output above is still what was measured.
    $verdict = [pscustomobject]@{ usable = $true; go = $false; failed = @($G8_GUARD); unexpected = @()
      g8Only = $true; otherFailing = @(); notRunReal = @(); verifyFailed = $true }
  } else {
    $verdict = [pscustomobject]@{ usable = $true; go = $false; failed = @('analyze (contract diff)'); unexpected = @('analyze (contract diff)')
      g8Only = $false; otherFailing = @(); notRunReal = @(); verifyFailed = $false }
  }
}
if ($verdict.go) {
  Ok 'preflight verdict: GO — every blocking guard is green.'
} elseif ($verdict.g8Only) {
  Say '  preflight verdict: NO-GO, and the ONLY substantive failure is G8, the session-format door.'
  Say "  failing blocking guard(s)   : $($verdict.failed -join '; ')"
  Say "  verify gates other than G8 that ran and failed : $(if ($verdict.otherFailing.Count) { $verdict.otherFailing -join ',' } else { 'none' })"
  Say "  verify gates that did not run (GFULL is opt-in and excluded) : $(if ($verdict.notRunReal.Count) { $verdict.notRunReal -join ',' } else { 'none' })"
  Say '  So the `verify` guard fails ONLY because G8 fails; G1-G7 all ran and all passed.'
  if (-not $AcceptSessionFormatUpgrade) {
    Refuse ("preflight is NO-GO on the G8 session-format door: the candidate writes session format v4 while the logs on disk are v3, and no down-migration codec exists. That is a one-way door, and it is a decision only the operator can make.`n               Re-run with -AcceptSessionFormatUpgrade to RECORD that decision — the acceptance is written into the pin and the pipeline history, not skipped.")
  }
  Ok '-AcceptSessionFormatUpgrade was given: G8 is accepted as a RECORDED, deliberate decision, not a bypass.'
  Warn 'READ THIS BEFORE STEP 2. `promote` conditions are 1) a passing verify for this exact contract,'
  Warn '2) a diff verdict that is not BREAKS, 3) strictly newer than the pin, 4) the session-format door'
  Warn 'absent or accepted. -AcceptSessionFormatUpgrade satisfies condition 4 ONLY. Condition 1 keys on'
  Warn '`verify.pass`, and verify.mjs sets pass=false whenever ANY gate that ran has ok=false — which'
  Warn 'G8 does here. So unless G8 passes, promote WILL refuse at step 2 and this switch will roll the'
  Warn 'pre-state back. That is the pipeline''s own gate, and it is not something this script may or'
  Warn 'should bypass: condition 1 has no flag on purpose.'
} else {
  Refuse ("preflight is NO-GO for reasons other than the session-format door.`n               Failing blocking guard(s): $($verdict.failed -join '; ')`n               Nothing was written. Fix the pipeline's own complaint above, then run this again.")
}

# ── the plan ─────────────────────────────────────────────────────────────────────────────────────
$expectRoot = Join-Path $UpdRoot "vendor\prefix\$Version"
$lcNow = Read-Json $WindowsJson
$installAtPlan = if ($lcNow -and $lcNow.PSObject.Properties.Name.Contains('dshInstall') -and $lcNow.dshInstall) { [string]$lcNow.dshInstall } else { $expectRoot }

Head 'THE PLAN — the exact sequence, and the files it writes'
Show-Plan -Stamp $stamp -ExpectRoot $expectRoot -InstallAtPlan $installAtPlan -Engine $engine -PinVersion $pin.version

if ($DryRun) {
  Head 'DRY RUN — proof that nothing was written'
  $preStateAfter = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'switch-*' } | ForEach-Object { $_.Name } | Sort-Object)
  $pinAfter      = Get-Sha $PinPath
  $launcherAfter = Get-Sha $WindowsJson
  $lockAfter     = Get-Sha (Get-LockPath)
  $changedCfg = @()
  foreach ($f in $cfgBefore.Keys) { if ((Get-Sha $f) -ne $cfgBefore[$f]) { $changedCfg += $f } }
  $added = @($preStateAfter | Where-Object { $preStateBefore -notcontains $_ })
  Say "  state\switch-* directories : before $($preStateBefore.Count), after $($preStateAfter.Count)$(if ($added.Count) { "  <-- CREATED: $($added -join ', ')" } else { '  (none created)' })"
  Say "  state\pin.json             : $(if ($pinAfter -eq $pinBefore) { "unchanged  $pinAfter" } else { "CHANGED  $pinBefore -> $pinAfter" })"
  Say "  $WindowsJson"
  Say "                             : $(if ($launcherAfter -eq $launcherBefore) { "unchanged  $launcherAfter" } else { "CHANGED  $launcherBefore -> $launcherAfter" })"
  Say "  lock file                  : $(if ($lockAfter -eq $lockBefore) { "unchanged  $(if ($lockAfter) { $lockAfter } else { '(does not exist)' })" } else { "CHANGED  $lockBefore -> $lockAfter" })"
  Say "  recorded config files      : $(if ($changedCfg.Count -eq 0) { "all $($cfgBefore.Count) unchanged" } else { "CHANGED: $($changedCfg -join ', ')" })"
  if ($added.Count -or $pinAfter -ne $pinBefore -or $launcherAfter -ne $launcherBefore -or $lockAfter -ne $lockBefore -or $changedCfg.Count) {
    Stop-Hard 'a dry run modified something it must not have. That is a bug in this script, not a state to trust.' 1
  }
  Say ''
  Say '  DRY RUN COMPLETE — every precondition passed, the plan is printed above, and this switch wrote'
  Say '  nothing: no pre-state directory, no lock file, no pin, no launcher config, no live config file.'
  exit 0
}

# ── THE GATE — the mechanism, not the instruction ────────────────────────────────────────────────
if (-not $writesAllowed) {
  if ($lockPath) { Exit-SwitchLock -LockPath $lockPath }
  Say ''
  Say 'switch-engine: REFUSED — the live-write gate is locked.'
  Say "               $gateRefusal"
  Say ''
  Say '               NOTHING WAS WRITTEN. Every precondition above passed and the plan is printed'
  Say '               above; this run wrote no pre-state directory, no lock file, no pin, no launcher'
  Say '               config and no live config file. The lock it took for the plan was released.'
  exit 2
}

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# APPLY
# ══════════════════════════════════════════════════════════════════════════════════════════════════
$stepFailed = $null
$promoteCode = 0        # 0 = "promote never ran or refused before writing"; set below when it does run
$syncCode = $null
$wroteAnything = $false
$preDir = $null
$hardStop = $null

try {
  Head 'STEP 1 — write the pre-state record (everything needed to undo steps 2-4)'
  $preDir = New-PreState -Stamp $stamp -EngineInfo $engine -LockPath $lockPath
  $preRead = Read-Json (Join-Path $preDir 'PRE-STATE.json')
  if (-not $preRead) {
    # NOT an exit: an unreadable pre-state is a failure on the FIRST write, and the failure path below
    # releases the lock and tells the operator exactly where the directory is. A way back that cannot
    # be read is not a way back, so nothing is promoted either way.
    throw "the pre-state record could not be written or read back: $preDir\PRE-STATE.json (the directory was left in place for inspection)"
  }
  $wroteAnything = $true
  Say "  pre-state   : $preDir"
  Say "  pin.json    : sha256 $($preRead.pin.sha256Before)   (version $($pin.version))"
  Say "  launcher    : $($preRead.launcherConfig.path)"
  Say "                sha256 $($preRead.launcherConfig.sha256Before)   dshInstall now $(if ($installAtPlan -eq $expectRoot -and -not ($lcNow.PSObject.Properties.Name -contains 'dshInstall')) { 'ABSENT' } else { "'$installAtPlan'" })"
  Say "  config files: $(@($preRead.recordedConfigFiles).Count) recorded with sha256 AND a copy:"
  foreach ($r in @($preRead.recordedConfigFiles)) { Say "                  $($r.rel)   sha256 $($r.sha256)" }
  Say "  session list: $($preRead.sessionFiles.count) file(s) under $($preRead.sessionFiles.root)"
  Say "                -> $preDir\$($preRead.sessionFiles.list)"
  Say '                This list is what lets -Rollback identify EXACTLY which session.v4.jsonl.zstd'
  Say '                siblings APPEARED after this switch, and therefore which ones to quarantine.'
  Ok 'pre-state written'

  Head "STEP 2 — promote $Version"
  $promoteArgs = @('-NoProfile', '-File', $EntryPoint, 'promote', $Version)
  if ($AcceptSessionFormatUpgrade) { $promoteArgs += '--accept-session-format-upgrade' }
  if ($InjectPromoteScript) {
    $promoteArgs = @('-NoProfile', '-File', $InjectPromoteScript, '-Version', $Version, '-WindowsJson', $WindowsJson, '-PinPath', $PinPath, '-ExpectRoot', $expectRoot)
  }
  $pOut = Join-Path $preDir 'promote.out.txt'
  $pErr = Join-Path $preDir 'promote.err.txt'
  Say "  command: pwsh $($promoteArgs -join ' ')"
  $promoteCode = Invoke-Captured -Exe 'pwsh' -Arguments $promoteArgs -OutFile $pOut -ErrFile $pErr
  Say "  exit: $promoteCode"
  Say ''
  foreach ($l in @(Get-Content -LiteralPath $pOut -ErrorAction SilentlyContinue)) { Say "  $l" }
  $pErrTail = Get-Tail -Path $pErr -Lines 10
  if ($pErrTail -ne '(empty)' -and $pErrTail -ne '(no output file)') {
    Say ''; Say '  stderr:'; foreach ($l in ($pErrTail -split "`n")) { Say "  $l" }
  }
  $preUpd = Read-Json (Join-Path $preDir 'PRE-STATE.json')
  if ($preUpd) {
    $preUpd.promote = [ordered]@{ command = "pwsh $($promoteArgs -join ' ')"; exitCode = $promoteCode; out = 'promote.out.txt'; err = 'promote.err.txt' }
    Write-Json -Path (Join-Path $preDir 'PRE-STATE.json') -Object $preUpd
  }
  if ($promoteCode -ne 0) {
    $stepFailed = "promote exited $promoteCode and refused to write (its own gate named the reason above). Its output is kept at $pOut"
  } else {
    Ok 'promote wrote the pin and the launcher knob'
  }

  if (-not $stepFailed) {
    Head 'STEP 3 — run scripts/sync.py for real'
    $lcAfter = Read-Json $WindowsJson
    $newInstall = if ($lcAfter -and $lcAfter.PSObject.Properties.Name.Contains('dshInstall') -and $lcAfter.dshInstall) { [string]$lcAfter.dshInstall } else { $null }
    $syncArgs = @('-X', 'utf8', $SyncPy)
    if ($newInstall) { $syncArgs += @('--engine-root', $newInstall) }
    $sOut = Join-Path $preDir 'sync.out.txt'
    $sErr = Join-Path $preDir 'sync.err.txt'
    $syncCode = $null
    if ($InjectSyncOut) {
      Copy-Item -LiteralPath $InjectSyncOut -Destination $sOut -Force
      Set-Content -LiteralPath $sErr -Value '' -Encoding utf8
      Say "  command: (INJECTED) the text of $InjectSyncOut is used as sync.py's stdout; sync.py was NOT run"
      $syncCode = 0
    } else {
      Say "  command: python $($syncArgs -join ' ')"
      Say "  DSH_HOME=$TargetHome"
      Say "  the version precondition will resolve the engine from: $(if ($newInstall) { $newInstall } else { 'its own fallbacks — no dshInstall was written' })"
      $syncCode = Invoke-Captured -Exe 'python' -Arguments $syncArgs -OutFile $sOut -ErrFile $sErr -SetEnv @{ DSH_HOME = $TargetHome }
    }
    Say "  exit: $syncCode"
    Say ''
    foreach ($l in @(Get-Content -LiteralPath $sOut -ErrorAction SilentlyContinue)) { Say "  $l" }
    $sErrTail = Get-Tail -Path $sErr -Lines 12
    if ($sErrTail -ne '(empty)' -and $sErrTail -ne '(no output file)') {
      Say ''; Say '  stderr:'; foreach ($l in ($sErrTail -split "`n")) { Say "  $l" }
    }
    $preUpd2 = Read-Json (Join-Path $preDir 'PRE-STATE.json')
    if ($preUpd2) {
      $preUpd2.sync = [ordered]@{ command = $(if ($InjectSyncOut) { "(injected) $InjectSyncOut" } else { "python $($syncArgs -join ' ')" }); exitCode = $syncCode; out = 'sync.out.txt'; err = 'sync.err.txt' }
      Write-Json -Path (Join-Path $preDir 'PRE-STATE.json') -Object $preUpd2
    }
    if ($syncCode -ne 0) {
      Say ''
      Say "  NOTE: sync exited $syncCode. sync's exit code ALSO reflects its client-plugin and"
      Say '  metrics-sampler checks, which are machine-local and independent of this switch (they are'
      Say '  max()-ed into its exit code, see scripts/sync.py main()). The two coupled steps are judged'
      Say '  below by their own `version check passed` / `SKIPPED` lines, which is what this step needs.'
    }

    # ── FIX 3 — the coupled steps must have APPLIED, not been SKIPPED ────────────────────────────
    $syncText = [string](Get-Content -LiteralPath $sOut -Raw -ErrorAction SilentlyContinue)
    if ($syncText -match '(?m)^\s*presets: SKIPPED') {
      $stepFailed = 'sync reported `presets: SKIPPED`: the version precondition did not see the new engine, so the coupled config was NOT applied. A half-applied switch is the one state this script exists to prevent, so this counts as a FAILURE OF THE SWITCH and it is rolled back.'
    } elseif ($syncText -match '(?m)^\s*profiles: SKIPPED') {
      $stepFailed = 'sync reported `profiles: SKIPPED`: the version precondition did not see the new engine, so the coupled profile layer was NOT applied. This is a FAILURE OF THE SWITCH and it is rolled back.'
    } elseif (-not ($syncText -match '(?m)^\s*presets: version check passed')) {
      $stepFailed = 'sync did not report `presets: version check passed`, so its preset step is unaccounted for — an unreported step is a failed switch, not an unknown.'
    } elseif (-not ($syncText -match '(?m)^\s*profiles: version check passed')) {
      $stepFailed = 'sync did not report `profiles: version check passed`, so its profile step is unaccounted for — an unreported step is a failed switch, not an unknown.'
    } else {
      Ok 'sync reported `version check passed` for BOTH coupled steps — the preset and profile layers were published'
    }
  }

  # ── the mid-sequence test hook ──────────────────────────────────────────────────────────────────
  if ($TestHookAfterWrite) {
    Head 'TEST HOOK — running after the writes and before verification'
    Warn "TEST HOOK IN FORCE: $TestHookAfterWrite   (this is a test injection, not a production path)"
    $hOut = Join-Path $preDir 'test-hook.out.txt'
    $hErr = Join-Path $preDir 'test-hook.err.txt'
    $hCode = Invoke-Captured -Exe 'pwsh' -Arguments @('-NoProfile', '-File', $TestHookAfterWrite,
      '-WindowsJson', $WindowsJson, '-PinPath', $PinPath, '-PresetsDir', (Join-Path $TargetHome '.agent-presets'),
      '-ProfilesDir', (Join-Path $TargetHome 'profiles')) `
      -OutFile $hOut -ErrFile $hErr
    Say "  exit: $hCode"
    foreach ($l in @(Get-Content -LiteralPath $hOut -ErrorAction SilentlyContinue)) { Say "  $l" }
    if ($hCode -ne 0) { $stepFailed = "the test hook exited $hCode (that is the injected mid-sequence failure)" }
  }

  if (-not $stepFailed -and $InjectVerification) {
    Head 'STEP 4 — verify the outcome rather than assuming it'
    Warn "STEP 4 WAS SKIPPED, NOT PASSED. -InjectVerification '$InjectVerification' was given so that a"
    Warn 'check that comes LATER (the mid-sequence sync-tick reading) can be reached. No run that uses'
    Warn 'this injection can claim its outcome was verified, and none of them is a production path.'
  }

  if (-not $stepFailed -and -not $InjectVerification) {
    Head 'STEP 4 — verify the outcome rather than assuming it'
    $lcNow2 = Read-Json $WindowsJson
    $installNow = if ($lcNow2 -and $lcNow2.PSObject.Properties.Name.Contains('dshInstall') -and $lcNow2.dshInstall) { [string]$lcNow2.dshInstall } else { $null }
    if (-not $installNow) {
      $stepFailed = 'dshInstall is still ABSENT from the launcher config after promote'
    } elseif ([System.IO.Path]::GetFullPath($installNow).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($expectRoot).TrimEnd('\')) {
      $stepFailed = "dshInstall is '$installNow' but this version's own prefix is '$expectRoot'"
    } else { Ok "dshInstall = $installNow  (this version's own prefix)" }

    if (-not $stepFailed) {
      $livePresets = @(Get-ChildItem -LiteralPath (Join-Path $TargetHome '.agent-presets') -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'agent.cordis.yml' } | Where-Object { Test-Path -LiteralPath $_ })
      $livePatches = @(Get-ChildItem -LiteralPath (Join-Path $TargetHome 'profiles') -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'cordis.patch.yml' } | Where-Object { Test-Path -LiteralPath $_ })
      $goodPtc = 0; $badPtc = @(); $goodReg = 0; $badReg = @()
      foreach ($f in $livePresets) {
        $n = Count-Pattern -Path $f -Pattern $NEW_PTC
        $o = Count-Pattern -Path $f -Pattern $OLD_PTC
        if ($n -gt 0 -and $o -eq 0) { $goodPtc++ }
        else { $badPtc += "$f (names-new=$n, names-removed=$o)" }
      }
      foreach ($f in $livePatches) {
        $n = Count-Pattern -Path $f -Pattern $NEW_REG
        $o = Count-Pattern -Path $f -Pattern $OLD_REG
        if ($n -gt 0 -and $o -eq 0) { $goodReg++ } else { $badReg += "$f (names-new=$n, names-removed=$o)" }
      }
      if ($badPtc.Count -eq 0 -and $goodPtc -gt 0) {
        Ok "$goodPtc live preset file(s) now name @deepseek-ai/dsh-workflow-ptc and none name the removed worker-thread package"
      } else {
        $stepFailed = "the live presets did not all move to the new name: $($badPtc -join '; ')"
      }
      if (-not $stepFailed) {
        if ($badReg.Count -eq 0 -and $goodReg -gt 0) {
          Ok "$goodReg live profile patch(es) now name @deepseek-ai/dsh-agent-preset-registry and none name the removed plural package"
        } else {
          $stepFailed = "the live profile patches did not all move to the new name: $($badReg -join '; ')"
        }
      }
    }

    if (-not $stepFailed) {
      $chk = Test-LiveEngineUnchanged -Before $engine
      if ($chk.unchanged) { Ok "nothing restarted — $($chk.detail)" }
      else { $stepFailed = "the live engine CHANGED during this switch: $($chk.detail)" }
    }
  }

    # ── FIX 3 (cont.) — the post-state record ───────────────────────────────────────────────────────
  if (-not $stepFailed) {
    Head 'STEP 5 — record the post-state (what a later -Rollback needs to undo without guessing)'
    $written = New-Object System.Collections.Generic.List[object]
    $written.Add([pscustomobject]@{ path = $WindowsJson; role = 'launcher config'; sha256After = (Get-Sha $WindowsJson); sha256Before = $preRead.launcherConfig.sha256Before })
    $written.Add([pscustomobject]@{ path = $PinPath; role = 'pin'; sha256After = (Get-Sha $PinPath); sha256Before = $preRead.pin.sha256Before })
    foreach ($r in @($preRead.recordedConfigFiles)) {
      $dest = Join-Path $TargetHome ($r.rel -replace '/', '\')
      $written.Add([pscustomobject]@{ path = $dest; role = 'config'; sha256After = (Get-Sha $dest); sha256Before = $r.sha256 })
    }
    $baks = New-Object System.Collections.Generic.List[object]
    foreach ($cand in @(Get-ChildItem -LiteralPath (Split-Path -Parent $WindowsJson) -File -Filter "$(Split-Path -Leaf $WindowsJson).bak-dsh-update-*" -ErrorAction SilentlyContinue)) {
      $baks.Add([pscustomobject]@{ path = $cand.FullName; bytes = $cand.Length; sha256 = (Get-Sha $cand.FullName); note = 'created by promote; never deleted by this script' })
    }
    $post = [ordered]@{
      schemaVersion = 1
      mode = 'switch'
      createdAt = (Get-IsoNow)
      host = $env:COMPUTERNAME
      preStateDir = $preDir
      fromVersion = $preRead.fromVersion
      toVersion = $Version
      dshInstall = (Read-Json $WindowsJson).dshInstall
      expectRoot = $expectRoot
      targetHome = $TargetHome
      targetIsLive = $TargetIsLive
      engine = [ordered]@{ pid = $engine.pid; startedAt = $engine.startedAt; version = $engine.version; unchanged = $true }
      verification = $(if ($InjectVerification) { 'SKIPPED by -InjectVerification — this record does NOT claim the outcome was verified' } else { 'passed in step 4' })
      sync = [ordered]@{ exitCode = $syncCode; out = 'sync.out.txt'; err = 'sync.err.txt'
                         presetsApplied = $true; profilesApplied = $true }
      written = $written.ToArray()
      backupsCreated = $baks.ToArray()
    }
    Write-Json -Path (Join-Path $preDir 'POST-STATE.json') -Object $post
    Ok "post-state written: $preDir\POST-STATE.json"
    # `.Count` directly: `@(<a generic List>)` also throws "Argument types do not match" in
    # PowerShell 7 (measured here, 2026-09-28 — it threw AFTER the post-state was written).
    Say "  files recorded: $($written.Count)   backups promote made (never deleted): $($baks.Count)"
    foreach ($w in $written) { Say ("    {0}`n      after  {1}`n      before {2}" -f $w.path, $w.sha256After, $w.sha256Before) }
  }
} catch {
  # A thrown error inside the write sequence is handled like a failed step: it must reach the SAME
  # roll-back, not escape past it. The previous geometry (exit inside the try) leaked the lock and
  # skipped every repair; this cannot.
  $hardStop = "an unexpected error was thrown inside the write sequence: $($_.Exception.Message)"
  Say ''
  Say "  !! $hardStop"
  Say '     This is handled exactly like a failed step: nothing is left half-applied on purpose.'
} finally {
  if ($lockPath) { Exit-SwitchLock -LockPath $lockPath }
}

if ($hardStop) { $stepFailed = $hardStop }

# ── FIX 2 (cont.) — did a sync tick land mid-sequence? ───────────────────────────────────────────
Head 'STEP 6 — read the sync task AGAIN: did a tick land mid-sequence?'
$taskAfter = Get-SyncTaskState
if ($InjectLastRunAfter -and $taskBefore.injected) {
  $taskAfter = [pscustomobject]@{ readable = $true; injected = $true; taskName = $SyncTaskName
    lastRunTime = (Get-DtOrNull $InjectLastRunAfter); nextRunTime = $taskAfter.nextRunTime
    lastTaskResult = $null; note = "INJECTED post-write LastRunTime: $InjectLastRunAfter" }
  Warn "INJECTED post-write LastRunTime: $InjectLastRunAfter (simulating a tick that landed mid-sequence)"
}
Show-SyncTaskState -S $taskAfter
$tickRan = $false
if ($taskBefore.readable -and $taskAfter.readable -and $taskBefore.lastRunTime -and $taskAfter.lastRunTime) {
  $b = ([datetime]$taskBefore.lastRunTime).ToUniversalTime()
  $a = ([datetime]$taskAfter.lastRunTime).ToUniversalTime()
  if ($a -ne $b) {
    $tickRan = $true
    Say ''
    Warn "A SYNC TICK RAN DURING THIS SWITCH: LastRunTime moved from $($b.ToString('o')) to $($a.ToString('o'))."
    Warn 'That is exactly the overlap this guard exists to prevent. The switch is NOT accepted on trust.'
    Say '  Re-verifying the live config against the running engine now:'
    $recheck = New-Object System.Collections.Generic.List[string]
    $lcRe = Read-Json $WindowsJson
    $instRe = if ($lcRe -and $lcRe.PSObject.Properties.Name.Contains('dshInstall') -and $lcRe.dshInstall) { [string]$lcRe.dshInstall } else { $null }
    $badRe = 0
    # The re-verify runs even when an EARLIER check already failed, so the tick always gets its own
    # plain verdict printed. An earlier failure must not be allowed to hide what the tick did: those are
    # two different facts and both belong in the record.
    $livePresetsRe = @(Get-ChildItem -LiteralPath (Join-Path $TargetHome '.agent-presets') -Directory -ErrorAction SilentlyContinue |
      ForEach-Object { Join-Path $_.FullName 'agent.cordis.yml' } | Where-Object { Test-Path -LiteralPath $_ })
    foreach ($f in $livePresetsRe) {
      $n = Count-Pattern -Path $f -Pattern $NEW_PTC; $o = Count-Pattern -Path $f -Pattern $OLD_PTC
      if (-not ($n -gt 0 -and $o -eq 0)) { $badRe++; $recheck.Add("NOT consistent: $f (names-new=$n, names-removed=$o)") }
    }
    $syncRe = [string](Get-Content -LiteralPath (Join-Path $preDir 'sync.out.txt') -Raw -ErrorAction SilentlyContinue)
    if ($syncRe -notmatch '(?m)^\s*profiles: version check passed') { $badRe++; $recheck.Add('sync did not report `profiles: version check passed`') }
    if (-not $instRe) { $badRe++; $recheck.Add('dshInstall is absent') }
    foreach ($l in $recheck) { Warn $l }
    Say ''
    if ($badRe -eq 0) {
      Say '  TRUSTWORTHY: a tick ran, but the live config still resolves to the new names and dshInstall is'
      Say '  still the new prefix. The tick observed the same engine this switch promoted to, so it applied'
      Say '  the same config rather than fighting it. Read the sync output above before relying on this.'
    } else {
      Say '  NOT TRUSTWORTHY: a tick ran mid-sequence and the live config does NOT match the promoted'
      Say '  engine. Rolling back rather than reporting a success nobody can stand behind.'
      if (-not $stepFailed) {
        $stepFailed = 'a sync tick landed mid-sequence and the live config no longer matches the promoted engine'
      } else {
        Say "  (the switch was already failing for another reason: $stepFailed)"
      }
    }
  } else {
    Ok "LastRunTime did NOT move ($($b.ToString('o')) before and after) — no tick ran inside this switch"
  }
} else {
  Warn "the tick comparison needs a readable LastRunTime before and after; $(if (-not $taskBefore.readable) { 'the BEFORE reading failed' } else { 'one of them carried no LastRunTime' }) — so this switch cannot claim no tick ran"
}

# ── failure: roll back automatically ─────────────────────────────────────────────────────────────
# ONE exit path for every kind of failure past the gate: a step that failed, a thrown error, a sync
# tick that landed mid-sequence, or a pre-state that could not be read. A failed switch never leaves
# the engine and the config disagreeing with each other.
if ($stepFailed) {
  Head 'FAILURE — rolling back automatically'
  Say "  reason: $stepFailed"
  Say ''
  Say '  FIX 1 IN ACTION: this restores the engine pin AND the config, and re-hashes every restored'
  Say '  file against the value recorded before the switch. The previous version restored only the'
  Say '  engine and re-ran sync.py, which then SKIPPED the coupled steps and left the new-name config'
  Say '  behind — the incident this roll-back exists to make impossible.'
  Say ''
  $quarantineRoot = Join-Path $preDir 'quarantine'
  $preReadable = ($preDir -and (Test-Path -LiteralPath (Join-Path $preDir 'PRE-STATE.json')))
  $r = $null
  if ($preReadable) {
    $r = Restore-FromRecord -PreDir $preDir -QuarantineRoot $quarantineRoot
  } else {
    Say '  THE PRE-STATE ITSELF COULD NOT BE READ, so there is nothing to restore FROM. Nothing is'
    Say "  deleted and nothing was promoted past the write that failed: $preDir"
    $r = [pscustomobject]@{ ok = $false; restored = @(); movedAside = @(); names = @()
      problems = @("$preDir\PRE-STATE.json is absent or unreadable — manual attention required") }
  }
  foreach ($line in $r.restored)   { Ok   "restored  $line" }
  foreach ($line in $r.movedAside) { Warn $line }
  foreach ($p in $r.problems)      { Bad  $p }
  Say ''
  foreach ($n in $r.names) { Say "  $n" }
  Say ''
  if ($r.ok) {
    Say '  RESTORED: pin.json, the launcher config and every recorded config file are back to the exact'
    Say '  sha256 values recorded in step 1, and the re-hash above is the proof. THE SWITCH IS NOT APPLIED.'
    if ($promoteCode -ne 0) {
      Say '  Note: promote itself refused, so it wrote nothing beyond what is listed; this restore re-wrote'
      Say '  the same bytes it recorded, and the hashes above are the proof that nothing was left behind.'
    }
    if ($promoteCode -eq 0 -and -not (Test-Path -LiteralPath (Join-Path $preDir 'promote.out.txt'))) {
      Say '  Note: promote NEVER RAN — the failure happened before step 2, so no engine pin and no launcher'
      Say '  knob were ever written, and the restore above re-wrote the same bytes it recorded.'
    }
    Say "  Backups the pipeline made were NOT deleted — look beside $WindowsJson for a"
    Say '  .bak-dsh-update-* sibling, and beside the live preset/profile files for .bak-* siblings.'
    $chk = Test-LiveEngineUnchanged -Before $engine
    if ($chk.unchanged) { Ok "the engine was not disturbed — $($chk.detail)" }
    else { Warn "the engine changed during the failed switch: $($chk.detail)" }
    Say ''
    Say "  NEXT: read $preDir\step output before trying again."
    exit 4
  } else {
    Say '  THE AUTOMATIC ROLL-BACK DID NOT FULLY VERIFY. Manual attention is required.'
    if (-not $wroteAnything) { Say '  State changed before the first write (see the error above) — NOTHING was promoted.' }
    Say "  The pre-state holds every original file: $preDir"
    $chk = Test-LiveEngineUnchanged -Before $engine
    if ($chk.unchanged) { Ok "the engine was not disturbed — $($chk.detail)" }
    else { Warn "the engine changed during the failed switch: $($chk.detail)" }
    exit 5
  }
}

# ── success ──────────────────────────────────────────────────────────────────────────────────────
Head 'THE SWITCH IS APPLIED'
Say "  pin         : $($pin.version) -> $Version"
Say "  dshInstall  : $((Read-Json $WindowsJson).dshInstall)"
Say '  config      : the preset and profile steps of sync.py RAN (version check passed), they were not skipped'
Say "  engine      : NOT restarted — pid $($engine.pid), started $($engine.startedAt), still serving port $($engine.port)"
Say "  pre-state   : $preDir"
Say "  post-state  : $preDir\POST-STATE.json"
Say ''
Say 'NEXT, IN PLAIN WORDS'
Say '  1. THE CHANGE LANDS AT THE NEXT BOOT. This script did not restart anything and cannot: a running'
Say '     engine serves the session that ran this, so restarting it from here would kill that session.'
Say '     The next engine start — by a human, or by a reboot — picks up the new pin.'
Say "  2. UNTIL THAT BOOT the running engine is still $($engine.version), while the config on disk has"
Say '     already moved to the 0.1.7 names. Existing sessions keep working, but a NEW SESSION started on'
Say '     the CURRENTLY RUNNING engine may fail to mount its preset. That window is the cost of the'
Say '     switch, and it is exactly why the two halves are one operation.'
Say '  3. AFTER the first boot on the new engine, verify it — an unverified first boot is not an upgrade:'
Say '       - the engine serves, and its reported version is the new one'
Say '       - a NEW session starts and its preset mounts (the failure this whole switch exists to prevent)'
Say '       - a session from before the switch still opens'
Say '  4. TO GO BACK:  pwsh -File switch-engine.ps1 -Rollback -IUnderstandThisWritesTheLiveHome'
Say '     That restores the pin, the launcher knob and every recorded config file (re-hashing each one),'
Say '     cross-checks each against POST-STATE.json, and MOVES any session.v4.jsonl.zstd written since'
Say '     into a quarantine directory — never deletes it. Sessions WRITTEN by the new engine cannot be'
Say '     read by the old one: that is the one-way door G8 reported, and no roll-back can undo it.'
exit 0