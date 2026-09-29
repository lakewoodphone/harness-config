# STATE-COMPAT — 0.1.5 → 0.1.7-rc.2 on-disk state compatibility audit

**Scope:** read-only audit of every persisted store under `C:\Users\ezabz\.dsh\`.
**Method:** static reading of both installed builds, plus a read-only decode of the live session corpus.
**Baseline:** `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\` (packages at `0.1.5-rc.2`).
**Candidate:** `C:\Users\ezabz\Code\harness-config\dsh-update\vendor\prefix\0.1.7-rc.2\node_modules\@deepseek-ai\` (packages at `0.1.7-rc.2`).

Labels used throughout: **observed** = read from a named file and line, or measured; **inferred** = follows from the code but was not executed against the live home.

---

## 1. Headline answer

## `LAZY (new sessions only)` — the candidate does **not** rewrite existing v3 logs in place, and does **not** touch them at boot.

It writes a **new sibling generation file** beside the old one, and only for sessions that are opened **for writing**. Everything else leaves the v3 file byte-identical.

### Evidence

`dsh-session-persistence-jsonl@0.1.7-rc.2` — `lib/index.js`:

| line | what it establishes |
|---|---|
| `731` (`logSuffix(compression)`) + `761` (`generationLogFilename`) | the filename is `session.v<version>.jsonl<suffix>` — so a v4 generation is a **different filename** from `session.v3.jsonl.zstd` |
| `937-939` (`logPath`) | the append target is always `generationLogPath(root, cwd, id, SESSION_FORMAT_VERSION, compression)` — i.e. `session.v4.jsonl.zstd` |
| `1895-1902` (`assertGenerationPaths`) | **observed:** `const expectedSource = generationLogFilename(sourceVersion, …)`, `const expectedCurrent = generationLogFilename(currentVersion, …)`, and it requires `dirname(sourcePath) === dirname(currentPath)`. The migration's `currentPath` is a **sibling** of `sourcePath`, never the source itself. |
| `2077` (`publishPreparedMigration`) | **observed:** `let staged = await writeSyncedTemp(currentPath, suffix, compression, artifact, options.format, void 0, internals)` — the migrated bytes go to a **temp file**, not to `sourcePath` |
| `1952` (`writeSyncedTemp`) | **observed:** `path = join(dirname(currentPath), \`session.migration.${internals.randomToken()}${suffix}.tmp\`)` — the temp name confirms the appended file is likewise not the source path |
| `2084` → `publishCurrentExclusive`, defined at `2023-2043` | **observed:** `const published = await publishCurrentExclusive(staged.path, currentPath, internals)` (called at `:2084`) — `currentPath`, not `sourcePath` |
| `2012`, `2020` (`removeTemporary`, `removeCommittedTemporary`), called at `2000`, `2093`, `2106`, `2114` | **observed:** the only `rm` calls in this path remove `staged.path` — the `.tmp`. There is **no unlink of `sourcePath` anywhere** in the module. `rm(` occurs in the whole file only at `2012`, `2020` (both the stage), plus `603`, `1611`, `3146`, `3150`, `3164` (unrelated: process-exit staging and Win32 temp cleanup). No call site resolves to a generation path. |
| `2603-2627` (`requireStoredLog`) | **observed:** `if (selected.sourceVersion < SESSION_FORMAT_VERSION) { … this.loadStoredMigration(…) }`. Migration is prepared **in memory** on read-open; it is **not** published. |
| `2680-2740` (`prepareStoredMigration`) | **observed:** the doc comment is literally *"Decode one historical generation **without publishing a successor**."* |
| `2492-2495` in `open(id, access, options)` | **observed:** `const prepared = await this.requireStoredLog(...)` and then **`if (prepared.status === "prepared") stored = await this.publishStoredMigration(id, prepared)`** — i.e. publication happens **only inside `open(…, "write", …)`**. |
| `2431-2446` (`create`) | a brand-new session is created at `logPath(...)` = `session.v4.*` from the start. |
| `dsh-agent-loop@0.1.7-rc.2` `lib/index.js:1929` (inside `resumeWith`, defined `:1912`) | **observed:** `handle = await raceAbortCall(() => persistence.open(id, "write", { signal: fused }), …)`. The one production caller that opens **write** is **resume**. |

Boot and listing paths do **not** migrate:

- `listArtifacts` (`3031-3057`) calls `readGenerationHeader` + `this.listGenerations(...)`; it never calls `requireStoredLog`/`publishStoredMigration`.
- `dsh-workspace@0.1.7-rc.2` `lib/index.js:893` — `return (await this.ctx.sessionPersistence.list()).map((snapshot) => snapshot.header)` — the startup workspace registry is **list-only**.
- `dsh-bin@0.1.7-rc.2` `lib/bin.js:100-136` (`parseDshArgs`) exposes only `plugin`, `--dump-config`, `--dump-config-schema`, `--dump-default-config`. **There is no bulk `migrate`/`upgrade` subcommand.** `dsh-session-persistence-jsonl` exports only `JsonlCompressionSchema` and the default plugin (`3527`), so no standalone migration entry point exists either.

**Consequence (observed):** a v4 engine started against this home leaves all 1,256 existing files untouched. Each session converts the **first time it is resumed**, and nothing else in this deployment resumes sessions at boot — `C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml` contains no `resumeSessionId`, and `profiles\mesh\cordis.patch.yml` matches nothing for `resumeSessionId|sessionId:|agent-loop` (grepped). So the conversion is **per-session and lazy**.

**Measured corpus baseline (observed, so the "before" state is on the record):** a read-only decode of `C:\Users\ezabz\.dsh\sessions` found **1,256 files, all 1,256 named `session.v3.jsonl` with suffix `.zstd`, and all 1,256 first-line headers carrying `"version":3`** — 0 files of any other version. 397,292,678 bytes (378.7 MiB). **No session directory held more than one file** (1,257 session directories checked; every one held exactly 1 file) — so there is currently no v3/v4 pair anywhere, and no hidden shadowing yet.

---

## 2. Per-store comparison

| store | baseline format | candidate format | candidate reads baseline? | baseline reads candidate? | codec direction | derivable? | **verdict** |
|---|---|---|---|---|---|---|---|
| `sessions/` 378.7 MB / 1,256 files | `session.v3.jsonl.zstd`, header `version:3` (all 1,256 **observed**) | writes `session.v4.jsonl.zstd`, header `version:4` | **YES** — `sessionFormatCatalog.readHeader` returns `migration-required` (`dsh-session-format/lib/index.js:319`) | **NO** — v4 header > its `currentVersion:3` → `status:"unsupported"` (`dsh-session-format/lib/index.js:301-306`) | `v3→v4` only; **no `vX→vY` with `Y<X` exists in either install** | **NO** — irreplaceable | **ONE-WAY** |
| `storages/session_projcache/` 24.3 MB / 1,257 records | unit stamp `version:7`, record `identity.formatVersion:3` (**observed**, sampled record) | same unit `version:7`; records rewritten with `formatVersion:4` | YES (never rejected as a domain) | YES (numeric version is unchanged) | none needed — `version:7 === version:7` (`dsh-session-projection-cache/lib/index.js:92` both builds) | **YES** — pure fold cache | **SAFE** (cache misses, never data loss) |
| `storages/workspace.json` 5,090 B | `unit:{name:"workspace",version:2}` (**observed**) | `version:2`, **same** | YES | YES | none | NO — registry | **SAFE** |
| `attachments/` 215 MB / 723 files | `DSH_HOME/attachments/v1`, sha256-addressed | **same root**, `dsh-attachment-local/lib/index.js:996` candidate vs `:986` baseline | YES | YES | none | NO — but content-addressed, never rewritten | **SAFE** |
| `.credentials.yaml` 223 B | `version: 1` + `refs:` (**observed**) | `DOCUMENT_VERSION = 1`, accepts v1 | YES | YES | none | NO | **SAFE** |
| `profiles/` 42 files | composition YAML + per-profile pnpm tree | same layout | YES | YES | none | NO | **SAFE** |
| `.agent-presets/` 17 files / 3 dirs | read via `USER_PRESET_DIR = ".agent-presets"` | **no reference to it anywhere in the candidate** | n/a — **never read** | n/a | none | NO — hand-authored | **SAFE (inert, not deleted)** |
| `settings.yaml` 1,046 B | read by `dsh-settings-file` (`lib/index.js:32`) | candidate has **no** `dsh-settings-file`; nothing in the candidate opens `resolveDshHome()/settings.yaml` | not read | n/a | one-way, but not applied here (see §3.5) | NO | **SAFE (file untouched)** |
| `.anonymous-user-id` 37 B | `dsh-anonymous-user-id` | package `lib/index.js` **byte-identical** both builds | YES | YES | none | NO | **SAFE** |
| `llm-deepseek/files-v3.json` 9,310 B | `formatVersion !== 3` rejected | same check, same path `DSH_HOME/llm-deepseek/files-v3.json` (candidate `:781,:802,:804`) | YES | YES | none | YES-ish (re-uploadable) | **SAFE** |
| `health/`, `spend-guard/`, `governor/`, `mesh/`, `multi-window/`, `tools/`, `logs/`, `sync-*` | — | — | — | — | — | — | **OUT-OF-SCOPE** (see below) |
| `cache/` | **absent** (`Test-Path` false) | candidate would use it | n/a | n/a | none | YES | **SAFE (not present)** |
| session-query SQLite (absent on disk) | `PRAGMA user_version = 8` | `dsh-session-query-sqlite` **byte-identical** both builds | YES | YES | none | YES | **SAFE (not present)** |

### Why the OUT-OF-SCOPE rows are out of scope

Attributed by grepping every `*/lib/index.js` in the candidate for the directory name:

- `health`, `spend-guard`, `governor`, `mesh`, `multi-window`, `sync-*` — **zero upstream references**. These are this deployment's own plugins, scripts and browser profiles. Note `mesh/` is 7,372 files / 3.1 MB and `multi-window/` is the ~1 GB browser profile.
- `tools/` — the only upstream hit is `dsh-spill-policy/lib/index.js:126` (`const inject = ["tools"]`), which is the **tool service**, not a path. `C:\Users\ezabz\.dsh\tools` contains only `mcp\{package.json,package-lock.json,node_modules}` — a hand-installed MCP tree. Upstream does not read or write this path.
- `logs/` — upstream-owned (startup diagnostics write there, `dsh/lib/bin.js:150` comment: *"save a private, uniquely named report under DSH_HOME/logs"*), but it is append-only diagnostics. Nothing in either build parses it as state, so a format change cannot break it. Not audited further.

---

## 3. One-way and breaking consequences, with mitigations

### 3.1 `sessions/` — `ONE-WAY` (the only true one-way)

**What happens, in plain language.** The moment a session is resumed under 0.1.7, DSH writes a *second* file next to the old one — `session.v4.jsonl.zstd` — and from then on writes only to that file. The old `session.v3.jsonl.zstd` is **left completely intact and unmodified**. From that point:

- Every later version, including 0.1.5, picks the **highest-numbered** generation in the directory as the authoritative one.
- 0.1.5 therefore opens **v4**, not the v3 file that it can read.
- 0.1.5's version gate (`dsh-session-persistence/lib/index.js`, `sessionFormatVersionRefusal`) returns the `version > SESSION_FORMAT_VERSION` branch: *`session "<id>" uses log format v4, but this harness reads only v3: the log was written by a newer harness — upgrade the harness to open it`* (message identical in both builds — the candidate's copy is at `dsh-session-persistence/lib/index.js:138`; only its package `lib/index.js` and `package.json` differ between the two installs, and not in this string).
- On the **listing** path 0.1.5 does not even show an error: `listArtifacts` catches `SessionFormatUnsupportedError` and `continue`s (`dsh-session-persistence-jsonl/lib/index.js:2874`, inside `readGenerationHeader` reached from `listArtifacts`). **The session silently disappears from the sidebar.**
- On the **open** path it is a hard failure, not a silent one (`requireStoredLog:2629-2637`; `resolveCurrentLog:2850-2861` throws at `:2857` for a future generation).

