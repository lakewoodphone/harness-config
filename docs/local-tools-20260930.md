# Local tools — persistent Playwright profile (TS-5)

Date: 2026-09-30 · Host: ZABZ-YOGA · Author: seat (this machine, this repo)
Scope: the `mcp-playwright` row only. Nothing else in the preset or profile changed.

Goal: a browser login must survive the MCP server, the browser, and the engine
restart. Today the row starts Playwright with `--headless --no-sandbox` and no
explicit profile path, so where the cookies live is decided by the package, not
by us, and is not documented.

---

## 1. Where the playwright MCP server is configured on this machine

Found by `grep playwright` over the repo and `C:\Users\ezabz\.dsh`, plus reading
the installed package. Four places matter; only the first three are reproducible
from the repo:

| # | Path | Role |
|---|------|------|
| 1 | `presets/zabz/agent.cordis.yml` (row `mcp-playwright`, ~L679) | preset source, **generated** by `scripts/make_zabz_preset.py` |
| 2 | `profiles/web/cordis.patch.yml` (`preset-rows` managed block, ~L1597) | **live-effective**: `scripts/sync.py` copies it to `~/.dsh/profiles/web/cordis.patch.yml` and the engine composes that layer after the shipped bundles |
| 3 | `scripts/provision-mcp-tools.ps1` (`$packages @('…','@playwright/mcp')`) | installer of the package, not the launch row |
| 4 | `C:\Users\ezabz\.dsh\tools\mcp\node_modules\@playwright\mcp\cli.js` | the mounted binary the row points at (read-only; **not edited**) |

`C:\Users\ezabz\.dsh\settings.yaml` contains **no** `playwright` string (39 lines
in full) — the row is not defined there. `~/.dsh/profiles/web/cordis.patch.yml`
carries the same row at the same shape (verified read-only, L1597).

Installed package provenance: `@playwright/mcp` **0.0.81**,
`playwright`/`playwright-core` **1.64.0-alpha-2026-09-14**
(`.dsh/tools/mcp/node_modules/@playwright/mcp/package.json`).

---

## 2. The change (exact diff)

```diff
diff --git a/presets/zabz/agent.cordis.yml b/presets/zabz/agent.cordis.yml
@@ -687,6 +687,8 @@
       - '--headless'
       - '--no-sandbox'
+      - '--user-data-dir'
+      - 'C:\\Users\\ezabz\\AppData\\Local\\ms-playwright-mcp\\mcp-chrome-32dbea4'
       - '--output-dir'
       - 'C:\\Users\\ezabz\\code\\personal-secretary-mvp\\data\\browser\\mcp-output'
     cwd: 'C:\\Users\\ezabz\\code\\personal-secretary-mvp'

diff --git a/profiles/web/cordis.patch.yml b/profiles/web/cordis.patch.yml
@@ -1607,6 +1607,8 @@
                                 --headless,
                                 --no-sandbox,
+                                --user-data-dir,
+                                C:\\Users\\ezabz\\AppData\\Local\\ms-playwright-mcp\\mcp-chrome-32dbea4,
                                 --output-dir,
                                 C:\\Users\\ezabz\\code\\personal-secretary-mvp\\data\\browser\\mcp-output
```

Evidence the old row had no profile flag — at `HEAD`, before this change:

```
$ git show HEAD:presets/zabz/agent.cordis.yml | Select-String 'id: mcp-playwright' -Context 0,13
    args:
      - 'C:\\Users\\ezabz\\.dsh\\tools\\mcp\\node_modules\\@playwright\\mcp\\cli.js'
      - '--headless'
      - '--no-sandbox'
      - '--output-dir'
      - 'C:\\Users\\ezabz\\code\\personal-secretary-mvp\\data\\browser\\mcp-output'

$ git grep -n "user-data-dir" HEAD -- presets profiles
(no output, exit 1)
```

`--headless` and `--no-sandbox` are unchanged. `--user-data-dir` is documented
at `.dsh/tools/mcp/node_modules/@playwright/mcp/README.md:455` and is consumed at
`playwright-core/lib/coreBundle.js:73982`
(`const userDataDir = config.browser.userDataDir ?? await createUserDataDir(...)`),
then passed to `launchPersistentContext` at `:74000`. It must be an **absolute**
path (`:39951` asserts that).

### Why this exact path

`C:\Users\ezabz\AppData\Local\ms-playwright-mcp\mcp-chrome-32dbea4`

