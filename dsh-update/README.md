# dsh-update

Makes upgrading the DSH harness (`@deepseek-ai/dsh`) safe on a deployment that has ~40
customizations naming upstream artifacts by exact string. Upstream can remove something we depend on
**without any error** — a patch or settings key that stops applying is silently a no-op. This
pipeline detects that before it can reach a live engine, and gates the upgrade on a real boot test.

Frozen interface: `SPEC.md`. This file is the operator view of it — **rewritten 2026-09-28** to match
the code as it now stands (`lib/cli.mjs`, `lib/verify.mjs`, `lib/settings-effective.mjs`, `tools/`),
after the pipeline gained three verbs and the switch tool. Every claim below carries a `file:line`
that supports it; where a claim is a *gap*, it says so and does not soften.

**To actually take this deployment from the pinned engine to a newer one, use `RUNBOOK.md`.** This
file describes the verbs; the runbook describes the operation, its preconditions and its way back.

## Run it

`bin/dsh-update.ps1` is the only entry point. **No verb means `status`.**

```
check -> snapshot -> fetch <ver> -> analyze <ver> -> patch-effect <ver> -> preset-gate <ver>
      -> verify <ver> -> preflight <ver> -> plan <ver> -> promote <ver>
```

That is the order `preflight` enforces on itself: its blocking guards run baseline freshness, then
`analyze`, `patch-effect`, `preset-gate`, `verify`, then the G8 door (`lib/cli.mjs:1335-1405`). The
order string `--help` prints is shorter — it still lists only the original seven verbs
(`lib/cli.mjs:1462`); the line above is the one that is true.

| Verb | Writes | Notes |
|---|---|---|
| `status` | nothing | the pin, the real engine path and version (read by running the engine), what the registry offers, per-candidate analysis state, whether an upgrade is available |
| `check` | nothing | registry query; classifies every published version against the pin |
| `snapshot` | `state/baseline/{contract.json,tree.json}`, refreshes the pin's hashes | describes the **pinned** engine. Read-only against that engine (`--dump-config`) |
| `fetch <ver>` | `vendor/prefix/<ver>/**` | the only `npm install` in the pipeline, into a managed prefix. Never the npx cache, never a global prefix |
| `analyze <ver>` | `state/candidates/<ver>/{consumed.json,contract.json,tree.json,diff.json}`, and `report.md` when `lib/report.mjs` exists | runs our-consumption scan, describes the candidate engine, composes its tree, then diffs. `analyze` alone is enough: it produces everything the diff needs |
| `patch-effect <ver>` | `state/candidates/<ver>/patch-effect.json`, plus `state/baseline/tree-default.json` and `state/candidates/<ver>/tree-default.json` when those unpatched arms are missing; one history row | **does every patch WE own still have its intended effect?** Compares each patch entry's `config`/`disabled` against the candidate's composed row, using the engine's own unpatched `--dump-default-config` tree as the control. Also catches a patch silently swallowing a **new** upstream default. `--profile <name>` (default `web`), `--layer <yml>` to name a layer explicitly. Exit `1` only on a real `BREAKS` (`lib/cli.mjs:1101-1222`, exit at `:1213-1215`) |
| `preset-gate <ver>` | `state/candidates/<ver>/preset-gate.json`; one history row | **does every package and subpath our PRESETS name still resolve?** Resolves every `name:` in every preset file against the candidate contract. Needs `analyze` first — it refuses without the candidate contract (`lib/cli.mjs:1244-1299`, refusal at `:1249-1254`). Exit `1` only on a real `BREAKS` (`:1290-1292`) |
| `verify <ver>` | `state/candidates/<ver>/verify.json`, plus the isolated `home/` and `cwd/` and verbatim engine output under `state/logs/` | the gates; `--full` adds a real web-profile boot. Exit `7` unless `verify.pass` is true (`lib/cli.mjs:730`) |
| `preflight <ver>` | nothing of its own except one history row; it **runs** the other verbs through this same dispatcher, so their artifacts are refreshed | **one command, every guard, one GO/NO-GO** — the triple-check command. Blocking guards: baseline fresh, analyze, patch-effect, preset-gate, verify, and G8. `--full` is forwarded to `verify`. Reported but never blocking: the `unverified`/gap counts (`lib/cli.mjs:1301-1447`). Exit `0` on GO, `8` on NO-GO (`:1443`) |
| `plan <ver>` | nothing | exactly what `promote` would change, file by file, with old and new values and whether each file exists |
| `promote <ver>` | `state/pin.json`, `multi-window/windows.json`, `state/history/events.tsv`, `state/logs/` | gated; backs up before writing; **never restarts the engine** |
| `rollback` | `state/pin.json`, `multi-window/windows.json`, history | restores the predecessor pin and the launcher knob; also never restarts. This is the **pipeline's** rollback: pin and launcher only. The switch's fuller rollback (config files, v4 quarantine) is `-Rollback` in `RUNBOOK.md` |
| `report <ver>` | nothing | the report path, the diff verdict and the gate outcomes |


