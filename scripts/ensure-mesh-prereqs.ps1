<#
.SYNOPSIS
  Keep the LOCAL services the mesh depends on running, and say so when they are not.

.DESCRIPTION
  Measured 2026-09-15 (PAIN P164). Two failures of the same shape happened in one
  evening on ZABZ-TECH, and both were invisible from the outside:

    * Tailscale was Stopped (StartType Automatic). Every MagicDNS name stopped
      resolving, so `ssh secratary-ts`, the harness-config git remote and every
      agent's hop to another node failed - which reads as "the other machine is
      down". I misdiagnosed a laptop as offline because of it. It then stopped
      AGAIN within the hour.
    * IP Helper (iphlpsvc) was Stopped, which silently killed the netsh portproxy
      that publishes the secretary API on 192.168.50.138:8002. The app was healthy
      on loopback the whole time; the LAN address simply refused connections.

  Neither is watched by anything, and both are prerequisites for the sync path
  itself, so this check must not live inside what it protects. It is deliberately
  dumb: start what should be running, record what it found, exit 0 unless something
  is still broken. It never stops a service, never changes a firewall, and never
  touches application state.

.PARAMETER Status
  Print the last run and exit without changing anything.

.EXAMPLE
  pwsh -File scripts\ensure-mesh-prereqs.ps1
  pwsh -File scripts\ensure-mesh-prereqs.ps1 -Status
#>
[CmdletBinding()]
param(
    [switch]$Status,
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ConfigPath) { $ConfigPath = Join-Path $scriptDir 'mesh-prereqs.json' }

$statusDir = Join-Path $env:USERPROFILE '.dsh-sync-status'
$statusFile = Join-Path $statusDir 'mesh-prereqs.json'
$logFile = Join-Path $statusDir 'mesh-prereqs.log'

function Write-Log([string]$message) {
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'), $message
    if (-not (Test-Path $statusDir)) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

if ($Status) {
    if (Test-Path $statusFile) { Get-Content $statusFile -Raw } else { 'no mesh-prereqs status recorded yet' }
    return
}

$hostName = $env:COMPUTERNAME
$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$settings = $config.defaults
if ($config.hosts.PSObject.Properties.Name -contains $hostName) { $settings = $config.hosts.$hostName }

$findings = @()
$repaired = @()
$failed = @()

function Ensure-Service([string]$name) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $svc) { return @{ name = $name; state = 'absent' } }
    if ($svc.Status -eq 'Running') { return @{ name = $name; state = 'running' } }
    try {
        Start-Service -Name $name -ErrorAction Stop
        Start-Sleep -Seconds 2
        $now = (Get-Service -Name $name).Status
        return @{ name = $name; state = "was-$($svc.Status)-now-$now"; started = $true }
    } catch {
        return @{ name = $name; state = "was-$($svc.Status)-start-failed"; error = $_.Exception.Message.Substring(0, [Math]::Min(120, $_.Exception.Message.Length)) }
    }
}

if ($settings.iphlpsvc) {
    # IP Helper FIRST. Measured 2026-09-15: Tailscale declares iphlpsvc as a required
    # service, so when IP Helper dies, Windows stops Tailscale with it and never brings
    # it back (iphlpsvc's own recovery only restarts iphlpsvc). Repairing the dependency
    # before its dependent is the only order that converges in one pass.
    $r = Ensure-Service 'iphlpsvc'
    $findings += "iphlpsvc:$($r.state)"
    if ($r.started) { $repaired += "started IP Helper ($($r.state))" }
    if ($r.state -like '*failed*') { $failed += "iphlpsvc $($r.state): $($r.error)" }
}

if ($settings.tailscale) {
    $r = Ensure-Service 'Tailscale'
    $findings += "tailscale:$($r.state)"
    if ($r.started) { $repaired += "started Tailscale ($($r.state))" }
    if ($r.state -like '*failed*') { $failed += "Tailscale $($r.state): $($r.error)" }
}

foreach ($proxy in @($settings.portproxy)) {
    if ($null -eq $proxy) { continue }
    $table = (& netsh interface portproxy show v4tov4 2>&1) -join "`n"
    $present = ($table -match [regex]::Escape($proxy.listenAddress)) -and ($table -match [regex]::Escape("$($proxy.listenPort)"))
    if ($present) {
        $findings += "portproxy:$($proxy.listenAddress):$($proxy.listenPort):present"
    } else {
        try {
            & netsh interface portproxy add v4tov4 listenaddress=$($proxy.listenAddress) listenport=$($proxy.listenPort) connectaddress=$($proxy.connectAddress) connectport=$($proxy.connectPort) | Out-Null
            $findings += "portproxy:$($proxy.listenAddress):$($proxy.listenPort):repaired"
            $repaired += "re-added portproxy $($proxy.listenAddress):$($proxy.listenPort) -> $($proxy.connectAddress):$($proxy.connectPort)"
        } catch {
            $findings += "portproxy:$($proxy.listenAddress):$($proxy.listenPort):failed"
            $failed += "portproxy $($proxy.listenAddress):$($proxy.listenPort) could not be added: $($_.Exception.Message.Substring(0, [Math]::Min(120, $_.Exception.Message.Length)))"
        }
    }
}

$result = if ($failed.Count -gt 0) { 'attention' } elseif ($repaired.Count -gt 0) { 'repaired' } else { 'clean' }
$record = [ordered]@{
    updated = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    host    = $hostName
    result  = $result
    detail  = ($findings -join ' ')
    repaired = $repaired
    failed  = $failed
}
if (-not (Test-Path $statusDir)) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
($record | ConvertTo-Json -Depth 4) | Set-Content -Path $statusFile -Encoding UTF8

Write-Log "mesh-prereqs host=$hostName result=$result $($findings -join ' ')"
if ($failed.Count -gt 0) {
    Write-Log "mesh-prereqs FAILED: $($failed -join '; ')"
    exit 1
}
exit 0
