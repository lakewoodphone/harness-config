# dsh-plugin-remote-fanout

**One agent, running on one node, fanning children out to a different node.**

The harness already has the seam: `ctx.subagents` is a *named-provider registry*
(`@deepseek-ai/dsh-subagent/README.md:69`), and a composition "can offer
in-process, ACP, SDK, Codex, or Claude Code children side by side" (`:12`). What
the fleet did not have is a provider whose children run **on another machine**.
This package is that provider — a second provider beside the built-in `spawn`,
with its own model-facing tool, so a parent agent can delegate locally or
remotely and it shows in which tool it calls.

```
parent agent (node A) ── subagent_remote ──▶ ssh ──▶ fresh `dsh --profile headless`
                                                      on node B: a REAL agent turn
                                                      (full dsh-base toolbelt)
```

It ships with two things around it:

| | |
|---|---|
| `profiles/mesh/cordis.patch.yml` + `bin/install-mesh-profile.mjs` | the **`mesh` profile**: `dsh-base` + `dsh-headless` + this bundle + the agent-presets row. `dsh --profile mesh headless "<task>"` is a dispatcher on any node, because a profile is read at process start — **no engine restart** (P210) |
| `bin/mesh-run.mjs` | the dispatcher CLI: PLACE (broker) → CONFIGURE → RUN → VERIFY → DONE, exit `0`/`10`/`1`, logs under `~/.dsh/mesh/logs/` |

The end-to-end proof — three children on another node, `MESH-HOST` verified from
each child's own report, the parent's node flat, nothing restarted — is
`docs/mesh/70-remote-fanout-proof.md`.

## Local pressure changes where a child goes

A dispatcher that offers everything while its own machine is full is why the mesh sat idle
on 2026-09-17, so `acquire()` reads this machine before it asks the broker
(`docs/mesh/109-pressure-routing.md`):

| this machine, committed vs physical | what happens |
|---|---|
| below **85 %** | nothing changes; the broker is asked exactly what it was asked before |
| at or above **85 %** | the local node is added to the broker's `exclude` hint — the mesh is *asked* to take the child |
| at or above **92 %** AND less than **1.5 GiB** physical available | a local child is REFUSED before the broker is asked, with the reading in the error |
| no reading | behaves exactly as before; unknown is not pressure |

The reading is `\Memory\Committed Bytes` against physical RAM (the quantity
`84-calibration.md` §3 fits its 403 MiB/turn cost in), taken from `plugin-health`'s
snapshot — **one file read, no process** — with a self-probe fallback for a node that has
no plugin-health. Every decision is recorded in the placement ledger, in the engine log,
and in the child's own report, including the case where the broker placed locally anyway.
`bin/mesh-pressure.mjs` reads it from a shell; `bin/mesh-pressure-proof.mjs` reproduces
the three proofs in `109` §4. It takes effect at the next engine start.

## What it is not

- **Not a scheduler.** One plugin row names one `target`. Which node *should* run
  a job is the broker's decision (`docs/mesh/71-mesh-program.md` §2.2); `mesh-run`
  is what turns that decision into this provider's environment.
- **Not continuable.** `prepareContinuable` is deliberately absent, so the seam
  rejects continuable starts on this provider. A remote child is one prompt, one
  final message. The seam names the missing contract itself: *"remote providers
  need an Activation ownership contract before they can support continuable
  children"* (`README.md:170`).
- **Not a script runner.** The child is `node <dsh>/lib/bin.js --profile
  headless "<prompt>"` on the target: a real DSH agent turn with the `dsh-base`
  toolbelt (pwsh/bash, fs, fs-search, jobs, web).

## Proof of location

Every dispatched child is instructed, by this wrapper, to open its report with
`MESH-HOST: <hostname>` (`docs/mesh/71-mesh-program.md` §2.4). Two independent
comparisons must then pass, and **either one fails the run**:

1. the host recorded by the **target's own shell** before any model ran
   (`FANOUT_TRANSPORT_HOST`) must be one of the configured `targetHosts` — this
   catches an ssh alias that silently resolves to the wrong machine;
2. the child's own `MESH-HOST:` line must equal that recorded host — this catches
   a child that did not run where it claims.

