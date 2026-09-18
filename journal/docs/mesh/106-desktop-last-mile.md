# 106 — the desktop's last mile: a junction whose trust is an ACL owner

**Program:** `docs/mesh/` (the wall named by `105` §6, §8 items 1 and 7, and `99` §2.2 — the provider's
junction on `zabz-tech`).
**Date:** 2026-09-17, 15:30–16:00Z (11:30–12:00 local). **Author:** a delegated session, not the owner,
not the auditor.
**Owns:** the junction repair on `zabz-tech`, this file. **Nothing else in any repo was edited.** No
file under `packages/**`, no `profiles/**`, no script, no other doc. The one repo change this session
made anywhere is this file.

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the
command given, on the machine named. **READ** = read out of source. **REFUSED** = asked for and not
obtained, stated as a refusal rather than a silence.

**What was NOT done.** No engine was restarted on any node. `zabz-tech`'s live engine (**pid 24556**,
started 09:32:02 local) was never stopped, signalled or reconfigured; it held the only listener on 3099
before and after every step. The owner's laptop engine (pid 4880) was never touched *or queried* — the
brief put it out of bounds entirely. No process that this session did not start was killed. No history
was rewritten anywhere: no `reset`, no `rebase`, no `--force`, no `clean`, no push of any ref. The
`zabz-tech` checkout was **not** synced by this session (see §4 — it was already at `origin/master`
when the step was reached, and §4 says by what and when). Nothing under `packages/mesh-broker/**` or
`packages/plugin-mesh-http/**` was edited, staged or committed.

---

## 1. Headline

Three things are now measured that were not, and one of them **corrects the premise this stream
inherited**.

1. **The provider junction on `zabz-tech` has been repaired and the repair is proved from both reader
   classes.** Before: `dsh-plugin-remote-fanout`, `dsh-plugin-session-link` and `dsh-mesh-broker` were
   refused with *"The path cannot be traversed because it contains an untrusted mount point"*. After:
   all three read through the link, and `--dump-config` from the previously-failing reader went
   **exit 1 / 16 lines → exit 0 / 620 lines** (§2).
2. **The discriminator is the reparse point's ACL owner, not the reader's logon class** — and that
   inverts `99` §2.2 and `105` §8 item 7. A junction owned by `BUILTIN\Administrators` is traversable by
   a remote-logon (sshd) process; one owned by `zabz-tech\ezabz` is not. A **local** Interactive process
   traverses **both**. Measured 9/9 on the nine junctions in one directory, and reproduced by creating
   two probe junctions, one from each context (§3).
3. **Broker-driven placement is proven on `zabz-tech`** — the broker chose the node, the ledger records
   `source: "broker"`, and the lease was released — **but the child still exits 255**, because that
   machine **cannot ssh to itself**. The wall is no longer "the code does not load"; it is
   `Permission denied (publickey)` on `desktop-ts` (§6).

And the check that misses all of it, stated in full in §8: **`--dump-config` is a check that can only be
run as one reader, and its verdict depends on which reader runs it.** On the same machine, the same
bytes, at the same minute, it exits **0 with 620 lines** from an Interactive-logon process and **1 with
16 lines** from an ssh-spawned one. Nothing in its output says which reader it was.

---

## 2. Step 1 — the junction repair, and the through-the-link proof

### 2.1 Before

MEASURED on `zabz-tech`, 11:31–11:39 local, over ssh and from a local one-shot task:

```
$ cmd /c "type <DSH_HOME>\profiles\web\node_modules\dsh-plugin-remote-fanout\lib\index.js"
The path cannot be traversed because it contains an untrusted mount point.        (exit 1)
```

and the same three junctions, with their owner, from the **ssh reader**, against the seven that work:

| junction | owner | ssh `cmd /c type` through it |
|---|---|---|
| `dsh-plugin-attention`, `-attention-badge`, `-cost`, `-health`, `-mesh-http`, `-mobile`, `-windows` | **`BUILTIN\Administrators`** | **exit 0** (690 / 424 / … lines) |
| `dsh-plugin-remote-fanout` | `zabz-tech\ezabz` | **exit 1** — untrusted mount point |
| `dsh-plugin-session-link` | `zabz-tech\ezabz` | **exit 1** — untrusted mount point |
| `dsh-mesh-broker` | `zabz-tech\ezabz` | **exit 1** — untrusted mount point |

Nine junctions, one directory, **9/9 agreement between the owner and the verdict.** The reparse data is
*not* the difference: `fsutil reparsepoint query` on the failing link and on a working probe junction in
the same run prints byte-identical structures — same tag `0xa0000003`, same `Substitute Name:
\??\C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout`, same `Reparse Data Length 0x94`,
same 0x94 bytes of hex.

### 2.2 The repair

Two things follow from §3 that decide the method, and they are the opposite of what the brief expected:

* the junction had to be recreated **from an ssh session** (which yields owner
  `BUILTIN\Administrators`), *not* from a local Interactive task (which yields owner `zabz-tech\ezabz`
  and leaves a remote reader exactly as broken as before);
* and the repair had to cover **`dsh-plugin-session-link` as well**, because it is named in that
  profile's `dsh.profile.bundles` too — fixing only the provider link would have left the same wall
  standing one bundle later.

`mesh-run.mjs:229` already states this, in this repo, and it is worth quoting because this session's
measurement agrees with it and `99` §2.2 did not: *"this node's sshd session cannot traverse a reparse
point … fix it by recreating the links INSIDE an ssh session (see `70-remote-fanout-proof.md` §4.4)"*.

MEASURED (`C:\Users\ezabz\.dsh\mesh\106\repair.ps1`, run from inside an ssh session, 11:39:51 local;
repairer `identity=zabz-tech\ezabz authType=NTLM session=0`):

