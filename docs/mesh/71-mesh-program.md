# 71 — The mesh build program

Owner's mandate, 2026-09-16: *"instead of buying a crazy expensive computer... invest in building the
proper mesh infrastructure so agents and sessions always get routed to the most empty part of the
mesh that will run fastest. Engineer it. A robust system, not some patched-up thing."*

This file is the contract. Six workstreams build against it in parallel; the interfaces below are
FROZEN — if a stream needs a change, it asks the manager, it does not change the interface.

## 0. The constraints that shape every decision (all measured 2026-09-16)

| fact | evidence | consequence |
|---|---|---|
| One engine per `DSH_HOME`, one `DSH_HOME` per node | `windows.json:5`; two engines on one home corrupt session logs | a node is a unit; we never share a home |
| Sessions are node-local and do not move | `20-placement.md` §1.2, verified | **work moves, sessions do not** |
| A mounted bundle cannot hot-load | P210 | **v1 must not require an engine restart** |
| The engine's `/api` fence trusts loopback or a declared `trustedHosts`, and the launch token is per-process and never persisted | `66-dsh-remote-capability.md` finding 2 | **no dispatcher can mint a cookie for another node** — do not build on `/api` from outside |
| `tailscale serve` preserves Host, and forwards `X-Forwarded-For` + identity | measured 21:47Z, 18:06:48Z | the gate is the only door, and it can see who is calling |
| `dsh --profile headless "<task>"` runs one agent turn and exits, no port | measured: `REMOTE OK`, exit 0, 18 s, laptop commit flat 20.12→19.97 GB | **the execution transport exists today** |
| A plugin can own an HTTP route with its own auth | `66` finding 1 | the v2 transport, once a restart window exists |
| Laptop↔office is a DIRECT path, 27–45 ms | `tailscale ping`, and the 18 s cross-node run | placement is not limited by the relay |
| The gate is deployed on every Windows node and on the authority, and restarts freely | this session | **the capacity surface lives in the gate, not a plugin** |

## 1. Architecture

```
   client (laptop / desktop / phone)
        |  https://<node>.tail93e6e6.ts.net/     (Tailscale Serve -> phone-gate)
        v
   +--------------------+     GET /mesh/capacity      +-----------------------+
   |  phone-gate.py     | <-------------------------- |  mesh-broker          |
   |  per node          |                             |  (secratary)          |
   |  - signs in owner  |     PLACE / DONE            |  - reads every node's |
   |  - /mesh/capacity  | --------------------------> |    capacity           |
   |  - /mesh/run (v2)  |                             |  - computes position  |
   +--------------------+                             |  - never refuses      |
        |  relay                                      +-----------------------+
        v                                                     ^
   +--------------------+                                     | PLACE
   |  the node's engine |                                     |
   +--------------------+                              +---------------------+
                                                       |  mesh-run (CLI)     |
        +-------------- ssh + --profile headless ----->|  agent-fleet        |
        |  (v1 transport)                              |  the orchestrator   |
        v                                              +---------------------+
   a worker node
```

**Three ideas, and nothing else is load-bearing:**

1. **The gate is the capacity authority.** It already answers on every node, it restarts freely, and
   it already knows who called. `GET /mesh/capacity` is served BY THE GATE, before relaying, exactly
   as it already serves `/dsh-phone-mobile.css` and `/dsh-attention.json`. **No engine restart is
   required to ship this**, which is why it is the foundation.
2. **The broker decides; it does not execute.** It is a small service on the authority that reads
   capacities and answers "where", computed fresh every time. It stores no node state it can go stale
   on (that is the mistake a heartbeat-fed table makes), and **no verb it exposes ever returns a
   refusal** — position is computed, never a threshold.
3. **Transport is pluggable and v1 is the boring one.** `ssh <alias> dsh --profile headless` is
   proven cross-node today and needs no restart, no plugin and no new auth. The HTTP route
   (`/mesh/run`, HMAC) is v2, built behind the same interface so v1 can be swapped without touching
   the broker or the callers.

## 2. FROZEN INTERFACES

### 2.1 `GET /mesh/capacity` — served by the gate (stream S1)

Answers `200 application/json`. Unauthenticated on loopback; through the tailnet it is inside the
gate's existing device allow-list, so it is exactly as exposed as the gate itself. No secrets.

