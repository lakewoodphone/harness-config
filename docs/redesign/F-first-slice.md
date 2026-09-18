# F — The first slice: one node, one queue, one admission gate

**Stream F of the redesign. Owns exactly two files: this one and `measured-constants.json`.**
No code, no config, no script, no machine state, no service. **Date:** 2026-09-18.
**Author:** a delegated session (stream F), not the owner.

**What this document is.** The smallest end-to-end slice that would **prove or falsify** the model in
`D-architecture.md` on this fleet, in a form the owner can approve in one reading. It is a design, not a
build. Nothing below was run.

**Provenance convention, and it is the whole point of the exercise.** Every claim about what a machine
does is one of exactly three things, and the tag is on the claim:

| tag | meaning |
|---|---|
| **[M]** | **Measured** — a named document (A, B, C, D or the `docs/mesh/*` document they cite) ran a command and quoted its output. The document is named. |
| **[R]** | **Read** — read out of source, config or a live file. The path is named. |
| **[P]** | **Prediction** — mine. This slice has not been built and nothing here has been run. Every [P] is paired with the experiment in §3 that would settle it. |

**A prediction labelled as one is fine. A prediction presented as a measurement is the failure this whole
exercise exists to stop** — the exact failure in `A` Part 3, where a two-endpoint slope on the laptop
became "0.81 GB per generating turn" and was re-quoted as MEASURED by two later documents.

**And one thing I did verify by reading, this session, because it changes what this slice may assume:**
the correction to the refuted constant has **partly** propagated. Read 2026-09-18 at
`C:\Users\ezabz\code\harness-config`:

| copy | size | carries `0.81` | carries `403` |
|---|---:|---|---|
| `presets/zabz/skills/parallel-agent-orchestration/SKILL.md` | 10,802 B | yes — **as a warning, named inline** | yes |
| `presets/cordis-bg/skills/…/SKILL.md` | 10,802 B | yes — as a warning | yes |
| `$HOME/.dsh/.agent-presets/zabz/skills/…/SKILL.md` | 10,802 B | yes — as a warning | yes |
| `journal/presets/zabz/skills/…/SKILL.md` | 10,458 B | **yes — uncorrected** | **no** |
| `journal/presets/cordis-bg/skills/…/SKILL.md` | 10,458 B | **yes — uncorrected** | **no** |
| `packages/plugin-mesh-http/README.md` | 4,621 B | **yes — uncorrected** | **no** |
| `journal/packages/plugin-mesh-http/README.md` | — | **yes — uncorrected** | **no** |

**Three of the five deployed skill copies are corrected and two are not**, and the difference is visible in
the byte count — 10,802 versus 10,458. **Correction partial.** `journal/docs/mesh/` contains **no**
`parallel-agent-orchestration` directory at all, so the path `D` D10 and `B` §0 name does not exist at that
location on this tree; that is a correction to the record, not a refutation of the four copies that do
exist. And **no checker, no consumer and no clock** exist for any of it (§6).

---

## 1. Why this slice, and what "smallest" is allowed to mean

`D` §5 gives an eight-step migration. This is not that. This is the one vertical slice that, if it passes,
makes **the rest of `D` worth building**, and if it fails, makes them worth not building. It is chosen by
a single test: **which properties does the entire redesign rest on, such that no amount of later work
rescues them if they are false?**

Three, and they are all in `D`'s own words:

1. **A node cannot be blind to its own load, so the only component entitled to decide whether a node has
   room is the node itself** (`D` §7 sentence 1; §3.3.1). **This is the property the whole architecture
   exists to express, and it is the one the fleet has already failed.** [M] `D` D1/D2: on 2026-09-17 at
   22:12 the laptop advertised **12 free slots** while at **120–126 % of physical memory committed**, and
   the placement that decided that was `floor(physical cores × 0.75)` — a core count, with the memory term
   pinned at its cap on every node in the fleet (`84` §5.3, `95` §5.3).
2. **The queue can be quiet, and quiet is visible.** `D` §3.8 calls this *"the single biggest risk in this
   design"* — *"a pull queue cannot be blind to load, but it can be quiet"*. [M] `95` §0: the broker's last
   placement was `2026-09-17T04:12:42Z`, the newest dispatcher record was `04-14-39-996Z`, and **nine
   hours passed with every process live**. The design's own answer is that this must be proved *by
   deliberate failure, not asserted* (`D` §3.7 V4 and V9).
