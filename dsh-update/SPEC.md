# dsh-update — spec and frozen interface

Status: **frozen 2026-09-23** (ZABZ-TECH). This file is the integration contract between the four
modules of the pipeline. Change it deliberately, never silently.

> **READ `## Corrections from measurement` AT THE END FIRST.** Several claims in the sections above
> were falsified by running the engine on 2026-09-23; where that section and an earlier section
> disagree, **the corrections section wins**. The earlier text is left in place on purpose — the
> record of having been wrong is worth more than a clean-looking document.


## Why this exists

DSH is an npm package (`@deepseek-ai/dsh`), and this deployment runs a **preview/rc** line. Upstream
moves. We have roughly 40 places that name upstream artifacts by exact string — plugin package
names, subpath exports, row ids, service names in `isolate:`, settings keys, CLI subcommands — plus
11 of our own cordis plugins that consume the upstream host API. An upstream change can therefore
remove a capability we depend on **without any error**, because a patch or a settings key that stops
applying is not an error. That is the whole risk: silent loss.

Measured facts this design rests on (all read from this machine, 2026-09-23):

| Fact | Value | How it was read |
|---|---|---|
| Installed version | `0.1.5-rc.1` | `node <bin.js> --version` |
| Engine path | `%LOCALAPPDATA%\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js` | `Get-CimInstance Win32_Process` for the live `dsh web --port 3099` |
| Registry `latest` / `next` / `alpha` | `0.1.5-rc.3` / `0.1.7-rc.1` / `0.1.7-alpha.2` | `npm view @deepseek-ai/dsh dist-tags --json` |
| All published versions | 25, from `0.0.1-rc.1` to `0.1.7-rc.1` | `npm view @deepseek-ai/dsh versions --json` |
| `dsh --dump-config` | **exit 0, 180 ms, 21,804 bytes** | run against the live install, read-only |
| Launcher | `multi-window\dshw.ps1 ensure -ConfigPath multi-window\windows.json` (Task `DSH Engine Watchdog (1m)` → `.vbs`) | scheduled task action + VBS body |
| Launcher's engine knob | `dshInstall` in `windows.json`, or `$env:DSH_INSTALL` (npm prefix) | `dshw.ps1` ~L249-293 |
| Profile size | `~/.dsh/profiles/web` = **0.1 MB / 32 files**; `node_modules` holds 11 links to our own plugins only; `.dsh-module-fallback/node_modules` is **empty** | dir walk |
| Upstream plugin resolution | from the **engine install**, not the profile | absence of `@deepseek-ai` under the profile `node_modules` |
| **An install is a SET of versions, not one** | **240** `@deepseek-ai/*` packages installed; **230 at `0.1.5-rc.2`**, **1 at `0.1.5-rc.1`** (the `dsh` launcher itself), plus cordis `4.0.2`, schemastery `3.18.2`, cosmokit `1.8.3` | per-package `package.json` census, 2026-09-23 |

### The version is a set, not a number — and this is load-bearing

`node <bin.js> --version` on this machine prints **`0.1.5-rc.1`**. That is the version of the `dsh`
launcher package only. Every plugin that does the actual work — `dsh-base`, `dsh-agent-loop`,
`dsh-tool-subagent`, `dsh-session`, all 230 of them — is installed at **`0.1.5-rc.2`**, because
`dsh@0.1.5-rc.1` declares its dependencies as `^0.1.5-rc.1` and npm resolved them to the highest
matching prerelease. So the running engine is a mix, and **the CLI's version string does not
describe it.**

Three consequences, all of which the code must honour:

1. **`pin.json` carries `packageVersions`** — a map of package name → installed version, plus
   `packageVersionsSha256`. A single `version` field is a display convenience and must never be the
   only identity recorded.
2. **Every diff is per package, never per version string.** Two installs both reporting `0.1.5-rc.1`
   can differ in 230 packages. `status` must print the mixture, not just the headline.
3. **The candidate is also a mixture.** `fetch <ver>` installs one version of the launcher; its
   plugins resolve independently. So `analyze` and `verify` must compare the candidate's
   **packageVersions map**, and the `contractSha256` — not the version string — is what a `verify`
   result is bound to.

An install whose packages disagree with the launcher is **normal here** and is not by itself a
finding. What matters is whether the *surfaces we consume* still exist.


The last two matter: it means an isolated `DSH_HOME` copy is cheap, and a candidate engine resolves
the candidate's own upstream plugins — so a verify run is a genuine end-to-end test, not a fake one.

## The six breakage classes

Each is detected by code, not by a human reading a changelog. `B*` ids appear in findings.

- **B1 package missing** — we name `@deepseek-ai/dsh-x` (preset row, profile bundle, or plugin
  import) and the candidate has no such package. → `BREAKS`
- **B2 subpath missing** — we name `@deepseek-ai/dsh-x/subpath` and the candidate's `exports`
  lacks it (real case in this repo: `dsh-tool-subagent-control/list-agents`). → `BREAKS`
- **B3 patch target gone** — our `cordis.patch.yml` (or a preset overlay) patches row `id: X`, and
  the candidate's composed tree no longer contains a row `X`. Our customization is now a **silent
  no-op**. → `BREAKS`
- **B4 patch target moved** — row `X` still exists but now carries a different plugin `name`, so our
  patch now configures a different plugin. → `RISKY`
- **B5 bundle missing** — a name in `dsh.profile.bundles` no longer resolves. → `BREAKS`
- **B6 settings key rejected** — a key we set in `settings/*.yaml` is no longer accepted by the
  candidate. `--dump-config` **cannot** see this (it never reads the user settings document — a
  recorded lesson in `scripts/merge-settings.mjs`), so this class is only caught by a real boot. →
  `BREAKS` if the engine refuses to boot, `RISKY` if it warns.
- **B7 package surface changed** — a package we depend on kept its name but changed `exports`,
  `dsh` config, or its version across a semver range we do not control. → `RISKY`
