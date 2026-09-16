<#
.SYNOPSIS
  One command that answers "can I actually use each node from here, right now?".

.DESCRIPTION
  Written because the obvious check is wrong. Measured 2026-09-16 on ZABZ-YOGA:

    * `tailscale serve status` printed a correct-looking mapping
      (https://zabz-yoga-1.tail93e6e6.ts.net -> http://127.0.0.1:3086) at the exact moment the
      published URL answered **502**, because nothing was listening on 3086. Publication config is
      not evidence a node is usable; only a request is.
    * A **403** and a **401** on the same URL mean opposite things and both look like failure.
      403 = the engine's /api fence refused the Host (this node was published without a gate or a
      `--trusted-host`). 401 = the fence passed and only a cookie is missing, which is the correct
      answer for an anonymous client and means the node is WORKING.
    * This laptop sets a proxy AutoConfigURL (a .pac file), and a proxy is fully capable of
      manufacturing a 502 that has nothing to do with the node. Every request here therefore goes
      out with the proxy explicitly disabled.
    * GET / through a gate is **200** for a cold visitor (the gate signs you in); GET / with no
      gate on a fence-clean engine is **401**. Both are healthy, and the check accepts both.

  So the check is per node: fetch `/` and `/api`, classify the codes, then prove an AUTHENTICATED
  path exists by reusing the cookie from `/` to call `/healthz`. A node that answers `/` but fails
  `/healthz` with a cookie is published and useless, which is the failure this command exists to
  name.

.EXAMPLE
  pwsh -File scripts\mesh-health.ps1
  pwsh -File scripts\mesh-health.ps1 -Nodes zabz-tech,secratary -Json
  pwsh -File scripts\mesh-health.ps1 -Nodes zabz-yoga-1 -TimeoutSec 40
#>
[CmdletBinding()]
param(
    [string[]]$Nodes = @('zabz-yoga-1', 'zabz-tech', 'secratary'),
    [int]$TimeoutSec = 20,
    [switch]$Json
)

$ErrorActionPreference = 'Continue'
$statusDir = Join-Path $env:USERPROFILE '.dsh-sync-status'
$statusFile = Join-Path $statusDir 'mesh-health.json'

# Proxy OFF, cookies ON, in one object. Deliberately not Invoke-WebRequest: `-NoProxy` is
# PowerShell 7 only, the .pac proxy on this machine can invent a 502, and a health check that can
# be fooled by the local proxy is worse than none.
function New-ProbeClient([int]$timeoutSeconds) {
    try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch { }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $true
    $handler.CookieContainer = New-Object System.Net.CookieContainer
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($timeoutSeconds)
    return $client
}

function Get-Probe($client, [string]$url) {
    $result = [ordered]@{ url = $url; code = 0; body = ''; error = '' }
    try {
        $response = $client.GetAsync($url).GetAwaiter().GetResult()
        $result.code = [int]$response.StatusCode
        $result.body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    } catch {
        $result.error = $_.Exception.Message
        $inner = $_.Exception.InnerException
        if ($inner) { $result.error = "$($inner.GetType().Name): $($inner.Message)" }
    }
    return $result
}

function Classify([string]$what, $probe, [int[]]$pass) {
    if ($probe.error) { return "FAIL: $what could not be reached - $($probe.error)" }
    if ($pass -contains $probe.code) { return "PASS: $what -> $($probe.code)" }
    $why = switch ($probe.code) {
        403 { "fence refused the Host: published WITHOUT a gate and without --trusted-host" }
        502 { "Serve has no backend listening on the port it proxies to" }
        404 { "no such route on this engine" }
        200 { "answered 200 where an unauthenticated answer was expected" }
        default { "unexpected status" }
    }
    return "FAIL: $what -> $($probe.code) ($why)"
}

function Get-FirstProperty($object, [string[]]$names) {
    # The health surface has been renamed once already (an `eventLoop` object became `loop`), so a
    # health check that hard-codes one spelling breaks silently the next time. Take the first name
    # that exists and say `n/a` when none does — a missing number must never render as a number.
    if ($null -eq $object) { return 'n/a' }
    foreach ($n in $names) {
        $p = $object.PSObject.Properties[$n]
        if ($p -and $null -ne $p.Value) { return $p.Value }
    }
    return 'n/a'
}

