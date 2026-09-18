# 04 — DeepSeek API, context caching, `usage`, and compaction thresholds

Researched 2026-09-16. Source-quality labels: **(a) official** = vendor's own docs/site; **(b) third party** = credible independent source; **(c) community** = issue-thread / reverse-engineered / folklore.

## 0. Headline correction to the brief's premise

- The brief assumed the real published ids are `deepseek-chat` / `deepseek-reasoner`. **Not found on current official docs.** The current pricing table lists only `deepseek-flash` and `deepseek-v4-pro`. **(a)** https://api-docs.deepseek.com/quick_start/pricing
- So this deployment's ids are **not** private/newer-than-docs — they are the currently documented ids. **(a)** same URL.
- Legacy ids still accepted: `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp` — retired models, requests served by DeepSeek-V4.1-Flash and billed at Flash price. **(a)** https://api-docs.deepseek.com/quick_start/pricing (footnote 1)
- `deepseek-v4-pro` continues after 2026-09-14, billing unchanged. **(a)** https://api-docs.deepseek.com/quick_start/pricing (footnote 2); https://api-docs.deepseek.com/updates

## 1. Pricing (official)

Source: **(a)** https://api-docs.deepseek.com/quick_start/pricing — "prices listed below are in units of per 1M tokens".

| per 1M tokens | flash off-peak | flash peak | v4-pro off-peak | v4-pro peak |
|---|---|---|---|---|
| cache **hit** input | $0.003 | $0.006 | $0.022 | $0.044 |
| cache **miss** input | $0.15 | $0.30 | $0.66 | $1.32 |
| output | $0.60 | $1.20 | $1.98 | $3.96 |

- Verbatim pairing on the page: `1M INPUT TOKENS (CACHE HIT) OFF-PEAK $0.003 / PEAK $0.006`; `(CACHE MISS) OFF-PEAK $0.15 / PEAK $0.3`; `1M OUTPUT TOKENS OFF-PEAK $0.6 / PEAK $1.2` for flash. **(a)** same URL.
- **Off-peak = exactly half of peak.** **(a)** same URL, footnote 3: "Off-peak rates are half of the peak rates."
- **Peak hours: 01:00–04:00 and 06:00–10:00 UTC, Monday through Friday (all other hours are off-peak).** **(a)** same URL, footnote 3. ⇒ weekends are entirely off-peak. (Any older DeepSeek off-peak window is superseded by this footnote; I did not find an earlier published window in this session, so I make no claim about what it was.)
- Concurrency limit: flash 2500, v4-pro 500. **(a)** same URL, footnote 4.
- Context length: **1M** for both. **Max output: 384K.** Thinking mode: both support non-thinking and thinking (thinking is the default). **(a)** same URL.
- `max_tokens`: "The value must be between 1 and 384K (393216). When not set, the default is 8K in non-thinking mode, 64K in thinking mode (128K with `reasoning_effort` set to `max`)." **(a)** https://api-docs.deepseek.com/api/create-chat-completion
- Pricing effective date: "The new prices will take effect at 16:00 (UTC Time) on August 16, 2026." **(a)** https://api-docs.deepseek.com/updates
- Changelog latest entry as of fetch: **Date: 2026-09-10** (DeepSeek-V4.1-Flash Release). **(a)** https://api-docs.deepseek.com/updates

**NOT FOUND:** an "updated on <date>" line on the pricing page itself. The page carries no last-updated stamp; the nearest official dates are the changelog entry (2026-09-10) and the price-change effective time (2026-08-16 16:00 UTC). Searched: pricing page full text, changelog page.

## 2. Context caching (official)

Source: **(a)** https://api-docs.deepseek.com/guides/kv_cache

- Enabled by default for all users, no code change needed. **(a)**
- Definition of a hit: "Each user request will trigger the construction of a hard disk cache. If subsequent requests have overlapping prefixes with previous requests, the overlapping part will only be fetched from the cache, which counts as a 'cache hit.'" **(a)**
- Current mechanism (changed from older docs): "Due to the Sliding Window Attention mechanism... Each cached prefix is an independent, complete unit. A subsequent request can only hit the cache if it **fully matches** a **cache prefix unit**." **(a)**
- When prefixes are persisted — three rules: (1) **at request boundaries** — a unit at the *end position of the user input* and one at the *end position of the model output*; (2) **common prefix detection** across multiple requests; (3) **fixed token intervals** for long inputs/outputs. **(a)**
- Best-effort: "does not guarantee a 100% cache hit rate." **(a)**
- Output still computed/inferred; temperature randomness applies to generation, not to prefix matching. **(a)**

