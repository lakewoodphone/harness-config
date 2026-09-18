# Warm shells and shell-tool latency on Windows — cited research

Each bullet carries its source. Non-vendor, non-source claims are labelled **community**.

## 1. ConPTY vs pipes for a persistent/stateful shell on Windows

**What the API officially guarantees**

- A pseudoconsole lets an app host character-mode apps: the host owns display and input, but the console session still exists and "all the rules of console sessions still apply" — https://learn.microsoft.com/en-us/windows/console/pseudoconsoles
- `CreatePseudoConsole` needs two channels "currently restricted to synchronous I/O" (no async pipes) plus a character-cell size; streams are UTF-8 text interleaved with Virtual Terminal Sequences, closed via `ClosePseudoConsole` — https://learn.microsoft.com/en-us/windows/console/createpseudoconsole
- Documented cost: each channel must run on its own thread, since single-threaded servicing "may result in a deadlock where one of the communications buffers is filled" — https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session
- `ClosePseudoConsole` sends `CTRL_CLOSE_EVENT`, clients may keep writing until disconnected, so the host must close or keep draining the output pipe; closing also terminates related processes in the tree — https://learn.microsoft.com/en-us/windows/console/closepseudoconsole
- Same page: on Windows 11 24H2 (26100)+ that call returns immediately, but **earlier versions wait indefinitely**, so failing to drain can hang the host — https://learn.microsoft.com/en-us/windows/console/closepseudoconsole

**Documented minimum Windows build**

- Minimum supported client for `CreatePseudoConsole`, `ResizePseudoConsole` and `ClosePseudoConsole` is **Windows 10 October 2018 Update (version 1809)**, desktop apps only — https://learn.microsoft.com/en-us/windows/console/createpseudoconsole
- ConPTY first shipped in the Autumn/Fall 2018 Windows 10 release; older-Windows apps must detect it with `LoadLibrary`/`GetProcAddress` — https://devblogs.microsoft.com/commandline/windows-command-line-introducing-the-windows-pseudo-console-conpty/
- Microsoft's `node-pty`: Windows support uses "the Windows conpty API on Windows 1809+"; winpty was removed and "Windows 10 version 1809 (build 18309) or later is now required" — https://github.com/microsoft/node-pty/blob/main/README.md
- Independent confirmation: Codex gates on `MIN_CONPTY_BUILD = 17_763` via `RtlGetVersion`, erroring "Windows 10 October 2018 or newer is required" — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/psuedocon.rs

**What breaks under ConPTY**

