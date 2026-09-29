# The spend guard's load path — `spend-guard (dsh-plugin-cost/guard): failed to import`

**Date:** 2026-09-28 · **Package:** `packages/plugin-cost` · **Engine under test:** `0.1.7-rc.2`
(`dsh-update/vendor/prefix/0.1.7-rc.2`) · **Machine:** ZABZ-YOGA

This file is the durable record of one failure mode and its removal. It is written for the session
that has no memory of this one: what was measured, what was changed, how to tell in one command
whether the money ceilings are actually being enforced, and what is still not proven.

---

## 1. The failure, and why it was the worst kind

`spend-guard` is the row that enforces the owner's money ceilings (`warn` 35 USD, no new fan-out past
80, refuse a step at 150, concurrency cap 12 generating agents). Booting a candidate engine against
an isolated home, the engine reported:

```
dsh: warning: 1 entry did not activate
spend-guard (dsh-plugin-cost/guard): failed to import
```

That is the whole diagnostic. No reason, no path, no error. An engine that boots with this row absent
is **worse than an engine with no guard at all**, because the operator believes he is protected.

Worse still, it was intermittent: the prior session's four back-to-back boots of *one unchanged*
staged home produced two failures and two passes, and the variable it was testing (legacy
`settings.yaml` present or absent) had no effect on the outcome.

## 2. What is established

### 2.1 The engine's own diagnostic is a constant string, not an error

`entry.fiber === undefined` is rendered as the literal text `failed to import`
(`@deepseek-ai/dsh-app-boot/lib/index.js`, `inactiveEntries()`), and the underlying throw from
`@deepseek-ai/cordis-plugin-loader/lib/index.js` `Entry._init()` is sent to `ctx.logger.error(error)`,
**which reaches no sink in this deployment** — it appears in no engine stderr, in no stdout, and in no
file. So the reason was invisible *by construction*, on both sides. That is why the earlier
investigation could not name a cause from the logs: there was nothing in them to name.

### 2.2 The module failed to load, deterministically, when its anchor could not provide the package

The guard's generated module scope carried exactly one bare-package resolution:

```js
const Schema = require('@deepseek-ai/schemastery');   // lib/guard.js, module scope, line 23 (before the fix)
```

through a hand-rolled anchor at `<DSH_HOME>/profiles/web/package.json`, which resolves
`@deepseek-ai/*` out of `<DSH_HOME>/profiles/node_modules`. Measured both directions, before the fix:

| `DSH_HOME` | `import('.../lib/guard.js')` |
|---|---|
| an isolated home with no `node_modules` anywhere | **`FAILED: MODULE_NOT_FOUND :: Cannot find module '@deepseek-ai/schemastery'`** |
| the staged home (the anchor resolves) | `LOADED` |

That is the failure mode, reproducible on demand — and it is the same one recorded on 2026-09-17
(`docs/incidents/2026-09-17-dsh-engine-boot-failure/`), where it was worse: it took the whole engine
down with exit 1.

### 2.3 The mechanism of the INTERMITTENCY is not established

The fix below removes the failure mode without proving why the engine hit it about half the time. Two
candidate mechanisms were tested and neither is confirmed:

- **"The anchor directory is transiently absent during boot."** Plausible: the engine rewrites
  `profiles/web/cordis.yml` on every boot and takes a lock (`package.json.lock`) in that directory,
  so something in the profile's plugin tree is being reconciled while entries are imported. **Not
  observed**: the anchor (`<staged>/profiles/node_modules/@deepseek-ai/schemastery/package.json`)
  existed in every boot this session watched, and the flake did not reproduce at all.
- **"The slowest import loses a loader race."** Disproved as a *primary* explanation by measurement:
  `lib/guard.js` costs 65–85 ms to import and a sibling plugin entry with no bare-package resolution
  costs 68–85 ms, in the same runs. The guard's import was not slow, so "slowest entry loses" has
  nothing to bite on.

**Baseline in THIS session, before any change:** four consecutive boots of the staged home, four
`entries activated : all (no activation warning)`. The flake did not reproduce today, so "the
flakiness is gone" cannot be demonstrated causally from boot counts alone — see §5 for what was done
instead, and §2.2 for the one measurement that does decide the question at the module level.

