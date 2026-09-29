# mid-sequence-failure.ps1 — force a failure AFTER the writes and BEFORE the verification step.
#
# WHY IT EXISTS: the previous version of the switch failed exactly here and nobody had a way to reach
# this point on purpose, so the defect survived three fixture runs. This script is the injection that
# reaches it: `-TestHookAfterWrite` runs it once the pre-state exists, promote has written the pin and
# the launcher knob, and sync.py has run — and then it makes something wrong and exits non-zero, as a
# step failure would.
#
# It runs LAST in the sequence deliberately: everything the switch is supposed to undo has already been
# overwritten by the time it fires. A roll-back that misses ANY of those files fails the proof.

[CmdletBinding()]
param(
  [string]$WindowsJson = '',
  [string]$PinPath = '',
  [string]$PresetsDir = '',
  [string]$ProfilesDir = '',
  [string]$Note = 'injected mid-sequence failure'
)

Write-Output "mid-sequence-failure: the switch's writes have landed; this hook now makes them WRONG ($Note)"

# The pin and the launcher config get values that cannot be right for the running engine, which is the
# incident's own shape: a pin that says 0.1.5-rc.1 while the launcher names the 0.1.7 prefix.
if ($PinPath -and (Test-Path -LiteralPath $PinPath)) {
  $pin = Get-Content -LiteralPath $PinPath -Raw | ConvertFrom-Json
  $pin.version = '0.1.5-rc.1'
  $pin.predecessor = 'INJECTED-MISMATCH'
  $pin | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $PinPath -Encoding utf8
  Write-Output "mid-sequence-failure: pin version forced to 0.1.5-rc.1 while the launcher names the 0.1.7 prefix"
}
if ($WindowsJson -and (Test-Path -LiteralPath $WindowsJson)) {
  $w = Get-Content -LiteralPath $WindowsJson -Raw | ConvertFrom-Json
  $w.dshInstall = 'C:\INJECTED\not-a-real-prefix'
  $w | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $WindowsJson -Encoding utf8
  Write-Output "mid-sequence-failure: dshInstall forced to C:\INJECTED\not-a-real-prefix"
}
# And every LIVE config file carries an appended line, so that a roll-back which "restores" by
# re-running sync.py instead of restoring bytes leaves visible evidence behind.
$n = 0
foreach ($dir in @($PresetsDir, $ProfilesDir)) {
  if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { continue }
  foreach ($f in @(Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue)) {
    Add-Content -LiteralPath $f.FullName -Value '# INJECTED-MID-SEQUENCE-FAILURE — this line must not survive the roll-back'
    $n++
  }
}
Write-Output "mid-sequence-failure: appended an injected line to $n LIVE config file(s)"
Write-Output 'mid-sequence-failure: nothing is repaired here — undoing all of the above is the roll-back''s job'
exit 3
