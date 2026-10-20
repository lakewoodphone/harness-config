# Apply tonight's two config fixes to THIS machine's repo checkout and live home.
#
# The same two changes were made by hand on ZABZ-TECH at 22:49 and 22:58Z:
#   1. `connection` row: `!!js ctx.webRuntime.trustedHosts` -> `ctx.webStartup.trustedHosts`
#      (0.2.1 renamed the injected service; 0.2.0 injects webRuntime, 0.2.1 injects webStartup)
#   2. persona suffix: `Your working directory is {{cwd}}.` -> a `pwd` instruction
#      (0.2.1 registers only provider and model as prompt variables)
# and then the preset rows were regenerated into the profile patch, because on 0.1.7+ the
# `.agent-presets` DIRECTORY is not read: the mounted rows are what a session gets.
#
# SCOPE: the repo checkout and the live config files. NO engine change. The live profile patch is only
# rewritten if --include-live is passed, because on a machine still running 0.2.0 the old expression is
# the CORRECT one and flipping it early breaks the running engine's client.
param([switch]$IncludeLive)
$ErrorActionPreference = 'Stop'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$repo = 'C:\Users\ezabz\code\harness-config'

function Fix-Connection([string]$file) {
    if (-not (Test-Path $file)) { Write-Output "  missing $file"; return }
    $lines = [System.Collections.Generic.List[string]](Get-Content $file)
    $idx = @()
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -eq 'trustedHosts: !!js ctx.webRuntime.trustedHosts,') { $idx += $i } }
    if ($idx.Count -eq 0) { Write-Output "  connection row already fixed in $file"; return }
    if ($idx.Count -ne 1) { Write-Output "  REFUSED $file : $($idx.Count) expression lines"; return }
    Copy-Item $file "$file.bak-webstartup-$stamp" -Force
    $lines[$idx[0]] = $lines[$idx[0]].Replace('ctx.webRuntime.trustedHosts', 'ctx.webStartup.trustedHosts')
    $lines.Insert($idx[0], '      # 2026-10-19: 0.2.1 injects `webStartup`, not `webRuntime` (upstream rename,')
    $lines.Insert($idx[0] + 1, '      # measured from --dump-default-config). The old name throws inside the loader.')
    Set-Content -Path $file -Value $lines -Encoding utf8
    Write-Output "  connection row fixed in $file"
}

function Fix-Cwd([string]$file) {
    if (-not (Test-Path $file)) { return }
    $lines = [System.Collections.Generic.List[string]](Get-Content $file)
    $idx = @()
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i].TrimEnd() -eq '    suffix: Your working directory is {{cwd}}.') { $idx += $i } }
    if ($idx.Count -eq 0) { return }
    if ($idx.Count -ne 1) { Write-Output "  REFUSED $file : $($idx.Count) suffix lines"; return }
    Copy-Item $file "$file.bak-cwdvar-$stamp" -Force
    $lines[$idx[0]] = '    suffix: Run `pwd` in your shell for the working directory; never assume a path.'
    $lines.Insert($idx[0], '    # 2026-10-19: 0.2.1 registers only `provider` and `model` as prompt variables; `{{cwd}}`')
    $lines.Insert($idx[0] + 1, '    # failed every turn with  unknown prompt variable "{{cwd}}" in section "deployment:persona-suffix".')
    Set-Content -Path $file -Value $lines -Encoding utf8
    Write-Output "  persona suffix fixed in $file"
}

$targets = @()
$targets += (Join-Path $repo 'profiles\web\cordis.patch.yml')
$presetDirs = @(Join-Path $repo 'presets')
if ($IncludeLive) {
    $targets += (Join-Path $env:USERPROFILE '.dsh\profiles\web\cordis.patch.yml')
    $presetDirs += (Join-Path $env:USERPROFILE '.dsh\.agent-presets')
}

Write-Output '=== connection expression ==='
foreach ($t in $targets) { Fix-Connection $t }
Write-Output '=== preset persona suffix ==='
foreach ($root in $presetDirs) {
    foreach ($d in (Get-ChildItem $root -Directory -ErrorAction SilentlyContinue)) {
        Fix-Cwd (Join-Path $d.FullName 'agent.cordis.yml')
    }
}

Write-Output '=== regenerate the preset rows (repo) ==='
Push-Location $repo
node scripts\make-preset-rows.mjs --install 2>&1 | Select-Object -Last 3
if ($IncludeLive) {
    Write-Output '=== regenerate the preset rows (live profile patch) ==='
    node scripts\make-preset-rows.mjs --install --install-target (Join-Path $env:USERPROFILE '.dsh\profiles\web\cordis.patch.yml') 2>&1 | Select-Object -Last 3
}
node scripts\make-preset-rows.mjs --check 2>&1 | Select-Object -Last 2
Pop-Location
