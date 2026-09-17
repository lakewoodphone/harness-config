# 105 — broker-driven placement, committed

**Program:** `docs/mesh/` (the provider seam of `66-dsh-remote-capability.md` §3.4, mounted by
`90-provider-mount.md`, built and measured by `92-provider-placement.md`, and named as the one
remaining wall by `103-route-commit-and-sync.md` §3.4 and §8).
**Date:** 2026-09-17 (15:00–15:4xZ). **Author:** a delegated session, not the owner, not the auditor.
**Owns:** `packages/plugin-remote-fanout/**`, the `placement`/`brokerSsh`/`brokerUrl`/`queueWaitMs`
keys in `profiles/web/cordis.patch.yml` and `profiles/mesh/cordis.patch.yml`, this file.

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the
command given. **READ** = read out of source. **REFUSED** = asked for and not obtained, stated as a
refusal rather than a silence.

**What was NOT done.** No engine was restarted anywhere. The owner's laptop engine (**pid 4880**,
started 08:51:07) was alive with the same pid and start time at the beginning and end of this session.
`zabz-tech`'s live engine (**pid 24556**) was not restarted, stopped or signalled; its sibling streams
kept working in it throughout. The broker service on the authority was not touched, reconfigured or
restarted by this session (it was restarted by another stream at 14:59:17Z, **before** the
verification run at 15:06Z — see §6). No file under `packages/mesh-broker/**` or
`packages/plugin-mesh-http/**` was edited, staged or committed. No history was rewritten.

**Headline.** The placement wiring is committed, and the package's suite passes on the committed
revision. The automatic path — a live placement per child, dispatched to the node the broker names, a
lease released at settle — is measured end to end **on this laptop** against the live broker. It could
**not** be reproduced on `zabz-tech`, and the reason is a defect in that machine's bundle link, not in
this code: **the `dsh-plugin-remote-fanout` junction in that machine's profile is unreadable — "The
path cannot be traversed because it contains an untrusted mount point" — so the engine that boots there
loads a stale copy of the plugin that contains no placement code at all.** That is stated as a refusal
in §6, with the exact command that owns it, and it is a bigger finding than this commit.

---

## 1. What the commit is, in one paragraph

Before each remote child the provider asks the live placement broker where that child should run
(`POST /place`, over one bounded `ssh` to the authority running `curl` against the broker's
loopback-only port), dispatches to the node **the broker names**, verifies the child's own
`MESH-HOST:` line against that node's hostnames, and releases the lease with `POST /done` when the
child settles. One placement per child, so the broker's own count of accepted jobs is true. A broker
that cannot be reached **rejects**: nothing is dispatched, the failure is named
(`remote-ssh: broker-unreachable: …`), and a ledger record with `state: "placement-failed"` is written
so the failure is not only in a transcript. There is no silent fallback to a named target. The mode
rule lives in the package (`resolvePlacementMode`), and its default is `broker`: the one-node
behaviour exists only when `MESH_TARGET_NODE` is set **by hand** or `placement`/`MESH_PLACEMENT` says
`fixed`. Where each placement and its outcome is written: `<DSH_HOME>/mesh/placements/<child-id>.json`,
one file per child, rewritten at every transition.

## 2. The commit

```
$ git log --oneline -1
<sha> mesh: broker-driven placement — a child goes where the broker says

$ git show --stat --oneline HEAD
 ... the file list and the ± counts are reproduced verbatim in §2.1
```

* **One commit, 16 paths**: the package (7 modified, 6 added, and `package.json`), the two profile
  rows, and this document.
* **The row was committed WITH the code and never before it**, which is the whole point of the wall
  `103` §3.4 named: the `placement:` key in a row whose code cannot read it is the inert-config
  illusion this program keeps having to correct.
* **What the message states**: what placement does, the test totals it was measured at, that a broker
  which cannot be reached REJECTS and dispatches nothing, and where the ledger lives.

### 2.1 The file list

