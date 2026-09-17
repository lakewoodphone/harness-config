# 99 — The POSIX installer's landmine, and what actually happened on ZABZ-TECH

**Program:** `docs/mesh/`. **Date:** 2026-09-17, 13:5x–14:2xZ (09:5x–10:2x local).
**Author:** a delegated session, not the owner, not the auditor, not the author of any `docs/mesh/8x`.
**Owns:** `scripts/install-client-plugin.sh` and this file. Nothing under `packages/**`, no other script, no
other doc was edited. `packages/mesh-broker/**`, `packages/plugin-mesh-http/**` and
`packages/plugin-remote-fanout/**` were being edited by three other streams while this ran.

**What was NOT done.** No engine was restarted anywhere — the laptop's engine (pid 4880, the owner's live
work) was never touched, and ZABZ-TECH's engine (pid 24556) was not restarted either, for a reason
measured in §4. No process was killed. No history was rewritten: no `reset`, no `rebase`, no `--force`,
no push of any ref. ZABZ-TECH's checkout was **not** synced, and §3 says why in measurement rather than
in preference.

| # | item | verdict |
|---|---|---|
| 1 | `scripts/install-client-plugin.sh` arms the bundle landmine | **FIXED** and the failure mode reproduced (§1) |
| 2 | ZABZ-TECH "lost" its provider work when its engine restarted | **THE PREMISE IS FALSE** — it never had it; archaeology in §2.1, restoration in §2.2 |
| 3 | ZABZ-TECH's checkout is 26 commits behind | **MEASURED, NOT SYNCED** — one precise wall, §3 |
| 4 | Fleet gates derive from more than one place | **RECORDED, NOT FIXED** — assessment in §5 |

---

## 1. DEFECT 1 — the POSIX installer, and the boot failure it reproduced

### 1.1 What it was

`scripts/install-client-plugin.sh` pushed the package's `name` into `dsh.profile.bundles` with **no
`dsh.bundle.patch` test at all** (old lines 77–85, blob `f0b23c1c`). `dsh.profile.bundles` is not a
dependency list: the loader mounts every declared name as a patch layer and throws on one whose package
declares no bundle (`dsh-app-boot/lib/index.js:852`; `:831` for one that does not resolve), so **one such
name stops the engine booting** while the engine already running looks perfectly healthy.

The repaired PowerShell installer has enforced the loader's own rule since 2026-09-17 00:3xZ
(`docs/mesh/90-provider-mount.md` §3, after it made ZABZ-YOGA and ZABZ-TECH unbootable). The POSIX one
did not, and it is **the installer the macOS node is provisioned with** — a node whose engine is a
LaunchDaemon with `RunAtLoad` + `KeepAlive{SuccessfulExit:false}` (`docs/mesh/97-fleet-repairs.md` §1.5),
so a profile that cannot boot there is not a node that goes quiet, it is a crash loop the node's own
supervisor sustains. Recorded as `journal/entries/pain/P237.md` before this session; closed by it.

### 1.2 The change (the diff, in words)

One behaviour, three parts, all inside the single-package installer:

* **Enrolment requires the bundle to have been read out of the package's own manifest.** The same node
  process now reads `dsh?.bundle?.patch` from `$PKG_DIR/package.json` and refuses when it is absent
  (the loader's exact test is `=== undefined`; an empty string is refused too, because the loader would
  then try to read a directory as the patch layer and fail on the next boot instead).
* **A declared name that fails the test is REMOVED**, by the same JSON round-trip, with a
  `package.json.bak-<UTCstamp>` copy written first. (The PowerShell installer drops such a name; this one
  now drops it too, and additionally leaves a backup, which `install-client-plugins.ps1` does not.)
* **The package is still LINKED** — resolution by name is a separate need from being mounted as a layer,
  and a service with a `bin` (`mesh-broker`) must keep resolving. The refusal is about naming, not about
  the link.
* Exit codes are now part of the contract and are in the header: `0` installed, `1` no profile at that
  path, `2` usage / no package / no node, **`3` REFUSED** (linked, never named, and any declared name
  removed). A silent exit 0 is how this class stayed invisible for a day; `serve-phone.sh:172` already
  branches on the exit code, so a refusal now reaches it.
* The closing "confirm the client roster carries it" message is unreachable on the refusal path — nothing
  is installed, so nothing is claimed.

`scripts/install-client-plugin.sh` sha256 after the change:
`3c7e3180445e415858fc708ee7771c36b7bd2c52f496a14195cebefcf20b7c43`. Pre-fix blob:
`f0b23c1c0376a63b257d0a05d52fa779b8dc60a7`.

### 1.3 The proof — the failure mode, before and after, in scratch homes

No real profile was touched. Everything below ran against scratch `DSH_HOME` trees under
`%TEMP%\hc99\…` (Git Bash + `PHONE_NODE=/c/Program Files/nodejs/node.exe`), 2026-09-17 10:05 local
(14:05Z). The pre-fix script is `git show HEAD:scripts/install-client-plugin.sh` — not a reconstruction.

**The pre-fix script arms it, and the loader then refuses to compose the profile:**

