# 111 — Placement: what decides where a child runs, with the numbers we actually measured

Deliverable 2 of the mesh goal. Written 2026-09-18 from ZABZ-YOGA. Every number here is a reading with
a date; where a number is missing the text says so rather than filling it in.

## 1. The property we are buying

> *"when I use DSH it is speedy without any lagging … because it offloads properly"* — the owner.

That sentence has two halves and they need different mechanisms:

- **"offloads properly"** is a PLACEMENT problem: put the child on a machine that has room.
- **"speedy without lagging"** is a LOCAL problem: the machine he is sitting in front of must not be
  doing work that another machine could do. Placement alone does not buy this; a laptop can be busy for
  reasons that have nothing to do with agents (browser windows, MCP servers, the engine itself).

Most of this programme's design effort has gone into the first half. The second half has one measured
sensor (`pressure.js`) and no budget for anything else yet, and saying so is more useful than implying
otherwise.

## 2. The inputs a placement decision may use — measured 2026-09-18 15:00Z

| node | cores | memTotal MiB | memFree MiB | commitFree MiB | disk free GiB | node | engine:3099 | role |
|---|---|---|---|---|---|---|---|---|
| `laptop-ts` ZABZ-YOGA | 22 | 32373 | 13678 | 20812 | 48.4 | v24.12.0 | yes | the machine he uses |
| `desktop-ts` ZABZ-TECH | 32 | 65173 | 38761 | 39504 | 185.5 | v24.19.0 | yes | the workhorse |
| `secratary-ts` | 4 | 23421 | 15349 | advisory | 134.8 | v20.20.2 | no | authority; 4 GiB swap **100 % full** |
| `linux-pc-ts` | 12 | 11673 | 10329 | 4666 | 20.9 | v22.23.2 | yes | `dsh` on PATH |
| `mac-mini-ts` | 10 | 16384 | — | — | 46.0 | v24.19.0 present | yes | fifth node; PATH blocks dispatch |

Node-to-node cost, measured from `desktop-ts` (the only direction measured so far): `mac-mini-ts`
205 ms, `linux-pc-ts` 315 ms, `secratary-ts` 522 ms, `laptop-ts` 1069 ms. From the laptop the same
five nodes answer in 0.7–3.4 s including a full probe, so **dispatch latency is tens to hundreds of
milliseconds, not seconds** — it is not a reason to keep work local.

**What is missing, and must not be invented:** per-node *cost of one agent turn*. The one datum that
exists is a whole child turn of 449 s and one of 504 s on `desktop-ts`, both `exit 0`, both doing many
tool calls. That is a duration, not a unit cost. The laptop's unit cost — **403 MiB of commit per
concurrent turn, CI 270–533** — remains the only calibrated figure, and it is the one the thresholds
are built on. Until the other nodes are calibrated the same way, placement between *remote* nodes is
ranked on capacity, not on measured cost.

## 3. The rules, in the order they apply

1. **A reading that could not be made never changes a decision.** `pressure.js` returns
   `band: 'unknown'` and the dispatcher behaves exactly as it did before the check existed. This is not
   a nicety: today's four false conclusions (see `109`) all came from treating an unmakeable reading as
   a negative one.
2. **The local machine is the default and the mesh is the offer.** Below the high line (85 % of
   physical committed on this host) the local node is not excluded; at or above it the local node is
   excluded from the ranking, which is *how* the work is offered outward.
3. **Refusal needs two conditions, not one.** `commit/physical >= 0.92` AND `< 1.5 GiB available`. The
   ratio alone exceeds 100 % on this laptop while 7.4 GiB of commit headroom and 7.6 GiB of physical
   are free — a one-condition rule would refuse work on an idle machine.
4. **The mesh being unreachable changes the answer, not the intent.** Above the high line with no
   broker, nothing is dispatched and the error says why, rather than dispatching locally after having
   just declined local.
5. **Small and long beats big and short on a constrained node.** `secratary` may host a child of
   hundreds of megabytes; it may not host a multi-gigabyte one. Its binding limit is 216 kB of free
   swap, not its commit figure.
