# Is ZABZ-TECH's outbound ssh BROKEN, or is it only broken when its stdout is PIPED?
#
# Three readings had to be reconciled: a child reported all five aliases HANG (it used
# `Start-Job { & ssh ... }`); two other children on the same node in the same hour returned full
# reports measured over ssh (one of secratary, one of the mac mini); and a direct `& ssh ...` run
# from this node hung for four minutes. The hypothesis that fits all three: the ssh CLIENT works,
# but it never returns when its stdio is captured by a pipe -- and this environment is documented
# to fail exactly on piped child stdio. M2 found the same thing independently and routed every
# probe through `Start-Process -RedirectStandardOutput` instead.
#
# So this script uses that form, and bounds every hop so a hang is data rather than a stall.
$ErrorActionPreference = 'Continue'
"running on: $(hostname)"
foreach ($a in @('laptop-ts', 'secratary-ts', 'mac-mini-ts', 'linux-pc-ts')) {
    $o = Join-Path $env:TEMP "hop_$a.out"
    $e = Join-Path $env:TEMP "hop_$a.err"
    Remove-Item $o, $e -ErrorAction SilentlyContinue
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath 'C:\Program Files\OpenSSH\ssh.exe' `
        -ArgumentList @('-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=8', $a, 'hostname') `
        -NoNewWindow -PassThru -RedirectStandardOutput $o -RedirectStandardError $e
    if (-not $p.WaitForExit(20000)) { $p.Kill(); "{0,-14} HANG (killed at 20s)" -f $a; continue }
    $sw.Stop()
    $out = ((Get-Content $o -Raw -ErrorAction SilentlyContinue) -replace "`r?`n", ' ').Trim()
    $err = ((Get-Content $e -Raw -ErrorAction SilentlyContinue) -replace "`r?`n", ' ').Trim()
    "{0,-14} {1,7} ms  -> {2}{3}" -f $a, $sw.ElapsedMilliseconds, $out, $(if ($err) { " [stderr: $err]" } else { '' })
}
