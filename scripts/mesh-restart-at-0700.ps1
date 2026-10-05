<#
.SYNOPSIS
The 07:00 restart window: gate on the owner's work, converge the tree, install the mesh provider and
the mesh HTTP route, restart the engine ONE time by the supported path, and verify -- or refuse and
do nothing.

WHY THIS EXISTS, AND WHY IT REFUSES
Mounting a bundle in a running engine is impossible (P210), so the remote subagent provider and the
`POST /mesh/run` route can only arrive with a restart -- and a restart ends every live session in
that engine. The owner runs his own fleet through the night, so the only acceptable behaviour is:
take the window only when nothing of his is running, decide that from EVIDENCE rather than a clock,
and say exactly what was found when it refuses.

THE ORDER, AND WHY IT IS THIS ORDER
  1. GATE. Two independent readings: this engine's own `/healthz` (authenticated -- the cookie is
     minted from the engine's launch line in its launcher log, which is the only supported way) and
     the phone gate's `/mesh/capacity` on loopback. Any `running` session, or a non-zero
     `agentLoopsRunning`, refuses. Session ids AND titles come from `/api/session/list`.
  2. SNAPSHOT. What the restart would end: pid, uptime, DSH_HOME, every session with its title, the
     persisted session-file count, and the established connections on both ports.
  3. JOURNAL CONVERGE. The tree is diverged: untracked entries whose ids `origin/master` has taken,
     plus tracked files dirty in a way `pull --ff-only` refuses. Each colliding entry is re-filed
     through `journal.py append --body-file` (collision-safe: it bumps with an alias rather than
     overwriting) and the ORIGINAL is removed only after its append succeeded. Then the pull must
     succeed. Nothing here is forced.
  4. INSTALL. `scripts/mesh-provider-install.ps1 -Check` must pass, and `--dump-config` must compose,
     BEFORE anything restarts.
  5. RESTART. `multi-window/dshw.ps1 restart` -- the machine's own supported path (it stops the
     server tree and starts it again through Task Scheduler, same port, same profile, same
     DSH_HOME, and it refuses to leave two engines on one home). Never a hand-rolled Start-Process.
  6. VERIFY, and assert the provider rather than assume it. See `Assert-ProviderPresent`.

SAFE TO RUN TWICE: a lock file marks a run in flight, every write keeps a `.bak`, and the journal
re-file is idempotent (an already-present id is aliased, not duplicated). A second run after a
successful one finds the gate closed (there is nothing of the owner's running) and re-verifies.

USAGE
    pwsh scripts/mesh-restart-at-0700.ps1                    # the real thing
    pwsh scripts/mesh-restart-at-0700.ps1 -DryRun            # gate + snapshot + checks, no writes, no restart
    pwsh scripts/mesh-restart-at-0700.ps1 -SkipJournal       # a human's override (see 71 4.7)
    pwsh scripts/mesh-restart-at-0700.ps1 -ForceGate         # human-only: restart with sessions live
    pwsh scripts/mesh-restart-at-0700.ps1 -ProbeProvider:$false   # skip the one-session assertion

EXIT CODES: 0 the run did what the gate allowed (including a DEFERRAL, which writes no change) -
            1 a step before the restart failed, so nothing was restarted - 2 it could not even read
            the machine's state (and restarted nothing).
#>
[CmdletBinding()]
param(
    [int]$Port = 3099,
    [int]$GatePort = 3086,
    [string]$Repo,
    # How long to wait for the restarted engine to answer, and for a session probe to settle.
    [int]$WaitSeconds = 300,
    [int]$ProbeWaitSeconds = 180,
    # Gate + snapshot + the read-only checks, then stop. Writes nothing and restarts nothing.
    [switch]$DryRun,
    # Skip the journal converge step (the tree stays as it is; the pull is not attempted).
    [switch]$SkipJournal,
    # Restart even when the gate sees live work. A HUMAN's switch; the scheduled task never passes it.
    [switch]$ForceGate,
    # Do not re-verify the mesh provider install before restarting.
    [switch]$SkipInstall,
    # Do not ask a live session to name its subagent tools (the provider assertion).
    [switch]$ProbeProvider,
    # Skip the commit/push of the converged tree.
    [switch]$SkipPush
)

$ErrorActionPreference = 'Continue'

$REPO = if ($Repo) { $Repo } else { Split-Path -Parent $PSScriptRoot }
$checkout = Join-Path $env:USERPROFILE 'code\harness-config'
if ($REPO -like "$env:TEMP*" -and (Test-Path (Join-Path $checkout 'profiles'))) { $REPO = $checkout }
$env:DSH_HOME = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runDir = Join-Path $env:DSH_HOME "mesh\restart-0700\$stamp"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$runLog = Join-Path $runDir 'run.log'
$lockPath = Join-Path (Join-Path $env:DSH_HOME 'mesh\restart-0700') '.lock'

$report = [ordered]@{
    startedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    machine = $env:COMPUTERNAME
    dshHome = $env:DSH_HOME
    port = $Port
    gatePort = $GatePort
    dryRun = [bool]$DryRun
    steps = [ordered]@{}
    changes = @()
    problems = @()
}
$failures = @()

function Log([string]$text) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $text
    Write-Host $line
    Add-Content -LiteralPath $runLog -Value $line -ErrorAction SilentlyContinue
}
function Step([string]$text) { Write-Host ''; Log $text }
function Change([string]$text) { $script:report.changes += $text; Log "CHANGED: $text" }
function Problem([string]$text) {
    $script:report.problems += $text
    $script:failures += $text
    Log "PROBLEM: $text"
}
function SaveReport([string]$name) {
    $path = Join-Path $runDir $name
    # A plain conversion, no depth games: the report is scalars, arrays and small objects by design.
    $script:report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding utf8
    return $path
}

