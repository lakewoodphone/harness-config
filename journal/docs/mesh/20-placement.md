# 20 — Placement: where agent work runs across the 6-node mesh

## CORRECTIONS APPLIED 2026-09-16 (verification pass — see 60-verification.md)

A second agent re-measured this document's load-bearing numbers on `ZABZ-YOGA` at 21:44–21:56Z and against
the machine's own sampler record (`~/.dsh/metrics/harness-metrics.csv`). Four things were wrong here, and one
of them is a **provenance** error in the document whose §0 is entirely about provenance discipline. Prose is
left intact and marked `[corrected 2026-09-16: was X]` so the error stays legible.

| # | Old value (in this document) | Corrected value | Evidence |
|---|---|---|---|
| 1 | **`§1.4`, `§6.1`: "one generating turn = 0.81 GB commit, ~1 core" tagged PRIOR-MEASURED** (`:172`, `:665`) | **Not supported.** Measured: **≈18 GB resident before any work** and **≈0.58 GB commit per extra node PROCESS** (r = 0.937). "Generating turn" is not the unit the machine recorded — the sampler's `engines` column has no documented definition and does not predict memory (`engines=15` and `21` both showed 34.6 GB while `engines=13` showed 17.2 GB) | least-squares over 477 rows: `corr(commit_gb,node)=0.937`, slope 0.5754; commit at `engines≤13` never exceeded 19.11 GB; idle floor 17.0–18.4 GB. `60-verification.md` §2.2 |
| 2 | **`§6.1` table header "Measured constants used"** (`:661–674`), of which `:670–672` (`ZABZ-YOGA` budget, `secratary`, `ZABZ-TECH` headroom) are one live reading from one moment | **`:670–672` are now labelled for what they are** — one `/healthz` reading at 20:10Z, not constants. `:665` is PRIOR-MEASURED from `PROGRAM.md:75` and is corrected by row 1. The commit limit in `:670` is also **wrong today**: measured 43.11 GiB, not 44,149 MiB | `(Get-Counter '\Memory\Commit Limit')` = 46,293,966,848 B = 43.11 GiB = 31.61 GiB RAM + 11,776 MB pagefile, exactly. `AutomaticManagedPagefile = True`, so the limit MOVES. `60-verification.md` §1.2 |
| 3 | **`§4.2`: "`ZABZ-YOGA` budget: commit limit 44,149 MiB"** (`:670`) | **43.11 GiB, read at call time.** Never hard-code it | same as row 2 — note `Win32_OperatingSystem.TotalVirtualMemorySize` IS the commit limit and excludes committed bytes, which is the trap that produced the old number |
| 4 | **`§1.4`, `§6.3`, `§D6`, `§9`: "1,596 % disk time"** (`:178`, `:716`, `:760`, `:802`, `:845`; also `:501`) | **Not a possible reading of `\PhysicalDisk(_Total)\% Disk Time` on a one-disk machine**, and no counter is named anywhere. **The condition is real and re-measured: 4.48 % avg at 21:46Z, 97.31 % avg at 21:53Z.** Cite the saturation, the queue length and the latency — never the 1,596 % | `Win32_DiskDrive` → 1 device; `Get-Volume` → 1 volume; `Get-Counter '\PhysicalDisk(_Total)\% Disk Time'` and `\...\Current Disk Queue Length` (0.00 at 21:46Z, 0.74 at 21:47Z) |
| 5 | **`§8 Phase 1 item 2`: acceptance = "one cold `GET /` **200** from a phone with no token in the URL"** (`:781–783`) | **A cold no-token `GET /` is never 200 — it is 401 by design** (`:437–445` of this same document says so). Measured: `GET /` on a foreign authority = **401**, `GET /api` = **403**. The publish test is: `tailscale serve status` names a port **that has a live listener**, and the served URL is **not 403 and not 502**. **Also measured and worse: `ZABZ-YOGA`'s serve entry currently points at `127.0.0.1:3086`, which has NO listener — so `https://zabz-yoga-1.tail93e6e6.ts.net/` returns 502 right now** | `curl --noproxy '*' http://127.0.0.1:3099/` → 401; `... -H "Host: zabz-yoga-1.tail93e6e6.ts.net" /api` → 403; `Get-NetTCPConnection` on 3080–3100 → only 3099; `curl https://zabz-yoga-1.tail93e6e6.ts.net/` → **502 in 0.060 s**. Full corrected procedure: `60-verification.md` §4.2 |
| 6 | **`§0`: "Serve is not enabled on `ZABZ-TECH`, `ZABZ-YOGA` or `linux-pc` (\"No serve config\")"** (`:33–35`, `:88–89`) | **Stale for `ZABZ-YOGA`** — it is served now (see row 5 for where it points). `§9` of this same document (`:852–857`) already said the general fact correctly; §0 was not reconciled with §9 | `tailscale serve status` → `https://zabz-yoga-1.tail93e6e6.ts.net (tailnet only) |-- / proxy http://127.0.0.1:3086` |
| 7 | **`§6.3`: "1,172 ms for one scan (430 files / 237.5 MB)"** (`:669`) and "237.5 MB corpus" (`:720`, `:760`, `:802`) | **The corpus is 444 files / 255,137,162 B (243.3 MiB) as measured**, and the same figure is quoted as a *file count* and a *memory quantity* in two places. Treat `list_agents` cost as **"≈250 MB corpus"** and re-measure the scan | `Get-ChildItem ~/.dsh/sessions -Recurse -File | Measure Length -Sum` → `n=444 bytes=255137162`. `30-truth-and-disk.md:18` says 436 / 251,054,028 — three mutually exclusive figures in circulation. `60-verification.md` §1.3 |
| 8 | **`§1.4`: "the binding resource on the laptop is **commit**, not CPU"** (`:173`) | **Contradicted by `40-hardware-costs.md:325` ("the binding constraint is CORES, not RAM"), which is the better-supported claim.** The laptop's commit has never exceeded 36.49 GB against a 43.11 GiB limit; what it does is page under I/O pressure | `60-verification.md` §3 C6 |

**What did NOT change.** The spine of this document — one engine per `DSH_HOME`, sessions never move, the
client targets whatever origin served it (`§1.3`), the gate-in-front shape proven on `secratary` (`§1.0`),
the placement-not-restart recovery model (`§5`), and D1–D6 — is unaffected by every correction above. Rows
1 and 8 change *sizing inputs*; rows 4 and 5 change *what proves it works*. The design does not rest on any
number that failed.

**One warning that this pass earned the hard way.** `§7` D3 and `§4.2` propose publishing each node with
`tailscale serve`. **That is now demonstrated insufficient on this very laptop: a serve entry can point at a
port with no listener, and every request then returns 502 while `tailscale serve status` looks perfectly
healthy.** Any acceptance test for publication must include the listener check, in addition to the status
line — see `60-verification.md` §4.2 steps 1 and 3.

---

**Program:** `docs/mesh/` (this file is the placement volume; it depends on nothing else in the series and
nothing in the series depends on it being read first).
**Date:** 2026-09-16. **Author:** an agent session, not the owner. **Status:** design, nothing implemented by
this document. Read-only: no engine was started, stopped, restarted or reconfigured to write it.

**The owner's goal, in his words:**
> *"whether I am running you on the yoga, on the office desktop, on my iPhone, it is always properly balanced
> across the mesh and speeding fast … I can also change out the secretary server to something better … we can
> buy whatever is needed and implement whatever code is needed."*

---

## 0. Provenance discipline

Every load-bearing sentence below carries one of four tags. Nothing is asserted from a README, from another
document's summary, or from configuration alone.

| tag | means |
|---|---|
| **MEASURED** | taken live in this session (2026-09-16 ~19:50–20:15 local on `ZABZ-YOGA`) by running something; the command or endpoint is given |
| **READ** | read out of installed source or this repo's configuration, with `path:line` |
| **PRIOR-MEASURED** | measured on this host by an earlier session of this same program; the document and line are given, and it is a claim about a machine that is still moving |
| **PROPOSED** | this document's design decision. Not built, not verified. Every one is marked again where it matters |

Three numbers that this document does **not** have, and says so rather than guessing:

- **`ZABZ-TECH`'s live *headroom*.** Its shape is now MEASURED (24c/32t, 63.6 GB — §1.0), and a prior session
  measured commit 44.5 GB / 38.1 GB free (`docs/dsh-at-scale/PROGRAM.md:76`), but **no capacity reading was
  taken on it for this document**: it answers SSH, and nothing in this task was allowed to run a probe there.
  Treat its *headroom* as PRIOR-MEASURED, not current.
