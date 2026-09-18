# 101 — The spend guard, installed and proven

**Written** 2026-09-17 14:20–15:00Z on **ZABZ-YOGA**, by the agent briefed to build and install it.
**Owns** `packages/plugin-cost/**`, the `spend-guard` policy block in `settings/base.yaml`, and this file.
**Status** built, unit-tested (66/66), mounted and demonstrated firing on an **isolated engine**, and
**not yet mounted in the owner's live engine** — the live engine (pid 4880) was never restarted, and §9
says the one command that acts.
**Relationship to doc 65 and doc 96.** `docs/mesh/65-spend-guard.md` designed this and never installed it;
`docs/mesh/96-gateway-at-scale.md` measured why the numbers had to move ($68/hour at 55 agents, $544 for
eight hours, one hour = 1.24× the worst recorded day) and recommended `$35 / $80 / $150` plus a
12-agent cap. This document is the installation, the proof, and the four things that are still not true.

---

## 0. The five answers, in one screen

**(1) What exists now.** `packages/plugin-cost/src/guard.mjs` (the guard), `src/guard-entry.mjs` (its host
row), a generated `lib/guard.js`, the `spend-guard` row in `packages/plugin-cost/cordis.patch.yml`, the
`spend-guard:` block in `settings/base.yaml`, and `test/guard.test.mjs` (66 checks, all passing). Nothing
in the arithmetic is new: the guard prices with this package's existing `cost-core.mjs`, its existing
`pricing.json` rates and its existing `session-log.mjs` reader.

**(2) The three thresholds, as installed.** **$35 warn** · **$80 stop new fan-out** · **$150 refuse a
new billable step** — plus a fourth, non-money ceiling: **12 generating agents per machine**.

**(3) It fires, and it was shown firing.** On an isolated DSH home with an artificially low policy
($0.00005 / $0.00008 / $0.00015) the guard produced all three behaviours in order, and the refusal was
measured end to end: **`turn/end` reason `"blocked"`, zero `assistant/message` events carrying a usage
sample, zero `step/start` events** — the step was vetoed before the engine appended it, so nothing was
sent and nothing was billed. §6 is the raw output.

**(4) The fail-closed paths are implemented and tested**, each with the code that does it: an unpriced
route is bounded at the dearest card rate; the guard's own internal error refuses the step; a missing or
zeroed price card refuses to mount. §5 names each one.

**(5) Nothing here is hardcoded to a model, and nothing here points at the gateway.** The guard prices
whatever provider/model the engine actually records, so a model swap needs no code change. Confirmed
again today: `agent-default-model` is `deepseek-official` / `deepseek-flash`, the DeepSeek adapter's
default base URL is `https://api.deepseek.com`, and a grep of `settings/**` and `presets/**` for
`secretary-auto|secretary-fast|secretary-smart|SECRETARY_API_BASE` returns **one** hit — the standing
instruction's own prose, and no configuration. **The fleet is not on the gateway**, which is why §7's
`secretary-fast` finding is a trap that is currently *armed but unstepped-on*.

---

## 1. What was built, and where

| path | what it is |
|---|---|
| `packages/plugin-cost/src/guard.mjs` | the guard: the counter, the four thresholds, the fail-closed paths. `createGuard(deps)` is the factory; `lib/guard.js` is generated from it |
| `packages/plugin-cost/src/guard-entry.mjs` | the Cordis plugin shape (`name`/`inject`/`apply`) for the host row. Concatenated into `lib/guard.js` |
| `packages/plugin-cost/lib/guard.js` | **generated** by `scripts/build.mjs` from `src/cost-core.mjs` + `src/session-log.mjs` + `src/guard.mjs` + `src/guard-entry.mjs` |
| `packages/plugin-cost/scripts/build.mjs` | now emits three artifacts (`lib/index.js`, `lib/guard.js`, `lib/client.js`) and its `--check` compares all three |
| `packages/plugin-cost/package.json` | adds the `./guard` subpath export |
| `packages/plugin-cost/cordis.patch.yml` | adds the `id: spend-guard` row, `name: dsh-plugin-cost/guard` |
| `packages/plugin-cost/test/guard.test.mjs` | 66 checks: thresholds, boundaries, fail-closed, the notice, the cap, the seed, the restart |
| `packages/plugin-cost/test/verify.mjs` | the guard suite joined the `verify` gate as its own check |
| `settings/base.yaml` | the `spend-guard:` block: policy data, synced to every machine |
| `docs/mesh/101-spend-guard-installed.md` | this file |

