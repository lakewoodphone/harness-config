# dsh-update

Makes upgrading the DSH harness (`@deepseek-ai/dsh`) safe on a deployment that has ~40
customizations naming upstream artifacts by exact string. Upstream can remove something we depend on
**without any error** — a patch or settings key that stops applying is silently a no-op. This
pipeline detects that before it can reach a live engine, and gates the upgrade on a real boot test.

Frozen interface: `SPEC.md`. This file is the operator view of it.

## Run it

`bin/dsh-update.ps1` is the only entry point. No verb prints `status`.

```
check -> snapshot -> fetch <ver> -> analyze <ver> -> patch-effect <ver> -> verify <ver> -> plan <ver> -> promote <ver>
```

| Verb | Writes | Notes |
|---|---|---|
| `status` | nothing | the pin, the real engine path and version (read by running the engine), what the registry offers, per-candidate analysis state, whether an upgrade is available |
| `check` | nothing | registry query; classifies every published version against the pin |
| `snapshot` | `state/baseline/{contract.json,tree.json}`, refreshes the pin's hashes | describes the **pinned** engine. Read-only against that engine (`--dump-config`) |
| `fetch <ver>` | `vendor/prefix/<ver>/**` | the only `npm install` in the pipeline, into a managed prefix. Never the npx cache, never a global prefix |
| `analyze <ver>` | `state/candidates/<ver>/{consumed.json,contract.json,tree.json,diff.json}`, and `report.md` when `lib/report.mjs` exists | runs our-consumption scan, describes the candidate engine, composes its tree, then diffs. `analyze` alone is enough: it produces everything the diff needs |
| `patch-effect <ver>` | `state/candidates/<ver>/patch-effect.json` (+ `tree-default.json` arms if missing) | **does every patch WE own still have its intended effect?** Compares each patch entry's `config`/`disabled` against the candidate's composed row, using the engine's own unpatched `--dump-default-config` tree as the control. Also catches a patch silently swallowing a **new** upstream default. Exit `1` only on a real `BREAKS` |
| `verify <ver>` | `state/candidates/<ver>/verify.json` | the gates; `--full` adds a real web-profile boot |
| `plan <ver>` | nothing | exactly what `promote` would change, file by file, with old and new values and whether each file exists |
| `promote <ver>` | `state/pin.json`, `multi-window/windows.json`, `state/history/events.tsv`, `state/logs/` | gated; backs up before writing; **never restarts the engine** |
| `rollback` | `state/pin.json`, `multi-window/windows.json`, history | restores the predecessor pin and the launcher knob; also never restarts |
| `report <ver>` | nothing | the report path, the diff verdict and the gate outcomes |


`--json` on any verb prints one JSON object on stdout. `--help` prints the table.

## Promote in one paragraph

`promote` refuses unless all three hold: a `verify.json` with `pass:true` whose `contractSha256`
equals the candidate contract **on disk right now**; a `diff.json` whose verdict is not `BREAKS`; and
a candidate strictly newer than the pin. It then copies `multi-window/windows.json` to a
`.bak-dsh-update-<UTC>` sibling, writes `dshInstall` to `vendor/prefix/<ver>`, writes `pin.json` with
`managed:true` and the entire previous pin as `predecessor`, appends one history row, and prints a
notice. **There is no flag that bypasses the verify gate — a bypass is a code change.**

## The change takes effect at the next engine boot

`promote` and `rollback` write state. Neither starts, stops nor restarts an engine, ever: the engine
serves the session running the promote, so restarting it would kill that session. The change lands
the next time an engine is started by a human or by a reboot.

## What this does NOT yet catch — read this before trusting a `SAFE`

A `SAFE` verdict is a statement about what was **checked**, and the honest list of what was not is
short but real. All of it is measured, not guessed (evidence: `SPEC.md` sections C1-C14).

1. **A settings key the candidate has quietly stopped honouring is invisible to every gate here.**
   Measured 2026-09-23: an unknown top-level key, an unknown key inside a known section, a wrong
   value type, an out-of-range number and an invalid enum value **all boot with exit 0 and print no
   diagnostic at all**. The engine refuses only a document it cannot *parse* (`DUPLICATE_KEY` →
   exit 1). So gate G4 catches a malformed settings document and a hard boot failure — not a key that
   silently became a no-op. The fix is to read the engine's own *effective* settings back from the
   settings controller and assert every key we set is present with our value; it is specified and
   **not yet implemented**.
2. **A patch target is checked by comparison, not by the engine's `patched by` comment** — and that
   is deliberate. The comment is emitted only for some patch shapes: an entry setting only
   `disabled: true` applies perfectly and carries no annotation. Asserting on it produced two false
   `BREAKS` on a candidate that breaks nothing (see `SPEC.md` C1/C13). Everything in
   `patch-effect.mjs` asserts on the composed value against the unpatched arm instead.
