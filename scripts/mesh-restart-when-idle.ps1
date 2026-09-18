<#
.SYNOPSIS
The idle window: restart the resident engine at the first moment none of the owner's own work is
running, so the host-plane rows already installed on this laptop become live -- and refuse, cheaply
and loudly, on every other tick.

WHY THIS EXISTS
A host-plane row is read at engine start and never before (docs/mesh/90-provider-mount.md §2; the row
mechanics are docs/mesh/92-provider-placement.md). The placement rows in the `web` profile's patch
layer and `dsh-plugin-remote-fanout`'s broker client are therefore INERT until the engine that serves
:3099 is restarted. The owner runs his own fleet through the night and said the restart may happen at
a moment of his choosing; asking him to pick that moment is a question he should not have to answer.
So this window takes the first moment his work is genuinely idle -- decided from EVIDENCE (the
engine's own /healthz plus its session list), never from a clock.

IT IS A WRAPPER, ON PURPOSE
The window logic is not re-implemented here. `scripts/mesh-restart-at-0700.ps1` is this machine's
proven window -- gate -> snapshot -> install re-verify -> ONE `dshw restart` by the supported path ->
verify -> rollback instructions -- and this script calls it. What this script adds is exactly three
things:

  1. A GATE THAT RUNS FIRST AND COSTS ALMOST NOTHING, so that 96 ticks a day cannot accumulate work
     on a machine that is in use: no token, no cookie, no session created, no install, no
     `--dump-config`, no git. A tick while the owner works ends after two HTTP calls.
  2. AN IDEMPOTENCE MARKER holding the pid of the engine this window last restarted into. A later
     tick that finds that same pid serving :3099 does nothing at all. Without it a 15-minute schedule
     plus a 15-minute autosync that rewrites the live patch layer would restart the owner's engine
     four times an hour, forever.
  3. THE ONE VERIFICATION THIS WINDOW EXISTS FOR, which the 07:00 window does not make: that the
     COMPOSED configuration carried by the NEW engine contains the placement rows. See
     `Get-PlacementEvidence` and `Assert-Placement`.
  4. THE SECOND ACTIVATION, in a different layer: `dsh-plugin-mesh-http` v0.2.0. See `TWO THINGS,
     ONE RESTART` below.

TWO THINGS, ONE RESTART, AND THEY ARE NOT IN THE SAME LAYER
The owner gets one interruption, so the one restart must land both of these whole:
  (a) THE PLACEMENT ROWS -- host-plane, in the `web` profile's patch layer.
  (b) `dsh-plugin-mesh-http` v0.2.0 on this node. Measured 2026-09-17 14:05Z: this node's route
      answers `version 0.1.0`, `limits.oneRunAtATime: true`, `node: "zabz-yoga"`, `fqdn: ""` -- the
      v0.1.0 single-slot ceiling and the two identity defects of
      `docs/mesh/93-transport-concurrency.md` §8, where the engine booted 52 s before
      `tailscale-ipn` and cached an empty tailnet name for its whole life. The desktop's route,
      restarted by the transport stream, answers `version 0.2.0`, `node: "zabz-tech"`,
      `fqdn: "zabz-tech.tail93e6e6.ts.net"`, `identityDegraded: false` (measured the same minute).
      A bundle cannot hot-load (P210), and 93 §7 puts the deploy cost at "one engine restart per
      node" -- so (b) rides (a).
    What (b) needs INSTALLED is nothing: measured the same minute, the junction
    `~/.dsh/profiles/web/node_modules/dsh-plugin-mesh-http` already resolves into THIS checkout and
    the `lib/index.js` on disk already says `VERSION = '0.2.0'` (sha256 c9aebdb4…, byte-identical to
    the desktop's copy). The RUNNING engine is what is old. This window does not take that on trust:
    `Get-MeshHttpEvidence` runs the transport stream's own installer `--check` (applying it if it
    reports drift), compares the deployed version and file hash against this checkout, and
    `Assert-MeshHttp` runs the package's OWN test suite (measured green: 36 pass / 0 fail / 13.4 s)
    and corroborates the code against the desktop where v0.2.0 was measured. If any of that cannot be
    verified, or the desktop's copy differs, THE WINDOW STOPS AND REPORTS rather than restarting into
    an unknown state. One measured exception, stated so it can be overruled: a desktop that does not
    ANSWER is a warning rather than a stop, because another machine's absence is not this node's
    fault (the misattributed-blocker rule `mesh-restart-at-0700.ps1` applies to a fetch and a pull).

WHY `-SkipJournal` IS PASSED TO THE INNER WINDOW, AND WHY THAT IS DELIBERATE
The 07:00 window's step 3 converges the tree, pulls, commits and pushes. That is right for a
once-a-day window a human scheduled, and wrong for an unattended 15-minute one: it would `git add`
about twenty paths that belong to other sessions' live work and publish them without anyone asking.
This window's job is to ACTIVATE configuration, not to publish a tree. Everything that makes a
restart safe is kept: the install re-verify (which is also what APPLIES the placement rows -- see
below), the `--dump-config` pre-flight, and the refusal to restart if any step before it fails.

THE INSTALL STEP IS NOT OPTIONAL, AND THIS LAPTOP IS THE PROOF
Measured 2026-09-17 09:47 local: the live layer `~/.dsh/profiles/web/cordis.patch.yml` did NOT carry
the placement rows, even though the repo's working copy did.
`scripts/autosync.ps1` (task `PersonalSecretary-HarnessSync`, every 15 minutes) exports HEAD to a temp
snapshot and runs `scripts/sync.py` from THAT snapshot (`autosync.ps1:358-380`), and
`sync.py:plan_profile_patches` copies `profiles/web/cordis.patch.yml` over the live layer. HEAD does
not contain the placement rows -- they are uncommitted working-tree edits -- so the live layer was
reverted to a placement-less configuration at 09:47:17, with the placement version kept beside it as
`cordis.patch.yml.bak-20260917-134717`. A restart that skipped the install re-verify would have booted
a composed configuration WITHOUT `placement`, `brokerSsh` and `brokerUrl`. The inner window's step 4
runs `mesh-provider-install.ps1 -Check` and applies it when it reports drift, which is how the rows
reach the layer in time for the restart this script then performs. `Assert-Placement` below is what
turns that from a hope into a checked outcome.

ROLLBACK (the commands, not an action)
  1. pwsh scripts/mesh-provider-install.ps1 -Rollback      # takes the placement rows and the bundle
                                                          # names out
  2. pwsh multi-window/dshw.ps1 restart                    # ONE restart puts the engine back
  3. Disable-ScheduledTask -TaskName 'DSH Mesh Restart When Idle'   # stop this window firing again
  4. Remove-Item "$env:USERPROFILE\.dsh\mesh\restart-when-idle\.done.json"  # clear the idempotence
     marker ONLY if a future idle tick should also be allowed to take another restart
  For the route package (activation b) there are two different intentions, and they are not the same:
     * take the route OFF this node: node packages/plugin-mesh-http/bin/install-mesh-http.mjs --remove
       (it removes the junction and the bundle name, writing nothing else), then restart;
     * go BACK to the previous route code: git -C . checkout <commit> -- packages/plugin-mesh-http,
       then restart. v0.1.0 is not on this disk any more -- the junction points at this checkout, so
       there is no copy of the old code to restore from except git history.
  Nothing in this script deletes a record: everything it writes under
  ~/.dsh/mesh/restart-when-idle/ is the evidence for all of the above.

RECORDS
  ~/.dsh/mesh/restart-when-idle/run.log                  one line at a time, every tick (rolling)
  ~/.dsh/mesh/restart-when-idle/decisions.log            one line per tick: the decision, always
  ~/.dsh/mesh/restart-when-idle/refusals/latest.json     the latest DEFERRAL, with the ids and titles
  ~/.dsh/mesh/restart-when-idle/.done.json               the idempotence marker
  ~/.dsh/mesh/restart-when-idle/<stamp>/pre-restart.json what the restart was about to end
  ~/.dsh/mesh/restart-when-idle/<stamp>/post-restart.json what was verified after it
A stamp directory is created only when the gate OPENS, i.e. when a restart is attempted. A deferral is
recorded in the rolling logs and in refusals/latest.json instead: at 96 ticks a day, one directory per
deferral would be ~35,000 directories a year that hold nothing but "he was working".

USAGE
    pwsh scripts/mesh-restart-when-idle.ps1              # what the scheduled task runs
    pwsh scripts/mesh-restart-when-idle.ps1 -DryRun      # gate + snapshot + read-only checks; no writes, no restart
    pwsh scripts/mesh-restart-when-idle.ps1 -ForceGate   # HUMAN ONLY: restart even with work running

EXIT CODES
  0 the run did what the gate allowed (a DEFERRAL and an ALREADY-DONE tick both exit 0)
  1 a step before the restart failed (nothing was restarted), or the post-restart verification found
    a problem (the engine is reported as it is found)
  2 the machine's state could not be read at all (nothing was restarted)
#>
[CmdletBinding()]
param(
    [int]$Port = 3099,
    [int]$GatePort = 3086,
    [string]$Repo,
    # How long the inner window may wait for the restarted engine, and for a probe to settle.
    [int]$WaitSeconds = 300,
    # Gate + snapshot + every read-only check, then stop: no install is applied and nothing is
    # restarted. Its own stamp directory and the rolling logs are written, so a dry run is legible
    # afterwards -- it just cannot look like a restart.
    [switch]$DryRun,
    # Restart even when the gate sees live work. A HUMAN's switch; the scheduled task never passes it.
    [switch]$ForceGate,
    # Do not run plugin-mesh-http's own test suite before restarting. A HUMAN's switch; it removes a
    # gate that exists to stop this window deploying a route package that does not pass its own tests.
    [switch]$SkipMeshHttpTests
)

$ErrorActionPreference = 'Continue'

$REPO = if ($Repo) { $Repo } else { Split-Path -Parent $PSScriptRoot }
$checkout = Join-Path $env:USERPROFILE 'code\harness-config'
if ($REPO -like "$env:TEMP*" -and (Test-Path (Join-Path $checkout 'profiles'))) { $REPO = $checkout }
$env:DSH_HOME = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }

