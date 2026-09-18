# Trigger "open another window" from the protocol handler, running in HER session.
#
# WHY THIS INDIRECTION EXISTS
# The dsh-new:// protocol used to point straight at `dshw.ps1 new`. That runs the handler as whoever
# the protocol launches it as, and when that lands outside her interactive session the window it
# creates is not on a desktop anybody can see -- the same failure the desktop shortcut had. Verified
# on this machine: the protocol was registered and correct, `plugin-windows` was linked and served,
# and the button still did nothing.
#
# So the handler now only does one thing: it starts the scheduled task that runs INSIDE her session.
# The task does the actual work. This file never touches the browser itself.
$ErrorActionPreference = 'Continue'
$logDir = 'C:\Users\cheve\.dsh\multi-window\logs'
$log = Join-Path $logDir 'newwindow.log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
function Log([string]$m) {
    Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
}

Log "=== new-window protocol fired (session $((Get-Process -Id $PID).SessionId)) ==="

# `schtasks /run` is used rather than Start-ScheduledTask because this may be invoked from a context
# without the ScheduledTasks module loaded, and it is the one call that reliably starts a task
# regardless of who is asking.
$task = 'Yocheved DSH Window'
$out = & schtasks.exe /run /tn $task 2>&1
$code = $LASTEXITCODE
Log ("  schtasks /run `"$task`" -> exit=$code  " + (($out -join ' ') -replace '\s+', ' '))
if ($code -ne 0) {
    Log "  FAILED to start the task; the button will appear to do nothing"
}
Log "=== done ==="