`--json` on any verb prints one JSON object on stdout. `--help` prints the table.

## Promote in one paragraph

`promote` refuses unless **all four** hold, and prints each one pass/fail either way
(`lib/cli.mjs:898-903`):

1. a `verify.json` with `pass:true` whose `contractSha256` equals the candidate contract **on disk
   right now** — no bypass flag exists, a bypass is a code change (`lib/cli.mjs:899`, `:922-923`);
2. a `diff.json` whose verdict is not `BREAKS` (`:900`);
3. a candidate strictly newer than the pin (`:901`);
4. the session-format upgrade is either absent or explicitly accepted with
   `--accept-session-format-upgrade` (`:902`, `:888-896`). That flag is **not** a bypass: it records
   the decision in the pin and the history, because that upgrade is the one step a rollback cannot
   undo (`:858-871`, `:947-959`).

It then copies `multi-window/windows.json` to a `.bak-dsh-update-<UTC>` sibling, writes `dshInstall`
to `vendor/prefix/<ver>`, writes `pin.json` with `managed:true` and the entire previous pin as
`predecessor`, appends one history row, and prints a notice (`lib/cli.mjs:930-987`).

## The change takes effect at the next engine boot

`promote` and `rollback` write state. Neither starts, stops nor restarts an engine, ever: the engine
serves the session running the promote, so restarting it would kill that session
(`lib/cli.mjs:12-15`, `:980-983`). The change lands the next time an engine is started by a human or
by a reboot.

