# DSH desktop-app route on Windows — state and feasibility

**Machine:** `ZABZ-YOGA` (hostname verified: `zabz-yoga`), Windows 11, PowerShell `7.6.6`.
**Researched:** 2026-09-11, 13:02–13:20 local (`-04:00`). Everything below was read on that date.

**Bottom line.** The desktop app is **real and official** — it is `apps/desktop` inside the monorepo,
package name `@deepseek-ai/dsh-desktop`, version `0.1.5-rc.2` — but it is **not installable** by any route I could
find: it is `"private": true`, unpublished on npm, and **every one of the 5 most recent official releases carries
zero downloadable assets**, while the update/CDN origin it would publish to returns 404. And even if it were
installable it **would not answer this repo's question**: it takes a **process-lifetime single-instance lock**, so
`ZABZ-YOGA` could run **exactly one** DSH desktop window, not 8–12. That is by design, not an accident.

---

## 1. Does a DSH desktop/Electron app exist as a real, installable artifact?

### 1a. It exists as official source — confirmed

| Fact | Source |
|---|---|
| Official in-repo app at `apps/desktop` | <https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md> (read 2026-09-11) |
| `"name": "@deepseek-ai/dsh-desktop"`, `"description": "Electron desktop shell for a bundled dsh runtime and external plugins"` | `https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/apps/desktop/package.json` (read 2026-09-11) |
| `"version": "0.1.5-rc.2"` | same file |
| `"private": true` — **cannot be published to npm** | same file |
| `"main": "lib/main.js"`, `"type": "module"`, dep on `electron-updater ^6.8.9`; devDep `electron ^44.0.0`, `electron-builder ^26.15.3` | same file |

The app is an Electron shell around the existing Web UI. Its own README describes the architecture
(<https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/apps/desktop/README.md>, read 2026-09-11):

> "The desktop application is an Electron shell around the dsh Web UI. It opens no listening port: a bundled
> upstream Node.js child boots the installed dsh project, versioned framed byte pipes carry Fetch requests and
> streaming responses without an outer Base64 envelope, Node IPC carries lifecycle control, and `dsh-app://`
> serves the matching client assets."

This closes the loop on `BRIEF.md` fact #9: the `desktop` profile name is reserved because this app **owns it**.
Confirmed in the installed launcher at `C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\dsh\lib\bin.js`
lines 28–30 (read 2026-09-11):

```js
function rejectElectronProfile(program, profile) {
	if (profile.toLowerCase() === "desktop") program.error("error: profile \"desktop\" is managed exclusively by the Electron application");
}
```

### 1b. It is **not installable** — this is the load-bearing finding

**GitHub releases carry no desktop installers.** Command run (2026-09-11):

```
Invoke-RestMethod "https://api.github.com/repos/deepseek-ai/deepseek-harness/releases?per_page=5"
```

Observed output — note `ASSETS=0` on every release, including the newest:

```
TAG=dsh-v0.1.5-rc.2        NAME=v0.1.5-rc.2        PUBLISHED=09/10/2026 15:09:34  PRERELEASE=True  ASSETS=0
TAG=dsh-v0.1.5-rc.1        NAME=v0.1.5-rc.1        PUBLISHED=09/10/2026 03:09:00  PRERELEASE=True  ASSETS=0
TAG=dsh-v0.1.5-alpha.2     NAME=v0.1.5-alpha.2     PUBLISHED=09/09/2026 14:23:10  PRERELEASE=True  ASSETS=0
TAG=dsh-v0.1.5-alpha.1     NAME=v0.1.5-alpha.1     PUBLISHED=09/08/2026 16:16:04  PRERELEASE=True  ASSETS=0
TAG=dsh-v0.1.3-alpha.2     NAME=v0.1.3-alpha.2     PUBLISHED=09/07/2026 13:59:29  PRERELEASE=True  ASSETS=0
```

- Latest **stable/product** release line is a prerelease channel: `dsh-v0.1.5-rc.2`, published **2026-09-10 15:09:34**.
  (`https://github.com/deepseek-ai/deepseek-harness/releases`, read 2026-09-11 — tag list also shows
  `v0.1.5-rc.1` "released this 10 Sep 03:09", `v0.1.2-rc.1` "03 Sep 06:06".)
