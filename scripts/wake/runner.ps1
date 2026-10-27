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
    _npx path is a time bomb): $env:WAKE_DSH_BIN, else the INSTALLED ENGINE at
    `$DSH_ENGINE` / `$HOME\.dsh\engine`, else the newest
    `_npx\*\node_modules\@deepseek-ai\dsh\lib\bin.js` in the npm cache, else the
    npx CLI entry (asking for the `@deepseek-ai/dsh` package, never the bare name
    `dsh`) - and every one of those is still launched through node.exe.
    2026-10-27: the engine step was added after BOTH _npx roots came up absent on
    ZABZ-TECH and every release for hours died on "npm error could not determine
    executable to run" while the dispatcher reported only `failed`.

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
    # THE CHEAP LANE, SCALED WITH THE BALANCE (2026-10-14). The dispatcher passes the lane the
    # budget control resolved (`wake-dispatch.sh`, from ~/.sms-inbox/wake-budget.json); empty
    # means "do not pin", which is the healthy case. This is applied to $env:WAKE_AGENT_MODEL
    # BEFORE wake-model.ps1 runs, because that variable is the resolver's own authoritative
    # candidate chain (wake-model.ps1:143) - so no code change to the resolver was needed to make
    # a low balance select a cheaper model, only a value to give it.
    [string]$Model = '',
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

    # THE INSTALLED ENGINE, before the npx cache (2026-10-27). The _npx cache is not a
    # fixture: `npm cache clean`, a node upgrade, or nothing at all empties it. MEASURED on
    # ZABZ-TECH 2026-10-27T23:4x Z: BOTH _npx roots were ABSENT, so this function fell
    # through to the npx-cli.js last resort, which asks npm for the package `dsh` - a
    # DIFFERENT package that is not an executable - and npm exited 1 with "could not
    # determine executable to run". Every release in that window died in 3-24 s with an
    # empty answer: the dispatcher logged `failed`, the ledger advanced by nothing, and the
    # only symptom was a green-looking autonomy-status that said the dispatcher was alive.
    # The engine DSH installs at $HOME\.dsh\engine IS the durable checkout and it resolves
    # its own node_modules from that directory, so prefer it over any cache.
    $engineRoots = @()
    if ($env:DSH_ENGINE) { $engineRoots += $env:DSH_ENGINE }
    if ($env:DSH_HOME) { $engineRoots += (Join-Path $env:DSH_HOME 'engine') }
    if ($env:USERPROFILE) { $engineRoots += (Join-Path $env:USERPROFILE '.dsh\engine') }
    if ($env:HOME) { $engineRoots += (Join-Path $env:HOME '.dsh\engine') }
    if ($env:LOCALAPPDATA) { $engineRoots += (Join-Path $env:LOCALAPPDATA 'dsh\engine') }
    foreach ($root in ($engineRoots | Where-Object { $_ -and (Test-Path -LiteralPath $_) })) {
        $bin = Join-Path $root 'node_modules\@deepseek-ai\dsh\lib\bin.js'
        if (Test-Path -LiteralPath $bin) {
            return @{ Node = $node; Args = @($bin, '--profile', $Profile); Cwd = $root; Via = "installed engine $bin" }
        }
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
        # `npx dsh` is NOT the command this estate needs: npm's package `dsh` is a different
        # project (or nothing at all), so npx exits 1 with "could not determine executable to
        # run" and the hop looks like a session that failed instead of a runner that never
        # started one. `--package @deepseek-ai/dsh dsh` asks for the bin from OUR package, and
        # `--yes` means a headless hop can never stop on an install prompt.
        return @{ Node = $node; Args = @($npxCli, '--yes', '--package', '@deepseek-ai/dsh', 'dsh', '--profile', $Profile); Cwd = $cwd; Via = 'npx-cli.js fallback (@deepseek-ai/dsh)' }
    }

    return @{ Error = 'no node.exe and no dsh entry point found; set WAKE_DSH_BIN or DSH_ENGINE, or install the DSH engine at $HOME\.dsh\engine' }
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
# MODEL RESOLUTION (audit D8 / journal D177, L1606). The seat's model is never a
# literal in this path: bin/wake-model.ps1 reads a LIVE catalog, validates the
# candidate, and writes a --patch overlay that is passed to dsh here. Fail soft
# and SAY SO - an unresolved model must be visible in the run record, never silent.
# ---------------------------------------------------------------------------
$modelInfo = $null
# The lane the balance control asked for, if any. Set BEFORE the resolver runs so the resolver
# treats it as its authoritative env candidate chain (wake-model.ps1:143). Recorded in the out-file
# so a run's model provenance says WHY that lane was used, not only which one it was.
if ($Model) {
    $env:WAKE_AGENT_MODEL = $Model
    Write-Out "model lane: PINNED by the balance control -> $Model (WAKE_AGENT_MODEL)"
}
try {
    $resolver = Join-Path (Split-Path -Parent $PSCommandPath) 'wake-model.ps1'
    if (Test-Path -LiteralPath $resolver) {
        $psExe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
        if (-not $psExe) { $psExe = (Get-Command powershell -ErrorAction SilentlyContinue).Source }
        if ($psExe) {
            $json = & $psExe -NoProfile -ExecutionPolicy Bypass -File $resolver 2>$null | Select-Object -Last 1
            if ($json) { $modelInfo = $json | ConvertFrom-Json }
        }
    }
} catch { $modelInfo = $null }

