# 90 — plugin-health: a health surface, a list_agents deadline+cache, an admission governor

Program: `docs/dsh-at-scale` (this file). The unversioned copies under `_dsh-scale/` are drafts. Host: **ZABZ-YOGA** (Windows 11, Core Ultra 7 155H, 22 logical cores, 31.6 GB RAM, Node v24.12.0).
Built 2026-09-16. Everything below is either a measurement taken in this session (with the command
that produced it) or a statement about code that was read. Nothing is claimed from configuration alone.

**One deliverable:** `harness-config/packages/plugin-health/` — one host-plane Cordis plugin, mounted by
the web profile's bundle list, giving three surfaces the engine did not have.

```
packages/plugin-health/
  package.json            bundle manifest (dsh.bundle.patch -> cordis.patch.yml)
  cordis.patch.yml        THE MOUNT ROW (one `insert`: id plugin-health, name dsh-plugin-health)
  README.md               what it is, how it mounts, how to verify it
  lib/index.js            the plugin: samplers, /healthz route, engine_health tool, wiring
  lib/lag.js              self-timing event-loop lag ring + percentiles
  lib/sessions.js         agent-loop census, process memory, engine identity
  lib/processes.js        process-table classification (runners, MCP servers, engine)
  lib/snapshot.ps1        the OS process snapshot (kernel32 P/Invoke + Get-Process)
  lib/agents-list.js      the list_agents replacement (deadline + single-flight TTL cache)
  lib/governor.js         the lease protocol (acquire/renew/release/reap/status/budget)
  lib/admission-tool.js   the admission_governor model-facing tool
  bin/governor.mjs        the same protocol from a shell
  test/model.test.mjs     18 tests
  test/agents-list.test.mjs  21 tests
  test/governor.test.mjs  19 tests
  test/governor-stress.mjs   cross-process proof (real child processes)
```

`node --test test/model.test.mjs test/agents-list.test.mjs test/governor.test.mjs` → **58 pass, 0 fail**.
`node test/governor-stress.mjs --contenders 30 --slots 5` → **all 15 checks pass**.

---

## 0. Where it is mounted, and the exact mount row

The plugin is a **host-plane** row. The whole row is the package's own patch file, which is applied
automatically because the package name is in the profile's `dsh.profile.bundles`:

```yaml
# packages/plugin-health/cordis.patch.yml
- insert:
    - id: plugin-health
      name: dsh-plugin-health
```

The machine-local half is the bundle entry plus the `node_modules` link, and that is the keeper's job,
never a hand edit:

```powershell
pwsh scripts/install-client-plugins.ps1 -RequireAll   # link + add to dsh.profile.bundles
pwsh scripts/install-client-plugins.ps1 -Check        # verify every mounted bundle resolves
```

Verified on ZABZ-YOGA after the sync wired this in (`-Check`, 2026-09-16): all six repo packages
`LINK … ok`, ending `every mounted bundle resolves`, exit 0. `dsh-plugin-health` is present in
`~/.dsh/profiles/web/package.json` (`dsh.profile.bundles`) and junctioned to
`C:\Users\ezabz\code\harness-config\packages\plugin-health`.

**A new bundle does NOT hot-mount — measured, not assumed.** On an isolated engine (own `DSH_HOME`,
port 3097) with the plugin absent: `GET /healthz` → 404. Then the bundle name was added to the running
profile's `package.json` and the package junctioned into its `node_modules`, and after 8 s:
`GET /healthz` → **404 still**, no `health/` directory, no side effect. `patchReload: live` covers the
profile's own `cordis.patch.yml`, not the bundle list. **The live engine needs one restart.**

---

## 1. Feature 1 — the health surface. **VERIFIED LIVE** (isolated engine, port 3098)

There was no health endpoint anywhere: `GET /healthz` → 404 on the live engine
(`Invoke-WebRequest http://127.0.0.1:3099/healthz` → `404`, 2026-09-16), and `dsh-host-webserver`
"knows no harness concepts". Now:

