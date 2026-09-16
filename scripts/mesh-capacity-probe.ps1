<#
.SYNOPSIS
  Fetch `GET /mesh/capacity` from every gated node and validate it against the frozen schema.

.DESCRIPTION
  Stream S1's own acceptance command (docs/mesh/71-mesh-program.md §3). For each node it asks the
  gate for `GET /mesh/capacity` and checks the answer against the §2.1 schema field by field —
  names, types and nullability — then prints one line per node and exits non-zero if any node
  failed. `-Raw` prints the JSON that was actually received, which is what a person wants when a
  number looks wrong.

  FOUR THINGS IT DOES ON PURPOSE:

    * PROXY OFF. This machine has a PAC proxy, and through it a request to a tailnet name comes
      back as a 502 invented by the proxy rather than anything the node said. Every fetch here uses
      an HttpClient with `UseProxy = $false` (not `-NoProxy`, which Windows PowerShell 5.1 does not
      have, and not `Invoke-WebRequest`, which would also parse and reformat the JSON).

    * NULL IS NOT A FAILURE. `agents` and `governor` are null whenever the engine is not answering,
      `load1` is null on Windows because Windows has no load average, and `physical` is null where
      the core count could not be read. The schema allows all of those, and a node fails only for a
      value of the wrong TYPE, a MISSING field, an UNKNOWN field, or the one combination the
      interface forbids: `accepts.fleet:false` with no `reason`.

    * ONE-SHOT IS CHECKED AGAINST THE ENGINE, NOT ASSUMED. `accepts.oneShot` is always true, and
      that is the acceptance criterion for the engine-down case (§2.1): a `dsh --profile headless`
      run needs no engine. A node reporting `oneShot:false` fails here.

    * THE NUMBERS ARE CROSS-CHECKED WHERE THEY CAN BE. For the node this script runs on, free
      memory and free disk are compared against a direct OS reading taken in the same breath
      (§4.1: "the numbers match a direct measurement taken at the same moment"). Free memory moves
      between the two reads by design, so the tolerance is wide and stated in the output; the point
      is to catch a route reporting a different machine, not to police a megabyte.

.PARAMETER Node
  Short node names (`zabz-tech`) or FQDNs. Default: every node in the gated set that Tailscale
  knows about, plus this node's own loopback gate.

.PARAMETER Port
  The gate's loopback port, for the local target. Default 3086.

.PARAMETER All
  Target every tailnet peer, including nodes with no gate deployed (S2's linux-pc, the employee's
  Mac). Their failures are reported as unreachable, which is the honest answer today.

.PARAMETER Local
  Only this node, through its own loopback gate — the fast check while editing the route.

.PARAMETER Raw
  Print the raw JSON body for every node after the table.

.PARAMETER Json
  Print one JSON object for the whole run instead of a table.

.EXAMPLE
  pwsh -File scripts\mesh-capacity-probe.ps1
  pwsh -File scripts\mesh-capacity-probe.ps1 -Local -Raw
  pwsh -File scripts\mesh-capacity-probe.ps1 -Node zabz-tech,secratary -Json

.NOTES
  Exit codes: 0 every target passed, 1 at least one target failed or was unreachable, 2 usage.
