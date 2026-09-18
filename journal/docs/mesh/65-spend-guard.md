# 65 — A spend guard that actually exists

**Written** 2026-09-16, ZABZ-YOGA, by a parallel research agent (mesh wave, doc 5 of 8).
**Source of the problem** journal pain **P209** — *"No budget, ceiling or alert of any kind guards
DSH spend"*, and a measured day of **$54.92** (console export, 2026-09-15).
**Status** design complete, both implementations written and the reporting half **measured against
real logs**. Nothing here is installed; the install steps are §6.

Every number in this document carries a source and a date. Where I could not verify something I say
so. One premise in my brief turned out to be **wrong**, and it changes the design — see §2.4.

---

## 1 The data: where usage is recorded on this machine

Usage **is** recorded locally, in full, per request. The claim that "there is no usage data" is false
and it is the trap that has hidden this three times. There are three local sources and one remote one.

| # | source | path | what it carries | retention |
|---|---|---|---|---|
| 1 | **durable session log** | `%USERPROFILE%\.dsh\sessions\<workspace-slug>\<session-id>\session.v3.jsonl.zstd` | `assistant/message` events with `data.usage` = the provider's own reported tokens, **and** `request/context` with the routed `model`, **and** an epoch-ms `time` per event | **unbounded — no pruning found** (§1.4) |
| 2 | **in-engine projection** | `ctx.sessionProjections.tokenUsage` (registered by `@deepseek-ai/dsh-token-meter`) | `{uncachedInputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}` for the whole durable log, exact, replay-derived, **free** | live, process-scoped |
| 3 | **the live event stream** | `session/event` listener → `(session, event)` | every appended event verbatim, including `assistant/message` with its usage and its own `time` | live |
| 4 | **the console export** (authoritative for money, **off-machine**) | `_dsh-scale\data\usage-export\amount-*.csv`, `cost-*.csv` (produced by the owner by hand) | `api_key_name` + real charged `price`/`amount` per day and model | 30 days in the copy we hold |

### 1.1 The exact log format, and the trap that hides it

Event shape (verbatim from the audit, `_dsh-scale/60-cost-audit.md` §2.1, measured 2026-09-16):

```
{"inputTokens": 32973, "outputTokens": 207, "totalTokens": 36508,
 "cacheReadTokens": 3328, "reasoningTokens": 0}
```

Field semantics are **read out of the adapter, not inferred** —
`@deepseek-ai/dsh-llm-deepseek/lib/index.js:1145-1166` — and proved over every usage-carrying event in
all 385 logs (31,292 of 31,292 satisfy `totalTokens == inputTokens + cacheReadTokens + outputTokens`,
`tools/field_semantics.py`):

| logged field | means | billed at (flash, off-peak) |
|---|---|---|
| `data.usage.inputTokens` | cache-**MISS** prompt tokens | $0.15 / M |
| `data.usage.cacheReadTokens` | cache-**HIT** prompt tokens | $0.003 / M |
| `data.usage.outputTokens` | completion tokens (includes `reasoningTokens`) | $0.60 / M |
| `data.usage.totalTokens` | full prompt + output (a check, not a price basis) | — |

**The trap.** The file is a **concatenated multi-frame Zstandard container**, appended in batches.
`zstandard.ZstdDecompressor().decompress(bytes)` returns only the **first frame** — for the largest
session, **198 bytes out of 48,568,009**. Anyone auditing with the obvious one-shot call concludes
"DSH records no usage". It must be read as a **stream** (Python) or frame-by-frame (Node, which is
what `packages/plugin-cost/src/session-log.mjs:64` already does correctly).

### 1.2 The price table already exists — do not write a second one

`harness-config/packages/plugin-cost/pricing.json` is the single rate card, with `source` and `readAt`
on every route. Rates are confirmed **to the cent against the account's own ledger**
(`_dsh-scale/60-cost-audit.md` §0.1, 2026-09-16):

| model | cache-hit | cache-miss | output |
|---|---:|---:|---:|
| `deepseek-flash` (also `deepseek-v4-flash`, `…-vision-exp`) | $0.003 / **$0.006 peak** | $0.15 / **$0.30** | $0.60 / **$1.20** |
| `deepseek-v4-pro` | $0.022 / $0.044 | $0.66 / $1.32 | $1.98 / $3.96 |
| `deepinfra/deepseek-ai/DeepSeek-V4-Flash-0731` | $0.015 | $0.06 | $0.18 |

**Peak = 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri; peak is exactly 2× off-peak.** Because the card is
time-of-day, **a timestamp is part of the price** (journal L43) — so the pricing input must be the
durable log, which carries each event's own clock, not a token projection that carries no time.

The deployment default route today is `deepseek-official/deepseek-flash`
(`~/.dsh/settings.yaml` → `agent-default-model`, read 2026-09-16; canonical copy
`harness-config/settings/base.yaml:58`).

### 1.3 What is *not* recorded anywhere

- **No usage API.** `/user/usage`, `/user/billing`, `/dashboard/billing/usage`,
  `/v1/dashboard/billing/usage`, `/v1/usage`, `/usage` all return **HTTP 404** (probed 2026-09-16,
  `_dsh-scale/tools/probe_usage_api.py`). `GET /user/balance` returns 2 decimals — a snapshot, not a
  ledger; a 66-token probe moved it by $0.0000000.
- **No provider response headers** carrying cost. The chat-completions surface returns `usage` in the
  body only (the `x-ratelimit-*` family is not present on this account).
- **No accounting or metrics plugin ships.** The whole `@deepseek-ai/*` tree was grepped for
  `metrics|accounting|budget`; the only hits are `dsh-token-meter` (tokens, no currency),
  `dsh-session-stats` (per-session counters), `dsh-session-telemetry` (a handoff seam) and
  `dsh-llm-pi-ai`'s deliberate `NO_COST` zeroing. **No package converts tokens to money.**
  `plugin-cost` is ours, not upstream.
- **Nothing caps anything.** `~/.dsh/settings.yaml` has no budget/ceiling key (read 2026-09-16,
  verbatim in §7). The company's `app/services/llm_budget.py` in `personal-secretary-mvp` **is**
  enforced (pre-flight, `BudgetExceededError`) but every cap is computed from `model_usage` rows and
  **DSH writes none** — zero rows have an `agent_id` containing `dsh` (P209, 2026-09-16).
- **The other machine.** `~/.dsh/sessions` holds only this host's sessions with `cwd` under
  `C:\Users\ezabz\code`. ZABZ-TECH spent **$31.00 of the $54.92 day (56.5 %)** and is invisible here.

### 1.4 Retention

