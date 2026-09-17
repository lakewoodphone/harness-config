# 96 — The gateway at scale: what 55 concurrent agents do to the provider and to the wallet

**Written** 2026-09-17 12:55–13:35Z, on **ZABZ-YOGA**, by the agent the owner briefed for exactly this question.
**Owns** this file and nothing else. Every script, log and JSON referenced below lives under `%TEMP%\gw96`
outside both repositories; no file other than this one was created, edited or deleted in any repository.
**Cost of writing it** **$0.0175** across 128 measured requests (counted below, §7) — 0.35 % of the $5 cap.
**Relationship to the machines measurement** `docs/mesh/84-calibration.md` measured the *machines* (403 MiB
commit and 0.62–1.68 logical CPUs per turn, and estimated **~$0.007/turn** at 99 % cache hit from a decoded
session's token structure). This document measures the *service* — the thing on the other end of the wire —
and the money it produces at fleet scale. The two agree in order of magnitude and this document's figure is
lower (**$0.0042/turn** on the measured mix and the measured card, §4.1); §4.1 says which input accounts for
the difference.

> **The headline.** The provider's own concurrency limit for `deepseek-flash` is **2500 simultaneous
> requests per account**, and the fleet's measured peak to date is **≈16–22 simultaneous requests** — so the
> 55-agent plan cannot reach the provider's ceiling by a factor of ~45, and nothing in the provider path
> queues, throttles or degrades before it. The ceiling is **not the provider's capacity and not the
> laptop's memory. It is the wallet, and it has no ceiling at all**: 55 agents generating continuously
> costs **≈ $68 an hour off-peak (≈ $136 peak)**, which crosses the guard's $50 stop in **44 minutes**. One
> hour of it is **1.24× the worst day the owner has ever had ($54.92)** — a rate he has never sustained for
> longer than minutes — and the whole measured ramp to 32 concurrent requests cost **1.7 cents and
> produced zero errors**.

---

## 0. The five answers, in one screen

**(1) The gateway the owner's agents actually talk to is not the one he thinks.** The 55 agents on the
laptop and the desktop call **`https://api.deepseek.com` directly** through the harness's own DeepSeek
adapter — there is **no `SECRETARY_API_BASE` and no `secretary-*` route anywhere in the harness's settings
or presets** (verified again today), and the desktop's live settings name `provider: deepseek-official`
with **zero** mentions of any proxy hostname (read over the tailnet today). The `personal-secretary-mvp` AI
gateway on `secratary` is a *second, separate* OpenAI-compatible surface serving VS Code and the company's
own agents; it is not in the DSH path. Both facts matter, and §1 separates them. The only machines behind
a pass-through are Yocheved's two (`packages/deepseek-proxy`, a Cloudflare Worker), and it adds no limit
(worker.mjs:1–129, request and response bodies forwarded verbatim).

**(2) The provider's real limits, with the file and the line.** Account-level concurrency **2500**
(`deepseek-flash`) / **500** (`deepseek-v4-pro`); overflow is **HTTP 429**, never a silent queue; a request
counts as a concurrent connection only while it is in flight; a request that has *not started inference*
after **10 minutes** has its connection closed. On our side: **no semaphore, no rate limiter, no retry
budget on request count** — `maxRetries: 2` (`~/.dsh/settings.yaml:12-26`), `maxParallelToolCalls: 20`
(per session), and **no budget key of any kind** (§1.4, §4).

**(3) The measured curve, N = 1 … 32.** Flat as a board and then gently up: small-prompt p50 **1.90 s at
N=1 → 1.00 s at N=16** (through the proxy), realistic 48 k-token prompts **1.81 s at N=4 → 1.82 s at N=8 →
3.39 s at N=32**. **Zero errors, zero 429s, cache still 99.6 % at N=32.** The only bend in the whole curve
is that last 4× (8 → 32 concurrent), which costs +1.6 s of median latency and nothing else.

**(4) The spend rate at 55.** **≈ $68/hour off-peak, ≈ $136/hour inside the peak windows**, built from the
fleet's own measured mix — 2.73 requests per turn (`84-calibration.md`), a 12.1 s turn, and a measured
**$0.001523 per request** at the 09-17 mean context (196,945 tokens, 98.5 % cache hit). Assumptions, the
sensitivity, and the comparison against $54.92 in §4.1; what to *set* in §5.

**(5) The observability gap is total.** `tools/spend-guard.py` works and is accurate, and **nothing runs
it and nothing enforces it**: there is no `guard.mjs`, no guard row in `packages/plugin-cost/cordis.patch.yml`
(13 lines: only `/cost`), no `settings/base.yaml` budget block, no `~/.dsh/spend-guard/` state directory,
and no scheduled task. The owner can see spend **only by asking me to run a 15-second scan**, i.e.
afterwards. §4.

---

## 1. Which gateway, and what it is

### 1.1 The DSH fleet's path: straight to the provider

| machine | what serves its model | evidence |
|---|---|---|
| `ZABZ-YOGA` (laptop) | `deepseek-official` → **`https://api.deepseek.com`** direct | `~/.dsh/settings.yaml` → `agent-default-model: {provider: deepseek-official, model: deepseek-flash}`; adapter default `PUBLIC_BASE_URL = "https://api.deepseek.com"` (`@deepseek-ai/dsh-llm-deepseek/lib/index.js:1911`), resolved `:1993` |
| `ZABZ-TECH` (desktop, primary) | direct (see §1.4 note) | its live settings are read in §1.4; `harness-config/settings/machines/ZABZ-TECH.yaml` sets no `agent-default-model`, so it inherits `base.yaml:59-60` (`deepseek-official` / `deepseek-flash`) |
| `LAKEWOOECHSMINI`, `DESKTOP-FGV6KMH` (Yocheved) | behind the Cloudflare Worker `ds.abletelsolutions.com` | `settings/machines/LAKEWOOECHSMINI.yaml:77-80`, `DESKTOP-FGV6KMH.yaml:105-108` |

**The finding, stated plainly:** `grep` of `harness-config/settings/**` and `presets/**` for
`SECRETARY_API_BASE`, `secretary-auto`, `secretary-fast`, `secretary-smart`, `secretary-genius` returns
the *standing instruction text* in `presets/zabz/agent.cordis.yml:83` and the audit's own notes — **zero
configuration**. The standing instruction tells a future agent to *prefer* gateway route aliases; **today
no client in the harness is pointed at that gateway at all.** The only file on this machine that names the
gateway's key is an environment variable (`PERSONAL_SECRETARY_AI_GATEWAY_KEY`), and nothing in the harness
reads it.

### 1.2 The gateway that does exist (`personal-secretary-mvp`, on `secratary`)

Reached and exercised today over the tailnet: `GET http://secratary.tail93e6e6.ts.net:8002/v1/models` →
**HTTP 200, 29.0 s**, a 38-entry catalog of route aliases and concrete models; `POST /v1/chat/completions`
with `model: secretary-fast` → **HTTP 200, 2.17 s**, answered by **`deepseek/deepseek-v4-pro`** after a
first-attempt `google/gemini-3-flash` fallback (`fallback_chain[0].reason_code: finish_reason_le…`).
Its own limits, from the code:

| limit | value | where |
|---|---|---|
| outbound HTTP connection pool | **`max_connections: 128`**, keepalive 64, expiry 60 s | `app/config.py:1219`; `app/services/ai_gateway.py:600-609` |
| per-request timeout | **600 s** | `app/services/ai_gateway.py:4324`, `:4978` |
| inbound concurrency cap | **none found** | no `Semaphore`/limiter in `ai_gateway.py`; the pool is the only bound, and httpx *waits* for a free connection rather than refusing |
| gateway daily pre-flight budget | **$5.00** | `app/config.py:1201` |
| per-session daily seat belt | **$2.00**, and an over-cap session is *downgraded*, not refused | `app/config.py:1193`; `ai_gateway.py:1888-1907` |
| hourly alert | $3.00 gateway / $1.50 session, 30-minute throttle | `app/config.py:1194-1196` |
| fallback on 429 | **yes** — `{402, 408, 409, 425, 429}` or ≥500 triggers the next candidate | `ai_gateway.py:3958-3972` |
| accounting queue | 5 000; on full, records **synchronously** (so a full queue slows the request path, never loses the row) | `ai_gateway.py:649-650`, `:685-697` |
| observability it *does* publish, per response | `secretary_cost.{cost_usd, cached_pct, session_usd_day, gateway_usd_hour, gateway_usd_day, gateway_usd_week}` and `session_envelope.{cap_usd, spent_usd, remaining_usd, over_cap}` | measured today, verbatim in §2.3 |

**What it does not have:** any request-rate limiter, any inbound concurrency cap, and any queue depth
metric. At 128 connections with a 600-second timeout, 55 simultaneous callers are ~43 % of the pool —
this gateway would not refuse them either.

**And it is not free.** `secretary-fast` — the alias whose own description says *"Force the fast/cheap
tier"* — **served `deepseek-v4-pro`** in today's call. v4-pro is **4.4× the miss rate, 7.3× the hit rate
and 3.3× the output rate** of flash (`packages/plugin-cost/pricing.json:18,40`). So *if* the harness ever
were pointed at `secretary-fast`, DSH's ~$0.007-turn would silently become ~$0.03–0.05/turn. That is a
live trap, not a hypothetical; it is item 4 in the owner question at the end.

### 1.3 The proxy (the one component of the chain that is ours)

`packages/deepseek-proxy/worker.mjs:1-129` — a Cloudflare Worker that holds no key, creates no
connections of its own beyond one upstream fetch, and **forwards request and response bodies unbuffered**
(`:90-112`). Its only gates are: `OPTIONS` → 204, `/__health`, and a bearer token verified against the
upstream model list with a 10-minute positive/negative cache (`:29-61`). **No rate limit, no concurrency
cap, no queue, no timeout of its own.** Measured header set today includes
`Server-Timing: …cfWorker;dur=1367` — the Worker's own share of a small request is **1.37 s**, against a
**0.59 s** median time-to-first-byte for the same prompt straight to `api.deepseek.com` (§2.1). The Worker
is a *latency* cost, not a capacity one.

### 1.4 Provider-side facts, and how solid each one is

| fact | value | source | status |
|---|---|---|---|
| account concurrency limit, `deepseek-flash` | **2500** | https://api-docs.deepseek.com/quick_start/rate_limit, read today | **PUBLISHED** |
| account concurrency limit, `deepseek-v4-pro` | **500** | same | **PUBLISHED** |
| accounting unit | *"A request counts as one concurrent connection from the time it is sent until the model response is complete"*; *"calculated at the account level, regardless of which API Key is used"* | same | **PUBLISHED** |
| overflow behaviour | **HTTP 429** — *"when the concurrency limit is exceeded, you will receive an HTTP 429 error code"*; it does **not** queue | same | **PUBLISHED** |
| stall behaviour | *"If the request has not started inference after 10 minutes, the server will close the connection"*; keep-alive is empty lines (non-stream) or `: keep-alive` comments (stream) | same | **PUBLISHED** |
| requests-per-minute or tokens-per-minute limit | **not published anywhere I could find** | searched `quick_start/rate_limit`, `quick_start/error_codes`, `quick_start/token_usage`, `guides/kv_cache`, the FAQ | **NOT DOCUMENTED** |
| rate-limit headers on the response | **none** | measured today: the full header set is `Transfer-Encoding, Connection, Date, Server: elb, Vary, Access-Control-Allow-Credentials, x-ds-trace-id, Strict-Transport-Security, X-Content-Type-Options, X-Cache: Miss from cloudfront, Via, X-Amz-Cf-Pop, X-Amz-Cf-Id, Content-Type`. No `x-ratelimit-*`, no `retry-after`, no capacity field | **MEASURED** |
| our client's retry on 429 | `RATE_LIMIT` is retryable; **`maxRetries: 2`** (shipped default 5), backoff 500 ms → 5 s, jitter 0.1 | `~/.dsh/settings.yaml:12-26`; shipped defaults `@deepseek-ai/dsh-llm/lib/index.js:232-234` | **MEASURED (read)** |
| any client-side concurrency limiter | **none** — a grep of the DeepSeek adapter for `semaphore|concurren|maxConnections|queue` finds only two unrelated doc comments | `@deepseek-ai/dsh-llm-deepseek/lib/index.js` | **MEASURED (read)** |
| any budget/ceiling key in the harness | **none** — grep of all `@deepseek-ai/*` packages for `budget|maxDailyUsd|ceiling|spendGuard|maxCostUsd` returns only token budgets, byte budgets and *quota-error detection*, never a dollar cap | installed tree, read today | **MEASURED (read)** |

**Verdict on the 21st or 51st simultaneous request:** it is accepted, served, and billed. At 55 in flight
the account is at **2.2 % of the flash ceiling**; the first thing that happens at 2501 is a 429, and a 429
costs a 0.5–5 s retry, **not** a lost turn.

---

## 2. The measured concurrency ramp

### 2.1 What was actually run, and what it is not

Two arms, one burst per level, every request counted, **no retries anywhere in the rig**, one level at a
time:

* **small** — 89-character prompt, `max_tokens: 8`, non-streaming (one 1-request streaming smoke run at the
  start, `N=1`, 1.91 s / TTFB 1.30 s, proved the surface before the level sweep). The provider-latency arm.
  Sent through `ds.abletelsolutions.com` (the proxy path) at N = 1, 4, 8, 16, and **direct to
  `api.deepseek.com` at N = 16**, so the proxy's share is separable.
* **big** — a byte-identical **48,694-token** prompt (real repository documents concatenated once),
  `max_tokens: 4` (and one N=8 burst at `max_tokens: 1024`). The **cache-and-cost** arm, at fleet-realistic
  prompt size. All big-arm requests were streaming; `usage` arrives on the final SSE frame
  (`stream_options.include_usage`).

**What it is not: these are not `dsh --profile headless` agent turns.** I tried that first and it **does
not work on this machine today**: one `node …/dsh/lib/bin.js --profile headless "<task>"` process, given a
240-second budget, produced **zero bytes on stdout, zero on stderr, and had to be killed**
(`%TEMP%\gw96\turn-n1-1.out.txt` / `.err.txt`, both 0 bytes; sampler `turn-ramp.json`). I aborted the N=4
burst rather than spend the budget on a hang. **Consequence:** every number below is the *wire* behaviour
of the request the harness sends, not the harness's own end-to-end turn time. The turn-level numbers
(403 MiB, 12.1 s) come from `84-calibration.md` and are quoted, not re-measured.

### 2.2 The latency and error curve (MEASURED, 2026-09-17 13:06–13:22Z)

| arm | route | N | ok | statuses | wall | p50 | p95 | max | TTFB p50 | miss tok | hit tok | out tok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| small | proxy | 1 | 1/1 | 200 | 1.90 s | 1.90 s | — | 1.90 s | 1.90 s | 54 | 0 | 8 |
| small | proxy | 4 | 4/4 | 200 | 1.76 s | **1.27 s** | 1.63 s | 1.63 s | 1.27 s | 216 | 0 | 32 |
| small | proxy | 8 | 8/8 | 200 | 1.24 s | **1.13 s** | 1.23 s | 1.23 s | 1.13 s | 432 | 0 | 64 |
| small | proxy | 16 | 16/16 | 200 | 1.42 s | **1.00 s** | 1.33 s | 1.33 s | 1.00 s | 864 | 0 | 128 |
| small | **direct** | 16 | 16/16 | 200 | 1.31 s | **1.14 s** | 1.25 s | 1.25 s | **0.59 s** | 864 | 0 | 128 |
| big (48.7 k) | proxy | 1 | 1/1 | 200 | 1.94 s | 1.94 s | — | 1.94 s | 1.13 s | 48,694 | 0 | 4 |
| big (48.7 k) | proxy | 4 | 4/4 | 200 | 2.13 s | **1.81 s** | 2.11 s | 2.11 s | 1.39 s | 728 | 194,048 | 15 |
| big (48.7 k) | proxy | 8 | 8/8 | 200 | 2.67 s | **1.82 s** | 2.63 s | 2.63 s | 1.52 s | 1,456 | 388,096 | 28 |
| big (48.7 k) | proxy | 8 (`max_tokens` 1024) | 8/8 | 200 | 2.90 s | **2.39 s** | 2.76 s | 2.76 s | 1.90 s | 1,456 | 388,096 | 156 |
| big (48.7 k) | proxy | **32** | **32/32** | 200 | 4.38 s | **3.39 s** | 4.08 s | 4.21 s | 3.09 s | 5,824 | 1,552,384 | 117 |

*All rows are MEASURED; every figure is the aggregation the rig's own JSON computes, not a transcribed
console line. There are **two different `N=1` small requests in the record** and the table shows the
non-streaming sweep's one: the streaming smoke run (1.91 s total, TTFB 1.30 s — both measured, §2.1) and this
row (1.90 s total, which for a non-streaming call *is* the first byte). They are counted as two requests in
§7, not one. **The table is the authoritative copy**; no number in it passed through prose.*

**The shape, and it is not what a queue looks like.**

* **No 429, no 5xx, no timeout, no aborted connection — 128/128 requests returned HTTP 200 with a usage
  block.** That is the strongest single result here: the provider did not throttle at any level tested.
* **The small-prompt arm gets faster with concurrency** (p50 1.90 → 1.00 s from N=1 to N=16): one cold
  request pays connection setup and a cold edge, N=16 amortises it. This is a warm-up effect, not a
  property of concurrency, and it is exactly the kind of single-point artefact that would have been read
  as "concurrency is free" if only N=1 and N=16 had been measured.
* **The big-prompt arm is where the bend is**: p50 **1.81 s at N=4 → 1.82 s at N=8 → 3.39 s at N=32**.
  A **+1.6 s median (+87 %)** for a 4× increase in concurrency, with p95 growing 2.63 → 4.08 s. That is
  ordinary server-side queueing beginning to show, and it is the only bend in the curve.
* **Cache behaviour is untouched by concurrency.** The 48,694-token prefix cost a cache miss **once**
  (N=1) and every subsequent request at every level hit **exactly 48,512 tokens per request** —
  194,048/4, 388,096/8, 1,552,384/32 — i.e. **99.6 % hit at N=32**. The provider's prefix cache is
  account-level and it does **not** degrade, fragment or miss under a burst. This is the single most
  important number for the wallet, because the cache-hit rate *is* the bill.
* **Proxy vs direct:** TTFB p50 **1.00 s (proxy) vs 0.59 s (direct)** for the identical small prompt at
  N=16 — the Worker's own `Server-Timing: cfWorker;dur=1367` corroborates it. Total time is nearly equal
  (1.42 s vs 1.31 s), so the proxy costs ~0.4 s of *perceived* speed and no throughput.

### 2.3 Cost of the ramp, and the per-request rate card

Token totals for every request in the rig (§7): **62,208 miss / 2,522,624 hit / 920 output = $0.01745** on
the `plugin-cost` card at off-peak rates — **under two cents for 128 requests**, including a 32-way burst of
48.7 k-token prompts. Measured unit costs, per request (*the "cold", "warm" and 48.5 k rows are what the rig
literally measured; the last two apply the fleet's own logged mix to the same rate card — their 830 output
tokens are the fleet's measured mean, not the rig's, which ran `max_tokens` 4–1024*):

| request shape | prompt tokens | miss | hit | out | cost (off-peak) |
|---|---|---|---|---|---|
| small probe (this rig) | 54 | 54 | 0 | 8 | $0.000013 |
| realistic, **cold prefix** | 48,694 | 48,694 | 0 | 4 | **$0.007306** |
| realistic, **warm prefix** (what the rig measured at N = 4 … 32) | 48,512 | 182 | 48,330 | 4 | **$0.000175** |
| the same 48.5 k context with a real turn's output (830 tokens, mostly a cache hit) | 48,512 | 744 | 47,768 | 830 | $0.000753 |
| **a real turn's step at the fleet's measured mean context, 09-17 mix** | **196,945** | **2,954** | **193,991** | **830** | **$0.001523** |
| the same step, fleet-average 09-15 mix (252,661 prompt / 99.25 % hit / 977 out per request) | 252,661 | 1,895 | 250,766 | 977 | $0.001623 |

**The cold/warm ratio is 42× and it is the whole cache story**: a cache miss costs **50×** a hit, so an
agent that loses its prefix pays 42× for that step. My big arm sat at 99.6 % because the prefix never
changed; a fleet whose sessions start and stop loses far more than that. `60-cost-audit.md` §3.2 lists
what invalidates it (tool list change, pruner rewrite, mid-session system-prompt rewrite) and those
remain the cheapest money in the system.

**The rate card itself was re-verified today** against the live pricing page, not trusted from memory:
`deepseek-flash` off-peak $0.003 / $0.15 / $0.60, peak exactly double (they are **$0.006 / $0.30 / $1.20**);
`deepseek-v4-pro` $0.022 / $0.66 / $1.98 off-peak — identical to `packages/plugin-cost/pricing.json:18,40`,
so the card is current and every dollar below is priced on the provider's own published numbers.
The live request also confirmed **the route really serves `deepseek-flash`** (not a silent downgrade or
upgrade), and the DeepSeek wire usage block is the disjoint convention the card assumes
(`prompt_tokens_details.cached_tokens` + `prompt_cache_miss_tokens` + `completion_tokens`).

### 2.4 What the historical logs say the real concurrency already is (MEASURED, all 619 session logs)

From `data.usage` timestamps in every durable session log on this machine (the same population the guard
prices), counted into 1-second and 10-second buckets:

| day (UTC) | requests | mean prompt | cache hit | peak requests **started per second** | peak per 10 s | top session |
|---|---|---|---|---|---|---|
| 2026-09-17 (to 13:30Z) | 6,102 | 196,945 | 98.5 % | **9** | 26 | 0.89 req/min |
| 2026-09-16 | 13,760 | 193,581 | 99.1 % | 7 | 22 | 0.33 req/min |
| 2026-09-15 (the $54.92 day) | 5,813 | 252,661 | 99.3 % | 9 | **39** | 0.32 req/min |
| 2026-09-14 (the $44.88 day) | 12,279 | 274,157 | 99.0 % | **12** | 29 | 0.41 req/min |
| 2026-09-11 | 7,020 | 261,408 | 99.3 % | 7 | 20 | — |

Two facts fall out, and both are load-bearing for §5:

1. **The fleet has never exceeded ~12 model requests started in any one second**, on any day, including
   both spike days. The busiest 10-second window on the record is **39 requests**.
2. **The fleet has been operating at roughly 0.16 requests per second average** on its heaviest days
   (13,760 / 86,400 s), i.e. **about 0.7 agents' worth of continuous generation**, not 55. *Correction
   recorded rather than quietly overwritten:* the first draft of this document said "1.6 requests per
   second" — a factor of 10 too high, and it is the same class of error the program keeps making. The
   1.6 was the correctly-measured **per-10-seconds** figure (09-16's busiest 10 s window held 22 requests;
   09-15's held 39).

**Provenance, stated because it bounds the claim:** these are *departures*, not in-flight counts. The true
number of simultaneous connections follows Little's law from the service time (§2.2, ≈1–2 s per request):
peak arrivals of 9–12/s against ~1.8 s service = **≈ 16–22 requests genuinely in flight at the peak
second**. Both the arrival and the in-flight figure are far below 55.

---

## 3. The risk I accepted, and where I stopped

| risk | assessment at the time | what I did |
|---|---|---|
| tripping a provider rate limit that bans or throttles the key | The published limit is **2500 concurrent / account** and I am one key on an account with a ~$49 balance. A 32-request burst is **1.3 %** of that. The residual risk is an *undocumented* requests-per-minute limiter at the edge. | Ran N = 1, 4, 8, 16, 32 **sequentially**, one burst per level, 1.5 s of calm between levels, **no retries** (a retry storm is what turns a soft limit into a hard one). Watched for 429 as the primary abort signal. **I stopped at 32.** I did not test 55, and the brief's instruction not to risk a ban is the reason: per the published table 55 is safe, but I could not verify the *unpublished* per-minute limiter exists or not, and a ban would break the owner's live work. |
| the burst slowing or breaking the owner's live work on this laptop | One engine (pid 4880) is serving the owner. My bursts are HTTP only (no child processes, no MCP servers), 16–32 sockets for a few seconds. Measured during the runs: commit 25.2 GiB, 11.4 GiB free physical, governor `1 of 24 slots in use` (held by the owner's own e2e test). | Kept bursts to seconds, never touched pid 4880, never restarted anything, and abandoned the process-spawning `headless` arm the moment it hung rather than push 16 hung processes onto the box. |
| spending past $5 | Counted every request in the rig's own JSON | Total **$0.0175** for 128 requests (§7), plus ~$0.00007 of gateway probes. **0.35 % of the cap.** |

**Where I stopped, and why:** at **N = 32** — below the owner's 55 — because the curve's only bend appears
exactly there and testing 55 would have added a 1.7× larger burst to buy a point I can already bound: at 32
the median rose 1.6 s and **nothing failed**; each further doubling is a queueing curve, not a cliff, and
the provider's ceiling is **78× further out** (2500 / 32). **The provider side is not the constraint, and I
have enough to say so with evidence rather than by extrapolation.**

---

## 4. The spend rate, and the guard

### 4.1 What 55 concurrent agents cost

**Model inputs, all measured.** Cost per request **$0.001523**, from the fleet's own 2026-09-17 mix
(mean prompt **196,945 tokens**, **98.5 %** of them cache hits, **830** output tokens — §2.4) priced on the
re-verified card (§2.3). Requests per turn **2.73** and turn length **12.1 s**, both from
`84-calibration.md` §1.5/§1.2 — measured on this same fleet, and *quoted* rather than re-measured because
the harness's own headless turn would not run today (§2.1, §6.1).

**Derivation.**

```
one agent, generating continuously:
   1 / 12.1 s            = 0.0826 turns/s      = 0.2256 requests/s
   0.2256 requests/s     x 3600 s              = 812 requests/hour
   812 requests          x $0.001523           = $1.24 / agent-hour
```

| fleet | off-peak | peak (exactly 2×) | 6-hour block | 8-hour night |
|---|---|---|---|---|
| **55 agents generating continuously** | **$68/hour** | **$136/hour** | **$408** | **$544** |
| the same 55 at a 40 % provider duty cycle | ≈ $27/hour | ≈ $54/hour | ≈ $163 | ≈ $218 |
| what the fleet's own log says it sustained on its heaviest day (0.159 req/s) | $0.87/hour | $1.74/hour | — | — |
| the same arithmetic on the 09-15 mix instead of 09-17 ($0.001623/request) | $73/hour | $145/hour | $436 | $581 |
| **one hour at 55 vs the worst day ever recorded ($54.92)** | **1.24×** | **2.5×** | — | — |

*All five rows are the same single multiplication (requests × $/request); only the third is bounded by
something other than the plan, and it is 78× smaller — which is the honest measure of how far past the
fleet's demonstrated behaviour this plan is (§2.4).*

**The load in the demand dimension — this is the part that matters more than the dollars.**
One continuous agent is **0.226 requests/s**, so 55 of them are **12.4 requests/s = 44,673 requests/hour**,
re-reading **2.44 M prompt-tokens per second — 35 GB of context every hour (at 4 bytes/token), ~280 GB
across an eight-hour night**. Compare against what the fleet has actually done:

| | requests/s | vs the 55-agent plan |
|---|---|---|
| busiest **10 seconds** ever recorded (09-15, 39 requests) | 3.9 | the plan is **3.2× that, held indefinitely** |
| busiest **single second** ever recorded (09-14, 12 requests) | 12 | the plan is at that rate **continuously** |
| 09-15 as a whole day (5,813 requests / 86,400 s) | 0.067 | the plan is **184× that** |
| 09-16, the heaviest request day on record (13,760 / 86,400 s) | 0.159 | the plan is **78× that** |
| 09-17 so far, with a research fleet running all day (6,102 / 48,600 s = to 13:30Z) | 0.126 | the plan is **99× that** |

**Assumptions, plainly.**
1. *Continuous generation.* The $68/hour figure assumes all 55 agents are inside the provider at once —
   `84-calibration.md`'s "resident" turn, which is what a fleet of 55 *blocked* agents looks like. Real
   fleets spend ~40 % of wall-clock inside the provider (12.1 s turn, ~2.7 model calls × ≈1.8 s measured
   service time), which is why row 2 exists. **$68/hour is the ceiling of the range; ~$27/hour is the
   middle; and neither has ever been tested.**
2. *The provider serves the throughput.* Nothing published states a tokens-per-second or
   requests-per-minute limit (both NOT DOCUMENTED, §1.4), and nothing published says the account can absorb
   2.44 M prompt-tokens/s — the account's worst day moved 2.66 B hit tokens in 24 h, i.e. **31 k tokens/s,
   79× less**. **This, not concurrency, is the untested assumption, and the failure mode if it is wrong is
   latency and queueing, not 429** (a 429 is a documented, retryable, non-billing event).
3. *Off-peak.* The arithmetic uses the card's off-peak flash rates. Peak (01:00–04:00 and 06:00–10:00 UTC
   Mon–Fri) is **exactly 2×** — and in the owner's local evening that means **21:00–00:00 and 02:00–06:00
   Eastern**, i.e. a late-night 55-agent run lands **inside** peak, not outside it.
