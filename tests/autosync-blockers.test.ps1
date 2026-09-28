# test-autosync-blockers.ps1 - prove the 2026-09-28 blocker-clearing path on a scratch repo.
# Two scenarios, both built from scratch under $env:TEMP:
#   A) a modified GENERATED file + an untracked IDENTICAL file  -> cleared, fast-forward SUCCEEDS
#   B) an untracked DIFFERING file the incoming commit tracks   -> KEPT, pull refuses, path is NAMED
# Nothing here touches the real repo.
$ErrorActionPreference = 'Stop'
$script = 'C:\Users\ezabz\Code\harness-config\scripts\autosync.ps1'
$T = Join-Path $env:TEMP ('autosync-test-' + (Get-Date -Format 'yyyyMMddHHmmss'))
New-Item -ItemType Directory -Force -Path $T | Out-Null
Write-Output "scratch=$T"

function New-Fixture([string]$name, [string]$mode) {
  $base = Join-Path $T $name
  $origin = Join-Path $base 'origin.git'
  $seed = Join-Path $base 'seed'
  $work = Join-Path $base 'work'
  New-Item -ItemType Directory -Force -Path $base | Out-Null
  git init -q --bare $origin
  git init -q $seed
  New-Item -ItemType Directory -Force -Path (Join-Path $seed 'scripts') | Out-Null
  Set-Content (Join-Path $seed 'scripts\sync.py') "# stub`nimport sys`nprint('stub: nothing to apply')`nsys.exit(0)`n" -Encoding ascii
  New-Item -ItemType Directory -Force -Path (Join-Path $seed 'journal\index'), (Join-Path $seed 'journal\state') | Out-Null
  Set-Content (Join-Path $seed 'journal\index\stamp.json') '{"v":1}' -Encoding ascii
  Set-Content (Join-Path $seed 'journal\state\owner-questions.md') 'mirror v1' -Encoding ascii
  git -C $seed -c user.email=t@t -c user.name=t add -A
  git -C $seed -c user.email=t@t -c user.name=t commit -qm 'base'
  git -C $seed branch -M master
  git -C $seed remote add origin $origin
  git -C $seed push -q origin master

  # work clone == what the machine has. core.autocrlf=false from the clone itself, because that is
  # the config the pull runs under (autosync passes -c core.autocrlf=false); setting it afterwards
  # leaves CRLF worktree files behind and every one of them reads as locally modified.
  git clone -q --config core.autocrlf=false $origin $work
  git -C $work config user.email t@t
  git -C $work config user.name t
  git -C $seed config core.autocrlf false
  git -C $work branch -M master

  # upstream advances, touching the same generated paths (this is what a real incoming commit does)
  Set-Content (Join-Path $seed 'journal\index\stamp.json') '{"v":2}' -Encoding ascii
  Set-Content (Join-Path $seed 'journal\state\owner-questions.md') 'mirror v2' -Encoding ascii
  Set-Content (Join-Path $seed 'scripts\engine-vitals.mjs') "// new upstream file`n" -Encoding ascii
  git -C $seed add -A
  git -C $seed commit -qm 'upstream: touch generated files, add a new script'

  if ($mode -eq 'A') {
    # the machine's own writes, mid-flight, to the same generated paths
    Set-Content (Join-Path $work 'journal\index\stamp.json') '{"v":1,"local":true}' -Encoding ascii
    Set-Content (Join-Path $work 'journal\state\owner-questions.md') 'mirror v1 + local edit' -Encoding ascii
    # an untracked copy that is byte-identical to what upstream now tracks
    Copy-Item (Join-Path $seed 'scripts\engine-vitals.mjs') (Join-Path $work 'scripts\engine-vitals.mjs')
  } else {
    # an untracked file that DIFFERS from what upstream now tracks: unique work, must survive
    Set-Content (Join-Path $work 'scripts\engine-vitals.mjs') "// a different, locally-authored revision`n" -Encoding ascii
  }
  git -C $seed push -q origin master
  return [pscustomobject]@{ base = $base; work = $work; state = (Join-Path $base 'state') }
}

# ---------------- scenario A ----------------
$a = New-Fixture 'A' 'A'
$beforeA = (git -C $a.work rev-parse --short HEAD)
$outA = & pwsh -NoProfile -File $script -Repo $a.work -StateDir $a.state -SyncStatusDir (Join-Path $a.base 'status') 2>&1 | Out-String
$codeA = $LASTEXITCODE
$afterA = (git -C $a.work rev-parse --short HEAD)
$statusA = Get-Content (Join-Path $a.state 'status.json') -Raw | ConvertFrom-Json
Write-Output "--- SCENARIO A (generated + identical) ---"
Write-Output ("exit=$codeA  before=$beforeA after=$afterA  behind_after=" + (git -C $a.work rev-list --count "HEAD..origin/master"))
Write-Output ("result=" + $statusA.result + "  detail=" + $statusA.detail)
Write-Output ("blockers_cleared=" + $statusA.blockers_cleared + "  blockers_kept=" + $statusA.blockers_kept)
Write-Output ("backups=" + @(Get-ChildItem (Join-Path $a.state 'blockers') -Recurse -File -ErrorAction SilentlyContinue).Count)
Write-Output ("manifest:"); Get-ChildItem (Join-Path $a.state 'blockers') -Recurse -Filter manifest.tsv -ErrorAction SilentlyContinue | ForEach-Object { Get-Content $_.FullName }
$stampBk = @(Get-ChildItem (Join-Path $a.state 'blockers') -Recurse -Filter 'stamp.json' -ErrorAction SilentlyContinue)
Write-Output ("local stamp preserved in backup: " + $(if ($stampBk.Count) { Select-String -Path $stampBk[0].FullName -Pattern 'local' -Quiet } else { 'NO BACKUP FILE' }))

# ---------------- scenario B ----------------
$b = New-Fixture 'B' 'B'
$beforeB = (git -C $b.work rev-parse --short HEAD)
$hashBefore = (git -C $b.work hash-object -- (Join-Path $b.work 'scripts\engine-vitals.mjs'))
$outB = & pwsh -NoProfile -File $script -Repo $b.work -StateDir $b.state -SyncStatusDir (Join-Path $b.base 'status') 2>&1 | Out-String
$codeB = $LASTEXITCODE
$afterB = (git -C $b.work rev-parse --short HEAD)
$hashAfter = if (Test-Path (Join-Path $b.work 'scripts\engine-vitals.mjs')) { (git -C $b.work hash-object -- (Join-Path $b.work 'scripts\engine-vitals.mjs')) } else { 'DELETED' }
$statusB = Get-Content (Join-Path $b.state 'status.json') -Raw | ConvertFrom-Json
Write-Output "--- SCENARIO B (untracked, differs) ---"
Write-Output ("exit=$codeB  before=$beforeB after=$afterB (must be unchanged)")
Write-Output ("result=" + $statusB.result)
Write-Output ("detail=" + $statusB.detail)
Write-Output ("blockers_cleared=" + $statusB.blockers_cleared + "  blockers_kept=" + $statusB.blockers_kept)
Write-Output ("local file hash before=$hashBefore after=$hashAfter  untouched=" + ($hashBefore -eq $hashAfter))
Write-Output "scratch kept at $T"
