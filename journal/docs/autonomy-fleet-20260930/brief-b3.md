# BRIEF B3 — Always-on agent infrastructure: what to adopt, what to ignore

You are a mesh research subagent on RELIABLE, ALWAYS-ON INFRASTRUCTURE for autonomous agents. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\b3-infra.md`

## Context
Date: 2026-09-30. You run on ZABZ-TECH (Windows). The client runs a 24/7 autonomous operation: a Linux server (the authority, always on) holds the durable state and a scheduler that starts headless agent sessions over ssh on a Windows desktop and potentially other nodes. Today design is roughly: cron or systemd timers run a bash dispatcher, which runs ssh to a node and invokes the agent engine headless with a prompt, and a result is written back to SQLite. Releases are capped and leased. A killed ssh hop can lose a result. There is no retry or resume, no idempotency guarantee on side effects, and no independent watchdog.

## RULES
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files. No git mutations. No messages to anyone. READ-ONLY on every machine.
- You MAY browse the web with `web_search` and `web_fetch` if you have them; otherwise shell HTTP (`Invoke-WebRequest`, `curl.exe`). Every claim carries a URL and the publication or update date. Prefer primary docs over blog posts.
- Aim to finish in under 45 tool calls. Report 10 to 16 KB, dense. No filler.

## Scope
1. **Durable execution, honestly assessed for our case.** Temporal, Restate, Inngest, Trigger.dev, DBOS, Cloudflare Workflows with Durable Objects and the Agents SDK, AWS Step Functions and Bedrock AgentCore, Azure Durable Functions, Prefect and Dagster as orchestration, and any 2026 product that markets long-running agent workflows with resumption and human-in-the-loop. For each: the programming model in one paragraph, what it guarantees (at-least-once versus exactly-once side effects, replay, versioning of running workflows), self-host cost and operational weight — does it need Postgres, a cluster, dedicated workers? — language support, and whether it fits a single Linux box with SQLite today and a real database tomorrow.
2. **Sandboxed agent execution.** E2B, Daytona, Modal, Fly Machines, Vercel Sandbox, Morph, Blaxel, Northflank, gVisor, Firecracker, plus Docker-based self-hosting. Compare cold start, persistent sessions, snapshot and resume, cost per agent-hour, whether a logged-in browser profile can persist, and whether they work from a home or office LAN on consumer internet. Include the self-hosted options a competent operator could run on one Linux box, with the trade-offs named.
3. **Reliability patterns that transfer regardless of vendor.** Find and cite the strongest engineering write-ups from 2025 and 2026 on: idempotency keys for agent side effects, lease with heartbeat and reaper design, at-least-once delivery with de-duplication, checkpointing an agent conversation and tool state, resumable long-horizon runs, the failure mode where the answer is the thing that gets lost, and cost ceilings that actually bind. Summarise the patterns, not the marketing.
4. **Scheduling.** cron versus systemd timers versus a real queue (Redis or Postgres backed, for example pg-boss, Graphile Worker, Hatchet, Celery, RQ) for headless-session dispatch. What does each buy in observability, retries, concurrency control and dead-lettering? Give a recommendation for our scale (tens of sessions a day growing to hundreds) with a migration path that does not require a rewrite.
5. **Node topology and failover.** Patterns for a small mesh of always-on nodes where a session must run on a machine that has the code and the credentials: capability-based placement, health-gated routing, stuck-node detection, and graceful degradation when the only node is a laptop that sleeps. Cite real systems that do this, but keep the recommendation proportional — do not recommend Kubernetes for one box.
6. **Observability for unattended agents.** What to instrument so the owner can answer "is it working, what did it do, what did it cost" in one read: a trace per session, step-level cost, outcome tables, a dead-man switch. Include the specific tooling for a dead-man switch that fires if the authority itself dies — an external service, not self-hosted — with pricing.
7. **THE QUESTION THAT MATTERS MOST.** Given one Linux box (say 8 to 16 cores, 32 to 64 GB RAM, office internet, no Kubernetes) and a Windows desktop as a worker, name the SMALLEST set of changes that would take the current design from "a dispatcher that can lose an answer" to "a durably queued, retried, resumable, observable system that cannot silently stop". Each change with its effort and its adoption risk. Be concrete and proportional.

## Output format
```
# B3 — Always-on agent infrastructure: what to adopt, what to ignore
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30
## 1. Verdict (max 4 sentences)
## 2. Durable execution compared (table plus when-to-use verdict)
## 3. Sandboxes compared (table plus our pick)
## 4. Reliability patterns worth copying (each with a citation)
## 5. Scheduling: cron versus timers versus a queue, with a recommendation for our scale
## 6. Node topology and failover patterns
## 7. Observability and an external dead-man switch (with price)
## 8. The smallest set of changes to make it un-silently-stoppable (ranked, with effort and risk)
## 9. Candidate improvements (numbered IN-1..IN-N; TOPIC / WHAT / WHY / EFFORT S|M|L / EXPECTED GAIN / RISK / SOURCE URL+date / FIRST CONCRETE STEP) — 8 to 12 items
## 10. Not verified, and why
## 11. Sources (URL + date + what it established)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Never invent a price, a latency or a guarantee. Where a vendor page does not state something (for example exactly-once semantics), write "not stated" rather than assuming. Say when a recommendation is your judgement rather than a sourced fact.