**Minimum cacheable prefix length = 64 tokens (unit: tokens).** Verbatim (official announcement page): "The cache system uses 64 tokens as a storage unit; content less than 64 tokens will not be cached." **(a)** https://api-docs.deepseek.com/news/news0802 (dated 2024/08/02)
- **Caveat:** the *current* `kv_cache` guide does **not** restate the 64-token minimum; it describes "cache prefix units" instead. Whether 64 is still the exact unit under the sliding-window scheme is **NOT FOUND**. The 64 figure is official but from the older caching model.

**Cache TTL / eviction:** "Cache construction takes seconds. Once the cache is no longer in use, it will be automatically cleared, usually within **a few hours to a few days**." **(a)** https://api-docs.deepseek.com/guides/kv_cache ; same wording in **(a)** https://api-docs.deepseek.com/news/news0802 ("Unused cache entries are automatically cleared, typically within a few hours to days."). No exact TTL number published.

**Cache storage charged?** **NOT FOUND.** Official pricing lists only three line items (cache-hit input, cache-miss input, output); no storage/retention fee appears anywhere in the pricing page or the caching guide. Searched: pricing page, `guides/kv_cache`, `news/news0802`, changelog. A Chinese tech-media piece alleges DeepSeek raised cache pricing to recover a "storage tax" — **(b)/(c) unverified, not used as fact**: https://www.leiphone.com/category/yanxishe/NfnH0gxun9dwHGGX.html

**Cache scope (per-account / per-key / shared)?** **NOT FOUND.** The docs speak only of "Each user request will trigger the construction of a hard disk cache" and "the system detects a common prefix across multiple requests" — no statement of tenancy scope. A `user_id` parameter exists for scheduling/isolation purposes **(a)** https://api-docs.deepseek.com/quick_start/rate_limit, but the docs never say it partitions the cache. Searched: `guides/kv_cache`, `news/news0802`, `quick_start/rate_limit`.

## 3. The `usage` object — exact JSON field names (official)

Source: **(a)** https://api-docs.deepseek.com/api/create-chat-completion (usage section, quoted verbatim by extraction)

| field | required | documented meaning |
|---|---|---|
| `prompt_tokens` | required | "Number of tokens in the prompt. It equals `prompt_cache_hit_tokens` + `prompt_cache_miss_tokens`." |
| `completion_tokens` | required | "Number of tokens in the generated completion." |
| `total_tokens` | required | "Total number of tokens used in the request (prompt + completion)." |
| `prompt_cache_hit_tokens` | required | "Number of tokens in the prompt that hits the context cache." |
| `prompt_cache_miss_tokens` | required | "Number of tokens in the prompt that misses the context cache." |
| `prompt_tokens_details` | required (object) | "Breakdown of tokens used in the prompt." |
| `prompt_tokens_details.cached_tokens` | — | "Number of tokens in the prompt that hit the context cache. **Same as `prompt_cache_hit_tokens`.**" |
| `completion_tokens_details` | object | "Breakdown of tokens used in a completion." |
| `completion_tokens_details.reasoning_tokens` | — | "Tokens generated by the model for reasoning." |

Answers to the specific questions:
- **Does `prompt_cache_hit_tokens` exist? YES** — a top-level required field. **(a)** same URL; also **(a)** https://api-docs.deepseek.com/guides/kv_cache ("we have added two fields in the `usage` section").
- **Does `prompt_tokens_details.cached_tokens` exist? YES** — documented, and explicitly the same value as `prompt_cache_hit_tokens`. **(a)** same URL.

Streaming: `stream_options.include_usage` (bool) — "all chunks in the stream will include a `usage` field, whose value is `null` on every chunk except the last one... the last chunk before the `data: [DONE]` message carries the token usage statistics for the entire request." **(a)** same URL.

Reasoning model surface: chain-of-thought is returned via **`reasoning_content`**, "at the same level as `content`". Thinking mode also accepts `reasoning_effort`; `temperature`/`presence_penalty`/`frequency_penalty` are accepted but have no effect; `top_p` has a lower bound of 0.95 in thinking mode and is fixed at 1.0 in non-thinking mode. **(a)** https://api-docs.deepseek.com/guides/thinking_mode