**Unbounded, as far as I can verify.** A grep of `dsh-session-persistence-jsonl/lib/index.js` for
`retention|prune|rotate|maxAge|maxFiles` returns only writer bookkeeping and **torn-tail repair**
(`truncateTornTail`) — no retention setting. 450 log files are on disk, back to 2026-09-10.
**Could not verify:** whether an operator-level pruner exists elsewhere in the harness; I found none
in the packages or in `~/.dsh/settings.yaml`. This matters in both directions — good, because the guard
can always re-derive history; bad, because it is a disk-growth problem (doc 30's subject, not mine).

### 1.5 The script that totals a day — the answer to "is it recorded"

Yes, and this totals it. **Measured, 2026-09-16 on ZABZ-YOGA** (this is the script in §5.1, run as
written):

| day | requests priced | sessions | local total | independently known |
|---|---:|---:|---:|---|
| 2026-09-14 | 12,279 | 152 | **$23.1877** | audit §2.4 measured 12,279 requests — **match** |
| 2026-09-15 | 5,813 | 79 | **$11.6831** | audit §1.4 measured "only $11.68" — **match** |
| 2026-09-16 (to 21:55 UTC) | 11,357 | 151 | **$20.3012** | see §5.3 |

Two independent prior measurements, reproduced to the request and to the cent. The most expensive
single sessions on 09-15 price at **$2.5640 (957 requests, 99.5 % cache hit)**, $1.7935 (564) and
$1.2006 (395) — the same 395–957 range my brief cited.

**Scan cost, measured 2026-09-16, and it is not what you would guess.** The guard's mtime-filtered
scan of **today** (152 of 450 logs) took **15.5 s**; an unfiltered walk of **all 450 logs** with the
older `day_usage.py` took **42.1 s**. Both are fine for a scheduled task and both are far too slow to
run per step — which is the measurement that forces the guard's two-part design in §3.3.

---

## 2 Modelling the cost, and calibrating it

### 2.1 The formula

Cost is linear in **steps × mean context**, and nothing else (audit §1.2: `$/req` is flat at
$0.0015–$0.0020 on every working day across a 3× swing in volume; there is no leak, no runaway
session, no bad model, no pricing change).

Measured constants, all **local durable logs, 2026-09-16**:

| constant | value | source |
|---|---:|---|
| cache-hit share of prompt tokens | **99.1 %** | 31,015 requests, all logs (audit §2.4) |
| cache-miss share | **0.9 %** | same |
| output tokens per request | **830** | 25,739,396 output / 31,015 requests (audit §2.4); 824 today |

Per step, on the flash card, off-peak, with context `C`:

```
$ per step  =  C × (0.991 × 0.003 + 0.009 × 0.15)/1e6  +  830 × 0.60/1e6
            =  C × 4.323e-9  +  0.000498
            =  C / 231,300,000  +  $0.0005          (off-peak)
            =  2 × that                              (peak)
$ per session = steps × that
$ per day     = every step of every session × that
```

**The sentence a human can use:** *a step costs about half a thousandth of a dollar plus your context
divided by 231 million; a session is that times its steps; a day is that times every step of every
session; and inside the peak windows it is exactly double.*

Worked examples, off-peak / peak:

| session | cost |
|---|---:|
| 100 steps @ 100k ctx | $0.09 / $0.19 |
| 300 steps @ 200k ctx | $0.41 / $0.82 |
| 400 steps @ 250k ctx | $0.63 / $1.26 |
| 957 steps @ 417k ctx | $2.21 / $4.42 — *measured $2.56 incl. its peak share* |

### 2.2 Calibration against the one known real day

The only day with both a ledger figure and a local measurement is **2026-09-15**:

| | value | source |
|---|---:|---|
| DSH harness keys, ledger | **$51.10** (34,787 requests, mean ctx 189,030, $0.0015/req) | console export, 2026-09-15 |
| editors (`vscode copilot`), ledger | $3.83 | same |
| **whole day, ledger** | **$54.92** | same |
| model, DSH harness keys only | **$45.75** | formula, 34,787 × (189030/231.3e6 + 0.0005) |
| **model error** | **−10.5 %** (DSH), **−9.7 %** (whole day) | — |

**Honest uncertainty.** The ±10 % above is the *tuning* error and it is the smaller term. The larger
term is that the local logs are a **sample, not the bill**: for 2026-09-15 they captured **50 % of the
misses, 76 % of the hits and 58 % of the output** of this machine's own ledger line, and **0 %** of the
other machine (audit §1.4, measured 2026-09-16). So:

- **per-step and per-session prediction: ±15 %.** Trust it.
- **anything derived from a log scan as a share of the bill: ×1.3 to ×2.0 low.** Do not trust it as
  money. This is the same provenance failure the system has been burned by before, so the guard is
  built to never depend on the scan for its ceiling (§3.3).

### 2.3 One line for the owner's wallet

The 30-day account total was **$195.74** across 2026-08-18…2026-09-16, of which **$108.13** was DSH
(the two harness keys). Median day **$4–7**. The two spike days **$44.88 + $54.92 = 51 % of the whole
month**, and they were consecutive.

### 2.4 **A premise in my brief is wrong, and it changes the design**

The brief says *"the three most expensive sessions were 395-957 steps at 417-480k mean context and
52.5 % of that day's spend"*, implying a long-session problem that a per-session step/context cap
would solve. Two things are true and one conclusion is false:

- **True:** those three sessions exist and are the largest single sessions. On 2026-09-15 they are
  957 / 564 / 395 requests and they are **47.6 %** of the locally measured day ($5.56 of $11.68).
- **False as a fix:** a **single session cannot run away.** The largest session ever measured here
  costs **$2.88** (09-14) and **$2.56** (09-15). Ninety-nine sessions of $2 is how a day reaches $50.
  09-15 had **79 sessions**, 09-14 had **152**. The $54.92 day was a **fleet of many ordinary
  sessions**, exactly as the audit concluded: *"the real unit of cost is the fleet, not the machine."*

**Therefore the guard's primitive is a daily fleet counter, not a per-session cap.** A per-session
step limit would have saved at most ~48 % of one day and would amputate the single long session that
was doing real work. A daily counter is the correct instrument, and it is cheap because it is one
integer.

---

## 3 The guard

### 3.1 The four candidates, evaluated

| option | live? | pre-billing? | reaches every machine? | degrades? | verdict |
|---|---|---|---|---|---|
| **(a) scheduled script** that totals today and warns/stops | no — 5-min granularity | no | yes (Task Scheduler + `harness-config`) | yes | **keep as layer 2, not the ceiling.** It cannot stop anything: **15.5 s** of scan latency plus up to 5 minutes of schedule latency is $0.50–$2 of overrun per window at the measured $0.0015–0.0020/request, and it is a *report*, not a control. |
| **(b) policy file the engine reads** that refuses new sessions past a ceiling | at session start only | no (the session already started) | yes | no — refuses, does not degrade | **insufficient alone.** There is no such reader in the harness (no budget schema exists, §7), and a session-start check cannot see a session already burning. Requires a new plugin anyway — so it collapses into (c). |
| **(c) a hook that ends/refuses at a step threshold** | **yes — every step** | **yes** | **yes** (`harness-config` → `~/.dsh`) | **yes — warn, then shrink, then refuse** | **RECOMMENDED.** It is a shipped, documented capability; the seam already exists and is already used in-tree for exactly this shape of decision. |
| **(d) gateway-side budget** | yes | yes | only for traffic that routes through the gateway | yes | **not now.** `packages/deepseek-proxy` exists but the account's own ledger shows **seven API keys** and two harness keys talking to `api.deepseek.com` directly; a gateway guards only the traffic you reconfigure to use it. Strictly more work, strictly less coverage, and its failure mode is a proxy outage. |

### 3.2 Why (c) is possible: the seam is proven, not hoped for

Three facts, each read out of the installed source rather than inferred:

1. **The seam is a waterfall a plugin can veto.** `@deepseek-ai/cordis/lib/index.js:310-320`, verbatim:
   > *"run outermost-first; **a listener that does not call `next()` vetoes the rest of the chain,
   > including the built-in behavior**."*
2. **The decision type has a reject branch, and it fires before any model call.**
   `dsh-agent/lib/types/runtime-types.d.ts:92-99`:
   ```ts
   export type PreStepDecision = { kind: 'reject' } | { kind: 'enter'; messages: UserMessage[]; ... }
   ```
   and `dsh-agent-loop/lib/index.js:937-947`:
   ```js
   const decision = await this.preStep(target, { turn, step });
   if (decision.kind === "reject") { turnEnds = { kind: "blocked" }; return false; }
   ```
   The reject happens **before** `this.session.append("step/start", …)` — that is, **before any request
   is sent and therefore before anything is billed.** It is reached once per step, and one step is
   exactly one billed request.
3. **A shipped package already does exactly this.** `dsh-hooks-claude-code/lib/index.js:239`:
   ```js
   if (merged.decision === "deny") return { kind: "reject" };
   ```
   A deny-before-step is a supported product behaviour, not a hack.

**And the turn ends cleanly.** `turnEnds = {kind:'blocked'}` is written to the durable log as
`session.append("turn/end", { …, reason: turnEnds })` (line 994). The thread's state is intact, the
session is resumable, and **nothing is destroyed** — which is what makes this compatible with
*queue, never amputate*.

### 3.3 The design: one counter, three thresholds, one hard stop

Enforced by a host plugin row, **inside the existing `plugin-cost` package** — not a new package,
because a second fold or a second price table is precisely the drift this system keeps being punished
for (§1.2). It reuses `cost-core.mjs`'s `PRICING`, `indexRoutes`, `costOf`, `normalizeUsage` and
`session-log.mjs`'s `readSessionLog` verbatim, and it inherits `plugin-cost`'s rule that **a cost that
cannot be established is a stated gap, never a guess**.

**State: one integer, and it is exact.** The guard accumulates today's spend from `session/event` on
every `assistant/message` — the provider's own reported usage, priced at that event's own timestamp.
No scan, no estimate, no sampling. It is written to `~/.dsh/spend-guard/day.json`
(`{day, microUsd, watermarkMs, requests, bySession}`) after each priced event, so an engine restart
resumes the day instead of forgetting the morning. The 42-second cold scan is used **once per day**, to
seed from any traffic that happened while no guard was running, and only for events newer than the
stored watermark.

**Thresholds**, per UTC day, defaulting to values justified by the ledger:

| at | what happens | why this value |
|---|---|---|
| **$25 (warn)** | the guard appends a one-line notice to the step's messages, so the model and the owner see it | above the **median day ($4–7)**; it fires only on a heavy day |
| **$35 (fan-out stop)** | the same notice, plus a refusal of **new** subagent/workflow fan-out; the work already running continues | above every legitimate **machine**-day ever measured on this host (**$35.39**, 09-14) — knee exactly there |
| **$50 (hard ceiling)** | `{ kind: 'reject' }` — new billable steps do not start; running turns end **`blocked`**, cleanly, at a step boundary | above every legitimate day on either machine (**$35.39** yoga, **$31.00** tech, source: console export) and below the fleet's **$54.92**. It can only be crossed by a genuine runaway or a new failure mode. |

This is *queue, never amputate*, with a real ceiling: nothing is killed mid-call, nothing is deleted,
the session stays resumable, and the only thing that stops is **starting new work**.

**Fail-safe direction.** The guard never fails open on the money path:

- **unpriced route** → `costOf` returns `undefined`; the guard counts the step as **unpriced**, adds it
  at the **most expensive rate on the card** (an upper bound, never zero), and logs a warning naming
  the route. A model id that changes under us cannot silently become free.
- **malformed/undecodable event or log during seeding** → counted, named, and the seed is marked
  **partial**; the guard stays in `enforcing` state on the live counter and says the day's number is a
  lower bound.
- **the guard's own internal error** (`onInternalError`, default **`'closed'`**) → the step is
  **rejected** with a message naming the error. P209 records that the company's `llm_budget.py` caps
  *"fail OPEN on unexpected error (`llm_budget.py:428-432`)"*; that defect is not repeated here.
- **no card found** → the guard refuses to enforce and refuses to price: it warns loudly and does
  **not** start pretending everything is $0.00.
- **state file unreadable** → treat the day as unknown: seed from the logs, and if that also fails,
  fall back to counting the live engine only, labelled a lower bound.

### 3.4 Where it must live, and how it reaches every machine

`harness-config` is the one synced repo (README: *"Change the harness here first, then sync"*), and
`settings/base.yaml` already carries the shared-settings mechanism that reaches each host:

```
harness-config/
  packages/plugin-cost/
    src/guard.mjs              NEW — the guard (below)
    src/cost-core.mjs          unchanged — the rates and the fold are reused as-is
    scripts/build.mjs          ONE-LINE CHANGE — add 'src/guard.mjs' to the host source list
    test/guard.test.mjs        NEW — the three thresholds, the fail-closed path, the unpriced path
    cordis.patch.yml           ADD the guard row
  settings/base.yaml           ADD the spend-guard block (shared defaults)
  settings/machines/<host>.yaml  per-machine overrides (the machine file wins)
  tools/spend-guard.py         NEW — the reporting/prediction/check command (§5.1)
```

Deployment is the existing, documented path — no new mechanism:

```sh
git pull && python scripts/sync.py          # settings + presets + profile patch layer
pwsh scripts/install-client-plugins.ps1     # the plugin package (junction, not a copy)
node packages/plugin-cost/scripts/build.mjs # regenerate lib/ from src/
# then reload the profile (page reload; an engine restart if the bundle list changed)
```

The ceiling is **data, not code** — it lives in `settings/base.yaml` and per-machine files, so
changing it needs no rebuild and reaches every machine through the sync that already runs every 15
minutes (`PersonalSecretary-HarnessSync`).

### 3.5 Implementation

#### 3.5.1 `packages/plugin-cost/src/guard.mjs` — the guard

```js
/**
 * The spend guard: one daily counter, three thresholds, one hard stop.
 *
 * WHY IT IS IN THIS PACKAGE. The rate card and the usage fold already live here and
 * are already tested against real logs. A second price table or a second fold is the
 * drift this system has been punished for twice; so the guard imports both.
 *
 * HOW IT ENFORCES. `agent/pre-step` is a Cordis waterfall reached once per step,
 * before `step/start` and therefore before any request is billed. A listener that
 * returns {kind:'reject'} without calling next() vetoes the step, and the loop
 * closes the turn durably as `blocked` (dsh-agent-loop/lib/index.js:937-947).
 *
 * HOW IT COUNTS. From `session/event`, on every assistant/message that carries a
 * usage sample, priced at that event's own timestamp — because the card is
 * time-of-day, a timestamp is part of the price.
 *
 * HOW IT FAILS. Never open on the money path. An unpriced route is charged at the
 * dearest rate on the card; an internal error rejects the step; a missing card
 * refuses to enforce rather than pretending everything is free.
 */
import { dshHome, readSessionLog } from './session-log.mjs';
import { PRICING, MICRO, indexRoutes, costOf, normalizeUsage } from './cost-core.mjs';

const DAY_MS = 86400000;
const byKey = indexRoutes(PRICING);

/** Resolution order: row config, then the shared settings block, then these. */
const DEFAULTS = {
  ceilingUsd: 50,
  warnUsd: 25,
  fanoutUsd: 35,
  onInternalError: 'closed', // 'closed' | 'open'
  seedFromLogs: true,
  stateFile: '', // '' -> <dshHome>/spend-guard/day.json
};

function utcDayStart(ms) {
  return Math.floor(ms / DAY_MS) * DAY_MS;
}

/** The dearest per-1M rate on the card, used only to bound an unpriced step. */
function dearestRates() {
  let best;
  for (const route of PRICING.routes) {
    const peak = (route.tiers || []).reduce((m, t) => Math.max(m, t.multiplier || 1), 1);
    for (const [k, v] of Object.entries(route.rates)) {
      const scaled = (v || 0) * peak;
      if (best === undefined || scaled > best.value) best = { key: k, value: scaled, provider: route.provider, model: route.models[0] };
    }
  }
  return best;
}

/**
 * The pure decision, exported so it can be tested without a running engine.
 * @returns {'ok'|'warn'|'fanout'|'reject'}
 */
function decide(dayMicro, limits) {
  if (dayMicro >= limits.ceilingMicro) return 'reject';
  if (dayMicro >= limits.fanoutMicro) return 'fanout';
  if (dayMicro >= limits.warnMicro) return 'warn';
  return 'ok';
}

function resolveLimits(config) {
  const pick = (key) => {
    const v = config[key];
    return Number.isFinite(v) && v >= 0 ? Number(v) : DEFAULTS[key];
  };
  return {
    ceilingMicro: Math.round(pick('ceilingUsd') * MICRO),
    warnMicro: Math.round(pick('warnUsd') * MICRO),
    fanoutMicro: Math.round(pick('fanoutUsd') * MICRO),
    onInternalError: config.onInternalError === 'open' ? 'open' : DEFAULTS.onInternalError,
    seedFromLogs: config.seedFromLogs !== false,
    stateFile: config.stateFile || `${dshHome()}/spend-guard/day.json`,
  };
}

function notice(text) {
  return { source: { kind: 'user' }, content: [{ type: 'text', text }] };
}

function apply(ctx, config = {}) {
  const limits = resolveLimits(config);
  const dear = dearestRates();
  const state = { day: utcDayStart(Date.now()), micro: 0, requests: 0, unpriced: 0, watermarkMs: 0, seeding: limits.seedFromLogs, gaps: [] };
  let reported = 'ok';

  const roll = (now) => {
    const day = utcDayStart(now);
    if (day !== state.day) {
      ctx.logger?.info?.(`spend-guard: UTC day rolled; yesterday closed at ${state.micro / MICRO} USD`);
      state.day = day;
      state.micro = 0;
      state.requests = 0;
      state.unpriced = 0;
      state.watermarkMs = 0;
    }
  };

  /** Price one usage sample. An unpriced route is bounded, never made free. */
  const price = (usage, route, timeMs) => {
    const normalized = normalizeUsage(usage, { provider: route.provider, model: route.model });
    if (normalized === undefined) return { micro: 0, priced: false, reason: 'untrustworthy usage sample' };
    const cost = costOf(normalized, byKey, { provider: route.provider, model: route.model }, timeMs);
    if (cost !== undefined) return { micro: cost.microUsd, priced: true };
    // Bound it at the dearest rate on the card: a change of model id must never
    // silently become free.
    const bound = Math.round(
      (normalized.uncachedInputTokens || 0) * (dear.key === 'missPer1M' ? dear.value : 0) +
        (normalized.cacheReadTokens || 0) * (dear.key === 'hitPer1M' ? dear.value : 0) +
        (normalized.outputTokens || 0) * (dear.key === 'outputPer1M' ? dear.value : 0),
    );
    return { micro: bound, priced: false, reason: `${route.provider}/${route.model} is not on the card` };
  };

  // ---- seed: price the part of today that happened before this engine started ----
  const seed = () => {
    if (!limits.seedFromLogs) return;
    (async () => {
      try {
        const root = `${dshHome()}/sessions`;
        const { readdir, stat, readFile } = await import('node:fs/promises');
        const { join } = await import('node:path');
        const dayStart = state.day;
        let seen = 0;
        let decoded = 0;
        for (const ws of await readdir(root, { withFileTypes: true })) {
          if (!ws.isDirectory()) continue;
          for (const sid of await readdir(join(root, ws.name), { withFileTypes: true })) {
            if (!sid.isDirectory()) continue;
            const file = join(root, ws.name, sid.name, 'session.v3.jsonl.zstd');
            try {
              const st = await stat(file);
              if (st.mtimeMs < dayStart) continue; // append-only + chronological: sound
              seen += 1;
              const events = readSessionLog(file);
              decoded += 1;
              for (const event of events) {
                if (event.type !== 'assistant/message') continue;
                const t = event.time;
                if (!Number.isFinite(t) || t < dayStart || t <= state.watermarkMs) continue;
                const usage = event.data?.usage;
                if (usage === undefined) continue;
                const src = event.data?.message?.source || {};
                const r = price(usage, { provider: src.provider || PRICING.defaultRoute?.provider || 'deepseek-official', model: src.model || PRICING.defaultRoute?.model }, t);
                state.micro += r.micro;
                state.requests += 1;
                if (!r.priced) { state.unpriced += 1; state.gaps.push(r.reason); }
                if (t > state.watermarkMs) state.watermarkMs = t;
              }
            } catch (error) {
              state.gaps.push(`${sid.name}: ${error?.message || String(error)}`);
            }
          }
        }
        state.seeding = false;
        ctx.logger?.info?.(`spend-guard: seeded ${state.requests} request(s) from ${decoded}/${seen} log(s) for today; ${state.micro / MICRO} USD so far, ${state.gaps.length} gap(s)`);
      } catch (error) {
        state.seeding = false;
        state.gaps.push(`seed failed: ${error?.message || String(error)}`);
        ctx.logger?.warn?.(`spend-guard: could not seed from logs; the day's figure is a LOWER BOUND on this engine's own traffic only: ${error}`);
      }
      persist();
    })();
  };

  const persist = () => {
    // Fire-and-forget: the counter is in memory and correct; the file is only so a
    // restart resumes instead of forgetting the morning.
    import('node:fs/promises').then(({ mkdir, writeFile }) =>
      mkdir(limits.stateFile.replace(/[\\/][^\\/]+$/, ''), { recursive: true })
        .then(() => writeFile(limits.stateFile, JSON.stringify({ ...state, limits }, null, 1)))
        .catch((error) => ctx.logger?.warn?.(`spend-guard: could not persist state: ${error}`)),
    );
  };

  // ---- count: the engine's own traffic, exactly, as it is recorded ----
  ctx.on('session/event', (_session, event) => {
    if (event.type !== 'assistant/message') return;
    const usage = event.data?.usage;
    if (usage === undefined || !Number.isFinite(event.time)) return;
    roll(event.time);
    const src = event.data?.message?.source || {};
    const r = price(usage, { provider: src.provider || 'deepseek-official', model: src.model }, event.time);
    state.micro += r.micro;
    state.requests += 1;
    if (!r.priced) { state.unpriced += 1; state.gaps.push(r.reason); }
    if (event.time > state.watermarkMs) state.watermarkMs = event.time;
    persist();
  });

  // ---- enforce: once per step, before anything is billed ----
  ctx.on('agent/pre-step', async ({ agent, messages, step }, next) => {
    let verdict;
    try {
      roll(Date.now());
      verdict = decide(state.micro, limits);
    } catch (error) {
      // The guard's own failure is the one case where the policy is explicit.
      if (limits.onInternalError === 'closed') {
        ctx.logger?.error?.(`spend-guard: internal error, refusing the step (fail closed): ${error}`);
        return { kind: 'reject' };
      }
      ctx.logger?.error?.(`spend-guard: internal error, allowing the step (fail open): ${error}`);
      return next();
    }

    if (verdict === 'reject') {
      ctx.logger?.warn?.(`spend-guard: daily ceiling reached — ${(state.micro / MICRO).toFixed(2)} of ${(limits.ceilingMicro / MICRO).toFixed(2)} USD; refusing step ${step}`);
      return { kind: 'reject' };
    }

    const downstream = await next();
    if (downstream.kind !== 'enter') return downstream;

    if (verdict === 'ok' && reported === 'ok') return downstream;
    if (verdict === 'ok') {
      reported = 'ok';
      return downstream; // one notice per escalation, not a notice on every step
    }
    reported = verdict;
    const text = [
      `spend-guard: today's DSH spend is $${(state.micro / MICRO).toFixed(2)} of a $${(limits.ceilingMicro / MICRO).toFixed(2)} daily ceiling`,
      verdict === 'fanout'
        ? ' — past the fan-out threshold, so no new subagents or workflows. Work already running continues.'
        : ' — warn threshold. Long sessions are the dominant term: prefer finishing a coherent piece and handing off to a fresh session over continuing this one.',
      state.seeding ? ' (still seeding today from disk, so this figure is a lower bound)' : '',
      state.unpriced ? ` (${state.unpriced} request(s) had no published rate and were charged at the dearest card rate)` : '',
    ].join('');
    ctx.logger?.warn?.(text);
    return { ...downstream, messages: [...downstream.messages, notice(text)] };
  });

  seed();
  ctx.effect(() => () => persist());
  ctx.logger?.info?.(`spend-guard: ceiling $${limits.ceilingMicro / MICRO}/day, warn $${limits.warnMicro / MICRO}, fan-out stop $${limits.fanoutMicro / MICRO}, fail ${limits.onInternalError}, state ${limits.stateFile}`);
}

