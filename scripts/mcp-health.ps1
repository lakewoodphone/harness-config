<#
.SYNOPSIS
  Detect an MCP give-up: the state where a running engine's tool set has been unregistered
  and will NOT come back on its own.

.DESCRIPTION
  WHY THIS EXISTS (measured 2026-10-02, ZABZ-YOGA, PAIN P2824 / HANDOFF H3112)

  @deepseek-ai/dsh-mcp-client reconnects a dropped MCP connection on a bounded budget and,
  when the budget expires, it disposes every tool it registered and STOPS. Only an HMR
  reload or a Host restart brings them back. Its own source says so
  (dsh-mcp-client/lib/index.js, "giving up after N consecutive failed reconnect attempts --
  tools unregistered; reload the plugin or restart the Host").

  The failure is silent by construction: every MCP row sets failOnStartupError: false, so a
  give-up is a ctx.logger.error nobody reads, and the GUI shows only a neutral
  "Tools updated / N removed". The owner worked for half an hour with his 14 secretary tools
  gone and no indication of why.

  The budget was raised to ~27.5 minutes (reconnect: maxAttempts 60, maxDelayMs 30000 on
  every MCP row), which covers the measured trigger -- a Windows boot that beats Tailscale
  MagicDNS, so `ssh` cannot resolve the peer and exits instantly. A larger budget narrows the
  window; it does not make the failure visible, and that is what this script supplies.

  WHERE THE EVIDENCE IS. The launcher redirects the engine's stderr into
  <logDir>/3099-<yyyyMMddHHmmss>.err.log (dshw.ps1, -RedirectStandardError), so every
  ctx.logger line and every MCP child's stderr lands in a plain file. That file is outside
  every engine package and outside anything sync.py rewrites, which is exactly why detection
  reads it: patching the plugin itself would be wiped by the next engine install.

  WHAT IT DOES NOT DO. It never restarts anything and never writes to the engine. It reports.
  A detector that silently restarts an engine would trade one silent failure for a worse one:
  a restart loop whose cause nobody can see. Action is a separate, explicit decision.

  Status contract (same idiom as ~/.dsh-sync-status/status.json and
  ~/.harness-config-autosync/status.json, so a monitor can consume it unchanged):
    result: ok          - engines are running and no fresh give-up is on record
            mcp-down    - a give-up is on record for the current engine: tools are gone
            cannot-see  - the engine or its stderr log could not be read; NOT health
  Exit codes: 0 ok, 1 attention (mcp-down), 2 cannot-see. A "cannot see" is never a pass.

.EXAMPLE
  pwsh -File scripts\mcp-health.ps1
  pwsh -File scripts\mcp-health.ps1 -Status      # print the last record and exit
#>
[CmdletBinding()]
param(
  [string]$DshHome = $(if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }),
  [string]$StateDir = (Join-Path $env:USERPROFILE '.dsh-mcp-health'),
  [int]$PrimaryPort = 3099,
  # A give-up whose stderr log was last written longer ago than this is history, not current
  # state: the engine has since been restarted, and reporting it would be a false alarm.
  [int]$FreshMinutes = 60,
  [switch]$Status,
  [switch]$Quiet
)

$ErrorActionPreference = 'Continue'

function Log([string]$m) { if (-not $Quiet) { Write-Host $m } }

$statusPath = Join-Path $StateDir 'status.json'
$historyPath = Join-Path $StateDir 'history.log'

if ($Status) {
  if (Test-Path $statusPath) { Get-Content $statusPath -Raw; exit 0 }
  Write-Host "no record yet at $statusPath"; exit 0
}

function Write-Record($obj) {
  try {
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Force -Path $StateDir | Out-Null }
    # Never emit null for a field the schema promises: absent and empty mean the same thing to a
    # consumer, and null only invites a special case in every reader.
    $doc = [ordered]@{
      updated        = $obj.updated
      result         = $obj.result
      detail         = $obj.detail
      host           = $env:COMPUTERNAME
      engines        = $obj.engines
      connectors     = $obj.connectors
      log            = $obj.log
      logAgeMinutes  = $obj.logAgeMinutes
      giveups        = $obj.giveups
      giveupLine     = $obj.giveupLine
      fresh          = $obj.fresh
    }
    ($doc | ConvertTo-Json -Depth 4) | Set-Content -Path $statusPath -Encoding utf8
  } catch {
    Log "WARN could not write $statusPath : $($_.Exception.Message)"
  }
  $line = '{0} [{1}] {2}' -f $obj.updated, $obj.result, $obj.detail
  try { Add-Content -Path $historyPath -Value $line } catch { }
  Log $line
}

$now = (Get-Date).ToUniversalTime().ToString('o')