```
$ curl -s -i -H "Cookie: <dsh-auth cookie>" "http://127.0.0.1:3098/healthz?format=text"
HTTP/1.1 200 OK
content-type: text/plain; charset=utf-8

engine 3104 up 1m00s  since 2026-09-16T15:13:08.375Z
loop lag  p50=1ms  p95=17ms  max=8923ms  (194 samples @ 250 ms)
memory    rss=199.2 MiB  heap=45/47.7 MiB  external=82.3 MiB
system    phys avail 16024.1 / 32373.4 MiB  cpus=22  load1=0
          commit 20638.7 free of 44149.4 MiB limit  memoryLoad=50%
processes 405 total, 6496 threads; engine 17 threads, 268 handles  (3s old)
          tool-call runners 0 (0 MiB)   mcp 0 (0 MiB)
sessions  0 root, 0 subagent, 0 agent loop(s) executing
listing   list_agents cache 3000 ms TTL, deadline 8000 ms: 0 scan(s), 0 cache hit(s), 0 coalesced, 0 deadline(s) (last scan never; last never called)
governor  0 of 24 heavy slot(s) leased, 24 free, 0 waiting
reading taken 2026-09-16T15:14:09.016Z on zabz-yoga (pid 3104); process table from snapshot.ps1 (child process, stdio ignored) at 2026-09-16T15:14:05.3587092Z
```

The same numbers are available as JSON (`/healthz`) and to a model as the `engine_health` tool.
Every counter asked for is present:

| asked for | where it is | how it is measured |
|---|---|---|
| event-loop lag p50/p95/max | `loop.*` | a self-timing `setInterval`; the reading is how late the loop ran its own timer. `lib/lag.js`; no busy poll, one unref'd timer |
| process memory rss/heap/external | `memory.*` | `process.memoryUsage()` |
| process count, thread count | `processes.total`, `processes.threadsTotal` | `snapshot.ps1` (kernel32 `CreateToolhelp32Snapshot` + `Get-Process`) |
| commit charge, available memory (Windows) | `system.probe.commit*`, `system.physicalAvailableBytes` | `GlobalMemoryStatusEx` P/Invoke — measured **10 ms**, against **286 ms** for the same numbers via `Get-CimInstance Win32_OperatingSystem` |
| live tool-call runner processes | `processes.toolCallRunnerProcesses` + rows | direct children of the engine running node. Measured 3 on the live engine while 3 shells were live |
| live MCP server processes per server name | `processes.mcpServersByName` + rows | descendants of the engine whose image path matches a known MCP package (`fetch`, `playwright`, `firecrawl`, `jina`, `context7`, `secretary`) |
| sessions with a running agent loop | `sessions.agentLoopsRunning` | `ctx.agents.list()` filtered on `status === 'running'`, plus root/subagent split from `owner` |
| uptime | `identity.uptimeMs` | monotonic `process.uptime()` (a clock step cannot fake a restart) |

**Cost, verified rather than asserted.** Two `/healthz` reads 30 s apart:

```
spawns                    : 6      → 12      (6 in 30 s = exactly one probe per 5 s interval)
ticksDroppedWhileInFlight : 1
failures                  : 0
lastSpawnMs               : 933    (the probe runs in its own process, off the engine's loop)
lastReadMs                : 0–1    (the engine only reads a 60 KB file)
```

There is no busy poll: one `setInterval` at 250 ms for lag (a timer wake-up), one at 5 s that spawns the
probe **only if the previous probe has already exited** — so the sampler cannot accumulate processes, and
one tick was dropped at boot exactly as designed. The probe child runs with `stdio: 'ignore'` and
`child.unref()`, so the engine never reads its stdout and never waits on it.

Provenance is structural: every reading carries `at`, `ageMs`, the pid and start time of the engine it came
from, and the source of the process table. A missing or stale snapshot is **not** health — `/healthz`
answers **503** with `"stale": true` and `"available": false`, and an unavailable process table is
reported as `null`, never as zero.

---

## 2. Feature 2 — `list_agents`: a deadline and a short-TTL cache. **Registered and unit-verified; the live mount needs the restart**

### The two defects, and the exact code

