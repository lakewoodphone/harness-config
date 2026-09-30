# BRIEF A3 — The work ledger and the sources that feed it

You are a mesh subagent auditing the WORK LEDGER and its SOURCES. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\a3-ledger-sources.md`

## Context
You run on ZABZ-TECH (Windows). Date: 2026-09-30. The owner runs an autonomous AI company on a Linux server (the authority) reachable with:

    ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts COMMAND

A wake system raises flags and starts headless DSH sessions on ZABZ-TECH with nobody at a keyboard. Each woken session is supposed to claim ONE durable work item from a ledger at `~/work/work.db` and finish it with a proof. You audit the ledger and the sources that fill it.

## RULES (violating any invalidates your work)
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files.
- READ-ONLY everywhere. Allowed: reading files with your file tools, and read-only shell commands (cat, ls, head, tail, grep, wc, stat, crontab -l, systemctl list-timers, systemctl status --no-pager, journalctl, `python3 SCRIPT --help`, `python3 -c` with a short read-only program).
- FORBIDDEN because it mutates the system you are auditing: any `work.py` or `wake.py` invocation (claim, finish, reap, add, attempt, seed, drop, block, flag, release, await, suppress), anything with `--apply`, systemctl start/stop/restart, crontab -e, any git mutation, rm, mv, sudo, pip or npm install, and any send-message path. To learn what a mutating command does, READ ITS SOURCE; never run it.
- SQL: SELECT and read-only PRAGMA only, with `.timeout 10000`, and never copy a store.
- No messages to any human. No background jobs, no sleep loops, no polling.
- Shell discipline: BATCH many commands into ONE call. Aim to finish in under 45 tool calls.
- Report 8 to 16 KB, dense, every number with the command that produced it.

## Read first
- `C:\Users\ezabz\Code\_autonomy-build-20260928\00-DESIGN-continuous-autonomy.md` (the ledger and driver design, plus earlier measurements)
- `C:\Users\ezabz\Code\harness-config\docs\autonomy-state-20260928.md`
- On the authority: `/home/zabz/bin/SIDE-CARS.md`, `/home/zabz/bin/sources/README.md`
- Run FIRST and quote: `ssh secratary-ts "bash ~/bin/autonomy-status.sh"`

## Your scope
1. **THE LEDGER** at `~/work/work.db`: dump the schema, then the live picture — counts by state and by project, priority distribution, age of the oldest todo and blocked item, attempts per item, how many settled attempts carry a proof, and whether any item is duplicated or near-duplicated in substance (the same work under two rows). Name the exact SQL you ran.
2. **THE 11 BLOCKED ITEMS**: what are they blocked by? Is `blocked` doing honest work (an owner decision, an external dependency) or hiding items nobody will ever unblock? How long have they been blocked? Is anything watching the age of blocked items?
3. **THE 6 TODO ITEMS**: what are they, who will run them, and is the queue deep enough to keep shifts busy? Clarify the difference between flags waiting in the wake store and items waiting in the ledger, because the status prints rows waiting and the dispatcher heartbeat separately.
4. **THE SOURCES**: `/home/zabz/bin/run-wake-sources.sh` and everything under `/home/zabz/bin/sources/` (list them with sizes and dates), plus `projects.json`, keepalive, discovery seeding, checkout-health, dormant-handoff, decision-queue sources. For each source: what it files, at what rate, how it dedupes, and whether it can misfire by re-filing the same thing under a different subject. Quantify items filed per day for the last 7 days against items completed.
5. **CAPS AND GATES in force right now**: enumerate every cap, cooldown and gate you can find in code, with its current value, and say which one is binding at this moment. Quote the IDLE line and explain it.
6. **THE REAPER**: does an expired lease get reaped on BOTH stores (wake store and ledger)? Was it ever proven to free anything — look for a proof script and its recorded result. A reaper that has run but never freed anything is untested; say which it is, with evidence.
7. **FAIRNESS AND STARVATION**: which projects are registered, which have items, which get released. Name any project that is enabled but has no items (the status reports one such), and any project whose items never get claimed. Is anything starved by priority or by a per-project cap?
8. **THROUGHPUT TRUTH**: from the ledger, compute items done per day for the last 14 days and the burn-down rate against the filing rate. Is the backlog growing or shrinking? Show the arithmetic.
9. **FILING-TIME TRUTH**: the discipline says an item is a statement about the world at filing time, so an item can go false while it waits. Find evidence of items that are now false, count them, and say whether anything re-validates an item before a shift spends its time on it.

## Output format
```
# A3 — The work ledger and its sources
**Auditor:** mesh subagent on ZABZ-TECH, 2026-09-30
## 1. Verdict (max 3 sentences)
## 2. Live evidence (command, excerpt, timestamp)
## 3. The ledger as it stands (tables, counts, SQL quoted)
## 4. Blocked, todo and stale items, itemised
## 5. Sources: what fills the ledger and at what rate (table)
## 6. Caps and gates in force (table, with the binding one named)
## 7. Findings (numbered; CLAIM / EVIDENCE / SEVERITY / WHY IT MATTERS)
## 8. Top 5 broken things, ranked, with the measurement
## 9. Candidate improvements (numbered LG-1..LG-N; TOPIC / WHAT / WHY / EFFORT / EXPECTED GAIN / RISK / EVIDENCE / FIRST CONCRETE STEP) — 6 to 10 items
## 10. Not verified, and why
## 11. Sources (paths+lines, SQL, timestamps)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Every number carries its command and timestamp. Never infer state from a config file — run it, or write "not verified".