$INNER = Join-Path $REPO 'scripts\mesh-restart-at-0700.ps1'
$root = Join-Path $env:DSH_HOME 'mesh\restart-when-idle'
$rollingLog = Join-Path $root 'run.log'
$decisions = Join-Path $root 'decisions.log'
$markerPath = Join-Path $root '.done.json'
$lockPath = Join-Path $root '.lock'
$refusalPath = Join-Path $root 'refusals\latest.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runDir = Join-Path $root $stamp
$stampLog = $null
New-Item -ItemType Directory -Force -Path $root | Out-Null

# The keys this window exists to see. They are READ from the row (never remembered from a previous
# run), but the REQUIRED set is named here on purpose: a check that only reports "some keys appeared"
# is a check that cannot fail. Names measured from the repo's managed block and the live row on
# 2026-09-17.
$PLACEMENT_KEYS = @('placement', 'brokerSsh', 'brokerUrl')
$PLACEMENT_KEYS_OPTIONAL = @('brokerTimeoutMs', 'queueWaitMs', 'queuePollMs')

$problems = @()
$warnings = @()
$report = [ordered]@{
    startedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    machine = $env:COMPUTERNAME
    dshHome = $env:DSH_HOME
    port = $Port
    gatePort = $GatePort
    dryRun = [bool]$DryRun
    forceGate = [bool]$ForceGate
    inner = $INNER
    steps = [ordered]@{}
}

function Log([string]$text) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $text
    Write-Host $line
    Add-Content -LiteralPath $rollingLog -Value ("{0} {1}" -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'), $text) -ErrorAction SilentlyContinue
    if ($script:stampLog) { Add-Content -LiteralPath $script:stampLog -Value $line -ErrorAction SilentlyContinue }
}
function Step([string]$text) { Write-Host ''; Log $text }
function Warn([string]$text) { $script:warnings += $text; Log "WARNING: $text" }
function Problem([string]$text) { $script:problems += $text; Log "PROBLEM: $text" }
function Decision([string]$decision, [string]$note) {
    $line = "{0} decision={1} port={2} enginePid={3} loops={4} running={5} note={6}" -f `
        (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'), $decision, $Port,
        $(if ($script:lastPid) { $script:lastPid } else { '?' }),
        $(if ($null -ne $script:lastLoops) { $script:lastLoops } else { '?' }),
        $(if ($null -ne $script:lastRunning) { $script:lastRunning } else { '?' }), $note
    Add-Content -LiteralPath $decisions -Value $line -ErrorAction SilentlyContinue
    Log "DECISION: $decision -- $note"
}
function New-RunDir {
    New-Item -ItemType Directory -Force -Path $runDir | Out-Null
    $script:stampLog = Join-Path $runDir 'run.log'
    $script:report.runDir = $runDir
}
function SaveRecord([string]$name, $value) {
    $path = Join-Path $runDir $name
    $value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $path -Encoding utf8
    return $path
}

# ── locks: one tick at a time ─────────────────────────────────────────────────────────────────
if (Test-Path -LiteralPath $lockPath) {
    $held = Get-Content -LiteralPath $lockPath -Raw -ErrorAction SilentlyContinue
    $heldPid = ($held -split "`n" | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1)
    if ($heldPid -and (Get-Process -Id ([int]$heldPid) -ErrorAction SilentlyContinue)) {
        Log "another tick holds the lock (pid $heldPid) -- exiting without doing anything"
        Decision 'LOCKED' "another tick (pid $heldPid) is in flight"
        exit 0
    }
}
Set-Content -LiteralPath $lockPath -Value "$PID`n$stamp`n" -Encoding utf8

