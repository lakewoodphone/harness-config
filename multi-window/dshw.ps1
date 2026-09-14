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
    [ValidateSet('up', 'down', 'restart', 'status', 'windows', 'new', 'open', 'stop', 'logs', 'health', 'autostart', 'watchdog', 'tasks-export', 'tasks-import', 'doctor', 'help')]
    [string]$Command = 'status',

    [Parameter(Position = 1)]
    [string]$Slot = '',

    [string]$ConfigPath = '',
    [int]$Lines = 40,
    # Default is NO windows. Starting the engine and opening eight windows are separate
    # intentions: the owner opens windows himself, one at a time, from the `+` in the UI
    # (or `dshw new`). `dshw up -WindowsMode yes` is the explicit "start everything" form.
    [ValidateSet('yes', 'no', 'auto')]
    [string]$WindowsMode = 'no',
    # Launch engines through Task Scheduler so they cannot die with the calling shell. Use
    # when starting the fleet from an agent/tool session rather than a real terminal.
    [switch]$Detached,
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

# Readiness = the log shows the URL line AND the port is listening.
#
# It deliberately does NOT ask the launched process "are you alive?" through
# Process.HasExited. Sampling that property blocks for the whole lifetime of a detached
# child on Windows here, which made `dshw up` hang until its outer timeout with the engine
# demonstrably running (measured twice on 2026-09-11, 420 s and 600 s). A dead child fails
# the timeout anyway, and the caller reports its stderr tail, so nothing is lost.
function Wait-ServerReady([string]$log, [long]$offset, [int]$timeoutSeconds, [int]$port) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    $sawUrl = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
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

function Get-ForeignEngines {
    # A `dsh web` process listening against this DSH_HOME that this launcher does not manage.
    #
    # windows.json calls two engines on one home unsupported: "two dsh web processes on one
    # home have been observed writing duplicate sequence numbers into one session log and
    # making the whole history unloadable". It cannot be seen from the port alone, because a
    # hand-started engine takes the default 3080, which no slot in windows.json uses -- so it
    # is read from the process command line instead.
    $managed = @{}
    $st = Get-State
    if ($st -and $st.slots) { foreach ($port in @($st.slots.Keys)) { $managed[[int]$port] = $true } }
    $out = @()
    foreach ($conn in Get-ListenTable) {
        $procId = [int]$conn.OwningProcess
        if ($procId -le 0) { continue }
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if (-not $proc -or $proc.ProcessName -ne 'node') { continue }
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).CommandLine
        if (-not $cmd) { continue }
        # A dsh web engine, not one of the subprocess runners or MCP bridges.
        if ($cmd -notmatch 'dsh' -or $cmd -notmatch 'web' -or $cmd -match 'subprocess-local') { continue }
        if ($managed.ContainsKey([int]$conn.LocalPort)) { continue }
        $out += [pscustomobject]@{ Port = [int]$conn.LocalPort; Pid = $procId }
    }
    return $out
}

