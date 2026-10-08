# staged-boot.ps1 — boot a CANDIDATE engine against an ISOLATED home and prove it serves.
#
# WHY THIS EXISTS
#
# Every other guard in this pipeline is static: it reads manifests, composes a config tree, or
# compares files. None of them proves that the engine actually STARTS and SERVES with a given config,
# and the two most expensive failures this deployment has had were both invisible to static checks —
# a preset row that composes fine and fails at mount, and a config the engine accepts at dump time
# and rejects at boot.
#
# This is the closest thing to "the first boot on the new engine" that can be done WITHOUT touching
# the live engine: point a candidate binary at an isolated home, on a spare port, and see whether it
# answers.
#
# IT IS DELIBERATELY PARANOID, because it starts a process:
#   * it refuses to run if the live port (3099) is targeted;
#   * it refuses to run if anything is already listening on the port it wants;
#   * it records the exact pid it started and kills ONLY that pid, with /T;
#   * it verifies the port is free again afterwards, and says so either way;
#   * it never touches the live DSH home and never stops an engine it did not start.
#
# USAGE
#   pwsh -File tools/staged-boot.ps1 -EngineBin <candidate bin.js> -StagedHome <dir> [-Port 3417]
#                                    [-TimeoutSec 240]
#
# EXIT: 0 = served; 1 = did not serve (with the engine's own words); 2 = refused before starting.

param(
  [Parameter(Mandatory = $true)][string]$EngineBin,
  [Parameter(Mandatory = $true)][string]$StagedHome,
  [int]$Port = 3417,
  [int]$TimeoutSec = 240,
  # How long to let the engine run AFTER it starts answering, before killing it.
  #
  # WHY THIS DEFAULTS TO MORE THAN ZERO. Some engine work happens after the server is up: `dsh-settings`
  # imports the legacy `settings.yaml` into the active profile from a `ctx.root.loader.await().then(...)`
  # continuation, i.e. only once the loader has settled. Killing on the first successful poll therefore
  # tears the process down mid-import -- and that import renames the document BEFORE its first write,
  # "so a partial import never repeats". Measured 2026-09-28: a boot killed 2.8 s after serving left
  # every settings section present ONLY in `settings.yaml.imported`, with nothing imported and nothing
  # logged. That is a real finding about the engine AND a real trap for this harness, so the default is
  # a settle window rather than an immediate kill.
  [int]$SettleSec = 8,
  [string]$LogDir = "$env:TEMP\dsh-staged-boot-logs"
)

$ErrorActionPreference = 'Continue'

function Refuse([string]$why) {
  Write-Host "staged-boot: REFUSED — $why"
  Write-Host "             nothing was started."
  exit 2
}

# ── preconditions ────────────────────────────────────────────────────────────────────────────────
if ($Port -eq 3099) { Refuse '3099 is the LIVE engine port. This tool exists precisely to avoid touching it.' }
if (-not (Test-Path $EngineBin)) { Refuse "candidate engine not found: $EngineBin" }
if (-not (Test-Path $StagedHome)) { Refuse "staged home not found: $StagedHome" }
if (-not (Test-Path (Join-Path $StagedHome 'profiles\web'))) {
  Refuse "the staged home has no profiles\web, so there is no web profile to boot: $StagedHome"
}

$liveHome = Join-Path $env:USERPROFILE '.dsh'
if ((Resolve-Path $StagedHome).Path -eq (Resolve-Path $liveHome -ErrorAction SilentlyContinue).Path) {
  Refuse "StagedHome IS the live DSH home. This tool must never boot a candidate against live state."
}

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) { Refuse "port $Port is already in use (pid $($busy[0].OwningProcess)) — pick another" }

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$outLog = Join-Path $LogDir "staged-boot-$stamp.out.txt"
$errLog = Join-Path $LogDir "staged-boot-$stamp.err.txt"

# Record what the LIVE engine is, so we can prove afterwards that we did not disturb it.
$liveBefore = @(Get-CimInstance Win32_Process -Filter "Name like '%node%'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match '3099' } |
  Select-Object ProcessId, CreationDate)

Write-Host "staged-boot: engine   $EngineBin"
Write-Host "staged-boot: home     $StagedHome"
Write-Host "staged-boot: port     $Port"
Write-Host "staged-boot: live engine before: $(if ($liveBefore) { "pid $($liveBefore[0].ProcessId) since $($liveBefore[0].CreationDate)" } else { 'NONE RUNNING' })"
Write-Host ''

# ── start ────────────────────────────────────────────────────────────────────────────────────────
$env:DSH_HOME = $StagedHome
$proc = Start-Process -FilePath (Get-Command node).Source `
  -ArgumentList @($EngineBin, 'web', '--port', "$Port", '--no-open') `
  -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
  -PassThru -NoNewWindow
$pid2 = $proc.Id
Write-Host "staged-boot: started pid $pid2 — polling http://127.0.0.1:$Port/ for up to ${TimeoutSec}s"