# ═══ the engine's own facts, the only supported way in ════════════════════════════════════════
function Get-EngineToken([int]$enginePort) {
    # The ONLY supported way to authenticate to an engine is a cookie minted from its per-process
    # launch token, and that token exists only in the launcher's log (dsh-client-connection mints it
    # per process and never persists it -- 66-dsh-remote-capability.md §2c). The multi-window launcher
    # writes `<port>.log` plus `<port>-<stamp>.log`; the newest that still has a token is the live one.
    $dir = Join-Path $env:DSH_HOME 'multi-window\logs'
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    $candidates = @()
    $p = Join-Path $dir "$enginePort.log"
    if (Test-Path -LiteralPath $p) { $candidates += Get-Item -LiteralPath $p }
    $candidates += @(Get-ChildItem -LiteralPath $dir -Filter "$enginePort-*.log" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 5)
    foreach ($f in $candidates) {
        $m = [regex]::Matches((Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue), 'token=([A-Za-z0-9_-]+)')
        if ($m.Count -gt 0) { return [pscustomobject]@{ token = $m[$m.Count - 1].Groups[1].Value; file = $f.FullName } }
    }
    return $null
}
function New-EngineCookie([int]$enginePort, [string]$token) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$enginePort/?token=$token" -MaximumRedirection 0 `
            -UseBasicParsing -SkipHttpErrorCheck -ErrorAction SilentlyContinue
        $set = @($r.Headers['Set-Cookie']) | Select-Object -First 1
        if ($set) { return ($set -split ';')[0] }
    } catch { }
    return $null
}
function Invoke-EngineRpc([int]$enginePort, [string]$cookie, [string]$method, [hashtable]$arguments, [int]$TimeoutSec = 60) {
    # `$args` is PowerShell's automatic argument array; naming a parameter that way turned a hashtable
    # into System.Object[] at the call site (measured in the 07:00 window). It is `$arguments` here.
    $body = @{ type = 'client-request'; rpcId = [guid]::NewGuid().ToString(); method = $method; payload = @{ args = $arguments } } |
        ConvertTo-Json -Depth 12 -Compress
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$enginePort/api/$method" -Method POST `
            -Headers @{ Cookie = $cookie; 'content-type' = 'application/json' } -Body $body `
            -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec $TimeoutSec
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
    $dir = Join-Path $env:DSH_HOME 'sessions'
    if (-not (Test-Path -LiteralPath $dir)) { return 0 }
    return @(Get-ChildItem -LiteralPath $dir -Recurse -File -Filter 'session.v3.jsonl.zstd' -ErrorAction SilentlyContinue).Count
}
function Get-TokenFingerprint([string]$token) {
    # A fresh launch token is the proof that this is a NEW process (it is minted per process and never
    # persisted). Its fingerprint proves that without writing the credential itself into a record.
    if (-not $token) { return $null }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($token))
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12)
}
function Get-EngineProcesses([int]$enginePort) {
    # "ONE engine on one port" asked of the process table. The match is deliberately narrow: a process
    # is an engine only when node ITSELF was handed `<...>@deepseek-ai/dsh/lib/bin.js` and the port
    # flag. Matching on the port string alone is WRONG and was measured wrong on 2026-09-17: a
    # tool-call runner (dsh-subprocess-local/lib/runner.js) and its pwsh child both carry the literal
    # text `--port 3099` in the command they are running, so a naive match counts three engines.
    $pattern = '(^|[\s"])[^"]*@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js"?\s'
    $portPattern = "--port\s+$enginePort(\s|$)"
    return @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $cl = [string]$_.CommandLine
            ($cl -notmatch 'subprocess-local|runner\.js') -and ($cl -match $pattern) -and ($cl -match $portPattern)
        } | ForEach-Object { [pscustomobject]@{ pid = $_.ProcessId; commandLine = [string]$_.CommandLine } })
}
function Get-GateCapacity([int]$gatePort) {
    try {
        $cap = Invoke-WebRequest -Uri "http://127.0.0.1:$gatePort/mesh/capacity" -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 20
        if ($cap.StatusCode -ne 200) { return [ordered]@{ status = $cap.StatusCode } }
        $cj = $cap.Content | ConvertFrom-Json
        return [ordered]@{
            status = 200; node = $cj.node
            loopsRunning = $cj.agents.loopsRunning; sessionsLive = $cj.agents.sessionsLive
            agentsIsNull = ($null -eq $cj.agents)
        }
    } catch { return [ordered]@{ status = "ERR: $($_.Exception.Message)" } }
}
function Get-LauncherSlot([int]$enginePort) {
    # dshw.ps1 owns the "one engine per DSH_HOME" rule and records the slot it started under THIS
    # DSH_HOME. That record is the cleanest available answer to "is this the same DSH_HOME?".
    $p = Join-Path $env:DSH_HOME 'multi-window\state.json'
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    try {
        $s = Get-Content -LiteralPath $p -Raw | ConvertFrom-Json
        $slot = $s.slots.PSObject.Properties | Where-Object { $_.Name -eq "$enginePort" } | Select-Object -First 1
        if (-not $slot) { return $null }
        return [ordered]@{
            stateFile = $p; pid = $slot.Value.pid; startedAt = [string]$slot.Value.startedAt
            label = [string]$slot.Value.label; profile = [string]$slot.Value.profile
            log = [string]$slot.Value.log; workspace = [string]$slot.Value.workspace
        }
    } catch { return [ordered]@{ stateFile = $p; error = $_.Exception.Message } }
}
function Resolve-PlacementMode {
    # A transcription of packages/plugin-remote-fanout/lib/index.js:64-68, kept so the record says which
    # mode the package will CHOOSE. If that rule changes, this line is wrong and says so in the record
    # rather than being silently obeyed.
    $configured = $env:MESH_PLACEMENT
    if ($configured -eq 'fixed') { return 'fixed' }
    if ($configured -eq 'broker') { return 'broker' }
    if ($env:MESH_TARGET_NODE -and $env:MESH_TARGET_NODE.Trim() -ne '') { return 'fixed' }
    return 'broker'
}

function Get-RunningSessionTitles([int]$enginePort, [int]$TimeoutSec = 40) {
    # `/api/session/list` is the ONLY surface that carries a session's title and its subagent label --
    # and it is expensive AND fragile under load: measured 2026-09-17 it returned 1.38 MB in 15.8 s
    # when the engine was quiet, and at 17 concurrent agent loops it did not answer inside 60 s at all.
    # So:
    #   * the gate itself is decided from `/healthz` (id + status, 49 ms), never from this;
    #   * this is called only when the verdict is DEFER, because that is when the window owes an
    #     account of what it found, and it does no work in that case;
    #   * the bound is short, and A FAILURE IS RECORDED AS A FAILURE. An empty answer from this call is
    #     NOT evidence that nothing is running, and the refusal never says so.
    $started = Get-Date
    $out = [ordered]@{ sessionListCalled = $true }
    $list = Invoke-EngineRpc $enginePort $script:engineCookie 'session/list' @{ _request = @{} } $TimeoutSec
    $out.sessionListMs = [int]((Get-Date) - $started).TotalMilliseconds
    if (-not $list -or -not $list.result -or -not $list.result.ok) {
        $out.sessionListError = "the session/list RPC did not answer ok within ${TimeoutSec}s, so TITLES could not be read; the ids below come from the engine's own census in /healthz and are unaffected"
        $out.sessionListOk = $false
        return $out
    }
    $out.sessionListOk = $true
    $items = @($list.result.value.items)
    $out.sessionRows = $items.Count
    $runningRows = @()
    foreach ($row in $items) {
        if (-not $row.running) { continue }
        $v = $row.projections.values
        $runningRows += [pscustomobject]@{
            id = [string]$row.sessionId
            title = [string]$v.title
            origin = [string]$row.origin
            label = if ($v.subagent) { [string]$v.subagent.label } else { '' }
            updatedAt = $row.updatedAt
        }
    }
    $out.runningFromList = $runningRows.Count
    $out.runningSessions = @($runningRows | Sort-Object updatedAt -Descending)
    $out.seenLiveSessions = @($items | Sort-Object updatedAt -Descending | Select-Object -First 20 | ForEach-Object {
            [pscustomobject]@{ id = [string]$_.sessionId; running = [bool]$_.running
                title = [string]$_.projections.values.title; origin = [string]$_.origin }
        })
    return $out
}

function Get-EngineFacts([int]$enginePort, [int]$gatePort, [switch]$Light) {
    <#
    THE GATE PASS IS LIGHT, AND THE SIZE OF THE DIFFERENCE IS MEASURED.
    On ZABZ-YOGA with the owner's fleet live (2026-09-17 10:10 local) the pieces cost:
      token 173 ms | cookie 459 ms | /healthz 49 ms | gate /mesh/capacity 274 ms   => ~1 s
      /api/session/list 15,816 ms (1.38 MB) | Get-NetTCPConnection x3 7,099 ms |
      session-file scan 4,738 ms | process table 908 ms                            => ~29 s
    A light pass reads the two things that DECIDE the gate (the engine's own census, and the phone
    gate's independent reading) and nothing else, so a tick on a machine in use costs about a second
    instead of half a minute. Everything expensive is read only when the gate opens -- or, in the
    deferral path, only when titles are owed.
    #>
    $f = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); port = $enginePort; light = [bool]$Light }
    $t = Get-EngineToken $enginePort
    if (-not $t) {
        $f.error = "no launch token in any log under $env:DSH_HOME\multi-window\logs -- the gate has NO evidence"
        return $f
    }
    $f.tokenFile = $t.file
    $f.tokenFingerprint = Get-TokenFingerprint $t.token
    $cookie = New-EngineCookie $enginePort $t.token
    if (-not $cookie) { $f.error = 'could not mint a cookie from the launch token -- no evidence'; return $f }
    $h = Get-EngineHealth $enginePort $cookie
    if (-not $h) { $f.error = 'GET /healthz did not answer 200 with a valid cookie -- no evidence'; return $f }
    # Kept in script scope, NOT in the returned object: this is a live credential and the returned
    # object is written to disk as a record.
    $script:engineCookie = $cookie

    $f.enginePid = $h.identity.pid
    $f.engineStartedAt = $h.identity.startedAt
    $f.engineUptimeMs = $h.identity.uptimeMs
    $f.engineArgv = @($h.identity.argv)
    $f.engineCwd = $h.identity.cwd
    $f.dshHomeReportedByHealthz = $h.identity.env.dshHome
    $f.dshHomeProcess = $env:DSH_HOME
    $f.sessionsLive = $h.sessions.live
    $f.agentLoopsRunning = $h.sessions.agentLoopsRunning
    $censusRunning = @($h.sessions.list | Where-Object { $_.status -eq 'running' } | ForEach-Object { $_.id })
    $f.runningFromCensus = $censusRunning.Count
    $f.runningIdsFromCensus = $censusRunning

    # SECOND, INDEPENDENT READING: the phone gate's own capacity route, answered before sign-in.
    $f.gateCapacity = Get-GateCapacity $gatePort
    $f.launcherSlot = Get-LauncherSlot $enginePort

    if ($Light) { return $f }

    # ── the expensive half: only when the gate opened, or when a verdict is being explained ─────
    $titles = Get-RunningSessionTitles $enginePort
    foreach ($k in $titles.Keys) { $f[$k] = $titles[$k] }
    if ($titles.sessionListOk) {
        $fromListIds = @($f.runningSessions | ForEach-Object { $_.id })
        $f.runningOnlyInCensus = @($censusRunning | Where-Object { $fromListIds -notcontains $_ })
    } else {
        # The census is still the truth about WHO is running; only the titles are missing.
        $f.runningOnlyInCensus = @($censusRunning)
        $f.runningFromList = $null
    }

    $listeners = @(Get-NetTCPConnection -LocalPort $enginePort -State Listen -ErrorAction SilentlyContinue)
    $f.listenersOnPort = $listeners.Count
    $f.listenerPids = @($listeners | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    $f.enginesOnPort = @(Get-EngineProcesses $enginePort)
    $f.sessionFilesOnDisk = Get-SessionFiles
    $f.establishedOnEnginePort = @(Get-NetTCPConnection -LocalPort $enginePort -State Established -ErrorAction SilentlyContinue).Count
    $f.establishedOnGatePort = @(Get-NetTCPConnection -LocalPort $gatePort -State Established -ErrorAction SilentlyContinue).Count
    # And what the route the ENGINE mounted says about itself -- the only before/after difference
    # activation (b) has.
    $f.meshHealth = Get-MeshRoute $enginePort
    return $f
}

function Get-PlacementEvidence {
    <#
    What the composed configuration says about placement, asked of TWO sources so the record cannot be
    satisfied by one of them being stale:
      * the LIVE patch layer on disk -- the file the loader applies last
      * the COMPOSED tree from `dsh --profile web --dump-config` -- what the engine will read
    `--dump-config` prints each row's raw `!!js` expressions rather than evaluating them (measured
    2026-09-17: it printed `target: !!js process.env.MESH_TARGET_NODE ?? 'desktop-ts'`), so a key's
    PRESENCE is readable there, and the evaluation question is answered separately from the rule.
    #>
    $ev = [ordered]@{}
    $live = Join-Path $env:DSH_HOME 'profiles\web\cordis.patch.yml'
    $ev.livePatch = $live
    $ev.requiredKeys = @($script:PLACEMENT_KEYS)
    $ev.liveRowPresent = $false
    $ev.liveKeys = [ordered]@{}
    foreach ($k in $script:PLACEMENT_KEYS) { $ev.liveKeys[$k] = $false }
    if (Test-Path -LiteralPath $live) {
        $li = Get-Item -LiteralPath $live
        $text = Get-Content -LiteralPath $live -Raw
        $ev.livePatchSha256Prefix = (Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash.Substring(0, 16)
        $ev.livePatchMtime = $li.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:ssK')
        $ev.livePatchBytes = $li.Length
        $ev.liveRowPresent = [bool]($text -match "id:\s*'?remote-fanout'?")
        foreach ($k in $script:PLACEMENT_KEYS) {
            $ev.liveKeys[$k] = [bool]($text -match ("(?m)^\s*" + [regex]::Escape($k) + "\s*:"))
        }
        $ev.liveOptionalKeys = @($script:PLACEMENT_KEYS_OPTIONAL | Where-Object { $text -match ("(?m)^\s*" + [regex]::Escape($_) + "\s*:") })
        $ev.liveToolRowDisabled = [bool]($text -match "id:\s*'?tool-subagent-remote'?[\s\S]{0,120}?disabled:\s*true")
        $ev.liveModeLiteral = ([regex]::Match($text, "(?m)^\s*placement\s*:\s*(.+)$")).Groups[1].Value.Trim()
    } else {
        $ev.livePatchMissing = $true
    }

    # The composed tree.
    $bin = Join-Path $env:USERPROFILE 'AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js'
    $ev.dumpConfigBin = $bin
    $ev.composedKeys = [ordered]@{}
    foreach ($k in $script:PLACEMENT_KEYS) { $ev.composedKeys[$k] = $false }
    $ev.composedRowPresent = $false
    if (Test-Path -LiteralPath $bin) {
        $out = & node $bin --profile web --dump-config 2>&1
        $ev.dumpConfigExit = $LASTEXITCODE
        $inRow = $false
        $row = @()
        foreach ($line in $out) {
            if ($line -match '^- id:\s*remote-fanout\s*$') { $inRow = $true; $row = @($line); continue }
            if ($line -match '^- id:\s*\S') { $inRow = $false }
            if ($inRow) { $row += $line }
        }
        $rowText = ($row -join "`n")
        $ev.composedRowPresent = ($row.Count -gt 0)
        foreach ($k in $script:PLACEMENT_KEYS) {
            $ev.composedKeys[$k] = [bool]($rowText -match ("(?m)^\s+" + [regex]::Escape($k) + "\s*:"))
        }
        $ev.composedRowFirstLines = @($row | Select-Object -First 12)
        $ev.dumpLineCount = @($out).Count
    } else {
        $ev.dumpConfigMissing = $true
    }

    # Which mode the package will CHOOSE, from every environment the launcher could have inherited.
    $ev.modeResolution = [ordered]@{
        rule = 'packages/plugin-remote-fanout/lib/index.js:64-68 -- config.placement ?? env.MESH_PLACEMENT; "fixed" -> fixed; "broker" -> broker; else MESH_TARGET_NODE non-empty -> fixed; else broker'
        processMESH_PLACEMENT = [string]$env:MESH_PLACEMENT
        processMESH_TARGET_NODE = [string]$env:MESH_TARGET_NODE
        userMESH_PLACEMENT = [string][Environment]::GetEnvironmentVariable('MESH_PLACEMENT', 'User')
        userMESH_TARGET_NODE = [string][Environment]::GetEnvironmentVariable('MESH_TARGET_NODE', 'User')
        machineMESH_PLACEMENT = [string][Environment]::GetEnvironmentVariable('MESH_PLACEMENT', 'Machine')
        machineMESH_TARGET_NODE = [string][Environment]::GetEnvironmentVariable('MESH_TARGET_NODE', 'Machine')
        resolvesTo = (Resolve-PlacementMode)
    }

    # THE BROKER CLIENT ITSELF: the row is worthless if the code behind it is not the linked package.
    $mod = Join-Path $env:DSH_HOME 'profiles\web\node_modules\dsh-plugin-remote-fanout'
    $ev.brokerClient = [ordered]@{
        linkedAt = $mod
        present = (Test-Path -LiteralPath $mod)
        target = $(if (Test-Path -LiteralPath $mod) { [string](Get-Item -LiteralPath $mod -Force).Target } else { $null })
        brokerClientJs = (Test-Path -LiteralPath (Join-Path $mod 'lib\broker-client.js'))
        placementJs = (Test-Path -LiteralPath (Join-Path $mod 'lib\placement.js'))
    }
    $profPkg = Join-Path $env:DSH_HOME 'profiles\web\package.json'
    $ev.declaredAsBundle = $false
    if (Test-Path -LiteralPath $profPkg) {
        $pj = Get-Content -LiteralPath $profPkg -Raw
        $ev.declaredAsBundle = [bool]($pj -match 'dsh-plugin-remote-fanout')
    }

    # DURABILITY. autosync rewrites the live layer from HEAD every 15 minutes, so an uncommitted row
    # survives only until the next tick. Recorded, never fatal -- see the header.
    $ev.headCarriesPlacement = $null
    try {
        $head = (& git -C $script:REPO show 'HEAD:profiles/web/cordis.patch.yml' 2>$null) -join "`n"
        if ($head) { $ev.headCarriesPlacement = [bool]($head -match '(?m)^\s*placement\s*:') }
        $ev.workingTreeModified = [bool]((& git -C $script:REPO status --porcelain -- profiles/web/cordis.patch.yml 2>$null) -match '\S')
    } catch { }
    $ev.durableAcrossAutosync = ($ev.headCarriesPlacement -eq $true)
    return $ev
}

