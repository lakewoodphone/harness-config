# Zabz: serve the rattlebyte PAC file over http://127.0.0.1:1081/proxy.pac
#
# Why not a file:// PAC: Chromium's support for file:// PAC URLs is unreliable,
# so Windows' AutoConfigURL points at this local HTTP endpoint instead.
# Uses a raw TcpListener (no HttpListener urlacl / admin requirement).
#
# Log: %USERPROFILE%\.dsh-network\pac-server.log
# Supervised by: rattlebyte-tunnel.ps1

$ErrorActionPreference = 'Continue'

$dir     = "$env:USERPROFILE\.dsh-network"
$log     = Join-Path $dir 'pac-server.log'
$pacPath = Join-Path $dir 'rattlebyte.pac'
$port    = 1081

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) $m" | Add-Content -Path $log }

Log "pac server starting on 127.0.0.1:$port"

$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
try {
    $listener.Start()
} catch {
    Log "start failed: $($_.Exception.Message)"
    exit 1
}
Log 'listening'

while ($true) {
    try {
        $client = $listener.AcceptTcpClient()
        $stream = $client.GetStream()
        # Drain the request line/headers (we serve the same body regardless of path).
        $buf  = New-Object byte[] 2048
        $null = $stream.Read($buf, 0, $buf.Length)

        $body  = [System.IO.File]::ReadAllText($pacPath)
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
        $header = "HTTP/1.1 200 OK`r`n" +
                  "Content-Type: application/x-ns-proxy-autoconfig`r`n" +
                  "Content-Length: $($bytes.Length)`r`n" +
                  "Cache-Control: no-store`r`n" +
                  "Connection: close`r`n`r`n"
        $hb = [System.Text.Encoding]::ASCII.GetBytes($header)
        $stream.Write($hb, 0, $hb.Length)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        $client.Close()
    } catch {
        Log "request error: $($_.Exception.Message)"
    }
}
