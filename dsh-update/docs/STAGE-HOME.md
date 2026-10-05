# `dsh-update/lib/stage-home.mjs` — building the STAGED HOME a candidate engine boots on

`dsh-update/tools/switch-engine.ps1` is the one command that switches the engine and the config
together, and it refuses unless the staged home already carries the MIGRATED config
(PRECONDITION 2, `switch-engine.ps1:1101-1138`). That predicate is precise and greppable, and until
this module existed **nothing in the repo built a home that satisfied it** — it was assembled by hand
and by test fixtures, which is the class of artefact that silently rots. This is the builder.

```
node dsh-update/lib/stage-home.mjs --from <configHome> --candidate <prefix> --out <dir>
                                  [--profile web] [--check] [--json]
```

| flag | meaning |
|---|---|
| `--from` | the home to take the config surface from. Default `$DSH_HOME`, else `~/.dsh`. **Read only** — this module never writes a byte into it. |
| `--candidate` | the npm prefix holding the candidate engine, i.e. the directory that has `node_modules/@deepseek-ai/`. A `…/dsh/lib/bin.js` path is also accepted. |
| `--out` | the staged home to build. With `--check` it is compared against and **never written**. |
| `--profile` | the profile whose patch layer receives the preset rows. Default `web`. |
| `--check` | write nothing; exit non-zero if the committed staged home would differ, and still run the real assertion over the **committed** tree. |
| `--json` | print exactly one JSON object on stdout; progress goes to stderr. |

Exit codes: `0` ok, `1` refusal or drift, `2` usage error.

---

## 1. What it decides, and what it refuses to decide

The two coupled package names are **never hardcoded as the answer.** They are read from the
candidate prefix's own directory listing (`<candidate>/node_modules/@deepseek-ai/`), per slot:

| slot | the two names on either side of the version line | where the name lives in our config |
|---|---|---|
| `workflow-runtime` | `@deepseek-ai/dsh-workflow-ptc` (0.1.7+) / `@deepseek-ai/dsh-workflow-worker-thread` (0.1.5) | `presets/<name>/agent.cordis.yml`, copied to `.agent-presets/<name>/` |
| `preset-registry` | `@deepseek-ai/dsh-agent-preset-registry` (0.1.7+) / `@deepseek-ai/dsh-agent-presets` (0.1.5) | `profiles/*/cordis.patch.yml` |
| `preset-row` | `@deepseek-ai/dsh-agent-preset` (0.1.7+ only) | the generated preset-row block |

A slot is decidable only when **exactly one** of its names is installed. Both present, or neither,
is a refusal with the slot named — a row naming an absent package fails at mount, and a row naming a
present-but-wrong package fails silently and expensively later.

The names live in `SLOTS` in the module. **Which** name is the modern one is a property of the slot
(`modernName`), not of its position in the list: the registry slot's two names happen to be listed
legacy-first, and a `names[0] === side` test classified the modern registry package as the legacy one
and then reported our own rewritten file as still naming the removed package. Measured 2026-10-05.

**On the 0.1.5 side the module refuses.** 0.1.5 reads presets from the `.agent-presets` *directory*
and provides no `dsh-agent-preset` row plugin at all, so there is nothing for a generated row to
mount as. Emitting rows that name an absent package to make the tool "work in both directions" would
be trading a loud refusal for a silent loss of the persona — the exact failure `FINDINGS.md` warns
about. The 0.1.5 direction is a deliberate gap, not an oversight: it needs no builder, because a run
that stays on the running engine does not migrate anything.

## 2. What is copied, and what is not

A staged home is **config, not state**.

* Copied: `profiles/<name>/{cordis.yml,cordis.patch.yml,package.json,pnpm-workspace.yaml}`,
  `.agent-presets/**` (minus `node_modules`), `settings.yaml`, and the generated preset-row artefact.
* **Never copied**: `sessions/`, `storages/`, `attachments/`, `.credentials.yaml`, `metrics/`,
  `health/`, `node_modules` at any depth, and any `.bak-*` / `.pre-sync` sibling in a profile
  directory. Each exclusion is recorded in the manifest with its reason.
* The profile config surface is a **whitelist**, not "everything except `node_modules`": the live
  `~/.dsh/profiles/web/` holds about thirty `cordis.patch.yml.bak-*` and `package.json.bak-*` files,
  and a staged home that carries a directory of timestamped backups invites a future reader to
  compare against the wrong generation.

Two of those exclusions are measured, not stylistic. A staged `sessions/` makes gate G8 compare the
candidate against a staged corpus instead of the operator's real 1,256 logs
(`tests/guards/state-home.mjs`), and a recursive copy that follows the junctions inside
`profiles/node_modules` measured **127,970 files / 1.0 GB** for a tree whose real content is 884 KB
(`tests/switch/README-rework.md`).

