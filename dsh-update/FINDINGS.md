# Findings — examined DSH versions

This file is the **durable** record of what the pipeline concluded about each upstream version.
`state/` (where `diff.json`, `report.md` and `verify.json` actually land) is git-ignored, so a
conclusion that lives only there does not survive a fresh clone. Anything a future session needs to
know goes here.

Written by hand from the pipeline's own artifacts, with every claim re-checked against the fetched
install. Relative to the pin `0.1.5-rc.1` (the `@deepseek-ai/dsh` launcher version; 230 of the 240
installed packages are `0.1.5-rc.2` — see `SPEC.md`, "The version is a set, not a number").

## 0.1.5-rc.3 — SAFE. Nothing breaks.

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

## Not yet examined

`0.1.5-rc.2`, `0.1.6-alpha.1`, `0.1.6-alpha.2`, `0.1.7-alpha.1`, `0.1.7-alpha.2`. One
`fetch` + `analyze` + `patch-effect` each answers them.

## Nothing has been promoted

`multi-window/windows.json` is byte-identical to before this work
(sha256 `765B8F65CFFEA6F277C99E7C4DE45147C13CE5ED17B9454E1A21E112D7798E1A`, no `dshInstall` key), and
the live engine on port 3099 was never started, stopped or restarted.