### 1.1 Why the guard is a second module in the same package, not a second package

A Cordis loader entry resolves a **module**, not a named export of one. Two rows naming `dsh-plugin-cost`
would mount that plugin twice — and a second guard in one process would count every request twice. So the
guard is its own entry, and `scripts/build.mjs` emits it from the **same sources** as the cost surfaces:

```
lib/index.js  ← cost-core.mjs + session-log.mjs + command.mjs     (+ /cost, the composer pill)
lib/guard.js  ← cost-core.mjs + session-log.mjs + guard.mjs + guard-entry.mjs
```

Both files contain the same rate table, because both are generated from it. There is no second copy to
edit, so the "one price table" rule that doc 65 §3.3 and journal P209 both insist on is enforced by the
build, not by discipline. `scripts/build.mjs --check` fails if either generated file drifts.

### 1.2 The two non-obvious things in the build

**A package dependency cannot be a `require` binding in a generated file.** The guard registers its
settings namespace, which needs a schemastery schema class, so `src/guard-entry.mjs` imports
`Schema from '@deepseek-ai/schemastery'`. A generated file must not resolve that name itself: the loader
mounts this package through a junction at `~/.dsh/profiles/web/node_modules/dsh-plugin-cost`, and
`harness-config` has **no `node_modules`**, so Node's own resolver walking up from
`packages/plugin-cost/lib/` finds nothing. The rule the build now follows is: **a `node:` builtin becomes
a `require` binding; a package stays a static `import` in the generated file, because the loader resolves
that one itself** — which is exactly the mechanism that resolved `dsh-plugin-cost/guard` in the first
place. Verified by loading the generated file directly:

```
$ node --input-type=module -e "await import('file:///.../plugin-cost/lib/guard.js')"
guard: apply,inject,name | cost: apply,costReport,inject,name
```

and by `dsh --profile web --dump-config`, which composes the new row and (when the row is duplicated)
throws `duplicate loader entry id: spend-guard` — i.e. the loader is really reading it.

**A generated artifact must not carry the building machine's paths — and the first version of this one
did.** `scripts/build.mjs` originally emitted `createRequire("C:/Users/ezabz/.dsh/profiles/web/package.json")`
into both `lib/index.js` and `lib/guard.js`: the absolute path of whichever host ran the build, committed
into a file every other machine receives. Caught by looking at the generated diff rather than only at the
test results, and fixed by emitting the anchor as a function of `process.env.DSH_HOME` and
`process.env.USERPROFILE`/`HOME` instead, using nothing imported in advance. Both generated files are now
free of machine paths (the one remaining match is a docstring describing a workspace-directory naming
example), and both load under two different `DSH_HOME` values.

---

## 2. The three thresholds as installed

| threshold | value | what happens | where the value comes from |
|---|---|---|---|
| **warn** | **$35** | a one-line notice is appended to the step, so the model and the owner see it, and it is logged. Nothing is refused | above the median day ($4–7) and above every legitimate single-machine day on record ($35.39, 09-14) |
| **stop new fan-out** | **$80** | the notice changes to *"start no new subagents or workflows. Work already running continues."* Nothing is refused | ≈70 minutes of a 55-agent fleet at the measured $68/hour |
| **refuse a new billable step** | **$150** | `{kind:'reject'}` is returned from `agent/pre-step`; the turn closes durably as **`blocked`**; the session stays resumable | 2.7× the worst day ever recorded ($54.92); the old $50 was 44 minutes of that fleet |
| **generating agents per machine** | **12** | a step is refused when 12 agents are already generating and this one is a **new** one; an agent already generating is never refused by this cap | matches the measured machine ceiling (14–39 turns before cores bind) and the fleet's measured historical peak (16–22 in flight) |