4. *The card, not the invoice.* These are `plugin-cost` rates re-verified today against the pricing page
   (§2.3) and confirmed to the cent against the console ledger on 2026-09-16, applied to tokens the provider
   itself reported. The local logs are a *sample* of the bill (50 % of misses / 76 % of hits on the one day
   that could be reconciled), so treat fleet-wide money as **×1.3–2.0 low** and per-request cost as **±15 %**.
5. *`deepseek-flash`.* All of it assumes the route stays on flash. §1.2's `secretary-fast → deepseek-v4-pro`
   observation is why that is a live question, not a hypothetical.

**One discrepancy with `84-calibration.md`, named rather than buried.** That document estimates **~$0.007 per
turn**; this one computes **$0.0042** (2.73 requests × $0.001523). The difference is the token volume per
turn. 84 derived **~3.1 M input tokens for the night from ~131 turns ≈ 24 k tokens/turn**; the fleet's
*logged* mean prompt on 09-17 is **196,945 tokens per request × 2.73 requests/turn = 538 k tokens/turn**, so
the estimate is low by ~22× *and* the two are not really in conflict, because 84's rig was a synthetic
`headless` turn with a fixed prompt while the logged mean is the real fleet carrying a full session history.
Neither is the bill: 84's figure is a **floored estimate** and mine is a **mean**, and the fleet's expensive
sessions are exactly the 395–957-step ones whose per-step context runs to 400 k+. **Use $0.0042 as the
floor for a healthy session and expect long sessions to cost several times it.**

