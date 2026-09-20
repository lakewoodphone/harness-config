# 100 — The idle restart window: taking the owner's one interruption at the first idle moment

**Program:** `docs/mesh/` — the activation half of `90-provider-mount.md` (the placement rows, inert
until a restart) and of `93-transport-concurrency.md` (the route package on this node).
**Date:** 2026-09-17, written between 14:05Z and 15:00Z. **Host:** `ZABZ-YOGA`, engine pid **4880** on
:3099, the owner's live work running throughout.
**Author:** a delegated build session, not the owner.
**What was NOT done:** **no engine was restarted on any node.** The owner's engine (pid 4880) and the
desktop's engine were both running before this session and were still running after it. Nothing was
installed: no installer was applied, no live layer was written, no junction was touched. The only
things created are the three artefacts named in §1 — and one scheduled task, which is disarmed by
nothing but the gate it runs.

---

## 0. The answer in one screen

| | |
|---|---|
| the window | `scripts/mesh-restart-when-idle.ps1` — a **wrapper** around the machine's proven window, `scripts/mesh-restart-at-0700.ps1`, called with `-SkipJournal` |
| the task | `DSH Mesh Restart When Idle`, repeating every 15 minutes, `StartWhenAvailable`, battery-safe, next run 10:29:23 local |
| it decides when | from **evidence on every tick**: the engine's own `/healthz` census and the phone gate's `/mesh/capacity`. Any running session or any executing agent loop ⇒ **DEFER, exit 0** |
| it costs, while the owner works | **~1.0 s** to decide (measured 1033 ms), plus ≤12 s when it owes an explanation |
| it restarts **once** | then records a marker holding the new pid, and every later tick that sees that pid does nothing |
| what one restart lands | (a) the placement rows in the `web` profile's patch layer; (b) `dsh-plugin-mesh-http` **v0.2.0** on this node, with its identity fix |
| the refusal, live, right now | `DEFERRED -- 16 running session(s), 16 agent loop(s)`, exit 0, ids and titles named — §3.3 |
| the thing that nearly made it pointless | **the live patch layer does NOT carry the placement rows, and a 15-minute autosync rewrites it from HEAD — which does not carry them either.** §5. The window's own install step is what closes this, in time for the restart. |

---

## 1. What was built, file by file

| file | what it is |
|---|---|
| `scripts/mesh-restart-when-idle.ps1` | **new**, 1141 lines. The idle window: light gate → idempotence marker → snapshot → route-package verification → ONE call to the 07:00 window with `-SkipJournal` → verification of both activations → marker → rollback. |
| `docs/mesh/100-restart-when-idle.md` | this file. |
| task `DSH Mesh Restart When Idle` | registered on `ZABZ-YOGA`, priority/user `ezabz`, `Interactive`, `Limited`. §7. |
| `~/.dsh/mesh/restart-when-idle/` | the window's own records: `run.log`, `decisions.log`, `refusals/latest.json`, `.done.json`, and one `<stamp>/` directory per run that got past the gate. |

It re-implements **no** window logic. `mesh-restart-at-0700.ps1` is the machine's proven path
(gate → snapshot → install re-verify → ONE `dshw restart` → verify), and this script calls it. What
the wrapper adds is the four things the brief asked for and the inner window does not have:

1. a gate that runs **first** and **cheaply**, so 96 ticks a day cannot accumulate work on a machine
   in use;
2. an **idempotence marker** keyed on the restarted engine's pid;
3. the **placement-row** verification the 07:00 window does not make;
4. the **route-package** verification, and the refusal to restart if it cannot be made.

**Why `-SkipJournal` is passed, and why that is a decision rather than an omission.** The 07:00
window's step 3 converges the tree, pulls, commits and pushes. That is right for a once-a-day window a
human scheduled and wrong for an unattended 15-minute one: it would `git add` about twenty paths that
belong to other sessions' live work and publish them with nobody asking. This window's job is to
**activate** configuration, not to publish a tree. Everything that makes a restart safe is kept: the
install re-verify (which is also what applies the placement rows), the `--dump-config` pre-flight, and
the refusal to restart if any step before it fails.

