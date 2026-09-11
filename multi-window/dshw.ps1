<#
.SYNOPSIS
    dshw - run, restore and supervise a set of independent DSH windows.

.DESCRIPTION
    One DSH server process per window slot, on its own port, with its own isolated
    browser profile (so each window has its own cookie jar and its own "last
    session"). State lives in <repo>/multi-window/windows.json, runtime state in
    <stateDir>/state.json, logs in <logDir>/<port>.log.

    Commands:
      dshw up                 start every enabled slot that is not already running,
                              then open its window
      dshw down               stop every server this launcher started
      dshw restart            down, then up
      dshw status             per-slot truth: port listening, pid alive, window count
      dshw new                start + open the first unused slot (the "new window" button)
      dshw open <slot>        open (or focus) a window for an already-running slot
      dshw stop <slot>        stop one slot
      dshw restart <slot>     restart one slot
      dshw logs <slot>        tail that slot's log
      dshw autostart on|off   register/remove the logon task that runs: dshw up -Windows auto
      dshw doctor             verify prerequisites and report exactly what is missing

    Exit codes: 0 ok, 1 nothing to do / partial, 2 bad usage, 3 precondition failed.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'restart', 'status', 'windows', 'new', 'open', 'stop', 'logs', 'health', 'autostart', 'watchdog', 'doctor', 'help')]
    [string]$Command = 'status',

    [Parameter(Position = 1)]
    [string]$Slot = '',

    [string]$ConfigPath = '',
    [int]$Lines = 40,
    [ValidateSet('yes', 'no', 'auto')]
    [string]$WindowsMode = 'yes',
    [switch]$Json,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ── paths ───────────────────────────────────────────────────────────────────
$RepoRoot   = Split-Path -Parent $PSScriptRoot           # multi-window/ -> repo root
if (-not $ConfigPath) { $ConfigPath = Join-Path $PSScriptRoot 'windows.json' }
if (-not (Test-Path $ConfigPath)) { Write-Error "config not found: $ConfigPath"; exit 3 }

$Cfg    = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$StateDir = $Cfg.server.stateDir
$LogDir   = $Cfg.server.logDir
New-Item -ItemType Directory -Force -Path $StateDir, $LogDir | Out-Null
$StatePath = Join-Path $StateDir 'state.json'

function Get-State {
    $slots = @{}
    if (Test-Path $StatePath) {
        try {
            $raw = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
            foreach ($prop in $raw.slots.PSObject.Properties) { $slots[$prop.Name] = $prop.Value }
        } catch { Write-Warning "state.json unreadable ($StatePath); treating as empty" }
    }
    return @{ slots = $slots }
}