### 4.2 Would the guard's ceilings have fired during my ramp?

**No — and the reason is not that the ramp was cheap, it is that nothing was watching.**

| guard threshold (§65 §3.3) | value | my ramp | time to it at 55 agents, off-peak |
|---|---|---|---|
| warn | $25 | **did not fire** ($0.0175) | **22 minutes** |
| stop new fan-out | $35 | did not fire | **31 minutes** |
| refuse new billable steps | $50 | did not fire | **44 minutes** |

`tools/spend-guard.py` works and is accurate: run today at ~13:20Z it reported
`{"day":"2026-09-17","spendUsd":12.022302,"ceilingUsd":50.0,"warnUsd":25.0,"state":"OK","requests":6146,
"sessions":142,"unreadable":0,"basis":"local durable logs, lower bound, this machine only"}` in ~15 s, and
`report` independently totalled **$12.0223** over 6,146 requests. My rig's $0.0175 is **0.15 %** of that
day's spend over 2 % of its requests — the wire is cheap, the context is not, and the two views reconcile.

**And the arithmetic is the problem:** the guard's own hard ceiling of $50 is **44 minutes of the plan the
owner just described**. A ceiling that a normal evening crosses in under an hour is not a ceiling — it is a
tripwire laid exactly across the situation it was invented to catch, and a tripwire that fires on normal
work gets disabled. **The measured day (09-17) is already at ~$12.02, so the headroom from where it stands
to $50 is **33½ minutes** of 55-agent operation** — less than one fan-out. (33.5 min: $37.98 of headroom ÷
$68.02/hour. It is shorter than the 44 minutes above because it starts from $12.02, not from zero.)

