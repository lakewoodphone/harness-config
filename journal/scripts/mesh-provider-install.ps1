<#
.SYNOPSIS
Put the remote subagent provider -- and the mesh HTTP route -- into the RESIDENT engine's profile,
verify that the engine will still boot, and be able to take it back out.

WHY THIS IS THREE FILES AND NOT ONE
`dsh-plugin-remote-fanout` registers a second named provider on `ctx.subagents` whose children are
real DSH agent turns on another node (`docs/mesh/70-remote-fanout-proof.md`), and
`dsh-plugin-mesh-http` serves `POST /mesh/run` on the node itself (`docs/mesh/83-http-transport.md`).
Both are BUNDLES, so both need a name in `<DSH_HOME>/profiles/web/package.json`. A bundle cannot
hot-mount (P210), so the last step is an engine restart -- which is why this script's job is to make
the restart SAFE, and to be checkable before it happens.

WHAT IT DOES, IN ORDER
  1. PROFILE HYGIENE. Every declared name must resolve AND declare `dsh.bundle.patch`; the loader
     throws on one that does not and the engine then cannot boot at all (`dsh-app-boot/lib/index.js`
     :831, :852). Measured live on BOTH Windows nodes 2026-09-17. Invalid names are removed.
  2. THE INVARIANT THAT KEEPS THE ENGINE BOOTABLE: `dsh-plugin-remote-fanout` may be named ONLY if
     the profile's patch layer carries its `remote-fanout` config. The provider row throws in
     `apply()` when `target` is missing (`lib/ssh-transport.js:99-101`), and a throw in a host row
     stops the boot -- so a named bundle with no config is a worse landmine than a missing feature.
     If the config is not there, the name is taken out.
  3. THE PATCH LAYER. `profiles/web/cordis.patch.yml` in the repo is the source of truth; this
     copies it to `<DSH_HOME>/profiles/web/cordis.patch.yml` (the layer the loader applies after
     every bundle layer), keeping a `.bak` of what it replaced.
  4. THE v2 SECRET. `mesh-http.mjs secret` creates the node's own secret outside the repo
     (`C:/ProgramData/dsh-mesh.env` on Windows, `/etc/dsh-mesh.env` 0640 on Linux). Never printed.
  5. THE PRESET. The `zabz` preset grants the `subagent_remote` TOOL; the deployed copy under
     `~/.dsh/.agent-presets/zabz/` is what the engine reads, so it is compared with the repo's.
  6. THE PRE-FLIGHT THAT DECIDES EVERYTHING: `dsh --profile web --dump-config` must exit 0 and the
     composed tree must contain all three rows. That command composes the bundle layers and starts
     NOTHING, so it is the one way to know the next boot will work without taking the boot.

USAGE
    pwsh scripts/mesh-provider-install.ps1 -Check        # verify only; writes nothing; exit 1 on drift
    pwsh scripts/mesh-provider-install.ps1               # apply (inert until the engine restarts)
    pwsh scripts/mesh-provider-install.ps1 -Rollback     # remove rows + names; restart to apply
    pwsh scripts/mesh-provider-install.ps1 -SkipHttp     # the provider only, no v2 secret/route

EXIT CODES: 0 every invariant holds - 1 something is unmet (under -Check, nothing was written) -
            2 this script cannot express the install (a precondition is wrong, not a defect here).

NOTHING HERE RESTARTS ANYTHING. The engine reads its profile at start; a running engine is
unaffected by every write below, and the caller decides when the restart window is.
#>
[CmdletBinding()]
param(
    # Report and change nothing.
    [switch]$Check,
    # Remove the managed rows and the bundle names, and prove the profile still composes.
    [switch]$Rollback,
    # The DSH profile directory. Defaults to $DSH_HOME/profiles/web.
    [string]$ProfileDir,
    # The harness-config checkout. Defaults to the parent of this script's directory.
    [string]$Repo,
    # Provider only: do not touch the v2 secret or the mesh-http bundle.
    [switch]$SkipHttp,
    # Do not touch the deployed preset.
    [switch]$SkipPreset
)

