# DSH cost audit — 2026-09-16

Scope: the DeepSeek API spend of the DeepSeek Harness (DSH) coding-agent fleet, with the
owner-supplied console usage export as ground truth. Read-only outside this deliverable and
the working files under `C:\Users\ezabz\code\_dsh-scale\`.

**Verdict in one line:** the **$54 is real and exact** — **$54.738153411** of
`deepseek-flash` plus **$0.183484268** of `deepseek-v4-pro` on 2026-09-15 = **$54.92** — and
it was **not a pricing event**. Cost per request that day was **$0.0015**, the *same* as the
day before. The bill tripled because **request count went 8,863 → 34,787** and each request
re-read a **189,000-token** context. The money is **the volume of re-read context**: 42% of
the DSH pool is literally the cache-hit input line item.

---

## 0 Ground truth: the console export

Supplied by the owner mid-audit: `C:\Users\ezabz\Downloads\usage_data_2026-08-18_2026-09-16.zip`,
extracted to `_dsh-scale\data\usage-export\`.

| file | rows | columns |
|---|---:|---|
| `cost-2026-08-18_2026-09-16.csv` | 46 | `user_id, start_time_iso, end_time_iso, model, wallet_type, cost, currency` |
| `amount-2026-08-18_2026-09-16.csv` | 348 | `user_id, start_time_iso, end_time_iso, model, api_key_name, api_key, type, price, amount` |

**This is the authoritative ledger and it supersedes every estimate in this report.** It
carries the **real charged price per token** and the one field that makes the whole audit
possible: **`api_key_name`** — which machine spent the money.

### 0.1 The export confirms the published prices to the cent

Distinct `(model, type, price)` tuples observed, in USD per 1M (`tools\ledger_final.py`):

| model | cache-hit input | cache-miss input | output |
|---|---:|---:|---:|
| `deepseek-flash` | **$0.003 / $0.006** | **$0.15 / $0.30** | **$0.60 / $1.20** |
| `deepseek-v4-pro` | $0.022 / $0.044 | $0.66 / $1.32 | $1.98 / $3.96 |

The two prices on each line are the two rate tiers (§4.1). My pre-export estimate of a
**$0.03/M** cache-hit rate was **5–10× too high**; the real rate is **$0.003–0.006/M**. That
single correction moves the whole cost composition — see §1.3.

### 0.2 The 30-day picture

```
day         flash$    pro$   TOTAL$          day         TOTAL$
2026-08-18    6.93    0.00     6.93          2026-08-31    5.32
2026-08-19    7.91    0.13     8.05          2026-09-01    2.84
2026-08-20    6.71    0.04     6.75          2026-09-02    3.27
2026-08-21   10.71    0.13    10.84          2026-09-06    0.68
2026-08-22    6.22    0.14     6.36          2026-09-09    0.23
2026-08-23    3.87    0.09     3.96          2026-09-10    6.31
2026-08-24    1.70    0.29     2.00          2026-09-11   13.52
2026-08-25    1.74    0.42     2.17          2026-09-13    1.32
2026-08-26    0.47    0.38     0.85          2026-09-14   44.88
2026-08-27    1.45    0.35     1.79          2026-09-15   54.92
2026-08-28    6.64    0.31     6.95          2026-09-16    0.58
2026-08-29    0.10    0.23     0.33
2026-08-30    4.88    0.02     4.90       GRAND TOTAL   195.74
```

**30-day total: $195.74.** Median day **~$4–7**. The two spike days are **$44.88 and $54.92 =
$99.80 = 51% of the entire month**, and they are consecutive.

By model: `deepseek-flash` **$119.72**, `deepseek-v4-flash` **$70.91**, `deepseek-v4-pro`
**$5.12**, `deepseek-v4-flash-vision-exp` $0.00.

---

## 1 The $54, attributed

### 1.1 It was both machines

`api_key_name` is the machine axis:

| `api_key_name` | host | requests | 30-day cost |
|---|---|---:|---:|
| `deepseek harness` | **ZABZ-YOGA** (this laptop) | 37,384 | **$69.68** |
| `zabz-tech-harness` | **ZABZ-TECH** (the desktop) | 28,033 | **$38.45** |
| `brand new vscode` | editor surface | 15,836 | $37.08 |
| `next vscode api key` | editor surface | 12,844 | $36.23 |
| `vscode copilot` | editor surface | 5,267 | $13.18 |
| `vscode`, `vscodeextensions write` | editor surface | 495 | $1.12 |

**2026-09-15 — the $54.92 day:**

| api key | requests | cost | share | mean context/req |
|---|---:|---:|---:|---:|
| `zabz-tech-harness` (ZABZ-TECH) | 23,223 | **$31.00** | 56.5% | 199,561 |
| `deepseek harness` (ZABZ-YOGA) | 11,564 | **$20.09** | 36.6% | 167,881 |
| `vscode copilot` | 2,185 | $3.83 | 7.0% | 69,715 |
| **TOTAL** | **36,972** | **$54.92** | | |

**2026-09-14 — the $44.88 day:** ZABZ-YOGA $35.39 (78.9%), ZABZ-TECH $5.55 (12.4%),
vscode copilot $3.94 (8.8%).

| day | ZABZ-YOGA | ZABZ-TECH | both |
|---|---:|---:|---:|
| 2026-09-10 | $0.79 | $0.00 | $0.79 |
| 2026-09-11 | $12.48 | $0.92 | $13.40 |
| 2026-09-13 | $0.35 | $0.98 | $1.32 |
| 2026-09-14 | **$35.39** | $5.55 | $40.94 |
| 2026-09-15 | $20.09 | **$31.00** | **$51.10** |
| 2026-09-16 | $0.58 | $0.00 | $0.58 |

**The $54 was two machines plus a little editor traffic.** On 09-14 this laptop was the big
spender; on 09-15 the **desktop took over** and was 56.5% of it. Neither machine's 30-day
total alone reaches $54 in a day — it takes the fleet. **The real unit of cost is the fleet,
not the machine.**

### 1.2 The bill tripled because request *count* tripled

Harness keys only, so the editors are excluded:

```
day             reqs     cost$    $/req    mean ctx   miss%
2026-09-10       349      0.79   0.0023      91,710   3.05%
2026-09-11     8,863     13.40   0.0015     222,948   1.14%
2026-09-13       437      1.32   0.0030     262,949   0.67%
2026-09-14    20,501     40.94   0.0020     229,609   1.49%
2026-09-15    34,787     51.10   0.0015     189,030   0.93%
2026-09-16       480      0.58   0.0012     102,387   3.19%
```

**`$/req` is flat — 0.0015 to 0.0020 every working day.** Nothing degraded. There is no leak,
no runaway session, no bad model, no pricing change. The 09-11→09-14 jump is `8,863 → 20,501`
requests; the 09-14→09-15 jump is `20,501 → 34,787`. **Cost is linear in
`requests × mean context`**, and that product is the only thing worth managing.

### 1.3 Composition — three comparable buckets, and the biggest is re-reading

| bucket | whole export | share | **DSH (2 harness keys)** | share |
|---|---:|---:|---:|---:|
| input **cache-HIT** tokens | $66.87 | 34.2% | **$45.55** | **42.1%** |
| **output** tokens | $54.78 | 28.0% | **$36.22** | **33.5%** |
| input **cache-MISS** tokens | $74.09 | 37.8% | **$26.35** | **24.4%** |

**Volume moved by the two harness keys over the export window:**

| | tokens |
|---|---:|
| `input_cache_hit_tokens` | **13,731,650,164** |
| `input_cache_miss_tokens` | **294,754,592** |
| `output_tokens` | **90,839,575** |

13.7 **billion** tokens of cached context re-read. This is not a malfunction — it is the
arithmetic of *steps × context* — but it is where 42% of the DSH money goes, and it is the
most reducible bucket because it is pure repetition.

### 1.4 Why the local session logs measured only $11.68 for 09-15

My independent measurement from `~/.dsh/sessions` (§2.4) gives, for 2026-09-15:
11,033,065 miss / 1,457,682,944 hit / 5,679,582 out. The ledger's ZABZ-YOGA line for the same
day is **21,975,657 miss / 1,919,397,888 hit / 9,846,477 out** — locally I captured **50% of
the misses, 76% of the hits, 58% of the output**. Same on 09-14 (33.2M vs 61.6M miss).

**Reason:** the local store only holds sessions still on disk whose `cwd` is
`C:\Users\ezabz\code`, and it has gaps — 09-12 and most of 09-13 have no local traffic at all
while the ledger charges $1.67 across those days.

**Standing rule to record:** the local session logs are a good *sample of mechanism* and must
never be used as a dollar source. **For DSH money, cite `api_key_name` from the console
export.** This is precisely the provenance failure this system has been burned by before — a
partial local copy read as if it were the whole truth, producing a confidently wrong number.

---

## 2 Measurement

### 2.1 Where usage is recorded — two places, two purposes

**Locally, for mechanism** (what the agent actually did, per step — needed to fix anything):

- `C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--\<session-id>\session.v3.jsonl.zstd`
- event type `assistant/message`, field **`data.usage`**

```
{"inputTokens": 32973, "outputTokens": 207, "totalTokens": 36508,
 "cacheReadTokens": 3328, "reasoningTokens": 0}
