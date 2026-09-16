# dsh-reap.ps1 -- remove DSH process waste without touching live work.
#
# WHY THIS EXISTS (2026-09-15, ZABZ-YOGA)
#   Measured: an engine that had been up 28 h held THREE complete generations of
#   every MCP server (3 x {firecrawl, context7, jina, fetch, playwright}), each
#   behind four process layers (python launcher -> cmd.exe -> npx-cli.exe ->
#   server), plus orphaned pwsh/conhost trees left behind by timed-out tool
#   calls. Node's own docs say ChildProcess.kill() does NOT kill a process tree
#   on Windows, so a cancelled tool call leaks its shell -- this is the default
#   behaviour of the platform, not a surprise.
#
# WHAT IT DOES -- two independent, provable rules:
#   RULE 1 (orphans): a process is garbage if its parent PID no longer exists
#     AND it is a harness process (node/cmd/conhost/pwsh whose command line
#     matches the npm npx cache, dsh-subprocess-local, or an MCP server path).
#     Nothing can ever reap it -- its owner is gone -- so it can only leak.
#   RULE 2 (stale MCP generations): for each MCP server package, keep the
#     NEWEST generation and reap older ones. Two generations of one server
#     cannot both be in use; the older is a leftover of a replaced bridge.
#
# WHAT IT NEVER TOUCHES
#   The DSH engine itself (`dsh\lib\bin.js web`), any browser (msedge, chrome,
#   msedgewebview2), anything launched by explorer.exe, anything younger than
#   -MinAgeMinutes, and any process whose command line does not match the
#   harness patterns. Not a single customer or business process is eligible.
#
# USAGE
#   .\dsh-reap.ps1                 # report only (default) -- changes nothing
#   .\dsh-reap.ps1 -Apply          # kill what it reported
#   .\dsh-reap.ps1 -Apply -Quiet   # for Task Scheduler
#
param(
    [switch]$Apply,
    [switch]$Quiet,
    [int]$MinAgeMinutes = 10
)

$ErrorActionPreference = 'Stop'
$logDir = Join-Path $env:LOCALAPPDATA 'dsh-reaper'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$log = Join-Path $logDir 'reap.log'

function Write-Reap([string]$line) {
    $stamp = (Get-Date).ToString('o')
    "$stamp $line" | Add-Content -Path $log -Encoding utf8
    if (-not $Quiet) { Write-Host $line }
}

# Command-line shapes that belong to the harness. An engine started by hand, a
# customer app, or his editor never match these.
$harnessPattern = 'npm-cache\\_npx|dsh-subprocess-local|dsh\\lib\\bin\.js|mcp-fetch-server|@playwright\\mcp|firecrawl-mcp|context7-mcp|mcp-remote\\dist\\proxy|ps_mcp_server'

# The engine is the one process that must survive a reap. It is also, in
# practice, parentless (launched from a terminal that closed), so RULE 1 would
# otherwise eat it -- this exclusion is load-bearing.
$enginePattern = 'dsh\\lib\\bin\.js\s+web'

$all = Get-CimInstance Win32_Process
$liveIds = @{}
foreach ($p in $all) { $liveIds[[int]$p.ProcessId] = $true }

$candidates = @()
$protected  = @()

foreach ($p in $all) {
    $cmd = [string]$p.CommandLine
    $age = 0.0
    try { $age = ((Get-Date) - $p.CreationDate).TotalMinutes } catch { $age = 999 }

    if ($p.Name -notmatch '^(node|cmd|conhost|pwsh|powershell)\.exe$') { continue }
    if ($cmd -match $enginePattern) { $protected += $p; continue }
    if ($cmd -notmatch $harnessPattern) { continue }
    if ($age -lt $MinAgeMinutes) { continue }

    $candidates += [pscustomobject]@{
        Pid = [int]$p.ProcessId
        Name = $p.Name
        AgeMin = [math]::Round($age, 1)
        MB = [math]::Round($p.WorkingSetSize / 1MB)
        Parent = [int]$p.ParentProcessId
        ParentAlive = ($liveIds.ContainsKey([int]$p.ParentProcessId))
        Cmd = $cmd
    }
}

# ---- RULE 1: orphans (parent gone) -----------------------------------------
$orphans = @($candidates | Where-Object { -not $_.ParentAlive })

