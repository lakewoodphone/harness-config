# ZABZ-YOGA — the DSH shortcut, the stack trace, and four supervisors with one port

**Date:** 2026-09-30, 19:05–19:24 America/New_York
**Machine:** ZABZ-YOGA (the laptop)
**Surface:** the owner double-clicked the Desktop shortcut `C:\Users\ezabz\OneDrive\Desktop\DSH.lnk`
and was shown a raw Node stack trace ending in `EADDRINUSE: address already in use 127.0.0.1:3099`.
**His words:** *"this is never supposed to happen."*
**Diagnosed and fixed by:** ZABZ-TECH session, over SSH (`zabz-yoga-1`), same evening.

---

## 1. What he saw, and what was actually true

He saw six error dialogs' worth of stack trace between 19:08:31 and 19:13:21. Each was the same
shape:

```
Error: dsh: plugin tree failed to load: ... loader entries failed to apply
  [cause]: Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@deepseek-ai/dsh-agent-preset'
           imported from C:\Users\ezabz\.dsh\profiles\web\
```

and later the same boot throwing

```
Error: failed to apply loader entry webserver (@deepseek-ai/dsh-host-webserver):
       listen EADDRINUSE: address already in use 127.0.0.1:3099
```

The engine was not broken. It was **being started twice, by two different supervisors, at once** —
while a *separate* configuration fault (section 3) made each attempt look like a broken install.

---

## 2. Timeline, from the machine's own logs

| time | event | source |
|---|---|---|
| earlier | YOGA engine running from the npx cache | `state.json` `startedAt` |
| ~18:58 | owner runs `npx @deepseek-ai/dsh web` in a console; npx **re-resolves** the floating `@deepseek-ai/dsh` and installs **0.2.0-rc.2** into the same npx cache directory YOGA boots from | PSReadLine history (`npx @deepseek-ai/dsh web`), cache `package.json` dep `^0.2.0-rc.2` |
| 19:08:31 | boot fails, `ERR_MODULE_NOT_FOUND` | `engine-recovery.log`, `logs/3099-20260930-190716.err.log` (13,940 B) |
| 19:10:02, 19:11:56, 19:13:21 | four more failed boots, two of them `EADDRINUSE` — the race | `logs/3099-20260930-190842/191040/191202.err.log` (13,940 B each) |
| 19:13:27 | a boot finally binds and answers | `engine-recovery.log` |
| 19:13:49 | harness sync rewrites the live web patch; the live engine keeps running on its old composition | file mtime of `profiles/web/cordis.patch.yml` |
| 19:16:45 | first **v4** session log written on YOGA | `sessions/--C-Users-ezabz-code--/session.v4.jsonl.zstd` |
| 19:21:46 | (my deliberate restart, to test the race fix) engine comes up and stays up | `engine-recovery.log` |
| 19:23 | broken package junction found and repaired | section 4 |

**Boot failures: 6. Sessions lost: none found. Engine version changed silently: yes.**

---

## 3. Root cause 1 — the engine version was floating, and the config was pinned to a different one

Three separate pins exist, and none of them was the one that mattered:

