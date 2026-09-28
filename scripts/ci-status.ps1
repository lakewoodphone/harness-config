<#
.SYNOPSIS
  Show the CI state of every repository's trunk, and shout when one is red.

.DESCRIPTION
  Why this exists. Measured 2026-09-28 (journal P2563): `kosher-filter-ai`'s Android CI had been red
  on `main` since 2026-09-15 and its Server CI since 2026-09-15 19:51 - ten to thirteen days - and
  nothing anywhere reported it. Both were still red on the day this was written, including the
  current main tip's own run. The one workflow that stayed green throughout was a health probe that
  measures a *service*, not the code, so a green light coexisted with two dead guards. A red alarm
  nobody reads is worse than no alarm: it makes the next real failure invisible.

  This prints the trunk's state in one line per repository, newest run first, and exits non-zero if
  any trunk is red so it can gate something.

  Read-only. It needs the GitHub CLI (`gh`) authenticated, and it does nothing at all for a
  repository whose remote is not on github.com.

.PARAMETER Root
  Directory whose immediate subdirectories are examined for git repositories. Default: ~/code.

.PARAMETER Repo
  One or more explicit repository paths. Overrides -Root.

.PARAMETER Trunk
  Branch to inspect. Default: main.

.PARAMETER Limit
  How many recent runs to consider per repository. Default 1 (just the trunk's latest state).

.EXAMPLE
  pwsh -File ci-status.ps1
  pwsh -File ci-status.ps1 -Repo C:\Users\ezabz\code\kosher-filter-ai -Limit 5
#>
[CmdletBinding()]
param(
    [string]$Root = (Join-Path $HOME 'code'),
    [string[]]$Repo,
    [string]$Trunk = 'main',
    [int]$Limit = 1
)

$ErrorActionPreference = 'Continue'

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "gh (GitHub CLI) is not installed - cannot read CI state. This is a refusal, not a clean bill of health." -ForegroundColor Yellow
    exit 3
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

# "owner/name" from any github remote shape: https, ssh (git@github.com:owner/name.git), git://
function Get-GitHubSlug([string]$repoPath) {
    $urls = & git -C $repoPath remote -v 2>$null
    foreach ($u in $urls) {
        if ($u -match 'github\.com[:/]([^/\s]+)/([^/\s]+?)(\.git)?\s') {
            return "$($Matches[1])/$($Matches[2])"
        }
    }
    return $null
}

$red = @()
$checked = 0
$skipped = @()

foreach ($r in Get-Repos) {
    $name = Split-Path -Leaf $r
    $slug = Get-GitHubSlug $r
    if (-not $slug) { $skipped += "$name (no github remote)"; continue }

    $json = & gh run list --repo $slug --branch $Trunk --limit $Limit `
        --json databaseId,conclusion,status,workflowName,displayTitle,createdAt,url 2>&1
    if ($LASTEXITCODE -ne 0) { $skipped += "${name} ($slug): $($json -join ' ')".Trim(); continue }

    $runs = $null
    try { $runs = $json | ConvertFrom-Json } catch { $skipped += "${name}: unreadable gh output"; continue }
    if (-not $runs) { $skipped += "${name}: no runs on '$Trunk'"; continue }

    $checked++
    foreach ($run in $runs) {
        $state = if ($run.status -ne 'completed') { $run.status } else { $run.conclusion }
        $colour = switch ($state) {
            'success' { 'Green' }
            'failure' { 'Red' }
            'cancelled' { 'DarkYellow' }
            default { 'DarkGray' }
        }
        if ($state -eq 'failure') { $red += [pscustomobject]@{ Repo = $name; Slug = $slug; Workflow = $run.workflowName; When = $run.createdAt; Url = $run.url } }
        Write-Host ("{0,-24} {1,-18} {2,-10} {3}" -f $name, $run.workflowName, $state, $run.createdAt) -ForegroundColor $colour
    }
}

Write-Host ""
if ($red.Count -eq 0) {
    Write-Host ("green: no failing run on '{0}' across {1} github repositor{2}." -f $Trunk, $checked, $(if ($checked -eq 1) { 'y' } else { 'ies' })) -ForegroundColor Green
} else {
    Write-Host ("{0} FAILING run(s) on '{1}'. A red trunk is the cheapest early warning there is." -f $red.Count, $Trunk) -ForegroundColor Red
    foreach ($x in $red) { Write-Host ("  {0}  {1}  {2}" -f $x.Repo, $x.Workflow, $x.Url) -ForegroundColor Red }
}
if ($skipped) { Write-Host ("`nnot checked: {0}" -f ($skipped -join '; ')) -ForegroundColor DarkGray }

exit $(if ($red.Count -gt 0) { 1 } else { 0 })
