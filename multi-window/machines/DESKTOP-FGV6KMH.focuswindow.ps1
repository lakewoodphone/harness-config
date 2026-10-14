# focuswindow.ps1 -- bring her assistant window to the front, or say it is not there.
#
# ASCII ONLY, DELIBERATELY. The desktop launcher reaches this file from a .cmd that runs Windows
# PowerShell 5.1 (`powershell -NoProfile -File`), which reads a BOM-less UTF-8 file as ANSI and
# corrupts non-ASCII bytes. A non-ASCII byte in a script pushed to this machine already broke a
# remote parse once (2026-09-28). Keep this file 7-bit clean.
#
# WHY THIS EXISTS -- the missing half of "open my assistant".
#
# Measured 2026-10-13. The click path was:
#   shortcut -> DESKTOP-FGV6KMH.open.cmd -> windowcount.ps1
#     if count != 0  ->  launch.cmd ensure ; echo "already open" ; exit
#     if count == 0  ->  schtasks /run "Yocheved DSH Window"  (opens one)
#
# So when a window already existed the click ran the ENGINE check, printed one line, and stopped.
# It never brought the window forward, and nothing in the estate could: dshw's dispatch has 24
# verbs (up down restart status windows new ensure restore plan open stop logs health watchdog
# tasks-export tasks-import autostart doctor help) and NOT ONE of them focuses, raises, restores or
# reloads an existing window.
#
# The consequence is the complaint itself. Edge `--app` windows have no tab strip and no address
# bar; on a box with 44+ msedge processes, a window that is minimised or simply behind other
# windows is findable only if you already know it is there. Double-clicking the shortcut produced a
# three-second console flash and nothing else -- which is exactly "it keeps stopping to work".
#
# THIS FILE DOES NOT COUNT, KILL OR LAUNCH ANYTHING. It only raises a window that already exists
# and belongs to THIS machine's assistant profile. That narrowness is the point: killing or
# relaunching is a decision that belongs to the caller, and on this box `msedge.exe` is also her
# normal browser.
#
# USAGE
#   focuswindow.ps1            -> raises the first assistant window it finds; prints "raised <pid>"
#                                 or "none" when there is nothing to raise. Exit 0 / 1.
#   focuswindow.ps1 -Quiet     -> no output; exit code only (0 raised, 1 nothing found)
#   focuswindow.ps1 -List      -> prints one line per assistant window: "<pid> <minimized|shown>"
#
# Exit: 0 a window was raised (or -List found some), 1 nothing was found, 2 the machine's own
# config could not be read (a refusal, not a negative).
[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$List
)
$ErrorActionPreference = 'Continue'

# ---- this machine's own configuration, never a guess --------------------------------------
$profileRoot = ''
$cfg = Join-Path $PSScriptRoot ("{0}.windows.json" -f $env:COMPUTERNAME)
if (-not (Test-Path -LiteralPath $cfg)) { $cfg = Join-Path (Split-Path -Parent $PSScriptRoot) 'windows.json' }
if (-not (Test-Path -LiteralPath $cfg)) { if (-not $Quiet) { Write-Output 'noconfig' }; exit 2 }
try {
    $j = Get-Content -Raw -LiteralPath $cfg | ConvertFrom-Json
    if ($j.browser -and $j.browser.profileRoot) { $profileRoot = $j.browser.profileRoot }
} catch { if (-not $Quiet) { Write-Output 'noconfig' }; exit 2 }

# ---- Win32, for raising a window ----------------------------------------------------------
# Written as a here-string so the type is declared once. If the type already exists in this
# process (a caller dot-sourcing us twice) Add-Type throws; that is not a failure, so it is caught.
$signature = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class DshWin {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextLengthW(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
try { Add-Type -TypeDefinition $signature -ErrorAction Stop } catch { }

# ---- which processes are assistant app windows ---------------------------------------------
# Root processes only: an `--app=` URL with no `--type=` is the browser process, and the browser
# process owns the top-level HWND. Renderer children also match `--app=` and do not own a window.
$pids = @()
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if (-not $p.CommandLine) { continue }
        if (-not $p.CommandLine.Contains('--app=')) { continue }
        if ($p.CommandLine.Contains('--type=')) { continue }
        if ($profileRoot -and (-not $p.CommandLine.Contains($profileRoot))) { continue }
        $pids += [int]$p.ProcessId
    }
} catch { }

if ($pids.Count -eq 0) { if (-not $Quiet) { Write-Output 'none' }; exit 1 }

# ---- find the top-level HWND each of those pids owns ----------------------------------------
$found = @()
$callback = [DshWin+EnumWindowsProc]{
    param([IntPtr]$hwnd, [IntPtr]$lparam)
    $wpid = 0
    [void][DshWin]::GetWindowThreadProcessId($hwnd, [ref]$wpid)
    if ($pids -contains [int]$wpid) {
        $len = [DshWin]::GetWindowTextLengthW($hwnd)
        # A Chromium app window has a real title. Frameless/hidden helper windows have none, and
        # raising one would do nothing visible.
        if ($len -gt 0) {
            $script:found += [pscustomobject]@{
                pid       = [int]$wpid
                hwnd      = $hwnd
                minimized = [DshWin]::IsIconic($hwnd)
                visible   = [DshWin]::IsWindowVisible($hwnd)
            }
        }
    }
    return $true
}
[void][DshWin]::EnumWindows($callback, [IntPtr]::Zero)

if ($found.Count -eq 0) { if (-not $Quiet) { Write-Output 'none' }; exit 1 }

if ($List) {
    foreach ($f in $found) {
        $state = if ($f.minimized) { 'minimized' } elseif ($f.visible) { 'shown' } else { 'hidden' }
        Write-Output ("{0} {1}" -f $f.pid, $state)
    }
    exit 0
}

# ---- raise it -------------------------------------------------------------------------------
# SW_RESTORE (9) un-minimises; SetForegroundWindow asks for the front. ShowWindowAsync is used as
# well because it does not block on the target's message pump -- an Edge window that is busy
# repainting would otherwise stall the click.
$ok = $false
foreach ($f in $found) {
    try {
        [void][DshWin]::ShowWindowAsync($f.hwnd, 9)
        [void][DshWin]::ShowWindow($f.hwnd, 9)
        [void][DshWin]::BringWindowToTop($f.hwnd)
        [void][DshWin]::SetForegroundWindow($f.hwnd)
        $ok = $true
    } catch { }
}
if ($ok) { if (-not $Quiet) { Write-Output ("raised " + $found[0].pid) }; exit 0 }
if (-not $Quiet) { Write-Output 'none' }
exit 1
