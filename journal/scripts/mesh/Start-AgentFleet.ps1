# =====================================================================================
# Start-AgentFleet.ps1   --   WORKSTREAM E: the missing instrument.
#
# Launches N concurrent headless DSH agent turns AIMED AT A NAMED MESH NODE over the
# remote-ssh route, so the children really execute there, then PROVES where they ran by
# reading each child's own MESH-HOST line. The dispatcher's intent is never trusted.
#
# It optionally samples a node (normally the owner's laptop) at ~1 Hz: committed bytes,
# available physical bytes, total process count, and RSS + private bytes of the DSH engine
# process (the node.exe serving `bin.js web --port 3099`).
#
# SEQUENCING (learned the hard way -- ssh session setup on this mesh costs 2-25 s and is
# highly variable, so a fixed-duration child can die before the sampler's window opens):
#   1. launch the children,
#   2. WAIT until every child's stdout shows its CHILD_PID= line -- i.e. until the remote
#      node.exe provably exists,
#   3. only then launch the sampler for its full window,
#   4. when the sampler reports END (or a bound trips), kill the children.
# The 60 s window is therefore covered by live children by construction, not by luck.
#
# Hazards implemented (H1-H3):
#   * ssh stdout is NEVER piped -- Start-Process -RedirectStandardOutput to a FILE, with a
#     bounded WaitForExit(ms) and Kill() on expiry.
#   * Every external call carries a numeric wall-clock deadline. A timed-out ssh is
#     reported as COULD NOT ASK, never as "the node is down".
#   * Every remote child PID started here is recorded, killed on stop/completion, and then
#     VERIFIED gone. A PID whose command line no longer matches ours is NOT killed.
#   * Hard total timeout and a memory-floor abort measured ON the observed node.
#   * At most 3 concurrent children (ValidateRange).
#
# Usage:
#   .\Start-AgentFleet.ps1 -Node desktop-ts -Count 3 -SampleNode laptop-ts `
#        -SampleSec 60 -MinAvailGiB 4 -HardTimeoutSec 90 -Tag B
# =====================================================================================
[CmdletBinding()]
param(
    # ssh alias of the node the children must run on
    [Parameter(Mandatory = $true)][string]$Node,

    # number of concurrent children (hard cap 3). 0 = BASELINE: launch nothing, just sample.
    [Parameter(Mandatory = $true)][ValidateRange(0, 3)][int]$Count,

    # safety ceiling only: children are normally killed by this driver when the window ends
    [int]$ChildAliveSec = 70,

    # after the sampling window, how long to let children finish their own turn so they can
    # emit their OWN MESH-HOST line before we kill them
    [int]$PostWindowWaitSec = 60,

    # hard wall-clock budget for the LOADED phase (children confirmed -> sampler END)
    [int]$HardTimeoutSec = 90,

    # abort immediately if available physical memory on $SampleNode drops below this (0 = off)
    [double]$MinAvailGiB = 0,

    # optional node to sample concurrently (e.g. laptop-ts). Empty = no sampling.
    [string]$SampleNode = '',

    # sampling window in seconds
    [int]$SampleSec = 60,

    # label for the run directory
    [string]$Tag = '',

    [string]$Root = 'C:\Users\ezabz\mesh-e'
)

$ErrorActionPreference = 'Stop'

$sshPath = 'C:\Program Files\OpenSSH\ssh.exe'
$nodeExe = 'C:\Program Files\nodejs\node.exe'
$binJs   = 'C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js'

if (-not $Tag) { $Tag = Get-Date -Format 'yyyyMMdd-HHmmss' }
$runDir = Join-Path $Root ('runs\' + $Tag)
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$logPath = Join-Path $runDir 'fleet.log'

function Write-Log {
    param([string]$Message)
    $line = (Get-Date -Format 'HH:mm:ss.fff') + '  ' + $Message
    Write-Host $line
    Add-Content -Path $logPath -Value $line
}

function ConvertTo-B64 { param([string]$Text) return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Text)) }
function Read-OutFile  { param([string]$Path) if (Test-Path $Path) { [string](Get-Content $Path -Raw -ErrorAction SilentlyContinue) } else { '' } }
function Read-ErrFile  { param([string]$Path) if (Test-Path $Path) { [string](Get-Content $Path -Raw -ErrorAction SilentlyContinue) } else { '' } }
function Get-ProcExit  { param($P) try { if ($P.HasExited) { return $P.ExitCode } } catch { } return 'running/unknown' }

