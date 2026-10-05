# loop-lag-probe.ps1 — what makes the DSH engine's event loop late?
#
# WHY. Measured 2026-10-05 on ZABZ-YOGA: the engine's self-timed loop lag is p50 ~77-80 ms and
# p95 1.4-1.5 s with max 5.2-7.4 s while 14 agent loops execute. That lag is the multiplier behind
# everything else measured that night: a session-list walk of ~7 500 awaited round-trips took 219 s
# where the same disk work takes 6.8 s (7 500 x 73 ms = 511 s, and the p50 IS 73-80 ms), and every
# interactive call queues behind it. The fix for the walk was to overlap the waits; the fix for the
# lag itself needs to know WHAT blocks the loop, which needs a time series, not a single reading.
#
# This is that time series. One cheap authenticated GET to the engine's own /healthz per sample,
# which already carries loop p50/p95/max, heap, RSS, sessions, live agent loops and process counts,
# plus a per-process CPU DELTA for the biggest consumers (cumulative CPU says nothing about now).
#
# It is deliberately ONE long-lived PowerShell process rather than a tool call per sample: on this
# machine a trivial `pwsh` start costs ~540-700 ms of CPU, so polling from a session would cost more
# than the thing being measured.
#
# USAGE
#   pwsh -NoProfile -File loop-lag-probe.ps1                       # 60 samples x 10 s = 10 min
#   pwsh -NoProfile -File loop-lag-probe.ps1 -Samples 20 -IntervalSeconds 5
# Output: %USERPROFILE%\.dsh\metrics\loop-lag-<stamp>.csv   (append-only; the summary is printed too)
param(
    [int]$Samples = 60,
    [int]$IntervalSeconds = 10,
    [int]$Port = 3099,
    [string]$OutDir = (Join-Path $env:USERPROFILE '.dsh\metrics')
)

$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$csv = Join-Path $OutDir "loop-lag-$stamp.csv"
$rows = New-Object System.Collections.Generic.List[object]

# ── the launch token is per engine process and lives only in the launcher log ───────────────────
function Get-EngineToken([int]$enginePort) {
    $dir = Join-Path $env:USERPROFILE '.dsh\multi-window\logs'
    $cands = @()
    $p = Join-Path $dir "$enginePort.log"
    if (Test-Path $p) { $cands += Get-Item -LiteralPath $p }
    $cands += @(Get-ChildItem -LiteralPath $dir -Filter "$enginePort-*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 5)
    foreach ($f in $cands) {
        $m = [regex]::Matches((Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue), 'token=([A-Za-z0-9_-]+)')
        if ($m.Count -gt 0) { return $m[$m.Count - 1].Groups[1].Value }
    }
    return $null
}
function New-EngineCookie([int]$enginePort, [string]$token) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$enginePort/?token=$token" -MaximumRedirection 0 -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 20
        $set = @($r.Headers['Set-Cookie']) | Select-Object -First 1
        if ($set) { return ($set -split ';')[0] }
    } catch { }
    return $null
}

$token = Get-EngineToken $Port
if (-not $token) { Write-Host "no launch token in the launcher logs -- cannot authenticate"; exit 2 }
$cookie = New-EngineCookie $Port $token
if (-not $cookie) { Write-Host "could not mint a cookie"; exit 2 }
Write-Host "probing :$Port every ${IntervalSeconds}s for $Samples sample(s) -> $csv"

$prevCpu = @{}
$header = 'ts,loops,sessions,lagP50,lagP95,lagMax,heapUsedMB,heapTotalMB,rssMB,availGB,commitLimitGB,procs,threads,top1,top1cores,top2,top2cores,top3,top3cores'
$header | Set-Content -LiteralPath $csv -Encoding utf8