**After the change:** 9 boots in one sequence (8 ordinary + 1 forced-degraded control) between
`2026-09-28T15:38:36` and `15:40:23`, `failed-to-import=0` on every one of them, on the final build.
The first such sequence, run before the last cosmetic change, was 15:36:05 → 15:37:50 and also clean.

## 3. The fix: remove the load-time dependency, do not race it

**A protective plugin may not fail to load because of where it looks for a library.**

`lib/guard.js` now resolves **only `node:` builtins** while it is being imported (`node:fs`,
`node:os`, `node:path`, `node:zlib`), which resolve from any anchor whatsoever — so no state of the
DSH home can stop this row from importing. The one thing the guard could not do without is the
settings *schema class*, and it is needed only to register the `spend-guard` settings namespace, not
to compute or enforce a ceiling. So it is resolved **lazily, inside `apply()`**:

- **multi-root, in probe order** — `<home>/profiles/node_modules`,
  `<home>/profiles/web/node_modules`, `<home>/profiles/web`, `<home>/profiles`,
  `<home>/node_modules`, plus `DSH_INSTALL/node_modules` when set. The old single hard-coded anchor is
  exactly what broke; this is the same multi-candidate shape as `loadYaml()` in
  `scripts/merge-settings.mjs`.
- **shape-validated** — the resolved value must actually carry the methods `policySchema()` calls
  (`object`, `number`, `string`, `boolean`, `union`). A module that resolves but is the wrong thing is
  **rejected**, not used hopefully.
- **reported** — every attempt is recorded (root → reason), whether or not one succeeded.
- **a failure is a DEGRADED mode, never an absent guard** — with no schema class the guard still
  mounts, still enforces `warn` 35 / fan-out 80 / ceiling 150 / cap 12 from the row `config` and the
  coded `DEFAULTS` in `src/guard.mjs`, and says so. `onInternalError: closed` is untouched.

`DSH_SPEND_GUARD_SCHEMA_ROOTS` (semicolon-separated) **replaces** the candidate list. That is how the
degraded path is forced on purpose — an operator question ("is the guard really enforcing?") and the
negative control in §5 both use it. Nothing edits a generated file to test this.

## 4. Where an operator sees whether the guard is enforcing

Three surfaces, in the order a check should look:

1. **`<DSH_HOME>/health/spend-guard.json`** — the activation record, written synchronously at mount
   and again on every escalation, roll and dispose. This is the deployment's own health surface:
   `plugin-health` writes `processes.json` and `list-agents.json` there and `scripts/engine-vitals.mjs`
   writes `engine-vitals.json`. Read it directly:

   ```powershell
   Get-Content "$env:USERPROFILE\.dsh\health\spend-guard.json" -Raw | ConvertFrom-Json |
     Select-Object mounted,degraded,writtenAt,pid,@{n='mode';e={$_.schema.mode}},@{n='schemaRoot';e={$_.schema.root}},
                   @{n='ceilingUsd';e={$_.limits.ceilingUsd}},@{n='source';e={$_.limits.source}}
   ```

   `degraded: true` means the settings namespace is not registered and a `spend-guard:` block in
   `settings.yaml` is being ignored — the ceilings in `limits` are still in force. A **missing or
   stale** `writtenAt` on a live engine means the row did not activate: that is the finding this file
   exists for.

