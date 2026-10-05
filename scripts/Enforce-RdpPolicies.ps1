# Enforce-RdpPolicies.ps1 - keep the RDP settings that make the session usable actually SET.
#
# WHY: on 2026-10-05 SelectTransport was set to 1 on ZABZ-TECH, verified by reading it back, and later found
# MISSING with no explanation - and a settings refresh (gpupdate /force) does NOT reproduce the removal, so it
# was not a policy refresh. Whatever did it is unknown; what is knowable is that a hand-set value that
# silently disappears is not a fix. This task makes the intended config self-healing and says so in one log,
# instead of leaving the owner to discover the regression as another freeze.
#
# ASCII-ONLY AND BOM-PADDED ON PURPOSE (see L3322): Windows PowerShell 5.1 reads a BOM-less script as ANSI,
# and one multi-byte character inside a string kills the whole file at parse time.
# ABSOLUTE PATHS ON PURPOSE: this task runs as SYSTEM, where $env:USERPROFILE is the SYSTEM profile
# (C:\Windows\system32\config\systemprofile) - not the owner's. A watchdog whose log lands where nobody looks
# is a watchdog that never reports. Measured: the first run of this script wrote its config line to the system
# profile and the owner's log stayed empty.
$log = 'C:\Users\ezabz\.dsh\logs\rdp-policy.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Get-Content $log -Tail 300 | Set-Content $log }

$key = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services'
New-Item -Path $key -Force | Out-Null

# The intended config, and why each value is here. 1 and 0 are the only accepted values.
$want = @(
  @{ name = 'SelectTransport';           value = 1; why = 'RDP over TCP only: the tailnet path changes under this link and RDP-UDP dies when it does' },
  @{ name = 'AVC444ModePreferred';       value = 0; why = 'AVC444 is the video codec: chroma-subsampled text looked wrong, and its pipeline logged 0x80004005 at the moment sessions died' },
  @{ name = 'AVCHardwareEncodePreferred';value = 0; why = 'keep the hardware H.264 encoder out of the text path on this machine' }
)

foreach ($w in $want) {
  $now = (Get-ItemProperty $key -Name $w.name -ErrorAction SilentlyContinue).($w.name)
  if ($now -eq $w.value) { continue }
  Set-ItemProperty -Path $key -Name $w.name -Value $w.value -Type DWord
  $after = (Get-ItemProperty $key -Name $w.name).($w.name)
  "$((Get-Date).ToString('s')) RE-APPLIED $($w.name): was $(if ($null -eq $now) { '(missing)' } else { $now }), now $after -- $($w.why)" | Add-Content $log
}

# Also record the full intended config once a day, so the record shows it is still in place rather than only
# ever showing repairs.
$stamp = 'C:\Users\ezabz\.dsh\logs\rdp-policy-stamp.txt'
$today = (Get-Date).ToString('yyyy-MM-dd')
$last = ''
if (Test-Path $stamp) { $last = (Get-Content $stamp -Raw).Trim() }
if ($last -ne $today) {
  $line = (Get-Date).ToString('s') + ' config: ' + (($want | ForEach-Object { "$($_.name)=$((Get-ItemProperty $key -Name $_.name -ErrorAction SilentlyContinue).($_.name))" }) -join ' ')
  $line | Add-Content $log
  Set-Content -Path $stamp -Value $today
}