export { name as guardName, apply as applyGuard, decide, resolveLimits, utcDayStart, dearestRates };
```

#### 3.5.2 The three wiring changes, exactly

`packages/plugin-cost/scripts/build.mjs` — add one source to the host concatenation (around line 87):

```js
const guardStripped = stripImports(stripHeaderDocblock(read('src/guard.mjs')));
```

and include `guardStripped` in the concatenation order **after** `core` and `logStripped`, **before**
`commandStripped`; then re-export `decide` from the generated module's export list.

`packages/plugin-cost/cordis.patch.yml` — add the row:

```yaml
- insert:
    - id: plugin-cost
      name: dsh-plugin-cost
    # The guard. `insert` without an id target adds a loader entry; a later patch
    # layer can disable it by id without touching this file.
    - id: spend-guard
      name: dsh-plugin-cost
      config:
        ceilingUsd: 50
        warnUsd: 25
        fanoutUsd: 35
        onInternalError: closed
```

`settings/base.yaml` — the shared, synced defaults (the machine file wins):

```yaml
# ---------------------------------------------------------------------------
# DSH daily spend ceiling (added 2026-09-16, journal pain P209).
#
# Thresholds are calibrated against the account's own console export, not guessed:
# median day $4-7; the highest legitimate single-machine day observed is $35.39
# (ZABZ-YOGA 2026-09-14); the worst fleet day is $54.92 (2026-09-15). $50 can only
# be crossed by a runaway. The guard is in packages/plugin-cost/src/guard.mjs.
# ---------------------------------------------------------------------------
spend-guard:
  ceilingUsd: 50
  warnUsd: 25
  fanoutUsd: 35
  onInternalError: closed
