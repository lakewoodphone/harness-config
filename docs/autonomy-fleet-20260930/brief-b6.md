# BRIEF B6 — Self-improvement: what actually works, with evidence, and what we should not do

You are a mesh research subagent on HOW AN AGENT SYSTEM GETS BETTER ON ITS OWN. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\b6-self-evolution.md`

## Context
Date: 2026-09-30. You run on ZABZ-TECH (Windows). The client is an autonomous AI company: a Linux server schedules headless agent sessions on a Windows desktop, 24/7, with no human. The owner words: he wants it "evolving yourself, getting better and better, at managing my life and creations". The system already has a markdown journal (one file per entry, kinds: lessons, pain, decisions, wins, handoffs; about 2,800 entries), a SQLite work ledger, per-project state files, and a habit of writing lessons with evidence. What it does NOT have is any mechanism that verifiably turns past failures into better future behaviour, and its history includes 55 improvements that piled up unapplied. Your job is to find what actually works, with evidence, and turn it into concrete proposals.

## RULES
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files. No git mutations. No messages to anyone. READ-ONLY.
- You MAY browse the web with `web_search` and `web_fetch` if you have them; otherwise shell HTTP (`Invoke-WebRequest`, `curl.exe`). Every claim carries a URL and a date. For research claims, cite the paper, say whether code and artefacts were released, and whether results were independently reproduced.
- Aim to finish in under 45 tool calls. Report 10 to 16 KB, dense. No filler, no futurism.

## Scope
1. **Closed-loop self-improvement that has evidence.** Survey and judge: GEPA (reflective prompt evolution), AlphaEvolve and evolutionary code search, Darwin-Godel Machine, SEAL (self-adapting language models), STOP and self-taught optimiser, reflexion and self-refine (including the counter-evidence that they often do not help), Voyager-style skill libraries, agent-skills libraries, experience replay and trajectory distillation for agents, automatic prompt optimisation (DSPy, MIPROv2, OPRO), and any 2026 result where an agent measurably improved ITSELF on a real task. For each: what exactly is optimised, the evidence (benchmark and numbers), the cost to run, and whether it transfers outside its benchmark. Be harsh about replication failures.
2. **The evaluation problem.** Self-improvement is meaningless without a fitness signal. What are the honest options for a business-automation agent: outcome tables (did the item close, did the proof command pass), regression suites built from past incidents, LLM-as-judge and its documented failure modes, human spot checks, and business ground truth such as did the customer pay or did the machine stay up? Find the strongest write-ups on evaluating long-horizon agents (multi-hour, many tools) and on which metrics actually predict usefulness. Cite specifics.
3. **Turning incidents into guardrails.** What is the state of the art in converting past failures into durable, automatically checked constraints — a regression test per incident, a lint rule per mistake, a checklist item per forgotten step, a schema per hand-written field? Find engineering write-ups from teams that do this at scale (SRE postmortem action-item practice, incident-to-test pipelines, policy as code). What mechanism makes it stick rather than pile up?
4. **Why improvement proposals do not get applied, and the fixes.** Find evidence on agent and memory systems that accumulate unapplied improvements: proposal backlog decay, the context cost of reading the backlog, and designs that force application — bounded work in progress, one lesson in and one mechanism changed, automatic change generation from a lesson, expiry of stale proposals, a metric that fails when the backlog grows. Then map it onto a system with a journal, a ledger and a scheduler.
5. **Self-modification safety, proportional to a small business.** What guards keep an agent from making itself worse or from breaking its own tooling? Cite practice on change budgets, canary and rollback for agent configuration changes, evaluating a change against a fixed task set before keeping it, measure whether it helped before keeping it, and keeping a human in the loop only for taste and irreversible actions. Include the failure mode where a self-modification silently disables a safety check.
6. **What a small system can actually afford.** Rank the interventions by evidence strength times expected improvement divided by effort for a system with: a markdown journal, a SQLite ledger, cron and systemd, git repositories, no ML training, no GPU, and 30 to 100 agent sessions a day. Which five would you do first, and what would each look like concretely — a script, a schema, a policy, a metric?
7. **The honest counter-case.** Where does the self-improvement literature fail to transfer to a business-automation setting, and which of these ideas would you explicitly NOT adopt, and why? Cite the failures. This section is as important as the recommendations.

## Output format
```
# B6 — Self-improvement: what actually works, with evidence, and what we should not do
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30
## 1. Verdict (max 4 sentences)
## 2. Closed-loop techniques judged (table: technique | what is optimised | evidence and numbers | cost | transfers? | source)
## 3. The evaluation problem for a business agent (options plus their failure modes, sourced)
## 4. Incident to durable guardrail: mechanisms that stick (sourced)
## 5. Why proposals do not get applied, and the fixes that exist
## 6. Self-modification safety, proportional guards
## 7. Five things to do first, concretely (each: the artefact to create, and the metric that proves it helped)
## 8. What NOT to adopt, and why (the counter-case)
## 9. Candidate improvements (numbered SI-1..SI-N; TOPIC / WHAT / WHY / EFFORT S|M|L / EXPECTED GAIN / RISK / SOURCE URL+date / FIRST CONCRETE STEP) — 8 to 12 items
## 10. Not verified, and why
## 11. Sources (URL + date + what it established)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Do not repeat a paper claim as established if replication is contested — say it is contested and cite the counter-evidence. Never invent a benchmark number. Say when a recommendation is your judgement rather than a sourced finding.
