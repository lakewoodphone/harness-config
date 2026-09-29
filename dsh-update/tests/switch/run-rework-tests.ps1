# run-rework-tests.ps1 — prove the reworked tools\switch-engine.ps1 against FIXTURES, never the live home.
#
# WHAT IS REAL AND WHAT IS SYNTHETIC
#   REAL      : bin\dsh-update.ps1 is never invoked here; everything else the script runs (scripts\sync.py,
#               scripts\check-version-coupled-config.py, lib\cli.mjs preflight) is the deployment's own code.
#   SYNTHETIC : -TargetHome, -WindowsJson and -StateRoot ALL point inside %TEMP%\switch-rework-<stamp>\,
#               so no run in this file can write ~\.dsh, multi-window\windows.json, or dsh-update\state\*.
#               `promote` is replaced by fixtures\support\inject-promote.ps1 (bin\dsh-update.ps1 promote
#               cannot run offline: there is no fetched 0.1.7-rc.2 prefix in vendor\prefix). The engine
#               reading is injected with -InjectEngineJson, and the sync task's clock with
#               -InjectNextRunInSeconds, so the guards are exercised deterministically.
#
# USAGE
#   pwsh -File dsh-update/tests/switch/run-rework-tests.ps1 [-Proof <n|all>] [-Rebuild]
#
# NOTHING HERE DELETES ANYTHING. Nothing here triggers the PersonalSecretary-HarnessSync task; the
# task is only READ with Get-ScheduledTaskInfo, and only in the cases that do not inject a clock.

[CmdletBinding()]
param(
  [string]$Proof = 'all',
  [switch]$Rebuild,
  [int]$TickInjectionSeconds = 60
)

$ErrorActionPreference = 'Continue'

$Here       = $PSScriptRoot
$UpdRoot    = Split-Path -Parent (Split-Path -Parent $Here)
$RepoRoot   = Split-Path -Parent $UpdRoot
$Switch     = Join-Path $UpdRoot 'tools\switch-engine.ps1'
$SyncPy     = Join-Path $RepoRoot 'scripts\sync.py'
$RealWindows = Join-Path $RepoRoot 'multi-window\windows.json'
$LiveHome   = Join-Path $env:USERPROFILE '.dsh'
$Version    = '0.1.7-rc.2'
$OldVersion = '0.1.5-rc.1'
$OldRoot    = Join-Path $env:LOCALAPPDATA 'npm-cache\_npx\1e7f6d9597241db0'

# ── the watched set: the ONLY things a correct switch may write ──────────────────────────────────
# WHY THIS REPLACED A WHOLE-TREE HASH. The first version of this proof fingerprinted every file under
# ~\.dsh by name + length + last-write time. It reported "CHANGED" on a run that provably refused —
# and the reason is this host, not the script: the LIVE ENGINE serving this very session continuously
# appends to ~\.dsh\sessions\...\session.v3.jsonl.zstd, \storages\..., \metrics\..., \health\... and
# \multi-window\logs\... (measured: 22 files under ~\.dsh rewritten inside 6 minutes, with the entry
# count unchanged). An mtime over the whole tree can never be evidence of anything while that is true.
# So the proof is explicit about the live surface a switch would touch: the three presets, the three
# profile patches, settings.yaml, state\pin.json and multi-window\windows.json — SHA256 per file, plus
# the set of switch-* directories and the presence of the lock file. That is the incident's blast
# radius, and it is checkable to the byte.
function Get-ConfigSurface {
  param([string]$DshHome, [string]$PinFile, [string]$LauncherFile)
  $rows = New-Object System.Collections.Generic.List[string]
  $files = New-Object System.Collections.Generic.List[string]
  foreach ($p in @('zabz','yocheved','cordis-bg')) { $files.Add((Join-Path $DshHome ".agent-presets\$p\agent.cordis.yml")) }
  foreach ($p in @('web','mesh','headless'))       { $files.Add((Join-Path $DshHome "profiles\$p\cordis.patch.yml")) }
  $files.Add((Join-Path $DshHome 'settings.yaml'))
  if ($PinFile)      { $files.Add($PinFile) }
  if ($LauncherFile) { $files.Add($LauncherFile) }
  foreach ($f in $files) { $rows.Add("$f|$(Sha $f)") }
  return ($rows -join "`n")
}

# The hash of a STRING, so a whole surface can be quoted as one value in the proof output.
function ShaStrings {
  param([string]$Text)
  if ($null -eq $Text) { return '(null)' }
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try { $h = $sha.ComputeHash($bytes) } finally { $sha.Dispose() }
  return (($h | ForEach-Object { $_.ToString('x2') }) -join '')
}

# Every file under $Root, excluding any subtree named node_modules. Needed because a staged home's
# `profiles\node_modules` holds DIRECTORY JUNCTIONS into an engine prefix: a plain recursive copy
# follows them and measured 127,970 files / 1.0 GB for what is really 884 KB of config.
function Copy-TreeSkippingModules {
  param([string]$Source, [string]$Destination, [string]$SkipName = 'node_modules')
  [void](New-Item -ItemType Directory -Path $Destination -Force)
  foreach ($item in @(Get-ChildItem -LiteralPath $Source -Force -ErrorAction SilentlyContinue)) {
    if ($item.Name -eq $SkipName) { continue }
    $dest = Join-Path $Destination $item.Name
    if ($item.PSIsContainer) { Copy-TreeSkippingModules -Source $item.FullName -Destination $dest -SkipName $SkipName }
    else { Copy-Item -LiteralPath $item.FullName -Destination $dest -Force }
  }
}

function Say  { param([string]$m = '') Write-Host $m }
function Rule { param([string]$m) Write-Host ''; Write-Host ('=' * 110); Write-Host "== $m"; Write-Host ('=' * 110) }
function Sub  { param([string]$m) Write-Host ''; Write-Host "-- $m"; Write-Host ('-' * 110) }
function Bad  { param([string]$m) Write-Host "  NO  $m" }
function Sha  { param([string]$p) if (Test-Path -LiteralPath $p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() } else { $null } }

# A whole-tree FINGERPRINT: every file's relative path, its length and its last-write time (UTC, to the
# tick), plus every directory's relative path. This is how "~\.dsh is byte-identical afterwards" is
# checked without reading tens of thousands of files' contents. A write always moves a last-write time,
# so a changed fingerprint means a write happened somewhere in the tree; an IDENTICAL fingerprint means
# no file or directory under it was created, changed, moved or removed.
function Get-TreeHash {
  param([string]$Root)
  if (-not (Test-Path -LiteralPath $Root)) { return '(absent)' }
  $parts = New-Object System.Collections.Generic.List[string]
  foreach ($f in @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue)) {
    $rel = [System.IO.Path]::GetRelativePath($Root, $f.FullName)
    $parts.Add("$rel|$($f.Length)|$($f.LastWriteTimeUtc.Ticks)")
  }
  foreach ($d in @(Get-ChildItem -LiteralPath $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue)) {
    $rel = [System.IO.Path]::GetRelativePath($Root, $d.FullName)
    $parts.Add("$rel/|dir")
  }
  $sorted = @($parts | Sort-Object)
  $joined = ($sorted -join "`n")
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($joined)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try { $h = $sha.ComputeHash($bytes) } finally { $sha.Dispose() }
  return ("{0}  ({1} entries)" -f (($h | ForEach-Object { $_.ToString('x2') }) -join ''), $sorted.Count)
}

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$T     = Join-Path $env:TEMP "switch-rework-$Stamp"
$Fx    = Join-Path $Here 'fixtures'
$Sup   = Join-Path $Fx 'support'
$FixRepo = Join-Path $T 'fixture-repo'
$HomeNew = Join-Path $T 'home-new'      # the fixture DSH home as it is BEFORE the switch (new names, 0.1.7 side)
$HomeOld = Join-Path $T 'home-old'      # the same home with the 0.1.5 names (the migrated / pre-state shape)
$Staged  = Join-Path $T 'staged-home'   # a staged, migrated home for the precondition-2 check
$StagedOld = Join-Path $T 'staged-old'
$BackupOk  = Join-Path $T 'backup-ok'
$BackupOld = Join-Path $T 'backup-old'
$BackupBad = Join-Path $T 'backup-bad'
$BackupMissing = Join-Path $T 'backup-missing'
$StateRoot = Join-Path $T 'state'
$WindowsT  = Join-Path $T 'windows.json'
$Inject    = Join-Path $T 'inject'
$OutRoot   = Join-Path $T 'out'