function Assert-Placement($ev, [string]$when) {
    # The assertion this window exists for. Every failure is named with the source it came from.
    $ok = $true
    if (-not $ev.liveRowPresent) { Problem "$when`: the live patch layer has no 'remote-fanout' row ($($ev.livePatch))"; $ok = $false }
    foreach ($k in $script:PLACEMENT_KEYS) {
        if (-not $ev.liveKeys[$k]) { Problem "$when`: the live patch layer does not carry '$k'"; $ok = $false }
        if (-not $ev.composedKeys[$k]) { Problem "$when`: the COMPOSED configuration does not carry '$k'"; $ok = $false }
    }
    if (-not $ev.composedRowPresent) { Problem "$when`: 'dsh --profile web --dump-config' printed no 'remote-fanout' row"; $ok = $false }
    if ($ev.dumpConfigExit -ne 0) { Problem "$when`: 'dsh --profile web --dump-config' exited $($ev.dumpConfigExit) -- THE ENGINE WOULD NOT COME BACK"; $ok = $false }
    if (-not $ev.brokerClient.brokerClientJs) { Problem "$when`: the linked package has no lib/broker-client.js at $($ev.brokerClient.linkedAt) -- the row's broker client is not there"; $ok = $false }
    if (-not $ev.declaredAsBundle) { Problem "$when`: dsh-plugin-remote-fanout is not named in the profile's dsh.profile.bundles"; $ok = $false }
    if ($ok) {
        Log "placement rows: live layer and composed tree both carry $($script:PLACEMENT_KEYS -join ', '); broker client present; bundle declared"
        Log "placement mode this package will choose: $($ev.modeResolution.resolvesTo) (MESH_PLACEMENT='$($ev.modeResolution.processMESH_PLACEMENT)', MESH_TARGET_NODE='$($ev.modeResolution.processMESH_TARGET_NODE)' at process/user/machine scope)"
        if ($ev.modeResolution.resolvesTo -ne 'broker') {
            Warn "$when`: placement resolves to '$($ev.modeResolution.resolvesTo)', not 'broker' -- the broker will NOT be consulted for a child; MESH_TARGET_NODE or MESH_PLACEMENT is set in an environment the launcher inherits"
        }
    }
    if ($ev.durableAcrossAutosync -eq $false) {
        Warn "$when`: HEAD does not carry the placement rows, so the next PersonalSecretary-HarnessSync tick (every 15 min) will rewrite the live layer from HEAD and take them out again. The running engine keeps what it read at boot; the NEXT restart would not. Commit 'profiles/web/cordis.patch.yml' to make the activation durable."
    }
    return $ok
}

function Get-MeshRoute([int]$enginePort) {
    # `GET /mesh/health` is answered on loopback before sign-in, so this needs no secret (measured
    # 2026-09-17: 200 with a full body while the owner worked). It is the only surface that says which
    # version of the route the RUNNING engine mounted, and therefore the only clean before/after
    # difference there is for activation (b). `node`/`fqdn`/`identityDegraded`/`fqdnSource`/`limits`
    # are all absent on v0.1.0, which is exactly why their absence is asserted as a failure.
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$enginePort/mesh/health" -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 15
        if ($r.StatusCode -ne 200) { return [ordered]@{ status = $r.StatusCode } }
        $j = $r.Content | ConvertFrom-Json
        return [ordered]@{
            status = 200; service = $j.service; host = $j.host; version = $j.version
            node = $j.node; fqdn = $j.fqdn; nodeSource = $j.nodeSource; fqdnSource = $j.fqdnSource
            identityDegraded = $j.identityDegraded; identityReason = $j.identityReason
            oneRunAtATime = $j.limits.oneRunAtATime
            concurrencyPresent = ($null -ne $j.concurrency)
            concurrencyLimit = $j.concurrency.limit
            secretConfigured = $j.auth.secretConfigured
        }
    } catch { return [ordered]@{ status = "ERR: $($_.Exception.Message)" } }
}