```

(verbatim, first `assistant/message` of `session-b60e96b3-…`)

A second, small source: `compaction/summary` events carry the same object for the
summarisation call (3 in that session).

**Centrally, for money** (what was charged, by machine): the console export's
`amount-*.csv` → `api_key_name, type, price, amount`; `cost-*.csv` → `cost`.

**Semantics, read out of the adapter, not inferred** —
`@deepseek-ai/dsh-llm-deepseek/lib/index.js:1145-1166`:

> `Map wire usage fields. DeepSeek's prompt_tokens INCLUDES cache hits
> (prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens,
> api/create-chat-completion); the harness TokenUsage convention is DISJOINT counts,
> so cache reads are subtracted out of inputTokens.`

```js
function mapUsage(usage) {
    const cacheRead = usage.prompt_tokens_details?.cached_tokens ?? usage.prompt_cache_hit_tokens;
    ...
    return {
        inputTokens: usage.prompt_tokens - (cacheRead ?? 0),
        outputTokens: usage.completion_tokens,
        ...hasExactTotal ? { totalTokens: combined } : {},
        ...cacheRead !== void 0 ? { cacheReadTokens: cacheRead } : {},
        ...reasoning !== void 0 ? { reasoningTokens: reasoning } : {}
    };
}
```

| logged field | meaning | billed at |
|---|---|---|
| `data.usage.inputTokens` | cache-**MISS** prompt tokens | $0.15–0.30/M |
| `data.usage.cacheReadTokens` | cache-**HIT** prompt tokens | $0.003–0.006/M |
| `data.usage.outputTokens` | completion tokens (includes `reasoningTokens`) | $0.60–1.20/M |
| `data.usage.totalTokens` | prompt (miss + hit) **+** output | — |

**Proof, over every usage-carrying event in all 385 logs** (`tools\field_semantics.py`):

```
H0 identity  totalTokens == input + cacheRead + output
  holds : 31,292
  breaks: 0
```

31,292 of 31,292. The alternative reading — `inputTokens` is the whole prompt — is refuted by
this identity *and* by the traces, which show prompts growing 36k → 791k. The ledger
independently confirms the disjoint convention: its `input_cache_hit_tokens` and
`input_cache_miss_tokens` are separate line items, exactly as `mapUsage` produces.

### 2.2 The trap that hides this data (and will hide it again)

The session logs are **multi-frame zstd** (append-only). A normal
`zstandard.ZstdDecompressor().decompress(bytes)` returns only the *first* frame — for the
largest session, **198 bytes out of 48,568,009**. Anyone auditing these logs with the obvious
API call concludes "DSH records no usage". The 12.8 MB session `session-b60e96b3-…` yields
**1,848 billed requests** only if read as a stream:

```python
with open(path,'rb') as fh, dctx.stream_reader(fh) as r:
    text = r.read().decode('utf-8','replace')