```
--- REPAIR: remove reparse point only, recreate from inside this ssh session ---
  dsh-plugin-remote-fanout recreated -> C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout
  dsh-plugin-session-link  recreated -> C:\Users\ezabz\Code\harness-config\packages\plugin-session-link
  dsh-mesh-broker          recreated -> C:\Users\ezabz\Code\harness-config\packages\mesh-broker
--- AFTER ---
  dsh-plugin-remote-fanout owner=BUILTIN\Administrators ssh_type_exit=0 lines=193 first=/**
  dsh-plugin-session-link  owner=BUILTIN\Administrators ssh_type_exit=0 lines=19  first=/**
  dsh-mesh-broker          owner=BUILTIN\Administrators ssh_type_exit=0 lines=28  first={
```

The removal is of the **reparse point only** (`[IO.Directory]::Delete`), never `-Recurse`, and the
target of each link was asserted to equal the expected path before the delete. The thing that must not
change did not change — the target's own content, hashed before and after **through the filesystem, not
through the link**:

```
  dsh-plugin-remote-fanout  lib/index.js sha256=BEA30611AACB220F0474F4EDE1D79524DCF94B3AE2E5A520862EEC5DFE9D82B1 bytes=9408 unchanged=True
  dsh-plugin-session-link   lib/index.js sha256=461DBA16A3756EE5134D11432E22C6DA1A87077E5C72E11B10D9E73AA8227877 bytes=846  unchanged=True
  dsh-mesh-broker           package.json sha256=90BB2091050BAFFDF41C16E5233F52524DB083775DC00BF3F2163816A5424DA2 unchanged=True
```

### 2.3 The proof — a read *through* the link, from both readers

**The ssh reader** (the one that failed before), same run:

```
--- the loader's own resolution, ssh reader, for the web profile ---
  dsh-plugin-remote-fanout -> C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-plugin-remote-fanout | version=0.2.0 | patchExists=true
  dsh-plugin-session-link  -> C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-plugin-session-link  | version=0.1.0 | patchExists=true
  node resolve exit=0
--- dump-config, ssh reader ---
dump_config exit=0 lines=620
```

That resolution is not `Test-Path`: it is the loader's own algorithm replicated exactly
(`resolveBundleDir` → `packageDirFromAnchor` → `createRequire(anchor).resolve.paths(name)`, then
`existsSync(join(candidate,'package.json'))`), anchored at `@deepseek-ai/dsh/package.json` first and the
profile's own `package.json` second — `dsh-app-boot/lib/index.js:905-921` READ. It then **reads**
`package.json` and the declared patch path through the resolved directory, which is the operation that
returns *untrusted mount point* when the link is refused.

**The local Interactive reader**, after the repair (task `DSH Mesh 106 After (once)`,
`logonType=Interactive runLevel=Limited`, session 1, 11:58:35 local):

```
cmd type THROUGH LINK exit=0 lines=193 first=/**
  dsh-plugin-remote-fanout -> C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-plugin-remote-fanout | version=0.2.0 | patchExists=true
node resolve exit=0
dump_config exit=0 lines=637
```

So both reader classes traverse the repaired link and both resolve the **0.2.0** package with the
placement code in it (`dsh-plugin-remote-fanout`, `dsh-api` version `0.2.0`, `lib/placement.js` present
in the worktree and in `HEAD:packages/plugin-remote-fanout/lib/placement.js`).

### 2.4 The repair is scriptable, and it needs no console

The repairing process was an ordinary ssh command on that machine. That is the whole point: the fix for
a junction that a *remote* process cannot traverse is a **remote** process recreating it. No scheduled
task, no one at the keyboard, no Interactive logon token — indeed an Interactive token produces the
*broken* kind (§3). The five one-shot tasks this session registered are **all unregistered**; nothing was
left behind (§7). The two probe junctions it created in its own scratch path
(`C:\Users\ezabz\.dsh\mesh\106\probe-ssh`, `probe-local`) were removed.

---

## 3. The mechanism, measured — and the two documents it corrects

The brief carried a measured claim forward: *"a junction created by an Interactive-logon scheduled task
IS trusted and traversable … while the real link failed in the same process."* **This session could not
reproduce the second half, and the first half is true of every junction on that machine.**

MEASURED, `matrix.ps1` as a local Interactive one-shot task, 11:37:41 local — the reader is
`identity=ZABZ-TECH\ezabz authType=CloudAP session=1`:

| junction | created by | read by **local task** | read by **ssh** |
|---|---|---|---|
| `probe-ssh` (made by an ssh process, 11:34:47) | ssh | OK, 193 lines | **OK, 193 lines** |
| `probe-local` (made by the task itself, 11:37:41) | local task | OK, 193 lines | **exit 1 — untrusted mount point** |
| `dsh-plugin-remote-fanout` (real, 10:10:31) | local task (per `99` §2.2) | **OK, 193 lines** | exit 1 — untrusted mount point |
| `dsh-plugin-session-link`, `dsh-mesh-broker` | earlier local | OK | exit 1 — untrusted mount point |
| `cost`, `mesh-http`, `attention`, `-badge`, `health`, `mobile`, `windows` | earlier, admin-owned | OK | OK |

**A local Interactive process traverses all six real junctions — including the two that are refused to
every remote process.** And an ssh-created junction is traversable *by ssh*; a locally-created one is
not. So neither "ssh-created = untrusted" (`99` §2.2) nor "task-created = trusted" (`105` §8 item 7)
survives the matrix as stated. What survives, 9/9 plus the two probes, is the **owner**.

`fsutil behavior query SymlinkEvaluation` on that machine reads
`Local-to-local ENABLED / Local-to-remote ENABLED / Remote-to-local DISABLED / Remote-to-remote DISABLED`
— the policy that makes the remote direction the guarded one.

### 3.1 `105` §6.1's headline number was a revision, not a fallback

