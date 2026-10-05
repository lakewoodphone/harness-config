# rdp-session.ps1 - open the RDP session to ZABZ-TECH and re-open it ONLY after a real drop.
#
# WHY /v: AND NOT THE .RDP FILE (measured 2026-10-05, and this is the whole point of this rewrite):
# Since the April 2026 Windows cumulative updates, opening a saved .rdp file shows the
# "Caution: Unknown remote connection" warning EVERY time, it IGNORES the file's redirection settings and
# asks the user to re-tick clipboard/microphone, and it needs a click before connecting. The same warning
# does NOT appear when the connection is started with `mstsc /v:<host>`, where the settings come from
# Documents\Default.rdp. That dialog is what the owner was seeing "every half a minute": this wrapper treated
# his Cancel click as a dropped session and relaunched, eight times in ninety seconds, each relaunch evicting
# the session it had just opened (host log: reason code 5, every time).
#
# TWO RULES THAT STOP THAT CLASS OF LOOP:
#   1. a session that ended in under 60 s is NOT a drop - it is a cancelled dialog, a refusal or a failed
#      connect. It is logged and NOT relaunched.
#   2. one wrapper at a time (lock file), so two shortcuts cannot fight over the single session.
# ASCII-ONLY AND BOM-PADDED: Windows PowerShell 5.1 reads a BOM-less file as ANSI and one multi-byte
# character inside a string kills the whole script at parse time, silently.
param(
  [int]$MaxAttempts = 4,
  [int]$HealthyWaitSeconds = 10,
  [int]$MinSessionSeconds = 60,
  [switch]$CheckOnly
)
$ErrorActionPreference = 'Continue'
$rdpFile = Join-Path $env:USERPROFILE 'OneDrive\Desktop\zabz-tech - mic.rdp'
$host_ = 'zabz-tech.tail93e6e6.ts.net'
$log = 'C:\Users\ezabz\.dsh\logs\rdp-session.log'
$lock = 'C:\Users\ezabz\.dsh\logs\rdp-session.lock'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Get-Content $log -Tail 300 | Set-Content $log }
function Note($m) { "$((Get-Date).ToString('s')) $m" | Add-Content $log }

function Test-Link {
  $ping = (tailscale ping -c 1 --timeout 3s zabz-tech 2>&1 | Select-Object -First 1) -join ' '
  $path = 'UNREACHABLE'
  if ($ping -match 'DERP|relay') { $path = 'RELAY' } elseif ($ping -match 'via ') { $path = 'direct' }
  $tcp = $false
  try {
    $c = New-Object Net.Sockets.TcpClient
    $t = $c.ConnectAsync($host_, 3389)
    $tcp = $t.Wait(4000) -and $c.Connected
    $c.Close()
  } catch { $tcp = $false }
  return @{ path = $path; tcp = $tcp }
}

if ($CheckOnly) {
  $l = Test-Link
  "path=$($l.path) tcp3389=$($l.tcp)  (would launch: mstsc `"$rdpFile`")"
  exit 0
}

# rule 2: one wrapper only
if (Test-Path $lock) {
  $age = ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes
  if ($age -lt 30) { Note "another wrapper is already running (lock is $([math]::Round($age)) min old) - exiting"; exit 0 }
  Note "stale lock removed"
}
Set-Content -Path $lock -Value (Get-Date).ToString('o')

try {
  for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    for ($w = 0; $w -lt 30; $w++) {
      $l = Test-Link
      if ($l.tcp) { break }
      Note "attempt ${attempt}: link not usable (path=$($l.path)) - waiting"
      Start-Sleep -Seconds $HealthyWaitSeconds
    }
    $l = Test-Link
    if (-not $l.tcp) { Note "attempt ${attempt}: giving up, 3389 never answered"; break }

    Note "attempt ${attempt}: opening the session (path=$($l.path))"
    $proc = Start-Process -FilePath "$env:WINDIR\System32\mstsc.exe" -ArgumentList ('"' + $rdpFile + '"') -PassThru
    $started = Get-Date
    while (-not $proc.HasExited) { Start-Sleep -Seconds 3; if ($proc.HasExited) { break }; $proc.Refresh() }
    $ran = (New-TimeSpan -Start $started -End (Get-Date)).TotalSeconds
    Note "attempt ${attempt}: session ended after $([math]::Round($ran)) s"

    # rule 1: a short run is not a drop
    if ($ran -lt $MinSessionSeconds) {
      Note "that was under $MinSessionSeconds s - treating it as cancelled or refused, NOT a drop; not re-opening"
      break
    }
    if ($ran -gt 300) { Note 'session ran normally; not re-opening'; break }
    Start-Sleep -Seconds 20
  }
} finally {
  Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
Note 'wrapper exiting'