function Save-State($state) {
    $json = [pscustomobject]@{ slots = $state.slots } | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($StatePath, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-SlotRecord($state, $port) {
    $p = "$port"
    if ($state.slots.ContainsKey($p)) { return $state.slots[$p] }
    return $null
}

function Set-SlotRecord($state, $port, $record) {
    $state.slots["$port"] = $record
}

# Read an optional property without tripping StrictMode (config files legitimately omit keys).
function Get-Prop($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    $p = $obj.PSObject.Properties[$name]
    if ($p) { return $p.Value }
    return $null
}

# ── node / dsh resolution ───────────────────────────────────────────────────
function Resolve-NodeExe {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if (-not $cmd) { throw 'node.exe not found on PATH' }
    return $cmd.Source
}

function Resolve-DshBin {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js'),
        (Join-Path $env:USERPROFILE '.dsh\profiles\node_modules\@deepseek-ai\dsh\lib\bin.js')
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    # fall back: the .bin shim's target, discovered from the shim itself
    $shim = Get-Command dsh -ErrorAction SilentlyContinue
    if ($shim) {
        $ps1 = $shim.Source
        if (Test-Path $ps1) {
            $m = Select-String -LiteralPath $ps1 -Pattern '(@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js)' -AllMatches
            if ($m) { return $m.Matches[0].Value }
        }
    }
    throw 'cannot locate @deepseek-ai/dsh/lib/bin.js'
}

function Get-EdgePath {
    $kind = if ($Cfg.browser.kind) { $Cfg.browser.kind } else { 'edge' }
    $names = if ($kind -eq 'chrome') { @('chrome.exe') } else { @('msedge.exe') }
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application'),
               (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application'))
    foreach ($n in $names) {
        foreach ($r in $roots) {
            if (-not $r) { continue }
            $sub = if ($n -eq 'msedge.exe') { 'Microsoft\Edge\Application' } else { 'Google\Chrome\Application' }
            foreach ($p in @((Join-Path $r $n), (Join-Path (Join-Path $r $sub) $n))) {
                if (Test-Path $p) { return $p }
            }
        }
    }
    return $null
}

# ── topology ────────────────────────────────────────────────────────────────
# single: one server on primaryPort, every window attaches to it.
# multi : each slot gets its own server on its own port.
function Get-Mode { [string]$(if ($Cfg.mode) { $Cfg.mode } else { 'single' }) }

function Get-PrimaryPort { return [int]$Cfg.primaryPort }

function Resolve-SlotPort($slot, [int]$index) {
    if ((Get-Mode) -eq 'multi') {
        $base = 3081
        $mp = $Cfg.PSObject.Properties['_multiPorts']
        if ($mp -and $mp.Value -and $mp.Value.basePort) { $base = [int]$mp.Value.basePort }
        return [int]($base + $index)
    }
    return [int](Get-PrimaryPort)
}

function Resolve-SlotInfo($slot, [int]$index) {
    $p = Resolve-SlotPort $slot $index
    return [pscustomobject]@{
        label     = $slot.label
        profile   = $slot.profile
        workspace = $slot.workspace
        enabled   = [bool]$slot.enabled
        port      = [int]$p
        index     = $index
        position  = (Get-Prop $slot 'position')
        size      = (Get-Prop $slot 'size')
    }
}

function Get-Slots {
    $out = @()
    for ($i = 0; $i -lt $Cfg.windows.Count; $i++) { $out += Resolve-SlotInfo $Cfg.windows[$i] $i }
    return $out
}

function Get-ServerSlot {
    $slots = Get-Slots
    if (Get-Mode -eq 'multi') { return $slots }
    return @($slots | Where-Object { $_.port -eq (Get-PrimaryPort) } | Select-Object -First 1)
}

# Readiness requires the URL line from THIS launch. A stale log holds the previous run's
# line, so the file is cleared before start and both the child and the parent read only
# content written after that point.
function Get-LogOffset([string]$path) {
    if (Test-Path $path) { return (Get-Item -LiteralPath $path).Length }
    return 0
}

function Read-NewLog([string]$path, [long]$offset) {
    if (-not (Test-Path $path)) { return '' }
    try {
        # FileShare.ReadWrite is required: the server holds the file open for writing.
        $fs = New-Object System.IO.FileStream($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            if ($offset -gt $fs.Length) { $offset = 0 }
            [void]$fs.Seek($offset, [System.IO.SeekOrigin]::Begin)
            $buf = New-Object byte[] ($fs.Length - $offset)
            $read = $fs.Read($buf, 0, $buf.Length)
            if ($read -le 0) { return '' }
            return [System.Text.Encoding]::UTF8.GetString($buf, 0, $read)
        } finally { $fs.Dispose() }
    } catch { return '' }
}

# Readiness = the process is alive, the port is listening, and the log shows the URL line.
# Any one of those alone has produced a false positive at some point in this script's
# development: a stale log line, a bound port with a half-built tree, a dead child.
function Wait-ServerReady([string]$log, [long]$offset, [int]$timeoutSeconds, $proc, [int]$port) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    $sawUrl = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if ($proc -and $proc.HasExited) { return $null }
        if (-not $sawUrl) {
            $text = Read-NewLog $log $offset
            if ($text) {
                $m = [regex]::Match($text, 'dsh web:\s*(\S+)')
                if ($m.Success) { $sawUrl = $m.Groups[1].Value }
            }
        }
        if ($sawUrl -and (Test-PortInUse $port)) { return $sawUrl }
    }
    return $null
}

# ── port / process helpers ──────────────────────────────────────────────────
# One TCP connection table per call, not per lookup: an unfiltered
# Get-NetTCPConnection is the single most expensive thing this script does.
function Get-ListenTable {
    $age = Get-Variable -Name ListenTableAge -Scope Script -ValueOnly -ErrorAction SilentlyContinue
    if ($age -and ((Get-Date) - $age).TotalSeconds -lt 5) { return $script:ListenTable }
    $script:ListenTable = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
    $script:ListenTableAge = Get-Date
    return $script:ListenTable
}

function Test-PortInUse([int]$port, $table = $null) {
    if (-not $table) { $table = Get-ListenTable }
    return [bool]($table | Where-Object { $_.LocalPort -eq $port })
}

function Get-PortOwner([int]$port, $table = $null) {
    if (-not $table) { $table = Get-ListenTable }
    $conn = $table | Where-Object { $_.LocalPort -eq $port } | Select-Object -First 1
    if (-not $conn) { return $null }
    try { return Get-Process -Id $conn.OwningProcess -ErrorAction Stop } catch { return $null }
}

function Get-Descendants([int]$rootPid) {
    $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId
    $out = New-Object System.Collections.Generic.List[int]
    $frontier = @($rootPid)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($f in $frontier) {
            foreach ($c in $all | Where-Object { $_.ParentProcessId -eq $f }) {
                if ($out -notcontains $c.ProcessId) { $out.Add($c.ProcessId); $next += $c.ProcessId }
            }
        }
        $frontier = $next
    }
    return $out
}

