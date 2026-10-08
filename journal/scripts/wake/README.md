# The wake system — audit and design

**Audience:** the person operating `secratary` at 3am, and the next engineer who has to
change this without breaking it.

**Status of this document.** It is the W4 deliverable of the `fleet/wake-audit` stream
described in `CONTRACT.md`. It describes the system the contract freezes. It does **not**
change the contract. Everything asserted about the authority was read from the authority
on **2026-09-18 between 03:09Z and 03:16Z**; the exact commands and their output are in
§9 and repeated inline where they matter.

**One thing to know before anything else:** the v0 of this system is **already live on
`secratary` right now**, installed by hand, with its cron line active (measured:
crontab line 51, `*/5 * * * * /bin/bash /home/zabz/bin/wake-dispatch.sh`). It has no
lease, no attempt cap, no cooldown and no reaper in its table, and **a row sat claimed for
nine and a half minutes with no way to tell whether its dispatcher was alive or dead**
(§5, FM-3). Read §3 and §7 before you touch anything.

**And one correction that changes which guard actually protects this machine:** the
`WAKE_MAX_USD_PER_DAY` dollar cap is **inert** (§6, guard 10). `dsh --profile headless`
reports no usage, no tokens and no cost of any kind, so `cost_usd` will be NULL on every
row and the dollar cap can never bind. **The real protection is the release COUNT** —
`WAKE_MAX_PER_DAY`, `WAKE_MAX_PER_SOURCE_PER_HOUR`, dedup, cooldown and the attempt cap.
Treat the count caps as the safety envelope and the dollar cap as a placeholder.

---

## 1. The problem, with evidence

### 1.1 Inbound texts were destroyed, silently, on the path that matters most

The authority runs the business text line. Measured from `journalctl -u secretary-api` on
2026-09-18:

```
journalctl -u secretary-api --no-pager | grep -c 'POST /webhook/twilio/sms.* 500'
11
journalctl -u secretary-api --since "7 days ago" --no-pager | grep -c 'database is locked'
8572
```

The mechanism, recorded in journal entry **H536** and pain entry **P264**:

> `Unhandled error on /webhook/twilio/sms: database is locked` → `HTTP/1.1 500 Internal
> Server Error`. **Twilio does not retry an inbound SMS webhook after a 5xx**, so each one
> was gone at that instant.

From H536, the count and the cost:

> **70 inbound texts on the AI line reached Twilio and never reached the app.** 325 inbound
> total, 15 correspondents. Not spam — this: *"Call me now"*, *"I tried to call you and you
> were just quiet"*, *"Open the front door for Mattis Klein for 10 minutes"*, *"Is this an
> automatic ai generated text or legitimate questions?"*, *"My car is not starting"*.

