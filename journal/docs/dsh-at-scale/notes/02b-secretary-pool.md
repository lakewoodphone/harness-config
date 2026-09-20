# 02b — Is the secretary's AI spend the same pool as DSH coding-agent spend?

**Verdict: DIFFERENT POOLS. The $54 belongs to the DSH pool, and nothing in the secretary DB can see or cap it.**
Measured read-only on `ZABZ-YOGA`, 2026-09-16T14:24Z (`data/secretary.db`, 509,313,024 bytes, mtime 2026-09-16T14:21:14Z local).

---

## 1. Tables holding per-call LLM usage / token / cost

All queries: `sqlite3.connect("file:.../data/secretary.db?mode=ro", uri=True)` — read-only URI, no writes, no migrations.

`TABLE_COUNT 182`. Relevant tables (exact `PRAGMA table_info` column lists):

| Table | Columns | Role |
|---|---|---|
| **`model_usage`** | `id, agent_id, provider, model, tier, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, latency_ms, success, error_message, created_at, cached_tokens, prompt_prefix_hash, served_by, session_id` | **THE per-call record.** Every LLM call, one row. This is the only source of the numbers below. |
| `tick_telemetry` | `id, tick_id, agent_id, tick_number, step_id, goal_id, started_at, ended_at, llm_rounds, total_tokens, total_cost, tool_calls_json, autonomy_decisions_json, latency_ms, steps_completed, outcome, error, tick_quality` | Per-tick aggregate (all rounds in one tick). Second, derived. |
| `tick_activity` | `id, tick_number, agent_id, was_active, action_type, step_id, goal_id, tokens_in, tokens_out, cost_usd, duration_ms, created_at` | Older per-tick path, has own cost/token columns. |
| `gateway_trace_span` | `id, trace_id, span, seq, status, agent_id, source, public_alias, canonical_id, provider, latency_ms, detail, created_ts` | Routing telemetry only — **no tokens, no cost.** |
| `ai_gateway_fallback_chains` | `id, trace_id, source, task_type, public_alias, initial_model, final_model, success, fallback_chain_json, created_at` | Routing only — no cost. |
| `model_quality_scores` | `id, canonical_id, task_type, alpha, beta, total_calls, successes, failures, avg_cost_usd, avg_latency_ms, last_updated` | Rolling avg cost per model+task, not a ledger. |
| `model_registry` | `id, canonical_id, provider, provider_model_id, display_name, tier, pricing_input_per_mtok, pricing_output_per_mtok, copilot_multiplier, ... pricing_source, pricing_last_checked_at, pricing_confidence` | Price *catalog* (input/output per Mtok), not usage. |
| `model_pricing_history` | `id, canonical_id, field_changed, old_value, new_value, source, changed_at` | Price-change log. |
| *(not LLM)* `pricing_history`, `pricing_trends` | customer/device repair quotes | **Repair-business pricing — unrelated name collision.** |

Writer: `app/database.py:2986` `INSERT INTO model_usage (...)` via `log_model_usage()` (`app/database.py:2961`); `estimated_cost_usd` is computed by the caller, not the DB.

## 2. The price table (`app/pricing.py` — real path is `app/pricing.py`, NOT `app/services/pricing.py`, which does not exist)

Units: **USD per 1,000,000 tokens**, tuples are `(input_per_mtok, output_per_mtok)`. Longest-prefix match wins (`app/pricing.py:24-26`).