Both ceiling values live in **two** places, deliberately, and neither is a second source of truth:
`settings/base.yaml` (the shared, synced policy) and the `spend-guard` row's `config` (the same numbers,
so a machine whose settings have not synced yet still enforces a ceiling). The guard registers the
`spend-guard` settings namespace, and the settings provider resolves `schema defaults → row config →
user layer`, so `settings/base.yaml` — merged into `~/.dsh/settings.yaml` by `scripts/sync.py` — is what
wins. Changing a ceiling is one line of YAML, no rebuild and no restart of the code.

---

## 3. Where every number comes from — a scan seeds, the live stream decides

This is the distinction that doc 65 §2.2 and doc 96 §4.2 force, and it is encoded in the guard:

| path | what it is | can it set the ceiling? |
|---|---|---|
| **LIVE** — `ctx.on('session/event', …)` | every `assistant/message` this engine appends, with the provider's own reported usage, priced at that event's own `time` (the card is time-of-day, so the timestamp is part of the price) | **yes. This is the number the ceiling is compared against.** It is exact for this engine's traffic — no decoding, no mtime filter, no disk scan |
| **SEED** — one read of `<DSH_HOME>/sessions` at activation | events **newer than the stored watermark**, so a restart resumes the day instead of forgetting the morning | **no — it is a lower bound, and it can only lower the counter.** On 2026-09-15 this machine's logs held **50 % of the misses and 76 % of the hits** of its own ledger line, which is why a scan may seed and may never decide |

`~/.dsh/spend-guard/day.json` carries `{day, micro, requests, unpriced, watermarkMs, seedRequests,
lastVerdict, lastReason, lastStep, generatingAtLastDecision, limitsUsd, writtenAt}`. It is written
atomically (temp + rename) after every priced event and after every refusal. The watermark is what makes
a restart idempotent: the live listener ignores any event at or before it. **Not yet verified:** an
actual engine restart mid-day; §10 says so.

---

## 4. The escape hatch on the notice — one per escalation, not one per step

A notice appended to every step of a long turn would itself be a cost, so the guard reports an escalation
**once**, and re-arms it when the verdict returns to `ok` (so dropping below a threshold and crossing it
again says so again). That re-arm is a deliberate behaviour with its own test:

```
ok    the WARN behaviour appends exactly one notice to the step
ok    the notice is not repeated on every following step
ok    crossing back up into the warning re-arms the notice
ok    an agent that IS one of the running ones is not warned about its own load
```

---

## 5. Fail closed, and where each case is implemented

Doc 65 §3.3's rule is *never fail open on the money path*, and each clause has code:

| case | behaviour | code |
|---|---|---|
| **an unpriced route** (a model id that is not on the card) | charged at the **dearest rate on the card**, with the card's highest multiplier applied — never zero, never free — and counted in `unpriced` with a named reason. On today's card that bound is `deepseek-v4-pro` at peak: **$1.32/1M in, $3.96/1M out**, 8.8× and 6.6× the flash rate | `priceSample()` — `if (cost !== undefined) return …` else `const bound = Math.round(…)`. Test: *"the dearest rate is deepseek-v4-pro at its peak multiplier"*, *"an unpriced route is charged at the dearest rate, not zero"* |
| **the guard's own internal error** | the step is **refused**, with the error logged, unless an operator has written `onInternalError: open` on purpose | the `catch` in the `agent/pre-step` listener: `if (limits.onInternalError === 'closed') { warn(…); return { kind: 'reject' }; }`. The company's `llm_budget.py` fails **open** on unexpected error (`llm_budget.py:428-432`, recorded in P209); that defect is deliberately not repeated. Tests: *"an internal error REJECTS the step"*, *"fail-open allows the step only when it was asked for by name"* |
| **a missing or empty price card** | **throws at mount**, so the row fails to activate and is named by `assertEntriesActivated` — the guard never mounts and then pretends everything is $0.00 | the `pricing.routes.length === 0` guard at the top of `apply()`. Test: *"a card with no routes refuses to mount rather than pricing everything at zero"* |
| **a zeroed price card** | throws too, when no explicit ceiling is configured, because an unpriced route could not be bounded | `if (dearestZero && !isLimit(config.ceilingUsd)) throw …` |
| **an unreadable state file** | the day is treated as unknown: it is re-seeded from the logs and **labelled a lower bound** in the log line and in `gaps` | `restore()` — a missing file is the first run and silent; anything else warns `WARNING could not read … today restarts from the logs and is a LOWER BOUND` |
| **a malformed usage sample** | not priced at all, and counted as a gap, rather than silently priced as zero | `normalizeUsage` returns `undefined` → `{ micro: 0, priced: false, reason: 'the usage sample failed validation…' }`. Test: *"a malformed usage sample is refused, not priced"* |
| **a negative, non-numeric or hostile limit** | falls back to the protective default, **never to zero** | `resolveLimits()` — `isLimit(source[key]) ? source[key] : DEFAULTS[key]`. Test: *"a non-number ceiling falls back to the default, never to zero"* |
| **an unknown config key** | named in a warning, not silently ignored | `limits.unknownKeys` |

One caveat, stated rather than hidden: a test that constructs the guard with a **missing `core`** throws
(*"the price core is missing"*), but that path is unreachable in the shipped module, because
`lib/guard.js` is generated with `cost-core.mjs` inside it. It is a test-time guard, not a live one.

---

## 6. The demonstration — all three behaviours, measured on an isolated engine

**Why an isolated engine and not the live one.** The owner's engine is **pid 4880, live work, and it was
not restarted and not killed at any point** (checked alive before and after; its HTTP surface still
answers `401` on unauthenticated `/`, which is the correct answer). The guard's live demonstration ran on
a **separate DSH home** (`%TEMP%\sg-eng`) with the **same engine binary**, the **same package** through a
junction, and the **same generated module** — the mechanism is identical; only the `DSH_HOME` differs.
An attempt to hot-mount the row into the live engine through its live-reload patch layer
(`~/.dsh/profiles/web/cordis.patch.yml`, `patchReload: live`) is described in §9 and did not activate;
that file was restored byte-identical from a backup (`sha256 850734E8…68F0` before and after).

**The policy used for the demonstration was artificially low, on purpose**, because the point is to show
the thresholds firing without waiting for a real overspend:

```json
{ "warnUsd": 0.00005, "fanoutUsd": 0.00008, "ceilingUsd": 0.00015,
  "concurrencyCap": 12, "onInternalError": "closed", "seedFromLogs": false,
  "stateFile": "%TEMP%/sg-eng/state/day.json", "sessionsRoot": "%TEMP%/sg-eng/sessions" }
```

### 6.1 WARN — the notice, and the step still runs

```
########## A: WARN - counter $0.000060 is above warn $0.00005, below fan-out $0.00008 ##########
--- model output ---
Two plus two is four.
--- exit=0  seconds=6.7 ---
--- day.json ---
{ "day": 1789603200000, "micro": 120, "requests": 1,
  "lastVerdict": "warn", "lastReason": "warn", "lastStep": 1,
  "generatingAtLastDecision": 1,
  "limitsUsd": { "warn": 0.00005, "fanout": 0.00008, "ceiling": 0.00015, "concurrencyCap": 12 } }
```

