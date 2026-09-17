# 103 — The route's commit, the desktop's sync, and the row that must name no node

**Program:** `docs/mesh/`. **Date:** 2026-09-17, 14:2x–14:5xZ (10:2x–10:5x local).
**Author:** a delegated session, not the owner, not the auditor, not the author of any `docs/mesh/9x`.
**Owns:** the commit of `packages/plugin-mesh-http/**`, the sync on `zabz-tech`, the provider row's
*target configuration*, and this file. Nothing else.

**Headline.** The transport v2 route's newest revision existed in **no commit** — it was the working tree
on ZABZ-YOGA and untracked files on `zabz-tech`, byte-identical on seven files, and `origin/master` held
**older** blobs for all seven. It is committed (`7ea1e85`, 36/36 tests passing) and pushed. That unblocked
`zabz-tech`, which was **30 commits behind** and is now **at the tip, fast-forwarded, with 28 files
preserved and `--dump-config` exiting 0 on both sides.** The provider row's `targetHosts` default no
longer names a node. **What could not be done is also stated: broker-driven placement exists in no commit,
so a `subagent_remote` call from `zabz-tech` still self-dispatches, and no configuration can change that
until that code is committed.**

**What was NOT done.** No engine was restarted anywhere — not ZABZ-YOGA's (pid 4880, the owner's live work)
and not ZABZ-TECH's (pid 24556). No process was killed that this session did not start. No history was
rewritten: no `reset`, no `rebase`, no `--force`, no `clean`. `zabz-tech`'s sync was a `--ff-only`
fast-forward. Nothing under `packages/plugin-remote-fanout/**` was edited, committed or reverted, and
`profiles/web/cordis.patch.yml`'s placement block — another stream's in-flight work, written 6 minutes
before this file — was left exactly as found except for the one line this session owns.

---

## 1. JOB 1 — the commit, and what it protected

### 1.1 What v0.2.0 is, and what it was measured at

Documented in full in `docs/mesh/93-transport-concurrency.md` (which a sibling stream committed as part of
`a446cbb` while this session ran — see §8). In one paragraph: **the route's hard ceiling of one agent per
node is gone.** The limit is derived from the node's own machine, `max(1, min(cpu, mem, declared, hard))`,
and a request beyond it is **not refused — it is given a position and served in arrival order.** Measured on
`zabz-tech` at 13:53Z from that node's own counters and its own process list: **limit 8** (cpu binds:
`floor(32 logical × 0.42 ÷ 1.68)`), **12 simultaneous requests → 8 admitted immediately, 4 queued at
positions 1–4, 12/12 answered, 0 refused, 12/12 reporting the correct node**; the target's process list
peaked at **8** children and never 9, and the node's own accounting reported `maxInFlightSeen = 8`; commit
**366 MiB/turn** against a predicted 403 (CI 270–533), **pagefile 0 % in all 39 samples**, disk queue **0**,
loop-lag maximum **unchanged at 17 ms**. The one remaining `429` is a wait budget, not a capacity refusal.
The same revision carries the two measured identity fixes in `lib/node-identity.js` — a degraded boot-time
tailnet read is retried instead of memoised for the process's life, and `nodeSource` now names the field
that actually supplied the value — plus `identityDegraded`/`identityReason` so a dispatcher can decline to
place work on a name a node cannot corroborate.

### 1.2 The commit, and the measurement that says it is the newest revision

```
$ git rev-parse HEAD                              → 31543041908722ce0a98089fb1069b06095891f4  (= origin/master, 0 0)
$ git hash-object <path>              # worktree       vs  git rev-parse origin/master:<path>
  lib/node-identity.js     02b7e5c6   vs  89b5c327
  lib/index.js             c020b30d   vs  75658086
  lib/runner.js            d70dbfd1   vs  60636d1c
  lib/handler.js           15b79731   vs  833833fd
  bin/mesh-http.mjs        016d06eb   vs  e64a0c0f
  bin/mesh-dispatch.mjs    035e41a8   vs  770833d5
  test/mesh-http.test.mjs  43278d6d   vs  e6bcb322
```

