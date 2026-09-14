# Does one engine slow down with 8–12 windows? Measured.

**The owner's question, 2026-09-11:** "I want no slowdowns, and I'm scared that with one engine and a bunch
of windows there might be some slowdowns." He also settled the design in the same breath: **one shared
history, not one per window** — *"I really want to talk to you each time"* — and **windows that are more
integrated, not less**.

**Answer:** the engine is not the problem and does not degrade at 12 windows. **The browsers were.** Nine
windows with default Edge flags cost **6,951 MB across 97 processes** while the engine stayed at 229 MB, and
free RAM fell to 2.3 GB on a 31.6 GB machine. That is what "slow" felt like. With lean launch flags the
per-window cost drops **41%** (770 MB → 454 MB), and that single change is worth more than any engine
tuning.

---

## Correction first, because the first measurement was wrong

The first harness (`_scratch/dshw-perf/dshw-perf.mjs`) POSTed `{}` to the `/api/*` endpoints. Every call
came back **HTTP 200 carrying `gateway/bad-request: invalid client-request message`** — the server rejects
the envelope at schema validation, before doing any work. Those numbers measured cheap validation, not the
boot path, and **the first version of this document drew a conclusion from them. It was wrong and is
withdrawn.** The real envelope, captured from a live tab, is:

```json
{ "type": "client-request", "rpcId": "<uuid>", "method": "settings/describe", "payload": { "args": {} } }
```

`dshw-perf2.mjs` speaks that protocol; five of the six boot calls now return `result.ok: true`.

## What the boot path actually costs (single window, valid payloads)

| call | ms | response | ok |
|---|---|---|---|
| `settings/describe` | **144.5** | 24,434 B | yes |
| `agentPresets/list` | **97.6** | 1,374 B | yes |
| `credentials/describe` | 10.7 | 175 B | yes |
| `session/modelCatalog` | 10.9 | 2,575 B | yes |
| `subagents/list` | 10.8 | 293 B | schema rejected my args |
| `session/list` | 8.3 | 282 B | schema rejected my args |

Two calls carry the whole cost: **`settings/describe` (145 ms)** and **`agentPresets/list` (98 ms)**. Both
are boot-path calls every window makes. The other four are 8–11 ms.

## What happens as windows multiply (valid payloads, one engine)

| concurrent windows | wall | call p50 | call p95 | per-window p50 | event-loop lag p50 | lag max |
|---|---|---|---|---|---|---|
| 1 | 153 ms | 11.9 ms | 99 ms | 153 ms | 9 ms | 20 ms |
| 2 | 234 ms | 16.2 ms | 158 ms | 233 ms | 14 ms | 26 ms |
| 4 | 1,031 ms | 43.8 ms | 823 ms | 1,028 ms | 75 ms | 225 ms |
| 8 | 728 ms | 65.6 ms | 478 ms | 722 ms | 54 ms | 84 ms |
| **12** | **1,363 ms** | **61.6 ms** | **979 ms** | **1,356 ms** | **125 ms** | **193 ms** |

**Read it honestly.** Twelve windows booting at the same instant cost each other about **1.36 s** of
end-to-end work, with 125 ms of typical event-loop lag and a worst case near 1 s for an individual call.
Nothing failed; every request was served. But this is **not free**, and it is not the flat line the
withdrawn measurement claimed. The knee is at **4 concurrent windows**, and it is caused almost entirely by
those two expensive calls being run four to twelve times at once.

**Why this is acceptable anyway.** It is a **startup** cost, not a steady-state one: a window pays it when
its tab loads. In steady state — one window streaming a conversation while eleven sit idle — the loop is
idle, and a human typing is nowhere near 4 simultaneous boot bursts. Mitigations already in place:

- `dshw` **staggers** window launches (250 ms) so twelve windows do not pile onto the two expensive calls.
- Lean Edge flags cut the browser side of the same burst by 41%.

What it is *not*: a reason to run more engines. See below — that is now ruled out for a different reason.

## The window cost, which is the bigger number

| | processes | MB total | MB per window |
|---|---|---|---|
| 9 windows, default Edge flags | 97 | 6,951 | ~770 |
| 6 windows, lean flags | 54 | 2,722 | **~454** |

Lean flags: `--disable-extensions`, `--disable-component-extensions-with-background-pages`,
`--disable-background-networking`, `--disable-component-update`, `--disable-sync`, plus a feature kill list
for the Edge sidebar / collections / shopping / wallet panels. **A 41% cut, with no loss of function** —
every one of the six test windows still authenticated and kept its own cookie jar and local storage, which
is what keeps each window's session choice its own.

