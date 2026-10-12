# 07-zabztech-diagnose.ps1 -- diagnose the stale search index on zabz-tech (desktop-ts).
#
# STATE AS OF 2026-10-12 (journal H3574): the index IS stale and the task IS failing, and the CAUSE IS
# NOT ESTABLISHED. This script exists so the next session starts where this one stopped instead of
# re-running the four probes that proved nothing.
#
# ALREADY RULED OUT -- do not re-investigate these:
#   1. The TRIGGER. MSFT_TaskTimeTrigger, Enabled=True, EndBoundary empty,
#      Repetition Interval=PT1H Duration='' StopAtDurationEnd=False, NumberOfMissedRuns=0, NextRunTime
#      populated. This is the HEALTHY shape -- the opposite of P2899 D2, whose pattern expired after
#      one day. The clock is not the defect here.
#   2. The historical IndexError. refresh.log holds a traceback from `refresh.py`'s FAILURE-REPORTING
#      generator (`"".splitlines()[-1]` -> IndexError) -- but the file on disk was fixed at
#      2026-09-14T17:06:22Z and its own line 324 documents the guard, and refresh-state.json records a
#      SUCCESSFUL run at 17:34:36 AFTER that fix. That traceback is historical. Do not report it as
#      the live cause; that mistake was one keystroke away.
#   3. The launcher, the interpreter, the paths. The task runs wscript.exe -> a VBS ->
#      `cmd /c C:\Python313\python.exe ...\.fsearch\refresh.py >> refresh.log 2>&1`, and every path
#      and interpreter exists.
#   4. A HANG. A full refresh takes 1044 s and is SILENT while it runs (it captures its sub-processes'
#      output instead of streaming it), so a short-cap probe reads as "hung" when it is working.
#      ANY CONCLUSION HERE NEEDS A 20+ MINUTE WINDOW AND output redirected to a FILE, then read.
#
# WHAT IS ESTABLISHED: the task fires hourly, returns 1, and writes NOTHING to refresh.log or
# refresh-state.json (both frozen at 2026-09-14T17:34) -- runs fail in a path that records nothing.
# ~20 GB of RETIRED-* index files also sit reclaimable in the same directory.
#
# READ-ONLY EXCEPT the last block, which is commented out on purpose: it starts the 20+ minute run.

$ErrorActionPreference = 'Continue'
$T   = 'DSH search index refresh'
$dir = "$env:USERPROFILE\.fsearch"

Write-Output "=== 1. the task, and whether its clock is the problem (it is not) ==="
$task = Get-ScheduledTask -TaskName $T -ErrorAction SilentlyContinue
if (-not $task) { Write-Output "  NOT FOUND: $T"; Get-ScheduledTask | Where-Object { $_.TaskName -match 'search|index|usearch' } | Select-Object TaskName, State | Format-Table -AutoSize }
else {
  "  State: $($task.State)"
  $task.Triggers | ForEach-Object {
    "  trigger: $($_.CimClass.CimClassName) enabled=$($_.Enabled) start=$($_.StartBoundary) end='$($_.EndBoundary)'"
    if ($_.Repetition) { "           repetition Interval=$($_.Repetition.Interval) Duration='$($_.Repetition.Duration)' StopAtDurationEnd=$($_.Repetition.StopAtDurationEnd)" }
  }
  $task.Actions | ForEach-Object { "  action: $($_.Execute) $($_.Arguments)" }
  $task.Settings | Select-Object ExecutionTimeLimit, MultipleInstances, StartWhenAvailable | Format-List
  Get-ScheduledTaskInfo -TaskName $T | Select-Object LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns | Format-List
}

Write-Output "=== 2. the artefacts, and how stale they actually are ==="
if (Test-Path $dir) {
  Get-ChildItem $dir -File | Sort-Object Length -Descending | Select-Object -First 8 |
    ForEach-Object { "  {0,-38} {1,18:N0} B  {2}" -f $_.Name, $_.Length, $_.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ') }
  $retired = (Get-ChildItem $dir -File -Filter 'RETIRED-*' | Measure-Object Length -Sum).Sum
  if ($retired) { "  RETIRED-* total: {0:N0} B ({1:N1} GB) -- reclaimable" -f $retired, ($retired/1GB) }
} else { "  MISSING $dir" }

Write-Output "=== 3. the last recorded state (if this is old, nothing has completed since) ==="
foreach ($f in @("$dir\refresh-state.json", "$dir\refresh.log")) {
  if (Test-Path $f) {
    "  --- $f  (mtime $((Get-Item $f).LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')), $((Get-Item $f).Length) bytes)"
    Get-Content $f -ErrorAction SilentlyContinue | Select-Object -Last 12
  }
}

Write-Output "=== 4. is a run live right now? (the lock names a pid; a DEAD pid is self-healing) ==="
$lock = "$dir\refresh.lock"
if (Test-Path $lock) {
  $raw = (Get-Content $lock -Raw).Trim()
  $alive = $false
  $lockPid = 0
  if ([int]::TryParse($raw, [ref]$lockPid)) { try { $null = Get-Process -Id $lockPid -ErrorAction Stop; $alive = $true } catch {} }
  "  refresh.lock content='$raw' alive=$alive mtime=$((Get-Item $lock).LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
} else { "  no refresh.lock -- no run in progress" }
Get-Process wscript, python -ErrorAction SilentlyContinue |
  Select-Object Id, ProcessName, StartTime, @{n='CPU(s)';e={[math]::Round($_.CPU,1)}} | Format-Table -AutoSize

Write-Output ""
Write-Output "=== 5. THE DECISIVE RUN -- commented out so this script stays read-only ==="
Write-Output @"
  Uncomment the next block, run it, wait 20+ MINUTES, then read BOTH files and refresh-state.json.
  That is the measurement this audit did NOT make, and it is the whole next step.

  `$out = "`$dir\refresh.diag.out"; `$err = "`$dir\refresh.diag.err"
  Start-Process -FilePath 'C:\Python313\python.exe' ``
    -ArgumentList '-u', "`"`$dir\refresh.py`"" ``
    -RedirectStandardOutput `$out -RedirectStandardError `$err -NoNewWindow
  # ... then, after 20 minutes:
  Get-Content `$out -Tail 40; Get-Content `$err -Tail 20; Get-Content "`$dir\refresh-state.json"

  THEN: read the four sub-steps' real rc values (fsearch, names, chatindex, comms) and add a
  freshness guard BESIDE the refresh -- the check-faindex-freshness pattern from
  scripts/find-anything/. This defect's whole cost is that a failing refresh looks like an idle one.
"@
