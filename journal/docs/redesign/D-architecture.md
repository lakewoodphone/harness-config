# D — Architecture: the harness redesigned from first principles

**Stream D of the redesign. Owns exactly one file: this one.** No code, no config, no other document was
written, and nothing on any machine was started, stopped, restarted or reconfigured to write it.
**Date:** 2026-09-18. **Author:** a delegated session (stream D), not the owner.
**Mandate (verbatim):** *"take a step back and audit and redesign this from the beginning with full
analysis research and more. this time with all the context mistakes and things you learned along the way
so you start from a more knowledgeable place, but don't get stuck in your old ways of thinking start from
scratch."*

**Provenance convention, and it is load-bearing.** Every factual claim below carries the document it came
from. **MEASURED** means a named document took it live with a command; the date is the document's.
**READ** means it was read out of source or configuration. **ASSUMPTION** means *I* added it, and every
assumption is paired with the measurement that would test it (§6.1). **REFUSAL** means asked for and not
obtained. I measured nothing myself — this is a design document written from the record, and where the
record contains a gap I say so rather than filling it.

**Cross-stream input, and what it changed.** Two of my sibling streams reached me mid-write and both changed
the design rather than decorating it.

*Stream B's assumption autopsy* (`B-assumptions.md`) supplied: the enforcement-layer hole, which becomes §2
**D9** and §3.3.7 (solving it, not restating it); the finding that restart-to-activate is *the loader's
accident promoted to policy* rather than a design, which rewrites §3.6 around the two escapes B verified;
and the propagation failure that keeps a refuted constant alive in five deployed copies, which becomes §2
**D10** and rule **V8**. **One of B's findings is also stale and I have not designed around it:** the
`slow`-node demotion it measured was reported fixed tonight — the pool now includes every node that can take
work and `slow` is a ranking, with a test that fails when the defect is restored. The *architectural* point
survives and is answered in §2 D5 and §3.3.1: **the branch is removed, not corrected**, and a property that
important must be *watched*, not merely implemented.

*Stream C's research* (`C-research.md`) supplied the framing — the launcher plus its origin proxy **is a
hand-rolled, less capable JupyterHub**, and the two things this harness is still blocked on are exactly the
two JupyterHub solved: **per-session addressability** and **a lifecycle policy**. Those become §2 **D11**,
§3.2 item 4, §3.5 and §3.3.8. C also inverted two of my assumptions with published prior art — Ray's
**local-first** scheduling and Nomad's **per-job spread** override — and both are now in the design with the
reasoning stated (§3.3.1, §3.3.8), plus the one in-house pattern C says I should extend rather than
reinvent (§3.2 item 1: `journal/index/`). §3.10 records what I took from the wider field and what does not
transfer.

---

## 0. What this document is, and the one thing it is not

It is an architecture: the units, the state model, the admission model, the money model, the UI, the
change model, the verification model, the failure model, and a migration path with each step reversible.
It is **not** an implementation and it changes nothing.

It is written against a specific, uncomfortable starting point: **two days of engineering produced a mesh
that an independent auditor found six defects in on the day it was declared finished**
(`95-audit-live-mesh.md` §0), and the single most important line in that audit is that the program's own
definition of done **cannot be produced by the program's own command** — `mesh-e2e.ps1 -Strict` exits 2
with three steps SKIPped, every time, on any mesh, forever (§5.3, §0 item 12). A redesign that starts from
"what did we build" inherits that. This one starts from "what is it for".

---

## 1. What the system is for

### 1.1 The real goal, in one paragraph

The fleet exists so that **one person — the owner of a phone-repair shop who is also building an
autonomous company — can have many agents working at the same time, started from the machine he is
sitting at, without that machine becoming unusable, without spending money he did not decide to spend,
and without losing a single byte of work, memory or customer data.** The scarce resources are his
attention and his concentration, not his hardware: he works the shop 12:30–5, comes back to the machine
late, and opens many windows with agents in them. What he is buying with this system is *parallel
thinking that does not cost him the machine he thinks on*. Concretely, from any window he should be able
to hand over a job and know three things without asking anybody: **where it is running, that it will not
slow his screen down, and what it will cost** — and if a window, an engine, a machine or the network
between the two sites dies, the work and the record survive it, and the system says which of the four
permitted states it is in instead of going quiet.

### 1.2 The four guarantees, stated so they can be falsified

| # | guarantee | what falsifies it |
|---|---|---|
| **G1** | Work gets done: a job is never lost, never silently dropped, and never runs somewhere it cannot be observed | a job that is neither running, nor queued-with-a-position, nor reported failed — `93 §3` records the shape: a run is **not** cancelled when the client disconnects, and the default 780 s queue budget against a dispatcher's 900 s POST budget is chosen so the node answers first |
| **G2** | The machine the owner is using stays usable | measured first symptom under load is the engine's own loop-lag **maximum**, 18 ms → 54 ms at 8 tool-heavy turns with the median unmoved (`84 §4.1`) — and on the laptop a fleet has never been run at all, because it was over the stop line before one was dispatched (`84 §1.1`, §6.1) |
| **G3** | Money does not run away | 55 agents generating continuously ≈ **$68/hour off-peak, $136 peak**; one hour is **1.24×** the worst day he has ever had ($54.92); the $50 tripwire is **44 minutes** into that plan; and nothing enforces anything today — no guard row, no budget key in the harness, no counter on screen (`96 §0`, §4.1–§4.3) |
| **G4** | Nothing is lost, and nothing is confidently wrong | 203 company tables and customer data on the same fleet; two recorded data losses; seven-plus checks shown to pass while the thing they checked was broken (§3.7) |

G4 is deliberately two things. The money failure mode in this system has never been theft — it has been a
**confident wrong number** (`96 §4.3`: the local ledger is a *lower bound* that can undercount the bill by
1.3–2.0×), and the time failure mode has never been a crash — it has been a **green check over a broken
thing**.

### 1.3 The one rule I keep from the last two days, and the one I throw out

**Keep:** *queue, never amputate* — for **capacity**. It is the owner's own rule and it is right: the
alternative to a queue is a refusal, and a refusal on capacity is a lie about a resource that is merely
busy (`71 §2.2`, `dsh-at-scale/PROGRAM.md` §"the rule that governs every change").

**Throw out:** *never refuse* as a **universal**. It has already produced an absurd answer — the broker,
given a 999-child fleet request, answered HTTP 200 with `position 5` and six rationale frames saying the
job cannot run (`95 §2.4`) — and it has no answer at all for the two resources that are *not* elastic:
**the wallet** (`96`) and **an unreachable site** (§3.3.5). Capacity queues; money refuses at a seam that
destroys nothing; a partition queues.

**And keep two patterns because they are the only two structural decisions in this whole estate that an
adversarial audit could not break** — `B-assumptions.md` §7, F4 and F5, both *"structural (never-refuse,
and print the arithmetic) rather than numeric"*: **never refuse**, scoped to capacity, and **print the
arithmetic**. §3.3.1 and §3.4 generalise them — every decision prints its own numbers, including every
refusal, and the never-refuse rule is attached to the resource it is true of.

---

## 2. The eleven defects the redesign has to cure

Each is a measured fact about what exists today, not an opinion about style. This is the "start from a
more knowledgeable place" section: these are the mistakes the redesign is required not to repeat. **D5 is
the one defect in this list that was fixed while this document was being written, and it is included
deliberately** — a property that important rested on one boolean, and no check watched the property.

| # | defect | the measurement |
|---|---|---|
| **D1** | **Placement is blind to load.** The score is `min(memorySlots, coreSlots)`, the memory term is pinned at its cap, so placement **is** `floor(physical cores × 0.75)` — a core count. A node running 8 real children scores identically to an idle one. | `84 §5.2`: in all 83 samples with 8 concurrent turns and 41.5 % of a machine's CPUs consumed, `/healthz` reported `agentLoopsRunning: 0`; `95 §5.4`: `agents.loopsRunning` is read into `broker.js:407`, printed at `:698`, and used in `scoring.js` **nowhere**; `95 §7c`: *"route work to the most empty part of the mesh" is, today, "route work to the node with the most physical cores"* |
| **D2** | **Nothing offers the work, and nothing watches the machine.** Zero placements in a window where the laptop was at 126 % of physical memory. | `109 §1`: the laptop advertised **12 free slots** at 124 % of physical committed, and at 22:43 **1 free slot**; *"of the 24 slots the broker offered this laptop across the evening, between 12 and 1 of them had any relation to whether the machine could hold a child."* `95 §0`: the broker's last placement was 04:12:42Z and the newest dispatcher record 00:15 local — **nine hours idle while every process was live**. `109 §1`: the ledger recorded no placement all day. *(The brief I was given says zero placements in 80 minutes; the documents support the stronger claim, and I cite the documents.)* |
| **D3** | **A published field that cannot vary, and a published field nobody consumes.** `accepts.maxChildren` is the literal `12` on all five nodes — it came from a JSON example in a frozen contract — and `governor.budgetSlots` is `24` on all five. | `95 §1.4`: `phone-gate.py:939 MESH_MAX_CHILDREN = 12`, *"a documentation example became a published per-node limit"*, and the **broker consumes it** (`accepts.maxChildren=12 < 999 child(ren)`); `governor.budgetSlots` is advisory and the gate's own contract says do not consume it |
| **D4** | **The transport owns a ceiling that belongs to the node.** `limit = max(1, min(cpu, mem, declared, hard))` = 8 on the desktop is the best-measured arithmetic in the whole program, and it lives in `plugin-mesh-http` — a component that cannot see the local machine's *other* work, and whose `declared` term is D3's literal. | `93 §2.1` (every constant traced to `84`), `93 §2.2` (8 / 5 / 1 / 3 / 1 across the mesh), `95 §1.4` (`declared` is 12 everywhere because it is a constant) |
| **D5** | **One boolean branch inverted the routing property on the node that mattered, and nothing noticed for hours.** *Reported fixed tonight* by stream B: the pool now includes every node that can take work, `slow` is a ranking rather than a disqualification, and a test fails when the removal is restored. **So the defect is no longer the design's problem — but its shape is, because the shape is a verification failure.** | `92 §5.2`: seven children in, the desktop was down to 11 free slots and the laptop read 12 — *"the eighth child **should** have gone to the laptop. It did not"*; `92 §5.3` reproduces it with six held leases; the laptop's gate alternated `ok`, `slow`, `ok` over three consecutive fresh reads. The live cost: the owner's own machine received **zero** children in an eight-child wave *while it had more free slots than the node that took all eight* — and the gate on that machine is measured at **4.42 s** where every other node answered in 0.27–1.58 s (`95 §1.1`), so under any latency-weighted ranking it will always look worst. **This is why §3.3.1 removes the branch rather than correcting it, and why §3.7 V4 exists.** |
| **D6** | **The money has no ceiling and no visibility.** | `96 §4.3`: no `guard.mjs`, no guard row, no budget key anywhere in the installed harness, no state directory, no scheduled task; `96 §4.2`: the $50 ceiling is **44 minutes** of the described plan and today's ordinary fleet was already at **$12.02 by 13:20Z**; `96 §4.3`: *"the only two ways to know are (a) ask me to run a 15-second scan, or (b) pull the console export by hand"* |
| **D7** | **Activating a change can brick a machine, and the arming is silent.** A rebuild through a live-reload junction wrote a module that resolved its dependencies from the wrong directory when `DSH_HOME` was unset; the engine booted fine for eleven hours on the in-memory tree and then failed its first **cold boot**, exit 1. The launcher retried three times and never showed the answer that was already in the log. | `incidents/2026-09-17-dsh-engine-boot-failure/diagnosis-report.md` §3–§4.3, §7.3, §8.1: *"A live-reload junction makes WIP instantly load-bearing … 'It works' after a rebuild proves nothing until the process restarts"*; and `95 §3.2`: the Mac's **resident engine is running a profile that can no longer be booted** (`--profile web --dump-config` → exit 1) |
| **D8** | **Checks pass while the thing they check is broken.** Seven-plus instances, catalogued in §3.7, including one whose result is a function of the *reader's logon class*. | `95 §5.1–§5.4`, `106 §8`, `87 §4.7`, `108 §10.1–§10.2`, `86` (the smoke script that would have been green while proving nothing), `MEMORY-AND-SESSION-LIST.md §3` (a token check that only ever looked at the token's shape); stream B's independent count is **seven** in two days, plus two more from the incident record (`B §A10`) |
| **D9** | **Enforcement lives where the resource is *requested*, not where it is *owned* — so the load-shedding property is a model's choice, and it fails at exactly the moment it is needed.** Routing is a property of a **tool name** the model has to remember; `subagent_local` and `subagent_fork` are not gated by anything, and the pressure refusal cannot reach them. | `109 §5`, in its own words: *"The refusal is not enforced on `subagent_local` or `subagent_fork` … **This is the single largest remaining hole**"*; `109 §1`: the placement ledger *"recorded no placement all day, because the model in each window chose `subagent_local` (or worked itself)"*; `94 §1`: a parent told to *"fan the work out"* chose the local tool, and the fix had to be a rename; `94 §8` admits *"nothing mechanical forbids the fallback while the mesh is up"*. Stream B's sharper statement: **any design where load-shedding depends on the loaded machine choosing to ask fails at the moment it is needed** — because the moment it is needed is the moment it is loaded. |
| **D10** | **A corrected fact does not reach the copies that act on it.** `60-verification.md` refuted the 0.81 GB constant on 09-16; `84-calibration.md` refuted it again on 09-17 with a confidence interval; six documents carry dated corrections — and **five deployed copies of the skill the default path loads still carry `0.81 GB / 13–14 turns / ~325 MB per window with no correction marker`**, plus production code documentation. | `B-assumptions.md` §0: `presets/zabz/skills/parallel-agent-orchestration/SKILL.md:135–136`, the identical file in `presets/cordis-bg/…`, in `journal/presets/*/…` and `journal/docs/mesh/*`, and `$HOME/.dsh/.agent-presets/zabz/skills/…` — *"the copy every session on this machine actually reads"* — plus `packages/plugin-mesh-http/README.md:66`. B's own sentence, which is the finding: the overnight program's rule *"a report is a claim, not evidence"* **was applied to reports and never to presets** (`B §0`). |
| **D11** | **The shell has no addressability and no lifecycle policy.** A window is identified by a **port**, not by a session; and nothing ever decides that a quiet session should be culled, suspended or moved — there is a watchdog (`ensure`) and a human-typed `stop <slot>`. | `C-research.md` §10.1: *"`pushState` / `replaceState` / `popstate` / `location.hash` / `sessionId` occur zero times across all 65 installed client bundles"*, the server matches **pathname only**, and the `?token=` exchange **303-redirects to literal `/`** so query parameters are discarded; session choice lives in `localStorage["dsh.sessions.current"]` keyed by origin, hence *"restore the window, then click the session"*. And the lifecycle half: JupyterHub's culler is fed by **two** signals — server activity reports **and** proxy-observed network activity — where the house has neither, which is why *"the machine he sits at becomes the bottleneck"* is a **policy** gap, not a bug. |

