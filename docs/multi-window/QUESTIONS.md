# Open questions — multi-window DSH

**How to use this file:** answer one at a time. Each question is self-contained, has options, and a
recommendation marked **(recommended)**. Answering a question moves it to `journal/DECISIONS.md` with
its reason, and the line here is marked answered. Nothing in this list blocks work that is already
underway.

Read `ANALYSIS-AND-DECISION.md` in this directory for the evidence behind each question.

Asked 2026-09-11 · ZABZ-YOGA.

---

## Q1 — How many engines: one shared process, or one process per window? — **ANSWERED 2026-09-11**

*Owner's answer, verbatim:* "what this is really about is performance... I don't specifically need different
engines and all that shared session history is better than everything having its own sessions, because I
really want to talk to you each time. I just want it to be in different windows so I could have a bunch of
different conversations happening with you. And I also want no slowdowns... Obviously, the more integrated
the windows are with each other even better."

**Decision: one shared engine, many windows — and it is also the faster choice.** Measured at 12 concurrent
windows: 72/72 calls succeeded, worst case 0.45 s, no errors, engine memory flat. One engine ~3 GB against
12 engines ~17 GB, and it is the only design that gives shared history. See `PERFORMANCE-MEASURED.md`.

---

## Q7 — Should there be a cross-window panel: one place that shows what all the sessions are doing?

You said you want the windows *more* integrated. They already share one session store, one set of agents and
one event stream, so each window can see every session. What does not exist is a single view of the fleet —
which session is working, which is waiting on you, which is stuck, and how much each has cost.

- **(a) Nothing for now — use the sidebar session list (recommended until you have used twelve windows for a
  few days).** The cheap version of integration already works. Building a panel you do not need is waste.
- **(b) A status strip in each window** showing the other windows' sessions: running, waiting, done.
- **(c) A dedicated "fleet" window** — one dashboard window listing every open session with state, model,
  token spend and last activity, and a click to jump to it. This is the shape VS Code landed on for the
  same problem (one Agent Sessions view, not twelve taskbar buttons).

**Recommendation: (a) now, then tell me after a few days whether you keep alt-tabbing to find things.** If
you do, (c) is the answer and it is a client-side plugin — the same work as question 3, so the two should be
built together.

---

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
