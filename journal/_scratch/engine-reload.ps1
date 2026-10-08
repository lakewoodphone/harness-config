# Reload the DSH engine on 3099 and PROVE it came back.
#
# WHY THIS IS A SCRIPT AND NOT A ONE-LINER: the two fixes it loads (the remote child turn cap
# in profiles/*/cordis.patch.yml, and enableRunInBackground on the mesh subagent rows in the
# zabz preset) are both read at composition time, so neither is live until the engine is
# rebuilt. A reload that fails and says nothing would leave the owner with no DSH at all and
# no explanation -- and this repo has already lost an engine that way
# (multi-window/engine-recovery.log: a start that exited 1 with MODULE_NOT_FOUND while the
# log filled with "port 3099 not answering").
#
# So: stop, start, then poll HTTP until it actually answers, and fall back to `dshw ensure`.
# The result goes to a log a later session can read, whether or not anyone was watching.
$ErrorActionPreference = 'Continue'
$log  = 'C:\Users\ezabz\code\harness-config\_scratch\engine-reload.log'
$dshw = 'C:\Users\ezabz\code\harness-config\multi-window\dshw.ps1'

function W($m) { "[{0}] {1}" -f (Get-Date -Format o), $m | Add-Content -LiteralPath $log -Encoding utf8 }
function Eng { (Get-NetTCPConnection -LocalPort 3099 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess }

W "=== reload requested; engine pid before = $(Eng) ==="
try {
    & pwsh -NoProfile -File $dshw stop 2>&1 | ForEach-Object { W "stop: $_" }
    Start-Sleep -Seconds 4
    & pwsh -NoProfile -File $dshw up 2>&1 | ForEach-Object { W "up: $_" }

    $ok = $false
    for ($i = 1; $i -le 24; $i++) {
        Start-Sleep -Seconds 5
        try {
            $c = [System.Net.Http.HttpClient]::new()
            $c.Timeout = [TimeSpan]::FromSeconds(4)
            $r = $c.GetAsync('http://127.0.0.1:3099/').GetAwaiter().GetResult()
            $c.Dispose()
            W "attempt $i : HTTP $([int]$r.StatusCode) - engine is answering"
            $ok = $true
            break
        }
        catch { W "attempt $i : $($_.Exception.Message)" }
    }

    if (-not $ok) {
        W "engine never answered; falling back to ensure"
        & pwsh -NoProfile -File $dshw ensure 2>&1 | ForEach-Object { W "ensure: $_" }
    }
    W "=== reload finished ok=$ok engine pid after = $(Eng) ==="
}
catch { W "FATAL: $($_.Exception.Message)" }
finally { schtasks /Delete /TN 'ZabzEngineReload' /F 2>&1 | ForEach-Object { W "task delete: $_" } }
