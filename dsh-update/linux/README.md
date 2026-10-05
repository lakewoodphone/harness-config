# dsh-update / linux

The Linux half of the engine-update story. `../bin/dsh-update.ps1` (and the Node core
behind it) moves the engine on a machine with a **launcher** — it writes `dshInstall`
in `multi-window/windows.json` and lets `dshw.ps1` pick it up. A Linux host has no
launcher: its engine is a **systemd unit with a hardcoded `ExecStart`**, and the owner
of that unit is the only thing that can move it.

This directory holds that counterpart, plus the one invariant that makes it safe.

## Why it exists: an engine and its config are ONE artefact

Measured 2026-10-05, upgrading `secratary` from DSH `0.1.5-rc.1` to `0.2.0-rc.2`.

0.2.0 renamed a family of packages, so the upgrade was engine **plus** a version-coupled
config migration. The first cutover attempt failed its own verification and
auto-rolled-back. `rollback.sh` did its job exactly — it restored the unit file
byte-for-byte (sha256 compared), restored the drop-ins, and swapped the engine symlink
back. It also correctly reported `SKIP_HOME=1`.

It had no idea the config had been migrated, because a **different script** did that.
So the machine came to rest on `0.1.5-rc.1` running `0.2.0` config, and the engine died:

```
TypeError: this.ctx.agentPresets.register is not a function
    at [cordis.init] (.../dsh-agent-preset/lib/index.js:25:37)
    at file:///home/zabz/.dsh/profiles/web/#preset-zabz
```

"Roll back the engine" is half a rollback, and the half left behind is the half that
cannot boot. `lib-configset.sh` exists so that can never happen again.

## The design

**`lib-configset.sh` owns the set** — not the caller, and not the cutover script.
`configset_paths` is deliberately explicit and narrow:

```
settings.yaml
profiles/*/cordis.patch.yml
profiles/*/cordis.yml
profiles/*/package.json
.agent-presets/*/agent.cordis.yml
.agent-presets/*/preset.yml
profiles/node_modules            (the module anchor: a farm of symlinks)
```

**Sessions, storages, credentials, logs and the governor are NOT in it.** A restore that
rolled back live data would be a worse failure than the one being fixed. 8 paths on a
live home.

- `configset_snapshot <dest>` copies each path and writes `manifest.tsv`
  (`<abs path> <TAB> sha256|DIR|LINK <TAB> <backup filename>`).
- `configset_restore <src> [aside]` **moves** the current version aside and copies the
  snapshot back. Never deletes; a restore is itself reversible.
- `configset_verify <src>` asserts the live tree still matches, naming every path that
  differs. Exit 0 only when nothing differs.
- `DSH_CUTOVER_HOME` overrides the home — this is what makes the whole thing testable in
  a sandbox, and what lets `rollback.sh --config-only` be exercised without a blast radius.

`cutover.sh` sources the library and snapshots into `$BK/config-before` **before its
first change**; `rollback.sh` lists the set in its RESTORES table and restores and
verifies it before the restart.

## Run it

```bash
# 1. stage the new engine into its own prefix (never over the live one)
# 2. see what a cutover would do, touching nothing
/home/zabz/_dsh020/cutover.sh
# 3. confirm the engine is idle -- this kills any live turn
/home/zabz/_dsh020/idle-check.sh          # must exit 0
# 4. cut over: snapshot config, atomic symlink swap, ExecStart rewrite, restart,
#    verify, and auto-rollback if verification fails
sudo /home/zabz/_dsh020/cutover.sh --apply --yes
# 5. undo, if needed
sudo /home/zabz/_dsh020/rollback.sh --apply --yes
#    ...or put the config back and leave the engine alone
sudo /home/zabz/_dsh020/rollback.sh --config-only --apply --yes
```

Every verb is a dry run unless given `--apply`. `cutover.sh` never starts, stops or
restarts anything during a dry run.

## Invariants

1. **Nothing deletes anything.** Backups are copies; displaced files are timestamped
   moves; the engine's own `state.json` is written *before* the first change.
2. **The engine and the version-coupled config are snapshotted and restored together.**
3. **The symlink swap is `rename(2)`** (`ln -s tmp && mv -Tf`), so a reader never sees an
   empty or missing `$LINK`.
4. **`ExecStart` is rewritten in place and verified** — exactly one line may change, or the
   script refuses and writes nothing.
5. **A verify failure triggers a rollback that includes the config.**
6. **A reading that fails is reported as a failure**, never as an empty success.

## The launch-token race — read this before changing the wait logic

`verify-live.sh` needs the engine's one-time `?token=`. On 0.2.0 the `dsh web:` banner is
printed **after the MCP servers start**, so a port-open check is *not* proof the token
exists yet. The first cutover waited only for the port, verified ~4 s after restart, found
only the *previous* engines' tokens in the append-only log, got `401` for all of them, and
failed a healthy change. `cutover.sh` therefore waits until some token in the log actually
exchanges for a `303`, up to 150 s, before it calls the verifier.