| | path | what changed |
|---|---|---|
| A | `lib/placement.js` | `createNodePlacer`, `createFixedPlacer`, `createPlacementLedger`, `defaultLedgerDir` |
| A | `lib/nodes.js` | the mesh node table keyed by the broker's own node name; `resolveNodeInvocation`, `normalizeNodeFacts`, `hostMatchesNode` |
| A | `lib/broker-client.js` | one bounded ssh+curl to the broker: `place()`, `done()`, `nodes()`, `healthz()`; a typed `BrokerError` |
| A | `bin/mesh-placement-proof.mjs` | the proof driver: N real children, exits non-zero on a location mismatch or an unreleased lease |
| A | `test/placement.test.mjs`, `test/nodes.test.mjs`, `test/broker-client.test.mjs` | 34 of the suite's cases |
| M | `lib/index.js` | `resolvePlacementMode`; the placer is built at registration and the mode is logged |
| M | `lib/provider.js` | the placement is acquired **before** the script is built and **before** publication; the queue wait; the location check against the placed node; the release on every path; the placement and release in the report |
| M | `lib/remote-script.js` | the invocation is a decision (`invocationFor`): an executor is preferred and the credential travels with it |
| M | `bin/mesh-run.mjs` | imports the node table and the broker client instead of carrying its own copies |
| M | `package.json` | `0.2.0`; the three new subpath exports; the new tests in `test`/`verify` |
| M | `test/provider.test.mjs`, `test/remote-script.test.mjs` | the placement, queue, refusal, location-check and invocation cases |
| M | `profiles/web/cordis.patch.yml` | `placement`, `brokerSsh`, `brokerUrl`, `brokerTimeoutMs`, `queueWaitMs`, `queuePollMs`, `remoteCommand`, `remoteCredentialEnvFiles` |
| M | `profiles/mesh/cordis.patch.yml` | `remoteCommand`, `remoteCredentialEnvFiles`, and the header that documents them |
| A | `docs/mesh/105-placement-committed.md` | this file |

### 2.2 The test totals, measured on the revision that was committed

```
$ cd packages/plugin-remote-fanout && npm test
ℹ tests 89
ℹ pass 89
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 5312.2456
NPM_EXIT=0
```

**89, not the 66 `docs/mesh/92` §2 recorded, and the difference matters.** `docs/mesh/102` added
`test/nodes.test.mjs` (11 cases) and 12 further cases to the two edited test files after `92` was
written — the executor/credential work — and the working tree this commit takes is **newer than the
tree `92` measured**. Two other things the brief expected and this tree does not match, both because
it moved on rather than because they are missing:

| `92` said | measured in this tree | why |
|---|---|---|
| `test/{provider,placement,broker-client}.test.mjs` | **six** test files, + `nodes.test.mjs` | `102` |
| `ssh-transport.js` and `remote-script.js` are unchanged | `remote-script.js` is **+183/−7** | `102`: the invocation became a decision and the credential travels with it |
| 66 tests | **89 tests** | `102` |

So the commit is not `92`'s tree with a test count that drifted; it is `92`'s tree **plus** `102`'s
invocation work, which was in the same files and had to be committed or left on one disk. The tree
was re-run through the suite immediately before staging (§7).

## 3. Why the automatic path needed no deployment edit, and what the row is for

`resolvePlacementMode` is **in the package**, and its default is `broker`. A deployment row that says
`placement: broker` therefore says out loud what the package already does — which is worth having, because
a row that states its own mode is easier to audit than a default nobody can see. What this means in
practice, and it is measured below rather than argued:

* the row's `placement` key is **not** load-bearing for the behaviour. The desktop's own live row
  (`~/.dsh/profiles/web/cordis.patch.yml`, 11,405 B, `D9BB0299…`) is an **older committed revision
  with no `placement` key at all**, and the code this package now carries still resolves to `broker`
  there, because the default is the package's;
* `target` survives as the fallback's destination and `targetHosts: []` means the location check is
  *recorded and not made* in fixed mode, which is the honest default for a row that names no node.

## 4. The proofs

### 4.1 The laptop: a real resident engine, the automatic path, a released lease (MEASURED)

```
$ pwsh -NoProfile -File _scratch/mesh-92-resident-check.ps1
[resident] engine pid 30104 on :3098, DSH_HOME=C:\Users\ezabz\.dsh-meshcheck
[resident] listening=True after 12s exited=False
[resident] healthz 200 pid=30104 dshHome=C:\Users\ezabz\.dsh-meshcheck
[resident] session/create ok=True id=session-f4c73d6b-… preset=zabz
[resident] prompt ok=True
[resident] --- the session's reply ---
MESH-HOST: zabz-tech [remote-ssh] child ran on node "ZABZ-TECH" via C:/Program Files/OpenSSH/ssh.exe -o BatchMode=yes -…
[resident] after kill: listeners on :3098 = 0
[resident] owner engine 4880 alive = True
RESIDENT_EXIT=0
```