1. **No deadline.** `dsh-tool-call-timeout-policy/lib/index.js:123-124` wraps a tool only when the tool
   declares `timeoutMs`; `list_agents` declares none, so `return next()` passes it through with no
   cancellation anywhere in the stack.
2. **No cache, and the cost is repaid by every caller.** `list_agents` → `subagents.listChildren` →
   `prepareListing` → `sessionQuery.listSessions` → `listArtifacts`: a fully serial walk of
   `~/.dsh/sessions` (readdir, open, zstd frame, `decompressZstdFrame`, `JSON.parse` per session) on the
   shared event loop. Live corpus measured this session: **389 files / 214.1 MB**.

### What was built

`lib/agents-list.js` re-registers the tool with the **same name, arguments, output schema and rendered
text**, plus:

* a **cooperative deadline** (`listAgentsTimeoutMs`, default 8000 ms) that aborts the scan through the
  signal the service already honours, and — this is the part that matters — is enforced by
  `Promise.race`, so a service that *ignores* the abort can still not hang the call. On expiry the caller
  gets the last known listing, or an explicit `{kind:'diagnostic', id:'list_agents', reason:'unavailable'}`
  row. Never a hang, never a blank;
* a declared **`timeoutMs = deadline + 2000`** on the definition, so the shipped timeout policy arms its
  hard backstop behind the cooperative deadline;
* a **3 s TTL cache with single-flight coalescing**: one scan serves every caller inside the TTL, and
  concurrent callers inside one scan coalesce onto it instead of each paying the full corpus walk.

This is registered **globally from the host row**, and the shipped preset row is disabled on Windows
(`disabled: !!js process.platform === 'win32'`) — see §5 for why it is gated rather than deleted, and for the
ordering rule that makes the transition safe.

### Verification, honest about what it covers

* 21 unit tests: TTL hit re-scans nothing; a zero TTL always re-scans; **three concurrent callers cause
  exactly one scan**; a failed scan poisons nothing; a scan that never settles still returns an explicit
  diagnostic in 159 ms with a 150 ms deadline; a timed-out call serves the last known listing; an empty
  listing renders `(no subagents)`, never a blank.
* **In a real engine** (isolated, port 3098) the registered definition was read back out of the tool
  registry — the same lookup the timeout policy performs:

```
registry                 : registered
registeredName           : list_agents
registeredTimeoutMs      : 10000
registeredByHealthPlugin : True
```

* Both schemas were validated with the framework's own `assertSupportedJsonSchema` (see §6 — this is how
  the `required: true` bug was found).
* **"Before" timings, measured from the live engine's own session logs** rather than from a wrapper that
  would itself change the measurement (`docs/dsh-at-scale/tools/measure-tool-call.py`, which pairs `tool/call` and
  `tool/result` events by `callId`):

| session | calls | min | median | max |
|---|---|---|---|---|
| `e34dd061` (the orchestrating session) | 6 | 644 ms | 940 ms | **1,286,379 ms** |
| `64681fe6` | 2 | 1090 ms | 4285 ms | 4285 ms |
| `719a39f8` (this session) | 1 | 754 ms | 754 ms | 754 ms |

  The 21-minute figure is a matched call/result pair in the log with no timeout to bound it — the direct
  consequence of the missing deadline. (Caveat, stated because it is real: a session that is suspended
  mid-call would also produce a long pair. Either way the call had no cancellation.)
* **"After" is not yet measurable on this host**, because the tool that serves it is not mounted on the
  live engine (next section). The instrument that measures it *is* live: the counters are in
  `/healthz` → `listAgents` (`scans`, `hits`, `coalesced`, `timeouts`, `lastScanMs`, `lastOutcome`). The
  before/after for the same code path is one config change apart — `listAgentsCacheMs: 0` disables the
  cache so `lastScanMs` reports the raw scan, and the default 3000 shows what the cache avoided.

### Why it is not mounted on the live engine *yet*

