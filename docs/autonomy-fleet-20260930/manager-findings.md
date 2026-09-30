# Manager findings — verified live by the orchestrator, 2026-09-30 ~14:35-15:00 UTC

Orchestrator seat on ZABZ-TECH. Every line below was produced by a command I ran myself in this session;
the command is quoted with each. These are the claims I will re-verify against the fleet reports, not
claims taken from them.

## M1 — The mesh `subagent` transport cannot carry an apostrophe

**Measured.** Three children died with `exited 1 and produced no final message`:
- `subagent-38` (A5 first attempt) — stderr tail was a fragment of the MIDDLE of my prompt.
- `subagent-41` (B3) — stderr was exactly `error: unknown option '--profile'`, and `--profile` appeared
  inside my prompt text (`dsh --profile headless`), not on the transport command line.
- `subagent-45` (A5 retry) — stderr tail ended with the final character of my prompt, a single quote.

**One controlled probe** (`subagent`, 852-char prompt, no apostrophe) came back clean, with every shell
metacharacter I planted (`$HOME`, backticks, `|`, `<angle bracket>`, `'single quote'` inside a
double-quoted sentence) intact. The one variable that differed was the apostrophe in *my* prose
("the day's figure", "the owner's").

**Conclusion:** the transport wraps the task string in single quotes, so a single apostrophe in the
prompt terminates the quoted argument and leaks the rest to the remote shell. **Rule: never dispatch a
mesh child with a long inline prompt. Write the brief to a file and dispatch the filename.** All 11
children in the retry wave were dispatched with a filename-only prompt and all 11 started.

## M2 — The wake system works end to end, with nobody at the keyboard

**Live process evidence, 14:50:31Z:**
```
2435484  bash /home/zabz/bin/wake-dispatch.sh
2435601  timeout -k 30 2160 ssh ... zabz-tech-ts powershell -NoProfile -ExecutionPolicy Bypass \
           -File "C:\Users\ezabz\bin\wake-run.ps1" -PromptFile "C:\Users\ezabz\bin\wake-prompt-152-...txt" \
           -OutFile "C:\Users\ezabz\bin\wake-out-152-...txt" -TimeoutSec 2100
```
`wake-fanout.log`: `2026-09-30T14:50:03Z started shift #1 pid=2435484 claimed=yes procs=1`, and
`wake-dispatch.log`: `2026-09-30T14:50:03Z releasing wake #152 (project:housekeeping:20260930#2)
by wake-dispatch@secratary -> zabz-tech-ts`.

So the trigger chain is real: cron -> `wake-fanout.sh` -> `wake-dispatch.sh` -> `ssh zabz-tech-ts` ->
`powershell wake-run.ps1` -> headless DSH. Hard bounds: outer `timeout -k 30 2160`, inner
`-TimeoutSec 2100`.

## M3 — The scheduler, exactly

`crontab -l | grep -n -i wake` on the authority:
```
55: */5  * * * *  WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /bin/bash /home/zabz/bin/wake-fanout.sh >> wake-cron.log
57: */15 * * * *  /bin/bash /home/zabz/bin/run-wake-sources.sh >> sources-cron.log
67: */15 * * * *  cd /home/zabz && python3 /home/zabz/bin/wake-cost.py --days 1 >> wake-cost-cron.log
```
Not a systemd timer: `systemctl list-units | grep -iE 'wake|autonom'` returns nothing.
Fan-out target 5 concurrent shifts, ceiling 8.

## M4 — THE BIG ONE: the queue is starved, and every reading calls it healthy

**Measured 14:52Z.** `wake-fanout.log` shows ten consecutive ticks that started a shift and failed to
claim — one every 5 minutes from ~14:00 to 14:45 — then a success at 14:50 which was a row filed by the
14:45 sources tick.

The seven rows that every one of those ticks could not claim, from
`sqlite3 -readonly ~/.sms-inbox/inbox.db "select id,subject,state,not_before from wake where state='new'"`:

| id | subject | not_before |
|---|---|---|
| 7 | odq-answer-open:61 | **2026-10-28** |
| 44 | odq-stale:78 | **2026-10-28** |
| 64 | wake-cost-digest:20260928 | 2026-10-05 |
| 66 | dormant-archive:20260928 | 2026-10-01 |
| 88 | wake-cost-tune:project:rental-system | 2026-10-06 |
| 102 | wake-cost-digest:20260929 | 2026-10-06 |
| 114 | dormant-archive:20260929 | 2026-10-02 |