### 6.2 STOP NEW FAN-OUT — the notice changes, the step still runs

```
########## C: STOP NEW FAN-OUT  (counter above fan-out $0.00008, below ceiling $0.00015) ##########
Two plus two is four.
exit=0
--- day.json ---
 "micro": 148, "requests": 1,
 "lastVerdict": "fanout", "lastReason": "fanout",
```

### 6.3 REFUSE A STEP — the turn ends `blocked` and nothing is billed

```
########## B: REFUSE - counter 0.000160 is above ceiling 0.00015 before the first step ##########
--- process output ---
(empty)
--- exit=1  seconds=4 ---
--- day.json ---
{ "day": 1789603200000, "micro": 160, "requests": 0, "unpriced": 0, "watermarkMs": 0,
  "seedRequests": 0, "lastVerdict": "reject", "lastReason": "daily ceiling", "lastStep": 1,
  "generatingAtLastDecision": 1,
  "limitsUsd": { "warn": 0.00005, "fanout": 0.00008, "ceiling": 0.00015, "concurrencyCap": 12 } }
```

`requests: 0` is the counter, which only moves on a billed event. The **independent** check is the
durable session log of that same run, read back with this package's own decoder:

```
session        : session-f884f799-385f-4311-a62c-f41a82ad81f3
event types    : session, permission/preset, sandbox/mode, approval/policy,
                 agent/inbox/spliced, turn/start, agent/inbox/spliced, turn/end
turn/end kinds : ["blocked"]
BILLED CALLS   : 0  (assistant/message carrying a usage sample)
```

Three facts, and the second is the one that proves *before billing*:
`turn/end` is `blocked`; **there is no `step/start` event at all** — the guard vetoed the step before
`this.session.append("step/start", …)`, which is exactly the seam doc 65 §3.2 read out of
`dsh-agent-loop/lib/index.js:937-947`; and there is **no `assistant/message` carrying usage**, i.e. no
model request was made, so nothing could be billed.

### 6.4 The real defaults, in force, with the engine normal

```
=== E: REAL DEFAULTS, isolated state, seedFromLogs ON ===
the guard is mounted and the engine is normal.
exit=0 seconds=5.5
--- day.json ---
 "micro": 71, "requests": 1, "lastVerdict": "ok",
 "limitsUsd": { "warn": 35, "fanout": 80, "ceiling": 150, "concurrencyCap": 12 }
```

A one-step turn cost **$0.000071**, the guard logged no escalation, and the engine answered normally.

### 6.5 The concurrency cap: what is proven, and what is not

The cap's **policy** is proven by test — a new agent is refused at the cap, `next()` is never called, an
agent that is already generating is never refused, and the count comes from the engine's own registry:

```
ok    a NEW agent is refused at the concurrency cap with no money spent
ok    the concurrency reject never calls next()
ok    the guard names the concurrency cap in its log
ok    an agent already generating is never refused by the concurrency cap
ok    within one of the cap the step is admitted with a warning notice
ok    below the cap the step is admitted with no notice at all
```

The count itself was **observed on a real engine** — the guard recorded `generatingAtLastDecision: 1`
while one agent was driving a turn. **Not demonstrated:** a live refusal *by the cap* on a real engine.
One subagent under a deliberately tiny cap (`concurrencyCap: 1`) was **not** refused, and the reason is
worth recording as a real caveat rather than a bug:

> **What the count counts.** The cap counts agents whose public status is `running`
> (`agents.list()` filtered by `status === 'running'`, the same counter `plugin-health`'s census reports
> as `sessionsRunning`). An agent parked waiting on a tool result is **not** `running`, so a parent
> blocked on its child does not count itself while the child counts one. The effect is that the cap
> **under-counts** and is therefore *conservative* — it can refuse slightly late, never early, and it can
> never refuse an agent that is not generating. What it is anchoring on is nonetheless the right thing to
> anchor on: `agent/pre-step` **is** the moment a step is about to become a model request, so the number
> of agents at a pre-step is the number that is about to generate.