| pin | says | truth |
|---|---|---|
| `dsh-update/state/pin.json` | `0.1.5-rc.1` | ZABZ-TECH really runs 0.1.5-rc.1; **ZABZ-YOGA was running 0.2.0-rc.2** |
| npx cache `package.json` | `"@deepseek-ai/dsh": "^0.1.5-rc.1"` then `"^0.2.0-rc.2"` | a caret range is not a pin: `0.2.0-rc.2» satisfies `^0.1.5-rc.1`? No — it does not. npx **re-resolved and installed a new tree** into the same directory. |
| `windows.json` | no `dshInstall` on YOGA | the launcher fell back to a hardcoded npx-cache path and then to "scan the npx cache for any `@deepseek-ai/dsh`" |

`dshw.ps1:Resolve-DshBin` resolves the engine in this order: `$env:DSH_BIN`, `windows.json dshBin`,
`$env:DSH_INSTALL`, `windows.json dshInstall`, then a **hardcoded** npx-cache path, then a **scan of
every npx cache directory**. On YOGA there was no configured value, so the engine that boots is
whatever happens to be newest in the npx cache. A command the owner typed changed that out from
under the launcher.

And the new version line renamed packages. Measured, via `createRequire` from
`C:\Users\ezabz\.dsh\profiles\web`, on the **installed 0.2.0-rc.2**:

```
FAILS     @deepseek-ai/dsh-agent-preset            (MODULE_NOT_FOUND)
FAILS     @deepseek-ai/dsh-agent-preset-registry   (MODULE_NOT_FOUND)
FAILS     @deepseek-ai/dsh-agent-presets           (MODULE_NOT_FOUND)
FAILS     @deepseek-ai/dsh-workflow-worker-thread  (MODULE_NOT_FOUND)
FAILS     @deepseek-ai/dsh-workflow-ptc            (MODULE_NOT_FOUND)
RESOLVES  @deepseek-ai/dsh-persona
RESOLVES  @deepseek-ai/dsh-agent-instructions
```

while the live profile patch names exactly the three packages that fail:

```
name: "@deepseek-ai/dsh-agent-preset"            x3
name: "@deepseek-ai/dsh-workflow-worker-thread"  x3
name: "@deepseek-ai/dsh-agent-instructions"      x3   (this one resolves)
```

This was not a surprise. `dsh-update/FINDINGS.md` records it in advance: on 0.1.7
`dsh-agent-presets` was removed and replaced by `dsh-agent-preset` + `dsh-agent-preset-registry`,
`dsh-workflow-worker-thread` was removed and replaced by `dsh-workflow-ptc`, and — the sharpest
line in that file — **`dsh-session-format-v3-to-v4` is new, and there is no v4→v3 codec**, which
makes promotion a one-way door for the 1,095 v3 session logs. `dsh-update/tools/switch-engine.ps1`
exists to walk that door deliberately, with gates. **Nobody ran it** — and the engine walked through
the door anyway, via `npx`.

Confirmed on disk after the fact: `sessions/--C-Users-ezabz-code--/session.v4.jsonl.zstd`, written
19:16 — a v4 log, on a machine the pin file says is 0.1.5.

---

## 4. Root cause 2 — four supervisors, one port, no mutual exclusion

The launcher's own header says `ensure` is "ONE place that answers *is there an engine, and if not,
start one*, so the launcher, `new`, `restore` and the watchdog cannot drift."

They did not drift in *logic*. They raced in *time*. On YOGA the callers are:

```
DSH Engine Watchdog (1m)        dshw.ps1 ensure     every 60 s
DSH Engine Vitals (5m)          dshw.ps1 health     every 300 s   (also starts engines)
DSH Window Fleet Watchdog       dshw.ps1 health     every 300 s
Desktop DSH.lnk                 dshw-launch.cmd → ensure, then restore
```

Each one independently: probes the port, finds it dead, decides to start an engine, and waits up to
40 s. The loser of that race dies on the bind and reports `EADDRINUSE`. Nobody's fault, and nobody
could see it, because each process had a correct view of a world that changed underneath it.

**This is the exact fault the code already documents as a past incident.** `Ensure-Engine` carries a
comment dated 2026-09-14: *"the health supervisor had already restarted 3099 as pid 32044 while the
watchdog tried to start another"*. It was patched then by making the **loser smarter** — re-read the
listen table, reclaim the real holder, retry. A smarter loser does not fix a race; it narrows the
window.

**Fixed** in `multi-window/dshw.ps1` (commit `709e174`, deployed to YOGA as `ded4edb`): a
machine-wide named mutex `Global\dsh-engine-ensure` held across decide-and-start, with
re-probe-under-the-lock, an abandoned-mutex catch (so a killed supervisor hands ownership on rather
than wedging the fleet), and the boot loop moved into a new `Invoke-EngineBoot` so the lock survives
its returns. A supervisor that arrives second now **waits and reports the winner's result**.

Acceptance, run on YOGA with the engine deliberately stopped:

```
=== RACE: three ensure calls, same instant, engine down ===
--- ensure #1 exit=0 ---   ensure: engine on 3099 is not answering (attempt 1/3) - starting it
--- ensure #2 exit=0 ---   ensure: engine on 3099 is not answering the fast probe - checking patiently
--- ensure #3 exit=0 ---   ensure: engine on 3099 is not answering the fast probe - checking patiently
=== did ANY supervisor emit a stack trace? ===
NO STDERR FROM ANY SUPERVISOR
crash-sized stderr logs before: 4
crash-sized stderr logs after:  4     (delta 0)
```

Before the fix that same scenario produced a 13,940-byte stack trace per caller.

---

## 5. Root cause 3 — a broken reparse point under the profile, which the boot depends on

During the repair I found one of the eleven package junctions in
`~/.dsh/profiles/web/node_modules` to be **broken in the nastiest possible way**: the link existed,
its target existed (31 files, valid `package.json`), it reported `LinkType=Junction` with the right
`Target` — and it resolved to **nothing**.

```
entries through link: 0
package.json through link: False
node realpathSync.native → UNKNOWN: unknown error, realpath '...node_modules\dsh-plugin-mesh-http'
```

The other ten were healthy. A boot that walks this tree dies with
`Error: UNKNOWN: unknown error, realpath '...dsh-plugin-mesh-http'` — which is what killed the engine
on my first restart attempt, and is a *different* error from the version fault, which is why the
diagnosis took as long as it did. Repaired with `rmdir <link>` + `mklink /J <link> <target>` (the
junction only; the target directory was never touched), verified by enumerating 15 entries and by
`node realpath`, then verified end-to-end by composing a fresh engine on port 3199 — it bound and
answered.

**What created it is still open.** No script was found that rewrites these links. The 15-minute sync
ran at 19:17 and at 19:32 without repeating it. Until it is explained, a broken link must be
*detected and repaired*, not merely understood.

---

## 6. Why the existing prevention did not fire

This is the part worth keeping. Every safety system we had was real, and every one of them was
placed at a point the failure did not pass through.

| guard that existed | why it did not help |
|---|---|
| `dsh-update/state/pin.json` = 0.1.5-rc.1 | Nothing **reads** it at boot. The launcher resolves its bin from the npx cache. A pin nothing consults is a record, not a control. |
| `check-version-coupled-config.py` + the sync guard | The guard deliberately **SKIPS** the coupled config when it cannot run — correct, and it protected TECH. It cannot protect a machine whose engine has *already changed*, because the config and the engine are then both wrong together. |
| `switch-engine.ps1` (promote/rollback with gates) | Requires a human or an agent to choose `promote`. `npx` chose instead. |
| `Ensure-Engine`'s reclaim/retry path | Written for this exact race on 2026-09-14, and made the loser smarter instead of making the operation atomic. |
| `dshw doctor`, `dshw status`, `health` every 5 min | All report on **engines and windows**. None reports the engine's *version*, the *install root it came from*, or whether the **package names the profile references actually resolve**. |
| `my_health`-class checks (gateway, budgets, circuit breakers) | Watch the company, not the harness's own composition. |
| The 5-minute health log | Recorded `unhealthy`/`CRASH ON BOOT` faithfully, six times — after the fact. Reactive, per-boot, invisible to the owner. |
| The `ensure` callers themselves | Each correct in isolation. Nothing serialised them. |

Two structural habits made this possible and will make the next one possible, whatever the specifics:

1. **The engine's version is not a fact anywhere.** No machine records "I am running dsh X from path
   Y". When the version changed, every gate and every log stayed silent, because none of them was
   asking.
2. **Failure reached the owner as raw stderr.** `dshw-launch.cmd` spawns the engine with inherited
   stdio, so when a boot crashes the child's unfiltered 14 KB stack trace lands in the window he
   just opened. Our own recovery code already computes an excellent one-line explanation — *"this is
   a CRASH ON BOOT, not a dead port: retrying produces the same exit"* — and writes it to
   `engine-recovery.log`, where he will never look. The diagnosis existed; only the *surface* was
   wrong.

---

## 7. Prevention — layered plan

Ordered by leverage against the failure classes actually measured. Each item names the check that
proves it.

### Tier A — make the two facts that were unknown, known

**A1. Pin the engine, by path, and prove it.**
Install the chosen version to a frozen prefix (`~/.dsh/engine`, i.e. *not* the npx cache) and set
`dshInstall` in `windows.json` on every machine. `Resolve-DshBin` already honours `dshInstall`
first, so this needs no new code.
*Proof:* `dshw status` prints the version and install root; a re-run of `npx @deepseek-ai/dsh web`
must no longer change what boots.

**A2. Stamp the version on every boot, and every crash.**
Extend `health`/`status` and the crash handler to print and log
`engine 0.2.0-rc.2 from C:\Users\ezabz\.dsh\engine` plus the count of resolvable `@deepseek-ai`
packages.
*Proof:* a version change appears in the 5-minute health log the first time it happens, with no
restart involved.

**A3. Doctor check: do the names in the config resolve against the running engine?**
Walk every `name:` in `profiles/*/cordis.patch.yml` and `presets/*/agent.cordis.yml`, resolve each
from the profile root, and report the missing ones by name with the exact
`dsh plugin --profile web install` remedy. This is the 30-line check that would have turned a 35,000
byte stack trace into "3 names are missing; the engine line changed".
*Proof:* run it on YOGA today — it must name `dsh-agent-preset` and `dsh-workflow-worker-thread`,
and it must be clean on TECH.

### Tier B — stop bad states from being entered

**B1. One engine version, one config, checked before boot, not after.**
Move the version-coupled check to boot time (`ensure`, before `Start-OneSlotEngine`): if the config
names packages the resolved engine does not ship, **refuse to start and say so in one line**.
A boot that fails fast and legibly beats a boot that fails six times and illegibly.

**B2. Never float.**
Ban `npx @deepseek-ai/dsh` (any bare form) in docs, shortcuts and scripts; it must always name an
exact version. Add a grep gate over the repo for `@deepseek-ai/dsh"` / `@deepseek-ai/dsh web` with no
`@<version>`.
*Proof:* the gate fails on the PSReadLine history line that caused this.

