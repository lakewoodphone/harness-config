<#
.SYNOPSIS
Ensure every local client plugin under packages/ is installed into a DSH profile, and say
so when one is not.

WHY THIS EXISTS
`scripts/sync.py` copies presets, settings and the profile patch layer into ~/.dsh. It does
NOT install plugin packages, and the profile's own package.json (which lists the bundles
the loader mounts) is machine-local and not in git. So a machine rebuilt from
harness-config, or a node_modules directory that gets rebuilt, silently loses them.

That is not hypothetical. On 2026-09-11 the fleet engine refused to boot:

    3099-20260911-154536.err.log
    Error: dsh: cannot resolve profile bundle "dsh-plugin-cost" from the dsh
    installation or C:\Users\ezabz\.dsh\profiles\web

and plugin-windows had to be copied into the profile by hand twice from another session,
once leaving a stale 3636-byte client.js in place. DECISIONS D38 already names the rule for
the phone plugin -- "a component that can silently disappear needs a keeper, not a
procedure" -- and `serve-phone.sh` is that keeper for plugin-mobile. This script is the same
keeper for every package under packages/.

WHY A JUNCTION RATHER THAN A COPY
The profile may resolve a package by name from the repo checkout (a junction) or from a
copy in node_modules. A copy drifts the moment the package is edited, and the drift is
invisible: the repo and the running engine disagree with no error. A junction makes the
repo checkout the only copy, so an edit is live without a reinstall. Junctions are used
rather than symlinks because Windows grants symlink creation only to an elevated shell or
Developer Mode, while a directory junction needs neither.

USAGE
    pwsh scripts/install-client-plugins.ps1 -Check    # report only; exit 1 if any is wrong
    pwsh scripts/install-client-plugins.ps1           # install/repair, idempotent

Exit codes: 0 every package present and linked · 1 a package is missing, copied, or absent
from the bundle list · 2 could not read the profile.

After a change, reload the profile (`patchReload: live` usually means a page reload) or
restart the engine.
#>
[CmdletBinding()]
param(
    # The DSH profile to install into. Defaults to $DSH_HOME/profiles/web.
    [string]$ProfileDir,

    # Report what is wrong and change nothing.
    [switch]$Check
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$home_ = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
if (-not $ProfileDir) { $ProfileDir = Join-Path $home_ 'profiles\web' }

$pkgRoot = Join-Path $repo 'packages'
$manifest = Join-Path $ProfileDir 'package.json'

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
Write-Host "packages: $($packages.Count)"
Write-Host ""

$problems = 0
foreach ($pkg in $packages) {
    $target = Join-Path $ProfileDir "node_modules\$($pkg.Name)"
    $inBundles = $bundles -contains $pkg.Name

    # Classify: a junction to the repo is correct; anything else is a copy or absent.
    $kind = 'MISSING'
    if (Test-Path $target) {
        $item = Get-Item $target -Force
        $isLink = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
        if ($isLink -and $item.Target -and ($item.Target | Select-Object -First 1) -eq $pkg.Source) {
            $kind = 'LINK'
        } elseif ($isLink) {
            $kind = 'LINK-ELSEWHERE'
        } else {
            $kind = 'COPY'
        }
    }

    $ok = ($kind -eq 'LINK') -and $inBundles
    if (-not $ok) { $problems++ }

    $status = if ($ok) { 'ok' } else { 'NEEDS FIX' }
    Write-Host ("  {0,-24} {1,-14} bundles={2,-6} {3}" -f $pkg.Name, $kind, $inBundles, $status)

    if ($ok -or $Check) { continue }

    # Repair: replace a copy/missing entry with a junction to the checkout, then ensure the
    # loader will mount it.
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    New-Item -ItemType Junction -Path $target -Target $pkg.Source | Out-Null
    Write-Host "      linked: $target -> $($pkg.Source)"

    if (-not $inBundles) {
        # Edit the parsed object and rewrite it: no YAML/JSON parsing dependency, and the
        # rest of the manifest is preserved field for field.
        if (-not $config.dsh) { $config | Add-Member -NotePropertyName dsh -NotePropertyValue ([pscustomobject]@{}) }
        if (-not $config.dsh.profile) { $config.dsh | Add-Member -NotePropertyName profile -NotePropertyValue ([pscustomobject]@{}) }
        $newBundles = @($bundles) + $pkg.Name
        $config.dsh.profile | Add-Member -NotePropertyName bundles -NotePropertyValue $newBundles -Force
        $bundles = $newBundles
        $json = $config | ConvertTo-Json -Depth 20
        # LF, to match the rest of the repo and to keep the file diffable.
        [System.IO.File]::WriteAllText($manifest, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "      added to bundles: $($pkg.Name)"
    }
}

Write-Host ""
if ($Check) {
    if ($problems -gt 0) {
        Write-Host "$problems package(s) need repair. Run without -Check to fix." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "all $($packages.Count) package(s) linked and mounted"
    exit 0
}

Write-Host "done. Reload the profile (or restart the engine) for a bundle change to take effect."
exit 0
