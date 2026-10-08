# Stream A — The as-built inventory and the consolidated evidence base

**Written:** 2026-09-17 23:47 local (2026-09-18T03:47Z) on **ZABZ-YOGA**, reading the tree at
`C:\Users\ezabz\code\harness-config` @ git `697ac3a` (dirty: `journal/index/*` modified, many
`_scratch/*` untracked).

**This is the factual floor, not a redesign.** Stream A writes exactly one file. Nothing was
started, stopped, restarted or killed; no file outside this one was created, modified or deleted;
every shell command run was read-only (`Get-*`, `Resolve-DnsName`, `Test-Connection`, `Invoke-WebRequest`
GETs against loopback, `journal.py check`, `Get-ScheduledTask`, `Get-CimInstance`, `Get-FileHash`).

**The owner was working on this machine throughout.** Engine `pid 4416` on `127.0.0.1:3099`,
started 2026-09-17 21:39:30 local, was never touched. It served live sessions the whole time —
13 agent loops were executing at 23:47 local (`GET http://127.0.0.1:3086/mesh/capacity`,
`"agents":{"loopsRunning":13,"sessionsLive":38}`).

---

## 0. How to read this document

Every claim carries a tag. The tags are not decorative; the whole point of this file is that a
reader can tell the difference between what a command printed and what a document asserted.

| tag | meaning |
|---|---|
| **[LIVE]** | I ran a read-only command in this session and quote its output. Command and output are in the text. |
| **[DOC-M]** | Copied from a document that presents the number as MEASURED — a command was run and its output quoted. The document is named. |
| **[DOC-R]** | Copied from a document that presents the number as READ out of source code, or REASONED / derived / modelled. The document is named. |
| **[DUP]** | The number appears in more than one document and they disagree. Both values and both sources are given. Never averaged, never picked. |
| **NOT VERIFIED** | Asked for and not obtained. A refusal, stated as a refusal. |

**Three things I could not do, stated up front.**

1. **The brief's question "how many mesh placements happened in 80 minutes of an overloaded
   machine" has no answer in this record, and I believe the premise is wrong.** Four independent
   searches (mine, plus a delegated repo-wide grep for `80 minutes`, `in 8x minutes`,
   `mesh placements`, `0 placements`, `no placement`) found no 80-minute placement window anywhere
   in `harness-config`, in any document, journal entry or log. The nearest measured facts are the
   opposite shape and are given in §2.13. If the 80-minute figure exists it is not written down,
   and this document will not invent it.
2. **A first-party reading of the *warm* session-list path is not available.** The proxy's own
   counters show a cold walk still taking seconds (§2.7); the document's 29 ms figure predates the
   proxy restart I observed. Marked **[DUP]**.
3. **The 0.81 GB/turn figure is dead, but the number that replaced it was measured on a different
   machine from the one the constant was written for.** §3.1. This is the single largest gap the
   redesign inherits.

---

# PART 1 — THE AS-BUILT INVENTORY

Fifteen components. For each: what it owns, what it depends on, what breaks when it fails. Anything
I did not verify live is tagged as the document that claims it.

## 1.1 The engine

| | |
|---|---|
| **What it is** | One `node .../@deepseek-ai/dsh/lib/bin.js web --port 3099 --no-open` process. `[DOC-M]` incidents/2026-09-17-dsh-engine-boot-failure/diagnosis-report.md Appendix A |
| **Live** | `[LIVE]` `Get-NetTCPConnection -LocalPort 3099 -State Listen` → `127.0.0.1 3099 OwningProcess 4416`. `[LIVE]` `Get-Process -Id 4416` → `RSS 1550.4 MB, Private 1898.8 MB, Threads 13, Start 09/17/2026 21:39:30` |
| **Owns** | Sessions (in-memory objects **in this one process**), the toolbelt, the MCP bridges, the sandbox, the credential store, the agent runtime, and the plugin tree composed from the profile. `[DOC-M]` docs/dsh-at-scale/10-dsh-source-audit.md §1 |
| **Does not own** | A session is **not** a process and a subagent is **not** a process — `NM\dsh-subagent-spawn-in-process\lib\index.js:5-9`, "runs each child as a fresh child Agent on the same cordis context … **The cheapest transport**". `[DOC-M]` 10-dsh-source-audit.md §1. A **tool call** normally is **two** processes. |
| **Depends on** | `DSH_HOME` (`C:\Users\ezabz\.dsh`); the profile at `<DSH_HOME>/profiles/web`; the junctions in `<DSH_HOME>/profiles/web/node_modules`; the npx checkout `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules`; `@deepseek-ai/schemastery` resolving through the profile anchor. |
| **Config split** | **Host plane** = `~/.dsh/settings.yaml` (machine-wide: `permission.defaultPreset`, `agent-default-model`, `agent-presets.default: zabz`, `agent-loop.maxParallelToolCalls`) plus every *host-plane row* of a mounted bundle. **Preset plane** = `presets/<name>/agent.cordis.yml` (per-session tool grants). A **bundle name** in `profiles/web/package.json`'s `dsh.profile.bundles` is read **at boot**; `cordis.patch.yml` is re-read live (`"patchReload": "live"`, `[LIVE]` `~/.dsh/profiles/web/package.json`). |
| **Breaks when it fails** | Everything. This is the keystone. A failed boot presents as `ensure: engine on 3099 is not answering` and the launcher opens windows against a dead port → `ERR_CONNECTION_REFUSED` in every window. |
| **Observed failure mode** | `[DOC-M]` incidents/…/README.md: a missing `.dsh` segment in a generated `createRequire` anchor made the whole plugin tree fail to load and the engine `exit 1` — **eleven hours after the rebuild that armed it**, on an unrelated reboot. |

**Live engine detail `[LIVE]`** — `GET http://127.0.0.1:3099/mesh/health` returns
`"host":"zabz-yoga","node":"zabz-yoga-1","fqdn":"zabz-yoga-1.tail93e6e6.ts.net","identityDegraded":false`,
`"version":"0.2.0"`, `"limits":{"maxConcurrent":5,...}`, `"concurrency":{"limit":5,...,"terms":{"cpu":5,"mem":36,"declared":12,"hard":24,"binding":"cpu"}}`.
The `host`/`node` disagreement inside one document is a live defect with a documented history — §4.4.

## 1.2 The profile/junction mount (live reload)

| | |
|---|---|
| **What it is** | Directory junctions from `<DSH_HOME>/profiles/web/node_modules/<pkg>` into `C:\Users\ezabz\code\harness-config\packages\<pkg>`. `[LIVE]`, all ten junction targets read from `~/.dsh/profiles/web/node_modules`: `dsh-mesh-broker`, `dsh-plugin-attention`, `-attention-badge`, `-cost`, `-health`, `-mesh-http`, `-mobile`, `-remote-fanout`, `-session-link`, `-windows` |
| **Owns** | The mechanism that makes a rebuild in the repo live in the profile **with no install step**. |
| **Depends on** | The junction's **ACL owner** — not the reader's logon class, and not who created it. `[DOC-M]` docs/mesh/106-desktop-last-mile.md §1/§2: a junction owned by `BUILTIN\Administrators` is traversable by a remote-logon (sshd) process; one owned by `zabz-tech\ezabz` is not; a **local** Interactive process traverses **both**. Measured 9/9. |
| **Keeper** | `scripts/install-client-plugins.ps1` (`-Check` reports a broken bundle; it *removes* a bundle name whose package declares no `dsh.bundle`). `[DOC-M]` docs/mesh/97-fleet-repairs.md §1.2. **The POSIX twin `scripts/install-client-plugin.sh` still has the pre-fix bug** — it pushes `name` into bundles with no `dsh.bundle.patch` test. `[DOC-M]` 97 §5 item 1, called there "the single highest-value follow-up". |
| **Breaks when it fails** | Two ways, both silent-ish. (a) A rebuild **arms** a fault that fires at the next process start — the 2026-09-17 incident, and the reason `--dump-config` is not proof (Part 3). (b) A junction with the wrong owner resolves for some readers and not others: `--dump-config` exits 0 for one reader and 1 for another **on the same bytes in the same minute**. `[DOC-M]` 106 §8: `exit=1 lines=16` (ssh-spawned) vs `exit=0 lines=620` (local Interactive). |

## 1.3 The browser windows (multi-window launcher, per-slot origins, shared profile)

| | |
|---|---|
| **What it is** | `multi-window/dshw.ps1` (154,731 B), `dshw.cmd`, `dshw-launch.cmd`, `dshw-proxy.mjs` (25,712 B), `dshw-geometry.ps1`, `windows.json`. |
| **Live config** | `[LIVE]` `multi-window/windows.json`: `"mode":"single"`, `"primaryPort":3099`, `"browser":{"kind":"edge","profileMode":"shared","sharedProfile":"_shared","windowSize":"700,440"}`, `"origins":{"enabled":true,"basePort":3200,"count":24,"script":"dshw-proxy.mjs","ttlMs":15000}`, 16 slots, `"maxWindows":24`. |
| **Profile vs origin** | `profileMode:"shared"` gives **one** Chromium `--user-data-dir` for every window. Per-window *identity* is preserved by giving each window its own **loopback origin** (`127.0.0.1:3200 + slotIndex`), because `localStorage["dsh.sessions.current"]` is keyed **by origin** (`dsh-api-session-controller/lib/client.js:3058`). `[DOC-M]` docs/multi-window/MEMORY-AND-SESSION-LIST.md §1. `profileMode:"per-window"` restores the old behaviour exactly, including its cost. |
| **Live** | `[LIVE]` sixteen `127.0.0.1:32xx` listeners `3200..3223` served by node `pid 30128` (`dshw-proxy.mjs --base 3200 --count 24 --target 3099 --ttl 15000`), which is also the registered `origins.pid`. `[LIVE]` `Get-Process msedge` → **66 processes**. |
| **Registry** | `[LIVE]` `~/.dsh/multi-window/windows-registry.json` currently holds a **two-generation mix**: keys `"3","4","5".."14 - auto"` carry `"port":"3099"` (pre-change, profile-keyed) while `"1 - main"` carries `"port":"3200"` and `"2"` carries `"3201"` (post-change, origin-keyed), with timestamps from 21:40 today through 23:44 tonight. |
| **Live consequence** | `[LIVE]` `GET http://127.0.0.1:3200/__dshw/open` → `{"ports":[3200],"live":{"3200":4}}` — exactly **one** window origin is live, while the registry still names fourteen slots as `open: true`. This is the incident README's open item 4 ("only one window group remained live within ~90 seconds … **No launcher log records a close or a reap**") still true ~2 hours later. |
| **Breaks when it fails** | In shared mode the **browser process is a single point of failure for every window** — a renderer crash takes one window, a browser-process crash takes all of them. `[DOC-M]` MEMORY-AND-SESSION-LIST.md §1 "What the owner loses". |

## 1.4 The origins proxy

| | |
|---|---|
| **What it is** | `multi-window/dshw-proxy.mjs` — a raw TCP splice to 3099 on 24 loopback ports, **plus one cached POST `/api/session/list`** re-labelled per caller. |
| **Owns** | (a) window identity (the origin); (b) the session-list cache. |
| **Depends on** | Winning a single-instance race. `[DOC-M]` MEMORY-AND-SESSION-LIST.md §3C: `ensure` runs every minute, so a manual `dshw ensure` and the watchdog can call `Start-OriginsProxy` at the same instant — measured, **two instances came up, one holding 3200-3215 and the other 3216-3223**, "healthy from any single port, broken as a whole." Three guards now exist (task left *registered* for `-MultipleInstances IgnoreNew`, exit 0 if `/__dshw/stats` already answers, atomic `wx` lockfile with pid liveness). |
| **Live** | `[LIVE]` `GET http://127.0.0.1:3200/__dshw/stats` → `{"spliced":112,"served":3,"filled":23,"cold":1,"prewarm":20,"prewarmSkipped":0,"errors":0,"cached":true,"ageMs":30822,"rows":694,"hasAuth":true,"openPorts":[3200]}` |
| **Live defect** | `[LIVE]` `~/.dsh/multi-window/watchdog.log` shows **9 consecutive `ensure` runs** (23:12:41 → 23:20:42 local) each logging `ensure: origins prewarm did not fill the cache: no auth cookie seen from any window yet`. The log then goes silent for the prewarm line, and `origins.log` shows a fresh proxy listening at `03:25:10Z` and `cache filled rows=685` at `03:25:22Z`. So the prewarm path failed for ~13 minutes and recovered only because the proxy was **restarted by something outside this session**, not because prewarm succeeded. An operator reading the stats today sees `prewarm:20` and would conclude it works. |
| **Breaks when it fails** | A plain splice **never fills the cache** — `[DOC-M]` MEMORY-AND-SESSION-LIST.md §2 "THE BUG INSIDE THE FIX": with keep-alive reuse "the proxy's own counters read `spliced=19, cold=0` while the sidebar sat empty". The fix rewrites `Connection:` to `close` on forwarded requests (never on upgrade). Without the proxy, every window pays the cold walk (§2.7). |

## 1.5 The gate (`phone-gate.py`), the device allow-list, and `tailscale serve`

