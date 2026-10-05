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
  Write-Host '    One door per machine: if a Chrome Remote Desktop session is open to'
  Write-Host '    that machine, your RDP login has to evict it - retry once if refused.'
  Write-Host ''
} catch {
  Write-Host ''
  Write-Host ('  ERROR: ' + $_.Exception.Message) -ForegroundColor Red
  Write-Host ('  at   : ' + $_.InvocationInfo.PositionMessage) -ForegroundColor DarkGray
  Write-Host ''
}
Read-Host 'Press Enter to close'
