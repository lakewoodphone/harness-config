# Cost model for N concurrent DSH sessions — measured

**Author:** Zabz (delegated subagent, parent `session-621bd168-5b2e-44f5-b98b-e24192ae03e8`)
**Host measured:** `ZABZ-YOGA` (Windows 11 laptop)
**Measurement window:** 2026-09-11 13:02:32 → 13:12:43 local (-04:00). All timestamps below are local.
**Method:** adapted from the assigned plan; every deviation is stated in §9.

Every number in this document carries its exact command and the time it was read. `ESTIMATE:` marks derived
numbers. `UNVERIFIED:` marks claims I could not establish from evidence.

---

## 0. Headline

| | Measured |
|---|---|
| Idle `dsh web` server process, empty `DSH_HOME`, no session, no MCP | **196 MB** WS / **198 MB** private (PID 43016, 13:08:05) |
| Idle `dsh web` server process, fully bootstrapped, no session, no MCP | **196.8 MB** WS / **200 MB** private (PID 16860, 13:10:57) |
| **Live** `dsh web` server, this very session, **17 children** (MCP + subprocess runners) | **878.4 MB** WS / **915.3 MB** private (PID 59460, 13:10:57) |
| Per `dsh-subprocess-local` runner child | **57.3 MB** mean WS (n=10, 13:11:27) |
| Per MCP server, fully resolved | **~204 MB** (ESTIMATE from 3 measured process layers, 13:07) |
| Time to `dsh web:` URL line, **fresh** `DSH_HOME` (cold bootstrap) | **~148 s** (13:04:09.517 → first observed 13:06:37) |
| Time to `dsh web:` URL line, **existing** `DSH_HOME` | **≤ 40 s**; 0 output at +30 s, URL present at +40 s (13:08:27.360 → +40 s) |

**The single most important structural fact:** the per-session marginal cost of *another window on one server*
is a browser renderer, not a server. The per-session marginal cost of *another server process* is
**196 MB idle, ~1.6 GB once its preset's 5 MCP servers and its own subprocess children are live**.

---

## 1. Host baseline

Command (13:02:32):
```powershell
(Get-CimInstance Win32_ComputerSystem | Select-Object Name,NumberOfLogicalProcessors,@{n='TotalRAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB,2)}}) | Format-List
Get-CimInstance Win32_OperatingSystem | Select-Object @{n='FreePhys_GB';e={[math]::Round($_.FreePhysicalMemory/1MB,2)}},@{n='TotalVisible_GB';e={[math]::Round($_.TotalVisibleMemorySize/1MB,2)}} | Format-List
Get-PSDrive C | Select-Object Used,Free
```

Raw (13:02:32):
```
Name                      : ZABZ-YOGA
NumberOfLogicalProcessors : 22
TotalRAM_GB               : 31.61
FreePhys_GB               : 7.66
TotalVisible_GB           : 31.61
C: Used 403897348096   Free 107018158080          # 376.2 GB used / 99.7 GB free
```

At 13:10:35 a second sample gave `FreePhys_GB=6.66`, `TotalVisible_GB=31.61`,
`CommittedLimit_GB=65.41`, `FreeVirtual_GB=29.21`.

> **Correction to the task premise.** The assignment specified "a laptop with 8-16 GB RAM". **This laptop has
> 31.61 GB of physical RAM** and 22 logical processors. The 8-16 GB figure is wrong for `ZABZ-YOGA`. The
> binding constraint on this machine is **free** RAM, not total: only **7.66 GB was free** at 13:02:32 and
> **6.66 GB at 13:10:35**, because ~23-25 GB was already in use by Chrome, Edge, two Android emulator/CI jobs
> and 30 `node.exe` processes. Every extrapolation in §7 is therefore given twice: against **total** RAM and
> against the **free** RAM actually observed.

`ZABZ-TECH` (i9 / 64 GB) was **not reachable from this session** — home and office are separate networks and
the only path is Tailscale. I did not attempt to measure it. `UNVERIFIED:` all ZABZ-TECH figures; the 64 GB
figure is taken from the brief, not measured.

---

## 2. Live DSH server and its process tree

### 2.1 The server itself

Command (13:02:52, then repeated 13:10:57):
```powershell
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Select-Object ProcessId,ParentProcessId,Name,@{n='WS_MB';e={[math]::Round($_.WorkingSetSize/1MB,1)}},CommandLine
Get-NetTCPConnection -LocalPort 3080 -State Listen
```

