# Measured mesh inventory — the foundation deliverable of the mesh goal.
#
# WHY THIS SHAPE: nodes.js carries a hand-written table whose "verified" strings date from
# 2026-09-16/17 and are the ONLY record of what each node can do. A placement decision made
# from a stale table is the same class of error as reading a stale database. This script
# measures instead: reachability, cores, memory, commit, disk, node/dsh presence, and the
# wall-clock cost of the ssh round trip, per node, right now.
#
# It writes JSONL (one line per node) plus a markdown table, and it never writes anything
# on a remote node: every probe is a read.
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ssh  = 'C:\Program Files\OpenSSH\ssh.exe'
$outJ = Join-Path $here 'inventory.jsonl'
$outM = Join-Path $here 'INVENTORY.md'
$OutputEncoding = [Text.Encoding]::UTF8

$nodes = @(
    @{ name = 'laptop-ts';    note = 'ZABZ-YOGA (laptop, this machine)';  mode = 'local' },
    @{ name = 'desktop-ts';   note = 'ZABZ-TECH (office desktop)';        mode = 'ssh'; shell = 'powershell' },
    @{ name = 'secratary-ts'; note = 'secratary (Linux authority)';       mode = 'ssh'; shell = 'posix' },
    @{ name = 'linux-pc-ts';  note = 'zabz-tech-linux';                   mode = 'ssh'; shell = 'posix' },
    @{ name = 'mac-mini-ts';  note = 'LakewooechsMini (macOS)';           mode = 'ssh'; shell = 'posix' }
)

$results = @()
foreach ($n in $nodes) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $raw = ''
    $err = ''
    try {
        if ($n.mode -eq 'local') {
            $raw = (& pwsh -NoProfile -File (Join-Path $here 'probe.ps1') 2>$null | Out-String).Trim()
        }
        elseif ($n.shell -eq 'powershell') {
            $raw = (Get-Content (Join-Path $here 'probe.ps1') -Raw |
                    & $ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 $n.name 'powershell -NoProfile -Command -' 2>&1 | Out-String).Trim()
        }
        else {
            $raw = (Get-Content (Join-Path $here 'probe.sh') -Raw |
                    & $ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 $n.name 'sh -s' 2>&1 | Out-String).Trim()
        }
    }
    catch { $err = $_.Exception.Message }
    $sw.Stop()

    $jsonLine = ($raw -split "`n" | Where-Object { $_.TrimStart().StartsWith('{') } | Select-Object -Last 1)
    $obj = $null
    if ($jsonLine) { try { $obj = $jsonLine | ConvertFrom-Json } catch { } }

    $row = [ordered]@{
        node        = $n.name
        note        = $n.note
        measuredAt  = (Get-Date).ToUniversalTime().ToString('s') + 'Z'
        reachable   = [bool]$obj
        sshMs       = $sw.ElapsedMilliseconds
        error       = $err
        raw         = if ($obj) { $null } else { $raw.Substring(0, [Math]::Min(400, $raw.Length)) }
    }
    if ($obj) { foreach ($p in $obj.PSObject.Properties) { $row[$p.Name] = $p.Value } }
    $results += [pscustomobject]$row
    Write-Host ("[{0}] reachable={1} sshMs={2}" -f $n.name, [bool]$obj, $sw.ElapsedMilliseconds)
}

$results | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 4 } | Set-Content -LiteralPath $outJ -Encoding utf8

$lines = @()
$lines += '# Measured mesh inventory'
$lines += ''
$lines += ('Measured ' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm') + 'Z from ZABZ-YOGA by `_scratch/mesh-inventory/run-inventory.ps1`.')
$lines += 'Every cell is a reading from the node itself; `sshMs` is the wall-clock cost of the whole probe over ssh.'
$lines += ''
$lines += '| node | what | reachable | sshMs | cores | memTotalMiB | memFreeMiB | commitFreeMiB | cFreeGiB | node | dshOnPath | engineOn3099 | harness-config |'
$lines += '|---|---|---|---|---|---|---|---|---|---|---|---|---|'
foreach ($r in $results) {
    $lines += ('| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} | {9} | {10} | {11} | {12} |' -f `
        $r.node, $r.note, $r.reachable, $r.sshMs, $r.cores, $r.memTotalMiB, $r.memFreeMiB,
        $r.commitFreeMiB, $r.cFreeGiB, $r.nodeVersion, $r.dshOnPath, $r.engineOn3099, $r.harnessConfig)
}
$lines += ''
$lines += 'Unreachable rows keep their error text in `inventory.jsonl`; an empty cell means the node did not answer that field, never that the field is zero.'
$lines | Set-Content -LiteralPath $outM -Encoding utf8
Write-Host ("wrote {0} and {1}" -f $outJ, $outM)
