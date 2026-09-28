# fleet-profile-gate.ps1 - ONE command that says whether every machine's engine can boot.
#
# WHY. On 2026-09-17 a defect that stops an engine booting (`dsh-mesh-broker` named in a profile's
# bundle list) was repaired on the three machines the repairing session could see: ZABZ-YOGA,
# ZABZ-TECH and lakewooechsmini. Yocheved's laptop was never on that list. It rebooted on
# 2026-09-18 and could not come back FOR TEN DAYS, because a profile is only read at START, so a
# running engine proves nothing and the machine looked merely idle.
#
# The lesson was "verify a fleet fix by ABSENCE OF THE DEFECT on every machine, not by listing the
# machines you repaired". This is the command that does that, and this list of machines is a
# TARGET LIST, not a source of truth: every machine that appears in it is checked, and a machine
# that cannot be reached is reported as UNREACHABLE rather than quietly omitted — an unreachable
# machine is precisely where a silent outage hides.
#
# It does NOT need an engine anywhere. `dsh --profile <p> --dump-config` composes the layers and
# starts nothing, so it works on the machine whose engine is dead — the whole point.
#
# USAGE
#   pwsh -File scripts/fleet-profile-gate.ps1
#   pwsh -File scripts/fleet-profile-gate.ps1 -Json
#   pwsh -File scripts/fleet-profile-gate.ps1 -Only secratary,zabz-tech

[CmdletBinding()]
param(
    [string[]] $Only,
    [switch]   $Json,
    [int]      $TimeoutSec = 60
)

$ErrorActionPreference = 'Continue'
$repoGate = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\profile-gate.mjs'
$ssh = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
if (-not (Test-Path $ssh)) { $ssh = 'ssh' }

# Each target: how to reach it, and the remote path of the gate + how to invoke node there.
# `npm`-style paths are per machine and were measured, not guessed.
$targets = @(
    [pscustomobject]@{
        Machine = 'zabz-yoga'; Kind = 'local'
        Node    = (Get-Command node -ErrorAction SilentlyContinue).Source
        Gate    = $repoGate
    }
    [pscustomobject]@{
        Machine = 'zabz-tech'; Kind = 'ssh'; Host = 'desktop-ts'
        Node    = 'node'
        Gate    = 'C:\Users\ezabz\code\harness-config\scripts\profile-gate.mjs'
    }
    [pscustomobject]@{
        Machine = 'secratary'; Kind = 'ssh'; Host = 'secratary-ts'
        Node    = 'node'
        Gate    = '/home/zabz/code/harness-config/scripts/profile-gate.mjs'
    }
    [pscustomobject]@{
        Machine = 'lakewooechsmini'; Kind = 'ssh'; Host = 'mac-mini-ts'
        Node    = 'node'
        Gate    = '/Users/lpt/code/harness-config/scripts/profile-gate.mjs'
    }
)

if ($Only) { $targets = $targets | Where-Object { $Only -contains $_.Machine } }

$rows = @()
foreach ($t in $targets) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $raw = $null
    $err = $null
    try {
        if ($t.Kind -eq 'local') {
            $raw = & $t.Node $t.Gate --json 2>&1 | Out-String
        } else {
            $raw = & $ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10 $t.Host `
                        "$($t.Node) $($t.Gate) --json" 2>&1 | Out-String
        }
    } catch { $err = $_.Exception.Message }
    $sw.Stop()

    $verdict = 'UNREACHABLE'; $detail = ($err, ($raw -replace '\s+', ' ')).Where({ $_ }) -join ' '
    if ($raw) {
        try {
            # The gate prints one JSON document; take the outermost object.
            $start = $raw.IndexOf('{'); $end = $raw.LastIndexOf('}')
            if ($start -ge 0 -and $end -gt $start) {
                $doc = ($raw.Substring($start, $end - $start + 1)) | ConvertFrom-Json
                $verdict = $doc.verdict
                $bad = @($doc.profiles | Where-Object { -not $_.ok })
                $detail = if ($bad.Count -eq 0) { "$(@($doc.profiles).Count) profile(s) compose" }
                          else { ($bad | ForEach-Object { "$($_.profile): $($_.failure)" }) -join ' | ' }
                $detail += "  [via node $($doc.nodeVersion)]"
            }
        } catch { $detail = "could not parse the gate's output: " + ($raw -replace '\s+', ' ') }
    }
    $rows += [pscustomobject]@{
        Machine = $t.Machine
        Verdict = $verdict
        Ms      = $sw.ElapsedMilliseconds
        Detail  = $detail.Trim()
    }
}

$bad = @($rows | Where-Object { $_.Verdict -ne 'ok' })

if ($Json) {
    [pscustomobject]@{ checkedAt = (Get-Date).ToString('o'); machines = $rows; problems = $bad.Count } | ConvertTo-Json -Depth 5
} else {
    Write-Host ''
    Write-Host ("FLEET PROFILE GATE  {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'))
    Write-Host '  "ok" means every profile on that machine COMPOSES, so its engine can start.'
    Write-Host '  A running engine is never consulted: the profile is read at boot, so a live engine proves nothing.'
    Write-Host ''
    $rows | Format-Table -AutoSize @{n='Machine';e={$_.Machine}}, @{n='Verdict';e={ if ($_.Verdict -eq 'ok') {'ok'} else {$_.Verdict} }}, @{n='ms';e={$_.Ms}}, @{n='Detail';e={$_.Detail}} | Out-String -Width 200 | Write-Host
    foreach ($r in $bad) {
        switch ($r.Verdict) {
            'CANNOT-BOOT'    { Write-Host ("  !! {0} CANNOT BOOT: {1}" -f $r.Machine, $r.Detail) -ForegroundColor Red }
            'UNREACHABLE'    { Write-Host ("  ?? {0} unreachable — NOT verified, which is not the same as healthy: {1}" -f $r.Machine, $r.Detail) -ForegroundColor Yellow }
            'no-working-harness' { Write-Host ("  ?? {0} could not be exercised (the gate checked nothing): {1}" -f $r.Machine, $r.Detail) -ForegroundColor Yellow }
            default          { Write-Host ("  ?? {0}: {1} {2}" -f $r.Machine, $r.Verdict, $r.Detail) -ForegroundColor Yellow }
        }
    }
}

# Exit non-zero only for a machine that PROVABLY cannot boot. An unreachable machine is a warning,
# not a false red: this script must never cry wolf, or it will be ignored exactly when it matters.
$cannotBoot = @($rows | Where-Object { $_.Verdict -eq 'CANNOT-BOOT' }).Count
if ($cannotBoot -gt 0) { exit 1 } else { exit 0 }
