# agent-fleet.ps1 — mechanical setup, inspection and teardown for a fleet of parallel coding agents.
#
# Why this exists: running N agents on one repository means N worktrees, and the failures are almost
# never in the code — they are forgotten worktrees eating disk, branches cut from a dirty base, and
# per-worktree test temp directories colliding. This script makes the mechanical part one command so
# the manager's attention goes to partitioning and integration, which is where the value is.
#
# Design rationale and the research behind it: harness-config/docs/parallel-agent-orchestration.md
#
# Safety posture, deliberately:
#   * It NEVER touches the repository's main worktree — only worktrees it created under -Root.
#   * It refuses to create a fleet from a dirty base, because a branch cut from uncommitted work
#     produces a merge nobody can reason about.
#   * It refuses to remove a dirty worktree unless -Force is given explicitly.
#   * It never deletes branches. Removing a worktree leaves the branch intact so work can be salvaged.
#
# Usage:
#   agent-fleet.ps1 new   -Name lpt-route,egress-wiring,docs-fix -Repo C:\path\to\repo
#   agent-fleet.ps1 status -Repo C:\path\to\repo
#   agent-fleet.ps1 clean  -Repo C:\path\to\repo          # drop _pt_* / __pycache__ / .gradle
#   agent-fleet.ps1 rm    -Name lpt-route -Repo C:\path\to\repo
#   agent-fleet.ps1 rmall -Repo C:\path\to\repo           # every agent/* worktree, branches kept

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('new', 'status', 'doctor', 'clean', 'rm', 'rmall')]
    [string]$Action,

    [string]$Repo = '.',
    [string]$Root = '',
    [string[]]$Name = @(),
    [string]$Base = 'main',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Get-RepoPath {
    $p = (Resolve-Path -LiteralPath $Repo).Path
    if (-not (Test-Path -LiteralPath (Join-Path $p '.git'))) {
        throw "Not a git repository: $p"
    }
    return $p
}

function Get-FleetRoot([string]$RepoPath) {
    # Computed, never created here: a read-only action (status/clean) must not leave an empty
    # directory behind just because it was asked a question. Only 'new' creates it.
    if ($Root) { return [System.IO.Path]::GetFullPath($Root) }
    $leaf = Split-Path -Leaf $RepoPath
    return [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $RepoPath) "_worktrees\$leaf"))
}

function Get-WorktreeRoots([string]$RepoPath, [string]$FleetRoot) {
    # The actual roots in play: the configured one plus wherever existing agent worktrees live, so
    # status/clean find a fleet even when it was created with a different -Root.
    $roots = @()
    if (Test-Path -LiteralPath $FleetRoot) { $roots += $FleetRoot }
    foreach ($t in (Get-AgentWorktrees $RepoPath)) {
        $parent = Split-Path -Parent $t.path
        if ($roots -notcontains $parent) { $roots += $parent }
    }
    return $roots
}

function Invoke-Git([string]$RepoPath, [string[]]$GitArgs) {
    # Returns @{ ok = $true/$false; out = <text> } and never throws on a non-zero git exit, so callers
    # can print a readable reason instead of a PowerShell stack trace.
    $out = & git -C $RepoPath @GitArgs 2>&1
    return @{ ok = ($LASTEXITCODE -eq 0); out = ($out | Out-String).Trim() }
}

function Get-AgentWorktrees([string]$RepoPath) {
    $lines = (& git -C $RepoPath worktree list --porcelain) -join "`n"
    $trees = @()
    $current = $null
    foreach ($line in ($lines -split "`n")) {
        if ($line -like 'worktree *') {
            if ($current) { $trees += $current }
            $current = [ordered]@{ path = $line.Substring(9).Trim(); branch = '' }
        }
        elseif ($current -and $line -like 'branch *') {
            $current.branch = ($line.Substring(7).Trim() -replace '^refs/heads/', '')
        }
    }
    if ($current) { $trees += $current }
    return $trees | Where-Object { $_.branch -like 'agent/*' }
}

