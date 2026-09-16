# apply-harness-config-archive.ps1 -- put a harness-config archive onto this machine's checkout.
#
# WHY THIS EXISTS
# A machine's harness-config checkout is what `harness-sync.mjs` APPLIES from. On Yocheved's laptop that
# checkout was a dead copy: it is not a git repository (no origin to pull), and nothing refreshed it, so
# the launcher on that machine ran code from 2026-09-14 for a day and a half while the repo moved on --
# which is how a fixed launcher stayed broken. Delivery and application are two different jobs; this is
# the delivery half, and it needs no git, no SSH and no Tailscale, only a file that arrived somehow.
#
# SAFETY, and these are not negotiable
#   * ADD AND OVERWRITE ONLY. Nothing is ever deleted. Files that exist here and not in the archive --
#     a machine's own launcher wiring, its hidden-task payloads, its local scripts -- survive untouched.
#   * `journal/` IS SKIPPED ENTIRELY. The journal is one file per entry with ids allocated per machine;
#     copying a remote tree over a local one can replace an entry under the same id with different
#     content, and the journal's own rule is that an id must never mean two things. Her machine keeps
#     its own journal; harness-sync does not read it.
#   * the report says what it did, in a file, so the outcome is an artifact and not a claim.
#
# Usage:
#   pwsh -File apply-harness-config-archive.ps1 -Archive C:\path\hc.zip -Target C:\Users\cheve\code\harness-config
param(
    [Parameter(Mandatory = $true)][string]$Archive,
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$Staging = '',
    [string]$TreeId = 'unknown',
    [string]$ReportPath = ''
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Archive)) { Write-Error "archive not found: $Archive"; exit 3 }
if (-not (Test-Path -LiteralPath $Target)) { Write-Error "target checkout not found: $Target"; exit 3 }
if (-not $Staging) { $Staging = Join-Path $env:TEMP ("hc-stage-" + [guid]::NewGuid().ToString('N').Substring(0, 8)) }
if (-not $ReportPath) { $ReportPath = Join-Path $Target 'HARNESS-CONFIG-APPLIED.json' }

Write-Host ("apply: archive  = {0}" -f $Archive)
Write-Host ("apply: target   = {0}" -f $Target)
Write-Host ("apply: staging  = {0}" -f $Staging)

# A staging directory this script created and owns. Removed if it already exists, because the only way
# it exists is that a previous run of this same script made it -- never a user's directory.
if (Test-Path -LiteralPath $Staging) { Remove-Item -LiteralPath $Staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Staging | Out-Null

try {
    # ZipFile.ExtractToDirectory first: Expand-Archive is a cmdlet wrapper whose per-entry progress
    # handling makes it several times slower on a tree of ~1,600 files, and the caller's exec channel
    # has a hard 60-second cap. The fallback exists so a zip variant this cannot read still lands.
    $extracted = $false
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        if ($Archive -match '\.zip$') {
            [System.IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Staging)
            $extracted = $true
        }
    } catch {
        Write-Host ("apply: ZipFile extraction failed ({0}); falling back to Expand-Archive" -f $_.Exception.Message)
    }
    if (-not $extracted) { Expand-Archive -LiteralPath $Archive -DestinationPath $Staging -Force }

    $added = 0
    $updated = 0
    $unchanged = 0
    $skipped = 0
    $failed = @()

    # .NET copy and a .NET hasher, not the cmdlets.
    #
    # MEASURED 2026-09-15: the cmdlet version (Get-ChildItem + Get-FileHash twice + Copy-Item per file)
    # did not finish 1,584 files inside the 60-second cap of the channel that delivers the archive, so
    # no delivery could complete. Two changes fix that: the archive is built without `journal/` (the
    # harness never reads it, and copying it is the one genuinely dangerous thing this script could
    # do), and the work is done in .NET.
    #
    # EQUAL LENGTH IS NOT EQUAL CONTENT, so a length match is confirmed by hash before a file is called
    # unchanged. Skipping that check would make this script a mechanism that silently leaves a stale
    # file behind -- the exact class of fault it exists to end.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    function Get-Sha256([string]$p) {
        $fs = [System.IO.File]::OpenRead($p)
        try { return [BitConverter]::ToString($sha.ComputeHash($fs)) } finally { $fs.Dispose() }
    }

    $files = Get-ChildItem -LiteralPath $Staging -Recurse -File -Force
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($Staging.Length).TrimStart('\', '/')
        $relNorm = $rel -replace '/', '\'

        # journal/ is never copied: see the header. Also refuse anything that would escape the target.
        if ($relNorm -match '^journal\\' -or $relNorm -eq 'journal') { $skipped++; continue }
        if ($relNorm -match '\\\.\.\\' -or $relNorm -match '^\.\.') { $skipped++; continue }

        $dest = Join-Path $Target $relNorm
        $dir = Split-Path -Parent $dest
        try {
            if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            if (Test-Path -LiteralPath $dest) {
                if ((Get-Item -LiteralPath $dest).Length -eq $f.Length -and (Get-Sha256 $dest) -eq (Get-Sha256 $f.FullName)) {
                    $unchanged++
                    continue
                }
                [System.IO.File]::Copy($f.FullName, $dest, $true)
                $updated++
            } else {
                [System.IO.File]::Copy($f.FullName, $dest, $true)
                $added++
            }
        } catch {
            $failed += ("{0}: {1}" -f $relNorm, $_.Exception.Message)
        }
    }
    $sha.Dispose()

    [pscustomobject]@{
        appliedAt  = (Get-Date).ToUniversalTime().ToString('o')
        machine    = $env:COMPUTERNAME
        tree       = $TreeId
        archive    = $Archive
        target     = $Target
        added      = $added
        updated    = $updated
        unchanged  = $unchanged
        skipped    = $skipped
        failed     = $failed.Count
        failures   = $failed
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ReportPath -Encoding utf8

    Write-Host ("apply: added={0} updated={1} unchanged={2} skipped={3} failed={4}" -f $added, $updated, $unchanged, $skipped, $failed.Count)
    foreach ($x in ($failed | Select-Object -First 10)) { Write-Host ("  FAIL {0}" -f $x) }
    if ($failed.Count -gt 0) { exit 1 }
    exit 0
} finally {
    # Only the staging directory this script created.
    if (Test-Path -LiteralPath $Staging) { Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue }
}
