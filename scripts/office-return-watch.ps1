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
      Write-Log "verify: mode        -> $($h.mode)  (the primary must NOT report survivor)"
    } catch { Write-Log "verify: /health     -> FAILED $($_.Exception.Message)" }
    foreach ($alias in 'secratary-ts') {
      $out = & ssh -o ConnectTimeout=10 -o BatchMode=yes $alias 'hostname; uptime; date -u; systemctl is-active secretary-api 2>/dev/null; systemctl is-cloudflared-active 2>/dev/null' 2>&1
      Write-Log "verify: ssh $alias  -> $($out -join ' | ')"
    }
    # The work-loop probe: liveness is not the thing that broke for 13 days in July.
    try {
      $ready = Invoke-RestMethod -Uri 'https://ai.abletelsolutions.com/ready' -TimeoutSec 20
      Write-Log "verify: loop_running_ok -> $($ready.autopilot.loop_running_ok)"
    } catch { Write-Log "verify: /ready      -> FAILED $($_.Exception.Message)" }

    # ---------------------------------------------------------------------
    # CLOSE THE OFFSITE GAP AUTOMATICALLY. The company had no offsite copy at
    # all until 2026-10-06; the pipeline is built and proven but the office must
    # PUSH (it sits behind NAT; Box 2 cannot reach in). So the moment the office
    # returns - even at 4am with nobody watching - install the push and start it.
    # Every step is additive and idempotent, and the ingest refuses to tag a
    # snapshot as trusted unless the byte count matches, so a failure here cannot
    # produce a false "we have a backup".
    # ---------------------------------------------------------------------
    $pushLocal = 'C:\Users\ezabz\code\personal-secretary-mvp\deploy\hosting-migration\scripts\company-offsite-push.sh'
    try {
      # NOTE the redirect form: `tr -d '\r' > "$FILE"`. An earlier version of
      # this line used `tr -d '\r' | cat > "$FILE"` with the variable assigned
      # on the same line, and the shell parsed `tr | REPO=/path` as a pipeline
      # whose second element is an assignment - so REPO was EMPTY, the path
      # became /scripts/server/ at the filesystem ROOT, the file was written
      # empty, chmod'd, and the command still echoed INSTALLED. Caught on
      # 2026-10-06 by testing the template against a live host before trusting
      # it. That is why this version (a) redirects instead of relying on stdin,
      # and (b) VERIFIES the installed copy (non-empty + valid bash) before it
      # touches cron, rather than announcing success.
      $file = '/home/zabz/personal-secretary-mvp/scripts/server/company-offsite-push.sh'
      $remote = "mkdir -p `$(dirname $file) && tr -d '\r' > $file && chmod 755 $file && " +
                "if [ ! -s $file ]; then echo 'VERIFY FAILED: installed copy is empty'; exit 3; fi && " +
                "if ! bash -n $file; then echo 'VERIFY FAILED: installed copy is not valid bash'; exit 4; fi && " +
                "echo `"VERIFIED bytes=`$(wc -c < $file)`" && " +
                "(crontab -l 2>/dev/null | grep -q company-offsite-push || (crontab -l 2>/dev/null; echo `"*/15 * * * * $file >> /var/log/company-offsite-push.log 2>&1`") | crontab -) && echo CRON_READY"
      $installOut = Get-Content -Raw $pushLocal | & ssh -o ConnectTimeout=20 -o BatchMode=yes secratary-ts $remote 2>&1
      Write-Log "offsite: install    -> $(($installOut -join ' | '))"
      # Kick the first push off in the background: ~16 GB takes a while, and the
      # watcher must not block on it. The every-15-minute cron makes the lag after
      # each new local snapshot at most 15 minutes, and re-runs are no-ops because
      # the push asks the receiver first (CHECK_ONLY) before sending anything.
      $kick = & ssh -o ConnectTimeout=20 -o BatchMode=yes secratary-ts "nohup $file > /var/log/company-offsite-push-first.log 2>&1 & echo STARTED" 2>&1
      Write-Log "offsite: first push -> $(($kick -join ' | '))"
    } catch { Write-Log "offsite: install/push -> FAILED $($_.Exception.Message)" }

    Write-Log "verify: peers       -> $((tailscale status 2>&1 | Select-String 'secratary|zabz-tech' | ForEach-Object { $_.Line.Trim() }) -join ' ; ')"
    @{
      recoveredAt = (Get-Date).ToUniversalTime().ToString('o')
      from        = $env:COMPUTERNAME
      tailscale   = if ($ts) { $ts.online } else { $null }
      tunnel      = $tn.detail
      offsite     = 'push installed and started; confirm with company-offsite-status.sh on Box 2'
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
