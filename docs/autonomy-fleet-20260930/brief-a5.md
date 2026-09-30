# BRIEF A5 — Throughput, cost and efficiency: the measured truth at 2026-09-30

You are a mesh subagent auditing THROUGHPUT, COST AND EFFICIENCY of an autonomous-agent system, with arithmetic. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\a5-throughput.md`

## Context
You run on ZABZ-TECH (Windows). Date: 2026-09-30. A Linux authority server is reachable with:

    ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts COMMAND

That server wakes headless DSH agent sessions on ZABZ-TECH while the owner is away. Each woken session, called a release, does one work item from a ledger and writes a proof. Your job: measure the true rate, cost and waste, then compute where the multiplier is. The owner wants far more autonomous productive work per day at a sane cost.

## RULES (violating any invalidates your work)
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files.
- READ-ONLY everywhere. Allowed: reading files with your file tools, and read-only shell commands (cat, ls, head, tail, grep, wc, stat, crontab -l, systemctl list-timers, systemctl status --no-pager, journalctl, `python3 SCRIPT --help`, `python3 -c` with a short read-only program).
- FORBIDDEN because it mutates the system you are auditing: any `wake.py` or `work.py` invocation, anything with `--apply`, systemctl start/stop/restart, crontab -e, any git mutation, rm, mv, sudo, pip or npm install, and any send-message path. To learn what a mutating command would do, READ ITS SOURCE; never run it.
- SQL: SELECT and read-only PRAGMA only, `.timeout 10000`, and never copy a store.
- No messages to any human. No background jobs, no sleep loops, no polling.
- Shell discipline: BATCH many commands into ONE call. Aim to finish in under 45 tool calls.
- Report 8 to 16 KB, dense, with the arithmetic shown.

## Read first
- `C:\Users\ezabz\Code\_autonomy-build-20260928\00-DESIGN-continuous-autonomy.md` (its measurements M1 to M13 are the 2026-09-28 baseline; you report the 2026-09-30 truth and the delta)
- `C:\Users\ezabz\Code\harness-config\docs\autonomy-state-20260928.md`
- FIRST, and quote both in full: `ssh secratary-ts "bash ~/bin/autonomy-status.sh"` and `ssh secratary-ts "python3 ~/bin/wake.py stats --json"`

## Measurements you must produce, each with its command and its arithmetic
1. Releases per day for the last 14 days: successes, failures, dropped. State the trend.
2. USD per day for the last 14 days from the cost records on the authority (look in `~/.sms-inbox/` and anywhere else cost is recorded): total, mean, median and p95 per release. Report the age of the newest record and whether today figure is current. This system has a history of a cap reading a stale number, so verify freshness explicitly.
3. Tokens per release: mean, median, p95, and direction of travel. Split input into cached and uncached, and show output separately, if the records allow it.
4. Duration per release: mean, median, p95, and the share that hit a bound or were killed.
5. VALUE per dollar. State and justify your definition of value — settled attempts carrying a proof, distinct items closed in the ledger, and any release whose outcome was nothing-todo or a duplicate of already-done work. Verify in the code how a proof is defined. Compute what fraction of spend produced a verified change to the world.
6. WASTE, itemised with counts and dollars each: duplicates, re-derivations of the same item, releases that ended with no work available, transport failures that burned tokens yet were recorded as failed, timeouts, retries of already-done work, and capped idle time.
7. UTILISATION: over the last 7 days, what fraction of wall-clock time had zero shifts in flight, and which gate explains each idle stretch? Reconstruct occupancy per 5-minute bucket from the dispatch log timestamps if you can, and give a simple histogram.
8. THE CEILING: with the measured per-release cost and duration, compute the theoretical maximum releases per day under the current design (caps, concurrency, wall-clock bound) and separately under a design with no artificial caps but the measured node capacity. State which resource binds, with evidence.
9. MODEL ECONOMICS: which model serves a woken shift? Find it in the profile and dispatcher on disk, and say whether it is resolved at runtime or hardcoded. Report its price per million tokens if you can find it, and the share of per-release cost that is input, output and cache. Then state what a smarter routing policy would save per 100 releases.
10. WHERE THE MULTIPLIER IS: rank the top 5 levers by expected gain times probability divided by effort, with the arithmetic. Be concrete, for example cost per release falls from X to Y if such-and-such, or releases per day rises from 32 to N if such-and-such.

## Output format
```
# A5 — Throughput, cost and efficiency: the measured truth at 2026-09-30
**Auditor:** mesh subagent on ZABZ-TECH, 2026-09-30
## 1. Verdict (max 3 sentences)
## 2. Headline numbers (table: metric, value, command, timestamp)
## 3. Daily series, 14 days (table)
## 4. Cost decomposition (arithmetic shown)
## 5. Waste, itemised with dollars
## 6. Utilisation and the binding constraint
## 7. The ceiling, computed two ways
## 8. Model economics and routing
## 9. Top 5 levers, ranked with arithmetic
## 10. Findings (numbered; CLAIM / EVIDENCE command+excerpt / SEVERITY / WHY IT MATTERS)
## 11. Candidate improvements (numbered TP-1..TP-N; TOPIC / WHAT / WHY / EFFORT / EXPECTED GAIN / RISK / EVIDENCE / FIRST CONCRETE STEP) — 6 to 10 items
## 12. Not verified, and why
## 13. Sources (paths, line numbers, commands, timestamps)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Every number carries the command that produced it and the time you ran it. Never infer state from a config file — run it, or write "not verified". If the cost records are stale or incomplete, say so and bound what you can still conclude.