$ErrorActionPreference = 'Continue'

$REPO = if ($Repo) { $Repo } else { Split-Path -Parent $PSScriptRoot }
# NEVER WORK FROM A TRANSIENT SNAPSHOT. `autosync` runs from a copy of HEAD under %TEMP%; a junction
# made from there dangles minutes later and the engine stops booting (install-client-plugins.ps1:65-85).
$checkout = Join-Path $env:USERPROFILE 'code\harness-config'
if ($REPO -like "$env:TEMP*" -and (Test-Path (Join-Path $checkout 'profiles'))) { $REPO = $checkout }

$env:DSH_HOME = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
if (-not $ProfileDir) { $ProfileDir = Join-Path $env:DSH_HOME 'profiles\web' }
$manifestPath = Join-Path $ProfileDir 'package.json'
$modules = Join-Path $ProfileDir 'node_modules'
$patchRepo = Join-Path $REPO 'profiles\web\cordis.patch.yml'
$patchLive = Join-Path $ProfileDir 'cordis.patch.yml'
$presetRepo = Join-Path $REPO 'presets\zabz'
$presetLive = Join-Path $env:DSH_HOME '.agent-presets\zabz'

$PROVIDER = 'dsh-plugin-remote-fanout'
$HTTP = 'dsh-plugin-mesh-http'
$MARK_BEGIN = '>>> mesh-provider-install: BEGIN managed block'
$MARK_END = '<<< mesh-provider-install: END managed block <<<'

$problems = @()
$changed = @()
function Note([string]$text) { Write-Host "  $text" }
function Head([string]$text) { Write-Host ''; Write-Host $text }
function Problem([string]$text) { $script:problems += $text; Write-Host "  [FAIL] $text" -ForegroundColor Red }
function Did([string]$text) { $script:changed += $text; Write-Host "  [wrote] $text" -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath $manifestPath)) {
    Write-Host "no profile manifest at $manifestPath -- is DSH installed and is the profile name right?"
    exit 2
}
if (-not (Test-Path -LiteralPath $patchRepo)) {
    Write-Host "the repo has no profiles/web/cordis.patch.yml at $patchRepo -- this script has nothing to install from"
    exit 2
}

# The installation's own node_modules, where in-box bundles resolve from (loader order: installation
# anchor first, then the profile). Probed, never assumed.
$installation = $null
foreach ($probe in @(
        (Join-Path $env:USERPROFILE 'AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules'),
        (Join-Path $env:USERPROFILE 'dsh-engine\node_modules'),
        '/home/zabz/dsh-engine/node_modules')) {
    if (Test-Path -LiteralPath (Join-Path $probe '@deepseek-ai\dsh\package.json')) { $installation = $probe; break }
}
if (-not $installation) { Write-Host 'could not find the dsh installation node_modules'; exit 2 }
$dshBin = Join-Path $installation '@deepseek-ai\dsh\lib\bin.js'

