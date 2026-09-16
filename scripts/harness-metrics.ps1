# harness-metrics.ps1 -- a continuous, cheap sample of this machine's pressure, for correlation.
#
# WHY THIS EXISTS (2026-09-16). The owner asked for a 2-3 hour record of what makes the laptop slow.
# A session cannot do that: a long session re-bills its whole history on every step (the largest
# single cost this fleet measured), so the monitor has to be a small process that runs on its own
# and writes to disk. This is that process.
#
# DESIGN NOTES
#   * One `Get-Counter` call per sample for every counter -- one sample of six counters is cheaper
#     than six calls and gives a consistent instant.
#   * One `Get-Process` call per sample; per-process CPU is a DELTA against the previous sample
#     (cumulative CPU says nothing about now), reported as % of the whole machine.
#   * The expensive CIM query (MCP servers, engines) runs every 5th sample only, and a failure
#     leaves those columns empty rather than aborting the row.
#   * Every row is flushed immediately, so an interrupted run still has all its data.
#
# USAGE
#   pwsh -NoProfile -File harness-metrics.ps1                     # 3 h at 20 s
#   pwsh -NoProfile -File harness-metrics.ps1 -IntervalSeconds 10 -Samples 1000
#
# Output: %USERPROFILE%\.dsh\metrics\harness-metrics.csv  (one row per sample, append-only)
param([int]$IntervalSeconds = 20, [int]$Samples = 540)

$ErrorActionPreference = 'Continue'
$dir = Join-Path $env:USERPROFILE '.dsh\metrics'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$csv = Join-Path $dir 'harness-metrics.csv'
$header = 'ts,commit_gb,avail_mb,pages_in_s,faults_s,disk_q,cpu_pct,procs,node,msedge,pwsh,conhost,cim_ok,mcp,engines,top1,top2,top3'
if (-not (Test-Path $csv)) { $header | Set-Content -Encoding utf8 $csv }

$prev = @{}
for ($i = 0; $i -lt $Samples; $i++) {
    $row = [ordered]@{
        ts = (Get-Date).ToString('s'); commit_gb = ''; avail_mb = ''; pages_in_s = ''; faults_s = ''
        disk_q = ''; cpu_pct = ''; procs = ''; node = ''; msedge = ''; pwsh = ''; conhost = ''
        cim_ok = ''; mcp = ''; engines = ''; top1 = ''; top2 = ''; top3 = ''
    }
    try {
        $c = Get-Counter '\Memory\Committed Bytes', '\Memory\Available MBytes',
                         '\Memory\Pages Input/sec', '\Memory\Page Faults/sec',
                         '\PhysicalDisk(_Total)\Avg. Disk Queue Length',
                         '\Processor Information(_Total)\% Processor Time' -MaxSamples 1 -ErrorAction Stop
        $s = $c.CounterSamples
        $row.commit_gb = [math]::Round($s[0].CookedValue / 1GB, 2)
        $row.avail_mb = [math]::Round($s[1].CookedValue)
        $row.pages_in_s = [math]::Round($s[2].CookedValue)
        $row.faults_s = [math]::Round($s[3].CookedValue)
        $row.disk_q = [math]::Round($s[4].CookedValue, 2)
        $row.cpu_pct = [math]::Round($s[5].CookedValue)
    } catch { }

    try {
        $procs = Get-Process -ErrorAction SilentlyContinue
        $row.procs = $procs.Count
        $row.node = @($procs | Where-Object Name -eq 'node').Count
        $row.msedge = @($procs | Where-Object Name -eq 'msedge').Count
        $row.pwsh = @($procs | Where-Object Name -eq 'pwsh').Count
        $row.conhost = @($procs | Where-Object Name -eq 'conhost').Count

        $top = @()
        foreach ($pr in $procs) {
            if ($null -eq $pr.CPU) { continue }
            if ($prev.ContainsKey($pr.Id)) {
                $d = (($pr.CPU - $prev[$pr.Id]) / $IntervalSeconds) * 100 / 22.0
                if ($d -ge 0.5) { $top += [pscustomobject]@{ n = $pr.Name; pct = [math]::Round($d, 1) } }
            }
            $prev[$pr.Id] = $pr.CPU
        }
        $top = @($top | Sort-Object pct -Descending | Select-Object -First 3)
        for ($k = 0; $k -lt $top.Count; $k++) { $row["top$($k+1)"] = "$($top[$k].n)=$($top[$k].pct)%" }
    } catch { }

    if ($i % 5 -eq 0) {
        try {
            $all = Get-CimInstance Win32_Process -ErrorAction Stop
            $row.mcp = @($all | Where-Object { $_.CommandLine -match 'mcp-fetch-server|@playwright/mcp|firecrawl-mcp|context7-mcp|mcp-remote|ps_mcp_server' }).Count
            $row.engines = @($all | Where-Object { $_.CommandLine -match 'dsh\\lib\\bin\.js\s+web' }).Count
            $row.cim_ok = 1
        } catch { }
    }

    ($row.Values | ForEach-Object { "$_" }) -join ',' | Add-Content -Path $csv -Encoding utf8
    Start-Sleep -Seconds $IntervalSeconds
}
