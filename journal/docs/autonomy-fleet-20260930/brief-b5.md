# BRIEF B5 — Models and routing: what we run, what we should run, and what it costs

You are a mesh research subagent on MODEL CHOICE AND ROUTING ECONOMICS for autonomous agent work. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\b5-models.md`

## Context
Date: 2026-09-30. You run on ZABZ-TECH (Windows). The client runs an autonomous AI company on a Linux server (the authority) reachable with:

    ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts COMMAND

The authority starts headless agent sessions over ssh on this desktop. Each session is a long tool-use loop — tens to hundreds of steps, 3 to 5 million tokens mostly cache-hit input — that must read files, run commands, edit code, write structured state, and stop cleanly. Hardcoding a model name is forbidden: models must be resolved at runtime from a gateway catalogue (`GET $SECRETARY_API_BASE/v1/models` on the authority), and route aliases exist. The owner wants the best capability per dollar, and no silent failures.

## RULES
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files. No git mutations. No messages to anyone.
- READ-ONLY. You MAY run read-only commands against the authority, including fetching the gateway model catalogue with `curl`. Do NOT start any agent session, do NOT send anything, do NOT write to any store, do NOT change any config or any model id.
- **NEVER print or paraphrase a secret.** If you read a credentials file, redact keys in your report and say where the value came from, not what it was.
- You MAY browse the web with `web_search` and `web_fetch` if you have them; otherwise shell HTTP. Every external claim carries a URL and a date. Prices must come from the vendor own pricing page, with the date you read it.
- Aim to finish in under 45 tool calls. Report 10 to 16 KB, dense.

## What to do
1. **Inventory our own catalogue, live.** Find the gateway base URL and the credentials the harness uses (look in `C:\Users\ezabz\.dsh\settings.yaml`, `C:\Users\ezabz\.dsh\.credentials.yaml` — read but never print a secret — and under `C:\Users\ezabz\Code\harness-config\`). Then fetch the catalogue read-only and table every model and route alias you can see: id, alias, context window, and anything the catalogue exposes about pricing or modality. Report the endpoint you used and its timestamp. Redact any key.
2. **What the woken shifts actually use.** Find which model and profile serves a headless woken session on this machine (the profile definition and the dispatcher invocation). Is it a literal model id in a script — a time bomb — or resolved from the catalogue or an alias? Quote file:line. Also find whether any failover exists when a model returns 502 or disappears: there is a `model-failover-watch.py` on the authority — read it, report what it does, and whether it has ever fired (check its log).
3. **2026 price and performance landscape for agentic tool use.** Table the current frontier and cheap tiers from the vendor own pages: DeepSeek, OpenAI, Anthropic, Google, Meta Llama hosted, Mistral, Qwen, Moonshot Kimi, Z.ai GLM, xAI, plus any open-weight model genuinely competitive for agentic tool calling in 2026. Columns: model, input price, cached input price, output price, context, a notable agentic benchmark (name the benchmark and cite it), source and date. Mark clearly which benchmarks are vendor-published.
4. **What actually matters for a long tool-use loop.** Cite evidence on cache pricing multipliers, context length versus degraded instruction-following, tool-calling reliability benchmarks, output-token cost dominating long loops, and reasoning-token billing. Then compute the cost of ONE representative shift — state your assumptions, for example 4M cached input, 200k uncached input, 60k output — under 4 or 5 candidate models, and rank by cost and by likely quality.
5. **Routing policy.** Recommend a concrete tier policy: what alias maps to what class of work (mechanical file edits, code changes, research and browsing, planning, verification), plus the rules — resolve at runtime, validate every configured id against the catalogue and drop what is not listed, cache with single-flight and fail soft, publish which model actually served a request, and never let an outage be silent. Name what you would change in a system that today appears to have one default model for everything.
6. **Open-weight and local option.** Is a local or self-hosted model now good enough for the mechanical share of this work (file edits, summaries, classification, simple tool calls)? Name the model, the hardware it needs, the throughput, and the break-even against API pricing at tens of sessions a day. Cite sources. Be blunt if the answer is "not yet worth it".
7. **Failure modes to design against**: silent fallback to a deterministic path, a model that stops existing, provider 502s, rate limits as a scheduling signal, and how to detect each cheaply. Cite real incidents or documented patterns if you can find them.

## Output format
```
# B5 — Models and routing: what we run, what we should run, and what it costs
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30
## 1. Verdict (max 4 sentences)
## 2. Our live catalogue (endpoint, timestamp, table of models and aliases)
## 3. What a woken shift actually uses (file:line, and whether it is hardcoded)
## 4. 2026 price and performance table (sources and dates, vendor benchmarks marked)
## 5. Cost of one representative shift under each candidate (arithmetic shown)
## 6. Recommended routing policy, in concrete rules
## 7. Local and open-weight option: worth it or not, with the break-even
## 8. Failure modes and how to detect each
## 9. Candidate improvements (numbered MD-1..MD-N; TOPIC / WHAT / WHY / EFFORT S|M|L / EXPECTED GAIN / RISK / SOURCE URL+date / FIRST CONCRETE STEP) — 6 to 10 items
## 10. Not verified, and why
## 11. Sources (URL + date + what it established)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Never print or paraphrase a secret. Never invent a price or a benchmark. If the catalogue is unreachable, say so with the exact error — this system has a history of a silent failure hiding for weeks behind a plausible-looking fallback.