- **B8 plugin API drift** — a symbol our `packages/plugin-*` import from cordis or an upstream DSH
  package is no longer exported. → `RISKY`, `BREAKS` if the package is gone.
- **B9 CLI drift** — a `dsh <subcommand>`/flag our scripts invoke is no longer accepted. → `RISKY`
- **B10 capability gain** — the candidate adds a package, subpath, row id, settings key, or CLI
  command. → `CAPABILITY` (never a reason to block)
- **B11 patch swallows a new upstream default** — **A PATCH REPLACES THE TARGETED ROW'S WHOLE
  `config`.** This deployment's own patch layer states that rule explicitly
  (`~/.dsh/profiles/web/cordis.patch.yml:47`, written after it caused PAIN P48). So when upstream
  adds a new key to the default config of a row we patch, our restated `config` silently drops it:
  the key reverts to its built-in default, or to `undefined`, with no error anywhere. This is the
  most dangerous class in the list, because the scar already exists — the `trustedHosts` incident
  was exactly this, and it was invisible on a workstation and total on the phone.
  **Detected by diffing `--dump-default-config`** (the profile tree *without* the user layer and
  without `--patch` overlays) for each patched row between baseline and candidate: any key present
  in the candidate's unpatched row config and absent from that row's unpatched baseline config, and
  absent from our patch's `config` for that row, is a swallowed default. → `RISKY`, `BREAKS` when
  the key is one whose loss the patch file calls load-bearing.

The live host patch layer targets exactly four rows — `typert-gateway`, `connection`,
`remote-fanout`, `tool-subagent-remote` (read from
`C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml`, 252 lines, 2026-09-23). Its format is a YAML
**flow sequence of `{ id, config }` maps**, with ids written `    id: 'typert-gateway',` — *not*
block-sequence `- id:` style. Extraction code must match this shape, and `harness-config/profiles/`
may hold more.


## Evidence tiers — provenance is not optional

A reading must never be presented as more certain than it is. Every field in `contract.json` that is
recovered by pattern-matching rather than by reading a manifest carries its `confidence`.

- **AUTHORITATIVE** — read from a JSON/YAML manifest or from the engine's own output:
  `package.json` (`name`, `version`, `exports`, `bin`, `dsh`, `dependencies`), file presence and
  sha256, `--dump-config` output (row id, plugin name, `disabled`, config, layer attribution),
  process exit codes, and verbatim engine diagnostics.
- **ADVISORY** — recovered by regex from built JavaScript (settings keys, registered service/tool
  names, exported symbols). Always labelled, never used alone to declare `BREAKS`.

Rule: a `BREAKS` finding may only rest on AUTHORITATIVE evidence. ADVISORY evidence may raise
`RISKY` or `CAPABILITY`, and must be reported with the pattern that produced it.

## Layout

```
harness-config/dsh-update/
  SPEC.md                     this file
  README.md                   operator-facing: what to run, in what order
  bin/dsh-update.ps1          the only entry point
  lib/
    yaml.mjs                  resolve a usable `yaml` impl from the installed harness tree
    store.mjs                 paths, atomic writes, pinned state, append-only history
    versions.mjs              npm registry queries + version classification + the pin
    contract.mjs              describe an installed DSH tree  -> contract.json
    compose.mjs               run --dump-config, normalize        -> tree.json
    consumed.mjs              describe what WE depend on          -> consumed.json
    diff.mjs                  baseline vs candidate               -> diff.json
    report.mjs                diff.json -> report.md
    verify.mjs                the gates                            -> verify.json
  state/
    pin.json                  what we are running now
    baseline/{contract.json,tree.json}
    candidates/<version>/{contract.json,tree.json,diff.json,report.md,verify.json}
    history/events.tsv        append-only
    logs/                     every engine invocation, verbatim
  vendor/
    prefix/<version>/         a managed npm prefix for a candidate install
    overlay/                  patch overlays used only by verify
```

Everything the pipeline writes outside `dsh-update/` is a timestamped backup plus an atomic
replacement, and only `promote`/`rollback` write outside at all.

## Frozen JSON schemas

### `state/pin.json`

```json
{
  "version": "0.1.5-rc.1",
  "installRoot": "C:\\Users\\ezabz\\AppData\\Local\\npm-cache\\_npx\\1e7f6d9597241db0",
  "enginePath": "<installRoot>\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js",
  "managed": false,
  "pinnedAt": "2026-09-23T20:00:00.000Z",
  "by": "ZABZ-TECH",
  "contractSha256": "<sha256 of state/baseline/contract.json>",
  "treeSha256": "<sha256 of state/baseline/tree.json>",
  "predecessor": null
}
```

