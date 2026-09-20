# G — Architecture v2: the revision against the red team's three kill objections

**Stream G of the redesign. Owns exactly one file: this one.** Nothing was written, moved, deleted,
started, stopped, restarted or reconfigured to produce it. The engine **pid 4416 on port 3099** was not
touched — not restarted, not signalled, not read through a mutating route. No service was started. The
journal, the gates, the broker and the git state were not written to. **Measured nothing.** Every
factual claim below cites `A`, `B`, `C`, `D`, `E`, `F` (including `measured-constants.json`) or a
`docs/mesh/*` document those cite; anything I add is marked **[G-ASSUMPTION]** with the measurement
that would test it. **Written:** 2026-09-18 on `ZABZ-YOGA`, reading the tree at
`C:\Users\ezabz\code\harness-config`.

**Mandate:** revise `D-architecture.md` against `E-redteam.md`'s three kill objections; fold in E's
seven new failure classes and its corrections to D's numbers; keep what E could not fault; restate the
deletions; give a buildability verdict.

**Read in full, myself, this session:** `E-redteam.md` (747 lines), `D-architecture.md` (1,304),
`measured-constants.json` (811), `F-first-slice.md` (632), `A` §4.1–§4.4 and §2.1–§2.2 and §2.9,
`C` §9. I did not re-read B in full; where I quote B I take E's and D's quotations of it and say so.

**What this document is and is not.** It is a **revision of D**, not a second architecture: it keeps
D's thesis wherever D earned it, and it changes a mechanism only where E showed the mechanism could
not work. It is **not** complete. Its most important content is the three places where the honest
answer is *"this is unresolved and here is what would settle it"* — and the single most important
finding in it is that **D's admission formula secretly re-derived the constant D deleted, and that
finding is fatal to the formula as written.** That is fixed here by deleting the formula's CPU term as
an *original* term and replacing it with a measurement-per-node requirement.

**Provenance convention, unchanged from D.** **MEASURED** = a named document took it live with a
command. **READ** = read out of source or configuration. **ARITHMETIC** = my own arithmetic over
measured inputs, labelled. **[G-ASSUMPTION]** = I added it, with the measurement that would test it.
**CUT** = removed from D's promise list by this revision. **REFUSAL** = asked for and not obtained.

---

## 0. Stream F is provisional input, and I treat it as such

`F-first-slice.md` is the first test of D and it is not final. Two reasons, stated before anything
depends on it:

1. **F reproduces D's admission formula verbatim as its slice's contract** (`F` §2.4: *"This is
   `D` §3.3.2's formula, unmodified, with every term's provenance stated [so] the slice has exactly
   one definition and no second one can drift from it"*). That is the formula this revision changes. **F
   §2.4 and §3.1 are therefore superseded by §1 of this document** — the *experiment* F designs
   (`1a/1b/1c`) survives and is strengthened; the *formula* it pins does not.
2. **F's `ownerReserve` question is still open and it is F's only owner question** (`F` §5). This
   revision does not answer it and does not wait for it: §1.6 gives a default that is a *policy with a
   stated cost*, changeable without a code change, so the owner's answer is an edit and not a
   prerequisite. F §3.1's case 1b — *"a reserve in the few-GiB range makes it 0 without touching a
   thing"* — remains true under the revised formula because the commit reserve term is unchanged.

F's keeper finding is not provisional and is carried forward as a **REFUSAL**: `measured-constants.json`
has *"no consumer, no keeper, no clock, no red path"*, verified four ways (`F` §6, `measured-constants.json`
`how_to_use.does_such_a_checker_exist_today`).

---

## 1. OBJECTION 1 — admission is undefined and there are two admitters per machine

**E's objection, in its own compressed form** (`E` §7 objection 1, §2.1): §3.3.2's formula has four
inputs and D fixes none of them; `0.42` is cited to a source that does not contain it and is
arithmetically the same single measurement as `1.679` divided by itself; and `turnsInFlight` is *"what
**THIS worker** has admitted"* while §3.3.7 step 1 admits local children **in the engine**, on the same
node, in a different process, with a private counter.

**This is the objection that decides whether there is a redesign at all.** A design whose scoring
function secretly re-derives the constant it deleted has not redesigned anything.

### 1.1 The finding, restated so it cannot be re-hidden

E's arithmetic, and I reproduce it because it is the single finding this revision must not leave
standing (`E` §2.1 item 3; inputs MEASURED, `A` §2.1, `A` §2.2, `measured-constants.json`
`largest_measured_cpu_occupancy_fraction`):

```
0.42 = 8 turns x 1.679 logical CPUs/turn / 32 logical CPUs   (ARITHMETIC, E §2.1)
     = 13.432 / 32 = 0.4198

cpuSlots = floor(logicalCpus x 0.42 / CPU_PER_TURN)
         = floor(logicalCpus x (8 x 1.679 / 32) / 1.679)
         = floor(logicalCpus / 4)                                   (ARITHMETIC)
```

On ZABZ-TECH (32 logical, `A` §1.11) that is **8** — the deleted `floor(24 physical × 0.75) = 18`'s
successor, and D's own calibration point. On ZABZ-YOGA (22 logical, `A` §2.13) that is **5** — and 5 is
`A` §2.13's *"the two calibrated constants"* sibling value and `93` §2.2's published derived limit
(`measured-constants.json` `derived_concurrency_limit_per_node`). The prediction reproduces the
production number on both machines, which is exactly what a hidden re-derivation looks like.

**Verdict, and it is a kill of the term, not a repair of it: D §3.3.2's CPU term is deleted as an
original term.** It is not wrong numerically; it is wrong as *design*, because it presents as a
calibrated two-constant capacity model something that is one division, and because `0.42`'s citation
(`84 §4.1`) does not contain an occupancy fraction at all (`E` §6.1, `measured-constants.json`).

### 1.2 What replaces it: the term is the measured quantity, with the coincidence named

The replacement does not hide the identity. It **prints it as the identity**, and it makes the
*validation state* of the node part of the answer.

```
U_cpu   = the largest CPU load this node has been observed to sustain
           with its own work still usable, in logical CPUs
cpuSlots = floor(U_cpu / w)         # w = the declared weight of the work being admitted
w        = 1.0  model-bound (model call + light tool use)
w        = 3.0  tool-heavy      (2.7x measured: 0.62 vs 1.679, A §2.1)
```

Six properties, each of which is checkable:

1. **`U_cpu` is a single measured quantity with one provenance**, not two constants that cancel. On
   ZABZ-TECH the only measured value is at N=8 tool-heavy: 41.5 % of 32 logical CPUs = **13.28 logical
   CPUs** (MEASURED, `A` §2.1's CPU table; `84`'s level table via E §2.1). Under the identity above this
   reproduces 8 slots, **and the document says that it reproduces 8, and that the number is not a new
   capacity claim**. `[LIVE]` `measured-constants.json` currently attributes `0.42` to `84 §4.1`; that
   attribution is what this revision corrects, and the corrected source is `84 §2.1`/§4.4/§5.2 as a
   partition-level occupancy.
2. **On a node with no measured `U_cpu`, the answer is not a number.** D's own refusal list applies:
   *"a reading without a source and an age is a refusal"*, and the same rule for capacity means a node
   without a measured curve reports `calibrated: false` (§1.5). This is not a new refusal — it is `A`
   Part 5 item 2 and `D` §6.2 item 1 promoted from a footnote to the admission contract.
3. **It stops being prompt-mode-blind, which was E's §2.3 objection to D.** D §3.3.2 needed to know
   whether a turn is tool-heavy or model-bound *before* it admits and never said which. Under the
   weight form, the work declares it and the counter sums weights — so 8 tool-heavy turns cost
   24 weight-units on a machine whose measured sustained load is 13.28, which is the measured
   over-commitment, now visible instead of averaged away.
4. **The cost of the change is a behaviour change and I state it:** the resident weight falls from
   1.679 to 1.0 for model-bound work, which *admits more* of it than D would have. That is what the
   measurement says is safe (0.62 logical CPUs of 13.28 available is 21x headroom per weight-unit) and
   it is the first time the design has used the resident figure for anything.
5. **The laptop's own curve is still missing, and this revision makes that a gate rather than a
   caveat.** `[G-ASSUMPTION G1]`: on ZABZ-YOGA, `U_cpu` is unmeasured and the CPU term reports
   `calibrated: false`; the node may take remote work only under the CPU bound of the last measured
   *resident* value on a comparable machine (ZABZ-TECH's 13.28 logical), minus `ownerReserve`, and the
   strip shows it. **Test:** `84` §6.1 item 1 — run the `84` rig from ZABZ-TECH against `zabz-yoga-1`,
   N=2…8, ~6 min, ~90 turns, after the laptop is back under ~12 GiB of commit; that produces the curve
   and retires the assumption.
6. **`measured-constants.json` gains two entries as a result** and loses no value: `U_cpu_zabz_tech =
   13.28 logical CPUs (MEASURED, N=8, one prompt class)` and `CPU_PER_TURN` becomes
   `w_model_bound = 0.62 / w_tool_heavy = 1.679` with their measured bands. The 2.7× spread stops being
   a two-valued unresolved parameter and becomes a declared input of the work.

### 1.3 `reserveMiB`: one value, by taking the term that fails in the safe direction

`measured-constants.json` records this as `unresolved` with two live values **~10 desktop slots apart**:
3,885 MiB (`scoring.js:70`) and `max(2048, 12 % of physical)` = **7,821 MiB** on ZABZ-TECH
(`93` §2.1, which attributes the formula to an `84 §4.4` that **does not state it**).

**The design decision, made here because it is a development decision and the standing rule is to
decide and record it.** Take the **larger** value:

```
reserveMiB = max(2048, 0.12 x physicalMiB)
```

Reasoning, not preference: of the two errors, **under-reserving is the one that hurts** — it advertises
room that is not there, which is D2's exact failure (`109` §1: *"A dispatcher that asked the broker and
obeyed the answer would have put the child on the laptop … with no bug anywhere"*), whereas
over-reserving costs throughput on a machine with no measured demand problem (`D` §3.9: the fleet runs
at ≈0.16 requests/s against a plan of 55). The 0.12 fraction is **[G-ASSUMPTION G2]**, and it is
reasoned rather than measured, but it is **not unconstrained**: the record already brackets the
near-failure band on both machines — within **410 MiB** of a hard allocation failure on the desktop and
**1,174 MiB** on the laptop, on a commit band **2–4 GiB wide** (`84` §4.4, MEASURED) — and 12 % of
physical lands at 3,885 MiB / 7,821 MiB, inside the same order as those measured margins. **Test:**
step commit charge toward the limit on each node under a real fleet and record the largest reserve at
which no allocation failure occurs; that replaces the fraction with a measurement. **Cost of choosing
wrong in the safe direction:** on ZABZ-TECH, 3,936 MiB ÷ 403 MiB ≈ **9.8 slots** of throughput.

**And the correction to the record this forces:** the keeper keeps **both** entries and both sources
(`E` §6.3 requires exactly that), because the *disagreement* is still a fact about two live code paths
even after the design picks one. Picking belongs here; hiding belongs nowhere.

### 1.4 `403` becomes `530` for admission, and the reason is the CI

`403.3 MiB` is the point estimate, 95 % CI **328.3…478.3** on the row-level fit and **271.5…533.0** on
the level-mean fit, union **≈270–530** (MEASURED, `A` §2.1). D §3.3.2 divides by the point estimate and
has **no safety factor**, and E notes the consequence: *"a node admitting to its own point estimate is
24 % over at the top of the interval"* (`E` §2.3).

**The revision divides by the top of the interval until the node has its own curve.**

```
memSlots = floor(availableMiB / 530)      # 530 = the top of the measured union, A §2.1
```

**Cost, stated plainly:** at the same `availableMiB`, this is 403/530 = **76 %** of D's slot count —
**24 % fewer memory slots**, which is the honest price of not knowing whether you are over-admitting.
**Reverse it per node**, not globally, when that node's own steady-state curve exists `[G-ASSUMPTION G3]`
— and note the record already has one node-local value *below* the estimate (**366 MiB/turn**, `93`
§5.2, *"inside the CI, 9 % below the point estimate"*), so a global constant would be wrong in both
directions at once.

### 1.5 The two admitters — the fix, and it is the old protocol rather than a new one

This is the load-bearing half of the objection and it has a mechanism available today.

**The problem, exactly.** §3.3.2 says `turnsInFlight` is *"what **THIS worker** has admitted and not yet
settled"*, and §3.3.7 step 1 admits local children **in the engine**. §3.8 SPOF 3 makes the node worker
*"a supervised process, not a session"* that survives the engine. So one machine has two admitters with
private counters, and D deletes `governor.budgetSlots` (§4.3) while **keeping the governor's lease
protocol** (§4.1) without wiring it to the formula. The measured proof the blindness class is real and
silent: **83 of 83 samples** with 8 real children consuming 3.0 GiB and 41.5 % of all logical CPUs
reported `agentLoopsRunning: 0`, and `governor.inUse` was **0 throughout** (`84` §5.2; `E` §2.1).

**The fix: the counter is a lease, not a variable in either process.** Both admitters take a lease
before starting any turn, and admission reads the lease count. This is `measured-constants.json`
`governor_budget_slots`'s own protocol, which is **the only concurrency mechanism in this estate with a
measured adversarial result behind it** (`F` §2.2 item 1, citing `90` §3): one lease file per admitted
turn, created `O_CREAT|O_EXCL`, liveness by heartbeat rather than pid guess, reaping guarded by an
atomic rename, proven by `governor-stress.mjs --contenders 30 --slots 5` → **30 concurrent acquires in
549 ms, exactly 5 granted, 25 queued**.

**What it costs.** One filesystem create plus a heartbeat per admitted turn and one reap per sweep, on
a path that is already the governor's; and it converts `turnsInFlight` from a process-local integer
into a shared quantity with a *failure mode* — a stale lease from a dead holder. That failure mode is
bounded by the TTL and is the reason the protocol carries a heartbeat rather than a pid.

**What it does not cover, and this is the honest limit.** Leases count **work that passes an admission
seam**. They cannot count work that never asks. Three named holes remain:

| hole | why it remains | how it is surfaced instead |
|---|---|---|
| **a model that works the task itself** | no provider seam sees it; D §3.3.7's last sentence already concedes this and `109` §1 measures it (*"chose `subagent_local` **(or worked itself)**"*) | the engine's own turn loop takes a lease at the step seam ([G-ASSUMPTION G4], and see §1.7), so a self-worked turn is counted **if** the engine is the engine this node's worker coordinates with — and the strip prints `uncountedTurns` as a first-class number rather than zero |
| **a shell** (`ssh secratary-ts …`, `dshw up`, `node …/bin.js web`) | `pwsh` is a different tool and §3.3.7's wrapper is not on that path (`E` §1.6b) | not fixed. Recorded as E's class 6, accepted-and-recorded (§3, row 6) |
| **the owner's own windows on this node** | they are the same engine; counted, but they are also the one load the owner feels | this is what `ownerReserve` is for, and it is enforced by the worker, which is the one component that can enforce it |

**What would settle whether the fix is sufficient — and it is E's own experiment, so it is already
specified** (`E` §7 objection 1): run `93` §5.1's rig on the laptop with **both** admitters live — N=8
in-session `subagent_local` children **and** a node worker holding 4 claimed jobs — and compare the sum
of the two private counters against the OS process count and `\Memory\Committed Bytes`. The method is
proven (the node's own counter and the OS list agreed at 8 of 8, `93` §5.1); D1's prediction is that
they will not agree. **Under this revision the experiment is runnable on day one**, because
`reserveMiB`, `U_cpu` and the weight table now have values and provenance.

### 1.6 `ownerReserve`: de-conflated from the commit reserve, given a default, and handed back as an edit

Two things were wrong with one term. D §3.3.2 uses `ownerReserve` as *"a floor of slots remote work may
never take on the machine a human is using"*, and D §6.3 makes a **default decision** rest on it
(*"should the laptop ever take remote work?" → "only in its reserve-free band"*) while **no value
exists anywhere** (`E` §2.1 item 4, `measured-constants.json`). F §5 correctly says it is genuine
owner taste and F asks it as one question.

**The revision separates two quantities that were one, and neither is a free parameter any more.**

```
ownerReserve   : integer slots, per node, default 0
commitReserve  : reserveMiB, MiB, from §1.3
```

`ownerReserve` is the **slot** floor for the human at the box; `commitReserve` is the **memory** floor
for the machine. Folding them into one term made D's arithmetic depend on a value that did not exist.

**The default, and the reasoning that makes it not-a-guess.** ZABZ-TECH and `secratary` have no
interactive human at the console by default → `ownerReserve = 0`. On **ZABZ-YOGA**, the machine the
owner sits at, the revision sets `ownerReserve = 1` **[G-ASSUMPTION G5]** — which is F §3.1's case 1b
made executable: at 27,386 MiB committed of a 44,149 MiB limit (`A` §1.11, `[LIVE]` 2026-09-17 23:47
local), `availableMiB = min(freePhysical, headroom − 3,885)` is already at or below zero *before*
`ownerReserve` is subtracted, so the value is a **floor on the worst case**, not a tuning knob, for
every state actually measured on that machine.

**And it is an edit, not a rebuild.** The value lives in the node's policy record with its own
provenance and date, is published on the strip, and changes with a config edit and no code change. So
the owner's answer to F §5 is a number typed once, and **nothing in this document is blocked on it** —
which is the test F itself applies to a defensible default (`F` §5, citing the standing rule).

### 1.7 The revised admission contract, in full, with every term's status

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

**Five behaviours that must be defined because `E` §1.1(b) showed D left them undefined.** D's
`stalled` is *"has slots and has not claimed within **T**"*, the cull policy closes a session *"idle by
both signals past **T**"*, and the supervisor boots the previous artefact when the new one *"fails to
become healthy **N** times"* — and **`T` and `N` are never given values** (`E` §6.3). A state whose
threshold is undefined **cannot be entered**, and a health surface with an unenterable fault state
reports health.

* **`T_stall` = 3 × the worker's own tick**, published by the worker (`[G-ASSUMPTION G6]`). Rationale:
  the tick is the only clock in the loop, so a reader cannot pick a `T` that makes a healthy worker
  look stalled; 3× is the same multiple F §2.5's spec uses for its stall window (`F` §3.2's 2b PASS
  criterion: *"a window > 3 × the worker's own tick"*).
* **`T_cull` is NOT given a default value in this revision.** It is one of the two values whose
  measurement does not exist: `measured-constants.json` `idle_window_cpu`'s `note_idle_culling` records
  **"NO measurement exists for the cost of an idle WINDOW CULL, and no cull policy exists to
  measure"**, and A Part 5 item 13 records the launcher's own close/reap behaviour as still unexplained
  (*one live origin against fourteen registry rows*). **The cull policy ships with `T_cull` unset and
  the lifecycle feature OFF**, which is a **CUT** relative to D §3.5 item 2 (§4). `[G-ASSUMPTION G7]`
  **Test:** F §6's A13 rig — a session idle from the server's view with a live proxy connection, and the
  reverse — measured with the cull disabled, producing the two signal distributions that `T_cull` is a
  quantile of.
* **`N_activation` = 3 consecutive failed health checks**, matching the incident's own observed retry
  count (*"The launcher retried three times and never showed the answer that was already in the log"*,
  `D` §3.6, `incident` §7.3). The *number* is not the defect there and this is not a claim that it is
  fixed: E §5's keeper finding — a non-zero exit into a task set where non-zero is already normal
  background (`A` §1.8: `2147946720`, result 1, a Disabled watchdog) — stands as class 7 / `E` §1.7b,
  accepted-and-recorded.
* **`unknown` has a defined behaviour** (E §1.3d showed D's did not). `unknown` (no reading) means **do
  not claim**, and the job keeps its position. Rationale, and it is the record's own: claiming without a
  reading reproduces **12 free slots on a machine at 126 %** (`109` §1), while not claiming is bounded by
  the `stalled` detector, which now has a value for `T` and was already designed to fire on exactly
  this shape (`F` §3.2). **So `unknown` degrades to "quiet and visibly quiet", not to "blind and
  confident".**
* **A node with `calibrated: false` is disclosed, not excluded.** It may take work up to its
  conservative bound, and every surface that shows its slots shows the word `uncalibrated` beside them.
  Excluding it would be the `slow`-demotion defect with a new name (`92` §5.2: the owner's own machine
  received **zero** children in an eight-child wave).

---

## 2. OBJECTION 2 — the wallet is reported and enforced locally, not granted

**D §3's headline claims *"money is global and granted"*. §3.4 describes no grant protocol** (`E` §2.2).
What it describes is a local step-seam check against a counter §3.4 itself calls a lower bound that
*"can be breached by 2× while reporting green"*, a display, a placement input, and per-machine
envelopes. §3.8 SPOF 7 chooses to keep spending when the authority is unreachable; the fleet-wide cap
is **12 per machine**, so four nodes admit 48 generating agents with no fleet total; and the guard
counts **this host only** — on 2026-09-15, **56.5 % of the day came from ZABZ-TECH** and this machine's
logs saw none of it, whence *"the fleet has no ceiling; each host has one"* (A §2.9, `101` §8.1).

### 2.1 The honest answer first: money cannot be granted on this fleet, and here is why

A grant is a promise: *"you may spend up to X, and the thing that issues X knows the total."* Issuing
that promise requires the issuer to be able to measure the resource. **On this fleet it cannot, and the
record says so in three independent ways:**

1. **The provider publishes no usage surface at all** — no `x-ratelimit-*`, no usage headers, no usage
   API (A §2.9, `96` §2.2/§4.3, MEASURED).
2. **The local ledger is a lower bound by a measured factor** — on the one reconcilable day the local
   logs captured **50 % of the misses and 76 % of the hits**, so fleet-wide money reads **×1.3–2.0
   low** (A §4.2 B12, `96` §4.1, MEASURED).
3. **The exact bill requires a console export that does not exist as an API** (`60`-cost-audit §8.3;
   `D` §6.3 records it as a dependency only the owner can satisfy).

**You cannot grant a resource you cannot measure, and any "grant" built on this ledger would be a
number with the authority's confidence attached to a quantity that is known to miss between a quarter
and half of the requests.** So: **the sentence "money is global and granted" is deleted from the thesis.**
That is a **CUT**, and it is the correct answer to the half of E's objection that asks for the sentence
to be removed if the grant is not designed.

### 2.2 What is actually built instead — a grant for the one countable resource

The revision does design a grant, for the resource that **is** exactly countable, exactly single-writer,
and currently has no fleet total: **concurrent generating agents.**

```
FLEET GRANT (concurrency only)
  resource   : one generating agent = one lease row, durable, TTL'd
  writer     : exactly one — the queue store (a single process; §3.1)
  scope      : fleet-wide, `fleetConcurrencyCap` = 4 nodes x 12 = 48, OR the owner's number
  protocol   : worker requests k leases; the store grants min(k, cap - held) or queues
  survives   : (a) a store restart  -> rows are files, not a Map (C §10.2, F §2.2 item 3)
               (b) a tailnet partition -> the store is on ONE site; the other site's workers
                   cannot reach it and fall back to their own per-machine cap (below)
  refused at : cap, and the refusal names the reading (leases held, cap, age)
```

**Why this is better than what D had, and it is a small change with a large property:** the number
**12** stops being a per-machine policy that nobody sums (`D` §3.4 item 5) and becomes a fleet total
that a single writer holds. The **48** figure is no longer an accidental product; it is a stated cap
with one owner.

**And the cost of the fallback is stated as the price, not hidden:** during a partition the store is
unreachable from the far site, so the far site runs under its own per-machine cap. **The bound on the
error is exactly (nodes on the far site) × 12 held leases**, because a lease is countable. **The
revision says plainly: the fleet concurrency cap is exact while the store is reachable and is bounded
by `n_far × 12` while it is not.**

### 2.3 And the money model states the weaker property it actually has

The money ceiling stays enforced **locally, at the step seam**, which is right for reasons D already
established and this revision does not re-open: the step seam is the only place that sees every
billable step and can close a turn without destroying anything (`96` §5.1, `D` §3.4 item 1). What
changes is the **claim**:

| property | D's claim | G's claim, and the residual race |
|---|---|---|
| money | *global and granted* | **local enforcement against a global display and a conservative reserve** |
| the fence | a per-node counter | the counter multiplied by the measured lower-bound factor before it is compared to the ceiling (`D` §3.4 item 4's own *"reserve against a multiple of the ledger figure"*, now mandatory and not optional) |
| the residual race | not stated | **N nodes each holding their own unconsumed headroom, plus `(N−1) × per-node allowance` after a partition** (exactly E §2.2's two-nodes-each-holding-$10, now named and bounded by the node count rather than by nothing) |
| the per-machine cap | *"12 generating agents per machine"* presented inside a fleet-wide money envelope | **it is a capacity bound, not a money bound**, and it is now granted from a single writer (§2.2) instead of assumed |
| the display | spend today, rate, ceiling | the same, **plus** the age of the last reconciliation and the word `LOWER BOUND` on the number, because `V7`/`96` §4.1 require it |

**What would change the answer, stated as the measurement rather than a wish** (E §7 objection 2):
two machines spending simultaneously against the authority, at 90 % of the ceiling, and a reading of
whether **both** stop before $150 or **each** stops at its own $150. The design's own M3 gate — *"a
synthetic step at the ceiling closes the turn `blocked` and spends nothing"* — is a **single-machine
test and cannot detect the race** (`E` §7 objection 2), so it is not a substitute. `[G-ASSUMPTION G8]`
**Test, exact:** run the two-node ramp; if both stop before the ceiling, promote the money ledger to a
real grant on the strength of a *summed* ledger that has been reconciled at least once; if not, keep
this weaker property and record the measured overshoot as the bound.

**What is not claimed and never will be by this document:** that the enforcement path works. It has
**never been observed refusing anything live** — `lastVerdict: "ok"`, no live cap refusal demonstrated
(A Part 5 item 19, `D` §3.4). That stays a REFUSAL until the M3 gate runs against the ceiling.

---

## 3. OBJECTION 3 — the pulled queue cannot execute three of D's own mechanisms

**E's objection** (`E` §2.4, §7 objection 3): §3.3.1 deletes the decision plane (*"the store is a claim
broker, not a decision plane … nothing about a node's suitability is computed there"*) and then
specifies three things that need a ranker able to refuse a claim: gang admission (§3.3.3), the
committed-until backfill of §3.3.8 item 2 (*"a job that fits sooner goes sooner"*), and per-job spread
(§3.3.8 item 1). And **M6's gate (*"positions in arrival order"*) and §3.3.8 item 2 cannot both pass** —
which is D §3.7 row 3's own worst shape (*"the contract names a command that cannot satisfy it"*),
written into the new design's acceptance criteria.

### 3.1 The ruling: the store refuses for rules it can evaluate, and never for suitability

One sentence replaces the ambiguous one, and it is testable:

> **The store refuses a claim only for a rule it can evaluate from the job and the claim table —
> already claimed, wait expired, a declared exclusive resource already held, a sibling of the same
> spread group already live on that node, a resource the store owns being exhausted. It never refuses,
> ranks, scores or excludes anything based on a property of the node.**

This keeps C §9 item 3's dropped prerequisite honestly: *"every scarce resource must be represented as
an integer a single writer controls"* (`C` §9 item 3). The revision **names which writer controls
which integer**, which is the part D left dangling:

| scarce resource | represented as | the single writer | source of truth |
|---|---|---|---|
| a node's slots | the node's lease directory | **the node** (its slot governor, §1.5) | one file per admitted turn |
| a node's CPU budget | `U_cpu` minus the weight of live leases | **the node** (§1.2) | the same leases |
| commit headroom | `commitLimitBytes − committedBytes` | **the OS** (read, never computed) | `plugin-health` |
| fleet concurrency | lease rows | **the queue store** (§2.2) | `claims/` |
| a job | one job file | **the queue store** | `jobs/` |
| an exclusive path (repo, worktree) | a lock row | **the queue store** | `claims/` |
| **a gang's 6 slots** | 6 leases on **one** node | **that node** | its slot directory |
| **spread-group exclusivity** | one lock row per (group, node) | **the queue store** | `claims/` |
| the wallet | a counter with a measured lower-bound factor | **nobody — see §2.3** | per-node ledger files |

### 3.2 Gang admission: **CUT to single-node, and the cut is stated as a guarantee**

D §3.3.3 says *"A 6-child fleet must reserve **6 slots at once, or none** … the reservation is
**atomic** (one writer, one critical section)"* and names no writer. If the store performs it, it must
know each node's admissible slots — which is precisely the *"suitability … computed there"* that §3.3.1
forbids; if a node's worker performs it, a gang spanning two nodes cannot be reserved atomically by one
writer, and a node can only reserve a gang it has already claimed a member of, which it cannot claim
without reserving (`E` §2.4, verbatim in substance).

**The design ruling: a gang is single-node.** The requester asks a node for six slots; the node's slot
governor takes all six atomically or takes none; the store never participates. **The guarantee this
buys, stated in the form it can be held to:** *a 6-child fleet either reserves six slots on one node or
is queued whole; it never starts five-of-six.* **The guarantee it does not buy: a gang spread across two
nodes.** That is a **CUT** relative to D §3.3.3, and it is the honest one, because the multi-node case
is the case that needs the arbiter D refused to build in one place and built in another.

**Three things that make the cut safe rather than merely convenient:**

1. **The measured precedent is single-node.** `92` §5.2's eight-child wave landed **seven on the
   desktop and the eighth did not go to the laptop** — the fleet's own behaviour has been single-node
   placement of a fleet, and `92` §5.3's `--hold 6` run was the manual simulation of the missing
   mechanism (`F` §7 item 6). A single-node gang is *strictly more* than the status quo.
2. **It restores a deleted field with a purpose.** D §4.3 deletes `accepts.maxChildren` as a *published
   measurement*, and D §3.3.3's gang admission then needs *"how large a fleet this node can take"*,
   which the new contract does not carry (E §4's deletion table calls this **unreplaced**). **Fix: the
   node publishes `maxGang` — the largest reservation it can take whole — as a computed quantity, not a
   constant.** The keeper keeps `accepts_max_children = 12` with its provenance (`phone-gate.py:939`, a
   documentation example) and marks it **superseded by `maxGang`, a computed value**; the constant is
   never published as a measurement again.
3. **A gang on a node whose `U_cpu` is unmeasured is refused with the reading named** — the same
   `calibrated: false` disclosure as §1.7, not a silent default.

**What settles whether even the single-node gang is worth it** (`E` §7 objection 3, `F` §7 item 6): run
M6's rig offering, at the same time, a 6-child gang and four single jobs to a fleet with 7 free slots
split 4 + 3, while one node holds a claim-ahead buffer of its own slot count; record whether the gang
ever starts whole and whether any single job passes a gang. Under this revision the *multi-node* half
of that experiment is **out of scope by construction**, and the single-node half is a two-node test.

### 3.3 Committed-until backfill: **CUT as an ordering rule, kept as a displayed projection**

§3.3.8 item 2 (*"a claim carries an expected end, so a scheduler can say 'this node is free in 40 s' …
and **a job that fits sooner goes sooner**"*) is a backfill scheduler — a ranker with a queue it
reorders — and §3.3.1 removed the ranker and provides no reorder point (`E` §2.4). M6's gate is
*"positions in **arrival order**"*. **They cannot both pass.**

**Ruling: arrival order is the contract; `expectedEnd` is a projection and never an ordering input.**

* `expectedEnd` stays on the claim (§3.3.1's durable rows, F's claim schema). It is what lets the strip
  and the caller read *"this node is free in ~40 s"*, and *"the fleet's jobs are short — a turn is ~12.1 s
  (`84` §1.2) — so a 40-second projection is the difference between a node idle for a minute and not"*
  remains a true statement about **information**.
* The promise *"a job that fits sooner goes sooner"* is **deleted**, and with it the backfill scheduler.
  **M6's gate then passes as written.**
* **What is lost, stated as a cost:** a job that could fit a gap waits behind a longer job. On a fleet
  whose units are ~12.1 s and whose largest measured queue depth is **4** (`A` Part 5 item 8), the
  measured queueing cost of this loss is small — but that is a *reasoned* claim on a fleet that has
  never been loaded above 8 concurrent turns, so it is marked **[G-ASSUMPTION G9]** and the measurement
  that tests it is the same M6 rig with a mixed short/long job stream.

### 3.4 Per-job spread: kept, because it is a rule the store can evaluate without ranking

§3.3.8 item 1 (*"**spread is a property of the job, not of the fleet** … So `spread` becomes a field on
the job"*) does **not** have to be dropped, and E's objection here is answerable without an arbiter:
enforcing spread *"requires the store to refuse a claim from a node that already holds a sibling — again
a suitability decision"* (E §2.4). **It is not a suitability decision about the node; it is a rule about
the identity of an already-written row**, which is exactly the class §3.1 permits. The store asks *"does
a live claim row exist for this spread-group on this node?"* — a lookup in a table the store itself
owns — and refuses if the answer is yes. **No node is scored, ranked or excluded.**

**The mechanism, so the single writer is explicit:** when a job carries `spreadGroup`, its claim writes
a lock row keyed `(spreadGroup, node)`; the lock is released when the claim settles or its TTL expires;
a new claim is refused if the row is live. The lock row lives in the store, so the writer is single, and
the TTL means a dead holder cannot wedge it.

### 3.5 The claim-ahead buffer — kept, but it must be *visible*, because E showed it creates an invisible wait state

D §3.3.1 lets a node *"claim ahead (a small local buffer of claimed jobs, bounded by its own slots) so
the store's latency is amortised"*. E §1.4a is right about the consequence: a job sitting in that buffer
has been **claimed**, so the queue reports it taken, the fleet strip reports no waiting work, and the
node reports `draining` — while the job is not running. `stalled` is defined as *"has slots and has **not
claimed**"*, so a node with slots that claims and does not start is, by D's own definition, healthy.

**The fix is the same shape as §1.5's: make the state countable and publish it.** The worker's row gains
`claimedNotStarted` (an integer) and the strip prints it, so **the claimed-but-not-running buffer is a
number on a surface rather than an absence.** `stalled` is redefined as **`slots > 0` and
`claimsSettledPerMinute == 0` and `claimedNotStarted > 0` for longer than `T_stall`** — which is
strictly the failure F §3.2's 2b experiment was designed to detect (*"N jobs waiting, 0 claimed in T,
and node X reports M free slots"*), with the buffer added so the buffer cannot hide inside it.

---

## 4. E's seven new failure classes — fixed, or accepted and recorded

E §1's table, in its own order. **FIXED** means this document changes a mechanism to close it. **ACCEPTED
AND RECORDED** means it stands, is named, and has a stated consequence — the standing rule is that a
problem with a solution I can find is not reported, so everything in the second column is either
unfixable within the thesis or is a cost accepted in exchange for something measured.

| # | E's own version of the pathology (`E` §1) | status in G | what changed, or the reached cost |
|---|---|---|---|
| **1** | **A check that cannot fail.** V5's SKIP/UNVERIFIED escape hatch lets a contract author authorise the same skip that broke `mesh-e2e.ps1`; `stalled`/cull/`N` were defined by an unbound `T`/`N`. | **FIXED** | §1.7 gives `T_stall`, `T_cull` (**unset → the cull policy ships OFF**, §4), `N_activation`; **and the keeper is extended to the contract itself** — V4's "demonstrated failure" requirement now attaches to the *executable contract*, not only to checks, so a contract that names a command which cannot satisfy it is itself a failure (V5's own wording, enforced instead of stated) |
| **2** | **A stale view on a cached local ref.** The fleet strip's freshness is never stated; the proxy keeps **one** session list, which M7 makes wrong content the moment two windows point at two nodes; the catalog is said to be written *"in the same critical section as the mutation"*, which is engine code — H-class on the engine D says must not need restarts. | **FIXED for the strip, ACCEPTED for the catalog** | **Strip:** the cached RPC is replaced by a read that **carries its age and refuses to render a reading older than `T_strip`** — the V7 rule applied to the one surface that shows them all; and **the single-response cache is scoped per origin**, because M7 makes one cached `session/list` wrong for every window but one (`E` §1.2a). **Catalog:** the writer is named — it is **engine code** (the session store's own critical section), which makes it **H-class**, and it therefore sits **behind the cold-boot gate of §6** and is not a step this revision claims can be taken without a restart. That is a **CUT** of D §3.2 item 1's "activation-free" implication. |
| **3** | **A silent fallback.** A local child never touches the queue, so the load that matters most is invisible; the proxy-fallback origin proves the *engine* answers and not that the *session* is the right one; the partition case is answered twice, differently; `unknown` has no behaviour. | **FIXED (three of four)** | **Local children:** they now take a **lease** (§1.5), so they are counted even though they never touch the store; and the worker's row publishes `localChildren` so the queue's silence about them is disclosed. **Fallback origin:** `Resolve-WindowUrl` must survive a **request that proves the session**, not merely the engine — the check reads back the session handle and compares it to the requested handle, which is `V3` (assert a property of the output, read through the path the consumer uses) applied to the exact `Test-LaunchUrl` failure class (`A` §3.7 row 14). **Partition:** resolved to **one store per site** (§3.1's single writer is *per site* for the queue store, and §2.2's fleet concurrency store is on the authority) — **so D §3.3.7 step 3's "the queue is unreachable → refuse" is retained only for the authority-side fleet-concurrency store, and the queue itself is never unreachable within a site.** `[G-ASSUMPTION G10]` The `E`-noted consequence is accepted: with a store per site, `D` §3.3.7 step 3's refusal is **nearly unreachable and is close to dead code**, which is stated rather than pretended. **`unknown`:** defined, §1.7 — do not claim. |
| **4** | **Work that looks running but is queued/waiting, inverted.** The claim-ahead buffer; the gang reservation idling 5 slots; a local child that is invisible, unleaded and dies with its engine. | **FIXED** | Buffer: `claimedNotStarted` published and `stalled` redefined (§3.5). Gang: single-node and atomic, so the reservation is a **lease on one node's governor** and is therefore visible in exactly the same counter as everything else on that node (§3.2). Local child: takes a lease (§1.5) — **and the honest residual is stated**: an in-engine child is `NM\dsh-subagent-spawn-in-process`'s *"fresh child Agent on the same cordis context"* (`A` §1.1), so it **has no separate process to leak and no lease it can outlive**; what it does have is the engine's own liveness, which is a **named SPOF** (E §1.5a) rather than an invisible one. |
| **5** | **A SPOF nobody named.** (a) the guard's import, which took the whole engine down once and which M3 makes load-bearing on **every** node; (b) every node's self-report has no second reader. | **(a) FIXED, (b) ACCEPTED** | **(a)** The guard's module-resolution path gets the **cold-boot gate's Appendix-B regression** applied to it — the incident's own one-liner (`Remove-Item Env:DSH_HOME; node -e "import('…/guard.js')…"` → must print `LOADED`), run per reader class. This is E's own finding (`A` §1.12 item 7: a one-segment path mistake in that row *"took down the entire engine"*) and it is fixed by a check the estate already trusts. **(b)** *"There is no component in the new architecture whose job is to disbelieve a node"* (`E` §1.5b) **stands**. The revision adds the closest available second reader and does **not** claim it is one: the fleet strip reads **every** node's `slots`, `calibrated`, `claimsSettledPerMinute` and `claimedNotStarted` from **one place**, so a node's confident `full` is at least *comparable* across nodes rather than self-reported in isolation. A node that is confidently full and wrong is still undetectable, and it is recorded as such. |
| **6** | **A policy enforced where a tool is named.** The `ctx.subagents` seam is a **preset-layer row**, so enforcement is per *composition*; `pwsh`/ssh are outside it; the owner's own windows are outside it; the residual (a model working the task itself) is answered with discipline. | **PARTLY FIXED, residuals ACCEPTED** | The wrapper is declared **mandatory in every composition that grants `subagent_local` or `subagent_fork`**, and a composition that grants either **without** the wrapper is **refused by the deployment path** — the same one-line shape as D §3.6 item 1's *"an unclassified change is refused"*, and it is the fix for E §1.6a (*"'it cannot be bypassed by composing differently' is unstated and false as written"*). **`pwsh`/ssh remain outside it** and are named as outside it. **The owner's own window remains an undeclared writer**, and so does `PersonalSecretary-HarnessSync`, which moves repo state every 15 minutes and is not in the DSH task set (`A` §1.8/§1.12 #9) — a queue-level lock cannot see either, and the measured cost of two undeclared writers on one tree is already in the record (`95` §6.3). **The residual (a model working the task itself)** stays answered by cost and context discipline, and it is now *measured* rather than asserted in one respect: §2.2's fleet concurrency grant can see a self-worked turn only if the engine takes a lease (§1.5, [G-ASSUMPTION G4]) — so the strip **prints `uncountedTurns`** instead of assuming zero. |
| **7** | **A corrected fact that never reaches the copies.** The keeper has no declared reader class; a keeper that can red falsely is ignored (measured); the registry's anchor is a mutable path that exists twice with different bytes. | **FIXED (two of three), ACCEPTED (one)** | **(a)** The keeper declares its reader class and runs in **each** one — local Interactive, ssh-spawned, scheduled task — because the same bytes gave `exit=1 lines=16` to an ssh reader and `exit=0 lines=620` locally *in the same minute* (`A` §3.7 row 7, `106` §8). **(c)** The registry records an **immutable identifier** — a blob id or sha256 — beside the document path, because `docs/mesh/` and `journal/docs/mesh/` hold 53 twins and **`84-calibration.md` differs by 85 bytes** between them (`A` §4.4, and `84` is the constants registry's own primary source). **(b) ACCEPTED:** a keeper that reds falsely gets ignored — measured, `install-client-plugins.ps1 -Check` disagreed with itself two runs apart (`A` §3.13) — and this revision does **not** solve how a correct red is distinguished from the scheduled-task ecosystem's existing non-zero noise (`A` §1.8: `2147946720`, result 1, a Disabled watchdog, a task pointing at a temp file). A design response is *"the keeper's red must be a state on a surface a human already reads"*, and that is a statement of intent, not a mechanism. Recorded as such. |

### 4.1 E §3 — "a session can never move" is a **choice**, and its cost is unpaid

E §3 is right and the revision accepts the correction in full. Three pieces of the record say so, and I
take them from E rather than re-deriving them:

1. **B — the document D cites as its authority — calls it open.** B §A7: *"The constraint is settled as
   a fact about the current loader; it is **OPEN as a design principle** and was never tested as one."*
2. **D itself builds the missing arbiter, for jobs** — durable claims with a TTL, an atomic multi-slot
   reservation, a store whose failure is survivable (`D` §3.3.1, §3.3.3, §3.8 SPOF 1). *"A design that
   can add one arbiter can add another; it chooses not to"* (`E` §3).
3. **C §6.6:** systems that move a live session *"do it by **never moving it** — the environment stays
   where it was created, and the **UI reattaches from anywhere**"*, and D's second half is blocked on
   the build (`C` §9.2: zero `pushState`/`hash`/`sessionId` across 65 client bundles).

**So the sentence changes, and only the sentence plus one procedure.** Not *"a session can never move"*
but:

> **A session is not moved, and that is a recorded choice, not a theorem.** The reason is that DSH's
> session writer consults a `Local\` kernel object with no cross-host visibility (`20` §1.1–§1.2, READ),
> and the reopening condition is stated: **if a shared session store with a lease is ever built, session
> placement becomes an ordinary engineering problem and this choice is revisited.**

**The procedure that has to change, because E caught it answering its own impossibility.** D §3.2 item 3
requires recovery onto node Y to establish *"(a) node X is **provably** dead — two independent checks,
no engine answering **and** no live lease holder"*. The lease is a `Local\` kernel object with **no lock
file on Windows** and no cross-host visibility by construction — **so the two clauses cannot both be
true**: if X answers, it is not dead; if X does not answer, the second check cannot be performed
(`E` §3). And D refuses this same ambiguity everywhere else: §3.3.5 will not dispatch into a site whose
reachability cannot be distinguished from its busyness.

**The revision deletes the clause rather than the procedure.** Recovery becomes:

```
RECOVERY (fail-closed, and it needs NO cross-host liveness determination)
  (a) the log's last frame verifies against the catalog's recorded (sequence, sha)   [V3: read the
      property, not the shape]
  (b) the workspace path exists on the target node
  (c) the source session is NOT claimed dead and is NEVER written to
  -> the session is opened on the target as a COPY under a NEW id, and the original is left untouched
  -> if (a) or (b) fails, the procedure refuses and names which clause failed
```

**What this costs.** It gives up *"recover the session"* and keeps *"do not lose the work"*, which is the
guarantee G4/`D` G1 actually makes. **A copy is not a move, and the design stops pretending otherwise.**
**A6** (`D` §6.1) survives with its adversarial half intact — corrupt the last frame and confirm the
procedure **refuses** — and its first half changes from *"kill a node mid-session; recover on another
node"* to *"take a copy while the source is live; verify the copy and leave the original intact"*, which
is **strictly safer to test and needs no second machine's death.**

**And the unpaid cost E named is now priced where it belongs:** immobility is why §3.2 of D adds five
stateful things (a write-maintained catalog, a node column, a recovery procedure, a durable handle, and
a log-as-authority rule) and every one of them is a new place for the stale-view class — on top of the
session store that already exists (`E` §3). This revision **drops the node column from the critical
path** (§4's cut of the catalog to H-class) and **drops the recovery-liveness clause** (§4.1), which is
two of the five removed rather than three more added.

### 4.2 E §4 — the deletions, restated in light of what E found

| D §4.3 deletion | E's verdict | G's restatement |
|---|---|---|
| `score = min(memorySlots, coreSlots)` with `0.75 x physical` | **unreplaced**: the replacement is the same term in another unit, or 2.7x looser | **Genuinely replaced now.** The CPU term is no longer a fraction of a ratio; it is `floor(U_cpu / w)` with `U_cpu` a per-node measurement and `w` declared by the work (§1.2). The identity is *printed* rather than hidden, and the node's calibration state is part of the answer. |
| `SWAP_PENALTY_PCT = 90` / `mem.swapUsedPct` | replaced, but the replacement is a subtraction on the consumer side; on macOS the memory quantity is **a different quantity**, and the Mac is the only node where the memory term binds | **Stands, with the caveat promoted.** `committedBytes` is a `plugin-health` gap to close, not a term to assume (A §2.9, `109` §5). **The Mac's memory term is not trusted**: `95` §1.1 measured it reporting `freeMiB 7067` where the actually-free number was **133 MiB**, so a macOS node reports `calibrated: false` for its memory term until that is fixed, and the Mac is a placement target **only** when its own curve exists ([G-ASSUMPTION G11], same test as G1). |
| `accepts.maxChildren`, `governor.budgetSlots` as published measurements | **unreplaced**: the only per-node statement of *how large a fleet this node can take*, which gang admission now needs | **Replaced by `maxGang` (computed, §3.2) and by the lease directory (§1.5).** `governor.budgetSlots`'s *protocol* is promoted from advisory to load-bearing; its *number* is deleted as a published measurement, and the keeper's `governor_budget_slots` entry is retained with the note that a field that cannot vary must report `constant` (V7). |
| the `fits`/`highest-slots`/`slow`/`unreachable` tiering | **fine** | unchanged |
| `160 MiB` as a placement constant | **fine** | unchanged |
| `0.81 GB per generating turn` | **fine**, except that the keeper that keeps it deleted is the keeper of §1.7 | unchanged, **and the keeper is still a REFUSAL** (no consumer, no clock, no red path — F §6) |
| "dispatch anyway" on expiry | **fine** — the cleanest deletion in the document | unchanged |
| the stale roster prose, `-Exclude` as policy, a window identified by a port | **fine** | unchanged |
| **`never refuse`, as a universal** | **a deletion of something that was never universal** — and the protection it gave (a caller cannot distinguish "no" from "later") is not covered anywhere | **RESTORED AS A SCOPED RULE, and the hole is closed.** See §4.3. |
| restart-to-activate as a class; the three-place coupling | **partly unreplaced**: the *idle* gate is lost, and the blast radius is measured (*"13 of 13 remembered window(s) reopened"* against a dead port, `ERR_CONNECTION_REFUSED` in every window, 3,760 → 24,200 → 9,764 process churn) | **Stands, and the cost is a measured number rather than a frequency claim.** D says the claim rests on *"it is now the rare, opt-in class"* — a claim about frequency, which is not a protection (`E` §4). This revision **replaces the frequency argument with the cold-boot gate as a hard precondition** (§6) and adds one **CUT**: the catalog's write seam is H-class, so the migration path contains **two** H-class acts, not one (§5). |

### 4.3 The `never refuse` deletion was aimed at a strawman, and the job-with-no-position hole is closed

E §4's longest paragraph, and I accept it. `95` §2.4's own verdict on the observation D cites is the
opposite of D's: *"**The never-refuse rule holds under the two hardest cases I could construct**"*, and
B §7 lists it as **F4**, one of *"the two design decisions in the whole estate that the adversarial
audit could not break"*. D cited the evidence *for* the pattern as the reason to delete it, and called
a `200 + position` *"absurd"* — a taste judgement about a response shape the pattern was designed to
produce.

**And the rule was never universal.** `71` §2.2: *"**The swap half is a ranking change, never a gate**"*;
`76` §4 and `dsh-at-scale/90` §3: *"**It never refuses.** There is no branch that returns 'no'."* And the
money ceiling **already refuses by design** in `65` §3.3: *"nothing is killed mid-call, nothing is
deleted, the session stays resumable, and the only thing that stops is **starting new work**"*, with
`65` §4's `{kind: 'reject'}`. **The pattern D deletes as a universal is a pattern the house had already
scoped correctly.**

**The revision therefore:**
1. **Restores `never refuse` as a scoped rule** — capacity queues, a partition queues, and only money and
   a resource the store itself owns may refuse. This is D §1.3's own conclusion, minus the framing that
   the pattern was ever universal.
2. **Closes the one real cost E identified**, which D had nowhere: *"a job refused at a seam exists only
   in the caller's context; it is neither running, nor queued-with-a-position, nor a node state"*
   (`E` §4.3). **So a refusal creates a job record with a position-bearing state.** Every refusal — the
   wallet at the ceiling, the fleet-concurrency grant at the cap, the store's identity and exclusivity
   rules — writes a durable row under the store's `refused/` directory with the reading that refused it.
   **`refused` becomes the fifth named state** (with `running`, `queued-with-a-position`, `settled`,
   `failed`), so the promise in D §1.1 — *"the system says which of the four permitted states it is in
   instead of going quiet"* — becomes *five*, and G1's falsifier (*"a job that is neither running, nor
   queued-with-a-position, nor reported failed"*) stops being satisfiable by a refusal.
3. **Notes where this makes refusal *worse* and leaves it**: D §3.3.7 step 3 refuses when the queue is
   unreachable — *"precisely when refusing is least safe and when a queue was the whole point"* (`E` §4.3).
   §3 of this document removes that case for the site-local queue store; it survives only for the
   authority-side fleet-concurrency store, where the fallback is the per-machine cap.

### 4.4 E §5 — migration reality, and the two items that change the plan

E's M7 finding is the one with the blast radius on the owner's screen, and this revision treats it as a
**CUT of a D claim**, not a plan:

* **D §3.1.1's *"available today, without a client change"* is not supported.** A loopback alias does
  need no engine config change — but reaching **another node's** engine does: DSH refuses `--host 0.0.0.0`
  on purpose (`20` §1.3: *"it would expose remote code execution to the network"*), the supported door is
  a **reverse proxy that preserves `Host` plus `--trusted-host <authority>`**, and `--trusted-host` is
  **read at engine start** (`20` §1.4; `secratary`'s own unit already carries it). That is an
  **H-class, per-node, restart-requiring** change appearing inside a step D classified *"client-side, so
  it still needs no idle window and no restart"* (`E` §5.1).
* **And the transport has never been measured at all:** whether a remote node's engine will serve a
  browser whose origin is the *laptop's* loopback port, through the node's own gate rather than a direct
  bind (`E` §5, closing paragraph). **One `curl` against a second node's engine carrying a foreign `Host`
  settles it**, and it decides whether M7 is one config key or a new per-node transport.
* **D's fallback is the `Test-LaunchUrl` failure class reproduced as a mitigation** (`E` §1.3b) — fixed
  in §4 row 3 by making the fallback prove the *session*.

**Two further migration realities E names, both accepted:** the keeper's environment is the same
scheduled-task set that already produces non-zero results nobody reads (`A` §1.8, `A` §3.13), and
**the isolated-engine acceptance path has never been run under load** — the record's engines *coexisted*,
not that either was loaded (`E` §5; `84` §7 states *"**Two nodes were never loaded at once**"*). So M2's
gate requires one real turn on a scratch engine while the owner's engine is live, *"a model call and
~403 MiB on a machine `A` §1.11 measured at 27,386 MiB of a 44,149 MiB commit limit with 13 agent
loops"* — **the design's own acceptance path has never been exercised in the condition the acceptance
path is for.** That is a measured risk of the plan and it is recorded, not engineered around.

---

## 5. E §6 — the numbers: every correction, marked fixed or accepted-and-recorded

| D's claim | the discrepancy (`E` §6.1) | status in G |
|---|---|---|
| §3.5: the *25.4 s → 29 ms* improvement is **"real and measured"** | A §2.5 marks the figure **[DUP]** and **NOT VERIFIED**; the live proxy's own refresh times are **3.5 s to 20 s** with the prewarm path silent for ~13 minutes (`A` §1.4) | **FIXED.** D's sentence is replaced: *the warm path is **not confirmed** on this machine; the only first-party readings are the proxy's own background refresh times, 3,482 / 12,412 / 20,064 ms (`A` §2.5, `[LIVE]`)*. The proxy cache stays as a stopgap and its **cost is now the honest one — a background refresh of 3.5–20 s, not a caller wait of 29 ms** — and the strip's age rule (§4 row 2) is what makes that visible. This is exactly the **0.81 GB shape** E names: a number A refused, asserted as settled. |
| §3.4 item 8 (twice): three sessions were **52.5 %** of a $54.92 day | A §4.2 **B10**: `65` §2.4 measures the same three sessions at **47.6 %** ($5.56 of $11.68) | **FIXED, and the second half matters more than the percentage.** D's *"the per-session envelope is the bigger lever"* is retained with **both** figures quoted and `65`'s own finding carried beside them: *"**a single session cannot run away.** The largest session ever measured here costs **$2.88** (09-14) and **$2.56** (09-15). **09-15 had 79 sessions, 09-14 had 152.**"* So the lever is **session count × context**, not a runaway session — and A §2.9's own law (*"cost is linear in `requests × mean context`"*) is what the envelope should be shaped around. |
| §3.3.2: `availableMiB = min(freePhysicalMiB, commitHeadroomMiB - reserveMiB)` | A §4.2 **B5**: **3,885** in `scoring.js:70` vs **7,821** on the desktop; `scoring.js:136`'s own comment admits the frozen value under-reserves by **3,936 MiB, ~24 slots**; the formula is attributed to an `84` §4.4 that does not contain it | **FIXED** (§1.3): the larger value is taken, the fraction is labelled **[G-ASSUMPTION G2]** with its reasoned basis (the measured 410 / 1,174 MiB near-failure margins), and the keeper keeps **both** rows so the disagreement stays visible. |
| §3.3.2: `cpuSlots = floor(logicalCpus x 0.42 / CPU_PER_TURN)` | `84 §4.1` contains **no occupancy fraction**; the 41.5 % lives at `84` §2.1/§4.4/§5.2; the same table's largest single sample is **62.9 %**; `CPU_PER_TURN` is 1.68 or 0.62, a 2.7× spread, both live in production | **FIXED** (§1.2): the term is deleted as an original term, the identity is printed, `U_cpu` and `w` replace it, and `measured-constants.json`'s `largest_measured_cpu_occupancy_fraction` entry's source is corrected from `84 §4.1` to the sections that contain it. The **62.9 %** maximum sample is recorded as the reason `U_cpu` must be **re-measured per node** rather than taken from one level. |
| §3.7 V8 / §3.2 item 1: the journal index is *"over **~2,000** entries"* | A §1.7 `[LIVE]` is **1,795**; A §4.1 A13 lists 1,400 / 1,616 / 1,728 / 1,795 | **FIXED** — *"~2,000"* → **"~1,800, and the count moves; `journal.py status` prints it"**. Minor, but it is a number inside the rule about numbers being right. |
| §3.3.3: *"a 12-child fleet cannot be honoured by per-child placements (`C §10.2`)"* | C §10.2's citation is **`76-broker.md §10.x` — a placeholder section number** — and C never says what the 12 is | **FIXED by deletion.** The sentence is removed and the design claim it supported is now made from **`92` §5.3** instead — the `--hold 6` run, six real leases held by hand to force the broker to consider a loaded node (`F` §7 item 6), which is a primary observation rather than a placeholder. |
| §3.3.1 / §3.4: *"a capacity read was measured at **7,342 ms** (`C §10.2`)"* | C cites `76-broker.md §10.5`; **no document states origin, destination, or who measured it**, and D already has a first-party number for the same link (**4.42 s**, `95` §1.1) | **FIXED.** The second-hand figure is dropped; the argument runs on the **first-party** one (`95` §1.1: the laptop's gate at **4.42 s** where every other node answered in 0.27–1.58 s) — which is stronger, because it is the one that shows *any* latency-weighted ranking makes the owner's machine look worst. |
| §3.8 SPOF 3: *"measured: `accepts.oneShot` is still true (a headless run needs no engine)"* | `71` §0 is a **published contract field** being read, with the interpretation in parentheses — D's own D1/D3 defect inside D's own SPOF table | **FIXED.** The claim is re-sourced to the **observed behaviour**: the isolated-home proofs (`92` §7, `105` §4.1, `106` §5) and the `--profile headless` fresh-process path (`71` §5). The published field is cited as a **pointer to a mechanism**, not as a measurement. |
| §3.1 table, §3.3.8 item 2: **~12.1 s**; §3.1.1: **27–45 ms**; §3.4 item 8: the **42×** cold/warm ratio | **not in A, B or C** — but all three are **sourced to the primary documents** (`84` §1.2, `71` §0, `96` §2.3), verified | **ACCEPTED AND RECORDED.** They are not inventions; they are listed in §7 below as numbers whose only support is a `docs/mesh/*` document, and the two that are load-bearing (`12.1 s`, `27–45 ms`) get a first-party re-read on the critical path of the steps that use them. |
| §6.3's decided default, *"should the laptop ever take remote work?" → "only in its reserve-free band"* | `ownerReserve` has **no value anywhere**, and the default **is** that parameter | **FIXED** (§1.6): de-conflated from the commit reserve, defaulted per node, published, changeable by an edit, and **not presented as a decision** — it is a default with a stated cost, which is what the standing rule requires. |

**And one number E cites correctly that this revision promotes to a constraint** (`E` §6.3, closing):
**ZABZ-YOGA's own turn-cost curve does not exist.** `84` §6.1 records it as blocked, and §1.1 records the
machine *"above that stop line **before any fleet was dispatched**"*. So **the admission function that
cures D1 has never been validated on the machine D2 is about**, and D §3.3.2's CPU term predicts **more**
concurrency there than the constant it deletes (5–14 vs `0.75 × 16 = 12`, all three ARITHMETIC from
`A` §2.13's 22 logical / 16 physical and §2.1's per-turn figures). **This is why §1.2 makes `U_cpu`
per-node and `calibrated: false` a published state.**

---

## 6. What E could not fault, preserved

**E's one unfaultable item is the cold-boot gate** (`E` §7, closing section): *"the design's refusal to
accept any evidence except a boot in the condition that broke the machine."* It is preserved here
**verbatim in intent**, as M2's contract:

> **THE COLD-BOOT GATE.** Four parts, all of which must pass:
> (a) a **scratch `DSH_HOME`** (its own directory — two engines on one home corrupt session logs) on a
> **scratch port**;
> (b) **`DSH_HOME` unset**, which is the incident's exact failing condition and *"the **normal** path,
> not an edge case"*;
> (c) `dsh --profile web --dump-config` → **exit 0**, then **boot**, then `GET /healthz` → **200**;
> (d) **one real turn** on the scratch engine.
> **The gate is run once per reader class that will use the composition** — local Interactive,
> ssh-spawned, scheduled task.
> Its regression is the incident's **Appendix B** one-liner: `Remove-Item Env:DSH_HOME; node -e
> "import('…/guard.js')…"` → must print `LOADED`.

**Why it survives, in E's three reasons, extended by one of this revision's own:**

1. **The failing condition is instantiated rather than approximated.** `Remove-Item Env:DSH_HOME` is
   Appendix B of the incident, and the diagnosis report states *"the unset path is the **normal** path,
   not an edge case. The normal path was the broken one."*
2. **The reader-class rule is a measured finding, not a principle** — the same bytes in the same minute
   gave `exit=1 lines=16` to an ssh-spawned reader and `exit=0 lines=620` to a local Interactive one
   (`106` §8).
3. **The negative direction is specified in advance and is deterministic** — Appendix B prints
   `FAILED: MODULE_NOT_FOUND` or `LOADED` — which is V4 satisfied **by construction rather than by
   assertion**.
4. **[G] And it is the only check in the design whose failure mode has already happened to this fleet**
   and cost **eleven hours** (`incident README:102-103`), while the engineering it depends on — an
   isolated engine on a scratch home and port — is a path this estate has actually exercised three
   times with the owner's engine verified alive before and after (`90` §2.1, `92` §7, `105` §6.1,
   `106` §6).

**The one thing this revision adds to it is the fix for E §1.5a**, and it is an addition rather than a
change: the guard's **import path** gets the appendix-B regression applied directly, because `A` §1.12
item 7 records that *"a one-segment path mistake in this row took down the entire engine"* and D §5 M3
makes `guard.mjs` load-bearing on **every** node rather than one machine. That check is now part of M2's
gate, run per reader class, with the same deterministic negative direction.

**What the gate does not cover, stated because E said it:** it catches the composed-profile case, **not a
wedged running engine** (`E` §1.5a). A running engine that has already loaded a bad composition is not a
boot, and nothing here detects it.

---

## 7. The buildability verdict

**One paragraph, and it is deliberately not tidy.** **Buildable now, with no new measurement: the Roster
as data (M0), the measured-constants registry with both corrections and both reserve values kept visible
(M0.5), the live defects the audit found (M1), the cold-boot gate plus the guard-import regression run
per reader class (M2), and the queue in observe mode with durable claims that survive a store restart
(M4).** **Buildable now but only by fixing the constants this document chose: the money guard at the
step seam (M3), with the fleet-concurrency grant of §2.2 as the one resource that gets a real single-writer
grant, and with the explicit statement that a money *grant* is impossible on this fleet because the
provider publishes no usage surface and the local ledger is measured at 50 % of misses / 76 % of hits —
so §2.2's stronger property applies to concurrency and §2.3's weaker property applies to money.** **Needs
a measurement before it can be claimed: the admission contract of §1.7 on the machine it matters for,
because `U_cpu` does not exist on ZABZ-YOGA and `84` §6.1's rig is a six-minute, ~90-turn run that would
retire the largest single unknown in the redesign; and the calibration record is mandatory — a node
without it reports `calibrated: false` and may take work only under its conservative bound, which is a
deliberate throughput cost of ~24 % in memory slots and 40 % in CPU slots until the curve exists.**
**Must be cut: the multi-node gang (single-node only, §3.2), the committed-until *ordering* promise that
contradicted M6's own gate (§3.3), the cull policy's `T` (ships OFF until a cull cost is measured,
§1.7), the money ledger's claim to be "granted" (§2.3), the session catalog's implication of
activation-free writing — it is engine code and therefore H-class (§4 row 2) — and the recovery
procedure's cross-host liveness clause, which could not be evaluated and is replaced by copy-recovery
(§4.1).** **The design is therefore buildable *as a sequence*, not as a whole: five steps are ready,
three need one six-minute measurement between them, and four promises are withdrawn rather than
engineered.** **And the single most important thing this revision must not be read as claiming: D's CPU
term was the deleted term in another unit, and it is deleted here — which means the fleet has *no
validated capacity model on the laptop at all*, only a validated one on the desktop and a stated bound
everywhere else.**

### 7.1 What E called the most important unresolved item, and where it now stands

**Objection 1 is resolved as a design and unresolved as a measurement, and the document says which is
which.** The design fix (leases as the shared counter, `U_cpu` per node, `w` declared, `reserveMiB` and
`ownerReserve` valued and separated, `calibrated: false` as a published state) is complete enough to
build. **The measurement that proves it does not exist**: 83 of 83 samples say the class of blindness
is real, and the only experiment that tests *this* mechanism — both admitters live, N=8 in-session
children plus 4 claimed jobs, counters compared against the OS — has never been run (`E` §7 objection 1).
Until it is, *"a node cannot be blind to its own load"* is a **design argument with a measured
counter-example behind it**, not a demonstrated property.

### 7.2 Every factual claim's status, in one table

| class | what is in it |
|---|---|
| **MEASURED, cited** | the 403.3 MiB point estimate and its 270–530 union; 0.62 / 1.679 logical CPUs; 41.5 % at N=8 on 32 logical; 8/5/1/3/1 derived limits; 3,885 / 7,821 MiB reserves; the 410 / 1,174 MiB near-failure margins; 83/83 `agentLoopsRunning: 0`; the 3,482 / 12,412 / 20,064 ms proxy refreshes; the 9-hour idle window; 50 % misses / 76 % hits; 56.5 % of 2026-09-15 from ZABZ-TECH; the 3,760 → 24,200 → 9,764 restart churn; `exit=1 lines=16` vs `exit=0 lines=620`; 25,371 ms and 5,900 ms session-list walks; 12.1 s per turn (primary-sourced only); 27–45 ms laptop↔office (primary-sourced only); the 42x cold/warm ratio (primary-sourced only) |
| **ARITHMETIC (mine, labelled)** | `0.42 = 8 × 1.679 / 32` and its cancellation (E's, reproduced); 403/530 = 76 %; 3,936/403 ≈ 9.8 desktop slots lost by choosing the larger reserve; 5 (laptop CPU ceiling under §1.2) vs `0.75 × 16 = 12` (the deleted constant) = the replacement is **2.4× more permissive**; 13.28 logical CPUs from 41.5 % × 32 |
| **[G-ASSUMPTION], with its test** | **G1** laptop `U_cpu` → `84` §6.1 item 1's rig; **G2** the 0.12 reserve fraction → step commit toward the limit and record the largest reserve with no allocation failure; **G3** 530 as the divisor until a node-local curve exists → that node's own steady-state fit; **G4** the engine's own turn loop takes a lease → the dual-admitter rig (§1.5); **G5** `ownerReserve = 1` on ZABZ-YOGA → an owner answer, which changes the number and not the code; **G6** `T_stall = 3 × tick` → F §3.2's 2b run; **G7** `T_cull` unset → F §6's A13 rig; **G8** the two-node spend race bound → two machines at 90 % of the ceiling simultaneously; **G9** arrival-order queueing cost is small → M6's rig with a mixed short/long job stream; **G10** one store per site makes §3.3.7 step 3 near-dead → a partition test between the two sites; **G11** the Mac's memory term untrusted → `95` §1.1's 7,067 vs 133 MiB discrepancy re-measured |
| **CUT, and stated as a withdrawn promise** | multi-node gang admission; committed-until *ordering*; the money grant; the cull policy's threshold (so the policy itself); the catalog's activation-free write; the recovery procedure's cross-host liveness clause; D §3.3.3's placeholder-sourced *"12-child fleet"* justification |
| **REFUSAL, still a refusal** | the constants keeper has no consumer, no clock and no red path (`F` §6, verified four ways); the enforcement path has never refused anything live (A Part 5 item 19); the idle-cull cost has never been measured and no cull policy exists to measure; the laptop's own curve; above 8 concurrent turns on any node; the exact bill needs a console export with no API |
| **UNRESOLVED, and left unresolved with its resolver named** | all 13 (or 14, counting the split reserve entries) `unresolved` entries in `measured-constants.json` stand, and the **three that bear on this design are resolved as decisions and kept as disagreements**: the reserve (§1.3), the per-node derived limit (§1.2), and the warm session-list path (§5). The rest — the commit limit's four live statements, the committed/physical ratio's five, the 16–22 vs 12 cap, the memory:core ratio, the commit-per-turn supersession chain — are **not** resolved here, correctly, because none of them is a decision this document is entitled to make |

---

## 8. What I did and did not do

**Measured nothing.** I ran no command that reads a live machine counter, dispatched no fleet, ran no
child turn, and killed, started or restarted nothing. The only two commands I ran were read-only reads of
the journal's own status page and a file listing under `docs/redesign/`. **Wrote exactly one file: this
one.** The engine `pid 4416` on port 3099 was not touched; no service was started; the journal, the
gates, the broker and the git state were not written to. **`E`'s and `D`'s provenance discipline is
inherited whole**: where I could not source a claim to A, B, C, D, E, F, the keeper, or a `docs/mesh/*`
document those cite, I marked it as an assumption with its test or recorded it as a refusal — and the
one place where I am confident and the record is silent is marked **ARITHMETIC** and shown.
