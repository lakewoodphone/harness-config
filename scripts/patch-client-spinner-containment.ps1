# patch-client-spinner-containment.ps1 — keep the spinner containment alive across installs.
#
# WHY. MEASURED 2026-10-05 on ZABZ-YOGA (docs/dsh-at-scale/97-client-per-window-cost.md): one client
# animation, `_dsh-state-dot-spin`, is essentially the whole per-window cost — a window in the
# "ongoing" state measured 0.94 core at 56.5 layouts/s, and cancelling that one animation took it to
# 0.17 core at 0.0 layouts/s, while 12 000 extra DOM nodes and a 2.3x viewport change moved neither.
# At 8 active windows that is ~8 cores against ~1.6 cores.
#
# WHERE IT MUST BE PATCHED, AND WHY NOT THE SOURCE FILE. The client consumes BUILT assets, not the
# package source: `dsh-client-ui-primitives/lib/index.js` (518 KB) carries the spinner CSS text and
# never reloads `lib/StateDot.module.css`, so an edit to the source is inert (that mistake was made and
# recorded in L3278). Exactly one served file carries both the keyframes and the spinner class:
#   dsh-web-frontend/dist/assets/index-*.css
# and that is what this script patches. It needs no engine restart — a page reload fetches it.
#
# USAGE
#   pwsh -File patch-client-spinner-containment.ps1 -Check      # 0 patchable, 2 already patched, 3 not found
#   pwsh -File patch-client-spinner-containment.ps1 -Apply
#   pwsh -File patch-client-spinner-containment.ps1 -Restore    # newest backup back
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Apply,
    [switch]$Restore,
    [string]$AssetsDir = (Join-Path $env:USERPROFILE '.dsh\engine\node_modules\@deepseek-ai\dsh-web-frontend\dist\assets')
)
$ErrorActionPreference = 'Continue'
$marker = 'harness-patch:spinner-containment'

function Get-Targets {
    if (-not (Test-Path -LiteralPath $AssetsDir)) { return @() }
    # The file that carries BOTH the keyframes and the spinner class is the one a browser loads.
    Get-ChildItem -LiteralPath $AssetsDir -File -Filter '*.css' | Where-Object {
        $t = Get-Content $_.FullName -Raw
        $t -match 'dsh-state-dot-spin' -and $t -match 'spinnerMotion'
    }
}

$targets = @(Get-Targets)
if ($targets.Count -eq 0) {
    Write-Host "NOT FOUND: no stylesheet under $AssetsDir carries both dsh-state-dot-spin and spinnerMotion"
    Write-Host "           (the client assets have changed shape — re-derive the patch rather than guessing)"
    exit 3
}

if ($Restore) {
    $n = 0
    foreach ($t in $targets) {
        $bak = Get-ChildItem -LiteralPath $t.DirectoryName -File -Filter "$($t.Name).bak-harness-*" |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($bak) { Copy-Item $bak.FullName $t.FullName -Force; Write-Host "restored $($t.Name) from $($bak.Name)"; $n++ }
    }
    if ($n -eq 0) { Write-Host 'no backup found to restore'; exit 3 }
    exit 0
}

$pending = @($targets | Where-Object { -not ((Get-Content $_.FullName -Raw) -match [regex]::Escape($marker)) })

if ($Check -or (-not $Apply)) {
    foreach ($t in $targets) {
        $patched = (Get-Content $t.FullName -Raw) -match [regex]::Escape($marker)
        Write-Host ("{0,-46} {1,8} KB  {2}" -f $t.Name, [math]::Round($t.Length / 1KB, 0), $(if ($patched) { 'PATCHED' } else { 'PENDING' }))
    }
    if ($pending.Count -eq 0) { Write-Host 'VERDICT   : ALREADY PATCHED'; exit 2 }
    Write-Host 'VERDICT   : READY TO PATCH'
    exit 0
}

foreach ($t in $pending) {
    $raw = Get-Content $t.FullName -Raw
    # Use the REAL hashed class names out of the served file: CSS-module names are hashed at build time,
    # so `.spinnerMotion` would match nothing in the asset.
    $names = [regex]::Matches($raw, '\.([A-Za-z0-9_-]*spinner(?:Motion|Track|Arc)?[A-Za-z0-9_-]*)') |
        ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
    if (@($names).Count -eq 0) { Write-Host "REFUSING: no spinner class names found in $($t.Name)"; exit 3 }
    Copy-Item $t.FullName "$($t.FullName).bak-harness-$(Get-Date -Format 'yyyyMMdd-HHmmss')" -Force
    $sel = (@($names) | ForEach-Object { ".$_" }) -join ",`n"
    $rule = "`n/* $marker — see docs/dsh-at-scale/97-client-per-window-cost.md */`n$sel { contain: layout paint; }`n"
    Add-Content -LiteralPath $t.FullName -Value $rule -Encoding utf8 -NoNewline
    $after = Get-Content $t.FullName -Raw
    Write-Host ("patched {0}: {1} class(es), {2} -> {3} chars, rulePresent={4}" -f `
        $t.Name, @($names).Count, $raw.Length, $after.Length, ($after -match 'contain:\s*layout paint'))
    Write-Host ("  classes: " + (($names | ForEach-Object { ".$_" }) -join ' '))
}
exit 0
