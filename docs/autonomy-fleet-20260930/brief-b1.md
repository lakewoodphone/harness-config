# BRIEF B1 — The 2026 agentic tooling landscape, audited against our stack

You are a mesh research subagent surveying the 2026 landscape of tools for long-horizon autonomous agent work. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\b1-landscape.md`

## Context
Date: 2026-09-30. You run on ZABZ-TECH (Windows). The client is an owner-operated business (phone repair and device resale) whose entire engineering operation is run by an autonomous AI company: a Linux server raises work flags and starts headless agent sessions on a Windows desktop, 24/7, with no human at a keyboard. The agent engine is called DSH (DeepSeek Harness). The client wants to know whether the tooling underneath it is still the right tooling, or whether the field has moved and he is falling behind.

## RULES
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files. No git. No messages to anyone. Do not modify any repository.
- READ-ONLY on every machine. Do not start any agent session. Do not send anything.
- You MAY browse the web. Use your `web_search` and `web_fetch` tools if you have them; otherwise use shell HTTP — on Windows: `Invoke-WebRequest -Uri THE_URL -UseBasicParsing` and read `Content`, or `curl.exe -sL THE_URL`.
- Every claim carries a URL and the date the source was published or last updated. Prefer PRIMARY sources: the project own repository, docs, changelog or pricing page. A blog listicle is a lead, not evidence — chase it to the primary source.
- Precision over volume. You are writing for an expert who will check you. Distinguish shipped-and-usable from announced from hype. Where maturity cannot be verified, write "not verified".
- Aim to finish in under 45 tool calls. Report 10 to 16 KB, dense. No filler, no scene-setting.

## Scope: the last roughly 9 months, 2026-01 to 2026-09-30, by category
For each entry: one line of what it is, who makes it, maturity, licence or price if public, and RELEVANT TO US with a one-clause reason. Then a short "so what" for the categories that matter.

1. **Agent harnesses and coding-agent CLIs, plus their orchestration**: Claude Code (and its subagent, hook and skill model), OpenAI Codex CLI, Gemini CLI, Cursor, Devin, OpenHands, Amp, Factory Droid, Cline and Roo, Goose, Aider, Continue, Zed agent, and anything that shipped in 2026 that is now a default choice. Which of these can run unattended, headless, on a schedule, with a durable record — and which cannot?
2. **Agent frameworks and runtimes**: LangGraph, Mastra, OpenAI Agents SDK and AgentKit, Google ADK, Pydantic AI, smolagents, Strands, Agno, CrewAI, DSPy, plus 2026 entrants. Which are actually used in production for long-running loops?
3. **Durable execution for agents** — the category most likely to matter: Temporal, Restate, Inngest, Trigger.dev, DBOS, Cloudflare Workflows and Durable Objects and Agents SDK, AWS Step Functions and Bedrock AgentCore, Azure Durable Functions, and any 2026 entrant targeting long-running agents with resumption. What does agent durability now mean in practice — checkpointing, human-in-the-loop, exactly-once side effects, replay?
4. **Sandboxes and execution isolation**: E2B, Daytona, Modal, Fly Machines, Vercel Sandbox, Morph, Blaxel, Northflank, gVisor, Firecracker, microVMs, plus 2026 entrants. Cost per agent-hour if published, cold start, whether Python and Node and a browser work.
5. **Memory and state**: Letta (MemGPT), Zep and Graphiti, mem0, cognee, MemOS, Supermemory, LangMem, and any 2026 system with published benchmarks. Which are real versus marketing.
6. **Evals and observability**: Braintrust, LangSmith, Langfuse, Arize Phoenix, W&B Weave, 2026 entrants, and specifically anything that evaluates multi-hour autonomous sessions rather than single calls.
7. **Self-improving and continual-learning agents**: GEPA, AlphaEvolve-style evolutionary search over agent code, Darwin-Godel Machine, SEAL, Voyager-style skill libraries, agent-skills standards, experience replay. Which have reproducible evidence?
8. **SPECIAL TASK — identify "Dots".** The owner said he saw something called Dots and does not know if it is relevant. Search hard: Dots agent tool 2026, Dots AI agents, Dots long-horizon agents, dots.ocr, Dots memory, Dots by any known lab. Report what it actually is (company or lab, product, what it does, pricing, maturity, source URLs with dates) and whether it is (a) irrelevant, (b) a possible tool, or (c) a possible competitor or alternative to what we built. If Dots resolves to several different things, list them and rank by likelihood that the owner meant it.
9. **SPECIAL TASK — identify "Coral".** The same owner referred to his current tools as Firecrawl, Coral and JINA. Search for what Coral is in the agent-tooling space in 2026 (any product named Coral for agents, data or search) and whether it plausibly outperforms the others for our use. Report plainly if you cannot identify it.

## Also answer, in two paragraphs, with citations
- What has MATERIALLY changed in the last 6 to 9 months about running agents unattended for hours at a time — capability, durability, cost?
- What is now table stakes that we might be missing entirely?

## Output format
```
# B1 — The 2026 agentic tooling landscape, audited against our stack
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30
## 1. Verdict (max 4 sentences: are we behind, current or ahead, and where)
## 2. Category-by-category table (name | what | maturity | pricing | relevant? | source+date)
## 3. The entries that actually matter to us (5 to 8, each 3 to 6 lines with sources)
## 4. "Dots" — what it is, and whether it matters
## 5. "Coral" — what it is, and whether it matters
## 6. What changed in 6 to 9 months about unattended agents
## 7. Table stakes we may be missing
## 8. Candidate improvements (numbered LS-1..LS-N; TOPIC / WHAT / WHY / EFFORT S|M|L / EXPECTED GAIN / RISK / SOURCE URL+date / FIRST CONCRETE STEP) — 8 to 12 items
## 9. Not verified, and why
## 10. Sources (URL, publication or update date, what it established)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Do not invent a product, a price, a date or a benchmark. If a search returns nothing verifiable, say exactly that. Anything learned from a listicle rather than a primary source must be labelled as such.
