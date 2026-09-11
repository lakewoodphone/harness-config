# DeepSeek model-family token pricing — verified 2026-09-11

Purpose: constants for computing per-session / per-turn USD cost from the harness token counters
(`uncachedInputTokens`, `cacheReadTokens`, `cacheWriteTokens`, `outputTokens`).
All figures read from the providers' own pages on 2026-09-11 UTC. Nothing here is inferred from
third-party blogs except where explicitly labelled.

## Headline finding that changes the engineering

**Every model id the harness routes to `deepseek-official` is served by `DeepSeek-V4.1-Flash` and
billed at the DeepSeek-V4.1-Flash (Flash) rate.** The ids `deepseek-v4-flash` and
`deepseek-v4-flash-vision-exp` are retired legacy aliases that still route to V4.1-Flash at Flash
price. So one rate card covers all of them; no per-id price lookup is needed.

Source: https://api-docs.deepseek.com/quick_start/pricing footnotes (1) and (2), and
https://api-docs.deepseek.com/news/news260910

## Official DeepSeek platform API (USD per 1M tokens)

Effective 04:00 UTC 2026-09-10 (news260910). Page states peak/off-peak, not a single rate.
Peak = 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri; all other hours off-peak. Off-peak = 50% of peak.

| model id in harness | served model | tier | P_miss | P_hit | P_out |
|---|---|---|---|---|---|
| `deepseek-flash` (= "DeepSeek-V41-Flash") | DeepSeek-V4.1-Flash | off-peak | 0.15 | 0.003 | 0.60 |
| `deepseek-flash` | DeepSeek-V4.1-Flash | peak | 0.30 | 0.006 | 1.20 |
| `deepseek-v4-flash` (retired alias → V4.1-Flash, Flash price) | DeepSeek-V4.1-Flash | off-peak / peak | 0.15 / 0.30 | 0.003 / 0.006 | 0.60 / 1.20 |
| `deepseek-v4-flash-vision-exp` (retired alias → V4.1-Flash, Flash price) | DeepSeek-V4.1-Flash | off-peak / peak | 0.15 / 0.30 | 0.003 / 0.006 | 0.60 / 1.20 |
| `deepseek-v4-pro` | DeepSeek-V4-Pro-0813 | off-peak | 0.66 | 0.022 | 1.98 |
| `deepseek-v4-pro` | DeepSeek-V4-Pro-0813 | peak | 1.32 | 0.044 | 3.96 |

P_write: **none. Not found because it does not exist on this page** — DeepSeek's rate card has
exactly three line items (cache-hit input, cache-miss input, output). Chinese page identical, same
three rows. DeepSeek's own deduction rule is "expense = tokens × price".

Chinese page (same numbers in CNY): 输入(缓存命中) 空闲 0.02 / 高峰 0.04 for `deepseek-flash`;
输入(缓存未命中) 空闲 1 / 高峰 2; 输出 空闲 4 / 高峰 8.

Note a small internal inconsistency on DeepSeek's own site: the CNY flash cache-hit figure is ¥0.02,
which converts to ~$0.0028, while the USD page says $0.003. Use the USD page. The cache-miss and
output CNY↔USD pairs are consistent at ~6.67 CNY/USD.

## DeepInfra (USD per 1M tokens)

Machine-readable and authoritative: `https://api.deepinfra.com/models/<model_id>` →
`pricing.cents_per_input_token`, `pricing.cents_per_output_token`,
`pricing.rate_per_input_token_cached` (a multiplier on input, not a price).

| model id | tier | P_miss | P_hit | P_out |
|---|---|---|---|---|
| `deepseek-ai/DeepSeek-V4-Flash-0731` | default | 0.06 | 0.015 | 0.18 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | default | 0.20 | 0.006 | 0.60 |
| `deepseek-ai/DeepSeek-V4-Flash` (not used by harness) | default | 0.09 | 0.018 | 0.18 |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | Priority (1.5×) | 0.09 | 0.0225 | 0.27 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | Priority (1.5×) | 0.30 | 0.009 | 0.90 |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | Flex (0.8×) | 0.048 | 0.012 | 0.144 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | Flex (0.8×) | 0.16 | 0.0048 | 0.48 |