- **Whether the owner has enabled Tailscale Serve beyond `secratary`.** MEASURED here: Serve is **not** enabled
  on `ZABZ-TECH`, `ZABZ-YOGA` or `linux-pc` ("No serve config"), and `secratary` is served. So the tailnet-level
  enablement exists; the *per-node* publication is what is missing.
  `[corrected 2026-09-16: **stale for `ZABZ-YOGA`, which is served now** — measured `tailscale serve status` →
  `https://zabz-yoga-1.tail93e6e6.ts.net (tailnet only) |-- / proxy http://127.0.0.1:3086`. This §0 sentence
  was never reconciled with §9 of this same document (`:852–857`), which had the general fact right. **And the
  more useful correction: being served is not sufficient** — that entry points at a port with no listener, so
  every request through the URL returns **502**. See `60-verification.md` §4.2 and §4.3.]`

---

## 1. The settled facts the design rests on

These are the constraints, not opinions. Each is a MEASURED or READ fact; the design in §3 is the arithmetic
that follows from them.

### 1.0 The roster, corrected — and one node that is already doing this right

Two node lists in circulation are wrong, and one node was missing from both. MEASURED by read-only SSH and
`tailscale status --json` from `ZABZ-YOGA`, 2026-09-16 ~20:15 UTC:

| node | hostname | OS | cores | RAM | role | reached by |
|---|---|---|---|---|---|---|
| office desktop | **`ZABZ-TECH`** | Win 11 Pro 26200 | 24c/32t | 63.6 GB | primary workstation | `desktop-ts` → `zabz-tech.tail93e6e6.ts.net` = 100.85.153.96 |
| home laptop | `ZABZ-YOGA` | Win 11 Home 26200 | 16c/22t | 31.6 GB | the owner's night machine | `laptop-ts` → `zabz-yoga-1.tail93e6e6.ts.net` = 100.72.162.5 |
| authority | `secratary` | Ubuntu 7.0.0-30 | **4** | 23.4 GB, **swap 100 % used** | authoritative DB + FastAPI + agent ticks | `secratary-ts` → 100.84.72.88 |
| office Linux | **`zabz-tech-linux`** | Ubuntu 6.8 | 12 (i5-11400) | 11.7 GB | office Linux box | `linux-pc-ts` → 100.105.248.90 |
| mac mini | `LakewooechsMini` | macOS 26.5.2, M4 | 10 | 16 GB, **17 GB disk free** | Yisroel's | `mac-mini-ts` → 100.126.146.121 |
| Hetzner | `waze-mdm-01` | Ubuntu 6.8 | 2 | 1.9 GB | Waze MDM | public 87.99.141.172 (**not on Tailscale**) |
| Hetzner #2 | `lpt-apps-01` | Ubuntu 6.8 | 4 | 7.8 GB, disk 84 % | LPT apps, caddy + postgres | public 2.28.33.58 |

**Corrections to the brief's node list, and they matter:** `ZABZ-TECH` is *not* host `DESKTOP-FGV6KMH` —
`multi-window/machines/DESKTOP-FGV6KMH.windows.json:2,13` describes that machine as **Yocheved's laptop** with
`primaryWorkspace C:\Users\cheve\code\lpt-hub`, and `multi-window/dshw.ps1:53,207` scopes it to `C:\Users\cheve\dsh`.
`ZABZ-TECH-LAPTOP` is referenced **only** at `scripts/mesh-prereqs.json:21` — absent from
`tailscale status --json`, absent from `~/.ssh/config`, and `desktop-fgv6kmh.tail93e6e6.ts.net` does not resolve.
UNKNOWN whether it is a real node or a stale key. And **`zabz-tech-linux` was missing**: a 12-core office Linux
box on the tailnet, which is the best cheap candidate for a Linux worker.

**And the finding that changes this document's tone: the mesh already contains a working, verified instance of
the architecture recommended in §2 — on `secratary`.** MEASURED:

```
$ ssh secratary-ts "ps -eo pid,etime,args | grep 'bin[.]js web' | grep -v grep; ss -ltnp | grep 308"
906634  13:59:37  node .../dsh/lib/bin.js web --port 3089 --no-open --trusted-host secratary.tail93e6e6.ts.net
LISTEN 127.0.0.1:3089  node       (the engine)
LISTEN 127.0.0.1:3086  python3    (the gate)
$ systemctl show phone-engine.service -p Environment
Environment=HOME=/home/zabz NODE_ENV=production      # no DSH_HOME => the default ~/.dsh, and it is the only engine on it
```

- **Exactly one engine, one `DSH_HOME` (`/home/zabz/.dsh`, 14 MB of sessions).** No second engine exists against
  that home, so there is nothing to audit away and the one-writer rule is already honoured *there*.
- **The engine binds loopback only and trusts the tailnet name** — `phone-engine.service`
  `ExecStart=… bin.js web --port 3089 --no-open --trusted-host secratary.tail93e6e6.ts.net`, owned by systemd
  (`Restart=always`), not by an SSH session (the reason is recorded at `docs/dsh-mobile/02-SYSTEMS.md:34-45`:
  `setsid nohup` does **not** escape a login session's cgroup, and systemd-logind reaped the phone silently).
- **A gate in front of it does the two things DSH makes hard** — `phone-gate.service` runs
  `scripts/phone-gate.py --listen-port 3086 --engine-port 3089`, and Tailscale Serve publishes **the gate**:
  MEASURED `tailscale serve status` on secratary → `https://secratary.tail93e6e6.ts.net (tailnet only) |-- / proxy http://127.0.0.1:3086`.
  Funnel is **not** configured (correctly), and `ZABZ-TECH`, `ZABZ-YOGA` and `linux-pc` all report
  **"No serve config"**. `[corrected 2026-09-16: stale for `ZABZ-YOGA` — it reports a serve entry, pointing at `127.0.0.1:3086`, which has no listener, so the URL answers 502. Source: 60-verification.md §4.3.]`
- **It is continuously probed, not assumed:** cron `*/5` runs `scripts/probe-phone.py` → `~/.dsh-phone/probe.json`,
  and its 15 checks include the cold visitor, the token exchange, the document, the **WebSocket upgrade 101**,
  the foreign-Host fence, a stale cookie, a dead link, **an authenticated `session/list` RPC**, and that the
  layer cannot be cached away (`docs/dsh-mobile/02-SYSTEMS.md:124-125`).

**So this document is not proposing a new pattern for remote access. It is proposing to generalise the one the
owner already has running, verified, on the authority — to every node that holds sessions he wants to reach.**
That is a much better position than a design starting from nothing, and it is why §2(a) wins on evidence rather
than on argument.

### 1.1 One engine per DSH_HOME. One DSH_HOME per node.

- One engine process per home: `node .../dsh/lib/bin.js web --port 3099` — PRIOR-MEASURED,
  `docs/dsh-at-scale/10-dsh-source-audit.md:21`.
- **Two engines on one home corrupt session logs** (duplicate sequence numbers made a history unloadable) —
  PRIOR-MEASURED, stated in `multi-window/windows.json:5`.
- The shipped lock does **not** fix this. It is a **per-session** write lease, held by the kernel, with
  **deliberately no expiry**: `dsh-session-persistence-jsonl/lib/index.js:611-640` — Windows takes a **named
  kernel semaphore** derived from the resolved artifact path (`:555-557`), contention maps to
  `SessionAlreadyOwnedError` (`:677`), and *"a live but wedged holder keeps the lock until its process exits:
  there is deliberately no expiry that could expropriate a stalled writer whose resumed appends would tear the
  log"* (`:621-624`). Two engines on one home do not corrupt the *same* session — the kernel stops that — but
  they still interleave unrelated appends, and the host-local state below has no lock at all.

- **A network-shared `DSH_HOME` across machines is not merely discouraged; it cannot work, and this is now
  readable from the code rather than inferred.** Three independent reasons:
  1. On Windows the lock is a `Local\` kernel object (`:557`) — **per machine**. Two Windows hosts sharing an
     SMB path cannot exclude each other *by construction*, and there is no lock file to fall back to
     (`:630` — *"Windows has no lock file at all"*). POSIX uses `flock(2)`
     (`node-addon-system/src/flock.c:58`, `LOCK_EX|LOCK_NB`), which an SMB/NFS client may or may not honour —
     the subagent's word for that is UNKNOWN, and an unknown arbiter is not an arbiter.
  2. Durability assumes one local filesystem: Windows publish is
     `MoveFileExW(..., MOVEFILE_WRITE_THROUGH)` with **no cross-volume fallback** (`:452`, `:534-543`;
     `ERROR_NOT_SAME_DEVICE` → `EXDEV`, `:496-497`), POSIX publish is `link()` + directory fsync
     (`:2970-2982`, `:3032-3039`), and identity is decided by `realpath` (`:3241-3254`).
  3. The home is *split anyway*: `harness-config/README.md:32-37` and `scripts/sync.py:42` both keep
     `sessions`, `.credentials.yaml`, `.anonymous-user-id` and `profiles/node_modules` **machine-local**.
     The repo already decided this; the design must agree with it.

  **Therefore: one `DSH_HOME` per node, unfailingly. `DSH_HOME` resolution is
  configured-path → `$DSH_HOME` → `~/.dsh`** (READ, `dsh-home-paths/lib/index.js:73-76`), so a node needs no
  configuration to be correct — and a node that *does* point `DSH_HOME` at a share is the hazard, not the
  feature.

### 1.2 What is node-local and what is shared — the mobility map

This is the single most important table in this document, because every placement decision is really a
decision about which row is authoritative.

| artefact | where it lives | cross-node? | evidence |
|---|---|---|---|
| **The session log** (`session.v3.jsonl.zstd`) | `<DSH_HOME>/sessions/--<cwd>--/<id>/` — **the node's own disk** | **No** | READ, `dsh-base/cordis.patch.yml:113` (`root: !!js dshHomePath('sessions')`); MEASURED here: **430 files / 237.5 MB** |
| **The session write lease** | kernel object on the node (no file on Windows) | No | READ, `dsh-session-persistence-jsonl/lib/index.js:555-557, 642` |
| **Client "current session"** | browser `localStorage["dsh.sessions.current"]`, keyed by **origin = scheme+host+port** | No | READ, `dsh-api-session-controller/lib/client.js:3058`, `:3411-3415` |
| **Auth cookie** | browser, name = `dsh-auth-<sha256(authority)>` | No — deliberately worthless on another authority | READ, `dsh-client-connection/lib/index.js:280-282`, `:435-441` |
| **Governor leases** | `<DSH_HOME>/governor/leases/slot-NN.lease` — **per home, per node** | **No — it is per-node by construction** | READ, `packages/plugin-health/lib/governor.js:83-97` |
| **The journal** | `harness-config/journal/` in git, replicated by `autosync` every 15 min | **Yes** | READ, `docs/dsh-mobile/00-RESEARCH.md:270-279` |
| **Presets, settings, scripts** | `harness-config/` → `scripts/sync.py` into `~/.dsh` | **Yes** | READ, `scripts/autosync.ps1:349-380` |
| **Repo code and branches** | the git remote | **Yes** | — |
| **Worktrees (fleet isolation)** | local path under the node's filesystem | **No** | READ, `docs/parallel-agent-orchestration.md:71` |
| **Session archive (searchable)** | authority SQLite, via `push-dsh-sessions.mjs` | **Yes — one way, and there is no path back** | READ, `scripts/push-dsh-sessions.mjs:59-60, 101-102, 264-297`; the cursor is `~/.dsh/dsh-archive-state.json` (`:61`); **nothing writes into `~/.dsh/sessions`** (`dsh-archive-import.py:1-17` is a one-shot into a *server-side* archive, `dsh-sessions.py:20-23` is a read-only reader) |
| **Per-node facts the company already records** | authority: `next_stage_node_reports`, `next_stage_machine_access_checks` | **Yes, already** | READ, `personal-secretary-mvp/app/services/next_stage_runtime.py:156-167, 173-185`; aggregated by `app/autopilot.py:3827-3831`; surfaced at `~/.personal-secretary/mesh-health.json` (`app/assistant_chat.py:2625-2641`) |
| **`owner_decision_queue`** | authority SQLite — `scripts/owner-queue.py:74`, DB `/home/zabz/personal-secretary-mvp/data/secretary.db` (`:49`) | Yes | MEASURED read-only: `/home/zabz/bin/owner-queue.py` present, 12,242 B, mtime Sep 15 22:48, `CREATE TABLE IF NOT EXISTS owner_decision_queue` at its `:54` |

**The consequence, stated plainly:** a session is a *node-local object*. "Open my session from the iPhone"
is not a routing problem, it is a **reach-that-node's-engine** problem. And the `session.lock` file
(`lease.d.ts`, quoted at `dsh-session-persistence-jsonl/lib/index.js:622-624`) says a *resumed* writer must
scavenge a stale lock — which is fine on one host and impossible to answer across hosts. **Design rule:
sessions do not move. Replicas are archives, not live sessions.**

### 1.3 The client already targets whatever engine it was served by

- The Remote stream WebSocket URL is derived from the **page's own origin**:
  `dsh-api-gateway/lib/client.js:542-545` — `base = location.origin`, then `url.protocol = https: ? wss: : ws:`.
  MEASURED behaviour of that code path: the mux path is the fixed `/api/remote.mux` (READ, `:49`).
- So a browser that loaded `https://zabz-tech.tail93e6e6.ts.net/` opens **that** node's WebSocket. No client
  change, no hostname in any config, no per-node client build.

