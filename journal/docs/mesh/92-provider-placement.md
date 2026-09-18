# 92 — Provider placement: the child goes where the broker says

**Program:** `docs/mesh/` (the provider seam of `66-dsh-remote-capability.md` §3.4, mounted by
`90-provider-mount.md`, and the deliverable `71-mesh-program.md` §5 left as *"choosing BETWEEN nodes
is the broker's decision, not a row's"*). **Date:** 2026-09-17 (13:00–14:00Z).
**Author:** a delegated build session, not the owner.
**Reads with:** `76-broker.md` (the live API), `71-mesh-program.md` §2.2 (the frozen contract),
`90-provider-mount.md` (the mount this changes), `91-resident-dispatch-proof.md` (the dispatch proof
this extends).

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the
command given. **READ** = read out of source, with `path`. **REFUSED** = asked for and not obtained,
stated as a refusal rather than as a silence. Every number below carries the run that produced it.

**What was NOT done.** No engine was started, stopped or restarted on the owner's home. The owner's
engine (**pid 4880**, `dsh web`, started 08:51 local) was verified alive before this session's first
command and after its last. Nothing was published: the live patch layer is the only file outside the
repo this session touched, it is inert until a restart, and it was written by the installer's own
documented path. No `git commit` was made (the tree keeps its uncommitted state, which is how it
arrived).

---

## 1. The defect, in the owner's terms

The provider row named **one** node:

```yaml
target: !!js "process.env.MESH_TARGET_NODE ?? 'desktop-ts'"
```

with the comment *"THE TARGET IS ONE NODE, DELIBERATELY. A provider row names one ssh destination —
choosing BETWEEN nodes is the broker's decision, not a row's."* The mechanism existed and was
deliberately not wired: every child of every session in the engine went to `desktop-ts`, whatever the
mesh looked like, so the mesh never got a say.

The owner's plan is what makes that fatal rather than untidy: he intends to open ten windows with
several agents each — on the order of **55 concurrent agents** — against measured ceilings of ~12
concurrent generating turns on the laptop, ~18 on the desktop, ~7 on the Mac Mini. With a fixed
target, all 55 land on one machine and the rest idle, which is the opposite of what the hardware was
bought for.

**What replaces it, in one sentence:** before each child the provider asks the live placement broker
where this child should run (`POST /place`, over ssh to the broker's loopback-only port), dispatches
to the node the broker names, and gives the lease back when the child settles (`POST /done`).

---

## 2. What was built, file by file

| file | what it is |
|---|---|
| `packages/plugin-remote-fanout/lib/nodes.js` | **new.** The mesh node table — ssh alias, allowed hostnames, shell, node/dsh paths, working directory, and when those were last measured — keyed by the name the BROKER uses. Moved out of `bin/mesh-run.mjs`, which carried it alone. Two copies of this table would drift, and the drift is invisible until a child lands somewhere it cannot run. No imports, no I/O. |
| `packages/plugin-remote-fanout/lib/broker-client.js` | **new.** One bounded `ssh` to the authority running a `curl` against the broker's loopback URL: `place()`, `done()`, `nodes()`, `healthz()`. A failure is a typed `BrokerError` (`broker-unreachable`, `broker-unparsable`) — never a default answer. |
| `packages/plugin-remote-fanout/lib/placement.js` | **new.** `createNodePlacer` (asks the broker, waits when queued, builds the placed node's transport, releases the lease), `createFixedPlacer` (the opt-in one-node path), `createPlacementLedger` (the durable per-child record), `defaultLedgerDir`. |
| `packages/plugin-remote-fanout/lib/provider.js` | **edited.** `start()` now acquires a placement **before** it builds the script (the script carries the placed node's own paths) and **before** it publishes; waits when `position > 0`; dispatches with the placed node's transport; verifies the child's `MESH-HOST:` line against the hostnames of the node **the broker named**; releases the lease on every path (completed, failed, aborted); and puts the placement and the release in the parent's report. |
| `packages/plugin-remote-fanout/lib/index.js` | **edited.** `resolvePlacementMode()` — the mode rule, in the package; builds the placer; logs which mode at registration. |
| `packages/plugin-remote-fanout/bin/mesh-placement-proof.mjs` | **new.** The proof driver: dispatches N real children at once through the provider, prints the broker's per-child answer, the lease, the release and the child's own `MESH-HOST:`, and exits non-zero if any child ran somewhere the broker did not name or if any lease was not given back. |
| `packages/plugin-remote-fanout/bin/mesh-run.mjs` | **edited.** Imports the node table and the broker client instead of carrying its own copies. Its flags, exit contract (0/10/1) and log shape are unchanged. |
| `packages/plugin-remote-fanout/test/{provider,placement,broker-client}.test.mjs` | provider: the placement, the queue, the refusal, the location check, the fixed opt-in. placement: acquire, the table lookup miss, the bounded wait, the release, the ledger. broker-client: the ssh argv, every failure shape, the quote guard. **66 tests, 66 pass** — `node --test test/*.test.mjs`. |
| `profiles/web/cordis.patch.yml` | **edited** (the deployment config — the one file outside the package): the row now carries `placement`, `brokerSsh`, `brokerUrl`, `brokerTimeoutMs`, `queueWaitMs`, `queuePollMs`. `target` and the path keys stay, as the fallback's fallback. |
| `docs/mesh/92-provider-placement.md` | this file. |

`ssh-transport.js` and `remote-script.js` are unchanged: the transport already took its target as a
parameter, which is what made per-node dispatch a wiring job rather than a rewrite.

---

## 3. The mode rule: the broker is the automatic path, fixed is opt-in

```js
// lib/index.js
export function resolvePlacementMode(config = {}, env = process.env) {
  const configured = config.placement ?? env.MESH_PLACEMENT;
  if (configured === 'fixed') return 'fixed';
  if (configured === 'broker') return 'broker';
  if (typeof env.MESH_TARGET_NODE === 'string' && env.MESH_TARGET_NODE.trim() !== '') return 'fixed';
  return 'broker';
}
```

| what is set | mode | what happens |
|---|---|---|
| nothing | **broker** | every child is placed by the broker |
| `placement: fixed` in the row, or `MESH_PLACEMENT=fixed` | fixed | every child goes to `target`, and the engine log says so at startup with a **warn** line that names the broker as unconsulted |
| `MESH_TARGET_NODE` set **by hand** in the engine's environment | fixed | the opt-in fallback; also what `bin/mesh-run.mjs` sets for the `--profile mesh` child it boots, so the dispatcher CLI behaves exactly as it did |
| `placement: broker` in the row, or `MESH_PLACEMENT=broker` | broker | an explicit choice wins over everything |

Three consequences worth stating plainly.

* **A row that merely names a `target` does not select fixed mode.** That was the old reading, and it
  is what made one node look like a mesh. `target` is used only when the mode is `fixed`.
* **A broker that cannot be reached is never a reason to use the fallback.** `start()` rejects with
  `remote-ssh: broker-unreachable: the placement broker could not be reached at
  secratary-ts:http://localhost:3091/place — …`, nothing is dispatched, and a ledger record with
  `state: "placement-failed"` is written so the failure is not only in a transcript. There is a test
  for it (`a broker that cannot be reached REJECTS start() with the named error, and starts nothing`).
* **The automatic path needed no deployment edit.** The mode rule lives in the package, so the
  package's own default is broker mode; the `profiles/web/cordis.patch.yml` change makes the
  deployment say out loud what the package already does. Both were kept because a row that states its
  own mode is easier to audit than a default nobody can see.

`target`, `remoteNodeExe`, `remoteDshBin`, `remoteCwd` and `remoteShell` therefore survive as the
fallback's configuration, and in broker mode the per-node shell, paths and hostname list come from
`lib/nodes.js`. That fixes a second, older defect for free: the row's `remoteShell` was derived from
**the parent's** `process.platform`, which is not a fact about the target — measured 2026-09-16, a
Windows parent dispatching to the Linux authority sent `powershell` and every child died with
`bash: line 1: powershell: command not found`, exit 127.

---

## 4. A queued child is not a running child

`POST /place` answers `position > 0` when the mesh has accepted jobs ahead of this one. Three things
are true of that state and all three are load-bearing:

1. **The child has not started.** The placement and the wait both happen inside `start()`, *before*
   the run is published to `ctx.subagents`. Publication is what makes a child appear as a running
   agent, so a waiting child cannot appear as one — the failure mode ("a waiting agent that looks like
   a running agent") is removed by construction rather than by a status field somebody has to read.
2. **The wait is visible while it lasts**, in a durable file: one JSON record per child under
   `<DSH_HOME>/mesh/placements/<id>.json`, rewritten at each transition
   (`placed`/`queued` → `dispatching` with `waitedMs` → `settled` with `stopReason`, `meshHost` and
   `leaseReleased`), with the broker's own `rationale` and the `queue` it named. Measured raw below.
   A file rather than a log line because **in the `web` profile a host-plane plugin's
   `ctx.logger.info` goes nowhere durable** (`90-provider-mount.md` §8.2, measured) — a queue position
   that only exists in a log nobody keeps is one nobody can see.
3. **The wait is bounded, and when it expires the child is dispatched anyway.** That is the broker's
   own rule (`queue, never amputate`); a caller that gave up on a queued child would be refusing work
   the mesh never refused. The report says which happened.

**The one channel that does not exist, stated as a refusal.** There is no live progress surface from a
provider to the caller's model *during* a delegation: `SubagentProvider.start(request)` must fulfil
before a run is published (`dsh-subagent/lib/types/types.d.ts:292-318`), and `@deepseek-ai/dsh-tool-subagent`
has no progress, update or event hook at all (READ: the package's `lib/index.js` contains no
`progress`/`emit(`/`onUpdate`). So a parent's view of a queued child is a pending tool call, and the
queue becomes *its* text only when the child settles. Fixing that means changing the seam, not the
provider — the honest shape of the fix is a `start()`-time progress channel on the provider contract,
and it is not in this package's gift.

---

## 5. The proofs, raw

Every run below dispatched **real children**: a fresh `dsh --profile headless` process on the target
machine, through the provider's own ssh transport, reporting its own hostname. Every run released every
lease it took. All runs used `bin/mesh-placement-proof.mjs`, which exits non-zero on a location
mismatch or an unreleased lease.

### 5.1 Two children at once — and the broker names ONE node

```
$ node bin/mesh-placement-proof.mjs --children 2 --child-timeout-ms 240000
=== the mesh, read fresh ===  (13:17:42Z)
  zabz-tech          state=ok  slots=18  free=18  coreSlots=18(physical)  leases={"running":0,"queued":0}
  zabz-yoga-1        state=ok  slots=12  free=12  coreSlots=12(physical)  leases={"running":0,"queued":0}
  zabz-tech-linux    state=ok  slots=4   free=4
  secratary          state=ok  slots=3   free=3   swap=81.2%  transport=null
  [proof] 2 children placed and launched in 1985 ms

child remote-763030f7-…  placed on zabz-tech (desktop-ts) position=0 score=18 tier=fits lease=mu5k1ap9-17e16-o-fdbb7369
  MESH-HOST zabz-tech   stopReason completed   lease RELEASED by POST /done
  rationale chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech
  rationale zabz-tech: 18 free slot(s) of 24 (slots 18 = 24 raw - see above, minus 0 broker lease(s) running here; 0 queued)
child remote-fea4fa32-…  placed on zabz-tech (desktop-ts) position=0 score=17 tier=fits lease=mu5k1bm0-17e16-p-0d9950f7
  MESH-HOST zabz-tech   stopReason completed   lease RELEASED by POST /done
  rationale … minus 1 broker lease(s) running here; 0 queued
broker leases   after live=0 (running=0, queued=0)
failures        none                       (exit 0)
```

**Read twice, because the second child's rationale is the interesting one.** It saw `17 free slot(s) …
minus 1 broker lease(s) running here` — its sibling's lease — and the broker still chose `zabz-tech`,
because it had more free slots than the laptop's 12. So: **two children requested at once do NOT land
on two different nodes on an idle-ish mesh, and that is the broker working as designed, not the
provider ignoring it.** `76-broker.md` §3 and `71-mesh-program.md` §2.2 rank the `fits` tier by
`score = freeSlots`, highest first. The mesh is filled in the order *most room first*, so it spreads
**proportionally and only under load** — the desktop takes children until it is down to the laptop's
12, and the next one goes to the laptop. That is the right policy for the owner's 55 agents (it uses
the 18-slot desktop before the 12-slot laptop), and it is not a per-child round robin.

### 5.2 Eight children at once — still one node, and the reason is a `slow` reading

```
$ node bin/mesh-placement-proof.mjs --children 8 --child-timeout-ms 300000
nodes used      zabz-tech×8          distinct nodes  1
scores         18, 17, 16, 15, 14, 13, 12, 11        MESH-HOST zabz-tech ×8
counters       {"placed":8,"queued":0,"released":8,"placementFailed":0}
broker leases  before live=0  after live=0          failures none      (exit 0)
```

Seven children in, the desktop was down to 11 free slots and the laptop was still reading 12 — so the
eighth child *should* have gone to the laptop. It did not, and the reason is a rule worth knowing:
**a node whose capacity read is momentarily `slow` is removed from the `fits` pool entirely**, not
merely ranked below the others — `broker.js:608-614`, `usable = preferred.length > 0 ? preferred :
dispatchable`, where `preferred` drops every `slow` node. The laptop's gate (a Python route on a
machine that is simultaneously running the owner's engine) alternates `ok`/`slow` every few seconds;
measured over three consecutive fresh reads at 13:17Z: `ok`, `slow`, `ok`.

So on this mesh, at this moment, eight concurrent children land on the desktop — **and the desktop
sustained them: 8 real child turns at once, all exit 0, in one wave.** The mesh does not spread until
the *other* node is both reachable-and-fast and the winner no longer fits the job.

### 5.3 The state that should force a split — and it still does not split, because of a `slow` reading

The mesh state that makes the broker split two simultaneous children is the state six children leave
behind: the desktop's free slots brought down to the laptop's 12. `--hold 6` takes six real leases
(the same thing six running children hold) and keeps them for the length of the run:

```
$ node bin/mesh-placement-proof.mjs --hold 6 --children 2 --child-timeout-ms 240000
=== the mesh, read fresh ===  (13:24:37Z)
  zabz-tech          state=ok    slots=18  free=18  leases={"running":0,"queued":0}
  zabz-yoga-1        state=slow  slots=12  free=12  leases={"running":0,"queued":0}   <-- slow
  zabz-tech-linux    state=ok    slots=4   free=4
  secratary          state=ok    slots=3   free=3   transport=null
  held mu5kab1f-… on zabz-tech (score 18)  …through…  held mu5kagsm-… on zabz-tech (score 13)
  [placer] child remote-0e1a7c8a-… placed on "zabz-tech" position=0 score=12 tier=fits
  [placer] child remote-d57e01ba-… placed on "zabz-tech" position=0 score=11 tier=fits
  both MESH-HOST zabz-tech, both completed, both leases RELEASED, all six held leases RELEASED
nodes used      zabz-tech×2          distinct nodes  1
broker leases   before live=0  after live=6 (the held ones)  after releasing the held leases=0
failures        none      (exit 0)
```

At `score 12` the desktop was exactly level with the laptop's 12 free slots; the second child saw
`score 11` on the desktop against a laptop with 12 — and still went to the desktop, because the laptop
read **`slow`** in that moment's reading and a `slow` node is not in the `fits` pool at all
(§6.2). **So the split did not happen, and the reason is not the provider.** This is the single most
useful negative in the document: the machine whose gate is slowest is the one the owner works on, and
while its capacity route takes longer than the broker's deadline it receives no children *even when it
has more free slots than the node that does*. Any plan that expects the laptop to share a fleet should
be read against this measurement first.

### 5.4 The queue: a mesh forced low, and a slot that frees while the child waits

The live broker cannot be made to say `position > 0` without filling every node with real accepted
jobs, so this run used the broker's **own documented stub mechanism** (`76-broker.md` §6.3) on a second
instance, loopback-only, on the authority at `:3092` — **the live broker on `:3091` was not touched,
not reconfigured and not restarted.** The stubbed part is the *capacity reading*; the node the broker
names (`zabz-tech`), the ssh destination, the child and the lease are real.

```
# on secratary, in /tmp/mesh-queue-proof: one stub gate at :3191 whose slots can be flipped,
# and a one-node roster pointing the broker at it (node name and fqdn unchanged: zabz-tech)
$ node /home/zabz/mesh-broker-run/bin/mesh-broker.mjs --port 3092 --config /tmp/mesh-queue-proof/roster.json
mesh-broker listening on http://127.0.0.1:3092  (port 3092)
  zabz-tech  http://127.0.0.1:3191/mesh/capacity  [office]
  cache capacity readings are reused for at most 5 s
```

then, from the laptop, with `MESH_BROKER_URL=http://localhost:3092`, `MESH_QUEUE_WAIT_MS=60000`,
`MESH_QUEUE_POLL_MS=5000`, and the gate flipped to `slots=6` from the authority at T+22 s:

```
=== the mesh, read fresh ===
  zabz-tech   state=ok  slots=0  free=0  memSlots=0  coreSlots=12(physical)  leases={"running":0,"queued":0}
  [placer]   child remote-d29b3b0d-… placed on "zabz-tech" (desktop-ts) by the broker —
             position 1, score 0, tier highest-slots, lease mu5k7wko-1cp7v-4-e876e3de
  [provider] child remote-d29b3b0d-… is QUEUED at position 1 on "zabz-tech"
             (lease mu5k7wko-1cp7v-4-e876e3de) — it has not started, and it is not published as a running agent
  [provider] still queued on "zabz-tech" — freeSlots 0 after 5691 ms
  [provider] still queued on "zabz-tech" — freeSlots 0 after 11891 ms
  [provider] still queued on "zabz-tech" — freeSlots 6 after 17861 ms
  [provider] queued-released on "zabz-tech" after 17865 ms — a free slot appeared after 17865 ms
  [provider] run remote-d29b3b0d-… on "ZABZ-TECH" (placed on "zabz-tech") mesh-host="zabz-tech" exit=0 in 6024 ms
  [placer]   lease mu5k7wko-1cp7v-4-e876e3de on "zabz-tech" released (true)

child remote-d29b3b0d-…
  placed on   zabz-tech (desktop-ts)  position=1 score=0 tier=highest-slots lease=mu5k7wko-1cp7v-4-e876e3de
  waited      17865 ms
  lease       RELEASED by POST /done
  stopReason  completed
  MESH-HOST   zabz-tech
  rationale   chosen from 1 configured node(s): … tier=highest-slots; chosen zabz-tech
  rationale   zabz-tech: 0 free slot(s) of 24 (slots 0 = 0 raw - see above, minus 0 broker lease(s) running here; 0 queued)
broker leases   after live=0      failures none      (exit 0)
```

Three things this proves that the brief asked for specifically:

* **the queue position is surfaced, not swallowed** — `position 1`, `tier highest-slots`, the broker's
  `blockedBy: ["no-free-slots"]` line and the wait itself are in the child's record and in the report;
* **the child waited, and it was not a silent wait** — the wait is `17.865 s` of recorded polls, and the
  transition to `queued-released` names the reading (`freeSlots 6`) that ended it;
* **the mechanism is not a simulation** — the child that finally ran really ran on `zabz-tech`, and
  said so itself: `MESH-HOST: zabz-tech`.

### 5.5 A queue wait that expires still dispatches, and says so

Measured on the same stub mesh in the run before the one above, with the gate left at 0 slots:

```
  [provider] child remote-979e9ade-… queued-expired on "zabz-tech" after 120989 ms —
             no free slot appeared within 120000 ms; dispatching anyway (queue, never amputate)
  [provider] run remote-979e9ade-… on "ZABZ-TECH" (placed on "zabz-tech") mesh-host="zabz-tech" exit=0 in 5898 ms
  waited      120989 ms (queue wait expired; dispatched anyway)
```

**And it found a real bug in this session's own code, which is why it is recorded.** The first attempt
at this run died with `Warning: Detected unsettled top-level await` immediately after logging
`is QUEUED at position 1`: the wait's `sleep()` used `timer.unref()`, so with the ssh client not yet
started there was nothing left holding the event loop open and Node exited out of the middle of the
wait. In the engine that would have been a queue that waits forever with no error at all.
`lib/placement.js` no longer unrefs that timer, and the comment there carries the measurement.

### 5.6 A REAL `subagent_remote` CALL from a resident engine session, on the new configuration

This is the run the brief's other halves were building toward: the **mounted tool**, called by a
model, in an engine session on the `zabz` preset, with the new patch row and **every `MESH_*` override
cleared** — so the provider took `resolvePlacementMode()`'s default, which is the automatic path.

```
$ pwsh _scratch/mesh-92-resident-check.ps1
[resident] engine pid 28924 on :3098, DSH_HOME=C:\Users\ezabz\.dsh-meshcheck
[resident] listening=True after 60s exited=False
[resident] healthz 200 pid=28924 dshHome=C:\Users\ezabz\.dsh-meshcheck
[resident] session/create ok=True id=session-30de7603-… preset=zabz
[resident] prompt ok=True
[resident] --- the session's reply ---
MESH-HOST: zabz-tech [remote-ssh] child ran on node "ZABZ-TECH" via C:/Program Files/OpenSSH/ssh.exe -o BatchMode=yes -…
```

and the engine's own placement ledger, `<scratch home>/mesh/placements/remote-9f44a60a-….json`,
abridged to the fields that matter:

```json
{ "source": "broker", "node": "zabz-tech", "ssh": "desktop-ts", "position": 0,
  "tier": "fits", "score": 18, "eligible": 4, "blockedBy": [],
  "lease": "mu5knypz-17e16-1e-98690754", "leaseTtlSec": 900,
  "rationale": ["chosen from 4 configured node(s): … tier=fits; chosen zabz-tech",
                "zabz-tech: 18 free slot(s) of 24 (slots 18 = 24 raw - see above, minus 0 broker lease(s) running here; 0 queued)",
                "zabz-yoga-1: 12 free slot(s) of 24, … effective 12, 11 after 1 child(ren)", "…"],
  "queue": [], "placedAt": "2026-09-17T13:35:19.174Z", "brokerCallMs": 3726,
  "facts": { "profile": "headless", "shell": "powershell", "cwd": "C:/Users/ezabz" },
  "state": "settled", "waitedMs": 0, "stopReason": "completed",
  "reportedHost": "ZABZ-TECH", "meshHost": "zabz-tech", "exitCode": 0, "ms": 7290,
  "leaseReleased": true }
```

Four separate claims are settled by those two blocks together:

* **the automatic path really is the broker** — `"source": "broker"`, with four candidates considered
  and the winner's arithmetic printed, in an engine where nothing named a target;
* **the tool is unchanged and still granted** — the session called `subagent_remote`, which is the
  name the owner's preset grants and sessions already use; no argument changed;
* **the placement was honoured** — the child's own `MESH-HOST: zabz-tech` and the ledger's
  `reportedHost: "ZABZ-TECH"` agree, and a disagreement would have failed the run (§ provider tests);
* **the lease was released** — `"leaseReleased": true`, and the live broker's `healthz` returned
  `leases.live: 0` afterwards.

Two honest footnotes. The session-list projection truncated the assistant's reply text (the ledger is
the complete record, which is exactly why it is written), and the first broker call cost **3.7 s**
(`brokerCallMs`) — a cold ssh round trip per placement, against ~0.4 s when the connection is warm.
One extra round trip per child is the price of asking; it is bounded and it is paid once per child,
not once per turn of a child.

Finally, nothing was left running: `after kill: listeners on :3098 = 0` and
`owner engine 4880 alive = True`.

---

## 6. What the broker's interface cannot express, said precisely

The brief asked for this to be stated rather than worked around, and there are three real gaps.

1. **There is no way to ask for a distribution.** `POST /place` names exactly one winner per call.
   There is no `spread`, no `maxPerNode`, no "place these K children over the mesh". One call per child
   is therefore the only shape available, and the ranking (`fits` → highest `freeSlots` → roster order)
   fills the roomiest node until it can no longer take the job. A caller that wants two children on two
   nodes at once either waits for the mesh to be loaded (measured §5.3) or drives `task.exclude` per
   child — and using `exclude` for that would be **this package inventing a policy the broker does not
   have**, and a bad one: at healthy capacity it would send the second child to the 4-slot office Linux
   box while the desktop still had 15 free slots. So it was not done. If a true spread is wanted it
   belongs in the broker, as a field on `task` that the ranking honours.
2. **A momentary `slow` reading removes a node from the `fits` pool entirely** (`broker.js:608-614`),
   rather than ranking it last. On this mesh that is the difference between an eight-child wave landing
   7+1 and landing 8+0. `76-broker.md` §10.8's intent — "a busy node is not a dead one" — is satisfied
   for the `highest-slots`/`transport` tiers but not for `fits`, and the effect is that a node whose
   gate is slow receives nothing while any other node answers fast. Worth a decision, not taken here:
   this is `packages/mesh-broker`, not this package.
3. **The roster's `dispatch.v1` is the only way to say "this node cannot actually run a child"**, and
   it is global to the node rather than per-caller. Measured and left alone: the live roster carries
   `zabz-tech-linux` as `dispatch.v1: true` with evidence that the *transport* works, while
   `lib/nodes.js` records the same node as `'NOT VERIFIED: this node has no Node runtime yet'` and
   names a `nodeExe` path that may not exist. A child the broker places there would probably fail on
   the node, not on the placement. That is a roster-accuracy question for the broker's owner, and this
   session did not touch the roster.

**One thing the API expresses perfectly and is now used properly:** `task.exclude` is the caller's hint
and it yields to never-refuse, which is exactly what a per-engine operator exclusion should be. It is
wired as a config key (`exclude`) and defaults to empty, because the provider has no evidence that any
node should be avoided that the broker does not already have.

---

## 7. Verification: every claim, its command, its result

| claim | command | result (MEASURED) |
|---|---|---|
| the package's own tests pass | `node --test test/remote-script.test.mjs test/ssh-transport.test.mjs test/provider.test.mjs test/placement.test.mjs test/broker-client.test.mjs` | **tests 66 · pass 66 · fail 0** |
| every source file parses | `node --check lib/*.js bin/*.mjs` | exit 0 |
| the dispatcher CLI is unchanged and still refuses a lookup miss | `node bin/mesh-run.mjs -Node nosuchnode` | `the broker named node "nosuchnode", which is not in this dispatcher's node table (zabz-tech, zabz-yoga-1, zabz-tech-linux, secratary, lakewooechsmini)`, **exit 1** |
| the profile still composes | `node …/dsh/lib/bin.js --profile web --dump-config` | **exit 0**, 620 lines, rows `remote-fanout` and `tool-subagent-remote (disabled)` present |
| the install's own invariants, and the patch layered onto the live profile | `pwsh scripts/mesh-provider-install.ps1 -Check` then `pwsh scripts/mesh-provider-install.ps1` | `-Check` first reported the drift it was meant to catch (`the live patch layer … differs from the repo's`), then the install reported **`every invariant holds (1 change(s))`**, `dump-config exit 0, 632 lines` (620 before), and printed the inert-until-restart warning |
| the composed provider row carries the placement keys | `node …/dsh/lib/bin.js --profile web --dump-config` | exit 0, 632 lines, and the row reads `placement: !!js process.env.MESH_PLACEMENT ?? (process.env.MESH_TARGET_NODE ? 'fixed' : 'broker')`, `brokerSsh`, `brokerUrl`, `brokerTimeoutMs`, `queueWaitMs: 120000`, `queuePollMs: 5000` |
| **the new row boots an engine** | `pwsh _scratch/mesh-92-boot-check.ps1` — a second engine, its own `DSH_HOME` (`~/.dsh-meshcheck`), its own port (:3098), carrying the repo patch | `listening=True after 30s`, `healthz 200`, `engine pid 23772`, `dshHome=C:\Users\ezabz\.dsh-meshcheck`; after the kill `listeners on :3098 = 0` and `owner engine 4880 alive = True` |
| the broker is live and loopback-only | `ssh secratary-ts "curl -s http://127.0.0.1:3091/healthz; ss -ltnp \| grep 3091"` | `{"ok":true,…,"nodes":4,"leases":{"live":0,…}}`; `LISTEN 127.0.0.1:3091 … users:(("node",pid=2024394))` |
| placement, dispatch, verification and release, end to end | §5.1–§5.5 | 11 real children across four runs; every one on the node the broker named; every lease released (`after live=0`); exit 0 |
| the owner's engine was never touched | `Get-Process -Id 4880` before and after | same pid, same start time (08:51:07), alive at the end of the session |

---

## 8. What was NOT done, and what it costs

* **No engine restart.** The running engine (pid 4880) loaded the previous package code and the
  previous patch layer at 08:51; my changes are on disk and take effect at the NEXT start. That means
  **the owner's live `subagent_remote` still goes to the fixed target until that restart**, and this
  document is the reason a restart window is now worth scheduling. The brief's rule was explicit: a
  restart is the owner's decision to schedule, so it was not taken.
* **The live patch layer was left as it was found, then updated by the installer's own path.** At the
  end of this session `scripts/mesh-provider-install.ps1` was run (first `-Check`, which is how the
  drift was caught and recorded, then the install itself) to copy the repo layer into
  `~/.dsh/profiles/web/cordis.patch.yml`. It reported `every invariant holds (1 change(s))` and
  re-verified `--dump-config` exit 0 with 632 lines. The write is inert until a restart, and
  `-Rollback` takes it back out. What it buys: the next boot needs no second decision, and a future
  session does not find a FAIL where the repo and the deployment disagree.
* **The composition WAS proven by booting an engine on an isolated home, but not on the owner's.** A
  second engine with its own `DSH_HOME` and port, carrying the repo patch, came up and answered
  `/healthz 200` (`_scratch/mesh-92-boot-check.ps1`, §7) — that is the proof that the new `!!js`
  expressions evaluate and that the row cannot stop a machine booting, which `--dump-config` alone
  cannot give (it evaluates no `!!js`). What it does not prove is a dispatch from that engine: see §9.
* **The `mesh` profile was not re-exercised.** `bin/mesh-run.mjs` is expected to behave exactly as
  before (it sets `MESH_TARGET_NODE` in the child's environment, which the mode rule reads as the
  opt-in fixed mode), and it was checked only at the argument/table level (`-Help`, `-Node nosuchnode`),
  not by dispatching a fleet through it.

---

## 9. What could not be verified, stated as refusals

* **That a `subagent_remote` call from a live session in the *owner's own* engine asks the broker.**
  The dispatch itself is now proven on a resident engine session (§5.6) — the mounted tool, a real
  child, a released lease — but that engine was a second one on an **isolated `DSH_HOME`**, because
  the owner's engine is still running the previous code and the previous patch layer and restarting it
  is the owner's decision to schedule. `90-provider-mount.md` §7 and `91-resident-dispatch-proof.md`
  record the same boundary for the previous configuration; what is new here is that the gap is now
  only the restart, not the wiring.
* **A cross-node two-child split with nothing holding leases.** Two children at once land on one node
  (§5.1) and eight land on one node while the laptop's gate reads `slow` (§5.2). Whether the split
  appears for a two-child fan-out on a healthy mesh is therefore **no**, and the reason is the broker's
  ranking, not this provider. Stated as a refusal because it is the one line of the brief that the
  measurement does not confirm.
* **The Mac Mini (`lakewooechsmini`) as a placement target.** It is in `lib/nodes.js` but not in the
  broker's roster — its gate does not answer `GET /mesh/capacity` (`nodes.json`'s own
  `_excluded_on_purpose`), so the broker can never name it and the provider can never be asked to
  place there. Unchanged by this work.
* **`secratary` as a placement target.** The roster carries `dispatch.v1: null` (never measured) and
  its swap is at 81% (halved slots). The broker can name it; the provider's facts for it are the two
  measured paths from `62-worker-runtime.md`, but no child has ever run there through this package.

---

## 10. What the next session should know

1. **The provider now asks before every child, and the mode rule is in the package.** `placement` is
   `broker` unless `MESH_TARGET_NODE` is set by hand or `placement`/`MESH_PLACEMENT` says `fixed`.
   Reading `target:` in a row and concluding "fixed" is the old mistake; read `resolvePlacementMode`.
2. **`docs/mesh/92` §5.1 is the answer to "why don't two children spread?"** — the broker's `fits` tier
   is `freeSlots`-ranked and fills the roomiest node first. Do not "fix" that in the provider.
3. **A queued child is invisible to its caller until it settles, on purpose.** The ledger file under
   `<DSH_HOME>/mesh/placements/` is the live surface; if a live channel to the caller is wanted, it is
   a `dsh-subagent` contract change (§4).
4. **An unref'd timer in a wait loop can end a process mid-wait** (§5.5). It cost one run here.
5. **The placement ledger will grow one small JSON file per remote child.** At the owner's scale
   (55 agents) that is tens of files per hour in `<DSH_HOME>/mesh/placements/`. It is deliberately not
   pruned here; if it becomes noise, the right fix is a bounded ring in `createPlacementLedger`, not a
   silent delete.
6. **The fixtures that re-run §5.6 and the boot check in one command**, both untracked scratch:
   `node packages/plugin-remote-fanout/bin/mesh-placement-proof.mjs --children N` (real broker, real
   nodes, exits non-zero on a location mismatch or an unreleased lease),
   `pwsh _scratch/mesh-92-boot-check.ps1` (isolated-home boot of the patched row) and
   `pwsh _scratch/mesh-92-resident-check.ps1` (boot + a session + one `subagent_remote` call). The
   isolated home is `~/.dsh-meshcheck` on port **3098**; the owner's engine is **3099**, and two
   engines on one `DSH_HOME` is the thing that must never happen.
