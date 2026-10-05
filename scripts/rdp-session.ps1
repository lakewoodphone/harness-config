# rdp-session.ps1 - open the RDP session to ZABZ-TECH and RE-OPEN it when it drops.
#
# WHY: the drops that keep costing the owner clicks are not the RDP client's fault. Measured 2026-10-05:
#   * the tailnet path between the Yoga (carrier-grade NAT) and the office blips (`path=UNREACHABLE` at
#     02:54:13) and each blip ends the session;
#   * the host's RemoteFX graphics pipeline logged `encountered an error (0x80004005)` at 02:39:18 and
#     02:49:25, exactly where sessions died, while running the AVC444 video codec.
# mstsc's own autoreconnect covers a short blip. Past that it gives up and shows a MODAL dialog that needs a
# click, which is where "it took a few tries" comes from. This wrapper removes the click: it re-opens the
# session when the link is healthy again, and it closes that dialog itself when the link is down (so it is
# certain the dialog is a failure, not the normal "connecting" window, which carries the same title).
#
# ASCII-ONLY AND BOM-PADDED ON PURPOSE: Windows PowerShell 5.1 reads a BOM-less file as ANSI, and one
# multi-byte character inside a string kills the whole script at parse time - silently behind a hidden
# window. That is how the previous tool died.
param(
  [int]$MaxAttempts = 8,
  [int]$HealthyWaitSeconds = 10,
  [switch]$CheckOnly
)
$ErrorActionPreference = 'Continue'
$rdp = Join-Path $env:USERPROFILE 'OneDrive\Desktop\zabz-tech - mic.rdp'
$log = Join-Path $env:USERPROFILE '.dsh\logs\rdp-session.log'
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
    $t = $c.ConnectAsync('zabz-tech.tail93e6e6.ts.net', 3389)
    $tcp = $t.Wait(4000) -and $c.Connected
    $c.Close()
  } catch { $tcp = $false }
  return @{ path = $path; tcp = $tcp }
}

if ($CheckOnly) {
  $l = Test-Link
  "path=$($l.path) tcp3389=$($l.tcp)"
  exit 0
}

if (-not (Test-Path $rdp)) { Note "no rdp file at $rdp"; exit 1 }

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
  # 1. wait for a link that can actually carry a session
  for ($w = 0; $w -lt 30; $w++) {
    $l = Test-Link
    if ($l.tcp) { break }
    Note "attempt ${attempt}: link not usable (path=$($l.path)) - waiting"
    Start-Sleep -Seconds $HealthyWaitSeconds
  }
  $l = Test-Link
  if (-not $l.tcp) { Note "attempt ${attempt}: giving up, 3389 never answered"; break }

  # 2. open the session and babysit it
  Note "attempt ${attempt}: opening the session (path=$($l.path))"
  $proc = Start-Process -FilePath "$env:WINDIR\System32\mstsc.exe" -ArgumentList ('"' + $rdp + '"') -PassThru
  $started = Get-Date
  while (-not $proc.HasExited) {
    Start-Sleep -Seconds 3
    if ($proc.HasExited) { break }
    $proc.Refresh()
    # The failure dialog and the "connecting" window share the title, so only close it when the link is
    # DOWN - then it can only be a failure, and closing it is what saves the owner a click.
    if ($proc.MainWindowTitle -eq 'Remote Desktop Connection') {
      $now = Test-Link
      if (-not $now.tcp) {
        Note "closing the failure dialog (link is down: path=$($now.path))"
        [void]$proc.CloseMainWindow()
        Start-Sleep -Seconds 4
      }
    }
  }
  $ran = (New-TimeSpan -Start $started -End (Get-Date)).TotalSeconds
  Note ("attempt ${attempt}: session ended after " + [math]::Round($ran) + " s")
  # A session that ran a while and was then closed is the owner finishing, not a drop.
  if ($ran -gt 300) { Note 'session ran normally; not re-opening'; break }
  Start-Sleep -Seconds 5
}
Note 'wrapper exiting'
