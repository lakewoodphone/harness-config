# 06 — Cost multipliers audit (ZABZ-TECH, read-only)

Host: Windows laptop, cwd `C:\Users\ezabz\code`. Install audited: `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\`.
All session numbers come from multi-frame zstd reads (`zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)`); a plain `.decompress()` was not used.
Measurement scripts (read-only, throwaway): `_dsh-scale/notes/_m06/{scan_session,batch,header_tools,tokshare,seeded,routes,msgshape}.py`.

Golden facts used, not re-derived: `assistant/message.data.usage = {inputTokens (cache-miss), outputTokens (incl. reasoningTokens), totalTokens (full prompt + output), cacheReadTokens (cache-hit)}`.

---

## (a) SUBAGENT FORK vs SPAWN — fork re-sends the parent's whole transcript

**Knob (no threshold; a provider choice).** `C:\Users\ezabz\code\harness-config\presets\zabz\agent.cordis.yml:270-287` — two rows, `provider: spawn` (`toolName: subagent`) and `provider: fork` (`toolName: subagent_fork`), both `backgroundMode: continuable`. In the shipped base row the fork tool is `backgroundMode: one-shot` (`dsh-base\cordis.patch.yml:362-367`); the zabz preset overrides it to continuable.

**FORK seeds the child session with the parent's log.** `dsh-subagent-fork-in-process\lib\index.js`:
- `:23-28` `completedTurnPrefix(parent)` → `parent.session.snapshotEvents()` sliced to the last `turn/end`.
- `:44` `inheritsParentContext = true`.
- `:48-51` `start(request) { const seed = completedTurnPrefix(request.parent); return startInProcessRun(request, { ...seed.length > 0 ? { seed } : {} }); }` — same in `prepareContinuable` (`:52-55`).
- `:6-8` module doc: *"runs each child as a child Agent **SEEDED with a prefix of the parent's session log** — so the child inherits the parent's conversation context instead of starting fresh."*

The seed is installed as the child's own session events: `dsh-subagent-in-process-driver\lib\index.js:180-189` passes `...seed !== void 0 ? { seed } : {}` plus `inheritedEventCount: activationBoundary` into `parent.ctx.agents.create()`. The seed is the child's *histórico*, not a one-time note — every child request is assembled from the child's session log, so the parent's messages are part of the child's prompt on every child turn. The codebase states the cost shape itself: `dsh-tool-subagent\lib\index.js:395` warns that route change *"can prevent provider-side reuse of the inherited conversation prefix"*, and `agent.cordis.yml:278-281` says fork omits model selection *"so provider/model stay equal to the parent and the inherited history remains eligible for KV Cache reuse."*

**SPAWN sends nothing from the parent's conversation.** `dsh-subagent-spawn-in-process\lib\index.js:4-8` doc: *"runs each child as a fresh child Agent on the same cordis context (its own session, own system prompt, **zero parent context**). The cheapest transport."* `:30` `inheritsParentContext = false`; `:34-39` `start() → startInProcessRun(request, {})` and `prepareContinuable() → {}` — no seed. The parent contributes only the prompt string: `dsh-subagent-in-process-driver\lib\index.js:207-210` `child.followup(createUserMessage({ content: prompt, ... }))`, plus the small `subagent/descriptor` event (`:139-148`) and the delegated policy overrides (`:172`).

**Quantification.** Let the parent have `N` tokens of history at fork time.
- First child turn: fork prompt ≈ `P + N + prompt`, where `P` is the shared fixed prefix (system + tools); spawn prompt ≈ `P + prompt`. Extra input tokens = **+N**, and because the seed is new bytes for that child session it is a cache **miss** on the first child request (full price).
- Every later child turn: both providers resend their growing child history, but the fork's history *contains* the parent transcript, so the fork continues to carry ~`N` extra tokens in every subsequent request. Those become cache reads once the child's own prefix is cached (cheap), so the recurring marginal cost is ~`N × cacheReadPrice` per turn, not full price.
- Worst case (fork child re-runs the parent's route unchanged and the prefix cache misses again): `N` full-price input tokens per child turn.
- This is per FORK CHILD. Fanning out F forks over the same parent multiplies it by F.

**Measured usage of the knob: zero forks in this workspace.** `_m06/seeded.py` over all 387 sessions in `C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--`: every session header `isSeeded: false`; `total seeded sessions: 0`. Every subagent transcript sampled carries `subagent/descriptor.mode = "continuable"` and a `parentSession`, i.e. the spawn path. **ESTIMATE** of the fork cost is therefore analytic, not measured: for a parent at 40k tokens, one fork child adds 40k cache-miss input tokens on turn 1 and ~40k cached tokens per later turn.

**Capability risk of changing it: small.** Switching fork rows to spawn costs context inheritance (a fork child that must reason about the parent's work would need it restated in the prompt). Nothing else reads `inheritsParentContext` except wording (`dsh-tool-subagent\lib\index.js:393-395`) and `childSessionMeta(parent, childDepth, seed !== void 0)`.

---

## (b) TOOL-RESULT SIZE / SPILL / TRUNCATION — every bound, with the real values

Registry of the bounds in force on this deployment:

| # | Mechanism | File + key | Current value | Default | Units | Effect |
|---|---|---|---|---|---|---|
| 1 | Spill policy (model-facing) | `dsh-base\cordis.patch.yml:383-386` `spill-policy.maxInlineBytes` | **50000** | none (unset ⇒ plugin is a documented no-op, `dsh-spill-policy\lib\index.js:45,104`) | UTF-8 bytes of the whole result | >50 000 B plain-text result is saved to the session spill store and replaced by head/tail preview + locator notice |
| 2 | Spill preview split | `dsh-spill-policy\lib\index.js:89-101` `preview()` | head `ceil(budget/2)`, tail `floor(budget/2)` where `budget = cap − notice − 2` (`:146`) | same (formula) | bytes | head ≈ 25 000 B, tail ≈ 25 000 B at cap 50 000 |
| 3 | Spill notice | `dsh-spill-policy\lib\index.js:21-23` | `" (N bytes omitted. Full formatted result stored at: <locator>. <hint>)"` | same | chars | the model gets a file reference, and `read` is deliberately exempt (`:157`) to avoid a read→spill→read loop |
| 4 | Tool-result pruner (durable log) | `dsh-base\cordis.patch.yml:394-399` and `presets\zabz\agent.cordis.yml:240-245` `tool-result-pruner` | `thresholdChars: 8192`, `headChars: 4096`, `tailChars: 1024` | identical (`dsh-compaction-tool-result-pruner\lib\index.js:11-13`) | chars | result >8 192 chars is **replaced in the session log** by head 4 096 + marker + tail 1 024 (`:93-95`, `:170-180`) — cuts = 4 096+1 024 = 5 120 chars kept |
| 5 | Pruner trigger | `dsh-compaction-basic\lib\index.js:873-905` via `toolResultPruner` | runs when session pressure ≥ threshold: `thresholdRatio 0.8` of context window (`:15`), retain `0.16` (`:17`) | same | ratio | the pruner is NOT applied per tool call; oversized results stay whole until the session reaches 80 % of the window |
| 6 | pwsh/bash inline output cap | `dsh-bash-local\lib\index.js:132` `maxOutputBytes` (pwsh-sandbox uses the same executor config) | **64000** | 64000 | bytes per stream | stdout is tail-kept to 64 000 B; the rest goes to a spill file and the text ends `[output truncated; full output: <path>]` (`dsh-tool-pwsh\lib\index.js:45-48`) |
| 7 | Subprocess spill ceiling | `dsh-bash-local\lib\index.js:89,133` `maxSpillBytes` | 64 MiB | 67108864 | bytes | full output file size cap |
| 8 | fs-search glob | `dsh-tool-fs-search\lib\index.js:1219` `globMaxResults` | 100 (config sets only `sampleOverCapGlobResults: false`, `cordis.patch.yml:263-266`) | 100 | count | over-cap returns first 100 in mtime order + a note + saved complete list (`:704-706`) |
| 9 | fs-search grep | `dsh-tool-fs-search\lib\index.js:1220` `grepMaxMatches` | **250** | 250 | matches | header reads `Found <kept> of <seen> matches` (`:1032`) |
| 10 | fs-search line cap | `:1221` `grepMaxLineBytes` / `:889` `GREP_MAX_LINE_BYTES` | 2000 | 2000 | bytes/line | long line suffixed ` (line truncated)` (`:233-242`) |
| 11 | fs-search meta | `:1222` `searchMetaMaxBytes` / `:58` | 65536 | 65536 | bytes | serialized meta marked `truncated: true` when clipped |
| 12 | fs-search raw pipe | `:1223` `rawOutputMaxBytes` / `:33` | 20 000 000 | 2e7 | bytes | exceeding it fails the call `SEARCH_RAW_OUTPUT_OVERFLOW` |
| 13 | fs-search stderr / timeout | `:1225-1226`, `:39,45,47` | 65536 B / 30000 ms / grace 3000 ms | same | — | diagnostic excerpt only |
| 14 | Tool-call timeout policy | `dsh-base\cordis.patch.yml:377-378` `timeout-policy` | mounted, no config | plugin default | — | per-tool call deadline |
| 15 | Duplicate-call reminders | `dsh-base\cordis.patch.yml:419-423` `repeat-tool-reminder` | thresholds `[3,5,8]`, `argumentsPreviewChars: 500` | same | counts / chars | injects a reminder (adds tokens) after repeated identical calls |
| 16 | Context compaction | `dsh-compaction-basic\lib\index.js:15-17` | threshold 0.8 of window, retain 0.16 | same | ratio | summarisation request when pressure is reached |
| 17 | Result retained by the model | measured, `cordis.patch.yml` | max observed single `tool/result` payload **42 974 chars** (`session-b60e96b3` seq 7186); `ps_health` is documented at ~90 KB (`agent.cordis.yml:396`) | — | chars | with #1 at 50 000 B the whole 43k-char tool result stays inline |

**Measured tool-output share of prompt tokens.** Estimator `_m06/tokshare.py`: per request, scale the characters of tool output currently in context to that same request's *measured* prompt tokens (`usage.totalTokens − usage.outputTokens`), anchored by the first request's measured prefix — no global chars/token constant is invented.

| session | requests | measured prompt tokens | est. prefix tok/req | est. share of prompt tokens from tool output |
|---|---|---|---|---|
| `session-e34dd061` | 101 | 19 424 770 | 38 112 | **82.5 %** |
| `session-e1fbfc24` | 123 | 24 203 355 | 37 630 | **86.9 %** |
| `session-b60e96b3` | 1 845 | 768 322 419 | 36 301 | **95.8 %** |
| `session-b60e96b3` (sizes) | — | — | — | 1 919 tool results, 2 499 963 chars of payload, 2 151 355 chars left in the final context |

So: **~83–96 % of prompt tokens in a real long session are repeated tool output, not conversation.** This is the single largest multiplier found.

**Capability risk of changing it: none/small.** Lowering `maxInlineBytes` or `thresholdChars` only changes what the model sees before it either gets a spill path or must re-read; the tool-result pruner already replaces log content (semantics preserved for replay via `compaction/prune` shadowing, `:162-169`). Risk is behavioural, not structural: over-aggressive pruning makes the model re-run expensive commands.

---

## (c) RETRIES — full input is re-billed, no partial reuse, EMPTY_RESPONSE is billed input

**Knobs.** `C:\Users\ezabz\code\harness-config\settings\base.yaml:87-96` `llm-deepseek.streamIdleTimeoutMs: 60000`, `retryPolicy: {mode: normal, maxRetries: 2, retryableCodes: [EMPTY_RESPONSE, RATE_LIMIT, SERVER, TIMEOUT, TRANSPORT], backoff: {initialDelayMs: 500, maxDelayMs: 5000, jitterRatio: 0.1}}`; mirrored live in `C:\Users\ezabz\.dsh\settings.yaml:12-26`. Plugin row: `dsh-base\cordis.patch.yml:84-85` `llm-retry`. Shipped defaults if unset: `maxRetries 5` (`dsh-llm\lib\index.js:232`), `initialDelayMs 500` (`:233`).

**When a failed attempt is retried, the whole request is re-issued.** `dsh-llm-retry\lib\index.js:175-178` subscribes `agent/request-error`; `:151-173` computes `retry = previousRetry + 1`, appends `llm/retry` durably, waits the backoff, and returns `{ kind: "retry" }`. There is no partial-response channel anywhere in the plugin: the only state carried is `{retry, retryId}` (`:82-85, 99-105`), a counter. `:164` `if (policy.mode === "normal" && previousRetry >= policy.maxRetries) return next();` — with `maxRetries: 2` the provider is called up to **3 times**.

**Answer to "is the already-sent input re-billed?"** Yes. Each attempt is a fresh full request built from the session log; the plugin never caches or reuses prompt state. The only mitigations are provider-side: a retry after a *stream* failure re-sends the same prefix, which the provider's prefix cache can serve as `cacheReadTokens` (cheap) — but a failure before any cache-safe boundary, or a changed prefix, is a fresh miss. **ESTIMATE** of worst case: a failure that is not cache-served and repeats to exhaustion bills the full prompt `1 + maxRetries = 3×` as input, i.e. **3× input tokens for that step**, plus the partial output the dead attempt already produced (unbilled-wise it is charged; not reusable). On the measured fixed prefix of ~36.3–38.1k tokens (see (e)) that is ≈109–114k input tokens for one fully-failed step, versus ≈36–38k for a clean one.

**Partial-response reuse:** none in `dsh-llm-retry` (no code path reads a partial assistant message) and none in the adapter's stream translate (`dsh-llm-deepseek\lib\index.js:1208-1247`: `[DONE]` is the only place blocks and usage are emitted, `pendingFinish`/`pendingUsage`).

**Are EMPTY_RESPONSE failures billed for input?** Yes. `EMPTY_RESPONSE` is manufactured *after* the provider stream ends normally: `dsh-llm-deepseek\lib\index.js:1236-1246` —
```js
const reason = pendingFinish ?? { kind: "stop" };
yield { type: "finish", reason: reason.kind === "stop" && order.length === 0
  ? { kind: "error", failure: { message: "model returned a completed response with no content", code: EMPTY_RESPONSE_CODE } }
  : reason };
