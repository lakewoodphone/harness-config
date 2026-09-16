# push-harness-config-to-laptop.ps1 -- deliver the harness-config repo to a machine that cannot pull it.
#
# THE GAP THIS CLOSES, measured 2026-09-15.
# A machine's harness-config checkout is what `harness-sync.mjs` applies FROM. Yocheved's laptop has no
# route to this repo's origin (its origin is the office server; her laptop is on a separate network with
# no Tailscale), so its checkout was a dead copy frozen at 2026-09-14. The launcher on that machine had
# already been fixed in the repo, and she kept running the broken version for a day and a half -- which
# is precisely the failure the owner reported as "the shortcut opens a window and nothing happens".
# Settings were being APPLIED faithfully. Nothing was DELIVERING.
#
# WHAT IT DOES
#   1. asks origin what master is, and stops if that exact commit was already delivered;
#   2. builds a zip of the tracked tree WITHOUT `journal/` (see apply-harness-config-archive.ps1 for why
#      journal is never copied between machines);
#   3. pushes the zip to the target machine, pushes the apply script, runs it;
#   4. runs that machine's own `harness-sync.cmd`, so the delivered config is actually applied;
#   5. reads back HARNESS-CONFIG-APPLIED.json and only then records the commit as delivered.
#
# The last step is the point. "The task exited 0" is not evidence that a machine is current; a file on
# that machine naming the tree it received is.
#
# Usage:
#   pwsh -File push-harness-config-to-laptop.ps1                 # deliver if origin/master moved
#   pwsh -File push-harness-config-to-laptop.ps1 -Force          # deliver even if it looks current
#   pwsh -File push-harness-config-to-laptop.ps1 -DryRun         # say what would happen
param(
    [string]$RepoRoot = '',
    [string]$Machine = 'DESKTOP-FGV6KMH',
    [string]$RemoteTarget = 'C:\Users\cheve\code\harness-config',
    [string]$RemoteIncoming = 'C:\Users\cheve\.dsh\_incoming',
    [string]$SyncCommand = 'C:\Users\cheve\code\harness-config\scripts\harness-sync.cmd',
    [string]$EnvFile = '',
    [string]$ExecBase = 'https://yocheved-cmd.abletelsolutions.com',
    [string]$StatePath = '',
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
if (-not $StatePath) {
    $StatePath = Join-Path $env:USERPROFILE '.dsh\push-harness-config-state.json'
}
$logDir = Join-Path $env:USERPROFILE '.dsh\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'push-harness-config.log'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
    Add-Content -LiteralPath $log -Value $line -ErrorAction SilentlyContinue
    Write-Output $line
}

# ── credentials ──────────────────────────────────────────────────────────────────────────────────
if (-not $EnvFile) {
    foreach ($c in @(
            (Join-Path $RepoRoot '..\personal-secretary-mvp\.env'),
            (Join-Path $env:USERPROFILE 'code\personal-secretary-mvp\.env'),
            (Join-Path $env:USERPROFILE 'personal-secretary-mvp\.env'))) {
        if (Test-Path $c) { $EnvFile = (Resolve-Path $c).Path; break }
    }
}
if (-not $EnvFile -or -not (Test-Path $EnvFile)) { Log "FAIL: no .env with the Cloudflare service token found"; exit 3 }