With no `targetHosts` configured the check is *recorded but not made*, and the
report says so in as many words. An unproven location is never reported as a
success.

## Why ssh, when a plugin HTTP route is cheaper

`docs/mesh/66-dsh-remote-capability.md` §3 ranks a plugin-owned HTTP route on the
target first, and for a mesh it is the right answer. It is unavailable here for
one concrete reason: **a route exists only once the plugin is mounted in the
target's engine, and mounting a bundle into a running engine needs a restart**
(measured, `docs/dsh-at-scale/90-plugin-health-governor.md` §0). The constraint
this was built under is that no engine anywhere restarts, so the transport that
works today is `ssh` plus a fresh one-shot process. `/api/session/prompt` remains
unusable for a different reason the same document names: the launch token is
minted per process and never persisted.

**And ssh does not work in every direction** — measured, and it is not a bug in
this package. A process launched by **ZABZ-YOGA's** sshd cannot traverse the
symlinks in `$DSH_HOME/profiles/node_modules`, and that is how a DSH profile
resolves its bundles; `ssh <laptop> dsh --profile headless` therefore fails with
`plugin tree failed to load`. The desktop's sshd session has no such problem.
See `70-remote-fanout-proof.md` §4.4 for the probe and the table.

## Mounting it

The package's own `cordis.patch.yml` inserts two rows: the provider
(`id: remote-fanout`) and a second instance of the shipped delegation tool bound
to it (`id: tool-subagent-remote`, `toolName: subagent_remote`,
`maxDepth: provider-managed`, `enableRunInBackground: false`). The built-in
`spawn` tool is untouched.

The provider row carries **no config in the package on purpose** — `target` and
the two paths on it are deployment facts. The profile that mounts the bundle must
supply them, and a patch **replaces** the targeted row's whole config, so every
key is restated (see `profiles/mesh/cordis.patch.yml` for the live example).

Requirements on the target node, and they are the whole list:

1. **Node ≥ 22.18** (the `import.meta.main` floor — below it, `bin.js` exits 0
   having done nothing, silently; `62-worker-runtime.md` §1.1).
2. **A DSH install** whose `lib/bin.js` path is what `remoteDshBin` names, and a
   `DSH_HOME` that can resolve the target profile's bundles.
3. **A credential the child can read** — a `DEEPSEEK_API_KEY` in the environment
   or a `.credentials.yaml` in the child's `DSH_HOME`. The child uses the
   **target's own home** by default, which is `71` §2.3's frozen v1 transport
   shape; `remoteHome` is the escape hatch, and if you use it do **not**
   pre-create `<home>/profiles/node_modules` — `dsh-app-boot` owns that directory
   (`healProfilesModuleFallback`, `lib/index.js:657`) and pre-creating it as a
   junction makes the child's boot fail with `UNKNOWN: unknown error, mkdir`.
4. **An ssh path from the parent's user to the target's user that does not
   prompt** (`BatchMode=yes`; key auth).

## The `posix` shell

`remoteShell: posix` builds a `sh` program delivered on stdin to `ssh <target>
sh -s`. It is unit-tested; **no Linux node has completed a child turn through it
in the field** (`70-remote-fanout-proof.md` §6.2). The shell is a property of the
**target** — `mesh-run` sets it per node, because inferring it from the caller's
`process.platform` sent a PowerShell command to a Linux node and killed every
child with exit 127 (measured 2026-09-16).

## Verification

```bash
node --test test/*.test.mjs     # 35 tests, 35 passing (2026-09-17)
node --check lib/index.js && node --check lib/provider.js && node --check lib/ssh-transport.js && node --check lib/remote-script.js && node --check bin/mesh-run.mjs
```

They cover the script builders (quoting, framing, exit-code propagation), the
parser (including a child that prints the marker words itself and cannot truncate
the frame), the transport (file redirection — **never a stdout pipe**, see
`lib/ssh-transport.js`'s header for the measurement — byte cap, timeout kill,
frame-settled completion, temp-file cleanup), the provider's settlement
vocabulary, and every branch of the location proof.

`bin/install-mesh-profile.mjs --check` exits 0 only when every bundle actually
resolves — the same invariant `install-client-plugins.ps1` guards for the web
profile.
