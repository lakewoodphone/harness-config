<#
.SYNOPSIS
  mesh-hygiene.ps1 -- the node hygiene policy and its drift report, for a Windows mesh worker node.

.DESCRIPTION
  OWNER: stream O4 of the overnight program (docs/mesh/81-overnight-program.md section 1).
  DOC:   docs/mesh/85-hygiene.md.
  MODEL: docs/mesh/80-mac-worker-hygiene.md -- the Mac mini's reclaim policy. This is that policy
         generalised to Windows (its sibling scripts/mesh-hygiene.sh covers Linux and macOS), plus
         the half the Mac version did not have: a per-node DRIFT REPORT, so a node sliding out of
         the placeable set is visible BEFORE the broker stops choosing it.

  THE PROBLEM, IN THE OWNER'S OWN WORDS (2026-09-16):
    "macs don't close down processes like on Windows -- when I X things out they are still running"
  Windows has the same class of waste with a different face: a browser or chat client that outlives
  its window, and orphaned helpers left behind by our own probes. A tool call that times out leaves
  a shell whose parent is gone, and Node's ChildProcess.kill() does not kill a process tree on
  Windows (scripts/dsh-reap.ps1 documents that measured case). Free memory drifts down over days,
  the broker reads memory honestly, and the node silently stops being chosen. reports/mesh/74 on the
  Mac measured the shape of it: ~0.8 of a core burned for 32 hours by thirteen orphans of our own
  diagnostic probes.

  TWO RECLAIM CLASSES, AND NOTHING ELSE IS EVER ELIGIBLE.
    CLASS A -- applications on an EXPLICIT target list, matched by the process's OWN EXECUTABLE PATH
               (a directory prefix), so Chrome under Google's own directory counts and a third-party
               renderer or an unrelated binary cannot. Only processes in the CONSOLE session are
               eligible: a hygiene policy has no business ending another user's session.
    CLASS B -- ORPHANS of our own tooling: the recorded parent PID no longer exists (on Windows the
               PPID field is never rewritten, so a dead parent is provable), the command line matches
               one of OUR tool entry points, and it is older than -MinOrphanAgeSeconds.

  THE THREE GATES. It acts ONLY when all three hold (81 section 1); every failing gate is named in
  the log line and in the record:
    1. no console user active  -- no active interactive session at all, OR one input-idle for at
                                  least -IdleSeconds. If a session exists and its idle time CANNOT
                                  be measured from where this script runs, the script DECLINES: an
                                  unmeasurable idle time is never read as idle.
    2. no dispatch in flight   -- no live `dsh ... --profile headless` child (the frozen dispatch
                                  shape, 71 section 2.3). A resident agent-loop session is NOT a
                                  dispatch: hybrid nodes must still be able to clean themselves.
    3. no lease held           -- no admission-governor lease whose own heartbeat is unexpired.
                                  (Liveness is the lease's `expiresAt`, never a pid guess --
                                  packages/plugin-health/lib/governor.js says why.)

  THE THREE COUNTERS (all in every record; do not confuse them)
    avail_mib          -- THE CAPACITY CONTRACT'S NUMBER: GlobalMemoryStatusEx().ullAvailPhys, which
                          is what node's os.freemem() returns and therefore what the gate's
                          `mem.freeMiB` and the governor's budget are derived from
                          (scripts/phone-gate.py, _memory_bytes() Windows branch). If this script
                          used a different "free", the drift report and the broker would disagree
                          about the same machine in the same second.
    reclaimable_rss_kb -- bytes held by processes THIS POLICY may reclaim right now (class A RSS +
                          class B RSS). This is the drift signal: it is what is accumulating.
    placeable_children -- the children the broker's frozen formula would place here right now:
                          memorySlots = min(floor((availMiB - 3885)/160), 24) - governor.inUse;
                          coreSlots   = floor(physicalCores * 0.75);
                          slots       = min(memorySlots, coreSlots); swap >= 90% halves it (71 s2.2).
                          REPRODUCED here, not asked of the broker: the disk and transport terms are
                          NOT included, and the record says so.

  A LOG LINE ON EVERY PATH, INCLUDING EVERY DECLINE, WITH THE REASON AND THE BYTES. Three sinks:
    <status dir>\mesh-hygiene.log     one human line per run
    <status dir>\mesh-hygiene.jsonl   one JSON object per run (the machine-readable half)
    <status dir>\mesh-hygiene.json    the latest record, for a monitor to read in one shot
  Default status dir: $env:USERPROFILE\.dsh-sync-status -- the same idiom as status.json,
  mesh-health.json and phone-gate.json on every Windows node.

  NOTHING IS KILLED UNLESS YOU PASS -Reclaim. The default mode is a read-only report.

.EXAMPLE
  pwsh -File scripts\mesh-hygiene.ps1                      # read-only report
  pwsh -File scripts\mesh-hygiene.ps1 -Reclaim             # act, with the shipped gates
  pwsh -File scripts\mesh-hygiene.ps1 -Drift -Last 20      # the drift series for this node
  pwsh -File scripts\mesh-hygiene.ps1 -Collect             # every node's latest line, one command
  pwsh -File scripts\mesh-hygiene.ps1 -SelfTest            # the regression test (spawns its own hogs)

.EXAMPLE
  # TASK SCHEDULER -- install (running this script installs nothing):
  #   $a = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument '-NoProfile -File C:\Users\ezabz\code\harness-config\scripts\mesh-hygiene.ps1 -Reclaim -Quiet'
  #   $t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
  #   Register-ScheduledTask -TaskName 'DSH Mesh Hygiene' -Action $a -Trigger $t -RunLevel Highest -User 'SYSTEM'
  # OFF SWITCH, exactly one command:
  #   Unregister-ScheduledTask -TaskName 'DSH Mesh Hygiene' -Confirm:$false
  # MEASURED (docs/mesh/85-hygiene.md section 8): registered as SYSTEM (session 0) on this build
  # (Windows 11 26200) the console's idle time is NOT readable, so a SYSTEM job DECLINES every time
  # with that reason. Register it as the console user if you want class A; as SYSTEM it still
  # reclaims class B orphans whenever no interactive session exists.

.NOTES
  Exit codes: 0 the script ran (reported / acted / declined). 1 usage or self-test failure.
              3 the primary counter or the process table could not be measured -- nothing was touched.

  WHAT THIS DELIBERATELY DOES NOT DO:
    * It does not reap stale MCP-server generations or npm/npx shims. scripts/dsh-reap.ps1 owns that
      class on Windows (its RULE 1/2), is already scheduled on this node, and two reapers with
      overlapping rules is how a machine gets eaten. The two are complementary and both idempotent.
    * It never kills a process it cannot identify by PATH (class A) or by a dead parent PLUS an
      explicit command-line pattern (class B). No name-only matching, ever.
    * It never touches the DSH engine (`dsh\lib\bin.js web`), the console user's non-listed apps, or
      any process belonging to another session.