| step | command | result |
|---|---|---|
| pre-fix installer on a non-bundle package | `bash <HEAD version> packages/mesh-broker <scratch profile>` | `added: dsh-mesh-broker -> …`, **exit 0**; bundles become `[…dsh-web-app, dsh-mesh-broker]` |
| that scratch home, composed | `DSH_HOME=<scratch> node …/dsh/lib/bin.js --profile web --dump-config` | **exit 1**, 16 lines: `Error: dsh: profile bundle "dsh-mesh-broker" declares no dsh.bundle in its package.json` at `dsh-app-boot/lib/index.js:852` |

**The fixed script refuses, and the same home composes:**

| case | what | result |
|---|---|---|
| A | non-bundle package, name not declared | `declares no dsh.bundle -- linked, never named as a bundle: dsh-mesh-broker` + `REFUSED: …` on stderr, **exit 3**; `bundles` unchanged (`["@deepseek-ai/dsh-base","@deepseek-ai/dsh-web-app"]`); the link is created |
| A | that home, composed | `--dump-config` **exit 0**, 539 lines |
| B | non-bundle package **already declared** | `declares no dsh.bundle -- REMOVING from the bundle list (naming it stops the engine booting)`, backup `package.json.bak-20260917T140524Z`, bundles `[…,dsh-plugin-cost]`, **exit 3**; second run is idempotent (`linked, never named`), bundles unchanged |
| C | a real bundle (`packages/plugin-health`) — control | `added: dsh-plugin-health`, backup written, **exit 0**; that home composes **exit 0**, 335 lines |
| D | no argument | `usage: install-client-plugin.sh <package-dir> [profile-dir]`, **exit 2** |

So: the failure is **demonstrated on the pre-fix file**, the refusal is **demonstrated on the fixed one**,
and the positive control proves enrolment of a genuine bundle still happens. The check that a future
session might otherwise trust blindly — "did the refusal path break normal installs?" — is case C.

### 1.4 Why the test is the loader's and not a convention

The plugin packages are `dsh-plugin-*`; the non-bundles in `packages/` are services with a `bin`
(`mesh-broker`) and an empty vestigial directory (`deepseek-proxy`, which has no `package.json` on
ZABZ-TECH at all — measured §3.4). A name shaped `dsh-plugin-*` is therefore *not* a sufficient test, and
neither is "it resolves": `dsh-mesh-broker` resolves perfectly and still stops the boot. The only test that
matches the loader is the loader's.

---

## 2. DEFECT 2 — what actually happened on ZABZ-TECH, and the restoration

### 2.1 The archaeology (this corrects `97` §5.4 and `95` §3.4)

The brief's causal story — a 09:32 restart came back without this morning's provider work — is false in
both halves. Measured on `zabz-tech-ts`, 2026-09-17 13:5x–14:0xZ.

**(a) The 07:00 window did not run on that machine, and did not restart anything anywhere.**

```
$ Test-Path C:\Users\ezabz\.dsh\mesh\restart-0700        (on ZABZ-TECH)
True                       <- but it holds only `http/` (13:53Z) and `logs/` (00:02Z); NO <stamp> directory,
                              and no run.log, anywhere under it (Get-ChildItem -Recurse -File → nothing)
$ Get-ScheduledTask -TaskName 'DSH Mesh 0700 Restart'   (on ZABZ-TECH)
Get-ScheduledTask : No MSFT_ScheduledTask objects found with TaskName equal to 'DSH Mesh 0700 Restart'.
```

On **ZABZ-YOGA** the window did run, and it did nothing:

```
C:\Users\ezabz\.dsh\mesh\restart-0700\  → 20260917-004210, -004258, -004550, -004635, -004732, 20260917-070001
$ Get-ScheduledTask -TaskName 'DSH Mesh 0700 Restart' | Get-ScheduledTaskInfo
state=Ready last=9/17/2026 7:00:00 AM result=1 next=
$ …\20260917-070001\run.log
[07:00:04] gate: OPEN -- no session is running and no agent loop is executing
[07:00:44] install check: every invariant holds
[07:00:44] composition: dump-config exit 0, 620 lines
[07:00:44] STOPPING BEFORE THE RESTART
[07:00:44]   FAILED: docs/mesh/87-harness-fork.md has 10 heading(s) origin/master does not: …
```

So the window's own gate said `OPEN` (nothing of the owner's running), it verified the composition, and it
then **refused at its journal step** because `docs/mesh/87-harness-fork.md` held ten headings the authority's
copy did not. Nothing was restarted by it. (The laptop's engine pid *did* change to 4880 at 08:51:07 — but
that is a different event, not this window, and not this session.)

**(b) The 09:32:02 restart was another session, and it names itself.** `docs/mesh/93-transport-concurrency.md`
§9, written by the stream that was measuring that node:

```
**One engine restart, on `zabz-tech` only**, and the readiness gate was satisfied immediately before it:
`established_on_3099=0`, the route answering `version=0.1.0`, nothing of the owner's running
(`agents.loopsRunning 0`, `sessionsLive 0`, …). Old pid 26140 → new pid 24556, same hand-started command
line, and 533 session files on that machine.
```

The machine's own records agree, line for line:

```
$ Get-Content C:\Users\ezabz\.dsh\multi-window\watchdog.log -Tail 3
[2026-09-17T08:50:32.4727384-04:00] ensure: engine on 3099 not answering the fast probe
[2026-09-17T09:32:00.1494302-04:00] ensure: engine on 3099 not answering the fast probe
$ Get-Content C:\Users\ezabz\.dsh\multi-window\engine-recovery.log -Tail 3
[2026-09-17T08:50:59.9403583-04:00] ensure: engine answering on 3099 (pid 26140)
[2026-09-17T09:32:02.2832377-04:00] ensure: port 3099 not answering, attempt 1/3
[2026-09-17T09:32:09.8007441-04:00] ensure: engine answering on 3099 (pid 24556)
$ Get-CimInstance Win32_Process -Filter "Name='node.exe'"
ProcessId 24556  CreationDate 9/17/2026 9:32:02 AM  …bin.js web --port 3099 --no-open
```

`DSH Engine Watchdog (1m)` (state Ready, last 09:55:57, result 0) is what started the new pid; the old one
had stopped between its last log line (`3099-20260917-085035.log`: `…"at":"2026-09-17T13:31:08.003Z"…health`)
and the watchdog's 09:32:00 probe. **Answer: another session, deliberately, through its own gate — not the
scheduled window running late.**

**(c) Nothing removed the provider, because it was never there.** Four independent measurements, all read
off that machine:

| what | measurement | what it proves |
|---|---|---|
| the manifest's bundle list | live `~/.dsh/profiles/web/package.json`, mtime **2026-09-17 00:32:27** (nine hours before the restart): base, web-app, attention, attention-badge, cost, mobile, windows, health, mesh-http — **no fanout** | the list it came back with is the list it went in with |
| every backup on that machine | `package.json.bak-1789617116473`, `…bak-20260911-153038`, `…bak-20260911-154532`, `…bak-20260917-003227`, `package.json.zabz-bak` — `fanout=False` in **all five** | no revision of that list ever named the provider |
| the resolution path | `~/.dsh/profiles/web/node_modules` holds 8 `dsh-plugin-*` junctions; **no `dsh-plugin-remote-fanout`** | the package could not have resolved even if named |
| the package itself | `packages/plugin-remote-fanout` **does not exist** in that checkout; `git -C … rev-parse --short HEAD` = `8795753`, `git rev-list --left-right --count HEAD...origin/master` = `0 26`, and the package first appears in git at `2200284` (`git log --oneline -- packages/plugin-remote-fanout`) | it was never delivered to that machine |
| the rows the brief places in its patch layer | `~/.dsh/profiles/web/cordis.patch.yml` = 4577 bytes, mtime **9/14/2026 1:17:03 AM**, `providerMentions=0`; the repo copy in that checkout is the same file, and `git show HEAD:profiles/web/cordis.patch.yml` has 0 mentions while `git show origin/master:…` has 1 | the rows are not on that machine either — they are in commits it does not have |

**And the documents that were said to claim it: they do not.** `docs/mesh/91-resident-dispatch-proof.md` §5
and §10 prove the resident-engine call **on this laptop's engine** (pid 4880, port 3099, sessions
`session-a0c11144-…` / `session-80c0abb7-…`) with the child landing on `zabz-tech`; §92 §5.6's resident run
is `[resident] engine pid 28924 on :3098, DSH_HOME=C:\Users\ezabz\.dsh-meshcheck` — a scratch home **on the
laptop**. No document claims the desktop's own engine mounted the provider. `97` §5.4 inferred it from a pid
change; `95` §3.4 repeated the inference. Both are corrected by this file.

### 2.2 The restoration, and how the junction was created safely

Requirements, read from the shared branch rather than assumed: the bundle's own patch layer
(`packages/plugin-remote-fanout/cordis.patch.yml`) **inserts both rows**, but its `remote-fanout` row carries
**no config on purpose** — its own comment says *"A profile that mounts the bundle and configures nothing
fails loudly at boot"* — so the profile layer's `remote-fanout` config row is **mandatory**, not decorative.
Naming the bundle without it would be a new landmine. The committed pair is self-contained: the committed
`lib/index.js`, `lib/provider.js`, `lib/ssh-transport.js`, `lib/remote-script.js` import only each other and
node builtins — the `./nodes.js` / `placement.js` / `broker-client.js` that the **uncommitted** working tree
adds are not referenced by anything committed, and the committed rows do not mention them either. So the
committed pair composes; the working tree's did not have to be used.

**The trust measurement that decided the method** (this machine, 2026-09-17 14:1xZ). One ssh-spawned
`node.exe`, same directory, four junctions:

```
  OK   dsh-plugin-cost           bytes=708
  OK   dsh-plugin-attention      bytes=504
  OK   dsh-plugin-mesh-http      bytes=1504
  ERR  dsh-plugin-session-link   UNKNOWN: unknown error, open 'C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-…'
```

Same reader, same directory, two verdicts — so the trust attribute is on the **junction**, and a junction
created by *this* session is exactly the untested bet `90-provider-mount.md` §3/§6 refused to make on a
machine with no console. (Corroboration from that machine's own history: it booted engine pid 23164 at
**2026-09-16 23:59:16** with `dsh-plugin-session-link` still named, and answered on 3099 — so the *local*
reader traverses that junction and only the ssh-spawned one does not.)

So the junction was created by a **local** process: a one-shot scheduled task for this user, registered with
a new name and none of the four shapes measured to fail (`-Force`, `-Principal`, `-AtLogOn`, `RestartCount`),
started on demand. It reported `logon=Interactive runLevel=Limited`. Its transcript, verbatim in the
essentials (`C:\Users\ezabz\.dsh\mesh\99\install-provider-local.log`, pid 5412, run 2026-09-17T14:10:31Z):

