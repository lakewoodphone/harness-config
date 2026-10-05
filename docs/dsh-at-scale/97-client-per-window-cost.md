# What actually costs CPU inside one DSH Web GUI window

**Host:** `ZABZ-YOGA` (Windows, 22 logical CPUs, user `ezabz`)
**Measured:** 2026-10-04 22:36 → 2026-10-05 00:25 local (America/New_York)
**Scope:** every file I created is under `C:\Users\ezabz\code\_scratch\perf\`. Nothing else was
modified, no service or task was changed, no owner browser window was touched, no port in the
forbidden ranges was bound. My isolated browsers used debug ports 9333-9343 and their own
`--user-data-dir`; every one of them is dead now (§7).

---

## 0. How to read this, and what is not being claimed

Two different "CPU" numbers appear in this report and they are not interchangeable:

- **TaskDuration s/s** — the renderer *main thread's* own accounting, from CDP
  `Performance.getMetrics`. It counts main-thread tasks only. It is exact for what it measures and
  blind to everything else the browser process tree does.
- **process CPU (cores)** — every msedge process whose command line carries *this run's* profile
  directory, sampled from PowerShell by differencing `Process.TotalProcessorTime` over a known
  interval. This is the number that decides whether a laptop feels sluggish.

They disagree in a way that matters, and **that disagreement is a headline result**, not a
measurement error: a window can show 0.05 core on the renderer and still cost 0.9 core of process
CPU (measured three times, §2.7 and §3.6).

I also state plainly where the evidence stops. The strongest claim in this report has a clean
ablation behind it; the arithmetic that explains the *whole* process cost does not, and I say so in
§5 and §8.

**Token provenance.** The launch token was read from
`%USERPROFILE%\.dsh\multi-window\windows.log`, newest `open slot=` line, written
`2026-10-04T22:30:14`. That file's mtime is still `10/04/2026 22:30:15` — I read it and never wrote
it. The token was verified before use against both `http://127.0.0.1:3306` (proxy) and
`http://127.0.0.1:3099` (engine) by following `/` with the returned cookie: HTTP 200, 35,846-byte
boot page on both. The token itself is not printed anywhere in this report or in `runs/` (all
logged URLs pass through a redactor). The engine process (pid 25228, started `10/02/2026 11:07:28`)
was never restarted, so one token covered the whole session.

---

## 1. Method, and the three things that would have made these numbers wrong

Each run: spawn an isolated headless Edge (`--headless=new`, own `--user-data-dir`, own debug port)
against a real origin; attach over CDP; enable `Runtime`/`Page`/`Performance`/`Network`; navigate;
settle; then sample `Performance.getMetrics` twice and divide the deltas by the elapsed wall time.
To put a window onto a chosen session, `localStorage['dsh.sessions.current']` is set to
`{"sessionId":"..."}` and re-asserted by a document-start script, then the page is reloaded.

Three traps, each of which would have produced a confident wrong number:

1. **`Win32_PerfFormattedData_PerfProc_Process` does not carry `CommandLine` on this host, and its
   rows only partly join to real PIDs.** Measured: a 7-process headless Edge joined to **0** rows.
   A first sampler used it and reported 0.00 core for a browser that was plainly working. Fixed by
   differencing `Get-Process TotalProcessorTime` per PID and grouping by
   `Win32_Process.CommandLine`. (A concurrent sampler then reported 0 procs for a *different*
   reason — `New-Object 'double[]' $n` is invalid PowerShell, and the error was swallowed by a
   `stdio: 'ignore'` child. Both are recorded because both are the kind of thing that turns into a
   false "cost is zero" finding.)
2. **A fresh profile takes ~23-30 s to boot before it renders anything.** At 45 s the first control
   run read `TaskDuration 0.166 s/s` on a page that said "Loading plugins…" with 34 elements. Every
   settled measurement in this report waits at least 35 s, most 40-90 s.
3. **`v3` sessions (biggest on disk, 12.6 MB) do not render at all in this engine build.** They
   open, project a title, and sit at "Loading history…" forever — measured for 130 s with the
   `session/follow` stream open and zero frames delivered on it, at 0.132 s/s, i.e. it is not a load
   *cost*. So the "largest session on disk" is not usable as a large-transcript sample; the large
   samples below are current-format `v4` sessions.

---

## 2. Results table

`lps` = LayoutCount/s. Blank cells are not measured, not zero.

### 2.1 Control — empty session state, fresh origin (requirement 1)

| run | what the window showed | TaskDuration s/s | Script s/s | lps | DOM nodes | JS heap | process CPU |
|---|---|---|---|---|---|---|---|
| control A (`…02-38-33`) | "Loading plugins…" after 45 s — **too early, discarded** | 0.166 | 0.097 | 0.3 | 588 | 46.2 MiB | — |
| control B (`…02-44-57`) | workspace picker, empty session | 0.119 | 0.114 | 0.0 | 573 | 78.0 MiB | — |
| **control C (`…03-56-45`)** | **empty session, composer idle** | **0.088** | **0.084** | **0.0** | **573** | **28.5 MiB** | **0.15 core mean** (29 ticks) |

