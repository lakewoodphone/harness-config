<#
.SYNOPSIS
  route-mesh.ps1 - which DESTINATION does THIS machine use to reach a mesh node, and why?

.DESCRIPTION
  The transport-policy half that `scripts/mesh/route.sh` and `Resolve-MeshPath.ps1` do NOT
  cover. Those two answer "which base URL do I use for the COMPANY AUTHORITY". Neither
  answers "how do I reach a WORKER NODE", and that is the question a mesh dispatch asks -
  `packages/plugin-remote-fanout/lib/nodes.js` hardcodes exactly ONE ssh destination per
  node and every one of them is a tailnet MagicDNS name.

  THE GAP THIS CLOSES (measured 2026-10-12 from zabz-tech, doc 187):
    * `nodes.js` names one destination per node and there is no second path anywhere in the
      dispatch code, so a Tailscale or MagicDNS failure removes the whole fleet at once.
    * MagicDNS resolution has failed intermittently on this estate already: the ssh config
      carries a standing note that on 2026-09-28 MagicDNS for `secratary.tail93e6e6.ts.net`
      failed four times in fourteen minutes WHILE the Tailscale service was up and the peer
      was active. `secratary-ip` (the bare 100.x address) exists because of that.
    * So for every node this script measures BOTH the MagicDNS name and the bare tailnet
      address, and prefers whichever actually ANSWERS. A name that answers because MagicDNS
      is healthy is not the same fact as an address that answers without it.

  POLICY: docs/mesh/143-TRANSPORT-POLICY.md - LAN, then Tailscale, then Cloudflare, and the
  selection is MEASURED, never assumed. Precedence here:
    1. lan    the office private address (only when both boxes are on the same subnet)
    2. tail   the tailnet, ENCRYPTED, and here in two independently testable spellings:
                tail-name  the MagicDNS name (`desktop-ts`)
                tail-ip    the bare 100.x address (survives a MagicDNS failure)
    3. flare  Cloudflare. There is NO per-node Cloudflare ssh door on this estate today -
              only `desktop-ssh` / `secretary-ssh`, which are the WINDOWS DESKTOP and the
              OFFICE BOX, not worker nodes. This row is therefore probed and reported as
              absent rather than quietly omitted, because an untested fallback is the bug
              the policy exists to prevent.

  READ-ONLY. This script only connects and disconnects (`ssh ... exit 0`, an HTTP GET, or a
  posture command). It starts, stops and reconfigures nothing.

.EXAMPLE
  .\route-mesh.ps1                          # matrix + the chosen destination per node
  .\route-mesh.ps1 -Explain                 # per-candidate evidence
  .\route-mesh.ps1 -Node zabz-tech -Json    # one node, machine-readable
  .\route-mesh.ps1 -ProbePath               # full mesh-HTTP reachability matrix

.OUTPUTS
  exit 0 every probed node answered on at least one transport
  exit 3 at least one node answered on NO transport (named on stdout)
  exit 4 nothing was probed (no node matched, or the roster could not be read)
#>
[CmdletBinding()]
param(
  [string[]]$Node,
  [int]$TimeoutSec = 8,
  [switch]$Explain,
  [switch]$Json,
  [switch]$ProbePath
)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

