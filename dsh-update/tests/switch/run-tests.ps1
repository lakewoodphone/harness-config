# run-tests.ps1 — exercise tools/switch-engine.ps1 against fixtures and against the real inputs.
#
# WHAT IS REAL AND WHAT IS A FIXTURE
#   REAL   : -Version 0.1.7-rc.2, -StagedHome %TEMP%\dsh-staged-migrated, the real verified backup
#            at %USERPROFILE%\dsh-backup-20260928-switch, the live engine on port 3099, the real
#            state\pin.json and the real state\history.
#   FIXTURE: DSH_UPDATE_WINDOWS_JSON  -> fixtures\windows.json        (the launcher config is never
#            written for real; the real file's sha256 is printed before and after to prove it)
#            DSH_SWITCH_TARGET_HOME   -> fixtures\targethome          (sync.py writes here, never ~\.dsh)
#
# NOTHING IN THIS FILE DELETES ANYTHING. Fixtures are built once with -Force copies and re-used.
#
# USAGE
#   pwsh -File tests/switch/run-tests.ps1 [-Case <name>] [-Rebuild]

param(
  [string]$Case = 'all',
  [switch]$Rebuild
)

$ErrorActionPreference = 'Continue'

$Here    = $PSScriptRoot
$TestsD  = Split-Path -Parent $Here
$UpdRoot = Split-Path -Parent $TestsD
$Repo    = Split-Path -Parent $UpdRoot

$Switch   = Join-Path $UpdRoot 'tools\switch-engine.ps1'
$SyncPy   = Join-Path $Repo 'scripts\sync.py'
$StateDir = Join-Path $UpdRoot 'state'
$Fx       = Join-Path $Here 'fixtures'
$Live     = Join-Path $env:USERPROFILE '.dsh'
$RealWindows = Join-Path $Repo 'multi-window\windows.json'
$OldRoot  = Join-Path $env:LOCALAPPDATA 'npm-cache\_npx\1e7f6d9597241db0'   # the 0.1.5-rc.1 prefix
$RealStaged = Join-Path $env:TEMP 'dsh-staged-migrated'
$RealBackup = Join-Path $env:USERPROFILE 'dsh-backup-20260928-switch'
$Version = '0.1.7-rc.2'

function Say  { param([string]$m = '') Write-Host $m }
function Rule { param([string]$m) Write-Host ''; Write-Host ("=" * 100); Write-Host "== $m"; Write-Host ("=" * 100) }
function Sha  { param([string]$p) if (Test-Path -LiteralPath $p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() } else { $null } }

# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────
function Build-Fixtures {
  Say "building fixtures under $Fx"
  foreach ($d in @($Fx, "$Fx\backup-ok", "$Fx\backup-old", "$Fx\backup-bad", "$Fx\backup-missing",
                   "$Fx\staged-old\.agent-presets\zabz", "$Fx\staged-old\profiles\mesh",
                   "$Fx\targethome\.agent-presets\zabz", "$Fx\targethome\.agent-presets\yocheved",
                   "$Fx\targethome\.agent-presets\cordis-bg",
                   "$Fx\targethome\profiles\web", "$Fx\targethome\profiles\mesh", "$Fx\targethome\profiles\headless",
                   "$Fx\targethome\sessions\--FIXTURE--\aaaa",
                   "$Fx\targethome\sessions\--FIXTURE--\bbbb",
                   "$Fx\targethome\sessions\--FIXTURE--\cccc")) {
    [void](New-Item -ItemType Directory -Path $d -Force)
  }

  # The launcher-config fixture: the REAL one, plus the dshInstall a roll-back would restore
  # (the 0.1.5-rc.1 prefix). primaryPort stays 3099 so the live-engine check still sees the real engine.
  $w = Get-Content -LiteralPath $RealWindows -Raw | ConvertFrom-Json
  if ($w.PSObject.Properties.Name -contains 'dshInstall') { $w.dshInstall = $OldRoot }
  else { $w | Add-Member -NotePropertyName dshInstall -NotePropertyValue $OldRoot -Force }
  $w | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$Fx\windows.json" -Encoding utf8

  # The target home: the LIVE config as it is NOW (the 0.1.5-shaped names) plus a fixture session.
  foreach ($p in @('zabz', 'yocheved', 'cordis-bg')) {
    Copy-Item -LiteralPath (Join-Path $Live ".agent-presets\$p\agent.cordis.yml") `
              -Destination "$Fx\targethome\.agent-presets\$p\agent.cordis.yml" -Force
  }
  foreach ($p in @('web', 'mesh', 'headless')) {
    Copy-Item -LiteralPath (Join-Path $Live "profiles\$p\cordis.patch.yml") `
              -Destination "$Fx\targethome\profiles\$p\cordis.patch.yml" -Force
  }
  Copy-Item -LiteralPath (Join-Path $Live 'settings.yaml') -Destination "$Fx\targethome\settings.yaml" -Force
  Set-Content -LiteralPath "$Fx\targethome\sessions\--FIXTURE--\aaaa\session.v3.jsonl.zstd" -Value 'FIXTURE-v3-original' -Encoding ascii

  # The staged-home fixture that is NOT migrated (the live, old-name copies).
  Copy-Item -LiteralPath (Join-Path $Live '.agent-presets\zabz\agent.cordis.yml') `
            -Destination "$Fx\staged-old\.agent-presets\zabz\agent.cordis.yml" -Force
  Copy-Item -LiteralPath (Join-Path $Live 'profiles\mesh\cordis.patch.yml') `
            -Destination "$Fx\staged-old\profiles\mesh\cordis.patch.yml" -Force

  # Backup reports.
  $now = (Get-Date).ToUniversalTime().ToString('o')
  $old = (Get-Date).ToUniversalTime().AddHours(-13).ToString('o')
  @{ ok = $true; finishedAt = $now; totalFiles = 3; destination = "$Fx\backup-ok"
     stores = @(@{ store = 'sessions'; verified = 2; ok = $true }, @{ store = 'settings.yaml'; verified = 1; ok = $true })
     problems = @() } | ConvertTo-Json -Depth 6 | Set-Content "$Fx\backup-ok\BACKUP-REPORT.json" -Encoding utf8
  @{ ok = $true; finishedAt = $old; totalFiles = 3; destination = "$Fx\backup-old"
     stores = @(@{ store = 'sessions'; verified = 3; ok = $true }); problems = @() } |
    ConvertTo-Json -Depth 6 | Set-Content "$Fx\backup-old\BACKUP-REPORT.json" -Encoding utf8
  @{ ok = $false; finishedAt = $now; totalFiles = 3; destination = "$Fx\backup-bad"
     stores = @(@{ store = 'sessions'; verified = 0; ok = $false })
     problems = @('sessions: 3 file(s) could not be copied faithfully') } |
    ConvertTo-Json -Depth 6 | Set-Content "$Fx\backup-bad\BACKUP-REPORT.json" -Encoding utf8
  Say 'fixtures built'
}