Raw:
```
LocalAddress LocalPort OwningProcess
127.0.0.1         3080         59460

port 3080 PID 59460 : WS_MB=878.4 Private_MB=915.3 Handles=454 Threads=14 Children=17 Created=12:46:08   # 13:10:57
```

Command line: `"node" "...\@deepseek-ai\dsh\lib\bin.js" web`. Version `0.1.5-rc.1`
(`node ...\@deepseek-ai\dsh\lib\bin.js --version`, 13:03:47).

**Measurement caution, stated because it affects every reading:** the same PID 59460 read **757.4 MB at
13:02:52**, **878.4 MB at 13:10:57** and **961.5 MB at 13:11:48**. It was actively serving this session the
whole time. A single reading of an active server is a snapshot, not a constant.

### 2.2 Children (13:10:57)

```
PID    WS_MB  Kind                   Cmd
39416  4.10   python                 ...personal-secretary-mvp\.venv\Scripts\python.exe  [MCP launcher]
5644   4.10   python                 (same)
50860  4.10   python                 (same)
1896   4.10   python                 (same)
58924  10.70  cmd.exe                /d /s /c "npx.cmd -y mcp-fetch-server"
31108  10.70  cmd.exe                /d /s /c "npx.cmd @playwright/mcp@latest --headless ..."
50512  58.00  dsh-subprocess-runner  node ...\dsh-subprocess-local\lib\runner.js -- pwsh ...
26636  57.80  dsh-subprocess-runner  (same)
12680  58.10  dsh-subprocess-runner  (same)
30632  58.00  dsh-subprocess-runner  (same)
22464  58.00  dsh-subprocess-runner  (same)
41008  58.30  dsh-subprocess-runner  (same)
7204   57.10  dsh-subprocess-runner  (same)
34756  56.80  dsh-subprocess-runner  (same)
42560  56.60  dsh-subprocess-runner  (same)
28748  58.10  dsh-subprocess-runner  (same)
```

### 2.3 MCP servers — one full set per server process

Command (13:02:52):
```powershell
Get-CimInstance Win32_Process -Filter "Name='node.exe' OR Name='pwsh.exe'" |
  Select-Object ProcessId,ParentProcessId,Name,@{n='WS_MB';e={[math]::Round($_.WorkingSetSize/1MB,1)}},CommandLine
```

Measured MCP-related processes (13:02:52), by declared server:

| MCP server | Processes measured | Working sets (MB) |
|---|---|---|
| firecrawl | `npx-cli.js -y firecrawl-mcp` | 95.1 |
| firecrawl | `...\_npx\12b05d...\firecrawl-mcp\dist\index.js` | 93.9 |
| jina | `npx-cli.js -y mcp-remote https://mcp.jina.ai/v1 ...` | 93.7 |
| jina | `...\_npx\705d23...\mcp-remote\dist\proxy.js` | 89.0 |
| context7 | `npx-cli.js -y @upstash/context7-mcp@latest` | 94.7 |
| context7 | `...\_npx\c35ab7...\@upstash\context7-mcp\dist\index.js` | 80.5 |
| fetch | `npx-cli.js -y mcp-fetch-server` | 95.2 |
| fetch | `...\_npx\9d6226...\mcp-fetch-server\dist\index.js` | 91.8 |
| playwright | `npx-cli.js @playwright/mcp@latest --headless ...` | 94.2 |
| playwright | `...\_npx\9833c1...\@playwright\mcp\cli.js --headless ...` | 90.9 |

Attribution to server PID 59460 was established by the parent-process chain at 13:10:57, e.g.
`59460 → 58924 cmd.exe mcp-fetch-server → 48848 npx-cli.js → 57392 mcp-fetch-server\dist\index.js`.

**Why this multiplies.** The MCP servers are declared as **stdio** MCP clients, not remote ones — read at
13:11:21 from `C:\Users\ezabz\code\harness-config\presets\zabz\agent.cordis.yml` lines 387-460:
```yaml
- id: mcp-firecrawl
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: firecrawl
    transport: stdio
    command: 'C:\Users\ezabz\code\personal-secretary-mvp\.venv\Scripts\python.exe'
    args: ['...mcp_launcher.py', firecrawl]
```
and `@deepseek-ai/dsh-mcp-client\lib\index.js:42`: `case "stdio": return new StdioClientTransport({ command: config.command, ... })`.
`StdioClientTransport` (imported from `@modelcontextprotocol/sdk/client/stdio.js`, line 6) **spawns a child
process**. Therefore **every DSH server process that loads this preset spawns its own copy of all five MCP
servers.** `ESTIMATE:` this is inference from configuration plus the SDK contract; I observed it empirically
only for the one live server, which I could not restart.