function Get-MeshHttpTests([string]$packageDir, [string]$logDir) {
    # THE PACKAGE'S OWN SUITE, because it is the strongest LOCAL statement that the code about to be
    # mounted is the code that was measured (docs/mesh/93 §1: 36 tests green on both machines, and two
    # of them assert the identity defects this window is here to close). It is BOUNDED: a suite that
    # does not finish inside the budget is an unknown state, and this window does not restart into an
    # unknown state. Start-Process with a redirect is deliberate -- Node block-buffers into a pipe and
    # the child needs a file handle (docs/mesh/90 §8.4).
    $t = [ordered]@{ ran = $false }
    $node = (Get-Command node -ErrorAction SilentlyContinue).Source
    $testFile = Join-Path $packageDir 'test\mesh-http.test.mjs'
    $t.node = $node; $t.testFile = $testFile
    if (-not $node -or -not (Test-Path -LiteralPath $testFile)) { $t.error = 'no node, or no test/mesh-http.test.mjs'; return $t }
    $outFile = Join-Path $logDir 'mesh-http-tests.out.txt'
    $errFile = Join-Path $logDir 'mesh-http-tests.err.txt'
    $t.outputFile = $outFile
    $p = Start-Process -FilePath $node -ArgumentList @('--test', $testFile) -WorkingDirectory $packageDir `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile -NoNewWindow -PassThru
    $t.ran = $true
    if (-not $p.WaitForExit(240000)) {
        try { $p.Kill() } catch { }
        $t.timedOut = $true
        $t.error = 'the suite did not finish within 240 s'
        return $t
    }
    $t.exit = $p.ExitCode
    $text = [string](Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue)
    $mp = [regex]::Match($text, 'pass (\d+)'); if ($mp.Success) { $t.pass = [int]$mp.Groups[1].Value }
    $mf = [regex]::Match($text, 'fail (\d+)'); if ($mf.Success) { $t.fail = [int]$mf.Groups[1].Value }
    $md = [regex]::Match($text, 'duration_ms ([\d.]+)'); if ($md.Success) { $t.durationMs = [double]$md.Groups[1].Value }
    return $t
}

function Get-MeshHttpEvidence([string]$repoRoot, [string]$logDir) {
    <#
    THE SECOND ACTIVATION, verified rather than assumed. Nothing is expected to need installing --
    measured 2026-09-17: the junction already resolves into this checkout and lib/index.js on disk
    already says VERSION 0.2.0 -- but "the bundle exists" is not "the version is right", so the
    transport stream's own installer is asked first, then the deployed code is read from disk, then
    the package's own suite is run.
    #>
    $ev = [ordered]@{}
    $pkg = Join-Path $repoRoot 'packages\plugin-mesh-http'
    $ev.packageDir = $pkg
    $ev.deployedPath = Join-Path $env:DSH_HOME 'profiles\web\node_modules\dsh-plugin-mesh-http'

    # 1. THE TRANSPORT STREAM'S OWN INSTALLER. `--check` changes nothing; applying it is the only
    #    supported path that may touch the junction or the bundle name.
    $installer = Join-Path $pkg 'bin\install-mesh-http.mjs'
    $ev.installer = $installer
    if (Test-Path -LiteralPath $installer) {
        $ck = & node $installer --check 2>&1
        $ev.installerCheckExit = $LASTEXITCODE
        $ev.installerCheckTail = @($ck | Select-Object -Last 10)
        if ($LASTEXITCODE -ne 0) {
            Log "install-mesh-http.mjs --check exited $LASTEXITCODE -- applying the transport stream's own installer"
            $ap = & node $installer 2>&1
            $ev.installerApplyExit = $LASTEXITCODE
            $ev.installerApplyTail = @($ap | Select-Object -Last 10)
            $ck2 = & node $installer --check 2>&1
            $ev.installerCheckExit = $LASTEXITCODE
            $ev.installerCheckTail = @($ck2 | Select-Object -Last 10)
            $ev.installerApplied = $true
        }
    } else { $ev.installerMissing = $true }

    # 2. THE DEPLOYED CODE, read from disk through the junction.
    $ev.deployedIsJunction = $false
    $ev.deployedTarget = $null
    if (Test-Path -LiteralPath $ev.deployedPath) {
        $it = Get-Item -LiteralPath $ev.deployedPath -Force
        $ev.deployedIsJunction = ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        $ev.deployedTarget = [string]$it.Target
        $dIndex = Join-Path $ev.deployedPath 'lib\index.js'
        if (Test-Path -LiteralPath $dIndex) {
            $dt = Get-Content -LiteralPath $dIndex -Raw
            $m = [regex]::Match($dt, "VERSION\s*=\s*'([^']+)'")
            if ($m.Success) { $ev.deployedVersion = $m.Groups[1].Value }
            $ev.deployedIndexSha256 = (Get-FileHash -LiteralPath $dIndex -Algorithm SHA256).Hash.ToLower()
            $ev.deployedIndexBytes = (Get-Item $dIndex).Length
        }
        $dpj = Join-Path $ev.deployedPath 'package.json'
        if (Test-Path -LiteralPath $dpj) { $ev.deployedManifestVersion = [string](Get-Content -LiteralPath $dpj -Raw | ConvertFrom-Json).version }
        $ev.deployedConcurrencyJs = Test-Path -LiteralPath (Join-Path $ev.deployedPath 'lib\concurrency.js')
    } else { $ev.deployedMissing = $true }

    # 3. THIS CHECKOUT, the same two facts.
    $rIndex = Join-Path $pkg 'lib\index.js'
    if (Test-Path -LiteralPath $rIndex) {
        $rt = Get-Content -LiteralPath $rIndex -Raw
        $m = [regex]::Match($rt, "VERSION\s*=\s*'([^']+)'")
        if ($m.Success) { $ev.repoVersion = $m.Groups[1].Value }
        $ev.repoIndexSha256 = (Get-FileHash -LiteralPath $rIndex -Algorithm SHA256).Hash.ToLower()
    }
    $ev.sameCode = ($ev.deployedIndexSha256 -and $ev.repoIndexSha256 -and $ev.deployedIndexSha256 -eq $ev.repoIndexSha256)

    $profPkg = Join-Path $env:DSH_HOME 'profiles\web\package.json'
    $ev.bundleDeclared = $false
    if (Test-Path -LiteralPath $profPkg) { $ev.bundleDeclared = [bool]((Get-Content -LiteralPath $profPkg -Raw) -match 'dsh-plugin-mesh-http') }

    # 4. THE SUITE, unless a human skipped it.
    $ev.tests = if ($SkipMeshHttpTests) { 'skipped (-SkipMeshHttpTests)' } else { Get-MeshHttpTests $pkg $logDir }
    return $ev
}

function Get-DesktopMeshHttp([int]$desktopPort = 3099) {
    # THE MACHINE WHERE v0.2.0 WAS MEASURED (docs/mesh/93: 8 concurrent children, 12/12 answered).
    # Two bounded ssh calls: the desktop's own route, and its copy of the file. Nothing is written on
    # the desktop and its engine is not touched.
    $ssh = Join-Path $env:ProgramFiles 'OpenSSH\ssh.exe'
    $d = [ordered]@{ sshExe = $ssh; host = 'desktop-ts'; port = $desktopPort }
    if (-not (Test-Path -LiteralPath $ssh)) { $d.error = 'no ssh.exe'; return $d }
    $o = & $ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=6 'desktop-ts' "curl -s --max-time 8 http://127.0.0.1:$desktopPort/mesh/health" 2>&1
    $d.healthExit = $LASTEXITCODE
    $raw = (($o -join ' ').Trim())
    # PARSE THE WHOLE BODY, then truncate only for the record. Parsing the truncated copy was a real
    # defect: the desktop answered 0.2.0 with a full fqdn and the window reported "did not answer",
    # because a 400-character prefix of the JSON does not parse.
    if ($LASTEXITCODE -eq 0 -and $raw) {
        try {
            $j = $raw | ConvertFrom-Json
            $d.version = $j.version; $d.node = $j.node; $d.fqdn = $j.fqdn
            $d.identityDegraded = $j.identityDegraded
        } catch { $d.parseError = $_.Exception.Message }
    }
    $d.healthRaw = $raw.Substring(0, [Math]::Min(400, $raw.Length))
    $o2 = & $ssh -o BatchMode=yes -o ConnectTimeout=6 'desktop-ts' 'certutil -hashfile C:\Users\ezabz\code\harness-config\packages\plugin-mesh-http\lib\index.js SHA256' 2>&1
    $d.hashExit = $LASTEXITCODE
    $m = [regex]::Match(($o2 -join ' '), '([0-9a-fA-F]{64})')
    if ($m.Success) { $d.indexSha256 = $m.Groups[1].Value.ToLower() }
    return $d
}

function Assert-MeshHttp($ev, $desktop, [string]$when) {
    $ok = $true
    if ($ev.deployedMissing) { Problem "$when`: nothing is deployed at $($ev.deployedPath)"; $ok = $false }
    elseif (-not $ev.deployedIsJunction) {
        Problem "$when`: $($ev.deployedPath) is a plain directory, not a junction -- a COPY drifts silently from this checkout (install-mesh-http.mjs's own rule)"; $ok = $false
    }
    if (-not $ev.deployedVersion) {
        Problem "$when`: no VERSION constant could be read from the deployed lib/index.js -- the version this window is about to deploy CANNOT BE VERIFIED, so it does not restart"; $ok = $false
    }
    if ($ev.deployedVersion -and $ev.repoVersion -and $ev.deployedVersion -ne $ev.repoVersion) {
        Problem "$when`: the deployed package says $($ev.deployedVersion) and this checkout says $($ev.repoVersion)"; $ok = $false
    }
    if ($ev.deployedIndexSha256 -and $ev.repoIndexSha256 -and -not $ev.sameCode) {
        Problem "$when`: the deployed lib/index.js is not this checkout's file (deployed $(($ev.deployedIndexSha256).Substring(0,16)), repo $(($ev.repoIndexSha256).Substring(0,16)))"; $ok = $false
    }
    if (-not $ev.bundleDeclared) { Problem "$when`: dsh-plugin-mesh-http is not named in the profile's dsh.profile.bundles"; $ok = $false }
    if ($null -ne $ev.installerCheckExit -and $ev.installerCheckExit -ne 0) {
        Problem "$when`: install-mesh-http.mjs --check still exits $($ev.installerCheckExit) after applying it"; $ok = $false
    }
    if ($ev.tests -is [System.Collections.IDictionary]) {
        if ($ev.tests.timedOut) { Problem "$when`: the mesh-http suite did not finish in 240 s -- refusing to restart into an unverified package"; $ok = $false }
        elseif ($ev.tests.error) { Problem "$when`: the mesh-http suite could not be run ($($ev.tests.error))"; $ok = $false }
        elseif ($ev.tests.exit -ne 0 -or $ev.tests.fail -gt 0) {
            Problem "$when`: test/mesh-http.test.mjs reports pass $($ev.tests.pass) / fail $($ev.tests.fail), exit $($ev.tests.exit) -- refusing to restart into a package that does not pass its own suite"; $ok = $false
        } else {
            Log "mesh-http suite: pass $($ev.tests.pass) / fail $($ev.tests.fail), exit $($ev.tests.exit), $([Math]::Round($ev.tests.durationMs)) ms"
        }
    }
    if ($desktop) {
        if ($desktop.version) {
            if ($ev.deployedVersion -and $desktop.version -ne $ev.deployedVersion) {
                Problem "$when`: the desktop -- where v0.2.0 was MEASURED -- runs mesh-http $($desktop.version), and this node would mount $($ev.deployedVersion). STOPPING: this window does not restart into a version other than the one measured working"; $ok = $false
            } elseif ($desktop.indexSha256 -and $ev.repoIndexSha256 -and $desktop.indexSha256 -ne $ev.repoIndexSha256) {
                Problem "$when`: the desktop's lib/index.js ($($desktop.indexSha256.Substring(0,16))) is not this checkout's ($($ev.repoIndexSha256.Substring(0,16))), although both report version $($ev.deployedVersion)"; $ok = $false
            } else {
                Log "cross-node: the desktop runs mesh-http $($desktop.version) with lib/index.js $($desktop.indexSha256.Substring(0,16)) -- the same code this node will mount"
            }
        } else {
            Warn "$when`: the desktop's route did not answer (exit $($desktop.healthExit): $($desktop.healthRaw)), so the version about to be deployed could not be corroborated against the machine where it was measured. Recorded as a warning, not a stop: another machine's absence is not this node's fault."
        }
    }
    return $ok
}

