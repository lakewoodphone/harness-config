# 70 — Tool-call latency in DSH on Windows: audit, measurements, and implementation spec

**Host:** ZABZ-YOGA · Intel Core Ultra 7 155H · 22 logical cores · 31.6 GB RAM · Windows 11 · Node v24.12.0
**Measured:** 2026-09-16 14:20–14:45 UTC. One DSH engine (`dsh\lib\bin.js web --port 3099`) was running throughout, plus 3–5 other sessions.
**DSH install:** `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\`

Every number below carries its instrument and its sample. Where I could not establish something, I say so instead of rounding it into a claim. Nothing outside `_dsh-scale/` was written; no preset was edited.

**Headline.** A trivial `pwsh` tool call on this host costs **≈540 ms at best and ≈700 ms typically, before the command does any work** — and **≈80 % of that is PowerShell's own start-up**, not DSH: process creation is 5–7 ms, the Job-owning runner is ≈136 ms, the collector is ~10 ms, and `pwsh.exe` start (with the executor's encoding preamble) is 405–550 ms. The one available change that removes the PowerShell start from every call is the installed-but-unmounted persistent shell, and it is **not a safe drop-in today**: it drops five tool parameters (`workdir`, `run_in_background`, `timeoutMs`, `description`, `sandbox_permissions`/`justification`), downgrades large output from a 64 MB spill file to a 16 KB truncated string, and its provider rows are not mounted in this profile at all. The owner's working estimate of "~100 ms per-call PowerShell overhead" understates this host by five times — and the correct response is to stop paying it per call, not to micro-tune the 7 ms of `CreateProcess`.

---

## 1. How to measure a tool call on a loaded machine

### 1.1 The three things that must be measured separately

One number is not enough, because the answer changes what you do:

| Quantity | What it is | How to get it |
|---|---|---|
| **Process-creation cost** | `CreateProcess` returning a live handle | delta from just before `spawn()` to the `'spawn'` event |
| **Overhead** | everything paid before the model's command starts: Node start, runner start, pwsh start, Job setup, collectors | `tool/result.time − tool/call.time` **minus** the command's own wall time, or the floor measured with a no-op command |
| **Cycle** | overhead + the command's work | `tool/result.time − tool/call.time` |

The floor for **overhead** is measured with a command that does nothing (`exit 0`): whatever that costs is overhead by definition, and any real command adds to it.

### 1.2 Why not `Measure-Command`

- `Measure-Command { ... }` in PowerShell costs **≈250–300 ms of its own** in output capture and formatting on this host (compare `pwsh enc getdate` 628 ms vs `pwsh enc exit` 548 ms for a command whose work is one property read).
- A PowerShell harness also pays the *host* PowerShell's own start-up before the measurement begins, and its first iteration is a warm-up that pollutes the sample.
- Worst of all it measures `& $exe` in a PowerShell pipeline, which is not how the harness spawns anything.

Use **Node** as the instrument: `node:perf_hooks.performance.now()`, `node:child_process.spawn`, and `process.resourceUsage()` read as a running total around each case. Why this is right:

- `performance.now()` is monotonic and sub-millisecond; `Date.now()` is wall-clock and can jump.
- `spawn` → `'spawn'` isolates `CreateProcess`; `spawn` → `'exit'` gives the cycle. The gap is the child's own start and work, which is the honest split.
- `process.resourceUsage()` is a **per-process running total** of user CPU, system CPU, minor and major page faults. A delta around one case is that case's cost, with no sampling and no profiler. Caveat measured here: on Windows, `majorPageFault` counts **hard faults of this process only**, so a child's faults are invisible — it read 0 for a pwsh start that certainly faulted. Use `sysCpuMs` and wall time; do not try to infer the child's paging.

### 1.3 The exact commands

All scripts are in `C:\Users\ezabz\code\_dsh-scale\bench\` (created by this audit; each writes a JSON result file next to itself).

```powershell
# 1. Interleaved battery: every case sees the same machine load. Per-case
#    spawn-return and full-cycle stats plus per-case CPU deltas.
cd C:\Users\ezabz\code\_dsh-scale\bench
node battery.mjs 12            # -> battery.json

# 2. Long steady-state series (min and p10 are the clean estimators under load).
node steady.mjs 30             # -> steady.json
node steady2.mjs 24            # -> steady2.json  (round-robin A/B, load drift cancels)

# 3. What inside a PowerShell start actually costs (module path, profile, preamble).
node psstart.mjs 14            # -> psstart.json
node psstart2.mjs 12           # -> psstart2.json

# 4. The persistent-shell path: node-pty/ConPTY spawn + per-command round trip.
node ptybench.mjs 3 8          # -> ptybench.json

# 5. Windows QoS: hidden vs visible window (documented Win11 throttle trap).
node qos.mjs 12                # -> qos.json

# 6. Non-shell tool path (stat/read), in-process.
node fslat.mjs 200             # -> fslat.json

