# Fetch-free recon from an explicit path list (no directory enumeration, which hangs on this machine).
# Emits one TSV row per repository, streaming, so partial output survives a hang.
param([Parameter(Mandatory=$true)][string]$List)
$ErrorActionPreference = 'Continue'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
Write-Output "path`tbranch`thead`theadDate`tupstream`tdirty`tuntracked`tstashes`tbranches`tcommon"
foreach ($line in (Get-Content -LiteralPath $List)) {
  $t = $line.Trim()
  if (-not $t) { continue }
  if (-not (Test-Path -LiteralPath (Join-Path $t '.git'))) { continue }
  $branch = (& git -C $t rev-parse --abbrev-ref HEAD 2>$null | Select-Object -First 1)
  $head = (& git -C $t rev-parse --short HEAD 2>$null | Select-Object -First 1)
  $headDate = (& git -C $t log -1 --format=%cI 2>$null | Select-Object -First 1)
  $upstream = (& git -C $t rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null | Select-Object -First 1)
  $dirty = ((& git -C $t status --porcelain --untracked-files=no 2>$null | Measure-Object).Count)
  $untracked = ((& git -C $t status --porcelain --untracked-files=normal 2>$null | Where-Object { $_ -match '^\?\?' } | Measure-Object).Count)
  $stashes = (@(& git -C $t stash list 2>$null)).Count
  $branches = (@(& git -C $t for-each-ref --format='%(refname:short)' refs/heads 2>$null)).Count
  $common = (& git -C $t rev-parse --git-common-dir 2>$null | Select-Object -First 1)
  Write-Output (@($t, $branch, $head, $headDate, $upstream, $dirty, $untracked, $stashes, $branches, $common) -join "`t")
}
