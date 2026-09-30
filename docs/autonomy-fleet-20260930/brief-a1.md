# BRIEF A1 — Wake dispatch path: end-to-end audit

You are a mesh subagent auditing the DISPATCH PATH of an autonomy system. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\a1-dispatch.md`

## Context
You run on ZABZ-TECH (Windows). Date: 2026-09-30. The owner runs an autonomous AI company on a Linux server (the authority) reachable from here with:

    ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts COMMAND

DSH (DeepSeek Harness) is the agent engine. A wake system lets the server start headless DSH sessions on ZABZ-TECH with nobody at a keyboard. That dispatch path is what you audit: flag to dispatcher to ssh to headless DSH session to result back to row settled.

Known components (verify, do not trust this list): `/home/zabz/bin/wake.py`, `wake-dispatch.sh`, `wake-fanout.sh`, `wake-cost.py`, the wake store `~/.sms-inbox/inbox.db`, `~/.sms-inbox/wake-dispatch.log`, `~/.sms-inbox/wake-cost.jsonl`, and whatever schedules them.

## RULES (violating any invalidates your work)
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere, on any machine. No temp or scratch files.
- READ-ONLY everywhere. Allowed: reading files with your file tools, and read-only shell commands (cat, ls, head, tail, grep, wc, stat, crontab -l, systemctl list-timers, systemctl status --no-pager, journalctl, `python3 SCRIPT --help`, and `python3 -c` with a short read-only program).
- FORBIDDEN because it mutates the system you are auditing: any `wake.py` or `work.py` invocation, anything with `--apply`, systemctl start/stop/restart, crontab -e, any git mutation (no fetch, merge, checkout, commit, push), rm, mv, sudo, pip or npm install, and any send-message path. To learn what a mutating command does, READ ITS SOURCE; never run it.
- SQL: SELECT and read-only PRAGMA only, with `.timeout 10000`, and never copy a store.
- No messages to any human. No background jobs, no sleep loops, no polling.
- Shell discipline: each shell call costs about 700 ms plus an ssh round trip, so BATCH many commands into ONE call. Prefer `--json` output. Aim to finish in under 45 tool calls.
- The report is a claim sheet, not an essay: 8 to 16 KB, dense, every number with the command that produced it.

## Read first
- `C:\Users\ezabz\Code\_autonomy-build-20260928\00-DESIGN-continuous-autonomy.md` (the design of this system, dated 2026-09-28, with baseline measurements M1 to M13)
- `C:\Users\ezabz\Code\harness-config\docs\autonomy-state-20260928.md`
- On the authority: `/home/zabz/bin/SIDE-CARS.md`, `/home/zabz/bin/sources/README.md`
- Run FIRST and quote in full: `ssh secratary-ts "bash ~/bin/autonomy-status.sh"`

## Your scope
The dispatcher, the wake store, the scheduler that triggers it (check the user crontab AND `systemctl list-timers --all` — the dispatch entry was NOT visible in the crontab head, so find the real trigger and name it), the ssh hop to ZABZ-TECH, the `dsh --profile headless` invocation, the answer-return path, leases, retries, timeouts, kill bounds, and the failure taxonomy.

## Questions you must answer, each with a measurement
1. Trace one release end to end from the code as written: which process claims a row, exactly what it runs, how the answer comes back, what settles the row. Quote file:line.
2. Today 32 releases, 7 failed. All-time 20 failed, 16 dropped. CLASSIFY the failures by reading the log and the store. How many are (a) transport lost the answer, (b) the session genuinely errored, (c) timed out or killed by a bound, (d) unknown. Give counts and example wake ids.
3. Is there ANY retry? What happens to a subject after the attempts cap? Does a transport failure that lost the answer consume an attempt and burn a cap, and does it record `failed` even though the work ran?
4. How many shifts can actually run at once, and what enforces it — a count of live PROCESSES or a count of claims? Name the arithmetic and the file:line of the hard ceiling.
5. What is the wall-clock bound on a session, who enforces it, and what happens to work that exceeds it (evidence: any release that hit it)?
6. What happens when ZABZ-TECH is off, asleep, or unreachable mid-run? Is there node failover? Which nodes can host a shift today — verified, not assumed?
7. What is the dispatcher heartbeat, where is it written, who reads it, and what happens if it stops? Is there anything that would tell the owner the wake system is dead?
8. How is the result transported back, how large can it be, and what happens to a result that is lost or truncated?
9. Cost instrumentation: is `spend_today_usd` current and true? Find the timestamp of the file behind it and check whether its own ceiling reads a live number. Verify with arithmetic.

## Output format (write exactly this)
```
# A1 — Wake dispatch path: end-to-end audit
**Auditor:** mesh subagent on ZABZ-TECH, 2026-09-30 · **Scope:** flag to dispatch to session to result to settle
## 1. Verdict (max 3 sentences)
## 2. Live evidence (each line: command, excerpt, timestamp)
## 3. The path as it actually runs (numbered steps, file:line each)
## 4. Failure taxonomy, classified with counts
## 5. Findings (numbered; CLAIM / EVIDENCE command+excerpt / SEVERITY blocker|high|medium|low / WHY IT MATTERS)
## 6. Top 5 broken things, ranked, each with the measurement that shows it
## 7. Candidate improvements (numbered ID-1..ID-N; each: TOPIC / WHAT / WHY / EFFORT S|M|L / EXPECTED GAIN / RISK / EVIDENCE / FIRST CONCRETE STEP) — 6 to 10 items
## 8. Not verified, and why
## 9. Sources (paths+lines, commands, timestamps)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Every number carries the command that produced it and when you ran it. Never infer state from a config file — run it, or write "not verified" and say what blocked you.
