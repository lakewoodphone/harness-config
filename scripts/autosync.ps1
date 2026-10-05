<#
.SYNOPSIS
  Keep this machine's harness-config in step with the source of truth - unattended.

.DESCRIPTION
  harness-config is the single source of truth for the harness (DECISIONS D7): settings, presets and
  scripts live in git and reach `~/.dsh` through `scripts/sync.py`. Until now that happened only when a
  session remembered to do it, so the two workstations drifted the moment nobody was looking (PAIN P8).

  This script closes that gap and is deliberately timid. It NEVER:
    * commits - what a human or an agent chose to write is theirs to commit (LESSONS L33)
    * merges or rebases - a divergence is reported, not resolved by guesswork
    * stashes, resets, cleans or force-pushes - this business has lost data twice
    * touches a dirty working tree at all

  It does exactly one safe thing: fast-forward the repo to origin, apply it to `~/.dsh`, prove the apply
  converged, push commits that are already made but not yet sent, and write down what happened.

  DIVERGENCE: PRESERVE FIRST, THEN REPORT (2026-09-14)
  ----------------------------------------------------
  Refusing to merge was right; refusing to *preserve* was the defect. Measured four times in one day:
  the moment any machine held a commit the remote did not have, `git pull --ff-only` refused, the run
  ended 'attention'/exit 1, and that machine kept its OLD settings, OLD presets and OLD launcher
  indefinitely - a blind machine also cannot receive a model-failover flip, so it can sit on a dead
  model. It LOOKED healthy while frozen, because the report went to a file nothing consumed.

  So the refusal now applies to the DESTINATION, not to the commits: when this checkout is ahead, the
  local commits are first pushed to a normal, NON-forced side ref -

      refs/heads/diverged-<host>-<UTC date>

  - which cannot fail a fast-forward and destroys nothing (it only ever creates or fast-forwards a ref).
  If that same push also accepts the BRANCH, there was no real divergence and the machine simply
  converges. Still no merge, no rebase, no reset, no force, no guess (LESSONS L33, PAIN P8/P47c).

  The status contract (kept in step with scripts/autosync.sh):
    * ~/.harness-config-autosync/status.json  - the per-host run record. Its shape is UNCHANGED: the
      attention plugin packages/plugin-attention/lib/index.js and the CEO-kernel sentinel both read
      `result`/`detail`/`at` from it, so fields are only ever added, never renamed or removed.
    * ~/.dsh-sync-status/status.json          - machine-readable health for a monitor to consume,
      mirroring the model-watch idiom (~/.dsh-model-watch/status.json). Fields: updated, result,
      detail, behind, ahead, branch, local_commits_preserved (+ host, repo, commit, preserved_ref).

  FOLLOW-UP (deliberately NOT done here - it belongs in the kernel, not in the deploy path)
  -----------------------------------------------------------------------------------------
  Another session holds ~/ceo-kernel dirty and mid-deploy, so this script only *writes* the status.
  When that tree is quiet, a `sync_frozen` sentinel check should read ~/.dsh-sync-status/status.json
  and escalate to the owner when `ahead > 0` or `local_commits_preserved` is true - that is the hop
  that still needs a consumer. Note for whoever writes it: the side ref lives on the REMOTE, so
  `git ls-remote origin refs/heads/diverged-*` lists every commit this ever had to rescue.

  MIRROR FALLBACK - A CONSUMER THAT SURVIVES A SECRATARY-DARK NIGHT (2026-10-02, item 367)
  -----------------------------------------------------------------------------------------
  origin lives on secratary. Every step above fetched `origin` and nothing else, so on the one
  night that matters -- the night the secratary HOST is the machine that is down -- this consumer
  could not fetch, ended 'attention'/1, and stayed pinned to the dead model. The model-failover
  mover can now push a flip to a non-secratary mirror (item 367), but a consumer that never reads
  the mirror makes that durability useless. So: when `git fetch origin` fails AND a mirror remote
  exists, this script fetches the mirror instead, takes its counts and fast-forwards from it, and
  records `synced_via`. The mirror remote name is `mirror` (override with HARNESS_MIRROR_REMOTE;
  empty disables the fallback). Origin is still tried first, so nothing changes on a normal night.

  Exit codes: 0 clean (synced, or nothing to do) - 1 attention (dirty tree, divergence, apply failed)
              - 2 cannot run (no repo, no python, git missing)

