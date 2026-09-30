# BRIEF B4 — Agent memory and context economics: what is real, and what we should change

You are a mesh research subagent on AGENT MEMORY AND CONTEXT ECONOMICS. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\b4-memory-context.md`

## Context
Date: 2026-09-30. You run on ZABZ-TECH (Windows). The client runs an autonomous AI company where amnesiac agent sessions, called shifts, start with no memory, claim one work item from a ledger, do it, write the result back, and exit. Measured cost of one shift is roughly 3 to 5 million tokens, mostly cache-hit input, at roughly 0.036 to 0.068 USD, with a median duration around 12 to 25 minutes. The owner complaint is that the same work gets re-derived, that the system does not get better at anything over time, and that the cost per useful action is too high. There is a home-grown journal (one markdown file per entry, about 2,800 entries, with a generated index) and a SQLite ledger.

## RULES
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files. No git mutations. No messages to anyone. READ-ONLY.
- You MAY browse the web with `web_search` and `web_fetch` if you have them; otherwise shell HTTP (`Invoke-WebRequest`, `curl.exe`). Every claim carries a URL and a date. Prefer primary sources — docs, papers, pricing pages — over blog posts. For research papers, cite the paper and say whether the code was released.
- Aim to finish in under 45 tool calls. Report 10 to 16 KB, dense, with numbers.

## Scope
1. **Memory systems, 2026 state, judged honestly.** Letta (MemGPT), Zep and Graphiti, mem0, cognee, MemOS, Supermemory, LangMem, and any 2026 entrant with published benchmarks. For each: what it actually stores (facts, graphs, episodes, embeddings), how it decides what to remember and forget, retrieval cost per query, whether it is a service or a library, licence or price, and the strongest INDEPENDENT evidence that it beats a well-built file-plus-SQLite memory. Separate marketing numbers from reproduced ones and say what you could not verify.
2. **Is structured memory better than vector memory for this workload?** Find evidence — papers and engineering write-ups — on agents using explicit typed state (task tables, ledgers, state machines, checklists, plan files) versus retrieval-augmented vector memory for long-horizon work. Which fails, how, and what the recommended hybrid looks like. Cite specifics.
3. **Context economics.** Current published prompt-cache pricing and behaviour for the major providers (DeepSeek, OpenAI, Anthropic, Google) as of 2026-09: cache-write and cache-read multipliers, the minimum cacheable prefix, TTL and eviction behaviour, and how caching interacts with a changing tool description or system prompt. Then compute: for a session re-sending a 120k-token prefix on every step for 200 steps, what the cached versus uncached cost is, and what a 10x reduction in re-sent context would save. Show the arithmetic with the real prices you found.
4. **Techniques with measured effect**, each with a source: context compaction and summarisation, subagent context offloading, tool-output truncation and structured returns, progressive disclosure of skills and instructions, retrieval instead of dumping, filesystem-as-memory, plan and checklist artifacts, cache-aware prompt layout with a stable prefix first, batching independent calls, model routing to a cheap model for mechanical steps, and stopping criteria. For each, a plausible percentage saving and whether the evidence is strong or anecdotal. Rank by expected saving for a workload like ours.
5. **Making an amnesiac workforce stateful across runs.** Literature and practice on durable agent state: checkpointed trajectories, resume from step N, replayable tool logs, handoff documents. What is the minimum viable version for a session that starts fresh every time — what should the FIRST 2,000 TOKENS of every shift contain, and how should a shift output be written so the next one can pick it up without re-reading the world? Cite the strongest examples you find, including 2026 agent products that ship this.
6. **Compounding self-improvement via memory.** Evidence on skill libraries and procedural memory that measurably improve later task performance (Voyager-style skill libraries, agent-skills formats, experience replay, trajectory distillation, GEPA-style prompt evolution). What is reproducible, and what would work with no gradient updates — that is, what can be improved purely by writing better files and better prompts.
7. **Concrete recommendation.** For a system with a markdown journal plus a SQLite ledger plus per-project JSON state and 30 to 100 shifts a day, name the top 5 changes to memory and context that would (a) cut tokens per shift and (b) make shifts compound instead of restarting, each with its effort and expected measurable effect.

## Output format
```
# B4 — Agent memory and context economics: what is real, and what we should change
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30
## 1. Verdict (max 4 sentences)
## 2. Memory systems (table: what it stores | retrieval cost | licence/price | independent evidence | verdict)
## 3. Structured state versus vector memory: the evidence
## 4. Context economics with the real 2026 prices (arithmetic shown)
## 5. Techniques ranked by expected saving for our workload (table plus sources)
## 6. State across amnesiac runs: minimum viable handoff, with the first-2000-tokens template you would use
## 7. Compounding improvement without gradient updates: what actually works
## 8. Top 5 changes for us, with expected measurable effect
## 9. Candidate improvements (numbered MC-1..MC-N; TOPIC / WHAT / WHY / EFFORT S|M|L / EXPECTED GAIN / RISK / SOURCE URL+date / FIRST CONCRETE STEP) — 8 to 12 items
## 10. Not verified, and why
## 11. Sources (URL + date + what it established)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Never invent a benchmark number, a price or a latency. Distinguish vendor claims from independent reproduction and say which is which. If a paper code is not released, say so.