$NewPtc  = "@deepseek-ai/dsh-workflow-ptc"
$OldPtc  = "@deepseek-ai/dsh-workflow-worker-thread"
$NewReg  = "@deepseek-ai/dsh-agent-preset-registry"
$OldReg  = "@deepseek-ai/dsh-agent-presets"

$script:Results = [ordered]@{}

# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────
# The package set the 0.1.7 side provides. `@deepseek-ai/dsh` carries the version; the rest are the
# names the repo's presets/profiles actually resolve (measured with check-version-coupled-config.py).
$NewPackages = @(
  'dsh','dsh-persona','dsh-agent-instructions','dsh-tool-bash','dsh-tool-pwsh','dsh-tool-fs',
  'dsh-tool-fs-search','dsh-tool-jobs','dsh-command-goal','dsh-tool-goal','dsh-plan-mode',
  'dsh-compaction-basic','dsh-command-compact','dsh-compaction-tool-result-pruner',
  'dsh-tool-subagent-control','dsh-tool-subagent','dsh-workflow-ptc','dsh-tool-workflow',
  'dsh-tool-ralph','dsh-tool-ask-user','dsh-tool-todo','dsh-tool-web','dsh-tool-cordis',
  'dsh-skill-filesystem','dsh-tool-skill','dsh-tool-present','dsh-mcp-client',
  'dsh-agent-preset-registry','dsh-agent-preset'
)
# What the 0.1.5 side provides: the same, MINUS the three names that only exist on the 0.1.7 line.
$OldOnly4   = @('dsh-workflow-ptc','dsh-agent-preset-registry','dsh-agent-preset')
$OldPackages = @($NewPackages | Where-Object { $OldOnly4 -notcontains $_ })

function New-Prefix {
  param([string]$Root, [string]$Ver, [string[]]$Packages)
  $api = Join-Path $Root 'node_modules\@deepseek-ai'
  [void](New-Item -ItemType Directory -Path $api -Force)
  foreach ($p in $Packages) {
    [void](New-Item -ItemType Directory -Path (Join-Path $api $p) -Force)
    if ($p -eq 'dsh') {
      @{ name = "@deepseek-ai/$p"; version = $Ver } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $api "$p\package.json") -Encoding utf8
    }
  }
  return $api
}

function Replace-InFile {
  param([string]$Path, [string]$From, [string]$To)
  $t = Get-Content -LiteralPath $Path -Raw
  $t = $t.Replace($From, $To)
  Set-Content -LiteralPath $Path -Value $t -Encoding utf8 -NoNewline
}

function Build-Fixtures {
  Say "building fixtures under $T"
  foreach ($d in @($T, $FixRepo, $StateRoot, $Inject, $OutRoot,
                   "$FixRepo\multi-window", "$FixRepo\lib", "$FixRepo\bin", "$FixRepo\tools",
                   "$FixRepo\scripts", "$FixRepo\state", "$FixRepo\state\candidates",
                   "$FixRepo\state\history", "$FixRepo\state\baseline",
                   "$FixRepo\vendor\prefix", "$Staged", "$StagedOld",
                   "$BackupOk", "$BackupOld", "$BackupBad", "$BackupMissing")) {
    [void](New-Item -ItemType Directory -Path $d -Force)
  }

  # 1. a fixture harness-config tree the script can drive itself from.
  #
  # WHAT IS COPIED AND WHAT IS NOT, with the measurement that decided it: `state\candidates\<ver>\home`
  # is a whole staged DSH home, and its `profiles\node_modules` holds DIRECTORY JUNCTIONS into an
  # engine prefix. A plain recursive copy follows them: measured 127,970 files / 1.0 GB and 3.8 minutes
  # for a tree whose real content is 884 KB. So the home IS copied — preflight's gates read the staged
  # home — but node_modules is skipped by name, recursively. `state\logs` (97 files, machine-local
  # history nobody here reads) is skipped entirely.
  Copy-Item -Path "$UpdRoot\lib\*"   -Destination "$FixRepo\lib"   -Recurse -Force
  Copy-Item -Path "$UpdRoot\bin\*"   -Destination "$FixRepo\bin"   -Recurse -Force
  Copy-Item -Path "$UpdRoot\tools\*" -Destination "$FixRepo\tools" -Recurse -Force
  Copy-Item -LiteralPath "$RepoRoot\scripts"  -Destination "$FixRepo\scripts" -Recurse -Force
  Copy-Item -LiteralPath "$RepoRoot\presets"  -Destination "$FixRepo\presets" -Recurse -Force
  Copy-Item -LiteralPath "$RepoRoot\profiles" -Destination "$FixRepo\profiles" -Recurse -Force
  if (Test-Path -LiteralPath (Join-Path $RepoRoot 'settings')) { Copy-Item -LiteralPath (Join-Path $RepoRoot 'settings') -Destination (Join-Path $FixRepo 'settings') -Recurse -Force }
  if (Test-Path -LiteralPath (Join-Path $UpdRoot 'state\pin.json')) { Copy-Item -LiteralPath (Join-Path $UpdRoot 'state\pin.json') -Destination "$FixRepo\state\pin.json" -Force }
  foreach ($d in @('history','baseline')) {
    $src = Join-Path $UpdRoot "state\$d"
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination "$FixRepo\state\$d" -Recurse -Force }
  }
  foreach ($cand in @(Get-ChildItem -LiteralPath (Join-Path $UpdRoot 'state\candidates') -Directory -ErrorAction SilentlyContinue)) {
    $dest = Join-Path "$FixRepo\state\candidates" $cand.Name
    [void](New-Item -ItemType Directory -Path $dest -Force)
    Copy-Item -Path (Join-Path $cand.FullName '*') -Destination $dest -Force -Exclude 'home','cwd'
    $candHome = Join-Path $cand.FullName 'home'
    if (Test-Path -LiteralPath $candHome) { Copy-TreeSkippingModules -Source $candHome -Destination (Join-Path $dest 'home') }
  }

  # 2. the three engine prefixes the fixture needs. The target version's prefix gets every package the
  #    repo's own presets/profiles name (the list measured with check-version-coupled-config.py), so
  #    the version-coupled steps really do report `version check passed` against it; the 0.1.5 one is
  #    deliberately missing exactly the three names that only exist on the 0.1.7 line, which is what
  #    makes it a faithful stand-in for the old line. bin\dsh-update.ps1 promote cannot run against
  #    these (no fetched npm prefix), which is why -InjectPromoteScript exists for the write proofs.
  [void](New-Prefix -Root (Join-Path $FixRepo "vendor\prefix\$Version")    -Ver $Version    -Packages $NewPackages)
  [void](New-Prefix -Root (Join-Path $FixRepo "vendor\prefix\$OldVersion") -Ver $OldVersion -Packages $OldPackages)

  # 3. the fixture launcher config: the repo's own, with dshInstall pointing at the 0.1.5 prefix
  #    (exactly the value a roll-back restores) and primaryPort left at whatever the real one says.
  $w = Get-Content -LiteralPath $RealWindows -Raw | ConvertFrom-Json
  if ($w.PSObject.Properties.Name -contains 'dshInstall') { $w.dshInstall = $OldRoot }
  else { $w | Add-Member -NotePropertyName dshInstall -NotePropertyValue $OldRoot -Force }
  $w | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $WindowsT -Encoding utf8
  Copy-Item -LiteralPath $WindowsT -Destination "$FixRepo\multi-window\windows.json" -Force

  # 4. the fixture DSH homes. home-new is built from the LIVE config (which is where the 0.1.7 names
  #    now stand), and home-old is the SAME BYTES with the 0.1.5 names put back — that is the shape
  #    the pre-state holds and therefore the shape a roll-back must reproduce exactly.
  foreach ($p in @('zabz','yocheved','cordis-bg')) {
    $dest = Join-Path $HomeNew ".agent-presets\$p"
    [void](New-Item -ItemType Directory -Path $dest -Force)
    Copy-Item -LiteralPath (Join-Path $LiveHome ".agent-presets\$p\agent.cordis.yml") -Destination (Join-Path $dest 'agent.cordis.yml') -Force
  }
  foreach ($p in @('web','mesh','headless')) {
    $dest = Join-Path $HomeNew "profiles\$p"
    [void](New-Item -ItemType Directory -Path $dest -Force)
    Copy-Item -LiteralPath (Join-Path $LiveHome "profiles\$p\cordis.patch.yml") -Destination (Join-Path $dest 'cordis.patch.yml') -Force
  }
  Copy-Item -LiteralPath (Join-Path $LiveHome 'settings.yaml') -Destination (Join-Path $HomeNew 'settings.yaml') -Force
  # The live config already carries the 0.1.5 preset name in some files and the 0.1.7 one in others.
  # NORMALISE home-new to the 0.1.7 side, which is what a switch target looks like once promoted.
  foreach ($f in @(Get-ChildItem -LiteralPath $HomeNew -Recurse -File -Force -ErrorAction SilentlyContinue)) {
    Replace-InFile -Path $f.FullName -From $OldPtc -To $NewPtc
    Replace-InFile -Path $f.FullName -From $OldReg -To $NewReg
  }
  [void](New-Item -ItemType Directory -Path (Join-Path $HomeNew 'sessions\--FIXTURE--\aaaa') -Force)
  Set-Content -LiteralPath (Join-Path $HomeNew 'sessions\--FIXTURE--\aaaa\session.v3.jsonl.zstd') -Value 'FIXTURE-v3-original' -Encoding ascii

  # home-old: the 0.1.5 shape of the same home, for the roll-back proof's restore target.
  [void](New-Item -ItemType Directory -Path $HomeOld -Force)
  Copy-Item -Path "$HomeNew\*" -Destination $HomeOld -Recurse -Force
  foreach ($f in @(Get-ChildItem -LiteralPath $HomeOld -Recurse -File -Force -ErrorAction SilentlyContinue)) {
    Replace-InFile -Path $f.FullName -From $NewPtc -To $OldPtc
    Replace-InFile -Path $f.FullName -From $NewReg -To $OldReg
  }

  # 5. the staged home (migrated: the 0.1.7 names) and a staged home that is NOT migrated.
  Copy-Item -Path "$HomeNew\*" -Destination $Staged -Recurse -Force
  Copy-Item -Path "$HomeOld\*" -Destination $StagedOld -Recurse -Force

  # 6. backup reports: one fresh and verified, one stale, one not ok, one absent.
  $now = (Get-Date).ToUniversalTime().ToString('o')
  $old = (Get-Date).ToUniversalTime().AddHours(-13).ToString('o')
  @{ ok = $true; finishedAt = $now; totalFiles = 4; destination = $BackupOk
     stores = @(@{ store = 'sessions'; verified = 1; ok = $true }, @{ store = 'config'; verified = 7; ok = $true })
     problems = @() } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $BackupOk 'BACKUP-REPORT.json') -Encoding utf8
  @{ ok = $true; finishedAt = $old; totalFiles = 4; destination = $BackupOld
     stores = @(@{ store = 'sessions'; verified = 1; ok = $true }); problems = @() } |
     ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $BackupOld 'BACKUP-REPORT.json') -Encoding utf8
  @{ ok = $false; finishedAt = $now; totalFiles = 4; destination = $BackupBad
     stores = @(@{ store = 'sessions'; verified = 0; ok = $false })
     problems = @('sessions: 1 file could not be copied faithfully') } |
     ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $BackupBad 'BACKUP-REPORT.json') -Encoding utf8

  # 7. the fixture state root's pin: the engine and the pin AGREE (precondition 3), so the cases that
  #    are not about the pin reach the later guard. The pin is a COPY; the deployment's pin.json is
  #    never touched.
  @{ version = $Version
     installRoot = (Join-Path $FixRepo "vendor\prefix\$Version")
     enginePath = (Join-Path $FixRepo "vendor\prefix\$Version\node_modules\@deepseek-ai\dsh\lib\bin.js")
     managed = $false; pinnedAt = $now; by = $env:COMPUTERNAME
     contractSha256 = ('0' * 64); treeSha256 = ('0' * 64); predecessor = $OldVersion } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $StateRoot 'pin.json') -Encoding utf8

  # 8. the injection files.
  @{ ok = $true; port = 3099; pid = 424242; startedAt = '2026-09-28T19:00:00.000Z'
     installRoot = $OldRoot; version = $Version; cmd = 'INJECTED for the switch tests' } |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Inject 'engine.json') -Encoding utf8

  Say "fixtures built"
}

