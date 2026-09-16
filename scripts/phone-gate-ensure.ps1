<#
.SYNOPSIS
  Keep this machine's phone gate listening, so the tailnet name it is published under works.

.DESCRIPTION
  The gate (`scripts/phone-gate.py`) is what makes a node reachable from the owner's phone at
  all. `dsh web` binds loopback on purpose and its `/api` fence accepts a loopback Host or a
  declared `trustedHosts` authority — and nothing else. Measured on ZABZ-YOGA 2026-09-16:

    * `tailscale serve --bg 3099` straight at the engine: `GET /api` through
      https://zabz-yoga-1.tail93e6e6.ts.net returned **403** (Serve preserves the Host header,
      and the engine was never launched with `--trusted-host`, which is a STARTUP setting —
      applying it means restarting the engine, which ends every live session, including the
      one that was doing the measuring).
    * the same URL with the gate in front and `--engine-authority 127.0.0.1:3099`:
      `GET /` **200** with a 30-day cookie minted, `GET /healthz` **200 application/json**,
      `GET /api` with no cookie **401**, and the engine itself still refuses a foreign Host
      with **403** when reached directly.

  So the gate is the single door and the fence stays closed: no network name is ever added to
  `trustedHosts`. That is strictly better than the `--trusted-host` shape in
  `docs/mesh/50-transport.md` §2.1, and it needs no engine restart.

  This script is deliberately dumb, in the same shape as `ensure-mesh-prereqs.ps1`: start the
  gate if the port is not listening, record what it found, exit 0 unless something is broken.
  It never stops a process, never touches the engine, and never changes the Serve config —
  publication is a separate, owner-visible act (`-Publish` does it and says so).

.PARAMETER ListenPort
  The loopback port the gate listens on. Tailscale Serve points here, never at the engine.

.PARAMETER EnginePort
  The port the node's one engine already listens on. 3099 is the launcher's default.

.PARAMETER EngineAuthority
  What the gate presents to the engine as Host AND Origin. Defaults to `127.0.0.1:<EnginePort>`,
  which is the value that keeps the fence closed. Only set it to something else if the engine
  was launched with `--trusted-host` for that name.

.PARAMETER Publish
  Also run `tailscale serve --bg <ListenPort>`. Off by default: publishing is visible to the
  owner's whole tailnet and should be a decision, not a side effect.

.PARAMETER Status
  Print the last recorded run and the live state, change nothing.

.EXAMPLE
  pwsh -File scripts\phone-gate-ensure.ps1 -Status
  pwsh -File scripts\phone-gate-ensure.ps1 -Publish

.EXAMPLE
  # Register it so it survives a reboot and restarts the gate if it dies (no admin needed):
  $a = New-ScheduledTaskAction -Execute 'C:\Program Files\PowerShell\7\pwsh.exe' `
       -Argument '-NoProfile -NonInteractive -WindowStyle Hidden -File "C:\Users\ezabz\code\harness-config\scripts\phone-gate-ensure.ps1"'
  $t1 = New-ScheduledTaskTrigger -AtLogOn
  $t2 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  Register-ScheduledTask -TaskName 'DSH Phone Gate' -Action $a -Trigger $t1,$t2 `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit 0 -MultipleInstances IgnoreNew) -Force
