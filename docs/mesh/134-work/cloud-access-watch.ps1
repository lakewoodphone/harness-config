# cloud-access-watch.ps1 — keep trying the authority until it answers, and write down every attempt.
#
# WHY THIS EXISTS (2026-10-11 06:40Z): every workstream porting jobs onto secratary-cloud lost SSH
# inside the same seven minutes — `Permission denied (publickey)` from two different source IPs and
# with two different keys, while https://api.abletelsolutions.com/health kept answering HTTP 200.
# The box is up; our key is not accepted. Recovery depends on the owner (Hetzner console) or on a
# session that still holds an open channel, and it must not depend on a human noticing that it
# came back.
#
# USAGE
#   pwsh -File cloud-access-watch.ps1                       # ~50 minutes, 90 s cadence
#   pwsh -File cloud-access-watch.ps1 -Attempts 200 -SleepSeconds 120
#
# The cadence is deliberately slow: the estate already paid for the other mistake (a fast retry
# loop against an sshd is how a per-source block is created in the first place), so this is one
# attempt every 90 s and it stops the moment one succeeds.
param(
  [int]$Attempts = 34,
  [int]$SleepSeconds = 90,
  [string]$KeyPath = "$env:USERPROFILE\.ssh\id_ed25519_hetzner",
  [string]$Host_ = "root@178.156.194.1",
  [string]$StateFile = "$PSScriptRoot\cloud-access-watch.state"
)

"# started $(Get-Date -Format o) attempts=$Attempts cadence=${SleepSeconds}s key=$KeyPath" |
  Out-File -Encoding utf8 -Append $StateFile

for ($i = 1; $i -le $Attempts; $i++) {
  $out = ssh -o BatchMode=yes -o ConnectTimeout=20 -o IdentitiesOnly=yes -i $KeyPath $Host_ "hostname" 2>&1
  $rc = $LASTEXITCODE
  "$(Get-Date -Format o) attempt=$i rc=$rc $($out -join ' ')" | Out-File -Encoding utf8 -Append $StateFile
  if ($rc -eq 0) {
    "CLOUD_ACCESS_RESTORED after $i attempt(s)" | Out-File -Encoding utf8 -Append $StateFile
    Write-Output "CLOUD_ACCESS_RESTORED after $i attempt(s)"
    exit 0
  }
  if ($i -eq $Attempts) {
    "STILL_BLOCKED after $Attempts attempt(s)" | Out-File -Encoding utf8 -Append $StateFile
    Write-Output "STILL_BLOCKED after $Attempts attempt(s)"
    exit 1
  }
  Start-Sleep -Seconds $SleepSeconds
}
