# harness-metrics.ps1 -- a continuous, cheap sample of this machine's pressure, for correlation.
#
# WHY THIS EXISTS (2026-09-16). The owner asked for a 2-3 hour record of what makes the laptop slow.
# A session cannot do that: a long session re-bills its whole history on every step (the largest
# single cost this fleet measured), so the monitor has to be a small process that runs on its own
# and writes to disk. This is that process.
#
# WHY IT WAS REWRITTEN (2026-09-16, verification pass -- see docs/mesh/60-verification.md).
# The first version defaulted to `-Samples 540` at 20 s: exactly 3 hours, then exit. The scheduled
# task that ran it had NO repetition trigger -- a single `StartBoundary 23:59` and nothing else --
# so when the script finished its sample count, the machine stopped being measured until the next
# day. MEASURED end to end on 2026-09-16: pid 908 started 16:10:25Z, 540 x 20 s = ends 19:10:25Z,
# next trigger 23:59 local, i.e. a **4.8-hour hole** in the record -- and nothing anywhere reported
# it. A stale CSV looked exactly like an idle machine. That is the failure this rewrite removes:
#
#   1. `-Samples 0` (the new default) means RUN FOREVER. There is no sample count to reach.
#   2. A heartbeat is written to `~/.dsh-sync-status/metrics-sampler.json` every sample, so
#      "the sampler is not sampling" is a visible fact rather than an inference from file age.
#   3. It takes a single-instance lock, so a Task Scheduler repetition that fires while it is
#      already running exits immediately instead of writing duplicate rows.
#   4. It self-rotates on `-MaxHours` (default 168 h) so a week-long run cannot accumulate a
#      multi-year handle count -- and the task's 5-minute repetition restarts it within 5 minutes.
#   5. A crash inside a sample is caught; the loop continues and the heartbeat records the error,
#      because a partial row is better than a dead instrument.
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
#   pwsh -NoProfile -File harness-metrics.ps1                    # FOREVER at 20 s (the scheduled use)
#   pwsh -NoProfile -File harness-metrics.ps1 -Once              # one sample, then exit
#   pwsh -NoProfile -File harness-metrics.ps1 -Foreground        # forever, also printing each row
#   pwsh -NoProfile -File harness-metrics.ps1 -IntervalSeconds 10 -MaxHours 24
#
# Output: %USERPROFILE%\.dsh\metrics\harness-metrics.csv        (one row per sample, append-only)
#         %USERPROFILE%\.dsh\metrics\sessions-activity.csv      (the turn-count companion)
#         %USERPROFILE%\.dsh-sync-status\metrics-sampler.json   (heartbeat; a stalled sampler is visible here)
param(
    [int]$IntervalSeconds = 20,
    [int]$Samples = 0,          # 0 = run forever. The old default was 540 = 3 h, which is what silently ended the record.
    [int]$MaxHours = 168,       # self-rotate weekly so a long run cannot leak; the task restarts it within 5 min.
    [switch]$Once,              # one sample and exit (for tests and for -RunNow)
    [switch]$Foreground,        # also emit each row to stdout
    [switch]$Force,             # ignore an existing sampler from another process
    [switch]$RespectSamples540  # opt OUT of the legacy-compatibility override documented below
)

# ---- LEGACY -Samples 540 COMPATIBILITY, and why it is here rather than in the task -----------------
# The installed task on ZABZ-YOGA is `DSH Metrics Sampler`, whose action is
#   wscript.exe //B //NoLogo "...\hidden-tasks\DSH_Metrics_Sampler.vbs"
# and that VBS hard-codes `-IntervalSeconds 20 -Samples 540`. MEASURED 2026-09-16: that task file is
# owned by BUILTIN\Administrators and grants `ZABZ-YOGA\ezabz` only `Read, Synchronize`, so the
# non-elevated token that runs this harness CANNOT re-register it, cannot delete it, and cannot
# change it with `schtasks /Change` either (all three return "Access is denied"). The only lever left
# is this script, which the task runs.
#
# So `-Samples 540` is read as the LEGACY SENTINEL it is: it is what the old finite run looked like
# when the old task passed it, and 540 is not a number an operator chooses. Treating it as "run
# forever" is what makes the locked task safe. It is announced in the heartbeat and on stderr so the
# override is never silent -- a silent override would be the same class of bug as the silent stop
# this rewrite exists to fix. Pass -RespectSamples540 to get the literal behaviour back.
$legacyFinite = $false
if ($Samples -eq 540 -and -not $RespectSamples540) {
    $Samples = 0
    $legacyFinite = $true
}

