<#
.SYNOPSIS
  Show every branch in every repository that holds commits that are not on the trunk.

.DESCRIPTION
  Why this exists. Measured 2026-09-28 (journal P2555): the kosher-filter-ai product had not moved
  on `main` for ten days, while three branches held *finished* work nobody merged — 878 lines of the
  audit's headline Android fix (unmerged 11 days), 6,584 lines of the only work in the repo that
  month, and 703 lines of the onboarding level step. Nothing in the session-start ritual showed any
  of it. A branch is not a deliverable, and an unreported branch is not even a fact.

  This makes the rot visible in one command. It answers one question per repository: what work exists
  that the trunk does not have, how big is it, and how long has it been sitting there.

  Read-only: it fetches (to see remote branches as they really are) and prints. It never merges,
  deletes, prunes or resets anything.

  The `--Days` filter is deliberately absent: a branch one day old may be a colleague's live work,
  and a branch sixty days old may be a deliberate archive. Age is printed, never used to hide.

.PARAMETER Root
  Directory whose immediate subdirectories are examined for git repositories. Default: ~/code.

.PARAMETER Repo
  One or more explicit repository paths. Overrides -Root.

.PARAMETER Trunk
  Candidate trunk names, in preference order. Default: main, master.

.PARAMETER NoFetch
  Skip `git fetch`. Faster and works offline, but reports the remote branches as last fetched.

.PARAMETER MinCommits
  Only report branches at least this many commits ahead of the trunk. Default 1 (everything).

.EXAMPLE
  pwsh -File unmerged-branches.ps1
  pwsh -File unmerged-branches.ps1 -Repo C:\Users\ezabz\code\kosher-filter-ai
  pwsh -File unmerged-branches.ps1 -MinCommits 5 -NoFetch
#>
[CmdletBinding()]
param(
    [string]$Root = (Join-Path $HOME 'code'),
    [string[]]$Repo,
    [string[]]$Trunk = @('main', 'master'),
    [switch]$NoFetch,
    [int]$MinCommits = 1
)

$ErrorActionPreference = 'Continue'

function Get-Trunk([string]$repoPath) {
    foreach ($t in $Trunk) {
        foreach ($ref in @("refs/remotes/origin/$t", "refs/heads/$t")) {
            $sha = (& git -C $repoPath rev-parse --verify --quiet $ref) 2>$null
            if ($LASTEXITCODE -eq 0 -and $sha) { return $ref }
        }
    }
    return $null
}

function Get-Repos {
    if ($Repo) {
        foreach ($r in $Repo) { if (Test-Path -LiteralPath (Join-Path $r '.git')) { $r } }
        return
    }
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike '_*' -and (Test-Path -LiteralPath (Join-Path $_.FullName '.git')) } |
        ForEach-Object { $_.FullName }
}

$now = Get-Date
$rows = @()
$scanned = 0
$skipped = @()

foreach ($r in Get-Repos) {
    $scanned++
    $name = Split-Path -Leaf $r
    if (-not $NoFetch) { & git -C $r fetch --quiet --all --prune 2>$null | Out-Null }

    $trunkRef = Get-Trunk $r
    if (-not $trunkRef) { $skipped += "$name (no main/master)"; continue }

    # -a covers local and remote-tracking branches; the symbolic origin/HEAD is excluded by the
    # --no-merged filter failing on it, but filter it explicitly so the output never shows "HEAD".
    $branches = & git -C $r for-each-ref --no-merged $trunkRef `
        --format='%(refname:short)|%(committerdate:iso-strict)|%(subject)' refs/heads refs/remotes 2>$null
    if (-not $branches) { continue }

    foreach ($line in $branches) {
        $parts = $line -split '\|', 3
        if ($parts.Count -lt 3) { continue }
        $branch = $parts[0].Trim()
        if ($branch -eq 'origin/HEAD' -or $branch -like 'origin/HEAD*') { continue }
        if ($branch -eq 'HEAD') { continue }

        $ahead = & git -C $r rev-list --count "$trunkRef..$branch" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ahead) { continue }
        $ahead = [int]$ahead
        if ($ahead -lt $MinCommits) { continue }

        $stat = & git -C $r diff --shortstat "$trunkRef...$branch" 2>$null
        $ins = 0; $del = 0; $files = 0
        if ($stat -match '(\d+) files? changed') { $files = [int]$Matches[1] }
        if ($stat -match '(\d+) insertions?') { $ins = [int]$Matches[1] }
        if ($stat -match '(\d+) deletions?') { $del = [int]$Matches[1] }

        $when = $null
        try { $when = [datetime]::Parse($parts[1].Trim()) } catch { }
        $days = if ($when) { [int]($now - $when).TotalDays } else { -1 }

        $rows += [pscustomobject]@{
            Repo    = $name
            Branch  = $branch
            Ahead   = $ahead
            Files   = $files
            Added   = $ins
            Removed = $del
            Days    = $days
            Last    = if ($when) { $when.ToString('yyyy-MM-dd') } else { '?' }
            Subject = ($parts[2].Trim() -replace '\s+', ' ')
        }
    }
}

if ($rows.Count -eq 0) {
    Write-Host ""
    Write-Host ("clean: no branch of {0} scanned repositor{1} holds work the trunk does not have." -f $scanned, $(if ($scanned -eq 1) { 'y' } else { 'ies' })) -ForegroundColor Green
} else {
    $rows = $rows | Sort-Object -Property @{Expression = 'Days'; Descending = $true }, 'Repo', 'Branch'
    Write-Host ""
    Write-Host ("{0} unmerged branch(es) across {1} repo(s)  --  a branch is not a deliverable" -f $rows.Count, ($rows.Repo | Sort-Object -Unique).Count) -ForegroundColor Yellow
    Write-Host ""
    $rows | Format-Table -AutoSize -Property @(
        @{ L = 'repo'; E = { $_.Repo } },
        @{ L = 'branch'; E = { $_.Branch } },
        @{ L = 'ahead'; E = { $_.Ahead } },
        @{ L = 'files'; E = { $_.Files } },
        @{ L = 'added'; E = { $_.Added } },
        @{ L = 'idle_d'; E = { $_.Days } },
        @{ L = 'last'; E = { $_.Last } },
        @{ L = 'subject'; E = { if ($_.Subject.Length -gt 64) { $_.Subject.Substring(0, 64) } else { $_.Subject } } }
    ) | Out-String -Width 220 | Write-Host

    $stale = $rows | Where-Object { $_.Days -ge 14 }
    if ($stale) {
        Write-Host ("{0} of them are 14+ days idle. The oldest is {1} days ({2} on {3})." -f `
            $stale.Count, $stale[0].Days, $stale[0].Branch, $stale[0].Repo) -ForegroundColor Yellow
    }
}

if ($skipped) { Write-Host ("`nskipped: {0}" -f ($skipped -join '; ')) }