| Dict | Line | Model prefix | Input $/Mtok | Output $/Mtok |
|---|---|---|---|---|
| `_OPENAI_PRICING` | 30 | `gpt-5.2-pro` | 21.00 | 168.00 |
| | 31 | `gpt-5.2-codex` | 1.75 | 14.00 |
| | 33 | `gpt-5-mini` | 0.25 | 2.00 |
| | 39 | `gpt-4o-mini` | 0.15 | 0.60 |
| | 42 | `o4-mini` | 4.00 | 16.00 |
| | 43 | `o3` | 10.00 | 40.00 |
| `_ANTHROPIC_PRICING` | 47-51 | `claude-opus-4.6/4.5/4-6/4-5/4-1` | 5.00 | 25.00 |
| | 52 | `claude-opus-4.8` | 10.00 | 50.00 |
| | 53-56 | `claude-sonnet-4.6/4.5/4-5/4` | 3.00 | 15.00 |
| | 58-60 | `claude-haiku-4.5/4-5/4` | 1.00 | 5.00 |
| `_GOOGLE_PRICING` | 67 | `gemini-3.5-flash-lite` | 0.30 | 2.50 |
| | 70 | `gemini-3.1-flash-lite` | 0.25 | 1.50 |
| | 73 | `gemini-3-pro` | 1.25 | 5.00 |
| | 74 | `gemini-3-flash` | 0.15 | 0.60 |
| `_DEEPINFRA_PRICING` | 90 | `deepseek-ai/DeepSeek-V4-Flash-0731` | **0.08** | **0.18** |
| | 92 | `MiniMaxAI/MiniMax-M3` | 0.28 | 1.10 |
| | 94 | `deepseek-ai/DeepSeek-V4-Pro-0813` | 1.30 | 2.60 |
| `_FIREWORKS_PRICING` | 102 | `accounts/fireworks/models/deepseek-v4-flash-0731` | 0.14 | 0.28 |
| | 104 | `accounts/fireworks/models/deepseek-v4-pro-0813` | 0.65 | 1.30 |
| `_DEEPSEEK_PRICING` | 116 | `deepseek-flash` (V4.1-Flash GA, off-peak) | 0.15 | 0.60 |
| | 117 | `deepseek-flash-peak` | 0.30 | 1.20 |
| | 118 | `deepseek-v4-flash` (legacy) | 0.44 | 1.32 |
| | 119 | `deepseek-v4-pro` (legacy) | 1.32 | 3.96 |
| `_OPENROUTER_PRICING` | 134 | `deepseek/deepseek-v4-flash` | 0.098 | 0.197 |
| | 138 | `deepseek/deepseek-v4-pro` | 0.435 | 0.87 |

**Cached-input prices exist only as prose comments, never as data — `pricing.py` has no cached-input field.**
Cache-read rates quoted in comments: V4-Flash `$0.016` (`:85`), MiniMax M3 `$0.056` (`:86`), V4-Pro `$0.10` (`:88`), DeepSeek `deepseek-flash` `$0.003` off-peak (`:110`).
The DB *does* store cache volume separately: `model_usage.cached_tokens` (44,125,614 of 290,949,736 total tokens = 15.2% all-time).

⚠️ **Price conflicts found (undecided, affects any estimate):**
- `app/pricing.py:118` `deepseek-v4-flash` = 0.44/1.32, but `AGENTS.md` says 0.14/0.28 for the same id, and `model_registry` row `('deepseek','deepseek-v4-flash')` = 0.44/1.32.
- `deepseek-flash` (the id DSH actually uses, see §4) appears in **`pricing.py:116` only** — there is **no `deepseek-flash` row in `model_registry`** at all.

## 3. Measured spend and tokens

Exact SQL (all against `model_usage`):

```sql
select date(created_at) d, count(*) calls, sum(total_tokens) toks,
       round(sum(estimated_cost_usd),6) cost
from model_usage
where date(created_at) >= date('now','-13 days')
group by d order by d desc;
```

Literal output — last 14 days, **all agents** (company + gateway):

| date | calls | total_tokens | cost USD |
|---|---|---|---|
| 2026-09-16 (partial, in-progress day) | 832 | 15,308,137 | 1.533791 |
| 2026-09-15 | 1,519 | 26,184,077 | 2.687874 |
| 2026-09-14 | 355 | 5,772,593 | 0.626157 |
| 2026-09-13 | 1 | 6,395 | 0.000563 |
| 2026-09-12 | 1 | 6,395 | 0.000563 |
| 2026-09-11 | 158 | 3,108,995 | 0.308027 |
| 2026-09-10 | 1,182 | 23,153,958 | 2.294136 |
| 2026-09-09 | — | — | *(no rows)* |
| 2026-09-08 | 5 | 116,413 | 0.107501 |
| 2026-09-07 | 8 | 186,218 | 0.183019 |
| 2026-09-06 | 14 | 329,815 | 0.295513 |
| 2026-09-05 | — | — | *(no rows)* |
| 2026-09-04 | 12 | 259,986 | 0.220284 |
| 2026-09-03 | — | — | *(no rows)* |