*Two readings of the same day, deliberately reported as two:* `spend-guard.py` priced **6,146 requests /
$12.0223** at ~13:20Z while the log-scan script counted **6,102 requests** to 13:30Z. The guard's scan is
mtime-filtered and the rig's own 128 requests landed inside the window, so the two are consistent to
within the in-flight session the guard had not yet seen flushed — and the pair is a good demonstration of
why the guard is a *lower bound* (its own docstring says so) rather than a bill.

### 4.3 Is anything enforcing it today?

**No. Verified four ways, today, on the machine that would enforce it:**

| check | result |
|---|---|
| `packages/plugin-cost/src/` — is there a `guard.mjs`? | **`command.mjs`, `cost-core.mjs`, `session-log.mjs` only** |
| `packages/plugin-cost/cordis.patch.yml` — is the guard row mounted? | **13 lines; one `insert` for `id: plugin-cost` (`/cost`). No guard row.** |
| `settings/base.yaml` — is there a `spend-guard:` block? | **no match for `budget`, `ceiling`, `spend` or `guard`** |
| scheduled task, or `~/.dsh/spend-guard/day.json` state? | **no task matching `spend`/`dsh`/`harness`; `~/.dsh/spend-guard` does not exist** |

So: `doc 65`'s design is real, complete and *uninstalled*; `tools/spend-guard.py` is a **manual command**;
and the harness ships **no dollar cap at all** (grep of every `@deepseek-ai/*` package for
`budget|maxDailyUsd|ceiling|spendGuard|maxCostUsd` finds token budgets, byte budgets and quota-error
*detection* — never a cap).

