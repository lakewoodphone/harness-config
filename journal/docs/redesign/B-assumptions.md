# B — Assumption autopsy

**Stream:** B of the from-scratch redesign. **Owns:** this file only. Nothing else was created,
edited, moved or deleted; no engine or gate was restarted; no process was killed; no git state
changed. **Written:** 2026-09-17/18 on `ZABZ-YOGA`, repo HEAD `697ac3a`.

**Method.** Every belief the current design and method rest on, stated as an assumption, attributed
to the document and line that carries it, then tested against a measurement. Three provenance
classes are marked explicitly:

* **MEASURED (mine)** — read this session, command and raw output given in §11.
* **MEASURED (cited)** — taken from a document that states its own command and raw output; the
  document is named and the line given. I did **not** re-run these.
* **READ** — read out of a document or source file, not measured by anyone.
* **REASONING** — marked as such. This is my inference, not an observation.

Where a claim would need a machine I do not have or a process I may not touch, I say so and mark it
**OPEN** with the measurement that would settle it.

**The audit found nine assumptions the owner named, plus fourteen more.** They are grouped by what
they break. Ten are settled empirically. Eight are genuinely open, each with a command sketch.
Three are load-bearing in a way that makes them costliest if false (§10).

---

## 0. What the repository itself says about the state of these beliefs

Before the autopsy, the single most important structural fact: **the design and the measurements
have diverged, and the instrument that would have caught it is not wired into the acceptance path.**

`docs/mesh/60-verification.md` already refuted the 0.81 GB constant on 2026-09-16 (§2.2, quoted at
`10-inventory.md:16`). `docs/mesh/84-calibration.md` refuted it again on 2026-09-17 with a proper
confidence interval (§3.1). Six documents then carry a dated correction. And yet:

* `presets/zabz/skills/parallel-agent-orchestration/SKILL.md:135–136` — the skill file the default
  orchestration path loads — still carries `0.81 GB per running turn`, `13-14 turns`, and
  `~325 MB private per browser window`, all three in one row, **with no correction marker**.
* The identical text is in `presets/cordis-bg/skills/…`, in `journal/presets/*/…` and in
  `journal/docs/mesh/*` — five deployed copies, none corrected.
* `packages/plugin-mesh-http/README.md:66`: *"One generating turn costs ~0.81 GB commit and ~1 core
  (`71` §2.2)"* — production code documentation citing a refuted constant.
* `$HOME/.dsh/.agent-presets/zabz/skills/parallel-agent-orchestration/SKILL.md` is byte-for-byte the
  same file (10,458 B, mtime 2026-09-17 14:17), i.e. the copy every session on this machine actually
  reads.

The rule `81-overnight-program.md:61` states — *"A report is a claim, not evidence"* — was applied to
reports and never to **presets**. A `sync.py` run copies the uncorrected skill onto every machine, so
the system's own method document propagates a number its own calibration document refuted. That is
the mechanism by which a refuted belief stays alive, and it is Assumption 11 (§4) at the level of the
harness itself.

---

## 1. The two constants, and what was built on them

### A1 — "One generating agent turn costs 0.81 GB of commit"

**What is assumed.** A concurrent agent turn is a ~0.81 GB unit of commit charge, so a node's
capacity is `0.75 × RAM ÷ 0.81` turns.

**Where it is written.** `docs/dsh-at-scale/PROGRAM.md:75`; `presets/zabz/skills/…/SKILL.md:135`
(deployed to `~/.dsh`); `docs/mesh/10-inventory.md:668` and §10's whole capacity table;
`docs/mesh/71-mesh-program.md:156` (inside the **frozen** §2.2 scoring rationale);
`packages/plugin-mesh-http/README.md:66`; `docs/mesh/61-buy-list-verified.md:44`.

**What contradicts it.** Two independent refutations, both with commands:
`docs/mesh/60-verification.md` §2.2 (slope `0.5754` GB per node **process**, `r = 0.937`, 477 rows of
`~/.dsh/metrics/harness-metrics.csv`, idle floor 17.0–18.4 GB) and `docs/mesh/84-calibration.md` §3
(row-level steady-state fit **403.3 MiB/turn**, CI 328.3–478.3, n = 63, r = 0.806; level-mean fit
**402.3 MiB**, CI 271.5–533.0, n = 6, r² = 0.948; cross-checked at −410 MiB/turn by `\Memory\Available
MBytes`). The verdict is stated at `84-calibration.md:345`: **REFUTED — 2.1× too high.**

**Why it was wrong, which matters more than the number.** `60-verification.md` §2.2 and
`40-hardware-costs.md:16` show the original 0.81 came from `(28.7 − 20.65) GB ÷ 10 turns` on the
**laptop** (`80-windows-and-parity.md:505`) — a two-point difference between an idle-ish fleet and a
loaded one, divided by a turn count read off a process table. The idle floor was never subtracted as
an intercept. The calibration fit has an intercept of 20,381 MiB, which is the idle floor, and the
slope with it is 403 MiB.

**Design implication if false.** Every "resident turns" number in the estate is off by the same
factor: `10-inventory.md` §10's capacity table (24/11/9/3/3/1/1, "≈50 agent-turns"), `20-placement.md`
§6.3's per-row budgets (line 717: *"0.81 GB + tool calls ≤ 20 × 160 MB = 3.2 GB worst case"*),
`40-hardware-costs.md` §4's purchase arithmetic, and the broker's 160 MiB-per-**slot** reserve, which
`84-calibration.md` §4.2 shows is 2.5× below the measured per-turn cost and therefore not the
quantity that limits any node. The correct implication is not "more turns fit" — it is that the unit
was wrong, so the **ranking formula** has to change shape, not coefficient (§2, A5).

**Settled or open?** **Settled for ZABZ-TECH at 8 concurrent turns and a ~12 s turn mix.** `OPEN`
everywhere else: it is one node, one workload mix, and an extrapolation beyond 8 turns
(`84-calibration.md` §3, §6.3). The measurement that would settle it on the laptop — the node the
constant was originally written for — is not taken and is named as the program's own highest-value
follow-up (`84-calibration.md` §6.1):

```powershell
# from ZABZ-TECH, so no driver/sampler process is charged to the laptop
pwsh %TEMP%\mesh-run.ps1 -Node zabz-yoga-1 -Children 2,4,6,8 -Prompt <resident>
```

### A2 — "ZABZ-YOGA pages at ~13–14 concurrent turns"

**What is assumed.** The laptop's ceiling is thirteen to fourteen concurrent generating turns.

**Where it is written.** `presets/zabz/skills/…/SKILL.md:135`; `docs/dsh-at-scale/PROGRAM.md:75`;
`docs/dsh-at-scale/50-implementation.md:218–219`; `journal/entries/lessons/L1711.md:23`,
`L1717.md:40`.

**What contradicts it.** `docs/mesh/60-verification.md` §2.3 already found it *"directionally
supported, but not as stated"* — the arithmetic there is `31.6 − 18 ≈ 13.6 GB` headroom at an
optimistic 0.81 GB/turn ≈ 12 turns. `84-calibration.md` §4.1 then measures that **paging is not a
function of concurrency at all** on the node it could measure: `\Paging File(_Total)\% Usage` was
**14.1 % in all 83 samples**, disk queue peaked at 1, page-in storms were process-start transients
(233,604/s inside a level whose neighbours read 1,000–6,000/s, and the pagefile never grew).

**My own arithmetic, on the current numbers (this is REASONING, with measured inputs).** Measured on
this laptop this session: total 32,373 MiB, commit limit 44,149 MiB, committed 27,141 MiB. Headroom
to the hard commit limit 17,008 MiB ÷ 403 MiB = **≈42 turns**; headroom to physical ÷ 403 =
**≈13 turns**. So the *physical* crossing is still ≈13 turns — the first statement is not merely
numerically wrong, it is addressing a different threshold than the one that kills an allocation. The
design builds against the wrong one: `84-calibration.md` §4.4 shows the commit limit is 410 MiB
(0.6 %) below the 90 % alarm on the desktop and 1,174 MiB (2.7 %) on the laptop, i.e. the alarm
cannot fire before the machine is already about to fail an allocation.