# ── poll ─────────────────────────────────────────────────────────────────────────────────────────
$served = $false
$status = $null
$sw = [Diagnostics.Stopwatch]::StartNew()
$lastErr = ''
while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
  if ($proc.HasExited) { break }
  try {
    # -SkipHttpErrorCheck: a 401 or 403 from the web app is a CORRECT answer. The token gate and the
    # `/api` trusted-hosts fence refuse an unauthenticated request while the server is plainly UP.
    # An earlier version of this tool demanded 2xx and therefore scored a FULLY STARTED server as
    # "did not serve" (measured 2026-09-28: `dsh web: http://127.0.0.1:3417/?token=…` alongside
    # `served: False`). A guard that reports health as failure is as dangerous as one that does the
    # reverse, so any HTTP status at all counts as "listening".
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 5 -UseBasicParsing -SkipHttpErrorCheck -ErrorAction Stop
    $status = [int]$r.StatusCode
    $served = $true
    break
  } catch { $lastErr = $_.Exception.Message }
  Start-Sleep -Milliseconds 700
}
$sw.Stop()
# Report the time to FIRST ANSWER separately from the total. An earlier version printed only this
# number while a settle window ran afterwards, so a run that actually occupied 47 s reported
# "elapsed 2.8 s" -- a reading that was true of one phase and misleading about the run.
$servedAtSec = $sw.Elapsed.TotalSeconds
$exited = $proc.HasExited
$exitCode = if ($exited) { $proc.ExitCode } else { $null }

# ── settle, then stop ONLY what we started ───────────────────────────────────────────────────────
if ($served -and $SettleSec -gt 0 -and -not $proc.HasExited) {
  Write-Host "staged-boot: serving at $([math]::Round($servedAtSec,1))s — letting the engine run ${SettleSec}s so post-boot work can finish"
  Start-Sleep -Seconds $SettleSec
  $exited = $proc.HasExited
  $exitCode = if ($exited) { $proc.ExitCode } else { $null }
}
$sw.Stop()
if (-not $exited) {
  Write-Host "staged-boot: killing pid $pid2 (the only process this tool started)"
  & taskkill /PID $pid2 /T /F 2>&1 | Out-Null
  Start-Sleep -Milliseconds 900
}
$portAfter = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$liveAfter = @(Get-CimInstance Win32_Process -Filter "Name like '%node%'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match '3099' } |
  Select-Object ProcessId, CreationDate)

# ── report ───────────────────────────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host ("  served            : {0}{1}" -f $served, $(if ($status) { " (HTTP $status — a 401/403 is the fence answering, i.e. it is UP)" } else { '' }))
Write-Host ("  served at         : {0:N1} s  (time to first HTTP answer)" -f $servedAtSec)
Write-Host ("  total run         : {0:N1} s  (includes the {1}s settle window)" -f $sw.Elapsed.TotalSeconds, $SettleSec)
Write-Host ("  process exited    : {0}{1}" -f $exited, $(if ($exited) { " (exit $exitCode)" } else { '' }))
Write-Host ("  port $Port free after: {0}" -f (-not $portAfter))
Write-Host ("  live engine after : {0}" -f $(if ($liveAfter) { "pid $($liveAfter[0].ProcessId) since $($liveAfter[0].CreationDate)" } else { 'NONE RUNNING' }))
Write-Host ("  stdout            : {0}" -f $outLog)
Write-Host ("  stderr            : {0}" -f $errLog)

$liveUntouched = ($liveBefore.Count -eq $liveAfter.Count) -and
  (@($liveBefore | ForEach-Object { $_.ProcessId }) -join ',') -eq (@($liveAfter | ForEach-Object { $_.ProcessId }) -join ',')

if (-not $liveUntouched) {
  Write-Host ''
  Write-Host '  *** WARNING: the LIVE engine process set CHANGED during this run. That was not this tool''s'
  Write-Host '  *** doing (it killed only the pid it started), but it must be investigated before trusting'
  Write-Host '  *** anything else in this session.'
}

$errTail = @(Get-Content $errLog -ErrorAction SilentlyContinue | Select-Object -Last 12)
if (-not $served) {
  Write-Host ''
  Write-Host '  REFUSAL IS A CORRECT ANSWER: the candidate did not serve. Its own words:'
  if ($errTail.Count -eq 0) { Write-Host '    (stderr was empty — check the stdout log)' }
  foreach ($l in $errTail) { Write-Host "    $l" }
  if ($lastErr) { Write-Host "    (last poll error: $lastErr)" }
}

# ── an engine that SERVES with an entry that did not activate is NOT a pass ──────────────────────
#
# "It booted" and "everything mounted and activated" are different claims, and this deployment has
# been bitten by the gap: a row can compose, load, and still fail to activate, leaving the engine
# healthy-looking with a capability silently absent. The engine says so in one line --
#   `dsh: warning: 1 entry did not activate`  /  `<name> (dsh-plugin-cost/guard): failed to import`
# -- so that line is treated as a FAILURE of this guard, not as a warning to scroll past.
$actErr = @(Select-String -Path $errLog -Pattern 'did not activate|failed to import' -ErrorAction SilentlyContinue)
$entryFailure = $actErr.Count -gt 0

Write-Host ''
Write-Host ("  entries activated : {0}" -f $(if ($entryFailure) { 'NO — an entry failed to activate (see below)' } else { 'all (no activation warning)' }))
if ($entryFailure) {
  Write-Host ''
  Write-Host '  *** This is the mounted-but-broken class: the engine is healthy and a capability is missing.'
  foreach ($l in $actErr) { Write-Host ("    " + $l.Line.Trim()) }
  Write-Host '  *** Before blaming the candidate, check the STAGED HOME: a plugin that resolves a module'
  Write-Host '  *** through `<DSH_HOME>/profiles/node_modules` (anchored at profiles/web/package.json)'
  Write-Host '  *** fails here if that directory was not staged, which is an artefact of the harness, not a'
  Write-Host '  *** finding about the engine. Measured 2026-09-28: dsh-plugin-cost/guard failed exactly this'
  Write-Host '  *** way on an incomplete staging and imports cleanly once the anchor exists.'
}

if (-not $served) { exit 1 }
if ($entryFailure) { exit 3 }
if (-not $liveUntouched) { exit 4 }
exit 0