**Observability, if the owner opens 10 windows tonight:** he cannot see spend as it accrues. There is no
counter on screen, no per-hour field, and no alert. The provider offers none either — **no
`x-ratelimit-*`, no usage headers, no usage API** (`/user/usage` and friends are 404s), and `/user/balance`
is a 2-decimal snapshot that a single request cannot move. The only two ways to know are (a) ask me to run
a 15-second scan, or (b) pull the console export by hand. **Everything else in this document is a
measurement; this is a gap, and it is the one that costs money.**

---

## 5. What the owner should set his ceiling to

**Recommendation: do not keep `$25 / $35 / $50`. Set `$35 warn / $80 stop-fan-out / $150 refuse`, and add a
concurrency ceiling of 12 generating agents per machine — because at 55 the *only* thing that stops the
spend is a number, and a number has to be big enough to survive a normal night.**

The reasoning, in the order it matters:

1. **$50 is 44 minutes of the plan the owner just described, and today is already 24 % of the way there
   by lunchtime.** A threshold crossed in the first hour of normal operation gets hit by accident, and a
   limit hit by accident gets raised by accident. A ceiling must sit above a *good* day, not above an
   average one. **$35 / $80 / $150 gives ~31 minutes / ~70 minutes / ~2.2 hours of 55-agent operation** —
   long enough to notice a fan-out going wrong, long enough to finish it, and still bounded at **2.7× the
   worst day ever recorded** ($54.92). Above $150 the design already knows what to do: `{kind:'reject'}`,
   the turn closes `blocked`, nothing is destroyed, the session resumes tomorrow.
