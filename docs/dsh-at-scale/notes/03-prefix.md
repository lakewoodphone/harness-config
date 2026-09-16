# 03 — What DSH puts at the START of every model request

Audit host: `ZABZ-YOGA` (Windows). DSH checkout
`C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\`.
Primary evidence: real session logs under `C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--\`
(multi-frame zstd; decompressed with `zstandard.ZstdDecompressor().stream_reader(fh).read()`).

All token figures are **ESTIMATES**. DeepSeek's tokenizer is not installed and no
`tiktoken` is present (`python -c "import tiktoken"` → ModuleNotFoundError). Estimator:
**calibrated 3.91 chars/token**, derived by measurement, not a guess — see §A.3.

---

## 0. Measured summary (this deployment)

| element | exact chars (measured) | tokens (EST, ÷3.91) | where it sits |
|---|---|---|---|
| tool schema block, 110 tools | **110,850** (`len(json.dumps(tools))`, compact: 105,983) | ~28,350 | front of the request, inside the prefix |
| tool schema block, 122 tools (same session, earlier) | 117,420 | ~30,030 | " |
| rendered system prompt (subagent sessions) | **24,888** | ~6,365 | `messages[0]` |
| rendered system prompt (session-b60e96b3, top-level) | **21,373** | ~5,466 | `messages[0]` |
| — of which deployment/preset persona | **17,915** | ~4,582 | inside the system prompt |
| — of which harness identity | 52 | ~13 | section order −1000, first char of prompt |
| agent-instructions message (`AGENTS.md` files) | **58,689** | ~15,010 | user message at seq 117, inside prefix |
| runtime-context snapshot (sandbox/approval policy) | 390 | ~100 | user message, appended when it changes |
| skill catalog | 1,460 | ~373 | user message at seq 10, inside prefix |

First request of session-b60e96b3: 138,793 prefix chars (tools 117,420 + system 21,373)
→ estimate ~35,500 tokens; **measured** `prompt_tokens` for that request = 36,301
(`inputTokens 32973 + cacheReadTokens 3328`). The estimate is within ~2% — estimator validated.

---

## A. The always-on instruction block

### A.1 Exact size, by measurement

The rendered system prompt is appended to the session surface as a single
`system/message` event and is therefore *in* the log verbatim:

`dsh-agent-loop/lib/index.js:1019-1027`
```js
const commits = this.systemPrompt.project(renderedPrompt, {
    inHistory: preparedCall?.systemPromptUpdate === "in-history",
    startsSeries: ... });
for (const { message, intent } of commits) this.session.append("system/message", {
    turn, step, message }, intent);
```

Measured from the log (one `system/message` event per session):

| session | seq | chars |
|---|---|---|
| `session-b60e96b3-6a48-4898-a770-bc9eb576b9ce` | 7 | 21,373 |
| `64681fe6-37f0-45af-b445-1a3d36f84f76` (subagent of the same parent) | — | 24,888 |
| `31a5456c-…`, `d7ce1f35-…` (sibling subagents) | — | 24,888 |

The preset persona prefix is 17,915 chars, measured off the live preset with PyYAML:
`harness-config/presets/zabz/agent.cordis.yml` row `id: persona`,
`name: '@deepseek-ai/dsh-persona'`, `config.prefix` = **17,915 chars**,
`config.suffix` = 34 chars (`Your working directory is {{cwd}}.`).
Row: `harness-config/presets/zabz/agent.cordis.yml:17-21` (the file the parent
identified as the live preset, `LastWriteTime 9/15/2026 11:07:47 PM`, 38,976 bytes).

Verbatim head and tail of the 21,373-char message:
```
You are an AI agent powered by DeepSeek Harness.

You are Zabz — Eliyahu's chief executive, engineer, researcher and chief of staff. …
…
… Do not start a replacement server unless the user asks; if one is needed, use a
managed background job and verify its exact URL.