# ── locks: one run at a time ──────────────────────────────────────────────────────────────────
if (Test-Path -LiteralPath $lockPath) {
    $held = Get-Content -LiteralPath $lockPath -Raw -ErrorAction SilentlyContinue
    $heldPid = ($held -split "`n" | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1)
    if ($heldPid -and (Get-Process -Id ([int]$heldPid) -ErrorAction SilentlyContinue)) {
        Log "another run holds the lock (pid $heldPid) -- exiting without doing anything"
        exit 0
    }
}
Set-Content -LiteralPath $lockPath -Value "$PID`n$stamp`n" -Encoding utf8
Log "run dir   $runDir"
Log "repo      $REPO"

# ── the engine's own facts ────────────────────────────────────────────────────────────────────
function Get-EngineToken([int]$enginePort) {
    # The ONLY supported way to authenticate to an engine is a cookie minted from its per-process
    # launch token, and that token exists only in the launcher's log (dsh-client-connection mints it
    # per process and never persists it -- 66-dsh-remote-capability.md 2c). The multi-window launcher
    # writes `<port>.log` plus `<port>-<stamp>.log`; the newest that still has a token is the live one.
    $dirs = @((Join-Path $env:DSH_HOME 'multi-window\logs'))
    foreach ($dir in $dirs) {
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        $candidates = @()
        foreach ($name in @("$enginePort.log")) {
            $p = Join-Path $dir $name
            if (Test-Path -LiteralPath $p) { $candidates += Get-Item -LiteralPath $p }
        }
        $candidates += @(Get-ChildItem -LiteralPath $dir -Filter "$enginePort-*.log" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 5)
        foreach ($f in $candidates) {
            $m = [regex]::Matches((Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue), 'token=([A-Za-z0-9_-]+)')
            if ($m.Count -gt 0) { return [pscustomobject]@{ token = $m[$m.Count - 1].Groups[1].Value; file = $f.FullName } }
        }
    }
    return $null
}
function New-EngineCookie([int]$enginePort, [string]$token) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$enginePort/?token=$token" -MaximumRedirection 0 -UseBasicParsing -SkipHttpErrorCheck -ErrorAction SilentlyContinue
        $set = @($r.Headers['Set-Cookie']) | Select-Object -First 1
        if ($set) { return ($set -split ';')[0] }
    } catch { }
    return $null
}
function Invoke-EngineRpc([int]$enginePort, [string]$cookie, [string]$method, [hashtable]$arguments) {
    # `$args` is PowerShell's automatic argument array, and naming a parameter that is how a hashtable
    # became System.Object[] at the call site (measured: "Cannot convert the System.Object[] value
    # ... to type System.Collections.Hashtable" at the session/list call). It is `$arguments` now.
    $body = @{ type = 'client-request'; rpcId = [guid]::NewGuid().ToString(); method = $method; payload = @{ args = $arguments } } |
        ConvertTo-Json -Depth 12 -Compress
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$enginePort/api/$method" -Method POST `
            -Headers @{ Cookie = $cookie; 'content-type' = 'application/json' } -Body $body `
            -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 60
        return ($r.Content | ConvertFrom-Json)
    } catch { return $null }
}
function Get-EngineHealth([int]$enginePort, [string]$cookie) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$enginePort/healthz" -Headers @{ Cookie = $cookie } `
            -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 30
        if ($r.StatusCode -ne 200) { return $null }
        return ($r.Content | ConvertFrom-Json)
    } catch { return $null }
}
function Get-SessionFiles {
    $root = Join-Path $env:DSH_HOME 'sessions'
    if (-not (Test-Path -LiteralPath $root)) { return 0 }
    return @(Get-ChildItem -LiteralPath $root -Recurse -File -Filter 'session.v3.jsonl.zstd' -ErrorAction SilentlyContinue).Count
}

# ═══ STEP 1 + 2: EVIDENCE, GATE, SNAPSHOT ═════════════════════════════════════════════════════
Step 'STEP 1: the gate -- is any of the owner''s work running?'
$t = Get-EngineToken $Port
$evidence = [ordered]@{ tokenFile = if ($t) { $t.file } else { $null } }
if (-not $t) {
    Problem "no launch token in any log under $env:DSH_HOME\multi-window\logs -- cannot authenticate to :$Port, so the gate has NO evidence"
    $report.steps.gate = $evidence
    SaveReport 'gate.json' | Out-Null
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Log 'DEFERRED: no evidence about the owner''s work, so nothing was restarted.'
    exit 0
}
$cookie = New-EngineCookie $Port $t.token
if (-not $cookie) {
    Problem 'could not mint a cookie from the launch token -- no evidence'
    SaveReport 'gate.json' | Out-Null
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Log 'DEFERRED: cannot authenticate to the engine, so nothing was restarted.'
    exit 0
}
$health = Get-EngineHealth $Port $cookie
if (-not $health) {
    Problem "GET /healthz did not answer 200 with a valid cookie -- no evidence"
    SaveReport 'gate.json' | Out-Null
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Log 'DEFERRED: the engine did not answer, so nothing was restarted.'
    exit 0
}
$evidence.enginePid = $health.identity.pid
$evidence.engineUptimeMs = $health.identity.uptimeMs
$evidence.engineDshHome = $health.identity.env.dshHome
$evidence.sessionsLive = $health.sessions.live
$evidence.agentLoopsRunning = $health.sessions.agentLoopsRunning
$evidence.runningIds = @($health.sessions.list | Where-Object { $_.status -eq 'running' } | ForEach-Object { $_.id })

