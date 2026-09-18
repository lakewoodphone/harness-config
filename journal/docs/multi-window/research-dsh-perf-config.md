# DSH performance knobs and limits for one `dsh web` process serving many concurrent sessions

**Date all sources were read: 2026-09-11** (America/New_York).
**Subject:** DeepSeek Harness, npm `@deepseek-ai/dsh`, repo `github.com/deepseek-ai/deepseek-harness`.
**Installed and verified locally:** `0.1.5-rc.1` (read from `package.json` in the npx cache at
`…\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\`). Published tags nearest to it:
`dsh-v0.1.5-rc.2`, `dsh-v0.1.5-rc.1` ([tag list](https://api.github.com/repos/deepseek-ai/deepseek-harness/tags), read 2026-09-11).
**Goal of the research:** 8–12 browser windows against ONE `dsh web` server process, each window its own agent
session with concurrent turns, with no slowdowns, and without separate engines.

## Method and source honesty

Two source classes are used and always labelled:

1. **Shipped package docs** — the `README.md` files inside the installed `0.1.5-rc.1` tree. These describe the
   version actually running here. Cited as `local: <package>/README.md`.
2. **Upstream repository docs and discussions** — the generated `docs/config-catalog.md` and GitHub
   Discussions/Issues. Cited with a URL.
3. Third-party blogs, community plugins and other-repo issues are labelled **blog/community** or **other repo**.

Tool outcomes, reported as required:

- `firecrawl_scrape` **worked** once called with top-level `url`/`formats`; my first three calls failed with
  `url: Invalid input: expected string, received undefined`, which was my own malformed argument shape, not a
  fault of the tool or the harness.
- `jina read_url` retrieved `docs/config-catalog.md` in full but reported
  `Question-grounded extraction was unavailable for this page; returning full content` — for raw
  `raw.githubusercontent.com` markdown it cannot answer a question, only dump the document. All other jina
  question-mode reads (GitHub Discussions, api-docs) returned focused snippets.

---

# 1. Configuration catalogue

The generated catalogue is the exhaustive deployment-axis reference:
[`docs/config-catalog.md` @ `dsh-v0.1.5-rc.2`](https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/config-catalog.md) (read 2026-09-11). Its own header says it is generated from
source, "verified fresh by `pnpm run verify-config-catalog`", and that "This is the **deployment**-axis
reference". Every loadable package's `README.md` also points at it, e.g.
`local: dsh-client-connection/README.md` line 50.

Settings that plausibly affect throughput or latency. **Key paths are relative to the plugin's `config:` block
in `cordis.yml`** (e.g. `client-connection` → `@deepseek-ai/dsh-client-connection`).

### Connection, transport and recovery

| Key path | Default | Project's own words |
|---|---|---|
| `client-connection.recovery.backoffBaseMs` | `500` | "First-retry delay cap in ms; actual delay is **50–100% of the cap**" |
| `client-connection.recovery.backoffFactor` | `2` | "Finite growth factor of at least 1 per failed attempt; 1 keeps a fixed cap" |
| `client-connection.recovery.backoffMaxMs` | `10000` | "Maximum retry delay cap in ms; retries continue at this cap" |
| `client-connection.recovery.generationReadyWarnMs` | `3000` | "Delay before reporting a slow handshake, without cancelling it" |
| `client-connection.recovery.generationReadyTimeoutMs` | `15000` | "Deadline in ms for readiness, **including physical connection setup**" |
| `client-connection.maxRequestBodyBytes` | `300 MiB` (`314572800`) | "Maximum buffered JSON body for every `/api` request" |
| `client-connection.cookieMaxAgeDays` | `30` | "Absolute browser-session lifetime in days" |
| `client-connection.trustedHosts` | unset | Authorities served beyond loopback; an unlisted Host is refused with 403 |
| `api-gateway.websocketHeartbeatIntervalMs` | `2000` | "WebSocket Ping interval … @default 2000" — and the Known Limitations add: it "is both the Ping cadence **and the Pong deadline**. The Host terminates a peer that does not answer before the next interval, so a deployment whose **event loop or network can stall longer than this interval must raise it**" |
| `host-webserver.compression` / `compressionLevel` / `compressionThresholdBytes` | `'none'` / `1` / `1024` | The shipped Web bundle uses gzip level 1 with a 1024-byte threshold; "other compositions default to no compression" |
| `host-webserver.host` / `port` | `127.0.0.1` / — | Two supported hosts only; socket backlog and other socket settings "remain internal until a deployment needs them" |

Source of the table: the catalog (URL above) plus `local: dsh-client-connection/README.md` (line 50),
`local: dsh-api-gateway/README.md` (lines 35, 77), `local: dsh-host-webserver/README.md` (lines 39, 114).
The catalog was **independently confirmed locally**: `dsh-client-connection/lib/index.js` line 24 sets
`DEFAULT_MAX_REQUEST_BODY_BYTES = 300 * 1024 * 1024`, and line 741 defaults it in the schema; the recovery
schema lives at lines 700–730 of `lib/index.js`.

### Agent loop, tool fan-out, jobs

| Key path | Default | Meaning |
|---|---|---|
| `agent-loop.maxParallelToolCalls` | `10` | "Parallel-safe tool calls in flight per step; `1` is serial". Also "the whole `agent-loop` settings section, so a user layer over this entry caps the next tool group **without a restart**" (`local: dsh-agent-loop/README.md` line 48) |
| `tools.maxParallelSubCalls` | `10` | "Concurrency cap for a `run_code` program's overlapping sub-calls" (`local: dsh-tools/README.md` line 75) |
| `jobs-local.maxConcurrentJobsPerOwner` | `10` | "Maximum `running` plus `stopping` jobs per exact owner or in the shared unowned bucket" |
| `workflow-worker-thread.maxConcurrentAgents` | `0` → auto | "`0` … auto-resolves to `min(16, max(1, cores - 2))`" |
| `workflow-worker-thread.maxTotalAgents` | `1000` | "Total `agent()` calls one run may start — the runaway-loop backstop" |
| `tool-subagent.maxDepth` | `3` | "Absolute delegation-depth cap (`0` forbids delegation)" — **depth only, no breadth cap** |

`local: dsh-tool-subagent/README.md` line 53, `local: dsh-workflow-worker-thread/README.md`.

### Output retention, spill, compaction

| Key path | Default | Meaning |
|---|---|---|
| `spill-policy.maxInlineBytes` | omitted (policy off) | "The model-facing context cap for a plain-text tool result, in UTF-8 bytes. **Omitted disables the policy entirely** (no-op)" |
| `compaction-basic.thresholdRatio` | `0.8` | "Compact at this fraction of the model's context window" |
| `compaction-basic.retainRatio` | `0.16` | "Recent context retained as a fraction of the model's window" |
| `compaction-basic.retainTokens` | unset | Absolute recent-context budget; mutually exclusive with `retainRatio` |
| `compaction-basic.maxTokens` | `8192` | Provider generation cap for summarization |
| `compaction-basic.compactionRetries` | `1` | Extra attempts when pressure remains above threshold |
| `compaction-basic.maxOverflowRetries` | `1` | Retries after canonical context overflow; `0` disables recovery |
| `compaction-basic.auto` | `true` | "Enable automatic step-boundary pressure and overflow-recovery listeners" |
| `compaction-basic.modelPolicies` | unset | Per provider/model overrides |
| `compaction-tool-result-pruner.thresholdChars` / `headChars` / `tailChars` | `8192` / `4096` / `1024` | Deterministic tool-result pruning, in Unicode code points |

`dsh-output-retention` is a **library, not loadable** ("a `cordis.yml` cannot load them" — catalog, "Library
packages" section). Its resident cost bound is documented: `TextRetainer` "holds at most `headBytes +
tailBytes + one chunk` in memory, so a large stream does not accumulate unbounded"
(`local: dsh-output-retention/README.md` line 112). `ItemRetainer` supports `head` only.

### Session store, projection cache, query concurrency, telemetry

| Key path | Default | Meaning |
|---|---|---|
| `session-query-sqlite.persistedReadConcurrency` | `4` | "Maximum concurrent persisted-log reads in one inherited batch read" |
| `session-query-sqlite.preparedSessionCacheSize` | `5` | "Maximum cold prepared-Session observations the inherited reader retains for reuse" |
| `session-query-sqlite.defaultLimit` / `maxLimit` | `20` / `100` | Page size when a request omits `limit` / largest accepted page |
| `session-query-sqlite.snippetChars` | `240` | Maximum snippet length in code points |
| `session-query-sqlite.journalMode` / `openAt` | `wal` / `startup` | SQLite journal mode; `never` disables FTS and never imports SQLite |
| `session-projection-cache.writeEveryEvents` / `writeIntervalMs` | **required, no default** | "Committed events per session that force a durable checkpoint write between mandatory points" / "Longest time (milliseconds) a dirty checkpoint may stay unwritten" |
| `session-persistence-jsonl.compression` | `zstd` | "Physical encoding; defaults to checksummed Zstandard frames" |
| `session-telemetry-otel.mode` | `FEEDBACK_ONLY` | "capture session history only when feedback is explicitly submitted"; `DISABLED` reads neither exporter nor deadline |
| `session-telemetry-otel.processor` | unset | Passed verbatim to `BatchLogRecordProcessor`; the SDK owns these knobs |
| `attachment-local.imageCompressionConcurrency` | `2` | "Maximum simultaneous normalization or request-image transformations in this service instance" |
| `attachment-local.maxMessageImageBytes` / `maxImageBytes` / `maxImagesPerMessage` | `200 MiB` / `20 MiB` / `20` | Aggregate per-message image cap; per-image cap; per-message count |
| `code-runtime-worker-thread.maxOldGenerationSizeMb` | unset | "The worker's max old-generation heap in MiB (`resourceLimits`); overflow kills the worker" |
| `llm-deepseek.streamIdleTimeoutMs` | five minutes | "Maximum provider idle time while one stream read is outstanding" |
| `llm-deepseek.retryPolicy` | omission | "omission uses normal mode with **five retries**"; eligible codes include `RATE_LIMIT`, backoff "from 500 ms to 10 seconds and 10 percent jitter" (`local: dsh-llm-retry/README.md` line 50) |
| `llm-deepseek.maxTokens` / `defaultContextWindow` | `256000` / `1000000` | Per-request output cap; context capacity when the model has no exact value |

`dsh-llm-retry` "has no configuration of its own" (`local: dsh-llm-retry/README.md` line 28) — the policy
lives on each provider adapter.

**Takeaway:** the throughput-relevant surface is small and entirely in `cordis.yml` — the two that actually
size a many-window server are `api-gateway.websocketHeartbeatIntervalMs` and
`client-connection.maxRequestBodyBytes`; nothing in the catalogue is a client-count or connection-count knob.

---

# 2. Documented limits

### Request-body buffering (the only hard per-request memory number)

> "**Buffered `/api` routes retain each request body in memory** — `maxRequestBodyBytes` (default 300 MiB,
> sized for the default 200 MiB aggregate image limit after base64 expansion plus envelope headroom) bounds
> ordinary image and RPC envelopes. Opt-in streaming routes receive backpressured chunks and bypass the
> aggregate cap; route implementations own persistence, cancellation, and any storage quota."
> — `local: dsh-client-connection/README.md`, "Known Limitations and Deferred Work" (line 66)

That is per in-flight request, and 300 MiB is a ceiling per request, not per client. There is no documented
per-client buffer total.

### WebSocket streams and heartbeat

> "The Client opens the Gateway-owned `/api/remote.mux` WebSocket when its plugin activates and keeps it
> connected while idle. … Independently cancellable logical streams share that socket."
> — `local: dsh-api-gateway/README.md` line 35

> "`websocketHeartbeatIntervalMs` is both the Ping cadence and the Pong deadline. The Host terminates a peer
> that does not answer before the next interval, so a deployment whose event loop or network can stall longer
> than this interval must raise it."
> — `local: dsh-api-gateway/README.md`, Known Limitations (line 77)

**This is the single most load-relevant sentence in the shipped docs.** At the 2000 ms default, a saturated
event loop that cannot service Ping/Pong for 2 s causes the Host to terminate that window's socket; the client
then reconnects and re-baselines. Twelve windows live on one event loop, so a stall costs twelve resyncs.

### One origin, one browser session, no per-window identity

> "Every Host RPC method and WebSocket stream requires one browser session. … Cookies … bind the normalized
> hostname plus port in both their deterministic name and signed payload. They are host-only, `Path=/`,
> `HttpOnly`, and `SameSite=Strict` … **There is no logout operation** — clearing the browser cookie ends one
> browser session; deleting the owner credential record and restarting `dsh` revokes every session."
> — `local: dsh-client-connection/README.md` lines 35, 37, 68

Consequence: all 12 windows on `http://127.0.0.1:<port>` share **one** authenticated browser session. There
is no per-window or per-tab identity, so there is nothing to configure per window and no way to give one
window different privileges. Windows are distinguished only by their own WebSocket and their own session
selection.

### Server surface

> "**`dsh web --host 0.0.0.0` remains unsupported**" — `local: dsh-client-connection/README.md` line 39.
> "**Binding all network interfaces is not supported** — `--host 0.0.0.0` is rejected at startup for safety"
> — `local: dsh-web-app/README.md` line 149.
> "**Socket options are fixed** — config selects the bind host and port, while backlog and other socket
> settings remain internal until a deployment needs them." and "**No server-wide TLS, authentication, or
> origin policy**" — `local: dsh-host-webserver/README.md` lines 113–114.

One `dsh web` process therefore = one loopback origin. Multiple windows are the only way to get multiple
surfaces, because the server cannot even be reached from another machine.

### No documented cap on windows, sessions or streams

**UNVERIFIED:** I found **no** documented maximum for concurrent sessions, concurrent browser tabs, WebSocket
connections, logical streams per client, or memory per session, in the catalogue, any package `README.md`, or
`docs/user/guide/index.md` (the whole Web UI user guide, read 2026-09-11:
[guide index](https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/user/guide/index.md)
— it documents model setup, workspace choice and one task, and says nothing about multiple windows at all).
The absence of a documented cap is not evidence of capacity.

### What the community reports about memory and buffering (labelled: upstream discussion, not official docs)

- **Web server OOM/linear heap growth with large histories** —
  [Discussion #3275](https://github.com/deepseek-ai/deepseek-harness/discussions/3275) (read 2026-09-11):
  "Web server OOMs within ~60s of any client connecting when a workspace contains a large session". The
  reporter measured "session dir total: 149MB compressed → ~500MB decompressed JSON", "the 3.18GB snapshot =
  the parsed object tree of all sessions", and concluded "the web server decompresses, parses and retains
  every session at startup — **heap usage grows linearly with the session directory**, so any fixed cap will
  eventually be hit". Workaround verified by the reporter: "`NODE_OPTIONS=--max-old-space-size=8192` runs fine
  (peak RSS ≈ 4.7GB)", which "only postpones the crash", and "the 4GB default is guaranteed death for users
  with large session histories". **This matters directly here: more sessions is more retained heap, and
  twelve concurrently active sessions grow the history faster.**
- **WebSocket downlink has no byte-level backpressure** —
  [Discussion #671](https://github.com/deepseek-ai/deepseek-harness/discussions/671) (read 2026-09-11,
  verified by the reporter at master `47f9438`): "The WebSocket downlink pump applies per-frame (rate)
  backpressure, not byte/buffer-level backpressure. On a throttled browser tab (backgrounded,
  CPU-suspended) with a dense event stream … `socket.bufferedAmount` grows without bound — a long-running
  memory leak." Suggested fix: check `socket.bufferedAmount` before `send`, pause above a threshold, cap
  queued frames. **With 12 windows, any one backgrounded window is a slow consumer that the Host cannot see.**
- **Full-fanout event multiplexing and UI starvation at 0.1.0-rc.6** —
  [Discussion #1316](https://github.com/deepseek-ai/deepseek-harness/discussions/1316) (read 2026-09-11):
  with 3 sessions streaming in parallel the mux delivered "344 frames/s, ~1.1 MB/s" and clicking "new
  session" took seconds; the reporter's root cause was that `events.mux` "registers a global `session/event`
  listener — **all events of all sessions broadcast in full to all browser connections, with no per-session
  subscription filtering**", plus an unbounded `FrameQueue` and unbounded browser `inbox`, and token-level
  chunk granularity. Static HTTP stayed fast (1–5 ms) while the UI stalled. **Caveat, verified: the reporter
  cites `packages/host/apiproxy/src/api-proxy.ts`, and that package does not exist in the `dsh-v0.1.5-rc.2`
  tree** (I listed `packages/host`: `directory-picker-auto`, `directory-picker-browse`,
  `directory-picker-native`, `README.*`, and the webserver/frontend-static/etc. set — no `apiproxy`), and the
  installed session-history path is now a **per-session** journal stream, not a global broadcast:
  "The Client adapter exposes `SessionEventStream`, a Gateway `RemoteJournalStream` bound to one ordinary or
  direct-subagent address" (`local: dsh-api-session-controller/README.md` line 33). So the rc.6 mechanism
  appears re-architected before rc.1; treat #1316 as a stale root cause with a still-plausible failure shape
  (the shared mux still carries host-wide forwarded events to every window —
  `local: dsh-api-remotes/lib/types/remote-events.js` lists ~20 host-wide events including
  `api-session/activity`, `api-session/status`, `settings/document-updated`, `cordis/*`).
- **Session-list rebuild starvation** —
  [Discussion #5205](https://github.com/deepseek-ai/deepseek-harness/discussions/5205) (read 2026-09-11):
  the `subagentTiming` projection is updated per token, which triggers `markDirty()` → `buildListSnapshot()`
  → "traverse all summaries, read projection values, run `flattenLineage()`, and rebuild
  `subagentsByParent`/`jobsBySession`", plus a potential O(N²) entry-cache cleanup. The reporter asks that
  "the menu timer, chat and sidebar stay interactive even with multiple subagents running". **This is a
  per-process, all-windows cost that grows with active subagents, i.e. exactly the 12-concurrent-session case.**

**Takeaway:** the project documents one hard per-request memory bound (300 MiB buffered bodies), a fixed
socket/timeout design, one origin with one shared cookie, and **no client-count or per-session memory limit
anywhere** — the community reports that the real ceiling is the single event loop plus linearly growing
session heap, not a configured cap.

---

# 3. Provider-rate-limit reality

**Official source:** [Rate Limit & Isolation, DeepSeek API Docs](https://api-docs.deepseek.com/quick_start/rate_limit/)
(read 2026-09-11).

What the page says, verbatim in substance:

- "For each account, the concurrency limits for different DeepSeek API models are shown in the table below."
  `deepseek-flash` → **2500**, `deepseek-v4-pro` → **500**.
- "A request counts as **one concurrent connection from the time it is sent until the model response is
  complete**".
- "Concurrency limits are calculated **at the account level, regardless of which API Key is used**."
- "API requests within the concurrency limit will receive a response; when the concurrency limit is exceeded,
  you will receive an **HTTP 429** error code."
- Higher concurrency is available by [capacity expansion request] — "We will match the appropriate concurrency
  based on your actual business needs. **There is no additional cost for capacity expansion.**"
- **`user_id` isolation:** "For regular API users, all `user_id` values are combined for concurrency limit
  calculation"; for accounts with increased quotas, "we will also impose concurrency limits on each `user_id`"
  at the same 2500/500 numbers, and "If a `user_id` exceeds its limit, requests with that `user_id` under your
  account will receive an HTTP 429 error code". `user_id` must match `[a-zA-Z0-9\-_]+`, max 512 chars.
- **Keep-alive / queue behaviour:** "After your request is sent, it may sometimes take a while to receive a
  response … your HTTP request will remain connected" while the server returns empty lines (non-streaming) or
  SSE keep-alive comments `: keep-alive` (streaming). "**If the request has not started inference after 10
  minutes, the server will close the connection.**"

**Tiering:** the page describes capacity differencing by **model** (flash 2500 vs v4-pro 500) and by **account
quota tier** (regular accounts vs accounts granted increased concurrency, which additionally get per-`user_id`
sub-limits). It does **not** publish a per-tier RPM or TPM table.

**UNVERIFIED:** requests-per-minute and tokens-per-minute limits. The official page documents **concurrency**,
per-`user_id` isolation, and keep-alive; I found no official RPM/TPM figures at
`api-docs.deepseek.com` on 2026-09-11. Claims circulating that DeepSeek "does not constrain rate limits"
([Simon Willison's blogmark, 2025-01-18](https://simonwillison.net/2025/Jan/18/deepseek-api-docs-rate-limit/);
**blog**, dated 2025 and superseded by the current page) must not be relied on — the current page states a
hard per-account concurrency limit and 429 behaviour.

**Do parallel requests queue?** Yes, in the sense that matters: a request is counted as one concurrent
connection while it is in flight, and once the account is at its cap further requests are refused with 429
rather than queued server-side. The harness then queues locally, because
`llm-deepseek.retryPolicy` omits to "normal mode: five retries for … `RATE_LIMIT` … with bounded exponential
backoff from 500 ms to 10 seconds and 10 percent jitter", and "A valid `Retry-After` from the provider
replaces local backoff when it fits the policy bounds"
(`local: dsh-llm-retry/README.md` lines 50, 54; `local: dsh-llm-deepseek/README.md`).

**Arithmetic for this deployment:** 12 simultaneous turns = 12 concurrent model requests against a ceiling of
500 (v4-pro) or 2500 (flash) — roughly 2.4% or 0.5% of the account cap, all under one API key, with no
per-`user_id` limit applying to a regular account. **The provider is not the bottleneck for 12 sessions.** The
bottleneck is the single Node event loop in the one `dsh web` process, plus whatever the 12 sessions' token
streams do to the browser side. The practical provider-side failure mode is not throttling but latency: a
429 becomes a 500 ms–10 s backoff per affected step.

**Takeaway:** at 12 concurrent turns the DeepSeek API has ~40× headroom and cannot be the cause of slowdowns;
concurrency is capped per account, 429 (not queuing) is the overflow behaviour, and any 429 surfaces locally
as bounded retry backoff.

---

# 4. Prior art on many-agent desktop setups

### 4a. This repository's own discussions — one process, many clients, and where it breaks

All read 2026-09-11; all are community bug reports/discussions, **not** maintainer statements (none of these
threads shows a maintainer reply; #1316 and #671 show "0 comments"/"0 replies").

| Thread | Setup | What happened | What was reported as the fix / lesson |
|---|---|---|---|
| [#1316](https://github.com/deepseek-ai/deepseek-harness/discussions/1316) | 3 sessions streaming in one `dsh web` | 344 frames/s ≈ 1.1 MB/s into the browser; "new session" click delayed seconds; static HTTP still 1–5 ms | Per-session subscription filtering on the mux; coalesce token chunks to 50–100 ms batches; **bounded** FrameQueue with a slow-consumer policy (drop or disconnect + resync); expose queue-length/backlog metrics |
| [#671](https://github.com/deepseek-ai/deepseek-harness/discussions/671) | one throttled/backgrounded tab | `socket.bufferedAmount` "grows without bound — a long-running memory leak" | Check `bufferedAmount` and pause the iterator above a threshold; cap queued frames |
| [#131](https://github.com/deepseek-ai/deepseek-harness/discussions/131) | 56 subagents from one task, one `dsh web` | Process reached ~2.2 GB, one core saturated ~20 min, `:3080` "completely unresponsive (requests queued and timing out)", only a manual kill recovered; deterministic, reproduced on restart | "Depth is capped, breadth is unlimited": `dsh-subagent` has **no** `maxTotal`/`maxConcurrent`; only `tool-subagent.maxDepth` (3). Reporter's quote of the repo's own note `2026-08-09-parallel-subagent-delegations`: "`maxParallelToolCalls` limits unsettled tool calls in a single step … **background and continuable calls settle at start and release their slot, so the subagents they leave running are not bounded by that limit. The LLM provider owns its own capacity control.**" (second-hand quote of an upstream agent note) |
| [#1452](https://github.com/deepseek-ai/deepseek-harness/discussions/1452) | **two** DSH processes sharing one `DSH_HOME`, same session open in both | Duplicate `seq` block written twice; loader judged the log corrupt and refused the entire history (129,772 events, 1 session lost, only offline repair recovered it) | Reporter recommends documenting "**only one writer process per `DSH_HOME` at a time**"; community answers that worked: separate `DSH_HOME` per instance (`DSH_HOME=~/.dsh-test npx @deepseek-ai/dsh web --port 3081`), a `dsh-single-instance-guard` plugin, and offline repair tools |
| [#3020](https://github.com/deepseek-ai/deepseek-harness/discussions/3020) | one backgrounded tab, 1.5 h | mux WebSocket died silently; the UI still said "connected"; a pending `ask_user_question` never rendered and the turn hung until page refresh | Server-side Ping/Pong heartbeat so a dead socket is detected and the pending prompt is replayed on reconnect |
| [#5205](https://github.com/deepseek-ai/deepseek-harness/discussions/5205) | several subagents streaming | token-frequency `subagentTiming` publication rebuilds the whole session list and starves the renderer | Publish timing at ≤1 Hz, flush at turn boundaries; invalidate the list per subscribed key instead of wholly; add a deterministic stress test |
| [#604](https://github.com/deepseek-ai/deepseek-harness/discussions/604) | wanted multi-pane UI | Not achievable by a plugin: the `conversation` slot is single and owned, sessions bind only to the current selection, and there is no by-id conversation read path | Proposals (0 comments): `ISessions.session(id)`, a `SessionScope` seat, a `conversation.panes` seam |

### 4b. What other tools' communities report (labelled: **other repos**, community issues)

- **`anthropics/claude-code` [#48649](https://github.com/anthropics/claude-code/issues/48649)** — "Subagents
  spawn duplicate MCP server processes, multiplying kernel resource consumption".
- **`anthropics/claude-code` [#82952](https://github.com/anthropics/claude-code/issues/82952)** — "Per-session
  MCP server spawn multiplies RAM use — lazy spawn or per-session MCP scoping needed".
- **`openai/codex` [#44474](https://github.com/openai/codex/issues/44474)** — "[CLI] Concurrent startup races
  state DB migration 53" — i.e. N processes against one shared state directory is itself a bug source.
- **`openai/codex-plugin-cc` [#382](https://github.com/openai/codex-plugin-cc/issues/382)** — "Concurrent
  Claude Code sessions race on shared `~/.codex` — app-server spawned without an isolated `CODEX_HOME`".

These four all describe the **N-processes-per-window** architecture failing on shared state and duplicated
per-session daemons — the same failure class as DSH #1452. None of them describes a per-window process model
working better than a shared server.

### 4c. Practitioner conventions (labelled: **third-party / community knowledge base**)

From [agentpatterns-ai, "Tiled Agent Layout"](https://raw.githubusercontent.com/agentpatterns-ai/website/main/workflows/tiled-agent-layout.md)
(**community knowledge base, last reviewed 2026-06-12**, read 2026-09-11): Cursor 3.1 added Tiled Layout
(one window, many panes; changelog 2026-04-13) precisely so a supervisor stops paying a per-switch cost;
"Reported concurrency from practitioners clusters around **4–10 agents per supervisor**", "A tiled layout with
five visible panes is at the edge of that range. Above five, panes become too small to read". It also cites
Boris Cherny running "five Claude Code sessions locally in terminal tabs, plus another five to ten in the
browser". Note the warning that applies here: above that range the supervision model degrades even when the
machine copes.

**Takeaway:** every documented case of running many agents on one machine converges on **one long-lived server
with many clients, plus hard per-process caps** (per-turn tool caps, subagent breadth caps, bounded event
queues); the cases that broke were either unbounded fan-out inside one process or **multiple engine processes
sharing one state directory**, which corrupts state rather than merely slowing things down.

---

# 5. What the project ships for multi-client use

**Ships:**

- **One server, many windows.** `dsh --profile web` runs one process serving one loopback origin; the browser
  opens the GUI, and "**Per-session agent setup** — Each browser session composes its own agent from the
  shipped presets (the `standard` preset by default), instead of sharing one process-wide tool set"
  (`local: dsh-web-app/README.md` line 62). Sessions are process-wide, so every window sees the same session
  list and can attach to a different session.
- **A multiplexed client transport.** One `/api/remote.mux` WebSocket per browser page, carrying
  "independently cancellable logical streams", with Ping/Pong keepalive at `websocketHeartbeatIntervalMs`
  (default 2000 ms) (`local: dsh-api-gateway/README.md` line 35).
- **A shared session store and index.** `dsh-session-persistence-jsonl` (zstd-compressed logs) plus
  `dsh-session-query-sqlite` (FTS index, WAL, `openAt: startup`) — that shared store is *why* N windows work
  at all, and it is also the single-writer constraint (see #1452).
- **A per-session history stream.** `SessionEventStream`: a `RemoteJournalStream` "bound to one ordinary or
  direct-subagent address" with follow-before-page, gap repair and `loadOlder()`/`loadThrough(seq)` paging
  (`local: dsh-api-session-controller/README.md` line 33) — i.e. each window streams **only** the session it
  shows, not all sessions.
- **Other multi-client surfaces, not GUIs.** ACP "multiplexes concurrent ACP sessions over one connection"
  (`local: dsh-acp/README.md` line 126, design note) with "Each session permits one in-flight prompt"
  (line 109); the SDK JSON-RPC server states "JSON-RPC requests may dispatch concurrently" and "independent
  requests may enqueue more work on the same session" (`local: dsh-sdk-jsonrpc-server/README.md` line 48);
  `dsh-headless` exists for "one-shot command-line tasks" (`local: dsh-web-app/README.md` line 12).

**Does not ship (verified absences):**

- **No daemon/server mode separate from the web profile.** No `dsh serve`/gateway daemon is documented in the
  catalogue or the package READMEs. **UNVERIFIED:** absence of a daemon subcommand was established by reading
  the catalogue, `dsh-web-app`, `dsh-host-webserver`, `dsh-headless` and `dsh-acp` docs, not by inspecting the
  CLI's full command table.
- **No multi-pane or multi-session-per-page UI.** Per
  [Discussion #604](https://github.com/deepseek-ai/deepseek-harness/discussions/604) (read 2026-09-11), a
  split-pane plugin cannot be built on the shipped client: the `conversation` slot "is `single` and owned
  exclusively by `ui-conversation`'s `ConversationRoot`", session-scoped slots "bind only to the current
  selection (`SessionProvider`)", and "there is no mechanism to render a subtree beneath an explicit session's
  provide bundle", nor a by-id conversation data read. The thread has 0 comments. **So at rc.1/rc.2, N browser
  windows is not a workaround for a missing feature — it is the only supported way to watch N sessions.**
- **No per-tab/per-window identity.** One cookie per host:port, host-only, no logout; static assets are public
  (`local: dsh-client-connection/README.md` lines 35, 37, 68).
- **No published client-count or per-session memory limit.** See section 2 (UNVERIFIED).
- **No cross-process coordination for sessions.** "**Process-local residency** — the Activation inbox and
  ownership graph do not coordinate two harness processes; concurrent access to one persistence store needs a
  durable mailbox and cross-process lease protocol" (`local: dsh-subagent/README.md` line 175).

**Takeaway:** the project ships exactly one supported shape for this need — **a single `dsh web` process with
many browser-window clients over one shared session store and one per-page mux socket** — and ships neither a
multi-pane UI nor any client-count cap, so 12 windows is the intended architecture but is also untested
territory that no limit protects.

---

# Applied to 12 windows on one `dsh web` (evidence-backed, no changes made)

1. **Do not run a second engine.** #1452 shows a second process on the same `DSH_HOME` corrupts session logs;
   use one `dsh web` and 12 windows, or give any additional instance its own `DSH_HOME` (**community-
   verified workaround**).
2. **Raise the heap before trusting the default.** #3275: heap grows linearly with the session directory and
   the 4 GB default is "guaranteed death" for large histories; the reporter's verified stopgap is
   `NODE_OPTIONS=--max-old-space-size=8192`. It postpones, not fixes.
3. **Watch the 2 s heartbeat on a busy loop.** `websocketHeartbeatIntervalMs` (default 2000) is both ping
   cadence and pong deadline (`local: dsh-api-gateway/README.md`) — a 2 s stall under 12 concurrent streams
   kills sockets. This is the first knob to raise if windows drop and resync.
4. **Assume backgrounded windows are slow consumers.** #671: no byte-level backpressure on the downlink, so a
   backgrounded/suspended tab accrues unbounded buffered bytes in the Host. Keeping all 12 windows front-most
   is not practical; this is the risk to measure.
5. **The provider is not the limit.** 12 concurrent requests is ~2.4% of the 500-request account ceiling
   (official docs, read 2026-09-11); a 429 costs a 500 ms–10 s retry, not a failure.
6. **Guard against fan-out, not against window count.** #131 and #5205 show the process-level killers are
   subagent breadth (no `maxTotal`/`maxConcurrent` in `dsh-subagent`; only `maxDepth` 3) and per-token
   projection fan-out. Twelve idle-ish sessions are cheap; twelve sessions each delegating is not.
7. **Nothing above is configured today, and no cap exists to trip.** The knobs are all `cordis.yml` keys; the
   catalogue is the exhaustive list and contains no client-count setting.
