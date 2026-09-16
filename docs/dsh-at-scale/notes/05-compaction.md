# 05 — DSH compaction system, exhaustive audit

Audit date: 2026-09-15 · machine ZABZ-YOGA · read-only.
Path root shorthand below: `$DSH` = `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai`.
All line numbers are `$DSH\<pkg>\lib\index.js` unless the path is written out in full.
Anything labelled `INFERRED:` is my reasoning, not the code's statement.

---

## 1. The compaction plugins

Four plugins, one seam.

| Plugin | Role | Package |
|---|---|---|
| `dsh-compaction` | The seam. Abstract `CompactionEngine extends Service` registered as `ctx.compaction`; checkpoint provenance; tool-pairing balance | `$DSH\dsh-compaction` |
| `dsh-compaction-basic` | The only backend. Trigger policy, retention selection, summarisation, durable commit | `$DSH\dsh-compaction-basic` |
| `dsh-compaction-tool-result-pruner` | Deterministic, non-LLM tool-output pruning. Runs *before* the summariser and can alone clear the trigger | `$DSH\dsh-compaction-tool-result-pruner` |
| `dsh-command-compact` | The human `/compact` command over the seam | `$DSH\dsh-command-compact` |

`dsh-compaction/lib/index.js`
- `:172-176` `var CompactionEngine = class extends Service { constructor(ctx) { super(ctx, "compaction"); } }` — one implementation per context.
- `:109-125` `COMPACT_CHECKPOINT_MARKER = { kind: "plugin", plugin: "compact" }`; `compactCheckpointSource(compactionId, sourceCommandId)`.
- `:80-93` `toolPairingBalancedBefore/After` — a cut is only legal if no unanswered tool call crosses it. Backed by a per-session `WeakMap` balance cache (`:19`, `:29-64`). Throws on a corrupt surface (`:36-38`).

Measurement comes from a fifth package, not a plugin of the seam: `dsh-token-meter` (`ctx.tokenMeter`).

---

## 2. Config-key table

### 2.1 `dsh-compaction-basic` — `static Config` at `:766-777`

Schema objects are declared at `:732-751`. There is **no** `.default(...)` call anywhere in the schema — **every default is applied in `resolveConfig` (`:58-78`), not by schemastery**, which is why `config: {}` and "row absent" behave identically.

| Key | Schema | Exact default | Source of default | Type / unit | What it does |
|---|---|---|---|---|---|
| `thresholdRatio` | `z.number()` `:732` | `0.8` | `DEFAULT_THRESHOLD_RATIO` `:15`, applied `:62` | dimensionless fraction of the model's **context window** | Compaction fires when measured total pressure ≥ `floor(contextWindow × thresholdRatio)`. Validated to be in `(0, 1]` — `assertRatio` `:200-202` |
| `retainRatio` | `z.number()` `:733` | `0.16` | `DEFAULT_RETAIN_RATIO` `:17`, applied `:63` | fraction of the **context window** | Size of the verbatim recent tail kept after compaction. Must be `< thresholdRatio` or plugin load throws `:135` |
| `retainTokens` | `z.number().step(1).min(0)` `:734` | unset | — | absolute tokens | Same thing, absolute. **Mutually exclusive** with `retainRatio` — `:169`, `:128-132` |
| `summarizationProvider` | `z.string()` `:735` | `""` (empty) | `:70` | provider route id | Which provider runs the summary. Empty ⇒ inherit |
| `summarizationModel` | `z.string()` `:736` | `""` (empty) | `:71` | model id | Which model runs the summary. Empty ⇒ inherit. Must be set/empty **as a pair with the provider** — `:176-183` |
| `maxTokens` | `z.number().step(1).min(1)` `:737` | `8192` | `:72` | output tokens | Generation cap for **the summary request only** |
| `compactionRetries` | `z.number().step(1).min(0)` `:738` | `1` | `:73` | count | Extra compaction attempts in the same step when pressure is still ≥ threshold (so up to 2 attempts) |
| `maxOverflowRetries` | `z.number().step(1).min(0)` `:739` | `1` | `:74` | count | Attempts after a provider `CONTEXT_WINDOW_EXCEEDED`. `0` disables recovery |
| `modelPolicies` | `z.array(modelPolicy)` `:775`, shape `:740-751` | unset → `[]` `:139` | — | array | Exact `provider`+`model` overrides of every key above **except `contextWindow`**. Duplicate target ⇒ load error `:145` |
| `auto` | `z.boolean()` `:776` | `true` | `:76` | boolean | Registers the automatic listeners at `:793-847`. `false` ⇒ compaction only via `/compact` |