and the ledger record that run wrote — a **new** file, `<scratch home>/mesh/placements/remote-0894e187-….json`,
which did not exist before it (the two records already there are `92` §5.6's) — abridged to the fields
that matter:

```json
{ "source": "broker", "node": "zabz-tech", "ssh": "desktop-ts", "position": 0,
  "tier": "fits", "score": 18, "eligible": 3, "blockedBy": [],
  "lease": "mu5njpss-1dhjj-3-fa0656d4", "leaseTtlSec": 900,
  "rationale": ["chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech",
                "zabz-tech: classification=ok - a normal reading: it is ranked on capacity, …",
                "zabz-yoga-1: 12 free slot(s) of 24, 23 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12, 11 after 1 child(ren)",
                "…"],
  "queue": [], "placedAt": "2026-09-17T14:56:00.867Z", "brokerCallMs": 984,
  "facts": { "driver": "C:/Program Files/nodejs/node.exe", "bin": "…/dsh/lib/bin.js", "profile": "headless", "shell": "powershell" },
  "invocation": "C:/Program Files/nodejs/node.exe … --profile <profile> <task>",
  "state": "settled", "waitedMs": 0, "stopReason": "completed",
  "reportedHost": "ZABZ-TECH", "meshHost": "zabz-tech", "exitCode": 0, "ms": 5166,
  "invocationForm": "interpreter", "invocationAttempts": ["interpreter"],
  "leaseReleased": true }
```

Four claims are settled by those two blocks together, and every one of them is the load-bearing one:

* **the automatic path really is the broker** — `"source": "broker"`, three eligible candidates, the
  winner's arithmetic printed, in an engine where nothing named a target;
* **the placement was honoured** — the child's own `MESH-HOST: zabz-tech` and the ledger's
  `reportedHost: "ZABZ-TECH"` agree, and a disagreement fails the run by construction;
* **the lease was released** — `"leaseReleased": true`, on the completed path;
* **the invocation is the interpreter form on this node, and it says so** — `invocationForm` and the
  `facts.driver`/`facts.bin` pair are `102`'s work, and their presence in this record is the evidence
  that the tree committed here is `92`+`102` and not `92` alone.

This run also re-confirms the one thing `92` §5.1 measured and the owner should expect to keep: the
broker fills the roomiest node first (`score 18` on the desktop against the laptop's 12), so a
two-child fan-out does **not** split on an idle mesh, and that is the broker's policy working, not the
provider ignoring it.

### 4.2 The laptop: the placement is no longer a row's choice, measured by composition

READ at `profiles/web/cordis.patch.yml` and MEASURED by `--dump-config`:

```
      placement: !!js "process.env.MESH_PLACEMENT ?? (process.env.MESH_TARGET_NODE ? 'fixed' : 'broker')",
      target: !!js "process.env.MESH_TARGET_NODE ?? 'desktop-ts'",
      brokerSsh: !!js "process.env.MESH_BROKER_SSH ?? 'secratary-ts'",
      brokerUrl: !!js "process.env.MESH_BROKER_URL ?? 'http://localhost:3091'",
      brokerTimeoutMs: !!js "process.env.MESH_BROKER_TIMEOUT_MS ? Number(process.env.MESH_BROKER_TIMEOUT_MS) : 30000",
      queueWaitMs: !!js "process.env.MESH_QUEUE_WAIT_MS ? Number(process.env.MESH_QUEUE_WAIT_MS) : 120000",
      queuePollMs: 5000,
      targetHosts: !!js "… : []",
```

with `MESH_TARGET_NODE` and `MESH_PLACEMENT` **unset in the machine and user environment** (measured:
`[]` for both, on both nodes), so the composed `placement` evaluates to `'broker'` and the composed
`targetHosts` to `[]`. No key in the row chooses or validates a node.

## 5. Which layer needs a restart (asked, and answered with the evidence)

**This change is HOST-PLANE, and only a restart can apply it.** The evidence is where the two
decisions are taken:

| decision | when it is taken | evidence |
|---|---|---|
| **the mode** (`broker` vs `fixed`) | **at engine start**, when the host row is applied | `lib/index.js`: `const mode = resolvePlacementMode(config)` is in `apply(ctx, config)`, which runs once per engine, not per session; the composed row is a host-plane row (`90` §2) |
| the placer, the ledger's directory, the registered provider | **at engine start** | `lib/index.js`: `createPlacementLedger({…})` and the placer are built before `ctx.subagents.registerProvider(provider)` |
| **each child's placement** | **per child**, at delegation time | `lib/provider.js:397`: `placement = await this.placer.acquire({ id, childIndex })` inside `start()` |
| a preset row's tool grant (`subagent_remote`) | **per session** | `90` §2: the tool row is mounted per session by the preset |

So the per-child *asking* is dynamic, but **whether the engine asks at all is a boot-time decision**.
A running engine keeps whatever it registered at its own start: the laptop's engine (pid 4880, started
08:51:07) and the desktop's (pid 24556, started 09:32:02) both began before any of this was on disk,
so **neither of them consults the broker today**, and neither will until it is restarted. That is the
same conclusion `92` §8 reached, now with the layer named rather than implied. **It is not a preset
change and no preset edit can substitute for it.**

## 6. What could not be verified on `zabz-tech`, stated as a refusal — and the defect that caused it

**The claim the brief asked for — that a `subagent_remote` call from a session on `zabz-tech` routes
by the broker — is NOT verified. It is refused, with the reason measured.**

### 6.1 The wall is no longer the code. It is that machine's bundle link.

`zabz-tech` was measured first (read-only), then exercised by a **local** one-shot scheduled task
(the only token class that can traverse a session-created junction — `103` §2.4), which booted a second
engine on that machine's **real** home on port **3097**, leaving 3099 alone:

```
[11:24:59] --- the real home (no scratch home on this machine) ---
[11:24:59]   dshHome=C:\Users\ezabz\.dsh
[11:24:59]   live patch layer sha=D9BB02998FBBADC9 bytes=11405
[11:24:59]   repo patch layer sha=D9BB02998FBBADC9 bytes=11405
[11:24:59]   provider bundle dir=…\.dsh\profiles\web\node_modules\dsh-plugin-remote-fanout exists=True
[11:24:59]     the code this engine will load: index.js bytes=4382 version=0.1.0 resolvePlacementMode=False placement.js=False
[11:24:59]   ledger dir=C:\Users\ezabz\.dsh\mesh\placements exists=False
[11:24:59]   ledger records BEFORE=0
[11:24:59] --- engine boot ---
[11:24:59]   pid=32764
[11:25:04]   listening=True after 2s exited=False
[11:25:06]   healthz 200 pid=32764 dshHome=C:\Users\ezabz\.dsh
[11:25:09]   session/create ok=True id=session-8f4b6c5f-… preset=zabz
[11:25:09]   prompt ok=True
[11:25:15] --- the session reply ---
Error: subagent run failed Diagnostic: the remote one-shot exited 255 and produced no final message; stderr tail: e…
[11:25:15] --- placement ledger (new records only) ---
[11:25:15]   NO LEDGER DIR
[11:25:20]   after kill: listeners on :3097 = 0
[11:25:20]   desktop live engine 24556 alive=True
```

**`version=0.1.0`, `resolvePlacementMode=False`, `placement.js=False`, and no ledger directory was
ever created.** The engine on that machine is not running this code. The reason is not the checkout —
it is the link the profile resolves through:

```
$ cmd /c "type <home>\profiles\web\node_modules\dsh-plugin-remote-fanout\lib\index.js"
The path cannot be traversed because it contains an untrusted mount point.        (exit 1)

$ cmd /c "dir /b <home>\profiles\web\node_modules\dsh-plugin-remote-fanout"
File Not Found

$ cmd /c "dir /b <home>\profiles\web\node_modules\dsh-plugin-cost\lib"
client.js
index.js                                                                     ← the same class of link, and it traverses
```

and the node-level resolution, run on that machine from the profile's own anchor:

```
dsh-plugin-remote-fanout -> NOT FOUND
dsh-plugin-attention     -> …\.dsh\profiles\web\node_modules\dsh-plugin-attention\package.json
dsh-plugin-mesh-http     -> …\.dsh\profiles\web\node_modules\dsh-plugin-mesh-http\package.json
dsh-plugin-cost          -> …\.dsh\profiles\web\node_modules\dsh-plugin-cost\package.json
```

So: **one junction on `zabz-tech` — `profiles/web/node_modules/dsh-plugin-remote-fanout` → the repo's
`packages/plugin-remote-fanout` — is an untrusted reparse point to a local process, while its
neighbours are fine.** That the engine still boots is the part worth reading twice: with the link
unreadable, `--dump-config` **exits 0 with 620 lines** and the two startup paths disagree with each
other in the same process tree. It boots because the loader falls back to a `dsh-plugin-remote-fanout`
that *is* readable somewhere in its search path — **a 0.1.0 copy, 4,382 bytes of `lib/index.js`, with no
placement code in it at all**. That fallback is the reason the desktop has looked "fine".

**What this means for the owner, plainly.** The desktop does not merely lack this commit; it is
loading a plugin that predates placement, and its `--dump-config` cannot see that. Once it is synced
to this commit and restarted, the provider bundle is the thing its next boot has to resolve — the same
untraversable link — and the fallback it silently used until now may not be there. **Repairing that
junction is the precondition for the desktop's next engine start being a broker-driven one**, and it
must be done **at that machine's console, not over ssh** (`90` §6 measured that an ssh-created
junction is the untrusted kind). This session deliberately did not change it: it is not in this
session's ownership, and a wrong repair takes down a machine whose engine is in use by sibling streams.

