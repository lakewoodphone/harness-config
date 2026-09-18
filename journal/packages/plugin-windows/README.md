# plugin-windows

The `+` control beside the composer: click it and a **new DSH window** opens on this
machine, on a new conversation.

![what it is] one button, one job: `+` → `dshw new` → a new window.

## Why it works this way

A web page cannot start a process, and it should not be able to. So the button does the
one thing a page may do: it navigates.

```
click +  →  dsh-new://open  →  Windows runs:  pwsh dshw.ps1 new
```

The URL protocol handler is registered once per machine (see the repo README). Windows
hands the URL to the launcher, the launcher opens a window with its own browser profile
against the running engine, and that window is a fresh conversation — because a DSH window
is a client of the shared engine and a new conversation is a new session in it.

Two consequences worth knowing:

- **The engine never executes anything on behalf of a page.** The host half of this
  package is deliberately empty. Opening a window is the launcher's job, so there is only
  one implementation of "open another window" (`+`, `dshw new`, and the desktop shortcut
  all end up in the same place).
- **The only failure mode is a missing protocol registration**, in which case the button
  does nothing. It cannot break the UI.

## On a phone, neither control exists

Below **768 px** the composer shows no `+` and no `⧉`, and that is deliberate:

- `⧉` hands `dsh-new://open` to Windows. A phone has nowhere to put a second window and no
  handler for the protocol, so the control would look live and do nothing — the owner asked
  for its absence in as many words on 2026-09-14: *"it doesn't need the plus button to open a
  new window because it's just a phone, so it doesn't need more than one window"*.
- `+` blanks this window into a new conversation, which the phone UI already offers from its
  own sidebar. A second copy beside the composer costs a tap target in the scarcest space on
  the screen.

The guard is on the **viewport**, not on the host: the same profile may serve a desktop and a
phone at once, so the decision belongs to the width the page is rendered at — the same rule
`plugin-mobile` and `assets/mobile.css` follow, at the same breakpoint. It is read per render
and re-read on resize, so rotating a phone or widening a window does the right thing without a
reload. `test/client-smoke.mjs` asserts the rendered result at 393 px, at exactly 768 px, one
pixel above it, and at desktop width.

## Dependencies: none, on purpose

The browser loader resolves **every** name in a plugin's `inject` and in the package's
`dsh.client.inject` as a *service*, and it refuses to activate the entry until each one
exists. A wrong name there does not degrade a plugin — it stops the whole web UI booting
with "Failed to load plugins". That is not hypothetical: it happened to
[`../plugin-cost`](../plugin-cost/) on 2026-09-11.

So this package declares nothing and reads the Slot registry defensively with
`ctx.get('slots')`. If you add a dependency here, use a **service** name the shipped client
plugins use (`slots`, `locale`, `connection`, `remote`), and only when the plugin genuinely
cannot work without it.

## Layout

| File | Role |
|---|---|
| `package.json` | the bundle manifest, plus the `dsh.client` declaration |
| `cordis.patch.yml` | the loader row that makes it a real bundle |
| `lib/index.js` | host half — inert, and says why |
| `lib/client.js` | the button, and the click handler |

## Verify

```powershell
# 1. the launcher can open a window at all
pwsh dshw.ps1 new

# 2. the protocol resolves to that same command
(Get-ItemProperty 'HKCU:\Software\Classes\dsh-new\shell\open\command').'(default)'

# 3. the plugin is in the payload the engine serves
pwsh dshw.ps1 status     # window count goes up by one per `new`
```

Then click `+` in any DSH window. The browser may ask once whether to open the app; after
that it is one click.
