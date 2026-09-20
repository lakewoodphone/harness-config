<#
.SYNOPSIS
Ensure every local client plugin listed in a DSH profile's bundle list actually resolves, and
say so when one does not.

WHY THIS EXISTS
`scripts/sync.py` copies presets, settings and the profile patch layer into ~/.dsh. It does
NOT install plugin packages, and the profile's own package.json -- the bundle list the loader
mounts -- is machine-local and not in git. So a machine rebuilt from harness-config, or a
node_modules directory that gets rebuilt, silently loses them.

That is not hypothetical. On 2026-09-11 the fleet engine refused to boot:

    3099-20260911-154536.err.log
    Error: dsh: cannot resolve profile bundle "dsh-plugin-cost" from the dsh
    installation or C:\Users\ezabz\.dsh\profiles\web

and plugin-windows had to be copied into the profile by hand twice from another session, once
leaving a stale 3636-byte client.js in place. DECISIONS D38 already names the rule for the
phone plugin -- "a component that can silently disappear needs a keeper, not a procedure" --
and `serve-phone.sh` is that keeper for plugin-mobile. This script is the same keeper for every
package under packages/.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
The invariant that matters is: **every name in the bundle list resolves.** A package that is in
`packages/` but not in the bundle list is reported as information, not as a fault -- mounting
it is somebody's decision, and a check that cries wolf about a deliberate choice gets ignored.
Pass -RequireAll to treat those as faults too.

THE SECOND HALF OF THAT INVARIANT, ADDED 2026-09-17 AFTER IT BIT US
Resolving is not sufficient: the name must also DECLARE A BUNDLE. `packages/` contains bundles and
plain programs (`mesh-broker`, `deepseek-proxy` -- a service with a `bin`, no `dsh` key at all), and
the loader mounts every declared name as a patch layer, throwing on any that declares no
`dsh.bundle.patch`. This script used to enrol every package it could link, so the moment
`packages/mesh-broker` existed the next sync made two machines unbootable -- live on ZABZ-YOGA and
ZABZ-TECH, both found on 2026-09-17 with `dsh --profile web --dump-config` exit 1 while the running
engines looked perfectly healthy. Enrolment is now gated on `dsh.bundle.patch`, and a declared name
that fails the test is REMOVED from the list rather than left to fail the next boot. Verified both
ways: the check fails on the pre-repair profile and passes after it.

WHY A JUNCTION RATHER THAN A COPY
A package may resolve by name from the repo checkout (a junction) or from a copy in
node_modules. A copy drifts the moment the package is edited, and the drift is invisible: the
repo and the running engine disagree with no error. Measured on ZABZ-TECH 2026-09-11, both
installed packages were copies. A junction makes the checkout the only copy, so an edit is live
without a reinstall. Junctions are used rather than symlinks because Windows grants symlink
creation only to an elevated shell or Developer Mode, while a directory junction needs neither.

USAGE
    pwsh scripts/install-client-plugins.ps1 -Check      # report only; exit 1 if a bundle is broken
    pwsh scripts/install-client-plugins.ps1             # install/repair, idempotent
    pwsh scripts/install-client-plugins.ps1 -RequireAll # also install repo-only packages

Exit codes: 0 every bundle resolves - 1 a bundle does not resolve (or a package is repo-only
under -RequireAll) - 2 the profile could not be read.

