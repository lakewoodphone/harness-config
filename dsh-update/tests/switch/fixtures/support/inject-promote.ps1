# inject-promote.ps1 — a STAND-IN for `bin\dsh-update.ps1 promote`, used only by the switch tests.
#
# WHY IT EXISTS: the real promote cannot run offline on this host. It fetches/validates the candidate
# prefix under `dsh-update\vendor\prefix\<version>`, and that prefix is not fetched here (measured
# 2026-09-28: `vendor\prefix` is empty). This script does the PART OF PROMOTE THAT MATTERS TO THE
# SWITCH — the two writes it performs at the end:
#
#   1. `dshInstall` in the launcher config  ->  <prefix>\<version>   (a .bak-dsh-update-* sibling first)
#   2. `state\pin.json`                     ->  the new version, predecessor recorded
#
# It writes NOTHING else, and it is never used outside the tests. The real promote's own gates
# (condition 1: a passing verify; condition 2: a diff verdict that is not BREAKS) are therefore NOT
# exercised by the switch tests — that is stated as a gap in the test README, not hidden here.

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Version,
  [Parameter(Mandatory=$true)][string]$WindowsJson,
  [Parameter(Mandatory=$true)][string]$PinPath,
  [Parameter(Mandatory=$true)][string]$ExpectRoot
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $WindowsJson)) { throw "no launcher config at $WindowsJson" }
if (-not (Test-Path -LiteralPath $PinPath))     { throw "no pin at $PinPath" }

# 1. the launcher config, with a timestamped backup beside it (the pipeline's own convention).
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
Copy-Item -LiteralPath $WindowsJson -Destination "$WindowsJson.bak-dsh-update-$stamp" -Force
$w = Get-Content -LiteralPath $WindowsJson -Raw | ConvertFrom-Json
if ($w.PSObject.Properties.Name -contains 'dshInstall') { $w.dshInstall = $ExpectRoot }
else { $w | Add-Member -NotePropertyName dshInstall -NotePropertyValue $ExpectRoot -Force }
$w | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $WindowsJson -Encoding utf8
Write-Output "inject-promote: dshInstall -> $ExpectRoot   (backup written: $WindowsJson.bak-dsh-update-$stamp)"

# 2. the pin, with the predecessor recorded.
$pin = Get-Content -LiteralPath $PinPath -Raw | ConvertFrom-Json
$from = [string]$pin.version
$pin.version      = $Version
$pin.installRoot  = $ExpectRoot
$pin.enginePath   = (Join-Path $ExpectRoot 'node_modules\@deepseek-ai\dsh\lib\bin.js')
$pin.managed      = $false
$pin.pinnedAt     = (Get-Date).ToUniversalTime().ToString('o')
$pin.by           = $env:COMPUTERNAME
$pin.predecessor  = $from
$pin | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $PinPath -Encoding utf8
Write-Output "inject-promote: pin version $from -> $Version"

# 3. the history row promote appends, so POST-STATE/reporting has something real to point at.
$histDir = Join-Path (Split-Path -Parent $PinPath) 'history'
if (-not (Test-Path -LiteralPath $histDir)) { [void](New-Item -ItemType Directory -Path $histDir -Force) }
$histFile = Join-Path $histDir 'events.tsv'
$line = "$((Get-Date).ToUniversalTime().ToString('o'))`tpromote`t$Version`t$from`tINJECTED-FOR-TESTS`t$ExpectRoot"
Add-Content -LiteralPath $histFile -Value $line
Write-Output "inject-promote: history row appended to $histFile"

exit 0
