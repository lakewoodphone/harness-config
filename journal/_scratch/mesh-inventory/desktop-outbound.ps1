# Can ZABZ-TECH ssh OUTWARD? Two sibling children did it successfully this hour (one measured
# mac-mini-ts in detail over ssh, one measured secratary-ts over ssh), while a third child reported
# all five aliases HANGing including the self-hop. One of those is wrong, and the difference is
# probably the WRAPPER: the third child used `Start-Job { & ssh ... }`, which captures the ssh
# child's output through a piped-stdio job runner -- and this environment is documented to fail
# exactly there. This script uses the plain `& ssh` form the two successful children used.
#
# HOSTNAME EVERY HOP. An alias that silently lands on the wrong machine is the failure this repo has
# already recorded once; the remote hostname is the only proof of where the command actually ran.
$ErrorActionPreference = 'Continue'
"running on: $(hostname)"
foreach ($a in @('laptop-ts', 'desktop-ts', 'secratary-ts', 'linux-pc-ts', 'mac-mini-ts')) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $out = ''
    $err = ''
    try {
        $out = (& ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 $a hostname 2>&1 | Out-String).Trim()
    }
    catch { $err = $_.Exception.Message }
    $sw.Stop()
    $flat = if ($out) { $out -replace "`r?`n", ' | ' } else { $err }
    "{0,-14} {1,7} ms  -> {2}" -f $a, $sw.ElapsedMilliseconds, $flat
}