```
so the model was prompted, the token bill exists, and the harness discards the result and retries. The second EMPTY_RESPONSE source is a missing body at `:1815` (`"DeepSeek API returned no response body"`), also after the request was sent.

**Measured retry incidence:** `llm/retry` events are permitted in the log (`dsh-session\lib\index.js:100`) and appear **once** in `session-e34dd061` (1 retry / 101 requests, `_m06/batch.py`). The other seven sampled sessions: 0. So the multiplier is real but currently ~1 % of requests, not a systemic cost.

**Capability risk of changing it: small.** `maxRetries: 0` removes transient-blip recovery (and the `base.yaml:76-86` rationale for 2 was written against a real DeepSeek flash outage); raising it multiplies the 3× above.

---

## (d) MCP TOOL SCHEMAS — 6 servers, 95 MCP tools, 87 777 schema chars

**Evidence: the `request/header` event carries the whole catalog.** `_m06/header_tools.py` on `session-b60e96b3-6a48-4898-a770-bc9eb576b9ce` (first header, `reason: "initial"`):

```
tool count: 122   serialized chars: 117176
mcp__ prefix count: 95   chars: 87777
  server firecrawl: 27 tools, 39770 chars
  server playwright: 24 tools, 17006 chars
  server jina:      22 tools, 14265 chars
  server secretary: 14 tools,  7950 chars
  server context7:   2 tools,  4665 chars
  server fetch:      6 tools,  4121 chars