function Get-Descendants([int]$rootPid, $all = $null) {
    # Cache the process table per call where possible: an unfiltered Win32_Process query
    # costs 5-35 s on a machine running a dozen Edge profiles plus eight MCP bridges, and
    # doing it inside a wait loop is what made `up` look like a hang (2026-09-11).
    if (-not $all) { $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId -ErrorAction SilentlyContinue }
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
    # A transient task may still exist if a launch failed midway; drop it first so nothing
    # can resurrect the engine while we are stopping it.
    $taskName = "DSH Engine (port $port)"
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    # NEVER name a variable $pid or $pids here: PowerShell's $PID is the CURRENT process
    # id and is read-only, so `$pids = @()` throws and the function dies before stopping
    # anything (found 2026-09-11 - it silently broke `dshw restart`).
    $serverIds = @()
    if ($record -and $record.pid) { $serverIds += $record.pid }
    $owner = Get-PortOwner $port $table
    if ($owner) { $serverIds += $owner.Id }
    $serverIds = $serverIds | Select-Object -Unique
    if (-not $serverIds) { return $false }
    foreach ($serverId in $serverIds) {
        $kids = Get-Descendants $serverId
        # children first, then the parent
        foreach ($k in ($kids | Sort-Object -Descending)) { Stop-Process -Id $k -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $serverId -Force -ErrorAction SilentlyContinue
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
                              latest = (Join-Path $LogDir "$port.log")
                              taskName = "DSH Engine (port $port)" }
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

# Launch one engine through Task Scheduler and return its pid.
#
# WHY NOT Start-Process. A child started directly by this script dies with the job object
# that owns it. Measured 2026-09-11: an engine started by Start-Process from an agent shell
# ran ~110 s and then vanished the moment the parent command finished, which made every
# launch look like a timeout with the engine "up" the whole time. A process created by Task
# Scheduler belongs to no job of ours, so it survives the caller, the shell, and this
# session. The transient task is removed as soon as the port is bound; the engine stays.
function Test-IsElevated {
    try {
        $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        return (New-Object System.Security.Principal.WindowsPrincipal($id)).IsInRole(
            [System.Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function New-InteractivePrincipal([switch]$Highest) {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $sid = $identity.User.Value
    $runLevel = if ($Highest) { 'Highest' } else { 'Limited' }
    if ($sid) {
        return New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel $runLevel
    }
    return New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel $runLevel
}

function Start-EngineDetached($inv, [int]$timeoutSeconds) {
    $mustUnregister = $false
    $existing = Get-ScheduledTask -TaskName $inv.taskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        $action = New-ScheduledTaskAction -Execute $inv.node `
            -Argument "`"$($inv.bin)`" web --port $($inv.port) --no-open" `
            -WorkingDirectory $inv.cwd
        # Keep the engine at the same privilege level as this script: the owner wants DSH
        # running elevated on both machines, and a task is the only way to create an
        # elevated process without an interactive UAC prompt.
        $principal = New-InteractivePrincipal -Highest:(Test-IsElevated)
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $inv.taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
        $mustUnregister = $true
    }
    Start-ScheduledTask -TaskName $inv.taskName

    # Readiness here = the engine printed its URL in THIS log file AND the port answers.
    # Deliberately no Get-NetTCPConnection: that query can stall for many seconds on a
    # loaded machine, and a stalled query inside a wait loop is indistinguishable from a
    # hung command (it cost several 420 s timeouts on 2026-09-11). A TCP connect with its
    # own timeout is bounded and local.
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    $url = $null
    $pid_ = $null
    $probe = New-Object System.Net.Sockets.TcpClient
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        if (-not $url -and (Test-Path $inv.log)) {
            $text = Read-NewLog $inv.log 0
            if ($text) {
                $m = [regex]::Match($text, 'dsh web:\s*(\S+)')
                if ($m.Success) { $url = $m.Groups[1].Value }
            }
        }
        $bound = $false
        try {
            $task = $probe.ConnectAsync('127.0.0.1', $inv.port)
            if ($task.Wait(1500)) { $bound = $probe.Connected }
        } catch { }
        if ($bound -and -not $pid_) {
            $owner = Get-PortOwner $inv.port
            if ($owner) { $pid_ = $owner.Id }
        }
        if ($url -and $bound) { break }
    }
    try { $probe.Dispose() } catch { }

    if ($mustUnregister) {
        # the engine is its own process now; this task only ever existed to create it
        Unregister-ScheduledTask -TaskName $inv.taskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    if (-not $pid_) { throw "engine on port $($inv.port) never bound the port (see $($inv.log))" }
    if (-not $url) {
        $tail = if (Test-Path $inv.err) { (Get-Content -LiteralPath $inv.err -Tail 10) -join ' | ' } else { '(no stderr)' }
        throw "engine on port $($inv.port) bound the port but never printed its URL (see $($inv.log)) :: $tail"
    }
    return [pscustomobject]@{ pid = $pid_; url = $url }
}

function Start-SlotServer($slotCfg) {
    $inv = Get-ServerInvocation $slotCfg
    if (Test-PortInUse $inv.port) { throw "port $($inv.port) already in use" }

    if ($Detached) {
        # Task Scheduler creates the engine outside this process's job object, so it cannot
        # die with the caller. The price is readiness: a task action cannot redirect stdout,
        # so the strongest signal (this launch's URL line) is unavailable and the bound port
        # is all there is to go on.
        $r = Start-EngineDetached $inv ([int]$Cfg.server.startTimeoutSeconds)
        return [pscustomobject]@{ pid = $r.pid; url = $r.url; log = $inv.log; err = $inv.err
                                  workspace = $inv.cwd; startedAt = (Get-Date).ToString('o') }
    }

    # Default: a direct spawn with the engine's own log files, which gives the strongest
    # readiness signal - a live process AND a bound port AND a URL line from THIS launch.
    $p = Start-Process -FilePath $inv.node -ArgumentList @($inv.bin, 'web', '--port', "$($inv.port)", '--no-open') `
            -WorkingDirectory $inv.cwd -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $inv.log -RedirectStandardError $inv.err

    $url = Wait-ServerReady $inv.log 0 ([int]$Cfg.server.startTimeoutSeconds) $inv.port
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
        $r.url = Wait-ServerReady $inv.log 0 ([int]$Cfg.server.startTimeoutSeconds) ([int]$port)
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

function Get-WindowProcs($table = $null) {
    # One process table for the whole status call. Querying CIM per slot was slow AND
    # unstable: 12 separate queries see the process list at 12 different instants, which
    # produced changing counts for the same window (measured 2026-09-11).
    if (-not $table) { $table = Get-CimInstance Win32_Process -Property ProcessId, Name, CommandLine -Filter "Name='msedge.exe' OR Name='chrome.exe'" -ErrorAction SilentlyContinue }
    return $table
}

function Get-WindowCount($slotCfg, $table = $null) {
    $profDir = Join-Path $Cfg.browser.profileRoot $slotCfg.profile
    # Count distinct app URLs in this profile, not processes: Edge may hold several window
    # ROOTS on one profile, and child processes inherit the parent's command line.
    try {
        $procs = Get-WindowProcs $table
        $urls = @($procs |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine.Contains($profDir) -and
                $_.CommandLine.Contains('--app=') -and
                -not $_.CommandLine.Contains('--type=')
            } | ForEach-Object {
                if ($_.CommandLine -match '--app=(\S+)') { $Matches[1] }
            } | Select-Object -Unique)
        return $urls.Count
    } catch { return 0 }
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
function Invoke-Up([switch]$WindowsOnly, [string]$WindowsMode = 'no') {
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
    # Settle the plugin layer BEFORE an engine starts. A profile whose bundle list names a
    # package that cannot be resolved does not degrade -- the engine refuses to boot with
    # "cannot resolve profile bundle ...", which is how the 15:45 start on 2026-09-11 died and
    # why plugin-windows then had to be copied in by hand. Idempotent and cheap.
    $keeper = Join-Path $RepoRoot 'scripts\install-client-plugins.ps1'
    if (Test-Path $keeper) {
        & pwsh -NoProfile -File $keeper -Check *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [plugins] a mounted bundle does not resolve - repairing before start" -ForegroundColor Yellow
            & pwsh -NoProfile -File $keeper 2>&1 | ForEach-Object { Write-Host "    $_" }
            if ($LASTEXITCODE -ne 0) { Write-Host "  [plugins] repair failed - the engine may refuse to boot" -ForegroundColor Red }
        }
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
        # SEQUENTIAL on purpose. The parallel path (Start-SlotServerParallel) launches one
        # helper process per engine and waits on readiness files; it was built for the
        # abandoned "one engine per window" design and it hung twice on 2026-09-11 - the
        # engine came up and wrote its state, but the launcher never returned, so the
        # command timed out while the server was fine. With ONE engine per machine there is
        # nothing to parallelise, so the direct path is both simpler and honest.
        foreach ($slot in $toStart) {
            $port = [int]$slot.port
            try {
                $r = Start-OneSlotServer $slot
                Set-SlotRecord $state $port ([pscustomobject]@{
                    pid = $r.pid; url = $r.url; log = $r.log; workspace = $r.workspace
                    startedAt = $r.startedAt; label = $slot.label; profile = $slot.profile
                })
                Save-State $state
                Write-Host ("  [up]   port {0,-5} pid {1,-7} {2}" -f $port, $r.pid, $slot.label) -ForegroundColor Green
            } catch {
                $failed += "port ${port}: $($_.Exception.Message)"
                Write-Host ("  [FAIL] port {0,-5} {1}" -f $port, $_.Exception.Message) -ForegroundColor Red
            }
        }
        $sw.Stop()
        Write-Host ("  (started {0} server(s) in {1}s)" -f ($toStart.Count - $failed.Count), [math]::Round($sw.Elapsed.TotalSeconds, 1))
    }

    if ($WindowsMode -in @('yes', 'auto')) {
        $state = Get-State
        foreach ($slot in $enabledWindows) {
            try { [void](Open-SlotWindow $slot $state) }
            catch { Write-Host ("  [WARN] could not open window '{0}': {1}" -f $slot.label, $_.Exception.Message) -ForegroundColor Yellow }
        }
        Write-Host ("  (asked the browser to open {0} window(s))" -f $enabledWindows.Count)
    }
    Write-Host ("up: {0} server(s) started, {1} already listening, {2} failed" -f `
        ($toStart.Count - $failed.Count), $already, $failed.Count)
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
    $procTable = Get-WindowProcs
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
            windows = Get-WindowCount $slot $procTable
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
    $foreign = @(Get-ForeignEngines)
    if ($foreign.Count) {
        Write-Host ("WARNING: {0} other dsh web against this DSH_HOME ({1}) - one writer only" -f `
            $foreign.Count, (($foreign | ForEach-Object { "pid $($_.Pid) :$($_.Port)" }) -join ', ')) -ForegroundColor Yellow
    }
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
    # Counting open windows needs a full process-table read, which is the single most
    # expensive thing in this script on a loaded machine (measured 15-35 s, and it is what
    # made `up` appear to hang). It runs here only because `new` must pick a free slot;
    # `up` never pays for it.
    $procTable = Get-WindowProcs
    $free = @($slots | Where-Object { (Get-WindowCount $_ $procTable) -eq 0 }) | Select-Object -First 1
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
    # The two things that have actually broken this fleet, checked here so `doctor` names them
    # rather than leaving them to be discovered when an engine refuses to boot.
    $keeper = Join-Path $RepoRoot 'scripts\install-client-plugins.ps1'
    if (Test-Path $keeper) {
        & pwsh -NoProfile -File $keeper -Check *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host "plugins     : every mounted client bundle resolves" }
        else { $problems += 'a mounted client bundle does not resolve - run scripts/install-client-plugins.ps1' }
    }
    $foreign = @(Get-ForeignEngines)
    if ($foreign.Count -eq 0) {
        Write-Host "engines     : no other dsh web against this DSH_HOME"
    } else {
        foreach ($f in $foreign) {
            $problems += "another dsh web on port $($f.Port) (pid $($f.Pid)) shares this DSH_HOME - two writers on one home can corrupt a session log; stop it, or take the port with 'dshw up -Force'"
        }
    }
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
    $action = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -WindowStyle Hidden -File `"$script`" up -ConfigPath `"$ConfigPath`" -WindowsMode no"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-InteractivePrincipal -Highest:(Test-IsElevated)
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
    # Transcript so a watchdog run that dies leaves evidence: a scheduled task that does
    # nothing and says nothing is indistinguishable from one that is not running at all.
    $logDir = Join-Path $StateDir 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Transcript -Path (Join-Path $logDir ("health-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))) -Force | Out-Null
    try {
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
    } else {

    Write-Host ("unhealthy: {0} of {1} engine(s) not listening - restarting: {2}" -f `
        $missing.Count, $needed.Count, (($missing | ForEach-Object { $_.port }) -join ', '))
    "[{0}] health: {1} engine(s) down ({2}) - restarting" -f `
        (Get-Date -Format o), $missing.Count, (($missing | ForEach-Object { $_.port }) -join ',') |
        Add-Content -LiteralPath $healthLog -Encoding utf8

    # Sequential, for the same reason as `up`: one engine per machine, and the parallel
    # helper process path proved unreliable (it hung while the engine itself came up fine).
    foreach ($slot in $missing) {
        $port = [int]$slot.port
        try {
            $r = Start-OneSlotServer $slot
        } catch {
            $msg = $_.Exception.Message
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
    } catch {
        Write-Host ("health: FAILED - " + $_.Exception.Message) -ForegroundColor Red
        "[{0}] health: FAILED: {1}" -f (Get-Date -Format o), $_.Exception.Message |
            Add-Content -LiteralPath (Join-Path $StateDir 'health.log') -Encoding utf8
    } finally {
        try { Stop-Transcript | Out-Null } catch { }
    }
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
    $principal = New-InteractivePrincipal -Highest:(Test-IsElevated)
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "watchdog: '$taskName' registered - 'dshw health' every 5 minutes, this user, no windows opened."
    Write-Host "          It only ever STARTS a missing engine. Live engines are left alone."
    Write-Host "          Log: $StateDir\health.log"
}

# Moving the two tasks between machines: register them ONCE on a machine that is already
# correct, export both to XML, and import either via `dshw tasks-import` or plain scp +
# `schtasks /Create /TN <name> /XML <file> /F`. Two traps, both hit on 2026-09-11:
#   1. Windows exports a UserId as a locally-mapped SID, so a naive host-name substitution
#      corrupts it and `schtasks` fails with "no mapping between account names and security
#      IDs". Import must rewrite <UserId> to the bare account name.
#   2. The bundle/args inside the XML are absolute paths, so both machines must keep the
#      repo at the same path.
function Invoke-TasksExport([string]$dir) {
    if (-not $dir) { $dir = Join-Path $StateDir 'tasks' }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($n in 'DSH Multi-Window Launcher', 'DSH Window Fleet Watchdog') {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if (-not $t) { Write-Host "  [skip] '$n' is not registered here" -ForegroundColor Yellow; continue }
        $file = Join-Path $dir (($n -replace '\s', '-') + '.xml')
        $xml = Export-ScheduledTask -TaskName $n
        [System.IO.File]::WriteAllText($file, $xml, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host ("  [export] {0} ({1} bytes)" -f $file, $xml.Length)
    }
    Write-Host "Copy these to the other machine and run: dshw tasks-import -Slot <dir>"
}

function Invoke-TasksImport([string]$dir) {
    if (-not $dir) { throw 'tasks-import needs a directory: dshw tasks-import -Slot <dir>' }
    $account = if ($env:USERNAME) { $env:USERNAME } else { whoami }
    $names = @{
        'DSH-Multi-Window-Launcher.xml' = 'DSH Multi-Window Launcher'
        'DSH-Window-Fleet-Watchdog.xml' = 'DSH Window Fleet Watchdog'
    }
    foreach ($k in $names.Keys) {
        $path = Join-Path $dir $k
        if (-not (Test-Path $path)) { Write-Host "  [skip] $k not found in $dir" -ForegroundColor Yellow; continue }
        $xml = [System.IO.File]::ReadAllText($path)
        # see the note above: never carry another machine's SID across
        $xml = $xml -replace '<UserId>[^<]*</UserId>', "<UserId>$account</UserId>"
        [System.IO.File]::WriteAllText($path, $xml, (New-Object System.Text.UTF8Encoding($false)))
        $out = & schtasks.exe /Create /TN $names[$k] /XML $path /F 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Host ("  [import] {0}" -f $names[$k]) -ForegroundColor Green }
        else { Write-Host ("  [FAIL] {0} :: {1}" -f $names[$k], ($out -join ' ')) -ForegroundColor Red }
    }
    foreach ($t in $names.Values) {
        $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        Write-Host ("  {0} -> {1}" -f $t, $(if ($task) { $task.State } else { 'MISSING' }))
    }
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
    'tasks-export' { Invoke-TasksExport ($Slot) }
    'tasks-import' { Invoke-TasksImport ($Slot) }
    'autostart' { Invoke-Autostart ($Slot) }
    'doctor'    { Invoke-Doctor }
    'help'      { Get-Help $PSCommandPath -Detailed }
    default     { Get-Help $PSCommandPath }
}
