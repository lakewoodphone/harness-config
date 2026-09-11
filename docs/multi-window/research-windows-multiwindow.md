# Windows: 8–12 persistent, independently-restorable app windows over a localhost web UI

**Author:** research subagent · **Date read/written:** 2026-09-11 (America/New_York) · **Machine:** ZABZ-YOGA,
Windows 11 Home 25H2, Edge **152.0.4191.66** (`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, read
2026-09-11), 4 monitors: `\\.\DISPLAY1` 1440×900 primary, `\\.\DISPLAY2/3/4` 2560×1440 (read 2026-09-11 via
`[System.Windows.Forms.Screen]::AllScreens`).

**Method.** Official docs first (Microsoft Learn, Chromium docs, Electron docs). Where docs were silent or
contradictory I ran a **live experiment on this machine** — launching Edge `--app` windows with separate
`--user-data-dir`s and reading real window rectangles with `GetWindowRect`. Experiment results are labelled
**[MEASURED on ZABZ-YOGA 2026-09-11]**. Nothing outside `%TEMP%\mwtest*` and the output file was touched; the DSH
instance on port 3080 was not touched; all test processes and temp profiles were removed afterwards.

Environment facts used: target = many `dsh web` servers, one port each; the auth cookie is bound to
`normalized hostname + port` (`BRIEF.md` items 4–5, read 2026-09-11); the frontend has **no service worker**, so
PWA installability is questionable — see Q1b.

---

## Q1. Persistent, isolated app windows over a localhost web app

### (a) Chromium/Edge `--app=` with a separate `--user-data-dir`

**Isolation — yes, per `--user-data-dir`.** Chromium docs: "The user data directory contains profile data such as
history, bookmarks, and cookies" and "the `--user-data-dir` flag takes precedence if both are present"
([chromium/src docs/user_data_dir.md](https://chromium.googlesource.com/chromium/src/+/main/docs/user_data_dir.md),
read 2026-09-11). **MEASURED:** two simultaneous Edge instances with `--user-data-dir=%TEMP%\mwtest2\a` and `...\b`
each created their own `Default\Preferences` (15488 b / 11030 b) and their own `Default\Local Storage\leveldb`, so
**cookies, localStorage, IndexedDB and the browser-session signing cookie are per-window because they are
per-profile.** Relaunching the *same* profile rejoins the same browser instance (normal Chromium single-instance
behaviour) — one profile = one window, exactly the 8–12-window shape wanted.

**Size, position, script launch — supported, but only with one profile per window.** Documented switches:
`--window-size=w,h`, `--window-position=x,y`, `--window-name="My custom title"`
([Peter Beverloo's Chromium switch list](https://peter.sh/experiments/chromium-command-line-switches/), read
2026-09-11 — third-party but generated from Chromium source and cited by Google/Microsoft engineers).
**MEASURED:** with a distinct `--user-data-dir` each, both windows landed exactly where asked —
`DSH-B X=1100 Y=120 W=700 H=500` from `--window-size=700,500 --window-position=1100,120`, and both were launched
from `pwsh Start-Process msedge.exe -ArgumentList ...` behaving as if launched by hand. **Counter-evidence
(documented bug):** launched into an *already-running* browser instance, size/position are ignored — "Any
subsequent window opened with `--app=...` and `--window-size=...` and `--window-position=...` gets the window size
and position of the first one started", filed on Windows 10, still open in 2023
([issues.chromium.org/40964468](https://issues.chromium.org/issues/40964468), read 2026-09-11). **Consequence:
separate `--user-data-dir` is not merely for isolation — it is what makes geometry work.**

**`--window-name` does not work on Windows.** **[MEASURED]** passing `--window-name=DSH-Beta` gave a window titled
with the page's `<title>` (`DSH-B`), not `DSH-Beta` — in Chromium it is an Ash/ChromeOS switch, beside
`--window-workspace`, with no platform matrix in the switch list ([same source](https://peter.sh/experiments/chromium-command-line-switches/),
read 2026-09-11). Treat it as unusable here: the **page `<title>` is the window title**, which is fine because each
DSH server can serve its own title.

**Does an `--app` window restore its own geometry after a restart?** Edge *does* persist it, but **not keyed to
anything you control.** **[MEASURED]** after a cleanly-positioned window, `Default\Preferences` in that profile
contained:

```json
"browser": { "app_window_placement": {
  "_text/html,<title>DSH-B</title><h1>B</h1>": {
    "left":1100,"top":120,"right":1800,"bottom":620,"maximized":false,
    "work_area_left":0,"work_area_top":0,"work_area_right":1440,"work_area_bottom":852 } } }
```

Three things follow. (1) The **storage key is the app URL's origin/spec**, not a window name and not the port
label — so a server that changes port loses its geometry. (2) The record stores the **work area as well as the
rect**, which is exactly the data needed to detect that the monitor topology or taskbar changed. (3) The key is
`app_window_placement`, an **undocumented internal key** — relying on it is fragile
(`UNVERIFIED: no Microsoft or Chromium documentation of app_window_placement exists; verified only by reading the
file on ZABZ-YOGA 2026-09-11`).

**Verdict:** `--app` + per-window `--user-data-dir` is the cheapest correct isolate, **but you must store the
geometry yourself** (see the box at the end of Q1) and pass it back on every launch.

### (b) Installed PWAs ("Install this site as an app")

**What Microsoft documents.** PWAs installed from Edge behave as Windows apps: they appear in the Taskbar, Start
menu and Alt+Tab, and have a documented **Auto-start on device login** toggle
([Use PWAs in Microsoft Edge](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/ux), page last
updated 2026-03-10, read 2026-09-11) — the built-in answer to "reopen after reboot".

**How they launch.** The installed shortcut runs `msedge_proxy.exe` with an app id, e.g.
`"C:\Program Files (x86)\Microsoft\Edge\Application\msedge_proxy.exe" --profile-directory=Default --app-id=<id>`
(question text + comments on
[superuser 1619172](https://superuser.com/questions/1619172/where-does-windows-10-chrome-or-edge-stores-the-data-of-an-installed-pwa),
read 2026-09-11 — **forum source**; corroborated by a community report that the shortcut "calls the
`msedge_proxy.exe` with the 'App ID' and the URL"
([Spiceworks](https://community.spiceworks.com/t/deploy-edge-chrome-site-as-app-and-customize-desktop-shortcut/785931)
— **forum source**)). So a PWA *can* be scripted by copying that command line with `--app-id=`.
`UNVERIFIED: no Microsoft page documents the msedge_proxy.exe --app-id command line as supported.`

**Known Windows caveats (documented).** PWAs are **not supported in FSLogix environments** — "you can install a
PWA, but when you log off and then log back in, the installed PWA is gone" (same page, read 2026-09-11). Not
applicable here (no FSLogix), but it shows install is profile-container-sensitive.
`UNVERIFIED: where Edge stores per-PWA window geometry. No `Web Applications` directory exists in this machine's
Edge profile (`%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Web Applications` → Test-Path False, checked
2026-09-11); the forum answer placing it under `User Data\Default\Extensions` is 2021-era and unverified on Edge 152.`

**The blocker for *this* use case.** A DSH server is a different origin per port and the frontend ships **no
service worker** (`BRIEF.md` item 5, read 2026-09-11); Edge installability requires an installable manifest and
typically a service worker, so the install affordance may not appear. **UNVERIFIED on the live app** — I did not run
a DSH server in this task. And an installed PWA is bound to one origin: **12 ports = 12 manual installs**, with no
documented scripted-install path.

### (c) Electron/Tauri wrapper you build

**Electron has this exact feature built in, documented.** "Window State Persistence allows your Electron
application to automatically save and restore a window's position, size, and display modes (such as maximized or
fullscreen states) across application restarts." It keys state to a **unique `name`** you supply, restores it on
window creation, saves on every change, emits `persisted-state-restored`, and — critically — "**Adapt restored
window state to multi-monitor setups and display changes automatically**"; options are
`windowStatePersistence: { bounds: true, displayMode: true }`
([electron docs/tutorial/window-state-persistence.md](https://github.com/electron/electron/blob/main/docs/tutorial/window-state-persistence.md),
read 2026-09-11). The older popular alternative is `electron-window-state`
([mawie81/electron-window-state](https://github.com/mawie81/electron-window-state), read 2026-09-11), whose bug
list includes "Window size not preserved correctly when multiple displays use different screen scaling"
([issue #80](https://github.com/mawie81/electron-window-state/issues/80), read 2026-09-11) — i.e. **display scaling
is the hard part, and the built-in feature claims to handle it while that library does not.** Cost: a 100 MB+
runtime, a build pipeline, code signing and Chromium patch cadence. Tauri is lighter but has no equivalent
built-in persistence — you would write the geometry logic yourself (`UNVERIFIED: no official Tauri window-state
persistence documentation found in this pass.`)

### Which one actually restores a set of windows to the same layout after a reboot

| Approach | Restores layout after reboot? | Evidence |
|---|---|---|
| `--app` + own launcher | **Yes, if the launcher passes `--window-size`/`--window-position` on every launch.** Edge's own stored placement is origin-keyed and undocumented. | MEASURED 2026-09-11; [issues.chromium.org/40964468](https://issues.chromium.org/issues/40964468) |
| Installed PWAs | Partly: "Auto-start on device login" reopens the windows; geometry restore undocumented; no scripted install. | [MS Learn PWAs](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/ux) (2026-03-10) |
| Electron/Tauri | **Yes**, by design and documentation, including multi-monitor adaptation. | [Electron window-state-persistence](https://github.com/electron/electron/blob/main/docs/tutorial/window-state-persistence.md) |
| PowerToys Workspaces as restorer | **Yes, as an external agent** that launches then moves/resizes; it "cannot tell an app to launch to a specific position". | [PowerToys Workspaces](https://learn.microsoft.com/en-us/windows/powertoys/workspaces) (2025-08-20) |

**What exactly has to be stored** (from the two mechanisms above and from what Edge itself stores —
**[MEASURED]** in `app_window_placement`):

- **window handle** — *do not store*. Handles are not stable across a reboot and mean nothing to a fresh process;
  they are only useful within one session for "is it already up" checks. Match windows by title or owning PID.
- **position + size** — the client rect (`left/top/right/bottom`) plus whether it was maximized.
- **monitor identity** — the device name (`\\.\DISPLAY2`), not just a coordinate, because coordinates shift when a
  monitor is unplugged or rearranged.
- **the monitor's work area** — Edge stores `work_area_left/top/right/bottom`; this detects a moved taskbar or a
  changed display and keeps windows off the taskbar. **[MEASURED]** this machine's primary work area is 1440×**852**
  — 48 px shorter than the 900 px screen.
- **display scaling / DPI per monitor** — required, per Electron's multi-monitor adaptation claim and
  `electron-window-state` bug #80. This machine mixes a 1440×900 panel with three 2560×1440 panels, so a saved rect
  must be re-validated against the current topology before use.
- **the port/profile pairing** — "window N ↔ port N ↔ user-data-dir N", which must never drift, because the auth
  cookie is bound to host+port (`BRIEF.md` item 4).

> **Q1 recommendation:** Use Edge `--app=<http://127.0.0.1:PORT/>` with one dedicated `--user-data-dir` per window,
> launched by your own script that passes an explicitly persisted `--window-size`/`--window-position` (save the
> rect, the monitor device name and its work area, and the per-monitor scale factor, then re-clamp on every
> launch); do not depend on Edge's internal `app_window_placement`, and do not expect `--window-name` to work on
> Windows.

---

## Q2. Reliable launch of a set of background processes at Windows logon that must survive the terminal closing

Scope: N per-user servers that must (i) hold a user's `DSH_HOME` and that user's credentials, (ii) start at
logon, (iii) outlive the terminal that started them.

### Option 1 — Task Scheduler

Documented triggers include "When the system is booted", "When a user logs on" and "When a Terminal Server
session changes state" ([Task Scheduler for developers](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page),
read 2026-09-11 — **that page does not document the two run-modes; those claims are community-sourced and
labelled as such below**).