Unknown keys are rejected at load (`validateKeys` `:185-187`), so a typo cannot silently fall back to a default.

Derived spec — `resolveCompactSpec` `:108-126`:
```
:111  const thresholdTokens = Math.floor(contextWindow * policy.thresholdRatio);
:112  const retainTokens    = policy.retainTokens === void 0 ? Math.floor(contextWindow * policy.retainRatio) : policy.retainTokens;
:113  if (retainTokens >= thresholdTokens) throw new TargetPressureConfigError(...)
```
There is **no** key for a message count, turn count or node count. Retention is token-only.

### 2.2 `dsh-compaction-tool-result-pruner` — `:60-67`

| Key | Default | Unit | What it does |
|---|---|---|---|
| `thresholdChars` | `8192` (`DEFAULTS` `:10-14`, applied `:36`) | Unicode **code points** of text in one tool result | A tool result whose text exceeds this is pruned |
| `headChars` | `4096` (`:11`, `:37`) | code points | Kept from the start |
| `tailChars` | `1024` (`:12`, `:38`) | code points | Kept from the end |

The middle is replaced by the fixed marker `"\n\n[... tool result middle pruned ...]\n\n"` (`lib/types/config.d.ts:4`, used `:109`). Slicing is by code point so surrogate pairs are not split (`:104-111`). Invariant `headChars + marker + tailChars ≤ thresholdChars` enforced at `:43-44`; the replacement is verified smaller and in-budget at `:120-122`.

### 2.3 `dsh-command-compact`

No configuration at all. `lib/index.js:48-71` — argument-free `/compact`; it calls `ctx.compaction.compactNow(invocation.agent, signal, commandId)` and reports `Compacted N history items` or a classified failure (`busy` / `cancelled` / `changed` / `summary` / `commit` / `persistence`, `:17-46`).

---

## 3. What actually triggers compaction

Three triggers, all in `dsh-compaction-basic`.

**(a) Step-boundary pressure — the normal path.** `:798-811` registers `ctx.on("agent/pre-step", ...)` which calls `compactIfNeeded(agent, "pressure", signal)` before every step.

`:873-920` is the whole decision:
```
:877  const meter = this.ctx.tokenMeter;
:878  let measurement = meter.measure(agent.session);
:895  const context = (await this.ctx.llm.resolveModelInfo(target.provider, target.model, signal)).context;
:898  if (context === void 0) throw new TargetPressureConfigError(targetKey, `compaction-basic: no context capacity for ${targetKey}; configure contextWindow on that adapter model`);
:899  const spec = resolveCompactSpec(policy, context.contextWindow);
:900  if (measurement.totalTokens < spec.thresholdTokens) return null;
:901  if (prune !== void 0) { prune.pruneSession(agent.session); measurement = meter.measure(agent.session); }
:905  if (measurement.totalTokens < spec.thresholdTokens) return null;
:907  for (let attempt = 0; attempt <= spec.compactionRetries; attempt += 1) { ... }
:919  throw new Error(`compaction still above threshold after ${spec.compactionRetries + 1} compaction attempts (...)`);
```

So: **the threshold is an absolute token count, derived at runtime as a fraction of an adapter-supplied `contextWindow` for the exact routed provider/model.** It is not a fraction at comparison time, not a message count, and not configurable as an absolute token number directly (only via `retainTokens` for retention — there is no `thresholdTokens` key).

Two important consequences visible in the code:
- The **pruner runs first and can cancel compaction entirely** (`:901-905`): a pruned session that drops back under threshold returns `null` with no LLM call.
- If the retry loop exhausts, it **throws** (`:919`); the pre-step listener catches and logs but continues the turn (`:802-809`). A stuck-above-threshold session therefore compacts every step and still runs. `INFERRED:` that is the pathological loop to watch for.

