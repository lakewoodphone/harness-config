# Harness configuration — single source of truth

**This repository is the authoritative source for every DSH preset, skill, plugin row, and setting
shared across the owner's machines.**

The problem it solves, in the owner's words:

> "we need one source of truth for all the presets plugins and changes we make together or you make to
> your harness, so on the desktop, yoga, and iphone i am always talking to the same you"

## Why it exists

The harness configuration lives in `~/.dsh` on each machine, and nothing keeps those copies
together. Audited 2026-09-11:

| | Desktop | Yoga |
|---|---|---|
| `.agent-presets/` | `cordis-bg` present | **absent** |
| `settings.yaml` size | 169 bytes | 571 bytes |
| `llm-pi-ai` provider block | absent | present |
| `agent-loop.maxParallelToolCalls` | absent | 20 |
| In git? | **no** | **no** |
| Used as default? | **no** — `settings.yaml` says `cordis`, so `cordis-bg` was never switched on | n/a |

So an improvement was authored on one machine, left switched off, version-controlled nowhere, and
invisible to the other two. Meanwhile the settings drifted in the opposite direction. This is the
same failure as the three `secretary.db` copies: **several things claim to be the same thing, and
none of them declares which one is true.**

## What belongs here, and what does not

| Belongs in git | Stays machine-local |
|---|---|
| Presets (`presets/*/agent.cordis.yml`, `preset.yml`, skills) | `sessions/` — per-machine transcripts |
| Non-secret settings (`settings/base.yaml`) | `.credentials.yaml` — secrets |
| Machine overrides (`settings/machines/<host>.yaml`) | `.anonymous-user-id` |
| Sync tooling and docs | `profiles/node_modules/` — installed packages |
| Local plugin packages (`packages/*`) | |

**Never commit secrets.** Credentials stay in `.credentials.yaml` and are referenced by env var name
(`apiKeyEnv: DEEPINFRA_API_KEY`), never by value.

## Layout

```
harness-config/
├── presets/                  # canonical agent presets, one dir each
│   └── cordis-bg/            # background-first shell policy
├── packages/                 # local DSH plugin packages
│   └── plugin-cost/          # /cost command + composer cost pill, with a cited rate card
├── profiles/                 # the profile patch layer we own (see below)
│   └── web/cordis.patch.yml  # applied after every bundle layer, on the `web` profile
├── multi-window/             # the window fleet: one engine, many windows
│   ├── dshw.ps1              # supervisor + control command
│   ├── dshw.cmd              # wrapper, so `dshw up` works from any shell
│   └── windows.json          # the single source of truth: mode, ports, one row per window
├── settings/
│   ├── base.yaml             # settings identical on every machine
│   └── machines/
│       ├── ZABZ-YOGA.yaml    # per-machine deltas
│       └── ZABZ-TECH.yaml
├── scripts/
│   └── sync.py               # apply this repo onto the local ~/.dsh
└── docs/
    ├── DECISIONS.md
    └── multi-window/         # analysis, measured performance, research, open questions
```

### The window fleet (`multi-window/`)

Run `dshw` for help. The short version:

```sh
dshw up           # start the engine if needed, open every enabled window
dshw new          # one more window, now
dshw status       # per-window truth: port, pid, window count, memory
dshw health       # idempotent: start ONLY what should be listening and is not
dshw watchdog on  # schedule `dshw health` every 5 minutes
dshw autostart on # schedule `dshw up` at logon, so the windows come back
dshw doctor       # resolve every prerequisite and name what is missing
```

`windows.json` is the manifest. **`mode` is `single` and that is the only supported value**: one engine,
many windows — because a window is only a browser client, because a second writer on one `DSH_HOME` has
corrupted a session log upstream, and because one engine costs ~3 GB where twelve would cost ~17 GB. See
[`docs/multi-window/ANALYSIS-AND-DECISION.md`](docs/multi-window/ANALYSIS-AND-DECISION.md) and
[`docs/multi-window/PERFORMANCE-MEASURED.md`](docs/multi-window/PERFORMANCE-MEASURED.md).

### Profile patches (`profiles/`)

A profile's own `cordis.patch.yml` is the layer that belongs to us — applied after every bundle layer, so
it survives an upgrade and a rebuild. `sync.py` copies `profiles/<name>/cordis.patch.yml` into
`~/.dsh/profiles/<name>/`. It never touches `profiles/node_modules/`, and a profile it has no overlay for
is left alone. The shipped packages under `node_modules` are **never** edited by hand: an upgrade wipes
them.

### Plugin packages

A package under `packages/` is installed into a DSH profile by `file:` path, so it is
version-controlled here and mounted from a checkout rather than hand-edited into
`node_modules`. `plugin-cost` is the first one; see
[`packages/plugin-cost/README.md`](packages/plugin-cost/README.md) for what it does, how to
install it, and how to verify it. `sync.py` does not install packages — installing is a
profile operation, not a `~/.dsh` copy.

Merge rule: **base, then machine delta.** A key in the machine file wins.

## Applying it

```sh
# see what would change, touch nothing
python scripts/sync.py --dry-run

# apply: copy presets, merge settings
python scripts/sync.py
```

`sync.py` never deletes `sessions/`, never writes `.credentials.yaml`, and refuses to touch the
**shipped** preset install beside the deployment (per the composition-editing rules — an upgrade
overwrites it and corrupting `cordis` disables preset authoring).

## The current state of the fleet

- `cordis-bg` is **the intended default**. Its `preset.yml` describes it as the creation-mode preset
  plus a shell execution policy that starts long commands as background jobs instead of letting them
  hit the 120-second foreground timeout.
- The desktop authored it but left `settings.yaml` pointing at `cordis`, so **the improvement was
  never in use.**
- Machine deltas capture the real differences rather than flattening them — the Yoga genuinely has a
  different provider block.

## Rule

**Change the harness here first, then sync.** A preset edited directly in `~/.dsh` is a change that
will be lost on the next sync and is invisible to every other machine.