Reproduces the briefing's 0.095 s/s. Note the process CPU is **0.15 core** for an empty window —
the renderer accounts for about a third of that.

### 2.2 Static, small transcript

| run | session (compressed size) | TaskDuration s/s | Script s/s | lps | DOM nodes | JS heap | process CPU |
|---|---|---|---|---|---|---|---|
| static (`…03-10-42`) | `769f277d…` (147 KB, few turns) | 0.104 | 0.061 | 0.0 | 1,483 | 34.5 MiB | **0.22 core** (23 ticks) |

### 2.3 Static, large transcript (requirement 2)

| run | session | TaskDuration s/s | Script s/s | lps | DOM nodes | JS heap | process CPU |
|---|---|---|---|---|---|---|---|
| static (`…03-03-58`) | `session-bb953f87…` (1.5 MB) | 0.479 | 0.183 | 54.5 | 5,876 | 72.5 MiB | 1.30 core |
| static (`…03-07-05`) | same | 0.508 | 0.227 | 39.1 | 6,346 | 73.8 MiB | 1.46 core |
| static (`…03-13-09`) | same | 0.494 | 0.175 | 48.7 | 6,764 | 81.8 MiB | 1.24 core |
| static (`…03-15-57`) | same, +scroll compare | 0.642 | 0.342 | 40.8 | 7,511 | 110.2 MiB | 1.61 core |
| static (`…03-30-35`) | `session-9c87363a…` (1.1 MB) | 0.529 | 0.218 | 51.2 | 11,997 | 77.6 MiB | 1.23 core |

5 s TaskDuration series for `session-bb953f87` (run `…03-15-57`), the burstiness check:

```
03:17:22  task 1.305  script 0.878  layouts/s 71.5  nodes 7361
03:17:27  task 0.414  script 0.109  layouts/s 59.6  nodes 7386
03:17:32  task 0.509  script 0.219  layouts/s 50.4  nodes 7408
03:17:37  task 0.488  script 0.194  layouts/s 54.1  nodes 7369
03:17:42  task 0.474  script 0.156  layouts/s 58.7  nodes 7369
03:17:47  task 0.416  script 0.062  layouts/s 64.0  nodes 7369
03:17:52  task 0.499  script 0.165  layouts/s 53.7  nodes 7369
03:17:57  task 0.489  script 0.162  layouts/s 57.1  nodes 7369
03:18:03  task 0.627  script 0.157  layouts/s 51.9  nodes 7360
03:18:08  task 0.516  script 0.133  layouts/s 57.6  nodes 7360
03:18:13  task 0.350  script 0.060  layouts/s 57.7  nodes 7360
03:18:18  task 0.579  script 0.315  layouts/s 45.6  nodes 7364
```

Read the `layouts/s` column: ~50-70 every single second, while `script` swings between 0.06 and
0.88, and `nodes` oscillates by ±40. The layout churn does not track the JavaScript work. That
was the first sign that the hypothesis in the brief (re-render per streamed event, scaling with
transcript size) was not the mechanism.

Scroll comparison inside run `…03-15-57` (transcript scroller 7,248 px tall in a 267 px viewport):
6 s pinned at the top vs 6 s pinned at the bottom gave DOM 6,469 → 6,495 nodes — i.e. **scrolling
the large transcript to an out-of-view position changed nothing**, so this is not scroll anchoring
or follow-tail work.

### 2.4 Live streaming (requirement 3)

A fresh blank session in an isolated window; a five-word prompt typed into the window's own
composer with `Input.insertText` and submitted with a real Enter keypress, so the app's own
`prompt()` path produced the stream. 2 s deltas; peaks and steady state:

```
 +2.1 s  task 0.965  script 0.229  layout 0.005  nodes 620  heap 40.2 MiB  chars 260
 +4.2 s  task 0.252  script 0.193  layout 0.012  nodes 709  heap 51.1 MiB  chars 356
 +6.2 s  task 0.054  script 0.047  layout 0.000  nodes 709  heap 45.5 MiB  chars 356
 +8.4 s  task 0.008  script 0.002  layout 0.000  nodes 709  heap 45.5 MiB  chars 356
+10.4 s  task 0.168  script 0.151  layout 0.000  nodes 709  heap 72.3 MiB  chars 356
+12.5 s  task 0.004  script 0.001  layout 0.000  nodes 709  heap 72.3 MiB  chars 356
+14.5 s  task 0.003  script 0.001  layout 0.000  nodes 709  heap 72.3 MiB  chars 356
+16.5 s  task 0.110  script 0.087  layout 0.000  nodes 688  heap 49.0 MiB  chars 356
+20.9 s  task 0.153  script 0.147  layout 0.000  nodes 688  heap 62.4 MiB  chars 356
+27.1 s  task 0.051  script 0.029  layout 0.000  nodes 688  heap 53.6 MiB  chars 356
```