---

## 7. The `secretary-fast` trap: what it is, why it happens, and who has to change it

**The measurement (doc 96 §1.2, and not re-measured here):** `POST http://secratary…:8002/v1/chat/completions`
with `model: secretary-fast` returned HTTP 200 served by **`deepseek/deepseek-v4-pro`** — the alias whose
own description says *"Force the fast/cheap tier (tool-capable)"*. On this package's card, `deepseek-v4-pro`
is **4.4× the miss rate, 7.3× the hit rate and 3.3× the output rate** of `deepseek-flash`.

**Where the alias is defined** (`personal-secretary-mvp`):

| fact | file and line |
|---|---|
| the alias and its description | `app/services/ai_gateway.py:987-991` — `"secretary-fast": ("work_mode", "low", "Force the fast/cheap tier (tool-capable)")` |
| its route policy | `app/services/smart_router.py:796-802` — `RoutePolicy(public_alias="secretary-fast", min_quality="low", min_tier="fast", max_output_cost_per_mtok=5.0, allowed_providers=_APPROVED_PROVIDERS)` |
| the gate that decides eligibility | `smart_router.py:1399-1416` — `if _TIER_RANK.get(tier,0) < _TIER_RANK.get(caps.min_tier,0): return f"tier_floor:…"` with `_TIER_RANK = {"fast": 0, "mid": 1, "ceo": 2}` (line 693) |
| the ranking | `smart_router.py:2010-2013` — `composite = capability_match × (1 − cost_weight) + min(1, cost_score/1000) × cost_weight`, `cost_weight = 0.3` at `normal` budget |
| the v4-pro entry | `smart_router.py:141-154` — `tier: "mid"`, `quality_class: "high"`, `cost_per_mtok_output: 0.87` |
| the flash entry | `smart_router.py:113-126` — `tier: "fast"`, `quality_class: "medium"`, `cost_per_mtok_output: 0.28` |

**Why it resolves to v4-pro — the mechanism, from the code.** `min_tier` is a **floor, not an
equal-to**: `_capability_rejection` rejects a candidate only when its tier rank is *below* the required
rank, so a policy that asks for `min_tier="fast"` admits `fast`, `mid` **and** `ceo`. The only money
constraint on the whole policy is `max_output_cost_per_mtok = 5.0`, which does not exclude v4-pro at
`$0.87`. Quality is then weighted **70 %** against cost's 30 %, so the mid-tier/high-quality model beats
the fast-tier/medium-quality one. **The result is not a bug in the router; it is the policy doing exactly
what it says.** `secretary-fast` means "fast *or better*", and the router's notion of better includes
spending 3.1× more on the same request.

**A second, independent reason flash may not even be in the pool:** `deepseek` candidates are dropped
unless `ai_gateway_direct_deepseek_enabled` is true, and it defaults to **`False`**
(`app/config.py:1175`; the drop is at `smart_router.py:1577` and `:1665`). I did not read the running
service's environment, so I cannot say which mechanism produced the observed call — only that either
one alone explains it, and the tier-floor mechanism is the one that survives the flag being on.

**The fix, as a one-line change a reviewer can check:** narrow the floor to the fast tier instead of
admitting everything above it. Two shapes, and the first is the honest one:

```python
# app/services/smart_router.py — RoutePolicy gains an explicit ceiling, and
# _capability_rejection compares it:
#   min_tier="fast", max_tier="fast"   ->  only tier == "fast" candidates survive
# or, without a new field, lower the existing cap:
#   max_output_cost_per_mtok=1.0       ->  rejects v4-pro's 0.87 only if the
#                                          DB rows price it above 1.0; today it
#                                          does not, so this alone is NOT enough
```

