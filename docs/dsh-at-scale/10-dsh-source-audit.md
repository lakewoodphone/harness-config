# DSH on ZABZ-YOGA — OS-resource source audit

Read-only audit. Nothing outside this file was created, modified or restarted. No build, no test, no server start/restart.

**Provenance of every measurement below.** Two independent sources are distinguished throughout:

- **CODE** — read from the installed checkout. Paths abbreviated `NM\` = `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\`. Install root verified to contain `dsh`, `dsh-subprocess-local` and ~330 further `dsh-*` packages (all unminified per-module ESM/CJS; the one genuine large bundle is `NM\dsh-session-persistence-jsonl\lib\worker.cjs`, 465 KB, which is grepped rather than read).
- **LIVE** — a process/memory/disk reading taken in this session, **2026-09-15 ~22:45–22:50 local**. Every LIVE number is a snapshot of a machine that is actively working; it moves. Where a number is quoted from the owner's own prior research it is marked `DOCS` with the file and line.

Host context (LIVE, same snapshot): 31.61 GB visible RAM, **1.45 GB free physical**, **commit charge 36.57 GB against a 53.74 GB commit limit**, pagefile `C:\pagefile.sys` allocated 22.13 GB / currently 1.66 GB. **501 processes total.** The commit charge exceeds physical RAM by ~5 GB, so the machine is paging: that, not any single process, is the freeze.

---

## 1. Process model

### One server, many sessions, many agents — one OS process

There is exactly **one** DSH engine process on this machine (LIVE):

```
21124  3173 MB  "C:\Program Files\nodejs\node.exe" ...\@deepseek-ai\dsh\lib\bin.js web --port 3099 --no-open
Get-NetTCPConnection -State Listen -LocalPort 3099  ->  127.0.0.1:3099  OwningProcess 21124
```

`~\.dsh\multi-window\state.json:3-8` records the same pid for port 3099, started `2026-09-14T18:28:59`. **34** live processes have `ParentProcessId == 21124`.

- **A session is not a process.** Sessions are in-memory objects in that one process; `NM\dsh-session\` has no spawn path, and `~\.dsh\sessions\--C-Users-ezabz-code--\` holds one *directory* per session, not a process.
- **A subagent is not a process.** `NM\dsh-subagent-spawn-in-process\lib\index.js:5-9` — "runs each child as a fresh child {@link Agent} on the same cordis context (its own session, own system prompt, zero parent context). **The cheapest transport**". `:34-36` `start(request) { return startInProcessRun(request, {}); }`. `NM\dsh-subagent-fork-in-process\` is the same design for forks. So 12 windows × N agents is still **one** OS process.
- **A tool call CAN be a process, and normally is two.** This is the observed `node.exe ... runner.js` population.

### Where `runner.js` is spawned

`NM\dsh-subprocess-local\lib\runner-launch-COYGu0Dl.js:1412-1416`:

```js
function spawnRunnerInvocation() {
    if ("pkg" in process) return [process.execPath];
    ...
    if (extname(fileURLToPath(import.meta.url)) !== ".ts") return [process.execPath, fileURLToPath(import.meta.resolve("@deepseek-ai/dsh-subprocess-local/runner"))];
```

So the runner is launched as a **full fresh Node.js process** — `process.execPath` (node.exe) plus the `runner.js` entry. Confirmed live, verbatim, on this machine:

```
node.exe ...\dsh-subprocess-local\lib\runner.js -- "C:\Program Files\PowerShell\7\pwsh.exe" -NoLogo -NoProfile -NonInteractive -Command "..."
```

**No npx/npm indirection on this path.** The per-spawn cost is a cold V8 isolate + the `runner.js` module graph + loading the `@deepseek-ai/dsh-win32-process` native bindings (`NM\dsh-subprocess-local\lib\runner.js:3`), then creating a Win32 **Job object**.

### Why the runner stays resident for the whole call

On Windows the runner does not `execve` into the target — it owns the target inside a Job. `NM\dsh-subprocess-local\lib\runner.js:221-242`:

```js
const spawned = this.internals.spawnCurrentTokenJobProcess(this.api, { command, applicationName, args, cwd: request.cwd, env: request.env,
    stdio: { stdin: 4, stdout: 5, stderr: 6 } });
this.processHandle = spawned.process;
this.jobHandle = spawned.job;
...
this.pollTimer = setInterval(() => { this.poll(); }, 10);
```

It exits only once the target has exited **and** `isJobEmpty` is true (`:287-291`). Consequence: **one `pwsh` tool call = one `node.exe runner.js` (~29–58 MB, polling every 10 ms) + one `pwsh.exe`, for the entire duration of the call.** Measured directly in this session: my own `pwsh` call appeared as pid 40664 (`runner.js`, 31 MB) with child pid 16288 (`pwsh.exe`, 31 MB).

Per-call cost measured on this host by the owner's own prior work (`DOCS ~\code\harness-config\docs\multi-window\research-resource-cost.md:102-111`, `:400-403`): runner **57.3–58.3 MB**, `pwsh.exe` grandchild 102.7 MB mean → **~160 MB per shell-command tool call in flight**, bounded by `maxParallelToolCalls`.

Live here, 15–19 runner processes were alive at any moment (~438 MB private in total for that class).

**What triggers it:** any tool whose executor goes through `ctx.subprocess` — `pwsh` (`NM\dsh-pwsh-local\lib\index.js:198` `static inject = ["subprocess"]`, spawn at `:327`/`:352`), `bash`, background jobs, and the Windows ACL sandbox rung. Note the alternative exists and is **not** mounted: `NM\dsh-tool-pwsh-persistent\lib\index.js:237` keeps `live.set(owner, spawned.sessionId)` — one shell per agent, reused across calls. That is the fix path for this multiplier.

**Spill side-effect:** each spawn writes a private temp root; the live evidence is `%TEMP%\dsh-subprocess-<rand>\dsh-subprocess-21124-24-<hash>-stdout.log` (`:34-37`, `:69-71` of `NM\dsh-spill-local\lib\index.js` per owner's prior audit), swept **once per process at activation**, age-only 30 days, no byte cap.

---

## 2. Agent registry / `list_agents` — the BLANK explanation

### The implementation

`NM\dsh-tool-subagent-control\lib\types\list-agents.js:53` registers the tool; `:125-151`:

```js
async execute(args, exec) {
    const parent = exec.agent;
    ...
    case 'children': {
        const entries = await ctx.subagents.listChildren(parent.id, exec.signal);
```

→ `NM\dsh-subagent\lib\types\index.js:248-250` → `NM\dsh-subagent\lib\types\list-children.js:95-103`:

```js
export async function listChildren(ctx, parentSessionId, signal) {
    const listing = await prepareListing(ctx, signal);
```

→ `:131-157`, the load-bearing call:

```js
async function prepareListing(ctx, signal) {
    ...
    const query = ctx.get('sessionQuery');
    ...
    records = await query.listSessions(signal);
```

→ `NM\dsh-session-query\lib\index.js:94-97`:

```js
async listSessions(signal) {
    signal?.throwIfAborted();
    const persistence = this._persistence;
    const persisted = persistence === void 0 ? [] : await listPersisted(persistence, signal);
```

→ `:282-284`:

```js
async function listPersisted(persistence, signal) {
    try {
        return (await persistence.list(signal === void 0 ? void 0 : { signal })).map((snapshot) => snapshot.header);
```

→ `NM\dsh-session-persistence-jsonl\lib\index.js:2454` `async list(options)` → `:2459` `for (const artifact of await this.listArtifacts(signal))` → `:2858-2888`, **the hot path**:

```js
async listArtifacts(signal) {
    ...
    for (const project of await this.listProjectDirs(signal)) {          // readdir(root)
        for (const dir of await this.listSessionDirs(project, signal)) { // readdir(project)
            const selected = await this.resolveGenerationInDirectory(dir, signal);   // readdir(dir)
            ...
            header = await this.readGenerationHeader(selected, void 0, signal);
```

and `readGenerationHeader` → `:3125-3155` `readFirstZstdLine(path)`:

```js
const handle = await open(path, "r");
for (;;) {
    const { bytesRead } = await handle.read(chunk, 0, chunk.length, null);
    ...
    const first = scanZstdFrames(content, 1).frames[0];
    ...
    plaintext = await decompressZstdFrame(content.subarray(first.start, first.end));
```

### Why this is the answer

`list_agents` has **no cache and no index**. Every single invocation performs a **fully serial, single-threaded, whole-home scan**:

1. `readdir(~/.dsh/sessions)` → 1 project dir;
2. `readdir` the project → **372 entries**;
3. for **each of 372 session directories, one after another** (`for … of` with `await` inside; there is no `Promise.all` in `listArtifacts`): `readdir(dir)`, `open()` the log, read 8 KB chunks until the first zstd frame completes, `decompressZstdFrame`, `JSON.parse` the header, `sessionFormatCatalog.readHeader`, plus a `stat` per file in `list()` (`:2462`).

LIVE disk measured this session: `~\.dsh\sessions` = **372 files / ~370 session dirs / 197–202 MB** (each dir holds exactly one file, `session.v3.jsonl.zstd`; largest 12.8 MB compressed). The owner's own session audit measured **211,462,657 B = 201.67 MB** at 22:48:39 the same evening, and noted the earlier same-command reading was 196.62 MB — *the corpus is growing while you read it*.

So: **one `list_agents` call ≈ 372 × (readdir + open + read + zstd-decompress + JSON.parse), serial, on the shared event loop, with no TTL cache, re-paid in full by every concurrent caller on every call.** The two comments that bound it are both about a *different* rung: `COLD_READ_CONCURRENCY = 4` (`list-children.js:78`) and `persistedReadConcurrency` default 4 (`dsh-session-query\lib\index.js:1043`) apply only to the **per-child identity fold after** the corpus scan — they do not bound the scan itself.

### Three distinct things that look like "BLANK", in order of likelihood

**(a) It never returned — no timeout exists to stop it.** `NM\dsh-tool-call-timeout-policy\lib\index.js:123-124`:

```js
const timeoutMs = ctx.tools.get(exec.name, exec.agent)?.timeoutMs;
if (timeoutMs === void 0) return next();
```

A tool that declares no `timeoutMs` is **not wrapped at all** — no deadline, no cancellation. `list_agents` declares none (`list-agents.js:53-152` passes only `name`, `description`, `parameters`, `output`, `execute`). Therefore a stalled scan hangs **indefinitely**; the UI renders nothing, and that reads as blank. This is the precise mechanism for "appears to freeze".

The trigger is contention, not the tool alone: all 12 windows share one event loop, and the owner already measured **125 ms median / 193 ms max event-loop lag** with 8–12 windows (`DOCS ~\.dsh\profiles\web\cordis.patch.yml:14-20`, quoted in `PERFORMANCE-MEASURED.md`). A long GC, a synchronous `zstdDecompressSync` (`NM\dsh-session-persistence-jsonl\lib\index.js:1263`), or a saturated libuv threadpool (default 4) turns 372 serial awaits into seconds each; several sessions calling `list_agents` at once multiply it.

**(b) It returned an empty list, which is NOT blank.** `list-agents.js:109-110` renders `entries.length === 0 ? '(no subagents)'`. So a genuinely empty result is *visible text*, not blank. Two filters can make a live fleet look empty:
- `:38-39` — `if (entry.mode !== 'continuable') return undefined;` → every one-shot child is dropped;
- `:207-209` — a **live** child whose identity fold has not yet been written returns `undefined`: `if (identity === undefined || identity === null || !candidate.live.isOwnSeq(identity.seq)) return;` → "the creation window before the establishing provider appends its descriptor". Under load that window is long, so a running child can be invisible.

**(c) Blank as a mis-read of (b).** If you saw no rows, distinguish "(no subagents)" from nothing at all — they have opposite causes: (b) is a real empty result from the filters, (a) is a hung call.

**Observed in this session, honestly:** `list_agents(scope=descendants)` **succeeded** and returned my 4 children with correct `parent=` / `depth=1` annotations. The failure is **load-dependent, not deterministic** — which is exactly what a serial O(372) disk scan on a contended loop predicts. I did not reproduce the blank; I have established the mechanism and the absence of the only thing that would bound it.

**No lock is involved.** There is no mutex, queue or shared state file in this path; the contrary impression is wrong. The cost is serial I/O, and the hazard is the missing timeout.

---

## 3. Concurrency limits and knobs

Verified in the checkout. `schemas` are Schemastery (`z.object`), so each default is the code default unless the settings layer overrides it.

| Area | Knob | Default | Where | Bounds |
|---|---|---|---|---|
| agent loop | `maxParallelToolCalls` | **10** in code, **20** in `~\.dsh\settings.yaml:39` | `NM\dsh-agent-loop\lib\index.js:1465`, `:1491` (`DEFAULT_MAX_PARALLEL_TOOL_CALLS` `:1226`) | parallel-safe tool calls in flight, **per step, per session** |
| agent loop | `maxParallelSubCalls` (PTC `run_code`) | 10 | `NM\dsh-tools\lib\index.js:2575` | overlap of one program's sub-calls |
| agent loop | exclusive-tool barrier | hardcoded | `NM\dsh-tools\lib\index.js:2953-2955` | any tool not returning exactly `true` from `isConcurrencySafe()` serialises |
| agent loop | step / turn cap | **none found** | no `maxSteps|maxTurns|stepLimit|maxIterations` anywhere in `NM\@deepseek-ai\*.js` | loop bounded only by turns, goals, LLM retries |
| subagents | `maxDepth` | **3** | `NM\dsh-tool-subagent\lib\index.js:269`; enforced `NM\dsh-subagent\lib\index.js:435` | nesting depth |
| subagents | `enableRunInBackground` | **true** | `NM\dsh-tool-subagent\lib\index.js:256` | whether a `subagent` call detaches |
| subagents | **fan-out breadth** | **no cap** | grepped `maxConcurrent|maxChildren|maxAgents|maxTotal` across `dsh-subagent`, `dsh-tool-subagent`, `dsh-tool-subagent-control`, `dsh-subagent-*-in-process` → only depth | breadth throttled only by the parent's 20-call step pool |
| subagents | spawn retry / backoff | **none** | `NM\dsh-subprocess-local\lib\index.js` has no retry; spawn provider config is only `providerName` | — |
| subprocess | spawn concurrency cap | **none** | `dsh-subprocess-local` has **no `static Config` at all** | nothing bounds concurrent runner.js processes |
| jobs | `maxConcurrentJobsPerOwner` | **10** | `NM\dsh-jobs-local\lib\index.js:77`, schema `:102`, enforced `:137` | active background jobs per owner — **throws**, does not queue |
| jobs | `outputLimitBytes` | **absent = unlimited** | `NM\dsh-jobs-local\lib\index.js:135` validates only if present | retained job output |
| jobs | `waitTimeoutMs` / `maxWaitTimeoutMs` | 30000 / 600000 | `NM\dsh-tool-jobs\lib\index.js:22-23` | `job_output` wait and its cap |
| workflow | `maxConcurrentAgents` | **0 = auto → `min(16, max(1, cpus-2))`** | `NM\dsh-workflow-worker-thread\lib\index.js:851`, `:883` | concurrent workflow agents (→ 16 here) |
| workflow | `maxTotalAgents` | 1000 | same, `:852`; ceiling `:835-839` | total agents per run |
| workflow | `maxItemsPerCall` | 4096 | same, `:853` | items per `parallel()`/`pipeline()` |
| ralph | `maxRounds` | 256; deployment **64** | `NM\dsh-tool-ralph\lib\index.js:20`; `NM\dsh-base\cordis.patch.yml:416` | rounds; also the ceiling for a model-requested cap |
| ralph | concurrency | **no cap** | serial `for` loop, `NM\dsh-tool-ralph\lib\index.js:99` | rounds are strictly serial by construction |
| shell | `timeoutMs` / `maxTimeoutMs` / `maxOutputBytes` (pwsh-local) | **120000 / 600000 / 64000** | `NM\dsh-pwsh-local\lib\index.js:201-203`, clamp `:250` | foreground budget, hard cap, per-stream bytes |
| shell | bash-local twins | 120000 / 600000 / 64000 | `NM\dsh-bash-local\lib\index.js:130-132` | same |
| shell | persistent `timeoutMs` / `maxOutputChars` | 300000 / 16000 | `NM\dsh-tool-pwsh-persistent\lib\index.js:388-389` | persistent shell (unmounted) |
| shell | `tool.timeoutMs` wrapper | **absent ⇒ no wrapper** | `NM\dsh-tool-call-timeout-policy\lib\index.js:123-124` | per-tool cooperative deadline only |
| LLM | `maxRetries` | 5; owner **2** | `NM\dsh-llm\lib\index.js:232`; `~\.dsh\settings.yaml:16` | retries per failed request |
| LLM | `streamIdleTimeoutMs` | 300000; owner **60000** | `NM\dsh-llm-deepseek\lib\index.js:1390`; `settings.yaml:13` | stream idle → `TIMEOUT` |
| LLM | backoff | 500 / 10000 / 0.1; owner 500 / 5000 / 0.1 | `NM\dsh-llm\lib\index.js:233-235`; `settings.yaml:23-26` | retry pacing |
| sessions | **max sessions per server** | **no cap** | zero matches for `maxSessions|maxActiveSessions|sessionLimit|MAX_SESSIONS` in `dsh-session`, `dsh-web`, `dsh-web-app`, `dsh-host-webserver` | unbounded |
| session query | `persistedReadConcurrency` | **4** | `NM\dsh-session-query\lib\index.js:10`, `:1043` | cold-log *inspections* after the corpus scan |
| session query | `preparedSessionCacheSize` / read window | 5 / 50 | `NM\dsh-session-query\lib\index.js:12`, `:8` | prepared sessions / max read window |
| HTTP | body-size limit | **no cap** | no `content-length|bodyLimit|maxRequest|payload` in `NM\dsh-host-webserver\lib\index.js` | unbounded |
| HTTP | socket/keepalive/headers timeouts | **no cap** | `NM\dsh-host-webserver\lib\index.js:140-145` is only host/port/compression; no `setTimeout`/`requestTimeout`/`headersTimeout` in file | Node defaults |
| HTTP | max simultaneous connections | **no cap** | no `maxConnections`/`maxRequestsPerSocket`/`setMaxListeners`; server built with no options (`:245`) | unbounded |
| WS | `websocketHeartbeatIntervalMs` | 2000, **patched to 15000** | `NM\dsh-api-gateway\lib\index.js:398`; `~\.dsh\profiles\web\cordis.patch.yml:30` | ping cadence **and** pong deadline |
| WS | missed-heartbeat tolerance | **2 (hardcoded)** | `NM\dsh-api-gateway\lib\index.js:197`, `:257-259` | sockets terminated |
| MCP | `toolCallTimeoutMs` | 60000; owner 90000–180000 | `NM\dsh-mcp-client\lib\index.js:728,750`; `presets\zabz\agent.cordis.yml:440,478,492,506,519,539` | per MCP tool call |
| MCP | reconnect backoff | on, 500→30000 ms, 10 attempts | `NM\dsh-mcp-client\lib\index.js:472-477`, delay `:597` | tool-registry reconnect |
| MCP | connect / `tools/list` timeout | **not configurable** — SDK default 60000 | `NM\dsh-mcp-client\lib\index.js:642`, `:87-92` pass no options | initial connect, discovery |
| retention | spill `maxInlineBytes` | schema-required; deployment **50000** | `NM\dsh-spill-policy\lib\index.js:74`; `NM\dsh-base\cordis.patch.yml:386` | inline bytes before spill |
| retention | spill `cleanupPeriodDays` | 30, swept **once per process at activation** | `NM\dsh-spill-local\lib\index.js:484`, `:499-505` | spill retention — no byte cap, no keep count |
| goals | `defaultMaxGoalRounds` | 256 | `NM\dsh-goal\lib\index.js:588` | autonomous continuation rounds |
| presets | preset mount | **once per preset**, standing scope | `NM\dsh-agent-presets\lib\index.js:1085-1097`, single-flight `:1768-1802` | MCP/plugin instance count per *host process* |

### Caps that exist today

| knob | default | where set | what it bounds |
|---|---|---|---|
| `agent-loop.maxParallelToolCalls` | 10 (code) / **20** (this host) | `~\.dsh\settings.yaml:39`; `NM\dsh-agent-loop\lib\index.js:1491` | parallel tool calls per step per session — multiplies to 20×12 = 240 in flight across 12 windows with no machine-wide budget |
| `maxConcurrentJobsPerOwner` | 10 | `NM\dsh-jobs-local\lib\index.js:77,102,137` | background jobs per owner; hard throw |
| `maxDepth` (subagent) | 3 | `NM\dsh-tool-subagent\lib\index.js:269` | subagent nesting depth |
| workflow `maxConcurrentAgents` | 0 → `min(16, cpus-2)` | `NM\dsh-workflow-worker-thread\lib\index.js:851,883` | workflow agents in flight |
| workflow `maxTotalAgents` | 1000 | `NM\dsh-workflow-worker-thread\lib\index.js:852` | agents per workflow run |
| ralph `maxRounds` | 256 / deployment 64 | `NM\dsh-tool-ralph\lib\index.js:20`; `NM\dsh-base\cordis.patch.yml:416` | ralph rounds |
| pwsh/bash `timeoutMs` | 120000, cap 600000 | `NM\dsh-pwsh-local\lib\index.js:201-202` | one foreground shell call |
| pwsh `maxOutputBytes` | 64000 | `NM\dsh-pwsh-local\lib\index.js:203` | retained bytes per stream |
| `tool.timeoutMs` | **none unless declared** | `NM\dsh-tool-call-timeout-policy\lib\index.js:123-124` | a tool without it cannot time out — **`list_agents` declares none** |
| `llm-deepseek.streamIdleTimeoutMs` | 300000 / **60000** | `~\.dsh\settings.yaml:13` | stream idle gap |
| `llm retryPolicy.maxRetries` | 5 / **2** | `~\.dsh\settings.yaml:16` | LLM request retries |
| `persistedReadConcurrency` | 4 | `NM\dsh-session-query\lib\index.js:1043` | cold-log inspections (not the corpus scan) |
| MCP `toolCallTimeoutMs` | 60000 / 90000–180000 | `presets\zabz\agent.cordis.yml:440-539` | one MCP tool call |
| MCP reconnect | 500→30000 ms, 10 tries | `NM\dsh-mcp-client\lib\index.js:472-477` | reconnect attempts |
| spill `maxInlineBytes` | 50000 | `NM\dsh-base\cordis.patch.yml:386` | inline tool-result bytes |
| spill `cleanupPeriodDays` | 30, once at activation | `NM\dsh-spill-local\lib\index.js:484` | spill file age |
| `websocketHeartbeatIntervalMs` | 2000 / patched **15000** | `~\.dsh\profiles\web\cordis.patch.yml:30` | WS ping + pong deadline |
| `defaultMaxGoalRounds` | 256 | `NM\dsh-goal\lib\index.js:588` | goal continuation rounds |
| **max sessions per server** | **none** | — | — |
| **subagent fan-out breadth** | **none** | — | — |
| **subprocess spawn concurrency** | **none** | — | — |
| **HTTP body size / conn count / socket timeouts** | **none** | — | — |
| **agent-loop step cap** | **none** | — | — |

---

## 4. MCP servers

### How they start

`NM\dsh-mcp-client\lib\index.js:40-50` builds the transport; for stdio (`:42-47`) it delegates to the SDK, which owns the spawn:

```js
case "stdio": return new StdioClientTransport({ command, args, env: buildChildEnv(config.env), cwd })
```

`node_modules\@modelcontextprotocol\sdk\dist\esm\client\stdio.js:1,65` `import spawn from 'cross-spawn'` → `spawn(command, args, {...})`. The bridge never calls `child_process` itself. Connect is **eager**: `NM\dsh-mcp-client\lib\index.js:677` `let settling = connectGeneration(true);`.

### How many, and per what — the key correction

**Not per session.** The bridge is per *plugin instance*, and the **preset** layer mounts each instance exactly once per host process: `NM\dsh-agent-presets\lib\index.js:1085-1097` — "mounted ONCE per preset under a standing scope and joined by every agent that names it … its plugin instances … exist exactly once"; single-flight mount at `:1768-1802`. So the declared set is **6 processes for the whole engine**, shared by all 12 windows. There is **no pool, no lazy connect and no idle disconnect** in the bridge (grep for `pool|warm|keepAlive|lazy|idle` → none; the only cross-instance structure is a duplicate-name guard, `:736` `const activeServerNames = new WeakMap()`).

The ACP path *is* per-session — `NM\dsh-acp\lib\index.js:216-218 mountAcpMcpServers(agentCtx, …)` looping `agentCtx.plugin(McpClient, config)`, called from per-session setup `:699-702`, `:717-721`. DSH web/CLI does not use it for these presets.

### What is declared (`~\.dsh\.agent-presets\zabz\agent.cordis.yml`, mirrored from `~\code\harness-config\presets\zabz\agent.cordis.yml`)

| id (line) | serverName | command → npm | tools | win32? |
|---|---|---|---|---|
| `mcp-secretary` `:418-441` | secretary | `ssh -T -o BatchMode=yes … secretary-ts /home/zabz/…/.venv/bin/python …/ps_mcp_server.py` | 14 | yes (`:420` `disabled: !!js process.platform !== 'win32'`) |
| `mcp-secretary-linux` `:452-462` | secretary | local venv python | 14 | no (`:454`) |
| `mcp-firecrawl` `:467-479` | firecrawl | `python mcp_launcher.py firecrawl` → **`npx -y firecrawl-mcp`** | 27 | yes |
| `mcp-jina` `:481-493` | jina | launcher → **`npx -y mcp-remote https://mcp.jina.ai/v1`** | 22 | yes |
| `mcp-context7` `:495-507` | context7 | launcher → **`npx -y @upstash/context7-mcp@latest`** | 2 | yes |
| `mcp-fetch` `:509-520` | fetch | **`npx.cmd -y mcp-fetch-server`** | 6 | yes |
| `mcp-playwright` `:525-540` | playwright | **`npx.cmd @playwright/mcp@latest`** `--headless --no-sandbox --output-dir …` | 26 | yes |

**97 bridged tools on Windows**, present in every request's tool schema.

### The `npx -y … @latest` indirection — exactly as suspected, and worse than expected

Five of six rows resolve through npm, and on Windows each costs **four** processes, because `cross-spawn\lib\parse.js:36,57-58` must wrap a `.cmd` (`needsShell = !/\.(com|exe)$/i.test(commandFile)` → `cmd.exe /d /s /c …`):

```
cmd.exe /d /s /c "npx.cmd -y mcp-fetch-server"
  └ node.exe ...\npm\bin\npx-cli.js "-y" "mcp-fetch-server"     ~97-99 MB
      └ cmd.exe /d /s /c mcp-fetch-server                       ~5 MB
          └ node.exe ...\mcp-fetch-server\dist\index.js         ~64-160 MB
```

**The `npx-cli.js` process stays resident for the whole life of the server** — measured live at 97–103 MB each, 9 of them alive at once. That is ~0.9 GB of pure npm shim, and `@playwright/mcp@latest` / `@upstash/context7-mcp@latest` additionally re-resolve registry metadata on every spawn.

### The finding that matters most: MCP sets leak on remount

LIVE start times of MCP-family processes against the engine's start (`21124` started **2026-09-14 18:27:48**):

| started | set observed |
|---|---|
| 9/14 18:29:10–18:29:22 | fetch (`11720`→`16600`→`20908`→`31240`) + playwright (`27376`→`30252`) — the initial mount, 82 s after engine start |
| 9/15 18:42:15–18:42:20 | **another** fetch (`20108`→`20300`→`32184`→`33500`) + playwright (`21752`→`32464`) |
| 9/15 18:58:04–18:58:11 | **another** fetch (`16780`→`17712`→`21876`→`22900`) + playwright (`3812`→`18564`) |
| 9/15 21:13:56–21:14:29 | a full launcher set: context7 (`38004`→`15252`→`35048`→`41604`), firecrawl (`10104`→`17524`→`5564`→`38180`), jina (`32000`,`27688`,`16640`→`40460`,`10104`,`38004`) |

**Four `mcp-fetch-server` stacks and three `@playwright/mcp` stacks are alive simultaneously, the oldest 27 hours old and still holding memory.** The engine never died (same pid throughout), so these are not pre-restart orphans — they are **remount residue**. The code that explains it is the preset remount on composition-stamp change (`NM\dsh-agent-presets\lib\index.js:1772-1775`), plus the fact that MCP children are spawned by the SDK via `cross-spawn`, **not** through `dsh-subprocess-local`, so they are **outside any Win32 Job object** and nothing reaps them when their generation is discarded. The bridge's own guard (`NM\dsh-mcp-client\lib\index.js:658-663`, stopping reconnect "to avoid overlapping server processes") bounds *one* generation, not the accumulation across generations.

LIVE cost of the residue: MCP-family private commit ≈ **2.1 GB** (playwright 21 procs / 1.16 GB, fetch 12 / 0.61 GB, jina 3 / 0.20 GB, firecrawl 3 / 0.16 GB, context7 3 / 0.16 GB, launcher wrappers 6 / 30 MB, `ps_mcp_server.py` 2 / 6 MB) — on top of ~0.9 GB of `npx-cli.js`. That is the single most wasteful and most easily reclaimed block on the machine.

---

## 5. Persistence and locks

### File count per session

One session = **2 files**, both steady-state:

1. **The log.** `NM\dsh-session-persistence-jsonl\lib\index.js:913-915` `sessionDir(root,cwd,id) = join(projectDir(root,cwd), encodeSegment(id))`; `:744-747` suffix `".jsonl"` + `".zstd"`; root from `NM\dsh-base\cordis.patch.yml:110-113` (`root: !!js dshHomePath('sessions')`). Verified on disk: `~\.dsh\sessions\--C-Users-ezabz-code--\<id>\session.v3.jsonl.zstd` — **372 dirs, exactly one file each, all identically named.** No index, no manifest, no per-session sqlite, no lock file. Lazily materialised (`README.md:74`); nothing deletes logs (`README.md:157`).
2. **The projection-cache record.** `~\.dsh\storages\session_projcache\sessions\<id>.json` (LIVE: 353 files / 9.42–9.46 MB). Spec `NM\dsh-session-projection-cache\lib\index.js:90`, opened `:151-153`.

Transient third file only during historical-format migration: `session.migration.<token><suffix>.tmp` (`:1950`). **LIVE: one leaked atomic-write temp sits unreaped** — `~\.dsh\storages\session_projcache\sessions\.ac103ce8-6d08-4b4c-83cd-0d77018c7455.tmp`, 82,179 B, mtime 9/14 18:27.

**Not sqlite.** `NM\dsh-base\cordis.patch.yml:129-133` mounts `session-query-sqlite` with `path: ':memory:'` and `openAt: never` → search disabled, `DatabaseSync` never opened, **no `.db` on disk** (verified: zero `*.db`/`*.sqlite` under `~\.dsh`).

### Locks — no global lock exists

Only a **per-session lease**. `NM\dsh-session-persistence-jsonl\lib\index.js:642` `LEASE_FILENAME = "session.lock"`. On Windows it is a **named kernel semaphore, not a file** — `:555-557`:

```js
const name = `Local\\dsh-session-lock-${createHash("sha256").update(resolve(path).toLowerCase()).digest("hex")}`;
```

acquired via `acquireLockHandleWin32` (`:481`, `:555-565`), `EBUSY → SessionAlreadyOwnedError` (`:677`), released by `ReleaseSemaphore` (`:571-575`). POSIX uses `open(path,"w")` + `tryLockExclusive(handle.fd)` (`:686-692`) with inode re-verify (`:695-700`), never unlinked (`:718-728`), and **deliberately no expiry** — "a live but wedged holder keeps the lock until its process exits" (`lib\types\lease.d.ts:11-13`).

**There is no global lock under `~\.dsh`.** LIVE: **0 `*.lock` files anywhere under `~\.dsh`**. Other lock files would come only from `NM\dsh-atomic-write\lib\index.js:105,122-145` (`withFileLock`, `.lock` sibling via `wx`, 2 s wait) — used by credentials/settings/llm-deepseek/app-boot, **not** by session persistence, storage-json, or the projection cache.

Gap worth recording: `NM\dsh-storage-json\lib\index.js:14-15` has **no lock and is last-write-wins by design** ("a unit file has exactly one writer per process and last-write-wins is correct"). Two engines on one `~\.dsh\storages` would silently clobber KV state. This reinforces `mode: single`.

### What can make one slow session stall another

No shared worker and no shared lock. `lib\worker.cjs` is **not** the write path — it is the historical-format **migration verifier**: spawned per verification (`:1444-1468`, `:1491` `new Worker(entry, options)`), terminated after one message (`:1502`), self-identifying at `worker.cjs:11632` `if (node_worker_threads.parentPort === null) throw new Error("migration verifier requires a parent port")`. Bounded process-wide by `MAX_CONCURRENT_VERIFIERS = 2` (`:1400`) in a module-level singleton (`:1443`), FIFO queue (`:1421-1431`), **no timeout**. Normal appends are plain `fs/promises` on the main thread (`:3046-3073`), 200 ms batch window (`:188-191`), single-flight drain (`:198-219`), **per-handle** chain (`:33`, `:251-255`).

The real couplings, all of which land on the **shared event loop**:

1. **One event loop serves all 12 windows.** Already measured by the owner: 8–12 windows → **125 ms median / 193 ms max lag**, and "a slow EventSource/journal read in one window can stall the loop long enough to kill every window's socket at once" (`DOCS ~\.dsh\profiles\web\cordis.patch.yml:14-20`).
2. **Synchronous zstd on the main thread.** `NM\dsh-session-persistence-jsonl\lib\index.js:1207` `handle.writeSync(this.stream._defaultFlushFlag, input, …)` and `:1263` `zstdDecompressSync(source.subarray(start, end))`; the loop yields only between chunks (`:1747-1753`, `:1921`). Largest logs are 12.8 MB / 9.5 MB compressed.
3. **`readdirSync` at backend construction** — `:3211` `readdirSync(this.root)` (`assertUsableRoot`).
4. **One write chain per storage domain, and one domain for every session's projection checkpoint.** `NM\dsh-storage-domain\lib\index.js:119-120`, `enqueue` `:221-224`; each checkpoint is a whole-file fsync'd atomic rewrite (`NM\dsh-storage-json\lib\index.js:25-41`), preceded by `await this.ctx.sessions.flush(session)` (`NM\dsh-session-projection-cache\lib\index.js:266`). Trigger cadence `writeEveryEvents: 200` / `writeIntervalMs: 5000` plus mandatory create / `turn/end` / dispose (`NM\dsh-base\cordis.patch.yml:164-166`). A 190 KB fsync for session A delays session B's checkpoint. Writes are fail-soft and not awaited (`:328-334`), so this queues rather than hard-blocks.
5. **libuv threadpool default 4** serves all fs/zlib async work. Twelve sessions flushing per tool call and per request, each `open`+`write`+`fsync`+`close` plus zstd, can saturate it — at which point *all* file operations queue behind each other. This is the mechanism by which one busy session slows another.
6. `session-query-sqlite`'s global `_serialized`/`_tail` (`:508`, `:621-644`) around synchronous `new DatabaseSync` (`:50-51`) is **inactive** here (`openAt: "never"`, `:593-596`).

---

## 6. What exists for sharing one server across Windows

**Yes — the GUI already shares one server process across tabs, and that is the configured and only supported mode.**

`~\code\harness-config\multi-window\windows.json:14` `"mode": "single"`, `:15` `"primaryPort": 3099`. The file's own comment (`:2`) states the design and the reason:

> "ONE server, MANY windows is the default because each server process eagerly starts its own five stdio MCP bridges (~1.4 GB per server measured 2026-09-11). Set mode to 'multi' only when you deliberately want a second isolated engine."

and `:5`:

> `"multi": "UNSUPPORTED on a shared DSH_HOME - do not use. Two dsh web processes on one home have been observed writing duplicate sequence numbers into one session log and making the whole history unloadable … It is also ~1.4 GB per engine against ~3 GB total for one engine with twelve windows."`

README, `dshw.ps1:6-7`: *"One DSH server process per window slot, on its own port, with its own isolated browser profile"* — i.e. a slot owns a port and a browser profile; a **window** is just a browser attached to a port.

Live confirmation: `~\.dsh\multi-window\windows-registry.json` has **w1…w12 all `open: true, port: "3099"`** — twelve windows, one engine. `windows.log` shows each launched as `msedge --app=http://127.0.0.1:3099/?token=… --user-data-dir=…\browser\w<N> …` with the lean-flag set. `state.json:2-11` holds exactly one slot.

**When a second server IS started** (`dshw.ps1`):

- `:981-991` — in `single` mode `$needed` is only the slots whose `port -eq (Get-PrimaryPort)`; otherwise (multi) all enabled slots.
- `:993-1005` — the gate: `$liveOwner = Get-PortOwner ([int]$slot.port) $listenTable; if ($liveOwner -and -not $Force) { $already++; continue }` — **a slot with a live listener is never started again.** A second engine appears only for a *different port in `multi` mode*, or under `-Force` (which first stops the holder to avoid `EADDRINUSE`, `:998-1003`).
- `:1010-1014` — *"SEQUENTIAL on purpose. The parallel path (Start-SlotServerParallel) … was built for the abandoned 'one engine per window' design and it hung twice on 2026-09-11"*.
- `:1101` — `"WARNING: {0} other dsh web against this DSH_HOME ({1}) - one writer only"`.
- Engine launches deliberately go through **Task Scheduler** (`:593-596`, `:627`) rather than `Start-Process`, because `:510-511` — *"A child started directly by this script dies with the job object that owns it. Measured 2026-09-11."*
- `:420` — the launcher's process classifier explicitly excludes *"the subprocess runners or MCP bridges"* when looking for engine processes, so the ~29–58 MB `runner.js` population is correctly not mistaken for extra servers.

LIVE cost of the shared-engine arrangement, and where it actually goes:

| class | count | private commit |
|---|---|---|
| `msedge` (the 12 windows) | 102 | **8.18 GB** |
| MCP family incl. `npx-cli.js` shims | ~50 | **~2.1 GB** (+0.9 GB npx) |
| DSH engine `21124` | 1 | **3.17 GB** |
| `dsh-subprocess-local runner.js` | 15–19 | **~0.44 GB** |

Per-window browser cost measured by the owner: **~454 MB/window with lean flags** vs ~770 MB default (`DOCS PERFORMANCE-MEASURED.md:71-83`); my 8.18 GB / 12 ≈ 680 MB/window, consistent with 12 separate `--user-data-dir` profiles and some heavier tabs.

Two levers the launcher already applies and one it does not: windows are **staggered** 250 ms apart (`PERFORMANCE-MEASURED.md:64`) and lean Edge flags cut the browser side 41% (`:76-80`); but `WindowsMode` defaults to **`no`** (`dshw.ps1:42`) — engines and windows are separate intentions, and `windows.json` enables only **8** slots while **12** are open, so the extra four were started ad hoc.

---

## 7. Built-in telemetry / health endpoint

**There is no health endpoint.** `NM\dsh-host-webserver\lib\index.js:96-101` — the webserver "knows no harness concepts and serves no files"; every route belongs to a feature plugin, registered via `register({kind:'exact'|'prefix',path,handler})` (`:176`), `registerUpgrade` (`:190`), `registerFallback` (`:205`); match order exact → longest prefix → fallback (`:322-331`), and with no fallback a miss is 404 (`:238-241`).

Searched `/health`, `/healthz`, `/metrics`, `/status`, `/api/health`, `/api/status`, and express-style `.get(`/`.post(`/`app.use(`/`router.`/`addRoute(` across the host packages: **not found.** Only false positives (`agent/status` at `NM\dsh-agent\lib\invariant.js:11`; `api-session/status` at `NM\dsh-api-session-controller\lib\index.js:2755`). Live proof, two read-only GETs with no token:

- `GET http://127.0.0.1:3099/` → **401**, `dsh web authentication required; reopen the URL printed by dsh web.`
- `GET http://127.0.0.1:3099/healthz` → **404** (static fallback miss, `NM\dsh-host-frontend-static\lib\index.js:67-71`)

**No endpoint or tool reports live session / agent / process / CPU / memory counts.** `NM\dsh-session-stats\lib\index.js:28-37` is a *per-session* projection (`turns, steps, llmMs, toolMs, ttftMs, ttftSteps, decodeMs, decodeTokens`) registered on `ctx.sessionProjections` (`:195`); `NM\dsh-session-telemetry\lib\index.js:46-102` is a record-handoff seam whose only aggregate is a private `adopted = new Set()` (`:55`). Grepping `process.memoryUsage`, `loadavg`, `cpuUsage(`, `freemem`, `totalmem`, `process.uptime` across host code → **no matches**.

The nearest thing to a status surface is `NM\dsh-host-plugin-inventory` — a read-only projection of current Loader entries over trusted client RPC; that is loaded plugins, not counts.

**OTel exists and is mounted by default but emits log records only.** `NM\dsh-session-telemetry-otel\lib\index.js:137-147` builds `LoggerProvider` + `BatchLogRecordProcessor` + `OTLPLogExporter`; instrumentation scope `:148`. **No meters/gauges**, so no CPU/memory/session-count series. Configured in `NM\dsh-base\cordis.patch.yml:184-197`: default URL `https://harness-telemetry.deepseeksvc.com/v1/logs`, gzip, `timeoutMillis: 1000`, batch 2048, `scheduledDelayMillis: 10000`; `DSH_TELEMETRY_OTLP_URL` overrides. Mode `FEEDBACK_ONLY` (`:187`), and only a new feedback submission authorizes capture (`:165-179`); `emit()` is a deliberate no-op (`:186`) and `DISABLED` builds no transport (`:115-122`). A row cannot be disabled by config — only by the launcher setting `DSH_TELEMETRY_DISABLED` (`:170-173`). In this session's environment `DSH_TELEMETRY_DISABLED`, `DSH_TELEMETRY_MODE` and `DSH_TELEMETRY_OTLP_URL` were all empty.

**Per browser tab: two long-lived connections, and no cap on either.**
- `GET /plugins/events` (SSE) — `NM\dsh-client-hmr\lib\client.js:98` `new EventSource(EVENTS_ENDPOINT)`; server holds `connections = new Set()` (`NM\dsh-client-hmr\lib\index.js:114-129`) and writes only one `: connected` line (`:121`), with no keepalive comment.
- `GET /api/remote.mux` (WebSocket) — `NM\dsh-api-gateway\lib\client.js:402`; server `new WebSocketServer({ noServer: true })` with an unbounded `connections` Set (`NM\dsh-api-gateway\lib\index.js:203-204`, `:231-234`), ping every 2 s and killed after 2 missed (`:197`, `:253-266`) — **patched to 15000 ms on this host**.

No `maxConnections`, `maxRequestsPerSocket`, `keepAliveTimeout` or `setMaxListeners` anywhere; `NM\dsh-host-webserver\lib\index.js:245` creates the http server with no options. So 12 windows ≈ 24 persistent sockets and nothing refuses a 13th or a 50th.

**Auth is per process, not per window.** A 32-byte base64url launch token lives in a `WeakMap` keyed by the root application context (`NM\dsh-client-connection\lib\index.js:227`, `:240-246`), surfaced only as `?token=` (`:370-377`); `GET /` with a matching token 303s to `/` plus an `HttpOnly; SameSite=Strict` HMAC cookie per Host authority (`:386-425`), enforced with `timingSafeEqual` (`:275-279`). All 12 windows share one token; revocation is a process restart. Known gap: the static fallback authenticates **only the index** (`NM\dsh-host-frontend-static\lib\index.js:59-66`, `:95`), so non-index assets under the dist root are served unauthenticated once the fallback is reached.

---

## Priority reading of the whole audit

Nothing here is a mystery about DSH's *design* — the design is one process, many windows, and the launcher already enforces it. The freeze is an arithmetic problem on a 31.6 GB machine whose commit charge is 36.57 GB, and DSH's own share of it decomposes into four multipliers that are all *duplicated work*, not inherent load:

1. **MCP remount residue, ~2.1 GB + 0.9 GB of `npx-cli.js`.** Four fetch stacks and three playwright stacks alive at once, oldest 27 h. MCP children are outside any Job object, so nothing reaps a discarded generation. This is the largest reclaimable block and needs no design change — only reaping.
2. **`npx` as the MCP transport, ~0.9 GB and a registry resolve per spawn.** A resolved, pinned `node <abs path>\dist\index.js` per server removes four processes and the network dependency per server.
3. **~64 MB per shell tool call, of which ~57 MB is a Job-owner process that exists only to hold a handle.** `dsh-tool-pwsh-persistent` is already written and shipped (`NM\dsh-tool-pwsh-persistent\lib\index.js:237`) precisely to avoid this; the mounted `tool-pwsh` row (`presets\zabz\agent.cordis.yml:151-152`) is the one-shot variant.
4. **12 browser windows at ~680 MB each = 8.18 GB, the single largest item on the machine.** The lean flags are already applied; the window *count* is the variable, and growing the session corpus makes each one's boot read a bigger `~/.dsh`.

And one latent hazard that is not yet biting: **`list_agents` can hang with no timeout at all**, because it re-scans 372 session logs serially on every call and declares no `timeoutMs` for the wrapper at `NM\dsh-tool-call-timeout-policy\lib\index.js:123-124` to arm. That is the exact code that explains a blank `list_agents`, and it will get worse on its own as `~/.dsh/sessions` grows.