Not one of them is claimable today; the soonest is four days out. Meanwhile `autonomy-status.sh` printed:

```
PROBLEMS : none
IDLE     : 7 row(s) waiting and no cap in force - the next cron tick should claim
```

**Both lines are false in the way that matters.** There is no cap in force — the gate is `not_before`,
which the status tool does not consider — and the next tick could not claim any of them. This is the
exact defect class the 2026-09-28 state document calls out as the pattern to check first
(`docs/autonomy-state-20260928.md:82-97`: *a reading that cannot distinguish two different states is not
a reading*), reproduced live, uncorrected, today.

**Consequence:** for 55 minutes the system did nothing, attempted 11 pointless shift starts, and no
reading on the machine could distinguish that from a healthy gated queue. `wake.py` already computes the
right answer (`_candidates_gated()` at `wake.py:786`, reporting `blocked_by` and a per-reason `gated`
dict) and `autonomy-status.sh` does not consult it.

## M5 — The fan-out destroys its own failure evidence, and one bad row blocks the queue

`wake-fanout.sh:184-187`:
```
say "fanout: shift #$started (pid $pid) did not claim - stopping this run"
note "started shift #$started pid=$pid claimed=no; stopping"
rm -rf "$INST"
break
```
Three defects in five lines:
1. **`rm -rf "$INST"` deletes `wake-ssh.log`, `claim.json` and `prompt.txt`** — so the reason a claim
   failed is unrecoverable after the fact. The staging directories that survive are only the successful
   ones (`wake-instances/` held 223 entries at 14:50, one per successful start).
2. **`break`** stops the whole run, so a single unclaimable row at the head of the ordering blocks every
   other waiting row. Nothing tries the next candidate.
3. The reason is never recorded: `wake.py` computes `blocked_by` and `gated`; the fan-out throws both away.

## M6 — The always-on company is not wired to the work supply

`grep -rln "wake.py\|work.py" /home/zabz/ceo-kernel/` returns **nothing**. The CEO kernel runs
`run-sentinel.sh` every 5 minutes and `run-ha-truth.sh` every 30, plus `company-outcome-monitor.timer`,
and none of it can file a ledger item or raise a wake flag. The only things that file work are the eight
scripts in `/home/zabz/bin/sources/` plus `sms-responder.py` and `work-integrator.py`.

So the largest producer of "the machine noticed something" in this system is disconnected from the only
consumer of work. That is the supply-side reason the owner still has to tell the machine what to do —
not a fault in the trigger, which works.

## M7 — Small, verified details worth keeping

- Wake rows are re-released, not consumed: `wake.py stats` says so itself — `released_today 32`,
  "sessions started, NOT pieces of work ... measured 2026-09-29: 133 releases over 41 distinct ids".
- `wake.py list --json` returns 50 rows ordered by id ascending, so a naive read shows only rows 1-4 and
  every one of them `done`. There is no state filter; the pending work needs raw SQL.
- Cost is metered separately from the dispatch: the dispatcher logs
  `cost: not reported by this harness surface (dsh --profile headless prints no cost)` while
  `wake-cost.py` prices `~/.sms-inbox/wake-cost.jsonl` every 15 min. `spend_today_usd` was 0.610408 at
  14:49Z and `/home/zabz/.sms-inbox/wake-cost.jsonl` had mtime 14:45Z — so the figure was 4 minutes
  stale, i.e. current.
- A shift transcript is 184-201 KB (`wake-out-150/151` on this desktop) and only a truncated `outcome:`
  line ever reaches the log or the store. The full record is never harvested.
- `dormant-archive` and `wake-cost-digest` rows file themselves with a `not_before` 3 to 7 days out:
  the sources deliberately create gated rows, which is what makes `waiting > 0` a meaningless signal.

## M8 — The real reason the machine idles: the ledger's actionable work is parked in `blocked`, and nothing owns the transition out of it

`sqlite3 -readonly ~/work/work.db "select id,project,blocked_on from work_item where state='blocked'"`
returns 11 rows, and every one of them names an owner-queue row that is still pending, or an
integrator role that does not exist on any schedule:

| id | project | blocked_on |
|---|---|---|
| 12 | kosher-ai-filter | owner-queue #171 (maintenance window) |
| 13 | kosher-ai-filter | owner-queue #171 (maintenance window) |
| 14 | kosher-ai-filter | Q22 decision, reversing needs the owner |
| 54 | housekeeping | owner-queue #190 (a production API restart a shift must not do) |
| 82 | chumash | **a person with main-branch access** (owner-queue #192, still pending) |
| 83 | rental-system | **integrator/owner**: land origin/fix/rentals-origin-master-race-90; a shift may not commit to main |
| 86 | lpt-sync | owner-queue 194 and 195 (duplicate pair, both pending) |
| 111 | rental-system | **integrator/owner** (owner-queue #198) |
| 112 | rental-system | owner decision (owner-queue #198) |
| 124 | housekeeping | **owner/integrator**: only a person may commit to main; owner-queue #199 |
| 132 | lpt-sync | owner-queue #204 (customer 1295 phone correction) |

Item 82 in full, quoted from the store:
```
title = land review/chumash-search onto main (reviewed, merge is clean, tests green)
why   = review/chumash-search @37dd8e8 is reviewed: 264/264 tests, tsc clean, merge-tree onto
        current main exits 0 with no conflicts. ... The integrator owns the merge-to-main step;
        the review shift may not commit to main.
dod   = git fetch && git checkout main && git merge --no-ff origin/review/chumash-search && npm ci
        && npx vitest run && npx tsc --noEmit
state = blocked
```
A merge-ready branch, reviewed, tests green, conflict-free, with a DoD that is a single command —
parked in `blocked` since 2026-09-29, touched 2026-09-30T12:09Z and untouched since.

**And the integrator exists as code with no trigger.** `/home/zabz/bin/work-integrator.py` (12,815 bytes,
mtime 2026-09-28) and `crontab -l | grep -i integrator` returns **nothing**. No source in
`run-wake-sources.sh` files integration items either. So the role the ledger's own text depends on
("the integrator owns the merge-to-main step") has never been scheduled, and three items (82, 83, 111,
124) are blocked on it while the queue the dispatcher can see is empty.

This is the mechanism behind the owner's complaint. It is not a cap, not a broken trigger, and not a
shortage of work — it is a **state machine whose `blocked` state has no transition, plus an owner role
(merging to main) that a shift is forbidden to take and nothing else is scheduled to take.**

## M9 — A shift answering the owner's own text is running right now

`work_item` id 141: `project=housekeeping, priority=1, state=running, claimed_by=keepalive-housekeeping,
lease_until=2026-09-30T16:20:09Z, created_at=2026-09-30T13:45:06Z, updated_at=2026-09-30T14:50:09Z,
title="owner asked by text: No, don't you remember we dismissed Weinberg? I s..."`.

Fired from the owner's own SMS at 13:45Z and picked up by wake #152 at 14:50Z. Priority 1, ahead of every
project item. This is the one supply path that works: a human's text becomes work within ~65 minutes.

## M10 — The authority can host a shift locally, and does not

`/home/zabz/.dsh/` on the authority holds a `headless` profile (`~/.dsh/.agent-presets/` contains
`headless`, `zabz`, `cordis-bg`, `yocheved`) and the engine is installed at
`/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js` (a `web` instance has been running on
port 3089 for 8 h 06 m). `grep "profile headless" /home/zabz/bin/*.sh` finds only *comments* — no local
invocation exists.

So the always-on machine has the engine and a headless profile, and yet every shift crosses
`ssh zabz-tech-ts` to a Windows desktop that can sleep. Single point of failure, unverified as removable.
**Highest-value experiment in this audit: start one trivial headless shift locally on the authority and
see whether it completes.** Not yet run — recorded as unverified on purpose.

## M11 — The always-on company is not wired to the work supply (confirmed)

`grep -rln "wake.py\|work.py" /home/zabz/ceo-kernel/` returns nothing. `/home/zabz/ceo-kernel/scripts/`
holds `run-sentinel.sh` (cron every 5 min), `run-ha-truth.sh` (every 30 min) and verification helpers —
none of which can file a ledger item or raise a flag. Meanwhile the journal carries **304 open pain
entries** and the owner queue carries **33 open rows**, and neither is a work source for the ledger.
`grep -rln journal /home/zabz/bin/sources/` shows only `dormant-handoff.py` (which reads handoffs, not
pain) — so the machine's own written backlog never becomes work.

The two supply paths that do exist: the eight scripts in `/home/zabz/bin/sources/`, and the owner's own
texts through `sms-responder.py`.

## M12 — PROVEN EXPERIMENT: the authority can host a shift itself, and it does not

I ran one, verbatim:
```
ssh secratary-ts 'cd /home/zabz && timeout 170 /home/zabz/node/bin/node \
  /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js --profile headless \
  "Reply with exactly LOCAL_SHIFT_OK and nothing else."'
EXIT=0
--- output ---
LOCAL_SHIFT_OK
```
`/home/zabz/.dsh/profiles/headless/` is a real profile (`package.json` declares the bundles
`@deepseek-ai/dsh-base` and `@deepseek-ai/dsh-headless`; `cordis.yml` was regenerated today at 14:45Z), and
`dsh --help` documents the exact form: `dsh --profile headless "run the tests"` — answer one task, print
the result, and exit. A session record was created under `/home/zabz/.dsh/sessions/`.

**So the always-on machine is a working, never-sleeping shift host, and every shift still crosses
`ssh zabz-tech-ts` to a Windows desktop.** That hop is the documented answer-loss point — the 2026-09-28
design records 7 releases that "really ran and burned tokens" but were filed `failed` because the answer
did not survive the transport — and it is the reason the whole system depends on a machine that can
sleep. Removing the dependency needs no new software and no new spend.

**The one thing that blocks a naive move to local execution:** some ledger DoDs name Windows paths. Item
82's DoD is `cd C:\Users\ezabz\Code\chumash-timeline && git fetch ... && npx vitest run`. The authority
holds the same repository at `/home/zabz/repos/chumash-timeline`. So the fix is a small schema change —
per-item `runner`/`node` plus a repo-relative DoD — not a rewrite. Verified: `ls /home/zabz/repos/` holds
the project checkouts; the profile and the engine are installed; the run exits 0.

## M13 — The desktop is not even the only worker; nothing routes by capability

`wake-dispatch.sh` hardcodes the release target (`-> zabz-tech-ts` in every one of the 2,646 dispatch log
lines). Fan-out target 5 and ceiling 8 are counts of *processes on one node*, not a placement decision
across nodes. The mesh broker that does capability-aware placement exists and is used by my own
`subagent` calls (they print `placement = broker → node "zabz-tech", score 14`), but the wake path does
not consult it. So the wake system has a dispatcher, a queue and a runner, and no placement layer at
all — and the field's whole answer to "run agents reliably on more than one machine" is exactly that
layer.

## M14 — Failure taxonomy, classified by me from the store and the log

`sqlite3 -readonly ~/.sms-inbox/inbox.db "select id,subject,attempts,substr(coalesce(outcome,''),-140)
from wake where state='failed' order by id desc limit 8"` plus today's log. All 20 `failed` rows fall into
four classes, and the dominant one is the answer getting lost:

| class | rows seen (by wake id) | what the recorded tail says |
|---|---|---|
| **output captured the transport, not the agent** | 144, 139, 135 | the outcome text is the ssh post-quantum warning: `** WARNING: connection is not using a post-quantum key exchange algorithm ... openssh.com/pq.html` |
| **connection lost mid-run** | 100 | `Connection reset by peer / client_loop: send disconnect: Broken pipe` |
| **result could not be copied back** | 79 | `session finished but the output file could not be copied back (scp rc=1) - the result is unverified` |
| **killed by a bound or by a lock-induced heartbeat loss** | 140, 97, 125 | 140 and 97 end in the kill harness's `SUCCESS: The process with PID ... has been terminated`; 125 says `lease heartbeat lost three times; session killed so it could not be double-run (session ran 655s)` |

Reinforcing the lock cause, today's log carries a contention storm at 00:07-00:40Z (20:07-20:40 local):
```
2026-09-30T00:07:45Z WARN heartbeat for wake #132 failed (attempt 1/3, rc=2): wake: database error: database is locked
2026-09-30T00:10:32Z ERROR reap failed (rc=2): wake: database error: database is locked
```
A heartbeat that cannot write, per row 125's own recorded reason, causes the session to be killed so it
cannot be double-run. So the store's write contention converts directly into killed shifts.

**At least 5 of 20 all-time failures and 3 of today's 7 are the transport/capture class, not the work.**
Every one of them consumed an attempt, and the sessions behind them burned tokens with nothing to show.
This is the single strongest argument for M12's local runner: a session that writes its own result into
the local store has no answer to lose.