# --- H1: ssh with FILE redirection + bounded WaitForExit. Never a pipe. --------------
function Invoke-RemoteSsh {
    param(
        [string]$Target,
        [string]$ScriptText,
        [int]$TimeoutSec,
        [string]$Label,
        [switch]$Background
    )
    $o = Join-Path $runDir ($Label + '.out')
    $e = Join-Path $runDir ($Label + '.err')
    Remove-Item $o, $e -ErrorAction SilentlyContinue

    $argList = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', $Target,
                 'powershell', '-NoLogo', '-NoProfile', '-EncodedCommand', (ConvertTo-B64 $ScriptText))

    $proc = Start-Process -FilePath $sshPath -NoNewWindow -PassThru `
                          -RedirectStandardOutput $o -RedirectStandardError $e `
                          -ArgumentList $argList

    $obj = [pscustomobject]@{
        Label = $Label; Target = $Target; Proc = $proc; OutFile = $o; ErrFile = $e
        TimedOut = $false; ExitCode = $null; ElapsedSec = $null
    }

    if ($Background) { return $obj }

    $sw = [Diagnostics.Stopwatch]::StartNew()
    $ok = $proc.WaitForExit($TimeoutSec * 1000)
    if (-not $ok) { try { $proc.Kill() } catch { } }
    $sw.Stop()
    $obj.TimedOut   = -not $ok
    $obj.ExitCode   = if ($ok) { $proc.ExitCode } else { $null }
    $obj.ElapsedSec = [math]::Round($sw.Elapsed.TotalSeconds, 2)
    return $obj
}

Write-Log "=== Start-AgentFleet tag=$Tag node=$Node count=$Count childCeiling=${ChildAliveSec}s hardTimeout=${HardTimeoutSec}s floor=${MinAvailGiB}GiB sample=$SampleNode/${SampleSec}s"
Write-Log "runDir=$runDir"

# --- step 1: who is on the far end? Refuse to launch if we cannot even ask. ----------
$who = Invoke-RemoteSsh -Target $Node -TimeoutSec 25 -Label 'whoami_node' -ScriptText 'hostname'
if ($who.TimedOut -or $who.ExitCode -ne 0) {
    Write-Log "COULD NOT ASK: ssh $Node hostname timedOut=$($who.TimedOut) exit=$($who.ExitCode)"
    $err = Read-ErrFile $who.ErrFile; if ($err) { Write-Log ('stderr: ' + $err.Trim()) }
    throw "COULD NOT ASK: no session to $Node (refusing to launch children blind)"
}
$expectedHost = (Read-OutFile $who.OutFile).Trim()
Write-Log "expected_host($Node) = '$expectedHost'  (ssh exit=$($who.ExitCode), $($who.ElapsedSec)s)"
if (-not $expectedHost) { throw "COULD NOT ASK: ssh $Node gave empty stdout (H2)" }

# --- step 2: build the remote child payload ------------------------------------------
# headless writes ONLY the final assistant message to stdout (measured: intermediates are
# dropped), so the hostname MUST be demanded in the final message or the child cannot prove
# where it ran.
$prompt = 'First run hostname in your shell tool and remember its exact output. ' +
          'Then run this exact command in your shell tool: Start-Sleep -Seconds ' + $ChildAliveSec + ' . ' +
          'Then, as your FINAL message and nothing else, output exactly two lines: the first line is MESH-HOST: followed by the hostname you observed, and the second line is the single word DONE.'
if ($prompt -match "['`"]") { throw 'internal: prompt contains a quote character' }