6. **A node is not a capability.** `dsh` on PATH is false on four of five nodes by design; `node` on
   PATH is false on the mac mini's non-interactive shell while two runtimes exist on disk. Any rule
   keyed on "is the binary on PATH" is wrong on this mesh.

## 4. Queueing instead of caps — the failure this programme was actually born from

The owner's instruction of 2026-09-15 was to make long work *queue* rather than be cut off, and the
measured history is unambiguous: a provider-level cap of 300 s severed five fleets in one night
(`D267`), while the transport underneath it was willing to wait 900 s. The pattern to enforce:

- **bounds live at the edges, not in the middle.** A child turn is bounded by the transport that
  carries it (now 1800 s, overridable), and a *machine* is bounded by the governor (`admission_governor`,
  memory-derived, never refuses — it queues).
- **a queue position is information, not a failure.** The broker already returns
  `position 0 (tier fits) … started immediately`; a queued placement must surface its position the same
  way, so a slow start is legible instead of looking hung.
- **nothing long should be *held* inside a turn.** A turn that blocks for 20 minutes is a turn the
  owner watches do nothing. Long work goes to a background job and is polled — with
  `enableRunInBackground: true` a mesh child now returns a durable id immediately, which is what makes
  this possible for fan-out at all.

## 5. Phased implementation, each phase with its own measurement

**Phase 0 — prove the fifth node works, then calibrate it.** **CORRECTED before it was implemented, and
the correction matters more than the phase.** The first version of this paragraph asserted that
`mac-mini-ts` is unplaceable because its non-interactive PATH lacks node. **That is false.**
`lib/nodes.js` already carries the per-node interpreter
(`lakewooechsmini: driver: '/usr/local/bin/node'`, `bin: '/Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js'`),
and the provider invokes those **absolute paths**, so the non-interactive PATH is irrelevant to a
dispatch. The PATH problem was a defect in my *probe* (`109`), never in the mesh — the node table had
this right too. What the row does say is that it has **never been exercised as a worker**, so the honest
next step is not a fix but a TEST: run one real child turn against `lakewooechsmini`. Done when a
child's own `MESH-HOST:` line names that node, or when the failure names a concrete blocker.

**MEASURED OUTCOME, SAME DAY, AND IT DID NOT PASS.** The test was run correctly this time — a local
child was told to dispatch exactly one subagent, so that the target actually carried by the environment
(`MESH_TARGET_NODE=lakewooechsmini`) would be exercised. Result:

- the run itself looked fine: `exitCode 0`, `timedOut false`, `ms 15188`;
- the dispatched child reported **`MESH-HOST: zabz-yoga`** — the laptop;
- `mesh-run`'s verify phase scored `childHosts: ["zabz-yoga"]`, `disagreements: ["zabz-yoga"]`,
  `outcome: "failed"`, `reason: "location disagreement: zabz-yoga not on lakewooechsmini"`, exit 1.

So **a dispatch aimed at the mac mini produced a child that ran on the laptop.** The tool caught it,
because it verifies the child's own report of where it ran rather than trusting its own intent — that
verification phase is the reason this was not written down as a success.

The likely cause is consistent with the evidence but is **not proven**: the fixed-target default in
`profiles/mesh/cordis.patch.yml` is `process.env.MESH_TARGET_NODE ?? 'laptop-ts'`, and `laptop-ts`
resolves to `zabz-yoga` — exactly the hostname observed. That would mean the environment override was
not honoured and the row fell back to its default node. The alternative — that the override was honoured
and the placement still landed locally — has not been excluded. Either way the mac mini remains
**unproven as a worker**, and there is now a reproducible silent mis-placement to chase. This is the
same failure class as the `laptop-ts` scare of 2026-09-17 and it deserves to be fixed before any
twelve-hour fleet is aimed at a node list.

**Phase 1 — calibrate the remote nodes.** Measure commit-per-concurrent-turn on `desktop-ts` the way
403 MiB was measured on the laptop. Until that exists, "the desktop has more room" is arithmetic on a
different machine's units.

