<#
  sweep-transfer-staging.ps1 - find the staging folders left behind by phone-transfer tools.

  Both WhatsApp transfer tools (WatsGo/iToolab and Wondershare Dr.Fone / MobileTrans) stage the customer's entire
  attachment set on the technician's Windows machine and never clean it up. One real job left 121 GiB across four
  folders while the drive had 78 GB free (ZABZ-YOGA, measured 2026-09-30).

  Owner policy, stated 2026-09-30: we are not responsible for a customer's data more than 30 days after the job.
  Owner rule, stated 2026-10-27: a FULL copy of a customer's data is kept only in `Downloads\customer data`,
  one subfolder per customer, findable, and deleted after a month. That folder is scanned here too - report
  only unless -DeleteCustomerData is passed, because deleting a customer's data is an act, not a side effect.

  This script therefore REPORTS by default and deletes only when asked with -Delete, and only folders older than
  -Days (default 30). Deleting a customer's data is an act, not a cron side effect.

  See docs/shop/customer-data-retention.md.

  Examples
    pwsh -File sweep-transfer-staging.ps1
    pwsh -File sweep-transfer-staging.ps1 -Delete -Days 30
    pwsh -File sweep-transfer-staging.ps1 -DeleteCustomerData -Days 30
    pwsh -File sweep-transfer-staging.ps1 -Roots C:\D:\ -Json
#>
[CmdletBinding()]
param(
  [string[]] $Roots = @('C:\'),
  [string[]] $Names = @('WatsGoBackup', 'WatsGo-Cache', 'WatsGoGoogleDriverBackup',
                        'Wondershare_DrFone_WhatsApp_Backup', 'Wondershare_SocialApp_Temp',
                        'Backuptrans_WhatsApp_Backup', 'iMobie_WhatsApp_Backup'),
  [string[]] $CustomerDataRoots = @((Join-Path $env:USERPROFILE 'Downloads\customer data')),
  [int]      $Days = 30,
  [switch]   $Delete,
  [switch]   $DeleteCustomerData,
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
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
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

# --- the owner's canonical home for a FULL copy of a customer's data (rule stated 2026-10-27) ---------------
# Age comes from the folder's own `_landed-on.txt` marker, never from the files inside it: a folder moved from
# the bench keeps the phone's own dates (2026-10-06 on the Shande job), so mtime would call fresh data a month
# old. A folder with no marker cannot be dated, and an undated folder is never treated as expired.
foreach ($cd in $CustomerDataRoots) {
  if (-not $cd -or -not (Test-Path -LiteralPath $cd)) { continue }
  foreach ($dir in (Get-ChildItem -LiteralPath $cd -Directory -Force -ErrorAction SilentlyContinue)) {
    $marker = Join-Path $dir.FullName '_landed-on.txt'
    $landed = $null
    if (Test-Path -LiteralPath $marker) {
      $first = Get-Content -LiteralPath $marker -TotalCount 1 -ErrorAction SilentlyContinue
      if ($first -match '(\d{4}-\d{2}-\d{2})') {
        try { $landed = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd', $null) } catch { $landed = $null }
      }
    }
    $cdFiles = Get-ChildItem -LiteralPath $dir.FullName -Recurse -File -Force -ErrorAction SilentlyContinue
    $cdBytes = ($cdFiles | Measure-Object -Property Length -Sum).Sum
    if (-not $cdBytes) { $cdBytes = 0 }
    $ageDays = $null
    $past    = $false
    $note    = 'NO _landed-on.txt - cannot be dated, so never past the window'
    if ($landed) {
      $ageDays = [int]((Get-Date) - $landed).TotalDays
      $past    = ($landed -lt $cutoff)
      $note    = ''
    }
    $rows += [pscustomobject]@{
      Path       = $dir.FullName
      Kind       = 'customer-data'
      GB         = [math]::Round($cdBytes / 1GB, 2)
      Files      = $cdFiles.Count
      Newest     = $landed
      AgeDays    = $ageDays
      PastWindow = $past
      Note       = $note
    }
  }
}

$rows = $rows | Sort-Object GB -Descending

if ($Json) {
  $rows | ConvertTo-Json -Depth 3
} elseif ($rows.Count -eq 0) {
  "no transfer staging folders and no customer-data folders found under: $(@($Roots + $CustomerDataRoots) -join ', ')"
} else {
  $rows | Format-Table Path, GB, Files, Newest, AgeDays, PastWindow -AutoSize
  $undated = @($rows | Where-Object { $_.Note })
  foreach ($u in $undated) { "UNDATED - not swept: $($u.Path)  ($($u.Note))" }
  "total GB: $([math]::Round((($rows | Measure-Object GB -Sum).Sum),2))   past the ${Days}-day window: $(@($rows | Where-Object PastWindow).Count)"
}

# Staging folders are deleted with -Delete. Customer-data folders need their OWN switch on top: the owner's rule
# is that this data is deleted after a month, but each deletion is still an act he authorises, per folder.
# `-Json` must emit JSON and nothing else, so every human-facing line below is suppressed in that mode.
if ($Delete -or $DeleteCustomerData) {
  $doomed = @($rows | Where-Object {
    $_.PastWindow -and (($_.PSObject.Properties.Name -contains 'Kind' -and $_.Kind -eq 'customer-data') -eq [bool]$DeleteCustomerData)
  })
  if ($doomed.Count -eq 0) { if (-not $Json) { "nothing past the ${Days}-day window to delete with the switches given." } }
  foreach ($r in $doomed) {
    # rd /s /q is far faster than Remove-Item on folders with tens of thousands of files
    cmd /c "rd /s /q `"$($r.Path)`""
    if (Test-Path -LiteralPath $r.Path) { "FAILED to delete: $($r.Path)" }
    else { "deleted $($r.Path)  ($($r.GB) GB, $($r.Files) files, $($r.AgeDays) days old)" }
  }
}