`managed:false` means we inherited whatever npx resolved (today's state). `managed:true` means the
engine comes from `vendor/prefix/<version>` and we control it. `predecessor` is the whole previous
pin object, so `rollback` needs no other input.

### `contract.json`

```json
{
  "schemaVersion": 1,
  "generatedAt": "ISO-8601Z",
  "host": "ZABZ-TECH",
  "installRoot": "C:\\...",
  "dsh": {
    "name": "@deepseek-ai/dsh",
    "version": "0.1.5-rc.1",
    "bin": { "dsh": "lib/bin.js" },
    "exports": { ".": { "import": "./lib/bin.js" } },
    "exportSubpaths": [".", "./package.json"],
    "repository": "git+https://github.com/deepseek-ai/deepseek-harness.git",
    "dsh": { "configTrees": [ { "mount": "config/agent-presets", "path": "../../packages/preset/agent-presets/presets", "scanRoster": true } ] },
    "dependencies": { "@deepseek-ai/dsh-base": "^0.1.5-rc.1" }
  },
  "packages": {
    "@deepseek-ai/dsh-tool-subagent": {
      "version": "0.1.5-rc.1",
      "dir": "node_modules/@deepseek-ai/dsh-tool-subagent",
      "present": true,
      "exportSubpaths": [".", "./package.json"],
      "exportsRaw": { ".": "./lib/index.js" },
      "dsh": {},
      "dependencies": {},
      "peerDependencies": {},
      "files": { "lib/index.js": { "bytes": 42123, "sha256": "..." } },
      "provenance": {
        "manifest": "AUTHORITATIVE",
        "exportSubpaths": "AUTHORITATIVE",
        "settingsKeys": "ADVISORY",
        "serviceNames": "ADVISORY",
        "toolNames": "ADVISORY",
        "symbols": "ADVISORY"
      },
      "settingsKeys": ["provider", "toolName", "enableRunInBackground", "backgroundMode", "maxDepth", "modelSelectionSettings"],
      "serviceNames": ["subagents"],
      "toolNames": ["subagent"],
      "symbols": ["export", "class", "function"]
    }
  },
  "packageCount": 78,
  "notes": []
}
```

`packages` covers **every** `@deepseek-ai/*` package under `<installRoot>/node_modules/@deepseek-ai`,
not only the ones we reference — the cross-reference against `consumed.json` is what decides which
differences matter.

### `tree.json` (composed profile tree)

```json
{
  "schemaVersion": 1,
  "generatedAt": "ISO-8601Z",
  "enginePath": "C:\\...\\bin.js",
  "engineVersion": "0.1.5-rc.1",
  "dshHome": "C:\\Users\\ezabz\\.dsh",
  "profile": "web",
  "isolatedHome": null,
  "invocation": "node <bin.js> --profile web --dump-config",
  "exitCode": 0,
  "durationMs": 180,
  "stderr": "",
  "rows": [
    {
      "index": 0,
      "id": "timer",
      "name": "@deepseek-ai/cordis-plugin-timer",
      "disabled": false,
      "group": false,
      "config": {},
      "layers": ["@deepseek-ai/dsh-base"],
      "patchedBy": null
    }
  ],
  "rowIds": ["timer", "hmr", "..."],
  "names": ["@deepseek-ai/cordis-plugin-timer", "..."],
  "layerComments": ["@deepseek-ai/dsh-base", "C:\\Users\\ezabz\\.dsh\\profiles\\web\\cordis.patch.yml"],
  "patchedRowIds": ["typert-gateway"],
  "disabledRowIds": ["hmr"]
}
```

Row objects carry `layers` (the `# == ...` lineage comments preceding the row) and `patchedBy`
(the `patched by <path>` comment, or `null`). `patchedRowIds` is the load-bearing field for B3/B4.

A dump that exits non-zero, or whose stdout does not parse, must produce a `tree.json` with
`exitCode` and the raw stdout saved beside it under `state/logs/` — **never a silently empty
`rows` array**. An empty result is a refusal, not health.

### `consumed.json`

```json
{
  "schemaVersion": 1,
  "generatedAt": "ISO-8601Z",
  "configRoot": "C:\\Users\\ezabz\\Code\\harness-config",
  "dshHome": "C:\\Users\\ezabz\\.dsh",
  "profileBundles": [
    { "name": "@deepseek-ai/dsh-base", "source": "profile", "file": "C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json", "line": 12 }
  ],
  "packageRefs": [
    { "name": "@deepseek-ai/dsh-tool-subagent", "subpath": ".", "kind": "preset-row",
      "file": "presets/zabz/agent.cordis.yml", "line": 347 }
  ],
  "rowIds":          [ { "id": "tool-subagent", "file": "...", "line": 346, "where": "preset" } ],
  "isolateServices": [ { "service": "workflowEngine", "file": "...", "line": 301 } ],
  "settingsKeys":    [ { "key": "spend-guard.ceilingUsd", "value": 150, "file": "settings/base.yaml", "line": 41 } ],
  "cliInvocations":  [ { "argv": ["archive", "import"], "file": "scripts/dsh-archive-import.py", "line": 12 } ],
  "pluginImports":   [ { "package": "dsh-plugin-health", "module": "@deepseek-ai/cordis", "symbols": ["Context"] } ],
  "patchRowTargets": [ { "id": "typert-gateway", "file": "C:\\Users\\ezabz\\.dsh\\profiles\\web\\cordis.patch.yml", "line": 7, "layer": "host" } ],
  "notes": []
}
```

Scan roots, in order: `presets/**`, `profiles/**`, `settings/**`, `packages/*/src` + `packages/*/package.json`,
`scripts/**`, `multi-window/**`, and `~/.dsh/profiles/*/{package.json,cordis.yml,cordis.patch.yml}`.
Exclusions: `**/node_modules/**`, `journal/entries/**`, `dsh-update/state/**`, `dsh-update/vendor/**`,
`**/*.bak-*`, `_scratch/**`, `.git/**`.

An `isolateServices` entry matters more than it looks: those keys name **services**, and a renamed
service makes the row fail to mount at all.

### `diff.json`

```json
{
  "schemaVersion": 1,
  "generatedAt": "ISO-8601Z",
  "baseline": { "version": "0.1.5-rc.1", "contractSha256": "...", "treeSha256": "..." },
  "candidate": { "version": "0.1.7-rc.1", "contractSha256": "...", "treeSha256": "..." },
  "verdict": "BREAKS",
  "counts": { "BREAKS": 0, "RISKY": 0, "CAPABILITY": 0, "INFO": 0 },
  "findings": [
    {
      "id": "F001",
      "class": "B2",
      "severity": "BREAKS",
      "subject": "@deepseek-ai/dsh-tool-subagent-control/list-agents",
      "evidence": "exports in 0.1.7-rc.1 = [\".\", \"./package.json\"]; no ./list-agents",
      "evidenceTier": "AUTHORITATIVE",
      "consumers": [ { "file": "presets/zabz/agent.cordis.yml", "line": 338 } ],
      "why": "the preset row would fail to resolve at mount, so session creation on the zabz preset breaks",
      "suggested": "keep the disabled row; do not delete it, and re-check whether upstream now ships a deadline"
    }
  ],
  "consumed": { "packagesChecked": 61, "unverified": [] }
}
```

`verdict` is `BREAKS` if any finding is `BREAKS`, else `RISKY` if any is, else `SAFE`.
`consumed.unverified` lists consumed references the analysis could not resolve — an honest gap
list, so "no findings" is never confused with "not checked".

### `verify.json`

```json
{
  "schemaVersion": 1,
  "generatedAt": "ISO-8601Z",
  "version": "0.1.7-rc.1",
  "contractSha256": "...",
  "pass": false,
  "gates": [
    { "id": "G1", "name": "dump-config composes", "ran": true, "ok": true, "exitCode": 0,
      "detail": "412 rows", "evidence": "state/logs/verify-0.1.7-rc.1-G1.txt" },
    { "id": "G2", "name": "every patch target still applies", "ran": true, "ok": false,
      "detail": "lost: typert-gateway, mcp-secretary", "evidence": "..." },
    { "id": "G3", "name": "our 11 plugins resolve", "ran": true, "ok": true, "detail": "11/11", "evidence": "..." },
    { "id": "G4", "name": "settings document accepted (boot)", "ran": true, "ok": true,
      "detail": "no unknown-key or schema diagnostics", "evidence": "..." },
    { "id": "G5", "name": "headless agent turn completes", "ran": true, "ok": true,
      "detail": "exit 0, assistant text 'OK', 4120 ms", "evidence": "..." },
    { "id": "G6", "name": "no patched row swallowed a new upstream default", "ran": true, "ok": true,
      "detail": "4 patch targets compared via --dump-default-config; no new keys dropped",
      "evidence": "..." }
  ],
  "notes": ["G5 runs headless with MCP bridges absent by construction; --full also boots the web profile"]
}
```

`pass` is true only when every gate with `ran:true` has `ok:true`.

## Verify gates

| Gate | Name | Method | Cannot be caught by |
|---|---|---|---|
| G1 | tree composes | candidate `--dump-config` with an isolated `DSH_HOME`: exit 0, rows parse, rows > 0 | — |
| G2 | every patch target still applies | every consumed `patchRowTargets` id appears in the candidate tree's `patchedRowIds` | the contract diff |
| G3 | our plugins resolve | all 11 `dsh-plugin-*` names from the live profile's `dsh.profile.bundles` appear as a row `name` | the contract diff |
| G4 | settings document accepted | **a real boot** — `--dump-config` never reads the settings document | G1-G3 |
| G5 | a headless agent turn completes | candidate `--profile headless` with a trivial prompt; exit 0, assistant text present, verbatim stderr kept | everything else |
| G6 | no patched row swallowed a new upstream default | diff `--dump-default-config` per patch target, baseline vs candidate | G1-G3 (they see only the *patched* tree) |

**An isolated `DSH_HOME` is mandatory for G1-G6.** Build it by copying `settings.yaml`, `profiles/`
and `.agent-presets/` into `state/candidates/<ver>/home/` — the live home is ~0.1 MB of profile, so
this is cheap, and it is what keeps a candidate engine away from live session logs. Two engines
sharing one `DSH_HOME` have corrupted session logs before, and that is recorded in
`multi-window/windows.json`.

`--full` adds a seventh step: start the candidate `web` profile on a free port in 3400-3500, poll
HTTP until it answers or times out, then kill **only the pid it started**. It is opt-in because a
web boot spawns the MCP bridges and costs real memory. It must never touch port 3099.

A gate that did not run is `ran: false` and **never** `ok: true`.

## CLI surface

`bin/dsh-update.ps1 <verb> [args]`. No verb = `status`. Every verb supports `-Json`.

**The PowerShell file is a six-line shim** that resolves `node` and execs `lib/cli.mjs` with the
arguments unchanged, forwarding the exit code. All logic is Node, because the engine is Node and
because a `.ps1`-that-drives-`.mjs` boundary would otherwise mean parsing JSON across two languages
in ten places. `lib/cli.mjs` is the dispatcher; `lib/*.mjs` are plain ESM modules that also run
standalone as `node lib/<module>.mjs <args>`, printing their JSON artifact to stdout, so each can be
tested and re-run without the dispatcher.

| Verb | Writes | What it does |
|---|---|---|
| `status` | nothing | pin, engine path, available versions, last analysis/verification per version |
| `check` | nothing | registry query; classify each newer version; show which are already analyzed |
| `snapshot` | `state/baseline/**` | describe the pinned engine (contract + tree) — the diff substrate |
| `fetch <ver>` | `vendor/prefix/<ver>/**` | `npm install @deepseek-ai/dsh@<ver>` into a managed prefix; no touching the live install |
| `analyze <ver>` | `state/candidates/<ver>/**` | contract diff + consumed cross-reference + isolated tree diff → `diff.json` + `report.md` |
| `plan <ver>` | nothing | exactly what `promote` would change, file by file, line by line |
| `verify <ver>` | `state/candidates/<ver>/verify.json` | the five gates; `-Full` adds a real web-profile boot |
| `promote <ver>` | `state/pin.json`, `windows.json`, history | **refuses unless `verify.pass` is true for that exact contract hash**; backs up, writes atomically; **never restarts the engine** |
| `rollback` | `state/pin.json`, `windows.json`, history | restores `predecessor`; also never restarts |
| `report <ver>` | nothing | print the report path and the verdict summary |

## Safety invariants

1. **Nothing here deletes anything.** No `rm`, no `Remove-Item -Recurse`, no pruning of the npx
   cache or of `vendor/`. Old prefixes stay until a human removes them.
2. **No verb except `promote` and `rollback` writes outside `dsh-update/`.**
3. **No verb kills or restarts an engine.** `promote` writes the pin and the launcher knob; the
   change takes effect at the **next** boot. Restarting the engine from inside a session would kill
   that session — including the one running the promote.
4. **Every write outside `dsh-update/` is preceded by a timestamped backup**, and applied by
   temp-file + atomic rename.
5. **`promote` requires a passing `verify` for the same `contractSha256`.** No override flag may
   bypass this; a deliberate bypass is a code change, not a flag.
6. **`state/history/events.tsv` is append-only** and is the audit trail for every promotion and
   rollback.
7. **Provenance in every reading.** Fields carry `AUTHORITATIVE`/`ADVISORY`; findings carry the
   command, file and line that produced them.
8. **An empty or failed read is reported as a failure**, never as an empty success.

## Definition of done

- `bin/dsh-update.ps1 status` runs on a clean checkout, prints the real pin, and exits 0.
- `check` lists the 25 published versions and marks the 4 newer than the pin.
- `snapshot` produces `contract.json` covering every `@deepseek-ai/*` package and a `tree.json`
  whose `rows` count matches a fresh `--dump-config`.
- `analyze <newer>` produces a `diff.json` with a verdict and a `report.md` a person can act on,
  and its findings name real files and lines in this repo.
- `verify <newer>` runs all five gates and is honest when one cannot run.
- `promote`/`rollback` refuse to run without a passing verify and a clean `plan`, and leave a
  history row.
- A test that proves the detector actually detects: `tests/fixtures/` holds a synthetic
  baseline/candidate pair with a known B2 and a known B3, and `tests/run.ps1` asserts both are
  found. A detector that has never fired on a known-bad input is not a detector.

---

# Corrections from measurement

Every item below was **measured on ZABZ-TECH on 2026-09-23**, after the interface above was frozen.
Each says what was claimed, what was actually observed, and what the code must do instead. Where an
item contradicts an earlier section, **this section wins.**

Measured baselines to rewrite into the code and the earlier table:

| Reading | Real value | How |
|---|---|---|
| `--dump-config` stdout for profile `web` | **21,151 bytes** (not 21,804 — that figure came from a `*>` redirect that merged other streams), **163 rows** | stdout captured separately; stderr **0 bytes** |
| `--dump-config` duration | **100-280 ms** | several runs |
| `contract.json` over the live install | **240** `@deepseek-ai/*` packages, **423 ms**, 3,385 files (3,384 hashed; 1 over the 2 MB cap) | `contract.mjs` |
| `--dump-config --profile headless` | **87 rows**, exit 0 | `compose.mjs` |
| Candidate `0.1.5-rc.3` in `vendor/prefix/` | **163 rows, exit 0, 279 ms**, no lost patch target | `compose.mjs` |

## C1 — **A patch that applies may carry no `patched by` annotation. The annotation is not the detector.**

**Claimed:** B3 detects a lost patch by checking that our patch ids appear in `tree.json`'s
`patchedRowIds` (the rows annotated `patched by <path>`).

**Measured:** `~/.dsh/profiles/web/cordis.patch.yml` has four entries. The dump annotates only
**three** of them — `typert-gateway`, `connection`, `remote-fanout`. The fourth,
`{ id: 'tool-subagent-remote', disabled: true }` (line 248), **applies correctly** (the composed row
reads `disabled: true`) and carries **no annotation at all**.

So the claimed detector is wrong in both directions: it would fire a false `BREAKS` on a working
disable-type patch, and it would stay silent if a real disable-type patch stopped applying.

**Must do instead.** Detect by comparing **intent against effect**, not by reading comments. For each
patch entry `{id, config?, disabled?}` in a layer we own:

1. find the row by `id` in `candidateTree.rows`;
2. **row absent** → `BREAKS`: upstream deleted the row, our entry is a silent no-op;
3. `config` present → every leaf the patch sets must appear in the composed row's `config` with an
   equal value; a leaf missing or different → `BREAKS` (a later layer overrode us, or the key is no
   longer in the row's schema);
4. `disabled` present → the composed row's `disabled` must equal it → else `BREAKS`;
5. `patched by` is kept in `tree.json` as **supporting** evidence only, never as the assertion.

B4 becomes: the row id survives, and the plugin `name` on it changed, *or* the row's composed config
differs from the previous install in a leaf our patch sets.

## C2 — **An unknown settings key is completely silent. G4 as written detects nothing.**

**Claimed:** G4 catches settings-schema drift (B6) by scanning engine stderr for unknown-key or
validation complaints.

**Measured.** Two real headless boots against an isolated home, one prompt each, credentials passed
through the environment only:

```
real settings, no bogus key     exit=0  2939 ms  stdout tail "OK"   stderr EMPTY
real settings + this-plugin-does-not-exist:
  aKeyWeInvented: 12345         exit=0  3438 ms  stdout tail "OK"   stderr EMPTY
```

Byte-for-byte the same outcome. **The engine silently ignores a top-level settings key it does not
recognise.** There is no warning to scan for, so stderr-scanning cannot detect B6 at all.

**Must do instead.** Gate G4 must read the engine's own **effective** settings and assert each key we
set is present with our value. The web profile exposes a settings controller
(`@deepseek-ai/dsh-api-settings-controller`); so G4 becomes: boot the candidate's web profile on a
spare port in 3400-3500 against the isolated home, read back the effective settings, and require
every leaf in `consumed.settingsKeys` to be present with the configured value. Any leaf absent, or
present with a different value, is B6 — and this is AUTHORITATIVE evidence, because it is the
engine's own report of what it is running with.

To keep this cheap, the boot may run with the MCP rows disabled via an extra `--patch` overlay, and
that must be stated in `verify.json.notes`. `--no-boot` marks G4 `ran: false`; it must never be
`ok: true`.

## C3 — **Agent presets contribute no rows to the composed tree. Preset breakage needs its own gate.**

**Claimed:** the tree diff covers the deployment's customizations.

**Measured.** Computed from `presets/zabz/agent.cordis.yml` against the real dump: the preset has
**26** row ids, the host composition has **163**. **14** ids are preset-exclusive — `persona`,
`planning`, `compaction`, `delegation`, `tool-ask-user`, `tool-cordis`, `present`, `mcp-secretary`,
`mcp-secretary-linux`, `mcp-firecrawl`, `mcp-jina`, `mcp-context7`, `mcp-fetch`, `mcp-playwright` —
and **not one of them appears in the dump**. `rowsPatchedByAPresetPath` is empty. The only
preset-adjacent rows are the *host* components `id: agent-presets`
(`@deepseek-ai/dsh-agent-presets`, `config.default: standard`) and `id: ui-agent-preset`.

Corroborating: upstream ships exactly four presets — `cordis`, `minimal`, `ptc`, `standard` — while
ours live in `~/.dsh/.agent-presets/` as `cordis-bg`, `yocheved`, `zabz`. And `settings.yaml` sets
`agent-presets.default: zabz`, a name the shipped roster does not contain.

A false lead worth recording, because it wasted a first attempt: `tool-subagent`, `skill-filesystem`,
`tool-workflow` and `tool-ralph` look preset-only and are **not** — they ship in the `dsh-base` host
bundle. The discriminating test is set arithmetic (id in a preset file, absent from the whole host
dump), not a grep for a familiar name.

**Must do instead.** Add **G7 — preset resolution**: enumerate every preset directory
(`~/.dsh/.agent-presets/*`, `harness-config/presets/*`) and resolve **every** `name:` in each
`agent.cordis.yml` against the candidate install, including subpath exports
(`@deepseek-ai/dsh-tool-subagent-control/list-agents` is exactly this case). Also assert that the name
in `settings.yaml`'s `agent-presets.default` exists in the union of shipped and local rosters. This is
the *only* gate that sees new-session breakage, and it is cheap — no engine needed.

## C4 — **`--dump-config` is not read-only: it rewrites `profiles/<name>/cordis.yml`.**

**Claimed:** the dump is a read-only operation.

**Measured.** On a **successful** dump against the live home, `~/.dsh/profiles/web/cordis.yml`'s
mtime moved; its sha256 did **not** (`C300DCF2…` before and after; content stays the canonical empty
root `[]` plus its comment header). On a dump that *fails*, nothing is written (verified: exit 1,
mtime and hash unchanged).

**Must do instead.** Never hash the profile **directory** as evidence, and never treat the profile
tree as immutable. Hash only `package.json`, `cordis.patch.yml` and `settings.yaml`. Any "the config
is unchanged" claim must be made against those three files, not the directory. A dump must also not
be assumed to fail-safe on a read-only mount.

## C5 — **The isolated `DSH_HOME` must include each profile's own `node_modules`. Recipe corrected.**

**Claimed:** an isolated home is a copy of `settings.yaml`, `profiles/` and `.agent-presets/`.

**Measured.** Two separate traps, both hit for real:

1. `Copy-Item -Recurse ~/.dsh/profiles` **walks `profiles/node_modules`**, which is a complete
   187-package `@deepseek-ai` tree. The copy timed out at 120 s. Copy **only the named profile
   directories**, never the shared parent.
2. Dropping every `node_modules` makes the dump **fail**:
   ```
   Error: dsh: cannot resolve profile bundle "dsh-plugin-attention" from the dsh installation
   or C:\Users\ezabz\AppData\Local\Temp\dsh-home-probe2\profiles\web;
   run 'dsh plugin --profile web install' if its dependency is not installed
   at resolveBundleDir (…/@deepseek-ai/dsh-app-boot/lib/index.js:831)
   ```
   `profiles/web/node_modules` holds the 11 links that make **our** bundles resolvable. Those are
   required; the shared `profiles/node_modules` is what must be excluded.

**Must do instead.** Build the isolated home as: `settings.yaml`, `.agent-presets/`, and for each
needed profile, `profiles/<name>/**` **including `profiles/<name>/node_modules`** but **excluding
`profiles/node_modules`**. Measured cost of the correct isolated home: **0.24 MB / 22 files** — a
successful `--dump-config --profile headless` in it exits 0 in 121 ms with no resolution errors. That
confirms the candidate resolves its own upstream plugins, so the gate is a genuine end-to-end test.

## C6 — **There are two complete DSH installs on this machine, not one.**

**Measured.** `%LOCALAPPDATA%\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\` (240
packages) **and** `~/.dsh\profiles\node_modules\@deepseek-ai\` (187 packages), the latter as **real
directories, not junctions**, with the same version mix (its `dsh` is `0.1.5-rc.1`, 230 packages at
`0.1.5-rc.2`). `multi-window/dshw.ps1` lists `~/.dsh/profiles/node_modules/.../bin.js` as a candidate
engine path, and its resolution order puts `dshInstall`/`DSH_INSTALL` **first** (the `$root` branch
precedes the hardcoded npx path). The engine actually running is the npx one (pid observed on
`dsh web --port 3099`).

**Must do instead.** `detectInstalledEngine()` reports **every** install it finds, which one is
running, and which one the launcher would pick — never a single silently-chosen path. `status` prints
the list. Promotion sets `dshInstall`, which wins the resolution order, so it is sufficient — but
`promote` must first assert that the running engine is the one the pin names, or say plainly that a
restart would switch engines.

## C7 — **`dsh` CLI exit codes are not a guard.** (Correcting the correction.)

**Reported by review, then measured more precisely.** Bare `dsh status` does **not** print help and
succeed — it errors:

```
$ node bin.js status
error: --profile <name> is required
exit=1
```

The real hazard is narrower and worse: the CLI is `allowUnknownOption().passThroughOptions()`, so
`dsh --profile <name> <anything>` treats `<anything>` as **app arguments and boots the app**. A
review pass proved this accidentally — `--profile headless verify` completed a real LLM turn at exit 0.

**Must do instead.** Never invoke `dsh <verb>` expecting validation. Our own entry point is
`bin/dsh-update.ps1` and it must never forward an unknown verb to `dsh`. Any check that shells out to
the engine asserts on **output shape** (`--version` format, `--dump-config` row count), never on exit
status alone. Do not add a `dsh <verb>` wrapper.

## C8 — **Promotion is a one-way door for existing session logs. Gate the session-format version.**

**Measured.** `@deepseek-ai/dsh-session-format-catalog` declares `currentVersion: 3`, with codecs for
v0→v1→v2→v3 only. The live home holds **1,095** session files, **all** `session.v3.jsonl.zstd`.

A candidate that raises `currentVersion` to 4 will **write** v4 logs. Rolling back then leaves logs the
older tree cannot read — a downgrade destroys access to the operator's real history, not a test
fixture.

**Must do instead.** Add **G8 — session-format compatibility**: read `currentVersion` (and the codec
list) from both installs. Candidate `> ` current is `RISKY` at minimum and must be stated on the
report in plain language; it must not be silently promoted. A candidate with **no** codec covering
every version present on disk makes `rollback` unsafe, and `plan` must say so.

## C9 — **A `BREAKS` needs the artifact, not the version string.** (Consistent with the pin change above.)

Verify results must be bound to `contractSha256` **and** `treeSha256` **and** the
`packageVersionsSha256` of the candidate. `promote` re-derives all three and refuses on any mismatch,
so an edit to a `file:` plugin dependency or a re-resolved transitive prerelease after a passing
verify cannot be promoted on the strength of the old pass.

## C10 — **Cross-machine version skew is invisible and is reachable through git.**

Five machines share `harness-config`. A settings key or preset row written for a newer host is
**silently ignored** by an older one (see C2). `check` must therefore: write the validated version
tuple and a config-revision hash at every `promote`, and warn when the local tuple differs from the
tuples recorded for other machines in the repo. A `pm`-style "which machine is on what" line in
`status` is enough to make the skew visible.

## C11 — **`exports` subpath extraction must use Node's rule, or B2 never fires.**

A key is a **subpath** if and only if it is `"."` or begins with `"./"`. Anything else is a
condition. A first implementation used "contains a dot", which classified the map
`{"./list-agents": …}` as a *condition* map and collapsed the subpath list to `["."]` — which would
have made a **removed** subpath look **present**, silently disabling B2, the class this pipeline most
needs. Correct output for `@deepseek-ai/dsh-tool-subagent-control` is
`[".", "./list-agents", "./src/*", "./package.json"]`. Keep a regression test for exactly this.

## C12 — **A patch replaces the row's whole `config`, so a new upstream default is swallowed silently.**

Already recorded as B11 and gate G6; the measurement that makes it concrete is C1's: our patch file
has **4** id targets and **3** `config:` bodies. So the `disabled`-only entry is immune, and the three
config bodies are each a place where a newly added upstream key silently reverts to its built-in
default. `--dump-default-config` (which does **not** parse the user patch layer at all, making it the
clean comparison arm) is the evidence for G6.

## C13 — Integration fixes required before this pipeline's verdict may be trusted

The pipeline ran end to end on 2026-09-23 for the first time, against the real candidate
`0.1.5-rc.3`, and **its verdict was wrong**: `analyze 0.1.5-rc.3` returned `verdict: BREAKS`,
`counts BREAKS=2`, with two findings whose `evidenceTier` was `AUTHORITATIVE` and whose `why` read
*"our override is applied to nothing, and the setting we depend on silently reverts to upstream
default"*.

**That claim is false, and it was verified false by hand before anything was reported.** Both
findings were the same false positive, F001 and F002, on `tool-subagent-remote`:

```
candidate 0.1.5-rc.3: present=true disabled=true  patchedBy=false cfgKeys=provider,toolName,enableRunInBackground,maxDepth
baseline  0.1.5-rc.1: present=true disabled=true  patchedBy=false cfgKeys=provider,toolName,enableRunInBackground,maxDepth
candidate exit=0 rows=163 | baseline exit=0 rows=163
row ids added: (none) | row ids removed: (none)
```

All four patch targets are identical across the two versions, and the candidate adds and removes no
rows. **`0.1.5-rc.3` breaks nothing.** The detector was wrong, not the upgrade — this is the same
class as reporting a crisis that does not exist, which is the most expensive failure in this
system's history. Fix these before the verdict is trusted again:

- **F1 (causes the false BREAKS).** B3 still asserts on `patchedRowIds`, which C1 proves is an
  incomplete signal. Replace it with the effect comparison: read **both** the composed tree and the
  `--dump-default-config` tree for each side, and for each patch target assert the composed row's
  `disabled` and every `config` leaf the patch sets, per C1's five steps. Keep `patchedBy` as
  supporting detail in `evidence` only. **Hold this as a regression fixture**: a target whose patch
  sets only `disabled: true` must produce **no** finding when the composed row is disabled.
- **F2 (causes the duplication).** `patchRowTargets` records the same target **two to four times**,
  once with an absolute path and once relative:
  `remote-fanout ×4` (`profiles/mesh/cordis.patch.yml@73`, `profiles/web/cordis.patch.yml@132`, each
  in both spellings), `typert-gateway ×2`, `connection ×2`, `tool-subagent-remote ×2` — 10 entries for
  4 logical targets. Deduplicate by `(profile, id)` and keep every discovered location as a separate
  entry in `consumers`.
- **F3 (a correctness bug, not just noise).** Targets are **not scoped by profile**. `remote-fanout`
  is patched by `profiles/mesh/cordis.patch.yml` — a layer belonging to the **mesh** profile — and it
  was being checked against the **web** tree. A target from another profile's layer must never
  produce a finding for this profile. Add `profile: "web" | "mesh" | …` to each `patchRowTargets`
  entry, derived from the layer's directory, and compare a target only against its own profile's tree.
- **F4 (needed for F1).** `patchRowTargets` entries carry only `["id","file","line","layer"]` — no
  intent. Add `intent: { config?, disabled? }`, the literal body of that patch entry, so `diff.mjs`
  can assert effect without re-parsing YAML.
- **F5 (readability; a report nobody reads is not a report).** The same run emitted **253 INFO** and
  **422 `unverified`** findings. The B1/B5 entries are honestly reasoned — they are our own
  `dsh-plugin-*` names, which an upstream-only contract cannot judge, and the `why` says so. The
  problem is volume and repetition, not reasoning: 118 of them are the same 11 local plugins repeated
  across files. Aggregate `unverified` settings keys **by key** with a list of locations, and mark
  local-package notes as a single grouped line. `INFO` should be a short list a person can read.
- **F6 (cosmetic).** B9 subjects truncate multi-token argv badly: `dsh --dump-config did`. Rejoin the
  full argv into the subject.

Keep the two guards that did work, because both fired correctly on the first run: `promote` refused
without a passing verify and changed nothing, and `check` classified 26 published versions with 7
newer than the pin.

## C14 — The boot gates cannot run unless `verify` solves credentials for the isolated home

**Measured.** The first headless boot inside an isolated home failed immediately:

```
$ DSH_HOME=$env:TEMP\dsh-home-probe2 node <bin.js> --profile headless "Reply with the single word OK…"
exit=1  3951 ms
dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official";
     store DEEPSEEK_API_KEY through the credentials service (the web Models page writes it),
     or export DEEPSEEK_API_KEY in the launching environment
```

The credential lives in `$DSH_HOME/.credentials.yaml`, so a *different* `DSH_HOME` has none. Since
G4 and G5 both boot a candidate engine, **a pipeline that ignores this has two gates that can never
pass** — the classic shape of a check that silently becomes decorative.

**The fix is measured to work.** Passing the key in the child environment, with no file written
anywhere, ran both boots to `exit=0` and the model replied `OK`:

```
DEEPSEEK_API_KEY=<resolved from the live .credentials.yaml, never printed, never persisted>
  → exit=0  2939 ms  stdout "OK"   stderr empty    (control, real settings)
  → exit=0  3438 ms  stdout "OK"   stderr empty    (with a bogus settings key)
```

**Must do instead.** For G4/G5 (and `--full`), resolve the credential from the **live**
`$DSH_HOME/.credentials.yaml` — the file is a `records` map containing `DEEPSEEK_API_KEY` — and pass
it to the candidate engine as an environment variable. **Never copy the credential into the isolated
home, never write it to a log, and never print it**: `state/logs/` is plain text and this is a live
secret. If it cannot be resolved, mark G4/G5 `ran: false` with the reason and say so — do not mark
them passed, and do not let `pass` become true by omission.

Note the useful half of that failure: the engine's own word is legible and actionable, which is what
`verify.json` should be carrying for every failed gate.

## C15 — Defects in THIS document, found by the workstreams that implemented it

The record of having been wrong is worth more than a clean-looking spec, so these are listed rather
than quietly edited out.

- **D1 — this document contained a fabricated example, and that is the worst kind of error in it.**
  The `cliInvocations` example read `{ "argv": ["archive", "import"], "file": "scripts/dsh-archive-import.py", "line": 12 }`.
  The implementer checked: `scripts/dsh-archive-import.py` **never invokes `dsh`** — it imports a
  session archive — and no `["archive", "import"]` invocation exists on this machine. The example was
  inferred from a filename and written as though it had been read. **Rule for this file: every
  example must be traceable to a real reading, and an untraceable example is worse than none**,
  because implementers build fixtures from it. The 12 real invocations found are in
  `multi-window/dshw.ps1`, `scripts/mesh-provider-install.ps1`, `scripts/provision-mesh-node.sh`,
  `scripts/wake/runner.ps1` and `packages/plugin-mesh-http/test/mesh-http.test.mjs`.
- **D2 — `isolateServices` is smaller and differently sourced than claimed.** The spec said to expect
  `more` services "in the live `cordis.patch.yml`". The live layer contains **no `isolate:` mapping
  at all** (only the word "isolated-home" inside a comment on line 107). The complete set is exactly
  four — `planMode`, `compaction`, `toolResultPruner`, `workflowEngine` — all from the three preset
  files, 24 location entries across the repo copy and the live copy.
- **D3 — the `kind` enum is internally inconsistent.** The rules require `kind` to be one of
  `preset-row | profile-bundle | profile-row | settings | plugin-import | script | other`, and in the
  same breath require our own `dsh-plugin-*` names to be recorded as `kind: "own-plugin"`, which is
  not in that set. Implemented as `own-plugin` for our names (93 entries) with a location kind
  otherwise.
- **D4 — the `pluginImports` example omitted `file`/`line`** while the accompanying rule says every
  entry's `file`/`line` must be real. The implementation emits both.
- **D5 — B8 (plugin API drift) has no input on this deployment, so it is not coverage.** No package
  under `packages/*` imports `@deepseek-ai/cordis` or any `@deepseek-ai/dsh-*` module: our plugins
  receive `ctx` by injection. B8 is therefore inert here and must never be counted as a check that
  ran. The neighbouring contract-diff classes (B1/B2/B5/B7) do carry real weight.
- **D6 — accepted interpretation:** rows inside an `insert:` block are additions, not targets, so
  they are in `rowIds` but not in `patchRowTargets`. Nothing can "stop applying" to a row we bring
  ourselves.
- **D7 — deliberate coverage cost:** comment-only mentions of upstream packages are excluded from
  `packageRefs`, so B4 (a patch target that changed plugin) gets no advisory input. Recorded in
  `consumed.json`'s own notes rather than left implicit.

Two more spec corrections from the same pass, both widening what the code accepts rather than
narrowing it: `diff.mjs` and `verify.mjs` now export importable entry points *and* keep their CLI, and
`cli.mjs` invokes `verify.mjs` with `--engine/--contract/--tree/--diff/--logs-dir/--dsh-home`, which
`verify.mjs` now accepts. `verify.mjs` additionally required a `complete` field: under a literal
reading of the earlier `pass` rule, `--no-boot` would have produced `pass: true`, which SPEC section 5
would then have let a `promote` ride on. A verify that skipped the boot gates now returns
`pass: false`.