$modelReady = $false
$modelProblem = $null
if ($modelInfo -and $modelInfo.model) {
    # DSH_HOME is NOT set in the ssh/spawned wake environment (MEASURED 2026-09-30):
    # `Join-Path $env:DSH_HOME ...` returned a relative path, the patch was never
    # passed, and the literal seat model silently served every wake. Resolve the
    # same conventional home wake-model.ps1 does.
    $dshHome = $env:DSH_HOME
    if (-not $dshHome -and $env:USERPROFILE) { $dshHome = Join-Path $env:USERPROFILE '.dsh' }
    if (-not $dshHome -and $env:HOME) { $dshHome = Join-Path $env:HOME '.dsh' }
    $modelPatch = if ($dshHome) { Join-Path $dshHome 'runtime-model.patch.yml' } else { $null }
    if ($modelInfo.unvalidated) {
        $modelProblem = "resolver could not validate '$($modelInfo.model)' against a live catalog (catalog=$($modelInfo.catalog))"
    } elseif (-not ($modelPatch -and (Test-Path -LiteralPath $modelPatch))) {
        $modelProblem = "patch overlay not found at $modelPatch - the profile default would silently apply"
    } else {
        $launch.Args = @($launch.Args) + @('--patch', $modelPatch)
        $modelReady = $true
        Write-Out "model: $($modelInfo.model)  provider: $($modelInfo.provider)  validated: $(-not $modelInfo.unvalidated)  catalog: $($modelInfo.catalog)"
        if (@($modelInfo.dropped).Count -gt 0) {
            Write-Out "model candidates dropped (absent from the live catalog): $((@($modelInfo.dropped) -join ', '))"
        }
    }
} elseif ($modelInfo) {
    $modelProblem = "resolver returned no model (catalog=$($modelInfo.catalog) errors=$((@($modelInfo.errors) -join '; ')))"
} else {
    $modelProblem = 'wake-model.ps1 produced no parseable JSON'
}

