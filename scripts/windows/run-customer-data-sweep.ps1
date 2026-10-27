<#
  run-customer-data-sweep.ps1 - the scheduled wrapper around sweep-transfer-staging.ps1.

  The owner's rule (2026-10-27): a full copy of a customer's data lives only in `Downloads\customer data`
  and is deleted after a month. A rule with no mechanism decays, so this runs the report on a schedule and
  leaves three files a session can read instead of a memory:

    %USERPROFILE%\.customer-data-sweep\report-<yyyy-MM-dd>.txt   the full report for that day
    %USERPROFILE%\.customer-data-sweep\last-report.txt           the newest one
    %USERPROFILE%\.customer-data-sweep\DUE.txt                   one line per folder past the window, or "none"

  It REPORTS ONLY. It never passes -Delete or -DeleteCustomerData: deleting a customer's data is an act the
  owner authorises per folder, not a side effect of a weekly task.

  See docs/shop/customer-data-retention.md.

  Examples
    pwsh -NoProfile -File run-customer-data-sweep.ps1
#>
[CmdletBinding()]
param(
  [int] $Days = 30
)

$ErrorActionPreference = 'Stop'

$here  = Split-Path -Parent $PSCommandPath
$sweep = Join-Path $here 'sweep-transfer-staging.ps1'
$log   = Join-Path $env:USERPROFILE '.customer-data-sweep'
New-Item -ItemType Directory -Force -Path $log | Out-Null

$stamp  = (Get-Date).ToString('yyyy-MM-dd')
$report = Join-Path $log "report-$stamp.txt"
$last   = Join-Path $log 'last-report.txt'
$due    = Join-Path $log 'DUE.txt'

$raw = & $sweep -Json -Days $Days *>&1 | Out-String
try {
  $rows = $raw | ConvertFrom-Json
  $ok = $true
} catch {
  $rows = @()
  $ok = $false
}

$lines = @()
$lines += "customer data sweep - $(Get-Date -Format 'yyyy-MM-dd HH:mm')  (window ${Days} days)"
if (-not $ok) {
  $lines += "FAILED - the sweep did not return parseable JSON. Raw output follows; nothing was deleted."
  $lines += $raw
  $lines | Set-Content -LiteralPath $report -Encoding utf8
  Copy-Item -LiteralPath $report -Destination $last -Force
  'SWEEP FAILED - see the report' | Set-Content -LiteralPath $due -Encoding utf8
  $lines | ForEach-Object { $_ }
  exit 1
}

$sorted = @($rows | Sort-Object @{ Expression = { if ($null -eq $_.AgeDays) { -1 } else { $_.AgeDays } } } -Descending)
foreach ($r in $sorted) {
  $name   = Split-Path $r.Path -Leaf
  $landed = if ($r.Newest) { ([datetime]$r.Newest).ToString('yyyy-MM-dd') } else { '(no marker - undated)' }
  $age    = if ($null -eq $r.AgeDays) { '?' } else { $r.AgeDays }
  $flag   = if ($r.PastWindow) { 'PAST THE WINDOW' } else { 'within' }
  $lines += ('{0,-42} {1,7} GB {2,6} files  landed {3}  {4,3}d  {5}' -f $name, $r.GB, $r.Files, $landed, $age, $flag)
}
$past = @($sorted | Where-Object PastWindow)
$undated = @($sorted | Where-Object { $null -eq $_.AgeDays })
$lines += ''
$lines += "past the window: $($past.Count)   undated (never swept): $($undated.Count)   total GB: $([math]::Round((($sorted | Measure-Object GB -Sum).Sum),2))"
$lines += 'NOTHING IS DELETED BY THIS JOB. Each folder past the window needs the owner''s per-folder yes;'
$lines += 'check the job succeeded first, then run the sweep with -DeleteCustomerData.'

$lines | Set-Content -LiteralPath $report -Encoding utf8
Copy-Item -LiteralPath $report -Destination $last -Force

if ($past.Count -eq 0) {
  'none' | Set-Content -LiteralPath $due -Encoding utf8
} else {
  $past | ForEach-Object { '{0}  |  {1} GB  |  {2} files  |  landed {3}  |  {4} days' -f $_.Path, $_.GB, $_.Files, (([datetime]$_.Newest).ToString('yyyy-MM-dd')), $_.AgeDays } |
    Set-Content -LiteralPath $due -Encoding utf8
}

$lines | ForEach-Object { $_ }