| | |
|---|---|
| **What it is** | A Python **raw TCP relay**, not an HTTP proxy, on `127.0.0.1:3086`, published by `tailscale serve` as `https://zabz-yoga-1.tail93e6e6.ts.net/`. |
| **Live** | `[LIVE]` `Get-NetTCPConnection -LocalPort 3086 -State Listen` → `127.0.0.1 3086 OwningProcess 16840`; `[LIVE]` process = `pythonw.exe "...\scripts\phone-gate.py" --listen-port 3086 --engine-port 3099 --engine-authority 127.0.0.1:3099 --log-file ...`, parent pid 8528. `[LIVE]` `tailscale serve status` → `https://zabz-yoga-1.tail93e6e6.ts.net (tailnet only) |-- / proxy http://127.0.0.1:3086` |
| **Owns** | (a) first-visit sign-in: a browser asking for `/` with no cookie and no token gets a `302` to `/?token=<live>`; everything else is relayed byte-for-byte, so the WebSocket mux `/api/remote.mux` passes through untouched. `[DOC-M]` scripts/phone-gate.py header. (b) **the capacity surface** — `GET /mesh/capacity` is answered **before** the sign-in logic, which is why it is reachable unauthenticated from the tailnet. `[DOC-M]` docs/mesh/95-audit-live-mesh.md §1.1. (c) the device allow-list. |
| **Allow-list** | `[LIVE]` `scripts/phone-gate-allow.txt` lists five tailnet addresses (laptop 100.72.162.5, iphone 100.85.105.93, desktop 100.85.153.96, secratary 100.84.72.88, zabz-tech-linux 100.105.248.90) and **deliberately excludes** `100.126.146.121` (the employee's Mac — enrolled under the *same* Google identity, so an identity check cannot exclude it, only the address list can). It is **fail-open**: a missing or empty list signs in *every* device and says so loudly. |
| **Chain** | `tailscale serve` (TLS + tailnet-only) → gate :3086 → engine :3099. The engine binds loopback only, so 3086 is the only non-loopback door. `[LIVE]` non-loopback listeners on this host: 22, 135, 139, 443 (`tailscale` pid 8600), 445, 1035, 3000, 4586, 5040, 5357, 5432, 5985, 7680, 47001 + RPC ephemerals. |
| **Breaks when it fails** | Remote and phone access, and **the mesh's view of this node** — the broker reads only `/mesh/capacity`, which the gate serves. A dead gate makes this laptop invisible to placement and unreachable from the phone, while its own windows keep working. |
| **Known live state** | `[LIVE]` `GET http://127.0.0.1:3086/mesh/capacity` → `{"schema":1,"node":"zabz-yoga-1","fqdn":"zabz-yoga-1.tail93e6e6.ts.net","at":"2026-09-18T03:46:41Z","cpu":{"logical":22,"physical":16},"mem":{"totalMiB":32373,"freeMiB":11598,"swapUsedPct":0.0},"agents":{"loopsRunning":13,"sessionsLive":38},"governor":{"budgetSlots":24,"inUse":0,"queued":0},"accepts":{"oneShot":true,"fleet":true,"maxChildren":12,"reason":null}}`. Note `accepts.maxChildren: 12` — a **literal**, `MESH_MAX_CHILDREN = 12` (`scripts/phone-gate.py:939`), identical on all five nodes including the 4-core authority. `[DOC-M]` 95 §1.4. |

## 1.6 The mesh — broker, provider, transports v1/v2

| piece | what it is | owns | depends on | breaks when it fails |
|---|---|---|---|---|
| **Broker** | Node service, systemd unit `mesh-broker`, `127.0.0.1:3091`, verbs `POST /place`, `POST /done`, `GET /nodes[?fresh=1]`, `GET /healthz`. `[DOC-M]` docs/mesh/76-broker.md §4, 95 §2.1 (`Main PID 2024394`, `active (running) since Thu 2026-09-17 03:54:31 UTC; 9h ago`, `enabled`) | placement decisions from live readings. **Its only state is in memory** — readings cached ≤15 s plus a lease table, TTL 900 s; "**No file is written anywhere**" `[DOC-M]` 76 §1 | each node's gate answering `/mesh/capacity`; the roster `packages/mesh-broker/nodes.json` | placements stop. Nothing else notices — the provider falls back to a fixed target (`~/.dsh/mesh/placements/*.json` all read `"leaseReleaseSkipped": "no lease: this provider is on a fixed target"`, `[LIVE]`) |
| **Roster** | `[LIVE]` `packages/mesh-broker/nodes.json`: four rows — `zabz-tech`, `zabz-yoga-1`, `zabz-tech-linux`, `secratary` — plus `"_excluded_on_purpose": {"lakewooechsmini": ...}`. `cacheTtlMs 15000`, `readTimeoutMs 1500`, `leaseTtlMs 900000` | who may be placed on | Tailscale **DNS labels** (`lib/config.js` refuses to boot on a row whose name is not the first label of its own fqdn) | the Mac is unreachable to placement even though it answers |
| **Provider v1 (ssh)** | `packages/plugin-remote-fanout` — `providerName: remote-ssh`, `ssh <alias> dsh --profile headless "<prompt>"`. Deployment facts live in `profiles/web/cordis.patch.yml`, **not** in the package | remote child dispatch | ssh; the target's `dsh` executor **or** an explicit `nodeExe`+`bin.js` pair; the credential file the executor sources | children die before running. Measured twice, both exit `127` then `MISSING_CREDENTIAL` `[DOC-M]` 97 §4.2 |
| **Provider v2 (HTTP)** | `packages/plugin-mesh-http/**` — `POST /mesh/run` on the node's own engine, HMAC-SHA256 over `(timestamp,nonce,body)`, secret at `C:/ProgramData/dsh-mesh.env` `[LIVE]` per `/mesh/health` | the same dispatch without ssh | the route mounted (one engine restart per node); the derived concurrency limit | falls back to v1 (404 on `/mesh/health` means "no route here") |
| **Mount plane** | `remote-fanout` and `tool-subagent-remote` are **host-plane** rows; the *tool* is granted per agent by `presets/zabz/agent.cordis.yml`. The provider **cannot** be a preset row — `ctx.subagents` is process-wide and `registerProvider` throws `DUPLICATE_PROVIDER` on a second registration. `[DOC-M]` docs/mesh/90-provider-mount.md §2 | | | **A new bundle does not hot-mount.** Measured: `GET /healthz` → 404 before and after adding the bundle name to a *running* engine. `[DOC-M]` docs/dsh-at-scale/90-plugin-health-governor.md §4 |

## 1.7 The journal

| | |
|---|---|
| **What it is** | Append-only, **one file per entry**: `journal/entries/<kind>/<ID>.md` for five kinds. A generated cache, a state tier, an allocation ledger, and a repair toolbox. |
| **Live counts** | `[LIVE]` `decisions 224 · handoff 404 · lessons 773 · pain 219 · wins 175` = **1,795 entry files**. Plus frozen flat files still on disk: `HANDOFF.md 384,016 B`, `LESSONS.md 163,523 B`, `DECISIONS.md 98,106 B`, `PAIN.md 99,685 B`, `WINS.md 50,910 B`, `QUESTIONS.md 25,304 B`, `NOW.md 6,753 B`, `AUDIT.md 6,977 B`, `SPEC-v2.md 17,171 B`, `README.md 14,613 B` (= 938 KB of legacy). |
| **Live cache** | `[LIVE]` `journal/index/`: `journal.db 10,534,912 B`, `entries.tsv 379,595 B`, `aliases.tsv 49,751 B`, `stamp.json 658 B`, **plus a residue pair** `.journal.db.tmp35748` (1,024,000 B) and `-journal` (26,112 B). |
| **Id allocation** | Monotonic **band reserved per host** in `journal/alloc/bands.tsv`, columns `kind reserved_from reserved_through host stamp rev`; `claim` reserves and publishes, `append` is **LOCAL ONLY** and cannot move any ref. `[DOC-M]` docs/mesh/108-id-allocation.md §4.1–§4.2, §5.5 |
| **Repair tools** | `check`, `repair-ids`, `dedupe`, `import-legacy`, `idguard.py`, `verify-alloc.py`, `rehash.py`, `selftest.py`, `migrate.py`. `[LIVE]` all present under `journal/tools/`. |
| **Live health** | `[LIVE]` `python journal/tools/journal.py check` → `journal: cache is stale and locked by another session — answering from entries/`, then warnings and **exit 0**. (Namely: `WARN H83 (handoff) has an empty body`, ~95 dangling-ref warnings including `docs/mesh/85-hygiene.md`, `docs/mesh/92-provider-placement.md`, `docs/mesh/104-node-enabled.md`, `lpt-hub:D194`, `personal-secretary-mvp@47c3db250`, and `INFO` notes that `D105`/`D106`/`D136` carry legacy ids in their headings.) |
| **Breaks when it fails** | It has failed three documented ways and each is a design lesson: **(1)** the file lock's stale-break path `unlink`ed a live lock, so *two writers entered* — the mechanism behind **161 collided ids on 2026-09-14** `[DOC-M]` docs/dsh-at-scale/30-locks-audit.md §1.2/§1.3, since fixed to a real OS lock + inode check `[DOC-M]` docs/dsh-at-scale/PROGRAM.md line 38. **(2)** the allocator cannot see another machine's uncommitted files, so two machines mint the same number offline — **18 contested ids on 2026-09-17** `[DOC-M]` docs/mesh/107-journal-convergence.md §1, see §2.18. **(3)** an inline-push version of `append` pushed a commit that **deleted 1,249 paths — all 1,728 journal entries — and exited 0**, because the parent *commit* was resolved from a freshly fetched ref while the parent *tree* was resolved from a mutable local name **13 commits behind** `[DOC-M]` 108 §5.1. |
| **Defects still open** | `[DOC-M]` 107 §6.6 / 108 §8.1: both `questions` and `import-legacy` leak their `.lock`, holder pids dead; and **the generator of the id collision is untouched** — "The next pair of concurrent writes recreates this defect" `[DOC-M]` 107 §7. |

## 1.8 The schedulers — every DSH scheduled task

`[LIVE]` `Get-ScheduledTask | Where TaskName -like '*DSH*' | Get-ScheduledTaskInfo`. All run as
`ezabz`, `LogonType: Interactive`. All actions are hidden via a `wscript.exe //B //NoLogo
"...\scripts\hidden-tasks\<name>.vbs"` wrapper except **DSH Origins Proxy**, which is the node
process directly.

| task | state | cadence | what it actually runs | what it can change |
|---|---|---|---|---|
| **DSH Engine Watchdog (1m)** | Ready | **PT1M** | `dshw.ps1 ensure -ConfigPath ...\windows.json` | **starts the engine**; manages the proxy; prewarms the session cache; writes `engine-recovery.log`, `watchdog.log` |
| **DSH Mesh Restart When Idle** | Ready | **PT15M** | `scripts/mesh-restart-when-idle.ps1` | **can restart a node's engine** if idle. Does not restart here: `[LIVE]` `~/.dsh/mesh/restart-when-idle/decisions.log` every 15 min tonight reads `decision=DEFERRED … 1..19 running session(s), N agent loop(s)`. Since 21:44Z it first logged **16 consecutive `decision=NO-EVIDENCE port=3099 enginePid=? … the engine could not be read, so nothing was restarted and nothing was written`** (21:44Z → 01:29Z), then switched to `DEFERRED` at 01:44Z. |
| **DSH Mesh 0700 Restart** | Ready | daily 07:00 | `scripts/mesh-restart-at-0700.ps1` | same class; last run 9/17 07:00, **LastTaskResult 1** |
| **DSH Phone Gate** | Ready | **PT5M** | `phone-gate-ensure.ps1 -ListenPort 3086 -EnginePort 3099 -EngineAuthority 127.0.0.1:3099 -Publish` | starts/re-publishes the gate; can change `tailscale serve` |
| **DSH Origins Proxy** | **Running** | trigger-less (started by ensure) | `node dshw-proxy.mjs --base 3200 --count 24 --target 3099 --ttl 15000 --pidfile ~/.dsh/multi-window/origins.pid --log ...\origins.log` | owns 24 loopback ports and the session-list cache. `[LIVE]` `LastTaskResult 267009` |
| **DSH Process Reaper** | Ready | **PT10M** | `scripts/dsh-reap.ps1 -Apply -Quiet -MinAgeMinutes 30` | **kills processes.** The only DSH task that does. `[LIVE]` last run 23:40:01, result 0 |
| **DSH Multi-Window Launcher** | Ready | **at logon** | `dshw.ps1 up -WindowsMode no` | starts the engine, does not open windows. `[LIVE]` last 9/17 21:31:30, **result 1** (the boot-failure window) |
| **DSH Window Fleet Watchdog** | **Disabled** | (PT5M trigger present) | `dshw.ps1 health` | nothing while disabled |
| **DSH Metrics Sampler** | Ready | single 23:59, **no repetition** | `harness-metrics.ps1 -IntervalSeconds 20 -MaxHours 168` | writes `~/.dsh/metrics/*.csv`; the `_note` in its `.json` records that a finite `-Samples 540` version produced a measured **4.8-hour hole** |
| **DSH Metrics Sampler Watchdog** | **Running** | **PT5M** | `harness-metrics.ps1 -IntervalSeconds 20 -MaxHours 168` — **but from a snapshot path**: `[LIVE]` currently `pwsh … -File "C:\Users\ezabz\AppData\Local\Temp\harness-config-snap-20260917-233221\scripts\harness-metrics.ps1"`, and earlier today `…-snap-20260917-221723\…`, `…-171703\…`. The task re-launches a script **out of a temp snapshot of the repo**, not out of the repo. | writes the metrics CSVs. **`[LIVE]` `LastTaskResult 2147946720`** (= `0x800700A0`, "the directory or file cannot be created" class) |
| **DSH unified-search refresh** | Ready | **PT30M** | `cmd /c C:\Users\ezabz\.usearch\bin\usearch-refresh.cmd` (cwd `C:\Users\ezabz\code\unified-search\scripts`) | rebuilds the search index |
| **dsh-harvest-a1** | Ready | single 2026-09-17 22:26 | `C:\Users\ezabz\AppData\Local\Temp\dsh-harvest-a1.cmd` | **a one-shot task pointing at a temp file that may no longer exist** — verified `Ready`, not deleted |
| **DSH elevation probe** | Ready | none | `_scratch\elevated-listener.ps1 -Port 3077 -Seconds 240` | a 240 s elevated listener on 3077 |
| **PersonalSecretary-PushDSHSessions** | Ready | logon + **PT1H** | `node scripts/push-dsh-sessions.mjs` | pushes session data outward. `[LIVE]` last run 23:05:01, **result 1** |
| *not DSH, same install path* | | | `PersonalSecretary-HarnessSync` (logon + PT15M), `PersonalSecretary-NodeAgent` (PT1H), `PersonalSecretary-PushVSCodeChats` (PT1H), `LPT-EnvBackup` (daily), `LPT-EnvBackup-AtStartup` (boot), `LPT-MonthlyAnalysis` (daily), `VSCodeUpdate-20260803` | **`PersonalSecretary-HarnessSync` runs `git`-adjacent repo sync every 15 minutes** — it can move the tree under a running agent |

**`[LIVE]` 20 tasks match `DSH|PersonalSecretary|LPT|dsh`.**

## 1.9 The guards (spend guard, governor, hygiene)

| guard | what it is | live state | depends on | breaks when it fails |
|---|---|---|---|---|
| **Spend guard** | `dsh-plugin-cost/guard` — a host-plane loader row. One daily counter fed by `session/event`, one decision at `agent/pre-step` **before `step/start`**, so a refused step is never billed | `[LIVE]` `~/.dsh/spend-guard/day.json`: `{"day":1789689600000,"micro":8318426,"requests":2949,"unpriced":0,"lastVerdict":"ok","lastStep":14,"generatingAtLastDecision":12,"limitsUsd":{"warn":35,"fanout":80,"ceiling":150,"concurrencyCap":12},"writtenAt":"2026-09-18T03:45:28.872Z"}` → **$8.32 spent today, 2,949 requests, verdict ok, 12 generating** | `@deepseek-ai/schemastery` resolving **through the profile anchor**. This is the exact dependency that killed the engine on 2026-09-17 (`[DOC-M]` incidents/…/README.md) | the **whole engine**, not just the guard — a failed import of this row fails the plugin tree and `exit 1`. `onInternalError: closed` |
| **Admission governor** | `packages/plugin-health` — `lib/governor.js` (protocol), `bin/governor.mjs` (CLI), `lib/admission-tool.js` (model side). "One implementation, three entry points" | `[LIVE]` `/healthz` → `governor: 0 of 24 heavy slot(s) leased, 24 free, 0 waiting`; `[LIVE]` `/mesh/capacity` → `"governor":{"budgetSlots":24,"inUse":0,"queued":0}` | one lease **file per slot** created `O_CREAT\|O_EXCL`; liveness by **heartbeat, not pid guess**; reap guarded by an atomic rename | nothing to the engine. Budget = `(free physical − reserve) / 160 MiB`, reserve `max(2 GiB, 12%)`, cap 24, floor 4 `[DOC-M]` 90-plugin-health-governor.md §3. It **never refuses** — `QUEUED position N`, exit 10 |
| **Hygiene** | `scripts/dsh-reap.ps1` (task), `scripts/mesh-hygiene.ps1\|.sh`, `dshw.ps1 health`, `scripts/mesh-health.ps1` | `[LIVE]` `~/.dsh/multi-window/health.log` tail: `health: 1 engine(s) down (3099) - restarting` → `port 3099 restart FAILED … MODULE_NOT_FOUND` (21:37–21:40), then `recovery: missing=1 opened=1 (1 - main) held=` (23:44:35) | `dshw.ps1` | reap is the only automatic process-killer in the system; `mesh-health.ps1`'s default node list is `@('zabz-yoga-1','zabz-tech','secratary')` — **3 of 5 gated nodes** `[DOC-M]` 95 §5.1 |

## 1.10 The search/DB side

| | |
|---|---|
| **Unified search** | `[LIVE]` `C:\Users\ezabz\.usearch\bin\usearch-refresh.cmd`, driven by the `DSH unified-search refresh` task every 30 min, cwd `C:\Users\ezabz\code\unified-search\scripts`. Refresh is a **scheduled, state-changing job** with no DSH-side health surface I could find. |
| **Journal FTS** | `[LIVE]` `journal/index/journal.db` (10,534,912 B) — sqlite + FTS5 over the entries, rebuilt by `journal.py index`. `[DOC-M]` 30-locks-audit.md §1.4: a full rebuild is "the dominant remaining cost" inside the global lock. |
| **Company authority DB** | **On `secratary`**, not here. `[DOC-M]` 30-locks-audit.md §2.1 read this laptop's copy: `data\secretary.db` **504,360,960 B** (+ `-wal` 41,200,032 B, `-shm` 98,304 B), `journal_mode=wal`, 182 tables (authority: 203). Single-writer, `busy_timeout 10000`, `wal_autocheckpoint=10000`, `journal_size_limit=67108864` — **per-connection**, so any script connecting without them gets 4 MB checkpoints and a WAL that is never truncated. `[DOC-M]` §2.1. **`owner-queue.py` runs `executescript(SCHEMA)` on every invocation including `next`/`list`/`stats` — "a read takes the database's write lock"**, and **the file does not exist at `C:\Users\ezabz\bin\owner-queue.py` on this host** `[DOC-M]` §2.2. |
| **`~/.dsh/storages`** | `[LIVE]` `session_projcache/sessions/` — one JSON **per session**, 1,000+ files. `[DOC-M]` 10-dsh-source-audit.md §5: `NM\dsh-storage-json\lib\index.js:14-15` has **no lock and is last-write-wins by design**, so two engines on one `~/.dsh` would silently clobber KV state. |

## 1.11 Raw process/memory snapshot at 23:47 local `[LIVE]`

```
engine pid 4416 : RSS 1550.4 MB, Private 1898.8 MB, 13 threads, since 21:39:30
node.exe        : 18 processes (largest 1551 MB engine; then 209, 98, 60, 60, 60, 59, 59, 58, 58, 58, 57, 57, 56, 56, 45, 45, 39)
pwsh            : 10    msedge : 66    python/pythonw : 13
processes       : 403 total (per Win32_OperatingSystem) ; 394 (health/processes.json @ 03:45:29Z)
threads         : health/processes.json totals.threads = 6049, handles = 175226
memory          : physical total 32373 MiB (31.61 GiB) ; free 10740 MiB
commit          : \Memory\Committed Bytes = 27386.3 MB ; \Memory\Commit Limit = 44149.4 MB
paged pool      : 1856.7 MB ; nonpaged pool 1060.4 MB
os              : Microsoft Windows NT 10.0.26200.0
```

`~/.dsh/health/list-agents.json` `[LIVE]` is a held-breath signal:
`{"scans":4,"hits":0,"staleServes":2,"timeouts":3,"coalesced":0,"failures":0,"deadlineServes":3,"lastScanMs":4952,"lastScanAt":"2026-09-18T03:34:34.739Z","cacheMs":3000,"deadlineMs":8000,"at":"2026-09-18T03:34:34.739Z"}`
— **4 scans, 0 cache hits, 3 of 4 scans reaching the 8 s deadline, with a 3 s TTL configured.**
Four scans is a small sample and this is one reading, not a trend; stated as an observation.

---

## 1.12 THE SINGLE POINTS OF FAILURE, NAMED

Ranked by blast radius, with the measurement that establishes each.

1. **The engine on 3099.** One process for all 16 windows, all sessions, all agents. It has already
   failed to boot for 11 hours (`[DOC-M]` incidents/2026-09-17/README.md) and the launcher could not
   tell a dead port from a crash-on-boot. Everything else on this list is downstream of it.
2. **`~/.dsh/profiles/web/node_modules` junction ownership.** `[DOC-M]` 106 §1/§2 measured 9/9 that
   a junction owned by `zabz-tech\ezabz` is untraversable to any remote-logon reader while a
   `BUILTIN\Administrators` one is not — **the same profile reads differently to different readers
   in the same minute**. Silently changes whether a bundle resolves (§4.5).
3. **`dshw-proxy.mjs`.** Every window's origin *and* the session-list cache route through it. Two
   instances split the port range (§1.4); a plain splice means the cache never fills (§1.4).
4. **`phone-gate.py` on 3086.** The only non-loopback door, and the node's capacity surface for the
   mesh. Its allow-list is the only control that can exclude the employee's Mac — and it is
   **fail-open by design** if the file is missing or empty.
5. **`mesh-broker` on `secratary`.** Holds no state and writes no file, so its loss is invisible
   except as a fallback to a fixed target (`[LIVE]` every placement ledger reads
   `"leaseReleaseSkipped": "no lease: this provider is on a fixed target"`).
6. **The journal's single global lock.** One lock, no queue, no fairness. Measured hold times
   **41–98 s** under normal fleet load against a 120 s foreground kill budget `[DOC-M]`
   30-locks-audit.md §0/§7 — and `LOCK_WAIT_SEC = 240` is *larger* than the kill budget, so writers
   are killed mid-write. `[LIVE]` today's `journal.py check` reported
   `cache is stale and locked by another session` while still answering — i.e. the lock was held by
   another session at 23:47 local. `[LIVE]` dead-holder residue is still on disk
   (`index/.journal.db.tmp35748*`).
7. **The spend guard's import path.** A one-segment path mistake in this row took down the entire
   engine. The guard is a **load-bearing single point of failure for the whole harness**, not a
   bolted-on guard.
8. **`DSH Metrics Sampler Watchdog`.** Running every 5 minutes out of a **temp snapshot** of the
   repo, with `LastTaskResult = 2147946720`. It is the source of every longitudinal number in
   Part 2 (§2.21, §2.22) and it is currently misconfigured.
9. **`PersonalSecretary-HarnessSync`** every 15 minutes. It moves repo state under running agents
   and is not in the DSH task set, so a DSH-only audit will not see it.
10. **The profile's `dsh.profile.bundles` list.** Read **at boot only**. A bad row (a package with
    no `dsh.bundle`) makes a node unbootable while its *running* engine is fine — measured on the
    Mac, whose engine had been up 3.6 days on a profile that **could no longer be booted**
    `[DOC-M]` 95 §3.2.

