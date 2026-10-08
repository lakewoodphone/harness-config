# E — Red team: breaking the redesign before it is built

**Stream E of the redesign. Owns exactly one file: this one.** Nothing was written, moved, deleted,
started, stopped, restarted or reconfigured to produce it; no git state was changed. **Written:**
2026-09-18 on `ZABZ-YOGA`, reading the tree at `C:\Users\ezabz\code\harness-config`.
**Mandate:** attack `D-architecture.md` in six named orders, cite the design's own section or line for
every objection, cite a source for every measurement, soften nothing, invent nothing.

**What I read.** `docs/redesign/A-as-built-and-evidence.md`, `B-assumptions.md`, `C-research.md` and
`D-architecture.md` in full, myself. The primary sources the design leans on (`docs/mesh/84, 93, 95,
109, 20, 71, 76`, `docs/incidents/2026-09-17-dsh-engine-boot-failure/*`,
`docs/multi-window/MEMORY-AND-SESSION-LIST.md`) through five delegated read-only extraction sessions
plus my own greps, so that every quoted sentence below was read out of the file rather than out of a
sibling's summary. **I measured nothing on any machine and ran no command that changes state.**

**One method note, and it matters for anyone checking my citations.** The line numbers a reader tool
reports for these files do not agree with the line numbers PowerShell's `Get-Content` reports for the
same file (D 1304 vs 1137; A 1400 vs 1175; B 968 vs 798; C 1264 vs 1034), so I cite **sections** and
quote **verbatim text** rather than quoting line numbers that two tools disagree about. Where I do
give a number for a primary source, it is a number an extraction session read out of the file.

**Verdict in one line.** This is a better architecture than the one it replaces and it is **not yet
buildable as written**: three of its central mechanisms are undefined or self-contradicting, one
headline claim about the wallet is a slogan rather than a mechanism, and its own change-classification
table cannot classify the first step of its own migration path. It also contains the single best
verification idea in this estate (V4), and it does not repeat the original sin of an invented
measurement — its unsourced constants are all *parameters of new machinery*, not measurements.

---

## 1. The seven new failure classes

The brief's seven pathologies, each with the design's answer, each with the design's **own** version.
The last column is my verdict: does the design prevent the class or move it.

| # | old pathology | D's answer | D's own version of it | verdict |
|---|---|---|---|---|
| 1 | a check that cannot fail | §3.7 V4/V5 | the contract's own named-skip exemption; three states/policies defined by an unbound `T`/`N`; `full` indistinguishable from a miscalculation | **moved** |
| 2 | a stale view built on a cached local ref | §3.7 V6; §3.2 item 1 | the fleet strip ("Cost: one cached RPC"); the catalog's write seam is engine code, which the design cannot activate | **moved, worse** |
| 3 | a silent fallback | §3.3.5 (deletes "dispatch anyway") | §3.3.7 step 1 (a local child never touches the queue); §3.5's fallback origin lands the window on a different session; `unknown` admission has no stated behaviour | **moved** |
| 4 | work that looks running but is queued/waiting | §3.3.7 step 2; §3.3.2's `stalled` | the claim-ahead buffer (§3.3.1); a gang reservation idling 5 slots (§3.3.3); a local child defeated by no mechanism | **moved, and inverted** |
| 5 | a single point of failure nobody named | §3.8 (nine rows, three marked NEW) | the guard row's import (A §1.12 #7, fired once) is absent from the table and M3 makes it universal; the truth of every node's self-report has no second reader; the provider wrapper is S-class and on every delegation path | **not prevented** |
| 6 | a policy enforced where a tool is named | §3.3.7 (the `ctx.subagents` seam) | the seam is a **preset-layer row**, so enforcement is per *composition*, and §3.6 item 0 makes per-process composition the default execution unit; `pwsh`/ssh are outside it; the owner's own windows are outside §3.3.6 | **moved one level** |
| 7 | a corrected fact never reaches the copies | §3.7 V8; §5 M0.5 | the keeper has no declared reader class; a keeper that reds falsely is ignored (measured); the registry's anchor is a mutable path that exists twice with different bytes | **partly prevented, anchor is mutable** |

### 1.1 A check that cannot fail