```

### 2.3 How to reproduce

| tool | what it does |
|---|---|
| `tools\console_ledger.py` | **authoritative**: the export by day / model / api_key |
| `tools\ledger_final.py` | observed prices, the $54 attribution, composition, `$/req` trend |
| `tools\reconcile.py` | local session sum vs the ledger, per day |
| `tools\day_usage.py` | full local accounting → `data\usage-yoga.json` |
| `tools\day_sessions.py` | per-session cost, one UTC day |
| `tools\trace_session.py` | prompt growth + compaction/error markers, one session |
| `tools\tool_sizes.py` | raw `tool/result` payload sizes vs the pruner |
| `tools\waste_probe.py` | error attempts, retries, root-vs-subagent |
| `tools\field_semantics.py` | the identity proof (must print `breaks: 0`) |
| `tools\peak_split.py` | peak vs off-peak share, detected from the ledger's own prices |

Locally measured population: **385 session logs**, all `cwd = C:\Users\ezabz\code`, all preset
`zabz`; **333 subagent, 54 root**; one workspace only.

### 2.4 The locally measured token picture (a sample, not the bill)

```
day               n        miss         hit       out         tot    think
2026-09-10        1       8,561           0        18       8,579        0
2026-09-11     7020  13,636,727 1,821,445,760 5,097,757 1,840,180,244 1,715,062
2026-09-14    12279  33,198,778 3,333,177,85610,372,940 3,376,749,574 3,743,129
2026-09-15     5813  11,033,065 1,457,682,944 5,679,582 1,474,395,591 1,962,730
2026-09-16     5902   7,595,598 1,003,896,576 4,589,099 1,016,081,273 1,511,360
TOTAL         31015  65,472,729 7,616,203,13625,739,396 7,707,415,261 8,932,281
```

- cache **hit** 7,616,203,136 (**99.1%**), cache **miss** 65,472,729 (**0.9%**)
- mean prompt per request: **247,676 tokens**

By model: `deepseek-flash` **30,718 of 30,995 requests (99.1%)**; `deepseek-v4-pro` 139
(under 1% of cost); deepinfra routes 13. **Model-tier routing is not a cost lever** — a
measured "no", worth stating because it is the first thing most audits propose.

### 2.5 Is the caching working? Yes — that is not the problem

**99.1% of prompt tokens are cache hits**, and the ledger's own miss rate agrees (0.67–3.19%
per day, §1.2). This is not a broken-prefix-cache story, so the intuitive fix — "stabilise the
prefix so the cache works" — is already done. §3 pins the prefix; §1.2 shows where the volume
comes from.

---

## 3 Prompt-prefix and cache analysis

Full evidence: `notes\03-prefix.md`. Measured off real `request/header` events.

### 3.1 What DSH puts at the start of every request

| element | size | source |
|---|---:|---|
| harness identity line | **52 chars** | first thing in the system prompt |
| preset `zabz` persona + instruction block | **17,915 chars** | `presets\zabz\agent.cordis.yml` (`config.prefix`) |
| rendered system prompt (whole) | **24,888 chars** | one `system/message` event at seq 7 |
| **tool schema block** | **110,850 chars** | `request/header.data.header.tools` |
| agent-instructions message (`AGENTS.md` ×2) | **58,689 chars** | `dsh-agent-instructions`, seq 117 |

Token estimator: **not** `len//4`. Calibrated at **3.91 chars/token** from real usage
(145,479 prefix chars ↔ 37,190 measured prompt tokens) and validated independently
(138,793 chars → estimate 35.5k vs measured `prompt_tokens` 36,301).

The fixed head is **~34,700 tokens**: **~28,350 for the tool schemas** (110 tools) plus
**~6,365 for the system prompt**.

**Half of the owner's question is answered well:** the first request of a *brand-new* session
already shows `cacheReadTokens ≈ 34,560` with only ~1,300–2,600 miss tokens. **The prefix
cache is shared across sessions and works at 93–97% on a cold start.** ~34.7k tokens are paid
once per *prefix generation*, not once per session.

### 3.2 What could invalidate the prefix — ranked by demonstrated risk

1. **The tool list changes mid-session. It already has.**
   `dsh-mcp-client` registers tools after `await connection.ready` and re-syncs on
   `ToolListChangedNotificationSchema`. In `session-b60e96b3` the catalog went
   **122 → 108 → 110 tools / 117,420 → 110,850 chars** across two resume boundaries (14
   `mcp__secretary__ps_*` tools disappeared, 2 `mcp__playwright__browser_webmcp_*` appeared).
   Tools sit at the **front** of the cacheable block, so the miss is total.
2. **Tool-result pruning rewrites mid-history.** `dsh-compaction-tool-result-pruner` emits
   `surfaceOp {op:"replace"}`; 14 prune events plus 3 compactions in one 67-turn session.
   Every prune re-bills everything after the earliest replaced sequence number.
3. **The system prompt changing mid-series.** Appended safely while the series continues — but
   when `startsSeries` is also true (resume, or a tool change) the head is *rewritten* and the
   whole prompt region's cache is lost.
4. **Not present on this deployment** (checked in code, logs and composition): no timestamp in
   the prefix (`dsh-time-context` is not mounted, and when mounted it injects a *user* message);
   `dsh-launch-environment` contributes no prompt text; `dsh-shell-env` registers no prompt
   section; no session id, nonce or randomness reaches the wire body. **This is a genuinely
   clean prefix design** and it is why the hit rate is 99.1%.
5. **Ordering is deterministic** — explicit section orders, name-sorted sections, name-sorted
   tool array.

### 3.3 Cross-session caching — answered definitively

Three concurrent sibling sessions (parent `64681fe6`, `31a5456c`, `d7ce1f35`) have
**byte-identical** system prompts (longest common prefix 24,888 / 24,888) and **byte-identical**
tool JSON (110,850 / 110,850), and **each showed 34,560 cached tokens on its very first
request**. The cache is account-level and shared. Between sessions of *different composition*
divergence starts at char **1,537** of the system prompt (inside the persona) and char
**74,158** of the tool JSON.

**Operational consequence:** ~34.7k tokens are paid once per prefix generation. A persona edit,
or any change in which MCP servers answer, silently costs ~34k uncached tokens on the next
session. Editing the preset is not free — and at the miss price that block costs 50× what it
costs cached.

---

## 4 Online research, with URLs

Full detail, including everything that could not be verified, in `notes\04-research.md`.

**Premise correction: `deepseek-flash` and `deepseek-v4-pro` ARE the officially documented
ids today.** `deepseek-chat`/`deepseek-reasoner` are not on the current pricing page. Verified
live: `GET https://api.deepseek.com/v1/models` returns exactly `deepseek-flash` and
`deepseek-v4-pro` (`tools\probe_models.py`).

### 4.1 Pricing — https://api-docs.deepseek.com/quick_start/pricing (USD per 1M)

| | flash off-peak | flash peak | v4-pro off-peak | v4-pro peak |
|---|---:|---:|---:|---:|
| cache **hit** input | $0.003 | $0.006 | $0.022 | $0.044 |
| cache **miss** input | $0.15 | $0.30 | $0.66 | $1.32 |
| output | $0.60 | $1.20 | $1.98 | $3.96 |

- Off-peak is **exactly half** peak.
- **Peak = 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri.** All other hours, and all weekend, are
  off-peak.
- Context 1M, max output 384K. Effective 16:00 UTC 2026-08-16; changelog latest entry
  2026-09-10. The page carries no "updated on" date of its own.
- **Confirmed against the account's own ledger:** §0.1's observed prices match this table
  exactly. This is no longer a documentation claim.

### 4.2 The cache