2. **The concurrency cap is the cheap half of the same protection, and it is the one that addresses the
   untested assumption.** 12 generating agents per machine matches the *measured* machine ceiling
   (`84-calibration.md`: 14–39 turns before cores bind on the desktop, and the mesh broker's own 18-slot
   core term) *and* the measured historical peak (16–22 in-flight). Above 12, the laptop's own commit and
   core budget bind long before the provider's 2500 does — so a fleet-wide money cap alone would let the
   machines thrash while the wallet stayed green. **Cap both.**
3. **Keep the guard's shape exactly as doc 65 designed it** — a daily fleet counter with warn → stop
   fan-out → refuse, failing closed, because a fleet of ordinary sessions is what makes a big day (§65
   §2.4 measured that a $54.92 day is 79 sessions of ~$0.7, not one runaway). Only the numbers change.
4. **Then actually install it.** The design is written, the price card is reconciled to the console, the
   reporting half is proven, and the seam (`agent/pre-step` → `{kind:'reject'}`) is a shipped capability.
   The gap between doc 65 and a protected wallet is `guard.mjs`, one build-script line, one YAML row and
   one sync — not a research problem. **A ceiling that is not installed is a document, and the owner
   already has one of those.**

**Two free wins while he is at it.** (a) The chain has a **1.37 s Cloudflare Worker** in front of every
desktop request (`Server-Timing: cfWorker`), and the direct path's TTFB is **0.59 s vs 1.00 s** — if the
desktop's URL filter ever allows it, `deepseek-official` is strictly faster than the Worker. (b) Not one
of the 55 agents should ever be pointed at `secretary-fast` while it serves `deepseek-v4-pro` at **3–7×**
the flash rates (§1.2).

