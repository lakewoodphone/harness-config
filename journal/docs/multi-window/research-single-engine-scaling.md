# Single-engine scaling audit: 12 browser windows against one `dsh web` process

**Question.** One server process (`dsh web`) will be shared by 8–12 simultaneous browser windows, each running its own agent session with concurrent turns, tool calls and streaming. Where can that one process serialize, block or degrade?

**Method / provenance.** Read-only inspection of the installed build. No file was created, modified or deleted outside this report; no process was started, stopped or killed; no server was probed. Every claim below was read from the built JavaScript on disk. Where a claim is reasoning rather than reading, it is labelled `INFERRED:`.

**Path convention.** Paths starting with `@\` are relative to `C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\`. Paths starting with `$DSH\` are relative to `C:\Users\ezabz\.dsh\`. Everything else is absolute. Line numbers refer to the shipped `lib/*.js` in this installation.

**Caveat on magnitude.** This audit establishes *what code runs on which path*, and therefore what is serialized, unbounded or synchronous. It does **not** measure wall-clock. No process was inspected, so all "cost" statements are code-structural (O(1) vs O(n), serialized vs parallel), not timings. Sibling documents in this folder that carry measured numbers were not read for this report.

---

## 0. What is actually composed (so defaults are real values, not guesses)

| Fact | Evidence |
|---|---|
| Profile `web` mounts bundles `dsh-base`, `dsh-web-app`, `dsh-plugin-cost` | `$DSH\profiles\web\package.json:6-9` |
| The user patch layer is **empty** — nothing overridden at the profile layer | `$DSH\profiles\web\cordis.patch.yml` (217 bytes, body is `[]`) |
| Projection-cache checkpoint cadence: **200 events / 5000 ms** | `@\dsh-base\cordis.patch.yml:165-166` |
| Spill threshold **50000 bytes**; spill root unset | `@\dsh-base\cordis.patch.yml:380-386` |
| Tool-result pruner: threshold 8192 chars, head 4096, tail 1024 | `@\dsh-base\cordis.patch.yml:394-398` |
| HTTP gzip **on**, level 1, threshold 1024 bytes | `@\dsh-web-app\cordis.patch.yml:141-143` |
| Session full-text search **disabled** (SQLite `:memory:`, `openAt: never`) | `@\dsh-base\cordis.patch.yml:129-133` |
| Telemetry mode `FEEDBACK_ONLY` (no ordinary-activity capture) | `@\dsh-base\cordis.patch.yml:184-197` |
| Permission default preset `danger-full-access` | `$DSH\settings.yaml:5-6` |
| Default agent preset `zabz` — this is what every session mounts | `$DSH\settings.yaml:7-8` |
| `agent-loop.maxParallelToolCalls: 20` (raised from the code default of 10) | `$DSH\settings.yaml:23-24` |
| Six stdio MCP bridge rows live in the `zabz` preset | `$DSH\.agent-presets\zabz\agent.cordis.yml:372-460` |

The last two rows matter: the deployment has already raised the per-step tool-call pool to 20, and every session mounts the preset that carries six MCP bridges.

---

## 1. Synchronous calls in the request / event / tool / stream path, ranked by heat

### 1.1 `spawnSync("taskkill", …)` on the Windows child-termination path — **hottest synchronous call found**

`@\dsh-subprocess-local\lib\runner-launch-COYGu0Dl.js:131-134`

```js
/** Terminate one Windows process tree with taskkill, contained like POSIX group signalling. */
function taskkillTree(pid, force) {
	spawnSync("taskkill", [
```

and again at `:842-845`

```js
function taskkillProcessTree(pid) {
	spawnSync("taskkill", [
```

Heat: per cancellation — tool abort, cooperative tool timeout, `job_kill`, session cancel, host teardown. `spawnSync` blocks the event loop for the whole duration of a process spawn (tens of ms on Windows). With 12 windows, one window cancelling a command can stall the other 11. Frequency is bounded by how often commands are killed, not by stream volume, so it is a *liveness* hazard rather than a throughput one.

### 1.2 `structuredClone` per session event, on the emit path

`@\dsh-session-persistence-jsonl\lib\index.js:185-192`

```js
	enqueueLive(event, reportBackgroundFailure) {
		this.buffered.push(structuredClone(event));
		if (this.batchTimer !== void 0 || this.drainPaused) return;
		this.batchTimer = setTimeout(() => {
			this.batchTimer = undefined;
			this.drainLive().catch(reportBackgroundFailure);
		}, 200);
	}
```

Heat: **every published session event, for every live session** (`@\dsh-session-persistence-jsonl\lib\index.js:406-411` routes `session/event` into `enqueueLive`). One assistant message is one durable append, so this is per message/tool-result event, not per token — but a 12-session burst of tool results deep-copies all of them on the one thread, synchronously, with no yielding.

A **second** synchronous deep clone of the same event data exists in the telemetry path, `@\dsh-session-telemetry\lib\index.js:135-146`:

```js
	captureEvent(session, event) {
		this.deliver(session, {
			record: this.redact({
				channel: "ledger",
				time: event.time,
				severity: severityOf(event),
				attributes: identityOf(session, event),
				body: structuredClone(event.data)
			}),
```

`INFERRED:` this is dormant for ordinary activity because the mounted mode is `FEEDBACK_ONLY` (`@\dsh-base\cordis.patch.yml:187`) and release requires explicit user feedback (`:168-169`); it becomes live if that mode is changed.

### 1.3 HMR bundle poll: `statSync` of every client bundle every 500 ms — **recurring, unconditional**

`@\dsh-client-hmr\lib\index.js:28-34`, `:77-90`, `:103-113`

```js
function bundleStat(path) {
	const bundle = statSync(path);
	return { mtimeMs: bundle.mtimeMs, size: bundle.size };
}
```

```js
	const pollWatches = () => {
		for (const [id, watch] of watched) {
			let current;
			try {
				current = bundleStat(watch.path);
```

```js
		const timer = setInterval(pollWatches, pollIntervalMs);
```

with `pollIntervalMs` defaulting to 500 (`@\dsh-client-hmr\lib\index.js:22`). One graph row per package that ships a client bundle; this installation has dozens (every `dsh-client-ui-*` package plus `dsh-client-modules`, `dsh-client-connection`, …). This is a permanent synchronous filesystem walk of the main thread every 500 ms whether or not anything changed, for the whole life of the server.

`dsh-web-app` mounts this row unconditionally (`@\dsh-web-app\cordis.patch.yml:167-168`), and the profile sets `patchReload: live` (`$DSH\profiles\web\package.json:12`). `INFERRED:` magnitude is small per call (a stat is microseconds) but it is on the loop with no back-pressure, and it scales with the number of client bundles, not with sessions.

### 1.4 `statSync` + `accessSync` per subagent working-directory validation

`@\dsh-subagent\lib\index.js:2526-2533`

```js
function isEnterableDirectory(path) {
	try {
		if (!statSync(path).isDirectory()) return false;
		accessSync(path, constants.X_OK);
		return true;
	} catch {
		return false;
	}
}
```

Heat: once per child-agent creation (`assertUsableCwd`, `:2545-2548`). Synchronous, but per spawn rather than per turn.

### 1.5 Cold (verified once-per-process / activation) — listed so they are not mistaken for hot paths

| Call | Location | Provenance |
|---|---|---|
| `readdirSync(root)` | `@\dsh-session-persistence-jsonl\lib\index.js:3209-3216` | Only caller is the constructor `:2299` — once per process. The listing paths use async `readdir` (`:3165`, `:3259`, `:3270`, `:3305`). |
| `mkdtempSync` | `@\dsh-spill-local\lib\index.js:34-37` | `??=`-guarded, first spill only. |
| `existsSync(executableSidecar)` | `@\dsh-tool-fs-search\lib\index.js:120-128` | Inside a memoized promise (`rgPathPromise ??=`), once per process. |
| `lstatSync(candidate)` for pwsh discovery | `@\dsh-pwsh-local\lib\index.js:42-49`, `:59-62` | `resolvePwshPath` is called only from the constructor/config setter (`:228`, `:239`) — once per executor, not per command. |
| `readFileSync` / `statSync` of client bundles | `@\dsh-client-modules\lib\index.js:545`, `:732`, `:753` | `:753` is activation; `:545` is the HMR rebuild hook. Not per request; served bytes are held in memory. |
| `spawnSync` bwrap/seatbelt/ACL probes | `@\dsh-sandbox-local\lib\index.js:101`, `:123`, `:145` | Probes run at chain selection; on Windows the chain is a sole candidate and is selected **unprobed** (`@\dsh-sandbox-local\lib\index.js:175`, `:482-484`). |
| `spawnSync` systemd-run/systemctl | `@\dsh-subprocess-local\lib\index.js:74`, `:101` | Linux only. |
| `execFileSync` process identity | `@\dsh-subprocess-local\lib\runner-launch-COYGu0Dl.js:304` | Only reached from the POSIX/macOS process tables (`:581`, `:596`, `:610`) — **not** on Windows. |

### 1.6 A false alarm worth recording explicitly

`@\dsh-win32-process\lib\index.js:465-476` performs a genuinely blocking, infinite Win32 wait:

```js
function waitForProcessExit(api, process) {
	try {
		if (api.waitForSingleObject(process, 4294967295) === 4294967295) throwLastError(api, "WaitForSingleObject");
```

and its caller wraps it in a promise that does not make it asynchronous, `@\dsh-sandbox-windows-acl\lib\types-DuU3lSVe.js:1055-1056`:

```js
				wait: async () => {
					exitCodePromise ??= Promise.resolve(waitForExit(api, native.process));
```

`Promise.resolve(...)` evaluates its argument first, so this call blocks the thread that runs it. **However, the only production caller is the ACL runner child process** (`@\dsh-sandbox-windows-acl\lib\runner.js:142` constructs the `AclSandbox`), which the sandbox seam spawns as an argv prefix (`@\dsh-sandbox-local\lib\index.js:519-529`), so the blocked thread is the runner, not `dsh web`. **It is not a server-side stall.** The cost that does land on the server is one extra `node runner.js` process per sandboxed command, and that path is gated: the deployment default is `danger-full-access` (`$DSH\settings.yaml:5-6`), `INFERRED:` so the ACL rung is normally not engaged.

### 1.7 The dominant synchronous cost is not a `*Sync` call at all

The heavy per-event work is the projection fold: `@\dsh-session-projection\lib\index.js:402-428` runs every registered projection unit for every committed event (`drive()`), and compaction stability checks compare whole node arrays on the loop — `@\dsh-compaction-basic\lib\index.js:581`:

```js
	if (!isDeepStrictEqual(dependencies.meter.measure(session).nodes, prepared.measurement.nodes)) throw new SurfaceChangedError("compaction: session surface changed during summarization");
```

plus `:595-596`. `INFERRED:` with 12 long sessions, a compaction is the most visible single stall of the shared event loop, because it is synchronous CPU proportioned to the whole session surface.

---

## 2. Global locks, mutexes, single-flight queues and serialized resources

Headline: **there is no process-wide mutex over sessions.** Sessions do not serialize against each other on the request path. What does exist is (a) one serialized durable-write chain for the projection-cache *domain*, shared by all sessions, and (b) a set of per-session, per-file and per-preset serializations that are correctly scoped. Both are stated precisely below.

### 2.1 CROSS-SESSION: one write chain for the whole `session_projcache` domain

`@\dsh-storage-domain\lib\index.js:119-120`

```js
	/** Tail of the write chain; every link settles (rejections are observed by the caller's slice). */
	chain = Promise.resolve();
```

`@\dsh-storage-domain\lib\index.js:221-226`

```js
	enqueue(job) {
		const result = this.chain.then(job);
		this.chain = result.then(noop, noop);
		return result;
	}
```

`@\dsh-storage-domain\lib\index.js:257-262`

```js
	put(key, value) {
		return this.host.enqueue(async () => {
```

Every session's projection checkpoint enters this one chain via
`@\dsh-session-projection-cache\lib\index.js:346-352`

```js
	async put(id, identity, rows) {
		const detached = snapshotJsonValue(rows);
		if (detached === undefined) throw new TypeError("projection checkpoint is not losslessly JSON-serializable (a unit state violates the plain-JSON contract)");
		await this.requireTable().put(id, {
```

and each job is a full document replace with an fsync — `@\dsh-storage-json\lib\index.js:25-41`

```js
async function writeAtomic(path, data) {
	const tmp = join(dirname(path), `.${randomUUID()}.tmp`);
	try {
		const handle = await open(tmp, "wx", 384);
		try {
			await handle.writeFile(data, "utf8");
			await handle.sync();
		} finally {
			await handle.close();
		}
		await rename(tmp, path);
		await fsyncDirectory(dirname(path));
```

**What is serialized:** the *durable write* of every session's projection checkpoint, process-wide. **What is not:** cache reads (they are synchronous off the domain's in-memory tables, `@\dsh-session-projection-cache\lib\index.js:168-172`) and the cold-read fold itself. So a 12-session burst of turn-end checkpoints queues behind one another on a single promise chain, each paying temp-create + fsync + rename. The per-record layout (`@\dsh-session-projection-cache\lib\index.js:99`) removes *file* contention but not *chain* contention.

### 2.2 CROSS-SESSION: the same checkpoint forces the session's JSONL flush first

`@\dsh-session-projection-cache\lib\index.js:263-267`

```js
	async write(session) {
		const rows = this.ctx.sessionProjections.checkpoint(session);
		this.markClean(session);
		if (this.ctx.sessions.get(session.id) === session) await this.ctx.sessions.flush(session);
		await this.put(session.id, identityOf(session.header, session.inheritedEventCount), rows);
	}
```

So one checkpoint = JSONL flush (see §6.1, includes an fsync) **then** a domain-chain document write (another fsync). Both are durable-by-design, and the first is not on the serialized chain, so 12 sessions can have 12 concurrent JSONL flushes competing for the filesystem while their cache writes queue serially. `INFERRED:` this combination is the single largest serialized-I/O cluster on the box.

### 2.3 WITHIN one session: the JSONL handle's mutation chain

`@\dsh-session-persistence-jsonl\lib\index.js:33`, `:251-254`

```js
	chain = Promise.resolve();
```

```js
	enqueueChain(op) {
		const next = this.chain.then(op);
		this.chain = next.catch(() => {});
		return next;
	}
```

Scoped to one handle, i.e. one session. Two windows on two different sessions never touch each other's chain. Two windows on the **same** session are excluded earlier (see 2.4).

### 2.4 Per session directory: a kernel write lease held for the handle's lifetime

Windows uses a named kernel semaphore, not a file — `@\dsh-session-persistence-jsonl\lib\index.js:555-565`

```js
async function acquireLockHandleWin32(path) {
	const api = await win32();
	const name = `Local\\dsh-session-lock-${createHash("sha256").update(resolve(path).toLowerCase()).digest("hex")}`;
	const handle = api.createSemaphoreW(null, 1, 1, name);
```

POSIX takes a non-blocking `flock` on `session.lock` (`:642`, `:665-692`). Contention does not wait — it throws `SessionAlreadyOwnedError` (`:677`). Acquired lazily and held for the handle's life, `:247-249`:

```js
	async ensureLease() {
		this.lease ??= await this.storage.acquireWriteLease(this.header);
	}
```

**Precisely:** this serializes *cross-process writers of one session's artifact directory*. It is not a cross-session lock and it never blocks on a queue. Its operational consequence for 12 windows: 11 distinct sessions never contend; a second writer on the *same* session is refused loudly rather than slowed.

### 2.5 A second, independent file lock exists but is not on the session-log path

`@\dsh-atomic-write\lib\index.js:105`, `:122-145`

```js
const DEFAULT_LOCK_WAIT_MS = 2e3;
```

```js
async function withFileLock(filename, operation, options) {
	const lockPath = `${filename}.lock`;
	const deadline = Date.now() + (options?.waitMs ?? DEFAULT_LOCK_WAIT_MS);
```

This is a `wx`-created `<file>.lock` sibling with a default 2 s deadline, and it is the one place a caller can *wait* on a lock. Its call sites are outside the packages inspected here (`INFERRED:` settings/JSON-document writers, not the session log — the session log uses the lease in 2.4). Recorded so it is not rediscovered later as a mystery.

### 2.6 Per-session single-flight (correctly scoped, listed for completeness)

- `@\dsh-api-session-controller\lib\index.js:178-179`, `:222-227` — `resumes` / `creations` `Map`s keyed by `sessionId`, deduping concurrent activation of the *same* session.
- `@\dsh-api-session-controller\lib\index.js:181`, `:344-348` — image admission:

```js
	serializeImageAdmission(agent, operation) {
		const result = (this.imageAdmissionChains.get(agent) ?? Promise.resolve()).then(operation);
		this.imageAdmissionChains.set(agent, result.then(() => void 0, () => void 0));
		return result;
	}
```

A `WeakMap` keyed by the **Agent object**. Two sessions never block each other here; within one session, image admission and model selection serialize against each other. This is the only construct in the tree named like a lock that a reader might expect to be global — it is not.

- `@\dsh-agent-presets\lib\index.js:1721`, `:1732-1739` — `switches` chain per agent id for preset switching.
- `@\dsh-mcp-client\lib\index.js:550-557` — `syncChain` serializes `tools/list` syncs for one MCP instance.
- `@\dsh-session-persistence-jsonl\lib\index.js:1400`, `:1414-1423` — `MAX_CONCURRENT_VERIFIERS = 2` gates **generation-migration verifiers only**, not the write path.

### 2.7 One process-wide single-flight that works in our favour: the preset standing mount

`@\dsh-agent-presets\lib\index.js:1467-1478`

```js
		* Standing mounts by preset id, single-flight so two agents racing the
		* first use of one preset share one composition. A settled failure is
```

```js
		standing = /* @__PURE__ */ new Map();
```

`@\dsh-agent-presets\lib\index.js:1768-1776`

```js
		async ensureStanding(preset) {
			const pending = this.standing.get(preset.id);
			if (pending !== void 0) {
				const mounted = await pending;
				const current = await compositionStamp(preset.path);
				if (current === void 0 || sameStamp(mounted.stamp, current)) return mounted;
```

This is what makes the six MCP bridges shared rather than per-window — see §7.

### 2.8 The agent loop's tool scheduling is per-step, per-session — not a global semaphore

`@\dsh-agent-loop\lib\index.js:583` and `:624-629`

```js
	const inFlight = /* @__PURE__ */ new Map();
```

```js
	const fillPool = async () => {
		while (!aborted && nextToStart < group.length && inFlight.size < maxParallelToolCalls) {
			const nextCall = group[nextToStart];
			if (nextToStart > 0 && mode === "parallel" && ctx.tools.executionMode(nextCall.exec).kind !== "parallel") break;
			await startCall(nextToStart);
			nextToStart++;
```

`inFlight` is local to one `runGroup` invocation. An "exclusive" (non-`isConcurrencySafe`) tool call becomes a barrier **within one step of one session** (`@\dsh-agent-loop\lib\index.js:527-531` slices `[first]` for exclusive), and cannot block another session's tool calls. The corresponding classification lives in `@\dsh-tools\lib\index.js:2951-2957` and fails closed to `exclusive`.

---

## 3. Every concurrency cap, its default, and whether raising it is safe

| # | Cap | File : line | Default (this deployment) | Scope | Safe to raise? |
|---|---|---|---|---|---|
| 1 | `maxParallelToolCalls` | `@\dsh-agent-loop\lib\index.js:1226` `const DEFAULT_MAX_PARALLEL_TOOL_CALLS = 10;`; resolved `:1424`; schema `:1465`, `:1491` | 10 in code — **20 in this deployment** (`$DSH\settings.yaml:23-24`) | One step of one session | Per-session, so raising it does not serialize anything — but it multiplies *total* concurrent work linearly across 12 sessions (12 × 20 = 240 in-flight dispatches) with no machine-wide budget behind it. Raise only deliberately. |
| 2 | `maxParallelSubCalls` (`run_code` sub-dispatch) | `@\dsh-tools\lib\index.js:2558-2561`, `:2575` | 10 | One `run_code` execution | Safe; bounded per execution. |
| 3 | `persistedReadConcurrency` | `@\dsh-session-query\lib\index.js:10`, `:1043-1044`; `@\dsh-session-query-sqlite\lib\index.js:495`, `:1086` | 4 | Cold session reads | Safe, **and currently moot**: the deployment opens search `never` with `:memory:` (`@\dsh-base\cordis.patch.yml:129-133`). |
| 4 | `COLD_READ_CONCURRENCY` | `@\dsh-subagent\lib\index.js:2054`, used `:2169` | 4 | Child-session cold reads during listing | Safe. |
| 5 | `imageCompressionConcurrency` | `@\dsh-attachment-local\lib\index.js:910`, `:912`, schema `:973`, guard `:1005-1006` | 2 (max 8) | **Process-wide** — one `LocalAttachmentStore`, one limiter (`:1008`) | Raising to 8 is the only headroom and it is real (image work is native CPU), but the limiter's wait queue is unbounded — see below. |
| 6 | `maxConcurrentJobsPerOwner` | `@\dsh-jobs-local\lib\index.js:102`; constant `:77` `const DEFAULT_MAX_CONCURRENT_TASKS_PER_OWNER = 10;`; counter `:286`; throw `:137` | 10 | Per exact owner object | Safe. The counter is per owner (`:286` iterates jobs filtering `job.owner === owner`), so 12 sessions get 10 slots each; over-limit **throws** rather than queueing (`:137`). |
| 7 | workflow `maxConcurrentAgents` | `@\dsh-workflow-worker-thread\lib\index.js:851`, `:883` | 0 → `Math.min(16, Math.max(1, availableParallelism() - 2))` | Per workflow run | Not global: 12 windows could each fan out ~16 agents. Raise only with a machine-wide agent budget. |
| 8 | workflow `maxTotalAgents`, `maxItemsPerCall` | `@\dsh-workflow-worker-thread\lib\index.js:851-853` | 1000, 4096 | Per run | Safe as-is. |
| 9 | `MAX_CONCURRENT_VERIFIERS` | `@\dsh-session-persistence-jsonl\lib\index.js:1400` | 2 | Format-migration verification | Safe; not on the per-turn path. |
| 10 | `DEFAULT_MAX_MESSAGES` (history page) | `@\dsh-api-session-controller\lib\index.js:1328`, used `:1382`, `:1461` | 50 | One history request | Safe; larger pages add payload and O(n) backward scanning. |
| 11 | history page **upper bound** | `@\dsh-api-session-controller\lib\index.js:1568-1571` | **none** — caller-supplied `maxMessages` is only validated `> 0` | Per request | **This is a missing cap, not a raise.** A client can request an arbitrarily large page. |
| 12 | `maxRequestBodyBytes` | `@\dsh-client-connection\lib\index.js:24`, `:741`, `:754` | 300 MiB (314572800) | Per in-flight buffered request | Lower it to the real image limit; see §4.5. |
| 13 | `websocketHeartbeatIntervalMs` | `@\dsh-api-gateway\lib\index.js:398`, schema `:433` | 2000 ms, `MAX_MISSED_HEARTBEATS = 2` (`:197`) | All clients, one timer | **Yes, and it should be raised** — see §4.4. |
| 14 | HMR `pollIntervalMs` | `@\dsh-client-hmr\lib\index.js:22` | 500 ms | Whole process | Can be raised; only affects dev reload latency. |
| 15 | spill `maxInlineBytes` | `@\dsh-base\cordis.patch.yml:386` | 50000 bytes | Per tool result | Safe; raising keeps more in context (which costs model tokens, not RAM). |
| 16 | tool-result pruner | `@\dsh-base\cordis.patch.yml:396-398` | 8192 / 4096 / 1024 chars | Per oversized tool result | Safe. |
| 17 | Ralph `maxRounds` | `@\dsh-base\cordis.patch.yml:416` | 64 | One Ralph loop | Safe; it is a runaway guard. |
| 18 | MCP reconnect policy | `@\dsh-mcp-client\lib\index.js:472-477` | `enabled: true, initialDelayMs: 500, maxDelayMs: 30000, maxAttempts: 10` | Per bridge | Safe. |
| 19 | MCP generation close bound | `@\dsh-mcp-client\lib\index.js:478` | 5000 ms | Per bridge | Safe. |

**No cap exists** for: concurrent sessions; concurrent subagent spawns; concurrent MCP tool calls across the six bridges; per-client stream buffers (§4.2). Those absences are the findings, not the numbers.

---

## 4. The event stream and WebSocket path

### 4.1 How many streams one tab opens

**Two persistent connections per tab.**

1. **One WebSocket** at `/api/remote.mux` — path constant `@\dsh-api-gateway\lib\index.js:10-11`:

```js
/** Exact WebSocket route carrying every Typert Remote stream. */
const REMOTE_STREAM_MUX_PATH = "/api/remote.mux";
```

registered as an upgrade route at `@\dsh-api-gateway\lib\index.js:457-476`:

```js
			const mux = new RemoteStreamMuxServer((endpoint, payload, signal) => this.openWireStream(endpoint, payload, signal), this.wireStream.failure, resolved.websocketHeartbeatIntervalMs);
			webCtx.effect(() => {
				const route = {
					path: REMOTE_STREAM_MUX_PATH,
					handler: (req, socket, head) => {
						const rejection = webCtx.connection.requestRejection(req);
						if (rejection !== void 0) {
							rejectRemoteStreamUpgrade(socket, rejection);
							return;
						}
						mux.handleUpgrade(req, socket, head);
```

2. **One SSE stream** at `/plugins/events` (HMR) — `@\dsh-client-hmr\lib\index.js:5`, route registered `kind: "exact"` at `:131-143`, one `res` added to a `Set` at `:126`.

Everything else is one-shot HTTP: the index page, the plugin-bundle batches, dist assets, unary `POST /api/<endpoint>`, file upload. **Logical** streams (the `$events` forwarded-event stream, one `session.control`, one `session.follow` per open session) are multiplexed onto the single WebSocket and are not extra sockets.

### 4.2 The per-client mux, and the per-client queues that are unbounded

Per-connection state — `@\dsh-api-gateway\lib\index.js:270-275`:

```js
var RemoteStreamMuxConnection = class {
	socket;
	open;
	failure;
	streams = /* @__PURE__ */ new Map();
	writes = Promise.resolve();
```

Client registries are a `Map`/`Set`, never a single queue — `@\dsh-api-gateway\lib\index.js:203-205`, `:441-442`:

```js
	server = new WebSocketServer({ noServer: true });
	connections = /* @__PURE__ */ new Set();
	missedHeartbeats = /* @__PURE__ */ new WeakMap();
```

```js
	remoteEventClients = /* @__PURE__ */ new Map();
	pendingRemoteEvents = /* @__PURE__ */ new Map();
```

Fan-out is synchronous, per event, over every client, with no await — `@\dsh-api-gateway\lib\index.js:621-629`:

```js
	broadcastRemoteEvent(frame) {
		assertRemoteEventFrame(frame);
		const wire = {
			type: "emit",
			event: frame.event,
			args: frame.args
		};
		for (const client of this.remoteEventClients.values()) client.queue.push(wire);
	}
```

and this is the shape that matters — `@\dsh-api-session-controller\lib\index.js:1001-1008`:

```js
		ctx.sessionProjections.onChanged((session, key, value, seq) => {
			this.broadcast({
				type: "projection",
				sessionId: session.id,
				key,
				value,
				seq
			});
```

with `@\dsh-api-session-controller\lib\index.js:1100-1102`:

```js
	broadcast(frame) {
		for (const stream of this.streams) stream.push(frame);
	}
```

**So: every projection change of every session is pushed to every connected control stream.** O(clients) per event, and — critically — the push is into an **uncapped** `Deque` per client, `@\dsh-api-session-controller\lib\index.js:1104-1114`:

```js
var ControlQueue = class {
	buffer = new Deque();
	wake;
	done = false;
	push(frame) {
		if (this.done) return;
		this.buffer.pushBack(frame);
```

The same is true of the per-follower buffer for a session view, `@\dsh-api-session-controller\lib\index.js:1404`:

```js
		const buffered = new Deque();
```

fed by three `{ global: true }` listeners that see every session's events and filter by id (`@\dsh-api-session-controller\lib\index.js:1419-1444`), and of the gateway's own per-client event queue, `@\dsh-api-gateway\lib\index.js:881-889`:

```js
var RemoteEventQueue = class {
	frames = new Deque();
	waiter;
	closed = false;
	push(frame) {
		if (this.closed) return;
		this.frames.pushBack(frame);
		this.waiter?.();
	}
```

`Deque` grows without a maximum — `@\dsh-deque\lib\index.js:6`, `:62-71` (it only shrinks when nearly empty). **There is no cap constant to quote for any of these three buffers. That absence is the finding.**

### 4.3 Back-pressure: a slow client cannot stall other clients, but it is not harmless

Writes are serialized **per connection** and the producer awaits each one — `@\dsh-api-gateway\lib\index.js:322-329` and `:346-365`:

```js
	async pump(streamId, endpoint, payload, active) {
		try {
			const source = await this.open(endpoint, payload, active.abort.signal);
			for await (const value of source) await this.send({
				type: "item",
				streamId,
				value
			});
```

```js
		const delivery = this.writes.then(() => new Promise((resolve, reject) => {
			if (this.socket.readyState !== WebSocket.OPEN) {
				reject(/* @__PURE__ */ new Error("api gateway: Remote stream socket is closed"));
				return;
			}
			this.socket.send(text, (error) => {
				if (error) reject(error);
				else resolve();
			});
		}));
		this.writes = delivery.catch(() => void 0);
```

Consequences, stated precisely:

- **Cross-client:** a stalled socket does **not** block fan-out or the producing session, because `writes` is a field of one `RemoteStreamMuxConnection` (`:275`) and `broadcast` never awaits. A slow client cannot make another window slow.
- **Same client:** every logical stream on that tab shares one `writes` chain, so a pending frame for one stream delays every other stream on the same tab. Correct behaviour, worth knowing.
- **Memory:** with the producer suspended inside `await this.send(...)`, the upstream buffer is where the growth happens. A suspended tab's `follow` buffer accumulates that session's events **including assistant stream frames** (`@\dsh-api-session-controller\lib\index.js:1436-1444`) without limit — and nothing consults `socket.bufferedAmount` anywhere in the tree.
- **No drain handling on the socket path at all.** The only drain-aware write in the wire layer is the HTTP `/api` proxy, `@\dsh-client-connection\lib\index.js:93-101`:

```js
	for await (const chunk of response.body) if (!res.write(chunk)) await new Promise((resolve) => {
		const done = () => {
			res.off("drain", done);
			res.off("close", done);
			resolve();
		};
		res.once("drain", done);
		res.once("close", done);
	});
```

The HMR SSE fan-out writes and ignores the result — `@\dsh-client-hmr\lib\index.js:144-151`:

```js
		const unsubscribe = ctx.clientModules.onRebuilt((id, rev) => {
			const line = sseData({
				type: "rebuilt",
				id,
				rev
			});
			for (const res of connections) res.write(line);
```

Rare frames, but the same uncapped class of bug.

### 4.4 Heartbeat can decapitate all 12 windows at once

`@\dsh-api-gateway\lib\index.js:197`, `:251-268`:

```js
const MAX_MISSED_HEARTBEATS = 2;
```

```js
	startHeartbeat() {
		if (this.heartbeatTimer !== void 0) return;
		this.heartbeatTimer = setInterval(() => {
			for (const socket of this.server.clients) {
				if (socket.readyState !== WebSocket.OPEN) continue;
				const missed = this.missedHeartbeats.get(socket);
				if (missed >= MAX_MISSED_HEARTBEATS) {
					setImmediate(() => {
						if (this.missedHeartbeats.get(socket) >= MAX_MISSED_HEARTBEATS) socket.terminate();
					});
					continue;
				}
				this.missedHeartbeats.set(socket, missed + 1);
				socket.ping();
			}
		}, this.heartbeatIntervalMs);
```

One global timer, all sockets pinged in one turn, tolerance of two missed ticks, then `terminate()` — so a single event-loop stall longer than roughly 4–6 s (a long GC, a 300 MiB `Buffer.concat`, a large synchronous fan-out, a compaction's `isDeepStrictEqual` sweep, a `spawnSync taskkill`) terminates **every** socket in the same tick and all 12 tabs reconnect together. The client's retry is single-flight with jittered backoff (`@\dsh-client-connection\lib\client.js:903-909`, defaults 500 ms / ×2 / 10 s max per `@\dsh-client-connection\lib\index.js:707-709`), which spreads the reconnect, but each reconnect re-establishes `$events` and re-reads its snapshots. The package README states this risk directly.

### 4.5 The largest per-window resident bound is the HTTP body buffer

`@\dsh-client-connection\lib\index.js:20-24`, `:55-71`:

```js
/** Default carrier cap for all HTTP RPC bodies: sized for the default
 * aggregate image limit (200 MiB) after base64 expansion plus envelope
 * headroom (~267.7 MiB required), rounded up for slack. The bridge buffers
 * each body in memory, so this cap is also the per-request resident bound. */
const DEFAULT_MAX_REQUEST_BODY_BYTES = 300 * 1024 * 1024;
```

```js
		const chunks = [];
		let received = 0;
		for await (const chunk of req) {
```

```js
			...chunks.length > 0 ? { body: Buffer.concat(chunks) } : {},
```

Each in-flight buffered request may hold up to 300 MiB, and `Buffer.concat` transiently doubles it. `INFERRED:` 12 simultaneous large image uploads could reserve multiple gigabytes; this is a theoretical ceiling that a deliberate or accidental burst can reach, not a steady-state cost.

---

## 5. Memory growth per session and per stream, and the retention/spill policy

### 5.1 Per session — unbounded, by design, several times over

- **The whole event log lives in memory.** `@\dsh-session\lib\index.js:1200` `this.log.push(event);` (and `:1075` for seeded snapshots). The package README states sessions remain in memory.
- **Every assistant message embeds its complete provider stream.** `@\dsh-agent-loop\lib\index.js:1113` `stream: live.stream` (five call sites: `:1063`, `:1068`, `:1073`, `:1086`, `:1113`), and the getter copies the whole thing — `@\dsh-agent-loop\lib\index.js:454-457`:

```js
	/** Exact compact stream for the final durable event. */
	get stream() {
		return [...this.accumulator.snapshot()];
	}
```

  So the transcript holds the raw chunk stream *in addition to* the derived blocks, and it is re-copied on each call.
- **A per-session assistant-stream accumulator grows per chunk for the life of an attempt.** `@\dsh-api-session-controller\lib\index.js:1335`, `:1344-1352`, `:1233-1237`:

```js
	assistantStreams = /* @__PURE__ */ new Map();
```

```js
			let stream = this.assistantStreams.get(agent.session.id);
```

```js
				attempt.stream.push({
					time: frame.time,
					chunk: frame.chunk
				});
```

  One entry per session, deleted on `agent/disposed` (`:1352`). Long streams in 12 sessions are 12 full chunk archives resident simultaneously; there is no trimming inside an attempt.
- **A derived message cache that only grows.** `@\dsh-session\lib\index.js:1246` `derived = [];`, returned as a full copy per request — `:1283` `return [...this.derived];` — and reset only on a surface generation bump (`:1272-1274`), i.e. on compaction.
- **Opening a session loads its entire decoded log into the handle.** `@\dsh-session-persistence-jsonl\lib\index.js:2356-2369` and `:2377-2390` store `primed: stored`, with `stored` the validated event array; a *write* handle reads from it cheaply (`:67-68`) and drops it on the first append (`:237` `this.state.primed = void 0;`). A *read* handle discards it and re-reads from disk instead (`:69-76`, `:81-83`).
- **Two whole parsed logs are memoized process-wide.** `@\dsh-session-persistence-jsonl\lib\index.js:2175` `const COLD_LOG_MEMO_MAX_ENTRIES = 2;` with LRU eviction at `:2691-2697`. Twelve concurrently-appending sessions thrash a two-entry cache, so the memo effectively never hits and every cold read pays a full-file decode; `INFERRED:` the entry size grows with how long the two most recent sessions are.
- **The one genuinely unbounded persistence buffer:** on a failed drain the buffered batch is kept and the timer is not re-armed — `@\dsh-session-persistence-jsonl\lib\index.js:209-218`:

```js
		while (this.buffered.length > 0) await this.enqueueChain(async () => {
			const batch = this.buffered.splice(0);
			try {
				await this.persistContiguous(materializeAppendBatch(batch));
			} catch (error) {
				this.buffered = batch.concat(this.buffered);
				this.drainPaused = true;
				throw error;
			}
```

  combined with `:187` `if (this.batchTimer !== void 0 || this.drainPaused) return;`. A single stuck fsync makes *that* session's memory grow without limit while the other 11 continue — a per-session, quiet OOM.

### 5.2 Per connected window (not per session) — the part that multiplies

- One control stream per client, whose opening frame is a **baseline computed over every live session** — `@\dsh-api-session-controller\lib\index.js:1040-1080`:

```js
	async *control(signal) {
		signal.throwIfAborted();
		const queue = new ControlQueue();
		this.streams.add(queue);
		try {
			yield {
				type: "baseline",
				value: this.baseline()
			};
```

```js
	projectionBaseline(sessions) {
		const blocks = Object.create(null);
		for (const session of sessions) {
			const snapshot = this.ctx.sessionProjections.snapshot(session);
```

  `INFERRED:` with W windows and S live sessions, each window connect costs W × S folds. Windows are held resident in `streams` (`:997`) and `closeFollowers` (`:1334`).
- Per-client byte/token buffers are unbounded in three places (§4.2), and each is fed by a process-wide listener.
- Up to 300 MiB per in-flight buffered request (§4.5).
- The browser-side session cluster is per window — `@\dsh-api-session-controller\lib\types\client\sessions\manager.js:20-24` (a `Map` of session instances plus queues). That memory is the browser's, not the server's, but it is still per window.

### 5.3 Retention / spill policy and defaults

- **`@\dsh-output-retention` has no defaults at all.** It is a library, not a service: budgets are required and validated (`@\dsh-output-retention\lib\index.js:34-36`), state is per-instance and released at `finish()` (`:18-21`). It cannot be a leak source by itself; the operative byte budgets live in its callers.
- **Spill threshold: `maxInlineBytes: 50000`** (`@\dsh-base\cordis.patch.yml:386`), applied as a strict `>` on the formatted result's UTF-8 size with the preview split half/half. With `maxInlineBytes` unset the plugin is a true no-op.
- **Spill files:** per-session hashed directory under a per-process private temp root — `@\dsh-spill-local\lib\index.js:34-37`, `:69-71`. Retention is **age-only, 30 days** — `@\dsh-spill-local\lib\index.js:482-485` `cleanupPeriodDays: z.number().step(1).min(0).default(30)` — and the sweep runs **once per process at activation**, not periodically (`:499-505`, `:521-527`), walking every spill root, every session directory and every file (`:321-345`, `:407-421`). There is **no per-file byte cap and no keep count**. `INFERRED:` a long-lived `dsh web` therefore accumulates spill files until restart, and the one sweep it does run is a directory walk on the event loop at activation.
- **Attachments are never reclaimed** (`@\dsh-attachment-local` README: stored images are never deleted automatically); the compression limiter's wait queue is unbounded — `@\dsh-attachment-local\lib\index.js:51-52` `if (this.active < this.concurrency) start(); else this.waiting.push(start);` with a per-process limiter (default 2, max 8).
- **Session logs and projection records are never pruned** on their own schedules: the projection cache's own README states records accumulate per session with no eviction surface, and the session store's README states nothing deletes session files. The projection domain additionally loads **every** record into memory when the domain opens — `@\dsh-storage-json\lib\index.js:410-420` reads each `<id>.json` — so memory scales with the number of sessions ever checkpointed (23+ records are present on this machine today).

---

## 6. Where the file system or a single file is the bottleneck

### 6.1 The JSONL append path: O(1) per append, but an fsync per batch and a *forced* flush at every request and every tool call

Append mechanics — `@\dsh-session-persistence-jsonl\lib\index.js:3041-3073`:

```js
	async appendLines(meta, events) {
		const content = await this.encodeEventBatch(events);
		const path = logPath(this.root, meta.cwd, meta.id, this.compression);
		const handle = await open(path, "a");
		let closed = false;
		const closeAppendHandle = async () => {
			if (closed) return;
			closed = true;
			await handle.close();
		};
		try {
			const { size: before } = await handle.stat();
			try {
				await handle.writeFile(content);
				await handle.sync();
```

Good news: each session's write is independent (own `open`, own fd, own chain, own lease), the append is O(1) in file size, and there is no shared file, no directory scan and no cross-session lock on this path.

The cost is **how often** it runs. `@\dsh-session-persistence-jsonl\lib\index.js:185-192` batches on a **200 ms per-session timer**, and then `@\dsh-session-checkpoint-policy\lib\index.js` overrides that batching with a hard flush at three boundaries:

```js
	ctx.on("llm/stream", (options, next) => {
		if (options.sessionId === void 0) return next();
		const session = ctx.sessions.get(options.sessionId);
		return session === void 0 ? next() : afterCheckpoint(ctx, session, next);
	});
	ctx.on("tools/execute", async (exec, next) => {
		if (exec.agent === void 0 || exec.parent !== void 0) return next();
		await ctx.sessions.flush(exec.agent.session);
```

```js
	ctx.on("agent/pre-step", async ({ agent }, next) => {
		await ctx.sessions.flush(agent.session);
```

with `afterCheckpoint` at `:26-31`:

```js
	return (async function* () {
		await ctx.sessions.flush(session);
		yield* next();
	})();
```

So: **one durable flush before every model request, before every top-level tool dispatch, and at every pre-step** — plus the 200 ms ceiling during streaming. Default compression is zstd (`@\dsh-session-persistence-jsonl\lib\index.js:2175-2176` `const COLD_LOG_MEMO_MAX_ENTRIES = 2;` / `const DEFAULT_COMPRESSION = "zstd";`), so each batch is compressed asynchronously and decompressed whole on read.

`INFERRED:` Node's filesystem and zlib async work runs on the libuv threadpool, whose default size is 4. Twelve sessions each flushing at every tool call and every request, each flush an `open` + `write` + `fsync` + `close`, plus per-append zstd compression and per-cold-read zstd decompression, is a workload that can saturate those four threads — at which point *all* file operations, including other sessions' appends and the projection cache's writes, queue behind each other. This is the mechanism by which one busy session can slow another through the filesystem, and it is the reason §2.2's serialized cache chain matters.

### 6.2 The projection cache is the one place a single writer really is shared

Already quoted in §2.1–2.2. Concretely: one promise chain per domain (`@\dsh-storage-domain\lib\index.js:120`), one record per session (`layout: "per-record"`), each write a whole-document `writeAtomic` with `handle.sync()` (`@\dsh-storage-json\lib\index.js:25-41`), each preceded by a session flush (`@\dsh-session-projection-cache\lib\index.js:266`). Trigger cadence: `turn/end` always (`:291-295`), `session/created` (`:310-312`), `session/disposed` (`:313-317`), plus the 200-event / 5000 ms throttle (`@\dsh-base\cordis.patch.yml:165-166`). **Twelve sessions finishing turns at the same time serialize their checkpoint writes**, each with two fsyncs' worth of durability.

### 6.3 Directory listings and full-file reads on the request/turn path

- `findLog` walks **every project directory** and `readdir`s each session directory — `@\dsh-session-persistence-jsonl\lib\index.js:3193-3207`:

```js
	async findLog(id, signal) {
		const matches = [];
		for (const project of await this.listProjectDirs(signal)) {
			signal?.throwIfAborted();
			await this.rejectLegacyFlatArtifact(project, id, signal);
```

  and it is reached from `resolveCurrentLog` (`:2705-2716`), which `read()` calls **on every read that is not served from a primed handle** (`:70`, `:82`). Read handles are exactly the "another window is watching this session" case and the session-list case. So a second window on a session can pay a project-directory scan per read.
- `listArtifacts` `readdir`s every session directory and reads every header (`:2858-2888`, with `readGenerationHeader` `:2889-2923`), i.e. O(sessions on disk) per session listing.
- `ensureRootEncoding` walks every project and session directory (`:3281-3286`) but is memoized after first success (`:3277-3280` `this.rootEncodingCheck ??= this.checkRootEncoding();`), so it is a one-time cost.
- Resolving a *read* re-reads and re-decodes the **entire** log: `readCurrent` (`:101-108`) → `readStoredLog` → full decode, mitigated only by the two-entry memo (`:2175`).
- The spill sweep (§5.3) and the HMR `statSync` poll (§1.3) are the two other directory/stat walks, one per activation and one every 500 ms.
- **Telemetry is not a file bottleneck:** `@\dsh-session-telemetry\lib\index.js` imports no `node:fs`; records go to an OTLP backend, and the mounted mode is `FEEDBACK_ONLY` (`@\dsh-base\cordis.patch.yml:187`). The only telemetry cost on the hot path is its `structuredClone` (§1.2).

---

## 7. Startup and per-turn cost of the MCP bridges

**Bottom line: the six stdio bridges spawn once per process — at the first session creation that mounts the `zabz` preset — and are shared by every session thereafter. They are not per window, not per session and not per turn. Adding the 12th window costs no MCP spawn, no `tools/list`, and no bridge memory.**

Evidence, in order:

- Spawn happens inside the SDK transport, reached from plugin activation — `@\dsh-mcp-client\lib\index.js:42-47`:

```js
		case "stdio": return new StdioClientTransport({
			command: config.command,
			args: config.args,
			env: buildChildEnv(config.env),
			cwd: config.cwd
		});
```

  `@\dsh-mcp-client\lib\index.js:770-789`:

```js
async function apply(ctx, config) {
	const reconnect = resolveReconnectPolicy(config.reconnect, `mcp-client(${config.serverName}): reconnect`);
```

```js
	const connection = startConnection(ctx, config, reconnect);
	ctx.effect(() => {
		return () => connection.dispose();
	}, "mcp-client.connection");
	const outcome = await connection.ready;
```

  with the connect itself at `:637-642`:

```js
			const generation = new Client({
```

```js
			await generation.connect(createTransport(config));
```

- The client is a closure variable of one plugin instance, not a session-keyed cache — `@\dsh-mcp-client\lib\index.js:530` `let client;`, `:625` `client = generation;`. The only `Map`-like store is a server-name reservation keyed by registration scope (`:736`, `:773-781`).
- Plugin instances are mounted once per preset: `@\dsh-agent-presets\lib\index.js:1467-1478` and `:1763-1803` (`ensureStanding`, single-flight per `preset.id`), bound into each new agent at `:1499-1506`:

```js
		async mount(agentCtx, id) {
			const agentKey = scopeOf(agentCtx);
			if (agentKey === void 0) throw new Error("agent-presets: refusing to compose an unscoped context; the scope key is what joins an agent to its preset");
			const preset = await this.resolveMountable(id);
			const standing = await this.ensureStanding(preset);
			this.bindings.set(agentKey, bindScopeParent(agentKey, standing.key));
```

- The six rows are preset rows in the preset this deployment defaults to (`$DSH\settings.yaml:7-8` → `zabz`): `$DSH\.agent-presets\zabz\agent.cordis.yml:372-460` (`mcp-secretary`, `mcp-firecrawl`, `mcp-jina`, `mcp-context7`, `mcp-fetch` via `npx.cmd`, `mcp-playwright` via `npx.cmd`). Each sets `failOnStartupError: false`.
- Tool definitions are fetched by the bridge and registered into the tool registry once per generation — `@\dsh-mcp-client\lib\index.js:151-179` (`syncTools`, paginating `tools/list` and swapping registrations), invoked from `:551-557` (`enqueueSync`) and re-invoked only on `notifications/tools/list_changed`, on reconnect, or when the composition file changes. There is no per-session or per-turn refetch.

**The one cost that does land on the first window:** `@\dsh-mcp-client\lib\index.js:787` `const outcome = await connection.ready;` is awaited by plugin activation, and the preset mount awaits activation. So the **first** session that uses the preset blocks until the slowest bridge has connected and completed its `tools/list`; later sessions reuse the live mount and pay only a scope bind. `INFERRED:` the bound on that wait is the MCP SDK's own request timeout, since the plugin passes no connect/discovery timeout of its own; I did not open the SDK source to confirm the exact value.

**What does scale per session, and is easy to mistake for MCP cost:** the entire tool schema surface is materialized into every request. `@\dsh-tools\lib\index.js:2609` `ctx.systemPrompt.tools((context) => this.wireSchemas(context.scope));` with `view()` rebuilt per call rather than cached — `@\dsh-tools\lib\index.js:2854-2862`:

```js
	view(scope) {
		const layers = this.layers.chainLayers(scope);
		const own = this.layers.peek(scope);
		const inherited = new Map(this.layers.global.tools.entries());
```

plus `:2890-2891`, `:2952`, `:3034`, `:3055`. Cost is O(tools × scope-chain layers) of `Map` allocation per rebuild — it grows with the number of registered MCP tools (six bridges' worth) but **not** with transcript length. So the MCP tax per turn is schema size and per-request assembly, not process spawns.

---

## 8. Ranked: the five things most likely to make 12 windows feel slow

Each entry: reason, mitigation, and whether I verified it by reading code or am inferring.

### 1. Unbounded per-client stream buffers, fed by process-wide fan-out (verified by reading code)

**Reason:** the `follow` buffer (`@\dsh-api-session-controller\lib\index.js:1404`), the control queue (`:1105`) and the gateway's per-client event queue (`@\dsh-api-gateway\lib\index.js:882`) are `Deque`s with no cap, filled by listeners that see every session's events, and drained only as fast as each socket's serialized `writes` chain allows (`@\dsh-api-gateway\lib\index.js:275`, `:325`). Any window that is backgrounded, throttled or briefly stalled accumulates that session's events *and assistant token frames* in host RAM, forever.
**Mitigation:** cap each buffer by entries/bytes with an explicit policy (drop-oldest plus a client-visible resync, or close the generation so it rebuilds from a snapshot), and have the producer consult `socket.bufferedAmount` before enqueueing. Nothing in the tree reads `bufferedAmount` today.
*Verified:* buffer types, absence of caps, fan-out loops, and the awaited per-frame send were all read directly. *Inferred:* only the rate at which a real browser falls behind.

### 2. One serialized, fsync'd write chain for the projection cache, in front of which every checkpoint also forces a session flush (verified by reading code)

**Reason:** all sessions' checkpoints enter a single domain promise chain (`@\dsh-storage-domain\lib\index.js:120`, `:221-226`), each doing a full document replace with `handle.sync()` (`@\dsh-storage-json\lib\index.js:28-36`), and each preceded by `await this.ctx.sessions.flush(session)` (`@\dsh-session-projection-cache\lib\index.js:266`). This is the only *cross-session* serialization in the process, and it sits on the turn-end path of all 12 sessions.
**Mitigation:** treat the cache as what it is (a fold shortcut, fail-soft by its own contract) — make its write non-fsync'd, and/or coalesce per-session checkpoints behind a short debounce with a single most-recent-wins write, instead of one durable document per checkpoint.
*Verified:* the chain, the atomic write with fsync, the forced flush, and the trigger cadence were all read. *Inferred:* how often 12 sessions actually collide at high concurrency.

### 3. A durable session flush before every model request, every tool dispatch and every pre-step — with zstd cost on both ends (verified by reading code)

**Reason:** `@\dsh-session-checkpoint-policy\lib\index.js:61-75` forces `ctx.sessions.flush()` at three boundaries, each ending in `open("a")` + `writeFile` + `handle.sync()` + `close` (`@\dsh-session-persistence-jsonl\lib\index.js:3049-3060`), with zstd compression default-on (`:2175-2176`). Twelve sessions × (1 request + N tool calls + steps) means hundreds of fsyncs per minute, plus whole-file zstd decodes on every cold read.
**Mitigation:** relax the checkpoint policy to turn boundaries (the 200 ms batcher already bounds data loss), and/or make the flush non-fsync'ing while keeping ordering. If the durability contract really requires per-request fsync, bound total in-flight flushes.
*Verified:* the flush call sites, the write path, and the zstd default were read. *Inferred:* the specific contention point is the libuv threadpool (documented default size 4) and the disk; I did not measure either.

### 4. Per-session memory that grows without limit: the in-memory log, the embedded provider stream, the per-attempt chunk archive, plus two-entry memo thrash (verified by reading code)

**Reason:** `@\dsh-session\lib\index.js:1200` keeps the whole event log in memory; `@\dsh-agent-loop\lib\index.js:1113` embeds the full provider stream in each assistant message and `:455-456` copies it on every access; `@\dsh-api-session-controller\lib\index.js:1335`, `:1233-1237` accumulates every chunk of the live attempt per session with no trimming; and the cold-read memo holds only two whole parsed logs (`@\dsh-session-persistence-jsonl\lib\index.js:2175`), so 12 live sessions thrash it and re-decode full files. There is also one plain unbounded buffer on a failed drain (`:209-218`).
**Mitigation:** stop persisting the raw chunk stream in durable events (keep blocks only), cap or window the per-attempt archive, raise `COLD_LOG_MEMO_MAX_ENTRIES` past the expected window count, and bound `buffered` with a loud failure instead of silent growth.
*Verified:* every structure and its growth rule was read; caps were confirmed absent. *Inferred:* the resulting bytes per session, which depend on transcript length and stream verbosity.

### 5. Per-turn O(transcript) scans and full copies, on one thread shared by all 12 sessions (verified by reading code)

**Reason:** `hasPromptRequest` scans the entire event log on every prompt (`@\dsh-api-session-controller\lib\index.js:946` `return agent.session.snapshotEvents().some((event) => {`); `deriveMessages` returns a full copy per step (`@\dsh-agent-loop\lib\index.js:1204` → `@\dsh-session\lib\index.js:1283` `return [...this.derived];`); the token meter re-measures and re-clones the whole priced surface per step (`@\dsh-token-meter\lib\index.js:637`, `:678`, plus a `JSON.stringify` of the whole tool array per `request/header` event at `:654`); each window's connect computes a projection baseline over **all** live sessions (`@\dsh-api-session-controller\lib\index.js:1070-1080`); and the tool registry's `view()` is rebuilt per call, deep-cloning schemas (`@\dsh-tools\lib\index.js:2854`, `:2918-2919`). Compaction additionally does synchronous whole-surface `isDeepStrictEqual` sweeps (`@\dsh-compaction-basic\lib\index.js:581`, `:595-596`).
**Mitigation:** maintain indexes/incremental cursors instead of rescanning (an RPC-id set for prompt dedupe; incremental token accounting keyed by appended event; a memoized tool view invalidated on registration change), and move compaction's stability checks off the critical synchronous path.
*Verified:* each call site and its complexity were read. *Inferred:* the aggregate wall-clock share on this machine; no profiling was performed.

**Honourable mentions, just outside the five.** (a) The heartbeat can terminate **all** sockets at once after a >4–6 s loop stall (`@\dsh-api-gateway\lib\index.js:197`, `:251-268`) — the failure mode of items 1–5 is not merely slowness but a synchronized 12-tab reconnect. (b) `spawnSync("taskkill")` on the Windows kill path (`@\dsh-subprocess-local\lib\runner-launch-COYGu0Dl.js:133`, `:844`) blocks the loop on every cancellation. (c) The first window that mounts the `zabz` preset waits for the slowest of six MCP bridges to connect and list tools (`@\dsh-mcp-client\lib\index.js:787`) — a startup-latency cost, paid once, not a scaling cost.

---

## 9. Explicitly not determined

- **No measurements.** Nothing was profiled and no process was inspected; every magnitude statement is structural. A code-derived O(n) claim is not evidence that 12 windows *actually* feel slow — the sibling `PERFORMANCE-MEASURED.md` in this folder was not read for comparison.
- **Actual MCP tool count and schema bytes** for the six configured bridges: obtaining them requires starting the bridges, which the read-only constraint forbids.
- **Which bridge is slowest to start**, same reason.
- **The exact SDK connect/discovery timeout** governing the first-session MCP stall: I read `await connection.ready` (`@\dsh-mcp-client\lib\index.js:787`) but did not open the `@modelcontextprotocol/sdk` sources.
- **The per-tab plugin-bundle batch count** and thus the cold-load HTTP request count: a function of the mounted client roster and 3 KB URL grouping (`@\dsh-client-modules\lib\index.js:124`), not derivable without a live boot graph.
- **Whether `withFileLock` (`@\dsh-atomic-write\lib\index.js:122`) is on any hot path:** its call sites lie outside the inspected package set. Nothing in the session stack appears to use it (the session log uses the kernel lease), but that is an absence of evidence, not proof.
- **Whether the Windows ACL sandbox rung is engaged in practice:** the code path exists and is selected unprobed on Windows (`@\dsh-sandbox-local\lib\index.js:175`, `:482-484`), but the deployment default preset is `danger-full-access` (`$DSH\settings.yaml:5-6`), so I record the path and decline to claim it runs.