$records = @()
foreach ($node in $Nodes) {
    # A node may be given as a short name; the tailnet FQDN is what the certificate is for.
    $host_ = $node.Trim()
    if ($host_ -notmatch '\.') { $host_ = "$host_.tail93e6e6.ts.net" }
    $base = "https://$host_"
    $checks = @()
    $detail = ''
    try {
        # 1. THE COLD VISITOR, with a cookie jar. 200 = a gate signed it in; 401 = the fence passed
        #    and only a cookie is missing, which is the correct answer from a fence-clean engine
        #    reached directly. Anything else is a real fault.
        $anon = New-ProbeClient $TimeoutSec
        try {
            $root = Get-Probe $anon "$base/"
            $checks += Classify 'GET / (cold visitor with a cookie jar)' $root @(200, 401)

            # 2. THE FENCE, on a SECOND client that has no cookie. A gate in front means the engine
            #    sees a loopback authority, so /api answers 401 (fence passed, unauthenticated).
            #    403 here means the node is published without a gate or --trusted-host.
            #    MEASURED 2026-09-16: reusing the cookie-bearing client for this check is wrong —
            #    with a valid cookie /api answers 404 (`no such route`), which is the correct
            #    answer for an API prefix with no route behind it, and reads as a failure.
            $bare = New-ProbeClient $TimeoutSec
            try {
                $api = Get-Probe $bare "$base/api"
                $checks += Classify 'GET /api (no cookie)' $api @(401)
            } finally { $bare.Dispose() }

            # 3. THE ONE THAT PROVES IT IS USABLE: an authenticated API call, reusing the cookie.
            $health = Get-Probe $anon "$base/healthz"
            # 404 = plugin-health is not mounted on that node. That is a gap, not a fault: the
            # front door works and the node can still serve work, so it is reported as a warning
            # rather than a failure. Anything else that is not 200 is a failure.
            if ($health.code -eq 404) {
                $checks += 'WARN: GET /healthz -> 404 (plugin-health not mounted on this node)'
            } else {
                $checks += Classify 'GET /healthz (with the cookie from GET /)' $health @(200)
            }
            if ($health.code -eq 200 -and $health.body) {
                try {
                    $h = $health.body | ConvertFrom-Json
                    $p95 = Get-FirstProperty $h.loop 'p95Ms', 'p95', 'lagP95Ms', 'p95LagMs'
                    $rssMiB = if ($h.memory.rss) { [int]($h.memory.rss / 1MB) } else { '' }
                    $detail = "pid=$($h.identity.pid) node=$($h.identity.node) loops=$($h.sessions.agentLoopsRunning)/$($h.sessions.live) rss=${rssMiB}MiB loopP95=$p95"
                } catch { $detail = 'healthz answered 200 but did not parse as JSON' }
            }
        } finally { $anon.Dispose() }
    } catch { $checks += "FAIL: probe error - $($_.Exception.Message)" }

    $failed = @($checks | Where-Object { $_ -like 'FAIL*' })
    $records += [ordered]@{
        node   = $host_
        status = if ($failed.Count -eq 0) { if (@($checks | Where-Object { $_ -like 'WARN*' }).Count) { 'degraded' } else { 'healthy' } }
                 elseif ($failed.Count -lt $checks.Count) { 'degraded' } else { 'down' }
        detail = $detail
        checks = $checks
    }
}

if ($Json) {
    $records | ConvertTo-Json -Depth 6
} else {
    foreach ($r in $records) {
        $colour = switch ($r.status) { 'healthy' { 'Green' } 'degraded' { 'Yellow' } default { 'Red' } }
        Write-Host ("{0,-28} {1,-9} {2}" -f $r.node, $r.status, $r.detail) -ForegroundColor $colour
        foreach ($c in $r.checks) {
            $cColour = if ($c -like 'PASS*') { 'DarkGray' } else { 'Red' }
            Write-Host ("    $c") -ForegroundColor $cColour
        }
    }
}

if (-not (Test-Path $statusDir)) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
@{
    updated = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    from    = $env:COMPUTERNAME
    nodes   = $records
} | ConvertTo-Json -Depth 8 | Set-Content -Path $statusFile -Encoding UTF8

$bad = @($records | Where-Object { $_.status -ne 'healthy' })
if ($bad.Count -gt 0) { exit 1 }
exit 0
