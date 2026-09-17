# Run one ssh command with REAL FILE HANDLES for stdin, stdout and stderr.
#
# WHY THIS EXISTS. A Win32-OpenSSH client whose stdout is a PIPE does not exit — measured on
# ZABZ-TECH against ZABZ-YOGA (`70-remote-fanout-proof.md` §4.1): identical command, six stdio
# shapes, and only the file-handle shapes returned (1.0-1.1 s); every pipe shape hung until killed.
# `Start-Process -RedirectStandard*` hands the child an OS file handle rather than a pipe, which is
# the fixed form. Two of this stream's own runs hung on the pipe shape before this replaced it.
#
# The remote program travels as `-EncodedCommand` (base64 of UTF-16LE) because between this
# PowerShell and the target's there may be a shell that rewrites the command line
# (`ship-to-node.ps1`'s header has the measurement). The payload, when there is one, travels on
# stdin, where `[Console]::In.ReadToEnd()` reads it.
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Alias,
  [Parameter(Mandatory)][string]$Program,      # PowerShell source, run on the target
  [string]$StdinFile,
  [string]$OutFile,
  [string]$ErrFile,
  [int]$TimeoutSec = 300
)

$ErrorActionPreference = 'Stop'
if (-not $OutFile) { $OutFile = Join-Path $env:TEMP ("sshout-" + [guid]::NewGuid().ToString('N') + ".txt") }
if (-not $ErrFile) { $ErrFile = "$OutFile.err" }
if (-not $StdinFile) { $StdinFile = Join-Path $env:TEMP 'ssh-empty-stdin.txt'; Set-Content -LiteralPath $StdinFile -Value '' -NoNewline }

$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Program))
$argList = @(
  '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=15',
  $Alias, 'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', $encoded
)
$exe = (Get-Command ssh).Source
$p = Start-Process -FilePath $exe -ArgumentList $argList `
  -RedirectStandardInput $StdinFile -RedirectStandardOutput $OutFile -RedirectStandardError $ErrFile `
  -NoNewWindow -PassThru
if (-not $p.WaitForExit($TimeoutSec * 1000)) {
  try { $p.Kill() } catch { }
  Write-Output "SSH-TIMEOUT after ${TimeoutSec}s"
}
Write-Output "SSH-EXIT=$($p.ExitCode)"
Write-Output "SSH-STDOUT=$OutFile"
Write-Output "SSH-STDERR=$ErrFile"
Get-Content -LiteralPath $OutFile -Raw -ErrorAction SilentlyContinue