# ---------------------------------------------------------------------------
# 1. The engines. Read from the process table, not from the state file, because the state
#    file is a launcher record that can lag a crash (measured: it still named pid 11176 after
#    the engine was gone and 25228 was serving).
# ---------------------------------------------------------------------------
$engines = @()
try {
  $engines = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction Stop |
    Where-Object { $_.CommandLine -match 'dsh[\\/]lib[\\/]bin\.js"?\s+web\b' } |
    ForEach-Object { [pscustomobject]@{ pid = [int]$_.ProcessId; started = $_.CreationDate } })
} catch {
  Write-Record ([ordered]@{ updated = $now; result = 'cannot-see'; detail = "process table unreadable: $($_.Exception.Message)"; engines = -1; connectors = -1; log = ''; logAgeMinutes = -1; giveups = -1; giveupLine = ''; fresh = $false })
  exit 2
}
if ($engines.Count -eq 0) {
  Write-Record ([ordered]@{ updated = $now; result = 'cannot-see'; detail = "no dsh web engine process is running on this host (port $PrimaryPort)"; engines = 0; connectors = -1; log = ''; logAgeMinutes = -1; giveups = -1; giveupLine = ''; fresh = $false })
  exit 2
}

# ---------------------------------------------------------------------------
# 2. The engine's stderr log. Named 3099-<yyyyMMddHHmmss>.err.log by the launcher; the stamp
#    is the boot attempt time, so the newest one belongs to the newest boot. Approximate the
#    binding by newest-mtime and say so rather than pretending to a precision that is not there.
# ---------------------------------------------------------------------------
$logDir = Join-Path $DshHome 'multi-window\logs'
if (-not (Test-Path $logDir)) {
  Write-Record ([ordered]@{ updated = $now; result = 'cannot-see'; detail = "engine log directory not found: $logDir"; engines = $engines.Count; connectors = -1; log = ''; logAgeMinutes = -1; giveups = -1; giveupLine = ''; fresh = $false })
  exit 2
}
$log = Get-ChildItem $logDir -File -Filter '*.err.log' -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $log) {
  Write-Record ([ordered]@{ updated = $now; result = 'cannot-see'; detail = "no *.err.log in $logDir, so a give-up cannot be ruled out"; engines = $engines.Count; connectors = -1; log = ''; logAgeMinutes = -1; giveups = -1; giveupLine = ''; fresh = $false })
  exit 2
}

$logAgeMin = [int]((Get-Date).ToUniversalTime() - $log.LastWriteTime.ToUniversalTime()).TotalMinutes

# ---------------------------------------------------------------------------
# 3. The give-up marker. dsh-mcp-client's own wording, so the detector and the thing it watches
#    cannot drift: it is the same string the source emits.
# ---------------------------------------------------------------------------
$marker = 'giving up after'
$giveups = @(Select-String -Path $log.FullName -SimpleMatch $marker -ErrorAction SilentlyContinue)
$giveupLine = if ($giveups.Count -gt 0) { $giveups[-1].Line.Trim() } else { '' }

# Positive control: the connector children that SHOULD exist while tools are registered.
$connectors = -1
try {
  $connectors = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ParentProcessId -eq $engines[0].pid -and $_.CommandLine -match 'ps_mcp_server|mcp_launcher|mcp-remote|@playwright' }).Count
} catch { $connectors = -1 }

if ($giveups.Count -gt 0 -and $logAgeMin -le $FreshMinutes) {
  Write-Record ([ordered]@{
      updated = $now; result = 'mcp-down'
      detail = "give-up on record in $($log.Name) ($logAgeMin min old): the tool set is unregistered and will not return without an engine restart"
      engines = $engines.Count; connectors = $connectors; log = $log.Name; logAgeMinutes = $logAgeMin
      giveups = $giveups.Count; giveupLine = $giveupLine; fresh = $true
    })
  exit 1
}

if ($giveups.Count -gt 0) {
  Write-Record ([ordered]@{
      updated = $now; result = 'ok'
      detail = "$($giveups.Count) historical give-up(s) in $($log.Name), last written $logAgeMin min ago - older than the $FreshMinutes min freshness window, so not current state"
      engines = $engines.Count; connectors = $connectors; log = $log.Name; logAgeMinutes = $logAgeMin
      giveups = $giveups.Count; giveupLine = $giveupLine; fresh = $false
    })
  exit 0
}

Write-Record ([ordered]@{
    updated = $now; result = 'ok'
    detail = "no give-up on record; engine(s) $($engines.Count), connector children $connectors, newest stderr log $($log.Name) ($logAgeMin min old)"
    engines = $engines.Count; connectors = $connectors; log = $log.Name; logAgeMinutes = $logAgeMin
    giveups = 0; giveupLine = ''; fresh = $false
  })
exit 0
