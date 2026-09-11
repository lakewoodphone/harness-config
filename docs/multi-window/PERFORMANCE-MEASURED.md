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