This is not an arbitrary new directory: it is **the directory the seat is already
using**. With no flag, this build derives the profile as
`%LOCALAPPDATA%\ms-playwright-mcp\mcp-{channel}-{sha256(client-cwd)[0:7]}`
(`coreBundle.js:74014-74024`), and
`sha256("C:\Users\ezabz\code\personal-secretary-mvp")[0:7] == 32dbea4`. Pinning it:

* keeps whatever cookie jar already exists there — **no login migration**;
* removes the dependency on the client `cwd` hash, so a `cwd` change can no
  longer silently start a fresh, logged-out profile;
* removes the dependency on package internals, so a future `@playwright/mcp`
  that reverts to a temporary directory cannot log the seat out;
* makes the location documented, so its permissions, backup and deletion are
  deliberate instead of implicit.

### Permissions

Measured with `icacls` on 2026-09-30 — already correct, no widening needed:

```
C:\Users\ezabz\AppData\Local\ms-playwright-mcp\mcp-chrome-32dbea4
    NT AUTHORITY\SYSTEM:(I)(OI)(CI)(F)
    BUILTIN\Administrators:(I)(OI)(CI)(F)
    zabz-yoga\ezabz:(I)(OI)(CI)(F)
```

No `BUILTIN\Users`, no `Everyone`, no inherited-from-`C:\` broad grant: only the
owning user, SYSTEM and Administrators can read the cookie store. If a future
step ever widens it, restore it with:

```powershell
icacls 'C:\Users\ezabz\AppData\Local\ms-playwright-mcp\mcp-chrome-32dbea4' `
  /inheritance:r `
  /grant:r "$env:USERNAME:(OI)(CI)F" `
  /grant:r "NT AUTHORITY\SYSTEM:(OI)(CI)F" `
  /grant:r "BUILTIN\Administrators:(OI)(CI)F"
```

Keep the profile **outside every git repo** (it is, under `%LOCALAPPDATA%`) and
outside `~/.dsh` (it is) — see §5.

### Single-instance caveat

A persistent profile can be opened by **one browser process at a time**
(`@playwright/mcp` README:482-483). Two seats sharing this path will make the
second one fail with `Browser is already in use for <dir>` (`coreBundle.js:74010`).
That is not new — sibling agents already shared the hash-derived default — but it
is now explicit. If a second seat must browse at the same time, give it
`--isolated` or a distinct `--user-data-dir`; do **not** kill the running browser,
because that is what flushes and persists the session.

---

## 3. One-time human login that persists

The seat starts Playwright **headless**, so a human cannot type into its window.
Log in **once** with a headed browser pointed at the same profile, then let the
headless seat reuse the cookies.

**Step 0 — stop the seat's browser first.** The profile is single-instance; the
headed login will fail while the seat's Chromium holds it. Close the seat's
browser (or let the MCP `--idle-timeout` default of one hour close it).

**Step 1 — run this headed login** (save as `playwright-login.mjs` anywhere, then
`node playwright-login.mjs https://the.portal.example/`). It uses the SAME
installed `playwright` package the MCP uses, so the browser build and the profile
format match:

```js
// node playwright-login.mjs <portal-url>
const { chromium } = require('C:\\Users\\ezabz\\.dsh\\tools\\mcp\\node_modules\\playwright');
const USER_DATA_DIR =
  'C:\\Users\\ezabz\\AppData\\Local\\ms-playwright-mcp\\mcp-chrome-32dbea4';

(async () => {
  const ctx = await chromium.launchPersistentContext(USER_DATA_DIR, {
    headless: false,        // the whole point: a human must see and type
    channel: 'chrome',      // matches the profile's `mcp-chrome` channel
    viewport: null,
  });
  const page = ctx.pages()[0] ?? (await ctx.newPage());
  await page.goto(process.argv[2] ?? 'about:blank');
  console.log('Log in fully (including any 2FA), then press Enter here to save and close.');
  await new Promise((r) => process.stdin.once('data', r));
  await ctx.close();        // clean close flushes cookies to disk
})().catch((e) => { console.error(e); process.exit(1); });
```

If Chrome is not installed, drop `channel: 'chrome'` and Playwright's bundled
Chromium (present: `%LOCALAPPDATA%\ms-playwright\chromium-1243`) is used; the
profile stays valid because cookies are encrypted per Windows user, not per
binary.

**Step 2 — confirm it stuck.** The profile must contain a non-empty cookie store,
and its mtime must move when you log in:

```powershell
Get-Item 'C:\Users\ezabz\AppData\Local\ms-playwright-mcp\mcp-chrome-32dbea4\Default\Network\Cookies' |
  Select-Object Length, LastWriteTime
```

**Step 3 — the seat is logged in.** The next `mcp-playwright` start loads the
profile. Verify from the seat with `browser_navigate` to a page that is only
reachable when authenticated (for example the portal's account page) and
`browser_snapshot`; if it shows the logged-in shell rather than a login form, the
session survived.

**Log out deliberately** = stop the seat's browser, then delete the whole profile
directory. That is the equivalent of "clear cookies".

---

## 4. Screenshots, handed to the seat so it can read the image

The row keeps `--output-dir C:\Users\ezabz\code\personal-secretary-mvp\data\browser\mcp-output`
and the MCP workspace root is the row's `cwd`
(`C:\Users\ezabz\code\personal-secretary-mvp`).

1. The seat calls **`browser_take_screenshot`** (`@playwright/mcp` README:1088).
   With no filename the PNG is auto-named into `--output-dir`; with an explicit
   name the path is resolved **against the workspace root**, not `--output-dir`
   (README:437). So `data/browser/mcp-output/portal.png` lands at
   `C:\Users\ezabz\code\personal-secretary-mvp\data\browser\mcp-output\portal.png`.
2. The tool response carries an **image content block** (`--image-responses allow`
   is the default; README:435). The seat then reads the saved file by absolute
   path with the harness **`read_image`** tool, which ingests the PNG itself
   instead of trusting a filename in text.
3. If the seat's model is **text-only**, `read_image` refuses (it requires an
   image-capable model). Two ways out: route the PNG through the gateway's vision
   route and read the returned text, or — preferred for action-taking — use
   **`browser_snapshot`** (README:1076), the accessibility tree, which is text by
   construction. The MCP itself says it plainly (README:1090): *"You can't perform
   actions based on the screenshot, use browser_snapshot for actions."*
4. Screenshots taken while logged in contain account content. Do not leave them
   lying in a repo working tree (see §5).

---

## 5. Security note — the profile is a live credential

* `mcp-chrome-32dbea4` holds **live session cookies**, `localStorage`,
  IndexedDB, service-worker caches and saved logins for every portal the seat has
  visited. Anyone who can read that directory can act as the logged-in user
  without a password. Treat it as a password, not as cache.
* **Never commit it.** It lives under `%LOCALAPPDATA%`, outside every git repo —
  keep it that way. If it is ever placed inside a repo, add it to `.gitignore`
  *and* remove it from the index; a committed cookie jar is a credential leak
  that survives deletion in history.
* **Never copy it off the machine** — no cloud backup, no OneDrive/Dropbox, no
  `scp` to another node, no attaching it to a report or chat. The cookies are
  additionally DPAPI-encrypted per Windows user, so a copied profile is usually
  unusable, but that is a second line of defence, not permission to move it.
* **Screenshots are the same class of data** and the `--output-dir`
  (`personal-secretary-mvp\data\browser\mcp-output`) *is* inside a repo. Never
  `git add` them; clear them when the review is done.
* Filesystem ACL is already least-privilege (§2): user + SYSTEM +
  Administrators only. Do not widen it. A `.zip` of this directory is as
  sensitive as the directory.
* The only intended reader is the seat's own browser process, launched by the
  `mcp-playwright` row. Nothing else on the machine should be pointed at this
  path.

---

## 6. What this document does not claim / open follow-ups

* **`scripts/make_zabz_preset.py` was not updated** (not in this task's owned
  file set). It still emits the row **without** `--user-data-dir`, so running it
  would silently revert the preset change. Its `--check` already reports drift at
  `HEAD` for unrelated reasons (`exit 1`, 2026-09-30), so this is not a new
  regression, but the generator's `mcp-playwright` row must be updated by its
  owner to make the change regeneration-proof.
* The `preset-rows` managed block in `profiles/web/cordis.patch.yml` is now
  **hand-maintained**: `scripts/make-preset-rows.mjs` no longer exists in the
  repo, and the block's recorded `sha256` (L295) was already stale against the
  current preset before this edit. That block is the layer the live engine reads,
  so it was edited directly.
* **No browser was launched and no live site was contacted** while producing this
  change. The profile directory already existed and was only inspected
  (read-only). Runtime proof that the seat reuses the login is the Step 3 check
  above, to be run at the next engine restart.
