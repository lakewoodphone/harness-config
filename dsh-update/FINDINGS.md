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