**(b) Provider-confirmed context overflow.** `:820-846`, `ctx.on("agent/request-error", ...)`, gated on `failure.code !== CONTEXT_WINDOW_EXCEEDED_CODE` (`:821`). On overflow it *bypasses* the threshold and the retained-tail policy entirely — `:891` calls `selectCompactableRange(session, measurement, 0)`, i.e. `retainTokens = 0`, so it compacts as much as is legal and useful. Retries capped by `maxOverflowRetries` (`:826-827`).

**(c) Manual `/compact`.** `:944-970` `compactNow`, requiring an idle agent (`agent.runMaintenance`) and using `retainTokens = 0` as well (`:951`).

### 3.1 Is the number real API usage or an estimate?

Both, conditionally — `dsh-token-meter/lib/index.js:643-686`:
```
:652  if (anchor !== void 0 && optionalHeaderEquals(anchor.header, header)) {
:653    const anchorSurfaceTokens = priceSurface(anchor.nodes, pricing, fileText).surfaceTokens + anchor.assistantTokens;
:654    const estimatedAnchorTokens = estimateToolsTokens(header) + anchorSurfaceTokens;
:655    const usage = anchor.usage;
:656    baseline = usage !== void 0 && usageTokens(usage) >= estimatedAnchorTokens ? { kind: "usage", tokens: usageTokens(usage), usage }
:660                                : { kind: "estimated", tokens: estimatedAnchorTokens };
:664    surfaceDeltaTokens = surface.surfaceTokens - anchorSurfaceTokens;
```
- Provider-reported usage is used **only if** the latest successful call's canonical request envelope matches the current header **and** its total is ≥ the route-priced estimate. Otherwise the whole envelope and surface are repriced.
- `usageTokens` (`:594-596`) = `inputTokens + cacheReadTokens + cacheWriteTokens + outputTokens`. The previous assistant's *output* is included because that output is in the next request's prompt. The bucket names come from `bucketsFrom` (`:348-352`), where `usage.inputTokens` is the **uncached** portion — so no double count.
- The fallback heuristic is fixed-density: `CHARS_PER_TOKEN = 4` (`:16`), `BLOCK_OVERHEAD = 4` per block (`:18`), `estimateContent` `:34-50`, `estimateMessage` `:71-74`, `estimateToolsTokens` `:81-84`. So a fresh session with no completed call is priced by `ceil(chars/4)`, and every post-compaction re-measure starts from that heuristic anchor.
- `assistantTokens` in the anchor price is itself an estimate: `_estimateProviderAssistant` `:776-778`.
- The UI-facing pressure projection deliberately excludes output (`pressureFrom` `:388-389`) — that is a *different* number from the one the trigger uses. `INFERRED:` this is a likely source of "the meter says X but compaction fired at Y" confusion; the trigger number is `measure().totalTokens`, not `contextPressure`.

**The completion reservation is not in the trigger.** `:900`/`:905` compare prompt-side pressure to `thresholdTokens`. The request's `max_tokens` is not added. See §6.

---

## 4. Where `contextWindow` comes from

Chain, all code:

1. `dsh-compaction-basic/lib/index.js:895` — `(await this.ctx.llm.resolveModelInfo(target.provider, target.model, signal)).context`.
2. `dsh-llm/lib/index.js:2051-2070` `normalizeModelInfo` — accepts the adapter's `context.contextWindow` only if a positive integer (`:2055`, else `LlmError INVALID_MODEL_CONTEXT`), and re-emits it at `:2067`.
3. `dsh-llm-deepseek/lib/index.js:1578-1599` `modelInfoFor`:
```
:1579  const configured = connection.models.find((entry) => entry.id === model);
:1580  const contextWindow = configured?.contextWindow ?? connection.defaultContextWindow;
:1588  context: { contextWindow },
:1590  ...configured?.systemPromptUpdate === void 0 ? {} : { systemPromptUpdate: configured.systemPromptUpdate },
```
4. Defaults: `:1392 const DEFAULT_CONTEXT_WINDOW = 1e6;` — used by every entry of `DEFAULT_MODELS` (`:1841-1871`, `deepseek-flash` at `:1843-1850` with `contextWindow: DEFAULT_CONTEXT_WINDOW` `:1845`), by the schema `:1895 defaultContextWindow: z.number().step(1).min(1).default(DEFAULT_CONTEXT_WINDOW)`, and by the resolved connection `:1999 defaultContextWindow: config.defaultContextWindow ?? 1e6`.