```

- **Server count: 6** — `secretary`, `firecrawl`, `jina`, `context7`, `fetch`, `playwright`. All declared in `presets\zabz\agent.cordis.yml:418-550` as `@deepseek-ai/dsh-mcp-client` rows, Win32-gated except `mcp-secretary-linux` (`:452-462`), all `failOnStartupError: false`. `C:\Users\ezabz\.dsh\settings.yaml` contains **no** MCP section (39 lines, read in full) — the preset is the only source. No `.mcp.json` is mounted by the harness; the only one referenced is VS Code's `personal-secretary-mvp/.vscode/mcp.json`, cited at `agent.cordis.yml:371-373`.
- **Tool counts:** 95 MCP + 27 builtin = 122 at the large-session header; the zabz subagent sessions show 110 tools / 110 850 chars (the fork/spawn tool rows and `workflow`/`ralph`/`list_agents` vary by realm), and top-level sessions 124 / 118 828.
- **Serialized schema characters: 117 176** (all tools, UTF-8 = ASCII). MCP = **87 777** (74.9 %); builtin = 29 399 (25.1 %).
- **Estimated tokens: ≈29 294** at 117 176 chars (`_m06/batch.py` reports the raw char count; the chars→token divisor 4 is the ESTIMATE convention used here). Of that, **≈21 944 MCP** vs ≈7 350 builtin. Cross-check against measured usage: the first prompt of the top-level session is measured at 36 864 + 1 248 = **38 112 tokens** (`_m06/batch.py`, `session-e34dd061`; `msgshape.py` gives system text 21 373 chars ≈5 343 tok), leaving ≈30.2k tokens for the 118 828-char catalog — i.e. the measured divisor is ~3.9 chars/token, so the ≈29 294 estimate is within ~3 %.
- **Per-request:** `request/header` appears 66× in 67 turns of the large session — the catalog is re-sent on every request (hence cache-read-heavy but still on the wire).
- Biggest single offenders: `mcp__firecrawl__firecrawl_search` 5 887 chars, `pwsh` 4 532, `workflow` 4 137, `mcp__firecrawl__firecrawl_crawl` 4 105, `mcp__firecrawl__firecrawl_scrape` 3 959, `mcp__context7__resolve-library-id` 2 936.

**How to change it.** Mounting rows: `presets\zabz\agent.cordis.yml:418-550` — disable a `mcp-*` row and the tool schemas vanish from every request's fixed prefix. There is no per-tool allowlist knob in the mounted rows (only `serverName`, `transport`, `command/args`, `cwd`, `toolCallTimeoutMs`, `failOnStartupError`).

**Capability risk of changing it: small.** Dropping `firecrawl` (27 tools, 39 770 chars ≈34 % of all MCP schema bytes) removes a duplicate of web search/fetch/crawl; `jina` and `fetch` overlap heavily with each other and with builtin `web_search`/`web_fetch`; `context7` is 2 tools for library docs. `secretary` (14 tools, 7 950 chars) is the company bridge and should stay.

---

## (e) ALWAYS-ON INSTRUCTION BLOCK vs REAL WORK

**Knobs.** Persona: `presets\zabz\agent.cordis.yml:17-131` (the `persona.prefix` block, ends with a duplicated "Read `~/code/personal-secretary-mvp/docs/secretary-replacement-audit/`…" line at `:131` that also appears at `:109`). Workspace instructions: `agent.cordis.yml:133-136` `agent-instructions.maxBytes: 65536` (shipped default requires the key, `dsh-agent-instructions\lib\index.js:28`; truncation and an "omitted or truncated to fit" notice are implemented at `:116-123, :249-254`).

**Measured.** `_m06/msgshape.py` / `batch.py`:
- `system/message` text = **24 888 chars** on every session sampled (`system_chars` identical across all 8 recent sessions) — one text block. **ESTIMATE ≈6 222 tokens** at 4 chars/token; against the measured 3.9 chars/token divisor from (d) it is ≈6 382.
- First `assistant/message` usage (fresh session, first user message ≈210 chars):

| session | first inputTokens | first cacheReadTokens | first totalTokens | requests | session cumulative charged tokens |
|---|---|---|---|---|---|
| `72feac5d` | 2 077 | 34 560 | 36 903 | 13 | 717 723 |
| `64681fe6` | 2 630 | 34 560 | 37 374 | 50 | 3 227 658 |
| `6810ace8` | 2 517 | 34 688 | 37 439 | 54 | 5 089 739 |
| `31a5456c` | 2 306 | 34 560 | 37 145 | 26 | 1 741 821 |
| `17fbe1d9` | 2 420 | 34 560 | 37 182 | 81 | 8 483 403 |
| `session-e34dd061` | 1 248 | 36 864 | 40 048 | 105 | 20 741 532 |

**Finding.** The always-on block costs **≈36–38k tokens on the first request** (24 888 chars of instructions + 110 850–118 828 chars of tool schemas + the user turn), and the first assistant message is ≈36 903–40 048 `totalTokens`. As a share of the session: 36 903 / 717 723 = **5.1 %** for a 13-request session, but 40 048 / 20 741 532 = **0.19 %** for the 105-request session. The instruction block is therefore **not** where session money goes — repeated tool output is (b). It is the *fixed floor per request*, and it matters as `requests × prefix`.

**Capability risk of changing it: none/small** for the persona text (it is prompt content only); **small** for `agent-instructions.maxBytes` (lowering it silently drops AGENTS.md content, announced only by the marker text at `dsh-agent-instructions\lib\index.js:116`).

---

## (f) MODEL TIER ROUTING — 100 % `deepseek-flash`; titling is on the cheap tier

Counts from `request/context.data.model` and `request/header.data.header.config` across the 60 newest sessions (`_m06/routes.py`, size ≤1.5 MB):

```
request/context model counts: {"deepseek-flash": 57}
request/header config variants:
  x49 {"provider":"deepseek-official","model":"deepseek-flash","reasoningEffort":"high","maxTokens":256000}
  x12 {"provider":"deepseek-official","model":"deepseek-flash","maxTokens":256000,"reasoningEffort":"high"}
