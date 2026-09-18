# Running many concurrent, agent-spawning Node.js processes on one Windows laptop

Research report — 2026-09-16 (local 2026-09-15 late evening).

## Provenance of every number in this report

| What | Where from | When |
|---|---|---|
| Local measurements ("measured on this laptop") | `ZABZ-YOGA`, Windows 11, PowerShell 7.6.6, Node `v24.12.0`, npm `11.6.2`, 22 logical cores, 16 physical cores (6P+8E+2LPE) | 2026-09-16 ~02:20 UTC, **while the machine was in the described degraded state**, not idle |
| Local counter snapshot at that moment | `Get-Counter` via pwsh | commit charge **39.43 GB** of commit limit **44.30 GB**; available **5,287 MB**; `\Memory\Pages Input/sec` **831/s** (hard faults); **531** processes; **52** `node` processes; **15** `conhost` processes |
| Web sources | fetched this session; URLs inline | — |

**Read every local timing below as an upper bound taken from a thrashing machine**, not as a clean benchmark. The point of quoting them is that they show *what the failure looks like when measured*, which is the baseline this fix has to beat.

Where I could not find hard evidence I write **"no evidence found"**. Where a claim is commonly repeated but wrong I write **MYTH**.

---

# Q1. Node.js version and runtime flags

## 1.1 Which Node major changes memory or startup for many short-lived processes

**Claim: no measured evidence exists that any Node major (18/20/22/24) "uses less memory" per process. There is measured evidence of a *startup regression* introduced in the v22 era, and measured evidence that V8/Node added an on-disk compile cache whose benefit is version-agnostic.**

