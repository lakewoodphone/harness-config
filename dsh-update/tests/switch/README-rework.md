# dsh-update/tests/switch — proofs for the reworked `switch-engine.ps1`

This directory proves `dsh-update\tools\switch-engine.ps1` after its 2026-09-28 rework. It answers one
question per run: **does the switch refuse what it must refuse, undo what it must undo, and leave the
live deployment alone while doing it?**

```
pwsh -File dsh-update/tests/switch/run-rework-tests.ps1 [-Proof <n|all>] [-Rebuild] [-TickInjectionSeconds 60]
```

Measured on ZABZ-YECHI (this host, `pwsh 7.6.6`): the whole suite is **77 s**, of which the eleven
`lib\cli.mjs preflight` runs are ~60 s. A single proof is 4-15 s. The fixture build is 3.8 s when
`-Rebuild` is given; otherwise the previous run's fixtures are reused.

`run-tests.ps1` (the earlier runner) is still here and still runs; it predates the rework and is kept
for its `syncstep` case, which proves — with the deployment's own `scripts/sync.py` and
`scripts/check-version-coupled-config.py` — that the same sync command flips from `SKIPPED` to
`version check passed` depending only on which engine root it is pointed at.

## The proofs `run-rework-tests.ps1` prints

| # | claim |
|---|---|
| 1 | the script parses, with the `[ref]` variables declared before use |
| 2 | **the live-write gate**: a full run whose `-TargetHome` IS `~\.dsh`, without `-IUnderstandThisWritesTheLiveHome`, refuses (exit 2) and every watched live file keeps its sha256 |
| 3 | `-DryRun` writes nothing: no `switch-*` directory, no lock file, fixture `windows.json` and `state\pin.json` unchanged, all 8 watched fixture files unchanged |
| 4 | the **sync-tick guard**: (4a) the real task is read, read-only; (4b) with `-InjectNextRunInSeconds 60` a tick inside the 180 s margin refuses (exit 2) and writes nothing; (4c) with `-InjectLastRunAfter` a tick that lands mid-sequence is reported, re-verified, and the switch rolls back rather than claiming success |
| 5 | **a failure after the writes rolls back completely**: `pin.json`, `windows.json` and all 7 `recordedConfigFiles` entries are byte-identical to their pre-state sha256 — checked independently, by this runner, against the pre-state the switch itself wrote |
| 6 | `sync.py` reporting `SKIPPED` for a coupled step is a **failure of the switch**, and it rolls back |
| 7 | a real refusal (exit 2) for each precondition: no backup report, `ok=false`, a 13-hour-old backup, a staged home that still carries the 0.1.5 names, preflight NO-GO without the acceptance flag, and preflight NO-GO for a non-G8 reason even with it |
| 8 | the live deployment was not touched: the live config surface, the repo's `multi-window\windows.json` and the repo's `state\pin.json` all keep their sha256, and the repo gains no `switch-*` directory. This proof also prints whether the 15-minute `PersonalSecretary-HarnessSync` task ran inside its window — because that task rewrites the very files being watched, so a difference is only attributable to this suite when it did not |
| 9 | `-Rollback` on a **succeeded** switch: restores `pin.json`, `windows.json` and every recorded config file to their recorded hashes, and MOVES (never deletes, never copies) the `session.v4.jsonl.zstd` that appeared after the switch into the pre-state's `quarantine\v4-sessions\` with a manifest, while the pre-existing v3 session is left alone |

## What is real, what is synthetic, and what is injected

**Real** — the deployment's own code runs: `scripts\sync.py`, `scripts\check-version-coupled-config.py`
and `lib\cli.mjs preflight` (all four guards). Proof 4a reads the real
`PersonalSecretary-HarnessSync` task with `Get-ScheduledTaskInfo`; nothing ever triggers it.

