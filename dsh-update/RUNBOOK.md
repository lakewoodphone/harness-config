# RUNBOOK — taking this deployment from the pinned engine to a newer one

One question: **how does an operator move this deployment from the pinned engine to a newer one,
safely, step by step?**

The answer is `dsh-update/tools/switch-engine.ps1`. It exists because of 0.1.5 -> 0.1.7
**version-coupled config**: `@deepseek-ai/dsh-workflow-ptc`,
`@deepseek-ai/dsh-agent-preset-registry` and `@deepseek-ai/dsh-agent-preset` exist ONLY on the 0.1.7
line, while `@deepseek-ai/dsh-workflow-worker-thread` and `@deepseek-ai/dsh-agent-presets` exist ONLY
on the 0.1.5 line. A composition row naming a package the running engine does not provide fails at
mount, so neither half can be applied alone — the config alone breaks new sessions now, the engine
alone breaks them at the next boot (`tools/switch-engine.ps1:3-17`).

Everything below was read from the code (`tools/switch-engine.ps1`, `lib/cli.mjs`, `lib/verify.mjs`,
`tools/backup-state.mjs`) or from a file in this repo that measured it. Where something is not
established, it says so.

---

## 1. Preconditions, in the order the script checks them

The script takes **no lock and writes nothing** until all five pass
(`tools/switch-engine.ps1:1069-1251`).

**0. The candidate is already fetched.** Not a precondition of the script, but of the pipeline inside
it: precondition 5 runs the real `preflight`, whose `analyze` and `verify` refuse when
`vendor/prefix/<ver>` holds no engine (`lib/cli.mjs:591-596`, `:679-684`). So before anything else:

```
pwsh -File dsh-update\bin\dsh-update.ps1 check
pwsh -File dsh-update\bin\dsh-update.ps1 snapshot
pwsh -File dsh-update\bin\dsh-update.ps1 fetch <ver>
```

**1. A verified backup, younger than 12 hours.** `-BackupDir` must contain a `BACKUP-REPORT.json`
that parses, reports `ok:true`, carries a parseable `finishedAt`, is not more than 12 hours old and is
not more than 15 minutes in the future; a directory that cannot show its own verdict is refused
(`tools/switch-engine.ps1:1069-1097`). Take it with:

```
node dsh-update/tools/backup-state.mjs [--home <dshHome>] [--to <dir>] [--sample N]
```

It copies, then proves completeness (per-store count and byte totals) and integrity (a hash manifest
plus a random sample re-read from both sides) and exits non-zero if any of that fails; the report is
written into the destination as `BACKUP-REPORT.json` (`tools/backup-state.mjs:14-30`, `:247`, `:267`).
Default destination is `<USERPROFILE>\dsh-backup-<UTC stamp>`, deliberately outside the DSH home
(`tools/backup-state.mjs:28-29`).

**2. The staged home already carries the migrated config.** `-StagedHome` must exist, contain at least
one `.agent-presets/*/agent.cordis.yml` and at least one `profiles/*/cordis.patch.yml`, and those
files must **name the new packages as QUOTED composition rows** and must **not name the removed
ones**:

- a preset must name `@deepseek-ai/dsh-workflow-ptc`, and must not name
  `@deepseek-ai/dsh-workflow-worker-thread`;
- a profile patch must name `@deepseek-ai/dsh-agent-preset-registry`, and must not name
  `@deepseek-ai/dsh-agent-presets`.

Quoted, because an unquoted mention is prose in a comment — the check would otherwise refuse a
correct file (`tools/switch-engine.ps1:170-179`, `:1101-1137`). The switch suite proves this refusal
fires on a staged home still carrying the 0.1.5 names (`tests/switch/README-rework.md:30`).

The mechanism this precondition depends on is measured: the same `scripts/sync.py` command reports
`SKIPPED` for both coupled steps against the 0.1.5 engine root and `version check passed` against the
0.1.7-rc.2 root, on identical config (`tests/switch/README.md:72-75`,
`tests/switch/README-rework.md:15-18`). **Not established here:** a committed, step-by-step procedure
for producing the staged home. The suite uses `%TEMP%\dsh-staged-migrated`, "the prepared, migrated
copy" (`tests/switch/README.md:18`), without recording how it was prepared.

**3. A clear sync window, and the lock.** Task `PersonalSecretary-HarnessSync` runs every 15 minutes
and applies the repo's committed config through `scripts/sync.py` (`tools/switch-engine.ps1:40-49`,
`:145`). The script **refuses with exit 2 and writes nothing** — not a pre-state directory, not a lock
— when a tick is due within `-SafetyMarginSeconds` (default 180 s) (`:131`, `:479-499`, `:1156-1165`),
because a concurrent sync could see the new `dshInstall` and install version-coupled config onto a
host still running the old engine. This check comes **before** the engine and preflight checks on
purpose: reading a clock is cheap and must not be discovered late (`:1139-1144`). From here on a
switch-held lock prevents two switches from interleaving — `state/locks/switch-engine.lock.json`, a
foreign lock older than `LockStaleSeconds` (default 300 s) being treated as stale (`:500-553`, `:132`,
env override `DSH_SWITCH_ENGINE_LOCK_STALE_SECONDS` at `:148-153`).