The second shape is written down because it is the obvious wrong answer: `0.87 < 1.0`, so it does nothing.
**The only fix that works is a tier ceiling (or changing the v4-pro row's tier), and it belongs to
`personal-secretary-mvp` — not to this fleet.** I own `packages/plugin-cost/**` and this document; I do
not own `smart_router.py`, it is loaded by a running service on `secratary` whose restart I was not
asked to do, and changing a shared route serving VS Code and the company's own agents without an owner's
yes is exactly the class of change that must not be silent. **So it is recorded, not changed.** It is
also in the owner's own queue as `[SECRETARY-FAST-TIER]`.

**And the trap is currently unstepped-on, which is the good news.** Re-verified today on this machine:
no `SECRETARY_API_BASE`, no `secretary-*` route and no gateway hostname anywhere in
`~/.dsh/settings.yaml`, `settings/base.yaml`, `settings/machines/*.yaml` or `presets/**` — the single
grep hit is the standing instruction's own prose about preferring those aliases. The DSH fleet calls
`api.deepseek.com` directly on `deepseek-flash`, so **no agent in this fleet is exposed to the alias
today**. The standing instruction's advice to prefer `secretary-fast` is, measured, advice to spend 3.1×
more than intended — which is why the alias must be fixed before anyone follows it.

---

## 8. What this does **not** cover

1. **The other machine.** The live counter is exact for **one engine's** traffic. On 2026-09-15,
   **56.5 % of the day came from ZABZ-TECH** and this machine's logs saw none of it. Until the layer-2
   roll-up posts per-host totals into the authority (doc 65 §3.6, P209's own recorded fix — not
   implemented here), the *fleet* has no ceiling; each host has one.
2. **A second engine on this host.** Two DSH engines share `~/.dsh/spend-guard/day.json`, and each will
   overwrite the other's total. Two engines on one machine therefore see roughly one engine's spend each
   — bounded, but not additive. Named here because it is not obvious from the code.
3. **Editor traffic.** `vscode copilot` was $3.83 of the $54.92 day and never touches DSH.
4. **Anything already in flight when the ceiling trips.** A model call in progress completes and is
   billed; the overrun is bounded by one step, not zero.
5. **Retries.** Each retry is a separately billed attempt and the guard counts each as it lands, but a
   retry storm inside one step is bounded only by `retryPolicy.maxRetries: 2`.
6. **The card is manual data.** A rate change is not detected. A wrong card makes the counter wrong by
   exactly the rate error.
7. **Cost scales with context, and the notice says so — the guard does not shrink anything.** It warns,
   refuses fan-out and refuses steps. It never truncates a prompt or downgrades a model; silently
   changing what the model sees would be a worse failure than the one it prevents.

---

## 9. How it reaches the live engine — the one command that acts

The guard is **installed in the repository and not yet mounted in the live engine.** That is deliberate:
mounting it requires the engine to reload a patch layer, and the owner's engine was not to be restarted.
What is proven is the mechanism (§6), on a real engine, with the real module.

**The row is already in the bundle patch** (`packages/plugin-cost/cordis.patch.yml`), so it takes effect
on the **next engine start** with no further edit. Composition was verified non-destructively:

```
$ node …/dsh/lib/bin.js --profile web --dump-config
- id: plugin-cost
  name: dsh-plugin-cost
- id: spend-guard
  name: dsh-plugin-cost/guard
    config:
      warnUsd: 35
      fanoutUsd: 80
      ceilingUsd: 150
      concurrencyCap: 12
      onInternalError: closed
```

**The deployment path for every machine** (the existing, documented one):

```powershell
git -C ~/code/harness-config pull
python ~/code/harness-config/scripts/sync.py            # settings + presets + the profile patch layer
pwsh   ~/code/harness-config/scripts/install-client-plugins.ps1
node   ~/code/harness-config/packages/plugin-cost/scripts/build.mjs   # regenerate lib/ from src/
# then reload the profile page; the engine picks up a new bundle ROW at its next start
```

**An attempt that did not work, recorded so nobody repeats it.** Writing the row into the live
`~/.dsh/profiles/web/cordis.patch.yml` — which `dsh-web`'s own `patchReload: live` watches
(`dsh/lib/profile-boot-*.js:321-338` registers the profile patch path and `$DSH_HOME/cordis.patch.yml`
with `watchUserPatches`, and a change transactionally re-composes the patch stack) — did **not** activate
the guard on pid 4880: no `~/.dsh/spend-guard/` state file appeared within ~10 s and the file's change
was otherwise silent. Two things were learned and are worth keeping: a whole-file rewrite of that YAML
**destroys its `!!js` expressions** (`yaml.parse` yields `null` for `!!js` and re-emitting nulls breaks
`trustedHosts`), so any automated editor of that file must be a surgical text insert; and the patch layer
was restored byte-identical afterwards (`sha256 850734E8…68F0`). **Whether HMR re-composition actually
mounts a brand-new loader entry on this build was not established**, and is the honest reason the live
engine does not yet have a guard.

---

## 10. What I could not verify

1. **A live-cap refusal on a real engine.** The cap's policy and its count are proven (§6.5); a real
   refusal *by the cap* was not produced. The cause is understood and written down: an agent parked on a
   tool result is not `running`, so a `concurrencyCap: 1` test let one subagent through while the parent
   waited on it.
2. **Engine-restart idempotence.** The unit suite proves the persisted-day path (a restart resumes
   `micro` from `day.json`, and an event at or before the watermark is ignored), but no real engine has
   been restarted mid-day to confirm the day's figure does not jump. **That is the first thing to test
   after the first restart**, by comparing `day.json` before and after.
3. **HMR activation of a new loader entry on the running engine** (§9).
4. **The scanner this machine's own lives depend on.** `seedFromLogs` was exercised with an injected
   reader returning one synthetic event, and the real scan path was not run against the owner's 450+ live
   logs in this session. The scan is doc 65's measured 15.5 s and it is one-shot at activation, so this is
   a performance claim, not a correctness one.
5. **Which mechanism produced doc 96's `secretary-fast → deepseek-v4-pro` call** — the tier floor, or
   `ai_gateway_direct_deepseek_enabled = False`, or both. I did not read the running gateway's
   environment. The tier-floor mechanism is provable from source and survives the flag being on; the
   other is inference from a default.
6. **Whether the account's real console ledger matches this counter.** The guard is priced on the card,
   and doc 65 §2.2 measured the local logs at 50 %/76 % of the ledger. A second paired day (a console
   export plus a `spend-guard.py report` at the same moment) is still the one measurement that would turn
   this counter into bill dollars.

---

## 11. Bottom line

- **The wallet now has a ceiling, and it is installed as code and data**: `$35 / $80 / $150` per UTC day
  and **12 generating agents per machine**, in `settings/base.yaml`, enforced by
  `packages/plugin-cost/src/guard.mjs` at `agent/pre-step` — before `step/start`, therefore before
  anything is billed.
- **It was shown working, not asserted to work**: warn and fan-out notices, and a refusal whose turn ends
  `blocked` with **no `step/start` and no usage-carrying `assistant/message`**, all on a real engine with
  an artificially low ceiling; and a real engine running normally with the real defaults in force.
- **It fails closed in five named places**, each with the code and a failing-if-wrong test.
- **A scan seeds; the live stream decides.** The seed can only lower the counter, because on the one day
  that could be reconciled the logs held half the misses and three-quarters of the hits.
- **The one remaining live trap is the gateway's `secretary-fast`, which means "fast or better" and
  therefore selects a model that costs 3.1× more.** Nothing in this fleet is pointed at it today, the
  mechanism is identified to the line, the effective fix is a tier ceiling in
  `personal-secretary-mvp/app/services/smart_router.py`, and that file is not mine and its service was
  not restarted — so it is recorded and queued rather than changed.