---

## 6. What I could not measure, and what would settle it

1. **A real `dsh --profile headless` turn on this machine hangs.** One process, 240 s, zero bytes out and
   zero bytes of stderr, killed. Not diagnosed, because diagnosing it means loading the owner's live
   laptop with more hung processes. *What would settle it:* run the same invocation with
   `--dump-config` and with a trivial profile in a scratch `DSH_HOME` — no engine restart, no shared
   state — and read where it blocks. **This blocks any future turn-level measurement on this host.**
2. **55 concurrent, and the provider's per-minute limiter (if it exists).** Not tested on purpose (§3).
   *What would settle it:* one metered hour at N = 32–55, reading the console export afterwards for the
   charge. **That hour is cheap in the wire sense — 44,673 requests at the fleet's own $0.001523 is only
   ~$68 — which is exactly why it is worth someone's deliberate yes rather than mine.**
3. **Whether the account can actually absorb 2.44 M prompt-tokens/s** (§4.1 assumption 2). Unpublished in
   both directions. *What would settle it:* the same metered hour, watching time-to-first-byte rather than
   error codes — at ~79× the worst day's token rate, the failure mode will be latency, not 429.
4. **End-to-end turn cost on this build.** My per-turn figure is `84-calibration.md`'s, not a fresh
   measurement, because of (1). *What would settle it:* one turn, then `spend-guard.py report` before and
   after — the plugin already prices it to the cent.