Seven of seven match the seven hashes `99` §3.2 recorded as the desktop's untracked files, and all seven of
`origin/master`'s blobs are **different**. The worktree was the newest revision; the branch held the older
one; and a `reset`, a `clean` or a fast-forward would have replaced a proved fix with the revision it
replaced — on the node the proof was taken on, silently, at its next restart.

**Test totals, measured before the commit (do not commit a broken tree):**

```
$ node --test packages/plugin-mesh-http/test/mesh-http.test.mjs
  tests 36 · pass 36 · fail 0 · cancelled 0 · skipped 0 · todo 0 · duration_ms 16752.6082 · exit 0
$ node --check lib/concurrency.js ; node --check test/concurrency-sweep.mjs ; node --check test/run-level.mjs
  ok · ok · ok
```

**Committed:** `7ea1e8508e9af1ee1a6e5913e121b690ec2cb8b4`, 12 files, **+1810 / −195**. The seven blobs were
re-verified **after** the commit and still read `02b7e5c6 / c020b30d / d70dbfd1 / 15b79731 / 016d06eb /
035e41a8 / 43278d6d`.

| | path | |
|---|---|---|
| M | `bin/mesh-dispatch.mjs` | transport order is a documented decision; a busy node queues instead of failing over |
| M | `bin/mesh-http.mjs` | `check`/`probe` report the limit, its arithmetic, and identity state |
| A | `lib/concurrency.js` | `deriveConcurrencyLimit`, commit headroom, the node's capacity contract |
| M | `lib/handler.js` | `queue {position, waitedMs, limit}`; `concurrency` in `GET /mesh/health` |
| M | `lib/index.js` | `VERSION = '0.2.0'`; every knob env-overridable |
| M | `lib/node-identity.js` | the two measured identity defects |
| M | `lib/runner.js` | `maxConcurrent` + FIFO; admission synchronous, slot reserved in the step it is tested |
| A | `test/concurrency-sweep.mjs` | the measurement rig |
| M | `test/mesh-http.test.mjs` | 36 tests |
| A | `test/run-level.mjs` | the measurement rig |
| A | `test/ssh-file.ps1` | the measurement rig |
| A | `test/sweep-sampler.ps1` | the measurement rig |

`git status` under the package was exactly those 12 paths — 7 modified, 5 untracked — and nothing else was
staged (verified with `git diff --cached --name-only`). **`package.json` is not part of the change**: it is
clean, it still reads `"version": "0.1.0"`, and the 0.2.0 lives in `lib/index.js:60`
(`export const VERSION = '0.2.0'`). No manifest bump was invented. The manifest/`VERSION` mismatch is
recorded here as an observation and left to the package's owner; `lib/index.js` is the revision the fleet
quotes, and the desktop's copy of `package.json` (`95cdcf12`, 0.1.0) is byte-identical to the committed one.

**Published:** `git push origin master` → `3154304..7ea1e85  master -> master`, exit 0, a fast-forward.
Re-verified after: `HEAD == origin/master == 7ea1e85`, `rev-list --left-right --count` = `0 0`.

---

## 2. The sync on `zabz-tech` — state first, then the wall, then the work

### 2.1 State established before anything moved (read-only, 14:32–14:43Z)

```
$ git fetch --prune                          fetch_exit=0
  HEAD          879575309762248fa7c5cc8ad25da640c500af5a
  origin/master a446cbbbb65e9f53bea9eaefa7b788c6a250796d
  $ git rev-list --left-right --count HEAD...origin/master   → 0   30
  $ git log --oneline origin/master..HEAD                    → (empty)
  $ git stash list                                           → (empty)
```

