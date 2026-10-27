# parallel-measure.ps1 - measure many directories at once with robocopy /L.
#
# Same method as scripts/windows/measure-space.ps1 (robocopy /L /E /BYTES /XJ, parse the summary)
# but takes a list of ROOTS, expands each into its child directories, de-duplicates, and measures
# them concurrently.  Written for the 2026-10-27 ZABZ-TECH audit where a single-threaded walk of
# ~950 GB was too slow to sit on.
#
# Size is GiB = bytes / 1GB, the number Explorer shows.  Reparse points are skipped, never followed.
# Loose files directly inside a root are reported as their own "<root> (loose files)" row, because
# a folder-only ranking hides a 100 GB zip sitting at the top of Downloads.

[CmdletBinding()]
param(
  [string[]] $Roots,
  [string] $RootsFile,
  [int] $Throttle = 8,
  [string] $Out = 'C:\Users\ezabz\Code\_audit\measure.tsv'
)

$ErrorActionPreference = 'SilentlyContinue'
$probe = Join-Path $env:TEMP '_dsh_space_probe'

function Measure-One {
  param([string] $Path)
  $o = cmd /c "robocopy `"$Path`" `"$probe`" /L /E /NFL /NDL /NJH /NP /BYTES /XJ /R:0 /W:0 2>nul"
  $f = ($o | Select-String -Pattern '^\s*Files\s*:' | Select-Object -First 1)
  $b = ($o | Select-String -Pattern '^\s*Bytes\s*:' | Select-Object -First 1)
  $files = if ($f) { [int64](($f.ToString() -split '\s+')[3]) } else { 0 }
  $bytes = if ($b) { [int64](($b.ToString() -split '\s+')[3]) } else { 0 }
  [pscustomobject]@{ Path = $Path; GiB = [math]::Round($bytes / 1GB, 2); Bytes = $bytes; Files = $files }
}

$targets = New-Object System.Collections.Generic.List[string]
if ($RootsFile) { $Roots = Get-Content -LiteralPath $RootsFile | Where-Object { $_.Trim() -ne '' } }
foreach ($r in $Roots) {
  $full = [IO.Path]::GetFullPath($r).TrimEnd('\')
  # A bare drive root must keep its trailing separator: "C:" means "the current directory on C:".
  if ($full -match '^[A-Za-z]:$') { $full += '\' }
  if (-not (Test-Path -LiteralPath $full)) { continue }
  foreach ($d in (Get-ChildItem -LiteralPath $full -Directory -Force)) {
    if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    if ($d.FullName.TrimEnd('\') -eq $full) { continue }
    if (-not $targets.Contains($d.FullName)) { $targets.Add($d.FullName) }
  }
  $loose = Get-ChildItem -LiteralPath $full -File -Force | Measure-Object -Property Length -Sum
  if ($loose.Count -gt 0) {
    $row = [pscustomobject]@{ Path = "$full (loose files)"; GiB = [math]::Round($loose.Sum / 1GB, 2); Bytes = [int64]$loose.Sum; Files = $loose.Count }
    $row | Export-Csv -LiteralPath $Out -NoTypeInformation -Append -Encoding utf8
  }
}

Write-Host "measuring $($targets.Count) directories with throttle $Throttle"

$targets | ForEach-Object -Parallel {
  $probe = $using:probe
  $o = cmd /c "robocopy `"$_`" `"$probe`" /L /E /NFL /NDL /NJH /NP /BYTES /XJ /R:0 /W:0 2>nul"
  $f = ($o | Select-String -Pattern '^\s*Files\s*:' | Select-Object -First 1)
  $b = ($o | Select-String -Pattern '^\s*Bytes\s*:' | Select-Object -First 1)
  $files = if ($f) { [int64](($f.ToString() -split '\s+')[3]) } else { 0 }
  $bytes = if ($b) { [int64](($b.ToString() -split '\s+')[3]) } else { 0 }
  [pscustomobject]@{ Path = $_; GiB = [math]::Round($bytes / 1GB, 2); Bytes = $bytes; Files = $files }
} -ThrottleLimit $Throttle | Sort-Object Bytes -Descending | Export-Csv -LiteralPath $Out -NoTypeInformation -Append -Encoding utf8

Write-Host "done: $Out"