```
STEP 0: repo HEAD 8795753 | package.json True | name/version dsh-plugin-remote-fanout 0.1.0
        dsh.bundle ./cordis.patch.yml | link exists False | patch layer 4577 bytes, provider mentions 0
        bundles before = @deepseek-ai/dsh-base, …, dsh-plugin-mesh-http       (9 names, no fanout)
STEP 1: created C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-plugin-remote-fanout
                -> C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout
STEP 2: TRAVERSAL OK dsh-plugin-remote-fanout v0.1.0 bytes=1152 bundle=./cordis.patch.yml
        child exit=0            <- a SEPARATE process, the test the brief asked for, run BEFORE naming anything
STEP 3: backup cordis.patch.yml.bak-99-20260917T141031Z; wrote origin/master's profile patch layer
        provider rows now: remote-fanout=4 tool-subagent-remote=1
STEP 4: backup package.json.bak-99-20260917T141031Z
        bundles after = @deepseek-ai/dsh-base, @deepseek-ai/dsh-web-app, dsh-plugin-attention,
        dsh-plugin-attention-badge, dsh-plugin-cost, dsh-plugin-mobile, dsh-plugin-windows,
        dsh-plugin-health, dsh-plugin-mesh-http, dsh-plugin-remote-fanout
STEP 5: dump-config exit=0 lines=617 remote-fanout=3 tool-subagent-remote=1
RESULT: installed-and-composing
```

A second local task then made the home layer byte-identical to the repo copy (the first write had preserved
the blob's CRLF; the checkout's copy is LF) and re-verified **the final state**, pid 11764, 14:12:00Z:

```
home patch bytes=10928 repo copy bytes=10928
home sha=850734E86700BEE0… repo sha=850734E86700BEE0… identical=True
bundles=@deepseek-ai/dsh-base, @deepseek-ai/dsh-web-app, dsh-plugin-attention, dsh-plugin-attention-badge,
        dsh-plugin-cost, dsh-plugin-mobile, dsh-plugin-windows, dsh-plugin-health, dsh-plugin-mesh-http,
        dsh-plugin-remote-fanout
  TRAVERSAL OK dsh-plugin-remote-fanout bytes=1152      traversal child exit=0
dump-config exit=0 lines=617 remote-fanout=3 tool-subagent-remote=1
  row: - id: remote-fanout
  row: name: dsh-plugin-remote-fanout
  row: - id: tool-subagent-remote
  row: provider: remote-ssh
  row: toolName: subagent_remote
RESULT: final-state-verified; this task disabled
```

**Files written on that machine, and their provenance:**

| what | where | where it came from |
|---|---|---|
| `packages/plugin-remote-fanout/**` (12 files) | that checkout | `git -C <repo> checkout origin/master -- packages/plugin-remote-fanout` — HEAD stayed at `8795753`, the files are staged at exactly the shared branch's content |
| `profiles/web/cordis.patch.yml` | that checkout | `git checkout origin/master -- profiles/web/cordis.patch.yml` (10928 bytes, previously the 4577-byte 9/14 copy) |
| `profiles/web/cordis.patch.yml` + `.bak-99-20260917T141031Z` | `~/.dsh/profiles/web/` | copied from the checkout, so home ≡ repo copy by hash |
| `profiles/web/package.json` + `.bak-99-20260917T141031Z` | `~/.dsh/profiles/web/` | one name appended by the local task |
| `node_modules/dsh-plugin-remote-fanout` (junction) | `~/.dsh/profiles/web/` | created by the local task, traversed by a separate local process before it was relied on |
| `~/.dsh/mesh/99/install-provider-local.ps1`, `verify-provider-local.ps1`, their two logs, `dump-config-after.txt` | that machine | this session (outside the repo) |

**Task hygiene, as the brief asked me to state it:** `DSH Mesh 99 Provider Install (once)` was
**unregistered** by the second task (`Unregister-ScheduledTask … -Confirm:$false`), after it had already
disabled itself; `DSH Mesh 99 Verify (once)` is **left registered but disabled** — a one-shot in the past,
so it cannot fire again. Remove it with one line:

```powershell
Unregister-ScheduledTask -TaskName 'DSH Mesh 99 Verify (once)' -Confirm:$false
```

**What the mounted provider will target, stated because it is a deployment fact and not a package fact:**
the committed profile row resolves `targetHosts` from `MESH_TARGET_HOSTS`, defaulting to `['zabz-tech']`.
Measured at 14:0xZ: that variable is **not set** machine-wide, user-wide, in the process environment, in
`C:\ProgramData\dsh-mesh.env` (which holds only `MESH_HTTP_SECRET`), or anywhere under `~/.dsh`. So on
ZABZ-TECH a `subagent_remote` call would dispatch to `zabz-tech` — **itself**. That is the fleet default
working as written, it is overridable per node by one environment variable, and changing it is a deployment
decision on the shared branch, which is why it is reported and not invented here.

### 2.3 The silent loss that did happen

