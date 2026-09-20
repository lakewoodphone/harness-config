# Read-only: the three facts that decide whether restarting this node's engine is safe and whether
# the route would be reachable afterwards.
#
#   1. IS THE ENGINE ALIVE ON 3099? A "LISTEN" entry was measured there while 3089 refused — the
#      gate's own default is `--engine-port 3089`, so which port it was started with is the fact
#      that decides reachability, not the port that happens to be listening.
#   2. WHAT PORT WAS THE GATE STARTED WITH? Its command line is the only honest answer.
#   3. IS ANYONE ATTACHED? A connected client on the engine's port is a browser tab belonging to a
#      person; an engine with no connections and no agent loops is an idle process, which is what a
#      restart costs.
$ErrorActionPreference = 'Continue'
"UTC=" + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
""
"== 1. the engine on 3099 answers its own /healthz? =="
$env:HTTP_PROXY = ''; $env:HTTPS_PROXY = ''; $env:NO_PROXY = '*'
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:3099/healthz' -TimeoutSec 10 -UseBasicParsing
    "HTTP $($r.StatusCode)"
    $h = $r.Content | ConvertFrom-Json
    "identity: pid=$($h.identity.pid) node=$($h.identity.node) started=$($h.identity.startedAt)"
    "sessions: agentLoopsRunning=$($h.sessions.agentLoopsRunning) live=$($h.sessions.live) root=$($h.sessions.root)"
    "loop lag: p50=$($h.loop.p50Ms)ms p95=$($h.loop.p95Ms)ms"
} catch {
    "could not read /healthz: $($_.Exception.Message)"
}
""
"== 1b. the same two /healthz shapes the gate uses (401 = fence passed, cookie missing) =="
try {
    $r2 = Invoke-WebRequest -Uri 'http://127.0.0.1:3099/' -TimeoutSec 8 -UseBasicParsing -SessionVariable s
    "GET / -> HTTP $($r2.StatusCode) (a gate in front signs a cold visitor in; the engine alone answers 401)"
} catch { "GET / -> $($_.Exception.Message)" }
""
"== 2. the gate's own command line, and what it proxies to =="
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*phone-gate*' } | ForEach-Object {
    "pid=$($_.ProcessId) started=$($_.CreationDate) :: $($_.CommandLine)"
}
Get-CimInstance Win32_Process -Filter "Name='python3.exe'" | Where-Object { $_.CommandLine -like '*phone-gate*' } | ForEach-Object {
    "pid=$($_.ProcessId) started=$($_.CreationDate) :: $($_.CommandLine)"
}
""
"== 3. who is connected to this node right now =="
foreach ($port in 3086, 3099) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Established' }
    "port $port established connections: " + @($conns).Count
    $conns | Select-Object -First 10 | ForEach-Object { "   $($_.RemoteAddress):$($_.RemotePort) state=$($_.State)" }
}
""
"== 3b. tailscale serve on this node =="
& tailscale serve status 2>&1 | Select-Object -First 6
""
"== 4. can this node boot a child profile at all? (the property v2 exists to stop needing) =="
$links = @(Get-ChildItem -Path 'C:\Users\ezabz\.dsh\profiles' -Recurse -Depth 3 -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.LinkType } | Select-Object -First 3)
"junctions under profiles: " + $links.Count
foreach ($l in $links) {
    try { $null = Get-ChildItem -LiteralPath $l.FullName -Force -ErrorAction Stop | Select-Object -First 1; "  OK   $($l.Name)" }
    catch { "  FAIL $($l.Name) :: $($_.Exception.Message)" }
}
