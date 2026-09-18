# 90 — Mounting the remote subagent provider in the resident engine

**Program:** `docs/mesh/` (the provider seam of `66-dsh-remote-capability.md` §3.4, the deliverable
`71-mesh-program.md` §5 deferred to "the first thing to land when a restart window opens").
**Date:** 2026-09-17 (written between 04:20Z and 05:10Z). **Author:** a delegated build session, not
the owner.
**What was NOT done:** no engine was restarted on any node. Every engine on both Windows nodes was
running before this session and was still running after it. No `git push` was made from this session
(everything it changed is local, deliberately: a local commit would diverge this tree from
`origin/master` and `git pull --ff-only` — the window's own step 3 — would then refuse).

---

## 1. What was built, file by file

| file | what it is |
|---|---|
| `profiles/web/cordis.patch.yml` | the deployment config: the `remote-fanout` provider row (target, ssh client, the target's node + dsh paths, the location check) and `tool-subagent-remote: disabled`. This is the layer the loader applies after every bundle layer. |
| `scripts/make_zabz_preset.py` | emits the `tool-subagent-remote` row into the `zabz` preset's delegation group, with a checked anchor (it exits 2 rather than generating a preset that silently lacks the tool). |
| `presets/zabz/agent.cordis.yml` | generated; `--check` green. |
| `scripts/mesh-provider-install.ps1` | **new.** Installs and verifies the above: profile hygiene, the boot invariant, the patch layer, the v2 secret, the preset, and the `--dump-config` pre-flight. `-Check` writes nothing, `-Rollback` takes it back out. |
| `scripts/mesh-restart-at-0700.ps1` | **new.** The window itself: gate → snapshot → journal converge + pull → install re-verify → ONE restart by the supported path → verify (including the provider assertion) → rollback instructions. |
| `scripts/install-client-plugins.ps1` | **edited** (see §3): only enrol a package whose manifest declares `dsh.bundle.patch`, and drop a declared name that does not. |
| `scripts/harness-verify.ps1` | **edited** (see §3): check 11 now reads EVERY declared name and requires it to declare a bundle. |
| `docs/mesh/90-provider-mount.md` | this file. |
| `~/.dsh/mesh/restart-0700/<stamp>/` | the window's own records: `run.log`, `gate-refused.json`, `pre-restart.json`, `post-restart.json`. |

**Measured tonight, in one place.**

| claim | command | result |
|---|---|---|
| the preset generates and is in sync | `python scripts/make_zabz_preset.py --check` | `zabz: in sync with the generator`, exit 0 |
| every mounted bundle resolves and declares a bundle | `pwsh scripts/install-client-plugins.ps1 -Check` | `every mounted bundle resolves`, exit 0 |
| the install's own invariants hold | `pwsh scripts/mesh-provider-install.ps1 -Check` | `every invariant holds`, exit 0 |
| the profile composes | `node …/dsh/lib/bin.js --profile web --dump-config` | exit 0, 620 lines, rows `remote-fanout`, `tool-subagent-remote (disabled)`, `plugin-mesh-http` present |
| **the provider actually registers, and a session sees the tool** | `_scratch/mesh-0700/scratch-boot.ps1 -CreateSession -AskTools` | an isolated-home engine on :3098, a session on the `zabz` preset answered `subagent subagent_fork subagent_remote` |
| the gate REFUSES while the owner works | `pwsh scripts/mesh-restart-at-0700.ps1` | `DEFERRED -- 9 running session(s), 9 agent loop(s)`, exit 0, ids and titles logged |
| the task is registered | `Get-ScheduledTask -TaskName 'DSH Mesh 0700 Restart'` | `Ready`, next run `09/17/2026 07:00:00` |

---

## 2. How the provider is expressed, and why that is the supported way

**The short version: a host-plane provider row plus a preset-plane tool row, and the deployment
config in the profile's own patch layer.**

```
@deepseek-ai/dsh-base            … provides ctx.subagents (the named-provider registry)
dsh-plugin-remote-fanout         the bundle. Its patch inserts two rows:
  remote-fanout                    HOST plane  → registerProvider('remote-ssh') on ctx.subagents
  tool-subagent-remote             HOST plane  → a second dsh-tool-subagent instance
profiles/web/cordis.patch.yml    the layer we own:
  { id: remote-fanout, config: … }  the deployment facts the package may not carry
  { id: tool-subagent-remote, disabled: true }  the tool is granted per agent, by the preset
presets/zabz/agent.cordis.yml    the TOOL, inside the existing `delegation` group:
  - id: tool-subagent-remote  provider: remote-ssh  toolName: subagent_remote
```

**Why the provider cannot be a preset row.** `ctx.subagents` is one process-wide registry and
`registerProvider` throws on a second registration of the same name —
`dsh-subagent/lib/index.js:3106-3116`, `DUPLICATE_PROVIDER`. A preset is mounted once per session, so
a provider row inside one works for the first session and breaks every session after it. Wrapping it
in an `isolate: {subagents: true}` realm does not help: the realm would have no `subagents` provider
in it, and the row's `inject: ['subagents']` would wait forever for a service only the root provides.
The preset's own delegation block already states this rule, and `dsh-subagent`'s README states the
general one: the registry and its backends are host-side, the preset contributes the delegation
tools.

**Why a preset row for the tool at all, rather than letting the bundle's own host-plane tool row
stand.** This is the shipped pattern for an out-of-process provider: the `codex` and
`claude-code` products are host-plane bundles whose *tool* rows live in presets, so that
availability is granted "to one Agent". Left enabled, the bundle's host-plane row would hand
`subagent_remote` to every session in the engine, including sessions on presets that never asked for
it. A later patch layer disabling a row by id is the documented shape — `packages/plugin-mesh-http`'s
own patch header says so — and the composed tree was checked: `--dump-config` prints
`- id: tool-subagent-remote … disabled: true`.

**Why the config is in `profiles/web/cordis.patch.yml` and not in the package.** `target`,
`remoteNodeExe` and `remoteDshBin` are facts about a machine and two paths on it. The package's own
patch carries no config on purpose, and a bundle mounted without one **fails the boot loudly**
(`lib/ssh-transport.js:99-101` throws before the engine is up). That is the right behaviour for a
package and the wrong thing to leave in a profile, which is why `mesh-provider-install.ps1` enforces
the invariant *bundle named ⇒ config present*, and takes the name out when it is not.

**Every value is `!!js` with a literal fallback**, in the `process.env.X ?? 'literal'` shape
`profiles/mesh/cordis.patch.yml` already uses and that the three-child proof ran on. The target is
one node (`desktop-ts`) on purpose: choosing between nodes is the broker's decision, not a row's.
`MESH_TARGET_NODE` / `MESH_TARGET_HOSTS` / `MESH_NODE_EXE` / `MESH_DSH_BIN` / `MESH_REMOTE_SHELL`
override it in the engine's environment; the location check then fails a run whose child reports a
host not in `MESH_TARGET_HOSTS`, which is the honest failure rather than a silent wrong placement.

### 2.1 The isolated-home proof, and the one thing it does not prove

`_scratch/mesh-0700/scratch-boot.ps1` boots a second engine with **its own `DSH_HOME`**
(`~/.dsh-meshcheck`) on port **3098**, carrying the same bundle list and the same patch layer. That is
the shape `70-remote-fanout-proof.md` §4.3 records ("installation shared, state isolated") and what
`harness-verify.ps1` check 7 allows: two engines on one home is what must never happen, and this is not
that. The owner's engine (pid 1784, port 3099) was verified alive before and after each run.

Result, from the run that matters:

```
[scratch] bundles   11: …, dsh-plugin-remote-fanout, dsh-plugin-mesh-http
[scratch] listening True after 20s
  "healthz": 200, "enginePid": 5900,
  "dshHomeSeenByEngine": "C:\\Users\\ezabz\\.dsh-meshcheck",
  "sessionCreateOk": true, "sessionCreateValue": {"sessionId": "session-53c4015e-…", "agentPreset": "zabz"},
  "promptOk": true,
  "assistantReply": "subagent subagent_fork subagent_remote",
  "saysSubagentRemote": true,
  "meshHealth": 200, "meshService": "mesh-http", "meshNode": "zabz-yoga-1"
[scratch] after kill: listeners on :3098 = 0
[scratch] owner engine 3099 pid 1784 alive=True
```

That is the whole composition exercised end to end short of a cross-node child: the profile composes,
the host rows apply, the provider registers, the v2 route answers, the preset's new row mounts, and a
live session's tool catalog contains `subagent_remote`.

**Left behind, deliberately:** the scratch home `~/.dsh-meshcheck` (its own `.credentials.yaml`
copy — same user, same disk, nothing new exposed — and the `zabz` preset copied into its
`.agent-presets/`, because the preset roster is per home). It is the fixture that re-runs this proof
in one command: `pwsh _scratch/mesh-0700/scratch-boot.ps1 -CreateSession -AskTools`. The helper scripts
live in `_scratch/mesh-0700/` (`bundle-audit.ps1`, `bundle-repair.ps1`, `engine-facts.ps1`,
`link-probe.ps1`, `scratch-boot.ps1`) with their raw output beside them; `harness-config` does not
track `_scratch/`, so nothing there can break a boot.

**What it does not prove:** that a `subagent_remote` call actually lands on `desktop-ts`. The ssh
transport itself is proven (`70-remote-fanout-proof.md` §2, three children on another node, each
reporting its own hostname), and the paths in the config are the ones `mesh-dispatch.mjs`'s measured
node table carries — but no child turn was dispatched from a *resident engine* here, and the after-restart
acceptance step below is the command that closes it.

---

## 3. THE DEFECT THIS WINDOW FOUND FIRST: both Windows nodes could not boot

Before anything about the provider, the gate that matters is "will the engine come back at all?".
Measured read-only, with the engine still running and untouched:

```
$ node …/dsh/lib/bin.js --profile web --dump-config
Error: dsh: profile bundle "dsh-mesh-broker" declares no dsh.bundle in its package.json
  at dsh-app-boot/lib/index.js:852
EXIT=1
```

`~/.dsh/profiles/web/package.json` named **`dsh-mesh-broker`** — a service with a `bin`
(`bin/mesh-broker.mjs`), whose `package.json` has no `dsh` key at all. The loader mounts every name in
`dsh.profile.bundles` as a patch layer and throws on one that declares no bundle, so the profile could
not compose and **the next engine start on ZABZ-YOGA would have failed**, leaving the machine down.
The engine running at the time was unaffected — it read its profile at 15:49 — which is exactly what
made it invisible.

The laptop was not alone. `scripts/bundle-audit.ps1` / `bundle-repair.ps1` were run on both nodes,
**read-only first, with the found state recorded before anything changed**:

| node | name found invalid | why | action |
|---|---|---|---|
| `ZABZ-YOGA` | `dsh-mesh-broker` | resolves, declares no `dsh.bundle` | name removed (backup `package.json.bak-20260917-003313`) |
| `ZABZ-TECH` | `dsh-plugin-session-link` | a junction whose TARGET is fine, but reading through it fails: `cmd /c type` answers *"The path cannot be traversed because it contains an untrusted mount point"* — the untrusted-reparse-point class of `70-remote-fanout-proof.md` §4.4 | name removed (backup `package.json.bak-20260917-003227`) |

Both then composed: `dump-config exit=0` on each. On the desktop the repair deliberately **did not**
recreate the junction: whether a link made from an ssh session is trusted by that machine's own *local*
engine start was not established by §4.4 — the document says so itself — and a wrong bet there is an
engine that cannot come back on a machine with no console. Restoring `dsh-plugin-session-link` (a
session-deep-link UI nicety) is a local one-liner, recorded in §6.

**The systemic cause, and the two checks that missed it.** `scripts/install-client-plugins.ps1` used
to enrol *every* package it could link, so the moment `packages/mesh-broker` existed the next
`sync.py` armed it — which is how it got here (the relink ordered for the desktop's broken junctions
was run with `-RequireAll` on this laptop during the fork work: the relink fixed one failure and armed
a worse one). `harness-verify.ps1`'s check 11 was green because it filtered `-like 'dsh-plugin-*'`,
and `dsh-mesh-broker` does not match that pattern — the fourth "check that cannot fail" of the night.
Both are fixed:

* `install-client-plugins.ps1` requires `dsh.bundle.patch` for enrolment and DROPS a declared name that
  fails the test. Proven after the fix: with `-RequireAll`, `dsh-mesh-broker` is reported as
  `declares no dsh.bundle -- linked, never named as a bundle`, and the bundle list keeps 11 names.
* `harness-verify.ps1` check 11 now reads every declared name. **Its failure mode was demonstrated
  before the repair** — on the pre-repair profile it printed
  `[FAIL] declared plugin bundles resolve … no dsh.bundle=[dsh-mesh-broker]` and exited 1 — and it
  passes after. A check whose failure has never been seen is a check nobody can trust.

---

## 4. The window script, step by step

`scripts/mesh-restart-at-0700.ps1`. Order is the contract; every step logs its numbers to
`~/.dsh/mesh/restart-0700/<stamp>/run.log`.

1. **GATE — from evidence, not a clock.** The engine's own `/healthz`, authenticated with a cookie
   minted from the launch token in its launcher log (the only supported way: the token is per process
   and never persisted, `66-dsh-remote-capability.md` §2c), plus `/api/session/list` for ids and
   titles, plus the phone gate's `/mesh/capacity` on loopback as an independent second reading.
   **Any `running` session, or a non-zero `agentLoopsRunning`, refuses and writes nothing.** The
   waze/mdm hunt is explicit and reported whether or not it finds anything.
2. **SNAPSHOT** — pid, uptime, `DSH_HOME`, every session's id/title/preset/running, the session-file
   count on disk, session rows in the list, established connections on both ports, listener count.
3. **JOURNAL CONVERGE + PULL** — the blocking set is computed, not assumed: for every untracked file
   under `journal/entries/**`, `git cat-file -e origin/master:<path>` decides whether the incoming
   tree contains that path. Each blocking entry is re-filed with
   `journal.py append <kind> --title T --body-file F --json` (the marker line and the generated
   heading are stripped so the body is content, not front matter), the from→to id is recorded, and
   **the original is removed only after its append succeeded** and only while it is still untracked.
   Tracked files that the fast-forward would overwrite are classified: generated caches
   (`journal/index/**`, `journal/state/**`) are restored from HEAD; `docs/mesh/87-harness-fork.md` is
   only discarded after checking that every heading of ours exists in the authority's copy; **any
   other file is left alone and the restart is refused**, because another stream's live edit is not
   this script's to throw away. Then `git pull --ff-only` must succeed. Then one commit and push.
4. **INSTALL RE-VERIFY** — `mesh-provider-install.ps1 -Check` (applying once if it reports drift) plus
   `--dump-config` exit 0. **If any step before the restart fails, nothing restarts.**
   Two deliberate exceptions to "any step fails ⇒ no restart", both about *other machines* rather than
   this tree, and both flagged here so they can be overruled: an unreachable **fetch** is a warning
   when `origin/master` already resolves locally (measured 00:46Z: `ssh: connect to host
   secratary.tail93e6e6.ts.net port 22: Connection timed out` while the local ref was already the
   merged commit — that is a misattributed blocker of the kind this system keeps punishing), and a
   **pull** that fails because the remote is unreachable is a warning too, while a pull that is
   *refused* stays fatal. The tree keeps its local state either way.
5. **RESTART** — `pwsh multi-window/dshw.ps1 restart`: the machine's own supported path, which stops
   the server tree and starts it again through Task Scheduler with the same port, profile and
   `DSH_HOME`, and which owns the "one engine per home" rule. Never a hand-rolled `Start-Process`
   (a child of this shell dies with the job object — `dshw.ps1:508-515`).
6. **VERIFY** — a new listener owned by a new pid; `/healthz` 200 with a *fresh* cookie (a fresh token
   is also the proof this is a new process); the same `DSH_HOME`; session files and session rows
   unchanged; the phone gate's `/mesh/capacity` 200; the engine's own `/mesh/health` 200 (the v2 route
   mounted, and therefore that the restart really did mount new host rows); and the provider
   assertion below.

### 4.1 How the provider is ASSERTED, and what could not be asserted

There is **no remote surface that lists registered subagent providers or registered tools** — checked,
not assumed: the `subagents` namespace exposes `list` (which is `remoteExportList(parentSessionId)`,
a per-parent catalog), `prompt` and `interruptByParent`; the tools registry is not remote at all; and
there is no `/api/tools/*`.

**And the engine's own log line cannot be used**, which invalidates the obvious plan. The provider
does log (`remote-fanout: provider "remote-ssh" registered → …`), but in the `web` profile host-plane
plugin log lines are written **nowhere durable**: the scratch engine's entire stdout+stderr over a
15-minute life was ~204 bytes holding the launch line and two v2 health lines, and the owner engine's
32 KB `.err.log` contains only MCP child output. Measured tonight, in both engines.

So the assertion is **by effect, in the only reader that has the answer**: the script creates one
session on the `zabz` preset, asks it not to call a tool but to name the tools it has that contain
`subagent`, and reads the reply from the session-list projection. In the isolated-home rehearsal that
answer was `subagent subagent_fork subagent_remote`. In the window the script records
`ASSERTED: a live session on the zabz preset names subagent_remote among its tools`, or
`NOT ASSERTED` with the reason — and it never claims the second as the first.

`-ProbeProvider:$false` skips it (it costs one small prompt on the owner's engine and leaves one
session behind, titled by the question).

### 4.2 What the refusal branch actually does (raw, tonight, 2026-09-17 00:42 local)

The owner's fleet was live while this ran, so this is a live test of the gate, not a rehearsal:

```
[00:42:58] STEP 1: the gate -- is any of the owner's work running?
[00:43:12] engine pid 1784, DSH_HOME=, sessions live 17
[00:43:12] agentLoopsRunning=9  (gate's own reading: 8)
[00:43:12] sessions running: census 9, /api/session/list 8
[00:43:12] waze/mdm matches: 18

[00:43:12] STEP 1 RESULT: REFUSED
[00:43:12] the owner's work is running in this engine, so the restart is DEFERRED:
[00:43:12]   - agentLoopsRunning = 9 (0 means idle)
[00:43:12]   - sessions whose public status is running: 9

sessions found running (id / origin / title):
  b534bfe8-7cf3-482c-9f91-a5552bde7240  subagent  READ-ONLY MINING TASK. There are
  f3880d68-0f15-4afe-b417-67f2b64d40d1  subagent  You are mining an AI-agent
  89e1b856-d03a-4875-a728-4b09c163f3ab  subagent  You are mining an AI-agent
  3c4aa9c0-89a7-4be9-8146-83ec794ddc35  subagent  You are mining a corpus
  c2bd04fd-2a72-4d84-a1c3-c4ebf0148f25  subagent  You are mining a corpus
  5d06e6e5-56c7-49b6-932a-a463565093ca  subagent  You own the last piece
  34b6d7a2-8cb5-4be1-894a-affaea783683  subagent  Across MONTHS of VS Code
  1ed6d1f1-b51a-4a5b-a2dd-1ae8a21fc8a5  subagent  You are doing forensic archaeology
  session-efca5060-70e2-4e9e-8679-942cabf38d34  (running in the census, no list row)

waze/mdm work found (this is what the gate exists for):
  1ed6d1f1-b51a-4a5b-a2dd-1ae8a21fc8a5  running=True  You are doing forensic archaeology
  session-0898187e-bb24-4d63-99d1-c2a331221f33  running=False  Waze MDM DRM LPT System Status
  session-431b2f31-375f-4385-8295-c2b6499dc767  running=False  Sourcing cheap eSIM iPhones for Waze fleet
  … 15 more (the run log holds all 18, with the subagent labels)

mesh-restart-at-0700: DEFERRED -- 9 running session(s), 9 agent loop(s); nothing was restarted.
EXIT=0
```

Two things worth reading twice. The ids are the *subagent* sessions of the owner's own fleet agent
(`origin=subagent`, labels like "Mine MDM host history", "Prepare the 07:00 engine restart"), which is
exactly the work the gate exists to protect. And the two independent readings disagree by one
(census 9 vs `/healthz` 9 vs list 8 vs the gate's 8) because sessions start and settle between the
two calls — which is the point of taking both, and the reason the refusal is on `> 0`, not on a
threshold.

---

## 5. The scheduled task, and the four measured facts it honours

```
$ pwsh scripts/…            # registration, run once, 2026-09-17 00:42 local
registered: DSH Mesh 0700 Restart
state=Ready  user=ezabz logon=Interactive runLevel=Limited
triggerStart=2026-09-17T07:00:00-04:00  enabled=True
execute=C:\Program Files\PowerShell\7\pwsh.exe
args=-NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\ezabz\code\harness-config\scripts\mesh-restart-at-0700.ps1"
workdir=C:\Users\ezabz\code\harness-config
restartCount=0 startWhenAvailable=True limit=PT1H
nextRun=09/17/2026 07:00:00
```

`Register-ScheduledTask -TaskName <new> -Action … -Trigger … -Settings …`: a **new** task name, no
`-Force`, no `-Principal`, no `-AtLogOn`, no `RestartCount` — the four shapes measured to fail on this
user. `StartWhenAvailable` so a sleeping laptop runs it on wake rather than missing it. The script
itself is the gate: the task's only job is to start it at 07:00.

Registration is one command and is not hidden inside another script; this is it:

```powershell
$action   = New-ScheduledTaskAction -Execute 'C:\Program Files\PowerShell\7\pwsh.exe' `
              -Argument '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\ezabz\code\harness-config\scripts\mesh-restart-at-0700.ps1"' `
              -WorkingDirectory 'C:\Users\ezabz\code\harness-config'
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date -Hour 7 -Minute 0 -Second 0)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
              -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'DSH Mesh 0700 Restart' -Action $action -Trigger $trigger -Settings $settings
```

---

## 6. Rollback

The install is inert until a restart, so rollback has two halves — the files, and the engine.

```powershell
# 1. the rows and the two bundle names, with a .bak of everything it touches
pwsh C:\Users\ezabz\code\harness-config\scripts\mesh-provider-install.ps1 -Rollback
#    prints the two junctions it leaves in place, and:
#    git -C <repo> checkout -- profiles/web/cordis.patch.yml      # the repo copy is version-controlled
# 2. the v2 route's junction and name (if it was installed too)
node C:\Users\ezabz\code\harness-config\packages\plugin-mesh-http\bin\install-mesh-http.mjs --remove
# 3. one restart puts the ENGINE back
pwsh C:\Users\ezabz\code\harness-config\multi-window\dshw.ps1 restart
```

`-Rollback` also re-runs `--dump-config` and refuses to say "done" unless the profile composes.
The v2 secret (`C:/ProgramData/dsh-mesh.env`) is outside the repo and unused once the route is gone;
delete it only if that is meant. If the window itself failed *before* the restart, there is nothing to
roll back — that is what "nothing restarts unless every step passed" buys.

**Restoring `dsh-plugin-session-link` on ZABZ-TECH** (withdrawn by the repair in §3, not part of the
install): run this **at that machine's console**, not over ssh, and then prove it locally:

```powershell
Remove-Item C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-plugin-session-link -Force -Recurse
New-Item -ItemType Junction -Path C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-plugin-session-link `
  -Target C:\Users\ezabz\code\harness-config\packages\plugin-session-link
# add the name back to dsh.profile.bundles, then:
node C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js --profile web --dump-config
# exit 0 = the machine will boot. The ssh-only check cannot see this failure class: that is why it
# must be verified where the engine starts.
```

---

## 7. What could not be verified, stated as refusals

* **The restart itself.** It must not happen until 07:00 and the gate says the owner is done. Every
  part of it is rehearsed except the one irreducibly dangerous action: the gate refused live, the
  snapshot is written, the composition is proven, and an engine booted on this exact composition — in
  an isolated home. The restart on the owner's home is unproven by construction.
* **A cross-node child from a resident engine.** Proven for the `mesh` profile
  (`70-remote-fanout-proof.md` §2) and not from a resident engine in the new configuration. The
  command that closes it, after the restart, from a session on the `zabz` preset:
  *"Call `subagent_remote` once with the task `run hostname and reply MESH-HOST: <hostname>`, then
  report its raw output."* The child's own `MESH-HOST: zabz-tech` line is the proof; the dispatcher's
  location check fails the run if it disagrees with `MESH_TARGET_HOSTS`.
* **The journal converge against the real tree.** It is written and its blocking-set computation was
  verified against the live tree (`origin/master` has `pain/P229`, `pain/P230`, `handoff/H433`; it has
  no `lessons/L1856` or `L1857`), but it has not been executed, because executing it requires the
  owner's writer to be idle — which is the same condition as the restart. `-DryRun` prints the plan.
* **`mesh-http.mjs probe` from another machine after the restart.** It reports
  `ACCEPTS v2` per node; run it from ZABZ-TECH after the window, not from here.
* **The v2 route on a node other than this one.** Unchanged by this work; `83-http-transport.md` §6-7
  is the record.
* **The flatness criterion.** `71-mesh-program.md` §4's "±1 GiB absolute" is **retired**: the
  acceptance stream measured an *idle* laptop moving 0.416–1.203 GiB per 30–176 s, so the bar was
  inside the machine's own noise and produced criterion failures rather than defects. The criterion is
  now RELATIVE — the fleet's delta must not exceed a same-length control window's delta measured
  beside it — and any absolute-flatness claim in an older record is stale.
* **The auth path's dependence on a log file.** The cookie comes from the launcher's log; a launcher
  that stops writing the token line would close the gate (the script then says `no evidence` and
  defers, which is the correct failure but is a hard dependency worth naming).

---

## 8. What the next session should know

1. **`--dump-config` is the cheapest real gate in this harness.** It composes the profile's bundle
   layers, starts nothing, evaluates no `!!js`, and is therefore safe on a machine that is in use. A
   live engine says nothing about whether the next one will come up.
2. **Host-plane plugin log lines are not durable in the `web` profile.** `ctx.logger.info` from a
   `dsh-plugin-*` host row goes nowhere you can read later. Assert by effect, or by an RPC surface
   that exists — and check that the surface exists before writing the assertion into a script.
3. **Two engines on one `DSH_HOME` is the thing to avoid; a second `DSH_HOME` is the way to test a
   composition change.** A scratch home with the same bundle list and patch layer, its own
   `.credentials.yaml`, its own `.agent-presets/<name>` (the roster is per home — a preset missing
   there answers `agent-preset/not-found`), and a different port, proves more than any amount of
   reading.
4. **Node's stdout is block-buffered when it is a pipe.** `& node … *> file` leaves the engine's
   launch line invisible until the process exits; `Start-Process -RedirectStandardOutput` gives it a
   file handle and the line appears immediately. That is also why the multi-window launcher's log
   works.
5. **A row can be disabled by id from a later layer** (`{ id: X, disabled: true }`), and the composed
   tree can be checked with `--dump-config` rather than trusted. Confirmed on `tool-subagent-remote`.
6. **`journal.py append` allocates `max(everything it can see) + 1`.** It cannot see another
   machine's uncommitted files, so a fleet that appends before pulling collides — pull first, then
   append, and treat an uncommitted entry in a diverged tree as an id already spent
   (`87-harness-fork.md` §4.7).