# ═══ STEP 1: THE GATE -- first, cheap, from evidence ══════════════════════════════════════════
Step "STEP 1: the gate -- is any of the owner's work running in the engine on :${Port}?"
$gateStart = Get-Date
$facts = Get-EngineFacts $Port $GatePort -Light
if ($facts.enginePid) {
    $script:lastPid = $facts.enginePid
    $script:lastLoops = $facts.agentLoopsRunning
    $script:lastRunning = $facts.runningFromCensus
}
Log "engine pid $($facts.enginePid), started $($facts.engineStartedAt), sessions live $($facts.sessionsLive)"
Log "agentLoopsRunning=$($facts.agentLoopsRunning) (the phone gate's own reading: $($facts.gateCapacity.loopsRunning))"
Log "sessions whose census status is running: $($facts.runningFromCensus)"
Log ("light pass took {0} ms (token, cookie, /healthz, the gate's capacity route)" -f [int]((Get-Date) - $gateStart).TotalMilliseconds)

if ($facts.error) {
    Problem $facts.error
    $report.steps.gate = $facts
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $refusalPath) | Out-Null
    $facts | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $refusalPath -Encoding utf8
    Decision 'NO-EVIDENCE' 'the engine could not be read, so nothing was restarted and nothing was written'
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host "mesh-restart-when-idle: NO EVIDENCE about the owner's work -- nothing was restarted." -ForegroundColor Yellow
    exit 2
}

# THE GATE, decided from the light pass. ANY running session, or ANY executing agent loop, refuses.
# The second reading -- `/api/session/list`, the only surface that carries titles -- costs 15.8 s and
# 1.38 MB on this engine (measured), so it is taken ONLY when the verdict is DEFER: that is the one
# case where the window owes an explanation of what it found, and it does no work in that case.
$gateOpen = ($facts.runningFromCensus -eq 0) -and ($facts.agentLoopsRunning -eq 0)

if (-not $gateOpen) {
    $gateNames = Get-Date
    # A SHORT BOUND ON THE DEFERRAL PATH, ON PURPOSE. Measured 2026-09-17 at 17 concurrent agent loops:
    # this RPC did not answer inside 40 s, so a longer bound would buy nothing on the common path --
    # it would only cost the wait. The ids are already complete (they come from /healthz); titles are
    # the courtesy, and a failure is reported as a failure. On the OPEN path the full pass asks for
    # the same titles with the longer bound, when the engine is quiet enough to answer.
    $titles = Get-RunningSessionTitles $Port -TimeoutSec 12
    foreach ($k in $titles.Keys) { $facts[$k] = $titles[$k] }
    # Now both readings exist and they can disagree by one, because sessions start and settle between
    # the two calls. That is why the refusal is on the UNION (`> 0`), never on a threshold.
    $gateOpen = ($facts.runningFromCensus -eq 0) -and ($facts.runningFromList -eq 0) -and ($facts.agentLoopsRunning -eq 0)
    Log ("naming pass took {0} ms (/api/session/list, {1} row(s))" -f [int]((Get-Date) - $gateNames).TotalMilliseconds, $(if ($null -ne $facts.sessionRows) { $facts.sessionRows } else { 'NO ANSWER' }))
}
$report.steps.gate = $facts
$report.gateOpen = $gateOpen

if (-not $gateOpen -and -not $ForceGate) {
    Step 'STEP 1 RESULT: DEFERRED -- the owner is working; this window does nothing'
    Log "agentLoopsRunning = $($facts.agentLoopsRunning) (0 means idle); sessions the census calls running = $($facts.runningFromCensus)"
    Log 'the ids below come from the engine''s own census in /healthz; titles come from /api/session/list when it answers'
    Write-Host ''
    Write-Host 'sessions the engine reports as running (id / origin / title), newest first:' -ForegroundColor Yellow
    $printed = @{}
    foreach ($row in $facts.runningSessions) {
        $t = ($row.title -replace '\s+', ' ')
        Write-Host ("  {0}  {1,-9} {2}" -f $row.id, $row.origin, $t.Substring(0, [Math]::Min(90, $t.Length))) -ForegroundColor Yellow
        Log ("  RUNNING {0} origin={1} label={2} title={3}" -f $row.id, $row.origin, $row.label, $t)
        $printed[$row.id] = $true
    }
    foreach ($id in $facts.runningIdsFromCensus) {
        if ($printed.ContainsKey($id)) { continue }
        Write-Host ("  {0}  (the census says running; no title was read)" -f $id) -ForegroundColor Yellow
        Log ("  RUNNING {0} (census only -- its title was not read)" -f $id)
    }
    if ($facts.sessionListError) {
        # A FAILED TITLE READ IS SAID OUT LOUD. An empty answer from an RPC is a refusal, not evidence
        # that nothing is running -- that mistake is the one this system has paid for most.
        Write-Host "  TITLES NOT READ: $($facts.sessionListError)" -ForegroundColor Yellow
        Log "  TITLES NOT READ: $($facts.sessionListError)"
    }
    if ($facts.runningFromCensus -eq 0) {
        Write-Host "  (no session row carries running=true; the refusal is on agentLoopsRunning=$($facts.agentLoopsRunning))" -ForegroundColor Yellow
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $refusalPath) | Out-Null
    $facts | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $refusalPath -Encoding utf8
    Decision 'DEFERRED' "$($facts.runningFromCensus) running session(s), $($facts.agentLoopsRunning) agent loop(s); ids in refusals\latest.json"
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host "mesh-restart-when-idle: DEFERRED -- $($facts.runningFromCensus) running session(s), $($facts.agentLoopsRunning) agent loop(s); nothing was restarted." -ForegroundColor Yellow
    exit 0
}
if (-not $gateOpen) { Warn 'the gate is NOT open and -ForceGate was given -- proceeding anyway (human override)' }
else { Log 'gate: OPEN -- no session is running and no agent loop is executing' }

# ═══ STEP 2: ALREADY DONE? the idempotence marker ══════════════════════════════════════════════
Step 'STEP 2: has this window already restarted into the engine now serving?'
$marker = $null
if (Test-Path -LiteralPath $markerPath) {
    try { $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json } catch { $marker = $null }
}
$report.steps.marker = [ordered]@{ path = $markerPath; found = [bool]$marker }
if ($marker) {
    $report.steps.marker | Add-Member -NotePropertyName recorded -NotePropertyValue $marker -Force
    Log "marker: this window last restarted :$($marker.port) into pid $($marker.newPid) at $($marker.at) (from pid $($marker.oldPid), verified=$($marker.verified))"
    if ("$($marker.newPid)" -eq "$($facts.enginePid)") {
        Log "the engine serving :$Port is pid $($facts.enginePid) -- the very engine this window started. Nothing to do."
        Decision 'ALREADY-DONE' "pid $($facts.enginePid) is the engine this window restarted into at $($marker.at)"
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        Write-Host ''
        Write-Host "mesh-restart-when-idle: already done -- pid $($facts.enginePid) is the engine this window restarted into; no second restart." -ForegroundColor Green
        exit 0
    }
    Log "the engine is now pid $($facts.enginePid), not the pid this window recorded -- the marker is stale, so the window stays armed"
} else {
    Log "no marker at $markerPath -- this window has not restarted this engine, so it stays armed"
}

# ═══ STEP 3: PRE-RESTART SNAPSHOT + the state of the thing being activated ═════════════════════
Step 'STEP 3: pre-restart snapshot, and what the composed configuration says about placement now'
New-RunDir
# THE FULL PASS, now that the gate is open: the listener/process/net/session-file readings and the
# route's own before-state are read ONCE, here, and `$facts` becomes the full object so everything
# downstream (the comparison after the restart) is comparing like with like. The gate's own object
# stays in the record as `steps.gate`.
$facts = Get-EngineFacts $Port $GatePort
Log "full pass: sessions live $($facts.sessionsLive), rows $(if ($null -ne $facts.sessionRows) { $facts.sessionRows } else { 'NO ANSWER' }), running census $($facts.runningFromCensus) / list $(if ($null -ne $facts.runningFromList) { $facts.runningFromList } else { 'NO ANSWER' })"
Log "listener(s) on :${Port}: $($facts.listenersOnPort) (pid(s) $($facts.listenerPids -join ', ')); engine-shaped processes: $($facts.enginesOnPort.Count); session files on disk: $($facts.sessionFilesOnDisk)"
$placementBefore = Get-PlacementEvidence
$report.steps.placementBefore = $placementBefore
$report.steps.snapshot = $facts
SaveRecord 'pre-restart.json' $report | Out-Null
Log "snapshot written to $runDir\pre-restart.json"
Log "placement BEFORE: live layer carries $((@($script:PLACEMENT_KEYS | Where-Object { $placementBefore.liveKeys[$_] }) -join ', ')); composed tree carries $((@($script:PLACEMENT_KEYS | Where-Object { $placementBefore.composedKeys[$_] }) -join ', '))"
if ($placementBefore.durableAcrossAutosync -eq $false) {
    Warn 'HEAD does not carry the placement rows (they are working-tree edits); the install below is what puts them in the live layer, and autosync can take them out again'
}