function Stop-ServerTree([int]$port, $record, $table = $null) {
    $pids = @()
    if ($record -and $record.pid) { $pids += $record.pid }
    $owner = Get-PortOwner $port $table
    if ($owner) { $pids += $owner.Id }
    $pids = $pids | Select-Object -Unique
    if (-not $pids) { return $false }
    foreach ($p in $pids) {
        $kids = Get-Descendants $p
        # children first, then the parent
        foreach ($k in ($kids | Sort-Object -Descending)) { Stop-Process -Id $k -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Milliseconds 250
        if (-not (Test-PortInUse $port)) { break }
    }
    return -not (Test-PortInUse $port)
}

# ── server lifecycle ────────────────────────────────────────────────────────
function Get-ServerInvocation($slotCfg) {
    $node = Resolve-NodeExe
    $bin  = Resolve-DshBin
    $port = [int]$slotCfg.port
    # One log file per launch, named for the launch: a fixed <port>.log cannot be trusted
    # because the server inherits the handle and recreates it after a delete, which produced
    # a 180s false "no URL" timeout on 2026-09-11.
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $log  = Join-Path $LogDir "$port-$stamp.log"
    $err  = Join-Path $LogDir "$port-$stamp.err.log"
    $cwd  = if ($slotCfg.workspace -and (Test-Path $slotCfg.workspace)) { $slotCfg.workspace } else { (Get-Location).Path }
    return [pscustomobject]@{ node = $node; bin = $bin; port = $port; log = $log; err = $err; cwd = $cwd
                              latest = (Join-Path $LogDir "$port.log") }
}

# Keep a stable <port>.log as the "latest" pointer for `dshw logs`, without ever touching a
# log a launch is still writing.
function Update-LatestLog($inv) {
    try {
        if (Test-Path $inv.log) { Copy-Item -LiteralPath $inv.log -Destination $inv.latest -Force -ErrorAction SilentlyContinue }
        # keep only the newest 10 launch logs per port
        $prefix = "$($inv.port)-"
        $old = Get-ChildItem $LogDir -Filter "$prefix*" -File -ErrorAction SilentlyContinue |
               Sort-Object LastWriteTime -Descending | Select-Object -Skip 10
        foreach ($f in $old) { Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue }
    } catch { }
}

function Start-SlotServer($slotCfg) {
    $inv = Get-ServerInvocation $slotCfg
    if (Test-PortInUse $inv.port) { throw "port $($inv.port) already in use" }
    $p = Start-Process -FilePath $inv.node -ArgumentList @($inv.bin, 'web', '--port', "$($inv.port)", '--no-open') `
            -WorkingDirectory $inv.cwd -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $inv.log -RedirectStandardError $inv.err

    $url = Wait-ServerReady $inv.log 0 ([int]$Cfg.server.startTimeoutSeconds) $p $inv.port
    if (-not $url) {
        if ($p.HasExited) {
            $tail = if (Test-Path $inv.err) { (Get-Content -LiteralPath $inv.err -Tail 15) -join "`n" } else { '(no stderr)' }
            throw "server on port $($inv.port) exited with code $($p.ExitCode). stderr tail:`n$tail"
        }
        throw "server on port $($inv.port) did not report a URL within $($Cfg.server.startTimeoutSeconds)s (see $($inv.log))"
    }

    return [pscustomobject]@{ pid = $p.Id; url = $url; log = $inv.log; err = $inv.err
                              workspace = $inv.cwd; startedAt = (Get-Date).ToString('o') }
}

# Public entry point: launches exactly one slot's server in this process and waits for it.
function Start-OneSlotServer($slotCfg) {
    $inv = Get-ServerInvocation $slotCfg
    $r = Start-SlotServer $slotCfg
    Update-LatestLog $inv
    return $r
}

