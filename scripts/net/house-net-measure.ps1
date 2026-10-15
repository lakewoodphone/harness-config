$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$file  = "C:\Users\ezabz\code\out\net-measure-$env:DSH_SESSION_ID.txt"
if (-not $env:DSH_SESSION_ID) { $file = "C:\Users\ezabz\code\out\net-measure-run.txt" }

function W($s) { $s | Tee-Object -FilePath $file -Append }

W "###### NET MEASUREMENT RUN ######"
W "start_utc       : $((Get-Date).ToUniversalTime().ToString('u'))"
W "local_time      : $stamp"
W "host            : $env:COMPUTERNAME"
W "session_env     : $env:DSH_SESSION_ID"

W ""
W "=== 1. WIRELESS LINK ==="
W (netsh wlan show interfaces 2>&1 | Out-String)

W "=== 2. NEIGHBOURING BSSIDS (interference) ==="
$nets = netsh wlan show networks mode=bssid 2>&1 | Out-String
$bssidLines = ($nets -split "`r?`n" | Where-Object { $_ -match 'SSID \d+\s*:|BSSID \d+\s*:|Signal\s*:|Channel\s*:|Radio type\s*:' })
W (($bssidLines | Select-Object -First 120) -join "`n")

W ""
W "=== 3. IP CONFIGURATION ==="
W (ipconfig /all 2>&1 | Out-String)

W "=== 4. DEFAULT GATEWAY / ROUTES ==="
$gw = $null
try {
  Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
    Sort-Object RouteMetric | Select-Object -First 3 |
    ForEach-Object { W ("route: {0} via {1} ifIndex {2} metric {3}" -f $_.DestinationPrefix, $_.NextHop, $_.ifIndex, $_.RouteMetric) }
  $gw = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1).NextHop
} catch { W "Get-NetRoute failed: $($_.Exception.Message)" }
if (-not $gw) { $gw = (ipconfig | Select-String 'Default Gateway' | Select-Object -First 1) -replace '.*:\s*','' }
W "gateway         : $gw"

W ""
W "=== 5. LAN PING (gateway $gw, 30 packets) ==="
if ($gw -match '^\d+\.\d+\.\d+\.\d+$') {
  W (ping -n 30 $gw 2>&1 | Out-String)
} else { W "no numeric gateway; skipped" }

W ""
W "=== 6. WAN PING 1.1.1.1 (30 packets) ==="
W (ping -n 30 1.1.1.1 2>&1 | Out-String)

W ""
W "=== 7. WAN PING 8.8.8.8 (30 packets) ==="
W (ping -n 30 8.8.8.8 2>&1 | Out-String)

W ""
W "=== 8. TRACE TO 1.1.1.1 ==="
W (tracert -d -w 1500 -h 16 1.1.1.1 2>&1 | Out-String)

W ""
W "=== 9. DNS RESOLUTION TIMING ==="
foreach ($n in @('google.com','facebook.com','speed.cloudflare.com','api.openai.com')) {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    $r = Resolve-DnsName -Name $n -Type A -ErrorAction Stop | Where-Object { $_.IPAddress } | Select-Object -First 1
    $sw.Stop()
    W ("{0,-24} {1,6} ms  -> {2}" -f $n, $sw.ElapsedMilliseconds, $r.IPAddress)
  } catch { $sw.Stop(); W ("{0,-24} {1,6} ms  -> FAILED: {2}" -f $n, $sw.ElapsedMilliseconds, $_.Exception.Message) }
}

W ""
W "=== 10. DOWNLOAD THROUGHPUT (cloudflare 25 MB) ==="
W (curl.exe -s -o NUL --max-time 60 -w "http=%{http_code} bytes=%{size_download} seconds=%{time_total} speed_Bps=%{speed_download}`n" "https://speed.cloudflare.com/__down?bytes=25000000" 2>&1 | Out-String)

W ""
W "=== 11. DOWNLOAD THROUGHPUT 2 (cachefly 10 MB) ==="
W (curl.exe -s -o NUL --max-time 60 -w "http=%{http_code} bytes=%{size_download} seconds=%{time_total} speed_Bps=%{speed_download}`n" "http://cachefly.cachefly.net/10mb.test" 2>&1 | Out-String)

W ""
W "=== 12. UPLOAD THROUGHPUT (10 MB to cloudflare) ==="
$up = "C:\Users\ezabz\code\out\uploadtest.bin"
try {
  $buf = New-Object byte[] (10MB)
  [System.IO.File]::WriteAllBytes($up, $buf)
  W (curl.exe -s -o NUL --max-time 90 -X POST --data-binary "@$up" -H "Content-Type: application/octet-stream" -w "http=%{http_code} seconds=%{time_total} speed_Bps=%{speed_upload}`n" "https://speed.cloudflare.com/__up" 2>&1 | Out-String)
} catch { W "upload test failed to build payload: $($_.Exception.Message)" }

W ""
W "=== 13. LATENCY UNDER DOWNLOAD LOAD (bufferbloat) ==="
$job = Start-Job -ScriptBlock { curl.exe -s -o NUL --max-time 45 "https://speed.cloudflare.com/__down?bytes=100000000" }
Start-Sleep -Seconds 6
W (ping -n 20 $gw 2>&1 | Out-String)
W "-- under load, host 1.1.1.1 --"
W (ping -n 20 1.1.1.1 2>&1 | Out-String)
Wait-Job $job -Timeout 60 | Out-Null
Remove-Job $job -Force

W ""
W "=== 14. TCP CONNECTION SNAPSHOT ==="
try {
  $c = Get-NetTCPConnection -State Established -ErrorAction Stop
  W ("established_total : {0}" -f $c.Count)
  $c | Group-Object OwningProcess | Sort-Object Count -Descending | Select-Object -First 12 | ForEach-Object {
    $p = (Get-Process -Id $_.Name -ErrorAction SilentlyContinue).ProcessName
    W ("  pid {0,-7} {1,-26} {2}" -f $_.Name, $p, $_.Count)
  }
} catch { W "Get-NetTCPConnection failed: $($_.Exception.Message)" }

W ""
W "=== 15. WIFI ADAPTER COUNTERS ==="
try {
  Get-NetAdapterStatistics -ErrorAction Stop | ForEach-Object {
    W ("{0} rx={1} tx={2} rxErr={3} txErr={4}" -f $_.Name, $_.ReceivedBytes, $_.SentBytes, $_.ReceivedDiscardedPackets, $_.OutboundDiscardedPackets)
  }
} catch { W "adapter stats failed: $($_.Exception.Message)" }

W ""
W "### RUN COMPLETE ###"
W "end_utc         : $((Get-Date).ToUniversalTime().ToString('u'))"
