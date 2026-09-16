# Zabz: health check for the rattlebyte.com workaround.
#   pwsh -File C:\Users\ezabz\.dsh-network\verify-rattlebyte.ps1
#
# The site is unreachable from this line directly (185.112.144.0/22 blackholed
# from T-Mobile); the tunnel via the office server is what makes it work.
# Healthy output: socks listener True, pac listener True, tunnel code=302,
# and the direct attempt still failing (proving the tunnel is doing the work).
#
# NOTE: this is a transport-level check (curl). Browser-level check:
#   pwsh -File C:\Users\ezabz\.dsh-network\verify-rattlebyte.ps1 -Browser

param([switch]$Browser)

$ProgressPreference = 'SilentlyContinue'
$k = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"

function Test-Port($p) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $t = $c.BeginConnect('127.0.0.1', $p, $null, $null)
        if ($t.AsyncWaitHandle.WaitOne(1200)) { $c.EndConnect($t); $c.Close(); return $true }
        $c.Close(); return $false
    } catch { return $false }
}

Write-Output ("AutoConfigURL : " + (Get-ItemProperty -Path $k).AutoConfigURL)
Write-Output ("socks 11080   : " + (Test-Port 11080))
Write-Output ("pac   1081    : " + (Test-Port 1081))

Write-Output "--- through the tunnel ---"
curl.exe -sS -o NUL --socks5-hostname 127.0.0.1:11080 -m 30 `
         -w "rattlebyte: code=%{http_code} final=%{url_effective} total=%{time_total}s`n" `
         -L https://rattlebyte.com 2>&1

Write-Output "--- direct (expected to fail; this is the block we route around) ---"
curl.exe -sS -o NUL --connect-timeout 4 -m 8 -w "direct: code=%{http_code}`n" https://rattlebyte.com 2>&1

Write-Output "--- control (must stay DIRECT) ---"
curl.exe -sS -o NUL --connect-timeout 5 -m 10 -w "google: code=%{http_code}`n" https://www.google.com 2>&1

if ($Browser) {
    Write-Output "--- browser-level (system PAC) ---"
    Write-Output "Open https://rattlebyte.com in Chrome/Edge; or run the Playwright tool."
}
