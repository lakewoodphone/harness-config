# windowstate.ps1 -- what the launcher's "is her assistant already open?" question SHOULD ask.
#
# ASCII ONLY, DELIBERATELY. The desktop launcher reaches this file through Windows PowerShell 5.1
# (`powershell -NoProfile -File`), which reads a BOM-less UTF-8 file as ANSI and corrupts any
# non-ASCII byte. An em-dash in a script pushed to this machine already broke a remote parse once
# (2026-09-28). Keep this file 7-bit clean.
#
# WHY THIS FILE EXISTS -- measured 2026-10-13 on DESKTOP-FGV6KMH.
# `DESKTOP-FGV6KMH.windowcount.ps1` answers "how many msedge processes carry an --app= URL under the
# profile root". That is a statement about PROCESSES, and the launcher treated it as a statement
# about whether she HAS A WORKING ASSISTANT. Those are different questions, and the difference is
# the whole of her complaint ("it keeps stopping to work"):
#
#   * the engine regenerates its launch token on every start, and a window's URL carries the token
#     it was born with. A window opened before a restart therefore holds a DEAD token and renders
#     "dsh web authentication required" -- a broken window;
#   * a profile cookie can also expire (30 days), which produces the same bare 401 page;
#   * `windowcount` still counts that window. So the shortcut took the "already open" branch, opened
#     nothing, raised nothing, and she was left looking at a window that did not work, with the one
#     action that would have fixed it (a fresh window) refused by design.
#
# dshw.ps1 already solved this for its OWN callers -- `Resolve-WindowUrl` probes a recorded token and
# will not hand out a dead one (its comment: "the token is now PROBED and not trusted", measured
# 2026-09-18). The launcher's own window count never got that treatment. This file gives it one.
#
# WHAT IT DOES
#   For every distinct msedge `--app=` URL under this machine's profile root, extract the token and
#   make a REAL HTTP request to the engine with it. Any HTTP status other than 401 counts as live
#   (dshw accepts "any status is acceptance" for the same reason: the engine answers 303 for an
#   already-cookied browser). 401 is the dead-token page. A refused connection means no engine.
#
# USAGE
#   windowstate.ps1                 -> JSON on one line
#   windowstate.ps1 -LiveCount      -> just the number of LIVE windows (integer), for a .cmd
#   windowstate.ps1 -DeadCount      -> just the number of DEAD windows
#   windowstate.ps1 -Pids           -> space-separated pids of live windows
#
# Exit 0 always; the answer goes to stdout. A count of 0 on a failure is honest only when paired
# with the JSON form, which says WHY.
[CmdletBinding()]
param(
    [switch]$LiveCount,
    [switch]$DeadCount,
    [switch]$Pids,
    [switch]$Summary
)
$ErrorActionPreference = 'Continue'

# ---- configuration: this machine's own file, never a guess -------------------------------
$profileRoot = ''
$port = 3099
$cfg = Join-Path $PSScriptRoot ("{0}.windows.json" -f $env:COMPUTERNAME)
if (-not (Test-Path -LiteralPath $cfg)) { $cfg = Join-Path (Split-Path -Parent $PSScriptRoot) 'windows.json' }
try {
    if (Test-Path -LiteralPath $cfg) {
        $j = Get-Content -Raw -LiteralPath $cfg | ConvertFrom-Json
        if ($j.browser -and $j.browser.profileRoot) { $profileRoot = $j.browser.profileRoot }
        if ($j.primaryPort) { $port = [int]$j.primaryPort }
    }
} catch { }

# ---- the probe ----------------------------------------------------------------------------
# Raw sockets rather than Invoke-WebRequest: the status code of a 401 is the ANSWER here, and
# Invoke-WebRequest turns it into a terminating exception whose shape differs between PowerShell
# versions. This form is the one already proven in dshw.ps1's Test-EngineAlive.
function Probe-Token([int]$Port, [string]$Token) {
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $connect.Wait(4000) -or -not $client.Connected) { return 'UNREACHABLE' }
        $stream = $client.GetStream()
        $stream.ReadTimeout = 8000
        $stream.WriteTimeout = 4000
        $path = if ([string]::IsNullOrEmpty($Token)) { '/' } else { '/?token=' + $Token }
        $req = "GET $path HTTP/1.1`r`nHost: 127.0.0.1:$Port`r`nConnection: close`r`n`r`n"
        $bytes = [Text.Encoding]::ASCII.GetBytes($req)
        $stream.Write($bytes, 0, $bytes.Length)
        $buffer = New-Object byte[] 128
        $read = $stream.Read($buffer, 0, $buffer.Length)
        if ($read -le 0) { return 'UNREACHABLE' }
        $head = [Text.Encoding]::ASCII.GetString($buffer, 0, $read)
        if ($head -notmatch '^HTTP/\d\.\d\s+(\d{3})') { return 'UNREACHABLE' }
        $code = [int]$Matches[1]
        if ($code -eq 401) { return 'DEAD' }   # the dead-token / expired-cookie page
        return 'LIVE'                          # 200, 303, anything else non-401
    } catch {
        return 'UNREACHABLE'
    } finally {
        if ($client) { try { $client.Dispose() } catch { } }
    }
}

# ---- enumerate the app windows -------------------------------------------------------------
$rows = @()
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue
    $seen = @{}
    foreach ($p in $procs) {
        if (-not $p.CommandLine) { continue }
        if (-not $p.CommandLine.Contains('--app=')) { continue }
        if ($p.CommandLine.Contains('--type=')) { continue }
        if ($profileRoot -and (-not $p.CommandLine.Contains($profileRoot))) { continue }
        if ($p.CommandLine -notmatch '--app=(\S+)') { continue }
        $url = $Matches[1]
        if ($seen.ContainsKey($url)) { continue }
        $seen[$url] = $true
        $token = ''
        if ($url -match 'token=([^&\s]+)') { $token = $Matches[1] }
        $state = Probe-Token -Port $port -Token $token
        $rows += [pscustomobject]@{
            pid   = [int]$p.ProcessId
            url   = $url
            state = $state
        }
    }
} catch { }

$live = @($rows | Where-Object { $_.state -eq 'LIVE' })
$dead = @($rows | Where-Object { $_.state -eq 'DEAD' })
$unreachable = @($rows | Where-Object { $_.state -eq 'UNREACHABLE' })

if ($LiveCount) { Write-Output $live.Count; exit 0 }
if ($DeadCount) { Write-Output $dead.Count; exit 0 }
if ($Pids)      { Write-Output (($live | ForEach-Object { $_.pid }) -join ' '); exit 0 }

# ONE line: "total live dead unreachable". The click path needs all four and a .cmd pays a whole
# PowerShell start-up per invocation, so asking four times would cost seconds on a loaded box.
if ($Summary) {
    Write-Output ("{0} {1} {2} {3}" -f $rows.Count, $live.Count, $dead.Count, $unreachable.Count)
    exit 0
}

$out = [pscustomobject]@{
    port        = $port
    profileRoot = $profileRoot
    total       = $rows.Count
    live        = $live.Count
    dead        = $dead.Count
    unreachable = $unreachable.Count
    windows     = $rows
}
Write-Output ($out | ConvertTo-Json -Depth 5 -Compress)
exit 0