**Phase 2 — make the local half of the promise measurable.** "Speedy without lagging" is currently
asserted, not measured. The laptop's engine already reports loop lag p50/p95/max and tool-runner
counts; capture them while the owner is working *and* while a fleet runs, and publish the difference.
If a fleet changes his numbers, that is a finding; if it does not, that is the evidence he is owed.

**Phase 3 — the scheduler proper.** Only after 1 and 2: rank nodes on measured unit cost and free
capacity, queue rather than refuse, and record every placement with its reason so the ledger can be
read back.

**Explicitly out of scope until Phases 0-2 are done:** a costed hardware plan. A recommendation to buy
RAM or nodes is not defensible while the only calibrated machine is the one that feels slow — the
measurement would be recommending hardware to fix a placement problem.

## 6. Measured after this document was written: where children ACTUALLY land

Three dispatches were run on 2026-09-18 while four fan-out children occupied `zabz-tech`. **All three
produced a child on the owner's laptop**, and each had been believed to be aimed somewhere else:

| what was asked for | what the child reported |
|---|---|
| `mesh-run -Node lakewooechsmini` | `MESH-HOST: zabz-yoga` |
| `mesh-run -Node secratary` | `MESH-HOST: zabz-yoga` |
| `--profile mesh` with `MESH_TARGET_NODE=secratary-ts` in the **real** process environment | `MESH-HOST: zabz-yoga` |

`mesh-run`'s verifier caught all three (`location disagreement`, exit 1). Two defects, and they must not
be conflated:

**(a) The fixed target never takes effect — root cause not established.** The installed
`~/.dsh/profiles/mesh/cordis.patch.yml:76` is
`target: !!js "process.env.MESH_TARGET_NODE ?? 'laptop-ts'"`, and every observed result is exactly the
**fallback** `'laptop-ts'` — the laptop's own alias. Either the `!!js` expression is evaluated somewhere
that cannot see `process.env`, or `--profile mesh` is not what mounts. Not distinguished; the
discriminator is the child's own boot log. Established: `-Node` constrains nothing.

**(b) The policy gap, and this is the answer to the owner's complaint.** Even in pure broker mode the
placement was **correct by the rules as written**: `pressure.js` excludes the local node only at or above
85 % of physical commit, and the laptop sits far below that. With `zabz-tech` carrying four children the
broker balanced onto the next node with room, and that node was the laptop. **There is no mechanism at
all for "the owner is using this machine right now."** A policy that treats his laptop as an ordinary
worker below the 85 % line will keep putting agents on the machine he is looking at — and adding
capacity elsewhere does not fix it, because the biggest node fills first.

**The change this demands, and it belongs in `pressure.js`:** a *presence* input. The engine already
knows when a session is active and already measures its own loop lag; "the owner is present" should raise
the local machine into the high band regardless of commit, with the reason spelled out in the decision
line so a placement can be explained afterwards. Everything needed to express this already exists — the
band vocabulary and `routeAwayFromLocal` — only the input is missing.

**Phase 1 of the plan below is therefore reordered: presence precedes calibration.** Measuring per-turn
cost on the remote nodes is still needed, but the number will not matter while the local machine can win
a placement outright.

## 7. Hazards that must be in every future brief, because they have each already cost a child

1. **Piped stdout hangs ssh on a Windows node.** Inline `& ssh` and `Start-Job { & ssh … }` never
   return there; `Start-Process -RedirectStandardOutput <file>` completes in under 1.1 s. Two children
   died to this in one hour, and one of them reported the node as unreachable.
2. **An empty result is not a negative result.** `command -v node` blank, `ss -ltn` zero rows, a commit
   figure — four wrong conclusions today, all from reading a blank as a fact.
3. **Bound every hop.** A child that hangs holds the parent's work. A partial matrix is a deliverable;
   a complete one obtained by waiting is not.
4. **Verify the node that answered.** Every hop must print the remote `hostname`; an alias that lands
   on the wrong machine has already happened once in this repo's history.
