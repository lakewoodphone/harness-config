# Get-NodeSample.ps1 -- WORKSTREAM E sampler.
# Runs ON the node being observed (shipped as base64 -EncodedCommand over ssh).
# Emits one CSV line per tick on stdout via [Console]::Out (AutoFlush=true), so the
# desktop side sees samples live through the ssh redirect file.
#
# Injected by the caller before this body: $DurationSec, $FloorGiB, $IntervalMs
#
# Output grammar (all byte counts are raw bytes):
#   RESOLVE,enginePid=<pid>,resolveMs=<ms>
#   S,<tick>,<elapsedSec>,<commitBytes>,<availPhysBytes>,<procCount>,<enginePid>,<engineRss>,<enginePrivate>,<engineAlive>
#   ABORT_MEM_FLOOR,<availPhysBytes>
#   END,<elapsedSec>,<ticks>

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Continue'

if (-not $DurationSec) { $DurationSec = 60 }
if (-not $FloorGiB)    { $FloorGiB    = 0 }
if (-not $IntervalMs)  { $IntervalMs  = 1000 }

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct MEMORYSTATUSEX {
    public uint  dwLength;
    public uint  dwMemoryLoad;
    public ulong ullTotalPhys;
    public ulong ullAvailPhys;
    public ulong ullTotalPageFile;
    public ulong ullAvailPageFile;
    public ulong ullTotalVirtual;
    public ulong ullAvailVirtual;
    public ulong ullAvailExtendedVirtual;
}

public static class MemApi {
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);
}
"@

function Read-Mem {
    # sizeof(MEMORYSTATUSEX) is 64 on both x86 and x64 (3 x uint + 8 x ulong - 4 pad = 64)
    $m = New-Object MEMORYSTATUSEX
    $m.dwLength = [uint32]64
    $ok = [MemApi]::GlobalMemoryStatusEx([ref]$m)
    if (-not $ok) { return $null }
    return $m
}

# --- resolve the DSH engine process once (the node.exe serving bin.js web --port 3099)
$enginePid = 0
$resolveSw = [Diagnostics.Stopwatch]::StartNew()
try {
    $cand = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -like '*bin.js web*3099*' } |
            Select-Object -First 1
    if ($cand) { $enginePid = [int]$cand.ProcessId }
} catch { }
$resolveSw.Stop()
[Console]::Out.WriteLine('RESOLVE,enginePid=' + $enginePid + ',resolveMs=' + [math]::Round($resolveSw.Elapsed.TotalMilliseconds,0))
[Console]::Out.Flush()

# --- sampling loop
$sw    = [Diagnostics.Stopwatch]::StartNew()
$tick  = 0
$floor = 0
if ($FloorGiB -gt 0) { $floor = [uint64]($FloorGiB * 1073741824) }

while ($sw.Elapsed.TotalSeconds -lt $DurationSec) {
    $tick++

    $m      = Read-Mem
    $commit = [uint64]0
    $avail  = [uint64]0
    if ($m -ne $null) {
        $commit = [uint64]$m.ullTotalPageFile - [uint64]$m.ullAvailPageFile
        $avail  = [uint64]$m.ullAvailPhys
    }

    $procCount = @(Get-Process -ErrorAction SilentlyContinue).Count

    $rss = -1; $priv = -1; $alive = 0
    if ($enginePid -gt 0) {
        $ep = Get-Process -Id $enginePid -ErrorAction SilentlyContinue
        if ($ep) { $rss = [int64]$ep.WorkingSet64; $priv = [int64]$ep.PrivateMemorySize64; $alive = 1 }
    }

    $line = 'S,' + $tick + ',' + [math]::Round($sw.Elapsed.TotalSeconds,2) + ',' +
            $commit + ',' + $avail + ',' + $procCount + ',' + $enginePid + ',' +
            $rss + ',' + $priv + ',' + $alive
    [Console]::Out.WriteLine($line)
    [Console]::Out.Flush()

    if ($floor -gt 0 -and $avail -gt 0 -and $avail -lt $floor) {
        [Console]::Out.WriteLine('ABORT_MEM_FLOOR,' + $avail)
        [Console]::Out.Flush()
        break
    }

    Start-Sleep -Milliseconds $IntervalMs
}

[Console]::Out.WriteLine('END,' + [math]::Round($sw.Elapsed.TotalSeconds,2) + ',' + $tick)
[Console]::Out.Flush()