```

**`deepseek-v4-pro`: 0 requests.** Not reachable from settings either: `base.yaml:58-60` and `C:\Users\ezabz\.dsh\settings.yaml:7-9` both pin `agent-default-model.model: deepseek-flash`; `base.yaml:34-57` records that Pro was tried and reverted. The only other configured family is the DeepSeek-on-DeepInfra pi-ai twin (`base.yaml:104-114`), mounted dormant.

**Titling.** `session-title-llm` is bound to `dsh-session-title-first-prompt-llm` (`dsh-base\cordis.patch.yml:55-62`: `targetWords 5, maxInputBytes 4096, maxOutputTokens 64, timeoutMs 60000`); the older `dsh-session-title-llm` package exists but is not the mounted provider. Every `session/title-llm-request` observed carries `route: {provider: deepseek-official, model: deepseek-flash}` (`_m06/routes.py`, 9 sessions; e.g. `session-e34dd061`). Bounded to 4 096 input bytes and 64 output tokens ⇒ worst case ≈1 024 input + 64 output tokens — **the cheap tier, not the expensive one**. Titling fires once per top-level session (absent in all subagent sessions sampled).

**Capability risk of changing it: none.** A route is data (`llm-deepseek` settings section); changing it needs no code.

---

## (g) CROSS-SESSION DUPLICATION — the prefix cache IS shared across sessions

**Answer: shared.** On a freshly created session the FIRST request already reports a large `cacheReadTokens`, i.e. the fixed prefix (system + 110–124 tool schemas) was a cache hit even though this session had never sent it. Sample of 6 recent sessions, first `assistant/message` (`_m06/batch.py`):

| session | first inputTokens (miss) | first cacheReadTokens (hit) | hit share of prompt |
|---|---|---|---|
| `72feac5d-2561-450b-8619-c8714027b330` | 2 077 | 34 560 | 93.9 % |
| `64681fe6-37f0-45af-b445-1a3d36f84f76` | 2 630 | 34 560 | 92.9 % |
| `6810ace8-abf0-4c2e-abf3-1754ba837bd7` | 2 517 | 34 688 | 93.2 % |
| `31a5456c-5de1-4584-9e72-175d7052a6a2` | 2 306 | 34 560 | 93.7 % |
| `17fbe1d9-f803-4768-bb56-267db699a4f1` | 2 420 | 34 560 | 93.5 % |
| `session-e34dd061-3b51-41b1-aa7e-a66bfc5d4ce0` | 1 248 | 36 864 | 96.7 % |

**Cold counter-example (proves the reading is real, not an artefact).** `session-24e68280-a452-41b3-8f82-542a4524f8f3` first request: `input 35 910, cacheRead 1 664` — 95.6 % MISS. Its very next requests are hits: `(655, 37 760)`, `(5 088, 38 656)`. So a first request *can* miss the whole prefix; the six above are genuinely shared hits, and the difference is cache residency, not a fixed property of "first request".

**Consequence.** Concurrent/subagent sessions do **not** each pay full price for their own copy of the shared prefix — they pay ~93–97 % of it at cache-read price. Aggregate over the 8 recently scanned sessions: 4 311 335 cache-read tokens vs 344 581 input (miss) tokens, i.e. **92.6 % of all input was cache hits**. The multiplier that survives this is not prefix duplication; it is the *repeated tool output inside each session* (b), which is also cache-read but re-charged every turn.

**Capability risk of changing it: none** (nothing is configurable here; it is provider-side prefix caching plus DSH's stable request shape — `dsh-base\cordis.patch.yml:307-309` and `presets\zabz\agent.cordis.yml:208` both keep the tool catalog unchanged across modes explicitly "for request-cache stability").

---

## Ranked multipliers

1. **Tool output re-sent every turn — 83–96 % of prompt tokens** (measured, (b)). The knobs that bound it (`maxInlineBytes 50000`, `thresholdChars 8192`) are generous and the pruner only fires at 80 % of the context window.
2. **The 122-tool catalog in every request's fixed prefix — 117 176 chars ≈ 29 294 tokens, 74.9 % of it MCP** (measured, (d)); `firecrawl` alone is 39 770 chars.
3. **`inputTokens` that never hit cache — retries (3× input worst case) and cold prefixes** (measured cold example 35 910 miss tokens; retry multiplier measured at 1/101 requests). This is the only path where the expensive line item is charged at full price rather than cache-read.