**Design implication if false.** The `coreSlots = floor(physical × 0.75)` term was derived from a
**paging** observation being used as a **CPU** budget (`84-calibration.md` §4.3: *"a wrong argument
produced a usable number"*). If the paging model is false, that derivation carries no weight at all
and the term must stand on its own measured core cost (0.62 logical CPUs resident / 1.68 tool-heavy,
`84-calibration.md` §4.3), which the constant does not express. Second: any design that says "keep
concurrency under 13" is rationing headroom that on this node is not the binding resource — the
**commit headroom** is, and it sits elsewhere.

**Settled or open?** **The mechanism is settled (paging is not the limiter); the laptop's number is
OPEN and unmeasured** — `84-calibration.md` §1.1 records that ZABZ-YOGA was above its own 26 GB stop
line before any fleet was dispatched, so the laptop's curve has never been measured by anyone.
Measurement that would settle it: the same rig as A1, on `zabz-yoga-1`, after the owner's sessions
end. There is a **conflicting signal in the record** that makes this worth taking: the same document
records the laptop going **27.11 → 29.92 → 34.72 GiB committed in fifteen minutes with 3,408 MiB of
RAM free and the governor at its floor of 4 slots** (`84-calibration.md` §1.1) while six agent loops
ran. That is a machine in visible distress at *six* turns, which is a different shape from the
desktop's flat line through eight — and it is a 6-sample excursion, not a fitted curve. Both readings
are in the record; neither is a laptop capacity curve.

### A3 — "`0.75 × physical cores` is the capacity score, and `min(memorySlots, coreSlots)` is the right shape"

**What is assumed.** Placement ranks on slots, computed as the smaller of a memory-derived and a
core-derived term.

**Where it is written.** `docs/mesh/71-mesh-program.md:136–141` and `:156–161` (the frozen §2.2
amended block); `packages/mesh-broker/lib/scoring.js:67,69` (`CORE_SLOT_FRACTION = 0.75`,
`SWAP_PENALTY_PCT = 90`).

**What contradicts it.** `84-calibration.md` §4.2–§4.4 and §5.3: the **memory term cannot vary** on
any node in this fleet (it caps at `freeMiB ≥ 7,725 MiB` and every node clears that by thousands), so
`min(...)` is always `coreSlots`; the core term is *unfalsifiable as written* because it converts a
paging observation into a CPU budget; and `swapUsedPct` is `max(0, committed − physical) ÷
(commitLimit − physical) × 100` (`scripts/phone-gate.py:1110–1149` read), i.e. commit-band occupancy
wearing a swap name, reading **exactly 0.0 across a 10 GiB spread of commit**. The live consequence is
measured by the audit: at 13:04Z the laptop reported `loopsRunning: 7, sessionsLive: 12` and 23.7 GiB
committed, and its own broker score stayed at **12 slots of 18** (`95-audit-live-mesh.md` §7(a));
`109-pressure-routing.md` §1 catches it at **126 % of physical memory committed with `accepts: true,
maxChildren 12`**.

**Design implication if false.** Placement is blind to load *by construction*, not by bug: the only
term that could see load is unclamped and unused, and `agents.loopsRunning` is read into the broker
at `lib/broker.js:407`, printed at `:698`, and referenced **nowhere in `scoring.js`** (§5.4). Any
redesign that keeps a slot product will reproduce the failure. The measured shape of the field to
build on is named at `84-calibration.md` §4.4: `min(mem.freeMiB, commitAvailableMiB − reserve)` —
monotone, unclipped, and it would have moved all night while `swapUsedPct` sat at 0.0.

**Settled or open?** **Settled** (the two constants as written are refuted or unfalsifiable). `OPEN`
only for the value of the workload-mix-dependent core cost — `84-calibration.md` §4.3 proposes a
fixed-mix sweep, N = 0,4,8,12,16,20, ~15 minutes and ~400 turns.

---

## 2. Memory, cores, and who is actually the bottleneck

### A4 — "Memory — RAM — is the binding resource on this machine"

**What is assumed.** The laptop's constraint is RAM, so the design's job is to spend less of it.

**Where it is written.** `docs/dsh-at-scale/PROGRAM.md:75`; the whole
`docs/multi-window/ANALYSIS-AND-DECISION.md` / `PERFORMANCE-MEASURED.md` lineage summarised at
`journal/README.md:149–153`; and, most consequentially, the shape of the admission governor —
`admission_governor` is described (in this session's own system prompt and in
`docs/dsh-at-scale/90-plugin-health-governor.md`) as *"before fanning out a large fleet … ask this
governor for a slot"*, with the budget computed from **free memory** at ~160 MB per in-flight tool
call.

**What contradicts it.** Two of them, one of which is a primary measurement:
1. `docs/mesh/84-calibration.md` §4.3, §5.3: **cores bind first**. On ZABZ-TECH the memory ceiling is
   ≈111 turns against a core term of 18 (`84-calibration.md` §4.2), i.e. memory does not bind until
   **6× past** where the design stops accepting work. The memory term is *decorative* — §5.3's word.
2. `docs/mesh/109-pressure-routing.md` §2.1 **corrects the governor's own premise**: on this laptop
   `committed ÷ physical = 120 %` at 22:12 on 2026-09-17 while **7.7 GiB of physical RAM was
   available and the pagefile held 194 MB**. A refusal on that reading *"would have refused work on a
   machine with 7.7 GiB free"*. The commit limit here (43.11–46.29 GB) sits far above RAM (31.61 GB),
   so a committed-over-physical ratio routinely exceeds 100 % with nothing wrong.

**Measured this session (mine).** Committed **27,141 MiB** of a 44,149 MiB commit limit, 10,713 MiB
free, pagefile 11,776 MiB with **222 MiB in use** — 1.9 % — with 16 node processes and 65 msedge
processes live. The pagefile is the counter that would show a RSS-against-RAM problem, and it shows
none.

**Design implication if false.** Three things were designed around the false bottleneck:
(a) the **admission governor's budget** — 160 MB per in-flight tool call, derived from a tool-call
runner's memory, which is why it reads 24 slots on a 4-core authority (§1.4 of `95-audit-live-mesh`);
(b) the **window-cost program** (`60.6 GB` of browser study) — real savings, wrong axis;
(c) **the mesh's own justification**, *"run fleets elsewhere because the laptop runs out of memory"*
— when the answer for four days has been *"the laptop runs out of **cores** while running 6–18
generating loops, and its own users' screen is one of them"*.
`REASONING`: the correct governor for this fleet is a **core** budget plus a **commit-headroom**
floor, and the fact that the owner had to invent the governor himself — after the calibration — is
itself evidence that the design never carried a load-aware control in the placement path.

**Settled or open?** **Settled: memory is not the binding constraint in the reachable range, and the
governor's memory basis over-permits by construction.** Open only in the form "at what commit
headroom does a *four-core* authority actually fall over" (`84-calibration.md` §6.2 — `secratary` has
4 cores and no `/healthz`; the measurement proposed is `/proc/meminfo` + `/proc/pressure/{cpu,memory,io}`,
which needs no engine).

### A5 — "The commit limit is the danger; 90 % is a warning"

**What is assumed.** A node near 90 % of its swap is in danger and should be penalised.