.EXAMPLE
  pwsh -File scripts\autosync.ps1
  pwsh -File scripts\autosync.ps1 -Status      # print the last run and exit
#>
[CmdletBinding()]
param(
  # Defaulted in the body, not here: Windows PowerShell 5.1 does not populate $PSScriptRoot while
  # evaluating parameter defaults, so `powershell -NoProfile -File scripts\autosync.ps1` with no
  # arguments died with "Split-Path: Cannot bind argument to parameter 'Path' because it is an empty
  # string". pwsh 7 fills it in, which is why only the older interpreter showed the fault. The whole
  # file is kept pure ASCII for the same reason: 5.1 reads a BOM-less .ps1 as ANSI, so a single em
  # dash made it refuse to parse the script at all. Both verified under powershell.exe and pwsh.
  [string]$Repo = '',
  [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'harness-config-autosync'),
  [string]$SyncStatusDir = (Join-Path $env:USERPROFILE '.dsh-sync-status'),
  [switch]$Status,
  [switch]$Quiet
)

# Item 367: the remote that carries a failover when origin (secratary) is the host that is down.
# Empty disables the fallback and restores origin-only behaviour.
$MirrorRemote = if ($env:HARNESS_MIRROR_REMOTE) { $env:HARNESS_MIRROR_REMOTE } else { 'mirror' }

$ErrorActionPreference = 'Stop'
# This file lives in <repo>/scripts, so the repo is the parent of the script directory.
if (-not $Repo) { $Repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath) }
if (-not $Repo) { $Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }  # dot-sourced
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
$syncStatusPath = Join-Path $SyncStatusDir 'status.json'

# --------------------------------------------------------------------------
# The record. Written on EVERY outcome, and written to both surfaces.
#
# A run that stops early (no repo, no python, fetch refused, divergence, apply failed) must still
# leave the last state readable - that is the whole point: a frozen machine has to be able to say
# so. The per-host shape is frozen (the attention plugin and the kernel sentinel read it); the
# ~/.dsh-sync-status/status.json file is the fixed machine-readable schema a monitor consumes.
# --------------------------------------------------------------------------
function Write-SyncStatus($obj) {
  try {
    if (-not (Test-Path $SyncStatusDir)) { New-Item -ItemType Directory -Force -Path $SyncStatusDir | Out-Null }
    # Never emit `null` for a field the schema promises: an absent ref and an empty one mean the
    # same thing to a consumer, and `null` only invites a special case in every reader.
    $doc = [ordered]@{
      updated                 = $obj.at
      result                  = $obj.result
      detail                  = $obj.detail
      behind                  = $(if ($null -eq $obj.behind) { 0 } else { $obj.behind })
      ahead                   = $(if ($null -eq $obj.ahead) { 0 } else { $obj.ahead })
      branch                  = $(if ($null -eq $obj.branch) { '' } else { $obj.branch })
      local_commits_preserved = [bool]$obj.local_commits_preserved
      host                    = $(if ($null -eq $obj.host) { '' } else { $obj.host })
      repo                    = $(if ($null -eq $obj.repo) { '' } else { $obj.repo })
      commit                  = $(if ($null -eq $obj.commit) { '' } else { $obj.commit })
      preserved_ref           = $(if ($null -eq $obj.preserved_ref) { '' } else { $obj.preserved_ref })
      # Added 2026-10-02 with the mirror fallback (item 367): which remote actually
      # carried this sync. 'origin' on a normal night; the mirror name when origin was
      # down. Added, never renamed -- an older reader can ignore it.
      synced_via              = $(if ($null -eq $obj.synced_via) { '' } else { $obj.synced_via })
      # Added 2026-09-15: -1 = not measured, 0 = measured and none. Never a null.
      id_collisions           = $(if ($null -eq $obj.id_collisions) { -1 } else { $obj.id_collisions })
    }
    ($doc | ConvertTo-Json -Depth 4) | Set-Content -Path $syncStatusPath -Encoding utf8
  } catch {
    Log "WARN could not write $syncStatusPath : $($_.Exception.Message)"
  }
}

