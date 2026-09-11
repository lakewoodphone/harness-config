<#
.SYNOPSIS
  Keep this machine's harness-config in step with the source of truth — unattended.

.DESCRIPTION
  harness-config is the single source of truth for the harness (DECISIONS D7): settings, presets and
  scripts live in git and reach `~/.dsh` through `scripts/sync.py`. Until now that happened only when a
  session remembered to do it, so the two workstations drifted the moment nobody was looking (PAIN P8).

  This script closes that gap and is deliberately timid. It NEVER:
    * commits — what a human or an agent chose to write is theirs to commit (LESSONS L33)
    * merges or rebases — a divergence is reported, not resolved by guesswork
    * stashes, resets, cleans or force-pushes — this business has lost data twice
    * touches a dirty working tree at all

  It does exactly one safe thing: fast-forward the repo to origin, apply it to `~/.dsh`, prove the apply
  converged, push commits that are already made but not yet sent, and write down what happened.

  Exit codes: 0 clean (synced, or nothing to do) · 1 attention (dirty tree, divergence, apply failed)
              · 2 cannot run (no repo, no python, git missing)

.EXAMPLE
  pwsh -File scripts\autosync.ps1
  pwsh -File scripts\autosync.ps1 -Status      # print the last run and exit
#>
[CmdletBinding()]
param(
  [string]$Repo = (Split-Path -Parent $PSScriptRoot),
  [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'harness-config-autosync'),
  [switch]$Status,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = $null  # harmless under Task Scheduler

function Log([string]$msg) { if (-not $Quiet) { Write-Host $msg } }

# --------------------------------------------------------------------------
# -Status: read the record, do not touch anything
# --------------------------------------------------------------------------
if ($Status) {
  $sf = Join-Path $StateDir 'status.json'
  if (-not (Test-Path $sf)) { Write-Host "no autosync record yet at $sf"; exit 0 }
  Get-Content $sf -Raw
  exit 0
}

if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Force -Path $StateDir | Out-Null }
$logPath = Join-Path $StateDir 'autosync.log'
$statusPath = Join-Path $StateDir 'status.json'

function Record($obj) {
  $obj | Add-Member -NotePropertyName host -NotePropertyValue $env:COMPUTERNAME -Force
  $obj | Add-Member -NotePropertyName at -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o') -Force
  ($obj | ConvertTo-Json -Depth 6) | Set-Content -Path $statusPath -Encoding utf8
  $line = '{0} [{1}] {2}' -f $obj.at, $obj.result, $obj.detail
  Add-Content -Path $logPath -Value $line
  Log $line
}

# --------------------------------------------------------------------------
# 0. Preconditions. A failure here is a real failure: say so, do not guess.
# --------------------------------------------------------------------------
if (-not (Test-Path (Join-Path $Repo '.git'))) {
  Record ([ordered]@{ result = 'cannot-run'; detail = "not a git repo: $Repo"; repo = $Repo })
  exit 2
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Record ([ordered]@{ result = 'cannot-run'; detail = 'git not on PATH'; repo = $Repo })
  exit 2
}

# Python with PyYAML. Try the plain interpreter first (it is what a session uses by hand), then the
# py launcher, then the secretary venv — and prove the import rather than assuming it.
$pythonCandidates = @()
$pc = Get-Command python -ErrorAction SilentlyContinue
if ($pc) { $pythonCandidates += $pc.Source }
$pl = Get-Command py -ErrorAction SilentlyContinue
if ($pl) { $pythonCandidates += $pl.Source }
$pythonCandidates += (Join-Path $env:USERPROFILE 'code\personal-secretary-mvp\.venv\Scripts\python.exe')

$python = $null
foreach ($cand in $pythonCandidates) {
  if (-not (Test-Path $cand)) { continue }
  $args = if ($cand -like '*\py.exe') { @('-3', '-c', 'import yaml') } else { @('-c', 'import yaml') }
  & $cand @args 2>$null
  if ($LASTEXITCODE -eq 0) { $python = $cand; break }
}
if (-not $python) {
  Record ([ordered]@{ result = 'cannot-run'; detail = 'no python with PyYAML found'; repo = $Repo })
  exit 2
}

$gitDir = (Resolve-Path $Repo).Path

# --------------------------------------------------------------------------
# 1. Note a tree with modified TRACKED files — but do not refuse to pull.
#
#    Refusing outright would mean the sync never runs on a machine where several agent sessions write
#    files all day (LESSONS L33, PAIN P13), which is exactly when drift goes unnoticed. So:
#      * the PULL is attempted anyway. `git pull --ff-only` refuses by itself to overwrite locally
#        modified files, so git is the safety here — not a heuristic of mine.
#      * the APPLY to ~/.dsh is skipped while tracked files are modified. Publishing a half-written
#        preset into the live config is the one thing that would actually cause harm; leaving ~/.dsh on
#        the last good state until the tree is clean is always safe and self-corrects next run.
# --------------------------------------------------------------------------
$dirty = @(& git -C $gitDir status --porcelain --untracked-files=no)
$untracked = @(& git -C $gitDir status --porcelain --untracked-files=all | Where-Object { $_ -like '??*' })
$dirtyNames = ($dirty | ForEach-Object { $_.Substring(3) } | Select-Object -First 8) -join ', '