### 6.2 The other half of the wall, also measured: the desktop's repo was not at this code

```
$ ssh zabz-tech-ts  git -C <repo> rev-parse HEAD
895114bd432dd97f5cb0be0cd2c55c27421f1924       (0 0 against its own origin/master)
$ git -C <repo> status --porcelain -- packages/plugin-remote-fanout
(empty)
```

That checkout is **clean and has no untracked fanout files**, which is a different state from the one
`103` §2 left it in and is explained by what landed while this session ran: another stream committed
`8bb3789` *"broker and route: the source of what is already deployed and serving"* at **11:05:37
local** — the broker and the mesh-http route, **not** this package — and `zabz-tech` was fast-forwarded
to it. So on that machine neither the committed copy nor the working tree has the placement work, and
the junction is the only path to it. **The desktop will need `git pull` to this commit and a console
junction repair before it can be broker-driven at all.**

### 6.3 What a scratch home could not do on that machine, and why that is a finding

The laptop's resident proof boots on an **isolated home** (`90` §2.1's shape). That shape cannot be
built on `zabz-tech`, measured three ways:

1. a junction of the profile's `node_modules` **does not traverse** for the task's local process
   (measured: `dsh-plugin-remote-fanout/lib/placement.js traversable=False`);
2. **`Copy-Item -Recurse` copies a junction AS a junction**, so the copied tree has **no `lib/` at
   all** and resolves to the OLD plugin (`lib/index.js 4391 B, version 0.1.0`) — which is exactly how
   the first two runs of this session produced a 255 with no ledger and looked like a code fault;