14-day window aggregate: **4,088 calls, 74,436,796 tokens, $8.25788**.
Company-only (excludes `agent_id='vscode_gateway'`) is the same to 4 dp — a single gateway row on 2026-09-01 ($0.000082) and none inside the window.

**Grand total, all time:**
```sql
select count(*), sum(total_tokens), sum(prompt_tokens), sum(completion_tokens),
       sum(cached_tokens), round(sum(estimated_cost_usd),6) from model_usage;
```
`(16706, 290949736, 285795097, 4007308, 44125614, 391.496009)` — **16,706 calls, 290.9M tokens, $391.496009**.
Span: `min=2026-05-07T00:14:37.675451+00:00`, `max=2026-09-16T14:23:30.637335+00:00`.
The 14-day figure ($8.26) is small vs the $391.50 lifetime because the March–August era (peaks $32.40 on 2026-06-14, $31.98 on 2026-06-12) is excluded by the window.

Top-8 all-time single days: 2026-06-14 $32.399452 · 2026-06-12 $31.984152 · 2026-08-02 $30.275076 · 2026-08-05 $25.265894 · 2026-08-04 $23.201885 · 2026-08-06 $22.825685 · 2026-07-29 $22.030427 · 2026-08-03 $21.747120. **No day has ever reached $54. Max ever ≈ $32.40.**

By model, 14 days:
```sql
select provider, model, count(*) calls, round(sum(estimated_cost_usd),6) cost
from model_usage where date(created_at)>=date('now','-13 days')
group by provider, model order by cost desc;
```
`deepinfra/deepseek-ai/DeepSeek-V4-Flash-0731` 2,786 / $5.524118 · `fireworks/...deepseek-v4-pro-0813` 522 / $1.371723 · `deepinfra/...DeepSeek-V4-Pro-0813` 102 / $0.681076 · `deepinfra/MiniMaxAI/MiniMax-M3` 554 / $0.444338 · `fireworks/...deepseek-v4-flash-0731` 45 / $0.145253 · `google/gemini-3.1-pro-preview` 8 / $0.032892 · `google/gemini-3.1-flash-lite` 26 / $0.026185 · `deepseek/deepseek-v4-pro` 38 / $0.021759 · `deepseek/deepseek-v4-flash` 5 / $0.010084 · `local/legacy-local` 1 / $0.0.

All-time top models: `deepseek/deepseek-v4-flash` 3,360 / $252.256113 · `google/google/gemini-3.5-flash` 568 / $65.582825 · `perplexity/sonar-deep-research` 30 / $12.04397 · `openai/gpt-4.1-nano` 2,008 / $10.395394 · `xai/grok-4.20` 353 / $10.019421.

**Freshness (provable):** newest `model_usage` row `created_at = 2026-09-16T14:23:30.637335+00:00` (id 16706 was `2026-09-16T14:21:58`; a newer row appeared between two queries). Query ran 2026-09-16T14:24:00Z → data **< 30 s old**. `tick_telemetry` max `ended_at = 2026-09-16T14:21:59.941058+00:00`, 378 rows / $1.2026 / 4,095,011 tokens in 14 days.

## 4. CRITICAL — does this pool cover DSH coding-agent traffic? **No.**

Two independent pools exist **inside the secretary**, and DSH is in **neither**.

**(a) The secretary's own split.** `app/database.py:3301`:
```python
_GATEWAY_AGENT_IDS = ("vscode_gateway",)
```
`get_company_daily_llm_spend()` (`:3304`) and `get_company_rolling_24h_llm_spend()` (`:3326`) sum `model_usage` with `agent_id NOT IN ('vscode_gateway')`; `get_gateway_daily_llm_spend()` (`:3056`) sums `agent_id IN ('vscode_gateway')`. Comment (`:3297-3299`): *"These exclude the 'vscode_gateway' agent so company-agent budget checks don't count VS Code Copilot traffic, and vice versa."* `budget_tiers.py:4`: *"Two independent pools: `company` (AI agents) and `gateway` (VS Code)."*

`vscode_gateway` all-time: **998 rows, $83.555569** — unchanged for the whole 14-day window (its only recent row is 2026-09-01, $0.000082). Models there are `google/gemini-3.5-flash`, `xai/grok-4.20`, `anthropic/claude-sonnet-4.5`, `openrouter/kimi-k2.6` etc. — a Copilot/Gemini surface, **not DSH**.

