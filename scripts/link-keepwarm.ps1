# link-keepwarm.ps1 - keeps the tailnet path to ZABZ-TECH warm and records every path change.
# Why: the Yoga sits behind carrier-grade NAT (T-Mobile home internet); when the carrier re-maps, the tailnet
# falls back to DERP and a long-lived RDP TCP session dies (ERROR_NETNAME_DELETED). Light continuous traffic
# keeps the mappings fresh and lets Tailscale find the direct path again - measured: RELAY at 02:04:37 became
# direct at 02:05:34 after this task started running every minute.
# netcheck (which probes every DERP region) only runs when the path changed, not on every tick.
$log   = "$env:USERPROFILE\.dsh\logs\link-keepwarm.log"
$state = "$env:USERPROFILE\.dsh\logs\link-keepwarm-state.json"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Get-Content $log -Tail 300 | Set-Content $log }

$prev = if (Test-Path $state) { try { Get-Content $state -Raw | ConvertFrom-Json } catch { $null } } else { $null }
$note = @()
$ts = Get-Service Tailscale -ErrorAction SilentlyContinue
if ($ts -and $ts.Status -ne 'Running') { try { Start-Service Tailscale; $note += 'started Tailscale' } catch { $note += 'Tailscale will not start' } }

$out  = (tailscale ping -c 1 --timeout 3s zabz-tech 2>&1 | Select-Object -First 1) -join ' '
$path = if ($out -match 'DERP|relay') { 'RELAY' } elseif ($out -match 'via ') { 'direct' } else { 'unreachable' }
$rtt  = if ($out -match 'in (\d+(\.\d+)?)ms') { $Matches[1] + 'ms' } else { '-' }

# only pay for netcheck when the path actually changed, or every 15th run (~15 min) as a baseline
$pub = if ($prev) { $prev.publicEndpoint } else { '' }
$changed = (-not $prev) -or ($prev.path -ne $path)
$beats = if ($prev -and $prev.beats) { [int]$prev.beats + 1 } else { 1 }
if ($changed -or ($beats % 15 -eq 0)) {
  $r = tailscale netcheck 2>&1 | Select-String 'IPv4: yes' | Select-Object -First 1
  if ($r) { $pub = ($r -replace '.*yes,\s*','').Trim() }
}
[ordered]@{ time=(Get-Date).ToString('o'); path=$path; rtt=$rtt; publicEndpoint=$pub; beats=$beats; note=($note -join '; ') } |
  ConvertTo-Json | Set-Content $state
if ($changed -or $note.Count) { "$((Get-Date).ToString('s')) path=$path rtt=$rtt public=$pub beats=$beats $(($note) -join '; ')" | Add-Content $log }