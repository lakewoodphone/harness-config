# harness-verify.ps1 -- are this harness's invariants still true?
#
# WHY THIS EXISTS
# Between 2026-09-15 and 2026-09-16 this harness was changed in ways that are easy to undo by
# accident and impossible to notice when they are undone:
#
#   * the journal lock became an OS lock (a re-added `unlink` reintroduces a silent race);
#   * the preset's MCP rows moved from `npx.cmd` to a direct `node` path from a stable install
#     (one regeneration without the generator being updated reverts them);
#   * the preset became GENERATED, so a hand edit is deleted by the next regeneration;
#   * a reaper must exist as a scheduled task, or discarded process generations accumulate;
#   * `sync.py` must install client plugins, or a plugin package silently misses a machine;
#   * memory commit must stay under physical RAM, because at 36-39 GB of 31.6 GB the machine
#     pages and the symptom is "everything froze" with CPU only at ~65 %.
#
# A change that looks applied is not applied. This script checks the FACTS, prints where each
# one came from, and exits non-zero when one is false.
#
# USAGE
#   pwsh -NoProfile -File harness-verify.ps1            # report
#   pwsh -NoProfile -File harness-verify.ps1 -Quiet     # failures only (for a timer)
#
# It is read-only: it starts nothing, stops nothing, writes nothing.

param([switch]$Quiet)

$ErrorActionPreference = 'Continue'
$repo = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { 'C:\Users\ezabz\code\harness-config' }
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
$results = @()

function Check([string]$name, [scriptblock]$test) {
    try {
        $ok, $detail = & $test
    } catch {
        $ok, $detail = $false, "threw: $($_.Exception.Message)"
    }
    $script:results += [pscustomobject]@{ Check = $name; Ok = [bool]$ok; Detail = $detail }
}

# ---- 1. the preset is in sync with the generator ------------------------------------------
Check 'preset in sync with generator' {
    if (-not $python) { return $false, 'no python on PATH' }
    $out = & $python "$repo\scripts\make_zabz_preset.py" --check 2>&1
    $inSync = ($out -match 'in sync with the generator') -and ($LASTEXITCODE -eq 0)
    return $inSync, (($out | Select-Object -First 2) -join ' / ')
}

# ---- 2. MCP rows launch a server directly, not through npx --------------------------------
Check 'MCP rows are direct node' {
    $dst = "$repo\presets\zabz\agent.cordis.yml"
    $txt = Get-Content -Raw $dst
    $npxRows = ([regex]::Matches($txt, '(?m)^\s+command:\s*''npx')).Count
    $toolsOk = Test-Path "$env:USERPROFILE\.dsh\tools\mcp\node_modules\mcp-fetch-server\dist\index.js"
    $ok = ($npxRows -eq 0) -and $toolsOk
    return $ok, "npx commands=$npxRows (want 0); stable install present=$toolsOk"
}

# ---- 3. the reaper is a scheduled task ----------------------------------------------------
Check 'process reaper scheduled' {
    $t = Get-ScheduledTask -TaskName 'DSH Process Reaper' -ErrorAction SilentlyContinue
    if (-not $t) { return $false, 'task "DSH Process Reaper" not found' }
    $info = Get-ScheduledTaskInfo -TaskName 'DSH Process Reaper' -ErrorAction SilentlyContinue
    return $true, "state=$($t.State); last=$($info.LastRunTime); result=$($info.LastTaskResult)"
}

# ---- 4. node startup cache -----------------------------------------------------------------
Check 'NODE_COMPILE_CACHE set' {
    $v = [Environment]::GetEnvironmentVariable('NODE_COMPILE_CACHE', 'User')
    if (-not $v) { return $false, 'user variable not set' }
    return (Test-Path $v), "value=$v exists=$(Test-Path $v)"
}

# ---- 5. the journal lock is a real OS lock and is free ------------------------------------
Check 'journal lock takes in <1s' {
    $j = "$repo\journal\tools\journal.py"
    if (-not (Test-Path $j)) { return $false, "missing $j" }
    $probe = @"
import importlib.util, time
s = importlib.util.spec_from_file_location('j', r'$j')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
t0 = time.time(); ok, tok = m.acquire_lock('verify', wait=1.0)
dt = time.time() - t0
if ok: m.release_lock(tok)
print('%s %.2f' % (ok, dt))
"@
    if (-not $python) { return $false, 'no python on PATH' }
    $out = (& $python -c $probe 2>&1 | Select-Object -Last 1) -join ''
    $ok = $out -match '^True'
    return $ok, "acquire/release -> $out (msvcrt/fcntl lock; stale files cannot wedge it)"
}

