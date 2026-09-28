<#
  dsh-update.ps1 — the only entry point. A shim, with no logic in it.

  It resolves node, execs lib/cli.mjs with every argument unchanged, and forwards the exit code.
  All behaviour lives in Node: the engine is Node, and splitting a JSON contract across PowerShell
  and JavaScript would mean parsing it in two languages in ten places.

  This shim starts nothing. In particular it never starts, stops or restarts a DSH engine.
#>
$ErrorActionPreference = 'Stop'

$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) { throw 'dsh-update: node.exe not found on PATH' }

$cli = Join-Path $PSScriptRoot '..\lib\cli.mjs'
if (-not (Test-Path $cli)) { throw "dsh-update: dispatcher not found at $cli" }

& $node $cli @args
exit $LASTEXITCODE