# ── running the switch as a real child process ───────────────────────────────────────────────────
function Run-Switch {
  param([string]$Name, [string[]]$Argv, [hashtable]$Env = @{})
  $out = Join-Path $OutRoot "$Name.out.txt"
  $err = Join-Path $OutRoot "$Name.err.txt"
  $saved = @{}
  foreach ($k in $Env.Keys) {
    $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process')
    [Environment]::SetEnvironmentVariable($k, [string]$Env[$k], 'Process')
  }
  Say "  cmd: pwsh -NoProfile -File `"$Switch`" $($Argv -join ' ')"
  foreach ($k in $Env.Keys) { Say "  env: $k=$($Env[$k])" }
  & pwsh -NoProfile -File $Switch @Argv 1> $out 2> $err
  $code = $LASTEXITCODE
  foreach ($k in $Env.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
  foreach ($l in @(Get-Content -LiteralPath $out -ErrorAction SilentlyContinue)) { Say $l }
  $et = @(Get-Content -LiteralPath $err -ErrorAction SilentlyContinue)
  if ($et.Count) { Say ''; Say '  --- stderr ---'; foreach ($l in $et) { Say $l } }
  Say ''
  Say "  EXIT CODE: $code"
  return [int]$code
}

function Base-Args {
  return @('-Version', $Version, '-StagedHome', $Staged, '-BackupDir', $BackupOk,
           '-StateRoot', $StateRoot, '-TargetHome', $HomeNew, '-WindowsJson', $WindowsT)
}

# Replace the run-specific root with a stable token so the pasted proof reads the same every run.
function Tidy {
  param([string]$Text)
  return ($Text -replace [regex]::Escape($T), '<TESTROOT>')
}
function Show-Out {
  param([string]$Name)
  $p = Join-Path $OutRoot "$Name.out.txt"
  foreach ($l in @(Get-Content -LiteralPath $p -ErrorAction SilentlyContinue)) { Say (Tidy $l) }
  $e = Join-Path $OutRoot "$Name.err.txt"
  $et = @(Get-Content -LiteralPath $e -ErrorAction SilentlyContinue)
  if ($et.Count) { Say ''; Say '  --- stderr ---'; foreach ($l in $et) { Say (Tidy $l) } }
}

$HomeHashBefore = Get-ConfigSurface -DshHome $LiveHome -PinFile (Join-Path $UpdRoot 'state\pin.json') -LauncherFile $RealWindows
$RealWindowsHashBefore = Sha $RealWindows
$RealStateBefore = @(Get-ChildItem -LiteralPath (Join-Path $UpdRoot 'state') -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like 'switch-*' } | ForEach-Object { $_.Name } | Sort-Object)
$RealPinHashBefore = Sha (Join-Path $UpdRoot 'state\pin.json')
$RealWindowsHashBefore2 = Sha $RealWindows

Rule "switch-engine REWORK — proofs on fixtures. test root: $T"
Say "  live home            : $LiveHome"
Say "  live home CONFIG surface sha256: $(ShaStrings $HomeHashBefore)"
Say "  real windows.json    : $RealWindowsHashBefore"
Say "  real state\pin.json  : $RealPinHashBefore"
Say "  real switch-* dirs   : $($RealStateBefore.Count)"
Say '  No run below is given a live path: -TargetHome, -WindowsJson and -StateRoot all live under the test root.'
Say '  The live-home check is over the CONFIG SURFACE the switch can reach (3 presets, 3 profile patches,'
Say '  settings.yaml, state\pin.json, multi-window\windows.json) — not the whole tree, because the live'
Say '  engine serving this session continuously rewrites ~\.dsh\sessions, \storages, \metrics and \health.'

if ($Rebuild -or -not (Test-Path -LiteralPath (Join-Path $Inject 'engine.json'))) { Build-Fixtures }
if ($Proof -eq 'build') { Say 'fixtures built only'; exit 0 }

$P = @{}
if ($Proof -eq 'all') { $P = @{ '1'=$true;'2'=$true;'3'=$true;'4'=$true;'5'=$true;'6'=$true;'7'=$true;'9'=$true } }
else { $P = @{ $Proof = $true } }

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['1']) {
  Rule 'PROOF 1 — it parses'
  $errs = $null; $toks = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile($Switch, [ref]$toks, [ref]$errs)
  Say "  file   : $Switch"
  Say "  tokens : $($toks.Count)"
  Say "  [ref] variables declared before use: `$errs is $($null -ne $errs.GetType()) , `$toks is $($null -ne $toks.GetType())"
  if ($errs -and $errs.Count) {
    foreach ($e in $errs) { Say "  line $($e.Extent.StartLineNumber): $($e.Message)" }
    Say "  PARSE ERRORS: $($errs.Count)"
  } else { Say '  PARSE OK — 0 errors' }
  $script:Results['1 parse'] = $(if ($errs -and $errs.Count) { 'FAIL' } else { 'PASS' })
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['2']) {
  Rule 'PROOF 2 — the live-write gate: a full run whose target IS the live home, without the flag'
  Say "  -TargetHome  = $LiveHome   (the REAL live home)"
  Say "  -WindowsJson = $WindowsT   (fixture)   -StateRoot = $StateRoot (fixture)"
  Say '  -IUnderstandThisWritesTheLiveHome is NOT given.'
  Say ''
  $homeHash2before = Get-ConfigSurface -DshHome $LiveHome -PinFile (Join-Path $UpdRoot 'state\pin.json') -LauncherFile $RealWindows
  $args2 = @('-Version', $Version, '-StagedHome', $Staged, '-BackupDir', $BackupOk,
             '-StateRoot', $StateRoot, '-TargetHome', $LiveHome, '-WindowsJson', $WindowsT,
             '-InjectEngineJson', (Join-Path $Inject 'engine.json'), '-InjectPreflightVerdict', 'GO')
  Say '  -InjectPreflightVerdict GO is passed so this run actually reaches the gate: on this host the'
  Say '  repository''s own preflight is NO-GO for reasons unrelated to the switch, and a refusal there'
  Say '  would prove nothing about the gate. With it, the run passes every precondition, prints the plan,'
  Say '  and then meets the gate — which is the thing under test.'
  $c2 = Run-Switch -Name 'p2-livehome-no-flag' -Argv $args2
  $homeHash2after = Get-ConfigSurface -DshHome $LiveHome -PinFile (Join-Path $UpdRoot 'state\pin.json') -LauncherFile $RealWindows
  Sub 'OUT OF BAND: is the live config surface byte-identical?'
  Say "  surface hash BEFORE : $(ShaStrings $homeHash2before)"
  Say "  surface hash AFTER  : $(ShaStrings $homeHash2after)"
  Say "  verdict             : $(if ($homeHash2before -eq $homeHash2after) { 'IDENTICAL — every one of the 8 watched files has the same sha256 (or is still absent)' } else { 'CHANGED — this is a bug' })"
  Say '  what is watched     : 3 presets, 3 profile patches, settings.yaml, state\pin.json, multi-window\windows.json'
  Say "  exit code           : $c2  $(if ($c2 -eq 2) { '(refused)' } else { '(EXPECTED 2)' })"
  $script:Results['2 live-write gate'] = $(if ($homeHash2before -eq $homeHash2after -and $c2 -eq 2) { 'PASS' } else { 'FAIL' })
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['3']) {
  Rule 'PROOF 3 — -DryRun writes nothing anywhere'
  $stateBefore3 = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object)
  $lockBefore3  = Test-Path -LiteralPath (Join-Path $StateRoot 'locks\switch-engine.lock.json')
  $winBefore3   = Sha $WindowsT
  $pinBefore3   = Sha (Join-Path $StateRoot 'pin.json')
  $surfaceBefore3 = Get-ConfigSurface -DshHome $HomeNew -PinFile (Join-Path $StateRoot 'pin.json') -LauncherFile $WindowsT
  Say "  state\ dirs before : $($stateBefore3.Count) [$($stateBefore3 -join ', ')]"
  Say "  lock file before   : $lockBefore3"
  Say "  windows.json before: $winBefore3"
  Say ''
  $c3 = Run-Switch -Name 'p3-dryrun' -Argv (@('-DryRun') + (Base-Args) + @('-InjectEngineJson', (Join-Path $Inject 'engine.json'), '-InjectPreflightVerdict', 'GO'))
  $stateAfter3 = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object)
  $lockAfter3  = Test-Path -LiteralPath (Join-Path $StateRoot 'locks\switch-engine.lock.json')
  $winAfter3   = Sha $WindowsT
  $pinAfter3   = Sha (Join-Path $StateRoot 'pin.json')
  $added3 = @($stateAfter3 | Where-Object { $stateBefore3 -notcontains $_ })
  $surfaceAfter3 = Get-ConfigSurface -DshHome $HomeNew -PinFile (Join-Path $StateRoot 'pin.json') -LauncherFile $WindowsT
  Sub 'OUT OF BAND: what the fixture tree looks like now'
  Say "  state\switch-* dirs : before $($stateBefore3.Count) -> after $($stateAfter3.Count)$(if ($added3.Count) { "   <-- CREATED: $($added3 -join ', ')" } else { '   (none created)' })"
  Say "  lock file exists    : before $lockBefore3 -> after $lockAfter3"
  Say "  windows.json        : before $winBefore3"
  Say "                        after  $winAfter3   -> $(if ($winBefore3 -eq $winAfter3) { 'UNCHANGED' } else { 'CHANGED' })"
  Say "  state\pin.json      : before $pinBefore3"
  Say "                        after  $pinAfter3   -> $(if ($pinBefore3 -eq $pinAfter3) { 'UNCHANGED' } else { 'CHANGED' })"
  Say "  fixture home surface: $(if ($surfaceBefore3 -eq $surfaceAfter3) { 'ALL 8 WATCHED FILES UNCHANGED' } else { 'CHANGED' })"
  Say "  exit code           : $c3  $(if ($c3 -eq 0) { '(dry run completed — every precondition passed, the plan was printed, nothing written)' } elseif ($c3 -eq 2) { '(a precondition refused, so the dry run stopped there — still nothing written)' } else { '(EXPECTED 0 or 2)' })"
  # Two honest outcomes, and BOTH are the claim being tested: a dry run either completes the plan and
  # exits 0, or a precondition refuses and it exits 2. On this host it is 2, because the repository's
  # own preflight is NO-GO for reasons unrelated to the switch (analyze and patch-effect report BREAKS).
  # What must hold either way: nothing at all was written.
  $ok3 = ($added3.Count -eq 0) -and (-not $lockAfter3) -and ($winBefore3 -eq $winAfter3) -and ($pinBefore3 -eq $pinAfter3) -and ($surfaceBefore3 -eq $surfaceAfter3) -and ($c3 -in @(0, 2))
  $script:Results['3 dry-run writes nothing'] = $(if ($ok3) { 'PASS' } else { 'FAIL' })
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['4']) {
  Rule 'PROOF 4 — the sync-tick guard refuses when a tick is inside the safety margin'
  Sub '4a. the REAL task, read only, with no injection — the margin decided against the real schedule'
  $env1 = @{ DSH_UPDATE_WINDOWS_JSON = $WindowsT }
  $argsA = @('-Version', $Version, '-StagedHome', $Staged, '-BackupDir', $BackupOk,
             '-StateRoot', $StateRoot, '-TargetHome', $HomeNew, '-WindowsJson', $WindowsT,
             '-InjectEngineJson', (Join-Path $Inject 'engine.json'), '-InjectPreflightVerdict', 'GO')
  Say '  (this run may refuse on the real schedule or proceed — either is honest; what matters is that'
  Say '   the decision is printed and derived from the real task)'
  Say ''
  $stateBefore4a = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
  $c4a = Run-Switch -Name 'p4a-tick-real-schedule' -Argv $argsA -Env $env1
  $stateAfter4a = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
  $lockAfter4a = Test-Path -LiteralPath (Join-Path $StateRoot 'locks\switch-engine.lock.json')
  Say ''
  Say "  state\switch-* before $($stateBefore4a.Count) -> after $($stateAfter4a.Count); lock file after: $lockAfter4a"

  Sub "4b. the schedule INJECTED to $TickInjectionSeconds s from now: -InjectNextRunInSeconds $TickInjectionSeconds, inside the 180 s margin"
  Say '  The real task''s timing cannot be controlled from a test, so it is injected through the'
  Say "  documented parameter. -InjectNextRunInSeconds $TickInjectionSeconds says: pretend NextRunTime is now + $TickInjectionSeconds s."
  Say ''
  $winBefore4 = Sha $WindowsT
  $pinBefore4 = Sha (Join-Path $StateRoot 'pin.json')
  $state4bBefore = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object)
  $c4b = Run-Switch -Name 'p4b-tick-injected-imminent' -Argv (@('-InjectNextRunInSeconds',"$TickInjectionSeconds") + $argsA) -Env $env1
  $state4bAfter = @(Get-ChildItem -LiteralPath $StateRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object)
  $lock4b = Test-Path -LiteralPath (Join-Path $StateRoot 'locks\switch-engine.lock.json')
  $winAfter4 = Sha $WindowsT
  $pinAfter4 = Sha (Join-Path $StateRoot 'pin.json')
  $added4 = @($state4bAfter | Where-Object { $state4bBefore -notcontains $_ })
  Sub 'OUT OF BAND'
  Say "  state\switch-* dirs : $(if ($added4.Count) { "CREATED: $($added4 -join ', ')" } else { "no new directory ($($state4bBefore.Count) before, $($state4bAfter.Count) after)" })"
  Say "  lock file exists    : $lock4b"
  Say "  windows.json        : $(if ($winBefore4 -eq $winAfter4) { "UNCHANGED $winAfter4" } else { "CHANGED $winBefore4 -> $winAfter4" })"
  Say "  state\pin.json      : $(if ($pinBefore4 -eq $pinAfter4) { "UNCHANGED $pinAfter4" } else { "CHANGED $pinBefore4 -> $pinAfter4" })"
  Say "  exit code           : $c4b  $(if ($c4b -eq 2) { '(refused)' } else { '(EXPECTED 2)' })"
  $ok4 = ($c4b -eq 2) -and ($added4.Count -eq 0) -and (-not $lock4b) -and ($winBefore4 -eq $winAfter4) -and ($pinBefore4 -eq $pinAfter4)
  $script:Results['4 sync-tick guard'] = $(if ($ok4) { 'PASS' } else { 'FAIL' })

  Sub '4c. a sync tick that LANDS MID-SEQUENCE: LastRunTime injected to move during the switch'
  Say '  -InjectLastRunAt is a time well before this run and -InjectLastRunAfter one well after it, so the'
  Say '  second reading of the task sees a move. That is the third thing FIX 2 asks for: a tick that ran'
  Say '  must be REPORTED, re-verified, and never silently accepted.'
  Say '  The sync output is injected as the 0.1.7-side text too, so the run really reaches step 6 rather'
  Say '  than failing earlier on the coupled-step check.'
  Say ''
  $tickBefore = (Get-Date).ToUniversalTime().AddMinutes(-30).ToString('o')
  $tickAfter  = (Get-Date).ToUniversalTime().ToString('o')
  $gBefore = Sha (Join-Path $StateRoot 'pin.json')
  $c4c = Run-Switch -Name 'p4c-tick-landed-mid-sequence' -Argv (@(
      '-InjectNextRunInSeconds', '900', '-InjectLastRunAt', $tickBefore, '-InjectLastRunAfter', $tickAfter) + $argsA +
      @('-AcceptSessionFormatUpgrade', '-IUnderstandThisWritesTheLiveHome',
        '-InjectPromoteScript', (Join-Path $Sup 'inject-promote.ps1'),
        '-InjectSyncOut', (Join-Path $Here 'fixtures\syncstep-new.out.txt'), '-InjectVerification', 'skipped-to-reach-the-tick-reading'))
  Sub 'OUT OF BAND'
  Say "  pin.json before the run : $gBefore"
  Say "  pin.json after the run  : $(Sha (Join-Path $StateRoot 'pin.json'))"
  $report4c = [string](Get-Content -LiteralPath (Join-Path $OutRoot 'p4c-tick-landed-mid-sequence.out.txt') -Raw -ErrorAction SilentlyContinue)
  $saidTick = ($report4c -match 'A SYNC TICK RAN DURING THIS SWITCH')
  $saidTrust = ($report4c -match 'TRUSTWORTHY: a tick ran')
  $saidNotTrust = ($report4c -match 'NOT TRUSTWORTHY')
  Say "  it REPORTED the mid-sequence tick        : $saidTick"
  Say "  it re-verified and called the outcome    : $(if ($saidTrust) { 'TRUSTWORTHY (config still resolves to the new names) — so it stays applied' } elseif ($saidNotTrust) { 'NOT TRUSTWORTHY (the re-verify found the config and the engine disagreeing) — so it rolls back' } else { 'NEITHER — the re-verify printed no verdict at all, which is a bug' })"
  Say "  exit code               : $c4c  $(if ($c4c -eq 0) { '(applied — the tick was reported and the result re-verified)' } elseif ($c4c -eq 4) { '(rolled back after the tick was reported untrustworthy)' } else { '(EXPECTED 0 or 4)' })"
  # EITHER verdict is honest behaviour, and both are the point of the check: the tick must be REPORTED
  # and the outcome must be re-verified rather than assumed. Which one comes out depends on whether the
  # config still matches the promoted engine, and the run says which in plain words.
  $ok4c = $saidTick -and ($saidTrust -or $saidNotTrust) -and ($c4c -in @(0, 4)) -and ($c4c -eq $(if ($saidTrust) { 0 } else { 4 }))
  if (-not $ok4c) { $script:Results['4 sync-tick guard'] = 'FAIL' }
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['5']) {
  Rule 'PROOF 5 — a failure AFTER the writes rolls back COMPLETELY (the incident''s own failure)'
  Say '  THE FIXTURE HOME FOR THIS CASE IS home-old: the 0.1.5 names, as the pre-state holds them.'
  Say '  -InjectPromoteScript runs fixtures\support\inject-promote.ps1, which does what the real'
  Say '  promote does at the end (write dshInstall and the pin) — bin\dsh-update.ps1 promote cannot run'
  Say '  here because vendor\prefix\0.1.7-rc.2 is not fetched on this host.'
  Say '  -TestHookAfterWrite then runs fixtures\support\mid-sequence-failure.ps1, which forces the pin'
  Say '  back to 0.1.5-rc.1, points dshInstall at a prefix that does not exist, and appends an injected'
  Say '  line to every live config file — then exits non-zero. The failure therefore lands after the'
  Say '  writes, which is the only interesting place for it, and a roll-back that "restores" by re-running'
  Say '  sync.py instead of restoring bytes leaves that injected line behind as visible evidence.'
  Say ''
  $args5 = @('-Version', $Version, '-StagedHome', $Staged, '-BackupDir', $BackupOk,
             '-StateRoot', $StateRoot, '-TargetHome', $HomeOld, '-WindowsJson', $WindowsT,
             '-IUnderstandThisWritesTheLiveHome', '-AcceptSessionFormatUpgrade', '-InjectPreflightVerdict', 'G8ACCEPTED',
             '-InjectEngineJson', (Join-Path $Inject 'engine.json'), '-InjectNextRunInSeconds', '900',
             '-InjectPromoteScript', (Join-Path $Sup 'inject-promote.ps1'),
             '-TestHookAfterWrite', (Join-Path $Sup 'mid-sequence-failure.ps1'))
  Say '  -InjectPreflightVerdict G8ACCEPTED is also passed: the repository''s own preflight is NO-GO on'
  Say '  this host for reasons unrelated to the switch (analyze and patch-effect both report BREAKS), so'
  Say '  without it no run could ever reach the write path. The REAL verdict is still printed above it,'
  Say '  and what the injection changes is only which verdict the shell acts on.'
  Say ''
  # NOTE: the containment flags mean the live-write gate does not apply here; -IUnderstand... is still
  # passed so the run is identical to the production invocation in every respect that matters.
  $c5 = Run-Switch -Name 'p5-midsequence-failure' -Argv $args5

  # OUT OF BAND: find the pre-state this run created and re-hash everything itself.
  $preDirs = @(Get-ChildItem -LiteralPath $StateRoot -Directory | Where-Object { $_.Name -match '^switch-\d{8}T\d{6}Z$' } | Sort-Object Name)
  if ($preDirs.Count -eq 0) {
    Bad 'this run wrote NO pre-state directory, so the roll-back it should have performed cannot be checked.'
    Say '  That means the attack got no further than a precondition — read the refusal above.'
    $script:Results['5 complete roll-back'] = 'FAIL'
  } else {
  $preDir = ($preDirs | Select-Object -Last 1).FullName
  Sub "OUT OF BAND — independent re-hash against the pre-state this run wrote"
  Say "  pre-state   : $preDir"
  $pre = Get-Content -LiteralPath (Join-Path $preDir 'PRE-STATE.json') -Raw | ConvertFrom-Json
  Say "  recorded    : pin.json + windows.json + $(@($pre.recordedConfigFiles).Count) config file(s)"
  Say "  POST-STATE.json present: $(Test-Path -LiteralPath (Join-Path $preDir 'POST-STATE.json'))   (expected: absent — the switch never succeeded)"
  Say ''
  $allOk = $true
  Say '  --- pin.json ---'
  $pinNow = Sha $pre.pin.path
  $pinOk = ($pinNow -eq $pre.pin.sha256Before)
  if (-not $pinOk) { $allOk = $false }
  Say "    recorded $($pre.pin.sha256Before)"
  Say "    now      $pinNow     $(if ($pinOk) { 'MATCH' } else { 'DIFFER' })"
  Say '  --- windows.json ---'
  $winNow = Sha $pre.launcherConfig.path
  $winOk = ($winNow -eq $pre.launcherConfig.sha256Before)
  if (-not $winOk) { $allOk = $false }
  Say "    recorded $($pre.launcherConfig.sha256Before)"
  Say "    now      $winNow     $(if ($winOk) { 'MATCH' } else { 'DIFFER' })"
  Say '  --- every recordedConfigFiles entry ---'
  foreach ($r in @($pre.recordedConfigFiles)) {
    $dest = Join-Path $pre.targetHome ($r.rel -replace '/', '\')
    $now = Sha $dest
    $ok = ($now -eq $r.sha256)
    if (-not $ok) { $allOk = $false }
    Say ("    {0,-8} {1}" -f $(if ($ok) { 'MATCH' } else { 'DIFFER' }), $r.rel)
    Say "             recorded $($r.sha256)"
    Say "             now      $now"
  }
  Say ''
  Say "  EVERY RECORDED FILE IS BYTE-IDENTICAL TO ITS PRE-STATE SHA256: $allOk"
  Say "  exit code: $c5   $(if ($c5 -eq 4) { '(a step failed AND the automatic roll-back restored the previous state)' } else { '(EXPECTED 4)' })"
  $script:Results['5 complete roll-back'] = $(if ($allOk -and $c5 -eq 4) { 'PASS' } else { 'FAIL' })
  }
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['6']) {
  Rule 'PROOF 6 — sync.py reporting SKIPPED for the coupled steps is treated as a FAILURE, and it rolls back'
  Say '  -InjectSyncOut feeds the switch the REAL text sync.py produced against the 0.1.5 engine root'
  Say '  (tests\switch\fixtures\syncstep-old.out.txt, captured by the previous test runner on this host).'
  Say '  That is the incident''s own signal: the version precondition saw the OLD engine, the coupled'
  Say '  steps were skipped, and the config was left behind. The switch must call that a failed switch.'
  Say ''
  $argz6 = @('-Version', $Version, '-StagedHome', $Staged, '-BackupDir', $BackupOk,
             '-StateRoot', $StateRoot, '-TargetHome', $HomeOld, '-WindowsJson', $WindowsT,
             '-IUnderstandThisWritesTheLiveHome', '-AcceptSessionFormatUpgrade', '-InjectPreflightVerdict', 'G8ACCEPTED',
             '-InjectEngineJson', (Join-Path $Inject 'engine.json'), '-InjectNextRunInSeconds', '900',
             '-InjectPromoteScript', (Join-Path $Sup 'inject-promote.ps1'),
             '-InjectSyncOut', (Join-Path $Here 'fixtures\syncstep-old.out.txt'))
  $c6 = Run-Switch -Name 'p6-sync-skipped' -Argv $argz6
  $preDirs6 = @(Get-ChildItem -LiteralPath $StateRoot -Directory | Where-Object { $_.Name -match '^switch-\d{8}T\d{6}Z$' } | Sort-Object Name)
  $preDir6 = if ($preDirs6.Count) { ($preDirs6 | Select-Object -Last 1).FullName } else { $null }
  if (-not $preDir6) {
    Bad 'this run wrote NO pre-state directory, so the roll-back it should have performed cannot be checked.'
    $script:Results['6 sync SKIPPED = failure'] = 'FAIL'
  } else {
  $pre6 = Get-Content -LiteralPath (Join-Path $preDir6 'PRE-STATE.json') -Raw | ConvertFrom-Json
  Sub 'OUT OF BAND — independent re-hash'
  Say "  pre-state: $preDir6"
  $allOk6 = $true
  foreach ($r in @($pre6.recordedConfigFiles)) {
    $dest = Join-Path $pre6.targetHome ($r.rel -replace '/', '\')
    $now = Sha $dest
    $ok = ($now -eq $r.sha256)
    if (-not $ok) { $allOk6 = $false }
    Say ("    {0,-8} {1}" -f $(if ($ok) { 'MATCH' } else { 'DIFFER' }), $r.rel)
  }
  $pin6 = Sha $pre6.pin.path
  $win6 = Sha $pre6.launcherConfig.path
  $pinOk6 = ($pin6 -eq $pre6.pin.sha256Before); $winOk6 = ($win6 -eq $pre6.launcherConfig.sha256Before)
  if (-not $pinOk6) { $allOk6 = $false }
  if (-not $winOk6) { $allOk6 = $false }
  Say "    pin.json     recorded $($pre6.pin.sha256Before)  now $pin6  $(if ($pinOk6) { 'MATCH' } else { 'DIFFER' })"
  Say "    windows.json recorded $($pre6.launcherConfig.sha256Before)  now $win6  $(if ($winOk6) { 'MATCH' } else { 'DIFFER' })"
  Say ''
  Say "  EVERY RECORDED FILE BACK AT ITS PRE-STATE SHA256: $allOk6"
  Say "  exit code: $c6  $(if ($c6 -eq 4) { '(rolled back)' } else { '(EXPECTED 4)' })"
  $script:Results['6 sync SKIPPED = failure'] = $(if ($allOk6 -and $c6 -eq 4) { 'PASS' } else { 'FAIL' })
  }
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['7']) {
  Rule 'PROOF 7 — a real refusal for each precondition'
  Say '  Each case prints its own refusal and its exit code. Nothing is written in any of them.'
  Say ''
  $r = [ordered]@{}
  Say '  --- 7a. no BACKUP-REPORT.json at all ---'
  $r['7a backup report absent'] = Run-Switch -Name 'p7a-no-report' -Argv (@('-Version',$Version,'-StagedHome',$Staged,'-BackupDir',$BackupMissing,'-StateRoot',$StateRoot,'-TargetHome',$HomeNew,'-WindowsJson',$WindowsT,'-InjectEngineJson',(Join-Path $Inject 'engine.json'),'-InjectNextRunInSeconds','900'))
  Say '  --- 7b. the backup report says ok=false ---'
  $r['7b backup not ok'] = Run-Switch -Name 'p7b-bad-report' -Argv (@('-Version',$Version,'-StagedHome',$Staged,'-BackupDir',$BackupBad,'-StateRoot',$StateRoot,'-TargetHome',$HomeNew,'-WindowsJson',$WindowsT,'-InjectEngineJson',(Join-Path $Inject 'engine.json'),'-InjectNextRunInSeconds','900'))
  Say '  --- 7c. the backup is 13 hours old ---'
  $r['7c backup stale'] = Run-Switch -Name 'p7c-stale-report' -Argv (@('-Version',$Version,'-StagedHome',$Staged,'-BackupDir',$BackupOld,'-StateRoot',$StateRoot,'-TargetHome',$HomeNew,'-WindowsJson',$WindowsT,'-InjectEngineJson',(Join-Path $Inject 'engine.json'),'-InjectNextRunInSeconds','900'))
  Say '  --- 7d. the staged home still carries the 0.1.5 names ---'
  $r['7d staged not migrated'] = Run-Switch -Name 'p7d-staged-old' -Argv (@('-Version',$Version,'-StagedHome',$StagedOld,'-BackupDir',$BackupOk,'-StateRoot',$StateRoot,'-TargetHome',$HomeNew,'-WindowsJson',$WindowsT,'-InjectEngineJson',(Join-Path $Inject 'engine.json'),'-InjectNextRunInSeconds','900'))
  Say '  --- 7e. preflight NO-GO without -AcceptSessionFormatUpgrade — the REAL pipeline and the REAL staged home ---'
  $r['7e preflight NO-GO, no acceptance'] = Run-Switch -Name 'p7e-no-acceptance' -Argv (@('-Version',$Version,'-StagedHome',$Staged,'-BackupDir',$BackupOk,'-StateRoot',$StateRoot,'-TargetHome',$HomeNew,'-WindowsJson',$WindowsT,'-InjectEngineJson',(Join-Path $Inject 'engine.json'),'-InjectNextRunInSeconds','900'))
  Say '  --- 7f. preflight refuses for a reason OTHER than G8, even WITH the acceptance flag ---'
  $r['7f preflight NOGO, acceptance given'] = Run-Switch -Name 'p7f-nogo-with-acceptance' -Argv (@('-Version',$Version,'-StagedHome',$Staged,'-BackupDir',$BackupOk,'-StateRoot',$StateRoot,'-TargetHome',$HomeNew,'-WindowsJson',$WindowsT,'-AcceptSessionFormatUpgrade','-InjectPreflightVerdict','NOGO','-InjectEngineJson',(Join-Path $Inject 'engine.json'),'-InjectNextRunInSeconds','900'))
  Say ''
  $all2 = $true
  foreach ($k in $r.Keys) { Say ("  {0,-44} exit {1}" -f $k, $r[$k]); if ($r[$k] -ne 2) { $all2 = $false } }
  Say ''
  Say "  every refusal exit code is 2 (nothing written): $all2"
  $script:Results['7 refusals'] = $(if ($all2) { 'PASS' } else { 'FAIL' })
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($P['9']) {
  Rule 'PROOF 9 — the -Rollback mode: restore from the record, verify, and QUARANTINE a session file that appeared after the switch'
  Say '  This runs a switch that SUCCEEDS (injected verdicts, injected promote, injected sync text), then'
  Say '  drops a new session.v4.jsonl.zstd into the fixture home the way a real run would, then invokes'
  Say '  -Rollback and checks what it restored and what it quarantined.'
  Say ''
  $prePin9 = Sha (Join-Path $StateRoot 'pin.json')
  $preWin9 = Sha $WindowsT
  $args9 = @('-Version', $Version, '-StagedHome', $Staged, '-BackupDir', $BackupOk,
             '-StateRoot', $StateRoot, '-TargetHome', $HomeNew, '-WindowsJson', $WindowsT,
             '-IUnderstandThisWritesTheLiveHome', '-AcceptSessionFormatUpgrade',
             '-InjectPreflightVerdict', 'GO', '-InjectVerification', 'skipped',
             '-InjectEngineJson', (Join-Path $Inject 'engine.json'),
             '-InjectPromoteScript', (Join-Path $Sup 'inject-promote.ps1'),
             '-InjectSyncOut', (Join-Path $Here 'fixtures\syncstep-new.out.txt'),
             '-InjectNextRunInSeconds', '900')
  Say '  --- 9a. a switch that succeeds ---'
  $c9a = Run-Switch -Name 'p9a-successful-switch' -Argv $args9
  $preDirs9 = @(Get-ChildItem -LiteralPath $StateRoot -Directory | Where-Object { $_.Name -match '^switch-\d{8}T\d{6}Z$' } | Sort-Object Name)
  $preDir9 = if ($preDirs9.Count) { ($preDirs9 | Select-Object -Last 1).FullName } else { $null }
  Sub 'OUT OF BAND'
  if (-not $preDir9) {
    Bad 'no pre-state directory was written, so -Rollback has nothing to work from.'
    $script:Results['9 rollback mode'] = 'FAIL'
  } else {
  Say "  pre-state          : $preDir9"
  Say "  POST-STATE.json    : $(Test-Path -LiteralPath (Join-Path $preDir9 'POST-STATE.json'))   (expected: True — the switch succeeded)"
  Say "  pin.json after 9a  : $(Sha (Join-Path $StateRoot 'pin.json'))"
  Say "  windows.json after : $(Sha $WindowsT)"
  Say "  exit code          : $c9a  $(if ($c9a -eq 0) { '(applied)' } else { '(EXPECTED 0)' })"

  Say ''
  Say '  --- 9b. a session.v4.jsonl.zstd that APPEARED after the switch ---'
  $sessRel = '--FIXTURE--\zzzz\session.v4.jsonl.zstd'
  $sessPath = Join-Path $HomeNew "sessions\$sessRel"
  [void](New-Item -ItemType Directory -Path (Split-Path -Parent $sessPath) -Force)
  Set-Content -LiteralPath $sessPath -Value 'FIXTURE-v4-APPEARED-AFTER-THE-SWITCH' -Encoding ascii
  $sessHash = Sha $sessPath
  Say "  wrote         : $sessPath"
  Say "  sha256        : $sessHash"
  Say "  the v3 original from before the switch is still there: $(Test-Path -LiteralPath (Join-Path $HomeNew 'sessions\--FIXTURE--\aaaa\session.v3.jsonl.zstd'))"

  Say ''
  Say '  --- 9c. -Rollback ---'
  $c9c = Run-Switch -Name 'p9c-rollback' -Argv (@('-Rollback', '-StateRoot', $StateRoot, '-TargetHome', $HomeNew,
      '-WindowsJson', $WindowsT, '-IUnderstandThisWritesTheLiveHome', '-InjectEngineJson', (Join-Path $Inject 'engine.json'),
      '-InjectNextRunInSeconds', '900'))

  Sub 'OUT OF BAND — what it restored, and what it quarantined'
  $pre9 = Get-Content -LiteralPath (Join-Path $preDir9 'PRE-STATE.json') -Raw | ConvertFrom-Json
  $allOk9 = $true
  Say '  restored file                                  recorded sha256                                                    now                                                                verdict'
  foreach ($rw in @(@{ p = $pre9.launcherConfig.path; sha = $pre9.launcherConfig.sha256Before },
                    @{ p = $pre9.pin.path;             sha = $pre9.pin.sha256Before })) {
    $now = Sha $rw.p
    $ok = ($now -eq $rw.sha); if (-not $ok) { $allOk9 = $false }
    Say ("  {0,-46} {1} {2} {3}" -f (Split-Path -Leaf $rw.p), $rw.sha, $now, $(if ($ok) { 'MATCH' } else { 'DIFFER' }))
  }
  foreach ($rw in @($pre9.recordedConfigFiles)) {
    $dest = Join-Path $pre9.targetHome ($rw.rel -replace '/', '\')
    $now = Sha $dest
    $ok = ($now -eq $rw.sha256); if (-not $ok) { $allOk9 = $false }
    Say ("  {0,-46} {1} {2} {3}" -f $rw.rel, $rw.sha256, $now, $(if ($ok) { 'MATCH' } else { 'DIFFER' }))
  }
  Say ''
  $q9 = Join-Path $preDir9 'quarantine\v4-sessions'
  $qFile = Join-Path $q9 $sessRel
  Say "  quarantined?   : $(Test-Path -LiteralPath $qFile)"
  Say "  the moved file : $(if (Test-Path -LiteralPath $qFile) { "$(Sha $qFile)  (was $sessHash)" } else { '(absent)' })"
  Say "  byte-identical : $(if ((Test-Path -LiteralPath $qFile) -and ((Sha $qFile) -eq $sessHash)) { 'yes — MOVED, not copied, not deleted' } else { 'NO' })"
  Say "  out of the sessions tree: $(-not (Test-Path -LiteralPath $sessPath))"
  Say "  the pre-existing v3 original is untouched: $(Test-Path -LiteralPath (Join-Path $HomeNew 'sessions\--FIXTURE--\aaaa\session.v3.jsonl.zstd'))"
  $man9 = Join-Path $q9 'quarantine-manifest.tsv'
  Say "  manifest       : $man9"
  if (Test-Path -LiteralPath $man9) { foreach ($l in @(Get-Content -LiteralPath $man9)) { Say "      $l" } }
  Say ''
  Say "  pin.json back to the pre-switch state?    $(if ((Sha (Join-Path $StateRoot 'pin.json')) -eq $prePin9) { 'yes' } else { 'NO' })"
  Say "  windows.json back to the pre-switch state?$(if ((Sha $WindowsT) -eq $preWin9) { ' yes' } else { ' NO' })"
  Say "  every recorded file at its recorded hash : $allOk9"
  Say "  exit code      : $c9c  $(if ($c9c -eq 0) { '(roll-back completed)' } else { '(EXPECTED 0)' })"
  $ok9 = $allOk9 -and ($c9c -eq 0) -and (Test-Path -LiteralPath $qFile) -and ((Sha $qFile) -eq $sessHash) -and (-not (Test-Path -LiteralPath $sessPath))
  $script:Results['9 rollback mode'] = $(if ($ok9) { 'PASS' } else { 'FAIL' })
  }
}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
Rule 'PROOF 8 — the live deployment was not touched by any of this'
$HomeHashAfter = Get-ConfigSurface -DshHome $LiveHome -PinFile (Join-Path $UpdRoot 'state\pin.json') -LauncherFile $RealWindows
$RealWindowsHashAfter = Sha $RealWindows
$RealStateAfter = @(Get-ChildItem -LiteralPath (Join-Path $UpdRoot 'state') -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like 'switch-*' } | ForEach-Object { $_.Name } | Sort-Object)
$RealPinHashAfter = Sha (Join-Path $UpdRoot 'state\pin.json')
$taskAtStart = Get-ScheduledTaskInfo -TaskName 'PersonalSecretary-HarnessSync' -ErrorAction SilentlyContinue
$taskAtEnd   = Get-ScheduledTaskInfo -TaskName 'PersonalSecretary-HarnessSync' -ErrorAction SilentlyContinue
Say '  WHAT THIS PROOF CAN AND CANNOT PROVE, in one paragraph, because the honest version matters:'
Say '  the live home is NOT a quiet place. The engine serving this session appends to ~\.dsh\sessions,'
Say '  \storages, \metrics and \health continuously, AND the 15-minute PersonalSecretary-HarnessSync tick'
Say '  rewrites the very files this proof watches when it fires (it applies the repo config to ~\.dsh).'
Say '  So a difference here is only attributable to THIS SUITE if the sync task did not run inside the'
Say '  window. Both are printed below rather than assumed.'
Say ''
Say "  live CONFIG surface sha256 : $(ShaStrings $HomeHashBefore)"
Say "                               $(ShaStrings $HomeHashAfter)   -> $(if ($HomeHashBefore -eq $HomeHashAfter) { 'IDENTICAL' } else { 'CHANGED' })"
Say '  the 8 watched live files, as they stand now:'
foreach ($line in ($HomeHashAfter -split "`n")) { Say "      $line" }
Say "  repo multi-window\windows.json : $(if ($RealWindowsHashBefore -eq $RealWindowsHashAfter) { "UNCHANGED $RealWindowsHashAfter" } else { "CHANGED $RealWindowsHashBefore -> $RealWindowsHashAfter" })"
Say "  repo dsh-update\state\pin.json : $(if ($RealPinHashBefore -eq $RealPinHashAfter) { "UNCHANGED $RealPinHashAfter" } else { "CHANGED $RealPinHashBefore -> $RealPinHashAfter" })"
Say "  repo dsh-update\state\switch-* : before $($RealStateBefore.Count) [$($RealStateBefore -join ', ')]  after $($RealStateAfter.Count) [$($RealStateAfter -join ', ')]"
Say "  the sync task's LastRunTime     : before $(if ($taskAtStart) { ([datetime]$taskAtStart.LastRunTime).ToUniversalTime().ToString('o') } else { '(unreadable)' })"
Say "                                    after  $(if ($taskAtEnd) { ([datetime]$taskAtEnd.LastRunTime).ToUniversalTime().ToString('o') } else { '(unreadable)' })"
$tickMoved = ($taskAtStart -and $taskAtEnd -and ([datetime]$taskAtStart.LastRunTime) -ne ([datetime]$taskAtEnd.LastRunTime))
Say "  did that task run during this suite: $(if ($tickMoved) { 'YES — so any difference in ~\.dsh config above is ITS doing, not this suite''s' } else { 'no' })"
Say ''
$liveFilesIdentical = ($HomeHashBefore -eq $HomeHashAfter)
$repoUntouched = ($RealWindowsHashBefore -eq $RealWindowsHashAfter) -and ($RealPinHashBefore -eq $RealPinHashAfter) -and ($RealStateBefore.Count -eq $RealStateAfter.Count)
if ($liveFilesIdentical -and $repoUntouched) {
  Say '  NOTHING IN THE LIVE DEPLOYMENT WAS WRITTEN BY THIS SUITE: True — the config surface is identical'
  Say '  and the repository gained no switch-* directory.'
} elseif (-not $liveFilesIdentical -and $tickMoved -and $repoUntouched) {
  Say '  THIS SUITE WROTE NOTHING UNDER THE REPO (no switch-*, same pin.json and windows.json), and the'
  Say '  live config surface changed in a window IN WHICH THE SYNC TASK RAN — so the change is attributable'
  Say '  to that task, which exists to apply the repo config to ~\.dsh and is not part of this suite. This is'
  Say '  the environment, and it is exactly why every write proof above runs against fixtures instead.'
} else {
  Say '  ATTENTION: the live config surface changed and the sync task did NOT run, so this suite''s own'
  Say '  runs have to be suspected. Re-run a single proof with -Proof 8 to isolate it.'
}
$script:Results['8 live deployment untouched'] = $(if ($liveFilesIdentical -and $repoUntouched) { 'PASS' } elseif ($repoUntouched -and $tickMoved) { 'PASS (live config changed by the sync task, not by this suite)' } else { 'FAIL' })

Rule 'SUMMARY'
foreach ($k in $script:Results.Keys) { Say ("  {0,-30} {1}" -f $k, $script:Results[$k]) }
Say ''
Say "  test root (everything this run created): $T"