**Nothing local to preserve in git** — no local commits, no stashes. That is *not* the same as "nothing to
preserve", and §2.2 is why. `99` §3.1 recorded `0 26`; it is now `0 30` because `4a8de19`, `3154304`,
`7ea1e85` (this session) and `a446cbb` landed after it was written.

**The readiness gate, taken immediately before the merge — the reading matters, so it is quoted:**

```
engine_pids=24556 (started 2026-09-17T09:32:02.4755680-04:00)
established_on_3099=0   headless_children=0   node_procs=2
gate=PASS
```

### 2.2 The wall is not the one `99` §3.2 named — it is the same class, one level down

`99` §3.2 said the seven files were at risk because `origin/master` held older blobs. **That was true and
this commit removes it.** What it did not say is that a fast-forward would have been refused *anyway*, for a
reason that has nothing to do with which revision is newer:

> **git refuses `merge --ff-only` when untracked files sit at paths the incoming commit will track — even
> when the content is byte-identical.**

Reproduced in a scratch repository on ZABZ-YOGA at 14:0xZ, both cases, so the identical-content case is not
an assumption:

```
IDENTICAL content:  error: The following untracked working tree files would be overwritten by merge:
                        sub/f.txt          Please move or remove them before you merge.  Aborting   exit 1
DIFFERING content:  same error, same exit 1
read-only detector: git read-tree -n -u -m HEAD <tip>   → exit 128, names the path, changes nothing
```

`zabz-tech`'s entire `packages/plugin-mesh-http/` directory was untracked (the package does not exist at its
old `HEAD`), so **28 paths** collided:

```
untracked=30  incoming_paths=2338  collide=28
  26 IDENTICAL to the incoming blob
   2 DIFFERS
      packages/plugin-mesh-http/test/concurrency-sweep.mjs   disk=c2ac1ddb  incoming=b6005246
      scripts/mesh-capacity-probe.ps1                        disk=0e9eb0a0  incoming=48fd76a8
  KEEP (the incoming commit does not track these, so they must survive):
      packages/plugin-mesh-http/probe-via-pivot.ps1
      packages/plugin-mesh-http/test/run-level.ps1
```

Also measured, because `99` §3.3 claimed it: `scripts/phone-gate.py` was ` M` in that checkout with
**worktree content == `origin/master`'s** (`9970cca2`, 121,763 bytes) while its index still held `HEAD`'s
72,210-byte revision. git's `verify_uptodate` compares the worktree to the **index**, so that file was a
second blocker in waiting; it was staged (`git add`, content already equal to the incoming blob —
`pgi == pgd` checked first) rather than checked out, because a checkout there would have destroyed the
canonical gate. `99` §3.3's conclusion that "no gate work is at risk" is right about *content* and was
silent about *git's refusal*.

### 2.3 The sync, and the guard that made it reversible

One script, run at **14:43:28Z**, in this order: fetch → readiness gate (**PASS**) → enumerate the 28
collisions → **copy every one of them, byte for byte, to
`C:\Users\ezabz\.dsh\mesh\103-sync-20260917T144328Z\` (28 files + `manifest.tsv`) and re-hash each copy**
(`backup_verify_errors=0`, `backed_up_files=29`) → stage `scripts/phone-gate.py` → remove the 28 collision
files (the two KEEP files were never touched) → `git merge --ff-only a446cbb`. If the merge had not reached
the tip, the script restored all 28 files from the backup and exited non-zero. It did not need to.

```
merge_out = Updating 8795753..a446cbb
            Fast-forward            merge_exit=0