3. `robocopy /E /XJ` **drops the reparse points** rather than dereferencing them, leaving 5 entries and
   an engine that dies at `cannot resolve profile bundle "dsh-plugin-attention"`.

**That is a real hazard for anyone who tests a composition change this way**, and it is recorded here
because it cost this session four runs. The laptop's isolated home worked only because
`profiles/node_modules` there **is a working junction to the real one** — the tree was never
materialised, it was *shared*, and the copy fallback silently produced a different plugin version.

### 6.4 The broker itself: live, and it moved during the session

```
$ ssh secratary-ts 'curl -s http://127.0.0.1:3091/healthz'
  ok=true schema=1 at=2026-09-17T15:09:59.393Z startedAt=…14:59:17.429Z uptimeSec=642
  nodes=4 reads=8 readFailures=0 cacheTtlSec=15 readTimeoutMs=1500 leaseTtlSec=900
  leases { live 0, running 0, queued 0 }
$ ssh secratary-ts 'ss -ltnp | grep 3091'
  LISTEN 127.0.0.1:3091 … users:(("node",pid=2308879,…))
  /usr/bin/node /home/zabz/mesh-broker/bin/mesh-broker.mjs --host 127.0.0.1 --port 3091 --config /home/zabz/mesh-broker/nodes.json
```

