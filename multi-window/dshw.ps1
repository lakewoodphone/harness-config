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
      dshw restore            reopen exactly the windows that were open when DSH was last closed
      dshw plan               show what `restore` would open and what the reconcile would forget,
                              and change nothing (a dry run; no window, no proxy, no registry write)
      dshw open <slot>        open (or focus) a window for an already-running slot
      dshw stop <slot>        stop one slot
      dshw restart <slot>     restart one slot
      dshw logs <slot>        tail that slot's log
      dshw autostart on|off   register/remove the logon task that runs: dshw up -WindowsMode restore
                              (engine, then the remembered windows - see Invoke-Autostart)
      dshw doctor             verify prerequisites and report exactly what is missing

    Exit codes: 0 ok, 1 nothing to do / partial, 2 bad usage, 3 precondition failed.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'restart', 'status', 'windows', 'new', 'restore', 'plan', 'ensure', 'open', 'stop', 'logs', 'health', 'autostart', 'watchdog', 'tasks-export', 'tasks-import', 'doctor', 'help')]
    [string]$Command = 'status',

    [Parameter(Position = 1)]
    [string]$Slot = '',

    [string]$ConfigPath = '',
    [int]$Lines = 40,
    # Default is NO windows. Starting the engine and opening eight windows are separate
    # intentions: the owner opens windows himself, one at a time, from the `+` in the UI
    # (or `dshw new`). `dshw up -WindowsMode yes` is the explicit "start everything" form.
    [ValidateSet('yes', 'no', 'auto', 'restore')]
    [string]$WindowsMode = 'no',
    # Launch engines through Task Scheduler so they cannot die with the calling shell. Use
    # when starting the fleet from an agent/tool session rather than a real terminal.
    [switch]$Detached,
    [switch]$Json,
    [switch]$Force,
    # `dshw plan` / `dshw restore -DryRun`: report the restore and reconcile plan and change nothing.
    # It is what makes the logon-restore decision testable without rebooting (WINDOW-KILLER.md 12).
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ── web search on a filtered network (DESKTOP-FGV6KMH only) ──────────────────────────────────────
#
# The harness web-search provider is a DeepSeek Anthropic-format Messages call that defaults to
# https://api.deepseek.com/anthropic/v1. On the owner's machines and on the office Mac that is
# reachable as itself; on Yocheved's LAPTOP it is blocked by URL category (Techloq), while chat is
# fine because chat uses the deepseek-proxy route. Search has its own endpoint, so it failed on every
# call and silently degraded into a dozen page fetches per answer.
#
# HOW THIS VARIABLE MAY BE SET AT ALL -- established by reading the installed harness, not guessed:
# `DEEPSEEK_SEARCH_BASE_URL` is in dsh-app-boot's BOOTSTRAP_NAMES, meaning it "decides how the process
# reaches the network". A .env file may NOT set it (the harness-home .env is the only layer ever
# exempted, and only for HTTP(S)_PROXY/NO_PROXY). Putting it in ~/.dsh/.env made the engine refuse to
# boot outright, and the symptom looked like a launcher fault. So it must be in the environment of the
# process that starts the engine -- which is this script, whichever entry point invoked it.
#
# It is HOSTNAME-GATED because the redirect exists for exactly one machine's filter; applying it
# everywhere would route every other machine's search through a Worker for no reason. Existing values
# win, so a launcher that already set one is not overridden.
#
# PLACEMENT MATTERS AND I GOT IT WRONG ONCE: this block must come AFTER the `param()` block.
# PowerShell requires `[CmdletBinding()]` and `param()` to be the first statements in a script, so an
# assignment above them is a parse error -- six of them, and the engine died on a busy day. Comment
# prose above `param()` is fine; executable code is not.
if ($env:COMPUTERNAME -eq 'DESKTOP-FGV6KMH' -and -not $env:DEEPSEEK_SEARCH_BASE_URL) {
    $env:DEEPSEEK_SEARCH_BASE_URL = 'https://ds.abletelsolutions.com/anthropic/v1'
}

# ── paths ───────────────────────────────────────────────────────────────────
$RepoRoot   = Split-Path -Parent $PSScriptRoot           # multi-window/ -> repo root

# CONFIG RESOLUTION: the machine's own file WINS, and this is not a convenience -- it is the fix for a
# launcher that clicked into nothing.
#
# MEASURED 2026-09-15 on Yocheved's laptop (DESKTOP-FGV6KMH). `multi-window/windows.json` is the
# OWNER's fleet config; it names `C:\Users\ezabz\.dsh\multi-window` as its stateDir. Every entry point
# that invoked this script WITHOUT `-ConfigPath` therefore ran against a stranger's directories. On
# her box `C:\Users\ezabz\.dsh` exists but is not writable by her user, so the very first diagnostics
# write -- `Add-Content ... watchdog.log` / `engine-recovery.log` -- threw, and because this script
# runs with `$ErrorActionPreference = 'Stop'` the exception aborted the launcher BEFORE a window was
# ever opened. The desktop shortcut then flashed a console for a few seconds and closed. Evidence:
# `C:\Users\cheve\.dsh\multi-window\logs\open.log`, 2026-09-15 09:44:14.
#
# Two entry points failed the same way on that box (a scheduled-task .vbs running `dshw.ps1 new`, and
# the open.cmd -> task chain), because both omitted the parameter. A default that is correct only when
# every caller remembers an argument is not a default. So the per-machine file is chosen here, once,
# and `doctor` prints which file was used -- this class of fault is then visible from one command.
if (-not $ConfigPath) {
    $machineCfg = Join-Path $PSScriptRoot ("machines\{0}.windows.json" -f $env:COMPUTERNAME)
    $ConfigPath = if (Test-Path $machineCfg) { $machineCfg } else { Join-Path $PSScriptRoot 'windows.json' }
}
if (-not (Test-Path $ConfigPath)) { Write-Error "config not found: $ConfigPath"; exit 3 }

$Cfg    = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$StateDir = $Cfg.server.stateDir
$LogDir   = $Cfg.server.logDir
New-Item -ItemType Directory -Force -Path $StateDir, $LogDir | Out-Null
$StatePath = Join-Path $StateDir 'state.json'

# Read an OPTIONAL key from windows.json without throwing.
#
# Under Set-StrictMode, `$Cfg.someNewKey` on a config that does not declare it throws
# "The property 'x' cannot be found on this object". That is exactly how a machine-specific
# `dshInstall` key failed: the read threw, `ensure` caught it, printed "start failed", and no
# engine was ever launched. An optional key that is absent must read as empty, never as an error.
function Get-ConfigValue([string]$name, $default = '') {
    if ($null -eq $Cfg) { return $default }
    $prop = $Cfg.PSObject.Properties[$name]
    if ($null -eq $prop) { return $default }
    if ($null -eq $prop.Value) { return $default }
    return $prop.Value
}

# A DIAGNOSTICS WRITE MUST NEVER BE THE REASON THE USER GETS NO WINDOW.
#
# This script runs with `$ErrorActionPreference = 'Stop'`, so a single unwritable log path is a hard
# abort of whatever was underway. MEASURED 2026-09-15 on her laptop: the launch sequence died on
# `Add-Content -LiteralPath ...\watchdog.log` (access denied against a state dir belonging to another
# user's profile) and never reached Open-SlotWindow. The symptom was "the shortcut opens a console
# for a few seconds and nothing else", because the only place the failure was recorded was a log the
# launcher never managed to write.
#
# Every write of a log line in this file goes through Add-Content, so the safe behaviour lives in one
# place: a shadowing function. It reports the problem on the console, never throws, and lets the
# caller carry on. Directory creation (line ~108) is still a hard check, so a genuinely unusable state
# dir is caught rather than papered over -- what changed is only that failing to *narrate* a run can
# no longer be what ends the run.
#
# The real cmdlet remains reachable as Microsoft.PowerShell.Management\Add-Content, and that is what
# Write-LogLine uses (calling the bare name there would recurse into this shim).
function Write-LogLine([string]$path, $text) {
    if (-not $path) { return }
    try {
        $dir = Split-Path -Parent $path
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $body = if ($text -is [array]) { $text -join [Environment]::NewLine } else { [string]$text }
        Microsoft.PowerShell.Management\Add-Content -LiteralPath $path -Value $body -Encoding utf8 -ErrorAction Stop
    } catch {
        Write-Host ("  [WARN] could not write {0}: {1}" -f $path, $_.Exception.Message) -ForegroundColor Yellow
    }
}

function Add-Content {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(ValueFromPipeline = $true)][AllowNull()]$Value,
        [string]$Encoding = 'utf8'
    )
    process { Write-LogLine -path $LiteralPath -text $Value }
}

