# plugin-health process sampler — one snapshot of the OS process table, as JSON.
#
# WHY THIS EXISTS AS THE HARNESS'S OWN CHILD
# Node has no built-in way to read another process's parent, thread count or
# working set, and Windows has no /proc. The alternatives were rejected
# deliberately: a CIM/WMI query (`Get-CimInstance Win32_Process`) costs hundreds
# of milliseconds and would be the heaviest thing this plugin does; a native
# addon is a build dependency on every machine. This script uses only what
# Windows already ships — `Get-Process` for memory, threads and handles, plus
# kernel32 `CreateToolhelp32Snapshot` for the parent-PID tree that `Get-Process`
# does not expose — and is spawned by a detached, `stdio: 'ignore'` child, so
# the engine's event loop never waits for it and never reads its stdout. The
# snapshot lands in a file the engine reads when someone asks for health.
#
# WHAT IT CANNOT SEE, SAID OUT LOUD
# 1. There is no command line anywhere in this output. `Get-Process` has none,
#    and `Win32_Process.CommandLine` needs WMI. So a `node.exe` row says only
#    that it is node; the engine classifies by parent PID and image path, and
#    nothing else is claimed. A bonus of that constraint: no process's command
#    line (which can carry tokens) is ever written to disk by this script.
# 2. `Get-Process -Name node` misses a node process owned by another user
#    account (access denied). `-IncludeUserName` needs elevation, so it is not
#    used and the gap is reported instead: `nodeProcessesInvisible` counts
#    node.exe rows from the kernel snapshot that `Get-Process` could not give
#    memory for.
# 3. A process that exits between the two enumerations appears in the tree with
#    no memory row, or in neither. Counts are a snapshot, not a transaction.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [Parameter(Mandatory = $true)][int]$EnginePid,
    [int]$ConhostPid = 0
)

$ErrorActionPreference = 'SilentlyContinue'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public sealed class DshTreeRow {
    public int pid;
    public int ppid;
    public int threads;
    public string name;
}

public static class DshTree {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct PROCESSENTRY32W {
        public uint dwSize;
        public uint cntUsage;
        public uint th32ProcessID;
        public IntPtr th32DefaultHeapID;
        public uint th32ModuleID;
        public uint cntThreads;
        public uint th32ParentProcessID;
        public int pcPriClassBase;
        public uint dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string szExeFile;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool Process32FirstW(IntPtr snapshot, ref PROCESSENTRY32W entry);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool Process32NextW(IntPtr snapshot, ref PROCESSENTRY32W entry);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr handle);

    public static DshTreeRow[] List() {
        var rows = new List<DshTreeRow>(600);
        IntPtr snap = CreateToolhelp32Snapshot(0x00000002, 0);
        if (snap == new IntPtr(-1)) return rows.ToArray();
        try {
            var entry = new PROCESSENTRY32W();
            entry.dwSize = (uint)Marshal.SizeOf(typeof(PROCESSENTRY32W));
            if (!Process32FirstW(snap, ref entry)) return rows.ToArray();
            do {
                var row = new DshTreeRow();
                row.pid = (int)entry.th32ProcessID;
                row.ppid = (int)entry.th32ParentProcessID;
                row.threads = (int)entry.cntThreads;
                row.name = entry.szExeFile;
                if (row.pid > 0) rows.Add(row);
            } while (Process32NextW(snap, ref entry));
        } finally {
            CloseHandle(snap);
        }
        return rows.ToArray();
    }
}

public static class DshMemory {
    [StructLayout(LayoutKind.Sequential)]
    struct MEMORYSTATUSEX {
        public uint dwLength;
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX status);

