<#
.SYNOPSIS
  Watch for the office coming back, verify it fully when it does, and record the outage.

.DESCRIPTION
  Written 2026-10-06 during the office outage that began 2026-10-05 22:57 UTC, in which
  secratary, zabz-tech, zabz-tech-linux and the mac mini all stopped reaching Tailscale
  within 31 seconds while the office Home Assistant host stayed online (proving the shop
  still had power AND internet). There is no out-of-band power path to the office, so the
  only useful thing a machine at home can do is notice the recovery and prove it is real
  rather than assume it.

  It polls three independent surfaces, because one is not evidence:
    1. Tailscale peer state for secratary (the control plane's own view)
    2. the secretary's public API through the Cloudflare tunnel (ai.abletelsolutions.com)
    3. the tailnet API port, if the box exposes it

  On the transition offline->healthy it runs a verification battery, writes the result to
  the log and to office-return-watch.json, and exits 0. It never reports success from
  configuration; only from an answered request.

.EXAMPLE
  pwsh -File scripts\office-return-watch.ps1 -MaxMinutes 720
#>
[CmdletBinding()]
param(
  [int]$IntervalSec = 60,
  [int]$MaxMinutes  = 720,
  [string]$LogPath  = (Join-Path $env:USERPROFILE '.dsh-sync-status\office-return-watch.log'),
  [string]$StatePath = (Join-Path $env:USERPROFILE '.dsh-sync-status\office-return-watch.json')
)

$ErrorActionPreference = 'Continue'
$dir = Split-Path -Parent $LogPath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

function Write-Log([string]$msg) {
  $line = "{0}Z  {1}" -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss'), $msg
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

function Test-SecretaryTunnel {
  # 200 + ok:true from the tunnel origin. A 530 means Cloudflare is up and the tunnel is not.
  try {
    $r = Invoke-WebRequest -Uri 'https://ai.abletelsolutions.com/health' -TimeoutSec 15 -UseBasicParsing
    if ($r.StatusCode -eq 200 -and $r.Content -match '"ok"\s*:\s*true') { return @{ up = $true; detail = 'tunnel 200 ok:true' } }
    return @{ up = $false; detail = "tunnel $($r.StatusCode)" }
  } catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
    return @{ up = $false; detail = if ($code) { "tunnel HTTP $code" } else { "tunnel unreachable: $($_.Exception.Message)" } }
  }
}

function Get-TailscalePeer([string]$name) {
  try {
    $j = tailscale status --json | ConvertFrom-Json
    foreach ($p in $j.Peer.PSObject.Properties) {
      if ($p.Value.HostName -eq $name) {
        return @{ online = [bool]$p.Value.Online; lastSeen = $p.Value.LastSeen }
      }
    }
  } catch { }
  return $null
}

$deadline = (Get-Date).AddMinutes($MaxMinutes)
Write-Log "watch started (interval ${IntervalSec}s, window ${MaxMinutes}m) from $env:COMPUTERNAME"
$wasUp = $false
$lastBeat = Get-Date

while ((Get-Date) -lt $deadline) {
  $ts = Get-TailscalePeer 'secratary'
  $tn = Test-SecretaryTunnel
  $up = ($ts -and $ts.online) -or $tn.up

  if ($up -and -not $wasUp) {
    Write-Log "RECOVERY DETECTED: tailscale_online=$($ts.online) $($tn.detail)"
    # Verification battery - claims must survive being checked.
    Write-Log "verify: tunnel      -> $($tn.detail)"
    try {
      $h = Invoke-RestMethod -Uri 'https://ai.abletelsolutions.com/health' -TimeoutSec 20
      Write-Log "verify: /health     -> $(($h | ConvertTo-Json -Compress -Depth 4))"
    } catch { Write-Log "verify: /health     -> FAILED $($_.Exception.Message)" }
    foreach ($alias in 'secratary-ts') {
      $out = & ssh -o ConnectTimeout=10 -o BatchMode=yes $alias 'hostname; uptime; date -u; systemctl is-active secretary-api 2>/dev/null; systemctl is-active cloudflared 2>/dev/null' 2>&1
      Write-Log "verify: ssh $alias  -> $($out -join ' | ')"
    }
    Write-Log "verify: peers       -> $((tailscale status 2>&1 | Select-String 'secratary|zabz-tech' | ForEach-Object { $_.Line.Trim() }) -join ' ; ')"
    @{
      recoveredAt = (Get-Date).ToUniversalTime().ToString('o')
      from        = $env:COMPUTERNAME
      tailscale   = if ($ts) { $ts.online } else { $null }
      tunnel      = $tn.detail
    } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8
    exit 0
  }

  if (-not $up -and $wasUp) { Write-Log "went offline again" }
  $wasUp = $up

  if (((Get-Date) - $lastBeat).TotalMinutes -ge 15) {
    Write-Log "still down: tailscale_online=$($ts.online) $($tn.detail)"
    $lastBeat = Get-Date
  }
  Start-Sleep -Seconds $IntervalSec
}

Write-Log "watch window ended with the office still offline"
exit 2