2. **The engine's own log** — `ctx.logger` is a **dead end in this deployment**, and that is measured,
   not assumed: neither the loader's `ctx.logger.error` for a failed entry nor the guard's own
   `ctx.logger.info` at mount appears in the engine's captured stderr, in stdout, or anywhere in its
   home (checked on the graded boots: 8 clean boots and 1 degraded boot, three stderr files, the whole
   staged home grep'd). The guard therefore writes the one line that must not be missed — `DEGRADED` —
   **straight to `process.stderr`** as well, once per boot, only in that mode. That line does land in
   the log the launcher keeps (`~/.dsh/multi-window/logs/<port>-*.err.log`, or the helper's stderr),
   and it is the only guard line that does. The ordinary mount is recorded in the health file, not on
   stderr, deliberately: a per-boot line for a normal mount becomes noise and hides the abnormal one.

3. **`node test/verify.mjs`** in this package (all six checks) — in particular the new **coldboot**
   half, which fails if anyone reintroduces a bare-package resolution into the generated guard, and
   which imports `lib/guard.js` in a child whose `DSH_HOME` is an empty directory.

## 5. Proof, both directions

| What | Result |
|---|---|
| `lib/guard.js` module scope: every `require()` specifier | `node:fs` ×2, `node:os`, `node:path`, `node:zlib` — **no bare package** (5 requires, all builtins) |
| `import('lib/guard.js')` with `DSH_HOME` = an empty home — **before** | `FAILED: MODULE_NOT_FOUND :: Cannot find module '@deepseek-ai/schemastery'` |
| the same command — **after** | `LOADED` |
| 8 consecutive boots of the staged home, same engine, same home | `failed-to-import=0` in all 8; `entries activated : all (no activation warning)` in all 8 |
| the shipped cold-boot suite against a scratch copy of the **old** shape | **2 FAIL** / exit 1 — the static "no bare require at load" check, and the dynamic barren-home import with `FAILED: MODULE_NOT_FOUND Cannot find module '@deepseek-ai/schemastery'`. The regression test reproduces the engine's own death on demand. |
| negative control: `DSH_SPEND_GUARD_SCHEMA_ROOTS` forced at a directory that cannot provide the library, then boot the engine | boots, `entries activated : all`, **the engine's stderr carries the guard's `DEGRADED` line naming the root it tried**, the record says `degraded: true`, and a step at the ceiling is still **refused** (proved in `guard.test.mjs`, which mounts the generated artifact with the resolution path forced to fail) |
| `node test/guard.test.mjs` | 86/86 — includes the forced-degraded mount of the *generated artifact*, the skipped settings namespace, the health record, and a `{kind:'reject'}` at the ceiling while degraded |
| `node test/cold-boot.test.mjs` | 15/15 — includes "every require() is a `node:` builtin" and the barren-home import |
| `node scripts/build.mjs --check` | `ok: lib/index.js`, `ok: lib/guard.js`, `ok: lib/client.js` |
| `lib/index.js`, `lib/client.js` byte-identical before/after | SHA-256 unchanged (`48F9DDC6…`, `9A04AF24…`): the change is confined to the guard |

## 6. What is still open

- **The intermittency mechanism (§2.3).** The failure mode is removed; why the engine hit it half the
  time is not proven. Do not present a guess as the cause.
- **The engine drops the reason for a failed entry.** `ctx.logger.error(error)` in
  `cordis-plugin-loader`'s `_init()` reaches no sink here, and `inactiveEntries()` prints the constant
  `failed to import`. This plugin can no longer *be* that entry for a missing package, but any other
  entry that fails still gets one useless line. That is an engine/launcher improvement, not this
  package's.
- **`profiles/web/cordis.yml` is rewritten on every boot** and a `package.json.lock` appears in that
  directory. Nothing in this session read what writes it. It is probably harmless; it is also the most
  likely home of the race, and it was not investigated to a conclusion.

## 7. Files this changed

| File | Why |
|---|---|
| `src/guard-entry.mjs` | removed the module-scope `Schema` import; added the lazy multi-root, shape-validated resolver, the DEGRADED report and its `process.stderr` echo |
| `src/guard.mjs` | `healthFile` config; the activation record; degraded mode stated at mount; `healthFile` in the settings schema |
| `scripts/build.mjs` | comments only — they described the contract that no longer exists |
| `test/guard.test.mjs` | every mount isolated with `healthFile`; new ACTIVATION section (degraded + ordinary) |
| `test/cold-boot.test.mjs` | new PACKAGES and BARREN halves |
| `README.md` | the guard row, the six checks, the layout |
| `docs/2026-09-28-guard-activation.md` | this file |
| `lib/guard.js` | regenerated (`node scripts/build.mjs`) — the only generated file that changed |

A journal entry was not filed from this session because its write scope was the package directory.
The intended shape, for whoever holds the journal:

```bash
python ~/code/harness-config/journal/tools/journal.py append pain --title "spend-guard could fail to IMPORT (money ceiling silently absent ~50% of boots); engine reports only 'failed to import'"
python ~/code/harness-config/journal/tools/journal.py append lessons --title "a protective plugin must resolve no package while loading: node: builtins only, everything else lazy and optional"
```
