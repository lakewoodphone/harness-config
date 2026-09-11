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

**Never commit secrets.** Credentials stay in `.credentials.yaml` and are referenced by env var name
(`apiKeyEnv: DEEPINFRA_API_KEY`), never by value.

## Layout

```
harness-config/
├── presets/                  # canonical agent presets, one dir each
│   └── cordis-bg/            # background-first shell policy
├── settings/
│   ├── base.yaml             # settings identical on every machine
│   └── machines/
│       ├── ZABZ-YOGA.yaml    # per-machine deltas
│       └── ZABZ-TECH.yaml
├── scripts/
│   └── sync.py               # apply this repo onto the local ~/.dsh
└── docs/
    └── DECISIONS.md
```

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
