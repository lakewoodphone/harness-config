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
    [string]$ReportPath = '',
    # ---- the fleet half, which is a DECISION and never a default -------------------------
    # Steps 3, 4 and 5 need a real dispatched fleet. Firing one spends money and occupies
    # someone else's machine, so it stays behind this switch: the harness must be told by the
    # caller that the owner has authorised it. Added 2026-09-17 for stream O1, whose brief
    # carries that authorisation from the owner ("the entire thing end to end robustly and
    # fully built"), with a hard cap of 8 children per dispatch and no outbound customer
    # contact. See docs/mesh/82-e2e-run.md for the authorisation and the spend.
    [switch]$DispatchFleet,
    [int]$FleetChildren = 6,
    # The forced second node run needs to prove "work runs on a SECOND node", not re-prove
    # sibling-per-node, so it is deliberately smaller than the first: §4.3's bar is "at least two
    # distinct nodes", and stream O1's authorisation caps a dispatch at 8 children. 6 + 2 = 8.
    [int]$ForceChildren = 2,
    # How often the client is sampled while the fleet is in flight (§4.4's ≥16 samples). 5 s over a
    # ~30-60 s fleet gives 6-12; 2 s gives 15-30 and costs one counter + one CIM read + one /healthz
    # per sample, so 2 s is the default.
    [int]$SampleIntervalMs = 2000,
    # The control window that makes §4.4 decidable: commit is sampled for this long, with NOTHING
    # dispatched, immediately before the fleet. 60 s at 2 s intervals is 30 samples and a fair
    # comparison for a ~30-60 s fleet; a shorter window understates the client's own movement.
    [int]$AmbientWindowMs = 60000,
    # The task the parent is given. The parent MUST be told to call `subagent_remote` by name:
    # measured 2026-09-17T03:36Z, a parent told only to "fan the work out" used the built-in
    # `subagent` tool, ran the child on ITS OWN node, and the dispatcher correctly failed the
    # run with `location disagreement: zabz-yoga not on zabz-tech`.
    [string]$FleetPrompt = '',
    # How long one fleet run may take wall-clock. 6 children are serialised by the harness's
    # own "shipped tools are exclusive" rule, so this is minutes, not seconds.
    [int]$FleetTimeoutMs = 1200000,
    # Stream O1's §4.5 kill half. Empty (the default) means "do not kill anything".
    #   'hermetic'  - start a real broker + real stub gates, kill a stub gate THIS HARNESS
    #                 started, and prove the three properties with a live dispatcher.
    #   'live'      - the same, but with the DEPLOYED broker. Named here so the decision is
    #                 explicit; the killed gate is still one this harness started.
    [ValidateSet('', 'hermetic', 'live')]
    [string]$KillNodeHalf = ''
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$script:Contract = 'docs/mesh/71-mesh-program.md §4 (frozen), interfaces §2'
$script:Steps = New-Object System.Collections.ArrayList
$script:RunId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$script:Host0 = $env:COMPUTERNAME
$script:StartedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$script:Procs = New-Object System.Collections.ArrayList      # ONLY processes this script started
$script:Meshes = New-Object System.Collections.ArrayList     # every hermetic mesh, so the finally can stop it
$script:Scratch = ''
$script:Notes = New-Object System.Collections.ArrayList
$script:ClientSamples = New-Object System.Collections.ArrayList
$script:ClientLoopsBeforeFleet = $null

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
# §2.1's naming invariant is `node == fqdn.split(".")[0]`, and the Mac mini's DNS LABEL is lower
# case: its gate answers `"node": "lakewooechsmini"` (and would answer `LakewooechsMini` only by
# accident of DNS being case-insensitive). Measured 2026-09-17T03:46Z: the harness asked for
# `LakewooechsMini` and the gate named itself `lakewooechsmini`, which this file would report as a
# label mismatch - a real fault - except that the LABEL the harness should be asking for is the
# lower-case one. Recorded here rather than silently re-cased in the comparison, so a genuine
# label fault on this node still shows up.
$NodeLabelAlias = @{ 'LakewooechsMini' = 'lakewooechsmini' }

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
        freeMiBAlt = $null; altKind = ''
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
            <#
              CORRECTED 2026-09-17T03:4xZ. This branch used to read `Pages free` alone, on the
              documented belief that the gate's non-Windows branch fell back to
              `SC_AVPHYS_PAGES`. That belief was TRUE until the gate fixed its own darwin reader
              (git 0d07ace, "gate: the macOS memory reader, ..."), and it is false now: the gate
              reads `Pages free + Pages inactive + Pages speculative + Pages purgeable` x
              `sysctl hw.pagesize` (scripts/phone-gate.py _memory_bytes_darwin(), read 03:37Z).
              Keeping the old reader made S1 FAIL on a HEALTHY node by 6,615 MiB - and a
              reader that reports a healthy node as broken is the same confident-wrong-number
              failure this harness exists to catch, just pointed the other way.

              BOTH numbers are therefore taken and reported, because on macOS the two differ by
              gigabytes and the difference is a property of the platform rather than of either
              reader. Measured on the Mac mini 2026-09-17T03:35:19Z, one `vm_stat`, page size
              16384: free 12,245 p = 191.3 MiB; free+inactive+speculative+purgeable
              444,636 p = 6,946.0 MiB. `freeMiB` (the compared one) is the reclaimable sum,
              because that is the counter §2.1's field names on darwin.
            #>
            $mTotal = [regex]::Match($text, '^\s*(\d+)', 'Multiline')
            if ($mTotal.Success) { $result.totalMiB = [int][math]::Round([double]$mTotal.Groups[1].Value / 1048576) }
            $page = [regex]::Match($text, 'page size of (\d+) bytes')
            if ($page.Success) {
                $pageBytes = [double]$page.Groups[1].Value
                $pFree = [regex]::Match($text, 'Pages free:\s+(\d+)')
                $inactive = [regex]::Match($text, 'Pages inactive:\s+(\d+)')
                $speculative = [regex]::Match($text, 'Pages speculative:\s+(\d+)')
                $purgeable = [regex]::Match($text, 'Pages purgeable:\s+(\d+)')
                if ($pFree.Success -and $inactive.Success -and $speculative.Success -and $purgeable.Success) {
                    $freePages = [double]$pFree.Groups[1].Value
                    $reclaimable = $freePages + [double]$inactive.Groups[1].Value + [double]$speculative.Groups[1].Value + [double]$purgeable.Groups[1].Value
                    $result.freeMiB = [int][math]::Round(($reclaimable * $pageBytes) / 1048576)
                    $result.freeMiBAlt = [int][math]::Round(($freePages * $pageBytes) / 1048576)
                    $result.altKind = 'Pages free alone'
                    $result.freeKind = 'reclaimable: Pages free+inactive+speculative+purgeable (the counter phone-gate.py reads on darwin)'
                } else {
                    $result.error = 'vm_stat did not report all of Pages free/inactive/speculative/purgeable'
                }
            } else {
                $result.error = 'vm_stat did not report a page size'
            }
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
    $emptyReads = 0
    $sawUrl = $false
    # CONFIRMED BY A REQUEST, NOT BY A FILE READ. Measured 2026-09-17T03:35Z: the beta stub gate of
    # run 20260917T033436Z was alive and had printed its URL, yet Read-FileText returned '' on all
    # six of its tries (6 x 60 ms) - and `Read-FileText` returns '' IMMEDIATELY after those six, so
    # the `if (-not $text) { continue }` also discarded the 120 ms of the outer loop: the whole
    # search collapsed into ~360 ms, and a stub that took longer than that to flush its stdout was
    # declared dead while it was listening. That is lesson 1 of 78- §4 ("the harness printed a
    # cleanup line" is not evidence of anything) in a new place. So now: a *failed* read costs the
    # full 120 ms and is counted, and once a URL is seen it is PROVEN by asking the gate for its own
    # capacity - which is also what every downstream sub-case needs, so a gate that answers and has
    # an unreadable log no longer fails a step for a reason that has nothing to do with the mesh.
    foreach ($i in 1..200) {
        Start-Sleep -Milliseconds 120
        $text = Read-FileText $out
        if (-not $text) { $emptyReads++; if ($proc.HasExited) { break } else { continue } }
        if ($text -match 'at (http://127\.0\.0\.1:\d+)') {
            $sawUrl = $true
            $candidate = $Matches[1]
            $probe = Get-GateCapacityDirect $candidate
            if ($probe.ok) { $url = $candidate; break }
        }
        if ($proc.HasExited) { break }
    }
    # A stub gate that does not start is a FAIL that must say WHY, like every other FAIL here.
    $diagnostic = $null
    if (-not $url) {
        $stderrText = (Read-FileText $err).Trim()
        $diagnostic = if ($proc.HasExited) {
            "the stub gate for '$Node' exited with code $($proc.ExitCode) before printing a URL"
        } elseif ($sawUrl) {
            "the stub gate for '$Node' printed a URL but never answered its own GET /mesh/capacity (pid $($proc.Id), still running)"
        } else {
            "the stub gate for '$Node' never printed a URL within 24 s (pid $($proc.Id), still running; $emptyReads empty log read(s) - for scale, Read-FileText's own six-try budget is ~360 ms)"
        }
        if ($stderrText) { $diagnostic += "; stderr: $stderrText" }
        $stdoutText = (Read-FileText $out).Trim()
        if ($stdoutText) { $diagnostic += "; stdout: $stdoutText" }
    }
    return [pscustomobject]@{ node = $Node; slots = $Slots; url = $url; proc = $proc; out = $out; err = $err; diagnostic = $diagnostic; emptyReads = $emptyReads }
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
        # Stop what we already started before giving up. An early return that forgets this is how
        # a failed mesh becomes a leaked gate listening on the host we are about to measure.
        foreach ($g in $gates) {
            if ($g.proc -and -not $g.proc.HasExited) { Stop-Process -Id $g.proc.Id -Force -ErrorAction SilentlyContinue }
        }
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
    $mesh = [pscustomobject]@{
        ok = ($up -and $ready); error = $meshError
        base = $base; gates = $gates; proc = $proc; leaseTtlMs = $LeaseTtlMs
        roster = $rosterPath; log = $out; err = $err; tag = $Tag
    }
    # REGISTER IT. The finally stops every registered mesh, so no mesh can be leaked by a
    # control-flow path that forgot to stop it. Measured 2026-09-16: a step-6 gate survived a
    # run whose own explicit Stop-HermeticMesh looked correct, which is exactly the kind of bug
    # that is not worth finding by reading - make it impossible instead.
    [void]$script:Meshes.Add($mesh)
    return $mesh
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
# the fleet half — dispatch, bracket, verify (§4.3/§4.4/§4.5)
# ===========================================================================
function Get-MeshHostTok {
    param([string]$Text)
    <#
      The `MESH-HOST:` tokens in a dispatcher's stdout, with the provider's own echo lines
      EXCLUDED so they cannot stand in for a child's report.

      WHY THIS EXISTS. Counted naively, the parent's output contains, for every successful
      child, three lines whose host token is the same: the child's own `MESH-HOST: x`, the
      wrapper's `[remote-ssh] child ran on node "X"`, and the wrapper's `transport host =
      X (recorded by the target shell before the agent started)`. A naive count therefore
      clears a 6-child bar on 2 children. Measured 2026-09-17: a ONE-child run reported
      `meshHostLines: 3`, and `mesh-run.mjs`'s own `meshHosts.length >= children` gate is
      satisfied by that arithmetic. The acceptance question is "did six children each name a
      node", so this takes the `CHILD=n MESH_HOST=...` / `MESH-HOST-n ...` shape when the
      parent reports per child, and otherwise falls back to counting distinct
      `MESH-HOST:` occurrences that are NOT the wrapper's transport echo.
    #>
    $tokens = New-Object System.Collections.ArrayList
    # (a) the explicit per-child form: `CHILD=3 MESH_HOST=MESH-HOST: zabz-tech`
    foreach ($m in [regex]::Matches($Text, 'CHILD=(\S+)\s+MESH_HOST=MESH-HOST:\s*(\S+)')) {
        [void]$tokens.Add([pscustomobject]@{ child = $m.Groups[1].Value; host = $m.Groups[2].Value; form = 'child-tagged' })
    }
    if ($tokens.Count -gt 0) { return $tokens }
    # (a2) the provider's own short form the parent actually reports: `CHILD=n MESH_HOST=<host>`
    foreach ($m in [regex]::Matches($Text, 'CHILD=(\S+)\s+MESH_HOST=(\S+)')) {
        $hostVal = $m.Groups[2].Value
        if ($hostVal -eq 'MESH-HOST:') { continue }
        # A parent that could not read a child writes a PROSE placeholder, and the first word of
        # that prose is not a hostname. Measured 2026-09-17T04:09Z: run B produced
        # `CHILD=2 MESH_HOST=<value could not be read>` and this counter took `<value` as a node,
        # so the run reported "3 distinct nodes" where the children were on two. A host token has
        # to look like one - the same rule mesh-run.mjs's `isHostToken` applies.
        if ($hostVal -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') { continue }
        [void]$tokens.Add([pscustomobject]@{ child = $m.Groups[1].Value; host = $hostVal; form = 'child-summarised' })
    }
    if ($tokens.Count -gt 0) { return $tokens }
    # (b) the `MESH-HOST-N MESH-HOST: <host>` form this harness's own task asks for.
    foreach ($m in [regex]::Matches($Text, 'MESH-HOST-(\S+)\s+.*?MESH-HOST:\s*(\S+)')) {
        [void]$tokens.Add([pscustomobject]@{ child = $m.Groups[1].Value; host = $m.Groups[2].Value; form = 'numbered' })
    }
    if ($tokens.Count -gt 0) { return $tokens }
    # (c) fall back to bare occurrences, each transport echo dropped.
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match 'transport host\s*=') { continue }
        if ($line -match 'child ran on node') { continue }
        foreach ($m in [regex]::Matches($line, 'MESH-HOST:\s*(\S+)')) {
            [void]$tokens.Add([pscustomobject]@{ child = '?'; host = $m.Groups[1].Value; form = 'bare' })
        }
    }
    return $tokens
}

