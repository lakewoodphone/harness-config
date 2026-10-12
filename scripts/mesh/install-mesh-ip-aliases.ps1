<#
.SYNOPSIS
  install-mesh-ip-aliases.ps1 - install the ADDRESS-SPELLING ssh aliases the mesh fallback
  needs, idempotently, and print the exact command that removes them again.

.DESCRIPTION
  WHY THIS EXISTS (measured 2026-10-12, doc 187).

  A mesh dispatch today resolves its worker through exactly ONE name, and every one of those
  names is a tailnet MagicDNS name: packages/plugin-remote-fanout/lib/nodes.js maps
  zabz-tech->`desktop-ts`, zabz-yoga-1->`laptop-ts`, zabz-tech-linux->`linux-pc-ts`,
  secratary->`secratary-ts`, lakewooechsmini->`mac-mini-ts`. If MagicDNS stops answering,
  every one of those names stops resolving and the whole fleet leaves at once - and that is
  not hypothetical on this estate:

    * `~/.ssh/config` already carries a standing note that on 2026-09-28 18:18-18:32Z MagicDNS
      for `secratary.tail93e6e6.ts.net` failed FOUR TIMES while the Tailscale service was up
      and the peer was `active; relay nyc`. That incident is why `secratary-ip` exists.
    * This script generalises that one hand-made fix to every node, because the fix was
      applied to one node by hand and the reasoning was never extended.

  WHAT IT ADDS, and why an ALIAS rather than a bare address. A bare `ssh 192.168.50.77`
  carries no account, so it tries the LOCAL user and is refused on a box whose account is
  `zabz` or `lpt`. Measured 2026-10-12: that false negative made a first draft of
  scripts/mesh/route-mesh.ps1 report three healthy LAN paths as dead. The alias carries the
  user AND the key, which is the entire reason `-ts` and `-lan` aliases exist.

  SAFETY. This changes ONE file, `~/.ssh/config`, in this user's home directory. It starts,
  stops, restarts and reconfigures NOTHING - no service, no Tailscale, no cloudflared, no DNS
  record. It is idempotent (a block that is already present is left alone) and reversible (it
  prints the removal command, and `-Remove` performs it). A backup of the previous file is
  written next to it before the first change.

.EXAMPLE
  .\install-mesh-ip-aliases.ps1 -DryRun     # show the block, change nothing
  .\install-mesh-ip-aliases.ps1             # install (idempotent)
  .\install-mesh-ip-aliases.ps1 -Remove     # remove the managed block
#>
[CmdletBinding()]
param(
  [switch]$DryRun,
  [switch]$Remove
)
$ErrorActionPreference = 'Stop'

$BEGIN = '# >>> mesh address-spelling aliases (doc 187) >>>'
$END   = '# <<< mesh address-spelling aliases (doc 187) <<<'

# ---------------------------------------------------------------------------
# Every address below was READ from `tailscale status --json` on zabz-tech on 2026-10-12,
# and every one of them answered an ssh `exit 0` from that machine on that date. Users are
# not guessed: `zabz` on the Linux boxes, `ezabz` on the Windows boxes, `lpt` on the Mac
# mini, `root` on the authority - each confirmed by the connection that succeeded.
# ---------------------------------------------------------------------------
$Aliases = @(
  @{ Name='desktop-ts-ip';          HostName='100.85.153.96';  User='ezabz'; Note='zabz-tech, the office desktop, by tailnet address' }
  @{ Name='desktop-lan';            HostName='192.168.50.138'; User='ezabz'; Note='zabz-tech, office LAN' }
  @{ Name='secratary-ip';           HostName='100.84.72.88';   User='zabz';  Note='the FROZEN office box by tailnet address (name already exists; listed so this block is self-contained)' }
  @{ Name='secratary-lan';          HostName='192.168.50.77';  User='zabz';  Note='the FROZEN office box on the office LAN (name already exists)' }
  @{ Name='linux-pc-lan';           HostName='192.168.50.23';  User='zabz';  Note='zabz-tech-linux, office LAN' }
  @{ Name='linux-pc-ts-ip';         HostName='100.105.248.90'; User='zabz';  Note='zabz-tech-linux by tailnet address' }
  @{ Name='laptop-ts-ip';           HostName='100.72.162.5';   User='ezabz'; Note='zabz-yoga-1, the HOME laptop, by tailnet address' }
  @{ Name='mac-mini-lan';           HostName='192.168.50.73';  User='lpt';   Note='lakewooechsmini on the office LAN. NOTE: the existing `mac-mini` alias points at .45 and that address does NOT answer; the peer is at .73' }
  @{ Name='mac-mini-ts-ip';         HostName='100.126.146.121';User='lpt';   Note='lakewooechsmini by tailnet address' }
  @{ Name='secratary-cloud-ip';     HostName='100.73.176.126'; User='root';  Note='THE AUTHORITY by tailnet address - survives a MagicDNS failure' }
  @{ Name='secratary-cloud-public'; HostName='178.156.194.1';  User='root';  Note='THE AUTHORITY by public IPv4 - the out-of-band door, measured OPEN on tcp/22 and accepted by the Hetzner key' }
)

