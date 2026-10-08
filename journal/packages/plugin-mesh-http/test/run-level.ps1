# One measurement level: start the target's sampler, drive N concurrent children over ONE
# transport, stop the sampler, and bring both records home.
#
# WHY THE SAMPLER IS STARTED DETACHED AND STOPPED EXPLICITLY. Launched as a child of the ssh
# session, the sampler dies when that session closes — measured, and it is why 84-calibration.md
# §6.5 has an empty CSV for its one real-dispatcher window. Launched detached it survives; the
# price is that it must be STOPPED, or it is a stray process on somebody else's machine. Both
# halves are here, and the pid is printed.
[CmdletBinding()]
param(
  [string]$Alias = 'desktop-ts',
  [Parameter(Mandatory)][string]$Label,
  [ValidateSet('v1', 'v2')][string]$Transport = 'v2',
  [int]$N = 1,
  [int]$TimeoutSec = 300,
  [string]$Node = 'zabz-tech',
  [string]$Out = "$env:USERPROFILE\mesh-sweep",
  [string]$SecretFile = "$env:TEMP\mesh-tech-secret.env"
)

$ErrorActionPreference = 'Continue'
$Pkg = Split-Path -Parent $PSScriptRoot
$sshHelper = Join-Path $PSScriptRoot 'ssh-file.ps1'
$remoteSampler = "C:/Users/ezabz/code/harness-config/packages/plugin-mesh-http/test/sweep-sampler.ps1"
$localOut = Join-Path $Out $Label
New-Item -ItemType Directory -Force -Path $localOut | Out-Null

function Invoke-Remote([string]$Program, [int]$Timeout = 120) {
  $o = Join-Path $env:TEMP ("remote-$([guid]::NewGuid().ToString('N')).txt")
  & pwsh -NoProfile -File $sshHelper -Alias $Alias -Program $Program -OutFile $o -TimeoutSec $Timeout | Out-Null
  $text = Get-Content -LiteralPath $o -Raw -ErrorAction SilentlyContinue
  return ($text -split "`r?`n" | Where-Object { $_ -notmatch '^SSH-(EXIT|STDOUT|STDERR)=' }) -join "`n"
}

# ---- 1. start the sampler, detached ---------------------------------------------------------
$startProgram = @"
`$ErrorActionPreference = 'Continue'
`$csv = `"`$env:TEMP\sweep-$Label.csv`"
Remove-Item `$csv -Force -ErrorAction SilentlyContinue
Remove-Item "`$csv.done" -Force -ErrorAction SilentlyContinue
`$sp = Start-Process -FilePath 'pwsh' -ArgumentList @('-NoProfile','-File','$remoteSampler','-Csv',`$csv,'-PeriodSec','3','-DurationSec','900','-Label','$Label') -WindowStyle Hidden -PassThru
Write-Output ("SAMPLER_PID=" + `$sp.Id)
"@
$started = Invoke-Remote -Program $startProgram -Timeout 90
Write-Host "[$Label] $started"
$samplerPid = ($started | Select-String -Pattern 'SAMPLER_PID=(\d+)').Matches[0].Groups[1].Value

# ---- 2. wait for the sampler to be producing rows -------------------------------------------
$remote = $Node
for ($i = 0; $i -lt 12; $i += 1) {
  Start-Sleep -Seconds 4
  $rows = Invoke-Remote -Program "Get-Content \`"`$env:TEMP\sweep-$Label.csv\`" -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count" -Timeout 60
  if ([int]($rows.Trim()) -ge 2) { Write-Host "[$Label] sampler has rows after $((($i + 1) * 4))s"; break }
}

# ---- 3. the level ----------------------------------------------------------------------------
$driver = Join-Path $Pkg 'test\concurrency-sweep.mjs'
$startedAt = Get-Date
& node $driver --node $Node --transport $Transport --n $N --label $Label --timeout-sec $TimeoutSec `
  --secret-file $SecretFile --out $Out
$driverExit = $LASTEXITCODE
$elapsedS = [int]((Get-Date) - $startedAt).TotalSeconds
Write-Host "[$Label] driver exit=$driverExit elapsed=${elapsedS}s"

# ---- 4. stop the sampler (it is OURS) and bring the CSV home ---------------------------------
Start-Sleep -Seconds 6
$stopProgram = @"
`$ErrorActionPreference = 'Continue'
try { Stop-Process -Id $samplerPid -Force; Write-Output "STOPPED $samplerPid" } catch { Write-Output "ALREADY GONE: `$(`$_.Exception.Message)" }
Get-Content `"`$env:TEMP\sweep-$Label.csv`" -Raw
"@
$csvText = Invoke-Remote -Program $stopProgram -Timeout 90
Set-Content -LiteralPath (Join-Path $localOut 'target.csv') -Value $csvText -Encoding utf8
$rows = (($csvText -split "`r?`n") | Where-Object { $_.Trim() -ne '' }).Count
Write-Host "[$Label] target.csv rows=$rows -> $localOut"
Get-Content -LiteralPath (Join-Path $localOut 'target.csv') | Select-Object -First 6