Related: the gate that signs a phone in reads the token from the unit's stdout append file
at request time, so it survives restarts — but it also means the file always contains
plausible **stale** answers. Always require the token to be *newer than the restart*.

## Platform assumptions — change these for another host

The scripts are proven on one host and are **not yet parameterised**. Every assumption is
a variable near the top of `cutover.sh` / `rollback.sh`; the list to change is:

| Variable | secratary value | what it is |
|---|---|---|
| `UNIT` / `UNIT_FILE` | `phone-engine.service` | the systemd unit that owns the engine |
| `PORT` | `3089` | the engine's port; also derives the stdout log name |
| `LINK` | `/home/zabz/dsh-current` | the stable indirection the unit names |
| `NODE` | `/home/zabz/node/bin/node` | **must be >= the highest `engines.node` floor in the install** |
| `LIVE_PREFIX` | `/home/zabz/dsh-engine` | the engine in use before the cutover |
| `LIVE_HOME` | `/home/zabz/.dsh` | `$DSH_HOME` |
| `TARGET` | `/home/zabz/dsh-install/<ver>` | the staged prefix |
| `TOKLOG` | `/home/zabz/.dsh-phone/engine-<PORT>.log` | the unit's `StandardOutput=append:` file |

Two host facts worth checking first on a new machine, both measured here:

- **`node` on `PATH` may not be the node the unit uses.** On secratary `/usr/bin/node` is
  **v20.20.2** while the unit runs `/home/zabz/node/bin/node` **v22.23.2**, and the 0.2.0
  packages declare `engines.node >= 22.19` (the floor comes from transitive deps such as
  `undici` and `libreoffice-kit`, **not** from `@deepseek-ai/dsh`, which declares none).
  `cutover.sh` computes the real floor from the whole tree and refuses a mismatch.
- **An install run with the wrong node on `PATH` is a silent hazard.** `npm` on this host is
  `#!/usr/bin/env node`, so `npm install` picks v20 unless `PATH` is set explicitly.

## Tests

`prove-configset.sh` exercises the library in a throwaway sandbox under
`/home/zabz/dsh-cutover/scratch/` — it never touches the live home. 19 checks: the set is
8 paths and excludes `sessions/`; verify is clean on an untouched tree; after a simulated
migration verify fails and names web patch, preset and settings; restore makes it match
again; the anchor symlink returns; session data is untouched; the displaced copy holds the
migrated bytes; re-snapshot displaces rather than deletes.

```bash
bash prove-configset.sh
```

The apply path is proven separately by `prove-config-only.sh` at the same location (not
promoted here — it hardcodes this host's paths).

## What this does NOT establish

- **It is proven on secratary and nowhere else.** No other Linux host has run it.
- **The variable table above is a promise, not a test.** Parameterising these scripts for a
  second host is untried work.
- **A restore running as root against the live home is untested.** `cp -a` preserves
  ownership so it should be correct, and the final cutover's config restore ran as root
  successfully, but the sandbox proofs ran as the unprivileged user.
- **The config set is a list someone must extend.** A new version-coupled path that nobody
  adds to `configset_paths` is invisible to both the snapshot and the restore. The
  safeguard is that `sync.py`'s write list and this list must agree — check them together
  at every version bump.
- **It is not the same tool as `../lib/cli.mjs`.** The Node pipeline does contract diffing,
  patch-effect analysis and a full boot gate; this does not. This moves a Linux engine
  safely; `dsh-update` decides whether the move is SAFE. They are complementary, and
  neither has been run as a step of the other.

## The two halves, and what has actually been run where

**`../bin/dsh-update.ps1` is a shim with no logic in it** — it resolves node and execs
`../lib/cli.mjs` with the arguments unchanged. That is why the pipeline's analysis half is
usable on Linux. Measured 2026-10-05 on secratary, node v22.23.2:

```bash
export DSH_UPDATE_WINDOWS_JSON=/tmp/scratch/windows.json   # any JSON; promote writes here
export DSH_INSTALL=/home/zabz/dsh-install/0.2.0-rc.2       # the engine prefix to inspect
node dsh-update/lib/cli.mjs status
```

exit 0, and it reported the real engine (`0.2.0-rc.2`, version read by *running*
`bin.js --version`), the npm dist-tags via a live registry query, and a newer candidate.
The only degraded reading was:

```
note  could not read the live dsh command line: process command lines can only be read
      on win32; this host has no reader installed
```

which costs one line of the report and nothing else.

**So the split is:** the analysis verbs are portable today (`DSH_UPDATE_WINDOWS_JSON`
redirects the launcher knob so `promote`/`rollback` cannot touch a launcher that does not
exist), and `cutover.sh` here is what a Linux **promotion** actually is. `MESH_DSH_BIN`-style
env overrides are the intended seam: `status`/`check`/`analyze`/`patch-effect`/`verify` are
read-only against the live install.

**What has NOT been run on Linux:** `analyze`, `patch-effect`, `verify`, `fetch` and
`plan` have never been executed on a Linux host — only `status` has. Do not read the
paragraph above as "the analysis half is verified on Linux"; it is *demonstrated to
boot and to do real work*, which is a smaller claim.