Worth recording next to the one that did not: the repair `90` §3 made on that machine **dropped
`dsh-plugin-session-link` from the bundle list because its junction could not be traversed** — and that drop
is **not durable**. Measured with the fixed installer's own test, run on that machine: `Test-Path` on the
junction = True, it is a reparse point with the right target, and the package declares
`dsh.bundle.patch` → the keeper classifies it `LINK` + bundle and **names it**. So the next successful local
`sync.py` / `install-client-plugins.ps1 -RequireAll` on that machine re-adds the name that was deliberately
removed. It is *probably* not a boot hazard there — the local engine traversed that junction at 23:59:16 —
but the repair is a one-off edit to a machine-local JSON file, and nothing in the keeper can reproduce it.
The general shape: **a hand-drop is not a keeper**.

---

## 3. The repo sync — measured, and not forced

### 3.1 The state, established before anything moved

Read on `zabz-tech-ts` at 14:0xZ, read-only, with `git fetch --prune` first:

```
$ git status --porcelain
A  packages/plugin-remote-fanout/**  (12, this session, staged from origin/master)
M  profiles/web/cordis.patch.yml     (this session, staged from origin/master)
 M scripts/phone-gate.py             (another stream — see 3.3)
?? packages/plugin-mesh-http/        (24 files, untracked, 7 of them NOT in git — see 3.2)
?? scripts/mesh-capacity-probe.ps1
$ git log --oneline origin/master..HEAD     → (empty)      # no local commits
$ git stash list                            → (empty)      # nothing stashed
$ git rev-list --left-right --count HEAD...origin/master
0	26
$ git rev-parse HEAD origin/master
879575309762248fa7c5cc8ad25da640c500af5a   bfeb1fa9b11106c4956c5c2253417b6dfcf48564
fetch_exit=0, counts_after=0	26, origin/master_after=bfeb1fa9…
```

So: **nothing local to preserve in git** — no local commits, no stashes, and the fast-forward is available
in principle. What blocked it is in the working tree, and this is where the measurement turns into a wall.

### 3.2 The precise wall: the fast-forward would overwrite newer-than-branch work

30 untracked paths, 24 of which `origin/master` tracks. Fifteen are byte-identical to `origin/master`;
**nine differ**, and for seven of them the comparing table is the deciding evidence (all hashes
`git hash-object` / `git rev-parse origin/master:<path>`, taken on ZABZ-YOGA at 14:0xZ and on ZABZ-TECH):

| path (under `packages/plugin-mesh-http/`) | laptop worktree | `origin/master` | ZABZ-TECH untracked |
|---|---|---|---|
| `lib/node-identity.js` | `02b7e5c6` | `89b5c327` | **`02b7e5c6`** |
| `lib/index.js` | `c020b30d` | `75658086` | **`c020b30d`** |
| `lib/runner.js` | `d70dbfd1` | `60636d1c` | **`d70dbfd1`** |
| `lib/handler.js` | `15b79731` | `833833fd` | **`15b79731`** |
| `bin/mesh-http.mjs` | `016d06eb` | `e64a0c0f` | **`016d06eb`** |
| `bin/mesh-dispatch.mjs` | `035e41a8` | `770833d5` | **`035e41a8`** |
| `test/mesh-http.test.mjs` | `43278d6d` | `e6bcb322` | **`43278d6d`** |
| `scripts/mesh-capacity-probe.ps1` | `48fd76a8` (= origin/master) | `48fd76a8` | `0e9eb0a0` |

The seven are the transport stream's **uncommitted** revision — the same bytes the laptop's working tree
holds and the set that includes `lib/node-identity.js`, whose fix `93` §8 proved live on that machine
(`identityDegraded: false` with the full fqdn). **They exist in no commit.** A fast-forward to `bfeb1fa`
would overwrite all seven with `origin/master`'s older content, and that content is what that machine's
live `/mesh/health` route serves (its junction points into that directory) — so the machine would keep
serving the newer code until its next restart and then silently regress to the older revision, undoing a
proved fix on the node the proof was taken on. Restoring them afterwards would put the checkout back into
the dirty state that makes the *next* sync refuse — the drift, re-created.

That is the measurable reason this session did not force it, and the wall is one step away from removal:

> **When the stream that owns `packages/plugin-mesh-http/**` commits its working tree to `master`, this
> machine's fast-forward becomes a pure upgrade and should be run immediately.**

Until then the sync is not merely optional-with-caveats, it is *blocked by git anyway*: the 24
untracked-collision paths make `git pull --ff-only` refuse, which is also what the machine's own sync
keeper is reporting (§3.4).

### 3.3 An aside that is not an aside: the gate on that machine is already the canonical one

`scripts/phone-gate.py` is ` M` in that checkout, which looks alarming until hashed:

```
HEAD:scripts/phone-gate.py          = 8be78057…  72210 bytes   (the old one)
origin/master:scripts/phone-gate.py = 9970cca2… 121763 bytes   (the canonical repaired gate)
working tree  scripts/phone-gate.py = 9970cca2… 121763 bytes   ← identical to origin/master
```

So a fast-forward would rewrite that file with the content it already has. The ` M` is a partial delivery,
not a local edit; **no gate work is at risk in this sync**, and the machine's running gate (pid 27472) is
already the canonical revision, as `97` §2.4 measured.

### 3.4 What the 26 commits cost while they are missing