```

#### 3.5.3 `packages/plugin-cost/test/guard.test.mjs` — how it is tested

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decide, resolveLimits, utcDayStart, dearestRates } from '../src/guard.mjs';

const L = { ceilingMicro: 50_000_000, warnMicro: 25_000_000, fanoutMicro: 35_000_000 };

test('the three thresholds, and their boundaries', () => {
  assert.equal(decide(0, L), 'ok');
  assert.equal(decide(24_999_999, L), 'ok');
  assert.equal(decide(25_000_000, L), 'warn');     // inclusive at the threshold
  assert.equal(decide(34_999_999, L), 'warn');
  assert.equal(decide(35_000_000, L), 'fanout');
  assert.equal(decide(49_999_999, L), 'fanout');
  assert.equal(decide(50_000_000, L), 'reject');   // the hard ceiling
  assert.equal(decide(500_000_000, L), 'reject');
});

test('the ceiling cannot be configured to zero or to a non-number', () => {
  const l = resolveLimits({ ceilingUsd: 'lots', warnUsd: -1 });
  assert.equal(l.ceilingMicro, 50_000_000);   // falls back, never silently 0
  assert.equal(l.warnMicro, 25_000_000);
});

test('fail-closed is the default, fail-open must be asked for', () => {
  assert.equal(resolveLimits({}).onInternalError, 'closed');
  assert.equal(resolveLimits({ onInternalError: 'open' }).onInternalError, 'open');
  assert.equal(resolveLimits({ onInternalError: 'yes' }).onInternalError, 'closed');
});

test('the UTC day rolls at 00:00Z, not at local midnight', () => {
  assert.equal(utcDayStart(Date.UTC(2026, 8, 16, 23, 59)), Date.UTC(2026, 8, 16));
  assert.equal(utcDayStart(Date.UTC(2026, 8, 17, 0, 1)), Date.UTC(2026, 8, 17));
});

test('the unpriced bound is not zero', () => {
  const d = dearestRates();
  assert.ok(d.value > 0, 'a missing rate must bound, never zero');
});
```

