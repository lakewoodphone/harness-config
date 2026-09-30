# Fetch-free read-only recon: prints TSV to stdout. Used where a fetch is too slow or has no credential.
param([string]$Root = 'C:\Users\ezabz\Code', [int]$Depth = 2)
$ErrorActionPreference = 'Continue'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
function Git([string]$wd, [string[]]$a) { (& git -C $wd @a 2>$null) }
$out = New-Object System.Collections.Generic.List[string]
$out.Add("path`tbranch`thead`theadDate`tupstream`tdirty`tuntracked`tstashes`tbranches`tcommon")
$trees = New-Object System.Collections.Generic.List[string]
foreach ($d in Get-ChildItem $Root -Directory -ErrorAction SilentlyContinue) {
  if (Test-Path (Join-Path $d.FullName '.git')) { $trees.Add($d.FullName) }
  if ($Depth -ge 2) {
    foreach ($s in Get-ChildItem $d.FullName -Directory -ErrorAction SilentlyContinue) {
      if (Test-Path (Join-Path $s.FullName '.git')) { $trees.Add($s.FullName) }
    }
  }
}
foreach ($t in $trees) {
  if ((& git -C $t rev-parse --is-inside-work-tree 2>$null) -ne 'true') { continue }
  $out.Add((@(
    $t,
    (Git $t @('rev-parse','--abbrev-ref','HEAD') | Select-Object -First 1),
    (Git $t @('rev-parse','--short','HEAD') | Select-Object -First 1),
    (Git $t @('log','-1','--format=%cI') | Select-Object -First 1),
    (Git $t @('rev-parse','--abbrev-ref','--symbolic-full-name','@{u}') | Select-Object -First 1),
    ((& git -C $t status --porcelain --untracked-files=no 2>$null | Measure-Object).Count),
    ((& git -C $t status --porcelain --untracked-files=normal 2>$null | Where-Object { $_ -match '^\?\?' } | Measure-Object).Count),
    (@(Git $t @('stash','list'))).Count,
    (@(Git $t @('for-each-ref','--format=%(refname:short)','refs/heads'))).Count,
    (Git $t @('rev-parse','--git-common-dir') | Select-Object -First 1)
  ) -join "`t"))
}
$out | ForEach-Object { $_ }