head_after = a446cbbbb65e9f53bea9eaefa7b788c6a250796d
leftright_after = 0   0
342 files changed, 42921 insertions(+), 63 deletions(-)
```

**Before/after refs:** `879575309762248fa7c5cc8ad25da640c500af5a → a446cbbbb65e9f53bea9eaefa7b788c6a250796d`,
`0 30` → `0 0`. No `reset`, no `rebase`, no `--force`.

**The seven blobs on that machine, re-read after the merge — now the committed, newest revision:**

```
lib/node-identity.js 02b7e5c6 · lib/index.js c020b30d · lib/runner.js d70dbfd1 · lib/handler.js 15b79731
bin/mesh-http.mjs 016d06eb · bin/mesh-dispatch.mjs 035e41a8 · test/mesh-http.test.mjs 43278d6d
```

So the sync was a **pure upgrade**: the live route's code is byte-identical to what it was already serving
(no restart needed for it to be correct, §5) and the checkout is now *at a commit* instead of 30 behind it.
The two KEEP files are still on disk and are the only untracked entries left:
`git status --porcelain` → exactly `?? packages/plugin-mesh-http/probe-via-pivot.ps1` and
`?? packages/plugin-mesh-http/test/run-level.ps1`.

**The 2 DIFFERS files were older drafts, and that is measured rather than asserted.** Both preserved copies
were diffed against what the commit put there:

| file | preserved | committed | the difference, read |
|---|---|---|---|
| `test/concurrency-sweep.mjs` | `c2ac1ddb`, 12,534 B | `b6005246`, 13,486 B | the on-disk revision **adds** the `--secret-file` check at argument parsing (`73` §4's fourth lesson) and the prompt's `MESH-HOST:` rationale — 20 lines the preserved copy does not have |
| `scripts/mesh-capacity-probe.ps1` | `0e9eb0a0`, 22,889 B | `48fd76a8`, 23,035 B | the on-disk revision **replaces** `$state.Self.HostName` with `$selfFqdn.Split('.')[0]` and says why ("Named by the DNS label, not `Self.HostName` … these are the names that resolve") — i.e. the identity fix |

Both are `<=` — lines only the older copy had — against `=>` lines the committed copy has. **No local work
was superseded by anything older, and nothing was deleted:** the preserved bytes are on disk at the backup
path above, with both hashes in `manifest.tsv`.

### 2.4 `--dump-config` on both sides — and the trap that would have faked a failure

**The ssh-spawned compose fails, and it is not the machine.** Run from this session:

```
$ ssh zabz-tech-ts … node <dsh>/lib/bin.js --profile web --dump-config
  dump_exit=1  dump_lines=16
  Error: dsh: cannot resolve profile bundle "dsh-plugin-remote-fanout" from the dsh installation or
         C:\Users\ezabz\.dsh\profiles\web; run 'dsh plugin --profile web install' …
```

and the same read shows **the junction is present and correct** —
`node_modules\dsh-plugin-remote-fanout` → `C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout`,
12 files, target exists — while `<junction>\package.json` traverses for eight other plugin junctions and
**not for this one**. That is exactly the asymmetry `99` §2.2 measured (`OK cost/attention/mesh-http`,
`ERR session-link`) and concluded from: *"the trust attribute is on the junction"*, and a junction created
by a session is the untested bet. **A network-logon token cannot traverse it; the engine's Interactive
logon can.** So an ssh-run compose on that machine reports a fault that does not exist.

**The compose was therefore run by a LOCAL process on that machine**, twice before and once after, using
the one-shot task `99` §2.2 left behind (`DSH Mesh 99 Verify (once)` → a local `pwsh -File` running
`~/.dsh/mesh/99/verify-provider-local.ps1`; **the task only reads, composes and appends to its own log**):

| when (local / UTC) | process | `dump-config` | traversal | lines |
|---|---|---|---|---|
| 10:43:03 / **14:43:03Z** (before the merge) | local task, pid in its own log | **exit 0** | `TRAVERSAL OK dsh-plugin-remote-fanout bytes=1152`, child exit 0 | 617 |
| 10:43:47 / **14:43:47Z** (after the merge) | local task | **exit 0** | idem | 617 |
| 10:45:16 / **14:45:16Z** (after the row change, §3) | my own task, pid 12612 | **exit 0** | — | 617 |

Both sides of the change exit **0**, with `remote-fanout=3 tool-subagent-remote=1` unchanged. **`99` §6's
first refusal — "that ZABZ-TECH's next engine start mounts the provider" — is now measured rather than
refused, at the strongest stand-in available without restarting that engine:** a fresh local process
composes the whole profile exactly as the next start will.

---

## 3. The row's target configuration — the decision, the set, and the wall

### 3.1 What the row was, and why the brief's mechanism was slightly off

`MESH_TARGET_HOSTS` is unset on `zabz-tech` (re-measured 14:37Z in the process, machine and user
environment; also `MESH_TARGET_NODE` and `MESH_PLACEMENT`), so the committed row's `targetHosts` defaulted
to `['zabz-tech']`. **But `targetHosts` is the location-check allow-list, not the destination.** The
destination is `target: process.env.MESH_TARGET_NODE ?? 'desktop-ts'`, and on that machine:

```
$ Select-String ~/.ssh/config -Pattern 'desktop-ts' -Context 0,2
Host desktop-ts zabz-tech-ts
    HostName zabz-tech.tail93e6e6.ts.net
