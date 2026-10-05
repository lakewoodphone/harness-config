# rdp-health.ps1 - keeps the ZABZ-TECH RDP door open, and explains in one place WHY it ever closed.
# Runs as SYSTEM every 2 minutes ("Zabz RDP health"). Safe by construction: it only ever restarts RDP
# services when the listener is ALREADY missing, so it cannot drop a live session.
$log    = 'C:\Users\ezabz\.dsh\logs\rdp-health.log'
$state  = 'C:\Users\ezabz\.dsh\logs\rdp-health-state.json'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 2MB)) { Get-Content $log -Tail 400 | Set-Content $log }
function Note($m) { "$((Get-Date).ToString('s')) $m" | Add-Content $log }

$prev = $null
if (Test-Path $state) { try { $prev = Get-Content $state -Raw | ConvertFrom-Json } catch {} }

# ---- 1. why the last session ended: translate the RDS reason codes ----
$why = @{
  '1'='disconnected by an admin tool in another session'; '2'='forced logoff by an admin tool'
  '3'='idle session limit reached'; '4'='active session limit reached'
  '5'='ANOTHER CONNECTION TOOK THE SESSION (client Windows allows one - CRD/console vs RDP)'
  '6'='server ran out of memory'; '7'='server denied the connection'
  '9'='insufficient access privileges'; '10'='server does not accept saved credentials'
  '11'='user disconnected their own session'; '12'='user logged off their session'
  '2147942464'='ERROR_NETNAME_DELETED - the network connection disappeared (path/NAT change)'
  '2147942521'='0x80070039 - abrupt client-side break'
  '2147024775'='0x80070079 ERROR_SEM_TIMEOUT - the transport stalled'
}
$since = (Get-Date).AddMinutes(-20)
$maxId = 0
if ($prev -and $prev.lastSessionEventId) { $maxId = [int]$prev.lastSessionEventId }
$events = Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TerminalServices-LocalSessionManager/Operational'; StartTime=$since} -ErrorAction SilentlyContinue |
  Where-Object { $_.Id -in 21,23,24,25,40 -and $_.RecordId -gt $maxId } | Sort-Object RecordId
$newest = $maxId
foreach ($e in $events) {
  $newest = [math]::Max($newest, $e.RecordId)
  $r = $null
  if ($e.Id -eq 40) { try { $x = [xml]$e.ToXml(); $r = $x.Event.UserData.EventXML.Reason } catch { $r = $null } }
  $meaning = if ($r -and $why.ContainsKey([string]$r)) { $why[[string]$r] } elseif ($r) { "reason code $r" } else { '' }
  if ($e.Id -in 40,24,25) { Note ("session-event id=$($e.Id) $meaning") }
}

# ---- 2. the three services the door needs ----
$healed = @(); $open = @()
foreach ($n in 'TermService','UmRdpService','SessionEnv') {
  $s = Get-Service $n -ErrorAction SilentlyContinue
  if (-not $s) { $open += "service missing: $n"; continue }
  if ($s.Status -ne 'Running') { try { Start-Service $n -ErrorAction Stop; $healed += "started $n" } catch { $open += "could not start $n" } }
}

# ---- 3. the listener: the Known Bad State is services Running with no rdp-tcp listener ----
$win = (qwinsta) -join "`n"
$listenerTcp = [bool](Get-NetTCPConnection -State Listen -LocalPort 3389 -ErrorAction SilentlyContinue)
$listenerWts = $win -match 'rdp-tcp'
if (-not ($listenerTcp -and $listenerWts)) {
  foreach ($n in 'SessionEnv','UmRdpService') { try { Restart-Service $n -Force -ErrorAction Stop } catch {} }
  try { Restart-Service TermService -Force -ErrorAction Stop } catch { try { Start-Service TermService -ErrorAction Stop } catch {} }
  Start-Sleep -Seconds 6
  $listenerTcp = [bool](Get-NetTCPConnection -State Listen -LocalPort 3389 -ErrorAction SilentlyContinue)
  $listenerWts = ((qwinsta) -join "`n") -match 'rdp-tcp'
  if ($listenerTcp -and $listenerWts) { $healed += 're-created the RDP listener without a reboot' }
  else { $open += 'RDP LISTENER MISSING and could not be re-created - ZABZ-TECH needs a reboot' }
}

# ---- 4. Tailscale and the live path ----
$ts = Get-Service Tailscale -ErrorAction SilentlyContinue
if ($ts -and $ts.Status -ne 'Running') { try { Start-Service Tailscale; $healed += 'started Tailscale' } catch { $open += 'Tailscale not running' } }
$path = 'unknown'
try { $p = (tailscale ping -c 1 --timeout 3s zabz-yoga-1 2>&1 | Select-Object -First 1) -join ' '
      $path = if ($p -match 'DERP|relay') { 'RELAY' } elseif ($p -match 'via ') { 'direct' } else { 'unreachable' } } catch {}

# ---- 5. state + trail (only write the trail when something actually changed) ----
$sessions = (qwinsta) -join ' | '
[ordered]@{
  time = (Get-Date).ToString('o'); listenerTcp = $listenerTcp; rdpTcpListener = $listenerWts; pathToYoga = $path
  healed = $healed; needsAttention = $open; sessions = $sessions; lastSessionEventId = $newest
} | ConvertTo-Json -Depth 4 | Set-Content $state
if ($healed.Count -or $open.Count) { Note ("HEALED: " + ($healed -join '; ') + " || OPEN: " + ($open -join '; ')) }
$changed = (-not $prev) -or ($prev.pathToYoga -ne $path) -or ($prev.listenerTcp -ne $listenerTcp) -or ($prev.sessions -ne $sessions)
if ($changed) { Note ("path=$path listener=$listenerTcp sessions: $sessions") }