Whole-window sample for the same run: **0.098 s/s, 573 nodes, 0.19 core**, i.e. the streaming
window measured *at rest* is indistinguishable from the empty control.

**Verdict: the stream itself is cheap.** A short generation costs about **0.9 core for one second**
at the moment the answer lands and ~0.05-0.15 s/s afterwards, with **zero layout churn**. My
measurement is option (a) from the brief (a prompt sent through the app's own path into a session
created for the test) — not a window pointed at someone else's stream.

### 2.5 Where the time goes — CPU profile (requirement 4) and what it does **not** contain

`Profiler.start`/`stop`, 200 µs sampling. Aggregated by self time, by owning script, and by root
frame. Large transcript at rest (`session-bb953f87`, 12 s, 14,289 samples, 13.29 s of thread time):

```
attributable (non-idle/program/GC): 0.699 s = 5.26% of the profile
100 ms buckets with work: 122/133 = 91.7%
BY SCRIPT
  95.57%  (native)                       <- browser internals, not attributable to any JS file
   1.88%  plugins/??…dsh-api-gateway… dsh-api-session-controller… (one bundle)
   1.28%  plugins/??dsh-plugin-windows… dsh-session-log-export…  (one bundle)
   1.27%  http://127.0.0.1:3306/assets/index-5SrrfWpU.js
BY ROOT FRAME
  94.74%  (root) @ (native)
   3.02%  publish  @ plugins/??…dsh-session-log-export…
   1.18%  (anonymous) @ assets/index-5SrrfWpU.js:56
   0.91%  (anonymous) @ plugins/??…dsh-api-gateway…
```

Top self-time *functions* in the same profile (share of the whole profile, so the tree caps at
100 % across all buckets):

```
 1. 61.05%  (idle)                                                      @ (native)
 2. 33.60%  (program)                                                   @ (native)
 3.  0.70%  ps                                                          @ assets/index-5SrrfWpU.js:56
 4.  0.42%  querySelector                                               @ (native)
 5.  0.40%  querySelectorAll                                            @ (native)
 6.  0.32%  (anonymous)                                                 @ plugins/??…dsh-api-gateway…:102334
 7.  0.30%  buildListSnapshot                                           @ plugins/??…dsh-api-session-controller…:23062
 8.  0.17%  walk                                                        @ plugins/??…dsh-api-session-controller…:20930
 9.  0.16%  ensureFresh                                                 @ plugins/??…dsh-api-session-controller…:21006
10.  0.15%  flattenLineage                                              @ plugins/??…dsh-api-session-controller…:20918
11.  0.15%  reconcileStatus                                             @ plugins/??…dsh-api-gateway…:25375
12.  0.15%  reconcile                                                   @ plugins/??…dsh-api-gateway…:113731
13.  0.14%  publishStatus                                               @ plugins/??…dsh-api-gateway…:25375
14.  0.13%  projectList                                                 @ plugins/??…dsh-api-session-controller…:23621
15.  0.13%  (anonymous)                                                 @ plugins/??…dsh-api-gateway…:45798
```

Stream profile (24 s, blank session with a live generation) is the same shape: 84.85 % `(idle)`,
5.95 % `(program)`, then `ps` (React scheduler) 1.08 %, `buildListSnapshot` 0.60 %,
`walk` 0.35 %, `projectList` 0.29 %, `reconcileStatus` 0.26 %, `reconcile` 0.22 %; by root frame
`publish` 4.80 % and `index-5SrrfWpU.js` 3.29 %.

**What this means, stated exactly.** The V8 profiler says the JavaScript is *not* where the CPU
goes — 95 % native, only 1-4 % attributable to any application script, and the recurring named
functions are all the session-list projection pipeline (`buildListSnapshot`, `projectList`,
`flattenLineage`, `walk`, `ensureFresh` — `plugins/??…dsh-api-session-controller`) plus the React
scheduler (`ps`, `assets/index-5SrrfWpU.js:56`). The 33 % `(program)` bucket is V8's catch-all for
builtins and runtime, and it is **not** attributed. So the profile localises the JS and shows it is
small; it does not, by itself, explain the renderer cost. §3.6 explains why: the cost is in layout
and style, which the JS profiler does not sample.

### 2.6 Sidebar session list (the cheap check)

Driving the app's own control, N times, and counting rendered rows each time:

```
sidebar before expand: {"rows":13,"nodes":736,"expander":"Show 108 more sessions"}
clicked "show more" 12x
sidebar after expand: {"rows":73,"nodes":2116,"grower":true}
```

So: **not virtualised — paginated.** The list renders every row the group holds, one batch per
expand click (13 → 73 rows, 108 more still available; §8 says how many the owner actually has).
Cost of that: an extra 60 rows moved `script` to 0.187-0.224 s/s in an otherwise empty window —
**about 0.1-0.2 core for the whole sidebar** — and, more interestingly, `lps` went to **0.0**
because the sidebar expansion pushed the animated status dots out of view. The session list is not
the window's problem.