At twelve windows that is roughly **5.4 GB instead of 9.2 GB**, against a 31.6 GB machine already holding a
5.3 GB qemu VM. `dshw` now passes these flags on every window it opens.

## Why one engine is now mandatory, not merely cheaper

Beyond the memory argument (~3 GB versus ~17 GB for twelve engines), there is a correctness argument found
in the project's own forum: **a second `dsh web` process on the same `DSH_HOME` wrote duplicate sequence
numbers into one session log and made the whole history unloadable**; the repository's conclusion is one
writer process per `DSH_HOME`. The same failure class is reported against other agent tools
(`openai/codex` #44474, `anthropics/claude-code` #48649). Source:
`research-dsh-perf-config.md` §6.

So `mode: "multi"` in `windows.json` is **not** a supported option on a shared home. It stays in the file
only as a marker of the alternative, and the config comment now says so.

## Two protections applied, and one known hazard left open

1. **WebSocket heartbeat raised to 15 s** (`typert-gateway.websocketHeartbeatIntervalMs`, was 2 s). The
   project documents this value as *both* the ping cadence *and* the pong deadline, tolerating only two
   misses — so a ~2 s event-loop stall would terminate every window's socket at once and start a
   twelve-window reconnect storm. Measured worst-case lag here is 193 ms, so the default had roughly 10x
   headroom; 15 s removes the class entirely. Landed in `profiles/web/cordis.patch.yml`, copied into place
   by `sync.py`, active from the next engine start (verified: engine restarted clean on the patched
   profile).
2. **Window launch stagger + lean flags**, as above.
3. **Still open (PAIN P16):** the project reports the WebSocket downlink has no byte-level backpressure, so
   a *backgrounded or throttled* tab can grow host-side buffers without bound. With twelve windows this is
   the most likely remaining source of a slow night. Nothing to configure — it is a code-level property —
   so the mitigation is operational: keep the number of *actively streaming* windows modest, and treat an
   unexplained memory climb as this.

## What "more integrated windows" means here

Already true, and worth knowing: the windows are **not** separate applications. All of them attach to one
engine, so they share one session store, one set of MCP bridges, one credential store and one agent
runtime. A session started in window 3 is visible in window 7's list. Nothing has to be built for the
windows to see each other's sessions — and the project's own UI cannot do better than N windows, because at
this version the conversation slot is single and owned: a multi-pane plugin is impossible until that
changes (`research-dsh-perf-config.md` §8).

The real integration gap is **addressing**: a window cannot be pointed at a chosen session by URL, so a
restored window needs a click. That is question 3, and it is the highest-value next piece of work.

---

# Re-measured 2026-09-14: 10 windows, and the engine is *faster* than the one-window baseline

**The owner's question:** "we have 10 DSH windows open on this yoga laptop now, and the harness seems to
be slowing down. Is it too much? Should we be doing different threads or cores?"

**Answer: the windows are not the problem and the engine is not the problem. Ten windows whose agents are
all RUNNING is what is heavy, and the resource that is actually tight is memory, not CPU. Adding
threads or cores cannot help this architecture, and that is now sourced rather than asserted.**

## What was measured, and how

`session/list` on the live engine reported **10 of 238 sessions `running: true`** — every open window had
a live agent loop, most on multi-round autonomous goals. The engine's HTTP latency was measured from Node
(PowerShell's ~100 ms per-call overhead would swamp it) with 40 sequential cheap calls plus bursts; CPU
was taken as a **delta over a 20 s window**, never as a cumulative `CPU` column, which says nothing about
the present; memory is **private bytes**, because summing `WorkingSet` across 90 Chromium processes
double-counts shared pages.

## The engine got faster, not slower

| | 2026-09-14, 10 windows | 2026-09-11, 1 window |
|---|---|---|
| cheap call p50 / p95 | **5.8 ms / 16.6 ms** (n=40) | 11.9 ms / 99 ms |
| 2 / 4 / 8 concurrent | 8.9 / 14.0 / 31.0 ms p50 | — |
| `settings/describe` | 7.5 ms | 145 ms |
| `agentPresets/list` | 81.5 ms | 97.6 ms |

Engine process: 13 OS threads, 763 CPU-seconds over 2.5 h (~0.08 of one core), private memory
oscillating 1,307 → 1,441 → 1,390 MB in 2 minutes — busy, not leaking. **The single event loop is not the
bottleneck, and ten WebSocket clients do not change that.**

## Where the load actually is

| consumer | processes | private | sustained CPU |
|---|---|---|---|
| Edge windows (10-11 instances) | 90 | 7,729 MB | **6.7 cores of 22** |
| engine tree (node + MCP bridges + Playwright's Chrome) | 37-42 | 2,651-2,988 MB | 0.66 core |
| `personal-secretary` uvicorn (+ `next dev`) | 4 | 2,526 MB | 0.22 core |
| other node (MCP bridges) | 20 | 3,005 MB total incl. engine | 0.48 core |
| TextInputHost | 1 | **1,195 MB** (abnormal) | — |

**The per-window cost is a function of whether that window's agent is generating, not of the window count:**

- window whose agent is generating: **1.0-1.1 of one core**, ~750 MB private
- window sitting quiet: **0.24-0.28 of one core**, 467-783 MB private

So ten idle windows ≈ 2.5 cores; ten generating agents ≈ 7 cores. Lean Edge flags are confirmed present
on the live command lines, so this is *after* the 41% cut this document recorded on 2026-09-11.

## The number that is actually tight: commit, not CPU

- **committed 28.6-28.8 GB of 31.61 GB physical → 2.8-3.3 GB of headroom**, and free RAM drained
  **~370 MB/min** while ten agents ran.
- Not paging yet: 1.6-10 pages/sec, pagefile 0.13 GB used of 11.5 GB allocated, disk idle, CPU boosting
  at 132% of nominal (no thermal throttle).
- **The tripwire: if commit crosses 31.61 GB the machine starts paging to an 11.5 GB pagefile, and that
  is the point at which it will feel genuinely slow.** Until then "slow" is commit pressure trimming
  working sets, plus the renderer of whichever window is streaming (a streaming window sits at ~100% of
  one core, which is enough to make a 700x440 window's scrolling and typing lag).

## Threads and cores: ruled out, with sources

Full sourced research: `~/code/research-node-cores-chromium-findings.md` (every claim labelled
OFFICIAL / COMMUNITY / INFERENCE with URLs). The load-bearing facts:

- Node runs all JS on **one** event-loop thread; the libuv pool (default 4, unchanged here) serves only
  `fs`, `dns.lookup`, async crypto and async zlib — **network I/O never touches it**, so
  `UV_THREADPOOL_SIZE` cannot speed up WebSocket fan-out.
- `cluster` shares no memory; `worker_threads` shares only `SharedArrayBuffer`. Neither can share a live
  object graph, and this engine is single-writer by design (two `dsh web` on one `DSH_HOME` corrupt the
  session log — already recorded in this document's §"Why one engine is mandatory").
- Microsoft: *"Setting thread affinity should generally be avoided, because it can interfere with the
  scheduler's ability to schedule threads effectively across processors."* Priority is documented as
  brief, time-critical-only, with boosts that decay every time slice.
- The one place cores are real: Windows assigns QoS by window state — In Focus **High**, Visible
  **Medium**, Minimized/Occluded **Low**, and Low/Utility schedules to efficient cores. On a 6 P-core /
  10 E-core Ultra 7 155H, the nine background windows are *supposed* to land on E-cores.
- `--single-process` is in Chromium's own dangerous-flags list (sandbox-disabling); `--disable-blink-
  features` / `--enable-blink-features` are annotated "not supported".

## Two structural facts found while measuring

1. **There is no global session-concurrency cap in DSH.** `maxParallelToolCalls` is per-session (default
   10; this machine sets **20**), and nothing limits how many sessions run at once. Ten was possible
   because nothing prevents ten. Each parallel tool call can spawn a ~57 MB `dsh-subprocess-local` runner.
2. **More windows are open than `windows.json` enables** — 8 enabled, ~11 open. `Invoke-New`
   force-enables every slot before picking the first free one, so `dsh new` opens slots marked
   `enabled: false` (w9, w10, w11).

## Recommended, in measured order (none applied — the owner said change nothing yet, 2026-09-14)

1. Free fixed overhead: Playwright's headless Chrome (**22 processes, 1.74 GB**, alive whether or not
   browser automation is in use) and the `personal-secretary` dev stack (2.46 GB + `next dev`).
2. Cap *simultaneously running* agents at 3-4; the cost tracks running sessions, not open windows.
3. `maxParallelToolCalls` 20 → 10 (the default).
4. Close unused windows, and fix `Invoke-New` to respect `enabled: false`.
5. Still open from 2026-09-11: the WS downlink has **no byte-level backpressure**. Node's own docs are
   explicit that `write() === false` means bytes queued in *server* memory, and WHATWG requires a
   WebSocket whose buffer is full to be closed. This remains the known mechanism for an unexplained
   memory climb, and it is a code-level property of the engine — not configurable.

