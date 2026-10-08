# sync-repos.ps1 - bring every repo on this machine toward its upstream. Conservative by design.
#
# NEVER: reset, clean, rebase, stash, force, delete a branch, touch a dirty working tree.
# DOES:  fetch | fast-forward when purely behind and the tracked tree is clean |
#        push when purely ahead | report everything else untouched.
#
# harness-config is excluded on purpose: scripts/autosync.ps1 owns it and this must not race it.
#
# Usage:  pwsh -File sync-repos.ps1            -> applies
#         pwsh -File sync-repos.ps1 -DryRun    -> reports only
[CmdletBinding()]
param(
  [string] $Root = (Join-Path $env:USERPROFILE 'code'),
  [switch] $DryRun
)
$ErrorActionPreference = 'Continue'

Write-Output ("machine`trepo`tbranch`tdirty`tahead`tbehind`taction`tresult")

$dirs = @(Get-ChildItem $Root -Directory -Force -ErrorAction SilentlyContinue)
foreach ($d in $dirs) {
  $name = $d.Name
  if ($name -match '^(harness-config|_.*|\..*|.*-backup-.*|.*\.bak-.*|.*-pre-unify-.*|.*worktree.*)$') { continue }
  if (-not (Test-Path (Join-Path $d.FullName '.git'))) {
    $g = git -C $d.FullName rev-parse --git-dir 2>$null
    if ($LASTEXITCODE -ne 0) { continue }
  }

  $branch = git -C $d.FullName rev-parse --abbrev-ref HEAD 2>$null
  if ($branch -eq 'HEAD' -or -not $branch) {
    Write-Output "$env:COMPUTERNAME`t$name`tHEAD`t-`t-`t-`tSKIP-DETACHED`tleft as found"
    continue
  }
  $dirty = @(git -C $d.FullName status --porcelain --untracked-files=no 2>$null).Count
  $up = git -C $d.FullName rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
  if (-not $up) {
    Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t-`t-`tNO-UPSTREAM`tleft as found"
    continue
  }

  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  git -C $d.FullName fetch --quiet --prune 2>&1 | Out-Null
  $fetchOk = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $prev
  if (-not $fetchOk) {
    Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t-`t-`tFETCH-FAILED`tunreachable, untouched"
    continue
  }

  $ahead  = git -C $d.FullName rev-list --count "$up..HEAD" 2>$null
  $behind = git -C $d.FullName rev-list --count "HEAD..$up" 2>$null
  if ($null -eq $ahead -or $null -eq $behind) { $ahead = '?'; $behind = '?' }
  $ahead = [string]$ahead; $behind = [string]$behind

  if ($ahead -eq '0' -and $behind -eq '0') {
    Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t0`t0`tOK`tin step with $up"
    continue
  }
  if ($ahead -ne '0' -and $behind -ne '0') {
    Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t$ahead`t$behind`tDIVERGED`treport only, nothing moved"
    continue
  }
  if ($ahead -ne '0') {
    if ($DryRun) { Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t$ahead`t0`tWOULD-PUSH`t(dry run)"; continue }
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    git -C $d.FullName push --quiet origin HEAD 2>&1 | Out-Null
    $pushOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    if ($pushOk) { Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t$ahead`t0`tPUSHED`t$ahead local commit(s) now on origin" }
    else { Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t$ahead`t0`tPUSH-REFUSED`tnot a fast-forward upstream, untouched" }
    continue
  }

  # purely behind
  if ($dirty -gt 0) {
    Write-Output "$env:COMPUTERNAME`t$name`t$branch`t$dirty`t0`t$behind`tBEHIND-DIRTY`t$dirty tracked file(s) modified, not pulled"
    continue
  }
  if ($DryRun) { Write-Output "$env:COMPUTERNAME`t$name`t$branch`t0`t0`t$behind`tWOULD-FF`t(dry run)"; continue }
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $out = (git -C $d.FullName merge --ff-only $up 2>&1 | Out-String)
  $ffOk = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $prev
  if ($ffOk) { Write-Output "$env:COMPUTERNAME`t$name`t$branch`t0`t0`t0`tFAST-FORWARDED`t$behind commits" }
  else {
    $why = (($out -split "`n" | Where-Object { $_ -match 'error|fatal|would be overwritten' } | Select-Object -First 1) -replace "`r",'').Trim()
    if ($why.Length -gt 90) { $why = $why.Substring(0,90) }
    Write-Output "$env:COMPUTERNAME`t$name`t$branch`t0`t0`t$behind`tFF-REFUSED`t$why"
  }
}