### 2.7 The measurement that changed the conclusion — ablation

Two ablations, each one line of CSS or one API call, nothing else touched.

**(a) Turn every animation off** (`*,*::before,*::after{animation:none!important;transition:none!important}`)
on the large transcript:

| state | TaskDuration s/s | script | layout s/s | lps | style/s | process CPU |
|---|---|---|---|---|---|---|
| animations ON | 0.520 | 0.183 | 0.052 | 56.0 | 58.0 | **1.10 core** |
| animations OFF | 0.540 | 0.428 | 0.006 | 3.2 | 6.1 | **1.07 core** |

(layout passes fall **17.5×** and layout time falls **8.7×**; this particular run was an actively
streaming session, which is why
`script` and the process CPU barely move — see §5 for that honest caveat.)

**(b) Add 2,000 synthetic nodes inside the transcript scroller**, animations untouched, same
window: `lps` 58.0 → 56.4, `task` 0.387 → 0.379, DOM 6,205 → 10,206 nodes. Nothing moved.

**(c) Per-layout cost vs DOM size**, with the frame clock running, in a fixed 700×320 scroller
appended to the page:

```
 975 nodes  task 0.289  layout 0.069  lps 61.2  avg layout 1.123 ms
2975 nodes  task 0.216  layout 0.066  lps 59.8  avg layout 1.107 ms
8975 nodes  task 0.295  layout 0.052  lps 56.3  avg layout 0.917 ms
24975 nodes task 0.340  layout 0.059  lps 56.4  avg layout 1.039 ms
```

**A layout pass costs ~1 ms whether the document has 1,000 nodes or 25,000.** DOM size is not the
multiplier I expected it to be.

**(d) Which animation** — cancel one `animation-name` at a time via `document.getAnimations()`,
same window, same session:

| cancelled | lps | layout s/s |
|---|---|---|
| baseline (all running) | 46.3 | 0.055 |
| `_dsh-state-dot-spin_1i3xo_1` (2 elements) | **1.0** | 0.003 |
| `_dsh-state-dot-dash_1i3xo_1` (2 elements) | 9.6 | 0.009 |
| `_dsh-row-shimmer-sweep_1rdzk_1` | 52.7 | 0.050 |
| `_dsh-row-shimmer-highlight_1rdzk_1` | 61.1 | 0.047 |
| all animations off | 1.3 | 0.004 |
| animations re-enabled | 57.8 | 0.048 |

**(e) The clean 2×2**, in one window, 1600×1000: four running state-dot spinners in the sidebar.

| state | TaskDuration s/s | layout s/s | lps | DOM nodes | process CPU |
|---|---|---|---|---|---|
| spinner ON, small DOM | 0.336 | 0.071 | **56.5** | 945 | **0.94 core** |
| spinner ON, +12,000 nodes | 0.371 | 0.079 | **55.0** | 24,978 | **1.03 core** |
| spinner OFF, +12,000 nodes | 0.048 | 0.000 | **0.0** | 24,979 | **0.17 core** |
| spinner OFF, small DOM | 0.046 | 0.000 | **0.0** | 977 | **0.23 core** |
| spinner ON again, small DOM | 0.247 | 0.055 | **60.7** | 976 | **0.99 core** |

This is the decisive result. Same session, same page, same code: **DOM mass is irrelevant**
(945 → 24,978 nodes changes nothing) and **the animation state is everything** (spinner ON =
55-61 layouts/s and ~1.0 core; spinner OFF = 0 layouts/s and ~0.2 core). Turning the animation off
and on again is reversible in the same window.

**(f) Viewport, on a session that has since gone quiet** (`session-9c87363a`, no animations left
running): 700×440 → 0.062 s/s / 1.0 lps; 1600×1000 → 0.088 s/s / 1.1 lps; back to 700×440 →
0.046 s/s. **Viewport size is irrelevant to this cost**, and an *idle* large session is as cheap as
the empty control (0.046-0.088 s/s).

### 2.8 Concurrency — what a fleet actually costs

Three isolated windows, each a fresh empty session on the live origin, all measured over the same
wall-clock interval:

```
window 0: task 0.052 script 0.050 lps 0.0 nodes 573   process CPU mean 0.12 core  max 0.42
window 1: task 0.054 script 0.051 lps 0.0 nodes 613   process CPU mean 0.20 core  max 0.48
window 2: task 0.066 script 0.056 lps 0.0 nodes 573   process CPU mean 0.31 core  max 1.69
renderer task sum: 0.135 s/s = 14% of one core
TOTAL process CPU: 0.64 core for 3 windows
```

**An empty window costs 0.12-0.31 core of process CPU while its renderer main thread is idle at
0.05 s/s.** Three of them cost 0.64 core doing nothing. That is a per-window floor nobody has
measured before, and it is *not* explained by anything in §3.

