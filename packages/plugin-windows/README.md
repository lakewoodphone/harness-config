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