`105` §6.1 reports the desktop loading *"v0.1.0, 4382 chars, no `placement.js`"* and concludes the
engine *"fell back to a `dsh-plugin-remote-fanout` that is readable somewhere in its search path"*.
MEASURED four ways, that conclusion does not hold:

* the desktop's `HEAD` at that time was **`895114b`** (its own reflog: `895114b HEAD@{11:24:46}`), and
  `packages/plugin-remote-fanout` at `895114b` is `"version": "0.1.0"` with `lib/index.js` **4296
  characters** — `4382` bytes on disk is that same file with CRLF, which is what `Get-Item.Length`
  reports and what `105` quotes;
* the loader's resolution on that machine returns the **junction path itself**
  (`…\profiles\web\node_modules\dsh-plugin-remote-fanout`), never a fallback directory;
* a local reader reads 193 lines *through* that junction today at `version=0.2.0` (§2.3);
* and a reader that genuinely cannot traverse it fails **both** the read and the composition — measured:
  ssh reader, exit 1, 16 lines, `cannot resolve profile bundle "dsh-plugin-remote-fanout"`.

So the 4382/0.1.0 reading was the linked file at a revision two commits before `263785d`, read
**successfully** through a traversable link. It was not a silent fallback, and it was not the reason the
child died.

### 3.2 The one thing in `105` this session cannot explain

`105` §8 item 7 shows a *local* task in which the real link returned *untrusted mount point* while a
probe junction created moments earlier in the same process traversed. This session measured the
opposite, twice, in the same reader class and the same directory (§2.3, §3). Both cannot be true of one
unchanging reparse point; the junction's creation time (`10:10:31`) is unchanged across both sessions,
and nothing here can distinguish the two. **Recorded as an open discrepancy rather than resolved.** The
practical consequence is nil — the reader that matters for a dispatched child is the remote one, and
§2.3 fixes it from both sides — but a future session should not re-derive trust from "which process
created it".

---

## 4. Step 2 — the sync: already at `origin/master`, and verified rather than performed

**This session did not run the sync.** The checkout reached `origin/master` **two minutes into the
session, by another process**, while the first read-only measurements were being taken. What was done
instead is the state-before/state-after and the preservation check the brief asked for, and the honest
finding is that the step was already complete when it was reached.

### 4.1 State before — MY OWN measurement, 11:31:36 local (15:31:36Z), read-only

```
$ git rev-parse HEAD           3d3dec1d4965ead42aa97de251f388467613cc6a
$ git rev-parse origin/master  e0d07cac600d81545257755bdc83a63a6de4ab3c
$ git rev-list --left-right --count HEAD...origin/master     0	2
$ git log --oneline origin/master..HEAD                      (empty)
$ git stash list                                             (empty)
$ git status --porcelain
 M journal/index/entries.tsv
?? journal/entries/handoff/H466.md
?? journal/entries/lessons/L1908.md
?? journal/entries/lessons/L1909.md
?? packages/plugin-mesh-http/probe-via-pivot.ps1
?? packages/plugin-mesh-http/test/run-level.ps1
```

Nothing local to preserve: **no local commits, no stashes**, and `0 2` — a fast-forward was theoretically
available.

### 4.2 What moved it, and when

That machine's own reflog, and its own sync keeper's status file:

```
a85232c HEAD@{2026-09-17 11:32:07 -0400}: merge origin/master: Merge made by the 'ort' strategy.
838b342 HEAD@{2026-09-17 11:32:03 -0400}: commit: journal(ZABZ-YOGA): a deposit smaller than the lab's own non-refundable charge …

$ cat ~/.dsh-sync-status/status.json
{ "updated": "2026-09-17T15:32:03.1797319Z", "result": "attention",
  "detail": "pull --ff-only refused: histories diverged (2 behind / 0 ahead) and step 2b preserved nothing. Needs a human.",
  "behind": 2, "ahead": 0, "branch": "master", "local_commits_preserved": false, "host": "ZABZ-TECH" }
```

So the machine's **keeper refused** (`PersonalSecretary-HarnessSync`, `LastTaskResult=1`), and a stream
working in that checkout committed the untracked journal entries it had and then merged `origin/master`
— which is the correct shape, because the commits are what make the untracked-collision trap irrelevant.
`a85232c` is the merge of that commit with `e0d07cac`.

### 4.3 State after, 11:40:14 local (verified again at 11:59:23)

```
$ git rev-parse HEAD            a85232c435328d9afebe340c1a83281695d2b3f9
$ git rev-parse origin/master   a85232c435328d9afebe340c1a83281695d2b3f9
$ git rev-list --left-right --count HEAD...origin/master     0	0
$ git log --oneline origin/master..HEAD                      (empty)
$ git stash list                                             (empty)
```

**Preserved, and verified by re-hash — nothing was lost:**

| path | state | evidence |
|---|---|---|
| `journal/entries/handoff/H466.md`, `lessons/L1908.md`, `lessons/L1909.md` | untracked before → **in `HEAD` now** | `git cat-file -e HEAD:<path>` → true, all three |
| `packages/plugin-mesh-http/probe-via-pivot.ps1` | still present, still **not** on origin | sha256 `3F8E769A34921C05…` |
| `packages/plugin-mesh-http/test/run-level.ps1` | still present, still **not** on origin | sha256 `EF5B1FB7DA4F99CE…` |
| the provider package's own content | worktree blob == committed blob | `git rev-parse HEAD:…/lib/index.js` = `git hash-object …/lib/index.js` = `ef49fb5f2e6ee9b590354338e3084f552575f666` |

### 4.4 The untracked-collision trap, run as the read-only detector

The brief's trap — `merge --ff-only` refused when untracked files sit at paths the incoming commit will
track even when the content is byte-identical — was run as its detector, and reported clean:

```
$ git read-tree -n -u -m 3d3dec1 e0d07cac        exit 0   (no output)
$ git read-tree -n -u -m HEAD origin/master      exit 0   (no output)
```