function Record($obj) {
  $obj | Add-Member -NotePropertyName host -NotePropertyValue $env:COMPUTERNAME -Force
  $obj | Add-Member -NotePropertyName at -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o') -Force
  # Defaults for the fixed schema, so every surface can state these rather than leave them blank.
  # Type-correct: a count stays a number, so a consumer never has to guess what `false` means.
  $defaults = [ordered]@{ behind = 0; ahead = 0; branch = ''; local_commits_preserved = $false }
  foreach ($p in $defaults.Keys) {
    if ($null -eq $obj.$p) { $obj | Add-Member -NotePropertyName $p -NotePropertyValue $defaults[$p] -Force }
  }
  # Cross-machine id collisions (journal/tools/idguard.py). This is the failure that is
  # invisible to BOTH this script and `journal.py check` -- a fast-forward cannot see it, and
  # check compares ids only within the working tree -- and it arrives as an unresolvable merge
  # hours later. 2026-09-15: 98 such ids cost most of a session. -1 means "not measured".
  if (-not ($obj.PSObject.Properties.Name -contains 'id_collisions')) {
    $obj | Add-Member -NotePropertyName id_collisions `
      -NotePropertyValue $(if ($null -eq $script:IdCollisions) { -1 } else { $script:IdCollisions }) -Force
  }
  ($obj | ConvertTo-Json -Depth 6) | Set-Content -Path $statusPath -Encoding utf8
  $line = '{0} [{1}] {2}' -f $obj.at, $obj.result, $obj.detail
  Add-Content -Path $logPath -Value $line
  Log $line
  Write-SyncStatus $obj
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
# py launcher, then the secretary venv - and prove the import rather than assuming it.
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
# 1. Note a tree with modified TRACKED files - but do not refuse to pull.
#
#    Refusing outright would mean the sync never runs on a machine where several agent sessions write
#    files all day (LESSONS L33, PAIN P13), which is exactly when drift goes unnoticed. So:
#      * the PULL is attempted anyway. `git pull --ff-only` refuses by itself to overwrite locally
#        modified files, so git is the safety here - not a heuristic of mine.
#      * the APPLY to ~/.dsh is skipped while tracked files are modified. Publishing a half-written
#        preset into the live config is the one thing that would actually cause harm; leaving ~/.dsh on
#        the last good state until the tree is clean is always safe and self-corrects next run.
# --------------------------------------------------------------------------
$dirty = @(& git -C $gitDir status --porcelain --untracked-files=no)
$untracked = @(& git -C $gitDir status --porcelain --untracked-files=all | Where-Object { $_ -like '??*' })
$dirtyNames = ($dirty | ForEach-Object { $_.Substring(3) } | Select-Object -First 8) -join ', '

# --------------------------------------------------------------------------
# 2. Fetch, then take the counts. Origin first; a non-secratary mirror as the
#    fallback when origin is unreachable (item 367). $syncRemote names whichever
#    remote actually carried the fetch, and every later origin/<branch> reference
#    goes through it.
# --------------------------------------------------------------------------
$syncRemote = 'origin'
$prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& git -C $gitDir fetch --quiet --prune 2>&1 | Out-Null
$fetchOk = ($LASTEXITCODE -eq 0)
if (-not $fetchOk -and $MirrorRemote) {
  $remotes = @(& git -C $gitDir remote 2>$null)
  if ($remotes -contains $MirrorRemote) {
    Log "  origin fetch failed; trying the non-secratary mirror '$MirrorRemote' (item 367)"
    & git -C $gitDir fetch --quiet --prune $MirrorRemote 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $fetchOk = $true; $syncRemote = $MirrorRemote }
  }
}
$branch = (& git -C $gitDir rev-parse --abbrev-ref HEAD 2>$null)
$counts = (& git -C $gitDir rev-list --left-right --count "$syncRemote/$branch...HEAD" 2>$null)
$ErrorActionPreference = $prevEap

if (-not $fetchOk) {
  Record ([ordered]@{ result = 'attention'; detail = "git fetch failed - offline, or the remote is down (tried origin and mirror '$MirrorRemote')"; repo = $gitDir; branch = $branch; synced_via = $syncRemote })
  exit 1
}

$behind = 0; $ahead = 0
if ($counts -match '^(\d+)\s+(\d+)$') { $behind = [int]$Matches[1]; $ahead = [int]$Matches[2] }

# --------------------------------------------------------------------------
# 2a. CROSS-MACHINE ID COLLISIONS. Measured here, before anything can exit, because this is
#     the fault that both this script and `journal.py check` are blind to: a fast-forward
#     cannot see it, and check compares ids within the working tree only. It surfaces as a
#     merge that refuses to resolve -- 98 ids on 2026-09-15, most of a session to untangle.
#
#     Read-only: idguard never writes to the journal. Its own ground-truth test is the 98:
#       python journal/tools/idguard.py --local-rev 919cfa64 --refs 613ee55   -> 98 collisions
#     A collision is NOT an error in this script's job -- the sync may still be perfectly
#     able to fast-forward -- so it is recorded as a number, not turned into a failure here.
# --------------------------------------------------------------------------
$IdCollisions = -1
try {
  $idguard = Join-Path $gitDir 'journal\tools\idguard.py'
  if (Test-Path $idguard) {
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $igRaw = (& $python $idguard --json 2>$null | Out-String)
    $ErrorActionPreference = $prevEap
    if ($igRaw -and $igRaw.Trim().StartsWith('{')) {
      $IdCollisions = @(($igRaw | ConvertFrom-Json).collisions).Count
    }
  }
} catch {
  $IdCollisions = -1   # cannot see is reported as cannot see, never as zero
}

# --------------------------------------------------------------------------
# 2b. AHEAD => PRESERVE FIRST, before any pull can move HEAD. This is the fix.
#
#     A plain `git push` is attempted first and is EXACTLY what the old step-4 push did (same
#     refspec, same --quiet, still no --force): if origin accepts it, the branch fast-forwarded and
#     this machine has simply converged - there was no real divergence, so there is nothing to
#     escalate and the run proceeds normally. The machine does not need a heuristic to decide.
#
#     A REFUSED push is the divergence signal. Then, and only then, the local commits are pushed to
#     `refs/heads/diverged-<host>-<UTC date>`: a new ref, so the push cannot fail a fast-forward and
#     cannot destroy anything. It exists so a later session can RECOVER the work -
#
#         git fetch origin 'refs/heads/diverged-*:refs/remotes/origin/diverged-*'
#         git log origin/diverged-<host>-<date>          # what was stranded, intact
#         git cherry-pick <sha>                          # or review and commit it properly
#
#     Nothing is merged, rebased, reset, stashed or forced. The refusal to guess is unchanged; only
#     the destination changed. The run still ends 'attention'/1, because a machine that cannot
#     fast-forward is NOT syncing and the owner must be able to see that.
# --------------------------------------------------------------------------
$preserved = $false
$preservedRef = ''
if ($ahead -gt 0) {
  $safeHost = ($env:COMPUTERNAME -replace '[^A-Za-z0-9._-]', '-')
  $preservedRef = 'refs/heads/diverged-{0}-{1}' -f $safeHost, (Get-Date).ToUniversalTime().ToString('yyyyMMdd')

  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  & git -C $gitDir -c core.autocrlf=false push --quiet 2>&1 | Out-Null
  $pushRefused = ($LASTEXITCODE -ne 0)
  $ErrorActionPreference = $prevEap

  if (-not $pushRefused) {
    # Fast-forwardable after all: the branch went to origin, so nothing was stranded and no side ref
    # was created. Do not report one - a status that names a ref which does not exist is a lie a
    # future session would act on.
    $preservedRef = ''
  } else {
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & git -C $gitDir -c core.autocrlf=false push --quiet origin "HEAD:$preservedRef" 2>&1 | Out-Null
    $preserveOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prevEap

    if ($preserveOk) {
      $preserved = $true
      $sha = (& git -C $gitDir rev-parse --short "refs/heads/$branch" 2>$null)
      Record ([ordered]@{
          result                  = 'attention'
          detail                  = "histories diverged ($behind behind / $ahead ahead) - local commits are SAFE on $preservedRef (HEAD $sha); fast-forward refused, so this machine is NOT syncing. Needs a human."
          repo                    = $gitDir; branch = $branch
          behind                  = $behind; ahead = $ahead
          local_commits_preserved = $true
          preserved_ref           = $preservedRef
        })
      Log "  recover with: git fetch origin 'refs/heads/diverged-*:refs/remotes/origin/diverged-*'  then  git log origin/diverged-$safeHost-*"
      exit 1
    }

    # Could not even create the side ref (no push rights, remote read-only, network died mid-run).
    # Say exactly that: the commits are NOT preserved and the state is worse than a plain refusal,
    # because this machine stays frozen either way. preserved_ref stays empty on purpose - naming a
    # ref that was never created would send a future session looking for something that is not there.
    Record ([ordered]@{
        result                  = 'attention'
        detail                  = "histories diverged ($behind behind / $ahead ahead) AND the local commits could NOT be pushed to $preservedRef - they exist only in this checkout; nobody else can see them. Needs a human."
        repo                    = $gitDir; branch = $branch
        behind                  = $behind; ahead = $ahead
        local_commits_preserved = $false
        preserved_ref           = ''
      })
    exit 1
  }
}

# --------------------------------------------------------------------------
# 2c. CLEAR WHAT ONLY *LOOKS* LIKE A DIVERGENCE, THEN PULL (2026-09-28).
#
#     Measured on ZABZ-TECH: this machine sat 56 commits behind for days while EVERY tick reported
#     "histories diverged (55 behind / 0 ahead) and step 2b preserved nothing. Needs a human." There
#     was no divergence at all. Two locally-modified GENERATED paths -- journal/index/stamp.json and
#     journal/state/owner-questions.md, both rewritten by ordinary use -- were also modified by the
#     incoming commits, and git refuses a fast-forward that would overwrite a locally modified file.
#     The run could not tell that apart from a real divergence, so it froze, said "human", and the
#     human was not there: 56 commits of configuration never reached this machine.
#
#     The old comment above claimed this branch was "unreachable in practice". It was reachable the
#     whole time; nothing had ever measured which condition reaches it.
#
#     So: ask git, read-only, EXACTLY what it would refuse, and clear only the two cases that are
#     provably not work:
#       * a modified tracked file under journal/index/ or journal/state/ -- a cache and a generated
#         mirror, both rebuildable, both never authored by hand. Backed up first, byte for byte.
#       * an untracked file whose bytes are IDENTICAL to the incoming blob. Nothing unique exists to
#         lose, and the incoming commit writes the same bytes back.
#     Everything else -- any other modified file, any untracked file that DIFFERS from the incoming
#     blob -- is left exactly where it is, named in the report, and the pull is allowed to refuse.
#     That refusal is then a real signal instead of a permanent alibi.
#
#     Nothing is reset, cleaned, stashed or forced. Every byte removed from the working tree is in
#     <StateDir>\blockers\<UTC stamp>\ first, with a manifest naming its sha256.
# --------------------------------------------------------------------------
$blockersCleared = @()
$blockersKept = @()
if ($behind -gt 0) {
  # git read-tree stops at the FIRST blocker it names, so one pass clears one file. Loop until a pass
  # finds nothing left to clear (measured: two generated files + one untracked-identical file needed
  # three passes). Bounded, and a pass that clears nothing ends the loop.
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $bkRoot = Join-Path $StateDir ("blockers\" + $stamp)
  $manifest = New-Object System.Collections.Generic.List[string]
  $bkRootMade = $false

  for ($pass = 1; $pass -le 25; $pass++) {
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    # -c core.autocrlf=false on purpose: the pull below runs with exactly this config, so the
    # detector must see the tree the same way. Measured 2026-09-28 on a fixture where the two
    # configs differed: the detector cleared the tree clean and the pull still refused on the same
    # paths, because under a different eol config every CRLF file reads as locally modified.
    $detect = (& git -C $gitDir -c core.autocrlf=false read-tree -n -u -m HEAD "$syncRemote/$branch" 2>&1 | Out-String)
    $ErrorActionPreference = $prevEap

    $named = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($detect -split "`n")) {
      $t = $line.Trim()
      # git prefixes these with "error: "; match the tail, not the start of the line.
      if ($t -match "Entry '(.+?)' not uptodate") { $named.Add($Matches[1]) }
      elseif ($t -match "Untracked working tree file '(.+?)' would be overwritten") { $named.Add($Matches[1]) }
    }
    if ($named.Count -eq 0) { break }

    $clearedThisPass = 0
    foreach ($rel in $named) {
      $abs = Join-Path $gitDir ($rel -replace '/', '\')
      if (-not (Test-Path $abs)) { if ($blockersKept -notcontains $rel) { $blockersKept += $rel }; continue }

      $tracked = (& git -C $gitDir ls-files --error-unmatch -- $rel 2>$null | Out-String).Trim()
      $isGenerated = ($rel -like 'journal/index/*') -or ($rel -like 'journal/state/*')

      $diskHash = ((& git -C $gitDir hash-object -- $abs 2>$null) | Out-String).Trim()
      $incoming = ((& git -C $gitDir rev-parse "$syncRemote/$branch`:$rel" 2>$null) | Out-String).Trim()

      $clear = $false
      if ($tracked -and $isGenerated) { $clear = $true }
      elseif (-not $tracked -and $incoming -and $diskHash -eq $incoming) { $clear = $true }

      if (-not $clear) {
        if ($blockersKept -notcontains $rel) { $blockersKept += $rel }
        continue
      }

      if (-not $bkRootMade) { New-Item -ItemType Directory -Force -Path $bkRoot | Out-Null; $bkRootMade = $true }
      $dest = Join-Path $bkRoot ($rel -replace '/', '\')
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
      Copy-Item $abs $dest -Force
      $srcHash = (Get-FileHash $abs -Algorithm SHA256).Hash
      $dstHash = (Get-FileHash $dest -Algorithm SHA256).Hash
      if ($srcHash -ne $dstHash) { if ($blockersKept -notcontains $rel) { $blockersKept += $rel }; continue }  # backup unproven => do not move it

      $manifest.Add(("{0}`t{1}`tsha256={2}" -f $rel, $(if ($tracked) { 'generated' } else { 'identical-to-incoming' }), $srcHash))

      $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
      if ($tracked) { & git -C $gitDir checkout -- $rel 2>&1 | Out-Null }
      else { Remove-Item $abs -Force -ErrorAction SilentlyContinue }
      $ErrorActionPreference = $prevEap
      if ($blockersCleared -notcontains $rel) { $blockersCleared += $rel }
      $clearedThisPass++
    }
    if ($clearedThisPass -eq 0) { break }
  }

  if ($manifest.Count -gt 0) {
    $manifest | Set-Content -Path (Join-Path $bkRoot 'manifest.tsv') -Encoding utf8
    Log ("  cleared {0} non-work blocker(s); preserved at {1}" -f $manifest.Count, $bkRoot)
  }
}

if ($behind -gt 0) {
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  if ($syncRemote -eq 'origin') {
    $pull = (& git -C $gitDir -c core.autocrlf=false pull --ff-only 2>&1)
  } else {
    # Already fetched from the mirror; fast-forward explicitly onto it. Origin is NOT
    # consulted here, because origin is the host that is down (item 367).
    $pull = (& git -C $gitDir -c core.autocrlf=false merge --ff-only "$syncRemote/$branch" 2>&1)
  }
  $pullOk = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $prevEap
  if (-not $pullOk) {
    # A refused pull is now a REAL finding: step 2c already cleared everything git could prove was
    # not work, so whatever is left is a modified file the incoming commits also touch, or an
    # untracked file that DIFFERS from the incoming blob. Name them, so the next session does not
    # have to rediscover the set by hand.
    $kept = if ($blockersKept.Count -gt 0) { ' Blocking path(s), left untouched: ' + (($blockersKept | Select-Object -First 6) -join ', ') } else { '' }
    Record ([ordered]@{
        result          = 'attention'
        detail          = "pull --ff-only refused with $behind commit(s) to take:$kept"
        repo            = $gitDir; branch = $branch
        behind          = $behind; ahead = $ahead
        blockers_cleared = $blockersCleared.Count
        blockers_kept    = $blockersKept.Count
        git             = ($pull | Select-Object -Last 3) -join ' | '
      })
    exit 1
  }
}

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 3. Apply to ~/.dsh - from the COMMITTED tree, not from the working tree.
#
#    Why: this file first refused to apply while tracked files were modified. That was safe but it made
#    the sync useless on these machines, where several agent sessions hold files modified most of the
#    day - ZABZ-YOGA sat on `dirty` while four files belonging to other sessions blocked every apply, so
#    committed config changes reached the *repo* and never reached the live `~/.dsh`. That is precisely
#    the drift this job exists to remove (PAIN P8).
#
#    The scheduled job's contract is "converge the live config to the committed source of truth". A
#    half-written file in someone's editor is not the source of truth, so the apply now runs against a
#    snapshot of HEAD exported to a temp directory: committed changes land, and nobody's in-flight work
#    is published or lost. A dirty tree is still *reported* - it is useful to know - but it no longer
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
  #
  # -cmatch, NOT -match (fixed 2026-09-28). PowerShell's -match is case-INSENSITIVE, so this test also
  # matched sync.py's two installer lines -- "client plugins: would run install-client-plugins.ps1" and
  # "metrics sampler: would run Install-MetricsSampler.ps1" -- which are reported on EVERY run, in both
  # modes, because a dry run cannot know whether an installer is already satisfied. Measured on
  # ZABZ-TECH: "apply did NOT converge" was reported 290 times between 2026-09-16 and this fix, and the
  # machine was unable to report `clean` at all after a successful pull. sync.py's own wording
  # distinguishes the two cases deliberately: an upper-case WOULD CHANGE / WOULD UPDATE / WOULD CREATE
  # is a pending write; a lower-case "would run <installer>" is an installer it cannot evaluate.
  $verify = (& $python (Join-Path $snapshot 'scripts\sync.py') --dry-run 2>&1)
  $verifyOk = ($LASTEXITCODE -eq 0) -and -not ($verify -cmatch 'WOULD')
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

# A step that SKIPPED is NOT a converged step. sync.py's version-coupling guard skips the
# presets and the profiles steps, on purpose, when the repo names a plugin the running engine
# does not provide - and until this line existed, a machine whose whole preset pipeline was
# skipped reported exactly what a healthy machine reports: `clean / nothing to apply`.
# Measured 2026-10-04 on ZABZ-TECH: presets and profiles had been skipped for six days while
# every tick said clean, and new-session creation was broken the whole time.
# Deliberately NOT part of the convergence test: sync.py avoids the word WOULD in a skip
# message because autosync treats WOULD as did-not-converge and would stall every tick.
$skippedLines = @($apply | Where-Object { $_ -match 'SKIPPED' } | ForEach-Object { ($_ -replace '^\s+', '').Trim() })
$skipped = if ($skippedLines.Count -gt 0) { ($skippedLines -join ' | ') } else { '' }
$skipNote = if ($skipped) { "; SKIPPED (not applied): $skipped" } else { '' }
$applied = if ($changedLines.Count -gt 0) { ($changedLines -join ' | ').Trim() } else { 'nothing to apply' }

# --------------------------------------------------------------------------
# 4. Send commits that are already made but never pushed. Never force.
#
#    Normally a backstop: step 2b already pushed (and warned) when $ahead -gt 0. Kept because the
#    apply above can only be published if the tree is on the right commit, and because a push that
#    failed transiently in step 2b deserves one more attempt in the same run.
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
$viaNote = if ($syncRemote -ne 'origin') { "; synced via non-secratary mirror '$syncRemote' (origin down)" } else { '' }
Record ([ordered]@{
    result                  = $result
    detail                  = if ($verifyOk) { "at $commit; $applied; pushed=$pushed$viaNote$skipNote" }
                              else { "apply did NOT converge - a second run still reports pending changes" }
    repo                    = $gitDir
    branch                  = $branch
    commit                  = $commit
    behind                  = $behind
    ahead                   = $ahead
    pushed                  = $pushed
    apply                   = $applied
    converged               = $verifyOk
    # Added 2026-10-05 with $skipNote: a skipped step is named on every outcome, so a frozen
    # pipeline cannot read as a healthy one. '' means measured and none.
    skipped                 = $skipped
    synced_via              = $syncRemote
    # Added 2026-09-28 with step 2c: a run that removed files from the working tree must say so on
    # every outcome, not only when the pull happened to fail. 0 means measured and none.
    blockers_cleared        = @($blockersCleared).Count
    blockers_kept           = @($blockersKept).Count
    local_commits_preserved = $preserved
    preserved_ref           = $preservedRef
  })

if ($verifyOk) { exit 0 } else { exit 1 }