### The one exception: the module ANCHOR, recreated as LINKS

`profiles/<name>/node_modules` **is** staged, but as **links**, never followed. The copy walks with
`lstat`, reproduces every symlink/junction to the same target, and recurses only into real
directories — skipping `node_modules` and `.pnpm` by name. Measured 2026-10-05: with the anchor
absent, the candidate composed the staged home to **185 rows** and said why in its own stderr, nine
times —

```
dsh: skipping profile bundle "dsh-plugin-attention": cannot resolve … from the dsh
installation or <staged>/profiles/web
```

— followed by `patch: entry "remote-fanout" not found` and `"tool-subagent-remote" not found`. Nine
of the eleven bundles `profiles/web/package.json` names are junctions into `packages/*`. Recreating
those links costs nothing and restores the composition exactly: **196 rows, empty stderr.**

## 3. How the generated preset rows reach the composition — the mechanism, and why

`scripts/make-preset-rows.mjs` (already committed, not modified here) turns each preset into a
`preset-<name>` composition row. The trap is recorded in `FINDINGS.md` item 2: a profile's patch
layers are its **bundles'** `dsh.bundle.patch` files (in `dsh.profile.bundles` order) and then the
profile's **own** `cordis.patch.yml` (`@deepseek-ai/dsh-app-boot/lib/index.js:462-475`). A second
loose file in the profile directory — `presets.generated.patch.yml` — is **not one of those layers**
and is therefore never read. Confirmed by composing a staged home that carried it: our rows were
absent.

Three wirings were available, and only one is usable from a builder that may not edit the candidate
prefix:

1. a launcher `--patch` argument — not this module's to add, and nothing in the repo passes one
   (`scripts/sync.py` and `multi-window/dshw.ps1` searched, no match);
2. a bundle that declares the file — would require writing into
   `<candidate>/node_modules/@deepseek-ai/dsh-web-app/package.json`, i.e. mutating a fetched install.
   Refused: the staged copy is the thing under test, not the install;
3. **fold the same rows into `profiles/<profile>/cordis.patch.yml`, inside a MARKED MANAGED BLOCK** —
   the layer the engine *already* loads, and the convention this repo established for exactly this
   problem (`make-preset-rows.mjs --install` does it for the repo copy).

**This module takes (3).** `insert:` with no `id` does `data.push(...insert)` in the engine's own
patch algorithm, so a row inserted from the profile layer is the same row as one inserted from a
`--patch` layer: the mechanism is provably equivalent, not merely similar. The block is derived from
the converter's **output**, so the two cannot disagree, and the markers are the converter's own
regexes.

### Why the body is re-emitted in flow style

The standalone artefact is a **block** sequence (`- insert:` at column 0); `cordis.patch.yml` is one
**flow** collection (`[ { … }, … ]`), and a block collection inside a flow collection is a parse
error. So the parsed entries are re-emitted in flow style with `!!js` kept as source text, and then
proved equal to the artefact by parsing both. A hand-rolled `YAML.stringify(value, { customTags })`
would silently write `!!js undefined` — `jsTag.stringify` is called once with the `{ __js }` wrapper
and its **return value is discarded** (measured, `FINDINGS.md`). The sentinel substitution in this
module is the same workaround, and `tests/stage-home/` asserts that every `!!js` value survives, that
every plain-safe expression is byte-identical, and that the result is the same entries as
`make-preset-rows.mjs --print-block`.

The block carries the artefact's own provenance comments (`# Written by …`,
`#   presets/<name>/agent.cordis.yml  rows=N  sha256=…`) as its leading lines. That is what lets
`spliceManagedBlock` refuse to overwrite a block that does **not** carry them — a generated block
without them was hand-edited, and overwriting it would hide that.

### What this deliberately does NOT do

* **It does not make one of our presets the default.** 0.1.7's `agent-preset-registry` row carries
  `config.default`, shipped as `standard` by `dsh-web-app`'s own patch layer (`FINDINGS.md` item 1).
  Our rows now compose, but a session that names no preset still gets `standard`. Naming `zabz` as
  the default is a patch to a row we do not own and a separate deliberate change; it is recorded in
  the manifest under `openRows`, not done here.
* **It does not carry `presets/<name>/preset.yml`**, so the roster shows preset *ids* rather than the
  written display names until a row carries them (`FINDINGS.md` item 4).
* **It does not resolve the `baseUrl` / `customSkillDirs` question** (`FINDINGS.md` item 3): on 0.1.7
  `baseUrl` is the *declaring patch layer's* base, not `presets/<name>/`, so the bundled skills may
  resolve somewhere other than the preset's own `skills/`. That is derived from the code paths and is
  **not** verified end-to-end; it needs a real session mount.