`99` §3.2's wall — 24 untracked `packages/plugin-mesh-http/**` paths, 7 of them *newer* than
`origin/master` and in no commit — is **gone**: that stream committed its tree. The detector that would
have caught it is now clean for both the historical pair and the current pair, which is the check a
future session should re-run before any fast-forward on that machine.

---

## 5. Step 3 — the restart: REFUSED, with the gate's numbers

**No restart was performed. The gate was closed at the decision point, and it was already closed when the
step began.**

| reading | 11:31:36 local | 11:40:14 local (the decision point) | gate requires |
|---|---|---|---|
| `established_on_3099` | **10** | **8** | `0` |
| in-flight children of the engine | **4** runners (pids 28396 11:29:55, 36332 11:31:13, 9412 11:31:37, …) | **2** (pid 43876 11:39:51, pid 16704 11:40:03) | none |
| listeners on 3099 | 1, pid **24556** | 1, pid **24556** (started 09:32:02) | — |

Every established connection is owned by the engine and loops back to `127.0.0.1`; the children are
`dsh-subprocess-local/lib/runner.js` processes **parented by pid 24556**, i.e. a sibling stream
executing tool calls *through that engine* at both readings — `lpt-recon`, `lpt-hub`, customer-plane
work. Killing pid 24556 would have taken another stream's in-flight work with it. The brief's own rule
governs: *"If it is NOT idle, do not restart; report and stop after step 2."*

Two consequences, stated plainly:

* the live engine on that machine is therefore **still pre-placement** and will remain so until someone
  restarts it in an honest idle window;
* and the restart is now **expected to succeed where `105` feared it would not** — a local Interactive
  reader resolves the provider bundle at **0.2.0 with `patchExists=true`** (§2.3), which is the reader
  class the engine itself runs in.

---

## 6. Step 4 — placement proven, and the wall that then stops the child

Because the restart was refused, the placement was proved **without it**, exactly as `105` §6.1 proved
its refusal: a **second engine on the same machine, on the real home, on a different port (3097)**,
started and killed by this session, leaving the listener on 3099 untouched. It is not a restart of the
live engine and it is not presented as one; it is a fresh process, so it boots the code the repaired
junction now resolves.

MEASURED, `proof.ps1` as a local Interactive one-shot task, 11:53:40–11:54:02 local. Every `MESH_*`
override was **removed from the environment first** (`MESH_PLACEMENT=''`, `MESH_TARGET_NODE=''`), so the
package's own default is what ran:

```
engine pid=37480 port=3097 DSH_HOME=C:\Users\ezabz\.dsh
listening=True after 4s exited=False
healthz 200 pid=37480 dshHome=C:\Users\ezabz\.dsh
session/create ok=True id=session-e03ff37d-a158-4a0a-8c25-6eec90589165 preset=zabz
prompt ok=True
--- the session's reply ---
Error: subagent run failed Diagnostic: the remote one-shot exited 255 and produced no final message; stderr tail: ezabz…
```

and the ledger record it left — a **new** file, `<DSH_HOME>/mesh/placements/remote-59e5ec01-….json`,
where the directory did not exist before the run (0 records → 1):

```json
{ "id": "remote-59e5ec01-b2d5-4394-90b9-789d97cdb5f2", "at": "2026-09-17T15:53:54.036Z",
  "source": "broker", "childIndex": 0, "node": "zabz-tech", "ssh": "desktop-ts",
  "position": 0, "tier": "fits", "score": 18, "eligible": 4, "blockedBy": [],
  "lease": "mu5pm4zq-1dxip-3-4055ded5", "leaseTtlSec": 900, "expiresAt": "2026-09-17T16:08:54.374Z",
  "rationale": ["chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits; chosen zabz-tech",
                "zabz-tech: 18 slot(s) of at most 24: floor((36927 MiB free - 7821 MiB reserve) / 160 MiB) = 181 slot(s), capped at maxSlots=24 -> 24, …",
                "zabz-yoga-1: 12 free slot(s) of 24, 24 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 12, 11 after 1 child(ren)",
                "zabz-tech-linux: 4 free slot(s) of 24, …", "secratary: 3 free slot(s) of 24, …"],
  "queue": [], "placedAt": "2026-09-17T15:53:53.314Z", "brokerAt": "2026-09-17T15:53:54.374Z",
  "brokerCallMs": 721, "state": "settled", "facts": { "driver": "C:/Program Files/nodejs/node.exe",
    "bin": "…/@deepseek-ai/dsh/lib/bin.js", "profile": "headless", "shell": "powershell" },
  "waitedMs": 0, "dispatchedAt": "2026-09-17T15:53:54.037Z", "stopReason": "error",
  "settledAt": "2026-09-17T15:53:54.392Z", "leaseReleased": true, "leaseReleaseSkipped": null,
  "leaseReleaseError": null, "reportedHost": null, "meshHost": null,
  "invocationForm": "interpreter", "invocationAttempts": ["interpreter"], "exitCode": 255, "ms": 108 }
```

**What that settles, and what it does not.**

* **The broker really chose the node.** `"source": "broker"`, `node: "zabz-tech"`, `position: 0`,
  `tier: "fits"`, four eligible candidates with the winner's arithmetic printed, `blockedBy: []`. The
  row's `targetHosts` is `[]` and nothing named a target in the environment — a self-dispatch would have
  been the bug this whole stream exists to catch, and the ledger says the broker is what dispatched.
* **The lease was released** on the settled path: `"leaseReleased": true`, with the TTL and the
  reclaim-by-expiry line recorded.
* **The placement is durable, not transcript-only**: one file under
  `<DSH_HOME>/mesh/placements/`, written by the engine, on the real home.