#>
[CmdletBinding()]
param(
    [string[]]$Node = @(),
    [int]$Port = 3086,
    [switch]$All,
    [switch]$Local,
    [switch]$Raw,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

# The nodes this program has deployed a gate on. `secratary` is spelled without the second `e`
# everywhere in this fleet (tailscale, ssh aliases, node-identity.json), so it is spelled that way
# here too. `zabz-tech-linux` was added 2026-09-16 when stream S2 brought that node up — before
# that, a probe could pass while a third of the mesh's capacity was invisible to the broker.
$GatedNodes = @('zabz-yoga', 'zabz-tech', 'secratary', 'zabz-tech-linux')

function Get-TailscaleState {
    try {
        $raw = & tailscale status --json 2>$null
        if (-not $raw) { return $null }
        return ($raw | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Resolve-Targets {
    param([string[]]$Wanted, [switch]$Everything, [switch]$OnlyLocal, [int]$Port)
    $discovered = @()
    if (-not $OnlyLocal) {
        $state = Get-TailscaleState
        if ($state) {
            $selfFqdn = ([string]$state.Self.DNSName).TrimEnd('.')
            if ($selfFqdn) {
                # Named by the DNS label, not `Self.HostName`, for the same reason the schema field is
                # (see Test-CapacitySchema): these are the names that resolve.
                $discovered += [pscustomobject]@{ name = "$($selfFqdn.Split('.')[0]) (self)"; url = "https://$selfFqdn/mesh/capacity" }
            }
            foreach ($entry in $state.Peer.PSObject.Properties) {
                $peer = $entry.Value
                # NOT `$host`: that name is a read-only automatic variable in PowerShell, and
                # assigning it fails at script scope with "Cannot overwrite variable Host".
                $peerName = [string]$peer.HostName
                if (-not $Everything -and ($GatedNodes -notcontains $peerName.ToLower())) { continue }
                $fqdn = ([string]$peer.DNSName).TrimEnd('.')
                if (-not $fqdn) { continue }
                $discovered += [pscustomobject]@{ name = $peerName; url = "https://$fqdn/mesh/capacity" }
            }
        }
        if ($Wanted.Count -gt 0) {
            $matched = @()
            foreach ($candidate in $discovered) {
                foreach ($name in $Wanted) {
                    if ($candidate.name -like "*$name*" -or $candidate.url -like "*$name*") { $matched += $candidate; break }
                }
            }
            if ($matched.Count -eq 0) {
                # Tailscale gave us nothing usable (or the name was not a peer): ask the name the
                # caller wrote, as a tailnet host, and let the fetch fail loudly if it is wrong.
                foreach ($name in $Wanted) {
                    $targetHost = $name
                    if ($targetHost -notmatch '\.') { $targetHost = "$targetHost.tail93e6e6.ts.net" }
                    $matched += [pscustomobject]@{ name = $name; url = "https://$targetHost/mesh/capacity" }
                }
            }
            $discovered = $matched
        }
    }
    $targets = @()
    $localListening = $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
                                 Select-Object -First 1)
    if ($OnlyLocal -or $localListening) {
        $targets += [pscustomobject]@{ name = 'loopback'; url = "http://127.0.0.1:$Port/mesh/capacity" }
    }
    $targets += $discovered
    return $targets
}

function Invoke-NoProxy {
    # A GET with no proxy and no redirection, returning status, body and how long it took.
    param([string]$Url, [int]$TimeoutSec = 10)
    # Windows PowerShell 5.1 does not load System.Net.Http on its own; pwsh 7 does. Without this
    # the whole probe dies on this node's own default shell with "cannot find type".
    if (-not ('System.Net.Http.HttpClient' -as [type])) {
        Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue | Out-Null
    }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $watch.Stop()
        return [pscustomobject]@{
            status = [int]$response.StatusCode
            body   = $body
            ms     = [int]$watch.ElapsedMilliseconds
            error  = $null
        }
    } catch {
        $watch.Stop()
        return [pscustomobject]@{
            status = 0
            body   = ''
            ms     = [int]$watch.ElapsedMilliseconds
            error  = $_.Exception.Message
        }
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Test-NumberType {
    # Windows PowerShell 5.1's ConvertFrom-Json hands back [decimal] for `0.0` and [int] or
    # [double] elsewhere; pwsh 7 gives [long] and [double]. All of them are JSON numbers, and a
    # checker that only knew one shell's habits would fail a correct node on the other.
    param($Value)
    return ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or
            $Value -is [decimal] -or $Value -is [single])
}

function Add-NumberProblem {
    # One place for the numeric rules, so every field is checked the same way.
    param($Value, [string]$Path, [switch]$AllowNull, [switch]$Positive, [ref]$Problems)
    if ($null -eq $Value) {
        if (-not $AllowNull) { $Problems.Value += "$Path is null but must be a number" }
        return
    }
    if (-not (Test-NumberType $Value)) {
        $Problems.Value += "$Path is $($Value.GetType().Name), not a number"
        return
    }
    if ($Positive -and $Value -le 0) { $Problems.Value += "$Path is $Value, must be > 0" }
    if (-not $Positive -and $Value -lt 0) { $Problems.Value += "$Path is $Value, must be >= 0" }
}

function Test-CapacitySchema {
    # The §2.1 schema, as a checker: field by field, because the point of a frozen interface is that
    # drift is caught by a machine, not by someone reading two documents side by side.
    param($Document)
    $problems = @()
    if ($null -eq $Document -or -not ($Document -is [System.Management.Automation.PSCustomObject])) {
        return @('the body is not a JSON object')
    }
    $top = @('schema', 'node', 'fqdn', 'at', 'cpu', 'mem', 'disk', 'agents', 'governor', 'accepts')
    foreach ($key in $top) {
        if (-not $Document.PSObject.Properties.Name.Contains($key)) { $problems += "missing field $key" }
    }
    foreach ($key in $Document.PSObject.Properties.Name) {
        if ($top -notcontains $key) { $problems += "unknown field $key (the schema is frozen)" }
    }
    if ($Document.schema -ne 1) { $problems += "schema is $($Document.schema), expected 1" }
    if (-not ($Document.node -is [string]) -or -not $Document.node) { $problems += 'node is not a non-empty string' }
    if ($null -ne $Document.fqdn -and -not ($Document.fqdn -is [string])) { $problems += 'fqdn is neither a string nor null' }
    # `node` is the Tailscale DNS LABEL — the name MagicDNS resolves, and therefore the only name a
    # broker or mesh-health.ps1 can act on. Settled 2026-09-16 after measuring this laptop: its
    # Self.HostName is `zabz-yoga` but the only name that resolves is `zabz-yoga-1`, so a `node`
    # taken from HostName is a node nothing can be placed on. This invariant makes it checkable.
    if ($Document.node -is [string] -and $Document.node -and $Document.fqdn -is [string] -and $Document.fqdn) {
        $label = $Document.fqdn.Split('.')[0]
        if ($Document.node -ne $label) {
            $problems += "node '$($Document.node)' is not the Tailscale DNS label of fqdn '$($Document.fqdn)' (expected '$label')"
        }
    }
    if ($Document.at -is [datetime]) {
        # Windows PowerShell 5.1 hands back the string; PowerShell 7.5 converts an ISO-8601
        # timestamp into a [datetime] on its own. Both are the same document, so both are accepted
        # here — and the WIRE format is checked separately, on the raw body, where no conversion has
        # happened (`$atText` is only about the value's shape).
        $atText = ([datetime]$Document.at).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    } elseif ($Document.at -is [string]) {
        $atText = $Document.at
    } else {
        $atText = $null
        $problems += 'at is neither a string nor a timestamp'
    }
    if ($atText -and $atText -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$') {
        $problems += "at is '$atText', expected UTC ISO-8601 to the second, e.g. 2026-09-16T23:20:00Z"
    }

    if ($Document.cpu -isnot [System.Management.Automation.PSCustomObject]) {
        $problems += 'cpu is not an object'
    } else {
        foreach ($key in @('logical', 'physical', 'load1')) {
            if (-not $Document.cpu.PSObject.Properties.Name.Contains($key)) { $problems += "missing field cpu.$key" }
        }
        Add-NumberProblem -Value $Document.cpu.logical -Path 'cpu.logical' -AllowNull -Positive -Problems ([ref]$problems)
        Add-NumberProblem -Value $Document.cpu.physical -Path 'cpu.physical' -AllowNull -Positive -Problems ([ref]$problems)
        if ($null -ne $Document.cpu.load1) {
            if (-not (Test-NumberType $Document.cpu.load1)) {
                $problems += "cpu.load1 is $($Document.cpu.load1.GetType().Name), not a number"
            } elseif ($Document.cpu.load1 -lt 0) {
                $problems += "cpu.load1 is $($Document.cpu.load1), must be >= 0"
            }
        }
    }

    if ($Document.mem -isnot [System.Management.Automation.PSCustomObject]) {
        $problems += 'mem is not an object'
    } else {
        foreach ($key in @('totalMiB', 'freeMiB', 'swapUsedPct')) {
            if (-not $Document.mem.PSObject.Properties.Name.Contains($key)) { $problems += "missing field mem.$key" }
        }
        Add-NumberProblem -Value $Document.mem.totalMiB -Path 'mem.totalMiB' -AllowNull -Positive -Problems ([ref]$problems)
        Add-NumberProblem -Value $Document.mem.freeMiB -Path 'mem.freeMiB' -AllowNull -Problems ([ref]$problems)
        if ($null -ne $Document.mem.swapUsedPct) {
            if (-not (Test-NumberType $Document.mem.swapUsedPct)) {
                $problems += 'mem.swapUsedPct is not a number'
            } elseif ($Document.mem.swapUsedPct -lt 0 -or $Document.mem.swapUsedPct -gt 100) {
                $problems += "mem.swapUsedPct is $($Document.mem.swapUsedPct), expected 0..100"
            }
        }
    }

    if ($Document.disk -isnot [System.Management.Automation.PSCustomObject]) {
        $problems += 'disk is not an object'
    } else {
        foreach ($key in @('workRoot', 'freeGiB')) {
            if (-not $Document.disk.PSObject.Properties.Name.Contains($key)) { $problems += "missing field disk.$key" }
        }
        if (-not ($Document.disk.workRoot -is [string]) -or -not $Document.disk.workRoot) {
            $problems += 'disk.workRoot is not a non-empty string'
        }
        Add-NumberProblem -Value $Document.disk.freeGiB -Path 'disk.freeGiB' -AllowNull -Problems ([ref]$problems)
    }

    foreach ($section in @(
        @{ name = 'agents';   keys = @('loopsRunning', 'sessionsLive') },
        @{ name = 'governor'; keys = @('budgetSlots', 'inUse', 'queued') })) {
        $value = $Document.($section.name)
        if ($null -eq $value) { continue }
        if ($value -isnot [System.Management.Automation.PSCustomObject]) {
            $problems += "$($section.name) is neither null nor an object"
            continue
        }
        foreach ($key in $section.keys) {
            if (-not $value.PSObject.Properties.Name.Contains($key)) { $problems += "missing field $($section.name).$key" }
            else { Add-NumberProblem -Value $value.$key -Path "$($section.name).$key" -Problems ([ref]$problems) }
        }
    }

    if ($Document.accepts -isnot [System.Management.Automation.PSCustomObject]) {
        $problems += 'accepts is not an object'
    } else {
        foreach ($key in @('oneShot', 'fleet', 'maxChildren', 'reason')) {
            if (-not $Document.accepts.PSObject.Properties.Name.Contains($key)) { $problems += "missing field accepts.$key" }
        }
        if ($Document.accepts.oneShot -isnot [bool]) { $problems += 'accepts.oneShot is not a boolean' }
        if ($Document.accepts.fleet -isnot [bool]) { $problems += 'accepts.fleet is not a boolean' }
        Add-NumberProblem -Value $Document.accepts.maxChildren -Path 'accepts.maxChildren' -Problems ([ref]$problems)
        if ($null -ne $Document.accepts.reason -and -not ($Document.accepts.reason -is [string])) {
            $problems += 'accepts.reason is neither a string nor null'
        }
        # §2.1: "`reason` carries the one-line explanation when `accepts` is restricted" — so a
        # refusal with no explanation is a failure. A reason on an ACCEPTING node is allowed and
        # is a NOTE, not a restriction: it names a number in this object that is derived rather
        # than measured (a node with no governor lease directory reports its computed slot budget
        # with `inUse: 0`, and says so). Measured 2026-09-16: the earlier build refused those
        # nodes instead, and the broker excluded both Linux machines from fleet placement.
        if ($Document.accepts.fleet -eq $false -and -not $Document.accepts.reason) {
            $problems += 'accepts.fleet is false and accepts.reason is empty: a restriction nobody can read'
        }
        if ($Document.accepts.reason -is [string] -and $Document.accepts.reason.Length -eq 0) {
            $problems += 'accepts.reason is an empty string: either name the condition or send null'
        }
        # The engine-down acceptance criterion: one-shot work is accepted on a node whose engine is
        # not answering, because `dsh --profile headless` needs no engine there (§0, §2.1).
        if ($Document.accepts.oneShot -ne $true) {
            $problems += 'accepts.oneShot is false: a headless run needs no engine on this node'
        }
    }
    return $problems
}

function Test-LocalCrossCheck {
    # Compare this node's own reported numbers with a direct OS read of the same machine.
    param($Document)
    $notes = @()
    $ok = $true
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $directFreeMiB = [int]($os.FreePhysicalMemory / 1KB)
        if ($null -ne $Document.mem.freeMiB) {
            $delta = [Math]::Abs([int]$Document.mem.freeMiB - $directFreeMiB)
            if ($delta -gt 1536) {
                $ok = $false
                $notes += "mem.freeMiB=$($Document.mem.freeMiB) vs direct $directFreeMiB MiB (delta $delta > 1536)"
            } else {
                $notes += "mem.freeMiB within $delta MiB of a direct read ($directFreeMiB MiB)"
            }
        }
    } catch {
        $notes += "free-memory cross-check unavailable: $($_.Exception.Message)"
    }
    try {
        $drive = (Split-Path -Qualifier $Document.disk.workRoot).TrimEnd(':')
        $directFreeGiB = [Math]::Round((Get-PSDrive -Name $drive).Free / 1GB, 1)
        if ($null -ne $Document.disk.freeGiB) {
            $delta = [Math]::Abs([double]$Document.disk.freeGiB - $directFreeGiB)
            if ($delta -gt 1) {
                $ok = $false
                $notes += "disk.freeGiB=$($Document.disk.freeGiB) vs direct $directFreeGiB GiB (delta $delta > 1)"
            } else {
                $notes += "disk.freeGiB within $delta GiB of a direct read ($directFreeGiB GiB)"
            }
        }
    } catch {
        $notes += "disk cross-check unavailable: $($_.Exception.Message)"
    }
    return [pscustomobject]@{ ok = $ok; notes = $notes }
}

# ---------------------------------------------------------------- run
$targets = @(Resolve-Targets -Wanted $Node -Everything:$All -OnlyLocal:$Local -Port $Port)
if ($targets.Count -eq 0) {
    Write-Error 'no targets: tailscale knows no peer, and -Node was empty'
    exit 2
}

$results = @()
foreach ($target in $targets) {
    $fetch = Invoke-NoProxy -Url $target.url -TimeoutSec 10
    $problems = @()
    $payload = $null
    $cross = $null
    if ($fetch.error) {
        $problems += "unreachable: $($fetch.error)"
    } elseif ($fetch.status -ne 200) {
        $problems += "HTTP $($fetch.status), expected 200"
    } else {
        try {
            $payload = $fetch.body | ConvertFrom-Json
            $problems += @(Test-CapacitySchema -Document $payload)
            # Checked on the RAW BODY, where no parser has touched it: the timestamp must be the
            # literal UTC form §2.1 froze, not a value that merely round-trips to one.
            if ($fetch.body -notmatch '"at"\s*:\s*"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"') {
                $problems += 'the raw body carries no "at":"<UTC ISO-8601 to the second>Z"'
            }
            if ($target.name -eq 'loopback') {
                $cross = Test-LocalCrossCheck -Document $payload
                if (-not $cross.ok) { foreach ($note in $cross.notes) { $problems += "cross-check: $note" } }
            }
        } catch {
            $problems += "the body is not valid JSON: $($_.Exception.Message)"
        }
    }
    $results += [pscustomobject]@{
        name     = $target.name
        url      = $target.url
        ok       = ($problems.Count -eq 0)
        status   = $fetch.status
        ms       = $fetch.ms
        problems = $problems
        cross    = $cross
        payload  = $payload
    }
}

$failed = @($results | Where-Object { -not $_.ok })

if ($Json) {
    $report = [pscustomobject]@{
        at      = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        host    = $env:COMPUTERNAME
        targets = @($results | ForEach-Object {
            [pscustomobject]@{
                name     = $_.name
                url      = $_.url
                ok       = $_.ok
                status   = $_.status
                ms       = $_.ms
                problems = @($_.problems)
                payload  = $_.payload
            }
        })
        failed  = $failed.Count
    }
    $report | ConvertTo-Json -Depth 8
} else {
    "{0}  host={1}  targets={2}  failed={3}" -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'),
        $env:COMPUTERNAME, $results.Count, $failed.Count
    foreach ($result in $results) {
        $doc = $result.payload
        $agents = '-'
        if ($doc) { $agents = if ($doc.agents) { "loops=$($doc.agents.loopsRunning)" } else { 'agents=null' } }
        $budget = '-'
        if ($doc) { $budget = if ($doc.governor) { "slots=$($doc.governor.budgetSlots)" } else { 'gov=null' } }
        $free = '-'
        if ($doc -and $doc.governor) { $free = "free=$($doc.governor.budgetSlots - $doc.governor.inUse)" }
        "{0,-22} {1,-40} schema={2,-3} {3,-14} {4,-13} {5,-10} {6,6}ms  {7}" -f `
            $result.name,
            $(if ($doc) { $doc.fqdn } else { $result.url }),
            $(if ($doc) { $doc.schema } else { '-' }),
            $agents, $budget, $free, $result.ms,
            $(if ($result.ok) { 'PASS' } else { 'FAIL' })
        foreach ($problem in $result.problems) { "    ! $problem" }
        if ($result.cross -and $result.cross.ok) { foreach ($note in $result.cross.notes) { "    . $note" } }
    }
    if ($Raw) {
        foreach ($result in $results) {
            ""
            "--- {0} ({1})" -f $result.name, $result.url
            if ($result.payload) { $result.payload | ConvertTo-Json -Depth 6 } else { '(no JSON body)' }
        }
    }
}

if ($failed.Count -gt 0) { exit 1 }
exit 0