**NOT FOUND:** the camelCase names this deployment's accounting uses (`inputTokens`, `outputTokens`, `totalTokens`, `cacheReadTokens`, `reasoningTokens`) do **not** appear in the OpenAI-format API reference. They resemble the **Anthropic-format** surface (DeepSeek exposes `https://api.deepseek.com/anthropic`, per the pricing page). I could **not** verify `cache_read_input_tokens` / `input_tokens` / `output_tokens` in DeepSeek's Anthropic-compat docs — the field table extraction for that page returned tool/parameter support statuses only (and confirmed `cache_control` is **"Ignored"**), not the usage schema. Searched: https://api-docs.deepseek.com/guides/anthropic_api, https://api-docs.deepseek.com/quick_start/rate_limit. Treat `cacheReadTokens → cache_read_input_tokens` as **unverified inference**, not fact.

## 4. Documented prefix-stability guidance (official)

Source: **(a)** https://api-docs.deepseek.com/guides/kv_cache

Officially stated rules and worked examples:
- **Append-only history is cacheable.** Ex. 1: round 1 = `A + B`, round 2 = `A + B + C` ⇒ round 2 "can fully match the cache prefix unit `A + B`, hitting the cache for `A + B`." **(a)**
- **Divergence after a shared prefix misses, then gets learned.** Ex. 2: round 1 = `A + B`, round 2 = `A + C` ⇒ "the second request cannot hit the cache, because `A + C` does not fully match the first round's cache prefix unit (`A + B`). However... the system will detect that the two requests share a common prefix `A`, and persist `A` as a cache prefix unit." Round 3 = `A + D` then hits `A`. **(a)**
- **Long-document reuse needs two prior near-identical requests.** Ex. 3 (long text Q&A): first two requests miss; afterwards the system identifies `system` message + report content as a cache prefix unit and persists it; the third request hits. **(a)**
- **Only the prefix is matched.** "The hard disk cache only matches the prefix part of the user's input." **(a)**
- Multi-turn reuse is the intended pattern because the API is stateless and the client "must concatenate all previous conversation history and pass it to the chat API with each request." **(a)** https://api-docs.deepseek.com/guides/multi_round_chat

**NOT FOUND:** any explicit official sentence about *dynamic content at the start of a prompt* (e.g. timestamps, session ids) destroying cacheability, and any explicit official "keep the prefix byte-stable" instruction. Searched: `guides/kv_cache`, `guides/multi_round_chat`, `guides/chat_prefix_completion`. The consequence (mutating or reordering anything before a persisted unit breaks the full match) follows from Example 2 but is **inference**, not a quoted rule.

## 5. Compaction thresholds in other agent harnesses

| harness | threshold | quality | URL |
|---|---|---|---|
| **Claude Code** | **no official number published** | **(a)** docs only say auto-compaction "summarizes conversation history when approaching context limits" | https://code.claude.com/docs/en/costs |
| Claude Code (measured/quoted) | **~83.5% of the effective window** — quoted client code: `defaultThreshold = effectiveWindow - 13000;     // ~83.5% of 200k`, plus a `Math.min(userThreshold, defaultThreshold)` clamp so `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` can only lower it | **(c)** community, reverse-engineered source posted in the official repo | https://github.com/anthropics/claude-code/issues/31806 |
| Claude Code (corroborating) | "auto-compact should fire around **83.5% (167K tokens)**"; also cites `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` 200K mode | **(c)** community report | https://github.com/anthropics/claude-code/issues/63015 |
| Claude Code (corroborating, no number) | "[BUG] Autocompact not triggering at high context usage (90%+)" | **(c)** | https://github.com/anthropics/claude-code/issues/17292 |
| **OpenAI Codex CLI** | default `auto_compact_token_limit` = **90% of the RAW context window**, while the hard limit is the effective window. For `gpt-5.6-sol`: raw 272,000; effective % 95% ⇒ usable 258,400; default limit **244,800** = **94.7% of usable**. Config keys: `model_auto_compact_token_limit`, effective-context % (95), scope `Total` / `BodyAfterPrefix` | **(c)** community reproduction (codex-cli 0.149.0-alpha.4.1, 2026-08-22) with code-path citations | https://github.com/openai/codex/issues/40095 |
| **Cursor** | official: summarization trained/tested at **80k** and **40k** token triggers; no shipped default % published in that post | **(a)** official Cursor blog | https://cursor.com/blog/self-summarization |
| **Cline** | default **auto-condense threshold 88%** (maintainer: "try resetting it to 88% (the default)"); auto-compact/auto-condense is **on by default** in VS Code | **(c)** maintainer statement in official repo; **(a)** feature doc has no number | https://github.com/cline/cline/issues/9748 · https://docs.cline.bot/features/auto-compact · https://github.com/cline/cline/pull/12739 |
| **Aider** | not a % of context: `--max-chat-history-tokens` — "Soft limit on tokens for chat history, after which summarization begins. If unspecified, defaults to the model's `max_chat_history_tokens`." Aider source shows `max_chat_history_tokens = 1024` | **(a)** official docs + official source | https://aider.chat/docs/config/options.html · https://github.com/Aider-AI/aider/blob/main/aider/models.py |

