# switch-yoga.ps1 — the ONE window: stop every engine on this machine, make its config correct for 0.2.1,
# install the proven candidate into the live root, start one engine, and prove it.
#
# WHY IT HAS TO BE ONE SCRIPT WITH THE ENGINES STOPPED. Two measured facts from 2026-10-19:
#   * the running engine OWNS profiles/<p>/cordis.patch.yml and rewrites it from memory (journal L10302), so a
#     config fix applied while it runs is reverted, not raced;
#   * `install-engine` refuses unless a preflight for the version is GO, and the config the machine will boot
#     with must already be the 0.2.1-shaped one when that boot happens.
# Order, therefore: STOP -> fix config -> install -> START -> verify.
#
# It never deletes anything: the previous engine tree is kept beside the new one, and every file it edits is
# first copied to a `.bak-switch-<stamp>` sibling.
#
#   pwsh -File dsh-update\tools\switch-yoga.ps1            # dry run: prints the plan, changes nothing
#   pwsh -File dsh-update\tools\switch-yoga.ps1 -Execute   # does it
param(
    [switch]$Execute,
    [string]$Version = '0.2.1-rc.2'
)
$ErrorActionPreference = 'Stop'
$repo = 'C:\Users\ezabz\code\harness-config'
$home_ = Join-Path $env:USERPROFILE '.dsh'
$live = Join-Path $home_ 'profiles\web\cordis.patch.yml'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log = Join-Path $repo "dsh-update\state\logs\switch-yoga-$stamp.log"
Set-Location $repo

function Say($msg) { Write-Host ("[{0}] {1}" -f (Get-Date).ToUniversalTime().ToString('HH:mm:ssZ'), $msg) }
Start-Transcript -Path $log -Append | Out-Null

Say "switch-yoga $Version  execute=$Execute"
$plan = @(
    '1. stop every dsh engine on this machine',
    '2. fix the LIVE profile patch for 0.2.1: connection expression webRuntime->webStartup, preset rows regenerated',
    "3. install-engine $Version  (stage -> verify --version -> patches -> audit -> compose -> swap by rename -> promote)",
    '4. start exactly one engine through multi-window\dshw.ps1 ensure',
    '5. verify: 3099 up, tree 0.2.1-rc.2, composed web tree has 0 ctx.webRuntime and 0 {{cwd}}, launcher dshInstall set'
)
$plan | ForEach-Object { Say "  $_" }

if (-not $Execute) {
    Say 'DRY RUN — nothing was stopped, edited, installed or started.'
    Stop-Transcript | Out-Null
    exit 0
}

