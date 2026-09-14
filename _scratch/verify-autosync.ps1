<#
  verify-autosync.ps1 - prove the divergence fix on the REAL scripts/autosync.ps1.

  Three runs, all against a scratch bare remote so nothing of value can be touched, and all with
  LOCALAPPDATA / USERPROFILE / TEMP / DSH_HOME redirected into an isolated sandbox so the run cannot
  reach the live ~/.dsh or the live sync state:

    1  OLD (parent commit) + diverged clone  -> refuses, preserves nothing  (the defect)
    2  NEW + diverged clone                  -> local commit preserved on refs/heads/diverged-*, status says so
    2a NEW + ahead but fast-forwardable      -> plain push accepted, no side ref invented
    3  NEW + clean behind origin             -> still fast-forwards and applies (normal path unchanged)

  Run:  pwsh -NoProfile -File _scratch\verify-autosync.ps1
        powershell -NoProfile -File _scratch\verify-autosync.ps1    (run BOTH: see below)
  Nothing is deleted: every sandbox is kept and printed so the evidence can be re-read by hand.

  WHY BOTH INTERPRETERS: Windows PowerShell 5.1 does not populate $PSScriptRoot while evaluating
  parameter defaults, and reads a BOM-less .ps1 as ANSI. Both faults hit scripts/autosync.ps1 for real
  on 2026-09-14 and were invisible to a pwsh-only harness. A verifier that only ever runs under 7
  cannot see them, so this file is written to run under both.
#>
[CmdletBinding()]
param(
  [string]$Repo = '',
  [string]$Root = '',
  [string]$OldScript = ''
)

$ErrorActionPreference = 'Continue'   # native git writes to stderr; 5.1 would abort on it
$here = $PSScriptRoot; if (-not $here) { $here = Split-Path -Parent $PSCommandPath }
if (-not $Root) { $Root = Join-Path $here ('autosync-verify-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if (-not $Repo) {
  # this file lives in _scratch/, so the repo is wherever git says the toplevel is
  $Repo = (& git -C $here rev-parse --show-toplevel 2>$null)
  if (-not $Repo) { $Repo = (Split-Path -Parent $here) }
  $Repo = "$Repo".Trim()
}
$script:Fail = 0
$env:GIT_AUTHOR_NAME = 'autosync-verify'; $env:GIT_AUTHOR_EMAIL = 'verify@localhost'
$env:GIT_COMMITTER_NAME = 'autosync-verify'; $env:GIT_COMMITTER_EMAIL = 'verify@localhost'

function Head($m) { Write-Host ''; Write-Host ("=" * 78); Write-Host "== $m"; Write-Host ("=" * 78) }
function Note($m) { Write-Host "   $m" }
function Ok($m)   { Write-Host "   PASS  $m" }
function Bad($m)  { Write-Host "   FAIL  $m"; $script:Fail++ }
function Check($cond, $m) { if ($cond) { Ok $m } else { Bad $m } }

# Capture without dragging stderr into the error stream: under Windows PowerShell 5.1 a native
# command that writes anything to stderr (git does, for CRLF warnings) raises a NativeCommandError,
# and with ErrorActionPreference=Stop that aborts the whole harness. pwsh 7 does not, which is exactly
# the kind of difference that made this run under only one interpreter.
function G([string]$dir, [string[]]$gitArgs) { (& git -C $dir @gitArgs 2>&1 | Out-String) }
function Gq([string]$dir, [string[]]$gitArgs) { (& git -C $dir @gitArgs 2>$null | Out-String) }
function Gcode([string]$dir, [string[]]$gitArgs) { & git -C $dir @gitArgs 2>$null | Out-Null; $LASTEXITCODE }
# first non-empty output line (rev-parse, rev-list --count, ...) - G returns one string, so index it
function Gline([string]$dir, [string[]]$gitArgs) {
  $o = @((G $dir $gitArgs) -split "`r?`n" | Where-Object { $_.Trim() })
  if ($o.Count -gt 0) { $o[0].Trim() } else { '' }
}
# every non-empty output line (for-each-ref listings)
function Glines([string]$dir, [string[]]$gitArgs) {
  @((G $dir $gitArgs) -split "`r?`n" | Where-Object { $_.Trim() } | ForEach-Object { $_.TrimEnd() })
}

# A minimal but real tree: autosync needs scripts/sync.py (to apply) and settings/base.yaml (to apply).
function New-SeedRepo([string]$path) {
  New-Item -ItemType Directory -Force -Path (Join-Path $path 'scripts'), (Join-Path $path 'settings') | Out-Null
  Copy-Item (Join-Path $Repo 'scripts\sync.py') (Join-Path $path 'scripts\sync.py')
  Set-Content -Path (Join-Path $path 'settings\base.yaml') -Encoding utf8 -Value @(
    '# synthetic seed for verification', 'agent-default-model:', '  provider: deepseek-official', '  model: deepseek-flash')
  & git -C $path init --quiet --initial-branch=master | Out-Null
  G $path @('add', '-A') | Out-Null
  G $path @('commit', '-q', '-m', 'seed') | Out-Null
}

function New-Sandbox([string]$name) {
  $root = Join-Path $Root $name
  $remote = Join-Path $root 'remote.git'
  $clone = Join-Path $root 'clone'
  $state = Join-Path $root 'state'
  $fakeHome = Join-Path $root 'home'
  New-Item -ItemType Directory -Force -Path $root, $fakeHome | Out-Null
  & git init --quiet --bare --initial-branch=master $remote | Out-Null
  $seed = Join-Path $root 'seed'
  New-SeedRepo $seed
  & git -C $seed remote add origin $remote | Out-Null
  & git -C $seed push -q origin master | Out-Null
  & git clone -q $remote $clone 2>&1 | Out-Null
  & git -C $clone remote set-head origin -a 2>&1 | Out-Null
  & git -C $clone branch --set-upstream-to=origin/master master 2>&1 | Out-Null
  # sync.py refuses to apply unless DSH_HOME exists ("install DSH first"), which is correct of it.
  # A real machine always has it; make the sandbox look like one.
  New-Item -ItemType Directory -Force -Path (Join-Path $fakeHome '.dsh'), (Join-Path $fakeHome '.dsh\.agent-presets') | Out-Null
  [pscustomobject]@{ Root = $root; Remote = $remote; Clone = $clone; State = $state; HomeDir = $fakeHome }
}

# The old script has no -SyncStatusDir; only pass parameters the target script actually declares.
function Script-Params([string]$path) {
  $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$null)
  @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
}

