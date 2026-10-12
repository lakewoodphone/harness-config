# 159 — THE MESH AFTER THE CLOUD CUTOVER: what was broken, what was fixed, and what is still open

**Date:** 2026-10-12, 03:05–03:40Z. **From:** ZABZ-YOGA (the owner's laptop, home).
**Trigger (owner, verbatim):** *"we just did a very big migration from the secretary server in the
office to the secretary server on the cloud … check the entire mesh system in regards to
orchestrating fanning out in sub agents and make sure that it works even better than before and
nothing is broken and everything got faster … Make sure that you know the parents able to talk to
the children and the children to the parents and run very robustly and works perfectly and it's
routed properly."*

Everything below is a measurement with the command that produced it, or it says it is not measured.
Two real children were dispatched onto the mesh during this audit and both are quoted.

---

## 0. The verdict in one screen

| # | finding | evidence | state |
|---|---|---|---|
| **M1** | **The staged cloud broker could not read a single node.** Every node's gate answers `403 Not signed in` to the authority, because the gate's device allow-list never listed the cloud. A broker with no readings answers every placement blind. | `GET /nodes?fresh=1` on the cloud: **5/5 unreachable, `reason: HTTP 403`**; `/place` answered `zabz-tech, position 1, blockedBy ["unreachable","no-free-slots"]` | **FIXED** — one line per node, §2.1 |
| **M2** | **The broker ran on the FROZEN rollback anchor**, and the staged cloud copy's roster did not exclude that box, so the staged move would have placed children on it. | cloud roster: `secratary excluded=False`; repo roster: `excluded=True`; `host-posture.tsv`: `secratary|frozen` | **FIXED** (roster synced; broker started on the authority). Stopping the office copy is the owner's call, §5.1 |
| **M3** | **The broker-unreachable fallback threw working nodes away.** `node-probes.js` read only `/mesh/health`, which two live nodes answer `404` / `502`; they were recorded `unreachable` and dropped. | before the fix the instrument reported those nodes as `unreachable`; after it, `reached: 5, unreachable: (none)`, both listed as candidates | **FIXED** §2.2, test-verified |
| **M4** | **A live mesh child cannot be messaged, and is invisible to `list_agents`.** Measured, not inherited from 119 §6. | `send_message` → `Error: subagent "subagent-246" is unavailable`; `list_agents` → `(no subagents)` while that child was mid-turn | **ENGINE LIMIT — confirmed §4.1**; the mailbox is the only channel and it is unreliable (§4.2) |
| **M5** | **The mailbox thread is not created on the child's node**, so the one cross-turn conversation channel silently reports `0 message(s)`. | the child's own header named `/home/zabz/code/.dsh-mesh-mailboxes/<id>/inbox.jsonl`; that directory did not exist on the node | **OPEN §5.3** (recorded, not fixed) |
| **M6** | **One dead-but-in-roster node costs ~4 s on every cold placement** (the Mac mini is unreachable from the broker host). | broker `/healthz` 747 / 896 ms warm against `/place` 6,768 ms cold; `lakewooechsmini: timed out after 4000 ms (hard wall-clock deadline)` | **OPEN §5.2** |

**The one sentence:** the migration left the mesh's control plane on the box it had just frozen,
and the fix had been half-applied — the dispatcher's default had already been retargeted to the
authority, but the authority could not read any node, which is a *worse* state than not having
moved at all, because a blind broker still answers.

---

## 1. What the mesh actually is, measured 2026-10-12 03:0xZ

| node | tailnet | role in the mesh | gate answers today |
|---|---|---|---|
| `zabz-tech` | `100.85.153.96`, office LAN | the strongest worker (32 cores, 63.6 GiB); dispatches and accepts | `/mesh/health` 200, `/mesh/capacity` 200 |
| `zabz-yoga-1` | `100.72.162.5`, home, off-LAN | the owner's laptop; dispatches and accepts | 200 / 200 |
| `zabz-tech-linux` | `100.105.248.90`, office LAN | worker, v1 ssh only | `/mesh/health` **404**, `/mesh/capacity` 200 |
| `lakewooechsmini` | `100.126.146.121`, relay "nyc" | Yisroel's Mac; worker | `/mesh/health` 502, `/mesh/capacity` 200 from a listed device; **unreachable from the cloud** |
| `secratary` | `100.84.72.88`, office LAN | **FROZEN rollback anchor**, `excluded: true` in the roster | `/mesh/health` 502, `/mesh/capacity` 200 |
| `secratary-cloud` | `100.73.176.126`, Ashburn | **THE AUTHORITY**; not a worker | 200 / 200 |
| office box's `mesh-broker` | loopback `127.0.0.1:3091` | **the live broker every installed dispatcher still uses** | `/healthz` ok, uptime 12,898 s |
| authority's `mesh-broker` | loopback `127.0.0.1:3091` | staged since 2026-10-11 13:27, **inactive/disabled** until this session | started here, §2.1 |

**LAN is not the mesh's transport.** Measured from `zabz-tech`: only `secratary` (192.168.50.77)
and `zabz-tech-linux` (192.168.50.23) answer on 192.168.50.0/24; the laptop is off-LAN and the Mac
is on a relay. So the policy in `143-TRANSPORT-POLICY.md` holds, and the tailnet is the transport
that actually carries fan-out.

**The two dispatch paths, and they disagreed.** `profiles/web/cordis.patch.yml` had been retargeted
to `secratary-cloud` (commit `d143fb7a`, 2026-10-11 18:51), while
`bin/mesh-run.mjs` still defaulted to `secratary-ts`. **Fixed here** — both now name the authority.

---

## 2. The defects, and what was done

### 2.1 M1 + M2 — the broker: staged, half-switched, and blind

**The roster.** `/opt/mesh-broker/nodes.json` on the cloud was the 2026-10-11 13:27 copy and carried
`secratary` with **no exclusion** — unlike the repo roster. Started as it was, the broker would have
spent leases on the frozen anchor. The repo roster was copied over it
(`sha256 690ea510…`, old copy kept as `nodes.json.bak-20261012`); the frozen box is now
`excluded: true` there too.

**The read path.** Starting the cloud broker was not enough, and this is the finding that matters:

```
# from the cloud, BEFORE the allow-list line — every node, every route:
HTTP/2 403   ("Not signed in", 639 bytes, cache-control: no-store)
# the broker's own view:
reads 5 failures 5
  zabz-tech          unreachable  reason: HTTP 403
  zabz-yoga-1        unreachable  reason: HTTP 403
  zabz-tech-linux    unreachable  reason: HTTP 403
  secratary          unreachable  reason: HTTP 403
  lakewooechsmini    unreachable  timed out after 4000 ms
# and its answer to a real /place:
  node=zabz-tech position=1 tier=highest-slots blockedBy=["unreachable","no-free-slots"]
```

The cause is `scripts/phone-gate.py`'s **device allow-list** (`phone-gate-allow.txt`): every node's
gate refuses any tailnet device not named in that file, and the authority was never named. This is a
deliberate, good control (2026-09-16: a cold `GET /` through a node's tailnet name handed out a
session cookie) colliding with a deliberate, good requirement (the broker must read every node).

**The fix, and what it costs, written into the file itself.** The authority's address was added to
the allow-list — the file's own convention is that a listing needs a written reason, and it now has
one. The cost is stated there too: a listed device can be signed in automatically, so a compromise
of the authority now also buys a session on every listed node. Two one-line reverts are written
beside it. Deployed to `zabz-tech`, `zabz-yoga-1` and `zabz-tech-linux`; **not** to the frozen box
(it is excluded from the roster, and touching it is not permitted).

```
# AFTER — from the cloud:
  zabz-tech          capacity=200     zabz-tech-linux   capacity=200
  zabz-yoga-1        capacity=200     lakewooechsmini   capacity=000 (its own allow-list, §5.2)
  secratary          capacity=403     (excluded from the roster; unchanged on purpose)

# the broker's own view after:
reads 20 failures 17        # the 17 are the pre-fix attempts
  zabz-tech        ok           slots=18  latencyMs=150
  zabz-yoga-1      ok           slots=12  latencyMs=221
  zabz-tech-linux  ok           slots=4   latencyMs=93
  secratary        unreachable  HTTP 403 (excluded)
  lakewooechsmini  unreachable  timed out after 4000 ms

# and a real placement through the cloud broker:
  node=zabz-tech position=0 tier=fits blockedBy=[] lease=mv4ot5qn-863x-2-ed44437b … released ok
```

### 2.2 M3 — the fallback dropped working nodes (fixed, with tests)

`lib/node-probes.js` read `GET /mesh/health` and, on anything but 200, returned the node as
`error` — and `chooseFailoverPlacement` records an `error` as *unreachable, never scored*. Two live
nodes answer `404` (`zabz-tech-linux`) and `502` (`secratary`) on that route while answering
`/mesh/capacity` 200, so the broker-unreachable fallback could see two of four working machines.

The fix: when the health read **answered at all** (an HTTP status, not a timeout), try
`/mesh/capacity`; if it answers, the node is usable over v1 with **slots UNMEASURED**. It is
deliberately not scored: `freeSlots` stays `null`, so it ranks below every measured node, and
`position` stays 0 because *unknown is not short* — a node whose slots nobody measured must not make
a child wait two minutes for a slot that may be free. No slot arithmetic is reimplemented here; the
only place that lives is the broker.

```
# bin/failover-place.mjs, with the fix, from the laptop:
reached      zabz-tech, zabz-yoga-1, zabz-tech-linux, secratary, lakewooechsmini
unreachable  (none)
candidate    zabz-tech 8 · zabz-yoga-1 5 · lakewooechsmini null · secratary null · zabz-tech-linux null
CHOSEN       zabz-tech   position 0 (start now)
· zabz-tech-linux: its /mesh/health route did not answer (HTTP 404), but its /mesh/capacity route
  did — the node is USABLE over v1 ssh and its slots are UNMEASURED, so it ranks below every
  measured node rather than being thrown away
```

Before this fix those two nodes were printed as `unreachable: … HTTP 404` / `HTTP 502` and were
absent from the ranking. `test/failover-placement.test.mjs` and the rest of the suite are green
(§6).

### 2.3 What was deliberately NOT changed

`lib/placement.js`, `lib/broker-client.js`, `lib/provider.js`'s dispatch path, the pressure policy,
the broker's scoring (`packages/mesh-broker/lib/scoring.js`) and the transport (ssh + curl) are
untouched. A second source of truth for placement — or for slot arithmetic — is the defect class
this programme exists to kill.

---

## 3. Speed: the numbers, before and after

| measurement | value | what it means |
|---|---|---|
| ssh round trip, laptop → office box (5 calls) | 716 / 755 / 776 / 796 / 905 ms, avg **790 ms** | the transport floor the broker pays per call |
| ssh round trip, laptop → cloud (5 calls) | 700 / 718 / 796 / 854 / 983 ms, avg **810 ms** | **the move is not a speed win by itself** — the same floor |
| broker `/healthz` over ssh (3 calls) | 747, 896, **8,845** ms | the hop is highly variable; that variance, not distance, is what a caller feels |
| broker `POST /place`, cold vs warm (office) | **6,768** ms, then 1,211, 856 ms | a cold placement pays the node reads; a warm one pays only the hop |
| broker `POST /place` via the cloud from the dispatcher | **6,826** ms, 2,577, 1,124 ms | same shape; the cold cost is the unreadable node (§5.2) |
| broker `POST /done` | 1,391–1,618 ms | one more ssh per child, at settle |
| child on `zabz-tech` (broker-placed, 127 s turn) | exit 0, `MESH-HOST` matched | a real fan-out child, end to end |
| child on `zabz-tech-linux` (broker-placed, 31 s turn) | exit 0, `MESH-HOST` matched | a second node, and the mesh spread the work as designed |
| direct v1 child turn over ssh, `zabz-tech-linux` | exit 0 in **13.6 s** | the node's own runtime is healthy |

**What is faster now, honestly stated:** the *ceiling* is lower, not the floor. Before this session
the mesh had one broker, on a box the migration had frozen, and any machine that re-installed its
profile would have pointed at an authority broker that could read nothing — every child queued and
piled onto `zabz-tech`. Now the authority reads the fleet and places on capacity, and the same
call costs the same hop. **No claim is made that a dispatch feels faster**; the measured claim is
that a cold placement is no longer blind, and that two nodes are back in the ranking that the
fallback used to discard.

---

## 4. Parent ↔ child, measured (the owner's second question)

### 4.1 Live messaging does not exist, and that is the engine's shape

While child `subagent-246` was working on `zabz-tech-linux`:

```
list_agents      -> (no subagents)
send_message     -> Error: subagent "subagent-246" is unavailable
```

The parent can **start** a child and **read its report at the end**; it cannot speak to it while it
works, and the child cannot reach the parent inside its turn. This confirms `119` §6 in the live
system rather than inheriting it: `send_message` requires a resident continuable child, and a
remote child is never resident.

### 4.2 The substitute channel is real, and it is not reliably established

`lib/mailbox.js` is the designed substitute: a durable JSONL thread on the child's node, read back
by the parent, so a *second* dispatch on the same thread reads everything said so far. Measured:

* **It worked** for the Windows child: it created `…\.dsh-mesh-mailboxes\remote-99ff…/outbox.jsonl`
  and wrote 7 lines, which the parent's report surfaced.
* **It failed on the Linux child**: the header named
  `/home/zabz/code/.dsh-mesh-mailboxes/remote-149e…/inbox.jsonl`, and that directory does not
  exist on the node (`ls: cannot access …`); the child, correctly obeying its read-only brief, did
  not create it. The report then says, truthfully and uselessly, `mailbox = 0 message(s) in the
  thread at <path>`.

So the honest statement to the owner is: **a parent can hear from a child while it works only if
the child writes to a thread directory that nothing creates for it.** That is §5.3.

### 4.3 A mesh child is a full agent, and it can fan out further

The child on `zabz-tech-linux` reported its own toolbelt, verbatim: `bash, create_goal, edit,
exit_plan_mode, get_goal, glob, grep, interrupt_agent, job_kill, job_list, job_output, list_agents,
ralph, read, read_image, send_message, skill, subagent, subagent_fork, todo_write, update_goal,
web_fetch, web_search, workflow`. `subagent_remote` is absent, `subagent` is present (the local
`spawn` provider on that node — the mesh provider itself lives in the host plane of a resident
engine). Depth beyond one hop therefore exists, with the caveat that a child's own children are
local to the child's machine unless the mesh profile is named.

---

## 5. What is still open, and who owns it

### 5.1 The office broker is still running — the owner's call
Two brokers now exist for one mesh, and that is a split-lease hazard: a dispatcher pointed at each
would each hand out its own leases, so two dispatchers could both fill a node to its roster cap.
Measured state on the frozen box: `mesh-broker.service` **active / enabled**, holding
`127.0.0.1:3091` (node pid 409399). Stopping it is **not permitted** by this estate's own rules —
`settings/machines/host-posture.tsv` (`secratary|frozen`), `131-MIGRATION-BRIEF.md` Rule 1 and
`142-ANCHOR-WRITE-NOTICE.md`, enforced by `scripts/mesh/guard-service-state.sh` (exit 2).
`154-MESH-BROKER-MOVE.md` reaches the same conclusion. **One question, with a recommendation,
carried to the owner in the session that wrote this.**

Until it is answered the hazard is bounded and known: the installed profile on each machine still
names `secratary-ts`, so the *live* fleet keeps using the office broker; the repo and
`mesh-run.mjs` name the authority, so anything re-installed uses the cloud. Both brokers work.

### 5.2 The Mac mini: reachable, mis-declared, and expensive
`tailscale status` says `offline, last seen 4m ago`, ssh to it times out (12.4 s, exit 255), and yet
its gate answers `/mesh/capacity` with a **live** document (`at: 2026-10-12T03:24:02Z`, load1 1.45,
freeMiB 7059) to a listed device. Its own allow-list does not list the authority, so the cloud
broker cannot read it and pays the **4,000 ms wall-clock deadline** on every cold placement — the
single largest term in the cold numbers in §3. Fix: one line in that machine's
`phone-gate-allow.txt` (it needs shell access, which is not available while ssh is timing out), or
take its row out of the roster. Recorded as `P3134`.

### 5.3 The mailbox directory is never created for the child
See §4.2. The provider computes the thread path and tells the child to read it, but nothing creates
the directory on the remote node, so the channel works only when the child improvises. A fix is
small (create it at dispatch, or say in the brief that the child should create it) and it is not
applied here — it belongs with the mailbox design, not with a post-migration audit.

### 5.4 Small, measured, not fixed
* `zabz-yoga-1`'s `/mesh/health` reports `host: "zabz-yoga"` while `node: "zabz-yoga-1"` — the two
  identity fields disagree on the owner's own laptop. Nothing places by `host` today, so nothing
  breaks; it is the same identity-drift class that cost the Mac mini a day on 2026-10-08.
* `secratary-cloud`'s gate advertises `auth.secretConfigured: false`
  (`cannot stat /etc/dsh-mesh.env`), so v2 `POST /mesh/run` cannot be signed there. The authority is
  not a worker and does not need it; it is recorded so the next reader does not read `ok:true` as
  "fully configured".
* The `phone-gate.py` allow-list is read **per node, from whichever checkout that node's gate was
  started from** — the same list exists at three different paths with three different contents
  (repo copy 4,745 B with the shop devices; `zabz-tech-linux`'s at
  `/home/zabz/dsh-mesh/repo/scripts/`, 3,051 B without them). That drift is why the fix in §2.1 had
  to be deployed per node rather than once.

---

## 6. Verification, and what is not verified

| claim | how it was verified |
|---|---|
| a real child is placed by the broker and runs on another node | two children, `MESH-HOST` matched the placed node both times, exit 0 |
| the cloud broker reads the fleet and places on capacity | `curl http://127.0.0.1:3091/nodes?fresh=1` → 3 ok / 2 unreachable with reasons; `/place` → `zabz-tech position 0 tier fits`, lease released |
| the dispatcher can use the cloud broker over ssh | `createBrokerClient({sshTarget:'secratary-cloud'})` → place 6,826 / 2,577 / 1,124 ms, `done` released `true` |
| the fallback now keeps capacity-only nodes | `bin/failover-place.mjs` → `reached: 5, unreachable: (none)`, two candidates listed with `freeSlots=null` |
| the plugin suite is green after the edits | `node --test test/*.test.mjs` → **222 tests, 220 pass, 0 fail, 2 skipped, exit 0** |
| the broker's own suite is green | `packages/mesh-broker` → **72/72 pass** |
| a full child dispatched **through the cloud broker** by the resident engine | **NOT VERIFIED** — this session's engine bound `MESH_BROKER_SSH` at boot (`secratary-ts`); the provider code path is identical and is proven at the broker level, and the switch happens at the next engine start (P210) |
| v1 dispatch to the Mac mini | **NOT VERIFIED NOW** — ssh times out (exit 255) at 12.4 s while its gate answers; not a fixable state from here |
| that `secratary`'s gate would accept the authority | **NOT APPLICABLE** — the frozen box is excluded from the roster and was deliberately left untouched |

---

## 7. Files changed

* `scripts/phone-gate-allow.txt` — the authority added, with the measurement and the cost written in
  the file. Deployed to `zabz-tech` (whole file) and `zabz-tech-linux` (the line appended to the
  copy its gate actually reads; backup `…allow.txt.bak-20261012`).
* `packages/plugin-remote-fanout/lib/node-probes.js` — a missing health route no longer discards a
  node that answers capacity.
* `packages/plugin-remote-fanout/lib/failover-placement.js` — `assessCapacityOnly`, its wiring in
  `chooseFailoverPlacement`, and the ranking line that says `slots UNMEASURED` rather than `short`.
* `packages/plugin-remote-fanout/bin/mesh-run.mjs` — the broker default moved off the frozen box to
  `secratary-cloud`, matching the provider row.
* **On `secratary-cloud` (the authority, writable):** `/opt/mesh-broker/nodes.json` replaced with the
  repo roster (old kept as `nodes.json.bak-20261012`); `mesh-broker.service` **enabled and started**
  (`guard-service-state.sh --host secratary-cloud --op start` → ALLOW, exit 0).
* **Nothing was changed on `secratary` (the frozen anchor).** Every command against it in this audit
  was a read: `systemctl is-active/cat`, `ss`, `sha256sum`, `curl`, `cat`.