3. **A check that has not been observed failing is a claim, not a check** (`D` §3.7 V4, modelled on
   `verify-alloc.py`, which takes the pre-change rule out of git at `622876e`, never retyped, and proves
   it collides). [M] Sixteen checks in this estate reported success while the thing they named was false
   (`D` §3.7's catalogue). The redesign must ship with the failing direction demonstrated.

**Everything else in `D` is deliberately outside this slice**, and §7 lists it so that "it passed" cannot be
read as more than it is.

---

## 2. The slice, specified exactly

### 2.1 One node, one queue, one admission gate

```
  ONE NODE  (the office desktop, ZABZ-TECH)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │                                                                          │
  │   ┌────────────────────────┐     claim only when slots > 0    ┌────────┐  │
  │   │  THE STORE             │◄─────────────(pull)──────────────│ WORKER │  │
  │   │  a directory of        │                                  │  1     │  │
  │   │  one file per job      │──────── claim (atomic rename) ──►│ process│  │
  │   │  + one file per lease  │                                  │        │  │
  │   └───────────┬────────────┘                                  └───┬────┘  │
  │               │ durable: a restart cannot forget a claim          │       │
  │               │                                                   │       │
  │               │        ┌──────────────────────────────────────────▼────┐  │
  │               │        │ ADMISSION  (local, arithmetic, never a refusal)│  │
  │               │        │  reads this machine's own commit headroom,     │  │
  │               │        │  logical CPUs, turns IT admitted, owner reserve│  │
  │               │        │  → slots = max(0, min(memSlots, cpuSlots)      │  │
  │               │        │              - turnsInFlight - ownerReserve)   │  │
  │               │        └──────────────────────┬─────────────────────────┘  │
  │               │                               │ slots = 0 → DO NOT CLAIM   │
  │               │                               ▼                            │
  │               │                    ┌──────────────────────┐                │
  │               └────────────────────│ the job runs         │                │
  │                                    │ (a real child turn)  │                │
  │                                    └──────────┬───────────┘                │
  │                                               │ first billable step        │
  │                                               ▼                            │
  │                                    ┌──────────────────────┐                │
  │                                    │ THE WALLET'S GRANT   │                │
  │                                    │ local slice of the   │                │
  │                                    │ fleet ledger; at the │                │
  │                                    │ CEILING the turn     │                │
  │                                    │ closes `blocked`     │                │
  │                                    └──────────────────────┘                │
  └──────────────────────────────────────────────────────────────────────────┘
```

**Which node.** **ZABZ-TECH**, the office desktop. Reasons, [M]: it is the only node where
**a measurement above zero concurrency exists at all** — `93` §5.1 ran 12 concurrent requests through it at
13:53Z on 2026-09-17 and got 8 admitted / 4 queued / 0 refused with `maxInFlightSeen = 8` corroborated by
the OS process list; its derived limit is the best-measured arithmetic in the program (`93` §2.1,
every term traced to `84`). [P] And it is not the machine the owner sits at, so a slice that misbehaves
costs him nothing he is using — which is the whole point of `D` G2.

### 2.2 The store

**It is a directory of files on the node that owns the work.** Named, and deliberately outside every
existing live surface:

```
<DSH_HOME>/slice-queue/
    jobs/<job-id>.json          one file per job: the offer
    claims/<job-id>.json        one file per live claim: the lease (owner, ttl, attempt, expectedEnd)
    done/<YYYY-MM-DD>/<job-id>.json   settled, kept (never deleted), one file per job
    heartbeat/<node>.json       the worker's own claims-per-minute, written every tick
    log.jsonl                   append-only, one row per state transition
```

Four decisions inside that, each stated so it can be argued with:

1. **[P] One file per job, not one table.** The claim is an atomic `rename` of `jobs/<id>.json` into
   `claims/<id>.json`. A rename either happens or does not, so two workers cannot take one job, and a
   worker that dies mid-claim leaves a *complete* file, never a torn row. This is the same shape as the
   governor's proven lease protocol, [M] `90` §3: *one lease file per slot created `O_CREAT|O_EXCL`*,
   liveness by heartbeat rather than pid guess, reaping guarded by an atomic rename, and
   `governor-stress.mjs --contenders 30 --slots 5` finishing **30 concurrent acquires in 549 ms** with
   exactly 5 granted and 25 queued. **That protocol is the only concurrency mechanism in this estate with
   a measured adversarial result behind it**, and the slice reuses it rather than inventing a second.
2. **[P] It is NOT the company database, NOT the journal, and NOT the mesh broker.** `D` §3.8 SPOF 1 says
   the store *"is deliberately not the company DB, on a 4-core box whose swap read 81.2 %"*. [M] `30`-locks
   §2.2: `owner-queue.py` on `secratary` runs `executescript(SCHEMA)` on **every invocation including
   `next`/`list`/`stats` — "a read takes the database's write lock"**. A store that takes a write lock to
   answer a read is a store that becomes the next nine-hour silence, with a lock instead of a reason.
3. **Durability is the property that makes it a scheduler rather than a scheduler-shaped process.**
   [M] Today leases live in an in-memory `Map` (`packages/mesh-broker/lib/leases.js`, cited in `C` §10.2),
   so **a broker restart forgets every commitment**, and `76` §8 already lists *"behaviour under a broker
   restart mid-flight"* as unverified. §3.2's third experiment is that gap, closed and shown.
4. **[P] The store is a claim broker, not a decision plane.** It holds positions and leases. It does not
   rank nodes and it does not know what a slot is. **Nothing about a node's suitability is computed in
   it**, because that is the whole inversion (`D` §3.3.1).

### 2.3 What a claim is

**A claim is a durable row naming an owner and an expiry, written in the same atomic act that removes the
job from the queue.** Fields, all required:

| field | meaning |
|---|---|
| `jobId` | the immutable identity. [M] `108` §5.3's rule, earned with a **1,249-path deletion**: *prefer an immutable identifier — a commit hash, a blob id, a sha256 — over a mutable name, and when the two must be mixed, resolve the whole unit from the same reading.* |
| `node` | which node holds it. The published-node-name defect is real — [M] `93` §8(1) records an engine whose boot read saw `Self.DNSName: ""` and memoised the empty value for eleven hours — so the node name is written by the worker, never inferred. |
| `claimedAt` / `expiresAt` | the TTL. [M] The broker's is 900 s (`packages/mesh-broker/nodes.json`, `leaseTtlMs: 900000`). **The slice's TTL is `max(3 × the measured p95 job duration, 60 s)` and is a *field*, not a constant**, because `D` §3.3.8 item 2 requires a claim to carry an **expected end** so a queue can project rather than guess. |
| `expectedEnd` | Slurm's backfill input (`C` §9.3). [M] The fleet's jobs are short — a turn is ~12.1 s (`84` §1.2) — so a 40-second projection is the difference between a node idle for a minute and not. |
| `attempt` | an integer, incremented on each re-claim. This is what makes the at-least-once semantics of a lease honest (`C` §6.2): a lease means **at-least-once, always**, and the answer to "twice" is an idempotency key on the *effect*, not a promise from the transport. |
| `reportedHost` | the `MESH-HOST:` proof-of-location. [M] `D` §4.1: *"a placement system that cannot prove where work ran is an assertion, not a measurement"*, and it works — `92` §5.6 recorded `MESH-HOST: zabz-tech` against a ledger `reportedHost: "ZABZ-TECH"`. **An unverifiable claim of location is a lie with a timestamp on it.** |

### 2.4 How a node admits from its own measured capacity, without asking anyone

**This is `G` §1.7's revised admission contract, quoted verbatim, with every term's provenance stated.**
It is quoted here so the slice has exactly one definition and no second one can drift from it. **It
supersedes the pin this section carried before 2026-09-18**, which was `D` §3.3.2's formula unmodified:
`G` §1.1 shows that formula's `0.42` term is arithmetically `8 × 1.679 / 32`, so its CPU term reduces to
`floor(logicalCpus / 4)` — the deleted `0.75 × physical` in another unit — and `G` §1.2 therefore deletes
it as an original term and replaces it with `cpuSlots = floor(U_cpu / w)`, where `U_cpu` is a **per-node
measured** largest-sustained CPU load and `w` is the weight the work declares. (`G` §0 item 1 records the
same split for this document in its own words: *"the experiment F designs (`1a/1b/1c`) survives and is
strengthened; the formula it pins does not."*) The `§` references inside the block below are **`G`'s own
sections**, not this document's.

```
# EVERY TERM BELOW IS ONE OF: measured-this-node | measured-elsewhere-with-band | policy-with-a-stated-cost | refused

commitHeadroomMiB = commitLimitBytes - committedBytes          # plugin-health publishes both; committedBytes is a
                                                               # subtraction on the consumer side (109 §5) — a defect
                                                               # to fix, not a term to trust blindly
availableMiB      = min(freePhysicalMiB, commitHeadroomMiB - reserveMiB)
reserveMiB        = max(2048, 0.12 x physicalMiB)              # §1.3; policy, reasoned from the measured
                                                               # 410 / 1,174 MiB near-failure margins
memSlots          = floor(availableMiB / 530)                  # §1.4; 530 = top of the measured union, A §2.1
U_cpu             = this node's largest sustained CPU load     # §1.2; MUST be measured on this node
                                                               #   (ZABZ-TECH: 13.28 logical CPUs, N=8)
w(turn)           = 1.0 model-bound | 3.0 tool-heavy           # §1.2; declared by the work, 0.62 / 1.679 measured
leasesInFlight    = leases held in the node's slot directory   # §1.5; the governor protocol, one file per turn
weightInFlight    = sum of w over leasesInFlight
cpuSlots          = floor(U_cpu / max(w of the work being admitted))
slots             = max(0, min(memSlots, cpuSlots) - turnsInFlight - ownerReserve)
turnsInFlight     = weightInFlight (memory bound)  |  count(leasesInFlight) (CPU bound)
calibrated        = (U_cpu measured on THIS node) AND (the node's steady-state commit/turn exists)
```

Five things about it, and each is a correction of something measured to be wrong:

* **Commit headroom, not `swapUsedPct`.** [M] `84` §4.4 proves the published field is
  `max(0, committed − physical) / (commitLimit − physical) × 100`; that it reads **exactly 0.0 across a
  10 GiB spread of commit** on both nodes and in all 83 samples on ZABZ-TECH; and that at "90 %" it is
  within **410 MiB** of a hard allocation failure on the desktop and **1,174 MiB** on the laptop — *"a
  near-OOM alarm wearing a swap name."*
* **403 MiB, not 160 MiB.** [M] `84` §4.2: 160 MiB is *"one in-flight tool call inside"* a turn. It stays a
  tool-call constant and **stops being a placement constant** (recorded as such in
  `measured-constants.json`, entries `slot_cost_tool_call` and `commit_per_turn`). `G` §1.4 keeps 403.3 as
  the point estimate and sets the **admission divisor to 530**, the top of the measured union, until a node
  has its own steady-state curve: 403/530 = **76 %**, i.e. **24 % fewer memory slots**, stated there as the
  honest price of not knowing whether the node is over-admitting.
* **Logical CPUs, in the unit that was measured.** [M] `93` §2.1 records the units error that produced a
  limit of 14 once: `84` measured `CPU_PER_TURN` in *logical* CPUs and validated `0.75 × physical` in
  *physical* ones, and the SMT conversion was never measured (`84` §6.6) — *"a 33 % error waiting to
  happen."* `G` §1.2 keeps the unit: `U_cpu` is a **logical**-CPU quantity, which is why the deleted term
  could hide inside it.
* **`turnsInFlight` is a count the worker owns and nobody else can compute for it.** [M] `84` §5.2: in
  **all 83 samples** with 8 real concurrent turns running, the target's `/healthz` reported
  `agentLoopsRunning: 0`. A dispatched child is a separate process that never registers in the resident
  engine. [M] `84` §5.4 adds that a `node.exe` count is a bad proxy — 19…27, non-monotonically, at 8 live
  turns. *"Use a turn count or use nothing"*, and the only component that can count turns for certain is
  the one that admits them. **[P]** this is `ASSUMPTION A1` and §3.1's first experiment is its test.
  **What `G` §1.5 changes is where the count lives, not whether it is needed:** it becomes a **lease** in
  the node's slot directory, taken by *both* admitters — the engine's local children and the node worker —
  because `D` §3.3.2's *"what **THIS worker** has admitted"* leaves two private counters on one machine.
  The measurement above is untouched and remains the reason the count cannot be inferred from the OS.
* **`ownerReserve` is a floor remote work may never take on the machine a human is using** — and it no
  longer blocks anything. [M] `D` D2's complaint is that the laptop's own user lost his machine. This
  expresses *"he is sitting there"* as arithmetic in the one place that can enforce it. **`G` §1.6
  de-conflated what had been one term into two:** `ownerReserve` is an **integer slot floor, per node** —
  default **1 on ZABZ-YOGA**, the machine the owner sits at, and **0** on ZABZ-TECH and `secratary`, which
  have no interactive human at the console — while `reserveMiB` is the separate **memory** reserve of
  `G` §1.3. It lives in the node's policy record with its own provenance and date, is published on the
  strip, and changes by **config edit with no code change**. **[P]** So the slice proceeds either way: the
  default is buildable now, and §5's answer **tunes** the value rather than gating the work — which is the
  same test this document applies to a defensible default in §5.

**And it never refuses.** If `slots = 0` the worker simply does not claim, and the queue keeps the job with
its position. *Queue, never amputate*, kept where it is true — [M] the owner's own rule, and the one
structural decision in this estate that an adversarial audit could not break (`B` §7, F4/F5).

**The four states, replacing the five ranking tiers** (`D` §3.3.2):

| state | meaning | what it must print |
|---|---|---|
| `draining` | has slots, and has claimed within T | its own arithmetic and its claims/min |
| `full` | has no slots | its own arithmetic, term by term — **so a reader can see which term bound** |
| `stalled` | **has slots and has not claimed within T** | that fact, as a fault, with the age |
| `unknown` | no reading, and it says so | which reading failed and when |

[M] `D` §3.3.2 deletes `ok / slow / unreachable / capacity-unreadable / absent` **as ranking tiers**
because `95` §2.2 and `92` §6.3 show what a tier does when it is wrong, and `92` §5.3 shows what a *false*
`slow` costs: **the owner's own machine received zero children in an eight-child wave while it had more
free slots than the node that took all eight.** "Measured broken" and "never measured" stay different
facts — as facts on the node's row, not positions in a ranking.

### 2.5 What happens on claim expiry

**[P] Expiry is a state transition, not a timeout that kills work.** In order:

1. **A claim past `expiresAt` is re-claimable by any worker on the node.** The re-claimer writes
   `attempt + 1` and a new `expiresAt`, and appends one `log.jsonl` row naming the previous holder and the
   age of the expiry. **Nothing is deleted** and no running work is killed. [M] `D` §3.3.7 item 4: *"a local
   child already running when the machine goes critical is never killed. The rule is about admission, not
   eviction."*
2. **The previous holder is reported, not punished.** If it is alive and simply slow, it will finish and
   find its claim gone; its result is written under `done/` with `superseded: true` and the run is
   attributed to the live claim. [M] This is the at-least-once reality of a lease (`C` §6.2), and the
   mechanisms for it are idempotency keys and a defined turn boundary (`C` §6.3, §9.5) — **neither of which
   this slice builds**, which is one of §7's honest gaps.
3. **At `attempt > maxAttempts` the job goes to `dead/` and is surfaced**, not retried forever and not
   silently dropped. [M] `D` G1 falsifies on *"a job that is neither running, nor queued-with-a-position,
   nor reported failed"*, and a job that vanishes into a retry loop is exactly that.
4. **[P] The expiry sweep is run by the workers themselves, on their own tick, with no owner.** There is no
   reaper process and nothing to schedule, because [M] `D` §3.8 SPOF 2 already requires the worker to be
   *"a supervised process, not a session"* that *"can be restarted without touching the engine"*. A sweep
   that needs its own daemon is a second thing to be quiet.
5. **The single reversal of today's behaviour, kept:** [M] `92` §5.5 records the current rule in the
   transport's own words — *"no free slot appeared within 120000 ms; dispatching anyway (queue, never
   amputate)"* — and it is right when the target is merely busy and **wrong when it is unreachable,
   because at expiry the code cannot tell the two apart.** [M] And `93` §3: *"a run is not cancelled when
   the client disconnects"*, so a caller who gives up while the node is still working *"has paid for a turn
   whose answer nobody saw."* **Expiry returns position and reason to the caller; the work stays queued.**

### 2.6 Where the wallet's grant sits in the path

**Not at the claim. At the step seam, which is the first billable moment.**

Four facts settle the placement, and all four are measured:

* [M] `96` §5.1: the only seam that sees every billable step and can close a turn **without destroying
  anything** is the pre-step seam — `{kind:'reject'}` → *"the turn closes `blocked`, nothing is destroyed,
  the session resumes tomorrow."*
* [M] `96` §4.3: the provider publishes **no `x-ratelimit-*`, no usage headers and no usage API**, so there
  is no remote answer to ask; the grant must be a local decision taken against a global number.
* [M] `D` §3.4's split: **capacity is local and pulled; money is global and granted.** A claim is capacity.
  A grant is money. **They are different acts and putting the wallet in front of the claim would burn
  wallet on work that never starts.**
* [M] `D` §3.8 SPOF 7: the ledger may be unreachable, and the designed behaviour is a **deliberate trade** —
  work continues under each node's local allowance with a loud line saying the fleet total is unknown,
  because *"we prefer a bounded overspend to a stalled night"*, and the local figure is **published as a
  lower bound** (`96` §4.1: on the one reconcilable day the local logs were **50 % of the misses and 76 %
  of the hits**).

**So the path is: claim → admit (local, capacity) → run → at the first billable step, ask the wallet → if
granted, proceed; if refused, the turn closes `blocked`.**

**And the honest weakness, stated rather than papered over.** [M] `D` §3.4: *"a budget enforced on a lower
bound is a budget that can be breached by 2× while reporting green — which is the exact failure class in
G4."* The slice carries **one node's slice of the counter**, which is [M] today's real state: `D` §3.4 and
`101` §8.1 — *"on 2026-09-15, 56.5 % of the day came from ZABZ-TECH and this machine's logs saw none of it.
Until the layer-2 roll-up posts per-host totals into the authority … the fleet has no ceiling; each host
has one."* **The slice does not fix that. It proves the seam exists, is on the path, and fails closed**, and
§7 says so.

---

## 3. The experiments, with pass/fail and the command

Every experiment is a script under the slice's own directory. `PASS`/`FAIL` are asserted by the script's
exit code, never by a human reading output — [M] because the estate's own catalogue contains a gate that
was *"a comment wearing a gate's clothes"* (`D` §3.7 row 10) and an acceptance criterion its own command
could not satisfy, exiting 2 with three SKIPs, **every time, on any mesh, forever** (`95` §5.3).

**And every experiment's result is one of five values, not two** (`D` §3.7 V5): `PASS / FAIL / SKIP /
UNVERIFIED / STALE`, and **`SKIP` and `UNVERIFIED` are reds unless the contract explicitly names them.**

### 3.1 Experiment 1 — **a node never takes work it cannot hold**, including at 120 %+ of physical

This is the case that broke the old design and the reason the redesign exists.

**The state that must be refused is real and recorded, not hypothetical.** [M] `D` D2 and `109` §1: on
2026-09-17 at 22:12 the laptop's own `/mesh/capacity` document reported **`accepts.maxChildren: 12`,
`accepts.oneShot: true`**, while the machine held **120–126 % of physical memory committed** with
7.7 GiB free and 194 MB in the pagefile — and the broker, reading exactly that document, advertised
**12 free slots of 24**. At 22:43 it advertised **1**. [M] `109` §1's own sentence: *"because commit charge
is not in the contract at all. A dispatcher that asked the broker and obeyed the answer would have put the
child on the laptop, on the authority's own numbers, with no bug anywhere."*

**Three cases, and the third is the one that matters.**

**The formula under test is `G` §1.7's contract, quoted verbatim in §2.4 of this document — the one
definition — which supersedes the `D` §3.3.2 formula this section pinned before 2026-09-18.** The line the
experiment reads back is the same line as before:

```
slots = max(0, min(memSlots, cpuSlots) - turnsInFlight - ownerReserve)
```

**And every experiment in this document survives the revision unchanged** — `1a`, `1b` and `1c` here, and
`2a`–`2d` plus the deliberately-broken `stalled` detector in §3.2/§3.3. They are tests of **a node refusing
on its own numbers**, which is what the revised contract asks for *more* strictly, not less: `U_cpu` must be
measured on the node itself and a node without it reports `calibrated: false` (`G` §1.2, §1.7). **`1a` and
`1c` get stronger under `G` §1.7, not weaker** — `1c` in particular now tests the exact property the
revision makes load-bearing: a node deciding alone, from counters it reads itself, with no central component
and no second admitter's private counter to borrow. **Nothing here should be re-read as invalidated by
`G`** — `G` §0 item 1 says it in its own words: *"the experiment F designs (`1a/1b/1c`) survives and is
strengthened; the formula it pins does not."*

| case | setup | the node must | why this is the test |
|---|---|---|---|
| **1a — replay** | feed the admission function the **recorded** capacity document and the recorded commit state from 2026-09-17 22:12 | answer **0 slots**, and name the binding term | this is the *exact* input that produced "12 free slots". The assertion is a property of the output (`slots == 0`) read back through the path a consumer uses, not a shape test — [M] V3, earned by a pixel test in `87` §4.7: *"every test that could have been written against the function calls would have gone green."* |
| **1b — live, no load induced** | run the admission function **on the owner's working machine, right now**, with the config's reserve injected | answer **0 slots** and print its own arithmetic term by term | **[P]** It needs no induced load: the machine's own commit headroom divided by 403 MiB, minus the reserve, is already at or below zero on a busy evening. [M] At 23:47 local on 2026-09-17 it read 27,386 MiB committed of a 44,149 MiB limit with 13 agent loops running (`A` §1.11, §1.5) — so a reserve in the few-GiB range makes it 0 without touching a thing. **This case is a test of the arithmetic on real numbers, not of the machine's tolerance.** [M] `G` §1.6 de-conflated the two quantities the flag's name used to merge: the few-GiB quantity here is `reserveMiB`, the **commit** reserve of `G` §1.3, which is unchanged, and `ownerReserve` is now a **slot** floor (default 1 on this machine). `G` §0 item 2 states the surviving half explicitly — *"a reserve in the few-GiB range makes it 0 without touching a thing" remains true under the revised formula because the commit reserve term is unchanged.* |
| **1c — no central component** | **1a and 1b with the store path pointed at a non-existent directory and every network route to the rest of the fleet removed** | answer **0 slots**, and refuse **by itself** | this is the actual claim in the mandate: *"a machine at 120 %+ of physical must refuse by itself, **with no central component needing to know**."* The refusal must name the reading it used. [M] The behaviour is `109` §3.3's, already chosen for the remote path and extended to all of them. |

```bash
# 1a + 1c
node tools/slice/admit.mjs --replay 2026-09-17T22:12-0400.json --store /nonexistent --assert slots==0
# 1b + 1c  (read-only: it reads this machine's counters and computes; it starts no child)
# the <MiB> reserve passed here is reserveMiB (G §1.3, the commit reserve); ownerReserve is a SLOT floor
# (G §1.6, default 1 on ZABZ-YOGA) and is passed as an integer count, never as MiB
node tools/slice/admit.mjs --live --owner-reserve <MiB> --store /nonexistent --assert slots==0 --print-arithmetic
```

**PASS = exit 0 and the printed arithmetic names the binding term, in all three cases.**
**NOT PASS = any case exits non-zero, or returns slots > 0, or cannot say which term bound.**
**[P] Prediction: 1a and 1c pass by construction** (they are arithmetic on recorded inputs — if they fail,
the *formula* is wrong, which is itself worth knowing on day one). **[P] 1b is the uncertain one**, and it
is uncertain for a reason worth naming: [M] the laptop's own curve **does not exist** (`84` §6.1, `A` Part 5
item 2, `D` §6.2 item 1) — the constant production used for it was never measured on it. If 1b returns
slots > 0 on a machine a human can feel struggling, **the formula is calibrated on the wrong machine and
that is the finding**, not a test bug.

**What this experiment does NOT prove:** that the reserve is *right*. It proves the gate computes and
honours a refusal. The reserve's value is §5's question — and under `G` §1.6 the answer **tunes** the slice
rather than gating it: `ownerReserve` is an integer **slot** floor, defaulted **1 on ZABZ-YOGA** and 0
elsewhere, living in the node's policy record and changeable by a config edit with no code change. So `1b`
runs either way, and the owner's answer only moves a number.

### 3.2 Experiment 2 — **the queue can be quiet, and quiet is visible**

`D` §3.8 calls this the biggest risk, and `D` §7's last line says it is *"the one property in this document
that must be proved by deliberate failure rather than asserted."*

**The nine-hour silence happened because two different situations looked identical.** [M] `95` §0:
*"Nine hours of idle. The processes are live; the workload is not."* Every process answered, every port was
listening, every service was `active (running)` — and no work moved. **A pull queue can fail exactly the
same way, and it will look exactly as healthy.**

**The separating signal. Two fields, read over the same window, and neither alone is enough:**

| if | and | then the state is | the sentence the strip prints |
|---|---|---|---|
| `queueDepth == 0` | `claimsPerMinute == 0` | **`idle`** | *"nothing to do: 0 jobs offered in the last T."* |
| `queueDepth > 0` | **`claimsPerMinute == 0`** | **`stalled`** | *"N jobs waiting, 0 claimed in T, and node X reports M free slots. **Nothing is claiming work that is available.**"* — age named |
| `queueDepth > 0` | `claimsPerMinute == 0`, **and no worker has written a heartbeat in T** | **`stalled (no worker)`** | the worker is gone, and it says which node stopped writing and when |
| the store cannot be read | — | **`queue-unreachable`** | the age of the last successful read — **never 0** |

**The rule that makes it work, stated as the rule:** *a fleet whose health is the liveness of its processes
cannot distinguish those two cases.* [M] `D` §3.7 **V9**: *"a component's claim that it is running is not
evidence; count artefacts"* — measured twice in this estate: two of six fleet workstreams landed **zero
commits** while reporting *"running"* (`journal/state/open-pain.md` `P181`), and the nine idle hours.
**So the worker's health is claims settled per minute, and a node with slots that is not claiming is
`stalled`.**

**The experiments, in order, and the second one is the deliberate failure:**

```bash
# 2a  clean quiet — must report `idle`, and must NOT report `stalled`
node tools/slice/harness.mjs  --run quiet-then-busy

# 2b  the SAME store, the SAME worker, three jobs injected, and the worker PAUSED BY ITS OWN CONTROL FILE
#     (a documented pause verb: nothing is killed and no process is signalled)
node tools/slice/harness.mjs  --run stalled --inject 3 --pause-worker --for 90s

# 2c  the store made unreadable (directory permissions changed by the harness, on its own path)
node tools/slice/harness.mjs  --run store-unreachable

# 2d  the store RESTARTED MID-FLIGHT with live claims held — the property the in-memory Map lacks
node tools/slice/harness.mjs  --run restart-midflight --live-claims 6
```

* **2a PASS** = `idle`, `stalled` count 0, and **the strip's own text contains no claim of health** — the
  first version must not be allowed to print "ok" as a synonym for "I did not see anything".
* **2b PASS** = `stalled`, with the waiting count, `claimsPerMinute == 0` over a window **> 3 × the
  worker's own tick**, the age, **and the free-slot figure that makes it a contradiction rather than a
  lull**. [M] This is the exact failure the old fleet could not express, and `92` §5.2's `slow` alternating
  `ok, slow, ok` over three consecutive fresh reads is why the state is a **fact on the row** and not a
  tier in a ranking (`D` §3.3.2).
* **2c PASS** = `queue-unreachable` with the age of the last successful read — [M] and specifically **not**
  an empty result presented as health. [M] `D` §3.7's adopted rule, verbatim from `B` §A10: **"an empty
  result is not health"**, with `100` §3.2's worked example — *"no session row carries running=true"*
  printed when `session/list` had simply timed out.
* **2d PASS** = **every one of the 6 live claims is still held and still attributable after the store
  process restarts**, and the log shows the store's own restart. [M] This is the property
  `C` §10.2 measures as absent (in-memory `Map`) and `76` §8 lists as unverified. It is also, per `D` §5
  step M4, one of the two gates that make the queue worth having at all.

**`SKIP` is a red here.** If 2d cannot run for any reason, the whole slice reports `UNVERIFIED` and the
result is **not** "the queue works".

### 3.3 The check that must be **shown failing** before it is trusted, and how to break it deliberately

**`D` §3.7 V4: *"Every check ships with a demonstrated failure… A check whose failure has not been observed
is a claim, not a check."*** Within this slice I name **exactly one** such check, and it is the `stalled`
detector from experiment 2, because it is the check that guards the design's own biggest admitted risk.
**If `stalled` is never observed firing, the slice has shipped the sixth version of a green light over an
unwatched thing.**

**The breach, and it is cheap and safe by construction:**

```
tools/slice/break-stalled.mjs
  1. seed 3 jobs into the store
  2. start the worker with a control file that contains `pause`
  3. wait past the stall window
  4. assert the strip reports  STALLED  (this is the ONLY assertion)
  5. restore the control file to `run`
  6. assert the strip returns to DRAINING and the 3 jobs settle
  7. write the transcript to done/ with both halves
```

**The pass/fail is inverted from every other experiment: the script exits 0 only if step 4 OBSERVED the
failure state.** A run in which `stalled` never appears is a **FAIL** of the check, not a pass of the
system — which is the whole of V4 in one line.

**The safe form of "break it", and this matters because the mandate forbids killing anything.** The worker
is **paused by its own documented control file** (`heartbeat/<node>.json` gains `"pause": true`), not
signalled and not killed. **The slice starts no service and stops nothing it did not start itself.** If a
build ever needs a harder failure, the correct move is still not `Stop-Process`: it is to point a
**second, scratch worker at the same store** that never claims — [M] the pattern the record already uses
and trusts, the isolated `DSH_HOME` process on a scratch port with the owner's engine untouched, proven
**three times** (`92` §7, `105` §4.1, `106` §5).

**Two more checks in this slice ship with their failure demonstrated, both cheap:**

* **[M] the store's restart durability (2d)** — demonstrated by restarting the store with live claims, which
  is *literally* the failing direction of the property it asserts. The model is `verify-alloc.py`, which
  [M] takes the pre-change rule **out of git at `622876e`, never retyped**, and proves it collides
  (`108` §6.1) — so 2d must additionally run the **pre-change implementation** (an in-memory `Map`, the
  thing that exists today) and show **it** losing the six claims. A test that only shows the new thing
  working proves nothing about the old thing being broken.
* **[P] the admission gate's refusal (1a)** — demonstrated by feeding it a machine that genuinely has no
  room; and the **negative half is the one that matters** (`D` §6.1 `A10`): the same check must **not** red
  on a healthy node, or it is a check people learn to ignore. That is [M] exactly the failure this estate
  has already paid for: *"a keeper that can report a false RED is a keeper that gets ignored"*
  (`90` §7, where two consecutive runs of `install-client-plugins.ps1 -Check` minutes apart disagreed).

---

## 4. Rollback and blast radius

**What the slice creates.** [P] One directory (`<DSH_HOME>/slice-queue/`), one worker process, one
observer process, four scripts under `tools/slice/`, and **one config row** whose only job is to be
removable. Nothing else.

**What the slice must not touch, named rather than implied:**

| must not touch | why |
|---|---|
| **the owner's live engine — `pid 4416` on port 3099** | [M] it serves 16 windows, all sessions and all agents, it is a single point of failure (`A` §1.12 SPOF 1), and it has already failed to boot once for eleven hours. **The slice never signals it, never restarts it, and does not mount anything into it.** Its own processes are separate (the pattern [M] `D` §3.8 SPOF 3 relies on: a headless child keeps working while the engine is down). |
| **the journal** | [M] one global lock, measured hold times **41–98 s** against a 120 s foreground kill budget, with writers killed mid-write (`A` §1.12 SPOF 6, `30`-locks §0). The slice writes nothing there. Its own log is its own file. |
| **the gates** | [M] `phone-gate.py` is **the only non-loopback door** and the node's capacity surface to the mesh (`A` §1.5). The slice reads its own machine's counters directly; it does not add a route to the gate and does not read `/mesh/capacity`. |
| **the mesh broker** | [M] `95` §5.4: a field can be published, read into a structure, printed, and never consumed — and `D` §5 note 1 says **nothing is deleted before nothing reads it**. The slice does not modify the broker, does not call it, and does not shadow its files. The old path keeps working while the slice runs beside it. |
| **git state** | no `git add -A`, no branch, no commit, no reset, no force push. [M] The measured cost of ignoring this: two machines committed the *same change three seconds apart* and the result could not `git pull --ff-only` (`95` §6.3, exit 128). The slice's outputs are **untracked, or in one worktree, and staged by path only.** |
| **the spend guard's live counter** | [M] two engines on one host **share and overwrite** `~/.dsh/spend-guard/day.json` (`101` §8.2). The slice's wallet check **reads** that file and writes nothing to it. |

**The one command that removes it:**

```bash
node tools/slice/slice.mjs remove --and-shelve
```

`remove` stops the worker and observer **the slice itself started**, deletes the config row, and
**moves** `<DSH_HOME>/slice-queue/` to `<DSH_HOME>/slice-queue.shelved-<utc>/` — **it does not delete it**.
[M] `D` G1: a job is never silently dropped; a teardown that destroys the record of what the slice did is a
teardown that destroys the evidence that it worked. **No `rm -rf`, and no verb in the slice can delete a
`done/`, `dead/` or `claims/` file at all** — the code has no such path, which is a stronger guarantee than
a policy not to use one.

**What rollback does not restore.** Nothing outside the slice was changed, so nothing outside it needs
restoring. **[P] The one real residue is a claim a worker held when it was removed** — handled by §2.5's
expiry path, and the removal prints every un-expired claim it is leaving behind, with its expiry.

---

## 5. What the owner decides, and what is not asked

**One question, and only one, because it is the only item in this slice that is his rather than mine.**

**`ownerReserve`: how much of the machine you are sitting at must stay yours?**

Everything else in this slice is a development decision and is decided here: the store's shape, the TTL's
formula, the attempt limit, the four states, the scripts' layout, the choice of ZABZ-TECH, and the removal
verb. [M] The standing rule is his own words — *"these are dev questions, their not boss qs you do the dev
stuff, i do the boss stuff"* — and by the same rule the three candidate questions inside `D` (*should
non-urgent work be deferred off-peak?*, *should the laptop ever take remote work?*, *how much may a night
cost?*) each have a defensible default and are **decided, recorded and moved on**, not queued (`D` §6.3,
final bullet).

**Why this one is his, in one sentence.** [M] `D` §3.3.2: `ownerReserve` *"expresses 'he is sitting there'
as arithmetic in the one place that can enforce it"* — and *"he is sitting there"* is a statement about
**his tolerance**, not about a counter. [M] The measurements differ by node and by evening — the laptop
read 120–126 % of physical committed while its owner was working in it (`109` §1) and 13 agent loops were
running at 23:47 (`A` §1.1) — so no measurement picks the number. **It is genuine taste about a machine he
is touch-typing on, which is exactly the class that belongs in the queue rather than in a default.**

*(Asked as one question with one recommendation, in the conversation — not as a request to read this
document. [M] His rule, 2026-09-11: "i don't review things, if you have important questions for me, ask
them clearly and explained and i'll answer one at a time.")*

---

## 6. The keeper, and whether one exists today

`measured-constants.json` is `D`'s **V8** and `B`'s third-costliest assumption: *a corrected fact never
reaches the copies that act on it.* Its `how_to_use` field specifies the intended enforcement — a checker
that resolves each entry's `restate_glob`, extracts the number each deployed copy **states**, and fails when
that number is neither the canonical value nor a value named inline as superseded; run in **every reader
class** that loads the copy, because [M] *"a profile check is only evidence for the logon class that ran
it"* (`106` §8, measured: `exit=1 lines=16` over ssh versus `exit=0 lines=620` locally, same bytes, same
minute).

**Does such a checker exist today? No. Verified this session, read-only, four ways:**

1. [R] `scripts/harness-verify.ps1` is a real invariant checker — 11 `Check` blocks, exits non-zero on
   failure — but it validates **artefacts and services** (preset-in-sync, MCP rows, reaper task, sampler
   heartbeat, journal lock, bundle resolution, primary-port ownership, commit-vs-physical, stale MCP
   generations, preset-deployed-to-`~/.dsh`, bundle declarations). **It contains no check on any measured
   constant in any document, README or skill.** Its closest text, line 206, prints `~0.58 GB commit per
   extra node process` as a **string inside a check whose actual assertion is `commit < physical`** — it
   documents the correction in prose and asserts nothing about it. [M] That is the shape `D` §3.7 catalogues
   as a *green check over a broken thing*.
2. [R] `Get-ScheduledTask` filtered to `pwsh`/`powershell` actions returns **exactly one task** —
   `DSH Metrics Sampler Watchdog`, running `harness-metrics.ps1` from a `%TEMP%` snapshot. **Nothing runs
   `harness-verify.ps1`, and nothing runs a constants check.** [M] That task is itself
   `LastTaskResult 2147946720` and runs from a temp snapshot of the repo (`A` §1.8, §2.22) — the keeper
   that *does* exist is misconfigured.
3. [R] Grep for `measured-constants` / `constants.json` / `keeper` across every `.mjs` and `.js`: the only
   hits are two source comments calling themselves keepers (`install-mesh-profile.mjs`,
   `mesh-http.mjs`) — **zero consumers of this file**.
4. [R] Grep for the refuted literal `0.81` across every `.ps1`: two hits, both **a comment** in
   `harness-verify.ps1:201` explaining why the string was removed from a guidance message.

**So: no consumer, no keeper, no clock, no red path.** This file is data with no enforcement behind it, and
saying so is the point — [M] `D` §6.3 refuses to claim otherwise, and the alternative is a keeper that does
not exist being reported as one that does, which is the failure mode this entire exercise is about.

---

## 7. The honest cost: what this slice does not prove

**Read this section as the price of the word "passed".**

1. **It does not prove the fleet.** It is **one node**. [M] `D` §3.3.5 makes a partition a first-class state
   with a queue per site behind a Tailscale link measured at 27–45 ms laptop↔office (`71` §0) — none of
   that is exercised by one node with one store.
2. **It does not prove the wallet.** The grant's *existence on the path* is proved. **The ceiling's
   accuracy is not**, and cannot be here: [M] the local ledger is a **lower bound** — on the one reconcilable
   day the local logs were **50 % of the misses and 76 % of the hits**, so fleet-wide money should be read
   as **×1.3–2.0 low** (`96` §4.1, `D` §3.4) — and [M] the exact bill needs a **provider console export**
   that does not exist as an API (`60`-cost-audit §8.3). **A ceiling enforced on a lower bound can be
   breached by 2× while reporting green**, and this slice would report green while it happened.
3. **It does not prove the enforcement seam.** The slice's worker is *the* path, so there is nothing to
   bypass. [M] `D` D9 and `109` §5 name **the single largest remaining hole**: the pressure refusal *"is not
   enforced on `subagent_local` or `subagent_fork`"*, and [M] `109` §1 measures its consequence — the
   placement ledger recorded **no placement all day** *"because the model in each window chose
   `subagent_local` (or worked itself), and neither of those paths measures anything."* **A slice whose
   worker is the only way to run work proves nothing about the paths that skip it**; that is `D` §5 step
   M6.5 and it is not here.
4. **It does not prove the laptop, and the laptop is the machine the owner asked about.** [M] `D` §6.2 item
   1: the constant production actually used for it — `floor(16 × 0.75) = 12` — **was never validated on it**,
   because the laptop crossed the program's own 26 GB stop line before any fleet was dispatched. **The
   single highest-value missing measurement in this estate is untouched by this slice** (`84` §6.1,
   `A` Part 5 item 2), and it is a ~6-minute, ~90-turn rig.
5. **It does not prove anything above 8 concurrent turns.** [M] `93` §10.3: the region above 8 has never
   been measured on any node; `55` has never been run (`93` §10.8). Every scale claim in `D` is an
   extrapolation of a measured 8-point curve and a 32-request ramp, and the slice does not extend it.
6. **It does not prove gang admission.** [M] `D` §3.3.3: a 6-child fleet must reserve 6 slots at once or
   none, and the harness has never had it — `92` §5.3's `--hold 6` run was a **manual simulation** of the
   missing mechanism. Per-child claims in this slice can interleave and hold part of what they need, which
   is the exact pathology gang reservation exists to prevent.
7. **It does not prove at-least-once is safe.** §2.5's expiry path re-claims work. [M] `C` §6.2–§6.3 and
   §9.5: a lease means **at-least-once, always**, and the answer is idempotency keys plus a defined,
   idempotent turn boundary. **This slice has neither**, so a re-claimed job whose first attempt already
   had a side effect can double it. Named as an unproven property, not designed around.
8. **It does not prove the session catalog, the handle, the cull policy, session placement, or the fleet
   strip.** [M] The 25.4 s session-list walk and the proxy cache that hides it (`D` §3.2 item 1, `C` §7.3),
   addressability ([M] zero `pushState`/`replaceState`/`popstate`/`location.hash`/`sessionId` across all
   65 installed client bundles; pathname-only routing; a `?token=` exchange that 303s to literal `/` —
   `C` §9.2, §10.1), and the lifecycle policy that [M] `C` §10.1 calls *"a policy gap, not a bug"* are all
   `D` §5 steps M7/M7.5 and none of them is here.
9. **It does not prove the store is the right store.** §2.2 picks one file per job and argues it from the
   governor's proven protocol. [P] **The slice's own first experiment must therefore include the store,
   not just the worker**: 2d restarts it, and if a file-per-job store under Windows rename semantics
   behaves differently from the POSIX assumption, that is a day-one finding with a cheap fix (the same
   protocol with an `O_CREAT|O_EXCL` lock instead of a rename). [M] `D` §3.8 SPOF 1 deliberately leaves
   *where* the store lives open and assigns it to whoever builds M4, with a measurement behind it rather
   than an opinion.

**What it does prove, if it passes.** That a machine which cannot hold work **says so itself, with
arithmetic, with no central component consulted** — the property the fleet was bought for and does not
have. That a queue can be **quiet and be seen to be quiet**, with a signal that tells *"nothing to do"* from
*"nobody is claiming"* — the failure that survived nine hours undetected. That a claim is **durable enough
to survive the decider's restart** — the property the in-memory lease table lacks. That the check guarding
the design's biggest risk **has been observed failing**. And that all of it can be **removed with one
command that destroys nothing.**

**That is the smallest thing worth building, and it is not small.**

---

## 8. What I did and did not do

**Measured nothing.** Every [M] above is quoted from `A`, `B`, `C`, `D` or the `docs/mesh/*` document they
cite, with the document named. Every [P] is mine and is labelled.

**Read this session, read-only:** the seven deployed copies' sizes and whether their text carries `0.81`
and/or `403`; `journal/docs/mesh/`'s file list; `scripts/harness-verify.ps1` (the `Check` blocks and
line 201–206); `Get-ScheduledTask` filtered to `pwsh`/`powershell` actions; and a grep for
`measured-constants` / `constants.json` / `keeper` across `.mjs`/`.js`, and for the refuted literal across
`.ps1`.

**Changed nothing.** The engine `pid 4416` on port 3099 was not touched — not restarted, not signalled, not
read through any mutating route. No process was started, stopped or killed. No service was started. The
journal, the gates and the git state were not written to. **No fleet was dispatched and no child turn was
run.** The only two files written are this one and `measured-constants.json`.
