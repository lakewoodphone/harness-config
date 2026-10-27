# verify-worktrees.ps1 - decide, per agent working copy, whether deleting it can lose anything.
#
# A directory is SAFE only if all three hold:
#   1. no modified tracked files          (git status --porcelain, lines not starting with "??")
#   2. no untracked AND non-ignored files (the "??" lines - build output is ignored, real work is not)
#   3. its HEAD is reachable from a remote branch (git branch -r --contains HEAD is non-empty)
# Anything else is HOLD with the reason. Containers (a dir that is not itself a repo but holds repos)
# are expanded one level so each checkout is judged on its own.
param(
  [string] $RootsFile = 'C:\Users\ezabz\Code\_audit\wt-roots.txt',
  [string] $Out = 'C:\Users\ezabz\Code\_audit\worktree-verdict.tsv',
  [int] $Throttle = 8
)
$ErrorActionPreference = 'SilentlyContinue'

$cands = New-Object System.Collections.Generic.List[string]
foreach ($r in (Get-Content -LiteralPath $RootsFile | Where-Object { $_.Trim() })) {
  if (-not (Test-Path -LiteralPath $r)) { continue }
  if (Test-Path -LiteralPath (Join-Path $r '.git')) { $cands.Add($r); continue }
  # container: take its repo children
  $kids = Get-ChildItem -LiteralPath $r -Directory -Force | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName '.git') }
  if ($kids) { foreach ($k in $kids) { $cands.Add($k.FullName) } }
  else { $cands.Add($r) }   # not a repo at all - judge by age only, verdict HOLD
}

Write-Host "judging $($cands.Count) directories"

$cands | ForEach-Object -Parallel {
  $d = $_
  $isRepo = Test-Path -LiteralPath (Join-Path $d '.git')
  $dirty = 0; $untracked = 0; $branch = ''; $head = ''; $onRemote = $false
  if ($isRepo) {
    $st = git -C $d status --porcelain 2>$null
    $dirty = @($st | Where-Object { $_ -notmatch '^\?\?' }).Count
    $untracked = @($st | Where-Object { $_ -match '^\?\?' }).Count
    $branch = (git -C $d rev-parse --abbrev-ref HEAD 2>$null)
    $head = (git -C $d rev-parse --short HEAD 2>$null)
    $rem = git -C $d branch -r --contains HEAD 2>$null
    $onRemote = [bool](@($rem | Where-Object { $_ -match '\S' }).Count)
  }
  $verdict = if (-not $isRepo) { 'HOLD-no-repo' }
             elseif ($dirty -gt 0) { 'HOLD-modified' }
             elseif ($untracked -gt 0) { 'HOLD-untracked' }
             elseif (-not $onRemote) { 'HOLD-not-on-remote' }
             else { 'SAFE' }
  [pscustomobject]@{ Path = $d; Repo = $isRepo; Branch = $branch; Head = $head; Dirty = $dirty
                     Untracked = $untracked; OnRemote = $onRemote; Verdict = $verdict
                     MTime = (Get-Item -LiteralPath $d -Force).LastWriteTime.ToString('yyyy-MM-dd') }
} -ThrottleLimit $Throttle | Sort-Object Verdict, Path | Export-Csv -LiteralPath $Out -NoTypeInformation -Encoding utf8

$v = Import-Csv $Out
$v | Group-Object Verdict | ForEach-Object { "{0,-20} {1,4}" -f $_.Name, $_.Count }
