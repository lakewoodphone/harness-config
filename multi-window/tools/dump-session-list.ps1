<#
.SYNOPSIS
    Dump the raw `session/list` response body so the row set can be inspected exactly.

.DESCRIPTION
    Same wire shape as probe-session-list.ps1 (read from the installed bundles, not guessed).
    Writes the body to a file and prints a bounded summary, because the full value can be large.
#>
[CmdletBinding()]
param(
    [int]$Port = 3099,
    [string]$OutFile = "$env:TEMP\session-list-raw.json",
    [int]$TimeoutSec = 180
)

$ErrorActionPreference = 'Stop'

function Resolve-Token([int]$port) {
    $dir = Join-Path $env:USERPROFILE '.dsh\multi-window\logs'
    foreach ($path in @((Join-Path $dir "$port.log")) + @(Get-ChildItem $dir -Filter "$port-*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 5 -ExpandProperty FullName)) {
        if (-not (Test-Path $path)) { continue }
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
$client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)

$origin = "http://127.0.0.1:$Port"
$token = Resolve-Token $Port
if (-not $token) { throw "no launch token for port $Port" }
$client.GetAsync($token).GetAwaiter().GetResult().Dispose()

$rpcId = [guid]::NewGuid().ToString()
$body = '{"type":"client-request","rpcId":"' + $rpcId + '","method":"session/list","payload":{"args":{"_request":{}}}}'
$req = [System.Net.Http.HttpRequestMessage]::new('POST', "$origin/api/session/list")
$req.Content = [System.Net.Http.StringContent]::new($body, [Text.Encoding]::UTF8, 'application/json')
$sw = [Diagnostics.Stopwatch]::StartNew()
$resp = $client.SendAsync($req).GetAwaiter().GetResult()
$text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
$sw.Stop()
$client.Dispose()

[System.IO.File]::WriteAllText($OutFile, $text, (New-Object System.Text.UTF8Encoding($false)))
"HTTP $([int]$resp.StatusCode) in $([math]::Round($sw.Elapsed.TotalMilliseconds)) ms; body $($text.Length) chars -> $OutFile"

$j = $text | ConvertFrom-Json
"envelope.type   : $($j.type)"
"result.ok       : $($j.result.ok)"
$v = $j.result.value
"value type      : $($v.GetType().FullName)"
if ($v -is [System.Management.Automation.PSCustomObject]) {
    "value members   : $(($v.PSObject.Properties | ForEach-Object { $_.Name }) -join ', ')"
} elseif ($v -is [array]) {
    "value count     : $($v.Count)"
}
