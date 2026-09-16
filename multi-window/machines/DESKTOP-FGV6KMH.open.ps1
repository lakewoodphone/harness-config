# Open her harness, running INSIDE her interactive session.
#
# ONE IMPLEMENTATION, MANY CALLERS.
#
# The desktop shortcut, the `+` new-window protocol and the scheduled tasks all have to end up doing the
# same thing, and that thing is now the whole of DESKTOP-FGV6KMH.open.cmd: count the windows that
# really exist, decide whether this click means "give me my assistant" or "she already has one", then
# make sure an engine is up.
#
# This file exists only because one scheduled task points at it. It carries no logic of its own -- it
# used to carry a second, incomplete copy of the launch sequence, which is exactly how the launcher
# went a day and a half running against the OWNER's directories instead of hers (measured 2026-09-15).
# A delegator cannot drift.
$ErrorActionPreference = 'Stop'
$entry = Join-Path $PSScriptRoot 'DESKTOP-FGV6KMH.open.cmd'
if (-not (Test-Path $entry)) {
    Write-Error "launcher not found: $entry"
    exit 3
}
& $entry
exit $LASTEXITCODE
