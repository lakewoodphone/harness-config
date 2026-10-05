# rdp-link-status.ps1 - is the link to ZABZ-TECH usable RIGHT NOW, before you try to connect?
#
# ASCII-ONLY ON PURPOSE. Windows PowerShell 5.1 reads a file with no BOM as ANSI, and a multi-byte
# character such as an em dash then decodes into a stray quote that closes a string and kills the whole
# script at PARSE time - silently, because the shortcut runs it in a window that closes. That is exactly how
# the first version of this tool died: no output, a flash, nothing in the log. Do not put non-ASCII
# punctuation in this file, and keep the try/catch + final Read-Host so a future failure is READ, not seen
# as a flicker.
$ErrorActionPreference = 'Continue'
$target = 'zabz-tech.tail93e6e6.ts.net'
$log = "$env:USERPROFILE\.dsh\logs\link-probe.log"
try {
  New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

  $ping = (tailscale ping -c 1 --timeout 3s zabz-tech 2>&1 | Select-Object -First 1) -join ' '
  $path = 'UNREACHABLE'
  if ($ping -match 'DERP|relay') { $path = 'RELAY (slower, most stable)' }
  elseif ($ping -match 'via ') { $path = 'direct' }
  $rtt = '-'
  if ($ping -match 'in (\d+(\.\d+)?)ms') { $rtt = $Matches[1] + ' ms' }

  $sw = [Diagnostics.Stopwatch]::StartNew()
  $tcp = $false
  try {
    $c = New-Object Net.Sockets.TcpClient
    $t = $c.ConnectAsync($target, 3389)
    $tcp = $t.Wait(4000) -and $c.Connected
    $c.Close()
  } catch { $tcp = $false }
  $sw.Stop()

  # SESSION OWNERSHIP, because that is what decides whether your apps survive.
  # A client Windows allows ONE interactive session per user. If the console sits at a lock screen (a session
  # with no user on it), RDP can create a NEW session instead of taking over the one your apps are in, and the
  # prompt it shows offers to SIGN OUT the other session - which is a logoff (reason code 12), not a disconnect,
  # and it closes every running app. Measured 2026-10-05: the owner clicked yes and lost his apps that way.
  $sessions = ''
  $sessionNote = 'could not read the desktop session list'
  try {
    $sessions = (ssh -o BatchMode=yes -o ConnectTimeout=8 100.85.153.96 'qwinsta' 2>&1) -join ' '
    if ($sessions -match 'console\s+(ezabz)\s') { $sessionNote = 'the console session is YOURS - a new RDP login takes over that same session, so your apps survive' }
    elseif ($sessions -match 'console\s+\d+\s+(Conn|Active)') { $sessionNote = 'the console is sitting at a LOCK SCREEN (no user on it). Sign in once at the PC (or through Chrome Remote Desktop) and both doors then share one session with your apps; if a prompt offers to close another session, DISCONNECT it (close the window) rather than signing it out' }
    elseif ($sessions -match 'ezabz') { $sessionNote = 'you already have a session on the desktop - reconnecting lands in it and your apps keep running' }
  } catch { }

  $verdict = 'Link looks good.'
  if (-not $tcp) { $verdict = 'NOT reachable on 3389 right now - retrying will not help, wait a minute.' }
  elseif ($path -like 'RELAY*') { $verdict = 'Reachable over the relay: slower, but the most stable mode.' }

  # Log FIRST, so "did it even run" is always answerable afterwards.
  "$((Get-Date).ToString('s')) path=$path rtt=$rtt tcp3389=$tcp tcp_ms=$($sw.ElapsedMilliseconds)" | Add-Content $log
  if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Get-Content $log -Tail 300 | Set-Content $log }

  Write-Host ''
  Write-Host ('  ZABZ-TECH link status   ' + (Get-Date).ToString('HH:mm:ss')) -ForegroundColor Cyan
  Write-Host ('    tailnet path : ' + $path)
  Write-Host ('    round trip   : ' + $rtt)
  if ($tcp) { Write-Host ('    RDP port 3389: reachable in ' + $sw.ElapsedMilliseconds + ' ms') }
  else { Write-Host '    RDP port 3389: NO ANSWER' -ForegroundColor Red }
  Write-Host ''
  Write-Host ('    ' + $verdict) -ForegroundColor Yellow
  Write-Host ''
  Write-Host ('    sessions : ' + $sessionNote) -ForegroundColor Gray
  Write-Host ''
  Write-Host '    One door per machine, and DISCONNECT rather than sign out:'
  Write-Host '    closing the window keeps the session and every app in it;'
  Write-Host '    "sign out" ends it and all its apps.'
  Write-Host ''
} catch {
  Write-Host ''
  Write-Host ('  ERROR: ' + $_.Exception.Message) -ForegroundColor Red
  Write-Host ('  at   : ' + $_.InvocationInfo.PositionMessage) -ForegroundColor DarkGray
  Write-Host ''
}
Read-Host 'Press Enter to close'