**B3. Repair reparse points instead of dying on them.**
Before a boot, verify every junction under the profile resolves (enumerate + `realpath`);
auto-repair a broken one from the referenced package and log one line. A broken link must never
again reach the engine as `UNKNOWN: unknown error`.

**B4. The owner-facing surface.**
`dshw-launch.cmd` must capture the engine's stderr to a log and, on failure, print **one line** —
the launcher's own headline — plus "full details: <path>". Raw stack traces are for us, not for him.
**Acceptance: no path through the shortcut can put a Node stack trace on his screen.**

### Tier C — make the class impossible, then mechanise the check

**C1. Single-flight boot.** *(done — the mutex, with the race acceptance test above)*

**C2. Fleet consistency gate, in the 5-minute health pass.**
Compare the running engine version on each machine against `pin.json` and against each other; report
drift as a first-class unhealthy state, not a log line.

**C3. One-way-door register.**
An explicit list of things that cannot be undone — session format v3→v4 today — each with the check
that must pass before the door closes. The YOGA walked through this one by accident.

**C4. A test that runs the race.**
The remaining tests in `dsh-update/tests/` cover version transitions and preset rows, not "four
supervisors, engine down". The acceptance run in section 4 (three concurrent `ensure`, engine
stopped, assert zero stack traces and zero new crash logs) becomes a fixture.