**"Run only when user is logged on" vs "Run whether user is logged on or not".** The second mode runs the task in
a non-interactive session, so **the GUI never appears**: "when i run Task with 'Run only when user is logged on'
works fine it opens the .exe, but when i use 'Whether user is logged on or not'" it does not
([Spiceworks thread](https://community.spiceworks.com/t/task-scheduler-and-run-whether-user-is-logged-on-or-not-not-openning-ps-or-cmd/961596),
read 2026-09-11 — **forum source**). The mechanism is documented: "All services run in Terminal Services session
0. Therefore, if an interactive service displays a user interface, it is visible only to the user who connected to
session 0" ([Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services),
read 2026-09-11). A GUI-less `dsh web` server would *survive* in that mode, but its window could never be shown in
the user's session — so **the correct mode for a GUI-adjacent fleet is "run only when user is logged on" with an
At-logon trigger.**

**Failure modes:**
- **Environment not inherited:** "Windows 2012 Scheduled Tasks do not see the correct environment variables,
  including `PATH`, for the account which the task is set to run as"
  ([serverfault 631995](https://serverfault.com/questions/631995/program-does-not-run-properly-as-scheduled-task),
  read 2026-09-11 — **forum source**); see also
  [SO 11824319](https://stackoverflow.com/questions/11824319/windows-7-task-scheduler-doesnt-use-updated-path).
  Microsoft's troubleshooting answer likewise says to "Confirm that environment variables and network mappings are
  accessible within the scheduled context"
  ([MS Learn Q&A 3849246](https://learn.microsoft.com/en-us/answers/questions/3849246/having-difficulty-getting-a-scheduled-task-to-work)).
  **Do not rely on `PATH`, `DSH_HOME`, `npx` or mapped drives; set them explicitly and use absolute paths.**
- **Network not yet up at logon** (Tailscale, mapped drives, LAN): `UNVERIFIED — no Microsoft statement
  quantifying the window.` Mitigation: the launcher waits on its own dependencies with a bounded retry loop
  instead of assuming the network exists. For this fleet nothing between the windows and their localhost servers
  needs Tailscale, so **Tailscale readiness only matters for anything talking to `secratary`.**
- **Task fails whenever the user is logged off** — expected, same session-0 rule.

### Option 2 — Startup-folder script

Works plainly: a shortcut in `shell:startup` runs at that user's logon **in that user's interactive session**, so
the GUI appears. Community guidance says it directly: "For GUI programs you want visible after unlock, use Startup
folder or per-user Run key or Task Scheduler with 'Run only when user is logged on'"
([Quora answer](https://www.quora.com/Is-it-possible-to-make-a-program-start-every-time-you-login-on-Windows-So-that-I-can-lock-the-computer-log-back-in-and-have-it-start-again),
read 2026-09-11 — **forum source**). Failure modes: **no restart on crash**, no per-item health state, no
ordering, no control UI, and nothing at all on a machine that boots without a logon.

### Option 3 — Windows service wrapper (nssm / WinSW / `sc.exe`)

`sc.exe` alone is documented as insufficient for desktop programs — "Using SC.EXE: Installing your desktop app
with SC works — but it fails to start because the app cannot talk to the Windows Service Control Manager"
([Core Technologies](https://www.coretechnologies.com/blog/windows-services/gui-applications-as-windows-services),
read 2026-09-11 — **vendor blog**). The structural reason is Microsoft's: "Services cannot directly interact with a
user as of Windows Vista", "`NoInteractiveServices` … defaults to 1, which means that no service is allowed to run
interactively, regardless of whether it has `SERVICE_INTERACTIVE_PROCESS`"
([Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)), and
"Because the user is not running in Session 0, he or she never sees the UI and cannot respond to it"
([Session Zero Guidelines for UMDF Drivers](https://learn.microsoft.com/en-us/windows-hardware/drivers/wdf/session-zero-guidelines-for-umdf-drivers),
read 2026-09-11). The vendor page names the usual workarounds and calls them fragile: auto-logon + Startup folder,
Task Scheduler "At Startup" ("timing, permissions, and session targeting can still bite you"), and raw `sc.exe`.
Maintenance, as reported (**forum/vendor sources only**): "NSSM is not more maintained since 2017, WinSW maintenance
seems complicated, no release since 2023 (but still working)"
([r/sysadmin](https://www.reddit.com/r/sysadmin/comments/1k0g6wx/winsw_nssm_shawl_creating_a_service_with_a_dumb/),
read 2026-09-11); new alternative **Servy**, "real-time monitoring, auto-recovery, logging"
([servy-win.github.io](https://servy-win.github.io/), **vendor site**;
[comparison](https://dev.to/aelassas/servy-vs-nssm-vs-winsw-2k46), 2026-01-26 — **vendor blog**).
**UNVERIFIED: release dates, licence and maintenance not checked in the repositories.**

### Option 4 — Tray supervisor

Not a Windows feature; an application pattern — a per-user process with a notification-area icon owning the
children. Same session as the user, so GUI children work; but *you* must build crash detection, single-instance
locking and per-child logging (Q4's list). `UNVERIFIED by documentation` — treat as "write it yourself"
([electron docs/tutorial/tray.md](https://github.com/electron/electron/blob/main/docs/tutorial/tray.md), path
verified 2026-09-11).

> **Q2 recommendation:** For per-user, GUI-adjacent servers holding a user's `DSH_HOME` and credentials, use a
> **Task Scheduler task with an At-logon trigger, "Run only when user is logged on", running as that user**, whose
> action is a launcher that sets every environment variable explicitly (never inherits `PATH`/`DSH_HOME`), uses
> absolute paths, and waits with bounded retry on its dependencies; **not** a service in session 0 — a service can
> hold the data but can never show or be reached by the user's window.

---

## Q3. Telling 8–12 windows apart on the Windows taskbar (Windows 11 25H2)

**Window titles are the thing you actually control.** **[MEASURED 2026-09-11]** an Edge `--app` window's caption
is the **page's `<title>`**, and `--window-name` does not override it on Windows. So the reliable identity
mechanism is: **serve a distinct document title from each DSH server** (e.g. `DSH :3101 · yz1`) — taskbar
tooltip/thumbnail label, Alt+Tab entry and caption all come from it, with no AUMID work needed.

**Grouping is decided by AppUserModelID (AUMID), and Microsoft documents the primitive:**
`SetCurrentProcessExplicitAppUserModelID` "Specifies a unique application-defined Application User Model ID
(AppUserModelID) that identifies the current process to the taskbar. **This identifier allows an application to
group its associated processes and windows under a single taskbar button.**" It "must be called during an
application's initial startup routine **before the application presents any UI**"
([MS Learn](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-setcurrentprocessexplicitappusermodelid),
page last updated 2024-02-22, read 2026-09-11). A Microsoft Q&A thread on Windows 11 25H2 concerns windows
"belonging to the same desktop product" being grouped together
([MS Learn Q&A 5968004](https://learn.microsoft.com/en-us/answers/questions/5968004/windows-11-25h2-clicking-a-thumbnail-in-a-grouped),
2026-08-06, read 2026-09-11) — the behaviour you would be trying to defeat.

- **Separate `--user-data-dir` per window:** separate instance, hence a separate taskbar button — but launching
  `msedge.exe` directly means **you cannot set the AUMID**; it sets its own, and Microsoft's taskbar-pinning
  documentation covers policy-managed pinning
  ([Configure the applications pinned to the taskbar](https://learn.microsoft.com/en-us/windows/configuration/taskbar/pinned-apps),
  read 2026-09-11). So 8–12 windows are Edge-branded buttons distinguished by **title**.
- **Installed PWAs:** these *do* get their own identity — the shortcut carries the app id and Edge assigns a
  distinct AUMID, which is why a PWA "appears in the Taskbar (where it can be pinned), in the Start menu, and when
  switching between apps with Alt+Tab"
  ([MS Learn PWAs](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/ux), 2026-03-10) as a
  distinct app rather than as Edge. Strongest identity available without writing code.
- **Your own Electron/Tauri wrapper:** you fully control the AUMID (Electron exposes taskbar identity —
  [electron docs/tutorial/windows-taskbar.md](https://github.com/electron/electron/blob/main/docs/tutorial/windows-taskbar.md),
  path verified 2026-09-11). Each window becomes a distinct taskbar entity with its own icon, jump list and pinned
  position — the only option giving 12 cleanly labelled, individually pinnable buttons.
- **Launcher-side trick:** a `.lnk` per window with an explicit AppUserModelID, launching **the shortcut** so
  Windows applies that AUMID to the process. `UNVERIFIED: not tested on Windows 11 25H2 in this pass.` It is the
  one mechanism that would give `--app` windows per-window taskbar identity without an app shell.

> **Q3 recommendation:** Make each DSH server serve a distinct `<title>` (`DSH :PORT · name`) as the primary,
> zero-cost discriminator, keep one `--user-data-dir` per window, and if genuinely distinct pinnable taskbar
> buttons are required, spend the effort either on installed PWAs (one per port, manual install) or on an Electron
> wrapper that sets its own AUMID per window — do not expect `--window-name` or a direct `msedge.exe` launch to
> give you separate AUMIDs.

---

## Q4. Health and supervision

**(a) Detect a dead port and restart only that process.** Poll the port, not a process name: a TCP connect to
`127.0.0.1:<port>` (or `Test-NetConnection -Port`) plus an HTTP GET on a cheap endpoint, because `BRIEF.md` item 2
establishes that `dsh web` **rejects plugin init on `EADDRINUSE` rather than silently picking another port**, so
"port is bound" and "this server is alive" are the same fact. One child per port, so the supervisor restarts
exactly the failed index. `UNVERIFIED by documentation: an engineering pattern, not a Windows feature; see the
[Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services) page (read
2026-09-11) for why the "monitoring, auto-recovery, logging" *service* category does not solve GUI-adjacency.`

**(b) Avoid two supervisors fighting over the same port.** Cross-process mechanisms that work: a **named mutex**
or a **byte-range lock on a per-port lock file** held for the child's lifetime, plus the port bind itself as last
defence (the second binder gets `EADDRINUSE`, per `BRIEF.md` item 2). Take the lock *before* launching; if it is
held, treat the port as already supervised and exit the duplicate supervisor rather than killing and relaunching in
a loop. `UNVERIFIED by documentation: no Microsoft page describes supervisor de-duplication. NSSM's selling point
is the same guarantee — it "monitors the running service and will restart it if it dies … with nssm you know that
if a service says it's running, it really is" ([winsw issue #606](https://github.com/winsw/winsw/issues/606), read
2026-09-11 — forum source) — which you must reproduce yourself outside a service.`

**(c) Per-port stdout/stderr logs.** One descriptor pair per child, `logs/<port>.out.log` /
`logs/<port>.err.log`, with the launcher appending a start/exit line. Logging and rotation are also headline
features of the service wrappers ([nssm.cc](https://nssm.cc/), [servy-win.github.io](https://servy-win.github.io/),
read 2026-09-11 — vendor sites). Never send the fleet's logs to the console of a terminal you intend to close —
`BRIEF.md` tells us the current process was started by hand and died with its terminal.

**(d) One control command for start/stop/restart of all.** One `pwsh` verb set
(`dsh-fleet start|stop|restart|status [port|all]`) reading one manifest (port, `DSH_HOME`, `--user-data-dir`,
window title, saved rect) that lives in `harness-config` as the single source of truth. If you also want OS-level
supervision, register **one** Task Scheduler task that invokes the same module, so OS and CLI never disagree.

**Concrete, free, currently maintained options** (all URLs read 2026-09-11; honesty labels as their sources deserve):

| Option | What it gives | Source / status |
|---|---|---|
| `WinSW` | Service wrapper, logs, restart, XML config | [winsw/winsw](https://github.com/winsw/winsw); **forum claim: no release since 2023** ([r/sysadmin](https://www.reddit.com/r/sysadmin/comments/1k0g6wx/winsw_nssm_shawl_creating_a_service_with_a_dumb/)) — UNVERIFIED by me |
| `NSSM` | Service wrapper, restart-on-death | [nssm.cc](https://nssm.cc/) still online; **forum claim: unmaintained since 2017** |
| `Servy` | GUI manager + CLI/PowerShell module, monitoring, auto-recovery, logging | [servy-win.github.io](https://servy-win.github.io/), [comparison](https://dev.to/aelassas/servy-vs-nssm-vs-winsw-2k46) — **vendor sources**, UNVERIFIED independently |
| Task Scheduler | Free, built-in, At-logon trigger, restart-on-failure | [MS Learn](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page) |
| Your own `pwsh` supervisor | Per-port locks, logs, restart policy — the only option that also manages the *windows* | Bespoke; **no documentation exists** |

> **Q4 recommendation:** Write one `pwsh` supervisor driven by a single checked-in manifest (port, `DSH_HOME`,
> `--user-data-dir`, title, saved rect), with a **per-port lock file/named mutex acquired before launch** as the
> duplicate-supervisor guard, per-port `.out/.err` logs, and a TCP/HTTP health probe per port that restarts only
> that index; register **one** Task Scheduler task (At-logon, run only when logged on) that invokes it — not a
> service wrapper, because a session-0 service can never own the windows.

---

## Q5. Prior art: many parallel agent sessions in many windows

**PowerToys Workspaces (and FancyZones).** Workspaces "helps you launch applications to custom positions and
configurations with a single click", captures the current desktop as a workspace, supports per-app CLI arguments,
and creates a desktop/taskbar shortcut for one-click relaunch
([PowerToys Workspaces](https://learn.microsoft.com/en-us/windows/powertoys/workspaces), page last updated
2025-08-20, read 2026-09-11) — **the most directly applicable prior art:** the "capture once, relaunch the set"
model plus per-app CLI arguments; an entry can point at
`msedge.exe --app=http://127.0.0.1:3101 --user-data-dir=...`. Its documented limits: "**PowerToys cannot tell an
app to launch to a specific position.** What we can do is launch an app first, and then give an instruction to
move and resize it" (windows visibly jump); snapping is not reproduced; "there is a known issue where apps that
launch as admin are unable to be repositioned"; and it names this brief's central trap — apps already running may
reposition instead of launching a new instance, and single-instance apps cannot be launched twice at all.
`UNVERIFIED: whether Workspaces persists across a reboot by itself — it is a shortcut you launch.` FancyZones is
the layout engine underneath ([FancyZones](https://learn.microsoft.com/en-us/windows/powertoys/fancyzones), read
2026-09-11): it resizes/repositions dragged windows; it is not a launcher, and a long-standing request asks for
exactly "Save and Restore Window Positions Across Multiple [monitors]"
([PowerToys issue #31377](https://github.com/microsoft/PowerToys/issues/31377), opened 2024-02-09, read
2026-09-11).

**Windows Terminal as the container.** Documented command-line support for windows/tabs/panes, including **named
windows**: `wt -w foo nt` ("new tab in the terminal window named foo with the default profile. **If foo does not
exist, create a new window named foo**"), `wt -w -1 nt`, `split-pane`
([Windows Terminal command line arguments](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments?tabs=windows),
read 2026-09-11). **Reusable:** addressing a window *by name* and scripting the layout in one command — `wt -w
<name>` is the closest documented "open window N for session N" primitive on Windows. **Not reusable:** a pane
hosts a *terminal app*, not a browser UI, so it is the wrong container for `dsh web` unless you accept a text UI.

**tmux-shaped Windows layouts for agents.** agent-mux is "tmux for humans and AI agents working in the same
terminal" ([maxto/agent-mux](https://github.com/maxto/agent-mux), read 2026-09-11); `psmux` is "a native Windows
terminal multiplexer (25,600 lines of Rust) that implements 76 tmux commands with flag-level compatibility"
([claude-code issue #34150](https://github.com/anthropics/claude-code/issues/34150), 2026-03-13 — **forum
source**). **Reusable:** the coordination model — one supervisor, N labelled sessions, one control command. **Not
reusable:** they multiplex *terminals*; a DSH session is a browser window over HTTP, and none of them can create,
title, position or restore a browser window.

**IDE-native session UIs.** VS Code's "Agent Sessions view" "gives you one place to see all your agent sessions —
local, background, cloud — and move between them"
([code.visualstudio.com blog, 2026-02-05](https://code.visualstudio.com/blogs/2026/02/05/multi-agent-development),
read 2026-09-11 — **vendor blog**). **Reusable as a design target:** a single-window session list is strictly
better than 12 taskbar buttons — evidence the industry answer is *one panel*, not N OS windows. **Not reusable
directly:** it is VS Code's UI. Generic dashboards exist too
([AgentsRoom](https://agentsroom.dev/multi-agent-dashboard), read 2026-09-11 — **vendor marketing page**), and the
pain is widely reported ("Too many windows tabs AI agents overwhelmed",
[r/ADHD_Programmers, 2026-09-04](https://www.reddit.com/r/ADHD_Programmers/comments/1w2gfi6/too_many_windows_tabs_ai_agents_overhelmd/),
read 2026-09-11 — forum source).

> **Q5 recommendation:** Steal the *shape* from PowerToys Workspaces (one captured manifest: command line + rect
> per window, relaunched by one shortcut/script) and the *control surface* from Windows Terminal's named windows
> (`wt -w <name>`) plus VS Code's Agent Sessions panel — treat tmux/psmux/agent-mux as prior art for supervision
> only, because they multiplex terminals and cannot own or restore a browser window.

---

## Summary of the five recommendations

1. **Windows:** Edge `--app=<http://127.0.0.1:PORT/>` + **one `--user-data-dir` per window** — that is what makes cookies/localStorage isolated *and* what makes `--window-size`/`--window-position` work; re-supply saved geometry on every launch; ignore `--window-name` (no-op on Windows).
2. **Boot persistence:** **Task Scheduler task, At-logon trigger, "Run only when user is logged on"**, running as the user, via a launcher that sets `DSH_HOME`/`PATH` explicitly and retries network dependencies — never a session-0 service for GUI-adjacent servers.
3. **Taskbar identity:** a distinct **page `<title>` per port**; separate `--user-data-dir`s give separate buttons; only installed PWAs or your own Electron app give distinct **AppUserModelIDs**.
4. **Supervision:** one `pwsh` supervisor over one checked-in manifest, per-port **lock/named mutex taken before launch**, per-port stdout/stderr files, TCP+HTTP probe per port, and one `start|stop|restart|status` command.
5. **Prior art:** reuse PowerToys Workspaces' capture-and-relaunch model and Windows Terminal's named-window CLI addresses; the tmux-family tools cannot manage or restore browser windows.

## Explicit unknowns left in this report

- `UNVERIFIED`: `--window-name` on non-Windows platforms; where Edge 152 stores per-PWA window geometry (no `Web Applications` directory exists on this machine) or whether an installed PWA restores it; whether a DSH server with no service worker is installable as an Edge PWA; whether a `.lnk` with an explicit AppUserModelID gives `--app` windows per-window taskbar identity on Windows 11 25H2 (not tested); release/maintenance dates for WinSW, NSSM and Servy (forum/vendor claims only); whether PowerToys Workspaces persists a layout across a reboot unaided.
- Not tested at scale: all experiments used **2** windows; 8–12-window behaviour (memory, `dsh` child process count, taskbar rendering) is an extrapolation from `BRIEF.md` item 8's per-process costs.