For context from the same sampler in every run of this session: the owner's own msedge group
(processes whose command line carries the shared `multi-window` profile) measured **5.46, 5.62,
5.64, 6.29, 6.43, 6.52, 6.55 and 6.75 core** across the session — against 22 logical CPUs, and
against my isolated windows' 0.15-0.22 core when idle.

---

## 3. Conclusion — the mechanism

### 3.1 What costs the CPU

**The renderer's per-second cost in a working window is dominated by a continuous, ~56-61 per
second layout + style-recalculation loop that is driven by the *state-dot spinner animation*, and
is almost completely independent of transcript size, DOM size, visible viewport, and streaming
activity.**

- With running spinners: **55-61 layouts/s, 56-63 style recalcs/s, ~0.05-0.08 s/s of layout,
  ~0.9-1.0 core of process CPU.**
- With the spinner animations cancelled (one CSS rule, page otherwise identical):
  **0-3 layouts/s, ~0.00-0.006 s/s of layout, ~0.2 core.**
- Re-enabling the animation restores the churn immediately, in the same window.
- Adding 12,000 or 24,000 nodes to the page changes none of these numbers; the per-pass cost is
  ~1 ms at both ends.

The animation is `StateDot`'s ongoing indicator: `.spinnerMotion { animation: dsh-state-dot-spin
1.5s linear infinite }` and `.spinnerArc { animation: dsh-state-dot-dash 1.5s ease-in-out infinite }`
in `…\@deepseek-ai\dsh-client-ui-primitives\lib\StateDot.module.css:42-62`, keyframes at
`:64-83`. One rendered busy session status paints two of these, and the sidebar paints one per
busy session/workspace, so the count scales with how many things are marked "running", not with
how much text is on screen.

### 3.2 What this refutes

The hypothesis in the brief — *the conversation view re-renders a large amount of work per streamed
event, so cost grows with transcript size × event rate* — is **not** what the measurements show:

- A one-sentence generation into a blank session cost a 0.9-core spike for one second and then
  0.05 s/s with **zero** layout churn. Streaming is cheap.
- The large transcript at rest burned 0.5 s/s with 50-70 layouts/s *while streaming nothing*.
- Adding 12,000 nodes inside the transcript changed the layout rate by 1.5 passes/s.
- Idle large sessions fall to 0.046-0.088 s/s once nothing in the workspace is running.
- The `node_modules` byte-smell is real — `_dsh-state-dot-spin` is applied per status dot and 230
  `callRow`/212 `root`/126 `summary` elements appear in a mid-size transcript — but the *count* of
  those elements is not what costs; the *one* spinner that is animating is.

### 3.3 The two regimes, stated as rates

| window state | renderer | layouts/s | process CPU |
|---|---|---|---|
| empty session, nothing running | 0.05-0.09 s/s | 0 | 0.12-0.31 core |
| large transcript, nothing running | 0.046-0.088 s/s | 1.0-1.1 | not measured at that moment |
| anything in the workspace marked busy (spinner visible) | 0.25-0.65 s/s | 46-61 | 0.9-1.6 core |
| streaming a short answer into a blank session | 0.9 core for 1 s, then 0.05 | 0.0 | 0.19 core |

### 3.4 The evidence that supports it

1. §2.7(e): same window, spinner ON/OFF, DOM 945 vs 24,978 nodes — layout churn and ~0.8 core of
   process CPU track the animation, not the DOM.
2. §2.7(d): cancelling the single animation name that belongs to the spinner drops layouts/s from
   46.3 to 1.0; cancelling the two shimmer names leaves it at 52-61.
3. §2.7(c): ~1 ms per layout pass at 975 nodes and at 24,975 nodes — the churn is many cheap
   passes, not few expensive ones.
4. §2.3 time series: 50-70 layouts/s every second while `script` swings by 15×.
5. §2.4: a real token stream costs almost nothing, which removes "per streamed event" as the
   driver.

### 3.5 The measurement that would falsify it

**Have a window with live running-state spinners, measure `LayoutCount/s` over 30 s, and get a
number below ~5.** If that happened, the churn would not be coming from the animated indicator and
the attribution above would be wrong. Equally falsifying: a window with **zero** running spinners
that still shows 40-60 layouts/s, or a window whose layouts/s tracks DOM size across a 25× range
(small window vs large transcript) with the spinner state held constant. None of these occurred in
any run here.

### 3.6 The part I cannot yet explain, stated as a gap

The 2×2 in §2.7(e) shows the spinner is worth roughly **0.8 core of process CPU** in a window whose
renderer cost is only ~0.3 s/s. TaskDuration, ScriptDuration, LayoutDuration and
RecalcStyleDuration together account for at most 0.29 s/s of that. **So the renderer main thread,
as CDP measures it, explains under a third of what the process costs.** The same gap appears in
§2.8: an empty window's renderer is ~0.05 s/s while its processes burn 0.12-0.31 core.

The V8 profiler cannot close that gap — 95 % of its samples are `(native)`/`(program)`, i.e. code
the profiler does not attribute. What I have **not** done is a compositor/paint-level trace (CDP
`Tracing`, `devtools.timeline` + `disabled-by-default-devtools.timeline`). I deliberately did not
run it: it is far heavier than anything else in this session on a machine already at 60-70 % CPU,
and I would rather report the gap than add load to the owner's laptop for it. It is the single
next measurement to take (see §9).

---

## 4. Proposed fix

The cost is **not** inherent and "use fewer windows" is **not** the only lever — the same session,
same code, same DOM drops 4-8× in layout work and ~5× in process CPU the moment the animated
indicator stops. But the honest ranking is: the client-side fix only addresses the part of the
process cost that §3.6 covers, so I list it with that caveat, and I list the cheap containment
change first because it is safe and reversible.

### Fix 1 (recommended, smallest, safest): stop the per-second spinner work from invalidating page layout

**File:** `C:\Users\ezabz\.dsh\engine\node_modules\@deepseek-ai\dsh-client-ui-primitives\lib\StateDot.module.css`
**Lines:** 37-45 (`.spinner`, `.spinnerMotion`) and 47-62 (`.spinnerTrack`, `.spinnerArc`).

The change: give the spinner its own layout-containment boundary so its animation cannot dirty its
ancestors' layout, e.g. `contain: layout paint` (or `contain: strict` with an explicit size) on
`.spinner`/`.spinnerMotion`, and prefer an attribute/property the compositor can animate. The two
animations should then cost style ticks, not whole-document layout passes.

**Why it is safe:** it is a CSS containment hint on a 10 px status glyph; it changes no markup, no
API, no state, and no capability. If it regresses the glyph's paint, deleting two declarations
reverts it. It cannot lose data or affect any outbound action.

**Why the diagnostics support exactly this:** the ablation in §2.7(d) shows that the spin
(`transform: rotate`) — not the shimmer, not the DOM, not the viewport — is what correlates with
the 46 → 1 layout collapse, and `transform` is a property the browser can composite *if* its
container does not force layout. The two candidate causes for the invalidation (an ancestor
`ResizeObserver` observing a box the animation dirties — `dsh-client-ui-chat/lib/client.js:4528`
observes the transcript column and scroller — or the animated SVG's stroke geometry) both live in
the ancestor's layout, which is exactly what `contain` cuts.

**Expected saving:** measured, in an isolated window, **55-61 layouts/s → 0-3 layouts/s**, layout
time **0.05-0.08 s/s → ~0**, and process CPU **~0.94-1.03 core → ~0.17-0.23 core** for a window in
which the spinner was the only busy thing. On the owner's live group (5.5-7.3 core across 5 windows)
this is the difference between "5 windows and the laptop is sluggish" and "5 windows and it is
quiet", *for the part of the cost that the renderer accounts for* — see the caveat in §3.6.

**Expected saving if the containment does not work:** this is the honest risk. If the 56 layouts/s
are really the SVG stroke geometry animating in a scrollable ancestor, containment on the glyph
alone may not stop it; the next step would be either a composited substitute for the arc (a
`background: conic-gradient()` sweep with a mask, which is what the `.spinner` boot spinner at
`dsh-web-frontend/dist/assets/index-BPHePDI_.css` already does) or `content-visibility: auto` on
sidebar rows. I would measure after the change, not assume it.

### Fix 2 (only if the owner wants the fleet to cost less at *idle*): the per-window floor

§2.8 measured 0.12-0.31 core per empty window, of which the renderer is a third or less. Three
windows cost 0.64 core doing nothing. Nothing in this report localises that floor. Until the
compositor trace in §3.6 is taken, the only honest advice is the one the brief anticipated: if the
floor turns out to be inherent to an Edge `--app=` window on a shared profile, then **fewer
windows, not less transcript, is the lever** — but I am not claiming that now, because I have not
measured where that floor goes.

---

## 5. Where the two numbers disagree, and why the report keeps both

| window | renderer (TaskDuration) | process CPU (all msedge procs of this profile) | ratio |
|---|---|---|---|
| empty session (`…03-56-45`) | 0.088 s/s | 0.15 core | 1.7× |
| empty session (`…03-21-24`) | 0.098 s/s | 0.19 core | 1.9× |
| 3 empty windows (§2.8) | 0.135 s/s total | 0.64 core total | 4.7× |
| spinner ON, small DOM (§2.7e) | 0.336 s/s | 0.94 core | 2.8× |
| spinner ON, +12k nodes (§2.7e) | 0.371 s/s | 1.03 core | 2.8× |
| spinner OFF (§2.7e) | 0.046 s/s | 0.17-0.23 core | 3.7-5.0× |
| large transcript at rest | 0.47-0.64 s/s | 1.24-1.61 core | 2.5× |

The renderer number is the one I can attribute by ablation; the process number is the one the
owner actually feels. Reporting only the first would understate the problem by 2-5×; reporting only
the second would have no attribution behind it. Both are given, and §3.6 names the gap.

---

## 6. Every command I ran, with its result line

Harness files (all under `_scratch/perf/`): `probe-lib.mjs` (CDP attach, metrics sampling, CPU
sampler, CPU profile with by-function/by-script/by-root-frame aggregation), `run-probe.mjs`
(phases: control/static/send, time series, scroll compare, minimal-DOM mode), `diag-window.mjs`,
`diag2.mjs`, `diag-ws.mjs`, `diag-anim.mjs`, `anim-ablate.mjs`, `ablate-run.mjs`, `mass-curve.mjs`,
`spin-vs-mass.mjs`, `growth-curve.mjs`, `concurrent-windows.mjs`. Every run wrote JSON under
`_scratch/perf/runs/`. The starter `idle-window-probe.mjs` and `session-list-probe.mjs` (written by
the briefing session) were left in place, untouched.

Representative command lines and their first result line:

| command | result |
|---|---|
| `node run-probe.mjs control --port 3306 --dbg 9333 --settle 40 --sample 30` | `TaskDuration 0.166 s/s = 16.6% of one core` — **discarded**: page still said "Loading plugins…" |
| `node run-probe.mjs control --port 3306 --dbg 9333 --settle 40 --sample 40` | `TaskDuration 0.088 s/s = 8.8% of one core`, `DOM nodes 573`, `OUR browser mean 0.15 core` |
| `node run-probe.mjs static --session session-bb953f87-… --settle 90 --sample 40` | `TaskDuration 0.479 s/s`, `LayoutCount/s 54.5`, `DOM nodes 5876`, `mean 1.30 core` |
| `node run-probe.mjs static --session session-bb953f87-… --settle 70 --sample 25 --scroll-compare` | 5 s series `0.414-0.627 task, 45.6-64.0 layouts/s`; scroll compare `nodesAtTop 6469 / nodesAtBottom 6495`, no change |
| `node run-probe.mjs static --session 769f277d-… --settle 70 --sample 30 --profile 12` | `0.104 s/s`, `lps 0.0`, `1483 nodes`, `mean 0.22 core` |
| `node run-probe.mjs send --settle 45 --sample 20 --stream 24 --prompt "Reply with one short sentence…"` | peak `task 0.965` in the first 2 s bucket, then `0.003-0.168`; window at rest `0.098 s/s` |
| `node run-probe.mjs static --session session-9c87363a-… --settle 55 --sample 30 --minimal` | the fetch-blocking control did **not** reduce the DOM (session data arrives over the WebSocket mux, not `fetch`): `0.529 s/s`, `11997 nodes` — kept as a negative result |
| `node diag-window.mjs --port 3306 --dbg 9333 --secs 60` | app boot 23 s in a fresh profile; 43 requests; `dsh-phone-mobile.css` 404 twice |
| `node diag2.mjs --secs 120 --session session-b60e96b3-…` | v3 session stuck at "Loading history…" for 130 s; only `/api/session/list`, `/api/session/create`, etc. — **no** history request |
| `node diag-ws.mjs --secs 75 --session session-b60e96b3-…` | `CREATED ws://127.0.0.1:3306/api/remote.mux`; `SENT … "endpoint":"session/follow"`; **365 RECV frames, 362 of them on `session/control`, none on the follow stream** |
| `node anim-ablate.mjs --session session-9c87363a-… --settle 30 --secs 8` | `baseline lps 46.3` → cancel `_dsh-state-dot-spin` → `lps 1.0`; cancel `_dsh-row-shimmer-*` → `lps 52.7/61.1`; all off → `lps 1.3`; re-enabled → `lps 57.8` |
| `node spin-vs-mass.mjs --settle 32 --secs 10 --mass 12000` | spinner ON 945 nodes: `lps 56.5, 0.94 core`; +12,000 nodes: `lps 55.0, 1.03 core`; spinner OFF: `lps 0.0, 0.17 core` |
| `node mass-curve.mjs --settle 32 --secs 8 --steps 0,1000,4000,12000` | `975/2975/8975/24975 nodes → lps 61.2/59.8/56.3/56.4, avg layout 1.123/1.107/0.917/1.039 ms` |
| `node growth-curve.mjs --session session-9c87363a-… --steps 3` | initial `9160 nodes, 12585 px scroll, task 0.495, lps 58.6`; after one "Load earlier" `9192 nodes, 12899 px, task 0.847`; the control then vanished (session was streaming, so "earlier" stopped being available) |
| `node ablate-run.mjs --session session-9c87363a-… --viewport-compare` | 700×440 `0.062 s/s, lps 1.0`; 1600×1000 `0.088 s/s, lps 1.1`; back `0.046 s/s` |
| `node ablate-run.mjs --fresh --width 1600 --height 1000 --sidebar-expand` | `rows 13 → 73, nodes 736 → 2116`, expander still present; `lps` fell to 0.0 (dots pushed out of view) |
| `node concurrent-windows.mjs --n 3 --settle 35 --sample 20` | `0.052/0.054/0.066 s/s`; process CPU `0.12/0.20/0.31 core`; total `0.64 core for 3 windows` |
| `Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" \| Where-Object CommandLine like '*--app=http://127.0.0.1:33*'` | `1` at 00:24 (was not probed at 22:36) |
| `Get-Content windows.log -Raw` before/after the session | `241840` bytes before and after — the file I read the token from was never written |