Query for any DSH attribution:
```sql
select agent_id, provider, model, count(*) from model_usage
where lower(agent_id) like '%dsh%' or lower(agent_id) like '%copilot%' or lower(agent_id) like '%vscode%'
group by agent_id, provider, model;
```
Returns **only `vscode_gateway` rows. Zero rows with `agent_id` containing `dsh`.** 74 distinct agent_ids exist; none is DSH.

**(b) DSH does not route through the secretary at all — it calls `api.deepseek.com` directly with its own key.**

- `C:\Users\ezabz\.dsh\settings.yaml:7-9`: `agent-default-model: provider: deepseek-official, model: deepseek-flash`.
- Adapter default: `node_modules/@deepseek-ai/dsh-llm-deepseek/lib/index.js:1911` `const PUBLIC_BASE_URL = "https://api.deepseek.com";` and `:1993` `baseURL: config.baseURL ?? environment?.get(BASE_URL_ENV)?.value ?? "https://api.deepseek.com"`. Key env: `:1838` `const DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY";`.
- `harness-config/settings/base.yaml:99`: *"The third failover tier, on infrastructure independent of api.deepseek.com."* — the failover is `deepinfra` → `https://api.deepinfra.com/v1/openai` (`:109`), again not the secretary.
- `harness-config/settings/machines/ZABZ-YOGA.yaml:12` and `LAKEWOOECHSMINI.yaml:80` (`baseURL: https://api.deepseek.com/v1`) — direct, per-machine.
- **Grep of `harness-config/settings/base.yaml` + `harness-config/presets/**/*.yaml` for `SECRETARY_API_BASE`, `secretary-auto`, `secretary-fast`, `secretary-smart`, `secretary-genius`: zero matches.** DSH has no secretary gateway route configured on this machine.

**(c) Credential env var NAMES** referenced (from `C:\Users\ezabz\.dsh\.credentials.yaml` — a DSH credential store with top-level keys `version, kind, records, refs, secret, payload`; **values were never read or printed**):
- **`DEEPSEEK_API_KEY`**
- **`DEEPINFRA_API_KEY`**

That is the whole credential surface for LLM providers in DSH: one direct DeepSeek key, one DeepInfra failover key. No secretary/gateway credential is present, which independently corroborates (b). The same two names appear as `apiKeyEnv` in harness-config and as `DEFAULT_API_KEY_ENV` in the adapter.

**Consequence:** the secretary's `$54/day`-class numbers are impossible — its lifetime peak day is $32.40 and the last 14 days total $8.26. **A $54 single-day charge on "the DeepSeek API" is the DSH pool**: DSH → `api.deepseek.com` directly with `DEEPSEEK_API_KEY`. The secretary DB contains **no row** for it and therefore **cannot** see it, attribute it, or cap it. To settle the exact figure, the only authoritative source is DeepSeek's own billing/usage endpoint for that key — the command that would settle it: `curl -H "Authorization: Bearer $DEEPSEEK_API_KEY" https://api.deepseek.com/user/balance` (balance) and the DeepSeek platform usage page for the dated breakdown. DSH-side, `dsh-token-meter` prices *context structure*, not dollars, and `dsh-session-stats`/`dsh-session-telemetry` contain no `cost`/`usd` symbols — so **DSH records no dollar figure locally either.**

## 5. Ceilings, budgets, alerts — and is `llm_budget.py` enforced or advisory?

**`llm_budget.py` is ENFORCED, pre-flight, fail-open on unexpected errors.** `check_budget()` raises `BudgetExceededError` (`:176`) *before* the call; callers abort the tick.

Enforced ladder (`app/services/llm_budget.py`):