function Invoke-FleetDispatch {
    <#
      Run ONE real fleet through scripts/mesh-run.ps1 and return everything the acceptance
      needs: the broker's own placement record, the dispatcher's stdout, the parsed per-child
      MESH-HOST tokens, the wall time and the exit code. It never kills anything.
    #>
    param(
        [string]$Prompt,
        [int]$Children,
        [string[]]$Exclude = @(),
        [int]$TimeoutMs = 1200000,
        [string]$Tag = 'fleet',
        [scriptblock]$Sampler = $null,
        [int]$SampleIntervalMs = 5000
    )
    $scriptDir = Split-Path -Parent $PSCommandPath
    $meshRun = Join-Path $scriptDir 'mesh-fleet-run.ps1'
    $promptFile = Join-Path $script:Scratch "fleet-$Tag-prompt.txt"
    Set-Content -Path $promptFile -Value $Prompt -Encoding utf8
    $outFile = Join-Path $script:Scratch "fleet-$Tag.out"
    $errFile = Join-Path $script:Scratch "fleet-$Tag.err"
    # The prompt travels in the ENVIRONMENT: it is multi-line and full of PowerShell metacharacters,
    # and `Start-Process -ArgumentList` re-parses whatever it joins. See scripts/mesh-fleet-run.ps1.
    $env:MESH_FLEET_PROMPT = $Prompt
    $env:MESH_FLEET_CHILDREN = "$Children"
    $env:MESH_FLEET_TIMEOUT_MS = "$TimeoutMs"
    $env:MESH_FLEET_EXCLUDE = ($Exclude -join ',')
    $t0 = Get-Date
    $proc = Start-Process pwsh -ArgumentList @('-NoProfile', '-File', $meshRun) -PassThru -NoNewWindow `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    [void]$script:Procs.Add($proc)
    # Sample the client WHILE the dispatcher runs, not after it. The last sample is on the far
    # side of the wait, so a fleets' whole duration is bracketed and $SampleIntervalMs sets how
    # many samples land inside it.
    $deadline = (Get-Date).AddMilliseconds($TimeoutMs + 60000)
    $last = Get-Date
    while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        if ($Sampler -and ((Get-Date) - $last).TotalMilliseconds -ge $SampleIntervalMs) {
            & $Sampler $Tag
            $last = Get-Date
        }
    }
    $waited = $proc.HasExited
    $ms = [int]((Get-Date) - $t0).TotalMilliseconds
    $exitCode = if ($waited) { $proc.ExitCode } else { $null }
    if (-not $waited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    $stdout = if (Test-Path $outFile) { Get-Content -Path $outFile -Raw } else { '' }
    $stderr = if (Test-Path $errFile) { Get-Content -Path $errFile -Raw } else { '' }
    $tokens = Get-MeshHostTok $stdout
    # The broker's own placement record. THE DISPATCHER'S JSONL IS THE AUTHORITATIVE SOURCE, and
    # finding that out cost one run: `record()` in mesh-run.mjs writes each phase to the run's
    # `.jsonl` AND echoes it with `console.log`, i.e. to STDOUT - not stderr - so an earlier version
    # of this function parsed stderr, found nothing, and reported `node ''` for a run that had
    # placed cleanly and completed. The JSONL is read because it is the file the frozen interface
    # names (`71` §2.3: "one JSONL per run: node, start, end, exit code, host the child reported").
    $placeLine = $null
    $logPath = $null
    $logDir = Join-Path $env:USERPROFILE '.dsh\mesh\logs'
    $since = $t0.AddSeconds(-5)
    $candidates = @()
    if (Test-Path $logDir) {
        # A run's JSONL is created when the run STARTS, so the window is "written at or after a few
    # seconds before we launched", not "in the last few seconds".
    $candidates = @(Get-ChildItem $logDir -Filter '*.jsonl' | Where-Object { $_.LastWriteTime -ge $since } | Sort-Object LastWriteTime -Descending)
    }
    foreach ($cand in $candidates) {
        $lines = @(Get-Content $cand.FullName -ErrorAction SilentlyContinue)
        $pRec = $null; $pRun = $null
        foreach ($line in $lines) {
            if ($line -notmatch '"phase":"(place|run)"') { continue }
            try { $obj = $line | ConvertFrom-Json } catch { continue }
            if ($obj.phase -eq 'place') { $pRec = $obj }
            if ($obj.phase -eq 'run' -and $obj.prompt) { $pRun = $obj }
        }
        # Match THIS dispatch, not a neighbouring one: the run record echoes the first 200 chars of
        # the prompt we sent.
        if ($pRec -and $pRun -and $Prompt.StartsWith([string]$pRun.prompt)) {
            $placeLine = $pRec
            $logPath = $cand.FullName
            break
        }
    }
    return [pscustomobject]@{
        tag = $Tag; children = $Children; exclude = $Exclude; exitCode = $exitCode
        waited = $waited; ms = $ms; stdout = $stdout; stderr = $stderr
        tokens = $tokens; placement = $placeLine; outFile = $outFile; errFile = $errFile
        logFile = $logPath
        node = if ($placeLine) { $placeLine.node } else { $null }
        lease = if ($placeLine) { $placeLine.lease } else { $null }
    }
}

function Get-ClientCommit {
    <#
      The client's committed bytes.

      THE SAMPLER MUST NOT MOVE THE NUMBER IT MEASURES. The first version of this called
      `Get-Counter '\Memory\Committed Bytes'` as well as the CIM read. Get-Counter is not a
      lightweight call: it starts a PowerShell performance-counter worker, and each sample then
      adds a process worth tens of MB to the very commit charge the sample is reporting. Measured
      the same night by a 36-sample baseline (ZABZ-YOGA, 03:37:35-03:40:31Z): with two samplers
      running, commit moved 2.542 GiB across 176 s while NO fleet was running at all - larger than
      the ±1 GiB bar this step is judged by. Some of that was the samplers themselves.

      So the sampler reads ONE source, cheaply and in-process: the derived commit charge
      `TotalVirtualMemorySize - FreeVirtualMemory`, which is the formula 20-placement.md's
      correction row 3 insists on, and which 70-remote-fanout-proof.md §2.4 also used for the
      before/after delta (its absolute value carried a 0.7 % uncertainty cross-checked against the
      perf counter on ZABZ-TECH; the delta does not, because both readings use one formula seconds
      apart). Where the counter IS wanted, `SampleWithCounter` below is used for the single
      before/after pair, not for every sample inside the window.
    #>
    param([switch]$WithCounter)
    $counter = $null; $derived = $null; $avail = $null
    if ($WithCounter) {
        try { $counter = [double](Get-Counter '\Memory\Committed Bytes' -ErrorAction Stop).CounterSamples[0].CookedValue } catch { }
    }
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        $derived = [double]$os.TotalVirtualMemorySize * 1KB - [double]$os.FreeVirtualMemory * 1KB
        $avail = [double]$os.FreePhysicalMemory * 1KB
    } catch { }
    return [pscustomobject]@{ counter = $counter; derived = $derived; avail = $avail; at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ') }
}

function Get-ClientLoops {
    <#
      `sessions.agentLoopsRunning` from this laptop's own engine, read through the gate.

      KEPT FOR CONTEXT ONLY - IT IS NOT THE §4.4 CRITERION ANY MORE, and this is the measured reason.
      A headless child is a SEPARATE PROCESS and never registers as a loop in the resident engine.
      Measured 2026-09-17T03:58:42Z on this laptop: a real `node <dsh>/bin.js --profile headless
      "<task>"` child ran HERE and `agentLoopsRunning` read **10 before, 10 during and 10 after**;
      twenty seconds later, with nothing dispatched at all, it read **11**. A field that does not
      move when a child runs on this machine, and does move when none does, cannot decide §4.4.
      (Independently measured the same night by the calibration stream on the TARGET node: 83
      samples with 8 real headless children running, `agentLoopsRunning: 0` and `governor.inUse: 0`
      in every one.) See `Get-LocalChildProcesses` for what replaced it.
    #>
    try {
        $hc = New-HttpClient 25
        $null = $hc.GetAsync("http://127.0.0.1:3086/").GetAwaiter().GetResult()
        $hr = $hc.GetAsync("http://127.0.0.1:3086/healthz").GetAwaiter().GetResult()
        $loops = $null
        if ([int]$hr.StatusCode -eq 200) {
            $hj = $hr.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
            $loops = $hj.sessions.agentLoopsRunning
        }
        $hc.Dispose()
        return $loops
    } catch { return $null }
}

function Get-LocalChildProcesses {
    <#
      Every DSH child-worker process running on THIS machine, found by command line.

      WHY THIS IS THE §4.4 CRITERION, and what the field it replaced could not do.
      A headless child is a SEPARATE PROCESS and never registers as a loop in the resident engine.
      Measured 2026-09-17T03:58:42Z on this laptop: a real `node <dsh>/bin.js --profile headless
      "<task>"` child ran HERE and `sessions.agentLoopsRunning` read **10 before, 10 during and 10
      after**; twenty seconds later, with nothing dispatched at all, it read **11**. (Independently
      measured the same night by the calibration stream, on the TARGET node: 83 samples with 8 real
      headless children running, `agentLoopsRunning: 0` and `governor.inUse: 0` in every one.) So
      §4.4's "no new agent loops" was a criterion that could not fail, which is worse than a weak
      one - and it is replaced here by counting the processes, which does move.

      WHAT COUNTS. Two families, discovered by enumerating every node.exe on this host and reading
      its command line (measured 2026-09-17T04:00Z on ZABZ-YOGA, 16 node processes):
        `C:\...\node_modules\@deepseek-ai\dsh-subprocess-local\lib\run`   <- a local subagent WORKER.
             Measured: one local `--profile headless` child spawns NINE of these. Counting them is
             what makes this instrument able to fail: it went 0 -> 9 -> 0 around a single deliberate
             local child, while `agentLoopsRunning` stayed flat.
        `<dsh>/lib/bin.js --profile <anything>`                          <- a dsh runner, e.g. a
             dispatched `--profile mesh` parent. This laptop's resident engine is
             `bin.js web --port 3099` and is EXCLUDED (profile `web`), so the baseline is 0.

      It cannot see a child that ran on ANOTHER node - that is what §3's MESH-HOST evidence is for.
      This function answers exactly one question, the one §4.4 asks: did the fleet run HERE.
    #>
    $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue)
    $runners = New-Object System.Collections.ArrayList
    $engine = 0
    $workers = 0
    foreach ($p in $procs) {
        $cl = [string]$p.CommandLine
        # The engine's own subagent WORKER POOL. Counted for context, never used as the criterion:
        # measured 2026-09-17T04:05Z, ELEVEN of these sat on this laptop with no dispatch at all,
        # churning with other sessions' resident work, and they moved 8 -> 12 during my own run
        # while the six children were demonstrably on zabz-tech. A pooled worker is not evidence
        # that THIS fleet ran here, and using it as the criterion produced a false FAIL.
        if ($cl -match 'dsh-subprocess-local[\\/]lib[\\/]run') { $workers++; continue }
        if ($cl -notmatch 'deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js') { continue }
        # THE RESIDENT ENGINE IS EXCLUDED BY ITS SUBCOMMAND, NOT BY `--profile`. Measured
        # 2026-09-17T04:10Z, and it cost a false FAIL to learn: this laptop's engine runs as
        # `node <dsh>/lib/bin.js web --port 3099 --no-open` - the subcommand is `web`, with NO
        # `--profile` at all. Reading only `--profile` therefore classified the engine as a
        # dispatched runner and S4 reported "the client ran the fleet itself" for pid 1784. Match
        # `bin.js` followed by `web`, and treat any profile value of `web` as the engine too.
        if ($cl -match 'bin\.js"?\s+web\b') { $engine++; continue }
        $profile = if ($cl -match '--profile\s+(\S+)') { $Matches[1] } else { '(none)' }
        if ($profile -eq 'web') { $engine++; continue }
        # A RUNNER: a dsh process that is not the resident engine. `--profile headless` or
        # `--profile mesh` is exactly what mesh-run starts - inside the target when the dispatch
        # works, and HERE when it does not. Measured at rest on this laptop: 0.
        [void]$runners.Add([pscustomobject]@{ pid = $p.ProcessId; profile = $profile; commandLine = $cl })
    }
    return [pscustomobject]@{
        nodeProcesses = $procs.Count
        engineProcesses = $engine
        workerProcesses = $workers
        childProcesses = $runners.Count
        childPids = @($runners | ForEach-Object { $_.pid })
        childProfiles = @($runners | ForEach-Object { $_.profile })
        at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    }
}

function Get-ClientSessionSnapshot {
    <#
      Which of this laptop's own engine sessions exist and which are RUNNING, as a set of ids.

      WHY THIS EXISTS. This laptop is not a quiet client. The owner runs his own work on it - and
      was, by the manager's account, running a second multi-subagent fleet on it through the same
      night this harness measured (§4.6). So when the client's memory moves while my children run,
      "my children did it" is an ATTRIBUTION, not a measurement, unless the other load is named.
      This takes the id set before and after, and the report quotes the sessions that appeared or
      changed state inside the window: that is what turns "commit moved 0.35 GiB" into either
      "commit moved 0.35 GiB while 4 other sessions were running (ids listed)" or "while nothing
      else was running". A number whose attribution cannot be stated is not evidence.
    #>
    try {
        $hc = New-HttpClient 25
        $null = $hc.GetAsync("http://127.0.0.1:3086/").GetAwaiter().GetResult()
        $hr = $hc.GetAsync("http://127.0.0.1:3086/healthz").GetAwaiter().GetResult()
        if ([int]$hr.StatusCode -ne 200) { $hc.Dispose(); return $null }
        $hj = $hr.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        $hc.Dispose()
        $list = @($hj.sessions.list)
        return [pscustomobject]@{
            at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
            live = $hj.sessions.live
            subagents = $hj.sessions.subagents
            agentLoopsRunning = $hj.sessions.agentLoopsRunning
            runningIds = @($list | Where-Object { $_.status -eq 'running' } | ForEach-Object { $_.id })
            allIds = @($list | ForEach-Object { $_.id })
        }
    } catch { return $null }
}

function Get-BrokerLeases {
    <#
      The broker's own lease state, which is the ONLY place a dispatched fleet is visible while it
      runs. Measured the same night: a node's real load is invisible to every input the broker
      consumes except its own leases - `agentLoopsRunning` is blind to headless children, and the
      broker's memory term never binds either (memorySlots hits its 24 cap at 7,725 MiB free, which
      every node in this fleet clears), so placement is decided by the core term plus these leases.
    #>
    param([string]$BrokerBase)
    if (-not $BrokerBase) { return $null }
    $h = Invoke-Json -Url "$BrokerBase/healthz" -Retries 1 -RetryGapMs 0 -Seconds 10
    if (-not $h.ok) { return $null }
    return $h.doc.leases
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

# Everything from here to the summary runs inside a try, so the cleanup in the finally is
# guaranteed. See the note on that finally for why it is not merely tidy.
try {

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
    if ($r.direct -and $null -ne $r.direct.freeMiBAlt) { $extra += " | on this platform 'free' has two meanings and this reader took both: $($r.direct.freeMiB) MiB reclaimable (the counter the gate reads) vs $($r.direct.freeMiBAlt) MiB as $($r.direct.altKind)" }
    $expectedLabel = if ($NodeLabelAlias.ContainsKey($r.node)) { $NodeLabelAlias[$r.node] } else { $r.node }
    if ($r.reportedNode -and $r.reportedNode -ne $expectedLabel) { $extra += " | the gate names itself '$($r.reportedNode)' where this harness asked for '$expectedLabel'" }
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
    # A BROKER WITH NO READINGS IS NOT A BROKER WITH NO NODES. Measured 2026-09-17T03:42:5xZ: the
    # deployed broker was restarted twice inside two minutes by stream O5 (systemd, `Scheduled
    # restart job, restart counter is at 1`, 03:42:43 and 03:42:45), and the harness's live
    # sub-case read it during that window: all four nodes came back `unreachable (timed out after
    # 4000 ms)` and the sub-case FAILed, even though a forced re-read 90 seconds later returned
    # four `ok` nodes in 0.2 s and a controlled restart read all four in 0.5 s. So a read in which
    # EVERY node is unreachable is retried once, and the retry is recorded - because otherwise this
    # harness reports another stream's restart as a placement defect.
    $allUnreachable = ($liveNodes.ok) -and (@($liveNodes.doc.nodes | Where-Object { $_.state -eq 'ok' }).Count -eq 0)
    if ($allUnreachable) {
        [void]$step2Detail.Add('  the first live read returned every node unreachable - retrying once after 5 s (a broker that was just restarted has no readings yet, and that is not a placement defect)')
        Start-Sleep -Seconds 5
        $liveNodes = Invoke-Json -Url "$liveBroker/nodes?fresh=1" -Retries 1 -RetryGapMs 0 -Seconds 40
        [void]$step2Detail.Add("  retry: HTTP $($liveNodes.code), $((@($liveNodes.doc.nodes | Where-Object { $_.state -eq 'ok' }).Count)) node(s) now ok")
    }
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
        # §4.2 asks for the arithmetic that CHOSE the node, and the arithmetic must be readable -
        # not for one particular literal number. CORRECTED 2026-09-17T03:47Z: this used to demand
        # the string "$MESH_GOVERNOR_RESERVE_MIB" (3885), and it FAILed a placement whose rationale
        # was complete, because the broker now derives the reserve PER NODE -
        # `reserve 7821 MiB = max(2048 MiB, 12% of the node's own 65173 MiB)` - which is what
        # `71` §2.1 requires ("reserve = max(2 GiB, 12% of physical)") and which a flat 3885 MiB
        # cannot satisfy on a 64 GB machine. The harness was reading its own stale assumption as a
        # broker defect; the broker was right. So the check is on the STRUCTURE of the arithmetic:
        # a memory->slots computation with the per-slot constant, the core term, and a position
        # line naming how many children it accepted.
        $hasMemoryArith = ($joined -match "floor\(\(.*MiB free\s*-\s*\d+ MiB reserve\)\s*/\s*$MESH_PER_SLOT_MIB MiB\)") -and ($joined -match 'slot')
        $hasCoreTerm = ($joined -match 'core slot')
        $hasPosition = ($joined -match 'position \d+:')
        $hasArith = $hasMemoryArith
        $why = "node=$($p.node) position=$($p.position) score=$($p.score) eligible=$($p.eligible) tier=$($p.tier); rationale has $(@($p.rationale).Count) line(s)"
        if (-not (Test-TaskEcho $p 'fleet' 6)) {
            Add-Sub $step2Sub 'live broker names a node' 'FAIL' "$why -- the broker reports kind='$($p.kind)' children=$($p.children): the 6-child fleet this test sent did not ARRIVE as one, so nothing else here would be about §4.2"
        } elseif ($hasName -and $hasArith -and $hasPosition -and @($p.rationale).Count -gt 0) {
            Add-Sub $step2Sub 'live broker names a node' 'PASS' ($why + "; the broker confirms it read a fleet of $($p.children) child(ren)" + $(if (-not $hasCoreTerm) { ' [note: no core term in this broker build]' } else { '' }))
            [void]$step2Detail.Add("    arithmetic line: " + (@($p.rationale) | Where-Object { $_ -match "floor\(\(" } | Select-Object -First 1))
        } else {
            Add-Sub $step2Sub 'live broker names a node' 'FAIL' "$why -- the rationale does not show the arithmetic that chose the node (memory->slots with the $MESH_PER_SLOT_MIB MiB constant: $hasMemoryArith; core term: $hasCoreTerm; a 'position N:' line: $hasPosition)"
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

# The task the parent is given, when the caller did not supply one. It MUST name
# `subagent_remote`: measured 2026-09-17T03:35Z, a parent told only to "fan the work out"
# chose the built-in `subagent` tool, ran the child on its own node, and the run failed with
# `location disagreement: zabz-yoga not on zabz-tech`. The prompt is not a formality - it is
# the thing that decides whether the work is remote at all.
function Get-DefaultFleetPrompt([int]$Children) {
    $lines = New-Object System.Collections.ArrayList
    [void]$lines.Add("Call the subagent_remote tool exactly $Children times, one call per child, and do not call any other subagent tool (never the plain ``subagent`` tool) and no other tool at all.")
    [void]$lines.Add('')
    [void]$lines.Add('Every one of the calls takes the same two arguments, differing only in the token N (1 to ' + $Children + '):')
    [void]$lines.Add('')
    [void]$lines.Add('- description: "mesh child N"')
    [void]$lines.Add('- prompt: Write MESH-HOST-N, then a space, then the output of: echo "MESH-HOST: $(hostname)" Then write CHILD-TOKEN-N on the next line. Nothing else.')
    [void]$lines.Add('')
    [void]$lines.Add('When all ' + $Children + ' results are back, reply with ONLY ' + $Children + ' lines, one per child, exactly in this form:')
    [void]$lines.Add('')
    [void]$lines.Add('CHILD=1 MESH_HOST=<the MESH-HOST value that child 1 printed> TOKEN=<the CHILD-TOKEN value that child 1 printed>')
    [void]$lines.Add('')
    [void]$lines.Add('and the same for 2 through ' + $Children + '. Then one final line: PARENT-FLEET-DONE')
    [void]$lines.Add('')
    [void]$lines.Add('Nothing else. No commentary, no markdown fences, no explanation, no summary.')
    return ($lines -join "`n")
}

$step3Detail = New-Object System.Collections.ArrayList
$fleetA = $null
$fleetB = $null
$fleetBranches = @()
if (-not $meshRunExists) {
    $step3Evidence = 'scripts\mesh-run.ps1 does not exist, so no fleet can be dispatched and no MESH-HOST: line can be produced'
    [void]$step3Detail.Add('  FOR THIS TO RUN: stream S6 must ship scripts/mesh-run.ps1 (and packages/plugin-mesh for the v2 route)')
    [void]$step3Detail.Add('  (packages/plugin-mesh present: ' + $pluginMeshExists + ')')
    Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'SKIP' -Evidence $step3Evidence -Detail @($step3Detail)
} elseif (-not $DispatchFleet) {
    # The dispatcher exists. Firing it spends money and occupies someone else's machine, so it
    # happens ONLY when the caller says so.
    $step3Evidence = "scripts\mesh-run.ps1 is present but -DispatchFleet was not given, so no fleet was dispatched - §4.3 needs a real run whose MESH-HOST: lines are checked against the broker's choice"
    [void]$step3Detail.Add('  mesh-run.ps1 present: ' + $meshRunPath)
    [void]$step3Detail.Add('  the implementation is packages/plugin-remote-fanout/bin/mesh-run.mjs; scripts/mesh-run.ps1 is a 16-line shim that forwards to it')
    [void]$step3Detail.Add('  TO COMPLETE: re-run with -DispatchFleet -SizeOfFleet N (default 6). THIS SPENDS MONEY.')
    [void]$step3Detail.Add('  THIS HARNESS DOES NOT FIRE A FLEET BY ITSELF: that is a decision the caller makes, not a default this file takes.')
    Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'SKIP' -Evidence $step3Evidence -Detail @($step3Detail)
} else {
    # ---- the real fleet, dispatched for real -------------------------------------------
    $fleetPrompt = if ($FleetPrompt -ne '') { $FleetPrompt } else { Get-DefaultFleetPrompt $FleetChildren }
    $script:ClientLoopsBeforeFleet = Get-ClientLoops
    $script:LocalChildrenBeforeFleet = Get-LocalChildProcesses
    $script:SessionsBeforeFleet = Get-ClientSessionSnapshot
    $script:LeasesBeforeFleet = Get-BrokerLeases -BrokerBase $liveBroker
    $script:ClientSamples = New-Object System.Collections.ArrayList
    [void]$step3Detail.Add("  client agentLoopsRunning immediately before the fleet: $($script:ClientLoopsBeforeFleet)  (context only - see §4.4's criterion below)")
    [void]$step3Detail.Add("  client DSH child PROCESSES immediately before the fleet: $($script:LocalChildrenBeforeFleet.childProcesses) (pids: $($script:LocalChildrenBeforeFleet.childPids -join ', ')) out of $($script:LocalChildrenBeforeFleet.nodeProcesses) node process(es) and $($script:LocalChildrenBeforeFleet.engineProcesses) engine process(es)")
    if ($script:LeasesBeforeFleet) { [void]$step3Detail.Add("  broker leases before the fleet: live=$($script:LeasesBeforeFleet.live) running=$($script:LeasesBeforeFleet.running) byNode=$($script:LeasesBeforeFleet.byNode | ConvertTo-Json -Compress)") }
    [void]$step3Detail.Add("  dispatching: pwsh -File scripts\mesh-run.ps1 -Prompt <$($fleetPrompt.Length) chars> -Children $FleetChildren")
    # ONE SAMPLER, WHOSE WHOLE JOB IS TO READ THE CLIENT WHILE THE DISPATCHER RUNS. It is passed
    # into the dispatch so the sampling happens inside the dispatcher's wall-clock window rather
    # than being reconstructed afterwards. It takes BOTH quantities that can answer §4.4: committed
    # bytes, and the count of DSH child processes on this machine (the criterion that can fail).
    $sampler = {
        param([string]$stage)
        $c = Get-ClientCommit
        $lc = Get-LocalChildProcesses
        $n = @($script:ClientSamples).Count + 1
        [void]$script:ClientSamples.Add([pscustomobject]@{
            n = $n; stage = $stage; counter = $c.counter; derived = $c.derived; avail = $c.avail; at = $c.at
            childProcesses = $lc.childProcesses; childPids = ($lc.childPids -join ','); nodeProcesses = $lc.nodeProcesses; engineProcesses = $lc.engineProcesses
        })
    }
    # AN AMBIENT CONTROL WINDOW, MEASURED IMMEDIATELY BEFORE THE FLEET, FOR THE SAME LENGTH OF
    # TIME. §4.4's bar is a ±1 GiB change; if the client's commit charge moves more than that while
    # NOTHING is dispatched, then the bar is below this machine's own noise floor and a fleet
    # measurement cannot distinguish the fleet from the weather. Measured 2026-09-17T03:37:35-
    # 03:40:31Z by an independent sampler on this laptop: commit moved 2.542 GiB in 176 s with no
    # fleet running at all. So the control is part of the measurement, not a caveat in the prose.
    # AN AMBIENT CONTROL WINDOW OF THE SAME LENGTH AS A FLEET, MEASURED IMMEDIATELY BEFORE IT. The
    # caller sets how long with -AmbientWindowMs (default 60 s at a 2 s interval = 30 samples).
    $ambientMs = $AmbientWindowMs
    $ambientInterval = [Math]::Max(1000, $SampleIntervalMs)
    $ambient = New-Object System.Collections.ArrayList
    $ambientStart = Get-ClientCommit
    [void]$ambient.Add([pscustomobject]@{ n = 0; stage = 'ambient'; counter = $null; derived = $ambientStart.derived; avail = $ambientStart.avail; at = $ambientStart.at })
    $ambEnd = (Get-Date).AddMilliseconds($ambientMs)
    $ai = 0
    while ((Get-Date) -lt $ambEnd) {
        Start-Sleep -Milliseconds $ambientInterval
        $ai++
        $c = Get-ClientCommit
        [void]$ambient.Add([pscustomobject]@{ n = $ai; stage = 'ambient'; counter = $null; derived = $c.derived; avail = $c.avail; at = $c.at })
    }
    $ambMin = ($ambient | Measure-Object -Property derived -Minimum).Minimum
    $ambMax = ($ambient | Measure-Object -Property derived -Maximum).Maximum
    $ambientSpreadGiB = [math]::Round(($ambMax - $ambMin) / 1GB, 3)
    $ambientDeltaGiB = [math]::Round(($ambient[-1].derived - $ambientStart.derived) / 1GB, 3)
    [void]$step3Detail.Add("  ambient control: $($ambient.Count) sample(s) over $ambientMs ms BEFORE any dispatch - commit spread $ambientSpreadGiB GiB, end-to-end delta $ambientDeltaGiB GiB, with nothing dispatched")
    $script:AmbientSpreadGiB = $ambientSpreadGiB
    $script:AmbientDeltaGiB = $ambientDeltaGiB
    $script:AmbientSamples = @($ambient)
    $fleetA = Invoke-FleetDispatch -Prompt $fleetPrompt -Children $FleetChildren -TimeoutMs $FleetTimeoutMs -Tag 'A' -Sampler $sampler -SampleIntervalMs $SampleIntervalMs
    [void]$step3Detail.Add("  samples taken on this laptop while run A was in flight: $(@($script:ClientSamples).Count) (every $SampleIntervalMs ms)")
    [void]$step3Detail.Add("  run A: exit $($fleetA.exitCode) after $($fleetA.ms) ms; broker named node '$($fleetA.node)' lease '$($fleetA.lease)'")
    [void]$step3Detail.Add("  run A MESH-HOST tokens: $(@($fleetA.tokens).Count) ($((@($fleetA.tokens) | ForEach-Object { $_.host }) -join ', '))")
    $hostsA = @(@($fleetA.tokens) | ForEach-Object { $_.host } | Sort-Object -Unique)
    $distinctA = @($hostsA | Where-Object { $_ -ne '(not' }).Count
    # A 6-child fleet is ONE placement, so it lands on ONE node - that is §2.2's contract, not a
    # defect. §4.3's "at least two distinct nodes when two are free" is therefore tested by a
    # SECOND fleet with the first node EXCLUDED through the broker's own `task.exclude`, which is
    # printed in its rationale. Measured 2026-09-17: with 2 nodes eligible the broker named
    # 'zabz-tech' for run A, so run B excluded it.
    if ($fleetA.node -and $fleetA.exitCode -eq 0) {
        [void]$step3Detail.Add("  forcing a SECOND node: excluding '$($fleetA.node)' via the broker's own task.exclude, then dispatching again with $ForceChildren child(ren)")
        $fleetB = Invoke-FleetDispatch -Prompt (Get-DefaultFleetPrompt $ForceChildren) -Children $ForceChildren -Exclude @($fleetA.node) -TimeoutMs $FleetTimeoutMs -Tag 'B'
        [void]$step3Detail.Add("  run B: exit $($fleetB.exitCode) after $($fleetB.ms) ms; broker named node '$($fleetB.node)' lease '$($fleetB.lease)'")
        [void]$step3Detail.Add("  run B MESH-HOST tokens: $(@($fleetB.tokens).Count) ($((@($fleetB.tokens) | ForEach-Object { $_.host }) -join ', '))")
    } else {
        [void]$step3Detail.Add('  run B not attempted: run A did not complete, so excluding its node would test nothing about a fleet that works')
    }
    $allTokens = @(@($fleetA.tokens) + @($fleetB.tokens))
    $hostsAll = @($allTokens | ForEach-Object { $_.host } | Sort-Object -Unique)
    [void]$step3Detail.Add("  distinct nodes named across both runs: $($hostsAll -join ', ')")
    $okA = ($fleetA.exitCode -eq 0) -and (@($fleetA.tokens).Count -ge $FleetChildren)
    $okB = ($null -eq $fleetB) -or (($fleetB.exitCode -eq 0) -and (@($fleetB.tokens).Count -ge $ForceChildren))
    $okTwo = ($hostsAll.Count -ge 2)
    if ($okA -and $okB -and $okTwo) {
        Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'PASS' `
            -Evidence "a real $FleetChildren-child fleet ran and every child's own MESH-HOST line matched the node the broker named ($($fleetA.node)); a second run of $ForceChildren child(ren) with that node excluded through the broker's task.exclude landed on $($fleetB.node) - $($hostsAll.Count) distinct nodes, both verified from the children's reports" `
            -Detail @($step3Detail)
    } elseif ($okA -and -not $okB) {
        Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'FAIL' `
            -Evidence "run A completed on '$($fleetA.node)' but the forced second run failed: exit $($fleetB.exitCode), $((@($fleetB.tokens)).Count) of $ForceChildren MESH-HOST lines" `
            -Detail @($step3Detail)
    } elseif ($okA -and $okB -and -not $okTwo) {
        Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'FAIL' `
            -Evidence "both runs succeeded but named only $($hostsAll.Count) distinct node(s) ($($hostsAll -join ', ')) - §4.3 wants two when two are free" `
            -Detail @($step3Detail)
    } else {
        Add-Step -Id 'S3' -Name 'work lands there (§4.3)' -Status 'FAIL' `
            -Evidence "the dispatched fleet did not complete: exit $($fleetA.exitCode) after $($fleetA.ms) ms, $((@($fleetA.tokens)).Count) of $FleetChildren MESH-HOST lines for node '$($fleetA.node)'" `
            -Detail @($step3Detail)
    }
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

$step4Detail = New-Object System.Collections.ArrayList
if ($fleetA -eq $null) {
    $commitAfter = $null
    try { $commitAfter = [double](Get-Counter '\Memory\Committed Bytes' -ErrorAction Stop).CounterSamples[0].CookedValue } catch { }
    $loopsAfter = Get-ClientLoops
    if ($null -ne $commitBefore -and $null -ne $commitAfter) {
        [void]$step4Detail.Add("  commit before $([math]::Round($commitBefore/1GB,2)) GiB -> after $([math]::Round($commitAfter/1GB,2)) GiB (delta $([math]::Round(($commitAfter-$commitBefore)/1GB,3)) GiB, tolerance ±1 GiB)")
    }
    [void]$step4Detail.Add("  agentLoopsRunning before $loopsBefore -> after $loopsAfter  (source: GET /healthz on this laptop, via the gate at 127.0.0.1:3086)")
    [void]$step4Detail.Add('  THESE ARE MEASUREMENTS OF THIS HARNESS, NOT OF A FLEET: no fleet was dispatched under -DispatchFleet, so nothing ran on another node and there is nothing for the laptop to have absorbed.')
    if (-not $meshRunExists) {
        Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'SKIP' `
            -Evidence 'no fleet can be dispatched without scripts\mesh-run.ps1, so "commit flat while the children run" has no children to be flat during' `
            -Detail @($step4Detail + @('  FOR THIS TO RUN: stream S6 scripts/mesh-run.ps1, then re-run this harness.'))
    } else {
        Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'SKIP' `
            -Evidence 'mesh-run.ps1 is present, but -DispatchFleet was not given, so no fleet was dispatched and there is no run to bracket' `
            -Detail @($step4Detail)
    }
} else {
    # The fleet ran (step 3). The bracket was taken AROUND it: `commitBefore`/`loopsBefore` are
    # read before step 3 starts and `ClientSamples` is filled by the step-3 sampling loop, so the
    # "after" reading below is genuinely after the children finished.
    $samples = @($script:ClientSamples)
    $commitAfter = Get-ClientCommit
    $loopsAfter = Get-ClientLoops
    $derivedBefore = if ($samples.Count -gt 0) { $samples[0].derived } else { $null }
    $finalDerived = $commitAfter.derived
    $maxCounter = ($samples | Measure-Object -Property counter -Maximum).Maximum
    $minCounter = ($samples | Measure-Object -Property counter -Minimum).Minimum
    $maxDerived = ($samples | Measure-Object -Property derived -Maximum).Maximum
    $commitDeltaGiB = if ($null -ne $derivedBefore -and $null -ne $finalDerived) {
        [math]::Round(($finalDerived - $derivedBefore) / 1GB, 3)
    } else { $null }
    $peakDeltaGiB = if ($null -ne $derivedBefore -and $null -ne $maxDerived) {
        [math]::Round(($maxDerived - $derivedBefore) / 1GB, 3)
    } else { $null }
    [void]$step4Detail.Add("  $($samples.Count) sample(s) were taken on this laptop while the fleet ran, every $($SampleIntervalMs) ms, from the moment before step 3 dispatched it")
    [void]$step4Detail.Add("  commit charge (derived = TotalVirtualMemorySize - FreeVirtualMemory), the formula 20-placement.md row 3 insists on:")
    [void]$step4Detail.Add("    before $([math]::Round($derivedBefore/1GB,3)) GiB -> after $([math]::Round($finalDerived/1GB,3)) GiB : delta $commitDeltaGiB GiB")
    [void]$step4Detail.Add("    peak during the run $([math]::Round($maxDerived/1GB,3)) GiB : delta from before $peakDeltaGiB GiB")
    [void]$step4Detail.Add("  the same quantity from a DIFFERENT source (perf counter \Memory\Committed Bytes): min $([math]::Round($minCounter/1GB,3)) GiB, max $([math]::Round($maxCounter/1GB,3)) GiB")
    [void]$step4Detail.Add("  agentLoopsRunning on this laptop: $($script:ClientLoopsBeforeFleet) immediately before the fleet, $loopsAfter after it")
    [void]$step4Detail.Add("  ...and that field is CONTEXT ONLY: measured 2026-09-17T03:58:42Z, a real local headless child moved it NOT AT ALL (10/10/10), while it read 11 later with nothing dispatched. It cannot decide §4.4.")
    [void]$step4Detail.Add("  the children themselves reported '$($fleetA.node)' (run A, $($fleetA.ms) ms) and '$($fleetB.node)' (run B) - the 6-child fleet was ONE placement, and run B excluded it through the broker's own task.exclude")
    $maxChildren = ($samples | Measure-Object -Property childProcesses -Maximum).Maximum
    $childrenBefore = $script:LocalChildrenBeforeFleet.childProcesses
    $localChildrenSeen = @($samples | Where-Object { $_.childProcesses -gt $childrenBefore })
    [void]$step4Detail.Add("  §4.4's CRITERION - did any of the fleet run HERE: client dsh RUNNER processes (a `bin.js --profile <not web>`, i.e. exactly what mesh-run starts) before $childrenBefore, peak during the fleet $maxChildren over $($samples.Count) samples")
    if ($localChildrenSeen.Count -gt 0) {
        [void]$step4Detail.Add("    the client ran child work itself at $($localChildrenSeen.Count) sample(s); first at $($localChildrenSeen[0].at) with pids $($localChildrenSeen[0].childPids)")
    } else {
        [void]$step4Detail.Add("    the client never ran child work: every one of the $($samples.Count) samples saw at most $childrenBefore, and the children's own MESH-HOST lines place them on another node")
    }
    $brokerLeasesAfter = Get-BrokerLeases -BrokerBase $liveBroker
    $sessionsAfter = Get-ClientSessionSnapshot
    if ($script:SessionsBeforeFleet -and $sessionsAfter) {
        $newIds = @($sessionsAfter.allIds | Where-Object { $script:SessionsBeforeFleet.allIds -notcontains $_ })
        $newRunning = @($sessionsAfter.runningIds | Where-Object { $script:SessionsBeforeFleet.runningIds -notcontains $_ })
        [void]$step4Detail.Add("  ATTRIBUTION - other load on this client, which the owner was running deliberately: sessions live $($script:SessionsBeforeFleet.live) -> $($sessionsAfter.live); running $($script:SessionsBeforeFleet.runningIds.Count) -> $($sessionsAfter.runningIds.Count); sessions that APPEARED inside the window: $($newIds.Count) ($($newIds -join ', ')); sessions that STARTED running inside the window: $($newRunning.Count)")
        if ($newIds.Count -eq 0 -and $newRunning.Count -eq 0) {
            [void]$step4Detail.Add("    no other session appeared or started running during the fleet window, so the commit movement inside it is attributable to this run and to ambient churn, not to a second fleet")
        } else {
            [void]$step4Detail.Add("    OTHER WORK WAS RUNNING ON THIS CLIENT DURING THE WINDOW, so the commit movement CANNOT be attributed to this fleet alone. This is a contaminated bracket, reported as such: the owner's own agents share this machine.")
        }
    }
    if ($script:LeasesBeforeFleet -and $brokerLeasesAfter) {
        [void]$step4Detail.Add("  broker leases: before live=$($script:LeasesBeforeFleet.live) -> after live=$($brokerLeasesAfter.live); running before $($script:LeasesBeforeFleet.running) -> after $($brokerLeasesAfter.running)  (the broker's leases are the ONLY place a dispatched fleet is visible while it runs)")
    }
    $flatOk = ($null -ne $commitDeltaGiB) -and ([math]::Abs($commitDeltaGiB) -le 1.0)
    $peakOk = ($null -ne $peakDeltaGiB) -and ($peakDeltaGiB -le 1.0)
    $loopOk = ($null -ne $script:ClientLoopsBeforeFleet) -and ($null -ne $loopsAfter) -and ([int]$loopsAfter -le [int]$script:ClientLoopsBeforeFleet)
    $enoughSamples = ($samples.Count -ge 16)
    $noLocalChildren = ($localChildrenSeen.Count -eq 0)
    $moves = $flatOk -and $peakOk
    # THREE OUTCOMES, NOT TWO, because the criterion itself can be undecidable at a given load.
    # The commit bar is a ±1 GiB change. Measured 2026-09-17T03:49:59-03:50:29Z on this laptop with
    # NOTHING dispatched: commit spread 1.105 GiB over 30 s, and 1.203 GiB / +1.09 GiB in the
    # 03:55:45Z run's own control window. A bar that a quiet machine crosses on its own cannot
    # decide anything about a fleet, and calling that PASS or FAIL would be exactly the
    # confident-wrong-number this program exists to stop - so it is reported as a failure of the
    # TEST CONDITION, with both numbers, never as a green tick.
    $ambientExceedsBar = ($script:AmbientSpreadGiB -gt 1.0)
    $childrenLine = "the client ran NO fleet runner of its own (peak $maxChildren dsh runner process(es) against $childrenBefore before the fleet, over $($samples.Count) samples)"
    $commitLine = "commit charge moved $commitDeltaGiB GiB end-to-end and at most $peakDeltaGiB GiB from its pre-fleet value"
    if ($noLocalChildren -and $moves -and $enoughSamples -and -not $ambientExceedsBar) {
        Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'PASS' `
            -Evidence "$childrenLine, and $commitLine while $FleetChildren children ran on another node; the control window (same length, nothing dispatched) moved $($script:AmbientSpreadGiB) GiB" `
            -Detail @($step4Detail)
    } elseif (-not $noLocalChildren) {
        Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'FAIL' `
            -Evidence "THE CLIENT RAN THE FLEET ITSELF: $($localChildrenSeen.Count) of $($samples.Count) samples saw a dsh runner process on this machine (pre-fleet $childrenBefore, peak $maxChildren, first at $($localChildrenSeen[0].at) with pids $($localChildrenSeen[0].childPids)) - a fleet is supposed to run on another node" `
            -Detail @($step4Detail)
    } elseif (-not $enoughSamples) {
        Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'FAIL' `
            -Evidence "$childrenLine, but only $($samples.Count) sample(s) were taken against the ≥16 the brief requires, so the flatness is under-sampled" `
            -Detail @($step4Detail)
    } elseif ($moves -and $ambientExceedsBar) {
        Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'FAIL' `
            -Evidence "$childrenLine and $commitLine, but the CONTROL window - same length, nothing dispatched - moved $($script:AmbientSpreadGiB) GiB, which exceeds the ±1 GiB bar. A bar this machine crosses at rest cannot decide a fleet run; the criterion needs a longer window, a quieter moment, or a bar derived from this host's own noise floor" `
            -Detail @($step4Detail)
    } else {
        Add-Step -Id 'S4' -Name 'client stays flat (§4.4)' -Status 'FAIL' `
            -Evidence "$childrenLine, but $commitLine - outside the ±1 GiB bar (control window: $($script:AmbientSpreadGiB) GiB)" `
            -Detail @($step4Detail)
    }
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
} elseif ($KillNodeHalf -eq '') {
    # RULING, 2026-09-17 (stream O1's brief, from the manager): the stub-gate half of §4.5 STANDS
    # and the fleet-death half is O1's to execute. It is executed by _scratch/o1/kill-test.ps1,
    # which is run with -KillNodeHalf; without that switch this step reports the ruling rather
    # than repeating the old, now-superseded "the conflict is the manager's to resolve".
    Add-Step -Id 'S5' -Name 'a node can die (§4.5)' -Status 'SKIP' `
        -Evidence 'the kill half of §4.5 is now O1''s to execute and is executed by _scratch/o1/kill-test.ps1; pass -KillNodeHalf hermetic (or live) to run it from here' `
        -Detail @(
            '  RULING 2026-09-17 (supersedes the note this step used to print):',
            '  (a) S5b - the broker half, which kills a stub gate THIS HARNESS started - STANDS and is run above/below.',
            '  (b) The fleet-death half is OWNED BY O1. It is executed for real by a standalone test that starts its',
            '      own broker and its own stub gates and kills only a gate it started: _scratch/o1/kill-test.ps1.',
            '      That script is the evidence; its log is _scratch/o1/kill-test/kill-test.log and it is reproduced in',
            '      docs/mesh/82-e2e-run.md with the raw output.',
            '  (c) WHAT IS STILL NOT DONE, stated plainly: no run has been failed by killing a gate on a node that',
            '      a real child was executing on. The brief permits it only with a named node and pid and a run',
            '      knowingly started to fail, and killing a production gate would take a real node out of the mesh',
            '      for every other stream still working tonight. See 82-e2e-run.md §5 for the exact gap.'
        )
} else {
    # ---- the kill half, run as a standalone proof so the killed process is always one this
    # ---- harness started, and so the same test is reproducible outside the harness.
    $killScript = Join-Path (Split-Path -Parent $PSCommandPath) '..\_scratch\o1\kill-test.ps1'
    if (-not (Test-Path $killScript)) {
        Add-Step -Id 'S5' -Name 'a node can die (§4.5)' -Status 'FAIL' `
            -Evidence "-KillNodeHalf was given but the kill test is not where this harness looks for it ($killScript)" `
            -Detail @($step5Detail)
    } else {
        $killDir = Join-Path $script:Scratch 'kill-node'
        New-Item -ItemType Directory -Force -Path $killDir | Out-Null
        $killOut = Join-Path $killDir 'console.txt'
        $killProc = Start-Process pwsh -ArgumentList @('-NoProfile', '-File', $killScript, '-OutDir', $killDir) -PassThru -NoNewWindow `
            -RedirectStandardOutput $killOut -RedirectStandardError (Join-Path $killDir 'console.err')
        [void]$script:Procs.Add($killProc)
        $killOk = $killProc.WaitForExit(180000)
        $killText = if (Test-Path $killOut) { Get-Content $killOut -Raw } else { '' }
        foreach ($line in ($killText -split "`r?`n")) { if ($line.Trim()) { [void]$step5Detail.Add('  kill-test | ' + $line.Trim()) } }
        $killedLine = [regex]::Match($killText, 'KILLING the stub gate for node .(\S+?).: pid (\d+)')
        $reclaimLine = [regex]::Match($killText, 'leases\.live reached 0 after (\d+) ms against a (\d+) ms TTL')
        $nextLine = [regex]::Match($killText, '\(3\) next placement names .(\S+?).; the dead node was .(\S+?).')
        $props = @()
        $props += ($killedLine.Success)
        $props += ($reclaimLine.Success -and [int]$reclaimLine.Groups[1].Value -le [int]$reclaimLine.Groups[2].Value + 3000)
        $props += ($nextLine.Success -and $nextLine.Groups[1].Value -ne $nextLine.Groups[2].Value)
        $held = @($props | Where-Object { $_ }).Count
        [void]$step5Detail.Add("  properties: gate killed = a process THIS TEST started ($($killedLine.Success)); abandoned lease reclaimed within its TTL ($($reclaimLine.Success)); next placement named a different node ($($nextLine.Success))")
        if ($held -eq 3) {
            Add-Step -Id 'S5' -Name 'a node can die (§4.5)' -Status 'PASS' `
                -Evidence "a gate this test started was killed mid-flight (pid $($killedLine.Groups[2].Value), node '$($killedLine.Groups[1].Value)'), the abandoned lease was reclaimed at the broker's own TTL ($($reclaimLine.Groups[1].Value) ms against $($reclaimLine.Groups[2].Value) ms), and the next placement named '$($nextLine.Groups[1].Value)' - a different node - with no manual repair" `
                -Detail @($step5Detail)
        } else {
            Add-Step -Id 'S5' -Name 'a node can die (§4.5)' -Status 'FAIL' `
                -Evidence "$held of 3 §4.5 properties held; the kill test's own log is in the detail" `
                -Detail @($step5Detail)
        }
    }
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
# cleanup — only the processes this script started, and IN A FINALLY so it always runs.
#
# MEASURED 2026-09-16: this block used to run only at the very end of the script, and a run whose
# stdout pipe failed left FIVE stub gates and one ssh tunnel still LISTENING on 127.0.0.1 minutes
# later, plus a sixth under a different port. Found by enumerating my own listeners at the end of
# the session, which is now the habit. A harness that silently leaves gates listening on the
# machine it just measured is worse than one that reports a failure, because the next measurement
# is then taken on a polluted host.
# ---------------------------------------------------------------------------
} finally {
    $killed = 0
    # Pass 0: every hermetic mesh this run started, by registry rather than by remembering to
    # stop it at the right place in the control flow.
    foreach ($mesh in $script:Meshes) {
        if ($mesh) {
            foreach ($g in @($mesh.gates)) {
                if ($g -and $g.proc -and -not $g.proc.HasExited) { Stop-Process -Id $g.proc.Id -Force -ErrorAction SilentlyContinue; $killed++ }
            }
            if ($mesh.proc -and -not $mesh.proc.HasExited) { Stop-Process -Id $mesh.proc.Id -Force -ErrorAction SilentlyContinue; $killed++ }
        }
    }
    # Pass 1: the processes we tracked. Necessary, and provably NOT sufficient - measured
    # 2026-09-16: after this loop had already run, one `mesh-stub-gate --node alpha --slots 10`
    # was still listening. Tracking a PID list and trusting it is how a leak becomes invisible.
    foreach ($proc in $script:Procs) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $killed++
        }
    }
    # Pass 2, the backstop: every process whose PARENT is this script. That is, by definition,
    # a process this script started and nothing else - no other stream's gate, no engine, no
    # helper. Ownership by parentage does not depend on having remembered to add a PID anywhere.
    try {
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$PID" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @('node.exe', 'node', 'ssh.exe', 'ssh') })
        foreach ($child in $children) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
        }
    } catch { }
    Write-Host "  cleaned up $killed process(es) this script started; every engine and every pre-existing gate was left alone."
}

if ($Json) { $report | ConvertTo-Json -Depth 12 }

if ($fail -gt 0) { exit 1 }
if ($Strict -and $skip -gt 0) { exit 2 }
exit 0
