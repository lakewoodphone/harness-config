# journal-daily.ps1 — write one handoff entry per day from a manager workstation.
#
# THE OWNER'S REQUIREMENT (2026-09-15): her machines must keep their own journal, handoff notes and
# pain points, evolving, and hold whatever needs HER attention -- not merely be able to read the
# owner's. This is the mechanism, and it is a scheduled job on purpose: a journal that depends on the
# model choosing to write it stops existing the first busy day.
#
# WHAT IT PRODUCES, and why each part is there:
#   * CHANGED   -- what actually moved in the shop's repos in the last day, read from git rather than
#                  remembered, so the entry is evidence instead of a claim.
#   * NEEDS ATTENTION -- the contents of `attention/` beside this journal. That folder is how work that
#                  needs HER (not the agent) gets surfaced instead of buried in a chat.
#   * OPEN PAIN -- left for the agent to append to, with the command shown so it knows how.
#   * NEXT      -- likewise.
#
# PROVENANCE: every entry carries the hostname it was written on. That is the owner's rule for her
# machines -- labelled, not restricted -- and it is what keeps her notes distinguishable from the
# owner's in the shared journal.
#
# Entry location: the harness-config checkout's journal, which is the one place in this fleet that
# already survives a session and is readable by later sessions on every machine. If this machine can
# reach the remote it publishes the entry; if not, the entry stays local and that is acceptable -- it
# is still there for the next session on this machine.
[CmdletBinding()]
param(
  [string]$Repo = '',
  [switch]$Quiet
)

$ErrorActionPreference = 'Continue'

if (-not $Repo) {
  foreach ($c in @(
      (Join-Path $env:USERPROFILE 'code\harness-config'),
      (Join-Path $env:USERPROFILE 'Code\harness-config'),
      (Join-Path $env:USERPROFILE 'harness-config'))) {
    if (Test-Path (Join-Path $c 'journal\tools\journal.py')) { $Repo = $c; break }
  }
}
if (-not $Repo -or -not (Test-Path (Join-Path $Repo 'journal\tools\journal.py'))) {
  Write-Output 'journal-daily: harness-config journal not found; nothing written'
  exit 1
}

$JournalPy = Join-Path $Repo 'journal\tools\journal.py'
$Machine = $env:COMPUTERNAME
$lines = New-Object System.Collections.Generic.List[string]

# --- CHANGED: what moved, read from git ------------------------------------------------------
$lines.Add('## Changed')
$lines.Add('')
$anyChange = $false
foreach ($name in @('lpt-hub', 'personal-secretary-mvp')) {
  foreach ($seg in @('code', 'Code', '')) {
    $r = if ($seg) { Join-Path $env:USERPROFILE "$seg\$name" } else { Join-Path $env:USERPROFILE $name }
    if (-not (Test-Path (Join-Path $r '.git'))) { continue }
    $recent = & git -C $r log --since='26 hours ago' --format='- %h %s' 2>$null | Select-Object -First 5
    if ($recent) {
      $anyChange = $true
      $lines.Add("- ${name}:")
      $recent | ForEach-Object { $lines.Add("  $_") }
    }
    break
  }
}
if (-not $anyChange) { $lines.Add('- no commits in the shop repos in the last day') }

# --- NEEDS ATTENTION: the folder that exists so her items are not lost ------------------------
$lines.Add('')
$lines.Add('## Needs attention')
$lines.Add('')
$attDir = Join-Path $Repo 'journal\attention'
$att = @()
if (Test-Path $attDir) {
  $att = Get-ChildItem $attDir -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 15
}
if ($att.Count -gt 0) { $att | ForEach-Object { $lines.Add("- $($_.Name)") } }
else { $lines.Add('- nothing filed for her attention') }

# --- OPEN PAIN / NEXT: the agent's job, with the command shown --------------------------------
$lines.Add('')
$lines.Add('## Open pain')
$lines.Add('')
$lines.Add("- (agent: append with  python journal.py append pain --title ""..."" --body-file <file>)")
$lines.Add('')
$lines.Add('## Next')
$lines.Add('')
$lines.Add('- (agent: fill this in as you work)')

$bodyFile = Join-Path ([IO.Path]::GetTempPath()) "journal-body-$Machine.md"
[IO.File]::WriteAllText($bodyFile, ($lines -join "`r`n"), (New-Object Text.UTF8Encoding($false)))

$title = "Daily note from $Machine"
if (-not $Quiet) { Write-Output "journal-daily: appending '$title'" }
& python $JournalPy append handoff --title $title --body-file $bodyFile 2>&1 | ForEach-Object { Write-Output $_ }
Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue

# --- publish if this machine can reach the remote ---------------------------------------------
Push-Location $Repo
try {
  $dirty = & git status --porcelain -- journal 2>$null
  if ($dirty) {
    & git add journal 2>$null
    & git -c user.name='Yocheved (manager)' -c user.email='yocheved@abletelsolutions.com' `
        commit -q -m "journal: daily handoff from $Machine" 2>&1 | Select-Object -First 2 | ForEach-Object { Write-Output $_ }
    $push = & git push origin HEAD 2>&1 | Select-Object -Last 2
    if ($push) { $push | ForEach-Object { Write-Output $_ } }
    else { Write-Output "journal-daily: entry committed locally (remote not reachable)" }
  } else {
    Write-Output 'journal-daily: nothing new to publish'
  }
} finally { Pop-Location }
