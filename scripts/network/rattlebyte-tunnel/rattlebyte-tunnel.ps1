# Zabz: supervisor for the rattlebyte.com workaround.
#
# Problem it solves: this laptop's home (T-Mobile) line cannot reach
# 185.112.144.0/22 at all - every port times out - while google, cloudflare and
# even 1984.is (the site's own host) are 100% healthy from here, and 8/8 global
# nodes plus the office server and Hetzner all reach the site fine. So the site
# is up; that one prefix is unroutable from this line. We route around it.
#
# What it keeps alive:
#   1. ssh -D 127.0.0.1:11080 -> secratary-ts   (SOCKS proxy via the office LAN)
#   2. pac-server.ps1 on http://127.0.0.1:1081/proxy.pac (PAC file for Windows)
#
# Only rattlebyte.com is routed through the tunnel; everything else stays DIRECT,
# so the blast radius is one domain. If this is not running, the PAC returns
# DIRECT and rattlebyte.com simply fails as it did before - nothing else breaks.
#
# Log:  %USERPROFILE%\.dsh-network\tunnel.log
# Undo: delete startup\zabz-rattlebyte-tunnel.vbs, kill this process, then delete
#       the AutoConfigURL value under
#       HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings

$ErrorActionPreference = 'Continue'

$dir       = "$env:USERPROFILE\.dsh-network"
$log       = Join-Path $dir 'tunnel.log'
$pwsh      = 'C:\Program Files\PowerShell\7\pwsh.exe'
$ssh       = 'C:\Program Files\OpenSSH\ssh.exe'
$hostAlias = 'secratary-ts'
$socksPort = 11080
$pacPort   = 1081

if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
if (-not (Test-Path $ssh)) { $ssh = 'ssh.exe' }

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) $m" | Add-Content -Path $log }
function Listening($p) { [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) }

Log "supervisor start (socks $socksPort, pac $pacPort, alias $hostAlias)"

$sshProc = $null

while ($true) {
    if (-not (Listening $pacPort)) {
        Start-Process -FilePath $pwsh `
                      -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass',
                                      '-File', (Join-Path $dir 'pac-server.ps1')) `
                      -WindowStyle Hidden
        Log 'pac server started'
    }

    if ($null -eq $sshProc -or $sshProc.HasExited) {
        if ($sshProc) { Log "ssh exited (rc=$($sshProc.ExitCode)); restarting" }
        $sshProc = Start-Process -FilePath $ssh `
                                 -ArgumentList @('-o', 'BatchMode=yes',
                                                 '-o', 'ExitOnForwardFailure=yes',
                                                 '-o', 'ServerAliveInterval=20',
                                                 '-o', 'ServerAliveCountMax=3',
                                                 '-o', 'StrictHostKeyChecking=accept-new',
                                                 '-N', '-D', "127.0.0.1:$socksPort", $hostAlias) `
                                 -PassThru -WindowStyle Hidden `
                                 -RedirectStandardError (Join-Path $dir 'ssh-err.log')
        Log "ssh started pid $($sshProc.Id)"
    }

    Start-Sleep -Seconds 15
}