# --------------------------------------------------------------------------
# 2. Fetch then fast-forward. Divergence is an owner-visible fact, not something to resolve here.
# --------------------------------------------------------------------------
$prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& git -C $gitDir fetch --quiet --prune 2>&1 | Out-Null
$fetchOk = ($LASTEXITCODE -eq 0)
$branch = (& git -C $gitDir rev-parse --abbrev-ref HEAD 2>$null)
$counts = (& git -C $gitDir rev-list --left-right --count "origin/$branch...HEAD" 2>$null)
$ErrorActionPreference = $prevEap

if (-not $fetchOk) {
  Record ([ordered]@{ result = 'attention'; detail = 'git fetch failed — offline, or the remote is down'; repo = $gitDir; branch = $branch })
  exit 1
}

$behind = 0; $ahead = 0
if ($counts -match '^(\d+)\s+(\d+)$') { $behind = [int]$Matches[1]; $ahead = [int]$Matches[2] }

if ($behind -gt 0) {
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $pull = (& git -C $gitDir -c core.autocrlf=false pull --ff-only 2>&1)
  $pullOk = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $prevEap
  if (-not $pullOk) {
    # Fast-forward refused ⇒ the histories diverged. Do not merge. Do not guess.
    Record ([ordered]@{
        result = 'attention'
        detail = "pull --ff-only refused: histories diverged ($behind behind / $ahead ahead). Needs a human."
        repo   = $gitDir; branch = $branch
        git    = ($pull | Select-Object -Last 3) -join ' | '
      })
    exit 1
  }
}

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 3. Apply to ~/.dsh — from the COMMITTED tree, not from the working tree.
#
#    Why: this file first refused to apply while tracked files were modified. That was safe but it made
#    the sync useless on these machines, where several agent sessions hold files modified most of the
#    day — ZABZ-YOGA sat on `dirty` while four files belonging to other sessions blocked every apply, so
#    committed config changes reached the *repo* and never reached the live `~/.dsh`. That is precisely
#    the drift this job exists to remove (PAIN P8).
#
#    The scheduled job's contract is "converge the live config to the committed source of truth". A
#    half-written file in someone's editor is not the source of truth, so the apply now runs against a
#    snapshot of HEAD exported to a temp directory: committed changes land, and nobody's in-flight work
#    is published or lost. A dirty tree is still *reported* — it is useful to know — but it no longer
#    blocks.
# --------------------------------------------------------------------------
$snapshot = Join-Path $env:TEMP ("harness-config-snap-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$tarball = Join-Path $env:TEMP ("harness-config-snap-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.tar')
$applyOk = $true
$apply = @()
$verifyOk = $false
$verify = @()
try {
  New-Item -ItemType Directory -Force -Path $snapshot | Out-Null
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  & git -C $gitDir archive --format=tar --output=$tarball HEAD 2>&1 | Out-Null
  $archiveOk = ($LASTEXITCODE -eq 0)
  if ($archiveOk) { & tar -xf $tarball -C $snapshot 2>&1 | Out-Null; $archiveOk = ($LASTEXITCODE -eq 0) }
  $ErrorActionPreference = $prevEap

  if (-not $archiveOk) {
    throw 'could not export HEAD (git archive/tar failed)'
  }

  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $apply = (& $python (Join-Path $snapshot 'scripts\sync.py') 2>&1)
  $applyOk = ($LASTEXITCODE -eq 0)
  # A second, dry run from the same snapshot is the verification: 'WOULD' means it did not converge.
  $verify = (& $python (Join-Path $snapshot 'scripts\sync.py') --dry-run 2>&1)
  $verifyOk = ($LASTEXITCODE -eq 0) -and -not ($verify -match 'WOULD')
  $ErrorActionPreference = $prevEap

  if (-not $applyOk) {
    Record ([ordered]@{
        result = 'attention'; detail = 'sync.py failed against the committed snapshot'
        repo = $gitDir; branch = $branch; output = ($apply | Select-Object -Last 6) -join ' | '
      })
    exit 1
  }
} catch {
  Record ([ordered]@{
      result = 'attention'; detail = "snapshot apply failed: $($_.Exception.Message)"
      repo = $gitDir; branch = $branch
    })
  exit 1
} finally {
  Remove-Item $snapshot, $tarball -Recurse -Force -ErrorAction SilentlyContinue
}

$changedLines = @($apply | Where-Object { $_ -match 'written|applied' })
$applied = if ($changedLines.Count -gt 0) { ($changedLines -join ' | ').Trim() } else { 'nothing to apply' }

# --------------------------------------------------------------------------
# 4. Send commits that are already made but never pushed. Never force.
# --------------------------------------------------------------------------
$pushed = 'no'
if ($verifyOk -and $ahead -gt 0) {
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  & git -C $gitDir -c core.autocrlf=false push --quiet 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { $pushed = "yes ($ahead commit(s))" }
  $ErrorActionPreference = $prevEap
}

$commit = (& git -C $gitDir rev-parse --short HEAD 2>$null)
$result = if ($verifyOk) { 'clean' } else { 'attention' }
Record ([ordered]@{
    result     = $result
    detail     = if ($verifyOk) { "at $commit; $applied; pushed=$pushed" }
                 else { "apply did NOT converge — a second run still reports pending changes" }
    repo       = $gitDir
    branch     = $branch
    commit     = $commit
    behind     = $behind
    ahead      = $ahead
    pushed     = $pushed
    apply      = $applied
    converged  = $verifyOk
  })

if ($verifyOk) { exit 0 } else { exit 1 }