# Titles: /api/session/list is the only surface that carries them.
$list = Invoke-EngineRpc $Port $cookie 'session/list' @{ _request = @{} }
$items = @()
if ($list -and $list.result.ok) { $items = @($list.result.value.items) }
$evidence.sessionListItems = $items.Count
$titles = @{}
$labels = @{}
$runningRows = @()
foreach ($row in $items) {
    $id = [string]$row.sessionId
    $v = $row.projections.values
    $titles[$id] = [string]$v.title
    if ($v.subagent -and $v.subagent.label) { $labels[$id] = [string]$v.subagent.label }
    if ($row.running) {
        $runningRows += [pscustomobject]@{
            id = $id; title = [string]$v.title; origin = [string]$row.origin
            label = if ($v.subagent) { [string]$v.subagent.label } else { '' }
            updatedAt = $row.updatedAt
        }
    }
}
# An id in the census with no row in the list is still running work: count it.
$runningIdsFromList = @($runningRows | ForEach-Object { $_.id })
$runningOnlyInCensus = @($evidence.runningIds | Where-Object { $runningIdsFromList -notcontains $_ })
$evidence.runningFromList = $runningRows.Count
$evidence.runningFromCensus = $evidence.runningIds.Count

# SECOND, INDEPENDENT SOURCE: the phone gate's own capacity route, answered before sign-in.
try {
    $cap = Invoke-WebRequest -Uri "http://127.0.0.1:$GatePort/mesh/capacity" -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 20
    if ($cap.StatusCode -eq 200) {
        $cj = $cap.Content | ConvertFrom-Json
        $evidence.gateCapacityStatus = 200
        $evidence.gateLoopsRunning = $cj.agents.loopsRunning
        $evidence.gateSessionsLive = $cj.agents.sessionsLive
        $evidence.gateNode = $cj.node
    } else { $evidence.gateCapacityStatus = $cap.StatusCode }
} catch { $evidence.gateCapacityStatus = "ERR: $($_.Exception.Message)" }

# The specific thing to look for, named rather than assumed.
$waze = @($items | Where-Object {
        $v = $_.projections.values
        ([string]$v.title -match '(?i)waze|mdm') -or
        ($v.subagent -and ([string]$v.subagent.label -match '(?i)waze|mdm'))
    } | ForEach-Object { [pscustomobject]@{ id = [string]$_.sessionId; running = [bool]$_.running; title = [string]$_.projections.values.title } })
$evidence.wazeMdmSessions = @($waze)
$report.steps.gate = $evidence

Log "engine pid $($evidence.enginePid), DSH_HOME=$($evidence.engineDshHome), sessions live $($evidence.sessionsLive)"
Log "agentLoopsRunning=$($evidence.agentLoopsRunning)  (gate's own reading: $($evidence.gateLoopsRunning))"
Log "sessions running: census $($evidence.runningFromCensus), /api/session/list $($evidence.runningFromList)"
Log "waze/mdm matches: $($waze.Count)"

$gateOpen = ($evidence.runningFromCensus -eq 0) -and ($evidence.runningFromList -eq 0) -and ($evidence.agentLoopsRunning -eq 0)
$report.gateOpen = $gateOpen

if (-not $gateOpen -and -not $ForceGate) {
    Step 'STEP 1 RESULT: REFUSED'
    Log  "the owner's work is running in this engine, so the restart is DEFERRED:"
    Log  "  - agentLoopsRunning = $($evidence.agentLoopsRunning) (0 means idle)"
    Log  "  - sessions whose public status is running: $($evidence.runningFromCensus)"
    Write-Host ''
    Write-Host 'sessions found running (id / origin / title):' -ForegroundColor Yellow
    foreach ($row in ($runningRows | Sort-Object updatedAt -Descending)) {
        Write-Host ("  {0}  {1,-9} {2}" -f $row.id, $row.origin, $row.title) -ForegroundColor Yellow
        Log ("  RUNNING {0} origin={1} label={2} title={3}" -f $row.id, $row.origin, $row.label, $row.title)
    }
    foreach ($id in $runningOnlyInCensus) { Write-Host "  $id  (running in the census, no list row)" -ForegroundColor Yellow; Log "  RUNNING $id (census only)" }
    if ($waze.Count -gt 0) {
        Write-Host ''
        Write-Host 'waze/mdm work found (this is what the gate exists for):' -ForegroundColor Yellow
        foreach ($w in $waze) { Write-Host ("  {0}  running={1}  {2}" -f $w.id, $w.running, $w.title) -ForegroundColor Yellow; Log ("  WAZEMDM {0} running={1} title={2}" -f $w.id, $w.running, $w.title) }
    } else {
        Log '  (no session title or subagent label contains "waze" or "mdm")'
    }
    SaveReport 'gate-refused.json' | Out-Null
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host "mesh-restart-at-0700: DEFERRED -- $($evidence.runningFromCensus) running session(s), $($evidence.agentLoopsRunning) agent loop(s); nothing was restarted." -ForegroundColor Yellow
    Log 'DEFERRED: nothing was written and nothing was restarted.'
    exit 0
}
if (-not $gateOpen -and $ForceGate) { Log 'WARNING: the gate is NOT open and -ForceGate was given -- proceeding anyway (human override)' }
if ($gateOpen) { Log 'gate: OPEN -- no session is running and no agent loop is executing' }
else { Log "gate: OVERRIDDEN by -ForceGate -- $($evidence.runningFromCensus) session(s) were running and $($evidence.agentLoopsRunning) agent loop(s) were executing when this began" }

Step 'STEP 2: pre-restart snapshot'
$snapshot = [ordered]@{
    at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    enginePid = $evidence.enginePid
    engineUptimeMs = $evidence.engineUptimeMs
    engineDshHome = $evidence.engineDshHome
    port = $Port
    sessionsLive = $evidence.sessionsLive
    sessionFilesOnDisk = Get-SessionFiles
    sessionListItems = $items.Count
    establishedOnEnginePort = @(Get-NetTCPConnection -LocalPort $Port -State Established -ErrorAction SilentlyContinue).Count
    establishedOnGatePort = @(Get-NetTCPConnection -LocalPort $GatePort -State Established -ErrorAction SilentlyContinue).Count
    listenersOnEnginePort = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count
    sessions = @($items | Sort-Object updatedAt -Descending | Select-Object -First 60 | ForEach-Object {
            [pscustomobject]@{
                id = [string]$_.sessionId; running = [bool]$_.running; origin = [string]$_.origin
                title = [string]$_.projections.values.title
                preset = [string]$_.projections.values.agentPreset
            }
        })
}
$report.steps.snapshot = $snapshot
$snapPath = SaveReport 'pre-restart.json'
Log "snapshot: engine pid $($snapshot.enginePid), $($snapshot.sessionFilesOnDisk) session file(s) on disk, $($snapshot.sessionListItems) session row(s), $($snapshot.listenersOnEnginePort) listener on :$Port"
Log "snapshot written to $snapPath"