# The key each alias must use. Taken from the alias that already works for that machine, so
# this block never invents a credential: `secratary-cloud` in the existing config uses the
# Hetzner key, and the workstation/LAN aliases use zabz-tech-ed25519.
$KeyFor = @{
  'secratary-cloud-ip'     = '~/.ssh/id_ed25519_hetzner'
  'secratary-cloud-public' = '~/.ssh/id_ed25519_hetzner'
}
$DefaultKey = '~/.ssh/zabz-tech-ed25519'

$cfg = Join-Path $env:USERPROFILE '.ssh\config'
if (-not (Test-Path -LiteralPath $cfg)) { throw "install-mesh-ip-aliases: $cfg does not exist. Refusing to create an ssh config from nothing; install one first." }

$lines = Get-Content -LiteralPath $cfg
$hasBlock = $false
foreach ($l in $lines) { if ($l.Trim() -eq $BEGIN) { $hasBlock = $true; break } }

$block = New-Object System.Collections.Generic.List[string]
$block.Add($BEGIN)
$block.Add('# WHY: doc 187. One name per node is a single point of failure; these are the same')
$block.Add('# peers by ADDRESS, which does not need MagicDNS. Read-only transport, no service state.')
$block.Add('# REMOVE THIS BLOCK WITH:  .\scripts\mesh\install-mesh-ip-aliases.ps1 -Remove')
foreach ($a in $Aliases) {
  $block.Add("")
  $block.Add("# $($a.Note)")
  $block.Add("Host $($a.Name)")
  $block.Add("    HostName $($a.HostName)")
  $block.Add("    User $($a.User)")
  $key = if ($KeyFor.ContainsKey($a.Name)) { $KeyFor[$a.Name] } else { $DefaultKey }
  $block.Add("    IdentityFile $key")
  $block.Add("    IdentitiesOnly yes")
  $block.Add("    StrictHostKeyChecking accept-new")
  $block.Add("    ConnectTimeout 10")
  $block.Add("    AddressFamily inet")
}
$block.Add($END)

if ($Remove) {
  if (-not $hasBlock) { Write-Output "install-mesh-ip-aliases: no managed block present; nothing to remove."; exit 0 }
  $out = New-Object System.Collections.Generic.List[string]
  $inBlock = $false
  foreach ($l in $lines) {
    if ($l.Trim() -eq $BEGIN) { $inBlock = $true; continue }
    if ($l.Trim() -eq $END)   { $inBlock = $false; continue }
    if (-not $inBlock) { $out.Add($l) }
  }
  $bak = "$cfg.bak-before-187-remove-" + (Get-Date -Format 'yyyyMMdd-HHmmss')
  Copy-Item -LiteralPath $cfg -Destination $bak -Force
  Set-Content -LiteralPath $cfg -Value $out -Encoding utf8
  Write-Output "install-mesh-ip-aliases: REMOVED the managed block. Backup: $bak"
  exit 0
}

if ($hasBlock) {
  Write-Output "install-mesh-ip-aliases: the managed block is ALREADY present in $cfg. Nothing to do (idempotent)."
  Write-Output "install-mesh-ip-aliases: to re-install cleanly, run with -Remove first."
  exit 0
}

if ($DryRun) {
  Write-Output "install-mesh-ip-aliases - DRY RUN. Would append $($block.Count) lines to $cfg :"
  Write-Output ""
  $block | ForEach-Object { Write-Output $_ }
  exit 0
}

$bak = "$cfg.bak-before-187-" + (Get-Date -Format 'yyyyMMdd-HHmmss')
Copy-Item -LiteralPath $cfg -Destination $bak -Force
$new = New-Object System.Collections.Generic.List[string]
foreach ($l in $lines) { $new.Add($l) }
$new.Add("")
foreach ($l in $block) { $new.Add($l) }
Set-Content -LiteralPath $cfg -Value $new -Encoding utf8

Write-Output "install-mesh-ip-aliases: appended the managed block to $cfg"
Write-Output "install-mesh-ip-aliases: backup of the previous file: $bak"
Write-Output "install-mesh-ip-aliases: REMOVE WITH:  .\scripts\mesh\install-mesh-ip-aliases.ps1 -Remove"
Write-Output ""
Write-Output "Verify one alias end to end:"
Write-Output "  ssh -o BatchMode=yes secratary-cloud-ip 'echo OK; hostname'"
exit 0