---

## 3. Disposable server test (one extra `dsh web`)

### 3.1 `DSH_HOME` can be pointed elsewhere — yes

`C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\dsh-home-paths\lib\index.js` (read 13:03:44):
```
15  const DSH_HOME_ENV = "DSH_HOME";
65   * Precedence, highest first: an explicit configured path, `$DSH_HOME`, then
67   * whitespace-only `$DSH_HOME` is treated as unset, so a blank override never
74  const fromEnv = env[DSH_HOME_ENV];
```
`dsh-app-boot\lib\index.js:1009` confirms `DSH_HOME` is **bootstrap-only** — only the inherited environment may
supply it, never a `.env` file.

**Verified working.** Server 3099 was launched with `DSH_HOME=C:\Users\ezabz\code\_scratch\multiwindow\dshhome`:
```powershell
$env:DSH_HOME="$s\dshhome"
& node "...\@deepseek-ai\dsh\lib\bin.js" web --no-open --port 3099
```
It bootstrapped a **complete parallel install**: `profiles\web\{package.json,cordis.yml,cordis.patch.yml,pnpm-workspace.yaml}`,
a full `profiles\node_modules` (all `@deepseek-ai` packages plus ~200 third-party deps), `.anonymous-user-id`
(37 B), `.credentials.yaml` (161 B), `storages\workspace.json` (199 B). Everything landed under the scratch
`DSH_HOME`; disk footprint outside `node_modules` was 7 files / 1134 bytes.

**It never touched `C:\Users\ezabz\.dsh`.** Diff against a 601-row baseline taken at 13:04:06:

| Time | Path | Cause |
|---|---|---|
| 13:05:34 | `.dsh\multi-window\logs` | **not mine** — parent agent's `logs-test`/test3 harness work |
| 13:05:36 | `.dsh\multi-window\browser` | **not mine** |
| 13:09:26-13:10:02 | `.dsh\multi-window\test3.json`, `logs-test\3081.log`, `logs-test\3081.err.log` | **not mine** — another agent's :3081 test |

Baseline 601 entries → 609 entries; **none of the 8 new paths were produced by my two servers.** They are
other agents' test artifacts (`logs-test\3081.log` etc.) appearing in the shared home. I did not create,
modify or delete anything under `C:\Users\ezabz\.dsh`.

### 3.2 Launch timing

| Phase | 3099 (fresh home) | 3100 (existing home) |
|---|---|---|
| `dsh web` invoked | 13:04:09.517 | 13:08:27.360 |
| profile files written | 13:04:09.985 | — (reused) |
| `node_modules` populated | 13:04:10 - 13:04:11 | — (reused) |
| `.credentials.yaml`, `storages\` | 13:04:51 | — (reused) |
| URL line first observed | 13:06:37 (**+147.5 s**) | t+30 s: no output; t+40 s: URL present (**+30 to +40 s**) |

The 3100 poll is reproducible evidence (10 s granularity):
```
t0 = 13:08:27.360
  t+10s  out_len=0   url_present=no   ws_MB=122.6
  t+20s  out_len=0   url_present=no   ws_MB=352.6
  t+30s  out_len=0   url_present=no   ws_MB=423.2     <- peak
  t+40s  out_len=82  url_present=YES  ws_MB=401.4     <- URL printed