D's answer is real and it is the best thing in the document: **V4** ("Every check ships with a
demonstrated failure… *A check whose failure has not been observed is a claim, not a check*") and **V5**
("`PASS / FAIL / SKIP / UNVERIFIED / STALE`… `-Strict` exiting 2 with SKIPs must be a **red**, not a
footnote"). Two holes remain.

**(a) V5's own escape hatch is the defect it was written to kill.** V5 says SKIP and UNVERIFIED are
reds *"unless the contract explicitly names them"*. The check that failed on 2026-09-17 (A §3.7 row 3,
B §A10) failed because **the contract named a command that could not satisfy it** — the defect was in
the contract, not in the runner. A rule that lets the contract authorise a skip hands the same author
the same power again. Nothing in §3.6 or §5 puts a keeper on the contract itself, and V4's "demonstrated
failure" requirement is stated for checks, not for the executable contract that defines them.

**(b) Three of the design's new states and policies are defined by a quantity it never values.** `stalled`
is "has slots and has not claimed **within T**" (§3.3.2); the cull policy closes a session "idle by *both*
signals **past T**" (§3.5 item 2); the supervisor "boots it when the new one fails to become healthy **N**
times" (§3.6 item 4). A state whose threshold is undefined cannot be entered, and a health surface with an
unenterable fault state reports health. This is A §3.7's row 12 shape ("the check cannot fail") sitting
inside the design's own four-state model.

**(c) The one state that *can* be entered is the dangerous one.** §3.3.2's four states are `draining`,
`full`, `stalled`, `unknown`. `stalled` catches a node that has slots and is not claiming — a *fault*. A
node whose admission is permanently miscalculated reads `full` and says so "with its own arithmetic"
(§3.3.2) — and `full` is indistinguishable from a node that is genuinely busy, because **the design
deleted the ranking tiering that used to give a second reader a chance to disagree**. Under the broker,
`/mesh/capacity` was read by another component (A §1.6: "each node's gate answering `/mesh/capacity`");
under D that field is self-reported and nobody cross-checks it (§3.3.4: "No penalty, no exclusion"). D2's
defect — a node publishing a slot count with **between 12 and 1 of them having any relation to whether
the machine could hold a child** (109 §1) — is the same defect with the sign flipped. The design calls its
biggest risk "a queue that can be **quiet**" (§3.8 closing paragraph); the quieter failure is a node that
is confidently full.

### 1.2 A stale view built on a cached local ref

D knows the class and names the pattern: V6 ("No check may read a generated cache, a mutable name, or a
memoised answer as if it were the source"), the catalog "extending the in-house `journal/index/` pattern"
(§3.2 item 1), and the cache kept explicitly as "one of six published remedies and the only one that
leaves the pathology in place" (§3.2 item 1, §4.2). Two new instances are created by the design.

**(a) The fleet strip is a cached view whose freshness is never stated.** §3.5 item 2 puts the strip in
"every window", served by "the launcher's `dshw-proxy.mjs`, which already keeps **one** cached
`session/list` response and re-labels it per caller", and prices it: "**Cost: one cached RPC.**" But the
strip's job is to show "each node, its own admission arithmetic, its queue depth, its `stalled`/`full`/
`draining` state; the wallet (spend today, rate, ceiling)". The design never says how fresh those numbers
are, who reads them, or what they say when the read fails — and the one cost it prices is a cached RPC, whose
measured live state on this machine was `ageMs: 30822`, `rows: 694`, with background refreshes
taking **3.5 s to 20 s** and a prewarm path that failed for ~13 minutes (A §1.4, A §2.5). Worse: the
proxy keeps **one** session list. The moment M7 lets two windows point at two different nodes, that one
cached response is *wrong content* for every window but one, and re-labelling `rpcId` (which is what
"re-labelled per caller" means — the client throws on a mismatched id, MEMORY §2) does not fix the
content. **D ships a cache that its own step M7 makes incorrect, and marks it as a stopgap for a
different problem.**

**(b) The catalog cannot be written where the design says it is written.** §3.2 item 1: the index is
"Written **in the same critical section as the mutation** (create/rename/append/close)". The mutation
happens inside the engine's session store — A §1.1: sessions are "in-memory objects **in this one
process**", and the store is `dsh-session-persistence-jsonl`, whose lock is the write lease of §1.3
below. A plugin cannot enter that critical section, and A §1.6 measures that "**A new bundle does not
hot-mount**… `GET /healthz` → 404 before and after adding the bundle name to a *running* engine", so
even a host-plane component needs a restart the design calls H-class and says to avoid (§3.6 item 1).
So either the catalog is engine code — H-class, on the engine the design says must not need restarts —
or the catalog is maintained outside the critical section, which is exactly `idguard`'s measured failure:
"the gate is only as fresh as a generated file a writer has to remember to rebuild" (A §2.12, `108 §10.2`).
D quotes that failure as the reason the session index is different, and does not say which process writes
it. **This is the same defect class as the one it cites, at the same seam, with no answer.**

### 1.3 A silent fallback

D deletes one fallback explicitly and well — §3.3.5: "**The single reversal I make of today's behaviour:** a
queue wait that expires must **not** 'dispatch anyway'", with the measured reason ("at expiry the code
**cannot tell the two apart**", `92 §5.5`, `93 §3`). Three new ones appear.

**(a) The cheapest path is a fallback by construction and it is unannounced.** §3.3.1: "*the local decision
needs no network at all* — a worker with a free slot reads its own machine and starts work (§3.3.2), and
**a local child never touches the queue store**"; §3.3.7 step 1: "If it has a slot and the target is local,
start the child — the cheapest path, no network, no queue." The measured consequence of exactly this
behaviour is D2's own evidence (`109 §1`): "*the ledger under `<DSH_HOME>/mesh/placements/` recorded **no
placement all day**, because the model in each window chose `subagent_local` (or worked itself), and
neither of those paths measures anything*." Under D, when the node has room, *no queue entry is created* —
so the fleet strip, the ledger and the queue depth are blind to the work that is actually running. D's
claim that "D2 … becomes impossible in the same way a mail server cannot 'have mail nobody fetched'"
(§3.3.1) is true only for work that *needed* a slot elsewhere. The load that matters most — a busy machine
busy with its own local children — is exactly the load the queue is designed not to see.

**(b) The declared fallback for a dead proxy silently changes which session the window is.** §3.5: "the
engine's own loopback port remains a valid fallback origin", and `Resolve-WindowUrl` "uses the first one
that survives a real request" (MEMORY §3A). A request surviving a fallback origin proves the *engine*
answers; it proves nothing about the *session*. That is the `Test-LaunchUrl` failure class exactly — "it
only ever checked the token's **shape**" (A §3.7 row 14) — reproduced as M7's stated mitigation.

**(c) The partition case is answered twice, differently.** §3.3.5: "**Cross-site jobs queue** rather than
being dispatched into a void" and "each site keeps its own queue and drains it locally". §3.3.7 step 3:
"If the local option is declined and the queue is unreachable, **refuse** with the reading named." §3.8
SPOF 1 places "the queue store (authority, **NEW**)". §6.3 admits "*whether the queue store belongs there,
on a second box, or on a `systemd`-supervised static file store, is a real question I have not answered*."
With one store on the authority, the home site has no queue during a tailnet partition and §3.3.5's
"drains it locally" is false; with two stores, §3.3.7 step 3's "the queue is unreachable" is nearly
unreachable and the refusal is dead code. The design cannot have both, and it does not choose.

**(d) `unknown` has no behaviour.** §3.3.2 defines the state ("`unknown` (no reading, and it says so rather
than guessing)") and never says whether a worker in `unknown` claims or does not. Either answer
re-creates a named failure: claim, and you get D2's 12-free-slots-on-a-machine-at-126 % (`109 §1`);
do not claim, and you get nine hours with every process alive (`95 §0`).

### 1.4 Work that looks running but is queued or waiting

The design explicitly fixes the published-agency half — §3.3.7 step 2: "*A child that is waiting is not
published as a running agent, which is a construction the remote provider already proves*" (`92 §4`). Then
it builds two new invisible wait states.

**(a) The claim-ahead buffer.** §3.3.1: "a node that *can* reach it **claims ahead** (a small local buffer of
claimed jobs, bounded by its own slots) so the store's latency is amortised across several starts instead
of paid per start." A job sitting in that buffer has been *claimed*: the queue reports it as taken, the
fleet strip reports no waiting work, and the node reports `draining` — while the job is not running. This
is D's own headline risk in a sharper form than the one D states. D's answer to the quiet queue is the
`stalled` state, and `stalled` is defined as "has slots and has **not claimed**" (§3.3.2) — a node with
slots that claims and does not start is, by the design's own definition, healthy.

**(b) The gang reservation.** §3.3.3: "A 6-child fleet must reserve **6 slots at once, or none**". The
design names the throughput risk in `ASSUMPTION A14` ("the risk is a 6-slot reservation idling 5 slots
while a fifth child spins up") but not the *visibility* risk: five slots held by a reservation are not
`stalled`, not `full`, and not queued — they are reserved. On a four-node fleet whose largest node has 8
slots (A §2.8), a waiting gang silently removes over half of the biggest node from the pool.

**(c) A local child is invisible, unleaded, and dies with its engine.** §3.3.2's `turnsInFlight` is "what
**THIS worker** has admitted"; §3.3.7 step 1 starts local children through the engine; §3.8 SPOF 3 says the
*worker* survives the engine ("a `--profile headless` child is a separate process that needs no engine")
and that "sessions are node-local and survive on disk; the supervisor restarts the engine". None of that
covers an **in-engine child**: A §1.1 records that a session is not a process and "a subagent is not a
process — `NM\dsh-subagent-spawn-in-process\lib\index.js:5-9` … runs each child as a fresh child Agent on
the same cordis context". It has no queue entry (1.3a), no lease (`§3.3.7` gives leases to queue claims),
and no `<DSH_HOME>/mesh/placements/` row (A §1.6). G1's falsifier is "a job that is neither running, nor
queued-with-a-position, nor reported failed" — a local child killed by its engine is exactly that, and
D §3.2 item 5's "a job that dies mid-turn is re-claimable rather than lost" is written about the **queue's**
leases.

### 1.5 A single point of failure nobody named

D's §3.8 names nine and marks three **NEW**. Two mattering omissions:

**(a) The guard row's import, which has already fired once.** A §1.12 item 7: "*The spend guard's import
path.* A one-segment path mistake in this row took down the entire engine. The guard is a **load-bearing
single point of failure for the whole harness**, not a bolted-on guard" (`onInternalError: closed`, A §1.9).
D §3.8's table lists "the spend ledger" as SPOF 7 with the designed behaviour "work continues under each
node's local allowance" — it guards the *number*, not the *module*. D §5 M3 then mounts `guard.mjs` in the
profile, and §3.4 item 1 requires enforcement "at the step seam, in the engine", making this module
load-bearing in **every** engine on **every** node rather than on one machine as today. The measured
consequence of a failure in it is a machine that will not boot for eleven hours (`README.md:102-103`:
"*Here it stayed armed for eleven hours and detonated on an unrelated reboot*"), and the cold-boot gate
(M2) catches only the composed-profile case, not a wedged *running* engine.

**(b) Every node's self-report now has no second reader.** The old design's `/mesh/capacity` was read by the
broker; the new design's admission is read by the node itself and consumed by the node itself (§3.3.2),
and §3.3.4 makes a wrong reading cost nothing ("It claims less often and the fleet fills around it. No
penalty, no exclusion"). The measured consequence of a node's published capacity being wrong is D2 itself.
There is no component in the new architecture whose job is to disbelieve a node.

### 1.6 A policy enforced where a tool is named, not where the resource is owned

This is D9, and D's answer is the most valuable structural repair in the document: the gate moves from
tool names to "the **service**… installed as a wrapper in the **preset layer**", and it is right that
"a tool name is chosen by a **model**, and a model that is telling itself the work is urgent will choose
the local path" (§3.3.7). `109 §6.1` already specified it, and `109 §7` records it as "not implemented".
Four gaps.

**(a) The seam is a preset-layer **row**, so it is enforced per composition — and §3.6 multiplies
compositions.** §3.6 item 0: "the default execution unit is a fresh process carrying the desired
composition"; item 1's **P** class is "anything a *fresh process* composes: the `mesh` profile's tree, the
headless worker's row set". A wrapper that lives in one preset's composition does not exist in another's.
D never states that the wrapper is mandatory in **every** composition that grants `subagent_local` or
`subagent_fork`, and A §1.6 records that the provider itself cannot be a preset row (`ctx.subagents` is
process-wide; `registerProvider` throws `DUPLICATE_PROVIDER`), so the registration and the gate live on
different planes. The claim "**it cannot be bypassed by naming a different tool**" is true; "it cannot be
bypassed by *composing differently*" is unstated and false as written.

**(b) A shell is a different tool.** The engine hands the model `pwsh`. `ssh secratary-ts …`, `dshw up`,
`node …/bin.js web`, or a `dsh --profile mesh headless` one-liner all start work on another machine, or on
this one, without touching `ctx.subagents`. D's own D9 sentence applies unchanged to this path, and the
record has the precedent: the `PersonalSecretary-*` and `dsh-harvest-*` scheduled tasks (A §1.8) start
work outside every provider.

**(c) The owner's own window is an undeclared writer.** §3.3.6 promotes "partition by file" to a declared
exclusive-resource claim enforced by the queue. The tree the owner is looking at is edited by *him* and by
**`PersonalSecretary-HarnessSync` every 15 minutes**, which A §1.8/§1.12 #9 records as "the one that moves
repo state under running agents and is not in the DSH task set, so a DSH-only audit will not see it". A
queue-level lock cannot see either writer, and the measured cost of two undeclared writers on one tree is
already in the record (`95 §6.3`: two machines committed the same change three seconds apart and the result
could not `git pull --ff-only`).

**(d) The residual case is answered with discipline rather than with a resource.** §3.3.7's last sentence:
"The one case it does not fix is a model that works the task itself instead of delegating it — no provider
seam can see that, and the answer there is **cost and context discipline (§3.4)**, not routing." That is
honest, and it is the same shape as the defect: a policy enforced nowhere, with a document as the
mechanism. It is also the larger half of `109 §1`'s measured sentence ("chose `subagent_local` **(or worked
itself)**").

### 1.7 A corrected fact that never reaches the copies that act on it

V8 and M0.5 are the right shape — "A document is not a delivery mechanism; **a keeper is**… something that
runs on the clock, compares against the canonical value, and exits non-zero" — and D extends it beyond the
five skill copies to a registry every consumer derives from. Three problems, all measured in the record.

**(a) The keeper has no declared reader class.** V2 exists precisely because "*a profile check is only
evidence for the class that ran it*" and the same bytes gave `exit=1 lines=16` to an ssh-spawned reader and
`exit=0 lines=620` to a local Interactive one (A §3.7 row 7, `106 §8`). D applies V2 to the cold-boot gate
(§3.6 item 3, M2) and **not** to M0.5's keeper, whose acceptance gate is "the keeper **demonstrably reds**
when a constant is hand-edited in a deployed copy". On which machine, read by which logon class, for which
of the deployed copies (A §1.12 item 2: a junction "is untraversable to any remote-logon reader while a
`BUILTIN\Administrators` one is — **the same profile reads differently to different readers in the same
minute**")? Unstated, and the class is the whole defect.

**(b) A keeper that can red falsely is a keeper that gets ignored — measured.** A §3.13: `install-client-
plugins.ps1 -Check` "two consecutive runs minutes apart disagreed — the first reported five packages
`LINK-ELSEWHERE / NEEDS FIX`, the second reported all six `LINK … ok`. … **a keeper that can report a false
RED is a keeper that gets ignored**". M0.5 introduces a keeper whose *signal* is a non-zero exit — into a
scheduled-task ecosystem where non-zero is already normal background (A §1.8: `DSH Metrics Sampler Watchdog`
`LastTaskResult 2147946720`, running out of a temp snapshot; `DSH Mesh 0700 Restart` result 1;
`DSH Window Fleet Watchdog` disabled; one task pointing at a temp file that may not exist). The design does
not say how a *correct* red is distinguished from that noise.

**(c) V8's anchor is a mutable name, against the rule stated four paragraphs earlier.** §5 M0.5: "one
machine-readable registry (value, **the document that measured it**, and the date)". A §4.4 measured the
problem: `docs/mesh/` holds 54 files and `journal/docs/mesh/` holds 53, 52 byte-identical, and
**`84-calibration.md` — the constants registry's own primary source — differs by 85 bytes** between the two
copies, with all 53 twins sharing one mtime. D §3.2 item 3 and §3.6 item 5 both quote `108 §5.3`'s rule
("prefer an **immutable identifier** — a commit hash, a blob id, a sha256 — over a mutable name") and apply
it to the release directory; V8's registry, whose entire job is to keep a fact alive, records a **path**.

---

## 2. The thesis, falsified

D §3: "*capacity is local and pulled; money is global and granted; state stays where it is and is indexed
everywhere.*" Both halves take damage, and the third clause is answered in §3 below.

### 2.1 "Capacity is local and pulled" — the gate is local, undefined, and owned twice

**The admission formula has four inputs, and D fixes none of them.**

```
commitHeadroomMiB = commitLimitBytes - committedBytes          # the counter 84 §4.4 names
availableMiB      = min(freePhysicalMiB, commitHeadroomMiB - reserveMiB)
memSlots          = floor(availableMiB / 403)
cpuSlots          = floor(logicalCpus × 0.42 / CPU_PER_TURN)
turnsInFlight     = what THIS worker has admitted and not yet settled
slots             = max(0, min(memSlots, cpuSlots) - turnsInFlight - ownerReserve)
```

*(§3.3.2, verbatim.)*

1. **`reserveMiB` is never given a value, and A §4.2 B5 is the row that documents the two live ones:**
   3,885 MiB (`scoring.js:70`) versus `max(2048, 12 % of physical)` = **7,821 MiB on the desktop** — "One
   named constant, 2× different, on the same machine, and a document attributing a formula to a source that
   does not contain it" (`84 §4.4` does not state that formula). On the desktop the difference is ~3,936 MiB
   ≈ **~10 slots**. A §4.2's heading is explicit that these disagreements "are the ones the redesign must
   resolve"; D does not resolve this one, it deletes the *field* and re-uses the *term*.
2. **`CPU_PER_TURN` is two measured values and D never chooses.** §3.3.2's prose lists both ("CPU_PER_TURN
   1.68 tool-heavy, 0.62 resident"). On the laptop (22 logical, A §2.13) the formula yields **5** with 1.68
   and **14** with 0.62 — a 2.7× range, on the one machine the design says was "over the stop line before
   one was dispatched" (G2, `84 §1.1`). And the value is not merely unstated: A §2.8 records it being set
   operationally today by an environment variable (`MESH_HTTP_CPU_PER_TURN=0.62` → `zabz-tech` 8 → 12), so
   the two values are both in production use in the same codebase.
3. **`0.42` does not reproduce, and arithmetically it is not an independent constant.** D cites it as "0.42
   = largest measured occupancy (`84 §4.1`)". **`84 §4.1` states no occupancy fraction at all** (its CPU
   content is the loop-lag tail). The value lives at `84 §2.1` / `§4.4` / `§5.2` — the level-mean **41.50 %**
   of 32 logical CPUs at the 8-tool-heavy-turn level; that same table's largest **single sample is 62.9 %**,
   which `93 §2.1`'s constants table attributes to "`84 §4.1/§4.3`" — a citation whose `§4.1` half does not resolve. Arithmetic
   from A §2.1's own numbers: 8 turns × 1.679 logical CPUs/turn ÷ 32 logical = **0.4198**. So `0.42` and
   `1.679` are **the same single measurement divided by itself**, and the CPU term reduces to:

   ```
   cpuSlots = floor(logicalCpus × (8 × 1.679 / 32) / 1.679) = floor(logicalCpus / 4)
   ```

   *(my arithmetic, from A §2.1's measured per-turn figures and `84`'s own level table — not a new
   measurement.)* On the desktop that is 8 — the calibration point, **reproduced by construction**, the same
   "unfalsifiable as written" property D §4.3 deletes `0.75 × physical` for (A §2.2). On the laptop it is
   5.5 → 5. **The deleted term and the replacement differ in unit, not in kind**, and `84` §6 item 6 (cited
   elsewhere as `§6.6`) states the
   unit conversion "under SMT … is not measured here and the two are conflated in the constant". D §3.3.2
   says "Everything stays in the unit that was measured" — but the 8/32 ratio *is* the physical/logical
   conversion, hidden inside two constants that cancel.
4. **`ownerReserve` is unvalued** — and D §6.3 makes it the basis of a decided default ("should the laptop
   ever take remote work?" → "only in its reserve-free band"). A default whose parameter has no value is
   not a decision.

**And the gate is owned by two components on one machine.** §3.3.2: "`turnsInFlight` is a count the worker
owns… **the only component that can count turns for certain is the one that admits them**". §3.3.7 step 1
admits local children **in the engine**, through the provider wrapper. §3.8 SPOF 3 says the node worker is
"a supervised process, not a session" and survives the engine. So on one machine there are two admitters,
each with its own private count, and neither can see the other — while the design deletes
`governor.budgetSlots` (§4.3) and keeps the governor's lease protocol (§4.1) without wiring it to the
formula. The measured proof that this class of invisibility is real and load-bearing: with 8 real children
consuming 3.0 GiB and 41.5 % of all logical CPUs, the resident engine reported `agentLoopsRunning: 0` **in
every one of the 83 samples**, and `governor.inUse` was **0 throughout** (`84 §5.2`, A §3.2). D's answer is
that the admitters now count; D's new defect is that there are two of them.

**Consequences, and they are the three the design claims to cure.** D1: a node can be blind to load again,
because the load counted is the load this component admitted. D2: the work the owner's own windows are
doing locally is never offered, so the queue is quiet by design (§1.3a). D5: no demotion branch exists —
but with a claim-ahead buffer (§3.3.1) and no penalty for not claiming (§3.3.4), a fast worker can hold a
buffer of every job while a slow one polls and finds nothing, which produces the same measured outcome
("the owner's own machine received **zero** children in an eight-child wave", D §2 D5) by a different
route — and this time nothing looks wrong on any surface.

### 2.2 "Money is global and granted" — the design implements a report and a local guess

D §3.4: "**Money is the only truly global resource in this fleet.** … So the design splits cleanly:
**capacity is local and pulled; money is global and granted.**" Nowhere does §3.4 describe a **grant** —
a protocol by which a spender obtains an allocation from the authority. What it describes is: a local
counter read at the pre-step seam (item 1), "a fleet-wide ledger on the authority" (item 2), a display
(item 3), a placement input (item 4), envelopes and a concurrency cap (item 5), reservation by request
(item 6), and a local refusal at the ceiling (item 7). Every one of those is *reporting* plus a *local*
decision against a number the design itself says is wrong:

* §3.4, under the heading "**The weakness I am not allowed to paper over**": the local ledger is "a **lower
  bound**… so fleet-wide money should be treated as *'×1.3–2.0 low'*. A budget enforced on a lower bound is
  a budget that can be breached by 2× while reporting green — which is the *exact* failure class in G4."
* §3.8 SPOF 7 chooses to keep spending when the authority is unreachable: "**deliberate choice, stated as a
  trade:** work continues under each node's local allowance, with a loud line saying the fleet total is
  unknown. We prefer a **bounded** overspend to a stalled night".

**The last-dollar race is decided locally, twice.** With the ceiling enforced at each node's own step seam
against a per-node counter, two nodes each holding $10 of headroom under a $150 ceiling will each spend to
their own limit; the "fleet-wide ledger on the authority" is not in the decision path (it cannot be — SPOF 7
says the decision survives it being gone). The bound D claims is real but is not the bound D's headline
claims: the concurrency cap is *per machine* (item 5: "**12 generating agents per machine**"), so four
machines may run 48 generating agents against a fleet total nobody is holding. **Nothing in §3.4 grants
anything.** The one thing that *is* granted and refused is the *local* step seam, which is a per-machine
allowance — the same architecture as today's per-host guard, whose blind spot A §2.9 already measured:
"On 2026-09-15, **56.5 % of the day came from ZABZ-TECH** and this machine's logs saw none of it. Until the
layer-2 roll-up posts per-host totals into the authority … **the fleet has no ceiling; each host has one.**"
D's §3.4 item 2 moves the ledger to the authority; it does not move the *decision*.

**Also unmeasured, and the design says so:** the enforcement path has never fired (A §5 item 19: "Whether
the spend guard has ever actually refused anything live — `101 §10`: no live cap refusal demonstrated; the
ledger shows `lastVerdict: "ok"`"), and the exact bill needs a console export only the owner can produce
(D §6.3). Two of the three numbers the grant would need (misses captured, hits captured) are measured at
50 % / 76 % — i.e. the *inputs* to any grant are known to miss between a quarter and half of the requests
(A §4.2 B12 quoting `60 §1.4`).

**What would settle it:** A5, plus a two-node experiment the design does not propose — two machines
spending simultaneously against the authority, at 90 % of the ceiling, and a reading of whether both stop
before $150 or each stops at its own $150. Until that runs, "granted" is a claim about a mechanism that
does not appear in the document.

### 2.3 Is local-first safe at 403 MiB / 0.62 logical CPUs with twenty workers on one machine?

Partly. The 403 MiB point estimate against a 270–530 MiB CI (A §2.1) means a node admitting to its own
point estimate is 24 % over at the top of the interval; D §3.3.2 has no safety factor and no margin term,
and §6.3 item 3 concedes nothing above 8 turns has ever been measured. Twenty workers on one machine is
not the risk — one node's admission caps the node. The risk is that the *same* number is used for jobs of
two different shapes: a tool-heavy turn costs 1.68 logical CPUs and a resident one 0.62 (A §2.1), and
§3.3.2's formula needs to know which *before* it admits. D never says which. The consequence is bounded
above by 14 concurrent turns on the machine whose curve was never measured, and D §6.2 item 1 admits the
measurement does not exist ("My admission function inherits that uncertainty on the one machine the owner
sits at"). That is honest; it is also the reason D1's cure cannot be verified on the machine it is for.

### 2.4 What the pull queue cannot execute

**Three of D's own additions require exactly the component §3.3.1 deletes.** §3.3.1: "**the store is a
claim broker, not a decision plane** — it holds positions and leases; it does not rank nodes, and nothing
about a node's suitability is computed there." Against that:

* **§3.3.3 gang admission** — "A 6-child fleet must reserve **6 slots at once, or none**… the reservation
  is **atomic** (one writer, one critical section)". If the store performs it, it must know each node's
  admissible slots, which is "suitability … computed there". If a node's worker performs it, a 6-child gang
  spanning two nodes cannot be reserved atomically by one writer, and a node can only reserve the gang it
  has already claimed a member of — which it cannot claim without reserving. There is no stated third place
  to put it. C §9 item 3 states the prerequisite D inherits and drops: "**every scarce resource must be
  represented as an integer a single writer controls** (slots, in-flight tool calls, API budget)". D's slots
  are represented by *N* writers, one per node, each with its own private count.
* **§3.3.8 item 2 committed-until ranking** — "a claim carries an expected end, so a **scheduler** can say
  *'this node is free in 40 s'*… and **a job that fits sooner goes sooner**". A backfill scheduler is a
  ranker with a queue it reorders. §3.3.1 removed the ranker and §3.3.3's pull model has no reorder point.
* **§3.3.8 item 1 per-job spread** — "**Spread is a property of the job, not of the fleet**… So `spread`
  becomes a field on the job." Under pull, the job does not choose *where*; a worker chooses the job.
  Enforcing spread requires the store to refuse a claim from a node that already holds a sibling — again a
  suitability decision, which §3.3.1 forbids.

**And D's own gate is unsatisfiable by D's own design.** M6's acceptance criterion is "positions in
**arrival order**"; §3.3.8 item 2's is "a job that fits sooner goes sooner"; §3.3.1's claim-ahead buffer
means the number a caller is shown is a queue position, not an execution order. These three cannot all be
true. This is the exact shape D §3.7 row 3 identifies as the program's worst check — "*the contract names a
command that cannot satisfy it*" — written into the new design's own acceptance criteria.

---

## 3. "A session can never move" — a choice, not a fact, and its cost is unpaid

**The mechanism, as it actually reads.** `docs/mesh/20-placement.md` §1.1–§1.2 (read verbatim for this
report): the session write lease is "a **per-session** write lease, held by the kernel, with **deliberately
no expiry**"; on Windows it is "a `Local\` kernel object — **per machine**. Two Windows hosts sharing an SMB
path cannot exclude each other *by construction*, and there is no lock file to fall back to ('Windows has no
lock file at all')"; POSIX uses `flock(2)`, "which an SMB/NFS client may or may not honour — **an unknown
arbiter is not an arbiter**"; and "a *resumed* writer must scavenge a stale lock — which is fine on one host
and impossible to answer across hosts. **Design rule: sessions do not move. Replicas are archives, not live
sessions.**"

That is a real and well-argued constraint **about one primitive**. It is not a proof of impossibility, and
three pieces of the record say so.

1. **B — the document D cites as its authority — calls it open.** B §A7: "*The constraint is settled as a
   fact about the current loader; it is **OPEN as a design principle** and was never tested as one.* … If
   'sessions are node-local' is a consequence of one-writer-per-home, then with a shared session store and a
   lease, session *placement* becomes an ordinary engineering problem and the whole 'work moves, sessions do
   not' split … is one design choice among several, not a law. That is a much larger redesign than anything
   stream D should assume — and **I am marking it as *available*, not *required***." D §2 states it as "**a
   session is a node-local object**" and §3.1 option 1 says it is "Refused by construction".
2. **The design itself builds the missing arbiter, for jobs.** §3.3.1: "**an atomic claim with a TTL** …
   the queue's claims are **durable rows**"; §3.3.3: an atomic multi-slot reservation with a TTL; §3.8 SPOF 1:
   a store on the authority whose failure is survivable. That is a cross-host arbiter of exclusive ownership
   — built by the same document that says exclusive ownership cannot be arbitrated across hosts. The
   difference is not capability; it is that DSH's session writer consults a `Local\` kernel object instead.
   **A design that can add one arbiter can add another; it chooses not to.**
3. **C says the industry's answer is the same choice plus something D does not have.** C §6.6: systems that
   move a live session "do it by *never moving it* — the environment stays where it was created, and the
   **UI reattaches from anywhere**. That is an important and rather deflating finding." D adopts the first
   half and its second half is **blocked on this build** (§3.2 item 4: zero `pushState`/`hash`/`sessionId`
   across 65 client bundles, pathname-only routing, `?token=` 303s to literal `/`), contingent on `A12`.

**The design's recovery procedure needs the arbitration it declares impossible.** §3.2 item 3: recovery onto
node Y requires "(a) node X is *provably* dead — two independent checks, **no engine answering** and **no
live lease holder**". The lease is a `Local\` kernel object with **no lock file on Windows** and no
cross-host visibility by construction. If X answers, it is not provably dead; if X does not answer, the
second check cannot be performed — the two clauses cannot both be true. D refuses to resolve this same
ambiguity everywhere else: §3.3.5, on a queue wait that expires, "*at expiry the code **cannot tell the two
apart*** (busy vs unreachable)", and therefore never dispatches into an unreachable site. Applied
consistently, the same standard forbids every recovery. **The fail-closed procedure as written refuses every
case, or trusts a single network fact it says cannot be trusted.**

**The real cost of the choice, in the design's own currency.** Immobility is why §3.2 adds five stateful
things — a write-maintained catalog, a node column, a recovery procedure, a durable handle, and a
log-as-authority rule — and every one of them is a new place for the stale-view failure class of §1.2, on
top of the session store that already exists. And the user-visible promise it buys — §3.5 item 2's "a session
idle by *both* signals past T is **closed, never deleted**… it is re-openable by handle" — depends on
M7.5's acceptance criterion ("a window is opened **by handle** and lands on *that* session after a reboot"),
which depends on `A12` finding one of two paths, one of which is H-class. **The design's answer to "why is my
laptop holding twelve sessions nobody is using" is contingent on a separate unmeasured question.** That is
the cost, and it is not priced in §5.

---

## 4. The deletion list — what each deletion stops protecting

D §4.3 deletes thirteen things and §7 restates them. I take them in the order they appear, and I mark the
ones where the protection is gone (**unreplaced**), the ones where it is replaced (**fine**), and the ones
where the deletion is not a deletion at all.

| deleted (D §4.3) | what it protected | verdict |
|---|---|---|
| `score = min(memorySlots, coreSlots)` with `0.75 × physical` | an upper bound on concurrency computed from a hardware fact the node cannot misreport, consumed by exactly one component | **unreplaced** — see §2.1: the replacement is arithmetically the same term in another unit, or 2.7× looser, with `reserveMiB` and `ownerReserve` unvalued and two admitters |
| `SWAP_PENALTY_PCT = 90` / `mem.swapUsedPct` | the only published field that could fire **near allocation failure** (410 MiB / 1,174 MiB bands, A §2.2) | **replaced, but the replacement is a subtraction on the consumer side** (§4.1: `committedBytes` is "a subtraction on the consumer side"); and on macOS the memory quantity is a different quantity (D §6.2 item 5), and the Mac is the only node where the memory term binds |
| `accepts.maxChildren`, `governor.budgetSlots` as published measurements | (i) the only per-node statement of **how large a fleet this node can take**, which §3.3.3's gang admission now needs and the new contract does not carry; (ii) the governor's **cross-process** slot protocol (A §1.9: one lease file per slot, `O_CREAT\|O_EXCL`, heartbeat liveness, "never refuses — `QUEUED position N`, exit 10") | **unreplaced** — D keeps the governor's protocol (§4.1) and replaces its count with a per-component private one (§3.3.2), and never states a node's maximum gang size |
| the `fits` / `highest-slots` / `slow` / `unreachable` tiering | a way to exclude an unplaceable node | **fine** — §3.3.5 recovers the only exclusion that mattered ("nothing is ever dispatched into an unreachable site"), and §3.3.2 keeps "measured broken" vs "never measured" as row facts |
| `160 MiB` as a placement constant | nothing — it is 2.5× below the per-turn cost (A §2.2) | **fine** |
| `0.81 GB per generating turn` | nothing | **fine**, except that the keeper that keeps it deleted is the keeper of §1.7 |
| "dispatch anyway" on expiry | nothing good | **fine** — this is the single cleanest deletion in the document |
| the stale roster prose, `-Exclude` as policy, a window identified by a port | nothing structural | **fine** |
| `never refuse`, as a universal | see below | **a deletion of something that was never universal** |
| restart-to-activate as a class; the three-place coupling | the ability to activate a host-plane change at all, supervised and gated | **partly unreplaced** — §3.6 item 4 reinstates a supervisor that boots the previous artefact, and §3.6 item 1 keeps an H class ("the owner's resident engine only"); what is lost is the *idle* gate, and the measured blast radius of a restart on this machine is "**13 of 13 remembered window(s) reopened**" against a dead port, `ERR_CONNECTION_REFUSED` in every window, and 3,760 → 24,200 → 9,764 process churn (incident README). D §3.8 SPOF 3 states the cost in its own words: "its windows 502". The claim that this is acceptable rests on "it is now the *rare, opt-in* class" (§3.6 item 1) — a claim about **frequency**, which is not a protection |

**The `never refuse` scoping deserves its own paragraph, because it is where D's reasoning is weakest.**
D §1.3 rests the deletion on one measurement: "*It has already produced an absurd answer — the broker, given
a 999-child fleet request, answered HTTP 200 with `position 5` and six rationale frames saying the job cannot
run (`95 §2.4`)*". The source's own verdict on that same observation is the opposite: `95 §2.4` ends
"**The never-refuse rule holds under the two hardest cases I could construct**", and B §7 lists it as F4,
one of "the two design decisions in the whole estate that the adversarial audit could not break". D is citing
the evidence *for* the pattern as the reason to delete it, and calling a `200 + position` "absurd" is a taste
judgement about a response shape that the pattern was designed to produce.

Three further facts make the framing wrong:

1. **It was never universal.** The rule's stated force is attached to capacity, placement and admission:
   `71 §2.2` "**The swap half is a ranking change, never a gate** (owner's rule: queue, never amputate)";
   `76 §4` "**It never refuses**"; `dsh-at-scale/90 §3` "**It never refuses.** There is no branch that
   returns 'no'." And the money ceiling already refuses, by design, in `65 §3.3`: "*This is queue, never
   amputate, with a real ceiling: nothing is killed mid-call, nothing is deleted, the session stays
   resumable, and the only thing that stops is **starting new work***", with `65 §4`'s `{kind: 'reject'}` at
   $50. The pattern D deletes as a universal is a pattern the house had already scoped correctly.
2. **The property it protected is the caller's inability to distinguish "no" from "later".** D's own D9
   argument is that a policy with an adversary inside the system fails — and a model that cannot get a
   position has no mechanism to wait, which is the measured behaviour D9 is built on (`94 §1`: a parent told
   to "fan the work out" chose the local tool; `109 §1`: the model "chose `subagent_local` (or worked
   itself)").
3. **A refusal is not a queue entry.** D §3.4 item 7 says a refusal "destroys nothing" because the turn
   closes `blocked` — true of the turn, not of the job. A job refused at a seam exists only in the caller's
   context; it is neither running, nor queued-with-a-position, nor a node state. §1.1 promises the owner
   that "the system says which of the four permitted states it is in instead of going quiet", and §3.3.2
   names exactly four node states; a refused job is a fifth outcome with no name, no position and no owner.

D's own §3.3.7 step 3 then makes this worse in the one case where it matters most: when the queue is
unreachable the design *refuses* — which is precisely when refusing is least safe and when a queue was the
whole point. **Verdict: the deletion is aimed at a strawman, and its one real cost — a job told "no" has no
position and no owner — is not covered anywhere.**

---

## 5. The migration reality on this fleet

The brief names the conditions: two of four machines Windows, a live-reload junction mount, a journal that
has collided four times, a scheduled-task ecosystem, and the owner working on the laptop right now.

**The step most likely to break the machine is M7 (session placement + the fleet strip).** Not because it is
the most ambitious, but because its stated mechanism is wrong in a way that is readable from the source D
cites, and because it is the step that opens his windows.

1. **The design's "available today" claim is not supported by the document it rests on.** §3.1.1: "**window →
   origin → node is a client-side decision, and the component that makes it is the one that already opens the
   windows.** The proxy for slot *n* forwards to the chosen node's engine instead of `127.0.0.1:3099`", and the
   third bullet claims a loopback alias needs "**no** engine config change and **no** engine restart". The
   engine is loopback-only on every node and refuses to be otherwise: `20 §1.3`/§1.4 — "*DSH refuses
   `--host 0.0.0.0` **on purpose** — `dsh-web-app/lib/startup.js:40`: 'it would expose remote code execution to
   the network; use 127.0.0.1 instead' … **The supported door is a reverse proxy that preserves `Host` plus
   `--trusted-host <authority>`***, and the same document's own conclusion is that "a browser that loaded
   `https://zabz-tech.tail93e6e6.ts.net/` opens **that** node's WebSocket." A §1.5 states the deployment:
   "The engine binds loopback only, so 3086 is the only non-loopback door." So reaching another node's engine
   needs **a per-node reverse proxy plus `--trusted-host`, which is read at engine start** (`secratary`'s own
   unit already carries `--trusted-host secratary.tail93e6e6.ts.net`, `20 §1.4`). That is an **H-class,
   per-node, restart-requiring** change — the class §3.6 item 1 exists to avoid — appearing inside a step M7
   classifies as "client-side, so it still needs no idle window and no restart". And loading each node's own
   tailnet URL instead is worse, not better: one origin per node means every window pointed at that node
   shares `localStorage["dsh.sessions.current"]` — the exact defect D §3.2 item 4 exists to fix.
2. **M7's own files are in none of §3.6's four classes, and §3.6 says an unclassified change is refused.**
   §3.6 item 1: "An **unclassified change is refused** by the deployment path." M7 edits
   `multi-window/dshw-proxy.mjs` and `windows.json` — the launcher, not a preset (S), not a profile-composed
   process (P), not a host-plane loader row (H), not settings (D). Its code is read whenever the watchdog
   restarts the process, which happens on a timer with no gate — measured tonight on this machine: a fresh
   proxy listener at `03:25:10Z` that no session started, with the prewarm line silent for ~13 minutes
   (A §1.4). **Either the migration path's own first UI step is illegal under its own rule, or the rule is
   incomplete at exactly the place the 2026-09-17 incident came from (a rebuild that became live with no
   gate).**
3. **Its stated fallback silently lands the window on the wrong session** (§1.3b), and the proxy's single
   cached session list becomes wrong-content the moment two windows point at two nodes (§1.2a).
4. **It is on his screen while he is working.** A §1.3's live state: one origin alive against fourteen
   registry rows marked open; the proxy has already come up as two instances splitting the port range
   (A §1.4); `ensure` runs every minute. The blast radius D itself states is "the one new SPOF that can make
   the owner's *screen* useless while everything else is healthy" (§3.8 SPOF 5).

**The one thing the design assumes that has never been measured.** Not the outcome — D's `A4` names the
outcome ("Session placement to another node is usable when that node has the workspace") — but **the
transport**: whether a remote node's engine will serve a browser whose origin is the *laptop's* loopback
port, i.e. whether the browser-trust fence's `127.0.0.1:<port>` acceptance (MEMORY §90, measured) survives a
request that arrives at a *different machine*, and whether it does so through the node's own gate
(`tailscale serve` → `phone-gate.py` → engine, with a sign-in redirect and a device allow-list) rather than
through a direct engine bind. No document measures it; `93 §3`'s own caller path is "through the gate at
`https://zabz-tech.tail93e6e6.ts.net/mesh/run`"; `95 §1.1`'s capacity reads are
`curl https://<node>.tail93e6e6.ts.net/mesh/capacity`. One `curl` against a second node's engine with a
foreign `Host` settles it, and it decides whether M7 is one config key or a new per-node transport — which
is the difference between an S-class step and the H-class class D says to avoid.

**Two further migration realities the path does not account for.**

* **The keeper's environment is measurably unreliable.** M0.5 and M2 both "run on the clock", into the task
  set A §1.8 measures: a sampler "Running" out of a temp snapshot with `LastTaskResult 2147946720`; a daily
  restart with result 1; a one-shot task pointing at a temp file; a fleet watchdog **Disabled**; and
  `PersonalSecretary-HarnessSync` moving repo state every 15 minutes. M0.5's acceptance gate requires the
  keeper to "**demonstrably red**" and A §3.13 already records the estate's one existing keeper producing a
  false red and being ignored.
* **The isolated-engine acceptance path has never been run under load.** D §3.6 item 0 calls the isolated
  `DSH_HOME` process "the acceptance path for any host-plane change", and it has been used three times
  (B §A12) — but the record's own summary of the evidence is that the engines *coexisted*, not that either
  was loaded: 106 §6 boots "a **second engine on the same machine, on the real home, on a different port
  (3097)**… leaving the listener on 3099 untouched" and reports liveness before/after; no document reports
  two engines *doing agent work at once*, and `84 §7` states "**Two nodes were never loaded at once**". M2's
  gate requires "(d) **one real turn** on the scratch engine" while the owner's engine is live — a model call
  and ~403 MiB on a machine A §1.11 measured at 27,386 MiB of a 44,149 MiB commit limit with 13 agent loops.
  **The design's own acceptance path has never been exercised in the condition the acceptance path is for.**

---

## 6. The numbers

**Method.** For every quantitative claim in D I could identify, I checked whether it appears in A, B or C,
and — where it does not — whether the **primary source D cites** actually contains it. Five delegated
read-only extraction sessions read the primary sources; I re-verified the three highest-risk ones myself
(`84 §1.2`, `71 §0`, `96 §2.3`). The headline verdict first, because it is the answer to the brief's real
question: **D does not repeat the original sin.** Every *measurement* it leans on is traceable, and several
numbers I expected to be inventions are sourced in the primary documents and absent from A/B/C only because
A/B/C did not need them: `12.1 s` (`84 §1.2`: "A real turn, a real tool call, ~12.1 s wall, dominated by
waiting"), `27–45 ms` (`71 §0`: "Laptop↔office is a DIRECT path, 27–45 ms | `tailscale ping`"), and the
`42×` cold/warm ratio (`96 §2.3`). The unsourced material is all in the **new machinery's parameters**.

### 6.1 Numbers D uses with a different value or status than A/B/C gives

| D's claim | what A/B/C says | significance |
|---|---|---|
| §3.5: "The 25.4 s → 29 ms improvement is **real and measured** (`§2`) and should ship as a stopgap" | A §0.2: "A first-party reading of the *warm* session-list path is **not available**"; A §2.5 marks the figure **[DUP]** and **NOT VERIFIED**, and reports the live proxy's own refresh times as **3.5 s to 20 s** with the prewarm path failing for ~13 minutes | **the 0.81 GB shape exactly**: a number A refused is asserted as settled. This one matters because it is the evidence for keeping the cache the design calls "the only remedy that leaves the pathology in place" |
| §3.4 item 8 (twice): "three sessions were **52.5 %** of a $54.92 day" | A §4.2 **B10**: `65 §2.4` measures the same three sessions at **47.6 %** ($5.56 of $11.68), and adds "a single session cannot run away. The largest session ever measured here costs **$2.88**" — and A §4.2's heading names these "the ones the redesign **must resolve**" | D's "per-session envelope is also the context discipline, and on the evidence that is the bigger lever" rests on the disputed half of the figure |
| §3.3.2: `availableMiB = min(freePhysicalMiB, commitHeadroomMiB - reserveMiB)` | A §4.2 **B5**: the reserve is **3,885 MiB** in `scoring.js:70` and **7,821 MiB** on the desktop under `max(2048, 12 %)`; `scoring.js:136`'s own comment admits the frozen value under-reserves by 3,936 MiB; and the formula is attributed to a `84 §4.4` that does not contain it | an unvalued term that changes the desktop's admission by **~10 slots** |
| §3.3.2: `cpuSlots = floor(logicalCpus × 0.42 / CPU_PER_TURN)` | A §2.1: `CPU_PER_TURN` is **1.68** tool-heavy *or* **0.62** resident; A §2.8 records `MESH_HTTP_CPU_PER_TURN=0.62` changing `zabz-tech`'s limit 8 → 12 in production. And **`84 §4.1` contains no occupancy fraction at all** — the 41.5 % lives at `84 §2.1/§4.4/§5.2`, whose same table's maximum single sample is **62.9 %** | two unresolved values spanning 2.7× on the laptop, and a citation that does not resolve |
| §3.7 V8 / §3.2 item 1: the journal index is "over **~2,000 entries**" | A §1.7 `[LIVE]`: **1,795** entry files; A §4.1 A13 lists 1,400 / 1,616 / 1,728 / 1,795 | minor, but it is the count inside the rule about numbers being right |
| §3.3.3: "a 12-child fleet cannot be honoured by per-child placements (`C §10.2`)" | C §10.2's own citation is `76-broker.md §10.x` — **a placeholder section number**, and C never says what the 12 is | the sole citation behind a design decision traces to a placeholder |
| §3.3.1 / §3.4: "a capacity read was measured at **7,342 ms** (`C §10.2`)" | C cites `76-broker.md §10.5`; **no document states origin, destination, or who measured it**, and D already has a first-party number for the same link (`4.42 s`, `95 §1.1`) | second-hand with no endpoints, used to justify inverting the architecture |
| §3.8 SPOF 3: "measured: *'`accepts.oneShot` is still true (a headless run needs no engine)'*" | `71 §0` is a **published contract field** being read (`"accepts": {"oneShot": true, …}`) with the interpretation in parentheses | D's own D1/D3 defect — a published field consumed as a measurement — inside D's own SPOF table |

### 6.2 Numbers that appear in D but in none of A, B or C — and their status

All three are **sourced to the primary documents** (verified verbatim for this report), so they are not
inventions; they are listed because the brief asks, and because two of them are load-bearing in arguments
where A/B/C never corroborated them: **`~12.1 s`** per turn (§3.1 table, §3.3.8 item 2 — `84 §1.2`);
**`27–45 ms`** laptop↔office (§3.1.1 — `71 §0`); **the `42×` cold/warm ratio** (§3.4 item 8 — `96 §2.3`).

### 6.3 Fresh unsourced constants, i.e. parameters of the new machinery

These are the ones I would hold D to, because they are new, they are not measurements, and they change
decisions: **`reserveMiB`** (§3.3.2, two live values, ~10 slots on the desktop); **`CPU_PER_TURN`**
(§3.3.2, two live values, 2.7× on the laptop); **`ownerReserve`** (§3.3.2, no value anywhere, and the basis
of a decided default in §6.3); **`T`** in three places (§3.3.2 `stalled`, §3.5 item 2 cull, §3.6 item 4
"healthy **N** times"); and the **gang size** — §3.3.3 reserves "6" for "a 6-child fleet" while the contract
that used to publish a per-node maximum (`accepts.maxChildren`) is deleted.

**One number D cites correctly and that I want on the record, because it is the one that should have been a
constraint and became an argument:** the laptop's own turn-cost curve does not exist. `84 §6.1` records
"**ZABZ-YOGA's own curve — the one the constants were written for**" as blocked, and §1.1 records the
machine "above that stop line **before any fleet was dispatched**". D §6.2 item 1 admits inheriting it. So
the admission function that cures D1 has never been validated on the machine D2 is about, and §3.3.2's CPU
term predicts **more** concurrency there than the constant D deletes (5–14 vs the deleted `0.75 × 16 = 12`).

---

## 7. Finish

### The three objections most likely to kill or badly damage this design

**1. Admission is the only gate, and D does not define it — and there are two of them per machine.**
§3.3.2's formula is the whole cure for D1, D2 and D5, and it has four inputs of which **`reserveMiB` has two
live values ~10 desktop slots apart, `CPU_PER_TURN` has two live values 2.7× apart on the laptop,
`ownerReserve` has no value, and `0.42` is the same single measurement as `1.679` divided by itself (so the
CPU term reduces to `logicalCpus / 4` with one constant and `logicalCpus × 0.677` with the other — the term
D deletes, in another unit, or 2.7× looser)**. Compounding it, `turnsInFlight` is "what **THIS worker** has
admitted" (§3.3.2) while §3.3.7 step 1 admits local children **in the engine**, and §3.8 SPOF 3 makes those
two different processes on one node — so the load that is counted is the load a component admitted, which is
D1's definition with a smaller denominator. `84 §5.2`'s 83 samples are the measured proof that this class of
blindness is real and silent.
*What settles it:* run `93 §5.1`'s rig on the laptop with **both** admitters live — N=8 in-session
`subagent_local` children **and** a node worker holding 4 claimed jobs — and compare the sum of the two
private counters against the OS process count and `\Memory\Committed Bytes`, while reading the fleet strip.
The method is already proven (the node's own counter and the OS list agreed at 8 of 8, `93 §5.1`); the
prediction D1 makes is that they will not agree here. Until `reserveMiB`, `CPU_PER_TURN` and `ownerReserve`
have values, no such run can even be specified.

**2. The wallet is not granted; it is reported, and enforced locally against a number the design says can be
2× wrong.** §3's headline says "money is global and **granted**"; §3.4 describes no grant protocol, and its
own "weakness I am not allowed to paper over" says a ceiling enforced on this ledger "can be breached by 2×
while reporting green — the *exact* failure class in G4". §3.8 SPOF 7 then chooses to keep spending when the
authority is unreachable, and §3.4 item 5's fleet-wide envelope is a **per-machine** concurrency cap of 12 —
so a fleet can run 48 generating agents while nobody holds a fleet total. The measured antecedent is A §2.9:
the guard already "counts this host only", and on 2026-09-15 "**56.5 % of the day came from ZABZ-TECH** and
this machine's logs saw none of it. Until the layer-2 roll-up posts per-host totals into the authority …
**the fleet has no ceiling; each host has one.**"
*What settles it:* two machines spending simultaneously at 90 % of the ceiling and a reading of whether both
stop before the ceiling (A5 gives the reconciliation half; this gives the race half). The design's own gate
("a synthetic step at the ceiling closes the turn `blocked` and spends nothing", M3) is a single-machine
test and cannot detect the race.

**3. The pulled queue cannot execute three of the design's own mechanisms, and its own acceptance gate is
unsatisfiable.** §3.3.1 deletes the decision plane ("the store is a claim broker, not a decision plane…
nothing about a node's suitability is computed there") and then specifies gang admission (§3.3.3: an atomic
6-slot reservation with no stated single writer), committed-until backfill ranking (§3.3.8 item 2: "a job
that fits sooner goes sooner"), and per-job spread (§3.3.8 item 1: "spread becomes a field on the job"),
each of which needs precisely a ranker that can refuse a claim. C §9 item 3 — the mechanism D adopts — states
the prerequisite D drops: "**every scarce resource must be represented as an integer a single writer
controls**". M6's gate ("positions in **arrival order**") and §3.3.8 item 2 cannot both pass.
*What settles it:* take M6's own rig and offer, at the same time, a 6-child gang and four single jobs to a
fleet with 7 free slots split 4+3, while one node holds a claim-ahead buffer of its own slot count. Record
whether the gang ever starts whole, whether any single job passes a gang, and whether the position shown to
each caller matches when it ran. This is one run on the existing `93 §2.1` rig and it decides whether gang
admission is a feature or a paragraph.

*Ranked fourth, and it is the one with the measured blast radius on his screen:* **M7's mechanism is not the
one the record documents** — session placement needs a per-node Host-preserving reverse proxy plus
`--trusted-host`, read at engine start (`20 §1.3`/§1.4; engine loopback-only per A §1.5), and its files are
unclassifiable under §3.6's own table, which says an unclassified change is refused. Settled by one `curl`
against a second node's engine carrying a foreign `Host`. It is fourth only because it damages the UI rather
than the guarantees — and it is the step that opens his windows.

### The one thing in the design I could not fault

**The cold-boot gate (§3.6 item 3), specifically its refusal to accept any evidence except a boot in the
condition that broke the machine.** Four parts, all of which must pass: a scratch `DSH_HOME` on a scratch
port; **`DSH_HOME` unset**, "which is the incident's exact failing condition and *'the normal path, not an
edge case'*"; `--dump-config` → exit 0, then boot, then `GET /healthz` → 200; and **one real turn** on the
scratch engine — run once per reader class. I attacked it three ways and it held: the failing condition is
not approximated but instantiated (`Remove-Item Env:DSH_HOME` is Appendix B of the incident, and
`diagnosis-report.md` states "*That means the unset path is the **normal** path, not an edge case. The normal
path was the broken one*"); the reader-class requirement is itself a measured finding rather than a
principle (the same bytes, same minute, `exit=1 lines=16` to an ssh-spawned reader and `exit=0 lines=620` to
a local Interactive one, `106 §8`); and the negative direction is specified in advance and is deterministic
(App. B prints `FAILED: MODULE_NOT_FOUND` or `LOADED`), which is V4 satisfied by construction rather than by
assertion. It is also the only check in the document whose failure mode has already happened to this fleet
and cost eleven hours, and the engineering it depends on — an isolated engine on a scratch home and port —
is a path this estate has actually exercised, with the owner's engine verified alive before and after
(`90 §2.1`, `92 §7`, `105 §6.1`, `106 §6`). I could not improve it, and I could not break it.

**What I did not do.** I measured nothing, ran no fleet, started or stopped nothing, killed nothing, and
changed no git state. My only original numeric result is the cancellation of `0.42` against `1.679` in
§2.1, which is arithmetic on A §2.1's measured per-turn figures and `84`'s own level table, labelled as
arithmetic. Where the record is silent I have said so rather than filling it: the catalog's writer is
unstated, the transport for cross-node placement is unmeasured, and the recovery procedure's second death
test is not performable as written.
