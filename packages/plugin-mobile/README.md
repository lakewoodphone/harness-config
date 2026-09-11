# dsh-plugin-mobile

Phone behaviour for DSH. One thing, because it is the one thing a stylesheet cannot do:

| Surface | What it does | Where it lives |
|---|---|---|
| The sidebar, on a narrow viewport | Picking a conversation closes it; a tap outside closes it; Escape closes it | Browser half: `lib/client.js` |

## Why this exists

The harness composes its desktop layout at phone width. `assets/mobile.css`, injected by
`scripts/phone-gate.py`, fixes what CSS can reach: touch targets under 44 px, the 13.33 px
composer field that makes iOS auto-zoom the page on focus, missing safe-area insets, and an
open sidebar that squeezed the content column from 337 px to 113 px instead of overlaying.

What CSS cannot reach is state. Measured on 2026-09-11 at 393x852 on the live app: tap a
conversation in the drawer, the conversation loads **behind** the drawer, and the drawer
stays open covering the screen the reader just asked for. That is a selection, so it belongs
in the client half of a plugin.

## What it reads, instead of reaching into the app

No private API, no storage keys, no React internals. The UI already publishes everything
needed:

- the sidebar toggle is a `button` whose accessible name is **"Open sidebar"** when the
  drawer is closed and **"Collapse sidebar"** when it is open — so the drawer's state is
  readable from the DOM;
- conversations live inside the sidebar's list region.

It reacts to clicks in the capture phase and never calls `preventDefault`: the click still
reaches the app, and the drawer closes ~150 ms later, once the app has applied the
selection. It closes on an outside tap too, because that is the gesture an overlay owes a
phone user, and on Escape.

**Excluded on purpose:** text fields (searching is not navigating), disclosures carrying
`aria-expanded` (expanding a workspace group), and the toggle itself.

**Width is checked per click**, not at install: the same browser is a phone and a desktop at
different moments. Above 768 px — the same breakpoint the stylesheet uses — nothing happens
at all.

## Install

```bash
# from the harness-config checkout
bash packages/plugin-mobile/install.sh            # symlink + bundle list, idempotent
bash packages/plugin-mobile/install.sh /path/to/profile   # a different profile
```

The harness needs the package to resolve by name from the profile and its name to be in
`dsh.profile.bundles`. The script does both and re-running it is a no-op. The profile then
reloads (`"patchReload": "live"` makes that a page reload; otherwise restart the engine).

## Verifying it, not assuming it

```bash
node --check lib/client.js        # the browser half parses as the loader will read it
curl -s http://127.0.0.1:3089/ -H 'Host: <authority>' | grep -o 'dsh-plugin-mobile/client.js' | head -1
```

The first proves the script is loadable. The second proves the client roster actually
carries it — the roster is assembled from package manifests, so a symlink alone is not
evidence that the browser will ever see this file.

What neither can prove is the behaviour: only a browser does. Open the harness at 393 px,
open the sidebar, tap a conversation, and confirm the drawer is gone and the conversation is
visible.

## What breaks on a harness upgrade

- **The toggle's accessible name.** `lib/client.js` decides the drawer is open by matching
  `/collapse/i` on that button's `aria-label`. If a release renames it, the plugin simply
  stops acting — it will not misfire — and the stylesheet half is unaffected.
- **`[class*="sidebarCol"]` / `[class*="listArea"]`.** CSS-module local-name substrings,
  matched the same way the stylesheet matches them, so a rebuild that keeps local names
  keeps this working.
- The plugin is inert on the host side, so a host upgrade cannot break it the way a row that
  registers a service could.
