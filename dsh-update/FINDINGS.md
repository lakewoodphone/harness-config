# Findings — examined DSH versions

This file is the **durable** record of what the pipeline concluded about each upstream version.
`state/` (where `diff.json`, `report.md` and `verify.json` actually land) is git-ignored, so a
conclusion that lives only there does not survive a fresh clone. Anything a future session needs to
know goes here.

Written by hand from the pipeline's own artifacts, with every claim re-checked against the fetched
install. Relative to the pin `0.1.5-rc.1` (the `@deepseek-ai/dsh` launcher version; 230 of the 240
installed packages are `0.1.5-rc.2` — see `SPEC.md`, "The version is a set, not a number").

## 2026-10-05 — the pipeline was fixed, the pin could not move, and the reason is the repo itself

This section is the honest state after a full session on the update system. Read it before trusting any
verdict above it: two of the entries above are now stale, and the reason nothing has been promoted
since 2026-09-23 is not in this file at all.

### The pin is stuck because `harness-config` stands on the version seam

`analyze` scans the **repo**, and the repo is half-migrated:

| surface | state | evidence |
|---|---|---|
| `profiles/web/cordis.patch.yml` (repo) | **0.1.7 names** — `@deepseek-ai/dsh-agent-preset` at 301, 485, 980; `@deepseek-ai/dsh-workflow-ptc` at 463, 928, 1481; 1624 lines | measured 2026-10-05 |
| `scripts/make-preset-rows.mjs` | **0.1.7 name** — `dsh.profile.bundles` names `@deepseek-ai/dsh-agent-preset` at :121 | measured 2026-10-05 |
| `presets/*/agent.cordis.yml` (all three) | **0.1.5 names** — `@deepseek-ai/dsh-workflow-worker-thread`, restored deliberately by commit `60b3724` on 2026-10-04 | measured 2026-10-05 |
| `~/.dsh/profiles/web/cordis.patch.yml` (live) | **neither** — 252 lines, no coupled name at all | measured 2026-10-05 |

`sync.py`'s version guard does its job and SKIPS both coupled scopes, so production is safe. But
`analyze` therefore reports BREAKS for **every** candidate:

```
0.1.5-rc.3   BREAKS=3   dsh-agent-preset (repo profile row), dsh-agent-preset (bundle decl), dsh-workflow-ptc
0.2.0-rc.2   BREAKS=2   dsh-agent-presets at profiles/mesh/cordis.patch.yml:93, dsh-workflow-worker-thread in all three presets
0.1.7-rc.2   BREAKS=1, and patch-effect BREAKS=2
```

and `verify` fails **G2** with `LOST (our patch silently stopped applying): agent-preset-registry`.
There is no candidate for which `promote` can pass condition 2. `check-version-coupled-config.py` names
this exact state in its own header: *"the machine is standing on the seam"*. It was invisible from
`status` because each half looks reasonable on its own.

### Two entries above are stale — the pipeline now catches them, which is the point

* **0.1.5-rc.3 is no longer demonstrably SAFE.** Its stored `verify.json` was produced for
  `contractSha256=3de3956a…` while the contract on disk is `48d47a8c…`, and it carries **six** gates —
  G1, G2, G3, G4, G5, GFULL, with **no G8 at all** — i.e. it was written by an older `verify.mjs`. A
  verdict can be invalidated by a change to the pipeline that produced it, and nothing could see that
  before the `verifyReading`/contract checks added on 2026-10-05.
* **`state/candidates/0.1.7-rc.2/*` still holds verdicts computed against a `%TEMP%` test fixture.**
  The stored `patch-effect.json` names
  `C:\Users\ezabz\AppData\Local\Temp\switch-rework-20260928T203232Z\staged-home\profiles\web\cordis.patch.yml`
  as the layer that broke. Re-run before reading anything in that directory.

### 0.2.0-rc.2 — fetched and analyzed. BREAKS=2, both mechanical.

`npm install` 107,761 ms into `vendor/prefix/0.2.0-rc.2` (453.6 MB / 26,622 files), the only npm install
in the pipeline; the npx cache was untouched. 288 packages, 194 composed rows (vs 163 at the pin).

| finding | what |
|---|---|
| `F001` B1 BREAKS | `@deepseek-ai/dsh-agent-presets` is ABSENT — named by `profiles/mesh/cordis.patch.yml:93` and the live `~/.dsh` copy |
| `F002` B1 BREAKS | `@deepseek-ai/dsh-workflow-worker-thread` is ABSENT — named by all three presets (`cordis-bg:287`, `yocheved:381`, `zabz:464`, repo and live) |