**This is why the whole remote story needs no client work at all**, and it is the reason Option A in §2 wins.

### 1.4 The owner's laptop is slow because of *running turns*, not windows

- A running turn costs **~0.81 GB commit and ~1 core**; an idle browser window ~0.25 core; the binding
  resource on the laptop is **commit**, not CPU — PRIOR-MEASURED, `docs/dsh-at-scale/PROGRAM.md:75`,
  `docs/multi-window/PERFORMANCE-MEASURED.md:168-185`.
- It is **windows whose agents are generating** that is heavy, and *"the resource that is actually tight is
  memory, not CPU"*, with *"cap simultaneously running agents at 3-4"* as a recommendation —
  PRIOR-MEASURED, `PERFORMANCE-MEASURED.md:127-135, 220-221`.
- Under load the second binding resource is **disk**: **1,596 %** disk time when builds + indexers + agents ran `[corrected 2026-09-16: the condition is real — 97.31 % average disk time over a 3 s window on this laptop, with SearchIndexer reading 44–102 MB/s — but the NUMBER is not a possible reading of the counter it is attributed to, because this machine has ONE physical disk and ONE volume and a per-disk percentage cannot exceed 100. No counter is named anywhere in the wave. Cite the saturation, the queue length and the latency; drop 1,596 %. Source: 60-verification.md §1.5 and §6.3 item 2.]`
  together — PRIOR-MEASURED, `docs/parallel-agent-orchestration.md:186-188` context and the program's own
  disk finding.

**Therefore the design goal is not "spread windows". It is "keep generating turns off the machine the owner
is holding".**

### 1.5 The per-call process cost that the admission governor already prices

- A tool call that runs a shell costs **two** processes: a ~57 MB Job-owner runner plus the shell (~103 MB) —
  **~160 MB in flight** — PRIOR-MEASURED, `10-dsh-source-audit.md:63-65`; the governor's own constant is 160 MiB
  (`governor.js:53`).
- **No shipped tool is concurrency-safe**, so parallel calls in one step run **in series** at ~700 ms each —
  PRIOR-MEASURED, `10-dsh-source-audit.md:192` (`dsh-tools/lib/index.js:2953-2955`, exclusive-tool barrier).
- The governor is **advisory today** and it **never refuses**: it returns `GRANTED` or `QUEUED position N` with
  exit code 10, budget = `(free physical − reserve) / 160 MiB`, capped 24, floored 4 —
  PRIOR-MEASURED, `docs/dsh-at-scale/90-plugin-health-governor.md:206-255`.

### 1.6 Live readings taken for this document

**MEASURED 2026-09-16 20:10:07Z on `zabz-yoga`, engine pid 1784 (up 20m56s), via the `engine_health` tool →
the plugin's own `/healthz`:**

```
loop lag  p50=2ms  p95=16ms  max=706ms  (512 samples @ 250 ms)
memory    rss=743.5 MiB  heap=426.3/623.3 MiB
system    phys avail 17575.1 / 32373.4 MiB  cpus=22
          commit 26334.8 free of 44149.4 MiB limit  memoryLoad=45%
processes 307 total, 4153 threads; tool-call runners 6 (251.9 MiB)  mcp 0 (0 MiB)
sessions  14 root, 0 subagent, 8 agent loop(s) executing
listing   list_agents cache 3000 ms TTL: 1 scan(s), 0 hits, 0 coalesced, 0 deadline(s) (last scan 1172 ms)
governor  2 of 24 heavy slot(s) leased, 22 free, 0 waiting
```

Two facts worth extracting: the health surface **is live on the owner's engine** (the plugin-health restart
that `90-plugin-health-governor.md:196-202` was waiting on has happened), and **8 generating turns were live
at that moment with 6 tool runners holding 251.9 MiB** — which is the empirical version of §3.6.

**MEASURED 2026-09-16 ~20:1x, read-only over SSH:**

```
$ ssh secratary-ts "hostname; nproc; free -m; df -h /"
secratary
4                                  # cores
Mem: 23421 total, 6017 used, 985 free, 18505 buff/cache, 17404 available
/dev/mapper/ubuntu--vg-ubuntu--lv  467G  263G  185G  59% /
```

**`secratary` — the authority — has 4 cores and 23.4 GB RAM.** It is the right place for the *control plane*
and the wrong place for parallel agent work. That is a measured constraint on §5, not a preference.

---

## 2. The placement model: four options, evaluated

The unit that can be placed is **not** a session. It is **outbound work**: a subagent turn, a fleet of
worktrees, a build. Sessions follow the client; work is placed. Every option below is judged on four
questions: what does it require, what does it cost, what does it break, and what does it do to the laptop.

### (a) One engine per node, client connects to whichever node holds the session

**What it requires.** A `DSH_HOME` per node (already true). A way for the browser to reach that node's
loopback engine. DSH refuses `--host 0.0.0.0` **on purpose** —
`dsh-web-app/lib/startup.js:40`: *"it would expose remote code execution to the network; use 127.0.0.1
instead"* — and the webserver schema is `127.0.0.1 | 0.0.0.0` (`dsh-host-webserver/lib/index.js:141`), so the
CLI check is the only thing stopping it. The supported door is a **reverse proxy that preserves `Host`** plus
`--trusted-host <authority>` (READ, `dsh-client-connection/lib/index.js:22, 188-215, 386-425`).

**Cost.** Zero engine changes and no new code. One `tailscale serve --bg <port>` per node
(READ, `scripts/serve-phone.ps1:90`; `scripts/serve-phone.sh:236`). The auth model already carries across:
MEASURED by experiment in `docs/dsh-mobile/00-RESEARCH.md:80-90` — a trusted non-loopback authority **can**
complete the `?token=` exchange, the cookie is minted *for that authority* (`{"authority":"dsh.test"}`), the
authenticated API answers on it, an untrusted Host is **403 even with a valid cookie**, and the same cookie on
another authority is **401**.

**What breaks.** Two things, both real:
1. **A session's "current session" is per origin, and there is no URL that selects a session.** So opening a
   node's URL shows *that node's* session list and the last session that origin had selected — probably not the
   one you meant. Mitigation and the one minimal client change: §3.
2. **The `serve-phone.ps1` / `serve-phone.sh` shapes disagree with each other, and one of them is wrong.**
   The Windows script documents starting a *"DEDICATED"* engine that *"shares DSH_HOME, so it is the same
   agent"* (`serve-phone.ps1:16-18`) — that is the one-writer violation, from §1.1. The Linux script does
   something better and more subtle: it runs an engine **behind a gate** on its own ports
   (`serve-phone.sh:22-23` — `PORT=3086` publishes the gate, `ENGINE_PORT=3089` is the engine), and the live
   server proves it: `phone-gate.service` listens on `3086` and relays to `3089`, one engine, one `DSH_HOME`
   (§1.0). **PROPOSED: the Windows scripts converge on the Linux shape** — a gate in front, and no second
   engine against a home that already has one.
3. **`--trusted-host` is a startup flag, so fixing this means one engine restart per node.** That is why §7's
   D3 bakes the authority into the launcher and syncs it from the repo rather than passing it ad hoc.

**Verdict: this is the spine.** It is the only option that needs no new code, no new dependency, and no
assumption about the network beyond Tailscale, which is already the only path between the two buildings — and
**it is already running on `secratary`, verified by a 15-check probe on a 5-minute cron** (§1.0).

