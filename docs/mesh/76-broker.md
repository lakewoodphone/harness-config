# 76 — The broker (STREAM S5)

**Program:** `docs/mesh/71-mesh-program.md`, §2.1 (the capacity object it consumes), §2.2 (its API,
FROZEN), §3 row S5, §4 items 2 and 6. **Depends on:** `docs/mesh/66-dsh-remote-capability.md` §4
(the recommendation this implements) and `docs/mesh/20-placement.md` §4.
**Date:** 2026-09-16, 23:15–23:21Z (every timestamp below is UTC, from the machines' own clocks).
**Author:** stream S5, an agent session; not the owner. **Status: built, tested, and running on the
authority.**
**Amended 2026-09-16 23:27–23:57Z with FOUR OWNER-APPROVED AMENDMENTS** — the fleet disk floor
scales with the fleet (§10.1), a swapping node's slots are halved for ranking (§10.2), the score is
`min(memorySlotTerm, physicalCores × 0.75)` with both terms printed (§10.3), and the roster carries a
per-node v1 transport capability that ranks a node measured unable to take the work below one that
can (§10.4). §10.5 records the two §2.1 contract-line corrections, which stream S1 landed in
`71-mesh-program.md` before this stream got there. **§10.6 is a fifth, contract-only change: the
`absent` state** (approved 2026-09-17, implemented in ~20 lines), and §10.7 records the agreed SHAPE
of a future elastic tier that is deliberately **not built**. Everything measured before the
amendments is marked as such; §7's readings are from 23:20Z and §11's are from 23:57Z.
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
| `packages/mesh-broker/lib/config.js` | the roster loader (a whole-file failure if there is no node, **or if a row is mis-keyed**) |
| `packages/mesh-broker/lib/leases.js` | the lease table — the broker's **only** state, in memory, TTL-reaped |
| `packages/mesh-broker/lib/broker.js` | the decision: tiers, ranking, position, the transport capability, and the `rationale` |
| `packages/mesh-broker/lib/server.js` | `POST /place`, `POST /done`, `GET /nodes[?fresh=1]`, `GET /healthz` |
| `packages/mesh-broker/lib/stub-gate.js` | a §2.1 stub gate, for the tests and for manual runs |
| `packages/mesh-broker/bin/mesh-broker.mjs` | the service entry point (prints its roster, TTLs and port at boot) |
| `packages/mesh-broker/bin/mesh-stub-gate.mjs` | the stub as a CLI |
| `packages/mesh-broker/nodes.json` | the roster: `zabz-tech`, `zabz-yoga-1`, `zabz-tech-linux`, `secratary` — each with its `dispatch` capability |
| `packages/mesh-broker/test/*.test.mjs` | **60 tests** (37 before the amendments), including the §4 items 2 and 6 acceptance tests and one named test per amendment |
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
| `score` | free slots on the chosen node — the **effective** count (§10.3): the §2.2 memory term, capped by `floor(cpu.physical × 0.75)`, then halved if the node is swapping (§10.2) |
| `eligible` | how many nodes were in the tier the winner came from |
| `rationale` | the numbers the decision used, in order: the roster count and each node's state, the frozen slot arithmetic verbatim, the free-slot count, the disk gate with its scaled requirement, the load, **both score terms and the effective score**, **the swap half when it applied**, **whether the node was slow and how long it took**, **the transport capability**, the fit arithmetic, the position arithmetic, and why each loser lost. **Non-empty is asserted by test** |
| `queue` | the live accepted jobs ahead on that node (`{lease, node, kind, children, state, waitsMs}`); `[]` when `position` is 0 |

Additive fields (not in §2.2, safe for any caller that ignores them): `at`, `kind`, `children`,
`tier` (`fits`/`highest-slots`/`transport`/`queued`/`internal-fault`), `blockedBy`
(`unreachable`/`disk`/`accepts`/`transport`/`caller-excluded`/`no-free-slots`), `considered`,
`unreachable`, `excluded`, `expiresAt`, `leaseTtlSec`.

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

Every row also carries the numbers behind the score, so a caller never has to parse a sentence out of
`rationale`: `slots` (effective), `memorySlots`, `coreSlots`, `coreSlotsBasis`
(`physical`/`logical`), `swapApplied`, `swapUsedPct`, `scoreTerms` (all five together), and
`transport: { v1, measuredAt, evidence }`.

## 3. The scoring: §2.2's memory arithmetic, and the three things layered on it

```
memorySlots  = min(floor((freeMiB - 3885) / 160), 24)  -  governor.inUse      <- §2.2, unchanged
coreSlots    = floor(cpu.physical * 0.75)                                     <- §10.3
slots        = min(memorySlots, coreSlots)                                    <- §10.3
slots        = swapUsedPct >= 90 ? floor(slots / 2) : slots                   <- §10.2
```

**All of this is now written into the frozen contract**: `docs/mesh/71-mesh-program.md` §2.2 was
amended 2026-09-17 to carry the core term, the swap half, the per-child disk floor and the transport
and node-state rules, because a contract that disagrees with the code is worse than no contract — the
next reader would implement the wrong one. `"AMENDMENT n"` anywhere in this package means amendment
`n` of this document's §10.

* `3885 MiB` reserve and `24` maxSlots are the governor's own derivation
  (`packages/plugin-health/lib/governor.js`: `MAX_SLOTS_DEFAULT` 24, reserve = 12 % of total, 3885 MiB
  on a 31.6 GB machine) — §2.2 froze those two numbers, so they are literals in `scoring.js`.
* `160 MiB` is the measured cost of one in-flight heavy tool call (governor.js:53).
* A negative result is **floored at 0** and the rationale says so — a negative slot count is not a
  number of slots (DEV DECISION; the alternative, reporting `-12 free slots`, is a number nobody can
  act on).
* A node is eligible iff `freeSlots - children >= 0` **or** it has the highest `slots` on the mesh, so
  *a fleet bigger than every node still places, queued rather than refused*.
* A node with `freeGiB < 20 + worktreeGiB + 0.5 × children` is ineligible for `kind=fleet` (§10.1).
* `kind=oneShot` has no disk gate (§2.2 gates fleets only), but the disk is still printed.
* **§2.2's frozen line is a memory formula, and it is still what the first rationale line prints,
  verbatim.** The amendments change which node WINS and what `score` means; they do not edit the
  memory arithmetic itself, and every one of them is printed alongside it. As of 2026-09-17 the
  amended terms are also part of §2.2 on disk, so the frozen contract and this code agree.
* **Ranking order, in one place** (the tier ladder of §4 plus the ordering inside a tier):
  `fits` → `highest-slots` → `slow` → `transport` → `queued`, and within a tier: reachable first,
  transport-capable first, fast before slow, then effective slots, then a bounded `prefer` bonus,
  then load, then roster order. Every one of those comparisons prints its own line in the rationale.

The arithmetic is pinned by a test that reproduces §2.2's own worked example — `mem.freeMiB 51000`
with `governor.inUse 15` → `"score": 9`, `"9 free slots of 24"`:

```
zabz-tech: 24 slot(s) of at most 24: floor((52040 MiB free - 3885 MiB reserve) / 160 MiB) = 300 slot(s),
           capped at maxSlots=24 -> 24, minus governor.inUse=0 -> 24
```

(That reading has no `cpu` block, so the core term is *unknown* rather than zero and the memory term
stands alone — which is why the score is still exactly 9. With a `cpu.physical: 16` present the core
term would be 12, which does not bind below 12, and `score` would still be 9: *"9 memory slot(s), 12
core slot(s) of 16 physical x 0.75 -> effective 9"*.)

## 4. The four robustness rules, and where each lives

| §2.2 rule | how it is made true | evidence |
|---|---|---|
| **It never refuses** | Five tiers (`fits` → `highest-slots` → `slow` → `transport` → `queued`, each relaxing one gate), ending in `emergencyPlacement()`: an internal fault still returns a node and `position ≥ 1`. A malformed body, an unparseable roster entry, an excluded-everything caller, an all-dark mesh and a mesh whose every node is measured unable to take v1 work all answer **200** with a placement | `test/acceptance.test.mjs`: "with EVERY node at zero slots…", "every node unreachable…", "a malformed body still returns a placement", "excluding every node is a caller mistake", "an internal fault still returns a placement", "when the only candidate cannot take v1 work it is still placed…" |
| **It stores nothing it can go stale on** | The only mutable state is a `Map` of readings with timestamps (≤15 s) and the lease table, in memory. **No file is written anywhere** | `test/leases.test.mjs` runs placements in a temp cwd and asserts the directory is still empty |
| **Every decision is explainable** | `rationale` is built from the same numbers the decision used, and a test asserts it is non-empty and contains the frozen slot arithmetic (`3885 MiB reserve`, `160 MiB`, `maxSlots=24`), the free-slot count, the child count and the position arithmetic | `test/acceptance.test.mjs` §4.2 test |
| **A dead dispatcher cannot wedge the mesh** | Leases are TTL'd (default 900 s) and reaped by whoever reads the table; nothing has to notice a death | `test/acceptance.test.mjs` "/done releases the reservation, and a lease nobody releases is reclaimed at its TTL" |

## 5. Decisions taken (DEV DECISIONS — recorded, not escalated)

1. **Direct reads, no federation.** Implemented per `66-dsh-remote-capability.md` §4 item 1: the
   broker calls each gate's `/mesh/capacity`; there is no PUBLISH verb, no heartbeat table and no
   node-state table. 15 s of staleness is the *maximum*, not a design input.
2. **Roster = 4 nodes, keyed by Tailscale DNS label.** `zabz-tech`, `zabz-yoga-1` (NOT `zabz-yoga`:
   the host name is `zabz-yoga` but the only name that resolves is `zabz-yoga-1` — measured 2026-09-16
   23:31Z), `zabz-tech-linux` (not the ssh alias `linux-pc`), `secratary`. The **Mac Mini
   (`lakewooechsmini`) is deliberately absent, and the reason has changed twice**: it is no longer a
   policy question (the owner has given free rein and it is becoming a worker node), and it is no
   longer "no answer at all" either. Measured 2026-09-16 23:30Z: `curl
   http://lakewooechsmini.tail93e6e6.ts.net/mesh/capacity` **exits 7** from the authority while the
   node is `active` in `tailscale status`; by 2026-09-17 it answers **200 with an unusable document**
   (`mem: {totalMiB: null, freeMiB: null}`), which is stream S3/S1 work in progress (the fix is
   `sysctl hw.memsize` plus `vm_stat`) and not a fault in this roster. The broker now reports that as
   `capacity-unreadable` rather than dropping the node (§10.9), so the day its reader works it becomes
   a placement target with no code change. The older reason here — "it is Yisroel's machine, so placing work on
   an employee's computer is the owner's call" — is out of date: the owner has given free rein on it
   and it is becoming a worker node. Adding it is one entry in `nodes.json`, with its `dispatch`
   measured the same way as the others, and no code change (§10.4).
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
13. **A timeout is retried once, and a retry is reported as `slow`** (requirement 3, §10.8). The
    deadline stays and the worst case is bounded at `readTimeoutMs + retryTimeoutMs`; the retry is what
    separates "busy" from "gone". The rule is `slow = retried` and deliberately not a cleverer one: an
    earlier version also required the retry to be slow, and a live measurement killed it, because that
    rule hid a real missed deadline. The false-alarm cost is bounded — one read, one tier — and the
    acceptance test pins the recovery, so a warm node returns to full rank on its next read.
14. **A 200 whose body is unusable is `capacity-unreadable`, never `unreachable` and never dropped**
    (requirement 4, §10.9). The node answered; its reader is broken; those are different facts and the
    caller can act on the difference. `validateCapacity()`'s strictness is unchanged — an unmeasured
    budget is still not treated as a big one.
15. **A roster capability is a dated measurement.** `dispatch.v1` was `false` for `zabz-yoga-1` for the
    eleven minutes the junction failure existed (23:27–23:44Z), and that stale row cost 12 effective
    slots — a whole node. The fix is written back into the roster the same hour it is proven (§10.4),
    and the evidence string carries the date and what was run. The same applies to every constant in
    this file: a number whose date is unknown is not a measurement.

## 6. How to run it

### 6.1 Tests

```
cd packages/mesh-broker
npm run verify      # node --check on every source file
npm test            # 60 tests: scoring, config, leases, acceptance
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
# WRONG, and it fails silently - see the lesson below:
#   scp -r packages/mesh-broker secratary-ts:/home/zabz/mesh-broker-run
# RIGHT: copy the sub-trees INTO the existing directory, then run the smoke script.
scp -r packages/mesh-broker/lib packages/mesh-broker/test packages/mesh-broker/nodes.json \
       packages/mesh-broker/package.json packages/mesh-broker/deploy \
       secratary-ts:/home/zabz/mesh-broker-run/
ssh secratary-ts "bash /home/zabz/mesh-broker-run/deploy/secratary-smoke.sh"
ssh secratary-ts "cd /home/zabz/mesh-broker-run && grep -c AMENDMENT test/scoring.test.mjs"   # verify the copy landed
```

The smoke script runs the tests, starts the broker on `127.0.0.1:3091` with a pidfile
(`/tmp/mesh-broker.pid`) and a log (`/tmp/mesh-broker.log`), and prints the three verbs' raw answers.
`deploy/mesh-broker.service` is a ready unit and is **not installed**: publishing or daemonising the
broker is the manager's/owner's call, and the unit must be pointed at whatever path the manager
chooses.

#### The lesson: two ways the deploy "succeeded" while proving nothing (MEASURED 2026-09-17)

Recorded because *"the test passed while proving nothing"* is the worst possible test, and both of
these were hit in the same session:

1. **`scp -r <dir> host:/an/existing/dir` is a no-op that exits 0.** With a destination that already
   exists, scp recreates `<dir>` *inside* it and nothing at the top level is touched; every exit code
   says 0. The first "deploy" therefore changed nothing, and the broker kept serving the **old** code —
   which is exactly what the smoke output showed (`tests 37`, and a rationale without a single amended
   line) while reporting success. **Verify the copy, not the exit code**: grep for something only the
   new code has (`grep -c AMENDMENT test/scoring.test.mjs`) and read the boot banner's roster.
2. **The restart raced, so the old broker answered every curl.** The script sent SIGTERM and slept
   0.5 s; the old process had not yet released the port, the new one died with `EADDRINUSE`, the
   pidfile was rewritten to point at the corpse, and the three verbs below it were answered by the
   **previous** broker. A smoke run that exercises the old code and prints the old numbers is the
   worst kind of green. The script now **waits for the old pid to disappear** (polling `kill -0`, up to
   10 s, then SIGKILL), starts the new one, and **fails loudly if the new pid is not alive** — printing
   its log rather than curling a stranger.

The general rule both share: after a redeploy, assert on something that could only have come from the
new build, and make the assertion name the process that answered it.

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

`secratary` reported `accepts.fleet:false` at 23:20Z with the gate's own reason (*"no governor lease
directory on this node, so its slot budget cannot be measured: one-shot runs are accepted, fleets are
not placed here"*) and the broker both respected it and printed it. **That reading is superseded**:
S1 corrected the rule at 23:40Z (the budget is computed from memory and only `inUse`/`queued` come
from the lease directory), and by 23:34Z all four nodes reported `accepts.fleet:true`, `secratary`
and `zabz-tech-linux` carrying a `reason` that is a *note* rather than a restriction — "a `reason` on
a `fleet: true` answer is a note" was already this broker's reading of §2.1 (§5 item 12), so no code
changed for it.

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

* **The Mac Mini, `zabz-tech-linux`'s fleet acceptance, and long-run behaviour.** No fleet placement
  has ever been *executed* on any node — the broker only decided *where*; **nothing in this stream ran
  work on any node**. That is stream S6's and S7's acceptance, not S5's. (`zabz-tech-linux` reported
  `accepts.fleet:false` when this list was written; by 23:34Z it reported `true`, so the blocker moved
  from the gate to whether a fleet can actually run there — still unmeasured.)
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

---

## 10. The amendments (owner-approved 2026-09-17)

Five changes on top of the built broker. The first four were approved together at 23:27Z; §10.6 was
approved after the elastic-cloud study. Each names its measurement, its test, and what it deliberately
does **not** do.

### 10.1 The fleet disk floor scales with the fleet — `requiredGiB = 20 + worktreeGiB + 0.5 × children`

**Why.** MEASURED 2026-09-16 23:34Z: `zabz-tech-linux` reports `disk.freeGiB 20.8` against a flat
20 GiB floor — **0.8 GiB of margin**, so one worktree flipped it into a silent overlap and the broker
said nothing. A floor that does not move with the fleet is not a floor.

**Rule.** One-shot needs `20 + 0.5` (the same formula with `children = 1`; `kind=oneShot` has no disk
gate anyway and the number is printed for information). A 6-child fleet needs 23 GiB; a 12-child fleet
needs 26 GiB. Half a gigabyte per child is the conservative allowance for the scratch and logs a child
writes that the caller has not declared.

**Where.** `scoring.js` `PER_CHILD_DISK_GIB = 0.5` and `diskRequirementGiB()`; the rationale line prints
all three terms (`20 GiB fleet floor + 2 GiB declared worktree + 0.5 GiB/child x 6 child(ren)`).

**Tests.** *"AMENDMENT 1 the fleet disk floor scales with the fleet: 20 + worktree + 0.5 per child"*
and *"AMENDMENT 1 the real numbers: 20.8 GiB free passes a 1-child fleet and fails a 12-child one"*
(scoring), plus *"AMENDMENT 1 the real 20.8 GiB node: a 1-child fleet places there, a 12-child fleet
does not"* (acceptance, end to end through `POST /place`).

**Not done.** No per-child disk measurement — 0.5 GiB is a stated allowance, not a reading, and the
rationale prints it as an allowance.

### 10.2 A swapping node's slots are halved for ranking — `swapUsedPct >= 90` → `floor(slots / 2)`

**Why.** MEASURED repeatedly 2026-09-16: `secratary` reports `mem.swapUsedPct 99.9` (4,092 of
4,095 MiB). Its `mem.freeMiB` therefore counts memory the node must **fault back in**, which is the
opposite of capacity for a fleet that starts six processes at once.

**Rule.** A node at or above 90% swap has its effective slots halved **for ranking**. **Never a gate**:
a node that is merely unattractive is still placed on when it is the only candidate, and the halving is
printed — `"swap 99.9% used (>= 90%): free memory is memory that must be faulted back in, so 3 slot(s)
halved to 1 - a ranking penalty, never a refusal"`. The owner's rule is queue-never-amputate, and this
is a ranking change, not a refusal.

**Where.** `scoring.js` `SWAP_PENALTY_PCT = 90`, `swapPenalty()`; applied inside `effectiveSlots()` and
reported as `swapApplied`/`swapUsedPct` on `/nodes`.

**Tests.** *"AMENDMENT 2 a node at or above 90% swap has its effective slots halved, and the line says
so"*, *"AMENDMENT 2 secratary's live numbers: 24 memory slots, 3 core slots, halved to 1 by 99.9%
swap"* (scoring) and *"AMENDMENT 2 a node at 99.9% swap reports the halving in its rationale and is
still placeable"* (acceptance). The boundary is asserted inclusive at exactly 90 and exclusive at 89.9.

**A first cut, stated plainly.** **90% is a first cut, not a measured threshold.** It is where a node
starts swapping hard enough that the memory term stops meaning capacity, but the number has not been
read off a node under a real fleet load, and there is no read that distinguishes "swapped once an hour
ago" from "swapping right now" — `swapUsedPct` is a level, not a rate. Revisit it the first time a node
is read while a fleet is running: the sharper signal would be a swap *rate* (pages in/out per second),
which §2.1 does not report today.

### 10.3 The score is `min(memorySlots, floor(cpu.physical × 0.75))`, and both terms are printed

**Why.** The frozen model derived slots purely from memory, so `secratary` (4 cores) scored **24 slots**
and `zabz-tech-linux` (6 physical cores) scored 24 — a 6x overstatement on the authority, and the
broker would happily send it a 12-child fleet. The score said nothing about whether the CPU could run
what the memory could hold.

**The measured constant.** ~1 core per actively generating agent turn (0.81 GB commit + ~1 core,
measured 2026-09-15/16), and this laptop's paging threshold is **13-14 concurrent turns on 16 physical
cores** — i.e. `floor(16 × 0.75) = 12`, the measured number to within one. A quarter of the cores is
held back for the OS and the human at the keyboard.

**Rule.** `coreSlots = floor(cpu.physical × 0.75)`; `effective = min(memorySlots, coreSlots)`; then the
swap halving of §10.2. `cpu.logical` is used **only** when `physical` is absent, and the line names
which was used and calls the logical basis a *looser ceiling*. A reading with neither is unknown —
never zero — and the memory term stands alone.

**Where.** `scoring.js` `CORE_SLOT_FRACTION = 0.75`, `coreSlots()`, `effectiveSlots()`. The rationale
prints one line per node in exactly this shape:

```
secratary: 24 memory slot(s), 3 core slot(s) of 4 physical x 0.75 -> effective 3
zabz-yoga-1: 23 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12
```

**What the four live nodes then score** (MEASURED 2026-09-16 23:34Z, from each gate's own document):

| node | cpu.logical | cpu.physical | memorySlots | coreSlots | swap | **effective** |
|---|---|---|---|---|---|---|
| `zabz-tech` | 32 | 24 | 24 | 18 | 0% | **18** |
| `zabz-tech-linux` | 12 | 6 | 24 | 4 | 15.3% | **4** |
| `zabz-yoga-1` | 22 | 16 | 23 (inUse 1) | 12 | 0% | **12** |
| `secratary` | 4 | 4 | 24 | 3 | 99.9% | **1** (3 halved) |

**Two of these disagree with the forecast this amendment was briefed with, and the measurement wins.**
`zabz-tech` was expected to be ~12; the node reports **24 physical cores** (i9-14900, `NumberOfCores`
24 × 32 logical, measured over its own sshd) so its core term is 18, not 12 — the 12 came from an
earlier note that read its *16* physical as if it were the desktop's. And `zabz-yoga-1` matches the
forecast at 12 exactly. `secratary` was expected to be ~3 and is **3 before the swap halving and 1
after**, which is the honest number for a box that is already 99.9% into swap.

**Is 18 right for a 24-core desktop?** Unknown, and stated as unknown. The 0.75 constant is calibrated
on a 16-core laptop; a 24-core machine has proportionally more cache and memory bandwidth and may
sustain more than 18 turns, or fewer if its disk is the real limit. The number is *conservative in the
right direction* (it under-promises a big machine, where a guess costs queue time) and it is *the
measured shape* on the machine the measurement was taken on. **The way to settle it is a reading from
`zabz-tech` under a real fleet** — start 18 children there and watch `commit` and page-ins. Until then
the constant is not tuned to taste in either direction.

**Where the brief's arithmetic is stored.** `CORE_SLOT_FRACTION` is one exported literal with the
measurement in the comment above it, so a future session can change one number and see the whole
fleet's ranking move — and `/nodes` publishes `scoreTerms` with `coreSlotsBasis`, so the change is
visible per request.

**Tests.** *"AMENDMENT 3 core slots are 0.75 x PHYSICAL cores, and never more than that"*, *"AMENDMENT 3
cpu.logical is the fallback when physical is absent…"*, *"AMENDMENT 3 the effective score is the
smaller term…"*, *"AMENDMENT 3 a node with 64 GiB free and 0 cores ranks below one with 8 GiB free and 8
cores"*, *"AMENDMENT 3 effective slots are never negative…"*, and the acceptance test *"AMENDMENT 3 the
rationale prints both score terms, so a small box is not read as a big one"*.

**Why it matters beyond the score.** The owner is deciding whether to rent small cloud machines as
elastic capacity. Under the old model a 2-vCPU rental reports 24 memory slots and looks like a
workhorse; under this one it scores `floor(2 × 0.75) = 1`, and the rationale prints both terms so that
number is visible before anything is bought.

### 10.4 The roster carries a per-node v1 transport capability, and the broker ranks on it

**Why — a correctness bug in production, MEASURED by stream S6 at 23:27Z 2026-09-16 (and FIXED at
23:44Z the same day; the `false` below is history, not the current state).** A dispatcher **could not
run work on `zabz-yoga` at all**: a process launched by that machine's sshd could not traverse the
junctions in `~/.dsh/profiles/node_modules`, which is exactly how a DSH profile resolves its bundles —
reading *through* the link gave `UNKNOWN (-4094)`, `require.resolve` gave `MODULE_NOT_FOUND`, and
`ssh <that node> dsh --profile headless` died with *"plugin tree failed to load"*
(`70-remote-fanout-proof.md` §4.4). `zabz-tech` over its sshd was fine. The broker had already placed
work there — `node=zabz-yoga, position=0, score=22`, 23:24Z — with no way to know it could not be done.
**A placed job that cannot run is worse than a queued one.** The cause turned out to be the platform's
reparse-point trust check rather than anything about DSH, and stream S6 cleared it by relinking
in-session (§10.4's roster table has the measurement).

**Rule.** Each roster row carries `dispatch: { v1, measuredAt, evidence }`, and the three states are
never collapsed:

| `dispatch.v1` | meaning | how the broker treats it |
|---|---|---|
| `true` | measured to accept `ssh <alias> dsh --profile headless` | a normal candidate |
| `false` | measured **not** to (the reason is in `evidence`) | ranked **below every node that can take the work**; chosen only when nothing else is eligible, and then the rationale says *"chosen despite transport=unavailable, because nothing else is eligible"* |
| `null` | never measured | ranked between the two, and printed as **unmeasured** — "not a claim that it works and not a claim that it does not" |

`"unmeasured"` and `"measured broken"` are different facts, and a broker that printed both as `false`
would be inventing a measurement. This is a **ranking** change, never a gate: queue-never-amputate
still holds, and a new tier (`tier=transport`, `blockedBy: ["transport"]`) names exactly that case.

**The live roster, with its evidence (all `nodes.json`, read 2026-09-17):**

| node | v1 | evidence |
|---|---|---|
| `zabz-tech` | `true` | S6's parent booted over ssh there and loaded the mesh plugin; three child turns completed with their `MESH-HOST:` lines verified (`70-remote-fanout-proof.md` §2) |
| `zabz-yoga-1` | `true` | **was `false` from 23:27Z to 23:44Z and is fixed.** The failure was Windows' *reparse-point trust check*: the profile links are junctions, and Windows refuses to traverse one created outside the reading session (*"The path cannot be traversed because it contains an untrusted reparse point"*). Relinked **in-session** — 413 links, 22 s, 0 failed — after which `ssh <laptop> … --profile headless "Reply with exactly: LAPTOP OK"` returned `LAPTOP OK` exit 0 in 10.3 s with engine pid 1784 **never restarted**, and a full dispatch TO the laptop completed exit 0 with `childHosts: ["zabz-yoga"]` (stream S6, 23:44Z) |
| `zabz-tech-linux` | `true` | MEASURED by this stream 23:33Z: `node /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js --profile headless "<task>"` over its sshd loaded the profile tree, printed the headless usage text and reached the model call, failing only on `MISSING_CREDENTIAL: llm-deepseek` — the transport works and the credential is the separate gap |
| `secratary` | `null` | **UNMEASURED.** It has node v20.20.2 and a dsh engine at `/home/zabz/dsh-engine`, but its `DSH_HOME` (`~/.dsh/profiles/`) holds only `node_modules` and `web` — there is no `headless` profile to load, so a v1 dispatch there can be shown neither to succeed nor to fail. Recorded as unmeasured rather than guessed, which is the whole point of the third state |

**The `false` state earned its keep in the eleven minutes it existed.** Between 23:27Z and 23:44Z a
placement could have gone to a node that could not run it, and after the fix the same mechanism is what
makes the mesh genuinely two-node: `zabz-tech` (18 effective slots) **and** `zabz-yoga-1` (12) are both
transport-capable, **30 effective slots instead of 18**. The lesson is not "the broker was wrong to
mark it false" — it was right, from a measurement — it is that **a roster capability is a dated
measurement, and a fix must be written back here the same hour it is proven**, because a stale `false`
costs a whole node.

**Tests.** *"AMENDMENT 4 a node measured unable to accept v1 work ranks below one that can, and says
why"*, *"AMENDMENT 4 a v1-unusable node with MORE slots still loses to a usable one with fewer"* (the
live bug, as a regression test), *"AMENDMENT 4 when the only candidate cannot take v1 work it is still
placed…"*, *"AMENDMENT 4 an unmeasured transport is neither 'works' nor 'broken'…"*.

**The permanent fix is v2.** The ssh transport is v1 and its one structural weakness is that it depends
on a login shell seeing the same filesystem the profile expects. The **v2 HTTP route** (`71` §1's
second-tier transport, the plugin-owned `/mesh/run` with HMAC) does not depend on ssh at all, so the
day it lands this entire capability column becomes a fallback rather than a gate — a node that fails
v1 can still take v2 work. This stream did not build it (§3's workstreams give it to S6), and the
capability is a *roster fact* precisely so it can be one line to re-measure when it does.

### 10.5 The two §2.1 contract lines

Both were corrected **by stream S1, in `71-mesh-program.md`, before this stream got to them** — recorded
here so the change of author is not mistaken for the change not happening:

1. **The `governor` bullet.** It said `governor` is read from the lease directory if present, else
   `null`. Stale: `budgetSlots` is **always** computed from `mem.freeMiB`, and only `inUse`/`queued` come
   from the lease directory — `0` each, and named in `accepts.reason`, when it does not exist. S1's
   text now reads exactly that, and adds that `governor` is null *as a whole* only when the engine does
   not answer. The broker's `slotArithmetic()` already treated a missing `governor` as `inUse = 0` and
   said so in the rationale, so no code changed.
2. **The `node` field.** It said "short name, matches the ssh alias prefix". Wrong and now settled in
   the file: it is **the node's Tailscale DNS label** (`Self.DNSName` minus the domain) — `zabz-tech-linux`,
   not `linux-pc`; `zabz-yoga-1`, not `zabz-yoga`; `lakewooechsmini`, not `Mac mini`/`LakewooechsMini`.
   The gate answers the DNS label and `mesh-health.ps1` can only resolve it. S1's comment in the §2.1
   sample now carries the invariant *`node == fqdn.split(".")[0]`*, and **this stream enforces it in
   `lib/config.js`: the broker refuses to boot on a row whose name is not the first label of its own
   fqdn**, because that failure is otherwise a node that silently never answers (measured: the laptop's
   `Self.HostName` is `zabz-yoga` while its `Self.DNSName` is `zabz-yoga-1`, and
   `zabz-yoga.tail93e6e6.ts.net` does not resolve). Test: *"§2.1 naming: a roster keyed on the HOST NAME
   or the ssh alias is refused at startup, loudly"*, and the live negative case is in §11.5.

### 10.6 Amendment 5 — the `absent` state (approved 2026-09-17, implemented small)

**Why.** The elastic-cloud study found one genuine gap in §2.2's frozen interface: `GET /nodes` had no
way to describe a node that is **configured but not yet provisioned**. Such a row is neither reachable
nor unreachable, and calling it `unreachable` is a false claim about reachability — the same error class
this broker already fixed once when it refused to fake a reading for a node that answered with
`mem.freeMiB: null` (§8, third item).

**What was approved and built (~20 lines).** `GET /nodes` gains an `absent` state:

* `absent: true` when a roster row is marked `volatile` and has **never answered** (not on this read and
  not on any read since the broker started). `unreachable` is then `false` — the two states are
  mutually exclusive, which is the point.
* An absent node is **excluded from `eligible`, from the ranking and from the candidate count**, and it
  is given **no reading and no latency** — the `reads`/`readFailures` counters still move, because a
  read really was attempted, but no member of the latency cache (`latencyMs` stays `null`) is invented.
* Its `ageSec` is the time since it was **configured** (`absentSince` names that moment), not since a
  last reading that never happened.
* `POST /place` reports `absent: N` on the response and counts it in the decision line
  (`… 2 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster, 1 absent (configured, never answered, not ranked)`).
* If **every** node is absent there is nothing to exclude, so the whole roster is the pool and the
  never-refuse rule still produces a placement — the one case where an absent node can be named.

**Tests.** *"AMENDMENT 5 a configured node that has never been read is ABSENT, not unreachable, and is
not ranked"* (acceptance), and *"the per-node v1 transport capability keeps 'measured broken' and
'unmeasured' apart"* covers the config normalizer next to it.

**A deliberately narrow reading of the approval.** The approved change came with the `volatile` roster
key named as *not* approved. The implementation therefore uses the marker internally and **sets it
nowhere in the live roster**, so nothing becomes absent today and no node's behaviour changes. When the
elastic tier is built (§10.7) the marker is what a proposed row would carry before it is provisioned.

### 10.7 The elastic tier: the agreed SHAPE, deliberately NOT built
Recorded because the study that produced it is expensive to redo, and because **the teardown rule
matters more than the price**:

> A forgotten CPX41 at **$141.49/month** costs **86.7% of owning the machine outright** — the point of
> elastic capacity is defeated by one instance nobody tears down.

**Agreed shape (NOT approved, NOT built, no provisioner exists):**

* Roster keys `volatile: true`, `hourlyUsd`, `maxLifetimeSec` — a row that describes capacity that may
  not exist yet, what it costs per hour, and how long it may live.
* A **single-flight provisioning lock** — one provisioner, so two simultaneous `tier != "fits"`
  placements cannot each boot an instance.
* A **teardown rule** — `maxLifetimeSec` as a hard ceiling, plus teardown on a completed run, and a
  reaper that does not depend on the placing caller still being alive (that last part is the same
  reasoning as the lease TTL, and it is why the rule belongs beside the lease, not beside the caller).

**The firing condition, as the study recommends it:**

* `POST /place` returns `tier != "fits"` **twice**, **at least 60 s apart**, **with `?fresh=1`** on the
  second read — so a single transient reading cannot boot a machine.
* **Fleets of 2+ children only. Never for a one-shot**: a headless turn is 3-5 s against a 2-4 minute
  boot, so a one-shot can never be improved by renting a box.
* **It lives in the dispatcher (S6), not in the broker.** §2.2 forbids the broker storing node state, and
  a "have I already tried twice?" counter is stored state. The broker reports the two readings it took;
  the caller decides.

**Why this document stops here.** Everything else in the elastic tier needs a provisioner that does not
exist, and building one to satisfy a study would be premature. The broker side of the shape — `absent`,
the capability column, the terms printed in the rationale — is what the study actually needed from this
stream.

### 10.8 A busy node is not a dead one — the `slow` state (approved 2026-09-17)

**Why.** MEASURED 2026-09-16 23:31:18Z: the deployed broker reported
`zabz-yoga: unreachable (timed out after 1500 ms)` **while that laptop's own gate was answering in
89-232 ms** — it was simply busy running the acceptance harness. In the same window one tailnet read to
`zabz-tech` took **7342 ms**. The broker was turning "busy" into "gone", and the two call for opposite
actions: a slow node should be ranked lower, a dead one avoided entirely. A node wrongly called
unreachable is dropped from the ranking, which is a whole node lost to a stopwatch.

**What was chosen, and why this shape.** The deadline stays — the caller must not hang — and the
outcome is distinguished by **making a second attempt**:

* A read that fails on **time** gets exactly **one retry** at a longer budget
  (`RETRY_READ_TIMEOUT_MS`, 4000 ms shipping; it scales down with a caller's own deadline, so a 300 ms
  test pair is 300 + 600). Nothing else is retried: a refused connection, a DNS failure, a 5xx or bad
  JSON are facts about the far side that a second second cannot change.
* **First attempt times out + second succeeds = `slow`**, carrying the elapsed time, the first
  attempt's latency, and its real capacity. It is ranked **below every node that answered first time**
  and **never refused** (if every candidate is slow, `tier=slow` places on the best of them and says
  so).
* **Both attempts fail, or the connection is refused = `unreachable`**, exactly as before.
* The worst case per re-read is bounded at `readTimeoutMs + retryTimeoutMs` (1500 + 4000 ms), which is
  the property the dispatcher depends on.

The pairing is what makes the distinction *legitimate* rather than a guess: within one read, a first
attempt failing and a second succeeding cannot happen to a machine that is gone. There is no third
attempt and no per-node timing memory — §2.2 forbids stored node state, and three attempts would turn a
dark mesh into a 16-second wait.

**Where.** `capacity.js` `classifyReadError()` / `isRetryableRead()` / `RETRY_READ_TIMEOUT_MS` and the
retry in `readNodeCapacity()`; the `slow` state and the `tier=slow` fallback in `broker.js`; the line
`"…: SLOW - the first read missed the 1500 ms deadline (1512 ms), the second answered in 31 ms for 1543 ms
door-to-door -> the node is BUSY, not gone; ranked below every node that answered first time, never
refused"`.

**Tests.** *"a node that accepts the connection and never answers is unreachable within the hard
timeout"* (unchanged in intent, updated for the retry and asserting the bound) and *"REQUIREMENT 3 a
node that misses the deadline once and answers on the retry is SLOW, not unreachable"*, which drives a
server that accepts the first request and answers the second.

**Known limit, stated.** One retry cannot tell "busy for a second" from "slowly dying"; it tells
"answered within 5.5 s" from "did not". A node that is slow on *every* read shows up as `slow` on every
`/nodes`, which is the signal to look at it — not a claim about why.

### 10.9 A broken reader is not an offline machine — `capacity-unreadable` (approved 2026-09-17)

**Why.** A node whose reader is broken answers `200` with something that is not a usable §2.1 document.
Before this the broker rejected the document outright, so the node was **invisible** — and an invisible
node and an offline node look identical at the caller. The Mac Mini is the live case: it now answers
`200` with `mem: { totalMiB: null, freeMiB: null }` (stream S1's reader; the fix is `sysctl hw.memsize`
plus `vm_stat`), and it is about to become a worker, so today it would be silently absent from every
placement.

**The rule.** A 200 whose body is not a usable capacity document is its **own state**:

* `state: "capacity-unreadable"`, `unreachable: false` (it answered — saying otherwise is a false claim
  about the network), `absent: false`.
* Excluded from the ranking, so an unmeasured budget is never treated as a big one — the strictness of
  `validateCapacity()` is unchanged and deliberate.
* Visible in `/nodes` with **the node's own reason** (`reason`, e.g. `"schema 2 is not 1"`), a note
  saying *"a broken reader, not an offline machine"*, and the document it actually sent kept under
  `unreadableReading` so the reader can be debugged.
* The rationale prints it as `"lakewooechsmini: CAPACITY-UNREADABLE - the node answered but its
  capacity document could not be read (schema 2 is not 1) - a broken reader, not an offline machine;
  not ranked"`.

**What is deliberately NOT this state.** A document that is usable apart from `mem.freeMiB: null` stays
`reachable` with `slotsKnown: false` and 0 slots (§5 item 11) — the node answered and only its memory
is unread, which is *unknown slots*, not an *unreadable capacity*. `absent` also wins over this state:
a node that has never answered is absent, not unreadable.

**Tests.** *"REQUIREMENT 4 a node whose capacity cannot be read is CAPACITY-UNREADABLE, not unreachable
and not dropped"*, plus the pre-existing *"a node that answers with mem.freeMiB null is REACHABLE with
unknown slots"*, which pins the boundary between the two.

### 10.10 The five states, in one table

| state | the node's own behaviour | ranked? | said in the rationale as |
|---|---|---|---|
| `ok` | answered, usable document | yes | normal lines (both score terms, disk, transport) |
| `slow` | missed the deadline once, answered on the retry | yes, below every `ok` node | `SLOW - … BUSY, not gone` |
| `unreachable` | refused, or both attempts timed out | no | `UNREACHABLE … reported, never dropped, never faked` |
| `capacity-unreadable` | answered with an unusable document | no | `CAPACITY-UNREADABLE … a broken reader, not an offline machine` |
| `absent` | in the roster, `volatile`, never answered | no | `absent … it is not unreachable, it has never been reachable` |

Order of precedence when more than one could apply: `absent` → `capacity-unreadable` → `unreachable` →
`slow` → `ok`. Never-refuse still holds across all five: if nothing is rankable the whole roster is the
pool, and the placement comes back with a position.

---

## 11. The amended broker, measured live (2026-09-16 23:43–23:45Z)

### 11.1 The suite, on the shipped code

```
cd packages/mesh-broker && npm test
ℹ tests 60   ℹ pass 60   ℹ fail 0     (Node v24.12.0, this laptop)

# the authority, Node v20.20.2, deploy/secratary-smoke.sh:
# tests 60   # suites 0   # pass 60   # fail 0   # duration_ms 4093.3928
```

The 37 tests that existed before the amendments all still pass, with the four that asserted the old
numbers updated to the new ones **and to the reason**: `score` 24 → 18 where a physical core term binds
(§4.2 acceptance, §2.1 down-state), the disk requirement string (`20 GiB required` → `21 GiB required`
where the per-child term applies), and the roster name (`zabz-yoga` → `zabz-yoga-1`).

### 11.2 The live mesh, read through the redeployed broker

`GET /nodes?fresh=1` on the running broker (pid 1892155, started 2026-09-17 00:05Z) — every node
answering, all four `ok`/`slow`-healthy, `absent: 0`:

| node | state | latencyMs | effectiveSlots | memorySlots | coreSlots | swapUsedPct | halved | transport.v1 |
|---|---|---|---|---|---|---|---|---|
| `zabz-tech` | ok | 9 | 18 | 24 | 18 (physical) | 0 | false | true |
| `zabz-yoga-1` | ok | 82 | 12 | 23 | 12 (physical) | 0 | false | **true** (§10.4 fix — it was `false`, and that false row cost 12 effective slots) |
| `zabz-tech-linux` | ok | 7 | 4 | 24 | 4 (physical) | 15.3 | false | true |
| `secratary` | ok | 3 | 1 | 24 | 3 (physical) | 99.9 | **true** | **null** (unmeasured) |

**30 effective slots on the two nodes that can take v1 work**, not 18 — the difference between a
one-node fleet mesh and a two-node one, and every bit of it now visible in one line per node.

### 11.3 Real placements, verbatim, AFTER the amendments

**First: the desktop wins on slots, and the laptop is a healthy loser with a working transport**
(`POST /place {fleet, 6 children, worktree 0}`, 00:04Z, `score 16`, `eligible 2`):

```
chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech
zabz-tech: disk 214.5 GiB free on C:/Users/ezabz/code vs 23 GiB required (20 GiB fleet floor + 0 GiB declared worktree + 0.5 GiB/child x 6 child(ren)) -> gate passes      ← §10.1
zabz-tech: 24 memory slot(s), 18 core slot(s) of 24 physical x 0.75 -> effective 18                                       ← §10.3
zabz-tech: transport v1 (ssh --profile headless) MEASURED to work (measured 2026-09-16): … - work dispatched here can actually run     ← §10.4
zabz-tech: 16 free slot(s) - 6 child(ren) = 10 >= 0 -> fits now
position 0: 16 free slot(s) - 6 child(ren) = 10 >= 0 on a reachable node -> start now
zabz-yoga-1: 12 free slot(s) of 24, 23 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12, 6 after 6 child(ren)
zabz-tech-linux: 4 free slot(s) of 24, 24 memory slot(s), 4 core slot(s) of 6 physical x 0.75 -> effective 4, -2 after 6 child(ren), disk 20.8 GiB < 23 GiB required
secratary: 1 free slot(s) of 24, 24 memory slot(s), 3 core slot(s) of 4 physical x 0.75 -> effective 1 (after the swap halving from 3), -5 after 6 child(ren), swap 99.9% used: effective slots halved, transport v1 unmeasured
```

**Then: the mesh actually spreads.** Four fleet-6 placements issued **concurrently**, then a fifth
afterwards (all 00:05Z). The loser line above is the winner line below, and no placement was
transport-blocked:

| placement | chosen | position | score | eligible | tier |
|---|---|---|---|---|---|
| 1 (concurrent) | `zabz-tech` | 0 | 13 | 2 | fits |
| **2 (concurrent)** | **`zabz-yoga-1`** | 0 | 12 | 2 | fits |
| 3 (concurrent) | `zabz-tech` | 0 | 12 | 2 | fits |
| 4 (concurrent) | `zabz-tech` | 0 | 14 | 2 | fits |
| 5 (afterwards, desktop at 11 free) | `zabz-tech` | 0 | 11 | 2 | fits |

Placement 2's rationale, verbatim — the laptop taking real work, with its own transport proof and its
own core term:

```
chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-yoga-1
zabz-yoga-1: 12 slot(s) of at most 24: floor((13729 MiB free - 3885 MiB reserve) / 160 MiB) = 61 slot(s), capped at maxSlots=24 -> 24, minus governor.inUse=1 -> 23
zabz-yoga-1: 12 free slot(s) of 24 (slots 12 = 23 raw - see above, minus 0 broker lease(s) running here; 0 queued)
zabz-yoga-1: disk 69.3 GiB free on C:/Users/ezabz/code vs 23 GiB required (20 GiB fleet floor + 0 GiB declared worktree + 0.5 GiB/child x 6 child(ren)) -> gate passes
zabz-yoga-1: load1 not measured on 22 logical cpu(s), 10 agent loop(s) running
zabz-yoga-1: 23 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12
zabz-yoga-1: transport v1 (ssh --profile headless) MEASURED to work (measured 2026-09-16): reparse-point trust fixed by an in-session relink; LAPTOP OK exit 0 in 10.3 s; a full dispatch to this node completed exit 0 (stream S6, 23:44Z) - work dispatched here can actually run
zabz-yoga-1: 12 free slot(s) - 6 child(ren) = 6 >= 0 -> fits now
position 0: 12 free slot(s) - 6 child(ren) = 6 >= 0 on a reachable node -> start now
zabz-tech: 11 free slot(s) of 24, 24 memory slot(s), 18 core slot(s) of 24 physical x 0.75 -> effective 18, 5 after 6 child(ren)
…
```

**What changed about the decision, in one line each:** `zabz-tech-linux` is correctly *too small to
matter* (4 slots, not 24) **and** under the disk requirement (20.8 < 23); `secratary` is 1 slot rather
than 24, and its own line names the swap halving that produced it; `zabz-yoga-1` is a **first-class
target again** — its 12 effective core slots are real capacity, and the row that said otherwise now
says why it changed; and the two-node spread is what the arithmetic produces when the desktop fills up,
with no caller-side exclusion and no transport workaround.

### 11.4 The `absent` state, the `slow` state and the naming invariant, as live negatives

* A roster whose row is keyed `zabz-yoga` with fqdn `zabz-yoga-1.tail93e6e6.ts.net` **refuses to boot**
  (§10.5), with the reason and both spellings in the message — measured, exit 1.
* A `volatile` row that has never answered reports `absent: true`, `unreachable: false`, no reading and
  no latency, an age measured from configuration, and is excluded from the ranking — measured by the
  acceptance test; **not observable on the live roster**, because no live row is volatile.
* A 200 that is not a usable document reports `capacity-unreadable` with the node's own reason, not
  `unreachable` — measured by the acceptance test; **not observable live**, because every live reader
  currently answers a usable document.
* A read that misses the deadline and then succeeds reports `slow` with both latencies, ranked below a
  node that answered first time — measured live on `zabz-yoga-1` (2026-09-16 23:58Z: `retried: true`,
  first attempt 1505 ms against the 1500 ms deadline, retry 455 ms, `elapsedMs` 1960) and measured by
  the acceptance test in both directions (retry slow = congested; retry fast = cold-start miss, and the
  next read returns the node to `ok`).

### 11.5 What could not be verified

* **No fleet was executed by this stream.** Every number above is the broker deciding *where*; the only
  work this session ran on another machine was the capability probes of §10.4 (`dsh --profile headless`
  over `zabz-tech-linux`'s sshd, which reached the model call and stopped at a missing credential) and
  the plain ssh/lscpu reads. So "(effective) slots" is a claim about what a node would accept, not a
  measurement of what it sustained. That is S6's and S7's acceptance.
* **The core constant on a 24-core machine** (§10.3) and **the 90% swap threshold under load** (§10.2)
  are the two numbers in this document that are *chosen* rather than measured, and both say so where
  they are defined.
* **`secratary`'s v1 transport is unmeasured** and is recorded as `null` rather than guessed (§10.4).
* **The live `zabz-yoga-1` reading was taken while the node was busy** (8 agent loops, 15 sessions,
  23:34Z). Its effective 12 is the memory-and-core arithmetic on a busy box, not an idle one.
* **The Mac Mini's reader is stream S3/S1 work in progress, not this stream's.** It answered `200`
  with `mem: {totalMiB: null, freeMiB: null}` on 2026-09-17 (it exited 7 with no route on 2026-09-16
  23:30Z), so it is not in the roster yet and its `dispatch.v1` is unmeasured too. The broker already
  handles the day it works: an unusable document is `capacity-unreadable` (§10.9), and a working one
  turns it into a placement target with no code change. The roster's old "it is Yisroel's machine"
  reason is superseded by measurement (§5 item 2).