Both are the two renames already documented above, and both are mechanically resolvable. The rest is
`RISKY=4` (the `@deepseek-ai/dsh` `configTrees` block emptied, `dsh-tool-cordis` gained `./host`,
`dsh-web-app`'s `dsh.bundle.patch` became an array of five, the CLI surface moved), `CAPABILITY=75`
including `dsh-plugin-manager`, `dsh-config-editor` and the voice-input group, and `INFO=55`.
**345 consumed references could not be resolved** — that is the honest size of the blind spot and it is
larger than at 0.1.5-rc.3, so treat this candidate as less well covered, not better.

### The pipeline itself was repaired on 2026-10-05 — four defects

1. **`preflight` and `promote` disagreed about `verify.json`, and the disagreement deadlocked the whole
   write path.** `verify.pass` is false whenever any gate that ran failed, and G8 is deliberately not ok
   for every candidate that writes session format v4. Preflight could reach GO with
   `--accept-session-format-upgrade`; promote condition 1 still demanded `pass === true`. So preflight
   said GO, promote refused, and `switch-engine.ps1` rolled the switch back — with the flag threaded to
   promote by `switch-engine.ps1:1334` and structurally impossible to honour. Both verbs now call
   `verifyPromotable()` in `lib/promote-reading.mjs`. Held by `tests/guards/promote-door.mjs` (16/16).
2. **No verdict recorded which config it judged.** `state/candidates/<ver>/*.json` is written by a real
   run *and* a test run, and on 2026-09-28 a fixture's staged home overwrote the authoritative
   artifacts while `status`/`preflight` presented them as this machine's state. `lib/artifact-provenance.mjs`
   now stamps a derived `configIdentity` into every artifact; re-stamping with a different home throws;
   `promote` gained condition 5 and `preflight` a blocking `artifact provenance` guard. Held by
   `tests/guards/provenance.mjs` (28/28).
3. **`lib/settings-effective.mjs` existed and no verb ran it.** The README's own gap #1 — "a settings
   key the candidate has quietly stopped honouring is invisible to every gate" — was detected but
   unreachable. There is now a `settings-effective <ver>` verb, reported non-blocking by `preflight`
   (its false-failure rate against a real candidate is not yet measured, so it does not change GO).
   **First real reading ever taken, 0.1.5-rc.3, 2026-10-05: `absent=0 different=0`** out of 108 keys /
   34 distinct, 19 present with our value, 15 not assertable on this machine — every settings key this
   deployment sets *is* present in the engine's own effective-settings report. The run also verified the
   live engine on :3099 was unchanged, and that the resolved API key appeared 0 times across the written
   files.
4. `status` no longer renders a door-only verify as a bare `FAIL`, and `promote` prints every condition
   from the array instead of indices 1-3 — which is how conditions 4 and 5 came to be evaluated but
   never shown.

### The no-data-loss proof, measured on 0.2.0-rc.2 (2026-10-05)

`tools/session-format-audit.mjs` — NEW, and re-runnable before **any** format-changing upgrade. It exists
because STATE-COMPAT.md named this exact work as its own item 1: *"I did not execute the v3→v4 codec
against a live log … What would settle it: in a throwaway DSH_HOME under %TEMP% (never the live home),
copy one session directory and call prepareJsonlMigration on it."* A conclusion that lives in a
hand-written document does not re-check itself, and the corpus has grown from 1,256 files to 2,250.

| arm | result |
|---|---|
| the formats in play | candidate declares `currentVersion: 4`; codecs v0→v1, v1→v2, v2→v3, **v3→v4**; **no down-migration codec exists**, so going back means removing the new sibling, never restoring an original |
| **source protection** (static, on the candidate's own persistence module) | 3,528 lines, exactly **two** removal calls: `rm(path)` inside `removeTemporary` (:2012) and `removeCommittedTemporary` (:2020), both staged temps. **No code path in the candidate unlinks a source log.** A v3 file is never the file it removes — which is what makes the move recoverable rather than final |
| **corpus admissibility** (read-only, frame by frame) | **2,250 live logs, all v3** by name AND by first-frame header; **328,864 zstd frames decoded, 0 decode errors, 0 unparseable lines**; **0 refused constructs** of all three kinds (`code-dispatch`, `request-header-system`, `tool-result-block`); 647.9 MB read read-only |

**No session in this corpus would be refused by the v3→v4 migration**, and the candidate cannot unlink an
original. That is the no-data-loss basis, and it is now a command rather than a paragraph:

```
node dsh-update/tools/session-format-audit.mjs --candidate dsh-update/vendor/prefix/<ver> --out <path>
```

Two notes for whoever runs it next. First, it reports the **frame count** on purpose: a whole-buffer
`zstdDecompressSync` returns ONE frame per file, so a naive scan produces the same clean zero for the
wrong reason — STATE-COMPAT.md records that its own first two scans failed exactly that way, and the
control is the frame count. Second, the source-protection arm resolves the **enclosing function** of each
removal call rather than pattern-matching the line: its first version flagged `rm(path)` as unsafe
because it could not see that `path` was a staged temp, and a gate that cries wolf on the one property it
exists to prove is a gate that gets ignored. The first version also flagged a comment.

**Still not proven:** the codec is not executed here, and whether `skills/` inside our presets still
resolves under 0.1.7+ (`baseUrl`/`customSkillDirs`, the item below) still needs a real session mount.

### 2026-10-05 (second session) — preflight went from 4 blocking failures to 1, and the last one is real

`preflight 0.2.0-rc.2 --full --accept-session-format-upgrade` with `DSH_HOME=<staged>` and
`DSH_STATE_HOME=<live>`:

```
PASS  baseline fresh
PASS  analyze (contract diff)      verdict RISKY  (BREAKS=0 RISKY=4 CAPABILITY=75 INFO=55)
PASS  patch-effect (our layers)    verdict SAFE
PASS  preset-gate                  verdict SAFE
FAIL  verify (gates G1-G8)         pass=false; failing: G2, G8
PASS  G8 session-format door       ACCEPTED DELIBERATELY — v4, live corpus counted
GAP   settings-effective           verdict BREAKS (absent=11 different=4 of 108 keys)
PASS  artifact provenance          5 artifacts agree on the staged home
VERDICT: NO-GO — 1 of 7 blocking guard(s) failed: verify
```

Three separate defects were diagnosed and fixed to get there.

**1. `analyze` scanned the repo, which was standing on the version seam.** The repo's
`profiles/web/cordis.patch.yml` was already on the 0.1.7 names while `presets/*/agent.cordis.yml` and
`profiles/mesh/cordis.patch.yml:93` were still on the 0.1.5 names, so `analyze` reported BREAKS for
**every** candidate. Fixed by migrating those four repo files — taken byte-for-byte from a staged home
built by `lib/stage-home.mjs`, so the rewrite is the proven quote-aware one. Safe on the running 0.1.5
engine, verified not assumed: `scripts/check-version-coupled-config.py` resolves the engine from the
RUNNING process and reports the modern names missing, so `sync.py` SKIPS both coupled scopes.

**2. The switch named the config home but not the state home.** `switch-engine.ps1` ran preflight with
only `DSH_HOME` staged, so for a deliberately-named staged home G4/G5 did not run (no credential), G8
refused because it looked for `<staged>\sessions`, and `settings-effective` refused for the same reason.
Three symptoms, one mistake: asking a config question of a directory that holds no state. `verify`
already supports `--state-home`; the call simply never passed it. G8 now counts the real corpus.

**3. `stage-home.mjs` generated the preset ROWS from the un-rewritten source.** It rewrote the staged
`.agent-presets` copies and then ran the converter against `join(opts.from, …)` — the LIVE, pre-rewrite
directory. Every emitted `preset-*` row therefore carried a `workflow` row naming
`@deepseek-ai/dsh-workflow-worker-thread`, which 0.1.7+ does not provide. **A composition row naming an
absent package fails at MOUNT, and inside a preset that breaks new session creation** — the 2026-10-04
incident. Nothing in the module or in `switch-engine.ps1` precondition 2 noticed, because every existing
assertion counts occurrences in the `.agent-presets/*/agent.cordis.yml` FILES, and on 0.1.7+ that
directory is **not read at all**; the rows the engine mounts live in the profile patch. `dsh-update
analyze` is what caught it. Fixed, with a hard refusal added so it cannot return: the converter now reads
the staged copy, and the staged web patch holds **0** occurrences of the old name and **3** of the new one.

### The one remaining blocker is a REAL silent loss, not a flaky gate — and it is a config discrepancy

`verify` fails **G2** and **G8**. G8 is the accepted one-way door and is handled by
`promote-reading.mjs`. **G2 is a genuine finding**, checked by hand rather than taken on faith:

```
our 5 web-profile targets: typert-gateway, connection, remote-fanout, tool-subagent-remote,
                           agent-preset-registry            intent {config:{default:"zabz"}}
the composed staged tree:  row agent-preset-registry exists, name @deepseek-ai/dsh-agent-preset-registry,
                           config {"default":"standard"}
```

So the entry that makes **`zabz` the default preset does not apply.** The cause is a discrepancy between
two copies of the web profile patch:

| file | lines | declares the `agent-preset-registry` target |
|---|---|---|
| `profiles/web/cordis.patch.yml` (repo) | 1624 | **yes**, at line 278 |
| `~/.dsh/profiles/web/cordis.patch.yml` (live) | 252 | **no** |

`consumed.json` reads patch targets from the repo AND the home, so G2 knows about the target; the composed
tree is the STAGED home's composition, built from the live 252-line file, which never declares it. Hence
"carries no patch attribution from ANY layer". The commit that pinned the presets back to the 0.1.5 names
on 2026-10-04 said the same thing in its own message: the profiles scope "is NOT pinned here: publishing it
would replace the live" file.

**This is the same finding `settings-effective` makes from the other end**: of 108 settings keys this
deployment sets, 0.2.0-rc.2 reports **11 ABSENT and 4 with a different value** (against 0.1.5-rc.3's
`absent=0 different=0`). One of them is the default-preset key. So an upgrade taken today would silently
change which preset a new session uses and drop eleven settings keys — behaviour changes, not crashes, and
exactly what the owner meant by "without breaking anything".

**Do not promote 0.2.0-rc.2 until the live/repo web-patch discrepancy is resolved and the 15 settings
BREAKS are read one by one.** Neither is a pipeline defect; both are configuration questions about which
of two divergent copies is authoritative.

### What is still missing before this can be promoted

* **`switch-engine.ps1` precondition 2 is a GREP, not a proof.** It checks that
  `.agent-presets/*/agent.cordis.yml` names `@deepseek-ai/dsh-workflow-ptc` — but on 0.1.7+ that
  directory is **not read at all**. A staged home can pass that check while the presets are dead on the
  target engine, and dead presets break **new session creation** — the 2026-10-04 incident, whose
  symptom is the workspace picker bouncing back with `agent-preset/invalid`. The check has to become a
  composed-tree assertion: the candidate must compose our presets as rows with their plugins.
* **Nothing in the repo builds the staged home** that precondition 2 requires. It was assembled by hand
  and by test fixtures. A builder is in flight on branch `fleet/dsh-stagehome`.

## 0.1.5-rc.3 — SAFE. Nothing breaks.

*(SUPERSEDED for the `verify` row — see the 2026-10-05 section above. The stored `verify.json` is stale
and carries no G8; `analyze` now reports BREAKS=3 because of the repo's half-migrated profile patch.)*


| step | result |
|---|---|
| `check` | 26 published versions; 7 newer than the pin |
| `fetch` | 25,464 files / 214.1 MB, 59.3 s, into an isolated prefix |
| `analyze` | **SAFE** — `BREAKS=0 RISKY=0 CAPABILITY=0 INFO=57`; 240 packages |
| `patch-effect` | **SAFE** — all 4 host patch targets verified, `unverified: nothing` |
| `verify` | **pass=true, complete=true** — G1-G5 ok in 4.4 s; G5 = a real headless turn, model replied `OK` |

Ground truth by hand: 163 rows in both versions, **no rows added or removed**, all four patch
targets identical (`typert-gateway`, `connection`, `remote-fanout`, `tool-subagent-remote`).

**Verdict: no reason not to move to it — but almost no reason to bother.** It is one prerelease step
on the same line, and the plugin packages already resolve to `0.1.5-rc.2` today.

## 0.1.7-rc.1 — BREAKS. Do not promote without changes.

`analyze` → **`BREAKS=2 RISKY=4 CAPABILITY=59 INFO=53`**. 277 packages (43 added, 6 removed), 188
composed rows (vs 163). `patch-effect` is **SAFE** — the patch layer is fine; the breakage is in what
our **preset and mesh-profile rows name**.

### The two breakages, verified against the fetched install by hand

Both are `B1`, `AUTHORITATIVE`, `BREAKS`.

1. **`@deepseek-ai/dsh-agent-presets` no longer exists.** Named by
   `~/.dsh/profiles/mesh/cordis.patch.yml:69` (and the repo copy `profiles/mesh/cordis.patch.yml:69`).
   A composition row naming an uninstalled package **fails to resolve at mount** — in the mesh host
   composition that can take the boot down.
2. **`@deepseek-ai/dsh-workflow-worker-thread` no longer exists.** Named by **all three of our
   presets**: `presets/zabz/agent.cordis.yml:432`, `yocheved:370`, `cordis-bg:276` (and the live
   copies under `~/.dsh/.agent-presets/`). This breaks **session creation** on those presets.

Confirmed by direct filesystem check, not by inference: the two directories are absent from
`vendor/prefix/0.1.7-rc.1/node_modules/@deepseek-ai/`, and `contract.json`'s package map agrees.

### What upstream renamed them to

Removed (6): `cordis-plugin-hmr`, `dsh-agent-presets`, `dsh-code-runtime`,
`dsh-code-runtime-worker-thread`, `dsh-settings-file`, `dsh-workflow-worker-thread`.

Added (43), of which these are the ones that matter to us:

| removed | what appeared instead |
|---|---|
| `dsh-agent-presets` | **`dsh-agent-preset`** and **`dsh-agent-preset-registry`** (singular, plus a registry) |
| `dsh-workflow-worker-thread` | **`dsh-workflow-ptc`**, `dsh-ptc-runtime`, `dsh-ptc-runtime-node` |
| `cordis-plugin-hmr` | **`dsh-hmr`** |
| `dsh-settings-file` | `dsh-config-editor` |

### The one-way door — this is the most important line in this file

**`@deepseek-ai/dsh-session-format-v3-to-v4` is new in 0.1.7-rc.1.** There is no v4→v3 codec in the
added or removed lists. The live home holds **1,095 session logs, all `session.v3.jsonl.zstd`**
(`dsh-session-format-catalog` declares `currentVersion: 3`).

So promoting `0.1.7-rc.1` upgrades the session log format and **rolling back to a 0.1.5-line engine
would then be unable to read the logs written after the upgrade**. That is not a reason to refuse —
it is a reason to decide deliberately, and it is exactly what `SPEC.md` C8 predicted and gate G8
(not yet implemented) is meant to catch automatically.

### Risky, and worth reading

- **`@deepseek-ai/dsh` lost `exports["."]` and its `dsh.configTrees` block** (`{}` in 0.1.7-rc.1),
  gaining `./lib/*` and `./profile-boot`. The `configTrees` mount is how the shipped preset roster is
  found, so this is a structural change to preset discovery.
- **`@deepseek-ai/dsh-web-app` now ships per-preset patches** and its `dsh.bundle.patch` became an
  **array**: `["./cordis.patch.yml", "./presets/standard.patch.yml", "./presets/ptc.patch.yml",
  "./presets/minimal.patch.yml", "./presets/cordis.patch.yml"]`. Our `dsh.profile.bundles` lists
  this bundle, so it is in the composition path.
- **`@deepseek-ai/dsh-tool-cordis` gained `./host`.**
- 59 capability gains, including `dsh-plugin-manager`, `dsh-config-editor`, `dsh-client-ui-slots` and
  a large `dsh-experimental-speech-to-text` / voice-input group.

### What to do before promoting 0.1.7-rc.1

1. Re-target `profiles/mesh/cordis.patch.yml:69` from `@deepseek-ai/dsh-agent-presets` to whichever
   of `dsh-agent-preset` / `dsh-agent-preset-registry` carries the registry the row needs.
2. Re-target the `dsh-workflow-worker-thread` row in all three presets to the new workflow runtime,
   or set `disabled: true` and keep the row so the intent survives.
3. Decide explicitly about the session-format upgrade and the loss of a clean rollback.
4. Re-run `analyze` + `patch-effect` after (1) and (2); `patch-effect` should stay SAFE and the two
   `BREAKS` should disappear.

## 0.1.7 removed local preset directories — the migration, verified

Measured 2026-09-28 against `vendor/prefix/0.1.7-rc.2`. This section answers item **2** of the
`0.1.7-rc.1` action list above. The conclusion: our three presets move to 0.1.7 **mechanically**,
the converter that does it is committed together with the output it generates, and the output was
composed by the candidate engine with the rows arriving intact. Nothing here was promoted; this is
preparation.

### The measurement: preset-directory discovery is gone

Baseline is the live 0.1.5 line — `@deepseek-ai/dsh` **0.1.5-rc.1** and
`@deepseek-ai/dsh-agent-presets` **0.1.5-rc.2**, versions read from their own `package.json`. It
declares a user-preset *directory* and builds a discovery root from it:

```
rg --no-ignore --hidden -n 'USER_PRESET_DIR' ^
  "$env:LOCALAPPDATA\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh-agent-presets" --glob '*.js'

lib/index.js:195           const USER_PRESET_DIR = ".agent-presets";
lib/index.js:1307          path: dshHomePath(USER_PRESET_DIR),
lib/invariant.js:194       const USER_PRESET_DIR = ".agent-presets";
lib/invariant.js:1284      path: dshHomePath(USER_PRESET_DIR),
lib/types/discovery.js:48  export const USER_PRESET_DIR = '.agent-presets';
lib/types/index.js:63,188  import … / { path: dshHomePath(USER_PRESET_DIR), trust: 'user' }
```

Candidate `0.1.7-rc.2`, over the **whole fetched install** — 7,338 `.js` files
(`rg --no-ignore --hidden --files --glob '*.js' <node_modules> | Measure-Object -Line`):

```
rg --no-ignore --hidden --glob '*.js' -c '\.agent-presets' ^
  dsh-update\vendor\prefix\0.1.7-rc.2\node_modules                      -> exit 1, no match
rg --no-ignore --hidden --glob '*.js' -c ^
  'USER_PRESET_DIR|presetRoot|presetDir|customPreset|userPreset' ^
  dsh-update\vendor\prefix\0.1.7-rc.2\node_modules                      -> exit 1, no match
rg --no-ignore --hidden --glob '*.js' -c 'dshHomePath' ^
  dsh-update\vendor\prefix\0.1.7-rc.2\node_modules                      -> exit 0, matches in
                                      @deepseek-ai/dsh-app-boot and @deepseek-ai/dsh-home-paths
```

The third command is the control, and it matters: `vendor/` is git-ignored
(`dsh-update/.gitignore:22`), so a default `rg` returns "no matches" there for a reason that has
nothing to do with DSH. With `--no-ignore` the tree is demonstrably read, the control matches, and
the two real queries are empty. **Two empty reads with a matching control is the claim.**

The replacement package has no filesystem access at all:
`rg --no-ignore -n 'readdir|readFile|existsSync|node:fs' …/@deepseek-ai/dsh-agent-preset-registry`
→ **exit 1, no match in any file**. It takes definitions programmatically instead:
`lib/index.js:500 async register(definition)`, keyed by `lib/index.js:476 definitions = new Map()`,
with `lib/index.js:472 default: z.string().required()` as the registry's own **row** config.

### The target row format, read off the candidate engine

`dsh --profile web --dump-config` under 0.1.7-rc.2 composes **193 rows, exit 0** — the live
`~/.dsh/profiles/web` tree, still 0.1.5-era, composes cleanly enough to be inspected — and contains
exactly four preset rows:

| row id | `name` | `config.id` | `config.order` | `plugins` |
|---|---|---|---|---|
| `preset-standard` | `@deepseek-ai/dsh-agent-preset` | `standard` | 1 | 19 |
| `preset-ptc` | `@deepseek-ai/dsh-agent-preset` | `ptc` | 2 | 20 |
| `preset-minimal` | `@deepseek-ai/dsh-agent-preset` | `minimal` | 3 | 2 |
| `preset-cordis` | `@deepseek-ai/dsh-agent-preset` | `cordis` | 4 | 20 |

The row's own schema is `@deepseek-ai/dsh-agent-preset/lib/index.js` —
`id: z.string().required()` (:14), `order: z.number()` (:17),
`plugins: z.array(z.any()).required()` (:18), with `static [EntryGroup.key] = true` (:12). And the
`plugins` array is **the same shape as our preset files**: `persona`, `agent-instructions`,
`tool-bash`… with `{id, name, config, disabled}` maps and `cordis:group` groups carrying a nested
`config:` list. That is what makes this conversion mechanical.

`insert:` is the correct vehicle, from `@deepseek-ai/dsh-app-boot/lib/index.js` — the patch
algorithm `--dump-config` and boot share (`applyEntryPatches`, :61): `if (insert)` (:74) with **no
`id`** does `data.push(...insert)` (:87), so it appends to the patch root and needs no existing row
to target; only a non-insert patch without an `id` warns (:92). `insert` is declared as an entry
list (:2758 `properties: { insert: ref("entryList") }`).

### What the converter emits

`scripts/make-preset-rows.mjs` reads each `presets/<name>/agent.cordis.yml` and writes
`profiles/web/presets.generated.patch.yml` — one `- insert:` patch entry per preset, each holding
one `preset-<name>` row whose `config.plugins` is that preset's own row list.

```
node scripts/make-preset-rows.mjs
  order rule: 10 + index in ascending name order over all 3 discovered preset(s)
  preset-cordis-bg  id=cordis-bg  order=10  plugins=19  !!js=4
  preset-yocheved   id=yocheved   order=11  plugins=20  !!js=4
  preset-zabz       id=zabz       order=12  plugins=26  !!js=11
  !!js expressions carried: 19; self-check: PASS
  wrote profiles/web/presets.generated.patch.yml (78758 bytes, 943 lines)
```

The order rule is `10 + index`, because the four shipped presets take 1-4. The index is the position
in **ascending name order over the whole discovered set**, and deliberately not over the emitted
subset: `--names zabz` still writes `order: 12`, so filtering never renumbers a preset.

`--check` compares the committed file with what would be generated and writes nothing; the file's
header says GENERATED, names the converter, and carries the `sha256` of every source it read. No
timestamp is recorded, so the output is byte-stable and `--check` can be a gate. Verified that the
gate can fail: pointed at a one-line hand edit it exits 1 with `first difference at line 1`.

### `YAML.stringify` + `customTags` cannot write `!!js` — measured, and worked around

This is the trap that would have made the migration look successful while destroying platform gating.

```
node -e "… YAML.stringify({a:{__js:\"process.platform === 'win32'\"}}, {customTags: CUSTOM_TAGS})"
  a: !!js undefined                     <- and re-parsing that yields the STRING "undefined"
```

Measured with yaml 2.9.0: the tag's `stringify` is called **once**, it receives the `{__js}` wrapper,
and **its return value is discarded** — an idempotent variant and `defaultStringType: 'PLAIN'` both
produce the same `!!js undefined`. On the read path the tag is fine; only the write path is broken.
The converter therefore swaps each wrapper for a unique sentinel string, stringifies, and
substitutes `!!js <source text>` back textually — which is why the expression text can be
byte-identical to the source rather than merely equivalent.

Every emission is then re-parsed with the unmodified parser and compared against the input before
anything reaches disk; a mismatch is a hard error. That check is not decoration: it fired on the
first run of this converter (a missing substitution call) and refused to write.

### The round-trip result

`dsh-update/tests/preset-rows/verify-preset-rows.mjs` — three independent checks, all passing:

| check | result |
|---|---|
| emitted `plugins` vs source row list, per preset | 19/19, 20/20, 26/26 rows; **ids identical and in the same order**; differing ids: none; whole row list **deep-equal: true** (structure, keys and values, not just ids) |
| `!!js` source text in the emitted bytes | 19 source expressions, **19 present verbatim**, 0 missing, **0 occurrences of `!!js undefined`** |
| the candidate engine composes it | `--patch profiles/web/presets.generated.patch.yml` → **exit 0, 196 rows** (193 + our 3); all three rows present with `config.plugins` **deep-equal to the source preset** |

The rows are attributed in the dump's own provenance comment, immediately above the first of them:

```
# == C:\Users\ezabz\Code\harness-config\profiles\web\presets.generated.patch.yml
- id: preset-cordis-bg
  name: '@deepseek-ai/dsh-agent-preset'
  config:
    id: cordis-bg
    order: 10
    plugins:
      - id: persona
```

and a gated row survives as text rather than as `undefined`
(`presets.generated.patch.yml:78`):

```
disabled: !!js process.platform === 'win32'
```

### The exact commands

```
node scripts/make-preset-rows.mjs                 # write profiles/web/presets.generated.patch.yml
node scripts/make-preset-rows.mjs --check         # exit 0 when committed output is up to date

node dsh-update/lib/compose.mjs --profile web ^
  --bin dsh-update\vendor\prefix\0.1.7-rc.2\node_modules\@deepseek-ai\dsh\lib\bin.js ^
  --patch profiles/web/presets.generated.patch.yml ^
  --out %TEMP%\verify.json --log-dir %TEMP%\logs

node dsh-update/tests/preset-rows/verify-preset-rows.mjs --tree %TEMP%\verify.json
```

Runtimes on ZABZ-YOGA, node v24.19.0: converter 0.13 s; `--check` 0.14 s; the compose above 0.39 s
of which the engine reports 152 ms; the verifier with `--tree` 0.13 s (with `--bin` it also runs the
compose, so about 0.5 s). Node start-up dominates every one of them.

### What this does NOT settle — read before promoting

1. **The registry row's `default` is a second, separate change.** 0.1.7's default is
   `default: z.string().required()` on the `agent-preset-registry` ROW (`lib/index.js:472`), and the
   composed web tree's registry row reads `config.default: standard` (raw dump line 616). Rows alone
   do not make `zabz` the default; that row must name it too. The row is shipped by upstream's
   `dsh-web-app` bundle, so it is patched, not authored — and it is outside what this converter
   owns, so it is recorded here rather than done.
2. **Nothing applies this file yet.** A profile's patch layers are its bundles' `dsh.bundle.patch`
   files plus its own `cordis.patch.yml`; `profiles/web/package.json` names eleven bundles, and a
   second loose file in the profile directory is not one of them. Neither `scripts/sync.py` nor
   `multi-window/dshw.ps1` mentions `--patch` at all (both searched, no match). So the layer that
   carries these rows still has to be wired — by a launcher `--patch`, by a bundle declaring it, or
   by `sync.py` folding it into the profile patch — and that wiring belongs to whichever of those
   files owns it. The generated file composes correctly when passed explicitly; it is simply not
   passed by anything today.
3. **`baseUrl` no longer means "the preset's own directory", and our `skill-filesystem` rows depend
   on it.** Our three presets pass
   `customSkillDirs: [!!js "… fileURLToPath(new URL('skills/', baseUrl))"]`. The registry mounts a
   preset with `mountPreset(scope.ctx.extend({ baseUrl: record.context.baseUrl }), …)`
   (`dsh-agent-preset-registry/lib/index.js:534`) — that is the **declaring patch layer's** base
   (`cordis-plugin-loader` sets `ctx.baseUrl` from the Loader config, :596), not `presets/<name>/`.
   So on 0.1.7 those skill directories most likely resolve somewhere other than the preset's own
   `skills/`, and the bundled `editing-cordis-compositions` / `cordis-plugin-development` /
   `parallel-agent-orchestration` skills would not be found. **This is derived from the code paths
   and is NOT verified end-to-end** — proving it needs a real session mount, and no engine was
   started for this work. It is the first thing to test after the rows land.
4. **`presets/<name>/preset.yml` is not carried.** That file holds the display `name` and
   `description`, which `AgentPreset.Config` accepts, but the emitted row is exactly
   `{id, order, plugins}` — the shape the four shipped rows use — so the roster will show preset ids
   rather than the written names until a row carries them.
5. **Nothing was mounted and no session was created.** `--dump-config` composes and reports; it does
   not activate a preset. The proof here is that the rows compose with the right contents, not that
   an agent runs on them.
6. The two `BREAKS` from the `0.1.7-rc.1` section look **already addressed in this working tree**,
   which is why re-running `analyze` is the next step rather than assuming either way:
   `profiles/mesh/cordis.patch.yml` now names `@deepseek-ai/dsh-agent-preset-registry` and explains
   the rename at lines 25-41 (the plural name survives only inside that comment), and all three
   presets declare `workflow-ptc` / `@deepseek-ai/dsh-workflow-ptc` (`zabz:455`, `yocheved:371`,
   `cordis-bg:288`), with `workflow-worker-thread` appearing only inside `cordis-bg`'s comment at
   line 275.

## Not yet examined

`0.1.5-rc.2`, `0.1.6-alpha.1`, `0.1.6-alpha.2`, `0.1.7-alpha.1`, `0.1.7-alpha.2`. One
`fetch` + `analyze` + `patch-effect` each answers them.

## Nothing has been promoted

`multi-window/windows.json` is byte-identical to before this work
(sha256 `765B8F65CFFEA6F277C99E7C4DE45147C13CE5ED17B9454E1A21E112D7798E1A`, no `dshInstall` key), and
the live engine on port 3099 was never started, stopped or restarted.


### 2026-10-05 (round 2) — the repo web patch is on the CRITICAL PATH, and the live profile layer is two weeks stale

Two facts discovered by chasing the G2 failure, both measured:

1. **The live profile layer is stale, and the guard did it on purpose.** The repo's
   `profiles/web/cordis.patch.yml` is 1624 lines with 45 patch entries; the live
   `~/.dsh/profiles/web/cordis.patch.yml` is 252 lines with **4** entries and has not been written since
   **2026-09-20 12:32:31**. `scripts/check-version-coupled-config.py` refuses to publish the profiles
   scope while the running engine lacks the 0.1.7 names, and this repo's web patch has named them since
   about then — so every repo-side profile change in that fortnight (mesh placement, prefer-remote, the
   dispatch-hop timeouts, the provider `targetHosts` default) was correctly SKIPPED and never reached
   this machine. The guard did its job; the consequence is that the live web profile is 41 entries
   behind the repo.

2. **The repo web patch cannot be avoided, because the switch requires it.** `switch-engine.ps1` FIX 3
   treats `presets: SKIPPED` / `profiles: SKIPPED` as a FAILURE OF THE SWITCH and rolls back — its own
   reasoning being that a half-applied switch is the state it exists to prevent. So the switch only
   succeeds if `scripts/sync.py` reports `version check passed` for BOTH coupled scopes, which means
   **sync publishes the repo's web patch during the switch**. Staging the profile layers from the live
   home therefore produces a composed tree that is not the post-switch state — which is the true reason
   G2 says our `agent-preset-registry` entry is lost.

Two fixes landed in `lib/stage-home.mjs`, both correct and both verified not to regress the proven path
(its own suite is still 109/109, and staging from live still builds):

* **The converter spells its provenance line two ways and the tool accepted one.** `--install` mode emits
  ``# Written by `node scripts/make-preset-rows.mjs --install` ``; file mode emits
  ``# Written by `scripts/make-preset-rows.mjs` ``. The old constant was the second verbatim, so the
  `node ` inside the backticks made the tool REFUSE to splice over the repo's own generated block, with
  the message "a block without that line was hand-edited, and installing over it would hide that" —
  true of neither. That was a guard rejecting the tool's own output.
* **`--profiles-from <dir>`** so the staged home can take its profile layers from the repo (the
  authoritative copy) instead of the stale live one, taking only profiles this machine already has —
  the same rule `sync.py` applies when it reports `profile <name>: not present on this machine -- skipped`.

**IT IS NOT YET USABLE, and that is the next piece of work.** Staging from the repo now fails on a real
limitation of the splicing code: `internal check failed: the entries outside the block are not the same
entries, in the same order, after the splice`. The repo's web patch holds **two** managed blocks
(`mesh-provider-install` at lines 80-251 and `preset-rows` at 284-END) and its entries are written in
flow style. Both files' markers are balanced (BEGIN 1 / END 1 each) and the top-level closing bracket is
intact, so this is not a malformed file — `spliceManagedBlock`'s invariant has never been exercised on a
patch file that carries two managed blocks at once. It must be fixed with a test that reproduces exactly
this shape, because it decides which configuration the switch installs.


### 2026-10-05 (round 3) — PREFLIGHT IS GO, and the settings gate immediately found 15 real silent losses

```
VERDICT: GO — 7 blocking guard(s) all green.
  PASS baseline fresh / analyze (RISKY, BREAKS=0) / patch-effect SAFE / preset-gate SAFE
  PASS verify (7 gates ran, only G8 failed and it was explicitly accepted)
  PASS G8 door / PASS artifact provenance
  GAP  settings-effective  BREAKS: absent=11 different=4 of 108 keys
```

This is the first time this pipeline has reached GO for a session-format candidate. It is the direct
result of the promote/preflight deadlock fix: `verify` now reports "7 gate(s) ran and passed; not run:
none; the only failure is G8 ... and it was explicitly accepted", which is exactly the reading
`promote-reading.mjs` exists to produce.

Three more defects were fixed to get here, all in `lib/stage-home.mjs`:

* **`spliceManagedBlock` could not handle a patch file carrying TWO managed blocks.** The repo's web
  patch holds `mesh-provider-install` (80-251) and `preset-rows` (284-END) together. The `replace` branch
  dropped every element matching the NEW generated entries in order and called the remainder "outside" —
  which cannot work, because `YAML.parse` groups a flow-style block body differently from the way a human
  names its entries (the code already recorded a correct splice refused as "7 vs 1331" for that reason).
  Then, after that fix, `outside` derived from `oldCount` produced the same class of FALSE refusal
  ("would lose 1 entry(ies) ... (preset-cordis-bg)") because the count is smaller than the number of
  entries a reader would name. "Outside" is now computed from the OLD BLOCK BODY itself — parse the body
  between the markers, remove those entries, require the rest to survive — with no count and no
  grouping assumption. Guarded by `tests/stage-home/two-block-splice.mjs`, 11/11, which reproduces the
  exact two-block shape; `tests/stage-home/run.mjs` is still 109/109.
* **The converter spells its provenance line two ways and the tool accepted one**, so it refused to
  splice over the repo's own converter-generated block (see the round-2 section).
* **`--profiles-from <dir>`** added, so the staged home carries the repo's authoritative layers (45 patch
  entries) instead of the stale live copy (4), restricted to profiles this machine has — the rule
  `sync.py` itself applies.

### WHY THE ENGINE HAS NOT BEEN FLIPPED: the settings losses are not cosmetic

The 15 breaks name, in the words of the engine's own `POST /api/settings/describe` report:

| key | what the engine resolved |
|---|---|
| `llm-pi-ai.providers.deepinfra.api` | absent — our value `"openai-completions"` is discarded |
| `llm-pi-ai.providers.deepinfra.apiKeyEnv` | absent |
| `llm-pi-ai.providers.deepinfra.baseURL` | absent |
| `llm-pi-ai.providers.deepinfra.models[].id` / `.name` | absent — **an entire model provider's configuration** |
| `llm-deepseek.retryPolicy.mode` / `.maxRetries` | absent — retry semantics revert to schema defaults |
| `llm-deepseek.retryPolicy.backoff.initialDelayMs` / `.jitterRatio` / `.maxDelayMs` | absent |
| `permission.defaultPreset` | absent — **the permission posture silently reverts to a schema default** |
| `agent-loop.maxParallelToolCalls` | present with a DIFFERENT value |
| `llm-deepseek.maxTokens` | present with a DIFFERENT value |
| `llm-deepseek.streamIdleTimeoutMs` | present with a DIFFERENT value |
| `ui-conversation.busyEnter` | present with a DIFFERENT value |

The consumers are our own layered settings — `settings/base.yaml:128` and
`settings/machines/{DESKTOP-FGV6KMH,LAKEWOOECHSMINI,ZABZ-YOGA}.yaml` — so these are OUR values, declared
in the repo, that 0.2.0-rc.2 no longer honours at those paths. Promoting on this evidence would silently
change model-provider routing, the permission preset, retry behaviour and the tool-concurrency and
call-bound limits on the machinery that runs the company. That is a loss, and "without breaking
anything" rules it out.

**This gate is non-blocking only because its false-failure rate was unmeasured when it was wired.** It has
now earned its keep on its first real run, and the next session should make `absent == 0 for keys this
deployment sets` a BLOCKING condition — otherwise the one guard that can see this class of loss is the
one guard that cannot stop a promote.

### The remaining work, in order

1. For each absent key, find where 0.2.0-rc.2 moved it — the artifact carries the engine's resolved
   namespaces, so this is a mechanical diff of our key paths against the engine's own shape, not a guess.
   Likely a rename or a restructure of `providers` in `llm-pi-ai` and of `retryPolicy` in `llm-deepseek`.
2. Update `settings/base.yaml` and the three `settings/machines/*.yaml` layers to the new paths.
3. Re-run `verify` + `settings-effective` until `absent == 0` for keys we set; then re-run preflight.
4. `node dsh-update/tools/backup-state.mjs` -> a `BACKUP-REPORT.json` younger than 12 h.
5. `switch-engine.ps1 -Version 0.2.0-rc.2 -StagedHome C:\Users\ezabz\.dsh-staged\0.2.0-rc.2 -BackupDir <dir>
   -AcceptSessionFormatUpgrade -IUnderstandThisWritesTheLiveHome`.
6. After the next boot: the new version serves, a NEW session mounts each preset, an existing session
   opens. Still unproven: whether `skills/` inside our presets resolves under 0.1.7+ (FINDINGS item 3).


### 2026-10-05 (round 4) — THE SETTINGS ARE NOT READ ON 0.2.0-rc.2 AT ALL, and that closes STATE-COMPAT §3.5

The 15 `settings-effective` breaks are not renamed keys. **Every path our settings use is valid on
0.2.0-rc.2; the READER moved.** Measured:

| | 0.1.5 line | 0.2.0-rc.2 |
|---|---|---|
| `@deepseek-ai/dsh-settings-file` | **present** — `lib/index.js:32` reads `resolveDshHome(config.dshHome)/settings.yaml` | **ABSENT** |
| `@deepseek-ai/dsh-settings` | — | `lib/index.js:339-348` only has `importLegacyDocument()`, reading `join(profile.home, "settings.yaml")` — the ACTIVE PROFILE's home |

This deployment has no `profiles/*/settings.yaml` and its settings live in `~/.dsh/settings.yaml`, the
harness home. On 0.2.0-rc.2 nothing opens that file. **So all 108 keys revert to schema defaults or
disappear** — which is exactly the shape of the two findings: keys WITH a schema default resolve to the
default (`maxTokens` 256000 vs our 65536, `streamIdleTimeoutMs` 300000 vs our 60000,
`maxParallelToolCalls` 10, `busyEnter` `"queue"`), and keys with NO schema default come back ABSENT
(`retryPolicy`, `permission.defaultPreset`, and the five `llm-pi-ai.providers.deepinfra.*`).

STATE-COMPAT.md §3.5 asked this question and left it open in its own words: *"settings.yaml is SAFE as a
file, but the reader moved … Whether the values still take effect is a separate question and is not
answered here."* It is answered now: **they do not.**

**The paths are fine.** Verified against the candidate's own `--dump-config-schema`:
`llm-deepseek.retryPolicy` accepts `mode`/`maxRetries`/`retryableCodes`/`backoff`; `permission` accepts
`defaultPreset`; `agent-loop` accepts `maxParallelToolCalls`; `ui-conversation` accepts `busyEnter`;
`llm-pi-ai.providers` is an open `additionalProperties` map whose entries accept
`apiKeyEnv`/`api`/`baseURL`/`models`/`retryPolicy`/`streamIdleTimeoutMs`. `deepinfra` does not appear
literally in the schema because providers are an open map — that is expected, and it is NOT evidence that
the provider is unsupported.

**Two structural changes worth knowing:**
1. The single `@deepseek-ai/dsh-llm-deepseek` row became **two**:
   `@deepseek-ai/dsh-llm-deepseek-api-key` (row id `llm-deepseek`, `/92`) and
   `@deepseek-ai/dsh-llm-deepseek-account` (row id `llm-deepseek-account`, `/93`), both declaring
   `llm-deepseek` settings. Our `settings/base.yaml` comments cite `dsh-llm-deepseek/lib/index.js` line
   numbers that no longer describe what runs.
2. `dsh-llm-retry` is its own row (`/18`) and `lib/index.js:28` throws
   *"llm-retry: retryPolicy belongs under each provider configuration"* — so a top-level `retryPolicy` is
   rejected by that package's own guard even though `llm-deepseek`'s schema still declares one.

**The fix, therefore, is not a rename.** Our settings must be delivered where 0.2.0 reads them: a
**profile-scoped** settings document (the settings row's own `config`, reached through the profile's patch
layer), not the harness-home `settings.yaml`. That is the work item, and it is a real migration rather
than a find-and-replace.

**New tool, so this is mechanical next time:** `dsh-update/tools/settings-map.mjs` — reads a candidate's
`--dump-config-schema`, and prints, per key, the owning NAMESPACE, the owning PACKAGE, the row path, and
the candidate schema's own DEFAULT. The schema's top-level `x-cordis.entries` is the roster that maps
every `#/$defs/configN` back to `{path, id, name, status, configRef}`, which is what makes "which row owns
this key" answerable at all. Read-only; starts nothing.

```
node dsh-update/tools/settings-map.mjs <schema.json> [--keys a,b,c] [--namespace <id>] [--json]
```


### 2026-10-05 (round 5) — WHERE SETTINGS ACTUALLY LIVE ON 0.1.7+, and the row each of our sections belongs to

**The mechanism, read from the candidate's own code.** On 0.1.7+ the settings document is
`configEditor.documentPath`, and that getter is

    dsh-config-editor/lib/index.js:24-26
      get documentPath() { return this.ownerContext.profileContext.patchPath; }

— i.e. **the profile's own `cordis.patch.yml`**. `dsh-settings`'s one other path,
`importLegacyDocument()` (`lib/index.js:346-363`), is a ONE-SHOT migration: it reads
`join(profile.home, 'settings.yaml')`, RENAMES it to `.imported`, then calls `update(section, values)` per
section. So a `settings.yaml` is not a store on this line; it is an input to a one-time import, and the
store is the profile patch.

**Refuted first, so it is not believed by accident.** Dropping the merged document at
`profiles/web/settings.yaml` and re-running `settings-effective` changed NOTHING — identical
`absent=11 different=4 present=2`. That path is not the mechanism.

**Our nine sections, and the row each belongs on.** Seven of the nine namespaces are already rows in the
composed 0.2.0-rc.2 web tree; the other two are renames upstream states in its own
`LEGACY_SECTION_ENTRIES` (`dsh-settings/lib/index.js:302-308`):

| settings.yaml section | row id | |
|---|---|---|
| `ui-onboarding` | `ui-settings-general` | renamed, upstream's own table |
| `ui-conversation` | `ui-conversation` | direct |
| `permission` | `permission` | direct |
| `agent-default-model` | `agent-default-model` | direct |
| `agent-presets` | `agent-preset-registry` | `config.default`; the repo patch already declares it |
| `llm-deepseek` | `llm-deepseek` | direct |
| `llm-pi-ai` | `llm-pi-ai` | direct |
| `spend-guard` | `spend-guard` | direct — OUR plugin, and it carries the spend ceilings |
| `agent-loop` | `agent-loop` | direct |

The document is small (1,087 bytes) but it is not cosmetic: `permission.defaultPreset:
danger-full-access`, `agent-presets.default: zabz`, and `spend-guard` `warnUsd 35 / fanoutUsd 80 /
ceilingUsd 150 / concurrencyCap 12 / onInternalError closed`. Money controls and the permission posture.

**The constraint that stopped this round, measured rather than assumed.** A profile patch is a **FLOW
collection** — it opens `[`, closes `]`, and its entries are flow mappings with TRAILING COMMAS:

    {
      id: 'agent-preset-registry',
      config: {
        default: 'zabz',
      },
    },

Emitting block-style entries (`- id: 'x'` plus an indented `config:`) is invalid inside a flow sequence,
and the engine rejects the whole overlay:

    dsh: failed to parse overlay .../profiles/web/cordis.patch.yml
         YAMLException: missed comma between flow collection entries (1622:3)

`dsh-update/tools/settings-to-entries.mjs` is NEW and its `--print` mode is correct and useful — it
performs exactly the section→row mapping in the table above, which is the analysis that was missing — but
`--install` is **fail-closed** until the emitter emits flow style. It is not a string tweak: nested
content (`llm-deepseek.retryPolicy.backoff`, `llm-pi-ai.providers.deepinfra.models[]`) cannot be block
style inside a flow mapping at all, so the block body needs a real YAML stringifier with `{flow: true}` on
every node. `scripts/make-preset-rows.mjs` already solved that exact problem for the preset rows and its
emitter is the thing to reuse rather than re-invent.

**Damage contained, and said plainly.** Installing the block-style entries into the STAGED home's web
patch broke its composition; `compose.mjs` caught it immediately (`exit 1`, 0-byte dump). The staged home
was re-staged from the repo and composes cleanly again — **197 rows, exit 0**. No live path was written at
any point; the live profile patch still carries its 2026-09-20 mtime.


### 2026-10-05 (round 6) — THE SETTINGS MIGRATION WORKS, and G2 is now the only blocker

**The settings story is closed.** Delivered as `config:` entries in the profile patch (round 5's finding),
installed into `profiles/web/cordis.patch.yml` and `profiles/mesh/cordis.patch.yml` by the new
`dsh-update/tools/settings-to-entries.mjs`. Measured before/after on the engine's own
`POST /api/settings/describe` report, against a staged home rebuilt FROM THE REPO:

```
before:  present=2  absent=11  different=4  BREAKS=15
after :  present=17 absent=0   different=0  BREAKS=0
```

and the composed tree carries them: `permission.defaultPreset danger-full-access`,
`agent-preset-registry.default zabz`, `llm-deepseek.maxTokens 65536` / `streamIdleTimeoutMs 60000`,
`spend-guard.ceilingUsd 150` / `concurrencyCap 12`, `agent-loop.maxParallelToolCalls 20`,
`ui-conversation.busyEnter steer`, `agent-default-model.model deepseek-flash`,
`llm-pi-ai.providers.deepinfra.baseURL https://api.deepinfra.com/v1/openai`.

**The style constraint, measured twice.** `profiles/web/cordis.patch.yml` is a FLOW collection (`[`…`]`,
flow mappings, trailing commas) and `profiles/mesh/cordis.patch.yml` is a BLOCK sequence (no brackets,
`- id: x`). Block entries inside the flow file make the engine reject the whole overlay
(`YAMLException: missed comma between flow collection entries`), so the emitter DETECTS the style from the
target and emits accordingly. The `config` body is always stringified FLOW, because nested content
(`retryPolicy.backoff`, `providers.deepinfra.models[]`) cannot be block style inside a flow mapping.

**The `settings-effective` guard is now blocking** whenever it ran and found a loss — the rationale being
that a gate which can see this class of loss and cannot stop a promote turns a refusal into a footnote.
It stays non-blocking when it could not reach a verdict (`ran === false`), so the pipeline cannot become
unpassable for reasons unrelated to the candidate. On this run it PASSES, and its detail now reads
"every settings key this deployment sets is present in the engine's own report with our value".

### G2 is the last blocker, it is newly caused by the settings entries, and its LOST reading is suspect

```
G2: LOST (our patch silently stopped applying): agent-default-model,
    deepseek-ai/DeepSeek-V4-Flash-0731, deepseek-ai/DeepSeek-V4.1-Flash, spend-guard
    — of those, all four carry no patch attribution from ANY layer
    our-layer patched rows in this tree: typert-gateway, llm-pi-ai, permission, agent-loop,
    llm-deepseek, connection, ui-settings-general, ui-conversation, agent-preset-registry,
    remote-fanout, tool-subagent-remote
```

Three reasons to treat this as a G2 defect rather than a real loss, and they are all measured:

1. **The values are provably in force.** `spend-guard.ceilingUsd = 150`, `spend-guard.concurrencyCap = 12`
   and `agent-default-model.model = "deepseek-flash"` are read straight out of the composed tree
   (`tree.json`), and the engine's own describe report shows `absent=0 different=0`. A row whose resolved
   config IS our value has not "silently stopped applying".
2. **Two of the four "targets" are not rows at all.** `deepseek-ai/DeepSeek-V4-Flash-0731` and
   `deepseek-ai/DeepSeek-V4.1-Flash` are MODEL IDS out of `llm-pi-ai.providers.deepinfra.models[]`.
   `consumed.json` classified them as patch targets; no patch entry can ever target a model id.
3. **G2 keys its verdict on attribution**, and this pipeline's own README records that attribution is
   unstable between runs and must never key a verdict — the same run reports "the supplied artifact's
   patchedRowIds contains 12 id(s) the fresh dump does not attribute to our layer".

**The fix, for the next session, and it is a real one.** G2 should fail on the two things that are
checkable without attribution: a target ROW that is ABSENT from the composed tree, and a row whose
resolved value does not carry the intent recorded in `consumed.json`. Attribution becomes a reported
reading, not a verdict. It needs a test that reproduces this exact case — our-value-equals-the-row's-default
— because that is the shape that makes attribution blind while the configuration is perfectly in force.
`G8` in the same run is the accepted one-way door (2,258 live v3 logs, all counted), so it is not a
blocker once `verify`'s `pass` is read through `promote-reading.mjs`.