Both facts are read directly from the **baseline's own** code and re-checked there: `resolveGenerationInDirectory` at `:3160-3192` (**observed:** `generations.sort((left, right) => right.version - left.version)[0]`) and `readGenerationHeader` at `:2890-2924` (**observed:** `:2914` substitutes the "upgrade the harness" reason when `result.storedVersion > SESSION_FORMAT_VERSION`, where `SESSION_FORMAT_VERSION = 3` at `dsh-session/lib/index.js:56`).

**Mitigation that makes it safe.** The v3 file is not destroyed, so this is recoverable by deletion of the *new* file, not by restore:

1. **Cold copy of `sessions\` (and `storages\`, `attachments\`, `.credentials.yaml`) to a location outside `~/.dsh` before the upgrade.** Kept as a rollback point, not as the rollback mechanism.
2. **If you roll back to 0.1.5:** remove only the `session.v4.jsonl.zstd` files. Every v3 original is still in its own directory; deleting the newer sibling restores 0.1.5 to full read/write access with zero data loss. Restoring the cold copy wholesale would *undo* any 0.1.7 work, so use it only as insurance, not as step 1.
3. Do **not** expect `dsh` to have a downgrade command: none exists in the candidate's CLI.

**Status:** I could not find any configuration knob that makes the candidate write v3 instead of v4. `logPath` (`:937-939`) always uses `SESSION_FORMAT_VERSION`; there is no override in the `Config` schema (`:2374-2377` — only `root` and `compression`). **Inferred:** a format downgrade switch does not exist in 0.1.7-rc.2.

### 3.2 `sessions/` — the *second* one-way edge, which is the one that could actually cost data

**Observed in the migration code itself:** `assertV4RetiredSyntax` (`dsh-session-format-v3-to-v4/lib/index.js:172-215`) **refuses** some v3 content outright, and a refusal during migration means the session **cannot be opened for writing at all** under 0.1.7. The refusals are:

- `:174` — event type `tool/code-dispatch` or `tool/code-dispatch-start` with `ignorable !== true` → `SessionFormatUnsupportedMigrationError`
- `:178` — `request/header` whose `data.header` has a `system` key
- `:157` — any content block of type `tool-result` inside `user/message`, `assistant/message`, `developer/message`, `team/message/queued`, `agent/inbox/spliced`, `session/title-llm-request`, `compaction/summary`, `tool/ptc-dispatch`, or a stream `block-end`/`block-start` with that type

On refusal the candidate is explicit and safe: `dsh-session-persistence-jsonl/lib/index.js:2767` — *`source v${error.fromVersion} artifact remains unchanged`* — and `sourceVersion >= format.currentVersion → Error` at `:2121`. Nothing is half-written.

**I checked this against the live corpus rather than assuming (observed).** A read-only pass over all 1,256 logs decompressed **192,468 zstd frames / 353,230 events** (0 decompression failures) and JSON-parsed each event:

- `tool/code-dispatch` (non-ignorable): **0**
- `tool/code-dispatch-start` (non-ignorable): **0**
- `request/header` with `header.system`: **0** (`request/header` does not occur at all)
- `tool-result` block in any interpreted content slot or stream chunk: **0**

A second read-only pass over the same corpus classified all **141,190 message-bearing slots**, and **0** of them lacked a valid `source.kind` (which `assertV4SourceRowAdmission`, `:142-152`, would refuse). Source kinds present: `tool` 75,107 · `model` 53,752 · `plugin` 4,206 · `user` 3,409 · `skill-catalog` 1,277 · `agent-message` 1,265 · `agent-instructions` 1,056 · `subagent-settled` 909 · `goal` 209.

**Verdict on this edge: no session in the current corpus would be refused by the v3→v4 migration.** *Inferred, not observed:* the migration would therefore succeed for all 1,256 sessions. I did not execute the codec, so this is a strong inference from two independent properties (no refused syntax; every message attributable), not a proof.

**Producer renaming — a cosmetic one-way loss, observed.** `producerKind` (`:87-93`) rewrites `plugin` sources: `@deepseek-ai/dsh-system-prompt` + role `system` → `system-prompt`; `tool-jobs`, `dsh-session-title-llm`, `tool-goal`, `repeat-tool-reminder`, `user-approval` → themselves; `compact` → `compact-checkpoint`; **anything else, including `@deepseek-ai/dsh-system-prompt` with a non-`system` role, → `plugin:<name>`**. The live corpus contains **1,254** `@deepseek-ai/dsh-system-prompt` sources whose role is **`user`**, plus **5** `compact`. Those become `plugin:@deepseek-ai/dsh-system-prompt` and `compact-checkpoint` respectively in the v4 file. This is lossless in content but **not reversible** — 0.1.5 could not be expected to reconstruct the original producer strings from a v4 file even if it could read one, and it cannot.

### 3.3 `storages/session_projcache/` — `SAFE`, with a deliberate cache miss

**Observed:** the live record `session-160208ad-…json` carries `unit.version = 7` and `record.identity.formatVersion = 3`. The candidate keeps `version: 7` (`dsh-session-projection-cache/lib/index.js:92`, with `compatibleVersions: [3,4,5,6]` at `:93-98`), and a v4-log session's header carries `version: 4`, so the identity becomes `formatVersion: 4`.

**Observed:** the reader is a strict equality — `currentLifecycleMatches` (`:399-401`): `stored.formatVersion === expected.formatVersion && lifecycleIdentityMatches(...)`. So **every existing cache record is invalidated on the first v4 read**, because `3 !== 4`. `predecessorIdentityMatches` (`:403-405`, `formatVersion < expected`) is used **only** by `cachedPredecessorTitle` (`:214-219`) as a zero-I/O listing hint — it never seeds a fold.

**Plain language:** the projection cache is a fold shortcut, not an authority (`:113-117` — *"a row is possibly stale… but never wrong; a `ver` mismatch discards the row instead of migrating it"*). The first open of each session under 0.1.7 replays its log tail and rewrites the cache. Cost: **slower first open per session**, no data loss, no user-visible corruption. **No action needed.** One caveat, **inferred:** the 24.3 MB of cache files are not deleted, just superseded — expect roughly that much dead weight until each session is opened.

### 3.4 `storages/workspace.json` — `SAFE`

**Observed:** live file is `{"unit":{"name":"workspace","version":2},"global":{...}}`. Both builds declare `name: "workspace", version: 2` (`dsh-workspace/lib/index.js:255-257` candidate vs `:248-250` baseline), and the candidate **adds** a `defaultWorkspaceId` and `pinnedSessionIds` field, both optional/`default([])`, documented at `:236-238` as *"defaulted so records written before the fields parse unchanged"*. A 0.1.5 file therefore parses in the candidate, and the two extra fields are additive. One structural difference worth naming: candidate `:203` hoists `sessionId` to a module const while baseline inlines the same transform at `:211`/`:239` — same behaviour.

**Not observed:** I did not run the zod parse against the live file, so "parses unchanged" is read from the comment and the schema, not executed.

### 3.5 `settings.yaml` — `SAFE` as a file, but the reader moved

Your brief says another gate covers this; here is only the persistence surface, stated precisely.

- **Observed:** the candidate **never opens** `resolveDshHome()/settings.yaml`. A grep across every `*/lib/index.js` for that path returns exactly one hit: `dsh-settings/lib/index.js:348` — `const path = join(profile.home, "settings.yaml")` — which is the **active profile's** home, not the harness home.
- **Observed:** the baseline **does** open it: `dsh-settings-file/lib/index.js:32` — `resolve(config.path ?? join(resolveDshHome(config.dshHome), "settings.yaml"))`.
- **Observed:** `dsh-settings-file` is **absent** from the candidate's package set entirely.
- **Observed — the honest caveat:** the candidate does not simply stop reading settings; it **renames and imports** a legacy document. `importLegacyDocument` (`dsh-settings/lib/index.js:346-363`, scheduled on `ctx.root.loader.await()` at `:339-341`) does `await rename(path, \`${path}.imported\`)` at `:351`, then replays each section through `this.update(ns, values)` into the **active profile's config entry**.
- **Observed:** `profile.home` is *not* the harness home — the only `settings.yaml` on this machine (searched, not recursed) is `C:\Users\ezabz\.dsh\settings.yaml`, and `C:\Users\ezabz\.dsh\profiles\{web,mesh,headless}\` contain **no** `settings.yaml`. So on this deployment `importLegacyDocument` finds nothing, renames nothing, and writes nothing.
- **Inferred:** the root `settings.yaml` becomes an orphaned file that no 0.1.7 code reads. Its values reached the running system only if migration into a profile patch happened elsewhere; that is the other gate's finding, not mine.

**Verdict:** `settings.yaml` is **not rewritten on boot** by 0.1.7-rc.2. Whether the *values* still take effect is a separate question and is not answered here.

### 3.6 `.agent-presets/` — `SAFE (inert)`, confirmed

**Observed:** the string `.agent-presets` occurs in the baseline as `USER_PRESET_DIR`, declared at `dsh-agent-presets/lib/index.js:195` and again at `lib/invariant.js:194` and `lib/types/discovery.js:48`, and consumed at `dsh-agent-presets/lib/index.js:1307` — `path: dshHomePath(USER_PRESET_DIR)` — gated by `config.includeUserRoot` (default `true`, `lib/index.js:1247`, used at `:1306`). A ripgrep for `agent-presets|USER_PRESET_DIR` across **every `.js` file in the candidate** returns **zero** hits on `.agent-presets` — the five candidate matches are all the unrelated invariant/UI **id string** `"agent-presets"` (`dsh-agent-preset-registry/lib/invariant.js:803`, `lib/types/invariant.js:11`, `dsh-client-ui-agent-preset/lib/client.js:1698`, `dsh-client-ui-settings-general/lib/client.js:249`, `dsh-cordis-client-runner/lib/client.js:4746`). The candidate replaces the package with `dsh-agent-preset-registry`, which reads presets from composition YAML.

**Confirmed:** the directory is **still present** with all 3 preset dirs (`cordis-bg`, `yocheved`, `zabz`) and 17 files. Nothing in the candidate deletes it. It is inert, not destroyed.

### 3.7 Every other audited store — no action

- **`attachments/`:** the root is `join(resolveDshHome(config.dshHome), "attachments", "v1")` in **both** builds (candidate `dsh-attachment-local/lib/index.js:996`; baseline `:986`). The live directory contains exactly one entry, `v1`. `normalizedImagePath` (`:296-298`) addresses by `sha256.slice(0,2)` + digest — content-addressed, append-only, never rewritten by a session format change. The v4 codec still carries `attachmentId` on system images (`dsh-session-format-v3-to-v4/lib/index.js:231`, `:276`), so image references survive migration. However, the two `dsh-attachment*` `lib/index.js` files **are** byte-different between builds, and I did not read the diff in full — see §4.
- **`.credentials.yaml`:** `dsh-credentials/lib/index.js` and `dsh-credentials-local/lib/index.js` are **byte-identical** between builds. `DOCUMENT_VERSION = 1` (`:124`), accepted at `:151` (`if (fields["version"] !== 1) throw …; this build reads version 1`), and `:150` errors loudly on a pre-release flat layout. The live file is already `version: 1`. It is not rewritten on boot — writes are per-key patches under a cross-process lock (`:34-35`, `:66-75`).
- **`llm-deepseek/files-v3.json`:** the filename still contains `v3` in **both** builds, still validated as `index.formatVersion !== 3` (candidate `:781`; baseline `:743`), still at `DSH_HOME/llm-deepseek/files-v3.json` (candidate `:802,:804`; baseline `:764,:766`). **Cosmetic trap worth naming:** the `v3` in this filename is the *upload-index* format, unrelated to the *session* format. Seeing `files-v3.json` on 0.1.7 does **not** mean session logs are v3.
- **`.anonymous-user-id`:** `dsh-anonymous-user-id/lib/index.js` byte-identical. Live value present and well-formed.
- **`profiles/`:** composition YAML plus per-profile pnpm trees. `profiles/web/cordis.yml` is `[]` with the instructions in its header comment, unchanged in shape. No version marker is read or written by either build at this path.
- **`cache/`** does not exist (`Test-Path` returned `False`), so the candidate's `dshCachePath` root is not in play.
- **No SQLite file exists** anywhere under `~/.dsh` (bounded `-Filter *.sqlite` search and a top-level name match both returned nothing), and `dsh-session-query-sqlite/lib/index.js` is byte-identical between builds (`PRAGMA user_version = 8` at `:117`). No action.

---

## 4. What I could not determine

Every item below is a real gap. Where I state a gap I say what would close it.

1. **I did not execute the v3→v4 codec against a live log.** My proof that migration succeeds for the whole corpus is two independent code-derived properties plus a byte-level scan, not a run. *What would settle it:* in a throwaway `DSH_HOME` under `%TEMP%` (never the live home), copy one session directory and call `prepareJsonlMigration` on it, then assert `artifact.header.version === 4` and compare the event count to the source. Not run here because the safety rules forbid writing a test session under the live home and I chose not to construct a synthetic home inside this session's scope.

2. **I did not diff the two `dsh-attachment*` packages in full.** I confirmed the root path and the addressing scheme are the same, and that v4 still carries `attachmentId`. I did **not** read every changed line, so an attachment *variant/normalisation* format change would have escaped me. *What would settle it:* a full `Compare-Object` of `dsh-attachment/lib/index.js` and `dsh-attachment-local/lib/index.js` across the two installs.

3. **`dsh-session-query` (not `-sqlite`) differs between builds and I did not read the diff.** The live deployment has no query database on disk, so this could not bite *today* — but if any profile turns the query store on, the difference is unaudited. *What would settle it:* read the `dsh-session-query/lib/index.js` diff.

4. **I did not verify that `cachedPredecessorTitle` behaves identically in practice.** I confirmed both builds define `predecessorIdentityMatches` (candidate `:403-405`, baseline `:383-384`) and both expose `cachedPredecessorTitle` (candidate `:214`, baseline `:210`), but the candidate's signature dropped the `inheritedEventCount` parameter (candidate `cachedPredecessorTitle(meta)`, line `:214`; baseline `cachedPredecessorTitle(meta, inheritedEventCount)`, line `:210`). That is a call-site signature change I did **not** trace through every caller. *What would settle it:* grep the candidate for `cachedPredecessorTitle(` call sites and confirm each passes only `meta`.

5. **I could not determine whether the candidate has any way to make an already-migrated session readable by 0.1.5.** I found no downgrade codec and no CLI. A journal/export path (`dsh-session-log-export`) can emit log text, but nothing re-emits a v3 artifact. **Inferred:** rollback requires deleting `session.v4.jsonl.zstd` files. *What would settle it:* a full read of `dsh-session-log-export/lib/index.js` and `dsh-session-format`'s exported surface for any inverse operation — I read the exports (`dsh-session-format/lib/index.js:491`, `dsh-session-persistence-jsonl:3527`) and found none, but I did not read the export package end to end.

6. **I did not confirm which code path, if any, opens a session `write` without user intent.** I traced `persistence.open(id, "write", …)` to exactly two production call sites in the candidate: `dsh-agent-loop/lib/index.js:1929` (`resumeWith`) and `dsh-message-feedback/lib/index.js:276` (write only when `write` is truthy). I did **not** enumerate every RPC that could reach `dsh-message-feedback` with `write: true`, nor read `dsh-api-session-controller`. If some scheduled or API-driven path resumes sessions unattended, the lazy conversion becomes less lazy than §1 describes — the *direction* is unchanged, but the *rate* would be. *What would settle it:* read `dsh-api-session-controller/lib/index.js` and `dsh-schedule/lib/index.js` for `resume`/`open` usage.

7. **The "1,257 vs 1,256" count difference is unexplained and I am not papering over it.** `sessions\` contains **1,257 project directories** but the file walk found **1,256 files** in **1,256 session directories**, and a per-directory check reported no empty project directory and no directory with a file count other than 1. Consistent with the earlier known figure of 1,255/1,256 files, one project directory appears to hold no session directory, but my check did not identify which. *What would settle it:* a targeted listing comparing project-directory names against session-directory names. It does not change any verdict — all 1,256 logs were located, decoded and classified.

8. **I did not test the baseline's behaviour against a real v4 file.** The claim in §3.1 — that 0.1.5 picks v4 and refuses it — is read from the baseline's own `resolveGenerationInDirectory:3185` and `readGenerationHeader:2914`, re-read twice. I did not construct a directory holding a synthetic v3+v4 pair and run the baseline against it. *What would settle it:* exactly that, in `%TEMP%`, with `resolveGenerationInDirectory` called against a synthetic directory containing two zero-byte files — no engine boot and no live state required.

---

## 5. Reproduction commands

Everything below is read-only against the live home and was what produced the numbers above. Scripts are under `%TEMP%\dsh-audit\` (`scan.mjs`, `scan-syntax3.mjs`, `scan-sources.mjs`, `probe-frames.mjs`).

```
node %TEMP%\dsh-audit\scan.mjs          # filenames, suffixes, first-frame header versions, sizes
node %TEMP%\dsh-audit\scan-syntax3.mjs  # per-frame decode + JSON parse; counts every v4-refused construct
node %TEMP%\dsh-audit\scan-sources.mjs  # every message-bearing slot's source.kind
```

One correctness note that matters if anyone re-runs this: **each session log is many separate zstd frames, one per record** (a probe of `session.v3.jsonl.zstd` found 149 frame magics; frame 0 is the header line, frame 1 the descriptor, and so on). `zlib.zstdDecompressSync` on the whole buffer returns **only the first frame** — 246 bytes of header, not the log. My first two scans were wrong for exactly that reason and reported a clean, meaningless zero; the corrected scan (`scan-syntax3.mjs`) decompresses frame by frame. Any future check of this corpus must not trust a single-shot zstd decode.