# Run a specific autosync.ps1 (path sent) inside a sandbox, with the sandbox as the whole world.
function Run-Autosync([string]$scriptPath, $sb) {
  $prev = @{ L = $env:LOCALAPPDATA; U = $env:USERPROFILE; T = $env:TEMP; D = $env:DSH_HOME }
  $env:LOCALAPPDATA = $sb.State
  $env:USERPROFILE  = $sb.HomeDir
  $env:TEMP         = (Join-Path $sb.Root 'tmp')
  $env:DSH_HOME     = (Join-Path $sb.HomeDir '.dsh')
  New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
  $out = @()
  try {
    $scriptArgs = @('-Repo', $sb.Clone, '-StateDir', $sb.State)
    if ((Script-Params $scriptPath) -contains 'SyncStatusDir') {
      $scriptArgs += @('-SyncStatusDir', (Join-Path $sb.HomeDir '.dsh-sync-status'))
    }
    Write-Host "   [invoke] pwsh -File $scriptPath $($scriptArgs -join ' ')"
    Write-Host "   [invoke] LOCALAPPDATA=$env:LOCALAPPDATA"
    Write-Host "   [invoke] USERPROFILE=$env:USERPROFILE"
    $out = & pwsh -NoLogo -NoProfile -File $scriptPath @scriptArgs 2>&1
    $code = $LASTEXITCODE
    Write-Host "   [invoke] exit=$code output-bytes=$(($out | Out-String).Length)"
  } finally {
    $env:LOCALAPPDATA = $prev.L; $env:USERPROFILE = $prev.U; $env:TEMP = $prev.T; $env:DSH_HOME = $prev.D
  }
  [pscustomobject]@{ Output = ($out -join "`n"); Code = $code }
}

function Show-Status($sb) {
  $hostStatus = Join-Path $sb.State 'status.json'
  $syncStatus = Join-Path $sb.HomeDir '.dsh-sync-status\status.json'
  Note "per-host record  $hostStatus"
  if (Test-Path $hostStatus) { (Get-Content $hostStatus -Raw).Trim() | Write-Host } else { Write-Host '   (absent)' }
  Note "monitor record    $syncStatus"
  if (Test-Path $syncStatus) { (Get-Content $syncStatus -Raw).Trim() | Write-Host } else { Write-Host '   (absent)' }
  return [pscustomobject]@{
    Host = if (Test-Path $hostStatus) { Get-Content $hostStatus -Raw | ConvertFrom-Json } else { $null }
    Sync = if (Test-Path $syncStatus) { Get-Content $syncStatus -Raw | ConvertFrom-Json } else { $null }
  }
}

