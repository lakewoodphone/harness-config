<#
.SYNOPSIS
    Probe the DSH connection RPC `session/list` the way the browser client does, and time it.

.DESCRIPTION
    THE SHAPE IS NOT GUESSED. It is read out of the installed client and host bundles:

      client  @deepseek-ai/dsh-client-connection/lib/client.js:6194-6216  createWebConnectionRpc.call
              POST <channel>/<endpoint>            channel = "/api"
              content-type: application/json
              { type: "client-request", rpcId: <uuid>, method: <endpoint>, payload: {...} }
              -> { type: "server-response", rpcId: <same>, result: { ok: true, value: ... } }

      host    @deepseek-ai/dsh-client-connection/lib/index.js:635-664   rpcFetchHandler
              request.method !== "POST"            -> 404 "not found"
              content-type not application/json    -> 415
              method !== endpoint                  -> gateway/bad-request
      (this is exactly why a GET to /api/session/list answers 404 -- a verb error, not a symptom)

      payload @deepseek-ai/dsh-api-session-controller/lib/index.js:2821
              `@param _request - reserved empty list request.`  -> the call takes no arguments

    AUTH: /api is behind a browser-trust fence. The launch token printed by `dsh web` is exchanged
    for a cookie by a normal GET (the server 303s to "/"), which is what a window does at startup.
    This probe replays exactly that exchange with its own throwaway cookie jar, so it reads the
    engine's real state without touching any open window.

.PARAMETER Port
    Engine port. Default 3099 (windows.json primaryPort).
.PARAMETER Base
    Alternate origin whose Host header the probe presents (an alias port from dshw-origins.mjs).
.PARAMETER Repeats
    How many times to issue the call. Each one is timed separately.
#>
[CmdletBinding()]
param(
    [int]$Port = 3099,
    [string]$LogPath = '',
    [int]$Repeats = 3
)

$ErrorActionPreference = 'Stop'

function Resolve-Token([int]$port, [string]$explicitLog) {
    $candidates = @()
    if ($explicitLog) { $candidates += $explicitLog }
    $candidates += (Join-Path $env:USERPROFILE ".dsh\multi-window\logs\$port.log")
    $candidates += (Get-ChildItem (Join-Path $env:USERPROFILE '.dsh\multi-window\logs') -Filter "$port-*.log" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 5 -ExpandProperty FullName)
    foreach ($path in $candidates) {
        if (-not $path -or -not (Test-Path $path)) { continue }
        $text = Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue
        if (-not $text) { continue }
        $m = [regex]::Matches($text, 'dsh web:\s*(\S+)')
        for ($i = $m.Count - 1; $i -ge 0; $i--) {
            $u = $m[$i].Groups[1].Value
            if ($u -match "127\.0\.0\.1:$port/" -and $u -match 'token=') { return $u }
        }
    }
    return $null
}

$handler = [System.Net.Http.HttpClientHandler]::new()
$handler.AllowAutoRedirect = $true
$handler.UseCookies = $true
$handler.CookieContainer = [System.Net.CookieContainer]::new()
$client = [System.Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds(120)

$origin = "http://127.0.0.1:$Port"

$token = Resolve-Token $Port $LogPath
if (-not $token) { throw "no launch token found for port $Port -- check the engine log" }

# 1. the token exchange, exactly as a window boot does it
$sw = [Diagnostics.Stopwatch]::StartNew()
$ex = $client.GetAsync($token).GetAwaiter().GetResult()
$sw.Stop()
"auth exchange : HTTP $([int]$ex.StatusCode) in $([math]::Round($sw.Elapsed.TotalMilliseconds)) ms  (token -> cookie)"
$ex.Dispose()
$cookies = $handler.CookieContainer.GetCookies([uri]$origin)
"cookies       : $(($cookies | ForEach-Object { $_.Name }) -join ', ')"

# 2. the call, in the client's own envelope
$call = {
    param($client, $origin, $payloadJson)
    $rpcId = [guid]::NewGuid().ToString()
    $body = '{"type":"client-request","rpcId":"' + $rpcId + '","method":"session/list","payload":' + $payloadJson + '}'
    $req = [System.Net.Http.HttpRequestMessage]::new('POST', "$origin/api/session/list")
    $req.Content = [System.Net.Http.StringContent]::new($body, [Text.Encoding]::UTF8, 'application/json')
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = $client.SendAsync($req).GetAwaiter().GetResult()
    $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $sw.Stop()
    return [pscustomobject]@{ status = [int]$resp.StatusCode; ms = [math]::Round($sw.Elapsed.TotalMilliseconds, 1); body = $text }
}.GetNewClosure()

# The payload is `{ args: { <declared parameter>: ... } }`, and this was established by a wrong
# guess, not by reading: `{"_request":{}}` is accepted by the connection layer and then rejected by
# the gateway with "Remote payload must contain exactly one plain-object args field"
# (dsh-api-gateway/lib/index.js, remoteRequest). The fixture transport in the same client bundle
# says the same thing in one line: `const args = payload.args; ... sessionApi.list(args._request)`.
$shapes = @(
    [pscustomobject]@{ name = 'args._request = {}'; json = '{"args":{"_request":{}}}' },
    [pscustomobject]@{ name = 'args = {}';         json = '{"args":{}}' }
)
$chosen = $null
foreach ($shape in $shapes) {
    $r = & $call $client $origin $shape.json
    "shape $($shape.name)  -> HTTP $($r.status)  $($r.ms) ms"
    if ($r.status -eq 200 -and $r.body -notmatch 'invalid client-request') { $chosen = $shape; break }
    if ($r.body.Length -lt 600) { "   body: $($r.body)" } else { "   body: $($r.body.Substring(0,600))..." }
}
if (-not $chosen) { throw 'no accepted payload shape' }
"payload shape : $($chosen.name)  (accepted)"

# 3. time it, and count the rows
for ($i = 1; $i -le $Repeats; $i++) {
    $r = & $call $client $origin $chosen.json
    $n = $null; $ok = $null; $err = $null
    try {
        $j = $r.body | ConvertFrom-Json
        $ok = $j.result.ok
        if ($ok) { $n = @($j.result.value).Count } else { $err = "$($j.result.error.code): $($j.result.error.message)" }
    } catch { $err = "unparseable: $($r.body.Substring(0, [Math]::Min(200, $r.body.Length)))" }
    "run $i          : HTTP $($r.status) in $($r.ms) ms  ok=$ok  rows=$n  $err"
    if ($i -eq 1 -and $ok) {
        $rows = @($j.result.value)
        "  first 5 rows:"
        $rows | Select-Object -First 5 | ForEach-Object { "    {0}  updated={1}" -f $_.sessionId, $_.updatedAt }
        "  distinct cwd values: $(@($rows | Where-Object { $_.cwd } | ForEach-Object { $_.cwd } | Select-Object -Unique).Count)"
        "  blank rows: $(@($rows | Where-Object { $_.blank }).Count)"
    }
}

$client.Dispose()