* **The child did not run.** `exitCode: 255`, `ms: 108`, `reportedHost: null`, `meshHost: null` — there
  is no `MESH-HOST:` line, so the second half of the brief's step 4 is **REFUSED, and the reason is
  measured, in §6.1**.

### 6.1 The wall that stops the child: `zabz-tech` cannot ssh to itself

MEASURED from a local Interactive one-shot task on that machine (`final.ps1`, session 1, 11:57:15 local):

```
$ ssh -n -v -o BatchMode=yes -o ConnectTimeout=8 desktop-ts hostname
debug1: Offering public key: C:\Users\ezabz/.ssh/zabz-tech-ed25519 ED25519 SHA256:tuQvTkv6fNSyfSjzylJpBkDkJo87YIeN9PEElUhotdE explicit
debug1: Authentications that can continue: publickey,password,keyboard-interactive
debug1: No more authentication methods to try.
ezabz@zabz-tech.tail93e6e6.ts.net: Permission denied (publickey,password,keyboard-interactive).
                                                                                  exit=255  ms=112
```

108 ms in the ledger, 112 ms here — the same immediate failure. `~/.ssh/config` on that machine maps
`desktop-ts` to `zabz-tech.tail93e6e6.ts.net`, and that machine's own `sshd` does not accept the key it
offers. So the provider placed the child correctly, dispatched it to `desktop-ts` as the node table says
(`lib/nodes.js`: `'zabz-tech': { ssh: 'desktop-ts', … }`), and the transport died in the first tenth of a
second.

**This is a different defect from the junction, it is on the same machine, and it is the thing that now
gates the desktop being broker-driven end to end.** It is also *not* about remote logon class: it is a
plain publickey denial on loopback, in the engine's own logon class. The broker call itself succeeds from
the same process (`brokerCallMs: 721`, and the provider reaches the broker by `ssh secratary-ts`), so the
machine's outbound mesh works and only this one destination is refused.

What was **not** determined: whether `secratary-ts` and `laptop-ts` are also slow from that context. Both
exceeded 25 s in the same probe and were killed, but `-v` writes enough stderr that a redirected read can
stall a probe of my own making, and the broker call proves `secratary-ts` *does* work from the engine — so
this probe's verdict for those two is not trustworthy and is recorded as such rather than as a finding.

---

## 7. Step 5 — post-verification, and hygiene

MEASURED on `zabz-tech`, 11:57–11:59 local:

| check | result |
|---|---|
| the engine is a single process on 3099 | **1** listener, owning pid **24556**, process alive, `CreationDate 2026-09-17 09:32:02` — the same pid and start time as at the first measurement |
| the port this session used is free again | listeners on **3097 = 0** (its own engine, pid 37480, was stopped by the script that started it) |
| the mesh route still answers on 3099 | `GET /mesh/health` → **200**, 2484 bytes, `"service":"mesh-http","version":"0.2.0","identityDegraded":false` |
| `/mesh/capacity` answers 200 | **not on 3099** — `GET http://127.0.0.1:3099/mesh/capacity` → **404**. It answers 200 where the code says it lives: `GET http://127.0.0.1:3086/mesh/capacity` → **200**, 476 bytes, `{"schema":1,"node":"zabz-tech","fqdn":"zabz-tech.tail93e6e6.ts.net","at":"2026-09-17T15:59:10Z",…}` (`plugin-mesh-http/lib/index.js:109`, `capacityUrl: 'http://127.0.0.1:3086/mesh/capacity'`) |
| nothing left running or scheduled | the five one-shot tasks (`DSH Mesh 106 Before/Matrix/Proof/Final/After (once)`) are **all unregistered**; 0 remain. The two probe junctions and the scratch file were removed |
| the ledger holds exactly the one proof record | `remote-59e5ec01-b2d5-4394-90b9-789d97cdb5f2.json`, 3898 bytes |

Not one of the 106 tasks was left registered-but-disabled, because a one-shot with no trigger and a
recorded transcript is a weaker artefact than the transcript plus a clean machine; the scripts themselves
remain at `C:\Users\ezabz\.dsh\mesh\106\` with their logs.

**Two untracked files in that machine's checkout are recorded as unexplained, not as mine.**
`packages/plugin-mesh-http/readmatrix.cjs` and `pairs.json` appeared in the checkout at **11:37:41.53**,
the second this session's matrix task ran, and their bytes are **verbatim this session's probe output** —
but the script that wrote them names an absolute path in `.dsh\mesh\106`, and a direct write-path probe
from the same context landed exactly there and not in the repo (`in106=True inRepoMeshHttp=False`). No
mechanism was found that puts them in the repo. They were **moved, not deleted**, to
`C:\Users\ezabz\.dsh\mesh\106\stray-from-repo\` so the checkout is clean without destroying bytes that
might be another stream's.

---

## 8. The check that cannot fail — recorded, with its two verdicts

The brief asked for this in the report and here it is, with the refinement the measurement forces.

**On `zabz-tech`, the same `--dump-config`, on the same bytes, at the same minute, gives two different
answers depending on which process runs it:**

```
$ node <dsh>/lib/bin.js --profile web --dump-config      # ssh-spawned reader, 11:31 local, BEFORE the repair
exit=1  lines=16
  Error: dsh: cannot resolve profile bundle "dsh-plugin-remote-fanout" from the dsh installation or
  C:\Users\ezabz\.dsh\profiles\web; run 'dsh plugin --profile web install' if its dependency is not installed
      at resolveBundleDir (…/dsh-app-boot/lib/index.js:831:8)

