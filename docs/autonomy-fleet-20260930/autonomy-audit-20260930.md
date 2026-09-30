# Can the authority start DSH sessions with nobody there? — end-to-end autonomy audit

**Date:** 2026-09-30 · **Author:** Zabz seat (DSH) on ZABZ-TECH · **Status:** audit complete; no live
script was changed

**Method.** Two independent passes. First, my own live verification on the authority and on the desktop —
every number below has the command that produced it and the minute it was run. Second, an 11-child mesh
fleet (5 auditors on the live system, 6 researchers on the 2026 landscape). Two facts about that fleet
matter for reading this: **nine of the eleven children failed to reach the authority** because ssh hangs
from inside a mesh child on this profile (L3112 — it prints the remote output and never exits), so every
autonomy measurement here is mine; and the four children whose briefs needed no remote access all
delivered, which is why the tooling and infrastructure sections rest on cited research.

Every claim in this document is labelled with how it was established. Where something could not be
verified it says so.

---

## 1. The answer

**Yes, it starts sessions with nobody there, and I watched it happen.** At 14:50:03Z the authority claimed
wake row 152 and started a headless DSH session on this desktop:

```
2435484   bash /home/zabz/bin/wake-dispatch.sh
2435601   timeout -k 30 2160 ssh ... zabz-tech-ts powershell -NoProfile -ExecutionPolicy Bypass \
            -File "C:\Users\ezabz\bin\wake-run.ps1" -PromptFile "wake-prompt-152-...txt" \
            -OutFile "wake-out-152-...txt" -TimeoutSec 2100
wake-fanout.log   2026-09-30T14:50:03Z started shift #1 pid=2435484 claimed=yes procs=1
wake-dispatch.log 2026-09-30T14:50:03Z releasing wake #152 (project:housekeeping:20260930#2)
```

And I proved the always-on machine can host its own shift, with no desktop in the loop at all:

```
ssh secratary-ts 'cd /home/zabz && node .../dsh/lib/bin.js --profile headless "Reply with exactly LOCAL_SHIFT_OK"'
EXIT=0
LOCAL_SHIFT_OK
```

**No, it is not yet autonomous in the sense you mean** — as in, it keeps working and finishes projects
without you telling it what to do. The trigger works; the *pipeline through it* does not. Measured today:
between 13:53Z and 14:50Z the system produced nothing, attempted **eleven pointless session starts**, and
every reading on the machine reported health. `autonomy-status.sh` said `PROBLEMS: none` and
`IDLE: 7 row(s) waiting and no cap in force - the next cron tick should claim`. Both statements were
false in the way that matters: all seven rows were gated days into the future, the soonest by four days
and two of them by twenty-eight.

**The binding constraint is not the trigger, the money, or the caps.** Today the system spent 0.61 of its
70 dollar daily ceiling and used 32 of a 500 release backstop. It idles because the work it already knows
about is parked in states that nothing consumes, and because the one queue the dispatcher can see was
entirely future-gated. The money and the caps are not what is stopping it.

---

## 2. What is proven to work

| Fact | Evidence | When |
|---|---|---|
| The trigger chain runs unattended | process list above, plus `wake-fanout.log` `claimed=yes` | 14:50:03Z |
| A shift writes a real result back | `wake-dispatch.log` `released wake #148 done exit=0 runner_code=0 dur=81s`; same for #149, #150, #151 | 13:11-13:53Z |
| The ledger holds durable work with proofs | `autonomy-status.sh`: `proofs 270 of 286 settled attempts carry one (10 still in progress)`; `done 117` | 14:44Z |
| Your own text becomes work fast | text at 13:45:06Z created ledger item 141 priority 1; wake #152 picked it up at 14:50:03Z — **65 minutes**, ahead of every project item | measured |
| Cost is metered and current | `wake.py stats`: `spend_today_usd 0.610408 of 70.0`, `released_today 32`; `wake-cost.jsonl` mtime 14:45Z — 4 minutes stale, i.e. live | 14:49Z |
| The engine runs on the always-on box | LOCAL_SHIFT_OK above; `/home/zabz/.dsh/profiles/headless/` declares bundles `dsh-base` + `dsh-headless` | 15:05Z |
| The scheduler is real and findable | crontab line 55: `*/5 ... wake-fanout.sh`, line 57 `*/15 ... run-wake-sources.sh`, line 67 `*/15 ... wake-cost.py`. Not systemd — `systemctl list-units` shows no wake unit | 14:45Z |