---

# PART 2 — THE CONSOLIDATED EVIDENCE BASE

Every load-bearing number measured in this window, with source and time. **[DOC-M]** means the
source document presents it as measured with command and output; **[LIVE]** means I measured it.

## 2.1 The cost of one agent turn — commit and CPU

**The 0.81 GB figure is falsified. Twice, on two different instruments.**

| constant | value | source | verdict |
|---|---|---|---|
| commit per **generating turn** | **0.81 GB** | `docs/dsh-at-scale/PROGRAM.md:75`, reused as MEASURED by `10-inventory.md:668` and `40-hardware-costs.md:22` | **REFUTED** — `[DOC-M]` docs/mesh/84-calibration.md §3.1 |
| commit per **node process** | **0.58 GB** (r = 0.937, 477 rows) | `docs/mesh/60-verification.md` §2.2 | **too high by 2.7×** for the measured node (216 MiB/process); and "a process is not what a broker counts" `[DOC-M]` 84 §3.1 |
| commit per node process, **re-fit on the same file** | **0.465 GB** (r = 0.8545, 1,478 rows, intercept 16.33 GB, residSd 2.16 GB) | `[DOC-M]` 84 §3.1 | "60-verification's 0.575 GB **does not reproduce** on the file that produced it (477 rows then, 1,478 now)" |
| **the replacement: commit per concurrent turn** | **403.3 MiB**, 95 % CI **328.3…478.3**, n=63, r=0.8063 | `[DOC-M]` 84 §3, steady-state row-level fit | "**the number to use**" |
| the conservative fit | **402.3 MiB**, CI **271.5…533.0**, n=6, r²=0.948 | `[DOC-M]` 84 §3, one point per level | "the one I would quote against a decision" |
| honest interval | **≈270–530 MiB** | `[DOC-M]` 84 §3 | union of the two defensible estimates |
| cross-check, OS `\Memory\Available MBytes` | **−410.4** MiB/turn, CI −471.6…−349.1, r=−0.8617 | `[DOC-M]` 84 §3 | independent counter agrees within 2 % |
| cross-check, node process count | **+216 MiB/process × 1.74 processes/turn = 376 MiB/turn** | `[DOC-M]` 84 §3 | a third way to the same number |
| measured on the *other* node, next session | **366 MiB/turn** (peak Δ 2,930 MiB ÷ 8) | `[DOC-M]` docs/mesh/93-transport-concurrency.md §5.2 | "inside the CI, 9 % below the point estimate" |
| measured over ssh, 4 real children | **503 MiB/turn**, and 380/turn one sample earlier | `[DOC-M]` 93 §5.3 | "the same per-turn cost as v2, as it must be" |

**CPU per turn** `[DOC-M]` 84 §2.1/§4.3, derived as Δ mean CPU % ÷ measured live turns × 32 logical:

| level | prompt | logical CPUs per turn |
|---|---|---|
| N=2 | resident | 0.306 |
| N=4 | resident | 0.575 |
| N=6 | resident | 0.655 |
| N=8 | resident | 0.632 |
| N=8 | **tool-heavy** | **1.679** |

"From N=4 on the figure is stable at **0.58–0.66** logical CPUs per resident turn. A tool-heavy turn
costs **1.68**, i.e. **2.7×** a model-bound one." So the sentence in `scoring.js:22–24` — *"one
actively generating agent turn costs ~1 core (0.81 GB commit + ~1 core)"* — is wrong in **both**
halves and in **opposite** directions `[DOC-M]` 84 §3.1.

**Self-inflicted defect worth carrying:** 84's first slope read **301 MiB/turn**, not 403, because a
row was stamped at the top of a loop whose counters were read 2–3 s later. Fitted offset
**+1.2 to +3.4 s** (r = 0.64–0.91). `[DOC-M]` 84 §1.4.1.

## 2.2 The two calibrated constants

**`CORE_SLOT_FRACTION = 0.75`** (`packages/mesh-broker/lib/scoring.js:91`) — **not falsified, but
"unfalsifiable as written"**:

- "It lands inside the measured band, **but for the wrong reason**, and the band runs from **14 to
  52 turns** depending on the kind of turn and whether you count logical or physical processors."
  `[DOC-M]` 84 §0(3)
- The band: turns to occupy all **32 logical** processors ≈ **52** (resident) / **19** (working); to
  occupy **24 processors'** worth ≈ **39** / **14**. `floor(24 × 0.75) = 18` sits inside 14…39.
- **Why the derivation is wrong:** `scoring.js:23–24` derives a *CPU* budget from *"this laptop's
  paging threshold is 13-14 concurrent turns on 16 physical cores"* — "a **paging** observation used
  to set a **CPU** budget … the coincidence that `floor(16 × 0.75) = 12` is near 13–14 is why a wrong
  argument produced a usable number." `[DOC-M]` 84 §4.3
- **A units trap the constant hides:** `\Processor(_Total)\% Processor Time` counts **logical**
  processors, `cpu.physical` counts **physical** ones; the SMT conversion is **not measured**, "a
  **33 % error waiting to happen**" on ZABZ-TECH (24 physical / 32 logical). `[DOC-M]` 84 §4.3
- **The laptop's own curve — the one the constant is actually used for — was never measured.**
  `0.75 × 16 = 12` is what production uses; the laptop could not be loaded because it was already
  past the stop line. `[DOC-M]` 84 §6.1. **NOT VERIFIED.**

**`SWAP_PENALTY_PCT = 90`** (`scoring.js:93`) — **wrong as written:**

- `[DOC-M]` 84 §4.4(a), reading `scripts/phone-gate.py:1110–1149`:
  `swapUsedPct = max(0, committed − physical) / (commitLimit − physical) × 100`. "**The field is not
  swap.** … a commit-headroom metric wearing a swap name."
- Measured: **0.0 in every one of the 83 samples on ZABZ-TECH**, including the level that consumed
  41.5 % of all 32 logical CPUs; and **0.0 on ZABZ-YOGA at 03:54Z** with 28,532 MiB committed of a
  44,145 MiB limit, 10,692 MiB RAM free, 1,469 MB resident in the pagefile, pagefile 12 % used.
- To *reach* 90 % takes commit within **410 MiB (0.6 %)** of the limit on ZABZ-TECH and **1,174 MiB
  (2.7 %)** on ZABZ-YOGA. "It is a **near-OOM alarm wearing a percentage**."
- The replacement the document recommends: **commit headroom**, which the contract already
  publishes — `/healthz` carries `system.probe.commitAvailableBytes` and `commitLimitBytes`.

**Still live in code** `[DOC-M]` a14efd95's grep-confirmed line numbers, read this session:
`scoring.js:55 PER_SLOT_MIB = 160`, `:70 RESERVE_MIB = 3885`, `:91 CORE_SLOT_FRACTION = 0.75`,
`:93 SWAP_PENALTY_PCT = 90`.

## 2.3 Where the laptop actually binds — **[DUP]**, and this is the most important conflict in the file

| claim | value | source | kind |
|---|---|---|---|
| laptop binds on **commit**, and the ranking was blind to it | committed/physical **120–126 %** at 22:12 local, physical available **7.7 GiB**, pagefile resident **194 MB**, **and the broker still advertised `12 free slot(s) of 24`**; 31 minutes later it advertised **1** | `[DOC-M]` docs/mesh/109-pressure-routing.md §1, measured 2026-09-17 22:12 and 22:43 local | MEASURED |
| laptop binds on **CPU** | derived limit **5**, `"binding":"cpu"`, `cpu=5 mem=21` | `[DOC-M]` 93 §2.2 (13:52Z) | DERIVED |
| laptop commit trajectory | 24.88 → 25.01 → 25.51 → **27.11** → **29.92** → **34.72 GiB** across 03:40–04:00Z; "**3,408 MiB** of physical RAM free … the governor's own budget is at its **floor of 4 slots**" | `[DOC-M]` 84 §1.1 | MEASURED |
| `[LIVE]` right now | commit **27,386 MB of a 44,149 MB limit** (62 % of limit); free physical **10,740 MiB**; `swapUsedPct 0.0`; `loopsRunning 13` | `[LIVE]` `\Memory\Committed Bytes` + `/mesh/capacity` | MEASURED |
| the mechanism | "**because commit charge is not in the contract at all.** A dispatcher that asked the broker and obeyed the answer would have put the child **on the laptop**, on the authority's own numbers, **with no bug anywhere**." | `[DOC-M]` 109 §1 | REASONED on measurement |

**Both numbers are given and I do not reconcile them.** The derived `cpu` term of 93 and the direct
commit saturation of 84/109 are measurements of different things (a headroom budget vs an occupancy
observation), and the record does not contain a measurement that decides between them. **What *is*
decided: the laptop saturated on commit while the published contract said it had 12 free slots.**

**The first counter that degrades, within reach** `[DOC-M]` 84 §4.1: engine **loop-lag maximum
18 → 54 ms** at 8 tool-heavy turns — commit, pagefile %, disk queue and pages-in all flat. The 93
re-run the next day saw loop-lag max **17 → 17 ms** on a *tool-light* prompt, and says so.

## 2.4 Per-window browser memory, before and after the shared-profile change **[DUP]**

Measured on ZABZ-YOGA 2026-09-18 by `Get-CimInstance Win32_Process -Filter "Name='msedge.exe'"`
grouped by `--user-data-dir` `[DOC-M]` docs/multi-window/MEMORY-AND-SESSION-LIST.md §1.

**BEFORE — 7 windows on 7 private profiles:**

| profile | processes | MB |
|---|---:|---:|
| w1 | 9 | 917 |
| w2 | 9 | 1027 |
| w3 | 9 | 807 |
| w4 | 9 | 886 |
| w5 | 9 | 692 |
| w7 | 9 | 1064 |
| w8 | 9 | 854 |

"**74 msedge processes, 6,804 MB. Nine processes and a mean of 892 MB per window** — for a UI that
renders one page." *(Note the doc's own rows sum to 63 processes while it states 74; both are quoted
as written. `[DUP]`)*

**AFTER — shared profile, two runs:**

| snapshot | all msedge procs | all MB | shared-profile procs | shared MB |
|---|---:|---:|---:|---:|
| baseline (6 legacy windows) | 65 | 6,499 | 0 | 0 |
| after window A (origin 3200) | 74 | 6,941 | 9 | 612 |
| after window B (origin 3201) | 74 | 7,000 | 9 | 764 |
| baseline (cleaner earlier run) | 66 | 6,927 | 0 | 0 |
| after window A | 76 | 7,562 | 10 | 672 |
| after window B | 77 | 7,858 | 11 | 926 |

"**Per-window marginal cost: ~9 processes / ~892 MB → ~1 process / ~60–296 MB.** The one-time shared
tree is the floor: for N windows the total is `tree + N × renderer` instead of `N × tree`. The
projection at 8 windows is **17 processes against 72**." `[DOC-M]` MEMORY-AND-SESSION-LIST.md §1.

**Four different per-window figures exist in the record and they are all quoted, none averaged:**

| figure | source | date | kind |
|---|---|---|---|
| ~200–350 MB | `[DOC-R]` docs/multi-window/ANALYSIS-AND-DECISION.md §1 | 2026-09-11 | REASONED |
| ~770 MB default flags, **~454 MB lean** (−41 %) | `[DOC-M]` docs/multi-window/PERFORMANCE-MEASURED.md lines 71–74 | 2026-09-11 | MEASURED (6 windows / 54 procs / 2,722 MB) |
| ~680 MB (8.18 GB ÷ 12) | `[DOC-M]` 10-dsh-source-audit.md §6 line 398 | 2026-09-15 | MEASURED — **and the 8.18 GB itself was later corrected**: Σ`WorkingSet` **8,181.6 MB** vs Σ`WorkingSetPrivate` **3,622.9–3,898.1 MB**, "2.2× inflated" `[DOC-M]` PROGRAM.md lines 81–82 |
| ~892 MB (6,804 MB ÷ 7) | `[DOC-M]` MEMORY-AND-SESSION-LIST.md line 55 | 2026-09-18 | MEASURED |

`[LIVE]` `Get-Process msedge` right now → **66 msedge processes** on this machine, consistent with
the "after" shape.

## 2.5 The session-list walk time **[DUP]**

**BEFORE the proxy cache** — `tools/probe-session-list.ps1` against the live engine
`[DOC-M]` MEMORY-AND-SESSION-LIST.md §2:

```
run 1 : HTTP 200 in 25370.8 ms  ok=True  rows=679
run 2 : HTTP 200 in 25069   ms  ok=True
run 3 : HTTP 200 in 31357.1 ms  ok=True
```

"1.46 MB of JSON, 679 rows. Every other RPC on the same page load answered promptly, so this is not
a saturated event loop — it is **this one code path**."

**Root cause, reproduced without the engine** — `tools/replicate-list-scan.mjs`:

```
project dirs         : 6                        24 ms
session dirs         : 681                      26 ms
first-zstd-line read : 681 parsed, 40.6 MB read  2723 ms
stat per artifact    : 681                      3127 ms
TOTAL                : 5900 ms
```

`listArtifacts()` walks **every session directory on every call**; "the cost is **linear in the
number of stored sessions** and there is no paging parameter to lean on."

**AFTER the fix** — "Measured through the proxy: **25,371 ms → 29 / 29 / 92 ms (n=3)** with `rpcId`
re-labelled correctly each time, **685 rows, 1,472,207 bytes**." `[DOC-M]` §2.

**[DUP] — and my own live reading does not confirm the warm figure is being achieved now.** `[LIVE]`
`GET http://127.0.0.1:3200/__dshw/stats` → `"filled":23,"cold":1,"prewarm":20,"cached":true,"ageMs":30822,"rows":694`.
`[LIVE]` `origins.log` tail shows a **fresh proxy** at `03:25:10Z` and:
```
[03:25:22.937Z] cache filled rows=685
[03:25:54.511Z] cache refresh ok rows=685 in 12412 ms
[03:43:16.065Z] cache refresh ok rows=686 in 3482 ms
[03:45:07.296Z] cache refresh ok rows=694 in 20064 ms
```
So the background stale-while-revalidate refresh is currently taking **3.5 s to 20 s**, not 29 ms —
those are refresh times, not caller waits, but they are the only walk times available on this
machine tonight. No first-party 29 ms measurement exists in this session. **NOT VERIFIED.**

Also **[DUP]** on the corpus size, three dates, three different quantities (files vs dirs vs rows):
`372 files / ~370 dirs / 197–202 MB` (2026-09-15, 10-dsh-source-audit.md §2) · `389 files / 214.1 MB`
(2026-09-16, 90-plugin-health-governor.md §2) · `681 session dirs / 6 project dirs / 40.6 MB read`
(2026-09-18, MEMORY-AND-SESSION-LIST.md) · `679 rows` then `685 rows` then `694 rows` in the probes.
Project dirs: **1** (2026-09-15) vs **6** (2026-09-18).

## 2.6 Mesh placements — the window that actually exists

**The brief's "80 minutes of an overloaded machine" is not in the record. NOT VERIFIED, and the
premise appears false.** Four searches found nothing (see §0). What the record does contain:

| fact | value | source |
|---|---|---|
| broker's last placement before the 13:04Z audit | `2026-09-17T04:12:42Z`, `place -> zabz-tech position=0 tier=fits fleet children=6`, released 0.3 s later | `[DOC-M]` 95 §2.1 |
| newest dispatcher record on the laptop at that time | `~/.dsh/mesh/logs/2026-09-17T04-14-39-996Z.jsonl`, written 00:15 local | `[DOC-M]` 95 §0 |
| the gap | "**Nine hours of idle.** The processes are live; the workload is not." | `[DOC-M]` 95 §0/§7(c)(6) |
| placements *the ledger* recorded, all day | "recorded **no placement all day**, because the model in each window chose `subagent_local` (or worked itself), and neither of those paths measures anything" | `[DOC-M]` 109 §1 |
| what I found in the ledger `[LIVE]` | **6 files**, 2026-09-17 14:36:01Z → 14:53:52Z UTC: **5 settled `stopReason:"error"`** (exit 127 ×2, exit 1 ×3, three of them with `"reportedHost":""` i.e. not even the node's name) and **1 settled `completed`** (`meshHost":"zabz-tech-linux"`, `"invocationForm":"executor"`, exit 0, 11,757 ms) | `[LIVE]` `~/.dsh/mesh/placements/*.json` |
| `[LIVE]` and every one of those six | `"leaseReleaseSkipped": "no lease: this provider is on a fixed target"` | `[LIVE]` same files |
| broker-driven fan-out measured, 13:17–13:24Z | 2 children → `zabz-tech`×2 (1,985 ms); **8 children → `zabz-tech`×8, scores 18,17,16,15,14,13,12,11**, `{"placed":8,"queued":0,"released":8,"placementFailed":0}`; `--hold 6 --children 2` → both to `zabz-tech` at 12 and 11 | `[DOC-M]` 92 §5.1–§5.4 |
| the reason 8/8 landed on one node | the laptop read `ok, slow, ok` on three consecutive fresh reads, and the shipped code **removed** a `slow` node from the pool entirely | `[DOC-M]` 92 §5.3, 98 §2.1 |

**The honest answer to "how many placements in 80 minutes": the ledger has a 18-minute window with
6 placement records, 5 of which failed, and a 9-hour window with zero.** Neither is the number the
brief describes.

## 2.7 What the broker does and does not see

**Sees** `[DOC-M]` 76 §4/§10, 95 §1.1: each node's `/mesh/capacity` — `node`, `fqdn`, `cpu.logical`,
`cpu.physical`, `cpu.load1`, `mem.totalMiB`, `mem.freeMiB`, `mem.swapUsedPct`, `disk.freeGiB`,
`agents`, `governor`, `accepts`. Plus its own lease table in memory, TTL 900 s. Freshness ≤ 15 s
(`cacheTtlMs 15000`), read timeout 1,500 ms `[LIVE]` nodes.json.

**Does not see (each is a measured finding, not an inference):**

| blind spot | the measurement |
|---|---|
| **commit charge** | not in the contract at all; 109 §1 shows the laptop advertising 12 free slots at 120–126 % of physical committed |
| **`agents.loopsRunning` is blind to dispatched work** | "in **every one of the 83 samples** … the target's `/healthz` reported `sessions.agentLoopsRunning: 0` and `sessionsLive: 1`" while 8 real turns consumed 3.0 GiB and 41.5 % of all 32 logical CPUs. A `--profile headless` child is a separate process; it never registers in the resident engine's session store and takes no governor lease. `[DOC-M]` 84 §5.2 |
| **…and even where it is non-zero, nothing consumes it** | "`loopsRunning` appears in the broker exactly twice: `broker.js:407` and `broker.js:698` … and **nowhere in `scoring.js`**. So a node running 8 loops and one running 0 score identically: the number is *reported*, never *consumed*." `[DOC-M]` 95 §5.4 |
| **the Mac Mini at all** | present in `nodes.json` only as `"_excluded_on_purpose"`; `GET /nodes?fresh=1` lists **4 of 5**. The exclusion's own stated condition ("add it the day its gate answers") **has been met** — `[DOC-M]` 95 §2.2 measured a 200 with a usable document |
| **`accepts.maxChildren` is a literal** | `MESH_MAX_CHILDREN = 12` (`phone-gate.py:939`), identical on all five nodes including the 4-core authority. "**A documentation example became a published per-node limit**", and the broker consumes it. `[DOC-M]` 95 §1.4 |
| **`governor.budgetSlots` is a constant** | **24 on all five nodes** `[DOC-M]` 95 §1.1/§1.4 |
| **`[LIVE]` whether it is even being asked** | every placement ledger on this machine reads `"no lease: this provider is on a fixed target"` — the route that uses the broker was not the route in use |

## 2.8 Transport concurrency per node

**v2 (HTTP) ceiling, derived** `[DOC-M]` 93 §2.1 —
`limit = max(1, min(cpu, mem, declared, hard))`:

```
cpu      = floor(logicalCpus × 0.42 / 1.68)
mem      = floor((availableMiB − reserveMiB) / 403)
declared = the node's own accepts.maxChildren  (else absent)
hard     = 24   (the governor's ceiling)
```

| node | logical | total MiB | available MiB | cpu | mem | declared | **limit** | binding |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `zabz-tech` | 32 | 65,173 | 52,976 | 8 | 112 | 12 | **8** | cpu |
| `zabz-yoga-1` | 22 | 32,373 | 12,701 | 5 | 21 | 12 | **5** | cpu |
| `secratary` | 4 | 23,422 | 5,168 | 1 | 5 | — | **1** | cpu |
| `zabz-tech-linux` | 12 | 11,673 | 4,675 | 3 | 6 | — | **3** | cpu |
| `lakewooechsmini` | 10 | 16,384 | **236** | 2 | **1** | — | **1** | **mem** |

Inputs measured 2026-09-17 13:32–13:56Z. **`zabz-tech-linux` and `secratary` limits are arithmetic,
not measurement** — both answer 404 on `/mesh/health` `[DOC-M]` 93 §10.4. **The Mac's limit is the
only one where the memory term decides.**

**v2 measured at the ceiling on `zabz-tech`, 13:53:04–13:53:33Z** `[DOC-M]` 93 §5.1:
`requested 12 · answered 12 · reportedCorrectHost 12 · refused 0 · admittedImmediately 8 · queued 4 ·
maxQueuePosition 4 · wallMs min/mean/max 10,951 / 15,254 / 20,992 · level wall 21,222 ms`. Two
independent counts agree: the target's process list peaked at **8** `--profile headless` and never 9;
the node's own counter read **`maxInFlightSeen = 8`**, `started=25 completed=25 failed=0 queued=8
queuePeak=4 maxQueueWaitMsSeen=10575`. Verbatim node log:
```
RUN   … inFlight=8/8 queued=0 queuePosition=0 queueWaitedMs=0
QUEUE local-eyj414fj position=1 limit=8 queueDepth=1 inFlight=8
DEQUEUE local-eyj414fj position=1 waitedMs=1800  limit=8
DEQUEUE local-4ryscpe9 position=1 waitedMs=10486 limit=8
```
At 8 concurrent: "pagefile **0 %** in every sample, disk queue **0**, engine loop-lag maximum
**unchanged at 17 ms**", commit peak 17,090 MiB from a 14,153 MiB baseline.

**v1 (ssh) ceiling: there is none in the transport, and the real one is probabilistic**
`[DOC-M]` 93 §5.4: twelve simultaneous ssh sessions all completed (`exitCodes = 0×12`,
`wallSeconds = 15`, every session saw ~30 sibling PowerShell processes). And on the target:
```
#MaxStartups 10:30:100
#MaxSessions 10
#MaxAuthTries 6
```
"**all three commented out** — so sshd's compiled defaults are in force: `MaxStartups 10:30:100`
begins dropping *unauthenticated* connections at random from the 11th (30 % probability, rising to
100 % at the 100th) … **the margin is one connection** and nothing in transport v1 knows the limit
exists … a probabilistic failure mode that produces a **255** exit and **no diagnostic**."

**The transports were never compared at the same N with the same work** `[DOC-M]` 93 §10.1.
**NOT VERIFIED.**

**One env var moves the v2 limit, measured** `[DOC-M]` 93 §2.2: `MESH_HTTP_CPU_PER_TURN=0.62` (the
resident figure) → `zabz-tech = min(21, 112, 12, 24) = 12`, `declared` binds.

**The broker's own concurrency numbers are different and both are given** `[DOC-M]` 92 §5.1 (13:17:42Z):
`zabz-tech slots=18 ... coreSlots=18(physical)`, `zabz-yoga-1 slots=12 ... coreSlots=12(physical)`,
`zabz-tech-linux slots=4`, `secratary slots=3 free=3 swap=81.2% transport=null`. **`[DUP]`** with 93's
**8 / 5 / 3 / 1**. Summary in §4.2.

## 2.9 Spend rate at high concurrency

**The scaling law the whole money story rests on, and its corollary for the redesign:**
`[DOC-M]` 60 §1.2 — "**Cost is linear in `requests × mean context`**, and that product is the only
thing worth managing." `[DOC-M]` PROGRAM.md line 48 — "cost scales as ***steps × mean context*** — the
three priciest sessions were **52.5 % of the $54.92 day**". `[DOC-M]` 60 §1.3 — "**13.7 billion
tokens of cached context re-read.** This is not a malfunction — it is the arithmetic of *steps ×
context*". `[DUP]` the 52.5 % is contradicted: `[DOC-M]` docs/mesh/65-spend-guard.md §2.4 measures the
same three sessions at **47.6 %** ($5.56 of $11.68) and adds the finding the percentage was used to
reach — "**a single session cannot run away.** The largest session ever measured here costs **$2.88**
(09-14) and **$2.56** (09-15). **09-15 had 79 sessions, 09-14 had 152.**" See §4.2 B10.

| quantity | value | source |
|---|---|---|
| 55 agents generating continuously | **$68/hour off-peak**, **$136/hour peak**, **$408** per 6 h, **$544** per 8 h | `[DOC-R]` docs/mesh/96-gateway-at-scale.md §4 |
| the same, as a duty-cycled lower bound | **≈$27/hour** at 40 % duty | `[DOC-M]` 96 §4.1 |
| one hour of 55 vs the worst recorded day | **1.24× off-peak / 2.5× peak** (worst day **$54.92**) | `[DOC-R]` 96 §4 |
| the fleet's own heaviest sustained day | **$0.87/hour** | `[DOC-M]` 96 §4.1 |
| provider ceiling vs the plan | `deepseek-flash` account concurrency limit **2500**; fleet's measured peak **≈16–22 simultaneous requests** → the plan cannot reach it "by a factor of **~45**" | `[DOC-M]` 96 §1.4, §0 |
| **what actually binds, in the record's own words** | "The ceiling is **not the provider's capacity and not the laptop's memory. It is the wallet, and it has no ceiling at all**" | `[DOC-M]` 96 headline |
| measured concurrency the fleet has ever reached | **never exceeded ~12 model requests started in any one second**; mean **≈0.16 req/s** on its heaviest days = "about **0.7 agents' worth** of continuous generation, not 55" | `[DOC-M]` 96 §2.4 |
| cost of the ramp itself | **$0.01745** across 128 requests; **zero errors, zero 429s** | `[DOC-M]` 96 §2.2/§2.3 |
| guard thresholds installed | warn **$35** · stop new fan-out **$80** · refuse a billable step **$150** · **12 generating agents per machine** | `[LIVE]` `day.json.limitsUsd` = `{warn:35, fanout:80, ceiling:150, concurrencyCap:12}`, matching `packages/plugin-cost/cordis.patch.yml` |
| where those numbers came from | warn: above the median day ($4–7) and above every legitimate single-machine day on record (**$35.39**, 09-14) · fanout: **≈70 minutes** of a 55-agent fleet · ceiling: **2.7×** the worst day ever recorded, where the old $50 was **44 minutes** of that fleet | `[DOC-R]` docs/mesh/101-spend-guard-installed.md §2 |
| `[LIVE]` spend so far today | `micro 8,318,426` = **$8.32**, `requests 2949`, `unpriced 0`, `lastVerdict "ok"`, `generatingAtLastDecision 12`, `writtenAt 2026-09-18T03:45:28.872Z` | `[LIVE]` `~/.dsh/spend-guard/day.json` |
| the guard's own blind spot | "On 2026-09-15, **56.5 % of the day came from ZABZ-TECH** and this machine's logs saw none of it. Until the layer-2 roll-up posts per-host totals into the authority … **the fleet has no ceiling; each host has one.**" | `[DOC-M]` 101 §8.1 |
| per-turn cost, **two figures** | **$0.0042/turn** (96, from a measured **$0.001523/request** × 2.73 requests/turn at a 196,945-token mean prompt and 98.5 % cache hit) **vs ~$0.007/turn** (84's estimate) | `[DOC-M]` 96 §4.1 — 96 explains the gap: 84's rig was a synthetic `headless` turn, the logged mean is the real fleet carrying full history |
| the account ledger | 30-day total **$195.74**; median day **$4–7**; the two spike days **$44.88 (09-14) and $54.92 (09-15) = $99.80 = 51 % of the entire month**, consecutive. 09-15 = **$54.738153411** of flash + **$0.183484268** of v4-pro | `[DOC-M]` docs/dsh-at-scale/60-cost-audit.md §0 |
| `$/req` over six working days | **0.0015 → 0.0020, flat**: "Nothing degraded. There is no leak, no runaway session, no bad model, no pricing change." | `[DOC-M]` 60 §1.2 |
| where the money goes | DSH pool: cache-hit input **42.1 %**, output **33.5 %**, cache-miss input **24.4 %** | `[DOC-M]` 60 §1.3 |
| **`[DUP]` "82 % of spend re-reading context"** | `PROGRAM.md:119` says 82 %; 60 §1.3 and 96 §8 both say **42 %**; the nearest "82" in 60 is a *different* quantity — "tool output is **82.5 %** … of prompt tokens" | §4.3 |
| tool output is the largest prompt driver | "**82.5 %, 86.9 % and 95.8 % of prompt tokens in three long sessions**"; largest single result **42,974 chars**; the pruner suppresses only **23 %** of tool bytes | `[DOC-M]` 60 §6.2 |
| MCP schema cost | 6 servers, **95 MCP tools** + 27 builtin = **122 tools**, serialized **117,176 chars ≈ 29,294 tokens**; MCP is 74.9 % of it, `firecrawl` alone 39,770 chars → "**~880 million tokens** of pure schema over 30,000 requests", **$2.6–5.3 per 30 days** | `[DOC-M]` 60 §6.4 |

## 2.10 Tool-call latency — the one number that justifies the whole tool policy

`[DOC-M]` docs/dsh-at-scale/70-toolcall-latency.md, measured ZABZ-YOGA 2026-09-16 14:20–14:45 UTC,
**n=30 each, interleaved**:

| case | min | p10 | p50 | p90 |
|---|---:|---:|---:|---:|
| `cmd.exe /d /c exit 0` | 32.8 | 33.5 | **35.9** | 44.4 |
| `runner.js` spawned and let exit | 120.3 | 127.8 | **136.3** | 148.6 |
| `node -e 0` | 69.8 | 73.5 | **76.6** | 85.3 |
| `pwsh … -Command "<ENC>; exit 0"` | 405.0 | 414.1 | **548.0** | 631.5 |
| `pwsh … "<ENC>; Get-Date\|Out-Null"` | 516.6 | 557.4 | 627.6 | 819.1 |
| `pwsh … "<ENC>; Write-Output hi"` | 539.1 | 560.6 | 646.6 | 996.4 |

**Decomposition of one trivial `pwsh` tool call** `[DOC-M]` §2.2: `probeWindowsJob` **<1 ms** ·
spawn `runner.js` **≈136 ms** · `CreateProcessW` **≈7 ms** · `pwsh.exe` start + encoding preamble
**≈550 ms** · collector+spill+canonicalisation **≈10 ms** · exit detection **0–10 ms** →
**≈700 ms typical / ≈540 ms best, with pwsh 78 %, runner 19 %, everything else <3 %.**

**The in-process tools are not in that league** `[DOC-M]` §5/§6.3, instrument `fslat.mjs` **n=200**:
`stat` p50 **0.11 ms**, `readFile` of a 60 KB YAML p50 **0.76 ms** — "**4,000× under the pwsh floor**",
"a **700× saving** on every call it applies to."

`[LIVE]` corroboration of the shape, not the constants: `~/.dsh/health/processes.json` reports
`totals.processes 394`, `threads 6049`, `handles 175226`; the engine's own `[LIVE]` `/healthz` read
via `engine_health` (delegated, 03:45:24Z) reported `tool-call runners 5 (321 MiB)` and
`loop lag p50=4ms p95=171ms max=1412ms (512 samples @ 250 ms)` — a **1,412 ms worst-case stall** on
a machine with 13 agent loops running, against the 54 ms max measured on an idle desktop node.

**The counter caveat that matters** `[DOC-M]` 84 §4.1: `loop.maxMs` is "a rolling maximum over a
**512-sample window at 250 ms — about 128 seconds**". It has a long memory: the 54 ms reading was
still shown two samples after the fleet stopped. It is not an instantaneous signal.

`[DOC-M]` `[DUP]`: §5 line 271 states pwsh start as "**340–406 ms best observed**", but no measured
row anywhere shows 340 — the minima are **377.3 ms** and **405.0 ms**, and §7.1 separately cites an
external **386.3 ms**. The 340 appears once and is unsupported by the tables.

## 2.11 Where the metrics come from, and the machine's own history

`[LIVE]` `~/.dsh/metrics/harness-metrics.csv`: header
`ts,commit_gb,avail_mb,pages_in_s,faults_s,disk_q,cpu_pct,procs,node,msedge,pwsh,conhost,cim_ok,mcp,engines,top1,top2,top3`,
**5,298 rows**, first row `2026-09-16T12:56:55,32.28,7862,3161,51700,0.68,75,483,29,129,12,14,1,0,0,,,`
and last `2026-09-17T23:47:12,25.27,11680,190,97632,0.46,54,380,13,55,9,16,,,,`.
`[LIVE]` `~/.dsh/metrics/sessions-activity.csv` exists (163,422 B) with a header-less
`ts,sessions,X,Y` shape.

**This is the file every longitudinal conclusion in the record rests on**, and `[DOC-M]` 84 §3.1 says
its own re-fit of it (1,478 rows, r = 0.8545, intercept 16.33 GB, residSd 2.16 GB) **did not
reproduce** the 0.575 GB/process figure that an earlier reading of the same file produced over 477
rows. **The same file, three readings, three slopes** (§4.2 C6).

## 2.12 The journal's id-collision history

**Three events, in order.**

**(1) 2026-09-14 — 161 collided ids.** `[DOC-M]` 30-locks-audit.md §1.2/§1.3: cause is the lock's
*break* path. Both processes can read the same stale `held`, both decide stale, A unlinks and
creates, then **B unlinks A's live lock** — "`unlink` compares nothing" — and both enter. "Result:
**two writers, one tree.**" The correct compare-and-swap exists in `release_lock` only, "which is
precisely why the failure is silent". Fixed to a real OS lock with an inode check; **verified: 3
writers, zero overlap; a force-killed holder released in 0.00 s** `[DOC-M]` PROGRAM.md line 38.

**(2) 2026-09-17 — 18 contested ids, `check` reporting 0 errors throughout.**
`[DOC-M]` 107-journal-convergence.md §1: **10 live** against `origin/master`
(`D254, H464, H465, H466, L1906, L1907, L1908, L1909, P242, P244`) and **8 latent** against the other
machine's unpushed set (`D252, D253, H467, H468, L1910, L1911, L1912, P246`) — "**18, every pair two
genuinely different entries.**" Renumbered to `D256–D258, H480–H484, L1920–L1926, P249–P251`;
"verified **18 of 18**, archived **8**, failures **1** (H467, heading title text; bodies
byte-identical)". The no-loss gate reads **1728 = |L ∪ O| = 1728, delta 0**.

**Why they collide, measured:** "Both machines minted from the same base … `next-id` reads the local
index and local refs, so it is collision-proof only after a successful push — offline or merely
unpushed, two machines pick the same number with confidence." `[DOC-M]` 107 §2.

**The tool that should have caught it:** `[DOC-M]` journal/reference/id-collision-20260917.md §3 —
`check` "validates `entries/` **within one tree**" and ran **0 errors** before and after every step;
`repair-ids` "has no verb for it" (and, measured on a synthetic tree, **left the offending file
behind**, so the invariant it is named for did not hold until a 2026-09-17 fix); `idguard.py` reported
**9 collisions while a content comparison found 10** because "the gate is only as fresh as a
generated file a writer has to remember to rebuild" (`D254` was committed without regenerating
`journal/index/entries.tsv`).

**(3) The allocator incident — one `append` that deleted the journal.** `[DOC-M]` 108 §5.1:
```
79efb088c78ff5a14541227a2418f44ff884e473   journal(alloc): ZABZ-YOGA reserves lessons<=1990
parent: 53cf517c61ce83f1426e096458e9e5d338cf8770 (the correct, converged tip)
diff against that parent: 2425 files changed, 1176 remaining -> 1249 PATHS DELETED
journal/entries/**/*.md in the committed tree: 0   (all 1728 journal entries gone)
exit code: 0
```
"The parent **commit** was resolved from the just-fetched remote tip (correct). The parent **tree**
was resolved from the mutable local name `refs/remotes/origin/master`, which in that worktree was
`622876e` — **13 commits behind**." Restored via `--force-with-lease` (the one authorised rewind);
`journal/entries/**/*.md` on the restored tip = **1728**; `journal.py check` → 0 errors.

**The rule 108 draws from it, which is a general lesson and not a journal one:** "prefer an
**immutable identifier** — a commit hash, a blob id, a sha256 — over a mutable name, and when the two
must be mixed, resolve the whole unit from the same reading." `[DOC-M]` 108 §5.3, which lists it as
the fifth of a class that also includes *"`--dump-config` returning 0 locally and 1 over ssh"*.

**Current state** `[LIVE]`: I could not read `journal/alloc/bands.tsv` contents (the directory exists;
I did not enumerate it). `[LIVE]` `journal.py check` at 23:47 local reported
`cache is stale and locked by another session — answering from entries/`, then warnings, then exit 0.
`[DOC-M]` 108 §9: the live journal on this laptop **had no published reservation of its own** from
that change, while a reservation for `ZABZ-YOGA` covering lessons up to `L1990` *was* published on
`origin/master` by the inline-push version during the incident.

## 2.13 Gate, mesh identity, and node facts at audit time

`[DOC-M]` 95 §1.1, five capacity documents read 2026-09-17 13:04:51–56Z over the tailnet:

| node | logical/physical | total MiB | free MiB | swap % | agents | v1 dispatch | engine pid |
|---|---|---:|---:|---:|---|---|---|
| `zabz-yoga-1` | 22 / 16 | 32,373 | 17,253 | 0.0 | loops 7, live 12 | true | 4880 (08:51:07) |
| `zabz-tech` | 32 / 24 | 65,173 | 53,827 | 0.0 | loops 0, live 0 | true | 26140 → 24556 |
| `zabz-tech-linux` | 12 / 6 | 11,673 | 10,160 | 15.2 | **null** | **false from 14:00Z** | 3572114 (up 49,454 s) |
| `secratary` | 4 / 4 | 23,422 | 15,718 | **81.2** | **null** | **null** | 2147621 (up 23,761 s) |
| `lakewooechsmini` | 10 / 10 | 16,384 | 7,067 | 57.8 | **null** | not in roster | 12458 (up 308,320 s = 3.6 days) |

`[DOC-M]` 95 §1.2: `mesh-e2e.ps1` S1 **PASS 5/5** at 13:11–13:12Z against a direct OS read, deltas
24 / 197 / 1 / 1 / 7 MiB against tolerances 324 / 652 / 256 / 256 / 256, totals exact.
`[DOC-M]` 95 §1.3: `node == fqdn` first label holds on all five.

`[DOC-M]` 95 §4.2: the device allow-list control **existed on 4 of 5 gated nodes**; on
`zabz-tech-linux` there was no allow-list file, so a **foreign device got 200 and a signed-in
session**. Fixed in 97 §2 (the employee's Mac now gets **403**, all five owner paths still **200**).

`[LIVE]` right now: `zabz-yoga` and `zabz-yoga-1` **both resolve on this machine**
(`Resolve-DnsName zabz-yoga` → `192.168.12.104`, `100.72.162.5`, plus AAAA;
`zabz-yoga-1` → CNAME → `100.72.162.5`), and the hosts file carries
`100.72.162.5 zabz-yoga-1.tail93e6e6.ts.net. zabz-yoga-1`. `[LIVE]` `COMPUTERNAME = ZABZ-YOGA`,
`hostname = zabz-yoga`, `DNS hostname = zabz-yoga`; `[LIVE]` `tailscale status --self` →
`100.72.162.5 zabz-yoga-1`. So **the published-node-name defect is narrower than "only
`zabz-yoga-1` resolves"**: on this laptop the legacy name resolves too, while on the mesh the DNS
label that resolves everywhere — and the one `tailscale serve` publishes — is `zabz-yoga-1`. See §4.4.

## 2.14 The governor's budget arithmetic

`[DOC-M]` 90-plugin-health-governor.md §3: `(free physical − reserve) / measured slot cost`, capped
**24**, floored **4**; reserve `max(2 GiB, 12%)`; slot cost **160 MiB**, "which is the measured cost
of one heavy tool call (**runner 57.3 MB + shell 102.7 MB**)".

Printed derivation: `15943 MiB free - 3885 MiB reserved = 12059 MiB usable / 160 MiB per slot = 75
slot(s), capped at maxSlots=24`. `[LIVE]` the same structure on my `/mesh/capacity` read right now:
`"governor":{"budgetSlots":24,"inUse":0,"queued":0}`, and `/mesh/health` →
`governor  0 of 24 heavy slot(s) leased, 24 free, 0 waiting`.

Cross-process proof `[DOC-M]` 90 §3: `node test/governor-stress.mjs --contenders 30 --slots 5` →
"**30 concurrent acquires finished in 549 ms**", all **15 checks pass**, "exactly 5 were granted",
"the rest (25) were queued", "same lease reaped by exactly one reaper". Never refuses: `QUEUED
position N`, exit **10**; exit codes `0 granted, 10 queued, 1 error`.

## 2.15 `--dump-config` as an instrument — four verdicts, and they conflict

| verdict | source | text |
|---|---|---|
| **cheapest real gate** | `[DOC-M]` docs/mesh/90-provider-mount.md §8 item 1 | "It composes the profile's bundle layers, starts nothing, evaluates no `!!js`, and is therefore safe on a machine that is in use. **A live engine says nothing about whether the next one will come up.**" |
| **exit 0 is not proof a bundle resolves** | `[DOC-M]` docs/mesh/105-placement-committed.md §8 item 5 | "it exits 0 with 620 lines while the same profile's provider bundle is unreadable and a *different* copy of the plugin answers. **The composition and the resolution can disagree.**" |
| **it depends on who runs it** | `[DOC-M]` docs/mesh/106-desktop-last-mile.md §8 | same bytes, same minute: `exit=1 lines=16` (ssh-spawned) vs `exit=0 lines=620` (local Interactive). "**a profile check is only evidence for the logon class that ran it** … Run `--dump-config` as each, or the check is a rubber stamp." This **corrects 105's reason while keeping its conclusion** (`[DOC-M]` 106 §8 lines 469–477). |
| **exit 1 IS deterministic** | `[DOC-M]` 97 §1.5 | argued for the Mac case — true of `exit 1`, and not a claim that `exit 0` proves a working profile |
| **and it does not cover the cold boot** | `[DOC-M]` incidents/2026-09-17/README.md lines 105–107 | "H461 did its diligence: 66 unit checks, `verify.mjs` green, `--dump-config` composed the row." The engine still died at the next cold boot. |

## 2.16 The engine's memory over its life — **[DUP]**

| reading | value | source | date |
|---|---|---|---|
| engine RSS, isolated engine, 1 min uptime | **199.2 MiB** (heap 45/47.7 MiB, external 82.3 MiB) | `[DOC-M]` 90-plugin-health-governor.md line 81 | 2026-09-16T15:14:09Z |
| engine, one process of a 14-node / 1,508 MB total | **612 MB** | `[DOC-M]` 70-toolcall-latency.md line 93 | 2026-09-16 |
| `dshw status` after the boot-failure recovery | **~301 MB RSS** | `[DOC-M]` incidents/2026-09-17/README.md line 129 | 2026-09-17 21:39 |
| engine pid 21124 | **3,173 MB** | `[DOC-M]` 10-dsh-source-audit.md §1/§6 | 2026-09-15 22:45 |
| `[LIVE]` engine pid 4416, up 2h08m | **RSS 1,550.4 MB**, Private 1,898.8 MB, 13 threads | `[LIVE]` `Get-Process -Id 4416` | 2026-09-17 23:47 |
| delegated same-session read of the same process | `rss=1590.6 MiB heap=1330.8/1474.3 MiB external=136 MiB` | `[LIVE]` `engine_health`, 03:45:24Z | same |
| and the delta over one minute at start | incident's start-of-life reading vs my 2-hour reading differ by **5×** on the same pid | — | — |

**This is the number the redesign most needs and the record most lacks:** there is no
life-over-life RSS curve for one engine, only point readings spanning **199 MB → 3,173 MB**, and the
2-hour point on the engine that is running right now is **1.55 GB**.

## 2.17 The 0.58 / 0.465 / 0.575 disagreement — one file, three slopes

`[DUP]` `[DOC-M]` 84 §3.1 row 3: `60-verification.md` §2.2's **0.5754 GB/process over 477 rows
(r = 0.937)** "does not reproduce" when the same `harness-metrics.csv` is re-fit at **1,478 rows**
(0.465 GB, r = 0.8545, intercept 16.33 GB, residSd 2.16 GB). And **the same document cites the same
source as both 0.58 GB and 0.575 GB** and gives two different multiples for it in one section —
"too high by **1.5×**" in the headline (process-vs-turn) and "too high by **2.7×**" in the table
(process-vs-process). Both are quoted.

`[DOC-M]` 84 §5.4 adds the *unit* problem that makes all three unusable: at 8 live turns the
`node.exe` count inside a single level ranged **19 … 27, non-monotonically**. "**Use a turn count or
use nothing.**"

## 2.18 Where the load actually sat on this laptop, 2026-09-14 `[DOC-M]`

From `docs/multi-window/PERFORMANCE-MEASURED.md` (second half), measured with 10 windows:

| consumer | processes | private | sustained CPU |
|---|---:|---:|---:|
| Edge windows (10–11 instances) | 90 | 7,729 MB | **6.7 cores of 22** |
| engine tree (node + MCP bridges + Playwright's Chrome) | 37–42 | 2,651–2,988 MB | 0.66 core |
| `personal-secretary` uvicorn (+ `next dev`) | 4 | 2,526 MB | 0.22 core |
| other node (MCP bridges) | 20 | 3,005 MB incl. engine | 0.48 core |
| `TextInputHost` | 1 | **1,195 MB** (abnormal) | — |

"**The per-window cost is a function of whether that window's agent is generating, not of the window
count**": generating **1.0–1.1 of one core, ~750 MB private**; quiet **0.24–0.28 of one core,
467–783 MB private**. And the binding resource: "**committed 28.6–28.8 GB of 31.61 GB physical →
2.8–3.3 GB of headroom**", free RAM draining **~370 MB/min** while ten agents ran; "the **tripwire**:
if commit crosses 31.61 GB the machine starts paging to an 11.5 GB pagefile."

Two structural facts from the same measurement: **there is no global session-concurrency cap in DSH**
(`maxParallelToolCalls` is **per session** — default 10, this machine sets **20** `[LIVE]`
`~/.dsh/settings.yaml`), and **more windows are open than `windows.json` enables** because
`Invoke-New` force-enables every slot before picking a free one. `[DUP]` on the slot count: **8
enabled** (2026-09-14) · **16 slots** (`[LIVE]` windows.json) · **24 origins** (`[LIVE]` windows.json
`origins.count` and the proxy's 24 live listeners) · **maxWindows: 24**.

## 2.19 The lock and serialization measurements

`[DOC-M]` 30-locks-audit.md, ZABZ-YOGA 2026-09-15 22:16–22:52 EDT, judged **under load**:

| operation | measured |
|---|---|
| `status` | 3.1 s (stale cache, locked) / 4.25 s (fresh) |
| `list --kind lessons --limit 3` | 1.66 s |
| `newest handoff 1` | 1.78 s |
| `doctor` | 3.65 s / 6.31 s |
| `costs` | 14.62 s |
| `next-id lessons --no-fetch` | **11.42 s** under active append load |
| `check` | **42 s** fresh cache; **>120 s → killed by the harness** |
| **real append lock hold time** | **41 s, 41 s, ≥89 s, ≥98 s** |

"The journal's critical section is **40–100 s under normal fleet load**, not 'well under a second'
as `journal.py:2467` assumes, and `LOCK_WAIT_SEC = 240` (`journal.py:142`) is larger than the
harness's 120 s foreground kill."

**A read can take the write lock across a network round trip:** `status` → `_maybe_refresh_questions`
→ spawns `journal.py questions` (a MUTATING command) → `subprocess.run(["ssh", … , "secratary-ts",
"python3 ~/bin/owner-queue.py list --all --json"], …, timeout=45)` — "**the journal write lock is
held across a network round trip to another machine, up to 45 s, triggered by a read.**"
`[DOC-M]` 30-locks-audit.md §1.5.

After the fixes `[DOC-M]` PROGRAM.md lines 25/38/39/40/45: append **10.4 s → 2.2–2.8 s** (12.6 s of a
14.9 s append was a migration scan run before *every* write, plus **15,303 `pathlib.relative_to`
calls at 7.2 s**); the lock is now a real OS lock with an inode check; `status` no longer triggers the
mutating refresh; `owner-queue.py` refuses instead of inventing an empty queue.

**`[LIVE]` today:** `journal.py check` at 23:47 local printed
`journal: cache is stale and locked by another session — answering from entries/` and still exited 0 —
so the "stale/locked, answer anyway" path is the one in use, and it is the path that produced the
`0 error(s)` readings throughout the 18-collision window.

## 2.20 Not verified, listed as refusals

- **The laptop's own turn-cost curve.** `[DOC-M]` 84 §6.1 refused it; the laptop was past the stop
  line before any fleet ran. `0.75 × 16 = 12` is used in production and **was never measured on the
  machine it is used for.**
- **`secratary` and `zabz-tech-linux` under load.** No `/healthz` (plugin-health unmounted; mounting
  it needs the engine restart P210 forbids), so their 93 limits are **arithmetic**.
- **Any matched-pair transport comparison at equal N with the same work.** 93 §10.1.
- **The region above 8 concurrent turns on any node.** 93 §10.3; "**A tool-heavy fleet of 8 on
  `zabz-tech` is not claimed safe.**"
- **The queue under the real 55-child flow.** "The deepest queue measured is **4**." 93 §10.8.
- **Engine warm-up / cold-start duration.** No document states it. The closest is the boot-path call
  costs (§2.4's neighbours: `settings/describe` 144.5 ms, `agentPresets/list` 97.6 ms) and the
  12-window boot burst (1,363 ms wall, 125 ms loop-lag p50, 193 ms max).
- **Whether the elevated cold boot works.** The incident README's open item 2: "An elevated cold
  boot was still not performed."
- **The unexplained window count after `restore`.** Incident README open item 4 — and `[LIVE]` it is
  still true tonight (§1.3).
- **`refuseWhenFull` against a live node.** 93 §10.7.
- **The Mac's memory term.** macOS has no `/proc/meminfo`; `availableMiB` is free physical (236 MiB),
  and whether that is the right substitute is not measured — and it is the only node where the memory
  term decides anything. 93 §10.6.

## 2.21 The spend guard's own live numbers as the money instrument

`[LIVE]` `~/.dsh/spend-guard/day.json` is the only first-party money counter on this machine:
`micro 8,318,426` (= $8.318), `requests 2949`, `unpriced 0`, `watermarkMs 1789703128870`,
`seedRequests 0`, `lastVerdict "ok"`, `lastReason ""`, `lastStep 14`,
`generatingAtLastDecision 12`, `writtenAt 2026-09-18T03:45:28.872Z` — i.e. **written 2.5 minutes
before I read it**, so it is live. Its own limits are the installed policy.

`[DOC-M]` 101 §8.2 names a defect this counter inherits: **two engines on one host share
`~/.dsh/spend-guard/day.json` and overwrite each other's total.** And 101 §8.1: it counts this host
only.

## 2.22 What the metrics sampler is doing while it writes the record

`[LIVE]` the `DSH Metrics Sampler Watchdog` task is **Running** and executing
`pwsh … -File "C:\Users\ezabz\AppData\Local\Temp\harness-config-snap-20260917-233221\scripts\harness-metrics.ps1" -IntervalSeconds 20 -MaxHours 168`
— i.e. **out of a temp snapshot of the repo taken at 23:32:21 tonight**, with
`LastTaskResult 2147946720`. Two earlier snapshot paths appear in the same task's history
(`…-221723`, `…-171703`), and the `.vbs` launcher's `CurrentDirectory` was
`C:\Users\ezabz\AppData\Local\Temp\harness-config-snap-20260917-171703`. So the longitudinal record
in §2.11 is being written by a script that is not the repo's script.

---

# PART 3 — FALSIFIED CLAIMS

**This is the most valuable section.** Each row: the belief, where it was believed, the measurement
that killed it, and the source. Nine were named in the brief plus two more I found while measuring;
I have added four the record supplies.

### 3.1 `0.81 GB` of commit per generating turn — **FALSIFIED, twice**

- **Belief:** "one actively generating agent turn costs ~1 core (**0.81 GB commit** + ~1 core)" —
  `packages/mesh-broker/lib/scoring.js:22–24`, inherited from `docs/dsh-at-scale/PROGRAM.md:75` and
  re-quoted as MEASURED by `10-inventory.md:668` and `40-hardware-costs.md:22`.
- **Where it came from:** a **two-endpoint slope** — "10 running turns → commit 28.7 GB → headroom
  2.9 GB", "(28.7 − 20.65) GB / (10 − 0) turns = **0.81 GB per running turn**"
  `[DOC-M]` docs/dsh-at-scale/80-windows-and-parity.md §6.4. Ten points, two of them used.
- **Killed by, first pass:** `[DOC-M]` docs/mesh/60-verification.md §2.2, 477 rows of
  `~/.dsh/metrics/harness-metrics.csv`: `corr(commit_gb, node_procs) = 0.937`,
  `d(commit_GB)/d(node_procs) = 0.5754`, idle floor **≈17.0–18.4 GB**. "It **does not support 0.81 GB
  per generating turn** — not as a marginal cost (0.575 vs 0.81, **1.4× overstated**) and not as a
  growth rate either." "**Therefore the 0.81 GB figure is not usable, and every downstream number is
  off by the same factor.**"
- **Killed by, second pass:** `[DOC-M]` docs/mesh/84-calibration.md §3.1, 2026-09-17 03:44–03:51Z on
  ZABZ-TECH: **403.3 MiB/turn** (n=63, CI 328.3…478.3; level-mean 402.3, CI 271.5…533.0).
  "**REFUTED — 2.1× too high.** Even the top of my 95 % CI (478 MiB) is 42 % below it."
  *(Arithmetic note: in binary units 0.81 GB = 829.4 MiB = 2.06× 403 MiB; the "2.1×" is stated, not
  derived. Quoted as written.)*
- **And the figure that killed it was itself replaced:** 0.58 GB/process → **0.465 GB** on a re-fit
  of the same CSV (§2.17).
- **Downstream corrections on record:** `40-hardware-costs.md:8` "**did not survive**" and row 3
  corrects "31.6 GB → 29 resident turns" to "**≈12 resident turns**" via
  `(0.75 × 31.61 − 18.0) / 0.58 = 12`; `20-placement.md:702` carries the correction inline;
  `83-http-transport.md:233` marks its own concurrency-1 rule "SUPERSEDED … commit is **403 MiB**/turn,
  not 810"; **`61-buy-list-verified.md:44` still carries it as `[CARRIED]`** — the concept is still
  quoted somewhere as valid.

### 3.2 `agentLoopsRunning` as a way to see dispatched work — **FALSIFIED**

- **Belief:** it is "the real unit of cost — a generation, not a window" (`20-placement.md:534`), and
  `60-verification.md` §6.3 **proposed settling the per-turn constant by regressing commit on it**.
- **Killed by:** `[DOC-M]` 84 §5.2 — "in **every one of the 83 samples** — with 8 real concurrent
  turns, 3.0 GiB of extra commit and 41.5 % of the machine's CPU consumed — the target's `/healthz`
  reported `sessions.agentLoopsRunning: 0` and `sessionsLive: 1`. A `dsh --profile headless` child is
  a **separate process** booting its own profile; it never registers in the resident engine's session
  store, and it takes no `governor` lease either (`governor.inUse` was 0 throughout)."
  "**That would have measured zero, at every load level.**"
- **And even where it is non-zero it decides nothing:** `[DOC-M]` 95 §5.4 — read into the broker at
  `broker.js:407`, printed at `:698`, used by `scoring.js` **nowhere at all**.
- **Still being used as a gate:** `[DOC-M]` `scripts/mesh-restart-when-idle.ps1:802` and
  `mesh-restart-at-0700.ps1:274` both refuse a restart on `agentLoopsRunning === 0` — so a node
  **running 8 dispatched children reports itself idle** to the restart gate. `[LIVE]` tonight's
  refusals are on *resident* loops (`loops=13`) so the gate is deferring for the right reason today,
  but the gate cannot distinguish the two cases.
- **A second, orthogonal defect in the same metric:** `[LIVE]` `~/.dsh/health/list-agents.json` —
  the replacement `list_agents` reports `4 scans, 0 cache hits, 3 deadline(s), last scan 4,952 ms`
  against a **3 s TTL and an 8 s deadline**. Documented expectation was that the TTL would produce
  hits. One reading, small n, stated as an observation.

### 3.3 `swapUsedPct` as swap — **FALSIFIED**

- **Belief:** `SWAP_PENALTY_PCT = 90` (`scoring.js:93`) guards against a swapping node; `nodes.json`'s
  `secratary` note says "Its swap is at 99.9% (measured repeatedly 2026-09-16), which halves its
  effective slots for ranking."
- **Killed by:** `[DOC-M]` 84 §4.4 — the field is
  `max(0, committed − physical) / (commitLimit − physical) × 100`
  (`scripts/phone-gate.py:1110–1149`): "**a commit-headroom metric wearing a swap name**". It reads
  **exactly 0.0** across a 10 GiB spread of commit on both nodes and in **all 83 samples** on
  ZABZ-TECH. To reach 90 % takes commit within **410 MiB (0.6 %)** of the limit on ZABZ-TECH and
  **1,174 MiB (2.7 %)** on ZABZ-YOGA. "It is a **near-OOM alarm wearing a percentage**."
- **The stale prose outlived the code:** `[DOC-M]` 95 §1.2 measured `secratary` live at
  **`swapUsedPct 81.2`** with `scoreTerms.swapApplied = false` — no penalty applied — while the
  `nodes.json` comment still said 99.9 %/halved. "It is a comment, not code, so nothing is
  mis-scored — but it is exactly the kind of stale prose that a later reader trusts instead of
  measuring."
- **The honest oddity, stated not smoothed:** `[DOC-M]` 95 §1.2 — 3,326 MiB of a 4,095 MiB swap file
  is in use, and the six largest `VmSwap` values on live processes sum to about **46 MiB**. "The
  number is real at the kernel level but is not attributable to any process currently resident."
  Whether that swap is reclaimable is **NOT VERIFIED**.

### 3.4 The laptop published as `zabz-yoga` when only `zabz-yoga-1` resolves — **CONFIRMED FALSE, with a live first-party correction to the claim's scope**

- **Belief (measured, 2026-09-16 23:31Z):** "the host name is `zabz-yoga` but the only name that
  resolves is `zabz-yoga-1`" `[DOC-M]` 76 §5 item 2, §10.5 item 2 — and `lib/config.js` now **refuses
  to boot** on a roster row whose name is not the first label of its own fqdn.
- **The defect this leaves live:** `[DOC-M]` 95 §3.3, at 13:13:45Z, `curl -s
  https://zabz-yoga-1.tail93e6e6.ts.net/mesh/health` returned
  `"host":"zabz-yoga","node":"zabz-yoga","nodeSource":"tailscale status --json Self.DNSName","fqdn":""`
  — **the field claims a source that would have produced `zabz-yoga-1`, and the value is the wrong
  name with an empty fqdn.** "The one field a `MESH-HOST:` check will use is the wrong one."
- **Cause, measured:** `[DOC-M]` 93 §8(1) — the engine started at **08:51:07**, `tailscale-ipn`
  started at **08:51:59**, 52 seconds later; the boot read saw `Self.DNSName: ""`, *succeeded*, and
  the memoised value was never re-read. "A fresh process on the same machine, reading the same file,
  returned `zabz-yoga-1.tail93e6e6.ts.net` at 13:06Z." Fixed to retry a degraded read, rate-limited
  to once per 15 s — **taking effect on the affected engine's next restart.**
- **`[LIVE]` — the fix has landed and the defect is gone on the current engine.** `/mesh/health` now
  returns `"host":"zabz-yoga","node":"zabz-yoga-1","fqdn":"zabz-yoga-1.tail93e6e6.ts.net","identityDegraded":false`. `node` is now correct; **`host` still says `zabz-yoga`** — the cosmetic half survives.
- **`[LIVE]` — and the claim's scope is narrower than stated, on this machine.** `Resolve-DnsName
  zabz-yoga` **succeeds here** (`192.168.12.104`, `100.72.162.5`, plus link-local and Tailscale
  IPv6), `Test-Connection zabz-yoga` answers, `hostname` returns `zabz-yoga`, and the hosts file
  carries both names. So "does not resolve at all" is true **from the mesh** (DNS label ≠ NetBIOS
  name) and false **locally**. The direction of the repair is unchanged; the statement needs the
  qualifier.

### 3.5 "The engine needs a restart to change a preset" — **FALSIFIED for a preset, TRUE for a bundle**

- **Belief, still asserted one day before the refutation:** `[DOC-M]` docs/dsh-at-scale/70-toolcall-latency.md:360,
  2026-09-16 — "An engine restart is required either way — the preset decides the tool catalog at
  session start (journal P11 documents exactly this trap)." The lineage is journal `P11`
  (2026-09-11): "The preset default is chosen at session start, so changes need a restart."
- **Killed by:** `[DOC-M]` docs/mesh/94-routing-default.md §6, 2026-09-17, "Does the owner need to
  restart the engine? **No.**" — from the loader's own source:
  discovery is unmemoised (`list()`/`resolve()` re-read the roots every call, `:1152-1158`); a
  session resolves its preset at **session creation** (`dsh-api-session-controller/lib/types/agent.js:382-391`,
  `dsh-agent-presets/lib/index.js:1499-1506`); and a **changed composition file forces a
  re-composition** — the standing mount is keyed by the file's `mtimeMs` + `size` stamp and
  re-created when it differs (`ensureStanding` `:1767-1776`, `compositionStamp`/`sameStamp`
  `:1806-1820`). "The change is therefore **live now for new sessions** and required no restart —
  which is also why `pid 4880` was never touched."
- **The honest limit recorded there:** `ensureStanding` is single-flight per preset id, and a child
  agent binds to its **parent's** standing composition rather than re-resolving (`:1507-1521`) — so a
  child created by an *old* session inherits the old tool set.
- **The other half, which is still true and was measured independently:**
  `[DOC-M]` 90-plugin-health-governor.md §4 — "**A new bundle does NOT hot-mount — measured, not
  assumed.** On an isolated engine with the plugin absent: `GET /healthz` → 404. Then the bundle name
  was added to the running profile's `package.json` and the package junctioned, and after 8 s:
  `GET /healthz` → **404 still** … `patchReload: live` covers the profile's own `cordis.patch.yml`,
  **not the bundle list**."
- **So the belief is not one belief but three, and only the middle one is false:**
  1. a **preset row** re-composes for **new sessions**, no restart — *false belief, corrected*;
  2. a **new bundle/plugin package** is read at boot — *restart required, measured*;
  3. a **host-plane row** of an already-mounted bundle is fixed at engine start —
     `[DOC-M]` 71-mesh-program.md §259–260 / 100-restart-when-idle.md §242–245 list **three** stale
     things: the patch layer, the deployed `zabz` preset, and the running route package.
- **The operational rule this produced, worth keeping:** the safe order is
  **restart first, remove the preset row second** — "Before the restart the shipped row still
  registers the tool (so nothing is lost), and after it the host row's global registration simply
  takes over. Doing it in the other order opens a window in which `list_agents` exists nowhere."
  `[DOC-M]` 90 §305–310.

### 3.6 The desktop "lost its provider on restart" — **REAL SYMPTOM, WRONG CAUSE**

- **Observed:** `[DOC-M]` 97 §5 item 4, 2026-09-17: `zabz-tech`'s engine **restarted at 09:32:02
  local (13:32Z)** and came back with the bundle list
  `@deepseek-ai/dsh-base, @deepseek-ai/dsh-web-app, dsh-plugin-attention, -attention-badge, -cost,
  -mobile, -windows, -health, -mesh-http` — **`dsh-plugin-remote-fanout` absent**. pid `26140` →
  `24556`; `/healthz` 200 → 401 (a fresh process). "Not done by this session … but it is measured,
  and it is the kind of change that should never go unrecorded."
- **First explanation on record (97 §5.4):** the restart returned the node to the **00:33Z repair
  state**, in which bundle rows whose junctions a remote reader could not traverse had been *removed
  by name* — `90-provider-mount.md` §3 records that repair for `dsh-plugin-session-link`: "a junction
  whose TARGET is fine, but reading through it fails: `cmd /c type` answers *'The path cannot be
  traversed because it contains an untrusted mount point'* … name removed
  (`package.json.bak-20260917-003227`)."
- **The cause the measurement actually supports — and it is a different one:**
  `[DOC-M]` 106-desktop-last-mile.md §1/§2/§3, 2026-09-17 15:30–16:00Z, **9/9 measured**:
  "**The discriminator is the reparse point's ACL owner, not the reader's logon class** — and that
  inverts `99` §2.2 and `105` §8 item 7. A junction owned by `BUILTIN\Administrators` is traversable
  by a remote-logon (sshd) process; one owned by `zabz-tech\ezabz` is not. A **local** Interactive
  process traverses **both**." The bare table:
  `dsh-plugin-attention, -attention-badge, -cost, -health, -mesh-http, -mobile, -windows` → owner
  `BUILTIN\Administrators` → `exit 0`;
  `dsh-plugin-remote-fanout`, `-session-link`, `dsh-mesh-broker` → owner `zabz-tech\ezabz` →
  `exit 1 untrusted mount point`.
  Repair: recreate the links **from inside an ssh session** so they are owned by
  `BUILTIN\Administrators`; after it, all three read `owner=BUILTIN\Administrators ssh_type_exit=0`
  and the previously-failing reader went `exit 1 / 16 lines → exit 0 / 620 lines`.
- **98 §1's second defect, same shape, different layer:** `[DOC-M]` "a node whose capacity read missed
  the 1500 ms deadline once and answered on the longer retry received **no work at all** while any
  other node answered quickly — *even when it had more free slots than the winner*." The shipped
  code's `preferred = dispatchable.filter(c => !c.slow)` made `slow` a **disqualification**, not a
  ranking penalty, "the exact opposite of his goal, which is to move work *off* [the laptop]."
  **The contract text was right and the code was wrong** — `76-broker.md` §10.8 and `71` §2.2 both
  already said "ranked below every node that answered first time and **never refused**".

### 3.7 An ssh-created junction being untrusted — **FALSIFIED; the discriminator is the ACL owner**

- **Belief as written:** `[DOC-M]` 99 §2.2 — "the untrusted kind" is created by ssh;
  `[DOC-M]` 105 §8 item 7 built a probe on it ("a task-created junction **IS** traversable on that
  machine, so the repair is scriptable") and got `exit 0, 95 lines`.
- **Killed by:** `[DOC-M]` 106 §3.1, measured on the nine real junctions in one directory:
  "`probe-local` (made by the task itself) | local task | OK, 193 lines | **exit 1 — untrusted mount
  point**" and "`dsh-plugin-remote-fanout` (real) | local task | **OK, 193 lines** | exit 1".
  "**A local Interactive process traverses all six real junctions** — including the two that are
  refused to every remote process. And an ssh-created junction is traversable *by ssh*; a
  locally-created one is not. **So neither 'ssh-created = untrusted' (`99` §2.2) nor 'task-created =
  trusted' (`105` §8 item 7) [holds]**."
- **`[DOC-M]` 106 §9 still records an open discrepancy** with 105's task result — "Recorded as an
  open discrepancy, not as a resolved contradiction." So this falsification is itself not fully
  closed.

### 3.8 `--dump-config` as proof a profile works — **FALSIFIED**

- **Belief:** "`--dump-config` is the **cheapest real gate** in this harness … safe on a machine that
  is in use" `[DOC-M]` 90 §8 item 1.
- **Killed by three measurements:**
  1. **Same bytes, same minute, two readers, two answers** — `[DOC-M]` 106 §8: `exit=1 lines=16`
     (ssh-spawned, 11:31) vs `exit=0 lines=620` (local Interactive, 11:34). "**a profile check is only
     evidence for the logon class that ran it.**"
  2. **Composition ≠ resolution** — `[DOC-M]` 105 §8 item 5: "it exits 0 with 620 lines while the
     same profile's provider bundle is unreadable and a *different* copy of the plugin answers."
  3. **Green dump-config, dead engine** — `[DOC-M]` incidents/2026-09-17/README.md: "66 unit checks,
     `verify.mjs` green, `--dump-config` composed the row" — and the engine `exit 1` at the next cold
     boot, eleven hours later. The cold-boot path under an unset `DSH_HOME` was the gap.
- **And `108` §5.3 files it as one of a class of five failures where a mutable name and an immutable
  id disagreed.**

### 3.9 "The 0.81 GB figure is now falsified" — see §3.1. It is the same row.

### 3.10 **New:** the page-in storm was a *past* state, not a present one — **FALSIFIED**

- **Belief (from the brief, quoted as given):** commit crossed physical at **33–37 GB** producing
  **1,500–62,000 page-ins/s**, so the fix is "cap concurrency so commit stays under physical".
- **Killed by:** `[DOC-M]` docs/mesh/30-truth-and-disk.md:79, measured at 18:00 on 2026-09-16 —
  `\Memory\Pages Input/sec` p50 **7,680** (window A) / **1,210** (window B), max 70,703 / 154,703,
  but `\Paging File(_Total)\% Usage` held at **2 %** of an 11,776 MB pagefile,
  `\Memory\Pages Output/sec` was **0** in the load window, and `\Memory\Available MBytes` never fell
  below **15.3 GB of 31.6 GB**. "Those page-ins are **soft faults served from the file cache**, not
  pagefile thrash — so the 33–37 GB commit storm is a past state, not the current one, and the fix
  must be re-derived from a measurement under real load."
- **A companion falsification in the same family:** `[DOC-M]` 40-hardware-costs.md row 7 killed
  "**1,596 %** disk time" as "**not a possible reading** of `\PhysicalDisk(_Total)\% Disk Time` on
  this machine — it has exactly **ONE physical disk and ONE volume**". Re-measured: **4.48 % avg** in
  a quiet window, **97.31 % avg** seven minutes later.
- **And the third:** `[DOC-M]` 60-verification.md §2.3 — the causal statement behind "~13–14 turns
  before this laptop pages" is false: "**The largest page-in burst in the whole corpus — 27,028/s —
  happened at `engines=0`**, with commit a healthy 18.03 GB."

### 3.11 **New:** four counters that looked alarming in the harmless region — **FALSIFIED as signals**

`[DOC-M]` 84 §5.5 names three, and 109 §2.1 adds a fourth and calls it "**the fifth counter in this
program to look alarming in the harmless region**".

| counter | the alarm | what it actually measured |
|---|---|---|
| `Load` average | high = overloaded | never usable as a claim in 84 or 93 (`81` §3.6) |
| `Pages free` | low = pressure | same |
| `% Disk Time` | 1,596 % | "not a possible reading" (above) |
| `pages input/sec` | 233,604/s | a **process-start transient**; correlation with commit **0.123**, with node processes 0.150, with disk queue **0.746** — it is a function of how many turns you *launch per second* |
| committed/physical ratio | >92 % = refuse | measured at **120 %** with **7.7 GiB free and 194 MB in the pagefile**. "A refusal there would have refused work on a machine with 7.7 GiB free" |

**And the timing one, which is the same class:** `[DOC-M]` 84 §1.4.1 — a row stamped at the top of a
loop that then spent 2.1 s reading counters **halved the apparent slope** (301 vs 403 MiB/turn).
"This is the **third time** in this program that a counter's *timing* has misled a reader."

### 3.12 **New:** the per-turn constant's proposed measurement method — **FALSIFIED before it was used**

`60-verification.md` §6.3 proposed settling the per-turn constant by regressing commit on `/healthz`'s
`agentLoopsRunning`. That is the same finding as §3.2, and it is worth separating because **it is a
falsified method, not a falsified number**: had it been run, it would have returned 0 at every load
level and produced a confident wrong constant.

### 3.13 **New:** round-up — other beliefs the record states and then measures false

| belief | killed by | source |
|---|---|---|
| The first multi-window perf harness's numbers were real | every call came back **HTTP 200 carrying `gateway/bad-request: invalid client-request message`** — schema rejection, before any work. "**It was wrong and is withdrawn.**" The real knee is **4 concurrent windows** | `[DOC-M]` PERFORMANCE-MEASURED.md §"Correction first" |
| A clean (un-tokenised) origin is the right URL for a window | Both premises false: the launch token is a **stable per-process value** and nothing in the client boot path reads `location.search`. A profile that had never exchanged a token got the bare `dsh web authentication required` page — "what the owner hit three times on 2026-09-15 … profile `w9`" | `[DOC-M]` ANALYSIS-AND-DECISION.md §4 |
| Geometry flags only work with a private profile | Both measured windows opened at the configured geometry **in shared mode** | `[DOC-M]` MEMORY-AND-SESSION-LIST.md §6 |
| `Test-LaunchUrl` could rely on token *shape* | the recorded token answered **401** while the engine's own newest log line answered **303** — the launcher would have landed new windows on `dsh web authentication required` | `[DOC-M]` MEMORY-AND-SESSION-LIST.md §3A |
| "Compact at 400k instead of 1M" is the big win | "**not the big win it looks like**" — a normal working day averages **102k–263k tokens per request**, mostly below 400k | `[DOC-M]` 60 §5.5 |
| ~38 % of cost falls in peak hours | "**That was wrong** — the measured figure is **21–25 %**" | `[DOC-M]` 60 §7 Tier-2 item 6 |
| the cache-hit rate was ~$0.03/M | "**5–10× too high**; the real rate is **$0.003–0.006/M**. That single correction moves the whole cost composition." | `[DOC-M]` 60 §0.1 |
| "1.6 requests per second" | "**a factor of 10 too high** … The 1.6 was the correctly-measured per-**10-seconds** figure." True value **0.16 req/s** | `[DOC-M]` 96 §2.4 |
| 12 Edge windows cost 8.18 GB | Σ`WorkingSet` **8,181.6 MB** vs Σ`WorkingSetPrivate` **3,622.9–3,898.1 MB** — "**2.2× inflated**" by summing working sets across shared pages | `[DOC-M]` PROGRAM.md lines 81–82 |
| `journal.py`'s lock is safe and its critical section is "well under a second" | the break path `unlink`ed a live lock; the critical section is **40–100 s**. Falsified by the **161-collided-id** incident and by direct timing | `[DOC-M]` 30-locks-audit.md §0/§1.2 |
| `repair-ids --apply` closes a duplicate-id tree | measured on a synthetic tree: it wrote `L2000.md` and **left `L1999b.md` behind**, so `check` still exited 1. Fixed 2026-09-17. | `[DOC-M]` journal/reference/id-collision-20260917.md §3 |
| `idguard` reports all collisions | reported **9** while a content comparison found **10** — `D254` was committed without regenerating `entries.tsv`. Also `in_origin_cache: 0` but `entry_committed_in_origin: 1` for `D254/H474/L1914/P247` | `[DOC-M]` same §3; 107 §6.4 |
| A fast-forward `git pull` was refused because origin held older blobs | "**That was true and this commit removes it. What it did not say is that a fast-forward would have been refused *anyway***": git refuses when untracked files sit at paths the incoming commit will track, **even when the content is byte-identical** | `[DOC-M]` 103-route-commit-and-sync.md §2.2 |
| `--dump-config` over ssh reports the machine's state | "a **network-logon token cannot traverse it**; the engine's Interactive logon can. So an ssh-run compose on that machine **reports a fault that does not exist**" | `[DOC-M]` 103 §2.4 |
| v2's ceiling is one agent per node | 12 requests → 8 admitted + 4 queued, 0 refused, `maxInFlightSeen = 8` | `[DOC-M]` 93 headline |
| a busy node is a reason to dispatch elsewhere | "**And explicitly NOT when the node is busy.** … busy now means *'you have a position'*" | `[DOC-M]` 93 §7 |
| a `slow` node should be removed from the pool | the code did remove it, the contract said it should not; consequence measured as "an eight-child wave landing **7+1** and landing **8+0**" | `[DOC-M]` 92 §6.2, 98 §2 |
| `install-client-plugins.ps1 -Check` is a reliable keeper | "two consecutive runs minutes apart disagreed — the first reported five packages `LINK-ELSEWHERE / NEEDS FIX`, the second reported all six `LINK … ok`. … **a keeper that can report a false RED is a keeper that gets ignored**" | `[DOC-M]` 90-plugin-health-governor.md §7 |
| `pwsh` under `child.spawn({detached:true})` runs the script | "a detached `pwsh.exe` exits **0 after ~160 ms without running the script** — no output, no file, a **clean exit code**" | `[DOC-M]` 90 §4 |
| `ctx.get('webServer')` inside `apply` is safe | the loader's activation order is not the composed-tree order, "so a bare `ctx.get` returned `undefined` and **the route was silently skipped** while the plugin reported itself mounted" | `[DOC-M]` 90 §4 |
| A reader can rebuild the journal cache without the lock | `ensure_cache()` checks `lock.exists()` and, if false at that instant, rebuilds **without taking the lock**, then writes `stamp.json` whose `tree_signature()` is computed at the **end** — so `cache_fresh()` reports **fresh** while `entries.tsv` is missing the entry. "**a silently invisible entry**" | `[DOC-M]` 30-locks-audit.md §1.2 |
| `1,596 %` disk time, `SearchIndexer 107/29 GB` | both withdrawn as load-bearing; the second is unmeasurable from an unprivileged seat and was not the top consumer | `[DOC-M]` 30-truth-and-disk.md:256 |

---

# PART 4 — WHERE TWO SOURCES DISAGREE

**Never averaged, never picked.** Each row gives both numbers and both sources. Where a mechanism for
the disagreement is stated in the record, it is given; where none exists, that is said.

## 4.1 Disagreements with a stated mechanism (the disagreement is explainable)

| # | quantity | value A | value B | stated mechanism |
|---|---|---|---|---|
| A1 | per-turn commit | **403 MiB** (level-mean fit, ZABZ-TECH, 03:44Z) | **366 MiB** (measured at the derived limit, same node, 13:53Z) | 93 §5.2: "inside the CI, **9 % below** the point estimate"; different day, different prompt class, different rig |
| A2 | loop-lag max at 8 turns | **18 → 54 ms** (84, tool-heavy) | **17 → 17 ms** (93, tool-light) | 93 §5.2 names it explicitly: "my prompt is a *tool-light* turn … it does not test the tool-heavy worst case that `CPU_PER_TURN = 1.68` is drawn from" |
| A3 | pagefile % usage | **14.1 %** in all 83 samples (84, ZABZ-TECH, 03:4xZ) | **0 %** in all 39 rows (93, ZABZ-TECH, 13:53Z) | 93 §5.2: "this node's pagefile state differs; `84` is a night earlier" |
| A4 | per-window browser MB | **892** (7 private profiles) | **~60–296 marginal** (shared) | different design, measured the same day, one document, both stated |
| A5 | secratary swap / slots | **99.9 % → 1 slot** (76 §10.2/§11.2, "measured repeatedly 2026-09-16") | **81.2 % → 3 slots, `swapApplied false`** (95 §1.2, 98 §3, 2026-09-17) | time: two different days; and 95 §1.2 identifies the stale artefact as the `nodes.json` comment |
| A6 | zabz-tech-linux v1 dispatch | **true** (76 §10.4/§11.2, 2026-09-16 23:33Z — the ssh transport reached a model call) | **false** (98 §1/§4.3, from 2026-09-17T14:00Z — the dispatcher's own invocation exits 127, then `MISSING_CREDENTIAL`) | 98 §4.2: "The old roster note … is **stale**"; the two sessions tested different things (the transport vs the dispatcher's invocation) |
| A7 | Mac capacity surface | **exit 7** / `mem {totalMiB: null}` (76 §5, 2026-09-16 23:30Z, over `http://`) | **200 with a usable document** (95 §1.1, 2026-09-17 13:04:56Z, over `https://`) | time + **scheme**: 76 used `http://`, 95 used `https://`; 76 does not reconcile the scheme |
| A8 | broker reads / readFailures | **reads 56, readFailures 1** (95 §2.2) | **reads 8, readFailures 0** and later **reads 12, readFailures 0** (98 §3/§6) | 98 restarted the broker at 14:05:47Z, resetting in-memory counters — "stated so nobody reads 8 < 56 as a regression" |
| A9 | broker PID / uptime | **2024394**, since 03:54:31Z (95 §2.1) | **1892155**, started 00:05Z (76 §11.2); then `2304821 → 2304920 → 2304940` at 14:05:47Z and `2308723 → 2308860 → 2308879` at 14:11Z (98 §3) | sequence, not conflict |
| A10 | journal `check` warnings | **79** after (108 §11, "before AND after") | **85** after (107 §5); both report the same **79 before** | un-reconciled. 108's "before" equals 107's "before", so either one "after" is wrong or they are different trees. **Both stand.** |
| A11 | `zabz-yoga` inside 76 itself | §7.2's table prints the row as `zabz-yoga` | §10.5 item 2 requires `zabz-yoga-1` and "the broker refuses to boot on a row whose name is not the first label of its own fqdn"; §11.1 records the rename | §7.2's table **predates the rename and is not marked as superseded** — read it as history |
| A12 | engine start time, same pid, same document | `2026-09-14T18:28:59` (10-dsh-source-audit.md:25) | `2026-09-14 18:27:48` (:307) | 71 s apart, no mechanism stated |
| A13 | journal entry totals | `handoff 304, lessons 587, pain 178, decisions 176, wins 155` = **1400** (95 §6.2) | `find … -name '*.md' | wc -l` → **1616** in the same section; separately **L=1702, O=1705, R=1728** (107 §5); **1728** (108) | 95 §6.2: "The difference is 216 and it is **not explained by this page**." 95 explicitly refuses to pick. `[LIVE]` my own count tonight: **1,795** files in `entries/` (224+404+773+219+175) |
| A14 | session-log population | **385** (60 §2.3: "333 subagent, 54 root") | **387** in the same document's §6.1; **619** in 96 §2.4 | un-reconciled |
| A15 | journal append lock, pid 14268 | "held ~5 s -> **36 s**" (30-locks-audit.md §0) | "**41 s** (14268)" (§7) | un-reconciled |

## 4.2 Disagreements with **no** stated mechanism (these are the ones the redesign must resolve)

| # | quantity | value A | value B | why it matters |
|---|---|---|---|---|
| **B1** | **`zabz-yoga-1` concurrency** | **12 free slots of 24** (broker, 92 §5.1/§5.2/§5.3, 109 §1) | **5** (`mesh-http` derived limit, 93 §2.2) | Two different numbers for "how much can this laptop take", published simultaneously by two live surfaces of the same system. **A dispatcher asking one gets a different answer from a dispatcher asking the other.** |
| **B2** | **`zabz-tech` concurrency** | **18 slots** (broker: free=18, coreSlots=18) | **8** (`mesh-http`: cpu binds) | Same shape, 2.25× apart |
| **B3** | **`secratary` concurrency** | **3** (broker) | **1** (`mesh-http`, 4 cores) | The authority is the node where oversubscription is worst and the one node that could not be tested |
| **B4** | **`lakewooechsmini` concurrency** | **~7** (92 §1) | **1**, mem-bound (93 §2.2) | 7× apart |
| **B5** | **the reserve constant** | **3,885 MiB** (`scoring.js:70 RESERVE_MIB`, and 84's arithmetic) | **`max(2048, 12% of physical)`** → **7,821** on zabz-tech (93 §2.1, which attributes the formula to "84 §4.4") | 84 §4.4 **does not state that formula**. `scoring.js:136`'s own comment admits it: "77173 MiB -> 7821 (frozen 3885 UNDER-reserves by 3936 MiB, ~24 slots)". **One named constant, 2× different, on the same machine, and a document attributing a formula to a source that does not contain it.** |
| **B6** | **memory-term : core-term ratio** | **6×** (84 §5.3) | **8×** (93 §2.1, describing 84 §5.3) | small, but it is one document describing another's measurement differently |
| **B7** | **ZABZ-YOGA commit limit** | **44,145 MiB** (84 §4.4, 03:54Z) | **46.29 GB** and, in the same section, **43.11 GiB** (109 §2.1); and `48,556,675,072` (**"43.28 GiB"**) (109 §4.1, 22:33Z) | Four statements of one quantity. The limit legitimately moves with pagefile growth between 03:54Z and 22:33Z — **but 109 §4.1's own conversion of 48,556,675,072 B to "43.28 GiB" is arithmetically wrong (it is 45.22 GiB)**, which is separate from the movement |
| **B8** | **ZABZ-YOGA committed/physical ratio, one evening, one machine** | **126 %** (109 §1) · **120 %** (109 §2.1) · **122.1 %** (109 §4.1 probe) · **125.6 %** (109 §4.1 normal path) · **124 %** (109 §4.2 case A) · **95 %** (§4.3, SIMULATED) | — | five values, two of them inside one section, and one case's ledger carries the *other* case's `pressureLine` ("40670 MiB (125.6 %)") while its own `commitBytes` = 40,136 MiB and `commitToPhysicalPct` = 124 |
| **B9** | **"82 % of spend re-reading context"** | `PROGRAM.md:119` | 60 §1.3 and 96 §8 both say **42 %**; 60's nearest "82.5 %" is **tool output as a share of prompt tokens** | a summary line contradicting the measurement it summarises |
| **B10** | **"52.5 % of that day" from three sessions** | **52.5 %** (60 §7 Tier-1 item 4, `tools\day_sessions.py`) | **47.6 %** (65-spend-guard.md §2.4, `spend-guard.py`: "957 / 564 / 395 requests and they are **47.6 %** of the locally measured day (**$5.56 of $11.68**)") | and 65 adds the finding the percentage was used to reach: "**a single session cannot run away.** The largest session ever measured here costs **$2.88** (09-14) and **$2.56** (09-15). Ninety-nine sessions of $2 is how a day reaches $50. **09-15 had 79 sessions, 09-14 had 152.**" |
| **B11** | **the 8.18 GB Edge figure** | **8.18 GB** for 12 windows (inherited; still quoted) | **3,622.9–3,898.1 MB** private for the same windows | stated as a correction, but the old figure is still in circulation |
| **B12** | **requests and mean context per day** | 2026-09-16: **480** requests (60 §1.2, console ledger) vs **5,902** (60 §2.4, local logs) vs **13,760** (96 §2.4, 619 session logs). 2026-09-15: **34,787** / **36,972** / **5,813**. Mean context 09-15: **189,030** / **252,661** / 199,561 (tech) / 167,881 (yoga) | — | 60 §1.4 states the mechanism ("the local store captured **50 % of the misses, 76 % of the hits, 58 % of the output**") and the standing rule: "**For DSH money, cite `api_key_name` from the console export.**" **The same day's "cost per request" is $0.0015 (ledger) or $0.001623 (computed on the local mix) depending on which population you use.** |

## 4.3 Disagreements inside a single document

| defect | detail |
|---|---|
| 84 §4.1 sample counts | "14.1 % in every one of the **83** sample (**83 load-window samples + the 9-sample baseline**)" sums to 92; §2.2 says "all **83** rows - 74 in the five loaded levels and 9 baseline". 74 + 9 = 83 is the consistent reading; a delegated count of the printed rows found **9, 15, 15, 15, 15, 14 = 83** |
| 84 §4.4 TECH 60 % row | **66,631 MiB** should be **67,631** (65,173 + 0.60 × 4,096). The YOGA 60 % row (39,439) is correct |
| 84 headline vs table | "too high by **1.5×**" (headline) vs "**2.7×**" (§3.1) for the same 0.58 GB; and the same source cited as **0.58 GB** (§3.1 row 2) and **0.575 GB** (row 3) |
| 109 §2.1 | the same commit limit written as "**46.29 GB**" and "**(43.11 GiB)**" one line apart |
| 93 §5.1 | caller-side waitedMs **3,924 / 4,758 / 4,815 / 4,745** vs node-side DEQUEUE waitedMs **1,800 / 2,062 / 10,486 / 10,575** for the same four requests, both printed, never reconciled |
| 92 §5.1 | the rationale prints "slots 18 = **24 raw** - see above" — "24 raw" is the physical core count compared against a fraction of itself (`floor(24 × 0.75) = 18`) and is derived nowhere in the document |
| 95 §6.1 | "**0 errors, and `check` exits 0 only on a real error**" — self-contradictory as written, and it matters because that sentence is the one a reader uses to conclude the journal is healthy |
| MEMORY-AND-SESSION-LIST.md §1 | the seven profile rows each say **9** processes (63 total) while the prose and the summary say **74** processes |
| 70 §5 vs §2.1/§2.2 | §5 says pwsh start is "**340–406 ms best observed**"; no measured row shows 340 (the minima are **377.3** and **405.0**), and §7.1 separately cites an external **386.3 ms** |

## 4.4 **A disagreement I found by measuring, not by reading: `docs/mesh/*` exists twice**

`[LIVE]` **`docs/mesh/` holds 54 `.md` files; `journal/docs/mesh/` holds 53.** 52 of the 53 are
**byte-identical** (`sha256`) and **one is not**:

| file | docs/mesh | journal/docs/mesh |
|---|---|---|
| `84-calibration.md` | **47,898 B**, `sha256 F8AD26C8B46C…` | **47,813 B**, `sha256 1A0768A529AB…` |
| all 52 others (incl. `95`, `76`, `98`, `107`, `108`) | identical hashes | identical hashes |

`journal/docs/mesh/` has **no file that `docs/mesh/` lacks**; `docs/mesh/109-pressure-routing.md` has
no twin at all. Every twin in `journal/docs/mesh/` carries a single mtime — **`2026-09-17 21:57:45`
for all 53** — i.e. they were copied there in one pass.

**This is the same class of defect as the journal's own id collision and the `--dump-config` finding,
and the record has already named the general rule for it** (`[DOC-M]` 108 §5.3): *prefer an immutable
identifier over a mutable name, and when the two must be mixed, resolve the whole unit from the same
reading.* Two copies of the same document, one of them silently 85 bytes different, is exactly a
"two sources of truth for one thing" — and this audit's own `95`, `97`, `107` and `108` are among the
duplicated set, so a future reader may be reading a different `95` than the one audited.

---

# PART 5 — NOT VERIFIED

Stated as refusals. An empty result is not evidence of health.

1. **The 80-minute placement window** — does not exist in the record (§2.6). Four searches. If it
   exists, it is unwritten.
2. **The laptop's own per-turn commit and CPU curve** — refused by 84 §6.1; the laptop was past the
   stop line before any fleet ran. `0.75 × 16 = 12` is used in production and was never measured on
   the machine it is used for. **This is the single highest-value missing measurement** and 84 says so.
3. **A warm session-list read right now.** My only first-party data is the proxy's counters and its
   refresh times (3.5–20 s). **NOT VERIFIED** at 29 ms.
4. **Engine RSS over its life.** Point readings span **199 MB → 3,173 MB**; the live engine is
   **1.55 GB** at 2h08m. No curve.
5. **Engine warm-up / cold-start duration** — no document states it.
6. **Any matched-pair transport comparison at equal N with the same work** (93 §10.1).
7. **The region above 8 concurrent turns on any node** (93 §10.3).
8. **A real 55-child flow through the queue** — deepest measured queue is **4** (93 §10.8).
9. **`secratary` and `zabz-tech-linux` under load** — no `/healthz`; their limits are arithmetic
   (93 §10.4).
10. **`refuseWhenFull` against a live node** (93 §10.7).
11. **The Mac's memory term** — free physical as a proxy for available memory on macOS is not
    measured, and it is the only node where the memory term decides anything (93 §10.6).
12. **Whether the elevated cold boot works** — the incident's open item 2: not performed.
13. **The unexplained window count after `restore`** — the incident's open item 4, and `[LIVE]` still
    true tonight (§1.3: one live origin against fourteen registry rows).
14. **Whether `append`'s local-only guarantee holds on this tree right now** — `[DOC-M]` 108 §11:
    "**The publish path has never run against the live `origin/master` from this version of the
    tool.**"
15. **Whether the two machines' journal trees agree today** — the 2026-09-17 snapshot is "a moment,
    not a state", and the other machine's untracked set moved 18 → 21 *during* that session
    (`[DOC-M]` journal/reference/id-collision-20260917.md §6).
16. **The Mac Mini as a placement target** — 92 §9: not in the roster; 95 §2.2: the exclusion's own
    condition has been met.
17. **Whether the `[LIVE]` `list_agents` deadline pattern (4 scans, 0 hits, 3 deadlines) is a trend** —
    four scans is a small sample. Recorded as one observation.
18. **Which mechanism produced `secretary-fast → deepseek-v4-pro`** — 101 §10: "not determined".
19. **Whether the spend guard has ever actually refused anything live** — 101 §10: no live cap refusal
    demonstrated; the ledger shows `lastVerdict: "ok"` `[LIVE]`.
20. **Anything on `secratary` or `ZABZ-TECH` first-hand.** Every non-laptop claim in this document is
    **[DOC-M]** or **[DOC-R]**; I verified nothing on another machine.
21. **The `journal/docs/mesh` divergence's direction.** I established that `84-calibration.md` differs
    by 85 bytes and that all 53 twins share one copy time; I did **not** establish which copy is
    authoritative, nor diff the bytes.
22. **Anything written after 23:47 local 2026-09-17 on this machine.** The tree was dirty and being
    worked on; every reading here is a moment, not a state.

---

# APPENDIX — Provenance index

## Documents whose numbers appear above, with the date each states for itself

| document | its own stated date | used for |
|---|---|---|
| `docs/incidents/2026-09-17-dsh-engine-boot-failure/README.md` + `diagnosis-report.md` + `resolution-probe.txt` | 2026-09-17, closing addendum 22:35 local | §1.1, §1.2, §3.8, §4.1 |
| `docs/mesh/76-broker.md` | 2026-09-16 23:15–23:21Z, amended 2026-09-17 00:20Z | §2.7, §2.13, §4.1 A5/A6/A7/A11 |
| `docs/mesh/81-overnight-program.md` | 2026-09-17 ~00:30Z (owner mandate) | the program's own definition of done |
| `docs/mesh/84-calibration.md` | 2026-09-17 03:30Z–04:05Z | **§2.1, §2.2, §2.3, §2.10, §2.17, Part 3** |
| `docs/mesh/92-provider-placement.md` | 2026-09-17 13:00–14:00Z | §2.6, §2.8, §4.2 B1–B4 |
| `docs/mesh/93-transport-concurrency.md` | 2026-09-17 13:20Z–14:10Z | **§2.1, §2.3, §2.8** |
| `docs/mesh/94-routing-default.md` | 2026-09-17 13:00–13:30Z | §3.5 |
| `docs/mesh/95-audit-live-mesh.md` | 2026-09-17 13:04Z–13:16Z | §1.6, §2.6, §2.7, §2.13, §4.1 A8/A9/A13 |
| `docs/mesh/96-gateway-at-scale.md` | 2026-09-17 12:55–13:35Z | §2.9 |
| `docs/mesh/97-fleet-repairs.md` | 2026-09-17 13:17–13:40Z | §1.2, §2.13, §3.6 |
| `docs/mesh/98-broker-fixes.md` | 2026-09-17 13:40–14:20Z | §2.6, §3.6, §4.1 A6/A8/A9 |
| `docs/mesh/101-spend-guard-installed.md` | 2026-09-17 14:20–15:00Z | §2.9, §2.21 |
| `docs/mesh/103-route-commit-and-sync.md` | 2026-09-17 14:2x–14:5xZ | §3.13 |
| `docs/mesh/105-placement-committed.md` | 2026-09-17 15:00–15:4xZ | §2.15, §3.7 |
| `docs/mesh/106-desktop-last-mile.md` | 2026-09-17 15:30–16:00Z | **§1.2, §2.15, §3.6, §3.7** |
| `docs/mesh/107-journal-convergence.md` | 2026-09-17 16:2x–16:4xZ | §2.12 |
| `docs/mesh/108-id-allocation.md` | 2026-09-17 16:4x–17:2xZ | §2.12, §4.4 |
| `docs/mesh/109-pressure-routing.md` | 2026-09-17/18 | **§2.3, §2.6** |
| `journal/reference/id-collision-20260917.md` | 2026-09-17 16:0x–16:4xZ | §2.12 |
| `docs/dsh-at-scale/10-dsh-source-audit.md` | 2026-09-15 ~22:45–22:50 local | §1.1, §1.10, §2.5 |
| `docs/dsh-at-scale/30-locks-audit.md` | 2026-09-15 22:16–22:52 EDT | §2.12, §2.19 |
| `docs/dsh-at-scale/60-cost-audit.md` | 2026-09-16 | §2.9, §3.13 |
| `docs/dsh-at-scale/70-toolcall-latency.md` | 2026-09-16 14:20–14:45 UTC | **§2.10**, §3.5 |
| `docs/dsh-at-scale/80-windows-and-parity.md` | 2026-09-16 | §3.1 |
| `docs/dsh-at-scale/90-plugin-health-governor.md` | 2026-09-16 | §1.8, §1.9, §2.14, §3.5, §3.13 |
| `docs/dsh-at-scale/PROGRAM.md` | 2026-09-15, with a 2026-09-16 ZABZ-TECH measurement | §2.1, §2.9, §3.1 |
| `docs/mesh/60-verification.md` | 2026-09-16 | §3.1, §3.10 |
| `docs/mesh/40-hardware-costs.md` | 2026-09-16 (+ corrections) | §3.10 |
| `docs/mesh/30-truth-and-disk.md` | 2026-09-16 | §3.10 |
| `docs/multi-window/MEMORY-AND-SESSION-LIST.md` | 2026-09-18 | **§1.3, §1.4, §2.4, §2.5** |
| `docs/multi-window/PERFORMANCE-MEASURED.md` | 2026-09-11 and 2026-09-14 | §2.4, §2.18, §3.13 |
| `docs/multi-window/ANALYSIS-AND-DECISION.md` | 2026-09-11 | §2.4, §3.13 |

## The commands I ran, in full

```powershell
# Structure and config
Get-ChildItem -Recurse -File docs\incidents\2026-09-17-dsh-engine-boot-failure | Select FullName,Length
Get-Content ~\.dsh\multi-window\windows.json -Raw
Get-Content C:\Users\ezabz\code\harness-config\multi-window\windows.json -Raw
Get-Content ~\.dsh\settings.yaml -Raw
Get-Content ~\.dsh\profiles\web\{cordis.yml,package.json} -Raw
Get-Content C:\Users\ezabz\code\harness-config\packages\mesh-broker\nodes.json -Raw
Get-Content C:\Users\ezabz\code\harness-config\packages\plugin-cost\cordis.patch.yml -Raw
Get-ChildItem ~\.dsh\profiles\web\node_modules | % { "$($_.Name) LinkType=$($_.LinkType) Target=$($_.Target)" }

# Live processes and ports
Get-NetTCPConnection -LocalPort 3099 -State Listen
Get-Process -Id 4416 | Select ProcessName,RSS,Private,Threads,StartTime
Get-Process node | Select Id,@{n='RSS_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}},StartTime | Sort RSS_MB -Desc
Get-Process msedge,pwsh,python -ErrorAction SilentlyContinue          # counts 66 / 10 / 13
Get-NetTCPConnection -State Listen | ? { $_.LocalAddress -notin @('127.0.0.1','::1') }
Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'phone-gate|mesh-broker|dshw-proxy|harness-metrics|dsh-reap' }
& "$env:ProgramFiles\Tailscale\tailscale.exe" status
& "$env:ProgramFiles\Tailscale\tailscale.exe" serve status

# Machine state
$os=Get-CimInstance Win32_OperatingSystem; $cs=Get-CimInstance Win32_ComputerSystem
#   LastBootUpTime 09/17/2026 21:31:07 ; TotalPhysicalMB 32373 ; FreePhysicalMB 10740
#   LogicalProcs 22 ; TotalVirtualMB 44149 ; FreeVirtualMB 16906
Get-Counter '\Memory\Committed Bytes','\Memory\Commit Limit','\Memory\Pool Paged Bytes','\Memory\Pool Nonpaged Bytes'
#   committed 27386.3 MB ; limit 44149.4 MB ; paged 1856.7 MB ; nonpaged 1060.4 MB

# Hostname resolution
Resolve-DnsName zabz-yoga ; Resolve-DnsName zabz-yoga-1 ; Test-Connection zabz-yoga -Count 1
Get-Content C:\Windows\System32\drivers\etc\hosts

# Scheduled tasks
Get-ScheduledTask | ? { $_.TaskName -match 'DSH|PersonalSecretary|LPT|dsh' } |
  % { $i=$_|Get-ScheduledTaskInfo; "$($_.TaskName)|$($_.State)|$($i.LastRunTime)|$($i.NextRunTime)|$($i.LastTaskResult)" }
Get-ScheduledTask | ? {...} | % { ($_.Actions|%{"$($_.Execute) $($_.Arguments)"}) ; ($_.Triggers|%{$_.CimClass.CimClassName+':'+$_.Repetition.Interval}) }
Get-ChildItem C:\Users\ezabz\code\harness-config\scripts\hidden-tasks\*.vbs | ? Name -match 'DSH|dsh|PushDSH' | % { Get-Content $_.FullName -Raw }

# Mesh / guards / gates — all read-only GETs, all with the proxy disabled
$h=New-Object System.Net.Http.HttpClientHandler; $h.UseProxy=$false
$c=New-Object System.Net.Http.HttpClient($h)
$c.GetAsync('http://127.0.0.1:3086/mesh/capacity')   # 200, the capacity document quoted in §1.5
$c.GetAsync('http://127.0.0.1:3099/mesh/health')     # 200, the mesh-http health document
(Invoke-WebRequest 'http://127.0.0.1:3200/__dshw/stats' -UseBasicParsing).Content
(Invoke-WebRequest 'http://127.0.0.1:3200/__dshw/open'  -UseBasicParsing).Content

# State files
Get-Content ~\.dsh\spend-guard\day.json -Raw
Get-Content ~\.dsh\health\list-agents.json -Raw
Get-Content ~\.dsh\health\processes.json -Raw | ConvertFrom-Json | Select system,totals,processorCount,enginePid,at
Get-Content ~\.dsh\multi-window\{state.json,ready-3099.json,windows-registry.json,origins.pid} -Raw
Get-Content ~\.dsh\multi-window\{engine-recovery.log,watchdog.log,health.log} -Tail 30
Get-Content ~\.dsh\mesh\restart-when-idle\decisions.log -Tail 25
Get-ChildItem ~\.dsh\mesh\placements -File | % { Get-Content $_.FullName -Raw }
Get-ChildItem ~\.dsh\metrics\harness-metrics.csv | % Length ; Get-Content ... -TotalCount 1 ; -Tail 3
(Get-Content ~\.dsh\metrics\harness-metrics.csv | Measure-Object -Line).Lines   # 5298

# Journal
cd C:\Users\ezabz\code\harness-config
python journal/tools/journal.py check                 # stale+locked, warnings, exit 0
Get-ChildItem journal\entries -Directory | % { "$($_.Name) = $((Get-ChildItem $_.FullName -File).Count)" }
                                                      # decisions 224, handoff 404, lessons 773, pain 219, wins 175

# Duplicate documentation finding
$a=(Get-ChildItem docs\mesh\*.md -File).Count         # 54
$b=(Get-ChildItem journal\docs\mesh\*.md -File).Count # 53
# per-file sha256 sweep: identical=52 different=1  (84-calibration.md)
```

## What I did not do

- **No engine restart, no process killed, no service started or stopped** — including the ones that
  would have made a measurement easier.
- **No fleet dispatched, no child turn run, no remote command executed on any node.**
- **No `git` state change** — no add, commit, branch, reset, stash, fetch or push.
- **No file written except this one.** `journal.py check` was run in its normal (cache-refreshing)
  mode; it answers from `entries/` when the cache is locked, which is what happened here.
- **No design proposed.** Part 1 describes what exists; it deliberately contains no recommendation.
  That is another stream's job.