---

## 8. What is still open

1. **Engine line, decided deliberately.** YOGA is on 0.2.0-rc.2 with a v4 session log already
   written; TECH is on 0.1.5-rc.1. `pin.json` says 0.1.5-rc.1. One of the three is going to lose.
2. **The three unresolvable preset rows** on YOGA (`dsh-agent-preset` ×3,
   `dsh-workflow-worker-thread` ×3). The engine boots and the owner can work, but those compositions
   are dead the moment anything dispatches them.
3. **What broke the junction**, and whether any other machine has one.
4. **One transient `The property 'Keys' cannot be found on this object`** in the 19:12 health
   transcript. Not reproducible: `Sync-WindowRegistry`, `Invoke-WindowRecovery`, `Get-WindowRegistry`,
   `Get-WindowOriginPorts` and `Get-OriginLiveLegs` all run clean on YOGA. It cost most of the
   diagnosis and it must be made to name its line.
5. **`Test-OriginsProxy` false negative**: the proxy answers `/__dshw/stats` with 200 while the
   launcher reports it dead, then starts three replacements that each exit with "another proxy
   already answers on :3200". Benign for boot, noisy for diagnosis, and it is a restart storm in
   `origins-start-errors.log`.

---

## 9. Evidence index

- `C:\Users\ezabz\.dsh\multi-window\engine-recovery.log` — six `CRASH ON BOOT` rows, 19:08:31–19:13:21
- `C:\Users\ezabz\.dsh\multi-window\logs\3099-20260930-190716.err.log` — 13,940 B, `ERR_MODULE_NOT_FOUND`
- `C:\Users\ezabz\.dsh\multi-window\logs\3099-20260930-191202.err.log` — 13,940 B, `EADDRINUSE`
- `C:\Users\ezabz\.dsh\multi-window\logs\3099-20260930-191327.err.log` — 1,108 B, benign MCP shutdown
- `C:\Users\ezabz\.dsh\multi-window\logs\health-20260930.log` — the boot failures and the `Keys` transcript
- `C:\Users\ezabz\.dsh\multi-window\origins-start-errors.log` — the proxy restart storm
- `C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml` — lines 300–301, 484–485, 979–980
- `harness-config\dsh-update\FINDINGS.md` — the rename table and the one-way-door warning, written
  in advance
- `harness-config\multi-window\dshw.ps1` — `Ensure-Engine` (mutex), `Invoke-EngineBoot`,
  `Resolve-DshBin`
