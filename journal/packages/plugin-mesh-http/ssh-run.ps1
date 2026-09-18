# Run a command on another Windows node, correctly quoted, and stream its output back.
#
# WHY THIS EXISTS, AND WHY IT IS `-EncodedCommand`
# The harness launches `ssh` through a bash box, and bash rewrites the remote command line before it
# is sent. Measured on this fleet tonight, three shapes and what came back:
#
#   ssh desktop-ts "powershell -Command 'Write-Output (\$env:COMPUTERNAME)'"
#       -> Write-Output (\ZABZ-YOGA)  ... the backslash survived, the dollar did not, and the
#                                       target printed THIS machine's name
#   ssh desktop-ts "powershell -Command `$x = 1; ..."
#       -> = [Console]::In.ReadToEnd(); ... variables arrived empty
#
# `-EncodedCommand` is base64 of UTF-16LE, so there is NO quoting surface at all: whatever this
# machine built is exactly what the target parses.
#
# AND WHY THERE IS ALSO A `-File` PATH
# A long `-EncodedCommand` is still a long command line, and Windows ssh answers a big one with
# `exec request failed on channel 0` (measured with a 27 KB encoded program — the remote command
# length, not the payload, is the limit). Past `-MaxInlineChars` this script therefore writes the
# program to a temporary file on the target — delivered over an ssh stdin pipe as base64, the one
# delivery shape that works here — and runs it with `-File`. The temporary file is removed at the
# end. Nothing else on the target is touched.
#
# USAGE
#   pwsh -File ssh-run.ps1 -Alias desktop-ts -Command "node C:/path/thing.mjs check"
#   pwsh -File ssh-run.ps1 -Alias desktop-ts -ScriptFile probe-node.ps1
#   pwsh -File ssh-run.ps1 -Alias desktop-ts -ScriptFile x.ps1 -StdIn "some text"
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Alias,
    [string]$Command,           # a PowerShell program, as one string
    [string]$ScriptFile,        # or a file whose contents are that program
    [string]$StdIn,             # optional text piped into the remote process (inline path only)
    [int]$ConnectTimeoutSec = 20,
    [int]$MaxInlineChars = 8000
)

$ErrorActionPreference = 'Stop'
if (-not $Command -and -not $ScriptFile) { throw 'give -Command or -ScriptFile' }
$program = if ($ScriptFile) { Get-Content -Raw -LiteralPath $ScriptFile } else { $Command }
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($program))

if ($encoded.Length -le $MaxInlineChars) {
    $remote = "powershell -NoProfile -NonInteractive -EncodedCommand $encoded"
    if ($PSBoundParameters.ContainsKey('StdIn')) { $StdIn | & ssh -o BatchMode=yes -o "ConnectTimeout=$ConnectTimeoutSec" $Alias $remote }
    else { & ssh -o BatchMode=yes -o "ConnectTimeout=$ConnectTimeoutSec" $Alias $remote }
    exit $LASTEXITCODE
}

# --- the long path: drop the program on the target, run it with -File, remove it ---------------
$stamp = [guid]::NewGuid().ToString('N')
$inner = @'
$ErrorActionPreference = "Continue"
[IO.File]::WriteAllText("$env:TEMP\o2-run-{0}.ps1", [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd())))
& "$env:TEMP\o2-run-{0}.ps1"
$code = $LASTEXITCODE
Remove-Item -LiteralPath "$env:TEMP\o2-run-{0}.ps1" -Force -ErrorAction SilentlyContinue
exit $code
'@.Replace('{0}', $stamp)
$innerEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
$remote = "powershell -NoProfile -NonInteractive -EncodedCommand $innerEncoded"
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($program))
Write-Host "program is $($encoded.Length) encoded chars: sending it to $Alias as a file (limit $MaxInlineChars)" -ForegroundColor DarkGray
$b64 | & ssh -o BatchMode=yes -o "ConnectTimeout=$ConnectTimeoutSec" $Alias $remote
exit $LASTEXITCODE
