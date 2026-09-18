# 104 — The node is enabled, and the second copy of the table is gone

**Program:** `docs/mesh/`. **Date:** 2026-09-17, 14:50–15:10Z (10:50–11:10 local).
**Author:** a delegated session, not the owner.
**Owns:** `packages/mesh-broker/nodes.json` + its deployment on the authority, the
`packages/mesh-broker/test/config.test.mjs` assertion that follows that flag,
`packages/plugin-mesh-http/bin/mesh-dispatch.mjs` + that package's tests, and this file.
**Reads with:** `102-linux-dispatch.md` (the dispatcher half, and the measurement this restores the
flag on), `98-broker-fixes.md` §4 (the roster half: the flag, and the two conditions that restore
it), `103-route-commit-and-sync.md` §3.4 (the code that is in no commit), `86-authority.md` §1 (the
broker's installer), `62-worker-runtime.md` §3.2 (why a version-stamped path rots),
`76-broker.md` §5 item 15 (a capability is a dated measurement).

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the
command given. **READ** = read out of source or a document, with the path. **REFUSED** = asked for
and not obtained, stated as a refusal rather than a silence. Every number carries the run that
produced it.

**What was NOT done.** No engine was started, stopped or restarted anywhere: the owner's laptop
engine **pid 4880** was alive with the same start time (`2026-09-17 08:51:07`) before the first
command and after the last; `zabz-tech`'s engine was not touched; and `zabz-tech-linux`'s engine was
not touched — every child this session ran there was a fresh `--profile headless` process. The
**broker service on the authority was restarted**, twice by its own installer and once by that
installer's SIGKILL test, which is the deploy path this package documents and the one thing the
brief names as expected. No `rm -rf` was run anywhere (the staging directory is new and unique, so
nothing was deleted to make room for it). No `git commit`, no `reset`, no `rebase`, no force push.
Nothing was published: the broker is loopback-only and `tailscale serve` still carries nothing on
3091. `packages/plugin-remote-fanout/**` was read, never edited. Two child agent turns were spent
(one per live dispatch proof) and both are quoted in full.

---

## 1. The two fixes in one line each

1. **`zabz-tech-linux` is `dispatch.v1: true` again, and the flag was restored by measurement, not
   by argument.** The `false` was correct when it was written and it answered the question the flag
   asks — *can a child the broker places here run, through the invocation the dispatcher actually
   runs* — so restoring it needed the invocation corrected **and** proven. Both are done:
   `plugin-remote-fanout/lib/nodes.js` invokes the node's own `dsh` executor by name (which sources
   `/etc/dsh-worker.env` itself) instead of the `nodeExe` + `bin.js` pair whose path does not exist
   on the machine (`102` §2, §4), and a real child through that row returns `MESH-HOST:
   zabz-tech-linux`, exit 0. Deployed with the package's own installer, proved live: the broker now
   places a 2-child fleet on that node as **`tier=fits`, `position 0`, `blockedBy: []`** where the
   shipped `false` row produced **`tier=transport`, `position 1`, `blockedBy: ["transport"]`** on the
   identical request.
2. **`plugin-mesh-http/bin/mesh-dispatch.mjs` no longer carries a copy of the node table.** It reads
   `packages/plugin-remote-fanout/lib/nodes.js` and derives only the view its callers need, so the
   rotted path — and the credential bypass that came with it — cannot exist in two places with two
   different lifetimes. **Option A of the two the brief offered, and §3 says why**, with the two
   measurements that made it the safe choice.

---

## 2. FIX 1 — the roster flag, its deployment, and the live proof

### 2.1 The roster change, verbatim

`packages/mesh-broker/nodes.json`, `nodes[zabz-tech-linux].dispatch`. Before and after, with the
byte-level proof that "before" is the exact state that was deployed by `98`:

```
before: 7384 bytes  sha256 6f46131a2cc373198503df594defda35e71cb39b3fb6cf50869d6ce198728032
        `ssh secratary-ts sha256sum /home/zabz/mesh-broker/nodes.json`
        -> 6f46131a2cc373198503df594defda35e71cb39b3fb6cf50869d6ce198728032   (identical)
after : 7654 bytes  sha256 6bc7134c403c4d8105c76ca0e33abff05be2efdf5b365f00f547aa06c819441b
```

So the diff below is against the exact tree the previous stream deployed, not against `HEAD` (whose
`nodes.json` is the PREVIOUS revision, `v1: true` with the 2026-09-16 note — which is why a plain
`git diff` shows no `v1` line at all and would be a misleading record here):

