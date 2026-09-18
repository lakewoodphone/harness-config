<#
.SYNOPSIS
    Run ONE dsh headless task on the always-on desktop and write its output to a file.

.DESCRIPTION
    This is the only thing that runs on the Windows side of a wake release. secratary
    copies a prompt FILE over and ssh's a single line that invokes this script; this
    script starts `dsh --profile headless <task>`, streams the run to -OutFile, and
    exits with the task's own exit code.

    THE POINT OF THIS FILE IS QUOTING. The v0 runner built the command line with
    `cmd /c "npx dsh --profile headless `"$prompt`""`, which meant:
      * every double quote in the prompt was DELETED (data loss, silently), and
      * the prompt was re-parsed by cmd.exe, so newlines and quotes were live syntax.
    Here the prompt is never placed in a shell command line at all:

      1. the prompt is read from the file as one string, byte-for-byte (no Trim,
         no quote stripping);
      2. node.exe is started directly (no cmd.exe, no .cmd shim) with an argument
         list, so the task travels as ONE argv element;
      3. each argument is escaped with the MSVCRT rule set (the same rule set
         node's own argv parser uses), so an embedded quote, backslash or newline
         is data, not syntax.

    The dsh CLI is resolved at runtime rather than hardcoded (a version-pinned
    _npx path is a time bomb): $env:WAKE_DSH_BIN, else the newest
    `_npx\*\node_modules\@deepseek-ai\dsh\lib\bin.js` in the npm cache, else the
    npx CLI entry - and every one of those is still launched through node.exe.

.PARAMETER PromptFile
    File holding the task text. Written by the dispatcher from the wake row.

.PARAMETER OutFile
    File to write the run to (created/overwritten, UTF-8 without BOM).

.PARAMETER TimeoutSec
    Hard bound on the session. On expiry the process tree is killed and the exit
    code is reported as 124. The dispatcher passes a value one minute inside its
    own ssh timeout, so a killed ssh cannot leave a session running forever.

.PARAMETER Profile
    dsh profile to boot. Default `headless` ("answer one task, print the result, exit").

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\ezabz\bin\wake-run.ps1 `
        -PromptFile C:\Users\ezabz\bin\wake-prompt.txt `
        -OutFile    C:\Users\ezabz\bin\wake-out.txt -TimeoutSec 840

.NOTES
    Stream W2. Contract: harness-config/scripts/wake/CONTRACT.md.
    v0 (`wake-run.ps1`) is replaced by this file; the trailing
    `=== exit code: N ===` line is kept so an older dispatcher still parses.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PromptFile,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [int]$TimeoutSec = 840,
    [Alias('DshProfile')][string]$Profile = 'headless',
    [string]$DshBin = $env:WAKE_DSH_BIN,
    # Resolution check only: report which node/dsh this would launch and exit 0
    # without starting anything. Lets the hop be audited without a live session.
    [switch]$ResolveOnly
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
if ($TimeoutSec -le 0) { $TimeoutSec = 840 }

$UTF8 = New-Object System.Text.UTF8Encoding($false)   # no BOM: a BOM broke the v0 log line

function OutDir([string]$p) {
    $d = Split-Path -Parent $p
    if ($d -and -not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

function Write-Out([string]$text) { [System.IO.File]::AppendAllText($OutFile, $text + "`r`n", $UTF8) }

# ---------------------------------------------------------------------------
# Windows argv escaping (MSVCRT rule set): a run of backslashes before a quote is
# doubled, quotes are escaped, and the whole element is quoted when it holds a
# space, tab or quote. This is what node's argv parser expects.
# ---------------------------------------------------------------------------
function ConvertTo-CommandLineArg([string]$a) {
    if ($null -eq $a) { $a = '' }
    if ($a.Length -gt 0 -and $a -notmatch '[\s"]') { return $a }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $backslashes = 0
    foreach ($ch in $a.ToCharArray()) {
        if ($ch -eq '\') { $backslashes++; continue }
        if ($ch -eq '"') {
            [void]$sb.Append('\' * ($backslashes * 2 + 1))
            [void]$sb.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) { [void]$sb.Append('\' * $backslashes); $backslashes = 0 }
        [void]$sb.Append($ch)
    }
    if ($backslashes -gt 0) { [void]$sb.Append('\' * ($backslashes * 2)) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Resolve-NodeExe {
    $candidates = @()
    if ($env:WAKE_NODE) { $candidates += $env:WAKE_NODE }
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles 'nodejs\node.exe') }
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe') }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe') }
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    return $null
}

function Get-NpxCacheRoots {
    $roots = @()
    if ($env:WAKE_NPX_CACHE) { $roots += $env:WAKE_NPX_CACHE }
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA 'npm-cache\_npx') }
    if ($env:APPDATA) { $roots += (Join-Path $env:APPDATA 'npm-cache\_npx') }
    return ($roots | Where-Object { Test-Path -LiteralPath $_ })
}

# Resolve dsh at runtime. Returns the process to start, the argument list BEFORE
# the task, and the working directory (the npx checkout the proven hop used).
function Resolve-DshLaunch {
    $node = Resolve-NodeExe
    if (-not $node) { return $null }

    if ($DshBin) {
        if (-not (Test-Path -LiteralPath $DshBin)) { return @{ Error = "WAKE_DSH_BIN/-DshBin does not exist: $DshBin" } }
        return @{ Node = $node; Args = @($DshBin, '--profile', $Profile); Cwd = (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $DshBin))); Via = 'WAKE_DSH_BIN' }
    }

    foreach ($root in Get-NpxCacheRoots) {
        # Newest checkout wins: the _npx hash directory is what the proven hop cd'd
        # into, and dsh resolves its profile plugins from the cwd's node_modules.
        $hits = @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object {
                $b = Join-Path $_.FullName 'node_modules\@deepseek-ai\dsh\lib\bin.js'
                if (Test-Path -LiteralPath $b) { [pscustomobject]@{ Dir = $_.FullName; Bin = $b } }
            })
        if ($hits.Count -gt 0) {
            $hit = $hits[0]
            return @{ Node = $node; Args = @($hit.Bin, '--profile', $Profile); Cwd = $hit.Dir; Via = "npx cache $($hit.Bin)" }
        }
    }

    # Last resort: the npx CLI itself, still launched through node.exe so the task
    # is never re-parsed by cmd.exe.
    $npxCli = Join-Path (Split-Path -Parent $node) 'node_modules\npm\bin\npx-cli.js'
    if (Test-Path -LiteralPath $npxCli) {
        $cwd = $null
        foreach ($root in Get-NpxCacheRoots) {
            $candidate = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'node_modules\.bin\dsh.cmd') } |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($candidate) { $cwd = $candidate.FullName; break }
        }
        return @{ Node = $node; Args = @($npxCli, 'dsh', '--profile', $Profile); Cwd = $cwd; Via = 'npx-cli.js fallback' }
    }

    return @{ Error = 'no node.exe and no dsh entry point found; set WAKE_DSH_BIN or install node' }
}

