# Run a read-only reconnaissance probe on a node reached THROUGH another node.
#
# WHY THIS EXISTS
# Home (the laptop) and the office are separate networks and Tailscale is the only path between
# them (`81` §2), so a node in the other building is reached by pivoting through a node this one
# can reach. Everything travels as STANDARD INPUT — `powershell -Command -` for a Windows target,
# `sh -s` for a POSIX one, and a single-quoted PowerShell here-string carrying the pipe in between.
# Three earlier shapes died on quoting between two Windows shells; the here-string is the one
# that does not have a quote to lose.
#
# READ-ONLY ON THE TARGET; the pivot writes nothing at all.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Pivot,                    # ssh alias of the node we can reach
    [Parameter(Mandatory)][string]$Target,                   # ssh alias reachable FROM the pivot
    [ValidateSet('windows', 'posix')][string]$TargetPlatform = 'posix',
    [string]$Probe
)

$ErrorActionPreference = 'Stop'
if (-not $Probe) {
    $Probe = if ($TargetPlatform -eq 'posix') { Join-Path $PSScriptRoot 'probe-node-posix.sh' } else { Join-Path $PSScriptRoot 'probe-node.ps1' }
}
if (-not (Test-Path $Probe)) { throw "no probe at $Probe" }
$body = (Get-Content $Probe -Raw) -replace "`r`n", "`n"

# A single-quoted here-string: PowerShell substitutes NOTHING inside it, so the probe arrives
# byte-for-byte and the `$` in its own variables belong to the target shell, not to the pivot.
if ($TargetPlatform -eq 'posix') {
    $remote = @'
$body | ssh -o BatchMode=yes -o ConnectTimeout=20 TARGETPLACEHOLDER "sh -s"
'@.Replace('TARGETPLACEHOLDER', $Target)
} else {
    $remote = @'
$body | ssh -o BatchMode=yes -o ConnectTimeout=20 TARGETPLACEHOLDER "powershell -NoProfile -NonInteractive -Command -"
'@.Replace('TARGETPLACEHOLDER', $Target)
}
$remote = $remote.Replace('$body', "`$body")
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
    "`$body = @'`n$body`n'@`n" + $remote))

Write-Host "running $([IO.Path]::GetFileName($Probe)) on $Target through $Pivot ..." -ForegroundColor DarkGray
# Single-quoted PowerShell strings everywhere on the outer layer: `$s` must reach the remote
# parser as a dollar sign, not be expanded here (which is what the previous version did).
$deliver = 'powershell -NoProfile -NonInteractive -Command ''$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("' + $b64 + '")); Invoke-Expression $s'''
& ssh -o BatchMode=yes -o ConnectTimeout=20 $Pivot $deliver
