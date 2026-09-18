<#
.SYNOPSIS
  Publish this machine's DSH harness to the owner's tailnet, so the iPhone can talk to it.

.DESCRIPTION
  REWRITTEN 2026-09-16. The previous version started a **dedicated second engine** on port 3085
  sharing the same ~/.dsh, and said so in its own header ("It shares DSH_HOME, so it is the same
  agent"). That is the one-writer violation: multi-window/windows.json:5 records that two `dsh web`
  processes on one home have been observed writing duplicate sequence numbers into one session log
  and making the whole history unloadable. It existed only because `--trusted-host` is a startup
  setting and restarting the engine in use would end every live session.

  Neither is necessary. Measured on ZABZ-YOGA 2026-09-16:

    * publishing the engine directly gives **403** on every /api call — `tailscale serve` preserves
      the client's Host header and the fence does not trust it;
    * the same URL with `scripts/phone-gate.py` in front, presenting Host AND Origin as
      127.0.0.1:<engine port>, gives `GET /` **200** with a 30-day cookie, `GET /healthz` **200
      application/json**, `GET /api` with no cookie **401**, and the engine reached directly with a
      foreign Host still **403**.

  So this script no longer starts, stops or knows about a second engine. It is now a thin front for
  `scripts/phone-gate-ensure.ps1`, which keeps the gate listening and re-asserts Serve, and it
  never touches the engine at all.

.EXAMPLE
  pwsh -File scripts\serve-phone.ps1              # publish (starts the gate if needed)
  pwsh -File scripts\serve-phone.ps1 -Status      # what is published, and the phone URL
  pwsh -File scripts\serve-phone.ps1 -Stop        # take it off the tailnet and stop the gate
#>
[CmdletBinding()]
param(
    [int]$Port = 3086,
    [int]$EnginePort = 3099,
    [switch]$Status,
    [switch]$Stop,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
function Say($m) { if (-not $Quiet) { Write-Host $m } }

$ensure = Join-Path $PSScriptRoot 'phone-gate-ensure.ps1'
if (-not (Test-Path $ensure)) { throw "phone-gate-ensure.ps1 not found at $ensure" }

$dns = ''
try {
    $st = (& tailscale status --json 2>$null | ConvertFrom-Json)
    if ($st.Self.DNSName) { $dns = $st.Self.DNSName.TrimEnd('.') }
} catch { }
if (-not $dns) { throw "could not determine this node's tailnet DNS name (is tailscale up?)" }

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1

if ($Status) {
    Say "tailnet name : $dns"
    Say "phone URL    : https://$dns/"
    Say ("gate  :{0}     {1}" -f $Port, $(if ($listener) { "listening (pid $($listener.OwningProcess))" } else { 'NOT listening' }))
    $engine = Get-NetTCPConnection -State Listen -LocalPort $EnginePort -ErrorAction SilentlyContinue | Select-Object -First 1
    Say ("engine :{0}    {1}" -f $EnginePort, $(if ($engine) { "listening (pid $($engine.OwningProcess))" } else { 'NOT listening' }))
    Say ''
    (& tailscale serve status 2>&1) | ForEach-Object { Say $_ }
    Say ''
    & $ensure -ListenPort $Port -EnginePort $EnginePort -Status
    Say ''
    Say 'Is it actually usable? That is not what serve status says. Check with:'
    Say '  pwsh -File scripts\mesh-health.ps1'
    exit 0
}

if ($Stop) {
    & tailscale serve reset 2>&1 | Out-Null
    Say 'serve config cleared - the tailnet name no longer reaches this machine'
    if ($listener) {
        # Only the GATE is stopped. The engine is the owner's, holds his live sessions, and is
        # none of this script's business.
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        Say ("stopped the gate (pid {0})" -f $listener.OwningProcess)
    }
    Say 'the engine was left running on purpose'
    exit 0
}

# Publish. -Publish asks `tailscale serve status` first and only asserts when the mapping is
# missing, so running this repeatedly is cheap and a lost Serve config heals itself.
& $ensure -ListenPort $Port -EnginePort $EnginePort -Publish -Quiet

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
Say ''
if ($listener) {
    Say ("published: https://{0}/  ->  gate on 127.0.0.1:{1}  ->  engine on 127.0.0.1:{2}" -f $dns, $Port, $EnginePort)
    Say ''
    Say 'ON THE PHONE: open the URL and you are signed in - the gate does the login itself, so there'
    Say 'is no token link to paste and nothing to bookmark. Add to Home Screen from Safari for the'
    Say 'standalone app.'
} else {
    Say ("the gate is NOT listening on {0} - see %LOCALAPPDATA%\dsh-phone\gate-{0}.log" -f $Port)
    exit 1
}