# Make the clone hold a commit the remote does not have, and the remote hold one it lacks: [ahead 1, behind 1].
function New-Divergence($sb, [string]$label) {
  & git -C $sb.Clone commit -q --allow-empty -m "$label local (must survive)" | Out-Null
  $seed = Join-Path $sb.Root 'seed'
  & git -C $seed commit -q --allow-empty -m 'upstream moved (must not be lost)' | Out-Null
  & git -C $seed push -q origin master | Out-Null
  & git -C $sb.Remote symbolic-ref HEAD refs/heads/master 2>&1 | Out-Null
  Note ("clone: " + ((Glines $sb.Clone @('rev-list', '--left-right', '--count', 'origin/master...HEAD')) -join ' ') + "   (behind ahead)")
}

New-Item -ItemType Directory -Force -Path $Root | Out-Null
Write-Host "harness-config: $Repo"
Write-Host "sandboxes:      $Root"
$oldScript = Join-Path $Root 'autosync-OLD.ps1'

# -- extract the pre-fix script from history - the real "before" -----------------------------------
# Do NOT assume HEAD~1: this repo is written to by several sessions, so the parent commit can already
# contain the fix (it did, and that silently turned TEST 1 into a no-op). Walk back until the file
# lacks the fix marker, and prefer an explicit -OldScript when one is supplied.
$oldScript = if ($OldScript) { $OldScript } else { Join-Path $Root 'autosync-OLD.ps1' }
if (-not (Test-Path $oldScript)) {
  $oldParent = ''
  foreach ($c in (Glines $Repo @('log', '--format=%H', '-25', '--', 'scripts/autosync.ps1'))) {
    $c = "$c".Trim(); if (-not $c) { continue }
    $body = (& git -C $Repo show "${c}:scripts/autosync.ps1" 2>$null) -join "`n"
    if ($body -notmatch 'PRESERVE FIRST') { $oldParent = $c; $body | Set-Content -Path $oldScript -Encoding utf8; break }
  }
  if (-not $oldParent) { "No pre-fix version of scripts/autosync.ps1 found in history." | Set-Content $oldScript -Encoding utf8 }
  $oldLen0 = if (Test-Path $oldScript) { (Get-Item $oldScript).Length } else { 0 }
  Check ($oldLen0 -gt 3000) "extracted pre-fix script from $oldParent ($oldLen0 bytes)"
} else {
  Check $true "using supplied pre-fix script $oldScript"
}

# ====================================================================================================
Head 'TEST 1 - OLD script, diverged clone: the defect'
$sb = New-Sandbox 't1-old-diverged'
New-Divergence $sb 'old'
$r = Run-Autosync $oldScript $sb
Write-Host "   exit code: $($r.Code)"
$r.Output
$s = Show-Status $sb
$remoteRefsOld = ((Glines $sb.Remote @('for-each-ref', '--format=%(refname)')) -join ' ')
Note "remote refs after run: $remoteRefsOld"
Check ($r.Code -eq 1) 'old script exits 1 (attention)'
Check ($remoteRefsOld -notmatch 'diverged') 'old script pushed NO side ref - nothing preserved'
Check ($s.Host.result -eq 'attention') 'old status records attention only'
Check ($s.Sync -eq $null) 'old script writes no monitor status file'

# ====================================================================================================
Head 'TEST 2 - NEW script, same divergence: preserve first'
$sb = New-Sandbox 't2-new-diverged'
New-Divergence $sb 'new'
$localSha = (Gline $sb.Clone @('rev-parse', 'HEAD'))
# Ask the REMOTE itself what master points at, before and after - the clone's origin/master ref is
# moved by the fetch, so it cannot prove the remote branch was left alone.
$remoteMasterBefore = (Gline $sb.Remote @('rev-parse', 'master'))
$newScript = Join-Path $Repo 'scripts\autosync.ps1'
$r = Run-Autosync $newScript $sb
Write-Host "   exit code: $($r.Code)"
$r.Output
$s = Show-Status $sb
$sideRefs = (Glines $sb.Remote @('for-each-ref', '--format=%(refname) %(objectname)'))
Note "remote refs after run:"
$sideRefs | ForEach-Object { Write-Host "   $_" }
$expectedRef = "refs/heads/diverged-$env:COMPUTERNAME-" + (Get-Date).ToUniversalTime().ToString('yyyyMMdd')
$sideMatch = $sideRefs | Where-Object { $_ -match [regex]::Escape($expectedRef) }
Check ($r.Code -eq 1) 'new script still exits 1 - divergence is reported, not hidden'
Check ([bool]$sideMatch) "side ref $expectedRef exists on the remote"
Check ($sideMatch -match [regex]::Escape($localSha)) 'the local commit is ON the remote under the side ref (byte-for-byte the same object)'
Check ($s.Sync.local_commits_preserved -eq $true) 'monitor status: local_commits_preserved = true'
Check ($s.Sync.ahead -eq 1 -and $s.Sync.behind -eq 1) 'monitor status: ahead/behind = 1/1'
Check ($s.Sync.preserved_ref -eq $expectedRef) 'monitor status carries the recovery ref'
Check ($s.Sync.result -eq 'attention') 'monitor status: result = attention'
Check ($s.Host.result -eq 'attention') 'per-host status still records attention (unchanged shape)'
Check ($s.Host.PSObject.Properties.Name -contains 'detail') 'per-host status still has result/detail/at fields consumers read'
Check ($s.Host.local_commits_preserved -eq $true) 'per-host status gained local_commits_preserved (added, nothing renamed)'
# the local commit is still checked out here too - nothing was lost locally either
Check (((Gline $sb.Clone @('rev-parse', 'HEAD'))) -eq $localSha) 'clone HEAD still holds the local commit'
# and the remote branch was left exactly where the other machine put it: no force, no reset
Check ((Gline $sb.Remote @('rev-parse', 'master')) -eq $remoteMasterBefore) 'origin/master was NOT rewritten on the remote (no force, no reset)'