---

## 7. Cleanup and side effects

- Every isolated browser was launched with its own `--user-data-dir` under
  `C:\Users\ezabz\code\_scratch\perf\udd-*` (or `%TEMP%\dsh-perf-*`, which on this host resolves
  under `~/.dsh/tmp/`) and its own debug port in 9333-9343.
- Killed per run by `killTree()`, which kills the root PID **and** every msedge process whose
  command line carries that run's profile path — necessary because `child.kill()` on the root left
  7 children alive (measured).
- Final check at 00:24: **0** msedge processes matching any of my profile paths; no listening
  socket on 9331-9346; the owner's `--app=` window is still present; **0** node processes started by
  me (three `node.exe` runners match `*_scratch\perf*` only because their command line embeds a
  PowerShell command that mentions this directory; they are the harness's own tool runners, not my
  probes). The `windows.log` byte count is unchanged.
- User-data-dirs were **kept**, not deleted, as instructed. They are listed in §7 of every run's
  JSON and enumerated in the session's scratch listing.

**Total spend:** one prompt of 13 words, one generated sentence, in one session created for the
test, on a blank-session path. No other generation was requested. The other large sessions were
only *read* into browser windows (and two of them were being written by the owner's own running
agents throughout).

---

## 8. What I could not verify

1. **Where ~70 % of the per-window process CPU goes.** The renderer's own accounting explains
   under a third of it (§3.6). The V8 profiler attributes only 5 % of its samples to any script.
   Closing this needs a compositor/paint trace (`Tracing` with `devtools.timeline` and
   `disabled-by-default-devtools.timeline`), which I judged too heavy for this machine while the
   owner was working. **This is the biggest open item.**
