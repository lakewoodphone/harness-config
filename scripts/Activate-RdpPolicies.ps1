# Activate-RdpPolicies.ps1 - finish the RDP policy work by restarting the RDP stack, but ONLY in a safe window.
#
# WHY THIS EXISTS (measured 2026-10-05): the RDP listener reads its policies when the service starts, and
# TermService on this machine had been running since 00:23:13 - hours before SelectTransport,
# AVC444ModePreferred, AVCHardwareEncodePreferred and fAllowDesktopCompositionOnServer were written at 11:0x.
# So every one of those values was inert, which is exactly why the session still reported `Initial profile: 2`
# (AVC444) long after the value said 0. Something has to restart the stack once, and doing that while the owner
# is working would end his session and every app in it - the thing he has already complained about twice.
#
# THE RULE: restart the stack only when no RDP session has been ACTIVE for 15 minutes, and only while the
# pending flag exists. If the stack does not come back, say a reboot is needed and stop - never reboot on its
# own, because that also costs the console session its sign-in.
#
# ASCII-ONLY, BOM-PADDED, ABSOLUTE PATHS (it runs as SYSTEM, where $env:USERPROFILE is the system profile).
$log  = 'C:\Users\ezabz\.dsh\logs\rdp-activate.log'
$flag = 'C:\Users\ezabz\.dsh\logs\rdp-policies-pending.txt'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Get-Content $log -Tail 300 | Set-Content $log }
function Note($m) { "$((Get-Date).ToString('s')) $m" | Add-Content $log }

if (-not (Test-Path $flag)) { exit 0 }

# 1. an ACTIVE RDP session means he is working - never touch the stack then.
$win = (qwinsta) -join "`n"
if ($win -match 'rdp-tcp#\d+\s+\S+\s+\d+\s+Active') { Note 'deferred: an RDP session is Active'; exit 0 }

# 2. and it must have been quiet for a while, not just disconnected a second ago.
$lastEvent = Get-WinEvent -LogName 'Microsoft-Windows-TerminalServices-LocalSessionManager/Operational' -MaxEvents 1 -ErrorAction SilentlyContinue
if ($lastEvent) {
  $quiet = ((Get-Date) - $lastEvent.TimeCreated).TotalMinutes
  if ($quiet -lt 15) { Note ("deferred: last session event was " + [math]::Round($quiet) + " min ago"); exit 0 }
}

# 3. restart the stack, furthest dependency first.
Note 'safe window reached: restarting the RDP stack to load the policies'
foreach ($s in 'SessionEnv', 'UmRdpService') { try { Restart-Service $s -Force -ErrorAction Stop } catch { Note "could not restart $s" } }
try { Restart-Service TermService -Force -ErrorAction Stop } catch { try { Start-Service TermService -ErrorAction Stop } catch { Note 'could not restart TermService' } }
Start-Sleep -Seconds 8

# 4. prove it: listener present, policies present. Only then clear the flag.
$listener = [bool](Get-NetTCPConnection -State Listen -LocalPort 3389 -ErrorAction SilentlyContinue)
$wts = (((qwinsta) -join "`n") -match 'rdp-tcp')
$policies = @{}
foreach ($n in 'SelectTransport', 'AVC444ModePreferred', 'AVCHardwareEncodePreferred', 'fAllowDesktopCompositionOnServer') {
  $policies[$n] = (Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services' -Name $n -ErrorAction SilentlyContinue).$n
}
$allSet = ($null -ne $policies['SelectTransport']) -and ($null -ne $policies['AVC444ModePreferred']) -and ($null -ne $policies['AVCHardwareEncodePreferred']) -and ($null -ne $policies['fAllowDesktopCompositionOnServer'])
if ($listener -and $wts -and $allSet) {
  Note ('DONE: listener back and policies present (' + (($policies.GetEnumerator() | ForEach-Object { $_.Key + '=' + $_.Value }) -join ' ') + '); the next session should negotiate a graphics profile other than 2')
  Remove-Item $flag -Force -ErrorAction SilentlyContinue
} else {
  Note ("NOT DONE: listener=$listener rdpTcp=$wts policiesComplete=$allSet - a REBOOT is needed instead; leaving the flag in place")
}