# ═══ STEP 3B: the SECOND activation -- the route package, verified before anything restarts ═════
Step 'STEP 3B: plugin-mesh-http -- what is deployed, whether it is this checkout, and its own suite'
$meshBefore = Get-MeshHttpEvidence $REPO $runDir
$desktopMesh = Get-DesktopMeshHttp $Port
$meshBefore.desktop = $desktopMesh
$report.steps.meshHttpBefore = $meshBefore
$repoShort = if ($meshBefore.repoIndexSha256) { $meshBefore.repoIndexSha256.Substring(0, 16) } else { 'n/a' }
$deployedShort = if ($meshBefore.deployedIndexSha256) { $meshBefore.deployedIndexSha256.Substring(0, 16) } else { 'n/a' }
Log "deployed: version '$($meshBefore.deployedVersion)' at $($meshBefore.deployedPath) (junction=$($meshBefore.deployedIsJunction), target '$($meshBefore.deployedTarget)', file $deployedShort)"
Log "checkout: version '$($meshBefore.repoVersion)', lib/index.js $repoShort; byte-identical file: $($meshBefore.sameCode); declared as a bundle: $($meshBefore.bundleDeclared)"
Log "the RUNNING engine's route says: version '$($facts.meshHealth.version)', node '$($facts.meshHealth.node)', fqdn '$($facts.meshHealth.fqdn)', oneRunAtATime $($facts.meshHealth.oneRunAtATime)"
$meshOk = Assert-MeshHttp $meshBefore $desktopMesh 'before the restart'
if (-not $meshOk) {
    Step 'STOPPING BEFORE THE RESTART: the route package could not be verified'
    SaveRecord 'stopped-before-restart.json' $report | Out-Null
    Decision 'FAILED-BEFORE-RESTART' 'plugin-mesh-http could not be verified, so NOTHING was restarted (see the problems above)'
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host 'mesh-restart-when-idle: the route package could not be verified -- NOTHING WAS RESTARTED.' -ForegroundColor Red
    exit 1
}

if ($DryRun) {
    Step 'DRY RUN COMPLETE'
    Log "the gate is $(if ($gateOpen) { 'OPEN' } else { 'OVERRIDDEN by -ForceGate' }). The window would now run: pwsh $INNER -SkipJournal -Port $Port -GatePort $GatePort"
    Log 'and would verify afterwards, in this order:'
    Log '  a. the placement rows (placement / brokerSsh / brokerUrl) present in BOTH the live patch layer and the COMPOSED tree, with lib/broker-client.js behind them;'
    Log '  b. GET /mesh/health reports the version this checkout carries (not what the running engine has now), a non-empty fqdn, node === fqdn.split(".")[0], identityDegraded false, oneRunAtATime false and a published concurrency limit;'
    Log '  c. GET /healthz 200 on a FRESH launch token, its pid equal to the listener''s on the port;'
    Log '  d. exactly ONE listener on the port, owned by exactly ONE engine-shaped process on the same DSH_HOME;'
    Log '  e. the phone gate still reaches the engine: /mesh/capacity 200 with a non-null engine reading;'
    Log '  f. the session corpus did not shrink.'
    Log "Dry run: nothing was installed and nothing was restarted. The records written are this run's own stamp directory ($runDir) and the two rolling logs."
    Decision 'DRY-RUN' 'gate open (forced); the inner window was NOT called and nothing was restarted'
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    exit 0
}

# ═══ STEP 4: HAND OVER to the machine's proven window ═════════════════════════════════════════
Step "STEP 4: the window itself -- $INNER -SkipJournal"
if (-not (Test-Path -LiteralPath $INNER)) {
    Problem "no window script at $INNER -- refusing to restart the engine by any other path"
    SaveRecord 'stopped-before-restart.json' $report | Out-Null
    Decision 'FAILED-BEFORE-RESTART' "the inner window script is missing: $INNER"
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host 'mesh-restart-when-idle: the window script is missing -- NOTHING WAS RESTARTED.' -ForegroundColor Red
    exit 1
}
$innerArgs = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $INNER, '-SkipJournal', '-Port', "$Port", '-GatePort', "$GatePort", '-WaitSeconds', "$WaitSeconds")
if ($ForceGate) { $innerArgs += '-ForceGate' }
Log "  pwsh $($innerArgs -join ' ')"
# The inner window gates again (defence in depth: the owner may have started work since step 1), then
# installs/verifies, then restarts ONCE by `dshw.ps1 restart`, then verifies.
$innerOut = & pwsh @innerArgs 2>&1
$innerExit = $LASTEXITCODE
foreach ($l in $innerOut) { Log "  inner: $l" }
$report.steps.inner = [ordered]@{ exit = $innerExit; tail = @($innerOut | Select-Object -Last 40) }
$stampInner = @(Get-ChildItem -LiteralPath (Join-Path $env:DSH_HOME 'mesh\restart-0700') -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1)
$report.steps.inner.runDir = $(if ($stampInner) { $stampInner[0].FullName } else { $null })
Log "inner window exited $innerExit; its own records are in $($report.steps.inner.runDir)"
if ($innerExit -ne 0) {
    Problem "the inner window exited $innerExit -- read $($report.steps.inner.runDir)\run.log; if it stopped before its restart step, nothing was restarted"
    SaveRecord 'stopped-before-restart.json' $report | Out-Null
    Decision 'FAILED-BEFORE-RESTART' "the inner window exited $innerExit"
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host "mesh-restart-when-idle: the window reported $innerExit; see $runDir and $($report.steps.inner.runDir)" -ForegroundColor Red
    exit 1
}

# ═══ STEP 5: VERIFY -- beginning with the one thing this window exists for ════════════════════
Step "STEP 5: verify the restarted engine on :$Port"
$oldPid = $facts.enginePid
$report.restart = [ordered]@{ oldPid = $oldPid }
$after = $null
$deadline = (Get-Date).AddSeconds([Math]::Max(30, $WaitSeconds))
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $after = Get-EngineFacts $Port $GatePort
    if ($after.enginePid -and "$($after.enginePid)" -ne "$oldPid" -and $after.listenersOnPort -eq 1) { break }
}
$report.steps.after = $after
if (-not $after -or -not $after.enginePid) {
    Problem 'the engine does not answer /healthz after the restart'
} elseif ("$($after.enginePid)" -eq "$oldPid") {
    Problem "the engine on :$Port is still pid $oldPid -- it did not restart"
} else {
    Log "engine back on :${Port} pid $($after.enginePid) (was $oldPid), started $($after.engineStartedAt)"
}

