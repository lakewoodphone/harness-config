# Read-only: what is the desktop's engine doing this minute, and is anything of the owner's or a
# sibling stream's running there? Written because "sessions touched in the last 30 minutes = 147"
# is not the same fact as "147 sessions are live", and the difference decides whether an engine
# restart is safe.
$ErrorActionPreference = 'Continue'
"UTC=" + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
""
"== engine process age and port =="
Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -like '*dsh*web*' } | ForEach-Object {
    "pid=$($_.ProcessId) started=$($_.CreationDate) :: $($_.CommandLine)"
}
""
"== every dsh process running right now (headless one-shots look like this) =="
Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -like '*--profile*' -or $_.CommandLine -like '*dsh*bin.js*' } | ForEach-Object {
    $c = $_.CommandLine; if ($c.Length -gt 150) { $c = $c.Substring(0, 150) + '...' }
    "pid=$($_.ProcessId) ppid=$($_.ParentProcessId) started=$($_.CreationDate) :: $c"
}
""
"== the engine's own children (an MCP fleet is normal; a fleet of dsh one-shots is not) =="
$engine = (Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -like '*dsh*web*' } | Select-Object -First 1).ProcessId
if ($engine) {
    "engine pid=$engine"
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$engine" | ForEach-Object { "  child pid=$($_.ProcessId) $($_.Name)" }
} else { "no engine process found" }
""
"== are the 147 recent sessions being WRITTEN or just read? =="
$sess = 'C:\Users\ezabz\.dsh\sessions'
$recent = Get-ChildItem $sess -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-30) }
"files touched in 30 min: " + @($recent).Count
"touched in the last 2 minutes: " + @($recent | Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-2) }).Count
"newest 3:"
$recent | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | ForEach-Object { "  $($_.LastWriteTime.ToString('HH:mm:ss')) $($_.Length) bytes $($_.Name)" }
"oldest 3 of those 147:"
$recent | Sort-Object LastWriteTime | Select-Object -First 3 | ForEach-Object { "  $($_.LastWriteTime.ToString('HH:mm:ss')) $($_.Length) bytes $($_.Name)" }
""
"== total session directories, and how many changed in the last hour =="
"all session files: " + @(Get-ChildItem $sess -Recurse -File -Filter 'session.v3.jsonl*' -ErrorAction SilentlyContinue).Count
"changed in 60 min: " + @(Get-ChildItem $sess -Recurse -File -Filter 'session.v3.jsonl*' -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-60) }).Count
""
"== what is listening, by port =="
foreach ($port in 3086, 3089, 3099) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($c) { "port $port LISTEN pid=$($c[0].OwningProcess)" } else { "port $port not listening" }
}