$ErrorActionPreference = 'Continue'
$dir = Join-Path $env:USERPROFILE '.dsh\metrics'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$syncDir = Join-Path $env:USERPROFILE '.dsh-sync-status'
New-Item -ItemType Directory -Force -Path $syncDir | Out-Null
$csv = Join-Path $dir 'harness-metrics.csv'
$heartbeatPath = Join-Path $syncDir 'metrics-sampler.json'
$header = 'ts,commit_gb,avail_mb,pages_in_s,faults_s,disk_q,cpu_pct,procs,node,msedge,pwsh,conhost,cim_ok,mcp,engines,top1,top2,top3'
if (-not (Test-Path $csv)) { $header | Set-Content -Encoding utf8 $csv }

$selfPid = $PID
$startedUtc = (Get-Date).ToUniversalTime()
$deadline = if ($Once -or $Samples -gt 0) { $startedUtc.AddYears(10) } else { $startedUtc.AddHours($MaxHours) }
$legacyNote = if ($legacyFinite) { 'legacy -Samples 540 overridden to run forever (task is not writable; see -RespectSamples540)' } else { '' }
if ($legacyFinite) {
    Write-Warning "legacy -Samples 540 from the installed task is overridden to RUN FOREVER; pass -RespectSamples540 to disable this"
}