```

`desktop-ts` **is `zabz-tech`** — its own tailnet name. So the desktop would ssh to itself, and
`targetHosts: ['zabz-tech']` would *bless* that self-dispatch as "matched configured target host". The
brief's conclusion is right; the key it blames is the allow-list rather than the destination. Both are
hardcoded node names in a row whose whole premise is that **no row chooses a node.**

### 3.2 The decision

> **No key in the provider row may choose or validate a node.** The destination is chosen by `placement`,
> which resolves to `broker` whenever `MESH_TARGET_NODE` is unset — a broker that cannot be reached is a
> reported `broker-unreachable` failure, never a default. `targetHosts`'s default becomes **`[]`**, so that
> even the hand-set `fixed` fallback names no node and its location check is *recorded and not made* (the
> documented empty-list behaviour, and the same default `profiles/mesh/cordis.patch.yml` already uses).
> `MESH_TARGET_HOSTS` and `MESH_TARGET_NODE` are set **nowhere**. `target`'s literal stays, because in
> `broker` mode it is unreachable and in `fixed` mode the environment supplies it — and because the
> installer's completeness invariant requires the key to be present.

**Set, in two places, both backed up, both compose-verified:**

| where | before | after | backup |
|---|---|---|---|
| `zabz-tech`: `~/.dsh/profiles/web/cordis.patch.yml` (the **composed** layer) | 11,966 B, sha256 `3061C6B4…` | **12,489 B, sha256 `0C754B77…`** | `cordis.patch.yml.bak-103-20260917T144441Z` |
| the shared row `profiles/web/cordis.patch.yml` (ZABZ-YOGA worktree) | line 170 `: ['zabz-tech']`, sha256 `05BE1DE9…` | **line 176 `: []`, sha256 `956A1397…`** | the file is under git; no other copy touched |

The desktop edit was a byte-preserving splice (`ISO-8859-1` round-trip, single-occurrence pattern asserted
before writing, `pattern_occurrences=1`) plus a seven-line ASCII comment naming this document, so that a
future session does not "restore" a node name; the shared-row edit used a normal text edit after proving the
file is valid UTF-8 (`13436 == 13436` bytes on round-trip, 0 replacement characters).

### 3.3 The composed evidence

Read out of a **local** compose on `zabz-tech`, 14:45:16Z, exit 0, 617 lines
(`~/.dsh/mesh/103/compose-dump.txt`, written by `~/.dsh/mesh/103/dump-compose.ps1`):

```
- id: remote-fanout
  name: dsh-plugin-remote-fanout
  config:
    providerName: remote-ssh
    target: !!js process.env.MESH_TARGET_NODE ?? 'desktop-ts'
    …
    remoteCwd: !!js >-  process.env.MESH_REMOTE_CWD ?? (process.platform === 'win32' ? 'C:/Users/ezabz' : '/home/zabz')
    targetHosts: !!js >-
      process.env.MESH_TARGET_HOSTS ?
      process.env.MESH_TARGET_HOSTS.split(',').map((s) => s.trim()).filter((s)
      => s.length > 0) : []
    verifyMeshHost: true