function Get-EnvVal([string]$key) {
    $line = Select-String -Path $EnvFile -Pattern "^$key=" | Select-Object -First 1
    if (-not $line) { return '' }
    return ($line.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
}
$cid = Get-EnvVal 'CF_ACCESS_CLIENT_ID'
$csec = Get-EnvVal 'CF_ACCESS_CLIENT_SECRET'
$token = Get-EnvVal 'YOCHEVED_EXEC_TOKEN'
if (-not $token) { $token = '81c7964f032db5ae' }   # the exec service's own shared token
if (-not $cid -or -not $csec) { Log "FAIL: CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET missing from $EnvFile"; exit 3 }

$headers = @{
    'CF-Access-Client-Id'     = $cid
    'CF-Access-Client-Secret' = $csec
    'X-Auth-Token'            = $token
}

function Invoke-Exec([string]$code, [int]$timeoutSec = 110) {
    # The exec service runs `cmd /c powershell -EncodedCommand <b64 of this string>`, so the payload is
    # PowerShell source and never touches cmd.exe quoting. Send PowerShell, not a shell pipeline.
    $body = @{ cmd = $code } | ConvertTo-Json -Compress
    return Invoke-RestMethod -Uri "$ExecBase/exec" -Method Post -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec $timeoutSec
}

function Write-Remote([string]$path, [byte[]]$bytes, [int]$timeoutSec = 115) {
    $body = @{ path = $path; b64 = [Convert]::ToBase64String($bytes) } | ConvertTo-Json -Compress
    return Invoke-RestMethod -Uri "$ExecBase/write" -Method Post -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec $timeoutSec
}

function Read-Remote([string]$path) {
    $uri = "$ExecBase/read?path=$([uri]::EscapeDataString($path))"
    return Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 60
}

# ── what does origin say master is? ──────────────────────────────────────────────────────────────
Push-Location $RepoRoot
try {
    & git fetch origin --quiet 2>&1 | Out-Null
    $head = (& git rev-parse origin/master).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $head) { Log 'FAIL: could not resolve origin/master'; exit 3 }

    $state = if (Test-Path $StatePath) { Get-Content -Raw $StatePath | ConvertFrom-Json } else { $null }
    if (-not $DryRun -and -not $Force -and $state -and $state.$Machine -eq $head) {
        Log "current: $Machine already has $($head.Substring(0,8))"
        exit 0
    }

    Log "deliver: $Machine <- origin/master $($head.Substring(0,8))"

    $tmp = Join-Path $env:TEMP ("hc-push-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'harness-config.zip'
    $applyLocal = Join-Path $RepoRoot 'scripts\apply-harness-config-archive.ps1'
    if (-not (Test-Path $applyLocal)) { Log 'FAIL: scripts/apply-harness-config-archive.ps1 missing from the checkout'; exit 3 }

    # journal/ is excluded at BUILD time as well as at apply time: two independent refusals, because the
    # one thing this must never do is put different content under a journal id that already exists.
    $paths = @(& git ls-tree --name-only origin/master) | Where-Object { $_ -and $_ -ne 'journal' }
    & git archive --format=zip -o $zip origin/master -- $paths 2>&1 | Out-Null
    if (-not (Test-Path $zip)) { Log 'FAIL: git archive produced nothing'; exit 3 }
    $zipBytes = [System.IO.File]::ReadAllBytes($zip)
    Log ("archive: {0:N0} bytes, {1} top-level paths" -f $zipBytes.Length, $paths.Count)

    if ($DryRun) { Log "dry run: would push to $RemoteTarget"; exit 0 }

    # 1. the archive
    $r = Write-Remote (Join-Path $RemoteIncoming 'harness-config.zip') $zipBytes
    Log ("push archive: " + $r.bytes + " bytes")

    # 2. the applier, to a path the archive also carries, so the two cannot drift
    $applyRemote = ($RemoteTarget.TrimEnd('\') + '\scripts\apply-harness-config-archive.ps1')
    $r = Write-Remote $applyRemote ([System.IO.File]::ReadAllBytes($applyLocal))
    Log ("push applier: " + $r.bytes + " bytes")

    # 3. apply
    $applyCmd = "& '$applyRemote' -Archive '$RemoteIncoming\harness-config.zip' -Target '$RemoteTarget' -TreeId '$head'"
    $resp = Invoke-Exec $applyCmd
    $out = ($resp.stdout -join "`n")
    Log ("apply exit=" + $resp.exit + " timedout=" + $resp.timedout)
    foreach ($l in ($out -split "`n" | Where-Object { $_ -match '^apply: ' })) { Log ("  " + $l.Trim()) }
    if ($resp.timedout -or $resp.exit -ne 0) { Log 'FAIL: the apply step did not complete'; exit 1 }

    # 4. make the delivered config take effect
    $resp = Invoke-Exec ("& '$SyncCommand'")
    Log ("harness-sync exit=" + $resp.exit + " timedout=" + $resp.timedout)
    if ($resp.timedout -or $resp.exit -ne 0) { Log 'FAIL: harness-sync did not complete'; exit 1 }

    # 5. prove it, from that machine's own record
    $markerPath = ($RemoteTarget.TrimEnd('\') + '\HARNESS-CONFIG-APPLIED.json')
    $marker = Read-Remote $markerPath
    if (-not $marker.exists) { Log "FAIL: $markerPath was not written"; exit 1 }
    # TrimStart the byte-order mark: the marker is written by whatever PowerShell the machine has, and
    # an older one emits a BOM that ConvertFrom-Json refuses on its first character.
    $markerText = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($marker.b64)).TrimStart([char]0xFEFF)
    $applied = $markerText | ConvertFrom-Json
    if ($applied.tree -ne $head) { Log ("FAIL: machine reports tree " + $applied.tree + " but master is " + $head); exit 1 }

    $rec = [ordered]@{}
    if ($state) { foreach ($p in $state.PSObject.Properties) { $rec[$p.Name] = $p.Value } }
    $rec[$Machine] = $head
    $rec['lastDeliveredAt'] = (Get-Date).ToUniversalTime().ToString('o')
    $rec | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding utf8

    Log ("verified: $Machine reports tree $($applied.tree.Substring(0,8)) (added=$($applied.added) updated=$($applied.updated) unchanged=$($applied.unchanged))")
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} finally {
    Pop-Location
}