$childScript = @"
`$ProgressPreference = 'SilentlyContinue'
`$node   = '$nodeExe'
`$bin    = '$binJs'
`$prompt = '$prompt'
`$argline = '"' + `$bin + '" --profile headless "' + `$prompt + '"'
`$p = Start-Process -FilePath `$node -ArgumentList `$argline -NoNewWindow -PassThru
[Console]::Out.WriteLine('CHILD_PID=' + `$p.Id)
[Console]::Out.Flush()
`$p.WaitForExit()
[Console]::Out.WriteLine('CHILD_EXIT=' + `$p.ExitCode)
[Console]::Out.Flush()
"@

# --- step 3: launch the fleet ---------------------------------------------------------
$children = @()
if ($Count -gt 0) {
for ($i = 1; $i -le $Count; $i++) {
    $c = Invoke-RemoteSsh -Target $Node -TimeoutSec ($HardTimeoutSec + 60) -Label ('child' + $i) -ScriptText $childScript -Background
    $c | Add-Member -NotePropertyName Index         -NotePropertyValue $i
    $c | Add-Member -NotePropertyName T0            -NotePropertyValue (Get-Date)
    $c | Add-Member -NotePropertyName ConfirmedAt   -NotePropertyValue $null
    $c | Add-Member -NotePropertyName ExitAt        -NotePropertyValue $null
    $c | Add-Member -NotePropertyName RemotePid     -NotePropertyValue $null
    $children += $c
    Write-Log "launched child$i  sshPid=$($c.Proc.Id)  out=$($c.OutFile)"
}
} else {
    Write-Log 'BASELINE mode: no children launched (Count=0)'
}

# --- step 4: wait until every child proves it has a live remote node.exe --------------
$abortReason = ''
$confirmed = @()
if ($Count -gt 0) {
$confirmDeadline = (Get-Date).AddSeconds(60)
while ($true) {
    $pending = @($children | Where-Object { -not $_.ConfirmedAt })
    if ($pending.Count -eq 0) { break }
    foreach ($c in $pending) {
        $txt = Read-OutFile $c.OutFile
        $m = [regex]::Match($txt, 'CHILD_PID=(\d+)')
        if ($m.Success) {
            $c.RemotePid   = [int]$m.Groups[1].Value
            $c.ConfirmedAt = Get-Date
            Write-Log "child$($c.Index) CONFIRMED remotePid=$($c.RemotePid) after $([math]::Round(((Get-Date)-$c.T0).TotalSeconds,2))s"
        }
    }
    if ((Get-Date) -gt $confirmDeadline) {
        foreach ($c in @($children | Where-Object { -not $_.ConfirmedAt })) {
            Write-Log "COULD NOT ASK: child$($c.Index) never printed CHILD_PID within 60s (ssh exit=$(Get-ProcExit $c.Proc))"
        }
        break
    }
    Start-Sleep -Milliseconds 250
}
$confirmed = @($children | Where-Object { $_.ConfirmedAt })
if ($confirmed.Count -eq 0) {
    Write-Log 'ABORT: no child confirmed on the remote node -- refusing to sample a fleet that does not exist'
    $abortReason = 'NO_CHILDREN_CONFIRMED'
} else {
    Write-Log "$($confirmed.Count)/$Count children confirmed on $Node"
}
}

# --- step 5: launch the sampler, now that the load provably exists --------------------
$sampler = $null
if ($SampleNode -and ($Count -eq 0 -or $confirmed.Count -gt 0)) {
    $samplerBody = Get-Content (Join-Path $Root 'Get-NodeSample.ps1') -Raw
    $prefix  = "`$DurationSec = $SampleSec; `$FloorGiB = $MinAvailGiB; `$IntervalMs = 1000`r`n"
    $sampler = Invoke-RemoteSsh -Target $SampleNode -TimeoutSec ($SampleSec + 60) -Label 'sample' `
                -ScriptText ($prefix + $samplerBody) -Background
    $sampler | Add-Member -NotePropertyName T0 -NotePropertyValue (Get-Date)
    Write-Log "launched sampler on $SampleNode (${SampleSec}s, floor=${MinAvailGiB}GiB) sshPid=$($sampler.Proc.Id) out=$($sampler.OutFile)"
}

# --- step 6: supervise the loaded phase ----------------------------------------------
$fleetSw = [Diagnostics.Stopwatch]::StartNew()
if ($sampler) {
    $loadedDeadline = (Get-Date).AddSeconds($HardTimeoutSec)
    while ($true) {
        foreach ($c in @($children | Where-Object { -not $_.ExitAt })) {
            if ($c.Proc.HasExited) { $c.ExitAt = Get-Date; Write-Log "child$($c.Index) ssh exited at t+$([math]::Round($fleetSw.Elapsed.TotalSeconds,2))s (exit=$(Get-ProcExit $c.Proc))" }
        }
        $raw = Read-OutFile $sampler.OutFile
        if ($raw -match 'ABORT_MEM_FLOOR') {
            $abortReason = 'MEMORY_FLOOR'
            $hit = (Select-String -Path $sampler.OutFile -Pattern 'ABORT_MEM_FLOOR,\d+' | Select-Object -First 1)
            Write-Log "ABORT: available physical memory on $SampleNode fell below $MinAvailGiB GiB  [$($hit.Line)]"
            break
        }
        if ($raw -match '(?m)^END,') { Write-Log 'sampler reported END'; break }
        if ((Get-Date) -gt $loadedDeadline) {
            $abortReason = 'HARD_TIMEOUT'
            Write-Log "ABORT: loaded phase exceeded ${HardTimeoutSec}s"
            break
        }
        Start-Sleep -Milliseconds 400
    }
}
$fleetSw.Stop()
$windowEnd = Get-Date
Write-Log "loaded phase over: elapsed=$([math]::Round($fleetSw.Elapsed.TotalSeconds,2))s abort='$abortReason'"
foreach ($c in @($children | Where-Object { -not $_.ExitAt })) {
    if ($c.Proc.HasExited) { $c.ExitAt = Get-Date }
}

# --- step 6b: let children FINISH their own turn so each emits its OWN MESH-HOST line.
# headless writes nothing to stdout until the turn completes, so a child killed mid-turn
# can never prove where it ran. Wait, bounded; survivors are killed in step 7.
if ($Count -gt 0) {
    $postDeadline = (Get-Date).AddSeconds($PostWindowWaitSec)
    while ($true) {
        foreach ($c in @($children | Where-Object { -not $_.ExitAt })) {
            if ($c.Proc.HasExited) {
                $c.ExitAt = Get-Date
                Write-Log "child$($c.Index) finished its own turn at t+$([math]::Round(($c.ExitAt - $windowEnd).TotalSeconds,2))s after window end"
            }
        }
        if (@($children | Where-Object { -not $_.ExitAt }).Count -eq 0) { break }
        if ((Get-Date) -gt $postDeadline) {
            Write-Log "post-window wait cap ${PostWindowWaitSec}s reached; $((@($children | Where-Object { -not $_.ExitAt })).Count) child(ren) still running will be killed without reporting a hostname"
            break
        }
        Start-Sleep -Milliseconds 400
    }
}

# --- step 7: record remote PIDs, kill exactly our processes, verify ------------------
foreach ($c in $children) {
    $txt = Read-OutFile $c.OutFile
    $m = [regex]::Match($txt, 'CHILD_PID=(\d+)')
    if ($m.Success) { $c.RemotePid = [int]$m.Groups[1].Value }
}
$remotePids = @($children | Where-Object { $_.RemotePid } | ForEach-Object { $_.RemotePid })
Write-Log ("remote child PIDs to kill: " + $(if ($remotePids.Count) { $remotePids -join ',' } else { '<none - COULD NOT ASK>' }))

if ($remotePids.Count -gt 0) {
    $pidList = ($remotePids -join ',')
    $killScript = @"
`$ProgressPreference = 'SilentlyContinue'
`$pids = @($pidList)
foreach (`$id in `$pids) {
    `$pr = Get-CimInstance Win32_Process -Filter "ProcessId=`$id" -ErrorAction SilentlyContinue
    if (-not `$pr) { [Console]::Out.WriteLine('KILL,' + `$id + ',ALREADY_GONE'); continue }
    `$cl = '' + `$pr.CommandLine
    if (`$cl -like '*bin.js*') {
        & taskkill.exe /T /F /PID `$id | Out-Null
        [Console]::Out.WriteLine('KILL,' + `$id + ',TASKKILLED_TREE')
    } else {
        [Console]::Out.WriteLine('KILL,' + `$id + ',SKIPPED_PID_REUSED_DO_NOT_TOUCH')
    }
}
Start-Sleep -Milliseconds 700
`$alive = 0
foreach (`$id in `$pids) { if (Get-Process -Id `$id -ErrorAction SilentlyContinue) { `$alive++ } }
[Console]::Out.WriteLine('VERIFY_ALIVE=' + `$alive)
[Console]::Out.Flush()
"@
    $kill = Invoke-RemoteSsh -Target $Node -TimeoutSec 45 -Label 'kill_remote' -ScriptText $killScript
    if ($kill.TimedOut) {
        Write-Log 'COULD NOT ASK: remote kill/verify ssh timed out after 45s -- remote children may still be alive'
    } else {
        foreach ($l in @((Read-OutFile $kill.OutFile) -split "`r?`n" | Where-Object { $_ })) { Write-Log ('  remote: ' + $l) }
    }
}