| Gate | Line | Value | Code |
|---|---|---|---|
| Owner chat | 251 | always bypasses | `if is_owner_chat: return` |
| Circuit breaker | 265-273 | — | `is_circuit_broken(agent_id)` → raise |
| Tiered pressure | 282-310 | defers P2/P3 at ORANGE, all non-P0 at RED | `decision.deferred` → raise |
| Monthly limit | 318-327 | **$300** default (`:41`) | `if monthly_spend >= config.monthly_limit: raise` |
| Stepped tier | 351-361 | company auto-cap **$50**, step $10, hard ceiling **$100** | `if not tier_check.is_allowed: raise` |
| Global daily | 365-371 | **$10/day** default (`:35`) | `if global_spend >= effective_daily_limit: raise` |
| Rolling 24h | 373-381 | **1.5 × daily = $15** (`:335-337`) | `if rolling_24h >= rolling_24h_limit: raise` |
| CEO reserve | 386-394 | $2/day (`:36,50`) | `if agent_spend >= effective_ceo_reserve: raise` |
| Agent soft cap | 396-402 | $1.60/day (`:52-57`) | `if agent_spend >= effective_agent_soft_cap: raise` |
| Dept pool | 414-424 | $8/day | `if dept_spend >= effective_dept_pool` … **except `source == "standing_work_order"`** |

Fail-open exception is explicit (`:428-432`): `"Budget pre-flight failed unexpectedly for agent '%s'; allowing call"`.
Daily caps can be burst-multiplied (`:330-346`) when monthly headroom exists.

`app/services/budget_tiers.py:34-40` — the stepped owner-gated ceilings:
```python
COMPANY_AUTO_CAP = 50.0        # auto-approved soft cap (tier 0)
COMPANY_STEP = 10.0            # each approval unlocks $10 more
COMPANY_HARD_CEILING = 100.0   # absolute stop

GATEWAY_AUTO_CAP = 100.0       # auto-approved soft cap (tier 0)
GATEWAY_STEP = 10.0            # each approval unlocks $10 more
GATEWAY_HARD_CEILING = 200.0   # absolute stop
```
`check_budget_tier()` (`:217`) returns `BudgetTierResult.HARD_BLOCKED` past the ceiling; `is_allowed` (`:123-124`) is `result == ALLOWED`, which `llm_budget.py:355` turns into a raised error. Enforcement is real, not advisory.

**Alerts** exist and are advisory-only *as alerts*: `get_budget_alerts()` (`llm_budget.py:646`) emits `warn`/`exceeded` per window; `_level()` (`:520`) = `exceeded` at 100%, `warn` at ≥80%. `get_budget_window_snapshot()` (`:531`) labels each window's own enforcement: `calendar_day` and `calendar_month` = `"hard_limit"`, `rolling_24h` = `"safeguard"`, **`rolling_30d` = `"advisory"`**.

**Live DB state (read-only):**
```sql
select * from settings_overrides;          -- 0 rows
PRAGMA table_info(settings_overrides)      -- (key, value_json, updated_at)
select count(*), max(updated_at) from agent_budgets;   -- (0, None)
select * from budget_tier_approvals;       -- 0 rows
```
So **no DB override is in force** — the effective caps are the code defaults above ($10/day company global, $50→$100 company stepped, $300/month). `settings_overrides` and `budget_tier_approvals` are both empty, meaning **no owner approval has ever raised a tier**, and no override has ever been written.

**Note on which pool the caps apply to:** every cap above is computed from `get_company_daily_llm_spend()` / `get_gateway_daily_llm_spend()` — i.e. `model_usage` rows. **A cap can only ever bind on traffic that writes to `model_usage`. DSH writes nothing.** There is therefore **no ceiling, budget, or alert of any kind guarding DSH spend** anywhere in the company codebase. This is the whole finding.

## Gaps / what would settle them
- The exact $54 date and its per-day DSH token split are **not locally knowable**; DeepSeek platform billing for `DEEPSEEK_API_KEY` is the only authority.
- Whether a `deepseek-flash` row *should* be added to `model_registry` — it is absent there while `pricing.py:116` prices it. Not measured: no `deepseek-flash` string in any `model_usage` row since 2026-09-01 (`select count(*) ... and model like '%deepseek-flash%'` → `0`).
- ~~`settings_overrides` unwrapping~~ **SETTLED, no bug:** `list_settings_overrides()` (`app/database.py:5351`) does run `json.loads(raw)` on `value_json` and returns a flat `dict[key, value]` (`:5366`), exactly what `_resolve_budget_limits` (`llm_budget.py:132-168`) expects. The override path works; it is simply unused (0 rows). No silent-override risk.
