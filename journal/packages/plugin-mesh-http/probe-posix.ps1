# Run a read-only POSIX reconnaissance probe on a node, delivering the script as base64 on stdin.
#
# WHY THIS SHAPE (four attempts, three of them wrong, all measured tonight)
# The probe is a shell script and the target is macOS or Linux, so the remote command is `sh -s` and
# the script arrives on stdin. Every way of getting it there through THIS machine failed except
# this one:
#
#   * `powershell -Command -` on the target reads a program from stdin but executed NOTHING and
#     exited 0 (measured, twice).
#   * A nested `-Command "..."` string died on the quoting between two shells, in three different
#     spellings; the harness launches ssh through bash, which consumed `$name` and left `\$name`.
#   * base64 inside the command line is 60+ KB and exceeds the 32,767-character argv limit.
#
# What works: a SHORT remote program that decodes stdin and pipes it to the shell it was written
# for. `python3 -c "..."` is that program; it is on every macOS and every Linux node on this fleet.
# It also survives the seconds-long relayed path to the Mac, where an ssh stdin pipe is the only
# transfer that has ever been reliable (`81` §2).
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Alias,                        # ssh destination
    [string]$ScriptFile = (Join-Path $PSScriptRoot 'probe-node-posix.sh'),
    [int]$ConnectTimeoutSec = 20
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $ScriptFile)) { throw "no probe at $ScriptFile" }
$body = (Get-Content -Raw -LiteralPath $ScriptFile) -replace "`r`n", "`n"
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($body))
$decoder = 'import sys,base64;sys.stdout.buffer.write(base64.b64decode(sys.stdin.read().strip()))'
$remote = 'python3 -c "' + $decoder + '" | sh -s'
Write-Host "probing $Alias with $([IO.Path]::GetFileName($ScriptFile)) ($($b64.Length) base64 chars on stdin)" -ForegroundColor DarkGray
$b64 | & ssh -o BatchMode=yes -o "ConnectTimeout=$ConnectTimeoutSec" $Alias $remote
exit $LASTEXITCODE