```json
{
  "schema": 1,
  "node": "zabz-tech",                       // the node's Tailscale DNS LABEL: Self.DNSName minus the
                                             // tailnet domain — the name MagicDNS resolves, and the one
                                             // `mesh-health.ps1` and the broker can act on. NOT the ssh
                                             // alias prefix: `zabz-tech-linux`'s aliases are `linux-pc`
                                             // and `hp-linux`, and this laptop's HostName is `zabz-yoga`
                                             // while the only name that resolves is `zabz-yoga-1`.
                                             // Invariant the probe enforces: node == fqdn's first label.
  "fqdn": "zabz-tech.tail93e6e6.ts.net",
  "at": "2026-09-16T23:20:00Z",
  "cpu":   { "logical": 32, "physical": 16, "load1": 0.42 },
  "mem":   { "totalMiB": 65156, "freeMiB": 51000, "swapUsedPct": 0.0 },
  "disk":  { "workRoot": "C:/Users/ezabz/code", "freeGiB": 236 },
  "agents":{ "loopsRunning": 0, "sessionsLive": 1 },
  "governor": { "budgetSlots": 24, "inUse": 0, "queued": 0 },
  "accepts":  { "oneShot": true, "fleet": true, "maxChildren": 12, "reason": null }
}
```

Rules the gate must obey:
* **Every field is measured or absent — never guessed.** If the engine is down, `agents` and
  `governor` are `null` and `accepts.oneShot` is still `true` (a headless run needs no engine).
  `reason` carries the one-line explanation when `accepts` is restricted, **and also when a number
  inside `accepts` is derived rather than measured**: a node with no governor lease directory
  reports the slot budget computed from `mem.freeMiB` with `governor.inUse: 0` and still accepts
  fleets, naming that in `reason`; only an unmeasurable *budget* makes `accepts.fleet` false. A
  `reason` on a `fleet: true` answer is therefore a note, not a restriction. (Corrected 2026-09-16
  23:40Z: the first build refused fleets on any node without a lease directory, which excluded
  `zabz-tech-linux` and the authority and halved the mesh. See 72 §2.)
* `mem.freeMiB` is the OS's own free-memory number, and `governor.budgetSlots` is **always** computed
  from it — `min(floor((freeMiB - reserve) / 160), 24)`, `reserve = max(2 GiB, 12% of physical)`,
  floored at 4. The governor's lease directory supplies only `inUse` and `queued`; when no directory
  exists they are `0` and `reason` says so (previous bullet). `governor` is `null` as a whole — every
  field of it — only when the engine does not answer.
* The route is answered **before** the sign-in logic, so a cold caller gets capacity, not a cookie.
* Residency/budget arithmetic belongs to the BROKER, not here: the gate reports measurements only.

### 2.2 The broker API — on secratary (stream S5)

`POST /place` — body `{"task":{"kind":"oneShot"|"fleet","children":6,"worktreeGiB":2,"prefer":"home"|"office"|null,"exclude":["node"]}}`

Responds `200`:
```json
{ "node":"zabz-tech", "position": 0, "lease":"<opaque>", "score": 9, "eligible": 3,
  "rationale":["9 free slots of 24", "disk 236 GiB free", "load 0.42"],
  "queue": [] }
```
* `position` 0 = start now; >0 = queued behind that many accepted jobs. **Never a refusal.**
* `rationale` is a list of human-readable lines naming the numbers the decision used. A placement
  decision that cannot be explained is a bug.
* Scoring, frozen: `slots = min(floor((freeMiB - reserveMiB) / 160), maxSlots)` where
  `reserveMiB = 3885` and `maxSlots = 24` — the governor's own derivation — minus `governor.inUse`.
  A node is eligible iff `slots - children >= 0` **or** it has the highest `slots` on the mesh
  (so a fleet bigger than every node still places, queued rather than refused). Disk: a node with
  `freeGiB < 20` is ineligible for `kind=fleet`.
* `POST /done` `{"lease":"...","ok":true}` releases the reservation. A lease older than its TTL is
  reclaimed by the broker itself, so a dead dispatcher cannot wedge the mesh.
* `GET /nodes` returns every node's last capacity reading plus its age. Cached ≤ 15 s; `?fresh=1`
  forces a re-read. A node unreachable is reported as `{"node":..., "unreachable":true, "ageSec":n}`
  — never dropped, never faked.

### 2.3 `mesh-run` — the dispatcher CLI (stream S6)

`mesh-run -Prompt "<task>" [-Node <name>] [-Children N] [-Workdir PATH] [-Json]`

* With `-Node`, runs on that node. Without it, asks the broker and runs where it is told; if
  `position > 0` it prints the position and waits (queue, never amputate).
* v1 transport: `ssh <alias> dsh --profile headless "<prompt>"`, wrapped with a hard timeout, the
  exit code, and stdout/stderr captured to a log under `~/.dsh/mesh/logs/`.
* Every run records: node, start, end, exit code, hostname the child reported, and bytes of output.
* Exit contract: `0` completed, `10` queued (still waiting when the caller gave up), `1` failed.
  No other codes — callers branch on these.