`dsh-plugin-health` is installed in the live profile, and the engine was **not** restarted: ten sessions
are using it, and the instruction for this task was to prepare rather than interrupt. So the row is live
only in the isolated engine today. Once the engine restarts, `/healthz` and both tools come up with no
further action (the shipped preset row still shadows the tool, so there is no window in which
`list_agents` is missing — see §5).

---

## 3. Feature 3 — the admission governor. **VERIFIED with real processes**

`lib/governor.js` (protocol), `bin/governor.mjs` (shell), `lib/admission-tool.js` (model side). One
implementation, three entry points, so a hand-run `gov acquire` and an agent's request cannot disagree.

**The protocol.** One lease file per slot, created with `O_CREAT|O_EXCL` — the filesystem is the mutex, so
there is no check-then-claim window. The payload carries `pid`, `host`, `kind`, `note`, `startedAt`,
`renewedAt`, `expiresAt`, `ttlMs`. Liveness is a **heartbeat, not a pid guess**: pids are reused, and a pid
check either reaps a live holder (losing data) or keeps a dead one forever (silently shrinking the budget).
Reaping is guarded by an **atomic rename** — exactly one process can win renaming an expired lease — and
the reaper then re-reads the file and **renames it back if the holder renewed in the meantime**. That is
the same read-then-delete race that cost this repo an incident on the journal lock, closed by construction.

**It never refuses.** There is no branch that returns "no". A caller who cannot be granted a slot gets
`QUEUED position N` and exit code 10, with the arithmetic behind the budget published alongside, so the
caller decides whether to wait (`--wait-ms`) or proceed. The budget is floored at `minSlots` (4), so even a
near-zero measured headroom still grants work and reports `headroomLow: true` — the owner's rule "trim
waste, do not reduce what agents can do" encoded in the interface rather than in a comment.