# ── the switch, run as a real child process ─────────────────────────────────────────────────────
function Run-Switch {
  param([string]$Name, [string[]]$Argv, [hashtable]$Env = @{})
  Rule "CASE $Name"
  $saved = @{}
  foreach ($k in $Env.Keys) {
    $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process')
    [Environment]::SetEnvironmentVariable($k, [string]$Env[$k], 'Process')
  }
  Say "cmd: pwsh -NoProfile -File `"$Switch`" $($Argv -join ' ')"
  foreach ($k in $Env.Keys) { Say "env: $k=$($Env[$k])" }
  Say ''
  $out = Join-Path $env:TEMP "switch-case-$Name.out.txt"
  $err = Join-Path $env:TEMP "switch-case-$Name.err.txt"
  & pwsh -NoProfile -File $Switch @Argv 1> $out 2> $err
  $code = $LASTEXITCODE
  foreach ($k in $Env.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
  foreach ($l in @(Get-Content -LiteralPath $out -ErrorAction SilentlyContinue)) { Say $l }
  $et = @(Get-Content -LiteralPath $err -ErrorAction SilentlyContinue)
  if ($et.Count) { Say ''; Say '--- stderr ---'; foreach ($l in $et) { Say $l } }
  Say ''
  Say "EXIT CODE: $code"
  return $code
}

$script:Codes = [ordered]@{}

# ═════════════════════════════════════════════════════════════════════════════════════════════════
if ($Rebuild -or -not (Test-Path "$Fx\windows.json")) { Build-Fixtures }

if ($Case -eq 'build') { exit 0 }

# ── 0. it parses ─────────────────────────────────────────────────────────────────────────────────
if ($Case -in @('all', 'parse')) {
  Rule 'CASE parse — the script parses, 0 errors'
  $errs = $null; $toks = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile($Switch, [ref]$toks, [ref]$errs)
  if ($errs -and $errs.Count) { foreach ($e in $errs) { Say "line $($e.Extent.StartLineNumber): $($e.Message)" } }
  else { Say 'PARSE OK — 0 errors' }
  $script:Codes['parse'] = 0
}

# ── 1. the real dry run ──────────────────────────────────────────────────────────────────────────
if ($Case -in @('all', 'dryrun')) {
  $preBefore = @(Get-ChildItem -LiteralPath $StateDir -Directory | Where-Object { $_.Name -like 'switch-*' } | ForEach-Object { $_.Name })
  $wBefore = Sha $RealWindows
  $pBefore = Sha (Join-Path $StateDir 'pin.json')
  $code = Run-Switch -Name 'dryrun' -Argv @(
    '-Version', $Version, '-StagedHome', $RealStaged, '-BackupDir', $RealBackup, '-DryRun', '-AcceptSessionFormatUpgrade')
  $preAfter = @(Get-ChildItem -LiteralPath $StateDir -Directory | Where-Object { $_.Name -like 'switch-*' } | ForEach-Object { $_.Name })
  $wAfter = Sha $RealWindows
  $pAfter = Sha (Join-Path $StateDir 'pin.json')
  Rule 'DRY RUN — OUT OF BAND PROOF'
  Say "  state\switch-* directories : before $($preBefore.Count) [$($preBefore -join ', ')]  ->  after $($preAfter.Count) [$($preAfter -join ', ')]"
  Say "  real windows.json sha256   : before $wBefore"
  Say "                               after $wAfter   -> $(if ($wBefore -eq $wAfter) { 'UNCHANGED' } else { 'CHANGED' })"
  Say "  real state\pin.json sha256 : before $pBefore"
  Say "                               after $pAfter   -> $(if ($pBefore -eq $pAfter) { 'UNCHANGED' } else { 'CHANGED' })"
  $script:Codes['dryrun'] = $code
}

# ── 2. the refusals ──────────────────────────────────────────────────────────────────────────────
if ($Case -in @('all', 'refusals')) {
  $script:Codes['R1'] = Run-Switch -Name 'R1-no-backup-report' -Argv @(
    '-Version', $Version, '-StagedHome', $RealStaged, '-BackupDir', "$Fx\backup-missing", '-DryRun')
  $script:Codes['R2'] = Run-Switch -Name 'R2-backup-not-ok' -Argv @(
    '-Version', $Version, '-StagedHome', $RealStaged, '-BackupDir', "$Fx\backup-bad", '-DryRun')
  $script:Codes['R3'] = Run-Switch -Name 'R3-backup-stale' -Argv @(
    '-Version', $Version, '-StagedHome', $RealStaged, '-BackupDir', "$Fx\backup-old", '-DryRun')
  $script:Codes['R4'] = Run-Switch -Name 'R4-staged-not-migrated' -Argv @(
    '-Version', $Version, '-StagedHome', "$Fx\staged-old", '-BackupDir', $RealBackup, '-DryRun')
  $script:Codes['R5'] = Run-Switch -Name 'R5-preflight-nogo-no-acceptance' -Argv @(
    '-Version', $Version, '-StagedHome', $RealStaged, '-BackupDir', $RealBackup, '-DryRun')
}

# ── 3. the G8-only failure, accepted ─────────────────────────────────────────────────────────────
if ($Case -in @('all', 'accept')) {
  $script:Codes['accept'] = Run-Switch -Name 'accept-G8' -Argv @(
    '-Version', $Version, '-StagedHome', $RealStaged, '-BackupDir', $RealBackup, '-AcceptSessionFormatUpgrade') `
    -Env @{ DSH_UPDATE_WINDOWS_JSON = "$Fx\windows.json"; DSH_SWITCH_TARGET_HOME = "$Fx\targethome" }

  Say ''
  Say "  real windows.json sha256 after the run: $(Sha $RealWindows)  (must equal the value printed in CASE dryrun)"
  Say "  fixture windows.json dshInstall now   : $((Get-Content -LiteralPath "$Fx\windows.json" -Raw | ConvertFrom-Json).dshInstall)"
  $zabz = Get-Content -LiteralPath "$Fx\targethome\.agent-presets\zabz\agent.cordis.yml" -Raw
  Say "  fixture target preset 'zabz' names ptc: $([bool]($zabz -match "@deepseek-ai/dsh-workflow-ptc"))   names worker-thread: $([bool]($zabz -match "@deepseek-ai/dsh-workflow-worker-thread"))"
  Say "  REAL state\pin.json version now       : $((Get-Content -LiteralPath (Join-Path $StateDir 'pin.json') -Raw | ConvertFrom-Json).version)   (unchanged: promote refused on condition 1)"
}