# Start several slots at once: each child pwsh launches its own server DETACHED and
# writes a readiness file naming that server's real pid, then exits. The parent waits
# on the readiness files. The child must never wait for the server: were it to, the
# parent would record the launcher's pid as the server's and `down` would not find it.
function Start-SlotServerParallel($slots) {
    $readies = @{}
    foreach ($slot in $slots) {
        $inv = Get-ServerInvocation $slot
        $ready = Join-Path $StateDir "ready-$($inv.port).json"
        if (Test-Path $ready) { Remove-Item -LiteralPath $ready -Force -ErrorAction SilentlyContinue }
        $readies["$($inv.port)"] = $ready
        $payload = @{
            node = $inv.node; bin = $inv.bin; port = $inv.port; cwd = $inv.cwd
            log = $inv.log; err = $inv.err; ready = $ready
        } | ConvertTo-Json -Compress
        # The child only launches the server detached and records its pid; it never waits,
        # never deletes a log, and never touches the parent's own files.
        $child = @'
$json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DSHW_PAYLOAD))
$p = $json | ConvertFrom-Json
$out = @{ ok = $false; port = $p.port; pid = $null; error = $null }
try {
    $proc = Start-Process -FilePath $p.node -ArgumentList @($p.bin, 'web', '--port', "$($p.port)", '--no-open') `
        -WorkingDirectory $p.cwd -WindowStyle Hidden -PassThru -RedirectStandardOutput $p.log -RedirectStandardError $p.err
    $out.pid = $proc.Id
    $out.ok = $true
} catch { $out.error = $_.Exception.Message }
[System.IO.File]::WriteAllText($p.ready, ($out | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
'@
        $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($child))
        Start-Process -FilePath (Get-Command pwsh).Source -WindowStyle Hidden `
            -ArgumentList @('-NoProfile', '-EncodedCommand', $enc) `
            -Environment @{ DSHW_PAYLOAD = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload)) } | Out-Null
    }

    $results = @{}
    foreach ($port in $readies.Keys) {
        $slot = $slots | Where-Object { "$($_.port)" -eq "$port" } | Select-Object -First 1
        $inv  = Get-ServerInvocation $slot
        $r = [pscustomobject]@{ pid = $null; url = $null; log = $inv.log; err = $inv.err
                                workspace = $inv.cwd; startedAt = (Get-Date).ToString('o'); error = $null }
        $r.url = Wait-ServerReady $inv.log 0 ([int]$Cfg.server.startTimeoutSeconds) $null ([int]$port)
        Update-LatestLog $inv
        # the pid comes from the readiness file the launcher child wrote
        if (Test-Path $readies[$port]) {
            try {
                $j = Get-Content -Raw -LiteralPath $readies[$port] | ConvertFrom-Json
                if ($j.pid) { $r.pid = $j.pid }
                if (-not $r.url -and $j.error) { $r.error = $j.error }
            } catch { }
        }
        if (-not $r.url) {
            $errText = Read-NewLog $inv.err 0
            if ($errText -and ($errText -match 'EADDRINUSE|Error:|error')) {
                $r.error = ($errText.Trim() -split "`n" | Select-Object -Last 3) -join ' | '
            } else {
                $r.error = "no URL within $($Cfg.server.startTimeoutSeconds)s (see $($inv.log))"
            }
        }
        if (-not $r.pid -and -not $r.error) {
            $owner = Get-PortOwner ([int]$port)
            if ($owner) { $r.pid = $owner.Id } else { $r.error = 'server reported a URL but no process owns the port' }
        }
        $results[$port] = $r
    }
    return $results
}

function Open-SlotWindow($slot, $state) {
    $exe = Get-EdgePath
    if (-not $exe) { throw 'no Edge/Chrome binary found' }

    # In single mode every window talks to the primary server, but each keeps its
    # own browser profile so its cookie jar and "last session" are its own.
    $targetPort = if (Get-Mode -eq 'multi') { $slot.port } else { Get-PrimaryPort }
    $rec = Get-SlotRecord $state $targetPort

    $profDir = Join-Path $Cfg.browser.profileRoot $slot.profile
    New-Item -ItemType Directory -Force -Path $profDir | Out-Null

    $target = if ($rec -and $rec.url) { $rec.url } else { "http://127.0.0.1:$targetPort/" }
    $label = if ($slot.label) { $slot.label } else { "$targetPort" }
    # NOTE (measured 2026-09-11, Edge 152 on Windows): --window-name is a no-op here and
    # the window caption is the page <title>. Geometry must be supplied on every launch,
    # and it only takes effect because each window has its own --user-data-dir.
    $winArgs = @(
        "--app=$target",
        "--user-data-dir=$profDir",
        "--no-first-run",
        "--no-default-browser-check",
        # Measured 2026-09-11: these five cut a window's whole Edge footprint from ~770 MB
        # to ~454 MB, because a DSH app window needs none of a browser's extensions,
        # component extensions, sync or background networking.
        "--disable-extensions",
        "--disable-component-extensions-with-background-pages",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-features=Translate,MediaRouter,msEdgeSidebarV2,msEdgeCollections,msEdgeShoppingAssistant,EdgeWallet,msEdgeIdentityFeature"
    )
    $slotSize = Get-Prop $slot 'size'
    $slotPos  = Get-Prop $slot 'position'
    if ($slotSize) { $winArgs += "--window-size=$slotSize" }
    elseif (Get-Prop $Cfg.browser 'windowSize') { $winArgs += "--window-size=$(Get-Prop $Cfg.browser 'windowSize')" }
    if ($slotPos) { $winArgs += "--window-position=$slotPos" }
    $extra = Get-Prop $Cfg.browser 'extraArgs'
    if ($extra) { $winArgs += $extra }

    $proc = Start-Process -FilePath $exe -ArgumentList $winArgs -PassThru -ErrorAction Stop
    # Measured 2026-09-11: 12 fresh windows booting at once cost the engine ~0.45 s of
    # end-to-end work (72 calls, all 2xx, event-loop ping 208 ms worst case) while one
    # window costs 60 ms. Staggering launches keeps the tail small.
    Start-Sleep -Milliseconds 250
    # Record every launch: an Edge app window's own process exits immediately after it
    # hands off to its browser process, so a silent failure here is otherwise invisible.
    $line = "[{0}] open slot={1} profile={2} pid={3} args={4}" -f (Get-Date -Format o), $label, $slot.profile, $proc.Id, ($winArgs -join ' ')
    Add-Content -LiteralPath (Join-Path $StateDir 'windows.log') -Value $line -Encoding utf8
    return $profDir
}