# ---------------------------------------------------------------------------
# THE ROSTER, with every transport spelling for each node.
#
# `node` is the BROKER's name for the machine (the key in
# packages/plugin-remote-fanout/lib/nodes.js, whose invariant is
# node === fqdn.split('.')[0]). `hosts` is the hostname set that node is allowed to
# report, copied from the same file so a wrong-machine answer is caught here too.
#
# `tailName` is what nodes.js actually dispatches to today. `tailIp`/`lanAlias` are the
# SECOND spelling of the same peer - the address, which survives a MagicDNS failure, reached
# through the ssh-config alias this doc's companion script installs. Every address here was
# read from `tailscale status --json` on zabz-tech 2026-10-12, and each row's `measured`
# field carries the latency that was actually observed.
# ---------------------------------------------------------------------------
$NODES = @(
  @{ node='zabz-tech';        posture='desktop-ts';    hosts=@('ZABZ-TECH','zabz-tech');        user='ezabz';
     lan='192.168.50.138';    lanAlias='desktop-lan';  tailName='desktop-ts';   tailIp='100.85.153.96';   tailIpAlias='desktop-ts-ip';   fqdn='zabz-tech.tail93e6e6.ts.net';
     measured='ALL MEASURED 2026-10-12 from zabz-tech: lan ok, tail-name ok, tail-ip ok. This is the local machine, so the tailnet address is its own - a dispatch from here is a loopback.' }
  @{ node='secratary';        posture='secratary-ts';  hosts=@('secratary');                    user='zabz';
     lan='192.168.50.77';     lanAlias='secratary-lan'; tailName='secratary-ts'; tailIp='100.84.72.88';    tailIpAlias='secratary-ip';    fqdn='secratary.tail93e6e6.ts.net';
     measured='MEASURED 2026-10-12 from zabz-tech: lan ok 217ms, tail-name ok 227ms, tail-ip ok 220ms (ssh round trip, auth-dominated). ICMP 0-1ms on all three. FROZEN rollback anchor - this script only runs `exit 0` on it.' }
  @{ node='zabz-tech-linux';  posture='linux-pc-ts';   hosts=@('zabz-tech-linux');              user='zabz';
     lan='192.168.50.23';     lanAlias='linux-pc-lan'; tailName='linux-pc-ts';  tailIp='100.105.248.90';  tailIpAlias='linux-pc-ts-ip';  fqdn='zabz-tech-linux.tail93e6e6.ts.net';
     measured='MEASURED 2026-10-12 from zabz-tech: lan ok 0-1ms ICMP, tail-name ok, tail-ip ok.' }
  @{ node='zabz-yoga-1';      posture='laptop-ts';     hosts=@('ZABZ-YOGA','zabz-yoga','zabz-yoga-1'); user='ezabz';
     lan=$null;               lanAlias=$null;          tailName='laptop-ts';    tailIp='100.72.162.5';    tailIpAlias='laptop-ts-ip';    fqdn='zabz-yoga-1.tail93e6e6.ts.net';
     measured='MEASURED 2026-10-12 from zabz-tech: NO LAN PATH - this is the HOME machine and zabz-tech is the OFFICE, different networks (docs/mesh/143). tail-name and tail-ip both answer. Its 192.168.50.244 LAN address is the OFFICE value and is not the path.' }
  @{ node='lakewooechsmini';  posture='mac-mini-ts';   hosts=@('LakewooechsMini');              user='lpt';
     lan='192.168.50.73';     lanAlias='mac-mini-lan'; tailName='mac-mini-ts';  tailIp='100.126.146.121'; tailIpAlias='mac-mini-ts-ip';  fqdn='lakewooechsmini.tail93e6e6.ts.net';
     measured='MEASURED 2026-10-12 from zabz-tech: lan answers ICMP at avg 64ms (min 3 / max 87) while the WIRED boxes on the same subnet answer at 0-1ms, so this peer is on WIFI with power-save jitter. tail-name ok 201ms ssh. Note ~/.ssh/config sends `mac-mini` to 192.168.50.45 and that address does NOT answer; the peer is at .73. See doc 187 SPOF 7.' }
)

# The authority is not a mesh node but it RUNS the broker, so its reachability is part of
# the mesh's own transport surface. Kept separate because its precedence differs: it has no
# LAN path from anywhere except itself (it is in Ashburn), and it is the only machine on this
# estate with a public ssh door.
$AUTHORITY = @(
  @{ label='tail-name'; target='secratary-cloud';      note='the tailnet name the ssh config uses; needs MagicDNS' }
  @{ label='tail-ip';   target='secratary-cloud-ip';   note='the bare tailnet address; survives a MagicDNS failure' }
  @{ label='public';    target='secratary-cloud-public'; note='the Hetzner public IPv4 measured OPEN on tcp/22; a real out-of-band door' }
)

function Say([string]$m) { if ($Explain -or $Json) { Write-Host $m } }

# `$a ?? $b` is PowerShell 7 only, and this estate runs Windows PowerShell 5.1 on ZABZ-TECH
# and ZABZ-YOGA. The scripts here must run on the shell the boxes actually have.
function First-Set($a, $b) { if ($null -ne $a -and "$a" -ne '') { return $a } return $b }

# ---------------------------------------------------------------------------
# A LAN probe must not fall through to the tailnet. `ping 192.168.50.45` from an off-LAN
# machine can be answered by a router or fail slowly; both would be a false reading. So the
# LAN candidate is only probed when this machine is itself on the office subnet.
# ---------------------------------------------------------------------------
function Get-LocalOfficeSubnet {
  try {
    $c = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
         Where-Object { $_.IPAddress -like '192.168.50.*' } | Select-Object -First 1
    if ($c) { return $true }
  } catch { }
  return $false
}
$onOfficeLan = Get-LocalOfficeSubnet