### (b) A headless worker node — runs engines, no GUI

**What it requires.** Nothing new: *every* engine is already headless in the sense that matters. The GUI is a
browser on some machine; the engine is a server on the node (`dsh-host-webserver` serves routes, and the
"window" is just a browser attached to a port — READ, `10-dsh-source-audit.md:366-377`). `secratary` already
runs engines for the phone this way (READ, `scripts/serve-phone.sh:296`).

**Cost, and the trap.** The trap is that "headless" in DSH's own vocabulary means a **different, weaker agent**:
`dsh --profile headless`, `--profile sdk` and `--profile acp` do **not mount `agent-presets`**, so the `zabz`
persona, the toolbelt and the MCP bridges are all absent — READ, `docs/dsh-mobile/00-RESEARCH.md:148-158`.
**So "headless worker node" must mean `--profile web` on a box with no display, never `--profile headless`.**

**What breaks.** Only that a worker node with no Serve entry cannot be *watched* from a phone; it can still be
driven from another engine's session by ordinary means (§2c), or watched via the same Serve trick.

**Verdict: adopted, but only in the corrected sense** — a node whose role is *work* rather than *display*, still
running `--profile web`. It is a role, not a build variant.

### (c) Driving other nodes through SSH from one engine

**What it requires.** An ssh tool call, which works and is already proven for the MCP bridge (READ,
`presets/zabz/agent.cordis.yml` via `10-dsh-source-audit.md:282`; the Linux-side row at
`docs/dsh-mobile/01-DESIGN-AND-PLAN.md:194`).

**Cost — three, and they compound.** (i) Each `ssh` is a **tool call on the origin node**, so it costs the
origin's commit ~160 MB and serialises against every other tool call in that step (§1.5) — you pay the
laptop's scarcest resource to avoid using it. (ii) The remote process is unreachable to the origin's Job
object, so the origin's `TerminateJobObject` guarantee does not extend to it (READ, `10-dsh-source-audit.md:52-63`).
(iii) **The session stays on the origin while the work runs on the remote node**, so the durable record of the
work and the work itself are on different machines — exactly the failure §5 is about.

**What breaks.** Long remote work does not survive the laptop sleeping, closing, or losing Tailscale. There is
no resumption, because nothing on the remote node knows a session owns the work.

**Verdict: kept for one purpose only** — *launching* a broker-placed job on another node (§6), never for the
work itself, and never as the placement mechanism.

### (d) A broker/scheduler node that owns placement decisions

**What it requires.** A node that is always on, reachable by every other node, and able to answer in bounded
time: a capacity registry, a queue with positions, and leases. `secratary` is the only always-on node in the
roster and it already hosts the authoritative database.

**Cost.** New code (§8 Phase 3). One new dependency: the broker must be reachable from the **home** network,
and home↔office is Tailscale only.

**What breaks if the broker is the *engine*.** Everything. But it is not: **the broker decides placement; it
does not run sessions.** With that boundary the failure mode is benign and is specified in §6.

**Verdict: adopted as a thin layer over (a), and never as a replacement for it.**

### The recommendation

**Spine: (a) one engine per node, one `DSH_HOME` per node, sessions that never move.** Each node that has an
engine whose sessions the owner may want reaches it through a `tailscale serve` publication of that engine's
**existing** loopback port with `--trusted-host <that node>.tail93e6e6.ts.net`; the client then works from the
laptop, the desktop homepage, or the iPhone with no client change, because the client's WebSocket is derived
from the page's own origin (§1.3). **A second engine on the same home is removed, not explained away** (§2a).

**Additions: (b) as a role, (c) as a launcher, (d) as a control plane** — a node running `--profile web` with
no display is a worker node; the broker launches work on other nodes rather than executing it through SSH; and
the broker is a decision service, never a session holder.

**Why the losers lose.** `(b)`-as-`--profile headless` gives you an agent with no toolbelt and no persona —
a second, weaker "me" wearing the same name, which is the exact failure the whole audit series exists to kill
(`docs/dsh-mobile/00-RESEARCH.md:232-233`). `(c)` as the general mechanism puts the laptop's scarcest resource
in the critical path of work meant to avoid the laptop, and splits a job from its durable record. `(d)` as an
engine host puts sessions on a 4-core, 23.4 GB box and makes the whole mesh depend on it being awake — the
opposite of the goal.

---

## 3. Session affinity and the UI

### 3.1 How a session gets opened from the laptop, the desktop, or the iPhone

**Exactly what must be true** — this list is exhaustive, and each item is READ from source:

1. **The node's engine is running and listening on loopback.** Its port is node-local; today the owner's is
   `3099` (`multi-window/windows.json:15`).
2. **`tailscale serve --bg <port>` is enabled on that node**, so `https://<node>.tail93e6e6.ts.net/` terminates
   TLS there and proxies to `127.0.0.1:<port>` **preserving `Host`** (READ, `serve-phone.ps1:90`,
   `serve-phone.sh:236, 267`).
3. **The engine was started with `--trusted-host <that exact authority>`**, or every `/api` request is **403**
   by the Host/Origin fence (READ, `dsh-client-connection/lib/index.js:201-215`, `:554`). `--trusted-host` is
   a **startup** setting: changing it means restarting the engine, which ends every live session — this is why
   `serve-phone.ps1:16-18` used a dedicated engine, and why §7 argues the fixed ordering instead.
4. **One token exchange per origin**, done once: open
   `https://<node>.tail93e6e6.ts.net/?token=<the launch token>`. The token comes from the engine's own stdout
   line, captured to a log by the launcher (READ, `serve-phone.ps1:70, 118`); it is **never written to disk by
   the app itself** (READ, `docs/multi-window/research-session-urls.md:490-498`). The exchange requires `GET`,
   `pathname === "/"`, exactly **one** `token` parameter, and a Host that passes the fence; on success it
   answers **303 → `/`** with `set-cookie: dsh-auth-<sha256(authority)>=…; HttpOnly; SameSite=Strict;
   Max-Age=30d` (READ, `dsh-client-connection/lib/index.js:386-425`).
5. **Nothing else.** The WebSocket is `/api/remote.mux` on the page's own origin (READ, §1.3), so there is no
   second hostname to configure.

**Consequences that follow, and one that does not:**

- **Each origin is its own world.** The cookie is bound to that authority and *worthless on another*
  (MEASURED experiment, `00-RESEARCH.md:87`). So the iPhone needs **one token exchange per node-URL** it will
  use, and then 30 days of plain URLs. There is no method-specific loopback tier and no trusted-network tier
  (READ, `00-RESEARCH.md:69`).
- **iOS Safari is the client-side trap, MEASURED elsewhere:** the renderer is suspended and TCP dropped after
  **~5 s in the background**, and an `EventSource` you closed deliberately will not resume via
  `Last-Event-ID` (`00-RESEARCH.md:251`). **Design rule: all work is server-side and the client is a viewer
  that reconnects.** A turn that is running when the phone is pocketed must keep running — and it does, because
  the engine is not the phone.
- **Serve on the tailnet is not the same as Serve on the hostname you type.** A missing tailnet ACL grant for
  tcp/443 fails *silently as a timeout* (`00-RESEARCH.md:248`). Any "the phone is broken" report is checked
  with `tailscale serve status` first (READ, `serve-phone.sh:259-264` — the script refuses to print a link
  until serve status proves it).

### 3.2 A window cannot be deep-linked to a session — what that means, and the minimal fix

**MEASURED/PRIOR-MEASURED exhaustively** in `docs/multi-window/research-session-urls.md`: zero
`pushState`/`replaceState`/`popstate`/`hashchange`/`location.hash` across all 65 client bundles; `sessionId`
appears **zero** times in the shell bundle; the server matches **pathname only**
(`dsh-host-webserver/lib/index.js:231`); the static fallback serves `index.html` **only at `/`**, so
`/session/<id>` is a **404** (verified live, `:122-123`); and the `?token=` exchange 303s to the literal `/`,
**discarding every other query parameter** (`:138-141`). Session selection lives in
`localStorage["dsh.sessions.current"]`, read **once, at page load** (READ, `dsh-api-session-controller/lib/client.js:3058-3060`).

**What that means, concretely, for "open my session on another machine":**

- Landing on a node's URL opens *whatever that origin last selected*, which for a freshly-used device is
  usually the wrong session. The fallback is always a **click** in that node's session list.
- Two windows on one origin cannot be independently restored to two sessions; different ports **are**
  different origins and therefore have no such conflict (PRIOR-MEASURED, `research-session-urls.md:480-483`).

**The minimal client-side change that fixes it (PROPOSED).** Three routes were rejected in that earlier
research, and the reasoning holds: a **path** route is a 404 because there is no SPA catch-all; a **query**
parameter cannot survive, because the token exchange strips the query; therefore the only position that
reaches the client unmodified is the **`#` fragment**. Nothing reads `location.hash` today —
`location\.hash` count **0**, `pushState` **0**, `popstate` **0** across all 65 client bundles and the shell
bundle (READ, `research-session-urls.md:53-65`; conclusion restated at `:513-517`) — so the fragment is free.

> **PROPOSED, and it is one new client plugin.** In the repo pattern that already exists
> (`packages/plugin-health`, loaded through the web profile's bundle list —
> `docs/dsh-at-scale/90-plugin-health-governor.md:36-58`): at client boot, read a
> `#session=<id>` fragment (or a 1-byte marker in the fragment path), wait for the session controller to be
> available and for the id to appear in the projected list, then call the same **`ClientSessions.open(id)`**
> the UI itself calls (READ, `dsh-api-session-controller/lib/client.js:3093-3095`), and clear the fragment.
> Retry with backoff while the list is loading; if the id never appears, leave the user on the default with a
> one-line notice rather than a blank window. ~30 lines.