#>
[CmdletBinding()]
param(
    [switch]$Reclaim,
    [switch]$Drift,
    [int]$Last = 10,
    [switch]$Collect,
    [string[]]$Nodes = @(),
    [switch]$SelfTest,
    [int]$IdleSeconds = 1800,
    [int]$MinOrphanAgeSeconds = 300,
    [string[]]$Targets = @(),
    [string]$OrphanPatterns = '',
    [string]$StatusDir = '',
    [string]$GovernorRoot = '',
    [string]$GateUrl = '',
    [int]$GateTimeoutSec = 2,
    [int]$GraceSec = 10,
    [switch]$NoEscalate,
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'

$HYGIENE_VERSION = '1.0.0'
$HYGIENE_SCHEMA  = 1

# 71 s2.2, frozen. Named once here so the drift report and the broker cannot drift apart silently.
$RESERVE_MIB   = 3885
$PER_CHILD_MIB = 160
$MAX_SLOTS     = 24
$CORE_FRACTION = 0.75
$SWAP_HALF_PCT = 90.0

if (-not $StatusDir) { $StatusDir = Join-Path $env:USERPROFILE '.dsh-sync-status' }
if (-not $GateUrl)   { $GateUrl = 'http://127.0.0.1:3086/mesh/capacity' }
if (-not $GovernorRoot) {
    if ($env:DSH_HOME) { $GovernorRoot = Join-Path $env:DSH_HOME 'governor' }
    else { $GovernorRoot = Join-Path (Join-Path $env:USERPROFILE '.dsh') 'governor' }
}

$LOG       = Join-Path $StatusDir 'mesh-hygiene.log'
$DECISIONS = Join-Path $StatusDir 'mesh-hygiene.jsonl'
$LATEST    = Join-Path $StatusDir 'mesh-hygiene.json'

# ---------------------------------------------------------------------------------------------
# THE EXPLICIT TARGET LIST (class A). Directory prefixes, not names: a match requires the process's
# own executable path to lie under one of these, so another vendor's helper, a WebView2 host or a
# standalone renderer is structurally unable to match. Every entry is an application a worker node
# accumulates because closing its window does not close it. A prefix that is not installed costs
# nothing; a path that is not in this list can never be returned. -Targets REPLACES the list, and
# the record names the source so a reader can always tell which list produced a kill.
# ---------------------------------------------------------------------------------------------
function Get-DefaultTargets {
    $pf   = [string]$env:ProgramFiles
    $pf86 = [string]${env:ProgramFiles(x86)}
    $lad  = [string]$env:LOCALAPPDATA
    $ad   = [string]$env:APPDATA
    $list = @()
    foreach ($root in @($pf, $pf86)) {
        if ($root) {
            $list += (Join-Path $root 'Google\Chrome\Application\')
            $list += (Join-Path $root 'Microsoft\Edge\Application\')
            $list += (Join-Path $root 'BraveSoftware\Brave-Browser\Application\')
            $list += (Join-Path $root 'Mozilla Firefox\')
            $list += (Join-Path $root 'Spotify\')
        }
    }
    if ($lad) {
        $list += (Join-Path $lad 'Google\Chrome\Application\')
        $list += (Join-Path $lad 'Microsoft\Edge\Application\')
        $list += (Join-Path $lad 'Programs\Opera\')
        $list += (Join-Path $lad 'Vivaldi\Application\')
        $list += (Join-Path $lad 'slack\')
        $list += (Join-Path $lad 'Discord\')
        $list += (Join-Path $lad 'Programs\Notion\')
        $list += (Join-Path $lad 'Obsidian\')
        $list += (Join-Path $lad 'WhatsApp\')
        $list += (Join-Path $lad 'Microsoft\Teams\')
        $list += (Join-Path $lad 'Programs\Microsoft Teams\')
    }
    if ($ad) {
        $list += (Join-Path $ad 'Spotify\')
        $list += (Join-Path $ad 'Zoom\bin\')
        $list += (Join-Path $ad 'Telegram Desktop\')
    }
    return @($list | Where-Object { $_ } | ForEach-Object { ($_.TrimEnd('\')) + '\' })
}

# ---------------------------------------------------------------------------------------------
# THE EXPLICIT ORPHAN PATTERNS (class B): our own tool entry points, by command line. A match is only
# eligible when the parent is GONE and the process is older than the age floor -- a live probe has a
# live parent and can never match.
#
# Deliberately NOT here: the DSH engine (`dsh\lib\bin.js`), MCP servers, and the npm/npx shim class.
# scripts/dsh-reap.ps1 owns those (its RULE 1/RULE 2) and is already scheduled on this node;
# duplicating them would give one machine two reapers with different rules.
# ---------------------------------------------------------------------------------------------
$DEFAULT_ORPHAN_PATTERNS = 'tailscale|phone-gate\.py|mesh-run\.mjs|mesh-capacity-probe|mesh-e2e\.ps1|mesh-health\.ps1|governor\.mjs|agent-fleet\.(ps1|sh|mjs)|journal\.py|mesh-hygiene'
# The one process that must survive every path in this script, however its command line reads.
$ENGINE_PATTERN = 'dsh\\lib\\bin\.js\s+web'

# ---------------------------------------------------------------------------------------------
# P/Invoke: the OS's own counters. Wrapped so that a locked-down host degrades to CIM AND SAYS SO in
# the record (`avail_source`), rather than reporting a number from a different definition.
# ---------------------------------------------------------------------------------------------
$script:HaveNative = $false
$script:NativeError = ''
try {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MeshHygieneNative {
    [StructLayout(LayoutKind.Sequential)]
    public struct MEMORYSTATUSEX {
        public uint dwLength; public uint dwMemoryLoad;
        public ulong ullTotalPhys; public ulong ullAvailPhys;
        public ulong ullTotalPageFile; public ulong ullAvailPageFile;
        public ulong ullTotalVirtual; public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;
    }
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX s);

    [StructLayout(LayoutKind.Sequential)]
    public struct PERFORMANCE_INFORMATION {
        public uint cb; public IntPtr CommitTotal; public IntPtr CommitLimit; public IntPtr CommitPeak;
        public IntPtr PhysicalTotal; public IntPtr PhysicalAvailable; public IntPtr SystemCache;
        public IntPtr KernelTotal; public IntPtr KernelPaged; public IntPtr KernelNonpaged;
        public IntPtr PageSize; public uint HandleCount; public uint ProcessCount; public uint ThreadCount;
    }
    [DllImport("psapi.dll", SetLastError=true)] public static extern bool GetPerformanceInfo(ref PERFORMANCE_INFORMATION p, uint cb);

    [StructLayout(LayoutKind.Sequential)]
    public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO lii);
    [DllImport("kernel32.dll")] public static extern uint GetTickCount();

    [StructLayout(LayoutKind.Sequential)]
    public struct WTS_SESSION_INFO { public int SessionID; public IntPtr pWinStationName; public int State; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct WTSINFOEX_LEVEL1 {
        public int SessionId; public int SessionState; public int SessionFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=33)] public string WinStationName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=21)] public string UserName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=18)] public string DomainName;
        public long LogonTime; public long ConnectTime; public long DisconnectTime;
        public long LastInputTime; public long CurrentTime;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct WTSINFOEX { public int Level; public WTSINFOEX_LEVEL1 Data; }

    [DllImport("wtsapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    public static extern int WTSEnumerateSessions(IntPtr h, int r, int v, ref IntPtr p, ref int n);
    [DllImport("wtsapi32.dll", SetLastError=true, CharSet=CharSet.Unicode, EntryPoint="WTSQuerySessionInformationW")]
    public static extern int WTSQuerySessionInformation(IntPtr h, int s, int c, ref IntPtr p, ref int n);
    [DllImport("wtsapi32.dll")] public static extern void WTSFreeMemory(IntPtr p);

    public static int[] SessionIds() {
        IntPtr p = IntPtr.Zero; int n = 0;
        if (WTSEnumerateSessions(IntPtr.Zero, 0, 1, ref p, ref n) == 0) { return new int[0]; }
        int[] ids = new int[n]; int sz = Marshal.SizeOf(typeof(WTS_SESSION_INFO));
        for (int i = 0; i < n; i++) {
            WTS_SESSION_INFO si = (WTS_SESSION_INFO)Marshal.PtrToStructure(new IntPtr(p.ToInt64() + i * sz), typeof(WTS_SESSION_INFO));
            ids[i] = si.SessionID;
        }
        WTSFreeMemory(p);
        return ids;
    }
    // "id|state|domain\\user|winstation|lastInputTicks|currentTicks", or "err:<code>".
    public static string SessionInfo(int sid) {
        IntPtr buf = IntPtr.Zero; int len = 0;
        if (WTSQuerySessionInformation(IntPtr.Zero, sid, 25, ref buf, ref len) == 0) { return "err:" + Marshal.GetLastWin32Error(); }
        try {
            WTSINFOEX x = (WTSINFOEX)Marshal.PtrToStructure(buf, typeof(WTSINFOEX));
            return string.Format("{0}|{1}|{2}\\{3}|{4}|{5}|{6}", x.Data.SessionId, x.Data.SessionState,
                x.Data.DomainName, x.Data.UserName, x.Data.WinStationName, x.Data.LastInputTime, x.Data.CurrentTime);
        } finally { WTSFreeMemory(buf); }
    }
    public static long LastInputIdleMs() {
        LASTINPUTINFO l = new LASTINPUTINFO();
        l.cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO));
        if (!GetLastInputInfo(ref l)) { return -1; }
        return (long)(GetTickCount() - l.dwTime);
    }
}
'@ -ErrorAction Stop
    $script:HaveNative = $true
} catch {
    $script:HaveNative = $false
    $script:NativeError = $_.Exception.Message
}

# ---------------------------------------------------------------------------------------------
# Plumbing.
# ---------------------------------------------------------------------------------------------
function Ensure-StatusDir {
    if (-not (Test-Path -LiteralPath $StatusDir)) {
        New-Item -ItemType Directory -Force -Path $StatusDir | Out-Null
    }
}

# Console only: for the read-only report modes, which must NOT append to the run log.
function Write-Out([string]$line) { Write-Host $line }

# Console AND the run log: one call per run, on every path out of Invoke-Reclaim.
function Write-LogLine([string]$line) {
    try { Ensure-StatusDir; Add-Content -LiteralPath $LOG -Value $line -Encoding UTF8 } catch { }
    if (-not $Quiet) { Write-Host $line }
}

function J-Num([object]$v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [bool]) { return 'null' }
    # MEASURED 2026-09-17 03:45Z: an integer-only test here wrote `"baseline_hours":null` and
    # `"hours_to_zero_children":null` for every DECIMAL field (and would have nulled a swap
    # percentage like 58.8). A number that cannot be written is worse than no field, because the
    # reader sees a measured-looking object with a hole in it. InvariantCulture so a host with a
    # decimal comma cannot emit `0,04`, which is not JSON.
    $s = [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0}', $v)
    if ($s -match '^-?\d+(\.\d+)?$') { return $s }
    return 'null'
}
function Iso-Utc([object]$v) {
    if ($null -eq $v) { return $null }
    if ($v -is [DateTime]) { return $v.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    if ($v -is [DateTimeOffset]) { return $v.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ssZ') }
    return [string]$v
}
function J-Str([object]$v) {
    if ($null -eq $v) { return 'null' }
    $s = [string]$v
    $s = $s.Replace('\', '\\').Replace('"', '\"').Replace("`r", ' ').Replace("`n", ' ')
    return '"' + $s + '"'
}
function Sum-Rss([object[]]$items) {
    $sum = [int64]0
    foreach ($i in @($items)) { if ($i) { $sum += [int64]$i.rss_kb } }
    return $sum
}
# Render a null as a word, never as an empty gap: a blank in a log line reads as if the field was
# measured and came back empty, which is the same class of mistake as a confident wrong number.
function N([object]$v) { if ($null -eq $v) { return 'none' } return [string]$v }

# A process holding a LISTENING socket is a service this node depends on, and our services are
# parentless BY DESIGN (the gate and the engine are started by a shell that then exits). MEASURED on
# ZABZ-YOGA 2026-09-17 03:43Z: the first report of this script classified the node's own phone-gate
# (pid 24148, `pythonw ... phone-gate.py --listen-port 3086`, recorded parent gone, age 12234 s) as a
# reclaimable orphan. It is the node's front door. So: a listener is never an orphan candidate.
function Get-ListenerPids {
    $pids = @()
    $source = 'unavailable'
    try {
        $pids = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique)
        $source = 'Get-NetTCPConnection'
    } catch {
        try {
            $pids = @(netstat.exe -ano 2>$null | Select-String -Pattern 'LISTENING' | ForEach-Object {
                $f = ($_.Line -split '\s+') | Where-Object { $_ }
                if ($f.Count -ge 5) { [int]$f[$f.Count - 1] }
            } | Sort-Object -Unique)
            $source = 'netstat -ano'
        } catch { }
    }
    return [pscustomobject]@{ pids = @($pids | Where-Object { $_ -and [int]$_ -gt 0 }); source = $source }
}

# ---------------------------------------------------------------------------------------------
# Measurement.
# ---------------------------------------------------------------------------------------------
function Get-Memory {
    $out = [ordered]@{ total_mib = $null; avail_mib = $null; avail_source = 'unmeasured'; swap_used_pct = $null; swap_source = 'unmeasured' }
    if ($script:HaveNative) {
        try {
            $ms = New-Object MeshHygieneNative+MEMORYSTATUSEX
            $ms.dwLength = [uint32][System.Runtime.InteropServices.Marshal]::SizeOf($ms)
            if ([MeshHygieneNative]::GlobalMemoryStatusEx([ref]$ms)) {
                $out.total_mib = [int64][math]::Round($ms.ullTotalPhys / 1MB)
                $out.avail_mib = [int64][math]::Round($ms.ullAvailPhys / 1MB)
                $out.avail_source = 'GlobalMemoryStatusEx.ullAvailPhys'
            }
        } catch { }
        try {
            $pi = New-Object MeshHygieneNative+PERFORMANCE_INFORMATION
            $pi.cb = [uint32][System.Runtime.InteropServices.Marshal]::SizeOf($pi)
            if ([MeshHygieneNative]::GetPerformanceInfo([ref]$pi, $pi.cb)) {
                $page = [int64]$pi.PageSize
                $commitLimit = [int64]$pi.CommitLimit * $page
                $commitTotal = [int64]$pi.CommitTotal * $page
                $physTotal   = [int64]$pi.PhysicalTotal * $page
                if ($commitLimit -gt $physTotal) {
                    $pct = (($commitTotal - $physTotal) / ($commitLimit - $physTotal)) * 100.0
                    if ($pct -lt 0) { $pct = 0.0 }
                    $out.swap_used_pct = [math]::Round($pct, 1)
                    $out.swap_source = 'GetPerformanceInfo(committed-vs-pagefile)'
                } else {
                    $out.swap_used_pct = 0.0
                    $out.swap_source = 'GetPerformanceInfo(no-pagefile)'
                }
            }
        } catch { }
    }
    if ($null -eq $out.avail_mib) {
        try {
            $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
            $out.total_mib = [int64][math]::Round([double]$os.TotalVisibleMemorySize / 1024)
            $out.avail_mib = [int64][math]::Round([double]$os.FreePhysicalMemory / 1024)
            $out.avail_source = 'Win32_OperatingSystem.FreePhysicalMemory(FALLBACK:' + $script:NativeError + ')'
        } catch { }
    }
    return $out
}

function Get-ProcessTable {
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop | ForEach-Object {
            $age = 0
            try { $age = [int64]((Get-Date) - $_.CreationDate).TotalSeconds } catch { $age = 0 }
            $ws = 0
            if ($_.WorkingSetSize) { $ws = [int64]$_.WorkingSetSize / 1KB }
            [pscustomobject]@{
                pid = [int]$_.ProcessId
                ppid = [int]$_.ParentProcessId
                name = [string]$_.Name
                cmd = [string]$_.CommandLine
                path = [string]$_.ExecutablePath
                rss_kb = $ws
                age_sec = $age
                session = [int]$_.SessionId
            }
        })
    } catch { return @() }
}

function Get-ConsoleState {
    $state = [ordered]@{
        present = $false; session = $null; user = ''; idle_seconds = $null
        idle_source = 'unmeasured'; sessions = ''
    }
    $all = @()
    $active = @()
    if ($script:HaveNative) {
        try {
            foreach ($sid in [MeshHygieneNative]::SessionIds()) {
                $info = [MeshHygieneNative]::SessionInfo($sid)
                if ($info -like 'err:*') { continue }
                $parts = $info -split '\|'
                $rec = [pscustomobject]@{
                    id = [int]$parts[0]; st = [int]$parts[1]; user = [string]$parts[2]
                    ws = [string]$parts[3]; lastInput = [long]$parts[4]; now = [long]$parts[5]
                }
                $all += $rec
                # WTS state 0 = Active: a user is logged on and the session is connected.
                if ($rec.st -eq 0 -and $rec.user -and $rec.user -notmatch '\\$') { $active += $rec }
            }
        } catch { }
    }
    $state.sessions = (@($all | ForEach-Object { "$($_.id):$($_.ws):$($_.user)" }) -join ', ')
    if (@($active).Count -eq 0) {
        # No interactive session at all: nobody to disturb. The headless worker-node case.
        $state.idle_source = 'no-active-session'
        return $state
    }
    $console = @($active | Where-Object { $_.ws -eq 'Console' })
    if (@($console).Count -gt 0) { $chosen = $console[0] } else { $chosen = $active[0] }
    $state.present = $true
    $state.session = $chosen.id
    $state.user = $chosen.user

    $mySession = $null
    try { $mySession = (Get-Process -Id $PID).SessionId } catch { }
    if ($null -ne $mySession -and $mySession -eq $chosen.id -and $script:HaveNative) {
        $idleMs = [MeshHygieneNative]::LastInputIdleMs()
        if ($idleMs -ge 0) {
            $state.idle_seconds = [int64][math]::Floor($idleMs / 1000)
            $state.idle_source = 'GetLastInputInfo(same-session)'
        }
    } elseif ($chosen.lastInput -gt 0 -and $chosen.now -gt 0) {
        $state.idle_seconds = [int64][math]::Floor(($chosen.now - $chosen.lastInput) / 1e7)
        $state.idle_source = 'WTSINFOEX.LastInputTime'
    } else {
        # MEASURED TRAP (Windows 11 build 26200, 2026-09-17, raw evidence in docs/mesh/85-hygiene.md):
        # WTSINFOEX_LEVEL1.LastInputTime and WTSINFO.LastInputTime are both 0 for a console session
        # on this build, so from another session (a SYSTEM scheduled task in session 0) the console's
        # idle time is NOT measurable. It is reported as unmeasured, and an unmeasured idle time is
        # never read as idle -- that is the point of gate 1.
        $state.idle_seconds = $null
        $state.idle_source = "unmeasurable(WTSINFOEX.LastInputTime=0; this process is in session " + $mySession + ", the console is session " + $chosen.id + ")"
    }
    return $state
}

function Get-WorkState {
    $proc = @($script:ProcessTable)
    $live = @{}
    foreach ($p in $proc) { $live[$p.pid] = $true }

    $dispatch = @()
    foreach ($p in $proc) {
        if ($p.cmd -match 'profile\s+headless') { $dispatch += $p.pid }
    }

    # Liveness is the lease's own heartbeat, NOT a pid guess: packages/plugin-health/lib/governor.js
    # says a pid check would either reap a live holder (data loss) or keep a dead one. `expiresAt` is
    # epoch MILLISECONDS. The holder pid is recorded for the reader only.
    $nowMs = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
    $held = @(); $holders = @(); $expired = 0; $corrupt = 0
    $leasesDir = Join-Path $GovernorRoot 'leases'
    $dirPresent = Test-Path -LiteralPath $leasesDir
    if ($dirPresent) {
        foreach ($f in @(Get-ChildItem -LiteralPath $leasesDir -Filter 'slot-*.lease' -ErrorAction SilentlyContinue)) {
            $doc = $null
            try { $doc = (Get-Content -LiteralPath $f.FullName -Raw -ErrorAction Stop | ConvertFrom-Json) } catch { $corrupt++; continue }
            if ($null -eq $doc) { $corrupt++; continue }
            $expires = 0
            try { $expires = [int64]$doc.expiresAt } catch { $expires = 0 }
            if ($expires -gt $nowMs) {
                $held += $f.Name
                $kind = '?'; $pidTxt = '?'; $note = ''
                if ($doc.kind) { $kind = [string]$doc.kind }
                if ($doc.pid) { $pidTxt = [string]$doc.pid }
                if ($doc.note) { $note = [string]$doc.note }
                $holders += ("pid $pidTxt $kind [$($f.BaseName)] expires in $([math]::Round(($expires - $nowMs) / 1000))s" + $(if ($note) { " -- $note" } else { '' }))
            } else {
                $expired++
            }
        }
    }
    return [ordered]@{
        dispatch_pids = @($dispatch)
        dispatch_count = @($dispatch).Count
        lease_held = @($held).Count
        lease_holders = (@($holders) -join '; ')
        lease_expired = $expired
        lease_corrupt = $corrupt
        lease_root = $GovernorRoot
        lease_dir_present = $dirPresent
    }
}

function Get-GateReading {
    $out = [ordered]@{
        url = $GateUrl; reachable = $false; error = ''; free_mib = $null; max_children = $null
        fleet = $null; node = ''; loops = $null; elapsed_ms = $null
    }
    try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch { }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $handler = New-Object System.Net.Http.HttpClientHandler
        $handler.UseProxy = $false
        $client = New-Object System.Net.Http.HttpClient($handler)
        $client.Timeout = [TimeSpan]::FromSeconds($GateTimeoutSec)
        try {
            $resp = $client.GetAsync($GateUrl).GetAwaiter().GetResult()
            $body = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            $sw.Stop(); $out.elapsed_ms = [int64]$sw.ElapsedMilliseconds
            if ([int]$resp.StatusCode -eq 200) {
                $doc = $body | ConvertFrom-Json
                $out.reachable = $true
                $out.node = [string]$doc.node
                $out.free_mib = $doc.mem.freeMiB
                $out.max_children = $doc.accepts.maxChildren
                $out.fleet = $doc.accepts.fleet
                if ($doc.agents) { $out.loops = $doc.agents.loopsRunning }
            } else {
                $out.error = "HTTP $([int]$resp.StatusCode)"
            }
        } finally { $client.Dispose(); $handler.Dispose() }
    } catch {
        $sw.Stop(); $out.elapsed_ms = [int64]$sw.ElapsedMilliseconds
        $inner = $_.Exception.InnerException
        if ($inner) { $out.error = "$($inner.GetType().Name): $($inner.Message)" } else { $out.error = $_.Exception.Message }
    }
    return $out
}

function Get-Capacity([object]$mem, [int]$inUse) {
    $cap = [ordered]@{
        formula = '71 s2.2 (memory + cores; disk and transport terms NOT included)'
        reserve_mib = $RESERVE_MIB; per_child_mib = $PER_CHILD_MIB; governor_in_use = $inUse
        memory_slots = $null; core_slots = $null; slots = $null; placeable_children = $null
        swap_halved = $false; physical_cores = $null
    }
    $physical = $null
    try { $physical = (Get-CimInstance Win32_Processor -ErrorAction Stop | Measure-Object -Property NumberOfCores -Sum).Sum } catch { }
    if (-not $physical -or $physical -le 0) {
        try { $physical = (Get-CimInstance Win32_Processor -ErrorAction Stop | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum } catch { }
    }
    $cap.physical_cores = $physical
    if ($null -ne $mem.avail_mib) {
        $memSlots = [math]::Floor(([double]$mem.avail_mib - $RESERVE_MIB) / $PER_CHILD_MIB)
        if ($memSlots -gt $MAX_SLOTS) { $memSlots = $MAX_SLOTS }
        $memSlots = $memSlots - $inUse
        $cap.memory_slots = [int64]$memSlots
    }
    if ($physical -and $physical -gt 0) { $cap.core_slots = [int64][math]::Floor($physical * $CORE_FRACTION) }
    if ($null -ne $cap.memory_slots) {
        $slots = [double]$cap.memory_slots
        if ($null -ne $cap.core_slots) { $slots = [math]::Min($slots, [double]$cap.core_slots) }
        if ($null -ne $mem.swap_used_pct -and [double]$mem.swap_used_pct -ge $SWAP_HALF_PCT) {
            $slots = [math]::Floor($slots / 2); $cap.swap_halved = $true
        }
        $cap.slots = [int64]$slots
        $cap.placeable_children = [int64]([math]::Max(0, $slots))
    }
    return $cap
}

# Class A: live processes in the console session whose own executable lies under a target prefix.
function Get-TargetProcesses([object]$console, [string[]]$targetList) {
    if (-not $console.present -or $null -eq $console.session) { return @() }
    $out = @()
    foreach ($p in $script:ProcessTable) {
        if ($p.session -ne $console.session) { continue }
        if (-not $p.path) { continue }                        # no path, no match -- fail closed
        $path = $p.path.ToLowerInvariant()
        foreach ($t in $targetList) {
            if (-not $t) { continue }
            if ($path.StartsWith($t.ToLowerInvariant())) {
                $out += [pscustomobject]@{ cls = 'target'; name = $p.name; pid = $p.pid; rss_kb = $p.rss_kb; path = $p.path; why = "path under $t" }
                break
            }
        }
    }
    return $out
}

# Class B: orphans (recorded parent gone) of our own tooling, older than the age floor, and NOT a
# listener (see Get-ListenerPids). Everything spared is recorded with its reason -- a policy that
# cannot show what it declined to touch is a policy nobody can audit.
function Get-Orphans([string]$pattern, [int]$minAgeSec) {
    $live = @{}
    foreach ($p in $script:ProcessTable) { $live[$p.pid] = $true }
    $re = $null
    try { $re = [regex]$pattern } catch { return @() }
    $listeners = @{}
    if ($null -eq $script:ListenerPids) { $script:ListenerPids = Get-ListenerPids }
    foreach ($lp in @($script:ListenerPids.pids)) { $listeners[[int]$lp] = $true }
    $out = @()
    foreach ($p in $script:ProcessTable) {
        if ($p.pid -eq $PID) { continue }
        if ($p.ppid -eq $PID) { continue }                    # never our own children
        if ($live.ContainsKey($p.ppid)) { continue }           # parent alive -> not an orphan
        if (-not $p.cmd) { continue }
        if ($p.cmd -match $ENGINE_PATTERN) { continue }        # the engine is never a candidate
        if (-not $re.IsMatch($p.cmd)) { continue }             # pattern FIRST: "not-yet" must mean
                                                               # "ours but too young", never "not ours"
        if ($p.age_sec -lt $minAgeSec) {
            # Matched our tooling, parent gone, but too young to be certainly abandoned. Recorded,
            # not silently dropped: a reader can then tell "nothing to reclaim" from "not yet".
            # MEASURED 2026-09-17 03:56Z: with this check ordered BEFORE the pattern test, every
            # young orphan on the machine -- including a human's ping and an unrelated sleeper --
            # was reported as "matches our tooling", which is exactly the kind of untrue log line
            # that makes a policy unfalsifiable.
            $script:Spared += ("$($p.pid) not-yet: parent is gone and it matches our tooling, but age $($p.age_sec)s < floor ${minAgeSec}s")
            continue
        }
        if ($listeners.ContainsKey($p.pid)) {
            $script:Spared += ("$($p.pid) spared: holds a LISTENING socket, so it is a service this node depends on (matched '$($p.cmd.Substring(0, [math]::Min(90, $p.cmd.Length)))')")
            continue
        }
        $out += [pscustomobject]@{ cls = 'orphan'; name = $p.name; pid = $p.pid; rss_kb = $p.rss_kb; path = $p.path; why = "orphan (recorded parent $($p.ppid) is gone), matches our tooling, age $($p.age_sec)s" }
    }
    return $out
}

# ---------------------------------------------------------------------------------------------
# Drift: this reading against the previous one, and against the oldest reading inside 24 h.
# ---------------------------------------------------------------------------------------------
function Get-PreviousReadings([int]$maxLines = 3000) {
    if (-not (Test-Path -LiteralPath $DECISIONS)) { return @() }
    $lines = @()
    try { $lines = @(Get-Content -LiteralPath $DECISIONS -Tail $maxLines -ErrorAction Stop) } catch { return @() }
    $records = @()
    foreach ($line in $lines) {
        if (-not $line) { continue }
        try { $records += ($line | ConvertFrom-Json) } catch { continue }
    }
    return $records
}

# A record's `at` comes back from ConvertFrom-Json as a DateTime, not the string that was written --
# and `[string]` on a UTC DateTime drops the Z, after which a naive parse reads it as LOCAL time.
# MEASURED 2026-09-17 03:44Z: that bug made `secs_since_prev` -14331 s (i.e. four hours in the
# future) between two readings 69 s apart. AssumeUniversal is the whole fix.
function Get-EpochSec([object]$v) {
    if ($null -eq $v) { return $null }
    if ($v -is [DateTimeOffset]) { return [int64]$v.ToUnixTimeSeconds() }
    if ($v -is [DateTime]) { return [int64]([DateTimeOffset]$v.ToUniversalTime()).ToUnixTimeSeconds() }
    try {
        $s = [string]$v
        if (-not $s) { return $null }
        return [int64]([DateTimeOffset]::Parse($s, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal)).ToUnixTimeSeconds()
    } catch { return $null }
}

function Get-Drift([object]$mem, [object]$capacity, [int64]$reclaimableKb) {
    $drift = [ordered]@{
        prev_at = $null; secs_since_prev = $null; d_avail_mib = $null; d_placeable = $null
        d_reclaimable_rss_kb = $null; baseline_at = $null; baseline_hours = $null
        d24_avail_mib = $null; avail_mib_per_hour = $null; d24_reclaimable_rss_kb = $null
        reclaimable_kb_per_hour = $null; hours_to_zero_children = $null; trend = 'no-history'
    }
    $history = @(Get-PreviousReadings)
    if (@($history).Count -eq 0) { return $drift }
    $prev = $history[$history.Count - 1]
    $drift.prev_at = Iso-Utc $prev.at
    $prevTime = Get-EpochSec $prev.at
    if ($null -ne $prevTime) {
        $drift.secs_since_prev = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $prevTime)
    }
    if ($null -ne $prev.memory.avail_mib -and $null -ne $mem.avail_mib) {
        $drift.d_avail_mib = [int64]($mem.avail_mib - [int64]$prev.memory.avail_mib)
    }
    if ($null -ne $prev.capacity.placeable_children -and $null -ne $capacity.placeable_children) {
        $drift.d_placeable = [int64]($capacity.placeable_children - [int64]$prev.capacity.placeable_children)
    }
    if ($null -ne $prev.reclaim.reclaimable_rss_kb) {
        $drift.d_reclaimable_rss_kb = [int64]($reclaimableKb - [int64]$prev.reclaim.reclaimable_rss_kb)
    }
    # The baseline is the OLDEST reading inside the last 24 h, so the rate is not one noisy 5-minute
    # step. If the history is younger than 24 h the window is what exists, and the record says how
    # many hours it covers.
    $baseline = $null
    $cutSec = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - (24 * 3600)
    # The OLDEST reading inside the window: the first one (the file is chronological) that is not
    # older than the cut. MEASURED 2026-09-17 03:45Z: without the `break` this walked to the NEWEST
    # record, so the baseline was the previous reading and the rate was never computed at all.
    foreach ($r in $history) {
        $t = Get-EpochSec $r.at
        if ($null -ne $t -and $t -ge $cutSec) { $baseline = $r; break }
    }
    if ($null -eq $baseline) { $baseline = $history[0] }
    if ($baseline -and (Get-EpochSec $baseline.at) -ne (Get-EpochSec $prev.at)) {
        $bt = Get-EpochSec $baseline.at
        if ($null -ne $bt) {
            $hours = ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $bt) / 3600.0
            if ($hours -gt 0) {
                $drift.baseline_at = Iso-Utc $baseline.at
                $drift.baseline_hours = [math]::Round($hours, 2)
                if ($null -ne $baseline.memory.avail_mib -and $null -ne $mem.avail_mib) {
                    $d = [double]($mem.avail_mib - [int64]$baseline.memory.avail_mib)
                    $drift.d24_avail_mib = [int64]$d
                    $drift.avail_mib_per_hour = [int64][math]::Round($d / $hours)
                }
                if ($null -ne $baseline.reclaim.reclaimable_rss_kb) {
                    $d2 = [double]($reclaimableKb - [int64]$baseline.reclaim.reclaimable_rss_kb)
                    $drift.d24_reclaimable_rss_kb = [int64]$d2
                    $drift.reclaimable_kb_per_hour = [int64][math]::Round($d2 / $hours)
                }
                if ($null -ne $drift.avail_mib_per_hour -and $drift.avail_mib_per_hour -lt 0 -and $null -ne $mem.avail_mib) {
                    $spare = [double]$mem.avail_mib - $RESERVE_MIB
                    if ($spare -gt 0) {
                        $drift.hours_to_zero_children = [math]::Round($spare / (-1.0 * $drift.avail_mib_per_hour), 1)
                    } else {
                        $drift.hours_to_zero_children = 0.0
                    }
                }
            }
        }
    }
    # "stable" needs a floor: on a 32 GiB machine a few hundred MiB between readings is weather.
    $threshold = 256
    if ($null -ne $drift.avail_mib_per_hour) {
        if ($drift.avail_mib_per_hour -le (-1 * $threshold)) { $drift.trend = 'shrinking' }
        elseif ($drift.avail_mib_per_hour -ge $threshold) { $drift.trend = 'growing' }
        else { $drift.trend = 'stable' }
    } else {
        $drift.trend = 'insufficient-window'
    }
    return $drift
}

# ---------------------------------------------------------------------------------------------
# THE RECLAIM CORE. One implementation, used by the shipped path and -- with the gates pre-set by
# -SelfTest -- by the regression test. It logs exactly once per call, on every path.
# ---------------------------------------------------------------------------------------------
function Invoke-Reclaim {
    param(
        [object]$Memory, [object]$Capacity, [object]$Console, [object]$Work, [object]$Gate,
        [string]$Mode, [string[]]$TargetList, [string]$TargetSource = 'default',
        [string]$OrphanPattern, [int]$MinAgeSec,
        [switch]$AssumeIdleForTest
    )
    $script:Spared = @()
    $targets = @(Get-TargetProcesses $Console $TargetList)
    $orphans = @(Get-Orphans $OrphanPattern $MinAgeSec)
    $reclaimableKb = (Sum-Rss $targets) + (Sum-Rss $orphans)

    $fails = @()
    if (-not $AssumeIdleForTest) {
        if ($Console.present) {
            if ($null -eq $Console.idle_seconds) { $fails += 'console_present_idle_unmeasurable' }
            elseif ([int64]$Console.idle_seconds -lt $IdleSeconds) { $fails += 'console_active' }
        }
        if ($Work.dispatch_count -gt 0) { $fails += 'dispatch_in_flight' }
        if ($Work.lease_held -gt 0) { $fails += 'lease_held' }
    }

    $drift = Get-Drift $Memory $Capacity $reclaimableKb
    $actedPids = @(); $escalatedPids = @(); $reclaimedKb = [int64]0; $actedNames = @()
    $outcome = 'declined'; $reason = ''

    if (@($fails).Count -gt 0) {
        $bits = @()
        if ($fails -contains 'console_active') { $bits += "console active: idle $($Console.idle_seconds)s < required ${IdleSeconds}s (user $($Console.user), session $($Console.session))" }
        if ($fails -contains 'console_present_idle_unmeasurable') { $bits += "a console session exists (session $($Console.session), user $($Console.user)) but its idle time is not readable from here: $($Console.idle_source)" }
        if ($fails -contains 'dispatch_in_flight') { $bits += "a dispatch is in flight: pids $((@($Work.dispatch_pids) -join ' '))" }
        if ($fails -contains 'lease_held') { $bits += "a governor lease is held: $($Work.lease_holders)" }
        $reason = ($bits -join '; ')
        if (-not $Reclaim) { $outcome = 'reported' }
    } elseif ((-not $Reclaim) -and (-not $AssumeIdleForTest)) {
        $outcome = 'reported'
        $reason = "report only (pass -Reclaim to act); all three gates pass; $($targets.Count) target(s) and $($orphans.Count) orphan(s) would be reclaimed"
    } elseif (($targets.Count + $orphans.Count) -eq 0) {
        $outcome = 'declined'
        $reason = 'nothing on the explicit target list and no orphan of our tooling -- already clean'
    } else {
        foreach ($c in $targets) {
            $p = Get-Process -Id $c.pid -ErrorAction SilentlyContinue
            if ($null -eq $p) { continue }
            $reclaimedKb += [int64]$c.rss_kb
            $actedNames += ("$($c.name)/$($c.pid)")
            try { [void]$p.CloseMainWindow() } catch { }
        }
        # A window that closed is not an application that quit -- that is the owner's original
        # complaint ("when I X things out they are still running"), so the ladder continues.
        $deadline = (Get-Date).AddSeconds($GraceSec)
        while ((Get-Date) -lt $deadline) {
            $alive = @($targets | Where-Object { Get-Process -Id $_.pid -ErrorAction SilentlyContinue })
            if (@($alive).Count -eq 0) { break }
            Start-Sleep -Milliseconds 500
        }
        foreach ($c in $targets) {
            if (Get-Process -Id $c.pid -ErrorAction SilentlyContinue) {
                if ($NoEscalate) { continue }
                try { Stop-Process -Id $c.pid -Force -ErrorAction Stop; $escalatedPids += $c.pid } catch { }
            }
        }
        foreach ($c in $orphans) {
            $reclaimedKb += [int64]$c.rss_kb
            $actedNames += ("$($c.name)/$($c.pid)")
            # Windows has no SIGTERM for an arbitrary process; an orphan of our own tooling has no
            # window to close, so TerminateProcess is the only request available. It is recorded.
            try { Stop-Process -Id $c.pid -Force -ErrorAction Stop } catch { }
        }
        foreach ($c in (@($targets) + @($orphans))) { if ($c.pid) { $actedPids += $c.pid } }
        Start-Sleep -Seconds 5
        $still = @(@($actedPids) | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        # RE-READ the process table for the after-measurement. MEASURED 2026-09-17 03:48Z: because the
        # table was cached from before the kill, the "after" number came back identical to the
        # "before" (179572 -> 179572) on a run that had by then killed both processes.
        $script:ProcessTable = @(Get-ProcessTable)
        $script:ListenerPids = $null
        $afterKb = (Sum-Rss @(Get-TargetProcesses $Console $TargetList)) + (Sum-Rss @(Get-Orphans $OrphanPattern $MinAgeSec))
        $outcome = 'acted'
        $reason = "reclaimed $($actedNames.Count) process(es) [$((@($actedNames) -join ','))]: $([math]::Round($reclaimedKb / 1024)) MiB resident let go; reclaimable_rss_kb $reclaimableKb -> $afterKb"
        if (@($escalatedPids).Count -gt 0) { $reason += "; escalated to force-kill for pids $((@($escalatedPids) -join ' '))" }
        if (@($still).Count -gt 0) { $reason += "; WARNING: $((@($still) -join ' ')) still alive after kill" }
    }

    # ONE LINE for a human, ONE JSON object for a machine, on EVERY path.
    $at = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    $idleTxt = 'unmeasured'; if ($null -ne $Console.idle_seconds) { $idleTxt = [string]$Console.idle_seconds }
    $sesTxt = 'none'; if ($null -ne $Console.session) { $sesTxt = [string]$Console.session }
    $line = "$at | $env:COMPUTERNAME | v$HYGIENE_VERSION | mode=$Mode | outcome=$outcome | " +
            "console=$($Console.user) session=$sesTxt idle_s=$idleTxt idle_required_s=$IdleSeconds idle_source=$($Console.idle_source) | " +
            "work dispatch=$($Work.dispatch_count) leases=$($Work.lease_held) loops=$(N $Gate.loops) | " +
            "mem avail=$($Memory.avail_mib)MiB swap=$($Memory.swap_used_pct)% | " +
            "placeable=$(N $Capacity.placeable_children) (memSlots=$(N $Capacity.memory_slots) coreSlots=$(N $Capacity.core_slots)) gate_free=$(N $Gate.free_mib)MiB gate_maxchildren=$(N $Gate.max_children) | " +
            "reclaimable_rss=$([int64]($reclaimableKb / 1024))MiB targets=$($targets.Count) orphans=$($orphans.Count) spared=$(@($script:Spared).Count) reclaimed=$([int64]($reclaimedKb / 1024))MiB | " +
            "drift prev_d=$(N $drift.d_avail_mib) MiB in $(N $drift.secs_since_prev) s rate=$(N $drift.avail_mib_per_hour) MiB/h over $(N $drift.baseline_hours) h placeable_d=$(N $drift.d_placeable) zero_children_in_h=$(N $drift.hours_to_zero_children) trend=$($drift.trend) | " +
            "reason=$reason"
    Write-LogLine $line

    $cand = ''
    if (($targets.Count + $orphans.Count) -gt 0) {
        $cand = (@($targets | ForEach-Object { "T:$($_.pid):$($_.why)" }) + @($orphans | ForEach-Object { "O:$($_.pid):$($_.why)" })) -join ' | '
    }
    $json = '{' +
        '"schema":' + $HYGIENE_SCHEMA + ',"tool":"mesh-hygiene","version":' + (J-Str $HYGIENE_VERSION) +
        ',"at":' + (J-Str $at) + ',"at_epoch":' + ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) + ',"host":' + (J-Str $env:COMPUTERNAME) +
        ',"platform":"windows","mode":' + (J-Str $Mode) + ',"outcome":' + (J-Str $outcome) + ',"reason":' + (J-Str $reason) +
        ',"node":' + $(if ($Gate.reachable -and $Gate.node) { (J-Str $Gate.node) } else { (J-Str $env:COMPUTERNAME) }) +
        ',"gates":{"failed":' + (J-Str (@($fails) -join ',')) + ',"idle_required_s":' + $IdleSeconds +
            ',"bypassed_for_selftest":' + ("$($AssumeIdleForTest.IsPresent)".ToLower()) + '},' +
        '"console":{"user":' + (J-Str $Console.user) + ',"session":' + (J-Num $Console.session) + ',"present":' + ("$($Console.present)".ToLower()) +
            ',"idle_seconds":' + (J-Num $Console.idle_seconds) + ',"idle_source":' + (J-Str $Console.idle_source) + ',"sessions":' + (J-Str $Console.sessions) + '},' +
        '"work":{"dispatch_in_flight":' + (J-Str (@($Work.dispatch_pids) -join ' ')) + ',"dispatch_count":' + $Work.dispatch_count +
            ',"leases_held":' + $Work.lease_held + ',"lease_holders":' + (J-Str $Work.lease_holders) +
            ',"lease_expired":' + $Work.lease_expired + ',"lease_root":' + (J-Str $Work.lease_root) +
            ',"lease_dir_present":' + ("$($Work.lease_dir_present)".ToLower()) +
            ',"agent_loops":' + (J-Num $Gate.loops) + '},' +
        '"memory":{"total_mib":' + (J-Num $Memory.total_mib) + ',"avail_mib":' + (J-Num $Memory.avail_mib) +
            ',"avail_source":' + (J-Str $Memory.avail_source) + ',"swap_used_pct":' + (J-Num $Memory.swap_used_pct) + ',"swap_source":' + (J-Str $Memory.swap_source) + '},' +
        '"capacity":{"formula":' + (J-Str $Capacity.formula) + ',"reserve_mib":' + $RESERVE_MIB + ',"per_child_mib":' + $PER_CHILD_MIB +
            ',"memory_slots":' + (J-Num $Capacity.memory_slots) + ',"core_slots":' + (J-Num $Capacity.core_slots) + ',"slots":' + (J-Num $Capacity.slots) +
            ',"placeable_children":' + (J-Num $Capacity.placeable_children) + ',"swap_halved":' + ("$($Capacity.swap_halved)".ToLower()) + '},' +
        '"gate":{"url":' + (J-Str $Gate.url) + ',"reachable":' + ("$($Gate.reachable)".ToLower()) + ',"error":' + (J-Str $Gate.error) +
            ',"free_mib":' + (J-Num $Gate.free_mib) + ',"max_children":' + (J-Num $Gate.max_children) + ',"fleet":' + (J-Num $Gate.fleet) +
            ',"elapsed_ms":' + (J-Num $Gate.elapsed_ms) + '},' +
        '"reclaim":{"targets_live":' + $targets.Count + ',"targets_rss_kb":' + (Sum-Rss $targets) +
            ',"orphans_live":' + $orphans.Count + ',"orphans_rss_kb":' + (Sum-Rss $orphans) +
            ',"reclaimable_rss_kb":' + $reclaimableKb + ',"reclaimed_rss_kb":' + $reclaimedKb +
            ',"acted_pids":' + (J-Str (@($actedPids) -join ' ')) + ',"escalated_pids":' + (J-Str (@($escalatedPids) -join ' ')) +
            ',"target_list_source":' + (J-Str $TargetSource) +
            ',"orphan_patterns":' + (J-Str $OrphanPattern) + ',"candidates":' + (J-Str $cand) +
            ',"listener_protection":' + (J-Str (N $script:ListenerPids.source)) +
            ',"spared":' + (J-Str (@($script:Spared) -join ' | ')) + '},' +
        '"drift":{"prev_at":' + (J-Str $drift.prev_at) + ',"secs_since_prev":' + (J-Num $drift.secs_since_prev) +
            ',"d_avail_mib":' + (J-Num $drift.d_avail_mib) + ',"d_placeable":' + (J-Num $drift.d_placeable) +
            ',"d_reclaimable_rss_kb":' + (J-Num $drift.d_reclaimable_rss_kb) +
            ',"baseline_at":' + (J-Str $drift.baseline_at) + ',"baseline_hours":' + (J-Num $drift.baseline_hours) +
            ',"d24_avail_mib":' + (J-Num $drift.d24_avail_mib) + ',"avail_mib_per_hour":' + (J-Num $drift.avail_mib_per_hour) +
            ',"d24_reclaimable_rss_kb":' + (J-Num $drift.d24_reclaimable_rss_kb) + ',"reclaimable_kb_per_hour":' + (J-Num $drift.reclaimable_kb_per_hour) +
            ',"hours_to_zero_children":' + (J-Num $drift.hours_to_zero_children) + ',"trend":' + (J-Str $drift.trend) + '},' +
        '"status_dir":' + (J-Str $StatusDir) + ',"log":' + (J-Str $LOG) + '}'
    try {
        Ensure-StatusDir
        Add-Content -LiteralPath $DECISIONS -Value $json -Encoding UTF8
        $tmp = "$LATEST.tmp"
        Set-Content -LiteralPath $tmp -Value $json -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination $LATEST -Force
    } catch { Write-Out "mesh-hygiene: could not write the record: $($_.Exception.Message)" }

    return [pscustomobject]@{
        outcome = $outcome; reason = $reason; targets = $targets.Count; orphans = $orphans.Count
        reclaimable_kb = $reclaimableKb; reclaimed_kb = $reclaimedKb; acted = @($actedPids)
        escalated = @($escalatedPids); failed_gates = @($fails); drift = $drift
    }
}

# ---------------------------------------------------------------------------------------------
# Read-only modes
# ---------------------------------------------------------------------------------------------
function Show-Drift([int]$count) {
    $history = @(Get-PreviousReadings)
    Write-Out "mesh-hygiene $HYGIENE_VERSION -- DRIFT REPORT (read-only): $($history.Count) record(s) in $DECISIONS"
    if (@($history).Count -eq 0) {
        Write-Out "no readings yet: run the script once in any mode to start the series"
        return 0
    }
    $tail = @($history | Select-Object -Last $count)
    Write-Out ("{0,-21} {1,-9} {2,10} {3,8} {4,6} {5,14} {6,3} {7,3} {8,-19} {9}" -f 'at(UTC)', 'outcome', 'availMiB', 'd(avail)', 'place', 'reclaimableKB', 'T', 'O', 'trend', 'reason')
    $prev = $null
    foreach ($r in $tail) {
        $d = '-'
        if ($prev -and $null -ne $prev.memory.avail_mib -and $null -ne $r.memory.avail_mib) { $d = [string]([int64]$r.memory.avail_mib - [int64]$prev.memory.avail_mib) }
        $reason = [string]$r.reason
        if ($reason.Length -gt 76) { $reason = $reason.Substring(0, 76) + '...' }
        Write-Out ("{0,-21} {1,-9} {2,10} {3,8} {4,6} {5,14} {6,3} {7,3} {8,-19} {9}" -f `
            (Iso-Utc $r.at), [string]$r.outcome, [string]$r.memory.avail_mib, $d,
            [string]$r.capacity.placeable_children, [string]$r.reclaim.reclaimable_rss_kb,
            [string]$r.reclaim.targets_live, [string]$r.reclaim.orphans_live, [string]$r.drift.trend, $reason)
        $prev = $r
    }
    $lastRec = $tail[$tail.Count - 1]
    Write-Out "latest: trend=$($lastRec.drift.trend) avail_per_hour=$(N $lastRec.drift.avail_mib_per_hour) MiB/h over $(N $lastRec.drift.baseline_hours) h; placeable=$(N $lastRec.capacity.placeable_children); zero-children-in=$(N $lastRec.drift.hours_to_zero_children) h"
    Write-Out "A node is drifting when avail_per_hour is negative for hours and zero-children-in is finite, even while placeable is still greater than zero."
    Write-Out "Files a human reads: $LATEST (latest), $DECISIONS (full history), $LOG (one line per run)"
    return 0
}

function Get-DefaultNodes {
    return @(
        [pscustomobject]@{ node = 'zabz-yoga-1';     alias = 'laptop-ts';    kind = 'windows' },
        [pscustomobject]@{ node = 'zabz-tech';       alias = 'zabz-tech-ts'; kind = 'windows' },
        [pscustomobject]@{ node = 'secratary';       alias = 'secratary-ts'; kind = 'posix'   },
        [pscustomobject]@{ node = 'zabz-tech-linux'; alias = 'linux-pc-ts';  kind = 'posix'   },
        [pscustomobject]@{ node = 'lakewooechsmini'; alias = 'mac-mini-ts';  kind = 'posix'   }
    )
}

function Show-Collect {
    Write-Out "mesh-hygiene $HYGIENE_VERSION -- DRIFT ACROSS NODES (read-only; each node's own latest record, read over ssh)"
    $rows = @()
    foreach ($n in (Get-DefaultNodes)) {
        if (@($Nodes).Count -gt 0 -and ($Nodes -notcontains $n.node) -and ($Nodes -notcontains $n.alias)) { continue }
        if ($n.kind -eq 'windows') {
            $remote = 'cmd /c type "%USERPROFILE%\.dsh-sync-status\mesh-hygiene.json" 2>NUL'
        } else {
            $remote = 'cat /var/log/mesh-hygiene.json 2>/dev/null || cat $HOME/.dsh-sync-status/mesh-hygiene.json 2>/dev/null'
        }
        $raw = ''
        $rc = 0
        try { $raw = (ssh -o BatchMode=yes -o ConnectTimeout=15 $n.alias $remote 2>&1 | Out-String).Trim(); $rc = $LASTEXITCODE } catch { $raw = ''; $rc = -1 }
        $doc = $null
        if ($raw -and $raw.StartsWith('{')) { try { $doc = $raw | ConvertFrom-Json } catch { $doc = $null } }
        if ($null -eq $doc) {
            $rows += [pscustomobject]@{ node = $n.node; at = '-'; avail = '-'; place = '-'; reclaim = '-'; drift = "no record (ssh exit $rc via $($n.alias): either the node has no record, or this host cannot reach/authenticate to it)" }
            continue
        }
        $rows += [pscustomobject]@{
            node = $n.node; at = (Iso-Utc $doc.at); avail = [string]$doc.memory.avail_mib
            place = [string]$doc.capacity.placeable_children; reclaim = [string]$doc.reclaim.reclaimable_rss_kb
            drift = "trend=$($doc.drift.trend) rate=$($doc.drift.avail_mib_per_hour)MiB/h zero_in=$($doc.drift.hours_to_zero_children)h"
        }
    }
    Write-Out ("{0,-18} {1,-21} {2,9} {3,6} {4,12} {5}" -f 'node', 'at(UTC)', 'availMiB', 'place', 'reclaimKB', 'drift')
    foreach ($r in $rows) {
        Write-Out ("{0,-18} {1,-21} {2,9} {3,6} {4,12} {5}" -f $r.node, $r.at, $r.avail, $r.place, $r.reclaim, $r.drift)
    }
    Write-Out "A node whose trend is 'shrinking' with a finite zero_in is the node to look at before the broker stops choosing it."
    return 0
}

function Invoke-SelfTest {
    # The scratch directory must NOT contain a string from the orphan pattern list, or the SPARED hog
    # would match through its own path. MEASURED 2026-09-17 03:48Z: with the directory named
    # `mesh-hygiene-selftest-*`, the shipped pattern `mesh-hygiene` matched BOTH hogs and the
    # "spared" case failed -- the pattern is matched against the whole command line, which includes
    # the path of the script being run. `hygiene-selftest-*` contains no pattern.
    $scratch = Join-Path $env:TEMP ('hygiene-selftest-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    $hogA = Join-Path $scratch 'mesh-hygiene-hog-a.ps1'
    $hogB = Join-Path $scratch 'unlisted-hog-b.ps1'
    $body = '$x = New-Object byte[] 64MB; Start-Sleep -Seconds 900'
    Set-Content -LiteralPath $hogA -Value $body -Encoding UTF8
    Set-Content -LiteralPath $hogB -Value $body -Encoding UTF8
    $pwshPath = (Get-Process -Id $PID).Path
    Write-Out "SELF-TEST (read-only against the machine; it spawns and then cleans up ITS OWN two hogs)"
    Write-Out "  scratch      : $scratch"
    Write-Out "  hog A        : mesh-hygiene-hog-a.ps1   -- matches the SHIPPED orphan pattern (mesh-hygiene)"
    Write-Out "  hog B        : unlisted-hog-b.ps1       -- matches nothing; it MUST survive"
    Write-Out "  pattern used : the shipped default ($DEFAULT_ORPHAN_PATTERNS)"
    Write-Out "  gates        : pre-set to their PASS values for this test, so the matching/kill/accounting"
    Write-Out "                 code below is the shipped code on a machine that is NOT idle"
    # The two hogs are spawned by an intermediate process that exits at once, so each hog's RECORDED
    # parent is a dead pid -- exactly the orphan rule's condition.
    foreach ($f in @($hogA, $hogB)) {
        $inner = "Start-Process -FilePath '$pwshPath' -ArgumentList @('-NoProfile','-File','$f') -WindowStyle Hidden; Start-Sleep -Milliseconds 500"
        # NOT `-Wait`: on Windows PowerShell's -Wait waits for the process AND ITS DESCENDANTS, so it
        # would sit on the 900-second hog and the self-test would never return (measured 2026-09-17
        # 03:46Z: the first version of this test had to be killed at 120 s). WaitForExit on the
        # intermediate alone is the whole fix, and the intermediate is the only thing that must be
        # gone for the hog's recorded parent to be a dead pid.
        try {
            $mid = Start-Process -FilePath $pwshPath -ArgumentList @('-NoProfile', '-Command', $inner) -WindowStyle Hidden -PassThru
            [void]$mid.WaitForExit(8000)
        } catch { }
    }
    Start-Sleep -Seconds 4
    $script:ProcessTable = @(Get-ProcessTable)
    $hogPids = @($script:ProcessTable | Where-Object { $_.cmd -match 'mesh-hygiene-hog-a\.ps1|unlisted-hog-b\.ps1' })
    Write-Out ("  hog processes found before reclaim: " + (@($hogPids).Count) + "  (pids " + ((@($hogPids) | ForEach-Object { $_.pid }) -join ' ') + ")")
    # The self-test writes its own record into the scratch dir, never into the production series.
    $savedStatus = $StatusDir; $savedLog = $LOG; $savedDecisions = $DECISIONS; $savedLatest = $LATEST
    $StatusDir = $scratch; $LOG = Join-Path $scratch 'mesh-hygiene.log'; $DECISIONS = Join-Path $scratch 'mesh-hygiene.jsonl'; $LATEST = Join-Path $scratch 'mesh-hygiene.json'
    $mem = Get-Memory
    $res = Invoke-Reclaim -Memory $mem -Capacity (Get-Capacity $mem 0) -Console (Get-ConsoleState) `
        -Work (Get-WorkState) -Gate ([ordered]@{ loops = $null; url = ''; reachable = $false; error = ''; free_mib = $null; max_children = $null; fleet = $null; elapsed_ms = $null }) `
        -Mode 'selftest' -TargetList @() -TargetSource 'default-shipped' -OrphanPattern $DEFAULT_ORPHAN_PATTERNS -MinAgeSec 5 -AssumeIdleForTest
    $StatusDir = $savedStatus; $LOG = $savedLog; $DECISIONS = $savedDecisions; $LATEST = $savedLatest
    Start-Sleep -Seconds 2
    $fresh = @(Get-ProcessTable)
    $aliveA = @($fresh | Where-Object { $_.cmd -match 'mesh-hygiene-hog-a\.ps1' })
    $aliveB = @($fresh | Where-Object { $_.cmd -match 'unlisted-hog-b\.ps1' })
    $rc = 0
    Write-Out ("  A mesh-hygiene-hog (matches shipped pattern) alive now: " + (@($aliveA).Count) + "  -> " + $(if (@($aliveA).Count -eq 0) { 'PASS' } else { 'FAIL' }))
    if (@($aliveA).Count -ne 0) { $rc = 1 }
    Write-Out ("  B unlisted-hog      (matches nothing)       alive now: " + (@($aliveB).Count) + "  -> " + $(if (@($aliveB).Count -ge 1) { 'PASS (spared)' } else { 'FAIL' }))
    if (@($aliveB).Count -lt 1) { $rc = 1 }
    Write-Out ("  reclaim: outcome=$($res.outcome) reclaimable_kb=$($res.reclaimable_kb) reclaimed_kb=$($res.reclaimed_kb) acted_pids=" + ((@($res.acted) -join ' ')))
    Write-Out "  the reclaim log line this test wrote (scratch, not the production series):"
    try { foreach ($l in @(Get-Content -LiteralPath (Join-Path $scratch 'mesh-hygiene.log') -ErrorAction Stop)) { Write-Out ("    " + $l) } } catch { }
    foreach ($p in @($hogPids)) { try { Stop-Process -Id $p.pid -Force -ErrorAction SilentlyContinue } catch { } }
    foreach ($p in @($aliveB)) { try { Stop-Process -Id $p.pid -Force -ErrorAction SilentlyContinue } catch { } }
    Write-Out $(if ($rc -eq 0) { 'SELF-TEST: ALL CASES PASSED' } else { 'SELF-TEST: FAILED' })
    return $rc
}

# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------
$mode = 'report'
if ($Reclaim) { $mode = 'reclaim' }
if ($SelfTest) { $mode = 'selftest' }

try {
    if ($Drift) { exit (Show-Drift $Last) }
    if ($Collect) { exit (Show-Collect) }
    if ($SelfTest) { exit (Invoke-SelfTest) }

    # -Targets REPLACES the default list. Bound-empty (`-Targets @()`) means "no class A at all",
    # which is how the orphan rule is exercised on a machine where a human's browser is open.
    $targetList = @($Targets | Where-Object { $_ })
    $targetSource = 'override'
    if (-not $PSBoundParameters.ContainsKey('Targets')) { $targetList = @(Get-DefaultTargets); $targetSource = 'default' }
    if (@($targetList).Count -eq 0) { $targetSource = "$targetSource(empty: class A disabled)" }
    $orphanPattern = $OrphanPatterns
    if (-not $orphanPattern) { $orphanPattern = $DEFAULT_ORPHAN_PATTERNS }

    $script:ProcessTable = @(Get-ProcessTable)
    if (@($script:ProcessTable).Count -eq 0) {
        Write-LogLine "$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')) | $env:COMPUTERNAME | v$HYGIENE_VERSION | mode=$mode | outcome=error | reason=the process table is empty, so nothing can be identified: refusing to act"
        exit 3
    }
    $memory = Get-Memory
    $console = Get-ConsoleState
    $work = Get-WorkState
    $gate = Get-GateReading
    $capacity = Get-Capacity $memory $work.lease_held
    $res = Invoke-Reclaim -Memory $memory -Capacity $capacity -Console $console -Work $work -Gate $gate `
        -Mode $mode -TargetList $targetList -TargetSource $targetSource -OrphanPattern $orphanPattern -MinAgeSec $MinOrphanAgeSeconds
    exit 0
} catch {
    Write-LogLine "$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')) | $env:COMPUTERNAME | v$HYGIENE_VERSION | mode=$mode | outcome=error | reason=unhandled: $($_.Exception.Message)"
    exit 3
}
