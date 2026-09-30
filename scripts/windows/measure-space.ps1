<#
  measure-space.ps1 - rank what is using space, correctly, on Windows.

  Written 2026-09-30 after a session where three wrong numbers nearly reached the owner:
  a recursive walk that followed the `AppData\Local\Application Data` junction and reported
  82 GiB of phantom space, and GiB/GB confusion between PowerShell and robocopy.

  Why not `Get-ChildItem -Recurse | Measure-Object -Sum Length`?
    It is correct but slow (a PowerShell object per file, ~1.17M files in AppData alone) and
    it FOLLOWS reparse points on some builds, double counting whole trees. This script walks
    with robocopy /L: C-level, no copying, /XJ skips junctions, and it reports the summary
    robocopy already computes.

  Expect minutes on a full profile; run it in the background for a whole drive.

  Examples
    pwsh -File measure-space.ps1 -Root D:\
    pwsh -File measure-space.ps1 -Root C:\Users\ezabz -Top 20 -MinGiB 0.2
    pwsh -File measure-space.ps1 -Root C:\Users\ezabz -Top 20 -Newest      # adds last-write date
    pwsh -File measure-space.ps1 -Root C:\ -Json
#>
[CmdletBinding()]
param(
  [string] $Root    = 'C:\',
  [int]    $Top     = 15,
  [double] $MinGiB  = 0.5,
  [switch] $Newest,          # second pass: newest write time under each reported folder
  [switch] $Json
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Root)) { throw "not found: $Root" }

$probe = Join-Path $env:TEMP '_dsh_space_probe'   # never created: /L lists only

function Measure-One {
  param([string] $Path)
  # /L list only, /XJ skip junctions, /BYTES raw bytes, /NJH /NFL /NDL quiet, /R:0 /W:0 no retries
  $o = cmd /c "robocopy `"$Path`" `"$probe`" /L /E /NFL /NDL /NJH /NP /BYTES /XJ /R:0 /W:0 2>nul"
  $f = ($o | Select-String -Pattern '^\s*Files\s*:' | Select-Object -First 1)
  $b = ($o | Select-String -Pattern '^\s*Bytes\s*:' | Select-Object -First 1)
  $files = if ($f) { [int64](($f.ToString() -split '\s+')[3]) } else { 0 }
  $bytes = if ($b) { [int64](($b.ToString() -split '\s+')[3]) } else { 0 }
  [pscustomobject]@{
    Path   = $Path
    Name   = Split-Path $Path -Leaf
    GiB    = [math]::Round($bytes / 1GB, 2)
    Bytes  = $bytes
    Files  = $files
    Junction = $false
  }
}

$rows = @()
$skipped = @()
foreach ($d in (Get-ChildItem -LiteralPath $Root -Directory -Force -ErrorAction SilentlyContinue)) {
  # A reparse point is not space of its own: counting it double counts its target.
  if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { $skipped += $d.Name; continue }
  $rows += Measure-One -Path $d.FullName
}

$rows = $rows | Where-Object { $_.GiB -ge $MinGiB } | Sort-Object GiB -Descending

if ($Newest) {
  foreach ($r in $rows) {
    $n = Get-ChildItem -LiteralPath $r.Path -Recurse -File -Force -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $r | Add-Member -NotePropertyName Newest -NotePropertyValue ($(if ($n) { $n.LastWriteTime.ToString('yyyy-MM-dd') } else { '-' }))
  }
}

# Loose files at the root of $Root matter too: a drive whose downloads land as single large
# files (C:\Users\ezabz\Downloads, D:\) shows nothing at all in a folder-only ranking.
$rootFiles = Get-ChildItem -LiteralPath $Root -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Length -ge ($MinGiB * 1GB) } |
  Sort-Object Length -Descending |
  Select-Object -First $Top @{n='GiB';e={[math]::Round($_.Length/1GB,2)}}, @{n='Files';e={1}}, Name, @{n='Path';e={$_.FullName}}, LastWriteTime

$drive = Get-PSDrive -Name ($Root.Substring(0,1)) -ErrorAction SilentlyContinue

if ($Json) {
  [pscustomobject]@{
    root     = $Root
    freeGiB  = if ($drive) { [math]::Round($drive.Free / 1GB, 2) } else { $null }
    top      = $rows | Select-Object -First $Top
    topFiles = $rootFiles
    junctionsSkipped = $skipped
  } | ConvertTo-Json -Depth 4
  exit 0
}

"ROOT : $Root"
if ($drive) { "FREE : $([math]::Round($drive.Free/1GB,2)) GiB" }
"note : GiB = bytes / 1GB (this is what Explorer calls GB). Junction points are skipped, not counted."
if ($skipped.Count -gt 0) { "note : skipped as reparse points: $($skipped -join ', ')" }
""
$rows | Select-Object -First $Top GiB, Files, Name, @{n='Path';e={$_.Path}} | Format-Table -AutoSize
"total measured under $Root : $([math]::Round((($rows | Measure-Object GiB -Sum).Sum),2)) GiB in $(@($rows).Count) folders over $([math]::Round($MinGiB,2)) GiB"

if ($rootFiles -and @($rootFiles).Count -gt 0) {
  ""
  "LARGEST FILES DIRECTLY IN $Root :"
  $rootFiles | Format-Table GiB, LastWriteTime, Name -AutoSize
}