With that in place, every artefact this mesh produces can be *addressed*: a journal handoff can name
`https://zabz-tech.tail93e6e6.ts.net/#session=<id>`, and the owner clicking that link lands on the right
conversation on the right node from any device. **Without it, "the same you everywhere" is a click away on
every device, every time** — and that is the difference between a mesh and four machines.

**Note for the record:** a DSH window cannot be pointed at a session *by URL*, but it **can** be pointed at a
session *by origin* (`dsh.sessions.current` on a distinct port), which is what `multi-window` already exploits
(`research-session-urls.md:443`). Neither substitutes for a real session URL when the session lives on a
different machine.

### 3.3 The pattern to generalise: a per-node gate, proven on `secratary`

Remote access does **not** need to be designed. It has been built, and it is worth being precise about what it
does, because the mesh version is the same component pointed at more nodes.

`scripts/phone-gate.py` is **a raw TCP relay, not an HTTP proxy** — deliberately, so that the WebSocket upgrade
survives untouched (`phone-gate.py:15`). It does four things and nothing else
(`docs/dsh-mobile/02-SYSTEMS.md:74-76`):

1. **Signs a cold visitor in, in flight.** The problem it solves is measured, 2026-09-11: DSH authenticates with
   a one-time `?token=` on `GET /` **only**, so a first-time visitor who reaches the root without it — a typed
   address, a restored tab, a phone home-screen icon — gets a 401 and a dead page (`phone-gate.py:4-13`). The
   gate reads the live token from the engine's own log at request time (so it survives engine restarts,
   `:19, 55-76`) and **performs the exchange itself**: ask the engine for the document with the token, keep the
   session cookie the engine hands back, fetch the document with that cookie, and return it to the client with
   `Set-Cookie` injected (`:194-245`). The client never sees a token in its URL or its history, **and no
   redirect loop is constructible** — the naive `302 → /?token=` shape was measured looping 50 hops to an abort
   (`:198-205`).
2. **Injects the client layer under the client's own control.** A mobile stylesheet and the
   `dsh-plugin-mobile` / `dsh-plugin-cost` links are injected before `</head>`, and the document is marked
   `Cache-Control: no-store`, because a document served from the client's own cache carries no layer at all
   (`:83-86, 631-653`). **This is the mechanism that makes "the same client everywhere" a per-node decision
   rather than a package fork**, and it is also the mount point for the §3.2 fragment reader.
3. **Relays `/api` and the WebSocket byte-for-byte**, so nothing about the RPC protocol or the mux is
   reimplemented.
4. **Refuses a foreign `Host`** and leaves the upgrade case alone (`:711-727`), so the fence from §3.1 is not
   weakened by the extra hop.

**PROPOSED: this is the unit of mesh remote access.** One gate per node, in front of that node's one engine, and
`tailscale serve` publishes **the gate** (as it does today — `serve status` → `:3086`, and the gate relays to
`:3089`). Each node then has exactly one publishable URL, one cold-visitor path that works from a phone without
a token in the URL, and one place to hang the per-device client layer. **Nothing about this needs new
research — it needs `serve-phone.py` renamed in spirit and pointed at each node's own ports.**

**And it composes with §5:** the gate is also the natural place to surface *which node you are on*. A device
that lands on the wrong node today gets a 401-free page showing that node's sessions; with the vocabulary of
§3.2 it can be told, in one line, "this is `zabz-yoga`; the session you asked for lives on `zabz-tech`" and
handed the link — which is the difference between a mesh and a redirect puzzle.

---

## 4. The queue, not a cap

### 4.1 Two layers, deliberately separate

| layer | question | answer shapes | where the rules live today |
|---|---|---|---|
| **Admission** | *can this host afford it right now?* | `GRANTED` / `QUEUED position N` | **built and proven** — `packages/plugin-health/lib/governor.js` |
| **Placement** | *which node should run it?* | `PLACED <node>` / `QUEUED position N` | **does not exist** — this section proposes it |

They compose in that order: **place first, admit second.** A job is offered to a node, and the node's own
governor answers whether it can take a slot *now*. A node that answers `QUEUED` is not a failure — the job
stays in the mesh queue and the next offer goes to the next node. Nothing is ever refused at either layer;
that is the owner's rule, already encoded in the governor's floor (`governor.js:63-71, 223`).

The distinction the governor already makes is the one to preserve: **a granted slot means a process is in
flight and is holding memory; a waiter holds nothing.** That is why position is *computed* rather than stored
(`governor.js:37-39`) — the same rule must hold mesh-wide.

### 4.2 What each node advertises

The capacity surface **already exists and is live** on the owner's engine (`/healthz`, MEASURED §1.6). The
fields a placement decision needs are a subset of it and need no new instrumentation:

| field | source in the live payload | why placement needs it |
|---|---|---|
| `system.physicalAvailableBytes`, `system.probe.commit*` | `/healthz` | the true scarcity (§1.4) |
| `system.cpus`, `load1` | `/healthz` | CPU headroom; a 4-core authority is not a worker |
| `processes.toolCallRunnerProcesses` (+ MiB) | `/healthz` | the 160 MB multiplier, counted directly |
| `sessions.agentLoopsRunning` | `/healthz` | **the real unit of cost — a generation, not a window** |
| `loop.lag.p95/p95Max` | `/healthz` | a node that is already stuttering should not be offered more |
| `governor.inUse/free/waiting` (+ the published arithmetic) | `/healthz` | the node's own admission answer, verbatim |
| `listing.listAgents.lastScanMs` | `/healthz` | a surrogate for filesystem pressure — a 430-file corpus makes this a load signal |
| disk headroom on the worktree volume | **not yet present** | the 1,596 % disk-time finding says this is a first-class resource, not an afterthought `[corrected 2026-09-16: the finding is real and this field is still missing; the figure is 97.31 % measured, not 1,596 %.]` |

**PROPOSED, the one missing field:** disk headroom (free bytes *and* a recent commit/IO stall indicator) on
each volume that can host a worktree. Without it, placement reasons about memory only and reintroduces the
measured disk collapse (`docs/parallel-agent-orchestration.md`, disk finding).

### 4.3 Where the state lives — one source of truth

**The authority's SQLite is the single source of truth for placement, and nothing else is.**

**And the node-fact half of it already exists** — this is the most useful finding of the read-only audit
behind this document. `personal-secretary-mvp/app/services/next_stage_runtime.py` already defines
`next_stage_node_reports` (`:173-185`, PK `source_machine`, with `source_role`, `os_family`, `hostname`,
`uptime`, `disk_json`, `services_json`, `repos_json`, `peers_json`, `reported_at`) and
`next_stage_machine_access_checks` (`:156-167`), and `app/autopilot.py:3827-3831` already aggregates them into
`~/.personal-secretary/mesh-health.json` (`app/assistant_chat.py:2625-2641`). **So a node-report channel
exists and is populated; the placement queue extends it rather than inventing a parallel source of truth.**
A mesh-wide `CREATE TABLE` grep found **no** lease, heartbeat, capacity, placement, scheduler or node-registry
table — so the *queue* is genuinely new work, and the *registry* is not.

```
canonical:  secratary  →  the authoritative SQLite   (owner's standing rule: the authority is authoritative)
            · EXTEND next_stage_node_reports with the §4.2 capacity fields  (PROPOSED — a column add, not a table)
            · ADD a jobs/leases table keyed by job_id                       (PROPOSED — genuinely new)
local:      <DSH_HOME>/governor/  →  the node's own admission leases (unchanged, per-node, correct as-is)
local:      <DSH_HOME>/mesh/queue.jsonl  →  PROPOSED append-only intent log for authority-unreachable play
```

**Why the authority and not one of the workstations:** it is the only always-on node, and the owner's own rule
is that the authoritative store is the authority. **Why it is safe despite being tiny:** placement is a few rows
per second and one query — measured here, `secratary` has 4 cores and 17.4 GB available (§1.6), which is ample
for a control plane and hopeless for a fleet. The two roles must not be confused (D4).

**PROPOSED table (shape only — the authoritative store is `secratary`'s; the mirror is
`journal/state/in-flight.md` for humans):**

| column | meaning |
|---|---|
| `job_id` | idempotency key, minted by the requester |
| `kind`, `payload_ref` | what to run; a **reference** (repo + branch + brief path), never the payload inline |
| `origin_node`, `session_id` | who asked, and which session owns the result — this is the durable link (§5) |
| `state` | `queued` / `offered` / `running` / `done` / `failed` / `orphaned` |
| `assigned_node`, `lease_expires_at`, `heartbeat_at` | the lease, with a **heartbeat, not a pid** (`governor.js:27-31`) |
| `position_seq` | monotonic; position is `COUNT(*) WHERE state='queued' AND seq < mine` — **computed, not stored** |
| `attempt`, `worktree`, `branch`, `base_commit` | where the work is, so a second attempt can resume it |
| `evidence` | path to the journal entry + the command that will prove done |

**Reboot, sleep and unreachability — specified, because "the node is gone" is the normal case, not the
exception:**

- **Node asleep.** It is not a candidate (its `heartbeat_at` ages out). A job **already running** there is
  unaffected — the engine keeps working while the screen is off — but it cannot be *offered* anything new.
  A **session** bound to it is unreachable from the phone until it wakes, and that is honest: the session list
  on the phone is served by the node the phone is connected to, and this node is not answering.
- **Node unreachable** (Tailscale down, LAN moved). Identical to asleep from the mesh's point of view, with one
  extra check: `scripts/ensure-mesh-prereqs.ps1:91-93` treats a stopped Tailscale as a first-class finding,
  because *"a stopped Tailscale on one node makes every MagicDNS name fail and reads as 'the other machine is
  down'"* (`scripts/mesh-prereqs.json:2`). **The mesh must not mistake one for the other** — report
  `unreachable` and the reason, not `failed`.
