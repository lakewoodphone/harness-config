# Reload-DshEngine.ps1 — stop the DSH engine on 3099, start it again, and PROVE it came back.
#
# WHY THIS IS A SCRIPT AND NOT A ONE-LINER. Several settings are read at COMPOSITION time — the remote
# child turn cap, the `prefer-remote` policy, the ssh hop arguments — so none of them is live until the
# engine is rebuilt. A reload that fails and says nothing would leave the owner with no DSH at all, and
# this repo has already lost an engine that way (multi-window/engine-recovery.log: a start that exited 1
# with MODULE_NOT_FOUND while the log filled with "port 3099 not answering").
#
# WHY IT USES `stop` + `up` AND NOT `restart`: `dshw restart` also reopens EVERY declared window, which on
# a shared-profile machine means opening the full declared set at once. This script changes the
# configuration and leaves the windows alone.
#
# THE BUG THIS VERSION FIXES, measured twice on 2026-09-18. `dshw up` starts the engine as a LONG-LIVED
# child. Piping its output (`& pwsh -File dshw.ps1 up 2>&1 | ForEach-Object ...`) therefore makes this
# script wait for the ENGINE to exit, which it never does — so the script hung forever, its scheduled task
# sat in "Running", and an orphaned pwsh held the engine's stdout open. Redirect to FILES and bound the
# wait, exactly as every mesh brief requires of every ssh hop (docs/mesh/115).
#
# Usage:
#   pwsh -NoProfile -File scripts/mesh/Reload-DshEngine.ps1 [-DelaySeconds 45]
#
# `-DelaySeconds` exists so the caller's own turn can finish and be delivered before the engine bounces;
# the bounce kills any turn in flight, which is why it is deferred rather than immediate.

[CmdletBinding()]
param(
    [int]$DelaySeconds = 0,
    [string]$Dshw = '',
    [int]$UpTimeoutSec = 180,
    [string]$LogFile = ''
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Dshw) {
    $Dshw = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) 'multi-window\dshw.ps1'
}
if (-not (Test-Path $Dshw)) { Write-Error "dshw.ps1 not found at '$Dshw'"; exit 2 }
if (-not $LogFile) { $LogFile = Join-Path $env:TEMP 'dsh-engine-reload.log' }

function W($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format o), $m
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding utf8
}
function Eng { (Get-NetTCPConnection -LocalPort 3099 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess }

if ($DelaySeconds -gt 0) { W "delaying $DelaySeconds s so the caller's turn can complete before the bounce"; Start-Sleep -Seconds $DelaySeconds }

W "=== reload requested; engine pid before = $(Eng) ==="

# --- stop. `dshw stop` terminates the engine, so its pipeline is not held open by a long-lived child. ---
& pwsh -NoProfile -File $Dshw stop 2>&1 | ForEach-Object { W "stop: $_" }
Start-Sleep -Seconds 4

# --- up, REDIRECTED TO FILES AND BOUNDED. Never piped: the engine outlives the pipeline. ---
$upOut = Join-Path $env:TEMP ('dshw-up-' + [guid]::NewGuid() + '.out')
$upErr = Join-Path $env:TEMP ('dshw-up-' + [guid]::NewGuid() + '.err')
$proc = Start-Process -FilePath 'pwsh' -NoNewWindow -PassThru `
    -RedirectStandardOutput $upOut -RedirectStandardError $upErr `
    -ArgumentList @('-NoProfile', '-File', $Dshw, 'up')
$exited = $proc.WaitForExit($UpTimeoutSec * 1000)
if (-not $exited) { try { $proc.Kill() } catch { } ; W "up: KILLED after ${UpTimeoutSec}s (the engine may still be starting)" }
foreach ($line in @(Get-Content $upOut -ErrorAction SilentlyContinue)) { W "up: $line" }
foreach ($line in @(Get-Content $upErr -ErrorAction SilentlyContinue)) { W "up-err: $line" }
Remove-Item $upOut, $upErr -ErrorAction SilentlyContinue

# --- prove it answers. An HTTP status of any kind is success; a refused connection is not. ---
$ok = $false
for ($i = 1; $i -le 24; $i++) {
    Start-Sleep -Seconds 5
    try {
        $c = [System.Net.Http.HttpClient]::new()
        $c.Timeout = [TimeSpan]::FromSeconds(4)
        $r = $c.GetAsync('http://127.0.0.1:3099/').GetAwaiter().GetResult()
        $c.Dispose()
        W "attempt $i : HTTP $([int]$r.StatusCode) — engine is answering"
        $ok = $true
        break
    }
    catch { W "attempt $i : $($_.Exception.Message)" }
}
if (-not $ok) {
    W 'engine never answered; falling back to ensure'
    & pwsh -NoProfile -File $Dshw ensure 2>&1 | ForEach-Object { W "ensure: $_" }
}
W "=== reload finished ok=$ok engine pid after = $(Eng) ==="
if (-not $ok) { exit 1 }
