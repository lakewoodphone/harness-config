# ZabzTech-BootWatch - logs firmware/TPM/VSM/Hello state at each boot, then removes itself.
# Runs as SYSTEM at startup.
#
# FIX HISTORY (both found on 2026-09-20, ZABZ-YOGA session):
#  1. Events must be WINDOWED TO THE CURRENT BOOT. The original read the last 40 Hello events
#     regardless of boot time, so the container deletion that happened BEFORE the reboot (e.g.
#     15:30:35) was counted as a failure of the boot at 15:38:49. A healthy boot reported FAILING.
#     Now every Hello event is filtered to TimeCreated >= LastBootUpTime.
#  2. The stale orphan container {16596639} (on disk since 2026-02-09) fails with 0xD000A002 on
#     EVERY boot and was counted as the user's Hello failing. It is now tagged [STALE-ORPHAN] and
#     excluded from the verdict. The verdict is driven by the real evidence: an 8002 load of a
#     non-orphan container reporting "State: Okay", and the absence of 3611/7002 for a non-orphan
#     container in THIS boot's window.
$ErrorActionPreference = 'Continue'
$dir   = 'C:\Users\ezabz\Code\_diag'
$log   = Join-Path $dir 'boot-watch.log'
$state = Join-Path $dir 'boot-watch-state.json'
$max   = 8
$STALE = '16596639-eacc-4eb5-8471-fcba99c18fd4'   # orphan from 2026-02-09, not the user's container

function L([string]$m) { "$((Get-Date).ToString('o'))  $m" | Add-Content -Path $log -Encoding UTF8 }

try {
L ""
L "############ BOOT WATCH ############"
$n = 0
if (Test-Path $state) { try { $n = [int](Get-Content $state -Raw) } catch { $n = 0 } }
$n = $n + 1
$n | Set-Content -Path $state

$os     = Get-CimInstance Win32_OperatingSystem
$b      = Get-CimInstance Win32_BIOS
$booted = $os.LastBootUpTime
L "run $n of $max   booted $booted   now $(Get-Date -Format o)"
L "BIOS            : $($b.SMBIOSBIOSVersion)   ($($b.ReleaseDate))"
L "TPM firmware    : $((& tpmtool getdeviceinformation 2>&1 | Select-String 'Manufacturer Version') -replace '\s+',' ')"

$k13 = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-General'; Id=13} -MaxEvents 1
$k12 = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-General'; Id=12} -MaxEvents 1
if ($k13 -and $k12) { L "off-window      : $([math]::Round(($k12.TimeCreated-$k13.TimeCreated).TotalSeconds)) s   (shutdown-start -> bootmgr-start)" }

L "--- firmware devices ---"
Get-PnpDevice -Class Firmware | ForEach-Object {
  $pc = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_ProblemCode').Data
  $dv = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_DriverVersion').Data
  L ("   {0,-6} {1,-52} driver={2,-14} problem={3}" -f $_.Status, $_.FriendlyName, $dv, $pc)
}

$vsmOk = $false
L "--- VSM key package (event 85; BlobSize 723 + corrupt 0 = healthy) ---"
Get-WinEvent -LogName 'Microsoft-Windows-Kernel-Boot/Operational' -MaxEvents 25 |
  Where-Object { $_.Id -eq 85 -and $_.TimeCreated -ge $booted } | Select-Object -First 1 | ForEach-Object {
    $m = $_.Message -replace '\s+',' '
    $bs = [regex]::Match($m,'BlobFromUefiVariableSize: (\d+)').Groups[1].Value
    $uc = [regex]::Match($m,'UefiBlobIsCorrupt: (\d+)').Groups[1].Value
    L ("   $($_.TimeCreated)  BlobSize=$bs  UefiBlobIsCorrupt=$uc  NeedToResealKeyPkg=" + ([regex]::Match($m,'NeedToResealKeyPkg: (\d+)').Groups[1].Value))
    if ([int]$bs -gt 0 -and [int]$uc -eq 0) { $script:vsmOk = $true }
  }
Get-WinEvent -LogName 'Microsoft-Windows-Kernel-Boot/Operational' -MaxEvents 25 |
  Where-Object { $_.Id -in 45,51 -and $_.TimeCreated -ge $booted } | Select-Object -First 2 | ForEach-Object {
    L ("   [$($_.Id)] $(($_.Message -replace '\s+',' '))")
  }

L "--- HELLO, THIS BOOT ONLY (everything below is >= $booted) ---"
$h = Get-WinEvent -LogName 'Microsoft-Windows-HelloForBusiness/Operational' -MaxEvents 60 |
     Where-Object { $_.Id -in 7002,3611,8611,8002,5701,5702 -and $_.TimeCreated -ge $booted } |
     Select-Object -First 20
if (-not $h) { L "   (no Windows Hello events since boot)" }
foreach ($e in $h) {
  $flat = ($e.Message -replace '\s+',' ')
  $tag  = if ($flat.ToLower().Contains($STALE)) { ' [STALE-ORPHAN]' } else { '' }
  L ("   [$($e.Id)]$tag $($e.TimeCreated) :: $($flat.Substring(0,[Math]::Min(190,$flat.Length)))")
}

$orphan = @($h | Where-Object { ($_.Message -replace '\s+',' ').ToLower().Contains($STALE) })
$live   = @($h | Where-Object { -not (($_.Message -replace '\s+',' ').ToLower().Contains($STALE)) })
$okLoad = @($live | Where-Object { $_.Id -eq 8002 -and ($_.Message -replace '\s+',' ') -match 'State: Okay' })
$bad    = @($live | Where-Object { $_.Id -in 7002,3611 })
if ($orphan.Count) { L "   note: stale orphan container $STALE failed $($orphan.Count)x - noise, NOT the user's Hello" }

L "--- firmware still offered ---"
$sess = New-Object -ComObject Microsoft.Update.Session
$f = $sess.CreateUpdateSearcher().Search("IsInstalled=0").Updates | Where-Object { $_.DriverClass -eq 'Firmware' }
L "   count = $(@($f).Count)"
$f | ForEach-Object { L "   - $($_.Title)" }

$helloVerdict = if ($bad.Count) { "FAILING (PIN will need re-set)" }
                elseif ($okLoad.Count) { "HEALTHY (container loaded State: Okay, no deletion this boot)" }
                else { "INDETERMINATE (no 8002 load and no failure since boot)" }
$vsmVerdict   = if ($vsmOk) { "HEALTHY (blob present, not corrupt)" } else { "SUSPECT (blob absent/corrupt)" }
L ">>> RESULT: HELLO $helloVerdict   |   VSM key $vsmVerdict"

if ($n -ge $max) {
  L "watcher finished $max boots - unregistering. Re-arm: register a task running this file at startup."
  Unregister-ScheduledTask -TaskName 'ZabzTech-BootWatch' -Confirm:$false -EA SilentlyContinue
}
L "############ END ############"
} catch {
L "UNHANDLED: $($_.Exception.Message)"
}