**NOT FOUND:** the "community-measured ~92%" Claude Code figure. It did not appear in any source I checked. Searched: `Claude Code auto-compact 92% context window`, `claude code auto compact threshold percentage`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, plus the official settings/env-vars/costs docs. What *is* sourced is **~83.5%** (community, source-quoted). Do not report 92% as a fact.

Side finding worth knowing: at the time of the Cline report, Cline displayed a 1M window but internally assumed 200K and summarized around ~100K tokens. **(c)** https://github.com/cline/cline/issues/9748

## 6. Compacting earlier vs later — what is evidenced vs folklore

### 6(i) Quality degrades as context grows — EVIDENCED
- **Lost in the Middle (Liu et al., TACL 2023)** — "performance is often highest when relevant information occurs at the **beginning or end** of the input context, and significantly degrades when models must access relevant information in the **middle** of long contexts, **even for explicitly long-context models**." **(b)** peer-reviewed https://arxiv.org/abs/2307.03172
- **Chroma, "Context Rot: How Increasing Input Tokens Impacts LLM Performance"** — performance degradation with growing input length across task types; cites NoLiMa, AbsenceBench and multi-round co-reference (MRCR) as further demonstrations. **(b)** https://research.trychroma.com/context-rot
- **NoLiMa: Long-Context Evaluation Beyond Literal Matching (ICML 2025)** — needle/question pairs with non-lexical matches "reveal significant performance drops". **(b)** https://icml.cc/virtual/2025/poster/46685 · https://huggingface.co/papers/2502.05167
- **Anthropic, context engineering cookbook** — official Anthropic treatment of memory/compaction/tool-clearing as context-management levers. **(a)** https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools

Reading: the *shape* (longer context ⇒ lower accuracy, worst in the middle) is well evidenced and not folklore. None of these sources gives a threshold for a 1M-token window, and none of them was run on DeepSeek V4 — they establish direction, not a crossover point.

### 6(ii) Cost of the compaction step — PARTIALLY evidenced
- **Compaction is slow and is itself a model call.** Codex report: "the two observed remote compactions took **approximately 85 and 104 seconds**." **(c)** single-report measurement https://github.com/openai/codex/issues/40095
- **Compaction has a request cost, and earlier compaction is not a free win** — the same report explicitly refuses to overclaim: "That 8.376M is the amount of high-context traffic observed in the gap. **It is not a claim of guaranteed net savings, because earlier compaction also has a request cost.**" and "Earlier compaction may happen slightly more frequently." **(c)** same URL
- **Measured effect of compacting earlier (Codex, patched threshold 232,560 vs stock 244,800):** mean input/call dropped **70.3%** and **76.4%** after two compactions; input tokens/minute 481,552 → 413,031 (**-14.2%**); worst ten-minute input **-14.0%**. Author's own caveat: "it was **not** a matched provider-facing A/B. The patched run also had lower call density, so the full 14.2% difference cannot be attributed solely to the threshold change." **(c)** same URL
- **Why large context stays expensive even at 97% cache hit** (Codex report, mature thread: 114,915,129 input tokens, 112,230,400 cached, 97.66% reuse, 840 completions, 9 compactions, 238.6 min): "cached input was simply being processed repeatedly as part of very large prompts." Relationship given: `input-token throughput ≈ active prompt size × sampling-call density`. **(c)** same URL — this is the mechanism, measured on OpenAI, not DeepSeek.
- **Compaction *method* changes both error and cost** — Cursor official: "Self-summary consistently reduces the error from compaction by **50%**, even compared to the targeted baseline approach, while using **one-fifth of the tokens** and **reusing the KV cache**", tested with **80k** and **40k** triggers. **(a)** https://cursor.com/blog/self-summarization