$ node <dsh>/lib/bin.js --profile web --dump-config      # local Interactive reader, 11:34 local, BEFORE the repair
exit=0  lines=620
```

That is the class of defect this build keeps losing time to: **a check whose result is a function of the
reader's logon token, whose output never names the reader, and which has only ever been run as the reader
that passes.** `105` §7's table records the row *"the desktop's `--dump-config` still exits 0 despite
that → exit=0 lines=620 — the two disagree, which is the finding"*, and the disagreement is real; but the
reason recorded there — that the composition validates while the bundle resolution is broken and *a
different, older plugin answers* — is **not** what this session measured. From the passing reader, the
bundle resolution is **correct**: the loader resolves the junction itself at `version=0.2.0` with
`patchExists=true`, and `105`'s own 4382-byte/0.1.0 read is that same file at a revision two commits
earlier (§3.1). What `--dump-config` cannot see is not a broken resolution in *its* reader; it is that
**the reader which actually runs a dispatched child is a different one, and for that one the profile does
not compose at all.**

The general rule, and it is the transferable part: **a profile check is only evidence for the logon class
that ran it.** A dispatched child, a `mesh-run` preflight and an `sshd` session are the remote class; the
GUI engine and a scheduled task are the local class. Run `--dump-config` as each, or the check is a
rubber stamp. `mesh-run.mjs:229` is the one place in this repo that already understood this, and it
refuses on exactly this condition; `--dump-config` does not.

---

## 9. What could not be verified, stated as refusals

| not verified | why | what would verify it |
|---|---|---|
| **that `zabz-tech`'s live engine (pid 24556) serves a broker-driven placement** | the gate was closed at both readings (`established_on_3099` 10 → 8, 2–4 in-flight children of that pid, a sibling stream working through it) and the brief forbids restarting when it is not idle (§5) | a restart in an honest idle window. **It should now succeed**: a local reader resolves `dsh-plugin-remote-fanout` at 0.2.0 with the patch present (§2.3), which is the engine's own reader class |
| **a `MESH-HOST:` line for a child on that machine** | the child was placed on `zabz-tech` — correctly — and then `ssh desktop-ts` from `zabz-tech` returned **255 in 112 ms, `Permission denied (publickey)`** (§6.1). `reportedHost: null`, `meshHost: null` | put `zabz-tech`'s own public key in its own `authorized_keys` (or point that node's `ssh` alias at an identity its ssHD accepts), then re-run the same one-shot proof. The ledger record is already there; only the transport is missing |
| **why `105` §8 item 7 saw a local task refused on that junction while this session saw it traverse, twice** | the junction's creation time is unchanged across both sessions, so the reparse point is not the variable (§3.2) | a future session that can reproduce `105`'s exact task, or a Windows-level trace. Recorded as an open discrepancy, not as a resolved contradiction |
| **whether `secratary-ts` / `laptop-ts` are genuinely slow from `zabz-tech`** | my probe killed them at 25 s, but `-v` stderr redirection can stall a probe of my own making and the broker call proves `secratary-ts` works from the engine (§6.1) | re-probe without `-v` and with concurrently-drained streams |
| **the sync, by this session** | it was already done by another process at 11:32:03–11:32:07, before this session reached the step (§4) | nothing; §4 verifies the result, including preservation by re-hash and the read-only collision detector |

---

## 10. Provenance

Every command ran between **2026-09-17T15:30Z and 16:00Z** (11:30–12:00 local). The session ran on
**ZABZ-YOGA**; every measurement quoted as being on `zabz-tech` was taken there, over
`ssh -o BatchMode=yes zabz-tech-ts …` with the remote script passed as
`powershell -NoProfile -EncodedCommand <base64>` (script bytes transferred by base64 over ssh **stdin**
and verified by SHA-256 on both sides before use — `repair.ps1` `3230FD0EA756292B…`, `proof.ps1`
`DF648E6F2D491A70…`). Anything that needed an Interactive-logon context ran as a one-shot scheduled task
registered **without** `-Force`, `-Principal`, `-AtLogOn` or `RestartCount`, reporting
`logonType=Interactive runLevel=Limited` each time.

* **Reads.** `105-placement-committed.md` and `99-installer-and-desktop.md` in full, first;
  `dsh-app-boot/lib/index.js` `resolveBundleDir`/`packageDirFromAnchor`/`loadProfileDirectory`;
  `packages/plugin-remote-fanout/lib/nodes.js`; `bin/mesh-run.mjs` lines 189–229;
  `plugin-mesh-http/lib/index.js` `capacityUrl`.
* **Repair.** `repair.ps1`, run from the ssh session at 11:39:51 local, log `repair.log`, both on
  `zabz-tech`.
* **Matrix.** `matrix.ps1` as task `DSH Mesh 106 Matrix (once)` at 11:37:41 local, log `matrix.log`;
  the ssh-side counterparts in the same two minutes.
* **Step 4.** `proof.ps1` as task `DSH Mesh 106 Proof (once)` at 11:53:40 local, log `proof.log`,
  engine logs `proof-3097.log` / `proof-3097.err.log`, ledger
  `C:\Users\ezabz\.dsh\mesh\placements\remote-59e5ec01-b2d5-4394-90b9-789d97cdb5f2.json`.
  It first failed to run at all under `powershell.exe` 5.1 — the script used `??` and
  `-SkipHttpErrorCheck`, which are PowerShell 7 syntax — and the task was re-registered on
  `C:\Program Files\PowerShell\7\pwsh.exe`. Recorded because a task that exits 1 with no log is a silent
  failure of exactly the kind this program keeps finding.
* **Step 5.** `final.ps1` as task `DSH Mesh 106 Final (once)` at 11:57:15 local, log `final.log`;
  `before.ps1` re-run as `DSH Mesh 106 After (once)` at 11:58:35 local.
* **Nothing of the owner's was touched.** No engine on ZABZ-YOGA was started, stopped or signalled; the
  only processes this session started on `zabz-tech` were the two short-lived extra engines it logged
  (pids 37480 on 3097 and the aborted first attempt) and the scheduled-task processes above, all of which
  it stopped or which exited on their own.

---

## 11. Closing addendum — the last wall came down, and the fix was one key line

**Author:** a *different* delegated session, also on ZABZ-YOGA, **2026-09-17 16:05–16:35Z** (12:05–12:35 local). §1–§10
are unchanged and are not reinterpreted; this section adds what happened next. Same provenance convention: **MEASURED**
with the command and the raw output, **READ** out of source, **REFUSED** stated as a refusal.

**What was NOT done.** No engine was restarted on any node. `zabz-tech`'s live engine is **still pid 24556, started
`2026-09-17T09:32:02.4755681-04:00`**, the only listener on 3099 before and after every step — the same pid and start
time §5 recorded. The owner's laptop engine (pid 4880) was never touched or queried. `secratary` was not touched. The
one scheduled task this session registered (`DSH Mesh 106 Closing (once)`, `Interactive` / `Limited`) was **deleted**;
nothing is left registered.

### 11.1 Headline

**The wall §6.1 measured is gone, and it was the fix §9 predicted: `zabz-tech`'s own public key was missing from its own
`authorized_keys`.** The exact command that returned `255 / Permission denied (publickey)` in 112 ms now returns **exit 0
in 402 ms**, and a re-run of §6's isolated-engine proof produced the `MESH-HOST:` line §6 could not:
`MESH-HOST: zabz-tech [remote-ssh] child ran on node "ZABZ-TECH"`, with the ledger saying `source=broker` and
`exitCode=0`. **Placement, transport and the child's own location claim are now all measured on `zabz-tech` at once.**

### 11.2 The fix, precisely

| | |
|---|---|
| file | `C:\Users\ezabz\.ssh\authorized_keys` — the file `sshd -T` resolves to: `authorizedkeysfile .ssh/authorized_keys`. There is **no** `Match Group administrators` override in this `sshd_config`, so `administrators_authorized_keys` is not the effective file |
| key | `~/.ssh/zabz-tech-ed25519.pub` = `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDQTL4gB3VLEVXvvTpNWKTN0bVsStBzpVsn6PRp7YRQn zabz-tech-desktop-2026-05-17`, fingerprint **`SHA256:tuQvTkv6fNSyfSjzylJpBkDkJo87YIeN9PEElUhotdE`** — the same fingerprint §6.1 recorded as *offered and refused* |
| change | **one line appended, 111 bytes.** 2500 B / 8 lines → 2611 B / 9 lines, `sha256 506DB609BDE0542E36A2BC5F73EA164490B5D1A9581FFD15F3CE436E20E024BE`, mtime `2026-09-17T12:09:02.0218212-04:00` |
| **not** changed | `sshd_config` (`sha256 C5C96DC46E486A4A0787D37E2581662055E7D6A91639B7E3F2ED739CDC637AD9`, mtime `2026-07-05T17:46:47`), so `PasswordAuthentication yes` and `AuthorizedKeysFile` stand as they were. No other node, no ACL, no other line |
| idempotent | the script tests for the exact line before writing. Its second run reported `action=none required (already present)` and left the file byte-identical — so re-running it anywhere is a no-op |
| file hygiene, MEASURED in the Interactive class | 9 lines, 0 LF-only, 9 CRLF, no BOM, and the desktop's own key on a line of its own (`the desktop's own key present as its own line: True`). **Pre-existing and not touched:** line 1 is 1091 bytes carrying **4** key tokens, i.e. three key lines once lost their newlines (`lpt-mac-mini-to-laptop`, `zabz-tech-linux-mesh` are the concatenated ones). The 12 keys still parse and the laptop's own key still authenticates, so nothing was broken by it — recorded, not fixed, because it belongs to whoever installed those keys |

