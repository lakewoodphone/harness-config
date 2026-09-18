# Sampler for the transport-concurrency measurement (docs/mesh/93-transport-concurrency.md §6).
#
# Runs ON THE TARGET. One consistent counter set, one consistent window, and — the point of this
# script — the CONCURRENCY READ FROM THE TARGET'S OWN PROCESS LIST, not from the caller's intent.
# A dispatcher's "I started 12" is a claim; `--profile headless` processes on this machine is the
# measurement.
#
# Discipline borrowed from 84-calibration.md §1.4.1: THE ROW IS STAMPED AFTER ITS READS, because a
# row labelled with the start of a window and filled from the end of it misaligns concurrency
# against memory by two to three seconds and attenuated 84's own first slope by 25 %.
#
# Counters are the ones 84 §1.3 validated. `Load`, `Pages free` and `% Disk Time` are deliberately
# NOT used: each has already misled this program once (81 §3.6).
[CmdletBinding()]
param(
  [string]$Csv = "$env:TEMP\mesh-sweep.csv",
  [int]$PeriodSec = 3,
  [int]$DurationSec = 300,
  [string]$Label = 'level'
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

# The engine cookie, minted the way scripts/phone-gate.py mints it: read the launch token out of the
# engine's own log and trade it for a session cookie. `/healthz` is fenced (it answers 401 to an
# anonymous caller), and the loop-lag reading exists nowhere else.
$token = $null
$newest = Get-ChildItem "$env:USERPROFILE\.dsh\multi-window\logs\3099-*.log" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($newest) {
  $m = Select-String -Path $newest.FullName -Pattern 'token=([A-Za-z0-9_\-]+)' | Select-Object -First 1
  if ($m) { $token = $m.Matches[0].Groups[1].Value }
}
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
if ($token) {
  try {
    Invoke-WebRequest -Uri "http://127.0.0.1:3099/?token=$token" -WebSession $session `
      -MaximumRedirection 0 -UseBasicParsing | Out-Null
  } catch { }
}

$header = 'label,ts,committedMiB,availMB,pagesInPerSec,pagefilePct,diskQ,cpuPct,nodeProcs,headlessChildren,loopP50,loopP95,loopMax,agentLoops'
Set-Content -LiteralPath $Csv -Value $header -Encoding utf8

$end = (Get-Date).AddSeconds($DurationSec)
while ((Get-Date) -lt $end) {
  $c = Get-Counter -Counter @(
    '\Memory\Committed Bytes',
    '\Memory\Available MBytes',
    '\Memory\Pages Input/sec',
    '\Paging File(_Total)\% Usage',
    '\PhysicalDisk(_Total)\Current Disk Queue Length',
    '\Processor(_Total)\% Processor Time'
  ) -SampleInterval 1 -MaxSamples 1
  # `CounterSamples.Path` comes back MACHINE-QUALIFIED — `\\zabz-tech\memory\committed bytes` — so a
  # lookup keyed on the bare counter path silently returns nothing and the whole row reads zero.
  # That is exactly what the first version of this script did, and it is worth the two lines.
  $v = @{}
  foreach ($s in $c.CounterSamples) {
    $v[($s.Path -replace '^\\\\[^\\]*', '').ToLower()] = $s.CookedValue
  }

  # THE MEASUREMENT: how many agent turns are running on this machine right now.
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'")
  $headless = @($procs | Where-Object { $_.CommandLine -like '*--profile headless*' }).Count
  $nodeProcs = $procs.Count

  $loop = $null
  try { $loop = Invoke-RestMethod -Uri 'http://127.0.0.1:3099/healthz' -WebSession $session -TimeoutSec 5 } catch { }

  $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
  $row = @(
    $Label, $ts,
    [int](($v['\memory\committed bytes']) / 1MB),
    [int]($v['\memory\available mbytes']),
    [int]($v['\memory\pages input/sec']),
    [math]::Round($v['\paging file(_total)\% usage'], 1),
    [int]($v['\physicaldisk(_total)\current disk queue length']),
    [math]::Round($v['\processor(_total)\% processor time'], 1),
    $nodeProcs, $headless,
    $loop.loop.p50Ms, $loop.loop.p95Ms, $loop.loop.maxMs,
    $loop.sessions.agentLoopsRunning
  )
  Add-Content -LiteralPath $Csv -Value ($row -join ',') -Encoding utf8
  Start-Sleep -Seconds $PeriodSec
}
"sampler done: $Csv" | Add-Content -LiteralPath "$Csv.done" -Encoding utf8