- **No `.exe`, `.dmg` or `.AppImage` is attached to any official release.**

**It is not on npm either.** Command run (2026-09-11):

```
npm view @deepseek-ai/dsh-desktop
```

Observed output:

```
npm error code E404
npm error 404 Not Found - GET https://registry.npmjs.org/@deepseek-ai%2fdsh-desktop - Not found
npm error A complete log of this run can be found in: C:\Users\ezabz\AppData\Local\npm-cache\_logs\2026-09-11T17_04_24_744Z-debug-0.log
```

**Its distribution origin is empty.** The desktop README states the production update origin is
`https://download.deepseek.com` and the target path is `_/harness/desktop/stable/<target>/`
(target = `mac-arm64`, `mac-x64`, `win-x64`). I probed it (2026-09-11):

```
ERR 404 https://download.deepseek.com/_/harness/desktop/stable/win-x64/latest.yml
ERR 404 https://download.deepseek.com/_/harness/desktop/stable/win-x64/alpha.yml
ERR 404 https://download.deepseek.com/_/harness/desktop/stable/mac-arm64/latest-mac.yml
ERR 404 https://download.deepseek.com/_/harness/desktop/
ERR 404 https://download.deepseek.com/_/harness/
ERR 404 https://download.deepseek.com/_/harness/desktop/stable/
ERR 404 https://download.deepseek.com/_/harness/desktop/stable/win-x64/DeepSeek-Harness-Setup-0.1.5-rc.2.exe
OK  200 https://download.deepseek.com/    <- this serves the DeepSeek *mobile app* landing page, not desktop
```

The root page is `<title>DeepSeek App</title>` described as "支持 iOS 和 Android 平台 … Available for iOS and
Android" — i.e. the DeepSeek chat app, **not** a Harness desktop download page. **No desktop installer is
published at the documented production origin.**

**The official README never tells a user how to install the desktop app.** `https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/README.md`
(read 2026-09-11) documents only:

> "Run from `npm` — Install `Node.js`, then run: `npx @deepseek-ai/dsh web`"
> "Run from source — git clone … pnpm install; pnpm run build; pnpm dsh web"

There is **no desktop install section at all**. The desktop README's own install-adjacent commands are all
**build-from-source** (`pnpm run dev:desktop`, `pnpm run package:desktop:win:x64`), and Windows packaging
requires signing material that does not exist outside DeepSeek: `DSH_DESKTOP_WINDOWS_CER_FILE` (a GlobalSign EV
leaf certificate) plus a USB token. I verified the packaging-config placeholder is unset on this machine
(2026-09-11):

```
DSH_DESKTOP_APP_ID (user/machine/process):  |  |
```

**Conclusion for (1):** a real, official, source-available Electron DSH app exists at version `0.1.5-rc.2`
(2026-09-10). **It is not published as a downloadable artifact** — not on GitHub releases, not on npm, not at
its documented CDN origin — and the official docs give no end-user install path for it. It is a developer-preview
component one builds oneself, and an unsigned local build additionally needs the env vars just listed.

