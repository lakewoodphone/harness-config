# Multi-window DSH — analysis, decision and ordered build

**Written:** 2026-09-11, ZABZ-YOGA. **Ask:** at least 8 independent DSH windows, robustly, on both
machines; reopen them all after a restart; one easy way to open a new window; put it in a document with
the owner's open questions at the end.

Everything below carries its evidence. Where something is inferred rather than measured it says so.

---

## 1. What "a window" actually is in DSH — this decides everything else

A DSH window is **not** a session. It is a browser client attached to a `dsh web` server process, and
**one server process already hosts many independent agent sessions** — each browser session composes its
own agent from the presets rather than sharing a process-wide tool set (`dsh-web-app` README,
"Per-session agent setup", read 2026-09-11).

So there are three separable things and the whole design is about not confusing them:

| Thing | What it is | What it costs |
|---|---|---|
| **Engine** | one `dsh web` process. Owns sessions, tools, MCP bridges, sandbox, credentials. | ~196 MB idle, ~1.4 GB with its five MCP bridges mounted (measured) |
| **Session** | one conversation + its agent, inside an engine | ~183 KB on disk; one `dsh-subprocess-local` runner (~57 MB) per concurrently running shell command |
| **Window** | one Chromium app window, in its own browser profile | a Chromium renderer set, ~200–350 MB, and its own cookie jar/localStorage |

**The number of windows is nearly free. The number of engines is what costs.**

---

## 2. The measured cost, and why it rules out "one process per window"

Measured on ZABZ-YOGA, 2026-09-11 (31.6 GB RAM, 22 logical CPUs; full method and raw output in
`docs/multi-window/research-resource-cost.md`):

| Item | Measured |
|---|---|
| idle `dsh web`, no session, no MCP | 196 MB |
| same server with its **five stdio MCP bridges** | **~1.4 GB whole tree** (26 processes) |
| each additional engine | pays that ~1.4 GB **again** — the bridges are declared per process, `agent.cordis.yml` `transport: stdio` |
| live server with 8 sessions and one person working in it | 878 MB – 961 MB (moves) |
| one runner child per concurrent shell command | 57 MB mean (n=10) |

I verified the per-engine MCP cost directly rather than trusting the extrapolation: three servers started
by `dshw` on three ports each had **26 descendants and ~1.4 GB** of tree, and the MCP bridges were
children of each server individually (measured 2026-09-11 13:1x, PIDs 23888/59480/34416).

| Topology | Cost at 8 windows | Cost at 12 windows | Failure blast radius |
|---|---|---|---|
| **8–12 engines, one per window** | ~11 GB | ~17 GB | one engine dies → one window |
| **1 engine, 8–12 windows** | ~2.7–3.1 GB (one person driving) | — | engine dies → supervisor restarts it; all windows reconnect |

The laptop has **7.7 GB free** at the time of writing (a qemu VM holds 5.3 GB). The 12-engine plan does
not fit there under any assumption. The 12-window plan fits with room to work.

→ **Decision: one engine, many windows.** A per-window engine stays available as a mode (`mode: "multi"`
in the config) but is not the default, and the reason is written into the config file itself.

---

## 3. The one real UI problem: a window cannot be restored to a session

This is the finding that shaped the build, and it is a limitation of the shipped UI, not of our setup
(`docs/multi-window/research-session-urls.md`, read from the installed bundles and verified live):

- **No session is addressable by URL.** `pushState` / `replaceState` / `popstate` / `location.hash` /
  `sessionId` occur **zero** times across all 65 installed client bundles and the shell bundle. The server
  matches pathname only and the SPA fallback serves index.html **only at `/`** — every other path 404s
  (verified live: `/some/random/path` → 404).
- The `?token=` exchange 303-redirects to literal `/` and discards every other query parameter, so a
  session parameter could not survive authentication even if a reader existed.
- Session choice lives in **`localStorage["dsh.sessions.current"]`**, keyed by **origin**
  (scheme+host+**port**), read once at page load (`dsh-api-session-controller/lib/client.js:3058`).
  Proven from disk, not just from source: the LevelDB of two `dshw` profiles contains
  `_http://127.0.0.1:3081\0dsh.sessions.current\0{"sessionId":"session-1b8e6fa7-…"}`.
- **Consequence:** two windows on the same port share that one key — last writer wins on reload. Two
  windows on **different ports** are different origins and do not interfere.

That gives the restore mechanism: **restore the window, then click the session.** Because that is
mildly annoying, it is question 3 for the owner, with three options and a recommendation.

---

## 4. What I built (in `harness-config`, so both machines get it)

`multi-window/` in the harness-config repo:

| File | What it is |
|---|---|
| `windows.json` | the single source of truth: mode, primary port, and one row per window (label, workspace, browser profile, optional size/position) |
| `dshw.ps1` | the supervisor and control command |
| `dshw.cmd` | thin wrapper so `dshw up` works from any shell |
| `selftest.json` | throwaway config used to verify the launcher end to end |

Commands: `dshw up` · `down` · `restart` · `status` · `new` · `open <slot>` · `stop <slot>` · `logs <slot>`
· `autostart on|off` · `doctor`.

Design points that are not obvious:

- **One browser profile per window** (`--user-data-dir`), which is what makes each window's cookie jar
  and its `dsh.sessions.current` **its own** — the isolation problem in §3 solved by not sharing an
  origin's storage. Measured: separate profiles ⇒ separate `Preferences` and separate Local Storage.
- **Geometry is supplied on every launch** (`--window-size`, `--window-position` per row).
  `--window-name` is a **no-op on Windows** (measured) — the window caption is the page `<title>`, so
  every window currently reads "DeepSeek Harness". Distinguishing them is question 2.
- **Servers are launched detached**, one child `pwsh` per engine that writes a readiness file naming the
  real node pid and exits, so `down` can always find and kill the right process tree. Parallel launch,
  not one-at-a-time.
- **Readiness is the `dsh web:` URL line**, not a bound port — the web app prints it only after the
  loader tree settles.
- **Auth survives a restart** because the cookie's signing secret lives in
  `$DSH_HOME/.credentials.yaml` and the cookie is valid 30 days; the supervisor stores the tokenized
  startup URL per engine so a fresh window can always complete the exchange.
- **Boot persistence:** `dshw autostart on` registers one Task Scheduler task, At-logon, "run only when
  the user is logged on" — the research is explicit that a session-0 service can hold the server but can
  never show or be reached by the user's window
  (`research-windows-multiwindow.md` §Q2, citing Microsoft's Interactive Services page).

---

## 5. Status: what is verified, and what is not

Verified by running it (evidence in the journal entry for this session):

- `dshw doctor` resolves node, the dsh bin, Edge, DSH_HOME and all three state directories.
- Starting a server on its own port with `--port` works; the URL line is parsed; the pid is recorded.
- **Two servers sharing one `DSH_HOME` boot and serve simultaneously with no lock, `-wal`, `-shm` or
  `.db` files anywhere** — concurrency control is a per-session named semaphore, so a collision is
  same-session only and fails fast with EBUSY (research-resource-cost.md step 3).

Not yet verified (and therefore not claimed): the end-to-end "8 windows open, each on its own session,
survive a logoff/logon" run, the `new` and `autostart` paths against the real config, and the shared
`settings.yaml` concurrent-write window.

---

## 6. Open questions — answered one at a time, see `QUESTIONS.md`