Your working directory is C:\Users\ezabz\code.
```

### A.2 Static vs per-session vs per-request

* **Per request: nothing.** Across 66 requests (`request/header` events) in session
  b60e96b3 there is exactly **one** `system/message` event → the rendered prompt was
  byte-identical for the whole session, including across 2 resumes.
* **Per session: the `{{cwd}}` interpolation** (40 chars in this run) and the
  composition (top-level vs subagent: 21,373 vs 24,888 chars — head and tail identical,
  so the +3,515 chars are extra middle sections in the subagent composition).
* Everything else is static: harness identity (`dsh-system-prompt/lib/index.js:216`),
  the persona text, the per-tool sections and the WEB_SURFACE section.
* The instruction-file message (58,689 chars, `AGENTS.md` aggregation) is static for the
  life of the session as long as those files do not change.

### A.3 The estimator, stated and calibrated

`len(text)//4` would give 5,343 tokens for the 21,373-char prompt. Instead the ratio was
*measured*: for two independent sessions, summing `len(json.dumps(tools)) + system-message
chars + user-message chars` and dividing by the API-reported prompt tokens:

| session | prefix chars | prompt tokens (total − output − reasoning) | chars/token |
|---|---|---|---|
| 64681fe6 | 145,479 | 37,190 | 3.91 |
| 31a5456c | 144,164 | 36,866 | 3.91 |

`usage` fields come from `assistant/message` events; the adapter documents that
`prompt_tokens` includes cache hits (`dsh-llm-deepseek/lib/index.js:1146-1160`).
So 3.91 chars/token is exact for this corpus; every token number above is derived with it
and labelled ESTIMATE.

---

## B. Elements inside the prefix that can change between two consecutive requests

Ranked by likelihood of actually breaking DeepSeek's prefix cache.

### B1. The tool list — HIGHEST REAL RISK (measured, it already happened)

MCP tools are registered **asynchronously** after connect, and re-synced on a server
notification, so the tool array is not fixed at session start:

`dsh-mcp-client/lib/index.js:770-787`
```js
async function apply(ctx, config) {
    ...
    const outcome = await connection.ready;
```
`dsh-mcp-client/lib/index.js:632`
```js
generation.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
```
`dsh-mcp-client/lib/index.js:151,171`
```js
async function syncTools(client, ctx, opts, previous) { ...
    for (const [publicName, definition] of definitions) disposers.set(publicName, ctx.tools.register(definition));
```

Measured consequence in **one** session (b60e96b3), tool count per `request/header`:
`122 → 108 → 110`, changing exactly at the two `resume` boundaries.
Tool names lost: 14 `mcp__secretary__ps_*` (`ps_health`, `ps_db_query`, `ps_action`, …);
names gained: `mcp__playwright__browser_webmcp_call`, `mcp__playwright__browser_webmcp_list`.
Within one process run it never changed: across 63 consecutive `series` headers there are
**zero** `change` headers (`buildRequest` logs one on any difference —
`dsh-agent-loop/lib/index.js:1176-1190` — and `headerEquals` compares config, adapter
defaults and every tool schema in order, `dsh-session/lib/index.js:533-538`).

Because tools are the *front* of the prompt, a change here re-bills everything after the
first differing tool. Measured: the common tool-JSON prefix between the 122-tool and
110-tool lists is **74,158 of 117,420 chars** — i.e. ~36k chars in front of the
divergence are unchanged, everything after is new — except that in a *new* request the
prompt is rebuilt, so the tail of the old prefix is gone regardless.

### B2. Compaction / tool-result pruning — HIGH, and it happens routinely

The pruner rewrites already-sent history in place:

`dsh-compaction-tool-result-pruner/lib/index.js:174`
```js
surfaceOp: { op: "replace", startSeq: seq, endSeq: seq }, sourceEventSeqs: [seq]
```
14 `compaction/prune` events plus 3 full compactions in session b60e96b3 (turns 29, 41, 64;
`compaction/prune` data: `{"shadowedSeqs":[18],"shadowedTokenCount":2833}`,
`{"shadowedSeqs":[6059]}`, `{"shadowedSeqs":[7186],"shadowedTokenCount":10617}`, …).
Each prune makes the next request diverge at the earliest replaced seq → every token
after that point is re-sent uncached. This is the single largest recurring cache cost in
long sessions, and it is a *design* cost, not a bug.