### 6(iii) FOLKLORE / NOT EVIDENCED — say so plainly
- **No published measurement found** of "compact at 400k vs compact at 1M" net cost or net quality on DeepSeek's 1M window, or on any harness. Searched: `compaction cost measurement summarization tokens cost agent harness benchmark`, `Cursor agent context window compaction summarization docs threshold`, plus the DeepSeek pricing/changelog pages. Any specific 400k-vs-1M break-even number would be fabrication.
- **No official DeepSeek guidance on when to compact.** Searched: `guides/kv_cache`, `quick_start/pricing`, `api/create-chat-completion`, changelog.

### Arithmetic derivable from official DeepSeek prices (labelled: derived, not published)
Using flash **peak** rates from **(a)** https://api-docs.deepseek.com/quick_start/pricing:
- Cache-hit input is **1/50th** of cache-miss input ($0.006 vs $0.30 per 1M). Re-reading an unchanged 1M-token prefix costs ≈ **$0.006**, not ≈$0.30 — *provided the prefix still fully matches a persisted cache prefix unit*.
- Output is **$1.20/M peak** = **200×** the cache-hit input rate. So a compaction step emitting `S` output tokens costs the same as reading `200 × S` cache-hit input tokens.
- Consequence (inference): for a stable, append-only prompt, the marginal cost of *not* compacting is very low per token; folding the context in changes its prefix and forces a fresh cache-miss read plus a fresh summary generation. Codex's measured per-call input drop after compaction is the strongest available evidence in the *other* direction (smaller prompts ⇒ fewer input tokens per call), but it was measured on a different provider with 97% cache reuse and the author explicitly declined to call it a net saving.
- With **off-peak pricing at half**, all of the above halves if work is scheduled outside 01:00–04:00 and 06:00–10:00 UTC Mon–Fri. **(a)**

## Explicit "not found" list (with queries attempted)

1. Official numeric Claude Code auto-compact threshold — **not found**. Queries: `Claude Code auto-compact 92% context window`, `claude code auto compact threshold percentage`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, `anthropics/claude-code issue auto-compact threshold`. Official docs fetched: costs, settings, common-workflows, env-vars (fr/zh mirrors surfaced too).
2. The "~92%" Claude Code figure specifically — **not found** in any source. Only ~83.5% is sourced (community).
3. DeepSeek cache tenancy scope (per-account vs per-key vs global/shared) — **not found** in official docs.
4. Whether DeepSeek charges for cache storage/retention — **not found**; no storage line item exists in official pricing.
5. `cache_read_input_tokens` (and the camelCase `cacheReadTokens` mapping) on DeepSeek's Anthropic-format endpoint — **not found**; `cache_control` is documented as "Ignored", usage-schema fields were not surfaced.
6. Whether the 64-token minimum still governs under the current "cache prefix unit" / sliding-window scheme — **not found**; the current guide does not restate any minimum.
7. An "updated on <date>" stamp on the pricing page — **not found**; page carries none. Nearest official dates: changelog 2026-09-10, price change effective 2026-08-16 16:00 UTC.
8. Any quantitative cost/quality comparison of compacting at 400k vs 1M tokens on DeepSeek — **not found**. Queries: `compaction cost measurement summarization tokens cost agent harness benchmark`, `DeepSeek V4 1M context billing`.
9. Exact max output for a *non-thinking* vs *thinking* request beyond "MAXIMUM: 384K" and the `max_tokens` default table — only the defaults (8K / 64K / 128K at `reasoning_effort=max`) are documented. **(a)** pricing + create-chat-completion pages.

## Practical implications for DSH (parent's decision input)

- The observed error (`maximum context length is 1048576 ... requested 1049125 = 793125 messages + 256000 completion`) is consistent with the documented **1M context / 384K max output** pair: 793,125 + 256,000 > 1,048,576. **(a)** pricing + create-chat-completion.
- Accounting must read `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` (or `prompt_tokens_details.cached_tokens`), not `cacheReadTokens`, unless the Anthropic-format surface is confirmed to expose it. `inputTokens`/`outputTokens` likewise need mapping confirmation — `prompt_tokens`/`completion_tokens` are the documented OpenAI-format names. **(a)** api/create-chat-completion.
- Prefix stability is the dominant cost lever: full-match semantics on independent cache prefix units means any mutation or reordering before a persisted unit costs a cache-miss re-read of everything after it. **(a)** guides/kv_cache.
- Off-peak is now **all hours except 01:00–04:00 and 06:00–10:00 UTC Mon–Fri**, and off-peak is exactly half. **(a)** pricing footnote 3.
