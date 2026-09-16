# Open her harness, running INSIDE her interactive session.
#
# ONE IMPLEMENTATION, MANY CALLERS.
#
# The desktop shortcut, the `+` new-window protocol and the scheduled task all have to end up doing the
# same two things: make sure an engine exists, then open a window. That logic lives in
# DESKTOP-FGV6KMH.launch.cmd, because the environment it must set (Techloq CA trust, IPv4-first,
# DSH_HOME, the search endpoint, and the path to this machine's own windows.json) has to be in place
# before PowerShell is even started -- an environment variable cannot be retro-fitted onto a process
# that is already running.
#
# This file is therefore a delegator and nothing else. It used to carry its own copy of the launch
# sequence, which meant a second place to forget `-ConfigPath`; measured 2026-09-15, that copy is
# exactly what ran against the owner's directories and produced a console flash with no window.
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'DESKTOP-FGV6KMH.launch.cmd'
if (-not (Test-Path $launcher)) {
    Write-Error "launcher not found: $launcher"
    exit 3
}
& $launcher 'new'
exit $LASTEXITCODE
