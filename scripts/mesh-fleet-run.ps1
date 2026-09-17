# mesh-fleet-run.ps1 — run ONE real fleet through scripts/mesh-run.ps1 with the task text passed
# through the ENVIRONMENT, not through an argument list.
#
# WHY THIS FILE EXISTS. scripts/mesh-e2e.ps1 has to start the dispatcher as a child process so it
# can sample the client while the fleet is in flight. The task text is multi-line, contains quotes,
# parentheses, `$` and backticks, and PowerShell re-parses whatever `Start-Process -ArgumentList`
# joins together — so passing it as an argument is a quoting bug waiting to be measured (and
# Windows' own quoting rules for a native `pwsh` differ again from PowerShell's). The prompt
# travels in `$env:MESH_FLEET_PROMPT` instead: an environment variable survives the process
# boundary byte-for-byte, and this file reads it and hands it to the real CLI as a single argument.
#
# It is a TEST DRIVER, not a second implementation. Everything it does is set four variables and
# call the frozen path.
#
#   MESH_FLEET_PROMPT       required — the task given to the parent
#   MESH_FLEET_CHILDREN     default 6
#   MESH_FLEET_EXCLUDE      default empty — comma-separated node names
#   MESH_FLEET_TIMEOUT_MS   default 1200000
#
# Exit codes are mesh-run's own (0 completed, 10 queued, 1 failed) and are forwarded verbatim.

$prompt = $env:MESH_FLEET_PROMPT
if (-not $prompt) {
    Write-Error 'mesh-fleet-run: MESH_FLEET_PROMPT is empty'
    exit 1
}
$children = if ($env:MESH_FLEET_CHILDREN) { $env:MESH_FLEET_CHILDREN } else { '6' }
$timeout = if ($env:MESH_FLEET_TIMEOUT_MS) { $env:MESH_FLEET_TIMEOUT_MS } else { '1200000' }
$scriptDir = Split-Path -Parent $PSCommandPath
$meshRun = Join-Path $scriptDir 'mesh-run.ps1'

$argList = @('-Prompt', $prompt, '-Children', $children, '-TimeoutMs', $timeout)
if ($env:MESH_FLEET_EXCLUDE) { $argList += @('-Exclude', $env:MESH_FLEET_EXCLUDE) }

& $meshRun @argList
exit $LASTEXITCODE