### B3. The system prompt itself changing mid-session — MEDIUM

`dsh-agent-loop/lib/index.js:266-284` (`SystemPromptProjection.project`): with
`inHistory: true` and a continuing series, a *changed* prompt is **appended** as a new
system message (`{ message: createSystemMessage(rendered), intent: { surfaceOp: "append" } }`),
and the head is only rewritten when `input.startsSeries` is true. So a prompt change
mid-series is prefix-safe (it lands after the history); a prompt change *plus* a new
series (resume, tool change — `toolsChanged()` at `dsh-agent-loop/lib/index.js:909-917`
forces `startsSeries`) rewrites the head → full prefix invalidation.
Observed: 1 system/message in 66 requests, so it did not fire in that session.

### B4. Session-varying identifier in the request — NOT in the prompt (verified)

`dsh-agent-loop/lib/index.js:1211-1217` puts `sessionId` on the internal request object,
but the wire body is built at `dsh-llm-deepseek/lib/index.js:1764`
(`JSON.stringify({...body, ...extensions.fields})`) and `serializeRequest`
(`:258-266`) emits only `model, messages, stream, stream_options, thinking,
reasoning_effort, tools, temperature, max_tokens, stop`. `sessionId` reaches only the
extension registry (`:1757`). The one registered extension is inert: the base composition
mounts `@deepseek-ai/dsh-session-log-deepseek` with no config
(`dsh-base/cordis.patch.yml:36-37`) and its `apply` returns unless `config.enabled === true`
(`dsh-session-log-deepseek/lib/index.js:118`). So no session id, no per-request nonce, and
no randomness reaches the prompt.

### B5. Timestamps / clock in the prefix — NOT MOUNTED HERE

`dsh-time-context` exists in the checkout and injects a changing clock reading, but it does
so as a **user message appended to the step** (not the prefix) —
`dsh-time-context/lib/index.js:229-246`
```js
return { ...decision, messages: [...decision.messages, createUserMessage({ content: [{type:"text", text}], ...
```
and its text is `Time sampled while preparing turn N, step M: 2026-…` (`:144-149`).
It is **not** in the live composition: `dsh-base/cordis.patch.yml` has no `time-context`
row, the preset has none (39 rows: persona, agent-instructions, 4 tools, goal, plan-mode,
compaction×3, delegation×5, workflow, ralph, ask-user, todo, web, cordis, skill×2, present,
7× mcp-client), and no `user/message` in the sample session carries `source.plugin ===
"time-context"`. Same verdict for `dsh-launch-environment` (pure env resolver, no prompt
API at all — `dsh-launch-environment/lib/index.js:1-82`) and `dsh-shell-env` (mounted at
`dsh-base/cordis.patch.yml:243` but registers no `systemPrompt` contribution).

### B6. Skill catalog — LOW (append-only)

Emitted as a user message: `dsh-tool-skill/lib/index.js:4` imports `createUserMessage` and
the catalog is a durable session catalog; in b60e96b3 it is one message at seq 10 (1,460
chars). Re-emission goes through
`dsh-agent-loop/lib/index.js:1028` — `this.session.append("user/message", message, { surfaceOp: "append" })`
— so a mid-session catalog change adds tokens at the tail, it does not rewrite the head.
(No `skill-catalog` re-emission occurs in b60e96b3; later sessions show 5.)

### B7. Ordering — deliberately deterministic (no risk)

Section order is an explicit table (`dsh-system-prompt/lib/index.js:10-42`:
HARNESS_IDENTITY −1000 → DEPLOYMENT_PERSONA_PREFIX 0 → tool sections 1000-2900 →
HARNESS_SOURCE 10000 → WEB_SURFACE 10100 → DEPLOYMENT_PERSONA_SUFFIX 10200), sections
within an order are sorted by name (`:96-98`), and with no `toolOrder` configured the
whole tool array is sorted by code-unit name comparison (`:84`, `:92-102`) — identical on
every machine. Good news: the tool block is a *sorted* list, so a single added/removed
tool does not shuffle the rest.

---