- **Node reboots mid-job.** The lease expires (heartbeat), the broker marks the row `orphaned`, and the job
  **returns to the queue with its position recomputed** — never silently dropped, never auto-retried twice on
  the same node. Recovery details are §5.
- **The authority itself is down.** Placement degrades to *local-only*: each node falls back to its own
  `mesh/queue.jsonl` + local governor, and appends a reconcile record naming what it did while blind. It never
  invents a position and never drops a job. **PROPOSED.** The alternative — blocking until the authority
  answers — would make a 4-core server a single point of failure for the entire mesh, which §2(d) rules out.

### 4.4 The minimal protocol

Four verbs, over the Surface the mesh already has (Tailscale + HTTP), and **no new daemon on the client**.
**PROPOSED:**

```
PUBLISH  node → authority     capacity advertisement: the §4.2 fields + heartbeat_at + hostname
                              every 15 s; a node is a candidate if heartbeat_at < 60 s old
PLACE    requester → authority  {job_id, kind, needs:{disk_gb, ram_gb, cores, repo}, brief_ref, origin_node, session_id}
                              → {state: PLACED node, lease_id} | {state: QUEUED, position: N}
OFFER    authority → node      {job_id, lease_id, ttl}   (the node's own governor answers GRANTED/QUEUED)
COMPLETE node → authority      {job_id, outcome, evidence_ref} + release the lease
```

**The placement function is deliberately dumb, and that is a feature.** Filter by hard needs (repo present,
disk headroom, cores), then rank surviving candidates by measured headroom *relative to the job's declared
footprint*, then break ties by a **stable, published order** (never by "least recently used" and never by a
random draw — a scheduler whose choice cannot be predicted cannot be debugged). Position is computed by
`position_seq` (§4.3). **No verb in this protocol returns a refusal; the only two answers are PLACED and
QUEUED.** That is the owner's rule made structural, exactly as the governor already does it
(`90-plugin-health-governor.md:220-223`).

**Why a queue and not a bigger cap** — the program's own words, and they are the owner's:
*"Where a limit was genuinely needed, the shape chosen is a queue, never a smaller cap on what an agent may
do"* (`docs/dsh-at-scale/PROGRAM.md:11`). Placement adds nodes rather than subtracting work.

---

## 5. Failure and recovery

### 5.1 A job's node dies mid-turn — the four questions, answered separately

| what | what happens | why, and the evidence |
|---|---|---|
| **The session** | **Survives on that node**, and reopens cleanly when the node comes back. A reboot does not lose a history. | The log is an append-only file of independent zstd frames with a checksummed header, and **a torn final frame is a normal crash boundary, not corruption** — READ, `docs/dsh-mobile/00-RESEARCH.md:131-139`. The write lease is a **kernel** object released when the process dies — READ, `dsh-session-persistence-jsonl/lib/index.js:619-624` — so *"a crashed holder never blocks a successor"*. |
| **The files it was editing** | **At risk for the last few writes, recoverable in git for everything committed.** The worktree is node-local and dies with the node's disk (§1.2). | A worktree shares the repo's object database, so the branch outlives the working tree — READ, `docs/parallel-agent-orchestration.md:71, 186-188`. Anything only in the working tree and not committed is gone; that is why §5.2 exists. |
| **The queue entry** | The **lease** is what dies, not the job. `heartbeat_at` ages past the TTL, the broker marks the row `orphaned`, and the job returns to `queued` with its position recomputed. | The heartbeat-not-pid rule exists precisely so a dead holder is detected without guessing — READ, `packages/plugin-health/lib/governor.js:27-31`; reaping is guarded by an **atomic rename** so exactly one reaper wins and a holder that renewed in the meantime is *renamed back* (`:32-36`). |
| **The requester** | The session that asked is **still there**, on its own node, waiting. It learns the outcome from the broker, not from a dead SSH pipe. | Sessions never move (§1.2); placement is a reference, not a transport (§2c). |

### 5.2 What must be written down before work starts

**One artefact, written *before* the first token is spent, in the one store that is replicated across nodes
(the journal in `harness-config`, synced every 15 minutes — READ, `docs/dsh-mobile/00-RESEARCH.md:270-279`):**

```
journal.py append handoff --title "fleet <job_id>: <what>"
  CHANGED   nothing yet (intent record)
  IN FLIGHT job_id, kind, ORIGIN NODE, session_id (the durable link back to the conversation)
            worktree path on the assigned node, branch name, BASE COMMIT sha
            brief path + the checkable definition of done
            assigned node, lease_id, attempt number
  BROKEN    (empty at start — filled by the failure)
  NEXT      the exact command that will prove it done
  EVIDENCE  path to the brief; the branch; the base commit
```

**Three properties make this the recovery mechanism rather than a diary:**

1. It is written **before** the work, so a node that dies with no further output is still accountable.
2. It is in **git**, so it exists on every node (and on the authority) within 15 minutes — unlike the session
   log, the worktree, or the governor's lease directory, which are all node-local.
3. It carries the **branch and base commit**, which is the only thing an operator needs to salvage an
   interrupted job of work: `git fetch && git checkout <branch>` on any node, or
   `git cherry-pick <sha>` if the branch was never pushed (`scripts/autosync.ps1:263` shows the existing
   recovery idiom).

**And the conversation survives on its own node.** The board is not the record: `push-dsh-sessions.mjs` ships
every session's events from every machine into the authority as **plain JSON with its own cursor and
`source_machine`**, on an hourly task (`scripts/push-dsh-sessions.mjs:3-6, 60-62, 102, 380`) — the DSH-side
twin of the already-proven VS Code pipeline (`docs/dsh-mobile/00-RESEARCH.md:181-194`). So after a disaster the
*record of what was asked and answered* is on the authority. **The session archive is evidence; the live
session is the session. Do not confuse them** — the archive cannot be resumed, replayed into a live engine, or
used to answer `session/list` on a second node.

### 5.3 The two recovery moves, written out

1. **Salvage the work on another node.** `git fetch` the branch (works whenever the assigned node pushed, or
   the side-ref rescue in `autosync.ps1:280-306` ran); cut a **fresh** worktree on the new node; the brief and
   the definition of done come from the journal entry, not from the dead node's disk.
2. **Reopen the conversation.** Go to the dead node's served origin (that is its own URL, and the session is
   on its disk), or restore the log from the authority's archive and open it on that node. The second path is
   the only one that works if the dead node's disk is *lost* — and it is a restore, not a resume: the session
   log is a plain append-only file, so it is a copy-back, not a replay. **PROPOSED, and explicitly out of scope
   for this document:** an automated restore path. It is worth building only after the queue exists.

---

## 6. What the owner gets, in numbers

A realistic mix: **one interactive chat** he is typing into, **a 6-agent fleet** building something, and
**one build**. Shown in the recommended design, then in the loser (everything on the laptop), so the
difference is arithmetic rather than adjective.

### 6.1 Measured constants used

| constant | value | provenance |
|---|---|---|
| one generating turn | **0.81 GB commit, ~1 core** | PRIOR-MEASURED, `PROGRAM.md:75` `[corrected 2026-09-16: the ~1 core survives; the 0.81 GB does NOT. Measured on this laptop: ≈18 GB of commit is resident before any work and each further node process costs ≈0.58 GB (r = 0.937 over 477 samples). This is the input every row below is derived from, so treat all of §6.3 as PROVISIONAL until it is re-derived. Source: 60-verification.md §2.2.]` |
| one shell tool call in flight | **160 MB, ~2 processes** | PRIOR-MEASURED, `10-dsh-source-audit.md:63-65`; governor constant `governor.js:53` |
| a browser window | **325–566 MB private** (lean flags) | PRIOR-MEASURED, `PROGRAM.md:75` |
| an idle browser window | ~0.25 core | PRIOR-MEASURED, `PERFORMANCE-MEASURED.md:168-171` |
| `list_agents` on the live corpus | **1,172 ms** for one scan (430 files / 237.5 MB) | MEASURED §1.6, and the 3000 ms TTL cache is live `[corrected 2026-09-16: the corpus is 444 files / 255,137,162 B (243.3 MiB) as measured, and 430/237.5 arrives from `30-truth-and-disk.md:18`'s 436/251,054,028 — three mutually exclusive figures, all claiming MEASURED. Use "≈250 MB corpus" and re-measure the scan. Source: 60-verification.md §1.3.]` |
| `ZABZ-YOGA` budget | commit limit 44,149 MiB; 26,335 MiB free at idle-ish; **phys avail 17,575 MiB** | MEASURED §1.6 `[corrected 2026-09-16: this whole row is ONE `/healthz` reading at 20:10Z, not a constant. The commit limit measured now is **43.11 GiB** (= 31.61 GiB RAM + 11,776 MB pagefile, exactly), and it MOVES because `AutomaticManagedPagefile=True`. Read it at call time; never hard-code it. Source: 60-verification.md §1.2.]` |
| `secratary` | **4 cores, 23.4 GB RAM, 17,404 MB available** | MEASURED §1.6 `[corrected 2026-09-16: the 17,404 MB is a transient reading of free memory, NOT headroom above a resident floor. With ≈18 GB already committed on a loaded node, 23.4 − 18 ≈ 5 GB of real headroom, and its **4 cores** are the binding limit regardless. Do not size anything on the 17,404 MB.]` |
| `ZABZ-TECH` | **24c/32t, 63.6 GB (MEASURED §1.0)**; commit 44.5 GB / ~19.1 GB headroom (**PRIOR-MEASURED**, `PROGRAM.md:76`) | MEASURED (shape) + PRIOR-MEASURED (headroom) `[corrected 2026-09-16: the header above says "Measured constants used". This row is explicitly PRIOR-MEASURED — §0 of this document (`:29–32`) says its headroom "was NOT measured" — so the header is a provenance error in the one place this document promises provenance. Nothing on ZABZ-TECH was re-measured in this wave. Source: 60-verification.md §3 C10.]` |
| `zabz-tech-linux` | **12 cores (i5-11400), 11.7 GB** — MEASURED §1.0 | MEASURED `[corrected 2026-09-16: this is the same machine `40-hardware-costs.md` describes as 6 c/12 t, and `10-inventory.md:439` as `nproc -> 12`. 12 logical / 6 physical. State which one is meant wherever it is used; the core count is the binding figure and the two differ by 2×.]` |
| `LakewooechsMini` | 10 cores (M4), 16 GB, **17 GB disk free** — an employee machine, and nearly full | MEASURED §1.0 |

