<#
.SYNOPSIS
  Refuse to deliver a preset or profile that names a plugin the installed engine does not have.

.DESCRIPTION
  Why this exists, measured 2026-09-29. The presets and profile patches were moved to the
  0.1.7-era plugin names on 2026-09-28 15:32, but the engine on this machine was still
  0.1.5-rc.1 and had never been promoted (dsh-update/FINDINGS.md:314 - "Nothing has been
  promoted"). Ten rows across five files named three packages that do not exist in the
  installed engine:

      dsh-workflow-ptc, dsh-agent-preset, dsh-agent-preset-registry

  The result was not an error message. `POST /api/session/create` answered **HTTP 200** with an
  error in the RPC body - `agent-preset/invalid`, "preset \"zabz\" failed to mount" - which the
  client swallows while resetting the workspace picker, so the visible symptom was "a new DSH
  window cannot choose a workspace and the composer never becomes a textbox". The config was
  applied, `scripts/sync.ps1` reported success, and the engine was unusable.

  So the check belongs where the delivery happens: a rename is version-coupled, and applying it
  against the wrong engine breaks preset mounting. This runs BEFORE anything is copied.

  It compares the package names in the repo against the packages actually present under
  $DSH_HOME\profiles\node_modules\@deepseek-ai - the same tree the engine resolves from, not a
  guess about which version is installed.

  Comment lines are skipped on purpose: the files document the other naming on purpose, and a
  comment cannot break a mount.

.PARAMETER Root
  The harness-config checkout to check. Defaults to the parent of this script's directory.

.PARAMETER DshHome
  The DSH home whose installed packages are authoritative. Defaults to $env:DSH_HOME, else
  $env:USERPROFILE\.dsh.

.PARAMETER Quiet
  Print only problems and the verdict.

.EXAMPLE
  pwsh -File preset-package-gate.ps1
  pwsh -File preset-package-gate.ps1 -Root C:\tmp\candidate
#>
[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$DshHome = $(if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }),
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'

$modulesRoot = Join-Path $DshHome 'profiles\node_modules\@deepseek-ai'
if (-not (Test-Path -LiteralPath $modulesRoot)) {
    Write-Host "preset-package-gate: cannot see the installed engine at $modulesRoot - this is a REFUSAL, not a pass." -ForegroundColor Yellow
    exit 3
}

$installed = @{}
Get-ChildItem -LiteralPath $modulesRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $installed[$_.Name] = $true }

# NOT `Join-Path $Root 'presets', Join-Path $Root 'profiles'` - that form passes the second
# Join-Path as another positional argument to the first and yields ONE malformed path, so $dirs
# came back empty and the first two versions of this gate reported "OK - 0 file(s)". Parenthesise
# each call.
$dirs = @(
    (Join-Path $Root 'presets'),
    (Join-Path $Root 'profiles')
) | Where-Object { Test-Path -LiteralPath $_ }
# Deliberately NOT `-Include '*.yml','*.yaml'`: with -LiteralPath that silently matched nothing and
# the first version of this gate reported "OK - 0 package reference(s) in 0 file(s)", which is the
# defect the gate exists to catch. Filter on the extension instead, and assert the scan is non-empty
# below, so it can never pass by scanning nothing again.
$files = @(
    foreach ($d in $dirs) {
        Get-ChildItem -LiteralPath $d -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in '.yml', '.yaml' }
    }
)

if ($files.Count -eq 0) {
    Write-Host "preset-package-gate: found no preset or profile files under $Root - this is a REFUSAL, not a pass." -ForegroundColor Yellow
    exit 3
}

$problems = @()
$rows = 0
foreach ($f in $files) {
    $n = 0
    foreach ($line in [System.IO.File]::ReadAllLines($f.FullName)) {
        $n++
        if ($line.TrimStart().StartsWith('#')) { continue }
        foreach ($m in [regex]::Matches($line, '@deepseek-ai/([A-Za-z0-9._-]+)')) {
            $rows++
            $pkg = $m.Groups[1].Value
            if (-not $installed.ContainsKey($pkg)) {
                $rel = $f.FullName.Substring($Root.Length).TrimStart('\', '/')
                $problems += "  ${rel}:${n}  names @deepseek-ai/$pkg - NOT INSTALLED in this engine"
            }
        }
    }
}

if (-not $Quiet) {
    Write-Host ("preset-package-gate: {0} package reference(s) in {1} file(s) checked against {2}" -f $rows, $files.Count, $modulesRoot)
}

if ($problems.Count -eq 0) {
    Write-Host ("preset-package-gate: OK - every named package resolves ({0} installed)" -f $installed.Count) -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "preset-package-gate: FAILED - these rows name packages this engine does not have." -ForegroundColor Red
Write-Host "A rename is version-coupled: delivering these breaks preset mounting, and the failure" -ForegroundColor Red
Write-Host "reaches the user as 'a new window cannot choose a workspace' rather than as an error." -ForegroundColor Red
$problems | ForEach-Object { Write-Host $_ -ForegroundColor Red }
Write-Host ""
Write-Host "Either pin the rows to the installed engine's names, or promote the engine first" -ForegroundColor Red
Write-Host "(dsh-update does both together; the session-log format upgrade is one-way)." -ForegroundColor Red
exit 1