This deployment's lane: `harness-config/settings/base.yaml:58-60` (`agent-default-model: provider: deepseek-official, model: deepseek-flash`) and `:62-74` (`agent-presets: default: zabz`); installed mirror `C:\Users\ezabz\.dsh\settings.yaml:7-11`. `PROVIDER = "deepseek-official"` is `dsh-llm-deepseek/lib/index.js:1840`.

**Answer: 1,000,000 comes from `DEFAULT_CONTEXT_WINDOW = 1e6` in the DeepSeek adapter's own hardcoded model catalog — not from the API's `/models` response and not from any settings file.** Confirmed by absence: `harness-config/settings/base.yaml:87-96` (`llm-deepseek:`) sets only `streamIdleTimeoutMs` and `retryPolicy`; `settings/machines/ZABZ-YOGA.yaml` (20 lines) touches only `llm-pi-ai` and `agent-loop`; `~/.dsh/settings.yaml:12-26` mirrors exactly that, with no `models:`, no `defaultContextWindow`, no `maxTokens`.

Verified against the observed live event: `{"provider":"deepseek-official","model":"deepseek-flash","contextWindow":1000000,...}` is fully explained by `:1580` falling through to `:1999`'s `1e6`.

**The catalog is optimistic against reality.** The observed API error says *"This model's maximum context length is 1048576 tokens"* — 1,048,576 = 2^20. The adapter's declared window is 1,000,000, i.e. **48,576 tokens below the provider's own limit**. DSH will therefore never use the top 48,576 tokens of the real window.

`maxTokens` on the same route: `:1394 const DEFAULT_MAX_TOKENS = 256e3;`, schema `:1894`, resolved `:1998 maxTokens: config.maxTokens ?? 256e3`, per-model override `:1878`, emitted `:246 {...options.maxTokens === void 0 ? {} : { max_tokens: options.maxTokens}}`. `256000` matches the observed error verbatim (*"256000 in the completion"*).

---

## 5. What is kept after compaction — and the summariser

### 5.1 Retention

`selectCompactableRange` `:393-416`:
```
:398  const firstIdx = systemHead(session, surfaceNodes[0]) === void 0 ? 0 : 1;
:400  let keepFromIdx = pricedNodes.length;
:401  for (let index = pricedNodes.length - 1; index >= 0; index -= 1) {
:402    accumulated += pricedNodes[index].tokens;
:403    keepFromIdx = index;
:404    if (accumulated >= retainTokens) break;
:405  }
:406  if (keepFromIdx <= firstIdx) return null;
:407  while (keepFromIdx > firstIdx) {
:408    if (toolPairingBalancedBefore(session, surfaceNodes[keepFromIdx])) break;
:409    keepFromIdx -= 1;
:410  }
:411  if (keepFromIdx <= firstIdx) return null;
:412  return { start: surfaceNodes[firstIdx], end: surfaceNodes[keepFromIdx - 1] };
```
- Walk backward accumulating **priced tokens** until `retainTokens` is reached; then walk further back until the cut is tool-pairing balanced. Nothing is expressed in messages or turns.
- **There is no "keep last N turns" key.** The only keys are `retainRatio` / `retainTokens`.
- Surface node 0 is never compacted when it is a `system/message` (`:398`, and the doc comment `:383-387`: "A `system/message` at surface node 0 is never inside the range").
- The region is replaced by exactly **one** synthesised user message (`:567-570`) carrying `compactCheckpointSource`, whose text is `CHECKPOINT_PREAMBLE` + `<compacted-summary>` … `</compacted-summary>` (`:257`, `:211-212`, `:323-335`).
- If the region cannot beat its own shadow, the whole attempt fails: `:572 if (framedSummaryTokenCount >= prepared.shadowedRouteTokenCount) throw new Error("summary is not smaller than the shadowed content ...")`. `INFERRED:` a very large single node can make a range unusable.