## C. Tool schema block size (measured from the real `request/header`)

Last `request/header` of `session-b60e96b3-…` — event data keys `["header","reason"]`,
`header` keys `["config","adapterDefaults","tools"]`:

* tools: **110**
* `len(json.dumps(header["tools"]))` = **110,850 chars**; with separators `(",",":")` = 105,983
* ESTIMATE: **~28,350 tokens** (110,850 / 3.91)

By source (last header):

| source | tools | chars |
|---|---|---|
| builtin (no `mcp__` prefix) | 27 | 29,399 |
| `mcp__firecrawl__` | 27 | 39,770 |
| `mcp__playwright__` | 26 | 18,410 |
| `mcp__jina__` | 22 | 14,265 |
| `mcp__fetch__` | 6 | 4,121 |
| `mcp__context7__` | 2 | 4,665 |
| `mcp__secretary__` | **0** | 0 |
| **total MCP** | **83** | 81,231 |

Note the asymmetry with the task brief: ~97 MCP tools were expected, 83 were present at
the end of this session and 97 at its start (122 total). The `mcp__secretary__` server
contributed 14 tools at seq 11 and **zero** at the end — the largest single schema
difference in the session. Biggest single schemas: `mcp__firecrawl__firecrawl_search`
5,887 chars, `pwsh` 4,532, `workflow` 4,137, `firecrawl_crawl` 4,105, `firecrawl_scrape` 3,959.

**Inside the cacheable prefix, and at its front.** Three independent lines of evidence:
(a) `tools` is a top-level field of the same request body, serialized ahead of everything
except `model`/`messages` (`dsh-llm-deepseek/lib/index.js:1764`), and DeepSeek renders tool
schemas into the prompt before the conversation; (b) the loop treats the tool array as part
of the request *header* that must be byte-equal from step to step
(`canonicalHeader`/`headerEquals`, `dsh-session/lib/index.js:515-538`); (c) quantitatively —
for a session's **first** request, measured `cacheReadTokens = 34,560` while the whole
prompt was 36,866–37,190 tokens. The system prompt alone is only ~6,365 tokens; tools +
system = 28,350 + 6,365 = 34,715 ≈ the 34,560 that were served from cache. The cached
block *is* tools + system prompt.

---

## D. `request/header` shape, and what `in-history` means

Representative event (`request/header`, seq 11, `reason: "initial"`; later ones add
`startsSeries: true` when a new series begins):

```
data keys        : ["header", "reason"]            (+ optional "startsSeries")
data.header keys : ["config", "adapterDefaults", "tools"]
config           : {"provider":"deepseek-official","model":"deepseek-flash",
                    "maxTokens":256000,"reasoningEffort":"high"}
adapterDefaults  : {"reasoningEffort":true,"maxTokens":true}
tools            : [110 tool schemas]              # 110,850 chars
```
Other reasons observed in the same session: `series` ×63 (header re-logged because a new
request series started, content unchanged), `resume` ×2 (process restart).
**No `change` event ever occurred** — the config and tool block were byte-stable for the
whole run (`canonicalHeader` + `headerEquals`).

The matching `request/context` event (seq 12):
```json
{"provider":"deepseek-official","model":"deepseek-flash",
 "contextWindow":1000000,"systemPromptUpdate":"in-history"}
```

**The system prompt is NOT in the header.** It is sent in-history:

1. The adapter's `serializeRequest` prepends a `system` field *if the harness sets one*
   (`dsh-llm-deepseek/lib/index.js:258-266`), and the agent loop sets none — its request
   object is `{...header.config, messages, tools, sessionId, signal}`
   (`dsh-agent-loop/lib/index.js:1211-1217`). There is no `system` key anywhere in the
   header (`header` has exactly `config`, `adapterDefaults`, `tools`).
2. `in-history` is the route capability that tells the loop to commit the rendered prompt
   as a **durable `system/message` event in the session surface**
   (`dsh-agent-loop/lib/index.js:1019-1020`), which is exactly what we observe: 1
   `system/message` at seq 7, source `{"kind":"plugin","plugin":"@deepseek-ai/dsh-system-prompt"}`.