# Kill the whole tree: dsh can leave child processes behind, and a leaked session
# on the always-on desktop is exactly the runaway this system must not have.
# Returns a line describing what happened, because "we killed it" is a claim that
# needs evidence.
function Stop-ProcessTree([int]$Id) {
    $detail = ''
    try {
        $p = Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', "$Id", '/T', '/F') `
            -NoNewWindow -Wait -PassThru -ErrorAction Stop
        $detail = "taskkill /PID $Id /T /F -> exit $($p.ExitCode)"
    } catch {
        $detail = "taskkill failed: $($_.Exception.Message)"
        try { Stop-Process -Id $Id -Force -ErrorAction Stop; $detail += '; Stop-Process -Force ok' }
        catch { $detail += "; Stop-Process failed: $($_.Exception.Message)" }
    }
    if (Get-Process -Id $Id -ErrorAction SilentlyContinue) { $detail += '; STILL RUNNING' } else { $detail += '; gone' }
    return $detail
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
OutDir $OutFile
$started = Get-Date
$promptBytes = 0
$prompt = ''
$readError = $null
try {
    $prompt = [System.IO.File]::ReadAllText($PromptFile, [System.Text.Encoding]::UTF8)
    $promptBytes = [System.Text.Encoding]::UTF8.GetByteCount($prompt)
} catch {
    $readError = $_.Exception.Message
}

[System.IO.File]::WriteAllText($OutFile,
    "=== wake-run (W2) started $($started.ToString('o')) ===`r`n" +
    "host: $env:COMPUTERNAME   powershell: $($PSVersionTable.PSVersion)   profile: $Profile`r`n" +
    "prompt file: $PromptFile`r`n", $UTF8)

if ($readError) {
    Write-Out "error: cannot read the prompt file: $readError"
    Write-Out "=== exit code: 2 ==="
    Write-Out "WAKE_EXIT_CODE=2"
    Write-Out "WAKE_COST_USD=none"
    exit 2
}

Write-Out "prompt bytes: $promptBytes"

if ($promptBytes -eq 0 -or $prompt.Trim().Length -eq 0) {
    Write-Out "error: the prompt is empty; dsh rejects a blank task, so nothing was started"
    Write-Out "=== exit code: 2 ==="
    Write-Out "WAKE_EXIT_CODE=2"
    Write-Out "WAKE_COST_USD=none"
    exit 2
}

$launch = Resolve-DshLaunch
if (-not $launch -or $launch.Error) {
    Write-Out "error: $($launch.Error)"
    Write-Out "the prompt is a file precisely so no shell command line is built from it; nothing was started"
    Write-Out "=== exit code: 127 ==="
    Write-Out "WAKE_EXIT_CODE=127"
    Write-Out "WAKE_COST_USD=none"
    exit 127
}

# ---------------------------------------------------------------------------
# Run it. stdout and stderr go to separate temp files (never to pipes, so there is
# no chance of a full-pipe deadlock), then both are folded into -OutFile.
# ---------------------------------------------------------------------------
if ($ResolveOnly) {
    Write-Out "node: $($launch.Node)"
    Write-Out "cwd:  $($launch.Cwd)"
    Write-Out "dsh:  $($launch.Via)"
    Write-Out "argv prefix: $($launch.Args -join ' ')"
    Write-Out "=== exit code: 0 ==="
    Write-Out "WAKE_EXIT_CODE=0"
    Write-Out "WAKE_COST_USD=none"
    exit 0
}

$argv = @($launch.Args) + @($prompt)
$argLine = ($argv | ForEach-Object { ConvertTo-CommandLineArg $_ }) -join ' '

Write-Out "launch: $($launch.Node)"
Write-Out "  cwd: $($launch.Cwd)"
Write-Out "  dsh: $($launch.Via)"
Write-Out "  args: $($launch.Args -join ' ') <task: $promptBytes bytes, passed as one argv element>"
Write-Out "  timeout: ${TimeoutSec}s"
Write-Out "=== output ==="

$proc = $null
$timedOut = $false
$killDetail = ''
$launchError = $null
$stdout = ''
$stderr = ''
try {
    # System.Diagnostics.Process, not Start-Process: under Windows PowerShell 5.1
    # the object Start-Process hands back reports an EMPTY ExitCode even after
    # WaitForExit(), so the runner could not tell a failed session from a
    # successful one. A Process we construct ourselves reports it correctly on
    # both 5.1 and 7.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $launch.Node
    $psi.Arguments = $argLine
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $psi.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    if ($launch.Cwd -and (Test-Path -LiteralPath $launch.Cwd)) { $psi.WorkingDirectory = $launch.Cwd }

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $null = $proc.Start()
    # Drain both pipes concurrently: reading them one after the other deadlocks
    # as soon as one buffer fills, and dsh's reasoning stream is big.
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()

    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        $timedOut = $true
        $killDetail = Stop-ProcessTree -Id $proc.Id
        $null = $proc.WaitForExit(30000)
    }
    $proc.WaitForExit()
    try { $stdout = $outTask.Result } catch { $stdout = '' }
    try { $stderr = $errTask.Result } catch { $stderr = '' }
} catch {
    $launchError = $_.Exception.Message
}