# ====================================================================================================
Head 'TEST 2a - NEW script, AHEAD but fast-forwardable: plain push, no side ref invented'
$sb = New-Sandbox 't2a-new-ahead-only'
& git -C $sb.Clone commit -q --allow-empty -m 'local only, upstream has nothing new'
$r = Run-Autosync $newScript $sb
Write-Host "   exit code: $($r.Code)"
$r.Output
$s = Show-Status $sb
$refs2a = ((Glines $sb.Remote @('for-each-ref', '--format=%(refname)')))
Note "remote refs: $($refs2a -join ' ')"
Check ($r.Code -eq 0) 'ahead-but-ff is not treated as divergence (exit 0)'
Check ($refs2a -notmatch 'diverged') 'no diverged- ref created when the branch push succeeded'
Check ($s.Sync.local_commits_preserved -eq $false) 'monitor status: nothing reported as preserved'
Check ([string]::IsNullOrEmpty($s.Sync.preserved_ref)) 'monitor status names no recovery ref that does not exist'
Check (((Gline $sb.Remote @('rev-parse', 'master'))) -eq ((Gline $sb.Clone @('rev-parse', 'HEAD')))) 'the commit landed on origin/master'

# ====================================================================================================
Head 'TEST 3 - NEW script, clean clone behind origin: normal path unchanged'
$sb = New-Sandbox 't3-new-ff'
# origin moves ahead via a different machine; this clone is clean and merely behind
$seed = Join-Path $sb.Root 'seed'
Set-Content -Path (Join-Path $seed 'settings\base.yaml') -Encoding utf8 -Value @(
  '# upstream change that must arrive', 'agent-default-model:', '  provider: deepseek-official', '  model: deepseek-v4-pro')
& git -C $seed add -A | Out-Null
& git -C $seed commit -q -m 'upstream: model flip'
& git -C $seed push -q origin master | Out-Null
$before = (Gline $sb.Clone @('rev-parse', 'HEAD'))
$r = Run-Autosync $newScript $sb
Write-Host "   exit code: $($r.Code)"
$r.Output
$s = Show-Status $sb
$after = (Gline $sb.Clone @('rev-parse', 'HEAD'))
$dshSettings = Join-Path $sb.HomeDir '.dsh\settings.yaml'
Check ($r.Code -eq 0) 'clean behind clone still exits 0'
Check ($before -ne $after) 'HEAD fast-forwarded to origin/master'
Check (((Gline $sb.Clone @('rev-parse', 'origin/master'))) -eq $after) 'HEAD is exactly origin/master'
Check ($s.Sync.result -eq 'clean') 'monitor status: clean'
Check ($s.Sync.detail -match 'deepseek-v4-pro|settings.yaml|nothing to apply') 'monitor status carries the apply detail'
Check (Test-Path $dshSettings) 'sync.py applied into the sandboxed ~/.dsh (DSH_HOME honoured)'
if (Test-Path $dshSettings) { Note "applied settings.yaml:"; (Get-Content $dshSettings -Raw).Trim() | Write-Host }
Check ($r.Output -notmatch 'diverged') 'no divergence chatter on the normal path'

Head 'RESULT'
if ($script:Fail -eq 0) { Write-Host 'ALL CHECKS PASSED'; exit 0 } else { Write-Host "$script:Fail CHECK(S) FAILED"; exit 1 }