function Get-WindowCount($slotCfg) {
    $profDir = Join-Path $Cfg.browser.profileRoot $slotCfg.profile
    $count = 0
    try {
        $count = @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe'" |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profDir) -and $_.CommandLine.Contains('--app=') }).Count
    } catch { }
    return $count
}

function Get-SlotCfgByPortOrLabel([string]$selector) {
    if (-not $selector) { return $null }
    foreach ($s in (Get-Slots)) {
        if ("$($s.port)" -eq $selector) { return $s }
        if ($s.label -eq $selector) { return $s }
    }
    return $null
}

# ── commands ────────────────────────────────────────────────────────────────
function Invoke-Up([switch]$WindowsOnly, [string]$WindowsMode = 'yes') {
    $state = Get-State
    $slots = Get-Slots
    $enabledWindows = @($slots | Where-Object { $_.enabled })

    if ($WindowsOnly) {
        foreach ($slot in $enabledWindows) { [void](Open-SlotWindow $slot $state) }
        Write-Host "opened $($enabledWindows.Count) windows"
        return
    }

    $failed = @()
    $listenTable = Get-ListenTable
    if ($Force) {
        foreach ($f in @((Join-Path $StateDir 'windows.log'))) { if (Test-Path $f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue } }
    }
    # Which servers must exist?
    if (Get-Mode -eq 'single') {
        $needed = @($slots | Where-Object { $_.enabled -and $_.port -eq (Get-PrimaryPort) } | Select-Object -First 1)
        if ($needed.Count -eq 0) {
            $needed = @([pscustomobject]@{
                label = 'primary'; profile = 'w1'; workspace = $Cfg.primaryWorkspace
                enabled = $true; port = (Get-PrimaryPort); index = 0
            })
        }
    } else {
        $needed = @($slots | Where-Object { $_.enabled })
    }

    $toStart = @(); $already = 0
    foreach ($slot in $needed) {
        $liveOwner = Get-PortOwner ([int]$slot.port) $listenTable
        $rec = Get-SlotRecord $state ([int]$slot.port)
        if ($liveOwner -and -not $Force) { $already++; continue }
        if ($liveOwner -and $Force) {
            # ownership moved on from the pid we recorded (an engine started by hand, or a
            # previous run): stop it first, or the new one dies on EADDRINUSE
            Write-Host ("  [take] port {0,-5} was held by pid {1} - stopping it to take the port" -f $slot.port, $liveOwner.Id) -ForegroundColor Yellow
            [void](Stop-ServerTree ([int]$slot.port) $rec $listenTable)
        }
        $toStart += $slot
    }

    $failed = @()
    if ($toStart.Count -gt 0) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $results = Start-SlotServerParallel $toStart
        $sw.Stop()
        foreach ($slot in $toStart) {
            $port = [int]$slot.port
            $r = $results["$port"]
            if (-not $r -or $r.error) {
                $msg = if ($r -and $r.error) { $r.error } else { 'no result from launcher child' }
                $failed += "port ${port}: $msg"
                Write-Host ("  [FAIL] port {0,-5} {1}" -f $port, $msg) -ForegroundColor Red
                continue
            }
            Set-SlotRecord $state $port ([pscustomobject]@{
                pid = $r.pid; url = $r.url; log = $r.log; workspace = $r.workspace
                startedAt = $r.startedAt; label = $slot.label; profile = $slot.profile
            })
            Write-Host ("  [up]   port {0,-5} pid {1,-7} {2}" -f $port, $r.pid, $slot.label) -ForegroundColor Green
        }
        Save-State $state
        Write-Host ("  (started {0} server(s) in {1}s)" -f ($toStart.Count - $failed.Count), [math]::Round($sw.Elapsed.TotalSeconds, 1))
    }

    if ($WindowsMode -in @('yes', 'auto')) {
        $state = Get-State
        foreach ($slot in $enabledWindows) { [void](Open-SlotWindow $slot $state) }
    }
    Write-Host ("up: {0} server(s) started, {1} already listening, {2} failed, {3} window(s) opened" -f `
        ($toStart.Count - $failed.Count), $already, $failed.Count, $enabledWindows.Count)
    if ($failed.Count) { $failed | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }; exit 1 }
}

function Invoke-Down {
    $state = Get-State
    $stopped = 0
    foreach ($port in @($state.slots.Keys)) {
        $rec = $state.slots[$port]
        $alive = (Test-PortInUse ([int]$port)) -or ($rec.pid -and (Get-Process -Id $rec.pid -ErrorAction SilentlyContinue))
        if (-not $alive) { continue }
        if (Stop-ServerTree ([int]$port) $rec) { $stopped++; Write-Host ("  [down] port {0,-5} pid {1}" -f $port, $rec.pid) }
        else { Write-Host ("  [WARN] port {0,-5} did not release" -f $port) -ForegroundColor Yellow }
    }
    Write-Host "down: $stopped stopped. (Browser windows are closed by you, or by closing them.)"
}

function Invoke-Status {
    $state = Get-State
    $primary = if (Get-Mode -eq 'single') { Get-PrimaryPort } else { $null }
    $rows = foreach ($slot in (Get-Slots)) {
        $owner = Get-PortOwner $slot.port
        $rec = Get-SlotRecord $state $slot.port
        $server = if ($owner) { "pid $($owner.Id)" } elseif ($rec -and $rec.pid) { 'recorded, not listening' } else { '-' }
        $engine = if (Get-Mode -eq 'single') { if ($slot.port -eq $primary) { 'primary' } else { "shared :$($slot.port)" } } else { "own :$($slot.port)" }
        [pscustomobject]@{
            slot    = $slot.label
            enabled = $slot.enabled
            engine  = $engine
            server  = $server
            windows = Get-WindowCount $slot
            mem_mb  = if ($owner) { [math]::Round($owner.WorkingSet64 / 1MB) } else { 0 }
            profile = $slot.profile
        }
    }
    if ($Json) { [pscustomobject]@{ mode = (Get-Mode); primaryPort = $primary; slots = $rows } | ConvertTo-Json -Depth 4; return }
    Write-Host ("mode: {0}{1}" -f (Get-Mode), $(if ($primary) { " (engine on port $primary)" } else { '' }))
    $rows | Format-Table -AutoSize slot, enabled, engine, server, windows, mem_mb, profile
    # count engines once each: every slot in single mode names the same process
    $engineRows = $rows | Where-Object { $_.server -like 'pid*' }
    $enginePids = @($engineRows | ForEach-Object { ($_.server -replace '[^0-9]', '') } | Select-Object -Unique)
    $win = ($rows | Measure-Object -Property windows -Sum).Sum
    $mem = 0
    foreach ($e in $enginePids) { $p = Get-Process -Id ([int]$e) -ErrorAction SilentlyContinue; if ($p) { $mem += [math]::Round($p.WorkingSet64 / 1MB) } }
    $tree = 0
    $procTable = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId -ErrorAction SilentlyContinue
    foreach ($e in $enginePids) { $tree += Get-TreeMemoryMb ([int]$e) $procTable }
    Write-Host ("{0} engine(s) live, {1} window(s) open, {2} MB engine RSS, {3} MB whole engine tree" -f $enginePids.Count, $win, $mem, $tree)
}

# Sum the working set of a process and every descendant: an engine's real cost is its
# MCP bridges and runners, not the node process itself. Pass a process table in when you
# call it in a loop — a fresh CIM query per slot is what makes this slow.
function Get-TreeMemoryMb([int]$root, $all = $null) {
    if (-not $all) { $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId -ErrorAction SilentlyContinue }
    $ids = New-Object System.Collections.Generic.List[int]
    $ids.Add($root)
    $frontier = @($root)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($f in $frontier) {
            foreach ($c in $all | Where-Object { $_.ParentProcessId -eq $f }) {
                if (-not $ids.Contains([int]$c.ProcessId)) { $ids.Add([int]$c.ProcessId); $next += $c.ProcessId }
            }
        }
        $frontier = $next
    }
    $sum = 0
    foreach ($i in $ids) { $p = Get-Process -Id $i -ErrorAction SilentlyContinue; if ($p) { $sum += $p.WorkingSet64 } }
    return [math]::Round($sum / 1MB)
}

function Invoke-New {
    $state = Get-State
    $slots = Get-Slots
    $used = @($slots | Where-Object { (Get-WindowCount $_) -gt 0 })
    $free = @($slots | Where-Object { (Get-WindowCount $_) -eq 0 }) | Select-Object -First 1
    if (-not $free) {
        Write-Host "all $($slots.Count) window slots are already open. Add another row to windows.json." -ForegroundColor Yellow
        exit 1
    }
    foreach ($slot in $slots) { $slot.enabled = $true }
    [void](Open-SlotWindow $free $state)
    Write-Host ("new window: slot '{0}' (profile {1}) against port {2}" -f $free.label, $free.profile, $(if (Get-Mode -eq 'multi') { $free.port } else { Get-PrimaryPort })) -ForegroundColor Green
}

function Invoke-Doctor {
    $problems = @()
    $node = try { Resolve-NodeExe } catch { $null }
    if (-not $node) { $problems += 'node.exe not on PATH' } else { Write-Host "node        : $node ($(& $node -v))" }
    $bin = try { Resolve-DshBin } catch { $null }
    if (-not $bin) { $problems += '@deepseek-ai/dsh/lib/bin.js not found' } else { Write-Host "dsh bin     : $bin" }
    $edge = Get-EdgePath
    if (-not $edge) { $problems += 'no Edge/Chrome binary found' } else { Write-Host "browser     : $edge" }
    $home_dsh = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }
    if (-not (Test-Path $home_dsh)) { $problems += "DSH_HOME missing: $home_dsh" } else { Write-Host "DSH_HOME    : $home_dsh" }
    foreach ($p in @($StateDir, $LogDir, $Cfg.browser.profileRoot)) {
        try { New-Item -ItemType Directory -Force -Path $p | Out-Null; Write-Host "dir ok      : $p" }
        catch { $problems += "cannot create $p" }
    }
    $disabled = @($Cfg.windows | Where-Object { -not $_.enabled }).Count
    Write-Host ("slots       : {0} enabled, {1} disabled" -f @($Cfg.windows | Where-Object { $_.enabled }).Count, $disabled)
    if ($problems.Count) {
        Write-Host "`nBLOCKERS:" -ForegroundColor Red
        $problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        exit 3
    }
    Write-Host "`nno blockers." -ForegroundColor Green
}