### 5.2 Which model summarises

`summarizeWithLlm` `:269-317`:
```
:270  const latest = agent.session.requestHeader()?.config;
:271  const configured = config.summarizationProvider.length === 0 ? void 0 : { provider: ..., model: ... };
:275  const agentTarget = ...agent.options.provider/model...;
:279  const target = configured ?? latest ?? agentTarget;
:280  if (target === void 0) throw new Error("no provider/model available for summarization: ...");
:297  maxTokens: config.maxTokens,
:299  purpose: "compaction",
```
Because this deployment sets neither `summarizationProvider` nor `summarizationModel`, `configured` is `undefined` and the target is `latest` — **the summarisation runs on the same provider and model as the main loop (`deepseek-official` / `deepseek-flash`), not a cheaper separate model.** It *can* be configured separately with the pair of keys (`:176-183` enforces set-as-a-pair), but nothing in the deployment does. The summary's generation cap is 8192 (`:297` → `config.maxTokens`), not the 256,000 the main loop gets.

### 5.3 Does the summary request re-send the whole context at full price?

**No — it re-sends only the region being compacted, plus the system head and the tool schemas, and it is deliberately constructed to be a cache-reusing prefix.**

`buildSummarizationInput` `:666-675`:
```
:667  const header = session.requestHeader();
:668  const head = systemHead(session, session.surface.nodes[0]);
:669  const system = head === void 0 ? null : session.deriveEventMessage(head);
:670  const regionMessages = shadowedSeqs.map((seq) => session.deriveEventMessage(session.eventAt(seq))).filter((message) => message !== null);
:671  return {
:672    ...header?.tools === void 0 ? {} : { tools: header.tools },
:673    messages: system === null ? regionMessages : [system, ...regionMessages]
:674  };
```
`shadowedSeqs` is the selected range from `:412-415` — **it excludes the retained tail**. Then `:282-291`:
```
:282  const messages = [...input.messages, createUserMessage({ content: [{ type: "text", text: COMPACTION_INSTRUCTION }], source: { kind: "plugin", plugin: "dsh-compaction-basic" } })];
```
and the intent is stated at `:655-661`: *"the system prompt held by the `system/message` at surface node 0, the header's tool schemas, then the region's own derived messages in surface order. The summarizer appends only the compaction instruction after this, so the call is a genuine prefix of the conversation and reuses the provider's KV cache."* Likewise `:213-219` and `:848-852`.

So the billed input of one compaction ≈ **`thresholdTokens − retainTokens`** ≈ 640,000 tokens at this deployment's defaults — not 1,000,000, and not the whole live context. Whether that lands as a cache *read* or a cold *write* depends on the provider's cache being warm and keyed on the same prefix. It is a separate, separately-billed API call either way (`:302 for await (const chunk of ctx.llm.stream(options))`). The direct instruction `COMPACTION_INSTRUCTION` is `:220-255` and forbids the model from mentioning the compaction.

`INFERRED:` I cannot determine DeepSeek's actual cache-hit/cache-miss price multipliers from the code I read, so I cannot convert this into currency.

### 5.4 Does compaction rewrite the system prompt / invalidate the KV cache?

`systemPromptUpdate: "in-history"` is a **capability the routed model declares**, not a compaction setting:
- Declared: `dsh-llm-deepseek/lib/index.js:1849` — the `deepseek-flash` catalog entry carries `systemPromptUpdate: "in-history"`; schema field `:1882 systemPromptUpdate: z.const("in-history")`; emitted `:1590`; validated `dsh-llm/lib/index.js:2057-2058`.
- Consumed: `dsh-agent-loop/lib/index.js:1019-1027`:
```
:1019  const commits = this.systemPrompt.project(renderedPrompt, {
:1020    inHistory: preparedCall?.systemPromptUpdate === "in-history",
:1021    startsSeries: startsRequestSeries || this.requestSurfaceGeneration !== this.session.surface.replaceGeneration || this.toolsChanged(assembly.tools)
:1022  });
```
- Meaning, `SystemPromptProjection.project` `:266-284`:
```
:274  if (!input.inHistory || input.startsSeries || rendered.length === 0) {
:275    const updates = nodes.slice(1).filter((node) => node.text !== "").map((node) => this.replace(node.seq, ""));
:276    if (head.text !== rendered) updates.push(this.replace(head.seq, rendered));
:277    return updates;
:278  }
:279  if (latest.text === rendered) return [];
:280  return [{ message: createSystemMessage(rendered, SOURCE), intent: { surfaceOp: "append" } }];
```
`systemNodes()` `:247-257` collects **every** `system/message` on the surface.