# ── 4. roll back the real pin + the fixture config (the tested way back) ─────────────────────────
if ($Case -in @('all', 'rback')) {
  $script:Codes['rback'] = Run-Switch -Name 'rollback-after-accept' -Argv @('-Rollback') `
    -Env @{ DSH_UPDATE_WINDOWS_JSON = "$Fx\windows.json"; DSH_SWITCH_TARGET_HOME = "$Fx\targethome" }
  Say ''
  Say "  real state\pin.json version now: $((Get-Content -LiteralPath (Join-Path $StateDir 'pin.json') -Raw | ConvertFrom-Json).version)"
  Say "  fixture windows.json dshInstall: $((Get-Content -LiteralPath "$Fx\windows.json" -Raw | ConvertFrom-Json).dshInstall)"
}

# ── 5. the v4 quarantine, on a fixture pre-state ─────────────────────────────────────────────────
if ($Case -in @('all', 'quarantine')) {
  # A pre-state as of NOW: the fixture target home's config, the fixture launcher config, the real pin.
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $fixPre = Join-Path $StateDir "switch-$stamp"
  [void](New-Item -ItemType Directory -Path "$fixPre\config" -Force)
  Copy-Item -LiteralPath (Join-Path $StateDir 'pin.json') -Destination "$fixPre\pin.json" -Force
  Copy-Item -LiteralPath "$Fx\windows.json"               -Destination "$fixPre\windows.json" -Force

  $recorded = @()
  foreach ($f in (Get-ChildItem -LiteralPath "$Fx\targethome\.agent-presets" -Directory |
                  ForEach-Object { Join-Path $_.FullName 'agent.cordis.yml' }) +
                 (Get-ChildItem -LiteralPath "$Fx\targethome\profiles" -Directory |
                  ForEach-Object { Join-Path $_.FullName 'cordis.patch.yml' }) +
                 @("$Fx\targethome\settings.yaml")) {
    if (-not (Test-Path -LiteralPath $f)) { continue }
    $rel = [System.IO.Path]::GetRelativePath("$Fx\targethome", $f) -replace '\\', '/'
    $dest = Join-Path "$fixPre\config" ($rel -replace '/', '\')
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force)
    Copy-Item -LiteralPath $f -Destination $dest -Force
    $recorded += [pscustomobject]@{ rel = $rel; sha256 = (Sha $f); copy = "config/$rel" }
  }

  # The pre-state's session list: the v3 original, and a v4 sibling that was ALREADY here.
  @("relpath`tbytes",
    "--FIXTURE--/aaaa/session.v3.jsonl.zstd`t20",
    "--FIXTURE--/bbbb/session.v4.jsonl.zstd`t21") |
    Set-Content -LiteralPath "$fixPre\sessions-present.tsv" -Encoding utf8

  # What the pre-state records, so a restore has something to restore TO.
  $preJson = [ordered]@{
    schemaVersion = 1; mode = 'fixture'; createdAt = (Get-Date).ToUniversalTime().ToString('o')
    host = $env:COMPUTERNAME; fromVersion = '0.1.7-rc.2'; toVersion = '0.1.7-rc.2'
    targetHome = "$Fx\targethome"; targetIsLive = $false
    launcherConfig = [ordered]@{ path = "$Fx\windows.json"; sha256Before = (Sha "$Fx\windows.json") }
    pin = [ordered]@{ path = (Join-Path $StateDir 'pin.json'); sha256Before = (Sha (Join-Path $StateDir 'pin.json')) }
    recordedConfigFiles = $recorded
    sessionFiles = [ordered]@{ root = "$Fx\targethome\sessions"; count = 2; list = 'sessions-present.tsv' }
    engine = $null
  }
  $preJson | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath "$fixPre\PRE-STATE.json" -Encoding utf8
  Say "fixture pre-state built: $fixPre"

  # NOW perturb everything the pre-state recorded, and add the two v4 files.
  (Get-Content -LiteralPath "$Fx\windows.json" -Raw) -replace '"dshInstall":\s*"[^"]*"', '"dshInstall": "C:\\PERTURBED\\not-a-prefix"' |
    Set-Content -LiteralPath "$Fx\windows.json" -Encoding utf8
  foreach ($r in $recorded) {
    Add-Content -LiteralPath (Join-Path "$Fx\targethome" ($r.rel -replace '/', '\')) -Value '# PERTURBED AFTER THE PRE-STATE WAS TAKEN'
  }
  Set-Content -LiteralPath "$Fx\targethome\sessions\--FIXTURE--\bbbb\session.v4.jsonl.zstd" -Value 'FIXTURE-v4-ALREADY-PRESENT' -Encoding ascii
  Set-Content -LiteralPath "$Fx\targethome\sessions\--FIXTURE--\cccc\session.v4.jsonl.zstd" -Value 'FIXTURE-v4-NEW-AFTER-THE-SWITCH' -Encoding ascii
  Say 'perturbed: windows.json dshInstall, every recorded config file, and two session.v4.jsonl.zstd files (bbbb = listed, cccc = NOT listed)'

  $script:Codes['quarantine'] = Run-Switch -Name 'fixture-rollback-quarantine' -Argv @('-Rollback') `
    -Env @{ DSH_UPDATE_WINDOWS_JSON = "$Fx\windows.json"; DSH_SWITCH_TARGET_HOME = "$Fx\targethome" }

  Rule 'INDEPENDENT RE-HASH OF THE RESTORED FILES (checked here, not by the script)'
  $allOk = $true
  foreach ($r in $recorded) {
    $p = Join-Path "$Fx\targethome" ($r.rel -replace '/', '\')
    $now = Sha $p
    $ok = ($now -eq $r.sha256)
    if (-not $ok) { $allOk = $false }
    Say ("  {0,-6} {1}`n         recorded {2}`n         now      {3}" -f $(if ($ok) { 'MATCH' } else { 'DIFFER' }), $r.rel, $r.sha256, $now)
  }
  Say "  windows.json : $(if ((Sha "$Fx\windows.json") -eq (Get-Content -LiteralPath "$fixPre\PRE-STATE.json" -Raw | ConvertFrom-Json).launcherConfig.sha256Before) { 'MATCH' } else { 'DIFFER' })"
  Say "  pin.json     : $(if ((Sha (Join-Path $StateDir 'pin.json')) -eq (Get-Content -LiteralPath "$fixPre\PRE-STATE.json" -Raw | ConvertFrom-Json).pin.sha256Before) { 'MATCH' } else { 'DIFFER' })"
  Say "  ALL RECORDED CONFIG FILES RESTORED TO THEIR RECORDED SHA256: $allOk"

  Rule 'THE v4 FILES AFTER THE QUARANTINE'
  foreach ($rel in @('--FIXTURE--\aaaa\session.v3.jsonl.zstd', '--FIXTURE--\bbbb\session.v4.jsonl.zstd', '--FIXTURE--\cccc\session.v4.jsonl.zstd')) {
    $p = Join-Path "$Fx\targethome\sessions" $rel
    Say ("  {0,-46} in the sessions tree: {1}" -f $rel, (Test-Path -LiteralPath $p))
  }
  $qd = Join-Path $fixPre 'quarantined-v4-sessions'
  Say "  quarantined-v4-sessions contents:"
  foreach ($f in @(Get-ChildItem -LiteralPath $qd -Recurse -File)) { Say "    $($f.FullName)  ($($f.Length) B)" }
  Say "  quarantine manifest:"
  foreach ($l in @(Get-Content -LiteralPath (Join-Path $qd 'quarantine-manifest.tsv'))) { Say "    $l" }
}

Rule 'EXIT CODES BY CASE'
foreach ($k in $script:Codes.Keys) { Say ("  {0,-12} {1}" -f $k, $script:Codes[$k]) }
Say ''
Say 'expected: parse 0, dryrun 0, R1 2, R2 2, R3 2, R4 2, R5 2, accept 4 (promote refuses on condition 1 while G8 fails), rback 0, quarantine 0, syncstep n/a'

# ── 6. the exact command STEP 3 issues, on BOTH sides of the version precondition ────────────────
#
# STEP 3 cannot be reached end to end for 0.1.7-rc.2, because `promote` refuses at condition 1 while
# G8 fails (see CASE accept). So the MECHANISM step 3 depends on is proven here directly: the SAME
# sync command, against the SAME config, flips from SKIPPED to APPLIED depending ONLY on which engine
# root the launcher config names. That is the self-enforcing order the whole switch rides on.
if ($Case -in @('all', 'syncstep')) {
  Rule 'CASE syncstep — sync.py for real, old engine root vs new engine root, on identical config'
  $newRoot = Join-Path $UpdRoot "vendor\prefix\$Version"
  foreach ($side in @(
      @{ name = 'OLD-root (what a roll-back restores)'; root = $OldRoot;  dir = "$Fx\syncstep-old" },
      @{ name = 'NEW-root (what promote writes)';       root = $newRoot;  dir = "$Fx\syncstep-new" })) {
    [void](New-Item -ItemType Directory -Path "$($side.dir)\profiles" -Force)
    Copy-Item -LiteralPath "$Fx\targethome\.agent-presets" -Destination "$($side.dir)\.agent-presets" -Recurse -Force
    foreach ($p in @(Get-ChildItem -LiteralPath "$Fx\targethome\profiles" -Directory)) {
      Copy-Item -LiteralPath $p.FullName -Destination "$($side.dir)\profiles\$(Split-Path -Leaf $p.FullName)" -Recurse -Force
    }
    Say ''
    Say "  --- $($side.name)"
    Say "  engine root : $($side.root)"
    Say "  DSH_HOME    : $($side.dir)"
    $o = "$($side.dir).out.txt"; $e = "$($side.dir).err.txt"
    $saved = [Environment]::GetEnvironmentVariable('DSH_HOME', 'Process')
    [Environment]::SetEnvironmentVariable('DSH_HOME', $side.dir, 'Process')
    & python -X utf8 $SyncPy --engine-root $side.root 1> $o 2> $e
    $code = $LASTEXITCODE
    [Environment]::SetEnvironmentVariable('DSH_HOME', $saved, 'Process')
    foreach ($l in @(Get-Content -LiteralPath $o -ErrorAction SilentlyContinue)) { Say "    $l" }
    Say "    exit: $code"
    $zabz = Get-Content -LiteralPath "$($side.dir)\.agent-presets\zabz\agent.cordis.yml" -Raw -ErrorAction SilentlyContinue
    $mesh = Get-Content -LiteralPath "$($side.dir)\profiles\mesh\cordis.patch.yml" -Raw -ErrorAction SilentlyContinue
    Say "    RESULT: preset 'zabz' names ptc = $([bool]($zabz -match '@deepseek-ai/dsh-workflow-ptc')) ; mesh patch names registry = $([bool]($mesh -match '@deepseek-ai/dsh-agent-preset-registry'))"
  }
}