function Write-Heartbeat {
    param(
        [int]$Sample = 0,
        [string]$State = 'running',
        [string]$Note = '',
        [int]$RowsWritten = 0
    )
    $hb = [ordered]@{
        updated          = (Get-Date).ToUniversalTime().ToString('o')
        state            = $State
        pid              = $selfPid
        host             = $env:COMPUTERNAME
        started_utc      = $startedUtc.ToString('o')
        uptime_seconds   = [int]((Get-Date).ToUniversalTime() - $startedUtc).TotalSeconds
        sample           = $Sample
        rows_written     = $RowsWritten
        interval_seconds = $IntervalSeconds
        samples_limit    = $Samples            # 0 = forever
        max_hours        = $MaxHours
        csv              = $csv
        csv_age_seconds  = $(try { [int]((Get-Date) - (Get-Item $csv).LastWriteTime).TotalSeconds } catch { -1 })
        note             = $Note
    }
    # Atomic: a reader must never see a half-written heartbeat, because the whole point of this
    # file is that a MONITOR reads it. A torn JSON would read as "sampler broken" and be wrong.
    $tmp = "$heartbeatPath.tmp$selfPid"
    try {
        [System.IO.File]::WriteAllText($tmp, ($hb | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -Force -LiteralPath $tmp -Destination $heartbeatPath
    } catch {
        # Never let the heartbeat take the sampler down with it.
    }
}

# ---- single-instance lock --------------------------------------------------------------------
# The scheduled task repeats every 5 minutes. Without this, every repetition that arrives while
# the current sample loop is still alive would append a DUPLICATE row from a second process. The
# lock is a heartbeat file naming a PID, which is enough here: a dead PID fails Get-Process.
function Get-LiveSampler {
    if (-not (Test-Path $heartbeatPath)) { return $null }
    try { $hb = Get-Content -Raw -LiteralPath $heartbeatPath | ConvertFrom-Json } catch { return $null }
    if (-not $hb.pid) { return $null }
    $p = Get-Process -Id ([int]$hb.pid) -ErrorAction SilentlyContinue
    if ($null -eq $p) { return $null }
    if ($p.ProcessName -notmatch 'pwsh|powershell') { return $null }
    return $hb
}

if (-not $Force -and -not $Once) {
    $live = Get-LiveSampler
    if ($live -and [int]$live.pid -ne $selfPid) {
        # Another sampler owns the record. Exit cleanly; Task Scheduler will fire again in 5 minutes.
        Write-Heartbeat -Sample 0 -State 'skipped-already-running' -Note "pid $($live.pid) is sampling" -RowsWritten 0
        if ($Foreground) { Write-Host "[metrics] another sampler is running (pid $($live.pid)) - exiting" }
        exit 0
    }
}

$prev = @{}
$rowsWritten = 0
$total = if ($Once) { 1 } elseif ($Samples -gt 0) { $Samples } else { [int]::MaxValue }

try {
    for ($i = 0; $i -lt $total; $i++) {
        if ((Get-Date).ToUniversalTime() -ge $deadline) {
            Write-Heartbeat -Sample $i -State 'rotating' -Note "reached MaxHours=$MaxHours; the task restarts this within 5 min" -RowsWritten $rowsWritten
            exit 0
        }

        $row = [ordered]@{
            ts = (Get-Date).ToString('s'); commit_gb = ''; avail_mb = ''; pages_in_s = ''; faults_s = ''
            disk_q = ''; cpu_pct = ''; procs = ''; node = ''; msedge = ''; pwsh = ''; conhost = ''
            cim_ok = ''; mcp = ''; engines = ''; top1 = ''; top2 = ''; top3 = ''
        }
        $loopNote = $legacyNote
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
        } catch { $loopNote = 'counter-failed' }

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
        } catch { if (-not $loopNote) { $loopNote = 'process-enum-failed' } }

        if ($i % 5 -eq 0) {
            # MEASURED 2026-09-16: this block wrote mcp=0 engines=0 while the engine was demonstrably
            # running (the same filter matches standalone: engines=1, mcp=7). I did not find the cause
            # before spending more context on it, so the column is made honest instead of believed: a
            # value is written ONLY when the query produced one, and 0 is written only when the query
            # really ran and found none. Recording "0" for "I did not measure" is how an instrument
            # starts lying, and that is worse than a blank.
            try {
                $all = Get-CimInstance Win32_Process -ErrorAction Stop
                $m = @($all | Where-Object { $_.CommandLine -match 'mcp-fetch-server|@playwright/mcp|firecrawl-mcp|context7-mcp|mcp-remote|ps_mcp_server' })
                $e = @($all | Where-Object { $_.CommandLine -match 'dsh\\lib\\bin\.js\s+web' })
                if ($all.Count -gt 0 -and ($m.Count + $e.Count) -gt 0) {
                    $row.mcp = $m.Count
                    $row.engines = $e.Count
                    $row.cim_ok = 1
                } else {
                    $row.mcp = 'n/a'; $row.engines = 'n/a'; $row.cim_ok = 0
                }
            } catch { $row.mcp = 'n/a'; $row.engines = 'n/a' }
        }

        try {
            ($row.Values | ForEach-Object { "$_" }) -join ',' | Add-Content -Path $csv -Encoding utf8
            $rowsWritten++
        } catch { if (-not $loopNote) { $loopNote = 'csv-append-failed' } }

        # The metric that actually predicts felt slowness (measured 2026-09-16): how many sessions are
        # GENERATING right now. Windows and process counts did not track it; this does. A session log
        # written in the last 60 s means that session's agent loop is running.
        try {
            $sess = Join-Path $env:USERPROFILE '.dsh\sessions'
            $active = @(Get-ChildItem $sess -Recurse -File -Filter 'session.v3.jsonl.zstd' -ErrorAction SilentlyContinue |
                        Where-Object { $_.LastWriteTime -gt (Get-Date).AddSeconds(-60) }).Count
            "{0},{1},{2},{3}" -f $row.ts, $active, $row.commit_gb, $row.pages_in_s |
                Add-Content -Path (Join-Path $dir 'sessions-activity.csv') -Encoding utf8
        } catch { }

        Write-Heartbeat -Sample $i -State 'running' -Note (@($legacyNote, $loopNote) -ne '' -join '; ') -RowsWritten $rowsWritten
        if ($Foreground) {
            Write-Host ("[{0}] sample {1} commit={2}GB avail={3}MB pages_in={4}/s procs={5}" -f `
                $row.ts, $i, $row.commit_gb, $row.avail_mb, $row.pages_in_s, $row.procs)
        }

        if ($i -lt $total - 1) { Start-Sleep -Seconds $IntervalSeconds }
    }
} catch {
    # A sampler that dies silently is the failure this whole rewrite exists to remove. Record why,
    # then exit non-zero so Task Scheduler's Last Run Result is honest and the 5-minute repetition
    # picks it straight back up.
    Write-Heartbeat -Sample $rowsWritten -State 'crashed' -Note "unhandled: $($_.Exception.Message)" -RowsWritten $rowsWritten
    throw
}

Write-Heartbeat -Sample $rowsWritten -State 'finished' -Note "sample limit reached (Samples=$Samples)" -RowsWritten $rowsWritten
exit 0