```

and, in the same file, **`placement` has 0 hits.** No node is named by the row.

### 3.4 The wall, and it is precise

**Broker-driven placement exists in no commit.** Measured, in this order:

```
$ git ls-tree -r --name-only origin/master -- packages/plugin-remote-fanout
  README.md bin/install-mesh-profile.mjs bin/mesh-run.mjs cordis.patch.yml lib/index.js lib/provider.js
  lib/remote-script.js lib/ssh-transport.js package.json test/provider.test.mjs test/remote-script.test.mjs
  test/ssh-transport.test.mjs                                     ← 12 files; no nodes.js, placement.js, broker-client.js
$ git log --name-status 7ea1e85..origin/master   → docs and journal only
$ git status --porcelain -- packages/plugin-remote-fanout        → 8 modified, 7 untracked (the broker wiring)
$ git show origin/master:packages/plugin-remote-fanout/lib/index.js | Select-String 'placement|broker'
  16: * a node (there is one `target` per plugin row — placement is a separate decision service, …)
```

The committed `lib/index.js` constructs the transport from `config.target` and the provider from
`targetHosts` and the remote paths — **it reads no `placement` key.** `lib/placement.js`,
`lib/nodes.js`, `lib/broker-client.js` and the row's `placement`/`brokerSsh`/`brokerUrl`/`queueWaitMs` keys
are the working tree's, and that stream was **demonstrably live** while this ran (its `provider.js` was
written 79 seconds before one of my reads; `profiles/web/cordis.patch.yml` was rewritten from 85 insertions
to 39 insertions/8 deletions between two of my reads).

**Therefore, on `zabz-tech` today:** the composed row has no `placement` key, so `placement` cannot resolve
to `broker`; `MESH_TARGET_NODE` is unset, so `target` resolves to `'desktop-ts'`; and `desktop-ts` is that
machine's own name. **A `subagent_remote` call from a session on that machine dispatches to the machine
itself.** Setting `placement: broker` in that row would have been **inert** — a configuration that looks
like a capability and is not — so it was deliberately not set. That is the precise wall: *the broker is
live, the decision is right, and the code that would read it is uncommitted.*

**The broker itself is live and can name any node** — measured, so this is a code gap and not a service gap:

```
$ ssh secratary-ts "curl -s -m 6 http://localhost:3091/nodes"
  http=200 · schema 1 · leaseTtlSec 900 · reads 44 · readFailures 2
  zabz-tech  { fqdn zabz-tech.tail93e6e6.ts.net, state ok, cpu.logical 32, mem.freeMiB 53369,
               agents.loopsRunning 0, latencyMs 49, at 2026-09-17T14:38:29Z }