**Community wrappers exist but are not "the DSH desktop app."** Search returned a large set of third-party
Electron wrappers for the same Web UI, e.g. `agent-earth/deepseek-harness-desktop`,
`lencx/Minke`, `dataelement/dsh-desktop`, `cherrchen/deepseek-harness-electron`,
`xizhilanre/deepseek-harness-desktop`, `RZX00/deepseek-harness-desktop`, plus a Microsoft Store listing
"DeepSeek-Harness-Setup" (<https://apps.microsoft.com/detail/9n5x0d86vx5s>, dated Sep 2 2026). These are
unofficial — the official project's own release notes state plainly that the `oh-my-dsh` community organisation
"is not affiliated with DeepSeek AI, and their projects are not official DeepSeek products"
(<https://github.com/deepseek-ai/deepseek-harness/releases>, read 2026-09-11). **Do not treat any of them as the
official desktop app**, and none ship from DeepSeek.

---

## 2. Is an Electron-based DSH app already present on this machine? **No.**

Every check below returned an empty result. I list the exact command and observed output, because a negative
finding is only useful with its method attached.

**(a) `$DSH_HOME` contents** — `Get-ChildItem C:\Users\ezabz\.dsh -Force` (2026-09-11):

```
d---- 9/11/2026 12:30:14 PM .agent-presets
d---- 9/10/2026 6:47:08 PM  profiles
d---- 9/10/2026 6:50:33 PM  sessions
d---- 9/11/2026 12:56:39 PM storages
-a--- 9/10/2026 6:47:14 PM  .anonymous-user-id
-a--- 9/10/2026 11:05:04 PM .credentials.yaml
-a--- 9/11/2026 12:40:12 PM settings.yaml
(+ 4 settings.yaml.bak-* files)
```

`C:\Users\ezabz\.dsh\profiles` contains **only** `node_modules` and `web`. Per the official
`apps/desktop/src/paths.ts` (read 2026-09-11), the Electron app creates `$DSH_HOME/desktop/` (its pnpm store
root) and `$DSH_HOME/profiles/desktop/`. **Neither exists.** The existence of `profiles/web` and the absence of
`profiles/desktop` is direct evidence that only the npm/CLI route has ever run here.

**(b) Install roots** — name filter `(?i)dsh|deepseek|harness|electron` over
`%LOCALAPPDATA%\Programs`, `%LOCALAPPDATA%`, `%APPDATA%`, `%ProgramFiles%`, `${env:ProgramFiles(x86)}` (2026-09-11):
**no matches in any of the five roots.**
`%LOCALAPPDATA%\Programs` contents in full: `Common, JLCONE, KiCad, Microsoft VS Code, playground, Python`.

**(c) Registry uninstall entries** — `Get-ItemProperty` over
`HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*`,
`HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*`, and
`HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*`, filtered on
`(?i)dsh|deepseek|harness|electron` (2026-09-11): **zero rows returned from all three hives.**

**Conclusion for (2): nothing found.** No Electron DSH app, no `desktop` profile, no install directory, no
uninstall entry on `ZABZ-YOGA`. (I did not check `ZABZ-TECH`; it is on a separate network and out of scope here.)

---

## 3. Electron/desktop markers inside the installed packages

**(a) Packages present.** `Get-ChildItem …\@deepseek-ai` in both locations (2026-09-11) listed ~250 packages.
Both trees are **identical in membership**, and **neither contains `dsh-desktop`** or any
desktop/electron-suffixed package. The desktop-adjacent packages that *are* installed are the **web** ones:
`dsh-web`, `dsh-web-app`, `dsh-web-frontend`, `dsh-web-fetch-http`, `dsh-web-search-deepseek`.

- `C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\` (all dirs dated 9/10/2026 6:47:08 PM)
- `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\` (all dated 9/10/2026 6:46:4x PM)

**(b) Content search for `electron` / `BrowserWindow` / `desktop`.** I searched `package.json` across the whole
`@deepseek-ai` tree, then `README.md` across the whole tree, with pattern `(?i)electron|BrowserWindow|desktop`.

- `package.json` — **No matches found.**
- `README.md` — **No matches found.**

**(c) The only hits anywhere are the reservation notice itself.** A recursive
`Select-String 'desktop','Electron','electron'` over the launcher package returned exactly four lines:

| File | Line | Content |
|---|---|---|
| `…\@deepseek-ai\dsh\lib\bin.js` | 28 | `function rejectElectronProfile(program, profile) {` |
| `…\@deepseek-ai\dsh\README.md` | 20 | "…The `desktop` name is reserved for the Electron-owned profile, so the CLI rejects boot, config-dump, and plugin-management requests for it." |
| `…\@deepseek-ai\dsh\README.zh.md` | 20 | (same statement in Chinese) |
| `…\@deepseek-ai\dsh\README.i18n.yaml` | — | (the translation source for that line) |

Launcher version confirmed by reading `…\@deepseek-ai\dsh\package.json`: `@deepseek-ai/dsh` **`0.1.5-rc.1`**.

**Conclusion for (3): what exists** is only the *reservation* of the `desktop` profile name and the CLI guard
that enforces it. **What does not exist:** any installed package that names, documents, or implements Electron,
`BrowserWindow`, or a native desktop window. There is no `dsh-desktop` code on this machine to run.

---

## 4. If a desktop app exists: multi-window, `--port`, restoration, `DSH_HOME`

It exists as source (see §1), so I answered these **from the official source**, not from speculation. All files
are from `https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/apps/desktop/src/…`, read
2026-09-11.

### 4a. Multiple independent windows/processes — **NO. This is hard, by design.**

`src/single-instance.ts` in full (read 2026-09-11):

```ts
export function claimDesktopSingleInstance(
  application: DesktopSingleInstanceApplication,
  focusOwner: () => void,
): boolean {
  if (!application.requestSingleInstanceLock()) {
    application.quit()
    return false
  }
  application.on('second-instance', focusOwner)
  return true
}
```

The doc comment above it reads: *"Claim the process-lifetime Desktop lock and route later launches to the
owner."* It is wired in `src/main.ts:506` (read 2026-09-11):

```
 506:   const ownsDesktopInstance = claimDesktopSingleInstance(app, () => { focusPrimaryWindow() })
 508:   if (ownsDesktopInstance) void app.whenReady().then(main).catch(async (error: unknown) => {
```

So a **second launch of the app quits immediately and merely focuses the first window.** The official desktop
README confirms the intent is deliberate:

> "Electron acquires its process-lifetime single-instance lock before any profile access and **exclusively owns
> `$DSH_HOME/profiles/desktop`** plus its package-manager state."

and the stated reason is explicitly to prevent races: *"two desktop processes could race on the same profile."*
The desktop README also says *"The CLI cannot boot or mutate this profile."*

`BrowserWindow` construction happens at exactly three places in `main.ts`: `createWindow` (line 90), the main
window (line 453), and the plugin-management window (line 429), plus an emergency-document fallback (line 515).
There is **no `app.on('second-instance')` handler that opens a new window** — it calls `focusOwner`, i.e.
`focusPrimaryWindow` (`main.ts:467–478`), which either shows/focuses the existing window or **recreates the single
main window** if it was closed. `mainWindow` is a single variable, and closing it quits the app on Windows
(`main.ts:483–484`: `app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })`).

**Therefore: one instance, one main window.** The official desktop app cannot give you 8–12 independent
windows — it gives you **one**. It is the wrong tool for this repo's objective.

### 4b. `--port`-style argument — **NO.**

`main.ts` contains **no `process.argv` handling and no `--port`/`--host` family.** The only "port" references in
the whole file are:

- `developmentHostInspectPort()` (`main.ts:80–87`), which reads the **env var** `DSH_DESKTOP_HOST_INSPECT_PORT`
  and throws `dsh desktop: DSH_DESKTOP_HOST_INSPECT_PORT must be an integer from 1 through 65535` if invalid;
- the dev-only debugging ports documented in the README (Main 9229, Renderer 9222, Host 9230) and their
  `DSH_DESKTOP_*_PORT` env overrides.

That is Node inspector plumbing for development, not the app's serving port. Structurally there is nothing to
point at a port: the app **opens no listening port at all** — it carries traffic over framed byte pipes and
serves client assets over the custom `dsh-app://` scheme (README, §1a). The web app's `--port`/`--host`/
`--trusted-host`/`--no-open` flags (`BRIEF.md` fact #1) belong to `dsh-web-app` and have **no counterpart** here.

### 4c. Window restoration on restart — **NO (only a fixed default geometry; state is not persisted).**

`main.ts:90–104` (read 2026-09-11) hardcodes the window at creation:

```ts
function createWindow(preload: string, show = false): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 880,
    minHeight: 600,
    show,
    webPreferences: { preload, nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true },
  })
```

I grepped `main.ts` for `restore|fullscreen|setBounds|windowState|kiosk` — the only `restore` hit is
`if (window.isMinimized()) window.restore()` (`main.ts:475`), i.e. **un-minimising**, not state persistence.
There is no window-bounds save/load, no session-restore of windows, and no per-window position memory.
`createWindow` is always called with its hardcoded 1280×840.

*Caveat, stated honestly:* I read `main.ts`, `single-instance.ts` and `paths.ts` directly. I did **not** read all
19 files in `apps/desktop/src` (listed via the GitHub API: `backend-controller.ts`, `core-package-set.ts`,
`host-process.ts`, `host-protocol.ts`, `ipc.ts`, `locale.ts`, `main.ts`, `owned-directory.ts`, `paths.ts`,
`preload-app.ts`, `preload.ts`, `profile-packages.ts`, `project-manager.ts`, `release.ts`, `runtime-tree.ts`,
`single-instance.ts`, `startup-document.ts`, `startup-error.ts`, `update-coordinator.ts`). A window-bounds
persister living in one of those unread files cannot be excluded, but it would be unusual (window geometry
normally lives in the main process) and none of the README's architecture description mentions it.
**`UNVERIFIED:` window-bounds persistence in the unread `apps/desktop/src` modules.**

### 4d. Own `DSH_HOME` or the user's — **shares the user's `DSH_HOME`; owns only the `desktop` sub-tree.**

`src/paths.ts` (read 2026-09-11), in full relevant part:

```ts
export function resolveDesktopPaths(dshHome: string = resolveDshHome()): DesktopPaths {
  const root = join(dshHome, 'desktop')
  const pnpm = join(root, 'pnpm')
  return {
    root,
    profile: join(dshHome, 'profiles', 'desktop'),
    lock: join(dshHome, 'profiles', 'desktop', 'lock'),
    pnpm: { root: pnpm, store: join(pnpm, 'store'), cache: join(pnpm, 'cache'),
            state: join(pnpm, 'state'), config: join(pnpm, 'config'), home: join(pnpm, 'home') },
  }
}
```

with the doc comment *"Harness home shared with npm-installed dsh."* So the desktop app **resolves the same
`DSH_HOME`** (`C:\Users\ezabz\.dsh` here) and **shares product data** — sessions, settings, credentials — with
the CLI, while owning exclusively: `$DSH_HOME/profiles/desktop` (its profile + `lock`), and `$DSH_HOME/desktop/pnpm`
(its store/cache/state/config/home). The README states the split exactly:

> "CLI and Desktop share supported product data under `$DSH_HOME`, but never executable packages, plugin
> activation, lockfiles, or `node_modules`."

Two consequences worth recording for later planning:
1. Desktop sessions would appear in the **same** session store as the CLI's — so a desktop app is not a way to
   get a second, separate DSH identity, and
2. the desktop profile's plugin graph is **independent** of `profiles/web` — you would have to install plugins
   into `profiles/desktop` separately, and the CLI is forbidden from managing it.

Development mode is the one exception that keeps state away from the user's home: the README says dev state
defaults to `apps/desktop/.desktop-build/development/home`, and *"An explicit `DSH_HOME` replaces only the
development Harness home."*

---

## 5. It does not exist as an installable artifact — so what is the best supported alternative?

**Plainly:** there is **no official, downloadable, installable DSH desktop app** for Windows today. The app is
source-only (`private`, unpublished, zero release assets, empty CDN origin) and, decisively, it would
**not** satisfy the requirement anyway, because of the single-instance lock (§4a). Even a perfect install would
give `ZABZ-YOGA` **one** window, and would not open 8–12.

Requirement restated from `BRIEF.md`: *"a real app icon that opens the GUI, restores its windows, and survives
closing the terminal."* Note carefully that **one `dsh web` process already hosts many independent agent
sessions** (`BRIEF.md` fact #3), so the requirement is satisfiable **without** the desktop app at all — the only
real gaps are (i) a supervisor that survives the terminal, (ii) app icons/shortcuts, and (iii) window restore.

### (a) Install the existing web GUI as a Chromium/Edge PWA app window — **recommended, with one caveat**

**What the manifest actually supports today** — this is the direct answer to the brief's `"display": "fullscreen"` note.
`C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\dsh-web-frontend\dist\manifest.webmanifest` (read 2026-09-11, 16 lines, complete):

```json
{
  "id": "/",
  "name": "DeepSeek Harness",
  "short_name": "DSH",
  "start_url": "/",
  "scope": "/",
  "display": "fullscreen",
  "icons": [
    { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" }
  ]
}
```

It is correctly wired (`dist/index.html:6`: `<link rel="manifest" href="./manifest.webmanifest" />`), and the
frontend package is `@deepseek-ai/dsh-web-frontend` **`0.1.5-rc.2`** — newer than the installed launcher
(`0.1.5-rc.1`).

**What it does *not* support — the blocker:**
- **No service worker.** I counted string occurrences in the built shell bundle
  `dist\assets\index-BKQ_L1z6.js` (555,926 bytes) on 2026-09-11 — command:
  `[regex]::Matches($c,'serviceWorker').Count`:

  | String | Occurrences in shell bundle |
  |---|---|
  | `serviceWorker` | **0** |
  | `pushState` | **0** |
  | `replaceState` | **0** |
  | `location.hash` | **0** |
  | `sessionId` | **0** |

  No service worker means **no offline capability and no installability-as-PWA**. Chromium's "Install app" /
  "Install this site as an app" still creates an **app shortcut window** — that path does not require a service
  worker — so an **icon that opens a chromeless window is achievable**, but it is a *shortcut window*, not an
  installable PWA. That is sufficient for "a real app icon that opens the GUI"; it is **not** installable in the
  strict PWA sense, and it will not work offline.
- **Icons are SVG-only** (`favicon.svg`, `sizes: "any"`), with **no** 192×192/512×512 PNG maskable entry. Fine
  for a Windows shortcut icon; not the shape a strict PWA installability check wants.
- **`"display": "fullscreen"`** is a real UX caveat, not a blocker: a Chromium app window for `display:
  fullscreen` opens fullscreen, which fights the "8 windows I can arrange and restore" objective. **This is a
  one-line fix** — change `display` to `window-controls-overlay`/`minimal-ui` — but it cannot be edited in place
  responsibly: `dist/` is installed package content under `$DSH_HOME/profiles/node_modules`, so a local edit is
  an unversioned overlay that any package reinstall silently reverts. It belongs upstream in `apps/web`.
  **`UNVERIFIED:` whether this Chromium/Edge build actually honours `display: fullscreen` for a *shortcut*
  window (as opposed to an installed PWA) — I could not test it without launching a server and creating a
  shortcut, both outside this task's constraints.**

**The deeper blocker for (a) — and for (b) — is the auth handshake.** From
`…\@deepseek-ai\dsh-client-connection\README.md` line 35 (read 2026-09-11):

> "Each process mints a random launch token. `dsh-web-app` prints and opens the ordinary root URL with
> `?token=...`; `frontend-static` delegates root and index requests to `ctx.connection.authorizeIndex`, which
> accepts that token only on `GET /`, writes an authority-bound signed cookie, and redirects to clean `/`. A
> missing, expired, malformed, or wrong-authority cookie returns **401** before RPC dispatch. Static assets remain
> public."

Confirmed in the installed `dsh-web-app` README line 37: *"you see a `dsh web:` line whose root URL carries a
fresh process token."* Consequences:
- Any new window/shortcut must receive **the current process's tokenized URL once**, or it gets **401**. A PWA
  shortcut whose `start_url` is bare `/` will work **only while** the authority-bound cookie is still valid
  (default 30-day max age per `BRIEF.md` fact #4; the cookie binds normalized hostname + port).
- The cookie's authority binding includes the **port**, so if you let the port change (`--port 0`), a previously
  saved shortcut **loses its authority and 401s**. A supervisor must therefore pin a **stable port per window**
  if shortcuts are to keep working. This is a concrete design constraint, derived from the two sources above.
- **No per-session deep link exists.** `pushState`, `replaceState`, `location.hash` and the literal `sessionId`
  all appear **0 times** in the shell bundle, and a sweep of all installed `dsh-client*` packages for
  `pushState`/`replaceState`/`searchParams.set(…session…)` returned only
  `dsh-client-connection\lib\index.js:374: url.hash = "";` (which *clears* the hash after the token exchange) and
  unrelated hashing code. **This confirms `BRIEF.md` fact #6's suspicion: there is no per-session URL.** You
  cannot open "window for session X" by URL; each window lands on the same root shell and the user picks the
  session. *Caveat:* `dsh-client-ui-session` client bundles are loaded at runtime from each package's
  `lib/client.js`; my sweep of those files found no URL routing, but a per-session link implemented through
  Host RPC rather than the URL would not have shown up. **`UNVERIFIED:` no alternative per-session addressing
  mechanism via Host RPC.**

**Verdict on (a):** the best *low-effort* route for icons + chromeless windows + persistence of a session across
terminal close, **provided** the supervisor pins stable ports and hands each window its tokenized URL once. The
`display: fullscreen` value and the missing service worker/PNG icons are the two things to fix upstream.

### (b) A small Electron/Tauri wrapper you build around the existing web UI — **works, and is what the ecosystem actually did; but it does not beat (a) for this goal**

Evidence this is the community's chosen route: at least ten third-party wrappers exist
(`agent-earth/deepseek-harness-desktop`, `lencx/Minke`, `dataelement/dsh-desktop`,
`cherrchen/deepseek-harness-electron`, `xizhilanre/…`, `RZX00/…`, `LambProgrammer/dsh-desktop-zero`,
`xiincs/…` and a Microsoft Store listing), and their published architectures are near-identical to what I would
build: spawn `dsh web --host 127.0.0.1 --port 0`, poll for readiness, load the URL in a sandboxed
`BrowserWindow`. `agent-earth/deepseek-harness-desktop`'s README, read 2026-09-11, is representative —
"Single-instance window", "Harness child-process lifecycle", "Random loopback port and readiness checks",
"Sandboxed BrowserWindow". `zouyuxuan122/Deepseek-Harness-EAC` documents the same shape with the explicit
command `dsh web --host 127.0.0.1 --port 0`.

Two things make this worse than it looks:
1. **The wrappers are single-window too.** Every one I inspected advertises a *single-instance* window
   (`agent-earth`: "Single-instance window"; `zouyuxuan122`: "Single-instance lock / window / menu /
   lifecycle"). None advertises multi-window. **`UNVERIFIED:` whether any community wrapper supports multiple
   independent windows — I read READMEs, not their source, and absence of a claim is not evidence of absence.**
   So building your own wrapper is the only way to get multi-window *and* the added value would be the wrapper
   itself, not the packaged app.
2. **It duplicates a solved problem.** You would re-implement process supervision, tray, port allocation and
   cookie/token handoff — the exact things the official `apps/desktop` already implements and that a supervisor
   script gets for free.

**Verdict on (b):** technically sound and proven feasible by the ecosystem, but it is **more** work than (a) for
the *stated* requirement, and its marginal benefit is only cosmetic (a native frame and titlebar) unless you
deliberately implement multi-window, which no existing wrapper does.

### (c) A Windows scheduled-task/tray supervisor plus browser windows — **recommended core mechanism**

This is the only option that directly satisfies "survives closing the terminal" and the real 8–12 requirement,
because the multiplicity lives in the **web server process**, which already hosts many independent sessions
(`BRIEF.md` fact #3): one `dsh web` process + N browser/app windows pointing at it.

Constraints it must respect, all sourced above: pin **one stable port per window-set** (the cookie binds
hostname+port, so a changing port invalidates saved shortcuts); capture and hand each new window the
**tokenized** URL once; expect and log **401** on any window that arrives without the cookie; and accept a
**~830 MB + 8×60 MB** process footprint per server (`BRIEF.md` fact #8) — so "12 windows" should mean *12 windows
over few servers*, not 12 servers, unless the memory is spent deliberately.

**Where a supervisor stops being enough:** it cannot restore *which session* a window was showing, because no
per-session URL exists (§5a). "Restore its windows" can therefore only mean *reopen the same windows at the same
URLs*, with the user re-picking sessions — unless a per-session deep link is added as a client-side package
(the `cordis-plugin-development` skill's territory).

### Recommendation, ranked

1. **(c) as the mechanism + (a) as the window surface.** A supervisor (scheduled task at logon + tray) starts
   one `dsh web` on a pinned port, captures the tokenized URL, installs Edge/Chromium app-shortcut windows for
   the desired count, and reopens them on restart. Best fit, least new code, no unverified dependencies.
2. **(b) only if a native frame/tray or multi-window is itself wanted** — and then build multi-window
   deliberately rather than adopting any existing wrapper, all of which are single-window.
3. **Do not plan around the official `apps/desktop`.** It is not installable today, and its single-instance lock
   means it structurally cannot serve the 8–12-window goal even when it is.

### Blockers found (consolidated)

| # | Blocker | Evidence |
|---|---|---|
| B1 | Official desktop app is not installable: `private: true`, absent from npm, **0 release assets** on the 5 latest releases, documented CDN origin 404s | §1b |
| B2 | Official desktop app is **single-instance by design** → 1 window, not 8–12 | `apps/desktop/src/single-instance.ts` + `main.ts:506` |
| B3 | Official desktop app takes **no `--port`/`--host`** and opens no port at all | §4b; README "opens no listening port" |
| B4 | No **window-state persistence**; geometry hardcoded 1280×840 | `main.ts:90–104`; `UNVERIFIED:` for the 16 unread `src` modules |
| B5 | Web frontend has **no service worker** → not a strict installable PWA (shortcut window still possible) | 0 occurrences of `serviceWorker` in `index-BKQ_L1z6.js` |
| B6 | Manifest declares `"display": "fullscreen"` → app windows open fullscreen; fix belongs upstream | `dist/manifest.webmanifest:7` |
| B7 | **No per-session deep link** → windows cannot restore *which* session they showed | 0 occurrences of `pushState`/`replaceState`/`sessionId` in shell bundle; all `dsh-client*` swept |
| B8 | Launch is **token-gated** (`?token=…` → authority-bound cookie, else **401**), and the authority binds hostname**+port** → shortcuts break if the port changes | `dsh-client-connection/README.md:35`; `dsh-web-app/README.md:37` |
| B9 | Desktop profile plugin graph is **independent** of `profiles/web` and CLI-forbidden → plugins must be installed twice | `apps/desktop/README.md`; `bin.js:28–30` |

---

## Method, provenance and limits

- **Date of every observation: 2026-09-11**, local `-04:00`, on `zabz-yoga`.
- **Local readings** are from `C:\Users\ezabz\.dsh\…` (installed `@deepseek-ai` packages) and
  `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\…`, read with `pwsh` 7.6.6 and
  `Invoke-WebRequest` / `Invoke-RestMethod`.
- **Remote readings** are raw GitHub `master` content plus the GitHub REST API, **not** a pinned commit. `master`
  moves; the `0.1.5-rc.2` desktop sources cited here correspond to tag `dsh-v0.1.5-rc.2` (2026-09-10), but I read
  the branch, so a later `master` could differ. **`UNVERIFIED:` byte-identity of the cited `master` files with
  tag `dsh-v0.1.5-rc.2`.**
- **Not done, by instruction:** no servers started, nothing installed or uninstalled, nothing modified outside
  this file pointer, no `ZABZ-TECH` inspection.
- **`UNVERIFIED:` items are labelled inline** and are: window-bounds persistence in the 16 unread
  `apps/desktop/src` modules; whether any community wrapper supports multi-window; whether Chromium honours
  `display: fullscreen` for a shortcut window; the absence of an RPC-based per-session addressing mechanism;
  and `master`-vs-tag file identity.
- **A negative that is reported as a negative, not as health:** §2 and §3's "nothing found" results are the
  product of the exact commands shown, run on the five install roots, three registry hives and two
  `node_modules` trees listed. They establish absence on `ZABZ-YOGA` only.