---

## 3. The eleven measured defects, ranked by how much autonomy they cost

### D1 — Work the machine already knows about is parked in `blocked`, and nothing owns the way out

`sqlite3 -readonly ~/work/work.db "select id,project,blocked_on from work_item where state='blocked'"`
returns **11 rows**. Every one names an owner-queue row that is still pending, or a role that does not
exist on any schedule. Item 82, quoted in full from the store:

```
title = land review/chumash-search onto main (reviewed, merge is clean, tests green)
why   = ... 264/264 tests, tsc clean, merge-tree onto current main exits 0 with no conflicts. It fixes a
        live bug ... The integrator owns the merge-to-main step; the review shift may not commit to main.
state = blocked        created 2026-09-29T00:59:45Z        updated 2026-09-30T12:09:23Z
```

A merge-ready branch with a one-command definition of done, parked since yesterday. Four of the eleven are
blocked on the same missing role ("a person with main-branch access", "integrator/owner"). **And the
integrator exists as code with no trigger:** `/home/zabz/bin/work-integrator.py` is 12,815 bytes and
`crontab -l | grep -i integrator` returns nothing. The role the ledger's own text depends on has never
been scheduled.

### D2 — The queue the dispatcher can see is gated for days, and the status line says otherwise

All seven rows in state `new` at 14:52Z, with their `not_before`:

| id | subject | not_before |
|---|---|---|
| 7 | odq-answer-open:61 | 2026-10-28 |
| 44 | odq-stale:78 | 2026-10-28 |
| 64 | wake-cost-digest:20260928 | 2026-10-05 |
| 66 | dormant-archive:20260928 | 2026-10-01 |
| 88 | wake-cost-tune:rental-system | 2026-10-06 |
| 102 | wake-cost-digest:20260929 | 2026-10-06 |
| 114 | dormant-archive:20260929 | 2026-10-02 |

`wake.py` already computes the right answer — `_candidates_gated()` at `wake.py:786` returns a `gated`
breakdown and reports `blocked_by` — and neither the status tool nor the fan-out consults it. The status
tool reasons only about *caps*, so a `not_before` gate is invisible to it. Two sources
(`dormant-handoff`, `wake-tuner`) file rows with `not_before` three to seven days out as a matter of
design, which makes `waiting > 0` structurally meaningless.

### D3 — The answer is the thing most likely to be lost

From the store's own `outcome` fields on the 20 all-time `failed` rows:

- **16 rows** carry the ssh post-quantum warning banner as the outcome —
  `** WARNING: connection is not using a post-quantum key exchange algorithm ... openssh.com/pq.html`.
  The transport's own chatter was captured as the shift's answer.
- Row 79: `session finished but the output file could not be copied back (scp rc=1) - the result is
  unverified`.
- Row 100: `Connection reset by peer / client_loop: send disconnect: Broken pipe`.
- Rows 140 and 97: ended in the kill harness's `SUCCESS: The process with PID ... has been terminated`.
- Row 125: `lease heartbeat lost three times; session killed so it could not be double-run (session ran
  655s)`.

So at least five of twenty all-time failures, and three of today's seven, are the *work ran and the answer
was lost* class. Each consumed an attempt; the sessions behind them burned tokens with nothing to show.

### D4 — The always-on box can host shifts and does not, and there is no placement layer