A stricter and more accurate version of the invariant, because the older wording ("no verb starts an
engine") is not literally true: **no verb starts, stops or restarts the LIVE engine.** Three things do
start a process of their own — `verify --full`, `lib/settings-effective.mjs` and
`tools/staged-boot.ps1` — always a candidate binary, always in an isolated home, always on a spare
port in 3400-3500, and each kills only the pid it started (`lib/verify.mjs:1522-1601`). Port 3099 is
never touched (`lib/verify.mjs:110-111`).

## What this does NOT catch — read this before trusting a `SAFE`

A `SAFE` verdict is a statement about what was **checked**. This list is the honest set of gaps, each
re-derived against the code on 2026-09-28. A gap that has been closed says which gate closes it; a gap
that has not been closed is not deleted.

1. **A settings key the candidate has quietly stopped honouring is STILL invisible to every gate.**
   *Still a gap.* Measured 2026-09-23 (SPEC §C2, restated verbatim in the module:
   `lib/verify.mjs:208-213`): an unknown top-level key, an unknown key inside a known section, a wrong
   value type, an out-of-range number and an invalid enum value **all boot with exit 0 and print no
   diagnostic at all**. G4 is a scan of engine output for diagnostics
   (`lib/verify.mjs:1238-1270`), so it catches a malformed settings document and a hard boot failure,
   never a key that silently became a no-op — and it says so into every `verify.json`
   (`lib/verify.mjs:1269`, `:1788`).
   The specified fix **exists as code**: `lib/settings-effective.mjs` boots a candidate web profile on
   a free port in 3400-3500 against an isolated home, reads the engine's own *effective* settings back
   over the settings controller's HTTP RPC, and asserts every key we set is present with our value
   (`lib/settings-effective.mjs:14-60`, CLI at `:88-91`, its own check at
   `tests/settings-effective/run.mjs`). **No verb in this pipeline runs it**: nothing under `lib/`,
   `tools/`, `bin/` or `scripts/` references the module — the only reference outside the module itself
   is its own test. The verb that should run it is `verify`, and its G4 does not. So the detector is
   built, tested and unwired.
   What it would NOT prove even when wired: that a key which survives schema resolution is still
   *acted on*. It asserts the engine's resolved settings document, not the engine's behaviour (read
   from the module's own mechanism description, `lib/settings-effective.mjs:38-44`).
2. **`patch-effect` and `verify`'s G2 assert different things.** *Moved, and sharpened.*
   `patch-effect` asserts an **effect**: our patch entry's `config` leaves and `disabled` against the
   candidate's composed row, with the unpatched `--dump-default-config` arm as the control, never the
   `patched by` comment (`lib/cli.mjs:1082-1100`). `verify`'s G2 still asserts **attribution**: a
   target passes only if it appears among the rows the fresh dump attributes to our layer
   (`lib/verify.mjs:1051-1056`, `:1107-1146`). So a disable-only patch — the exact shape SPEC §C1
   measured as carrying no annotation at all — is still judged by a comment inside G2, even though
   `patch-effect` judges it by value. `preflight` runs `patch-effect` as its own blocking guard
   (`lib/cli.mjs:1354-1359`), so the effect comparison is in the GO/NO-GO; it is simply not inside G2.
3. **Attribution is unstable between runs.** *Still a gap, and load-bearing.* This file recorded
   (2026-09-23) that the composed tree's `patchedRowIds` disagreed with a fresh dump on one id for the
   same engine. The code now reports that disagreement rather than hiding it — G1 compares the
   supplied artifact against the fresh dump (`lib/verify.mjs:1100-1103`, note at `:1757-1758`) and G2
   prints exactly which ids differ (`:1152-1156`) — but **the G2 verdict is still keyed on the fresh
   dump's attribution** (`:1108`, `:1144-1146`). Never key a verdict on it remains true advice; the
   gate does.
4. **Agent presets: the gap is closed — outside `verify`.** *Closed by the `preset-gate` verb.*
   Presets contribute **zero** rows to `--dump-config`, and a headless run does not load a preset
   either, so G5 — the strongest end-to-end gate — is blind to preset breakage
   (`lib/cli.mjs:1226-1243`, measured there 2026-09-28 with three staged homes). `preset-gate <ver>`
   resolves every `name:` in every preset file against the candidate contract and is a **blocking**
   guard in `preflight` (`lib/cli.mjs:1244-1299`, `:1361-1366`). It is **not** a verify gate: verify's
   gate list is G1, G2, G3, G4, G5, GFULL, G8 (`lib/verify.mjs:153-161`) — there is no G7, and the
   pipeline's own labels "(gates G1-G8)" (`lib/cli.mjs:1393`) and "G1-G7 all ran"
   (`tools/switch-engine.ps1:1237`) are looser than the list. What this still does not prove: that a
   session actually MOUNTS on a preset — the gate is static, and on the 0.1.7 line local preset
   **directories** stop being read anywhere in the install, so the mechanism itself changes
   (`FINDINGS.md:105-145`).
5. **Session format.** *Closed by G8, with the trap in item 9.* G8 reads `currentVersion` and the
   codec list out of **both** installs and counts the live session files by name
   (`lib/verify.mjs:1307-1500`; gate registered at `:160`); `--no-boot` does **not** skip it
   (`lib/verify.mjs:223`). It is a blocking guard in `preflight` (`lib/cli.mjs:1398-1405`) and promote
   condition 4 (`lib/cli.mjs:858-903`), and the deliberate acceptance of the one-way door is recorded
   in the pin and the history (`lib/cli.mjs:909`, `:947-959`). Recorded measurements of the door
   itself are in `SPEC.md` C8, `FINDINGS.md:63-72` and `lib/cli.mjs:858-866`; see `RUNBOOK.md` for the
   trap, and note that the session-file counts in those records differ (1,095 / 1,253 / 1,255 / 1,258)
   because they are readings taken at different times, not a disagreement about the format.
6. **The new-upstream-default check only runs when both `--dump-default-config` arms exist.**
   *Still a gap.* `patch-effect` generates them, and when it cannot it says so and lists the
   comparison as `unverified` — never as a pass (`lib/cli.mjs:1147-1166`, `:1202-1204`).
7. **`--full` is opt-in.** *Still a gap.* `GFULL` is the only opt-in gate (`lib/cli.mjs:1386`), it
   does not block `preflight`, and without it a verification does not prove the web profile boots; it
   proves the headless profile boots and completes a turn (`lib/verify.mjs:1796`).
8. **A `verify` pass is bound to `contractSha256`**, so editing a `file:` plugin dependency or
   re-resolving a transitive prerelease after verifying makes `promote` refuse. *Intended.*
   `promote` re-reads the candidate contract hash and refuses on a mismatch (`lib/cli.mjs:840-848`,
   `:899`).
9. **A one-way-door DECISION is folded into `pass`, which is a correctness flag — and `promote`
   condition 1 keys on `pass`.** `pass` is "every gate that ran is ok, and G4/G5 ran"
   (`lib/verify.mjs:1825-1832`); G8 legitimately fails for a candidate that writes a newer session
   format; and condition 1 keys on `pass` (`lib/cli.mjs:899`), so accepting the door at condition 4
   (`lib/cli.mjs:902`) still cannot accept it at condition 1, and promotion is blocked by a decision
   the operator has already made. The trap is stated in the switch suite's own record
   (`tests/switch/README.md:64-75`, measured on this deployment) and in `tools/switch-engine.ps1:1242-1248`.
   The disposition of this trap is recorded in the pipeline's own history; **it is not fixed here and
   nothing in this file promises a fix.**

## Taking the upgrade on the live deployment

The verbs above prepare and gate a candidate; they do not perform a safe live switch on their own.
For 0.1.5 -> 0.1.7 the engine and the version-coupled config must move **as one operation**, and the
tool for that is `tools/switch-engine.ps1` — its preconditions, its dress rehearsal, its exit codes
and its rollback are documented in **`RUNBOOK.md`**.

## Secrets

`verify` builds an isolated `DSH_HOME` out of `settings.yaml`, `profiles/` and `.agent-presets/`.
**`.credentials.yaml` is deliberately NOT copied** (`lib/verify.mjs:1717-1719`). The model credential
is resolved from the state home (`<state-home>/.credentials.yaml` — by default the operator's real
home, not the staged config under test) and passed to the boot children through the child
**environment** only; only its presence, and its length, are ever reportable
(`lib/verify.mjs:1694-1711`, `:1743-1744`). If a copy exists from an earlier run of an older version
of this module it is **reported, not removed** — nothing in this pipeline deletes anything
(`lib/verify.mjs:1733-1739`).

State and vendor output must never be committed: `dsh-update/.gitignore` ignores `state/` and
`vendor/` wholesale. **`state/candidates/**` should not be treated as shareable.** (One stale comment
still says the opposite inside a file this README does not own: `lib/verify.mjs:7`.)

## Safety invariants

1. Nothing deletes anything. No `rm`, no pruning of the npx cache or `vendor/`; old prefixes stay
   until a human removes them. `fetch` refuses to overwrite an existing prefix (`lib/cli.mjs:524-531`).
2. Only `promote` and `rollback` write outside `dsh-update/`, and only to
   `multi-window/windows.json` (or `DSH_UPDATE_WINDOWS_JSON`), after a timestamped backup
   (`lib/cli.mjs:930-934`, `:1009-1019`). `tools/switch-engine.ps1` writes more than that, on purpose;
   it is documented in `RUNBOOK.md`.
3. Every write outside `dsh-update/` is a backup plus a temp-file-and-rename replacement.
4. `state/history/events.tsv` is append-only and is the audit trail.
5. No verb starts, stops or restarts the **live** engine; see the corrected wording above.
6. Every reading carries its source; an empty or failed read is reported as a failure, never as an
   empty success. A registry that cannot be reached makes `status`/`check` exit non-zero, not "no
   newer versions" (`lib/cli.mjs:390-392`).

## Rolling back

```
pwsh -File dsh-update\bin\dsh-update.ps1 rollback
```

Restores the `predecessor` recorded in `pin.json` and the matching `dshInstall` value (removing the
key if the predecessor was unmanaged), appends a history row, and says plainly that the restored
engine takes effect at the next boot (`lib/cli.mjs:990-1050`). With no predecessor it refuses and
changes nothing (`:994-1000`). This restores **the pin and the launcher knob only** — after a switch
that also moved config files, use the switch's own `-Rollback` (`RUNBOOK.md`).

## Where state lives

```
dsh-update/state/pin.json                      what we run now
dsh-update/state/baseline/                     the pinned engine: contract.json, tree.json
                                               (tree-default.json is written by patch-effect)
dsh-update/state/candidates/<version>/         contract.json, tree.json, diff.json, verify.json,
                                               report.md, and the modules' own artifacts beside them:
                                               consumed.json, tree-default.json, patch-effect.json,
                                               preset-gate.json; plus home/ and cwd/ (isolated)
dsh-update/state/history/events.tsv            append-only audit trail
dsh-update/state/logs/                         verbatim engine and invocation output
dsh-update/state/locks/switch-engine.lock.json held only while a switch is running
dsh-update/state/switch-<UTC stamp>/           the switch's PRE-STATE.json, POST-STATE.json,
                                               config/ copies and quarantine/
dsh-update/vendor/prefix/<version>/            a candidate's own npm prefix
```

`store.mjs` names the five artifacts the dispatcher owns (`lib/store.mjs:75-85`); the rest are written
by the verb or module that produces them.

## Exit codes

These are the **pipeline's** codes (`lib/cli.mjs`); `tools/switch-engine.ps1` has its own, and they are
listed in `RUNBOOK.md`.

`0` ok; `1` bad usage; `2` absent/unusable state (no pin, unparseable config); `3` registry
unreachable; `4` a sibling `lib/*.mjs` is absent or does not export the expected entry point; `5` a
write was refused (config unreadable, prefix already present); `6` fetch failed; `7` a gate or the
composed tree failed (and `verify` exits `7` unless `pass` is true); `8` promote/rollback refused a
precondition, or `preflight` returned NO-GO.

`patch-effect` and `preset-gate` exit `1` on a real `BREAKS` only — `RISKY` is a thing to read, not a
stop signal (`lib/cli.mjs:1213-1215`, `:1290-1292`).

## Environment overrides

Read-only diagnostics, except where noted; none of them change what a verb does except the first two,
which exist so tests never touch the live launcher config.

- `DSH_UPDATE_WINDOWS_JSON` — path of the launcher config to read and write instead of
  `multi-window/windows.json`. Used to test `promote`/`rollback` against a copy.
- `DSH_INSTALL` — an npm prefix containing `node_modules\@deepseek-ai\dsh\lib\bin.js`. Read by this
  tool exactly as `dshw.ps1` reads it.
- `DSH_HOME` — the **config under test** for `analyze`, `verify`, `patch-effect` and `preset-gate`.
  Point it at a staged, migrated home and the guards can be judged against the config that would be
  installed rather than against the live one, which is by definition not migrated yet
  (`lib/cli.mjs:571-576`, `:695-698`, `:1132`, `:1255`).
- `DSH_STATE_HOME` (or `verify --state-home`) — where **runtime state** lives: G4/G5 read the
  credential from `<state-home>/.credentials.yaml` and G8 counts `<state-home>/sessions`
  (`lib/verify.mjs:233-237`). Default: the operator's real home, unless `DSH_HOME` names a staged
  location.
- `DSH_UPDATE_NPM_TIMEOUT_MS` — registry query timeout (default 90000).
- `DSH_UPDATE_FETCH_TIMEOUT_MS` — fetch timeout (default 900000).
- `DSH_SWITCH_TARGET_HOME`, `DSH_SWITCH_ENGINE_LOCK_STALE_SECONDS` — switch containment overrides,
  test-only in principle; see `RUNBOOK.md`.