5. **The peak/off-peak split of a 55-agent night.** Off-peak is half price and the owner works late; the
   measured 30-day split is 78.3 % off-peak. If his 55-agent night runs 21:00–00:00 local, it runs entirely
   **inside** peak. *What would settle it:* the console export's own per-line prices (`peak_split.py`).

---

## 7. Every request I made, and what it cost

Counted from the rig's own JSON (`%TEMP%\gw96\gw96-*.json`), token totals summed over every 200 response:

| burst | route | requests | miss tok | hit tok | out tok | cost |
|---|---|---|---|---|---|---|
| small, streaming smoke, N=1 (`gw96-small-stream-…48704`) | proxy | 1 | 54 | 0 | 8 | $0.000013 |
| small, non-stream, N=1/4/8/16 (`gw96-small-…508243`) | proxy | 29 | 1,566 | 0 | 232 | $0.000374 |
| small, streaming, N=16 (`gw96-small-stream-direct-…36733`) | **direct** | 16 | 864 | 0 | 128 | $0.000206 |
| big 48.7k, streaming, N=1/4/8 (`gw96-big-stream-…557242`) | proxy | 13 | 50,878 | 582,144 | 47 | $0.009406 |
| big 48.7k, streaming, N=32 (`gw96-big-stream-…643349`) | proxy | 32 | 5,824 | 1,552,384 | 117 | $0.005601 |
| big 48.7k, streaming, N=8, `max_tokens` 1024 (`gw96-big-stream-…212719`) | proxy | 8 | 1,456 | 388,096 | 156 | $0.001476 |
| small, non-stream, N=1/4/8/16 — **the repeat that proved the curve is reproducible** (`gw96-small-…344288`) | proxy | 29 | 1,566 | 0 | 232 | $0.000374 |
| **rig total (all 7 runs)** | | **128** | **62,208** | **2,522,624** | **920** | **$0.01745** |
| authority gateway probes (`/v1/models` ×3, one 2-token completion) | `secratary` | 4 | ~350 | 256 | 2 | ~$0.00005 |
| header probe (direct + proxy) | both | 2 | ~120 | 0 | 0 | ~$0.00002 |
| `spend-guard.py report` / `check` (no network) | — | 0 | — | — | — | $0 |

**Cost: 2,522,624 hit × $0.003/M + 62,208 miss × $0.15/M + 920 out × $0.60/M = $0.00757 + $0.00933 +
$0.00055 = $0.01745** at the card's off-peak rates — **under two cents for 128 requests, including one
32-way burst and one 48.7 k-prompt burst at `max_tokens` 1024.** That is the honest, complete spend of this
document, **0.35 % of the $5 cap.** The lesson is in the last column: **the wire is nearly free and the
context is the bill** — the two `small` runs that sprawl across four concurrency levels each (58 requests,
four levels) cost less than **one** 48.7 k-token request sent cold.

Reproducibility: the small non-stream sweep was run **twice** and the second run landed on the first
(p50 by level — first run 1.90 → 1.27 → 1.13 → 1.00 s, second run 1.07 → 0.98 → 0.92 → 1.09 s; both
29/29 success, both **flat across the whole range** within the ~1 s service time). The curve is a property
of the service, not of one warm connection. *The repeat sweep is the one place this rig deliberately spends
twice to answer a point, and §7 counts it.*

Non-network commands run: none that spend money. Nothing was restarted; pid 4880 (the owner's live engine)
was alive at the start, throughout, and at the end of every burst.

---

## 8. Bottom line

* **The provider cannot be the reason 55 agents fail.** Limit 2500 concurrent, measured peak 16–22, tested
  to 32 with zero errors and 99.6 % cache hits. The first bend in the latency curve is +1.6 s at 32
  concurrent, and the ceiling is 78× further out. **55 in flight is 2.2 % of the published limit.**
* **The wallet is the ceiling, and it is uncapped.** ≈ **$68/hour** at 55 agents generating continuously
  off-peak (**$136/hour** peak; ≈ $27/hour at a realistic 40 % duty cycle; **$544 for an eight-hour
  night**). One hour of it is **1.24× the worst day the owner has ever had**, and it is **3.2× the busiest
  10 seconds the fleet has ever produced, held indefinitely**.
* **Nothing would stop it.** No guard installed, no budget key in the harness, no counter on screen, and
  no provider header to read. The $50 tripwire is **44 minutes** into the plan, and today's ordinary
  fleet has already spent **$12.02** of the $50 before lunch.
* **What to set:** `$35 / $80 / $150`, plus **12 generating agents per machine**, both capped, and install
  the guard that already exists on paper.
* **The one number to carry away:** on the fleet's own 30-day measured composition (`60-cost-audit.md`
  §1.3: $45.55 of $108.13 re-read context, $36.22 output, $26.35 cache-miss input — those three sum to
  $108.12, and the "$108.13" is the audit's own rounded header figure), **42 % of the bill is
  re-reading context that did not change, 33.5 % is what the model wrote, and 24 % is uncached input.** Every
  dollar of this plan is a context-management decision, not a concurrency decision. *The same split for
  this rig's own 128 requests is 43 % / 3 % / 53 %, because the rig wrote almost nothing — which is the
  point: the re-read share is stable across workloads and the output share is not.*
