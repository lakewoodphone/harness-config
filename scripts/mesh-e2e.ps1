<#
.SYNOPSIS
  THE MESH ACCEPTANCE HARNESS — does this mesh actually work? (stream S7)

.DESCRIPTION
  This is docs/mesh/71-mesh-program.md §4, implemented as six named steps. §4 is the frozen
  specification; this file decides whether the other streams built what §2 promised. It was
  written BEFORE the components existed, on purpose: a test written after the thing it tests
  can always be adjusted until it passes, and then it has measured nothing.

  WHY IT IS SHAPED THIS WAY

  * Two kinds of step, and the difference is deliberate.
    - LIVE steps (1, 3, 4, 5) ask the real nodes, the real broker and the real dispatcher.
    - HERMETIC steps (2, 6, and the "b" sub-steps) start a real broker from
      packages/mesh-broker/ against real stub gates (packages/mesh-broker/lib/stub-gate.js)
      on port 0. §4.2 says "with that node's capacity forced to 0" and §4.6 says "a mesh with
      5 slots" - neither is a thing you can do to a live office desktop, and a test that
      cannot set up its own condition is not a test. A hermetic mesh also lets a step run
      WITHOUT perturbing the live mesh: §4.6 creates 30 leases, and 30 leases placed on the
      deployed broker would make real nodes look busy for 15 minutes and mislead every other
      stream. So the destructive arithmetic goes on stub gates, and the live broker is asked
      exactly one question (§4.2's first sub-case) whose lease is released immediately.

  * FAIL vs SKIP is decided by one rule, stated once here so it cannot drift:
      Does the capability exist ANYWHERE in the fleet yet?
        no  -> SKIP (it has not been built; name exactly what would have to exist)
        yes -> every gated node must have it, so a node that lacks it is FAIL
    And a node is only FAIL if something is there to fail: nothing published on 443 at all
    means the node is not a gated node yet, which is a SKIP with the reason.

  * EVERY HTTP CALL GOES OUT WITH THE PROXY OFF. Measured on this laptop: it sets a proxy
    AutoConfigURL (a .pac file) and a proxy is fully capable of manufacturing a 502 that has
    nothing to do with the node. `UseProxy = $false` on the HttpClient is the same protection
    scripts/mesh-health.ps1 uses, and for the same measured reason.

  * EVERY REQUEST HAS A TIMEOUT, and every HTTP call is retried on a transport failure.
    Measured 2026-09-16T23:18Z: zabz-tech's published /mesh/capacity answered 502 once and
    then answered 200 five times in a row inside three minutes, with no deployment change on
    that node in between. A single 502 is therefore evidence of nothing, and this harness
    retries a transport failure (502/503/504/refused/timeout) three times before it believes
    it. A 404 is NOT retried - it is a deterministic answer, not a blip.

  * IT NEVER RESTARTS AN ENGINE, AND IT NEVER KILLS A PROCESS IT DID NOT START. Every
    Stop-Process in this file is applied to a PID this file captured from its own
    Start-Process. The live gate processes and every engine on every node are left running:
    §0 of the program says a mounted bundle cannot hot-load and an engine restart ends live
    sessions, and the owner's session on this laptop is live right now.

.PARAMETER Nodes
  Which nodes to test. Default: the five in the fleet today.

.PARAMETER BrokerUrl
  The live broker's base URL. Default: discovered - -BrokerUrl, then $env:MESH_BROKER_URL,
  then http://127.0.0.1:3091, then an ssh tunnel to secratary-ts:127.0.0.1:3091. The tunnel is
  needed because the deployed broker listens on loopback only (measured 2026-09-16T23:19Z:
  secratary's 3091 is bound to 127.0.0.1 and the tailnet refused :3091).

.PARAMETER SkipHermetic
  Do not start the local broker+stub-gate mesh. Steps 2, 3b, 5b and 6 then SKIP.

.PARAMETER Strict
  Exit non-zero on SKIP as well as FAIL. Off by default: §4 above says SKIP is honest while a
  dependency is genuinely absent, and a harness that screams on an unbuilt component teaches
  people to ignore it.

.EXAMPLE
  pwsh -File scripts\mesh-e2e.ps1
  pwsh -File scripts\mesh-e2e.ps1 -Nodes zabz-yoga-1,zabz-tech -Json
  pwsh -File scripts\mesh-e2e.ps1 -SkipHermetic -Strict

.NOTES
  Owner of this file: stream S7. Files it writes: none in the repo. Runtime evidence goes to
  ~/.dsh/mesh/acceptance/<runId>/ (report.json, gate and broker logs).
#>
[CmdletBinding()]
param(
    [string[]]$Nodes = @('zabz-yoga-1', 'zabz-tech', 'secratary', 'zabz-tech-linux', 'LakewooechsMini'),
    [int]$TimeoutSec = 25,
    [string]$BrokerUrl = '',
    [string]$SshBrokerHost = 'secratary-ts',
    [int]$BrokerPort = 3091,
    [switch]$SkipHermetic,
    [switch]$Strict,
    [switch]$Json,
    [string]$ReportPath = ''
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$script:Contract = 'docs/mesh/71-mesh-program.md §4 (frozen), interfaces §2'
$script:Steps = New-Object System.Collections.ArrayList
$script:RunId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$script:Host0 = $env:COMPUTERNAME
$script:StartedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$script:Procs = New-Object System.Collections.ArrayList      # ONLY processes this script started
$script:Scratch = ''
$script:Notes = New-Object System.Collections.ArrayList

$MESH_GOVERNOR_RESERVE_MIB = 3885   # §2.2 frozen
$MESH_PER_SLOT_MIB        = 160     # §2.2 frozen
$MESH_MAX_SLOTS           = 24      # §2.2 frozen
$MESH_FLEET_DISK_FLOOR    = 20      # §2.2 frozen

# ---------------------------------------------------------------------------
# the node roster this harness knows about
#
# `name` is the §2.1 node name, which the spec REVISED on 2026-09-16 (while this harness was
# being written) to be the Tailscale DNS LABEL - the fqdn's first label - and NOT the ssh alias
# prefix. That matters: this laptop's HostName is `zabz-yoga` but the only name that resolves is
# `zabz-yoga-1`, and `zabz-tech-linux`'s ssh aliases are `linux-pc`/`hp-linux`. `-Nodes` accepts
# either the DNS label or the ssh alias, because a human will type either one.
# ---------------------------------------------------------------------------
$NodeTable = @(
    [pscustomobject]@{ name = 'zabz-yoga-1';      fqdn = 'zabz-yoga-1.tail93e6e6.ts.net';     ssh = 'laptop-ts';    platform = 'windows'; location = 'home' }
    [pscustomobject]@{ name = 'zabz-tech';        fqdn = 'zabz-tech.tail93e6e6.ts.net';       ssh = 'desktop-ts';   platform = 'windows'; location = 'office' }
    [pscustomobject]@{ name = 'secratary';        fqdn = 'secratary.tail93e6e6.ts.net';       ssh = 'secratary-ts'; platform = 'linux';   location = 'office' }
    [pscustomobject]@{ name = 'zabz-tech-linux'; fqdn = 'zabz-tech-linux.tail93e6e6.ts.net'; ssh = 'linux-pc-ts';  platform = 'linux';   location = 'office' }
    [pscustomobject]@{ name = 'LakewooechsMini'; fqdn = 'LakewooechsMini.tail93e6e6.ts.net'; ssh = 'mac-mini-ts';  platform = 'darwin';  location = 'office' }
)

# The local node is measured directly, not over ssh: a loopback ssh to this laptop is one more
# thing that can be misconfigured, and the OS counter is right here.
$LocalHostName = ''
try { $LocalHostName = (& node -p "require('os').hostname()" 2>$null | Select-Object -First 1) } catch { }
if (-not $LocalHostName) { $LocalHostName = $env:COMPUTERNAME }

# ===========================================================================
# output helpers
# ===========================================================================
function Write-Head([string]$text) {
    Write-Host ''
    Write-Host $text -ForegroundColor Cyan
    Write-Host ('-' * [Math]::Min(100, $text.Length)) -ForegroundColor DarkCyan
}

function Add-Step {
    param(
        [string]$Id, [string]$Name, [string]$Status, [string]$Evidence, [string[]]$Detail = @()
    )
    $entry = [pscustomobject]@{
        id = $Id; name = $Name; status = $Status; evidence = $Evidence; detail = @($Detail)
    }
    [void]$script:Steps.Add($entry)
    $colour = switch ($Status) { 'PASS' { 'Green' } 'FAIL' { 'Red' } 'SKIP' { 'Yellow' } default { 'Gray' } }
    Write-Host ''
    Write-Host ("  [{0}] {1,-30} {2}" -f $Id, $Name, $Status) -ForegroundColor $colour
    Write-Host ("       evidence: {0}" -f $Evidence)
    foreach ($d in $Detail) { Write-Host ("       $d") -ForegroundColor DarkGray }
}

function Add-Note([string]$text) { [void]$script:Notes.Add($text) }

# ===========================================================================
# HTTP — proxy OFF on every call, a timeout on every call, transport retried
# ===========================================================================
function New-HttpClient([int]$seconds) {
    try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch { }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false                                  # measured: this laptop's .pac invents 502s
    $handler.AllowAutoRedirect = $true
    $handler.MaxConnectionsPerServer = 128
    $handler.CookieContainer = New-Object System.Net.CookieContainer
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($seconds)
    return $client
}

<#
  One HTTP call, always resolving - never throwing at the caller. A transport failure
  (0/502/503/504) is retried; a 404 is believed the first time.
#>
function Invoke-Json {
    param(
        [string]$Url,
        [string]$Method = 'GET',
        [string]$Body = $null,
        [int]$Retries = 3,
        [int]$RetryGapMs = 2000,
        [int]$Seconds = 0
    )
    if ($Seconds -le 0) { $Seconds = $TimeoutSec }
    $transient = @(0, 502, 503, 504)
    $last = $null
    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        $client = New-HttpClient $Seconds
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        # NOT `$body`. PowerShell variable names are CASE-INSENSITIVE, so a local `$body`
        # IS the `-Body` parameter, and assigning to it here sent an EMPTY POST body.
        #
        # MEASURED COST OF GETTING THIS WRONG ONCE, 2026-09-16T23:25Z: every POST in this
        # harness went out with content-length 0; the broker's "never refuse" rule turned each
        # dropped "6-child fleet" into a 1-child one-shot; and four sub-cases PASSED while
        # testing a task nobody asked for. The run looked green. That is the whole reason the
        # kind/children assertions exist below - the broker echoes back the task it understood,
        # so a test can prove its body ARRIVED instead of trusting its own intent.
        $respCode = 0; $respBody = ''; $respDoc = $null; $errText = $null
        try {
            if ($Method -eq 'POST') {
                $content = New-Object System.Net.Http.StringContent($Body, [System.Text.Encoding]::UTF8, 'application/json')
                $response = $client.PostAsync($Url, $content).GetAwaiter().GetResult()
            } else {
                $response = $client.GetAsync($Url).GetAwaiter().GetResult()
            }
            $respCode = [int]$response.StatusCode
            $respBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        } catch {
            $ex = $_.Exception
            if ($ex.InnerException) { $ex = $ex.InnerException }
            $errText = "$($ex.GetType().Name): $($ex.Message)"
            $respCode = 0
        } finally {
            $sw.Stop()
            $client.Dispose()
        }
        if ($respCode -eq 200 -and $respBody) {
            try { $respDoc = $respBody | ConvertFrom-Json }
            catch { $errText = "HTTP 200 but the body is not JSON: $($_.Exception.Message)" }
        } elseif ($respCode -ne 200 -and $respBody) {
            # A FAIL must carry the SERVER's own words. Measured 2026-09-16T23:35Z: the broker
            # answered GET /nodes with HTTP 500 and {"error":"effective is not defined"}; without
            # this line the harness reported only "HTTP 500: " and sent the reader off to guess.
            $excerpt = ($respBody -replace '\s+', ' ').Trim()
            if ($excerpt.Length -gt 300) { $excerpt = $excerpt.Substring(0, 300) + '...' }
            $errText = "HTTP $respCode body: $excerpt"
        }
        $ok = ($respCode -eq 200 -and $errText -eq $null)
        $last = [pscustomobject]@{
            ok = $ok; code = $respCode; body = $respBody; doc = $respDoc; error = $errText
            latencyMs = $sw.ElapsedMilliseconds; url = $Url; method = $Method
            attempts = $attempt; at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        }
        if ($ok) { break }
        if ($transient -notcontains $respCode) { break }         # a 404/401/200-invalid is deterministic
        if ($attempt -lt $Retries) { Start-Sleep -Milliseconds $RetryGapMs }
    }
    return $last
}

function Get-Capacity([string]$fqdn) {
    return Invoke-Json -Url "https://$fqdn/mesh/capacity"
}

<#
  The broker echoes the task it understood: every placement response carries `kind` and
  `children` (§2.2). Asserting on that - rather than on what this script MEANT to send - is
  what turns a dropped, truncated or mangled request body into a loud FAIL instead of a quiet
  change of subject. It was written because exactly that happened: see the note in Invoke-Json.
#>
function Test-TaskEcho($placement, [string]$Kind, [int]$Children) {
    if ($null -eq $placement) { return $false }
    return ($placement.kind -eq $Kind) -and ([int]$placement.children -eq $Children)
}

# ===========================================================================
# direct measurement — the independent counter §4.1 compares the gate against
# ===========================================================================
function Get-DirectMemory {
    <#
      The gate's `mem.freeMiB` comes from the OS's own free-memory counter
      (phone-gate.py: GlobalMemoryStatusEx on Windows - the same call node's os.freemem()
      makes; MemAvailable on Linux). This reads the SAME counter WITHOUT going through the
      gate, which is what makes it an independent measurement rather than a second reading
      of the same number. Source and time are recorded with every value.
    #>
    param([pscustomobject]$Spec)
    $result = [ordered]@{
        node = $Spec.name; totalMiB = $null; freeMiB = $null; freeKind = ''
        source = ''; error = $null; at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    # A `|` separator, not a space: the numbers and the hostname must not be told apart by
    # guessing which token is not numeric.
    $js = "console.log(Math.round(require('os').totalmem()/1048576) + '|' + Math.round(require('os').freemem()/1048576) + '|' + require('os').hostname())"
    try {
        if ($Spec.fqdn -like "$LocalHostName*") {
            $raw = & node -e $js 2>&1
            $result.source = "local: node -e os.totalmem()/os.freemem() on $env:COMPUTERNAME"
        } elseif ($Spec.platform -eq 'windows') {
            $remote = 'node -e "' + $js + '"'
            $raw = & ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh $remote 2>&1
            $result.source = "ssh $($Spec.ssh): node -e os.totalmem()/os.freemem()"
        } elseif ($Spec.platform -eq 'linux') {
            $raw = & ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh 'grep -E "MemTotal|MemAvailable" /proc/meminfo' 2>&1
            $result.source = "ssh $($Spec.ssh): /proc/meminfo MemAvailable"
        } else {
            $raw = & ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh 'sysctl -n hw.memsize; vm_stat' 2>&1
            $result.source = "ssh $($Spec.ssh): sysctl hw.memsize + vm_stat (APPROXIMATE: macOS has no MemAvailable)"
        }
        $text = ($raw | Out-String)
        if ($Spec.platform -eq 'linux') {
            $mTotal = [regex]::Match($text, 'MemTotal:\s+(\d+)\s+kB')
            $mAvail = [regex]::Match($text, 'MemAvailable:\s+(\d+)\s+kB')
            if ($mTotal.Success) { $result.totalMiB = [int][math]::Round([double]$mTotal.Groups[1].Value / 1024) }
            if ($mAvail.Success) { $result.freeMiB = [int][math]::Round([double]$mAvail.Groups[1].Value / 1024) }
            $result.freeKind = 'MemAvailable'
        } elseif ($Spec.platform -eq 'darwin') {
            # Match the counter the GATE actually uses, or this is not a comparison. Verified by
            # reading scripts/phone-gate.py:814-832 on 2026-09-16: the non-Windows branch reads
            # /proc/meminfo MemAvailable, and on macOS there is no /proc, so it falls back to
            # os.sysconf("SC_AVPHYS_PAGES") * page_size - which is vm_stat's "Pages free" ONLY,
            # not free+inactive+speculative. A reader that summed the inactive pages would
            # disagree with a healthy macOS gate by gigabytes and call it a failure.
            $mTotal = [regex]::Match($text, '^\s*(\d+)', 'Multiline')
            if ($mTotal.Success) { $result.totalMiB = [int][math]::Round([double]$mTotal.Groups[1].Value / 1048576) }
            $page = [regex]::Match($text, 'page size of (\d+) bytes')
            $free = [regex]::Match($text, 'Pages free:\s+(\d+)')
            if ($page.Success -and $free.Success) {
                $result.freeMiB = [int][math]::Round(([double]$free.Groups[1].Value * [double]$page.Groups[1].Value) / 1048576)
            }
            $result.freeKind = 'SC_AVPHYS_PAGES (= vm_stat "Pages free" only)'
        } else {
            $parts = @(($text.Trim() -split '\|') | ForEach-Object { $_.Trim() })
            if ($parts.Count -ge 2) { $result.totalMiB = [int]$parts[0]; $result.freeMiB = [int]$parts[1] }
            if ($parts.Count -ge 3) { $result.source = "$($result.source) [host $($parts[2])]" }
            $result.freeKind = 'os.freemem()'
        }
    } catch {
        $result.error = $_.Exception.Message
    }
    if ($result.totalMiB -eq $null -or $result.freeMiB -eq $null) {
        if (-not $result.error) { $result.error = 'the direct reader returned nothing usable' }
    }
    return [pscustomobject]$result
}

<#
  The tolerance, and why it is this number.

  MEASURED on ZABZ-YOGA 2026-09-16T23:2xZ: six interleaved samples of [direct; gate+edge;
  direct] gave |gate - midpoint| of 6, 3, 18, 4, 24, 6 MiB - a maximum of 24 MiB. The gate
  and the direct reader read the SAME OS counter, so the entire difference is memory that
  moved between the two instants, not an error in either number.

  So the floor is 256 MiB: about 10x the largest observed sampling delta, which is room for a
  noisier moment than the six we happened to catch. The 1%-of-total term covers a bigger
  machine churning more bytes per second than this 32 GB laptop. Both are far below the size
  of the mistakes this check exists to catch: a gate reporting a stale reading, or `total`
  where `free` belongs, is out by thousands of MiB.
#>
function Get-FreeToleranceMiB([int]$totalMiB) {
    $floor = 256
    if ($totalMiB -gt 0) { return [int][math]::Max($floor, [math]::Round($totalMiB * 0.01)) }
    return $floor
}

function Test-CapacityShape($doc) {
    <# §2.1: schema 1, named node, and the numbers the broker's scoring cannot work without. #>
    $problems = New-Object System.Collections.ArrayList
    if ($null -eq $doc) { return @('the body is not a JSON object') }
    if ($doc.schema -ne 1) { [void]$problems.Add("schema is $($doc.schema), not 1") }
    if (-not $doc.node -or $doc.node -isnot [string]) { [void]$problems.Add('node is not a non-empty string') }
    # ConvertFrom-Json hands back Int64 for a small integer, so `-is [int]` would reject a
    # perfectly good 15423. Test for "is a number" instead.
    $fm = $doc.mem.freeMiB
    $isNumber = ($fm -is [int]) -or ($fm -is [long]) -or ($fm -is [double]) -or ($fm -is [decimal])
    $fmText = if ($null -eq $doc.mem) { 'there is no mem object at all' } else { "mem.freeMiB = $($doc.mem.freeMiB)" }
    if ($null -eq $doc.mem -or -not $isNumber) {
        [void]$problems.Add("$fmText, which is not a number. Not pedantry: packages/mesh-broker/lib/capacity.js validateCapacity() " +
            'rejects any document whose mem.freeMiB is not a number, so such a node is UNREACHABLE to the broker whatever its ' +
            'accepts block claims (measured 2026-09-16: lakewooechsmini published exactly this, declaring accepts.oneShot true, ' +
            'while the broker could not see it at all)')
    }
    if ($null -eq $doc.mem -or $null -eq $doc.mem.totalMiB) {
        [void]$problems.Add("mem.totalMiB is missing (value: $(if ($null -eq $doc.mem) { 'no mem object' } else { "$($doc.mem.totalMiB)" })) - it is the one number in mem that cannot drift, so it is the cheapest thing a gate can get right")
    }
    if ($null -eq $doc.disk -or $null -eq $doc.disk.freeGiB) { [void]$problems.Add('disk.freeGiB is missing') }
    if ($null -eq $doc.accepts) { [void]$problems.Add('accepts is missing (§2.1: oneShot is still true when the engine is down)') }
    if ($null -ne $doc.accepts -and $doc.accepts.oneShot -ne $true -and $null -eq $doc.agents) {
        [void]$problems.Add('accepts.oneShot is not true while agents is null (§2.1 requires a headless run to stay possible)')
    }
    # §2.1 REVISED 2026-09-16: `node` IS the Tailscale DNS label - the fqdn's first label - and
    # that is stated as "the invariant the probe enforces". This harness enforces it too, because
    # a node that names itself something no other machine resolves is a node the broker cannot
    # act on, and the whole mesh addresses nodes by that string.
    if ($doc.fqdn) {
        $label = @(([string]$doc.fqdn) -split '\.')[0]
        if ($doc.node -ne $label) {
            [void]$problems.Add("node '$($doc.node)' is not the fqdn's first label '$label' (§2.1: node IS the DNS label, not the ssh alias prefix and not the OS HostName)")
        }
    }
    # §2.1: "reason carries the one-line explanation when accepts is restricted". A restriction
    # with no explanation is exactly the thing §2.1 forbids, so it is a shape fault.
    if ($null -ne $doc.accepts -and $doc.accepts.fleet -eq $false -and -not $doc.accepts.reason) {
        [void]$problems.Add('accepts.fleet is false with no accepts.reason (§2.1: a restriction must name itself)')
    }
    return @($problems)
}

function Get-NodeFacts([pscustomobject]$Spec) {
    <# Read-only diagnosis over ssh, used only when the HTTP fetch failed, so a FAIL or SKIP
       says WHY rather than just naming a status code. #>
    $facts = [ordered]@{ serve = ''; listener = ''; gate = ''; error = $null }
    try {
        if ($Spec.platform -eq 'windows') {
            $facts.serve = (& ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh 'tailscale serve status' 2>&1 | Out-String).Trim()
            $facts.listener = (& ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh 'netstat -ano | findstr LISTENING | findstr :3086' 2>&1 | Out-String).Trim()
        } else {
            $facts.serve = (& ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh 'tailscale serve status' 2>&1 | Out-String).Trim()
            $facts.gate = (& ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh 'ps aux | grep phone-gate | grep -v grep' 2>&1 | Out-String).Trim()
            $facts.listener = (& ssh -o ConnectTimeout=10 -o BatchMode=yes $Spec.ssh 'ss -ltn 2>/dev/null | grep :3086' 2>&1 | Out-String).Trim()
        }
    } catch { $facts.error = $_.Exception.Message }
    return [pscustomobject]$facts
}

# ===========================================================================
# hermetic mesh — a real broker against real stub gates, on port 0
# ===========================================================================
function Get-FreePort {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

function Get-MeshBrokerRoot {
    $here = Split-Path -Parent $PSCommandPath
    $candidate = Join-Path (Split-Path -Parent $here) 'packages\mesh-broker'
    if (Test-Path (Join-Path $candidate 'bin\mesh-broker.mjs')) { return $candidate }
    return $null
}

function Get-MeshSourceFingerprint {
    <#
      The revision the hermetic steps are actually loading.

      WHY THIS EXISTS: the hermetic mesh runs packages/mesh-broker straight out of the working
      tree, so if a stream edits it while the harness runs, different sub-cases test DIFFERENT
      revisions and the result is a mixture that nothing explains.

      MEASURED 2026-09-16, run 20260916T233552Z: two sub-cases failed at 23:36:41 with
      `{"error":"effective is not defined"}` and two others PASSED, in the same run, against what
      looked like the same code - because broker.js was rewritten at 23:36:49, mid-run. Recording
      the fingerprint at both ends turns that from a mystery into a stated fact, and it is what
      lets a reader tell "the mesh is broken" apart from "the tree moved underneath the test".
    #>
    $root = Get-MeshBrokerRoot
    $fp = [ordered]@{
        at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); root = $root
        hash = $null; gitHead = $null; dirty = $null; files = @()
    }
    if (-not $root) { return [pscustomobject]$fp }
    $files = @(Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.js', '.mjs', '.json') -and $_.FullName -notmatch '\\node_modules\\' })
    $parts = @()
    foreach ($f in ($files | Sort-Object FullName)) {
        $h = (Get-FileHash $f.FullName -Algorithm SHA256).Hash
        $rel = $f.FullName.Substring($root.Length).TrimStart('\')
        $parts += "$rel=$h"
        $fp.files += ("{0}  {1}  {2}" -f $rel, $f.LastWriteTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'), $h.Substring(0, 12))
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $fp.hash = ([System.BitConverter]::ToString(
        $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes(($parts -join ';')))) -replace '-', '').Substring(0, 16)
    $repoRoot = Split-Path -Parent (Split-Path -Parent $root)
    try { $fp.gitHead = (& git -C $repoRoot rev-parse HEAD 2>$null | Select-Object -First 1) } catch { }
    try {
        $porcelain = (& git -C $repoRoot status --porcelain -- packages/mesh-broker 2>$null | Out-String).Trim()
        $fp.dirty = if ($porcelain) { $porcelain } else { '(clean)' }
    } catch { }
    return [pscustomobject]$fp
}

function Read-FileText([string]$Path) {
    <#
      Read a file another process is still writing, retrying instead of treating a lock as a fact.

      MEASURED 2026-09-16, three rounds x two stub gates, six files:
        * `[System.IO.File]::ReadAllText($path)` THREW MethodInvocationException on every single
          one of the six - a Start-Process -RedirectStandardOutput child holds the handle in a way
          that .NET's default share mode cannot open. It is the obvious call and it is the wrong one.
        * `Get-Content -Path $path -Raw -ErrorAction SilentlyContinue` returned the text 6 times
          out of 6.
      So: Get-Content, retried. This function was first written with ReadAllText and made the
      hermetic mesh fail deterministically - a self-inflicted regression that the final verification
      run caught, which is the entire argument for running the thing you just edited.
    #>
    for ($i = 0; $i -lt 6; $i++) {
        try {
            if (Test-Path $Path) {
                $text = Get-Content -Path $Path -Raw -ErrorAction SilentlyContinue
                if ($text) { return $text }
            }
        } catch { }
        Start-Sleep -Milliseconds 60
    }
    return ''
}

function Start-StubGate {
    param([string]$Node, [int]$Slots, [int]$DiskGiB = 236, [double]$Load1 = 0.42, [string]$Tag = 'g')
    $root = Get-MeshBrokerRoot
    $out = Join-Path $script:Scratch "gate-$Tag-$Node.out"
    $err = Join-Path $script:Scratch "gate-$Tag-$Node.err"
    # --in-use 0 matters: the stub's default is 2, and with slots=0 an inUse of 2 would still
    # floor to 0, but for the 5-slot mesh in §4.6 an implicit inUse of 2 would silently make
    # the mesh 3 slots and the test would pass while measuring the wrong thing.
    $nodeArgs = @('bin/mesh-stub-gate.mjs', '--node', $Node, '--slots', "$Slots",
              '--in-use', '0', '--disk-gib', "$DiskGiB", '--load1', "$Load1")
    $proc = Start-Process node -ArgumentList $nodeArgs -WorkingDirectory $root `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -NoNewWindow
    [void]$script:Procs.Add($proc)
    $url = $null
    foreach ($i in 1..200) {
        Start-Sleep -Milliseconds 120
        $text = Read-FileText $out
        if ($text -match 'at (http://127\.0\.0\.1:\d+)') { $url = $Matches[1]; break }
        if ($proc.HasExited) { break }
    }
    # A stub gate that does not start is a FAIL that must say WHY, like every other FAIL here.
    $diagnostic = $null
    if (-not $url) {
        $stderrText = (Read-FileText $err).Trim()
        $diagnostic = if ($proc.HasExited) {
            "the stub gate for '$Node' exited with code $($proc.ExitCode) before printing a URL"
        } else {
            "the stub gate for '$Node' never printed a URL within 24 s (pid $($proc.Id), still running)"
        }
        if ($stderrText) { $diagnostic += "; stderr: $stderrText" }
        $stdoutText = (Read-FileText $out).Trim()
        if ($stdoutText) { $diagnostic += "; stdout: $stdoutText" }
    }
    return [pscustomobject]@{ node = $Node; slots = $Slots; url = $url; proc = $proc; out = $out; err = $err; diagnostic = $diagnostic }
}

function Start-HermeticMesh {
    param(
        [object[]]$Spec,
        [int]$LeaseTtlMs = 60000,
        [int]$CacheTtlMs = 500,
        [int]$ReadTimeoutMs = 4000,
        [string]$Tag = 'mesh'
    )
    $root = Get-MeshBrokerRoot
    if (-not $root) {
        return [pscustomobject]@{ ok = $false; error = 'packages/mesh-broker/bin/mesh-broker.mjs not found'; gates = @(); procs = @() }
    }
    $gates = @()
    foreach ($s in $Spec) {
        $g = Start-StubGate -Node $s.node -Slots $s.slots -DiskGiB ($(if ($s.diskGiB) { $s.diskGiB } else { 236 })) `
                            -Load1 ($(if ($null -ne $s.load1) { $s.load1 } else { 0.42 })) -Tag $Tag
        $gates += $g
    }
    $missing = @($gates | Where-Object { -not $_.url })
    if ($missing.Count -gt 0) {
        $why = (($missing | ForEach-Object { $_.diagnostic }) -join ' | ')
        return [pscustomobject]@{ ok = $false; error = "stub gate(s) did not report a URL: $why"; gates = $gates; procs = @() }
    }
    $roster = [ordered]@{
        schema = 1; cacheTtlMs = $CacheTtlMs; readTimeoutMs = $ReadTimeoutMs; leaseTtlMs = $LeaseTtlMs
        nodes = @()
    }
    foreach ($g in $gates) {
        $spec = $Spec | Where-Object { $_.node -eq $g.node } | Select-Object -First 1
        $roster.nodes += [ordered]@{
            node = $g.node; fqdn = "$($g.node).mesh-acceptance.invalid"
            location = $(if ($spec.location) { $spec.location } else { 'home' })
            baseUrl = $g.url; excluded = $false
        }
    }
    $rosterPath = Join-Path $script:Scratch "roster-$Tag.json"
    $roster | ConvertTo-Json -Depth 8 | Set-Content -Path $rosterPath -Encoding UTF8
    $port = Get-FreePort
    $out = Join-Path $script:Scratch "broker-$Tag.out"
    $err = Join-Path $script:Scratch "broker-$Tag.err"
    $brokerArgs = @('bin/mesh-broker.mjs', '--port', "$port", '--host', '127.0.0.1', '--config', $rosterPath,
              '--cache-ttl-ms', "$CacheTtlMs", '--read-timeout-ms', "$ReadTimeoutMs", '--lease-ttl-ms', "$LeaseTtlMs")
    $proc = Start-Process node -ArgumentList $brokerArgs -WorkingDirectory $root `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -NoNewWindow
    [void]$script:Procs.Add($proc)
    $base = "http://127.0.0.1:$port"
    $up = $false; $ready = $false; $readyError = $null
    foreach ($i in 1..80) {
        Start-Sleep -Milliseconds 150
        if ($proc.HasExited) { break }
        $h = Invoke-Json -Url "$base/healthz" -Retries 1 -RetryGapMs 0 -Seconds 3
        if (-not $h.ok) { continue }
        $up = $true
        # /healthz proves the listener is up; it does NOT prove the mesh is usable. The mesh is
        # ready only when it can read its own nodes, because every assertion downstream begins
        # with GET /nodes?fresh=1 and a null there used to surface as a nonsense "-1 slots".
        $n = Invoke-Json -Url "$base/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 8
        if ($n.ok -and $n.doc.nodes -and @($n.doc.nodes).Count -ge @($gates).Count) { $ready = $true; break }
        $readyError = if ($n.ok) {
            "GET /nodes answered 200 but listed $(@($n.doc.nodes).Count) node(s) where $(@($gates).Count) gate(s) were started"
        } else {
            "GET /nodes?fresh=1: $($n.error)"
        }
    }
    $meshError = if (-not $up) {
        "the hermetic broker did not answer /healthz on $base"
    } elseif (-not $ready) {
        "the hermetic broker came up on $base but was never ready to be asked: $readyError"
    } else { $null }
    return [pscustomobject]@{
        ok = ($up -and $ready); error = $meshError
        base = $base; gates = $gates; proc = $proc; leaseTtlMs = $LeaseTtlMs
        roster = $rosterPath; log = $out; err = $err; tag = $Tag
    }
}

function Stop-HermeticMesh($Mesh) {
    if ($null -eq $Mesh) { return }
    foreach ($g in @($Mesh.gates)) {
        if ($g -and $g.proc -and -not $g.proc.HasExited) { Stop-Process -Id $g.proc.Id -Force -ErrorAction SilentlyContinue }
    }
    if ($Mesh.proc -and -not $Mesh.proc.HasExited) { Stop-Process -Id $Mesh.proc.Id -Force -ErrorAction SilentlyContinue }
}

function Stop-StubGate($Gate) {
    if ($Gate -and $Gate.proc -and -not $Gate.proc.HasExited) {
        Stop-Process -Id $Gate.proc.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 400
        return $true
    }
    return $false
}

function Get-GateCapacityDirect([string]$url) {
    $r = Invoke-Json -Url "$url/mesh/capacity" -Retries 2 -RetryGapMs 300 -Seconds 5
    return $r
}

# ===========================================================================
# run scratch + report
# ===========================================================================
$script:Scratch = Join-Path $env:USERPROFILE ".dsh\mesh\acceptance\$script:RunId"
New-Item -ItemType Directory -Force -Path $script:Scratch | Out-Null
if (-not $ReportPath) { $ReportPath = Join-Path $script:Scratch 'report.json' }

# The revision every hermetic sub-case will load, captured before the first one starts.
$sourceAtStart = Get-MeshSourceFingerprint

Write-Host ''
Write-Host 'MESH ACCEPTANCE HARNESS (stream S7)' -ForegroundColor White
Write-Host "  contract   $script:Contract"
Write-Host "  run        $script:RunId   from $script:Host0   started $script:StartedAt"
Write-Host "  evidence   $script:Scratch"
Write-Host '  rules      proxy OFF on every call; a timeout on every call; no engine is restarted;'
Write-Host '             no process is killed that this script did not start.'
Write-Host "  broker src $($sourceAtStart.hash)   git $($sourceAtStart.gitHead)"

# ---------------------------------------------------------------------------
# STEP 4 BASELINE (measured first, deliberately: the fleet is not dispatched yet, so these
# are the "before" numbers §4.4 will compare against once mesh-run exists)
# ---------------------------------------------------------------------------
$commitBefore = $null
try {
    $commitBefore = [double](Get-Counter '\Memory\Committed Bytes' -ErrorAction Stop).CounterSamples[0].CookedValue
} catch {
    try { $commitBefore = [double](Get-CimInstance Win32_PerfRawData_PerfOS_Memory -ErrorAction Stop).CommittedBytes } catch { }
}
$loopsBefore = $null
try {
    $hc = New-HttpClient 25
    $null = $hc.GetAsync("http://127.0.0.1:3086/").GetAwaiter().GetResult()   # the gate signs the caller in
    $hr = $hc.GetAsync("http://127.0.0.1:3086/healthz").GetAwaiter().GetResult()
    if ([int]$hr.StatusCode -eq 200) {
        $hj = $hr.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        $loopsBefore = $hj.sessions.agentLoopsRunning
    }
    $hc.Dispose()
} catch { }

# ===========================================================================
# STEP 1 — capacity is real
# ===========================================================================
Write-Head 'STEP 1 — capacity is real  (§4.1)'

$nodeResults = @()
foreach ($spec in ($NodeTable | Where-Object { ($Nodes -contains $_.name) -or ($Nodes -contains $_.ssh) })) {
    $cap = Get-Capacity $spec.fqdn
    $rec = [ordered]@{
        node = $spec.name; fqdn = $spec.fqdn; url = "https://$($spec.fqdn)/mesh/capacity"
        httpCode = $cap.code; latencyMs = $cap.latencyMs; attempts = $cap.attempts
        transportError = $cap.error; shapeProblems = @(); reportedNode = $null; gateAt = $null
        shape = 'unknown'; agreement = 'not tested'; direct = $null; deltaFreeMiB = $null
        toleranceMiB = $null; deltaTotalMiB = $null; verdict = 'SKIP'; why = ''
    }
    if ($cap.code -eq 200 -and $cap.doc) {
        $rec.reportedNode = $cap.doc.node
        $rec.gateAt = $cap.doc.at
        $problems = Test-CapacityShape $cap.doc
        $rec.shapeProblems = @($problems)
        $rec.shape = if ($problems.Count -eq 0) { 'ok' } else { 'invalid' }
        # The agreement question is asked whenever there is a number to compare - EVEN IF the
        # document is otherwise non-conformant. §4.1 asks two independent things ("answers a
        # schema-1 object" AND "the numbers agree"), and collapsing them would hide whether the
        # MEASUREMENTS are real behind an unrelated shape complaint. Measured reason: on
        # 2026-09-16 this laptop's gate got the node label wrong while its free-memory number was
        # right to within 22 MiB, and S1 needs to be told which of the two to fix.
        $fmRaw = $cap.doc.mem.freeMiB
        $fmIsNumber = ($fmRaw -is [int]) -or ($fmRaw -is [long]) -or ($fmRaw -is [double]) -or ($fmRaw -is [decimal])
        if ($fmIsNumber) {
            $direct = Get-DirectMemory $spec
            $rec.direct = $direct
            if ($null -ne $direct.freeMiB) {
                $tol = Get-FreeToleranceMiB $cap.doc.mem.totalMiB
                $rec.toleranceMiB = $tol
                $deltaFree = [int]$fmRaw - [int]$direct.freeMiB
                $rec.deltaFreeMiB = $deltaFree
                if ($null -ne $direct.totalMiB) { $rec.deltaTotalMiB = [int]$cap.doc.mem.totalMiB - [int]$direct.totalMiB }
                $totalOk = ($null -eq $direct.totalMiB) -or ([math]::Abs($rec.deltaTotalMiB) -le [math]::Max(64, [math]::Round($direct.totalMiB * 0.01)))
                if ([math]::Abs($deltaFree) -le $tol -and $totalOk) {
                    $rec.agreement = 'ok'
                    $rec.why = "freeMiB $fmRaw vs direct $($direct.freeMiB) (delta $deltaFree MiB, tolerance $tol); totalMiB $($cap.doc.mem.totalMiB) vs direct $($direct.totalMiB)"
                } else {
                    $rec.agreement = 'disagrees'
                    $rec.why = if (-not $totalOk) {
                        "totalMiB $($cap.doc.mem.totalMiB) vs direct $($direct.totalMiB) - total memory is a static fact and must agree"
                    } else {
                        "freeMiB $fmRaw vs direct $($direct.freeMiB) = delta $deltaFree MiB, outside the $tol MiB tolerance"
                    }
                }
            } else {
                $rec.agreement = 'unmeasurable'
                $rec.why = "no independent reader on $($spec.platform): $($direct.error)"
            }
        } else {
            $rec.agreement = 'unmeasurable'
            $rec.why = 'mem.freeMiB is not a number, so there is nothing to compare against'
        }
        # The verdict. A shape fault always fails; otherwise the measurement decides.
        if ($problems.Count -gt 0) {
            $rec.verdict = 'FAIL'
            $rec.why = 'HTTP 200 but the document does not match §2.1: ' + ($problems -join '; ') +
                       $(if ($rec.agreement -eq 'ok') { " -- THE NUMBERS THEMSELVES AGREE ($($rec.why)), so the fault is the label/shape, not the measurement" } else { '' })
        } elseif ($rec.agreement -eq 'ok') {
            $rec.verdict = 'PASS'
            $rec.why = "schema 1; $($rec.why)"
        } elseif ($rec.agreement -eq 'unmeasurable') {
            $rec.verdict = 'SKIP'
            $rec.why = "schema 1 and well-formed, but the agreement half of §4.1 could not be tested: $($rec.why)"
        } else {
            $rec.verdict = 'FAIL'
            $rec.why = 'schema 1 but the numbers do not agree: ' + $rec.why
        }
    } else {
        # not answering. Why matters, because it decides FAIL vs SKIP.
        $facts = Get-NodeFacts $spec
        $published = ($facts.serve -match 'tailscale') -or ($facts.serve -match 'proxy http')
        $rec.direct = [pscustomobject]@{ serve = $facts.serve; listener = $facts.listener; gate = $facts.gate }
        if ($cap.code -eq 0) {
            $rec.verdict = 'SKIP'
            $rec.why = "nothing is published on $($spec.fqdn):443 ($($cap.error)). " +
                       "FOR THIS TO RUN: a gate must be deployed on $($spec.name) and published with 'tailscale serve' (stream S1/S2)."
        } elseif ($cap.code -eq 404) {
            $rec.verdict = 'FAIL'
            $rec.why = "the gate answered 404 for /mesh/capacity: the route exists in the file but not in the process that is " +
                       "serving (a gate started before the route landed does not reload it - Python does not hot-reload). " +
                       "Gate facts: $($facts.gate)"
        } elseif ($cap.code -eq 502) {
            $rec.verdict = 'FAIL'
            $rec.why = "502 through 'tailscale serve': the URL is published but nothing answers on the port it proxies to. " +
                       "This is the failure scripts/mesh-health.ps1 exists to name. Serve: $($facts.serve); listener on 3086: $($facts.listener)"
        } else {
            $rec.verdict = 'FAIL'
            $rec.why = "HTTP $($cap.code) from $($spec.fqdn)/mesh/capacity (after $($cap.attempts) attempt(s)): $($cap.transportError)"
        }
    }
    $nodeResults += [pscustomobject]$rec
}

$anyCapacityAnswered = @($nodeResults | Where-Object { $_.shape -eq 'ok' -or $_.shape -eq 'invalid' }).Count -gt 0
if (-not $anyCapacityAnswered) {
    # NOTHING on the mesh serves a parseable §2.1 document yet. Then §4.1 cannot be attempted at
    # all, and every node is a SKIP rather than a FAIL - the capability has not been built
    # anywhere. Note this is "answered at all", not "answered correctly": a fleet whose gates all
    # answer but all get the label wrong HAS built the capability and must FAIL loudly.
    foreach ($r in $nodeResults) {
        if ($r.verdict -eq 'FAIL') {
            $r.verdict = 'SKIP'
            $r.why = 'the capacity surface exists nowhere in the fleet yet, so §4.1 cannot be attempted. ' +
                     'FOR THIS TO RUN: stream S1 must ship GET /mesh/capacity in scripts/phone-gate.py and deploy a gate on this node. ' + $r.why
        }
    }
}

$nodeDetail = @()
foreach ($r in $nodeResults) {
    $extra = ''
    if ($r.shape -eq 'ok' -and $null -ne $r.deltaFreeMiB) { $extra = " | free delta $($r.deltaFreeMiB) MiB (tol $($r.toleranceMiB))" }
    if ($r.reportedNode -and $r.reportedNode -ne $r.node) { $extra += " | the gate names itself '$($r.reportedNode)' where this harness asked for '$($r.node)'" }
    $nodeDetail += ("{0,-11} {1,-4} HTTP {2,-4} {3,6} ms{4}" -f $r.node, $r.verdict, $r.httpCode, $r.latencyMs, $extra)
    $nodeDetail += ("            why: {0}" -f $r.why)
}
$passCount = @($nodeResults | Where-Object { $_.verdict -eq 'PASS' }).Count
$failCount = @($nodeResults | Where-Object { $_.verdict -eq 'FAIL' }).Count
$skipCount = @($nodeResults | Where-Object { $_.verdict -eq 'SKIP' }).Count
$step1Status = if ($failCount -gt 0) { 'FAIL' } elseif ($skipCount -gt 0) { 'SKIP' } else { 'PASS' }
$step1Evidence = "$passCount of $($nodeResults.Count) node(s) answering a schema-1 object that agrees with an independent measurement taken at the same moment; $failCount FAIL, $skipCount SKIP"
Add-Step -Id 'S1' -Name 'capacity is real (§4.1)' -Status $step1Status -Evidence $step1Evidence -Detail $nodeDetail

# ===========================================================================
# STEP 2 — placement decides
# ===========================================================================
Write-Head 'STEP 2 — placement decides  (§4.2)'

$step2Detail = New-Object System.Collections.ArrayList
$step2Sub = New-Object System.Collections.ArrayList   # PASS/FAIL/SKIP per sub-case
$step2Evidence = ''
$hermeticAvailable = (-not $SkipHermetic) -and ($null -ne (Get-MeshBrokerRoot))

function Add-Sub {
    param($List, [string]$Name, [string]$Status, [string]$Why)
    [void]$List.Add([pscustomobject]@{ name = $Name; status = $Status; why = $Why })
    [void]$step2Detail.Add(("  {0,-34} {1,-4} {2}" -f $Name, $Status, $Why))
}

# --- 2a: a 6-child fleet is named, with the slot arithmetic in the rationale -----------
$liveBroker = $null
if ($BrokerUrl) {
    $liveBroker = $BrokerUrl.TrimEnd('/')
} elseif ($env:MESH_BROKER_URL) {
    $liveBroker = $env:MESH_BROKER_URL.TrimEnd('/')
} else {
    foreach ($candidate in @("http://127.0.0.1:$BrokerPort")) {
        $h = Invoke-Json -Url "$candidate/healthz" -Retries 1 -RetryGapMs 0 -Seconds 4
        if ($h.ok) { $liveBroker = $candidate; break }
    }
    if (-not $liveBroker) {
        # The deployed broker binds loopback on the authority. A tunnel is the only way to ask
        # it a question from here, and it changes nothing on either machine.
        $tunnelPort = Get-FreePort
        $fwd = "$tunnelPort" + ":127.0.0.1:$BrokerPort"
        $tErr = Join-Path $script:Scratch 'tunnel.err'
        $tProc = Start-Process ssh -ArgumentList @('-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
                '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10', '-L', $fwd, $SshBrokerHost) `
            -PassThru -NoNewWindow -RedirectStandardError $tErr
        [void]$script:Procs.Add($tProc)
        foreach ($i in 1..40) {
            Start-Sleep -Milliseconds 150
            $h = Invoke-Json -Url "http://127.0.0.1:$tunnelPort/healthz" -Retries 1 -RetryGapMs 0 -Seconds 4
            if ($h.ok) { $liveBroker = "http://127.0.0.1:$tunnelPort"; break }
            if ($tProc.HasExited) { break }
        }
        [void]$script:Notes.Add("live broker reached through an ssh tunnel to $SshBrokerHost (local port $tunnelPort): the deployed broker listens on loopback only")
    }
}

if ($liveBroker) {
    $hb = Invoke-Json -Url "$liveBroker/healthz" -Retries 1 -RetryGapMs 0 -Seconds 6
    $liveNodes = Invoke-Json -Url "$liveBroker/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 25
    [void]$step2Detail.Add("  live broker at $liveBroker : healthz $($hb.code), /nodes?fresh=1 $($liveNodes.code)")
    if ($liveNodes.ok) {
        foreach ($n in $liveNodes.doc.nodes) {
            $state = if ($n.unreachable) { "unreachable ($($n.reason))" } else { "slots $($n.slots), free $($n.freeSlots)" }
            [void]$step2Detail.Add("    node $($n.node): $state")
        }
    }
    $body = '{"task":{"kind":"fleet","children":6,"worktreeGiB":0}}'
    $place = Invoke-Json -Url "$liveBroker/place" -Method POST -Body $body -Retries 1 -RetryGapMs 0 -Seconds 30
    if ($place.ok) {
        $p = $place.doc
        $joined = ($p.rationale -join ' ')
        $hasName = [bool]$p.node
        $hasArith = ($joined -match "$MESH_GOVERNOR_RESERVE_MIB") -and ($joined -match "$MESH_PER_SLOT_MIB MiB") -and ($joined -match 'slot')
        $hasPosition = ($joined -match 'position \d+:')
        $why = "node=$($p.node) position=$($p.position) score=$($p.score) eligible=$($p.eligible) tier=$($p.tier); rationale has $(@($p.rationale).Count) line(s)"
        if (-not (Test-TaskEcho $p 'fleet' 6)) {
            Add-Sub $step2Sub 'live broker names a node' 'FAIL' "$why -- the broker reports kind='$($p.kind)' children=$($p.children): the 6-child fleet this test sent did not ARRIVE as one, so nothing else here would be about §4.2"
        } elseif ($hasName -and $hasArith -and $hasPosition -and @($p.rationale).Count -gt 0) {
            Add-Sub $step2Sub 'live broker names a node' 'PASS' "$why; the broker confirms it read a fleet of $($p.children) child(ren)"
            [void]$step2Detail.Add("    arithmetic line: " + (@($p.rationale) | Where-Object { $_ -match "$MESH_GOVERNOR_RESERVE_MIB" } | Select-Object -First 1))
        } else {
            Add-Sub $step2Sub 'live broker names a node' 'FAIL' "$why -- rationale is missing the slot arithmetic (need $MESH_GOVERNOR_RESERVE_MIB, $MESH_PER_SLOT_MIB MiB, a position line)"
        }
        if ($p.lease) {
            $done = Invoke-Json -Url "$liveBroker/done" -Method POST -Body ('{"lease":"' + $p.lease + '","ok":true}') -Retries 1 -RetryGapMs 0 -Seconds 10
            if ($done.ok -and $done.doc.released -eq $true) {
                Add-Sub $step2Sub 'live lease released via /done' 'PASS' "POST /done released lease $($p.lease) on $($p.node) (§2.2), so this test left the live mesh exactly as it found it"
            } else {
                Add-Sub $step2Sub 'live lease released via /done' 'FAIL' "POST /done answered HTTP $($done.code) released='$($done.doc.released)' reason='$($done.doc.reason)' - a live lease was left on $($p.node) for up to $($p.leaseTtlSec) s, which perturbs every other stream's view of that node"
            }
        }
    } else {
        Add-Sub $step2Sub 'live broker names a node' 'FAIL' "POST /place on the live broker answered HTTP $($place.code): $($place.transportError)"
    }
} else {
    Add-Sub $step2Sub 'live broker names a node' 'SKIP' 'no live broker reachable (loopback :3091, the tailnet, and an ssh tunnel to ' + $SshBrokerHost + ' all failed). FOR THIS TO RUN: the broker deployed on the authority and reachable from here.'
}

# --- 2b/2c: the hermetic mesh, which is the only place a capacity can be forced ---------
if (-not $hermeticAvailable) {
    $why = if ($SkipHermetic) { '-SkipHermetic was given' } else { 'packages/mesh-broker/bin/mesh-broker.mjs not found' }
    Add-Sub $step2Sub 'force one node to zero' 'SKIP' "$why. FOR THIS TO RUN: stream S5 packages/mesh-broker (its stub gate + broker) present."
    Add-Sub $step2Sub 'all nodes low -> position > 0' 'SKIP' "$why. FOR THIS TO RUN: stream S5 packages/mesh-broker present."
} else {
    # 2b: two identical nodes fit a 6-child fleet; then one is forced to zero capacity.
    $meshA = Start-HermeticMesh -Tag 's2a' -Spec @(
        [pscustomobject]@{ node = 'alpha'; slots = 10; diskGiB = 236; load1 = 0.10; location = 'home' }
        [pscustomobject]@{ node = 'beta'; slots = 10; diskGiB = 236; load1 = 0.42; location = 'office' })
    if (-not $meshA.ok) {
        Add-Sub $step2Sub 'force one node to zero' 'FAIL' $meshA.error
        Add-Sub $step2Sub 'all nodes low -> position > 0' 'FAIL' $meshA.error
    } else {
        $capA = Get-GateCapacityDirect $meshA.gates[0].url
        $stubFree = $null; $stubFree = if ($capA.ok) { [int]$capA.doc.mem.freeMiB } else { $null }
        $r1 = Invoke-Json -Url "$($meshA.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
        $firstName = if ($r1.ok) { $r1.doc.node } else { $null }
        # The strongest available proof that the arithmetic is live and not a template: the
        # chosen node's own measured freeMiB must appear in the rationale.
        $namedNumbers = $false
        if ($r1.ok -and $null -ne $stubFree) {
            $joined = ($r1.doc.rationale -join ' ')
            $namedNumbers = $joined -match "$stubFree MiB free"
        }
        if ($r1.ok -and -not (Test-TaskEcho $r1.doc 'fleet' 6)) {
            Add-Sub $step2Sub 'names a node + slot arithmetic' 'FAIL' "the broker reports kind='$($r1.doc.kind)' children=$($r1.doc.children): the 6-child fleet did not arrive as one"
        } elseif ($r1.ok -and $firstName -and @($r1.doc.rationale).Count -gt 0 -and $namedNumbers) {
            Add-Sub $step2Sub 'names a node + slot arithmetic' 'PASS' "mesh 10/10 slots, a fleet of $($r1.doc.children) -> node=$firstName position=$($r1.doc.position) tier=$($r1.doc.tier); the rationale quotes the gate's own measured $stubFree MiB free"
        } elseif ($r1.ok) {
            Add-Sub $step2Sub 'names a node + slot arithmetic' 'FAIL' "node=$($r1.doc.node) but the rationale does not quote the measured $stubFree MiB free - the arithmetic is not the one the mesh measured"
        } else {
            Add-Sub $step2Sub 'names a node + slot arithmetic' 'FAIL' "POST /place answered HTTP $($r1.code)"
        }
        if ($r1.ok -and $r1.doc.lease) {
            $null = Invoke-Json -Url "$($meshA.base)/done" -Method POST -Body ('{"lease":"' + $r1.doc.lease + '","ok":true}') -Retries 1 -RetryGapMs 0 -Seconds 8
        }
        Stop-HermeticMesh $meshA

        # now the same shape, with alpha's capacity forced to zero: a fresh mesh, so there is
        # no cache to argue with.
        $meshB = Start-HermeticMesh -Tag 's2b' -Spec @(
            [pscustomobject]@{ node = 'alpha'; slots = 0; diskGiB = 236; load1 = 0.10; location = 'home' }
            [pscustomobject]@{ node = 'beta'; slots = 10; diskGiB = 236; load1 = 0.42; location = 'office' })
        if (-not $meshB.ok) {
            Add-Sub $step2Sub 'force one node to zero' 'FAIL' $meshB.error
        } else {
            $null = Invoke-Json -Url "$($meshB.base)/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 15
            $r2 = Invoke-Json -Url "$($meshB.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
            if ($r2.ok -and $r2.doc.node -eq 'beta' -and $r2.doc.position -eq 0 -and (Test-TaskEcho $r2.doc 'fleet' 6)) {
                Add-Sub $step2Sub 'force one node to zero' 'PASS' "alpha forced to 0 slot(s), beta at 10, fleet of $($r2.doc.children) -> the broker named beta (position 0). It did not name the node with no room."
            } elseif ($r2.ok -and -not (Test-TaskEcho $r2.doc 'fleet' 6)) {
                Add-Sub $step2Sub 'force one node to zero' 'FAIL' "the broker reports kind='$($r2.doc.kind)' children=$($r2.doc.children): the 6-child fleet did not arrive as one"
            } elseif ($r2.ok) {
                Add-Sub $step2Sub 'force one node to zero' 'FAIL' "alpha was forced to 0 slot(s) but the broker named '$($r2.doc.node)' (position $($r2.doc.position)); beta had 10 slots"
            } else {
                Add-Sub $step2Sub 'force one node to zero' 'FAIL' "POST /place answered HTTP $($r2.code)"
            }
            if ($r2.ok -and $r2.doc.lease) {
                $null = Invoke-Json -Url "$($meshB.base)/done" -Method POST -Body ('{"lease":"' + $r2.doc.lease + '","ok":true}') -Retries 1 -RetryGapMs 0 -Seconds 8
            }
            Stop-HermeticMesh $meshB
        }

        # 2c: every node low. This is still a placement, never an error.
        $meshC = Start-HermeticMesh -Tag 's2c' -Spec @(
            [pscustomobject]@{ node = 'alpha'; slots = 0; diskGiB = 236; load1 = 0.10; location = 'home' }
            [pscustomobject]@{ node = 'beta'; slots = 0; diskGiB = 236; load1 = 0.42; location = 'office' })
        if (-not $meshC.ok) {
            Add-Sub $step2Sub 'all nodes low -> position > 0' 'FAIL' $meshC.error
        } else {
            $null = Invoke-Json -Url "$($meshC.base)/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 15
            $r3 = Invoke-Json -Url "$($meshC.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
            if ($r3.code -eq 200 -and $r3.ok -and $r3.doc.node -and [int]$r3.doc.position -gt 0 -and (Test-TaskEcho $r3.doc 'fleet' 6)) {
                Add-Sub $step2Sub 'all nodes low -> position > 0' 'PASS' "every node at 0 slot(s), fleet of $($r3.doc.children): HTTP 200, node=$($r3.doc.node), position=$($r3.doc.position), tier=$($r3.doc.tier) - queued, not refused"
            } elseif ($r3.code -eq 200 -and -not (Test-TaskEcho $r3.doc 'fleet' 6)) {
                Add-Sub $step2Sub 'all nodes low -> position > 0' 'FAIL' "the broker reports kind='$($r3.doc.kind)' children=$($r3.doc.children): the 6-child fleet did not arrive as one"
            } elseif ($r3.code -eq 200) {
                Add-Sub $step2Sub 'all nodes low -> position > 0' 'FAIL' "HTTP 200 but position=$($r3.doc.position) (must be > 0 when nothing fits) and node='$($r3.doc.node)'"
            } else {
                Add-Sub $step2Sub 'all nodes low -> position > 0' 'FAIL' "with every node low the broker answered HTTP $($r3.code) - §2.2 says there is no error path on /place"
            }
            if ($r3.ok -and $r3.doc.lease) {
                $null = Invoke-Json -Url "$($meshC.base)/done" -Method POST -Body ('{"lease":"' + $r3.doc.lease + '","ok":true}') -Retries 1 -RetryGapMs 0 -Seconds 8
            }
            Stop-HermeticMesh $meshC
        }
    }
}

$s2Fail = @($step2Sub | Where-Object { $_.status -eq 'FAIL' }).Count
$s2Skip = @($step2Sub | Where-Object { $_.status -eq 'SKIP' }).Count
$s2Pass = @($step2Sub | Where-Object { $_.status -eq 'PASS' }).Count
$step2Status = if ($s2Fail -gt 0) { 'FAIL' } elseif ($s2Skip -gt 0) { 'SKIP' } else { 'PASS' }
$step2Evidence = "$s2Pass sub-case(s) PASS, $s2Fail FAIL, $s2Skip SKIP (of $(@($step2Sub).Count))"
Add-Step -Id 'S2' -Name 'placement decides (§4.2)' -Status $step2Status -Evidence $step2Evidence -Detail @($step2Detail)

# ===========================================================================
# STEP 3 — work lands there
# ===========================================================================
Write-Head 'STEP 3 — work lands there  (§4.3)'

$scriptDir = Split-Path -Parent $PSCommandPath
$meshRunPath = Join-Path $scriptDir 'mesh-run.ps1'
$meshRunExists = Test-Path $meshRunPath
$pluginMeshExists = Test-Path (Join-Path (Split-Path -Parent $scriptDir) 'packages\plugin-mesh')

$step3Detail = New-Object System.Collections.ArrayList
if ($meshRunExists) {
    # The dispatcher exists. This harness still cannot assert PASS without running it, and it
    # must not run a fleet on its own initiative without the caller asking. So: report the
    # dependency as present and require a real fleet run to be pointed at it.
    $step3Evidence = "scripts\mesh-run.ps1 is present but this harness does not dispatch fleets by itself - §4.3 needs a real run whose MESH-HOST: lines are checked against the broker's choice"
    [void]$step3Detail.Add('  mesh-run.ps1 present: ' + $meshRunPath)
    [void]$step3Detail.Add('  the implementation is packages/plugin-remote-fanout/bin/mesh-run.mjs; scripts/mesh-run.ps1 is a 16-line shim that forwards to it')
    [void]$step3Detail.Add('  TO COMPLETE: dispatch the 6-child fleet and match every MESH-HOST: line to the node the broker named.')
    [void]$step3Detail.Add('  THIS HARNESS DOES NOT FIRE A FLEET BY ITSELF: that spends money and occupies other people''s machines, which is a decision, not a default.')
    Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'SKIP' -Evidence $step3Evidence -Detail @($step3Detail)
} else {
    $step3Evidence = 'scripts\mesh-run.ps1 does not exist, so no fleet can be dispatched and no MESH-HOST: line can be produced'
    [void]$step3Detail.Add('  FOR THIS TO RUN: stream S6 must ship scripts/mesh-run.ps1 (and packages/plugin-mesh for the v2 route)')
    [void]$step3Detail.Add('  (packages/plugin-mesh present: ' + $pluginMeshExists + ')')
    Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'SKIP' -Evidence $step3Evidence -Detail @($step3Detail)
}

# --- 3b: the part of §4.3 the broker owes, and which can be proven today ----------------
$step3bDetail = New-Object System.Collections.ArrayList
if (-not $hermeticAvailable) {
    Add-Step -Id 'S3b' -Name 'broker spreads across 2 nodes' -Status 'SKIP' `
        -Evidence 'the hermetic mesh cannot start, so placement across two free nodes cannot be forced' `
        -Detail @('  FOR THIS TO RUN: stream S5 packages/mesh-broker present (or run without -SkipHermetic).')
} else {
    $meshD = Start-HermeticMesh -Tag 's3b' -Spec @(
        [pscustomobject]@{ node = 'alpha'; slots = 10; diskGiB = 236; load1 = 0.10; location = 'home' }
        [pscustomobject]@{ node = 'beta'; slots = 10; diskGiB = 236; load1 = 0.42; location = 'office' })
    if (-not $meshD.ok) {
        Add-Step -Id 'S3b' -Name 'broker spreads across 2 nodes' -Status 'FAIL' -Evidence $meshD.error
    } else {
        $null = Invoke-Json -Url "$($meshD.base)/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 15
        $q1 = Invoke-Json -Url "$($meshD.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
        $q2 = Invoke-Json -Url "$($meshD.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
        $n1 = if ($q1.ok) { $q1.doc.node } else { $null }
        $n2 = if ($q2.ok) { $q2.doc.node } else { $null }
        [void]$step3bDetail.Add("  two 6-child fleets against alpha(10 slots) + beta(10 slots): first named '$n1' (pos $(if($q1.ok){$q1.doc.position}else{'?'})), second named '$n2' (pos $(if($q2.ok){$q2.doc.position}else{'?'}))")
        if ($n1 -and $n2 -and $n1 -ne $n2 -and $q1.code -eq 200 -and $q2.code -eq 200 `
            -and (Test-TaskEcho $q1.doc 'fleet' 6) -and (Test-TaskEcho $q2.doc 'fleet' 6)) {
            Add-Step -Id 'S3b' -Name 'broker spreads across 2 nodes' -Status 'PASS' `
                -Evidence "with two nodes free, two 6-child fleets were named on two distinct nodes ($n1 then $n2) - §4.3's 'at least two distinct nodes when two are free' is a property of the broker and it holds" `
                -Detail @($step3bDetail)
        } else {
            Add-Step -Id 'S3b' -Name 'broker spreads across 2 nodes' -Status 'FAIL' `
                -Evidence "two free nodes but the placements named '$n1' then '$n2' (HTTP $($q1.code), $($q2.code)) - the broker is not spreading work across the mesh" `
                -Detail @($step3bDetail)
        }
        foreach ($q in @($q1, $q2)) {
            if ($q.ok -and $q.doc.lease) {
                $null = Invoke-Json -Url "$($meshD.base)/done" -Method POST -Body ('{"lease":"' + $q.doc.lease + '","ok":true}') -Retries 1 -RetryGapMs 0 -Seconds 8
            }
        }
        Stop-HermeticMesh $meshD
    }
}

# ===========================================================================
# STEP 4 — the client stays flat
# ===========================================================================
Write-Head 'STEP 4 — the client stays flat  (§4.4)'

$commitAfter = $null
try { $commitAfter = [double](Get-Counter '\Memory\Committed Bytes' -ErrorAction Stop).CounterSamples[0].CookedValue } catch { }
$loopsAfter = $null
try {
    $hc2 = New-HttpClient 25
    $null = $hc2.GetAsync("http://127.0.0.1:3086/").GetAwaiter().GetResult()
    $hr2 = $hc2.GetAsync("http://127.0.0.1:3086/healthz").GetAwaiter().GetResult()
    if ([int]$hr2.StatusCode -eq 200) {
        $hj2 = $hr2.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        $loopsAfter = $hj2.sessions.agentLoopsRunning
    }
    $hc2.Dispose()
} catch { }

$step4Detail = New-Object System.Collections.ArrayList
$commitDeltaGiB = $null
if ($null -ne $commitBefore -and $null -ne $commitAfter) {
    $commitDeltaGiB = [math]::Round(($commitAfter - $commitBefore) / 1GB, 3)
    [void]$step4Detail.Add("  commit before $([math]::Round($commitBefore/1GB,2)) GiB -> after $([math]::Round($commitAfter/1GB,2)) GiB (delta $commitDeltaGiB GiB, tolerance ±1 GiB)")
}
[void]$step4Detail.Add("  agentLoopsRunning before $loopsBefore -> after $loopsAfter  (source: GET /healthz on this laptop, via the gate at 127.0.0.1:3086)")
[void]$step4Detail.Add('  THESE ARE MEASUREMENTS OF THIS HARNESS, NOT OF A FLEET: no fleet was dispatched, so nothing ran on another node and there is nothing for the laptop to have absorbed.')

if (-not $meshRunExists) {
    Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'SKIP' `
        -Evidence 'no fleet can be dispatched without scripts\mesh-run.ps1, so "commit flat while the children run" has no children to be flat during' `
        -Detail @($step4Detail + @('  FOR THIS TO RUN: stream S6 scripts/mesh-run.ps1, then re-run this harness; the before/after machinery is already here.'))
} else {
    Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'SKIP' `
        -Evidence 'mesh-run.ps1 is present, but this harness does not dispatch a fleet by itself; §4.4 needs a real 6-child run to bracket' `
        -Detail @($step4Detail)
}

# ===========================================================================
# STEP 5 — a node can die
# ===========================================================================
Write-Head 'STEP 5 — a node can die  (§4.5)'

$step5Detail = New-Object System.Collections.ArrayList
if (-not $meshRunExists) {
    $step5Evidence = 'scripts\mesh-run.ps1 does not exist: the run that must fail with exit 1 mid-fleet cannot be started, so the gate cannot be killed mid-run'
    [void]$step5Detail.Add('  FOR THIS TO RUN: stream S6 scripts/mesh-run.ps1. Then this step kills the CHOSEN NODE''S GATE')
    [void]$step5Detail.Add('  (never an engine), asserts exit 1 plus a log naming that node, asserts the broker reclaims the lease,')
    [void]$step5Detail.Add('  and asserts the next mesh-run succeeds on another node with no manual repair.')
    Add-Step -Id 'S5' -Name 'a node can die (§4.5)' -Status 'SKIP' -Evidence $step5Evidence -Detail @($step5Detail)
} else {
    Add-Step -Id 'S5' -Name 'a node can die (§4.5)' -Status 'SKIP' `
        -Evidence 'mesh-run.ps1 is present but this harness does not dispatch a fleet by itself, so a mid-run gate kill cannot be arranged here' `
        -Detail @(
            '  NOTE - §4.5 AS WRITTEN CONFLICTS WITH THIS HARNESS''S OWN RULES, and the conflict is the manager''s to resolve:',
            '  "kill the chosen node''s gate mid-run" means killing the gate a DIFFERENT stream deployed and is running on a node',
            '  this harness does not own, while S7''s brief says "never kill a process that is not a gate you started".',
            '  The two sanctioned ways out: (a) accept STEP 5b, which kills a stub gate THIS harness started and proves the same',
            '  broker-side property; or (b) have the manager state, for one named node and one named pid, that the gate may be killed.',
            '  Until then §4.5''s kill half is deliberately not executed, because a green result is worth less than the rule that stops it.'
        )
}

# --- 5b: the broker's half of §4.5, which exists and can be tested today ----------------
$step5bDetail = New-Object System.Collections.ArrayList
$step5bSub = New-Object System.Collections.ArrayList
if (-not $hermeticAvailable) {
    Add-Step -Id 'S5b' -Name 'broker half of §4.5' -Status 'SKIP' `
        -Evidence 'the hermetic mesh cannot start, so a gate cannot be killed and a lease cannot be left to expire under controlled conditions' `
        -Detail @('  FOR THIS TO RUN: stream S5 packages/mesh-broker present (or run without -SkipHermetic).')
} else {
    # (i) kill a gate mid-flight: the broker must stop choosing it, with no manual repair
    $meshE = Start-HermeticMesh -Tag 's5bi' -Spec @(
        [pscustomobject]@{ node = 'alpha'; slots = 10; diskGiB = 236; load1 = 0.10; location = 'home' }
        [pscustomobject]@{ node = 'beta'; slots = 10; diskGiB = 236; load1 = 0.42; location = 'office' }) -CacheTtlMs 500
    if (-not $meshE.ok) {
        [void]$step5bSub.Add([pscustomobject]@{ name = 'gate dies -> broker avoids it'; status = 'FAIL'; why = $meshE.error })
        [void]$step5bDetail.Add('  ' + $meshE.error)
    } else {
        $null = Invoke-Json -Url "$($meshE.base)/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 15
        $k1 = Invoke-Json -Url "$($meshE.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
        $victim = if ($k1.ok) { $k1.doc.node } else { $null }
        $victimGate = $meshE.gates | Where-Object { $_.node -eq $victim } | Select-Object -First 1
        $killed = Stop-StubGate $victimGate
        Start-Sleep -Milliseconds 1200      # let the broker's 500 ms reading cache expire
        $k2 = Invoke-Json -Url "$($meshE.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
        $survivor = if ($k2.ok) { $k2.doc.node } else { $null }
        [void]$step5bDetail.Add("  the broker first chose '$victim'; that node's GATE (a stub this harness started, pid $($victimGate.proc.Id)) was killed: killed=$killed")
        [void]$step5bDetail.Add("  the next placement answered HTTP $($k2.code) and named '$survivor' (position $(if($k2.ok){$k2.doc.position}else{'?'})) with no manual repair")
        if ($killed -and $k2.code -eq 200 -and $survivor -and $survivor -ne $victim -and (Test-TaskEcho $k2.doc 'fleet' 6)) {
            [void]$step5bSub.Add([pscustomobject]@{ name = 'gate dies -> broker avoids it'; status = 'PASS'; why = "chose '$victim', gate killed, next placement named '$survivor' with HTTP 200 - no journal repair, no restart, no human" })
        } else {
            [void]$step5bSub.Add([pscustomobject]@{ name = 'gate dies -> broker avoids it'; status = 'FAIL'; why = "victim='$victim' killed=$killed, next placement HTTP $($k2.code) named '$survivor'" })
        }
        foreach ($k in @($k1, $k2)) {
            if ($k.ok -and $k.doc.lease) {
                $null = Invoke-Json -Url "$($meshE.base)/done" -Method POST -Body ('{"lease":"' + $k.doc.lease + '","ok":true}') -Retries 1 -RetryGapMs 0 -Seconds 8
            }
        }
        Stop-HermeticMesh $meshE
    }

    # (ii) an abandoned lease is reclaimed by the broker at its TTL, not by anyone noticing
    $ttl = 3000
    $meshF = Start-HermeticMesh -Tag 's5bii' -LeaseTtlMs $ttl -Spec @(
        [pscustomobject]@{ node = 'alpha'; slots = 10; diskGiB = 236; load1 = 0.10; location = 'home' })
    if (-not $meshF.ok) {
        [void]$step5bSub.Add([pscustomobject]@{ name = 'lease reclaimed within TTL'; status = 'FAIL'; why = $meshF.error })
    } else {
        $null = Invoke-Json -Url "$($meshF.base)/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 15
        $abandon = Invoke-Json -Url "$($meshF.base)/place" -Method POST -Body '{"task":{"kind":"fleet","children":6}}' -Retries 1 -RetryGapMs 0 -Seconds 15
        if (-not $abandon.ok) {
            [void]$step5bSub.Add([pscustomobject]@{ name = 'lease reclaimed within TTL'; status = 'FAIL'; why = "POST /place answered HTTP $($abandon.code)" })
        } else {
            # deliberately NOT calling /done: this is the dead-dispatcher case.
            $waitStart = Get-Date
            $reclaimed = $false; $elapsedMs = 0
            foreach ($i in 1..40) {
                Start-Sleep -Milliseconds 250
                $hs = Invoke-Json -Url "$($meshF.base)/healthz" -Retries 1 -RetryGapMs 0 -Seconds 5
                $elapsedMs = [int]((Get-Date) - $waitStart).TotalMilliseconds
                if ($hs.ok -and [int]$hs.doc.leases.live -eq 0) { $reclaimed = $true; break }
            }
            [void]$step5bDetail.Add("  an abandoned lease (ttl ${ttl} ms, POST /done deliberately never sent) went from live=1 to live=0 after $elapsedMs ms")
            [void]$step5bDetail.Add("  (the abandoned placement echoed kind='$($abandon.doc.kind)' children=$($abandon.doc.children) - proving the body arrived, so the lease under test is the one that was asked for)")
            $slackMs = 2000
            if ($reclaimed -and $elapsedMs -le ($ttl + $slackMs)) {
                [void]$step5bSub.Add([pscustomobject]@{ name = 'lease reclaimed within TTL'; status = 'PASS'; why = "reclaimed $elapsedMs ms after issue, within the ${ttl} ms TTL (+${slackMs} ms poll slack): the broker outlives a dead dispatcher by itself" })
            } else {
                [void]$step5bSub.Add([pscustomobject]@{ name = 'lease reclaimed within TTL'; status = 'FAIL'; why = "reclaimed=$reclaimed after $elapsedMs ms against a ${ttl} ms TTL" })
            }
        }
        Stop-HermeticMesh $meshF
    }

    $s5bFail = @($step5bSub | Where-Object { $_.status -eq 'FAIL' }).Count
    $s5bPass = @($step5bSub | Where-Object { $_.status -eq 'PASS' }).Count
    foreach ($x in $step5bSub) { [void]$step5bDetail.Add(("  {0,-34} {1,-4} {2}" -f $x.name, $x.status, $x.why)) }
    Add-Step -Id 'S5b' -Name 'broker half of §4.5' -Status $(if ($s5bFail -gt 0) { 'FAIL' } else { 'PASS' }) `
        -Evidence "$s5bPass of $(@($step5bSub).Count) broker-side sub-case(s) of §4.5 hold: the broker stops choosing a node whose gate died, and it reclaims an abandoned lease at its own TTL" `
        -Detail @($step5bDetail)
}

# ===========================================================================
# STEP 6 — queue, never amputate
# ===========================================================================
Write-Head 'STEP 6 — queue, never amputate  (§4.6)'

$step6Detail = New-Object System.Collections.ArrayList
if (-not $hermeticAvailable) {
    Add-Step -Id 'S6' -Name 'queue, never amputate (§4.6)' -Status 'SKIP' `
        -Evidence 'a mesh with exactly 5 slots cannot be built without the hermetic mesh, and firing 30 placements at the LIVE broker would leave 30 leases on real nodes for 15 minutes' `
        -Detail @('  FOR THIS TO RUN: stream S5 packages/mesh-broker present (or run without -SkipHermetic).')
} else {
    $meshG = Start-HermeticMesh -Tag 's6' -LeaseTtlMs 120000 -Spec @(
        [pscustomobject]@{ node = 'solo'; slots = 5; diskGiB = 236; load1 = 0.10; location = 'home' }) -CacheTtlMs 2000
    if (-not $meshG.ok) {
        Add-Step -Id 'S6' -Name 'queue, never amputate (§4.6)' -Status 'FAIL' -Evidence $meshG.error
    } else {
        # Prove the mesh really has 5 slots BEFORE relying on it: §4.6 is meaningless if the
        # condition is wrong, and a stub with an implicit governor.inUse would quietly be 3.
        # Guard every dereference: a null `nodes` here means the READ failed, which is a
        # different fact from "the mesh has the wrong number of slots" and must not be reported
        # as one. (Measured 2026-09-16: the unguarded version of this line reported "the test
        # mesh has -1 slot(s)" and sent the reader after the wrong problem entirely.)
        $nz = Invoke-Json -Url "$($meshG.base)/nodes?fresh=1" -Retries 3 -RetryGapMs 1000 -Seconds 20
        $nodeList = if ($nz.ok -and $nz.doc.nodes) { @($nz.doc.nodes) } else { @() }
        $actualSlots = if ($nodeList.Count -gt 0) { [int]$nodeList[0].slots } else { $null }
        $arithLine = if ($nodeList.Count -gt 0) { [string]$nodeList[0].slotArithmetic } else { '' }
        [void]$step6Detail.Add("  the mesh: $($nodeList.Count) node(s) reported, $(if ($null -eq $actualSlots) { 'unknown' } else { "$actualSlots slot(s)" }) as the broker itself computed them ($arithLine)")
        if ($null -eq $actualSlots) {
            Add-Step -Id 'S6' -Name 'queue, never amputate (§4.6)' -Status 'FAIL' `
                -Evidence "the PRE-CONDITION read failed after $($nz.attempts) attempt(s), so 'a mesh with 5 slots' was never established and nothing else here would mean anything: GET /nodes?fresh=1 on $($meshG.base) -> $($nz.error)" `
                -Detail @($step6Detail)
        } elseif ($actualSlots -ne 5) {
            Add-Step -Id 'S6' -Name 'queue, never amputate (§4.6)' -Status 'FAIL' `
                -Evidence "the test mesh has $actualSlots slot(s), not the 5 §4.6 specifies - the precondition could not be established, so nothing else here would mean anything" `
                -Detail @($step6Detail)
        } else {
            $client = New-HttpClient 40
            $body = '{"task":{"kind":"oneShot","children":1}}'
            $tasks = New-Object System.Collections.ArrayList
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            foreach ($i in 1..30) {
                $content = New-Object System.Net.Http.StringContent($body, [System.Text.Encoding]::UTF8, 'application/json')
                [void]$tasks.Add($client.PostAsync("$($meshG.base)/place", $content))
            }
            $allDone = [System.Threading.Tasks.Task]::WaitAll($tasks.ToArray(), 60000)
            $sw.Stop()
            $codes = @{}; $positions = @(); $nodes = @(); $noAnswer = 0; $badBodies = 0; $badEcho = 0
            foreach ($t in $tasks) {
                try {
                    $resp = $t.Result
                    $code = [int]$resp.StatusCode
                    if ($codes.ContainsKey($code)) { $codes[$code]++ } else { $codes[$code] = 1 }
                    if ($code -eq 200) {
                        $j = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
                        $positions += [int]$j.position
                        $nodes += $j.node
                        if (-not $j.node) { $badBodies++ }
                        if (-not (Test-TaskEcho $j 'oneShot' 1)) { $badEcho++ }
                    }
                } catch {
                    $noAnswer++
                    if ($codes.ContainsKey(0)) { $codes[0]++ } else { $codes[0] = 1 }
                }
            }
            $client.Dispose()
            $non200 = @($codes.Keys | Where-Object { $_ -ne 200 } | ForEach-Object { $codes[$_] } | Measure-Object -Sum).Sum
            if ($null -eq $non200) { $non200 = 0 }
            $named = @($nodes | Where-Object { $_ } | Sort-Object -Unique)
            $queued = @($positions | Where-Object { $_ -gt 0 }).Count
            $hsFinal = Invoke-Json -Url "$($meshG.base)/healthz" -Retries 1 -RetryGapMs 0 -Seconds 8
            $leaseLine = if ($hsFinal.ok) { "broker afterwards: live=$($hsFinal.doc.leases.live) running=$($hsFinal.doc.leases.running) queued=$($hsFinal.doc.leases.queued); capacity reads=$($hsFinal.doc.reads)" } else { '' }
            [void]$step6Detail.Add("  30 concurrent POST /place in $($sw.ElapsedMilliseconds) ms (WaitAll completed=$allDone)")
            [void]$step6Detail.Add("  HTTP codes: " + (($codes.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' ') + "   (0 = no HTTP answer: $noAnswer)")
            [void]$step6Detail.Add("  nodes named: $(($named -join ', ')) ($($named.Count) distinct); answers with no node: $badBodies; answers whose echoed task was not oneShot/1: $badEcho")
            [void]$step6Detail.Add("  positions: min $(($positions | Measure-Object -Minimum).Minimum), max $(($positions | Measure-Object -Maximum).Maximum), >0: $queued of $($positions.Count)")
            [void]$step6Detail.Add("  $leaseLine")
            $ok = ($non200 -eq 0) -and ($named.Count -ge 1) -and ($positions.Count -eq 30) -and ($queued -ge 1) -and ($badBodies -eq 0) -and ($badEcho -eq 0)
            if ($ok) {
                Add-Step -Id 'S6' -Name 'queue, never amputate (§4.6)' -Status 'PASS' `
                    -Evidence "30 of 30 callers got HTTP 200 with a node and a position against a mesh with exactly 5 slots; $queued got position > 0 (up to $(($positions | Measure-Object -Maximum).Maximum)); zero non-200 responses" `
                    -Detail @($step6Detail)
            } else {
                Add-Step -Id 'S6' -Name 'queue, never amputate (§4.6)' -Status 'FAIL' `
                    -Evidence "30 concurrent placements against 5 slots: non-200=$non200, answers with a node=$($named.Count), positions returned=$($positions.Count) of 30, queued=$queued, wrong echo=$badEcho" `
                    -Detail @($step6Detail)
            }
        }
        Stop-HermeticMesh $meshG
    }
}

# ===========================================================================
# summary, report, exit code
# ===========================================================================
$sourceAtEnd = Get-MeshSourceFingerprint
$sourceMoved = ($sourceAtStart.hash -ne $sourceAtEnd.hash)
if ($sourceMoved) {
    Add-Note ("packages/mesh-broker CHANGED while this run was in progress: $($sourceAtStart.hash) -> $($sourceAtEnd.hash). " +
              'The hermetic sub-cases therefore did not all test the same revision, and a mixture of PASS and FAIL among them ' +
              'must be read as "the tree moved", not as "the broker is intermittently broken". Re-run on a still tree to get a ' +
              'verdict about one revision.')
    Write-Host ''
    Write-Host "  WARNING: packages/mesh-broker changed mid-run ($($sourceAtStart.hash) -> $($sourceAtEnd.hash))." -ForegroundColor Yellow
    Write-Host '           Hermetic sub-cases did not all test the same revision; re-run on a still tree for a clean verdict.' -ForegroundColor Yellow
}

$pass = @($script:Steps | Where-Object { $_.status -eq 'PASS' }).Count
$fail = @($script:Steps | Where-Object { $_.status -eq 'FAIL' }).Count
$skip = @($script:Steps | Where-Object { $_.status -eq 'SKIP' }).Count

Write-Head 'SUMMARY'
foreach ($s in $script:Steps) {
    $colour = switch ($s.status) { 'PASS' { 'Green' } 'FAIL' { 'Red' } 'SKIP' { 'Yellow' } default { 'Gray' } }
    Write-Host ("  {0,-5} {1,-32} {2}" -f $s.id, $s.name, $s.status) -ForegroundColor $colour
}
Write-Host ''
Write-Host ("  $pass PASS   $fail FAIL   $skip SKIP   of $($script:Steps.Count) step(s)") -ForegroundColor $(if ($fail -gt 0) { 'Red' } elseif ($skip -gt 0) { 'Yellow' } else { 'Green' })
if ($skip -gt 0 -and $fail -eq 0) {
    Write-Host '  INCOMPLETE: nothing failed, but not everything could be tested. A SKIP is not a pass.' -ForegroundColor Yellow
}

$finishedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$report = [ordered]@{
    harness = 'scripts/mesh-e2e.ps1'; stream = 'S7'; contract = $script:Contract
    runId = $script:RunId; host = $script:Host0; startedAt = $script:StartedAt; finishedAt = $finishedAt
    counts = [ordered]@{ pass = $pass; fail = $fail; skip = $skip }
    steps = @($script:Steps)
    nodes = @($nodeResults)
    liveBroker = $liveBroker
    meshBrokerSource = [ordered]@{ start = $sourceAtStart; end = $sourceAtEnd; changedDuringRun = $sourceMoved }
    step2subcases = @($step2Sub)
    step5bsubcases = @($step5bSub)
    notes = @($script:Notes)
    scratch = $script:Scratch
}
try {
    $report | ConvertTo-Json -Depth 12 | Set-Content -Path $ReportPath -Encoding UTF8
    Write-Host "  report: $ReportPath"
} catch {
    Write-Host "  report could not be written: $($_.Exception.Message)" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# cleanup — only the processes this script started
# ---------------------------------------------------------------------------
$killed = 0
foreach ($p in $script:Procs) {
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; $killed++ }
}
Write-Host "  cleaned up $killed process(es) this script started; every engine and every pre-existing gate was left alone."

if ($Json) { $report | ConvertTo-Json -Depth 12 }

if ($fail -gt 0) { exit 1 }
if ($Strict -and $skip -gt 0) { exit 2 }
exit 0
