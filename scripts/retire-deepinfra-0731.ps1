# Retire the DeepInfra 0731 model from every settings layer, and stop declaring a `name` that the engine
# humanises. Measured 2026-10-19: `settings/machines/ZABZ-YOGA.yaml:15` set `name:` to the raw upstream id,
# which is why `settings-effective` reported
#   document sets models[].name = "deepseek-ai/DeepSeek-V4-Flash-0731"; engine resolved "DeepSeek V4 Flash (0731)"
# and the model itself is retired in the estate's own registry. The current DeepInfra DeepSeek is V4.1-Flash.
#
# Line-wise on purpose: it keeps the YAML valid, keeps every prose comment that mentions 0731 as history, and
# prints exactly what it removed. It refuses to touch a file whose shape it does not recognise.
$ErrorActionPreference = 'Stop'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$files = @(
    'settings\base.yaml',
    'settings\machines\ZABZ-YOGA.yaml',
    'settings\machines\DESKTOP-FGV6KMH.yaml',
    'settings\machines\LAKEWOOECHSMINI.yaml'
)
$repo = 'C:\Users\ezabz\code\harness-config'

foreach ($rel in $files) {
    $path = Join-Path $repo $rel
    if (-not (Test-Path $path)) { Write-Output "  missing $rel"; continue }
    $lines = [System.Collections.Generic.List[string]](Get-Content $path)
    $drop = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $t = $lines[$i].Trim()
        # an ENTRY, never prose: a list item whose id is the retired model
        if ($t -eq '- id: deepseek-ai/DeepSeek-V4-Flash-0731') {
            $drop += $i
            if (($i + 1) -lt $lines.Count -and $lines[$i + 1].Trim().StartsWith('name:')) { $drop += ($i + 1) }
        }
    }
    if (-not $drop.Count) { Write-Output "  $rel : no 0731 model entry (nothing to do)"; continue }
    Copy-Item $path "$path.bak-retire0731-$stamp" -Force
    foreach ($i in ($drop | Sort-Object -Descending)) { $lines.RemoveAt($i) }
    # a display name that is the raw id is the other half of the mismatch: normalise it where we can see it
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim() -eq 'name: deepseek-ai/DeepSeek-V4.1-Flash') {
            $lines[$i] = $lines[$i].Replace('deepseek-ai/DeepSeek-V4.1-Flash', 'DeepSeek V4.1 Flash')
        }
    }
    Set-Content -Path $path -Value $lines -Encoding utf8
    Write-Output ("  {0} : removed {1} line(s) -> {2}" -f $rel, $drop.Count, ($drop -join ','))
}

Write-Output '=== resulting model blocks ==='
foreach ($rel in $files) {
    $path = Join-Path $repo $rel
    if (-not (Test-Path $path)) { continue }
    $hit = (Select-String -Path $path -Pattern '^\s*- id: deepseek-ai/' | Select-Object -First 1)
    if ($hit) {
        Write-Output "  $rel"
        $l = Get-Content $path
        for ($i = $hit.LineNumber - 1; $i -lt [Math]::Min($hit.LineNumber + 3, $l.Count); $i++) { Write-Output ("    " + $l[$i].TrimEnd()) }
    }
}