$code = $null
$codeUnreadable = $false
if ($launchError) {
    $code = 127
} elseif ($timedOut) {
    $code = 124
} elseif ($proc) {
    # An empty `exit $code` reports 0, which would turn a FAILED session into a
    # recorded success, so a value that cannot be read is 1, never 0.
    try { $code = $proc.ExitCode } catch { $code = $null }
}
if ($null -eq $code -or "$code" -eq '') {
    $code = 1
    $codeUnreadable = $true
}

if ($launchError) {
    Write-Out "launch failed: $launchError"
    Write-Out "  command was: $($launch.Node) $($launch.Args -join ' ') <task>"
}
if ($timedOut) { Write-Out "TIMEOUT: killed after ${TimeoutSec}s (exit reported as 124); $killDetail" }

Write-Out "--- stdout (final answer) ---"
if ($stdout.Trim().Length -gt 0) { Write-Out $stdout.TrimEnd() }
Write-Out "--- stderr (provider reasoning) ---"
if ($stderr.Trim().Length -gt 0) { Write-Out $stderr.TrimEnd() }

# ---------------------------------------------------------------------------
# Cost. dsh --profile headless prints the final answer on stdout and provider
# reasoning on stderr and NOTHING else - it exposes no cost figure (checked in
# @deepseek-ai/dsh-headless: the runner folds turn/end into text + exit code).
# So: report a number only when one is actually available (the harness's own
# output, or an explicit WAKE_COST_USD the caller already knows) and otherwise
# say `none` rather than inventing a figure.
# ---------------------------------------------------------------------------
$cost = $null
$costSource = $null
if ($env:WAKE_COST_USD -and $env:WAKE_COST_USD -match '^[0-9]+(\.[0-9]+)?$') {
    $cost = $env:WAKE_COST_USD
    $costSource = 'WAKE_COST_USD (supplied by the caller)'
} else {
    foreach ($text in @($stdout, $stderr)) {
        if ($costSource) { break }
        if (-not $text) { continue }
        $m = [regex]::Match($text, '(?im)^\s*(?:WAKE_COST_USD|cost_usd|total_cost)\s*[:=]\s*\$?([0-9]+(?:\.[0-9]+)?)\s*$')
        if ($m.Success) { $cost = $m.Groups[1].Value; $costSource = 'reported in the harness output' }
    }
}

$elapsed = [int]((Get-Date) - $started).TotalSeconds
if ($codeUnreadable) {
    Write-Out "error: the exit code of the session could not be read; reported as 1 (never as success)"
}
Write-Out "=== exit code: $code ==="
Write-Out "WAKE_EXIT_CODE=$code"
if ($cost) {
    Write-Out "WAKE_COST_USD=$cost"
    Write-Out "cost: `$$cost ($costSource)"
} else {
    Write-Out "WAKE_COST_USD=none"
    Write-Out "cost: not reported by this harness surface (dsh --profile headless prints the final answer and provider reasoning only)"
}
Write-Out "elapsed: ${elapsed}s"

exit $code
