# Open questions — multi-window DSH

**How to use this file:** answer one at a time. Each question is self-contained, has options, and a
recommendation marked **(recommended)**. Answering a question moves it to `journal/DECISIONS.md` with
its reason, and the line here is marked answered. Nothing in this list blocks work that is already
underway.

Read `ANALYSIS-AND-DECISION.md` in this directory for the evidence behind each question.

Asked 2026-09-11 · ZABZ-YOGA.

---

## Q1 — How many engines: one shared process, or one process per window?

Measured: an engine with its five MCP bridges costs **~1.4 GB**; the bridges are started per engine, so
every extra engine pays it again. Eight engines ≈ 11 GB, twelve ≈ 17 GB. This laptop has 31.6 GB total
and **7.7 GB free** at the moment of writing (a qemu VM holds 5.3 GB). One engine with 8–12 windows
costs ~2.7–3.1 GB total.

A window is only a browser client: one engine already hosts many **independent** sessions, so ten
windows on one engine are ten separate agents, not ten views of one.

- **(a) One engine, many windows (recommended).** Cheapest and fits the laptop with room to work. A
  window's own browser profile gives it its own cookie jar and its own "last session", so windows stay
  independent. Blast radius: if the engine dies every window reconnects after the supervisor restarts
  it (seconds).
- **(b) One engine per window.** True process isolation — one window's crash cannot touch another. Costs
  ~11 GB at eight windows and ~17 GB at twelve; does not fit the laptop as configured today. Available
  as `"mode": "multi"` in `windows.json` whenever you want it.

**Recommendation: (a)**, with (b) kept switchable for the desktop.

## Q2 — Where should the windows sit, and how should they be identified?

The machine has **four monitors**: DISPLAY1 1440×900 (primary, work area 1440×852) and DISPLAY2/3/4 at
2560×1440. Today's config opens eight windows in a 4×2 grid on the primary display. All eight currently
share the same caption — "DeepSeek Harness" — because an Edge app window's title is the **page title**,
and the `--window-name` flag is a **measured no-op on Windows**.

- **(a) 4×2 grid on the primary display (recommended now).** Works with the monitors as they are
  today and needs nothing new.
- **(b) Spread across the four monitors** (e.g. three on each 2560-wide panel). I need you to place one
  window per monitor once and tell me, or accept my guess at coordinates.
- **(c) Same as (a) now, add per-window titles later.** Titles require serving a distinct `<title>` per
  window, which is a small change to the DSH frontend shell — not something I can do in your local
  install without upstreaming it.

**Recommendation: (a)** now; answer (b) only if you actually want the other three panels used.

## Q3 — Restoring a window to a *specific* session

A session is not addressable by URL. The shipped UI keeps the chosen session in browser storage
(localStorage, key `dsh.sessions.current`), keyed by origin, read once at page load — I verified this in
the installed code and on disk. Nothing in the URL selects a session, and the server serves the app only
at `/`. So today a restored window opens the app and you click the session.

- **(a) Accept it: restore the window, then click the session (recommended for now).** Zero new code,
  works today, and eight windows cost one click each after a reboot.
- **(b) I write a client-side DSH plugin** that reads a session id from the URL (or a "restore this
  session" list) and selects it on load. This is the real fix, it is development work I can do, and it
  needs the DSH client-plugin path — bigger job, and it lives in the harness rather than in this repo.
- **(c) A "window → session" ledger:** the launcher remembers which session each window was last on and
  reopens that window's app, leaving the click to you. Cheapest middle ground, but still a click.

**Recommendation: (a) now, (b) as the next real piece of work** — this is the single biggest remaining
gap in the whole multi-window experience, and it is a UI change, not an ops change.

## Q4 — What should "open a new window" be?

`dshw new` already opens the next free window against the running engine. The question is how you want
to reach it.

- **(a) A desktop shortcut + an AutoHotkey/Win key shortcut (recommended).** One double-click or one
  keypress for a new window; no extra process.
- **(b) A tray icon** with a menu (new window / restart engine / status). Always visible, but it is
  another program to keep alive and patch.
- **(c) Both.**

**Recommendation: (a)**; add (b) only if you find yourself reaching for the terminal often.

## Q5 — Scope: build it on the laptop only, or on both machines now?

The config and scripts live in `harness-config`, which is the single source of truth and syncs to both
machines. `dshw doctor` re-resolves the dsh binary, the browser and `DSH_HOME` per machine, so the same
files should work on the desktop.

- **(a) Verify on the laptop first, then on the desktop when you are at the office (recommended).** I
  cannot test the desktop from here — it is on the other network.
- **(b) Commit now and treat the desktop as verified-by-construction,** fixing whatever breaks when you
  next use it there.

**Recommendation: (a).** The only machine-specific value is the window layout, and it is one block in
`windows.json`.

## Q6 — Default window count on the laptop: eight, or twelve?

Eight are enabled in `windows.json` today; twelve rows exist and enabling four more is a one-line change
each (a ninth and tenth window only fit on this screen as extra windows on the other monitors, or on a
second desktop).

- **(a) Eight now, twelve available on demand (recommended).** Each *idle* window costs disk (~200 MB of
  browser profile) plus a Chromium renderer set; eight is what the current screen layout shows at once.
- **(b) Twelve enabled from the start.**

**Recommendation: (a).**