- Command-boundary markers drift: VS Code says ConPTY "works a little differently to a regular pty", sequences "may be misplaced", and exposes `IsWindows` because their "positioning … [is] not guaranteed to be correct" — https://code.visualstudio.com/docs/terminal/shell-integration
- Cursor desync: ConPTY keeps a stale cursor after an unrecognised escape sequence (APC/Kitty graphics); the fix queries the real position by DSR CPR, and the issue calls it the same class as resize desync (#18725) — https://github.com/microsoft/terminal/issues/19926
- Availability gap: "ConPTY inside WSL is broken (e.g. running cmd.exe inside WSL)" — https://github.com/microsoft/terminal/issues/17822
- Input needs translation: Codex carries a separate `WindowsTtyInputNormalizer` on the write path and passes `PSEUDOCONSOLE_RESIZE_QUIRK` — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/pty.rs
- Ctrl-C is not a plain signal: OpenHands' Windows backend sends `CTRL_BREAK_EVENT` then kills descendants with `Get-CimInstance Win32_Process`, because CTRL_BREAK "can interrupt the waiting script first, leaving launched child processes alive" — https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/windows_terminal.py
- Non-TTY behaviour: a PTY child sees a console, so TTY-detecting programs change. OpenHands forces `PAGER=cat` because commands auto-launching `less` on a TTY "capture the pane and wedge the session" — https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/tmux_terminal.py
- Pipes have the opposite weakness: Codex's pipe backend says Windows "process-tree containment is best-effort because Tokio returns only after the root process starts, so job assignment cannot be atomic" — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/pipe.rs

**Measured ConPTY-vs-pipes comparison**

- **Not found.** No Microsoft-documented latency, throughput or CPU comparison for a long-lived shell; the nearest measured Windows terminal numbers are **community**, cover rendering (a render path at "usually around 1-3 ms", with postmortems), not transport — https://github.com/nowledge-co/con-terminal/pull/68

## 2. How other harnesses keep shell state warm

**Claude Code (closed source)**

- Its Bash tool description, quoted upstream, says "Working directory persists between commands; shell state (everything else) does not"; CWD reportedly resets to project root and `export`/virtualenv state does not survive — https://github.com/anthropics/claude-code/issues/28228
- Same issue: a Windows CWD non-persistence bug was filed and auto-closed, and context compaction also resets CWD, so even CWD persistence is unreliable — https://github.com/anthropics/claude-code/issues/28228
- **Community** reverse-engineering claiming a persistent session that preserves env/CWD and captures exit codes with a 120 s timeout contradicts the upstream behaviour above and is unresolved — https://github.com/mo-haggag/claude-code-induced-introspection/blob/main/docs/subsystems/bash_tool_explanation.md

**OpenAI Codex CLI (source)**

- `unified_exec` keeps resumable processes keyed by `process_id`: output streams to a `yield_time_ms` deadline, the result is `Alive` (resume by id) or `Exited` with an exit code, and stdin is fed later via a `write_stdin` interaction — state lives in the process, not replayed — https://github.com/openai/codex/blob/main/codex-rs/core/src/unified_exec/process_manager.rs
- Exit is an event, not a poll: a `oneshot` exit channel is fed by a blocking `child.wait()` — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/pty.rs
- On Windows the PTY path is ConPTY and every spawn gets a Job Object; the child is created `CREATE_SUSPENDED`, assigned, then resumed with `NtResumeProcess` to close the assign-after-start race — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/psuedocon.rs
- Per-platform command shape: PowerShell `-NoProfile -Command`, cmd `/c`, POSIX `-lc`/`-c` — https://github.com/openai/codex/blob/main/codex-rs/core/src/shell.rs

**Aider (source)**

- No warm shell: every command is `subprocess.Popen(..., shell=True)` returning `(returncode, output)`; with no session object, CWD/env persist only if the caller passes `cwd` — https://github.com/Aider-AI/aider/blob/main/aider/run_cmd.py

**OpenHands (source)**

- Its terminal tool is "a persistent shell session": "Environment variables, virtual environments, and working directory persist between commands", with tmux auto-detected and a subprocess-PTY fallback — https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/README.md
- Completion detection is a prompt sentinel: a custom `PS1` emits `CmdOutputMetadata` (exit code, dir, pid) and the backend scans pane content for PS1 begin/end markers — https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/tmux_terminal.py
- The legacy implementation polled the pane every `POLL_INTERVAL = 0.5` s, treated "completed" as output ending with the PS1 end marker, and added a 30 s no-change timeout plus a hard timeout — https://github.com/OpenHands/OpenHands/blob/0.30.0/openhands/runtime/utils/bash.py
- On Windows it keeps one `powershell.exe -NoLogo -NoProfile` over pipes (no ConPTY), writing the command plus a suffix that prints JSON metadata between PS1 markers, with stdout read on a dedicated thread — https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/windows_terminal.py

**SWE-agent / SWE-ReX (source)**

- One bash session is created at startup and every command runs in it via `run_in_session(BashAction(...))`, so CWD/env persist for the container's life — https://github.com/SWE-agent/SWE-agent/blob/main/sweagent/environment/swe_env.py
- Completion uses a PS1 sentinel (`SHELLPS1PREFIX`) plus a unique string: the command is suffixed with `TMPEXITCODE=$? ; sleep 0.1; echo -n 'UNIQUESTRING29234' ; (exit $TMPEXITCODE)`; the exit code is parsed from `EXITCODESTART$?EXITCODEEND` only when `check != "ignore"`, otherwise it is hardcoded 0 — https://github.com/SWE-agent/SWE-ReX/blob/main/src/swerex/runtime/local.py

**VS Code terminal / shell integration (official)**

- The terminal is a real long-lived shell, so state persists by construction; the API is `TerminalShellIntegration` plus `onDidStartTerminalShellExecution`/`onDidEndTerminalShellExecution`, the end event carrying `exitCode` — https://code.visualstudio.com/api/references/vscode-api
- Boundaries are detected by shell-emitted sequences injected at startup: `OSC 633 ; A` prompt start, `B` prompt end, `C` pre-execution, `D [; exit code]` finished, `E` command line (optional nonce against spoofing), plus `OSC 633 ; P ; Cwd=`; Final Term `OSC 133` and iTerm2 `OSC 1337` work with a "somewhat degraded experience" — https://code.visualstudio.com/docs/terminal/shell-integration

**Cursor / Windsurf**

- No official docs or source for either. **Community**, with a staff reply on Cursor's forum: "the default agent shell on Windows launches a fresh PowerShell process for each command and carries cwd and env forward by replaying state, rather than keeping one process alive"; its "Legacy Terminal Tool" keeps one process per chat; Windsurf produced no official docs or source at all — https://forum.cursor.com/t/persistent-warm-shell-process-across-agent-tool-calls-windows-edr-overhead/171272

## 3. Windows process-creation cost, measured

- **No official Microsoft figure exists for `CreateProcess` cost**, for parent address-space/DLL effects, or for Defender's first-execute cost. "A fork() in the road" contrasts fork's zero arguments with `CreateProcess()` taking "explicit parameters specifying every aspect of the child's kernel state — 10 parameters and many optional flags" — https://www.microsoft.com/en-us/research/uploads/prod/2019/04/fork-hotos19.pdf
- Its Figure 1 is the closest official measurement of the *parent-state* effect: fork+exec rises with parent address-space size (0–250 MiB, up to roughly 20–25 ms) while `posix_spawn` stays flat — fork-family data, not Windows — https://www.microsoft.com/en-us/research/uploads/prod/2019/04/fork-hotos19.pdf
- **Community** discussion argues "`CreateProcess` on Windows by itself isn't 'expensive'", the cost being mapping a new address space and running `main()` — a comment, not a measurement — https://lwn.net/Articles/785430/
- **Community, unmeasured:** an agent project's perf issue states "On Linux, each spawn adds ~5-10ms. On Windows, each adds ~50-200ms", adding "2-4 seconds" over 20+ tool calls, with no methodology — https://github.com/aden-hive/hive/issues/4427
- **Community, measured and self-reported:** a Defender-taxed process start at ~355 ms vs ~332 ms (≈7 % delta), with Python interpreter cold start at ~246 ms per shim; the write-up says the two competing diagnoses were never reconciled — https://github.com/rjmurillo/ai-agents/issues/3175
- Microsoft's official tool for this records `Microsoft-Antimalware-Engine` events and reports scan counts and duration per file, per process, per reason, with a `SkipReason` column including "Optimization (typically due to performance reasons)" — Defender does skip work for performance, but no per-exec ms is published — https://learn.microsoft.com/en-us/defender-endpoint/tune-performance-defender-antivirus
- **Community:** behind CrowdStrike Falcon, per-command process creation pushed sub-2-second commands to 10–25 s end-to-end — https://forum.cursor.com/t/persistent-warm-shell-process-across-agent-tool-calls-windows-edr-overhead/171272

## 4. Making Node child-process spawns cheaper

- Documented `spawn` defaults: `cwd` = `process.cwd()`, `env` = `process.env`, `shell` = `false` (defaults to `/bin/sh` on Unix, `process.env.ComSpec` on Windows), `windowsHide` = `false`, `windowsVerbatimArguments` = `false` and auto-set `true` "when `shell` is specified and is CMD", `timeout` = `0`/`undefined`, `serialization` = `'json'` (or `'advanced'` for `fork` IPC) — https://nodejs.org/api/child_process.html
- The `.cmd`/`.bat` trap: these "are not executable on their own without a terminal, and therefore cannot be launched using `child_process.execFile()`"; the routes are `spawn` with the shell option (marked "not recommended, see DEP0190"), `exec()`, or `cmd.exe /c` — https://nodejs.org/api/child_process.html
- Cost consequence of that mechanism: invoking a `.cmd` shim always costs one extra process (`cmd.exe`) beyond the shim's own interpreter, since the shim cannot be the direct image — https://nodejs.org/api/child_process.html
- CVE-2024-27980: arguments could inject commands "even if the shell option is not enabled", and Node now "will now error with `EINVAL` if a `.bat` or `.cmd` file is passed to `child_process.spawn` … without the `shell` option set"; `--security-revert=CVE-2024-27980` is advised against; affected 18.x/20.x/21.x — https://nodejs.org/en/blog/vulnerability/april-2024-security-releases-2
- What `shell: true` costs: an extra shell process and no arg escaping — `DEP0190` is a **runtime** deprecation stating values "are not escaped, only space-separated, which can lead to shell injection"; `DEP0196` covers an empty-string `options.shell` — https://nodejs.org/api/deprecations.html
- `NODE_COMPILE_CACHE=dir` (v22.1.0) enables an on-disk V8 code cache, with an explicit tradeoff: it "may slow down the first load of a module graph, but subsequent loads of the same module graph may get a significant speedup if the contents of the modules do not change" — https://nodejs.org/api/module.html
- Cache semantics for short-lived children: entries are per Node.js version and not reusable across versions, `module.enableCompileCache()` never throws, and `readOnly`/`NODE_COMPILE_CACHE_READONLY=1` exists for shipped caches; `os.tmpdir()` is recommended — https://nodejs.org/api/cli.html
- No per-invocation ms figure for the compile cache appears in the docs — only the qualitative "significant speedup" — and the 22.1.0 release notes carry the feature without a benchmark table — https://nodejs.org/en/blog/release/v22.1.0
- `NODE_OPTIONS` forwards only an allow-listed set of V8 options including `--max-old-space-size`, documented purely as a heap ceiling, with no startup-time claim — https://nodejs.org/api/cli.html

## 5. Windows Job Objects as a process-tree owner

- `CreateJobObjectW` starts with "all limits are inactive, and there are no associated processes"; processes join via `AssignProcessToJobObject`; the job is destroyed when its last handle closes *and* all members exited — unless it has `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, in which case closing the last handle "terminates all associated processes and then destroys the job object itself" — https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-createjobobjectw
- `TerminateJobObject` kills every associated process and cannot be postponed or handled by them ("It is as if `TerminateProcess` were called for each process"); a nested job also terminates all child jobs — https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject
- Nesting constraints: before Windows 8/Server 2012 "a process can be associated with only a single job"; nesting happens only "if the system can form a valid job hierarchy and neither job sets UI limits"; assigning out of order makes `AssignProcessToJobObject` **fail**; breakaway depends on the *immediate* job, and effective limits can only be more restrictive than the parent's — https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs
- `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is a `LimitFlags` bit in `JOBOBJECT_BASIC_LIMIT_INFORMATION` within `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, set via `SetInformationJobObject` with the `JobObjectExtendedLimitInformation` class — https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information
- Containment is not guaranteed: Codex's job wrapper notes "Nested jobs can reject assignment. Such a child is resumed without containment so callers can preserve their existing compatibility fallback", and that "Assignment is not retroactive: descendants created before this call completes are not guaranteed to become members of the job" — hence `CREATE_SUSPENDED` → assign → `NtResumeProcess` — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/job.rs
- **No published cost** for job creation/assignment was found. Practical shape per command from Codex: `CreateJobObjectW` + `SetInformationJobObject` + `AssignProcessToJobObject` + an extra `OpenProcess` + suspend/resume; it also sets `JOB_OBJECT_LIMIT_BREAKAWAY_OK` and can drop kill-on-close when the root exits normally — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/job.rs

## 6. Polling vs events for child-exit detection on Windows

- Event wait is the documented primitive: `WaitForSingleObject` waits until the object is signaled, and the documented waitable-object list includes **Process** — https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject
- `INFINITE` "will return only when the object is signaled", while 0 "does not enter a wait state if the object is not signaled; it always returns immediately", so one primitive covers blocking and free probing — https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject
- `GetExitCodeProcess` "returns immediately", returns `STILL_ACTIVE` (a macro for `STATUS_PENDING`) while running, and the real code only after termination; the docs warn not to use 259 as an application error code because pollers would loop forever — https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess
- Node does not poll: libuv's Windows backend registers a callback with `RegisterWaitForSingleObject`, and its comments flag that probing `GetExitCodeProcess` plus `WaitForSingleObject(handle, 0)` is "prone to a race" relative to a real wait — https://github.com/libuv/libuv/blob/v1.x/src/win/process.c
- Timer polling is documented as imprecise: `setTimeout` "will likely not be invoked in precisely `delay` milliseconds. Node.js makes no guarantees about the exact timing of when callbacks will fire"; sub-1 ms delays become 1 ms — https://nodejs.org/api/timers.html
- Each timer also costs a loop decision: libuv derives its poll timeout from "the closest timer", and a timer becoming due while other timers run "won't be run until the following event loop iteration" — https://docs.libuv.org/en/v1.x/design.html
- **No official measured overhead figure for a 10 ms `setInterval`** was found. Shipped agents use events: Codex feeds a `oneshot` exit channel from a blocking `child.wait()`, and OpenHands' Windows backend uses a `threading.Event` plus a blocking reader thread — https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/windows_terminal.py

## What is NOT established

- **No official measured ConPTY-vs-pipes comparison** (latency, throughput, CPU) for a long-lived shell exists in Microsoft documentation — https://github.com/nowledge-co/con-terminal/pull/68
- **No official `CreateProcess` microbenchmark**, no Microsoft figure for parent address-space/DLL effects, and no Microsoft figure for Defender's first-execution cost on a not-yet-cached executable; the 5-10 ms vs 50-200 ms Windows figures are an unsourced community estimate — https://github.com/aden-hive/hive/issues/4427
- **No published cost for job creation/assignment**, and no quantified failure rate for job assignment when the agent already runs inside another job — https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs
- **No official measured overhead for a 10 ms `setInterval`**, and no vendor quantification of how much cheaper `WaitForSingleObject` is than `GetExitCodeProcess` polling — https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject
- **No per-invocation ms figure for `NODE_COMPILE_CACHE`**, and **no evidence `NODE_OPTIONS` or `--max-old-space-size` materially change short-lived Node child startup** — https://nodejs.org/api/module.html
- **Claude Code, Cursor and Windsurf internals are not officially documented**; the community Claude Code claim of full shell persistence contradicts the upstream issue — https://github.com/anthropics/claude-code/issues/28228
- **Whether Codex falls back from ConPTY to its pipe backend was not verified**, and **no ANSI/CSI fidelity-loss or Ctrl-C delivery rates under ConPTY are measured** — https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/psuedocon.rs