**Where it is written.** `docs/mesh/71-mesh-program.md:140,164` — *"`slots = mem.swapUsedPct >= 90 ?
floor(slots / 2) : slots`"*, *"`90%` is a first cut"*; `packages/mesh-broker/lib/scoring.js:69`.

**What contradicts it.** `docs/mesh/84-calibration.md` §4.4, in three parts: the field is not swap
(it is commit-band occupancy); it reads **0.0 in every one of 83 samples** including the
CPU-heaviest; and at "90 %" it is within **410 MiB (0.6 %)** of the desktop's commit limit and
**1,174 MiB (2.7 %)** of the laptop's. The band the constant reasons about is **3.5 GiB wide on the
laptop and 2.2 GiB on the desktop — all of it crammed into the last gigabyte before a failed
allocation**. The 60 → 90 % comparison is therefore not measurable without ~117 concurrent turns on
the desktop — 14× the cap.

**Design implication if false.** The penalty is an **ungraded near-OOM alarm applied as a ranking
halving**, which is why it has never fired and never will in normal operation — `95-audit-live-mesh.md`
§1.2 shows `secratary` live at `swapUsedPct: 81.2` with `swapApplied: false`. The redesign should
carry **commit headroom**, which the contract *already publishes* (`commitAvailableBytes`,
`commitLimitBytes`) and consumes nowhere.

**Settled or open?** **Settled.** Replace, do not recalibrate.

---

## 3. The mesh: what it does and does not reduce

### A6 — "The mesh reduces load on the busy machine"

**What is assumed.** When the owner's machine is heavy, work is routed away from it, so the mesh
reduces its load.

**Where it is written.** `docs/mesh/71-mesh-program.md:5` (the owner's mandate is quoted verbatim:
*"agents and sessions always get routed to the most empty part of the mesh that will run fastest"*);
`docs/mesh/94-routing-default.md` §3 (*"`subagent` is a child on another machine"*);
`presets/zabz/skills/…/SKILL.md:130`: *"Fan the fleet **off** the machine the owner is sitting in
front of when it is heavy."*

**What contradicts it.** The mesh placed **zero units of work while the machine was over physical.**
Two records, two days, same finding:
* `docs/mesh/88-elastic-build.md:24` and §6.2: across **every placement this mesh has ever recorded —
  6 `POST /place` calls, both days, at 03:45Z on 2026-09-17 — `tier` was `fits` six times out of six**,
  at `position 0`, on a mesh with 30 effective slots free. The elastic trigger (`tier != "fits"` twice
  ≥60 s apart) **had never fired**.
* `docs/mesh/109-pressure-routing.md` §1: *"the ledger under `<DSH_HOME>/mesh/placements/` recorded
  **no placement all day**, because the model in each window chose `subagent_local` (or worked
  itself), and neither of those paths measures anything."* And the structural half: `109` §1 measured
  the laptop advertised as **"12 free slots"** while holding **126 % of physical memory committed**,
  and then **"1 free slot"** 31 minutes later, on the same machine, with no change but real life.

**Measured this session (mine, in the same vein).** The mesh's own processes are configured and the
broker's contract is reachable in principle, but nothing in the *path a session takes* consults it.
The active delegation rows are `subagent` → `remote-ssh`, `subagent_local` → `spawn`,
`subagent_fork` → `fork`; only the `remote-ssh` row passes through `pressure.js`/`placement.js`.
`109` §5 states the hole in its own words: *"The refusal is not enforced on `subagent_local` or
`subagent_fork` … **This is the single largest remaining hole**."*

**Design implication if false.** The core design premise — *"route to the most empty part of the mesh"*
— is **not a property of the system; it is a property of a model's tool choice**, mediated by one
sentence of persona (`presets/zabz/agent.cordis.yml` rule 1c, quoted at `94-routing-default.md:137–145`).
That sentence is the only mechanism, and `94` §8 admits *"nothing mechanical forbids the fallback
while the mesh is up; the deterrent is the name plus rule 1c."* A redesign that wants the premise to
be true must make the **default execution path** ask the placement service, rather than making the
tool name ask.

**When does it actually reduce anything?** From the measurements, exactly two conditions, and both
have to hold: (1) work is generated **inside** a session by a tool call that goes through
`remote-ssh`/`placement.js` — not by `subagent_local`, not by the model doing the work itself, not by
`workflow` subagents if those resolve to a local provider; and (2) the call happens **before** the
local machine is already over-committed, because `109` §3.3's own decision is that **when the mesh is
unreachable and the machine is over its high line, DSH refuses and dispatches nothing** — it does not
fall back locally. So the current design reduces load only for a *particular kind* of work, offered
*at a moment the machine is still healthy enough to ask*. Neither the kind nor the moment is
guaranteed by anything.

**Settled or open?** **Settled: it placed zero.** `OPEN` for the second-order question — *would the
mesh reduce load if the pressure path were live?* `109` §4.2 measured a real broker decision, a real
lease and a real ssh *because of* pressure, but **the child was never executed** (`109` §4.2's own
honest limit). Measurement that would settle it: after one honest idle restart, one `subagent` call
from a saturated laptop and read the report's own `pressure = …` line (`109` §7 says exactly this).

### A7 — "Sessions are node-local and work moves"

**What is assumed.** Work is the movable unit; a session belongs to the machine that created it.

**Where it is written.** `docs/mesh/71-mesh-program.md:15` (`Sessions are node-local and do not move`,
sourced to `20-placement.md` §1.2 and marked "verified"); `docs/mesh/71-mesh-program.md:266–268`;
`docs/mesh/88-elastic-build.md` §1.4 and §5.

**What would make it a consequence rather than a principle.** `71-mesh-program.md:265–267` says it
plainly: *"Sessions moving between nodes — they cannot, by construction. Session *placement* (choosing
a node at creation) is v2 and needs a client-side redirect the harness does not have."* **READ**: the
engine writes `sessions/**/session.v3.jsonl.zstd` under `DSH_HOME`, one writer per home
(`journal/README.md:149–151`: *"two engines on one home corrupt session logs"*; `MEMORY-AND-
SESSION-LIST.md` §2 measured 685 rows, 1.47 MB, walked per `session/list` call off local disk). So
the unit of locality is **a directory a process owns**, not a session. A session's turns are placeable
today — that is what `subagent` does (`91`/`92`/`105` record `MESH-HOST:` lines from real children on
other machines). What is not placeable is the session's **continuity**: its log, its workspace tree,
its attached UI.

**Is it what the owner actually wants?** `REASONING`, from his own record: he asked for *"many windows
each with an agent session … many agents fast"* and for *"agents and sessions always routed to the
most empty part of the mesh"* (`71-mesh-program.md:5`). Those are two different asks. The measured
fleet is **one engine, many browser windows** on one home (`journal/README.md:149`), and the laptop
that is over-committed is over-committed *because the owner's own 12–18 sessions and loops live on
it*. Mobility of sessions would not have changed that; the placement of **turns** would have, and that
half is built and unused (A6).

**Design implication if false.** If "sessions are node-local" is a consequence of one-writer-per-home,
then with a shared session store and a lease, session *placement* becomes an ordinary engineering
problem and the whole "work moves, sessions do not" split (and the `mesh` profile that exists only to
route work) is one design choice among several, not a law. That is a much larger redesign than
anything stream D should assume — and I am marking it as *available*, not *required*: the owner's
measured need is throughput, and turns are already placeable.

**Settled or open?** **The constraint is settled as a fact about the current loader; it is OPEN as a
design principle** and was never tested as one. The measurement that would settle the *cost* of
breaking it: whether `dsh-session-persistence-jsonl`'s `listArtifacts()`/append path tolerates a
network-backed store — `MEMORY-AND-SESSION-LIST.md` §2 already measured 5.9 s of raw filesystem walk
for 681 sessions on local NVMe, so the same walk over a share is the number that decides it.

### A8 — "The mesh placed nothing because the mesh was idle" — the counter-hypothesis

**What is assumed (by omission).** The zero placements in A6 are explained by *no demand offered*.

**What contradicts the simple version of that explanation.** `docs/mesh/92-provider-placement.md` §6.2
and §5.2–§5.3 measure a **structural** reason the mesh under-delivers even when asked: a node whose
capacity read is momentarily `slow` is **removed from the `fits` pool entirely**
(`packages/mesh-broker/lib/broker.js:608–614`, `usable = preferred.length > 0 ? preferred :
dispatchable`), not ranked last. Measured: the laptop's gate alternated `ok`/`slow`/`ok` across three
consecutive fresh reads, so **eight concurrent children all landed on the desktop** while the laptop
stayed empty — and at `score 12` against the laptop's `12 free`, a second child still went to the
desktop because the laptop's reading was `slow` that second. `92` §6.2's own verdict: *"a node whose
gate is slow receives nothing while any other node answers fast."* `95-audit-live-mesh.md` §1.1
measures the same shape from the other side (the laptop's gate answered in **4.42 s** while every
other node answered in 0.27–1.58 s).

**Design implication if false — and it is the more damaging direction.** The mesh's *distribution*
property is not merely unused; it is **inverted on the one node that needs it**. The machine the owner
works on is the slowest to answer, therefore the least likely to be chosen, therefore the one that
keeps the work. That is the opposite of "route to the most empty part of the mesh", and it comes from
a single `preferred`/`dispatchable` branch, not from capacity.

**Settled or open?** **Settled for the `slow`-demotion behaviour** (measured, three times). `OPEN`
for how much of the zero-placement record that explains versus the tool-choice explanation in A6 —
the two are not mutually exclusive, and no measurement separates them. What would separate them:
count, per day, the `tool/call` records in the session store by tool name (`subagent` vs
`subagent_local` vs no delegation) alongside the broker's own placement log — one join over data that
already exists on disk, needing no load and no fleet.

### A9 — "A second or third machine is what makes it fast"

**What is assumed.** Adding nodes (the buy list, the elastic tier) is the path to more throughput.

**Where it is written.** `docs/mesh/61-buy-list-verified.md`; `docs/mesh/79-elastic-cloud.md`;
`docs/mesh/88-elastic-build.md`; the mesh program's whole architecture (`71-mesh-program.md` §1).

**What the measurements say.**
* `docs/mesh/84-calibration.md` §4.3: the desktop's own ceiling is **14–39 concurrent turns**
  depending on mix, against a 24-child cap the fleet never approached — the highest measured point was
  **8 of 18 slots, 6.6 % of the memory ceiling**.
* `docs/mesh/88-elastic-build.md` §4.2: the study's recommended single-node pick (CPX11, 2 vCPU)
  scores **1 slot under the broker's own core term and cannot absorb the 2-child fleet that is the
  trigger's minimum** — *"the cheapest plan on the board is not eligible for the only job that pays
  for it."* And §6.1–§6.2: the honest refusal is that the trigger **has never fired**, so an
  auto-firing provisioner is *"a mechanism for converting an occasional slowdown into a recurring
  bill."*
* `docs/mesh/96-gateway-at-scale.md` §4.1: **55 agents generating continuously cost ≈$68/hour
  off-peak and ≈$136/hour at peak — $408 for a six-hour block, $544 for an eight-hour night** — and
  the whole harness has **no cap at all** (`docs/dsh-at-scale/60-cost-audit.md` §8.2: *"DSH has no cap
  whatsoever"*; `P209` open in `journal/state/open-pain.md:148`).

**Design implication if false.** The path to "many agents fast" is not more machines. It is (a) not
paying for work twice (`60-cost-audit.md` §7 Tier 1: 82–96 % of prompt tokens are carried tool output;
the largest single lever is *"split long work across sessions"*, measured at 52.5 % of a $54.92 day
sitting in three sessions), and (b) **not corrupting the one engine's own gate** — the laptop's
`/api/session/list` took **>40 s at 17 concurrent loops** (`100-restart-when-idle.md` §2), which is a
single-engine scaling limit, not a fleet limit. `REASONING`: the honest ranking of the current
program's items by effect on *"many agents fast"* is cost-per-turn first, engine-side list/scaling
second, fleet size a distant third — which is the reverse of where the last two days went.

**Settled or open?** `tier != fits` has **never been observed**, so the elastic demand is `OPEN` by
construction. The one measurement that changes the recommendation is named in `88` §6.3: **two or more
*unplaceable* fleets in a rolling seven days.** That counter starts at zero and is cheap to start
collecting: the dispatcher already records `tier` per placement
(`packages/plugin-remote-fanout/bin/mesh-run.mjs:317–328`), so it is a scan of
`~/.dsh/mesh/logs/*.jsonl`.

---

## 4. Method: checks, evidence, and the owner

### A10 — "A check proves the thing"

**What is assumed.** A green check is evidence that the thing it names works.

**Where it is written.** Everywhere, but the load-bearing instances are named as policy:
`81-overnight-program.md:13` (*"the mesh is DONE when `pwsh -File scripts/mesh-e2e.ps1 -Strict` exits
0 with zero SKIPs"*); `journal/README.md:98` (*"Run `doctor` on a machine that has never hosted a
fleet before trusting it"*); `presets/zabz/skills/…/SKILL.md:63–65` (*"`doctor` is not decorative"*);
`docs/mesh/71-mesh-program.md:243–255` (the six acceptance steps).

**What contradicts it — seven instances, all measured, all in two days:**

| # | the check | what it returns | what is actually true | source |
|---|---|---|---|---|
| 1 | `dsh --profile web --dump-config` | **exit 0, 620 lines** from an Interactive-logon process | **exit 1, 16 lines** from an ssh-spawned one, *same bytes, same minute* — the reader that runs a dispatched child cannot compose the profile at all | `106-desktop-last-mile.md` §8 (and §1) |
| 2 | `dsh --profile web --dump-config` | exit 0, 620 lines | the desktop's engine loaded `version 0.1.0` with `resolvePlacementMode=False` and **no `placement.js`** — placement was inert on that machine while its row said otherwise | `105-placement-committed.md` §6.1 (diagnosis corrected by `106` §3.1: it was a linked revision, not a silent fallback — the *observable* is what matters here) |
| 3 | `journal.py check` | **0 errors** | **10 live cross-tree id collisions**, every one a different entry wearing one id | `107-journal-convergence.md` §6.1; `108-id-allocation.md` §10.1 |
| 4 | `journal.py repair-ids --apply` | reports the renumber | **leaves the offending file behind**; `check` still exits 1 afterwards | `107-journal-convergence.md` §6.2 (reproduced, then fixed) |
| 5 | `idguard` | **9 collisions** | the content comparison finds **10** | `107-journal-convergence.md` §6.4 |
| 6 | `scripts/mesh-health.ps1` | **exits 0, healthy** | its default node list is **3 of 5** gated nodes — it never reads the fail-open one | `95-audit-live-mesh.md` §5.1 |
| 7 | `scripts/mesh-capacity-probe.ps1` | passes | the Mac Mini is **not in `$GatedNodes`**, so its capacity is never read — the exact defect the comment above it says already happened once with `zabz-tech-linux` | `95-audit-live-mesh.md` §5.2 |

Add two more from the incident record, same class:
8. The engine's `ensure` retry loop treated *"port not answering"* as *"start it"* and could not see
   **crash-on-boot**; the answer (`exit 1` + a stack trace) was in a log nobody was told to read
   (`docs/incidents/2026-09-17-dsh-engine-boot-failure/diagnosis-report.md` §4.3, §7.3).
9. `engine-recovery.log`'s own guard reported the engine up while the plugin tree had not mounted —
   *"`ensure` returning 'answering' does not guarantee the plugin tree fully mounted"* (same document,
   §4.4).

**And one more, in the same family, on the acceptance path itself:** `81-overnight-program.md:13`
defines done as `mesh-e2e.ps1 -Strict` exiting 0, and the command **cannot** return 0: S3/S4/S5 SKIP
without `-DispatchFleet`/`-KillNodeHalf`, which §0 does not mention, so the exit is **2, every time,
on any mesh, forever** (`95-audit-live-mesh.md` §4.1 and §5.3, re-run: `counts {pass:5, fail:0,
skip:3}`, `EXIT=2`).

**What the design has to change so a check IS evidence.** From the measurements, three properties,
each of which one of the seven failures lacked:
1. **The reader is part of the claim.** `--dump-config`'s verdict is a function of the logon class and
   its output *never says which reader ran* (`106` §8). So a check must declare and stamp the
   context it ran in, and a profile check is only evidence for the class that ran it: ssh-spawned, a
   scheduled task, and the GUI engine are three different readers.
2. **The domain is part of the claim.** `mesh-health` and `mesh-capacity-probe` are sound and their
   *scope* is silently narrower than their front page (`95` §5.1–§5.2). A check whose node list is a
   literal in the file is a check that cannot notice a new node; the fix is to derive the domain from
   the same roster the broker reads, and to fail when a roster node is not checked.
3. **A check must be demonstrable in the failing direction, on the same invocation.** The ones that
   survive scrutiny all were: `mesh-e2e.ps1` S1, S2, S3, S4, S5b went red for real causes
   (`82-e2e-run.md` §0b), `S1` enforces `node == fqdn.split('.')[0]` rather than assuming it, and
   `mesh-run.mjs:229` refuses on exactly the traversal condition `--dump-config` cannot see. `108` §4.4
   and §6 are the model: the pre-change tool is **taken out of git and run**, so the test carries a
   demonstrated failure mode rather than an assertion.
4. And in the negative: **an empty result is not health.** `100-restart-when-idle.md` §3.2 has the
   worked example — the first version printed *"no session row carries running=true"* when
   `session/list` had simply timed out; the fix is to name which reading failed and keep the one that
   did not. The same rule appears as `84-calibration.md` §1.4.2 (*"a counter that reads 0 is not
   evidence that nothing happened"*).

**Design implication if false.** A green check must never be allowed to be the *only* claim, and the
acceptance criterion must be written so it can fail. Concretely: the redesign's definition of done
should be a set of commands that have each been **observed failing** for their own defect, with the
failing observation recorded next to the passing one — because seven times in two days this system
shipped a green light over a broken thing, and in two of those cases (1, 2) the green light was
produced by the *same binary on the same bytes*.

**Settled or open?** **Settled, and worse than stated.** It is not that checks are unreliable; it is
that this fleet has a measurable talent for building checks that cannot fail in the direction that
matters. That is an empirical finding, n = 7.

### A11 — "A record is a record" — the lesson survives because it is written down

**What is assumed (implicitly, by the whole redesign method).** Writing a correction into a document
propagates it.

**What contradicts it.** §0 above: `84-calibration.md` refuted 0.81 GB on 2026-09-17 and **five
deployed copies of the skill that the default path loads still carry it without a marker**, plus one
production README. `journal/state/in-flight.md` §F records the same failure at the journal layer:
`check` cannot see a cross-tree collision, `idguard` undercounts from a cache, `note_git_ceiling()` is
dead code — all three **"recorded, not fixed"**, and the collision class then recurred
(`108-id-allocation.md` §2: *"the 107 convergence resolved 18 contested ids and left the allocator
untouched"*). `docs/mesh/100-restart-when-idle.md` §5 is the cleanest example: an installed host-plane
row is **silently reverted from `~/.dsh` every 15 minutes unless it is committed**, and the same
document records the hand-edit being wiped within five minutes (`103` §2.5). Recorded as open pain
`P239`.

**Design implication if false.** A document is not a delivery mechanism; **a keeper is** — something
that runs, compares against the canonical value, and exits non-zero. `journal/README.md:233–245`
already names the shape (*"a component that can silently disappear needs a keeper, not a procedure"*)
and `scripts/install-client-plugins.ps1 -Check` is the one instance that exists. The redesign should
assume that anything not enforced by a keeper executing on a clock will be reverted — and that this
includes **the method documents themselves**, which is why the skill file still carries a refuted
constant.

**Settled or open?** **Settled. This is the mechanism by which every other wrong assumption here
survives**, which is why it ranks in the top three (§10).

### A12 — "The owner is the bottleneck we route around" / "the agent should decide"

**What is assumed.** Two competing statements, and the last two days encoded one of them.

**Where it is written.** Both are written, in different documents: routing *around* him —
`journal/state/open-pain.md` P1 (*"the owner is the scarcest resource in the system and he was acting
as a decision router for questions the agent should have decided"*), the `zabz` persona rules
(*"do not route development decisions to him"*), `docs/mesh/88` and §2.4 (*"That is a development
decision (rule 3), recorded here"*). Routing *to* him — the four-hour-plus restart gate:
`100-restart-when-idle.md` §10 item 3 (*"This is the one thing a human should decide"*),
`92-provider-placement.md` §8 (*"a restart is the owner's decision to schedule"*),
`105-placement-committed.md` §8 item 2, `106-desktop-last-mile.md` §11.6.

**Which one is true?** The record settles it as **materially false in the direction that cost the
most**. `P210` is open: *"A new bundle cannot hot-mount, so every plugin costs an engine restart and
the live sessions with it"* — and the restart is what **armed a cold-boot failure that made the
machine unbootable eleven hours later** (`docs/incidents/2026-09-17-dsh-engine-boot-failure/`: the
rebuild at 10:45 silently armed a generator bug that could not fire until the next cold boot, at
21:31; `DSH_HOME` was unset at all three scopes, and the generated `requireAnchor()` fell back to
`USERPROFILE` without the `.dsh` segment). **The 15-minute idle window was built, measured, gated, and
has never once fired** — `100` §3.3 shows it declining live at 16–17 loops, and §4 records the gate
open only when the owner's fleet is done, which is exactly when nobody needs it. And the *design*
that waited for him was waiting on a decision it had already made for itself: the same documents
state the fix as a one-line change and a marker file.

`REASONING`: the last two days encoded **"wait for the owner's idle window"**, and that is the
expensive of the two. It cost: four days of the mesh being wired-but-inert, a second machine stuck
pre-placement, and — indirectly — the only hardware-down incident of the period, because *"the restart
will activate it"* was allowed to be a plan rather than a checked state.

**Design implication if false.** The redesign must not have a class of change that requires a person
to be idle. Two measured escapes exist in the record and neither needs the owner:
(a) **an isolated `DSH_HOME` process** — `92` §7 and `105` §4.1 both prove the whole composed
configuration boots and dispatches on a *second engine on a scratch home on a second port*, with the
owner's engine untouched; that is a real acceptance path for any host-plane change, and it was used
three times; and (b) **a `mesh` profile needs no restart at all** (`71-mesh-program.md:261–265`),
because a fresh `dsh --profile mesh headless` process composes its own tree.
The remaining need — activating a row in the owner's *live* engine — is real and should be met by
making activation **safe and reversible** (a validated, rollback-able activation) rather than by
waiting for an idle window that the measurements show does not arrive.

**Settled or open?** **Settled: he is not the bottleneck; the loader is.** The open question is
whether hot-mount can be made safe — `100` §10 item 5 names the unmeasured mechanism: the profile
sets `"patchReload": "live"`, and **what an autosync rewrite of the live patch layer does to an
already-mounted host-plane row is not measured**. That is a cheap experiment on a scratch home.

### A13 — "Three stale things must be fixed together, and a restart checks none of them"

**What is assumed (by the design's own arithmetic).** A host-plane activation is one act.

**Where it is written.** `100-restart-when-idle.md` §11 item 1: *"A host-plane activation has three
parts, and they live in three places: the package (linked into `profiles/<p>/node_modules`), the rows
(`~/.dsh/profiles/<p>/cordis.patch.yml`), and the running engine. A restart only refreshes the
third."* And §5's measurement: the live layer was byte-identical to `HEAD`, which did **not** carry
the rows, and a 15-minute autosync rewrote them out.

**What contradicts the assumption.** Nothing — this one is *correctly* stated in the record and
simply has not been designed around. The contradiction is between the statement and the architecture:
`71-mesh-program.md:16` lists *"A mounted bundle cannot hot-load — **v1 must not require an engine
restart**"* as a **constraint that shapes every decision**, i.e. the program's architect knew the
three-place coupling was the risk and wrote the constraint — and then `92`, `100`, `105`, `106` and
`109` all ship changes that require a restart.

**Design implication if false.** A configuration system with three independently-stale copies and one
activation trigger will keep producing "installed, inert, and reverted by a 15-minute job" (`100`
§11 item 1's own words). The redesign should have **one composed artefact per boot**, produced from the
repo, verified by a single command that can fail, and *served as evidence alongside the running
process's identity* — so that "what is running" and "what is composed" cannot disagree silently the
way `--dump-config` and the loader did in A10 #1 and #2.

**Settled or open?** **Settled as a defect; the replacement is unbuilt.** `harness-verify.ps1` is the
nearest existing shape and is **not referenced by any mesh acceptance criterion**
(`95-audit-live-mesh.md` §5.5: *"cannot be checked as a mesh instrument because no mesh claim depends
on it"* — which is itself the finding).

---

## 5. The interfaces: windows, ids, and the shape of the UI

### A14 — "Windows must be full browser instances"

**What is assumed.** To get N independent parallel sessions on one engine, each window needs its own
Chromium `--user-data-dir`, which costs ~9 processes and ~892 MB.

**Where it is written.** `docs/dsh-at-scale/80-windows-and-parity.md` §4.3–§4.5 — and it is stated
**strongly and correctly for the build it was measuring**: *"`--user-data-dir` per window is how this
build gets them without a second engine"*, and *"N tabs in ONE window on ONE port do not give N
independent sessions"* because `localStorage["dsh.sessions.current"]` is keyed by **origin**
(scheme+host+**port**), read once at page load, and shared across tabs.

**What contradicts it.** `docs/multi-window/MEMORY-AND-SESSION-LIST.md` §1, measured 2026-09-18 on
this laptop: **seven windows on seven private profiles cost 74 processes / 6,804 MB — 9 processes and
a mean 892 MB per window.** Two windows opened into a **shared** profile on two *alias loopback
origins* cost **+9–10 processes / +440–635 MB for the first** (the one-time tree) and **+0–1
processes / +59–296 MB for the second**. *"Per-window marginal cost: ~9 processes / ~892 MB → ~1
process / ~60–296 MB."* The projection at 8 windows is **17 processes against 72**.

**The resolution is the part worth keeping.** The old design's own reason was right and the
implementation was wrong: what a window needs is a distinct **origin**, not a distinct **profile**.
`dshw-proxy.mjs` serves 24 loopback ports (`3200..3223`) as a raw TCP splice to 3099, so each window
gets its own origin, its own session slot, and a *shared* cookie jar — the measured gain being that a
window can no longer land on `dsh web authentication required` because a sibling already
authenticated the origin family (`MEMORY-AND-SESSION-LIST.md` §1, "What the owner loses: Nothing he
uses").

**Other shape assumptions in the same family that the measurements falsify:**
* **"A process scan can tell you which windows are open."** Falsified: in a shared profile **only the
  first window's URL appears in any process command line**; a scan finds one window in total and
  reports every other slot empty (`MEMORY-AND-SESSION-LIST.md` §4). The working liveness signal is
  live connections per alias port, and the probe must exclude itself (measured bug: slot 1 read as
  permanently open).
* **"Eighteen windows is the ceiling because that is what fits."** Falsified in the other direction:
  the real per-window cost is ~1 process, so the window axis is nowhere near binding; and the four
  `enabled: false` windows that were open anyway cost **1,731 MB, 44 % of the browser footprint**,
  because `dshw new` force-enabled every row before picking (`80-windows-and-parity.md` §2.1 —
  `foreach ($slot in $slots) { $slot.enabled = $true }`).
* **"~325 MB private per browser window"** (SKILL.md:135, `PROGRAM.md:75`) is a *private-bytes*
  figure for the old shape. It is not wrong where it was measured, and it is one of the numbers the
  shared-profile change made obsolete — and it is still in the skill beside the other two (§0).

**Design implication if false.** The most expensive real-world resource this design spent was
**browser processes**, and it spent it on an implementation detail (profile-per-window) rather than on
the actual requirement (origin-per-window). The redesign should re-ask the same question one level up:
*what is the minimum distinct thing a window needs, and is a browser process that thing?* On this
evidence a window needs **an origin and a renderer**, nothing else.

**Settled or open?** **Settled, measured, and already fixed in `dshw.ps1`** — but the corrected number
has not reached the documents that plan against it, and the fix carries a stated cost that has not
been exercised: *"a **browser-process** crash now takes every window with it"*, with restore-after-a-
real-reboot **not tested** (`MEMORY-AND-SESSION-LIST.md` §6).

### A15 — "`~/.dsh/profiles/<p>/package.json` is the bundle list, and a junction makes a package live"

**What is assumed.** A package linked into the profile is the package the engine will load.

**What contradicts it.** `105-placement-committed.md` §6.1 and `106-desktop-last-mile.md` §2–§3,
measured on `zabz-tech`: the junction was present, its target existed, twelve files were in it — and
`cmd /c type <junction>\lib\index.js` returned **"The path cannot be traversed because it contains an
untrusted mount point."** The engine booted anyway, resolving a *different, older* copy (0.1.0,
4,382 bytes, no `placement.js`), and `--dump-config` exited **0 with 620 lines**. The discriminator,
established 9/9 plus two probes, is the **reparse point's ACL owner**: a junction owned by
`BUILTIN\Administrators` is traversable by an ssh-logon process; one owned by `zabz-tech\ezabz` is
not; a local Interactive process traverses both (`106` §3). This **inverted** the previous document's
rule (`99` §2.2 said ssh-created = untrusted; `105` §8 item 7 said task-created = trusted), and §3.2
of `106` records a discrepancy between `105` and `106` that **cannot be resolved from the evidence
available**.

**Design implication if false.** On Windows, "the package is installed" is a claim about a reparse
point's owner, and the ordinary tools (`Test-Path`, `dir`, `--dump-config`) do not test it. A
redesign that deploys code by junction must ship a **read-through-the-link** proof as the install's
own definition of done, not a listing — which is what `106` §2.3 did, and what `104` §2.2's
`node resolve` does.

**Settled or open?** **Settled on this machine, OPEN as a general rule** — `106` §3.2 explicitly
records two sessions disagreeing about one unchanged reparse point. The measurement that would settle
it: `fsutil reparsepoint query` plus the ACL owner, read on a third machine, with the reader class
named — which is A10's rule 1 applied to Windows itself.

### A16 — "The journal is the memory, append-only, ids allocated by taking the maximum"

**What is assumed.** An id is minted as `max(visible) + 1`, so two machines cannot mint the same id.

**Where it is written.** `journal/tools/journal.py` (the allocation block), described at
`journal/README.md:447+`; refuted and replaced by `docs/mesh/108-id-allocation.md`.

**What contradicts it — four collisions in two days, and the model is explicitly wrong:**
* `journal/state/open-pain.md` `P212`: *"Journal ids collide **by construction**: `max(seen)+1` means
  two machines writing concurrently pick the same number (measured 10/10)."*
* `docs/mesh/107-journal-convergence.md`: **18 contested ids** (10 live, 8 latent), and `check`
  reported **0 errors while all 18 existed**.
* `docs/mesh/108-id-allocation.md` §6.1: the pre-change tool is taken **out of git at `622876e`** and
  run — *"m1 rc=0 minted `['L2']`; m2 rc=0 minted `['L2']`"* — the same id on two machines that cannot
  see each other's uncommitted work, demonstrated rather than argued.
* `journal/state/in-flight.md`: *"One journal id means two different entries across machines — third
  occurrence"* (`P233`), plus `P182`, `P184`, `P197`.

**Why the wrong model survived so long, and it is the interesting part.** `108` §3 records the design
space honestly: (a) per-host bands, (b) a host suffix on the id, (c) a window reserved in the repo. It
chose **(c)** *because (b) would break the id format*, and said so: *"every existing id is bare
(`L1927`, `D259`) … A mis-parse in any of them produces an id that means two things."* So the
collision class was knowingly traded for format compatibility. Then the implementation of (c)
introduced its own defects, four of them, each one silent (`108` §5.6): `git mktree` refusing slashed
paths, a temporary index silently dropping the new file (`exit 0, nothing written`), a `(number, rev)`
tuple going into `max()` behind a guard that swallowed the `TypeError`, and a publish that **replaced**
the shared ledger with one machine's row.

**Was the model wrong or the implementation?** **Both, and separated by the evidence:**
1. **The model was wrong** for a fleet of machines that cannot see each other's uncommitted work —
   proven by running the old tool against itself (`108` §6.1), not by argument. `P212`'s 10/10 is the
   population number.
2. **The implementation was wrong on top of it**, and the fix chose compatibility over robustness.
   `108` §3(b) says in terms: *"**It remains the right answer for a future that can break the id
   format deliberately**"* — i.e. the model that is collision-proof *by construction* was identified
   and deferred, not rejected. That deferral is still standing: `journal/state/in-flight.md` §B says
   *"the real fix is still the reserved band per machine, or a host suffix … **Highest-value
   follow-up here**"*, and the *same file* in the newer section records the follow-up as **done** for
   the generator while leaving the overlap window open by design (`108` §4.2: *"while a machine is
   holding a local window whose top is beyond the published ledger, that window is not yet visible to
   anyone else, so another machine could have published the same numbers in the meantime"*).
3. **A third defect class is untouched**: `check` is single-tree by contract, so an id that differs on
   `origin/master` is **invisible** to it (`108` §10.1: *"`check` reported 0 errors while all 18
   collisions were live"*), and `idguard` reads a generated cache that a committing writer must
   remember to rebuild (`108` §10.2: reported 9 where the answer was 10). **Recorded, not built.**

**Design implication if false.** Two: the *durability* property is fine (append-only, one file per
entry, a generated cache that heals, a sha per body) and should be kept; the *identity* property is
still conditional on a convention. A redesign that wants "ids mean one thing" must either mint them
with a namespace that is disjoint by construction (and pay the format break deliberately, once, with
the migration planned) or accept that publication is a prerequisite for writing and make that a hard
refusal everywhere — `108` §4.4 already defines that fail-closed table, and it is good.

**Settled or open?** **The generator is FIXED and proved** (`108` §6.1–6.2, `verify-alloc.py` 21 checks
0 failures; a reservation for `ZABZ-YOGA` up to `L1990` is published). **The window-overlap race is
OPEN and structural**, and `108` §11 admits the whole thing *has never been run on any other node* and
*the publish path has never run against the live `origin/master`*. Measurements that would settle it:
`journal.py claim lessons` on `zabz-tech` and `zabz-yoga-1` in the same minute, then
`journal.py next-id lessons --plan` on both (expect disjoint); and the two-call cross-tree detector
`108` §10.1 specifies, run as a gate (`git hash-object --stdin-paths` locally +
`git ls-tree -r origin/master journal/entries` upstream — no cache, one subprocess each).

---

## 6. People and process

### A17 — "The owner is the bottleneck we route around" — the *other* half

Covered as A12. Stated separately here because it has a second, distinct failure: **the queue itself
was routed around.** `journal/README.md:259` says the owner-decision queue *"holds only what is
genuinely his … with one recommendation per row and never a menu of five."* What actually reached him
was a **15-minute scheduled restart window that has never fired** (`100` §3.3) and a host-plane
activation that waited on his idleness for four days — while the same documents record **three
separate surfaces where the fix was already decided and one line away** (`100` §5's installer step,
`105` §8 item 1's junction repair, `109` §6's restart). `REASONING`: this is not "asking him too
much"; it is **deferring to him what had already been decided**, which is the failure P1 names and
which the redesign must make structurally impossible: a change whose activation needs a human must
either be *made safe to activate* or be *explicitly queued as his decision*, not left armed in a
scheduled task.

### A18 — "The fleet is what makes progress" — and the two reported as running

**Where it is written.** `presets/zabz/skills/…/SKILL.md:8–16` (*"You manage; they build … A serial
agent stops after every increment"*), with the measured basis: 2,283 turns were the owner saying
*"keep going"*.

**What contradicts part of it.** `journal/state/open-pain.md` `P181`: *"Two of six workstreams landed
**0 commits** while reporting 'running'; 'running' is an assertion, not evidence — count commits per
branch."* The skill anticipates this exactly — §5: *"An agent's report is a claim, not evidence.
Reproduce it."* — and the measured instance shows the anticipation was not enough. `REASONING`: the
skill's own rule is stated in the right place (integration) and the wrong one (start). What the record
supports is *counting artefacts* (commits per branch, files changed, a command's output line) rather
than *believing status* — which is A10's rule 4 applied to agents.

**Settled or open?** **Settled that "running" is not evidence.** Open as to the *rate*: no document
measures how many fleet-houred agents produce an integrated artefact, which is the number that would
justify the method's cost. Cheap measurement: per fleet run, `git log --oneline main..branch | wc -l`
per branch, already recorded in every journal handoff (`SKILL.md:103–105`).

### A19 — "Five machines, six devices, one fleet"

**Where it is written.** `journal/README.md`'s machine table; `docs/mesh/10-inventory.md` §10;
`71-mesh-program.md` §0.

**What contradicts it.** The measurements do not show one fleet; they show **five different
revisions of the same components**: three gate revisions with **no common lineage**, two of them
outside any repository (`95-audit-live-mesh.md` §4.1; `99` §5.1 adds that the `zabz-tech-linux`
copy `git rev-parse --is-inside-work-tree` returns *"not a git repository"*); one node whose
`web` profile **cannot boot** (`95` §3.2: a `dsh-mesh-broker` row with no `dsh.bundle` marker); one
node **fail-open** on the device allow-list because the allow file sits beside whichever
`phone-gate.py` is running (`95` §4.2 — a foreign device gets **HTTP 200 and a signed-in session**,
"a shell as the owner"); a Mac Mini that answers capacity but is **not in the broker's roster** despite
the roster's own condition for adding it having been met (`95` §2.2); and a `secratary` dispatch row
marked `null`-unmeasured for a reason that **stopped being true nine hours earlier** (`95` §3.4).

**Design implication if false.** *"One source of truth"* is a property of the **repository**, and the
measured property of the **fleet** is drift with no detector: the allow-file convention, the
gate-beside-the-script resolution (`ALLOW_FILE = Path(__file__).resolve().parent / "phone-gate-allow.txt"`),
and the profile bundle list are each *per-node local facts* dressed as fleet facts. A redesign must
either make each node's state derivable from the repo by a command that can fail
(`99` §5.2 proposes exactly this: an explicit `--allow-file`, fail-closed on absence, plus a keeper
that compares the *running* gate's hash) or stop claiming fleet-level properties.

**Settled or open?** **Settled, and it includes a live security exposure** that is a *present* hole,
not a future risk (`95`: *"It is not a future risk, it is a present exposure, and the only thing that
changes is who notices"*).

---

## 7. Assumptions that turned out to be fine — recorded so they are not "fixed" later

| # | assumption | evidence it holds |
|---|---|---|
| F1 | One engine per `DSH_HOME`, one home per node | 1 engine per node on all five, measured twice (`95` §3.1) |
| F2 | `dsh --profile headless "<task>"` is a working cross-node transport | `71` §0; 11 real children across four runs, every `MESH-HOST:` matching (`92` §7) |
| F3 | The gate is the right place for the capacity surface | it restarts freely and needs no engine restart (`71` §0, `79` §5.3) |
| F4 | The broker never refuses — queue, never amputate | forced twice: every node caller-excluded → 200 + `position 4`; a 999-child fleet → 200 + `position 5` (`95` §2.4) |
| F5 | The `rationale` is auditable | 13 lines naming the arithmetic, the reserve and its basis, the disk floor per child, the lease TTL (`95` §2.3) |
| F6 | The prompt prefix is clean and 99.1 % cached | 42 % of DSH spend is cache-**hit** re-read; `totalTokens == input + cacheRead + output` held 31,292 of 31,292 (`60-cost-audit.md` §2.1) |

**F4 and F5 are the two design decisions in the whole estate that the adversarial audit could not
break**, and both are structural (never-refuse, and print the arithmetic) rather than numeric. They
are the model for the redesign.

---

## 8. Open empirical questions, with the measurement that would settle each

| # | question | command sketch | cost |
|---|---|---|---|
| Q1 | the laptop's real per-turn cost and ceiling (A1, A2) | the O3 rig, driven **from `zabz-tech`** against `zabz-yoga-1`, N = 2,4,6,8; `84-calibration.md` §6.1 | ~90 turns, no fleet on the laptop |
| Q2 | whether the mesh reduces load when the pressure path is live (A6) | after one honest idle restart: one `subagent` call from a saturated laptop; read the report's `pressure = …` line (`109` §7) | 1 turn |
| Q3 | how many of the zero placements were tool choice vs the `slow` demotion (A8) | count `tool/call` names in `~/.dsh/sessions/**/*.jsonl.zstd` against `~/.dsh/mesh/logs/*.jsonl` `phase:place` rows, per day | 0 turns |
| Q4 | whether session placement is a principle or a consequence (A7) | time `listArtifacts()`'s walk over a network-backed store vs local NVMe (the local figure is 5.9 s for 681 sessions, `MEMORY-AND-SESSION-LIST.md` §2) | 0 turns |
| Q5 | whether a live patch-layer rewrite disturbs a mounted host-plane row (A12) | on a scratch `DSH_HOME`, boot the profile, rewrite `cordis.patch.yml` underneath it, then call the tool | minutes |
| Q6 | the exact bill at fleet scale (A9) | the provider console export for the run window; `60-cost-audit.md` §8.3 — **no usage API exists** | owner-produced CSV |
| Q7 | the logical→physical core conversion under SMT (A3) | `84-calibration.md` §6.6 — not measured anywhere | one sweep |
| Q8 | whether the two-call cross-tree id detector finds collisions `check` cannot (A16) | `git hash-object --stdin-paths` locally + `git ls-tree -r origin/master journal/entries` upstream, compared; `108` §10.1 | 0 turns |

---

## 9. Assumptions I expected to find and could not substantiate

Honest gaps. Each of these is something a redesign might want to rely on, and there is **no
measurement** for it in the record — so it must be measured before it is built on.

1. **"The eight hours of idle broker, 04:12Z → 13:13Z, were zero units of work placed"** — the
   framing I was given. I could not find that counter in the repository. What I *can* cite:
   the broker's last placement was `2026-09-17T04:12:42Z` and the newest dispatcher record was
   `04-14-39-996Z`, so **nine hours passed with the processes live and the workload not**
   (`95-audit-live-mesh.md` §0: *"Nine hours of idle. The processes are live; the workload is not."*);
   and `109-pressure-routing.md` §1: *"the ledger under `<DSH_HOME>/mesh/placements/` recorded **no
   placement all day**"* on the evening of 09-18. Searched `docs/**` and `journal/**` for
   `eighty minutes`, `zero work`, `placed nothing`, `no units of work` — no match. **The claim is
   probably right; it is not sourced, and I will not put an unsourced count in the redesign's
   evidence base.** What would settle it: `ls -la ~/.dsh/mesh/placements/ | wc -l` plus the timestamp
   histogram of `~/.dsh/mesh/logs/*.jsonl` — both local, both free.
2. **"55 agents on this fleet will be slow"** — the number 55 appears as **the owner's intention**, not
   as a measurement, in every document that uses it (`92` §1: *"he intends to open ten windows with
   several agents each — on the order of 55 concurrent agents"*; `95` §7(a) reasons from it). No
   document measures a 55-agent fleet. `40-hardware-costs.md:21` already flags the same class
   (*"the demand figure is asserted, never measured"*) for 40–55 turns. The one thing that *is*
   measured at that scale is the wallet: **$68/hour off-peak, $136/hour peak** (`96` §4.1).
3. **"The engine is the scaling bottleneck"** — repeatedly implied by
   `docs/dsh-at-scale/60-cost-audit.md` §1.2 (`cost = requests × mean context`) and by
   `100-restart-when-idle.md` §2's `session/list` at **>40 s under 17 loops**, but no document
   measures engine-side throughput as a function of concurrency. The cost measurement is about
   **tokens**, not about the engine. Open: it decides whether "many agents fast" is an engine problem
   or a model-billing problem, and the two have different fixes.
4. **"Idle browser windows are cheap."** The number claimed is 0.24–0.28 core and 467–783 MB private
   per quiet window (`80-windows-and-parity.md` §6.4, quoting `PERFORMANCE-MEASURED.md:171`), and 12
   idle windows measured 2.27 of 22 cores. That is **not cheap** at 40 windows, and it is the axis
   the shared-profile change did *not* fix (it fixes processes, not the renderer). This is **REASONING
   from cited numbers**, not a measurement I have: nobody has measured 20+ shared-profile windows.
5. **"The owner's 12–18 sessions are the load."** Asserted in the incident narrative and visible in
   the census (`100` §3.3: 16 running, ids and titles named; `95` §1.1: `loopsRunning: 7,
   sessionsLive: 12`), but no document attributes the laptop's commit charge to the sessions rather
   than to the browser fleet or the MCP servers. `80-windows-and-parity.md` §6.1 has the parts
   (browser 3.9 GB, engine tree 1.56 GB, MCP ~355 MB, commit 20.65 GB) — and **~15 GB unaccounted**.
   That gap is the single most useful unmeasured thing on this machine, and it is free to close:
   `Get-Process | Group-Object ProcessName | Sort-Object {($_.Group | Measure-Object WorkingSet64 -Sum).Sum} -Descending | Select -First 15`
   against `\Memory\Committed Bytes` in the same second.

---

## 10. The three assumptions that, if wrong, cost the most — ranked

### 1. A4/A3 — "memory is the binding resource, and a slot count is the right capacity score"

**Wrong, and it is the deepest one.** The hardware measurement (three independent fits, three
counters, one confidence interval — `84-calibration.md` §3) says the memory term is pinned at its cap
on every node in the fleet, so placement is decided by `floor(physical cores × 0.75)` and by nothing
else; and the core term's own derivation converts a *paging* observation into a *CPU* budget
(`84-calibration.md` §4.3). Consequences already paid: the **admission governor the owner uses daily**
budgets memory at 160 MB per in-flight tool call and caps at 24 slots on a **4-core authority**
(`95` §1.4); placement advertises **12 free slots on a machine holding 126 % of physical memory**
(`109` §1); and the fleet's own `accepts.maxChildren` is a hardcoded **12 on every node**, sourced from
a JSON example in a frozen interface document (`95` §1.4, `phone-gate.py:937–939`). **If a redesign
keeps *any* form of slot product, it rebuilds a control that cannot see load — and the load is what the
owner asked to be routed around.** Cost if not corrected: every future placement decision, silently,
for as long as the formula lives, plus a purchase decision (`40-hardware-costs.md`, `61-buy-list`) that
was sized against a demand figure (`40–55 turns`) that no document measures.

### 2. A9 — "bigger fleet, more machines is the path to speed"

**Wrong in its economics, and the direction is measured.** `docs/mesh/96-gateway-at-scale.md` §4.1:
**55 agents generating continuously cost ≈$68/hour off-peak and ≈$136/hour at peak — $408 for a
six-hour block and $544 for an eight-hour night** — and the harness has **no cap at all**
(`60-cost-audit.md` §8.2; `P209`, open). The same audit measured that **82–96 % of carried prompt
tokens are tool output** and that the three priciest sessions were **52.5 % of a $54.92 day** — so the
lever with the largest measured effect on "many agents fast" is *cost and context per turn*, not
fleet size. Meanwhile `88-elastic-build.md` §6 refuses the elastic tier on its own evidence (the
trigger has **never fired**) and §4.2 finds the study's cheapest recommended node **cannot seat the
smallest job the trigger is allowed to fire for**. Cost if not corrected: the machine survives the
load and the wallet does not — and unlike the machine, the wallet has no ceiling and no alarm, so the
failure is silent and unbounded. This is the only assumption here whose false-belief failure mode is
**money**, and money is the owner's.

### 3. A10/A11 — "a check proves the thing, and a written record propagates"

**Wrong seven times in two days, and it is the reason the other two stayed wrong.** #1 and #2 of the
table in A10 are the same binary on the same bytes giving opposite verdicts by logon class; #3 is a
green gate over ten live id collisions; #6 and #7 are checks whose *domain* was silently narrower than
their front page; and the acceptance criterion in `81-overnight-program.md:13` **cannot return the
value it requires — exit 2, every time, on any mesh, forever** (`95` §4.1). A11 is the mechanism that
keeps those alive: `84-calibration.md` refuted 0.81 GB, and **five deployed copies of the skill this
system loads by default still carry it with no correction marker**, alongside a production README.
Cost if not corrected: the redesign's own acceptance criteria will be written as commands that exit 0
on a broken system, and its own corrections will fail to reach the copies that matter — which means the
**next** autopsy will find this one's conclusions still in force. It is ranked third only because it is
the cheapest to fix (declare the reader, derive the domain, prove the failing direction, and put a
keeper on anything that must stay true) and because its cost is multiplied by the two above it rather
than added to them.

---

## 11. What I measured myself, this session

Host `ZABZ-YOGA`, read 2026-09-17 (local evening) in one command:

```powershell
$os = Get-CimInstance Win32_OperatingSystem; $cs = Get-CimInstance Win32_ComputerSystem
"logical cores = $($cs.NumberOfLogicalProcessors)"
"totalMiB      = $([math]::Round($os.TotalVisibleMemorySize/1024,0))"
"freeMiB       = $([math]::Round($os.FreePhysicalMemory/1024,0))"
"commitLimitMiB= $([math]::Round($os.TotalVirtualMemorySize/1024,0))"
"commitFreeMiB = $([math]::Round($os.FreeVirtualMemory/1024,0))"
"committedMiB  = $([math]::Round(($os.TotalVirtualMemorySize-$os.FreeVirtualMemory)/1024,0))"
(Get-CimInstance Win32_PageFileUsage) | Select AllocatedBaseSize,CurrentUsage
@(Get-Process node).Count ; @(Get-Process msedge).Count
```

```
logical cores = 22
totalMiB      = 32373
freeMiB       = 10713
commitLimitMiB= 44149
commitFreeMiB = 17008
committedMiB  = 27141
pagefile      = 11776 allocated, 222 in use
node procs    = 16
msedge procs  = 65
healthz       = 401 (unauthenticated; the endpoint answers)
```

Three uses: (a) A4 — the pagefile is **1.9 % used at 84 % of physical committed**, so nothing on this
machine is paging, which is the measurement the governor's memory basis is not equal to; (b) A2 — the
fitted 403 MiB/turn applied to *this* machine's own numbers gives ≈13 turns to physical and ≈42 to the
commit limit, which is the arithmetic that separates the two thresholds the skill conflates; (c) the
reproducibility of any claim here on the machine the owner is using, without a fleet.

**I ran nothing else.** No engine was restarted or signalled; no gate was touched; no process was
killed; no fleet was dispatched; no git state changed; no file other than this one was created or
edited. A cross-node read was **not** attempted: the brief forbids touching other machines, the audit
of 09-17 measured four of five dead or misconfigured in ways that change hourly, and a stale reading
carried from another machine is the exact failure this document is about (§10 of the owner's standing
rules: *"if you cannot state a source and its age, do not report a number"*).

**Owed to a later stream, and deliberately not done here:** the eight open measurements in §8, the
five unsourced assumptions in §9, and the one thing I could not find at all — the zero-placement
counter, which is a two-command local read and should be taken before any redesign of the mesh's
*routing* rests on it.