#>
[CmdletBinding()]
param(
    [int]$ListenPort = 3086,
    [int]$EnginePort = 3099,
    [string]$EngineAuthority = "",
    [switch]$Publish,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
if (-not $EngineAuthority) { $EngineAuthority = "127.0.0.1:$EnginePort" }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$gate = Join-Path $scriptDir 'phone-gate.py'
$stateDir = Join-Path $env:LOCALAPPDATA 'dsh-phone'
$statusDir = Join-Path $env:USERPROFILE '.dsh-sync-status'
$statusFile = Join-Path $statusDir 'phone-gate.json'
$logFile = Join-Path $stateDir "gate-$ListenPort.log"
$errFile = Join-Path $stateDir "gate-$ListenPort.err"

function Say-Log([string]$message) {
    if (-not (Test-Path $statusDir)) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'), $message
    # FULLY QUALIFIED, because `dshw.ps1` defines its OWN function named `Add-Content` (a wrapper
    # around its per-slot log writer). PowerShell resolves functions through the caller's scope
    # chain, so when this script is invoked from `dshw ensure` — which is how it runs every minute —
    # a bare `Add-Content -Path` binds to THAT function and dies with "A parameter cannot be found
    # that matches parameter name 'Path'". Measured 2026-09-16: the gate self-healed and the status
    # record was written, but the log line was lost and the watchdog printed a red failure.
    Microsoft.PowerShell.Management\Add-Content -Path (Join-Path $statusDir 'phone-gate.log') -Value $line
    Write-Host $line
}

function Get-Listener([int]$port) {
    Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
}

if ($Status) {
    $l = Get-Listener $ListenPort
    "gate port $ListenPort : " + $(if ($l) { "listening (pid $($l.OwningProcess))" } else { 'NOT listening' })
    $e = Get-Listener $EnginePort
    "engine port $EnginePort : " + $(if ($e) { "listening (pid $($e.OwningProcess))" } else { 'NOT listening' })
    "serve: " + ((& tailscale serve status 2>&1) -join ' ').Trim()
    "last status record:"
    if (Test-Path $statusFile) { Get-Content $statusFile -Raw } else { '  none recorded yet' }
    return
}

$findings = @()
$repaired = @()
$failed = @()

if (-not (Test-Path $gate)) { $failed += "phone-gate.py not found at $gate" }

if ($failed.Count -eq 0) {
    $existing = Get-Listener $ListenPort
    if ($existing) {
        $findings += "gate:${ListenPort}:already-listening:pid=$($existing.OwningProcess)"
    } else {
        if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
        $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
        if (-not $python) { $failed += 'python.exe not on PATH' }
        else {
            $gateArgs = @('--listen-port', "$ListenPort", '--engine-port', "$EnginePort")
            if ($EngineAuthority) { $gateArgs += @('--engine-authority', $EngineAuthority) }

            # LAUNCH THROUGH VBSCRIPT, NOT Start-Process, AND WITHOUT `cmd /c` OR REDIRECTION.
            # Two measured failures on 2026-09-16 produced this shape:
            #  1. A nested `pwsh -File phone-gate-ensure.ps1` never returned: the tool running it hit
            #     its 120 s ceiling and killed the whole process tree, gate included. The work had
            #     actually succeeded (the status record says `repaired`) and the gate died anyway.
            #  2. Routing the child through `cmd /c "...python.exe" "...phone-gate.py" >> log 2>> err`
            #     produced a gate that never started and an empty error file — cmd's quote handling
            #     around a quoted program plus redirection is not something to build on.
            # `WScript.Shell.Run(line, 0, False)` starts the child hidden, does not wait, and gives it
            # no inherited handle on the caller's stdout (the same reason HiddenTaskAction.ps1 exists).
            # The gate writes its own log with --log-file, so no redirection is needed at all.
            $vbs = Join-Path $stateDir "phone-gate-$ListenPort.vbs"
            $line = '"{0}" "{1}" {2} --log-file "{3}"' -f $python, $gate, ($gateArgs -join ' '), $logFile
            $vbsBody = @(
                "' Generated by phone-gate-ensure.ps1 - hidden, detached launcher for the phone gate.",
                'Set sh = CreateObject("WScript.Shell")',
                ('WScript.Quit sh.Run("{0}", 0, False)' -f $line.Replace('"', '""'))
            ) -join "`r`n"
            [System.IO.File]::WriteAllText($vbs, $vbsBody + "`r`n", (New-Object System.Text.UTF8Encoding($false)))

            try {
                $wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
                Start-Process -FilePath $wscript -ArgumentList @('//B', '//NoLogo', $vbs) -WindowStyle Hidden | Out-Null
                Start-Sleep -Seconds 3
                $now = Get-Listener $ListenPort
                if ($now) {
                    $findings += "gate:${ListenPort}:started:pid=$($now.OwningProcess)"
                    $repaired += "started the gate on $ListenPort -> engine $EnginePort as $EngineAuthority"
                } else {
                    $findings += "gate:${ListenPort}:start-failed"
                    $failed += "the gate did not come up on $ListenPort; see $errFile"
                }
            } catch {
                $failed += "could not start the gate: $($_.Exception.Message)"
            }
        }
    }

    # The engine is NOT this script's job — but whether it is up decides whether the gate can
    # answer anything, and a phone that fails with no record of why is the failure this whole
    # file exists to remove. Report it; never start a second engine (windows.json:5).
    $engine = Get-Listener $EnginePort
    if ($engine) { $findings += "engine:${EnginePort}:listening:pid=$($engine.OwningProcess)" }
    else { $findings += "engine:${EnginePort}:NOT-listening"; Say-Log "phone-gate WARNING: no engine on $EnginePort - the gate will answer 502 until one is up" }
}

if ($Publish -and $failed.Count -eq 0) {
    # Ask before asserting. This runs from a one-minute watchdog, so re-running `tailscale serve`
    # unconditionally would spawn a CLI process 1,440 times a day on a machine whose whole purpose
    # in this program is to stop being busy. One `status` call (~100 ms) that usually answers
    # "already right" is the honest price of healing the case that actually happens: the Serve
    # config lives in the Tailscale daemon's state, so a daemon restart or a reboot loses it
    # silently while the gate keeps listening and nothing answers on the tailnet name.
    $live = ''
    try { $live = ((& tailscale serve status 2>&1) -join ' ') } catch { $live = '' }
    if ($live -match [regex]::Escape("127.0.0.1:$ListenPort")) {
        $findings += 'serve:already-published'
    } else {
        $serveOut = (& tailscale serve --bg $ListenPort 2>&1) -join ' '
        $findings += "serve:$($serveOut.Trim())"
        $repaired += "re-asserted tailscale serve -> $ListenPort"
        if ($serveOut -match '(?i)error|failed|not enabled') { $failed += "tailscale serve refused: $serveOut" }
    }
}

$result = if ($failed.Count -gt 0) { 'attention' } elseif ($repaired.Count -gt 0) { 'repaired' } else { 'clean' }
if (-not (Test-Path $statusDir)) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
@{
    updated = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    host    = $env:COMPUTERNAME
    result  = $result
    detail  = ($findings -join ' ')
    repaired = $repaired
    failed  = $failed
} | ConvertTo-Json -Depth 4 | Set-Content -Path $statusFile -Encoding UTF8

Say-Log "phone-gate host=$env:COMPUTERNAME result=$result $($findings -join ' ')"
if ($failed.Count -gt 0) { Say-Log "phone-gate FAILED: $($failed -join '; ')"; exit 1 }
exit 0