**Synthetic** — `-TargetHome`, `-WindowsJson` and `-StateRoot` all point inside
`%TEMP%\switch-rework-<stamp>\`, so no run can write `~\.dsh`, the repo's `multi-window\windows.json`
or `dsh-update\state\*`. Proof 8 re-hashes the live deployment's config surface at the end.

**Injected, and why** — four switches exist because the alternative was not to test the thing at all:

* `-InjectEngineJson` — the live engine identity. The real engine is a `dsh web --port 3099` process
  serving the session running the tests; the tests must not depend on its pid or version.
* `-InjectPreflightVerdict` — **the honest gap.** On this host the repository's own preflight is NO-GO
  for reasons that have nothing to do with the switch (`analyze (contract diff)` and
  `patch-effect (our layers)` both report BREAKS, and `verify` fails G2 as well as G8). Without an
  injection no run could ever reach the write path, so proofs 3, 4 and 5 inject `GO` or `G8ACCEPTED`
  and the injection is printed, with the real verdict above it. Proof 7e proves that the *uninjected*
  refusal happens (exit 2) and proof 7f proves a non-G8 refusal is not swallowed by the acceptance flag.
* `-InjectPromoteScript` — `fixtures\support\inject-promote.ps1` performs the two writes the real
  `promote` performs at the end (`dshInstall` plus a `.bak-dsh-update-*` sibling; the pin, with its
  predecessor recorded) and appends the history row. It exists because
  `bin\dsh-update.ps1 promote` needs a fetched prefix and `vendor\prefix\0.1.7-rc.2` is **empty** on this
  host. **Gap:** promote's own gates (condition 1, a passing verify; condition 2, a diff verdict that is
  not BREAKS) are therefore not exercised by the write proofs. Proof 4a does reach the real promote and
  records its real `REFUSED` verbatim, which is where that evidence comes from.
* `-InjectSyncOut` — feeds the switch the real text `sync.py` produced against the 0.1.5 engine root
  (`fixtures\syncstep-old.out.txt`) so proof 6 can exercise the SKIPPED decision without first breaking
  the engine.

* `-InjectVerification` — skips step 4 **without passing it**, and says so in its own output and in the
  `POST-STATE.json` it still writes (`verification: "SKIPPED by -InjectVerification …"`). It exists so
  the *later* mid-sequence sync-tick reading can be reached; a name mismatch in the fixture profiles
  would otherwise fail the switch before that check ran. No run that uses it can claim its outcome was
  verified, and the post-state it leaves says as much rather than implying otherwise.
* `-InjectNextRunInSeconds` / `-InjectLastRunAt` / `-InjectLastRunAfter` — the sync task's clock. Every
  write proof passes `-InjectNextRunInSeconds 900` so the guard is deterministic; proof 4a is the one
  that reads the REAL task. This is not cosmetic: with the real clock, a 180 s margin and an 83 s
  suite, proofs 5 and 6 were refused twice with a genuinely imminent tick — the guard doing its job on
  its own test suite.

## Measured facts this suite is built on

* `Get-ChildItem -Recurse` over `state\candidates\<ver>\home` follows **directory junctions** inside
  `profiles\node_modules`. Measured: 127,970 files / 1.0 GB for a tree whose real content is 884 KB,
  and a fixture build that took minutes. `Copy-TreeSkippingModules` skips `node_modules` by name;
  the build is now 3.8 s and 441 files.
* The **whole-tree fingerprint was removed** from proof 2 after it produced a false `CHANGED` on a run
  that provably refused. The live engine serving this session appends to `~\.dsh\sessions`,
  `\storages`, `\metrics` and `\health` every few seconds — measured: 22 files rewritten inside 6
  minutes with the entry count unchanged. No mtime over the whole tree can be evidence of anything
  while that is true, so the proof checks the config surface instead: 3 presets, 3 profile patches,
  `settings.yaml`, `state\pin.json`, `multi-window\windows.json`, SHA256 each.

## The fixtures

* `support\inject-promote.ps1` — the stand-in for the real `promote`, described above.
* `support\mid-sequence-failure.ps1` — the injected failure *after* the writes: it forces the pin back
  to 0.1.5-rc.1, points `dshInstall` at a prefix that does not exist, appends an injected line to every
  live config file, and exits non-zero. A roll-back that "restores" by re-running `sync.py` instead of
  restoring bytes leaves that line behind as visible evidence.
* `syncstep-old.out.txt` / `syncstep-new.out.txt` — real `sync.py` output on the same config against the
  0.1.5 root and the 0.1.7 root. Built by `run-tests.ps1 -Case syncstep`; both are consumed here.
* Everything under `%TEMP%\switch-rework-<stamp>\` is created per run: the fixture `harness-config`
  tree, the two synthetic engine prefixes, `home-new` (the 0.1.7 names), `home-old` (the same bytes
  with the 0.1.5 names), a migrated and a non-migrated staged home, four backup reports, and the
  fixture `state\`.

The synthetic prefixes carry only the `package.json` files and package directories the version checker
resolves. The 0.1.7 one provides every name the repo's presets and profiles name, so the coupled steps
really do report `version check passed`; the 0.1.5 one is missing exactly the three names that exist
only on the 0.1.7 line.

Nothing in this directory deletes anything. Nothing here triggers a scheduled task.