for ($i = 1; $i -le $Samples; $i++) {
    $sample = [ordered]@{ ts = (Get-Date).ToUniversalTime().ToString('HH:mm:ss') }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" -Headers @{ Cookie = $cookie } -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 15
        if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
        $h = $r.Content | ConvertFrom-Json
        $sample.loops = $h.sessions.agentLoopsRunning
        $sample.sessions = $h.sessions.live
        $sample.lagP50 = $h.loop.p50Ms
        $sample.lagP95 = $h.loop.p95Ms
        $sample.lagMax = $h.loop.maxMs
        $sample.heapUsedMB = [math]::Round($h.memory.heapUsed / 1MB, 1)
        $sample.heapTotalMB = [math]::Round($h.memory.heapTotal / 1MB, 1)
        $sample.rssMB = [math]::Round($h.memory.rss / 1MB, 1)
        $sample.availGB = [math]::Round($h.system.physicalAvailableBytes / 1GB, 2)
        # LABEL HONESTY: this is the commit LIMIT, not free commit. It was labelled commitFreeGB for
        # its first run, which is exactly the class of wrong number that makes an instrument useless
        # (the 10.7%-disk-free warning below came from the same kind of reading being trusted).
        $sample.commitLimitGB = [math]::Round($h.system.probe.commitLimitBytes / 1GB, 2)
        $sample.procs = $h.processes.total
        $sample.threads = $h.processes.threads
    } catch {
        $sample.loops = $sample.sessions = $sample.lagP50 = $sample.lagP95 = $sample.lagMax = ''
        $sample.heapUsedMB = $sample.heapTotalMB = $sample.rssMB = $sample.availGB = $sample.commitLimitGB = ''
        $sample.procs = $sample.threads = ''
        $sample.error = $true
    }

    # per-process CPU delta: who is actually burning the machine at this instant
    $cur = @{}
    $procs = Get-Process -ErrorAction SilentlyContinue
    foreach ($p in $procs) { $cur[$p.Id] = $p.CPU }
    $top = @()
    if ($prevCpu.Count -gt 0) {
        foreach ($p in $procs) {
            if ($prevCpu.ContainsKey($p.Id)) {
                $d = ($p.CPU - $prevCpu[$p.Id]) / $IntervalSeconds
                if ($d -gt 0.15) { $top += [pscustomobject]@{ name = "$($p.ProcessName)#$($p.Id)"; cores = [math]::Round($d, 2) } }
            }
        }
        $top = @($top | Sort-Object cores -Descending | Select-Object -First 3)
    }
    $prevCpu = $cur
    for ($k = 0; $k -lt 3; $k++) {
        $sample["top$($k+1)"] = if ($k -lt $top.Count) { $top[$k].name } else { '' }
        $sample["top$($k+1)cores"] = if ($k -lt $top.Count) { $top[$k].cores } else { '' }
    }

    $line = ($header -split ',') | ForEach-Object { $v = $sample[$_]; if ($null -eq $v) { '' } else { $v } }
    ($line -join ',') | Add-Content -LiteralPath $csv -Encoding utf8
    $rows.Add([pscustomobject]$sample)
    if ($i % 6 -eq 0 -or $i -eq 1) { Write-Host ("  [{0}/{1}] p50={2} p95={3} max={4} loops={5} heap={6}MB" -f $i, $Samples, $sample.lagP50, $sample.lagP95, $sample.lagMax, $sample.loops, $sample.heapUsedMB) }
    if ($i -lt $Samples) { Start-Sleep -Seconds $IntervalSeconds }
}

# ── summary: the correlation that the single reading could not give ────────────────────────────
$ok = @($rows | Where-Object { $_.lagP50 -ne '' -and $null -ne $_.lagP50 })
Write-Host ""
Write-Host "=== SUMMARY over $($ok.Count) good sample(s) ==="
if ($ok.Count -ge 3) {
    $lagP50 = @($ok | ForEach-Object { [double]$_.lagP50 })
    Write-Host ("lag p50: min {0} mean {1} max {2} ms" -f ($lagP50 | Measure-Object -Minimum).Minimum, [math]::Round(($lagP50 | Measure-Object -Average).Average, 1), ($lagP50 | Measure-Object -Maximum).Maximum)
    $mx = @($ok | ForEach-Object { [double]$_.lagMax })
    Write-Host ("lag max: min {0} mean {1} max {2} ms" -f ($mx | Measure-Object -Minimum).Minimum, [math]::Round(($mx | Measure-Object -Average).Average, 1), ($mx | Measure-Object -Maximum).Maximum)

    # lag bucketed by how many agent loops were executing at that moment
    Write-Host "--- lag by concurrent agent loops ---"
    $ok | Group-Object loops | Sort-Object Name | ForEach-Object {
        $m = ($_.Group | ForEach-Object { [double]$_.lagP50 } | Measure-Object -Average).Average
        $x = ($_.Group | ForEach-Object { [double]$_.lagMax } | Measure-Object -Average).Average
        Write-Host ("  loops={0,-3} n={1,-4} mean p50={2,6:N1} ms   mean max={3,7:N1} ms" -f $_.Name, $_.Count, $m, $x)
    }

    # does lag track heap growth (allocation/GC) or heap size?
    Write-Host "--- heap vs lag ---"
    $hu = @($ok | ForEach-Object { [double]$_.heapUsedMB })
    Write-Host ("  heapUsedMB: min {0} mean {1} max {2}" -f ($hu | Measure-Object -Minimum).Minimum, [math]::Round(($hu | Measure-Object -Average).Average, 1), ($hu | Measure-Object -Maximum).Maximum)
    $hi = @(); $lo = @()
    for ($k = 1; $k -lt $ok.Count; $k++) {
        $dHeap = [double]$ok[$k].heapUsedMB - [double]$ok[$k-1].heapUsedMB
        if ([math]::Abs($dHeap) -lt 1) { continue }
        if ($dHeap -gt 0) { $hi += [double]$ok[$k].lagP50 } else { $lo += [double]$ok[$k].lagP50 }
    }
    $hiMean = if ($hi.Count) { [math]::Round(($hi | Measure-Object -Average).Average, 1) } else { 'n/a' }
    $loMean = if ($lo.Count) { [math]::Round(($lo | Measure-Object -Average).Average, 1) } else { 'n/a' }
    Write-Host ("  p50 lag after heap GREW: {0} ms (n={1})   after heap SHRANK: {2} ms (n={3})" -f $hiMean, $hi.Count, $loMean, $lo.Count)

    # the biggest single jumps, with the top CPU consumer at that moment
    Write-Host "--- the 5 worst samples ---"
    $ok | Sort-Object { [double]$_.lagMax } -Descending | Select-Object -First 5 | ForEach-Object {
        Write-Host ("  {0}  p50={1,4} p95={2,5} max={3,6} ms  loops={4,-3} heap={5,6}MB  top: {6} ({7})" -f $_.ts, $_.lagP50, $_.lagP95, $_.lagMax, $_.loops, $_.heapUsedMB, $_.top1, $_.top1cores)
    }
}
Write-Host ""
Write-Host "csv: $csv"
