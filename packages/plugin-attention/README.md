# dsh-plugin-attention

`/attention` — what the company is reporting, in the composer you are already typing in.

```
Company findings — kernel report written 7m ago on secratary (12 checks: 7 ok, 5 needing attention)

  HIGH   comms_freshness: held messages older than 2h

  quiet: config_sync

Sensing:
  phone path    12/12 checks, 5m ago
  config sync   attention 15m ago: pull --ff-only refused: histories diverged (5 behind)
  phone ui      pass 6h ago

Read-only. Each reading carries the source and age above; a missing one is said out loud.
```

`phone ui` is the phone layer's own UI checks (`scripts/check-phone-ui.sh`): the composer row must
stay on one line, and an agent's question card must fit the viewport with its Submit button tappable.
Added 2026-09-14 after two layout defects reached the owner's phone with nothing automatic noticing
them — the composer doubled into two rows of controls whenever a session had usage, and a question
could not be answered from the phone at all. When it fails the line names what broke:

```
  phone ui      FAIL 4h ago  <- the phone's own controls are broken: ...
```

## Why this exists

Two sensing paths were working and reached nobody. On 2026-09-14 the autosync recorded a refused pull **every fifteen
minutes for seventy-five minutes** (`{"result":"attention","detail":"pull --ff-only refused: histories diverged (5 behind)"}`)
and the kernel's `config_sync` check already escalates any non-`clean` result to HIGH; the phone probe has written a verdict
the kernel reads since the same morning. Nothing was missing from the sensing — nothing delivered it. The owner learned
about the blocked deploy because a person happened to try one.

This is the smallest honest consumer: a command beside `/cost` in the slash menu, showing the same findings with the source
and the age of each reading.

## What it reads

| Source | File | Stale after |
|---|---|---|
| kernel findings | `$CEO_KERNEL_STATE/latest.json` (default `~/ceo-kernel-var`) | 20 min |
| phone path | `~/.dsh-phone/probe.json` | 20 min |
| config sync | `~/.harness-config-autosync/status.json` | 45 min |

Read-only. A source that is missing or older than its threshold is reported as **stale or unreadable**, never as health —
the same rule the kernel follows.

## Install

```bash
bash packages/plugin-attention/install.sh                 # symlink + bundle list, idempotent
bash packages/plugin-attention/install.sh /path/to/profile
```

Then reload or restart the profile so the bundle mounts.

## Verifying it, not assuming it

```bash
node --check lib/index.js                              # parses as the loader will read it
node <a script that calls attentionReport()>            # the report renders, including the refusal case
```

What only a session can prove: that the command is registered and produces text. Type `/attention` and read it. The
command list the client receives is the intermediate evidence; the text is the point.

## Why there is no badge

A badge would need the client half to ask the host half for data, and in this deployment that channel
(`harness.handle` + `host.call`) belongs to the dynamic Cordis runner, which is deliberately disabled in this preset.
Ordinary static plugins get `ctx.get('<service>')` and host `commands`, so a command is the shape that needs no new
service, no new channel and no permission. A badge is worth doing later by whichever route is chosen deliberately — see
`journal/DECISIONS.md` D41.

## What breaks on a harness upgrade

- **The `commands` service and `commands.register({name, description, handler})`.** If that signature changes, this
  plugin fails loudly at mount (a row that never activated), not silently.
- **The source paths.** They are this fleet's own files; if the kernel's state directory moves, set `CEO_KERNEL_STATE`.
  A moved file shows as "NOT READABLE", which is a finding rather than a blank.