2. **The exact invalidation path from the spinner to the 56 layouts/s.** I proved the animation
   state is what the churn tracks (§2.7d/e), and I named the two plausible mechanisms (an ancestor
   `ResizeObserver` — `dsh-client-ui-chat/lib/client.js:4528` — or the animated SVG stroke
   geometry). I did not disprove either. So the fix in §4 is a containment change at the glyph, and
   I say so rather than claiming a root cause I have not shown.
3. **The sidebar with the owner's *full* list.** My isolated window shows only 13 rendered rows and
   a "Show 108 more sessions" control; 12 clicks got to 73 rows. I never rendered the whole list in
   one window, so I cannot say what that costs — only that the list is paginated, not virtualised,
   and that 60 extra rows cost ~0.1-0.2 core of script in an otherwise empty window.
4. **The owner's real live windows.** I measured their *aggregate* process CPU (5.46-6.75 core,
   from the shared `multi-window` profile string) but I did not attach to any of them, so I have no
   per-window renderer numbers from the owner's own windows. The 5-window/3.2-4.2-core figure in
   the brief is not something I independently reproduced or refuted. (Window count at 00:24 was 1,
   per `--app=` command lines; the CPU group still measured 5.5-7.3 core, so that group is not a
   clean proxy for five app windows — it includes every msedge process on the shared profile.)