| cost | measurement |
|---|---|
| the machine's own sync keeper is **failing**, and says so | `~/.dsh-sync-status/status.json`, updated **2026-09-17T14:02:03Z**: `"result":"attention"`, `"detail":"pull --ff-only refused: histories diverged (26 behind / 0 ahead) and step 2b preserved nothing. Needs a human."`, `"behind":26,"ahead":0,"local_commits_preserved":false` |
| the installer on that machine is the **pre-fix** one | `Select-String scripts/install-client-plugins.ps1 -Pattern 'dsh\.bundle\.patch'` → **0 hits** (the gate lives only in `origin/master`); `scripts/autosync.ps1:377` runs `sync.py` **from a snapshot of HEAD**, and the snapshot-guard ("never link into a transient snapshot") is also only in `origin/master` |
| but it is not armed today, measured rather than assumed | all 9 real packages in that checkout declare `dsh.bundle.patch`; `deepseek-proxy` has **no `package.json` at all**, so even the pre-fix installer skips it (`if (-not (Test-Path $pkgJson)) { continue }`). The one name it would add that is not already there is `dsh-plugin-session-link` (§2.3) |
| what it does **not** cost | the v2 route works (children ran at 13:36:40, 13:46:06–13:46:13, 13:53:11–13:53:31Z, all `exit=0`), the gate is canonical, and the provider is now mounted |

**What a sync and then a restart would change on that machine, and whether it is safe.** It would install the
fixed installer and the snapshot guard (both improvements), bring `packages/plugin-mesh-http` to a revision
*older* than what the engine is running now, add nothing to the bundle list, and leave the gate unchanged
(§3.3). A restart after that sync would therefore **regress the route's code while still booting** — silent
capability loss, the class this program keeps re-finding — which is why the sync should be the commit's
follow-up and not its predecessor. The boot surface itself is unchanged by the sync: same bundle list, same
patch layer, and `--dump-config` exit 0 before and after (verified locally at 14:10:31Z and 14:12:00Z).

**Recommendation to whoever holds that decision:** do not hand-carry the rest of the 26 commits (that is
the failure mode the fork work removed). Get the transport stream's `packages/plugin-mesh-http/**` committed,
then run, on ZABZ-TECH, at a moment when nothing is executing there:

```powershell
cd C:\Users\ezabz\code\harness-config
git fetch origin
git rev-list --left-right --count HEAD...origin/master      # expect 0 <n>
git merge --ff-only origin/master                            # no reset, no rebase, no --force
node C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js --profile web --dump-config   # must exit 0
```

If git still refuses, it will name the path, and that path is a decision for its owner — not a reason to
`reset`.

---

## 4. Would a restart of ZABZ-TECH's engine be safe now?

**It is not forbidden by measurement — and it is not needed.** Measured at 14:12Z:

| reading | value |
|---|---|
| engine | pid 24556, `bin.js web --port 3099 --no-open`, started 2026-09-17 09:32:02 local |
| established connections on 3099 | **0** |
| node processes on the machine | **2** (the engine and `alpine-listener.js`, pid 24984, started 08:50:02) |
| last v2 `/mesh/run` child | **13:53:31Z** (`local-159dbru8`, exit 0, `meshHostLineSeen:true`) |
| last route activity | 14:05:36Z, a `health` verdict — no work in flight |
| the engine log's own counter | `inFlightAfter:0 queuedAfter:0` on the last run |

So no sibling stream and nothing of the owner's was executing on that machine at the moment of the
restoration. The reason not to restart is different and simpler: **a restart is not what makes the mount
real for the record** — a fresh local `--dump-config` process composed the whole profile, which is what the
next engine start will do — and the restart would also load the other streams' in-flight code state. The
mount takes effect at that machine's next start, whichever session is responsible for it. The one command,
for whoever wants the effect *now*, is its own supported path (`pwsh multi-window/dshw.ps1 restart`), not a
hand-rolled `Start-Process`; a child of an ssh shell dies with its job object (`dshw.ps1:508-515`).

The laptop's engine (pid 4880) was not touched, was never a candidate, and its 07:00 window's refusal is
what protected it.

---

## 5. Fleet gates from one place — assessment (recorded, NOT fixed)

### 5.1 The five gates, measured today

| node | running gate path | bytes | sha256 | where the file comes from | updatable by `git pull`? |
|---|---|---|---|---|---|
| `zabz-yoga-1` | `…\harness-config\scripts\phone-gate.py` | 121763 | `4cf9c268…632a` | a git checkout | **yes** |
| `zabz-tech` | `…\harness-config\scripts\phone-gate.py` | 121763 | `4cf9c268…632a` | a git checkout (worktree == `origin/master`, §3.3) | **yes** |
| `secratary` | `/home/zabz/harness-config/scripts/phone-gate.py` | 121763 | `4cf9c268…632a` | a git checkout | **yes** |
| `lakewooechsmini` | `/Users/lpt/.dsh-gate/scripts/phone-gate.py` | 121765 | `9e6a8650…9545` | a hand-placed directory | **no** |
| `zabz-tech-linux` | `/home/zabz/dsh-mesh/repo/scripts/phone-gate.py` | **105940** | **`4ec735cd…1661`** | a hand-placed directory | **no** |

Read over each node's own filesystem, 2026-09-17 14:1xZ; the `zabz-tech-linux` and `secratary` units were
read with `systemctl show phone-gate -p ExecStart`, the others are `97` §2.4's measurement, unchanged here.

**The brief's two claims, checked:**