# FAIL LOUD (item 181). Item 152 exists because a literal seat model silently served
# every wake whenever resolution failed. The default is now to REFUSE to boot on an
# unvalidated model instead of booting degraded on the profile default.
# WAKE_MODEL_FAIL_OPEN=1 restores the old fail-soft behaviour, explicitly, for an
# operator who would rather run degraded than not run at all.
if (-not $modelReady) {
    if ($env:WAKE_MODEL_FAIL_OPEN -eq '1') {
        Write-Out "model: UNRESOLVED (WAKE_MODEL_FAIL_OPEN=1 - booting on the profile composition default) - $modelProblem"
    } else {
        Write-Out "model: FAIL-LOUD UNRESOLVED - refusing to boot on the profile composition default: $modelProblem"
        Write-Out "=== exit code: 3 ==="
        Write-Out "WAKE_EXIT_CODE=3"
        Write-Out "WAKE_COST_USD=none"
        exit 3
    }
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

    # THE RECURSION GUARD, armed where it counts. A woken session runs the same
    # wake CLI, so a session that misunderstands its task could file a flag, which
    # releases another session, which files another - unbounded, spending money,
    # with only the daily cap between it and a fleet. wake.py refuses every flag
    # when WAKE_SESSION is set; setting it here is what makes that guard real
    # rather than theoretical. (Integration addition: the fleet built the refusal
    # in the store but nothing set the variable for the session.)
    $psi.EnvironmentVariables['WAKE_SESSION'] = '1'

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
# FAIL LOUD (ledger item 342, part 4). A shift that produced NO final answer and
# exited non-zero must SAY SO in a line a parser can grep, instead of leaving the
# reason buried in provider/MCP stderr chatter.
#
# MEASURED BEFORE THIS CHANGE - wake-out-351-20261001T194603Z-151139.txt:
#   --- stdout (final answer) ---            <- EMPTY
#   --- stderr (provider reasoning) ---      <- 30 lines of mcp-remote chatter
#   dsh: STREAM_CLOSED: SSE stream ended without [DONE]     <- line 43, unstructured
#   === exit code: 1 ===
#   WAKE_EXIT_CODE=1
# An empty, exit-1 shift was therefore indistinguishable from any other failure to
# anything that reads WAKE_EXIT_CODE, and the engine's own code was not named.
#
# This block adds WAKE_EMPTY_ANSWER=1 and WAKE_FAIL_REASON=<CODE>: <detail>, both
# ABOVE the exit-code lines so the tail the dispatcher parses is unchanged
# (dispatch.sh:503 greps WAKE_EXIT_CODE= with tail -1).
# ---------------------------------------------------------------------------
$answerEmpty = ($stdout.Trim().Length -eq 0)
$engineReason = $null
if ($answerEmpty -and $code -ne 0) {
    foreach ($text in @($stderr, $stdout)) {
        if (-not $text) { continue }
        # dsh's own error line: "dsh: STREAM_CLOSED: SSE stream ended without [DONE]"
        $m = [regex]::Match($text, 'dsh:\s*([A-Z][A-Z0-9_]*)\s*:\s*([^\r\n]+)')
        if ($m.Success) {
            $engineReason = "$($m.Groups[1].Value): $($m.Groups[2].Value.Trim())"
            break
        }
        # a JSON error envelope, if the engine ever emits one instead
        $m2 = [regex]::Match($text, '"code"\s*:\s*"([A-Z][A-Z0-9_]*)"')
        if ($m2.Success) { $engineReason = $m2.Groups[1].Value; break }
    }
    Write-Out "!!! EMPTY ANSWER: the session produced NO final answer and exited $code - NO WORK WAS DONE"
    Write-Out "WAKE_EMPTY_ANSWER=1"
    if ($engineReason) { Write-Out "WAKE_FAIL_REASON=$engineReason" }
    else { Write-Out "WAKE_FAIL_REASON=none-reported-by-engine" }
}

# ---------------------------------------------------------------------------
# THE LAUNCHER NEVER RAN DSH AT ALL (2026-10-27). Distinct from an empty answer,
# because the consequences are opposite: an empty answer means a session booted and
# failed, so the item's attempt WAS spent on it; a launcher failure means no session
# existed, so nothing was attempted and the item must keep its attempt.
#
# MEASURED BEFORE THIS LINE EXISTED. ZABZ-TECH, 2026-10-27 from 17:08Z: both npm
# `_npx` roots were absent, resolution fell through to `npx dsh`, npm said
# "npm error could not determine executable to run", and every release died in 3-24 s.
# The dispatcher could only say "ssh hop failed (rc=1) ... out-file was recovered
# (runner exit 1)", which wake.py's _retryable_reason deliberately EXCLUDES - so
# `project:lpt-website:20261027` spent attempt 1 at 17:08 and attempt 2 at 18:08 and
# became state=failed, attempts=2/2, permanently dead, with 57 todo items waiting.
# One infrastructure fault cancelled a project's whole day.
#
# The signal is POSITIVE and third-party: npm's own error vocabulary, which only
# appears when the launcher failed before any node process of ours started. A run
# that boots and then fails keeps WAKE_EMPTY_ANSWER and no WAKE_NOT_STARTED.
# ---------------------------------------------------------------------------
$launchFailed = $false
$launchWhy = $null
if ($launchError) {
    $launchFailed = $true
    $launchWhy = "process could not be started: $launchError"
}
if (-not $launchFailed -and $answerEmpty -and $code -ne 0 -and $stderr) {
    $npmLine = ($stderr -split "`r?`n" | Where-Object {
            $_ -match 'npm (error|ERR!)' -or $_ -match 'could not determine executable to run'
        } | Select-Object -First 1)
    if ($npmLine) {
        $launchFailed = $true
        $launchWhy = 'launcher refused to start dsh: ' + $npmLine.Trim()
    }
}
if ($launchFailed) {
    Write-Out "!!! NO SESSION EXISTED: $launchWhy"
    Write-Out 'WAKE_NOT_STARTED=1'
    Write-Out ("WAKE_NOT_STARTED_REASON=" + $launchWhy.Substring(0, [Math]::Min(240, $launchWhy.Length)))
    Write-Out 'WAKE_NOT_STARTED_CLASS=launcher'
}

# ---------------------------------------------------------------------------
# SESSION ID SIDECAR (ledger housekeeping item 12). wake-cost.py records a run
# TOKEN but never the DSH session id, so the release -> session map was DERIVED
# from timing and content; a release whose session carries none of its
# fingerprint text could not be mapped and its spend stayed unknown. Its own
# docstring names this exact fix: write the id to `wake-session-<release
# id>-<run token>.txt` and let the dispatcher copy it back like `wake-out-*.txt`.
#
# BEST-EFFORT BY CONSTRUCTION: this runs after the verdict is decided and never
# touches $code. A missing sidecar degrades the row to `near`/`none` (the old
# behaviour); it must never change what the run is recorded to have done.
# ---------------------------------------------------------------------------
try {
    $resolver = Join-Path (Split-Path -Parent $PSCommandPath) 'wake-session-id.ps1'
    if (Test-Path -LiteralPath $resolver) {
        $psExe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
        if (-not $psExe) { $psExe = (Get-Command powershell -ErrorAction SilentlyContinue).Source }
        if ($psExe) {
            $sidArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $resolver,
                         '-PromptFile', $PromptFile, '-OutFile', $OutFile,
                         '-StartedUtc', $started.ToUniversalTime().ToString('o'),
                         '-EndedUtc', (Get-Date).ToUniversalTime().ToString('o'), '-Json')
            if ($launch.Cwd) { $sidArgs += @('-RunnerCwd', $launch.Cwd) }
            $sidOut = & $psExe @sidArgs 2>$null | Select-Object -Last 1
            if ($sidOut) { Write-Out "session-id: $sidOut" }
        }
    }
} catch {
    Write-Out "session-id: sidecar not written: $($_.Exception.Message)"
}

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