```
Startup transient peaks near **423 MB** before settling back. `UNVERIFIED:` the exact +147.5 s for 3099 is
bounded by my polling interval, not measured at line precision — the server process exists from 13:04:09, but
the URL appeared at some point in (13:06:37−300 s, 13:06:37].

### 3.3 Disposable server cost

```
=== SETTLED measurement of scratch server (PID 43016) ===
WS_MB 195.7   Private_MB 198   Handles 251   Threads 12   Children: NONE      # 13:08:05
port 3099 PID 43016 : WS_MB=196.1 Private_MB=198   Handles=251 Threads=12 Children=0   # 13:10:57
port 3100 PID 16860 : WS_MB=196.8 Private_MB=200   Handles=250 Threads=12 Children=0   # 13:10:57
```

Both settled at **~196 MB WS / ~198-200 MB private with 0 children**. They had no MCP servers because no
session was ever created in them, so no agent preset was loaded. `ESTIMATE:` with its preset's 5 MCP servers
loaded, a server process adds **~1.02 GB** of MCP children (§5), i.e. an idle-but-fully-equipped server is
**~1.22 GB**.

---

## 4. Can two DSH processes share one `DSH_HOME`?

**Answer: yes, demonstrably — two servers booted and served from one home simultaneously, and I found no
advisory-lock, WAL, or SQLite artifact anywhere.** But the evidence also shows a narrow, real write-collision
surface that I could not exercise with two idle processes.

### 4.1 Both processes up at once, both serving

Command (13:10:16):
```powershell
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 3080,3099,3100 }
Invoke-WebRequest -Uri "http://127.0.0.1:$port/?token=$tk" -MaximumRedirection 0 -SkipHttpErrorCheck
```
Raw:
```
LocalAddress LocalPort OwningProcess
127.0.0.1         3080         59460
127.0.0.1         3099         43016      <- mine, DSH_HOME = scratch
127.0.0.1         3100         16860      <- mine, SAME scratch DSH_HOME

port 3099 : HTTP 303  Location=/  authCookie=dsh-auth-3BwAN0JzQxNZ7B750o6P03uc9I97dBiawafhMIr3xlg=v1.
            eyJ2ZXJzaW9uIjoxLCJhdXRob3JpdHkiOiIxMjcuMC4wLjE6MzA5OSIsImlzc3VlZEF0IjoxNzg5MTQ2NjE3MDEyLCJleHBpcmVzQXQiOjE3OTE3Mzg2MTcwMTJ9...
port 3100 : HTTP 303  Location=/  authCookie=dsh-auth-LRY7nQo-bsB3ijTvnQd3p_mAX7PDfOalkrVX0OO6MAs=v1.
            eyJ2ZXJzaW9uIjoxLCJhdXRob3JpdHkiOiIxMjcuMC4wLjE6MzEwMCIsImlzc3VlZEF0IjoxNzg5MTQ2NjE3NDUzLCJleHBpcmVzQXQiOjE3OTE3Mzg2MTc0NTN9...