```diff
-        "v1": false,
+        "v1": true,
-        "measuredAt": "2026-09-17T14:00Z",
+        "measuredAt": "2026-09-17",
-        "evidence": "MEASURED BROKEN FOR v1 AS THE DISPATCHER ACTUALLY DISPATCHES, 2026-09-17
-                     13:58-14:06Z … SET BACK TO true when the dispatcher table is corrected …
-                     The transport itself is not the gap; the dispatcher's two paths are."   (2246 chars)
+        "evidence": "MEASURED WORKING FOR v1 THROUGH THE CORRECTED INVOCATION, 2026-09-17
+                     (14:34-15:05Z) … (1) THE INVOCATION IS CORRECTED AND THE ROTTED PATH IS GONE …
+                     (2) A REAL CHILD WAS DISPATCHED THROUGH THE WHOLE DISPATCHER AND RETURNED …
+                     (3) THE SAME COMMAND BEFORE THE FIX EXITED 1 … (4) The stale 2026-09-16 note …
+                     (5) THE FLAG TAKES EFFECT IN PLACEMENT … SET BACK TO false if …"        (2524 bytes)
```

The new string keeps the three things `76-broker.md` §5 item 15 asks a capability row to carry: the
dated measurement with its commands and results, the stale note it corrects (**"no Node runtime
yet"**, now marked FALSE), and — the addition this session made — **what would revoke the flag
again**, because a row that names only what restored it is a row that can only ever move one way.
`SET BACK TO false if the executor form is replaced by an explicit interpreter pair again, or if
/usr/local/bin/dsh or /etc/dsh-worker.env is removed from the node - re-measure, do not re-argue.`

**The test that follows the flag had to move with it, and that is the point of the test.**
`test/config.test.mjs` asserted `v1 === false` for this node, with the reason attached
(`98` §5 changed it when the flag went down; this session changed it back). It now asserts `true`,
asserts the evidence names the stale note it corrects, asserts it **carries the live dispatch that
restored the flag** (`MESH-HOST: zabz-tech-linux`), asserts it names the corrected invocation
(`command: 'dsh'`), and asserts it says what would revoke it. A flag and its own test cannot drift
apart silently in either direction.

### 2.2 The restoring measurement, re-taken rather than inherited

`102` measured it at 14:45–15:05Z. This session re-took the machine facts and **one real child turn**
before writing the flag, because a roster capability is a claim about the fleet, not a citation:

```
$ ssh linux-pc-ts 'command -v dsh; command -v node; readlink -f /usr/local/bin/node; node --version; dsh --version; ls -l /etc/dsh-worker.env; ls -l /home/zabz/.local/node-v24.12.0-linux-x64/bin/node; hostname'
/usr/local/bin/dsh
/usr/local/bin/node
/home/zabz/.local/node-v22.23.2-linux-x64/bin/node
v22.23.2
0.1.5-rc.1
-rw-r----- 1 root zabz 108 Sep 16 19:15 /etc/dsh-worker.env
ls: cannot access '/home/zabz/.local/node-v24.12.0-linux-x64/bin/node': No such file or directory
zabz-tech-linux
```

and, through the live modules (`_scratch/102-live-child.mjs`, MEASURED 2026-09-17 14:56Z):

```
node        = zabz-tech-linux  (ssh linux-pc-ts, shell posix)
form        = executor
command     = dsh
credential  = the executor sources /etc/dsh-worker.env itself
--- the program the target runs (stdout lines only) ---
# invocation form: executor — the executor sources /etc/dsh-worker.env itself
cd '/home/zabz/code'
dsh --profile headless 'Report where you ran, first, … --- task --- Run the shell command `hostname` …'
--- dispatching ---
transport   = ssh linux-pc-ts
exit        = 0 in 12099 ms (markerSettled=false)
host line   =    cwd = /home/zabz/code
framed      = true
--- child final message ---
MESH-HOST: zabz-tech-linux
zabz-tech-linux
--- stderr tail ---
dsh: reasoning:
The command printed "zabz-tech-linux". Now reply begins with MESH-HOST: zabz-tech-linux, …
```

**The rotted path is not in the program, and the child's own reasoning shows it ran the command** —
which is the distinction `102` §4 drew and this session keeps: a name a child can read in its prompt
proves nothing, a name its own shell printed does.

### 2.3 The deployment

The package's own installer, on the authority, from a staged copy — never from a working tree:

```
$ tar -czf %TEMP%\mesh-broker-104.tgz -C packages mesh-broker            # 80408 bytes, exit 0
$ scp ... secratary-ts:/tmp/mesh-broker-104.tgz                          # exit 0
$ ssh secratary-ts "mkdir -p /tmp/mesh-broker-104-20260917T1502Z && tar -xzf … --strip-components=1"
  EXTRACT_OK
```

**22/22 sha256, local vs staged** (`sha256sum` on the authority, `Get-FileHash` locally, both
manifests sorted and compared):

```
local=22 remote=22
22/22 IDENTICAL: the staged tree is byte-for-byte the tree that was tested
```

```
$ ssh secratary-ts "sudo bash /tmp/mesh-broker-104-20260917T1502Z/deploy/install-authority.sh /tmp/mesh-broker-104-20260917T1502Z"
== source and runtime ==
source   : /tmp/mesh-broker-104-20260917T1502Z
dest     : /home/zabz/mesh-broker
node     : v20.20.2  (/usr/bin/node)
host     : secratary  Linux 7.0.0-30-generic
PASS  the deployed copy passes its own suite: # tests 61 # pass 61 # fail 0
PASS  the deployed copy carries the per-node reserve and the loopback-enforcing unit
PASS  port 3091 is held by this service itself (MainPID 2308879); the restart in step 5 replaces it
PASS  the listening pid IS the systemd MainPID (2329466)
PASS  bound to 127.0.0.1 only
PASS  a request to this host's own LAN address (192.168.50.77) does NOT get through (curl exit 7)
PASS  a request to the tailnet address (100.84.72.88) does NOT get through (curl exit 7)
PASS  tailscale serve publishes nothing on 3091
PASS  the service can READ the mesh (at least one node answered its gate)   [nodes 4 | reads 4 | readFailures 0]
PASS  POST /place answered a placement   [place -> zabz-tech position 0 score 18 tier fits]
PASS  systemctl restart: MainPID 2329466 -> 2329561
PASS  SIGKILL: MainPID 2329561 -> 2329585, service active
20 passed, 0 failed   (2026-09-17T14:59:20Z)

$ ssh secratary-ts "bash …/deploy/verify-deploy.sh /tmp/mesh-broker-104-20260917T1502Z"
running : pid 2329585: /usr/bin/node /home/zabz/mesh-broker/bin/mesh-broker.mjs --host 127.0.0.1 --port 3091 --config /home/zabz/mesh-broker/nodes.json
same    the running process IS the deployed copy
NO DRIFT: the deployed tree, the installed unit and the running process all agree.
```

The service went `2308879` (the `98` build) → `2329466` → `2329561` (supervised restart) → `2329585`
(post-SIGKILL). **Only the broker was restarted.**

### 2.4 The live proof: eligible, and `tier=fits` rather than `tier=transport`

A read-only probe on the authority against `http://127.0.0.1:3091` (`_scratch/104-live-probe.mjs`),
at **2026-09-17T15:00:29Z**:

```
GET /nodes?fresh=1 -> HTTP 200  reads=8 readFailures=0
  zabz-tech          state=ok  slots= 18 free= 18  transport.v1=true  measuredAt=2026-09-16
  zabz-yoga-1        state=ok  slots= 12 free= 12  transport.v1=true  measuredAt=2026-09-16
  zabz-tech-linux    state=ok  slots=  4 free=  4  transport.v1=true  measuredAt=2026-09-17
  secratary          state=ok  slots=  1 free=  1  transport.v1=null  measuredAt=null

zabz-tech-linux.transport.v1         = true
zabz-tech-linux.transport.measuredAt = "2026-09-17"
zabz-tech-linux.transport.evidence   = 2520 chars, beginning
  "MEASURED WORKING FOR v1 THROUGH THE CORRECTED INVOCATION, 2026-09-17 (14:34-15:05Z) …"

=== PLACEMENT 1 (whole mesh, fleet of 2) ===
POST /place -> HTTP 200 at 2026-09-17T15:00:29.661Z
node=zabz-tech position=0 score=18 tier=fits eligible=3 blockedBy=[]
  chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech
  …
  zabz-yoga-1: 12 free slot(s) of 24, … -> effective 12, 10 after 2 child(ren)
  zabz-tech-linux: 4 free slot(s) of 24, 24 memory slot(s), 4 core slot(s) of 6 physical x 0.75 -> effective 4, 2 after 2 child(ren)
  secratary: … -1 after 2 child(ren), swap 94.3% used: effective slots halved, transport v1 unmeasured
/done -> HTTP 200 {"ok":true,"released":true,…,"leases":{"live":0,…}}

=== PLACEMENT 2 (zabz-tech-linux as the only candidate, fleet of 2) ===
POST /place -> HTTP 200 at 2026-09-17T15:00:29.671Z
node=zabz-tech-linux position=0 score=4 tier=fits eligible=1 blockedBy=[]
  chosen from 4 configured node(s): 0 unreachable, 3 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech-linux
  zabz-tech-linux: disk 21 GiB free on /home/zabz/code vs 21 GiB required (20 GiB fleet floor + 0 GiB declared worktree + 0.5 GiB/child x 2 child(ren)) -> gate passes
  zabz-tech-linux: classification=ok - a normal reading: it is ranked on capacity, …
  zabz-tech-linux: transport v1 (ssh --profile headless) MEASURED to work (measured 2026-09-17): MEASURED WORKING FOR v1 …
  zabz-tech-linux: 4 free slot(s) - 2 child(ren) = 2 >= 0 -> fits now
  position 0: 4 free slot(s) - 2 child(ren) = 2 >= 0 on a reachable node -> start now
/done -> HTTP 200 {"ok":true,"released":true,…,"leases":{"live":0,…}}

HEALTHZ at 2026-09-17T15:00:29.679Z: {"ok":true,…,"leases":{"live":0,…}}
```

Two things in placement 1 are worth reading rather than skimming:

* **`eligible=3`, and the node that counts is the one that used to be missing.** The pool is every
  dispatchable node that can start THIS job, and `secratary` (1 free slot against 2 children) is
  correctly not in it. Before the flip the pool was 2 — the linux node was excluded by
  `dispatchOk`, not by capacity.
* **The linux node's own line in the rationale no longer carries `transport v1 MEASURED BROKEN`.**
  It now reads as ordinary capacity arithmetic (`4 free slot(s) … 2 after 2 child(ren)`), because
  `otherLine()` only prints a transport bit for a node measured broken or unmeasured.

### 2.5 The same request against the shipped `false` row — measured, not argued

The live broker cannot be asked to demonstrate the "before" state now, and re-deploying the old row
to prove a negative would disturb a live service. So the before state was exercised the way `98` §2.5
exercised defect 1: **the shipped configuration materialised from the authority's own deployed copy,
and the broker's own `place()` run in process against the same real mesh**
(`_scratch/104-before-contrast.mjs`, ~15:01Z):

```
config            : _scratch/104-nodes-before.json      (sha256 6f46131a…, the 14:11Z deployed copy)
zabz-tech-linux   : dispatch.v1=false measuredAt="2026-09-17T14:00Z"
GET /nodes        : reads=4 readFailures=0
  zabz-tech          state=ok free= 18 transport.v1=true
  zabz-yoga-1        state=ok free= 12 transport.v1=true
  zabz-tech-linux    state=ok free=  4 transport.v1=false
  secratary          state=ok free=  1 transport.v1=null

POST /place {fleet, 2 children, the other three excluded}
node=zabz-tech-linux position=1 score=4 tier=transport eligible=1 blockedBy=["transport"]
  zabz-tech-linux: disk 21 GiB free on /home/zabz/code vs 21 GiB required (…) -> gate passes
  zabz-tech-linux: transport v1 (ssh --profile headless) MEASURED BROKEN (measured 2026-09-17T14:00Z): …
  no node that can take v1 work can start this now; zabz-tech-linux is the best of the candidates that cannot
    (transport.v1=false), chosen despite transport=unavailable because nothing else is eligible
    -> placed there, QUEUED rather than refused (queue, never amputate)
  position 1: 4 free slot(s) - 2 child(ren) = 2 (it would fit), queued because transport; …
startNow=NO - this is a queue position
```

**Same request, same mesh, one minute apart, one field different:**

| | before (`v1: false`) | after (live, `v1: true`) |
|---|---|---|
| node | `zabz-tech-linux` | `zabz-tech-linux` |
| **tier** | **`transport`** | **`fits`** |
| position | **1 (queued)** | **0 (start now)** |
| `blockedBy` | **`["transport"]`** | **`[]`** |
| disk gate | passes (21 GiB vs 21 GiB) | passes (21 GiB vs 21 GiB) |
| free slots | 4 | 4 |

The flag is the only difference between a placement the provider **starts** and one it **queues**:
`98` §4.3's point, now measured in both directions rather than asserted.

---

## 3. FIX 2 — the second copy of the table, and which option was chosen

### 3.1 The choice: read the shared table (option A), not "correct it identically + agree by test"

**Chosen: A.** `bin/mesh-dispatch.mjs` now imports `NODES` and `resolveNodeInvocation()` from
`packages/plugin-remote-fanout/lib/nodes.js` and derives the view its callers need. Four reasons, in
the order they decided it:

1. **Reading across packages is possible in this bundle's resolution, and the proof is already in
   this package.** `test/dead-target-fallback.mjs` has imported
   `../../plugin-remote-fanout/lib/provider.js` and `…/lib/ssh-transport.js` since 2026-09-17
   (`docs/mesh/83-http-transport.md` §8 is that proof's record), and the brief's condition — "if
   reading across packages is not possible in that bundle's resolution" — is therefore not met.
   Nothing bundles `bin/**`: the plugin bundle mounts `lib/index.js`, whose import graph contains no
   node table at all.
2. **The junction is not a trap, and that was measured rather than assumed.** The package is mounted
   as a junction at `~/.dsh/profiles/web/node_modules/dsh-plugin-mesh-http`. Node resolves a module's
   REAL path by default — there is no `--preserve-symlinks` in play — so a relative import resolves
   against the checkout, not against the junction. MEASURED on ZABZ-YOGA 2026-09-17 with a junction
   whose two package dirs sat in a temp tree
   (`_scratch/104-junction-test/`): `import.meta.url` printed the REAL path
   (`…/104-junction-test/real/probe/bin/probe.mjs`) and the sibling import resolved.
3. **A path-only correction would have left the copy wrong in a second way.** The rotted path is only
   half of the defect: a dispatcher that names an interpreter bypasses the `dsh` wrapper that sources
   the credential, and dies `MISSING_CREDENTIAL` **even with the correct path** (`102` §2 row 1,
   §4 run 3). "Correct it identically" would have produced a table whose linux row is a *different*
   broken invocation of the same node. Reading the shared table inherits the executor form, which is
   the fix.
4. **The premise is the brief's own: one table, one place to be right.** The two copies had
   different lifetimes and no mechanism to notice each other, which is exactly how the same path
   rotted in one and was fixed in the other.

The agreement test the brief offered as the alternative is not needed — there is nothing left to
disagree — but the assertion that the two are the same table is kept, and §3.4 lists the four tests
that replace it.

### 3.2 What changed on the wire, before and after

The thing that rotted was a **string**. For `zabz-tech-linux`'s v1 (ssh) fallback:

```sh
# BEFORE — the second copy, as shipped
exec '/home/zabz/.local/node-v24.12.0-linux-x64/bin/node' '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js' --profile headless '<task>'
#   ^ does not exist on the machine: exit 127, `sh: 6: …: not found`

# AFTER — the shared table's resolved invocation
exec dsh --profile headless '<task>'
#   ^ the node's own wrapper: resolves the interpreter from $HOME and sources /etc/dsh-worker.env itself
```

The interpreter branch is kept, and kept honest, for a node that has no executor: it now sources the
declared credential file **first**, exactly as `remote-script.js` does it —
`if [ -r '/etc/dsh-worker.env' ]; then set -a; . …; set +a; fi` — and the executor branch sources
nothing, because the executor already did. A row that cannot resolve an invocation at all (a
`driver` with no `bin.js`) now **refuses to spawn** instead of reporting an exit code for a command
that could not work.

The v1 program is a **pure function now** (`buildV1Program({ facts, task })`), because a string built
inside a spawned promise can only be checked against a real node, while the same string returned as a
value can be asserted on for the whole fleet — which is what §3.4 does.

### 3.3 The dispatch record now says HOW, not only WHERE

`102` §2.2 item 2's lesson, applied here: a report that names a node is worth nothing if it does not
say how the child was launched there. The `start` and `fallback` records carry

```
"invocation":"dsh (the node's own executor: the executor sources /etc/dsh-worker.env itself)","invocationForm":"executor"
```

### 3.4 The tests

`packages/plugin-mesh-http/test/mesh-http.test.mjs` gained four tests (36 → **40**), and each one is
the assertion that would have caught the second copy rather than a restatement of it:

```
✔ the dispatcher keeps no node table of its own: its table is a view of the shared one
✔ no node is launched through a version-stamped interpreter path - the shape that rotted
✔ the linux node's v1 program invokes the executor by name and sources nothing itself
✔ the interpreter form sources its credential file first, and a half-pair refuses to spawn
```

The first asserts every row of the derived table equals the shared row field by field, and — as
**source** — that `bin/mesh-dispatch.mjs` imports the shared module and contains no hand-written
`nodeExe:`/`dshBin:` row, which is the fingerprint of the copy that rotted. The second walks the
whole table and fails on any version-stamped path **that would be executed** (the row's `verified`
string deliberately still names the dead path: that is the record of what was corrected). The third
asserts the exact program string for this node. The fourth proves the credential-sourcing order and
proves a half-pair refuses.

`test/concurrency-sweep.mjs` — the v1 concurrency rig — read `facts.nodeExe`/`facts.dshBin` from the
deleted copy; it now takes the invocation from the shared table and **refuses a POSIX node by name**,
because that rig drives a PowerShell `-EncodedCommand` and a node it cannot run a program on must not
be "measured" by it.

**One finding about the suite itself.** The brief's `node --test` is not a safe command in that
package: bare `node --test` collects **every `.mjs` under `test/`**, including the measurement rigs
`concurrency-sweep.mjs` and `run-level.mjs`, which fire real fleets at real nodes. Measured with
same-named probe files in a temp directory:

```
$ node --test        (in a scratch dir with the package's test file names)
✔ test\concurrency-sweep.mjs   ✔ test\dead-target-fallback.mjs   ✔ test\mesh-http.test.mjs   ✔ test\run-level.mjs
ℹ tests 4 · pass 4 · fail 0
```

So the suite is the package's own scoped command (`npm test` → `node --test
test/mesh-http.test.mjs`) and the package's build/verification equivalent is `npm run verify`
(`node --check` on every source file + that suite). `plugin-mesh-http` has **no build script** — the
only `scripts/build.mjs` in this repository belongs to `plugin-cost` — and it generates no artefact,
so there was nothing generated to rebuild and nothing was hand-edited into a bundle.

### 3.5 The live proof

`bin/mesh-dispatch.mjs` against the node, on the v1 path it owns (MEASURED 2026-09-17T14:58:23Z):

```
$ node bin/mesh-dispatch.mjs -Node zabz-tech-linux -Transport v1 -Json -TimeoutSec 300 -Prompt '… run hostname …'
{"phase":"result","runId":"2026-09-17T14-58-23-148Z","node":"zabz-tech-linux","transport":"ssh","ok":true,
 "childExitCode":0,"timedOut":false,"childHosts":["zabz-tech-linux"],"disagreements":[],"meshHostLines":1,"ms":5776}

the same run's JSONL record (…-dispatch.jsonl):
{"phase":"start",…,"ssh":"linux-pc-ts","invocation":"dsh (the node's own executor: the executor sources /etc/dsh-worker.env itself)","invocationForm":"executor",…}
{"phase":"fallback","outcome":"using ssh",…,"invocation":"dsh (the node's own executor: …)","invocationForm":"executor"}
{"phase":"run","transport":"ssh","ok":true,"exitCode":0,…,"childHosts":["zabz-tech-linux"],"disagreements":[],"meshHostLines":1}
```

**exit 0, one `MESH-HOST:` line, naming `zabz-tech-linux`, zero disagreements** — from the package
and the file that carried the rotted path, through the fixed program. `-Transport v1` was named
explicitly rather than letting the v2 probe decide, because: `GET
https://zabz-tech-linux.tail93e6e6.ts.net/mesh/health` answers **HTTP 404** (the gate answers; the
node has no `mesh-http` route), so **every** dispatch to this node is v1 and this is the path that
had to be fixed. That is not a limitation of the transport — it is why this file matters.

---

## 4. Two things found on the way that are NOT this session's to fix

Both are reported as measurements with their raw output, not diagnosed, because neither is in the
paths this session owns.

### 4.1 A child on this node that delegates further fails, twice, with `MISSING_CREDENTIAL`

The first live dispatch was the `102` §4 run 2 shape — *delegate this to a subagent via
`subagent_remote`* — and it failed while the node itself was fine. The child's own final message,
verbatim:

```
The remote delegation failed — twice, identically — so I have no `MESH-HOST` value to report.

Both `subagent_remote` calls reached the target node but the child agent could not start:

placement      = FIXED TARGET — "zabz-tech-linux" from configuration
transport cwd  = /home/zabz
target profile = headless
dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official";
     store DEEPSEEK_API_KEY through the credentials service (the web Models page writes it),
     or export DEEPSEEK_API_KEY in the launching environment
exit = 1 (~3 s)
--- child final message ---   (empty)
```

`mesh-run`'s own verdict on the same run was `exitCode 0` for the outer turn,
`only 0 MESH-HOST lines for 1 children`, `disagreements: []`, `childHosts: []`.

**What this is, stated no more strongly than the evidence allows:** the failure text is
`102` §4 run 3's failure mode one layer out — an inner dispatch through the **interpreter form** with
no credential source. What this session did **not** establish is which machine ran the inner dispatch
and where its plugin came from: the node's `headless` profile declares only `dsh-base` and
`dsh-headless` (`~/.dsh/profiles/headless/package.json`), and `/home/zabz/code/harness-config/packages/plugin-remote-fanout/lib/nodes.js`
does not exist on that machine — which is `103` §3.4's fact, one node over: the broker/placement
wiring exists in **no commit**, so a node synced from the branch does not have it. A future session
should measure the inner dispatch before acting on this; it is the same class of defect this document
fixes and it is not fixed by this document.

**What IS established:** this is not the node's v1 dispatch failing. The same node, minutes later,
ran a child that executed `hostname` and returned the right name (§2.2), and the package's own
dispatcher returned exit 0 with a verified `MESH-HOST:` line (§3.5).

### 4.2 One child answered the location question without running the tool, and the check caught it

The second live dispatch (`mesh-run`, the hostname shape) produced

```
----- dispatcher output -----
MESH-HOST: zabz-yoga
zabz-yoga
mesh-run: {"phase":"verify","meshHostLines":1,"childHosts":["zabz-yoga"],"disagreements":["zabz-yoga"],"ok":false}
mesh-run: {"phase":"result","outcome":"failed","reason":"location disagreement: zabz-yoga not on zabz-tech-linux"}
```

The child's own reasoning stream stops at *"Let me run it."* and never reports an output — and
**the string `zabz-yoga` exists nowhere on that machine**: `/etc/hostname` is `zabz-tech-linux`,
`HOSTNAME=zabz-tech-linux`, and `grep -ril zabz-yoga /home/zabz/.dsh/ /home/zabz/dsh-engine/`
returns nothing. So the name was not measured, it was produced — and `mesh-run` rejected the run
rather than reporting a completion. This is the `MESH-HOST:` check earning its place, and it is the
caution that goes with it: **a child's claim about where it ran is not a measurement of where it
ran.** A third dispatch (the framed instrument, §2.2) shows the machine fact and the child fact
agreeing when the child does the work.

---

## 5. Verification: every claim, its command, its result

| claim | command | result (MEASURED, 2026-09-17 unless stated) |
|---|---|---|
| the flag is `true`, with the restoring measurement | `packages/mesh-broker/nodes.json` + `ssh secratary-ts curl /nodes?fresh=1` | `transport.v1=true measuredAt="2026-09-17"`, evidence 2520 chars |
| the roster change is against the deployed tree, not against `HEAD` | `sha256sum` on the authority's `nodes.json` before the edit | `6f46131a…` = the local pre-edit hash; after: `6bc7134c…`, 7654 bytes |
| the flag's own test moved with it and still passes | `cd packages/mesh-broker && npm test` | **tests 61 · pass 61 · fail 0** · duration_ms 4926.7 |
| the copy deployed is the copy tested | 22 file hashes, local vs staged | **22/22 IDENTICAL** |
| the deployed copy passes its own suite (not the exit code of a copy) | `deploy/install-authority.sh` step 3 | `# tests 61 # pass 61 # fail 0`, then **20 passed, 0 failed** |
| the broker was restarted and is running the new code | installer steps 5/9 + `verify-deploy.sh` | `2308879 → 2329466 → 2329561 → 2329585`, `service active`, **NO DRIFT** |
| the node is eligible and placed as `fits`, not `transport` | live `POST /place {fleet, 2 children}`, whole mesh then alone | whole mesh `eligible=3 tier=fits`; alone `node=zabz-tech-linux position=0 tier=fits eligible=1 blockedBy=[]` |
| the shipped `false` row produced the opposite, on the same request | `node _scratch/104-before-contrast.mjs` (the deployed `false` row, in process) | `position=1 tier=transport eligible=1 blockedBy=["transport"]` |
| no lease was left holding a slot | `POST /done` for both placements + `GET /healthz` | both `released:true`; `leases.live=0` |
| a real child runs on the node through the corrected row | `node _scratch/102-live-child.mjs zabz-tech-linux` | exit 0 in 12099 ms, framed, `MESH-HOST: zabz-tech-linux`, child's stderr: *"The command printed \"zabz-tech-linux\""* |
| the second copy is gone and its replacement runs | `node bin/mesh-dispatch.mjs -Node zabz-tech-linux -Transport v1` | `ok:true, childExitCode:0, childHosts:["zabz-tech-linux"], disagreements:[], meshHostLines:1, ms:5776` |
| the package's suite passes, with the four new tests | `cd packages/plugin-mesh-http && npm test` | **tests 40 · pass 40 · fail 0** (36 before) |
| every source file still parses | `npm run verify` | exit **0** |
| bare `node --test` in that package is not its suite | probe with the package's file names in a scratch dir | it collects `concurrency-sweep.mjs` and `run-level.mjs` too — the measurement rigs |
| the node has no v2 route, so v1 is its whole dispatch path | `curl https://zabz-tech-linux.tail93e6e6.ts.net/mesh/health` | **HTTP 404** (the gate answers; there is no route) |
| the owner's engine was never touched | `Get-Process -Id 4880` | alive, same start time `2026-09-17 08:51:07` |
| no other node was touched | `ps`/`Get-Process` on the desktop and the linux node; no ssh to `desktop-ts` at all | nothing started or stopped on either |

---

## 6. What could not be verified, stated as refusals

* **A child turn through `subagent_remote` on `zabz-tech-linux`.** Attempted, and it failed —
  §4.1 — for a reason this session did not diagnose. Everything the roster flag claims is proven;
  the *nested* case is not.
* **`markerSettled` on a POSIX run.** Both live runs settled on the ssh client's own exit
  (`markerSettled=false`) rather than on the completion frame, so the frame-poll path was not
  exercised on this node. The runs completed correctly; `102` §7 recorded the same observation.
* **The `transport host` line on this node's POSIX runs.** The framed instrument printed
  `host line = ` (empty) with `framed = true`. The machine fact came from the child's own shell
  output instead (§2.2). A future session should not read the empty line as a failure of the run.
* **`secratary`'s v1 transport.** Still `null`, untouched, and honestly so: it is a `node v20.20.2`
  box with no `headless` profile, and changing the flag without a measurement would falsify it.
* **`lakewooechsmini`.** Not in the roster, not measured, not touched.
* **The linux node's dispatch under load.** One child at a time was measured. Its 4 effective slots
  and 21 GiB free disk are `GET /nodes` readings, not a concurrency measurement, and its concurrency
  ceiling as a *worker* (as opposed to as the `mesh-http` route's client) has never been measured.
* **Whether the second copy of this table exists anywhere else.** A grep over `harness-config` for
  `node-v24.12.0-linux-x64` returns: historical documents (`62`, `98`, `102`), places that name it as
  ABSENT or reconstruct the old shape to prove the check catches it
  (`plugin-remote-fanout/lib/nodes.js`'s `verified`, `test/nodes.test.mjs:221`,
  `test/remote-script.test.mjs:119`), `probe-node-posix.sh` (a POSIX probe that tries a LIST of
  candidate interpreters — not a dispatch table), this document, and this session's `_scratch/`.
  **No dispatch table still names it as the thing to run** — but this session checked the
  repository, not the fleet's checkouts, and `103` §3.4 measured that most of the placement wiring is
  in no commit at all.
* **The laptop's tailnet path.** `98` §3.1's `slow`/`unreachable` alternation was not re-measured.
  Every read in this session's window answered.

---

## 7. What the next session should know

1. **`zabz-tech-linux` is a v1 worker again, and the flag is a dated measurement in both directions.**
   Do not re-flip it without re-measuring the executor form; the row says exactly which change would
   revoke it (`SET BACK TO false if …`), and `nodes.json` + `test/config.test.mjs` moved together.
2. **The broker on the authority holds a COPY of `packages/mesh-broker/**`.** Deploy with
   `sudo bash deploy/install-authority.sh <staged-tree>` and check with
   `bash deploy/verify-deploy.sh <staged-tree>`; both are idempotent, the installer runs the deployed
   copy's own suite, and `verify-deploy.sh` is what catches silent drift. The staged tree used here
   is still at `/tmp/mesh-broker-104-20260917T1502Z` on the authority (and `/tmp/104-live-probe.mjs`).
3. **There is ONE node table: `packages/plugin-remote-fanout/lib/nodes.js`.** `bin/mesh-run.mjs`, the
   provider and `plugin-mesh-http/bin/mesh-dispatch.mjs` all read it. If you add a node, add its row
   there and nowhere else — and re-run `node bin/install-mesh-profile.mjs` (`102` §8 item 3), because
   a child engine boots its own provider from its own profile.
4. **Do not put a version-stamped interpreter path in any table.** `test/nodes.test.mjs` (fanout) and
   the new test in `mesh-http.test.mjs` both fail on one now, and they fail on *the string that would
   be executed* rather than on the row's prose.
5. **`npm test` in `plugin-mesh-http`, never bare `node --test`** — the latter collects the
   measurement rigs (§3.4's last row).
6. **§4.1 is an open defect of the same class as the one this document closes**, one layer out: a
   child that runs on a node and delegates further. It is not the node and it is not the flag.
