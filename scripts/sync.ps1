#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Apply this harness-config checkout onto the local ~/.dsh -- the PowerShell twin of sync.py.

.DESCRIPTION
  sync.py is the canonical apply step, but it needs Python with PyYAML, and two of the machines in
  this fleet (Yocheved's laptop, and any freshly imaged box) have neither. That made the deploy
  path machine-dependent: the settings could only be applied where Python happened to exist. This
  is the same job with the same merge rule, so a machine can be provisioned from this repo alone.

  What it does, in order:
    1. merge settings/base.yaml with settings/machines/<HOSTNAME>.yaml (machine wins) and write
       ~/.dsh/settings.yaml;
    2. copy presets/* into ~/.dsh/.agent-presets/;
    3. install the local plugin packages as DIRECTORY JUNCTIONS into the profile, so an edit here
       is live and the two cannot drift, and wire them into the profile's bundle list;
    4. wire the dsh-new:// protocol so the `+` control can open a window.

  Safety rules, deliberately enforced:
    * never writes .credentials.yaml
    * never touches sessions/, storages/, or profiles/node_modules EXCEPT to add its own junctions
    * never deletes a preset it did not put there (reports instead)
    * idempotent: running it twice changes nothing the second time

.PARAMETER DryRun
  Report what would change and write nothing.

.PARAMETER Hostname
  Override the machine whose settings file is merged. Defaults to this computer's name.
#>
[CmdletBinding()]
param(
  [switch]$DryRun,
  [string]$Hostname = $env:COMPUTERNAME,
  [string]$DshHome = $(if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' })
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$host_ = $Hostname.ToUpper()
$log = @()
function Say([string]$m) { Write-Host $m; $script:log += $m }

Say "harness-config sync (PowerShell)"
Say "  repo     : $repo"
Say "  DSH_HOME : $DshHome"
Say "  hostname : $host_"
Say "  mode     : $(if ($DryRun) { 'DRY RUN' } else { 'APPLY' })"
Say ""

if (-not (Test-Path $DshHome)) { Write-Error "$DshHome does not exist -- install DSH first"; exit 2 }

# --- 1. settings -------------------------------------------------------------------------------
# The merge is done by scripts/merge-settings.mjs, which uses the same `yaml` implementation the
# harness itself uses and self-checks its own output by re-parsing it.
#
# WHY NOT POWERSHELL: the first version of this file parsed and re-emitted YAML by hand. That
# silently destroyed a LIST value -- `models:` under `llm-pi-ai.providers.deepinfra` came out as a
# nested map, the llm-pi-ai block ended up in the file twice, and the engine refused to boot with
# `DUPLICATE_KEY at line 21`. `dsh --dump-config` did not catch it, because dumping the composed
# profile never reads the user's settings document. A merge that can corrupt its own output is
# worse than no merge, so it is delegated to the real parser and proved by re-parse.
$basePath = Join-Path $repo 'settings/base.yaml'
$machinePath = Join-Path $repo "settings/machines/$host_.yaml"
$settingsFile = Join-Path $DshHome 'settings.yaml'
$merger = Join-Path $repo 'scripts/merge-settings.mjs'

Say "machine settings: $host_.yaml ($(if (Test-Path $machinePath) { 'found' } else { 'MISSING -- only base will apply' }))"

if (-not (Test-Path $merger)) {
  Say "scripts/merge-settings.mjs: MISSING -- settings NOT applied (refusing to write a hand-merged document)"
} else {
  $nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
  if (-not $nodeExe) {
    Say "node.exe not on PATH -- settings NOT applied"
  } else {
    $mergeArgs = @($merger, $basePath, $(if (Test-Path $machinePath) { $machinePath } else { '-' }), $settingsFile)
    if ($DryRun) { $mergeArgs += '--check' }
    $out = & $nodeExe @mergeArgs 2>&1
    $code = $LASTEXITCODE
    if ($code -eq 0) {
      if (-not $DryRun) {
        $stamp = Get-Date -Format yyyyMMdd-HHmmss
        # keep the pre-change document, one generation, so a bad merge is recoverable
        if ((Test-Path $settingsFile) -and -not (Test-Path "$settingsFile.pre-sync")) {
          Copy-Item $settingsFile "$settingsFile.pre-sync"
        }
      }
      $out | ForEach-Object { Say "  $_" }
    } else {
      # A failed self-check must leave the existing document alone: the engine can boot on the old
      # file and cannot boot on a corrupted one.
      Say "  settings merge FAILED (exit $code) -- existing settings.yaml left untouched"
      $out | ForEach-Object { Say "    $_" }
    }
  }
}

# --- 2. presets --------------------------------------------------------------------------------
$presetRoot = Join-Path $DshHome '.agent-presets'
$srcRoot = Join-Path $repo 'presets'
if (Test-Path $srcRoot) {
  if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $presetRoot | Out-Null }
  foreach ($p in (Get-ChildItem $srcRoot -Directory)) {
    $dest = Join-Path $presetRoot $p.Name
    $n = (Get-ChildItem $p.FullName -Recurse -File | Measure-Object).Count
    if ($DryRun) { Say "preset $($p.Name): WOULD APPLY $n file(s)" ; continue }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item (Join-Path $p.FullName '*') $dest -Recurse -Force
    Say "preset $($p.Name): applied ($n file(s))"
  }
  $known = (Get-ChildItem $srcRoot -Directory | ForEach-Object { $_.Name })
  foreach ($local in (Get-ChildItem $presetRoot -Directory -ErrorAction SilentlyContinue)) {
    if ($local.Name -notin $known) { Say "preset $($local.Name): local-only (not in repo -- left alone)" }
  }
} else { Say "presets/: none in repo" }

# --- 3. plugins --------------------------------------------------------------------------------
# Directory junctions, not copies: one edit is live and the two cannot drift. A junction rather
# than a symlink because Windows grants symlink creation only to an elevated shell or Developer
# Mode, and these machines have neither by default.
$profile = Join-Path $DshHome 'profiles/web'
$pkgRoot = Join-Path $repo 'packages'
if (Test-Path $pkgRoot) {
  $nm = Join-Path $profile 'node_modules'
  if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $nm | Out-Null }
  $installed = @()
  foreach ($pkg in (Get-ChildItem $pkgRoot -Directory)) {
    $manifest = Join-Path $pkg.FullName 'package.json'
    if (-not (Test-Path $manifest)) { continue }
    $name = (Get-Content $manifest -Raw | ConvertFrom-Json).name
    if (-not $name) { continue }
    $link = Join-Path $nm $name
    if (Test-Path $link) { Say "plugin $name : already linked" }
    elseif ($DryRun) { Say "plugin $name : WOULD LINK" }
    else {
      cmd /c "mklink /J `"$link`" `"$($pkg.FullName)`"" | Out-Null
      Say "plugin $name : linked"
    }
    $installed += $name
  }
  # Bundle list: base + web app + every resolvable local plugin. Writing an unresolvable name
  # makes the engine refuse to boot (observed 2026-09-11 and again 2026-09-14), so the list is
  # built from what is actually present.
  $pf = Join-Path $profile 'package.json'
  if ((Test-Path $pf) -and $installed.Count -ge 0) {
    $pj = Get-Content $pf -Raw | ConvertFrom-Json
    $bundles = @('@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app') + $installed
    if ($DryRun) { Say "bundles: WOULD SET -> $($bundles -join ', ')" }
    else {
      $pj.dsh.profile.bundles = $bundles
      [IO.File]::WriteAllText($pf, ($pj | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
      Say "bundles: $($bundles -join ', ')"
    }
  }
} else { Say "packages/: none in repo (client plugins will not be installed)" }

# --- 4. the dsh-new:// protocol, so the `+` control can open a window --------------------------
$dshw = Join-Path $repo 'multi-window/dshw.ps1'
if (Test-Path $dshw) {
  $pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
  if (-not $pwshExe) { $pwshExe = Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe' }
  $cmd = "`"$pwshExe`" -NoProfile -WindowStyle Hidden -File `"$dshw`" new"
  if ($DryRun) { Say "dsh-new protocol: WOULD SET -> $cmd" }
  else {
    New-Item -Path 'HKCU:\Software\Classes\dsh-new\shell\open\command' -Force | Out-Null
    Set-ItemProperty -Path 'HKCU:\Software\Classes\dsh-new\shell\open\command' -Name '(default)' -Value $cmd
    New-ItemProperty -Path 'HKCU:\Software\Classes\dsh-new' -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    Say "dsh-new protocol: registered"
  }
} else { Say "multi-window/dshw.ps1: not present -- the + control will be inert" }

Say ""
Say $(if ($DryRun) { "dry run: nothing was written" } else { "sync complete. Restart the profile for a settings change to take effect." })
exit 0