# ── DSH_HOME: state it, never inherit it ────────────────────────────────────
#
# REPORT §7.2 OF THE 2026-09-17 INCIDENT (docs/incidents/2026-09-17-dsh-engine-boot-failure).
#
# The engine could not boot with `DSH_HOME` unset, because the module anchor generated into the
# `plugin-cost` bundle fell back to `USERPROFILE` — one segment short of the real home. The
# generator is fixed and the fallback is now right, and this is the other half of the same
# incident: until now the launcher only READ `DSH_HOME`, so the engine depended on inheriting it
# down Explorer -> cmd -> elevated pwsh -> node. That chain was never proved for the elevated path
# the desktop shortcut uses (the Copilot session said so explicitly, having declined to kill a
# healthy engine to find out). Nothing about it is needed: this script knows the home, so it says
# so, and an unset variable stops being a configuration the engine has to guess.
#
# SAME EXPRESSION AS `doctor`, and it is now the ONLY place it is written: `$env:USERPROFILE\.dsh`.
# A second convention here is how one launcher comes to hold two ideas of where the home is.
#
# AN EXISTING VALUE IS NEVER TOUCHED. `DSH_HOME` is documented as the override that gives a test
# or a second engine its own resolver — overwriting it would break exactly the case it exists for,
# and would have made the isolated cold-boot test below impossible.
function Initialize-DshHome([string]$logPath = '') {
    if ($env:DSH_HOME) { return $env:DSH_HOME }
    $userHome = $env:USERPROFILE
    # No profile to derive from (a scheduled task running as another account): leave it alone and
    # let the engine fall back the way it always did, rather than inventing a home.
    if (-not $userHome) { return $null }
    $value = Join-Path $userHome '.dsh'
    $env:DSH_HOME = $value
    Write-Host ("DSH_HOME was unset - using {0} explicitly, so the engine does not depend on inheriting it" -f $value) -ForegroundColor Yellow
    if ($logPath) {
        "[{0}] DSH_HOME was unset - set to {1} for the engine" -f (Get-Date -Format o), $value |
            Add-Content -LiteralPath $logPath -Encoding utf8
    }
    return $value
}

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
    # An explicit override wins: a machine may install DSH under its own npm prefix rather than the
    # npx cache or a profile. Yocheved's laptop does exactly that (`C:\Users\cheve\dsh`), and without
    # this the fleet could not find the engine binary at all -- `dshw doctor` reported
    # "@deepseek-ai/dsh/lib/bin.js not found" and every `ensure` silently did nothing, so the
    # launcher opened no window at all. Confirmed 2026-09-14.
    $candidates = @()
    # Read optional config keys defensively: under Set-StrictMode (which this script runs with)
    # touching a property a hand-written JSON does not declare THROWS, and that turned into
    # "ensure: start failed - The property 'dshBin' cannot be found on this object". A missing
    # optional key must simply mean "not configured".
    $cfgDshBin = ''
    $cfgDshInstall = ''
    $cfgDshBin = [string](Get-ConfigValue 'dshBin')
    $cfgDshInstall = [string](Get-ConfigValue 'dshInstall')
    foreach ($explicit in @($env:DSH_BIN, $cfgDshBin)) {
        if ($explicit) { $candidates += $explicit }
    }
    # A configured install ROOT (the npm prefix) is the friendlier knob: bin.js sits at a fixed path
    # beneath it, so a machine only has to say where DSH lives.
    foreach ($root in @($env:DSH_INSTALL, $cfgDshInstall)) {
        if ($root) { $candidates += (Join-Path $root 'node_modules\@deepseek-ai\dsh\lib\bin.js') }
    }
    $candidates += @(
        # THE FROZEN ENGINE COMES BEFORE THE npx CACHE (2026-09-30, owner's ZABZ-YOGA outage).
        #
        # The npx cache is NOT a pin. On 2026-09-30 the owner ran `npx @deepseek-ai/dsh web` by
        # hand, npx re-resolved the floating `@deepseek-ai/dsh` range, and the engine in the cache
        # changed from 0.1.5-rc.1 to 0.2.0-rc.2 underneath a running launcher that had no idea.
        # 0.2.0 had renamed packages the live profile still named, so the next boot died on
        # ERR_MODULE_NOT_FOUND; six failed boots and a raw stack trace later he was looking at a
        # broken machine that was never broken. A version that a stray `npx` can change is not
        # pinned. `~/.dsh/engine` is ours, is installed at an exact version, and nothing upgrades
        # it by accident -- so it is probed FIRST, and `dshInstall` in windows.json names it
        # explicitly on every machine. The npx paths stay only as a fallback for a machine that
        # has not been migrated yet.
        (Join-Path $env:USERPROFILE '.dsh\engine\node_modules\@deepseek-ai\dsh\lib\bin.js'),
        (Join-Path $env:LOCALAPPDATA 'npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js'),
        (Join-Path $env:USERPROFILE '.dsh\profiles\node_modules\@deepseek-ai\dsh\lib\bin.js')
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    # Scan the npx cache: the directory hash is not stable across machines, so the hardcoded path
    # above is a fast path rather than the only path.
    $npx = Join-Path $env:LOCALAPPDATA 'npm-cache\_npx'
    if (Test-Path $npx) {
        foreach ($d in (Get-ChildItem $npx -Directory -ErrorAction SilentlyContinue)) {
            $p = Join-Path $d.FullName 'node_modules\@deepseek-ai\dsh\lib\bin.js'
            if (Test-Path $p) { return $p }
        }
    }
    # fall back: the .bin shim's target, discovered from the shim itself
    $shim = Get-Command dsh -ErrorAction SilentlyContinue
    if ($shim) {
        $ps1 = $shim.Source
        if (Test-Path $ps1) {
            $m = Select-String -LiteralPath $ps1 -Pattern '(@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js)' -AllMatches
            if ($m) { return $m.Matches[0].Value }
        }
    }
    throw 'cannot locate @deepseek-ai/dsh/lib/bin.js -- set `dshInstall` in windows.json or $env:DSH_INSTALL to the npm prefix DSH is installed under'
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

# ── the two things that decide what a window COSTS ──────────────────────────
#
# MEASURED 2026-09-18 (ZABZ-YOGA, 7 windows open, one `--user-data-dir` per window):
#   profile w1 9 procs 917 MB | w2 9/1027 | w3 9/807 | w4 9/886 | w5 9/692 | w7 9/1064 | w8 9/854
#   = 74 msedge processes, 6804 MB. Each profile pays its OWN browser, GPU, crashpad, network and
#   utility processes: ~9 processes and a mean of 892 MB per window, for a UI that renders one page.
#   The private profile buys exactly one thing - a per-window cookie jar and a per-window
#   localStorage['dsh.sessions.current'] - and that one thing can be bought far more cheaply by
#   giving each window its own loopback ORIGIN instead (the key is namespaced by origin, not by
#   profile), which lets every window share ONE browser process tree.
#
# So profileMode 'shared' is the default and 'per-window' is the escape hatch. What the owner
# keeps either way: separate windows, one per slot, each remembering its own session, all of them
# restorable after a reboot. What changes: one browser process instead of one per window.
function Get-ProfileMode {
    $m = [string](Get-Prop $Cfg.browser 'profileMode')
    if ($m -ne 'shared' -and $m -ne 'per-window') { $m = 'shared' }
    return $m
}

function Get-SharedProfileName {
    $name = [string](Get-Prop $Cfg.browser 'sharedProfile')
    if (-not $name) { $name = '_shared' }
    return $name
}

# Which --user-data-dir this slot's window uses. In shared mode this is the SAME directory for
# every slot, and that is the point: it is the one browser tree.
function Get-SlotProfileDir($slot) {
    if ((Get-ProfileMode) -eq 'shared') {
        return (Join-Path $Cfg.browser.profileRoot (Get-SharedProfileName))
    }
    return (Join-Path $Cfg.browser.profileRoot $slot.profile)
}

function Get-OriginsConfig {
    $p = $Cfg.PSObject.Properties['origins']
    if (-not $p -or -not $p.Value) { return $null }
    return $p.Value
}

# Is the per-window loopback-origin proxy configured AND usable?
function Test-OriginsEnabled {
    $o = Get-OriginsConfig
    if (-not $o) { return $false }
    if ($o.PSObject.Properties['enabled'] -and $o.enabled -eq $false) { return $false }
    return $true
}

# The origin port for one slot: STABLE PER SLOT, because it is what identifies that window's
# session slot across a reload. Slot i always gets basePort + i, in windows.json order.
function Get-SlotOriginPort($slot) {
    if (-not (Test-OriginsEnabled)) { return (Get-PrimaryPort) }
    $o = Get-OriginsConfig
    # 3300, not 3200: the old 3200..3223 block swallowed port 3216, which the EA App's
    # in-game-overlay IPC server binds - see the _basePortWhy note in windows.json.
    $base = 3300
    if ($o.PSObject.Properties['basePort'] -and $o.basePort) { $base = [int]$o.basePort }
    return [int]($base + $slot.index)
}

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
#
# THAT LAST SENTENCE WAS WRONG, AND IT COST TEN MINUTES ON 2026-09-17 (report §7.3). A child that
# dies during boot does NOT "fail the timeout anyway" in any useful sense: it fails it 180
# SECONDS later, three times over, because nothing here looks for a death — the engine threw,
# exited 1, and this loop kept waiting for a URL that could never come. The fix is not
# `HasExited` (that is the hang recorded above); it is `-ExitPid`, an OPT-IN probe that asks the
# OS the question that cannot block: does this pid still exist? Only the direct-spawn path passes
# it, because only there is the pid this process's own child; the detached path keeps the old
# behaviour untouched.
function Wait-ServerReady([string]$log, [long]$offset, [int]$timeoutSeconds, [int]$port, [int]$ExitPid = 0) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    $sawUrl = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if ($ExitPid -gt 0 -and -not (Test-PidExists $ExitPid)) { return $null }
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

# Is this pid still running? A REFUSAL IS NOT AN ANSWER, so only one exception counts.
#
# `Process.GetProcessById` throws ArgumentException when the process is not running — that is a
# definitive "gone". Any OTHER failure (access denied, a transient) says nothing, so this returns
# $true and the caller carries on waiting: a probe that can report a live engine dead is worse
# than no probe, and a false "it died" would have `ensure` retry against a boot that was fine.
function Test-PidExists([int]$processId) {
    try {
        $null = [System.Diagnostics.Process]::GetProcessById($processId)
        return $true
    } catch [System.ArgumentException] {
        return $false
    } catch {
        return $true
    }
}

# ── port / process helpers ──────────────────────────────────────────────────
# One TCP connection table per call, not per lookup: an unfiltered
# Get-NetTCPConnection is the single most expensive thing this script does.
function Get-ListenTable {
    $age = Get-Variable -Name ListenTableAge -Scope Script -ValueOnly -ErrorAction SilentlyContinue
    if ($age -and ((Get-Date) - $age).TotalSeconds -lt 5) { return $script:ListenTable }
    # AN EMPTY LISTEN TABLE IS A FAILED READ, NOT A QUIET MACHINE (2026-09-14).
    #
    # There is no state in which a live Windows box has zero listening sockets -- RPC, SMB and
    # the like always listen -- so a null/empty result means the read failed, which on this
    # machine happens under load. The consequence used to be silent and severe: Get-PortOwner
    # returned $null, so `Ensure-Engine` concluded the port was free, never reclaimed the wedged
    # engine that really owned 3099, and died with "address already in use" instead. That is the
    # whole of engine-recovery.log 17:49:33 -> 17:49:38, and why the owner had a wedged engine
    # for 100 minutes while the 1-minute watchdog logged a failure a minute. Retry before
    # believing an empty answer.
    $table = $null
    for ($i = 1; $i -le 3; $i++) {
        $table = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
        if ($table -and @($table).Count -gt 0) { break }
        Start-Sleep -Milliseconds 400
    }
    $script:ListenTable = $table
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

function New-HiddenLauncherVbs {
    # Write (and return the path of) a wscript wrapper that runs a command with SW_HIDE, so its
    # console never shows a window. `-WindowStyle Hidden` hides only AFTER the console has appeared,
    # so a 1-minute watchdog task still flashed a PowerShell window and stole focus (the owner's
    # dictation/typing kept getting clobbered). WScript.Shell.Run cmd, 0, True creates the process
    # hidden, waits, and returns its exit code, so Task Scheduler's Last Run Result and
    # ExecutionTimeLimit keep their meaning.
    #
    # Split out of New-HiddenTaskAction so the origins proxy can reuse the SAME hidden launcher for
    # its direct (Task-Scheduler-denied) fallback: one wrapper, two independent ways to start it.
    param(
        [Parameter(Mandatory)][string]$Execute,
        [string]$Argument,
        [string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$TaskName
    )
    $wrapperDir = Join-Path $RepoRoot 'scripts\hidden-tasks'
    New-Item -ItemType Directory -Force -Path $wrapperDir | Out-Null
    $cmd = if ($Argument) { '"{0}" {1}' -f $Execute, $Argument } else { '"{0}"' -f $Execute }
    $safe = $TaskName -replace '[^\w\-]', '_'
    $vbs = Join-Path $wrapperDir "$safe.vbs"
    $esc = $cmd.Replace('"', '""')
    $lines = @(
        "' Generated by dshw.ps1 - hidden launcher for task '$TaskName'.",
        'Set sh = CreateObject("WScript.Shell")'
    )
    if ($WorkingDirectory) {
        $lines += "sh.CurrentDirectory = `"$($WorkingDirectory.Replace('"','""'))`""
    }
    $lines += "WScript.Quit sh.Run(`"$esc`", 0, True)"
    [System.IO.File]::WriteAllText($vbs, ($lines -join "`r`n") + "`r`n", (New-Object System.Text.UTF8Encoding($false)))
    return $vbs
}

function New-HiddenTaskAction {
    param(
        [Parameter(Mandatory)][string]$Execute,
        [string]$Argument,
        [string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$TaskName
    )
    $vbs = New-HiddenLauncherVbs -Execute $Execute -Argument $Argument -WorkingDirectory $WorkingDirectory -TaskName $TaskName
    $wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
    return New-ScheduledTaskAction -Execute $wscript -Argument ('//B //NoLogo "{0}"' -f $vbs)
}

function Invoke-HiddenTaskBootstrap {
    # Self-heal: convert every interactive console scheduled task to a hidden launcher so the
    # fleet stops popping PowerShell/python windows. Runs only when elevated (modifying these
    # tasks needs admin) and at most once a day per machine (marker in LOCALAPPDATA, which
    # autosync does not copy, so each machine keeps its own). Daily rather than once-ever on
    # purpose: if some installer re-registers a visible task, the next day's pass hides it
    # again instead of the owner having to report the popups a second time.
    # Non-fatal by design: this must never break the watchdog's real job of keeping the engine alive.
    if (-not (Test-IsElevated)) { return }
    $marker = Join-Path $env:LOCALAPPDATA 'harness-config\hidden-tasks.applied'
    if (Test-Path $marker) {
        $age = (Get-Date) - (Get-Item -LiteralPath $marker).LastWriteTime
        if ($age.TotalHours -lt 24) { return }
    }
    $script = Join-Path $RepoRoot 'scripts\Set-TaskHidden.ps1'
    if (-not (Test-Path $script)) { return }
    try {
        & pwsh -NoProfile -NonInteractive -File $script *> $null
        if ($LASTEXITCODE -eq 0) {
            New-Item -ItemType Directory -Force -Path (Split-Path $marker) | Out-Null
            [System.IO.File]::WriteAllText($marker, (Get-Date).ToString('o'), (New-Object System.Text.UTF8Encoding($false)))
        }
    } catch { }
}

function Set-LiveEngineUrl($url) {
    # THE ONE THING THE LAUNCHER ALREADY KNOWS AND THE OWNER STILL HAS TO BE TOLD (added 2026-09-30).
    #
    # The launch token is single-use and per-process: every engine boot mints a new one, and an
    # already-open window that reloads WITHOUT the token lands on "dsh web authentication required".
    # That is exactly what the owner hit on ZABZ-YOGA -- and it is also why a window looks broken
    # after a supervisor restarts the engine for its own reasons. Until this existed the only places
    # the token lived were the engine's stdout (thrown away on a detached boot) and `state.json`.
    # One small file, rewritten on every successful start, is what makes "open this URL" answerable
    # by anyone -- a person, a script, or another agent over SSH.
    if (-not $url) { return }
    # ONLY THE ENGINE'S OWN URL. The launcher also resolves per-window URLs on the origin ports
    # (3200..3223); writing one of those here produced a file that said :3214 and sent the next
    # reader to a proxy alias instead of the engine (measured 2026-10-01 00:39). The engine port is
    # the only one this file may name.
    $maybe = [regex]::Match([string]$url, '127\.0\.0\.1:(\d{1,5})')
    if ($maybe.Success -and [int]$maybe.Groups[1].Value -ne [int](Get-PrimaryPort)) { return }
    try {
        $p = Join-Path $StateDir 'live-url.txt'
        [System.IO.File]::WriteAllText($p, [string]$url, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

function Start-EngineDetached($inv, [int]$timeoutSeconds) {
    $mustUnregister = $false
    $existing = Get-ScheduledTask -TaskName $inv.taskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        # cmd.exe carries the scratch TEMP into the task: a scheduled-task action cannot
        # express environment variables directly, and without this the detached path would
        # still hand the engine the OS tmpdir that Windows deletes underneath it.
        $scratch = Get-EngineScratchDir
        $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" `
            -Argument "/c set `"TEMP=$scratch`" && set `"TMP=$scratch`" && `"$($inv.node)`" `"$($inv.bin)`" web --port $($inv.port) --no-open" `
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

    # FALLBACK: Task Scheduler is not dependable everywhere. On DESKTOP-FGV6KMH a task
    # registers, reports LastTaskResult 0, and nothing runs -- including a trivial
    # `cmd /c echo` marker task (measured 2026-09-14). Because this function was the only
    # launch path, `ensure` then failed silently, the engine never started, and the desktop
    # shortcut opened no window at all. So an immediate bind check is mandatory: if the task
    # produced nothing, start the engine through WMI instead, which also escapes this
    # process's job object and needs no service registration.
    Start-Sleep -Milliseconds 1200
    $boundEarly = $false
    try {
        $probeEarly = New-Object System.Net.Sockets.TcpClient
        $t = $probeEarly.ConnectAsync('127.0.0.1', $inv.port)
        if ($t.Wait(1200)) { $boundEarly = $probeEarly.Connected }
        $probeEarly.Dispose()
    } catch { }
    if (-not $boundEarly -and -not (Test-Path $inv.log)) {
        try {
            $scratch = Get-EngineScratchDir
            $outer = "$env:SystemRoot\System32\cmd.exe"
            $inner = "/c set `"TEMP=$scratch`" && set `"TMP=$scratch`" && `"`"$($inv.node)`" `"$($inv.bin)`" web --port $($inv.port) --no-open 1> `"`"$($inv.log)`"`" 2> `"`"$($inv.err)`"`"`""
            $res = ([wmiclass]'Win32_Process').Create("$outer $inner", $inv.cwd, $null)
            if ($res.ReturnValue -eq 0) {
                Write-Host ("start: Task Scheduler produced nothing - engine started via WMI (pid {0})" -f $res.ProcessId) -ForegroundColor Yellow
            } else {
                Write-Host ("start: WMI fallback returned {0}" -f $res.ReturnValue) -ForegroundColor Red
            }
        } catch {
            Write-Host ("start: WMI fallback failed - {0}" -f $_.Exception.Message) -ForegroundColor Red
        }
    }

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
                if ($m.Success) { $url = $m.Groups[1].Value; Set-LiveEngineUrl $url }
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

# ── ENGINE SCRATCH: keep the engine's os.tmpdir() out of Windows' cleanup scope ─────────────
#
# THE CRASH THIS PREVENTS, 2026-09-25 on ZABZ-YOGA. The engine spills oversized tool output
# into a private directory under the OS tmpdir (`mkdtempSync(join(tmpdir(), "dsh-subprocess-"))`,
# dsh-subprocess-local/lib/runner-launch-*.js:683). Nothing inside the harness removes that
# directory while the engine lives - the only removal is `process.once("exit")` at :687-692.
# Windows does. C: had fallen to 8% free, Storage Sense ran (free went 36 GB -> 61 GB in one
# pass), `%TEMP%\dsh-subprocess-USflM9` was deleted underneath a RUNNING engine, and the
# collector then tried to open its spill file inside the vanished directory:
#
#   Error: ENOENT: no such file or directory, open
#     '...\Temp\dsh-subprocess-USflM9\dsh-subprocess-12680-1-...-stdout.log'
#       at OutputCollector.spillAll (runner-launch-COYGu0Dl.js:766)
#       at OutputCollector.push   (runner-launch-COYGu0Dl.js:742)
#       at Socket.<anonymous>
#
# That throw is unhandled, so the ENGINE DIED - port 3099 stopped answering at 15:36:39 and the
# watchdog restarted it as pid 21440 by 15:37:08. Everything that felt "slow" followed from that:
# the dead engine, its cold replacement, and every in-flight turn. The corpus was measured and
# exonerated for this (a healthy engine walks all 843 sessions in 1,165 ms).
#
# A scratch directory inside DSH_HOME is in no cleanup scope, so the trigger cannot recur.
# `-Environment` is PowerShell 7.4+; this file's parallel-spawn path already depends on it.
function Get-EngineScratchDir {
    [void](Initialize-DshHome)
    $root = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }
    $dir = Join-Path $root 'tmp'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

function Start-SlotServer($slotCfg, $inv = $null) {
    # REPORT §7.2 OF THE 2026-09-17 INCIDENT. Every launch path funnels through here — `up`,
    # `restart`, `ensure`, `new`, `restore`, the watchdog — so this is where the engine's
    # environment is settled, once, instead of being inherited and hoped for. Idempotent, and
    # silent when DSH_HOME is already set.
    [void](Initialize-DshHome)
    # $inv is passed in by Ensure-Engine, which needs the SAME log paths afterwards to read the
    # stderr of the attempt that just failed. Re-deriving it here would be wrong: the name is
    # stamped with the second, so a call made a moment later names a file that does not exist.
    if (-not $inv) { $inv = Get-ServerInvocation $slotCfg }
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
    # TEMP/TMP are routed into DSH_HOME/tmp so Windows' own cleanup cannot delete the
    # engine's spill directory while it is running. See Get-EngineScratchDir above.
    $scratch = Get-EngineScratchDir
    $p = Start-Process -FilePath $inv.node -ArgumentList @($inv.bin, 'web', '--port', "$($inv.port)", '--no-open') `
            -WorkingDirectory $inv.cwd -WindowStyle Hidden -PassThru `
            -Environment @{ TEMP = $scratch; TMP = $scratch } `
            -RedirectStandardOutput $inv.log -RedirectStandardError $inv.err

    # $p.Id is passed as -ExitPid: this child is ours, so a boot that throws and exits is noticed
    # in half a second instead of after the whole 180 s budget. See Wait-ServerReady.
    $url = Wait-ServerReady $inv.log 0 ([int]$Cfg.server.startTimeoutSeconds) $inv.port $p.Id
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
# `$inv` is optional and only Ensure-Engine uses it, to keep the attempt's log paths.
function Start-OneSlotServer($slotCfg, $inv = $null) {
    if (-not $inv) { $inv = Get-ServerInvocation $slotCfg }
    $r = Start-SlotServer $slotCfg $inv
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
            -Environment @{ DSHW_PAYLOAD = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload)); TEMP = (Get-EngineScratchDir); TMP = (Get-EngineScratchDir) } | Out-Null
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

. "$PSScriptRoot\dshw-geometry.ps1"

# Which URL a window opens: the engine's TOKENIZED launch URL whenever one can be found, and the
# clean origin only as a last resort.
#
# MEASURED 2026-09-15 (ZABZ-TECH), because the decision recorded here on 2026-09-14 was wrong:
#   - That note claimed the tokenized URL "burns a one-time exchange" and lands on "a NEW document
#     whose bootstrap finds no session". Both are false. The launch token is a stable per-process
#     value (dsh-client-connection/lib/browser-auth.js: processLaunchToken caches it in a WeakMap on
#     the process owner) and is re-exchangeable at will; and nothing in the client boot path reads
#     location.search except the `?fixture=` test hooks, so the 303 -> "/" document is
#     indistinguishable from a direct load of "/". Session choice is localStorage
#     ["dsh.sessions.current"], keyed by origin, and survives either way.
#     Proof: a throwaway profile launched twice at the tokenized URL kept ONE window root and the
#     SAME session id (session-ea10e311-c9ae-48ce-886b-8b44eb1846df) across both launches.
#   - The clean origin authenticates ONLY through the profile's cookie, and NOTHING ever seeded that
#     cookie: a profile that has never exchanged a token -- or one whose 30-day cookie expired or was
#     cleared -- is served the bare 401 page "dsh web authentication required; reopen the URL printed
#     by dsh web". Reproduced headlessly on a fresh profile, and it is exactly what the owner hit on
#     2026-09-15 at 17:00-17:03 with profile w9: three attempts, three 401 pages. Every profile that
#     did work (w1..w8) had been seeded as a side effect of an older launcher that still opened the
#     tokenized URL.
# So the tokenized URL is preferred: it authenticates regardless of what the cookie jar holds, and a
# stale token degrades safely -- the server 303s an already-cookied browser to the clean "/".
function Test-LaunchUrl([string]$url, [int]$port) {
    if ([string]::IsNullOrWhiteSpace($url)) { return $false }
    try { $u = [uri]$url } catch { return $false }
    if ($u.Scheme -ne 'http' -or $u.Host -ne '127.0.0.1' -or $u.Port -ne $port) { return $false }
    if ($u.AbsolutePath -ne '/') { return $false }
    return [regex]::IsMatch($u.Query, '(?:^|[?&])token=[^&]+')
}

function Resolve-WindowUrl([int]$port, $rec, [int]$AliasPort = 0) {
    # $port is the ENGINE port the token must be valid for; $AliasPort is the origin the WINDOW
    # actually opens. They differ in the shared-profile model, and the rewrite is safe because the
    # token is a per-PROCESS value: the engine validates it against its own launch token, and the
    # Host header the browser sends (127.0.0.1:<AliasPort>) is accepted by the /api browser-trust
    # fence for ANY 127.0.0.1:<port> (measured 2026-09-18: a bare port alias answers 401 = fence
    # passed, auth missing, where `w1.localhost` answers 403 = fence refused).
    #
    # WHY THE TOKEN IS NOW PROBED AND NOT TRUSTED (measured 2026-09-18, and it was live):
    # `state.json` recorded pid 29116 / startedAt 13:45:30 while the engine actually serving 3099
    # was pid 4416, started 21:39. Its recorded token answered **401**, and the token in the
    # engine's own newest log line answered **303**. Test-LaunchUrl only ever checked the SHAPE of a
    # token, so the launcher would have handed every new window the dead one and landed it on
    # "dsh web authentication required". `dshw doctor` had been reporting this as a blocker for a
    # while without anything acting on it. So the recorded URL is now a CANDIDATE, and the one that
    # survives a real request is the one used.
    $rewrite = {
        param($url, $ap)
        if (-not $ap -or $ap -le 0) { return $url }
        try {
            $u = [uri]$url
            if ($u.Port -eq $ap) { return $url }
            return ('http://127.0.0.1:{0}/{1}' -f $ap, $u.Query)
        } catch { return $url }
    }

    $candidates = @()
    if ($rec) {
        $recorded = [string](Get-Prop $rec 'url')
        if (Test-LaunchUrl $recorded $port) { $candidates += $recorded }
    }
    # A token belongs to the process that printed it, and the engine prints its own URL at startup,
    # so the newest log line for this port is the freshest evidence -- the LAST match, because a log
    # can hold several launches.
    $fromLog = @()
    foreach ($log in @((Join-Path $LogDir "$port.log"), $(if ($rec) { Get-Prop $rec 'log' }))) {
        if (-not $log -or -not (Test-Path $log)) { continue }
        try { $text = Get-Content -LiteralPath $log -Raw -ErrorAction Stop } catch { continue }
        $m = [regex]::Matches($text, 'dsh web:\s*(\S+)')
        for ($i = $m.Count - 1; $i -ge 0; $i--) {
            $cand = $m[$i].Groups[1].Value
            if ((Test-LaunchUrl $cand $port) -and ($candidates -notcontains $cand)) {
                $candidates += $cand
                $fromLog += $cand
            }
        }
    }
    if ($candidates.Count -eq 0) { return "http://127.0.0.1:$(if ($AliasPort -gt 0) { $AliasPort } else { $port })/" }

    foreach ($cand in $candidates) {
        if (Test-TokenAccepted $cand $port) {
            $chosen = (& $rewrite $cand $AliasPort)
            Set-LiveEngineUrl $chosen
            return $chosen
        }
    }
    # NOTHING answered 303. That is either a dead token or an engine too loaded to answer, and those
    # want opposite choices: the engine's own log line is the better bet of the two, because a token
    # that was never current cannot become current, whereas a busy engine will accept a live one in
    # a moment. The browser retries the origin, so a slow engine is survivable; a wrong token is not.
    if ($fromLog.Count -gt 0) {
        Write-Host ("  [WARN] no launch token for port {0} answered a probe; using the engine's own newest log token (a stale recorded token is the usual cause -- `dshw doctor` names it)" -f $port) -ForegroundColor Yellow
        return (& $rewrite $fromLog[0] $AliasPort)
    }
    return (& $rewrite $candidates[0] $AliasPort)
}

# Does this launch token actually work? The launch URL 303s to "/" on acceptance; 401/403 is a
# refusal. Any exception is "unknown" and counts as NOT accepted, because the caller has a better
# candidate to try and a leftover-but-dead token is the failure this exists to prevent.
function Test-TokenAccepted([string]$url, [int]$port, [int]$TimeoutMs = 6000) {
    if (-not (Test-LaunchUrl $url $port)) { return $false }
    $client = $null
    try {
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $handler.AllowAutoRedirect = $false
        $client = [System.Net.Http.HttpClient]::new($handler)
        $client.Timeout = [TimeSpan]::FromMilliseconds($TimeoutMs)
        $resp = $client.SendAsync([System.Net.Http.HttpRequestMessage]::new('GET', $url)).GetAwaiter().GetResult()
        $code = [int]$resp.StatusCode
        $resp.Dispose()
        return ($code -ge 200 -and $code -lt 400)
    } catch {
        return $false
    } finally {
        if ($client) { $client.Dispose() }
    }
}

function Open-SlotWindow($slot, $state) {
    $exe = Get-EdgePath
    if (-not $exe) { throw 'no Edge/Chrome binary found' }

    # In single mode every window talks to the primary server, but each keeps its
    # own browser profile so its cookie jar and "last session" are its own.
    #
    # `Get-Prop`, NOT `$slot.port`, AND THAT WAS A LIVE BREAKAGE (found 2026-09-18 while opening a
    # test window). `Get-SlotCfgByPortOrLabel` builds its slots from the RAW config rows, which have
    # no `port` key at all in single mode - and under `Set-StrictMode -Version Latest` merely naming
    # `$slot.port` on the branch taken throws, so `dshw open <slot>` died with "The property 'port'
    # cannot be found on this object" before it opened anything. `new`, `restore` and the watchdog
    # pass RESOLVED slots and were unaffected, which is why this went unnoticed: the single-window
    # `open` path is the one a person uses by hand.
    $targetPort = if (Get-Mode -eq 'multi') { [int](Get-Prop $slot 'port') } else { Get-PrimaryPort }
    $rec = Get-SlotRecord $state $targetPort

    # THE TWO LINES THAT DECIDE WHAT A WINDOW COSTS (2026-09-18). The profile is shared, so the
    # browser process tree is shared; the ORIGIN is per-slot, so the session slot is not.
    $profDir = Get-SlotProfileDir $slot
    New-Item -ItemType Directory -Force -Path $profDir | Out-Null
    $originPort = Get-SlotOriginPort $slot
    if ((Get-ProfileMode) -eq 'shared' -and -not (Test-OriginsEnabled)) {
        # Shared storage with no per-window origin means every window would share one
        # localStorage['dsh.sessions.current'] - the exact limitation the per-window profiles used
        # to avoid. Say so rather than degrading silently.
        Write-Host "  [WARN] profileMode=shared with origins disabled: all windows will share one session slot" -ForegroundColor Yellow
    }
    # A PROXY THAT IS DOWN MUST NOT MEAN A WINDOW THAT CANNOT OPEN. Falling back to the engine port
    # costs the owner per-window session isolation (every window then shares one session slot) but
    # it keeps the window usable and the failure visible, which is strictly better than a dead
    # window. `ensure` picks the proxy back up within the minute.
    if ($originPort -ne $targetPort -and -not (Test-OriginsProxy -Quiet)) {
        Write-Host ("  [WARN] origin proxy not answering; opening slot '{0}' directly against :{1} (this window will SHARE the session slot of any other window opened the same way)" -f $slot.label, $targetPort) -ForegroundColor Yellow
        $originPort = $targetPort
    }

    # The engine's tokenized URL, so a window can never land on the 401 page (see Resolve-WindowUrl
    # above for the measurement that reversed the previous "clean origin" decision). "One window,
    # same session" is unaffected: the 303 to "/" happens inside this window, and the session comes
    # from the profile's own localStorage, not from the URL.
    $target = Resolve-WindowUrl $targetPort $rec $originPort
    $label = if ($slot.label) { $slot.label } else { "$targetPort" }
    # NOTE (measured 2026-09-11, Edge 152 on Windows): --window-name is a no-op here and
    # the window caption is the page <title>.
    #
    # NOTE (measured 2026-09-18, and it CONTRADICTS the note that used to sit here). The old comment
    # claimed geometry "only takes effect because each window has its own --user-data-dir". That is
    # wrong: a second `--app=` launch into an ALREADY-RUNNING profile is handed to the existing
    # browser process, and Edge applies --window-size/--window-position to the window it opens.
    # Verified by launching two windows into the shared profile on two alias origins and reading the
    # resulting rectangles (see docs/multi-window/MEMORY-AND-SESSION-LIST.md).
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
    # Placement: the owner's rule wins over the manifest. A remembered rectangle is used when
    # the manifest has one AND the caller asked for a remembered launch (`restore`); a fresh
    # window (`new`, and the + control) is placed on the monitor the pointer is on, cascaded
    # off the window already there. `dshw save-layout` writes what he has arranged.
    $slotSize = Get-Prop $slot 'size'
    $slotPos  = Get-Prop $slot 'position'
    if (-not $slotPos) {
        try {
            $placement = Get-PlacementForNewWindow
            $slotPos = $placement.position
            $slotSize = $placement.size
            Write-Host ("  placing on {0} at {1}" -f $placement.monitor, $slotPos) -ForegroundColor DarkGray
        } catch { }
    }
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
    $line = "[{0}] open slot={1} profile={2} origin={3} pid={4} args={5}" -f (Get-Date -Format o), $label, $slot.profile, $originPort, $proc.Id, ($winArgs -join ' ')
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
    # Count distinct app URLs, not processes: Edge may hold several window ROOTS on one profile,
    # and child processes inherit the parent's command line.
    #
    # IN SHARED-PROFILE MODE THE PROFILE NO LONGER IDENTIFIES A WINDOW. Every slot has the same
    # --user-data-dir, so a profile match would report the SAME count for all 16 slots - and `new`,
    # which picks the first slot with zero windows, would conclude there is no free slot and refuse
    # to open anything. Measured 2026-09-18 on the one shared-profiled window that existed: it
    # matched profile `_shared`, which no slot names, so no slot counted it at all.
    # The ORIGIN PORT is the per-slot identity now, because it is what the window actually opens.
    #
    # AND IT IS THE IDENTITY IN *EVERY* MODE - the previous version asked the proxy only in shared
    # mode and fell back to a profile scan otherwise, which is the shape that read a live
    # proxy-origin window as "empty" the moment the proxy was unreachable, and read a legacy
    # 127.0.0.1:3099 window as "empty" always. `Get-OpenOriginPorts` now unions the proxy's own
    # per-port connection count with a process scan keyed on each window's ORIGIN PORT, so one
    # answer covers the shared profile, the per-window profiles, the engine port and a dead proxy.
    $shared = (Get-ProfileMode) -eq 'shared' -and (Test-OriginsEnabled)
    $originPort = Get-SlotOriginPort $slotCfg
    try {
        if (@(Get-OpenOriginPorts) -contains [int]$originPort) { return 1 }
    } catch { }

    # NOTHING CLAIMS THIS SLOT'S ORIGIN. In shared-profile mode a window opened directly against the
    # engine port is indistinguishable from its siblings - they are all in ONE browser tree, and
    # only the first one's URL is in any command line - but "the owner closes every window on 3099
    # that I am trying to reopen because I could not see any of them" is a catastrophic false
    # negative (it duplicates the whole fleet), and it is the exact failure `new` hit. So a live
    # window on the engine port counts for the FIRST slot that asks, which is where the launcher
    # puts such a window anyway (Open-SlotWindow falls back to the engine port with a warning).
    if ($shared -and (Get-EnginePortWindowCount) -gt 0) {
        $firstOrigin = [int](Get-SlotOriginPort (@(Get-Slots) | Select-Object -First 1))
        if ([int]$originPort -eq $firstOrigin) { return 1 }
    }

    # Last resort, and only reachable PER-WINDOW (or with the proxy and the process scan
    # both silent): match this slot's own --user-data-dir.
    #
    # NEVER IN SHARED-PROFILE MODE. This one missing guard is why the `+`/`⧉` new-window
    # control did nothing for hours on 2026-09-18 (measured, not inferred). In shared
    # mode every slot carries the SAME --user-data-dir (`_shared`), so ONE live window
    # satisfies this match for ALL SIXTEEN slots. Get-WindowCount then answered 1 for
    # every slot, Invoke-New found no free slot, and it printed "all 16 window slots are
    # already open" to a console the `dsh-new://` protocol runs HIDDEN (the registry
    # command passes -WindowStyle Hidden) and exited 0 -- no window, no error, no line in
    # windows.log. `dshw status` showed it plainly: sixteen rows, each `windows 1`, the SAME
    # memory figure on every row and `_shared` -- one browser tree counted sixteen times. The
    # figure was 787 MB on ZABZ-YOGA (2026-09-18) and 338 MB on ZABZ-TECH (2026-09-20); the tell
    # is that it is identical on all sixteen rows, not what the number is.
    #
    # The comment above Get-WindowCount's origin-port test already states the rule this
    # line broke: in shared-profile mode the PROFILE IS NOT PER-SLOT IDENTITY. The origin
    # port is, and Get-OpenOriginPorts is the authority for it -- including when the proxy
    # is silent, because it unions the proxy's per-port count with a process scan.
    if ($shared) { return 0 }

    $profDir = Get-SlotProfileDir $slotCfg
    try {
        $procs = Get-WindowProcs $table
        $urls = @($procs |
            Where-Object {
                if (-not $_.CommandLine) { return $false }
                if (-not $_.CommandLine.Contains('--app=')) { return $false }
                if ($_.CommandLine.Contains('--type=')) { return $false }
                return $_.CommandLine.Contains($profDir)
            } | ForEach-Object {
                if ($_.CommandLine -match '--app=(\S+)') { $Matches[1] }
            } | Select-Object -Unique)
        return $urls.Count
    } catch { return 0 }
}

function Get-SlotCfgByPortOrLabel([string]$selector) {
    # Matches by port, label OR profile, and always returns a slot from the one canonical source
    # (`Get-Slots`) - so callers get `index`, which `Get-SlotOriginPort` needs.
    #
    # THE `open` COMMAND USED TO DIE HERE WITH "The property 'index' cannot be found on this
    # object", and the cause was NOT this function: the dispatch block did `$slot = $null` before
    # calling it, and PowerShell variable names are case-insensitive, so that assignment cleared the
    # `$Slot` PARAMETER - the selector was already an empty string by the time it arrived. See the
    # `'open'` branch. This function is only here to be the single place a selector becomes a slot.
    if (-not $selector) { return $null }
    foreach ($s in @(Get-Slots)) {
        if ("$($s.port)" -eq $selector -or "$($s.label)" -eq $selector -or "$($s.profile)" -eq $selector) {
            return $s
        }
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

    if ($WindowsMode -eq 'restore') {
        Invoke-Restore
    }
    elseif ($WindowsMode -in @('yes', 'auto')) {
        [void](Ensure-OriginsProxy)
        $state = Get-State
        foreach ($slot in $enabledWindows) {
            try { [void](Open-SlotWindow $slot $state) }
            catch { Write-Host ("  [WARN] could not open window '{0}': {1}" -f $slot.label, $_.Exception.Message) -ForegroundColor Yellow }
        }
        $map = Get-WindowRegistry
        foreach ($slot in $enabledWindows) { Set-WindowRegistryEntry $map (Get-SlotRegistryKey $slot) $true (Get-SlotOriginPort $slot) }
        Save-WindowRegistry $map
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
            profile = if ((Get-ProfileMode) -eq 'shared') { Get-SharedProfileName } else { $slot.profile }
            origin  = Get-SlotOriginPort $slot
        }
    }
    if ($Json) { [pscustomobject]@{ mode = (Get-Mode); primaryPort = $primary; profileMode = (Get-ProfileMode); origins = (Test-OriginsEnabled); slots = $rows } | ConvertTo-Json -Depth 4; return }
    Write-Host ("mode: {0}{1}, profileMode: {2}" -f (Get-Mode), $(if ($primary) { " (engine on port $primary)" } else { '' }), (Get-ProfileMode))
    $rows | Format-Table -AutoSize slot, enabled, engine, server, windows, mem_mb, profile, origin
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
    if (Test-OriginsEnabled) {
        $a = Get-OriginsArgs
        if (Test-OriginsProxy -Quiet) {
            $st = Get-OriginsStats
            Write-Host ("origins: proxy up on :{0}..:{1}; session/list served={2} cold={3} cacheAgeMs={4} rows={5}" -f `
                $a.basePort, ($a.basePort + $a.count - 1), $st.served, $st.cold, $st.ageMs, $st.rows)
        } else {
            Write-Host ("origins: proxy NOT ANSWERING on :{0} - run: dshw ensure" -f $a.basePort) -ForegroundColor Red
        }
    }
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

# ── which windows were open, so a relaunch can reopen the same ones ──────────
#
# The owner's requirement: "whichever window was open before a close should reopen".
# The engine persists itself; the WINDOWS are the launcher's business, so the launcher owns
# a small registry of the profiles it has opened. `open: true` means "this window is part of
# the working set"; `open: false` means the owner closed it deliberately and it should not
# come back. The registry is why the shortcut can restore rather than guess.
function Get-SlotRegistryKey($slot) {
    # The registry used to be keyed by browser profile. THAT STOPS WORKING THE MOMENT PROFILES ARE
    # SHARED: every slot would write the same key (`_shared`) and the last one to open would be the
    # only window remembered, so a reboot would restore exactly one window. The key is the slot
    # LABEL instead, which windows.json already requires to be unique, and it is stable across a
    # profile-mode change - which is the whole point.
    if ($slot.label) { return [string]$slot.label }
    return [string]$slot.profile
}

function Get-WindowRegistry {
    $path = Join-Path $StateDir 'windows-registry.json'
    $map = @{}
    if (Test-Path $path) {
        try {
            $raw = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
            foreach ($prop in $raw.PSObject.Properties) { $map[$prop.Name] = $prop.Value }
        } catch { Write-Warning "windows-registry.json unreadable; starting a fresh registry" }
    }
    # LEGACY KEY MIGRATION, ONCE. A registry written before shared profiles names slots by their
    # profile (`w1`..`w8`). Folding those into the label key is what stops the owner's working set
    # being forgotten the first time the new model runs: without this, Invoke-Restore finds no
    # remembered window and opens only the first slot.
    $changed = $false
    foreach ($slot in (Get-Slots)) {
        $key = Get-SlotRegistryKey $slot
        if ($map.ContainsKey($key)) { continue }
        $legacy = [string]$slot.profile
        if ($legacy -and $map.ContainsKey($legacy)) {
            $map[$key] = $map[$legacy]
            $map.Remove($legacy)
            $changed = $true
        }
    }
    if ($changed) { Save-WindowRegistry $map; Write-Host '  [registry] migrated profile keys to slot labels' -ForegroundColor DarkGray }
    return $map
}

function Save-WindowRegistry($map) {
    $path = Join-Path $StateDir 'windows-registry.json'
    $json = [pscustomobject]$map | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

# The interval, in seconds, between the two readings that must BOTH come back negative before the
# reconciler marks a remembered window closed. Stated once, here, because "two consecutive negatives"
# means nothing without a number, and the number is written into the row's own evidence.
$WindowPruneConfirmSeconds = 15

# ── `closedBy`: THE FIELD THAT SEPARATES A GUESS FROM A DECISION (2026-09-18) ────────────────────
#
# Before this field, `open: false` meant two incompatible things at once -- "the owner closed this"
# and "the launcher measured it missing at this instant" -- and no reader could tell which, which is
# how the 00:01:59 prune (rows `1 - main` and `2`, closed on ONE empty reading, after which
# Invoke-WindowRecovery's guard 1 short-circuited forever) read exactly like a deliberate decision.
# The vocabulary is fixed and every closure from now on carries it:
#
#   prune     - the launcher's own reconciler. An INFERENCE from two confirmed negative readings, or
#               from a recorded port the slot can no longer have. NOT a decision: read `evidence`
#               and `confirmations` before believing it.
#   reconcile - a person or an agent proved the row dead by a stronger rule and said so in `why`
#               (the 2026-09-18 window-killer reconcile wrote twelve rows this way).
#   owner     - the owner closed it deliberately. NOTHING in this script can infer this; the value
#               is only ever written by an explicit, human-authored edit of the registry.
#   unknown   - written by an older version, which recorded no provenance. Treat as a guess.
#
# AND THE WRITE MERGES RATHER THAN REPLACES. The previous version rebuilt the entry object from
# scratch on every call, so `why`, `reconciledBy` and `wasOpenAt` -- the fields the reconcile and the
# hunt wrote by hand -- were silently destroyed the next time the launcher touched that row.
function Set-WindowRegistryEntry {
    param(
        $map, [string]$key, [bool]$open, [string]$port,
        [string]$ClosedBy = '', [string]$Evidence = '', [int]$Confirmations = 0, [string]$Why = ''
    )
    $now = (Get-Date).ToString('o')
    $prev = $map[$key]
    $entry = [ordered]@{}
    if ($prev) { foreach ($p in $prev.PSObject.Properties) { $entry[$p.Name] = $p.Value } }
    if ($open) {
        $entry['open'] = $true
        $entry['port'] = $port
        $entry['at'] = $now
        # open again: the closure record describes a past state, so it is not carried forward
        foreach ($f in 'closedBy', 'closedAt', 'evidence', 'confirmations', 'rule') {
            if ($entry.Contains($f)) { $entry.Remove($f) }
        }
    } else {
        # keep the timestamp of the state being replaced -- it is the only record of when the window
        # was last known open, and the old code overwrote it on the way out
        if ($prev -and -not $entry.Contains('wasOpenAt')) {
            $wasAt = Get-Prop $prev 'at'
            if ($wasAt) { $entry['wasOpenAt'] = [string]$wasAt }
        }
        $entry['open'] = $false
        $entry['port'] = $port
        $entry['at'] = $now
        $entry['closedAt'] = $now
        $entry['closedBy'] = if ($ClosedBy) { $ClosedBy } else { 'unknown' }
        if ($Evidence) { $entry['evidence'] = $Evidence }
        if ($Confirmations -gt 0) { $entry['confirmations'] = $Confirmations }
        if ($Why) { $entry['why'] = $Why }
    }
    # NOTE: build the object from this dictionary and never by assigning a new property afterwards.
    # A PSCustomObject made this way is not extensible -- `$obj.newField = x` throws "the property
    # cannot be found" -- so every field a row can ever carry has to be decided here. That is why
    # `why` is a parameter and not a line in the caller.
    $map[$key] = [pscustomobject]$entry
}

# ── THE ONE RECONCILER. IT IS CALLED, NOT DECORATION, AND IT NEEDS MORE THAN ONE NEGATIVE ────────
#
# THIS FUNCTION WAS DEAD CODE UNTIL 2026-09-18: nothing called it, while the only reconciliation that
# ever ran was an inline prune inside `Invoke-Restore` that marked a window closed on a SINGLE empty
# reading (WINDOW-KILLER.md §7A/§7B). That inline prune is retired and this function is now the only
# thing in the launcher that ever closes a remembered row: `restore` and `health` both call it, and
# `dshw plan` prints exactly what it would do without doing it.
#
# WHY ONE READING IS NOT ENOUGH. `Get-WindowCount` unions two legs -- the proxy's per-port live
# connection count, and a process scan keyed on `--app=http://127.0.0.1:<port>`. Measured 2026-09-18
# (§6C): in a shared profile only the FIRST window of a browser carries that origin in a live command
# line; every later window is handed off invisibly to the same browser process. So for every origin
# except a profile's first, the proxy leg is load-bearing, and a live window whose page is momentarily
# not connected is invisible to BOTH legs. One empty reading is therefore a whole class of false
# negative, and on 2026-09-18 at 00:01:59 exactly one such reading pruned rows `1 - main` and `2` --
# after which Invoke-WindowRecovery's guard 1 short-circuited forever and the reopen loop ended
# because the REGISTRY had been pruned, not because the windows had stopped dying.
#
# TWO RULES, EACH REQUIRING THE EVIDENCE IT ACTUALLY NEEDS:
#
#   rule=port-mismatch -- NO liveness reading at all. The port recorded in the row is not the origin
#                         this slot has now, so no window this launcher can open will ever match that
#                         row again: Invoke-WindowRecovery's guard 2 can never fire on it, and a
#                         restore would reopen it on an origin it was never opened with. This is the
#                         class the hunt had to close TWELVE rows of BY HAND on 2026-09-18; it needs
#                         no inference, so no false negative is possible. Recorded as closedBy
#                         =reconcile -- a rule, not a guess.
#
#   rule=two-confirmed-negatives -- two readings of the same slot separated by at least $ConfirmSeconds,
#                         the second taken FRESH with every memo dropped (two reads of one cached set
#                         is ONE reading with extra steps, i.e. the 00:01:59 bug wearing a disguise).
#                         Both must be negative AND the origins proxy must have answered at both,
#                         because a negative taken while the proxy is restarting -- measured at
#                         23:11:48 that night -- is single-legged and proves nothing. Recorded as
#                         closedBy=prune: an INFERENCE, and it says so in the row.
#
# Callers may pass -Skip. A key the current run just opened has had no chance to connect yet, and "it
# did not connect in the milliseconds since we launched it" is not evidence that it is not there.
function Sync-WindowRegistry {
    param($state, [switch]$DryRun, [string[]]$Skip = @(), [int]$ConfirmSeconds = 15)
    $map = Get-WindowRegistry
    $slots = Get-Slots
    $legs1 = Get-OriginLiveLegs
    $procTable = Get-WindowProcs

    # A census, so the closedBy vocabulary has a reader: how many closed rows are a decision, how many
    # are this launcher's own inference, and how many predate the field and cannot be attributed.
    $attrib = [pscustomobject]@{ prune = 0; decision = 0; unattributed = 0 }
    foreach ($prop in @($map.Keys)) {
        $e = $map[$prop]
        if ((Get-Prop $e 'open') -ne $false) { continue }
        $by = [string](Get-Prop $e 'closedBy')
        if ($by -eq 'prune') { $attrib.prune++ }
        elseif ($by -or (Get-Prop $e 'why') -or (Get-Prop $e 'reconciledBy')) { $attrib.decision++ }
        else { $attrib.unattributed++ }
    }

    $report = [pscustomobject]@{
        considered = 0; closed = 0; mismatched = 0; spared = 0; unconfirmed = 0
        dryRun = [bool]$DryRun; proxyUp = [bool]$legs1.proxyUp
        intervalSeconds = $ConfirmSeconds; attribution = $attrib; details = @()
    }

    $candidates = @()
    foreach ($slot in $slots) {
        $key = Get-SlotRegistryKey $slot
        $entry = $map[$key]
        if (-not $entry) { continue }
        if ((Get-Prop $entry 'open') -ne $true) { continue }
        $origin = [int](Get-SlotOriginPort $slot)
        $recorded = 0
        try { $recorded = [int](Get-Prop $entry 'port') } catch { $recorded = 0 }

        if ($recorded -ne $origin) {
            $ev = "rule=port-mismatch; recorded={0}; slot-origin={1}; no liveness reading was used" -f $recorded, $origin
            $report.closed++; $report.mismatched++
            $report.details += ("closed: {0} - {1}" -f $key, $ev)
            if (-not $DryRun) {
                Set-WindowRegistryEntry $map $key $false ([string]$origin) -ClosedBy 'reconcile' -Evidence $ev `
                    -Why "recorded port $recorded is not this slot's origin $origin, so no window the launcher can open can ever match this row"
            }
            continue
        }

        if ($Skip -contains $key) { continue }
        if ((Get-WindowCount $slot $procTable) -gt 0) { continue }
        $candidates += [pscustomobject]@{
            key = $key; origin = $origin; slot = $slot
            proxy1 = [bool]($legs1.proxy -contains $origin)
            scan1  = [bool]($legs1.scan  -contains $origin)
        }
    }
    $report.considered = $candidates.Count

    if ($candidates.Count -gt 0) {
        # A NEGATIVE FROM A LEG THAT DID NOT ANSWER IS NOT A NEGATIVE. With origins enabled the proxy
        # leg is load-bearing (see the header), so if the proxy is not answering then nothing here may
        # be closed: the row is left exactly as it is and reported, once, as unconfirmed.
        if ($legs1.originsEnabled -and -not $legs1.proxyUp) {
            $report.unconfirmed = $candidates.Count
            $report.details += @($candidates | ForEach-Object {
                "unconfirmed: {0} origin :{1} - the origins proxy was not answering, so this negative is single-legged and was NOT acted on" -f $_.key, $_.origin })
        } else {
            $t1 = Get-Date
            Start-Sleep -Seconds $ConfirmSeconds
            $legs2 = Get-OriginLiveLegs -Fresh
            $t2 = Get-Date
            $procTable2 = Get-WindowProcs
            $interval = [int][math]::Round(($t2 - $t1).TotalSeconds)
            foreach ($c in $candidates) {
                if (((Get-WindowCount $c.slot $procTable2) -gt 0) -or ($legs2.union -contains $c.origin)) {
                    # IT WAS THERE AFTER ALL. The single reading that would have forgotten it was a
                    # false negative, which is precisely what this rule exists to survive.
                    $report.spared++
                    $report.details += ("spared: {0} origin :{1} - answered the second reading {2}s later" -f $c.key, $c.origin, $interval)
                    continue
                }
                $a1 = if ($c.proxy1) { 'yes' } else { 'no' }
                $a2 = if ($legs2.proxy -contains $c.origin) { 'yes' } else { 'no' }
                $b1 = if ($c.scan1)  { 'yes' } else { 'no' }
                $b2 = if ($legs2.scan  -contains $c.origin) { 'yes' } else { 'no' }
                $ev = ("rule=two-confirmed-negatives; confirmations=2; interval={0}s; r1={1}; r2={2}; " +
                       "legA(proxy)={3}/{4}; legB(procscan)={5}/{6}; proxyAnswered=yes") -f `
                      $interval, $t1.ToString('o'), $t2.ToString('o'), $a1, $a2, $b1, $b2
                $report.closed++
                $report.details += ("closed: {0} origin :{1} - {2}" -f $c.key, $c.origin, $ev)
                if (-not $DryRun) {
                    Set-WindowRegistryEntry $map $c.key $false ([string]$c.origin) -ClosedBy 'prune' -Evidence $ev -Confirmations 2
                }
            }
        }
    }

    if ($report.closed -gt 0 -and -not $DryRun) { Save-WindowRegistry $map }
    return $report
}

# One line for the closedBy census, so the field that separates a guess from a decision is READ
# somewhere instead of merely written. A closure this launcher inferred and a closure a person
# decided look identical in `open: false`, and telling them apart is the whole point of the field.
function Format-RegistryCensus($attrib) {
    if (-not $attrib) { return '' }
    return ("closed rows: {0} inferred by this launcher (closedBy=prune), {1} recorded as a decision, {2} unattributed (written before the field existed)" -f `
        $attrib.prune, $attrib.decision, $attrib.unattributed)
}

function Invoke-Restore {
    param([switch]$DryRun)
    # Reopen every window that was open when DSH was last closed, and nothing else. A window the owner
    # closed on purpose stays closed because the registry marks it `open: false`.
    #
    # -DryRun (added 2026-09-18) REPORTS what this would open and what the reconciler would forget,
    # and writes nothing, opens nothing, and does not start the origins proxy. It exists because the
    # LOGON PATH WAS CHANGED TO RESTORE (WINDOW-KILLER.md 12) and the only way to exercise that
    # decision without rebooting a machine the owner is working on is to ask for the plan. `dshw plan`
    # is the CLI surface for it; a dry-run path nothing can reach would be this file's own disease.
    if (-not $DryRun) { [void](Ensure-OriginsProxy) }
    $state = Get-State
    $slots = Get-Slots
    # NOTE: no reconciliation BEFORE the reopen. A restore runs at startup, when every window is by
    # definition closed, so 'the window is gone' would mark the whole working set closed and the
    # restore would find nothing to do (observed 2026-09-11). The registry is the record of the last
    # working set; only the CONFIRMED reconcile after the reopen narrows it.
    $map = Get-WindowRegistry
    $wanted = @($slots | Where-Object { $k = Get-SlotRegistryKey $_; $map.ContainsKey($k) -and $map[$k].open -eq $true })

    if ($wanted.Count -eq 0) {
        $first = $slots | Where-Object { $_.enabled } | Select-Object -First 1
        if ($DryRun) {
            Write-Host "restore plan: no window is remembered as open, so a restore opens exactly one - the first enabled slot:"
            if ($first) { Write-Host ("  [would open]  {0} (origin :{1})" -f $first.label, (Get-SlotOriginPort $first)) }
            else { Write-Host "  [would open]  nothing - no slot is enabled" }
            $rec = Sync-WindowRegistry $state -DryRun -ConfirmSeconds $WindowPruneConfirmSeconds
            Write-Host ("  [reconcile]   considered {0} recorded-open slot(s): would forget {1}, spare {2}, unconfirmed {3}" -f `
                $rec.considered, $rec.closed, $rec.spared, $rec.unconfirmed)
            Write-Host ("  [registry]    {0}" -f (Format-RegistryCensus $rec.attribution))
            return
        }
        # nothing remembered: this is a first run, so give the owner one window rather than none
        Write-Host "no remembered windows; opening the first slot"
        if ($first) { [void](Open-SlotWindow $first $state); Set-WindowRegistryEntry $map (Get-SlotRegistryKey $first) $true (Get-SlotOriginPort $first); Save-WindowRegistry $map }
        return
    }

    $procTable = Get-WindowProcs
    $opened = 0
    $skip = @()
    $alreadyLive = @()
    foreach ($slot in $wanted) {
        $k = Get-SlotRegistryKey $slot
        if ((Get-WindowCount $slot $procTable) -gt 0) { $alreadyLive += $k; continue }
        if ($DryRun) {
            Write-Host ("  [would open]  {0} (origin :{1})" -f $slot.label, (Get-SlotOriginPort $slot))
            $opened++; $skip += $k
            continue
        }
        try {
            [void](Open-SlotWindow $slot $state)
            $opened++
            $skip += $k
            Write-Host ("  [open]  {0}" -f $slot.label) -ForegroundColor Green
        } catch {
            # A FAILED LAUNCH IS NOT EVIDENCE THAT THE OWNER CLOSED THE WINDOW. Keep the row so the
            # recovery loop retries it: a transient launch fault must not silently forget a window.
            $skip += $k
            Write-Host ("  [WARN] could not reopen '{0}': {1}" -f $slot.label, $_.Exception.Message) -ForegroundColor Yellow
        }
    }

    if ($DryRun) {
        Write-Host ("restore plan: {0} remembered window(s) - would open {1}, {2} already live ({3})" -f `
            $wanted.Count, $opened, $alreadyLive.Count, ($alreadyLive -join ', '))
        $rec = Sync-WindowRegistry $state -DryRun -Skip $skip -ConfirmSeconds $WindowPruneConfirmSeconds
        Write-Host ("  [reconcile]   considered {0} recorded-open slot(s): would forget {1} ({2} of them on a port no window can match any more), spare {3}, unconfirmed {4}" -f `
            $rec.considered, $rec.closed, $rec.mismatched, $rec.spared, $rec.unconfirmed)
        Write-Host ("  [registry]    {0}" -f (Format-RegistryCensus $rec.attribution))
        foreach ($d in @($rec.details)) { Write-Host ("    {0}" -f $d) }
        return
    }

    # KEEP THE SET TIGHT, BUT NEVER ON ONE READING. This used to be an inline prune that marked a row
    # closed whenever a SINGLE liveness measurement came back empty, and at 00:01:59 on 2026-09-18
    # that is exactly what it did: rows `1 - main` and `2` went to open:false on one false negative,
    # Invoke-WindowRecovery's guard 1 then short-circuited forever, and the reopen loop ended because
    # the REGISTRY had been pruned rather than because the windows had stopped dying (7A). The rule
    # now lives in ONE place - Sync-WindowRegistry - which requires two FRESH negatives
    # $WindowPruneConfirmSeconds apart with the proxy answering, and which records which reading
    # closed the row and whether the row's port can even match a window now.
    #
    # AND NOTE WHAT THAT LEAVES FOR `restore`, because it is deliberate and it is not dead code:
    # every slot this run touched is passed as -Skip, and "touched" is every remembered row that was
    # not already live - which is precisely the whole class rule 2 could ever act on. So in `restore`
    # rule 2 has no candidates BY CONSTRUCTION, and the only thing it can close is rule 1, the
    # port-mismatch reconcile, which needs no liveness reading and therefore cannot be a false
    # negative. That division is the point: the confirmed-negative rule belongs to `health`, which
    # runs every five minutes over a machine in steady state and can honestly say "it was there last
    # tick and it is not there now", while `restore` is running three tenths of a second after it
    # launched the very windows a liveness test would be asked about. A window we could not launch is
    # a fault to retry, not a window the owner closed.
    $rec = Sync-WindowRegistry $state -Skip $skip -ConfirmSeconds $WindowPruneConfirmSeconds
    # the reconciler saved its own copy of the registry; re-read it, or the record pass below would
    # write the stale map back over the closures it just made
    $map = Get-WindowRegistry
    if ($rec.closed -gt 0) {
        Write-Host ("restore: forgot {0} window(s) - {1} confirmed gone by two readings {2}s apart, {3} on a port no window can match any more" -f `
            $rec.closed, ($rec.closed - $rec.mismatched), $WindowPruneConfirmSeconds, $rec.mismatched)
    }
    if ($rec.spared -gt 0) { Write-Host ("restore: kept {0} window(s) that answered the second reading - one negative would have forgotten them" -f $rec.spared) }
    if ($rec.unconfirmed -gt 0) { Write-Host ("restore: left {0} row(s) alone - the origins proxy was not answering, so a negative could not be trusted" -f $rec.unconfirmed) -ForegroundColor Yellow }
    Write-Host ("restore: {0} of {1} remembered window(s) reopened" -f $opened, $wanted.Count)

    # Record what is on screen NOW as the working set. Restore is the only moment the set is known to
    # be complete and correct, so it is where the record is written; a window closed afterwards is
    # caught by the next confirmed reconcile. Together those make "reopen what I had" true without
    # ever acting on a single negative reading.
    Start-Sleep -Seconds 3
    $procTable = Get-WindowProcs
    foreach ($slot in $slots) {
        if ((Get-WindowCount $slot $procTable) -gt 0) {
            Set-WindowRegistryEntry $map (Get-SlotRegistryKey $slot) $true (Get-SlotOriginPort $slot)
        }
    }
    Save-WindowRegistry $map
}
# ── the loopback-origin proxy: launcher-owned, because windows now depend on it ──────────────
#
# In shared-profile mode EVERY window opens an alias origin rather than the engine's own port, so
# this proxy is load-bearing: if it is not running, no window can reach the engine at all. It is
# therefore started, adopted and health-checked by the launcher exactly like the engine is, and
# Open-SlotWindow falls back to the engine port (with a warning) if it cannot be reached, so a
# proxy fault degrades to "all windows share one session slot" instead of "no windows".
function Get-OriginsPidFile { return (Join-Path $StateDir 'origins.pid') }
function Get-OriginsLogFile { return (Join-Path $LogDir 'origins.log') }

function Get-OriginsArgs {
    $o = Get-OriginsConfig
    $script = Join-Path $PSScriptRoot $(if ($o -and $o.script) { [string]$o.script } else { 'dshw-proxy.mjs' })
    $base = 3300; $count = 24; $ttl = 15000   # 3300 not 3200 - see windows.json _basePortWhy
    if ($o) {
        if ($o.PSObject.Properties['basePort'] -and $o.basePort) { $base = [int]$o.basePort }
        if ($o.PSObject.Properties['count'] -and $o.count) { $count = [int]$o.count }
        if ($o.PSObject.Properties['ttlMs'] -and $o.ttlMs) { $ttl = [int]$o.ttlMs }
    }
    return [pscustomobject]@{
        script = $script; basePort = $base; count = $count; ttlMs = $ttl
        target = (Get-PrimaryPort); pidFile = (Get-OriginsPidFile); log = (Get-OriginsLogFile)
    }
}

# Ask the proxy itself, over HTTP, rather than trusting a port or a pid file: a bound port proves
# nothing about whether the process behind it is working, which is the same trap `ensure` records
# for the engine. Memoised per command, because Get-WindowCount asks once per slot.
function Test-OriginsProxy([switch]$Quiet, [switch]$Fresh) {
    if (-not (Test-OriginsEnabled)) { return $false }
    if ($Fresh) { $script:OriginsAlive = $null }   # see Start-OriginsProxy: the wait loop must not read a memo
    if ($null -ne $script:OriginsAlive) { return [bool]$script:OriginsAlive }
    $a = Get-OriginsArgs
    $alive = $false
    try {
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromSeconds(4)
        $resp = $client.GetAsync("http://127.0.0.1:$($a.basePort)/__dshw/stats").GetAwaiter().GetResult()
        $alive = [int]$resp.StatusCode -eq 200
        $resp.Dispose(); $client.Dispose()
    } catch {
        if (-not $Quiet) { Write-Host ("  [origins] proxy not answering on :{0} - {1}" -f $a.basePort, $_.Exception.Message) -ForegroundColor DarkGray }
    }
    $script:OriginsAlive = $alive
    return $alive
}

# THE PER-SLOT LIVENESS SIGNAL, and the only one that works in shared-profile mode.
#
# Measured 2026-09-18: in a shared profile only the FIRST window's URL appears in any process
# command line. The browser root carried `--app=http://127.0.0.1:3200/`, and the second window -
# opened into the same profile and therefore handed to the same browser process - existed only as
# an anonymous `--type=renderer` child with no URL. A process scan can therefore find exactly ONE
# window per profile, so in shared mode it finds one window in total and reports every other slot as
# empty: `new` re-opens the same slot forever and `restore` duplicates every window.
#
# What IS per-window is the alias ORIGIN. A live window keeps streaming connections open on its own
# port (`$events` / `session/follow`), and the proxy counts live connections per port. Verified: the
# two windows opened during this measurement each held 2 established connections on 3200 and 3201.
# ── LIVENESS, WHICH MUST WORK ON *ANY* ORIGIN THE LAUNCHER USES ──────────────────────────────
#
# The one question every window-opening path asks is "does this slot already have a live window?".
# Getting a FALSE NEGATIVE there reopens a window the owner already has - measured 2026-09-18 in
# `~/.dsh/multi-window/windows.log`: slots 1 and 2 opened at 23:13:29/23:13:52 and again at
# 23:21:28/23:21:59, and 229 open events had accumulated. So the answer has to be right in every
# shape this launcher can produce a window in, and there are THREE of them:
#
#   A. a window on a proxy ORIGIN (127.0.0.1:3200..3223) - the current model. Only its port is
#      per-window; in a shared profile the browser root's command line carries the FIRST window's
#      URL and every later window is an anonymous `--type=renderer` child with no URL at all, so a
#      process scan cannot see it. The proxy counts live connections per port and is exact.
#   B. a window opened DIRECTLY against the engine port (127.0.0.1:3099) - `per-window` mode, or
#      the documented fallback when the proxy is not answering (Open-SlotWindow warns and falls
#      back). Several such windows keep SEPARATE browser trees, one per profile directory, so the
#      `--app=http://127.0.0.1:3099/` command line identifies them.
#   C. a window opened on an origin whose proxy has since died. The proxy cannot answer, so the
#      process scan is the only evidence left - and it must look for THIS slot's origin port, not
#      for the engine port, or the window is invisible for exactly as long as the proxy is down.
#
# All three are unioned below. A slot is live if ANY of them says so, and `live` is the union of
# every slot's origin port plus the engine port, so one answer serves all sixteen slots.
function Get-WindowOriginPorts($table = $null) {
    if ($null -ne $script:OriginLiveMap) { return $script:OriginLiveMap }
    $map = @{}
    $procs = Get-WindowProcs $table
    foreach ($p in @($procs)) {
        if (-not $p.CommandLine) { continue }
        # Only a window, never a child: `--type=renderer` etc. inherit their parent's command line
        # and would otherwise be counted as windows of their own.
        if ($p.CommandLine.Contains('--type=')) { continue }
        if (-not $p.CommandLine.Contains('--app=')) { continue }
        $u = ''
        $m = [regex]::Match($p.CommandLine, '--app=http://127\.0\.0\.1:(\d{1,5})')
        if ($m.Success) { $u = $m.Groups[1].Value }
        else {
            $m2 = [regex]::Match($p.CommandLine, '--app="([^"]+)"')
            if ($m2.Success) {
                $mf = [regex]::Match($m2.Groups[1].Value, '127\.0\.0\.1:(\d{1,5})')
                if ($mf.Success) { $u = $mf.Groups[1].Value }
            }
        }
        if (-not $u) { continue }
        if ($map.ContainsKey($u)) { $map[$u] = $map[$u] + 1 } else { $map[$u] = 1 }
    }
    $script:OriginLiveMap = $map
    return $map
}

function Get-EnginePortWindowCount($table = $null) {
    $map = Get-WindowOriginPorts $table
    $p = [string](Get-PrimaryPort)
    return $(if ($map.ContainsKey($p)) { [int]$map[$p] } else { 0 })
}

# ── THE LEGS, KEPT SEPARATE, BECAUSE THE RECONCILER HAS TO KNOW WHICH ONE ANSWERED ────────────────
#
# Get-OpenOriginPorts answers "is this origin live?", and that is all most callers need. The reconciler
# needs one thing more: WHICH legs produced the negative, and whether the proxy leg was reachable at
# all. Measured 2026-09-18 (§6C): only the FIRST window of a shared-profile browser carries
# `--app=<origin>` in a live command line, so for every other origin the proxy's per-port connection
# count is load-bearing -- and a negative taken while the proxy is restarting (measured 23:11:48 that
# night) is single-legged, i.e. it proves nothing at all.
function Get-OriginLiveLegs {
    param([switch]$Fresh)
    if ($Fresh) {
        # DROP EVERY MEMO. Two reads of one cached set is ONE reading with extra steps, and a
        # "two consecutive negatives" rule built on the cache would have re-created the 00:01:59 bug
        # while looking exactly like a safeguard.
        $script:OriginsAlive = $null
        $script:OriginLiveMap = $null
        $script:OpenOriginCache = $null
        $script:OriginLiveLegsCache = $null
    }
    if ($null -ne $script:OriginLiveLegsCache) { return $script:OriginLiveLegsCache }

    $originsEnabled = [bool](Test-OriginsEnabled)
    $proxyUp = $false
    $proxyPorts = @()
    if ($originsEnabled -and (Test-OriginsProxy -Quiet)) {
        $proxyUp = $true
        $a = Get-OriginsArgs
        # A - ask the proxy. It answers with its own requesting connection excluded, so the probe
        # cannot report itself as a window (measured previously: `openPorts:[3200]` with every window
        # closed).
        $client = $null
        try {
            $client = [System.Net.Http.HttpClient]::new()
            $client.Timeout = [TimeSpan]::FromSeconds(4)
            $txt = $client.GetStringAsync("http://127.0.0.1:$($a.basePort)/__dshw/open").GetAwaiter().GetResult()
            $proxyPorts = @(@(($txt | ConvertFrom-Json).ports) | ForEach-Object { [int]$_ })
        } catch { } finally { if ($client) { $client.Dispose() } }

        # THE FIRST SAMPLE CAN MISS A WINDOW THAT IS STILL CONNECTING. A window is only visible through
        # A once its page has loaded and opened a streaming connection on its origin, which is one to
        # several seconds after the launch - and `new`/`restore` ask this question immediately after
        # the previous open returned. Two more samples 600 ms apart close that window instead of
        # widening the answer with an invented grace period. Only paid when the first sample is empty,
        # so the settled case stays at one HTTP call.
        if (@($proxyPorts).Count -eq 0) {
            foreach ($n in 1..2) {
                Start-Sleep -Milliseconds 600
                if (-not (Test-OriginsProxy -Quiet -Fresh)) { $proxyUp = $false; break }
                $c2 = $null
                try {
                    $c2 = [System.Net.Http.HttpClient]::new()
                    $c2.Timeout = [TimeSpan]::FromSeconds(4)
                    $t2 = $c2.GetStringAsync("http://127.0.0.1:$($a.basePort)/__dshw/open").GetAwaiter().GetResult()
                    $ports2 = @(@(($t2 | ConvertFrom-Json).ports) | ForEach-Object { [int]$_ })
                    if ($ports2.Count -gt 0) { $proxyPorts = @($proxyPorts + $ports2); break }
                } catch { } finally { if ($c2) { $c2.Dispose() } }
            }
        }
    }

    # B and C - the process scan. This is also what makes the answer independent of the proxy's
    # liveness: a window the proxy would have reported is still found here by its own origin port.
    $scanPorts = @(@(Get-WindowOriginPorts).Keys | ForEach-Object { [int]$_ })
    $union = @(@($proxyPorts) + @($scanPorts) | Sort-Object -Unique)
    $script:OpenOriginCache = @($union)
    $script:OriginLiveLegsCache = [pscustomobject]@{
        union          = @($union)
        proxy          = @($proxyPorts | Sort-Object -Unique)
        scan           = @($scanPorts)
        proxyUp        = [bool]$proxyUp
        originsEnabled = $originsEnabled
    }
    return $script:OriginLiveLegsCache
}

function Get-OpenOriginPorts {
    # The union of both legs. See Get-OriginLiveLegs for the legs themselves and for why the reconciler
    # insists on knowing which of them actually answered.
    if ($null -ne $script:OpenOriginCache) { return $script:OpenOriginCache }
    return @((Get-OriginLiveLegs).union)
}

function Get-OriginsStats {
    if (-not (Test-OriginsEnabled)) { return $null }
    $a = Get-OriginsArgs
    try {
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromSeconds(4)
        $txt = $client.GetStringAsync("http://127.0.0.1:$($a.basePort)/__dshw/stats").GetAwaiter().GetResult()
        $client.Dispose()
        return ($txt | ConvertFrom-Json)
    } catch { return $null }
}

# The proxy's node argument list, in ONE place: the Task Scheduler action, the hidden wscript
# wrapper and the direct fallback must all describe exactly the same proxy or `ensure` starts a
# proxy the launcher cannot find.
function Get-OriginsNodeArgument($a) {
    return '"{0}" --base {1} --count {2} --target {3} --ttl {4} --pidfile "{5}" --log "{6}"' -f `
        $a.script, $a.basePort, $a.count, $a.target, $a.ttlMs, $a.pidFile, $a.log
}

function Write-OriginsProxyUp($a, $how = '') {
    $suffix = if ($how) { " ($how)" } else { '' }
    Write-Host ("  [origins] proxy up on :{0}..:{1} -> engine :{2}{3}" -f `
        $a.basePort, ($a.basePort + $a.count - 1), $a.target, $suffix) -ForegroundColor Green
}

# Poll until the proxy answers or the budget runs out. -Fresh is load-bearing: Test-OriginsProxy
# memoises its answer for the whole command, so without it this loop reads its own first "no" back.
function Wait-OriginsProxy([int]$TimeoutSeconds = 25) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 400
        if (Test-OriginsProxy -Quiet -Fresh) { return $true }
    }
    return [bool](Test-OriginsProxy -Quiet -Fresh)
}

# Does this registered task already point at the hidden wrapper we would register? If it does, it can
# be STARTED without writing to Task Scheduler at all - which is what makes a restart safe on a
# machine where Register-ScheduledTask is denied without elevation (D230, measured on ZABZ-YOGA).
function Test-OriginsTaskUsesWrapper($task, $vbs) {
    if (-not $task -or -not $task.Actions -or $task.Actions.Count -lt 1) { return $false }
    $act = $task.Actions[0]
    if (-not $act.Execute) { return $false }
    if ((Split-Path -Leaf $act.Execute) -ne 'wscript.exe') { return $false }
    return [bool]($act.Arguments -and $act.Arguments.Contains($vbs))
}

# The escape hatch: detached, hidden and OUTSIDE this process's job object, via WMI - the same
# mechanism Start-EngineDetached falls back to after Task Scheduler produced nothing. It needs no
# Task Scheduler permission and no elevation, and a duplicate is harmless: the proxy refuses to bind
# when the base port already answers and its own lock file is held by a live pid.
function Start-OriginsProxyDirect($a) {
    $node = Resolve-NodeExe
    $vbs = New-HiddenLauncherVbs -Execute $node -Argument (Get-OriginsNodeArgument $a) `
        -WorkingDirectory $PSScriptRoot -TaskName 'DSH Origins Proxy'
    $wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
    $res = ([wmiclass]'Win32_Process').Create("`"$wscript`" //B //NoLogo `"$vbs`"", $PSScriptRoot, $null)
    if ($res.ReturnValue -ne 0) { throw "WMI Win32_Process.Create returned $($res.ReturnValue) starting '$wscript'" }
    return [int]$res.ProcessId
}

# WHY TASK SCHEDULER IS PREFERRED, AND WHY THE TASK IS THEN LEFT REGISTERED. Both were written in the
# trunk's version of this function and are kept here, because they are the reasons the three paths
# below are ordered the way they are:
#   - Task Scheduler, for the same reason the engine is launched that way: a child started directly by
#     this script dies with the job object that owns it, and the proxy has to outlive the shell that
#     started it and the session that ran it.
#   - LEFT REGISTERED, because it is a real race rather than a tidy-up. `ensure` runs every minute as a
#     scheduled task, so a manual `dshw ensure` and the watchdog can call this at the same moment.
#     Measured 2026-09-18: that produced TWO proxy instances which SPLIT THE PORT RANGE between them
#     (3200-3215 and 3216-3223) -- healthy from any single port, broken as a whole.
#     `-MultipleInstances IgnoreNew` only has anything to ignore while the task still EXISTS, so PATH 1
#     STARTS the registered task instead of re-registering it, and nothing here ever unregisters it.
#
# Launch the proxy. Three independent paths, tried in order, because it is the door every window uses
# and it MUST come back. `$env:DSHW_ORIGINS_NO_SCHEDULER=1` skips Task Scheduler entirely, which is
# how the direct path is exercised in a test.
function Start-OriginsProxy {
    $a = Get-OriginsArgs
    if (-not (Test-Path $a.script)) { throw "origins script not found: $($a.script)" }
    $taskName = 'DSH Origins Proxy'
    $node = Resolve-NodeExe
    $nodeArg = Get-OriginsNodeArgument $a
    $problems = New-Object System.Collections.Generic.List[string]
    $useScheduler = ($env:DSHW_ORIGINS_NO_SCHEDULER -ne '1')

    # The wrapper is (re)written every time and is what both scheduler paths expect to find. It is
    # regenerated rather than trusted so a stale file (e.g. an old script path) cannot be started.
    $vbs = New-HiddenLauncherVbs -Execute $node -Argument $nodeArg -WorkingDirectory $PSScriptRoot -TaskName $taskName

    # PATH 1 - an already-registered task that points at the current wrapper is STARTED, not
    # re-registered. THIS IS THE FIX for the 2026-09-20 outage: `ensure` called
    # Register-ScheduledTask -Force unconditionally first, and on a machine where registering
    # without elevation is denied (D230) that threw "Access is denied" BEFORE it ever tried to start
    # the proxy that was already registered and working - leaving every window's origin ports dead.
    # Starting an existing task needs no write access to its definition.
    $existing = if ($useScheduler) { Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue } else { $null }
    if ($existing -and (Test-OriginsTaskUsesWrapper $existing $vbs)) {
        try {
            if ("$($existing.State)" -eq 'Running') {
                # A killed proxy can leave the task instance looking Running while wscript still
                # waits. Clear it, or -MultipleInstances IgnoreNew swallows the Start below.
                try { Stop-ScheduledTask -TaskName $taskName } catch { }
                Start-Sleep -Milliseconds 300
            }
            Start-ScheduledTask -TaskName $taskName
            if (Wait-OriginsProxy 15) { Write-OriginsProxyUp $a 'registered task'; return }
            $problems.Add('the registered task started but the proxy never answered')
        } catch { $problems.Add("Start-ScheduledTask: $($_.Exception.Message)") }
    } elseif ($existing) {
        $problems.Add('the registered task does not point at the current hidden wrapper')
    }

    # PATH 2 - register the hidden task, then start it. Needed on a first run (no task yet) or when
    # the registration drifted. On a machine that denies registration this is where the old code
    # died; the catch now feeds the direct fallback instead of the console.
    if ($useScheduler) {
        try {
            $action = New-HiddenTaskAction -Execute $node -Argument $nodeArg -WorkingDirectory $PSScriptRoot -TaskName $taskName
            $principal = New-InteractivePrincipal -Highest:(Test-IsElevated)
            $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
            Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
            Start-ScheduledTask -TaskName $taskName
            if (Wait-OriginsProxy 15) { Write-OriginsProxyUp $a 'registered task'; return }
            $problems.Add('the task was registered and started but the proxy never answered')
        } catch { $problems.Add("task-scheduler launch: $($_.Exception.Message)") }
    }

    # PATH 3 - no Task Scheduler at all. Detached via WMI, hidden via the same wscript wrapper.
    try {
        $directPid = Start-OriginsProxyDirect $a
        if (Wait-OriginsProxy 25) { Write-OriginsProxyUp $a "direct, pid $directPid"; return }
        $problems.Add("the direct launch (pid $directPid) ran but the proxy never answered")
    } catch { $problems.Add("direct launch: $($_.Exception.Message)") }

    $tail = if (Test-Path $a.log) { (Get-Content -LiteralPath $a.log -Tail 6) -join ' | ' } else { '(no log)' }
    throw ("origins proxy could not be started on :{0}. attempts: {1} :: {2}" -f $a.basePort, ($problems -join '; '), $tail)
}

function Ensure-OriginsProxy {
    if (-not (Test-OriginsEnabled)) { return $true }
    if (Test-OriginsProxy -Quiet -Fresh) { return $true }
    Write-Host '  [origins] proxy is not answering - starting it' -ForegroundColor Yellow
    try { Start-OriginsProxy; return $true }
    catch {
        # RECORD THE REAL ERROR OBJECT, not just its message. The 2026-09-20 outage printed only
        # "Access is denied", which was not enough to place the fault; the type, HResult, category
        # and script stack go to a file so the next occurrence is diagnosable without a repro.
        $e = $_.Exception
        $detail = @(
            ("[{0}] Ensure-OriginsProxy failed" -f (Get-Date -Format o)),
            ("  type    : {0}" -f $e.GetType().FullName),
            ("  message : {0}" -f $e.Message),
            ("  hresult : 0x{0:X8}" -f $e.HResult),
            ("  category: {0}  target: {1}" -f $_.CategoryInfo.Category, $_.CategoryInfo.TargetName),
            ("  errorId : {0}" -f $_.FullyQualifiedErrorId),
            ("  stack   : {0}" -f $_.ScriptStackTrace)
        )
        if ($e.InnerException) { $detail += ("  inner   : {0}: {1}" -f $e.InnerException.GetType().FullName, $e.InnerException.Message) }
        try { $detail | Add-Content -LiteralPath (Join-Path $StateDir 'origins-start-errors.log') -Encoding utf8 } catch { }
        Write-Host ("  [origins] could not start the proxy: {0}" -f $e.Message) -ForegroundColor Red
        Write-Host ("  [origins] full error object recorded in {0}" -f (Join-Path $StateDir 'origins-start-errors.log')) -ForegroundColor DarkGray
        return $false
    }
}

# Warm the session/list cache, so a window the owner opens renders its session list immediately
# instead of showing an empty list for the 25-31 s the engine needs to walk 681 session
# directories. Called from `ensure`, which already runs once a minute, so the cache is essentially
# always warm and even the first window after a boot is fast.
function Invoke-OriginsPrewarm {
    if (-not (Test-OriginsEnabled)) { return $null }
    $a = Get-OriginsArgs
    try {
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromSeconds(120)
        $txt = $client.GetStringAsync("http://127.0.0.1:$($a.basePort)/__dshw/prewarm").GetAwaiter().GetResult()
        $client.Dispose()
        return ($txt | ConvertFrom-Json)
    } catch { return $null }
}

# ── the fast loop: one bounded check, restart only after two failures ────────
function Invoke-Ensure {
    $port = Get-PrimaryPort
    # REPORT §7.2, FIRST, BEFORE ANYTHING ELSE: this is the function the desktop shortcut runs, and
    # the engine it may start must not depend on `DSH_HOME` having been inherited down Explorer ->
    # cmd -> elevated pwsh -> node. That chain was never proved for the elevated path, and on
    # 2026-09-17 the engine could not boot without the variable. Setting it here means the engine
    # this run starts is told where its home is, whatever the environment it was launched from.
    # Silent when DSH_HOME is already set, so an ordinary boot is not noisier for this.
    [void](Initialize-DshHome (Join-Path $StateDir 'engine-recovery.log'))
    # THE ORIGIN PROXY, BEFORE THE ENGINE, because in shared-profile mode it is the door every
    # window uses. It is also the only thing that keeps the session/list cache warm: this function
    # already runs once a minute as a scheduled task, so a prewarm here is free and means the owner
    # essentially never waits for the 681-directory walk. Both calls are silent when healthy.
    if (Test-OriginsEnabled) {
        if (-not (Ensure-OriginsProxy)) {
            # REFUSE, do not continue as if healthy. In shared-profile mode every window's URL is an
            # origin port, so an `ensure` that reports success while 3200-3223 are dead is a lie that
            # leaves the owner with a dead GUI (measured 2026-09-20). Start-OriginsProxy now has three
            # independent launch paths; reaching here means all three failed. Exit non-zero and say so.
            $oa = Get-OriginsArgs
            $why = ("origins proxy is not answering on :{0} and could not be started - REFUSING: every open window uses ports {0}..{1}. See {2}" -f `
                $oa.basePort, ($oa.basePort + $oa.count - 1), (Join-Path $StateDir 'origins-start-errors.log'))
            Write-Host ("  [origins] {0}" -f $why) -ForegroundColor Red
            try { ("[{0}] ensure: {1}" -f (Get-Date -Format o), $why) | Add-Content -LiteralPath (Join-Path $StateDir 'watchdog.log') -Encoding utf8 } catch { }
            exit 3
        }
        # ── PREWARM IS GATED ON CACHE AGE (2026-10-05, ZABZ-YOGA) ───────────────────────────────
        # It used to run unconditionally, on the reasoning above that `ensure` runs once a minute and
        # therefore "the cache is essentially always warm". That reasoning expired with the session
        # store. MEASURED 2026-10-05: 1059 session directories. The raw disk work for ONE walk - read
        # the first 64 KB of every session's newest generation file, decompress it, and stat it - is
        # 6797 ms in plain Node with no engine involved (tools/replicate-list-scan.mjs: 1059 dirs,
        # 62.8 MB read, 2582 ms + 4161 ms). The ENGINE took 219223 ms for the same walk
        # (multi-window/logs/origins.log, 01:44:27Z), ~32x the disk cost, because its single event
        # loop is shared with the owner's live generations; probed directly, POST /api/session/list
        # did not answer within 300 s while every other RPC answered in 14-330 ms. So an
        # unconditional prewarm every 60 s keeps a multi-minute engine-wide walk running
        # *permanently* - it is now a cause of the sluggishness it was written to prevent.
        # The proxy serves this list stale-while-revalidate (dshw-proxy.mjs), so a window never waits
        # for the refresh anyway; only a cold or old cache is worth the walk. Unreachable stats means
        # prewarm as before. Restore the 60 s cadence once the walk is cheap again - i.e. once the
        # local session store is pruned or the engine's list path is indexed.
        $cacheAgeMs = $null
        try {
            $oaPrewarm = Get-OriginsArgs
            $probe = [System.Net.Http.HttpClient]::new()
            $probe.Timeout = [TimeSpan]::FromSeconds(5)
            $statsJson = $probe.GetStringAsync("http://127.0.0.1:$($oaPrewarm.basePort)/__dshw/stats").GetAwaiter().GetResult()
            $probe.Dispose()
            $cacheAgeMs = ($statsJson | ConvertFrom-Json).ageMs
        } catch { $cacheAgeMs = $null }
        if ($null -eq $cacheAgeMs -or $cacheAgeMs -gt 1200000) {
            $warm = Invoke-OriginsPrewarm
            if ($warm -and -not $warm.ok) {
                "[{0}] ensure: origins prewarm did not fill the cache: {1}" -f (Get-Date -Format o), $warm.reason |
                    Add-Content -LiteralPath (Join-Path $StateDir 'watchdog.log') -Encoding utf8
            }
        }
    }
    # THE PHONE GATE FIRST, AND INDEPENDENTLY OF ENGINE HEALTH.
    #
    # The gate is what makes this node reachable from the owner's phone over the tailnet: the
    # engine's /api fence accepts only a loopback Host, so the gate presents the rewritten
    # authority and is the single door (`scripts/phone-gate-ensure.ps1` has the measurements).
    # It is checked BEFORE the engine because the two failures are independent — a gate that is
    # down makes the published URL answer 502 while the engine is perfectly healthy, which looks
    # exactly like "the other machine is offline" from a phone.
    #
    # This is also the only durability hook available on a machine where registering a scheduled
    # task needs elevation (measured 2026-09-16: BUILTIN\Administrators is "deny only", a
    # UAC-filtered token). This watchdog already runs every minute as the user, so hanging the
    # gate on it needs no new task and no admin.
    $gateEnsure = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\phone-gate-ensure.ps1'
    if (Test-Path $gateEnsure) {
        try {
            # -Publish is cheap when Serve is already correct: the script asks `serve status`
            # before asserting anything. Without it, a daemon restart would leave the gate
            # listening and the tailnet name dead, which is the failure that has no symptom here.
            & $gateEnsure -EnginePort $port -Publish -ListenPort 3086 *> $null
        } catch {
            Write-Host ("ensure: phone gate check failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
        }
    }
    $flag = Join-Path $StateDir "watchdog-failures-$port.txt"
    $log = Join-Path $StateDir 'watchdog.log'
    if (Test-EngineAlive $port) {
        Write-Host ("ensure: engine is answering on {0}" -f $port)
        return
    }
    # RECOVER THROUGH Ensure-Engine, NOT THROUGH A SECOND COPY OF THE START LOGIC.
    #
    # This function used to start an engine itself and nothing else, which made the 1-minute
    # watchdog the one caller that could NOT recover a wedged engine: the port was still bound,
    # so every attempt died with "port 3099 already in use" and the log filled with failures
    # while the engine stayed silent (16:45-18:22 on 2026-09-14, ~20 lines). Meanwhile the only
    # path that COULD take the port -- Ensure-Engine, called by `new` and `restore` -- was wired
    # to a window-opening command and killed a live engine on a false negative at 18:27.
    #
    # So there is now one recovery path, and it is the one that knows the difference between a
    # loaded engine and a dead one (Test-EngineWedged: two patient probes, five seconds apart).
    # The 1-minute watchdog is therefore allowed to reclaim a genuinely wedged engine -- and only
    # that.
    #
    # Reaching here means the fast probe failed, which on this machine is often just load.
    Write-Host ("ensure: engine on {0} is not answering the fast probe - checking patiently" -f $port) -ForegroundColor Yellow
    "[{0}] ensure: engine on {1} not answering the fast probe" -f (Get-Date -Format o), $port |
        Add-Content -LiteralPath $log -Encoding utf8
    if (Ensure-Engine) {
        Remove-Item $flag -Force -ErrorAction SilentlyContinue
        return
    }
    Write-Host ("ensure: could not recover an engine on {0}" -f $port) -ForegroundColor Red
    "[{0}] ensure: could not recover an engine on {1}" -f (Get-Date -Format o), $port |
        Add-Content -LiteralPath $log -Encoding utf8
}
# ── make sure an engine exists, and retry rather than give up ────────────────
#
# The owner hit ERR_CONNECTION_REFUSED from the new-window control because the engine was
# down at that instant and nothing retried: a launcher that starts a window against a dead
# port is worse than one that refuses. This is the single place that answers "is there an
# engine, and if not, start one", with a bounded retry, so every caller gets the same
# behaviour instead of each inventing its own.
function Test-EngineAlive([int]$port, [int]$ConnectMs = 6000, [int]$ReadMs = 12000) {
    # AN HTTP ANSWER, NOT A BARE TCP CONNECT.
    #
    # This used to be `TcpClient.ConnectAsync` and nothing more. On DESKTOP-FGV6KMH that probe
    # returns **True for a port with no listener at all** when run inside another process's tree
    # (measured 2026-09-14: `Test-EngineAlive 3099` -> True while `Get-NetTCPConnection` showed no
    # listener, reproducibly, in the context the launcher runs in; the same call in a fresh shell
    # returned False). A bound-but-inherited socket is indistinguishable from a live server to a
    # connect-only check.
    #
    # The consequence was total and silent: `ensure` concluded the engine was up, never started
    # one, and the desktop shortcut then opened a window against a dead port -- so double-clicking
    # the icon raised UAC, flashed a console, and produced no window, with nothing logged. A probe
    # that can report health for something that is not there is worse than no probe, which is the
    # same failure class as the stale-database incident this repo keeps citing.
    #
    # So the engine must actually answer HTTP. Any status is acceptance; connection refused,
    # a timeout, or a reset is a dead engine.
    #
    # THE BUDGET WAS TOO SHORT FOR THIS MACHINE (2026-09-14 18:27). It was 1500 ms to connect
    # and 2500 ms to return the first byte, and that is not enough for a HEALTHY engine here:
    # ten open windows (~97 Edge processes), a Next dev server on 3000, the personal-secretary
    # stack on 8002 and ~1.4 GB of stdio MCP bridges put this box at 84% CPU, and a loopback
    # GET of the UI shell behind a busy Node event loop routinely takes longer than 2.5 s. A
    # false "not answering" is not a cosmetic log line -- `Ensure-Engine` KILLS the port holder
    # on the strength of it. So the budget is now 6 s / 12 s by default, and callers that are
    # about to TAKE SOMETHING AWAY (reclaim a port, kill a process) must ask for a patient
    # probe and require two of them; see Test-EngineWedged.
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.ConnectAsync('127.0.0.1', $port)
        if (-not $connect.Wait($ConnectMs) -or -not $client.Connected) { return $false }
        $stream = $client.GetStream()
        $stream.ReadTimeout = $ReadMs
        $stream.WriteTimeout = $ConnectMs
        $req = "GET / HTTP/1.1`r`nHost: 127.0.0.1:$port`r`nConnection: close`r`n`r`n"
        $bytes = [Text.Encoding]::ASCII.GetBytes($req)
        $stream.Write($bytes, 0, $bytes.Length)
        $buffer = New-Object byte[] 64
        $read = $stream.Read($buffer, 0, $buffer.Length)
        if ($read -le 0) { return $false }
        $head = [Text.Encoding]::ASCII.GetString($buffer, 0, $read)
        return ($head -match '^HTTP/\d\.\d')
    } catch {
        return $false
    } finally {
        try { $client.Dispose() } catch { }
    }
}

function Test-EngineWedged([int]$port) {
    # A SLOW ANSWER IS NOT A DEAD ENGINE. This is the fix for the 2026-09-14 18:27 incident, and
    # it exists because the recovery path was wired to the wrong command.
    #
    # What happened: `Ensure-Engine` reclaimed (KILLED) a bound-but-silent port after ONE probe
    # on a 1.5 s / 2.5 s budget. `Ensure-Engine` is called by `dshw new` and `dshw restore` --
    # commands whose entire job is to OPEN A WINDOW. So clicking "new window" on a loaded machine
    # diagnosed a healthy engine as dead, killed the process the owner was typing into, and every
    # open window on the machine froze. Evidence: engine-recovery.log 18:27:31 "port 3099 bound
    # but not answering - reclaiming from pid 19556"; windows.log shows slot 5/10 opened at
    # 18:28:43, 18:29:01, 18:31:14 and 18:32:51 with a `dshw.ps1 new` process in the same window;
    # the engine that replaced it took 71 s to answer. The comments in this file already record
    # the same wound twice (pid 32044 at 15:05 the same day, and 2026-09-13).
    #
    # The rule from here: only a port that is silent to TWO PATIENT probes, five seconds apart,
    # is wedged. A busy engine that answers either probe is never touched, and no window-opening
    # command may reclaim a bound port at all.
    for ($i = 1; $i -le 2; $i++) {
        if (Test-EngineAlive $port -ConnectMs 10000 -ReadMs 30000) { return $false }
        if ($i -lt 2) { Start-Sleep -Seconds 5 }
    }
    return $true
}
# ── crash on boot: an engine that started and died is not a dead port ────────
#
# REPORT §7.3 OF THE 2026-09-17 INCIDENT. `ensure` knew exactly one thing: the port is not
# answering. So on 2026-09-17 between 21:32 and 21:39 it retried three times, spawning an engine
# that booted, threw, and exited 1 each time, while the diagnosis — an exit code and a stack trace
# naming MODULE_NOT_FOUND — sat in engine-recovery.log that nobody had been told to read. The
# owner lost ten minutes to a question the launcher could have answered in one line.
#
# WHY NOT SIMPLY THE LAST LINES OF STDERR. Measured against the incident's own stderr
# (docs/incidents/2026-09-17-dsh-engine-boot-failure/engine-boot-failure-stderr.log, 63 lines):
# the last six lines are `      }`, `    }`, `  }`, `}`, ``, `Node.js v24.12.0` — a tail that
# diagnoses nothing. The fault is at the HEAD: line 5 names the plugin tree and the missing
# module, line 8 names it again plainly, line 19 is the frame in OUR code that threw
# (lib/guard.js:22), and line 56 carries the code. This picks DIAGNOSTIC lines wherever they are,
# and falls back to a genuine tail when none match so nothing is lost for an unfamiliar failure.
function Get-EngineCrashLines([string]$errPath, [int]$maxLines = 5) {
    if (-not $errPath -or -not (Test-Path $errPath)) { return @() }
    $text = Read-NewLog $errPath 0
    if (-not $text) { return @() }
    $lines = @($text -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_.Length -gt 0 })
    if ($lines.Count -eq 0) { return @() }
    $wanted = New-Object System.Collections.ArrayList
    $take = {
        param([string]$pattern)
        foreach ($line in $lines) {
            if ($line -match $pattern) {
                if ($wanted.Contains($line)) { continue }
                [void]$wanted.Add($line)
                return
            }
        }
    }
    & $take '^\[?cause\]?:?\s*Error:|^Error:'
    & $take 'Cannot find module|MODULE_NOT_FOUND|EADDRINUSE|EACCES|ENOENT|EADDRNOTAVAIL|ENOTDIR'
    & $take 'harness-config'
    # `code:` first, then the rest: Node prints `errno:` BEFORE `code:`, and `code: 'ENOTDIR'` is
    # the one a person reads. Two passes so line order does not decide which token survives.
    & $take 'code:'
    & $take 'errno:|syscall:|requireStack:'
    if ($wanted.Count -eq 0) { return @($lines | Select-Object -Last $maxLines) }
    return @($wanted | Select-Object -First $maxLines)
}

# The first line of a multi-line exception message, so a log line stays one line.
function Get-ErrorHeadline([string]$message) {
    $first = ($message -split "`r?`n")[0]
    if ($first.Length -gt 300) { return $first.Substring(0, 300) + ' ...' }
    return $first
}

# The exit code out of "server on port 3099 exited with code 1. stderr tail:...".
function Get-EngineExitCode([string]$message) {
    if ($message -match 'exited with code (-?\d+)') { return [int]$Matches[1] }
    return $null
}

# Say it out loud, on the console AND in the log, bounded, at the moment it happens.
function Write-EngineCrashReport([int]$Port, [string]$ErrPath, [string]$Reason, [string]$LogPath = '') {
    $lines = @(Get-EngineCrashLines $ErrPath 5)
    Write-Host ("ensure: the engine on {0} STARTED AND DIED during boot - {1}" -f $Port, $Reason) -ForegroundColor Red
    Write-Host ("ensure:   this is a CRASH ON BOOT, not a dead port: retrying produces the same exit") -ForegroundColor Red
    foreach ($line in $lines) { Write-Host ("ensure:   {0}" -f $line) -ForegroundColor Red }
    if ($ErrPath) { Write-Host ("ensure:   full stderr: {0}" -f $ErrPath) -ForegroundColor Red }
    if ($LogPath) {
        $block = @("[{0}] ensure: CRASH ON BOOT on {1} - {2}" -f (Get-Date -Format o), $Port, $Reason)
        foreach ($line in $lines) { $block += ("  {0}" -f $line) }
        if ($ErrPath) { $block += ("  full stderr: {0}" -f $ErrPath) }
        Add-Content -LiteralPath $LogPath -Encoding utf8 -Value $block
    }
}

function Ensure-Engine([int]$maxAttempts = 3, [int]$waitSeconds = 40) {
    # ONE place that answers "is there an engine, and if not, start one", so the launcher,
    # `new`, `restore` and the watchdog cannot drift. Every attempt is logged, because the
    # engine died at 00:xx on 2026-09-13 while a restart was in flight and there was no
    # record of what had been tried - an unlogged recovery is indistinguishable from none.
    $port = Get-PrimaryPort
    $recoveryLog = Join-Path $StateDir 'engine-recovery.log'
    $slot = @(Get-Slots | Where-Object { $_.enabled } | Select-Object -First 1)
    if (-not $slot) { throw 'no enabled slot in windows.json' }

    # ONE BOOT AT A TIME, FLEET-WIDE (added 2026-09-30, owner's ZABZ-YOGA outage).
    #
    # WHAT WENT WRONG. Four independent supervisors call `ensure` on a timer -- the 1-minute
    # engine watchdog, the 5-minute vitals, the window fleet watchdog and the desktop
    # shortcut -- and none of them knew about the others. When the engine was down, two of
    # them would each decide to start one, each waited the same 40 s, and the loser died with
    # `EADDRINUSE 127.0.0.1:3099`. Because the loser is a child of the owner's shortcut,
    # a raw 20-line Node stack trace about "address already in use" was dumped in front of
    # him. Measured on ZABZ-YOGA: six consecutive failed boots between 19:08:31 and 19:13:21,
    # each one a stack trace, while the port flip-flopped between a slow-loading engine and
    # the next attempt. The engine was never actually broken -- it was being started twice.
    #
    # THE FIX. A machine-wide named mutex, so "is there an engine, and if not, start one"
    # is one atomic decision instead of a race. The loser does NOT give up: it waits for the
    # winner to finish and then re-probes (see below), so a supervisor that arrived second
    # reports success rather than a crash. A mutex (not a lock FILE) because it is released
    # by the kernel if a holder is killed, so a wedged supervisor cannot wedge the fleet.
    $ensureMutex = New-Object System.Threading.Mutex($false, 'Global\dsh-engine-ensure')
    $held = $false
    try {
        try { $held = $ensureMutex.WaitOne([TimeSpan]::FromSeconds($waitSeconds)) }
        catch [System.Threading.AbandonedMutexException] {
            # The previous holder died mid-boot. The kernel hands us ownership: take it and
            # carry on rather than treating an abandoned boot as a permanent failure.
            $held = $true
            "[{0}] ensure: took over an ABANDONED ensure lock (a previous supervisor died mid-boot)" -f (Get-Date -Format o) |
                Add-Content -LiteralPath $recoveryLog -Encoding utf8
        }
        if (-not $held) {
            # Someone else is already booting. Do not start a second engine -- that is the
            # exact fault this guard exists for. Wait, then report whether they succeeded.
            "[{0}] ensure: another supervisor is starting the engine - waiting instead of racing it" -f (Get-Date -Format o) |
                Add-Content -LiteralPath $recoveryLog -Encoding utf8
            Write-Host ("engine on {0} is being started by another supervisor - waiting for it" -f $port) -ForegroundColor Yellow
            $waitUntil = (Get-Date).AddSeconds($waitSeconds)
            while ((Get-Date) -lt $waitUntil) {
                if (Test-EngineAlive $port) { return $true }
                Start-Sleep -Milliseconds 750
            }
            return $false
        }
        # RE-PROBE UNDER THE LOCK. Between the caller's decision to start and this line, the
        # other supervisor may have already brought the engine up; starting a second one now
        # would be the EADDRINUSE we came to prevent.
        if (Test-EngineAlive $port) { return $true }
        return (Invoke-EngineBoot -Port $port -MaxAttempts $maxAttempts -WaitSeconds $waitSeconds -Slot $slot)
    } finally {
        if ($held) { try { $ensureMutex.ReleaseMutex() } catch { } }
        try { $ensureMutex.Dispose() } catch { }
    }
}

function Invoke-EngineBoot([int]$Port, [int]$MaxAttempts, [int]$WaitSeconds, $Slot) {
    # The boot loop itself, split out 2026-09-30 so Ensure-Engine can own the mutex and the
    # loop can `return` from inside it (a `return` in a child function must not release a
    # lock the parent still holds). Behaviour here is unchanged from the original loop.
    $port = $Port
    $maxAttempts = $MaxAttempts
    $waitSeconds = $WaitSeconds
    $slot = $Slot
    $recoveryLog = Join-Path $StateDir 'engine-recovery.log'
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        if (Test-EngineAlive $port) { return $true }
        Write-Host ("engine on {0} is not answering (attempt {1}/{2}) - starting it" -f $port, $attempt, $maxAttempts) -ForegroundColor Yellow
        "[{0}] ensure: port {1} not answering, attempt {2}/{3}" -f (Get-Date -Format o), $port, $attempt, $maxAttempts |
            Add-Content -LiteralPath $recoveryLog -Encoding utf8
        # RECLAIM BEFORE STARTING (2026-09-14). A port that is BOUND but not answering means a
        # wedged engine still owns it, and starting a second one dies with EADDRINUSE -- exactly
        # what the owner walked into at 15:05 that afternoon: the health supervisor had already
        # restarted 3099 as pid 32044 while the watchdog tried to start another, and the window
        # it opened went to a URL that could not authenticate.
        #
        # Stop-ServerTree already finds the REAL holder by port instead of trusting the recorded
        # pid (which was stale: ready-3099.json still named a dead pid 37064), so use it before
        # every start, not only in `restart`. Guarded on the process name so a foreign listener
        # is reported rather than killed; if it is not ours, start anyway and let the normal
        # EADDRINUSE path speak.
        $holder = Get-PortOwner $port
        if ($holder -and $holder.ProcessName -eq 'node') {
            if (-not (Test-EngineWedged $port)) {
                # Bound AND answering on a patient probe: the engine is alive, only loaded.
                # Never take a working engine away -- see Test-EngineWedged.
                "[{0}] ensure: port {1} bound (pid {2}) and answering a patient probe - leaving it alone" -f (Get-Date -Format o), $port, $holder.Id |
                    Add-Content -LiteralPath $recoveryLog -Encoding utf8
                Write-Host ("engine on {0} answered a patient probe (pid {1}) - leaving it alone" -f $port, $holder.Id) -ForegroundColor Green
                return $true
            }
            "[{0}] ensure: port {1} silent to two patient probes - reclaiming from pid {2}" -f (Get-Date -Format o), $port, $holder.Id |
                Add-Content -LiteralPath $recoveryLog -Encoding utf8
            [void](Stop-ServerTree $port (Get-SlotRecord (Get-State) $port))
        } elseif ($holder) {
            "[{0}] ensure: port {1} held by {2} (pid {3}), not a node engine - not reclaiming" -f (Get-Date -Format o), $port, $holder.ProcessName, $holder.Id |
                Add-Content -LiteralPath $recoveryLog -Encoding utf8
        }
        # Declared OUTSIDE the try because the catch reads it, and a throw from the invocation
        # itself (no node on PATH, for one) would leave it unset — StrictMode would then turn the
        # crash report into a second, louder failure.
        $inv = $null
        try {
            # THE ATTEMPT'S OWN LOG PATHS, COMPUTED BEFORE IT RUNS AND PASSED DOWN. The launch
            # stamps each log with the second it was taken, so asking for "the invocation" again
            # after a failure can name a file the attempt never wrote — which is how the stderr
            # that answers "why did it die" would be missed by the very code trying to read it.
            $inv = Get-ServerInvocation $slot
            $r = Start-OneSlotServer $slot $inv
            $state = Get-State
            Set-SlotRecord $state $port ([pscustomobject]@{
                pid = $r.pid; url = $r.url; log = $r.log; workspace = $r.workspace
                startedAt = $r.startedAt; label = $slot.label; profile = $slot.profile })
            Save-State $state
            $deadline = (Get-Date).AddSeconds($waitSeconds)
            while ((Get-Date) -lt $deadline) {
                if (Test-EngineAlive $port) {
                    Write-Host ("engine is answering on {0}" -f $port) -ForegroundColor Green
                    "[{0}] ensure: engine answering on {1} (pid {2})" -f (Get-Date -Format o), $port, $r.pid |
                        Add-Content -LiteralPath $recoveryLog -Encoding utf8
                    return $true
                }
                Start-Sleep -Milliseconds 750
            }
            "[{0}] ensure: engine started (pid {1}) but never answered on {2}" -f (Get-Date -Format o), $r.pid, $port |
                Add-Content -LiteralPath $recoveryLog -Encoding utf8
            # DID IT DIE, OR IS IT ONLY SLOW? Two different faults that used to look identical.
            # A pid that no longer exists cannot answer a later probe, so say so now rather than
            # spending the next two attempts on it. See Write-EngineCrashReport.
            $alive = $false
            if ($r.pid) { $alive = Test-PidExists ([int]$r.pid) }
            if ($alive) {
                Write-Host ("ensure: the engine on {0} is still running (pid {1}) but has not answered in {2}s - a slow boot, not a crash; not retrying against it" -f $port, $r.pid, $waitSeconds) -ForegroundColor Yellow
            } else {
                Write-EngineCrashReport -Port $port -ErrPath $r.err -Reason ("the process (pid {0}) is gone and nothing is answering on {1}" -f $r.pid, $port) -LogPath $recoveryLog
            }
        } catch {
            # A competing supervisor may have won the race: if the port answers now, that is a
            # success, not a failure. Same 2026-09-14 incident as the reclaim block above.
            if (Test-EngineAlive $port) {
                "[{0}] ensure: start reported '{1}' but {2} answers now - treating it as up" -f (Get-Date -Format o), $_.Exception.Message, $port |
                    Add-Content -LiteralPath $recoveryLog -Encoding utf8
                return $true
            }
            # EADDRINUSE IS PROOF THE PORT IS HELD, even when the listen table said otherwise.
            # 2026-09-14 17:49: the table read came back empty on a loaded machine, so no reclaim
            # was attempted and the start died with "port 3099 already in use". The watchdog then
            # logged that same failure roughly once a minute for the next 100 minutes while a
            # wedged engine kept the port. So: refresh the table with the cache bypassed, and if a
            # node process really owns the port -- and is silent to the patient two-probe test --
            # reclaim it and take another run at starting.
            if ($_.Exception.Message -match 'already in use|EADDRINUSE') {
                $script:ListenTableAge = $null
                $holder2 = Get-PortOwner $port
                if ($holder2 -and $holder2.ProcessName -eq 'node' -and (Test-EngineWedged $port)) {
                    "[{0}] ensure: start hit EADDRINUSE - reclaiming the real holder, pid {1}" -f (Get-Date -Format o), $holder2.Id |
                        Add-Content -LiteralPath $recoveryLog -Encoding utf8
                    [void](Stop-ServerTree $port (Get-SlotRecord (Get-State) $port))
                    Start-Sleep -Seconds 2
                    continue
                }
            }
            # THE ANSWER, SAID AT THE POINT OF FAILURE INSTEAD OF LEFT IN A LOG (report §7.3).
            # Two shapes, deliberately: a CRASH gets the bounded report below, and anything else
            # gets one line. The log no longer receives the whole 15-line stderr dump on a single
            # line — the incident's own engine-recovery.log shows that dump spread over 15 lines,
            # where it buried the following attempt instead of naming the fault.
            $headline = Get-ErrorHeadline $_.Exception.Message
            $exitCode = Get-EngineExitCode $_.Exception.Message
            $errPath = if ($inv) { $inv.err } else { $null }
            if ($exitCode -ne $null -and $errPath) {
                Write-EngineCrashReport -Port $port -ErrPath $errPath -Reason ("it exited with code {0}" -f $exitCode) -LogPath $recoveryLog
                # AND STOP. A boot that threw and exited is DETERMINISTIC — same command, same
                # code, same config, so attempt 2 and attempt 3 produce the same exit. The
                # incident's three polite attempts (`21:32:09`, `21:33:17`, `21:34:33`) were three
                # copies of one failure, and each one cost another read of a 180 s budget before
                # reporting the same thing. Nothing is lost by returning now: the watchdog runs
                # Ensure-Engine again within the minute, and by then the reason is on screen and in
                # the log. A NON-crash failure ("did not report a URL within Ns") is not provably
                # deterministic, so that one still gets its retries.
                return $false
            }
            Write-Host ("  start failed: {0}" -f $headline) -ForegroundColor Red
            "[{0}] ensure: start FAILED - {1}" -f (Get-Date -Format o), $headline |
                Add-Content -LiteralPath $recoveryLog -Encoding utf8
        }
        Start-Sleep -Seconds 2
    }
    return $false
}
function Invoke-New {
    [void](Ensure-OriginsProxy)
    $state = Get-State
    $slots = Get-Slots
    # Counting open windows needs a full process-table read, which is the single most
    # expensive thing in this script on a loaded machine (measured 15-35 s, and it is what
    # made `up` appear to hang). It runs here only because `new` must pick a free slot;
    # `up` never pays for it.
    $procTable = Get-WindowProcs
    # `$_.enabled -and` added 2026-09-16. Without it the pick considered ALL TWELVE rows,
    # and the line below force-enabled whichever one it chose -- so `new` opened slots that
    # windows.json says must never open (w9-w12), and never wrote the file back, leaving
    # `status`/`doctor` reporting "8 enabled" while 12 were on screen. Measured on
    # ZABZ-YOGA: the 4 extra windows cost 37 processes / 1,731 MB private = 44 % of the
    # whole Edge footprint, and they reuse w1-w4's screen positions, so they stack.
    $free = @($slots | Where-Object { $_.enabled -and (Get-WindowCount $_ $procTable) -eq 0 }) | Select-Object -First 1
    if (-not $free) {
        # NO FREE SLOT IS NOT THE SAME AS NOTHING TO DO.
        #
        # Measured 2026-09-15: the engine had been stopped (its port free) but Edge still held window
        # processes whose slot count read as occupied, so this branch ran, printed "all slots are
        # already open", and exited 1 -- WITHOUT ever starting an engine. The click did nothing, the
        # task recorded failure, and the cause was a window count, not a server.
        #
        # `new` is reached from the desktop shortcut, whose whole purpose is to hand her a working
        # assistant. So before giving up, make sure an engine exists: if the port is free, bring one
        # up. A window may still not open (every slot genuinely occupied), but she is never left with
        # a dead port and a silent click.
        $enginePort = Get-PrimaryPort
        if (-not (Get-PortOwner $enginePort)) {
            Write-Host ("no free window slot, and no engine on {0} - starting the engine before reporting" -f $enginePort) -ForegroundColor Yellow
            if (Ensure-Engine) { Write-Host ("engine is now up on {0}" -f $enginePort) }
            else { Write-Error ("no free window slot AND no engine could be started on {0}" -f $enginePort); exit 1 }
        }
        Write-Host "all $($slots.Count) window slots are already open. Add another row to windows.json." -ForegroundColor Yellow
        exit 0
    }
    # The force-enable that used to sit here (`foreach ($slot in $slots) { $slot.enabled = $true }`)
    # was removed 2026-09-16: it was the mechanism by which `new` opened disabled slots, and it
    # is what made the window count a one-way ratchet that only a human could undo.
    [void](Open-SlotWindow $free $state)
    Write-Host ("new window: slot '{0}' (profile {1}, origin :{2}) against engine port {3}" -f `
        $free.label, $(if ((Get-ProfileMode) -eq 'shared') { Get-SharedProfileName } else { $free.profile }),
        (Get-SlotOriginPort $free), $(if (Get-Mode -eq 'multi') { $free.port } else { Get-PrimaryPort })) -ForegroundColor Green
    $map = Get-WindowRegistry
    Set-WindowRegistryEntry $map (Get-SlotRegistryKey $free) $true (Get-SlotOriginPort $free)
    Save-WindowRegistry $map
}

function Invoke-Doctor {
    $problems = @()
    # WHICH CONFIG AM I ACTUALLY RUNNING AGAINST. Printed first because the 2026-09-15 fault on her
    # laptop was exactly this and was invisible: the launcher had silently picked up the OWNER's fleet
    # config, so every path it used belonged to another person's profile, and the only clue was an
    # access-denied line in a log. One line here would have ended it in seconds.
    Write-Host ("config      : {0}" -f $ConfigPath)
    $node = try { Resolve-NodeExe } catch { $null }
    if (-not $node) { $problems += 'node.exe not on PATH' } else { Write-Host "node        : $node ($(& $node -v))" }
    $bin = try { Resolve-DshBin } catch { $null }
    if (-not $bin) { $problems += '@deepseek-ai/dsh/lib/bin.js not found' } else { Write-Host "dsh bin     : $bin" }
    $edge = Get-EdgePath
    if (-not $edge) { $problems += 'no Edge/Chrome binary found' } else { Write-Host "browser     : $edge" }
    # How a new window will authenticate. A window that opens the CLEAN origin can only pass through
    # that profile's cookie and nothing seeds it, which is exactly how the owner met the bare
    # "dsh web authentication required" page on 2026-09-15. So doctor names the URL a new window
    # would use and proves the token is accepted (303), instead of leaving it to be discovered in the
    # browser. The token itself is redacted -- doctor output gets pasted into notes and logs.
    $dport = Get-PrimaryPort
    $durl = Resolve-WindowUrl $dport (Get-SlotRecord (Get-State) $dport)
    if (Test-LaunchUrl $durl $dport) {
        Write-Host ("window url  : {0} (tokenized)" -f ($durl -replace 'token=.*', 'token=<redacted>'))
    } else {
        Write-Host ("window url  : {0} (NO TOKEN - a profile without a cookie shows the auth page)" -f $durl) -ForegroundColor Yellow
        $problems += "no usable launch token for port $dport; new windows depend on an already-seeded profile cookie"
    }
    if (Test-PortInUse $dport) {
        # HttpClient with redirects OFF, because that is the only way to observe the 303:
        # `Invoke-WebRequest -MaximumRedirection 0` throws "Operation is not valid due to the current
        # state of the object" on PowerShell 7, and following the redirect reports a harmless 200.
        $client = $null
        try {
            $handler = [System.Net.Http.HttpClientHandler]::new()
            $handler.AllowAutoRedirect = $false
            $client = [System.Net.Http.HttpClient]::new($handler)
            $client.Timeout = [TimeSpan]::FromSeconds(5)
            $resp = $client.SendAsync([System.Net.Http.HttpRequestMessage]::new('GET', $durl)).GetAwaiter().GetResult()
            $code = [int]$resp.StatusCode
            Write-Host ("auth probe  : token exchange -> {0}{1}" -f $code, $(if ($code -eq 303) { ' (accepted)' } else { ' (EXPECTED 303)' }))
            if ($code -ne 303) { $problems += "the launch token for port $dport was refused with HTTP $code" }
            $resp.Dispose()
        } catch {
            Write-Host ("auth probe  : failed - {0}" -f $_.Exception.Message) -ForegroundColor Yellow
        } finally { if ($client) { $client.Dispose() } }
    }
    # ONE expression, in one place (Initialize-DshHome), because two conventions is how a launcher
    # comes to hold two ideas of where the home is. It also fills an unset DSH_HOME in, which is
    # what `ensure` does — doctor just reports what that resolved to.
    $home_dsh = Initialize-DshHome
    if (-not $home_dsh) { $problems += 'DSH_HOME could not be derived: USERPROFILE is not set' }
    elseif (-not (Test-Path $home_dsh)) { $problems += "DSH_HOME missing: $home_dsh" }
    else { Write-Host "DSH_HOME    : $home_dsh" }
    foreach ($p in @($StateDir, $LogDir, $Cfg.browser.profileRoot)) {
        try { New-Item -ItemType Directory -Force -Path $p | Out-Null; Write-Host "dir ok      : $p" }
        catch { $problems += "cannot create $p" }
    }
    $disabled = @($Cfg.windows | Where-Object { -not $_.enabled }).Count
    Write-Host ("slots       : {0} enabled, {1} disabled" -f @($Cfg.windows | Where-Object { $_.enabled }).Count, $disabled)
    # WHAT A WINDOW COSTS, AND WHAT ITS SESSION LIST WILL DO. Both are the reason this build exists,
    # so `doctor` states them instead of leaving them to be inferred from how a window feels.
    $pMode = Get-ProfileMode
    if ($pMode -eq 'shared') {
        Write-Host ("profile mode: shared ({0}) - one browser process tree for every window" -f (Get-SharedProfileName))
    } else {
        Write-Host ("profile mode: per-window - one browser process tree PER window (~9 processes, mean 892 MB each measured 2026-09-18)") -ForegroundColor Yellow
    }
    if (-not (Test-OriginsEnabled)) {
        Write-Host "origins     : DISABLED" -ForegroundColor Yellow
        if ($pMode -eq 'shared') { $problems += 'origins disabled with profileMode=shared: every window will share ONE session slot (localStorage dsh.sessions.current is keyed by origin)' }
    } else {
        $a = Get-OriginsArgs
        if (Test-OriginsProxy -Quiet) {
            $st = Get-OriginsStats
            Write-Host ("origins     : proxy up on :{0}..:{1} -> engine :{2}" -f $a.basePort, ($a.basePort + $a.count - 1), $a.target)
            if ($st) {
                Write-Host ("session list: served={0} cold={1} cached={2} ageMs={3} rows={4} errors={5}" -f `
                    $st.served, $st.cold, $st.cached, $st.ageMs, $st.rows, $st.errors)
                if (-not $st.cached) { Write-Host "session list: cache EMPTY - the next window to load pays the full 25-31 s walk" -ForegroundColor Yellow }
            }
        } else {
            Write-Host ("origins     : NOT ANSWERING on :{0}" -f $a.basePort) -ForegroundColor Red
            $problems += "the origin proxy is not answering on port $($a.basePort); windows opened now cannot reach the engine (run: dshw ensure)"
        }
    }
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
    # -WindowsMode RESTORE, AND THAT IS FIX 3 OF THE 2026-09-18 WINDOW-KILLER WORK.
    #
    # This task registered `-WindowsMode no`, which starts the ENGINE and nothing else: `no` matches
    # neither the `restore` branch nor the `yes/auto` branch of Invoke-Up, so the registry was never
    # consulted and no window ever came back. `dshw-launch.cmd` -- the one entry point that does
    # `ensure` then `restore`, i.e. exactly what a logon wants -- is referenced by no task and no
    # shortcut, so after a reboot the engine returned and the owner's windows did not, which
    # contradicts the stated intent of the launcher. `restore` is the right mode here rather than
    # `yes`: `yes` opens EVERY enabled slot (sixteen), while `restore` opens the remembered working
    # set and never more than one when nothing is remembered.
    #
    # This is safe ONLY because the reconcile that guards the registry no longer acts on a single
    # false negative (Sync-WindowRegistry) -- the 00:01:59 prune is what made a logon restore
    # untrustworthy in the first place. See docs/multi-window/WINDOW-KILLER.md 12.
    $action = New-HiddenTaskAction -Execute $ps -TaskName $taskName `
        -Argument "-NoProfile -WindowStyle Hidden -File `"$script`" up -ConfigPath `"$ConfigPath`" -WindowsMode restore"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    # PRESERVE THE RUN LEVEL OF AN EXISTING REGISTRATION. `Test-IsElevated` describes the shell that
    # happens to run `autostart on`, not the task: re-registering from an elevated session must not
    # silently escalate a logon task that was registered least-privilege, because that changes what
    # every process it starts is allowed to do. Measured 2026-09-18: this task is RunLevel=Limited,
    # and re-registering it from an elevated shell would have made it Highest.
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $keepHighest = if ($existing) { "$($existing.Principal.RunLevel)" -eq 'Highest' } else { Test-IsElevated }
    $principal = New-InteractivePrincipal -Highest:$keepHighest
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "autostart: '$taskName' registered (at logon, this user, hidden): dshw up -WindowsMode restore"
    Write-Host "          It starts the engine if it is not listening, then reopens exactly the windows in the registry."
    Write-Host "          Test the restore decision without opening anything: dshw plan"
}

function Invoke-WindowRecovery($state, [int]$MaxOpens = 2, [switch]$DryRun) {
    # A WINDOW THAT DIES NO LONGER COMES BACK BY ITSELF. The engine has `ensure` every minute, but
    # nothing watched the WINDOWS: the registry answers "what was open when DSH was last closed",
    # and only `restore` consults it, so a window that crashed mid-session stayed gone until the
    # owner clicked `+`. This is the loop that closes that gap, and it is deliberately the most
    # conservative thing in the file, because the failure it can cause (opening a window the owner
    # already has) is worse than the one it fixes.
    #
    # FIVE GUARDS, because 229 duplicate open events is what this class of bug already cost:
    #   1. the registry must say the window was part of the working set (`open: true`);
    #   2. the origin port the registry RECORDED must equal the origin this slot has now, so a
    #      pre-shared-profile entry (`port: 3099`, the legacy engine-port windows) is never treated
    #      as a missing window - those entries cannot be told apart slot by slot, so the honest
    #      answer for them is "leave them alone";
    #   3. the origin must have a LISTENER, which is independent evidence that the proxy really
    #      serves it, so a registry entry naming a port nothing ever served is never acted on;
    #   4. the origin must not be in the live set that Get-OpenOriginPorts just measured, in any of
    #      the three shapes a window can be open in;
    #   5. a per-slot cooldown, so a window that was JUST reopened (and has not connected yet) is
    #      never reopened again by the next run.
    # Plus a cap per run: if more than $MaxOpens windows are genuinely missing, the rest are
    # reported and left for the next run, so a systematic fault can never open sixteen windows at
    # once.
    $map = Get-WindowRegistry
    $slots = Get-Slots
    $live = @(Get-OpenOriginPorts | ForEach-Object { [int]$_ })
    $listenTable = Get-ListenTable
    $cooldown = 600
    $markerPath = Join-Path $StateDir 'window-recovery.json'
    $marks = @{}
    if (Test-Path $markerPath) {
        try {
            $raw = Get-Content -Raw -LiteralPath $markerPath | ConvertFrom-Json
            foreach ($p in $raw.PSObject.Properties) { $marks[$p.Name] = [string]$p.Value }
        } catch { }
    }

    $missing = @()
    foreach ($slot in $slots) {
        if (-not $slot.enabled) { continue }
        $key = Get-SlotRegistryKey $slot
        $entry = $map[$key]
        if (-not $entry) { continue }
        if ($entry.open -ne $true) { continue }
        $origin = [int](Get-SlotOriginPort $slot)
        $recorded = 0
        try { $recorded = [int](Get-Prop $entry 'port') } catch { $recorded = 0 }
        if ($recorded -ne $origin) { continue }                       # guard 2
        if (-not (Get-PortOwner $origin $listenTable)) { continue }   # guard 3
        if ($live -contains $origin) { continue }                     # guard 4
        $missing += [pscustomobject]@{ key = $key; origin = $origin; label = $slot.label }
    }
    if ($missing.Count -eq 0) { return [pscustomobject]@{ missing = 0; opened = 0; held = @(); note = '' } }

    $opened = 0
    $held = @()
    $notes = @()
    foreach ($m in $missing) {
        if ($opened -ge $MaxOpens) { $held += $m.key; continue }
        $last = $null
        if ($marks.ContainsKey($m.key)) { try { $last = [datetime]::Parse($marks[$m.key]) } catch { $last = $null } }
        if ($last -and ((Get-Date) - $last).TotalSeconds -lt $cooldown) {     # guard 5
            $held += $m.key
            continue
        }
        if ($DryRun) {
            Write-Host ("  [recover] would reopen '{0}' (origin :{1}, registry says open)" -f $m.key, $m.origin)
            $opened++
            $notes += "dry-run: $($m.key)"
            continue
        }
        $slot = @($slots | Where-Object { (Get-SlotRegistryKey $_) -eq $m.key }) | Select-Object -First 1
        try {
            [void](Open-SlotWindow $slot $state)
            Set-WindowRegistryEntry $map $m.key $true $m.origin
            $marks[$m.key] = (Get-Date).ToString('o')
            $opened++
            $notes += $m.key
            Write-Host ("  [reopen] {0} (origin :{1}) - its window was gone" -f $m.key, $m.origin) -ForegroundColor Green
        } catch {
            $notes += ("{0} FAILED: {1}" -f $m.key, $_.Exception.Message)
            Write-Host ("  [WARN] could not reopen '{0}': {1}" -f $m.key, $_.Exception.Message) -ForegroundColor Yellow
        }
    }
    if (-not $DryRun) {
        if ($opened -gt 0) { Save-WindowRegistry $map }
        try {
            $json = [pscustomobject]$marks | ConvertTo-Json -Depth 3
            [System.IO.File]::WriteAllText($markerPath, $json, (New-Object System.Text.UTF8Encoding($false)))
        } catch { }
        $line = "[{0}] recovery: missing={1} opened={2} ({3}) held={4}" -f `
            (Get-Date -Format o), $missing.Count, $opened, ($notes -join ','), ($held -join ',')
        Add-Content -LiteralPath (Join-Path $StateDir 'health.log') -Encoding utf8 -Value $line
    }
    return [pscustomobject]@{ missing = $missing.Count; opened = $opened; held = $held; note = ($notes -join '; ') }
}

function Invoke-Health {
    # Designed to be run from a scheduled task every few minutes. It is idempotent and
    # additive: it starts ONLY the servers that should be listening and are not, then
    # exits. It never stops or restarts a live engine, and it appends a line to health.log
    # only when it actually did something, so the log stays readable.
    #
    # IT ALSO RECOVERS WINDOWS, AND THAT IS NEW (2026-09-18). Until now this command opened
    # nothing, which is why `DSH Window Fleet Watchdog` - the task that runs it - was the wrong
    # suspect for the "two windows every ten minutes" report and the wrong thing to disable: the
    # windows were opened by `new`/`restore`, whose liveness test could not see a window on a proxy
    # origin and so re-opened one that was already there. The liveness test is fixed
    # (Get-OpenOriginPorts), and a window that dies is now restored by Invoke-WindowRecovery, which
    # opens at most two windows per run and never one the live set already reports.
    #
    # Safe to run twice at once: the port bind itself is the lock, and the
    # loser of a race fails with EADDRINUSE instead of starting a second writer on the
    # same DSH_HOME (which would corrupt session logs).
    # Transcript so a watchdog run that dies leaves evidence: a scheduled task that does
    # nothing and says nothing is indistinguishable from one that is not running at all.
    $logDir = Join-Path $StateDir 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    # ONE TRANSCRIPT PER DAY, APPENDED -- not one per run.
    #
    # The reason for a transcript at all is sound: "a scheduled task that does nothing and says
    # nothing is indistinguishable from one that is not running at all". But a file per run at a
    # run every five minutes is 288 files a day, and by 2026-09-14 this directory held ~1000
    # health-*.log files, which is slow to enumerate and painful to read. Appending to a
    # per-day file keeps the evidence and bounds the count to ~30 files a month. Nothing is
    # deleted; the existing per-run files stay exactly where they are.
    Start-Transcript -Path (Join-Path $logDir ("health-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))) -Append -Force | Out-Null
    try {
    [void](Ensure-OriginsProxy)
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

    # ── AND NOW THE WINDOWS, WHICH IS WHY THIS TASK WAS DISABLED AND IS THE GAP BEING CLOSED ────
    # `health` used to do nothing but engines, so the task named "Window Fleet Watchdog" watched
    # no windows at all: a window that died stayed dead until the owner clicked `+`. With the
    # liveness check above now recognising a window on ANY origin the launcher uses, "this slot
    # has a live window" is finally answerable, which is what makes a recovery pass safe to run.
    #
    # AND IT RECONCILES FIRST (added 2026-09-18). This is the path the confirmed-negative rule is
    # really for: `health` runs every five minutes over a machine in steady state, so a row recorded
    # open whose window has not been live for two readings $WindowPruneConfirmSeconds apart is a
    # genuine "it was there last tick and is not there now" - which is a different statement from the
    # one `restore` can make about a window it launched 300 ms ago. Reconciling BEFORE recovery also
    # means guard 1 stops treating a window the owner closed as a reopen candidate, and recovery
    # running after means the reconciler never sees a window it just had us open.
    try {
        $reconcile = Sync-WindowRegistry $state -ConfirmSeconds $WindowPruneConfirmSeconds
        Write-Host ("windows: reconcile considered {0} recorded-open slot(s) - closed {1} ({2} by port mismatch, {3} by two fresh negatives {4}s apart), spared {5}, unconfirmed {6}" -f `
            $reconcile.considered, $reconcile.closed, $reconcile.mismatched, ($reconcile.closed - $reconcile.mismatched),
            $WindowPruneConfirmSeconds, $reconcile.spared, $reconcile.unconfirmed)
        Write-Host ("windows: {0}" -f (Format-RegistryCensus $reconcile.attribution))
        foreach ($d in @($reconcile.details)) { Write-Host ("windows:   {0}" -f $d) }

        $rec = Invoke-WindowRecovery $state
        # ALWAYS SAY WHAT THE PASS SAW, not only when it opened something. The whole reason this
        # task was switched off by hand on 2026-09-18 is that a window-opening loop was invisible
        # until someone read the raw open log; a recovery pass that does nothing must therefore be
        # distinguishable in the transcript from one that never ran.
        Write-Host ("windows: live origins [{0}]; registry-open-and-missing {1}; reopened {2}{3}" -f `
            ((@(Get-OpenOriginPorts) -join ',')), $rec.missing, $rec.opened,
            $(if (@($rec.held).Count) { "; held for the next run: " + (@($rec.held) -join ',') } else { '' }))
        if ($rec.missing -gt 0) {
            Write-Host ("windows: {0} recorded as open but gone; reopened {1}" -f $rec.missing, $rec.opened) -ForegroundColor Yellow
        }
    } catch {
        Write-Host ("windows: reconcile/recovery pass FAILED - " + $_.Exception.Message) -ForegroundColor Red
        "[{0}] health: window reconcile/recovery FAILED: {1}" -f (Get-Date -Format o), $_.Exception.Message |
            Add-Content -LiteralPath (Join-Path $StateDir 'health.log') -Encoding utf8
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
    # `1m` is the fast loop the owner actually needs: the browser cannot recover for you when
    # the engine is gone (it retries a socket, it cannot start a process), and a five-minute
    # gap is long enough to close DSH and give up. The fast loop checks with a bounded socket
    # connect and restarts only after TWO consecutive failures, so a single blip cannot cause
    # a restart loop.
    $fast = ($mode -eq 'fast')
    $taskName = if ($fast) { 'DSH Engine Watchdog (1m)' } else { 'DSH Window Fleet Watchdog' }
    if ($mode -eq 'off') {
        foreach ($t in 'DSH Window Fleet Watchdog', 'DSH Engine Watchdog (1m)') {
            if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
                Unregister-ScheduledTask -TaskName $t -Confirm:$false
                Write-Host "watchdog: removed '$t'"
            }
        }
        return
    }
    $ps = (Get-Command pwsh).Source
    $script = Join-Path $PSScriptRoot 'dshw.ps1'
    $verb = if ($fast) { 'ensure' } else { 'health' }
    $action = New-HiddenTaskAction -Execute $ps -TaskName $taskName `
        -Argument "-NoProfile -WindowStyle Hidden -File `"$script`" $verb -ConfigPath `"$ConfigPath`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes $(if ($fast) { 1 } else { 5 }))
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
    $principal = New-InteractivePrincipal -Highest:(Test-IsElevated)
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host ("watchdog: '{0}' registered - 'dshw {1}' every {2} minute(s), this user." -f $taskName, $verb, $(if ($fast) { 1 } else { 5 }))
    Write-Host "          It only ever STARTS a missing engine, and reopens a window the registry says was open and the liveness check says is gone."
    Write-Host "          Live engines and live windows are left alone."
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

# Self-heal: stop interactive console task windows from popping up. Safe to call on every
# invocation (guarded by elevation + a per-machine daily marker), and it must run here rather
# than only in `ensure`/`health` so a plain elevated `dshw status` also applies it.
Invoke-HiddenTaskBootstrap

# Per-command memo for the origin-proxy probes: Get-WindowCount is called once per slot, and a
# fresh HTTP round trip and a fresh process scan per slot is exactly the mistake `status` already
# records (12 queries see the process list at 12 different instants). Reset here, so every command
# starts from the truth.
$script:OriginsAlive = $null
$script:OpenOriginCache = $null
$script:OriginLiveMap = $null
$script:OriginLiveLegsCache = $null

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
    'new'    {
        # `new` OPENS A WINDOW. It must never take the engine down.
        # If the port has a listener the engine exists; a slow probe means a loaded engine, not a
        # dead one. 2026-09-14 18:27: this path reclaimed a live engine (pid 19556) and froze
        # every window on the machine, because the probe budget was shorter than this machine's
        # normal worst-case response time. See Test-EngineWedged.
        $enginePort = Get-PrimaryPort
        if (Get-PortOwner $enginePort) { Invoke-New }
        elseif (Ensure-Engine) { Invoke-New }
        else { Write-Error 'no engine could be started on the primary port'; exit 1 }
    }
    'ensure' { Invoke-Ensure }
    'restore' {
        # Same rule as `new`: reopening windows must never reclaim a bound port.
        if ($DryRun) { Invoke-Restore -DryRun }
        else {
            $enginePort = Get-PrimaryPort
            if (Get-PortOwner $enginePort) { Invoke-Restore }
            elseif (Ensure-Engine) { Invoke-Restore }
            else { Write-Error 'no engine could be started on the primary port'; exit 1 }
        }
    }
    # `plan` is the CLI surface for Invoke-Restore -DryRun, and it is the ONLY reason the switch
    # exists: the logon path now restores (see Invoke-Autostart), and the only way to exercise that
    # decision without a reboot is to ask what it would do. It opens nothing, starts no proxy and
    # writes no registry (added 2026-09-18).
    'plan'   { Invoke-Restore -DryRun }
    'open'   {
        # `$slotCfg`, NOT `$slot`, AND THAT IS LOAD-BEARING. PowerShell variable names are
        # case-INSENSITIVE, so `$slot` and the parameter `$Slot` are THE SAME VARIABLE - a local
        # `$slot = $null` here silently blanked the selector, and the very next line then reported
        # "no slot matches ''". Every command whose whole job is to act on one named slot was
        # therefore broken when invoked as `dshw open 3` / `dshw open -Slot 3`, while `dshw new`
        # (which takes no selector) worked, which is why it went unnoticed.
        $slotCfg = Get-SlotCfgByPortOrLabel $Slot
        if (-not $slotCfg) { Write-Error "no slot matches '$Slot'"; exit 2 }
        [void](Open-SlotWindow $slotCfg (Get-State))
        Write-Host ("opened window for slot '{0}'" -f $slotCfg.label)
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
