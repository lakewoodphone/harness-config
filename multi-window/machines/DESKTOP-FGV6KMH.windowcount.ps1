# Count the harness app windows that are really open on this machine. Prints one integer.
#
# Kept as its own file because the alternative is a PowerShell one-liner nested inside cmd.exe quoting,
# and that is the kind of thing that works once and then silently stops.
#
# IT MUST COUNT WHAT dshw COUNTS. First version of this file counted msedge processes carrying `--app=`
# without `--type=`, and on 2026-09-15 that reported **2 windows when there was 1**: Edge keeps a second
# root process alive during a profile handoff, both carrying the same `--app=` URL. dshw's own
# `Get-WindowCount` counts **distinct app URLs within the profile root**, and this is now the same rule
# -- because this file is what the desktop launcher's "is it already open?" decision reads, and a
# disagreement between the two would either duplicate her window or refuse to open one.
#
# Exit 0 always; the number goes to stdout, or 0 when nothing can be determined.
$ErrorActionPreference = 'Continue'

$profileRoot = ''
$cfg = Join-Path $PSScriptRoot ("{0}.windows.json" -f $env:COMPUTERNAME)
if (-not (Test-Path $cfg)) { $cfg = Join-Path (Split-Path -Parent $PSScriptRoot) 'windows.json' }
try {
    if (Test-Path $cfg) {
        $j = Get-Content -Raw -LiteralPath $cfg | ConvertFrom-Json
        if ($j.browser -and $j.browser.profileRoot) { $profileRoot = $j.browser.profileRoot }
    }
} catch { }

try {
    $procs = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue
    $urls = @($procs | Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains('--app=') -and
            (-not $_.CommandLine.Contains('--type=')) -and
            ((-not $profileRoot) -or $_.CommandLine.Contains($profileRoot))
        } | ForEach-Object {
            if ($_.CommandLine -match '--app=(\S+)') { $Matches[1] }
        } | Select-Object -Unique)
    Write-Output $urls.Count
} catch {
    Write-Output 0
}