```

Two independently minted signing keys and independently signed cookies, bound to `127.0.0.1:3099` and
`127.0.0.1:3100` respectively, both reading the same `$DSH_HOME/.credentials.yaml`. Both returned
`303 → /` with a valid `Set-Cookie`. **No bind conflict, no "home already in use" refusal, no crash.**

### 4.2 Files the second process wrote

Second process (`16860`, started 13:08:27) wrote exactly **one** file into the shared home:
```
13:08:28.177    223  ...\dshhome\profiles\web\cordis.yml
```
Everything else kept its 13:04 timestamps (`.anonymous-user-id` 13:04:29, `.credentials.yaml` 13:04:51,
`storages\workspace.json` 13:04:51). So the second process **reused** the existing profile layer and did not
re-bootstrap it — good for startup time, and it means `cordis.yml` is rewritten on every boot.

### 4.3 Lock files, WAL and SQLite: searched, found nothing

Command (13:10:24):
```powershell
$roots=@("$s\dshhome","C:\Users\ezabz\.dsh")
foreach($r in $roots){ Get-ChildItem $r -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match '(?i)\.lock|\.lock$|wal$|shm$|\.db$|\.db-|journal|\.pid$' } }
```
Raw:
```
C:\Users\ezabz\code\_scratch\multiwindow\dshhome: matches=0
C:\Users\ezabz\.dsh:                              matches=0
```
The same search was run at 13:03:21 (before: `matches=0`) and at 13:10:24 (during: `matches=0`). There is **no
`-wal`, no `-shm`, no `*.lock`, no `*.db`, no `*.pid`** under either home, at any point.

Consequently, **the "session-query sqlite database" the task asked me to check for read-write sharing does not
exist on this machine.** `@deepseek-ai/dsh-session-query-sqlite` is installed, and it defaults to WAL
(`lib\index.js:490` `default("wal")`, `:1081` `journalMode: config.journalMode ?? "wal"`), and would take a
read-write handle — but it is **not instantiated in this deployment**. Evidence that the only session index
present is the JSON projection cache, not SQLite: `C:\Users\ezabz\.dsh\storages\` contains exactly
`workspace.json` + `session_projcache\` (21 entries at 13:12:43), and zero SQLite files. If it is ever
enabled, the WAL question re-opens and my answer here would no longer apply.

### 4.4 What the concurrency control actually is

The design uses a **per-session named kernel semaphore**, not a home-wide file lock —
`dsh-session-persistence-jsonl\lib\index.js:545-563` (read 13:06:37):
```
545 * Acquire the session write lock as a named kernel semaphore (count 1) whose
546 * name is derived from the canonical lock path. A kernel object never touches
547 * the filesystem, so readers, searches, and directory removal proceed freely
548 * while the lock is held; a second acquirer's zero-timeout wait times out
549 * (`EBUSY`); and when the last handle closes — including on any process
550 * death — the object is destroyed, so a successor's create starts fresh.
557 const name = `Local\\dsh-session-lock-${createHash("sha256").update(resolve(path).toLowerCase()).digest("hex")}`;
```
This is why no `.lock` file appears on disk and why two homes-sharing processes coexist: the lock is scoped to
a **session directory**, so two processes collide only if they open the *same session*. That is exactly the
"two windows, one session" case, and it fails fast with `EBUSY` rather than corrupting.

### 4.5 The honest limits of this conclusion

I verified: two processes, one home, both boot, both serve, no lock artifacts, no re-bootstrap, one shared
file (`cordis.yml`) rewritten. I did **not** verify: concurrent writes to the shared mutable files while both
processes are actually working. The residual risk is precise and I will not hand-wave it:

- **`settings.yaml`** — the live home contains a rewrite history that proves concurrent write pressure is real:
  `settings.yaml` (660 B, mtime 12:40:12) plus **four** `settings.yaml.bak-*` files
  (23:49:23, 12:22:08, 12:32:29, 12:39:08). Someone/something rewrites settings and leaves backups. If two
  server processes both write settings from independent in-memory copies, the last writer wins and the other
  process's change is lost. `UNVERIFIED:` I did not provoke this, so I cannot state the loss window.
- **`.credentials.yaml`** — two processes rotating or re-signing it concurrently could invalidate the other's
  cookies.
- **`storages\session_projcache\sessions\*.json`** — one file per session. Safe across processes *if* only the
  owning process touches its own session's file, which §4.4's session-scoped lock implies. Two processes on
  one session would be the failure mode.

**What I would need to settle it:** run two server processes on one `DSH_HOME`, create a session in each,
have both write settings and credentials simultaneously, then diff. I could not do that here because the
scratch servers had no browser client attached (no session was ever created), so the shared-settings write
path was never exercised. That is the gap, stated plainly rather than papered over.

---

## 5. Server-side concurrency caps, and which binds first at 12 sessions

Grepped `C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\*\lib\*.js` for
`maxParallel|maxConcurrent|max_concurrent|concurrency|p-limit|pLimit|Semaphore|acquire\(|maxSessions|sessionLimit|MAX_SESSIONS|maxRunning|maxInFlight|queueLimit|maxWindows`.

**There is no cap on the number of concurrent agent sessions in one server process.** Searches for
`maxSessions`, `MAX_SESSIONS`, `sessionLimit`, `maxActiveSessions`, `concurrentSessions`, `maxWindows` returned
**zero hits**. This agrees with the brief's finding that one server hosts many independent sessions.

The caps that do exist:

| Cap | Value | File:line | Scope |
|---|---|---|---|
| `maxParallelToolCalls` | **10** | `dsh-agent-loop\lib\index.js:1424` (`value ?? 10`), schema `:1465`, `:1491` | parallel tool calls within ONE step of ONE agent loop |
| `maxConcurrentJobsPerOwner` | **10** | `dsh-jobs-local\lib\index.js:77` (`DEFAULT_MAX_CONCURRENT_TASKS_PER_OWNER = 10`), `:102`, enforced `:137` | background jobs per owner |
| `maxConcurrentAgents` (workflow) | `availableParallelism()-2`, clamped to `[1,16]`; `0` = auto | `dsh-workflow-worker-thread\lib\index.js:851`, `:883` | workflow-run subagents only |
| `MAX_CONCURRENT_VERIFIERS` | **2** | `dsh-session-persistence-jsonl\lib\index.js:1400` | log verification |
| `imageCompressionConcurrency` | default **2**, max **8** (`z.number().min(1).max(8)`) | `dsh-attachment-local\lib\index.js:910`, `:912`, `:973` | image compression |
| `persistedReadConcurrency` | default **4** | `dsh-session-query\lib\index.js:10`; `dsh-session-query-sqlite\lib\index.js:495` | persisted session reads |
| `COLD_READ_CONCURRENCY` | **4** | `dsh-subagent\lib\index.js:2054` | cold reads of subagent children |
| `maxConcurrentFileUploads` | default **2** | `dsh-client-ui-conversation\lib\client.js:16476` | browser-side uploads |

**Which bites first at 12 concurrent sessions:** none of these caps counts *sessions*. They all bind *within*
a session or on a specific subsystem, so 12 sessions do not contend for any of them. The caps that will be felt
are (a) `maxParallelToolCalls=10`, which caps fan-out inside any one agent's step, and (b) on this laptop,
the **real** ceiling is neither of these — it is memory (§7) and the workflow plugin's
`availableParallelism()-2 = **20**` subagent ceiling (22 logical processors), which is bounded by the
`Math.min(16, ...)` clamp to **16**.

I flag one honest limitation: I found these by string-searching minified/bundled `lib/*.js`. A cap expressed
without any of those keywords, or enforced structurally (e.g. a fixed-size array), would not appear.

---

## 6. Measured cost table

| Unit | Working set | Private bytes | n | Source (time) |
|---|---|---|---|---|
| Idle `dsh web` server, empty home | 196 MB | 198 MB | 1 | PID 43016, 13:08:05 |
| Idle `dsh web` server, bootstrapped home | 196.8 MB | 200 MB | 1 | PID 16860, 13:10:57 |
| Startup transient peak of a booting server | 423 MB | — | 1 | PID 16860 at t+30 s, 13:08:57 |
| **Live** server, 17 children, serving this session | 878.4 MB | 915.3 MB | 1 | PID 59460, 13:10:57 |
| `dsh-subprocess-local` runner child | **57.3 MB** mean (min 51.6, max 58.4) | — | 10 | 13:11:27 |
| `pwsh.exe` grandchild doing the tool work | **102.7 MB** mean (83.8-121.2) | — | 8 | 13:11:27 |
| One MCP server, fully resolved | **~204 MB** | — | 5 | ESTIMATE, §2.3, 13:02:52 |
| One DSH browser window (`--app=`, container) | 275.5 / 252.5 / 209.0 MB | — | 3 | 13:12:43 |
| One session on disk | **183 KB** mean | — | 20 | `...\sessions\--C-Users-ezabz-code--\`, 13:11:27 |
| One session projection-cache entry | ~14-53 KB | — | 21 | `...\storages\session_projcache\`, 13:12:43 |

### Per-session marginal costs

- **Another window on the same server:** `ESTIMATE:` one browser renderer + shared container. Measured
  `--app=` container processes were 275.5, 252.5 and 209.0 MB — but those are **containers**, and this is
  therefore an **upper bound** on a window's true marginal cost, because a second window reuses the already-running
  browser process. `UNVERIFIED:` the true marginal renderer cost; I could not open a second window on one
  server and diff, because that would have required driving the GUI. Chrome's 16 processes summed to 3982.9 MB
  over (at least) one window plus extensions, and Edge's 57 processes summed to 6185.7 MB across three DSH
  windows plus other tabs — dividing either by window count is not defensible. **Do not multiply these.**
- **Another session inside one server:** ~183 KB of disk, and the server's own memory grows with its live
  context. `UNVERIFIED:` I could not isolate the per-session heap increment of the shared server; the live
  server's 878 MB includes this session's whole prefix, and I have no second session in a controlled server
  to diff against.
- **Another running agent turn:** the observable components are one `dsh-subprocess-local` runner (**57.3 MB**)
  plus, while a shell command actually runs, one `pwsh.exe` grandchild (**102.7 MB** mean). So `ESTIMATE:`
  **~160 MB per shell-command tool call in flight**, and this is bounded by `maxParallelToolCalls=10`
  (→ ~1.6 GB if one agent saturates its parallel tool budget). Background jobs are separately capped at 10
  per owner.
- **Another server process:** **196 MB** idle with no session; **ESTIMATE ~1.22 GB** once its preset's five
  MCP servers are live (`196 + 5×204`).

---

## 7. Extrapolation to N=8 and N=12

### 7.1 Assumptions, stated explicitly

1. **Per server process**: 196 MB measured idle. Adding one live session adds its MCP set.
2. **Per server process, preset fully loaded** (`ESTIMATE`): `196 + 5 × 204 = 1216 MB ≈ 1.19 GB`. The five MCP
   servers are stdio and therefore per-process (§2.3); the measured MCP layers are real, the multiplication is
   inferential.
3. **Per window**: browser-side, mostly shared within one browser instance. Counted separately and conservatively.
4. **Server children scale with *concurrent tool calls*, not with window count.** A window that is open but
   idle generates zero `dsh-subprocess-local` runners. So children are modelled per *busy session*, not per N.
   `ESTIMATE:` 1 runner per busy session = 57.3 MB, plus 102.7 MB only while a command runs.
5. **Both machines run the same Windows build of the same `dsh` 0.1.5-rc.1**; `UNVERIFIED:` that ZABZ-TECH's
   64 GB figure is accurate, and no ZABZ-TECH measurement was taken.

### 7.2 ZABZ-YOGA (measured host): 31.61 GB total, 7.66 GB free

**Option A — one server process, N browser windows**

| Component | Unit | N=8 | N=12 |
|---|---|---|---|
| Server process | 878.4 MB (measured, live) | 0.88 GB | 0.88 GB |
| 5 MCP servers | 1021 MB (ESTIMATE) | 1.02 GB | 1.02 GB |
| Windows (ESTIMATE, 40-275 MB each; see §6 warning) | 40 MB | **0.32 GB** | **0.48 GB** |
| Busy-session runners (ESTIMATE 57.3 MB each, assuming all busy) | 57.3 MB | 0.46 GB | 0.69 GB |
| **Total, ZABZ-YOGA, one server** | | **≈ 2.7 GB** | **≈ 3.1 GB** |

**Option B — N server processes on N ports**

| Component | Unit | N=8 | N=12 |
|---|---|---|---|
| Server processes | 196 MB each (measured) | 1.53 GB | 2.30 GB |
| MCP sets | 1021 MB each (ESTIMATE) | 7.98 GB | 11.96 GB |
| Busy-session runners (ESTIMATE 57.3 MB each) | 57.3 MB | 0.46 GB | 0.69 GB |
| Windows (ESTIMATE) | 40 MB | 0.32 GB | 0.48 GB |
| **Total, ZABZ-YOGA, N servers** | | **≈ 10.3 GB** | **≈ 15.4 GB** |

**Verdict for the laptop.** Option A fits in the **7.66 GB observed free** at N=12 (3.1 GB). Option B does
not: at N=8 it already needs ~10.3 GB, i.e. it must evict other work, and at N=12 ~15.4 GB is **twice the free
RAM observed** and roughly half of total physical RAM. Note also the disk cost of Option B is not zero — each
new `DSH_HOME` bootstraps its own full `profiles\node_modules` (measured 13:04:09→13:04:11, hundreds of
packages), and a shared home only avoids that for the *bootstrap*, not for the per-process MCP cost.

### 7.3 ZABZ-TECH (i9 / 64 GB) — `UNVERIFIED`, derived by scaling only

I did not measure this machine. If its per-process costs match ZABZ-YOGA's (same OS, same package version),
then the same table holds with more headroom:

- Option A: ~2.7 GB (N=8), ~3.1 GB (N=12) — trivially fits 64 GB.
- Option B: ~10.3 GB (N=8), ~15.4 GB (N=12) — fits 64 GB comfortably, still the worse choice.

`UNVERIFIED:` whether the i9 desktop actually runs the same MCP set, whether its Edge/Chrome baseline is
comparable, and whether free RAM there is better than the 7.66 GB seen here.

### 7.4 Extrapolation margins

`ESTIMATE:` the Option B numbers carry a wide band, because the dominant term (MCP sets, 1021 MB) is
inference. If MCP processes were somehow shared across server processes rather than duplicated, Option B would
fall to N×196 MB + one MCP set ≈ 2.5 GB (N=8) / 3.3 GB (N=12) — i.e. **the entire conclusion depends on
whether stdio MCP servers are per-process.** I read the config (`transport: stdio`) and the SDK import, and I
observed one server's five MCP sets, but I did not observe a *second* server spawning its own. A single cheap
trial — boot a second server with the real `DSH_HOME`, open one session in it, count MCP processes — would
convert that inference into measurement. I did not run it because it would have required browser automation
against the shared live home and the parent's own tests were already occupying ports 3081-3083.

---

## 8. Cleanup — reported as required

| Action | Evidence |
|---|---|
| Killed PID 43016 (my 3099 server) | `Stop-Process -Id 43016 -Force` at 13:11:48; `PID 43016 EXITED` |
| Killed PID 16860 (my 3100 server) | `Stop-Process -Id 16860 -Force` at 13:11:48; `PID 16860 EXITED` |
| Confirmed both exited | 13:11:52: no listener on 3099 or 3100; only `3080 → 59460` remained |
| Confirmed live server untouched | `PID 59460 ALIVE (untouched) created=12:46:08` at 13:11:52 |
| Removed scratch directory | `Remove-Item C:\Users\ezabz\code\_scratch\multiwindow -Recurse -Force` at 13:12:14; `exists_after=False`; `_scratch` now empty |
| Background job settled | job `pwsh-55` completed (exit 1, from the forced kill); no other jobs left running |

I killed **only** the two PIDs I started, by id, and deleted **only** the scratch directory I created. No file
under `C:\Users\ezabz\.dsh` was created, modified or deleted by me. Port 3080 and PID 59460 were never touched.
No process I did not start was killed.

---

## 9. What I ran — deviations from the assigned method

1. **RAM premise wrong.** Task said 8-16 GB laptop; measured **31.61 GB, 22 logical CPUs**. Reported the
   measured truth and reframed the constraint as *free* RAM (7.66 GB), which is the real binding limit here.
2. **Same-machine contention.** The parent agent was concurrently running its own DSH server tests on ports
   **3081, 3082, 3083** (measured 13:12:43: three `msedge.exe --app=http://127.0.0.1:308X/?token=...` windows,
   plus `.dsh\multi-window\logs-test\3081.log`). This inflates every *system-wide* memory aggregate I took.
   My two servers' individual figures are unaffected; the `node.exe` total (4165.7 MB over 30 processes at
   13:10:57) is **not** a clean baseline and I did not use it for extrapolation.
3. **Shared-home test redesigned for safety.** The task asked me to determine whether two processes sharing a
   `DSH_HOME` corrupt shared state. Rather than risk `C:\Users\ezabz\.dsh`, I bootstrapped a **scratch home**,
   ran server 3099 in it, then ran server 3100 in the **same scratch home** while 3099 was live. This gave the
   same evidence (both boot, both serve, shared files, no lock artifacts) with zero risk to the live home. The
   cost is that no browser was attached, so **the shared-settings write path was never exercised** — the one
   gap I name in §4.5.
4. **Attempted `Invoke-WebRequest /api/sessions`** on both servers to prove session independence; both failed
   with `The maximum redirection count has been exceeded` (auth redirect) and a bad-Cookie-header error from my
   own empty-cookie construction. Superseded by the stronger evidence in §4.1 — two independently signed
   cookies bound to two different authorities. Not pursued further.
5. **No `handle.exe`/`openfiles` enumeration.** The task asked which files the second process opened. I
   established *which files changed* by mtime diff against a 601-row recursive baseline (exact CSV, 13:04:06)
   rather than by open-handle enumeration, and found no lock/WAL/SHM artifacts at three separate times. I did
   not install Sysinternals to enumerate handles.
6. **`ZABZ-TECH` not measured** — separate network, no attempt made.

---

## 10. Recommendation

**Use one server process with many windows.** On this laptop's measured 7.66 GB of free RAM, one server serves
N=12 for ~3.1 GB while N=12 server processes need ~15.4 GB. The dominant reason is not the 196 MB server — it
is the ~1.02 GB of five stdio MCP servers that every new server process spawns for itself. Nothing in the
installed packages caps concurrent sessions, and the session write lock is per-session (`Local\dsh-session-lock-<sha256>`),
so many windows on one process is the design's intended shape.

Two caveats that belong to whoever decides next:

- The Option B figure rests on one inference (§7.4). Convert it to a measurement before treating 15.4 GB as
  final: boot a second real-`DSH_HOME` server, open one session, count MCP processes.
- Two processes on one `DSH_HOME` demonstrably coexist, but concurrent writes to the shared mutable files
  (`settings.yaml`, `.credentials.yaml`) were not exercised. The four `settings.yaml.bak-*` files in the live
  home say that file is rewritten often enough that this deserves a test before being relied on.