1. **The Linux node's third revision out of `…/dsh-mesh/repo/scripts/` is confirmed, and the reason is
   stronger than "a directory a pull can never update": it is not a repository at all.**
   ```
   $ cd /home/zabz/dsh-mesh/repo && git rev-parse --is-inside-work-tree
   fatal: not a git repository (or any of the parent directories): .git     (×5 — no .git anywhere up the tree)
   $ ls -la /home/zabz/dsh-mesh/repo/scripts/phone-gate.py
   -rwxr-xr-x 1 zabz zabz 105940 Sep 16 19:30
   $ sha256sum …/phone-gate.py   →  4ec735cd0c747b86dccecbe6d0ade5822452dd80c64571e2804d2fd154b01661
   ```
   `…/dsh-mesh/` holds only `repo/`; nothing in that path is versioned, so the file's *content* has no
   provenance on that node and the drift is invisible to every `git` check in the fleet. Its allow-list
   *is* beside it (3051 bytes, 09:20 today, installed by yesterday's repair) — which is the only reason it
   refuses a foreign device at all.
2. **`secratary`'s stale 40,206-byte gate in a second location is confirmed — with a correction to `97`
   §2.4's description of why it is stale.**
   ```
   $ sha256sum /home/zabz/code/harness-config/scripts/phone-gate.py
   8ef819be3b193633acca153450e69f96e1adffb71cf2e6215a40c3d36db2d942   40206 bytes, mtime Sep 15 19:14
   $ ls -la …/scripts/phone-gate-allow.txt
   ls: cannot access '…/phone-gate-allow.txt': No such file or directory       ← the fail-open hole, pre-created
   ```
   But that file is **the committed blob at that checkout's `HEAD` *and* at its own `origin/master`**
   (`git cat-file -s HEAD:scripts/phone-gate.py` → 40206, blob `9d3d245`; same for `origin/master`; worktree
   clean; last commit touching it `246c3a9`), with `HEAD...origin/master` = `0 0` and remote
   `secretary:/home/zabz/harness-config.git`. So it is **not** "a directory a `git pull` can never update":
   it is a real checkout whose remote-tracking ref is stale, and one `git fetch && git pull` there would
   bring the canonical 121,763-byte gate. The same 40,206-byte blob is committed in
   `/home/zabz/code/harness-config` on `zabz-tech-linux` (`HEAD f14bfde`, `0 0`). What makes both dangerous
   is not that they cannot be updated — it is that **nothing updates them and nothing checks them**, and
   neither has an allow-list beside it, so a unit pointed at either one re-creates yesterday's hole exactly.

### 5.2 What it would take to make the fleet's gates derive from one place

The mechanism that produced the hole is in the gate's own first line of configuration, not in any one
deployment: `ALLOW_FILE = Path(__file__).resolve().parent / "phone-gate-allow.txt"` (line 2055 canonical,
1772 in the Linux node's revision; `97` §2.4 shows all three revisions resolve it the same way). **A file
resolved beside the running script is only as durable as whatever put the script there** — so when two of
five nodes run a hand-placed copy, the allow-list's location is a hand-placed fact too, and its absence is
noticed only by a log line (`2026-09-16T19:30:46 phone-gate: NO DEVICE RESTRICTION — … does not exist;
every device on the tailnet will be signed in automatically`), which is a warning where it must be a refusal.

Three changes would make "one place" true, in increasing order of cost:

1. **Make the two coordinates explicit and fail-closed.** Give the gate `--allow-file <path>` (or
   `PHONE_GATE_ALLOW_FILE`), have each unit pass it, and make the *absence* of a configured allow-list a
   refusal to sign anyone in — not a warning that signs everyone in. A unit that names its own allow-list
   cannot become fail-open by accident, and "no path configured" is a startup error rather than a log line
   nobody reads. This is the change that would have prevented the hole with no fleet-wide coordination.
2. **One delivery path for the file, and a check that the running gate came from it.** Every node can hold
   a `harness-config` checkout (four of the five do, in some form); point every unit at
   `<checkout>/scripts/phone-gate.py` and let `git pull`/`sync.py` be the only thing that writes it. Where a
   node genuinely cannot hold a checkout, copy **the script and the allow-list together** and record the
   expected `sha256` of both in the repo. Then add one **keeper** — the shape of `mesh-hygiene.sh` /
   `phone-gate-ensure.ps1`, which exist for the Windows side only — that on each node compares the *running*
   gate's hash, the *configured* allow-file's hash and the device count against the canonical values, and
   exits non-zero on drift. The evidence that this is needed rather than nice: yesterday's hole existed on
   one node for ~21 hours and was found by an audit, not by any keeper; today's table found a third gate
   revision and two stale copies the same way (`97` §2.4's table is a per-incident measurement that should
   be automatic).
3. **Then the file's own drift becomes findable by `git`** — today the fleet has gate revisions
   `4cf9c268`, `9e6a8650` and `4ec735cd` with no common lineage, and two of the three live outside any
   repository. Note the deliberate limit of this recommendation: `97` §2.4 measured that the *behaviour* of
   the Linux node's revision is correct (403 foreign / 200 owner / 200 loopback, probes C–G), so this is a
   provenance and updatability defect, not a live vulnerability. It is worth fixing precisely because it
   will not announce itself next time.

**Is the file-beside-the-script convention worth keeping?** No — it should be replaced by an explicit,
configured path, with the beside-the-script location kept only as a *default for the canonical checkout*.
The convention assumes the script and its list travel together, and this fleet has measured twice
(`97` §2.4, §5.1) that they do not: one node got the script without the list and became fail-open; two
nodes got the script without the list and are one unit-file edit away from the same. A convention whose
violation is silent and whose consequence is "every device on the tailnet is signed in" should not be a
convention.

---

## 6. What I could not verify, stated as refusals

| not verified | why | what would verify it |
|---|---|---|
| **that ZABZ-TECH's next engine start mounts the provider** | restarting pid 24556 needs a decision this session does not own, and a restart also loads three other streams' in-flight state; a local `--dump-config` is the strongest available stand-in and it exits 0 with both rows | that machine's next start, or a restart in a quiet minute: `curl -s http://127.0.0.1:3099/api/session/list` on a `zabz` session, or the `dshw.ps1 restart` window |
| **that a `subagent_remote` call from a resident session on that machine lands anywhere useful** | the row's `targetHosts` is unset there and defaults to `['zabz-tech']` — the machine itself; and no child turn was dispatched from its engine, which costs money and is the owner's call | the acceptance command `91` §10 uses, run from a session on that machine: *"Call `subagent_remote` once … then report its raw output"* |
| **whether the junction created by the local task is traversable by the *engine's* precise logon context** | the separate-process traversal and a fresh local `--dump-config` both succeeded, and the engine boots through junctions created that way (8 of them), but "the engine's own process" and "a task-started pwsh" are not provably the same token | the next engine start on that machine, with `--dump-config` re-run first; if it fails, the rollback is the one line in §2.2 (drop the name) |
| **the sync** | §3.2: seven files newer than `origin/master`, in no commit | the owning stream commits `packages/plugin-mesh-http/**`, then the fast-forward |
| **`zabz-tech-linux`'s third revision against the canonical one, by diff** | `97` §4 already refuses this and it is not this session's file; the behaviour is proven correct there | `diff` of `4ec735cd` vs `4cf9c268`, or a fresh probe round after the Mac's `9e6a8650` is diffed too |
| **why the fix rejected `97` §2.4's "far behind" for the secratary copy** | its `origin/master` is a *local* remote-tracking ref; `0 0` against it does not prove the true shared branch is 0 ahead | `git fetch` in `/home/zabz/code/harness-config` on that node (not run: that checkout is not this session's) |

---

## 7. Provenance

Every command below ran on **ZABZ-YOGA** unless it names a node, between **2026-09-17T13:50Z and 14:25Z**.
Cross-node reads were `ssh -o BatchMode=yes -o ConnectTimeout` to `zabz-tech-ts`, `linux-pc-ts`,
`secratary-ts`; Windows remotes were driven with `powershell -NoProfile -EncodedCommand <base64>` because
their default ssh shell is PowerShell and nested quoting had already destroyed one probe attempt.

* **The installer (§1).** Read at 13:52Z; patches written 13:55Z–14:00Z; the proof ran at 14:05Z in
  `%TEMP%\hc99\{pre,a,b,c}\scratchnode\.dsh\profiles\web` via `C:\Program Files\Git\bin\bash.exe` with
  `PHONE_NODE=/c/Program Files/nodejs/node.exe`. Loader: `…\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js`.
  Pre-fix file from `git show HEAD:scripts/install-client-plugin.sh`; `HEAD` = `bfeb1fa`. No real profile
  was pointed at by any of it.
* **The archaeology (§2.1).** ZABZ-TECH at 13:53Z–14:02Z: task inventory, `watchdog.log`,
  `engine-recovery.log`, `3099-20260917-093202.log`, `Win32_Process`. The laptop's window at 13:53Z:
  `~/.dsh/mesh/restart-0700/20260917-070001/run.log` and `Get-ScheduledTask … | Get-ScheduledTaskInfo`.
  The bundle-list history at 13:56Z (`package.json` + five backups, `Get-FileHash` on each).
* **The trust measurement (§2.2).** ZABZ-TECH at 14:08Z: an ssh-spawned `node.exe` reading four junction
  targets. The restoration: scripts written 14:09Z (sha256 `42a3b819…094d` verified on both sides),
  task registered and started 14:10:2xZ, transcript read 14:10:31Z; normalisation + final verification
  14:12:00Z (home and repo copies both `850734E86700BEE0…`, 10928 bytes).
* **The sync assessment (§3).** ZABZ-TECH at 14:0xZ: `git fetch`, `git status`, `git log origin/master..HEAD`,
  `git stash list`, `git rev-list --left-right --count`, the 30×2273 untracked-vs-`origin/master` set
  comparison with `git hash-object` on each collision. The laptop's comparison hashes at 14:1xZ.
  `~/.dsh-sync-status/status.json` read at 14:14Z (its own `updated` field: 14:02:03Z).
* **The gates (§5).** `linux-pc-ts` and `secratary-ts` at 14:15–14:20Z: `systemctl show phone-gate -p ExecStart
  -p MainPID -p ActiveEnterTimestamp`, `ls -la`, `sha256sum`, `find`, and `git cat-file -s
  HEAD:scripts/phone-gate.py` / `origin/master:…` / `rev-list --left-right --count` inside
  `/home/zabz/code/harness-config`.
* **No engine was restarted, no process was killed, and no git ref was moved** on any node. The only
  processes this session started were its own scratch shells, two scratch `node --dump-config` runs on the
  laptop, and the two one-shot scheduled-task runs on ZABZ-TECH (pids 5412 and 11764) that the record
  above quotes.
