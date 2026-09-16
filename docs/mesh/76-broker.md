# 76 — The broker (STREAM S5)

**Program:** `docs/mesh/71-mesh-program.md`, §2.1 (the capacity object it consumes), §2.2 (its API,
FROZEN), §3 row S5, §4 items 2 and 6. **Depends on:** `docs/mesh/66-dsh-remote-capability.md` §4
(the recommendation this implements) and `docs/mesh/20-placement.md` §4.
**Date:** 2026-09-16, 23:15–23:21Z (every timestamp below is UTC, from the machines' own clocks).
**Author:** stream S5, an agent session; not the owner. **Status: built, tested, and running on the
authority.**
**Read-only with respect to everything else:** no engine was started, stopped, restarted or
reconfigured; no allow-list or serve config was changed; `personal-secretary-mvp` was not touched;
nothing was committed (the manager integrates).

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the
command given. **READ** = read out of source, with `path:line`. **DEV DECISION** = this stream's own
call, recorded here because the frozen interface does not cover it (§7 of `20-placement.md` gives
streams that authority). **UNVERIFIED** = stated as unknown, never as fact.

---

## 1. What it is, and where

A small Node service on the authority that answers one question — *where should this work run?* — from
**live measurements only**.

| file | what it is |
|---|---|
| `packages/mesh-broker/lib/scoring.js` | the frozen §2.2 arithmetic, as pure functions over a reading |
| `packages/mesh-broker/lib/capacity.js` | the client: `GET /mesh/capacity` through a node's gate, short timeout, never rejects |
| `packages/mesh-broker/lib/config.js` | the roster loader (a whole-file failure if there is no node) |
| `packages/mesh-broker/lib/leases.js` | the lease table — the broker's **only** state, in memory, TTL-reaped |
| `packages/mesh-broker/lib/broker.js` | the decision: tiers, ranking, position, and the `rationale` |
| `packages/mesh-broker/lib/server.js` | `POST /place`, `POST /done`, `GET /nodes[?fresh=1]`, `GET /healthz` |
| `packages/mesh-broker/lib/stub-gate.js` | a §2.1 stub gate, for the tests and for manual runs |
| `packages/mesh-broker/bin/mesh-broker.mjs` | the service entry point (prints its roster, TTLs and port at boot) |
| `packages/mesh-broker/bin/mesh-stub-gate.mjs` | the stub as a CLI |
| `packages/mesh-broker/nodes.json` | the roster: `zabz-tech`, `zabz-yoga`, `zabz-tech-linux`, `secratary` |
| `packages/mesh-broker/test/*.test.mjs` | 37 tests, including the §4 items 2 and 6 acceptance tests |
| `packages/mesh-broker/deploy/secratary-smoke.sh` | the on-authority smoke run (tests, service, three verbs) |
| `packages/mesh-broker/deploy/mesh-broker.service` | a ready systemd unit — **not installed** (see §6.4) |

No new dependencies: `node:http`, `node:https`, `node:fs`, `node:crypto`, `node:os`, `node:test`.
Verified under **Node v24.12.0** (this laptop) and **Node v20.20.2** (the authority, which is the
version that matters) — MEASURED.

## 2. The API, as implemented

### `POST /place`

Body `{"task":{"kind":"oneShot"|"fleet","children":6,"worktreeGiB":2,"prefer":"home"|"office"|null,"exclude":["node"]}}`

**200**, always:

```json
{ "node":"zabz-tech", "position":0, "lease":"mu4q576o-13752-3-4dc3f685", "score":23, "eligible":2,
  "rationale":["..."], "queue":[] }
```

| field | meaning |
|---|---|
| `node` | the node named. Always a non-empty string: **no code path returns an error instead of a placement** |
| `position` | `0` = start now; `>0` = queued behind that many accepted jobs on that node. Never a refusal |
| `lease` | opaque, TTL'd; released by `/done` or reclaimed by the broker at expiry |
| `score` | free slots on the chosen node — the §2.2 example's own number (`"score": 9`, "9 free slots of 24") |
| `eligible` | how many nodes were in the tier the winner came from |
| `rationale` | the numbers the decision used, in order: the roster count, the frozen slot arithmetic verbatim, the disk gate, the load, the lease counts, the fit arithmetic, the position arithmetic, and why each loser lost. **Non-empty is asserted by test** |
| `queue` | the live accepted jobs ahead on that node (`{lease, node, kind, children, state, waitsMs}`); `[]` when `position` is 0 |

Additive fields (not in §2.2, safe for any caller that ignores them): `at`, `kind`, `children`,
`tier` (`fits`/`highest-slots`/`queued`/`internal-fault`), `blockedBy`
(`unreachable`/`disk`/`accepts`/`caller-excluded`/`no-free-slots`), `considered`, `unreachable`,
`excluded`, `expiresAt`, `leaseTtlSec`.

### `POST /done`

Body `{"lease":"...","ok":true}` → **200** `{ok, released, lease, node, state, heldMs, reason, at}`.
An unknown or already-expired lease answers `released:false` with a reason — a fact, not an error.

### `GET /nodes[?fresh=1]`

Every configured node's last reading **plus its age**, whether or not it answered. Cached ≤ 15 s;
`?fresh=1` forces a re-read of every node. A node that did not answer is:
`{"node":"zabz-tech","unreachable":true,"ageSec":n,"reason":"HTTP 502","slots":0,...}` — **never
dropped, and never given a reading it did not send**. When a previous reading exists it is returned
under `staleReading` with its own age and the note *"this is the last reading that succeeded; it is
NOT current"*.

## 3. The scoring, exactly as §2.2 froze it

```
slots = min(floor((freeMiB - 3885) / 160), 24)   -   governor.inUse
```

* `3885 MiB` reserve and `24` maxSlots are the governor's own derivation
  (`packages/plugin-health/lib/governor.js`: `MAX_SLOTS_DEFAULT` 24, reserve = 12 % of total, 3885 MiB
  on a 31.6 GB machine) — §2.2 froze those two numbers, so they are literals in `scoring.js`.
* `160 MiB` is the measured cost of one in-flight heavy tool call (governor.js:53).
* A negative result is **floored at 0** and the rationale says so — a negative slot count is not a
  number of slots (DEV DECISION; the alternative, reporting `-12 free slots`, is a number nobody can
  act on).
* A node is eligible iff `freeSlots - children >= 0` **or** it has the highest `slots` on the mesh, so
  *a fleet bigger than every node still places, queued rather than refused*.
* A node with `freeGiB < 20` is ineligible for `kind=fleet`. Where the caller declares `worktreeGiB`,
  the requirement becomes `20 + worktreeGiB` (DEV DECISION: the 20 GiB floor is for the fleet's own
  writes, not for the worktree the caller already knows it needs).
* `kind=oneShot` has no disk gate (§2.2 gates fleets only), but the disk is still printed.

The arithmetic is pinned by a test that reproduces §2.2's own worked example — `mem.freeMiB 51000`
with `governor.inUse 15` → `"score": 9`, `"9 free slots of 24"`:

```
zabz-tech: 24 slot(s) of at most 24: floor((52040 MiB free - 3885 MiB reserve) / 160 MiB) = 300 slot(s),
           capped at maxSlots=24 -> 24, minus governor.inUse=0 -> 24
```

## 4. The four robustness rules, and where each lives

| §2.2 rule | how it is made true | evidence |
|---|---|---|
| **It never refuses** | Three tiers (`fits` → `highest-slots` → `queued`, each relaxing one gate), ending in `emergencyPlacement()`: an internal fault still returns a node and `position ≥ 1`. A malformed body, an unparseable roster entry, an excluded-everything caller and an all-dark mesh all answer **200** with a placement | `test/acceptance.test.mjs`: "with EVERY node at zero slots…", "every node unreachable…", "a malformed body still returns a placement", "excluding every node is a caller mistake", "an internal fault still returns a placement" |
| **It stores nothing it can go stale on** | The only mutable state is a `Map` of readings with timestamps (≤15 s) and the lease table, in memory. **No file is written anywhere** | `test/leases.test.mjs` runs placements in a temp cwd and asserts the directory is still empty |
| **Every decision is explainable** | `rationale` is built from the same numbers the decision used, and a test asserts it is non-empty and contains the frozen slot arithmetic (`3885 MiB reserve`, `160 MiB`, `maxSlots=24`), the free-slot count, the child count and the position arithmetic | `test/acceptance.test.mjs` §4.2 test |
| **A dead dispatcher cannot wedge the mesh** | Leases are TTL'd (default 900 s) and reaped by whoever reads the table; nothing has to notice a death | `test/acceptance.test.mjs` "/done releases the reservation, and a lease nobody releases is reclaimed at its TTL" |

## 5. Decisions taken (DEV DECISIONS — recorded, not escalated)

1. **Direct reads, no federation.** Implemented per `66-dsh-remote-capability.md` §4 item 1: the
   broker calls each gate's `/mesh/capacity`; there is no PUBLISH verb, no heartbeat table and no
   node-state table. 15 s of staleness is the *maximum*, not a design input.
2. **Roster = 4 nodes.** `zabz-tech`, `zabz-yoga` (note the MagicDNS name is `zabz-yoga-1`),
   `zabz-tech-linux`, `secratary`. The **Mac Mini is deliberately absent**: it is Yisroel's machine
   (`20-placement.md` §1.0), and placing work on an employee's computer is the owner's call, not a dev
   default. Adding it is one entry in `nodes.json` and no code change.
3. **Port 3091, loopback.** Free on the authority (MEASURED: `ss -ltn` shows 3086, 3087, 3089, 8002 in
   use). **Publication is not this stream's decision** — the broker serves `127.0.0.1` and nothing was
   added to `tailscale serve`.
4. **Lease TTL 900 s**, overridable (`--lease-ttl-ms`, `MESH_BROKER_LEASE_TTL_MS`) so acceptance can run
   in seconds. Longer than the governor's 120 s because a broker lease spans a whole fleet run, not one
   tool call.
5. **The tier ladder, and reachability first when nothing can start.** `fits` → `highest-slots`
   (the frozen rule) → `queued`, where the pool is every non-excluded node ranked **reachable first**,
   then slots, then score. This changed because of a live measurement, not a theory: the first version
   put an unreachable laptop ahead of the one node that was actually answering, because that node
   declared `accepts.fleet:false`. Regression test: *"when nothing can start, a node we can measure
   beats one we cannot"*.
6. **`prefer` is worth +4 slots in the ranking**, not in the reported score (so `score` stays the
   literal free-slot count §2.2 shows). A node 5+ slots freer wins regardless of preference. The number
   appears in the rationale, so it is auditable.
7. **`position` = the number of accepted jobs ahead on the chosen node** (the literal reading of §2.2),
   with a minimum of 1 when a node can take nothing at all, so *"a job that cannot start is queued, not
   refused"* is stated in the rationale rather than hidden. **Known wart, stated:** this is a computed
   depth, not a FIFO ticket — a later caller can win a slot that frees before an earlier queued caller.
   FIFO needs a stored queue, which §2.2 explicitly refuses ("nothing it can go stale on").
8. **Exclusion has two strengths.** `task.exclude` is the caller's *hint* and yields when it names every
   node (never refuse); `"excluded": true` in the roster is the operator's *switch* and is hard.
9. **A failed read is cached for the same window as a good one.** One timeout per 15 s per dead node,
   not one timeout per placement — otherwise 30 concurrent placements against a dark mesh cost 30
   timeouts. `/nodes?fresh=1` is the immediate retry path.
10. **A hard wall-clock timeout**, in addition to the socket timeout: `request.setTimeout()` is a
    socket-*inactivity* timer, so a name that resolves slowly spends DNS time first. MEASURED live on
    the authority: `zabz-tech-linux` reported `latencyMs 3031` against a 1500 ms timeout (exactly two
    timeouts deep). The hard timer fixed it; the regression test measures **310 ms for a 300 ms
    timeout** against a server that accepts and never answers.
11. **`mem.freeMiB: null` means reachable-with-unknown-slots, not unreachable.** S1's own checker allows
    it (`scripts/mesh-capacity-probe.ps1:259`, "every field is measured or absent"), and calling such a
    node unreachable would be a false statement about reachability. It arrives with `slotsKnown:false`,
    `slots: 0` and a rationale line saying the reading is missing.
12. **`accepts` and `maxChildren` are hard gates, a missing `accepts` is not.** A gate that *measured*
    `fleet:false` or `maxChildren: 0` is respected (and quoted in the rationale); a null/absent
    `accepts` is unknown, and unknown is not a restriction.

## 6. How to run it

### 6.1 Tests

```
cd packages/mesh-broker
npm run verify      # node --check on every source file
npm test            # 37 tests: scoring, config, leases, acceptance
npm run stress      # just the §4.6 30-concurrent-against-5-slots test
```

### 6.2 The service

```
node packages/mesh-broker/bin/mesh-broker.mjs --port 3091
# then:
curl -s localhost:3091/nodes
curl -s -X POST -H 'content-type: application/json' \
  -d '{"task":{"kind":"fleet","children":6,"worktreeGiB":2}}' localhost:3091/place
curl -s -X POST -H 'content-type: application/json' -d '{"lease":"<id>","ok":true}' localhost:3091/done
```

### 6.3 Without waiting for a real node: the stub

```
node packages/mesh-broker/bin/mesh-stub-gate.mjs --node zabz-tech --free-mib 51000 --in-use 15
# a node with its capacity forced to zero (§4 item 2):
node packages/mesh-broker/bin/mesh-stub-gate.mjs --node zabz-tech --slots 0
# then point a broker at it:
node packages/mesh-broker/bin/mesh-broker.mjs --port 3091 \
  --config <a nodes.json whose baseUrl is the stub's printed URL>
```

### 6.4 On the authority

```
scp -r packages/mesh-broker secratary-ts:/home/zabz/mesh-broker-run
ssh secratary-ts "bash /home/zabz/mesh-broker-run/deploy/secratary-smoke.sh"
```

The smoke script runs the tests, starts the broker on `127.0.0.1:3091` with a pidfile
(`/tmp/mesh-broker.pid`) and a log (`/tmp/mesh-broker.log`), and prints the three verbs' raw answers.
`deploy/mesh-broker.service` is a ready unit and is **not installed**: publishing or daemonising the
broker is the manager's/owner's call, and the unit must be pointed at whatever path the manager
chooses.

## 7. Evidence (MEASURED 2026-09-16)

### 7.1 The test suite, both Node versions

```
# this laptop, Node v24.12.0
ℹ tests 37   ℹ pass 37   ℹ fail 0   ℹ duration_ms 1586

# the authority, Node v20.20.2 — /home/zabz/mesh-broker-run, deploy/secratary-smoke.sh
# tests 37   # suites 0   # pass 37   # fail 0   # duration_ms 1110.401543
```

Raw per-test lines include, from both runs: *"§4.2 forcing the chosen node to 0 slots names a
different node next time"*, *"§4.2 with EVERY node at zero slots it still names a node, and position >
0, HTTP 200"*, and *"§4.6 30 concurrent placements against a mesh with 5 slots: every caller gets a
node and a position, at least one > 0, zero non-200"* — which asserts, exactly: 30 responses, all
HTTP 200, all with a node and an integer position ≥ 0, **5 at position 0 and 25 queued**.

### 7.2 The real mesh, read from the broker on the authority

`GET /nodes` (23:20Z) — all four nodes answering, ages 0 s:

| node | unreachable | latency | slots | freeSlots |
|---|---|---|---|---|
| zabz-tech | false | 92 ms | 24 | 23 |
| zabz-yoga | false | 205 ms | 23 | 23 |
| zabz-tech-linux | false | 48 ms | 24 | 23 |
| secratary | false | 19 ms | 24 | 24 |

`secratary` reports `accepts.fleet:false` with the gate's own reason (*"no governor lease directory on
this node, so its slot budget cannot be measured: one-shot runs are accepted, fleets are not placed
here"*) and the broker both respects it and prints it.

### 7.3 A real placement, verbatim (the flagship rationale)

`POST /place {"task":{"kind":"fleet","children":6,"worktreeGiB":2}}`, 23:20:57Z:

```
chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech
zabz-tech: 24 slot(s) of at most 24: floor((52040 MiB free - 3885 MiB reserve) / 160 MiB) = 300 slot(s), capped at maxSlots=24 -> 24, minus governor.inUse=0 -> 24
zabz-tech: 23 free slot(s) of 24 (slots 24 = 24 raw - see above, minus 1 broker lease(s) running here; 0 queued)
zabz-tech: disk 220 GiB free on C:/Users/ezabz/code vs 22 GiB required (20 GiB fleet floor + 2 GiB declared worktree) -> gate passes
zabz-tech: load1 not measured on 32 logical cpu(s), 0 agent loop(s) running
zabz-tech: 23 free slot(s) - 6 child(ren) = 17 >= 0 -> fits now
position 0: 23 free slot(s) - 6 child(ren) = 17 >= 0 on a reachable node -> start now
zabz-yoga: 23 free slot(s) of 24, 17 after 6 child(ren)
zabz-tech-linux: 23 free slot(s) of 24, 17 after 6 child(ren), disk 21 GiB < 22 GiB required
secratary: 24 free slot(s) of 24, 18 after 6 child(ren), accepts.fleet=false (no governor lease directory on this node, so its slot budget cannot be measured: one-shot runs are accepted, fleets are not placed here)
lease mu4q576o-13752-3-4dc3f685 (opaque, running) expires 2026-09-16T23:35:57.504Z; ttl 900 s, reclaimed by the broker at expiry so a dead dispatcher cannot wedge the mesh
```

That is the design's intent, measured on the real mesh: **a 6-child fleet lands on `ZABZ-TECH`**, the
64 GB desktop — the row `20-placement.md` §6.2 predicts — while the owner's laptop and the authority
are both correctly passed over (and the reason each was passed over is in the same list).

### 7.4 Never refusing, on the real mesh

* All four nodes excluded by the caller (23:18Z): `200`, `tier=queued`, `position=2`,
  `blockedBy:["caller-excluded"]`, and the position line reads
  `24 free slot(s) - 1 child(ren) = 23 (it would fit), queued because caller-excluded; …`.
* A malformed body (`-d 'not json'`): `200`, with
  `note: the request body was not valid JSON … assumed kind=oneShot children=1 - the broker never refuses a placement`.
* Earlier in the same session, when `zabz-tech` returned **502** (`tailscale serve` pointing at a port
  with no listener — the exact failure `20-placement.md` §0 row 5 describes) and `secratary` and
  `zabz-tech-linux` were dark, the placement was still `200` with the chosen node,
  `position 1`, and three `unreachable (last attempt N s ago: HTTP 502) - reported, never dropped,
  never faked` lines.

## 8. Two bugs the live run caught, and what they were

Recorded because a confident wrong answer is the failure this whole program exists to prevent:

1. **A 3031 ms read against a 1500 ms timeout** for a node that never answered. Cause: the socket
   timeout is an inactivity timer and does not cover name resolution. Fixed with a hard wall-clock
   deadline, and the regression test now measures 310 ms for a 300 ms timeout.
2. **A rationale line that lied about its own arithmetic**: `position 2: 22 free slot(s) - 1 child(ren)
   = 21 < 0 …` — 21 is not < 0. The line had assumed "queued" always means "not enough slots", while
   the real reason was the caller excluding every node. The line is now derived from `blockedBy` and
   reads `… = 23 (it would fit), queued because caller-excluded`, and the all-excluded test asserts no
   false `< 0` can appear.

A third, found by reading S1's probe rather than by a failure: a node answering with
`mem.freeMiB: null` would have been reported as `unreachable`. That is a false claim about
reachability, and it is now `reachable: true, slotsKnown: false` (§5 item 11).

## 9. What could not be verified

* **The Mac Mini, `zabz-tech-linux`'s fleet acceptance, and long-run behaviour.** `zabz-tech-linux`
  answered `/mesh/capacity` (MEASURED above) but reports `accepts.fleet:false`, so no fleet placement
  has ever been *executed* on it — the broker only decided *where*; **nothing in this stream ran work
  on any node**. That is stream S6's and S7's acceptance, not S5's.
* **Publication of the broker beyond the authority's loopback.** It listens on `127.0.0.1:3091` on
  `secratary` and nothing was added to `tailscale serve`. Any caller not on the authority needs that
  decision to be taken by whoever owns the mesh's allow-list.
* **The systemd unit is unvalidated**: `deploy/mesh-broker.service` has not been installed or started,
  so its paths and sandbox settings are a proposal, not a measurement.
* **Concurrency at a scale beyond 30**, and behaviour under a *broker* restart mid-flight: a restart
  loses live leases by design (nothing is on disk), which costs at most one TTL of over-counted slots.
  Stated as a property, not measured under load.
* **`zabz-yoga`'s `cpu.load1` is `null`** (the gate reports no load average on Windows — S1's probe
  says so explicitly). The ranking therefore falls back to slots and roster order on those nodes; a
  real load signal would make the tie-break sharper.
* Whether the **`position` semantics** (a computed depth, not a FIFO ticket) are what the owner wants
  from a queue. §2.2 freezes the shape and forbids stored state; FIFO would need both changed, so it is
  left as the honest reading rather than quietly invented.
