$ErrorActionPreference = 'Continue'
$r         = "C:\Users\ezabz\code\harness-config"
$movedRoot = "C:\Users\ezabz\code\_journal-backup-20260916b\moved"
$journal   = Join-Path $r 'journal'

Write-Output "=== 1. classify every moved entry ==="
$restore = @()
$collide = @()
$same    = 0
foreach ($f in Get-ChildItem $movedRoot -Recurse -File) {
    $rel    = $f.FullName.Substring($movedRoot.Length + 1)
    $target = Join-Path $journal $rel
    if (-not (Test-Path $target)) { $restore += [pscustomobject]@{ rel = $rel; src = $f.FullName } }
    else {
        $a = (Get-FileHash $f.FullName -Algorithm SHA256).Hash
        $b = (Get-FileHash $target    -Algorithm SHA256).Hash
        if ($a -eq $b) { $same++ } else { $collide += [pscustomobject]@{ rel = $rel; src = $f.FullName; target = $target } }
    }
}
Write-Output ("  restore (id free)      : " + $restore.Count)
Write-Output ("  identical already      : " + $same)
Write-Output ("  COLLISION (id taken)   : " + $collide.Count)
$collide | ForEach-Object { Write-Output ("     collision: " + $_.rel) }

Write-Output ""
Write-Output "=== 2. restore the ones whose id is free ==="
foreach ($x in $restore) {
    $target = Join-Path $journal $x.rel
    New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
    Copy-Item $x.src $target -Force
}
Write-Output ("  restored: " + $restore.Count)

Write-Output ""
Write-Output "=== 3. clear the merge conflict on the generated index ==="
git -C $r checkout HEAD -- journal/index/entries.tsv 2>&1
Write-Output "  took HEAD's generated index (journal.py rebuilds it when stale)"

Write-Output ""
Write-Output "=== 4. record the collisions for re-append ==="
$collide | ConvertTo-Json | Set-Content "C:\Users\ezabz\.dsh-network\journal-collisions.json" -Encoding utf8
Write-Output ("  wrote C:\Users\ezabz\.dsh-network\journal-collisions.json (" + $collide.Count + " entries)")

Write-Output ""
Write-Output "=== 5. status ==="
git -C $r status --short 2>&1 | Where-Object { $_ -notmatch '^\?\? _scratch' } | Select-Object -First 12