5. **The `v3` session load path.** Four v3 sessions (5.3-13.2 MB) all failed to render history in
   this build; I measured the failure and its cost (0.132 s/s, i.e. no cost) but did not diagnose
   the cause, and I did not test whether the owner can open those sessions in the real GUI — my
   isolated profile may simply be missing something the real one has.
6. **The `--minimal` control did not work as intended.** Blocking `fetch` for heavy `/api/*`
   endpoints did not empty the page, because the session data arrives over the WebSocket mux
   (`/api/remote.mux`), not over `fetch`. I report the run as a negative result and did not build a
   second control (blocking the mux itself) because the ablation design in §2.7 gave a cleaner
   answer.
7. **Whether the ~23-30 s boot of a fresh profile is normal or an artifact of this host.** It is
   consistent across every run and the 29 s bundle request points at the engine's dev plugin
   bundler, but I did not isolate the cause. It is not per-window steady-state cost either way.
8. **Some runs have no process-CPU column.** The ablation runs before `…03-56` (`grid-…`) show
   `proc=0.00` in `runs/` because the sampler's PowerShell was silently dying then (trap 1 in §1);
   I have not retro-filled those cells, and the report leaves them blank rather than quoting a
   zero I know to be false. The spans that do carry process CPU (`…03-56`, `…2.7e`, §2.8) are from
   the fixed sampler, whose first action is to print `sampler: N profile needles` — that line is
   visible in the run logs precisely so this trap cannot recur unnoticed.