# ---- 6. sync installs client plugins ------------------------------------------------------
Check 'sync installs client plugins' {
    $txt = Get-Content -Raw "$repo\scripts\sync.py"
    $ok = $txt -match 'install-client-plugins\.ps1'
    return $ok, $(if ($ok) { 'sync.py calls install-client-plugins.ps1' } else { 'sync.py does NOT call the installer' })
}

# ---- 7. the primary engine owns its port alone --------------------------------------------
# Deliberately NOT "there must be exactly one engine on the machine": an isolated second engine
# with its own DSH_HOME is a legitimate way to test a composition change (and is how the
# plugin-health work is being verified). What must never happen is TWO engines on ONE DSH_HOME:
# the dsh docs record that producing duplicate sequence numbers in one session log and making
# the whole history unloadable, and `dshw doctor` refuses it for the same reason. So the check
# is the observable invariant -- the primary port has exactly one listener -- and every other
# engine is reported, with a reminder to confirm it has its own home.
Check 'primary port has one engine' {
    $cfg = Get-Content -Raw "$repo\multi-window\windows.json" | ConvertFrom-Json
    $primary = [int]$cfg.primaryPort
    $all = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'dsh\\lib\\bin\.js\s+web' })
    $listeners = @(Get-NetTCPConnection -LocalPort $primary -State Listen -ErrorAction SilentlyContinue)
    $ok = ($listeners.Count -eq 1)
    $other = @($all | Where-Object { $_.CommandLine -notmatch "--port $primary\b" } |
               ForEach-Object { (($_.CommandLine -split '--port ')[1] -split ' ')[0] })
    return $ok, ("primary :$primary listeners=$($listeners.Count); engines total=$($all.Count); other ports=[$($other -join ',')] " +
                 "-- any engine listed here must have its OWN DSH_HOME")
}

# ---- 8. memory commit vs physical (the freeze predictor) ---------------------------------
Check 'commit under physical RAM' {
    $os = Get-CimInstance Win32_OperatingSystem
    $physGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    $commitGb = [math]::Round((Get-Counter '\Memory\Committed Bytes' -MaxSamples 1).CounterSamples.CookedValue / 1GB, 1)
    $pagesIn = [math]::Round((Get-Counter '\Memory\Pages Input/sec' -MaxSamples 1).CounterSamples.CookedValue)
    $ok = $commitGb -lt $physGb
    return $ok, "commit=$commitGb GB of $physGb GB physical; pages_in/s=$pagesIn (~0.81 GB per running turn; ~13-14 turns pages this host)"
}

# ---- 9. stale MCP generations -------------------------------------------------------------
Check 'no stale MCP generations' {
    $out = & pwsh -NoProfile -File "$repo\scripts\dsh-reap.ps1" -MinAgeMinutes 30 2>&1
    $line = ($out | Where-Object { $_ -match 'stale MCP gens' }) -join ''
    $n = [int](($line -replace '.*:\s*', '') -replace '\D.*', '')
    return ($n -eq 0), "stale MCP generation chains older than 30m: $n"
}

# ---- report ------------------------------------------------------------------------------
$failed = @($results | Where-Object { -not $_.Ok })
if (-not $Quiet) {
    Write-Host ''
    Write-Host 'harness-verify  (ZABZ-YOGA invariants, 2026-09-16)' -ForegroundColor Cyan
    foreach ($r in $results) {
        $colour = if ($r.Ok) { 'Green' } else { 'Red' }
        Write-Host ("  [{0}] {1,-38} {2}" -f $(if ($r.Ok) { 'ok' } else { 'FAIL' }), $r.Check, $r.Detail) -ForegroundColor $colour
    }
    Write-Host ''
    Write-Host ("  {0} ok, {1} failed" -f ($results.Count - $failed.Count), $failed.Count)
    Write-Host ''
}
if ($failed.Count) { exit 1 }
exit 0