**4. A live engine, exactly at the pin's version.** `state/pin.json` must exist and carry a version,
a live engine must be readable, and its reported version must equal the pin's exactly — "a mismatch
means the pin is not describing what is running" (`tools/switch-engine.ps1:1177-1192`).

**5. Preflight says GO — or fails on G8 alone and that is accepted.** The script runs
`node dsh-update/lib/cli.mjs preflight <ver> --json` with `DSH_HOME` set to `-StagedHome`
(`tools/switch-engine.ps1:726-731`), prints every guard, and then:

- **GO** — proceed (`:1230-1231`);
- **NO-GO whose only substantive failure is the G8 session-format door**, with no other failing
  blocking guard, no non-opt-in verify gate failed and no verify gate silently not run — proceed
  **only** with `-AcceptSessionFormatUpgrade`, which records the decision rather than skipping the
  check (`:734-766`, `:1232-1241`);
- **NO-GO for any other reason** — refuse, exit 2, nothing written (`:1249-1251`).

This step is not read-only for the pipeline: it refreshes `dsh-update/state/candidates/<ver>/*.json`
and appends a history row, and the script says so before running it (`:1196-1199`).

## 2. The command line

Apply:

```
pwsh -File dsh-update\tools\switch-engine.ps1 `
  -Version <ver> `
  -StagedHome <staged home carrying the migrated config> `
  -BackupDir  <directory containing BACKUP-REPORT.json> `
  -IUnderstandThisWritesTheLiveHome `
  [-AcceptSessionFormatUpgrade]