# ═══ STEP 3: JOURNAL CONVERGE + PULL ══════════════════════════════════════════════════════════
if (-not $SkipJournal) {
    Step 'STEP 3: converge the tree, then pull (append is collision-safe; the pull is not forced)'
    $journalTool = Join-Path $REPO 'journal\tools\journal.py'
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    $gj = [ordered]@{}

    $fetch = & git -C $REPO fetch origin --quiet 2>&1
    $gj.fetchExit = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) {
        # A FETCH IS A REFRESH, NOT A PREREQUISITE. The blocking set is computed against the LOCAL
        # `origin/master` ref, and the merged state is normally already fetched; refusing the window
        # because another machine is unreachable would be a misattributed blocker. Measured 2026-09-17
        # 00:46Z: `git fetch` from here answered `ssh: connect to host secratary.tail93e6e6.ts.net port
        # 22: Connection timed out` while `origin/master` was already the merged commit locally.
        & git -C $REPO rev-parse --verify --quiet origin/master 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Problem "git fetch failed AND there is no local origin/master to judge against ($($fetch -join ' '))"
        } else {
            $gj.fetchWarning = "fetch failed; judged against the local origin/master, which exists: $($fetch -join ' ')"
            Log "WARNING: git fetch failed, but origin/master resolves locally -- using the local ref: $($fetch -join ' ')"
        }
    } else { Log 'fetch: origin updated' }

    if ($gj.fetchExit -eq 0) {
        # WHICH UNTRACKED ENTRIES ACTUALLY BLOCK THE PULL? The blocking set is not the untracked set:
        # git refuses to overwrite an untracked path that the incoming tree also contains, so the test
        # is `origin/master:<path>` -- nothing else. (Measured by the verifier: the untracked set grew
        # 17 -> 18 while the blocking set stayed at 8.)
        $status = & git -C $REPO status --porcelain -- journal/entries 2>&1
        $untracked = @()
        foreach ($line in $status) {
            if ($line -match '^\?\?\s+(.+)$') { $untracked += ($Matches[1]).Trim() }
        }
        $blocking = @()
        foreach ($rel in $untracked) {
            & git -C $REPO cat-file -e "origin/master:$rel" 2>$null
            if ($LASTEXITCODE -eq 0) { $blocking += $rel }
        }
        $gj.untrackedEntries = $untracked.Count
        $gj.blockingEntries = $blocking
        Log "untracked entries under journal/entries: $($untracked.Count); of those, taken on origin/master: $($blocking.Count)"
        foreach ($b in $blocking) { Log "  blocking: $b" }

        $mapping = @()
        foreach ($rel in $blocking) {
            $abs = Join-Path $REPO ($rel -replace '/', '\')
            $kind = Split-Path (Split-Path $abs -Parent) -Leaf
            $lines = @(Get-Content -LiteralPath $abs -ErrorAction SilentlyContinue)
            if ($lines.Count -eq 0) { Problem "$rel is empty -- not re-filing it"; continue }
            $i = 0
            if ($lines[0] -match '^<!--\s*e:') { $i = 1 }
            $title = ''
            if ($i -lt $lines.Count -and $lines[$i] -match '^#{1,3}\s*(.+)$') {
                $title = $Matches[1]
                $i++
            } elseif ($i -lt $lines.Count -and $lines[$i] -match '^\*\*\s*(.+?)\s*\*\*$') {
                # `lessons` entries carry their title as a bold first line rather than a `##` heading
                # (`**L1848 · …**`), measured 2026-09-17. Without this the re-filed entry gets the
                # fallback title and becomes hard to find in a list.
                $title = ($Matches[1] -replace '^[A-Z]\d+\s*[·\-—]\s*', '')
                $i++
            }
            if (-not $title) { $title = "re-filed from $rel" }
            # The v1 marker line is a FILE header, so it must not travel into the body; the heading is
            # regenerated by `append` from --title. Everything else is content and is kept verbatim.
            $bodyFile = Join-Path $runDir ("refile-" + (Split-Path $abs -Leaf))
            Set-Content -LiteralPath $bodyFile -Value (($lines[$i..($lines.Count - 1)] -join "`n")) -Encoding utf8

            if ($DryRun) {
                Log "  DRY RUN: would re-file $rel (kind $kind, title '$title') through append --body-file"
                $mapping += [pscustomobject]@{ from = (Split-Path $abs -Leaf); to = '(dry run)'; source = $rel }
                continue
            }
            $out = & $python $journalTool append $kind --title $title --body-file $bodyFile --json 2>&1
            $okJson = $null
            try { $okJson = ($out -join "`n" | ConvertFrom-Json) } catch { }
            if ($LASTEXITCODE -ne 0 -or -not $okJson -or -not $okJson.id) {
                Problem "append failed for ${rel}: $((($out -join ' / ')).Substring(0, [Math]::Min(300, (($out -join ' / ')).Length)))"
                continue
            }
            $mapping += [pscustomobject]@{ from = (Split-Path $abs -Leaf); to = [string]$okJson.id; source = $rel; bumpedFrom = [string]$okJson.bumped_from }
            Change "re-filed $rel -> $($okJson.id)$(if ($okJson.bumped_from) { " (id bumped from $($okJson.bumped_from))" })"
            # ONLY NOW, and only this file, and only while it is still untracked.
            & git -C $REPO ls-files --error-unmatch $rel 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { Problem "$rel became tracked while we worked -- NOT removing it"; continue }
            Remove-Item -LiteralPath $abs -Force
            Change "removed the untracked original $rel (its content is now $($okJson.id))"
        }
        $gj.mapping = $mapping
        $report.steps.journal = $gj

        # Tracked files that are dirty in this tree and would be overwritten by the fast-forward.
        $incoming = @(& git -C $REPO diff --name-only HEAD origin/master 2>&1)
        $dirty = @()
        foreach ($line in (& git -C $REPO status --porcelain 2>&1)) {
            if ($line -match '^( M|M |MM)\s+(.+)$') { $dirty += ($Matches[2]).Trim() }
        }
        $trackedBlockers = @($dirty | Where-Object { $incoming -contains $_ })
        $gj.trackedBlockers = $trackedBlockers
        Log "tracked files dirty here that origin/master also changed: $($trackedBlockers.Count) [$($trackedBlockers -join ', ')]"
        foreach ($rel in $trackedBlockers) {
            $abs = Join-Path $REPO ($rel -replace '/', '\')
            $backup = Join-Path $runDir ("local-" + (Split-Path $abs -Leaf))
            Copy-Item -LiteralPath $abs -Destination $backup -Force
            $gj["localCopyOf_" + (Split-Path $abs -Leaf)] = $backup
            # ONLY THREE CLASSES MAY BE DISCARDED HERE, and each has a reason:
            #   journal/index/**            a GENERATED cache -- it rebuilds itself on the next read
            #   journal/state/owner-questions.md  generated by `journal.py questions` from the table
            #   docs/mesh/87-harness-fork.md      the authority's copy is authoritative IF AND ONLY IF
            #                                     it contains every heading ours has (checked below)
            # Anything else that a pull would overwrite is ANOTHER STREAM'S LIVE EDIT, and this script
            # is not entitled to throw it away. It backs the file up, names it, and refuses the restart.
            $isCache = ($rel -like 'journal/index/*') -or ($rel -like 'journal/state/*')
            if ($isCache) {
                if ($DryRun) { Log "  DRY RUN: would restore the generated cache $rel from HEAD"; continue }
                & git -C $REPO checkout -- $rel 2>&1 | Out-Null
                Change "restored the generated cache $rel from HEAD so the fast-forward can proceed (copy kept at $backup)"
                continue
            }
            if ($rel -like 'docs/mesh/87-*') {
                # Do NOT discard content that has not been compared. The authority's copy is
                # authoritative, but that is a claim to CHECK: every heading in ours must exist in
                # theirs, or the pull is refused rather than losing a section.
                $ours = @(Select-String -Path $abs -Pattern '^#{1,4}\s' -ErrorAction SilentlyContinue | ForEach-Object { $_.Line.Trim() })
                $theirsText = & git -C $REPO show "origin/master:$rel" 2>$null
                $theirs = @($theirsText | Select-String -Pattern '^#{1,4}\s' -ErrorAction SilentlyContinue | ForEach-Object { $_.Line.Trim() })
                $missing = @($ours | Where-Object { $theirs -notcontains $_ })
                $gj.sectionCheck = [ordered]@{ ours = $ours.Count; theirs = $theirs.Count; missingInTheirs = $missing.Count }
                if ($missing.Count -gt 0) {
                    Problem "$rel has $($missing.Count) heading(s) origin/master does not: $($missing -join ' | ') -- not discarding it"
                    continue
                }
                Log "${rel}: every one of our $($ours.Count) headings exists in origin/master's $($theirs.Count) -- safe to take theirs"
            } else {
                Problem "$rel is dirty here AND changed on origin/master, and it is neither a generated cache nor the fork doc -- this script will not discard another stream's edit. The file is kept at $backup; resolve it by hand and re-run."
                continue
            }
            if ($DryRun) { Log "  DRY RUN: would back up and restore $rel from HEAD so the pull can proceed"; continue }
            & git -C $REPO checkout -- $rel 2>&1 | Out-Null
            Change "restored $rel from HEAD so the fast-forward can proceed (local copy kept at $backup)"
        }

        if ($failures.Count -eq 0 -and -not $DryRun) {
            $pull = & git -C $REPO pull --ff-only 2>&1
            $gj.pullExit = $LASTEXITCODE
            $gj.pullOutput = @($pull | Select-Object -First 20)
            if ($LASTEXITCODE -ne 0) {
                $pullText = ($pull -join ' ')
                # A REFUSED PULL AND AN UNREACHABLE REMOTE ARE DIFFERENT FAILURES. A refusal means the
                # tree is in a state git will not resolve, and the window stops (the parent's rule). An
                # unreachable remote means a DIFFERENT MACHINE is down, and stopping the provider
                # install for that is a misattributed blocker -- the failure this system keeps
                # punishing. Recorded as a warning; the tree keeps its local state either way.
                $offline = $pullText -match 'Could not read from remote|Connection timed out|timed out|Could not resolve hostname|Network is unreachable'
                if ($offline) {
                    $gj.pullWarning = "the remote is unreachable, so the pull was not attempted successfully: $pullText"
                    Log "WARNING: git pull could not reach the remote -- the tree keeps its local state and the window continues: $($pullText.Substring(0, [Math]::Min(200, $pullText.Length)))"
                } else {
                    Problem "git pull --ff-only refused: $($pullText.Substring(0, [Math]::Min(400, $pullText.Length)))"
                }
            } else { Log "pull: $(($pull | Select-Object -First 3) -join ' / ')" }

            if ($gj.pullExit -eq 0 -and -not $SkipPush) {
                # The one artefact that must not stay on one disk in a dirty tree.
                $integration = Join-Path $REPO 'docs\mesh\89-integration.md'
                $add = @()
                if (Test-Path -LiteralPath $integration) { $add += 'docs/mesh/89-integration.md' }
                $add += @($mapping | ForEach-Object { $_.source })
                # Anything still untracked under journal/entries after the pull is ABOVE the ceiling
                # (not taken on master), so it is safe to carry -- including entries another session
                # wrote while this window ran. Without this they stay on one disk in a dirty tree,
                # which is the failure that put docs/mesh/89-integration.md at risk in the first place.
                foreach ($line in (& git -C $REPO status --porcelain -- journal/entries 2>&1)) {
                    if ($line -match '^\?\?\s+(.+)$') { $add += ($Matches[1]).Trim() }
                }
                $add += @('scripts/mesh-provider-install.ps1', 'scripts/mesh-restart-at-0700.ps1', 'docs/mesh/90-provider-mount.md',
                          'profiles/web/cordis.patch.yml', 'presets/zabz/agent.cordis.yml', 'scripts/make_zabz_preset.py',
                          'scripts/install-client-plugins.ps1', 'scripts/harness-verify.ps1')
                $existing = @($add | Where-Object { Test-Path -LiteralPath (Join-Path $REPO ($_ -replace '/', '\')) })
                if ($existing.Count -gt 0) {
                    & git -C $REPO add -- $existing 2>&1 | Out-Null
                    $staged = @(& git -C $REPO diff --cached --name-only 2>&1)
                    if ($staged.Count -gt 0) {
                        $msg = "mesh: the remote provider and the v2 route are installed for the 07:00 restart`n`nPlus the journal entries re-filed out of the diverged tree (see docs/mesh/90-provider-mount.md)."
                        & git -C $REPO commit -m $msg 2>&1 | Out-Null
                        $gj.commitExit = $LASTEXITCODE
                        if ($LASTEXITCODE -ne 0) { Problem "git commit failed" }
                        else {
                            Change "committed $($staged.Count) path(s): $($staged -join ', ')"
                            $push = & git -C $REPO push 2>&1
                            $gj.pushExit = $LASTEXITCODE
                            if ($LASTEXITCODE -ne 0) {
                                # NOT a reason to refuse the restart: the restart installs the provider,
                                # the push only publishes. Recorded so it is not silently lost.
                                Problem "git push failed (recorded, not a reason to hold the restart): $((($push -join ' ')).Substring(0, [Math]::Min(200, (($push -join ' ')).Length)))"
                            } else { Change 'pushed the commit to origin' }
                        }
                    } else { Log 'nothing to commit' }
                }
            }
        } elseif ($DryRun) { Log 'DRY RUN: the pull is not attempted' }
    }
} else {
    Log 'STEP 3 skipped (-SkipJournal)'
    $report.steps.journal = @{ skipped = $true }
}

# ═══ STEP 4: the install must be verifiable BEFORE anything restarts ═══════════════════════════
if (-not $SkipInstall) {
    Step 'STEP 4: re-verify the provider install (read-only) and the composition'
    $installer = Join-Path $REPO 'scripts\mesh-provider-install.ps1'
    if (-not (Test-Path -LiteralPath $installer)) { Problem "no $installer" }
    else {
        $check = & pwsh -NoLogo -NoProfile -File $installer -Check 2>&1
        $checkExit = $LASTEXITCODE
        $report.steps.install = [ordered]@{ checkExit = $checkExit; lines = @($check | Select-Object -Last 25) }
        if ($checkExit -ne 0) {
            Log "install -Check exited $checkExit -- applying once, then re-checking"
            $apply = & pwsh -NoLogo -NoProfile -File $installer 2>&1
            $report.steps.install.applyExit = $LASTEXITCODE
            $report.steps.install.applyLines = @($apply | Select-Object -Last 25)
            $recheck = & pwsh -NoLogo -NoProfile -File $installer -Check 2>&1
            $report.steps.install.recheckExit = $LASTEXITCODE
            if ($LASTEXITCODE -ne 0) { Problem "the install cannot be verified (mesh-provider-install.ps1 -Check exits $LASTEXITCODE) -- refusing to restart" }
            else { Change 'applied the provider install (mesh-provider-install.ps1)' }
        } else { Log 'install check: every invariant holds' }
    }
    $bin = Join-Path $env:USERPROFILE 'AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js'
    $dump = & node $bin --profile web --dump-config 2>&1
    $report.steps.composition = [ordered]@{ exit = $LASTEXITCODE; lines = (($dump -join "`n").Split("`n").Count) }
    if ($LASTEXITCODE -ne 0) { Problem "dsh --profile web --dump-config exits $LASTEXITCODE -- THE ENGINE WOULD NOT COME BACK" }
    else { Log "composition: dump-config exit 0, $($report.steps.composition.lines) lines" }

    # ── STEP 4b: THE ENGINE PATCH MUST BE IN PLACE BEFORE THE ENGINE COMES BACK ────────────────
    # `DSH Engine Pin Install` runs `npm install` in ~/.dsh/engine, which re-extracts the package and
    # silently reverts any patch to it. This is therefore checked and re-applied HERE, immediately
    # before the one restart that would put it into effect -- it costs no extra process and it cannot
    # be lost to an install that happens between two 07:00 windows.
    #
    # MEASURED 2026-10-05: `POST /api/session/list` over 1068 sessions took 219223 ms (and 641532 ms
    # in a later refresh) while every other RPC answered in 14-330 ms; the same filesystem work with
    # no engine is 6797 ms. The walk was three STRICTLY SEQUENTIAL await chains of ~1068 iterations
    # and the engine's median event-loop lag is 73 ms (p95 1258 ms), which is ~500 s of arithmetic
    # and matches the observation. Pooling them measured 21185 ms -> 1320 ms (16.1x, interleaved A/B)
    # with an IDENTICAL artifact id set (sha256 6f4bc3b71ef630c3, 1068 artifacts) -- see
    # docs/dsh-at-scale/95-session-list-pool.md and scripts/patch-engine-session-list.mjs.
    #
    # A version change is a WARNING, not a blocker: the engine is fine, the walk is merely slow again,
    # and refusing the restart over that would be a misattributed blocker. It IS recorded, because
    # otherwise it is invisible.
    $patcher = Join-Path $REPO 'scripts\patch-engine-session-list.mjs'
    if (Test-Path -LiteralPath $patcher) {
        $patchLines = @(& node $patcher --check 2>&1)
        $patchExit = $LASTEXITCODE
        $report.steps.enginePatch = [ordered]@{ checkExit = $patchExit; lines = @($patchLines | Select-Object -Last 6) }
        if ($patchExit -eq 2) {
            Log 'engine patch: session-list pooling already applied'
        } elseif ($patchExit -eq 3) {
            Log "WARNING: the session-list pooling patch cannot be applied to this engine build (check exited 3): $(($patchLines | Select-Object -Last 1))"
            Log 'WARNING: the engine will start UNPATCHED -- the sidebar walk stays sequential until the patch is re-derived for this version'
        } else {
            $applied = @(& node $patcher --apply 2>&1)
            $report.steps.enginePatch.applyExit = $LASTEXITCODE
            $report.steps.enginePatch.applyLines = @($applied | Select-Object -Last 8)
            if ($LASTEXITCODE -ne 0) {
                Log "WARNING: applying the session-list patch failed (exit $LASTEXITCODE): $(($applied | Select-Object -Last 1))"
                Log 'WARNING: the engine will start UNPATCHED, which is slower but not broken'
            } else { Change "applied the pooled session-list engine patch before the restart: $(($applied | Where-Object { $_ -match '^bytes' }) -join '')" }
        }
    } else { Log "no $patcher -- the session-list patch is not carried by this checkout" }
} else { Log 'STEP 4 skipped (-SkipInstall)' }

if ($failures.Count -gt 0 -and -not $ForceGate) {
    Step 'STOPPING BEFORE THE RESTART'
    foreach ($f in $failures) { Log "  FAILED: $f" }
    SaveReport 'stopped-before-restart.json' | Out-Null
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host "mesh-restart-at-0700: $($failures.Count) step(s) before the restart failed -- NOTHING WAS RESTARTED." -ForegroundColor Red
    exit 1
}

if ($DryRun) {
    Step 'DRY RUN COMPLETE'
    Log "the gate is $(if ($gateOpen) { 'open' } else { 'OVERRIDDEN by -ForceGate' }), the snapshot is written, and the checks above are the pre-flight. No writes, no restart."
    SaveReport 'dry-run.json' | Out-Null
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    exit 0
}

# ═══ STEP 5: THE RESTART, by the machine's own supported path ══════════════════════════════════
Step 'STEP 5: restart the engine (multi-window/dshw.ps1 restart)'
$dshw = Join-Path $REPO 'multi-window\dshw.ps1'
$oldPid = $evidence.enginePid
$beforeFiles = $snapshot.sessionFilesOnDisk
$beforeRows = $snapshot.sessionListItems
$restartOut = & pwsh -NoLogo -NoProfile -File $dshw restart 2>&1
$restartExit = $LASTEXITCODE
$report.steps.restart = [ordered]@{ exit = $restartExit; lines = @($restartOut | Select-Object -Last 30) }
foreach ($l in $restartOut) { Log "  dshw: $l" }
if ($restartExit -ne 0) { Problem "dshw restart exited $restartExit" }

$newPid = $null
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $listen = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listen.Count -eq 1 -and $listen[0].OwningProcess -ne $oldPid) { $newPid = $listen[0].OwningProcess; break }
}
$report.steps.restart.newPid = $newPid
$report.steps.restart.listenerCount = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count
if (-not $newPid) { Problem "no single listener on :$Port owned by a new pid after ${WaitSeconds}s" }
else { Log "engine back: pid $newPid (was $oldPid), one listener on :$Port" }

# ═══ STEP 6: VERIFY ════════════════════════════════════════════════════════════════════════════
Step 'STEP 6: verify the restarted engine'
$verify = [ordered]@{ oldPid = $oldPid; newPid = $newPid; at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
if ($newPid) {
    # A NEW token: the launch token is per process, so the old cookie is dead by construction -- and
    # that is also the proof that this is a new engine and not the old one still serving.
    $t2 = $null
    for ($i = 0; $i -lt 24; $i++) {
        $t2 = Get-EngineToken $Port
        if ($t2) {
            $c2 = New-EngineCookie $Port $t2.token
            $h2 = Get-EngineHealth $Port $c2
            if ($h2) { break }
        }
        Start-Sleep -Seconds 5
    }
    if (-not $h2) { Problem 'the restarted engine does not answer /healthz with a fresh cookie' }
    else {
        $verify.healthz = 200
        $verify.enginePid = $h2.identity.pid
        $verify.engineStartedAt = $h2.identity.startedAt
        $verify.engineDshHome = $h2.identity.env.dshHome
        $verify.sessionsLive = $h2.sessions.live
        $verify.agentLoopsRunning = $h2.sessions.agentLoopsRunning
        Log "healthz 200: pid $($verify.enginePid), started $($verify.engineStartedAt), DSH_HOME $($verify.engineDshHome)"
        if ("$($verify.engineDshHome)" -ne "$($evidence.engineDshHome)" -and $evidence.engineDshHome) {
            Problem "the restarted engine reports DSH_HOME $($verify.engineDshHome), not $($evidence.engineDshHome)"
        } else { Log "DSH_HOME unchanged: $($verify.engineDshHome)" }

        # The persisted record must be intact: the session CORPUS is what a restart could damage.
        $verify.sessionFilesOnDisk = Get-SessionFiles
        $verify.sessionListItems = 0
        $l2 = Invoke-EngineRpc $Port $c2 'session/list' @{ _request = @{} }
        if ($l2 -and $l2.result.ok) { $verify.sessionListItems = @($l2.result.value.items).Count }
        Log "session files: $beforeFiles -> $($verify.sessionFilesOnDisk); session rows: $beforeRows -> $($verify.sessionListItems)"
        if ($verify.sessionFilesOnDisk -ne $beforeFiles) { Problem "session file count changed: $beforeFiles -> $($verify.sessionFilesOnDisk)" }
        if ($beforeRows -gt 0 -and $verify.sessionListItems -lt $beforeRows) { Problem "session rows dropped: $beforeRows -> $($verify.sessionListItems)" }

        # The phone gate must still reach the engine.
        try {
            $cap2 = Invoke-WebRequest -Uri "http://127.0.0.1:$GatePort/mesh/capacity" -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 25
            $verify.gateCapacityStatus = $cap2.StatusCode
            if ($cap2.StatusCode -eq 200) {
                $cj2 = $cap2.Content | ConvertFrom-Json
                $verify.gateNode = $cj2.node
                $verify.gateSessionsLive = $cj2.agents.sessionsLive
                if ($null -eq $cj2.agents) { Problem 'the gate answers but its engine reading is null -- the gate cannot reach the restarted engine' }
                else { Log "gate /mesh/capacity 200 for node $($cj2.node); it sees $($cj2.agents.sessionsLive) session(s)" }
            } else { Problem "gate /mesh/capacity returned $($cap2.StatusCode)" }
        } catch { Problem "gate /mesh/capacity threw: $($_.Exception.Message)" }

        # The v2 route lives in the engine now (a NEW host-plane bundle, so this is also the proof that
        # the restart mounted new rows at all).
        try {
            $mh = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/mesh/health" -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 15
            $verify.meshHealth = $mh.StatusCode
            if ($mh.StatusCode -eq 200) {
                $mj = $mh.Content | ConvertFrom-Json
                $verify.meshService = $mj.service
                $verify.meshSecretConfigured = $mj.auth.secretConfigured
                Log "engine /mesh/health 200: service $($mj.service), secretConfigured $($mj.auth.secretConfigured), node $($mj.node)"
            } else { Problem "engine /mesh/health returned $($mh.StatusCode) -- the v2 route did not mount" }
        } catch { Problem "engine /mesh/health threw: $($_.Exception.Message)" }

        # THE PROVIDER. There is no remote surface that lists registered subagent providers (measured:
        # `subagents/list` is remoteExportList(parentSessionId); the tools registry is not remote at
        # all), and the web profile writes host-plane plugin log lines NOWHERE durable (measured: a
        # scratch engine's whole stdout+stderr was 204 bytes and held no plugin line; the owner
        # engine's 32 KB err.log holds only MCP child output). So the assertion is a session's own
        # answer about its tool catalog -- the only reader of that catalog is a session.
        if ($ProbeProvider) {
            $probe = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
            $created = Invoke-EngineRpc $Port $c2 'session/create' @{ request = @{ cwd = (Join-Path $env:USERPROFILE 'code'); agentPreset = 'zabz' } }
            if (-not ($created -and $created.result.ok)) {
                $probe.result = 'NOT ASSERTED: could not create a session'
                if ($created) { $probe.error = $created.result.error }
            } else {
                $sid = [string]$created.result.value.sessionId
                $probe.sessionId = $sid
                $ask = 'Do not call any tool. Reply with exactly the names of the tools available to you that contain the substring "subagent", one per line, and nothing else.'
                $null = Invoke-EngineRpc $Port $c2 'session/prompt' @{ request = @{
                        requestId = [guid]::NewGuid().ToString(); sessionId = $sid; mode = 'queue'
                        content = @(@{ type = 'text'; text = $ask }) } }
                $deadline2 = (Get-Date).AddSeconds($ProbeWaitSeconds)
                $reply = ''
                while ((Get-Date) -lt $deadline2) {
                    Start-Sleep -Seconds 5
                    $pl = Invoke-EngineRpc $Port $c2 'session/list' @{ _request = @{} }
                    if (-not ($pl -and $pl.result.ok)) { continue }
                    $row = @($pl.result.value.items | Where-Object { [string]$_.sessionId -eq $sid }) | Select-Object -First 1
                    if (-not $row) { continue }
                    $ol = @($row.projections.values.turnOutline)
                    if ($ol.Count -gt 0) { $reply = [string]($ol | Select-Object -First 1).response }
                    if ($reply -and -not $row.running) { break }
                }
                $probe.reply = $reply
                if ($reply -match 'subagent_remote') { $probe.result = 'ASSERTED: a live session on the zabz preset names subagent_remote among its tools' }
                elseif ($reply) { $probe.result = "NOT ASSERTED: the session's reply did not name subagent_remote: $($reply.Substring(0, [Math]::Min(200, $reply.Length)))" }
                else { $probe.result = 'NOT ASSERTED: no reply within the window' }
            }
            $verify.providerProbe = $probe
            Log "provider probe: $($probe.result)"
        } else { $verify.providerProbe = 'skipped (-ProbeProvider:$false)' }
    }
}
$report.steps.verify = $verify
SaveReport 'post-restart.json' | Out-Null

Step 'ROLLBACK (the command, not an action)'
Log '  1. pwsh scripts/mesh-provider-install.ps1 -Rollback     # takes the rows and the two bundle names out'
Log '  2. node packages/plugin-mesh-http/bin/install-mesh-http.mjs --remove    # if you also want the v2 junction gone'
Log "  3. pwsh multi-window/dshw.ps1 restart                   # one restart puts the ENGINE back"
Log '  (the v2 secret file is outside the repo and unused once the route is gone; delete it only if you mean to)'

Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "mesh-restart-at-0700: finished with $($failures.Count) problem(s); see $runDir" -ForegroundColor Red
    exit 1
}
Write-Host "mesh-restart-at-0700: restart complete and verified; record in $runDir" -ForegroundColor Green
exit 0