### 6.2 Where each piece lands

| piece | node | commit | cores |
|---|---|---|---|
| **interactive chat** — your session, your tool calls | **the laptop you are holding** | 0.81 GB + tool calls ≤ 20 × 160 MB = 3.2 GB worst case, **typically 1–2 in flight = ~1.1 GB** | ~1.0 |
| **the 6-agent fleet** (subagents are **not processes** — `10-dsh-source-audit.md:28`) | **a worker node — `ZABZ-TECH`** | 6 × 0.81 GB = **4.86 GB** | ~6.0 |
| the fleet's shell calls (say 6 concurrent, one per agent) | same worker node | 6 × 160 MB = **0.96 GB** | ~1.0 |
| **the build** | the worker node too (it holds the worktree), or a third node if one exists | 1.5–4 GB depending on toolchain | 2–8 |
| **the browser windows** | **the laptop** — they are display, not work | 4 windows × ~450 MB = **1.8 GB** | ~1.0 idle |
| **the mesh control plane** (heartbeats, queue, placement) | `secratary` | ~negligible; it is 3 rows/s and a query | ≪0.1 |

### 6.3 The arithmetic, both ways

**Recommended (work placed away from the laptop).**

```
ZABZ-YOGA  commit   = engine 0.74 GB (MEASURED rss 743.5 MiB) + 1 chat turn 0.81 GB
                    + tool calls say 6 × 0.16 GB = 0.96 GB + 4 windows ~1.8 GB
                    = 4.3 GB of the machine's own budget
           physical = 17,575 MiB available, minus 4.3 GB ≈ 13.2 GB still free
           CPU      = 1.0 (chat) + 1.0 (windows, idle) ≈ 2.0 of 22 cores
           loop lag = p95 16 ms with 8 generating turns live, measured (§1.6)

ZABZ-TECH  commit   = 6 fleet turns 4.86 GB + fleet shells 0.96 GB + build ~3 GB ≈ 8.8 GB
           physical = ~19.1 GB headroom → ~10 GB left
           verdict  = fits with room, and that is the whole point of a 64 GB box
```

**The loser (everything on the laptop — today's default, because every session starts on the node the client
is attached to).**

```
ZABZ-YOGA  commit   = 0.74 engine + 1 chat 0.81 + 6 fleet 4.86 + fleet shells 0.96
                    + build ~3 + 1.8 windows  =  12.2 GB of commit of NEW demand
           physical = 17,575 MiB available against ~12 GB of new demand, i.e. it survives
                    — and that is exactly why this is a PLACEMENT problem and not a
                    "buy more RAM" problem. The laptop CAN run it; it just stops being
                    the machine he is holding and becomes the machine that is working
           CPU      = ~1 + 6 + 2..8 = **9–15 of 22 cores**, and the event loop already
                    measured 706 ms max lag under load (MEASURED §1.6)
           disk     = the measured failure mode: 1,596 % disk time when builds + indexers
                    + agents ran together — and the zstd decompress into `list_agents`
                    is SYNCHRONOUS on that same loop (READ,
                    `dsh-session-persistence-jsonl/lib/index.js:1263` `zstdDecompressSync`),
                    which on this node's 237.5 MB corpus measured 1,172 ms for one scan (§1.6)

CONTEXT, so the two columns are comparable: the same engine measured 26,334 MiB of
commit still free of a 44,149 MiB limit while 8 agent loops and 6 tool runners were
live (§1.6). The design's whole job is to keep that reading looking like that while
the fleet runs somewhere else.
```

> `[corrected 2026-09-16 — this whole block is a DERIVATION from the refuted 0.81 GB/turn constant, so it is
> retained as the original argument but must not be quoted as a measurement. What the machine's own sampler
> record does support: idle commit floor ≈17–18.4 GB; ≈0.58 GB per extra node process (r = 0.937); peak
> observed commit 36.49 GB at 58 node processes with 62,865 page-ins/s; and **commit has never exceeded the
> 43.11 GiB limit**, so "the laptop CAN run it" is right for the wrong reason — the laptop does not run out of
> commit, it pages under disk pressure. The disk line: 1,596 % is not a possible reading of the counter it is
> attributed to (one disk); the measured figure is 97.31 % average, and the corpus is ≈243–255 MB, not
> 237.5 MB. The "26,334 MiB free of 44,149 MiB" reading is one `/healthz` snapshot at 20:10Z; the limit today
> is 43.11 GiB and it moves. Source: 60-verification.md §1.2, §1.3, §1.5, §2.2.]`

**The difference is not "the laptop is a bit slower".** The recommended plan leaves ~13 GB of physical headroom
and 20 free cores on the machine he is holding; the loser spends 9–15 cores of it and pushes commit toward the
paging tripwire — the tripwire being *the* thing that makes the machine feel broken
(`PERFORMANCE-MEASURED.md:181-185`).

**And the number that matters most is the one the design *creates*:** with placement, the fleet costs the
laptop **zero**, and the owner's own words are *"speeding fast"*, not *"a bit faster"*. **A 6-agent fleet on
the laptop is not a tuning problem. It is a placement problem, and placement is the only fix that costs the
laptop nothing.**

### 6.4 The honest caveat

The fleet does not place itself. **A session is created on the node the client is attached to, so an agent
that fans out a fleet today fans it out locally** — which is exactly the loser's column. That is why §8 Phase
3 (placement in the kernel, `docs/dsh-at-scale/PROGRAM.md` style) is not optional polish; it is the load-bearing
change. Until it exists, fan-out stays a human decision ("run this one on the desktop"), and the numbers above
are what that decision is worth.

---

## 7. Decisions taken here, and why (dev decisions — recorded, not escalated)

The owner's rule (`docs/dsh-at-scale` program and the standing instruction) is that development decisions are
mine to take and record. These are taken.

| # | decision | why | alternative rejected |
|---|---|---|---|
| D1 | **Sessions do not move. Placement moves work.** | The session log, its lease and its "current session" pointer are all node-local by construction (§1.2), and the write lease is deliberately non-expropriable across hosts. | Replicating `~/.dsh/sessions` between nodes: no shipped mechanism, and a network-share `DSH_HOME` breaks atomic rename/fsync/single-writer assumptions the persistence layer is built on. |
| D2 | **One engine per `DSH_HOME`, always — and the correct remote shape is a *gate in front of that engine*, not a second engine.** | The Windows script's *"shares DSH_HOME, so it is the same agent"* (`serve-phone.ps1:16-18`) is the one-writer violation (`windows.json:5`); the Linux shape — `phone-gate.service` on 3086 relaying to `phone-engine.service` on 3089, one engine, one home — is MEASURED working on `secratary` with a 15-check probe (§1.0, §3.3). | Leaving the Windows shape: it works until a session is opened on both engines, and then a history is unloadable. |
| D3 | **`--trusted-host <node>.tail93e6e6.ts.net` is baked into the launcher and synced from the repo**, not passed ad hoc; `tailscale serve` publishes the **gate**, never the engine directly. | `--trusted-host` is a **startup** setting, so an ad-hoc change means an engine restart means every live session ends. Publishing the gate is already the proven shape (`serve status` on secratary → `:3086`), and it hides the token exchange from every client (§3.3). | Publishing the engine's own port: then every device needs a `?token=` link at least once per origin, and a first-time visitor hitting the bare URL gets a 401. |
| D4 | **The broker is the authority; the authority is not an engine host** — with one measured exception, already taken. | `secratary` has **4 cores, 23.4 GB, swap 100 % used** (MEASURED §1.0/§1.6): a fine control plane, a hopeless worker. | Moving *fleet* work there, or treating its 4 cores as capacity. The phone engine already lives there and that is fine — one idle session store is not a fleet. |
| D5 | **Position is computed, never stored; no verb ever returns a refusal.** | Already the governor's rule and the owner's rule (`PROGRAM.md:11`, `governor.js:37-39, 63-71`). | A cap: subtracts capability, which is the one thing the program refuses to do. |
| D6 | **Disk headroom becomes a first-class placement input.** | 1,596 % disk time is a measured collapse, and the sync zstd decompress on a 237.5 MB corpus is on the same loop. `[corrected 2026-09-16: the DECISION STANDS and is arguably strengthened — measured 97.31 % average disk time on this laptop, single disk, with SearchIndexer at 44–102 MB/s sustained. Only the figure 1,596 % must not be used (one disk cannot exceed 100 %), and the corpus is ≈250 MB rather than 237.5 MB. Source: 60-verification.md §1.3, §1.5.]` | Memory-only placement, which is what the governor does today and why it cannot see the disk failure coming. |

---

## 8. The phased build

Each phase ends in something **measurable**, and nothing in a later phase is needed for an earlier one.

### Phase 1 — this week, existing hardware, no purchases, no new code beyond the two smallest changes

**Goal: the mesh stops being four machines and starts being one system with honest limits.**

