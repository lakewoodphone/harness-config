# Deliver a directory from this checkout to another node, and run a short extraction program there.
#
# WHY `-EncodedCommand` AND NOT A QUOTED `-Command` STRING (measured on ZABZ-TECH, tonight)
# Between this PowerShell and the target's PowerShell there is a bash — the harness launches `ssh`
# through a bash box — and bash rewrites the remote command line before it is ever sent:
#
#     ssh desktop-ts "powershell -Command 'Write-Output (\$env:COMPUTERNAME)'"
#       -> Write-Output (\ZABZ-YOGA) : The term '\ZABZ-YOGA' is not recognized
#
# The backslash survived and the dollar did not: the target printed THIS machine's name, so the
# variable was expanded locally and the escaping arrived as text. Two earlier shapes failed the
# other way (`$b64` arrived empty). `-EncodedCommand` (base64 of UTF-16LE) has no shell-quoting
# surface at all, and it also keeps a 60 KB payload off the command line — base64 of the PROGRAM is
# ~2 KB, and the PAYLOAD travels on stdin, which `[Console]::In.ReadToEnd()` reads under an encoded
# program too (measured: "GOT 18 chars").
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Alias,                       # ssh destination
    [string]$Path,                                              # a directory; defaults to this package
    [string]$Destination = 'C:/Users/ezabz/code/harness-config/packages'
)

$ErrorActionPreference = 'Stop'
if (-not $Path) {
    # This script lives IN the package it ships, so `$PSScriptRoot` IS the default payload.
    $Path = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
}
if (-not (Test-Path $Path)) { throw "no such path: $Path" }
$Path = (Resolve-Path $Path).Path
$name = Split-Path -Leaf $Path
$stamp = [guid]::NewGuid().ToString('N')
$tgz = Join-Path $env:TEMP "o2-ship-$stamp.tgz"

Push-Location (Split-Path -Parent $Path)
try {
    & tar -czf $tgz $name
    if ($LASTEXITCODE -ne 0) { throw "tar failed with $LASTEXITCODE" }
} finally {
    Pop-Location
}
$bytes = [IO.File]::ReadAllBytes($tgz)
$b64 = [Convert]::ToBase64String($bytes)
Write-Host "packed $name -> $($bytes.Length) bytes ($($b64.Length) base64 chars)" -ForegroundColor DarkGray

# The remote program is a HERE-STRING: PowerShell substitutes NOTHING inside `@'...'@`, so every `$`
# in it is the target's own, written once, with no escaping to get wrong. The two values that must
# come from here ($stamp, $Destination) are substituted with -f, which is explicit about it.
$template = @'
$ErrorActionPreference = "Stop"
$b64 = [Console]::In.ReadToEnd()
if ($b64.Trim().Length -lt 100) { Write-Output ("DELIVERY-FAILED: only " + $b64.Trim().Length + " bytes of payload arrived on stdin"); exit 9 }
$b = [Convert]::FromBase64String($b64.Trim())
$p = Join-Path $env:TEMP "o2-ship-{0}.tgz"
[IO.File]::WriteAllBytes($p, $b)
tar -xzf $p -C "{1}"
Write-Output ("EXTRACT_EXIT=" + $LASTEXITCODE)
Get-ChildItem "{1}/{2}" -Recurse -File | ForEach-Object { $_.FullName }
Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
'@
$remoteScript = $template.Replace('{0}', $stamp).Replace('{1}', $Destination).Replace('{2}', $name)
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoteScript))

try {
    $b64 | & ssh -o BatchMode=yes -o ConnectTimeout=30 $Alias "powershell -NoProfile -NonInteractive -EncodedCommand $encoded"
} finally {
    Remove-Item -LiteralPath $tgz -Force -ErrorAction SilentlyContinue
}
