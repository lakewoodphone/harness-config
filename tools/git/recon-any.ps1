# Parameterised read-only git recon. Safe: fetches only non-heroku remotes, prompting disabled.
param(
  [string]$Root = 'C:\Users\ezabz\Code',
  [string]$Out  = 'C:\Users\ezabz\Code\_scratch\git-recon\recon.tsv',
  [int]$Depth = 3
)
$ErrorActionPreference = 'Continue'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'

function Git([string]$wd, [string[]]$a) { (& git -C $wd @a 2>$null) }

function Get-Row([string]$t) {
  if ((Git $t @('rev-parse','--is-inside-work-tree')) -ne 'true') { return $null }
  $commonRaw = (Git $t @('rev-parse','--git-common-dir') | Select-Object -First 1)
  $fetchErr = ''
  foreach ($rn in @(Git $t @('remote'))) {
    $url = Git $t @('remote','get-url',$rn) | Select-Object -First 1
    if ($url -match 'heroku') { continue }
    $null = (& git -C $t fetch --prune --quiet $rn 2>&1)
    if ($LASTEXITCODE -ne 0) { $fetchErr += "$rn:fail;" }
  }
  $upstream = Git $t @('rev-parse','--abbrev-ref','--symbolic-full-name','@{u}') | Select-Object -First 1
  $ahead = ''; $behind = ''
  if ($upstream) {
    $c = Git $t @('rev-list','--left-right','--count',"$upstream...HEAD")
    if ($c) { $p = $c -split "`t"; $behind = $p[0]; $ahead = $p[1] }
  }
  [pscustomobject]@{
    path = $t
    branch = (Git $t @('rev-parse','--abbrev-ref','HEAD') | Select-Object -First 1)
    head = (Git $t @('rev-parse','--short','HEAD') | Select-Object -First 1)
    headDate = (Git $t @('log','-1','--format=%cI') | Select-Object -First 1)
    common = $commonRaw
    upstream = $upstream; ahead = $ahead; behind = $behind
    dirty = (& git -C $t status --porcelain --untracked-files=no 2>$null | Measure-Object).Count
    untracked = (& git -C $t status --porcelain --untracked-files=normal 2>$null | Where-Object { $_ -match '^\?\?' } | Measure-Object).Count
    stashes = (@(Git $t @('stash','list'))).Count
    branches = (@(Git $t @('for-each-ref','--format=%(refname:short)','refs/heads'))).Count
    fetch = $fetchErr
  }
}

$trees = New-Object System.Collections.Generic.List[string]
$trees.Add($Root)
foreach ($d in Get-ChildItem $Root -Directory -ErrorAction SilentlyContinue) {
  if ((Test-Path (Join-Path $d.FullName '.git'))) { $trees.Add($d.FullName) }
  if ($Depth -ge 2) {
    foreach ($s in Get-ChildItem $d.FullName -Directory -ErrorAction SilentlyContinue) {
      if ((Test-Path (Join-Path $s.FullName '.git'))) { $trees.Add($s.FullName) }
    }
  }
}
$rows = @()
foreach ($t in $trees) { $r = Get-Row $t; if ($r) { $rows += $r } }
$rows | ForEach-Object { ($_.PSObject.Properties | ForEach-Object { $_.Value }) -join "`t" } | Set-Content $Out -Encoding utf8
Write-Output ("{0} rows -> {1}" -f $rows.Count, $Out)
$rows | Sort-Object { [int]$_.dirty + [int]$_.untracked + [int]$_.stashes } -Descending |
  ForEach-Object { "{0,-58} {1,-34} dirty={2,-5} untr={3,-4} stash={4,-3} ahead={5,-4} behind={6,-4} {7}" -f $_.path, $_.branch, $_.dirty, $_.untracked, $_.stashes, $_.ahead, $_.behind, $_.fetch }
