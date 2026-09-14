# dsh-plugin-attention-badge

The attention badge, on every machine — not only the one whose document the phone gate rewrites.

```
        ┌──────────────────────────────┐
        │ ●  6 needing attention · stale 9h ago │
        └──────────────────────────────┘
        ┌─────────────────────────────────────┐   (tap the pill)
        │ Company findings (stale)            │
        │ kernel report written 9h ago on     │
        │ secratary (13 checks: 7 ok, 6 …)    │
        │ CRITICAL delivery: nothing is …     │
        │ HIGH     evolution: 71 proposals …  │
        └─────────────────────────────────────┘
```

## Why this package exists

The badge was first delivered by `scripts/phone-gate.py`, which rewrites the document on its way to
the phone. That works, and **only there**: every other machine runs its own DSH engine on loopback,
nothing rewrites its document, and nothing injected the badge. Measured on `ZABZ-YOGA`:
engine on `127.0.0.1:3099`, profile holding `dsh-base`, `dsh-web-app`, `plugin-cost`,
`plugin-windows`, `plugin-mobile` — and no badge. The owner asked the obvious question (*"why just my
iphone and not the desktop and yoga"*), and the honest answer was that the delivery path had been
chosen for one surface and never generalised.

This package is that generalisation, and it is deliberately tiny: **one script tag.**

## What it does

```
lib/client.js                        lib/index.js
─────────────                        ────────────
injects, once:                       a valid Cordis host half that contributes
  <script id="dsh-attention-badge-     nothing, on purpose. No service, no command,
   loader"                             no host RPC — so there is no second data
   src="https://secratary.tail93e6e6.ts.net/dsh-attention.js"
   data-attention-json="https://secratary.tail93e6e6.ts.net"
   async>
```

The badge then fetches `/dsh-attention.json` **from the authority it was loaded from**, not from the
local engine. That is what `data-attention-json` is for: the plugin's page is
`http://127.0.0.1:3099` while the data is on the authority, so a relative fetch would ask the local
engine for a route it does not have.

## Why it does not bundle a copy of the badge

A second copy would drift from `assets/phone-badge.js` the first time either side changed, and the
drift would be invisible: the phone and the desktop would disagree about what the company is
reporting, with no error anywhere. Loading the one file means one implementation and one truth.

The cost is that a machine with no route to the authority shows nothing — which is the honest
outcome, because it genuinely cannot know the findings, and `phone-badge.js` renders that as
*"findings unavailable"* rather than as a green zero.

## Install

```powershell
# from a harness-config checkout
pwsh scripts/install-client-plugins.ps1 -RequireAll     # links every package in packages/ and adds it
pwsh scripts/install-client-plugins.ps1 -Check          # report only; exit 1 if a bundle is broken
```

```bash
bash scripts/install-client-plugin.sh packages/plugin-attention-badge   # one package, Linux/macOS
```

Then reload the profile. `dsh.profile.patchReload: "live"` in the profile is usually enough for a
page reload; a client bundle that mounts a **new** package has been observed to need an engine
restart. `dsh --profile web --dump-config` proves the composition resolves without restarting
anything — do that first, because a broken bundle row is a boot failure.

## Configuration

| What | Where | Default |
|---|---|---|
| the authority that serves the badge | `BADGE_AUTHORITY` in `lib/client.js` | `https://secratary.tail93e6e6.ts.net` |
| the badge source file | `assets/phone-badge.js` in this repo | — |
| the findings route | `/dsh-attention.json` on the authority | — |

**If the authority moves or is renamed**, `BADGE_AUTHORITY` is the one line to change, and then every
machine must be reinstalled (or its page reloaded) — client bundles are served immutable, so a
mounted machine caches its copy for a year. Until then it shows "findings unavailable", which is
correct but silent: the reason only appears in the expanded card.

## How it fails

| Failure | What you see | Why it is that way |
|---|---|---|
| no route to the authority | `findings unavailable`, dashed border, reason in the card | it genuinely cannot know the findings |
| the authority's gate down | same | same |
| the kernel stopped writing | a reading with `· stale <age>` and a `(stale)` card | a reading of unknown or old age must not look current |
| the kernel's file is malformed | `findings unavailable` with the reason the gate gave | a refusal, not a confident zero |
| the plugin is not installed | nothing at all | absence of the badge is not absence of findings |

## Verifying it

```bash
node scripts/verify-badge.js            # 130 checks, no browser, either OS
python scripts/verify-badge-gate.py     # 55 checks of the gate's half
```

`verify-badge.js` boots the real badge in a `node:vm` sandbox with a DOM stub and drives every
render and failure path, then runs a **round trip**: it takes the bytes the gate really produces and
renders them with the badge that really renders them. That test exists because the two halves share
a field contract and are written in different languages, and nothing coupled them — a rename on one
side would otherwise have reached the owner's phone before anyone noticed.

What the checks **cannot** prove is that a human can see the badge in their browser. That is the one
link that needs eyes, and `docs/badge/README.md` says how to close it.

## What breaks on a harness upgrade

- **`window.__ModuleLoader__.load({id, factory})`** — the client loader's contract. A bundle is a
  plain script that populates `module.exports`; an ES module here is loaded and silently contributes
  nothing. `plugin-mobile` and `plugin-cost` in this same checkout are the working references.
- **`dsh.client.platform: "web"`** and **`exports["./client"]`** — the loader only mounts a client
  half that declares both.
- **`cordis.patch.yml` needs the `insert:` wrapper.** Without it the loader reports
  `entry "dsh-plugin-attention-badge" not found` and **skips the bundle silently** — measured, and
  the reason that wrapper is not cosmetic.
