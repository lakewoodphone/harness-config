# Open her harness, running INSIDE her interactive session.
#
# WHY A SEPARATE SCRIPT FROM dshw's own launcher
# The desktop shortcut used to run the launcher directly, from an elevated cmd.exe, which lands in
# session 0 -- the service session with no desktop. The engine starts there (it is headless) but the
# window it asks for is created where nobody can see it. Windows will not let session 0 draw on the
# interactive session, so the work has to happen in a process that already lives in her session. A
# scheduled task with an Interactive logon type is that process.
#
# This script is what that task runs. It brings the engine up if needed and then reopens her window,
# which is the pair of actions the shortcut always intended.
$ErrorActionPreference = 'Continue'
$hc = 'C:\Users\cheve\code\harness-config'
$pwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'
$dshw = Join-Path $hc 'multi-window\dshw.ps1'
$logDir = 'C:\Users\cheve\.dsh\multi-window\logs'
$log = Join-Path $logDir 'open.log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Log([string]$m) {
    Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
}

Log "=== open requested (session $((Get-Process -Id $PID).SessionId), user $(whoami)) ==="
Log ("dshw: " + $dshw + "  exists=" + (Test-Path $dshw))

$env:DSH_HOME = 'C:\Users\cheve\.dsh'
$nodeDir = 'C:\Users\cheve\node-v22.14.0-win-x64'
if (Test-Path (Join-Path $nodeDir 'node.exe')) { $env:PATH = "$nodeDir;$env:PATH" }

# Step 1: the engine, if it is not already answering.
$out = & $pwsh -NoProfile -ExecutionPolicy Bypass -File $dshw ensure 2>&1
$out | ForEach-Object { Log ("  ensure: " + $_) }

# Step 2: her window. `restore` reopens what she had; if nothing is remembered it opens the first
# slot, which is the behaviour she expects from "open my assistant".
$out2 = & $pwsh -NoProfile -ExecutionPolicy Bypass -File $dshw restore 2>&1
$out2 | ForEach-Object { Log ("  restore: " + $_) }

# Step 3: prove it. A click that silently does nothing is the failure being fixed here, so the
# outcome is written down either way.
$titled = @(Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle })
$appUrl = @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
            Where-Object { [string]$_.CommandLine -match '--app=http' })
Log ("  windows with a title: " + $titled.Count + "   edge processes running her app: " + $appUrl.Count)
Log "=== open done ==="
