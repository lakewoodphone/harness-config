# 109 — Pressure routing: the local machine's own saturation, in the placement path

**Status:** implemented in `packages/plugin-remote-fanout/lib/pressure.js`, wired into
`lib/placement.js`, `lib/provider.js` and `lib/index.js`. Takes effect at the **next
engine start** (host-plane row — `~/.dsh` is not reloaded into a running engine;
`docs/mesh/92-provider-placement.md` §7 has the same rule for the same reason).
**Date:** 2026-09-17/18, ZABZ-YOGA (the owner's laptop).
**Reader:** this is the record. The decisions are in §2, §3, §6; the proofs are in §4.

---

## 1. The gap, measured

The owner's words, 2026-09-17:

> *"if the laptop is used up, why didn't dsh start offloading more to the mesh, isn't that the point?"*

He is right, and the reason is not a missing node, a broken broker or a full disk. It is
that **nothing in the routing path ever looked at the local machine.**

What the path did, before this change:

| component | what it decides | did it know this machine was full? |
|---|---|---|
| `dsh-tool-subagent` row (`presets/zabz/agent.cordis.yml:347`) | which provider a `subagent` call goes to | no — it is a config row, bound to `remote-ssh` at boot |
| `RemoteOneShotProvider.start()` | asks the placer, then dispatches | no |
| `createNodePlacer.acquire()` | `POST /place` over ssh, dispatch to the named node | no |
| the broker (`mesh-broker`) | ranks the nodes it knows about | **it was never sent this machine's numbers** |

The broker's ranking is made from each node's **capacity contract** (`GET /mesh/capacity`,
polled every ~15 s). On 2026-09-17 22:12 local the laptop's contract read:

```
node            zabz-yoga-1
state           slow
mem             totalMiB 32373, freeMiB 7896, swapUsedPct 38
agents          loopsRunning 18, sessionsLive 39
governor        budgetSlots 24, inUse 2
accepts         oneShot true, maxChildren 12, reason null      <- "I can take 12 more children"
```

and the broker's own ranking of it, from the live `/place` rationale captured in §4:

```
zabz-yoga-1: 12 free slot(s) of 24, 17 memory slot(s), 12 core slot(s) of 16 physical x 0.75
             -> effective 12, 11 after 1 child(ren), SLOW (3454 ms door-to-door ...):
             still slow on the second attempt
```

And 31 minutes later, from a second live `/place`, as the machine got worse:

```
zabz-yoga-1: 1 free slot(s) of 24, 1 memory slot(s), 12 core slot(s) of 16 physical x 0.75
             -> effective 1, 0 after 1 child(ren), excluded by the caller
```

**Twelve free slots advertised on a machine holding 126 % of physical memory committed** at
22:12, and **one free slot** at 22:43 — i.e. of the 24 slots the broker offered this laptop
across the evening, between 12 and 1 of them had any relation to whether the machine could
hold a child. The arithmetic behind that number is the diagnosis, and it is worth stating
exactly:

* `coreSlots = floor(physical cores × 0.75)` = `floor(16 × 0.75)` = **12**. On a laptop
  whose *logical* CPU count is 16, this is the whole of the number.
* `memorySlots = floor((freeMiB − reserve) / 160)` = `floor((7896 − 3885) / 160)` = **24**,
  capped at 24. As `84-calibration.md` §5.3 measured, this term is **floor((free − 3885)/160)**,
  a *slot* count derived from a 160 MiB-per-slot constant that has nothing to do with the
  403 MiB a generating turn actually costs; it reached the cap at 22:12 and, at 22:43 with
  4.3 GiB free, fell to 1.
* `min(memorySlots, coreSlots)` = 12, then 1.

So the mesh knew the laptop had 39 live sessions and was "slow", and **still ranked it as
having twelve slots free**, because commit charge is not in the contract at all. A
dispatcher that asked the broker and obeyed the answer would have put the child **on the
laptop**, on the authority's own numbers, with no bug anywhere.

**That is the structural half of the gap**, and it is why this change does not simply add
a check to the broker's input path: the *only* number that separates "12 slots free" from
"no room for one more agent" is a reading of the local machine, and the only component
positioned to take it before dispatching is the dispatcher. §5 says what the broker would
need to close it from its side.

The behavioural half is the one the owner felt: **nothing offered the work.** The ledger
under `<DSH_HOME>/mesh/placements/` recorded no placement all day, because the model in
each window chose `subagent_local` (or worked itself), and neither of those paths measures
anything. `subagent`/`subagent_remote` are bound to the mesh and would have gone
off-machine — but only if they were called. A dispatcher with a full machine must *offer*
its work to the mesh, not wait to be asked.

---

## 2. The thresholds, and the arithmetic behind each

Every number below is either a measurement from a named document or arithmetic on one.

| constant | value | where it comes from |
|---|---|---|
| one extra concurrent agent turn | **403 MiB** of commit | `84-calibration.md` §3, level-mean fit, r² = 0.948, 95 % CI **270-530 MiB** |
| `HIGH_COMMIT_PHYSICAL_PCT` | **0.85** | 85 % of 31.62 GiB = 26.9 GiB committed, ~4.7 GiB left = **~11 more turns** |
| `CRITICAL_COMMIT_PHYSICAL_PCT` | **0.92** | 92 % of 31.62 GiB = 29.1 GiB, ~2.5 GiB left = **~6 more turns** |
| `REFUSE_AVAILABLE_FLOOR_BYTES` | **1.5 GiB** | 1.5 GiB ÷ 403 MiB = **~3.8 turns** — below this there is not enough room to honour the child being asked for |

Read as a rule:

* **below 85 % of physical committed** — nothing changes. The child goes wherever the
  broker says, and the broker is asked exactly what it was asked before this existed.
* **at or above 85 %** — this machine is not the place for one more agent. The local node
  is added to the broker's `exclude` hint, so the mesh is *asked* to take the child. If
  the broker places it here anyway, the child runs and the disagreement is recorded loudly
  (§3).
* **at or above 92 % AND less than 1.5 GiB physical available** — a local child is refused
  outright, before the broker is asked, with an error that names the reading and the lines.
* **no reading at all** — behave exactly as before this module existed. Unknown is not
  pressure.

### 2.1 Why the refusal needs BOTH halves, and this is the one place I departed from the brief

The brief's shape was *"above ~92 %, refuse local spawn outright"* on the
committed-to-physical ratio. **On this host that rule alone is wrong, and I can show it
with today's numbers rather than argue about it.** Measured 2026-09-17 22:12 local:

```
\Memory\Committed Bytes   39.93 GB
\Memory\Commit Limit      46.29 GB          (31.61 GiB RAM + 11,776 MB pagefile, exactly)
\Memory\Available MBytes   7,892 MB
Win32_PageFileUsage        CurrentUsage 194 MB of 11,776 MB allocated
```

* committed / physical = **120 %** — over the 92 % line on any reading of the terms;
* commit headroom = 46.29 − 39.93 = **6.36 GB** = ~16 more turns;
* physical available = **7.7 GiB**;
* pagefile resident = **194 MB**, i.e. the machine was not paging.

**A refusal there would have refused work on a machine with 7.7 GiB free.** The ratio
exceeds 100 % on this laptop routinely, because Windows commit charge counts *reserved*
address space and file-backed mappings that consume no physical page, and because the
commit limit here (43.11 GiB) is far above RAM (31.61 GiB). The counter is real; the
inference from it alone is not.

This is the fifth counter in this program to look alarming in the harmless region —
`84-calibration.md` §5.5 names `Load` average, `Pages free`, `% Disk Time` and
`Pages Input/sec` before it — and the honest fix is the same as the fix for those: state
what the number does and does not support, and require a second, independent condition
before it is allowed to change behaviour. Hence: **the ratio is necessary, and physical
availability is the second half.** The ratio alone never refuses anything.

### 2.2 What each number is allowed to claim

| number | backed by | NOT backed by it |
|---|---|---|
| `commitToPhysicalPct` | the quantity the 403 MiB/turn fit is stated in, and the *crossing*: how far past physical the machine is committed | that an allocation will fail — that is the commit limit |
| `commitAvailablePct` / `commitAvailableBytes` | the only number that says an allocation would fail | per-turn cost — measured against, not derived from |
| `availableBytes` | whether a new process of ~400 MiB can be held resident | — |
| `agentsRunning` | the engine's own session census (`ctx.agents.list()` filtered by `status === 'running'`) | the *node's* load: `84-calibration.md` §5.2 measured that a mesh-dispatched child is a separate process and never registers, so a node running eight dispatched children looks idle to this field |
| `toolRunnerProcesses` | direct node children of the engine in the snapshot — a **floor** on local agent count | a count of agents: one agent can hold several shells |
| `nodeProcesses` | every `node.exe` on the machine | generating turns — §5.4 measured 19…27 non-monotonically at 8 live turns |

`mem.swapUsedPct` is **not read anywhere in this change**. `84-calibration.md` §4.4 proved
it is `max(0, committed − physical) / (commitLimit − physical) × 100`, that it reads
exactly 0.0 across a 10 GiB spread of commit on both nodes, and that at "90 %" it is
within 410 MiB of a hard allocation failure. It is a near-OOM alarm wearing a swap name.

---

## 3. What was built

### 3.1 `lib/pressure.js` — the sensor

One reading, from the cheapest source that can answer, on the hot path:

1. **`<DSH_HOME>/health/processes.json`** — the document `plugin-health` already writes
   every 5 s with `GlobalMemoryStatusEx` (`plugin-health/lib/snapshot.ps1:182-202`; the
   same file publishes `commitLimitBytes` and `commitAvailableBytes`, which is where
   committed bytes comes from as `limit − available`). Reading it is one `readFileSync` of
   ~60 KB — p50 **0.76 ms** for a file of that size on this host. **This is the normal path
   and it spawns nothing.**
2. Only when that file is missing or older than 30 s does the reader run its **own** probe
   — one `pwsh -NoProfile -Command` that P/Invokes `GlobalMemoryStatusEx` directly. At most
   one in flight, at most one per 5 s, result cached in
   `<DSH_HOME>/mesh/pressure/last-probe.json` and read synchronously next time. **The probe
   never blocks the dispatch that started it**: that dispatch uses the previous reading or
   reports `unknown`, and the next one reads the answer.

So the steady-state cost is a file read, not a process. `bin/mesh-pressure.mjs` exposes
the same reader to a shell so the number can be checked without an engine.

### 3.2 The decision, on the record, in three places

`placement.acquire()` now, in order: reads pressure → records it → refuses if critical →
asks the broker with the local node added to `exclude` when high → records the placement
with the decision, **including the case where the broker overrode it**.

* **The ledger** (`<DSH_HOME>/mesh/placements/<id>.json`) carries `pressure` (the whole
  reading), `pressureLine` (one sentence), `pressureDecision` (band, decision, reason,
  `localNode`, `excludedLocalNode`, `excludeSentToBroker`, `placedLocally`), and
  `pressureConflict` when the broker placed locally against a non-`ok` band.
* **The child's own report** carries two new lines, above the child's message:

  ```
  pressure       = HIGH — route-remote — the LOCAL option was declined and offered to the
                   mesh as excluded; the child was placed on "zabz-tech"; 40670 MiB of
                   32373 MiB physical committed (125.6 %), commit free 5637 MiB, 6555 MiB
                   physical available; ...
  pressure check = local pressure HIGH — 40670 MiB of 32373 MiB physical committed
                   (125.6 %; lines: 85 % to route remote, 92 % to refuse local)
  ```

  `pressure` is present **only when pressure moved the decision**, so a healthy machine's
  report is byte-for-byte what it was. `pressure check` is always present, so "was the
  local option even looked at?" is never answered by silence. Every band that is not `ok`
  also names the declined local option in words.
* **The engine log**: both lines at placement time.

### 3.3 The refusal, and the case with no good answer

`mesh-unavailable-local-saturated` and `local-pressure-refused` are the two typed errors
(`PressureRefusalError`, carrying the reading and the decision as `detail`).

**The decision the brief asks for explicitly: when the mesh cannot be reached AND this
machine is over its high line, DSH refuses, at both bands, and dispatches nothing.**
The reasoning, in full:

* Above the high line the local option has **already been declined** — excluding this node
  from the ask is the mechanism by which the work is offered to the mesh. If the mesh
  cannot answer, there is nowhere to offer it, and dispatching locally would issue a
  placement this decision has just declared unwanted without recording that it changed its
  mind.
* The alternative — pile the child on — spends a real model turn and ~403 MiB of commit to
  produce work that runs slower than it would have, on the machine the owner is using. The
  first thing `84-calibration.md` §4.1 measured to degrade under load is the engine's own
  loop-lag **maximum**; the mesh exists to keep that from happening.
* The refusal is loud and actionable: it names the reading, both lines crossed, and says
  *"retry when the mesh answers again, or when this machine is under its high line"*. It
  spends **no ssh call and takes no lease** — deliberately, because a lease issued and then
  not dispatched is a slot the mesh has lost for its 900 s TTL.

Under the high line, an unreachable mesh changes **nothing**: the child runs locally, which
is exactly what happened before this existed. `test/pressure.test.mjs` asserts all three.

### 3.4 What was preserved

* A broker that cannot be reached still **rejects** and dispatches nothing.
* `subagent_remote`'s name and arguments are unchanged; so is `subagent`'s
  (`presets/zabz/agent.cordis.yml` is untouched — it already binds `subagent` to
  `remote-ssh`, the provider this package registers).
* `targetHosts` remains what it was: the allow-list for the **placed** node, checked
  against the child's own report. This change never widens it, never adds a name to it, and
  never consults it for a routing decision.
* **No row chooses a node by hand.** `exclude` is a *caller hint* the broker may ignore —
  `broker.js:326-330` and the tier line say so — and the file that carries the hint is this
  package's placement code, not a profile.
* `resolvePlacementMode` is untouched: `fixed` is still the hand-set opt-in, and **pressure
  is not consulted on a fixed target at all** — that mode does not choose a node, a human
  did, and `describePlacement()` says so in the boot log.

---

## 4. Proof by effect, on the saturated machine

Machine state during every measurement below: **ZABZ-YOGA**, 2026-09-17 22:33-22:36 local
(-04:00), engine pid 4416 on port 3099 serving the owner's live work, 29-32 `node.exe`
processes, ~41 GiB committed.

### 4.1 (a) The reader's numbers against an independent `Get-Counter`

Same minute, both readings below; the independent one is a separate `pwsh` process:

```
$ Get-Counter '\Memory\Committed Bytes','\Memory\Commit Limit','\Memory\Available MBytes' -MaxSamples 1
\\zabz-yoga\memory\committed bytes                       41088241664   (38.27 GiB)
\\zabz-yoga\memory\commit limit                          48556675072   (43.28 GiB)
\\zabz-yoga\memory\available mbytes                          7605  MB
```

```
$ node bin/mesh-pressure.mjs --force-probe
pressure HIGH; commit 39543 MiB of 32373 MiB physical (122.1 %); commit free 6764 MiB
  (14.6 % of the limit); available 7100 MiB; agents ? (node processes 29, tool-call
  runners ?); read 10669 ms ago from this package's own probe
raw: commitBytes=41464074240 commitLimitBytes=48556675072 commitAvailableBytes=7092600832
     physicalBytes=33945935872 availableBytes=7444578304
ratios: commit/physical=122.1 %  commit/limit=85.4 %  commitAvailable/limit=14.6 %
        available/physical=21.9 %
band=high decision=route-remote localNode=zabz-yoga-1 routeAwayFromLocal=true refuse=false
```

Agreement, term by term: physical 33,945,935,872 B = 31.61 GiB against the counter's
31.61 GiB (the OS's own `Win32_OperatingSystem.TotalVisibleMemorySize` says 32,373 MiB);
commit limit 48,556,675,072 B = 43.28 GiB **identical**; available 7,444 MiB against
7,605 MB, a **2 %** difference taken 40 s apart on a machine whose commit moved 0.4 GiB in
that window; committed = limit − available, and the same subtraction on each side agrees to
**0.2 %**.

The same comparison on the §4.2 run, where the counter was taken **0.9 s** from the reading
and the two are therefore as close to simultaneous as two processes can be:

| term | the reader (02:43:03Z) | `Get-Counter` (22:43:02.21 local = 02:43:02Z) |
|---|---|---|
| commit limit | 48,556,675,072 B | 48,556,675,072 B |
| commit available | 3,720,595,456 B (3,548 MiB) | 4,457 MB |
| committed (`limit − available`) | 44,836,072,616 B (42,759 MiB) | 45,178,687,488 B (43,085 MiB) |
| available physical | 4,968,009,728 B (4,738 MiB) | 4,145 MB |

Committed differs by **0.8 %** over 0.9 s, and the direction (falling) matches both
`Available MBytes` and the reader's own previous reading. The limit — the one term that
cannot move unless the pagefile is resized — is **identical**.

`--force-probe` is the mode that points the reader at a snapshot path that cannot exist, so
the **fallback probe** is what answered the first of those readings. On the normal path the
same numbers come from `plugin-health`'s snapshot and **no process is spawned** — `spawns=0`,
measured:

```
$ node bin/mesh-pressure.mjs
pressure HIGH; commit 40670 MiB of 32373 MiB physical (125.6 %); commit free 5637 MiB
  (12.2 % of the limit); available 6555 MiB; agents ? (node processes 30, tool-call
  runners 12); read 3012 ms ago from plugin-health snapshot (GlobalMemoryStatusEx,
  refreshed every 5 s)
probe: spawns=0 failures=0 snapshot=C:\Users\ezabz\.dsh\health\processes.json
```

### 4.2 (b) A dispatch choosing a remote node *because of* pressure

`bin/mesh-pressure-proof.mjs` — the **real** placer, the **real** broker client over ssh to
`secratary-ts`, a **real** lease issued by the broker and recorded. Case A uses this
machine's own reading, taken at `2026-09-18T02:40:04Z`; nothing about case A is simulated.

```
=== CASE A — MEASURED reading, REAL broker ===
host                     ZABZ-YOGA → node zabz-yoga-1
pressure HIGH; commit 40136 MiB of 32373 MiB physical (124 %); commit free 6171 MiB
  (13.3 % of the limit); available 6498 MiB; ... read 3375 ms ago from plugin-health snapshot
DECISION                 route-remote — broker placed the child on "zabz-tech"
excludedLocalNode        true (exclude sent to the broker: ["zabz-yoga-1"])
placedLocally            false
broker rationale         chosen from 4 configured node(s): 0 unreachable, 1 excluded by the
  caller, 0 switched off in the roster; tier=fits; chosen zabz-tech | zabz-tech: 18 slot(s)
  of at most 24 ... | zabz-yoga-1: 12 free slot(s) of 24, 15 memory slot(s), 12 core slot(s)
  of 16 physical x 0.75 -> effective 12, 11 after 1 child(ren), SLOW (3640 ms door-to-door,
  first attempt missed the deadline): still slow on the second attempt, excluded by the caller
lease mu6cp1p9-1dxip-b-f32b9942 ... expires 2026-09-18T02:55:01.245Z; ttl 900 s
```

The ledger record (`_scratch/109-pressure/proof-a-measured.json`), the part that must name
the reason:

```json
"node": "zabz-tech",
"excludedLocalNode": true,
"placedLocally": false,
"pressureLine": "pressure HIGH; commit 40670 MiB of 32373 MiB physical (125.6 %); ...",
"pressure": { "band": "high", "commitBytes": 42086006784, "physicalBytes": 33945935872,
              "availableBytes": 6814081024, "commitLimitBytes": 48556675072,
              "commitAvailableBytes": 6470668288, "commitToPhysicalPct": 124,
              "commitToLimitPct": 86.7, "nodeProcesses": 30, "toolRunnerProcesses": 12,
              "ageMs": 3375,
              "source": "plugin-health snapshot (GlobalMemoryStatusEx, refreshed every 5 s)" },
"pressureDecision": { "decision": "route-remote", "refuse": false,
  "reason": "committed 124 % of physical (at or above 85 %): this machine is not the place
             for one more agent: the mesh is asked to take this child, and the local node is
             excluded from the ranking rather than forbidden",
  "localNode": "zabz-yoga-1", "excludedLocalNode": true,
  "excludeSentToBroker": ["zabz-yoga-1"], "placedLocally": false }
```

**Read the two lines of the broker's own rationale together**: it excluded `zabz-yoga-1`
*"by the caller"* and then, in the same answer, told the reader that `zabz-yoga-1` had 12
free slots. The exclusion is the only thing that kept the child off a machine at 124 % of
physical, and the exclusion came from this change.

What this proof is and is not: the placement is end-to-end real — a live broker decision, a
live lease, a live ssh — and the child was **not** executed (no model turn was spent). The
transport that would carry it is `docs/mesh/70-remote-fanout-proof.md` §2, measured,
unchanged by this work. A pressure-caused *child run* was not performed, and §7 says so.

### 4.3 (c) The refusal firing

**The reading in this case is SIMULATED; the refusal path is real.** The machine cannot be
pushed over the critical line without hurting the owner's live work, and a rule that has
never once fired is not implemented. What the simulation does and does not cover is stated
below the output.

```
=== CASE C — SIMULATED critical reading (the reading is simulated; the refusal path is real) ===
reading                  SIMULATED reading (mesh-pressure-proof case C) — not measured on this machine
band                     critical
broker calls made        0  (0 = refused before any ssh, so no lease was taken)
REFUSAL                  local-pressure-refused: committed 95 % of physical (at or above
  92 %) AND only 900 MiB physical memory available (below the 1536 MiB floor): this machine
  has no room to honour another turn, and the mesh IS reachable, so remote placement is what
  is wanted; nothing was dispatched and no reservation was taken. Retry when this machine
  is under its high line (85 % of physical committed, docs/mesh/109-pressure-routing.md)
ledger record            state=pressure-refused code=local-pressure-refused band=critical
```

* **Simulated:** the reading (`shapePressure(…, { source: 'SIMULATED reading … — not
  measured on this machine' })`, so the label is *inside* the reading and the ledger record
  cannot be mistaken for a measurement).
* **Real:** the threshold arithmetic, the band, the refusal decision, the typed error, the
  ledger write, the fact that the broker was never called (`brokerCalls = 0` — the counter
  wraps the real broker client, so a call would have been an ssh), and the mesh-reachability
  half (`mesh reachable true`, measured by asking the live broker's own `/healthz` over ssh
  in the same run).
* **Not covered by this case:** the "unreachable AND saturated" wording end-to-end
  (asserted by unit test only — `test/pressure.test.mjs`, *"critical pressure WITH an
  unreachable mesh refuses in the words that name both halves"*; proving it end to end would
  mean taking the placement broker down while the owner's sessions are live), and the
  `plugin-health`-absent branch of the reader, which was exercised separately by
  `bin/mesh-pressure.mjs --force-probe` (§4.1) rather than by removing the snapshot.

### 4.4 (d) Below the threshold, nothing regresses

Case B uses a **simulated calm reading** (40 % of physical committed) and the **real**
broker:

```
=== CASE B — SIMULATED calm reading (the reading is simulated; the broker is real) ===
DECISION                 ok — broker placed the child on "zabz-tech"
exclude sent to broker   []  (empty = exactly today's behaviour)
excludedLocalNode        false
```

`[]` is the whole assertion: on a healthy machine the broker receives byte-for-byte the
request it received before this change. The unit test *"under the high line nothing changes:
the broker is asked with the caller's own exclude list"* pins it more tightly still — a
caller that had its own hint gets `['lakewooechsmini']` and **not** the local node.

Evidence kept at `_scratch/109-pressure/`: `proof.txt`, `proof.json`, and the three ledger
records.

---

## 5. The defect this found in its own first draft, and what is still not right

Two things were wrong in the first working version, and both are recorded because both are
the class of error this program keeps making.

1. **The fallback probe overstated committed bytes by 64 %.** It computed
   `(totalPhys − availPhys) + (commitLimit − commitFree)` — a two-term sum whose second term
   already contains the first, because physical memory is part of the commit limit. Measured
   against `Get-Counter` in the same minute: **66,878 MiB against 40,695 MiB**, and a
   commit/limit ratio of 144 % where the truth was 88 %. It is now `commitLimit −
   commitFree`, one term, and it agrees with the counter to 0.2 % (§4.1). *A formula that
   looks like it is adding two independent quantities is the kind of arithmetic that gets
   cited for months.*
2. **The probe's 4 s timeout was too tight for a saturated machine.** Measured on this
   host with 30+ node processes: the same script that answers in ~1.2 s on an idle desktop
   was killed at 4,000 ms twice, and the reader correctly fell back to `unknown` — which is
   the honest answer, but it means the probe was useless exactly when it was needed. The
   bound is now 12 s, and it costs a dispatch nothing because the result is read by the
   *next* dispatch.

**What is still not right, stated plainly:**

* **`plugin-health` publishes no `committedBytes`.** It publishes `commitLimitBytes` and
  `commitAvailableBytes`, so committed bytes is a subtraction on the consumer side. That is
  fine and it is what this module does, but the number the broker, the calibration document
  and this module all reason about is not on the health surface. If `plugin-health` were
  mine to change it would publish it directly; it is readable but not writable from this
  task, and I have not touched it.
* **`agentsRunning` is null on the CLI path.** The live census comes from the engine
  (`ctx.agents.list()`); a shell has no engine, so `bin/mesh-pressure.mjs` reports `?` and
  the snapshot's `toolRunnerProcesses` stands in as a labelled floor. In the engine the
  census is populated, and that is the path that decides anything.
* **A remote child is invisible to this machine's counters and to the census.** §5.2 of
  `84-calibration.md` measured that on the *target*. It applies here in the other
  direction: a child this engine dispatched to `zabz-tech` is not a local agent loop, so
  the census is a count of *local* generating agents, which is what the label says.
* **The refusal is not enforced on `subagent_local` or `subagent_fork`.** Those are bound to
  the `spawn` and `fork` providers, which this package does not own and cannot gate. What
  this change can do about them it does: `describePlacement()` names the rule in the boot
  log, the report carries the reading, and an agent that reads it has the number in hand.
  Making it *impossible* needs a provider wrapper in the preset layer, and that is a
  separate change with a separate proof. **This is the single largest remaining hole, and
  §6 is where it should be closed.**

---

## 6. What needs a restart to activate, and what would finish the job

**Restart required, and not taken.** `remote-fanout` is a **host-plane** plugin row
(`~/.dsh/profiles/web/cordis.patch.yml:132`), and `~/.dsh/profiles/web/cordis.patch.yml` is
read at boot. Everything in this change is inert until the engine restarts: the running
engine (pid 4416, port 3099) has the old module in memory and keeps placing exactly as it
did. **I did not restart it** — it is serving the owner's live work, and
`docs/mesh/100-restart-when-idle.md` owns when that happens.

What a restart activates, exactly:

* the boot log line `remote-fanout: local pressure at boot — …` and
  `remote-fanout: pressure routing — …`, plus `describePlacement()`'s sentence naming the
  two thresholds;
* `createNodePlacer({ pressureReader, agentsRunning, meshCheck })` in place of the current
  no-argument placer;
* per placement: the reading, the `exclude` hint above 85 %, the refusal above 92 % with
  the floor breached, the ledger fields, and the two report lines.

Until then, `bin/mesh-pressure.mjs` measures the same reader the engine will use, and its
output on this machine is §4.1.

**The two changes that would finish this properly, neither of them in this task's scope:**

1. **Gate the local providers** (`spawn`, `fork`) so a *local* dispatch is refused on a
   saturated machine too. The seam's own shape for this is a provider wrapper registered in
   the preset layer, where `subagent_local` and `subagent_fork` are bound
   (`presets/zabz/agent.cordis.yml:375`, `:387`).
2. **Put the pressure signal in the broker's input**, so the *ranking* stops advertising 12
   free slots on a machine at 126 % of physical. `84-calibration.md` §4.4 already names the
   field: commit headroom, which the capacity contract could carry (`system.probe.commitAvailableBytes`
   exists on the engine's own `/healthz`, and `plugin-health` is not mounted on the
   authority). With this change, pressure arrives at the broker as an *exclusion* rather
   than as a reading, which is enough to move the work but not enough for the broker to
   say *why* it moved.

---

## 7. Appendices

**Files changed** (`packages/plugin-remote-fanout/`):

| file | what changed |
|---|---|
| `lib/pressure.js` | **new** — the reader, the thresholds, the decision, the two report lines |
| `lib/placement.js` | `acquire()` reads pressure, refuses, excludes the local node, records the decision; `PressureRefusalError` and its two codes |
| `lib/provider.js` | the two report lines; `describePlacement()` names the gate |
| `lib/index.js` | one reader per engine, the live agent census, the bounded `meshCheck`, the boot lines |
| `bin/mesh-pressure.mjs` | **new** — the reader as a CLI, with `--force-probe` and `--simulate` |
| `bin/mesh-pressure-proof.mjs` | **new** — the three cases of §4 |
| `test/pressure.test.mjs` | **new** — 15 tests: thresholds, decision table, sources, the four placement outcomes |
| `test/placement.test.mjs` | injects a calm reader, so the existing broker/no-node/queue assertions keep testing what they were written to test |
| `package.json` | `0.3.0`; `./pressure` export; the new files in `verify`/`test` |

**Verified, by command:**

```
node --check lib/pressure.js lib/placement.js lib/provider.js lib/index.js
node --test test/*.test.mjs                       # 104 tests, 104 passing, 0 failing
node bin/mesh-pressure.mjs                        # §4.1, spawns=0
node bin/mesh-pressure.mjs --force-probe          # §4.1, the fallback probe
node bin/mesh-pressure-proof.mjs --ledger <dir>   # §4.2-4.4
```

**Not verified, and what would verify it:**

* **No child turn was executed by this work.** Case A (§4.2) is a real broker decision, a
  real lease and a real ssh; it stops short of starting the remote agent. *What would verify
  it:* one `subagent` call from a session on a restarted engine, with the report's
  `pressure = …` line read back — which needs §6's restart.
* the "unreachable AND saturated" end-to-end path (§4.3);
* any behaviour **inside the running engine** — pid 4416 has not loaded this code, by
  design (§6);
* the local-provider gate (§6.1), which is not implemented;
* whether a *corrected* capacity contract would have moved the owner's work on its own.
  The broker ranked a saturated laptop as having 12 free slots (§1); that is the ranking
  defect, and this change routes around it rather than fixing it.
