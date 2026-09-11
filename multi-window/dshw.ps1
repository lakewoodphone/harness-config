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
    [ValidateSet('up', 'down', 'restart', 'status', 'windows', 'new', 'open', 'stop', 'logs', 'autostart', 'doctor', 'help')]
    [string]$Command = 'status',

    [Parameter(Position = 1)]
    [string]$Slot = '',

    [string]$ConfigPath = '',
    [int]$Lines = 40,
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
function Get-Mode { if ($Cfg.mode) { "$($Cfg.mode)" } else { 'single' } }

function Get-PrimaryPort { [int]$Cfg.primaryPort }

function Resolve-SlotPort($slot, [int]$index) {
    if (Get-Mode -eq 'multi') {
        $base = 3081
        $mp = $Cfg.PSObject.Properties['_multiPorts']
        if ($mp -and $mp.Value -and $mp.Value.basePort) { $base = [int]$mp.Value.basePort }
        return $base + $index
    }
    return (Get-PrimaryPort)
}

function Resolve-SlotInfo($slot, [int]$index) {
    return [pscustomobject]@{
        label     = $slot.label
        profile   = $slot.profile
        workspace = $slot.workspace
        enabled   = [bool]$slot.enabled
        port      = Resolve-SlotPort $slot $index
        index     = $index
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

# ── port / process helpers ──────────────────────────────────────────────────
function Test-PortInUse([int]$port) {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    return [bool]$conn
}

function Get-PortOwner([int]$port) {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
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

function Stop-ServerTree([int]$port, $record) {
    $pids = @()
    if ($record -and $record.pid) { $pids += $record.pid }
    $owner = Get-PortOwner $port
    if ($owner) { $pids += $owner.Id }
    $pids = $pids | Select-Object -Unique
    if (-not $pids) { return $false }
    foreach ($p in $pids) {
        $kids = Get-Descendants $p
        # children first, then the parent
        foreach ($k in ($kids | Sort-Object -Descending)) { Stop-Process -Id $k -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 20; $i++) {
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
    $log  = Join-Path $LogDir "$port.log"
    $err  = Join-Path $LogDir "$port.err.log"
    $cwd  = if ($slotCfg.workspace -and (Test-Path $slotCfg.workspace)) { $slotCfg.workspace } else { (Get-Location).Path }
    return [pscustomobject]@{ node = $node; bin = $bin; port = $port; log = $log; err = $err; cwd = $cwd }
}

function Start-SlotServer($slotCfg) {
    $inv = Get-ServerInvocation $slotCfg
    if (Test-PortInUse $inv.port) { throw "port $($inv.port) already in use" }
    foreach ($f in @($inv.log, $inv.err)) { if (Test-Path $f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue } }

    "[$(Get-Date -Format o)] dshw: node $($inv.bin) web --port $($inv.port) (cwd $($inv.cwd))" |
        Add-Content -LiteralPath $inv.log -Encoding utf8

    $p = Start-Process -FilePath $inv.node -ArgumentList @($inv.bin, 'web', '--port', "$($inv.port)", '--no-open') `
            -WorkingDirectory $inv.cwd -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $inv.log -RedirectStandardError $inv.err

    $deadline = (Get-Date).AddSeconds([int]$Cfg.server.startTimeoutSeconds)
    $url = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if ($p.HasExited) {
            $tail = if (Test-Path $inv.err) { (Get-Content -LiteralPath $inv.err -Tail 15) -join "`n" } else { '(no stderr)' }
            throw "server on port $($inv.port) exited with code $($p.ExitCode). stderr tail:`n$tail"
        }
        if (Test-Path $inv.log) {
            $m = Select-String -LiteralPath $inv.log -Pattern 'dsh web:\s*(\S+)' -ErrorAction SilentlyContinue | Select-Object -Last 1
            if ($m) { $url = $m.Matches[0].Groups[1].Value; break }
        }
    }
    if (-not $url) { throw "server on port $($inv.port) did not report a URL within $($Cfg.server.startTimeoutSeconds)s (see $($inv.log))" }

    return [pscustomobject]@{ pid = $p.Id; url = $url; log = $inv.log; err = $inv.err
                              workspace = $inv.cwd; startedAt = (Get-Date).ToString('o') }
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
        $child = @'
$json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DSHW_PAYLOAD))
$p = $json | ConvertFrom-Json
$out = @{ ok = $false; port = $p.port; pid = $null; error = $null }
try {
    foreach ($f in @($p.log, $p.err)) { if (Test-Path $f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue } }
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

    # wait until every slot's log shows its URL line (a port bind alone is not readiness:
    # the web app prints the URL only after the loader tree has settled)
    $results = @{}
    $deadline = (Get-Date).AddSeconds([int]$Cfg.server.startTimeoutSeconds + 30)
    foreach ($port in $readies.Keys) {
        $slot = $slots | Where-Object { "$($_.port)" -eq "$port" } | Select-Object -First 1
        $inv  = Get-ServerInvocation $slot
        $r = [pscustomobject]@{ pid = $null; url = $null; log = $inv.log; err = $inv.err
                                workspace = $inv.cwd; startedAt = (Get-Date).ToString('o'); error = $null }
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
            if (Test-Path $inv.log) {
                $m = Select-String -LiteralPath $inv.log -Pattern 'dsh web:\s*(\S+)' -ErrorAction SilentlyContinue | Select-Object -Last 1
                if ($m) { $r.url = $m.Matches[0].Groups[1].Value; break }
            }
            if (Test-Path $inv.err) {
                $content = Get-Content -LiteralPath $inv.err -Raw -ErrorAction SilentlyContinue
                if ($content -and ($content -match 'EADDRINUSE|Error:')) { $r.error = ($content.Trim() -split "`n" | Select-Object -Last 3) -join ' | '; break }
            }
        }
        if (-not $r.url -and -not $r.error) { $r.error = "no URL within $($Cfg.server.startTimeoutSeconds)s" }
        # the pid comes from the readiness file the launcher child wrote
        if (Test-Path $readies[$port]) {
            try { $j = Get-Content -Raw -LiteralPath $readies[$port] | ConvertFrom-Json
                  if ($j.pid) { $r.pid = $j.pid }
                  if (-not $r.error -and $j.error) { $r.error = $j.error } } catch { }
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
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-features=Translate,MediaRouter"
    )
    if ($slot.size) { $winArgs += "--window-size=$($slot.size)" }
    elseif ($Cfg.browser.windowSize) { $winArgs += "--window-size=$($Cfg.browser.windowSize)" }
    if ($slot.position) { $winArgs += "--window-position=$($slot.position)" }
    if ($Cfg.browser.extraArgs) { $winArgs += $Cfg.browser.extraArgs }

    Start-Process -FilePath $exe -ArgumentList $winArgs | Out-Null
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
        if (Test-PortInUse ([int]$slot.port) -and -not $Force) { $already++; continue }
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
    $live = @($rows | Where-Object { $_.server -like 'pid*' }).Count
    $win = ($rows | Measure-Object -Property windows -Sum).Sum
    $mem = ($rows | Measure-Object -Property mem_mb -Sum).Sum
    Write-Host ("{0} engine(s) live, {1} window(s) open, {2} MB engine RSS" -f $live, $win, $mem)
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
    $home_dsh = Join-Path $env:USERPROFILE '.dsh'
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
    'up'     { Invoke-Up }
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
    'autostart' { Invoke-Autostart ($Slot) }
    'doctor'    { Invoke-Doctor }
    'help'      { Get-Help $PSCommandPath -Detailed }
    default     { Get-Help $PSCommandPath }
}