```

`-Version`, `-StagedHome` and `-BackupDir` are all required (`tools/switch-engine.ps1:1056-1058`).
`-AcceptSessionFormatUpgrade` is required only when precondition 5 comes out NO-GO on G8 alone
(`:1238-1241`).

Rollback:

```
pwsh -File dsh-update\tools\switch-engine.ps1 -Rollback -IUnderstandThisWritesTheLiveHome
```

**Exit codes** (`tools/switch-engine.ps1:75-82`) — these are the switch's own, not the pipeline's:

| code | meaning |
|---|---|
| `0` | the switch is applied (or `-DryRun` / `-Rollback` completed) |
| `1` | an unexpected internal error |
| `2` | a precondition refused, or the live-write gate was not unlocked — NOTHING was written, not even the pre-state directory or a lock file |
| `3` | `-Rollback` could not proceed (no pre-state), or a restore failed to verify |
| `4` | a step failed and the automatic roll-back RESTORED the previous state, verified by sha256 |
| `5` | a step failed AND the automatic roll-back could not fully restore — attention required |

## 3. Dress rehearsal vs `-DryRun` — two different promises

- **Dress rehearsal** = a full run **without** `-IUnderstandThisWritesTheLiveHome`. Every precondition
  runs, the plan is printed, and then the gate refuses with exit `2` and writes no pre-state
  directory, no lock, no pin, no launcher config and no live config file
  (`tools/switch-engine.ps1:51-55`, `:71-73`, `:1287-1296`).
- **`-DryRun`** = the same run, with two added guarantees for the switch's own writes: it takes **no
  lock at all** (`:1169-1171`), and afterwards it measures that no `state\switch-*` directory
  appeared and that the pin, the launcher config, the lock and every recorded config file kept their
  sha256 — hard-failing the run if it modified anything (`:1261-1279`).

**The fine print, read from code, and it matters before you quote either promise:** *neither* mode
skips precondition 5 (`:1194-1212`), so both run the real `preflight`, and preflight re-runs
`analyze`, `patch-effect`, `preset-gate` and `verify` through the same dispatcher
(`lib/cli.mjs:1340-1373`). Those rewrites `dsh-update/state/candidates/<ver>/*.json` and append
`state/history/events.tsv` rows (`lib/cli.mjs:1437-1440`). So a dress rehearsal is read-only with
respect to **the deployment**, not with respect to **the pipeline's own state**. The `-DryRun` banner,
"writes nothing at all, anywhere" (`tools/switch-engine.ps1:1047`), is broader than what the code can
deliver; what is actually verified untouched is the list at `:1263-1276`. Neither mode writes to the
live home, the launcher, the pin, or the lock — that part is exact.

`-Rollback -DryRun` likewise reports what it would restore and would quarantine without doing it
(`tools/switch-engine.ps1:877-883`, `:962-966`).

**Test-only overrides must stay at their defaults on a real switch.** `-StateRoot`, `-TargetHome`,
`-WindowsJson` and the `-Inject*` switches exist to prove the write path against copies; every one is
printed loudly when in force (`tools/switch-engine.ps1:84-102`, `:1016-1038`). `-StateRoot` in
particular redirects the switch's own state directory, not the pipeline's.

## 4. The promoted engine does not start until the NEXT boot

Say it plainly: **this switch does not start, stop or restart an engine, and no verb in the pipeline
does either.** The reason is not policy, it is arithmetic: a live DSH engine serves the session that
runs the switch, so restarting it from inside that session would kill the session
(`tools/switch-engine.ps1:57-64`; `lib/cli.mjs:12-15`, `:980-983`). Step 4 proves the engine was not
disturbed, by pid **and** start time, before the switch may claim success
(`tools/switch-engine.ps1:1478-1482`, `:422-446`). The new pin and the new `dshInstall` take effect
the next time an engine is started — by a human, or by a reboot (`:1666-1673`).

**The window that creates, and you must plan for it:** between a successful switch and that boot, the
running engine is still the OLD version while the config on disk has already moved to the new package
names. Existing sessions keep working, but a NEW session started on the currently running engine may
fail to mount its preset (`tools/switch-engine.ps1:1670-1673`). That window is the cost of the switch,
and it is exactly why the two halves are one command rather than two.

## 5. Rollback

`switch-engine.ps1 -Rollback -IUnderstandThisWritesTheLiveHome`. `-Version` / `-StagedHome` /
`-BackupDir` are ignored — the pre-state directory is the input (`tools/switch-engine.ps1:819-821`).
It picks the **most recent** `state/switch-<UTC stamp>` that contains a `PRE-STATE.json`
(`:825-835`), and it refuses with exit `2` unless `-IUnderstandThisWritesTheLiveHome` was given when
that pre-state targeted the live home (`:851-856`).

What it restores, in order:

1. **`pin.json`, the launcher config, and every file in the pre-state's `recordedConfigFiles`** — each
   one **re-hashed against the sha256 recorded before the switch**, with any mismatch a hard failure,
   and anything it overwrote that was not in the pre-state moved aside rather than deleted
   (`:873-898`, `Restore-FromRecord` at `:629-725`). This is FIX 1: the version that failed on
   2026-09-28 restored only the engine and re-ran `sync.py`, which then skipped the coupled steps and
   left the new-name config behind (`:29-38`, `:1605-1608`).
2. A **cross-check against `POST-STATE.json`**, naming any file that is neither what the switch wrote
   nor its pre-switch value (`:900-921`).
3. **Quarantine of v4 session siblings that appeared after the switch.** Every `session.v4.jsonl.zstd`
   under `<target home>\sessions` that was **not** in the pre-state's session list is **MOVED —
   `Move-Item`, never copied, never deleted —** into `<pre-state>\quarantine\v4-sessions\`, with a
   `quarantine-manifest.tsv` recording `relpath / bytes / sha256 / movedTo` (`:923-991`). A file that
   *was* already there is left alone; with no readable pre-state list, v4 files are reported rather
   than moved, because a move without that list could hide a session that was already there
   (`:932-936`, `:948-957`). The move is a repair, not a deletion: the v4 log makes the OLD engine
   hide or refuse that session even though the v3 original is intact, because
   `@deepseek-ai/dsh-session-persistence-jsonl` prefers the v4 sibling
   (`:923-928`).
4. The engine is checked again and left alone; the restored `dshInstall` takes effect at the next boot
   (`:994-1004`).

Exit `3` if there is no pre-state at all (`:827-833`) or if the restore does not verify (`:889-894`).

## 6. The honest traps

**T1 — the 15-minute `PersonalSecretary-HarnessSync` task can rewrite the same live config
mid-switch.** *Read from code, and measured by the switch suite.* This is not theoretical: the
2026-09-28 incident at 15:32:08 happened in the same second the tick fired — the live `~/.dsh` config
was rewritten to the 0.1.7 package names while the OLD engine was still running
(`tools/switch-engine.ps1:20-27`). The defences are the window guard, the lock, and a **re-read of the
task after the writes**: a tick that landed mid-sequence is reported plainly, re-verified, and the
switch rolls back rather than claiming success (`:44-49`, `:1560-1595`). The suite exercises exactly
that (`tests/switch/README-rework.md:27`) and prints, per run, whether the real task ran inside its
window — because that task rewrites the very files the proofs watch (`tests/switch/README-rework.md:31`).
It is also measured that the guard fired on its own test suite twice, with a genuinely imminent tick
(`tests/switch/README-rework.md:70-74`).

**T2 — the session format is a one-way door.** *Measured.* The live home holds session files that are
all `session.v3.jsonl.zstd`; candidates on the 0.1.7 line declare the catalog's `currentVersion: 4`
and ship only a **v3 -> v4** codec, which CONSUMES the old logs into the new format, and no
down-migration codec exists anywhere (`lib/cli.mjs:858-866`, `FINDINGS.md:63-72`,
`tools/backup-state.mjs:9-12`). So rollback is only complete for the logs whose **v3 original is still
on disk** — hence the quarantine in §5, and hence the backup requirement: a copy is the only thing
that bounds the loss (`tools/backup-state.mjs:11-13`). The session-file totals recorded in different
places differ — 1,095 (`FINDINGS.md:66`), 1,253 (`lib/cli.mjs:863`), 1,255
(`tools/backup-state.mjs:10`), 1,258 (`tests/guards/README.md:80`) — they are readings taken at
different times, not a disagreement about the format.

**T3 — version-coupled config names packages that exist on only one side of a version line, so neither
half can be applied alone.** *Read from code, measured against the fetched install.* See the header at
`tools/switch-engine.ps1:5-17`, the names the precondition checks at `:170-179` and `:1127-1130`, and
`FINDINGS.md:38-47`. The consequence the switch's step 3 defends against: if `sync.py` reports
`SKIPPED` for either coupled step, the config was NOT applied, and that is treated as a **failure of
the switch** and rolled back — a half-applied switch is the one state the whole operation exists to
prevent (`tools/switch-engine.ps1:1400-1412`).

**T4 — `-DryRun` writes nothing to the deployment but does write the pipeline's own state.** *Read
from code.* See §3. Do not quote the banner at `:1047` as "writes nothing anywhere"; the verified
surface is `:1263-1276`.

**T5 — accepting G8 does not get you past `promote` condition 1 today.** *Measured on this
deployment.* `promote` condition 1 requires `verify.pass === true`; `pass` is "every gate that ran is
ok"; G8 legitimately fails for a v4-writing candidate; so `-AcceptSessionFormatUpgrade` satisfies
condition 4 only, `promote` still refuses, and the switch rolls the pre-state back with exit `4`
(`tools/switch-engine.ps1:1242-1248`; `tests/switch/README.md:64-75`;
`lib/verify.mjs:1825-1832`; `lib/cli.mjs:899`). The suite's `syncstep` case proves the mechanism step 3
depends on instead (`tests/switch/README.md:72-75`). The disposition of this trap is recorded in the
pipeline's own history; this runbook does not claim it is fixed.

**T6 — what the switch does with `state/switch-*` afterwards.** *Read from code.* The pre-state
directory, its `config/` copies and its `quarantine/` are **left in place**, deliberately: they are
the way back, and nothing here deletes anything (`tools/switch-engine.ps1:1310-1330`, `:1626-1649`).

## 7. What to check after the next boot

The switch prints this list itself on success (`tools/switch-engine.ps1:1674-1677`). An unverified
first boot is not an upgrade:

1. **The engine serves, and its reported version is the new one.** `bin/dsh-update.ps1 status` reads
   the engine path and version by running the engine and prints them under `ENGINE (measured now, not
   from the pin)` (`lib/cli.mjs:338-345`).
2. **A NEW session can be created on each preset, and its preset mounts.** This is the failure the
   whole switch exists to prevent: a preset row naming a package the running engine does not provide
   fails at mount, so it appears the next time somebody starts a chat
   (`tools/switch-engine.ps1:9-12`). Check every preset, not one.
3. **A session from before the switch still opens.** On the v4 door this is the check that has no
   rollback: logs WRITTEN by the new engine cannot be read by the old one
   (`tools/switch-engine.ps1:1681-1682`).

If any of the three fails, `-Rollback` is the way back (`§5`) — and note that it restores the
configuration and quarantines v4 siblings, but it cannot un-write a session the new engine already
wrote in the new format.

---

### What is not established here

- How the staged home in precondition 2 is produced, step by step, in a committed procedure. The
  switch suite depends on one existing (`tests/switch/README.md:18`) and proves the sync mechanism
  that flips it (`tests/switch/README-rework.md:15-18`), but the preparation itself is not recorded.
  What would establish it: a scripted prepare step, or a measurement in the switch suite naming the
  command that builds `%TEMP%\dsh-staged-migrated`.
- Whether the generated preset-rows layer is actually wired into the composition on the 0.1.7 line.
  `FINDINGS.md:275-282` records, as of 2026-09-28, that the generated file composes correctly when
  passed explicitly but is passed by nothing yet. `switch-engine.ps1` does not check that; what would
  establish it: a boot on the new engine whose dump attributes the `preset-<name>` rows to a path the
  profile actually loads.
- No engine was started, stopped or restarted, and no pipeline verb was run, to write this document.
  Every claim above is a reading of the code or of a named measurement in this repo.