**Provenance of that line, stated plainly because it is not what the first attempt expected.** The appending process was
**this session's own first attempt**, whose nested-`ssh` probe hung and which the operator killed at the outer layer: the
remote PowerShell survived the kill as an **orphan** and finished its append at **12:09:02 local**. Measured, not
inferred — the file's `LastWriteTime` is `12:09:02.0218212-04:00`, it grew by exactly the 111 bytes of that key line, and
the two orphans (`pid 10564`, `pid 16736`, both started `12:04:46`) were still alive when this session looked for them
and were stopped. The lesson travels: **killing an ssh session does not kill what sshd spawned**, so a "killed" script
may still have written.

### 11.3 The through-the-wire proof — both reader classes, before and after

MEASURED by a one-shot task in the **Interactive** class (`identity=ZABZ-TECH\ezabz authType=CloudAP session=1`) — the
same class §6.1 measured the 255 in — log `C:\Users\ezabz\.dsh\mesh\106\closing.log`:

```
--- A. authorized_keys as THIS logon class sees it ---
  len=2611 mtime=2026-09-17T12:09:02.0218212-04:00 sha256=506DB609BDE0542E36A2BC5F73EA164490B5D1A9581FFD15F3CE436E20E024BE
  the desktop's own key present as its own line: True
--- B. the exact command a placed child runs, in THIS logon class (255 at 11:57) ---
  desktop-ts   exit=0 ms=402 out=[zabz-tech] err=[]
  desktop      exit=0 ms=390 out=[zabz-tech] err=[]
--- C. the engine this re-run must not disturb ---
  port 3097 listeners before=0          3099 listeners=1
--- E. post ---
  listeners 3097=0 3099=1
```

`desktop-ts` is the alias the node table names (`lib/nodes.js`: `'zabz-tech': { ssh: 'desktop-ts', … }`), so that row is
the dispatched child's own command, **exit 0**, `err=[]`.

### 11.4 The child's own line, and the ledger

MEASURED by `proof.ps1` — §6's script, **unmodified**, same shape: a second engine on the real home, port 3097, every
`MESH_*` override removed first (`MESH_PLACEMENT='' MESH_TARGET_NODE=''`). New ledger record
`C:\Users\ezabz\.dsh\mesh\placements\remote-85df2039-6478-4d1a-9353-5b57caaab83b.json` (the directory went 1 → 2 records):

