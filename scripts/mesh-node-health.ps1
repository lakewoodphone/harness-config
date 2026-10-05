# mesh-node-health.ps1 — keeps the mesh's node-level preconditions true, and says why when they are not.
#
# WHY THIS EXISTS: on 2026-10-05 this node lost all mesh capability because
# $DSH_HOME\profiles\node_modules had been pre-created as a JUNCTION. dsh-app-boot owns that
# directory (healProfilesModuleFallback) and mkdir on a reparse point fails with UNKNOWN (-4094),
# so every child died in ~74 ms before it could run a turn — while the transport reported
# "exit 0, no completion frame". The plugin-remote-fanout README states the rule; this task
# enforces it on the machine, every ten minutes, as SYSTEM for the services and as the user for
# the reader class that actually matters here.
#
# WINDOWS POWERSHELL 5.1 COMPATIBLE ON PURPOSE (it runs under powershell.exe from Task Scheduler):
# no `?.`, no ternary operator, no -Parallel.
#
# IT IS DELIBERATELY NARROW. It repairs exactly one thing, whose correct state is unambiguous:
# `profiles\node_modules` belongs to dsh and must not be a link. Every other reparse point is TESTED
# BY READING THROUGH IT and merely reported, because whether a link is traversable depends on the
# link's ACL owner and on the reader's logon class (docs/mesh/106-desktop-last-mile.md §1–§3) — a
# guard that "repaired" those would destroy links that are fine for the reader that matters.

$log   = "$env:USERPROFILE\.dsh\logs\mesh-node-health.log"
$state = "$env:USERPROFILE\.dsh\logs\mesh-node-health-state.json"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Get-Content $log -Tail 300 | Set-Content $log }
function Note($m) { "$((Get-Date).ToString('s')) $m" | Add-Content $log }

$profiles = Join-Path $env:USERPROFILE '.dsh\profiles'
$healed = @()
$open = @()

# 1. THE RULE — dsh owns profiles\node_modules; a link there breaks every child's boot.
$parent = Join-Path $profiles 'node_modules'
$parentIsLink = $false
if (Test-Path -LiteralPath $parent) {
  $item = Get-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue
  if ($item -and $item.LinkType) {
    $parentIsLink = $true
    cmd /c ('rmdir "' + $parent + '"') | Out-Null
    if (Test-Path -LiteralPath $parent) {
      $open += "profiles\node_modules is a " + $item.LinkType + " and could not be removed"
    } else {
      $healed += "removed the " + $item.LinkType + " at profiles\node_modules (dsh recreates it as a directory on the next profile boot); its target was " + ($item.Target -join ',')
    }
  }
}

# 2. REPORT every other link under profiles\*\node_modules, tested by reading through it.
$checked = @()
foreach ($p in (Get-ChildItem $profiles -Force -Directory -ErrorAction SilentlyContinue)) {
  $nm = Join-Path $p.FullName 'node_modules'
  if (-not (Test-Path -LiteralPath $nm)) { continue }
  foreach ($l in (Get-ChildItem $nm -Force -Directory -ErrorAction SilentlyContinue)) {
    if (-not $l.LinkType) { continue }
    $text = (cmd /c ('type "' + $l.FullName + '\package.json" 2>&1') | Out-String)
    $verdict = 'unreadable'
    if ($text -match 'untrusted mount point') { $verdict = 'UNTRUSTED' }
    elseif ($text -match 'File Not Found|cannot find the path') { $verdict = 'DANGLING' }
    elseif ($text -match '"name"|"version"|"main"|"exports"') { $verdict = 'ok' }
    $checked += [ordered]@{ link = $l.FullName; verdict = $verdict }
    if ($verdict -ne 'ok') { $open += ('link ' + $l.Name + ': ' + $verdict) }
  }
}

# 3. State, plus one trail line whenever anything changed.
$prev = $null
if (Test-Path $state) { try { $prev = Get-Content $state -Raw | ConvertFrom-Json } catch { $prev = $null } }
[ordered]@{
  time                     = (Get-Date).ToString('o')
  linksChecked             = $checked.Count
  healed                   = $healed
  needsAttention           = $open
  links                    = $checked
  profilesNodeModulesIsLink = $parentIsLink
} | ConvertTo-Json -Depth 5 | Set-Content $state
if ($healed.Count -or $open.Count) { Note ('HEALED: ' + ($healed -join '; ') + ' || OPEN: ' + ($open -join '; ')) }
$wasOpen = ''
if ($prev) { $wasOpen = ($prev.needsAttention -join '|') }
if ((-not $prev) -or ($prev.linksChecked -ne $checked.Count) -or ($wasOpen -ne ($open -join '|'))) {
  Note ('links=' + $checked.Count + ' open=' + $open.Count + ' healed=' + $healed.Count)
}