So the answer to "does the system prompt live inside the message history" is **yes, on this route**: with `in-history`, a changed prompt is *appended as a new `system/message` node* (`:280-283`) instead of replacing node 0, precisely so the cached prefix survives. Consequences:

- **Compaction can prune or rewrite most of the system prompt.** `selectCompactableRange` protects only surface node 0 (`:398`). Every in-history system node at index ≥ 1 is inside `start..end` and gets summarised into prose. The head is safe; later prompt revisions are not.
- **Compaction forces the next request to stop being a continuing series.** Compaction bumps the surface generation; the very next step evaluates `this.requestSurfaceGeneration !== this.session.surface.replaceGeneration` (`:1021`) as `true` → `startsSeries` → `project` takes the `:274` branch → **all non-head system nodes are emptied (`:275`) and the head is rewritten if its text differs (`:276`)**. `INFERRED:` this is the mechanism by which the prompt prefix after a compaction differs from the prompt prefix before it, which is exactly the condition that loses the provider's KV cache for the system-prompt region. The code states the intent in the class doc at `:233-239`: *"A capable continuing series appends changed nonempty text after the cached history. An incapable route, broken series, or cleared prompt instead normalizes the first system node and empties later active nodes."*
- The same surface mutation also discards the derived-message cache — `INFERRED` from the existing audit at `harness-config/docs/multi-window/research-single-engine-scaling.md:678,919` (reset only on a surface generation bump, i.e. on compaction).

---

## 6. What this deployment has set right now

**Nothing. Every compaction key is at its shipped default.**

| Where | Line | Value |
|---|---|---|
| `harness-config/presets/zabz/agent.cordis.yml` | `234-235` | `- id: compaction-basic` / `name: '@deepseek-ai/dsh-compaction-basic'` — **no `config:` block at all** |
| `harness-config/presets/zabz/agent.cordis.yml` | `240-245` | pruner row **does** set `thresholdChars: 8192`, `headChars: 4096`, `tailChars: 1024` — identical to the shipped defaults, so no-op |
| `C:\Users\ezabz\.dsh\.agent-presets\zabz\agent.cordis.yml` | `234-243` | identical to the repo copy (installed runtime mirror) |
| `presets/cordis-bg/agent.cordis.yml` | `147-158` | same rows, same no-config `compaction-basic` (the preset `zabz` derives from) |
| `dsh-base/cordis.patch.yml` | `320-321`, `394-395` | host-plane `compaction-basic` and `tool-result-pruner` rows, also unconfigured |
| `harness-config/settings/base.yaml`, `settings/machines/ZABZ-YOGA.yaml`, `C:\Users\ezabz\.dsh\settings.yaml` | all | zero matches for `compaction`, `thresholdRatio`, `retainRatio`, `retainTokens`, `contextWindow` |
| `~/.dsh/.agent-presets/*` | — | only `thresholdChars/headChars/tailChars`; no compaction-basic config anywhere |

### Effective spec, computed from the code

```
contextWindow  = 1,000,000        (dsh-llm-deepseek:1392 → 1845 → 1580 → 1999)
thresholdRatio = 0.8   → thresholdTokens = floor(1e6 × 0.8)  = 800,000   (compaction-basic:111)
retainRatio    = 0.16  → retainTokens    = floor(1e6 × 0.16) = 160,000   (compaction-basic:112)
maxTokens (summary) = 8,192 ;  compactionRetries = 1 ;  maxOverflowRetries = 1 ;  auto = true
summariser target = the routed request's own provider/model = deepseek-official/deepseek-flash
pruner = 8192 / 4096 / 1024 code points, and it runs BEFORE the threshold test
```

