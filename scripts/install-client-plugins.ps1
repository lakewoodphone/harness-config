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
$packages = @()
if (Test-Path $pkgRoot) {
    foreach ($dir in Get-ChildItem $pkgRoot -Directory | Sort-Object Name) {
        $pkgJson = Join-Path $dir.FullName 'package.json'
        if (-not (Test-Path $pkgJson)) { continue }
        $name = (Get-Content $pkgJson -Raw | ConvertFrom-Json).name
        if (-not $name) { continue }
        $packages += [pscustomobject]@{ Name = $name; Source = $dir.FullName }
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
foreach ($pkg in $packages) {
    $target = Join-Path $modules $pkg.Name
    $inBundles = $bundles -contains $pkg.Name

    # Classify: a junction to the repo is correct; anything else is a copy, a foreign link, or absent.
    $kind = 'MISSING'
    if (Test-Path $target) {
        $item = Get-Item $target -Force
        $isLink = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
        $first = if ($item.Target) { $item.Target | Select-Object -First 1 } else { $null }
        if ($isLink -and $first -eq $pkg.Source) { $kind = 'LINK' }
        elseif ($isLink) { $kind = 'LINK-ELSEWHERE' }
        else { $kind = 'COPY' }
    }

    if (-not $inBundles -and -not $RequireAll) {
        # Deliberate or not, it is not mounted, so it cannot break a boot. Information only.
        Write-Host ("  {0,-24} {1,-14} not mounted (repo-only; -RequireAll to install)" -f $pkg.Name, $kind)
        continue
    }

    $ok = ($kind -eq 'LINK')
    if (-not $ok) { $problems++ }
    Write-Host ("  {0,-24} {1,-14} bundles={2,-6} {3}" -f $pkg.Name, $kind, $inBundles, $(if ($ok) { 'ok' } else { 'NEEDS FIX' }))

    if ($ok -or $Check) { continue }

    # Repair: a junction to the checkout, so the profile and the repo cannot diverge.
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    New-Item -ItemType Junction -Path $target -Target $pkg.Source | Out-Null
    Write-Host "      linked: $target -> $($pkg.Source)"

    if (-not $inBundles) {
        # Rewrite the parsed manifest: no YAML/JSON dependency, and every other field survives.
        if (-not $config.dsh) { $config | Add-Member -NotePropertyName dsh -NotePropertyValue ([pscustomobject]@{}) }
        if (-not $config.dsh.profile) { $config.dsh | Add-Member -NotePropertyName profile -NotePropertyValue ([pscustomobject]@{}) }
        $bundles = @($bundles) + $pkg.Name
        $config.dsh.profile | Add-Member -NotePropertyName bundles -NotePropertyValue $bundles -Force
        # LF, to match the rest of the repo and to keep the file diffable.
        $json = $config | ConvertTo-Json -Depth 20
        [System.IO.File]::WriteAllText($manifest, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "      added to bundles: $($pkg.Name)"
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