$verify = [ordered]@{
    at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    oldPid = $oldPid
    newPid = $(if ($after) { $after.enginePid } else { $null })
    # 1. SINGLE PROCESS ON THE PORT.
    listenersOnPort = $(if ($after) { $after.listenersOnPort } else { $null })
    listenerPids = $(if ($after) { $after.listenerPids } else { $null })
    engineShapedProcesses = $(if ($after) { $after.enginesOnPort } else { $null })
    healthz = $null
    dshHome = $null
    gateCapacity = $null
    placement = $null
    corpus = $null
}
if ($after -and $after.enginePid) {
    $verify.healthz = 200
    $verify.healthzPidMatchesListener = (@($after.listenerPids) -contains $after.enginePid)
    $verify.freshLaunchToken = ($null -ne $after.tokenFingerprint -and "$($after.tokenFingerprint)" -ne "$($facts.tokenFingerprint)")
    $verify.engineArgv = $after.engineArgv

    if ($after.listenersOnPort -ne 1) { Problem "there are $($after.listenersOnPort) listeners on :$Port, not one -- this window must leave EXACTLY ONE engine on the port" }
    else { Log "one listener on :$Port (pid $($after.listenerPids -join ','))" }
    if ($after.enginesOnPort.Count -ne 1) {
        Problem "$($after.enginesOnPort.Count) engine-shaped node process(es) serve :$Port, not one: $(($after.enginesOnPort | ForEach-Object { $_.pid }) -join ', ')"
    } else { Log "one engine-shaped node process serves :$Port (pid $($after.enginesOnPort[0].pid))" }
    if (-not $verify.healthzPidMatchesListener) { Problem "/healthz reports pid $($after.enginePid) but the listener on :$Port is owned by $($after.listenerPids -join ',')" }
    if (-not $verify.freshLaunchToken) { Problem "the launch token did not change across the restart (fingerprint $($after.tokenFingerprint)) -- this may be the OLD process still serving" }
    else { Log "GET /healthz 200 on a FRESH launch token ($($after.tokenFingerprint)) -- a new process, not the old one" }

    # 2. THE SAME DSH_HOME. The engine reports `env.dshHome` as null on this build (measured), so the
    # evidence is assembled from three things that are checkable rather than from a field that is not
    # there: the launcher's own slot record for this port (dshw owns the one-home rule), the token that
    # only exists under this home's launcher log, and the session corpus that did not move.
    $slot = $after.launcherSlot
    $verify.dshHome = [ordered]@{
        processDSH_HOME = $after.dshHomeProcess
        reportedByHealthz = $after.dshHomeReportedByHealthz
        reportedByHealthzIsNull = ($null -eq $after.dshHomeReportedByHealthz)
        launcherStateFile = $(if ($slot) { $slot.stateFile } else { $null })
        launcherRecordedPid = $(if ($slot) { $slot.pid } else { $null })
        launcherRecordedPidMatchesEngine = $(if ($slot) { "$($slot.pid)" -eq "$($after.enginePid)" } else { $false })
        launcherLogUnderThisHome = $(if ($slot -and $slot.log) { $slot.log -like "$($after.dshHomeProcess)*" } else { $false })
        tokenFileUnderThisHome = ($after.tokenFile -like "$($after.dshHomeProcess)*")
    }
    if (-not $verify.dshHome.launcherRecordedPidMatchesEngine) {
        Problem "the multi-window launcher's slot record does not name pid $($after.enginePid) -- the engine serving :$Port is not the one this DSH_HOME's launcher started"
    } elseif (-not $verify.dshHome.tokenFileUnderThisHome) {
        Problem "the live token was found outside $($after.dshHomeProcess) ($($after.tokenFile))"
    } else {
        Log "same DSH_HOME: launcher slot names pid $($after.enginePid), its log and the live token are both under $($after.dshHomeProcess) (healthz reports env.dshHome=$($after.dshHomeReportedByHealthz))"
    }
    $verify.corpus = [ordered]@{
        sessionFilesBefore = $facts.sessionFilesOnDisk; sessionFilesAfter = $after.sessionFilesOnDisk
        sessionRowsBefore = $facts.sessionRows; sessionRowsAfter = $after.sessionRows
        unchanged = ($after.sessionFilesOnDisk -eq $facts.sessionFilesOnDisk)
    }
    Log "session corpus: $($facts.sessionFilesOnDisk) -> $($after.sessionFilesOnDisk) session file(s); $($facts.sessionRows) -> $($after.sessionRows) row(s)"
    if ($facts.sessionFilesOnDisk -gt 0 -and $after.sessionFilesOnDisk -lt $facts.sessionFilesOnDisk) {
        Problem "session file count dropped: $($facts.sessionFilesOnDisk) -> $($after.sessionFilesOnDisk)"
    } elseif ($facts.sessionRows -gt 0 -and $after.sessionRows -lt $facts.sessionRows) {
        Problem "session rows dropped: $($facts.sessionRows) -> $($after.sessionRows)"
    }

    # 3. THE PHONE GATE MUST STILL REACH THE ENGINE.
    $verify.gateCapacity = Get-GateCapacity $GatePort
    if ($verify.gateCapacity.status -ne 200) { Problem "the phone gate's /mesh/capacity returned $($verify.gateCapacity.status)" }
    elseif ($verify.gateCapacity.agentsIsNull) { Problem 'the phone gate answers but its engine reading is null -- the gate cannot reach the restarted engine' }
    else { Log "phone gate /mesh/capacity 200 for node $($verify.gateCapacity.node); it sees $($verify.gateCapacity.sessionsLive) session(s) and $($verify.gateCapacity.loopsRunning) loop(s)" }

    # 4. THE PLACEMENT ROWS -- one of the two reasons this window exists.
    $verify.placement = Get-PlacementEvidence
    Assert-Placement $verify.placement 'after the restart' | Out-Null

    # 4b. THE SECOND ACTIVATION, BY EFFECT: the route's version and its identity. v0.1.0's body has no
    #     `identityDegraded`, no `fqdnSource` and no `concurrency`, and its `limits.oneRunAtATime` is
    #     true -- so every one of these checks FAILS if the old bundle is still the one mounted.
    $r = $after.meshHealth
    $verify.meshRouteBefore = $facts.meshHealth
    $verify.meshRouteAfter = $r
    if (-not $r -or $r.status -ne 200) {
        Problem "GET /mesh/health on :$Port did not answer 200 after the restart (status $($r.status))"
    } else {
        Log "route after the restart: version '$($r.version)' (was '$($facts.meshHealth.version)'), node '$($r.node)', fqdn '$($r.fqdn)', identityDegraded '$($r.identityDegraded)', oneRunAtATime '$($r.oneRunAtATime)', concurrency limit '$($r.concurrencyLimit)'"
        $want = if ($meshBefore.deployedVersion) { $meshBefore.deployedVersion } else { '0.2.0' }
        if ("$($r.version)" -ne "$want") {
            Problem "the route reports version '$($r.version)', not '$want' -- the new bundle did NOT mount"
        } else { Log "route version $($facts.meshHealth.version) -> $($r.version): the second activation this restart was for" }
        if (-not $r.fqdn) {
            Problem "the route still reports an EMPTY fqdn -- the boot-time tailnet read was degraded again (docs/mesh/93 §8.1)"
        } elseif ("$($r.node)" -ne (("$($r.fqdn)") -split '\.')[0]) {
            Problem "node '$($r.node)' is not the first label of fqdn '$($r.fqdn)' -- the invariant node === fqdn.split('.')[0] is broken (docs/mesh/93 §8.2)"
        } else { Log "identity: node '$($r.node)' IS the first label of fqdn '$($r.fqdn)'" }
        if ($r.identityDegraded -ne $false) {
            Problem "identityDegraded is '$($r.identityDegraded)' -- either the node reports a name it cannot corroborate, or the field does not exist, which is v0.1.0's shape"
        }
        if ($r.oneRunAtATime -ne $false) {
            Problem "limits.oneRunAtATime is '$($r.oneRunAtATime)' -- the one-child ceiling is STILL in force, so the new route did not mount"
        }
        if (-not $r.concurrencyPresent) {
            Problem 'the route publishes no concurrency block -- the new route publishes its derived limit and every term behind it'
        } else { Log "the node now publishes a derived concurrency limit of $($r.concurrencyLimit), with oneRunAtATime false" }
    }

    # 5. THE BROKER ITSELF, as far as one bounded probe can tell. WARN-ONLY: a broker that is down is a
    # mesh-wide condition and not a reason to call this restart failed, but it is the difference between
    # "placement is configured" and "placement will work".
    $ssh = Join-Path $env:ProgramFiles 'OpenSSH\ssh.exe'
    if (Test-Path -LiteralPath $ssh) {
        $burl = 'http://localhost:3091'
        $pb = & $ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 secratary-ts "curl -s -o /dev/null -w %{http_code} $burl/health" 2>&1
        $verify.brokerProbe = [ordered]@{ ssh = $ssh; target = 'secratary-ts'; url = $burl; exit = $LASTEXITCODE; output = (($pb -join ' ').Trim()) }
        if ($LASTEXITCODE -eq 0 -and ($pb -join '') -match '200') { Log "placement broker reachable: $burl/health -> 200" }
        else { Warn "the placement broker probe did not answer 200 (exit ${LASTEXITCODE}: $(($pb -join ' ').Trim().Substring(0, [Math]::Min(160, ($pb -join ' ').Trim().Length)))) -- the rows are in place, but a child would fall to a reported broker-unreachable failure" }
    } else { $verify.brokerProbe = 'skipped: no ssh.exe' }
} else {
    $verify.corpus = $null
}

$report.steps.verify = $verify
SaveRecord 'post-restart.json' $report | Out-Null
Log "verification written to $runDir\post-restart.json"

# ═══ STEP 6: THE MARKER -- written because the RESTART happened, never because it verified ═════
Step 'STEP 6: the idempotence marker'
if ($after -and $after.enginePid -and "$($after.enginePid)" -ne "$oldPid") {
    # THE MARKER IS KEYED ON THE RESTART, NOT ON THE VERIFICATION, and that is deliberate: if the
    # restart happened and the verification then failed, marking it "done" stops a 15-minute schedule
    # from restarting the owner's engine again and again while someone reads the failure. `verified`
    # is recorded inside the marker so a failure is never hidden by the fact that the marker exists.
    $markerValue = [ordered]@{
        at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        machine = $env:COMPUTERNAME
        port = $Port
        oldPid = $oldPid
        newPid = $after.enginePid
        engineStartedAt = $after.engineStartedAt
        verified = ($problems.Count -eq 0)
        problems = @($problems)
        warnings = @($warnings)
        runDir = $runDir
        innerRunDir = $report.steps.inner.runDir
    }
    $markerValue | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $markerPath -Encoding utf8
    Log "marker written: $markerPath (newPid $($after.enginePid), verified $($markerValue.verified))"
} else {
    Log 'no marker written: no restart was observed, so the window stays armed'
}

Step 'ROLLBACK (the commands, not an action)'
Log "  1. pwsh $REPO\scripts\mesh-provider-install.ps1 -Rollback     # takes the rows and the bundle names out"
Log "  2. pwsh $REPO\multi-window\dshw.ps1 restart                   # ONE restart puts the ENGINE back"
Log "  3. Disable-ScheduledTask -TaskName 'DSH Mesh Restart When Idle'"
Log "  4. Remove-Item '$markerPath'   # only if a future idle tick should be allowed another restart"

Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
Write-Host ''
if ($problems.Count -gt 0) {
    Decision 'RESTARTED-WITH-PROBLEMS' "$($problems.Count) problem(s): $($problems -join ' | ')"
    Write-Host "mesh-restart-when-idle: restarted into pid $($after.enginePid) with $($problems.Count) problem(s); see $runDir" -ForegroundColor Red
    exit 1
}
Decision 'RESTARTED-VERIFIED' "pid $oldPid -> $($after.enginePid); placement rows present in the composed configuration; records in $runDir"
Write-Host "mesh-restart-when-idle: restarted $oldPid -> $($after.enginePid) and verified; records in $runDir" -ForegroundColor Green
exit 0