---

## 2. The order, and the cost of each step

```
STEP 1  the gate            light pass: token, cookie, /healthz, gate /mesh/capacity        ~1.0 s
                            + /api/session/list ONLY when it owes titles (deferral)           ≤12 s
STEP 2  already done?       the marker, keyed on the engine pid                              ~0 s
STEP 3  snapshot            full pass: session list, net connections, processes, files      ~40 s
                            + placement evidence (live layer + composed tree)                ~10 s
STEP 3B route package       installer --check, deployed vs repo, the package's own suite     ~25 s
STEP 4  the window          pwsh mesh-restart-at-0700.ps1 -SkipJournal                       minutes
STEP 5  verify               both activations, healthz, gate, ONE process, corpus            ~40 s
STEP 6  marker              written on the RESTART, not on the verification                  ~0 s
```

**TIMINGS ARE MEASURED, AND THAT IS WHY THE GATE IS SPLIT.** On this laptop with the owner's fleet at
17 concurrent agent loops (2026-09-17 ~10:26 local):

| call | cost |
|---|---|
| launch token from the launcher log | 173 ms |
| cookie minted from that token | 459 ms |
| `GET /healthz` (census: every session's id and status) | **49 ms** |
| phone gate `GET /mesh/capacity` (independent reading) | 274 ms |
| `POST /api/session/list` (the only surface with **titles**) | **15,816 ms and 1.38 MB** when quiet, **>40 s** at 17 loops |
| `Get-NetTCPConnection` × 3 | 7,099 ms |
| session-file scan (`sessions/**/session.v3.jsonl.zstd`) | 4,738 ms |
| process-table read (`Win32_Process`) | 908 ms |

So the gate reads the two things that **decide** it — the engine's own census and the gate's own
reading — and nothing else. A tick on a machine in use costs about a second instead of half a minute.
The expensive readings happen only when the gate opens, or, on a deferral, only when titles are owed.

---

## 3. The gate

### 3.1 What it refuses on

**Any** session whose census status is `running`, or **any** non-zero `agentLoopsRunning` ⇒ DEFER,
`exit 0`, nothing written to the engine. Two independent readings are taken
(`/healthz` and the phone gate's `/mesh/capacity` on loopback), and the refusal is on the **union**
(`> 0`), never on a threshold, because the two legitimately disagree by one as sessions start and
settle between the calls.

### 3.2 A failed title read is reported as a failure, not as quiet

`/api/session/list` did not answer inside 40 s while the owner's fleet sat at 17 concurrent loops.
The first version of this window then printed *"no session row carries running=true"* — which is
exactly the **"an empty result is not evidence of health"** failure this system has paid for most. It
now names **every id from the census** (which costs 49 ms and is unaffected), adds titles when the RPC
answers, and otherwise prints:

```
  TITLES NOT READ: the session/list RPC did not answer ok within 12s, so TITLES could not be read;
  the ids below come from the engine's own census in /healthz and are unaffected
```

### 3.3 The refusal branch, RUN LIVE (the owner was working, so it declined)

Raw, `2026-09-17 10:10:10 local`, exit **0**, nothing restarted. Titles were read on this run:

```
[10:10:10] engine pid 4880, started 09/17/2026 12:51:07, sessions live 40, rows 636
[10:10:10] agentLoopsRunning=16  (the phone gate's own reading: 16)
[10:10:10] sessions running: census 16, /api/session/list 16
[10:10:10] listeners on :3099 1 (pids 4880); engine-shaped processes 1

[10:10:10] STEP 1 RESULT: DEFERRED -- the owner is working; this window does nothing

sessions found running (id / origin / title), newest first:
  410113e6-a7d3-4182-8323-efddc8e1ea2b  subagent   Build and install the spend guard
  3d31d821-8b2f-42f5-8743-e31d93bb279c  subagent   Schedule the activation restart window
  f66a0bf4-2d01-4d56-913b-ae5dc8695529  subagent   Fix the POSIX installer and restore the desktop
  41771d66-0f5a-4265-baf2-7e9ec410ac0c  subagent   Fix the broker's two placement defects
  9616e13e-d858-46eb-aaf2-ab5e456d39aa  subagent   You are one workstream in …
  9832afeb-595c-48d5-b926-378a83be4a3e  subagent   You are one workstream in …
  686799cc-c9ab-487e-afa9-fb9d42fcf4ba  subagent   You are one workstream in …
  2c79505c-ed04-4b81-9b63-2cbdca3a61cf  subagent   You are one workstream in …
  8103e1de-7b32-40b8-aaa7-8624160e8d18  subagent   You are one workstream in …
  09272c34-4135-4a58-9af0-c24b899aafe1  subagent   You are one workstream in …
  3c41695c-1863-4df5-86a5-e8dfa0bf6e23  subagent   You are one workstream in …
  5fed82e1-b481-40dd-aca3-c1618c3e2ea6  subagent   You are one workstream in …
  session-41868590-a7db-492b-9104-f76df3d0c714  Audit and build LPT website setup
  session-b451d9c3-258d-49a5-8722-cce32b15ea85  Audit LPT website redesign status
  session-1b5b4ddc-5b7d-4936-a93d-cb3d8d9c096c  Full CFO orchestration for finances
  3bfaa9fd-72e4-426c-a964-ea6ce32a50d4  subagent   F2 login reachability build

[10:10:11] DECISION: DEFERRED -- 16 running session(s), 16 agent loop(s)

mesh-restart-when-idle: DEFERRED -- 16 running session(s), 16 agent loop(s); nothing was restarted.
EXIT=0
```

Read twice: the ids are the owner's **own fleet**, mid-flight, and one of them is the very session
that wrote this window. A machine being worked on cannot be restarted by a schedule — including by the
schedule that was built to restart it.

A later run at 17 loops produced the same verdict with **no titles** and said so (§3.2), which is the
honest shape of the same outcome. `refusals/latest.json` always holds the full evidence of the most
recent deferral, and `decisions.log` holds one line per tick.

---

## 4. Is the gate open right now? No — and here is why that is not a problem

| reading | value | when |
|---|---|---|
| `agentLoopsRunning` | 16–17 | 10:10 and 10:26 local |
| sessions the census calls `running` | 16–17 | same |
| listeners on :3099 | 1 (pid 4880) | same |
| the phone gate's own reading | 16–17 loops, 40–42 sessions | same |

The window will fire when both readings are **0**. On this machine that is when the owner's fleet has
finished — not before.

---

## 5. THE FINDING THAT CHANGES THE PLAN: the live layer is stale, and a 15-minute job keeps it stale

**The brief's premise was that the placement code is "installed on this laptop but inert until the
engine restarts". Half of that is true and half is not, and the difference decides whether this window
does anything at all.**

What is true: the **package** is linked and current. `~/.dsh/profiles/web/node_modules/dsh-plugin-remote-fanout`
is a junction into this checkout and carries `lib/broker-client.js`, `lib/placement.js`, `lib/nodes.js`.

What is **not** true: the **rows** are not in the layer that turns them on. Measured 2026-09-17:

| fact | reading |
|---|---|
| live layer `~/.dsh/profiles/web/cordis.patch.yml` | 10,928 bytes, written **09:47:17**, sha256 `850734E8…` — **no `placement:`, no `brokerSsh`, no `brokerUrl`** |
| this checkout's `profiles/web/cordis.patch.yml` | 12,598 bytes, edited **09:31:11** — carries all three (lines 135/137/138) |
| live vs `git show HEAD:profiles/web/cordis.patch.yml` | **byte-identical** |
| `dsh --profile web --dump-config`, filtered to the `remote-fanout` row | the row is present, its `config:` has **no** placement keys |

So a restart **without** an install step would boot a composed configuration that does not carry the
named rows. (It would probably still *behave* as broker placement, because
`packages/plugin-remote-fanout/lib/index.js:64-68` resolves *nothing at all* to `broker`, and
`brokerSsh`/`brokerUrl` fall back to `secratary-ts` / `http://localhost:3091` inside the package — but
"would probably behave" is not what this window is for, and the designed verification would have
failed.)

**Why the layer is stale, with the chain of evidence:**

1. `~/.dsh/profiles/web/cordis.patch.yml.bak-20260917-134717` — 12,598 bytes, content mtime 09:31:11:
   the **placement version**, displaced at **13:47:17Z = 09:47:17 local**.
2. `scripts/sync.py:184-187` is the only writer that names a backup `<file>.yml.bak-<UTC stamp>`, and
   it copies `REPO/profiles/<name>/cordis.patch.yml` over the live layer.
3. `scripts/autosync.ps1:358-380` runs `sync.py` **from a snapshot of HEAD exported to `%TEMP%`**:
   *"the apply now runs against a snapshot of HEAD … committed changes land, and nobody's in-flight
   work is published or lost"*. HEAD's copy has no placement keys (verified: `git show
   HEAD:profiles/web/cordis.patch.yml` matches neither `placement:` nor `brokerSsh`).
4. The task `PersonalSecretary-HarnessSync` last ran **09/17/2026 09:47:02** (result 1) and repeats
   **every 15 minutes** — 09:32 → 09:47 exactly, 15 minutes after the installer's own local-stamped
   backup `.bak-20260917-093240` at 09:32:40.

**The reconstruction:** at 09:31 the placement rows were written to the repo working tree; at 09:32:40
`mesh-provider-install.ps1` applied them to the live layer (backing up the then-live 10,928-byte copy);
at 09:47:17 autosync rewrote the live layer from HEAD and took them out again. They are working-tree
edits, so **they cannot survive an autosync tick until they are committed.**

**Why this does not make the window pointless, MEASURED rather than reasoned.** The inner window's
step 4 runs `mesh-provider-install.ps1 -Check`. Run read-only on 2026-09-17 at 10:33 local it exited
**1** with two problems and **`0 change(s) (check only: nothing was written)`**:

```
2. the profile patch layer (the deployment config)
  repo layer carries the remote-fanout row: yes
  [FAIL] the live patch layer (...\.dsh\profiles\web\cordis.patch.yml) differs from the repo's
         -- the engine would boot without the provider config
5. the zabz preset (the TOOL half)
  make_zabz_preset.py --check: in sync
  [FAIL] the deployed preset differs from the repo preset -- the engine reads the deployed copy
6. pre-flight: will the engine boot?  (dsh --profile web --dump-config)
  dump-config exit 0, 620 lines composed
```

So the window **will** apply the installer (that is what its step 4 does when `-Check` fails), and the
apply copies this checkout's layers over the live ones **before** the restart that reads them. The live
layer was byte-identical before and after the read-only check (10,928 bytes, mtime `09:47:17`
unchanged), which is what makes the check safe on a machine in use.

Note what the same output says about the shape of "the activation": there are **three** stale things,
not two — the patch layer (the placement rows), the **deployed `zabz` preset** (the `tool-subagent-remote`
row, the tool half of the provider), and the **running** route package (§6.2). The installer's step 5
covers the preset; its step 2 covers the layer; the restart covers the engine.


**What the window does about the durability hole, and what it cannot do.** After the restart the
window checks whether HEAD carries the rows and, if not, records a warning naming the exact
consequence — *the running engine keeps what it read at boot; the NEXT restart would not* — and the
marker keeps `warnings` so a later reader sees it. It does **not** commit anything; that is the
07:00 window's step 3 (which explicitly stages `profiles/web/cordis.patch.yml`) or a human's
one-liner, and it is the parent's call rather than a 15-minute job's.

---

## 6. The two activations, and what the window verifies about each

### 6.1 (a) the placement rows

Recorded **before** the restart and asserted **after** it, from **two** sources so neither can be
stale alone:

* the **live patch layer** on disk — the file the loader applies last (existence of the `remote-fanout`
  row and of its keys);
* the **composed tree** from `dsh --profile web --dump-config` — what the engine will actually read
  (the same three keys, inside the `remote-fanout` row's `config:` block, plus exit 0);

and two facts about the code behind them: `lib/broker-client.js` present in the **linked** package, and
`dsh-plugin-remote-fanout` named in `dsh.profile.bundles`. The required key set is
**`placement`, `brokerSsh`, `brokerUrl`** — read out of the live row, not remembered:
`placement: !!js "process.env.MESH_PLACEMENT ?? (process.env.MESH_TARGET_NODE ? 'fixed' : 'broker')"`,
`brokerSsh: !!js "process.env.MESH_BROKER_SSH ?? 'secratary-ts'"`,
`brokerUrl: !!js "process.env.MESH_BROKER_URL ?? 'http://localhost:3091'"`; `brokerTimeoutMs`,
`queueWaitMs` and `queuePollMs` are recorded as present-but-optional.

Because `--dump-config` prints raw `!!js` expressions rather than evaluating them, the window also
records which mode the package will *choose*, transcribed from `lib/index.js:64-68`, from all three
environments the launcher could have inherited (process, user, machine). Measured right now:
`MESH_PLACEMENT` and `MESH_TARGET_NODE` are empty at every scope ⇒ **`broker`**. If they were not, the
window warns loudly instead of pretending.

A bounded, warn-only probe also asks the broker behind that row whether it is up
(`ssh secratary-ts curl … http://localhost:3091/health`), because "the rows are configured" and
"placement will work" are different claims.

### 6.2 (b) `dsh-plugin-mesh-http` v0.2.0

**The measurement that decides the whole of this half.** On this node, right now:

| | deployed on disk | running engine |
|---|---|---|
| version | **0.2.0** (`lib/index.js:60`, sha256 `c9aebdb4dd1f3cb8…`) | **0.1.0** (`GET /mesh/health`) |
| `limits.oneRunAtATime` | — | **true** (the one-child ceiling) |
| `node` / `fqdn` | — | **`zabz-yoga` / `""`** |
| `identityDegraded`, `fqdnSource`, `concurrency` | — | **absent** |

and on the desktop, where v0.2.0 was measured working (8 concurrent children, 12/12 answered):

| | desktop |
|---|---|
| version | **0.2.0** |
| `node` / `fqdn` | `zabz-tech` / `zabz-tech.tail93e6e6.ts.net` |
| `identityDegraded` | **false** |
| `lib/index.js` sha256 | **`c9aebdb4dd1f3cb8…` — byte-identical to this checkout's** |

So **there is nothing to install for this half**: the junction already resolves into this checkout, the
file on disk is already the desktop's file, and the bundle name is already declared. The deploy cost is
exactly the restart (`93` §7), which is why it rides this window. The `""` fqdn is the defect `93` §8.1
describes — this engine booted 52 s before `tailscale-ipn` and cached the empty read — and it is
**unfixable without a restart**, which makes it a clean, checkable before/after difference.

The window does not take any of that on trust. Before the restart it:

1. runs the transport stream's own installer — `node packages/plugin-mesh-http/bin/install-mesh-http.mjs
   --check` (writes nothing) — and, **only if it reports drift**, applies it and re-checks;
2. reads `VERSION` and the file hash out of the **deployed** tree (through the junction) and out of
   **this checkout**, and requires them to be a junction, equal, and equal to each other;
3. runs the package's **own test suite** (`node --test test/mesh-http.test.mjs`) with a bounded wait —
   measured here: **pass 36 / fail 0, exit 0, 12.1–13.4 s** — and refuses to restart if it fails or
   does not finish;
4. corroborates against the desktop with two bounded ssh calls: its route's version must equal the
   version about to be deployed, and its `lib/index.js` hash must equal this checkout's.

If any of (1)–(4) fails, **the window stops and reports** rather than restarting into an unknown
state. One stated exception, so it can be overruled: a desktop that does **not answer** is a
**warning**, not a stop — another machine's absence is a misattributed blocker, the failure
`90-provider-mount.md` §4 was written to avoid.

After the restart, asserted **by effect**: `GET /mesh/health` must report the version this checkout
carries (**not** `0.1.0`), a **non-empty** `fqdn`, `node === fqdn.split(".")[0]` (the v0.2.0 contract
invariant, and `node` must be the real label `zabz-yoga-1`, not the `HostName` fallback),
`identityDegraded === false`, `limits.oneRunAtATime === false`, and a published `concurrency` block
with the derived limit. Every one of those fails when old code is still mounted — the fields do not
exist at all on v0.1.0 — which is what makes this a check that can fail.

### 6.3 The rest of the verification (from the 07:00 window, kept)

`GET /healthz` 200 on a **fresh** launch token (a per-process token, so a fresh fingerprint is also the
proof this is a new process); the listener's pid equals `/healthz`'s pid; **exactly one listener** on
the port owned by **exactly one engine-shaped `node` process**; the **same `DSH_HOME`**; the phone
gate's `/mesh/capacity` still 200 with a non-null engine reading; and the session corpus not shrunk
(file count and row count).

**Two things about that check are worth carrying forward.** *"One engine"* could not be asked of the
port string — a tool-call runner and its `pwsh` child both carry the literal text `--port 3099` in the
command they are running (measured: three "engines" by a naive match, one by the right one), so the
match requires node to have been handed `@deepseek-ai/dsh/lib/bin.js` **and** the port flag. And the
engine reports `identity.env.dshHome` as **`null`** on this build, so "the same home" is assembled
from three checkable things instead of one absent field: the multi-window launcher's own slot record
for the port naming the new pid, the live token being found under this `DSH_HOME`, and the session
corpus that did not move.

---

## 7. The scheduled task, and the four measured facts it honours

```
registered: DSH Mesh Restart When Idle
  state=Ready  user=ezabz  logon=Interactive  runLevel=Limited
  execute=C:\Program Files\PowerShell\7\pwsh.exe
  args=-NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\ezabz\code\harness-config\scripts\mesh-restart-when-idle.ps1"
  workdir=C:\Users\ezabz\code\harness-config
  triggerStart=2026-09-17T10:29:23-04:00  enabled=True
  repetitionInterval=PT15M  repetitionDuration=(none: repeats indefinitely)
  startWhenAvailable=True  multipleInstances=IgnoreNew  limit=PT1H
  allowStartIfOnBatteries=True  stopIfGoingOnBatteries=False
  nextRun=9/17/2026 10:29:23 AM
```

A **new** task name, no `-Force`, no `-Principal`, no `-AtLogOn`, no `RestartCount` — the four shapes
measured to fail registration for this user (`90-provider-mount.md` §5). `StartWhenAvailable` so a
sleeping laptop runs it on wake rather than missing the moment; `IgnoreNew` so a slow tick cannot
stack; battery-safe per the owner's laptop. **The task is not the gate** — it only starts the script,
and the script decides.

**Its first scheduled fire, live, 10:29:23 local:**

```
$ Get-ScheduledTaskInfo -TaskName 'DSH Mesh Restart When Idle'
  last=09/17/2026 10:29:23  result=0  next=09/17/2026 10:44:23

$ ~/.dsh/mesh/restart-when-idle/decisions.log
2026-09-17T14:29:26Z decision=LOCKED port=3099 enginePid=? loops=? running=? note=another tick (pid 32452) is in flight
```

It landed **inside** a rehearsal that held the run lock, so it did the correct thing on the correct
evidence: it did not restart anything, it did not queue, and it exited **0** with the reason written
down. The lock is what makes two ticks harmless; the pid in the message is the tick that was already
in flight. The next fire is 15 minutes later, and on that one the gate will be the thing that decides.

Registration is one command and is not hidden inside another script:

```powershell
$action   = New-ScheduledTaskAction -Execute 'C:\Program Files\PowerShell\7\pwsh.exe' `
              -Argument '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\ezabz\code\harness-config\scripts\mesh-restart-when-idle.ps1"' `
              -WorkingDirectory 'C:\Users\ezabz\code\harness-config'
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
              -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'DSH Mesh Restart When Idle' -Action $action -Trigger $trigger -Settings $settings
```

---

## 8. Idempotence: what stops a 15-minute schedule restarting the machine four times an hour

`~/.dsh/mesh/restart-when-idle/.done.json` holds `{ oldPid, newPid, engineStartedAt, verified, … }`.
Every tick, before doing anything, the window asks `/healthz` who is serving the port; if that pid is
the marker's `newPid`, the tick logs `ALREADY-DONE`, writes one line, and exits 0. A marker whose pid
is **not** the serving engine is stale (something else restarted the engine) and the window stays
armed.

**The marker is written when the restart HAPPENED, not when the verification passed**, and that is
deliberate: if the restart succeeded and the verification then failed, marking it done stops this
schedule from restarting the owner's engine again and again while someone reads the failure. `verified`
and the problem list are recorded **inside** the marker, so a failure is never hidden by the marker's
existence. A run that fails *before* the restart writes no marker, so the window stays armed for the
next idle moment — which is the behaviour that makes a 15-minute cadence useful rather than noisy.

The lock file (pid-stamped, same shape as the 07:00 window's) makes two overlapping ticks impossible.

---

## 9. Rollback

```powershell
# 1. the placement rows and the bundle names, with a .bak of everything it touches
pwsh C:\Users\ezabz\code\harness-config\scripts\mesh-provider-install.ps1 -Rollback
# 2. ONE restart puts the engine back
pwsh C:\Users\ezabz\code\harness-config\multi-window\dshw.ps1 restart
# 3. stop this window firing again
Disable-ScheduledTask -TaskName 'DSH Mesh Restart When Idle'
# 4. clear the idempotence marker ONLY if a future idle tick should be allowed another restart
Remove-Item "$env:USERPROFILE\.dsh\mesh\restart-when-idle\.done.json"
```

For the route package there are two different intentions and they are not the same:

```powershell
# take the route OFF this node (removes the junction and the bundle name; writes nothing else)
node C:\Users\ezabz\code\harness-config\packages\plugin-mesh-http\bin\install-mesh-http.mjs --remove
# or go BACK to the previous route code -- v0.1.0 is not on disk any more, because the junction makes
# this checkout the only copy, so git history is the only place it exists
git -C C:\Users\ezabz\code\harness-config checkout <commit> -- packages/plugin-mesh-http
```

If the window failed **before** its restart step there is nothing to roll back — that is what "no step
before the restart may fail" buys. Nothing in this script deletes a record.

---

## 10. What could not be verified, stated as refusals

1. **The restart itself, and both verifications after it.** They have not run: the gate is closed
   (16–17 running sessions, the owner's fleet) and the window is forbidden to force it. Everything
   before the restart is exercised live — the refusal (§3.3), the light and full passes, the placement
   evidence, the route-package evidence including its test suite and the cross-node corroboration —
   and the whole of `-ForceGate -DryRun` was rehearsed end to end without touching the engine. What is
   unproven by construction is the restart and everything after it.
2. **That `mesh-provider-install.ps1` will apply the placement rows when the window runs it.**
   **Half measured, half inferred, and the halves are now clearly separated.** Measured: `-Check`
   exits 1 with *"the live patch layer differs from the repo's"* and *"the deployed preset differs from
   the repo preset"*, writing nothing (live layer byte-identical before and after, §5). Inferred from
   the installer's own code: that the apply copies this checkout's layer and preset over the live ones.
   The apply was **not executed** — it writes to `~/.dsh` and that is outside this session's brief by
   design. So the window's install step is *known to be triggered* and *known to be the only thing
   standing between the composed configuration and a placement-less boot*; what it does when triggered
   is read, not observed.
3. **Durability of the activation across a later restart.** Not fixable inside this window, and stated
   as the warning it is: the rows are working-tree edits, HEAD does not carry them, and
   `PersonalSecretary-HarnessSync` rewrites the live layer from HEAD every 15 minutes. Committing
   `profiles/web/cordis.patch.yml` is what makes the activation survive the *next* restart. **This is
   the one thing a human should decide**, and the window names it in its own record rather than
   swallowing it.
4. **A cross-node child after the restart.** `93` measured the transport; this window verifies the
   *route's* version and identity, not that a child lands on another node. The command that closes it,
   from a session on the `zabz` preset after the restart: *"Call `subagent_remote` once with the task
   `run hostname and reply MESH-HOST: <hostname>`, then report its raw output."*
5. **`patchReload: live` and a host-plane row.** The profile sets `"patchReload": "live"`, and the
   premise of the whole window is that a **host-plane** row is read at engine **start**. What happens
   to an already-mounted host row when autosync rewrites the live patch layer *underneath a running
   engine* is **not measured here**, and it is the mechanism by which the activation could be
   disturbed after the fact. The restart is what reads the layer; what a live re-read does to a mounted
   provider row is an open question, named rather than assumed.
6. **The desktop's junction.** Its route answers `0.2.0` with a full fqdn and its `lib/index.js` is
   byte-identical to this checkout's, but its own junction target was not read (a `dir /AL` filter
   returned nothing). The comparison that matters — same code, same version — was made on content.
7. **Titles on a busy engine.** `/api/session/list` did not answer inside 40 s at 17 concurrent loops,
   while it answered in 15.8 s when the engine was quieter. So a deferral's *titles* are best-effort
   and its *ids* are certain. Stated because "we could not read the names" must never be recorded as
   "there was nothing there".

---

## 11. What the next session should know

1. **A host-plane activation has three parts, and they live in three places:** the *package* (linked
   into `profiles/<p>/node_modules`), the *rows* (`~/.dsh/profiles/<p>/cordis.patch.yml`), and the
   *running engine*. A restart only refreshes the third. Checking one and assuming the other two is how
   "installed but inert" becomes "installed, inert, and reverted by a 15-minute job".
2. **`sync.py` applies from a HEAD snapshot, so an uncommitted live-layer change is temporary by
   design.** Anything that must be in `~/.dsh` at a future boot has to be **committed** — the apply is
   deliberately not the working tree (`autosync.ps1:352-356`).
3. **The cheapest real gate is still `--dump-config`** (`90-provider-mount.md` §8.1), and it prints raw
   `!!js` expressions: presence is checkable there, evaluation is not.
4. **`/api/session/list` is the expensive call in this system's own gate path** — 1.38 MB and 15.8 s
   quiet, no answer in 40 s busy, on an engine with ~640 session rows. Any script that runs on a timer
   should decide from `/healthz` and pay for that only when it owes an explanation.
5. **`"$Port?"`, `"$Port:"` and `"$x?"` do not do what they look like** in PowerShell: `?` and `:` are
   legal in a variable name, so the name is swallowed and the value silently becomes empty. `${Port}?`
   and `` $when`: `` are the forms that work. Both bit this script during its own build.
6. **An empty result from an RPC is a refusal.** The first version of this window printed *"no session
   row carries running=true"* when `session/list` had in fact timed out. The fix is not a longer
   timeout; it is to say which reading failed and to keep the reading that did not.