- Evidence — startup regression: [nodejs/performance#180 "Potential startup regression since on Node.js >= 22"](https://github.com/nodejs/performance/issues/180). Measured with hyperfine: `./node-0522ac08 --version` = **14.6 ms ± 0.5** vs `./node-6b76b778 --version` = **23.3 ms ± 0.5** — "1.60 ± 0.07 times faster". Joyee Cheung attributes it to the V8 11.8 upgrade ([nodejs/node#49639](https://github.com/nodejs/node/pull/49639)) and notes she could reproduce on arm64 macOS but not on a Linux server. Later comments report the regression was transient across a couple of v22 releases and "seems to be working normally again" on Ubuntu 22.04, with a bare `node --version` measured at **26.3 ms** on an 8th-gen i5 laptop.
- Evidence — compile cache: `NODE_COMPILE_CACHE` landed in **v22.1.0** ([nodejs.org release v22.1.0](https://nodejs.org/en/blog/release/v22.1.0)) via [nodejs/node#52535](https://github.com/nodejs/node/pull/52535), which states: *"Locally, this speeds up loading of `test/fixtures/snapshot/typescript.js` from **~130 ms to ~80 ms**."* The API `module.enableCompileCache()` / `getCompileCacheDir()` / `compileCacheStatus` was added **v22.8.0**, `module.flushCompileCache()` in **v23.0.0 / v22.10.0**, and `NODE_COMPILE_CACHE_READONLY` only in **v26.8.0** ([nodejs.org/api/module.html](https://nodejs.org/api/module.html)).
- Applies here: **stay on Node 24 LTS (the installed `v24.12.0`).** There is nothing to gain from a major-version downgrade and no measured per-process RAM difference between majors to chase. The real levers are the compile cache and process count, not the major number.
- **MYTH:** *"Node 22/24 uses less RAM than Node 18/20."* No measurement found supporting any per-process RSS reduction by major version. Per-process RSS is dominated by the image, V8 baseline, and loaded module graph, not by the major version.

## 1.2 `NODE_COMPILE_CACHE` — the single biggest lever for spawn-heavy workloads

**Claim: `NODE_COMPILE_CACHE` persists V8 code cache on disk per module, so repeated short-lived processes skip recompiling the same module graph. It is enabled by env var or by `module.enableCompileCache()`, and the cache is versioned and user-suffixed by default.**

- Evidence: [nodejs.org/api/module.html](https://nodejs.org/api/module.html) — *"whenever Node.js compiles a CommonJS, an ECMAScript Module, or a TypeScript module, it will use on-disk V8 code cache persisted in the specified directory… This may slow down the first load of a module graph, but subsequent loads of the same module graph may get a significant speedup if the contents of the modules do not change."* Default directory is `path.join(os.tmpdir(), 'node-compile-cache')`; the docs *recommend* a directory under `os.tmpdir()` "to avoid filling up the disk with stale cache".
- Critical operational detail: *"the code cache is generated from the compiled code immediately, but will only be written to disk when the Node.js instance is about to exit."* For a fleet that spawns hundreds of short-lived processes, the **long-lived parent must call `module.flushCompileCache()`** (v23.0.0/v22.10.0) so children see a warm cache. This is exactly what the docs say the method is for: *"in case the application wants to spawn other Node.js instances and let them share the cache long before the parent exits."*
- Second critical detail: *"Compilation cache generated by one version of Node.js can not be reused by a different version."* So the cache must be cleared on any Node upgrade, and multi-version fleets get one cache directory per version automatically.
- Third: cache is version+user keyed; a portable cache (`NODE_COMPILE_CACHE_PORTABLE=1`) is needed if the project directory moves.
- Also: *"when using the compile cache with V8 JavaScript code coverage, the coverage … may be less precise."* Disable it for coverage runs with `NODE_DISABLE_COMPILE_CACHE=1` (added v22.8.0).
- Measured on this laptop (n=6 each, loaded machine, `node -e ""`): **1,280 ms → 1,028 ms** with a warm compile cache. Small sample, high variance — directional only, and the absolute numbers are inflated by paging (see Q2). The upstream measured 38% reduction on a cold module graph is the trustworthy figure.
- Applies here: set `NODE_COMPILE_CACHE` **once, machine-wide**, to a fixed short path (e.g. `C:\Users\ezabz\AppData\Local\node-compile-cache`), and make every DSH process inherit it. Expect the biggest wins on the CLI entry points and the MCP servers, which load large dependency graphs per spawn. Do **not** put it under `%TEMP%` if Defender is excluded on the repo but not on temp — put it somewhere you also exclude.

## 1.3 `--max-old-space-size`

**Claim: it caps V8's *old generation* only. It does not cap RSS or total commit. The documented use is to leave headroom on memory-constrained machines.**

- Evidence: [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) — *"Sets the max memory size of V8's old memory section. As memory consumption approaches the limit, V8 will spend more time on garbage collection in an effort to free unused memory. On a machine with 2 GiB of memory, consider setting this to 1536 (1.5 GiB) to leave some memory for other uses and avoid swapping."* Allowed in `NODE_OPTIONS`. There is also `--max-old-space-size-percentage` (percentage of available system memory, takes precedence over the absolute flag).
- Applies here: **apply it to the long-lived MCP servers, not to the hundreds of short-lived tool subprocesses.** A short-lived CLI that finishes in 1 s never GCs enough for the cap to matter, and a low cap turns a legitimately memory-hungry tool into an OOM crash. The MCP servers are the ones that grow to hundreds of MB and stay resident — see [claude-code#45880](https://github.com/anthropics/claude-code/issues/45880), which names `NODE_OPTIONS=--max-old-space-size=256` on MCP children as *"the single highest-impact fix"*.
- **MYTH:** *"Setting `--max-old-space-size` reduces a Node process's memory."* It caps one heap region. Node's RSS also includes the young generation, code space, the snapshot, and external/native buffers. Measured per-process figures in the wild (197–295 MB per subagent Node process, [claude-code#11502](https://github.com/anthropics/claude-code/issues/11502)) are not explained by a single heap-limit number.

## 1.4 `--max-semi-space-size`

**Claim: it trades memory for throughput; each +1 MiB of semi-space costs ~3 MiB of heap. The default already scales with the memory limit, and the docs say throughput benefit is workload-dependent.**

- Evidence: [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) — *"Since the young generation size of the V8 heap is three times … the size of the semi-space, an increase of 1 MiB to semi-space applies to each of the three individual semi-spaces and causes the heap size to increase by 3 MiB. The throughput improvement depends on your workload (see [#42511](https://github.com/nodejs/node/issues/42511))."* Default on 64-bit with a 512 MiB limit is 1 MiB; for limits up to 2 GiB the default is under 16 MiB.
- Applies here: **do not touch it.** For a workload that is process-count-bound and memory-constrained, raising semi-space makes the exact metric that is already failing (commit charge) worse, for a throughput gain that the docs explicitly refuse to promise. The correct direction even reverses: for a *capped* process, a *smaller* semi-space reduces peak young-gen footprint at the cost of more scavenges.

## 1.5 `--jitless`, `--no-opt`

**Claim: `--jitless` disables executable-memory allocation and Node's own docs call the performance impact potentially severe. `--no-opt` is not a documented Node flag and is not in the `NODE_OPTIONS` allowlist.**

- Evidence: [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) — `--jitless` (v12.0.0, Stability 1 Experimental): *"Disable runtime allocation of executable memory. … It can also reduce attack surface on other platforms, but the performance impact may be severe."* The `NODE_OPTIONS` allowlist of V8 flags is enumerated in the same page and contains `--jitless`, `--max-heap-size`, `--max-old-space-size`, `--max-semi-space-size`, `--stack-trace-limit`, `--expose-gc`, `--disallow-code-generation-from-strings`, `--interpreted-frames-native-stack`, `--abort-on-uncaught-exception`, and the Linux-only perf flags. **`--no-opt` does not appear anywhere in `node --help` or the Node CLI docs.**
- Applies here: **use neither.** There is **no evidence found** of a measured memory win from `--jitless` on a spawn-heavy Node workload, and it would slow every JS-heavy tool call. `--no-opt` is a V8 internal; passing it is unsupported and untested by the Node team ("V8's options have *no stability guarantee*" — [cli.html](https://nodejs.org/api/cli.html)). If you want to test `--jitless` on a *single* short-lived class of process, measure it; do not put it in the global `NODE_OPTIONS`.

## 1.6 `--snapshot-blob`

**Claim: it is an experimental (Stability 1) V8 startup-snapshot mechanism, added v18.8.0, allowed in `NODE_OPTIONS`. Loading a blob hard-fails on any version/arch/platform/V8-flag/CPU-feature mismatch.**

- Evidence: [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) — *"When used without `--build-snapshot`, `--snapshot-blob` specifies the path to the blob that is used to restore the application state… Node.js checks that: 1. The version, architecture, and platform of the running Node.js binary are exactly the same… 2. The V8 flags and CPU features are compatible… If they don't match, Node.js refuses to load the snapshot and exits with status code 1."*
- Applies here: **theoretically the biggest startup lever (it skips module parsing entirely), practically a trap for this fleet.** A blob that hard-exits with code 1 on a Node patch upgrade, or because one process added a V8 flag another didn't, will look exactly like the "tool calls return blank" failure already being seen. If adopted at all, adopt it as an experiment on one class of process, with `--build-snapshot` regenerated in CI on every Node upgrade, and fail *open* (fall back to normal startup) rather than exit 1.

## 1.7 `--disable-warning`, `--no-warnings`, `NODE_OPTIONS`

**Claim: `--disable-warning=code-or-type` is stable and allowed in `NODE_OPTIONS`; `--no-warnings` is also allowed; `NODE_OPTIONS` accepts a documented subset of flags, and command-line flags override it.**

- Evidence: [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) — `--disable-warning=code-or-type` (now stable), e.g. `node --disable-warning=ExperimentalWarning`. The allowlist includes `--disable-warning` and `--no-warnings`. On precedence: *"A singleton flag passed as a command-line option will override the same flag passed into `NODE_OPTIONS`"*; multi-instance flags are concatenated with `NODE_OPTIONS` first.
- Applies here: warning writes go to stderr, which in this fleet is usually a pipe back to a parent that has to parse it, and on Windows a console-attached process means the write path involves `conhost`. Suppressing known-noisy warning classes is cheap and reduces per-spawn work. Use `--disable-warning=ExperimentalWarning,DeprecationWarning` rather than blanket `--no-warnings`, so genuine deprecations still surface.

## 1.8 `UV_THREADPOOL_SIZE` (bonus lever the question didn't ask about)

**Claim: libuv's threadpool defaults to 4 threads and is used by all async `fs`, `crypto`, `dns.lookup`, and `zlib` calls. Starving it makes unrelated APIs appear to hang.**

- Evidence: [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) — *"Because libuv's threadpool has a fixed size, it means that if for whatever reason any of these APIs takes a long time, other (seemingly unrelated) APIs that run in libuv's threadpool will experience degraded performance."* Must be set in the environment before the process starts (*"setting this from inside the process … is not guaranteed to work"*).
- Applies here: **this is a plausible mechanism for the reported "tool calls that hang".** A tool call whose `fs` work queues behind 4 saturated threadpool threads behind a Defender-scanned, page-faulting disk looks like a hang, not like slowness. Raising it to 8 is cheap and safe; more than that mostly adds contention on this machine. Set it as an env var in the launcher, not in code.

## 1.9 Summary table for Q1

| Flag / env | (a) long-lived server (dsh main, MCP servers) | (b) short-lived CLI subprocesses | Basis |
|---|---|---|---|
| Node 24 LTS | yes | yes | no measured per-major RAM win to chase |
| `NODE_COMPILE_CACHE` | yes | **yes — biggest win** | 130→80 ms, node#52535 |
| `module.flushCompileCache()` in parent | yes | n/a | docs: cache written only at exit |
| `--max-old-space-size=256` | **yes, on MCP servers** | no | claude-code#45880 |
| `--max-semi-space-size` | no | no | docs: workload-dependent, costs 3× |
| `--jitless` | no | no | docs: "impact may be severe"; no measured win found |
| `--no-opt` | no | no | **not a documented Node flag** |
| `--snapshot-blob` | experiment only | experiment only, fail-open | exits 1 on mismatch |
| `--disable-warning=…` | yes | yes | allowed in NODE_OPTIONS |
| `UV_THREADPOOL_SIZE=8` | yes | yes (env, pre-launch) | default 4; hang mechanism |

---

# Q2. Windows-specific limits and costs

## 2.1 There is no `fork()` on Windows; every spawn is a full `CreateProcess`

**Claim: Windows has no lightweight fork. Process creation always sets up a fresh address space and maps the image and its DLLs; there is no copy-on-write shortcut. Microsoft's own researchers argue in print that this is the *better* design, which is a separate question from whether it is cheap.**

- Evidence: [Microsoft Research — "A fork() in the road" (HotOS '19)](https://www.microsoft.com/en-us/research/publication/a-fork-in-the-road/), abstract and paper; community analysis and the authors' framing in the [LWN discussion](https://lwn.net/Articles/785430/), where the substantive point raised is that `CreateProcess` is criticised for API ugliness and backward-compatibility constraints rather than for being *inherently* expensive — i.e. do not over-claim that Windows process creation is inherently slow.
- Applies here: **the honest position is that Windows spawn is not catastrophically more expensive than Linux spawn; the cost on this laptop is dominated by *loading the Node image and its DLLs from a disk that is being scanned and paged*.** Evidence for that: measured on this laptop, `node -v` averaged **964.6 ms** (min 274.8, max 1,468.1; n=6) and `node -e ""` averaged **1,280.1 ms** while `\Memory\Pages Input/sec` was **831/s**. A bare `node --version` is a sub-50 ms operation on an idle Windows machine. **~20× of the spawn cost here is I/O and page-fault cost, not syscall cost.** This is why the fix ordering below puts memory/Defender/windowsHide ahead of micro-optimising Node flags.
- **MYTH:** *"Windows process creation is 10–100× slower than Linux fork()."* No evidence found for a factor that large. The measured comparison in nodejs/performance#180 was between two *Node builds of the same OS* (14.6 ms vs 23.3 ms), not between OSes.

## 2.2 `conhost.exe` and console windows

**Claim: Windows allocates a console (hosted by `conhost.exe`) for console subsystem processes, and Node explicitly creates one per child unless told not to. Node's `windowsHide` defaults to `false`.**

- Evidence: [Creation of a Console](https://learn.microsoft.com/en-us/windows/console/creation-of-a-console) — *"The system creates a new console when it starts a console process, a character-mode process whose entry point is the main function."* A process can avoid one via `DETACHED_PROCESS` ([Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags): *"For console processes, the new process does not inherit its parent's console… This value cannot be used with CREATE_NEW_CONSOLE"*) or run windowless with `CREATE_NO_WINDOW` (*"The process is a console application that is being run without a console window. Therefore, the console handle for the application is not set."*).
- Node's side, [nodejs.org/api/child_process.html](https://nodejs.org/api/child_process.html): `windowsHide` — *"Hide the subprocess console window that would normally be created on Windows systems. **Default: `false`.**"* Present on `exec`, `execFile`, `spawn`, `fork`.
- Is it per process? **Measured on this laptop: 52 `node` processes and 15 `conhost.exe` processes.** So `conhost` is shared per console/process-group rather than allocated strictly 1:1 — a console inherited from a common parent is reused. But every *new console* is a real process, and real projects have had to fix console-window flashes from spawns ([openhuman#1498 "silence conhost flashes from core-side spawns"](https://github.com/tinyhumansai/openhuman/pull/1498)).
- Applies here: **pass `windowsHide: true` on every `spawn`/`exec`/`execFile`/`fork` in DSH, its tool-call layer, and every MCP client.** Every DSH process also writes a non-zero amount of stderr; on Windows stderr attached to a console costs window-buffer work, which is part of what `dwm` has to composite. This is a one-line change per call site with no downside.

## 2.3 `shell: true` costs a second process, and `.bat`/`.cmd` force it

**Claim: on Windows, `exec`/`shell:true` spawns `cmd.exe` (from `process.env.ComSpec`) as an extra intermediate process, and `.bat`/`.cmd` files cannot be launched without one. Using `shell:true` with `args` is deprecated (DEP0190).**

- Evidence: [nodejs.org/api/child_process.html](https://nodejs.org/api/child_process.html) — *"On Windows, however, `.bat` and `.cmd` files are not executable on their own without a terminal, and therefore cannot be launched using `child_process.execFile()`"* — the recommended forms are `exec()`, or `spawn('cmd.exe', ['/c', 'my.bat'])`, or (not recommended, see DEP0190) `spawn()` with `shell` set. The `shell` option default is *"`/bin/sh` on Unix, `process.env.ComSpec` on Windows."*
- Applies here: **every `.cmd` shim (npm/npx shims, most Node CLI shims installed by npm on Windows) adds one `cmd.exe` per invocation.** In a fleet that spawns hundreds of short-lived calls, that doubles the process count for those calls. Prefer absolute paths to `node.exe` and to the package's real JS entry (`node path\to\cli.js`), never the `.cmd` shim.
- **MYTH:** *"`spawn` with `shell:true` is the same as `execFile`."* It is strictly worse: an extra shell process, an extra parse step, and a documented command-injection surface (*"Never pass unsanitized user input to this function"*).

## 2.4 `npx -y pkg@latest` is the worst possible way to start an MCP server

**Claim: `npm exec`/`npx` only reuses a local package when the specifier matches name **and exact version**; a floating tag like `@latest` therefore cannot match a local install and forces a registry resolution. Anything not already local is installed into the npm cache. And `npx` start-up itself is expensive.**

- Evidence: [npm docs — npx](https://docs.npmjs.com/cli/v10/commands/npx) — *"If any requested packages are not present in the local project dependencies, then they are installed to a folder in the npm cache, which is added to the `PATH`…"* and *"Package names with a specifier will only be considered a match if they have the exact same name and version as the local dependency."* Also: *"npx will always use the `npm` it ships with"*, so every `npx` run boots npm itself.
- Measured on this laptop (loaded machine, n=6): `npx --version` averaged **4,061.6 ms** (min 2,646.7, max 6,429.2) versus `node -v` at **964.6 ms** and a raw `node -e ""` at **1,280.1 ms**. That is roughly **3–4× a bare Node process just to enter npm**, before any registry round-trip or install.
- Real-world confirmation that this pattern multiplies: [openai/codex#38754](https://github.com/openai/codex/issues/38754) counted **51 `npx.exe`** as direct children of the app's process roots, alongside 17 `node.exe`, 17 `node_repl.exe`, 17 `python.exe`.
- Applies here: **replace every `npx -y pkg@latest` MCP entry with a pre-installed, version-pinned launch.** Concretely: install the MCP packages once into a dedicated prefix, invoke them as `node <abs path to entry>.js` or `node_modules\.bin\*.cmd`→absolute JS path, and never let `@latest` reach a runtime path. Expected effect: removes one npm boot (~3 s on this machine) plus one registry round-trip **per MCP server per session**, and removes a whole class of "first call hangs" behaviour when the registry is slow.
- Alternative if you must keep `npx`: pin an exact version (`pkg@1.2.3`) so the local match rule can hit, and add `--prefer-offline`. Do not use `@latest` under any circumstance in a hot path.

## 2.5 Microsoft Defender real-time scanning

**Claim: Defender's real-time protection scans file opens by default; Microsoft provides three legitimate configuration paths (custom exclusions, Developer Drive "performance mode", and a performance analyzer to measure first), and explicitly warns that exclusions are protection gaps to be used sparingly.**

- Evidence:
  - [Configure custom exclusions for Microsoft Defender Antivirus](https://learn.microsoft.com/en-us/defender-endpoint/configure-exclusions-microsoft-defender-antivirus) — file/folder, extension, process, and contextual exclusions; configurable by PowerShell, Group Policy, CSP, WMI `MSFT_MpPreference` (`ExclusionPath`, `ExclusionExtension`, `ExclusionProcess`).
  - [Exclusions in Microsoft Defender Antivirus](https://learn.microsoft.com/en-us/defender-endpoint/configure-extension-file-exclusions-microsoft-defender-antivirus) — *"Every exclusion is a protection gap that lowers your defenses, so use exclusions sparingly. Define an exclusion only to resolve a specific problem, such as a performance or app compatibility issue… Don't exclude something just because you think it might be a problem later."* Also the practical footguns: *"A file name only value like `sample.test` doesn't reliably exclude the file. Specify the file's full path instead."*; extension exclusions are global, so `C:\example\*.test` must be a path exclusion; and *"Using many process restrictions on a device can degrade performance."*
  - [Performance analyzer for Microsoft Defender Antivirus](https://learn.microsoft.com/en-us/defender-endpoint/tune-performance-defender-antivirus) — *"The performance analyzer is a PowerShell command-line tool that helps you determine files, file extensions, and processes that might be causing performance issues… during antivirus scans"*, via `Get-MpPerformanceReport`, with a `SkipReason` column whose values are `Not Skipped` / `Optimization` / `User skipped`. **This is how you prove the exclusion helped instead of guessing.**
  - [Set up a Dev Drive on Windows 11](https://learn.microsoft.com/en-us/windows/dev-drive/) — ReFS volume with *"targeted file system optimizations"* and a Defender **performance mode**: *"This capability reduces the performance impact of Microsoft Defender Antivirus scans for files stored on a designated Dev Drive."* Prerequisites: Windows 11 build 10.0.22621.2338+, min 50 GB free, local admin. Important caveat from the same page: *"The C: drive on your machine cannot be designated as a Dev Drive. Developer tools, such as Visual Studio, MSBuild, .NET SDK, Windows SDK, etc, should be stored on your C: drive and not in a Dev Drive."* Another: by default all filters are off on a Dev Drive *except* antivirus filters, and the antivirus-filter attachment can be disabled with `fsutil` (a machine-wide policy).
- Applies here: **this is a primary suspect and the cheapest high-yield change.** The workload's signature — thousands of small reads/writes (module loads, git worktrees, journal appends, SQLite WAL/`-shm` I/O) from many short-lived processes — is precisely Defender's worst case. Recommended order: (1) run `Get-MpPerformanceReport` for 10 minutes during a fleet run to get evidence; (2) add **path** exclusions (not extension exclusions, not bare names) for the repo root, the worktree root, the npm cache, and the journal/SQLite directory; (3) add a **process** exclusion for `node.exe` only if the path exclusions prove insufficient, accepting that process exclusions also switch off network protection and ASR inspection for that process ([exclusions doc](https://learn.microsoft.com/en-us/defender-endpoint/configure-extension-file-exclusions-microsoft-defender-antivirus)); (4) if this is a long-term pattern, move repos + npm cache + journal onto a Dev Drive and use performance mode instead of exclusions, which preserves protection.

## 2.6 Max processes and handles

**Claim: there is no documented hard per-machine process cap that this workload will hit; the binding limits are memory commit and kernel pool/handle consumption. A real Windows machine has been observed at 764 processes and 418,237 handles during exactly this failure.**

- Evidence: [openai/codex#38754](https://github.com/openai/codex/issues/38754) — *"At the time of the snapshot, the whole system had: 764 processes, 418,237 handles, 46.04 GiB aggregate process private bytes, ~54.3 GiB committed out of a ~59.9 GiB commit limit, ~3.8 GiB physical memory available"*, on a machine that also reported severe stutter and an OS bugcheck. The reporter's workaround was `taskkill /PID <pid> /T /F` on stale generations ([taskkill docs](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill): `/t` terminates the process *and any child processes started by it*, `/f` forces).
- A documented Windows limit that *does* bite console/window-heavy workloads is desktop heap exhaustion — [Fix Desktop Heap Limitation and Out of Memory Errors](https://learn.microsoft.com/en-us/troubleshoot/windows-server/performance/desktop-heap-limitation-out-of-memory). With a console-per-spawn pattern this is a plausible secondary failure, but **no evidence found** tying it to this specific measured symptom set, so treat it as a latent risk, not a diagnosis.
- Applies here: **do not spend effort on process-count limits; spend it on commit charge.** Measured on this laptop: 531 processes and 39.43 GB commit against a 44.30 GB limit, with only 5.29 GB available. The failure is memory, and the mystery is *why a 31.6 GB machine has a 44.3 GB commit limit* — that pagefile is absorbing the overcommit and converting a hard "out of commit" error into sustained thrashing. Both need fixing: cap the workload **and** keep the pagefile as a safety valve that the cap makes unreachable.

## 2.7 `taskkill` trees and orphaned processes

**Claim: on Windows `ChildProcess.kill()` terminates only the direct child; the process tree survives. Node documents that signals are handled differently on Windows and that killing a shell does not kill the shell's children.**

- Evidence: [nodejs.org/api/child_process.html](https://nodejs.org/api/child_process.html) — *"On Windows, where POSIX signals do not exist, signals are handled as follows. `'SIGKILL'`, `'SIGTERM'`, `'SIGINT'` and `'SIGQUIT'` terminate the process forcefully and abruptly (similar to `'SIGKILL'`)… `'SIGWINCH'` is not terminal and is not coerced: `subprocess.kill()` throws an `ENOSYS` error and the child keeps running."* And, on tree kill with a shell: *"`subprocess.kill(); // Does not terminate the Node.js process in the shell."*
- Applies here: **every DSH cleanup path must use a tree kill.** On Windows that means `taskkill /PID <pid> /T /F` via `spawn('taskkill', ['/PID', String(pid), '/T', '/F'], {windowsHide:true})`. This is the same fix the Codex reporter applied live. Without it, the `node` + `conhost` + `cmd.exe` population never returns to baseline — which is exactly the accumulation pattern documented in Q6.

---

# Q3. Concurrency architecture: how to enforce a global cap

## 3.1 What real tools actually do (all CPU-derived, none RAM-derived)

| Tool | Default concurrency | Source |
|---|---|---|
| Jest (single run) | *"the number of the cores available on your machine minus one for the main thread"* | [jestjs.io/docs/cli](https://jestjs.io/docs/cli) |
| Jest (watch mode) | *"half of the available cores on your machine **to ensure Jest is unobtrusive and does not grind your machine to a halt**"* | [jestjs.io/docs/cli](https://jestjs.io/docs/cli) |
| Playwright | *"Defaults to half of the number of logical CPU cores"*; accepts `'50%'` | [playwright.dev/api/class-testconfig](https://playwright.dev/docs/api/class-testconfig) |
| Gradle test forking | *"A good default is the number of available CPU cores or slightly fewer"*, sample code `Runtime.runtime.availableProcessors().intdiv(2) ?: 1` | [docs.gradle.org — performance](https://docs.gradle.org/current/userguide/performance.html) |
| Node's own `--test-concurrency` | *"defaults to `os.availableParallelism() - 1`"* | [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) |

- **Claim: the "cores/2" family is real and documented. The specific formula "cores/2 − 1" is not an official standard — no evidence found for it as a published rule.**
- **The rationale is documented, and it is exactly this problem.** Jest's watch-mode wording — *"to ensure Jest is unobtrusive and does not grind your machine to a halt"* — is the only official justification of the halving, and it is a *desktop-responsiveness* justification, not a throughput one. That is the governing constraint for an agent fleet running behind a human's compositor.
- Applies here: **22 logical / 16 physical cores is the wrong denominator for a background fleet.** On a hybrid Core Ultra 7 155H the E-cores are slower, and the human needs cores for `dwm` and the foreground app. Compute the CPU-derived ceiling as `floor(physical_cores / 2) - 1 = floor(16/2) - 1 = 7`. Then compute the memory-derived ceiling (below) and take the minimum. **The memory ceiling is lower, so memory governs.**

## 3.2 The memory-derived cap (the one that matters here)

Budget from measured numbers rather than a rule of thumb, because **no evidence found** for the widely-repeated "2–4 agents per 16 GB" figure — I could not locate a published, measured source for it.

- Physical RAM 31.6 GB; measured commit limit 44.30 GB; measured commit charge 39.43 GB.
- Keep the compositor alive: reserve ~6 GB commit for OS + `dwm` + browser + the human's foreground app. Target steady-state total commit ≤ ~28–30 GB, i.e. **agent budget ≈ 22 GB commit**.
- Costs: 10 dsh sessions × (Electron/webview ~250–400 MB + main Node ~150–300 MB) ≈ 5–6 GB. A bounded MCP server ≈ 150–350 MB. A short-lived tool subprocess ≈ 64–150 MB.
- ⇒ **8 MCP servers ≈ 2.8 GB worst case; 24 concurrent short-lived tool subprocesses ≈ 3.6 GB.** Total ≈ 12 GB, leaving headroom under the 22 GB budget.
- **Recommended global caps: ≤ 4 concurrent `dsh` sessions, ≤ 8 MCP server processes machine-wide, ≤ 6 concurrent subagent/tool subprocesses per session, ≤ 24 concurrent short-lived Node processes machine-wide.** These are derived, not copied; the verification procedure in the last section is how you confirm or correct them.

## 3.3 How to enforce a *global, cross-process* cap on Windows

Ranked by friction on this stack.

1. **A tiny broker/supervisor process (recommended).** One long-lived Node process owns an integer semaphore and hands out leases over a **named pipe** (`\\.\pipe\dsh-gov`) via `net.createServer`/`net.connect`. Pure Node, no native addon, no filesystem, works across sessions and across every node process on the machine, and it can *also* be the single writer for the SQLite database and the journal (Q5), and the process-tree reaper. Evidence that named pipes are the right Windows IPC here: [creation of a console](https://learn.microsoft.com/en-us/windows/console/creation-of-a-console) is irrelevant to pipes, but MCP's own docs list "Unix domain sockets or TCP" as first-class transports and on Windows named pipes are the equivalent primitive ([MCP transports](https://modelcontextprotocol.io/docs/concepts/transports)). Verification: the broker's build must fail closed — if the broker dies, leases must time out rather than leak.
2. **Windows named semaphore.** The kernel primitive designed for exactly this: `CreateSemaphoreA` with a name and an `lMaximumCount`; openers get a handle to the *existing* object and `GetLastError` returns `ERROR_ALREADY_EXISTS`. Names can use a `Global\` or `Local\` prefix; the name space is shared with events, mutexes, waitable timers, jobs and file mappings, so a name collision with any of those returns `ERROR_INVALID_HANDLE` ([CreateSemaphoreA](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createsemaphorea)). **Caveat: Node has no built-in binding for this.** Using it requires a native addon or a helper executable, which is why the broker ranks first.
3. **Job Objects** — the correct tool for *bounding and reaping a tree*, less good as a counter. Documented capabilities that matter here: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (*"closing the last job object handle terminates all associated processes and then destroys the job object itself"*), per-process working-set limits, and the note that *"If a process associated with a job attempts to increase its working set size or process priority from the limit established by the job, the function calls succeed but are silently ignored."* CPU rate control supports a **hard cap** (`JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP`, `CpuRate` as *percent × 100* — *"After the job reaches its CPU cycle limit for the current scheduling interval, no threads associated with the job will run until the next interval"*) or a relative **weight** (1–9). Sources: [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [JOBOBJECT_CPU_RATE_CONTROL_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information), [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject). Two gotchas documented there: a process can only join a job if the new job is empty or in its existing nested-job hierarchy; and **assigning a process to a job with a memory limit does not account for memory it allocated before assignment**.
   - **This is the only mechanism in the list that hard-limits memory per process and reaps the whole tree on one handle close — but again, Node has no native binding; it needs a helper (.NET/PowerShell wrapper) to set up before launching `node.exe`.**
4. **Lock files with atomic create.** `fs.open(path, 'wx')` — *"Like `'w'` but fails if the path exists"* — and Node documents the Windows mapping: *"`O_EXCL|O_CREAT` to `CREATE_NEW`, as accepted by `CreateFileW`"* ([nodejs.org/api/fs.html](https://nodejs.org/api/fs.html)). This is a correct primitive for a *mutex*, not a counting semaphore: implement a cap of N with N fixed slot files and a retry loop with jitter. Important documented caveat: *"The exclusive flag might not work with network file systems."* Combined with the SQLite warning about buggy locking on network filesystems ([sqlite.org/faq.html](https://sqlite.org/faq.html) Q5), this means **the journal's lock must not live on a share**.
5. **`taskkill /T /F`** as the enforcement arm for whatever cap you choose — see 2.7.

- **MYTH / commonly repeated but wrong: "use a Windows named mutex from Node to cap concurrency."** Node core exposes no named-mutex or named-semaphore binding; every npm "global lock" package resolves to file-based locking, not kernel objects. Say so plainly rather than reaching for a native addon.
- **MYTH: "CI runners cap local parallelism a specific documented way."** No evidence found for a documented global local-concurrency cap in GitHub Actions or Azure Pipelines that maps onto this problem — they isolate by VM/container rather than by counting processes on one desktop.

---

# Q4. Keeping the desktop responsive while the fleet runs

## 4.1 Windows 11 Efficiency mode (EcoQoS) — the best-evidenced lever

**Claim: Efficiency mode lowers a process's base priority to low **and** applies EcoQoS. Microsoft measured foreground responsiveness improvements of 14%–76% on a CPU-contended system.**

- Evidence — [Reduce Process Interference with Task Manager Efficiency Mode](https://devblogs.microsoft.com/performance-diagnostics/reduce-process-interference-with-task-manager-efficiency-mode/) (Microsoft DevBlogs, Performance & Diagnostics): *"When Efficiency mode is enabled on a process, it a) reduces process base priority to low, and b) sets QoS mode to EcoQoS. Low priority ensures that this process does not interfere with higher priority processes that the user is actively using. EcoQoS ensures the process is executed in the most power-efficient manner. This could mean running the processor at a lower frequency to save power… We see up to 4x improvements (or ~76% reduction, see below) in UI responsiveness on a CPU contended system."* Method: synthetic CPU workload on a normal-priority thread per core at 100%, measuring app launch and Start Menu open times, *"normalized to the baseline completion times without the CPU load"*. Result: *"14% ~ 76% across the common scenarios we tested."*
- Programmatic equivalent ([Quality of Service](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)): the QoS table lists **Eco** — *"Applications that explicitly tag processes with SetProcessInformation or threads with SetThreadInformation"*, *"Always selects most efficient CPU frequency and schedules to efficient cores"*, released with **Windows 11**. Also **Utility** (background services, Windows 11 22H2). Mechanism per [SetProcessInformation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation) with `ProcessPowerThrottling` and a [PROCESS_POWER_THROTTLING_STATE](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-process_power_throttling_state) whose `ControlMask`/`StateMask` are set to `PROCESS_POWER_THROTTLING_EXECUTION_SPEED`; per-thread equivalent via [SetThreadInformation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setthreadinformation) with `THREAD_POWER_THROTTLING_EXECUTION_SPEED`. Microsoft's own guidance: *"EcoQoS should be used when the work is not contributing to the foreground user experience… EcoQoS should not be used for performance critical or foreground user experiences."*
- Applies here: **this is the highest-value, lowest-risk change in the whole report.** On a hybrid Core Ultra 7 155H, "schedules to efficient cores" has a real mechanical meaning — the fleet moves off the P-cores the human is typing on. The 76% figure is Microsoft's own measurement of *this* metric (foreground responsiveness under CPU contention), which is precisely the reported symptom ("the UI feels frozen").

## 4.2 Priority classes and background mode

**Claim: `IDLE_PRIORITY_CLASS` and `BELOW_NORMAL_PRIORITY_CLASS` are real, and `PROCESS_MODE_BACKGROUND_BEGIN` lowers resource scheduling priorities (CPU **and** I/O) for a process and its threads. It can only be applied to the *current* process.**

- Evidence: [SetPriorityClass](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setpriorityclass) — `IDLE_PRIORITY_CLASS` = *"Process whose threads run only when the system is idle… The idle-priority class is inherited by child processes."*; `BELOW_NORMAL_PRIORITY_CLASS` = *"above IDLE but below NORMAL"*; `PROCESS_MODE_BACKGROUND_BEGIN` = *"The system lowers the resource scheduling priorities of the process (and its threads) so that it can perform background work without significantly affecting activity in the foreground."* Documented constraint: *"This value can be specified only if `hProcess` is a handle to the current process."*
- Two useful consequences: **`IDLE_PRIORITY_CLASS` is inherited by children**, so setting it once at the top of a session makes the whole subtree idle-priority; and background mode is *I/O* priority as well as CPU, which matters far more than CPU here.
- Applies here: prefer **`BELOW_NORMAL` + EcoQoS** over `IDLE` for the agent fleet. `IDLE` can starve the fleet's own I/O behind unrelated background work and make tool calls time out; `BELOW_NORMAL` + EcoQoS is the documented combination that Microsoft's own Efficiency-mode numbers were measured with.

## 4.3 Affinity

**Claim: `SetProcessAffinityMask` restricts a process's threads to a set of logical processors; on a machine with >64 processors additional rules apply.**

- Evidence: [SetProcessAffinityMask](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setprocessaffinitymask) — the mask is applied to *the threads of the process*; *"On a system with more than 64 processors, the affinity mask must specify processors in a single processor group"*; since Windows 11/Server 2022, process and thread affinities span all processor groups by default.
- Applies here: **use affinity only as a blunt instrument, and prefer EcoQoS first.** On this 22-thread hybrid chip you could pin the fleet to the E-core set and leave P-cores free, which is mechanically the strongest guarantee of desktop responsiveness. The costs are real: Node has no binding for it, so it needs a helper; and pinning to E-cores permanently caps the fleet's throughput even when the human is away. **EcoQoS achieves most of the benefit and is reversible at runtime; affinity is not.** Recommended only if EcoQoS + BELOW_NORMAL measurably fail.

## 4.4 "Efficiency mode" from the shell — what actually works, and a myth

**Claim: PowerShell's `Start-Process` has no `-Priority` parameter. Verified on this machine.**

- Evidence: measured on this laptop, PowerShell **7.6.6**: `(Get-Command Start-Process).Parameters.Keys` filtered for priority/window/wait returns exactly **`NoNewWindow`, `PassThru`, `WindowStyle`, `Wait`**. [Start-Process reference](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process) documents `-WindowStyle` and `-Environment` but no priority parameter.
- **MYTH: "use `Start-Process -Priority Idle` to background a fleet."** The parameter does not exist in PowerShell 7.6.6 and the command will fail. Equally, **`wmic process … setpriority` is not a safe recommendation on Windows 11** — WMIC is deprecated and absent on current builds.
- What *does* work, in increasing order of friction: (a) set the priority **inside** the Node process at startup — Node cannot call `SetPriorityClass`, but it can shell to a helper once, or on Windows use a tiny native binding; (b) `(Get-Process -Id $p.Id).PriorityClass = 'Idle'` immediately after `Start-Process -PassThru` — works, but is racy: the process runs at normal priority for a moment, and any children it spawned in that window inherited normal priority; (c) **the reliable route: a small helper (`dsh-fleet.exe`/PowerShell wrapper calling `CreateProcess` in a Job with the desired limits, or `SetPriorityClass` + `SetProcessInformation`) launched *before* the fleet's root process, so every descendant inherits the class**; this also lets you use `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` as the tree-reaper. This is the only route that composes with the Q3 architecture, and it is why the broker/helper keeps appearing.

---

# Q5. SQLite and file locks under concurrency

## 5.1 The single most important sentence in the SQLite docs

**Claim: starting a write transaction with `BEGIN IMMEDIATE` instead of `BEGIN` guarantees no `SQLITE_BUSY` for the rest of that transaction.**

- Evidence: [sqlite.org/rescode.html](https://sqlite.org/rescode.html) §5 — *"An `SQLITE_BUSY` error can occur at any point in a transaction: when the transaction is first started, during any write or update operations, or when the transaction commits. To avoid encountering `SQLITE_BUSY` errors in the middle of a transaction, the application can use `BEGIN IMMEDIATE` instead of just `BEGIN` to start a transaction. The `BEGIN IMMEDIATE` command might itself return `SQLITE_BUSY`, but if it succeeds, then SQLite guarantees that no subsequent operations on the same database through the next `COMMIT` will return `SQLITE_BUSY`."*
- Applies here: **this is the fix for "database is locked" in DSH's writers.** A retry wrapper around `BEGIN IMMEDIATE` is bounded and safe; a retry wrapper around a deferred transaction is the bug.

## 5.2 What actually causes "database is locked"

**Claim: `SQLITE_BUSY` means a conflict with a *separate connection/process*; `SQLITE_LOCKED` means a conflict within the same connection. The classic multi-process cause is a deferred read transaction being upgraded to a write.**

- Evidence: [rescode.html](https://sqlite.org/rescode.html) — *"The `SQLITE_BUSY` result code differs from `SQLITE_LOCKED` in that `SQLITE_BUSY` indicates a conflict with a separate database connection, probably in a separate process, whereas `SQLITE_LOCKED` indicates a conflict within the same database connection."* And, for the exact upgrade scenario: *"If a write statement occurs while a read transaction is active, then the read transaction is upgraded to a write transaction if possible. If some other database connection has already modified the database or is already in the process of modifying the database, then upgrading to a write transaction is not possible and the write statement will fail with `SQLITE_BUSY`."* ([lang_transaction.html](https://sqlite.org/lang_transaction.html) §2.1). In WAL the same situation surfaces as the extended code `SQLITE_BUSY_SNAPSHOT` ([rescode.html](https://sqlite.org/rescode.html) §517). *"If the first statement after `BEGIN DEFERRED` is a SELECT, then a read transaction is started."*
- Applies here: any DSH code path that does `BEGIN` → `SELECT` (check existing row) → `INSERT/UPDATE` is a guaranteed source of intermittent "database is locked" under 10 concurrent sessions. Audit for it; convert every such path to `BEGIN IMMEDIATE`.

## 5.3 WAL — what it buys, and its hard constraints

**Claim: WAL lets readers and writers proceed concurrently and reduces fsyncs, but it requires all processes to be on the same host and does not work over a network filesystem; it still can return `SQLITE_BUSY` in enumerated cases; and a WAL-reset corruption bug existed until 3.51.3.**

- Evidence: [sqlite.org/wal.html](https://sqlite.org/wal.html) — *"All processes using a database must be on the same host computer; WAL does not work over a network filesystem. This is because WAL requires all processes to share a small amount of memory."* *"It is not possible to open read-only WAL databases"* without write access to the `-shm` file or the containing directory. *"WAL might be very slightly slower (perhaps 1% or 2% slower) than the traditional rollback-journal approach in applications that do mostly reads and seldom write."* §9 enumerates the cases where a WAL query can still return `SQLITE_BUSY`: another connection has the database open in **exclusive locking mode**; *"When the last connection to a particular database is closing, that connection will acquire an exclusive lock for a short time while it cleans up the WAL and shared-memory files. If a separate attempt is made to open and query the database while the first connection is still in the middle of its cleanup process, the second connection might get an `SQLITE_BUSY` error."*; and the first connection after a crash runs recovery.
- **Two facts that matter a lot here and are easy to miss:**
  1. **Chrome and Firefox open their databases in exclusive locking mode** — the docs say so explicitly, "so attempts to read Chrome or Firefox databases while the applications are running will run into this problem." If DSH ever touches a browser profile DB, that alone produces "database is locked".
  2. **The WAL-reset bug**: *"The bug is likely present in all version of SQLite from 3.7.0 (2010-07-21) through 3.51.2 (2026-01-09). It is fixed in version 3.51.3 (2026-03-13)… The bug only affects databases in WAL mode when there are two or more database connections open on the same file, in separate threads or processes, and when those two connections attempt to write or checkpoint at the same instant."* That is *exactly* this workload's shape.
- Applies here: **use WAL — it is the right mode for many readers and one writer on one host — but check the SQLite version in every stack, because a `node:sqlite`/`better-sqlite3` binary older than 3.51.3 puts a multi-process, multi-writer workload on a known corruption path.** Verify with `sqlite3 --version` or `select sqlite_version();`. If the bundled version is older and you cannot upgrade, the mitigation is a single writer connection owned by the broker (5.5), which also removes the "two connections write at the same instant" precondition.

## 5.4 `busy_timeout` and the journal-mode tradeoffs

**Claim: `PRAGMA busy_timeout` installs a busy handler per connection; only one busy handler exists per connection; SQLite's default behaviour on a locked file is to return `SQLITE_BUSY` immediately.**

- Evidence: [PRAGMA busy_timeout](https://sqlite.org/pragma.html#pragma_busy_timeout) — *"This pragma is an alternative to the `sqlite3_busy_timeout()` C-language interface… Each database connection can only have a single busy handler. This PRAGMA sets the busy handler for the process, possibly overwriting any previously set busy handler."* [sqlite.org/faq.html](https://sqlite.org/faq.html) Q5 — *"When SQLite tries to access a file that is locked by another process, the default behavior is to return `SQLITE_BUSY`. You can adjust this behavior… using the `sqlite3_busy_handler()` or `sqlite3_busy_timeout()` API functions."* Checkpoint modes and their blocking behaviour are documented under `PRAGMA wal_checkpoint` ([pragma.html](https://sqlite.org/pragma.html)): `PASSIVE` *"never invoked in this mode"* for the busy handler, `FULL` *"blocks concurrent writers while it is running, but readers can proceed"*, `RESTART`/`TRUNCATE` additionally block until readers finish.
- `synchronous`: [wal.html](https://sqlite.org/wal.html) §5 suggests running checkpoints in a separate thread so *"the main thread or process that is doing database queries and updates will never block on a sync operation. This helps to prevent 'latch-up' in applications running on a busy disk drive. The downside… is that transactions are no longer durable."* The FAQ warns `PRAGMA synchronous=OFF` *"will cause SQLite to not wait on data to reach the disk surface… But if you lose power in the middle of a transaction, your database file might go corrupt."*
- Applies here: set `busy_timeout` **and** `BEGIN IMMEDIATE` (belt and braces; the timeout covers the `BEGIN IMMEDIATE` itself, which is the one statement `BEGIN IMMEDIATE` cannot protect). Use `synchronous=NORMAL` in WAL. **Never `synchronous=OFF`** — this business has lost customer data twice and this is the exact command that loses it on power loss. Avoid `TRUNCATE`/`RESTART` checkpoints in a hot path; use `PASSIVE` and let the default auto-checkpoint run.

## 5.5 The architecture that actually removes "database is locked"

**Claim: SQLite's own guidance is that many concurrent writers are out of scope and that queuing (or a client/server engine) is the answer.**

- Evidence: [sqlite.org/whentouse.html](https://sqlite.org/whentouse.html) — *"Very large datasets…"* aside, the two relevant entries: *"High Concurrency — SQLite supports an unlimited number of simultaneous readers, but it will only allow one writer at any instant in time. For many situations, this is not a problem. Writers queue up. Each application does its database work quickly and moves on, and no lock lasts for more than a few dozen milliseconds. But there are some applications that require more concurrency, and those applications may need to seek a different solution."* And the decision checklist: *"Many concurrent writers? → choose client/server. If many threads and/or processes need to write the database at the same instant (and they cannot queue up and take turns) then it is best to select a database engine that supports that capability, which always means a client/server database engine. SQLite only supports one writer at a time per database file. But in most cases, a write transaction only takes milliseconds and so multiple writers can simply take turns. SQLite will handle more write concurrency than many people suspect."* Also: *"A good rule of thumb is to avoid using SQLite in situations where the same database will be accessed directly… simultaneously from many computers over a network"*, because *"file locking logic is buggy in many network filesystem implementations (on both Unix and Windows)."*
- Applies here: **keep SQLite, add the queue — do not migrate to PostgreSQL for this.** The measured shape (a handful of writes per tool call, 10 sessions) is *inside* SQLite's supported envelope. Route **all writes** through the broker from Q3.3, so the machine has exactly one writing connection; readers stay direct. This converts a statistical race into a serialized queue, which is the documented remedy, and it also removes the 3.51.3 WAL-reset precondition.
- The stated alternative, if you ever truly need simultaneous writers, is the documented one: move to the authoritative Postgres on `secratary` (which is where `owner_decision_queue` already lives). That is a decision about the *authoritative* store, not about the local journal.

## 5.6 Lock-file protocols that are safe on Windows

| Pattern | Verdict | Evidence |
|---|---|---|
| `open(path, 'wx')` / `O_EXCL` / `CREATE_NEW` — atomic exclusive create | **Safe on a local NTFS volume** | Node: *"'wx': Like 'w' but fails if the path exists"* and *"`O_EXCL\|O_CREAT` to `CREATE_NEW`, as accepted by `CreateFileW`"* ([fs.html](https://nodejs.org/api/fs.html)). Node's own caveat: *"The exclusive flag might not work with network file systems."* |
| `mkdir` as the lock | **Safe, and the better choice on shares** | [proper-lockfile](https://www.npmjs.com/package/proper-lockfile): *"This library utilizes the `mkdir` strategy which works atomically on any kind of file system, even network based ones."* It also documents exactly why `O_EXCL` is worse: *"It relies on `open` with `O_EXCL` flag which has problems in network file systems… `O_EXCL` is broken on NFS file systems; programs which rely on it for performing locking tasks will contain a race condition."* |
| Check-then-create (`exists()` then `writeFile()`) | **Unsafe — TOCTOU race** | Follows directly from the atomicity claims above; the whole point of `'wx'`/`mkdir` is to combine the check and the create. |
| Lock with no liveness signal | **Unsafe** | `proper-lockfile` documents that the naive version *"has a default value of `0` for the stale option which isn't good because any crash or process kill that the package can't handle gracefully will leave the lock active forever."* |
| Lock with a continuously-refreshed `mtime` + stale threshold | **Safe, and the recommended shape** | `proper-lockfile`: *"When a lock is successfully acquired, the lockfile's `mtime` … is periodically updated to prevent staleness. This allows to effectively check if a lock is stale by checking its `mtime` against a stale threshold."* Defaults: `stale` = 10000 ms (min 5000), `update` = `stale/2` (min 1000, max `stale/2`), `retries` = 0. |
| Using `ctime` for staleness | **Unsafe for long-running processes** | `proper-lockfile`: the older `lockfile` package *"staleness check is done via `ctime` (creation time) which is unsuitable for long running processes."* |
| Unbounded retry / spin-wait | **Unsafe** | Not a documented recommendation anywhere; and here it is the mechanism that turns a lock conflict into a "hung tool call". Bound the retry, then fail loudly. |
| Locks on a network share / SMB, or a DB on `/mnt/c` from WSL | **Unsafe** | Node: exclusive flag "might not work" on network FS. SQLite: locking logic *"is buggy in many network filesystem implementations (on both Unix and Windows)"* ([whentouse.html](https://sqlite.org/whentouse.html), [faq.html](https://sqlite.org/faq.html)). Also reported in the wild: WAL failing entirely on WSL2 when the DB is on the Windows filesystem ([beads#920](https://github.com/gastownhall/beads/issues/920)). |

- Applies here: **the journal's lock file is almost certainly the cause of the reported "lock files on the journal" symptom**, and the fix is a small, known-correct protocol: atomic create (`'wx'` on the local NVMe; `mkdir` if the journal ever lives on a share), owner PID + hostname + timestamp written into the lock file, `mtime` heartbeat, stale threshold, bounded retries with jitter, and a stale-lock breaker that only fires on an expired heartbeat. `proper-lockfile` already implements all of this; use it rather than hand-rolling. **But note it is still a mutex, not a cap** — the cap belongs to the broker (Q3.3). Do not add a second, independent locking scheme for the same resource.

---

# Q6. Prior art — this exact failure, already reported by other people

## 6.1 The closest match: OpenAI Codex on Windows (MCP process generations never reaped)

**Claim: a Windows agent app accumulated ~17 complete generations of every configured MCP/runtime process, and the machine reached 764 processes / 418,237 handles / ~54.3 GB of a 59.9 GB commit limit, with severe UI stutter and an OS bugcheck. Root cause was lifecycle reuse, not a single leaking heap. `taskkill /PID … /T /F` was a working live mitigation.**

- Evidence: [openai/codex#38754 "[Windows Codex app] Local stdio MCP servers are repeatedly spawned and not reaped within a single task"](https://github.com/openai/codex/issues/38754). Quoted: *"The Codex process tree had accumulated exactly 17 copies of several configured local MCP/runtime processes. Direct children of the Codex process roots included: 51 `npx.exe` / 17 `node.exe` / 17 `node_repl.exe` / 17 `python.exe`"*; *"764 processes / 418,237 handles / 46.04 GiB aggregate process private bytes / ~54.3 GiB committed out of a ~59.9 GiB commit limit / ~3.8 GiB physical memory available"*; *"This does not look like a single leaking Node heap. It looks like complete MCP/runtime generations are being created repeatedly and retained instead of being reused or reaped."* Root cause per the reporter: reconciliation not reusing a pending MCP connection while its startup was still pending, plus a one-way `terminated` flag whose second caller could return before the first finished cleanup, plus signal failures logged as success. Also in the duplicate list from the same tracker: **#38526** (local STDIO MCP process groups accumulate and consume **~7 GB RAM**), **#38537** (VS Code extension "one full set per session, never reaped — **up to 490 processes / 26.5 GB observed**"), **#38693** (subagents leave unused stdio MCP process trees), **#38714** ("CUA node_repl workers remain … and correlate with system-wide UI stalls").
- Applies here: **this is the same shape as the reported symptom set, on the same OS.** Note the numbers: the failing machine had *fewer* process generations than this fleet's described configuration (10 sessions × multiple MCP servers), and it hit commit exhaustion. The implication is that DSH's MCP lifecycle must be checked for **reuse of a pending connection** and for **cancellation-safe shutdown with a shared completion flag** before anything else is tuned.

## 6.2 Subagents that leak Node processes

**Claim: agent subagents spawn Node processes that do not exit when the agent finishes, accumulating 60+ processes on a Windows 11 machine.**

- Evidence: [anthropics/claude-code#11502 "Subagents don't clean up their Node processes"](https://github.com/anthropics/claude-code/issues/11502) (closed as duplicate of #11046) — *"Process accumulation (60+ zombie Node processes after moderate usage) / Memory exhaustion (individual processes grow to 295MB+) / System slowdown… / Processes only terminate when explicitly killed (taskkill)"*, platform: Windows 11.
- Applies here: **DSH's subagent teardown needs the same audit**, and the platform-specific part is directly actionable: because Windows `kill()` does not kill trees (2.7), the leak is the expected default behaviour rather than a surprise. Add an orphan reaper that periodically enumerates `node` processes whose parent is gone and tree-kills them.

## 6.3 Multi-session multiplicative blow-up, with the mitigations already spelled out

**Claim: with N sessions and M MCP servers, hosts spawn up to N×M Node processes with no heap cap; a 64 GB machine kernel-panicked at 15 sessions × 34 servers.**

- Evidence: [anthropics/claude-code#45880 "[BUG] Multiple concurrent sessions multiply MCP server processes without memory limits, causing kernel panic"](https://github.com/anthropics/claude-code/issues/45880) — *"With N sessions and M configured MCP servers, the system spawns up to N×M node processes with no memory cap. On a 64 GB MacBook Pro, 15 concurrent sessions with 34 configured MCP servers caused a hardware watchdog kernel panic twice in one evening… (12 sessions + 308 node processes = 111 GB total → kernel panic)"*. Their proposed mitigation list, verbatim: **(1)** set `NODE_OPTIONS=--max-old-space-size=256` on MCP server child processes — *"the single highest-impact fix"*; **(2)** share MCP server instances across sessions; **(3)** lazy-start MCP servers; **(4)** clean up MCP processes on session end; **(5)** expose a global config setting for MCP server memory limits; **(6)** warn or refuse when the total MCP server process count would exceed a threshold.
- Applies here: **that is a ready-made spec for DSH's own governor, and it names the exact knob (`--max-old-space-size` on MCP children) that the Q1 analysis independently selected.** Also note their arithmetic sanity check — *"Even if each node process only reaches 200 MB (modest), that's 510 × 200 MB = 102 GB"* — which is the same budget method used in Q3.2.

## 6.4 MCP process sprawl is structural — 1 client : 1 subprocess for stdio

**Claim: MCP's stdio transport is a client-launched subprocess, so process count scales 1:1 with clients unless the server uses Streamable HTTP (or the host implements pooling). A host cannot dedupe stdio servers whose `args` differ.**

- Evidence: [MCP transports overview](https://modelcontextprotocol.io/docs/concepts/transports) — *"stdio: newline-delimited messages over the standard streams of a client-launched subprocess"*; *"Streamable HTTP: each message is an HTTP POST to a single MCP endpoint"*; and, for custom transports, *"the stdio binding is just newline-delimited JSON-RPC over a byte stream, and only its process-lifecycle rules are specific to standard streams."* The pooling gap is documented from the host side in [claude-code#63749](https://github.com/anthropics/claude-code/issues/63749): a machine with ~15 plugins wrapping the same MCP binary produced *"60 subprocesses of the same binary / ~5.7 GiB total RSS"*, with the explicit architectural note that *"The MCP spec defines stdio as 1 client : 1 subprocess; there's no in-protocol multiplexing for stdio. This is therefore explicitly a host-level orchestration concern"* — and their conclusion that *"Streamable HTTP transport… is the cleanest path for servers that can run as HTTP."* They also cite an adjacent issue: *"[BUG] Multiple concurrent sessions multiply MCP server processes without memory limits"* (#45880, above).
- Applies here: **the durable structural fix for DSH is one shared MCP server per tool family, reached over Streamable HTTP or a named pipe, with per-instance tool filtering done host-side.** Until that exists, the governor's per-family process cap is the only defence.

## 6.5 Do published "agents per GB of RAM" caps exist?

**Claim: no evidence found for a published, measured "2–4 concurrent agents per 16 GB RAM" rule.** The documented defaults in the wild are all CPU-derived (Q3.1), and every real-world RAM number found (7 GB, 26.5 GB, 46 GB private bytes, 111 GB total) was reported as a *post-mortem measurement of a failure*, not a design budget. The defensible approach is the derived budget in Q3.2 plus the counters in the final section, not a borrowed rule.

## 6.6 One more piece of prior art worth noting

**Claim: hosts have repeatedly had to fix "console window flashes" caused by core-side spawns on Windows** — [openhuman#1498](https://github.com/tinyhumansai/openhuman/pull/1498). Supporting evidence that §2.2 is a real, recurring defect class rather than a theoretical concern.

---

# Recommended settings for this machine

Ordered by expected effect per unit of risk. Each row: action → expected effect → source.

### Tier 1 — do these first (largest effect, lowest risk)

**1. Enforce a global process cap so commit charge cannot exceed physical RAM.**
Cap: **≤ 4 concurrent `dsh` sessions, ≤ 8 MCP server processes machine-wide, ≤ 6 concurrent subagent/tool subprocesses per session, ≤ 24 concurrent short-lived Node processes machine-wide.** Implement as the broker from §3.3 (one Node process on a named pipe handing out leases). Expected effect: this is the only change that *directly* fixes the reported symptom — commit 39.43 GB against 31.6 GB physical is the thrash, and 831 hard faults/s is what makes `dwm` look frozen.
*Source:* derived from measured commit limit/charge (§3.2) using the budget method in [claude-code#45880](https://github.com/anthropics/claude-code/issues/45880); the "warn or refuse above a threshold" idea is their mitigation (6).

**2. Fix MCP process lifecycle: reuse pending connections, and make shutdown cancellation-safe.**
Before tuning anything, audit for the exact two defects found in [codex#38754](https://github.com/openai/codex/issues/38754): (a) a connection refresh that spawns a duplicate while a previous startup is pending; (b) a one-way `terminated` flag where a second shutdown caller can return before cleanup completes. Expected effect: turns unbounded N×M growth into a bounded set. **This is prior art for the same OS and the same architecture; treat it as the highest-probability root cause.**
*Source:* [codex#38754](https://github.com/openai/codex/issues/38754); corroborated by [claude-code#11502](https://github.com/anthropics/claude-code/issues/11502), [#45880](https://github.com/anthropics/claude-code/issues/45880), [#63749](https://github.com/anthropics/claude-code/issues/63749).

**3. Cap every MCP server's heap and every session's process count in config.**
Set `NODE_OPTIONS=--max-old-space-size=256` on all MCP children; add a startup warning (and a hard refusal threshold) when the machine-wide MCP process count exceeds 8. Expected effect: bounds the *resident* population, which is the part that actually occupies commit.
*Source:* [claude-code#45880](https://github.com/anthropics/claude-code/issues/45880) calls this *"the single highest-impact fix"*; flag semantics from [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html).

**4. Kill process trees on Windows, always.**
Replace every `child.kill()` teardown with `taskkill /PID <pid> /T /F`. Add a periodic orphan reaper for `node` processes whose parent is gone. Expected effect: stops the leak that produces the accumulation pattern in §6.1–6.3.
*Source:* [nodejs.org/api/child_process.html](https://nodejs.org/api/child_process.html) (signals on Windows; killing a shell does not kill its children) and [taskkill](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill); the workaround is verbatim from [codex#38754](https://github.com/openai/codex/issues/38754).

**5. Replace every `npx -y pkg@latest` with a pinned, pre-installed launch.**
Install MCP packages once; invoke `node <abs path to entry>.js`. Never route a hot path through `@latest`.
*Source:* [npm npx docs](https://docs.npmjs.com/cli/v10/commands/npx) (specifier must match name **and exact version** to reuse a local install; otherwise installed into the cache). Measured on this laptop: `npx --version` **4,061.6 ms** vs `node -v` **964.6 ms**; [codex#38754](https://github.com/openai/codex/issues/38754) counted 51 `npx.exe`. Expected effect: removes ~3 s of npm boot plus one registry round-trip per MCP server per session.

**6. `windowsHide: true` on every spawn; never `shell: true`; never a `.cmd` shim.**
*Source:* [child_process.html](https://nodejs.org/api/child_process.html) — `windowsHide` *"Default: `false`"*, and `shell` defaults to `process.env.ComSpec` on Windows; `.bat`/`.cmd` cannot be launched without a shell. Measured on this laptop: 15 `conhost.exe` for 52 `node` processes. Expected effect: fewer console hosts, less `dwm` compositing work, one fewer `cmd.exe` per call that would otherwise use a shim.

### Tier 2 — do these next (high effect, small config cost)

**7. Turn on the V8 compile cache machine-wide.**
`NODE_COMPILE_CACHE=<fixed local dir>`, plus `module.flushCompileCache()` in long-lived parents. Clear the cache on every Node upgrade. Expected effect: upstream measured **~130 ms → ~80 ms** per module graph; locally 1,280 ms → 1,028 ms for `node -e ""` (loaded machine, n=6, directional). Biggest relative win on the MCP servers and CLI entry points.
*Source:* [nodejs.org/api/module.html](https://nodejs.org/api/module.html); [nodejs/node#52535](https://github.com/nodejs/node/pull/52535).

**8. Apply Microsoft Defender exclusions — measurably, not by guesswork.**
First run `Get-MpPerformanceReport` during a fleet run to get evidence. Then add **path** exclusions (not extension exclusions, not bare filenames) for: repo root, git worktree root, npm cache, journal + SQLite directory, and the compile-cache directory. Long-term, move these onto a **Dev Drive** with Defender **performance mode** instead — that preserves protection. Expected effect: removes per-file-open scanning from the hot path of thousands of small reads/writes.
*Source:* [configure custom exclusions](https://learn.microsoft.com/en-us/defender-endpoint/configure-exclusions-microsoft-defender-antivirus); [exclusions in MDAV](https://learn.microsoft.com/en-us/defender-endpoint/configure-extension-file-exclusions-microsoft-defender-antivirus) (use sparingly; full paths; process exclusions also disable network protection/ASR for that process); [performance analyzer](https://learn.microsoft.com/en-us/defender-endpoint/tune-performance-defender-antivirus); [Dev Drive + Defender performance mode](https://learn.microsoft.com/en-us/windows/dev-drive/) (build 22621.2338+, 50 GB min; **C: cannot be a Dev Drive**).

**9. Put the whole fleet in BELOW_NORMAL priority + EcoQoS at launch.**
Set it on the fleet's root process so it is inherited, from a helper launched *before* the fleet. Expected effect: Microsoft measured **14%–76% improvement in foreground responsiveness** on a CPU-contended system with exactly this mechanism; on a hybrid P/E chip EcoQoS also moves the fleet to E-cores.
*Source:* [Efficiency mode DevBlog](https://devblogs.microsoft.com/performance-diagnostics/reduce-process-interference-with-task-manager-efficiency-mode/); [Quality of Service](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service); [SetPriorityClass](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setpriorityclass) (`IDLE_PRIORITY_CLASS` *"is inherited by child processes"*; `PROCESS_MODE_BACKGROUND_BEGIN` lowers CPU **and** I/O priority but only for the current process); [SetProcessInformation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation) + [PROCESS_POWER_THROTTLING_STATE](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-process_power_throttling_state).
**Do not** reach for `Start-Process -Priority` — measured on PowerShell 7.6.6, `Start-Process` has no such parameter. Prefer `BELOW_NORMAL` + EcoQoS over `IDLE`, which can starve the fleet's own I/O and cause timeouts.

**10. Fix all SQLite writes.**
On every connection: `PRAGMA journal_mode=WAL;` (once), `PRAGMA busy_timeout=5000;`, `PRAGMA synchronous=NORMAL;`. Replace every `BEGIN` that will write with `BEGIN IMMEDIATE`. Route all writes through the single broker connection; readers stay direct. Verify `sqlite_version() >= 3.51.3`. Never place the DB on a network share. Expected effect: eliminates the "database is locked" class, not just its frequency.
*Source:* [rescode.html](https://sqlite.org/rescode.html) (the `BEGIN IMMEDIATE` guarantee; `SQLITE_BUSY` vs `SQLITE_LOCKED`; `SQLITE_BUSY_SNAPSHOT`); [lang_transaction.html](https://sqlite.org/lang_transaction.html) §2.1–2.2; [pragma.html --busy_timeout](https://sqlite.org/pragma.html#pragma_busy_timeout); [wal.html](https://sqlite.org/wal.html) (same-host + no-network-FS requirement; §9 `SQLITE_BUSY` cases; the **WAL-reset bug fixed in 3.51.3**); [whentouse.html](https://sqlite.org/whentouse.html) (many concurrent writers → queue or client/server).

**11. Replace the journal's lock protocol.**
Atomic create (`fs.open(path,'wx')` on local NVMe, `mkdir` if ever on a share), owner PID+host in the file, `mtime` heartbeat, stale threshold, bounded retries with jitter, and a stale-breaker. Use `proper-lockfile` rather than hand-rolling. Fail loudly on timeout instead of retrying forever — an unbounded retry is what turns a lock conflict into a "hung or blank tool call". Expected effect: removes the journal lock symptom and converts residual contention into a visible error.
*Source:* [fs.html](https://nodejs.org/api/fs.html) (`'wx'`; `O_EXCL|O_CREAT`→`CREATE_NEW`; *"might not work with network file systems"*); [proper-lockfile](https://www.npmjs.com/package/proper-lockfile) (why `mkdir` beats `O_EXCL`; why `ctime` staleness is wrong; why a `stale` default of 0 is wrong).

### Tier 3 — cheap hardening

**12. Set `UV_THREADPOOL_SIZE=8` in the launcher environment** (default is 4; `fs`, `crypto`, `dns.lookup`, and `zlib` all share it). This is a plausible mechanism for the reported hangs. *Source:* [nodejs.org/api/cli.html](https://nodejs.org/api/cli.html) §UV_THREADPOOL_SIZE. Must be set before launch — setting it from inside the process is documented as unreliable.

**13. Suppress known warning classes rather than all warnings:** `--disable-warning=ExperimentalWarning,DeprecationWarning` (allowed in `NODE_OPTIONS`). *Source:* [cli.html](https://nodejs.org/api/cli.html).

**14. Do not raise the pagefile as a "fix".** It is a safety valve, not a cure: the measured 44.30 GB commit limit on a 31.6 GB machine is already absorbing overcommit and converting a hard out-of-commit failure into sustained thrashing (831 hard faults/s). Set the cap in item 1 so the pagefile is never reached, and only then consider a larger fixed pagefile so that a future burst degrades to slowness rather than to failed allocations. *Source:* the measured commit limit/charge pair in the provenance table.

**15. Do not do these** (each is either a myth or unsupported here): change Node major version hoping for lower RAM (§1.1); `--max-old-space-size` on short-lived tool processes (§1.3); any `--max-semi-space-size` tuning (§1.4); `--jitless` or `--no-opt` (§1.5); `--snapshot-blob` in production (§1.6); `Start-Process -Priority` (§4.4); `wmic` for priority; `synchronous=OFF`; SQLite on a share or WSL `/mnt/c`; and any "N agents per GB" rule of thumb (§6.5).

### Verify the fix with the same counters that diagnosed it

Before and after, run under load:

```powershell
$c = Get-Counter '\Memory\Committed Bytes','\Memory\Commit Limit','\Memory\Available MBytes','\Memory\Pages Input/sec'
$c.CounterSamples | ForEach-Object { '{0} = {1:N0}' -f $_.Path, $_.CookedValue }
(Get-Process).Count
(Get-Process -Name node -ErrorAction SilentlyContinue).Count
(Get-Process -Name conhost -ErrorAction SilentlyContinue).Count
```

Success criteria, stated as measurements rather than assurances:
1. **commit charge < 31.6 GB** (below physical RAM) at steady state under a full fleet run;
2. **`Pages Input/sec` below ~100/s** (this machine measured 831/s);
3. **`node` process count flat over a 30-minute run** (not growing) — this is the leak test from §6.1;
4. **`conhost` count near-constant** after the `windowsHide` change;
5. **zero "database is locked"** and **zero lock-timeout hangups** in the log for the same 30 minutes;
6. **foreground responsiveness**: the Microsoft method from the Efficiency-mode blog — time Start Menu open under the fleet load and report the delta.

If (1) holds but (3) still grows, the MCP lifecycle defect in item 2 is the cause, not the cap. If (1) holds, (3) is flat, and the desktop is *still* unresponsive, escalate to Tier-2 item 9 then affinity (§4.3) — and only then.