1. **Make every node match the node that already works (§1.0).** Audit for a second engine against any one
   `DSH_HOME`; adopt the `secratary` shape — one engine, loopback only, `--trusted-host <node>.tail93e6e6.ts.net`,
   owned by a service rather than a login session — and a gate in front of it (§3.3). Converge `serve-phone.ps1`
   onto the Linux shape, which is the correct one.
   *Measure:* on every node, `ps … | grep 'bin[.]js web' | wc -l` is **1**; `tailscale serve status` names the
   gate's port; `probe-phone.py` (adapted per node) passes its WebSocket-upgrade and authenticated-`session/list`
   checks from the phone. `secratary` is the reference implementation and already passes all 15.
2. **Publish every node the owner uses.** `tailscale serve --bg <gate port>` per node; `--trusted-host
   <node>.tail93e6e6.ts.net` in the launcher, synced from `harness-config` (D3).
   *Measure:* `tailscale serve status` on each node, and one cold `GET /` **200** from a phone with no token in
   the URL. Today three of the four workstations report **"No serve config"** (MEASURED §1.0) — this is the
   single highest-value item in Phase 1, because it is the whole difference between "reachable" and "not".
   `[corrected 2026-09-16: **the "200" is wrong and so is the missing half of the test.** (a) A cold `GET /`
   with no token is **401 by design** — §3.1 `:437–445` of this same document says a first-time visitor who
   reaches the root without a token "gets a 401 and a dead page", so §8.1 contradicted §3.1. Measured on
   ZABZ-YOGA: `GET /` on a foreign authority → **401**; `GET /api` on a foreign authority → **403** (the fence
   is stricter on `/api`). **A node behind a gate answers 200 here because the gate does the token exchange;
   a node publishing a raw engine cannot.** (b) `tailscale serve status` ALONE IS NOT EVIDENCE — measured the
   same evening, this laptop's serve entry pointed at `127.0.0.1:3086`, which had NO LISTENER, and every
   request through `https://zabz-yoga-1.tail93e6e6.ts.net/` returned **502** while `serve status` looked
   healthy. The test must therefore ALSO assert that the port named by `serve status` has a live listener.
   Full corrected procedure, with the meaning of 401/200/403/502/000: **`60-verification.md` §4.2**. Also note
   `--no-proxy`: this machine's `AutoConfigURL` PAC can manufacture a 502 that reads like a broken mesh.]`
   `[corrected 2026-09-16: "three of the four workstations report No serve config" is stale for ZABZ-YOGA —
   it IS served now (see the 502 above). §9 of this document already recorded the general fact.]`
3. **Ship the §3.2 fragment plugin** into the gate's injected layer (§3.3 item 2), so it lands on every node at
   once. *Measure:* `https://<node>.tail93e6e6.ts.net/#session=<id>` opens that session from the phone.
4. **Make cross-node placement an explicit, written act.** Until Phase 3 exists, `agent-fleet` ships with
   `-Node` and the launcher refuses to fan a fleet out on the laptop he is holding without saying so.
   *Measure:* a 6-agent fleet runs on `ZABZ-TECH` (24c/32t) or `zabz-tech-linux` (12 cores) and the laptop's
   commit is unchanged ±1 GB; the `/healthz` reading on the laptop before and after is the evidence.
5. **Write the §5.2 handoff before every fleet.** *Measure:* a kill of the fleet's node mid-run, and the
   work found again from the journal entry alone on a second node.

**Phase 1's single acceptance test:** *take the phone, open one session that lives on the desktop, start a
6-agent fleet in it, and watch the laptop's commit while nothing on the laptop moves.*

### Phase 2 — what needs bought hardware

**Goal: remove the two bottlenecks money can remove, and make the always-on tier real.**

| buy | why, in the measurements | what it changes |
|---|---|---|
| **A dedicated NVMe volume for `<DSH_HOME>` and worktrees** (or at minimum, separate them from the build artifacts) | 1,596 % disk time `[corrected 2026-09-16: use the measured 97.31 % average / single disk instead]`; a 237.5 MB session corpus `[corrected 2026-09-16: ≈243–255 MB measured]` with a synchronous zstd decompress on the same loop; `list_agents` at 1,172 ms for one scan | the largest measurable non-memory stall in the whole program stops being a stall |
| **Parity for `ZABZ-TECH`** (not a purchase — the fixes are already written): `NODE_COMPILE_CACHE`, the reaper, `maxParallelToolCalls`, Defender exclusions | the desktop is a **24c/32t, 63.6 GB** box carrying the waste the laptop already shed (MEASURED §1.0 for its shape; `PROGRAM.md:76, 89-104` for the waste) | it becomes the fleet node it is already the best candidate for |
| **A Linux worker on the office LAN** — `zabz-tech-linux` already exists at **12 cores / 11.7 GB** | the cheapest capacity in the roster that is not the owner's laptop and not the authority; needs no purchase, only parity deployment | a second work node for fleets that must not touch either laptop |
| **Disk, not cores, on the mac mini** | MEASURED: **17 GB free of 228 GB** (§1.0). An employee's machine with 93 % disk used cannot host worktrees, and should not be given fleet work without that being fixed first | rules `LakewooechsMini` out of the worker role as-is — a measured exclusion, not an opinion |
| **Always-on compute for the worker role** — a small NUC/1 L box with ≥16 cores and ≥64 GB, NVMe, wired at the office | the *only* always-on node today has **4 cores and 23.4 GB** (MEASURED) and is already running the company's 18-agent tick loop | work that must not depend on a laptop being awake gets somewhere to run |
| (optional) **a laptop-speed ceiling check**: is the owner's laptop already NVMe? | §6 says the laptop is not the fleet host again — so spending on it is the wrong spend | avoids buying the wrong thing |

*Measure:* the worker node accepts a 6-agent fleet + a build and its `/healthz` never reports a governor queue
position; the laptop's commit is flat while it happens.

### Phase 3 — code that has to be written

**Goal: placement becomes automatic, and provable.**

1. **Federate the capacity surface (PROPOSED).** Each node's plugin-health publishes the §4.2 fields to the
   authority on a heartbeat. *Measure:* one row per node per 15 s, and a node killed by hand aging out of the
   candidate set within 60 s.
2. **The placement service (PROPOSED).** `PLACE` / `OFFER` / `COMPLETE` + the computed-position queue on the
   authority. *Measure:* 30 concurrent requests, ≥1 queued with a correct position, **zero refusals**, and
   every grant naming a distinct node — the governor already has this exact test
   (`test/governor-stress.mjs --contenders 30 --slots 5`, `90-plugin-health-governor.md:235-255`); the mesh
   version must reproduce it across hosts, not processes.
3. **Wire `agent-fleet` to the broker, remote-first (PROPOSED).** One acquisition before fan-out, position on
   queue. The integration point and the exit-code contract (0 granted, 10 queued) are already documented as
   this workstream's, not the plugin's (`90-plugin-health-governor.md:379-381`).
4. **The §5.2 pre-work handoff as a required argument** — fleet jobs cannot start without writing the record.
   *Measure:* a fleet that fails to write the record does not start.
5. **Disk headroom into the placement inputs (D6).** *Measure:* a job that declares a 20 GB worktree is not
   offered to a node with 6 GB free.

**Phase 3's single acceptance test:** *the owner types one sentence into the session on whichever machine he
is holding; the fleet, the placement, the queue position, the recovery record and the evidence all happen
without him choosing a machine — and when a node is killed mid-flight, the position, the branch and the
handoff are all still correct.*

---

## 9. Open, and genuinely the owner's

Two things, and neither is a document to read. **The first is a single question, asked plainly.**

1. **Money, and it is the only question in this file for him.** Phase 2 proposes an always-on worker node
   (≥16 cores, ≥64 GB, NVMe, wired at the office) so that fleets do not depend on either laptop being awake,
   and a dedicated NVMe volume for `<DSH_HOME>` + worktrees because **1,596 % disk time** is the measured stall
   that memory tuning cannot fix. `[corrected 2026-09-16: this is the sentence that carries a wrong number into
   a question for the owner, so it is corrected rather than annotated. What is measured is **97.31 % average
   disk time on a single disk over a 3-second window**, with SearchIndexer reading 44–102 MB/s through it, and
   `\PhysicalDisk(_Total)\% Disk Time` cannot exceed 100 % on one disk so 1,596 % was never a reading of that
   counter. **The question to the owner is unchanged in substance** — the disk is a real bottleneck and the
   money question is real — but do not put "1,596 %" in front of him.]` Two cheap alternatives already exist and need no purchase —
   `ZABZ-TECH` at **24c/32t / 63.6 GB** and `zabz-tech-linux` at **12 cores / 11.7 GB** (both MEASURED §1.0) —
   so the honest question is whether he wants to buy a box or spend the two free ones first.
   *My recommendation: Phase 1 + parity on the two existing machines, and revisit the purchase only if a
   measured fleet run still queues.*

2. **A status correction to the record, not a question: Tailscale Serve is already enabled and `secratary` is
   already published** — MEASURED `tailscale serve status` → `https://secratary.tail93e6e6.ts.net (tailnet
   only) |-- / proxy http://127.0.0.1:3086`, with Funnel deliberately **off**. What is *not* done is per-node
   publication: `ZABZ-TECH`, `ZABZ-YOGA` and `linux-pc` each report **"No serve config"**. `[corrected 2026-09-16: `ZABZ-YOGA` DOES have a serve entry now; what it does not have is a live listener behind it (points at 3086, nothing there, URL answers 502). This §9 paragraph is the one place the document had the general fact right — the sentence corrected here is only the per-node list. Source: 60-verification.md §4.3.]` The blocker recorded
   on 2026-09-11 (`docs/dsh-mobile/01-DESIGN-AND-PLAN.md:71-76`) is therefore closed, and Phase 1 item 2 needs
   no owner action at all.

Everything else in §7 and §8 is a development decision and is taken here.