# local ssh processes: kill exactly the PIDs we started, then verify gone
$localPids = @($children | ForEach-Object { $_.Proc.Id })
if ($sampler) { $localPids += $sampler.Proc.Id }
foreach ($lp in $localPids) {
    $p = Get-Process -Id $lp -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -eq 'ssh') { try { Stop-Process -Id $lp -Force -ErrorAction Stop } catch { } }
}
Start-Sleep -Milliseconds 500
$localAlive = @($localPids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }).Count
Write-Log "local ssh PIDs started=$($localPids -join ',')  stillAliveAfterKill=$localAlive"

if ($sampler) {
    $ok = $sampler.Proc.WaitForExit(30000)
    if (-not $ok) { try { $sampler.Proc.Kill() } catch { }; Write-Log 'sampler ssh killed by driver after 30s wait' }
    else { Write-Log "sampler ssh exit=$($sampler.Proc.ExitCode)" }
}

# --- step 8: per-run report -----------------------------------------------------------
Write-Log '--- REPORT ---'
Write-Log "run tag=$Tag node=$Node expectedHost=$expectedHost abort='$abortReason'"
$hostCache = @{}
foreach ($c in $children) {
    $txt = Read-OutFile $c.OutFile
    $hostMatch = [regex]::Match($txt, 'MESH-HOST:\s*(\S+)')
    $reported  = if ($hostMatch.Success) { $hostMatch.Groups[1].Value } else { 'COULD NOT ASK (no MESH-HOST line)' }
    $placedOk  = if ($hostMatch.Success -and $hostMatch.Groups[1].Value -eq $expectedHost) { 'CONFIRMED' } else { 'NOT CONFIRMED' }
    $wall      = if ($c.ExitAt) { [math]::Round(($c.ExitAt - $c.T0).TotalSeconds, 2) } else { 'still running' }
    $covered   = 'UNKNOWN'
    if ($c.ConfirmedAt -and $c.ExitAt) {
        if ($c.ExitAt -ge $windowEnd) { $covered = 'ALIVE_THROUGH_WINDOW_END' } else { $covered = 'DIED_BEFORE_WINDOW_END' }
    }
    $childExit = '?'; if ($txt -match 'CHILD_EXIT=(-?\d+)') { $childExit = $Matches[1] }
    Write-Log ("child$($c.Index): sshPid=$($c.Proc.Id) remotePid=$($c.RemotePid) reportedHost=$reported placement=$placedOk coverage=$covered sshExit=$(Get-ProcExit $c.Proc) childExit=$childExit childWallClock=${wall}s")
    if ($reported -notlike 'COULD*') { $hostCache[$reported] = 1 }
}
Write-Log ("hosts actually observed running children: " + $(if ($hostCache.Count) { ($hostCache.Keys -join ',') } else { '<none>' }))
if ($sampler) {
    $raw   = Read-OutFile $sampler.OutFile
    $ticks = @($raw -split "`r?`n" | Where-Object { $_ -like 'S,*' })
    Write-Log "sampler: ticks=$($ticks.Count) file=$($sampler.OutFile)"
    if ($ticks.Count -gt 0) {
        Write-Log ("sampler first=" + $ticks[0])
        Write-Log ("sampler last="  + $ticks[-1])
        $span = 'n/a'
        $first = [double](($ticks[0]  -split ',')[2])
        $last  = [double](($ticks[-1] -split ',')[2])
        $span  = [math]::Round($last - $first, 2)
        Write-Log "sampler window span=${span}s over $($ticks.Count) ticks"
    }
}
Write-Log '--- END REPORT ---'

