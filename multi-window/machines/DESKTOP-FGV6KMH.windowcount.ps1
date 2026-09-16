# Print how many harness app windows are alive, for the launcher wrapper to report.
#
# Kept as its own file because the alternative is a PowerShell one-liner nested inside cmd.exe
# quoting, and that is exactly the kind of thing that works once and then silently stops working.
# Exit 0 always; the number goes to stdout, or 0 when nothing can be determined.
$ErrorActionPreference = 'Continue'
$url = 'http://127.0.0.1:3099'
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue
    $n = @($procs | Where-Object {
        $_.CommandLine -and
        $_.CommandLine.Contains('--app=') -and
        -not $_.CommandLine.Contains('--type=')
    }).Count
    Write-Output $n
} catch {
    Write-Output 0
}