function Invoke-Autostart([string]$mode) {
    $taskName = 'DSH Multi-Window Launcher'
    if ($mode -eq 'off') {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host "autostart: removed '$taskName'"
        } else { Write-Host 'autostart: task was not registered' }
        return
    }
    $ps = (Get-Command pwsh).Source
    $script = Join-Path $PSScriptRoot 'dshw.ps1'
    $action = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -WindowStyle Hidden -File `"$script`" up -ConfigPath `"$ConfigPath`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "autostart: '$taskName' registered (at logon, this user, hidden). Test now: Start-ScheduledTask -TaskName '$taskName'"
}

function Invoke-Health {
    # Designed to be run from a scheduled task every few minutes. It is idempotent and
    # additive: it starts ONLY the servers that should be listening and are not, then
    # exits. It never stops or restarts a live engine, never opens browser windows, and
    # appends a line to health.log only when it actually did something, so the log stays
    # readable. Safe to run twice at once: the port bind itself is the lock, and the
    # loser of a race fails with EADDRINUSE instead of starting a second writer on the
    # same DSH_HOME (which would corrupt session logs).
    $state = Get-State
    $listenTable = Get-ListenTable
    $slots = Get-Slots

    if (Get-Mode -eq 'single') {
        $needed = @($slots | Where-Object { $_.enabled } | Select-Object -First 1)
        if (-not $needed) {
            $needed = @([pscustomobject]@{ label = 'primary'; profile = 'w1'; workspace = $Cfg.primaryWorkspace
                                           enabled = $true; port = (Get-PrimaryPort); index = 0 })
        }
    } else {
        $needed = @($slots | Where-Object { $_.enabled })
    }

    $missing = @($needed | Where-Object { -not (Get-PortOwner ([int]$_.port) $listenTable) })
    $healthLog = Join-Path $StateDir 'health.log'

    if ($missing.Count -eq 0) {
        Write-Host ("healthy: all {0} enabled engine(s) listening" -f $needed.Count)
        return
    }

    Write-Host ("unhealthy: {0} of {1} engine(s) not listening - restarting: {2}" -f `
        $missing.Count, $needed.Count, (($missing | ForEach-Object { $_.port }) -join ', '))
    "[{0}] health: {1} engine(s) down ({2}) - restarting" -f `
        (Get-Date -Format o), $missing.Count, (($missing | ForEach-Object { $_.port }) -join ',') |
        Add-Content -LiteralPath $healthLog -Encoding utf8

    $results = Start-SlotServerParallel $missing
    foreach ($slot in $missing) {
        $port = [int]$slot.port
        $r = $results["$port"]
        $inv = Get-ServerInvocation $slot
        Update-LatestLog $inv
        if (-not $r -or $r.error) {
            $msg = if ($r -and $r.error) { $r.error } else { 'no result' }
            Write-Host ("  [FAIL] port {0,-5} {1}" -f $port, $msg) -ForegroundColor Red
            "[{0}] health: port {1} restart FAILED: {2}" -f (Get-Date -Format o), $port, $msg |
                Add-Content -LiteralPath $healthLog -Encoding utf8
            continue
        }
        Set-SlotRecord $state $port ([pscustomobject]@{
            pid = $r.pid; url = $r.url; log = $r.log; workspace = $r.workspace
            startedAt = $r.startedAt; label = $slot.label; profile = $slot.profile })
        Write-Host ("  [up]   port {0,-5} pid {1,-7} {2}" -f $port, $r.pid, $slot.label) -ForegroundColor Green
        "[{0}] health: port {1} restarted, pid {2}" -f (Get-Date -Format o), $port, $r.pid |
            Add-Content -LiteralPath $healthLog -Encoding utf8
    }
    Save-State $state
}

function Invoke-Watchdog([string]$mode) {
    $taskName = 'DSH Window Fleet Watchdog'
    if ($mode -eq 'off') {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host "watchdog: removed '$taskName'"
        } else { Write-Host 'watchdog: task was not registered' }
        return
    }
    $ps = (Get-Command pwsh).Source
    $script = Join-Path $PSScriptRoot 'dshw.ps1'
    $action = New-ScheduledTaskAction -Execute $ps `
        -Argument "-NoProfile -WindowStyle Hidden -File `"$script`" health -ConfigPath `"$ConfigPath`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "watchdog: '$taskName' registered - 'dshw health' every 5 minutes, this user, no windows opened."
    Write-Host "          It only ever STARTS a missing engine. Live engines are left alone."
    Write-Host "          Log: $StateDir\health.log"
}

