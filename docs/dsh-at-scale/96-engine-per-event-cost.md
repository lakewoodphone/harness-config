# What the DSH engine does synchronously, per session event

Read-and-report task, host ZABZ-YOGA, 2026-10-04 late evening local (2026-10-05 ~03:30 UTC).
Everything below was read out of the installed source on THIS machine and, where marked
MEASURED, timed here against this machine's real session logs. Nothing was restarted, killed,
reconfigured, or edited outside `C:\Users\ezabz\code\_scratch\perf\`; no port was bound.

## 0. Engine version — verified

- `...\.dsh\engine\node_modules\@deepseek-ai\dsh\package.json` → `"version": "0.2.0-rc.2"`.
- `...\dsh-session-persistence-jsonl\package.json:4` → `"version": "0.2.0-rc.2"`, peer deps pinned
  to `@deepseek-ai/dsh-session@0.2.0-rc.2`, `dsh-session-persistence@0.2.0-rc.2`, `cordis@~4.0.4`,
  dependency `koffi@3.1.1` (line 36). Runtime: Node **v24.12.0** (`node --version`).
- The engine root package is named `dsh-engine-pin` and carries **no** version field.
- **A harness patch is already applied** to the persistence module:
  `lib/index.js` is 144,695 B / 3,570 lines, with three siblings
  `index.js.bak-harness-2026-10-05T02-{36-30,37-01,38-25}*` (142,847 B / 3,527 lines) written
  ~50 min before this report. I diffed them: the ONLY change is
  `/* harness-patch:session-list-pool */` — pooled per-directory generation selection and pooled
  header reads, env knob `DSH_LIST_CONCURRENCY` (default 32). **The per-event append path is
  stock 0.2.0-rc.2.** Do not mistake that patch for anything on this path.

## 1. What actually runs per event, on the main thread

"Per event" here means per **session event** — `assistant/message`, `tool/call`, `tool/result`,
`step/start`, `step/end`, `turn/start`, `turn/end`, `request/header`. There is **no per-token
session event**: in `dsh-agent-loop/lib/index.js` the model stream is accumulated
(`for await (const chunk of stream) live.push(chunk)`, `:1076-1079`) and the log is appended
once per settled message (`:1144`) or per tool result (`:697`). Text deltas travel the
`agent/assistant-stream` channel (`:1067-1069`), which is a **separate** path — see §5.

### 1.1 `Session.append()` — the synchronous spine, called once per event

`dsh-session/lib/index.js:1441-1481`. Everything here is on the caller's stack (the agent loop),
so it is un-yieldable main-thread time:

```js
append(type, data, ...opts) {
    const surfaceOpts = opts[0];
    const surfaceMetadata = { ... };                       // 1443-1446
    const dataSnapshot = snapshotJsonValue(data);          // 1447  <-- full deep validate+copy
    if (dataSnapshot === void 0) throw new Error(...);      // 1448
    const surfaceMetadataSnapshot = snapshotJsonValue(surfaceMetadata); // 1449
    const event = deepFreeze({                              // 1453  <-- full recursive freeze
        type, seq: SessionSeq(this.log.length), time: Date.now(),
        data: dataSnapshot, ...surfaceMetadataSnapshot
    });
    validateSessionEventData(event, `session event ...`);   // 1460  (traversal; NOT exported, inferred)
    this.surfaceManager.validateNext(event);                // 1461
    let callbacks;
    const callbackArgs = [this, event];
    if (entry !== void 0) callbacks = collectSessionCallbacks(entry.emitCtx,
        [entry.carrier, "session/event", ...callbackArgs]); // 1466-1470
    this.log.push(event);                                   // 1471
    this.eventsSnapshot = void 0;                           // 1472
    if (callbacks !== void 0 && entry !== void 0)
        invokeContainedSessionObservers(entry.emitCtx, "session/event", entry.id, callbackArgs, callbacks); // 1473
    return event;
}
```

`snapshotJsonValue` = `walkJsonValue(value, true)` (`dsh-util-values/lib/index.js:159-161`), an
iterative task-machine that allocates a task object per property/node and builds a detached copy.
`deepFreeze` (`dsh-util-values/lib/index.js:194+`) is a second full traversal of that copy.

**Fan-out is synchronous and unbounded by the number of mounted subscribers** — every
`session/event` listener runs inside the producer's `append()` call:

```js
function collectSessionCallbacks(ctx, args) { return [...ctx.events.dispatch("emit", args)]; }   // :1224-1225
function invokeContainedSessionObservers(ctx, name, id, args, callbacks) {
    for (const callback of callbacks) try { const returned = callback(...args); ... }             // :1228-1237
}
```

I enumerated **36 `ctx.on("session/event", ...)` sites across 30 packages**. Every one of them is
inside this loop. (Their individual bodies are not all audited — see §7.)

### 1.2 Persistence: `enqueueLive` — a second full copy, per event

`dsh-session-persistence-jsonl/lib/index.js:186-193`, installed as a `session/event` listener at
`:408-412`:

```js
enqueueLive(event, reportBackgroundFailure) {
    this.buffered.push(structuredClone(event));   // 187  <-- SYNCHRONOUS full deep clone, per event
    if (this.batchTimer !== void 0 || this.drainPaused) return;
    this.batchTimer = setTimeout(() => {          // 189
        this.batchTimer = void 0;
        this.drainLive().catch(reportBackgroundFailure);
    }, 200);                                      // 192  <-- the coalescing window
}
```

### 1.3 JSON serialisation — synchronous, per event, at drain time

`eventLines()` → `eventLine()` (`lib/index.js:946-956, 3229`):

```js
function eventLines(events) { return events.map(eventLine).join("\n"); }        // 946-948
function eventLine(event) { return JSON.stringify(sessionFormatCatalog.encodeCurrentEvent(event)); }  // 954-955
```

### 1.4 zstd compression — **NOT** synchronous. This is the answer to suspect #1.

```js
const zstdCompressAsync = promisify(zstdCompress);              // 1289
const CHECKSUM_OPTIONS = { params: { [constants.ZSTD_c_checksumFlag]: 1 } };   // 1291
async function compressZstdFrame(input) { return zstdCompressAsync(input, CHECKSUM_OPTIONS); }  // 1369-1371
async function encodeEventBatch(events) {
    const body = eventLines(events) + "\n";                     // 3229
    return this.compression === "zstd" ? compressZstdFrame(body) : body;  // 3230
}
```

`lib/index.js:15` imports `zstdCompress`, `createZstdCompress`, `zstdDecompressSync` — but the
**write** path uses only the promisified async one, which runs on the libuv threadpool. `koffi` is
imported (`:468`) for the win32 named-semaphore lease only, not for compression.
`NodePrivateZstdFrameDecoder` (`:1157-1180`) and `zstdDecompressSync` (`:1265`) are the
**decode** path (open/read/repair), with per-frame-boundary event-loop yields
(`ZSTD_DECODE_YIELD_INTERVAL_MS = 500`, `:2291`). Not per event.

**One frame per batch, and a flush writes only the new bytes — no whole-file rewrite.**

```js
async function appendLines(meta, events) {
    const content = await this.encodeEventBatch(events);        // 3249
    const path = logPath(this.root, meta.cwd, meta.id, this.compression);
    const handle = await open(path, "a");                       // 3251  <-- append, not rewrite
    ...
    const { size: before } = await handle.stat();               // 3259
    await handle.writeFile(content);                            // 3261
    await handle.sync();                                        // 3262
```

Rollback truncates back to `before` (`rollbackAppend`, `:3276-3284`). Whole-file rewrites exist
only in materialization (`encodeMaterialization`/`writeSyncedTempFile`, `:3206-3226`), in
historical-format migration, and in the **projection checkpoint** (§1.5) — never per event.

### 1.5 Projection cache — cheap per event, expensive per trigger

`dsh-session-projection-cache/lib/index.js:294-312` (listener body):

```js
this.ctx.on("session/event", (session, event) => {
    if (event.type === "turn/end") { this.flushSoft(session, "turn/end"); return; }   // 295-297
    const state = this.dirty.get(session) ?? { pending: 0, timer: void 0 };
    this.dirty.set(session, state);
    state.pending += 1;
    if (state.pending >= this.config.writeEveryEvents) { this.flushSoft(session, "count threshold"); return; }  // 305-307
    state.timer ??= setTimeout(() => { this.flushSoft(session, "interval"); }, this.config.writeIntervalMs);     // 309-311
});
```

Per-event cost is one Map lookup, one integer add, at most one timer arm per session. The expensive
work is behind `write()` (`:266-271`), which runs at `turn/end`, `session/created`,
`session/disposed`, every 200 events, and every 5000 ms while dirty:

```js
async write(session) {
    const rows = this.ctx.sessionProjections.checkpoint(session);   // 267  sync, whole checkpoint
    this.markClean(session);
    if (this.ctx.sessions.get(session.id) === session) await this.ctx.sessions.flush(session);  // 269  drains the log
    await this.put(session.id, identityOf(...), rows);              // 270
}
async put(id, identity, rows) {
    const detached = snapshotJsonValue(rows);                       // 350  ANOTHER full pass+copies
    if (detached === void 0) throw new TypeError(...);
    await this.requireTable().put(id, { identity, rows: detached }); // 352
}
```

and inside the projection registry, `checkpoint()` (`dsh-session-projection/lib/index.js:196-207`):

```js
checkpoint(session) {
    const rows = {};
    for (const registration of this.registrations.values()) {
        const cell = this.cellFor(registration, session);
        rows[registration.def.key] = { ver: ..., seq: cell.observedSeq, val: structuredClone(cell.state) };  // 203
    }
    return rows;
}
```

So one checkpoint traverses the whole state **three times**: `structuredClone` per unit (`:203`),
then `snapshotJsonValue(rows)` (`:350`), then the storage layer's `JSON.stringify` + whole-file
`writeAtomic` temp-write + fsync + rename (`dsh-storage-json/lib/index.js:25-41`).

Config is from `dsh-base/cordis.patch.yml:182-186`, and the composed live tree confirms it
(`~\.dsh\tmp\composed-web.yml:504-511`): `writeEveryEvents: 200`, `writeIntervalMs: 5000`.
The module's own contract (`lib/index.js:112-117`) says the cache is "a fold shortcut, never an
authority: a row is possibly stale ... but never wrong", and writes are fail-soft.

### 1.6 Per-event projection fan-out — the uninstrumented suspect

`dsh-session-projection/lib/index.js:64-66` subscribes `drive` to every event (`:402-428`), and for
every registered unit whose state changed with a wire view and a listener:

```js
const next = registration.def.apply(previousState, event);      // 411
const changed = !Object.is(next, previousState);
...
if (changed && wire !== void 0) {
    views[0] = views[1];
    if (this.listeners.size > 0) {
        views[1] = wire.view(next);                            // 420  builds the whole view object
        if (!Object.is(views[0], views[1])) {
            const value = wire.viewSchema.parse(views[1]);      // 422  ZOD PARSE, per unit, per event
            for (const listener of this.listeners) listener(session, registration.def.key, value, event.seq);  // 423
        }
    }
}
```

`api-session-controller/lib/index.js:1137-1145` registers such a listener and broadcasts one
`{type:"projection", ...}` frame per changed unit to every control stream; `broadcast` (`:1186-1188`)
pushes the same frame object to each queue. The live cache holds **24 projection keys** (§3.3), one
of which (`contextBreakdown`) is 36 KB on its own — so if its view changes on a typical event, this
line is a larger per-event block than `snapshotJsonValue`. **I could not verify how often it
changes** (§7).

### 1.7 `dsh-session-query-sqlite` — mounted but INERT. Zero per-event cost.

`dsh-base/cordis.patch.yml:149-153`:

```yaml
    - id: session-query-sqlite
      name: '@deepseek-ai/dsh-session-query-sqlite'
      config:
        path: ':memory:'
        openAt: never
```

- `lib/index.js:50-51` `const { DatabaseSync } = await import("node:sqlite"); const db = new DatabaseSync(actual);` — synchronous API, but only reached from `_open()` (`:606-611`), which `_ensureReady` (`:612-620`) defers; `openAt: never` makes `_assertSearchEnabled` (`:593-596`) refuse every search call, and `:535` only opens at startup when `openAt === "startup"`.
- Defaults are `openAt: 'startup'`, `journalMode: 'wal'` (`:1080-1081`) — **not in force here**.
- PRAGMAs set: `application_id` (`:83`), `user_version` (`:80`, `:117`), `journal_mode` (`:62`). **No `synchronous`, no `busy_timeout`, no `wal_checkpoint`, and no `session/event` subscription anywhere in the file** (grepped; the only writes are in `_reconcile`, pulled by query operations at `:543` and `:564`, never by an event).
- Independent confirmation of the composition: `~\.dsh\tmp\composed-web.yml` and `harness-config/docs/dsh-at-scale/10-dsh-source-audit.md:333` agree — `:memory:`, `never`, no `.db` on disk.

**Verdict on suspect #2: it is not the problem, and cannot be turned on without choosing a real path
and accepting synchronous `DatabaseSync` writes on the loop.** This deployment does not have that
problem today.

## 2. Existing batching, and how well it works — MEASURED

There **is** coalescing, and it is almost entirely defeated.

- Window: **200 ms per live session** (`dsh-session-persistence-jsonl/lib/index.js:189-192`), armed
  on the first buffered event and drained by `drainBuffered()` (`:204-220`), which splices the whole
  buffer into ONE `persistContiguous` call — so a drain is one append, one zstd frame, one fsync.
- Other batching: the projection cache's count/interval triggers (`:294-312`), the storage-domain
  write chain (one chain per domain), and `SessionAssistantStreamAccumulator` for text deltas.

What the log says about the window (MEASURED, three real sessions, `bench-per-event.mjs` /
`frame-timing.mjs`; frame count comes from the engine's own `scanZstdFrames` algorithm, ported
verbatim from `lib/index.js:1300-1363`):

| session (this machine) | events | zstd frames | events/frame | frame span p50 / p90 | frames spanning >200 ms |
|---|---|---|---|---|---|
| `session-b60e96b3` (13.2 MB) | 10 155 | 5 834 | 1.74 | 1 ms / 5 ms | **0.1 %** |
| `session-85f98648` (9.8 MB) | 10 228 | 5 876 | 1.74 | 2 ms / 6 ms | **0.1 %** |
| `session-0898187e` (7.4 MB) | 10 359 | 5 934 | 1.75 | 2 ms / — | — |

Events-per-frame histogram for a 10 228-event log: **1 868 frames with one event, 3 745 with two,
257 with three-to-five, 6 with six-to-twenty, 0 with more**. 34 % of frames span exactly 0 ms.
Frame sizes: p50 620-698 B, p90 3-6 KB, max 41 KB.

**So the 200 ms timer is not what fires.** Frames are opened by the three semantic flush boundaries in
`dsh-session-checkpoint-policy/lib/index.js`, each of which calls `ctx.sessions.flush(session)` (which
in turn calls `drainLive()`, cancelling the timer at `:205-208`):

```js
ctx.on("llm/stream", (options, next) => { ... return afterCheckpoint(...) });   // :61-64, flush at :28
ctx.on("tools/execute", async (exec, next) => { ... await ctx.sessions.flush(exec.agent.session); ... });  // :66-71
ctx.on("agent/pre-step", async ({ agent }, next) => { await ctx.sessions.flush(agent.session); ... });     // :72-75
```

That is a **durability guarantee, not waste** — no tool body or model request runs before its logged
prefix is on disk. The waste is what each of those flushes costs: `open()` + `write()` + `fsync()` +
`close()` and a complete independent zstd frame, for ~1.75 events.

## 3. The biggest synchronous block, and how it scales — MEASURED

All numbers below are from `bench-per-event.mjs`, `bench-aggregate.mjs`, `projcache-size.mjs` run in
`C:\Users\ezabz\code\_scratch\perf\`, importing the engine's own exported `snapshotJsonValue` /
`deepFreeze` and using this machine's real session logs. Single-process, serial, on a loaded machine
(23 session logs were written in the 60 minutes before this measurement), so treat them as
lower bounds on a quiet machine.

### 3.1 Whole-session aggregate — 10 359 real events, 24.91 MB of event payload

| synchronous pass | total ms | share |
|---|---|---|
| `snapshotJsonValue(data)` (`dsh-session:1447`) | **6 106** | 60 % |
| `structuredClone(event)` (`jsonl:187`) | 1 894 | 19 % |
| `deepFreeze` (`dsh-session:1453`) | 1 186 | 12 % |
| `JSON.stringify` (`jsonl:955`) | 954 | 9 % |
| **TOTAL un-yieldable main-thread time** | **10 140** | 100 % |

**407 ms of loop-blocking work per MB of session events**, before `validateSessionEventData`, before
`surfaceManager.validateNext`, before zstd submission, before fsync, and before any subscriber body.
The 10 largest events account for 14.9 % of it.

### 3.2 Single events

| event | bytes | snapshot | snapshot+freeze | structuredClone | JSON.stringify | zstd async (pool) | zstd sync (counterfactual) |
|---|---|---|---|---|---|---|---|
| largest in log | 135 042 | **6.06 ms** | 7.16 ms | 1.53 ms | 1.42 ms | 3.26 ms | 2.14 ms |
| p50 event | 503 | 0.011 ms | 0.012 ms | 0.006 ms | 0.002 ms | 1.44 ms | 0.105 ms |
| largest `tool/result` | 110 404 | 4.19 ms | 6.03 ms | 2.77 ms | 1.65 ms | 14.92 ms | 2.71 ms |

Event size distribution (three sessions): p50 442-588 B, p90 6.6-16.6 KB, p99 29-64 KB,
max 118-156 KB. By bytes the log is 63-69 % `assistant/message`, 8-18 % `tool/result`,
7-8 % `tool/call`.

**The biggest single synchronous block per event is `snapshotJsonValue(data)` at
`dsh-session/lib/index.js:1447`: ~245 ms/MB of text, ~500 ms/MB for node-dense objects (nested
objects with many short fields), and ~6 ms for one 135 KB tool result.** Capability notes: it is
**independent of the number of live sessions and of the number of watchers** (it is per event), but
the aggregate loop load grows linearly with live sessions because they share the one loop.

Scaling answers explicitly:
- **(a) event size** — linear in nodes/bytes; measured 0.011 ms at 503 B, 6.06 ms at 135 KB.
- **(b) live sessions** — per-event cost is unchanged; total load is the sum over sessions. The
  engine's own numbers (11-13 loops → 48-79 ms p50 lag, +8-15 ms per loop) are consistent with this
  arithmetic: 407 ms/MB × the MB/s the fleet produces.
- **(c) watchers** — no engine-side copy per watcher on the fan-out (`api-session-controller:1464-1471`
  pushes the **same frozen event reference**; `api-gateway:846-854` pushes the **same `wire` object**),
  but each client serialises it when writing (`dsh-api-gateway/lib/index.js:388`
  `text = JSON.stringify(message)`), i.e. **one extra full serialisation of the event per attached
  window**, +9 % per watcher of the 10 140 ms figure above.

### 3.3 One projection checkpoint — MEASURED against the live cache

`~\.dsh\storages\session_projcache\sessions\`: **1 066 records, 30.01 MB total**, p50 23.2 KB,
p90 53.1 KB, p99 132.2 KB, max 676 KB. The newest record at measurement time
(`session-bb953f87-df3b-4b99-b196-dcae1f4bdbc9.json`, mtime `2026-10-05T03:25:32Z` — written
minutes earlier, so this is live, not stale):

| property | value |
|---|---|
| projection keys | **24** |
| compact key values | 42 322 B (largest: `contextBreakdown` 36 347 B, then `titleInput` 1 161 B) |
| on disk | 100 737 B (pretty-printed) |
| `structuredClone(rows)` | 2.00 ms |
| `snapshotJsonValue(rows)` (`cache:350`) | **21.48 ms** |
| sum of `structuredClone(unit.val)` × 24 (`projection:203`) | **16.70 ms** |
| `JSON.stringify(rows)` | 0.88 ms |

**A fully-populated checkpoint costs roughly 38 ms of synchronous main-thread work** (16.7 + 21.5)
plus a 100 KB whole-file fsync'd atomic replace — and it fires on every `turn/end`, not only on the
count/interval throttles. Note the ratio: for this node-dense graph `snapshotJsonValue` is **~10×
`structuredClone`** for the same data; its cost tracks node count, not bytes.

## 4. Does anything compress or hash the WHOLE session per event? — No

- Appends are `open(path,"a")` + write of the new frame only (`jsonl:3251, 3261`); no whole-file rewrite.
- `createHash("sha256")` sites: `:558` (win32 named-semaphore name from the resolved path, once per lease), `:1804` / `:1829` (snapshot/prefix verification on the migration path), `:3034` (`hash.update(JSON.stringify([path, revision]))` — lock/lease key material). **None per event.**
- No per-event whole-log re-read: `handle.read()` (`:62-110`) does re-scan the artifact, but nothing on the `session/event` path calls it; `requestHeader()` (`dsh-session:1494-1498`) folds only the new slice.
- The one **O(whole log) shape I found and then dismissed**: `dsh-session-projection:407` can call `session.snapshotEvents(0, event.seq)` to lazily `buildCell` a unit's full prefix — but `session.snapshotEvents()` (`dsh-session:1376-1382`) is **not** a deep copy; it returns a cached frozen array of pointers (`this.eventsSnapshot ??= Object.freeze([...this.log])`). So it is O(n) pointer work once per (unit, session), not per event.
- The full-log scans in `**/invariant.js` (e.g. `dsh-tools/lib/invariant.js:40,51`,
  `dsh-tool-todo/lib/invariant.js:48`, `dsh-goal/lib/invariant.js:297`) would be O(n) per event, but
  they are **not mounted here**: the composed live tree `~\.dsh\tmp\composed-web.yml` (written
  2026-10-02 11:27) contains **zero** occurrences of `invariant`, and `dsh-base/cordis.patch.yml:100-219`
  mounts no such row. Flagged so a future session does not rediscover it as a crisis.

## 5. The other per-chunk path (text deltas) — different, smaller, and per watcher

Deltas do not touch the log. `dsh-agent-loop:1067-1069` emits `agent/assistant-stream` per chunk;
`dsh-api-session-controller/lib/index.js:1388-1395` folds each frame into a per-session accumulator
(`accept`, `:1249-1290`, which calls `attempt.stream.push({time, chunk})`), and each attached history
stream adds its own wire frame per chunk (`:1481-1489`, `wireAssistantStreamFrame(...)`) plus a
`notify()`. Cost per chunk is small (an object push), but it is multiplied by the number of attached
streams for that session, and it is on the same loop as the model stream it is mirroring.

## 6. Ranked fixes (waste removed, capability preserved)

Each is stated with the exact site, why it is safe, and how to verify. Ordered by
(expected ms saved per event) × (confidence) ÷ (risk).

**F1 — delete the redundant per-event `structuredClone` in the persistence enqueue.**
`dsh-session-persistence-jsonl/lib/index.js:187` (`this.buffered.push(structuredClone(event))`).
The event handed to this listener was already detached (`snapshotJsonValue`, `dsh-session:1447`) and
deep-frozen (`deepFreeze`, `dsh-session:1453`) by `append()`, so no caller-owned reference survives
and the "persistence-owned copy" the comment claims is satisfied by construction. Safest form that
cannot change behaviour in any edge case: `this.buffered.push(Object.isFrozen(event) ? event : structuredClone(event));`
**Saves 1 894 ms per 10 359 events (19 % of the per-event sync total; 1.5 ms on a 135 KB event).**
Verify: unit test asserting that mutating the object returned by `session.append` throws in strict
mode and that the drained log is byte-identical; re-run `bench-aggregate.mjs`.

**F2 — stop re-doing the whole checkpoint twice on one write.**
`dsh-session-projection-cache/lib/index.js:350` `snapshotJsonValue(rows)` — `rows` was created one
line earlier by `checkpoint()`, which already `structuredClone`s every unit state into a fresh graph
that no one else holds. Replace the detaching `snapshotJsonValue(rows)` with the non-copying twin
`isJsonValue(rows)` (`dsh-util-values/lib/index.js:167-169`, same lossless-JSON rules, no copy) and
store `rows` directly. **Saves 21.48 ms per checkpoint** on the measured live record, plus one of
three whole-checkpoint copies and the garbage. Capability preserved: the lossless-JSON proof stays;
the graph is already private to this call. Verify: deep-equal the stored record against
`checkpoint(session)` output; assert a later mutation of a unit state does not change the stored rows.

**F3 — skip a checkpoint whose units have not advanced.**
`dsh-session-projection-cache/lib/index.js:266-271`, reached from `:295-297` on **every** `turn/end`.
`checkpoint()` already computes each row's `seq` (`dsh-session-projection:202`, `cell.observedSeq`).
If every row's `seq` equals the last durably written record's `seq`, the write is a no-op rewrite of a
100 KB document. Guard on that comparison and return early. **Saves the full ~38 ms + 100 KB
fsync + rename per no-op checkpoint**, and there is no freshness change at all because nothing moved.
This is the waste-free way to cut checkpoint frequency — prefer it to touching
`writeEveryEvents` / `writeIntervalMs` (`dsh-base/cordis.patch.yml:185-186`), which are freshness
knobs and should not be reduced.

**F4 — hold the log file handle open across appends.**
`dsh-session-persistence-jsonl/lib/index.js:3251` `const handle = await open(path, "a");` …
`:3256` `await handle.close();` — a fresh `open`/`close` pair for every frame, i.e. ~5 900 times per
10 000-event session. The handle is already exclusively leased by this process
(`acquireWriteLease`, `:249`; win32 named semaphore, `:555-565`), so a handle cached on
`JsonlSessionHandle` and closed in `close()`/`flushAll()` preserves the ownership and durability
contract exactly. **Removes 2 syscalls per frame** and lets the write use an explicit offset.
Verify: run a session write, assert `handle.sync()` still precedes every durability boundary, and
assert clean teardown (`flushAll`, `:384-397`) closes the cached handle; watch for a
Windows `EBUSY` on `truncateTornTail`/`rollbackAppend`, which reopen the path.

**F5 — serialise a broadcast frame once per broadcast, not once per client.**
`dsh-api-gateway/lib/index.js:846-854` already shares one `wire` object across all
`remoteEventClients`, but each client's write does its own `JSON.stringify(message)` at `:388`.
With the owner's ~5 windows attached, that is 5 identical serialisations of the same event —
measured single-serialisation cost is 954 ms per 10 359 events, so this is ~4 × that in pure waste.
Attach a lazily-computed cached string to the frame (memoise on the shared object) and reuse it.
Capability preserved: identical bytes on every wire. Verify: capture two clients' frames and compare
bytes; re-run the per-event benchmark with N clients attached.

**F6 — make `snapshotJsonValue` cheaper or rarer, the single biggest lever.**
`dsh-session:1447` and `dsh-util-values/lib/index.js:159-161` / `walkJsonValue`. Two
capability-preserving directions, both worth a measured trial:
(a) **fast-path already-detached values**: `walkJsonValue` allocates one task object per node; a
recursive fast path for plain objects/arrays with a plain prototype, no getters, and no cycles would
cut the 500 ms/MB node-dense rate without changing the accepted language. The current implementation
is deliberately iterative (no stack overflow) — keep an iterative copy of the hot path.
(b) **`isJsonValue` instead of `snapshotJsonValue` where the value is already private**, e.g. the
same reasoning as F2.
Verify: the package's own conformance tests for lossless JSON must still pass, then re-measure
`msPerMBofEvents` with `bench-aggregate.mjs`. Do not touch the validation, only its cost.

**F7 — bound the per-event projection validation (`drive`, `dsh-session-projection:420-423`).**
`wire.view(next)` + `viewSchema.parse` per changed unit per event, with 24 units registered and one
of them 36 KB. **Measure first** (§7) — if it fires on most events, caching a per-unit
`view` memo keyed by `cell.state` identity (the code already compares view references with
`Object.is`) or validating only keys some listener actually needs is the fix. Do not remove the
schema validation: it is the contract that keeps the Web client honest.

**F8 — the structural answer, honestly.** Everything above is per-event constant work on ONE loop:
after F1-F7 the same accounting still leaves `snapshot + freeze + stringify` per event, times the
fleet's event rate. If the owner wants 12+ concurrent sessions, these fixes buy headroom but not a
different curve; the remaining lever is **more than one engine process**. That is a real capability
trade, not free: the profile's own record (`harness-config/multi-window/windows.json:5`) says
`multi` is "UNSUPPORTED on a shared DSH_HOME — two dsh web processes on one home have been observed
writing duplicate sequence numbers into one session log and making the whole history unloadable",
and costs **~1.4 GB per engine** because each engine eagerly starts its own five stdio MCP bridges.
So a second engine needs its own DSH_HOME (its own sessions, storages, credentials) and windows must
attach to the engine that owns the session. Cost: RAM plus the loss of one shared session across all
windows. I am not recommending it before F1-F6 are measured; I am recording that it is the only
lever that changes the shape rather than the constant.

## 7. What I could not verify

1. **How often each of the 24 projection units actually changes** (`dsh-session-projection:411-422`),
   and therefore the true size of the `viewSchema.parse` block. I know the units exist, their names,
   and the size of one view (`contextBreakdown`, 36 KB). Deciding whether F7 matters needs
   instrumentation inside a live engine, which this task forbids. Cheapest honest measurement:
   replay one real log through a standalone `Session` + `SessionProjections` in a scratch process and
   count `changed` per unit. If that changes nothing, F7 drops below F4.
2. **`validateSessionEventData`'s cost** (`dsh-session:1460`). Called per event on the whole event;
   not exported, so I did not time it. It is structurally a full traversal, so I included it as an
   unmeasured addition to the 407 ms/MB, not as a number.
3. **The other 32 `session/event` subscriber bodies.** I enumerated all 36 sites and verified the
   fan-out mechanism plus 4 of the subscriber bodies in full — the persistence enqueue, the
   projection registry, the projection cache, and the controller's history follower. I did not audit
   `dsh-session-telemetry-otel`, `dsh-session-title`, `dsh-compaction-basic`, `dsh-agent-instructions`,
   `dsh-token-meter`, `dsh-workspace-changes`, `dsh-goal`, `dsh-tool-*`, `dsh-user-approval`,
   `dsh-hook-protocol`, the controller's second site (`:2890`), or the rest.
   I did verify that every full-log `snapshotEvents()` loop I found lives in an `invariant.js`
   companion, and that no `invariant` row is mounted in the composed tree — but that composed file
   is from 2026-10-02, two days before writing.
4. **Which of these module versions the running engine actually loaded.** The engine is live and
   single-process on `~\.dsh`; the source on disk is what it loaded at boot, and no dependency was
   reinstalled since the `.bak-harness` patch 50 minutes ago (mtime 22:38 local 2026-10-04), but I
   did not restart or inspect its process to prove the loaded graph.
5. **The reported lag figures** (48.5 / 62.5 / 78.8 ms p50 at 11/12/13 loops) are the briefing's
   measurements, not re-measured here; I did not touch `/healthz`. My numbers are the work that the
   loop must run *before* that lag appears.
6. **zstd frame independence.** I confirmed one complete frame is emitted per batch
   (`compressZstdFrame`, `:1369-1371`) and that frames are concatenated (`scanZstdFrames`,
   `:1300-1363`). I did not measure the compression-ratio cost of per-frame compression versus a
   streaming container; the code at `:1972-1985` shows a streaming variant with
   `finishFlush: ZSTD_e_flush` exists, but only on the migration/compaction path.

## 8. Reproduction

Scripts (all read-only w.r.t. the engine, one process each, no ports):
`C:\Users\ezabz\code\_scratch\perf\bench-per-event.mjs`,
`bench-aggregate.mjs`, `projcache-size.mjs`, `frame-timing.mjs`.
Run e.g.
`node --max-old-space-size=6144 bench-aggregate.mjs "$env:USERPROFILE\.dsh\sessions\--C-Users-ezabz-code--\session-0898187e-bb24-4d63-99d1-c2a331221f33\session.v3.jsonl.zstd" "session-bb953f87-df3b-4b99-b196-dcae1f4bdbc9.json"`.
`scanZstdFrames` in those scripts is a faithful port of `dsh-session-persistence-jsonl/lib/index.js:1300-1363`
(Node's own one-shot decoder stops after the first frame, which is why the port is necessary).