```

### 3.5 One more machine's row, stated because it differs

The **laptop's** composed layer (`~/.dsh/profiles/web/cordis.patch.yml`, 10,928 B, sha256 `850734E8…`,
mtime 09:47:17 local) is a **stale copy that predates both the sibling's row and this change**, so a fresh
compose on ZABZ-YOGA still resolves `targetHosts: ['zabz-tech']` (`dump_exit=0 lines=628`, read at
14:46Z). The file that *owns* the row now says `[]`; the laptop's deployment copy has not been refreshed,
and it was deliberately not refreshed by this session: propagating the sibling's `placement` keys into a
machine whose code cannot read them buys nothing and manufactures exactly the inert-config illusion §3.4
refuses. **The durable fix is that the row's owner commits the file.**

---

## 4. Would a restart of ZABZ-TECH's engine be safe? (reported, not done)

**Not done, and not needed.** Measured 14:32–14:45Z:

| reading | value |
|---|---|
| engine | pid 24556, `…bin.js web --port 3099 --no-open`, started 2026-09-17T09:32:02 local |
| established connections on 3099 | **0** |
| `--profile headless` children | **0** |
| node processes | **2** (the engine and `alpine-listener.js`) |

**What a restart would change.** Nothing in the route: the seven files are byte-identical to what the
running engine mounted, so the route's code is already the committed revision. It *would* re-read the
profile — same bundle list (10 names), same patch layer except the `targetHosts` default this session set,
and the whole 342-file tree is now at a commit rather than 30 behind.

**Whether it is safe: yes, and measurably safer than before the sync** — a fresh local process composed the
whole profile to exit 0 three times (14:43:03, 14:43:47, 14:45:16Z), which is the same path the next start
takes. It was still not done, because it is not needed and because that machine is in use by sibling
streams whose in-flight state a restart would load. **The laptop's engine (pid 4880) was never a candidate
and was not touched.** One caveat that is a property of the fleet rather than of this change: because a
network-logon token cannot traverse the fanout junction, **a remote (=ssh) verification of that machine's
boot will always report a false failure**; only a local process proves it (§2.4).

---

## 5. What I could not verify, stated as refusals

| not verified | why | what would verify it |
|---|---|---|
| **that a `subagent_remote` call from a session on `zabz-tech` lands anywhere useful** | §3.4: the composed row has no `placement`, and the code that would read it is uncommitted. It would dispatch to `desktop-ts` = itself. Dispatching a real child costs a turn and is not mine to spend | the acceptance command `91` §10 uses, run from a session on that machine — **after** the placement wiring is committed |
| **that a `placement: broker` row actually works end to end** | the wiring is uncommitted and no engine anywhere runs it; setting it on a machine that cannot read it would be inert | committing `packages/plugin-remote-fanout/**` + the row, then one real dispatch |
| **who rewrote `zabz-tech`'s home row at 14:13:29Z, and who re-arms `DSH Mesh 99 Provider Install (once)`** | that task's own script logged `unregistered` at 14:12:01, 14:15:00, 14:43:04 and 14:44:42, and the task was present and `Ready` at 14:42 — so an external re-registrar exists and is unmeasured. Its side-effect at 14:13:29Z was the home row going from 10,928 B / `850734E8` to 11,966 B / `3061C6B4` (byte-level re-encoding of non-ASCII comment characters; functionally inert — the compose stayed at exit 0, 617 lines) | the machine's task-registration history and the writer's own record |
| **that this session's row edit survives the row's owner** | they were mid-edit; if they regenerate the file from their own template the `[]` and its comment revert. Re-read after: it was still `[]`, sha `956A1397` | their commit of `profiles/web/cordis.patch.yml` |
| **`zabz-tech`'s boot under the engine's own token** | the strongest available stand-in is a fresh local compose, and it exits 0 three times — but "a task-started pwsh" and "the engine's own process" are not provably the same token (`99` §6) | that machine's next start |

---

## 6. What was left behind, and where

| node | artifact | why |
|---|---|---|
| `zabz-tech` | `~/.dsh/mesh/103-sync-20260917T144328Z\` — 28 preserved files + `manifest.tsv` (path, disk hash, incoming hash, verdict) | §2.3: every file the fast-forward would have written over, byte-preserved |
| `zabz-tech` | `~/.dsh/profiles/web/cordis.patch.yml.bak-103-20260917T144441Z` | §3.2 |
| `zabz-tech` | `~/.dsh/mesh/103\{dump-compose.ps1, compose-dump.txt, compose-dump.log}` | §3.3: the local compose instrument and its evidence |
| `zabz-tech` | task `DSH Mesh 103 Compose (once)` | registered for §3.3 and **unregistered** (`unregistered=ok`) |
| ZABZ-YOGA | the commit, this file, and the journal entries below | nothing outside the repository's own tree |
| both | `scripts/phone-gate.py` staged on `zabz-tech` (content unchanged; the index now holds the 121,763-byte canonical gate it already had on disk) | §2.2 |

No process was started that is still running. No engine was restarted.

---

## 7. Provenance

Every command below ran on **ZABZ-YOGA** unless it names a node, between **2026-09-17T14:20Z and 14:50Z**
(local 10:20–10:50, America/New_York, −04:00). Cross-node reads were `ssh -o BatchMode=yes
-o ConnectTimeout=15` to `zabz-tech-ts` and `secratary-ts`, driven with `powershell -NoProfile
-EncodedCommand <base64 of UTF-16LE>` because the remote default shell is Windows PowerShell and nested
quoting had already destroyed one probe attempt in this program (`99` §7).

* **The commit (§1).** Test run and `git add`/`commit`/`push` at 14:2xZ; blob hashes with `git hash-object`
  and `git rev-parse origin/master:<path>` before the commit and `git rev-parse HEAD:<path>` after it. The
  push was verified by a second `git fetch --prune` and `rev-list --left-right --count`.
* **The wall (§2.2).** The scratch-repo reproduction ran in `%TEMP%` on ZABZ-YOGA at 14:0xZ (created,
  exercised and deleted in one command); the desktop's collision set and hashes were read on `zabz-tech`
  at 14:41Z.
* **The sync (§2.3).** One ssh command at 14:43:28Z; its whole transcript is quoted above. The backup
  manifest is `manifest.tsv` inside the backup directory, written before anything was removed.
* **The compose (§2.4, §3.3).** `DSH Mesh 99 Verify (once)` started on demand at 14:43:03Z, 14:43:47Z and
  14:44:41Z and its own log read back; the composed dump at 14:45:16Z is
  `~/.dsh/mesh/103/compose-dump.txt`. **The ssh-spawned compose (§2.4) is quoted as the artifact it is,
  and is not treated as a measurement of the machine.**
* **The row (§3).** The desktop's before/after bytes and sha256 from `Get-Item`/`Get-FileHash` around a
  byte-preserving `ISO-8859-1` splice; the shared row's via `Get-FileHash` and `Select-String`; the
  environment re-read at 14:37Z; `desktop-ts` from ZABZ-YOGA's `~/.ssh/config`.
* **The broker (§3.4).** `curl` over ssh to `secratary-ts` at 14:38:30Z (the broker's own `at` field).
* **No engine was restarted, no process was killed, and no git ref was rewritten on any node.** The
  processes this session started were its own local `node --dump-config` and `git` invocations, the ssh
  sessions themselves, and one local one-shot scheduled task it registered and then unregistered.

## 8. The two follow-ups this file exists to carry

1. **Commit the placement wiring.** `packages/plugin-remote-fanout/{lib/placement.js,lib/nodes.js,lib/broker-client.js,lib/index.js,lib/provider.js,…}`
   and the row's `placement`/`brokerSsh`/`brokerUrl`/`queueWaitMs` keys exist in **no commit**. Until they
   do, no machine is broker-driven, every node still falls back to a named `target`, and §3.4's wall stands.
   `docs/mesh/93-transport-concurrency.md` was in this same position at 14:35Z and a sibling stream
   committed it at 14:36Z as part of `a446cbb` — the same must happen here.
2. **Carry `targetHosts: []` with it.** The shared row's line 176 is this session's; it is uncommitted in
   that stream's working tree, and their commit of `profiles/web/cordis.patch.yml` is what makes it durable
   and fleet-wide. If they regenerate the file from a template, this line reverts, and `zabz-tech`'s row
   goes back to naming a node it may not be.