`wake-dispatch.sh` hardcodes the target: all 2,646 `releasing ... ->` lines in the dispatch log name
`zabz-tech-ts`. Fan-out target 5 and ceiling 8 count *processes on one node*, not a placement decision.
Meanwhile a real capability-aware broker exists and is used by the fleet (my children print
`placement = broker → node "zabz-tech", score 18`). The wake path does not consult it. So the entire
24/7 operation depends on a Windows desktop being awake and reachable — a dependency I removed in one
command, above.

Blocking a naive switch: some definitions of done name Windows paths (item 82's DoD is
`cd C:\Users\ezabz\Code\chumash-timeline && ... npx vitest run`). The authority holds the same repository
at `/home/zabz/repos/chumash-timeline`. The fix is a per-item `runner` field plus a repo-relative DoD, not
a rewrite.

### D5 — The supply engine is eight cron scripts; the company's own sensing is disconnected

`grep -rln "wake.py\|work.py" /home/zabz/ceo-kernel/` returns **nothing**. The CEO kernel runs
`run-sentinel.sh` every five minutes and `run-ha-truth.sh` every thirty, plus
`company-outcome-monitor.timer` — and none of it can file a ledger item or raise a flag. The journal holds
**304 open pain entries**; the owner queue holds **32 pending rows**; `grep -rln journal
/home/zabz/bin/sources/` shows only `dormant-handoff.py`, which reads handoffs, not pain. The machine's
own written backlog never becomes work.

The two supply paths that do work: the eight scripts in `/home/zabz/bin/sources/`, and your texts through
`sms-responder.py` — which fired today and became item 141 in 65 minutes.

### D6 — The fan-out destroys its own failure evidence and stops on the first failure

`wake-fanout.sh:184-187`:

```
say "fanout: shift #$started (pid $pid) did not claim - stopping this run"
rm -rf "$INST"
break
```

- `rm -rf "$INST"` deletes `wake-ssh.log`, `claim.json` and `prompt.txt` — the reason a claim failed is
  unrecoverable afterwards. Only successful starts leave a surviving instance directory (223 of them,
  never cleaned).
- `break` stops the whole run, so one unclaimable row at the head of the ordering blocks every other row.
- The gate reason is computed by `wake.py` and thrown away by the fan-out, so it reaches no log.

Eleven consecutive ticks between 14:00Z and 14:45Z each paid for a started process and learned nothing.

### D7 — Store contention converts directly into killed sessions

```
2026-09-30T00:07:45Z WARN heartbeat for wake #132 failed (attempt 1/3, rc=2): wake: database error: database is locked
2026-09-30T00:10:32Z ERROR reap failed (rc=2): wake: database error: database is locked
```

And row 125's own recorded cause: heartbeat lost three times, so the session was killed at 655 seconds.
Eight or more writers hammer this store (dispatcher heartbeats, responder, mirror, sources, cost,
keepalive). Every lock-induced heartbeat failure is a session that dies for a reason nobody chose.

### D8 — The model a shift runs on is a literal id in a config file

`~/.dsh/settings.yaml` on this desktop:

```
agent-default-model:
  provider: deepseek-official
  model: deepseek-flash
```