**Ranked by what they cost if left uncorrected, because §5's migration order follows this ranking.** Stream
B ranked the same population independently and put (1) the memory/slot belief, (2) *"bigger fleet is the
path to speed"*, and (3) *"a check proves the thing"* together with *"a written record propagates"* as its
top three (`B §10`). I agree on the first, and I put the enforcement layer ahead of the third, because D9
is what makes the routing property optional in the first place:

**D1** (silent, permanent — every future placement decision inherits it, and it is what made the fleet's
*distribution* property unusable on the machine it was bought for) → **D6** (the only failure mode that is
both unbounded and the owner's own; the machine survives the load and the wallet does not) → **D9** (makes
the estate's central property conditional on a model's choice) → **D8/D10** (the cheapest to fix and the
reason the two above them stay alive) → **D7** (costs a machine, once) → **D11** (costs nothing to fix and
buys the owner the two things he keeps asking for — *"which session is this window?"* and *"why is my laptop
holding a session nobody is using?"*) → the rest.

**Two more facts that are not defects but constraints the design must live inside**, and both are
measured: **`0.81 GB per generating turn` is refuted** — the measured value is **403 MiB, CI 270–530**
(`84 §3`, `§3.1`) — and it is *still* printed in `dsh-at-scale/PROGRAM.md:75` and in **both** copies of
the `parallel-agent-orchestration` skill (`presets/*/skills/parallel-agent-orchestration/SKILL.md:135`);
and **a session is a node-local object** — one engine per `DSH_HOME`, a per-*machine* kernel write lease
with deliberately no expiry, and no way to arbitrate a stale lock across hosts (`20 §1.1`).

---

## 3. The design

```
   THE OWNER'S SCREEN                          THE FLEET
   ┌───────────────────────┐
   │ window  origin 3200 ──┼──┐
   │ window  origin 3201 ──┼──┤  the launcher's origin proxy      ┌──────────────┐
   │ window  origin 3202 ──┼──┼──► asked for a window: which      │ FLEET CATALOG│
   │  …  one browser tree  │  │    node owns this session? ──────►│ sessions →   │
   │  + the fleet strip ◄──┼──┘                                    │ node, cost,  │
   └───────────────────────┘                                       │ load, state  │
              │                                                    └──────────────┘
              │ opening a session                                     ▲  written by the
              ▼                                                       │  owner of each session
   ┌──────────────────────────┐    offer work     ┌──────────────────┴───────────┐
   │  THE QUEUE  (one per     │◄──────────────────│  any caller: window, worker,  │
   │  site; a relay between)  │                   │  scheduled job, another node  │
   │  atomic claim = a lease  │─── hand out ─────►└──────────────────────────────┘
   └───────────┬──────────────┘
               │  a job is taken ONLY when the taker's own admission says it has room
               ▼
     ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
     │ node worker @yoga  │   │ node worker @tech  │   │ node worker @…     │
     │ admission: local   │   │ admission: local   │   │ admission: local   │
     │  commit headroom   │   │  commit headroom   │   │  commit headroom   │
     │  logical CPUs      │   │  logical CPUs      │   │  logical CPUs      │
     │  turns IT admitted │   │  turns IT admitted │   │  turns IT admitted │
     │  a reserve for the │   │                    │   │                    │
     │   human at the box │   │                    │   │                    │
     └─────────┬──────────┘   └─────────┬──────────┘   └─────────┬──────────┘
               │  children run without the resident engine needing to be up
               ▼                        ▼                        ▼
        fleet-wide money gate (one account)  ←  the ONLY global resource
```

**One sentence:** *capacity is local and pulled; money is global and granted; state stays where it is and
is indexed everywhere.*

### 3.1 The unit of work: the turn is the accounting unit, the task is the scheduling unit, the session is the state unit

Today only a **dispatched subagent** is placeable; a session's own turn is not (`71 §5`). The brief asks
whether the turn, the session, or something else is the right unit. The answer is that these are three
different questions and the current design conflates them.

| unit | what it is | is it placeable? | evidence |
|---|---|---|---|
| **the turn** | one model call sequence plus its tool calls, ~12.1 s, **403 MiB commit**, **0.62 logical CPUs** model-bound / **1.68** tool-heavy | **No — and it should not be the placement unit** | `84 §3`, `84 §4.3`, `84 §1.2` |
| **the task** | a bounded piece of work with a definition of done; de-facto today, a `subagent` call: one process, one session, one prompt, one result | **Yes — this is what is placed today, and it is the right scheduling unit** | `71 §2.3`, `92 §5.1–§5.6` (11 real children across four runs, every one on the node the broker named) |
| **the session** | the context container: log, write lease, cwd, origin slot | **Not movable; placeable only at creation** | `20 §1.1`, `§1.2`: the lease is a `Local\` kernel object per machine, the log's durability assumes one local filesystem, identity is `realpath`; *"design rule: sessions do not move"* |

**What would it take to make a session's own turn placeable?** Two options, and only one is real.

1. **Move the session so the turn follows it.** Refused by construction (`20 §1.1`): a *resumed* writer
   must scavenge a stale lock, which is one host's question and cannot be answered across hosts; a
   network-shared `DSH_HOME` has no arbiter on Windows at all (`Local\` kernel object, no lock file).
2. **Split the turn.** The model call is *already* remote — the fleet calls `https://api.deepseek.com`
   directly; there is no gateway in the DSH path (`96 §1.1`). What remains local is context assembly, the
   session log, and **tool execution**. So "make any turn placeable" reduces to **"make any tool call
   placeable"**: a remote executor the engine calls instead of spawning `pwsh` locally.

**Is that what the owner actually needs?** No — not first, and here is the arithmetic. A turn costs 0.62
logical CPUs when it is model-bound and 1.68 when it is tool-heavy (`84 §4.3`). Offloading tool execution
can only touch the **1.06-CPU difference**; the 0.62 is the engine's own loop, parsing, context assembly
and session writes, and it cannot leave the machine while the session stays. So the ceiling on the benefit
of turn-splitting is ~63 % of a tool-heavy turn's CPU, on a mechanism that **has never been built or
measured anywhere** (`ASSUMPTION A2`, §6.1). Meanwhile the same owner outcome — *the machine I am sitting
at is not the machine my agents are using* — is bought far more cheaply and entirely with existing
measured mechanisms by **placing the session at creation** (§3.1.1) and **placing the task at dispatch**
(§3.3).

#### 3.1.1 Session placement, and why it is available *today* without a client change

The two-day program's own §5 says session placement "is v2 and needs a client-side redirect the harness
does not have" (`71 §5`). **That is wrong, and the launcher already is the client.** Three measured facts
make it true:

* the client's WebSocket URL is derived from **the page's own origin** — `base = location.origin`
  (`dsh-api-gateway/lib/client.js:542-545`, READ in `20 §1.3`), so a window loaded from an origin served
  by node X opens node X's engine, *"no client change, no hostname in any config, no per-node client
  build"* (`20 §1.3`);
* the launcher already gives **every window its own loopback origin**: `dshw-proxy.mjs` serves
  `3200..3223`, one per slot index, *"'the origin is the window, not the profile'"*
  (`MEMORY-AND-SESSION-LIST.md §1`);
* a loopback-port alias is the **only** origin trick that needs no engine config change and no engine
  restart — the `/api` browser-trust fence 403s `w1.localhost` and accepts any `127.0.0.1:<port>`
  (same section, measured).

Therefore: **window → origin → node is a client-side decision, and the component that makes it is the one
that already opens the windows.** The proxy for slot *n* forwards to the chosen node's engine instead of
`127.0.0.1:3099`. What must be true for it to work: the node must have the workspace (`~/code` exists on
both Windows machines — 22 repos on the laptop, ~28 on the desktop, per the shared context), the tailnet
path must be up (`27–45 ms` laptop↔office, `71 §0`), and the session's own state is then *created* on that
node — which is exactly where it belongs, because it can never move afterwards.

**One condition, and it comes straight from D9: session placement is decided by a component running on the
owner's machine, and that is acceptable only because the decision happens *before* the machine is loaded** —
at window-open time, when there is nothing left to fail. Everything that has to be decided *while* the
machine is saturated must be decided where the resource is owned, not by the machine asking for help
(§3.3.7).

**The honest cost of session placement, which the current design does not have to pay:** a session that
lives on the desktop works on the desktop's checkout. Divergent work on two machines is the failure the
worktree rule exists for (`docs/parallel-agent-orchestration.md`, and the `--ff-only` divergence in
`95 §6.3` where two machines made the *same* change three seconds apart). So session placement is right
for work that is self-contained on the target node (research, docs, a repo already cloned there, a fleet
in worktrees) and **wrong** for work that edits the tree the owner is looking at. That is not a
limitation to engineer around; it is a policy to state in the placement decision, and it is the reason
§3.3 keeps both units.

### 3.2 Where state lives

**Keep: the session log is node-local.** Reasons, all READ out of source in `20 §1.1–§1.2` and none of
them negotiable: the write lease is a per-machine kernel object with no expiry by design; durability
assumes one local filesystem (`MoveFileExW` with no cross-volume fallback on Windows, `link()` + directory
fsync on POSIX); identity is decided by `realpath`; and `sessions`, `.credentials.yaml` and
`profiles/node_modules` are already deliberately machine-local in the repo's own sync rules.

**Add five things, and they are what make a session survive a machine, a window, and the process that owns
it.**

1. **A fleet session catalog — built as the in-house pattern, not as a second invention.** One index row per
   session: `id, node, workspace, cwd, created, last write, bytes, last verified sequence/sha`. Written **in
   the same critical section as the mutation** (create/rename/append/close), stamped, and served at O(1);
   reads refuse to trust a stamp older than T rather than silently serving it.
   *Why it is not optional:* the session list is produced by walking **every session directory on the
   node**, and the cost is **linear in stored sessions** — 681 directories, `readdir` + `stat` + a
   first-zstd-line read each, **5.9 s of raw filesystem work** on one node, **25.4 s** through the engine,
   with *"no paging parameter to lean on"* (`MEMORY-AND-SESSION-LIST.md §2`). The 29 ms cached answer is
   **one of six published remedies and the only one that leaves the pathology in place**, and it converts a
   30 s read into a **15 s correctness window that grows with every session stored** (`C §7.3`, which is
   right about this and says so plainly: *"the fix is one of six published remedies, chosen because it
   required no engine restart"*).
   *And the pattern already exists here:* `journal/index/` is a generated index over ~2,000 entries
   (`entries.tsv` + `journal.db` + a `stamp.json` staleness marker) with a rebuilder that heals itself —
   *"the same repository already implements exactly that shape for the journal … the house is not missing
   the idea, it is missing the application"* (`C §10.4`). **Extending an in-house pattern beats inventing a
   second one**, and it comes with one measured caveat that is now a rule: `108 §10.2` showed the journal's
   own index going stale because a *committing writer must remember to rebuild it* (`idguard` reported 9
   collisions where the answer was 10). So the session index is **write-maintained with a drift-detecting
   rebuild**, never a cache a writer has to remember — which is V6 applied to the one artefact that has
   already failed it once.
2. **A "which node owns this" column in every surface that lists sessions.** Today nothing on any machine
   knows where a session lives; opening one is "reach that node's engine" (`20 §1.2`), and the only
   cross-machine path is a one-way archive with *"no path back"* (`20 §1.2`).
3. **A fail-closed recovery procedure**, because "sessions do not move" and "a session cannot be
   recovered" are different claims and only the first is true. Recovery onto node Y requires, **all** of:
   (a) node X is *provably* dead — two independent checks, no engine answering **and** no live lease
   holder; (b) the log's last frame verifies against the catalog's recorded sequence and sha; (c) the
   workspace path exists on Y; (d) if (b) fails, the session is opened as a **copy** under a new id and
   the original is left untouched. Otherwise it refuses and says which clause failed. This is the same
   *"immutable identifier over a mutable name"* rule that `108 §5.3` earned with a 1,249-path deletion;
   here the immutable identifier is a verified (sequence, sha) pair rather than "the newest file on
   disk".
4. **A durable handle per session, and it is data before it is a URL.** One identity — the catalog id —
   that every surface uses to refer to a session: the fleet strip, the ledger, the launcher registry, a
   future link, and the recovery procedure above. What this buys immediately is that **the window stops
   being the identity**: today a window is a *port*, session choice lives in
   `localStorage["dsh.sessions.current"]` keyed by origin, and *"two windows on the same port share that
   one key — last writer wins on reload"* (`C §9.2`). What it does **not** buy for free, stated as a
   blocker rather than a plan: a *URL* form of the handle is **not available on this build** —
   `pushState`/`replaceState`/`popstate`/`location.hash`/`sessionId` occur **zero times across all 65
   installed client bundles**, the server matches **pathname only**, and the `?token=` exchange
   **303-redirects to literal `/`**, discarding query parameters (`C §9.2`, §10.1). So there are exactly
   two honest paths, and both are priced in §5 rather than assumed: **(a)** an engine-side route that
   honours a handle (H-class, and therefore behind the cold-boot gate), or **(b)** a **proxy-injected
   bootstrap** — the launcher's origin proxy already sits in front of every window and already rewrites
   one request header, so it can carry the handle into the page it serves. Until one is taken, the handle
   is authoritative in the catalog and the launcher maps handle → slot, which is strictly better than a
   port and strictly worse than a URL. `ASSUMPTION A12` is the measurement that decides.
5. **The log is treated as *the* state, not as a record of what a process did.** The raw material is
   already there — a per-session JSONL zstd log with sequence numbers (`20 §1.2`) — and the design adds the
   two properties that make it authoritative: a **defined, idempotent turn boundary** at which a step is
   durable, and the rule that **affinity is an optimisation, not a requirement** (Temporal's published
   position: *"if the cached Workflow is evicted… the Worker must replay the Event History to restore its
   state before continuing"*; LangGraph checkpoints per super-step — `C §9.5`). Two consequences, and the
   second is the one this design acts on immediately: a session can be **restarted in place** without
   ending it, and **a job that dies mid-turn is re-claimable rather than lost** — which is what makes the
   queue's leases safe. What it does **not** yet give is live migration: replaying into a half-applied
   effect is exactly the hazard `C §9.5` pairs with idempotency keys, and the harness's write lease cannot
   be arbitrated across hosts (`20 §1.1`). **So the design takes restartable-in-place and resumable-tasks
   now, and leaves live migration as the thing the checkpoints would eventually make ordinary** — not as
   something this document pretends is solved.

**What state must *not* move, and what identity belongs to what.** Three identities exist and only one of
them should ever be load-bearing: the **origin** (a loopback port) is how a browser keeps two windows from
sharing one `localStorage` slot — a mechanism, not an identity; the **session log** on a node is the
authoritative state; and the **handle** in the catalog is what every surface should name a session by.
Today the fleet reasons about the first one, which is why a window and a session are the same thing in
practice and why a session cannot be addressed on its own (`C §9.2`). Decoupling them is what lets §3.5 be
cheap — and it is the precondition for anything else that wants to talk about "this session" without
knowing which port it happens to be on.

### 3.3 Scheduler and admission

#### 3.3.1 Replace push-ranking with pull-claiming

Today a central broker **ranks polled snapshots** and pushes a decision; a node that is busy cannot say so,
because the broker never asks it — it asks a *contract*, and the contract's load fields are either
constants (D3) or blind (D1). **Invert it.** Work is offered to a queue. Each node runs **one worker** that
asks the queue for the next job **only after its own admission controller has said it has room**. Placement
then happens where the truth is: on the machine that is about to do the work.

The lease survives and is the good part of the broker: **an atomic claim with a TTL**, so two workers
cannot take one job and a dead client cannot wedge the queue (`71 §2.2`: `POST /place` → lease, `POST
/done` → release, *"a lease older than its TTL is reclaimed by the broker itself, so a dead dispatcher
cannot wedge the mesh"*). The *ranking* dies; the *lease* stays — with the one thing stream C found
missing from it: **the claim table must survive the decider's restart.** Today leases live in an in-memory
`Map` (`packages/mesh-broker/lib/leases.js`, cited in `C §10.2`), so a broker restart forgets every
commitment, and `76-broker.md` §8 already lists *"behaviour under a broker restart mid-flight"* as
unverified. The queue's claims are **durable rows**, and that is not a detail: it is the difference between
a scheduler and a scheduler-shaped process.

**And the decision is local-first, because the alternative puts a slow link on the critical path of every
unit of work.** Ray's published design is the inverse of this harness's: schedule bottom-up, try local, and
**spill to a global decider only under overload** (`C §3.5`, §10.2) — against a broker consulted *first*
for every unit of work, across a link where a capacity read was measured at **7,342 ms** (`C §10.2`; the
laptop's own gate is separately measured at **4.42 s**, `95 §1.1`). Stream C's argument against
broker-first is therefore measured rather than theoretical, and it lands. The design's answer is three
parts:

* **the local decision needs no network at all** — a worker with a free slot reads its own machine and
  starts work (§3.3.2), and a local child never touches the queue store;
* **the store is only consulted to acquire work the node does not already hold** — so a node that cannot
  reach it still runs everything it holds, and a node that *can* reach it **claims ahead** (a small local
  buffer of claimed jobs, bounded by its own slots) so the store's latency is amortised across several
  starts instead of paid per start;
* **the store is a claim broker, not a decision plane** — it holds positions and leases; it does not rank
  nodes, and nothing about a node's suitability is computed there.

This directly and structurally cures D1, D2 and D5:

* **D1** — a busy node is a node that is not currently claiming. It cannot be blind to its own load, because
  it is the component doing the loading.
* **D2** — nothing has to *offer* the work to the mesh for the mesh to see it: offering is what a queue
  entry **is**, and the worker is already asking. The nine-hours-idle failure (`95 §0`) becomes
  impossible in the same way a mail server cannot "have mail nobody fetched".
* **D5** — **the branch that inverted the routing property does not exist.** A pull design has no `slow`
  pool to be dropped from and no `preferred`/`dispatchable` alternation to get backwards; latency is only
  how often a worker finishes a claim, and capacity is the only thing that decides whether it claims. The
  current defect is reported fixed tonight — a `slow` node is a ranking, and a test fails when the removal
  is restored — **but that fix corrects a branch, and this design removes the branch.** The transferable
  point is B's: a property that important must be *watched*, not merely implemented (§3.7 V4).

#### 3.3.2 Admission is the only gate, and it is local, arithmetic, and never a refusal

```
commitHeadroomMiB = commitLimitBytes - committedBytes          # the counter 84 §4.4 names
availableMiB      = min(freePhysicalMiB, commitHeadroomMiB - reserveMiB)
memSlots          = floor(availableMiB / 403)                  # 403 MiB/turn, CI 270-530 (84 §3)
cpuSlots          = floor(logicalCpus × 0.42 / CPU_PER_TURN)   # 0.42 = largest measured occupancy (84 §4.1)
                                                               # CPU_PER_TURN 1.68 tool-heavy, 0.62 resident (84 §4.3)
turnsInFlight     = what THIS worker has admitted and not yet settled
slots             = max(0, min(memSlots, cpuSlots) - turnsInFlight - ownerReserve)
```

Five decisions inside that, each traceable:

* **commit headroom, not `swapUsedPct`.** `84 §4.4` proves the published field is
  `max(0, committed − physical)/(commitLimit − physical)×100`, that it reads **exactly 0.0 across a 10 GiB
  spread of commit** on both nodes, and that at "90 %" it is within **410 MiB** of a hard allocation
  failure on the desktop and **1,174 MiB** on the laptop: *"a near-OOM alarm wearing a swap name."* The
  design reads headroom directly, which is the quantity the 403 MiB fit is stated against and which the
  health surface already publishes as `commitLimitBytes` / `commitAvailableBytes` (`109 §3.1`).
* **403 MiB, not 160 MiB.** The 160 MiB slot constant is *"one in-flight tool call inside"* a turn, not a
  turn (`84 §4.2`: *"2.5× the measured per-turn commit cost … and it is not the quantity that limits this
  node"*). It remains a tool-call constant; it stops being a placement constant.
* **logical CPUs, in the unit measured.** `93 §2.1` records the units error that produced a limit of 14
  once: `84` measured `CPU_PER_TURN` in *logical* CPUs and validated `0.75 × physical` in *physical* ones,
  and the conversion under SMT was never measured (`84 §6.6`). Everything stays in the unit that was
  measured.
* **`turnsInFlight` is a count the worker owns.** This is the answer to `84 §5.2`'s finding that a
  dispatched child is a separate process invisible to the resident engine's census, and to `84 §5.4`'s
  finding that a `node.exe` count is a bad proxy (19…27 non-monotonically at 8 live turns). *"Use a turn
  count or use nothing"* — and the only component that can count turns for certain is the one that admits
  them (`ASSUMPTION A1`).
* **`ownerReserve`: a floor of slots remote work may never take on the machine a human is using.** D2's
  whole complaint is that the laptop's own user lost his machine. This expresses "he is sitting there" as
  arithmetic in the one place that can enforce it, rather than as a tier in a central ranking.

**Never a refusal:** if `slots = 0` the worker simply does not claim, and the queue keeps the job with its
position. `queue, never amputate`, kept where it belongs.

**The four states, replacing the five tiers.** `draining` (has slots, claims), `full` (has none, says so
with its own arithmetic), **`stalled`** (has slots and has not claimed within T — *a fault, reported as a
fault*), `unknown` (no reading, and it says so rather than guessing). The redesign deliberately deletes
`ok / slow / unreachable / capacity-unreadable / absent` as *ranking tiers*: `95 §2.2` and `92 §6.3` show
what a tier does when it is wrong, and `92 §5.3` shows what a *false* `slow` costs. "Measured broken" and
"never measured" remain different facts — but they are facts on the node's row, not a position in a
ranking.

#### 3.3.3 What happens when there is no room

The job stays queued, with a position, and the caller is told. This is today's rule and it is right. What
changes is that the position is now computed **at the node that will do the work**, from numbers that
move, instead of at a central service from a contract whose load fields are constants.

**One thing the current design genuinely lacks, and stream C named the published model for it: gang
admission.** A 6-child fleet must reserve **6 slots at once, or none** — otherwise two fleets interleave,
each holds part of what it needs, and neither can start. The harness has never had this: the placement
docs' own note is that a 12-child fleet cannot be honoured by per-child placements (`C §10.2`), and `92
§5.3`'s `--hold 6` run was a *manual simulation* of exactly the missing mechanism (six real leases held by
hand to force the broker to consider a loaded node). The design adopts the published shape — Kueue's
quota reservation before admission, Ray's placement groups for the all-or-nothing case (`C §9.3`) — with
the three properties that make it safe here: the reservation is **atomic** (one writer, one critical
section), it carries an **expected end** so a queue can project rather than guess (Slurm's backfill
rationale), and it **expires under a TTL** so a dead reservation-holder cannot wedge the fleet.
`ASSUMPTION A14` is its test.

#### 3.3.4 What happens when a node is slow

It claims less often and the fleet fills around it. No penalty, no exclusion, and **no `fits`-tier pool to
be dropped from** — because the branch that could get it backwards is not in the design (D5). If a node is
slow *and idle* for longer than T, it is `stalled`: an alert, not a score. Note what that costs and does
not cost. The owner's laptop gate answered in **4.42 s** where every other node answered in 0.27–1.58 s
(`95 §1.1`), so under *any* latency-weighted ranking of nodes the machine he works on will look worst —
which is precisely why the decision is not a ranking of nodes at all, and is instead the node's own claim.

#### 3.3.5 What happens when the mesh is unreachable

* **Each site keeps its own queue and drains it locally.** Home and office are separate networks joined
  only by Tailscale, so a partition is a first-class state, not an error.
* **Cross-site jobs queue** rather than being dispatched into a void.
* **The single reversal I make of today's behaviour:** a queue wait that expires must **not** "dispatch
  anyway". `92 §5.5` records the current rule in the transport's own words — *"no free slot appeared within
  120000 ms; dispatching anyway (queue, never amputate)"* — and it is right when the target is merely busy
  and wrong when it is unreachable, because at expiry the code **cannot tell the two apart**. Meanwhile
  `93 §3` records that *"a run is not cancelled when the client disconnects"*: a caller who gives up while
  the node is still working *"has paid for a turn whose answer nobody saw"*. So: expiry returns position
  and reason to the caller; the work stays queued. Capacity queues; a partition queues; nothing is ever
  launched somewhere it cannot be observed (G1).

#### 3.3.6 One writer per resource

The orchestration skill's rule — partition by file so no two agents touch the same path — is a *brief*
today, which means it is enforced by an LLM's memory. Promote it: **a job declares the exclusive
resources it writes (repo paths, worktree, mission-critical files) and the queue will not hand out two
live jobs that declare an overlap.** The measured reason: the two-machine commit divergence in `95 §6.3`,
where the laptop and the authority each committed **the same change three seconds apart** and the
resulting state could not `git pull --ff-only` (`exit 128`), and the *"staged paths were `journal/**` and
`docs/mesh/**` only — never `git add -A`"* discipline that every careful stream has had to re-derive
(`108`, header).

#### 3.3.7 Enforcement belongs where the resource is owned, not where it is requested

This is the answer to D9, and it is the one place where stream B's finding changes the design rather than
confirming it.

**The hole, in the record's own words.** `109 §5`: the pressure refusal *"is not enforced on
`subagent_local` or `subagent_fork`"*, because those rows are bound to the `spawn` and `fork` providers,
which the placement package does not own — and `109` calls that *"the single largest remaining hole."* Its
measured consequence is `109 §1`: the placement ledger recorded **no placement all day** *"because the model
in each window chose `subagent_local` (or worked itself), and neither of those paths measures anything."*
And the one sentence of persona meant to deter the fallback is admitted to be the only mechanism
(`94 §8`).

**Why it is structural, in one sentence:** a tool name is chosen by a **model**, and a model that is
telling itself the work is urgent will choose the local path. A policy attached to a tool name therefore
has an adversary inside the system.

**The design.** There is exactly one place in the engine where every delegation begins, whichever name was
called: the provider registry (`ctx.subagents`). All four providers — `spawn`, `fork`, `remote-ssh`, and
whatever a `workflow` resolves to — start through it, and each registers under a name a request picks by
name (`94 §2b`). So the gate belongs on the **service**, installed as a wrapper in the **preset layer** —
which is the seam `109 §6.1` already names (*"a provider wrapper registered in the preset layer, where
`subagent_local` and `subagent_fork` are bound"*). Two properties follow immediately: it is **S-class**, so
it is live at the next session with no restart (`94 §6`), and **it cannot be bypassed by naming a different
tool**.

**The order of decision, for every provider and every call:**

1. **Read this node's own admission** (§3.3.2). If it has a slot and the target is local, start the child —
   the cheapest path, no network, no queue.
2. **If it has no slot, offer the job to the queue** and return the position. A child that is waiting is not
   published as a running agent, which is a construction the remote provider already proves (`92 §4`:
   *"a waiting child cannot appear as one"*).
3. **If the local option is declined and the queue is unreachable, refuse with the reading named** — the
   behaviour `109 §3.3` already chose for the remote path, now applied to all four names.
4. **A local child already running when the machine goes critical is never killed.** The rule is about
   admission, not eviction; `queue, never amputate` is a promise about work, and killing running work would
   be the amputation the rule exists to prevent.

**What this makes true that was not.** Load-shedding stops depending on the loaded machine *choosing* to
ask, because no child of any kind can start without passing that machine's own admission, and the
admission's answer when the node is full is *"queued at position N"* rather than *"run it here"*. The one
case it does not fix is a model that works the task itself instead of delegating it — no provider seam can
see that, and the answer there is cost and context discipline (§3.4), not routing.

#### 3.3.8 Three ranking decisions the current design gets wrong, and the published alternatives

All three come from stream C's research, and each is a case where a mechanism with a published design was
re-derived less completely.

**1. Spread is a property of the job, not of the fleet.** The current ranking fills the roomiest node until
it can no longer take the job (`92 §5.1`: *"the mesh is filled in the order most room first, so it spreads
proportionally and only under load"*) — which is defensible for two children and indefensible for eight.
Being precise about the two causes of the eight-child measurement, because they are different defects with
different fixes: the **roomiest-first fill** explains why the first **seven** landed on the desktop
(`92 §5.2`: seven children in, the desktop was at 11 free slots and the laptop at 12), and the **`slow`
demotion** explains the **eighth** (`92 §5.3` — the branch, removed in §3.3.1, which the *slow* fix
corrected tonight). Nomad's published shape has the same default and the half the harness lacks: **binpack
by default, with a per-job spread override** (`C §3.3`) — it is the *override* that is missing here. So
`spread` becomes a field on the job, and the design's own reasoning for the default is stated rather than
inherited: a *large independent* job spreads (fan-out over nodes is the entire point), a *small* job does
not (one node taking two children avoids two cold starts, and `92 §5.1`'s measurement of **1985 ms** to
place and launch two children on one node is the cost a naive round-robin would double).

**2. Ranking must be on what is *committed*, not only on what is free.** Today a node carrying a long
lease ranks identically to an idle one, because the score sees instantaneous free slots — no projection, no
backfill (`C §10.2`). Slurm's backfill and SQS's visibility timeout are the published answers: a claim
carries an expected end, so a scheduler can say *"this node is free in 40 s"* rather than *"this node has 0
slots"*, and a job that fits sooner goes sooner. This matters here because the fleet's work is bursty and
its jobs are short (a turn is ~12.1 s, `84 §1.2`), so a 40-second projection is the difference between a
node being idle for a minute and not.

**3. Shedding needs a declared order, because right now the OS decides.** The admission governor admits from
free memory and **never preempts** (`C §10.6`); under pressure the observed behaviour is *"commit pressure
trimming working sets"* and whichever window was streaming became slow (`PERFORMANCE-MEASURED.md`, cited in
`C §10.6`). Kubernetes' published model is an **ordered eviction policy** — `BestEffort`, then `Burstable`,
then `Guaranteed` (`C §10.6`). The design adopts the *ordering* and not the eviction, because
never-amputate applies to admitted work: what may be shed is always something that is **not running work** —
an idle window's renderer first, a prewarmed runner second, a completed session's UI third — and admitted
agent work is never killed to make room. That is a declared policy replacing an emergent one, and it is the
honest reading of the rule: *queue, never amputate* is a promise about work, not about browser renderers.

### 3.4 Cost as a first-class constraint

**Money is the only truly global resource in this fleet.** CPU and commit are per node and measurable
locally; the wallet is one provider account for every machine, and the provider publishes **no
`x-ratelimit-*`, no usage headers and no usage API** (`96 §2.2`, `§4.3`). So the design splits cleanly:
**capacity is local and pulled; money is global and granted.**

**Where the budget belongs, precisely:**

1. **At the step seam, in the engine.** The only place that sees every billable step and can close a turn
   without destroying anything is the pre-step seam (`96 §5.1`: `{kind:'reject'}` → *"the turn closes
   `blocked`, nothing is destroyed, the session resumes tomorrow"*). Enforcement there, not in a report.
2. **With a fleet-wide ledger on the authority**, because a per-node counter cannot see the fleet, and the
   authority already owns the authoritative store.
3. **Visible on screen**, in the fleet strip (§3.5): `96 §4.3` measured that today the owner *cannot* see
   spend as it accrues, and that the two existing ways both require asking someone.
4. **As a placement input**, because the card is exactly **2× at peak** and the peak windows are his
   evenings (`96 §4.1` assumption 3: 21:00–00:00 and 02:00–06:00 Eastern on weekdays). A scheduler *may*
   defer non-urgent work into off-peak; the default is **off** (do not delay a job he asked for), and the
   capability exists so that a fleet of mechanical jobs can be told to run cheap.
5. **As a rate and a ceiling that mean different things.** Three envelopes: **per session** (a runaway
   session cannot eat the fleet), **per hour** (a burst cannot eat the day), **per day** (the total), plus
   the **concurrency cap** — `96 §5.2`'s recommendation is **12 generating agents per machine**, and it
   matches the machine measurements independently: 14–39 turns before cores bind on the desktop (`84
   §4.3`) and the historical in-flight peak of 16–22 requests (`96 §2.4`). *"Cap both"* — a fleet-wide
   money cap alone would let the machines thrash while the wallet stayed green.
6. **The unit of reservation is the request, not the turn.** The per-turn figure is a **mean over a heavy
   tail**: `96 §4.1` computes **$0.0042/turn** (2.73 requests × $0.001523 at the 09-17 mix of 196,945
   tokens and 98.5 % cache hit) and then says plainly that *"the mean is the floor"* and that the 395–957
   step sessions were **52.5 % of a $54.92 day**. Reserving a constant per turn would systematically
   under-reserve exactly the sessions that cause the damage.
7. **Fail-closed, with the owner's rule intact.** At the ceiling, **new fan-out stops** and the turn closes
   `blocked`; nothing is destroyed and nothing is refunded mid-flight. Below the ceiling, nothing changes
   at all.
8. **The per-session envelope is also the context discipline, and on the evidence that is the bigger
   lever.** The priority ordering the measurements support is **cost-per-turn first, the engine's own
   single-engine scaling second, fleet size a distant third** — the reverse of where the last two days went
   (`B §A9`). Cost-per-turn: **82–96 % of carried prompt tokens are tool output** (`60-cost-audit.md` §7
   Tier 1, cited in `B §10.2`), the largest single measured lever is *"split long work across sessions"*,
   and three sessions were **52.5 %** of a $54.92 day (`96 §8`). Engine-side: `/api/session/list` took
   **>40 s at 17 concurrent loops** (`100 §2`) — a single-engine scaling limit, not a fleet limit, and the
   same code path `MEMORY-AND-SESSION-LIST.md` measured at 25.4 s on the laptop. So the envelope in item 5
   is not only a cap on a session; it is the mechanism that forces long work into separate sessions, which
   is where the money actually is.

**The weakness I am not allowed to paper over.** The local ledger is a **lower bound**: `96 §4.1`
assumption 4 records that on the one reconcilable day the local logs were **50 % of the misses and 76 % of
the hits**, so fleet-wide money should be treated as *"×1.3–2.0 low"*. A budget enforced on a lower bound
is a budget that can be breached by 2× while reporting green — which is the *exact* failure class in G4.
So the architecture requires three things, not one: **(a)** reserve against a multiple of the ledger
figure, **(b)** reconcile against the provider console export on a schedule and **publish the
reconciliation and its date**, and **(c)** never present the ledger number as *the bill* — the provenance
rule ("every reading carries its source and its age; a reading without them is a refusal") applies to
money with the same force as to memory. `ASSUMPTION A5` (§6.1) is the test.

**One more thing the money model must do, because it is the cheapest money in the system:** 42 % of the
bill is *re-reading context that did not change*, 33.5 % is what the model wrote, 24 % is uncached input
(`96 §8`, from `60-cost-audit.md §1.3`); the cold/warm ratio is **42×** (`96 §2.3`); and cost scales as
**steps × mean context** (`dsh-at-scale/PROGRAM.md`). A budget that only counts dollars and does nothing
about prefix invalidation is treating the symptom. Cache-preserving changes (stable tool lists, no
mid-session system-prompt rewrites, the pruner settings already measured) are *budget* work, not
performance work.

### 3.5 The UI

**Is a browser window the right shell? Yes — and the window must stop being the identity.**

The measurements settle the cost question: a private-profile window cost **9 processes / 892 MB** (7
windows: 74 processes, 6,804 MB) and the shared-profile fix reduced the marginal window to **+0–1
processes / +60–296 MB**, because for N windows the total is now `tree + N × renderer` instead of `N ×
tree` (`MEMORY-AND-SESSION-LIST.md §1`). What made sharing safe is that **the origin is the window, not
the profile**: a distinct loopback port is a distinct origin, so each window keeps its own session slot
**without** owning a browser (`§1`). That is the whole design and it is already built and measured.

**Three limits on that number, because stream B measured the other half of it and the fix did not touch
it.** (a) The 60–296 MB / +0–1 process figure is the **marginal** cost at **n = 2** windows; the projection
at 8 (17 processes against 72) is a projection (`MEMORY-AND-SESSION-LIST.md §1`, §6), and **twenty or more
shared-profile windows have never been measured by anyone**. (b) The change fixed the **process tree**, not
the **renderer**: a quiet window still costs **0.24–0.28 core and 467–783 MB private**, and 12 idle windows
measured **2.27 of 22 cores** (`80-windows-and-parity.md §6.4`, cited in `B §9.4`). (c) In a shared profile
**only the first window's URL appears in any process command line**, so no process scan can say how many
windows are open — the liveness signal is live connections per alias port, and the probe must exclude itself
(`MEMORY-AND-SESSION-LIST.md §4`). **Consequence for the design: the UI must not assume that many windows
are free.** So the redesign reduces the number of windows that need the *loaded* engine (§3.1.1) and puts
the fleet view in **every** window, instead of relying on window count being cheap.

So the redesign keeps:

* **separate OS windows** (he tiles them, he alt-tabs — removing that would be taking a capability away
  for an engineering taste reason, and the program's own standing rule is to remove waste before
  capability);
* **one window per slot/workspace**, because the origin still is per-slot;
* the **shared profile** as the default, with `profileMode: "per-window"` kept as the escape hatch.

And adds two things, both of which cost **no new browser process and no engine restart**:

1. **The window is not the session.** With §3.1.1, a window's origin can point at *another node's* engine,
   so the number of windows stops being the number of sessions the laptop's engine carries. This is the
   single change that most directly serves G2 — today, ten windows with several agents each means ten
   resident sessions in **two** engines, and if the tools are plain `subagent` calls *"all 55 land on the
   machine that owns the window and nothing consults the broker"* (`95 §7a`).
2. **A fleet strip in every window**, served by the component that is already in front of every window —
   the launcher's `dshw-proxy.mjs`, which already keeps one cached `session/list` response and re-labels
   it per caller (`MEMORY-AND-SESSION-LIST.md §2`). It shows: each node, its **own** admission arithmetic,
   its queue depth, its `stalled`/`full`/`draining` state; the wallet (spend today, rate, ceiling); and
   **which node owns each of my sessions**, from the catalog in §3.2. Cost: one cached RPC.

**The session list is fixed by the index, not by the cache.** The 25.4 s → 29 ms improvement is real and
measured (`§2`) and should ship as a stopgap; but it is a cache over a walk that is **linear in stored
sessions** and has no paging parameter, and its 15 s TTL is explicitly *"a judgement, not a
measurement"* (`§6`). The architecture's answer is the catalog (§3.2), and the cache is marked in the
design as a band-aid so nobody later mistakes it for the fix.

**Three things the shell is missing that the wider field solved, and they are not cosmetic** (`C §9.1`,
§9.2, §10.1, which call the launcher-plus-proxy *"a hand-rolled, less capable JupyterHub"* and note that
**addressability and a lifecycle policy are exactly the two things this harness is still blocked on**):

1. **Addressability — a durable handle, not a port.** Covered as §3.2 item 4. The measured size of the
   problem: session choice lives in `localStorage` keyed by **origin**, so two windows on one port share one
   key and the last writer wins on reload; nothing is addressable by URL; and the `?token=` exchange
   discards query parameters on its way to `/` (`C §9.2`). The fleet strip is the first consumer of the
   handle — *"which node owns this session"* is unanswerable today because a session has no name a surface
   can use.
2. **A lifecycle policy, not a watchdog.** The house has `ensure` (*"is it up?"*) and a human-typed
   `stop <slot>`, so **nothing ever decides that a quiet session should be culled, suspended or moved**
   (`C §10.1`, §9.1). JupyterHub's culler is fed by **two** signals — server activity reports **and**
   proxy-observed network activity — with a documented timeout, and the launcher's proxy is *already in a
   position to observe the second one*: it counts live connections per alias port and serves
   `/__dshw/open` (`MEMORY-AND-SESSION-LIST.md §4`). So the design adds a **declared cull policy**: a
   session idle by *both* signals past T is **closed, never deleted** — its state is the log, its slot is
   freed, and it is re-openable by handle (§3.2 item 4). This is the mechanism that answers D2's complaint
   at the level the owner actually feels it: *"why is my laptop holding twelve sessions nobody is using?"*
3. **One spawner abstraction over "where".** JupyterHub's Spawner exists so that *local process*,
   *container* and *another host* are the same three operations — start, poll, stop (`C §10.1`). The house's
   equivalent is split across `dshw.ps1` (one Windows machine), the broker (placement) and
   `plugin-remote-fanout` (dispatch): three mechanisms for one concept. The design does not build a
   Spawner interface — it does not need the abstraction — but it makes the three agree on **one contract**:
   the session handle, the node, and the state transition — so that "where did this session go" has one
   answer instead of three partial ones.

**What he loses, stated honestly:**

* **Nothing he uses**, per the measurements: separate windows, one per slot, restore-after-reboot, and
  per-window session *and* cookie isolation all survive (`§1`, "What the owner loses").
* **The accepted cost stands:** with one browser tree, a **browser-process** crash takes every window with
  it (a renderer crash still takes only its own). That is why `profileMode` remains a config key
  (`§1`, `§6`).
* **A new cost the design accepts and must design around:** with windows pointing at remote engines, the
  launcher's origin proxy becomes load-bearing for *opening* windows (§3.8, SPOF 5). The mitigation is
  that the proxy must never be load-bearing for *state*: `Resolve-WindowUrl` already treats the recorded
  URL as a **candidate** and uses the first one that survives a real request
  (`MEMORY-AND-SESSION-LIST.md §3A`), and the engine's own loopback port remains a valid fallback origin.

**What I would not build:** a desktop/Electron shell — a second Chromium is the 892 MB cost the shared
profile exists to avoid; and a per-node dashboard page inside each engine, because that is D8's trap (a
surface that reports the node it is on and looks healthy).

### 3.6 Configuration and change without a restart

The incident is the specification: a **rebuild through a live-reload junction armed a fault eleven hours
before it could fire**, and the first cold boot failed with `MODULE_NOT_FOUND` three layers away from the
mistake, while the launcher retried three times and never surfaced the stderr tail it had already captured
(`2026-09-17-dsh-engine-boot-failure` §3, §4.3, §7.3, §8.1). The Mac Mini carries the same class of
defect right now: its **running engine cannot be booted** (`--profile web --dump-config` exit 1, `95
§3.2`), and nobody would notice until a reboot, a crash, or a hygiene action.

**0. The premise, corrected: restart-to-activate is not a design — it is the loader's accident promoted to
policy.** Stream B found this and it is the most useful negative in the record. `71-mesh-program.md:16`
states as a *frozen constraint* that *"a mounted bundle cannot hot-load — **v1 must not require an engine
restart**"*; `92`, `100`, `105`, `106` and `109` then all shipped changes that require one. **And the idle
window built to take those restarts has never fired and cannot**: it declines on any non-zero
`agentLoopsRunning`, and the owner's fleet is always running — `100 §3.3` shows a live refusal at 16–17
loops, and §4 records the gate open only when his fleet is done, *"which is exactly when nobody needs it"*
(`B §A12`). Meanwhile the restart that *was* taken is what armed the cold-boot failure that took the
machine down (`incident`, and §2 D7). Two measured escapes need no idle window and no owner:

* **An isolated `DSH_HOME` process** — a second engine on a scratch home and a scratch port, the owner's
  engine untouched. This is not a proposal: it has been used to prove a composed configuration boots and
  dispatches **three times** (`92 §7`, `105 §4.1`, and `106 §5`'s isolated-engine proof), and it is the
  acceptance path for any host-plane change.
* **A profile that composes fresh per process** — `dsh --profile mesh headless "<task>"` *"starts a fresh
  process with that composition"*, which is exactly why the `mesh` profile needs no restart at all
  (`71 §5`).

**The design's conclusion: the default execution unit is a fresh process carrying the desired
composition.** Composition changes are then activation-free *by construction* — the change lives in the repo
and the profile, and the next process composes it — and the resident engine is kept for what it is actually
good at: the owner's own interactive sessions. Those may lag a change, and that lag is a **visible state**
(item 5), never a blocker and never a reason to wait for a human to be idle.

**1. Classify every change by its activation cost, in the artefact itself.**

| class | examples | when it takes effect | evidence |
|---|---|---|---|
| **S — session-scoped** | presets, skills, agent config, per-agent tool grants, **the provider wrapper of §3.3.7** | **live**: the next session a human opens | `94 §6` — the preset store's `list()`/`resolve()` re-read roots on every call, `mount()` re-composes at `session/create`, and a changed composition file forces re-composition on an `mtimeMs + size` stamp |
| **P — profile-scoped** | anything a *fresh process* composes: the `mesh` profile's tree, the headless worker's row set | **live**: the next process — no restart, no idle window | `71 §5`; and item 0's three isolated-home proofs |
| **H — host-plane** | the profile's bundle list, `cordis.patch.yml` rows, host plugins — **i.e. the owner's resident engine only** | **only at engine start**, and it is now the *rare, opt-in* class | `90 §0`, measured: a bundle added to a running profile's `package.json` and junctioned into its `node_modules` produced `/healthz` **404 still** after 8 s; *"`patchReload: live` covers the profile's own `cordis.patch.yml`, not the bundle list"* |
| **D — data/config read at start** | settings, machine overrides | at start | `95 §3.4` (a roster note and its `dispatch.v1: null` had been stale for nine hours) |

An **unclassified change is refused** by the deployment path. One line, and it kills a whole family of
silent surprises; it is the same shape as "every reading carries its source". The point of the table is
now the *inverse* of what it was: **H is the class to avoid designing changes into**, because P covers it.

**2. One composed artefact per boot, verified by one command that can fail.** `100 §11 item 1`: *"a
host-plane activation has three parts, and they live in three places: the package (linked into
`profiles/<p>/node_modules`), the rows (`~/.dsh/profiles/<p>/cordis.patch.yml`), and the running engine. A
restart only refreshes the third."* The measurement that makes the coupling concrete: the live patch layer
was byte-identical to `HEAD` — which **did not** carry the rows — and a **15-minute autosync rewrote them
out of `~/.dsh`** (`100 §5`); the same document records a hand-edit wiped within five minutes. The fix: the
package link, the rows, and the profile's bundle list are **derived into one composed artefact** from the
repo, that artefact is verified by one command that can fail, and **its identity is served beside the running
process** — so "what is composed" and "what is running" cannot disagree silently. That silent disagreement
is precisely D8's rows 1 and 2, where the *same binary on the same bytes* returned exit 0 with 620 lines and
exit 1 with 16.

**3. The cold-boot gate validates the artefact, and it runs in the class that matters.** Four parts, all of
which must pass: (a) a scratch `DSH_HOME` (its own directory — two engines on one home corrupt session
logs, `20 §1.1`) on a scratch port; (b) **`DSH_HOME` unset**, which is the incident's exact failing
condition and *"the normal path, not an edge case"* (`incident §4.2`); (c) `dsh --profile web --dump-config`
→ exit 0, then boot, then `GET /healthz` → 200; (d) **one real turn** on the scratch engine. Added by §3.7
V2: the gate is run **once per reader class that will use the composition** — Interactive, ssh-spawned,
scheduled task — because a profile check is only evidence for the class that ran it (`106 §8`). The
incident's Appendix B is a one-line regression for the specific bug (`Remove-Item Env:DSH_HOME; node -e
"import('…/guard.js')…"` → must print `LOADED`), and the Mac Mini is the standing example of what happens
without the gate: its **running engine cannot be booted** (`95 §3.2`).

**4. Activation is atomic, reversible, and has a last-known-good.** The previous artefact is kept and the
supervisor boots it when the new one fails to become healthy N times. The supervisor must distinguish
**"port dead" from "the process started and exited"** — the incident's §7.3 is explicit that `ensure` cannot,
and that surfacing the captured stderr tail *"would have turned a 10-minute investigation into an instant
answer."*

**5. Mount immutably, and prove the mount by reading *through* it.** A junction to a mutable checkout means
**a rebuild is live the instant it is built** (`incident §2`, §8.1). The fix is `108 §5.3`'s rule — *prefer an
immutable identifier over a mutable name* — applied to mounting: build into a **content-addressed release
directory** and flip one pointer, so "what is deployed" and "what is running" are both identifiable by a
hash. And on Windows the install's own definition of done must be a **read-through-the-link** proof, not a
listing. Measured on the desktop: the junction was present, its target existed, twelve files were in it,
`cmd /c type <junction>\lib\index.js` returned *"The path cannot be traversed because it contains an
untrusted mount point"*, the engine booted anyway **resolving a different, older copy** (0.1.0, 4,382
bytes, no `placement.js`), and `--dump-config` exited **0 with 620 lines** (`106 §2–§3`, `B §A15`). The
discriminator is the reparse point's **ACL owner**, and `Test-Path`, `dir` and `--dump-config` do not test
it.

**6. Nothing is armed silently, and nothing is activated by a person being idle.** `journal/entries/handoff/H461.md`
knew the guard would mount at the next restart and said so — in a document, which is not a surface any
machine reads (incident, addendum). So: an **armed registry** publishes what is on disk, what the *running*
process has actually loaded, and the difference between them, on the health surface and in the fleet strip —
"takes effect at next start" becomes a visible state rather than a footnote. And the rule that follows from
B's A17: **a change whose activation needs a human must either be made safe to activate or be explicitly
queued as an owner decision — never left armed in a scheduled task.** The 15-minute restart window is the
worked example of the third option, and it is the one that cost the most.

### 3.7 Verification: what the architecture must make true for a check to be evidence

**The catalogue, because the catalogue is the requirement.** Every entry is a check that reported success
while the thing it named was false:

| # | the check | what it reported | what was actually true | shape |
|---|---|---|---|---|
| 1 | `mesh-health.ps1` (default node list) | healthy | it asks **3 of the 5** gated nodes; the two newest were never read — one of them fail-open, one of them un-bootable | **domain narrower than the claim** (`95 §5.1`) |
| 2 | `mesh-capacity-probe.ps1` (`$GatedNodes`) | pass | the Mac is not in the list, so its capacity is never read — *the exact failure the comment above it records as already having happened once* | domain (`95 §5.2`) |
| 3 | `mesh-e2e.ps1 -Strict` | the program's definition of done | exits **2 with 3 SKIPs**, every time, on any mesh, forever, because the named command does not pass the flags the steps need — *"§0's success criterion is not reachable by §0's own command"* | **the contract names a command that cannot satisfy it** (`95 §5.3`) |
| 4 | `accepts.maxChildren` | this node's measured acceptance limit | the literal `12`, derived from a JSON example in a frozen contract, consumed by the broker | **a constant published as a measurement** (`95 §1.4`) |
| 5 | `governor.budgetSlots` | this node's slot budget | `24` on all five nodes | constant as measurement (`95 §1.4`) |
| 6 | `agents.loopsRunning` | the node's agent load | 0 in all 83 samples with 8 real children running; and used in scoring **nowhere** even when it is non-zero | **reported, never consumed** (`84 §5.2`, `95 §5.4`) |
| 7 | `--dump-config` on the desktop | the profile composes | **exit 0 with 620 lines from an Interactive-logon reader and exit 1 with 16 lines from an ssh-spawned one, on the same bytes, in the same minute** | **the result is a function of the reader** (`106 §8`) |
| 8 | `journal.py check` | 0 errors | 0 errors while **18 id collisions were live**, because it builds its world from one tree and never asks what a ref holds | single-tree by contract (`108 §10.1`) |
| 9 | `idguard` | 9 collisions | 10 — because it reads a **generated cache** the other machine committed without regenerating | **a gate as fresh as a file a writer must remember to rebuild** (`108 §10.2`) |
| 10 | the carry script's `EXPECT = 41` | a gate | *"a comment wearing a gate's clothes"*; the next version had no gate and began appending **457 spurious files** | **a check with no red path** (`87 §4.7`) |
| 11 | acceptance sub-cases binding `$body` | four sub-cases passed | every POST carried an empty body — they tested the wrong task | the check did not test its subject (`87 §4.7`, `L1824`) |
| 12 | a macOS audit script's `uid` check | "no blockers" | `uid` is a readonly bash builtin; it failed silently every time | the check cannot fail (`87 §4.7`) |
| 13 | `secratary-smoke.sh` starting a second broker | green | it would have died of `EADDRINUSE` and every curl would have been answered by the **service** | **green while proving nothing** (`86`) |
| 14 | `Test-LaunchUrl` | a valid launch URL | it only ever checked the token's **shape**; the recorded token was dead (401) while the live one answered 303 | shape instead of behaviour (`MEMORY-AND-SESSION-LIST.md §3A`) |
| 15 | `Test-OriginsProxy` | the proxy is dead | it read **its own memoised first answer** 60 times while the proxy was up and serving | a stale reading taken as current (`§3B`) |
| 16 | `error_log` row counts | "how often the DB locks" | **222 rows all-time / 130 in 7 days** against **3,322 journal events in the same 7 days** — a **27×** undercount, because the health probe handles its own timeout | **the denominator is not the population** (the `ps_db_query` schema hint, which exists because agents got this wrong) |

**Nine rules the architecture must make true.** These are not style; each is the direct inverse of one or
more shapes above.

* **V1 — A check's domain is data, and it is declared.** A node list is derived from the roster, never a
  literal. A check whose domain is smaller than its claim must **fail**, and the failure names the missing
  members. (Inverse of 1, 2.)
* **V2 — A check declares the reader class it is valid for, and the runner runs it in each class.** The
  classes are measured, not invented: local Interactive, ssh-spawned remote, scheduled task,
  SYSTEM/session-0 (`106 §8`; and `85 §8.2` measured that a SYSTEM task in session 0 *cannot* measure the
  console). A check not yet run in the class its subject runs in reports **UNVERIFIED**, never PASS.
  (Inverse of 7.)
* **V3 — A check asserts a property of the output, read back through the path a consumer uses.** `87 §4.7`
  earned this with a pixel test: *"the failing assertion was the one that decoded the JPEG and read the
  pixels back; every test that could have been written against the function calls would have gone green…
  when a pixel test fails and the geometry test passes, believe the pixel test."* The Windows case of the
  same rule is the reparse point (`§3.6.5`): *"the package is installed"* is a claim about an ACL owner, and
  the only proof is reading **through** the link (`106 §2.3`). (Inverse of 11, 13, 14.)
* **V4 — Every check ships with a demonstrated failure.** Either a mutation that removes the thing being
  checked, or the pre-change implementation taken from an **immutable id** and shown failing.
  `verify-alloc.py` is the model: it takes the old rule out of git at `622876e` — never retyped — and
  proves two machines mint the same id under it, then proves the new rule does not (`108 §6.1–§6.2`). *A
  check whose failure has not been observed is a claim, not a check.* (Inverse of 10, 12, 13, 15.)
* **V5 — Five outcomes and an executed contract.** `PASS / FAIL / SKIP / UNVERIFIED / STALE`, and the
  **contract itself is executable**, so a done-criterion that its own command cannot satisfy is itself a
  failure. `-Strict` exiting 2 with SKIPs must be a **red**, not a footnote. (Inverse of 3, 6.)
* **V6 — No check may read a generated cache, a mutable name, or a memoised answer as if it were the
  source.** Read the source of truth, or label the reading a lower bound and say so. Where two reads must
  agree, resolve the whole unit from **one immutable reading** (`108 §5.3`). (Inverse of 8, 9, 15.)
* **V7 — Every reading carries its source and its age, or it is refused; and a field that cannot vary
  across a population is reported as a constant.** The second half is the operational test for 4 and 5: if
  five nodes report one value, print `constant`, not `measured`. `84 §5.5` adds the timing rule: *a row's
  timestamp must be the moment it measured* — stamping at the top of a loop that then spent 2.1 s in
  `Get-Counter` **halved the apparent slope** (301 vs 403 MiB/turn) and would have misled in the other
  direction against any counter read early.
* **V8 — A fact that must stay true gets a keeper, not a document.** This is the direct answer to D10, and
  it is ranked third by B for cost *"only because it is the cheapest to fix"* while being *"the mechanism by
  which every other wrong assumption here survives"* (`B §A11`). A document is not a delivery mechanism; **a
  keeper is** — something that runs on a clock, compares against the canonical value, and exits non-zero.
  `journal/README.md` already names the shape (*"a component that can silently disappear needs a keeper, not
  a procedure"*) and `install-client-plugins.ps1 -Check` is the one instance that exists. Concretely: **one
  measured-constants registry** — each constant with its value, the document that measured it, and the date
  — every consumer (skill, README, preset, code comment) either derived from it or compared against it, and
  a keeper that reds when a **deployed** copy disagrees. The rule that makes drift self-announcing: *a
  superseded constant must carry its replacement at the point of use*, so a stale copy cannot be mistaken
  for a live one. Without this, this document's own corrections will be the next autopsy's findings.
* **V9 — A component's claim that it is *running* is not evidence; count artefacts.** Measured in this
  estate twice: two of six fleet workstreams landed **zero commits** while reporting *"running"*
  (`journal/state/open-pain.md` `P181`, cited in `B §A18`), and *"the processes are live; the workload is
  not"* across nine idle hours (`95 §0`). The redesign applies it to its own new component: a worker's
  health is **claims settled per minute**, not a live process; a node with slots and no claims is `stalled`;
  and *"count commits per branch"* is the same rule for fleets. It is also the rule that makes §3.8's
  biggest risk detectable rather than fatal.

**Three models to copy, all already in the estate.** (a) `verify-alloc.py`, which takes the pre-change rule
**out of git at `622876e`, never retyped**, and proves it collides (`108 §6.1`) — the only check here that
carries its own demonstrated failure. (b) **Tonight's `slow` fix**, which ships with a test that fails when
the defect is restored (`actual: 'zabz-tech', expected: 'zabz-yoga-1'`, stream B's correction note) — V4
applied to a live regression by the stream that fixed it. (c) `mesh-e2e.ps1` S1, which **enforces**
`node == fqdn.split('.')[0]` rather than assuming it and reports both macOS meanings of "free" (`95 §1.3`,
§5.3) — a check that reads a property instead of a shape. And one rule from `B §A10` adopted verbatim: **an
empty result is not health.** `100 §3.2` has the worked example — *"no session row carries running=true"*
printed when `session/list` had simply timed out; the fix is to name which reading failed and keep the one
that did not. `84 §1.4.2` states the same for counters: *"a counter that reads 0 is not evidence that
nothing happened."*

**And the inverse obligation, which is the real point:** a redesign of the *system* must make the checks
cheap. Every one of the sixteen failures above is cheaper to prevent with a structure than with
discipline — a roster that is data, a reader class in the command line, a mutation test next to the check,
a contract that is code. This is why §3.6's armed registry and §3.3's `stalled` state are *verification*
features, not operational ones.

### 3.8 Failure and blast radius

Named single points of failure, and the designed behaviour when each dies. Three of these are **new** in
this design and are the price of it; they are marked **NEW**, and each has a stated mitigation.

| # | SPOF | what dies with it | designed behaviour | mitigation |
|---|---|---|---|---|
| 1 | **The queue store** (authority, **NEW**) | new work stops being *offered* to the fleet; nothing already claimed is lost | each worker finishes its claimed jobs; unclaimed jobs stay queued; every caller already holding a position keeps it; the fleet strip shows `queue-unreachable` and the age of the last successful read | the store holds **only** claims and positions — it is not the ledger (per-node files, `92 §4`) and not the catalog (derived); it is deliberately **not** the company DB, on a 4-core box whose swap read **81.2 %** (`95 §1.1`) and whose swap-in-use is *"not attributable to any process currently resident"* (`95 §1.1`) |
| 2 | **A node's worker** | that node stops claiming | other nodes drain the queue; the node's un-settled claims are returned by lease TTL (`71 §2.2`); the node reports `stalled` **because it has slots and is not claiming** — the state D2's nine idle hours had no way to express | the worker is a supervised process, not a session; it can be restarted without touching the engine |
| 3 | **A node's resident engine** | that node's *sessions* stop; its windows 502 | **the worker on that node keeps working**, because a `--profile headless` child is a separate process that needs no engine (`71 §0`, measured: *"`accepts.oneShot` is still true (a headless run needs no engine)"*) | sessions are node-local and survive on disk; the supervisor restarts the engine; windows re-attach to the same origin |
| 4 | **The Tailscale path** (home↔office) | cross-site placement | each site drains its own queue; cross-site jobs queue with position; **nothing is dispatched into an unreachable site** (§3.3.5) | the two sites are independent queues by construction; the partition is a *state*, not an error |
| 5 | **The launcher's origin proxy** (**NEW**) | every window's origin, while the engine is fine | this is the one new SPOF that can make the owner's *screen* useless while everything else is healthy, so: the proxy is supervised exactly as the engine is (the launcher already re-registers its task every minute and holds an atomic lock — `MEMORY-AND-SESSION-LIST.md §3C`), the **direct engine URL remains a validated fallback candidate** (`§3A`), and **no session state depends on the proxy** | ship §3.1.1 behind a per-slot opt-in so the blast radius of a proxy bug is one class of slot, and keep `profileMode` |
| 6 | **The browser process** (shared profile) | all windows at once (a renderer crash takes only its own) | accepted, measured cost of one browser tree (`MEMORY-AND-SESSION-LIST.md §1`, §6); sessions and their logs are untouched; the launcher restores the working set | `profileMode: "per-window"` restores the old behaviour exactly, at 892 MB per window |
| 7 | **The spend ledger** | the fleet cannot see its own money | **deliberate choice, stated as a trade:** work continues under each node's local allowance, with a loud line saying the fleet total is unknown. We prefer a **bounded** overspend to a stalled night, and the bound is *not* misrepresented as a measurement — the local figure is published as a **lower bound** (`96 §4.1`) | reconcile and publish on a schedule (§3.4); the ceiling is enforced at the step seam, which is local and survives an unreachable authority |
| 8 | **The journal id allocator** | new journal entries are refused rather than mis-numbered | correct as built: it refuses at the window edge with no reachable ref, **writes nothing**, and recovers when the ref returns (`108 §4.4`, §7) | journal writes must never be on the critical path of a turn: a locally-spooled entry plus a 64-id window (§4.4) is the mechanism, and it is already implemented |
| 9 | **The provider** | the model calls fail | measured: 2500 concurrent is 45× the plan and **overflow is a documented, retryable, non-billing 429**, not a silent queue (`96 §1.4`, §0) | not a real SPOF at this scale — and the honest residual risk is the *undocumented* per-minute limiter, which is `ASSUMPTION A8` (§6.1) |

**The single biggest risk in this design** is #2 combined with #1 in their *silent* form, and it is the risk
V9 exists for: a pull queue cannot be blind to load, but it can be **quiet**. If the store stops serving, or
a worker stops claiming while it has capacity, the fleet looks exactly like a fleet with nothing to do —
which is the precise failure this program has already shipped once, when the broker's last placement was nine
hours old and every process was alive (`95 §0`: *"the processes are live; the workload is not"*). The design's
answer is the `stalled` state, a queue that reports "waiting, 0 claimed in T", a worker whose health is
claims-per-minute rather than liveness, and the fleet strip — but it is the one property here that must be
*proved with a deliberate failure*, not asserted (§3.7 V4 and V9).

### 3.9 What I deliberately did not design

* **Elastic cloud.** Two days of work has one measured demand problem (the wallet) and no measured
  *capacity* problem at the fleet's real workload: it has been running at **≈0.16 requests/s, about 0.7
  agents' worth of continuous generation**, against a plan of 55 (`96 §2.4`). Buying capacity before
  removing the waste is the thing the owner's own standing rule forbids
  (`dsh-at-scale/PROGRAM.md`, his words 2026-09-15: *"Focus on getting rid of waste"*). Stream B closed it
  with two facts I did not have: the elastic trigger (`tier != fits` twice, ≥60 s apart) **has never fired
  in the mesh's entire recorded life** — six placements, six `fits` (`88` §6.2) — and the study's own
  cheapest recommended node (CPX11, 2 vCPU) scores **1 slot under the broker's own core term and cannot seat
  the 2-child fleet that is the trigger's minimum**: *"the cheapest plan on the board is not eligible for the
  only job that pays for it"* (`88` §4.2). An auto-firing provisioner on this evidence is, in `88`'s own
  words, *"a mechanism for converting an occasional slowdown into a recurring bill."* The counter that would
  reopen the question is named and cheap — **two or more unplaceable fleets in a rolling seven days**
  (`88` §6.3) — and it starts at zero.
* **Worktrees as a placement mechanism.** Worktrees are how agents are isolated locally
  (`docs/parallel-agent-orchestration.md`), and they are node-local (`20 §1.2`). They are the right tool
  for the *task* unit and they do not become a state-migration mechanism.
* **Live session migration.** Refused by construction (§3.2). Recovery is a procedure, not a feature.
* **A per-node dashboard page.** It is D8's trap: a page served by the node it describes, which will look
  healthy.
* **Hot-mounting, as a research question rather than a plan.** The loader's own claim is that a mounted
  bundle cannot hot-load (`90 §0`, measured) — but **what an autosync rewrite of the live patch layer does
  to an already-mounted host-plane row is not measured anywhere** (`B §Q5`; `100 §10 item 5` names the same
  experiment, and notes the profile sets `"patchReload": "live"`). It is a minutes-long test on a scratch
  `DSH_HOME`. If a live patch-layer rewrite turns out to be safe, §3.6's H class shrinks toward nothing and
  the profile-per-process rule becomes a preference rather than a constraint. I did not design on the
  assumption that it is safe.
* **Turn-level remote tool execution.** It is the only honest answer to "make any turn placeable" (§3.1)
  and it is **unbuilt and unmeasured anywhere**; it is placed in §6.1 as `ASSUMPTION A2` with its test, not
  in the design.

### 3.10 Prior art: what I took, what I rejected, and why

Stream C did the survey (`C-research.md`, 1,264 lines with URLs and read dates). This is the part of it that
touches the design, listed as decisions rather than as reading. The mandate said not to get stuck in old
ways of thinking; the honest form of "not stuck" is naming what the wider field already solved and then
saying which of it applies to four heterogeneous machines, one user, two of them Windows, and a personal
budget.

**Taken, with the mechanism named:**

| taken | from | where it lands |
|---|---|---|
| **Local-first scheduling, spill under overload** | Ray's bottom-up design (`C §3.5`, §10.2) | §3.3.1 — the local decision needs no network; the store is a claim broker, never a decision plane, and a node that cannot reach it still runs what it holds |
| **Per-job spread override** | Nomad (`C §3.3`) | §3.3.8 — spread is a property of the job, with the default argued from this fleet's own measurement (`92 §5.1`) |
| **Reservation before admission, TTL lease, queue position, never a refusal** | Kueue's QuotaReservation → Admission; SQS visibility timeout (`C §9.3`) | §3.3.1 (durable claims), §3.3.3 (gang admission) |
| **All-or-nothing (gang) reservation** | Ray placement groups; Kueue (`C §9.3`) | §3.3.3 — a 6-child fleet reserves 6 or none |
| **Committed-until ranking / projection** | Slurm backfill; SQS visibility (`C §10.2`) | §3.3.8 item 2 — a claim carries an expected end |
| **Ordered shed classes** | Kubernetes eviction order (`C §10.6`) | §3.3.8 item 3 — declared, and it never touches admitted work |
| **A write-maintained index instead of a walk** | Kubernetes' watch cache; and the house's own `journal/index/` (`C §7.3`, §10.4) | §3.2 item 1 — extend the in-house pattern, with the staleness caveat `108 §10.2` already measured |
| **Stale-while-revalidate, as a stopgap** | RFC 5861 (`C §7.2`) | §3.5 — the proxy cache ships, marked as one of six remedies and the only one that leaves the pathology in place |
| **Client/server split; the front door is not the owner** | tmux; JupyterHub's proxy ≠ Hub; Coder's control plane ≠ data plane (`C §9.1`) | §3.8 SPOF 3 — a worker that does not need the resident engine, and a session whose state is its log |
| **Durable log + per-step checkpoints; affinity as an optimisation** | Temporal event history and sticky queues; LangGraph checkpointers (`C §9.5`) | §3.2 item 5 — restartable in place and resumable tasks now; live migration honestly deferred |
| **One durable handle per session, in the URL** | JupyterHub named servers `/user/<name>/<server>` (`C §9.2`) | §3.2 item 4, §3.5 — with the URL half explicitly *blocked on this build* and priced rather than assumed |
| **Idle culling fed by two signals** | JupyterHub's culler (`C §10.1`) | §3.5 item 2 — the proxy already counts live connections per port |
| **Shared user-data-folder, one environment many windows** | Chromium/WebView2's own rule (`C §10.3`) | §3.5 — independent confirmation of the profile fix the house made by measurement |

**Rejected, with the reason — and this list matters as much as the one above:**

* **Kubernetes, Nomad, Slurm, Ray, Kueue, Temporal, Coder, Che, BinderHub and Codespaces *as systems*.** Each
  needs a cluster OS, a control-plane database, or per-workload VMs; two of the four machines run Windows and
  the budget is personal (`C §8`). The *mechanisms* transfer; the software does not.
* **Multi-tenancy and per-user isolation.** One user plus one employee. Any mechanism whose value is
  isolation *between users* buys nothing here (`C §8`).
* **Containers and microVMs.** Not installed, not wanted on the Windows boxes, and single-user isolation is
  not a requirement — but the **warm-pool and snapshot policies** on top of them transfer as process-level
  analogues, and that is the one piece of C's §8 worth keeping in view for a future fleet.
* **VS Code Server as prior art for N concurrent sessions in one engine.** Microsoft's licence forbids
  hosting it as a service and it is single-user by design (`C §8`); this harness's one-engine-many-sessions
  model is *ahead* of it, not behind, and it should not be re-shaped to look like it.
* **A Spawner interface as such.** The abstraction is right and the implementation cost is not: three
  mechanisms stay, and they are made to agree on one contract (§3.5 item 3) instead of being unified.

**The two inversions, restated as the design's answer.** Ray schedules local-first and spills only under
overload where this harness was **broker-first** — with a capacity read measured at **7,342 ms** and the
laptop's own gate at **4.42 s** (`C §10.2`, `95 §1.1`); the design inverts to local-first (§3.3.1). Nomad
binpacks by default **with a per-job spread override**; the harness has only the binpack half, which is
measured to have put the first **seven** of an eight-child wave on the desktop while the laptop sat idle —
and the **eighth** as well, because of the `slow` demotion that the branch removal in §3.3.1 eliminates
(`92 §5.2`, `92 §5.3`). The design adds the missing override (§3.3.8). Both changes are small; both remove
a class of failure the measurements had already produced.

---

## 4. What survives the two days' work

The two days produced **measurements** and **mechanisms**. The measurements are almost all durable; a
minority of the mechanisms are. This table is the honest accounting, and it is deliberately not generous:
the centrepiece of the two days — the broker — mostly dies.

### 4.1 Kept, unchanged or nearly so

| kept | why it survives |
|---|---|
| **The measured constants** — 403 MiB/turn (CI 270–530), 0.62 / 1.68 logical CPUs, commit headroom as the memory quantity, loop-lag max as the first degradation signal, the 14–39 band, ~111 turns to the memory ceiling on the desktop, 8/5/1/3/1 derived limits | `84` in full. This is the most valuable artefact of the program: it turned three invented constants into measured ones and refuted a fourth. The redesign consumes it directly (§3.3.2). |
| **`MESH-HOST:` proof-of-location** | `71 §2.4`: *"A placement system that cannot prove where work ran is an assertion, not a measurement."* Every child states its hostname; the dispatcher verifies it against the node the broker named and **fails the run** on disagreement. It is the one anti-lie mechanism in the program and it works (`92 §5.6`: `MESH-HOST: zabz-tech` with a ledger `reportedHost: "ZABZ-TECH"`). |
| **The gate as the only door**, and the **device allow-list** | `71 §0`: it is deployed everywhere, it restarts freely, and `tailscale serve` forwards `X-Forwarded-For` + identity so the gate can see who is calling. The `/mesh/capacity` route is a **report of measurements**, which is the right job for it. |
| **The lease with a TTL** (`/place` → `/done`, reclaimed at expiry) | The good half of the broker: an atomic claim that cannot be double-spent and cannot be wedged by a dead client (`71 §2.2`). It becomes the queue's claim. |
| **The placement ledger** (one JSON file per placement under `<DSH_HOME>/mesh/placements/`) | Chosen because *"in the `web` profile a host-plane plugin's `ctx.logger.info` goes nowhere durable"* (`92 §4`, measured). Durable, per-child, and the only live surface a queued child has. Keep it, with a bounded ring as `92 §10.5` already proposes. |
| **`plugin-health`**: `/healthz`, loop lag p50/p95/max, the process snapshot, `commitLimitBytes`/`commitAvailableBytes`, the agent census, the governor's lease protocol | `90-plugin-health-governor.md`. It is the sensor layer the redesign's admission reads. The one thing it does **not** publish is `committedBytes` (a subtraction on the consumer side — `109 §5`, recorded as a defect to fix). |
| **`plugin-cost` and the guard design** | Prices to the cent and reconciles to the console (`96 §4.2`: 6,146 requests / $12.0223 in ~15 s); the guard's shape (daily counter, warn → stop fan-out → refuse, failing closed) was designed in `65` and is **not installed**. The redesign installs it and moves its enforcement to the step seam (§3.4). |
| **`plugin-mesh-http`'s derived concurrency arithmetic** | `93 §2.1`: every term traced to `84`, measured 12 requests → 8 admitted, 4 queued, 0 refused, `maxInFlightSeen = 8` corroborated by the OS process list. It is the best-measured thing in the program. **It moves** (into the node's admission controller, §3.3.2) and does not die. |
| **The launcher's shared-profile / per-slot-origin model and the origin proxy** | 892 MB → 60–296 MB per marginal window; 25,371 ms → 29/29/92 ms for the session list; and the insight that *the origin is the window, not the profile*. It becomes the mechanism for session placement (§3.1.1). |
| **The journal's id allocator and `verify-alloc.py`** | `108`: the reservation ledger, `append` incapable of moving a ref, fail-closed at the window edge, 21 checks with 0 failures, and a proof that takes the old rule out of git. It is the model for V4. |
| **The `journal/index/` pattern** | A generated index (`entries.tsv` + a db + a `stamp.json` staleness marker) over ~2,000 entries, with a rebuilder that heals itself — *"the same repository already implements exactly that shape"* (`C §10.4`). It is the pattern the session catalog extends rather than reinvents (§3.2 item 1), **and** its one measured failure (`108 §10.2`: a cache a writer must remember to rebuild) is the rule the session index inherits. |
| **The incident diagnosis and its Appendix B reproduction** | The report is a template for how to write a failure: a timeline with file mtimes, a root cause with the resolution measured both ways, a labelled mask with a rollback, and a one-line regression. |
| **`queue, never amputate`** — for capacity | The owner's rule, correct where it applies. |
| **The two structural patterns an adversarial audit could not break** | `B-assumptions.md` §7 (F4, F5): **never refuse** and **print the arithmetic** — *"both structural (never-refuse, and print the arithmetic) rather than numeric"*, and they are *"the two design decisions in the whole estate that the adversarial audit could not break."* Keep them, extend the arithmetic rule to every decision including every refusal, and keep the never-refuse rule attached to the resource it is true of (capacity). |
| **The `slow`-gate fix and the test shipped with it** | It is V4 in production: a regression whose test fails when the defect is restored. It is a *corrected branch*; §3.3.1 removes the branch entirely, and both belong in the record. |
| **The measurement method itself** | `84`'s sampler discipline (the counter set, the offset-fitted concurrency, the counters that are *not* used), `93`'s two-independent-sources method, and `108`'s "take the baseline out of git, never retype it". |

### 4.2 Rewritten

| rewritten | from → to |
|---|---|
| **The broker** | push-ranking over polled contracts → **pull-claiming over a queue with the worker's own admission**. The API shrinks to: offer, claim, settle, and a position. |
| **The capacity contract** | `mem.swapUsedPct`, `accepts.maxChildren: 12`, `governor.budgetSlots: 24` → **commit headroom**, **logical-CPU budget**, **turns this node has admitted**, **owner reserve** — every field one that can vary, and each one printed with its source. |
| **`mesh-e2e.ps1`** | six steps with three unconditional SKIPs and a done-criterion its own command cannot meet → an **executable contract** where `SKIP` and `UNVERIFIED` are reds unless the contract explicitly names them, and every step declares the reader class it runs in. |
| **`mesh-health.ps1` / `mesh-capacity-probe.ps1`** | literal node lists → **roster-derived**, with the count asserted against the roster. |
| **`mesh-http`'s ceiling** | the transport derives the limit → the **node's admission controller** derives it and the transport asks. Two components deriving a limit from the same constants will drift (and one of the inputs is already a doc example). |
| **The session list** | a 25.4 s walk, cached in a proxy → an **index** (§3.2) with the cache kept as a measured stopgap — *"the fix is one of six published remedies, chosen because it required no engine restart, and it is the only one that leaves the pathology in place"* (`C §7.3`). |
| **The window's identity** | the **port** → the **session handle**. The loopback-origin trick stays as the mechanism that gives a window its own `localStorage` slot; it stops being what the fleet calls a session (§3.2 item 4, §3.5). Without this, C's item 1 stands: the shell is *"a hand-rolled, less capable JupyterHub"* and the two things it is blocked on are addressability and lifecycle. |
| **`ensure`** | a **watchdog** (*"is it up?"*) → a **lifecycle policy**: an idle culler fed by server activity **and** proxy-observed traffic, which closes (never deletes) a quiet session and frees its slot (§3.5 item 2). |
| **The queue's claim table** | an in-memory `Map` that a restart forgets (`C §10.2`, `76-broker.md` §8) → **durable claims** with a TTL, which is what makes "committed until acknowledged" possible at all (§3.3.1, §3.3.8 item 2). |

### 4.3 Deleted

| deleted | why |
|---|---|
| **`score = min(memorySlots, coreSlots)` with `0.75 × physical`** | the memory term is decorative (it caps whenever `freeMiB ≥ 7,725` and every node clears that by thousands — `84 §5.3`, `95 §5.3`), so the score is a core count; and its derivation converts a **paging** observation into a **CPU** budget (`84 §4.3`). |
| **`SWAP_PENALTY_PCT = 90`, and `mem.swapUsedPct` as any kind of signal** | `84 §4.4`: the field is commit-band occupancy; it reads **0.0** until the node is within 410 MiB (desktop) / 1,174 MiB (laptop) of a hard allocation failure; the whole band it reasons about is **2–4 GiB wide**. |
| **`accepts.maxChildren` and `governor.budgetSlots` as published per-node measurements** | constants that cannot vary, one of them derived from a documentation example, one of them consumed by the thing it was declared advisory for (`95 §1.4`). |
| **The `fits` / `highest-slots` / `slow` / `unreachable` tiering and the exclusion of a `slow` node from service** | `92 §5.2`/`§5.3`: measured cost is that the owner's laptop received **zero** children in an eight-child wave while it had more free slots than the node that took all eight. |
| **`160 MiB` as a placement constant** | it is one in-flight tool call inside a turn, not a turn (`84 §4.2`). Keep the number; move it. |
| **`0.81 GB per generating turn`** | refuted by 2.1× (`84 §3.1`) and still live in `dsh-at-scale/PROGRAM.md:75` and **both** `parallel-agent-orchestration` skills (`SKILL.md:135-136`). A refuted constant that a human sizes machines from is a hazard, not a legacy. |
| **"dispatch anyway" on a queue wait that expires** | it cannot distinguish *busy* from *unreachable* at expiry, and a run is not cancelled when the client disconnects (`92 §5.5`, `93 §3`). |
| **`never refuse`, as a universal** | a 999-child request answered 200 with `position 5` and six frames saying it cannot run (`95 §2.4`). Capacity queues; money refuses; a partition queues. |
| **The `secratary` "swap at 99.9 %, halve its slots" note, and the rest of the stale prose in the roster** | `95 §1.1`: the live value was 81.2 % and the broker's own `scoreTerms.swapApplied` was `false` — *"exactly the kind of stale prose that a later reader trusts instead of measuring."* |
| **`-Exclude` used as policy** (a caller hint bent into a routing decision) | `92 §6.1`: *"using `exclude` for that would be this package inventing a policy the broker does not have, and a bad one"*. The local-pressure module already does this deliberately and honestly (`109 §3.2`) — the *rule* stays, the *habit* goes. |
| **A window identified by a port** | `C §9.2`: session choice lives in `localStorage` keyed by origin, so *"two windows on the same port share that one key — last writer wins on reload"*, and nothing is addressable by URL. The port survives as a mechanism; it stops being an identity (§3.2 item 4). |
| **Restart-to-activate as a class** | `B §A12/A13`: the program's own frozen constraint said *"v1 must not require an engine restart"* (`71 §16`) and then five documents shipped changes that need one; the idle window built to take them **has never fired and cannot** (`100 §3.3`, a live refusal at 16–17 loops); and the restart that was taken armed the cold-boot failure. Replaced by profile-per-process plus the isolated-home acceptance path (§3.6 items 0–3). |
| **The three-place coupling** — package link / patch rows / running engine | `100 §11 item 1`, with the measurement that makes it concrete: an installed host-plane row is **silently reverted from `~/.dsh` every 15 minutes unless it is committed** (`100 §5`). Replaced by one composed artefact per boot, verified by one command that can fail, with its identity served beside the running process. |
| **`0.81 GB / 13–14 turns / ~325 MB per window` in the deployed skill copies** | Refuted twice (`84 §3.1`) and still carried **without a correction marker** in five deployed copies — one of them the file every session on this machine actually reads — plus `plugin-mesh-http/README.md:66` (`B §0`). Deleted **and** kept deleted by a keeper (V8, `§5` M0.5). |

---

## 5. Migration path

Each step is reversible, and each carries the gate that proves it did what it says. **"Idle?"** means
*needs the owner's live machine to be free of his own work.* The order follows §2's cost ranking: the
propagation fix is first, the money step happens early because it is the only risk that accrues *while* we
build, and the fleet-size question is last. Only **one** step in the whole table is H-class (§3.6 item 1),
and the cold-boot gate of §3.6 item 3 precedes it — because §3.6 item 0's conclusion is that a change which
needs a restart is a change to be *avoided*, not scheduled.

| # | step | what changes | reversible by | Idle? | the gate |
|---|---|---|---|---|---|
| **M0** | **Roster as data** (S, scripts only) | one machine-readable roster on the authority; every instrument — `mesh-health`, `mesh-capacity-probe`, the probes, the acceptance steps — derives its node list from it; the Mac and `zabz-tech-linux` are in it | revert the scripts | no | every instrument prints a node count equal to the roster's, and **fails** when the roster has a member they cannot read (V1). This single step retires defects 1 and 2 of §3.7 permanently. |
| **M0.5** | **The measured-constants registry and its keeper** (S; scripts + one corrected artefact per consumer) | one machine-readable registry (value, the document that measured it, the date) for the constants that matter — 403 MiB, 0.62 / 1.68 logical CPUs, the commit-headroom basis, the derived limits; every consumer (skill, README, preset, code comment) derived from it or compared against it; **the five deployed skill copies and `plugin-mesh-http/README.md:66` corrected, with the refuted value named inline beside the measured one**; a keeper that runs on the clock and reds on a drifted **deployed** copy | revert the registry; the copies are text | no | the keeper **demonstrably reds** when a constant is hand-edited in a deployed copy and **does not** red on a clean machine (V4: the negative half is the one that matters). This step exists first because V8 is *"the mechanism by which every other wrong assumption survives"* (`B §A11`). |
| **M1** | **The live defects the audit found** (S, no restart) | the fail-open gate on `zabz-tech-linux` gets its allow-list file (`95 §4.2`); the Mac's `web` bundle list loses the row that makes it unbootable (`95 §3.2`); the stale roster notes and `dispatch.v1: null` are corrected from measurement (`95 §3.4`); the journal's `check` learns the ref comparison, in `idguard` not `check` (`108 §10.1`) | each is one file; revert | no (Mac/desktop only) | the foreign-device probe **403s** on all five nodes; `--dump-config` exits 0 on the Mac **and** a cold boot of its engine in a scratch home succeeds; `idguard` reports the 10 collisions `check` could not see |
| **M2** | **The cold-boot gate** (S, a script) | the four-part gate of §3.6 item 3, run once per **reader class**, runnable by hand and by the deployment path; plus the incident's Appendix B one-liner as its regression | script only | no | the gate **catches the boot failure deliberately re-armed** (unset `DSH_HOME`, broken anchor) and refuses activation; and it passes on the current good tree. This is the checkpoint the one H-class step depends on. |
| **M3** | **The money guard** (P for fleet processes; H **only** for the resident engine) | `guard.mjs` mounted in the profile, ceilings set, the counter in the fleet strip; enforcement at the pre-step seam; the ledger reconciled against the console export and the reconciliation published | un-mount the row; revert the ceilings | **no** — it activates in every **fresh** process immediately; the resident engine is a separate, optional, validated activation (M2) whose lag is *shown*, not waited on | a synthetic step at the ceiling closes the turn `blocked` and **spends nothing**; a day's ledger reconciles against the export within the published bounds, and the **lower-bound** label is on the number (A5) |
| **M4** | **The queue, in observe mode** (S, new process) | the queue store — **durable claims with a TTL, atomic claims, and gang reservation** — plus a worker that **claims nothing** and prints, per node, the admission decision it *would* have made, with its arithmetic | kill the process | no | run it on the laptop at 124 % of physical and confirm it says **0 slots** where the broker's own rationale said **12 free** (`109 §1`), reproduced as a test; **and restart the store mid-flight** and confirm every live claim is still held (the property the in-memory `Map` lacks, `C §10.2`) |
| **M5** | **Shadow** (S) | the same callers feed the queue *and* the broker; disagreements are recorded per job | stop feeding | no | zero unexplained disagreements on capacity; every remaining one is explained by a named field |
| **M6** | **Flip one class** (S) | one-shots (`subagent` dispatches) go through the queue; the broker keeps fleets | config key | no | `93 §2.1`'s rig reproduced: 12 concurrent requests → 8 admitted, 4 queued, **0 refused**, positions in **arrival order**; the node's own `maxInFlightSeen` agrees with the OS process count; and a **6-child gang either reserves 6 or is queued whole** — never five-of-six (the case `92 §5.3` had to simulate by hand) |
| **M6.5** | **The enforcement seam** (S, preset layer) | the provider wrapper of §3.3.7: every provider's `start()` passes this node's own admission first, then the queue, then a refusal that names the reading; `subagent_local` and `subagent_fork` stop being an unguarded bypass | remove the wrapper row | no — a preset change is live at the next session (`94 §6`) | **all four** provider names are shown passing through the same decision, including a saturated machine refusing its own local spawn with the reading named — the measurement `109 §6.1` records as not existing (A11) |
| **M7** | **Session placement + the fleet strip** (S, launcher + proxy) | a slot's origin can point at another node's engine, per-slot opt-in; the strip shows nodes, queue, wallet, and which node owns each session, from the catalog | per-slot config key; `profileMode` | a quiet moment (it is the thing that opens his windows) — **and it is client-side, so it still needs no idle window and no restart** | one real task in a session created on `zabz-tech` from a laptop window, with the laptop's commit and CPU **measured flat** across it; the catalog shows the session's node; and killing the proxy leaves the direct URL a working fallback (SPOF 5) |
| **M7.5** | **Addressability and lifecycle** (S for the handle and the cull policy; H **only** if the URL form is taken engine-side) | the catalog handle becomes what every surface names a session by (§3.2 item 4); the launcher maps handle → slot; a declared cull policy closes (never deletes) a session idle by **both** signals past T, fed by the proxy's per-port connection count and the engine's activity (§3.5 item 2); the URL form of the handle is implemented **only** if A12 says one of the two paths works | remove the cull policy; the handle is data | no for the handle and the cull policy; **yes, one H-class activation, only if** the engine-side URL route is chosen — and then behind M2 | a window is opened **by handle** and lands on *that* session after a reboot (the case `ANALYSIS-AND-DECISION.md` §3 records as unsolved); a quiet session is culled after T and **re-opens with its history intact**; and the cull policy is shown **not** to fire on a session that the *server* sees as idle while the *proxy* sees traffic, or vice versa (A13) |
| **M8** | **Delete** (S + one H to unmount) | the broker's ranking path and its tiering; the fields of §4.3; the queue-expiry-dispatch rule | revert | no | `grep` finds no consumer of any deleted field; the acceptance suite passes **with the broker stopped** |

**Three notes on the path.**

1. **Nothing is deleted before nothing reads it.** M8 is last on purpose: `95 §5.4` shows what happens when
   a field is published, read into a data structure, printed, and never consumed — deleting it earlier
   would destroy the evidence that it was inert.
2. **No step in this path needs the owner's machine to be idle, and that is a deliberate correction of the
   last two days.** B established that the idle window this program was built around **has never fired and
   cannot** — it declines on any non-zero `agentLoopsRunning` and his fleet is always running
   (`100 §3.3`), so a step that waits for one is a step that never happens, which is the measured history
   of five documents (`B §A12`). M3's activation is profile-scoped and therefore immediate for every fresh
   process; M6.5 and M7 are preset- and client-side; only M8's single H-class act touches the resident
   engine, it is protected by M2, and it is the owner's to schedule or decline **without blocking anything
   else in this table**.
3. **The path is network-first, not code-first.** M0–M2 retire the two *domain* failures outright (rows 1 and
   2 of §3.7), install the reader-class rule that row 7 needs, and fix the two most likely 24-hour
   breakages (`95 §7b`: the Mac's un-bootable engine, and the fail-open gate) — all before a line of the new
   architecture exists. That ordering is deliberate: the redesign's first obligation is to stop the bleeding
   it inherited.

---

## 6. Honesty

### 6.1 Assumptions I added, each with the measurement that would test it

| id | assumption | what would test it |
|---|---|---|
| **A1** | A node worker can count the turns it admitted, accurately enough to be the admission input | run N = 8 children from the worker and compare its count against the target's own process list — the method `93 §5.1` used, where the node's `maxInFlightSeen = 8` and the OS process count agreed. A worker that also *spawns* has a stronger position than the engine, which `84 §5.2` proved cannot see dispatched children. |
| **A2** | Remote tool execution would reduce a tool-heavy turn's local cost toward the model-bound figure (1.68 → ~0.62 logical CPUs) | the `84` rig, same prompt class, local tool execution vs remote, measuring `\Processor(_Total)\% Processor Time` and commit per turn. **This is the measurement that decides whether turn-splitting is ever worth building** (§3.1). |
| **A3** | A pull queue drains as fast as push placement at equal capacity | `93 §2.1`'s rig re-run against the queue: 12 and 32 concurrent jobs, compare time-to-admission and total wall time, and confirm `0 refused` with positions in arrival order |
| **A4** | Session placement to another node is usable when that node has the workspace | one session created on `zabz-tech` via a loopback origin, one real task, the laptop's commit and CPU sampled across it, and the resulting work merged cleanly — plus the *negative*: the same test on a repo that exists in divergent state on both machines, to price the divergence risk |
| **A5** | The money ledger's lower bound can be made accurate enough to enforce a ceiling without lying | one day of reconciliation against the provider console export, publishing the ratio (the one existing reconciliation was 50 % of misses / 76 % of hits — `96 §4.1`), and a deliberate test that the enforcement path refuses at the ceiling |
| **A6** | Replicating session logs to the authority is sufficient for fail-closed recovery | kill a node mid-session; recover on another node; verify (sequence, sha) and that `dsh` opens the session; then corrupt the last frame and confirm the recovery **refuses** rather than resuming |
| **A7** | A cold-boot gate in a scratch home catches the class of failure that bricked the engine | re-arm the incident's exact defect (unset `DSH_HOME`, wrong anchor) and confirm the gate refuses activation and names the failing import — the incident's Appendix B, turned into a test |
| **A8** | The provider's real limit at 55 is a *latency* effect, not a 429 storm | one metered hour at N = 32–55, watching time-to-first-byte rather than error codes — `96 §6.2` names this as the honest open question and the reason it is worth a deliberate yes rather than an agent's decision |
| **A9** | A fleet session **catalog** (an index) beats a network-backed shared session store | time `listArtifacts()`'s walk over a network-backed store against the measured local figure — **5.9 s of raw filesystem work for 681 sessions on local NVMe** (`MEMORY-AND-SESSION-LIST.md §2`, and `>40 s` through the engine at 17 loops, `100 §2`). This is stream B's Q4 and it is free to take. If a share is fast enough, §3.2's recovery path gets much cheaper and the catalog becomes a convenience rather than the fix. |
| **A10** | A constants keeper (V8) actually catches drift in deployed copies | hand-edit one constant in a deployed skill copy on one machine and confirm the keeper reds on its next tick, **and** that it does not red on a clean machine — the negative half is the one that matters (V4). |
| **A11** | The provider-seam wrapper can see and gate **all four** providers | call each of the four names from a saturated engine and confirm each reaches the same admission decision, with `spawn` and `fork` refused or queued and the reading named — the measurement `109 §6.1` records as not existing. |
| **A12** | A session **handle in a URL** can be made to work on this build, by one of two paths | the blocking facts are measured (`C §9.2`): zero `pushState`/`hash`/`sessionId` across all 65 client bundles, pathname-only routing, and a `?token=` exchange that **303s to literal `/`**. So the test is direct: (a) open `/?s=<known-id>` and see which session the page lands on (expected: **it is discarded**, and that is a *result*, not a failure); (b) boot an engine on a scratch `DSH_HOME` with a route that honours a handle, and (c) have the origin proxy inject the handle into the page it serves. Whichever of (b)/(c) lands the window on the named session is the path; if neither, the handle stays catalog-only and the launcher keeps mapping it, which is still strictly better than a port. |
| **A13** | Server activity **and** proxy-observed traffic together are a sufficient idle signal for culling | run a session that is idle from the server's point of view while the proxy sees an open connection (a window left focused, no prompts sent) and one that is the reverse; the cull policy must fire on the first and not the second. JupyterHub's two-signal culler is the published model (`C §10.1`); the proxy already counts live connections per alias port (`MEMORY-AND-SESSION-LIST.md §4`), so the signals both exist. |
| **A14** | Gang admission does not cost throughput at this fleet's shape | `93 §2.1`'s 12-request rig re-run with 6-child gangs: confirm nothing is refused, that no gang starts partially, and that wall time is not worse than the per-child placement it replaces (the risk is a 6-slot reservation idling 5 slots while a fifth child spins up). |

### 6.2 Uncertainties I will not paper over

1. **The laptop's own curve does not exist.** The constant the production system actually used —
   `floor(16 × 0.75) = 12` — was never validated on the machine it was used for: the laptop crossed the
   program's own 26 GB stop line **before any fleet was dispatched** and ended 10 GiB further into
   pressure with the program's own streams running (`84 §1.1`, §6.1). My admission function inherits that
   uncertainty on the one machine the owner sits at, and the measurement that fixes it is cheap and
   specified (`84 §6.1` item 1: run the rig from the desktop against the laptop, N = 2…8, ~6 minutes,
   ~90 turns, after the laptop is back under ~12 GiB of commit).
2. **Two nodes have no capacity surface at all** — `secratary` and `zabz-tech-linux` have no `/healthz`
   and no `Get-Counter` (`84 §6.2`). Their numbers in `93 §2.2` are **arithmetic, not measurement**, and
   the authority is the node where the derivation matters most (4 cores → limit 1).
3. **Nothing above 8 concurrent turns has ever been measured** (`84 §6.3`), and **55 has never been run**
   (`96 §3`, `93 §10.8`). Every "at 55" number in this document is an extrapolation of a measured
   8-point curve and a 32-request ramp. I have marked them as such rather than presenting them as
   measured.
4. **The cost per turn is a mean over a heavy tail**, and `96 §4.1` says so in its own words. Budget
   arithmetic that treats it as a constant will be wrong on exactly the sessions that matter.
5. **macOS's memory quantity is not the same quantity.** On darwin the gate reports *reclaimable* where
   Windows and Linux report *available*, and nothing in the contract says which — `95 §1.1` measured the
   Mac reporting `freeMiB 7067` where the actually-free number was **133 MiB**. `93 §10.6` records the
   same gap for the derived limit. If the Mac ever becomes a real worker, its memory term must be fixed
   before its slots are believed.
6. **The `slow` reading on the laptop's gate is real and unexplained.** Measured `ok`, `slow`, `ok` over
   three consecutive fresh reads while the machine ran the owner's engine (`92 §5.2`). My design removes
   its *consequence* (no tier to be dropped from) without explaining its *cause*, and a slow gate is still
   a slow fleet strip.

### 6.3 Refusals

* **I measured nothing.** Every number here is quoted from a named document with its own date and method.
  Where two documents disagree I have said so rather than choosing: `84 §1.5` estimates **~$0.007/turn**
  and `96 §4.1` computes **$0.0042/turn**, and `96` reconciles them honestly — *"84's figure is a floored
  estimate and mine is a mean"* — which is the right resolution and I have adopted it.
* **I did not verify any of the quoted measurements myself.** A design document that re-derived them would
  cost more than it is worth, and re-deriving a measurement you are not set up to take is how the
  "confident wrong number" gets made. One measurement is quoted from stream B rather than from a document
  that measured it: the laptop's own numbers taken this session — **27,141 MiB committed of a 44,149 MiB
  limit, 222 MiB of pagefile in use (1.9 %) at 84 % of physical committed** (`B §11`). It is the reading
  that settles "is this machine paging" in the negative, and it is attributed.
* **The zero-placement counter is unsourced in the brief's form, and I will not carry it as a measurement.**
  The brief I was given says *"zero placements in 80 minutes"*; the repository says **nine hours with the
  processes live and the workload not** (`95 §0`) and *"no placement all day"* (`109 §1`). Stream B
  searched `docs/**` and `journal/**` for the 80-minute form and found no match (`B §9.1`). Two local,
  free commands settle it — `ls -la ~/.dsh/mesh/placements/ | wc -l` plus a timestamp histogram of
  `~/.dsh/mesh/logs/*.jsonl`. Until they are run, the sourced claim is the one I cite.
* **I inherit B's eight open questions rather than restating them.** `B-assumptions.md` §8 lists them with
  command sketches and costs: the laptop's own curve; whether the mesh reduces load once the pressure path
  is live; tool choice versus the `slow` demotion; the network-store walk; whether a live patch-layer
  rewrite disturbs a mounted host-plane row; the exact bill; the logical→physical conversion under SMT;
  the cross-tree id detector. Three are named above as `A1`, `A9` and `A11`; the rest are unchanged and I
  have not duplicated them. **Three of B's five unsourced items in its §9 are also still unsourced**, and
  two of them matter to this design: *"the owner's 12–18 sessions are the load"* has **~15 GB
  unaccounted** between the measured browser, engine and MCP footprints and the machine's commit charge
  (`80-windows-and-parity.md §6.1`) — which is the single most useful free measurement on this laptop — and
  *"idle browser windows are cheap"* is falsified in B's own reading (0.24–0.28 core, 467–783 MB private
  each), which §3.5 now states.
* **Where stream C's research is unverified, I lean on mechanisms rather than numbers.** C's own §11 lists
  ten things it could not verify — among them **Slurm's atomic all-or-nothing allocation** (its "gang
  scheduling" page describes timeslicing), the **current browser limit on WebSocket connections per host**,
  and E2B's and Modal's vendor claims. The design takes the *mechanism* those systems are known for (gang
  reservation, the watch cache, local-first spill) and takes **no number from any of them**; every figure in
  this document comes from this repository's own measurements, which is the only population that describes
  these four machines.
* **The addressability blocker is stated rather than engineered around.** A session handle in a URL is not
  available on this build (zero `pushState`/`hash`/`sessionId` across 65 client bundles, pathname-only
  routing, and a token exchange that 303s to `/` and discards query parameters — `C §9.2`). §3.2 item 4 and
  `ASSUMPTION A12` give the two paths and the measurement that decides; I did **not** assume either works.
* **One input this design cannot obtain by itself:** the exact bill needs a provider **console export**
  (`B §Q6`; `60-cost-audit.md §8.3` — *"no usage API exists"*). That is a credential/artefact question
  rather than a design or taste question, and it is the single thing in §3.4 whose accuracy depends on
  something only the owner can produce. It is not raised as an owner *decision*; it is recorded as a
  dependency.
* **I did not price the migration.** No estimate of hours or dollars is given, because every hour estimate
  in this system's history has been wrong in the same direction and the steps are defined by their gates,
  not their duration.
* **I did not design the company-facing side.** The authority also runs `personal-secretary-mvp` (618
  routes, 203 tables, 18 agents, ~300 ticks/day) on the same 4-core box that §3.8 makes the queue store.
  Whether the queue store belongs there, on a second box, or on a `systemd`-supervised static file store,
  is a real question I have not answered — and it is a **development** decision with a measurement behind
  it (the authority's own I/O and swap behaviour under the queue's load), not an owner question. Assigned
  to whoever builds M4.
* **No owner decision is raised by this document.** The three candidate questions inside it — "should
  non-urgent work be deferred into off-peak pricing?", "should the laptop ever take remote work?", "how
  much may a night cost?" — each has a defensible default (no; only in its reserve-free band; and the
  guard's ceilings, which are his to set only if he disagrees with `96 §5`'s recommendation), and per
  standing rule a defensible default is decided and recorded, not queued.

---

## 7. The report

**The thesis, in three sentences.**

1. **Capacity is local and pulled; money is global and granted — and the decision is local-first, so no
   round trip stands between a machine with room and the work it can do.** A node cannot be blind to its own
   load, so the only component entitled to decide whether a node has room is the node itself: a queue that
   workers *claim* from (the queue being a claim broker, never a decision plane), with the node's own
   admission as the only gate and the wallet as the one resource that is granted centrally and refused when
   empty.
2. **State stays where it is and is indexed everywhere.** A session can never move — the write lease is a
   per-machine kernel object with no cross-host arbiter — so the design stops trying to move it and instead
   (a) *places new sessions at creation*, which the launcher can already do because the client's connection
   follows the window's origin, (b) *indexes every session's node in one fleet catalog*, extending the
   in-house `journal/index/` pattern rather than inventing a second one, because a session list built by
   walking one node's disk is linear in stored sessions and already takes 25 seconds, (c) gives every session
   **a durable handle** so the window stops being the identity, and (d) *recovers* a session onto another
   node as a fail-closed procedure, never as a live migration.
3. **Every decision is a measurement with its source and its age, every check ships with a demonstrated
   failure, every policy is enforced where the resource is owned rather than where a tool name requests it,
   and every fact that must stay true gets a keeper rather than a document** — because this system's two
   dominant failure modes are a confident wrong number and a green check over a broken thing, not a crash,
   and because a corrected constant that never reaches the copies that act on it is the mechanism that keeps
   every other mistake alive.

**What I keep.** The measured constants (403 MiB/turn, 0.62/1.68 logical CPUs, commit headroom, loop-lag
max as the first degradation signal); `MESH-HOST:` as the proof of where work ran; the gate and its device
allow-list as the only door; the lease-with-a-TTL as the atomic claim; the per-placement ledger files;
`plugin-health` and `plugin-cost` and the uninstalled guard's design; the derived concurrency arithmetic
from `plugin-mesh-http` (moved into the node); the launcher's shared-profile / per-slot-origin proxy and
its session-list cache (as a stopgap); the `journal/index/` pattern, which becomes the session catalog; the
journal's id allocator and its 21-check proof; the incident diagnosis and its one-line regression;
`queue, never amputate` — for capacity; and **the two structural patterns an adversarial audit could not
break: never refuse (scoped to capacity) and print the arithmetic (extended to every refusal)**.

**What I delete.** `score = min(memorySlots, coreSlots)` and `0.75 × physical` cores; `SWAP_PENALTY_PCT`
and `mem.swapUsedPct` as any kind of signal; `accepts.maxChildren` and `governor.budgetSlots` as published
per-node measurements; the `fits` / `highest-slots` / `slow` tiering, and with it the branch that inverted
the routing property on the machine the owner uses; the 160 MiB slot as a *placement* constant; the
refuted **0.81 GB / 13–14 turns / ~325 MB per window** in `PROGRAM.md` and in the five deployed skill
copies; "dispatch anyway" when a queue wait expires; `never refuse` as a universal; the stale roster prose;
`-Exclude` used as policy; **a window identified by a port**; an in-memory lease table that a restart
forgets; a watchdog in place of a lifecycle policy; **restart-to-activate as a class**, and with it the
three-place coupling (package link / patch rows / running engine) that a 15-minute autosync silently
reverts.

**The single biggest risk in this design:** a pull queue cannot be blind to load, but it can be **quiet** —
if the queue store stops serving or a worker stops claiming while it has capacity, the fleet looks exactly
like a fleet with nothing to do, which is the failure this program has already shipped once (nine hours
idle, every process alive, `95 §0`). The design's answer is the `stalled` state, a queue that reports
"waiting, 0 claimed in T", the fleet strip, durable claims a restart cannot forget, and V4's rule that a
check must be *shown* failing — and it is the one property in this document that must be proved by
deliberate failure rather than asserted.
