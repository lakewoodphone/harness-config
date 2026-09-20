# Window geometry for dshw: place a new window on the screen the owner is on, and remember
# the layout he has arranged. Dot-sourced by dshw.ps1 after $Cfg and $StateDir exist.
#
# The owner's requirement, verbatim: pressing + "should open a new window on the same screen I
# clicked it on instead of going back to the default screen every time and then I have to drag
# it". So placement is computed from the pointer's monitor at launch time, not from a grid in
# windows.json; `dshw save-layout` is how an arrangement he likes becomes the remembered one.

Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue

$dshWinSource = Join-Path $StateDir 'DshWin.cs'
if (-not (Test-Path $dshWinSource)) {
    $cs = @(
        'using System;',
        'using System.Runtime.InteropServices;',
        'public static class DshWin {',
        '    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }',
        '    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }',
        '    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();',
        '    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);',
        '    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);',
        '}'
    )
    [System.IO.File]::WriteAllText($dshWinSource, ($cs -join [Environment]::NewLine), (New-Object System.Text.UTF8Encoding($false)))
}
if (-not ('DshWin' -as [type])) { Add-Type -Path $dshWinSource -ErrorAction SilentlyContinue }

# The monitor that contains the pointer right now.
function Get-CursorMonitor {
    $screens = [System.Windows.Forms.Screen]::AllScreens
    $pt = New-Object DshWin+POINT
    if ([DshWin]::GetCursorPos([ref]$pt)) {
        foreach ($s in $screens) {
            $b = $s.Bounds
            if ($pt.X -ge $b.X -and $pt.X -lt ($b.X + $b.Width) -and $pt.Y -ge $b.Y -and $pt.Y -lt ($b.Y + $b.Height)) { return $s }
        }
    }
    return ($screens | Where-Object { $_.Primary } | Select-Object -First 1)
}

# The live rectangle of the window carrying a given browser profile.
function Get-LiveWindowRect([string]$profile) {
    $profDir = Join-Path $Cfg.browser.profileRoot $profile
    $proc = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and $_.CommandLine.Contains($profDir) -and
            $_.CommandLine.Contains('--app=') -and -not $_.CommandLine.Contains('--type=')
        } | Select-Object -First 1
    if (-not $proc) { return $null }
    $r = New-Object DshWin+RECT
    if ([DshWin]::GetWindowRect([IntPtr]$proc.ProcessId, [ref]$r)) {
        return [pscustomobject]@{ left = $r.Left; top = $r.Top; width = ($r.Right - $r.Left); height = ($r.Bottom - $r.Top) }
    }
    return $null
}

# Where the next window goes: on the pointer's monitor, cascaded off a window that is already
# there so the two do not land exactly on top of each other, and clamped to the work area.
function Get-PlacementForNewWindow {
    $size = '700,440'
    foreach ($slot in (Get-Slots)) { if ($slot.size) { $size = $slot.size; break } }
    $parts = $size -split ','
    $w = [int]$parts[0]
    $h = [int]$parts[1]

    $monitor = Get-CursorMonitor
    $wa = $monitor.WorkingArea

    $left = $wa.X + 40
    $top = $wa.Y + 40
    foreach ($slot in (Get-Slots)) {
        $rect = Get-LiveWindowRect $slot.profile
        if ($rect) { $left = $rect.left + 32; $top = $rect.top + 32; break }
    }
    if (($left + $w) -gt ($wa.X + $wa.Width)) { $left = $wa.X + 40 }
    if (($top + $h) -gt ($wa.Y + $wa.Height)) { $top = $wa.Y + 40 }
    return [pscustomobject]@{ position = "$left,$top"; size = "$w,$h"; monitor = $monitor.DeviceName }
}

# Remember where the windows actually are, so a relaunch puts them back there.
function Invoke-SaveLayout {
    $file = Join-Path $PSScriptRoot 'windows.json'
    $raw = Get-Content -Raw -LiteralPath $file | ConvertFrom-Json
    $changed = 0
    for ($i = 0; $i -lt $raw.windows.Count; $i++) {
        $slot = $raw.windows[$i]
        $rect = Get-LiveWindowRect $slot.profile
        if (-not $rect) { continue }
        $newPos = "$($rect.left),$($rect.top)"
        $newSize = "$($rect.width),$($rect.height)"
        if ($slot.position -ne $newPos -or $slot.size -ne $newSize) {
            $slot.position = $newPos
            $slot.size = $newSize
            $changed++
            Write-Host ("  {0}: {1} {2}" -f $slot.profile, $newPos, $newSize) -ForegroundColor Green
        }
    }
    if ($changed -gt 0) {
        ($raw | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $file -Encoding utf8
        Write-Host ("save-layout: remembered {0} window(s)" -f $changed)
    } else {
        Write-Host 'save-layout: nothing moved'
    }
}