function Get-DirSizeMB([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if (-not $sum) { return 0 }
    return [math]::Round($sum / 1MB, 1)
}

function Show-Status([string]$RepoPath, [string]$FleetRoot) {
    $trees = @(Get-AgentWorktrees $RepoPath)
    Write-Host "repo:  $RepoPath"
    Write-Host "fleet: $FleetRoot"
    if ($trees.Count -eq 0) { Write-Host "`nno agent worktrees." -ForegroundColor Yellow; return }

    Write-Host ("`n{0,-28} {1,-34} {2,-9} {3,-8} {4,-8} {5}" -f 'name', 'branch', 'dirty', 'artifacts', 'size MB', 'path')
    Write-Host ('-' * 118)
    $total = 0
    foreach ($t in $trees) {
        $dirty = (& git -C $t.path status --porcelain 2>$null | Measure-Object).Count
        $art = 0
        foreach ($pat in @('_pt_*', '__pycache__', '.gradle', 'node_modules')) {
            $art += (Get-ChildItem -LiteralPath $t.path -Recurse -Directory -Force -Filter $pat -ErrorAction SilentlyContinue | Measure-Object).Count
        }
        $size = Get-DirSizeMB $t.path
        $total += $size
        Write-Host ("{0,-28} {1,-34} {2,-9} {3,-8} {4,-8} {5}" -f `
            (Split-Path -Leaf $t.path), $t.branch, $dirty, $art, $size, $t.path)
    }
    Write-Host ('-' * 118)
    Write-Host ("total on disk: {0} MB across {1} worktree(s)" -f ([math]::Round($total, 1)), $trees.Count)
    Write-Host "`nReminder: 'dirty' > 0 on a branch you intend to merge means the work is not committed."
}

function Clear-Artifacts([string]$Path) {
    $removed = 0
    foreach ($pat in @('_pt_*', '__pycache__', '.pytest_cache')) {
        Get-ChildItem -LiteralPath $Path -Recurse -Directory -Force -Filter $pat -ErrorAction SilentlyContinue |
            ForEach-Object {
                # Only ever remove the patterns above; never a caller-supplied path.
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
                $removed++
            }
    }
    return $removed
}

$repoPath = Get-RepoPath
$fleetRoot = Get-FleetRoot $repoPath

switch ($Action) {

    'new' {
        if ($Name.Count -eq 0) { throw "-Name is required for 'new' (comma-separated slugs, e.g. -Name a,b,c)" }
        New-Item -ItemType Directory -Force -Path $fleetRoot | Out-Null

        $status = Invoke-Git $repoPath @('status', '--porcelain')
        if (-not $status.ok) { throw "git status failed: $($status.out)" }
        if ($status.out) {
            throw "Refusing to create a fleet: '$repoPath' has uncommitted changes. A branch cut from a dirty base produces a merge nobody can reason about. Commit or stash first.`n$($status.out)"
        }

        Invoke-Git $repoPath @('fetch', '--quiet', 'origin') | Out-Null
        $head = (Invoke-Git $repoPath @('rev-parse', '--short', 'HEAD')).out
        Write-Host "base $Base @ $head — creating $($Name.Count) worktree(s) under $fleetRoot`n"

        $created = 0
        foreach ($n in $Name) {
            $slug = ($n -replace '[^A-Za-z0-9._-]', '-').ToLower()
            $path = Join-Path $fleetRoot $slug
            $branch = "agent/$slug"
            if (Test-Path -LiteralPath $path) { Write-Host "SKIP  $slug (path exists)" -ForegroundColor Yellow; continue }
            if ((Invoke-Git $repoPath @('rev-parse', '--verify', '--quiet', $branch)).ok) {
                # Branch already exists (a previous fleet). Attach to it rather than failing, so an
                # interrupted run can be resumed instead of leaving the branch unreachable.
                $r = Invoke-Git $repoPath @('worktree', 'add', '--quiet', $path, $branch)
            }
            else {
                $r = Invoke-Git $repoPath @('worktree', 'add', '--quiet', '-b', $branch, $path, $Base)
            }
            if ($r.ok -and (Test-Path -LiteralPath $path)) {
                Write-Host "OK    $slug  ->  $path  [$branch]"
                $created++
            }
            else {
                Write-Host "FAIL  $slug  $($r.out)" -ForegroundColor Red
            }
        }
        Write-Host "`n$created worktree(s) ready. Each agent must be told its absolute path and that it may not push."
    }

    'status' { Show-Status $repoPath $fleetRoot }

    # "Can this machine host a fleet" and "is this repo ready right now" are different questions.
    # Conflating them is how a tool says READY and then refuses to do the thing.
    'doctor' {
        $ok = $true
        Write-Host "repo:       $repoPath"
        Write-Host "fleet root: $fleetRoot`n"

        $gitVer = (& git --version) 2>$null
        Write-Host ("{0,-28} {1}" -f 'git', ($(if ($gitVer) { $gitVer } else { 'MISSING' })))
        if (-not $gitVer) { $ok = $false }

        $py = (Get-Command python -ErrorAction SilentlyContinue)
        Write-Host ("{0,-28} {1}" -f 'python', ($(if ($py) { $py.Source } else { 'MISSING (optional)' })))

        $wt = Invoke-Git $repoPath @('worktree', 'list')
        Write-Host ("{0,-28} {1}" -f 'worktrees supported', ($(if ($wt.ok) { 'yes' } else { 'NO - git too old' })))
        if (-not $wt.ok) { $ok = $false }

        $parent = Split-Path -Parent $fleetRoot
        New-Item -ItemType Directory -Force -Path $parent -ErrorAction SilentlyContinue | Out-Null
        $writable = $true
        try { $probe = Join-Path $parent ('.write-probe-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType File -Path $probe -Force | Out-Null; Remove-Item $probe -Force }
        catch { $writable = $false }
        Write-Host ("{0,-28} {1}" -f 'fleet root writable', ($(if ($writable) { "yes ($parent)" } else { "NO ($parent)" })))
        if (-not $writable) { $ok = $false }

        $gitdir = (Invoke-Git $repoPath @('rev-parse', '--git-dir')).out
        $nested = $gitdir -match '[\\/]worktrees[\\/]'
        Write-Host ("{0,-28} {1}" -f 'nested worktree', ($(if ($nested) { 'YES - do not create a fleet from here' } else { 'no' })))
        if ($nested) { $ok = $false }

        $dirty = (& git -C $repoPath status --porcelain 2>$null | Measure-Object).Count
        Write-Host ("{0,-28} {1}" -f 'base clean', ($(if ($dirty -eq 0) { 'yes' } else { "NO ($dirty changed) - 'new' will refuse" })))

        Write-Host ''
        if (-not $ok) { Write-Host 'NOT READY: this machine cannot host a fleet - see the failures above.' -ForegroundColor Red; exit 1 }
        if ($dirty -ne 0) {
            Write-Host 'CAPABLE, not ready: this machine can host a fleet, but the base has uncommitted changes' -ForegroundColor Yellow
            Write-Host "and 'new' will refuse until it is clean. Commit or stash first."; exit 1
        }
        Write-Host 'READY: this machine can host a fleet, and the base is clean enough to cut branches from.' -ForegroundColor Green
    }

    'clean' {
        $trees = @(Get-AgentWorktrees $repoPath)
        $paths = @(Get-WorktreeRoots $repoPath $fleetRoot) + ($trees | ForEach-Object { $_.path })
        $total = 0
        foreach ($p in $paths) {
            if (Test-Path -LiteralPath $p) {
                $n = Clear-Artifacts $p
                if ($n) { Write-Host ("cleaned {0,-46} {1} dir(s)" -f $p, $n) }
                $total += $n
            }
        }
        Write-Host "`nremoved $total artifact director(ies)."
    }

    'rm' {
        if ($Name.Count -eq 0) { throw "-Name is required for 'rm'" }
        foreach ($n in $Name) {
            $slug = ($n -replace '[^A-Za-z0-9._-]', '-').ToLower()
            $path = Join-Path $fleetRoot $slug
            if (-not (Test-Path -LiteralPath $path)) { Write-Host "SKIP  $slug (no such worktree)" -ForegroundColor Yellow; continue }
            $args = @('worktree', 'remove', $path)
            if ($Force) { $args += '--force' }
            $r = Invoke-Git $repoPath $args
            if ($r.ok) { Write-Host "OK    removed $slug  (branch agent/$slug kept)" }
            else { Write-Host "FAIL  $slug  $($r.out)" -ForegroundColor Red; Write-Host "      (dirty worktree: commit, or pass -Force to discard)" }
        }
    }

    'rmall' {
        $trees = @(Get-AgentWorktrees $repoPath)
        if ($trees.Count -eq 0) { Write-Host "nothing to remove."; return }
        foreach ($t in $trees) {
            $slug = Split-Path -Leaf $t.path
            if (-not $Force) {
                $dirty = (& git -C $t.path status --porcelain 2>$null | Measure-Object).Count
                if ($dirty) { Write-Host "SKIP  $slug (dirty; commit or pass -Force)" -ForegroundColor Yellow; continue }
            }
            $args = @('worktree', 'remove', $t.path)
            if ($Force) { $args += '--force' }
            $r = Invoke-Git $repoPath $args
            if ($r.ok) { Write-Host "OK    removed $slug  (branch kept)" } else { Write-Host "FAIL  $slug  $($r.out)" -ForegroundColor Red }
        }
        Invoke-Git $repoPath @('worktree', 'prune') | Out-Null
        Write-Host "`nBranches are kept on purpose so unmerged work stays salvageable. Inspect with: git branch --list 'agent/*'"
    }
}
