<#
  sweep-transfer-staging.ps1 - find the staging folders left behind by phone-transfer tools.

  Both WhatsApp transfer tools (WatsGo/iToolab and Wondershare Dr.Fone / MobileTrans) stage the customer's entire
  attachment set on the technician's Windows machine and never clean it up. One real job left 121 GiB across four
  folders while the drive had 78 GB free (ZABZ-YOGA, measured 2026-09-30).

  Owner policy, stated 2026-09-30: we are not responsible for a customer's data more than 30 days after the job.
  This script therefore REPORTS by default and deletes only when asked with -Delete, and only folders older than
  -Days (default 30). Deleting a customer's data is an act, not a cron side effect.

  See docs/shop/customer-data-retention.md.

  Examples
    pwsh -File sweep-transfer-staging.ps1
    pwsh -File sweep-transfer-staging.ps1 -Delete -Days 30
    pwsh -File sweep-transfer-staging.ps1 -Roots C:\D:\ -Json
#>
[CmdletBinding()]
param(
  [string[]] $Roots = @('C:\'),
  [string[]] $Names = @('WatsGoBackup', 'WatsGo-Cache', 'WatsGoGoogleDriverBackup',
                        'Wondershare_DrFone_WhatsApp_Backup', 'Wondershare_SocialApp_Temp',
                        'Backuptrans_WhatsApp_Backup', 'iMobie_WhatsApp_Backup'),
  [int]      $Days = 30,
  [switch]   $Delete,
  [switch]   $Json
)

$ErrorActionPreference = 'Stop'
$cutoff = (Get-Date).AddDays(-$Days)
$rows = @()

foreach ($root in $Roots) {
  if (-not (Test-Path -LiteralPath $root)) { continue }
  foreach ($name in $Names) {
    $path = Join-Path $root $name
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $item  = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    $files = Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue
    $bytes = ($files | Measure-Object -Length -Sum).Sum
    if (-not $bytes) { $bytes = 0 }
    # age from the newest write under the folder: a job in progress is never old
    $newest = $item.LastWriteTime
    if ($files.Count -gt 0) { $newest = ($files | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime }
    $rows += [pscustomobject]@{
      Path       = $path
      GB         = [math]::Round($bytes / 1GB, 2)
      Files      = $files.Count
      Newest     = $newest
      AgeDays    = [int]((Get-Date) - $newest).TotalDays
      PastWindow = ($newest -lt $cutoff)
    }
  }
}

$rows = $rows | Sort-Object GB -Descending

if ($Json) {
  $rows | ConvertTo-Json -Depth 3
} elseif ($rows.Count -eq 0) {
  "no transfer staging folders found under: $($Roots -join ', ')"
} else {
  $rows | Format-Table Path, GB, Files, Newest, AgeDays, PastWindow -AutoSize
  "total GB: $([math]::Round((($rows | Measure-Object GB -Sum).Sum),2))   past the ${Days}-day window: $(@($rows | Where-Object PastWindow).Count)"
}

if ($Delete) {
  $doomed = @($rows | Where-Object PastWindow)
  if ($doomed.Count -eq 0) { "nothing to delete."; exit 0 }
  foreach ($r in $doomed) {
    # rd /s /q is far faster than Remove-Item on folders with tens of thousands of files
    cmd /c "rd /s /q `"$($r.Path)`""
    if (Test-Path -LiteralPath $r.Path) { "FAILED to delete: $($r.Path)" }
    else { "deleted $($r.Path)  ($($r.GB) GB, $($r.Files) files, $($r.AgeDays) days old)" }
  }
}
