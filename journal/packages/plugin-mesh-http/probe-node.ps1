# O2 / transport-v2 reconnaissance on a node, over that node's own sshd.
#
# READ-ONLY. Writes nothing except its own stdout: it lists node processes and their command
# lines, the published engines, whether a gate is listening, and how recently sessions were
# touched (which is how "is anything of the owner's running here" is answered by measurement
# rather than by assumption).
#
# RUN THIS ON THE PIVOT when the target is behind it:
#   pwsh -File probe-via-pivot.ps1 -Pivot desktop-ts -Target mac-mini-ts -TargetPlatform posix
# `-Target` names an ssh alias reachable FROM THE PIVOT; with no -Target it probes the local node.
[CmdletBinding()]
param(
    [string]$Target,
    [ValidateSet('windows', 'posix')][string]$TargetPlatform = 'windows'
)

$ErrorActionPreference = 'Continue'
$env:HTTP_PROXY = ''; $env:HTTPS_PROXY = ''; $env:NO_PROXY = '*'

if ($Target) {
    $script = Get-Content $PSCommandPath -Raw
    $inner = if ($TargetPlatform -eq 'windows') { '"powershell -NoProfile -NonInteractive -Command -"' } else { '"sh -s"' }
    $piped = "Get-Content -Raw -LiteralPath '$PSCommandPath' | ssh -o BatchMode=yes -o ConnectTimeout=20 $Target $inner"
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($piped))
    $deliver = "powershell -NoProfile -NonInteractive -Command `"`$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$b64')); Invoke-Expression `$s`""
    & ssh -o BatchMode=yes -o ConnectTimeout=20 $Target $deliver
    exit $LASTEXITCODE
}

"UTC=" + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
"HOST=" + $env:COMPUTERNAME
""
"== node/engine processes =="
Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('node.exe', 'dsh.exe') } | ForEach-Object {
    $c = $_.CommandLine
    if ($null -eq $c) { $c = '(command line unreadable)' }
    if ($c.Length -gt 200) { $c = $c.Substring(0, 200) + '...' }
    "pid=$($_.ProcessId) ppid=$($_.ParentProcessId) start=$($_.CreationDate) :: $c"
}
""
"== loopback engine on 3089 and gate on 3086 =="
foreach ($port in 3086, 3089) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/mesh/capacity" -TimeoutSec 6 -UseBasicParsing
        "port $port -> $($r.StatusCode) " + $r.Content.Substring(0, [Math]::Min(200, $r.Content.Length))
    } catch {
        "port $port -> ERR $($_.Exception.Message)"
    }
}
""
"== tailscale serve =="
& tailscale serve status 2>&1 | Select-Object -First 8
""
"== node and dsh =="
& node --version 2>&1 | Select-Object -First 1
foreach ($dsh in @(
        'C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js')) {
    if (Test-Path $dsh) { "dsh bin present: $dsh" } else { "dsh bin ABSENT at $dsh" }
}
""
"== sessions touched in the last 30 minutes (is anything of the owner's running here?) =="
$sess = 'C:\Users\ezabz\.dsh\sessions'
if (Test-Path $sess) {
    $recent = Get-ChildItem $sess -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-30) }
    "count=" + @($recent).Count
    $recent | Select-Object -First 8 | ForEach-Object { "  $($_.LastWriteTime.ToString('HH:mm:ss')) $($_.FullName)" }
} else { "no sessions dir at $sess" }
""
"== the web profile's bundle list =="
Get-Content 'C:\Users\ezabz\.dsh\profiles\web\package.json' -Raw -ErrorAction SilentlyContinue