DeepInfra applies **no peak/off-peak tiers** — flat per-token, with optional Priority/Flex service
tiers instead.

## Cache-write billing (the question with a real answer)

- **Official DeepSeek: no cache-write charge, and no cache-write counter.** Not found because the
  product has no such line item. The first request that populates a prefix bills normally at the
  miss rate; later identical prefixes bill at the hit rate. A `cacheWriteTokens` counter against
  `deepseek-official` should be priced at **0** — not at the miss rate, or you double-count if the
  harness also counts those tokens as `uncachedInputTokens`.
- **DeepInfra default path: no cache-write charge either.** Automatic prefix caching is free of any
  write premium; the populating request bills its tokens as ordinary input.
- **DeepInfra has an opt-in cache-write premium**, but only when the caller explicitly opens a
  retention window via `prompt_cache_options` (`prompt_cache_key` alone does not). Per the models
  API, `pricing.rate_per_explicit_cache_write_token` is `{"5m": 1.25, "1h": 2.0}` for
  `deepseek-ai/DeepSeek-V4-Flash` (granularity 1024 tokens), i.e. 1.25× / 2.0× the input rate.
  **For the two ids the harness uses it is `null`** — verified by reading the models API for
  `DeepSeek-V4-Flash-0731` and `DeepSeek-V4.1-Flash`. So P_write = 0 for the harness unless it
  starts sending `prompt_cache_options`.
- Other providers do bill cache writes at a premium (Anthropic 1.25×), which is where the general
  assumption comes from. It does not apply here.

## Reasoning tokens

- DeepInfra, explicitly: "Reasoning tokens count toward output token billing."
  https://docs.deepinfra.com/chat/reasoning
- Official DeepSeek: the page states billing is on "the total number of input and output tokens by
  the model", and both `deepseek-flash` and `deepseek-v4-pro` support thinking mode by default. No
  separate reasoning rate exists on the rate card. Treated as billed at P_out.

## Recommended constants (single-card, official)

Use one card for all four `deepseek-official` ids: P_miss=0.15, P_hit=0.003, P_write=0, P_out=0.60
(off-peak) or ×2 at peak. Optionally keep the exact V4-Pro card for `deepseek-v4-pro` if you want to
model it before the September 14, 2026 routing change.

## Confidence and gaps

- **Found and quoted (high confidence):** all DeepSeek official USD figures; all DeepInfra figures
  for both target ids including cache multipliers and service tiers; both providers' cache-write
  positions; DeepInfra reasoning-token billing.
- **Gaps / not found:** (a) whether the harness's `cacheWriteTokens` counter is ever non-zero against
  these routes — that is a harness fact, not a pricing fact, and should be measured; (b) the
  authoritative superseded rate card for retired V4-Flash (pre-2026-09-10) is no longer on the
  pricing page, so historical sessions cannot be repriced from primary sources; (c) DeepSeek's
  cache-hit price carries a small USD/CNY internal inconsistency noted above; (d) DeepInfra's
  default-path write behaviour is documented as "opaque, no write charge", not as an explicit
  "cache writes are free" statement.
- **Not substituted:** no price from any other model has been used to fill a gap for a target id.

## Sources

- https://api-docs.deepseek.com/quick_start/pricing (en) — the rate card
- https://api-docs.deepseek.com/zh-cn/quick_start/pricing (zh) — independent confirmation
- https://api-docs.deepseek.com/news/news260910 — V4.1-Flash launch, effective date, 50% off-peak
- https://deepinfra.com/pricing — per-model table
- https://deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731 and .../DeepSeek-V4.1-Flash — per-model cards
- https://api.deepinfra.com/models/deepseek-ai/DeepSeek-V4-Flash-0731 and .../DeepSeek-V4.1-Flash — machine-readable pricing
- https://docs.deepinfra.com/chat/reasoning — reasoning tokens billed as output
- https://docs.deepinfra.com/chat/prompt-caching and https://docs.deepinfra.com/chat/prompt-cache-retention — caching and the opt-in write premium
