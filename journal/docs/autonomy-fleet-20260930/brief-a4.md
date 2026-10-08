# BRIEF A4 — The owner-facing loop: what reaches him, and what would wake him if this died

You are a mesh subagent auditing the OWNER-FACING HALF of an autonomy system. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\a4-owner-loop.md`

## Context
You run on ZABZ-TECH (Windows). Date: 2026-09-30. The owner (Eliyahu) runs a phone-repair and device-resale business and an autonomous AI company on a Linux server (the authority) reachable with:

    ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts COMMAND

A wake system starts headless DSH agent sessions on ZABZ-TECH while he is asleep or at the shop. He is terse and dislikes being asked things that are not his. A separate owner decision queue exists (`~/bin/owner-queue.py` on the authority; table `owner_decision_queue`) for the one-question-at-a-time channel.

## RULES (violating any invalidates your work)
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files.
- READ-ONLY, and **you must not trigger or send anything**. Absolutely forbidden: running any SMS, email or call sending path (do NOT run `sms-responder.py` at all — read its source instead), any `wake.py` invocation, any `work.py` invocation, any `owner-queue.py` write, anything with `--apply`, systemctl start/stop/restart, crontab -e, any git mutation, rm, mv, sudo, pip or npm install. Do not even run a digest script until you have read its source and confirmed it only prints.
- Allowed: reading files with your file tools, and read-only shell commands (cat, ls, head, tail, grep, wc, stat, crontab -l, systemctl list-timers, journalctl, `python3 SCRIPT --help`, `python3 -c` with a short read-only program), and SQL with SELECT only and `.timeout 10000`.
- No messages to any human. No background jobs, no sleep loops, no polling.
- Shell discipline: BATCH many commands into ONE call. Aim to finish in under 45 tool calls.
- Report 8 to 16 KB, dense, every number with the command that produced it.

## Read first
- `C:\Users\ezabz\Code\_autonomy-build-20260928\C-text-channel-audit.md`
- `C:\Users\ezabz\Code\_autonomy-build-20260928\00-DESIGN-continuous-autonomy.md` (especially section 3.2, the owner side of the loop)
- On the authority: `/home/zabz/bin/SIDE-CARS.md`, `/home/zabz/bin/sources/README.md`
- Run FIRST and quote: `ssh secratary-ts "bash ~/bin/autonomy-status.sh"`

## Your scope
1. **REACH-BACK WHEN WORK LANDS.** When a woken shift finishes a real item, what does the owner see? Trace it in code and find live evidence in the last 14 days: which script, which transport, how many messages, and what they actually said (quote 2 or 3 verbatim). If nothing reaches him, say so plainly with the evidence — a design note claiming a path exists is not evidence.
2. **REACH-BACK WHEN WORK FAILS.** A shift fails, or a subject exhausts its attempts cap and stops forever. Who is told, when, and what does the message say? Quantify: of the failed releases all-time, how many produced any owner-visible signal?
3. **THE ONE-QUESTION CHANNEL.** The table `owner_decision_queue` has 33 open rows. How is a row created, how does the owner answer, and how does an answer get consumed? Is there evidence of a recently answered row actually being acted on (the design mentions a `decision-answer-unconsumed` source)? How long has the oldest open row been open, and how many are really engineering questions that should never have reached him?
4. **MESSAGE VOLUME.** Count messages sent to the owner per day for the last 14 days, by source, from the live stores, read-only. The live business lineage is the Dialpad tables (for example `dialpad_sms_cache`, `dialpad_call_full`) in the app database; the frozen Twilio lineage is `sms_log` and `call_log`. Answer: is the machine message volume rising or falling, and which source dominates?
5. **THE DEATH DETECTOR** — the most important question in this brief. If the authority reboots, or the dispatcher dies, or BOTH heartbeats go stale, how does the owner find out? Is there any watchdog with an independent path (a second machine, an external monitor, a provider-side alert)? What is the mean time to detect a totally dead wake system? Give the evidence: what reads the heartbeats, what threshold, and what happens when it trips. If nothing watches, say so plainly and name the smallest thing that would fix it.
6. **HE DOES NOT REVIEW DOCUMENTS.** Check whether any automated path asks the owner to read a document or confirm a table. If the digest does, quote the offending lines.
7. **SILENCE VERSUS HEALTH.** Find every place where an empty result is presented as health without a liveness check — the known archetype is a responder that prints "0 to decide" because it reads an empty store. List these with file:line.

## Output format
```
# A4 — The owner-facing loop: what reaches Eliyahu, and what would tell him this died
**Auditor:** mesh subagent on ZABZ-TECH, 2026-09-30
## 1. Verdict (max 3 sentences)
## 2. Live evidence (command, excerpt, timestamp)
## 3. What reaches him today (paths, verbatim examples, counts per day)
## 4. What does NOT reach him (failures, caps exhausted, a dead system)
## 5. The death detector: does one exist? MTTA evidence.
## 6. Message volume trend (table)
## 7. Findings (numbered; CLAIM / EVIDENCE / SEVERITY / WHY IT MATTERS)
## 8. Top 5 broken things, ranked
## 9. Candidate improvements (numbered OL-1..OL-N; TOPIC / WHAT / WHY / EFFORT / EXPECTED GAIN / RISK / EVIDENCE / FIRST CONCRETE STEP) — 6 to 10 items
## 10. Not verified, and why
## 11. Sources (paths+lines, SQL, timestamps)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Every number carries its command and timestamp. Never infer state from a config file — run it, or write "not verified".