    /** totalPhys, availPhys, commitLimit, commitAvailable, memoryLoadPercent. */
    public static long[] Read() {
        var status = new MEMORYSTATUSEX();
        status.dwLength = (uint)Marshal.SizeOf(typeof(MEMORYSTATUSEX));
        if (!GlobalMemoryStatusEx(ref status)) return new long[] { 0, 0, 0, 0, 0 };
        return new long[] {
            (long)status.ullTotalPhys,
            (long)status.ullAvailPhys,
            (long)status.ullTotalPageFile,
            (long)status.ullAvailPageFile,
            (long)status.dwMemoryLoad
        };
    }
}
'@

# One enumeration pass. `Get-Process` and the kernel snapshot are taken a few
# hundred microseconds apart, not atomically — see the header.
$live = @(Get-Process -ErrorAction SilentlyContinue)
$byPid = [System.Collections.Generic.Dictionary[int, object]]::new()
foreach ($process in $live) {
    $byPid[$process.Id] = $process
}

$rows = [System.Collections.Generic.List[object]]::new()
$threadTotal = 0
$handleTotal = 0
$invisibleNodes = 0
$resident = 0
foreach ($entry in [DshTree]::List()) {
    $resident += 1
    $threadTotal += $entry.threads
    $process = $null
    if ($byPid.ContainsKey($entry.pid)) { $process = $byPid[$entry.pid] }
    $isNode = $entry.name -match '^(node|node\.exe)$'
    if ($isNode -and $null -eq $process) { $invisibleNodes += 1 }
    $workingSet = 0
    $privateBytes = 0
    $handleCount = -1
    if ($null -ne $process) {
        $workingSet = [long]$process.WorkingSet64
        $privateBytes = [long]$process.PrivateMemorySize64
        $handleCount = [int]$process.Handles
        $handleTotal += [int]$process.Handles
    }
    $rows.Add([pscustomobject]@{
        pid             = $entry.pid
        ppid            = $entry.ppid
        threads         = $entry.threads
        workingSetBytes = $workingSet
        privateBytes    = $privateBytes
        handles         = $handleCount
        name            = $entry.name
        hasMemory       = ($null -ne $process)
    })
}

# Commit charge is the number that explains a freeze on this machine: when commit
# exceeds physical RAM the pagefile is in use and every process pays for it.
# `Get-CimInstance Win32_OperatingSystem` carries it, but measured here on
# ZABZ-YOGA 2026-09-16 it costs **286 ms** against **10 ms** for the same numbers
# from `GlobalMemoryStatusEx` — and it spawns a WMI worker into the bargain. A
# sampler that runs every few seconds must not be the heaviest thing on the box,
# so the P/Invoke wins. (Physical totals agree between the two: 31.6 GB total,
# 13.9 GB available.)
$memory = [DshMemory]::Read()
$totalPhys = $memory[0]
$availPhys = $memory[1]
$commitLimit = $memory[2]
$commitFree = $memory[3]
$memoryLoad = $memory[4]

$snapshot = [pscustomobject]@{
    at             = [DateTime]::UtcNow.ToString('o')
    writerPid      = $PID
    enginePid      = $EnginePid
    conhostPid     = $ConhostPid
    processorCount = [System.Environment]::ProcessorCount
    os             = [System.Environment]::OSVersion.VersionString
    system         = [pscustomobject]@{
        totalPhysBytes       = $totalPhys
        availPhysBytes       = $availPhys
        commitLimitBytes     = $commitLimit
        commitAvailableBytes = $commitFree
        memoryLoadPercent    = $memoryLoad
    }
    totals         = [pscustomobject]@{
        processes     = $resident
        threads       = $threadTotal
        handles       = $handleTotal
        nodeInvisible = $invisibleNodes
    }
    processes      = $rows
}

// Atomic replace: the engine may poll this file at any moment and must never
// read a half-written document. `Move-Item -Force` on the same volume replaces
// the destination in one step.
$json = $snapshot | ConvertTo-Json -Depth 5 -Compress
$temp = "$Out.tmp-$PID"
[System.IO.File]::WriteAllText($temp, $json, (New-Object System.Text.UTF8Encoding($false)))
Move-Item -LiteralPath $temp -Destination $Out -Force
