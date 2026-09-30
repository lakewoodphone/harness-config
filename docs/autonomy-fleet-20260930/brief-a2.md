# BRIEF A2 — The shift contract: what a woken session actually is, and how good it is

You are a mesh subagent auditing WHAT A WOKEN SESSION ACTUALLY IS AND DOES. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\a2-shift-contract.md`

## Context
You run on ZABZ-TECH (Windows). Date: 2026-09-30. The owner runs an autonomous AI company on a Linux server (the authority) reachable from here with:

    ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts COMMAND

DSH (DeepSeek Harness) is the agent engine. The server raises a flag, and a dispatcher starts a headless DSH session on ZABZ-TECH — roughly `dsh --profile headless PROMPT`. You audit the CHILD end of that: the prompt the shift receives, the profile, model and tools it gets, what it is told to do, and how it writes its result back.

## RULES (violating any invalidates your work)
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files.
- READ-ONLY everywhere. Allowed: reading files with your file tools, and read-only shell commands (cat, ls, head, tail, grep, wc, stat, crontab -l, systemctl status --no-pager, journalctl, `python3 SCRIPT --help`, `python3 -c` with a short read-only program).
- FORBIDDEN because it mutates the system you are auditing: any `wake.py` or `work.py` invocation, anything with `--apply`, ANY `dsh` invocation with a task (never start a session), systemctl start/stop/restart, crontab -e, any git mutation (no fetch, merge, checkout, commit, push), rm, mv, sudo, pip or npm install, and any send-message path. To learn what a mutating command does, READ ITS SOURCE; never run it.
- SQL: SELECT only, `.timeout 10000`, never copy a store.
- No messages to any human. No background jobs, no sleep loops, no polling.
- Shell discipline: batch many commands into ONE call. Aim to finish in under 45 tool calls.
- Report 8 to 16 KB, dense, every number with the command that produced it.

## Read first
- `C:\Users\ezabz\Code\_autonomy-build-20260928\00-DESIGN-continuous-autonomy.md`
- `C:\Users\ezabz\Code\harness-config\docs\autonomy-state-20260928.md`
- On the authority: `/home/zabz/bin/SIDE-CARS.md`, `/home/zabz/bin/sources/README.md`
- Run FIRST and quote: `ssh secratary-ts "bash ~/bin/autonomy-status.sh"`

## Your scope
1. **THE PROMPT.** Find the exact text a woken session receives (the shift contract or prompt template — grep the wake scripts and `harness-config/scripts/wake/` for it; look for a renderer with a dry-run or print mode that does NOT start a session). Quote the full prompt verbatim in your report — it is the single most important artefact. State its size in characters and tokens. Answer: what does it tell the agent to read, do, prove, write back, and in what order? Does it name a specific item, or tell the agent to go claim one?
2. **THE PROFILE.** What does the headless profile mount on ZABZ-TECH: which model, which tools, which skills, which working directory, which environment variables (confirm the WAKE_SESSION marker), what step or time limit, what permission or sandbox mode? Find the profile definition on disk (for example `C:\Users\ezabz\.dsh\settings.yaml`, `C:\Users\ezabz\.dsh\.agent-presets\`, `C:\Users\ezabz\Code\harness-config\presets\`, `profiles\`). Is the model HARDCODED anywhere in the wake path, or resolved at runtime? A literal model id in a script is a time bomb — quote file:line.
3. **WHAT IT ACTUALLY DID.** Read the per-project state files (`~/.wake-projects/*.json`), the dispatch log outcomes, and the ledger attempts with proofs. Take the 3 most recent non-trivial releases and reconstruct: which item, what it did, what proof it produced, what it left over, and whether the next shift could tell what had happened.
4. **THE HANDOFF.** Does a shift see the previous shift state? Is there a written handoff, or does each shift re-derive the world? Quantify re-derivation if you can.
5. **INTEGRATION.** When a shift pushes a branch, who merges it? Is there an integrator session, an integrator queue item, or nothing? Find live evidence of unmerged shift work (branches pushed by shifts that are not on main). READ-ONLY git: `git log`, `git branch`, `git status`, `git for-each-ref` only.
6. **EFFICIENCY OF THE CHILD.** How many tokens and steps does a typical shift consume, and what in the contract makes it expensive (reading large files, re-reading the ledger, no compaction, a long prompt, huge tool outputs)? Get numbers from the cost records or session logs.

## Output format
```
# A2 — The shift contract: what a woken session is, and how good it is
**Auditor:** mesh subagent on ZABZ-TECH, 2026-09-30
## 1. Verdict (max 3 sentences)
## 2. The prompt, verbatim (fenced block) plus measured size
## 3. The profile as actually mounted (evidence per field)
## 4. Three recent shifts, reconstructed (item, did, proof, leftover, could the next shift continue)
## 5. Findings (numbered; CLAIM / EVIDENCE / SEVERITY / WHY IT MATTERS)
## 6. Top 5 weaknesses in the contract, ranked
## 7. Candidate improvements (numbered SQ-1..SQ-N; TOPIC / WHAT / WHY / EFFORT / EXPECTED GAIN / RISK / EVIDENCE / FIRST CONCRETE STEP) — 6 to 10 items
## 8. Not verified, and why
## 9. Sources (paths+lines, commands, timestamps)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Every number carries its command. Never infer state from a config file — run it, or write "not verified".
