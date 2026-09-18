# Remote measurement for a second machine, piped over ssh (avoids nested quoting entirely).
# Usage:  Get-Content measure-remote.ps1 | ssh desktop-ts "powershell -NoProfile -Command -"
$ErrorActionPreference = 'SilentlyContinue'

function Line($k, $v) { "{0,-22}: {1}" -f $k, $v }

$os = Get-CimInstance Win32_OperatingSystem
Line 'host' $env:COMPUTERNAME
Line 'os' ("{0} build {1}" -f $os.Caption, $os.BuildNumber)
Line 'cores' ([Environment]::ProcessorCount)
Line 'ram_total_gb' ([math]::Round($os.TotalVisibleMemorySize / 1MB, 1))
Line 'ram_free_gb' ([math]::Round($os.FreePhysicalMemory / 1MB, 1))
Line 'commit_gb' ([math]::Round((Get-Counter '\Memory\Committed Bytes' -MaxSamples 1).CounterSamples.CookedValue / 1GB, 1))
Line 'pages_in_per_s' ([math]::Round((Get-Counter '\Memory\Pages Input/sec' -MaxSamples 1).CounterSamples.CookedValue))

$p = Get-CimInstance Win32_Process
Line 'processes' $p.Count
Line 'node_procs' (@($p | Where-Object { $_.Name -eq 'node.exe' }).Count)
Line 'edge_procs' (@($p | Where-Object { $_.Name -eq 'msedge.exe' }).Count)
Line 'chrome_procs' (@($p | Where-Object { $_.Name -eq 'chrome.exe' }).Count)
Line 'conhost_procs' (@($p | Where-Object { $_.Name -eq 'conhost.exe' }).Count)

$engines = @($p | Where-Object { $_.CommandLine -match 'dsh\\lib\\bin\.js\s+web' })
Line 'dsh_engines' $engines.Count
foreach ($e in $engines) {
    $port = if ($e.CommandLine -match '--port\s+(\d+)') { $Matches[1] } else { '?' }
    Line ("  engine_pid_{0}" -f $e.ProcessId) ("port {0}, MB {1}" -f $port, [math]::Round($e.WorkingSetSize / 1MB))
}

$mcp = @($p | Where-Object { $_.CommandLine -match 'mcp-fetch-server|@playwright/mcp|firecrawl-mcp|context7-mcp|mcp-remote|ps_mcp_server' })
Line 'mcp_server_procs' $mcp.Count
Line 'mcp_npx_shims' (@($mcp | Where-Object { $_.CommandLine -match 'npx-cli' }).Count)
$direct = @($mcp | Where-Object { $_.CommandLine -match 'node_modules\\.*\\dist\\index\.js' }).Count
$mcpRows = if ($direct -gt 0) { 'yes' } else { 'no' }
Line 'mcp_rows_direct' $mcpRows

$hc = Join-Path $env:USERPROFILE 'code\harness-config'
if (Test-Path $hc) {
    Line 'harness_branch' ((git -C $hc rev-parse --abbrev-ref HEAD) 2>&1 | Select-Object -First 1)
    Line 'harness_head' (((git -C $hc log --oneline -1) 2>&1 | Select-Object -First 1))
} else { Line 'harness-config' 'MISSING' }

$s = Join-Path $env:USERPROFILE '.dsh\settings.yaml'
if (Test-Path $s) {
    $line = Select-String -Path $s -Pattern 'maxParallelToolCalls:\s*(\d+)'
    Line 'maxParallelToolCalls' ($(if ($line) { $line.Matches.Groups[1].Value } else { 'unset (code default 10)' }))
} else { Line 'settings.yaml' 'MISSING' }

Line 'node_compile_cache' ([Environment]::GetEnvironmentVariable('NODE_COMPILE_CACHE', 'User'))
Line 'mcp_tools_dir' (Test-Path (Join-Path $env:USERPROFILE '.dsh\tools\mcp'))
Line 'verify_script' (Test-Path (Join-Path $hc 'scripts\harness-verify.ps1'))
Line 'reaper_task' ((Get-ScheduledTask -TaskName 'DSH Process Reaper').State)