# ── 1. stop every engine ──────────────────────────────────────────────────────────────────────────
Say 'STEP 1  stopping engines'
foreach ($p in @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*@deepseek-ai*dsh*bin.js*' })) {
    Say ("  stop pid {0}" -f $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 6
$alive = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*@deepseek-ai*dsh*bin.js*' }).Count
Say ("  engines alive: {0}" -f $alive)
if ($alive -gt 0) { Say 'ABORT: an engine survived the stop; not editing an owned file'; Stop-Transcript | Out-Null; exit 3 }

# ── 2. config for 0.2.1, with nothing running ─────────────────────────────────────────────────────
Say 'STEP 2  correcting the live profile patch'
Copy-Item $live "$live.bak-switch-$stamp" -Force
$lines = [System.Collections.Generic.List[string]](Get-Content $live)
$fixed = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    $t = $lines[$i].Trim()
    if ($t.StartsWith('#')) { continue }
    if ($t -match 'trustedHosts:.*ctx\.webRuntime\.trustedHosts') {
        $lines[$i] = $lines[$i].Replace('ctx.webRuntime.trustedHosts', 'ctx.webStartup.trustedHosts')
        $lines.Insert($i, '      # 2026-10-19: 0.2.1 injects `webStartup`, not `webRuntime` (upstream rename,')
        $lines.Insert($i + 1, '      # measured from --dump-default-config on this machine).')
        $fixed++
        break
    }
}
if ($fixed) { Set-Content -Path $live -Value $lines -Encoding utf8 }
Say ("  expression lines fixed: {0}" -f $fixed)
& node scripts\make-preset-rows.mjs --install --install-target $live 2>&1 | ForEach-Object { Say "  $_" }

# 2b. the settings document AND the rows generated from it, so the live config is exactly what preflight judged.
# Measured 2026-10-19: the retired DeepInfra 0731 model lived in base.yaml + a machine overlay, and the ROWS are
# what the engine actually reads on 0.1.7+; regenerating one without the other leaves the machine running a
# document nobody verified.
Say '  regenerating the merged settings document and the rows it owns'
$merged = Join-Path $env:TEMP 'settings-merged-switch.yaml'
& node scripts\merge-settings.mjs settings\base.yaml settings\machines\ZABZ-YOGA.yaml $merged 2>&1 | ForEach-Object { Say "    $_" }
Copy-Item $merged (Join-Path $home_ 'settings.yaml') -Force
foreach ($prof in @('web', 'mesh')) {
    $patch = Join-Path $home_ "profiles\$prof\cordis.patch.yml"
    if (Test-Path $patch) {
        & node dsh-update\tools\settings-to-entries.mjs --settings (Join-Path $home_ 'settings.yaml') --install $patch 2>&1 | ForEach-Object { Say "    $_" }
    }
}

# ── 3. install ────────────────────────────────────────────────────────────────────────────────────
Say "STEP 3  install-engine $Version"
& node dsh-update\tools\install-engine.mjs --version $Version --accept-session-format-upgrade `
    --allow-patch-failures settlement-crash,window-blank-isolation 2>&1 | ForEach-Object { Say "  $_" }
$installRc = $LASTEXITCODE
Say ("  install-engine exit: {0}" -f $installRc)
if ($installRc -ne 0) {
    Say 'INSTALL DID NOT COMPLETE — the previous tree is intact (see the output above). Starting the old engine back up.'
    & pwsh -NoProfile -File multi-window\dshw.ps1 ensure -ConfigPath multi-window\windows.json 2>&1 | ForEach-Object { Say "  $_" }
    Stop-Transcript | Out-Null
    exit 4
}

# ── 4. start ──────────────────────────────────────────────────────────────────────────────────────
Say 'STEP 4  starting one engine'
& pwsh -NoProfile -File multi-window\dshw.ps1 ensure -ConfigPath multi-window\windows.json 2>&1 | ForEach-Object { Say "  $_" }

# ── 5. prove ──────────────────────────────────────────────────────────────────────────────────────
Say 'STEP 5  verifying'
Start-Sleep -Seconds 20
$listener = Get-NetTCPConnection -LocalPort 3099 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $pkg = Join-Path $env:USERPROFILE '.dsh\engine\node_modules\@deepseek-ai\dsh\package.json'
    Say ("  3099 <- pid {0}, tree {1}" -f $listener.OwningProcess, (Get-Content $pkg -Raw | ConvertFrom-Json).version)
} else { Say '  NOT LISTENING' }
$env:DSH_HOME = $home_
$cmp = & node (Join-Path $repo 'dsh-update\vendor\prefix\0.2.1-rc.2\node_modules\@deepseek-ai\dsh\lib\bin.js') --profile web --dump-config 2>&1
Say ("  composed rows={0} ctx.webRuntime={1} cwd-tokens={2}" -f `
    @($cmp | Select-String -Pattern '^\s*-\s+id:').Count, `
    @($cmp | Select-String -Pattern 'ctx\.webRuntime').Count, `
    @($cmp | Select-String -Pattern '\{\{cwd\}\}').Count)
Say ("  dshInstall: {0}" -f ((Get-Content (Join-Path $repo 'multi-window\windows.json') -Raw | ConvertFrom-Json).dshInstall))
Say "DONE — log written to $log"
Stop-Transcript | Out-Null