Two failures stacked: the text was lost, and nobody was told it was lost. It was only
recoverable **because Twilio keeps the messages**. The 5-minute reconciler
(`~/bin/sms-inbox.py`, frozen copy `harness-config/scripts/sms-inbox.py`) now catches
that class within five minutes — but the webhook still returns 500, so there is still a
five-minute hole, and the fix belongs in the app against the **deployed** tree, which is
diverged (owner decision #89).

### 1.2 Nothing on the authority can start a session

That was the whole gap. The authority can *see* — the reconciler runs every 5 minutes, 44
cron jobs are active, 222 tables, 18 agents ticking ~300 times a day — but no process on
it can begin real work. Anything needing judgement or a tool run waited until a human
opened a session. The owner, 2026-09-18:

> *"this might be one of the final pieces in making you actually autonomous … the secretary
> server [becomes] your brain when you are not alive, because no one typed into the GUI …
> and then when it needs to fully reactivate you in a full dsh session, it could run you in
> headless mode back on the desktop … make certain things that the secretary [sees] flags …
> just raise a flag … **make sure it doesn't sit there spawning hundreds of DSH sessions for
> no reason.**"*

### 1.3 The failure this document exists to prevent

Every complaint in the audit docs and the journal has the same shape: **the system kept
running and said nothing**, or **it said something confident and wrong**.

- Journal **L1550**: *"The whole stack kept running and said nothing: every fix must end
  with a number that moved."* — written after a fix written *for* silent failure failed
  silently.
- `04-autonomous-system-postmortem.md` §2.1: **3,246 ticks, zero completions, six
  consecutive days** (8–13 Aug), every one the same cause, discovered six days late.
- `04-autonomous-system-postmortem.md` §2.2: 24 August — *"the system tried twice as hard as
  usual — 597 ticks, its second-busiest day ever — and 84% of them failed. Nobody was
  told."*
- `03-secretary-system-map.md` §5: a **stale copy** of the database on the Yoga *"looks
  exactly like the real one"* — which is how a false outage report was produced.

So a system that can now *spend money by itself* inherits both risks at once. It can
become a session factory (volume without meaning) **or** it can look idle while broken
(silence without meaning). The audit below is two-thirds about telling those apart.

---

## 2. The mechanism

```
anything on secratary            raises a FLAG        (a row in the wake table, with a prompt)
cron on secratary    */5         claims ONE flag      (wake.py claim --by <dispatcher>)
                                 sends the prompt as a FILE to ZABZ-TECH
ZABZ-TECH (Windows, always on)   powershell runs      C:\Users\ezabz\bin\wake-run.ps1
                                 -> npx dsh --profile headless "<prompt>"   (answers, exits)
secratary                        copies the result back, closes the flag row (wake.py finish)
```

### Hosts, files, and who owns them

| piece | host | path | owner |
|---|---|---|---|
| flag store | `secratary` | `~/bin/wake.py`, tables in `~/.sms-inbox/inbox.db` | **W1** (`scripts/wake/wake.py`) |
| dispatcher | `secratary` | `~/bin/wake-dispatch.sh` | **W2** (`scripts/wake/dispatch.sh`) |
| runner | `ZABZ-TECH` | `C:\Users\ezabz\bin\wake-run.ps1` | **W2** (`scripts/wake/runner.ps1`) |
| sources | `secratary` | `~/bin/wake-*.py` | **W3** (`scripts/wake/sources/*.py`) |
| installer, cron, this document | — | `scripts/wake/{deploy.sh,cron.txt,README.md}` | **W4** (this) |
| headless profile | `ZABZ-TECH` | `C:\Users\ezabz\.dsh\profiles\headless\` | DSH |

Verified on 2026-09-18:

```
$ ssh zabz-tech-ts "powershell -NoProfile -Command -" < desk1.ps1
host=ZABZ-TECH user=ezabz
--- C:\Users\ezabz\bin ---
wake-out.txt       125 9/17/2026 11:10:03 PM
wake-prompt.txt     57 9/17/2026 11:09:59 PM
wake-run.ps1      1261 9/17/2026 11:03:07 PM
--- .dsh\profiles ---
headless
mesh
node_modules
web
```

The hop is proven: `~/bin/wake-dispatch.sh` on the authority reached `zabz-tech-ts`,
`wake-run.ps1` ran, a session started, and the row closed. The archive agrees — two
headless sessions on `zabz-tech` landed in `dsh_sessions` with project
`--C-Users-ezabz-AppData-Local-npm-cache-_npx-1e7f6d9597241db0--` and 19 events each.

### The rule that keeps this from becoming a session factory

> **A wake row is only ever filed by something that knows there IS work.**
> **Nothing on a timer may file work. A dispatcher releases; it never invents.**

— `CONTRACT.md` §2. Everything in §6 of this document exists to make that rule hold *under
failure*, not to make it optional.

---

## 3. What is on the authority today (measured baseline)

This is the state the design has to survive, not a hypothetical starting point.

### 3.1 The v0 is installed and its cron line is live

```
$ crontab -l    (52 lines, 44 of them jobs; the release line as it stands now)
51:*/5 * * * * /bin/bash /home/zabz/bin/wake-dispatch.sh >> /home/zabz/.sms-inbox/wake-cron.log 2>&1
```

Two things to notice, both real, and one of them was found and then fixed *by someone
else* while this audit was being written:

1. **A cron job on this box could not run at all, and nobody knew.** At 03:09Z the
   SMS/route line ended with the two literal characters `\` and `r`:

   ```
   $ crontab -l | sed -n '51p' | tail -c 30 | od -c
   ... l o g   2 > & 1   \   r  \n           <- TWO characters: backslash, r. Not a CR byte.
   $ crontab -l | grep -c $'\r$'      -> 0     (no real CR byte anywhere in the crontab)
   $ crontab -l | grep -c '\\r'       -> 1
   ```

   Reproduced on the same host, exactly as cron would run it:

   ```
   $ printf 'echo RAN >> /tmp/t.log 2>&1\\r\n' > t.sh ; bash t.sh ; echo rc=$?
   t.sh: line 1: 1r: ambiguous redirect
   rc=1
   $ ls -la /tmp/t.log        -> 0 bytes, and RAN was never written
   $ sh t.sh ; echo rc=$?     -> "Syntax error: Bad fd number"   rc=2, /tmp/t.log not even created
   ```

   cron runs job lines with `/bin/sh`, so the second result is the one that applied: the
   command never ran. Its log, `~/.sms-inbox/learn.log`, **did not exist** at 03:09Z — while
   the line had been on cron every five minutes. By 03:25Z that line had been repaired by
   another operator, `learn.log` existed, and the `\r` was gone. **The finding is that the
   class of failure is live on this box, not that it is still there** — and it is why
   `deploy.sh` checks for both a real CR byte and the literal `\r` and reports either.
2. Line 51 already runs a dispatcher every five minutes. **Adding the fleet's cron lines
   without removing this one gives two dispatchers** — failure mode FM-2, measured.

The deployed files are byte-identical to the hand-made v0 kept in `_scratch`:

```
$ md5sum /home/zabz/bin/wake-dispatch.sh /home/zabz/bin/wake.py
a63522b9ae1f3002e59ed86af6b8d108  /home/zabz/bin/wake-dispatch.sh
5347578c2d7c6f2927105e71674533f5  /home/zabz/bin/wake.py

$ Get-FileHash -Algorithm MD5 _scratch\wake-dispatch.sh, _scratch\wake.py
A63522B9AE1F3002E59ED86AF6B8D108  _scratch\wake-dispatch.sh
5347578C2D7C6F2927105E71674533F5  _scratch\wake.py
```

### 3.2 The live `wake` table has none of the guard columns

```
$ sqlite3 ~/.sms-inbox/inbox.db "select name from pragma_table_info('wake');"
id subject kind prompt context priority created_at state claimed_by claimed_at finished_at outcome
```

Eleven columns. The contract's DDL (§3) requires `source`, `not_before`, `attempts`,
`max_attempts`, `lease_until`, `cost_usd`, and a `wake_budget` table that does not exist
here either.

**This is a deployment trap, and it is the single most important operational fact in this
document.** The contract's DDL is `CREATE TABLE IF NOT EXISTS`. Against the database that
is already on the authority, that statement is a **no-op** — the new columns will never
appear, every guard that reads them fails, and `wake.py` will look *installed* while being
incapable of leasing, capping or reaping. A naive `scp wake.py ~/bin/` deploy on this box
produces a system that reports success and enforces nothing.

`deploy.sh` detects this by name, and will only fix it behind an explicit
`--migrate-wake-table` flag, which first takes an atomic backup of `inbox.db`.

### 3.3 A row sat claimed, and the store could not tell whether it was alive

```
$ sqlite3 -header ~/.sms-inbox/inbox.db "select id,state,claimed_by,claimed_at,finished_at from wake;"
   (03:15:54Z)
id|state|claimed_by|claimed_at|finished_at
1|done|zapz-tech-desktop|2026-09-18T03:04:38+00:00|2026-09-18T03:04:43+00:00
2|claimed|zapz-tech-desktop|2026-09-18T03:08:28+00:00|
3|done|zapz-tech-desktop|2026-09-18T03:10:01+00:00|2026-09-18T03:10:07+00:00

   (03:25Z, later in the same session)
2|done|...|2026-09-18T03:08:28+00:00|2026-09-18T03:18:05+00:00
```

Row #2 (`await:8482102477:SMb2205782317374ff1c23f42f9ea68716` — Yisroel Weinberg's reply)
was claimed at 03:08:28, was **still claimed seven and a half minutes later**, and finished
`done` at 03:18:05 — 9m37s after the claim. It did complete. **The failure is not that it
was lost; it is that for those 9m37s nothing in the system could tell a live release from a
dead one.** There is no `lease_until`, no heartbeat column, and no reaper in the v0 schema,
so a row whose dispatcher had died at 03:09 would have sat `claimed` forever — and because
`subject` is `UNIQUE`, that reply could never have been filed again either. The row would
have been both lost and un-refilable, with no error anywhere.

That is exactly what guard 7 (lease) and guard 8 (reaper) exist for, and neither can be
implemented on this box until the table is migrated (§3.2).

Row #1 shows the second defect: it is `done` with an **empty outcome** (`  outcome: ` in
`wake-dispatch.log` line 6), because `scp` of the out-file produced nothing and the v0 ran
it with `2>/dev/null`. A "done" that carries no evidence is indistinguishable from a
"done" that never happened — the exact failure `04-autonomous-system-postmortem.md` records
as *hollow completion*.

### 3.4 The layers that feed it

| layer | state | measured |
|---|---|---|
| capture | healthy, every 5 min | `messages`: 1,535 total, **329 inbound**, 1,206 outbound |
| triage | running, `--max-sends 2` per tick | inbound state: `seen` 258, `ignored` 64, `queued` 5, `answered` 1, **`woken` 1** |
| permission ledger | partly seeded | `permissions`: `queue` 8, `never` 4, `auto` 3 |
| awaits | one consumed, ever | `awaited`: `consumed` 1 |
| flags | 3 rows, 1 lost | §3.3 |
| owner queue | 16 pending | `owner_decision_queue`: pending 16, answered 8, resolved 43, dismissed 42 |

The one `woken` message is the Weinberg reply at 03:02:16, and it is the only flag in the
system's history that was filed because a human answered a question we asked. That is what
"filed by something that knows there is work" looks like in practice.

### 3.5 Money, so the cost guard has a scale

```
$ sqlite3 -header secretary.db "select date(created_at) d, count(*) n,
    round(sum(estimated_cost_usd),4) usd from model_usage group by d order by d desc limit 6;"
d|n|usd
2026-09-18|282|1.1342
2026-09-17|2914|10.3149
2026-09-16|3019|11.7318
2026-09-15|5671|25.9158
2026-09-14|3218|10.7593
2026-09-13|2541|8.0764
```

The authority already spends $8–$26 a day on model calls. A wake session must stay small
against that. **But the dollar figure cannot be used as the guard, because a headless
session reports no cost** (§5 FM-7): `dsh --profile headless --help` exposes only `-h`, and
prints no usage, tokens or spend. So the envelope that actually holds is the **count** —
`WAKE_MAX_PER_DAY=8` releases, `WAKE_MAX_PER_SOURCE_PER_HOUR=3`, `WAKE_MAX_ATTEMPTS=2` — and
8 releases a day of a bounded session is the number to reason about, not $3.00. The dollar
column exists in the schema for the day a measurement exists to fill it.

---

## 4. Flag sources, ranked

For each: the signal, how often it actually fires (measured, not estimated), what a session
costs, what the session would **do**, and — most importantly — **what it must never do**.

### Rank 1 — An awaited reply. *Already wired; live; the canonical source.*

| | |
|---|---|
| **Signal** | `sms-responder.py` consumes an `awaited` row (line ~375: `wake_mod.consume_await(conn, from_number)`) and files a wake from the `what` text registered when we sent the message. Subject: `await:<last10>:<MessageSid>`. |
| **Fires** | Measured: **1, ever** (`messages.state='woken'` = 1 row, 2026-09-18T03:02:16). Bounded by how often we ask a specific person for a specific thing and they answer. Single digits per day at worst. |
| **Cost** | Exactly one headless session. |
| **It does** | The instruction that was registered *at send time* — which is the key idea: a reply is a **task**, not a notification. |
| **It must never** | File on *every* inbound (**329 measured** — that is the 5-minute session factory). File when the reply is small talk; `sms-responder.py` files an owner-decision row for that instead, and the two paths must stay separate. Re-file the same `MessageSid` — the SID is in the `subject`, and `subject` is `UNIQUE`, which is the only thing preventing a duplicate. Be filed by the reconcile step. Be filed by a timer of any kind. |

### Rank 2 — A blocking owner-decision row that is genuinely the owner's, and is old.

| | |
|---|---|
| **Signal** | `owner_decision_queue WHERE status='pending' AND blocks IS NOT NULL AND asked_at < now−3d`. |
| **Fires** | Measured: 16 pending, 8 of them `high`, **exactly 1 blocking past 3 days** (queue #20, asked 2026-09-14T15:58). Arrival rate: 11 rows today, 20 on 09-17, 35 on 09-15, 26 on 09-14 — call it ~20/day, so a careless version of this source is 20 sessions/day. |
| **Cost** | One session. |
| **It does** | Re-derive the decision from evidence and either (a) discover it is an engineering question the owner never had to answer — `06-decision-log.md` records **313 questions pending**, and the audit's headline finding is that **383 of 595** "waiting for owner" messages were engineering faults — and close it, or (b) sharpen the recommendation and restate it. This is the highest-value non-SMS source precisely because it retires the largest known backlog. |
| **It must never** | Fire per row: 16 pending is 16 sessions in one tick. Fire on `severity` alone. Fire on rows that are `answered`, `resolved` or `dismissed` (that is 93 of 109 rows). Repeat for the same row — subject must be `odq:<id>`. **Send anything outbound.** A session that wakes to answer a question about money or a customer must come back with a recommendation, not a message. |

### Rank 3 — Carrier-delivered messages absent from our store (the family-chat class).

| | |
|---|---|
| **Signal** | `scripts/family_chat_watchdog.py` (cron `*/30`, `flock`-guarded) prints `PROBLEM: N of N messages the carrier DELIVERED in the last 6h are absent from our database`. Measured: **19 `PROBLEM` lines** in `/home/zabz/family-chat-watchdog.log`; latest is `PROBLEM: 11 of 11 messages the carrier DELIVERED in the last 6h are absent from our database`. |
| **Fires** | When the hub breaks, not continuously — but while broken it re-reports every 30 minutes. |
| **Cost** | One session per incident-day. |
| **It does** | Locate the break (hub bridge vs store vs carrier), restore, and re-verify against the carrier's own record. This is the L1572 / P165 class, and it is exactly the kind of work only a session can do. |
| **It must never** | Fire per missing message (the live incident is **11 at once** — that is 11 sessions for one break). Fire when the count is 0; a healthy source prints `quiet` (`CONTRACT.md` §7 W3). Send anything to the family. Re-open a subject that is already `new` or `claimed`. |

### Rank 4 — `database is locked`, as an incident rather than an event. *Conditional.*

| | |
|---|---|
| **Signal** | A count in a rolling window above the current band: `journalctl -u secretary-api --since "1 hour ago" \| grep -c 'database is locked'`, or `error_log` growth. |
| **Fires** | **Constantly.** Measured: **8,572** matching journal lines in 7 days, against **167** `error_log` rows in 7 days containing the same string — a **51× undercount**, because the `/health` DB probe catches its own timeout and writes nothing. This is not an exception; it is the steady state. |
| **Cost** | One session per incident window, or thousands per day if done wrong. |
| **It does** | Find the lock holder — a long write transaction, a second process on the same file, or WAL checkpoint starvation (P264 lists exactly these three candidates) — and then fix it or file it. |
| **It must never** | Fire per event. Fire on the steady state: because the steady state *is* the incident, a naive version of this source would release a session every five minutes for as long as the bug exists. **This source is only safe once the app-side write path is fixed, or when reduced to at most one flag per 6-hour window with subject `dblock:<YYYY-MM-DD>-<HH/6>`.** It is ranked last among live sources for that reason. |

### Sources that must **NOT** be flags, and why

Each of these is a real, currently-running signal. Each would be a session factory.

| source | measured behaviour | why it must not flag |
|---|---|---|
| `model-failover-watch.py` (cron `*/5`) | 932 parsed lines; `bad=[]` on 794; **non-empty `bad` on 138** — but **131 of those 138 were on 2026-09-16 alone**, i.e. it can fire on every single 5-minute tick for a day (sample: `bad=['deepseek-official/deepseek-v4-pro']`). | A flag per check is up to 288 sessions/day. It also **self-heals** — the line already reports `current=<model>`, which is the whole remedy. If ever adopted: one flag per *incident window*, 6-hour cooldown, never per check. |
| `ha-security-absence` (cron `*/15`) | 4 `RESULT:` lines, **all identical**: `RESULT: FAULT — 7 entity(ies) unavailable or missing.` The log's own footnotes say *"8 restored leftover(s) counted as `stale`, NOT faults"* and *"4 camera(s) classified on state alone — snapshots NOT CHECKED here."* | A chronic fault re-reported every 15 minutes. A session cannot act on it without re-deriving the entire HA inventory, which is work a monitor should do, not a session. Not a flag until the monitor reports *changes*. |
| `owner-attention-digest` (cron `*/30`) | Non-empty by design — it currently reports `3 of 15 checks failing`, `HIGH attention_debt`, `HIGH config_sync`, `HIGH owner_queue`. | 48 sessions/day of "read the digest". It is a *human* surface; see §5 FM-8, where it becomes part of the answer to "quiet or broken". |
| `box-health-check.sh` (daily 05:15) | Its cron line writes to `/var/log/box-health.log`, and on 2026-09-18: `tail: cannot open '/var/log/box-health.log' for reading: No such file or directory`. | The job's output is **already invisible**. A flag on a monitor whose output nobody can read is a second layer of blindness, not a signal. Fix the visibility first. |
| `production-comms-freshness` / `lpt-recon-check` / `comms-refresh` / `website-comms-push` | `production-freshness.log` ends `fresh`; `comms-check.log` ends `ok — 167,968 communications`; `lpt-recon-check` has **20 `rc=1` runs** (1 on 09-15, 6 on 09-16, 12 on 09-17, 1 on 09-18). | These already have their own alerting path and already file to `owner_decision_queue` when they need him (`stripe-key-watch` filed 2 `ANOMALY` rows on 09-18 — **both identical, both in the same second**). A flag would duplicate an existing path and inherit its duplicate-filing bug. |
| `tasks` overdue / `standing_work_orders` | 31 `blocked` tasks, 25,750 `done`, 34 standing work orders. | Any timer that flags overdue tasks *invents* work. The audit's finding is the opposite problem: 595 owner-directed messages, 383 of them engineering faults. |
| `heartbeat.sh` | Writes `~/heartbeat.log` every 60 s (measured mtime 03:15, current). | It is a liveness writer, not a signal. Its **absence** is the signal — and its consumer is a human surface, not a flag (§5 FM-8). |
| anything at all, on a timer | — | `CONTRACT.md` §2. A flag must be filed by something that knows there **is** work. |

---

## 5. Failure modes, each with the guard that answers it

### FM-1 · Runaway session spawning
**How it happens.** A source fires per check instead of per incident. Measured upper bounds
on this box: `model-failover-watch` 131 bad checks on 2026-09-16; `owner_decision_queue`
~20 rows/day; inbound texts 329 all-time, 8,572 `database is locked` lines in 7 days.
**Guards.** §2's rule (only a work-knowing source files) + #3 daily cap (`WAKE_MAX_PER_DAY`,
default **8**) + #4 per-source cap (3 per source per rolling hour) + #5 night gate (low
priority only 13:00–03:00 UTC). With all four, the 09-16 failover stretch of 131 signals
becomes at most 8 sessions, and more likely 1.

### FM-2 · Two dispatchers racing
**How it happens.** Cron overlaps itself. The v0's ssh step is wrapped in `timeout 900`
(15 minutes) inside a `*/5` cron — so a slow session *guarantees* overlap.
**Observed live, 2026-09-18 03:10:41Z:**

```
2661989 bash -c bash /home/zabz/bin/wake-dispatch.sh; python3 /tmp/wake-rows.py
2661990 bash /home/zabz/bin/wake-dispatch.sh
2662010 timeout 900 ssh ... zabz-tech-ts powershell ... -PromptFile C:/Users/ezabz/bin/wake-prompt.txt ...
2662011 ssh ... zabz-tech-ts powershell ... -PromptFile C:/Users/ezabz/bin/wake-prompt.txt ...
```

Two dispatchers were live at once, and **both used the same fixed prompt and out files**
(`C:/Users/ezabz/bin/wake-prompt.txt`, `wake-out.txt`) — so a still-running release has its
prompt overwritten by the next one, and its output read back by the wrong release. That is
silent cross-contamination of two sessions' work.
**Guards.** A single-instance `flock` in `dispatch.sh` (contract §7 W2) **and** per-release
filenames (`wake-prompt-<id>.txt`, `wake-out-<id>.txt`) so that even with the lock broken
two releases cannot read each other's bytes. The daily cap must be counted from
`wake_budget` (guard 3), never by grepping the dispatch log the way the v0 does —
`grep -c "^released $TODAY"` counts lines a failed run may never write.

### FM-3 · A claim left dangling when the dispatcher dies
**How it happens.** The dispatcher claims a row, then dies (ssh drop, box reboot, OOM,
`set -u` on an empty variable) before `finish`.
**Observed live.** Row #2, `claimed` at 03:08:28, **still `claimed` at 03:15:54**, finished
`done` at 03:18:05 — 9m37s in which nothing could distinguish it from a dead run, because
the v0 table has **no `lease_until` column at all** (verified with `pragma_table_info`) and
therefore no reaper can exist. It happened to complete; had the dispatcher died at 03:09
the row would have sat `claimed` forever, and because `subject` is `UNIQUE`
(`await:8482102477:SMb2205782317374ff1c23f42f9ea68716`) **that customer's reply could never
have been filed again either** — lost, un-refilable, and silent.
**Guards.** #7 lease (`claim --lease-seconds`, default 1200; `heartbeat` extends it while
the session runs) + #8 reaper (`reap` returns expired leases to `new`; fail-over-attempted;
expire >30 days) + the W2 requirement that the dispatcher **always** `finish`es in a trap,
even on crash. Plus: `deploy.sh` must migrate the table (§3.2) — otherwise the columns that
make lease and reap possible simply do not exist on this box.

### FM-4 · A session that fails forever
**How it happens.** A prompt that cannot succeed (the Weinberg row is a live example: the
three facts it asks for *do not exist on file*, and the case file explicitly forbids
inventing them) is retried every five minutes forever.
**Guards.** #9 attempt cap (`attempts` increments on every claim; `WAKE_MAX_ATTEMPTS`
default **2**, terminal `failed`) + #8 reaper failing rows over the cap + #1 dedup, because
`subject` being `UNIQUE` is what stops a repeated identical signal from becoming a new row.
A `failed` row with an outcome is information; a `new` row that keeps failing is a leak.

### FM-5 · A prompt that breaks the command line
**How it happens.** The runner builds a command line. `wake-run.ps1` does:

```powershell
$out = & cmd /c "npx dsh --profile headless `"$($prompt -replace '\"','')`" 2>&1"
```

Only the double quotes are stripped. Everything else goes through `cmd.exe`. **Measured on
ZABZ-YOGA 2026-09-18, reproducing that exact construction with `node -e
console.log(JSON.stringify(process.argv.slice(1)))` in place of `npx dsh`:**

```
--- plain             (57 bytes)
["Reply with exactly WAKE_OUTCOME_BACK_OK and nothing else."]

--- multi-line        (56 bytes)
["Business name: Yo's Munchies"]                       <-- line two is GONE

--- trailing-backslash (34 bytes)
["publish to C:\\Users\\ezabz\\lpt-hub\""]               <-- argv gained a stray quote

--- double-percent    (33 bytes)
["report cost ezabz and C:\\Users\\ezabz\\AppData\\Local\\Temp"]   <-- %USERNAME% / %TEMP% expanded
```

Three distinct, silent corruptions:

1. **An embedded newline truncates the prompt at the first line.** This is the *normal*
   shape of a real flag — the Weinberg reply in `responder.log` was
   `"Business name: Yo's Munchies\nBusiness number: 7327017757"`. The session would be
   given half its instruction and no indication that anything was missing.
2. **`%NAME%` is expanded by `cmd.exe` before `dsh` ever sees it.** A prompt mentioning a
   path becomes a different prompt.
3. **A prompt ending in a backslash corrupts the closing quote**, appending a literal `"` to
   the argument.

(One thing that is *not* a hazard, and I checked it rather than assuming: `&` inside the
double quotes is **not** executed — `cmd /c "echo "a & echo b""` prints the whole string
literally. The metacharacter risk here is corruption, not injection.)

**Guards.** The prompt must travel as a **file path**, never as an interpolated string:
the runner should read the prompt itself and hand it to `dsh` in a way that does not
re-enter a shell (stdin, or `dsh`'s own prompt-file argument), with per-release filenames.
This is a **W2 requirement**, and it is stated here with the measurement because the
current v0 runner fails it. The *store* side takes no action — `flag` must exit 0 and must
never rewrite what its caller wrote — so the correct place to catch this is the runner, and
the second-best place is the source, by preferring single-line prompts.

### FM-6 · A monitor that cries wolf
**How it happens.** The source flags on the normal case.
**Measured on this box.** `ha-security-absence` has produced 4 identical
`RESULT: FAULT — 7 entity(ies) unavailable` lines; `model-failover-watch` produced 131
non-empty-bad checks in a single day; the live crontab has 44 jobs, many of which are
"always something to say". A flag wired to any of these converts a noisy log into a
permanent session factory.
**Guards.** `CONTRACT.md` §7 W3 — *"**does nothing when its signal is healthy** … prints
`flagged <subject>` or `quiet`"* — plus guard #4 (3 releases per source per hour) and #2
(cooldown, default 1800 s). Additionally, a new source must ship with a `--dry-run` and
must be run in dry-run against **a full week** of the authority's own logs before its cron
line is added; the *number of times it would have fired last week* is the acceptance test,
and anything above `WAKE_MAX_PER_DAY` is a monitor, not a source.

### FM-7 · Cost runaway — and the guard that cannot fire

**How it happens.** Sessions are not free, and the failure compounds: a bad prompt burns a
session, the retry burns another, and a source that fires per check burns them all day.

**Scale, measured.** The authority already spends $10.31 (09-17), $11.73 (09-16) and $25.92
(09-15) a day in `model_usage.estimated_cost_usd`.

**But the dollar cap in the contract is inert, and this had to be corrected once it was
measured.** `dsh --profile headless --help` on the desktop exposes exactly one option, `-h`.
It prints the final assistant message and streams reasoning to stderr. **It reports no
usage, no token counts and no cost of any kind.** Therefore:

- `wake.py finish --cost-usd X` will have no X to record, and `cost_usd` will be **NULL on
  every row**;
- `WAKE_MAX_USD_PER_DAY` (guard 10) can never bind, because nothing ever accumulates
  against it;
- `stats` will report a day's spend of `0`, which is not "cheap" — it is **unmeasured**.

**An unmeasured resource cannot be capped.** The honest substitute is a cap on the thing
that *can* be counted, set conservatively until spend is measurable:

| what protects the machine | default | why it is the real envelope |
|---|---|---|
| **#3 release count per day** | **8** | the only bound the system can actually observe |
| **#4 releases per source per hour** | **3** | stops one noisy source consuming the day |
| **#9 attempt cap** | **2** | bounds the retry multiplier on a prompt that cannot succeed |
| **#7 lease** | **1200 s** | bounds a hung session instead of re-running it |
| **#6 kill switch** | `WAKE_PAUSED` | the only bound that is instant and total |
| #10 dollar cap | 3.0 | **placeholder.** Inert until spend is measurable (§8, item 10) |

**What would have to change to make the dollar cap real:** the runner must obtain a spend
figure for the session it just ran and pass it to `finish --cost-usd`. `dsh --profile
headless` does not supply one, so this needs either (a) a DSH change that prints token
counts for a headless run, (b) the session itself reporting its own usage as part of its
answer, or (c) attributing the row's window against `model_usage` on the authority, which
is possible today — `model_usage` has `session_id` and `estimated_cost_usd` — but only if
the headless run's `session_id` is captured and carried back with the result. Until one of
those exists, do not describe the dollar cap as enforced. A cap that looks enforced and
never fires is worse than no cap, because it hides the fact that nothing is measuring.

### FM-8 · The one that matters most: quiet because it is broken

A wake system that has released nothing for two days looks **exactly** like a wake system
that had nothing to release. This operation has been burned by reading a live-looking
process as work-happening (`04-autonomous-system-postmortem.md`: *"the system tried twice as
hard as usual … and 84% of them failed. Nobody was told"*), and by reading a stale copy as
production (`03-secretary-system-map.md` §5: *"a stale copy of the database … looks exactly
like the real one"*).

**There are three different ways for this system to be silently dead, and they need three
different checks.**

| what is dead | the tell | the command |
|---|---|---|
| **capture** (nothing is arriving) | no new `messages` rows today even though the line is live | `sqlite3 ~/.sms-inbox/inbox.db "select count(*) from messages where direction='inbound' and date(first_seen)=date('now');"` — **zero on a weekday is not "a quiet day", it is a broken capture**, and `sms-inbox.py gaps` is the check that proves it against Twilio |
| **dispatcher** (flags are filed and nothing releases them) | rows sitting in `new`, and no dispatcher tick in the log | `python3 ~/bin/wake.py list --state new` **and** `tail -1 ~/.sms-inbox/wake-dispatch.log` — the log must gain a line **on every run, including the quiet path**. Cron runs every 5 minutes, so **no new line in 15 minutes means the cron line is gone, the box is down, or the script exits before its first write** |
| **session** (releases happen and always fail) | rows in `failed` with outcomes, or rows that cycle `new`→`claimed`→`new` | `python3 ~/bin/wake.py list --state failed` and `wake.py stats` — a rising `failed` count with a stable `new` count is FM-4, not idleness |

**The required fix for the "dispatcher" row is a design requirement on W2, not a nicety:**
the dispatcher must write one line per run, before it does anything else, in a fixed
machine-readable shape:

```
tick 2026-09-18T03:15:01Z claim=none new=3 claimed=1
tick 2026-09-18T03:20:02Z claim=7     new=2 claimed=1
```

That single line makes the difference between the two states unambiguous, and it is why
`cron.txt` includes a `wake-liveness` line that alerts a **human surface** (not a flag) when
the dispatcher stops writing.

**And the honesty caveat that makes all of this work.** None of these checks may read the
database alone. Measured on 2026-09-18:

```
sqlite3 secretary.db "select count(*) from error_log where error_message like '%locked%' ..."  -> 167 rows / 7 days
journalctl -u secretary-api --since "7 days ago" | grep -c 'database is locked'                -> 8,572 lines / 7 days
```

A health check written against `error_log` reports a system that is 98% healthier than the
one that exists. **An empty result is a refusal, not health** — and a quiet wake queue is
only evidence of calm if the three checks above each produced a positive reading.

---

## 6. The safety envelope, restated

From `CONTRACT.md` §4. Defaults are env-overridable; the **names are fixed**, and so is the
enforcement point. All ten are required — a guard that cannot be exercised by a test does
not exist.

| # | guard | default | enforced in | what it stops |
|---|---|---|---|---|
| 1 | Dedup — `subject` is `UNIQUE` | — | `wake.py flag` (prints `deduped`) | the same signal becoming two rows, and a retried signal becoming a new row |
| 2 | Cooldown | `WAKE_COOLDOWN_SEC=1800` | `wake.py flag` (sets `not_before`) | a signal that flaps producing a session per flap |
| 3 | Daily cap | `WAKE_MAX_PER_DAY=8` | `wake.py claim` (reads `wake_budget`) | volume runaway; **this is the guard the owner actually asked for, and it is the one that really protects the machine** |
| 4 | Per-source cap | `WAKE_MAX_PER_SOURCE_PER_HOUR=3` | `wake.py claim` | one noisy source consuming the whole day's budget |
| 5 | Night gate | `WAKE_NIGHT_QUIET=1` (low only, 13:00–03:00 UTC) | `wake.py claim` | waking a session at 4am for something that can wait |
| 6 | Kill switch | `WAKE_PAUSE_FILE=~/.sms-inbox/WAKE_PAUSED` | `wake.py flag` + `claim` | everything, immediately. **Never deleted automatically.** |
| 7 | Lease | `WAKE_LEASE_SEC=1200` | `claim --lease-seconds` / `heartbeat` | FM-3 — a dead dispatcher's claim |
| 8 | Reaper | — | `wake.py reap`, called at the **start** of every dispatch run (W2) | expired leases, over-attempted rows, >30-day `new` rows |
| 9 | Attempt cap | `WAKE_MAX_ATTEMPTS=2` | `claim` increments, `reap` fails | FM-4 — a prompt that fails forever |
| 10 | Cost log | `WAKE_MAX_USD_PER_DAY=3.0` | `finish --cost-usd`, `stats`, `claim` | **INERT. `dsh --profile headless` reports no usage, tokens or cost, so `cost_usd` is NULL on every row and this guard can never bind. See FM-7 — the count caps (3, 4, 9) are the real envelope.** |

**Enforcement is in the store, not the dispatcher, and that is deliberate.** Every guard
above is checked inside `wake.py` at `flag` or `claim` time, so a dispatcher bug, a
hand-written cron line, or a source with a loop in it still cannot exceed the budget. Any
guard implemented only in the dispatcher (as the v0's daily cap is — a `grep -c` over the
dispatch log) is not a guard; it is a hope.

**Read the guard list like an operator, not like a designer.** Five of the ten are
counting rules (1, 2, 3, 4, 9), one is a clock (5), one is a manual stop (6), two are
recovery (7, 8), and one does not work yet (10). The counting rules are what stand between
this system and the owner's stated fear — *"hundreds of DSH sessions for no reason"* — and
they are the only ones that hold without a human paying attention.

---

## 7. The runbook

Written so that someone with no memory of this work can operate it. **Tier A** is what works
on `secratary` today; **Tier B** is what works after this fleet is deployed. Where they
differ it is called out, because pretending the frozen CLI is already installed is how you
spend twenty minutes typing a subcommand that does not exist.

Set your shell up once:

```bash
ssh secratary-ts
IN=~/.sms-inbox/inbox.db
W="python3 $HOME/bin/wake.py"
```

### A. See what is queued

```bash
# Tier B (frozen CLI, CONTRACT.md §5):
python3 ~/bin/wake.py list --json
python3 ~/bin/wake.py list --state new
python3 ~/bin/wake.py stats --json       # counts by state, released today, spend today, caps in force

# Tier A (v0 on the box today -- list has no --json, stats has no --json):
python3 ~/bin/wake.py list
python3 ~/bin/wake.py list --state claimed
python3 ~/bin/wake.py stats

# Ground truth, always, whichever tier: read the table directly. Read-only, so it is safe.
sqlite3 -header -column "$IN" \
  "select id,state,priority,substr(subject,1,44) subject,claimed_at,finished_at from wake order by id;"
```

Read the result like this: **`new` rows older than 10 minutes with no dispatcher tick =
the dispatcher is dead (FM-8). `claimed` rows with no lease column = lost rows (FM-3).**

### B. See what is being released right now

```bash
pgrep -af 'wake-dispatch'                       # the dispatcher, if one is running
tail -f ~/.sms-inbox/wake-dispatch.log          # one block per release: === releasing wake #N (subject) ===
tail -40 ~/.sms-inbox/wake-cron.log             # cron's own stdout/stderr for the dispatcher
tail -20 ~/.sms-inbox/wake-dispatch.log | cut -c1-200
```

The release is running on the desktop, so the other end is worth a look:

```bash
ssh zabz-tech-ts "powershell -NoProfile -Command Get-Content C:\Users\ezabz\bin\wake-out.txt -Raw"
ssh zabz-tech-ts "powershell -NoProfile -Command Get-Process node -ErrorAction SilentlyContinue | Select-Object Id,StartTime"
```

### C. Read the log

```bash
grep -nE '^===|^released|^  outcome|^tick|cap reached|failed' ~/.sms-inbox/wake-dispatch.log | cut -c1-200
wc -l ~/.sms-inbox/wake-dispatch.log
```

A `released <date> wake #N exit=<n>` line is a finished release. **`exit=0` with an empty
`  outcome:` is not a success** — row #1 is exactly that, and it is the hollow-completion
failure. Treat an empty outcome as a failure to be investigated.

### D. Pause everything

```bash
# Tier B (frozen CLI). Two verbs, both in CONTRACT.md §5:
python3 ~/bin/wake.py pause          # creates ~/.sms-inbox/WAKE_PAUSED
python3 ~/bin/wake.py resume

# Tier A (today): the v0 wake.py DOES NOT READ the pause file.
#   `wake.py pause` -> "invalid choice: 'pause'"   (verified: v0 has only
#   await/awaits/add/list/claim/finish/stats)
# The only real pause today is to stop the cron line. Do it deliberately:
crontab -l > ~/crontab-backup-$(date -u +%Y%m%dT%H%M%SZ).txt   # ALWAYS back up first
crontab -l | sed 's#^\(\*/5 \* \* \* \* /bin/bash /home/zabz/bin/wake-dispatch.sh.*\)$#\# PAUSED \1#' | crontab -
crontab -l | tail -3
```

Creating `~/.sms-inbox/WAKE_PAUSED` on the Tier A box does nothing — say so out loud to
whoever asked, rather than reporting a pause that is not in force. Restore by
`crontab -l > /tmp/now && crontab ~/crontab-backup-<stamp>.txt` after reading it, or by
editing the line back in `crontab -e`.

### E. Resume

```bash
# Tier B:
python3 ~/bin/wake.py resume
ls -la ~/.sms-inbox/WAKE_PAUSED        # must be gone

# Tier A: either un-comment the line in `crontab -e`, or restore the backup from step D.
ls ~/crontab-backup-*.txt              # pick the one you took, and read it before restoring
crontab -l > ~/crontab-before-resume-$(date -u +%Y%m%dT%H%M%SZ).txt   # so resume is also reversible
crontab ~/crontab-backup-<stamp>.txt
crontab -l | tail -2                   # the wake line must be back, uncommented, without a CR
crontab -l | cat -A | tail -2          # `$` at the end, never `^M$`
```

Then prove it resumed, do not assume it:

```bash
sleep 320; tail -2 ~/.sms-inbox/wake-dispatch.log        # a new tick must appear within ~5 min
```

### F. Cancel a row

**There is no `cancel` verb in the frozen CLI.** `CONTRACT.md` §5 lists `pause | resume` and
nothing for cancellation, and I am not going to invent a verb three other streams are
compiled against. Two options that both work today, in order of preference:

```bash
# 1) Preferred: use a frozen verb and leave a truthful trail. The row ends `done`,
#    the outcome says who did it and why. Nothing is deleted.
python3 ~/bin/wake.py finish <ID> --outcome "cancelled by operator <who> at $(date -u +%FT%TZ): <why>"

# 2) If it must read as cancelled, edit the row directly -- AFTER a backup, because
#    inbox.db is live data (messages, permissions, awaits all live in it).
sqlite3 "$IN" ".backup $HOME/.sms-inbox/inbox.db.bak-$(date -u +%Y%m%dT%H%M%SZ)"
sqlite3 "$IN" "update wake set state='cancelled', finished_at=datetime('now'), \
  outcome='cancelled by operator <who>: <why>' where id=<ID>;"
sqlite3 -header "$IN" "select id,state,outcome from wake where id=<ID>;"
```

**Raise this with W1**: a `cancel` verb is missing from the frozen CLI and the runbook needs
it. Until it exists, do not stall — option 1 is always available.

### G. Inspect one release's outcome

```bash
ID=2
sqlite3 -header -line "$IN" "select * from wake where id=$ID;"        # the row, in full
grep -n -A4 "releasing wake #$ID" ~/.sms-inbox/wake-dispatch.log | cut -c1-200
ssh zabz-tech-ts "powershell -NoProfile -Command Get-Content C:\Users\ezabz\bin\wake-out.txt -Raw"
ls -la ~/.sms-inbox/   # the row's own state, plus everything the run wrote
```

Read the dispatch log for the id, the row for the recorded outcome, and the out-file for
what the session actually said. All three, or you do not know what happened.

### H. Add a new flag source

1. **Write it as a standalone script that prints `flagged <subject>` or `quiet`,** calls the
   frozen CLI, is idempotent, has a `--dry-run`, and **does nothing when its signal is
   healthy** (contract §7 W3). A source that flags on the normal case is the session factory.
2. **Prove its fire rate against a week of real logs before it gets a cron line.**
   ```bash
   # example: how many times would this have fired in the last 7 days?
   /path/to/new-source.py --dry-run --since "7 days ago" | grep -c '^flagged'
   ```
   Anything above `WAKE_MAX_PER_DAY` (8) is a monitor, not a flag source. Reference points
   measured on this box: `model-failover-watch` would have fired **131** times on 09-16
   alone; `owner_decision_queue` grows by **~20 rows/day**.
3. **Put it on cron with its own log and its own `flock`**, using the template in
   `cron.txt`; then watch its first day: `python3 ~/bin/wake.py stats` for releases per
   source, and `list --state failed` for what it produced that could not succeed.

### I. The one command that answers "quiet, or broken?"

```bash
date -u +%FT%TZ
tail -1 ~/heartbeat.log; stat -c '%y %n' ~/heartbeat.log          # the box is alive if < 2 min old
tail -1 ~/.sms-inbox/wake-dispatch.log                             # the dispatcher is alive if < 15 min old
python3 ~/bin/wake.py stats                                        # what the store thinks
sqlite3 "$IN" "select count(*) from messages where direction='inbound' and date(first_seen)=date('now');"
```

Four readings, and each has a different meaning. A **fresh heartbeat with a stale dispatch
tick** is a dead cron line. A **fresh tick with zero `new` rows and zero inbound today** is a
dead capture, not a calm day. **`failed` climbing with `new` flat** is FM-4. And an **all-zero
display from a single source** — a health check that reads only SQL — is a refusal, not
health: measured on this box, `error_log` undercounts `database is locked` by **51×**.

### J. Deploy or upgrade

`deploy.sh` changes nothing unless you say `--apply`. **On `secratary`, the table migration
is not optional** — read §3.2 first.

```bash
# 0. get it there with LF endings (a CRLF shell script fails in ways nobody enjoys)
scp harness-config/scripts/wake/deploy.sh secratary-ts:/tmp/wakeaudit/
ssh secratary-ts 'sed -i "s/\r$//" /tmp/wakeaudit/deploy.sh'

# 1. look. THIS IS READ-ONLY AND IT TELLS YOU MOST OF WHAT YOU NEED.
ssh secratary-ts '/bin/bash /tmp/wakeaudit/deploy.sh --check'
#    reads: which source files exist, the live cron situation, whether the wake table
#    has the six guard columns and wake_budget, whether the desktop hop works

# 2. see exactly what --apply would do
ssh secratary-ts '/bin/bash /tmp/wakeaudit/deploy.sh --dry-run'

# 3. apply. --migrate-wake-table is REQUIRED on this box: it takes an atomic
#    .backup of inbox.db, then adds the six missing columns, additively.
ssh secratary-ts '/bin/bash /tmp/wakeaudit/deploy.sh --apply --migrate-wake-table'
#    it pauses the queue (WAKE_PAUSED) unless you pass --no-pause

# 4. it printed the cron lines and did not install them. Do that by hand (§7 D:
#    back the crontab up first), and REMOVE the v0 wake-dispatch line if it is there.

# 5. prove it, do not assume it
ssh secratary-ts 'sqlite3 ~/.sms-inbox/inbox.db "select name from pragma_table_info(\"wake\");"'
ssh secratary-ts 'ls -la ~/.sms-inbox/WAKE_PAUSED'          # pause is in force
ssh secratary-ts 'python3 ~/bin/wake.py stats'
ssh secratary-ts 'python3 ~/bin/wake.py resume'             # now release
sleep 320; ssh secratary-ts 'tail -3 ~/.sms-inbox/wake-dispatch.log'
```

Running `--apply` twice is safe and is the intended way to confirm a clean state: the second
run prints `Nothing needed changing`. Verified on the authority 2026-09-18 against a copy of
the live database (§9).

---

## 8. What this does NOT do

Honest limits, in the order they are likely to bite.

1. **It does not fix `/webhook/twilio/sms`.** The app still returns 500 on a locked DB, and
   Twilio still does not retry. The reconcile net catches it within five minutes; the
   five-minute hole remains open until the app-side write path is fixed against the
   **deployed** tree (owner decision #89). Nothing in this fleet closes it.
2. **It cannot reach a machine that is off.** `ZABZ-TECH` is the only release target and the
   hop is `ssh zabz-tech-ts`. If the desktop is asleep, the flag waits, and the lease will
   eventually expire and re-offer it. There is no second target and no queueing of sessions.
3. **The frozen CLI has no `cancel` verb** (§7 F). Cancelling a row today means `finish` with
   an explicit outcome, or a direct `UPDATE` after a backup.
4. **It does not install cron and it must not.** `deploy.sh` prints the exact lines and stops.
   Removing the live v0 line 52 is an operator action, and if it is skipped you get two
   dispatchers (FM-2) — measured as already possible today.
5. **It does not make a session more trustworthy than an interactive one.** A headless
   session has the same tools, the same permissions and the same failure modes. It will not
   send an outbound message on its own authority, and a prompt that asks it to should be
   rejected at the source.
6. **A gate cannot fix a bad prompt.** §5 FM-5 shows a multi-line prompt is silently
   truncated by the current runner. The store must not rewrite what its caller wrote (a
   `flag` must never break its caller), so the fix lives in the runner — which is W2's file,
   not this one.
7. **It does not give the sources a heartbeat.** The liveness line covers the *dispatcher*.
   A source whose cron line silently vanished is detectable only by its absence from
   `stats` — which means every new source needs its own "I ran and was quiet" line if you
   care about it.
8. **The 30-day expiry and the six-hour incident windows are design defaults, not measured
   optima.** They are defaults in the contract because nobody has run this long enough to
   know. Watch `stats` for a week before believing them.
9. **This document was written from a single 8-minute observation window** on 2026-09-18
   (03:09Z–03:16Z, with three follow-up readings at 03:25Z). Fire-rate figures are counts
   over whatever the logs on the box held at that moment; §9 says which command produced
   each number, and every one of them should be re-measured before being relied on. **The
   authority was being actively worked on by other streams while this was written** — the
   malformed cron line of §3.1 was repaired and a `~/.sms-inbox/wake-heartbeat` file
   appeared at 03:25Z — so anything marked with a timestamp is a reading, not a state.
10. **The dollar cap does not work and cannot work yet.** `dsh --profile headless` reports no
    usage, tokens or cost, so `cost_usd` is always NULL and `WAKE_MAX_USD_PER_DAY` is inert
    (§5 FM-7, §6 guard 10). The count caps are the real envelope. Making the dollar cap real
    requires a spend figure to reach `finish --cost-usd`, and §5 FM-7 lists the three ways
    that could happen; none of them exists today.
11. **The audit stream owns three files and no more.** A liveness checker
    (`wake-liveness.sh`) and a `cancel` verb are both specified in this document and neither
    is delivered here, because neither is W4's file to write. They are named as gaps rather
    than quietly implemented in someone else's stream.

---

## 9. Evidence index

Every factual claim above, with the command that produced it. Run on `secratary` unless
marked otherwise, 2026-09-18 03:09Z–03:16Z.

| claim | command |
|---|---|
| 8,572 `database is locked` lines / 7 d | `journalctl -u secretary-api --since "7 days ago" --no-pager \| grep -c 'database is locked'` |
| 11 SMS-webhook 500s in the journal | `journalctl -u secretary-api --no-pager \| grep -c 'POST /webhook/twilio/sms.* 500'` |
| 70 inbound texts lost; H536; P264 | `journal.py show H536`, `journal.py show P264` |
| 51× undercount (8,572 vs 167) | above, plus `sqlite3 secretary.db "select count(*) from error_log where error_message like '%locked%' ..."` = 167 |
| the v0 cron line | `crontab -l \| grep -n 'wake-dispatch'` → line 51 |
| the malformed `\r` line at 03:09Z | `crontab -l \| sed -n '51p' \| tail -c 30 \| od -c` → `... 2 > & 1 \ r \n`; `crontab -l \| grep -c $'\r$'` → 0 (no real CR byte); `crontab -l \| grep -c '\\r'` → 1 |
| the consequence, reproduced on the host | `printf 'echo RAN >> /tmp/t.log 2>&1\\r\n' > t.sh; bash t.sh` → `1r: ambiguous redirect`, rc=1, log 0 bytes; `sh t.sh` → `Syntax error: Bad fd number`, rc=2, log not created; `ls ~/.sms-inbox/learn.log` → *No such file or directory* at 03:09Z, 26 bytes at 03:25Z |
| deployed v0 == repo v0 | `md5sum ~/bin/wake-{dispatch.sh,py}` vs `Get-FileHash -Algorithm MD5` locally |
| the `wake` table has 11 columns, no lease | `sqlite3 ~/.sms-inbox/inbox.db "select name from pragma_table_info('wake');"` |
| row #2 claimed, then done 9m37s later | `sqlite3 -header ~/.sms-inbox/inbox.db "select id,state,claimed_by,claimed_at,finished_at from wake;"` at 03:15:54Z (`claimed`) and at 03:25Z (`done`, finished 03:18:05) |
| row #1 `done` with empty outcome | `head -6 ~/.sms-inbox/wake-dispatch.log` |
| two dispatchers live at once | `pgrep -af 'wake-dispatch'` → pids 2661989, 2661990, 2662010, 2662011 (03:10:41Z) |
| 329 inbound / 1,535 messages / state split | `sqlite3 -header ~/.sms-inbox/inbox.db "select state,count(*) from messages where direction='inbound' group by state;"` |
| permissions 8 queue / 4 never / 3 auto | `sqlite3 ~/.sms-inbox/inbox.db "select allow,count(*) from permissions group by allow;"` |
| awaited consumed = 1 | `sqlite3 ~/.sms-inbox/inbox.db "select state,count(*) from awaited group by state;"` |
| the one `woken` reply | `sqlite3 -header ~/.sms-inbox/inbox.db "select sid,from_number,state,reason from messages where state='woken';"` |
| the responder files wakes | `grep -n 'wake' ~/bin/sms-responder.py` (lines 61–66, 373–388) |
| owner queue: 16 pending | `sqlite3 -header secretary.db "select status,count(*) from owner_decision_queue group by status;"` |
| ~20 owner rows/day; 11 today | `sqlite3 -header secretary.db "select date(asked_at),count(*) from owner_decision_queue group by 1 order by 1 desc limit 6;"` |
| queue #20 blocking, 3.5 d | `python3 ~/bin/owner-queue.py next` |
| spend $10.31 / $11.73 / $25.92 per day | `sqlite3 -header secretary.db "select date(created_at),count(*),round(sum(estimated_cost_usd),4) from model_usage group by 1 order by 1 desc limit 6;"` |
| failover watcher: 138 bad, 131 on 09-16 | `grep -cE 'bad=\[[^]]' ~/.dsh-model-watch/cron.log` then `\| cut -c1-10 \| sort \| uniq -c` |
| (correction) the naive pattern over-counts | `grep -c 'bad=\[.'` = 932 also matches the healthy `bad=[]`; `grep -c 'bad=\[\]'` = 794; 794 + 138 = 932 |
| HA: 4 identical FAULTs | `grep 'RESULT:' ~/ha-security-absence/latest.log \| sort \| uniq -c` |
| family chat: 19 PROBLEMs, 11 of 11 missing | `grep -c PROBLEM ~/family-chat-watchdog.log`; `tail -3 ~/family-chat-watchdog.log` |
| lpt-recon: 20 rc=1 | `grep -c 'rc=1' ~/.lpt-recon/check.log` |
| stripe watch: 2 identical ANOMALYs, same second | `grep 'ANOMALY' ~/.lpt-verify/stripe-watch.log` |
| box-health log does not exist | `tail -20 /var/log/box-health.log` → `No such file or directory` |
| heartbeat fresh | `ls -la ~/heartbeat.log` (03:15Z) |
| attention digest: 3 of 15 failing | `head -25 ~/secretary-attention-digest/latest.txt` |
| 222 tables; 44 cron job lines | `sqlite3 secretary.db "select count(*) from sqlite_master where type='table';"`; `crontab -l \| grep -vc '^#'` |
| desktop runner + headless profile present | `ssh zabz-tech-ts "powershell -NoProfile -Command -" < desk1.ps1` |
| prompt truncation / `%VAR%` / trailing backslash | `pwsh -NoProfile -File argv.ps1` (mimics `wake-run.ps1`'s exact command line with `node -e` in place of `npx dsh`); the `&` safety check is in `mimic.ps1` |
| `npx dsh --profile headless` reports no cost | `dsh --profile headless --help` on ZABZ-TECH — one option, `-h`; no usage/token/cost output (measured by the parent agent, stated as such) |
| the installer, end to end, on a copy of the live db | `deploy.sh --apply --migrate-wake-table --no-pause --bin /tmp/wakeaudit/bin --state /tmp/wakeaudit/state --src /tmp/wakeaudit` on secratary → 6 `ALTER TABLE` statements, 7 `CHANGED`, then `columns: ... cost_usd` and `rows preserved: wake=3 messages=1536 permissions=15`; a second `--apply` printed `Nothing needed changing` |
| `bash -n` clean | `bash -n scripts/wake/deploy.sh` → exit 0, no output |

**What I could not verify:** whether the deployed dispatcher's ssh to the desktop is
reachable *at the moment of a real release* under load (I saw it reachable twice, and both
releases in the log took under 10 s); the 131-on-09-16 failover stretch was counted from the
log rather than from `tick_telemetry`; the fire rates for the monitors are counts in their
own log files, so a monitor that fails to write looks quiet; I did not run `wake.py` at all,
so every statement about the frozen CLI's behaviour is read from `CONTRACT.md` §5 and from
the v0 source rather than observed; and the dollar cost of a headless session is not merely
unverified but **unavailable by construction** (FM-7).