### 2.4 The child's own proof of location

Every dispatched child is instructed, by the wrapper, to begin its report with a line of the form
`MESH-HOST: <hostname>`. The dispatcher verifies that line against the node it believes it used and
**fails the run** if they disagree. A placement system that cannot prove where work ran is a
assertion, not a measurement.

## 3. Workstreams, and the one owner per file

| # | stream | owns | deliverable | acceptance |
|---|---|---|---|---|
| S1 | capacity surface | `scripts/phone-gate.py` (the `/mesh/capacity` route only), `scripts/mesh-capacity-probe.ps1`, `docs/mesh/72-capacity-contract.md` | the route live on every gated node | from the laptop: each node answers valid JSON matching §2.1; the engine's down-state still reports `accepts.oneShot:true` |
| S2 | linux-pc as a node | `scripts/provision-mesh-node.sh`, `docs/mesh/73-linux-pc-node.md` | `zabz-tech-linux` runs an engine + gate | `mesh-health.ps1` reports it healthy; a `--profile headless` turn completes there |
| S3 | the Mac Mini | `scripts/mac-mini-audit.sh`, `docs/mesh/74-mac-mini.md` | what is consuming it, and the fix | a measured before/after of the thing that is actually burning it; NO cosmetic change applied without the owner |
| S4 | fix-forward | `docs/mesh/75-fix-forward.md` (+ the ngram work already in flight) | the residual read and the failing adapter | ngram delete no longer scans; `chat:vscode` stops failing 30 times in a row |
| S5 | the broker | `packages/mesh-broker/**`, `docs/mesh/76-broker.md` | the service + its tests | its own governor test reproduced across nodes: 30 contenders, ≥1 queued with a correct position, **zero refusals** |
| S6 | dispatch + `mesh-run` | `packages/plugin-mesh/**`, `scripts/mesh-run.ps1`, `docs/mesh/77-dispatch.md` | the CLI, and the v2 HTTP route behind the same interface | one parent on one node dispatches 3 children to another; each child's `MESH-HOST:` line proves where it ran; the parent's node stays flat |
| S7 | acceptance (after S1–S6) | `scripts/mesh-e2e.ps1`, `docs/mesh/78-acceptance.md` | the end-to-end proof | see §4 |

Rules for every stream: no engine restart anywhere; no `git push`; commit nothing (the manager
integrates); write only the files you own; every number carries its source and its date; "could not
verify" is a correct answer and a confident wrong claim is not.

## 4. The acceptance test, written as commands

1. **Capacity is real.** For every node: `mesh-capacity-probe.ps1` returns a schema-1 object, and the
   numbers match a direct measurement taken at the same moment.
2. **Placement decides.** With the broker told to place a 6-child fleet: it names a node, and
   `rationale` contains the slot arithmetic that chose it. Repeat with that node's capacity forced
   to 0 and it names a different node. With ALL nodes forced low, it still names one and returns
   `position > 0` — never an error.
3. **Work lands there.** A 6-child fleet dispatched from the laptop produces 6 `MESH-HOST:` lines
   naming the nodes the broker chose, and at least two distinct nodes are named when two are free.
4. **The client stays flat.** The laptop's commit before and after the fleet is within ±1 GB, and
   `/healthz` on the laptop shows no new `agentLoopsRunning` while the children run.
5. **A node can die.** Kill the chosen node's gate mid-run: the run fails with exit 1 and a log
   naming the node, the broker's lease is reclaimed within its TTL, and the next `mesh-run`
   succeeds on a different node with no manual repair.
6. **Queue, never amputate.** 30 concurrent placements against a mesh with 5 slots: every caller
   gets a node and a position, at least one position is > 0, and there are zero non-200 responses.

## 5. What we deliberately do NOT build yet

* **Automatic `subagent` routing** — a remote `SubagentProvider` mounted in the RUNNING engine needs a
  preset row, which needs an engine restart (P210). But a **`mesh` PROFILE needs no restart at all**:
  `dsh --profile mesh headless "<task>"` starts a fresh process with that composition, so its children
  can fan out across the mesh while the node running the parent stays flat. That is the owner's
  sentence implemented without touching a live engine, and it is stream S6's deliverable. Mounting the
  same provider in the resident engine is the upgrade, and the first thing to land when a restart
  window opens; §2.3's interface is already frozen for it.
* **Sessions moving between nodes** — they cannot, by construction. Session *placement* (choosing a
  node at creation) is v2 and needs a client-side redirect the harness does not have.
* **A heartbeat table of node state** — the broker re-reads. Stale state is how this system has lied
  to itself before.
