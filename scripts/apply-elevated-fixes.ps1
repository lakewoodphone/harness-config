# apply-elevated-fixes.ps1 — the two owner-approved, admin-only changes, in one elevated run.
#
# WHAT AND WHY (all measured on this machine, 2026-10-05):
#  1. `ipfsvc` = "Intel(R) Innovation Platform Framework Service". Its child `ipf_helper.exe` measured a
#     CONTINUOUS 0.72-0.93 of a core (202 008 CPU-s = 56 h cumulative) on a 22-thread laptop. It is the
#     only cost found that is continuous rather than triggered. Capability cost, stated to the owner:
#     Intel Dynamic Tuning thermal/power tuning. Reversible with:
#       sc.exe config ipfsvc start= auto ; sc.exe start ipfsvc
#  2. Defender real-time scanning cost, measured with a controlled workload: MsMpEng 6.81 CPU-s per
#     1000 newly-written small files, and SearchIndexer 12.55 per 1000 plus 381.7 CPU-s over one 668 MB
#     bulk read. Exclusions for the two trees this harness churns (code + .dsh) remove that tax on the
#     paths the engine walks (a session-list walk reads 62 MB of headers, 1082 directories).
#     Security cost, stated to the owner: those two trees are no longer scanned in real time.
#
# The output goes to a FILE because an elevated process's console cannot be captured by the caller.
[CmdletBinding()]
param([string]$LogDir = (Join-Path $env:USERPROFILE '.dsh\metrics'))
$ErrorActionPreference = 'Continue'
$log = Join-Path $LogDir ("elevated-apply-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$lines = New-Object System.Collections.Generic.List[string]
function Say($m) { $lines.Add($m); Write-Host $m }
function Flush { try { $lines | Set-Content -LiteralPath $log -Encoding utf8 } catch { } }

try { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null } catch { }
Say ("host {0}  user {1}  at {2}" -f $env:COMPUTERNAME, "$env:USERDOMAIN\$env:USERNAME", (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Say "elevated: $isAdmin"
if (-not $isAdmin) { Say 'REFUSING: not running elevated - nothing changed'; Flush; exit 1 }
Flush

# ── 1. the Intel service ─────────────────────────────────────────────────────────────────────────
Say ''
Say '=== 1. ipfsvc (Intel Innovation Platform Framework) ==='
$before = Get-Service ipfsvc -ErrorAction SilentlyContinue
Say ("before: Status={0} StartType={1}" -f $before.Status, $before.StartType)
$helperBefore = @(Get-Process ipf_helper, ipf_uf -ErrorAction SilentlyContinue)
Say ("before: ipf processes = {0}" -f (($helperBefore | ForEach-Object { "$($_.ProcessName)#$($_.Id)" }) -join ' '))
Flush
$stop = & sc.exe stop ipfsvc 2>&1
Say ("sc stop  : " + (($stop | Out-String).Trim() -replace "`r?`n", ' | '))
$cfg = & sc.exe config ipfsvc start= disabled 2>&1
Say ("sc config: " + (($cfg | Out-String).Trim() -replace "`r?`n", ' | '))
Start-Sleep -Seconds 3
Say '--- any stragglers after the service stopped (killing only if the service is really down) ---'
$svc = Get-Service ipfsvc -ErrorAction SilentlyContinue
Say ("after : Status={0} StartType={1}" -f $svc.Status, $svc.StartType)
$helperAfter = @(Get-Process ipf_helper, ipf_uf -ErrorAction SilentlyContinue)
Say ("after : ipf processes = {0}" -f (($helperAfter | ForEach-Object { "$($_.ProcessName)#$($_.Id)" }) -join ' '))
if ($svc.Status -ne 'Running' -and $helperAfter.Count -gt 0) {
    foreach ($p in $helperAfter) { try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Say ("killed {0}#{1} (its service is stopped)" -f $p.ProcessName, $p.Id) } catch { Say ("could not kill {0}#{1}: {2}" -f $p.ProcessName, $p.Id, $_.Exception.Message) } }
    Start-Sleep -Seconds 2
    Say ("after kill: ipf processes = {0}" -f ((@(Get-Process ipf_helper, ipf_uf -ErrorAction SilentlyContinue) | ForEach-Object { "$($_.ProcessName)#$($_.Id)" }) -join ' '))
}
Flush

# ── 2. Defender exclusions ──────────────────────────────────────────────────────────────────────
Say ''
Say '=== 2. Defender exclusions ==='
try {
    $paths = @('C:\Users\ezabz\code', 'C:\Users\ezabz\.dsh')
    Add-MpPreference -ExclusionPath $paths -ErrorAction Stop
    Say ("Add-MpPreference: applied for " + ($paths -join ', '))
} catch {
    Say ("Add-MpPreference FAILED: " + $_.Exception.Message)
}
try {
    $pref = Get-MpPreference
    Say ("readback ExclusionPath   : " + (($pref.ExclusionPath) -join ' | '))
    Say ("readback ExclusionProcess: " + (($pref.ExclusionProcess) -join ' | '))
    Say ("readback RealTimeProtection: " + (Get-MpComputerStatus).RealTimeProtectionEnabled)
} catch { Say ("readback failed: " + $_.Exception.Message) }
Flush

Say ''
Say '=== done ==='
Say ("log: " + $log)
Flush
exit 0
