$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$file = "C:\Users\ezabz\code\out\net-burst.txt"
function W($s) { $s | Tee-Object -FilePath $file -Append }

function PingStats($target, $n) {
  $r = (ping -n $n -w 2500 $target 2>&1 | Out-String)
  $loss = '?'; $mn='?'; $av='?'; $mx='?'
  if ($r -match 'Lost = (\d+) \((\d+)% loss\)') { $loss = $Matches[2] + '%' }
  if ($r -match 'Minimum = (\d+)ms, Maximum = (\d+)ms, Average = (\d+)ms') { $mn=$Matches[1]; $mx=$Matches[2]; $av=$Matches[3] }
  $times = [regex]::Matches($r, 'time=(\d+)ms') | ForEach-Object { [int]$_.Groups[1].Value }
  if ($times.Count -gt 0) {
    $sorted = $times | Sort-Object
    $p95 = $sorted[[Math]::Min($sorted.Count-1, [int][Math]::Floor($sorted.Count*0.95))]
    return "min=$mn avg=$av max=$mx p95=$p95 loss=$loss n=$($times.Count)"
  }
  return "loss=$loss raw=$(($r -split "`n" | Select-Object -First 2) -join ' ')"
}

W "###### VARIANCE BURST  (how variable is the path right now?) ######"
W "start_utc : $((Get-Date).ToUniversalTime().ToString('u'))"
W "round | time_utc | wifi | wan_8.8.8.8 | tmobile_hop | dl_cloudflare_10s"

for ($i = 1; $i -le 24; $i++) {
  $t = (Get-Date).ToUniversalTime().ToString('HH:mm:ss')

  $wifi = ''
  $w = (netsh wlan show interfaces 2>&1 | Out-String)
  if ($w -match 'Rssi\s+:\s+(-?\d+)') { $wifi += "rssi=$($Matches[1]) " }
  if ($w -match 'Receive rate \(Mbps\)\s+:\s+(\d+)') { $wifi += "rx=$($Matches[1]) " }
  if ($w -match 'Channel\s+:\s+(\d+)') { $wifi += "ch=$($Matches[1])" }

  $wan  = PingStats '8.8.8.8' 8
  $tmo  = PingStats '192.168.12.1' 4

  $dl = (curl.exe -s -o NUL --max-time 10 -w "%{speed_download} %{size_download} %{time_total}" "https://speed.cloudflare.com/__down?bytes=20000000" 2>&1 | Out-String).Trim()
  $parts = $dl -split '\s+'
  $mbps = 'fail'
  if ($parts.Count -ge 1 -and [double]$parts[0] -gt 0) { $mbps = [Math]::Round([double]$parts[0] * 8 / 1e6, 1) }
  $gotmb = '0'
  if ($parts.Count -ge 2) { $gotmb = [Math]::Round([double]$parts[1] / 1e6, 1) }

  W ("{0,5} | {1} | {2} | {3} | {4} | {5} Mbps ({6} MB)" -f $i, $t, $wifi.Trim(), $wan, $tmo, $mbps, $gotmb)
}
W "end_utc : $((Get-Date).ToUniversalTime().ToString('u'))"