---

## 7. 1,000,000 → 400,000

### 7.1 The two ways to do it are not the same change

"Changing the budget to 400k" is ambiguous in this code, because `contextWindow` drives **both** the threshold and the retained tail:

| Lever | `thresholdTokens` | `retainTokens` | Per-cycle growth room |
|---|---|---|---|
| today (`W=1e6`, `t=0.8`, `r=0.16`) | 800,000 | 160,000 | **640,000** |
| `llm-deepseek.defaultContextWindow: 400000` (or per-model `contextWindow: 400000`) | 320,000 | 64,000 | **256,000** |
| `compaction-basic.thresholdRatio: 0.4` only | 400,000 | 160,000 | 240,000 |
| `thresholdRatio: 0.4` + `retainTokens: 64000` | 400,000 | 64,000 | 336,000 |

Only the second row is literally "the context budget is 400k". The third is the cheaper, reversible way to buy headroom without touching the adapter — and `compaction-basic.modelPolicies` **cannot** change `contextWindow` at all (`types.d.ts:27-32` lists only `provider`, `model` + the eight policy fields; `resolveCompactSpec` `:108-126` takes `contextWindow` as an argument, never a key).

Setting `contextWindow` via `llm-deepseek.defaultContextWindow: 400000` is the config-level route (schema `:1895`, resolve `:1999`).

**Trap, code-evidenced:** if you instead set `llm-deepseek.models: [...]`, that list **replaces** `DEFAULT_MODELS` entirely (`:1896 models: z.array(catalogModel).default(DEFAULT_MODELS)`, and `harness-config/settings/base.yaml:102` states *"Machine files may narrow `models`; their array replaces this one"*). You must then re-declare `systemPromptUpdate: in-history` on the `deepseek-flash` entry (`catalogModel` field `:1882`) or the route silently loses that capability, `modelInfoFor` stops emitting it (`:1590`), and `inHistory` at `agent-loop:1020` becomes `false` — which flips the system prompt to the prefix-rewriting branch (`agent-loop:274-277`) on every change.

### 7.2 Arithmetic

Steady state: after a compaction the context is `retainTokens` (plus one checkpoint node); it then grows until `thresholdTokens`, when it compacts again. Per-cycle room = `thresholdTokens − retainTokens`.

**How much earlier it fires.** First compaction at 320,000 measured tokens instead of 800,000 — **fires 480,000 tokens earlier, at 40% of the old trigger point.** For a session whose running request pressure is `T` tokens, the number of compaction events is `N = 1 + floor((T − threshold) / room)`:

| `T` (total conversation tokens) | `N` today (800k / 640k room) | `N` at 400k window (320k / 256k room) | extra events |
|---|---|---|---|
| 400,000 | 0 (never fires) | 1 | +1 |
| 800,000 | 1 (right at the line) | 2 | +1 |
| 1,000,000 | 1 | 3 | +2 |
| 2,000,000 | 2 | 7 | **+5** |
| 3,000,000 | 4 | 11 | +7 |
| 5,000,000 | 7 | 19 | +12 |
| asymptote | `T/640,000` | `T/256,000` | **2.5×** |

Asymptotically **2.5× as many compaction events** (`640,000 / 256,000 = 2.5`). The ratio is *worse than 2.5×* for mid-size sessions because the first trigger moves 480,000 tokens earlier: 2M gives 3.5×, 3M gives 2.75×, and it converges to 2.5× only as `T → ∞`.

Note the "0 → 1" row: with the 400k window, sessions that today never compact at all will start compacting. That is the qualitative change, not just a multiplier.

### 7.3 Can compacting MORE OFTEN cost MORE? Yes.

The counter-intuitive part first: **the summariser's input volume is invariant, not increased.**

- Per event the summariser replays the shadowed region, which at trigger time is ≈ `thresholdTokens − retainTokens` = the cycle room (`buildSummarizationInput` `:666-674`, `selectCompactableRange` `:393-415`). Today that is 640,000; at 400k it is 256,000.
- Events scale as `1 / room`. So `total summariser input ≈ (T / room) × room = T` **either way**.