## 4. Provenance: the manifest

Every build writes `<out>/STAGED-HOME.json`: the generator and timestamp, the source home, the
candidate, the per-slot decision, the exclusions and their reasons, the recreated links, the block
that was spliced, the open rows above, and a **sha256 of every file** in the tree.

Two things it is not:

* It is **not a gate on the manifest's own timestamp.** `--check` compares the tree's files and
  ignores `provenance.generatedAt`; a gate that failed on the clock is a gate nobody can keep green.
* The hash list is the **generator's own record**, not an independently computed one. It catches a
  fetch-time failure — an unreadable source tree, a crashed process — not a bug in the hashing code.
  The independent proofs are the assertion in §5 and the composed tree in §6.

## 5. The assertion, run in both modes

`assertStagedHome()` reproduces the `switch-engine.ps1` PRECONDITION 2 predicate literally, using the
candidate's own names:

* a preset file exists at `<out>/.agent-presets/*/agent.cordis.yml` and a profile patch at
  `<out>/profiles/*/cordis.patch.yml`;
* the presets name the candidate's workflow package at least once and the removed one **zero** times
  outside a comment;
* the profile patches name the candidate's registry package at least once and the removed one zero
  times outside a comment;
* every `preset-<name>` row implied by the staged presets is present in a **profile patch layer the
  engine loads**, with a non-empty `config.plugins` and the right row plugin.

The comment handling is quote-aware, character by character, because a comment is a `#` at the start
of a line or after whitespace **but not inside a quoted scalar** — and that is where these files keep
everything that matters. `profiles/mesh/cordis.patch.yml:93` is
`name: '@deepseek-ai/dsh-agent-preset-registry'`, a real row whose line *starts* with a `#`; a reader
that does not track quote state calls that row prose, and the first version of this module did
exactly that, reporting our own rewritten file as still naming the removed package.

`--check` runs this assertion against the **committed** tree as well as the freshly built one: a
comparison against the wrong standard is not a gate.

## 6. Evidence

| command | result |
|---|---|
| `node dsh-update/tests/stage-home/run.mjs` | **PASS — 109 checks**, including the live-home fingerprint, the real candidate, and a compose of the staged tree |
| `node dsh-update/lib/stage-home.mjs --from ~/.dsh --candidate <0.1.7-rc.2 prefix> --out <dir> --profile web` | exit 0; 3 presets migrated, 3 rows spliced, assertion PASS |
| the same with `--check` on that tree | exit 0 — `38 file(s) match a fresh build` |
| the same `--check` after a one-byte edit | exit 1 — drift plus two assertion failures |
| `node dsh-update/lib/compose.mjs --profile web --bin <0.1.7-rc.2>/dsh/lib/bin.js --home <dir>` | **196 rows, exit 0, empty stderr**; `preset-zabz` 26 plugins, `preset-yocheved` 20, `preset-cordis-bg` 19 |
| the switch predicate counted over the whole staged tree, comments included | `NEW_PTC=9 OLD_PTC=0` and `NEW_REG=6 OLD_REG=0` |

---

## Appendix — the CLI contract in one page

```
node dsh-update/lib/stage-home.mjs --from <configHome> --candidate <prefix> --out <dir>
                                  [--profile web] [--check] [--json]
```

Build output (stdout, or `--json` for one object):

```
stage-home: built <dir>
  from / candidate
  slot <id> : modern -> @deepseek-ai/<package>          # one line per coupled slot
  files / rewrites          # what was copied, what links were recreated, what was retargeted
  preset rows : N entr(ies) [ids] spliced into profiles/<p>/cordis.patch.yml
  assert ok  <check>: <value>                            # every assertion line
  assertion : PASS
  manifest  : <out>/STAGED-HOME.json
```

Exported for tests: `detectSlots`, `candidateSlots`, `countRefs`, `blockFromGenerated`,
`entriesToFlowLines`, `collectJsTexts`, `isPlainSafeFlow`, `spliceManagedBlock`, `assertStagedHome`,
`buildStagedHome`, `diffTrees`, `parseArgs`, `main`, `yamlInfo`.

Operational note: `%TEMP%` on `ZABZ-YOGA` is `C:\Users\ezabz\.dsh\tmp`, so a literal `%TEMP%\…` in a
command writes **inside the live home's `tmp\` subdirectory**. The builder only ever reads the live
config surface and is proved not to write there (`tests/stage-home/` hashes the whole surface before
and after a build), but a command that is *not* this tool — a scratch file, a manual edit — should be
pointed at a path outside `~/.dsh` deliberately.