```
--- the session's reply ---
MESH-HOST: zabz-tech [remote-ssh] child ran on node "ZABZ-TECH" via C:/Program Files/OpenSSH/ssh.exe -o BatchMode=yes -.
meshHostLines = MESH-HOST: zabz-tech

  "source": "broker", "node": "zabz-tech", "ssh": "desktop-ts", "position": 0, "tier": "fits", "score": 18,
  "eligible": 4, "blockedBy": [], "brokerCallMs": 417, "leaseReleased": true,
  "stopReason": "completed", "exitCode": 0, "ms": 5289,
  "reportedHost": "ZABZ-TECH", "meshHost": "zabz-tech", "invocationForm": "interpreter",
  "dispatchedAt": "2026-09-17T16:15:03.992Z", "settledAt": "2026-09-17T16:15:09.515Z"
```

The §6 record, for contrast, is the one immediately before it in the same directory:

```
  remote-59e5ec01-…  source=broker node=zabz-tech tier=fits brokerCallMs=721
                     stopReason=error exitCode=255 ms=108 meshHost= reportedHost= leaseReleased=True
```

So on `zabz-tech`: the broker chose the node, the lease was released, the child **ran**, and the child's own
`MESH-HOST:` line agrees with the ledger's `reportedHost`/`meshHost`. The §9 row that said *"put `zabz-tech`'s own
public key in its own `authorized_keys`, then re-run the same one-shot proof"* is **discharged**.

### 11.5 A defect this session found and did not fix: `ssh` nested inside an sshd session HANGS on this machine

This corrects §6.1's own doubt (*"what was not determined: whether `secratary-ts` and `laptop-ts` are also slow from that
context"*). MEASURED, `diag.log`, from an ssh-spawned session on `zabz-tech`, each probe bounded by a background job:

```
  control_echo: hello-from-job                 ← Start-Job works here, so the timeouts are real hangs
  ssh_secratary_ts: <<TIMEOUT 20s>>             ← a destination that WORKS from the engine (the broker call)
  dns_tailscale: 100.85.153.96                 ← name resolution is fine
  tcp22_tailscale: True     tcp22_lan: True    ← TCP 22 is reachable
  ssh_desktop_ts: <<TIMEOUT 25s>>              ← with -v, and NOT ONE LINE of debug output in 25 s
  ssh_lan_self:   <<TIMEOUT 25s>>
```

So the 25 s kills §6.1 saw were **the context**, not those hosts — as §6.1 suspected and could not prove. `ssh.exe`
launched from an ssh-spawned session on this machine produces no output at all and never connects, for **every**
destination, while the same binary from the Interactive class completes in ~400 ms. **Consequence for method, not for
the fix: a probe run over ssh on that machine is not evidence about machine-to-machine ssh, which is why §6's proof and
this one both ran as an Interactive one-shot task.** Cause not determined (recorded as a refusal, not a diagnosis);
a future session should trace it rather than re-derive it.

### 11.6 Still open, and one thing this addendum could not change

1. **`zabz-tech`'s live engine (pid 24556) is still pre-placement.** It booted at 09:32:02, before the placement
   packages existed on disk, so it does not consult the broker today (§5). It was never restarted here — the rule
   against restarting another stream's engine still holds, and the gate was never even reached this time. Once it *is*
   restarted in an honest idle window it should be broker-driven: the junction is repaired (§2), the provider resolves
   at `0.2.0` from both reader classes (§2.3), and the transport now works (§11.3).
2. **`proof.ps1`'s own "live engine untouched" line is blind, and that is worth knowing before trusting it.** Both
   readings in §6 and in this re-run printed `live 3099 engine BEFORE/AFTER pid= count=0` — while port 3099 had exactly
   one listener throughout. The assertion that the engine survived therefore rests on the **listener count**, not on
   that line. Whether the cause is a class-dependent CIM failure or the process-pattern match was not determined;
   recorded so nobody reads `count=0` as "no engine".
3. **This record is still uncommitted, and now for a measured reason that is not about the record.** See §11.7: the
   laptop's journal tree collides with `origin/master` on ten entry ids, so committing it would mean either a merge or
   a rewritten worktree. The bytes are on disk, unchanged at **34,612 B + this section**.

### 11.7 Why the commit did not happen (JOB 3, refused)

MEASURED on ZABZ-YOGA at 16:2xZ: `HEAD=e0d07cac`, `origin/master=8875e22`, `rev-list --left-right --count HEAD...origin/master`
→ **`0 6`** at the first reading and **`0 9`** minutes later (the fleet pushed three more commits *during this session*),
none ahead, and `git ls-tree origin/master -- docs/mesh/106-desktop-last-mile.md` is **empty** (the record is on disk
only). The push is refused, with the remote's own words:

```
$ git push --dry-run origin master:master
To secretary-ts:/home/zabz/harness-config.git
 ! [rejected]          master -> master (non-fast-forward)
error: failed to push some refs to 'secretary-ts:/home/zabz/harness-config.git'
hint: Updates were rejected because the tip of your current branch is behind its remote counterpart.   exit=1
```

The read-only fast-forward detector refuses too, and the reason is not this document:

```
$ git read-tree -n -u -m HEAD origin/master
error: Untracked working tree file 'journal/entries/decisions/D254.md' would be overwritten by merge.   exit=128
```

That file is a **different entry wearing an id that `origin/master` now also holds** — the collision is recorded in
full in `journal/reference/id-collision-20260917.md`, with both `journal.py check` outputs, the ten live ids, the eight
latent ones, and the exact renumber map the next session needs. Committing here would therefore diverge, which the
brief forbids; the record is left on disk for the session that can merge first. **Nothing was pushed, nothing was
merged, no history was rewritten, and `git add -A` was never run.**