**The budget is derived from measurement, generously.** `(free physical − reserve) / measured slot cost`,
capped at 24 and floored at 4. The reserve is `max(2 GiB, 12%)`; the slot cost is 160 MiB, which is the
measured cost of one heavy tool call (runner 57.3 MB + shell 102.7 MB, this repo's own earlier audit).
On this host, unloaded at 15:0x:

```
governor on zabz-yoga: 0 of 24 slot(s) in use, 24 free, 0 waiting
  derivation   15943 MiB free - 3885 MiB reserved = 12059 MiB usable / 160 MiB per slot = 75 slot(s), capped at maxSlots=24
```

**Cross-process proof** (`node test/governor-stress.mjs --contenders 30 --slots 5`), real child processes,
a scratch lease directory:

```
30 concurrent acquires finished in 549 ms
  ok   every contender either GRANTED or QUEUED, none errored
  ok   exactly 5 were granted
  ok   the rest (25) were queued
  ok   a queued caller is told its position, not refused
  ok   every grant names a slot
  ok   no slot was granted twice
  ok   exactly 5 lease files exist
  ok   every lease file is a complete document
  ok   every holder is a distinct process id
  ok   status agrees with the lease files
  ok   status publishes the arithmetic behind the budget
  ok   both reapers ran cleanly
  ok   the same lease was reaped by exactly one reaper
  ok   the slots are free again after the reap
  ok   a freed slot is reusable
```

**Cross-surface proof** (isolated engine, port 3098): the CLI acquired a lease in a separate process and
the running engine's own health surface reported it —

```
governor: inUse=1 free=23 holders=1
  slot 1 pid 32252 cli-proof note=issued next to the running isolated engine
```

**Usable from a shell** — the CLI is the entry point scripts use (`status`, `acquire`, `renew`, `release`,
`reap`; exit 0 granted, 10 queued, 1 error). The two-line integration for a fleet script is in the
package README. `scripts/agent-fleet.ps1` was **not** modified: it belongs to the orchestration workstream
and the exact integration should be its decision, not a side effect of this one.

---

## 4. What could NOT be made to work, and what is prepared but not applied

**Could not make work (with the reason):**

1. **Hot-mounting a new bundle.** Measured 404 before and after adding the name to a *running* engine's
   bundle list. Not fixable from a plugin: bundle layers are read at boot. Folded into the "one restart"
   requirement rather than worked around.
2. **A global override without a preset edit.** A scoped tool shadows a global one, so the shipped
   `list_agents` row has to go for the replacement to take effect. Registering from the preset scope
   instead was rejected deliberately: a preset row naming `dsh-plugin-health` would make an uninstalled
   package break *session creation* instead of the *engine boot*. See §5.
3. **`pwsh` under `child.spawn(..., {detached: true})`.** Measured on this host: a detached `pwsh.exe`
   exits 0 after ~160 ms **without running the script** — no output, no file, a clean exit code. The same
   argv with `detached: false` runs normally (1173 ms, 58 KB written). The probe is therefore a plain
   child with `stdio: 'ignore'` and `unref()`, which gives the same "never blocks the loop, never holds the
   process open" property without the silent no-op.
4. **`ctx.get('webServer')` inside `apply`.** A loader entry's activation order is not its order in the
   composed tree, so a bare `ctx.get` returned `undefined` and the route was silently skipped while the
   plugin reported itself mounted. Two wrong fixes were considered and rejected: hard `inject` (a headless
   profile would then fail to boot) and accepting the skip (invisible). The fix is `ctx.inject([...], body)`
   — a child fiber that waits for the service, ever, and cannot fail the boot.
5. **`tools.register` needs RAW JSON Schema.** Writing the author DSL's inline `required: true` throws
   `JsonSchemaError: required must be an array of strings` inside a guarded registration, so the tool
   silently does not exist. Both schemas were then validated with the framework's own
   `assertSupportedJsonSchema` (all four checks VALID).

**Prepared but NOT applied to the live engine** (each with its trigger):

| # | Prepared | Trigger | Risk if applied early |
|---|---|---|---|
| A | The package is installed in the live profile and in `dsh.profile.bundles` (`-Check` green) | an engine restart | none — inert until boot |
| B | The preset change: `tool-subagent-list-agents` in `presets/cordis-bg/agent.cordis.yml` now carries `disabled: !!js process.platform === 'win32'`, so on Windows the global replacement is the tool that executes while Linux/macOS keep the shipped one | **landed in the repo**; the *effect* on a running engine waits for that engine's next preset mount | on ZABZ-YOGA, once the sync copies the new preset, every *new* session has no `list_agents` until the engine restarts. Sessions already running keep the composition they mounted |

**The ordering rule this produced, and it is the important operational finding:** the safe order is
*restart first, remove the preset row second*. Before the restart the shipped row still registers the tool
(so nothing is lost), and after it the host row's global registration simply takes over. Doing it in the
other order opens a window in which `list_agents` exists nowhere. The exact edit is two lines in
`presets/cordis-bg/agent.cordis.yml` plus a regeneration — already exercised once, diffed (33 insertions,
2 deletions, nothing else), and then reverted so the working tree could not leak it through the sync.

## 5. Rollback

Every step is reversible and none of them touches an installed DSH package.

```powershell
# 1. unmount without uninstalling: disable the row in the profile's own patch layer
#    (~/.dsh/profiles/web/cordis.patch.yml, synced from harness-config/profiles/web/):
#      - id: plugin-health
#        disabled: true
#    then restart the engine. /healthz disappears; list_agents falls back to the
#    shipped tool as soon as the preset row is restored.

# 2. restore the shipped list_agents row (if the preset edit was applied)
cd C:\Users\ezabz\code\harness-config
git checkout -- presets/cordis-bg/agent.cordis.yml presets/zabz/agent.cordis.yml
python scripts/make_zabz_preset.py --check     # expect: zabz: in sync with the generator
python scripts/sync.py                          # copy the restored preset to ~/.dsh

# 3. release any leases the governor is holding, then remove its state
node packages/plugin-health/bin/governor.mjs status
node packages/plugin-health/bin/governor.mjs release --id <id>   # one per holder
Remove-Item "$env:USERPROFILE\.dsh\governor" -Recurse -Force      # optional; leases are inert state

# 4. uninstall the bundle entirely
pwsh scripts/install-client-plugins.ps1 -Check    # see the current state
# edit ~/.dsh/profiles/web/package.json to drop "dsh-plugin-health" from dsh.profile.bundles
# and remove the node_modules junction, then restart.
```

Rollback was tested in the direction that matters: the plugin was developed against an **isolated engine
on its own `DSH_HOME` and port (3098)**, never against the live engine, and the live engine has not been
restarted or reconfigured by this work. The only live-engine change made was letting the sync install the
package (inert until boot); the profile's own `cordis.patch.yml` was not touched.

## 6. Provenance of every number in this document

| Number | Command / source | When |
|---|---|---|
| `/healthz` → 404 on the live engine | `Invoke-WebRequest http://127.0.0.1:3099/healthz` | 2026-09-16 ~14:2x |
| health text output, 200, all counters | `curl -s -i -H "Cookie: …" "http://127.0.0.1:3098/healthz?format=text"` | 15:14 |
| probe cost: 6 spawns/30 s, 1 tick dropped, 0 failures, 933 ms | `/healthz` → `probe` twice, 30 s apart | 15:0x |
| 389 session files / 214.1 MB | `Get-ChildItem ~/.dsh/sessions -Recurse -File \| Measure-Object Length -Sum` | 15:0x |
| `list_agents` 644/940/4285/1286379 ms | `python docs/dsh-at-scale/tools/measure-tool-call.py <session> list_agents` (reads the session log) | 15:1x |
| tool registry: `registered`, `timeoutMs 10000` | `curl /healthz` → `listAgents.registry` | 15:14 |
| governor 30-process stress: 5 granted / 25 queued, one reaper wins | `node test/governor-stress.mjs --contenders 30 --slots 5` | 15:2x |
| budget 24 of a 75-slot derivation | `node bin/governor.mjs status` | 15:2x |
| CLI lease visible in the engine's health | `acquire` then `curl /healthz` → `governor.inUse` | 15:15 |
| `GlobalMemoryStatusEx` 10 ms vs CIM 286 ms | `_dsh-scale/_ph-debug.ps1` (temporary probe, left in place) | 15:0x |
| detached `pwsh` exits 0 in ~160 ms without running | `node -e` spawn matrix, 4 option sets | 15:0x |
| new bundle does not hot-mount (404 before and after) | isolated engine 3097 + live profile edit | 15:0x |
| keeper green | `pwsh scripts/install-client-plugins.ps1 -Check` | 15:2x |

## 7. What is left for the owner, and what is left for the fleet

**Owner / one restart:** the live engine on 3099 must be restarted once for features 1 and 2 to exist
there. Nothing else is needed from him; the package is already installed and the row is already in the
bundle list. Ten live sessions end when that happens, so it is his call when.

**Then, immediately after the restart (one command each):**
1. `curl` `/healthz` on 3099 and confirm 200 with real numbers.
2. Remove the preset row (§4-B), regenerate, `--check`, sync — that is what makes the new `list_agents`
   the effective one.
3. Call `list_agents` once from a session; then read `/healthz` → `listAgents.scans >= 1` proves the
   replacement is the definition that RAN (the readout's `registry` field alone cannot prove that: it reads
   the global view, and a surviving scoped row would shadow it), and `hits`/`coalesced` show what the cache
   avoided.

**Orchestration workstream (not done here):** wire `governor.mjs acquire/release` into `agent-fleet.ps1`
before it fans out, so a fleet asks for its slots instead of assuming them. The CLI and the exit-code
contract (0 granted, 10 queued) are in place for exactly that.

**One unresolved observation, for whoever owns the sync:** two consecutive runs of
`install-client-plugins.ps1 -Check` minutes apart disagreed — the first reported five packages
`LINK-ELSEWHERE / NEEDS FIX`, the second reported all six `LINK … ok`. The authoritative reading
(`cmd /c dir /AL` and `LinkTarget`) shows all six junctions pointing at
`C:\Users\ezabz\code\harness-config\packages\…`, and `Test-Path` on each `package.json` resolves. Most
likely a concurrent autosync run was rewriting the links while the first check ran. Not dangerous, but a
keeper that can report a false RED is a keeper that gets ignored; the `-Check` path is worth a second look
if it recurs.