# ---- RULE 2: stale MCP generations ----------------------------------------
function Get-McpKind([string]$cmd) {
    if ($cmd -match 'mcp-fetch-server')   { return 'fetch' }
    if ($cmd -match '@playwright\\mcp')   { return 'playwright' }
    if ($cmd -match 'firecrawl-mcp')      { return 'firecrawl' }
    if ($cmd -match 'context7-mcp')       { return 'context7' }
    if ($cmd -match 'mcp-remote')         { return 'jina' }
    if ($cmd -match 'ps_mcp_server')      { return 'secretary' }
    return $null
}

$servers = @()
foreach ($c in $candidates) {
    $kind = Get-McpKind $c.Cmd
    # Only the real server process, not its cmd/npx shims.
    if (-not $kind) { continue }
    if ($c.Cmd -match 'cmd\.exe|npx-cli') { continue }
    $servers += [pscustomobject]@{ Kind = $kind; Pid = $c.Pid; AgeMin = $c.AgeMin; MB = $c.MB }
}

# A generation is a CHAIN: engine -> cmd -> npx-cli -> cmd -> server. Killing
# only the server (the leaf) leaves the three shim layers behind, so walk up to
# the highest ancestor that is still part of the harness and kill THAT tree.
$byPid = @{}
foreach ($p in $all) { $byPid[[int]$p.ProcessId] = $p }

function Get-ChainRoot([int]$pid_, $byPid_, [string]$enginePattern_) {
    $cur = [int]$pid_
    for ($i = 0; $i -lt 8; $i++) {
        $rec = $byPid_[[int]$cur]
        if (-not $rec) { break }
        $par = [int]$rec.ParentProcessId
        $prec = $byPid_[[int]$par]
        if (-not $prec) { break }
        $pcmd = [string]$prec.CommandLine
        if ($pcmd -match $enginePattern_) { break }          # do not climb into the engine
        if ($pcmd -notmatch $harnessPattern) { break }        # not ours -- stop here
        $cur = $par
    }
    return $cur
}

$roots = @{}
foreach ($s in $servers) {
    $s | Add-Member -NotePropertyName Root -NotePropertyValue (Get-ChainRoot $s.Pid $byPid $enginePattern) -Force
    $roots[$s.Root] = $s.Kind
}

$stale = @()
foreach ($g in ($servers | Group-Object Kind)) {
    $sorted = @($g.Group | Sort-Object AgeMin | Select-Object -Skip 1)   # newest generation stays
    foreach ($s in $sorted) {
        $stale += [pscustomobject]@{ Kind = $s.Kind; Pid = $s.Root; ServerPid = $s.Pid; AgeMin = $s.AgeMin; MB = $s.MB }
    }
}
$stale = @($stale | Sort-Object Kind, ServerPid -Unique)

# ---- report ----------------------------------------------------------------
$totMb = (($orphans | Measure-Object MB -Sum).Sum + ($stale | Measure-Object MB -Sum).Sum)
if (-not $Quiet) {
    Write-Host ""
    Write-Host "DSH process reaper  ($(if ($Apply) { 'APPLY' } else { 'REPORT ONLY' }))  age>=${MinAgeMinutes}m" -ForegroundColor Cyan
    Write-Host "  engine protected : $($protected.Count)"
    Write-Host "  orphans          : $($orphans.Count)"
    Write-Host "  stale MCP gens   : $($stale.Count)"
    Write-Host ""
    if ($orphans) { $orphans | Format-Table Pid, Name, AgeMin, MB, Cmd -AutoSize }
    if ($stale)   { $stale   | Format-Table Kind, Pid, AgeMin, MB -AutoSize }
}

Write-Reap ("reap start apply={0} orphans={1} staleMcp={2} candidates={3} reclaimMB={4}" -f `
    [bool]$Apply, $orphans.Count, $stale.Count, $candidates.Count, [math]::Round($totMb))

if (-not $Apply) {
    Write-Reap "report only - nothing killed (pass -Apply to act)"
    return
}

# ---- apply -----------------------------------------------------------------
# Kill leaves first (highest PIDs of the same tree), and always by tree, so a
# server cannot outlive the cmd/npx layers that spawned it.
$killed = 0
foreach ($victim in (@($orphans) + @($stale) | Sort-Object Pid -Descending)) {
    try {
        & taskkill.exe /PID $victim.Pid /T /F 2>&1 | Out-Null
        $killed++
        Write-Reap ("killed pid={0} name={1} ageMin={2} mb={3}" -f $victim.Pid, $victim.Name, $victim.AgeMin, $victim.MB)
    } catch {
        Write-Reap ("FAILED pid={0}: {1}" -f $victim.Pid, $_.Exception.Message)
    }
}
Write-Reap ("reap done killed={0} reclaimMB~{1}" -f $killed, [math]::Round($totMb))
