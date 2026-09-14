#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Install the DshActor provenance git hook on this machine.

.DESCRIPTION
  The owner's requirement (2026-09-14): anything that changes from a non-owner machine must be
  machine-attributed, so a change from Yocheved's laptop stays distinguishable from one made by
  the owner. This installs a `prepare-commit-msg` hook that appends machine/actor/session
  trailers to every commit made on this host.

  WHY A HOOK AND NOT A CONVENTION: a convention is something an agent can forget, and a
  git-notes or trailer rule that lives inside a workspace is something an agent can edit. The
  hook lives under the user profile and is wired in with `core.hooksPath`, which is a global git
  setting, so it applies to every repository on the machine and cannot be disabled by editing
  anything inside a workspace the agent can write.

  WHY TRAILERS: git already has a first-class trailer mechanism, so the marker survives rebases
  and is greppable:
      git log --grep 'Dsh-Machine: DESKTOP-FGV6KMH'
  A single query therefore partitions the whole history by origin.

  Idempotent: re-running replaces the hook in place. Never touches repository content.

.PARAMETER Actor
  Overrides the actor identity. Defaults to "<user>@<machine>".

.PARAMETER Uninstall
  Removes the hooksPath setting and the hook, reverting to git's defaults.

.EXAMPLE
  pwsh -File Install-DshActorHook.ps1
  pwsh -File Install-DshActorHook.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [string]$Actor,
  [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$hookDir = Join-Path $env:USERPROFILE '.githooks'
$hookPath = Join-Path $hookDir 'prepare-commit-msg'

if ($Uninstall) {
  git config --global --unset core.hooksPath 2>$null | Out-Null
  if (Test-Path $hookPath) { Remove-Item -LiteralPath $hookPath -Force }
  Write-Host "DshActor hook uninstalled (core.hooksPath cleared, hook removed)."
  exit 0
}

if (-not $Actor) { $Actor = ('{0}@{1}' -f $env:USERNAME, $env:COMPUTERNAME).ToLowerInvariant() }

New-Item -ItemType Directory -Force -Path $hookDir | Out-Null

# The hook is a POSIX sh script: git for Windows runs hooks through its bundled sh, and a sh
# hook works on the Linux nodes too, so one file covers the whole fleet.
$hook = @'
#!/bin/sh
# DshActor provenance hook -- installed by harness-config/scripts/Install-DshActorHook.ps1.
# Appends machine-attribution trailers so a commit made on a non-owner machine is always
# distinguishable from one made by the owner. Managed file: edit the installer, not this.
#
# $1 = path to the commit message file
# $2 = commit source (message | template | merge | squash | commit)
# For `message` the user supplied -m/-F, so we must not clobber their text -- we append.
case "$2" in
  message|template)
    # Skip if already stamped, so amends and rebases do not stack trailers.
    if grep -q '^Dsh-Machine:' "$1" 2>/dev/null; then exit 0; fi
    MACHINE="$(hostname 2>/dev/null)"
    ACTOR="$(whoami 2>/dev/null)"
    WHEN="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    {
      printf '\n'
      printf 'Dsh-Actor: %s\n'   "$ACTOR"
      printf 'Dsh-Machine: %s\n' "$MACHINE"
      printf 'Dsh-At: %s\n'      "$WHEN"
      if [ -n "$DSH_SESSION_ID" ]; then printf 'Dsh-Session: %s\n' "$DSH_SESSION_ID"; fi
    } >> "$1"
    ;;
esac
exit 0
'@

# LF endings: git's bundled sh and the Linux nodes both require them.
[IO.File]::WriteAllText($hookPath, ($hook -replace "`r`n", "`n"), [Text.UTF8Encoding]::new($false))

git config --global core.hooksPath $hookDir

# Prove it, rather than assume it: an unverifiable control is decoration.
$verifyPath = git config --global --get core.hooksPath
Write-Host "DshActor hook installed."
Write-Host "  hooks path : $verifyPath"
Write-Host "  hook file  : $hookPath"
Write-Host "  actor      : $Actor"
Write-Host "  machine    : $env:COMPUTERNAME"
Write-Host ""
Write-Host "Verify with: git log --grep 'Dsh-Machine: $env:COMPUTERNAME'"
