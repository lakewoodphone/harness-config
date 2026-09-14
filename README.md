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
dshw up           # start the engine if it is not listening. NO windows.
dshw new          # open ONE more window (a new conversation)
dshw status       # per-window truth: port, pid, window count, memory
dshw health       # idempotent: start ONLY what should be listening and is not
dshw watchdog on  # schedule `dshw health` every 5 minutes
dshw autostart on # schedule "engine at logon", so the app is always reachable
dshw doctor       # resolve every prerequisite and name what is missing
```

**Starting the engine and opening windows are separate intentions.** `dshw up` starts the engine and stops
there; opening eight windows at logon is not what anyone wants. The owner opens windows one at a time:

- the **`+` control beside the composer** in any DSH window (see `packages/plugin-windows`), or
- `dshw new` from a shell, or
- the **DSH Windows** desktop shortcut, which is the same as `dshw up -WindowsMode yes`.

The `+` control needs a Windows URL-protocol registration, once per machine:

```powershell
$pwsh = (Get-Command pwsh).Source
$dshw = "$env:USERPROFILE\code\harness-config\multi-window\dshw.ps1"
New-Item 'HKCU:\Software\Classes\dsh-new\shell\open\command' -Force | Out-Null
Set-ItemProperty 'HKCU:\Software\Classes\dsh-new\shell\open\command' -Name '(default)' `
  -Value "`"$pwsh`" -NoProfile -WindowStyle Hidden -File `"$dshw`" new"
Set-ItemProperty 'HKCU:\Software\Classes\dsh-new' -Name 'URL Protocol' -Value ''
```

Clicking `+` navigates the page to `dsh-new://open`, which Windows hands to that command. Expect the browser
to ask once whether to open the app. The button is inert if the protocol is not registered — that is the
only failure mode, and it cannot break the UI.

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

### Deploying the fleet to another machine

In this order. Run `dshw doctor` and read what it says.

```sh
git pull                                  # in the harness-config checkout on that machine
python scripts/sync.py                    # presets, settings, and the profile patch layer
pwsh scripts/install-client-plugins.ps1   # the local plugin packages; sync.py does not install these
dshw doctor                               # names anything missing (node, dsh bin, browser, DSH_HOME)
dshw up                                   # start the engine if it is not listening, open the windows
dshw autostart on                         # bring the windows back at logon
dshw watchdog on                          # restart a dead engine every 5 minutes
```

The third step is the one that was missing, and its absence is silent: `sync.py` restores
presets and settings but installs no packages, so the engine starts and then refuses to
resolve a bundle its own `package.json` still lists.

The two scheduled tasks can be carried across rather than re-created, which guarantees the second machine
gets exactly the first one's configuration:

```sh
dshw tasks-export                      # writes both task XMLs to ~/.dsh/multi-window/tasks/
# copy them over, then on the other machine:
dshw tasks-import -Slot <that-dir>
```

Two traps, both hit on 2026-09-11: Windows exports `UserId` as a **locally-mapped SID**, so importing
another machine's XML unchanged fails with *"no mapping between account names and security IDs"* —
`tasks-import` rewrites it to the bare account name; and the task arguments are **absolute paths**, so both
machines must keep the repo at the same path.

**One engine per `DSH_HOME`.** The fleet guards this on its own port: `dshw up` treats a live engine it does
not own as an explicit take-over (`-Force`) rather than starting a second one. It cannot *stop* a
hand-started `dsh web` on a different port, but it can now see one: `dshw status` and `dshw doctor` read
each listener's command line and name any `dsh web` that is not the fleet's own, with `doctor` raising it
as a blocker rather than a note. Seen live on 2026-09-11: `another dsh web on port 3080 (pid 44040) shares
this DSH_HOME`. If you start one by hand, stop the fleet's engine first (`dshw stop`), or accept two
writers.

### Plugin packages

There are three, all mountable client plugins: `plugin-cost` (the `/cost` command and the
composer cost pill), `plugin-mobile` (the phone drawer; `scripts/serve-phone.sh` keeps it
installed), and `plugin-windows` (the `+` and `⧉` controls beside the composer).

`sync.py` does **not** install packages, and the profile's own `package.json` — the bundle
list the loader mounts — is machine-local and not in git. A package is therefore invisible
to a machine rebuilt from this repo unless something installs it. That is not hypothetical:
on 2026-09-11 the fleet engine refused to boot with

```
Error: dsh: cannot resolve profile bundle "dsh-plugin-cost" from the dsh
installation or C:\Users\ezabz\.dsh\profiles\web
```

and `plugin-windows` had to be copied into the profile by hand twice from another session.

The keeper is `scripts/install-client-plugins.ps1`, on the same reasoning as D38 — a
component that can silently disappear needs a keeper, not a procedure:

```powershell
pwsh scripts/install-client-plugins.ps1 -Check   # report only; exit 1 if anything is wrong
pwsh scripts/install-client-plugins.ps1          # install/repair, idempotent
```

It installs each package as a **directory junction** to this checkout rather than a copy, so
an edit here is live without a reinstall and the two cannot drift. A junction rather than a
symlink, because Windows grants symlink creation only to an elevated shell or Developer
Mode. A bundle-list change needs the profile reloaded — usually a page reload, otherwise an
engine restart.

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