After a bundle-list change, reload the profile (`patchReload: live` usually means a page
reload) or restart the engine.
#>
[CmdletBinding()]
param(
    # The DSH profile to install into. Defaults to $DSH_HOME/profiles/web.
    [string]$ProfileDir,

    # Report what is wrong and change nothing.
    [switch]$Check,

    # Also install packages that exist under packages/ but are not in the bundle list.
    [switch]$RequireAll
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot

# NEVER LINK INTO A TRANSIENT SNAPSHOT. Measured 2026-09-16 on BOTH machines, and it took the
# desktop's engine down and left the laptop one restart away from the same fate.
#
# `autosync` applies harness-config from a SNAPSHOT of HEAD under %LOCALAPPDATA%\Temp
# (`harness-config-snap-<timestamp>`) rather than from the working tree -- a deliberate property,
# so a dirty tree is neither published nor lost. But when it runs THIS script from there, `$repo`
# IS the snapshot, so every junction this script created pointed into a directory that was deleted
# minutes later. The links then dangle: `Test-Path <link>/package.json` is false and
# `require.resolve` from the profile fails with MODULE_NOT_FOUND, so the engine cannot resolve its
# own bundles and refuses to boot at all:
#
#     Error: dsh: cannot resolve profile bundle "dsh-plugin-cost" ...
#
# The trigger is any restart AFTER a sync -- which is why a reboot produced it. A junction must
# point at the checkout, the only copy that persists, no matter where the script was invoked from.
$checkout = Join-Path $env:USERPROFILE 'code\harness-config'
if ($repo -like "$env:TEMP*" -and (Test-Path (Join-Path $checkout 'packages'))) {
    Write-Host "note: invoked from a temp snapshot ($repo)"
    Write-Host "      linking to the checkout instead ($checkout) -- a junction into %TEMP% dangles"
    $repo = $checkout
}
$dshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
if (-not $ProfileDir) { $ProfileDir = Join-Path $dshHome 'profiles\web' }

$pkgRoot = Join-Path $repo 'packages'
$manifest = Join-Path $ProfileDir 'package.json'
$modules = Join-Path $ProfileDir 'node_modules'

if (-not (Test-Path $manifest)) {
    Write-Error "no profile manifest at $manifest -- is DSH installed and is the profile name right?"
    exit 2
}

# Read the bundle list once; it is what the loader mounts.
$config = Get-Content $manifest -Raw | ConvertFrom-Json
$bundles = @()
if ($config.dsh -and $config.dsh.profile -and $config.dsh.profile.bundles) {
    $bundles = @($config.dsh.profile.bundles)
}

# Every packages/plugin-* directory that declares a name.
#
# `Bundle` IS THE FACT THAT DECIDES ENROLMENT, and it was missing (2026-09-17). A profile's
# `dsh.profile.bundles` is not a dependency list: every name in it is mounted as a patch LAYER, and
# the loader THROWS on a name whose package declares no `dsh.bundle.patch` --
#
#     Error: dsh: profile bundle "dsh-mesh-broker" declares no dsh.bundle in its package.json
#       at dsh-app-boot/lib/index.js:852
#
# so ONE such name stops the engine booting at all. `packages/` holds both kinds of thing: bundles
# (`dsh-plugin-*`) and plain programs with a `bin` that are started as their own process
# (`mesh-broker`, `deepseek-proxy`). This script used to enrol every package it could link, so as
# soon as `packages/mesh-broker` existed, a sync armed a machine that could not come back -- measured
# live on ZABZ-YOGA (manifest written 23:47, engine up since 15:49, `dsh --profile web --dump-config`
# exit 1 with the error above) and on ZABZ-TECH. The invariant this now enforces is the loader's own:
# **never name a bundle you have not just proved declares one.**
$packages = @()
if (Test-Path $pkgRoot) {
    foreach ($dir in Get-ChildItem $pkgRoot -Directory | Sort-Object Name) {
        $pkgJson = Join-Path $dir.FullName 'package.json'
        if (-not (Test-Path $pkgJson)) { continue }
        $parsed = Get-Content $pkgJson -Raw | ConvertFrom-Json
        $name = $parsed.name
        if (-not $name) { continue }
        $isBundle = [bool]($parsed.dsh -and $parsed.dsh.bundle -and $parsed.dsh.bundle.patch)
        $packages += [pscustomobject]@{ Name = $name; Source = $dir.FullName; Bundle = $isBundle }
    }
}

if ($packages.Count -eq 0) {
    Write-Host "no plugin packages found under $pkgRoot"
    exit 0
}

Write-Host "profile : $ProfileDir"
Write-Host "bundles : $($bundles.Count) declared, $($packages.Count) package(s) in the repo"
Write-Host ""

# A bundle the loader will mount but that no package here provides is not ours to fix; note it
# so the report is complete rather than quietly narrower than its claim.
$ours = $packages | ForEach-Object { $_.Name }
$foreign = $bundles | Where-Object { $ours -notcontains $_ }

$problems = 0

# PHASE 1 -- discover and repair every junction BEFORE naming anything in the manifest.
#
# WHY THE PHASES ARE SEPARATE (2026-09-16). The manifest used to be rewritten INSIDE the loop, once
# per package. So a run that established the first junction and then failed on a later one -- a
# locked file, a permission, or simply the process being killed -- left `dsh.profile.bundles` naming
# a bundle that could not resolve, and the engine then refused to boot at all:
#
#     Error: dsh: cannot resolve profile bundle "dsh-plugin-attention"
#
# That happened for real on ZABZ-TECH, it took twenty minutes to diagnose because every
# process-level signal (port, pid, MCP counts) looked fine, and the machine's own engine watchdog
# could not repair it (it kept replaying the same deterministic failure). The invariant that
# prevents the whole class is simple and is now enforced: **never name a bundle you have not just
# proved resolves.** Junctions first, manifest second, once, and only names that resolved.
$status = @{}
foreach ($pkg in $packages) {
    $target = Join-Path $modules $pkg.Name
    $kind = 'MISSING'
    if (Test-Path $target) {
        $item = Get-Item $target -Force
        $isLink = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
        $first = if ($item.Target) { $item.Target | Select-Object -First 1 } else { $null }
        if ($isLink -and $first -eq $pkg.Source) { $kind = 'LINK' }
        elseif ($isLink) { $kind = 'LINK-ELSEWHERE' }
        else { $kind = 'COPY' }
    }

    if ($kind -ne 'LINK' -and -not $Check) {
        # Repair: a junction to the checkout, so the profile and the repo cannot diverge.
        try {
            if (Test-Path $target) { Remove-Item $target -Recurse -Force -ErrorAction Stop }
            New-Item -ItemType Junction -Path $target -Target $pkg.Source -ErrorAction Stop | Out-Null
            $kind = 'LINK'
        } catch {
            Write-Host ("      ! could not link {0}: {1}" -f $pkg.Name, $_.Exception.Message)
        }
    }
    $status[$pkg.Name] = $kind
}

# PHASE 2 -- report, and rewrite the manifest ONCE with only the names that resolve AND declare a
# bundle. A package that is linked but declares no `dsh.bundle.patch` is NEVER enrolled: naming it
# would stop the engine booting (see the note above `$packages`).
$resolved = @($packages | Where-Object { $status[$_.Name] -eq 'LINK' -and $_.Bundle } | ForEach-Object { $_.Name })
$unresolved = @($packages | Where-Object { $status[$_.Name] -ne 'LINK' -or -not $_.Bundle } | ForEach-Object { $_.Name })

foreach ($pkg in $packages) {
    $kind = $status[$pkg.Name]
    $inBundles = $bundles -contains $pkg.Name
    if (-not $pkg.Bundle) {
        $note = if ($inBundles) { 'declares no dsh.bundle -- REMOVING from the bundle list (naming it stops the engine booting)' }
                else { 'declares no dsh.bundle -- linked, never named as a bundle' }
        Write-Host ("  {0,-24} {1,-14} {2}" -f $pkg.Name, $kind, $note)
        continue
    }
    if (-not $inBundles -and -not $RequireAll) {
        Write-Host ("  {0,-24} {1,-14} not mounted (repo-only; -RequireAll to install)" -f $pkg.Name, $kind)
        continue
    }
    $ok = ($kind -eq 'LINK')
    if (-not $ok -and $inBundles) { $problems++ }   # a NAMED bundle that cannot resolve is the hazard
    Write-Host ("  {0,-24} {1,-14} bundles={2,-6} {3}" -f $pkg.Name, $kind, $inBundles, $(if ($ok) { 'ok' } else { 'NEEDS FIX' }))
}

if (-not $Check) {
    # Drop from the bundle list anything we just failed to make resolvable, and add what we did.
    $wanted = @($bundles | Where-Object { $unresolved -notcontains $_ })
    $added = @($resolved | Where-Object { $wanted -notcontains $_ })
    if ($added.Count -gt 0 -or $wanted.Count -ne $bundles.Count) {
        if (-not $config.dsh) { $config | Add-Member -NotePropertyName dsh -NotePropertyValue ([pscustomobject]@{}) }
        if (-not $config.dsh.profile) { $config.dsh | Add-Member -NotePropertyName profile -NotePropertyValue ([pscustomobject]@{}) }
        $config.dsh.profile | Add-Member -NotePropertyName bundles -NotePropertyValue @($wanted + $added) -Force
        $json = $config | ConvertTo-Json -Depth 20
        [System.IO.File]::WriteAllText($manifest, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
        if ($added.Count -gt 0) { Write-Host ("      added to bundles: {0}" -f ($added -join ', ')) }
        if ($wanted.Count -ne $bundles.Count) {
            Write-Host ("      REMOVED from bundles (either it would not resolve, or it declares no dsh.bundle -- naming it would stop the engine booting): {0}" -f (($bundles | Where-Object { $unresolved -contains $_ }) -join ', '))
        }
    }
}

if ($foreign.Count -gt 0) {
    Write-Host ""
    Write-Host "also in the bundle list, not from packages/ (left alone): $($foreign -join ', ')"
}

Write-Host ""
if ($Check) {
    if ($problems -gt 0) {
        Write-Host "$problems bundle(s) will not resolve. Run without -Check to fix."
        exit 1
    }
    Write-Host "every mounted bundle resolves"
    exit 0
}

Write-Host "done. Reload the profile (or restart the engine) for a bundle change to take effect."
exit 0