3. **Attribution is unstable between runs.** The composed tree's `patchedRowIds` disagreed with a
   fresh dump on one id for the same engine. Never key a verdict on it.
4. **Agent presets are outside the composed tree entirely.** Presets contribute **zero** rows to
   `--dump-config`; 14 preset-exclusive row ids appear in the dump in no form. Preset-level breakage
   is caught only by the contract diff (`B1`/`B2`) — a preset `name:` that no longer resolves is
   visible there, but a preset whose *behaviour* changed is not. A dedicated preset-resolution gate
   (G7) is specified and **not yet implemented**.
5. **No session-format gate yet.** `@deepseek-ai/dsh-session-format-catalog` declares
   `currentVersion: 3`, and the live home holds 1,095 session files, all `session.v3.jsonl.zstd`. A
   candidate that starts writing v4 makes `rollback` unable to read that history — a one-way door
   that nothing here inspects. Specified as G8 and **not yet implemented**.
6. **The new-upstream-default check only runs when both `--dump-default-config` arms exist.**
   `patch-effect` generates them, and when it cannot it says so and lists the comparison as
   `unverified` — never as a pass.
7. **`--full` is opt-in**, so `verify` alone does not prove the web profile boots; it proves the
   headless profile boots and completes a turn.
8. **A `verify` pass is bound to `contractSha256`**, so editing a `file:` plugin dependency or
   re-resolving a transitive prerelease after verifying makes `promote` refuse. That is intended.

## Secrets

`verify` boots an engine in an isolated `DSH_HOME`, and a headless turn cannot reach a model without
a credential, so `verify.mjs` currently **copies `.credentials.yaml`** into
`state/candidates/<ver>/home/`. That copy is ignored by git twice over — the repo-root
`.credentials.yaml` pattern matches at any depth, and `dsh-update/.gitignore` ignores `state/`
wholesale. **`state/` and `vendor/` must never be committed.** The intended fix is to stop copying it
and pass the key through the child environment instead (`SPEC.md` C14), which was measured working.
`state/candidates/**` therefore should not be treated as shareable.

## Safety invariants

1. Nothing deletes anything. No `rm`, no pruning of the npx cache or `vendor/`; old prefixes stay
   until a human removes them. `fetch` refuses to overwrite an existing prefix.
2. Only `promote` and `rollback` write outside `dsh-update/`, and only to
   `multi-window/windows.json`, after a timestamped backup.
3. Every write outside `dsh-update/` is a backup plus a temp-file-and-rename replacement.
4. `state/history/events.tsv` is append-only and is the audit trail.
5. No verb starts, stops or restarts an engine.
6. Every reading carries its source; an empty or failed read is reported as a failure, never as an
   empty success. A registry that cannot be reached makes `status`/`check` exit non-zero, not "no
   newer versions".

## Rolling back

```
pwsh -File dsh-update\bin\dsh-update.ps1 rollback
```

Restores the `predecessor` recorded in `pin.json` and the matching `dshInstall` value (removing the
key if the predecessor was unmanaged), appends a history row, and says plainly that the restored
engine takes effect at the next boot. With no predecessor it refuses and changes nothing.

## Where state lives

```
dsh-update/state/pin.json                      what we run now
dsh-update/state/baseline/                     the pinned engine's contract + composed tree
dsh-update/state/candidates/<version>/         per candidate: consumed.json, contract.json, tree.json, diff.json, report.md, verify.json
dsh-update/state/history/events.tsv            append-only audit trail
dsh-update/state/logs/                         verbatim engine and invocation output
dsh-update/vendor/prefix/<version>/            a candidate's own npm prefix
```

## Exit codes

`0` ok; `1` bad usage; `2` absent/unusable state (no pin, unparseable config); `3` registry
unreachable; `4` a sibling `lib/*.mjs` is absent or does not export the expected entry point;
`5` a write was refused (config unreadable, prefix already present); `6` fetch failed; `7` a gate or
the composed tree failed; `8` promote/rollback refused a precondition.

## Environment overrides

Read-only diagnostics; none of them change what a verb does except the first two, which exist so
tests never touch the live launcher config.

- `DSH_UPDATE_WINDOWS_JSON` — path of the launcher config to read and write instead of
  `multi-window/windows.json`. Used to test `promote`/`rollback` against a copy.
- `DSH_INSTALL` — an npm prefix containing `node_modules\@deepseek-ai\dsh\lib\bin.js`. Read by this
  tool exactly as `dshw.ps1` reads it.
- `DSH_UPDATE_NPM_TIMEOUT_MS` — registry query timeout (default 90000).
- `DSH_UPDATE_FETCH_TIMEOUT_MS` — fetch timeout (default 900000).
