# link-probe.ps1 - a permanent, bounded record of the link from THE CLIENT's side.
#
# WHY: the failures the owner hit (freeze, then "session ended", then a connect timeout) were the tailnet
# path between the Yoga (T-Mobile home internet, carrier-grade NAT) and the office going away or changing,
# not RDP failing. The host already logs the path every two minutes from ITS side; this is the other half
# of the pair, so a future "it dropped again" can be answered with which side lost the path and when.
# Runs from a scheduled task every 10 minutes: 5 samples, 30 s apart, appended to one rotating log.
$log = "$env:USERPROFILE\.dsh\logs\link-probe.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Get-Content $log -Tail 300 | Set-Content $log }

for ($i = 1; $i -le 5; $i++) {
  $ping = (tailscale ping -c 1 --timeout 3s zabz-tech 2>&1 | Select-Object -First 1) -join ' '
  $path = 'UNREACHABLE'
  if ($ping -match 'DERP|relay') { $path = 'RELAY' } elseif ($ping -match 'via ') { $path = 'direct' }
  $rtt = '-1'
  if ($ping -match 'in (\d+(\.\d+)?)ms') { $rtt = $Matches[1] }

  $sw = [Diagnostics.Stopwatch]::StartNew()
  $tcp = $false
  try {
    $c = New-Object Net.Sockets.TcpClient
    $t = $c.ConnectAsync('zabz-tech.tail93e6e6.ts.net', 3389)
    $tcp = $t.Wait(4000) -and $c.Connected
    $c.Close()
  } catch { $tcp = $false }
  $sw.Stop()

  # TWO references, because they answer different questions and the first version of this probe got it
  # wrong: `secratary` is itself reached over a relayed tailnet path and dips on its own, so a False there
  # says nothing about this machine's internet. 1.1.1.1:443 is a plain public endpoint - if THAT fails, this
  # side is offline; if it succeeds while zabz-tech is unreachable, the path/office side is the problem.
  $internet = $false
  try {
    $c2 = New-Object Net.Sockets.TcpClient
    $t2 = $c2.ConnectAsync('1.1.1.1', 443)
    $internet = $t2.Wait(3000) -and $c2.Connected
    $c2.Close()
  } catch { $internet = $false }
  $refPing = (tailscale ping -c 1 --timeout 3s secratary 2>&1 | Select-Object -First 1) -join ' '
  $refOk = $refPing -match 'in \d'

  "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') path=$path rtt=$rtt tcp3389=$tcp ms=$($sw.ElapsedMilliseconds) internet=$internet secratary=$refOk" | Add-Content $log
  if ($i -lt 5) { Start-Sleep -Seconds 30 }
}
