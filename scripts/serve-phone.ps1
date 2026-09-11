<#
.SYNOPSIS
  Publish this machine's DSH harness to the owner's tailnet, so the iPhone can talk to it.

.DESCRIPTION
  `dsh web` binds loopback only, on purpose: the CLI refuses `--host 0.0.0.0` because it "would expose
  remote code execution to the network". The supported way in is a reverse proxy that preserves `Host`
  in front of loopback, plus `--trusted-host <that authority>` on the engine. Tailscale Serve is that
  proxy: HTTPS with a valid certificate, tailnet-only, no public exposure, no domain to buy.

  Verified by experiment (docs/dsh-mobile/00-RESEARCH.md §2): with `--trusted-host <name>` the one-time
  `?token=` URL is accepted from that authority, the cookie is minted **for that authority**, every API
  and WebSocket call then authenticates with it, an untrusted Host is refused 403 even with a valid
  cookie, and the cookie is worthless on any other authority.

  The engine here is DEDICATED and on its own port, because `--trusted-host` is a startup setting and
  changing it means restarting the engine — which would kill every session in the one you are using.
  It shares DSH_HOME, so it is the same agent: same preset, same tools, same session store.

.EXAMPLE
  pwsh -File scripts\serve-phone.ps1              # publish (starts the engine if needed)
  pwsh -File scripts\serve-phone.ps1 -Status      # what is published, and the phone URL
  pwsh -File scripts\serve-phone.ps1 -Stop        # take it off the tailnet, stop the engine
#>
[CmdletBinding()]
param(
  [int]$Port = 3085,
  [switch]$Status,
  [switch]$Stop,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
function Say($m) { if (-not $Quiet) { Write-Host $m } }

$stateDir = Join-Path $env:LOCALAPPDATA 'dsh-phone'
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
$logPath = Join-Path $stateDir "engine-$Port.log"
$statePath = Join-Path $stateDir 'state.json'

$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts) { throw 'tailscale CLI not found — Serve needs it installed and signed in' }

# --- the tailnet name this machine answers on -----------------------------------------------
$st = & $ts status --json 2>$null | ConvertFrom-Json
$dns = $st.Self.DNSName
if (-not $dns) { throw 'could not determine this node''s tailnet DNS name (is tailscale up?)' }
$dns = $dns.TrimEnd('.')
Say "tailnet name: $dns"

$bin = Get-ChildItem "$env:LOCALAPPDATA\npm-cache\_npx\*\node_modules\@deepseek-ai\dsh\lib\bin.js" -ErrorAction SilentlyContinue |
       Select-Object -First 1 -ExpandProperty FullName
if (-not $bin) { throw 'could not find the dsh bin.js in the npx cache — run `dsh web` once so npx installs it' }

function Get-PhoneEngines {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq 'node.exe' -and $_.CommandLine -and $_.CommandLine -match '\bbin\.js\b' -and
    $_.CommandLine -match "\bweb\b" -and $_.CommandLine -match "--port\s+$Port\b"
  }
}

# --- -Status ---------------------------------------------------------------------------------
if ($Status) {
  $engines = @(Get-PhoneEngines)
  Say ("engine on :{0}  ->  {1}" -f $Port, if ($engines.Count) { "running (pid $($engines[0].ProcessId))" } else { 'NOT running' })
  $served = (& $ts serve status 2>&1) -join "`n"
  Say $served
  $tok = if (Test-Path $logPath) { (Select-String -Path $logPath -Pattern 'token=([A-Za-z0-9_\-]+)' | Select-Object -Last 1).Matches.Groups[1].Value } else { $null }
  if ($tok) {
    Say ''
    Say 'One-time phone link (open on the phone; it mints a 30-day cookie, then use the plain URL):'
    Say ("  https://{0}/?token={1}" -f $dns, $tok)
    Say ("Plain URL afterwards: https://{0}/" -f $dns)
  } else { Say '(no token seen in the engine log yet)' }
  exit 0
}

# --- -Stop -----------------------------------------------------------------------------------
if ($Stop) {
  & $ts serve reset 2>&1 | Out-Null
  Say 'serve config cleared'
  foreach ($e in @(Get-PhoneEngines)) { & taskkill /PID $e.ProcessId /T /F 2>&1 | Out-Null; Say ("stopped engine pid {0}" -f $e.ProcessId) }
  if (Test-Path $statePath) { Remove-Item $statePath -Force }
  exit 0
}

# --- publish: Serve, then an engine that trusts the served name --------------------------------
$serveOut = (& $ts serve --bg $Port 2>&1) -join "`n"
Say $serveOut.Trim()
if ($serveOut -match 'not enabled') {
  Write-Host ''
  Write-Host 'Serve is not enabled on this tailnet. Only the owner can enable it:' -ForegroundColor Yellow
  Write-Host ('  https://login.tailscale.com/f/serve?node={0}' -f $st.Self.ID) -ForegroundColor Yellow
  exit 3
}
if ($serveOut -match '(?i)error|failed') { throw "tailscale serve failed: $serveOut" }

$engines = @(Get-PhoneEngines)
if ($engines.Count -eq 0) {
  Say "starting a harness engine on :$Port that trusts $dns"
  Remove-Item $logPath -ErrorAction SilentlyContinue
  Start-Process -FilePath 'node' -WindowStyle Hidden `
    -ArgumentList @($bin, 'web', '--port', "$Port", '--no-open', '--trusted-host', $dns) `
    -RedirectStandardOutput $logPath -RedirectStandardError (Join-Path $stateDir "engine-$Port.err")
  # the URL (and its token) is printed only once the loader tree settles
  $deadline = (Get-Date).AddSeconds(90)
  do {
    Start-Sleep -Seconds 3
    $ready = (Test-Path $logPath) -and ((Get-Content $logPath -Raw -ErrorAction SilentlyContinue) -match 'token=')
  } while (-not $ready -and (Get-Date) -lt $deadline)
  if (-not $ready) { Say "warning: the engine has not printed its URL yet — check $logPath" }
} else {
  Say ("engine already running on :{0} (pid {1})" -f $Port, $engines[0].ProcessId)
}

$tok = if (Test-Path $logPath) { (Select-String -Path $logPath -Pattern 'token=([A-Za-z0-9_\-]+)' | Select-Object -Last 1).Matches.Groups[1].Value } else { $null }

@{
  port    = $Port
  tailnet = $dns
  url     = "https://$dns/"
  token   = $tok
  at      = (Get-Date).ToUniversalTime().ToString('o')
  host    = $env:COMPUTERNAME
} | ConvertTo-Json | Set-Content -Path $statePath -Encoding utf8

Say ''
Say ("published: https://{0}/  ->  http://127.0.0.1:{1}" -f $dns, $Port)
if ($tok) {
  Say ''
  Say 'ON THE PHONE, open this once:'
  Say ("  https://{0}/?token={1}" -f $dns, $tok)
  Say ("then https://{0}/ is enough for the next 30 days." -f $dns)
  Say 'Add to Home Screen from Safari for the standalone app.'
} else {
  Say "(no token yet; re-run -Status once the engine has printed its URL)"
}
