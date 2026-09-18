# provision-mcp-tools.ps1 -- install the MCP servers the preset points at, once per machine.
#
# WHY THIS EXISTS
# The preset launches each MCP server as `node <absolute path>` (no `npx`, no `cmd` shim, no
# registry round trip on every start -- see docs/dsh-at-scale/70-toolcall-latency.md). That makes
# the install location part of the deployment: on a machine where `~/.dsh/tools/mcp` does not
# exist, every one of those rows points at nothing and the servers silently do not start
# (`failOnStartupError: false` is deliberate, so nothing blocks the preset).
#
# Measured 2026-09-16: ZABZ-TECH was in exactly that state -- `npx commands=0` in the preset but
# `stable install present=False` -- while ZABZ-YOGA had it. So it is a per-machine provisioning
# step, and it belongs in a script a machine can run, not in someone's memory.
#
# Idempotent: if the entry points are already there it does nothing (use -Force to reinstall).
#
# USAGE
#   pwsh -NoProfile -File scripts/provision-mcp-tools.ps1
#   pwsh -NoProfile -File scripts/provision-mcp-tools.ps1 -Force

param([switch]$Force)

$ErrorActionPreference = 'Stop'
$dst = Join-Path $env:USERPROFILE '.dsh\tools\mcp'
$packages = @('mcp-fetch-server', 'firecrawl-mcp', 'mcp-remote', '@upstash/context7-mcp', '@playwright/mcp')

# The entry points the preset names, relative to the install root.
$entries = @(
    'node_modules\mcp-fetch-server\dist\index.js',
    'node_modules\@playwright\mcp\cli.js',
    'node_modules\firecrawl-mcp\dist\index.js',
    'node_modules\mcp-remote\dist\proxy.js',
    'node_modules\@upstash\context7-mcp\dist\index.js'
)

$missing = @($entries | Where-Object { -not (Test-Path (Join-Path $dst $_)) })
if ($missing.Count -eq 0 -and -not $Force) {
    Write-Host "provision-mcp-tools: already provisioned at $dst"
    exit 0
}

Write-Host "provision-mcp-tools: installing $($packages.Count) packages into $dst"
Write-Host ("  missing entry points: {0}" -f ($missing -join ', '))
New-Item -ItemType Directory -Force -Path $dst | Out-Null
& npm install --prefix $dst --no-audit --no-fund --loglevel=error @packages
if ($LASTEXITCODE -ne 0) { Write-Error "npm install failed with exit $LASTEXITCODE"; exit 1 }

$still = @($entries | Where-Object { -not (Test-Path (Join-Path $dst $_)) })
if ($still.Count) {
    Write-Error ("installed, but these entry points are still missing: {0}" -f ($still -join ', '))
    exit 1
}
Write-Host "provision-mcp-tools: all 5 entry points present -- restart the DSH profile so the rows mount"
exit 0