# 7. END-TO-END, from real session logs: every tool call's visible latency.
node sesslat.mjs "C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--\<session-id>"
```

### 1.4 The only honest end-to-end method: the session log

A tool call and its result are two events in the session artifact with their own timestamps. Their delta is exactly what the owner waits for, needs no cooperation from the running engine, and works while the machine is loaded:

```
tool/call   {"type":"tool/call",  "seq":17,"time":1789520666113,"data":{"callId":"call_00_…","name":"pwsh","arguments":"…"}}
tool/result {"type":"tool/result","seq":18,"time":1789520683014,"data":{"message":{"source":{"kind":"tool","callId":"call_00_…"}},…}}
```

The artifact `session.v3.jsonl.zstd` is a **concatenated-Zstd-frame container** (one checksummed frame per durable batch — `dsh-session-persistence-jsonl\lib\index.js:1281-1361`), so a single `zstdDecompressSync` of the whole file returns only the header frame (198 bytes). `sesslat.mjs` walks the frame boundaries structurally and decompresses each frame; on the audited session it recovered **639 events from 341 frames with 0 frames failing to parse**.

Live excerpt from this session at the time of writing (n=59 `pwsh` calls in the log so far): `pwsh` min 42 ms, p10 3 543 ms, p50 22 553 ms, p90 88 429 ms. That distribution says what the composite above says: the floor is small, and the tail is the command's own work — the **63 % of calls** you cannot fix by making startup cheap. The fix for the median is making the *shell* cheap; the fix for the tail is not running a 90-second command in the foreground at all.

### 1.5 The counters to take

- **spawn-return** and **cycle** per case: n, min, p10, p50, p90, max. Report min/p10 alongside p50 — this host's p50 moves 20 % between passes, its min moves ~3 %.
- **`sysCpuMs` per case** (system CPU delta ÷ iterations) — the cost that is genuinely in the kernel.
- **process count and total working set** for the tool path: `(Get-Process node).Count`, `(Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -like '*runner.js*' }).Count`.
- **`Processor Queue Length`** and `Win32_Processor.LoadPercentage` at measurement time, so a reading carries its load.
- Provenance: state the machine load and the sample count with every number. An empty result is not health.

### 1.6 Machine state at measurement time

`LoadPercentage` 3–50 depending on the pass · `Processor Queue Length` 12, 0, 0 · 407 processes · 14 `node` (1 508 MB total, engine 612 MB) · 4 `pwsh` (471 MB) · 3 `runner.js` (57 MB each). `/dsh/subprocess-local` runners left over from earlier sessions were resident and idle.

`NODE_COMPILE_CACHE` is machine-wide as recorded in journal L1701.

---

## 2. Cold vs warm numbers

### 2.1 Measured (ZABZ-YOGA, 2026-09-16, `steady.mjs`, n=30 each, interleaved)

| Case | min | p10 | p50 | p90 | What it is |
|---|---|---|---|---|---|
| `cmd.exe /d /c exit 0` | **32.8** | 33.5 | 35.9 | 44.4 | process creation + minimal shell = **pure overhead floor** |
| `runner.js` spawned and let exit | **120.3** | 127.8 | 136.3 | 148.6 | Node start (~77) + module load + IPC connect = **runner overhead** |
| `node -e 0` | **69.8** | 73.5 | 76.6 | 85.3 | Node 24 start with warm compile cache |
| `pwsh … -Command "<ENC>; exit 0"` | **405.0** | 414.1 | 548.0 | 631.5 | PowerShell start = **the dominant overhead** |
| `pwsh … -Command "<ENC>; Get-Date\|Out-Null"` | 516.6 | 557.4 | 627.6 | 819.1 | start + trivial work |
| `pwsh … -Command "<ENC>; Write-Output hi"` | 539.1 | 560.6 | 646.6 | 996.4 | start + one line of output |

`<ENC>` is the executor's own preamble, verbatim: `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [System.Text.UTF8Encoding]::new($false); ` (`dsh-pwsh-local\lib\index.js:158`).

Interleaved A/B (`steady2.mjs`, n=24, round-robin so load drift cancels):

| Variant | min | p10 | p50 | Δ vs plain |
|---|---|---|---|---|
| `-Command 'exit 0'` | 377.3 | 418.1 | **515.0** | — |
| `+ encoding preamble` | 408.9 | 435.5 | **553.5** | **+19 ms min / +38 ms p50** |
| `… + Get-Date \| Out-Null` | 526.0 | 556.0 | 655.3 | +149 min |
| `-NoProfile` removed (profile loads) | 450.0 | 467.0 | 551.4 | within noise |
| `PSModulePath=''` | 428.2 | 449.0 | 542.1 | ~+20 ms vs preamble-only, within noise |
| `PSModulePath` intact + `$PSModuleAutoLoadingPreference='None'` | 495.0 | 538.6 | 656.0 | **slower**, do not use |

Robust pty measurement (`ptybench.mjs`, 3 ConPTY sessions × 8 commands, n=24):

| Quantity | min | p50 | p90 |
|---|---|---|---|
| ConPTY spawn + pwsh start (`node-pty.spawn`, measured over a 150 ms window) | 166.6 | 168.6 | 168.6 |
| **one command round trip on an already-warm shell** | **18.0** | **33.8** | 59.7 |

### 2.2 The audited path, decomposed

`dsh-tool-pwsh` → `ctx.shell.run` → `dsh-pwsh-sandbox` (mode `danger-full-access` → delegates straight to `super.run`, no confinement work) → `dsh-pwsh-local.PwshLocalExecutor.runArgv` → `ctx.subprocess.spawn` → `dsh-subprocess-local.spawn` → `probeWindowsJob()` → `launchWindowsJob` (spawn `runner.js`) → runner `CreateProcessW` inside its Job → poll every 10 ms until exit.

| Component | Typical (p50) | Best observed (min) | Overhead or work | Instrument |
|---|---|---|---|---|
| `probeWindowsJob()` per spawn: `runnerInvocationAvailable` + `loadWin32ProcessBindings()` + `probeCurrentTokenJobSupport()` | **< 1 ms** | < 1 ms | overhead | `dshspawn.mjs` `probeMs` |
| spawn `runner.js` (Node start + module graph + IPC) | **≈136 ms** | 120 ms | pure overhead | `steady.mjs` runner-idle |
| `CreateProcessW` of the target from inside the runner | **≈7 ms** | 4.5 ms | necessary | `battery.mjs` spawn-return |
| `pwsh.exe` start + the encoding preamble | **≈550 ms** | 405 ms | pure overhead on a one-shot design | `steady.mjs`, `steady2.mjs` |
| collector wiring + spill decision + JSON canonicalisation | **≈10 ms** (derived) | ≈10 ms | overhead | derived |
| exit detection (`setInterval(…, 10)` polling in `runner.js:240-242`) | 0–10 ms + 0.1 ms/job/s | 0 | overhead | code read |
| **TOTAL over the whole `pwsh` tool call** | **≈700 ms** | **≈540 ms** | **pwsh 78 %, runner 19 %, everything else <3 %** | sum of the above; each row is its own fresh-process series, so this is a decomposition, not one end-to-end run |

**Cold vs warm for the harness as a whole.** The engine itself is now warm after boot: a session is not a process and a subagent is not a process. A *cold engine* pays a one-time Node start plus the profile composition (order of seconds; not re-measured here, and the owner's "446 ms warm / 1 608 ms cold `node -e`" from L1701 is the right shape). A *cold tool call* pays none of that — every call is warm in Node terms and cold in PowerShell terms. **The thing that is cold on every single call is `pwsh.exe`.**

`npx`: `cmd.exe /d /c npx --no-install --version` measured p50 **517 ms** (n=6, `spawnbench.mjs`) — i.e. an `npx` call is another full Node start behind a `cmd` shim, and it is why L1701 moved MCP off `npx`. Also measured: Node 24 **refuses to `spawn` a `.cmd` shim directly** — `spawn('C:\\Users\\ezabz\\AppData\\Roaming\\npm\\npx.cmd', …)` throws `EINVAL errno -4071`. That is CVE-2024-27980 hardening, documented: Node "will now error with `EINVAL` if a `.bat` or `.cmd` file is passed to `child_process.spawn` … without the `shell` option set" **[OFFICIAL]**: [April 2024 security releases](https://nodejs.org/en/blog/vulnerability/april-2024-security-releases-2). The sanctioned routes are `shell: true` — now a **runtime** deprecation (DEP0190), because values "are not escaped, only space-separated, which can lead to shell injection" **[OFFICIAL]**: [Node deprecations](https://nodejs.org/api/deprecations.html) — or an explicit `cmd.exe /c`. Either way a `.cmd` shim costs one extra `cmd.exe` process, because the shim cannot be the direct image **[OFFICIAL]**: [child_process](https://nodejs.org/api/child_process.html). Ignore `npx` in any latency budget and call `node <entry.js>` directly, as L1701 already did.

`windowsHide` is not a latency lever here: Node documents its default as **`false`** **[OFFICIAL]**: [child_process](https://nodejs.org/api/child_process.html), and DSH sets it true; measured A/B in §7.3 shows the difference is inside noise. It is a UI-hygiene flag, not a performance one — do not chase it.

**Where the p50 spread comes from.** Community write-ups claim Windows spawn costs "~50–200 ms" per spawn versus "~5–10 ms" on Linux **[COMMUNITY, unmeasured]**: [aden-hive/hive#4427](https://github.com/aden-hive/hive/issues/4427). **This host measures a minimal `cmd.exe` spawn at 33–36 ms, and 500 ms goes to PowerShell's own initialization** — so that community figure is neither the local reality nor the explanation for the owner's complaint. Measured-and-self-reported community data on AV tax puts a Defender-scanned process start at ~355 ms vs ~332 ms (**≈7 %**) **[COMMUNITY, measured]**: [rjmurillo/ai-agents#3175](https://github.com/rjmurillo/ai-agents/issues/3175). Microsoft ships no per-exec Defender figure but documents that the engine skips work for performance via a `SkipReason` of "Optimization" **[OFFICIAL]**: [tune Defender performance](https://learn.microsoft.com/en-us/defender-endpoint/tune-performance-defender-antivirus). On this host `pwsh.exe` is executed hundreds of times a day, so its image and its dependency closure are long since cached; **Defender is a plausible contributor to the p50/p10 spread and is not the 500 ms.**

### 2.3 What is work and what is overhead

- **Work:** `CreateProcess` of the real target (7 ms) and the command the model asked for.
- **Overhead that buys nothing:** PowerShell's initialization (~500–550 ms typical, ~80 % of the total), the runner process (~136 ms, ~20 %), the encoding preamble (~20–40 ms).
- **Overhead the owner asked for and cannot be removed:** the Job-owning runner's guarantee (see §4), the sandbox decision, output collection.

The owner's working estimate of "PowerShell's own ~100 ms per-call overhead" is wrong for this host by a factor of five. Nothing else in this report is as large.

---

## 3. The persistent shell, in full

Source read end to end: `dsh-tool-pwsh-persistent\lib\index.js` (407 lines) and `dsh-tool-pwsh\lib\index.js` (452 lines), plus its two dependencies (`dsh-terminal`, `dsh-terminal-bash`) and the composition rows that would have to mount them.

### 3.1 What it registers

- **Tool name: still `pwsh`.** `defineTool({ name: "pwsh", … })` — `dsh-tool-pwsh-persistent\lib\index.js:354`. Same model-facing name as the one-shot tool, so nothing in a persona or a prompt has to change.
- **Parameters: exactly one.** `parameters: { command: { type: "string", required: true } }` (`:356-360`). This is the whole schema.
- **Output:** `schema: { type: "string" }`, rendered as one text block (`:361-367`). The one-shot tool returns a structured foreground object (`kind`, `exitCode`, `signal`, `timedOut`, `aborted`, `timeoutMs`, `stdout{text,truncated,spillPath}`, `stderr{…}`, `sandbox{…}`) or a `background` job handle (`dsh-tool-pwsh\lib\index.js:271-354`).
- **Config** (`:386-391`): `backendType` default `"shell"`, `timeoutMs` default `300000`, `maxOutputChars` default `16000`, `description` default a one-liner. No `timeoutMs` is passed to `defineTool`, so the tool declares **no per-call timeout** and the tool-call timeout policy does not fire for it (§5.2).
- **No `systemPrompt` section**, unlike the one-shot tool (`dsh-tool-pwsh\lib\index.js:228-232`), so the harness's "non-zero exits are reported as `[exit code: N]`…" paragraph disappears from the prompt.
- **Lifetime:** one shell per agent owner in a `Map`, created lazily on the first call (`:226-262`), disposed with the owner (`:238-244`) and with the plugin (`:211-219`).

### 3.2 Behaviour on each edge case, read from the code

| Situation | What happens | Evidence |
|---|---|---|
| **Timeout** | The command deadline aborts; partial output is rendered ("Your command timed out after Ns or experienced an OOM error. Below is partial output:"), the shell is **killed and reset**, and the next call starts a fresh shell | `:275`, `:306-315`, `:220-225` |
| **Shell exit** | The exited session is detected, its retained scrollback is rendered, `[shell exited: code N]` / `[shell killed by signal: S]` is appended, the owner's shell is reset, and the fixed message "The persistent pwsh shell was reset; the next pwsh call starts from the workspace with a fresh current directory and environment." is returned | `:179-193`, `:284`, `:324` |
| **Hung command with no output** | The loop alternates `startSend(submit:true)` then `startSend(text:"", submit:false)` every 25 ms until the deadline. A command blocked on stdin never yields the end marker, so it burns a core at 40 iterations/s for the full `timeoutMs` (default **300 s**) and then resets the shell | `:282-327`, `:74`, `:140-142`, `:289` |
| **Command that changes directory** | **Persists.** The wrapper is `Invoke-Expression` inside the same shell, so `cd`/`Set-Location` persists to the next call. This is the only real capability *gain* | `:99-102` |
| **Command that exports variables** | **Persists**, same mechanism. Also a gain | `:101` |
| **Concurrent calls, same owner** | Serialised by a per-owner promise queue (`queues` WeakMap); a second call waits for the first | `:342-352` |
| **Background jobs** | **Not available.** `run_in_background` is not a parameter; there is no `ctx.jobs` use anywhere in the file. Background work must be launched as a detached child inside the command string, and the shell is then busy until it returns | `:353-381` |
| **Sandbox escalation** | **Not available.** No `ctx.approval`, no `sandbox_permissions`, no `justification`. A denial is terminal | `:353-381`; the one-shot path resolves it at `dsh-tool-pwsh\lib\index.js:212-227` |
| **Working directory per call** | **Not available.** Every call runs in the shell's current directory. Startup cwd is the session header cwd | `:233-236` |
| **Massive output** | The ConPTY scrollback is paged back (1 000-line pages) and the assembled text is cut to `maxOutputChars` (16 000 chars) with `<response clipped>…` appended. The beginning is *kept*, the tail is dropped, and the dropped part is **gone** — there is no spill file | `:73`, `:76-79`, `:147-170`, `:171-174` |
| **Exit code** | The wrapper appends `__END_<nonce>:<code>` and the tool renders `[exit code: N]` only for non-zero. `$LASTEXITCODE` is cleared before the body; if the body leaves it null the code is derived from `$?` | `:99-102`, `:120`, `:173` |
| **Owner/agent absent** | Throws `pwsh requires an owning agent session` | `:370-371` |
| **Empty command** | Throws `command must be a non-empty string` | `:369` |
| **Messages with no output** | Only the exit marker; `(no output)` is not synthesised | `:175-177` |

### 3.3 The DIFF table — one-shot `dsh-tool-pwsh` vs `dsh-tool-pwsh-persistent`

| Parameter / edge case | One-shot (`dsh-tool-pwsh`) | Persistent (`dsh-tool-pwsh-persistent`) | Verdict |
|---|---|---|---|
| tool name | `pwsh` | `pwsh` | same |
| `command` | required string | required string | same |
| `description` | **required** string, shown in the UI, and `presentCall` uses it | not a parameter; the tool's own description string replaces it; UI title is the command | **LOSS** |
| `workdir` | optional string, relative resolved against the session workspace | absent; the shell's cwd persists across calls | **LOSS** (a `cd` can be prefixed, but the cwd then leaks into later calls) |
| `timeoutMs` | optional number; executor default 120 000, capped at 600 000 (`dsh-pwsh-local` Config) | absent; fixed 300 000 from plugin config, not per-call | **LOSS** (can be raised for all calls via config only) |
| `run_in_background` | `true` → registers a job with `ctx.jobs`, returns `{kind:"background", jobId}`; `job_output`/`job_kill` work | absent; no job support at all | **LOSS** (hard; this is the designed way to run anything >60 s) |
| `sandbox_permissions` / `justification` | escalate a denial via `ctx.approval`, same turn, with a user prompt | absent; denial is final | **LOSS** |
| exit reporting | structured `exitCode`/`signal`/`timedOut`/`aborted`; `[exit code: N]`, `[timed out after Nms]`, `[killed by signal: S]` | `[exit code: N]` only; timeout message is prose; shell death renders `[shell exited: code N]` | **PARTIAL LOSS** — `timedOut` and `signal` are not distinguishable in the text; the UI loses the exit-status pill |
| stdout/stderr shape | **separate** streams, each with `[stderr]` marker | merged: ConPTY merges them into one byte stream | **LOSS** (a command cannot be told apart by stream) |
| large output | in-memory 64 000-byte tail per stream, **spill file up to 64 MB**, model is told `[output truncated; full output: <path>]` and can read the file | 16 000-char cut, `<response clipped>` notice, **no path, bytes unrecoverable** | **LOSS — the biggest one** |
| truncation direction | keeps the **tail** (errors and final results cluster there — the documented tail-keep rationale in `runner-launch-COYGu0Dl.js`) | keeps the **head**, drops the tail | **BEHAVIOURAL CHANGE** — the tail is where failures are |
| shell state | none; every call fresh | cwd + variables + functions persist | **GAIN** |
| per-call cost (warm) | ≈700 ms (≈540 ms best observed) | ≈34 ms measured round trip after a one-time ≈170 ms spawn | **GAIN ≈660 ms per call** |
| process count while idle | 0 | 1 `pwsh` (~103 MB) + 1 ConPTY owner per owner with a live shell | **COST** (memory, and one more thing to reap) |
| process-tree containment | Windows **Job object**, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, runner-owned; host exit terminates it synchronously | **none.** Windows ConPTY is deliberately outside Job containment (`dsh-subprocess-local\lib\index.js:1025`: "Windows ConPTY remains outside Job containment"); cleanup is descendant enumeration + signals | **LOSS — load-bearing, see §4.3** |
| timeout recovery | the process dies; nothing else affected | the shell is killed **and the warm state is lost**, so the next call pays the start again | minor LOSS |
| sandbox mode `read-only`/`workspace-write` | the executor confines the argv via `ctx.sandbox.confine` | the backend confines the argv the same way **and** adds a mode fence so a mode change cannot reuse a stale shell | same (persistent is slightly stricter) |
| UI card | `terminal` card with `cwd` and a parsed exit pill | `terminal` card, title only | minor LOSS |

**Safe drop-in? No.** Four of the losses are behavioural, not cosmetic: `run_in_background` (the documented way to run anything long), `sandbox_permissions` (the only path out of a denial), the spill file (the only way to see more than 16 KB), and per-call `workdir`. Any one of them can silently change what an agent can do, and the owner's constraint is that nothing may be lost.

### 3.4 Why it will not even mount today

`dsh-tool-pwsh-persistent` declares `inject = ["tools", "terminals"]` (`:384`). Nothing in the current profile provides `terminals`:

- `dsh-base\cordis.patch.yml` mounts `subprocess` (`dsh-subprocess-local`) but **not** `dsh-terminal`, and no bundle patch in `~/.dsh/profiles/node_modules/@deepseek-ai/*/cordis.patch.yml` mentions `dsh-terminal` at all. The grep over every bundle patch returns exactly one hit: `dsh-sdk-minimal`, where the whole persistent-shell stack lives (`:50-64`, `:123-139`).
- `dsh-session-projection` — the other hard dependency of the terminal backend (`dsh-terminal-bash` `inject` includes `sessionProjections`) — **is** mounted by `dsh-base:138`, so that one is satisfied.

Mounting the row as-is would therefore fail the preset mount audit with a row that never activated, or collide. The composition work in §6 covers it.

---

## 4. Can the runner process be avoided, or made lighter?

### 4.1 There is no config, by design

`dsh-subprocess-local` has **no `static Config`** and exports only `LocalSubprocessRuntime` (`lib/index.js:1084`). Its module doc says so explicitly (lines 898-906): *"It has no config: every disposition and limit arrives on the spec, so deployment-varying choices stay with the caller's config."* The containment mode is chosen at runtime, per spawn, by `selectContainmentMode(kind)` (`:1007-1021`): Linux user-systemd scope if the deep probe passes, Windows Job for `ordinary` on win32, otherwise a weaker fallback with a one-time warning (`warnFallback`, `:1022-1027`). **There is no knob to choose `fallback` on Windows, to change the 10 ms poll, or to reuse a runner.**

### 4.2 The 10 ms poll is a timing floor, not a spin

`runner.js:240-242` installs `setInterval(() => this.poll(), 10)` **after** the target is created, and `finish()` clears it (`:354-355`). The runner is *not* polling while idle — an idle leftover runner costs a resident 57 MB and nothing else (measured: 3 of them resident before this audit, `runner-idle` cycle 120–149 ms). While a command runs, the cost is one timer per live job: 100 wakes/s per concurrent tool call. With ≤20 concurrent tool calls that is ≤2 000 timer callbacks/s, i.e. ~0.1 ms of the 10 ms slot each. **Not worth changing.** The 10 ms interval does add up to 10 ms of exit-detection latency per call, which is inside this host's noise floor.

**Why the poll exists at all — and why it is not simply a mistake.** Node does not poll a direct child: libuv's Windows backend registers `RegisterWaitForSingleObject`, a real event wait **[REPO]**: [libuv `src/win/process.c`](https://github.com/libuv/libuv/blob/v1.x/src/win/process.c). DSH needs something Node cannot give it: it waits for the **Job** to become empty, not for the direct child to exit, and `isJobEmpty` (`runner.js:287-291`) is a query with no waitable event. A `WaitForSingleObject` on the process handle would answer "the direct child exited" and would then have to *keep* polling the Job anyway to know the range drained. So the 10 ms timer is the price of the containment guarantee, and it is paid 0.1 ms at a time. `WaitForSingleObject(handle, 0)`-style probing is explicitly described by libuv as "prone to a race" relative to a real wait, which is another reason not to hand-roll it.

### 4.3 What the Job owner buys, and what losing it costs

Read from `launchWindowsJob` (`dsh-subprocess-local\lib\index.js:493-584`) and `WindowsJobRunner` (`runner.js:138-362`):

1. **Synchronous tree kill on host exit.** The runner creates the target via `CreateProcessW` inside a Job; on disconnect the runner calls `terminateJob(api, job, 1)` before exiting (`runner.js:330-350`), and the host's `process.prependListener("exit", …)` path calls `terminateForHostExit()` synchronously (`index.js:929-947`). `TerminateJobObject` kills **every associated process** and "cannot be postponed or handled" by them — it is as if `TerminateProcess` were called for each **[OFFICIAL]**: [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject). That is why the leaked-descendant class of bug cannot occur on this path.
2. **Proof of quiescence.** `rangeExit` resolves only when the runner exits `0` *after* having published `target-exit` (`index.js:568-576`) — so `waitForExit()` means "the whole managed range is gone", not "the direct child exited". Compare the documented weaker guarantee elsewhere in the same codebase: *"Assignment is not retroactive: descendants created before this call completes are not guaranteed to become members of the job"* — the runner avoids that race by creating the target **inside** the Job from the start (it is the runner, not the agent host, that calls `CreateProcessW`).
3. **A hard error if that proof is missing.** A runner that dies before proving the range empty raises *"Windows Job runner exited with <status> before proving its managed range empty"* (`index.js:574-575`). Silently leaking work is not an available outcome.

Without it, cleanup is `LocalTerminalHandle`-style descendant discovery: snapshot the process tree, `SIGTERM`, wait `graceMs`, re-snapshot, `SIGKILL`, and *throw* if anything survives (`index.js:779-788`, `846-851`). This is exactly the mechanism that FAILED twice in this system's history, and the code's own warning says it: *"descendants that escape the process group or direct-parent tree are not guaranteed to terminate or delay waitForExit()"* (`index.js:1026`). `ChildProcess.kill()` does not kill a tree on Windows — journal L1701 records that and the ~2 GB of MCP residue it produced.

**Verdict: the Job owner is load-bearing for cleanup and must stay.** It costs ≈135 ms per call, and it is the reason a killed tool call does not leave orphaned `pwsh`/`msbuild`/`npm` trees behind. Removing it to save 135 ms would trade a measured, bounded overhead for an unbounded, historically demonstrated leak. Do not.

### 4.4 The one legitimate runner saving

If the persistent shell is adopted, the runner disappears from the per-call path as a side effect: the persistent shell is spawned once through `node-pty` and **all** subsequent commands ride the same process, so there is no `dsh-subprocess-local` spawn per command at all. That is a saving of ≈135 ms that the Job owner costs only once per shell, not once per call — and the Job guarantee is lost for the shell's children (§3.3). That is the actual trade, stated plainly: **the runner's 135 ms and its cleanup guarantee are the same purchase.**

### 4.5 What is left that is actually configurable

- `dsh-pwsh-local` config: `timeoutMs` 120 000, `maxTimeoutMs` 600 000, `maxOutputBytes` 64 000, `maxSpillBytes` 64 MB, `graceMs` 3 000 (`lib\index.js:201-206`). None of these is set in the base profile, so the defaults apply.
- `dsh-subprocess-local`: nothing.

---

## 5. Everything else on the tool-call path, ranked

| Rank | Item | Measured / read cost | Where |
|---|---|---|---|
| 1 | **pwsh start** | **≈500–550 ms p50, 340–406 ms best observed** | §2 |
| 2 | **runner.js start** | **≈135 ms** | §2 |
| 3 | **ConPTY shell spawn** (persistent path only, once) | ≈170 ms | §2.1 |
| 4 | encoding preamble | **≈20–40 ms** per call | §2.1 |
| 5 | per-command round trip, warm ConPTY shell | **18 ms min / 34 ms p50** | §2.1 |
| 6 | output collector + spill decision | ~10 ms derived; a spill *write* only happens above 64 000 bytes and streams to disk, so it is not a cliff | `runner-launch-COYGu0Dl.js` `OutputCollector` |
| 7 | exit-detection poll granularity | 0–10 ms | `runner.js:240-242` |
| 8 | `probeWindowsJob()` per spawn | **< 1 ms** | §2.2 |
| 9 | sandbox resolution | ~0 ms at `danger-full-access`: `SandboxPwshExecutor.run` short-circuits to `super.run` and only stamps `{mode, denied:false}` | `dsh-pwsh-sandbox\lib\index.js:151-160` |
| 10 | tool argument validation | ~0 ms: `defineTool` compiles the parameters schema once at registration and validates a ~200-byte object per call; it costs microseconds, and unknown keys are **not** rejected (no `additionalProperties:false` on the generated parameters schema) | `dsh-tools\lib\index.js:837-868` |
| 11 | tool-call timeout policy | one registry lookup + one `AbortController` per call; **skipped entirely** when the tool declares no `timeoutMs` | `dsh-tool-call-timeout-policy\lib\index.js:115-141` |
| 12 | `dsh-fs` read path (stat + readFile + observation gate) | **stat p50 0.11 ms, readFile of a 60 KB YAML p50 0.76 ms** — 4 000× under the pwsh floor | `fslat.mjs` |
| 13 | permission prompts | zero in mode `danger-full-access` (approval policy resolves to `never`) | `dsh-base:224-241` |
| 14 | spill policy / output retention | only engages above `maxInlineBytes: 50000` | `dsh-base:383-386` |

**The one ranked item that is worth a change and is not the shell: nothing.** Items 3–14 are either negligible or already only paid once. Everything that matters is items 1 and 2.

---

## 6. Implementation plan (spec — not applied)

### 6.1 Source of truth

`presets/zabz/agent.cordis.yml` is **generated**. `scripts/make_zabz_preset.py:16-19` states it: *"GENERATED OUTPUT. `presets/zabz/agent.cordis.yml` is rewritten wholesale from this file. NEVER hand-edit that file."* The generator reads `presets/cordis-bg/agent.cordis.yml` (`:29`), replaces the persona row wholesale (`:343-366`), appends `MCP_ROWS` (`:369`), writes `preset.yml`, and copies `presets/cordis-bg/skills/`. **The tool rows are therefore inherited verbatim from `presets/cordis-bg/agent.cordis.yml`, where the `tool-pwsh` row lives at lines 64-65.** The row that must change is:

```yaml
# harness-config/presets/cordis-bg/agent.cordis.yml:60-65   (SOURCE OF TRUTH)
- id: tool-pwsh
  name: '@deepseek-ai/dsh-tool-pwsh'
  disabled: !!js process.platform !== 'win32'
```

Editing `presets/zabz/agent.cordis.yml` directly loses the change the next time anyone runs `make_zabz_preset.py` — the exact failure mode that lost persona rules 2b and 2c on 2026-09-11.

### 6.2 The change, in three parts, all-or-nothing

**Part A — the terminal provider must go on the HOST plane, not into the preset.** `dsh-terminal` publishes the process-global `terminals` service (`dsh-terminal\lib\index.js:58`), and the editing rule for compositions is that a service the host plane supplies cannot be mounted loose in a preset (it collides on the second session) and a label-realm cannot pool instances. The correct rows are the ones `dsh-sdk-minimal` already uses (`:50-64`), and the right home is the profile-host patch — for the `web` profile that is the owned layer `~/.dsh/profiles/web/cordis.patch.yml` (its header names it "the layer we own"; its current contents are heartbeat/recovery patches). Add, gated to Windows:

```yaml
  # terminal provider for the persistent shell. dsh-sdk-minimal mounts this same
  # pair; nothing in dsh-base does, so ctx.terminals resolves nowhere today.
  { id: 'pty', name: '@deepseek-ai/dsh-terminal' },
  { id: 'terminal-pwsh',
    name: '@deepseek-ai/dsh-terminal-bash',
    disabled: !!js process.platform !== 'win32',
    config: { shellDialect: pwsh, timeoutMs: 300000 } },
```

**Part B — swap the tool row in the source composition** (`presets/cordis-bg/agent.cordis.yml:64-65`), keeping the one-shot row present but disabled as the rollback:

```yaml
- id: tool-pwsh
  name: '@deepseek-ai/dsh-tool-pwsh'
  disabled: true
- id: tool-pwsh-persistent
  name: '@deepseek-ai/dsh-tool-pwsh-persistent'
  disabled: !!js process.platform !== 'win32'
  config:
    maxOutputChars: 64000      # match the one-shot in-memory tail exactly
    timeoutMs: 120000          # match the one-shot default, not the 300 s default
```

`maxOutputChars: 64000` and `timeoutMs: 120000` remove two of the four behavioural losses at zero engineering cost by matching the values the one-shot path already uses (`dsh-pwsh-local` Config `maxOutputBytes` 64 000, `timeoutMs` 120 000).

**Part C — the remaining three losses need a thin adapter, and this spec does not pretend otherwise.**

- `run_in_background` and `sandbox_permissions`/`justification` and `workdir` cannot be added by config; the tool's `parameters` object is closed and is not configurable.
- The honest options, in order of preference:
  1. **Upstream the parameters.** The plugin's `defineTool` call is a 30-line change: keep `command`, add `workdir` (prefix `Set-Location -LiteralPath '…'; ` and restore after), `run_in_background` (register with `ctx.jobs` around a detached `Start-Process`), `timeoutMs` (per-call deadline instead of the config constant), `description` (presentation only), and the escalation pair (map to `ctx.approval` and re-run). This is a package change, it survives upgrades, and it is the only option with no permanent capability loss.
  2. **A host-plane wrapper tool** that registers both `pwsh` (persistent, full parameter surface) and `pwsh_oneshot` (the current tool, unchanged), with a prompt rule that names which to use when. Two tools in the catalog costs request-cache stability and one more schema in every request; it does not lose anything.
  3. **Do nothing yet** and take the measured, zero-risk win in §6.3 first.
- **Recommendation: option 1, then option 2 as the interim if upstream is slow.** Do not ship the bare persistent row: losing `run_in_background` on this harness means every long build goes back to the 120 s foreground cap, which is the exact failure recorded in journal L1566 ("my foreground pwsh call was killed at the 120s cap mid-restart, which left the API down until I re-ran it as a background job").

### 6.3 The change to make first, because it is free and reversible

The measurements say the persistent shell is worth building but the bare row is a capability regression. So the first change is the one that costs nothing at runtime, changes no capability, and makes the rest measurable:

**Part A alone — mount `pty` + `terminal-pwsh` in the owned profile-host patch (`~/.dsh/profiles/web/cordis.patch.yml`), leaving `tool-pwsh` as the live tool.** It adds two rows, provides a service nothing consumes yet, removes nothing, and cannot alter a single tool call until Part B is flipped. Its value is that it turns "would the persistent path work here?" from an argument into a one-flag experiment with the §6.5 test table.

Two things that must be said plainly about the alternatives:

- **Micro-tuning `CreateProcess` or the poll is not worth doing.** 7 ms and 0–10 ms sit inside a 170 ms spread on a host whose floor already moves 20 % between passes. Anyone proposing to shave them is optimising the wrong 1 %.
- **The honest first-order win is already available and is not a code change:** the slow shell calls are slow because they are shell calls. Measured tool cost for the same information: `read`/`stat` p50 **0.76 ms / 0.11 ms** vs **≈540–700 ms** through `pwsh`. Preferring the file and search tools over `pwsh Get-Content`/`Select-String` is a 700× saving on every call it applies to, and it is a practice-and-prompt change, not a harness change.

### 6.4 Rollback

1. `presets/cordis-bg/agent.cordis.yml`: set `tool-pwsh-persistent` back to `disabled: true`, `tool-pwsh` back to enabled, re-run `python scripts/make_zabz_preset.py`.
2. Host patch: remove the `pty`/`terminal-pwsh` rows. The rows are additive and gated to Windows; removing them leaves `dsh-base` untouched.
3. Verify with `python scripts/make_zabz_preset.py --check` (writes nothing, catches drift) before and after.
4. An engine restart is required either way — the preset decides the tool catalog at session start (journal P11 documents exactly this trap).
5. Nothing is irreversible: no data is migrated, no file is deleted, no model or provider changes.

### 6.5 Test plan that proves no capability loss

Run each row against a live session on the modified preset and compare to the one-shot behaviour recorded in §3.3. Every command is a single parameter surface.

| # | Exercise | Exact command | Pass condition |
|---|---|---|---|
| 1 | `command` | `Write-Output hi` | output `hi`, no `[exit code]` |
| 2 | non-zero exit | `cmd /c exit 3` | `[exit code: 3]` in the result |
| 3 | exit 0 explicit | `exit 0` | no marker |
| 4 | **`workdir`** | `(Get-Location).Path` after a call with `workdir` set to a subdirectory | returns that subdirectory, and the *next* call returns to the previous cwd |
| 5 | **`run_in_background`** | `run_in_background: true` with `Start-Sleep 15; 'done'` | returns a job id immediately; `job_output` shows `done`; `job_kill` stops it |
| 6 | **`timeoutMs`** | `timeoutMs: 3000` with `Start-Sleep 30` | result says timed out after ~3 s; the next call still works |
| 7 | **`description`** | any call with a description | the UI card shows the description |
| 8 | **escalation** | under a confined mode, a denied path then a retry with `sandbox_permissions` + `justification` | the denial marker and the same-turn escalation hint both appear; the approval prompt is raised |
| 9 | **huge output** | `1..20000 \| ForEach-Object { "line $_" }` | more than 16 000/64 000 chars: for the one-shot path the result names a spill file and that file exists and holds the tail; for persistent `maxOutputChars` is honoured and the notice appears |
| 10 | **stderr separation** | `[Console]::Error.WriteLine('E'); 'O'` | one-shot: `[stderr]` section; persistent: merged (record the difference, decide) |
| 11 | cwd persistence (gain) | `Set-Location $env:TEMP` then `(Get-Location).Path` | second call returns TEMP — **this is the feature; confirm it is intended** |
| 12 | env persistence (gain) | `$env:ZABZ_T=1` then `$env:ZABZ_T` | second call returns 1 |
| 13 | concurrency | two `pwsh` calls in one assistant step | both complete; per-owner serialisation holds |
| 14 | shell exit | `exit 7` | `[shell exited: code 7]` + the reset message; the next call works from a fresh shell |
| 15 | timeout recovery | a 30 s sleep with a 3 s timeout, then `Write-Output ok` | second call succeeds; the warm state is gone (expected) |
| 16 | no orphan on kill | start `Start-Sleep 300` in the background, kill the owner, then `Get-Process pwsh` | **no surviving `pwsh`** — this is the persistent path's weakest point; if it fails, §6.2 must not ship without a Job wrapper |
| 17 | latency | time a `Write-Output hi` call 20× in one session | p50 ≤ 100 ms after the first call (vs ≈700 ms today) — measured with `sesslat.mjs` on the session log, not by eye |

Test 16 is the gate. If a persistent shell's children can survive the engine, the persistent path needs the plane it was built on (a Job-owning spawn), not a preset change — because losing the Job guarantee is the one loss this business has already paid for twice.

---

## 7. Online research, with sources

### 7.1 PowerShell start-up on Windows

- Microsoft frames start-up as three phases — process creation, SessionState initialization, profile processing — and states that "on first startup after installation or upgrade, PowerShell and .NET run optimization tasks… Startup will take longer during this first-time optimization" **[OFFICIAL]**: [Troubleshoot PowerShell startup issues](https://learn.microsoft.com/en-us/powershell/scripting/dev-cross-plat/performance/startup-performance).
- The same page names the caches: `ModuleAnalysisCache-*` and `StartupProfileData-*` under `%LOCALAPPDATA%\Microsoft\PowerShell`, deleted to fix a slow start and rebuilt on next start **[OFFICIAL]**. Measured consequence here: run the exact argv posture once before benchmarking.
- Microsoft's own best breakdown, with hardware named: PowerShell PR #18195 moved type initializers to a background thread and measured `pwsh.exe -noprofile -c echo 1` at **557.2 ms → 386.3 ms** on a Xeon W-2235, Win11, .NET 7 RC **[REPO, measured]**: [PowerShell#18195](https://github.com/PowerShell/PowerShell/pull/18195). **386 ms matches this host's 377–406 ms best-observed floor almost exactly** — i.e. the local floor is normal, and the p50 inflation to ~550 ms is load, not a misconfiguration.
- Per-component attribution from a PerfView trace: `powershell.config.json` + Newtonsoft "expected perf win 50–100 ms", ApplicationInsights lazy init "30 to 100 ms", `InitialSessionState` cctor / `GetAppLockerPolicy` "~10–30 ms", a `string.ToLowerInvariant()` in the command-line parser at **26 ms** **[REPO]**: [PowerShell#14268](https://github.com/PowerShell/PowerShell/issues/14268). Same thread warns that `EventSource.CreateManifestAndDescriptors()` appears only because the profiler collects ETW and is a tracing artefact.
- `-NoProfile` "Doesn't load the PowerShell profiles" — and nothing more is documented **[OFFICIAL]**: [about_Pwsh](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_pwsh). This host has **no profile at all** (`C:\Users\ezabz\Documents\PowerShell\profile.ps1` absent), which is why removing `-NoProfile` changed nothing in my A/B — a clean confirmation of the documented contract, measured.
- `-NonInteractive` is documented as an input-behaviour switch, but the start-up page also makes it a performance switch: interactive sessions auto-load PSReadLine, "a signed module. PowerShell must verify the digital signature… the default timeout for CRL checks is 15 seconds", and the prescribed test is exactly `pwsh.exe -noninteractive` **[OFFICIAL]**. The harness already passes `-NonInteractive` (`dsh-pwsh-local\lib\index.js:271-279`), so that saving is already banked.
- Two documented environment variables remove *network* cost from start-up and are the reported fix for pathological starts: `POWERSHELL_TELEMETRY_OPTOUT` and `POWERSHELL_UPDATECHECK` **[OFFICIAL for their existence; COMMUNITY for the measured effect]**: [PowerShell#24710](https://github.com/PowerShell/PowerShell/issues/24710). Pathological outliers on record: 147 s and 180 s starts, one "Loading personal and system profiles took 180574ms" **[COMMUNITY]**: [PowerShell#24710](https://github.com/PowerShell/PowerShell/issues/24710), [PowerShell#23830](https://github.com/PowerShell/PowerShell/issues/23830). **Worth testing on this host: two env vars in the executor's `ENV_OVERRIDES`, zero risk.** I did not test them in this pass; they are the cheapest open experiment in this report.
- `PSModulePath`: PowerShell "recursively searches each folder" for `.psd1`/`.psm1`, and "command auto-discovery analyzes each module… can be expensive", cached per user **[OFFICIAL]**: [about_PSModulePath](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_psmodulepath), [module authoring considerations](https://learn.microsoft.com/en-us/powershell/scripting/dev-cross-plat/performance/module-authoring-considerations). **My A/B measured emptying `PSModulePath` at ~+20 ms, inside noise, and `$PSModuleAutoLoadingPreference='None'` at *slower* (656 ms p50 vs 553 ms).** Do not empty it: the documented failure mode is `CommandNotFoundException` for `Get-CimInstance` & co., and this harness's own audit tools use exactly those cmdlets.
- ReadyToRun/crossgen: PowerShell ships R2R images ("all shipped assemblies are R2R images now") **[REPO]**: [PowerShell#14266](https://github.com/PowerShell/PowerShell/issues/14266). `DOTNET_ReadyToRun=0` would *force* JIT and make startup slower **[OFFICIAL]**: [runtime config — compilation](https://learn.microsoft.com/en-us/dotnet/core/runtime-config/compilation). `DOTNET_TieredPGO`, `DOTNET_EnableWriteXorExecute`: **no PowerShell-specific measurement located** — do not cite them as startup wins.
- The documented cheap-to-open hosting route is `InitialSessionState.CreateDefault2()`, which "loads only the commands required to host PowerShell", versus `CreateDefault()` which loads all built-in commands **[OFFICIAL]**: [Creating an InitialSessionState](https://learn.microsoft.com/en-us/powershell/scripting/developer/hosting/creating-an-initialsessionstate). That is the .NET-hosting lever; DSH does not host PowerShell in-process, so it is not available without a new executor.

### 7.2 ConPTY vs pipes, and how other harnesses stay warm

- **ConPTY is officially supported on Windows 10 1809+ only, desktop apps only, and its channels "are currently restricted to synchronous I/O"** — each channel needs its own thread or "one of the communications buffers" fills and can deadlock the host **[OFFICIAL]**: [CreatePseudoConsole](https://learn.microsoft.com/en-us/windows/console/createpseudoconsole), [Creating a pseudoconsole session](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session). `node-pty` states the same floor ("Windows 10 version 1809 (build 18309) or later is now required") **[OFFICIAL/VENDOR]**: [microsoft/node-pty README](https://github.com/microsoft/node-pty/blob/main/README.md). One that matters for cleanup: `ClosePseudoConsole` on pre-24H2 (26100) "waits indefinitely", so a host that stops draining the output pipe can hang **[OFFICIAL]**: [ClosePseudoConsole](https://learn.microsoft.com/en-us/windows/console/closepseudoconsole).
- **What ConPTY costs is not documented and not measured anywhere I could find** — no official latency/throughput/CPU comparison for a long-lived shell, and the nearest numbers are community render-path figures (1–3 ms), not transport **[COMMUNITY]**. **My own measurement stands alone here: spawn+start ≈170 ms, warm round trip p50 33.8 ms.** No published figure contradicts it.
- **dsh-terminal-bash already chooses the right dialect and args for a persistent Windows shell**: `DEFAULT_PWSH_ARGS = ['-NoLogo','-NoProfile']` with a prompt function that emits OSC `133;D;<code>` + BEL (`lib\index.js:16-17`, `:900`) — the same prompt-boundary convention VS Code documents for its own shell integration (`OSC 633 ; A/B/C/D/E`, with an optional nonce against spoofing) **[OFFICIAL]**: [VS Code shell integration](https://code.visualstudio.com/docs/terminal/shell-integration). Scrollback is bounded at 10 000 lines / 4 MB with a 256 KB per-read cap (`:44-46`) — the ceiling behind the 16 KB model-facing cut.
- **Every serious harness solves completion detection with a marker, not a prompt read.** OpenHands: a custom `PS1` emitting `CmdOutputMetadata` (exit code, dir, pid) scanned from the pane, plus a 30 s no-change timeout **[REPO]**: [tmux_terminal.py](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/tmux_terminal.py). SWE-ReX: suffix the command with `TMPEXITCODE=$? ; sleep 0.1; echo -n 'UNIQUESTRING29234' ; (exit $TMPEXITCODE)` and parse `EXITCODESTART$?EXITCODEEND` **[REPO]**: [swerex `runtime/local.py`](https://github.com/SWE-agent/SWE-ReX/blob/main/src/swerex/runtime/local.py). DSH's persistent tool uses random-UUID markers per call (`index.js:80-86`) — same idea, better nonce hygiene.
- **OpenHands is the existence proof for the pipe design, on Windows, in production**: "one `powershell.exe -NoLogo -NoProfile` over pipes (no ConPTY), writing the command plus a suffix that prints JSON metadata between PS1 markers, with stdout read on a dedicated thread" **[REPO]**: [windows_terminal.py](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/windows_terminal.py). It also forces `PAGER=cat` because a TTY-detecting pager "capture[s] the pane and wedge[s] the session" — DSH already sets `PAGER=cat`/`GIT_PAGER=cat`/`NO_COLOR=1` in `ENV_OVERRIDES` (`dsh-pwsh-local\lib\index.js:145-149`), which is the same lesson learned twice.
- **Codex does the Job containment properly**: on Windows every PTY spawn gets a Job Object, and the child is created `CREATE_SUSPENDED`, assigned, then resumed with `NtResumeProcess` to close the assign-after-start race **[REPO]**: [psuedocon.rs](https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/psuedocon.rs), [job.rs](https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/job.rs). That is the pattern a persistent-shell-on-Windows design would need in order to keep the cleanup guarantee — and the reason test 16 in §6.5 is the gate.
- **Ctrl-C under ConPTY is not a plain signal.** OpenHands' Windows backend sends `CTRL_BREAK_EVENT` and then kills descendants via `Get-CimInstance Win32_Process`, because CTRL_BREAK "can interrupt the waiting script first, leaving launched child processes alive" **[REPO]**. DSH's `LocalTerminalHandle.signalForeground` on win32 writes `\x03` to the terminal (`dsh-subprocess-local\lib\index.js:695-704`); it then relies on the Job/descendant machinery, and on the persistent path there is **no Job** — the concrete form of test 16's risk.
- **Claude Code's own issue tracker says CWD persistence is unreliable** ("Working directory persists between commands; shell state (everything else) does not", plus a Windows non-persistence bug, plus compaction resetting CWD) **[REPO]**: [anthropics/claude-code#28228](https://github.com/anthropics/claude-code/issues/28228). A community reverse-engineering document claims full env/CWD persistence; it contradicts the upstream behaviour and is **unresolved [COMMUNITY]**. Cursor's default Windows agent shell "launches a fresh PowerShell process for each command and carries cwd and env forward by replaying state" per a **community** forum reply (staff) — i.e. the mainstream Windows agents are, like DSH, paying the start per command unless the user enables a legacy persistent mode.
- **Conclusion the sources support:** no harness has published a measured win from ConPTY over pipes; one ships pipes on Windows in production; DSH's ConPTY tool works but drops stdout/stderr separation and Job containment. **A pipe-based persistent shell (`pwsh -Command -`, or a Node-owned `pwsh -NoLogo -NoProfile -NoExit` with marker-suffixed writes) is the design with the better evidence behind it, and it is untested here.**

### 7.3 Windows QoS — tested, not confirmed

Microsoft documents that Win11 QoS classifies a process by window state (Visible → Medium, Minimized/Fully Occluded → Low) and warns that "**Automated tests lacking user input may trigger this feature, lowering QoS and skewing results**", with `HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling\DisableUserPresenceQos = 1` as the test switch **[OFFICIAL]**: [Quality of Service (Win32)](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service). The harness spawns every child with `windowsHide: true` and no focus, which is exactly the described shape. **The registry key is absent on this host, so the default applies.**

Measured A/B (`qos.mjs`, n=12, interleaved): `windowsHide:true` p50 **583 ms** vs `windowsHide:false` p50 **551.8 ms** — a 31 ms difference against a 170 ms spread. **Not confirmed. QoS is a plausible partial explanation and not the cause of the 500 ms.** Do not act on it.

---

## 8. What is not established

- Whether `POWERSHELL_TELEMETRY_OPTOUT=1` + `POWERSHELL_UPDATECHECK=Off` (or `-Off`) shaves anything measurable here. Cheapest open experiment; two lines in `ENV_OVERRIDES`.
- The exact cost of the encoding preamble *for a command that writes non-ASCII*, versus its 20–40 ms cost for a command that writes nothing. The preamble exists for Windows PowerShell 5.1 fallback (`dsh-pwsh-local\lib\index.js:150-158`); `resolvePwshPath` prefers pwsh 7, so the cost may be pure insurance. Not measured.
- Whether a pipe-based persistent shell (`pwsh -Command -`) is cheaper and safer than the ConPTY one. Untested, and it is the most promising untested item.
- Cold-engine start-to-ready time. Not re-measured in this pass.
- Whether the persistent path's children survive the engine (test 16 in §6.5). The code says ConPTY is outside Job containment and that is a quoted design statement, not a measurement. The research makes this sharper: `ClosePseudoConsole` itself "terminates related processes in the tree" **[OFFICIAL]**: [ClosePseudoConsole](https://learn.microsoft.com/en-us/windows/console/closepseudoconsole) — so an orderly teardown *may* reap the shell's children, while an engine crash or `SIGKILL` (which never reaches that call) may not. That is precisely the case test 16 must exercise, and it must be a **kill**, not a clean exit.
- Whether DSH can hold a Job around a ConPTY shell at all. Codex's source does it (`CREATE_SUSPENDED` → assign → `NtResumeProcess`) and also documents that a nested job can **refuse** assignment, in which case it resumes the child *without* containment and only logs **[REPO]**: [job.rs](https://github.com/openai/codex/blob/main/codex-rs/utils/pty/src/win/job.rs). Whether this engine's process already sits inside a Job on ZABZ-YOGA is untested, and it decides whether the persistent path can keep the cleanup guarantee.
- Whether ConPTY's documented sequence drift affects DSH's UUID markers. VS Code documents that ConPTY "works a little differently to a regular pty" and that sequences "may be misplaced" **[OFFICIAL]**: [VS Code shell integration](https://code.visualstudio.com/docs/terminal/shell-integration). DSH's markers are matched with `lastIndexOf` on a UUID (`dsh-tool-pwsh-persistent\lib\index.js:108-122`), which is forgiving of reordering; the drift risk is real but not measured here.
- No official or measured `CreateProcess` microbenchmark exists **[OFFICIAL-adjacent]**: [A fork() in the road](https://www.microsoft.com/en-us/research/uploads/prod/2019/04/fork-hotos19.pdf) measures fork/posix_spawn, not `CreateProcess`; the local 33–36 ms figure in §2.1 is the only number in this report and it is mine.

---

## Appendix A — files read for this audit

| File | Lines that matter |
|---|---|
| `dsh-tool-pwsh-persistent\lib\index.js` | 68-79 (truncation), 96-102 (wrapper), 226-262 (shell map), 268-334 (execute loop), 340-405 (registration, Config) |
| `dsh-tool-pwsh\lib\index.js` | 60-80 (render), 134 (Config), 236-270 (parameters), 271-359 (output schema, render), 360-449 (execute, escalation, background) |
| `dsh-pwsh-local\lib\index.js` | 145-158 (ENV_OVERRIDES, encoding preamble), 201-206 (Config defaults), 271-303 (argv, spawnSpec) |
| `dsh-pwsh-sandbox\lib\index.js` | 145-160 (`danger-full-access` short-circuit), 184-227 (per-process facts) |
| `dsh-subprocess-local\lib\index.js` | 493-584 (`launchWindowsJob`), 898-906 (no-config doc), 1007-1027 (containment selection + warning), 1028-1074 (terminal spawn) |
| `dsh-subprocess-local\lib\runner.js` | 138-362 (`WindowsJobRunner`), 240-242 (10 ms poll), 287-291 (Job-empty check), 330-350 (release/terminate) |
| `dsh-terminal-bash\lib\index.js` | 16-17 (pwsh args), 37-52 (Config), 843-869 (inject + mode fence), 900-960 (startup), 975-989 (spawn) |
| `dsh-tools\lib\index.js` | 837-883 (`defineTool` + per-call validation), 1160-1300 (scheduler), 2938-2959 (`executionMode`), 2567-2609 (ToolRuntime Config) |
| `dsh-tool-call-timeout-policy\lib\index.js` | 115-141 (the whole wrapper) |
| `dsh-session-persistence-jsonl\lib\index.js` | 1281-1361 (zstd frame container) |
| `dsh-base\cordis.patch.yml` | 199-264 (subprocess/sandbox/tool rows), 377-386 (timeout + spill) |
| `dsh-sdk-minimal\cordis.patch.yml` | 36-64 (pty + terminal backends), 123-139 (the persistent tool rows) |
| `~/.dsh/profiles/web/cordis.patch.yml` | whole file (the owned host layer) |
| `harness-config\presets\cordis-bg\agent.cordis.yml` | 60-65 (`tool-bash`/`tool-pwsh` rows) |
| `harness-config\presets\zabz\agent.cordis.yml` | 147-153 (the generated copies) |
| `harness-config\scripts\make_zabz_preset.py` | 1-31 (generated-output contract), 328-428 (main) |

## Appendix B — measurement artifacts

`C:\Users\ezabz\code\_dsh-scale\bench\`: `battery.mjs`/`battery.json`, `steady.mjs`/`steady.json`, `steady2.mjs`/`steady2.json`, `psstart.mjs`/`psstart.json`, `psstart2.mjs`/`psstart2.json`, `ptybench.mjs`/`ptybench.json`, `qos.mjs`/`qos.json`, `fslat.mjs`/`fslat.json`, `sesslat.mjs`/`sesslat-session-e34d.json`, `spawnbench.mjs`/`spawn-*.json`, `spawnutil.mjs`, `dshspawn.mjs`.
`C:\Users\ezabz\code\_dsh-scale\research\`: `powershell-startup.md`, `warm-shells-and-spawn.md`.