function Get-ManifestPath([string]$name) {
    $local = Join-Path $modules "$name\package.json"
    if (Test-Path -LiteralPath $local) { return $local }
    $alt = Join-Path $installation "$name\package.json"
    if (Test-Path -LiteralPath $alt) { return $alt }
    return $null
}
function Get-DeclaredBundle([string]$manifestJsonPath) {
    try { return (Get-Content -LiteralPath $manifestJsonPath -Raw | ConvertFrom-Json).dsh.bundle.patch } catch { return $null }
}
function Invoke-DumpConfig {
    $out = & node $dshBin --profile web --dump-config 2>&1
    return [pscustomobject]@{ exit = $LASTEXITCODE; text = ($out -join "`n") }
}
function Save-Manifest($manifest) {
    $backup = "$manifestPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item -LiteralPath $manifestPath -Destination $backup -Force
    $manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    return $backup
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$bundles = @($manifest.dsh.profile.bundles)

# ── stages 1 and 2: hygiene, and the bundle-only-if-configured invariant ──────────────────────
Head "1. profile hygiene + the boot invariant   ($manifestPath)"
$patchText = if (Test-Path -LiteralPath $patchLive) { Get-Content -LiteralPath $patchLive -Raw } else { '' }
# Under -Check the REPO layer is the one about to be installed, so judge the invariant against it.
$patchForInvariant = if ($patchText -match [regex]::Escape($MARK_BEGIN)) { $patchText } else { Get-Content -LiteralPath $patchRepo -Raw }
$patchHasProvider = ($patchForInvariant -match "id:\s*'remote-fanout'") -and ($patchForInvariant -match 'target:')
$drop = @()
foreach ($name in $bundles) {
    $mj = Get-ManifestPath $name
    if (-not $mj) { Note "$name : UNRESOLVED"; $drop += $name; continue }
    if (-not (Get-DeclaredBundle $mj)) { Note "$name : declares no dsh.bundle"; $drop += $name; continue }
    if ($name -eq $PROVIDER -and -not $patchHasProvider) {
        Note "$name : declares a bundle but the patch layer has no remote-fanout config"
        $drop += $name
        continue
    }
    Note "$name : ok"
}
if ($drop.Count -gt 0) {
    if ($Check) {
        Problem "the bundle list names $($drop.Count) name(s) the engine cannot boot with: $($drop -join ', ')"
    } else {
        $manifest.dsh.profile.bundles = @($bundles | Where-Object { $drop -notcontains $_ })
        $bk = Save-Manifest $manifest
        Did "removed from dsh.profile.bundles: $($drop -join ', ') (backup $bk)"
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $bundles = @($manifest.dsh.profile.bundles)
    }
}

# ── stage 3: the patch layer, then the enrolment it authorises ────────────────────────────────
Head '2. the profile patch layer (the deployment config)'
if ($patchHasProvider) {
    Note "repo layer carries the remote-fanout row: $(if ($patchHasProvider) { 'yes' } else { 'no' })"
} else {
    Problem "profiles/web/cordis.patch.yml has no 'id: remote-fanout' row with a target -- without it the provider row throws at boot and the bundle must not be named"
}
$repoBytes = [System.IO.File]::ReadAllBytes($patchRepo)
$liveBytes = if (Test-Path -LiteralPath $patchLive) { [System.IO.File]::ReadAllBytes($patchLive) } else { @() }
$sameLayer = ($liveBytes.Length -eq $repoBytes.Length) -and (-not (Compare-Object $repoBytes $liveBytes -SyncWindow 0))
if ($sameLayer) { Note 'live layer == repo layer' }
elseif ($Check) { Problem "the live patch layer ($patchLive) differs from the repo's -- the engine would boot without the provider config" }
else {
    $bak = "$patchLive.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    if (Test-Path -LiteralPath $patchLive) { Copy-Item -LiteralPath $patchLive -Destination $bak -Force }
    Copy-Item -LiteralPath $patchRepo -Destination $patchLive -Force
    Did "copied the repo layer over $patchLive (backup $bak)"
}

Head '3. bundle enrolment'
foreach ($name in @($PROVIDER) + $(if ($SkipHttp) { @() } else { @($HTTP) })) {
    $mj = Get-ManifestPath $name
    if (-not $mj) {
        # Not linked yet: link it from the checkout, but ONLY if it declares a bundle.
        $dirName = $name -replace '^dsh-', ''
        $candidate = Join-Path (Join-Path $REPO 'packages') $dirName
        if (-not (Test-Path -LiteralPath (Join-Path $candidate 'package.json'))) { Problem "$name is neither installed nor in $candidate"; continue }
        if (-not (Get-DeclaredBundle (Join-Path $candidate 'package.json'))) { Problem "$candidate declares no dsh.bundle -- it must not be named as a bundle"; continue }
        if ($Check) { Problem "$name is not linked into $modules"; continue }
        New-Item -ItemType Junction -Path (Join-Path $modules $name) -Target $candidate -ErrorAction SilentlyContinue | Out-Null
        $mj = Get-ManifestPath $name
        Did "linked $name -> $candidate"
    }
    if (-not (Get-DeclaredBundle $mj)) { Problem "$name declares no dsh.bundle.patch -- refusing to name it"; continue }
    if ($bundles -notcontains $name) {
        if ($Check) { Problem "$name resolves and declares a bundle but is not in dsh.profile.bundles -- the engine will not mount it"; continue }
        $manifest.dsh.profile.bundles = @($bundles) + $name
        $bk = Save-Manifest $manifest
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $bundles = @($manifest.dsh.profile.bundles)
        Did "named $name in dsh.profile.bundles (backup $bk)"
    } else { Note "$name already named in dsh.profile.bundles" }
}

# ── stage 4: the v2 secret ────────────────────────────────────────────────────────────────────
if (-not $SkipHttp) {
    Head '4. the mesh HTTP route secret (outside the repo, never printed)'
    $httpBin = Join-Path (Join-Path $REPO 'packages\plugin-mesh-http\bin') 'mesh-http.mjs'
    if (-not (Test-Path -LiteralPath $httpBin)) { Problem "no $httpBin" }
    else {
        $secretCheck = & node $httpBin secret 2>&1 | Out-String
        $usable = ($LASTEXITCODE -eq 0)
        if ($usable) { Note "secret usable: $(($secretCheck | ConvertFrom-Json).file)" }
        elseif ($Check) { Problem "the v2 secret is not usable yet (run without -Check to create it)" }
        else {
            & node $httpBin secret 2>&1 | Out-Null
            $again = & node $httpBin secret 2>&1 | Out-String
            if ($LASTEXITCODE -eq 0) { Did "created the v2 secret at $((($again | ConvertFrom-Json).file))" } else { Problem "mesh-http.mjs secret failed: $again" }
        }
    }
}

# ── stage 5: the preset that grants the tool ──────────────────────────────────────────────────
if (-not $SkipPreset) {
    Head '5. the zabz preset (the TOOL half)'
    $gen = & python (Join-Path $REPO 'scripts\make_zabz_preset.py') --check 2>&1
    if ($LASTEXITCODE -eq 0) { Note 'make_zabz_preset.py --check: in sync' } else { Problem "the repo preset is not in sync with its generator: $($gen -join ' / ')" }
    $src = Join-Path $presetRepo 'agent.cordis.yml'
    $dst = Join-Path $presetLive 'agent.cordis.yml'
    if (-not (Test-Path -LiteralPath $src)) { Problem "no repo preset at $src" }
    elseif (-not (Test-Path -LiteralPath $dst)) { Problem "no deployed preset at $dst" }
    else {
        $srcText = Get-Content -LiteralPath $src -Raw
        if ($srcText -notmatch 'tool-subagent-remote') { Problem 'the repo preset has no tool-subagent-remote row -- the agent would have no mesh delegation tool' }
        $same = (Get-FileHash -LiteralPath $src).Hash -eq (Get-FileHash -LiteralPath $dst).Hash
        if ($same) { Note 'deployed preset == repo preset' }
        elseif ($Check) { Problem 'the deployed preset differs from the repo preset -- the engine reads the deployed copy' }
        else {
            $bak = "$dst.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
            Copy-Item -LiteralPath $dst -Destination $bak -Force
            Copy-Item -LiteralPath $src -Destination $dst -Force
            Did "deployed the repo preset over $dst (backup $bak)"
        }
    }
}

# ── stage 6: the pre-flight that decides everything ──────────────────────────────────────────
Head '6. pre-flight: will the engine boot?  (dsh --profile web --dump-config)'
$dump = Invoke-DumpConfig
if ($dump.exit -ne 0) {
    Problem "dump-config exited $($dump.exit) -- the engine would NOT come back on the next start"
    ($dump.text -split "`n" | Select-Object -First 6) | ForEach-Object { Note $_ }
} else {
    Note "dump-config exit 0, $((($dump.text -split "`n").Count)) lines composed"
    foreach ($needle in @('id: remote-fanout', 'id: tool-subagent-remote', 'id: plugin-mesh-http')) {
        if ($dump.text -match [regex]::Escape($needle)) { Note "composed: $needle" } else { Problem "the composed tree has no '$needle'" }
    }
    if ($dump.text -match '(?m)^\s*disabled: true\s*$[\s\S]{0,400}?- id: plugin-mesh-http') { Note 'host-plane tool-subagent-remote is disabled (the preset grants the tool)' }
}

# ── rollback ─────────────────────────────────────────────────────────────────────────────────
if ($Rollback) {
    Head '7. ROLLBACK'
    # THE LIVE LAYER ONLY. The repo copy is the SOURCE, and a rollback that strips the source cannot be
    # undone by this script (it would have nothing left to install from). Rolling the deployment back
    # means: the running/would-be-running configuration loses the rows, and the source keeps them until
    # somebody commits or discards them deliberately.
    foreach ($target in @($patchLive)) {
        if (-not (Test-Path -LiteralPath $target)) { continue }
        $text = Get-Content -LiteralPath $target -Raw
        if ($text -notmatch [regex]::Escape($MARK_BEGIN)) { Note "$target has no managed block -- left alone"; continue }
        $lines = $text -split "`n"
        $keep = @(); $inside = $false
        foreach ($line in $lines) {
            if ($line -match [regex]::Escape($MARK_BEGIN)) { $inside = $true; continue }
            if ($line -match [regex]::Escape($MARK_END)) { $inside = $false; continue }
            if (-not $inside) { $keep += $line }
        }
        $bak = "$target.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Copy-Item -LiteralPath $target -Destination $bak -Force
        Set-Content -LiteralPath $target -Value ($keep -join "`n") -Encoding utf8 -NoNewline
        Did "removed the managed block from $target (backup $bak)"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $names = @($manifest.dsh.profile.bundles)
    $gone = @($names | Where-Object { $_ -eq $PROVIDER -or $_ -eq $HTTP })
    if ($gone.Count -gt 0) {
        $manifest.dsh.profile.bundles = @($names | Where-Object { $gone -notcontains $_ })
        $bk = Save-Manifest $manifest
        Did "removed from dsh.profile.bundles: $($gone -join ', ') (backup $bk)"
    } else { Note 'neither bundle was named' }
    Note "the two junctions under $modules are left in place (a read-through-able link harms nothing);"
    Note "remove them with: Remove-Item '$modules\$PROVIDER','$modules\$HTTP' -Force -Recurse"
    Note "the SOURCE copy at $patchRepo still carries the rows on purpose -- this script installs from"
    Note "it, so stripping it would make its own re-install impossible. To retire them for good:"
    Note "    git -C '$REPO' checkout -- profiles/web/cordis.patch.yml   # and then commit or discard"
    $after = Invoke-DumpConfig
    Note "dump-config after rollback: exit $($after.exit)"
    if ($after.exit -ne 0) { Problem 'the profile does not compose after the rollback -- do not restart' }
}

# ── summary ──────────────────────────────────────────────────────────────────────────────────
Write-Host ''
if ($problems.Count -gt 0) {
    Write-Host "mesh-provider-install: $($problems.Count) problem(s), $($changed.Count) change(s) $($(if ($Check) { '(check only: nothing was written)' } else { '' }))" -ForegroundColor Red
    exit 1
}
Write-Host "mesh-provider-install: every invariant holds ($($changed.Count) change(s))" -ForegroundColor Green
if (-not $Check -and -not $Rollback) {
    Write-Host 'NEXT: this is INERT until the engine restarts -- a mounted bundle cannot hot-load (P210).'
    Write-Host '      The restart ends every live session in that engine, so gate it on the owner being done.'
    Write-Host "      Rollback: pwsh scripts/mesh-provider-install.ps1 -Rollback   (then restart)"
}
exit 0