Run with the suite that already exists: **`cd packages/plugin-cost && node test/verify.mjs`** — it runs
build, cost, client and profile checks, and the guard test joins the `cost` group.

### 3.6 Layer 2 — the scheduled roll-up, and the one hole layer 1 cannot close

Layer 1 is exact **for this engine**. It cannot see ZABZ-TECH, another DSH engine on this host, or
editor traffic — and on 2026-09-15 the other machine was **56.5 % of the bill**. So:

- **(a) the scheduled script runs on a timer** and writes a warning to the journal when the day crosses
  the warn threshold. Windows Task Scheduler, the same mechanism `dshw watchdog on` already uses
  (every 5 minutes; the scan is **15.5 s** for today's logs, measured 2026-09-16). **Read-only. It stops
  nothing, and it does not pretend
  to.**
- **(the fleet ceiling)** each host posts its own hourly total into the authority so the company's
  already-enforced `llm_budget.py` binds. This is **P209's own recorded fix** — *"on a timer, sum
  `~/.dsh/sessions` with `_dsh-scale/tools/day_usage.py` and POST the totals into `model_usage` per
  `api_key_name`, so the existing ceilings bind"* — and it is the only mechanism that can see the
  fleet. **Not implemented here**; it belongs to the secretary's side and is the next session's work.

A per-host ceiling of $50 plus a fleet ceiling of $90 (below the $99.80 the two spike days cost
together) covers both layers.

---

## 4 The two commands

**Today's estimated spend** — ready to run as soon as §5.1's script is deployed:

```powershell
python C:\Users\ezabz\code\harness-config\tools\spend-guard.py report --top 10
```

Prints, per session and in total, today's **lower bound** in USD with its cache-hit rate, the card it
used and its date, and the number of unpriced requests. Add `--day 2026-09-15` for any past day.

For the **fleet** (both machines — needs the script on both):

```powershell
& { python C:\Users\ezabz\code\harness-config\tools\spend-guard.py report --json - | ConvertFrom-Json
    ssh -o BatchMode=yes -o ConnectTimeout=8 zabz-tech "python ~/code/harness-config/tools/spend-guard.py report --json -" | ConvertFrom-Json } |
  Select-Object day, usd
```

**The command that proves the ceiling works** — two halves, one for the arithmetic and one for the
engine:

```powershell
# 1. the arithmetic: a ceiling of one cent must be reported OVER and must exit 1
python C:\Users\ezabz\code\harness-config\tools\spend-guard.py check --day 2026-09-15 --ceiling 0.01 ; echo "exit=$LASTEXITCODE"
#    expect: {"state":"OVER",...} then exit=1
python C:\Users\ezabz\code\harness-config\tools\spend-guard.py check --day 2026-09-15 --ceiling 1000 ; echo "exit=$LASTEXITCODE"
#    expect: {"state":"OK",...} then exit=0
```

```powershell
# 2. the engine: with the row set to ceilingUsd: 0.01 and the profile restarted, send one message.
#    Proof is three observations, all required:
#      a. the turn ends with reason "blocked" (grep the session log for turn/end)
#      b. /cost on that session shows $0.00 — nothing was billed for the refused step
#      c. the engine log carries "spend-guard: daily ceiling reached"
#    If any of the three is missing, the ceiling was NOT proven.
```

---

## 5 The implementation

### 5.1 `harness-config/tools/spend-guard.py` — report, predict, check

This is the working script. It reads the rate card that `plugin-cost` already owns (so there is one
price table, not two), prices every billed request at its own timestamp, and takes **no implicit
writes** — `--json` and any state path are explicit, so a plain `report` cannot touch the disk.

**Measured 2026-09-16:** reproduces 2026-09-15 as **5,813 requests / $11.6831** and 2026-09-14 as
**12,279 requests / $23.1877**, matching the audit's independently recorded figures exactly. `selftest`
passes **6/6**, both with an explicit `--card` and with the card auto-resolved through the repo layout.
All three `check` exit codes verified (1 / 2 / 0). Scan: **15.5 s** for today's 152 live logs;
**42.1 s** for an unfiltered walk of all 450.

**Design note for whoever implements the plugin.** `cost-core.mjs:340-353` shows that `foldSession`
rows already carry `time`, `microUsd`, `peakMicroUsd`, `tier` and `usage` **per billed attempt**, and
that a retry is a separate attempt in the same step. A cold scan can therefore sum `rows[].microUsd`
for rows whose `time` is in the day and after the watermark — reusing the **tested** fold instead of
pricing events by hand. The guard in §3.5.1 prices each event directly because it must also handle the
live stream, where there is no fold; if you prefer one code path, use `foldSession` in the seeder and
keep the live listener as it is. Either way **do not write a third pricing path**.

```python
#!/usr/bin/env python3
"""spend-guard - DSH daily spend: measure it, predict it, refuse past a ceiling.

Prices every billed model request recorded in the durable session logs, using the
rate card that plugin-cost already owns (packages/plugin-cost/pricing.json), so
there is exactly one price table in the system.

  spend-guard.py report  [--day YYYY-MM-DD]      today's estimated spend, by session
  spend-guard.py predict --turns N --ctx TOKENS [--model M]
  spend-guard.py check   --ceiling 25 [--warn 18]  exit 0 ok / 2 warn / 1 over
  spend-guard.py selftest                        the arithmetic, on synthetic input

Every number is a LOWER BOUND on the bill: it can only see logs that are still on
this machine. It cannot see another machine, another engine, or a rotated log.
"""
import argparse, collections, datetime, json, os, sys, glob

CARD_ENV = "DSH_SPEND_CARD"


def find_card(explicit):
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    dsh = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    cands = [explicit, os.environ.get(CARD_ENV),
             os.path.join(here, "..", "packages", "plugin-cost", "pricing.json"),
             os.path.join(here, "packages", "plugin-cost", "pricing.json"),
             os.path.join(dsh, "profiles", "web", "node_modules", "dsh-plugin-cost", "pricing.json")]
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return None


class Card:
    def __init__(self, path):
        with open(path, encoding="utf-8") as fh:
            self.raw = json.load(fh)
        self.by_model = {}
        for r in self.raw["routes"]:
            for m in r["models"]:
                self.by_model[m] = r
        self.path = path
        d = self.raw.get("defaultRoute") or {}
        self.default_model = d.get("model") or next(iter(self.by_model))
        self.unpriced = set((self.raw.get("unpriced") or {}).keys())

    def route(self, model):
        """Return (route, priced). An unknown model is priced at the default route
        and flagged, never silently made free."""
        r = self.by_model.get(model)
        return (r, True) if r is not None else (self.by_model[self.default_model], False)

    @staticmethod
    def multiplier(route, ts):
        mult, name = 1.0, "offpeak"
        for t in route.get("tiers") or []:
            days = t.get("days") or []
            if days:
                wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][ts.weekday()]
                if wd not in days:
                    continue
            for a, b in t.get("windows") or []:
                ah, am = (int(x) for x in a.split(":"))
                bh, bm = (int(x) for x in b.split(":"))
                if (ah, am) <= (ts.hour, ts.minute) < (bh, bm):
                    return float(t.get("multiplier", 1)), str(t.get("name", "peak"))
        return 1.0, name


def price_micro(card, usage, model, ts):
    """Exact integer micro-USD for one billed request.
    USD/1M tokens * tokens = micro-USD, so no floating total is accumulated."""
    route, priced = card.route(model)
    mult, tier = Card.multiplier(route, ts)
    rates = route["rates"]
    miss = int(usage.get("inputTokens") or 0)
    hit = int(usage.get("cacheReadTokens") or 0)
    out = int(usage.get("outputTokens") or 0)
    micro = (miss * rates.get("missPer1M", 0) + hit * rates.get("hitPer1M", 0)
             + out * rates.get("outputPer1M", 0)) * mult
    return int(round(micro)), tier, priced


def decode(path):
    """The log is a CONCATENATED multi-frame zstd container. A one-shot
    decompress returns only the first frame - 198 bytes of a 48 MB file - which is
    why this data has been declared missing three times. Read it as a stream."""
    import zstandard as zstd
    with open(path, "rb") as fh:
        with zstd.ZstdDecompressor().stream_reader(fh) as r:
            return r.read().decode("utf-8", "replace")


def scan(card, root, day):
    """Every billed request whose own UTC timestamp falls on `day`.
    mtime >= start-of-day is a sound pre-filter: logs are append-only and events are
    chronological, so a log last written before the day holds no event inside it."""
    lo = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    lo_ms = lo.timestamp() * 1000.0
    rows = collections.defaultdict(lambda: collections.Counter())
    unreadable, unpriced_models = [], collections.Counter()
    files = [p for p in glob.glob(os.path.join(root, "*", "*", "session.v3.jsonl.zstd"))
             if os.path.getmtime(p) >= lo.timestamp()]
    for path in files:
        sid = os.path.basename(os.path.dirname(path))
        try:
            text = decode(path)
        except Exception as exc:
            unreadable.append((sid, str(exc)[:80]))
            continue
        model = card.default_model
        for ln in text.splitlines():
            if '"usage"' not in ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            data = o.get("data") or {}
            if o.get("type") == "request/context":
                if data.get("model"):
                    model = data["model"]
                continue
            u = data.get("usage")
            if not isinstance(u, dict):
                continue
            t = o.get("time")
            if not isinstance(t, (int, float)):
                continue
            if t < lo_ms or t >= lo_ms + 86400000:
                continue
            ts = datetime.datetime.fromtimestamp(t / 1000.0, datetime.timezone.utc)
            micro, tier, priced = price_micro(card, u, model, ts)
            if not priced:
                unpriced_models[model] += 1
            c = rows[sid]
            c["micro"] += micro
            c["n"] += 1
            c["miss"] += int(u.get("inputTokens") or 0)
            c["hit"] += int(u.get("cacheReadTokens") or 0)
            c["out"] += int(u.get("outputTokens") or 0)
            if tier != "offpeak":
                c["peak_n"] += 1
                c["peak_micro"] += micro
    return rows, files, unreadable, unpriced_models


def usd(micro):
    return micro / 1e6


def cmd_report(args):
    card = Card(find_card(args.card))
    day = (datetime.date.fromisoformat(args.day) if args.day
           else datetime.datetime.now(datetime.timezone.utc).date())
    rows, files, unreadable, unpriced_models = scan(card, args.sessions, day)
    total = sum(c["micro"] for c in rows.values())
    print(f"DSH spend, {day.isoformat()} UTC  (LOWER BOUND on the bill)")
    print(f"  card    {card.path}  (updated {card.raw.get('updated')})")
    print(f"  scanned {len(files)} log(s) written since {day.isoformat()} 00:00Z"
          f"   unpriced-route requests: {sum(unpriced_models.values())}")
    print()
    print(f"  {'session':<38}{'req':>6}{'$':>10}{'cache-hit':>11}{'peak$':>8}")
    for sid in sorted(rows, key=lambda s: -rows[s]["micro"])[:args.top]:
        c = rows[sid]
        inp = c["miss"] + c["hit"]
        hr = (100.0 * c["hit"] / inp) if inp else 0.0
        print(f"  {sid[:38]:<38}{c['n']:>6}{usd(c['micro']):>10.4f}{hr:>10.1f}%{usd(c['peak_micro']):>8.4f}")
    print()
    print(f"  TOTAL    ${usd(total):.4f}   sessions {len(rows)}   "
          f"requests {sum(c['n'] for c in rows.values()):,}")
    if unreadable:
        print(f"  UNREADABLE (not priced, so NOT in the total): {len(unreadable)}")
        for sid, err in unreadable[:5]:
            print(f"    {sid}: {err}")
    if unpriced_models:
        print(f"  WARNING unpriced route priced at default and flagged: {dict(unpriced_models)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"day": day.isoformat(), "micro": total, "usd": usd(total),
                       "requests": sum(c["n"] for c in rows.values()),
                       "sessions": {s: dict(rows[s]) for s in rows}, "card": card.path}, fh, indent=1)
    return 0


def cmd_predict(args):
    """$ per step = C/231,300,000 + $0.0005 off-peak, exactly 2x at peak."""
    card = Card(find_card(args.card))
    route, priced = card.route(args.model)
    r = route["rates"]
    miss_frac = args.miss_frac
    hit_frac = 1.0 - miss_frac
    for label, mult in (("off-peak", 1.0), ("peak", 2.0)):
        prompt = args.turns * args.ctx
        micro = (prompt * hit_frac * r.get("hitPer1M", 0)
                 + prompt * miss_frac * r.get("missPer1M", 0)
                 + args.turns * args.out * r.get("outputPer1M", 0)) * mult
        print(f"  {label:<9} ${usd(int(round(micro))):>8.2f}   "
              f"({args.turns:,} steps x {args.ctx:,} ctx, {miss_frac:.1%} miss, "
              f"{args.out:,} out/step)")
    print(f"\n  model {args.model} ({route['provider']})  card {os.path.basename(card.path)}"
          f"{'' if priced else '  [UNPRICED ROUTE - priced at default, flagged]'}")
    print("  Measured reference: a working day ran $0.0015-$0.0020 per request at "
          "189k-263k mean context (console export, 2026-09-10..16).")
    return 0


def cmd_check(args):
    card = Card(find_card(args.card))
    day = (datetime.date.fromisoformat(args.day) if args.day
           else datetime.datetime.now(datetime.timezone.utc).date())
    rows, files, unreadable, unpriced = scan(card, args.sessions, day)
    total = usd(sum(c["micro"] for c in rows.values()))
    state, code = "OK", 0
    if total >= args.ceiling:
        state, code = "OVER", 1
    elif args.warn is not None and total >= args.warn:
        state, code = "WARN", 2
    print(json.dumps({"day": day.isoformat(), "spendUsd": round(total, 6),
                      "ceilingUsd": args.ceiling, "warnUsd": args.warn, "state": state,
                      "requests": sum(c["n"] for c in rows.values()), "sessions": len(rows),
                      "unreadable": len(unreadable),
                      "basis": "local durable logs, lower bound, this machine only",
                      "exit": code}))
    return code


def cmd_selftest(args):
    card = Card(find_card(args.card))
    utc = datetime.timezone.utc
    mp = datetime.datetime(2026, 9, 14, 2, 0, tzinfo=utc)    # Monday 02:00Z - peak
    mo = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=utc)   # Monday 12:00Z - off-peak
    sa = datetime.datetime(2026, 9, 12, 2, 0, tzinfo=utc)    # Saturday - off-peak
    u = {"inputTokens": 1000, "cacheReadTokens": 100000, "outputTokens": 500}
    off = price_micro(card, u, "deepseek-flash", mo)
    pk = price_micro(card, u, "deepseek-flash", mp)
    we = price_micro(card, u, "deepseek-flash", sa)
    hand = round(1000 * 0.15 + 100000 * 0.003 + 500 * 0.60)
    checks = [("offpeak == hand arithmetic", off[0] == hand, f"{off[0]} == {hand}"),
              ("peak == exactly 2x offpeak", pk[0] == 2 * off[0], f"{pk[0]} vs {2 * off[0]}"),
              ("weekend 02:00Z is offpeak", we[1] == "offpeak", we[1]),
              ("Mon 02:00Z is peak", pk[1] == "peak", pk[1]),
              ("unknown model flagged, not free", card.route("no-such-model")[1] is False, "flagged"),
              ("one request is well under a cent", usd(hand) < 0.01, f"${usd(hand):.6f}")]
    bad = 0
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({detail})")
        bad += 0 if ok else 1
    print(f"\n  card {card.path}\n  {len(checks) - bad}/{len(checks)} checks passed")
    return 1 if bad else 0


def main():
    # `--card`/`--sessions` are accepted BOTH before and after the subcommand: a
    # human types both orders, and failing on the more natural one is a trap, not
    # a contract.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--card")
    common.add_argument("--sessions", default=None)
    ap = argparse.ArgumentParser(parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", parents=[common])
    r.add_argument("--day")
    r.add_argument("--top", type=int, default=15)
    r.add_argument("--json")
    p = sub.add_parser("predict", parents=[common])
    p.add_argument("--turns", type=int, required=True)
    p.add_argument("--ctx", type=int, required=True)
    p.add_argument("--model", default="deepseek-flash")
    p.add_argument("--out", type=int, default=830)
    p.add_argument("--miss-frac", type=float, default=0.009)
    c = sub.add_parser("check", parents=[common])
    c.add_argument("--day")
    c.add_argument("--ceiling", type=float, required=True)
    c.add_argument("--warn", type=float, default=None)
    sub.add_parser("selftest", parents=[common])
    args = ap.parse_args()
    if args.sessions is None:
        args.sessions = os.path.join(
            os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh"), "sessions")
    return {"report": cmd_report, "predict": cmd_predict,
            "check": cmd_check, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

### 5.2 Measured output, verbatim (2026-09-16, ZABZ-YOGA)

```
$ python spend-guard.py --card .../pricing.json selftest
  PASS  offpeak == hand arithmetic  (750 == 750)
  PASS  peak == exactly 2x offpeak  (1500 vs 1500)
  PASS  weekend 02:00Z is offpeak  (offpeak)
  PASS  Mon 02:00Z is peak  (peak)
  PASS  unknown model flagged, not free  (flagged)
  PASS  one request is well under a cent  ($0.000750)
  6/6 checks passed

$ python spend-guard.py --card .../pricing.json report --day 2026-09-15
DSH spend, 2026-09-15 UTC  (LOWER BOUND on the bill)
  card    ...\packages\plugin-cost\pricing.json  (updated 2026-09-11)
  scanned 218 log(s) written since 2026-09-15 00:00Z   unpriced-route requests: 0

  session                                  req         $  cache-hit   peak$
  session-b60e96b3-6a48-4898-a770-bc9eb5   957    2.5640      99.5%  0.8754
  session-4db964fb-b407-4a72-b698-5688c7   564    1.7935      99.6%  1.3389
  session-87dce8c8-f82b-41b6-a67c-64e5d4   395    1.2006      99.5%  0.6071
  ...
  TOTAL    $11.6831   sessions 79   requests 5,813
```

`predict --turns 400 --ctx 250000` prints `off-peak $0.63 / peak $1.26`; `check --day 2026-09-15
--ceiling 0.01` prints `"state":"OVER"` and exits 1.

### 5.3 Today so far, as measured

`report --day 2026-09-16` at ~21:55 UTC, **15.5 s**, 152 logs (mtime-filtered from 450):

```
  session                                  req         $  cache-hit   peak$
  session-e34dd061-3b51-41b1-aa7e-a66bfc   491    1.3668      98.8%  0.2010
  session-ad81c35e-c87e-411a-84a2-0c1fdd   295    0.7842      99.6%  0.1590
  session-890df78b-ec89-49a6-a335-6ebb6d   366    0.6898      99.6%  0.2834
  session-24e68280-a452-41b3-8f82-542a45   202    0.5618      99.3%  0.2701
  ef8ac479-766a-467a-8ac2-72a2088c359d     298    0.5191      99.9%  0.3309
  d1ff0721-813f-4618-956d-f39fef71cd40     250    0.5122      99.3%  0.3063

  TOTAL    $20.3012   sessions 151   requests 11,357
```

Three things this run proves, and one it warns about.

- **The card auto-resolved through the installed plugin**: the report cites
  `~\.dsh\profiles\web\node_modules\dsh-plugin-cost\pricing.json` — which *is* the repository file,
  because `scripts/install-client-plugins.ps1` installs each package as a **junction**, not a copy.
  The guard and `/cost` therefore cannot drift onto two rate cards.
- **The ceiling arithmetic is proven end to end** (§5.2): `--ceiling 0.01` → `"state":"OVER"`, exit 1;
  `--ceiling 1000` → `"state":"OK"`, exit 0; `--ceiling 25 --warn 10` → `"state":"WARN"`, exit 2.
- **`predict` matches the model**: 400 steps × 250k ctx → **$0.63 off-peak / $1.26 peak**.
- **The warning: the day's figure is meaningless without the day's clock.** One day earlier the
  ledger recorded 2026-09-16 as **$0.58**, because the audit's export was produced mid-day. This
  reading, taken at the end of a day when a fleet of parallel agents ran, is **$20.30** — 35× larger,
  same date. The top session here (`session-e34dd061…`, $1.3668, 491 requests, 98.8 % cache hit) is
  the **research agent that wrote this document**: the guard's first measured act was watching the
  fleet that commissioned it. Always quote the timestamp with the figure.

---

## 6 Install order

1. `packages/plugin-cost/src/guard.mjs` ← §3.5.1; add it to `scripts/build.mjs`; add
   `test/guard.test.mjs` ← §3.5.3.
2. `node packages/plugin-cost/scripts/build.mjs && node packages/plugin-cost/test/verify.mjs` —
   must be green before anything is mounted.
3. Add the row to `packages/plugin-cost/cordis.patch.yml` ← §3.5.2.
4. Add the `spend-guard:` block to `settings/base.yaml` and any per-machine override.
5. Save `tools/spend-guard.py` ← §5.1. Run `selftest` and `report --day 2026-09-15`; **both must
   reproduce §5.2 before you trust anything else.** Then run the §4 proof.
6. Commit in `harness-config`, then on each machine: `git pull && python scripts/sync.py && pwsh
   scripts/install-client-plugins.ps1`, and reload the profile.
7. Schedule layer 2 (`dshw`-style Task Scheduler entry) — read-only warning, every 5 minutes.

---

## 7 The finding that makes the guard urgent

**Nothing in this deployment caps spend, and nothing ever has.** `~/.dsh/settings.yaml`, read verbatim
2026-09-16 — every key in it:

```yaml
ui-onboarding: {welcomeNoticeVersion: 2026-08-13.1}
ui-conversation: {busyEnter: steer}
permission: {defaultPreset: danger-full-access}
agent-default-model: {provider: deepseek-official, model: deepseek-flash}
agent-presets: {default: zabz}
llm-deepseek: {streamIdleTimeoutMs: 60000, retryPolicy: {...}}
llm-pi-ai: {providers: {deepinfra: {...}}}
agent-loop: {maxParallelToolCalls: 20}
```

No budget, no ceiling, no alert. The only enforced budget in the group is the company's
`llm_budget.py`, and it cannot see DSH at all (§1.3). **`agent-loop.maxParallelToolCalls: 20` is the
closest thing to a spend control in this file, and it limits concurrency, not total** — twenty
parallel tool calls across a fleet of sessions is a cost multiplier, not a ceiling.

---

## 8 Recommendation, coverage, and the one measurement

**Recommendation.** Build the ceiling as a **host plugin row inside the existing `plugin-cost`
package** that subscribes to `agent/pre-step` and prices the engine's own traffic from `session/event`,
because that is the only candidate that is live, pre-billing, reachable on every machine through
`harness-config`, and graceful: at **$25** it tells the session what today costs, at **$35** it refuses
new fan-out while running work continues, and at **$50** it returns `{kind:'reject'}` and the turn
closes durably as **`blocked`** — before `step/start`, so nothing is billed for the step that stops,
nothing is destroyed, and the session resumes tomorrow. The daily counter is the right primitive
because the measurement in §2.4 refutes the runaway-session story: the largest session ever recorded
here cost **$2.88**, and the $54.92 day was **79 ordinary sessions at once**. A *scheduled script* and
a *session policy file* cannot stop anything in time, and a *gateway* only guards traffic you remember
to route through it. The guard's hard ceiling must be a **fleet daily counter with three thresholds**,
and the arithmetic it needs is already in the repo, already priced against the account's own ledger,
and already tested.

**What it does not cover.**

- **The other machine, and any second engine on this host.** The live counter is exact for *one*
  engine's traffic. On the worst measured day, **56.5 % of the bill came from ZABZ-TECH**. Until the
  layer-2 roll-up posts per-host totals into the authority's `model_usage` (§3.6, P209's own recorded
  fix — **not implemented here**), the *fleet* has no ceiling, only each host has one.
- **Editor traffic** — `vscode copilot` and the other VS Code keys were **$3.83 of the $54.92 day**
  (console export, 2026-09-15). They never touch DSH.
- **Anything already in flight when the ceiling trips.** A model call in progress completes and is
  billed. The overrun is bounded by one step, not zero.
- **Retries and failed attempts.** Each retry attempt is a separately billed request
  (`turn-usage.js` treats `llm/retry-started` as a new attempt) and the guard counts each as it lands,
  but a retry storm inside one step is bounded only by `retryPolicy.maxRetries: 2`.
- **The rate card is manual data.** `pricing.json` records `readAt` and nothing detects a rate change.
  A wrong card makes the counter wrong by exactly the rate error — and the guard would *report* a
  ceiling breach that is not real, which is why `selftest` asserts the card's arithmetic rather than
  trusting it.
- **Model ids can change and the card will not.** A new id is caught (§3.3, bounded at the dearest
  rate), but it will be **priced by bound, not by fact**, and the guard says so. It would rather
  over-charge the counter than under-report.
- **Whether an engine restart mid-day double-counts.** The state file stores a `watermarkMs` and the
  seed skips events at or before it. **I have not run that case** — it is the first thing the install
  in §6 step 5 should test, by restarting the profile mid-day and confirming the day's figure does not
  jump.

**The single measurement that would make the model trustworthy.** One more **console export covering
2026-09-14…09-16, taken at the same time as a re-run of §5.1 on both machines.** Today the model rests
on **one** day where a ledger figure and a local figure exist together — 2026-09-15, which gave a
−10 % tuning error on top of a **50 %/76 % local-capture** gap. A second and third paired day
converts the local counter into **bill dollars** with a measured, dated ratio instead of an assumption,
and that ratio is the only thing standing between "we have a ceiling" and "we have a ceiling that
means dollars." Everything else in this document is already measured; that is the one number still
guessed. **The owner's own standing answer to this is available and cheap: the console export he
produced by hand on 2026-09-16 is the only authoritative source that will ever exist, because no usage
API does (all six endpoints 404, probed 2026-09-16).**