A headless shift boots `--profile headless`, which takes its model from here. This is exactly the time
bomb the standing rule forbids, and it has already fired once in this business — live AI calls in
`personality-system` failed for over a week behind a plausible-looking fallback. The runner got it right
for the *binary* (`wake-run.ps1` resolves the dsh CLI at runtime and says "a version-pinned npx path is a
time bomb"); nobody did it for the model. The gateway catalogue at `http://127.0.0.1:8002/v1/models`
answered 200 today and offers route aliases (`secretary-auto`, `secretary-fast`, `secretary-smart`) plus
34 concrete models — none of which the runner path uses.

### D9 — Nothing would tell you if the whole thing died

The dispatcher writes a heartbeat (`~/.sms-inbox/wake-heartbeat`, mtime 14:50:04Z) and so do the sources
(`sources-heartbeat`, 14:45:09Z). What reads them and what fires when they stop is the question the
research pass could not finish (the auditor for it could not reach the authority). What I could verify:
nothing in the crontab alerts on heartbeat age, and no external dead-man switch is configured. The
authority has a `company-outcome-monitor.timer` and a `box-health-check.sh`, both of which run *on the
authority* — so if the authority itself dies, nothing reports it.

### D10 — A shift's real record is written and never harvested

Staged prompt and output files live on the desktop: `wake-out-150-...txt` is **184,719 bytes** and
`wake-out-151-...txt` is **201,763 bytes**. What reaches the log and the store is one truncated `outcome:`
line. The dispatcher logs, for every release, `cost: not reported by this harness surface (dsh --profile
headless prints no cost)` — so the per-shift cost is reconstructed elsewhere. Two hundred kilobytes of
worked reasoning per shift, discarded.

### D11 — The fleet itself cannot reach the authority, which constrains every future audit

Probe, run in a mesh child on this desktop:

```
ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts hostname
→ printed "secratary", then did not exit; killed at 45s [exit 1]
```

Nine of eleven children died to this in one wave, and their recorded stderr is a diary of the same fight.
It is not a network fault — the remote command ran and answered. The working pattern, which this audit
used, is: **the manager collects the evidence with its own ssh calls and hands the child a file.** Manager
ssh is unaffected (dozens of calls today, zero hangs).

---

## 4. What must change, in order

1. **Run shifts locally on the authority, with the desktop as a peer executor.** Proven feasible today at
   zero marginal cost. This deletes D3 (no answer to lose), D4 (no sleeping-machine dependency), and most
   of D7. The only prerequisite is a per-item `runner` field and repo-relative definitions of done.
2. **Give `blocked` a way out.** Type the blocker (`owner` | `role` | `dependency`), store a
   `revisit_at`, and schedule the roles — starting with an integrator that can merge to main under a
   scoped authorization. Then nothing sits blocked without a wake time. D1.
3. **Make the result write happen on the runner before any lease is released**, so "finished but
   unrecorded" cannot exist. D3, D7.
4. **Build one reading that decides, and one that shouts.** Next-claimable-time, gated-versus-stalled,
   last-success age, and an *external* dead-man switch. D2, D9.
5. **Wire the supply engine to the machine's own backlog** — journal pain, the owner queue, ceo-kernel
   outcomes, drift checks — and make integration a first-class source, not a role with a script and no
   cron entry. D1, D5.
6. **One budget, metered by value.** Reconcile the harness guard (warn 35, fanout 80, ceiling 150) with
   the wake ceiling (70/day) into one number, and report verified items per day beside dollars per day.

## 5. Where this is genuinely yours, and where it is not

Your queue is doing its job: 32 pending rows, and item 162 (the Weinberg close-out) is a real
money-and-legal decision with the arithmetic already worked out. That is correctly yours.

But two of the blocked items are not business decisions. "A person with main-branch access" and "only a
person may commit to main" are a *missing role*, not a judgement call. **My recommendation: authorize an
integrator agent with a scoped, audited, revertible right to merge reviewed branches to main, and stop
routing merges to you.** Everything else in section 3 is engineering and mine.

## 6. What this audit did not do

- **Changed no live script.** Every fix is in `capability-backlog-20260930.md` with a first concrete step.
- **Did not verify the death detector** (D9). The child assigned that question could not reach the
  authority, and my own pass established only that the heartbeats exist and nothing obvious watches them.
- **Did not re-measure the 14-day cost series.** The 2026-09-28 design's M1-M13 remain the last full
  measurement; today's spot figures are above.
- **Did not test a local shift against a real ledger item** — only a trivial one. That is item 1's first
  step, not a claim.