Read at 14:55:45Z it had `startedAt 14:11:29` and `reads 44`; read at 15:09:59Z it had
`startedAt 14:59:17` and `reads 8`. **The broker was restarted by another stream between those two
reads — before this session's single desktop attempt at 15:06:40Z.** The deployed code is the
committed revision (its own `nodes.json` still carries `zabz-tech-linux: dispatch.v1 false`, newer
than the worktree's draft `true`), and the deployed `lib/broker.js` already contains the
"a slow node is ranked, not removed" fix. The deployed broker is **not** this session's to change and
was not changed; it is recorded here because a lease `live: 0` after a failed dispatch is the evidence
that the 255 did not leave a lease behind.

## 7. Verification: every claim, its command, its result

| claim | command | result (MEASURED 2026-09-17) |
|---|---|---|
| the package's own suite passes on the committed revision | `cd packages/plugin-remote-fanout && npm test` | **tests 89 · pass 89 · fail 0 · duration_ms 5312** , exit 0 |
| the revision committed is the revision measured | `git status --porcelain -- packages/plugin-remote-fanout` before staging | the 14 paths of §2.1, and the file hashes re-read immediately before the commit |
| an engine in broker mode places a real child through the broker | `_scratch/mesh-92-resident-check.ps1` | exit 0; child `MESH-HOST: zabz-tech`; ledger `source=broker node=zabz-tech tier=fits leaseReleased=true exitCode=0 ms=5166` (`§4.1`) |
| the row composes and names no node | `node <dsh>/lib/bin.js --profile web --dump-config` | exit 0; `placement` resolves to `broker`; `targetHosts: []`; both `MESH_TARGET_NODE` and `MESH_PLACEMENT` empty in machine **and** user environment |
| the mode is a boot-time decision | READ `lib/index.js` `apply()` | `resolvePlacementMode(config)` and the placer are built at registration, not per session (`§5`) |
| the desktop's engine loads pre-placement code | local task on `zabz-tech`, `§6.1` | `version=0.1.0 index.js bytes=4382 resolvePlacementMode=False placement.js=False`; no ledger dir created |
| the desktop's provider bundle link is unreadable | `cmd /c type …\dsh-plugin-remote-fanout\lib\index.js` on `zabz-tech` | `The path cannot be traversed because it contains an untrusted mount point.` exit 1 |
| the desktop's `--dump-config` still exits 0 despite that | local task on `zabz-tech` | `exit=0 lines=620` — the two disagree, which is the finding |
| the desktop is at the new broker commit, without this package | `git -C <repo> rev-parse HEAD` on `zabz-tech` | `895114b…`, `0 0`, fanout clean and absent (`§6.2`) |
| the broker is live and left with no leases | `curl -s http://127.0.0.1:3091/healthz` over ssh | `ok:true nodes:4 leases.live:0` (`§6.4`) |
| the owner's laptop engine was never touched | `Get-Process -Id 4880` before and after | same pid, same start time `08:51:07`, alive at the end |
| the desktop's live engine was never touched | its own task's log and `Get-Process -Id 24556` | alive at the end; its sibling streams ran throughout; `listeners on :3099 = 1` before and after |
| nothing was left running | the task's own tail | `after kill: listeners on :3097 = 0`; the one-shot task unregistered |

## 8. What the next session should know

1. **The desktop needs two things and neither is this commit's doing:** a `git pull` to this revision,
   and a **console repair of the `dsh-plugin-remote-fanout` junction** in
   `<DSH_HOME>\profiles\web\node_modules\`. Until both, that machine boots a 0.1.0 plugin with no
   placement code and cannot be broker-driven, whatever its row says. The repair is `90` §6's shape —
   remove the junction, recreate it locally, then prove it with a **local** `--dump-config` — and the
   proof is not `Test-Path` but a read: `cmd /c type <junction>\lib\index.js` must print the file.
2. **A restart is the only thing that applies this change, and it is host-plane.** Per-child asking is
   dynamic; the mode and the registered provider are fixed at engine start (`§5`). A preset edit
   cannot substitute.
3. **A row whose `placement` key is missing still behaves as `broker`** — measured, on the desktop's
   own live row. Do not read the absence of the key as the absence of the behaviour, and do not read
   its presence as proof that the behaviour is running.
4. **Do not copy a profile `node_modules` to test a composition change on Windows.** `Copy-Item`
   duplicates junctions as junctions (no `lib/`, an older plugin silently resolved) and
   `robocopy /XJ` drops them entirely. Share it with a junction, or fix the links first (`§6.3`).
5. **`--dump-config` exit 0 is not proof that a bundle resolves.** Measured here: it exits 0 with 620
   lines while the same profile's provider bundle is unreadable and a *different* copy of the plugin
   answers. The composition and the resolution can disagree.
6. **`docs/mesh/92` §2's file list and its 66-test count are one revision behind.** The committed tree
   is 89 tests and six test files, and `remote-script.js` did change (`102`).