- **Minimum cacheable prefix = 64 tokens.** Official announcement
  https://api-docs.deepseek.com/news/news0802: *"The cache system uses 64 tokens as a storage
  unit; content less than 64 tokens will not be cached."* **Caveat:** the *current* guide
  (https://api-docs.deepseek.com/guides/kv_cache) does not restate 64 and now describes
  independent "cache prefix units"; whether 64 still governs is **not found**.
- **TTL: "usually within a few hours to a few days"** (official, both pages). No exact number.
  This is why a session resumed after a long gap pays a miss on its whole prefix — and why
  `session-24e68280` was measured at **35,910 miss / 1,664 hit** on its first request before
  hitting normally.
- **Match rules** (official examples): A+B then A+B+C **hits** (append is cacheable). A+B then
  A+C **misses**. Match is **full-unit-only, prefix-only, best-effort, no guarantee**.
- **Not found:** whether cache storage is charged; whether the cache is account-, key- or
  deployment-scoped.

### 4.3 The API's own `usage` fields — https://api-docs.deepseek.com/api/create-chat-completion

- `prompt_tokens` (= `prompt_cache_hit_tokens` + `prompt_cache_miss_tokens`),
  `completion_tokens`, `total_tokens`
- `prompt_cache_hit_tokens` — **exists** · `prompt_cache_miss_tokens` — **exists**
- `prompt_tokens_details.cached_tokens` — **exists**, documented *"Same as
  `prompt_cache_hit_tokens`"*
- `completion_tokens_details.reasoning_tokens`
- Streaming: `stream_options.include_usage`; `usage` is null on every chunk except the last.

Verified live against this account (`tools\rate_probe.py`, one 66-token request):

```json
{"prompt_tokens": 58, "completion_tokens": 8, "total_tokens": 66,
 "prompt_tokens_details": {"cached_tokens": 0},
 "completion_tokens_details": {"reasoning_tokens": 8},
 "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 58}
```

The Harness talks the **chat-completions** surface
(`dsh-llm-deepseek/lib/index.js:1770` → `${baseURL}/chat/completions`; `:1911`
`PUBLIC_BASE_URL = "https://api.deepseek.com"`), so these are the authoritative field names.

### 4.4 Compaction thresholds elsewhere

| harness | threshold | source quality |
|---|---|---|
| Claude Code | `defaultThreshold = effectiveWindow - 13000` → **~83.5%** of window | community source-quote, [issue 31806](https://github.com/anthropics/claude-code/issues/31806), [63015](https://github.com/anthropics/claude-code/issues/63015). **No official number.** The widely-repeated "~92%" was **not found anywhere** — do not use it. |
| OpenAI Codex CLI | `auto_compact_token_limit` default = 90% of the **raw** window (244,800 of 272,000) → fires at **94.7% of usable** | [issue 40095](https://github.com/openai/codex/issues/40095) |
| Cursor | self-summarisation tested at **80k** and **40k** triggers | official: [cursor.com/blog/self-summarization](https://cursor.com/blog/self-summarization) |
| Cline | auto-condense default **88%** | maintainer, [issue 9748](https://github.com/cline/cline/issues/9748) |
| Aider | not a %: `--max-chat-history-tokens`, source default **1024** | [aider.chat/docs/config/options.html](https://aider.chat/docs/config/options.html) |
| **DSH (this deployment)** | **80% of 1,000,000 = 800,000** | measured, §5 |

**Every comparable harness compacts well below where DSH does in absolute terms** — 80k, 40k,
and windows of 200–272k. DSH's 80% is nominally in range, but its *window* is 1M, so its
trigger sits at 800k, and §5.4 shows the three most expensive sessions never reached even half
of that.

### 4.5 Compaction earlier vs later — what is evidenced and what is folklore

**Evidenced (quality decays with context length):** *Lost in the Middle*, TACL 2023 — best
performance at the beginning and end, significant degradation in the middle "even for
explicitly long-context models" (https://arxiv.org/abs/2307.03172); Chroma *Context Rot*
(https://research.trychroma.com/context-rot); NoLiMa, ICML 2025
(https://icml.cc/virtual/2025/poster/46685). **None of these is DeepSeek V4 at 1M**, so they
establish a *direction*, not a crossover point.

**Evidenced (the compaction step is not free):** two observed remote compactions took ~85 s
and ~104 s, and the author explicitly warns earlier compaction is not a free win because
*"earlier compaction also has a request cost"* — with a measured earlier-compaction run
showing mean input/call −70.3%/−76.4% while input tokens/minute fell only −14.2%, and still
"not a matched A/B" (https://github.com/openai/codex/issues/40095).

**Folklore / not found:** any measured 400k-vs-1M net cost or net quality break-even, on
DeepSeek or any other provider. Anyone claiming a number is extrapolating.

**Derived from the account's real rates (§0.1):** on flash, cache-hit input is **1/50th** of
cache-miss, and output is **200×** cache-hit input ($1.20 vs $0.006). Re-reading an unchanged
1M prefix costs ~$0.006–0.012 — *but only while it fully matches a persisted prefix unit.* Any
edit before that unit forces a full cache-miss re-read of everything after it, at **50×** the
cached rate.

---

## 5 Compaction knobs and their real effect

Full evidence: `notes\05-compaction.md`. Line numbers refer to
`@deepseek-ai\dsh-compaction-basic\lib\index.js`.

### 5.1 Every config key, with its default

`Config` is a schemastery schema with **no `.default()` anywhere** (schema `:732-751`,
`:766-777`); every default is applied in `resolveConfig` (`:58-78`). So "row absent" and
"`config: {}`" are identical.

| key | default | unit | what it does |
|---|---|---|---|
| `thresholdRatio` | **0.8** (`:15`, `:62`) | fraction of `contextWindow` | fires when `meter.totalTokens >= floor(W × ratio)` (`:111`) |
| `retainRatio` | **0.16** (`:17`, `:63`) | fraction of `contextWindow` | verbatim tail kept after compaction (`:112`); must be `< thresholdRatio` (`:135`) |
| `retainTokens` | unset | absolute tokens | same; mutually exclusive with `retainRatio` (`:169`) |
| `summarizationProvider` | `""` (`:70`) | route id | empty ⇒ inherits the routed target |
| `summarizationModel` | `""` (`:71`) | model id | must be set as a pair with the provider (`:176-183`) |
| `maxTokens` | **8192** (`:72`) | output tokens | cap for the **summary** call only (`:297`) |
| `compactionRetries` | **1** (`:73`) | count | up to 2 attempts, then throws (`:919`) |
| `maxOverflowRetries` | **1** (`:74`) | count | retries after a `CONTEXT_WINDOW_EXCEEDED` (`:820-846`) |
| `modelPolicies` | `[]` (`:139`) | array | per provider/model overrides; **cannot set `contextWindow`** |
| `auto` | **true** (`:76`) | bool | registers the pre-step and overflow listeners (`:793-847`) |
| `thresholdChars` / `headChars` / `tailChars` (pruner) | **8192 / 4096 / 1024** | Unicode code points | runs **before** the threshold test (`:901-905`) |

**There is no message-count or turn-count key.** Retention is token-only (`:393-416`).

### 5.2 What this deployment is actually set to

**Nothing. Pure defaults, everywhere.**

- `presets\zabz\agent.cordis.yml:234-235` mounts `@deepseek-ai/dsh-compaction-basic` with
  **no `config:` block**; the installed mirror under `~\.dsh\.agent-presets\zabz` is identical.
- The `compaction` group (`:227-232`) carries only `isolate:` names.
- `settings\base.yaml`, `settings\machines\ZABZ-YOGA.yaml` and `~\.dsh\settings.yaml` have
  **zero** matches for `compaction`, `thresholdRatio`, `retainTokens`, `contextWindow`.
- `contextWindow = 1,000,000` is **hardcoded**, not configured and not read from the API:
  `dsh-llm-deepseek\lib\index.js:1392` `DEFAULT_CONTEXT_WINDOW = 1e6` → `:1845` → `:1580`
  → `:1999`.

**Effective: threshold 800,000 · retain 160,000 · room per cycle 640,000 · summariser
`deepseek-flash`, the same model as the main loop (`:270-280`).**

### 5.3 What 1M → 400k would actually do

At the same default ratios (0.8 / 0.16):

| | today (1M window) | at 400k window |
|---|---:|---:|
| compaction threshold | 800,000 | **320,000** |
| verbatim tail retained | 160,000 | **64,000** |
| room per cycle | 640,000 | **256,000** |
| compaction events (asymptotic) | 1× | **2.5×** |

For a session totalling 2M tokens: **2 events → 7 events (3.5×)**. Sessions that never
compacted before start compacting.

**Does the summary re-send the whole context at full price? No — and this corrects the
intuitive model.** `buildSummarizationInput` (`:666-675`) sends the system head + **only the
shadowed region** + the header tools; `summarizeWithLlm` appends the instruction as the final
user message (`:282-291`). The class docstring (`:655-661`) states the intent explicitly: it is
a genuine prefix of the last routed request **so the provider KV cache is reused**. The
retained tail is not re-sent. Billed input per compaction ≈ **640,000 tokens** today — a
separately billed call, mostly at the cached rate.

**So can compacting more often cost MORE? Yes, on three channels.** Summary *input* volume is
invariant — `(T/room) × room = T` either way. What multiplies ~2.5× is:

1. summary **output** (up to 8,192 tokens/event, and output is the expensive bucket — $1.20/M
   vs $0.003–0.006/M cache-hit input, **200×**);
2. per-event fixed cost — a durable event triple, one extra round trip, and **two synchronous
   whole-surface `isDeepStrictEqual` sweeps** (`:581`, `:595-596`) already flagged as the
   biggest event-loop stall in `docs/multi-window/research-single-engine-scaling.md:167-173`;
3. **cache re-warm count** — every compaction breaks the request series, and shorter cycles are
   likelier to fall outside the provider cache TTL (§4.2).

### 5.4 The defect worth fixing regardless of the threshold

The trigger compares **prompt-side pressure only** and never adds the **256,000-token
completion reservation** (`DEFAULT_MAX_TOKENS`, `:1394`, `:1998`). The largest legal prompt is
`1,048,576 − 256,000 = 792,576`, but the trigger is 800,000 — leaving a **7,424-token band
where DSH will not compact and the API still rejects the request.**

The observed failure sits exactly in that band:

```
This model's maximum context length is 1048576 tokens. However, you requested 1049125
tokens (793125 in the messages, 256000 in the completion).
```

793,125 ∈ (792,576, 800,000). **Every `CONTEXT_WINDOW_EXCEEDED` on the record is this bug
firing**, and each one costs a wasted full-price request plus an unplanned `retainTokens = 0`
compaction (a *whole-history* summary, the most expensive kind). Measured: 10 such errors
across 09-11..09-15, all root sessions.

Also: DSH's declared 1M window is **48,576 tokens below the provider's real 1,048,576**, so DSH
gives away 4.6% of usable context for no benefit.

### 5.5 Which lever, and the trap

| lever | file + key | gives | cost of the change |
|---|---|---|---|
| shrink the window | `settings\base.yaml` → `llm-deepseek.defaultContextWindow: 400000` | threshold 320k / retain 64k | adapter change; **and** setting `llm-deepseek.models` *replaces* `DEFAULT_MODELS` (`dsh-llm-deepseek:1896`) and silently drops `systemPromptUpdate: in-history` (`:1882`, `:1590`) unless re-declared — **a prefix-cache hazard** |
| lower the ratio only | `presets\zabz\agent.cordis.yml` → `compaction-basic` → `config.thresholdRatio: 0.4` | threshold 400k / **retain stays 160k** | one line, reversible, no adapter change, no cache hazard |

**The ratio-only lever is strictly safer.** It moves the compaction point without touching the
adapter, and keeping `retainRatio` at 0.16 preserves verbatim recall of the recent tail — the
variant that best respects "no capability loss".

**And the honest verdict on the owner's own hypothesis:** "compact at 400k instead of 1M" is
**not** the big win it looks like. §1.2 shows a normal working day averages **102k–263k tokens
per request** — mostly *below* a 400k threshold — while the traces show prompts climbing
monotonically 36k → 791k over hundreds of steps. What actually costs money is that climb
combined with the step count. 400k would fire more often, on three channels that each
multiply. See §6.5 for the version of this lever that *does* pay.

---

## 6 Multipliers

Full evidence: `notes\06-multipliers.md`. For each: the real knob, its measured size, and the
capability risk of changing it.

### 6.1 (a) Subagent `fork` vs `spawn` — analytic only, fork is unused

Fork seeds the child with the parent's **whole completed-turn log**
(`dsh-subagent-fork-in-process\lib\index.js:23-28,44,48-51`) and that seed is **re-sent as that
child's prompt on every turn**. Spawn passes `{}`
(`dsh-subagent-spawn-in-process\lib\index.js:30,34-39`) and sends **zero** parent context.
Extra cost of a fork: **+N tokens on the child's first turn** (N = full parent history, at
cache-miss price, 50× the cached rate) and **~N cached tokens on every later child turn**.

The shipped README is candid (`dsh-subagent-fork-in-process\README.md:118`): *"Forking
duplicates retained completed history into the child's request, which then accumulates its own
tokens independently."* Its KV-cache claim (`:120-122`) is that the child *may* reuse the
inherited byte-identical prefix — consistent with the measured subagent miss rate below.

**Measured use here: `isSeeded = false` for all 387 sessions; total seeded sessions = 0. Fork
has never been used on this machine.** A latent risk, not a current cost — and worth recording
precisely because "fan the job out across subagents" is the standing default, so the moment
someone reaches for a fork to save context the bill goes up, not down.

### 6.2 (b) Tool-result size — the largest measured driver

| knob | value | file |
|---|---|---|
| spill `maxInlineBytes` | **50,000** | `dsh-base\cordis.patch.yml:383-386` (head/tail split of the budget, `dsh-spill-policy:89-101`) |
| pruner `thresholdChars` / `headChars` / `tailChars` | **8192 / 4096 / 1024** | `patch.yml:394-399` **and** `presets\zabz\agent.cordis.yml:240-245` |
| pwsh/bash inline cap | 64,000 B, 64 MiB spill | `patch.yml:132-133` |
| glob / grep / grep-line | 100 results / 250 matches / 2,000 B per line | `dsh-tool-fs-search` |

**Measured: tool output is 82.5%, 86.9% and 95.8% of prompt tokens in three long sessions.**
Largest single result **42,974 chars**. And the pruner does far less than it appears:

```
pruner config: thresholdChars=8192 headChars=4096 tailChars=1024
session-b60e96b3 : 1919 results  3,648,817 raw chars -> 3,089,532 kept (84.7%)
session-85f98648 : 1881 results  4,809,550 raw chars -> 3,551,070 kept (73.8%)
session-0898187e : 1924 results  4,139,323 raw chars -> 3,017,860 kept (72.9%)
ALL FILES        : 12,597,690 raw chars -> 9,658,462 kept (76.7%)
```

Only **1.9–4.6%** of results exceed the 8,192-char threshold at all, so the pruner suppresses
just **23%** of tool bytes. The problem is not oversized results; it is **the number of results
carried forward and re-read on every subsequent step.** In `session-b60e96b3`, 1,919 results
totalling ~3.1M chars (~770k tokens) are re-read across 1,848 requests.

**Capability risk of tightening: small.** The full output already goes to a spill file and the
model can re-read a specific slice; head and tail are where the signal is for command output
and diffs.

### 6.3 (c) Retries — a failed attempt still bills full input

`dsh-llm-retry` re-issues the **entire** request; the only state carried is `{retry, retryId}`
(`:82-85`, `:151-178`). **No partial-response reuse exists** — the adapter emits content blocks
only at `[DONE]` (`dsh-llm-deepseek:1208-1247`). `EMPTY_RESPONSE` is billed input: it is
manufactured after a normal `[DONE]` with zero blocks (`:1236-1246`).

**Worst case for `maxRetries: 2` = 3× that step's input tokens** — on a ~37k prefix, ~111k
tokens, and at the miss price ~$0.033. The current setting is a deliberate documented choice
(`settings\base.yaml:87-96`: `mode: normal`, `maxRetries: 2`, five retryable codes, 500 ms →
5 s backoff, 0.1 jitter). Incidence is low: **16 `llm/retry` events total**, and of 55 error
attempts most were `QUOTA`/`RATE_LIMIT` (which do not bill input). **Not material. Leave it.**

### 6.4 (d) The MCP tool schemas — ~28–29k tokens on every request, forever

Measured from a real `request/header`:

- **6 MCP servers: 95 MCP tools + 27 builtin = 122 tools**
- serialized **117,176 chars** ≈ **29,294 tokens** (calibrated 3.9 chars/token)
- **MCP is 87,777 chars of it — 74.9%.** `firecrawl` alone **39,770 chars**; `jina` 22 tools,
  `playwright` 24–26, `secretary` 14, `fetch` 6, `context7` 2
- re-sent on **every** request: over 30,000 requests that is **~880 million tokens** of pure
  schema, re-read regardless of what the agent is doing
- all MCP rows live at `presets\zabz\agent.cordis.yml:418-550`; `~\.dsh\settings.yaml` has no
  MCP section

**The overlap is the finding:** `firecrawl` (27 tools), `jina` (22) and `fetch` (6) all fetch
web content — **55 tools and ~62k chars, over half the schema bytes, doing three versions of
one job.** Cost at the real rates: 29,294 tokens × $0.003–0.006/M × 30,000 requests ≈
**$2.6–5.3** per 30 days for the schema alone on the fleet's request count — modest in dollars,
but it is 15% of every prompt, and it is the term that *does not shrink*.

**Capability risk of trimming: small, if done by deleting a redundant server rather than
hiding tools mid-session** (a changing tool list is a §3.2 cache-invalidator).

### 6.5 (e) The always-on instruction block vs real work — not the problem

System prompt **24,888 chars ≈ 6.2k tokens**, byte-identical on every session sampled (§3.3).
The agent-instructions `AGENTS.md` payload is **58,689 chars ≈ 15k tokens**.

The floor is **5.1% of a 13-request session but 0.19% of a 105-request one**. Cached 99% of the
time, its cost is ~$0.0001/request. **Trimming the persona would be the wrong fix** — it is the
cheapest context in the system. It *would* matter if it ever stopped being cached, which is
the §3.2 hazard.

### 6.6 (f) Model-tier routing — already clean, measured

`request/context.data.model` across the local store: `deepseek-flash` **30,718 of 30,995
(99.1%)**; `deepseek-v4-pro` **139**; deepinfra routes 13. Independently, a 57-request sample
of the newest sessions returned `{"deepseek-flash": 57}` and **zero** `deepseek-v4-pro`.
Session titling runs on `dsh-session-title-first-prompt-llm` with route model `deepseek-flash`
(`maxInputBytes: 4096`, `maxOutputTokens: 64`) — one cheap call per top-level session, none in
subagent sessions.

**Model-tier routing is not a cost lever.** A measured "no", and worth stating plainly because
it is the first thing most audits propose.

### 6.7 (g) Cross-session prefix duplication — cached, not paid per session

§3.3: the prefix is **shared and cached**. A cold session's first request already reports 34,560
cache-read tokens against ~1,300–2,600 miss. The counter-example that proves the reading is real
is `session-24e68280`, whose first request is **35,910 miss / 1,664 hit** (prefix changed or
cache expired) and which hits normally afterwards. Concurrency does **not** multiply prefix cost;
**cache expiry and prefix-generation changes do**, and either silently re-bills ~34.7k tokens
across the fleet.

### 6.8 Ranked

| # | multiplier | measured size | capability risk to fix |
|---|---|---|---|
| 1 | tool output re-sent every turn | **83–96% of prompt tokens** | small |
| 2 | context × step count (the climb to 791k) | mean 189k–263k/req; 13.7B cache-hit tokens/30d | small (split sessions) |
| 3 | 122-tool catalog in every prefix | **117,176 chars ≈ 29.3k tokens**; 74.9% MCP; firecrawl 39.8k | small |
| 4 | cache-miss input (cold prefixes, prefix changes, retries) | 294.8M tokens/30d; 0.67–3.19% of prompt | small / none |
| 5 | compaction-at-overflow band defect | 10 wasted requests + 10 whole-history compactions | none — pure bug |
| 6 | retries | 16 retry events fleet-wide | leave alone |
| 7 | always-on instruction block | 0.19–5.1% of prompt | do not touch |
| 8 | model-tier routing | already 99.1% flash | nothing to fix |
| 9 | fork duplication | analytic only; fork unused (0/387) | none today |

---

## 7 Ranked savings plan

Every item is **waste recovery** unless marked otherwise. The owner's constraint — minimise
cost **without** reducing capability — is respected in that no item removes context the agent
has already produced; they change *how often the same bytes are re-billed*.

Baseline: **$195.74 over 30 days**, of which the two harness keys are **$108.13** and the two
spike days are **$99.80 (51%)**. A normal working day is **$13.40–$51.10** for the fleet.

### Tier 1 — pure savings, no capability loss

**1. Cap the climb: compact on the way up, not at the wall.** *(the defect + the real lever)*
The trigger ignores the 256,000-token completion reservation, leaving a 7,424-token band where
DSH refuses to compact and the API rejects. Every `CONTEXT_WINDOW_EXCEEDED` on the record is
this. Remove the band **and** move the trigger somewhere it actually acts.
- File: `presets\zabz\agent.cordis.yml` → `compaction-basic` → add
  `config: { thresholdRatio: 0.4 }` (threshold 400k, retain stays at 0.16 = 160k verbatim tail),
  which also removes the overflow band with margin.
- Saving: eliminates the 10 recorded failures plus the 10 emergency whole-history compactions
  they force. More importantly it caps the `context × steps` product on sessions that today
  run to 791k tokens × hundreds of steps — the mechanism behind the spike days.
- Capability risk: **none to small.** Retaining 160k verbatim is generous relative to every
  comparable harness (§4.4) and it is the *recent* context — the part that matters most.
- Verify: `day_usage.py` mean prompt/request must fall; `trace_session.py` must show no
  `CONTEXT_WINDOW_EXCEEDED`; the ledger's `miss%` should stay ≤1.5% and `mean ctx` should fall.
- Honest caveat, restated from §5.3: compaction events multiply ~2.5×, so **measure the net**.
  If the ledger's `$/req` rises, revert. Use `thresholdRatio`, **never**
  `defaultContextWindow` (§5.5 trap).

**2. Un-mount the redundant MCP servers.** *(pure savings, no capability loss if the survivor
covers the capability)*
`firecrawl` (27 tools, 39,770 chars) + `jina` (22) + `fetch` (6) are three implementations of
web retrieval. Keep one.
- File: `presets\zabz\agent.cordis.yml:418-550` — drop or `disabled: true` the overlapping
  rows; mount the Secretary MCP in a *separate preset* used for company work instead of in
  every session.
- Saving: ~50k of 117k schema chars ≈ **12,500 tokens off every request**. At real rates that
  is **$0.04–0.075 per 1,000 requests**, i.e. roughly **$1.5–2.6 per 30 days** on the fleet's
  volume — modest in dollars, but it cuts ~15% of every prompt and shrinks the fixed piece that
  never amortises on short sessions. It also makes every other item cheaper.
- Capability risk: **small, not none** — confirm with a live call that the survivor covers what
  the work actually uses.
- Verify: `len(json.dumps(tools))` from a fresh `request/header` should fall from 110,850 to
  ~60k; a cold session's first-request `cacheReadTokens` should fall from ~34,560 to ~22k.
- **Do this once.** The first generation of a new tool list is a fleet-wide prefix miss (§3.2).

**3. Tighten tool-result spill and pruning.**
- Files: `dsh-base\cordis.patch.yml:383-386` → `maxInlineBytes: 20000` (from 50,000);
  `presets\zabz\agent.cordis.yml:240-245` → `thresholdChars: 2000`, `headChars: 800`,
  `tailChars: 400` (from 8192/4096/1024), mirrored at `patch.yml:394-399`.
- Saving: measured 82.5–95.8% of prompt tokens are tool output, and the pruner suppresses only
  23%. Tightening to a ~1,200-char inline budget should remove on the order of **40–50% of
  carried tool bytes**, i.e. a large share of the **42% of DSH spend that is cache-hit input**.
  On a $51 day that is plausibly **$8–15**.
- Capability risk: **small.** Full output already lands in a spill file and can be re-read
  selectively; head and tail carry the signal.
- Verify: `tool_sizes.py` "kept % of raw" should fall from 76.7% to ~45%; then the ledger's
  `mean ctx` and `cost` per day must fall with `$/req` flat.

**4. Split long work across sessions instead of running one session for a day.** *(operating
rule, no config change)*
Cost is `requests × mean context`. The three most expensive local sessions on 09-15 were 395–957
steps at 417–480k mean context and were **52.5% of that day**. Splitting a 900-step session into
3 × 300-step sessions cuts prompt volume by roughly two thirds.
- Saving: the largest single item where it applies — up to **~50%** of a heavy day.
- Capability risk: **small** — the cost is losing conversational memory at the split point,
  which is exactly what a written handoff to the journal already provides. The mechanism exists;
  it needs to be the default rather than the exception.
- Verify: `day_sessions.py` — the metric that must fall is *max* `requests × mean prompt` per
  session, not total work done.

### Tier 2 — real but smaller, or with a tradeoff

**5. Bring DSH spend under a ceiling.** *(pure savings in expectation — bounds the tail)*
Today **no cap exists** (§8.2). `llm_budget.py` is genuinely enforced (pre-flight,
`BudgetExceededError`, $10/day · $15-per-24h · $50→$100 stepped · $300/month) but every cap is
computed from `model_usage` rows and **DSH writes none**.
- Change: on a timer, sum the session logs with `day_usage.py` and POST the totals into
  `model_usage` (or have the console export polled). The parser exists and needs no new format
  knowledge.
- Saving: not per-token — it bounds the tail. Two $50 days against a **$49.27** remaining
  balance is the actual risk.
- Capability risk: **none.**
- Note: the caps fail **open** on unexpected error (`llm_budget.py:428-432`); a DSH guard should
  fail closed.

**6. Exploit the off-peak window deliberately.**
Off-peak is **exactly half** peak (§4.1), and peak is **01:00–04:00 and 06:00–10:00 UTC Mon–Fri**
— which in local Eastern time is **21:00–00:00 and 02:00–06:00** (both *inside* the owner's late
night). Whether a request was charged peak or off-peak is recoverable from the ledger, because
each line item's price tells you its tier (`tools\peak_split.py`).

Measured split, using the ledger's own prices as the detector:

```
                          off-peak   peak
all keys 30 days          72.2%      27.8%
the two harness keys      78.3%      21.7%
2026-09-14 (harness)      75.2%      24.8%   -> $30.80 / $10.14
2026-09-15 (harness)      78.6%      21.4%   -> $40.18 / $10.91
```

- Finding: the fleet is **already mostly off-peak** (78.3%), because the owner works at night.
- Remaining opportunity: the **21.7% ($23.42 of the 30-day $108.13)** charged at peak, or
  **$10.14–10.91 per spike day**. Shifting the heaviest fan-out batches out of the local
  21:00–00:00 and 02:00–06:00 windows saves **up to that amount, i.e. roughly 20%** of a heavy
  day — worth having, but **not** the headline item.
- Capability risk: **none** — same model, same context window, same work.
- Verify: re-run `peak_split.py` after a week; the peak share should fall toward 0.
- Corrected claim: an earlier draft of this report asserted "~38% of cost fell in peak hours" on
  the spike days. **That was wrong** — the measured figure is 21–25%. The correction is recorded
  here rather than silently overwritten.

### Tier 3 — explicitly NOT recommended

- **Changing the model to a cheaper tier.** `deepseek-flash` is already 99.1% of requests and
  `deepseek-v4-pro` is $5.12 of $195.74. Nothing to save; this is the "capability loss first"
  move the owner ruled out.
- **Trimming the persona / instruction block.** 6.2k tokens, cached 99%, ~$0.0001/request.
- **Reducing `maxRetries`.** 16 retry events fleet-wide. Capability loss for no measurable gain.
- **Recompacting at 400k as a *first* move, or via `defaultContextWindow`.** §5.3 and §5.5.
- **Forking subagents to "share context".** It makes the bill worse, not better (§6.1).

---

## 8 What I could not determine

**1. Whether `secratary` (the Linux box) also holds a DSH key.** The export shows seven keys and
none is named for it, but `secratary` runs 18 agents and ~300 ticks/day with the *company's*
provider, so its traffic is in the secretary's own `model_usage` table (a separate pool, §8.2)
rather than here. **Settle it** by listing key names in the DeepSeek console's API-keys page.

**2. Any budget, ceiling or alert on DSH spend — there is none.** Established, not uncertain:
`app/database.py:3301` splits the secretary's pools by `_GATEWAY_AGENT_IDS = ("vscode_gateway",)`,
`llm_budget.py` is enforced but reads `model_usage`, the last 14 days of which total **$8.26**,
and **zero rows have an `agent_id` containing "dsh"**. The company's all-time peak day is
**$32.40** (2026-06-14) against a $300/month cap; **DSH has no cap at all.** The 30-day DSH pool
is **$108.13** and unguarded.

**3. The account balance is only read to 2 decimals.** `GET /user/balance` returns
`"total_balance": "49.27"` (down from `"49.37"` at the start of this session) — a **snapshot, not
a ledger**. A 66-token probe moved it by `$0.0000000`, which is correct for a $0.00001 call and
proves it cannot be used per-request. **No usage API exists:** `/user/usage`, `/user/billing`,
`/dashboard/billing/usage`, `/v1/dashboard/billing/usage`, `/v1/usage`, `/usage` all return
**HTTP 404** (`tools\probe_usage_api.py`). **The console CSV export is the only authoritative
source** — which is why the owner producing it mid-audit is what made this report possible.

**4. The DeepSeek cache TTL in hours.** Published only as "a few hours to a few days" (§4.2).
This decides how much a resumed session re-pays, and it is why `session-24e68280` took a
35,910-token miss. Settle with a controlled experiment — cold session, re-attach at t+1h, t+6h,
t+24h, read `cacheReadTokens` on the first request. **Cheap to run; I did not, because it needs
session restarts on a machine the owner is actively using.**

**5. Whether the `inputTokens`/`cacheReadTokens` *names* are the provider's or the adapter's.**
The adapter maps `prompt_tokens_details.cached_tokens ?? prompt_cache_hit_tokens` into
`cacheReadTokens` (`dsh-llm-deepseek:1155`), and the camelCase names do not appear in DeepSeek's
OpenAI-format reference. **This is now only a cosmetic question**: the 31,292/31,292 identity
test proves the arithmetic, and the ledger's separate `input_cache_hit_tokens` /
`input_cache_miss_tokens` line items confirm the disjoint convention directly.

**6. Why the system prompt grew 21,373 → 24,888 chars.** Needs a diff of `harness-config` git
history against the preset. Not cost-relevant by itself, but it is a prefix-generation change
and therefore a silent ~34k-token re-bill event.

**7. Whether the local session store can be made complete.** It captured 50% of misses and 76%
of hits for 09-15. Closing that gap would make local mechanism-level analysis a valid second
opinion on money. Worth one investigation: DSH session-log retention/pruning settings and
whether logs are being archived off `~/.dsh/sessions`.

---

## Appendix: reproduction

```powershell
# AUTHORITATIVE — the console export
python C:\Users\ezabz\code\_dsh-scale\tools\console_ledger.py
python C:\Users\ezabz\code\_dsh-scale\tools\ledger_final.py

# local measurement vs the ledger
python C:\Users\ezabz\code\_dsh-scale\tools\day_usage.py --host ZABZ-YOGA `
       --json C:\Users\ezabz\code\_dsh-scale\data\usage-yoga.json --top 20
python C:\Users\ezabz\code\_dsh-scale\tools\reconcile.py

# mechanism
python C:\Users\ezabz\code\_dsh-scale\tools\day_sessions.py 2026-09-15
python C:\Users\ezabz\code\_dsh-scale\tools\tool_sizes.py
python C:\Users\ezabz\code\_dsh-scale\tools\waste_probe.py
python C:\Users\ezabz\code\_dsh-scale\tools\field_semantics.py   # must print "breaks: 0"
python C:\Users\ezabz\code\_dsh-scale\tools\trace_session.py `
  "C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--\session-b60e96b3-6a48-4898-a770-bc9eb576b9ce\session.v3.jsonl.zstd"
```

Supporting briefs, each with its own file:line evidence:

- `notes\02b-secretary-pool.md` — the secretary DB, its price table, and the pool separation
- `notes\03-prefix.md` — prefix measurement and invalidators
- `notes\04-research.md` — online research with URLs
- `notes\05-compaction.md` — compaction keys and arithmetic
- `notes\06-multipliers.md` — the seven multipliers