So the summary-*input* bill does not rise. Three other channels do:

1. **Summariser output scales with event count, not volume.** Each event emits a fresh structured checkpoint capped at `maxTokens: 8192` (`compaction-basic:72`, `:297`; realistic output is a fraction of that). At 2.5× the events that is **~2.5× the summariser's output tokens**, and output is normally the most expensive bucket per token. This is the dominant "more compaction costs more" term.
2. **Per-event fixed overhead and wall clock.** Each event appends a durable `compaction/start` + `compaction/summary` + `compaction/end` triple (`:452`, `:605`, `:467`), makes one extra network round trip, and performs two synchronous whole-surface `isDeepStrictEqual` sweeps (`:581`, `:595-596`) whose cost is O(surface nodes) — flagged as the most visible single event-loop stall by the existing audit (`harness-config/docs/multi-window/research-single-engine-scaling.md:167-173`). 2.5× as many of those.
3. **Cache-churn.** Every compaction replaces the region with one node and bumps the surface generation, so the next request is a broken series (`agent-loop:1021`) and the retained tail plus the whole system-prompt region must be re-established in the provider's cache. The *volume* is invariant (`events × retainTokens = 0.25 T` either way), but cache **writes** are priced above cache **reads**, and 2.5× more restarts means 2.5× more opportunities for the retained tail to miss the cache entirely. At 400k the tail is only 64,000 tokens, so a cycle is much shorter and more likely to fall inside the provider's cache TTL between requests.

**Net:** more frequent compaction does not buy its savings where the bill is largest. It trades a smaller per-event input for more events, keeps total summary input flat, and multiplies the summary *output*, the fixed per-event cost, the stalls, and the re-warm frequency by ~2.5×. `INFERRED:` with no measured price table for this provider in the repo I could not put a dollar figure on it, and I have not measured this machine's real per-session token volumes, so I cannot say whether the 400k setting would show up as a cost increase or a cost decrease in the monthly bill — only which channels multiply.

### 7.4 A defect that the 400k change would hide

From the observed error: `1049125 requested = 793125 in the messages + 256000 in the completion`, limit `1048576`.

- The trigger compares **prompt-side pressure only** to `thresholdTokens` (`:900`, `:905`). The request's own completion reservation is never added.
- The provider validates **prompt + completion**. With `max_tokens` = 256,000 (adapter default, `:1394`/`:1998`) the largest prompt that can legally be sent is `1,048,576 − 256,000 = 792,576`.
- Today's trigger is 800,000. So there is a **7,424-token band (792,576 … 800,000)** in which DSH will *not* compact, the meter is below threshold, and the request is nevertheless rejected by the API.
- The observed failure sits inside that band (793,125 — 547 tokens above the safe ceiling, 6,875 below the trigger). It was recovered only by the overflow path (`:820-846`, `maxOverflowRetries: 1`), at the cost of one wasted failed request and a warning.
- DSH's own declared window (1,000,000) makes this structural rather than accidental: `1,000,000 − 800,000 = 200,000 < 256,000` completion reservation, so the declared headroom can never cover the completion.
- At a 400,000 window the trigger becomes 320,000 against the same 792,576 safe ceiling — a 472,576-token margin — so this specific overflow would essentially stop happening. `INFERRED:` that is a real reliability benefit of the change, separate from the cost question.

### 7.5 What I could not determine

- DeepSeek's actual cache-hit / cache-miss / output price multipliers, and whether `deepseek-flash` on this route bills cache reads at all — nothing in the packages I read carries pricing; the only pricing-shaped code is route *image* pricing (`dsh-token-meter:687-692`, `dsh-llm-deepseek:1570`).
- This machine's real per-session token volumes, therefore the true `N` and the true sign of the cost delta.
- Whether the sessions that matter actually reach `T` large enough for the 1M path to be exercised today at all — the observed overflow implies at least one session reached ~793k prompt tokens, which is below the 800k trigger, consistent with 0 compactions having fired in it.
- The provider's cache TTL/model. The adapter only sets DSH's own `streamIdleTimeoutMs: 60000` (`harness-config/settings/base.yaml:88`); any prompt-cache expiry window is provider-side and not visible in this code.