# ---------------------------------------------------------------------------
# Probes. Each returns @{ok; why}. `tcp` proves the PORT answers without an ssh auth round
# trip; that is the honest test of a TRANSPORT, and it is the one that does not depend on a
# key being installed.
# ---------------------------------------------------------------------------
function Test-Tcp([string]$host_, [int]$port = 22) {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    $c = New-Object System.Net.Sockets.TcpClient
    $t = $c.ConnectAsync($host_, $port)
    if ($t.Wait($TimeoutSec * 1000) -and $c.Connected) {
      $sw.Stop(); $c.Close()
      return @{ ok = $true; why = ("tcp/{0} open in {1}ms" -f $port, [math]::Round($sw.Elapsed.TotalMilliseconds)) }
    }
    $c.Close()
    return @{ ok = $false; why = ("tcp/{0} no answer within {1}s" -f $port, $TimeoutSec) }
  } catch {
    return @{ ok = $false; why = ("tcp/{0} {1}" -f $port, ($_.Exception.Message -split [char]10)[0]) }
  }
}

function Test-Ssh([string]$dest, [int]$timeout) {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $tmp = [System.IO.Path]::GetTempFileName()
  # stdout goes to a FILE, never a pipe: on Windows an ssh client whose stdout is a pipe
  # does not exit even after the remote command has finished (measured, and the reason
  # packages/plugin-remote-fanout/lib/ssh-transport.js redirects both streams to files).
  $p = Start-Process ssh -ArgumentList @(
        '-o', 'BatchMode=yes', '-o', "ConnectTimeout=$timeout",
        '-o', 'StrictHostKeyChecking=accept-new', $dest, 'exit 0') `
       -RedirectStandardOutput $tmp -RedirectStandardError "$tmp.err" -NoNewWindow -PassThru
  $null = $p | Wait-Process -Timeout ($timeout + 6) -ErrorAction SilentlyContinue
  if (-not $p.HasExited) { try { $p | Stop-Process -Force } catch { } }
  $sw.Stop()
  $code = $null; try { $code = $p.ExitCode } catch { }
  Remove-Item $tmp, "$tmp.err" -Force -ErrorAction SilentlyContinue
  if ($code -eq 0) { return @{ ok = $true; why = ("ssh exit=0 in {0}ms" -f [math]::Round($sw.Elapsed.TotalMilliseconds)) } }
  return @{ ok = $false; why = ("ssh exit={0}" -f $code) }
}

# ---------------------------------------------------------------------------
# The candidates, in policy precedence.
#
# EVERY candidate is probed as an SSH DESTINATION, through an ssh-config alias, and never as
# a bare address. Why: a bare `ssh 192.168.50.77` does not carry the account, so it tries
# `ezabz@192.168.50.77` and is REFUSED on a box whose account is `zabz` - a false negative
# that libels a working transport. Measured 2026-10-12: that is exactly what the first draft
# of this script did, and it reported three healthy LAN paths as dead. The alias carries the
# user AND the key, which is the same reason `main`/`-ts`/`-lan` aliases exist at all.
#
# The alias rows are installed by scripts/mesh/install-mesh-ip-aliases.ps1, which is
# idempotent and reversible; this script names them and does NOT create them.
# ---------------------------------------------------------------------------
function Get-Candidates($n) {
  $rows = @()
  if ($n.lanAlias -and $onOfficeLan) {
    $rows += @{ transport = 'lan';   label = 'lan';       ssh = $n.lanAlias;     note = 'office subnet, unencrypted switch hop' }
  }
  $rows += @{ transport = 'tail'; label = 'tail-name';  ssh = $n.tailName;      note = 'tailnet MagicDNS name - what nodes.js dispatches to today' }
  if ($n.tailIpAlias) {
    $rows += @{ transport = 'tail'; label = 'tail-ip';    ssh = $n.tailIpAlias;   note = 'bare tailnet address - survives a MagicDNS failure' }
  }
  # Cloudflare: reported, never silently omitted.
  $rows += @{ transport = 'flare'; label = 'flare'; ssh = $null; note = 'NO per-node Cloudflare ssh door exists on this estate' }
  return $rows
}

$results = @()
$dead = @()
$probedNodes = 0

Say "route-mesh  host=$env:COMPUTERNAME  at=$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
Say "policy: docs/mesh/143-TRANSPORT-POLICY.md - LAN, then Tailscale, then Cloudflare; measured, never assumed"
Say "on-office-lan=$onOfficeLan"
Say ""

foreach ($n in $NODES) {
  if ($Node -and ($Node -notcontains $n.node)) { continue }
  $probedNodes++
  Say "--- $($n.node)  (posture alias $($n.posture))"
  $chosen = $null; $alts = @()
  foreach ($c in (Get-Candidates $n)) {
    if ($c.label -eq 'flare') {
      Say "    [absent]  flare -> $($c.note)"
      $alts += [ordered]@{ transport = $c.transport; candidate = $null; result = 'absent: ' + $c.note }
      continue
    }
    $res = Test-Ssh $c.ssh $TimeoutSec
    $verdict = if ($res.ok) { 'ok' } else { 'fail' }
    Say "    [$verdict]  $($c.label) -> $($c.ssh)  $($res.why)"
    $alts += [ordered]@{ transport = $c.transport; candidate = $c.ssh; result = $res.why }
    if ($res.ok -and -not $chosen) {
      $chosen = [ordered]@{ transport = $c.transport; label = $c.label; ssh = $c.ssh; evidence = $res.why }
    }
  }
  if ($chosen) {
    Say "    CHOSE $($chosen.label) -> $($chosen.ssh)   transport=$($chosen.transport)"
  } else {
    Say "    NO PATH ANSWERED - this node is unreachable on every transport probed"
    $dead += $n.node
  }
  Say ""
  $results += [ordered]@{ node = $n.node; posture = $n.posture; fqdn = $n.fqdn; chosen = $chosen; alternatives = $alts }
}

# ---------------------------------------------------------------------------
# --ProbePath: the mesh HTTP surface, per node, over the tailnet name. This is the transport
# that plugin-mesh-http provides and the DEFAULT dispatcher does not use. GET only.
# ---------------------------------------------------------------------------
$pathResults = @()
if ($ProbePath) {
  Say "--- mesh HTTP surface (GET /mesh/capacity over the tailnet name) ---"
  $pathTargets = @($NODES | ForEach-Object { @{ node = $_.node; url = ("https://" + $_.fqdn + "/mesh/capacity") } })
  $pathTargets += @{ node = 'secratary-cloud'; url = 'https://secratary-cloud.tail93e6e6.ts.net/mesh/capacity' }
  foreach ($t in $pathTargets) {
    $out = [System.IO.Path]::GetTempFileName()
    $code = & curl.exe -s -m $TimeoutSec -o $out -w '%{http_code}' $t.url 2>$null
    $body = ''
    try { $body = (Get-Content $out -Raw -ErrorAction SilentlyContinue) } catch { }
    Remove-Item $out -Force -ErrorAction SilentlyContinue
    $shape = if ($body -match '"node"\s*:\s*"([^"]+)"') { $Matches[1] } else { '' }
    $verdict = if ($code -eq '200') { 'ok' } else { 'fail' }
    Say ("    [{0}] {1,-18} http={2} node={3} {4}" -f $verdict, $t.node, $code, $shape, $t.url)
    $pathResults += [ordered]@{ node = $t.node; url = $t.url; http = $code; reportedNode = $shape }
  }
  Say ""
}

if ($Json) {
  [ordered]@{
    host = $env:COMPUTERNAME
    at = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    policy = 'docs/mesh/143-TRANSPORT-POLICY.md'
    onOfficeLan = $onOfficeLan
    nodes = $results
    meshHttp = $pathResults
    unreachable = $dead
    authority = $AUTHORITY
  } | ConvertTo-Json -Depth 8
  exit $(if ($dead.Count -gt 0) { 3 } else { 0 })
}

if ($probedNodes -eq 0) {
  Write-Error "route-mesh: nothing was probed. -Node matched no roster entry. Refusing to report health for a set that was never measured."
  exit 4
}

Write-Output ""
Write-Output "=== AUTHORITY REACHABILITY (the box that runs mesh-broker) ==="
foreach ($a in $AUTHORITY) {
  $res = Test-Ssh $a.target $TimeoutSec
  $v = if ($res.ok) { 'ok  ' } else { 'FAIL' }
  Write-Output ("  [{0}] {1,-10} {2,-26} {3}  ({4})" -f $v, $a.label, $a.target, $res.why, $a.note)
}

Write-Output ""
Write-Output "=== SUMMARY: chosen transport per node ==="
foreach ($r in $results) {
  $c = $r.chosen
  if ($c) { Write-Output ("  {0,-18} {1,-10} -> {2}" -f $r.node, $c.transport, $c.ssh) }
  else     { Write-Output ("  {0,-18} {1,-10} -> UNREACHABLE" -f $r.node, 'NONE') }
}
if ($dead.Count -gt 0) {
  Write-Output ""
  Write-Output ("UNREACHABLE ON EVERY TRANSPORT: " + ($dead -join ', '))
  exit 3
}
exit 0