function Invoke-Logs {
    $slot = Get-SlotCfgByPortOrLabel $Slot
    if (-not $slot) { Write-Error "no slot matches '$Slot'"; exit 2 }
    $log = Join-Path $LogDir "$($slot.port).log"
    if (-not (Test-Path $log)) { Write-Error "no log at $log"; exit 1 }
    Get-Content -LiteralPath $log -Tail $Lines
}

# ── dispatch ────────────────────────────────────────────────────────────────
function Restart-OneEngine($slot) {
    $state = Get-State
    [void](Stop-ServerTree ([int]$slot.port) (Get-SlotRecord $state ([int]$slot.port)))
    $r = Start-SlotServer $slot
    Set-SlotRecord $state ([int]$slot.port) ([pscustomobject]@{
        pid = $r.pid; url = $r.url; log = $r.log; workspace = $r.workspace
        startedAt = $r.startedAt; label = $slot.label; profile = $slot.profile })
    Save-State $state
    Write-Host ("restarted engine on port {0} (pid {1})" -f $slot.port, $r.pid)
    Write-Host "existing windows will reconnect on their own; a window that shows the auth page needs: dshw open <slot>"
}

switch ($Command) {
    'up'     { Invoke-Up -WindowsMode $WindowsMode }
    'down'   { Invoke-Down }
    'restart' {
        if ($Slot) { Invoke-Down }
        $state = Get-State
        $engineSlots = if (Get-Mode -eq 'single') {
            @([pscustomobject]@{ label = 'primary'; profile = 'w1'; workspace = $Cfg.primaryWorkspace
                                 enabled = $true; port = (Get-PrimaryPort); index = 0 })
        } else { Get-ServerSlot }
        foreach ($s in $engineSlots) { Restart-OneEngine $s }
        if (-not $Slot) { Invoke-Up -WindowsOnly }
    }
    'status' { Invoke-Status }
    'windows' { Invoke-Up -WindowsOnly }
    'new'    { Invoke-New }
    'open'   {
        $slot = Get-SlotCfgByPortOrLabel $Slot
        if (-not $slot) { Write-Error "no slot matches '$Slot'"; exit 2 }
        [void](Open-SlotWindow $slot (Get-State))
        Write-Host ("opened window for slot '{0}'" -f $slot.label)
    }
    'stop'   {
        $engineSlots = if (Get-Mode -eq 'single') {
            @([pscustomobject]@{ label = 'primary'; port = (Get-PrimaryPort) })
        } elseif ($Slot) {
            $s = Get-SlotCfgByPortOrLabel $Slot
            if (-not $s) { Write-Error "no slot matches '$Slot'"; exit 2 }
            @($s)
        } else { Get-ServerSlot }
        $state = Get-State
        foreach ($s in $engineSlots) {
            if (Stop-ServerTree ([int]$s.port) (Get-SlotRecord $state ([int]$s.port))) {
                Write-Host ("stopped engine on port {0}" -f $s.port)
            } else { Write-Host ("engine on port {0} was not running" -f $s.port) }
        }
    }
    'logs'      { Invoke-Logs }
    'health'    { Invoke-Health }
    'watchdog'  { Invoke-Watchdog ($Slot) }
    'autostart' { Invoke-Autostart ($Slot) }
    'doctor'    { Invoke-Doctor }
    'help'      { Get-Help $PSCommandPath -Detailed }
    default     { Get-Help $PSCommandPath }
}