3. That event is re-sent at the front of every request: `deriveEventMessage` maps
   `system/message` → `event.data.message` in surface order
   (`dsh-session/lib/index.js`, `deriveEventMessage`), and `session.deriveMessages()`
   feeds `messages` for every step (`dsh-agent-loop/lib/index.js:1204`, `:1213`).
   Position: seq 7 is the first surface node, so `messages[0]` is the system prompt —
   before the user message (seq 8), the runtime-context snapshot (seq 9), the skill catalog
   (seq 10) and the 58,689-char instructions message (seq 117).

So "in-history" = *the system prompt is a message in the conversation history, re-sent at
the front on every request, and updated by appending a new system message when it changes
rather than mutating the head* (see B3).

---

## E. Is the prefix stable, and is it cached across sessions?

### E.1 Within one session: stable, and the cache is being hit

Session b60e96b3, 66 requests / 67 turns:

* 1 `system/message` (never rewritten, across 2 resumes).
* 0 `change` headers; the only header deviations coincide with `resume`.
* Measured cache behaviour (`assistant/message.usage`, DeepSeek's
  `prompt_cache_hit_tokens` mapped at `dsh-llm-deepseek/lib/index.js:1155`):

| request | prompt tokens | cache read | uncached |
|---|---|---|---|
| 1st (seq 16) | 36,301 | 3,328 | 32,973 |
| 2nd (seq 23) | 40,384 | 36,480 | 3,904 |
| last (seq 9,917) | 332,451 | 332,288 | 163 |

From request 2 onward ≥90% of the prompt is served from cache, and at the end 99.95%.

### E.2 Across concurrent sessions: the prefix IS shared — it is not per-session

The three sibling sessions on this machine (`64681fe6` — my parent — `31a5456c`,
`d7ce1f35`, all with 110 tools) were compared byte-for-byte:

* system prompt common prefix = **24,888 of 24,888 chars** (identical)
* tool-block JSON common prefix = **110,850 of 110,850 chars** (identical)
* each of them, on its **first request ever**, reported `cacheReadTokens = 34,560` of
  ~36,866–37,190 prompt tokens — i.e. ~94% of a brand-new session was served from cache
  built by another session.

The ~3.4k-token remainder is that session's own user message + runtime context. The cache
is keyed on the prompt prefix, not on the session id, and nothing session-specific reaches
the wire body (§B4). Conclusion: **the ~34.7k-token block (tools + system prompt) is paid
once per *prefix generation* on this account, not once per session.**

### E.3 What is the first element that differs against a *different* session

Same machine, same preset, but an older run (`session-b60e96b3`, 122 tools, 21,373-char
prompt) versus the current subagent composition:

* system prompt: common prefix = **1,537 chars** of 24,888 — the divergence is inside the
  deployment persona text, so the whole 24,888-char system prompt after char 1,537 is
  uncached for whichever side loses the race.
* tool JSON: common prefix = **74,158 chars** of 110,850–117,420 — divergence at the first
  tool name that differs (the tool list is name-sorted), everything after that is re-sent.

So the first thing that differs between two different-composition sessions is the
**system-prompt body (persona)**; the first thing that differs when only the tools differ
is the **first differing tool schema, ~74k chars into the tool array**.

Practical consequence: any edit to the preset persona, or any change in which MCP servers
answer, silently costs ~34k uncached tokens in the next session — once per generation,
and every session that starts after the change pays for its own divergent tail. Multiple
sessions sharing a generation (the sibling case) pay it once.

---

## F. What could not be determined

* Whether DeepSeek's server places the rendered tools before or after the system message
  inside the prompt is provider-side and not observable from DSH; the token arithmetic in
  §C shows only that both are inside the cached block.
* Exact token counts: no DeepSeek tokenizer available locally; all token figures are
  ESTIMATES from the calibrated 3.91 chars/token ratio.
* The cause of the 21,373 → 24,888 char system-prompt change between session-b60e96b3 and
  the later sessions was not isolated (both were measured, neither preset revision was
  diffed against a git commit). `harness-config` is a git repo; that diff is the next step
  if the size of that change matters.
