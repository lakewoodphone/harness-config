# 178 — THE AUTONOMOUS WAKE SYSTEM, AUDITED AND RE-ARMED (2026-10-18)

Owner's brief: *"the autonomous wake system ... goes through that day's sessions and previous day
sessions and finds goals and works on projects and all that must be made way, way better. Read it
all, audit it, orchestrate, fan out."*

**Read this before touching anything in `/root/bin/sources`, `/home/zabz/bin/wake*`, or `work.py`.**

Method: eight read-only audits run as a fleet (release path, work supply, ledger, session capture,
owner channel, self-audit, cost). Every finding below carries the command or `file:line` that
produced it. Three were re-verified by me directly against the live store rather than taken from a
child's report.

---

## INDEX — read this line, then jump

Written across one session, 2026-10-18, rounds 1-23. **If you have 60 seconds:** §1 (the pattern),
§22 (where it stands, what is unverified, the next three actions). **If you are about to change
something:** §4 (the open defects with file:line), then the matching §5-§23 for what has already been
tried and failed — three fixes in here were attempted and abandoned, and their reasons are recorded
so they are not retried.

| § | what |
|---|---|
| 1 | THE ONE PATTERN: a correct mechanism wired to nothing |
| 2 | measured baseline at 01:20Z |
| 3 | fixed and proven in round 1 (5 mechanisms) |
| 4 | OPEN — ranked, with the file to change |
| 5 | the budget answer |
| 6-7 | what could not be verified; round 2 (answer gate, session-sweep, budget tier) |
| 8 | round 3: the integrator was never scheduled |
| 9 | round 4: a standing condition bought a shift every day |
| 10-12 | rounds 5-8: the sweep's own bugs, the lease race, the settled-row guard |
| 13 | round 9: reviving the transport-killed rows, by a rule |
| 14-16 | rounds 10-12: the digest path, `lint-refs`/`due` wired as a report |
| 17-18 | rounds 13-14: my own change made waste; three items I nearly retracted |
| 19-21 | rounds 15-18: suggestions to rows that do not exist; two failed patches |
| 22 | WHERE THIS STANDS — unverified list and the next three actions |
| 23 | round 20: the third attempt that worked, and why the first two failed |

## 1. THE ONE PATTERN
Every serious defect found is the same shape, and it is the estate's oldest failure:

> **A monitor that reports success while measuring nothing (or the wrong thing), where its
> "quiet" output is byte-identical to a healthy one.**

Instances found in one night:

| what | it says | what is true |
|---|---|---|
| `dormant-handoff.py` | `SIGNAL UNREADABLE` in a log line | 241 runs / 241 failures / 0 findings since 2026-10-13. Dead on `Path.home()` + a ref that this estate stopped publishing |
| `decision-queue-stale.py`, `decision-answer-unconsumed.py` | `quiet` | blind their whole life: read a zero-row copy of the DB. 33 pending owner rows, oldest 31 days, 41 answered-but-unconsumed |
| `check-dsh-freshness.py` | `refused: no such table: dsh_sessions` | pointed at a stub DB; exits 2, and nothing consumes exit 2 |
| `done` in the wake store | the shift finished | exit code 0 and a non-empty file. Nothing reads the answer |
| `outcome` column | the shift's verdict | `tail -c 2000` of a 70–130 KB transcript — i.e. the model's chain-of-thought, never the report |
| `SENT` from `owner_attention.send()` | he was told | Twilio *acceptance*. `sms_log` 4276 was still `queued` 35 h later |
| the 70 USD/day ceiling | spend is capped | it reads only `wake-cost.jsonl` (~1 USD/day). Real model spend is **23–39 USD/day**, so the guard covers ~3 % of the bill |

## 2. MEASURED BASELINE (2026-10-18 01:20Z)

```
releases today   : 15 of 150 backstop | spend reported 0.98 of 70 USD
real model spend : 2026-10-13 23.32 | 10-14 34.53 | 10-15 38.60 | 10-16 35.14 | 10-17 33.81 USD
wake states      : done 788, failed 271, cancelled 82, dropped 16, new 4, unverified 7
ledger           : todo 91, blocked 38 (oldest 5d), done 370
blocked classified: a=17 owner decision | b=5 human resource | c=9 shift-ready but FORBIDDEN | d=7 stale
sessions 48h     : 239 ran, 223 with a final message, ~63 ending on a commitment or open question
```
Cost per release is ~0.065–0.098 USD. A 4× increase to 60 releases/day costs about **4 USD/day**.
**Money is not the binding constraint. Startable work and integration are.**

## 3. WHAT WAS FIXED AND PROVEN (this session)

1. **`dormant-handoff.py` — 241 consecutive dead runs.** `/root/bin/sources/` + `/home/zabz/bin/sources/`.
   `_repo()` assumed `~/harness-config` (= `/root/harness-config` under cron, absent); `_newest_handoff()`
   read `origin/master`, which this estate no longer publishes **and whose `origin` fetches from the
   FROZEN OFFICE BOX** — it answered `H3392` while HEAD held `H7017`.
   Now: repo resolved from a candidate list, newest handoff taken as **the max across
   HEAD/journal/main/origin\***, and the ref+repo recorded in the flag's context.
   Also: a failing archive checker no longer discards the handoff finding (it used to raise and take
   the primary signal down with it).
   *Proof:* true quiet now (`0 findings` — newest handoff H7017, ~1 h old); planted condition
   (`DORMANT_HANDOFF_DAYS=0`) → `flagged dormant-handoff:H7017`. Both trees md5 `20806161…`.

2. **`_flag.py app_db()` — the escalation detectors were blind.** Defaulted to
   `~/personal-secretary-mvp/data/secretary.db` = a zero-row stale copy. Now `/root/authority.db`
   when present (same precedent as the `app_unit()` correction in the same file).
   *Proof:* `decision-queue-stale.py` → `flagged odq-stale:78`; `decision-answer-unconsumed.py` →
   `flagged odq-answer-open:61`. First findings in either source's history.

3. **`wake-dispatch.sh` — the prompt copy had no recovery and killed the work item.** Every real
   failure in the preceding 48 h was `prompt transfer … failed (…); no session was started`
   (`scp: Connection closed` under concurrent dispatchers, desktop reachable, 188 GB free). Now two
   attempts with a 3 s backoff, and `scp rc` + stderr carried into the outcome.
   *Proof:* `bash -n` OK; `--dry-run` claims and renders normally.

4. **`wake.py _retryable_reason` — a hop that never started a session burned the item's attempt.**
   `"no session was started"` was in the exclusion list, so the transfer failure consumed an attempt;
   **ten rows reached 2/2 and are permanently dead.** Now a `prompt transfer to ` line returns
   retryable *before* the exclusions, so the attempt is refunded and the row returns in 600 s.
   *Proof:* selftest `11 cases, 0 failed, rc=0`; a recovered hop still returns `None`.

5. **Owner-escalation cadence 30 d → 7 d** (`ODQ_STALE_COOLDOWN_SEC` / `ODQ_ANSWER_COOLDOWN_SEC`
   exported in `/root/bin/run-wake-sources.sh`; both sources already read the env, so this is
   configuration, not code). Rows 7 and 44 had been parked since 2026-09-28 with
   `not_before=2026-10-28`, so a 31-day-old owner row got one lost attempt and a month of silence.
   *Proof:* rows unparked (21 KB JSON backup in `/root/.sms-inbox/`); dispatch log
   `01:37:04 releasing wake #7` / `01:37:06 releasing wake #44`.

Backups: `*.bak-dormantfix-*`, `*.bak-appdb-*`, `wake.py.bak-retry-*`,
`wake-dispatch.sh.bak-scpretry-*`, `run-wake-sources.sh.bak-odqcooldown-*`.

## 4. OPEN — RANKED, WITH THE FILE TO CHANGE

### P0 — the release path cannot tell whether work happened
- **`done` = exit 0 + non-empty file** (`wake-dispatch.sh:1209-1218`). The runner writes the header
  *before* launching, so every started run is non-empty. Require a non-empty ANSWER, then parse it.
  A session that boots, does nothing and exits 0 is recorded `done` today.
- **`outcome` is chain-of-thought** (`RESULT_TEXT=$(bounded "$(tail -c 2000 …)")`, `:1123`): the
  shift report never reaches the store, so `wake.py list` cannot show it. Store the **head of the
  `--- stdout (final answer) ---` section**, and keep the tail separately.
- **`deploy.sh` would REGRESS production.** It installs repo `dispatch.sh` (579 lines) as the live
  `wake-dispatch.sh` (1252 lines) and repo `wake.py` over live (diff 1042 lines, no `unverified`
  state). **Do not run it.** Reconcile by pulling production INTO the repo first, then add
  diff-and-refuse.

### P1 — the owner's own ask: read the day's sessions
- **Nothing maps a session to an obligation.** `dormant-handoff` reads journal handoffs and archive
  freshness only; `continuation.py` exists but its DB holds **0 rows**; no session-end hook exists
  anywhere. Handoffs in the last 48 h on this checkout: **0**, against 239 sessions.
- **Build `session-sweep.py`** as a source in the existing 30-minute loop. It is cheap and proven
  feasible: `dsh_sessions` (8 326 rows) has a real `updated_at`; `dsh_session_events` is indexed on
  `(source_machine, session_id, seq)`, so a per-session tail is an **index search**, not a scan
  (a naive `created_at` scan on that table did not finish in 3 minutes — do not write one).
  Session tails already reach `/root/authority.db` hourly. Extract commitments / open questions /
  `remind me <when>`; file **≤3 wake rows per day**, subject `session-sweep:<session_id>`; for an
  explicit date also insert one `reminders` row (`source_ref=<session_id>`). Never paraphrase —
  quote the tail. Skip any session whose tail already names a written handoff id.
- **Reminders: CORRECTED 2026-10-18 — the audit was wrong and this file said so.** The earlier
  claim here ("reminders exist and are being deleted… 106 deadline reminders died in 30 days,
  including a live 10/20 payment") is **FALSE** and is retracted. What is true, measured directly:
  `lifecycle_sweep.py:161` gives the `owner_message_queue` **notification** a 24 h life (409
  expired, 311 never attempted), and that is *by design* — the durable item lives in `reminders`.
  Verified: `reminders` holds 668 rows, 559 `sent`, **0 past-due pending**, and delivery is
  punctual to the second — reminder 654 (the Adelphi deadline) `sent` 2026-10-16 17:00:09 for a
  17:00 slot; 515 and 516 (the Chase card due 10/20) `sent` 2026-10-15 13:00:17 for 13:00.
  My first check said "no matching reminder row" for 6 samples; that was a **false negative of my
  own** — the notification body is prefixed `⏰ Reminder: ` and my `LIKE` used the truncated
  prefixed text. `LIKE '%Adelphi%'` finds exactly 1 row in `reminders`; `%Pesach%` finds 16.
  The lesson is the estate's own: a child's report is a claim, and a negative from a string match
  is only as good as the string.
  **Still open, and it is a real question rather than a defect:** 554 of 559 delivered reminders go
  to `delivery_channel='dashboard'`, not to his phone. Nothing has measured whether he reads that
  dashboard, so "the reminder was delivered" currently means "a row moved to `sent`".
- **The owner gets 258 characters a day.** `owner_attention.py` builds a 14 964-char digest of 36
  items and texts exactly one. The bash digest that *does* report liveness first
  (`WAKE SYSTEM` section) is **installed nowhere** and its output dir does not exist.
- **Google Calendar is authenticated and empty**; nothing writes a deadline to it.

### P2 — the loop does not close
- **Evolution cannot improve itself**: propose → gate → apply is `CODE_EDIT_AUTO_APPLY=false`
  (`.env:122`), measure is dormant (`evolution_verification` 25 rows, all `proposal_id=0`, newest
  2026-07-04), and **revert does not exist** (`evolution_verifier.py:421` writes `failed` and stops).
- **`pain-checks` closer is muted**: 608 open, 45 FIXED-but-still-open, 434 without any check; the
  closer's subject is count-bucketed and its row is at `attempts 2/2`, so it is suppressed.
- **`wake-cost.py` maps release→session on release id only** (`:527`), ignoring the run token, with
  no time window: 3 of 12 rows today were priced against another release's session.
- **No capability tiers.** `wake_model.lane_for` returns `None` unless the *balance* tier is
  degraded, and the live catalog holds only `deepseek-flash` and `deepseek-v4-pro`, so a degraded
  tier still selects flash. Item 293 burned four flash attempts in 50 minutes, all closed `todo`.
- **9 blocked items are blocked only by the shift contract**, not by reality: it forbids a restart
  or a deploy outright, while `settings/machines/host-posture.tsv` says `secratary-cloud` is
  writable and service state may be changed there *deliberately and recorded*. The contract is
  stricter than the estate rule.
- **17 blocked items need the owner and only 11 have a queue row** — 6 have none; nothing in
  `work.py` writes `owner_decision_queue` (`:1133` is a SELECT only).
- **The repo is not production** (see P0). This is the single biggest hazard to every fix above.

## 5. THE BUDGET ANSWER

He offered a bigger budget. The honest answer: **the wake loop is not what costs money.** Measured
23–39 USD/day of model spend against ~1 USD/day attributed to wakes, and the ceiling that is
supposed to protect him measures only the smaller half. Throughput is capped by (a) startable
ledger items, (b) integration of finished branches, (c) one release target. Four times the releases
costs about 4 USD/day; the money is not the constraint and raising it would buy nothing until the
work supply and the verification of `done` are fixed.

## 6. WHAT I COULD NOT VERIFY
- Whether a wake row's *claimed* work changed anything in the world. Nothing checks a commit, a
  file mtime or a ledger row — `done` is self-attested. This is the defect that makes the rest of
  the numbers hard to trust and it is P0.
- The authority's own session shipping: `check-dsh-freshness.py` reports `secratary-cloud` as
  `stale` only because it has no shipper cursor there. That is "cannot tell", not "gap", and it is
  left unfixed rather than turned into a daily false alarm.
- Journal id spaces disagree across trees (HEAD `H7017`, this laptop's journal `H6889`, sessions
  citing `H6505`): a convergence question, filed not fixed.

---

## 7. ROUND 2 — THREE MORE SHIPPED, ONE OF THEM THE OWNER'S ACTUAL ASK

**6. `done` now requires an ANSWER, and the stored outcome is the answer, not the reasoning.**
`wake-dispatch.sh`. Two changes: `answer_head()` takes the section between the runner's
`--- stdout (final answer) ---` and `--- stderr (provider reasoning) ---` banners, so `outcome`
carries the shift's report (measured on four real transcripts: 2 666–4 084 bytes of report, first
lines like `## Shift report — kosher-ai-filter, item 383 → DONE`) instead of `tail -c 2000` of the
model thinking; and a session that produced no answer is now `unverified` — which refunds the
attempt — instead of `done`.
*Proof:* three cases — header-only run → not present; markers with a whitespace-only section → not
present; a real 56 KB transcript → present. `bash -n` clean, `--dry-run` clean.
**Not yet observed in production:** the first three releases under the gate (rows 1165, 1166, 1175)
were still running when this was written. Read their stored `outcome` before trusting the change —
they started after the install, so they are running the gated code and their outcome is the proof.
The old behaviour is why every downstream number was unverifiable: `done` meant "exit 0 and the
file is non-empty", and the runner writes its header *before* it launches, so every started run
qualified.

**7. `session-sweep.py` — the day's sessions now become work.** New source,
`/root/bin/sources/session-sweep.py`, wired into the existing 30-minute loop. It reads
`/root/authority.db` (`dsh_sessions` bounded by `updated_at`, then ONE index probe per session for
its last `assistant/message`), keeps only the `text` parts of the final answer, and files at most
3 wake rows a day, subject `session-sweep:<session_id>`, quoting the session's closing words
verbatim and telling the session to verify before believing them.
*Proof:* a full pass over 213 sessions in 48 h took **0.23 s / 47 MB**, separated 180 machine
sessions from the rest, and produced 3 candidates — including a maintenance-window question that
had been waiting 47 h and an Audible-cancellation question 28 h old. The first was filed for real:
wake row 1175, claimed and running.
**Never query `dsh_session_events` by `created_at`** — that scan did not finish in 3 minutes and
had to be killed. Enter by session id.

**8. The budget tier was a cliff that cost two thirds of the throughput.** `wake_budget.py:148`.
`tier = "ok" if cap >= cmax else "conserve"` can only be true while the balance is at least
`cmax x runway_days` = 210.00, so the live box sat at `conserve` on 208.49 — three days of funded
runway — which made `wake-fanout.sh` halve its target. Now `conserve` means the balance cannot fund
*half* a normal day (balance below 105.00), and the real guards (the `stop` tier, the
`cap <= balance` invariant) are untouched.
*Proof:* `cap_for_balance` across the boundary — 208.49 `ok` (was `conserve`), 105.00 `ok`,
104.90 `conserve`, 3.00 `conserve` cap 1.00, 2.20 `conserve` (still above the 0.75 stop line).
Live: `wake-fanout.log 01:54:02 start in_flight=1 store=1 procs=1 target=3 max=8` (was
`target=1 max=2`), then two shifts started — **three dispatch processes running where there was
one.**

**Also verified this round:** the two owner escalations released at 01:37 completed — wake #7
`done` in 695 s and its outcome records that it filed and claimed **ledger item 518**. That is the
full chain working: a 31-day-old queue row → escalation → real ledger work.

---

## 8. ROUND 3 — THE INTEGRATION LOOP WAS NEVER SCHEDULED

**9. `work-integrator.py` existed for three weeks and NOTHING REFERENCED IT.** Measured:
`crontab -l | grep -c integrator` = **0**, `grep -c integrator /root/bin/run-wake-sources.sh` = **0**.
Its own docstring names the failure it was written for — *"a woken shift pushes a branch and NOTHING
EVER MERGES IT … a fleet that builds and never integrates produces branches, not progress"* — and
then the tool itself was never wired, so the debt was only ever discovered when a human ran it by
hand. The scale of it: **304 settled attempts in the last 7 days carry a `left_over` naming a merge
or a branch** (`select count(*) from attempt where (left_over like '%merge%' or left_over like
'%branch%') and ended_at > datetime('now','-7 day')` → 304), with left-overs like
`PR #461 must merge and deploy after item 506 is green` and
`Merge of c41420ef into main remains for the integrator`.
Now wired into `run-wake-sources.sh` with its own 300 s block (the 90 s loop would kill a slow
`git fetch` and the kill would read as silence).
*Proof:* the wired run completed in **3.2 s and filed 3 integration items** — 531 and 532
(lpt-website, `origin/integrate/six` and `origin/integrate/clean-seven` into `origin/test`) and 533
(prod-db-sync, `origin/integrate/master-34` into `origin/master`). Todo moved 102 → 106. Those
three branches were invisible to every scheduled process before this.

**10. The three blocked integration items are NOT blocked on the merge rule.** Checked each one:167 blocks on *"the shift contract forbids a shift restarting a production service"*, 31 on *"a
maintenance WINDOW with company-api stopped"*, 333 on *"owner approval of owner-queue row 522"*.
So the merge phase is not the stopper — the restart/window policy is, which is exactly the question
in owner row **547**. One answer unblocks that class: 9 restart-blocked + these 3 integration items.
Nothing needed to be built for it, which is why nothing was.

---

## 9. ROUND 4 — THE MACHINE IS SPENDING ITS SHIFTS ON A STANDING CONDITION

Measured 2026-10-18, from the store rather than from opinion:

```
releases today, by kind      checkout-health 5 (one per project) | project:kosher-ai-filter 4
                             sms-app-gap 1 | session-sweep 1 | odq-stale 1 | odq-answer-open 1 | cfo-backfill 1
items closed today, by project  kosher-ai-filter 5 | housekeeping 5 | prod-db-sync 4 | cfo 1 | lpt-sync 1 | lpt-website 1
lpt-website                  todo 25, closed today 1
last 60 checkout-health verdict lines
                             quiet 26 | declared 43 | suppressed 13 | flagged 14 | unreadable 5
the recurring flag           housekeeping  dirty-old; branch=keepalive/323-pickup-weekly-digest
                             — already recorded as ledger item 149, blocked, priority 6
```

**The defect.** `checkout-health.py` is correct in itself: it only files when `report["reasons"]` is
non-empty, and its stdout says `quiet` otherwise. The waste is in the SUBJECT:
`checkout-health:<project>:<YYYYMMDD>` carries the UTC date, so a **standing** condition becomes a
brand-new subject every day by construction and costs one shift per project per day for ever. Two of
the two post-gate rows I read opened with *"the brief was stale — the tree had moved"* or *"two things
the brief measured were already stale: there was no lock"*, and closed having changed nothing. The
housekeeping `dirty-old` condition on a keepalive branch is exactly item 149, which is already
blocked at p6 as **not shift-completable**. So the loop re-discovers a known-unfinishable state every
day, spends a shift confirming it, and files nothing new.

**The fix, not yet made (deliberately, and it is next).** Two options, in order of preference:
1. **Suppress when it is already known.** Before filing, ask the ledger whether this project already
   has a `blocked` item naming the same reason token (`dirty-old`, a held lock, stranded branches).
   If it does, print `suppressed  known: ledger item <id>` and spend nothing. Additive, keeps the
   daily cap, and fails OPEN if the ledger is unreadable (a guard must not go silent on an I/O error).
2. **Key the subject on the reason, not the date** — `checkout-health:<project>:<reason>` — so the
   same condition dedupes by cooldown while a genuinely new condition still files at once. Cheaper,
   but it changes the documented "one session per project per day" cap to a cooldown, so it needs the
   docstring and `_DECLARED` handling re-read first.

**Why it was not changed in this round:** `checkout-health.py` is 2,100+ lines, it is a working guard,
and the change is a suppression rule — the cheapest way to turn a guard silently off. Doing it at the
end of a long session, from a partial read, is how a green guard becomes a blind one. It gets a fresh
round, with the two failure cases planted (`--selftest` exists at line 1873 and must be extended).

---

## 10. ROUND 5 — MY OWN SENSOR WAS LYING, AND ONE ROW'S REPORT WAS DESTROYED

**11. `session-sweep` reported an age it had not measured.** Wake row 1175 — the first row the sweep
ever filed — came back `done` with this verdict, and it is worth quoting because a shift diagnosed my
code better than I had:

> "NOT OPEN AS QUOTED, and the subject work was already in the ledger. The 'Want me to ... or will
> you?' message is from 2026-10-16T21:15:09Z; **the owner answered it in the same session at turn
> 36** … **ROOT CAUSE OF THE FALSE '27.7 h': session-sweep read the authority copy, whose last row was
> 27.7 h old, while the live file had resumed 31 min before the sweep (mtime 01:23Z) and was still
> growing**"

Two defects, both now fixed in `/root/bin/sources/session-sweep.py`:
- **Freshness.** `dsh_sessions` is a projection pushed hourly, so an age read from it is
  age + ingest lag. The sweep now measures the archive's own lag and only treats a session as quiet
  if its newest archived row is older than the archive's newest row by a margin (`--quiet-margin`,
  default 2 h). Measured live: archive 0.0 h behind, 11 sessions excluded as still-live.
- **Who spoke last.** When the newest event in a session is the owner's, the ball is with the
  assistant and the assistant's closing question is no longer an open commitment. `owner_spoke_last()`
  does this with two index probes; it is exactly what excluded the false positive.
*Proof:* `228 session(s) in 48h, 187 machine, 11 still-live, 1 owner-spoke-last, 1 candidate(s)` —
down from 3 candidates, and the one that cost a shift is gone. The surviving candidate is a CFO
text-cap question 34 h old.

**12. A completed row's report was overwritten by the dispatcher's own lease monitor — cause not yet
established, so not patched.** Timeline, from the log and the store:

```
02:06:57  row 1175 reads state=done, finished_at=02:06:57, with the full report above
02:07:46  ERROR lease for wake #1175 not renewed … the store reports the row is no longer claimed by us
02:07:47  released … failed exit=124 dur=1123s ; state=failed, attempts=0, outcome OVERWRITTEN
```
So the row was finished, and 49 s later the same dispatcher judged its lease lost, killed the
session and re-finished it as `failed` — losing the report and refunding the attempt. Occurrences in
the whole store: **1** (this row), so it is rare, and there are two candidate causes that need
telling apart before touching the file: (a) a second dispatcher on the same row, or (b) the heartbeat
loop still running against a row its own `finish` had already settled. The narrow, correct guard
either way — *if the row is already terminal, kill the session but never re-finish it* — is written
down here and gets a round with a seeded second claim, because this file is the live release path and
a wrong edit stops every shift. The shift's actual WORK landed (ledger items closed), so only the
wake row's history is wrong.

---

## 12. ROUND 8 — THE LEASE RACE IS GUARDED, AND THE ROW REPAIRED ITSELF

The 2026-10-18 lease race from §10 is now guarded, and the diagnosis was independently confirmed
before I shipped it: at **02:09:07** the row was re-finished `done` by another process, with an
outcome that reads

> "DONE 2026-10-18T02:06:46Z. (The dispatcher's 02:07:47 'failed - lease not renewed' is a
> bookkeeping artifact: this sessi…"

So the store's own record now says what §10 said — the work was done and the `failed` was wrong.
**Guard installed** in `wake-dispatch.sh`: `row_state()` does one primary-key read of the row, and
the heartbeat-lost branch now asks it first. If the row is neither `claimed` nor `unknown`, it logs
`the row is already '<state>' - killing the session but NOT re-finishing it`, kills the session (a
second worker must never run the same row) and exits **without writing**. It is deliberately
cause-agnostic: both candidate explanations for the race lose the same way if the row is re-written,
so the guard does not need to know which one it was.
*Proof:* `row_state`'s exact query returns `1175 -> done`, `1180 -> new`, `99999 -> missing`; the
guard is present (4 references); `bash -n` clean; `--dry-run` still runs
(`releases today 27/150 … reap: 0 back to new`). It fails **safe**: an unreadable store prints
`unknown` and the old behaviour resumes untouched.
Backup: `wake-dispatch.sh.bak-settled-*`.

---

## 13. ROUND 9 — THE ROWS THE TRANSPORT BUG KILLED ARE REVIVED, BY A RULE
Fixing the prompt-transfer defect (round 2) stopped new work items dying of it, but did not bring
back the ones already killed. Measured: **22 rows** carry a `prompt transfer …` outcome and are still
`failed`/`new`. They split cleanly, and the split is the rule:

| kind | count | verdict |
|---|---|---|
| subject carries a date (`…:20261016`) | 18 | **NOT revived** — the brief is one to two days old and the sources re-file the current condition; reviving spends a shift on a stale measurement, which is the very defect §9 measures |
| standing condition (no date) | 4 | **revived** — it never ran, so nothing about it is stale |

Revived: `602 cron-failing:wake-cost`, `932 stickybrand-828330-delivery-verify`,
`1123 finance-reconciliation-disagrees`, `1150 cron-failing:journal-ceiling-refresh` — set to
`state=new, attempts=0, not_before=NULL`, with a reasoned outcome line rather than silence.
*Proof:* all four appear in `wake-nextclaim.py`'s `claimable_ids` (claimable 9 of waiting 11).
22-row JSON backup: `/root/.sms-inbox/wake-prompttransfer-backup-*.json`.
**The rule, for next time:** a transport failure is not a spent attempt, but an expired *brief* is
not revivable work either. Revive on the subject's timelessness, never on the failure's cause alone.

---

## 14. ROUND 10 — THE DIGEST: PATH CORRECTED, NUMBERS CONFIRMED BY ME, DEPLOY COST DOWN

**15. The audit cited a file that does not exist, and the correction makes the fix cheaper.** It
described the owner digest as `/opt/company/app/services/owner_attention.py`. That path is absent
(`ls` → No such file). What actually runs is
`/root/personal-secretary-mvp/scripts/owner_attention.py` — 48,516 B, md5 `66700644` — executed by
`lpt-owner-attention.timer` as:
`ExecStart=/root/personal-secretary-mvp/.venv/bin/python3 /root/personal-secretary-mvp/scripts/owner_attention.py send --days 3 --top 12 --urgency urgent`.
Its substance stands (its `send()` citation lands on line 1041, which in the real file IS
`print(f"SENT {len(body)} chars to {dest} …")`), so the audit read this file and recorded a wrong
path — a shape this estate keeps paying for.
**What that changes: the digest is a TIMER-RUN STANDALONE SCRIPT, so a code change takes effect at
the next 14:14 run with NO company-api restart.** The remaining item is therefore cheap to deploy,
and the reason it sat undone was assumed, not measured.

**16. Confirmed by me from journald, not from a child's report** (`journalctl -u
lpt-owner-attention.service --since "2 days ago"`):
```
Oct 16 14:24:35  built: 36 item(s) surfaced from 78 candidate(s)
Oct 16 14:24:35  SENT 269 chars to +18483897895 (urgency=urgent)
Oct 17 14:22:32  built: 36 item(s) surfaced from 78 candidate(s)
Oct 17 14:22:32  SENT 258 chars to +18483897895 (urgency=urgent)
```
So 36 items are surfaced from 78 candidates and **258 characters** reach him: one urgent item, and no
liveness line anywhere in the text. That is the whole of the owner's daily visibility into a system
running 30 shifts a day.
**NOT CHANGED, and this one is his call, not mine:** altering what lands on his phone is an outbound
change and needs his yes to the exact text. The proposed addition is one line at the top —
`WAKE: alive | 30 releases today | 0 failed | dispatcher 0.5 min | 112 todo` — read from the two
heartbeat files and the store, no new message, no new channel.

---

## 15. ROUND 11 — "RESOLVED" IS NOT "UNBLOCKED", AND THAT KILLS A RECOMMENDED AUTOMATION

§4's P2 list said the stale-block detector is unreachable (`work.py:1054-1069` only runs on the
`nothing-todo` branch, and there are 112 todo items, so it never runs), and implied releasing blocked
items whose named owner row is resolved. **Measured, and the implication is wrong.** Of the 28 blocked
items with no `owner_row` column set:

- `292 Work the 223 new production-audit findings` cites owner row **295, which IS resolved** — and
  the resolution text is *"I walk them, not you"*. The owner claimed that work for himself. Releasing
  it would hand an autonomous shift work he had explicitly taken.
- `247 PARTNER signs in…` cites row **533, resolved** (the Cloudflare token was created), so that
  blocker is genuinely satisfied — but its remaining work needs a deploy, which is the class owned by
  owner row 547.
- `364` cites row **525, still pending** — correctly parked, nothing to do.

**So the safe rule is not "release when the cited row is resolved"; it is "read the resolution text
and decide whether the row was satisfied or the work was claimed".** A blanket release would have
produced the worst failure shape available here: the machine doing work the owner said he would do,
and reporting it as progress. Nothing was released this round, deliberately.
**What this changes for `work.py`:** the useful automation is not a release rule but a *report* —
when a blocked item's cited row is resolved, print `resolved-row: item <id> cites <row> (<verdict>)`
on the stale scan and let a session decide, exactly as `work.py` already does for the other stale
classes. That keeps the judgement where the text can be read.

---

## 16. ROUND 12 — TWO VERBS THAT EXISTED AND NEVER RAN NOW RUN, AS A REPORT

`work.py lint-refs` and `work.py due` both existed, both produce actionable output, and **nothing
scheduled either** — `lint-refs` ran only on the claim-next `nothing-todo` branch, which cannot fire
while 112 todo items exist. Measured when first run by hand:

```
STALE item 32  (lpt-sync)   -> owner-queue #526 is dismissed
STALE item 247 (lpt-website)-> owner-queue #533 is resolved
STALE item 323 (prod-db-sync)-> owner-queue #428 is resolved
STALE item 345 (lpt-website)-> owner-queue #520 is resolved
STALE item 366 (lpt-sync)   -> owner-queue #526 is dismissed
+ 8 ORPHAN (a title naming owner-queue #N with owner_row NULL)
due: item 345 (p1, revisit 2026-10-16) and item 128 (p5, revisit 2026-10-17)
```
Both are now wired into `run-wake-sources.sh` as a **report**, in the 15-minute loop, logging
`ledger-refs STALE=n ORPHAN=n: <first entries>` and `ledger-due n item(s) past their revisit time`.
*Proof:* the block produces `ledger-refs  STALE=5 ORPHAN=8: STALE item 32 (lpt-sync) -> owner-queue
#526 is dismissed|…` under the same shell; `bash -n` clean; backup
`run-wake-sources.sh.bak-ledgerrefs-*`.
**Why a report and not a release** is §15: item 292's cited row is resolved and its resolution reads
"I walk them, not you". The repair here is *visibility*, and the decision stays with a reader.
Also queued for the owner: **row 549**, the digest liveness line (§14) — so the question survives the
conversation, which is the one thing guaranteed to be thrown away.

---

## 17. ROUND 13 — MY OWN CHANGE MADE WASTE, A SHIFT CAUGHT IT, AND THE RACE CAUSE IS NOW KNOWN

**18. The lease race's cause is established, from the row itself.** Wake 1175's repaired outcome now
reads: *"this session called `wake.py finish` while the dispatcher still held the lease, so its next
heartbeat saw the row unclaimed and killed the runner."* That is candidate (b) from §12 — the session
settling the row under the dispatcher — so the round-8 guard (settled row ⇒ kill, never re-finish) is
aimed at the actual mechanism rather than at a guess. It was shipped cause-agnostic and it turns out
to be exactly right.

**19. Wiring the integrator (§8) amplified an existing bug, and a shift filed it as item 545.**
Verbatim: *"item 533 claimed origin/integrate/master-34 was unmerged; the branch is master 4026431c9
direct parent and 0 ahead. The checkout was shallow (.git/shallow cut master at cd6ca1c1f) so
merge-base/merge-tree could not see the ancestry; **the integrator has no shallow check**. One shift
was spent on a no-op and items 533-537 share the risk."* In a shallow clone `merge-base --is-ancestor`
returns FALSE for a direct parent, so every already-merged branch reads as unmerged.
Fixed: a per-repo `git rev-parse --is-shallow-repository` guard that SKIPS the repo loudly
(`SKIPPED (shallow): … NO branch in this repo can be called unmerged`).
*Proof:* the dry run now prints `lpt-website SKIPPED (shallow)` — which is where items 531 and 532
came from — and `prod-db-sync … merged=10`. Backup `work-integrator.py.bak-shallow-*`.
Retracted the three false claims (531, 532, 533) as `dropped` with the measurement recorded in
attempts **989, 990, 991** each: *"filed by work-integrator from a shallow clone, which cannot answer
is-ancestor."*
**The lesson is the estate's own, applied to me:** a tool that had never run on a clock was wired into
one, and its first act was to manufacture three work items that did not exist. Wiring a dormant
mechanism is not free — it needs the same proof as new code.
**Still open from this:** 536, 537, 538 are prod-db-sync items from the same run. prod-db-sync is not
reported shallow, but 533 proved its base detection can still be wrong, so those three need one
verifying shift before anyone trusts them.

---

## 18. ROUND 14 — THE THREE ITEMS I WAS ABOUT TO RETRACT ARE REAL

§17 left 536/537/538 open: prod-db-sync items from the same integrator run that produced the false
533. I was one step from retracting them by association. **Measured instead, with the commands the
items' own DoDs name:**

```
git -C /opt/company rev-parse --is-shallow-repository      -> false
origin/integrate/master-pds31-20261015             ahead=19  ancestor_rc=1
origin/integrate/preserve-uncommitted-20261013-subset  ahead=1   ancestor_rc=1
origin/rescue/secratary-worktree-20261007T160715Z   ahead=1   ancestor_rc=1
```
All three are genuinely ahead of `origin/master` and none is an ancestor, on a repo that is NOT
shallow. **They stay.** So the split is precise and each verdict came from a measurement rather than
from its neighbours:

| item | repo | verdict |
|---|---|---|
| 531, 532 | lpt-hub | retracted — the clone **is** shallow today; ancestry uncomputable |
| 533 | /opt/company | retracted — depth-proven no-op by the shift, and the clone was shallow *then* |
| 536, 537, 538 | /opt/company | **real** — ahead 19/1/1, not ancestors, repo not shallow |

That also explains the apparent contradiction: `/opt/company` was shallow when 533 was measured and
is not shallow now (it was deepened in between), so the same command gives opposite answers at two
times. **A depth reading is a reading with a timestamp, not a property of the repo.**
**The rule this round paid for:** never retract a sibling on the strength of a neighbour's failure.
Verify each, with its own DoD's command, or leave it alone.

---

## 19. ROUND 15/16 — `lint-refs` SUGGESTS LINKS TO ROWS THAT DO NOT EXIST

Acting on the 8 ORPHANs from §16. `work.py lint-refs` prints a ready-to-run fix —
`link it: work.py owner-row <id> --owner-row <n>` — and **three of the eight named row 2026.**
Measured: `select count(*) from owner_decision_queue where id=2026` → **0**. The queue holds 545-odd
rows, so `2026` is almost certainly a YEAR pulled out of prose by the orphan parser, offered as an
owner-row id with the same confidence as the real ones. Applying it would have created three links to
a row that does not exist, and the next reader would have trusted them.
**Applied only the four verified targets** — 546→542, 543→537, 529→516, 520→498, each confirmed to
exist first (`owner-row-set {"item": 546, "owner_row": 542, "previous": null}` ×4).
`lint-refs` now reports **8** findings instead of 13.
**The defect to fix, in `work.py`:** an ORPHAN whose extracted id does not exist in
`owner_decision_queue` must be reported as `UNRESOLVED-REF` naming the string it tried, never as a
`link it:` command. The test is one `select id` — it is already reading that database to know the
row is non-pending. Until then the three `2026` suggestions stay unapplied, deliberately.
**And the pattern again:** the tool was right to complain and wrong about the remedy, which is worse
than silence when the remedy is a copy-pasteable command.

---

## 20. ROUND 17 — I TRIED TO FIX IT TWICE, FAILED, AND SHIPPED NOTHING

Attempted the `work.py` UNRESOLVED-REF guard from §19. Two patches, both compiled, both **did not
work**, and neither was installed:

1. First attempt reached for `a.db.execute(...)` in the `lint-refs` print loop. Result:
   `UNRESOLVED-REF` count **0**, `ORPHAN` count **3** — i.e. `_qids` came back empty and the guard
   failed OPEN, printing the bogus `--owner-row 2026` suggestion unchanged.
2. Second attempt handled both a connection and a path (`hasattr(a.db,"execute")`, else
   `sqlite3.connect("file:%s?mode=ro")`). Result: **still 0**. So neither accessor is the one that
   resolves the statuses the STALE lines display — `_orphan_prose_owner_refs()` holds the right
   handle internally and it must expose the id set rather than the printer reconstructing it.

**Nothing was installed.** `grep -c UNRESOLVED-REF /home/zabz/bin/work.py` → **0**, and the patched
copy was deleted so no future deploy can pick it up; `lint-refs` still reports the same 3 orphans,
i.e. behaviour is exactly as before. The `.bak-*` files listed beside it are older, unrelated backups.
**Why this is the right outcome and not a wasted round:** the tempting move was to install the
compiled file and report a fix. It would have been a no-op wearing a commit message, and the next
session would have believed the bogus `2026` suggestions were handled. **A change that cannot be
shown to change behaviour is not a change.** What the next attempt needs, precisely: have
`_orphan_prose_owner_refs(db)` return `(orphans, existing_ids)` in one pass — it already has the open
connection — and let the printer use that set.
**Also still unexercised, unchanged from §16/§19:** `ledger-refs` in cron (first tick 02:37) and the
checkout-health suppression (first date roll at 00:07). Three promises now rest on hand-testing only,
and they are named rather than dressed up.

---

## 21. ROUND 18 — CONTAINED WHERE IT SPREADS

A third attempt at `work.py` was the wrong move, so instead the hazard is cut at the point it
propagates: round 12's log line QUOTED every `link it: work.py owner-row <id> --owner-row <n>` that
`lint-refs` emits, including the three naming the non-existent row 2026 — into `sources.log`, which a
shift reads. It now counts orphans and quotes only STALE lines, whose ids were genuinely resolved
against the queue.
*Proof:* the same shell that produced the bad line now prints
`STALE=5 ORPHAN=3: STALE item 32 (lpt-sync) -> owner-queue #526 is dismissed|STALE item 247
(lpt-website) -> owner-queue #533 is resolved|` — counts kept, no copy-pasteable command, no `2026`.
`bash -n` clean; backup `run-wake-sources.sh.bak-orphanquote-*`.
**This was a containment, and §23 is the fix.** `work.py` still emitted the bad suggestion for
anyone running it by hand until round 20; the connection that resolves those statuses is in a
DIFFERENT database from the one `_orphan_prose_owner_refs` opens — which is why two attempts failed.

---

## 23. ROUND 20 — THE FIX, ON THE THIRD ATTEMPT, AND WHY THE FIRST TWO FAILED

The cause, stated exactly: `_orphan_prose_owner_refs()` connected to the **ledger**, and the ids it
needed to validate against live in the **owner-queue** database. `work.py` already had the one
resolver for that — `resolve_oq_db()`, used by `_stale_oq_refs` four hundred lines earlier — and I
never looked at how that function got its statuses. Two patches failed because I reached for a handle
that could not hold the answer.
**Shipped:** `_orphan_prose_owner_refs` now attaches `exists` to every orphan, read in one pass from
`owner_decision_queue` via `resolve_oq_db(None)` on a read-only connection, and the printer emits
`UNRESOLVED-REF … which does NOT exist in the queue; not a link - probably a year or a task id`
instead of a `link it:` command. Fails OPEN: an unreadable queue reports every ref as existing, which
is the old behaviour.
*Proof on the live file:* `work.py lint-refs` now prints
`UNRESOLVED-REF item 521 (cfo, todo) -> title/why names owner-queue #2026, which does NOT exist in
the queue` for 521, 522 and 523, and **0** ORPHAN lines — the four real ones were linked in §19, the
three bogus ones are named as bogus, and nothing is silently dropped. `work.py list` still works.
Backup `work.py.bak-orphanfix-*`.
**The transferable lesson:** before adding a lookup, find the function in the same file that already
performs it. I spent three rounds on a connection that already existed, four hundred lines up.

---

## 24. ROUND 24 — THE REMINDER BRANCH OF THE SWEEP HAS NO SINK

Checked whether a woken session can actually *create* a reminder, which "sets reminders" requires.
**It cannot.** `ls /root/bin/*remind* /home/zabz/bin/*remind*` → nothing, and
`grep -ln "INSERT INTO reminders"` across `/root/bin`, `/home/zabz/bin` and `/opt/company/scripts`
→ nothing. The only writers of `reminders` are the app's own agent actions (`source` values
`chat_action` 599, `owner_direct_request` 12, `twilio_sms` 2, …), which a headless DSH session does
not reach.
**So `session-sweep.py`'s `REMIND_RE` branch is detection without a sink.** It was written to catch
"remind me …" and pass it to a shift. Nothing in `build_prompt()` promises a reminder — the prompt
offers only `work.py add` and an owner-queue row — so the behaviour is harmless rather than wrong,
but the `reminder` field is dead data and a genuine "remind me Thursday" from a chat ends up as a
ledger item or a queue row, not as a reminder on a clock.
**The fix, not made (and why not now):** a `reminder-add.py` CLI that inserts into `reminders` with
the app's own required columns, `source='session_sweep'`, `source_ref=<session_id>`. The DDL is known
(NOT NULL on message/scheduled_time/source/status/priority/requires_ack/delivery_channel/
delivery_attempts/quiet_hours_override/created_at/updated_at) and `process_due_reminders` delivers
punctually, so the sink would work — but that is a NEW WRITER to a live production table, and §13
already paid for what happens when a dormant mechanism is wired up without proof. It needs a
throwaway-store test that proves a row is inserted, picked up and delivered, before it touches
`authority.db`.
**Until then, be precise in any report about this:** the system reads the day's sessions, and it does
file their loose ends — but it does not yet turn a spoken reminder into a scheduled one.

---

## 25. ROUND 25 — TWO ITEMS UNBLOCKED BY READING THE RESOLUTION TEXT

Applied the §15 rule to the five STALE items: read each cited row's resolution, then decide.
- **item 345 (p1) → todo.** Row 520: *"Decided 2026-10-15 by me, under DQT1 … PROMOTE IT."* The
  reviewer the blocker named is the owner, and he approved. Released — a priority-1 item that was
  sitting behind a decision that had already been made.
- **item 247 (p4) → todo.** Row 533: *"DONE 2026-10-16. The owner supplied the credential and the
  deploy path completed end to end."* Blocker satisfied. Released.
- **items 32, 366 (cite 526) and 323 (cite 428) are NOT released.** 526 reads *"NOT AN OWNER
  DECISION - moved to the business queue"*, so their block should cite that queue, not row 526; and
  323's `blocked_on` says *"DATE GATE, not a person: the Monday-only gate"*, so row 428 was never its
  gate. Both need their `blocked_on` corrected rather than the item released — a distinction only
  reading the text produces.
*Proof:* `345 todo p1`, `247 todo p4`; blocked **38 → 36**; `lint-refs` STALE **5 → 3**; attempts
994 and 995 recorded with the resolution quoted.
**Two of five released, three correctly refused, and the refusal is the interesting half.**

---

## 26. ROUND 26 — MY THIRD `work.py` PATCH REPORTED SUCCESS AND WROTE NOTHING

`work.py edit` cannot correct `blocked_on` (it takes title/dod/why/priority), which is what the three
refused items in §25 need. I added the field to `_EDITABLE_FIELDS` and a change branch in `cmd_edit`,
then tested it on a **throwaway store** rather than production — and the test caught it:

```
$ work.py --db /tmp/wt3.db edit 1 --from-json /tmp/t.json --by tester
edit-ok {"fields": ["blocked_on"], "id": 1, "note": 1}
$ sqlite3 /tmp/wt3.db "select id||' -> '||coalesce(blocked_on,'(null)') from work_item"
1 -> (null)
```

It **detected the change, wrote it to the note trail, printed `edit-ok`, and updated nothing** — the
generic UPDATE that applies `changes` does not carry `blocked_on`. That is precisely the failure class
this whole audit is about, committed by me, in a patch I was about to install because it compiled and
looked like its three siblings.
**Not installed.** `work.py` is untouched (`grep` for the new field → 0, `py_compile` clean,
`lint-refs` still reports the same 3 STALE), the `.new` and every throwaway store were deleted.
**What this proves and why it is the most useful round in the tail of this session:** the sibling
branches (`title`, `dod`, `why`, `priority`) work because the UPDATE carries those columns — copying
their shape is not the same as joining their whitelist. **The next attempt must find the column list
the UPDATE uses, not the list `_EDITABLE_FIELDS` holds.** Two lists, and I patched the wrong one.
A patch whose only proof is that it compiles is not proven; a patch whose proof is a success message
is not proven either.

---

## 27. ROUND 27 — `edit` CAN NOW CORRECT `blocked_on` (3rd attempt, works); AND A DESIGN DEFECT UNDER IT

**SHIPPED.** The third attempt at `work.py edit` succeeded, and the reason the first two failed is now
written into the code: **three places must agree** — `_EDITABLE_FIELDS`, the change branch in
`cmd_edit`, and the ALWAYS-FULL column list in the `UPDATE` (`SET title=?, dod=?, why=?, priority=?,
blocked_on=?, updated_at=?`). The earlier attempts changed the first two and not the third, so the row
was reported edited, the note trail was written, and nothing was stored.
*Proof, throwaway store first:* `edit-ok {"fields": ["blocked_on"], "id": 1, "note": 1}` **and**
`1 -> Monday-only gate, not a person`. Then on the live ledger: items 323, 32 and 366 corrected
(notes 25, 26, 27). Backup `work.py.bak-blockedon-*`.

**STILL OPEN, and it is a DESIGN defect rather than a bug.** `lint-refs` kept reporting 323 and 366
after the text was corrected, because `_stale_oq_refs` resolves **`owner_row`**, and that column still
holds 428 and 526. They are not gates — for 323 the row was resolved *by filing the item*, and for
366 the row was *dismissed* — but `work.py` has no way to say "this reference is provenance":
`owner-row` demands an integer (`invalid int value: ''`), so it cannot be cleared, and the scanner
cannot distinguish a gate from a citation.
**The fix, precisely:** either make `owner_row` clearable (`owner-row <id> --clear`) and have the
scanner skip a NULL, or add a `blocked_gate` column that the scanner reads instead of `owner_row`.
Until then, an item whose owner row is provenance reports STALE for ever — the report is *correct
about the field and wrong about the meaning*, which is this estate's signature failure in its mildest
form.

---

## 28. ROUND 28 — FIVE STALE REFERENCES TO ZERO, AND TWO LESSONS I KEPT RELEARNING

**The capability was already there.** `cmd_owner_row` reads
`val = None if getattr(a, "clear", False) else a.owner_row` — there is a `--clear` flag. My round-27
attempt used `--owner-row ""` and concluded the field could not be cleared, and §27 then specified a
code change that was never needed. `owner-row 323 --clear` → `{"owner_row": null, "previous": 428}`;
same for 366. **I wrote a design recommendation for a feature that existed, because I did not read the
command I was calling.** That is the second time in this session (the first was `resolve_oq_db`), and
both times the answer was in the same file, above or below the code I was reading.

**Then my own correction re-created the citation.** Item 323 still reported STALE after clearing,
because `_stale_oq_refs` parses PROSE — and my "corrected" `blocked_on` read *"owner row 428 is
PROVENANCE"*, naming the row. The explanatory sentence re-established the very reference the sentence
existed to explain. Reworded without the number (the row is now described, not named), and:
`lint-refs` → **STALE 0**.
**Final ledger effect across §19-§28:** 5 STALE → 0, 2 items released with their resolutions quoted
(345 p1, 247), 3 blockers corrected in place (32, 366, 323 → notes 25, 26, 27, 28), and `work.py edit`
gained a `blocked_on` correction path that is proven on a throwaway store *and* on the live ledger.
**The two lessons, and they are the same lesson:** read the function you are about to reimplement, and
do not put the identifier you are suppressing into the text that explains the suppression.

---

## 29. ROUND 29 — PROVEN BY A CLOCK, AND IT PAID FOR ITSELF IMMEDIATELY

The `ledger-refs` / `ledger-due` block fired in cron for the first time at **02:37:01**:

```
02:37:01  ledger-refs  STALE=1 ORPHAN=1: STALE item 290 (kosher-ai-filter) -> owner-queue #524 is resolved|
02:37:01  ledger-due   1 item(s) past their revisit time: 128  housekeeping  2026-10-17T01:06:14+00:00 5  vendor: Sticky Brand…
```

So §16's wiring is **proven by a clock, not by my hands** — the last of the three hand-only items in
§22 to become verified. And it earned its place inside the first minute: item 290 cites row 524, which
was PENDING an hour earlier and had just been resolved.

Row 524: *"DEPLOYED AND VERIFIED FROM OUTSIDE 2026-10-18 … Measured: `docker ps` shows
lpt_filter_ai_api Up 7 minutes (healthy) and lpt_filter_ai_api_b Up 8 … verified AGAIN by me rather
than only reported by the deploying agent."* That is second-party verification of exactly what item
290 asked for, so **290 is closed `done`** (attempt 1001) with the resolution quoted as proof and
`--left` recording that the verification pre-dates the close.
**Ledger now:** blocked **35** (38 at session start), done 382, todo 115.
**Note the shape:** a stale-reference report, wired this session, found a blocker that had become
obsolete within the hour; reading its cited row turned it into a completed item rather than a shift's
worth of re-derivation. That is the whole thesis of §1 working in production.

**Round 30 checkpoint (02:39Z):** 33 releases today, 1 failed, **23 items closed at 0.089 USD each**,
todo 115 with a **priority-1 at the front** (item 345, released in §25 from a resolved owner row),
blocked 35, `PROBLEMS none`, failed 118 → 114 (the four revived rows, §13), dispatcher heartbeat 4.4 min.
**One known, accepted report:** item 366 shows ORPHAN because its prose names owner-queue #526 as
HISTORY — *"moved from row 526 to the business queue"* — and the linter cannot tell history from a
gate. Its `owner_row` is correctly NULL. The alternative is deleting the provenance from its `why` to
make a counter read zero, which trades a true record for a tidy number. Left as is, deliberately.

---

## 30. ROUND 31 — THE REMINDER SINK NOW EXISTS AND IS PROVEN ON A THROWAWAY STORE

§24 recorded that a session could not create a reminder. `/root/bin/reminder-add.py` now does:
one insert into the table `process_due_reminders` already drains, with the NOT-NULL columns the app
requires, `--dry-run`, `--db` so it can be pointed at a throwaway store, and `source_ref` as the
idempotency key. Delivery, quiet hours, ack and snooze stay the app's business — this is a sink, not a
scheduler.

*Proven on a throwaway store built from the real DDL* (not on production):
```
reminder-created {'id': 1, 'at': '2026-10-18T04:41:31+00:00', 'channel': 'dashboard'}   # "in 2h"
reminder-created {'id': 2, 'at': '2026-10-19T09:00:00+00:00', 'channel': 'dashboard'}   # "tomorrow 9am"
rows: 1|pending|dashboard|2026-10-18T04:41:31|probe1   2|pending|dashboard|2026-10-19T09:00:00|probe2
re-run probe1 -> exists {'id': 1, 'source_ref': 'probe1'}
```
A bad time is **refused** (rc=2) rather than guessed: *"a reminder on the wrong day is worse than
none."* The throwaway test also caught a real bug before install — `"in 2h"`, the obvious spelling, was
rejected because the first parser split on whitespace and expected `"2 h"`; it is now a regex.

**What is NOT done, and must not be implied:** nothing calls it yet. The shift prompt and
`session-sweep`'s `build_prompt()` mention only `work.py add` and owner-queue rows, so a session still
cannot be *told* to use it — and no end-to-end delivery has been observed, because creating a real
reminder puts a message in front of the owner and that is his call, not mine. The remaining steps are
one line in the shift contract and one deliberately-created reminder watched to `status='sent'`.

---

## 31. ROUND 32 — THE CONTRACT NOW TELLS A SHIFT HOW TO SET A REMINDER

`wake-dispatch.sh` rule 6 gained a paragraph (the WAKE CONTRACT every release carries), because §30
left the sink unreachable: *"A REMINDER IS NOT A MESSAGE, and you may set one … `--at` accepts ISO8601,
`in 2h`, `in 3d` or `tomorrow 9am` and REFUSES anything else rather than guessing. It writes one row to
the dashboard reminder queue and never sends a text, so rule 6 still governs anything that leaves the
building. `--source-ref` is the dedupe key."*
**The hazard that made this a careful edit:** the contract lives inside a bash `$'...'` string, where a
single quote terminates it and breaks the contract for EVERY shift. The added text therefore contains
no apostrophes and no single quotes, and says so in a comment above it.
*Proof:* `bash -n` clean; a `--dry-run` renders the prompt and `grep -c reminder-add.py
/tmp/pt/prompt.txt` → **1**, on the patched copy and again on the installed file. Backup
`wake-dispatch.sh.bak-reminderrule-*`.
**Still not proven:** an actual reminder created by a shift and delivered. That needs one deliberately
created and watched to `status='sent'`, and creating one puts a message in front of the owner — so it
waits for him.

---

## 32. ROUND 34 — THE SWEEP NOW TELLS A SHIFT TO USE THE SINK

The last link: `session-sweep.build_prompt()` gained rule 3b — *"If the session asked for a REMINDER at
a time … do not file it as work — schedule it"* — with `--source-ref` set to the **session id**, so a
re-run cannot double-schedule, and an explicit note that a CLI refusal is a correct outcome rather than
something to work around with an approximate reminder.
**Caught in my own text before it shipped:** the example first read `--at "mon 9am|…"`, and the parser
does not accept day names — only ISO8601, `in 2h`/`in 3d`, and `tomorrow 9am`. A prompt that teaches a
command the tool refuses is worse than no prompt, so it was corrected in the same round.
*Proof:* compiles; a live dry run still reports `228 session(s) … 1 candidate(s)`; and a rendered
prompt for a synthetic reminder candidate contains `reminder-add.py`, the session id as `--source-ref`,
and the corrected `--at` example.
**The chain is now complete except its last link, which is the owner's:** detect (sweep) → instruct
(contract + prompt) → write (reminder-add.py, proven on a throwaway store) → deliver (**unproven**;
needs one real reminder watched to `status='sent'`).

---

## 33. ROUND 35 — THIRTY MINUTES, SIXTEEN RELEASES, ZERO FAILURES

Stability check after ~12 edits to live files in one session:

```
02:47:15Z  releases today 38 of 150 | failed 1 | PROBLEMS none
           finished in the last 30 min:  done 16 | failed 0
           26 items closed today at 0.082 USD each | todo 114 | blocked 35 | claimed 3
           dispatcher heartbeat 0.2 min | sources heartbeat 9.9 min (loop runs every 30)
```
**Sixteen consecutive releases, all `done`, no failures**, three in flight, and the cost per closed
item has fallen from 0.089 to 0.082 as throughput rose. Releases today went 15 → 25 → 33 → 38 across
the session, and 16 of those 38 landed in the final half hour — the fan-out target (1 → 3), the scp
retry, the attempt refund and the settled-row guard compounding.
This is the objective's own test, read from the store rather than asserted: the company runs while
nobody is watching, and what it runs is recorded.

---

## 34. ROUND 36 — A COUNTER THAT DESCRIBED ITSELF, INSIDE THE SENSOR I WROTE

`session-sweep`'s state file claimed `filed: 3` while the wake table held **2** rows with
`source='session-sweep'`. Cause, from the 02:07 log: `flagged session-sweep:90c1285d… ->
suppressed:cooldown` was counted as a FILING. A suppression produces no row and costs nothing, so it
was silently shortening the day's quota for genuine candidates.
Fixed: only a verdict starting with `filed` spends the budget; anything else prints
`not a filing (<verdict>) - the daily budget is unchanged`. Today's counter was then reconciled to the
store (3 → 2) so the third real candidate can still go out.
**Why this belongs in the record and not a footnote:** it is the same defect as §1 — a number that
describes itself instead of the thing it claims to measure — living inside the sensor written to stop
that, written by the session that had spent thirty rounds cataloguing it. Two of the four bugs found in
my own code tonight were of exactly this shape. The discipline is therefore not "avoid the error" but
"make the number readable back from the store", which is the only test that catches it.
**Also verified:** the additions run on EVERY tick, not once — `ledger-refs`, `ledger-due`,
`session-sweep` and `work-integrator` all appear at both 02:07:01 and 02:37:01.

---

## 35. ROUND 39 — THE INTEGRITY CHECK CANNOT TAKE A CONSISTENT SNAPSHOT, AND SAYS SO IN A LOG LINE

Found while regression-checking my own edits, which is the only reason it was seen: three
pre-existing `FAILED` lines in `sources.log`, and one matters.

```
status.json : at 2026-10-14T00:03:20Z | ok TRUE | 732.1 s | 26,779,312,128 bytes
              source "live-readonly(in-place)" | snapshot null | snapshot_age_seconds null
              warning: "no usable snapshot under /var/lib/authority-snapshots and the copy gate needs
              35.2 GiB free while this filesystem has 0.0 GiB: the LIVE database was read read-only
              IN PLACE under the shared I/O lock, bounded to 1800 s."
cron.log    : FAILED TO CHECK - not enough free space for a consistent copy: 8.9 GiB free,
              33.6 GiB required (DB_INTEGRITY_FREE_COPY_FACTOR=1.25 x the live database)
now         : 25,436,592 KB free (24.3 GiB); crontab has the weekly line (17 4 * * 0)
```
**So the estate's only database-integrity verification has never had the room to check a CONSISTENT
copy.** It reads 26.8 GB in place under a shared I/O lock and calls that `ok: true`. An in-place read of
a live, written-to database is not the same claim as an integrity check of a snapshot, and the tool's own
warning says so — once, into a file, at 4-day-old intervals.
`db-integrity` reports `SIGNAL UNREADABLE ... not completed for 98.6 h` because the status file is stale;
the real cause is the free-space gate, not a broken job. Those are different sentences and the source
currently prints the wrong one.
**The arithmetic, so the decision is not a guess:** the copy needs 1.25 × 26.8 GB = 33.5 GB free;
there are 24.3 GB. The shortfall is about **9 GB**. The candidates are (a) prune snapshots under
`/var/lib/authority-snapshots` (the `prune-backups` and `disk-guard` jobs already own that area),
(b) lower `DB_INTEGRITY_FREE_COPY_FACTOR` — which trades the safety margin for the check and should not
be done casually, or (c) accept in-place reads and say so explicitly in the status file instead of
leaving a warning nobody reads. **Not acted on**: this touches the only integrity verification of the
company's authoritative database, and every option either deletes something or weakens a margin. It is
recorded as a live risk with a number, and it is the first item for the next session.
**The lesson that generalises:** I found it only because I checked for `FAILED` in a log while checking
my own work. The audit's own §1 pattern — a correct mechanism held back by a condition nobody prints —
one level up from the mechanism itself.

---

## 36. ROUND 41 — THE THIRD `Path.home()` VICTIM, AND THE PATTERN IS NOW A CLASS

`cron-targets` had been logging `SIGNAL UNREADABLE -- the guard itself is missing` on every tick. The
guard is real: **`/usr/local/bin/cron-target-guard.py`, 27,212 B**, and the crontab already calls it from
there. `cron-targets.py:55` defaults it to `Path.home()/"bin"/...`, and cron runs these sources as root
with `HOME=/root`, so it looked in `/root/bin`.
Fixed as CONFIGURATION, not code — the source already reads `CRON_TARGET_GUARD`, so it is one export in
`run-wake-sources.sh`.
*Proof, same command, two environments:*
```
without the env : cron-targets: SIGNAL UNREADABLE -- the guard itself is missing at /root/bin/cron-target-guard.py
with the env    : quiet
```
**This is the THIRD instance of one class tonight**, all found in different files and all fixed
differently: `dormant-handoff._repo()` (/root/harness-config), `_flag.app_db()` (/root/personal-secretary-mvp/data),
and now `cron-targets` (/root/bin). All three were `Path.home()` resolved under a cron HOME that has
none of those files, and all three printed a line that read like a broken tool rather than a wrong path.
**The class-level fix, for whoever gets there:** `_flag.HOME` should be resolved once — prefer
`/home/zabz` when running as root under cron, or take it from an exported `ESTATE_HOME` — and every
source should use that constant instead of `Path.home()`. Until then, each new source is one cron away
from the same silent death.
**Running total of revivals this session:** dormant-handoff, decision-queue-stale,
decision-answer-unconsumed, and now cron-targets — four sensors that had each been printing a
failure line every tick for days.

---

## 37. ROUND 42 — CHECKING MY OWN CLASS FIX BEFORE ANYONE APPLIES IT

§36 recommended resolving `HOME` once and preferring `/home/zabz`. That is a BROAD change — every
source's store path, CLI path and state directory derive from `HOME` — so it was checked rather than
left standing as advice:

```
/home/zabz/.sms-inbox/inbox.db   33,820,672 B   inode 2080009
/root/.sms-inbox/inbox.db        33,820,672 B   inode 2080009   <-- SAME FILE
/home/zabz/bin/wake.py  and  /root/bin/wake.py  both present
```
So the two home directories resolve to the same store and the same CLI, and a resolved
`ESTATE_HOME` would **not** silently point the sources at a different database — which was the obvious
way to break everything.
**But that is necessary, not sufficient, and §36's wording was too confident.** The shared inode proves
the DB is safe; it does not prove every other `$HOME`-relative path used anywhere in these scripts
(`wake-failed/`, `wake-instances/`, `.wake-projects/`, `.cso/`, marker files) behaves the same, and one
of those differing would be a quiet data split rather than an error.
**Revised advice:** do not swap `HOME` globally. Extend the CANDIDATE-LIST idiom already proven in
`dormant-handoff._repo()` to each path that needs it, one at a time, each with the before/after command
recorded — which is what §3, §36 and this section all did. Slower, and the only version whose failure
mode is visible.
**The general point:** a fix proposed in one section must be measured before a later section relies on
it. I nearly left a confident architecture recommendation that nobody had tested.

---

## 38. THE VERIFICATION LEDGER — WHICH CHANGES A CLOCK HAS PROVEN

Written at 02:53Z, because this session shipped a lot and the difference between "installed" and
"exercised" is the whole subject of the document. **Do not treat row 2 as done until 03:07 exists.**

| change | proven by | state |
|---|---|---|
| `dormant-handoff` repo+ref fix | planted `DORMANT_HANDOFF_DAYS=0` → `flagged dormant-handoff:H7017`; true quiet otherwise | **VERIFIED** |
| `_flag.app_db` → live queue | `flagged odq-stale:78`, `odq-answer-open:61`; in cron 02:07 and 02:37 | **VERIFIED** |
| prompt-transfer retry | forced `WAKE_SCP_CMD=/bin/false`: two attempts logged, rc in outcome | **VERIFIED** |
| attempt refund on a lost hop | row 1173 → `attempts=0`, `state=new`, retry in 600 s | **VERIFIED** |
| answer gate + report in `outcome` | rows 1165/1166 store `# Checkout health … **Result:** …` | **VERIFIED** |
| budget tier at half the cap | `target=3 max=8`, three dispatch processes live | **VERIFIED** |
| session-sweep freshness + owner-last | candidates 3 → 1; 11 still-live and 1 owner-last excluded | **VERIFIED** |
| `work-integrator` scheduled | filed 531/532/533, then 536/537/538; dedupe clean | **VERIFIED** (then bug fixed, §17) |
| shallow-clone guard | dry run: `lpt-website SKIPPED (shallow)`, `prod-db-sync merged=10` | **VERIFIED** |
| `lint-refs`/`due` in cron | `02:37:01 ledger-refs STALE=1 ORPHAN=1 …`, `ledger-due 1 item` | **VERIFIED** |
| orphan id validation | `UNRESOLVED-REF … #2026 does not exist` ×3, `ORPHAN 0` | **VERIFIED** |
| `edit --blocked_on` | throwaway store: value stored; live: notes 25-28 | **VERIFIED** |
| `reminder-add.py` | throwaway store: `in 2h` → +2h, `tomorrow 9am` → 09:00, dedupe | **VERIFIED** (store only) |
| contract + prompt tell a shift to use it | dry run renders prompt, `grep -c reminder-add.py` → 1 | **VERIFIED** |
| loop-stall detector (missing file) | standalone: `DETECTOR MISSING` once, then marker-suppressed | **VERIFIED in isolation** |
| `cron-targets` guard path | `SIGNAL UNREADABLE` → `quiet` with the env set | **VERIFIED in isolation** |
| **those two, in cron** | next tick **03:07** | **PENDING** |
| session-sweep quota (filed 2 of 3) | next tick **03:07** should file one | **PENDING** |
| checkout-health suppression | the **00:07 date roll**; look for `suppressed  known:` | **PENDING** |
| settled-row guard | cannot be triggered on demand | **UNPROVEN** |
| a real reminder delivered | one created by a shift, watched to `sent` | **UNPROVEN — needs the owner** |

**Two rows are unproven and one of them is not mine to close.** Everything else has a command behind
it, which is the only standard this document has used from the first section.

---

## 39. ROUND 44 — THE FREE-SPACE OPTION IN §35 IS FALSIFIED BY MEASUREMENT

§35 offered "prune snapshots under `/var/lib/authority-snapshots`" as the cheapest way to find the ~9 GB
the integrity check needs. Measured, and it is worthless:

```
/var/lib/authority-snapshots       1.4 MB   (one dir: r4-deploy-20261014T201607Z)
/var/lib/authority-backup           72 KB
/root/tmp-rescue                    40 KB
/opt/company/archive                12 MB    <-- contradicts AGENTS.md's "6.6 GB lpt-transcripts"; NOT verified, different path or a du that did not descend
/ (sda1)   157,149,496 KB total | 125,296,012 KB used | 25,435,972 KB free | 84%
```
**Pruning cannot free 9 GB because there is nothing there to prune** — the snapshot area holds 1.4 MB.
So the shortfall must be found among the ~125 GB actually in use, and that requires a real inventory of
the filesystem rather than a guess about which directory looks disposable. The 26.8 GB database
accounts for only a fifth of it.
**Two things this changes:** (a) anyone following §35's option (a) would have spent a session and freed
1.4 MB; (b) the `AGENTS.md` figure of 6.6 GB for the transcript archive does not match a 12 MB reading
here, and one of the two is wrong — that is flagged, not resolved, because I did not follow the path
down. **A number from a document is not a measurement**, which is the sentence this document has now
produced three different ways.
**What a fresh session should do first:** `du -x -d1 /` for the real consumers, then decide. Do not
repeat §35's option (a).

---

## 40. ROUND 45 — THE DISK PICTURE, RESOLVED: `/root` IS 77.7 GB

Resolves §39's flag and replaces its dead end with a direction.

**The archive contradiction was mine, not the document's.** `/opt/company/archive/lpt-transcripts` is a
**symlink** to `/opt/company-archive/lpt-transcripts`, and `du` does not follow symlinks — so my 12 MB
reading measured the link's parent and AGENTS.md's figure measured the target. Both were right about
different objects. Real size now: **7.5 GB** (the document says 6.6 GB; it has grown), and
`df -Ph` shows it on **/dev/sda1 — the same filesystem as `/`**, so it does count against the space the
integrity check needs.

**Real consumers of `/dev/sda1` (150 G, 120 G used, 25 G free, 84%):**
```
/root    77.7 GB   <-- the database is 26.8 GB of this; ~51 GB is something else
/opt     28.3 GB
/home     7.3 GB   (includes the 7.5 GB archive, via the /opt/company-archive path)
/usr      2.8 GB
/var      0.5 GB
```
**So the ~9 GB the integrity check needs is almost certainly sitting in `/root`**, which holds nearly
three times the database itself. **Next step, exactly:** `du -x -d1 /root | sort -h | tail` to find the
~51 GB, then decide. Do not prune `/var/lib/authority-snapshots` (§39: 1.4 MB), and do not assume the
database is the problem — it is a third of that directory.
**This is the third time tonight that the number in front of me measured a different object than the one
I assumed**: the notification prefix versus the reminder body, the shallow clone yesterday versus today,
and now a symlink versus its target. The habit that catches all three is the same — print the raw value
beside the predicate.

---

## 41. ROUND 46 — THE 9 GB IS PROBABLY THREE DIRECTORIES NAMED "RESCUE"

Ran §40's command. `/root` at one level down:

```
/root              77.7 GB total
  /root/work                       13.8 GB
  /root/_lptsecret_fix              3.8 GB
  /root/.cfo                        3.8 GB
  /root/repos                       3.7 GB
  /root/mail-archive                2.7 GB
  /root/git-rescue-20261012         2.5 GB
  /root/wt-gf-uefi                  2.2 GB
```
Those seven sum to about 32 GB; the remainder is large FILES directly in `/root`, chiefly
`authority.db` at 26.8 GB.

**The shortfall the integrity check needs is ~9 GB, and three of these are named like temporary
artefacts** — `_lptsecret_fix` (3.8), `git-rescue-20261012` (2.5), `wt-gf-uefi` (2.2) = **8.5 GB**,
which is the shortfall to within half a gigabyte.
**NOT DELETED, and deliberately not deleted by me.** Each is named "rescue" or "fix", each is the kind of
directory this estate created to avoid losing work, and this business has lost customer data twice. The
rule is explicit: no delete without a per-action yes for that exact path. What a fresh session (or the
owner, in one line) should do first is prove uniqueness — that nothing in them exists only there —
before any of the three is removed.
**So the disk thread ends where it should:** the integrity check is blocked by ~9 GB; the ~9 GB is
plausibly three stale rescue directories; proving that is a five-minute check and freeing them is the
owner's call. Nothing was deleted on a guess about a name.

---

## 42. ROUND 47 — ONE OF THE THREE HOLDS UNPUSHED WORK. MY GUESS WAS WRONG.

§41 called the three directories "plausibly stale" from their names. Checked what they actually contain:

```
/root/_lptsecret_fix      clone of github.com/lakewoodphone/lpt-hub
                          head 5cd20bf "security: redact a live BitLocker recovery key…"
                          dirty files 0 | HEAD contained in 1 remote branch   -> PUSHED
/root/wt-gf-uefi          clone of lpt-hub
                          head 3ecb08b20 "Greenfeld Surface 1950: full state of play…"
                          dirty files 0 | HEAD contained in 0 remote branches -> NOT PUSHED
                          local branches: main, item334-shande-sync-link,
                            case/fisher-review-20261018, case/oneplus-third-return-20261018,
                            docs/waze-returns-prop65-20261018
/root/git-rescue-20261012 MANIFEST-README.txt, MANIFEST.tsv, RESCUE.log  -> a deliberate rescue
                          artefact that documents itself; not a clone, not mine to judge
```
**`wt-gf-uefi` holds UNPUSHED work — five local branches, four of them dated customer-case names
(`fisher-review`, `oneplus-third-return`, `waze-returns-prop65`, `item334-shande-sync-link`).** Deleting
it on the strength of the word "wt" in its name, which is what §41 was drifting toward, would have
destroyed unique case work. Only `_lptsecret_fix` is **provably** removable: clean tree, and HEAD is
already contained in a remote branch, so nothing exists only there.
**So the honest accounting:** ~3.8 GB is provably freeable, not 8.5; `git-rescue-20261012` is a rescue
artefact with its own manifest and is not a candidate at all; `wt-gf-uefi` is live work that should be
pushed before anything else is decided about it. That leaves the integrity check still ~5 GB short.
**The lesson, and it is the sharpest one of the night:** a directory's name is not a measurement. §41
said "not deleted on a guess about a name" and then reasoned *from* the names; the check took two
commands and inverted the conclusion for the largest-risk candidate.

---

## 43. ROUND 48 — THE UNPUSHED CASE WORK IS NOW ON THE REMOTE, AND THE DISK ASK IS FILED

Acted on §42's own instruction — publish `wt-gf-uefi`'s work before anything is decided about the
directory. Four branches pushed explicitly by refspec (never `main`, never force), then **verified
against the remote**, not against my own echo:

```
a19a70c80…  refs/heads/case/fisher-review-20261018
9362e88ba…  refs/heads/case/oneplus-third-return-20261018
bf37f6b25…  refs/heads/docs/waze-returns-prop65-20261018
5eb03619f…  refs/heads/item334-shande-sync-link
```
All four SHAs match the local tips. And every commit is now covered:
`remote branches containing HEAD (3ecb08b20): 4`, `main ahead of origin by: 0`.
**So ~6.0 GB is now provably freeable** — `_lptsecret_fix` 3.8 GB (already pushed, clean tree) plus
`wt-gf-uefi` 2.2 GB (previously live unique work, now every commit on origin) — against the ~9 GB the
integrity check needs. `/root/git-rescue-20261012` is **not** a candidate: it is a documented rescue
artefact.
**Filed as owner row 551**, because deleting is his call and the question must survive the conversation:
*"May I remove /root/_lptsecret_fix and /root/wt-gf-uefi? Both are lpt-hub clones whose every commit is
now on origin, and together they are 6.0 GB of the 9 GB the database integrity check needs."*
**The sequence here is the point:** §41 guessed from names; §42 measured and found live case work; this
round **protected the work first** and only then asked about the space. A deletion proposed before the
push would have been a loss dressed as housekeeping.

---

## 22. WHERE THIS STANDS — START HERE NEXT

**Live at 02:27Z:** 31 releases today, **1 failed** (row 1175's lease race, repaired by the system
itself and guarded since), 20 items closed at 0.083 USD each, todo 111, blocked 38, `PROBLEMS none`,
fan-out target 3 where it was 1 when this session began.

**Proven by a clock, not by hand:** the session sweep filed rows (1175, 1180); the integrator filed
integration items (531-538); the prompt-transfer retry and the attempt refund fired on a real row;
the answer gate stored a real report (1165, 1166); the tier change took the fan-out from 1 to 3;
`work.py reap` still runs; remind delivery is punctual.

**Proven by hand ONLY — do not treat as verified:**
1. `run-wake-sources.sh`'s `ledger-refs` / `ledger-due` block — first cron tick 02:37, not yet reached.
2. `checkout-health.py`'s known-blocked suppression — first date roll at 00:07 tomorrow
   (§11 says exactly what to look for, and says what it means if it does not appear).
3. `wake-dispatch.sh`'s settled-row guard — cannot be triggered on demand; it fires only when a
   session settles its own row, which is what caused §12's one occurrence.

**THE NEXT THREE, in order:**
1. **Answer owner row 547.** It frees 12 items (9 restart-blocked + 3 blocked integration items) and
   it is the only thing standing between the fleet and every deploy/deploy-shaped task. Row 549 (the
   digest liveness line) is seconds of work once answered.
2. **Finish the `work.py` orphan fix.** `_orphan_prose_owner_refs` already holds a connection to the
   LEDGER; the id set must come from the OWNER-QUEUE store, which is a different database and is
   resolved elsewhere in `work.py` (wherever `_stale_oq_refs` gets its statuses). Have it return
   `(orphans, existing_ids)` in one pass. Do not retry the two approaches in §20.
3. **The 8 ORPHANs and 5 STALEs now report every 15 minutes** — a session that reads `sources.log`
   should act on them, and the four links already made (546→542, 543→537, 529→516, 520→498) are the
   pattern to follow: verify the target exists, then link.

**Do not do, and why:** do not release blocked items whose cited owner row is resolved (§15 — item
292's resolution says "I walk them, not you"); do not run `deploy.sh` (§4 — it would install a
579-line dispatcher over the live 1252-line one); do not copy an ORPHAN `link it:` command out of the
log (§19 — three named a row that does not exist).

---

## 11. ROUND 6 — THE STANDING CONDITION NO LONGER BUYS A SHIFT EVERY DAY

**13. `checkout-health.py` now asks the ledger before spending a shift.** The fix discussed in §9,
made with both cases planted. `collect_for_flagging()` wraps `collect()` and drops any finding whose
project already has a **blocked** ledger item naming the same reason token
(`dirty-old`, `stranded-branches`, `stranded`), printing
`<pid>  suppressed  known: the ledger already holds a BLOCKED item for dirty-old`.
It **FAILS OPEN** — an unreadable ledger prints a line and files the finding exactly as before,
because a guard must never go silent on an I/O error.
*Proof, both directions:* with the condition planted,
`housekeeping` (blocked item 149, `dirty-old`) is suppressed and `lpt-website` (no matching blocked
item) is **kept** — `kept: ['checkout-health:lpt-website:20261018']`. The source's own
`--selftest` still passes **33 checks**, and a live `--dry-run` reports
`0 flag(s) to raise, 3 suppression(s), 0 unreadable`.
Backup: `checkout-health.py.bak-knownblocked-*`. Note `/root/bin/sources` and
`/home/zabz/bin/sources` are the **same inode** (2163905, md5 `4e4b6300`), so one install covers both.
**Why this is safe and not a way to silence a guard:** it can only suppress a finding whose exact
reason a human or shift has *already written down as blocked in the ledger*. A new condition, a
different project, or an unreadable ledger all still file. What it stops is paying a shift to
rediscover a known-unfinishable state — measured at 5 of 11 releases on 2026-10-18.
**Its limitation, stated so it is not oversold:** matching is at TOKEN granularity, so if
housekeeping acquires a `dirty-old` on a *different* branch (measured 02:07: the token moved from
`keepalive/323-pickup-weekly-digest` to `fix/family-chat-outbox-gate-hold`) it is suppressed too. That
is the intended reading — item 149 is a project-level condition — but a genuinely new reason still
files, and every suppression prints its own line naming the reason and the subject, so the escape
hatch is visible in `sources.log` rather than silent. If the token-level match turns out too coarse,
the fix is to include the branch in the token, not to remove the suppression.
**First live exercise, honestly reported:** running the source immediately after install printed
`prod-db-sync suppressed dedup … is already new` and the same for housekeeping — the *pre-existing*
same-day dedup fires first because the 02:07 rows are still `state=new`. So the new gate is proven by
the planted test, but its first real workout is the **00:07 run tomorrow**, when the UTC date rolls
and the subject changes. Watch for `suppressed  known:` in `sources.log` at that run; if it does not
appear and a fresh `checkout-health:housekeeping:<newdate>` row is filed, the suppression is wrong and
this section is wrong with it.


---

## 44. ROUND 49 — THE 03:07 CLOCK: ONE PENDING PROOF HELD, ONE WAS FALSIFIED

§38 waited on the 03:07 tick for two rows. Both now have an answer, and the log they live in is
`/root/.sms-inbox/sources.log` — `sources-cron.log` is a **0-byte decoy** (last written 2026-10-14);
`run-wake-sources.sh:9` sets `LOG=/root/.sms-inbox/sources.log` itself, so cron's fd 1 is never used.

| §38 row | verdict at 03:07 | evidence |
|---|---|---|
| `cron-targets` guard path | **VERIFIED FIXED** | no `cron-targets` line at all after `02:37` — quiet is its healthy output; the `export CRON_TARGET_GUARD=/usr/local/bin/...` holds |
| `loop-stall` detector | **FALSIFIED — still broken** | `2026-10-18T03:07:01 loop-stall UNUSABLE rc=2: ... /root/bin/kaf-loop-status.py: No such file or directory` |

Both trees are identical (`md5sum /root/bin/run-wake-sources.sh /home/zabz/bin/run-wake-sources.sh`
-> `99380109882666287f2207e8c5b3e36e` twice), so the two-tree theory was wrong; the real cause is
line 117 using `"$HOME/bin/kaf-loop-status.py"`, and **the file exists nowhere**: `/root/bin`,
`/home/zabz/bin`, `/usr/local/bin` all absent, and the estate file search returns no match under any
path. 245 of 245 runs have failed. H3417 recorded this months ago.

## 45. ROUND 50 — `deploy.sh` WOULD HAVE DELETED 710 AND 721 LINES. IT NOW REFUSES.

A fleet child measured the repo copies against the live files. These are **not older snapshots of the
same lineage, they are different lineages**, and repo-only line counts are also non-zero (55/78/6), so
neither side is a superset:

| file | repo | live | live-only lines |
|---|---|---|---|
| `wake-dispatch.sh` | 579 lines, 26,254 B | 1,351 lines, 71,014 B | **710** |
| `wake.py` | 1,280 lines, 54,119 B | 2,036 lines, 95,093 B | **721** |
| `run-wake-sources.sh` | 48 lines | 249 lines | 192 (not installed by deploy at all) |

`install_file()` was `backup -> install`: it copied over the top silently, and `--apply` also writes
`WAKE_PAUSED`, so one command would both regress the dispatcher (dropping `unverified`, absent from
the repo, 44 uses live) **and** stop the queue.

Fixed in `scripts/wake/deploy.sh`: `install_file` counts destination lines the source does not carry
(`grep -Fxv -f "$src" "$dst" | wc -l`) and REFUSES unless `--replace-divergent` says a human read the
diff. Proven against the real `--src`, live files untouched:

```
REFUSED  /root/bin/wake.py holds 721 line(s) that .../wake/wake.py does not have
         src: 1280 lines, 54119 B   dst: 2036 lines, 95093 B
REFUSED  /root/bin/wake-dispatch.sh holds 710 line(s) that .../dispatch.sh does not have
         src: 579 lines, 26254 B   dst: 1351 lines, 71014 B
RESULT: nothing was changed (--dry-run). 11 item(s) would change on --apply. 2 REFUSED as divergent.
```
md5 of both live files identical before and after. Committed `19522934`.

## 46. ROUND 51 — `edit --blocked_on` NEVER HAD THE FLAG. §27 WAS FALSE.

§27 claimed "`edit` CAN NOW CORRECT `blocked_on` (3rd attempt, works)". The implementation does:
`_EDITABLE_FIELDS` (`work.py:701`) lists it, the change-branch (`:754`) compares it, the UPDATE
(`:774`) writes it. But the `edit` argparse never defined `--blocked_on`, so on a throwaway store:

```
$ WORK_DB=/tmp/wt.db work.py edit 167 --blocked_on "TEST" --by auditor
work.py: error: unrecognized arguments: --blocked_on TEST
```

A correct mechanism wired to nothing — inside the sensor that documents that class. Patched by adding
the argument (`120834 -> 121160` bytes, `py_compile` OK), and proven on a throwaway copy:

```
$ WORK_DB=/tmp/wt2.db work.py edit 26 --blocked_on "PROOF-OF-FLAG test" --by auditor
edit-ok {"fields": ["blocked_on"], "id": 26, "note": 32}
$ sqlite3 /tmp/wt2.db "select substr(blocked_on,1,40) from work_item where id=26;"
PROOF-OF-FLAG test
```

## 47. ROUND 52 — THE LEDGER'S BLOCKERS DESCRIBED A WORLD THAT MOVED

Row 547 was **already `resolved`** before this session ("the owner delegated it"), and
`shift-packet.py:97-112` already carries `RESTART-CONTRACT-V1`: a restart is allowed when the item
names HOST, SERVICE and WINDOW, the host is writable, the gate allows, and it is recorded. The gate
agrees: `guard-service-state.sh --host secratary-cloud --op restart` -> `ALLOW ... rc=0`.

So the 12 items "blocked by the contract" were **stating a rule that no longer exists**. A child
triaged all 35 blocked items (bucket counts: 12 owner / 3 human / 8 over-strict rule / 7 stale /
4 mis-filed / 1 unclassifiable) and four of the owner-needing ones have **no queue row at all**
(152, 337, 373, 457) — invisible to him.

Five corrections applied (attempts 1025-1029), each with its own evidence:
- **167 -> dropped**: it is a DUPLICATE of todo item **317** (`Deploy the _db_lock fix and restart
  company-api`), not a restart to authorise. I would have restarted the company API twice for one fix.
- **26 -> blocked on ledger item 317**, naming host/service/window per V1. `systemctl cat company-api`
  -> `Restart=always RestartSec=10`, so an unattended restart self-heals.
- **323, 80 -> DATE GATE, not a person** (both open 2026-10-19); **128 -> vendor recheck 2026-10-21**.
  Left `blocked` on purpose: making a date-gated item `todo` invites a shift to burn itself on a gate.
- Ledger after: `blocked 34` (one newly classified), `dropped 18 -> 19`, `todo 108`.

## 48. ROUND 53 — `I'll f` WAS A ONE-CHARACTER REGEX, AND FOUR MORE DEFECTS AROUND IT

The owner's flagship. `session-sweep.py` filed row 1184 with the reason
`commitment phrase: "I'll f"`. Cause, proven: `COMMITMENT_RE` spells `\bi'll \w` — **exactly one
character** — and `classify()` returned `m.group(0)`, the span, not the sentence. Five fixes, each
with a before/after test on real text:

| # | defect | proof |
|---|---|---|
| 1 | `\w` matches one char | reason `"I'll b"` -> `...I'll bring you the determination once #536 lands...` |
| 2 | reason is the span, not the sentence | same line: 29 of 55 reasons in 7 days were <=7 chars |
| 3 | handoff guard collapsed to "mentions an H-number" (`HANDOFF_WRITTEN_RE` already contains `H\d{4,}`) | prose mentioning `H7071` -> old `already recorded a handoff`, new `interesting=True`; 50 of 77 skips unjustified |
| 4 | fenced drafts counted as commitments | straight-apostrophe draft: old `commitment phrase: "I'll f"`, new `False` |
| 5 | typographic apostrophe missed entirely | `I’ll` -> old `False`, new `True` |

`python3 /root/_test_session_sweep_fix.py` -> `RESULT: PASS 0 case(s) failed`, 5 cases. The patch
refuses if any anchor is not found exactly once and re-parses before writing. Backed up as
`session-sweep.py.bak-sweepfix-20261018`. **First cron run on the new classifier: 04:07.**
Still open (needs a design decision, not a patch): `closing question` routes to a `resume` wake when
11 of 12 are the assistant asking HIM, so those belong in `owner_decision_queue`.

## 49. ROUND 54 — THE CONSERVE TIER PINNED A MODEL THAT DOES NOT EXIST

`wake_budget.py:168` returned the literal `"deepseek-flash"`. The live catalog
(`/root/.sms-inbox/model-catalog.json`, 35 ids) holds `deepseek/deepseek-v4-flash` and
`deepseek/deepseek-v4-pro` and **no bare `deepseek-flash`** — and the resolver validates against the
catalog, so every shift would fail loud at exactly the moment the balance dropped. Measured after the
one-line fix: `lane_for("conserve") = deepseek/deepseek-v4-flash`, `in catalog: True`. This is the
standing rule about never hardcoding a model, still true in the file that chooses one.

## 50. ROUND 55 — THE OWNER CHANNEL, MEASURED, AND IT IS NARROWER THAN IT LOOKS

Counted by me, not taken from a child, `/root/authority.db`:

```
sms_log, outbound to +18483897895, last 7 days:
  delivered 2 | failed 5 | queued 35 | sent 8 | suppressed 23
```

And the reconciler **works** — at `03:30:03` it flipped one row:
`SM4c762dfdb0c0b9d4 queued -> delivered  to=+18483897895`. So the right sentence is not "the pipe is
broken", it is **"delivery is mostly unconfirmed, and 41 rows can never be confirmed"**:
`select count(*) ... status="queued" and twilio_sid<>"" and created_at < datetime("now","-48 hours")`
-> **41**, because the reconciler runs with `--hours 48` and a row older than that is never revisited.
75 queued rows carry a SID; 41 of them are permanently outside the window.

Two more, both from a child and both consistent with the counts: 554 of 559 reminders are delivered to
`delivery_channel='dashboard'`, whose consumer (`personal_ops.py:1008`) enqueues an owner message at
`status="held"` — so a reminder is marked `sent` while the message that would show it is held
(reminder 667 -> queue row 2632 `held`). And punctuality is not "to the second": `318` within 60 s,
`402` within 5 min, **48 delivered more than a day late**, of 568.

The liveness line the owner asked for in row 549 exists in exactly one file and is **invoked by
nothing**: `scripts/owner-attention-digest.sh` prints
`Dispatcher: last ran Nm ago` / `the wake system is NOT running, so nothing can revive a session`,
`crontab -l | grep -c owner-attention-digest` -> `0`, and its output dir
`/home/zabz/secretary-attention-digest` does not exist. The dispatcher is in fact alive
(`/home/zabz/.sms-inbox/wake-heartbeat` = `2026-10-18T03:22:03+00:00`).

## 51. ROUND 56 — SELF-EVOLUTION: THE PIPELINE IS DEAD, THE LOOP IS ALIVE

Four verdicts, each with the number that decided it:

| claim | verdict | the number |
|---|---|---|
| evolution cannot improve itself (gate/measure/revert) | **TRUE** | `CODE_EDIT_AUTO_APPLY=false`; `evolution_verification` 25 rows all `proposal_id=0`, newest `2026-07-04` (106 days); `evolution_verifier.py:421` writes `failed` and returns — no revert exists, though its docstring promises "auto-rollback" |
| pain-checks closer muted | **TRUE, twice** | the installed cron decodes to `pain-check.py --write-status`, `--close` appears nowhere; and the flag's subject is count-bucketed (`45 // 10 * 10 = 40`) so it dedupes onto a row already at `attempts 2/2` |
| wake-cost maps release->session on release id only | **TRUE on mechanism, FALSE on the figure** | key is `re.match(r"wake-session-(\d+)-", ...)` (`:527`); measured today `7 of 29` rows come from a multi-sidecar release, not "3 of 12" |
| no capability tiers | **PARTLY** | two states, not a ladder — and the conserve state pinned a non-existent id (round 54) |

**Does it improve itself? Yes — through the wake loop, not the pipeline.** 13 commits by
`Secretary Autopilot` in 7 days, and today `046dc0f 2026-10-18 01:42:57 Daniel decision-queue-stale:
honor deferred_until`, which the release closed two seconds after committing. The purpose-built
propose->gate->measure->revert machine has applied nothing since 14 September and cannot roll back
what it applies.

## 52. ROUND 57 — THE VERIFICATION LEDGER, UPDATED

| change | proven by | state |
|---|---|---|
| `deploy.sh` divergence guard | `--dry-run` with real `--src`: 721 / 710 lines refused; live md5 unchanged | **VERIFIED** |
| `work.py edit --blocked_on` | throwaway store: `edit-ok {"fields": ["blocked_on"]}` and the value read back | **VERIFIED** |
| five ledger blocker corrections | `attempt-recorded` 1025-1029; `blocked 34` | **VERIFIED** |
| session-sweep classifier (5 defects) | `_test_session_sweep_fix.py` 5/5 PASS; before/after reasons quoted | **VERIFIED in isolation** |
| session-sweep in cron | next tick **04:07** | **PENDING** |
| `wake_budget` conserve lane | `lane_for("conserve")` in catalog: True | **VERIFIED** |
| `loop-stall` retirement | `bash -n` OK; marker pinned to `${STATE_DIR:-/root/.sms-inbox}` | **PENDING (04:07 tick)** |
| `cron-targets` guard | quiet from 02:37 onward | **VERIFIED** |
| settled-row guard | cannot be triggered on demand | **UNPROVEN** |
| a real reminder delivered | needs one created by a shift, watched to `sent` | **UNPROVEN** |

**NOT DONE, and deliberately:** the 41 permanently-`queued` SMS rows need the reconciler's window
widened from `--hours 48`; that value lives in a base64-encoded crontab line, so it is a careful edit
rather than a sed. The evolution revert (`evolution_verifier.py:428`) is a real change to a service
that has been dormant for 106 days and deserves its own round with a planted regression.

---

## 53. ROUND 58 — A CORRECTION TO §50, AND THE REAL CAUSE: THE RECONCILER WRITES THE MIRROR, NOT THE SOURCE

**§50's number was wrong and this section replaces it.** §50 said 41 outbound rows were "permanently
outside the reconciler's 48-hour window". Both halves were wrong, and the way they were wrong matters.

**The count.** `created_at` in this table is ISO-8601 with a `T` and an offset
(`2026-10-11T14:00:48.148242+00:00`), while `datetime('now')` renders `2026-10-18 03:43:00` with a space.
`T` is ASCII 84 against space 32, so a string comparison silently mis-orders every row on the boundary
date. Measured side by side:

```
created_at <  datetime('now','-48 hours')   -> 41   (WRONG -- string compare)
julianday(created_at) < julianday('now','-48 hours') -> 65   (correct; oldest 2026-09-29T19:38:31)
```

**The mechanism.** Widening the window changed nothing, which falsified the window theory outright:
`reconcile-sent-status.py --hours 720` (dry) -> `unsettled outbound rows in the last 720h: 2`, and both
were synthetic test SIDs answering HTTP 404. The reason is line 38 and lines 113-114: the script opens
`INBOX = ~/.sms-inbox/inbox.db` and reconciles **`messages`** — a mirror. The owner's texts live in
**`/root/authority.db` -> `sms_log`**, which has no `messages` table at all. So delivery truth is written
to one store and read from another, and nothing propagates back.

Proven on one message, two truths:

```
sms_log   (what owner_attention and the ps_* tools read):  4276  queued   2026-10-17T14:22:32
messages  (what the reconciler updates), same SID:          delivered
of the 65 stale queued SIDs, 50 exist in the mirror -> 50 rows where the answer is already known
and is being withheld from the store that asks the question.
```

**So §50's real finding stands and gets sharper:** the channel does not mis-deliver, it *under-reports*,
and the fix is a write-back from `messages` to `sms_log` keyed on `twilio_sid` — not a wider window. The
15 SIDs absent from the mirror are a second, separate question (they may predate the mirror).

**The lesson, which is the estate's oldest:** a number produced by a string comparison is not a
measurement. §50 broadcast 41 into this document and into H7337; the correct figure is 65, and the cause
was not the one the number suggested. Print the raw value beside the predicate, and when two stores
disagree about one row, ask which one the consumer actually reads.

---

## 54. ROUND 59 — P7307 CLOSED: THE WRITE-BACK EXISTS, IS SCHEDULED, AND SETTLED 52 ROWS

§53 named the defect and deliberately did not fix it. This round fixes it, and the fix is a new script
rather than a widening of anything.

`/root/bin/sync-sent-status-to-app.py` carries a SETTLED status from the mirror (`inbox.db.messages`) into
`sms_log`, keyed on `twilio_sid`, outbound only. It refuses to overwrite one settled status with a
DIFFERENT settled status: two stores disagreeing is a conflict for a human, not a guess. Dry-run by
default; `--apply` is the only write.

**Proven on a throwaway pair of stores first** (`/root/test-sync-sent-status.py`, 7 rows covering every
branch) — `RESULT: PASS 0 failure(s)`, and the second `--apply` wrote 0, so it is idempotent:

```
scanned=6  to_change=2  conflicts=1  already_same=1  no_mirror_row=1  mirror_not_terminal=1
CONFLICT id=4 SM_D: sms_log=delivered mirror=failed (left alone)
RESULT: wrote 2 status update(s); 1 conflict(s) left for a human
```

**Production, before and after, from the store itself:**

```
BEFORE: suppressed=2036 failed=1039 sent=303 delivered=290 queued=79  undelivered=15 pending=3
AFTER : suppressed=2036 failed=1039 sent=303 delivered=342 queued=27  undelivered=15 pending=3
RESULT: wrote 52 status update(s); 37 conflict(s) left for a human
```

The SID from §53 (`SM8dea23086e7e9f203aadb4134ecaf70c`) now reads `delivered` in `sms_log` where it read
`queued`. Scheduled as `5,15,25,35,45,55 * * * *` through `cron-wrap.sh sync-sent-status` (crontab 243 ->
244 lines, one matching line; backup at `/root/crontab.bak-sentsync-20261018`), i.e. five minutes after the
reconciler so it always copies a fresh reading. Run once in cron's own environment: `rc=0`,
`wrote 0 status update(s)`.

**Two residuals, both measured, neither guessed:**

1. **All 27 rows still `queued` have NO mirror row** — `select count(*) ... left join messages` -> `27|27`.
   They can never be settled from the mirror; they need a direct Twilio status query against `sms_log`
   itself. That is the next change, and it is a different one.
2. **37 conflicts, every one `sms_log=failed` against `mirror=delivered`.** Left alone on purpose. The
   pattern is uniform enough to be systematic rather than random, which suggests `sms_log.failed` is being
   written by something other than Twilio's verdict — worth one round on its own before anything trusts
   `failed` for a retry decision.

**A note on the shape.** The reconciler was not broken and its window was never the problem (§53). The
missing piece was one direction of a two-store hop, and nothing anywhere reported that the hop was one-way
— each side looked healthy. That is the same class as the rest of this document, and the reason a status
field is now checked by re-deriving it rather than by trusting the row.

---

## 55. ROUND 60 — THE API IS KILLED TEN TIMES A DAY AND NOTHING WATCHED MEMORY

This started as "close item 317" and turned into the most consequential finding of the session.

**Item 317 is done, with all four DoD clauses measured:** `grep -c _DB_LOCK_WAIT_S
/opt/company/app/database.py` -> `3`; `curl /v1/models` -> `200`; `text-health.py` ->
`RESULT: 15 check(s), 0 FAIL`; `journalctl -u company-api --since '-10 min' | grep -c '_db_lock
contended'` -> `0`; and `database.py` mtime `2026-10-15T15:13:40` predates the running process, so the
deployed code IS the fixed code. Attempt 1033. Item **26 unblocked** in the same breath, because the
restart it depended on has happened.

**The restart was not a shift's.** `journalctl` says `company-api.service: Scheduled restart job, restart
counter is at 2` — systemd restarting a unit that had just died. What killed it:

```
Oct 18 03:30:56  company-api.service: The kernel OOM killer killed some processes in this unit.
Oct 18 03:30:58  company-api.service: Failed with result 'oom-kill'.
Memory cgroup out of memory: Killed process 219223 (python)
  total-vm:22874432kB, anon-rss:12519032kB, UID:0
```

`anon-rss` 12,519,032 kB against `MemoryMax` 12,884,901,888 bytes. **Ten `oom-kill` results in 24 hours**,
four of them inside two hours — 01:21:12, 01:42:51, 02:21:49, 03:30:58. This is not the box running out of
memory; it is the API filling its own cgroup. At the time of measurement it sat at ~4.7 GB and was **flat
over 80 seconds** (`03:50:39 4734685184` ... `03:51:59 4684701696`), so the growth is EPISODIC and follows
work, and no linear leak rate is claimed — an earlier 52 MB/min figure was two points 60 s apart and is
withdrawn before it reached a recommendation.

Each kill drops every in-flight request, and abandoned threads keep their SQLite locks — this estate's
documented `database is locked` mechanism. A share of the 114 failed wake rows is plausibly this, which
cannot be measured from the store and is therefore stated as a suspicion, not a cause.

**The gap this exposes: nothing in the estate watched memory.** Disk has had a source since two near-fills
(`sources/disk-space.py`); memory had none, so ten restarts a day were invisible.

### The new source, and the defect it nearly shipped with

`sources/memory-pressure.py` flags on (a) any `oom-kill` for the unit in a 2 h window — day-bucketed
subject `memory-oom:<day>`, priority **high**, because an OOM kill is an outage that has already happened;
(b) `MemoryCurrent` at or above 80 % of `MemoryMax`; (c) swap at or above 90 %. Tested on all three
contract cases:

```
real condition  -> flagged memory-oom:20261018          (row 1186, high, filed)
healthy case    -> (dry-run: 0 finding(s)) quiet        (tiny window, thresholds at 99.9)
bogus unit      -> memory-pressure: SIGNAL UNREADABLE -- unit no-such.service does not exist  rc=1
```

**The third case failed on its first run and that is the important line in this section.** `systemctl show
no-such.service -p MemoryCurrent` exits **0** and prints an empty line, so the source reported `quiet` for a
unit that does not exist — the exact defect §1 of this document is about, in a file written to catch it. The
fix is `_flag.unit_exists()` plus a refusal when `MemoryCurrent` reads 0 for a running service. A written-up
pattern does not protect you from writing the pattern; only the negative test does.

Installed by adding `memory-pressure` to the source loop in `run-wake-sources.sh` (`bash -n` OK, one
occurrence, backup `run-wake-sources.sh.bak-memsrc-20261018`), and the leak itself filed as **ledger item
559** (housekeeping, priority 2) so a shift owns it rather than a log line owning it.

### Also this round: the evolution pipeline records every measurement against proposal 0

`app/evolution.py:1136` called `create_verification(proposal_id=0, ...)` — a **literal zero** — while
`proposal_id` was in scope as the validated non-empty string used for the evolution log one line above. That
is why all 25 rows in `evolution_verification` have `proposal_id = 0` and why a revert could not have worked
no matter what code sat at `evolution_verifier.py:421`: **there was nothing to revert to.** Patched to
`proposal_id=int(proposal_id)`, backup `/root/evolution.py.bak-proposalid-20261018`, `py_compile` OK.

**Labelled honestly: this branch is dormant.** It only runs when `auto_applied` is true, which needs
`CODE_EDIT_AUTO_APPLY=false -> true` at `/opt/company/.env:122`. The fix is correct and it cannot be proven
by anything today. Revert is the next round, and auto-apply comes after a revert has been proven by a
planted regression — in that order, because enabling self-editing ahead of rollback is how this estate would
lose a working system to a confident one.

---

## 56. ROUND 61 — THE REVERT EXISTS AND IS PROVEN ON A PLANTED REGRESSION

§51 recorded "revert does not exist" as TRUE and §55 fixed its prerequisite (the literal `proposal_id=0`).
This round closes it.

**Why it could not have worked before, stated precisely.** Three facts, each measured:
1. `code_self_edit` has always snapshotted every file it applies and **returned `snapshot_id`**; 50 snapshots
   sit in `/opt/company/data/code_snapshots` as `{id,label,created_at,files:{rel:{content,sha256}}}`.
2. `evolution_verification` had **no column** able to name a snapshot, and `create_verification()` never
   received one.
3. The regression branch at `:421` therefore recorded `status='failed'` and returned.

So the machinery to revert existed and had no target. That is why "add a revert" would have been the wrong
first move in §51, and why `proposal_id` had to be fixed first.

**What changed** (commit `30b3cb51e` in `/opt/company`): `evolution_verification.snapshot_id` (additive
`ALTER`, idempotent); `create_verification(..., snapshot_id=None)` stores it; `app/evolution.py` passes
`apply_result.get("snapshot_id")`; `_restore_snapshot()` restores every file in a snapshot; and
`record_measurement()` now **restores first, then records** — `status='reverted'` with the file list, or
`failed` with `REVERT FAILED: <why>` or `NO snapshot_id on this row, so nothing was restored`.

**It refuses rather than restoring nothing.** A revert that silently does nothing would let a row read
`reverted` over code that is still regressed, which is worse than no revert. `_restore_snapshot` raises on a
missing snapshot, an empty file set, and any path that resolves outside the checkout.

**Proven on a planted regression, in a throwaway checkout** (`scripts/wake/tests/test_evolution_revert.py`):

```
restore returned: ['app/thing.py']
file now reads : "def f():\n    return 'GOOD'\n"        <- was REGRESSED
PASS missing snapshot raises FileNotFoundError
PASS traversal refused: snapshot evil: ../outside.py escapes the checkout
PASS empty snapshot refused: code snapshot empty holds no files
PASS no .revert.tmp debris left behind
RESULT: PASS  0 failure(s)
```

**Labelled honestly, again: this branch is dormant.** It runs only when `auto_applied` is true, which needs
`CODE_EDIT_AUTO_APPLY=true` at `/opt/company/.env:122`, and that is still `false`. What is proven is the
restore function and its refusals under a planted regression; what is NOT proven is `record_measurement`
completing a live revert, because forcing that in production would rewrite `app/` files from a snapshot as a
test. The next round that turns auto-apply on must prove the full path with a deliberately regressive
proposal on a branch, never on master.

**A note on my own reporting.** The patch printed "20659 -> 22659 bytes"; the file was 21,997 bytes on disk.
`len()` counted *characters* — the file is full of box-drawing glyphs at 3 bytes each. The patch was correct
and the label was wrong, which is the same defect as a wrong number anywhere else, so it is recorded rather
than quietly fixed. **03:57Z check: the 04:07 tick had not yet run, so the `loop-stall` retirement and the
session-sweep classifier remain PENDING.**

---

## 57. ROUND 62 — THE 37 "CONFLICTS" WERE ONE EXPLAINED CLASS AND ONE WRONG RULE

§54 left 37 rows as "conflicts for a human" and 27 rows unconfirmed. This round resolves the first and
names the cause of the rest.

### The 37 were a 2026-08-30 relabel, not a disagreement

Every one of them is `sms_log=failed` against `mirror=delivered`, and every one carries the same
`error_message`:

    S3b 2026-08-30: Twilio outbound retired (no from-number configured; owner SMS kill-switched;
    LPT customer SMS = Dialpad only). Message never delivered; kept as audit record.

56 rows carry that label. On 2026-08-30 Twilio outbound was retired and every outstanding message was
relabelled `failed` with that note — while the mirror kept **Twilio's own verdict**, which for 37 of them is
`delivered`. So the two stores disagree because one describes a *retirement* and the other a *delivery*.
Neither is a bug, and the sentence "Message never delivered" is inaccurate for the 37 that were delivered
before the retirement.

That is not something a write-back should resolve by choosing a winner. It is a class with a written
explanation, and a report that shows 37 unexplained conflicts on every run is precisely how an operator
learns to ignore the report. So the script now **names** it: `retired_relabel`, counted and printed, never
overwritten.

### And one of the 37 was my rule being wrong, not the data

After the class was named, exactly **one** row remained:

    CONFLICT id=4139 SMe8a017b4306a52ce3c33b41b93908685: sms_log=sent mirror=delivered

`sent -> delivered` is an **upgrade**, not a disagreement — Twilio's status flows
`queued -> sent -> delivered|failed|undelivered`. My rule treated any two different terminal states as a
conflict, which buried a real delivery behind a label that made it look unresolved. Corrected: that pair is a
change, and it applied.

### Measured, before and after, from the stores

```
dry run, before the two fixes: scanned=754 to_change=0  retired_relabel=36 conflicts=1 already_same=357
after --apply               : scanned=754 to_change=1  retired_relabel=36 conflicts=0 already_same=357
sms_log outbound BEFORE: suppressed=2036 failed=1039 delivered=342 sent=303 queued=27 undelivered=15
sms_log outbound AFTER : suppressed=2036 failed=1039 delivered=343 sent=302 queued=27 undelivered=15
RESULT: wrote 1 status update(s); 36 known-class row(s) named; 0 conflict(s) left for a human
```

Row 4139 reads `delivered` with `updated_at 2026-10-18T04:00:53`. The throwaway gate grew two cases (the
S3b row must be *named*, the `sent -> delivered` row must be *changed*) and passes: `RESULT: PASS 0
failure(s)` over 9 rows, second apply writes 0.

### The 842-row failure class nobody had named

While reading `failed` I found the dominant historical cause, which is not Twilio's verdict at all:

    HTTPSConnectionPool(host='api.twilio.com', port=443): Max retries exceeded ... 841 rows
    NameResolutionError: Failed to resolve 'api.twilio.com' ([Errno -3] Temporary failure in name resolution)

842 rows, **newest 2026-10-06T13:58:40**, and `getent hosts api.twilio.com` resolves fine now. So the
authority could not resolve Twilio for a window that ended twelve days ago, every send in that window was
recorded `failed` by the *sender's* network stack rather than by Twilio, and nothing said so. Not live, and
therefore not urgent — but it is the reason `failed` in this table cannot be read as "Twilio rejected it", and
that is worth knowing before anything builds a retry policy on the column.

**Still open: 27 rows with no mirror row** (`no_mirror_row=360` overall, `27|27` of the queued ones). They need
a direct Twilio status query against `sms_log`; the mirror cannot settle them and neither can a wider window.

---

## 58. ROUND 63 — THE RECONCILER WAS ASKING THE WRONG TWILIO ACCOUNT

§54 and §57 left 27 rows unconfirmed because they have no row in the capture mirror. The mirror cannot
settle them, so the only remaining source is the provider. This round asked it, and the answer was not what
any of the counts implied.

### Two accounts, and only one was ever asked

`reconcile-sent-status.py` builds one URL from `TWILIO_ACCOUNT_SID`. Measured on one of the 27 sids:

```
MAIN   creds present: True   acct tail: 71b6   -> HTTP 404
FAMILY creds present: True   acct tail: f292   -> HTTP 200  status=delivered from=+17328009174 to=+18482245096
```

The row was **delivered**, by the **family-chat account**, while every reconciler in the estate asked the
main account and got "not this account's message". That is why the rows were unconfirmable, and it is not an
age problem: their `created_at` range is `2026-10-14 .. 2026-10-18`, i.e. the last four days.

### The result, from the store

New `/root/bin/reconcile-sms-log.py` — asks each account in order, reports which answered, never filters on a
date (age is the point; the existing reconciler's own comments record how a string date comparison once
selected 1838 of 1914 rows), and skips any row without a real `SM...` sid.

```
unsettled outbound rows to ask Twilio about: 23
  4240   SM1a9e36203e88b80625eb4f42fa9fe5d2 queued -> delivered (answered by family)
  ...
to_change=23  already_settled=0  unanswered=0
sms_log outbound AFTER: suppressed=2036 failed=1039 delivered=366 sent=302 undelivered=15 queued=4 pending=3
RESULT: wrote 23 status update(s); 0 unanswered
```

**22 of the 23 were messages the database insisted had not been delivered.** `queued 27 -> 4`,
`delivered 343 -> 366`, and the sid from the two-account test (`...c76d`, row 4155) reads `delivered`.

**The first `--apply` wrote nothing**: `sqlite3.OperationalError: database is locked`. The authority database
is written continuously by company-api, and one lock lost the whole batch because the script committed once at
the end. Fixed with `PRAGMA`-level patience expressed as code the reader can see: per-row commit and a
retry-with-backoff (`_write_status`, 6 attempts), so a lock costs one row instead of the run. That is the same
pressure the ten OOM kills a day produce (§55), arriving in a different costume.

Scheduled `12,42 * * * *` via `cron-wrap.sh reconcile-sms-log` (crontab 244 -> 245, one match, backup
`/root/crontab.bak-smsrecon-20261018`).

### The four that remain, and why they are not a defect to fix here

```
id 1038, 1039, 1040, 1044   twilio_sid = ''   created_at 2026-09-29
```

They have **no sid at all**, so they never became a Twilio message and no API can have an opinion about them.
Their `queued` status is wrong for a different reason than the other 23 — something failed between "record the
intent" and "create the message" — and rewriting it from here would be inventing a verdict. Counted, explained,
left for the sender to fix.

### A correction to §50

§50 reported `delivered 2, failed 5, queued 35` over seven days and I read that as "delivery is mostly
unconfirmed". The count was right; the conclusion was too dark. **At least 23 of those queued rows were
delivered**, and the record could not say so because nothing asked the second account. The honest sentence is
"the record could not see the delivery", not "the delivery did not happen" — and the difference between those
two sentences is the whole reason this document exists.

---

## 59. ROUND 64 — THE 04:07 CLOCK: `loop-stall` VERIFIED, AND THE ARCHIVE CHECK WAS READING A DEAD COPY

The tick that §52 and §56 both waited on finally ran at **04:07:01Z**, and it settles two rows.

### Verified by the clock

```
2026-10-18T04:07:01+00:00  loop-stall  RETIRED: no detector at /root/bin/kaf-loop-status.py
                                       on this host (announced once; this source is silent until one exists)
$ ls -l /root/.sms-inbox/.loop-stall-retired
-rw-r--r-- 1 root root 0 Oct 18 04:07 /root/.sms-inbox/.loop-stall-retired
```

Announced once, marker written, and no `UNUSABLE` line this hour. Before this the source had printed
`UNUSABLE rc=2` on **245 of 245** runs. The signal is not deleted — if a detector ever appears at that path
the source runs it.

`memory-pressure` also appears in the loop for the first time and behaves:

```
2026-10-18T04:07:01+00:00  memory-pressure  (memory-oom:20261018: suppressed:cooldown)
```

A dedupe against the row it filed at 03:53, which is exactly right. `session-sweep` is still
`(daily cap reached: 3 filed 2026-10-18)`, so its new classifier has still not run — the cap resets at
00:00 UTC and that is the next honest proof point, not a reason to raise the cap.

### The tick also exposed a live defect, and it is the fifth of one class

```
dormant-handoff  archive-check UNUSABLE (Unreadable: freshness checker refused (its inputs could not be read):
  {"ok": false, "refused": true,
   "error": "could not read dsh_sessions: no such table: dsh_sessions"})
```

`check-dsh-freshness.py:68` defaulted `DSH_ARCHIVE_DB` to
`/home/zabz/personal-secretary-mvp/data/secretary.db` — a **1.9 MB copy that does not contain
`dsh_sessions`** — while the live table, 8,415 rows, sat in `/root/authority.db` on the same host. So the
check that guards whether session archives still have a copy was refusing to answer, on every run, in a
sub-line of a source whose main output was `quiet`.

Fixed the same way `_flag.app_db` was: prefer `/root/authority.db` when it exists, keep the old path as the
fallback, and let an explicit env var still win. Verified with no override at all — the checker now reports
per-machine freshness (`desktop-fgv6kmh shipped 0.1 h ago`, `zabz-tech shipped 0.0 h ago`, and so on).

This is the **fifth** wrong-store/path default in this class: `_flag.app_db`, `cron-targets`, dormant-handoff's
repo path, `loop-stall`'s missing detector, and now the archive checker. Every one of them printed something
that looked like a reading.

### What the now-working checker says, recorded as a QUESTION and not a diagnosis

```
PROBLEM secratary-cloud cannot tell whether this host is shipping:
        no shipper cursor at /root/.dsh/dsh-archive-state.json
```

Supporting measurements, taken once, not yet interpreted:

```
dsh_sessions by source_machine: zabz-tech 4927 | zabz-yoga 2092 | secratary 525 (frozen 10-11)
                                | zabz-tech-linux 525 | lakewooechsmini 185 ... and NO secratary-cloud row
/root/.dsh/sessions           : 6 trees, 226 MB, newest --home-zabz-phone-- (544 entries, 2026-10-18 00:08)
```

So the authority runs or holds DSH session data that appears in **no** `dsh_sessions` row under its own name,
and has no shipper cursor. **That is not yet a finding of loss**, and AGENTS.md is explicit about the last
agent who declared data loss from a path it had not followed down. The two candidates are (a) these are
originals that nothing ships, or (b) they are a staging copy of sessions already archived under their real
`source_machine`. Telling them apart is one round of work and it is the next one, because if it is (a) then a
quarter of a gigabyte of reasoning exists in exactly one place.

---

## 60. ROUND 65 — THE 226 MB IS SAFE; THE PROJECTION STOPPED AT THE CUTOVER

§59 left this as an explicit question: 226 MB of session trees on the authority, no `secratary-cloud` row in
`dsh_sessions`, and a checker complaining about a missing shipper cursor. It is answered, and the answer is
**not loss**.

### What is actually missing

Whole-tree comparison, not sampling:

```
session dirs in /root/.dsh/sessions/--home-zabz-phone-- : 542
archived ids in dsh_sessions                          : 8415
MISSING from the archive                              : 93
mtime of the 93: 10-11 x1 | 10-12 x42 | 10-13 x7 | 10-14 x13 | 10-15 x21 | 10-16 x7 | 10-18 x2
```

**All 93 are dated 2026-10-11 or later**, and `dsh_sessions` has no `secratary` row after
`2026-10-11T03:32:42`. 10-11 is the cutover day. The older 449 sessions in that tree ARE archived, attributed
to `secratary`.

### Why, and the one check that decides whether it matters

`push-dsh-sessions.mjs` is a **client-side scheduled task** that runs on the machine holding the sessions. The
machine is `secratary` — the FROZEN rollback anchor, `cron` masked on purpose. So the pusher stopped at the
cutover and nothing replaced it. That is precisely the trap AGENTS.md §1 records from 2026-10-09: *"Never let
a client-side scheduled task be the only thing that ships"* — measured that time as a task reporting
`LastTaskResult=0` every hour for 21 days while the archive stood still.

But the **bytes** are a different path, and it is driven from the authority:

```
arrival where rel_path like '%home-zabz-phone%':  machine=secratary  count=632  max(received_at)=2026-10-18T01:23:01
```

All four sampled "missing" ids return `1` in `arrival`. So the raw archive holds every one of them, and what
stopped is only the **parsed projection** — the searchable, trainable form. Nothing was lost; something became
harder to read.

### Why it is filed rather than run tonight

The pusher supports exactly the override this needs — `DSH_HOME` and `DSH_ARCHIVE_MACHINE` — so it can be run
*from* the authority against the staged copy and attribute the result to `secratary`. Dry run:

```
would ship: 618 session(s), 216738 new row(s), 912018 KB
```

That is a heavy write job against the live company database, at 04:15, on a 15 GB box whose API is OOM-killed
ten times a day (§55). `estate-systems` says plainly not to run a corpus scan on the authority. So it is
**ledger item 561** (housekeeping, priority 2) with a DoD that names the env, requires a memory ceiling, and
requires `count(*) where source_machine='secratary'` to exceed 525 afterwards — and the DoD was corrected once
already because the first version said `DSH_ARCHIVE_MODE` instead of `DSH_ARCHIVE_MACHINE`, which a shift would
have followed literally and failed.

**The shape worth remembering:** two paths for the same data, one driven from the authority (kept working
through the freeze) and one from the frozen host (silently stopped). A checker on the authority reported the
symptom as "cannot tell whether this host is shipping", which pointed at the destination instead of at the
missing pusher.

## 61. ROUND 66 — A FIXED SENSOR IMMEDIATELY SHOWED A WRONG REMEDY

The moment `check-dsh-freshness.py` could read its table (§59), `dormant-handoff` filed a real finding again —
`dormant-archive:20261018`, *"secratary: local work has sat unshipped for 110 min - the shipper is not
sending"*. Its own prompt then told the reader to fix it, and both instructions were wrong:

1. **"The authoritative store is `secretary.db` via `POST /api/v1/owner/dsh-sessions/ingest`."** It is not.
   The authoritative store is `/root/authority.db`, table `dsh_sessions` — a `secretary.db` copy is the exact
   thing that made this source refuse for weeks.
2. **"Fix the CAUSE"**, for a machine whose shipper is stopped **on purpose**. `secratary` is the frozen
   rollback anchor; starting its cron is the incident AGENTS.md §5 records (5,129 rows written into the anchor
   and a rollback point that is no longer clean).

Patched to say what is actually true and what is actually allowed: read `settings/machines/host-posture.tsv`
FIRST; for a frozen host the shipper is *supposed* to be stopped, its bytes still arrive because the authority
pulls them, only the parsed projection stops, and that is filled from the authority as **ledger item 561**
with `DSH_HOME` + `DSH_ARCHIVE_MACHINE` under a memory ceiling — because the dry run measured 216,738 rows.

**Why this is its own section rather than a footnote.** A monitor that has been silent for weeks comes back
with an instruction nobody has reviewed since it was written, at the moment it is most likely to be followed.
The estate's pattern is usually "the monitor measures nothing"; this is the sibling — **the monitor measures
correctly and prescribes harmfully**. Both are cured by reading the remedy as carefully as the reading.

---

## 62. ROUND 67 — CAPABILITY TIERS EXIST NOW; UNTIL TODAY PRIORITY WAS INVISIBLE TO THE MODEL

The last named item in the brief that was still only half-done. §51 recorded "no capability tiers" as
PARTLY TRUE, and round 54 fixed only the broken literal in the one lane that existed. This round adds the
ladder.

### What was true before

`wake-dispatch.sh` read exactly one input to choose the seat model: the **balance tier**.

```
LANE=${WAKE_BUDGET_LANE:-}            # empty unless tier != ok
LANE_ARG=" -Model \"$LANE\""          # carried to wake-run.ps1 -> WAKE_AGENT_MODEL -> resolver
```

So a customer-facing critical repair and a routine tidy-up were handed the same model, and `PRIORITY` — which
the dispatcher has known all along (`:820`, `:835`) — was never consulted.

### The ladder, and why it is shaped this way

Measured distribution from the wake store: **4 high vs 25 normal** releases in a day (all-time 230 high, 916
normal, 37 low). A release costs 0.05-0.07 USD, so upgrading four of them is cents against a 67.36 USD daily
ceiling — while a failed high-priority row costs a whole shift and re-files. The balance lever still wins
whenever the tier is not `ok`: money pressure outranks capability.

**The id is resolved from the live catalog, never a literal.** Preference chain
`deepseek/deepseek-v4-pro` -> `deepseek-v4-pro` -> `secretary-smart`, tested against
`model-catalog.json`; if none is listed the lane stays EMPTY and the default seat is used. That is the
standing rule (`journal.py show L1606`: every live AI call failed for a week behind a deterministic
fallback), and this estate has already had a lane pin a model id that did not exist (§49).

### Proven by running the shipped block, not by reading it

Executed the exact lines in a subshell with each state:

```
PRIORITY=high    -> LANE=[deepseek/deepseek-v4-pro]  LANE_ARG=[ -Model "deepseek/deepseek-v4-pro"]
PRIORITY=normal  -> LANE=[]                          LANE_ARG=[]
tier=conserve + PRIORITY=high -> lane stays deepseek/deepseek-v4-flash, reason=balance
```

Catalog resolver, all three states: real catalog -> `deepseek/deepseek-v4-pro`; catalog without the strong ids
-> `(none - no pin)`; unreadable catalog -> `(none - no pin)`. An absent catalog cannot make it guess.

`wake-dispatch.sh` `bash -n` clean after the edit (70994 -> 72840 chars, backup
`wake-dispatch.sh.bak-ladder-20261018`).

**And the choice is now visible**, which it never was: the dispatcher appends to
`~/.sms-inbox/wake-lane.log`

```
2026-10-18T04:17:44+00:00 wake #9999 priority=high lane=deepseek/deepseek-v4-pro reason=capability:high-priority
2026-10-18T04:17:44+00:00 wake #9997 priority=high lane=deepseek/deepseek-v4-flash reason=balance
```

A lane that cannot be read from the store is a lane nobody can audit; "the cheap lane is used when balance is
low" was unverifiable until this line existed.

**PENDING, and a clock owns it:** the first real high-priority release must show
`reason=capability:high-priority` in `wake-lane.log` AND the shift must actually run under that model (the
resolver validates against the catalog and fails loud if it does not). Check with
`tail -5 ~/.sms-inbox/wake-lane.log` and `wake.py list --state done` for a high row.

**Not done, deliberately:** `deepseek-r1-0528` is a reasoning model in the same catalog and may be the better
seat for diagnosis-heavy rows, but nothing here has measured its quality or cost per shift. Adding it on
intuition would be the same mistake as picking a model by name.

### 62a. CORRECTION — the three lane-log lines above are MY VERIFICATION, not a live proof

Appended at 04:21Z, before anyone could read §62 as a live verification. The three lines in
`wake-lane.log` carry ids **9999, 9997 and 1** — all three are the standalone runs I made to prove the
block, not releases. `wake #1` is the giveaway, since real ids are four digits and climbing.

**The ladder has NOT yet been exercised by a real release.** At 04:20:59Z the one pending high-priority row
(`wake #1177`, `odq-answer-open:69`) was still `new`, because the fan-out was already carrying other work.
So §62's behaviour is proven **by running the shipped block in isolation**, and the live proof remains
pending exactly as stated there — but with the additional warning that a log line is only evidence if you
check the id against the store.

This is the same trap as §50's wrong 41 and §57's "conflict": a reading that looks like confirmation and is
actually the instrument's own footprint.

### 62b. AND A SECOND CORRECTION — the "re-armed completed row" is the system working

Chasing why `wake #1177` showed `state=new, attempts=0, created_at=02:37:05` while the dispatch log recorded
it `done` at 02:34:41, I suspected duplicate work: a completed row revived and the same shift dispatched twice.
Measured, and it is **not** a defect:

```
subject            = odq-answer-open:69        <- anchored on the OLDEST unanswered row's id, not a count
dispatch log       = released 02:08:03, done 02:34:41 (dur 1597s)
outcome            = "16 of the 22 are closed; 6 are left open"
prompt at 02:37:05 = "6 row(s) in the owner decision queue carry a recorded answer and were never
                      resolved for more than 6 hour(s) as of 2026-10-18T02:37:05Z"
source cooldown    = ODQ_ANSWER_COOLDOWN_SEC=604800  (7 days)
```

The shift closed sixteen of twenty-two, **honestly recorded the six it left**, and the source re-filed because
those six still carry unread answers — with a **freshly rendered prompt**, not a stale one. `wake.py:1103`
revives a terminal row for the exact subject, and the anchor-row subject means "this instance, again", which
is correct when the condition genuinely persists. The 7-day cooldown bounds it to one shift a week.

**The one thing worth knowing** (not a defect, a bound): revival resets `attempts` to 0, so the 2-attempt cap
is per revival rather than per condition. The only thing preventing an uncloseable condition from looping
forever is the source's cooldown. Any source with a short cooldown and a persistent condition should be
reading `defer_on_cooldown=False` — five sources already do (`cfo-backfill`, `comms-freshness` x2,
`memory-pressure`).

**Two false alarms in one round, both mine**, both caught by reading the artefact instead of the label: my own
test ids read as a live proof (§62a), and correct revival read as duplicate work. The habit that caught them
is the one this document keeps paying for — print the raw value, then check it against the store.

---

## 63. ROUND 68 — THREE SHIFTS WERE KILLED BY A LOCK, AND THE MESSAGE SAID "unknown"

While checking whether my dispatcher edit had caused anything, the release count showed `failed 4` where it
had been `1`. It was not my edit. It was worse, and it was live.

### The incident, in the log's own words

```
04:17:51Z ERROR lease for wake #1170 not renewed - killing the session to avoid a double release: unknown
04:19:40Z ERROR exited (rc=2) with wake #1169 still claimed - closing as failed
04:21:21Z ERROR exited (rc=2) with wake #1123 still claimed - closing as failed
```

Three consecutive releases, two minutes apart, each killed after ~2 minutes of work. The warning lines that
explain them were present at 01:50, 03:15 and 04:10 — and in all three earlier cases the second attempt
recovered, which is why nobody had noticed:

```
WARN heartbeat for wake #1123 could not renew (attempt 1, rc=2):
     wake: database error: database is locked; retrying while the lease has margin
```

So: a **transient `database is locked` on the wake store**, retried until the lease margin ran out, and then
the dispatcher does the correct thing — kill the session rather than risk a double release.

### Three defects made it far worse than a slow store should

1. **A 5-second patience.** `wake.py:connect()` used Python's sqlite3 default busy timeout. A write transaction
   held for six seconds was reported as a hard failure. Now `PRAGMA busy_timeout=30000`, verified on a live
   connection: `busy_timeout= 30000`. Waiting costs seconds; killing a shift costs a shift.
2. **The CLI broke its own exit contract.** `cmd_heartbeat` returned **2** for `no-such-row` and `not-claimed`,
   while `wake-dispatch.sh:1091` states: *"1 = the store itself says we do NOT hold this row … 2 = transient"*.
   The dispatcher only survived that by string-matching the JSON. Both now return **1**, proven:
   `heartbeat 1177 --by probe-test` -> `REAL rc=1` with `{"error": "not-claimed", "state": "new"}`.
3. **The kill message discarded the one line that explained it.** `_LEASE_LAST_ERR` held
   `wake: database error: database is locked`; the log printed `${LEASE_LOSS_REASON:-unknown}`. A kill that
   cannot say why is the sibling of a monitor that measures nothing. Both the log line and `OUTCOME_REASON`
   now fall back to `_LEASE_LAST_ERR`.

All three applied with backups (`wake.py.bak-lease-20261018`, `wake-dispatch.sh.bak-lease-20261018`),
`py_compile` and `bash -n` clean.

### What is NOT yet known, stated plainly

**The holder of the long write transaction is unidentified.** The store is *already* WAL
(`PRAGMA journal_mode` -> `wal`), so this is writer-writer contention, and at least eight scripts open that
database (`mirror-owner-sms`, `owner_flood_guard`, `reconcile-sent-status`, `dead-project-flags`,
`owner-text-asks-unrecorded`, `owner-text-ledger-delta`, plus the fan-out every minute and the dispatcher's own
heartbeats). A manual write lock on the store right now takes **0.106 s**, so this is intermittent, not
standing.

Filed as **ledger item 562** with a DoD that requires naming the holder from a real measurement. The next
occurrence will name it, because the kill message no longer says `unknown` — which is the only reason it is
acceptable to stop here rather than keep guessing.

**A note on how this was found.** It surfaced only because I checked my own change against the failure count,
and the failure count happened to move. Had I trusted `bash -n` and moved on, three shifts a day would keep
dying with an explanation the system already had and was throwing away.

**Correction (same round):** the lock-contention item filed above is **ledger item 565**, not 562 — 562 was
already taken. A wrong id in a record is a wrong number, so it is corrected here rather than edited away.

---

## 64. ROUND 69 — THE LOCK'S HOLDER, AND IT WAS A NETWORK CALL INSIDE A WRITE TRANSACTION

§63 named the symptom (`database is locked` killing shifts) and refused to guess the holder. This round names
it, proves the mechanism, and removes it.

### The code, quoted

`reconcile-sent-status.py` — running every 10 minutes against `~/.sms-inbox/inbox.db`, **the same store the
dispatcher renews leases on**:

```python
for r in rows:                                  # up to 25 rows
    urlopen(req, timeout=30)                    # an HTTP call to Twilio
    if real != old and a.apply:
        conn.execute("UPDATE messages SET status=? WHERE sid=?", (real, sid))   # implicit txn opens
        changed += 1
if a.apply:
    conn.commit()                               # only here, after the whole loop
```

Python's `sqlite3` opens an implicit transaction on the first DML statement and does not end it until `commit`.
So the store's **write lock is held for the rest of the loop** — across every remaining Twilio round-trip.

### Proven, not asserted

`/root/_prove_lock_mechanism.py` on a throwaway database: a child process updates then sleeps four seconds
without touching the database, while a second connection tries `BEGIN IMMEDIATE` with a 500 ms busy timeout.

```
RESULT: BEGIN IMMEDIATE failed while the child slept: database is locked
RESULT: after the child committed, BEGIN IMMEDIATE succeeds immediately  -> lock released
CONFIRMED: uncommitted UPDATE holds the write lock across non-database work
```

That is the mechanism behind §63's three kills, demonstrated in isolation. With 25 rows and a 30-second HTTP
timeout each, the window is tens of seconds — larger than the heartbeat margin that §63 showed being exhausted.

### The fix and its bound

`conn.commit()` now happens **per row**, immediately after the `UPDATE`. The write transaction spans one
statement instead of twenty-five network calls. Applied to `/home/zabz/bin/reconcile-sent-status.py`, which is
**the same inode** as `/root/bin/reconcile-sent-status.py` (`stat -c %i` -> `2079928` for both), so the cron path
and the other tree cannot drift. `py_compile` clean, backup `reconcile-sent-status.py.bak-commit-20261018`, and a
real run afterwards: `unsettled outbound rows in the last 48h: 0` / `nothing to reconcile`.

### What is still unprovable, and why that is acceptable now

**Whether that exact script was the holder at 04:17:51 cannot be established retroactively** — the kill message
of the period said `unknown`, and SQLite keeps no history of who held a lock. What is established: it is *a*
holder, on the same store, with a window far longer than the margin, on a ten-minute cycle that overlaps the
kills. §63's fix means the *next* occurrence names its holder in the log instead of saying `unknown` — which is
the difference between resolving this and guessing at it.

**Ledger item 565 closed done** with the mechanism, the code change and the bound.

### 64a. Did the class spread? Partly — and one detail validates the timeout choice

Ten scripts in `/root/bin` and `/home/zabz/bin` contain both `urlopen`/`requests` and `.execute`, which is not
the same as containing the defect: my own `reconcile-sms-log.py` is on that list and commits per row by design.
Spot-checked the one on the shortest cycle, `sms-inbox.py` (every 5 minutes):

```
295  conn.executemany(...)
297  conn.commit()            <- batch, then commit. No network in between.
341  conn.execute("PRAGMA journal_mode=WAL")
342  conn.execute("PRAGMA busy_timeout=30000")
357  with urllib.request.urlopen(req, timeout=60)   <- fetch happens in its own function
473  conn.commit()            <- writes a list already fetched; no HTTP inside the write loop
```

So it is safe by construction — **fetch, then write** — and it is the only one of the ten on a five-minute cycle.
The dangerous shape is the interleaved one, which `reconcile-sent-status.py` had and no other checked script
does.

**The useful detail: `sms-inbox.py` already sets `busy_timeout=30000`.** So §63's 30-second patience is not a
number I invented — it is the estate's own existing choice for the same store, which is the only reason to
prefer it over guessing.

---

## 65. ROUND 70 — IDLE WAS HONEST, AN OWNER ROW WAS MISSING, AND A YEAR WAS AN ORPHAN

### The IDLE line, verified rather than assumed

With `in flight : 0` and five rows pending, the question was whether the machine had stalled. It had not, and it
said so precisely:

```
IDLE  : healthy - 5 row(s) waiting, NONE claimable now; earliest 2026-10-18T04:37:12+00:00
        (checkout-health:prod-db-sync:20261018)
claim --json -> {"blocked_by": "night-quiet",
                 "gated": {"not_before": 5, "night_quiet": 0, "source_hourly_cap": 0, "new_rows": 5 ...}}
```

`night_quiet: 0` matters: no row was actually gated by the night rule, so `blocked_by` was naming the first gate
it checked rather than the reason. The real gate was `not_before` on each row. **And the prediction held to the
second:** at 04:38:04-04:38:07 three releases started, 52 seconds after the named earliest time.

```
04:38:04Z releasing wake #1165 (checkout-health:prod-db-sync:20261018)
04:38:05Z releasing wake #1168 (project:lpt-website:20261018)
04:38:07Z releasing wake #1179 (project:cfo:20261018)
04:42:42Z released wake #1165 done exit=0 runner_code=0 dur=277s
          outcome: "## Checkout health - prod-db-sync **Result: the ..."
```

**`#1165` is the first release since `wake.py` and `wake-dispatch.sh` were edited in §62-§64, and it completed
cleanly with a real answer.** That is the safety check on those edits: a release can still claim, heartbeat and
settle. It is NOT a proof of the lock fix, because no lock episode occurred during it - there was nothing to
survive.

### A blocked item the owner could not see

A fleet triage had reported four owner-blocked items with **no queue row**. Checked one by one rather than
trusting the count: items 337 and 457 are the shop-reply lane, which row 527 already ruled "NOT AN OWNER
DECISION"; item 373 is an engineering defect (a text producer bypassing the send seam) that should never have
been blocked on him. **Item 152 is genuinely his and was invisible:**

> Security: a live broker credential for user `zabz-desktop` sits in plaintext, and clearing it needs a
> production broker container recreate plus a fleet-wide re-issue.

Filed as **owner queue 554** (high) with one recommendation and three options, then linked so the block clears
itself when he answers:

```
owner-row-set {"item": 152, "owner_row": 554, "previous": null}
152|554|blocked
```

That is three of the four accounted for as mis-bucketed and one made visible — the difference between "17 items
wait for him" and "17 items, some of which are our own filing error".

### `lint-refs` was reporting a year as an unresolved reference

```
UNRESOLVED-REF item 522 (housekeeping, blocked) -> title/why names owner-queue #2026, which does NOT exist
                                              in the queue; not a link - probably a year or a task id
```

The tool said "probably a year" and reported it anyway, every 15 minutes, forever. A finding that can never be
acted on teaches the reader to ignore the log - the same lesson as the 245-of-245 `loop-stall UNUSABLE` lines
retired in §59. The year band (1900-2100) is now excluded from the orphan path only; `_stale_oq_refs` needs a
row to exist before it can be stale, so a year cannot reach it.

```
before:  lint-refs: 1 orphan prose reference(s) across 140 live item(s)
after :  lint-refs: clean - 6 reference(s) across 37 blocked item(s) all live, 0 orphan prose ref(s)
         across 140 live item(s)
```

**A note on a small self-inflicted error:** one command in this round piped a grep into `/dev/null` and exited
1; the `[exit code: 1]` in the transcript is my malformed command, not a system failure, and is recorded so it
is not mistaken for one later.

---

## 66. ROUND 71 — EVIDENCE RECORDING WAS CHANGING THE WORLD IT DESCRIBED

Started as "fix the muted pain closer" and turned into the sharpest trap of the session.

### The trap, found by using the tool

Recording a diagnostic lead on item 559:

```
$ work.py attempt 559 --by wake-audit-20261018 --did "..." --proof "..." --result "..."
attempt-recorded {"attempt": 1053, ..., "id": 559, "state": "todo"}
```

Item 559 had been **blocked**. `attempt` shares `cmd_attempt` with `close`, and its `--state` defaulted to
`todo`, so **writing a note about an item unblocked it**. Worse, one line below:

```python
blocked_on = a.blocked_on if state == "blocked" else None
```

the same call writes `blocked_on = NULL` over a recorded blocker — the exact hazard the code already guards for
`--state blocked` ("an untyped block is how work goes invisible"), reached from the other side.

Fixed: `attempt --state` now defaults to **None = record only, change nothing**; the item keeps its state, and a
blocked item keeps its blocker. `close` keeps its `todo` default, because closing a shift must state an outcome.

### And the test found a second defect neither of us had noticed

With state and blocker preserved, the throwaway test printed:

```
before:  blocked  "MEASURED 2026-10-16: no human decider ex..."  revisit 2026-10-19T06:54:04Z
after :  blocked  "MEASURED 2026-10-16: no human decider ex..."  revisit 2026-10-25T04:52:55Z
```

`revisit_at` was recomputed with `revisit_default()` (+7d) whenever the item was blocked and no `--revisit` was
given — so **every diagnostic note pushed a blocked item a week further from being looked at again.** The block
got quieter each time somebody examined it, which is the opposite of what a revisit date is for. Now an existing
date is preserved and only an explicit `--revisit` replaces it.

Retested on a fresh copy: `blocked | same blocker | revisit 2026-10-19T06:54:04Z — unchanged`. Backup
`work.py.bak-attemptstate-20261018`, `py_compile` clean.

**This is why the throwaway store exists.** Both defects are invisible on a successful-looking run: the first
prints `attempt-recorded` with no warning, and the second only shows if you print the column before and after.

### The owner channel: one item raised from the dead

Of four owner-blocked items with no queue row, three were mis-bucketed (337/457 ruled "NOT AN OWNER DECISION" by
row 527; 373 is an engineering defect). **Item 152 was real and invisible** — a live broker credential for
`zabz-desktop` in plaintext whose fix needs a production broker recreate and a fleet-wide re-issue. Filed as
**queue 554** (high) and linked: `152|554|blocked`.

### `lint-refs` was reporting a year as an unresolved reference

Item 522 names `#2026` in prose; the tool said "probably a year" and reported it every 15 minutes forever. The
year band (1900-2100) is now excluded from the orphan path. `1 orphan -> clean — 0 orphan prose ref(s) across
140 live item(s)`.

### The muted pain closer: measured, and started

```
PAIN CHECK 2026-10-18T04:54:17Z
  check files      : 21
  findings         : FIXED 45 | LIVE 115 | UNKNOWN 22
  open entries     : 612
  FIXED but OPEN   : 42  <- close these with --close
  LIVE and open    : 110
  open, no check   : 438
```

`pain-check.py` HAS `--close`; the cron line runs only `--write-status`, so it measures and never acts — the
closer was muted by one missing flag. `close()` is conservative and correct (only entries whose **own check**
reports FIXED, evidence quoted into the resolution, warnings on failure).

A manual `--close --write-status` run was launched. **At the time of writing it was still inside C1.sh** (the
suite alone takes ~4m38s per file, and 21 files run). Its closure count is therefore **UNVERIFIED**, and
`--close` is deliberately **NOT yet in cron**: a closer that has been run is not a closer that has been tested,
and this document has already recorded what happens when that distinction is skipped.

### One more silent monitor, recorded not fixed

`sms-app-gap` reports `quiet` every tick. It asks `messages where direction='inbound' and app_has_it=0`, and the
measured distribution is:

```
inbound  app_has_it=1  450          <- all of them
inbound  app_has_it=0    0
```

With today's labelling it **cannot fire**: every inbound row is marked as held by the app, so the comparison is
circular. That is a reading that cannot distinguish two states, and rebuilding it against real provider truth is
its own piece of work rather than a patch at the end of a round.

### 66a. A probe that counted itself

`pgrep -fc "pain-check.py --close"` returned **3** twice while the work had actually finished, and returned **2**
when nothing was running at all. `pgrep -f` matches its own command line and the shell that invoked it, so the
number included the probe. The reliable reading is `ps -eo pid,etime,cmd | grep ... | grep -v grep`, which shows
real PIDs and an elapsed time:

```
466903  00:29  /usr/bin/python3 /root/bin/pain-check.py --close --write-status
466905  00:29  bash /home/zabz/bin/pain-checks/C1.sh
```

A relaunch also silently failed while an earlier `nohup ... &` inside the same ssh invocation was killed when the
session closed; `nohup setsid ... < /dev/null &` followed by a **separate** call to verify is what works.

This is the estate's oldest lesson in a new costume: *do not trust a `0` (or a `3`) from a counter that the
probe can be part of.* The closer's real state at the end of this round: **running** (PID 466903, verified by
`ps`), closure count still **UNVERIFIED**, and `--close` still **not in cron**.

### 66b. `lint-refs` caught something bigger: the owner queue reclassifies itself

Seconds after linking item 152 to **queue 554**, `lint-refs` reported it STALE:

```
STALE item 152 (kosher-ai-filter) -> owner-queue #554 is dismissed
```

Row 554 was filed at 04:28:38 and **dismissed at 04:55:44** — not by the owner, who was never asked — with:

> NOT AN OWNER DECISION. Moved to the business queue as ledger item **581** with question, context, options
> and recommendation preserved verbatim. The owner's 2026-10-...

Four other rows are in the same state (319 -> 528, 333 -> 522, 362 -> 523, 424 -> 535, all `dismissed`), so this
is a **standing triage mechanism**, not a one-off. It applies the owner's own delegation (*"this is your
decision it doesn't need me think about it ... decide the best one and get it implemented"*, quoted in row 547's
resolution) to questions that are really engineering.

**Three consequences, and the third is the important one:**

1. **"Filed" does not mean "asked", and now it also does not mean "waiting".** §  P2942 established that a filed
   question may never reach him; this adds that it may also be *answered by the system on his behalf* and turned
   into ledger work. Both are correct behaviours and both are invisible from the row count.
2. The successor is real: **ledger item 581** exists, `housekeeping`, `todo`, priority 3, carrying my question
   verbatim. The block on item 152 can still clear itself — by 581 being DONE, not by him replying.
3. **The security exposure is mine to fix, not his to authorise.** That is what the delegation says, so this
   round does not get to file it and walk away: the remaining work is a production broker recreate plus a
   fleet-wide credential re-issue, which is a service-state change requiring
   `settings/machines/host-posture.tsv` to permit the host and `guard-service-state.sh` to allow the operation.
   **Not attempted at 05:03 with the round's remaining budget** — a credential re-issue across a fleet is
   exactly the kind of action that must not be squeezed in at the end, and the next round starts with it.

The general lesson: **an automated triage that reclassifies questions is a writer of `status`**, so a queue
count is not a measure of what is waiting for a human. §   The same rule as everywhere else in this document,
now applied to the queue itself.

---

## 67. ROUND 72 — THE CLOSER WORKS, AND THE JOURNAL'S OWN READERS DISAGREE ABOUT IT

### The closer, run and measured

`pain-check.py --close --write-status` ran to completion in ~6 minutes:

```
PAIN CHECK 2026-10-18T05:07:12Z
  findings    : FIXED 45 | LIVE 115 | UNKNOWN 22
  open entries: 588
  FIXED but OPEN : 17   <- was 42 before this run
  closed         : 15 ['P261', 'P264', 'P2819', 'P2823', 'P2833', 'P327', 'P338', 'P340',
                       'P345', 'P347', 'P42', 'P48', 'P58', 'P76', 'P84']
WARN: could not close P2561b: no entry P2561b
WARN: could not close P45b: no entry P45b
```

The two warnings are real and correct: `P2561b` and `P45b` are check-file ids that name no journal entry, so the
closer declined rather than inventing one. **42 -> 17, with 15 closed on evidence and 2 legitimately refused.**

### The evidence is in the store, not in the claim

`journal/state/status.tsv` holds **40 rows dated 2026-10-18**, each one quoting its own check and run time, e.g.:

```
pain  P261  done  2026-10-18  SECRATARY-CLOUD  Closed by pain-check: the entry's own check reports FIXED.
      Reason: one author in the last 25 lpt-hub commits (worktrees=0) (check C4.sh, run 2026-10-18T05:07:13Z)...
pain  P48   done  2026-10-18  SECRATARY-CLOUD  ... Reason: only 0 locked events in 7 days - refusals are not
      happening (check C1.sh, run 2026-10-18T05:07:40Z)...
```

`journal.py status` agrees: **OPEN PAIN 608 -> 573**. And the closer is now **scheduled** — the cron payload was
decoded, edited and re-encoded, verified by decoding it back:

```
/usr/bin/python3 /root/bin/pain-check.py --close --write-status >> /root/.pain-check/run.log 2>&1
```

Crontab 245 lines before and after; backup `/root/crontab.bak-painclose-20261018`.

### But the journal's readers disagree, and that is a live defect

The authority's index held **0 entries**, so it was rebuilt: `index: 5282 entries -> journal.db + fts5`. Then:

```
$ journal.py show P261        -> "### P261 · pain · 2026-09-17 · open"      <- WRONG, status.tsv says done
$ journal.py list --kind pain --status done --since 2026-10-18
   no entries match
   # 0 entries in index/entries.tsv                                       <- while wc -l says 5283
$ journal.py status           -> OPEN PAIN 573                            <- correct, sees the resolves
```

So after a real resolve: `status` counts it, `show` denies it, and `list` reports the index as empty while the
file it names holds 5,283 lines. **`show` is the command the journal's own README tells a session to use to read
one entry** — so a future session reading P261 would see `open` and re-open work that was closed on evidence.
That is the repeated-work failure this estate pays for most often, produced by the memory system itself.

**Recorded as an open defect, not fixed**: the readers resolve their index root differently and this round's
budget went to proving the closer. It is the next round's first item, because until it is fixed the closer's
work is half-visible — and a closer whose effect half the readers cannot see is a closer nobody can trust.

**Also noted:** the authority's journal holds **5,282** entries while this session's checkout reports **4,384**.
Two checkouts, two counts. That is the same split-store shape as everything else in this document and is not yet
explained.

### 67a. The disagreement, diagnosed — two status sources

The "# 0 entries in index/entries.tsv" line is misleading but not the fault: it is the count **after** filtering.
`list --kind pain --limit 2` prints `# 729 entries in index/entries.tsv` and `stats` agrees (`pain: 729`), so the
index is readable and complete.

The real fault is that the journal has **two status sources and the readers split between them**:

| reader | where status comes from | result for P261 |
|---|---|---|
| `status` (the always-read page) | `state/status.tsv` (the append-only resolve log) | **sees the resolve** — OPEN PAIN 608 -> 573 |
| `show <id>` | the entry file's own frontmatter | **`open`** |
| `list --status done` | the entry file's own frontmatter | **no entries match**, though 40 done rows exist for today |

`cmd_resolve` is documented as *"Record that an entry's status changed. Appends; never edits the entry file."*
So the entry file is **correctly** left alone and the frontmatter **correctly** keeps saying `open` forever. The
readers simply never overlay the resolve log.

**Consequence, and why this is the worst possible place for it:** the journal's own README tells a session to
read one entry with `show <id>`. A session that follows the instructions sees `open` on work that was closed on
evidence twenty minutes earlier, and re-opens it. The memory system is generating the repeated-work failure it
exists to prevent, and it will do so for every closure the closer now makes daily.

**Fix direction (not attempted — the journal is the one system where a rushed edit costs the most):** overlay
`state/status.tsv` onto the frontmatter in the `show` and `list` read paths, so all three readers agree, and make
the `list` footer say "N entries after filters" rather than implying the index is empty. It needs its own round
with a throwaway journal to prove it, exactly as the write-back needed one.

---

## 68. ROUND 73 — MY OWN CAPABILITY LADDER KILLED TWO SHIFTS

The failure count moved while this session was working: `failed 4` at 05:03, **`failed 6`** at 05:09. Both new
failures were high-priority rows — precisely the class the ladder from §62 targets — and both died in **2
seconds**:

```
05:08:05Z releasing wake #1186 (memory-oom:20261018) -> zabz-tech-ts
05:08:07Z released 2026-10-18 wake #1123 failed exit=1 runner_code=3 dur=2s
   outcome: ssh hop failed (rc=1) after 2s, ... output: === wake-run (W2) started ...
     model lane: PINNED by the balance control -> deepseek/deepseek-v4-pro (WAKE_AGENT_MODEL)
     model: FAIL-LOUD UNRESOLVED - refusing to boot on the profile composition default:
            resolver could not validate 'deepseek/deepseek-v4-pro' against a live catalog
```

**This was my change.** The ladder resolved the id from the authority's catalog FILE
(`~/.sms-inbox/model-catalog.json`, where `deepseek/deepseek-v4-pro` is listed); the runner validates against a
**live** catalog and does not contain it. §62 proved the shell block produced the right argument — it did — and
never proved the id was valid *where it would actually be used*.

### Stopped, and the cost

The pin is now inert: it requires `WAKE_CAPABILITY_LANE=1`, which nothing sets. Verified by running the shipped
block with `PRIORITY=high` and the env unset: `LANE=[] LANE_ARG=[]`. `bash -n` clean, backup
`wake-dispatch.sh.bak-ladderoff-20261018`. The ladder code, catalog resolution and `wake-lane.log` are kept so the
next round can point it at the right catalog instead of rebuilding it.

**Damage, repaired where possible:** `wake #1123` had reached **2 of 2 attempts** and would never retry — a row
killed by my bug, not by its own work. Its attempt is refunded (`state=new, attempts=1/2`) with the reason
written into `outcome` so the next reader sees why:

> REFUNDED 2026-10-18 by wake-audit: failed exit=1 runner_code=3 in 2s because the capability lane pinned
> deepseek/deepseek-v4-pro and the runner could not validate it. That was a dispatcher regression, not a fault
> of this work ... The lane is now inert until WAKE_CAPABILITY_LANE=1.

`wake #1186` still had an attempt in hand and will retry on its own.

### The lesson, which is about my method and not about models

§62 said, in the record, "PENDING, and a clock owns it: the first real high-priority release must show
`reason=capability:high-priority` AND the shift must actually run under that model". **Then it shipped the change
active by default anyway.** Labelling something "pending proof" is not a safety measure; the only safe form of an
unproven lane is an inert one, enabled by whoever holds the proof.

The counter that caught it was not a test — it was `failed` going 4 → 6 between two reads. Twelve minutes of
monitoring the number that matters was worth more than the isolation test that said the block was correct.

**The fix for next round is small and specific:** resolve the lane against the same catalog the runner reports
(`catalog=https...` in the outcome above), prove it with ONE high-priority release whose outcome line reads
`model lane: ...` and no `FAIL-LOUD`, and only then export `WAKE_CAPABILITY_LANE=1`.

---

## 69. ROUND 74 — THE JOURNAL'S READERS NOW AGREE, AND `--since` MEANS THE CLOSURE DATE

§67a diagnosed the split and stopped there because the journal is the one system where a rushed edit costs
most. This round fixes it, proven on a throwaway copy first.

### Two faults, not one

**1. `show` and `list` never consulted the resolve log.** `cmd_resolve` appends to `state/status.tsv` and never
edits the entry — deliberate and documented. `effective_status()` exists precisely to overlay it, and `status`
calls it, but `cmd_show` printed `e["status"]` straight from the marker and `cmd_list` both **filtered** and
printed on it.

**2. `--since` compared the wrong date, and that one misled me.** Even with the overlay in place,
`list --kind pain --status done` returned 141 entries while `--status done --since 2026-10-18` returned
**nothing**, because `_matches` compares `e["date"]` — when the entry was **written**. A closure is always newer
than the entry it closes, so "what did I close today" could not be expressed. **I spent two rounds reading that
empty result as "the closes did not take effect" when they had** — a filter that answers a different question
than it appears to is the same class as a monitor that measures the wrong thing.

### The fix, and its proof

- Both read paths overlay the resolve log. Deliberately narrow: `catalog()` keeps its raw view so the
  integrity and drift checks still see the markers.
- The overlay carries `status_date`, and when a status filter is in play `--since`/`--until` compare **that**.
  Without a status filter nothing changes, so "entries created since X" behaves exactly as before.

Proven on a `cp -a` copy of the journal first (`--root /tmp/jtest`), then on the live tree:

```
throwaway:  list --kind pain --status done --since 2026-10-18  ->  40 entries   (created 2026-09-25 .. 10-04)
live:       show P261                                          ->  pain · 2026-09-17 · done
live:       list --kind pain --status done --since 2026-10-18  ->  40 entries
live:       journal.py check                                   ->  0 error(s)
```

**40 is not a coincidence: it is exactly the number of resolve rows in `state/status.tsv` dated 2026-10-18.**
The list and the store now count the same thing.

Committed `f6d9b4d2` in `/root/code/harness-config` and pushed explicitly to
`refs/heads/fix/journal-status-readers` on origin (never to main, never forced).

**Why this mattered more than its size:** the journal's README tells a session to read one entry with
`show <id>`. Until this round, that command reported `open` on work closed on evidence minutes earlier — so the
memory system would have regenerated the repeated-work failure it exists to prevent, once a day, for every
closure the now-scheduled pain closer makes.

---

## 70. ROUND 75 — THE CONSERVE LANE WAS A LATENT TOTAL OUTAGE, ARMED BY BALANCE PRESSURE

§68 disabled the capability ladder because two shifts died on an id the runner rejected. This round found out
which ids it accepts, by **asking the resolver itself** instead of reading any catalog file:

```
$env:WAKE_AGENT_MODEL="deepseek/deepseek-v4-pro"; & C:\Users\ezabz\bin\wake-model.ps1
-> {"catalog":"https://api.deepseek.com/v1/models","catalog_ok":true,
    "candidates":["deepseek/deepseek-v4-pro"],"dropped":["deepseek/deepseek-v4-pro"],"unvalidated":true}

$env:WAKE_AGENT_MODEL="deepseek-v4-pro"; ...
-> {"dropped":[],"unvalidated":false}          validated=True
```

The runner validates against **DeepSeek's own API catalog**, not the secretary gateway and not
`~/.sms-inbox/model-catalog.json`. Measured verdicts:

| candidate | verdict |
|---|---|
| `deepseek/deepseek-v4-pro` | dropped, unvalidated |
| `deepseek/deepseek-v4-flash` | dropped, unvalidated |
| `deepseek-chat` | dropped, unvalidated |
| `deepseek-v4-pro` | **validated** (`dropped: []`) |
| `deepseek-v4-flash` | dropped, unvalidated |

### The finding that matters more than the ladder

`wake_budget.lane_for("conserve")` returned **`deepseek/deepseek-v4-flash`** — wrong prefix *and* an id the
provider catalog does not contain at all. Round 49 "fixed" that literal to a secretary-catalog id, and it was
still invalid **where it is used**.

So the conserve lever — which fires automatically when the prepaid balance drops — would have made **every
shift fail in two seconds**, exactly as `#1123` and `#1186` did, at the moment the balance was already low and
the system could least afford it. It has never worked; it has only never been pulled. That is a latent total
outage armed by money pressure, and it was invisible because nothing ever exercised it.

**Fixed to `None`** — do not pin — because no validated *cheap* id exists in this provider's catalog, and
pinning an invalid id is strictly worse than using the default seat. The conserve behaviour is now honestly
"no lane change" rather than a guaranteed failure, and the comment records the measurement and the reason.

```
$ import wake_budget; lane_for("conserve"), lane_for("ok")  ->  None, None
```

### The ladder

`PREF` in the dispatcher is corrected to the one validated id: `PREF = ("deepseek-v4-pro",)`, `bash -n` clean,
backups `wake_budget.py.bak-laneids-20261018` / `wake-dispatch.sh.bak-laneids-20261018`.

**It stays inert** (`WAKE_CAPABILITY_LANE` unset). Validated-by-the-resolver is not validated-in-a-release, and
§68 is the record of confusing those two. **And enabling it as it stands would silently do nothing**, because
the resolution step still reads the gateway catalog file, which does not list the bare id — so the next
session's one-line change is to set `LANE="deepseek-v4-pro"` directly inside the gated branch, prove it with one
high-priority release whose outcome reads `model lane: ...` and no `FAIL-LOUD`, and only then export the flag.

**The method lesson, again: ask the thing that decides.** Three rounds were spent on this id — a local catalog
file, then a gateway HTTP catalog, then the provider's own — and only the third one is the list the decision is
made against. One invocation of the resolver would have answered it at any point.

### 70a. The diagnostic from §63 paid for itself, and proved the work is not finished

Fifteen minutes after the lane fixes, `failed` moved 6 -> 7. The new kill is the same class as §63's three, and
this time the message names the cause instead of `unknown`:

```
05:10:40Z WARN  heartbeat for wake #1170 renewed on attempt 2 after 1 transient failure(s): wake: database error: database is locked
05:14:09Z ERROR lease for wake #1170 not renewed - killing the session to avoid a double release: wake: database error: database is locked
```

That is the `_LEASE_LAST_ERR` fallback added in §63 doing exactly what it was added for: the same event that
said `unknown` at 04:17 now says `database is locked`.

But it also shows the class is **not closed**. Item 565 fixed `reconcile-sent-status` (commit per row) and
`wake.py` took `busy_timeout=30000` — verified on a live connection — and a writer can still hold the wake
store longer than the lease margin. SQLite keeps no history of a lock holder, so the only remaining way to name
it is to capture it **at the instant of failure**.

Filed as **ledger item 584**: on `rc=2` with `database is locked`, record `fuser -v` (or `/proc/*/fd` plus
cmdline) for `inbox.db` into the dispatch log next to the error, then produce one occurrence naming a real PID
or 24 hours with none. **Not implemented this round** — it touches the lease path in the live dispatcher, and
the last time this session edited that file without an end-to-end proof it cost two shifts (§68).

---

## 71. ROUND 76 — A WATCHER THAT NAMES THE LOCK HOLDER, BUILT WITHOUT TOUCHING THE LEASE PATH

Item 584 asked for the lock holder to be captured at the instant of failure. §70a deferred it because the
obvious implementation edits `lease_probe` in the live dispatcher, and §68 is the record of what an unproven
edit to that file costs.

**So it was built as an additive watcher instead** — `/root/bin/wake-lock-watch.py`. It samples the lock a
writer needs (`BEGIN IMMEDIATE` with a 300 ms busy timeout) for a bounded window; on failure it records the raw
error plus **every PID with the database open** (scanned from `/proc/*/fd`, so no `lsof` dependency) and each
holder's command line. Nothing in the dispatch path changed.

### Proven on a planted lock, both paths

```
quiet path   (real store)   ->  quiet: 2 probe(s), the write lock was free every time
planted lock (throwaway db) ->  LOCKED database is locked | holders: pid 499887 python3 -c
                                import sqlite3,time ... c.execute("BEGIN IMMEDIATE"); time.sleep(9) ...
```

That is a real PID and its full command line, captured while it held the lock — exactly what SQLite cannot
tell you after the fact. The first version listed **itself** as a holder (honest noise, useless signal); it now
skips `os.getpid()`.

### Installed and running

`* * * * *` via `cron-wrap.sh wake-lock-watch`, 15 probes at 3 s (a 45-second window each minute), crontab
245 -> 246 lines, payload decoded to verify:

```
/usr/bin/python3 /root/bin/wake-lock-watch.py --probes 15 --gap 3 >> /root/.sms-inbox/wake-lock-cron.log 2>&1
```

**Fired under cron at 05:17: `quiet: 15 probe(s), the write lock was free every time`, and no
`wake-lock.log` was created** — which is the correct quiet behaviour, and also an honest "not yet".

**Item 584 stays OPEN.** Its DoD is a *real* capture naming a real holder, or 24 hours with none; a mechanism
that has only ever been shown a planted lock has been RUN, not TESTED by the world. The note on the item records
the mechanism, the planted proof and that it is awaiting its first true occurrence.

**The shape worth keeping:** when a change would touch a fragile live path and cannot be proven end to end, do
not make it smaller — make it a *separate process* that observes. The estate already learned this once
(`mirror-owner-sms` rather than editing the live responder). This is the same move applied to instrumentation.

### 71a. A lock kill was consuming the work's attempts, so infrastructure failures killed real work

Checking what the day's lock kills had cost:

```
1123 | claimed | 2/2 | high    <- refunded earlier this session, now claimed and RUNNING
1169 | failed  | 2/2 | normal  <- killed 04:19:40 by "lease not renewed ... database is locked"
1170 | failed  | 2/2 | normal  <- killed 04:17:51 and again 05:14:09, same cause
```

`max_attempts` is the guard that stops a *work item* from being retried forever — but it counts every failure,
including failures that are not the item's fault. So a lock that lasts past the lease margin converts an
infrastructure problem into **permanently abandoned work**: `1169` and `1170` were both at 2 of 2 and neither
would ever run again.

**Both refunded to `attempts=0`, `state=new`**, with the reason written into `outcome` so the next reader sees
why this was done and does not read it as leniency:

> REFUNDED 2026-10-18 by wake-audit: killed by the wake-store write lock (lease not renewed -> database is
> locked), not by its own work. Items 565/584 address the lock; this row deserves to run once it is quiet.
> One-time repair: a THIRD lock failure should be diagnosed, not refunded again.

The earlier refund of `1123` is the evidence that this works: it was 2/2 and dead, it is now `claimed` and
running.

**The general point, which is worth more than the two rows:** an attempts cap cannot distinguish "this work
failed" from "the platform failed while this work ran". Any failure class that is not about the item — a lock, a
transport hop, a model id that does not exist — should refund rather than consume, and the three repairs in this
session (1123, 1169, 1170) were all that class. A future cap should count *the work's own* failures.

### 71b. A kill at 05:18 still said `unknown`, and it is not the store

Twelve minutes after the lane fixes, `failed` moved 7 -> 9. The newest is `#1188` at 05:18:07:

```
05:15:36Z WARN  heartbeat for wake #1123 could not renew (attempt 1, rc=2): wake: database error: database is locked
05:15:41Z WARN  heartbeat for wake #1123 renewed on attempt 2 after 1 transient failure(s)
05:18:07Z ERROR lease for wake #1188 not renewed - killing the session to avoid a double release: unknown
```

**"unknown" again, and this time it is not the lock:** the watcher ran at 05:17 and reported
`quiet: 15 probe(s), the write lock was free every time`, and no `wake-lock.log` exists.

What is ruled out:

- `WAKE_CLI=${WAKE_CLI:-$HOME/bin/wake.py}` -> under cron that is `/root/bin/wake.py`, and
  `stat -c %i /root/bin/wake.py /home/zabz/bin/wake.py` returns **2162185 for both** — one inode, so the
  patched `heartbeat` (which returns **1** for `not-claimed`) IS the copy being invoked.
- So the probe did not report `not-claimed` (that would set
  `LEASE_LOSS_REASON="the store reports the row is no longer claimed by us"`), and it did not report a
  transient error either (that would set `_LEASE_LAST_ERR`). **Both were empty, which means the flow reached the
  kill block without going through either `lost` branch of the `case "$decision"`.**

The likely shape — **not yet proven** — is that the heartbeat loop exited some other way (its `LOOP_DEADLINE`,
or the session's own timeout) and fell through with no reason set. That is a hole in the *reason plumbing*, not
in the store: the third instance of "the failure happened and the explanation was not carried".

**Not fixed this round.** It needs the exit paths of `heartbeat_lease` read line by line with the loop's
deadline logic, and the last edit to that region (§68) cost two shifts. Recorded so the next session starts at
the loop's exits rather than re-deriving that the store is innocent.

---

## 72. ROUND 77 — THE "unknown" KILL DID NOT COME FROM WHERE THE CODE SAYS IT MUST HAVE

§71b narrowed an unexplained kill to the heartbeat loop's exit paths. This round tested the function instead of
reading it again, and the test **contradicted my hypothesis**.

### The test

Extracted the shipped `heartbeat_lease()` from the live dispatcher, stubbed only `lease_probe` (returns 1) and
`lease_decision` (prints `lost`), and called it:

```
ret=1 decision=[lost] rc=[1] attempt=[1] reason=[the store reports the row is no longer claimed by us]
```

So the normal `lost` path **does** set `LEASE_LOSS_REASON`, and the globals do escape the function. A kill that
prints `unknown` therefore **cannot** have come from that path — the hole is somewhere else, and my §71b guess
(the `LOOP_DEADLINE` exit) is not yet supported by anything.

### So the next occurrence will name its own path

Rather than keep hypothesising about a 1,340-line script, three minimal edits make the kill self-explaining
with **no control-flow change** (one assignment per branch, one longer message, two initialisers):

```
LEASE_DECISION="$decision"; LEASE_RC="$rc"; LEASE_ATTEMPT="$attempt"      # in the lost branch
log "ERROR lease for wake #$ID not renewed ... [decision=${LEASE_DECISION:-unset} rc=${LEASE_RC:-unset}
     attempt=${LEASE_ATTEMPT:-unset} err=${_LEASE_LAST_ERR:-none}]"
```

`bash -n` clean, backup `wake-dispatch.sh.bak-leasediag-20261018`. The next kill now reads one of:

| message | meaning |
|---|---|
| `decision=unset ...` | **not** `heartbeat_lease` — a different call site prints this string |
| `decision=lost rc=1 reason=...` | a normal "no longer ours" loss |
| `decision=lost rc=2 reason=... margin` | the store could not be reached before the margin |
| `decision=<anything else>` | the state machine produced a decision nobody has seen |

**This is deliberately not a fix.** Three kills today had an explanation available and discarded; the pattern is
not "the code is wrong" but "the evidence was not carried". Adding the evidence first, and reading the next
occurrence, costs one kill instead of another round of guesses — and the last time this file was edited on a
hypothesis rather than a measurement it cost two shifts (§68).

---

## 73. ROUND 78 — THE DEPLOY HAZARD IS CLOSED AT BOTH ENDS: THE REPO NOW IS PRODUCTION

§4 named this "the single biggest hazard to every fix above": the repo copies were **different lineages**
from what runs. §45 built the refuse guard, which stopped the damage; it never removed the cause, because
§4's own prescription was *"pull production INTO the repo first, then add diff-and-refuse"* and only the
second half was done.

Measured today, the gap had widened:

```
dispatch.sh          repo  579 lines / 26254 B / 9e619d0c    live 1400 lines / 74101 B / b5f77b77
wake.py              repo 1280 lines / 54119 B / 3cda25e6    live 2046 lines / 95848 B / 8b027117
run-wake-sources.sh  repo 2979 B                             live 19228 B / 45a475af
```

All three live files were copied into `scripts/wake/` and committed (`f6f5b0c7`, pushed to
`refs/heads/fix/reconcile-wake-repo`). **The proof is the same dry run that used to refuse:**

```
before:  REFUSED  /root/bin/wake.py holds 721 line(s) that .../wake/wake.py does not have
         REFUSED  /root/bin/wake-dispatch.sh holds 710 line(s) that .../dispatch.sh does not have
after :  ok       /root/bin/wake.py (identical, nothing to do)
         ok       /root/bin/wake-dispatch.sh (identical, nothing to do)
```

**So the deploy hazard is now closed at both ends:** the guard refuses a divergent install, and there is no
longer anything divergent to install. A `deploy.sh --apply` today is a no-op, which is what a deploy should
be until someone deliberately changes the repo.

**The direction of truth is now stated once and unambiguously: production is what runs.** Every future edit
starts from these files, and a session that edits the repo copy and then deploys will be changing the live
dispatcher deliberately rather than by accident.

**One honest caveat:** this commit was made in the authority's checkout (`/root/code/harness-config`) because
that is where the live files are. This session's other commits are in the Windows checkout. Two checkouts, two
HEADs — the estate's documented divergence (`AGENTS.md` §6.1), not something this round created or fixed. The
next integrator should merge `fix/reconcile-wake-repo` before editing these three files anywhere.

---

## 74. ROUND 79 — THE FIRST REAL LOCK CAPTURE, AND WHY IT MADE THE INSTRUMENT BETTER BY MAKING IT QUIETER

The watcher from §71 caught its first live event within three minutes of installation:

```
2026-10-18T05:20:05+00:00 LOCKED database is locked | holders:
  pid 504337 /usr/bin/python3 /root/bin/sms-responder.py run --send --limit 8 --max-sends 3
  pid 504373 /usr/bin/python3 /home/zabz/bin/sms-inbox.py sync --pages 3
  pid 504634 python3 /root/bin/wake.py stats --json
  pid 504668 python3 /root/bin/wake.py heartbeat 1167 --by wake-dispatch@secratary-cloud
```

Four processes named, with command lines. **And not one of them is the culprit.**

- `sms-responder.py` commits **per row** (`_record()` does `UPDATE` then `commit()`), so its write
  transactions are short. Read, not assumed.
- `sms-inbox.py` does `executemany` then `commit()` — batch, bounded.
- `wake.py stats` is a pure read: `_ensure()` reads `PRAGMA table_info(wake)` and **early-returns** once the
  columns exist, so it does not take the write lock. My hypothesis that every `wake.py` call writes was wrong,
  and reading the function is what disproved it.

So the capture named *who was around*, not *who was holding*. **The fault was the instrument's threshold:** it
probes with a 300 ms busy timeout, which flags ordinary overlap between two writers, while the failures that
kill shifts happen after **30 seconds**. A log full of ordinary contention would be read as noise, and the real
event would be missed inside it — the same failure mode as a monitor whose output is byte-identical to health.

### The refinement

The watcher now records only a lock that survives `--streak` **consecutive** probes (3 × 3 s ≈ 9 s by default),
and prints the streak so persistence is visible. Shorter overlaps are counted in the summary and written
nowhere. Proven both ways:

```
planted 12 s lock -> LOCKED streak=3 database is locked | holders: pid 510885 python3 -c ...
planted  1 s lock -> transient only: 1 of 4 probe(s) refused, but never 3 in a row - not recorded  (0 lines)
```

Backup `wake-lock-watch.py.bak-streak-20261018`, `py_compile` clean.

**Item 584 stays OPEN, with its requirement sharpened:** not "one occurrence naming a holder" — that has
happened — but **a `streak>=3` capture that coincides with a shift kill**. The first capture satisfied the
letter of the DoD and would have satisfied nothing else, which is exactly why the DoD is being rewritten rather
than ticked.

---

## 75. ROUND 80 — THE BACKFILL WAS ALREADY IN HAND; THE RECURRENCE WAS NOT

Three checks, and the first one earned its keep before any work was done.

### 1. Item 561 is being worked, so it was not duplicated

```
item 561 | state=running | claimed_by=wake-dsh-archive:20261018 | since 04:45:58
still missing: 93 -> 68 -> 51   (measured across this round)
```

A shift claimed the 93-session backfill 25 minutes before this round began and is closing the gap steadily. **The
"before you build, prove it is not already there" step prevented re-running a dry-measured 216,738-row job on a
box that OOM-kills its API ten times a day.** That is the whole reason the rule exists, and it cost one query.

### 2. The self-audit is NOT an orphan — verified rather than assumed

`weekly-evolution.py` looked unscheduled: zero crontab matches and absent from the `for s in ...` loop. But it is
invoked **outside** the loop at `run-wake-sources.sh:206`, so it runs every 30 minutes with the sources. Its log
holds exactly one line in five days —

```
2026-10-13T01:37:01  weekly-evolution  flagged self-audit:2026-W42
```

— which is correct for a week-bucketed subject: the source says nothing when the week's row is already filed.
`grep -c weekly-evolution crontab` returning 0 was my error of scope, not a defect. **The "audits itself" half of
the brief is wired.**

### 3. The recurrence was not filed, and now is

Item 561 clears the backlog **once**. The cause remains: `push-dsh-sessions.mjs` is a client-side task whose
client is `secratary`, the frozen rollback anchor, so it stopped at the 2026-10-11 cutover while the bytes kept
arriving through the authority's own pull. Without a shipper run **from the authority**, the same gap refills
every day and the next session finds 93 more.

Filed as **item 586** (housekeeping, p3) with the exact command
(`DSH_HOME=/root/.dsh DSH_ARCHIVE_MACHINE=secratary`, cursor-based, **no `--all`**) and the warning that `--all`
on a fresh cursor is the 216,738-row job again.

**Nothing was changed this round.** Three verifications, one filing, and one duplicate avoided — which is the
correct shape for a round that arrives while another shift is mid-work on the same file.

### 75a. The diagnostic fired, and it says the function never decided

`failed` moved 9 -> 10 at 05:24:45, and the kill line now carries the facts:

```
ERROR lease for wake #1169 not renewed - killing the session to avoid a double release:
      unknown [decision=unset rc=unset attempt=unset err=none]
```

**All four unset.** Those globals are assigned in `heartbeat_lease`'s `lost` branch, immediately before its
`return 1`. So the function returned **non-zero without taking the `lost` branch** — and since the only other
return is `renew` (which returns 0), the function did not return through its own code at all.

That rules out, with evidence rather than reading:

- the store declining the heartbeat (`rc=1` -> `lost` -> reason set),
- a transient error (`rc=2` -> `_LEASE_LAST_ERR` set),
- any decision the state machine produced (it would be printed).

**What is left is an interrupt:** `heartbeat_lease` sleeps inside its `*)` branch and between attempts, and a
signal delivered while it sleeps makes `if ! heartbeat_lease` see a non-zero status with none of its own
bookkeeping done. That is a *hypothesis*, not a finding — and it is now a cheap one to settle, because the next
step is one line (`echo $?` plus the function's entry/exit into the log) rather than another round of reading.

**This is what the last three rounds bought.** §63 made the message carry `_LEASE_LAST_ERR`; §72 made it carry
the decision, rc and attempt. The first answered "a lock, not the store"; the second answered "not a decision at
all". Each round of instrumentation halved the remaining space, and none of it would have been visible from the
`unknown` that started it.

---

## 76. ROUND 81 — THE EXIT STATUS, WHICH IS THE ONLY NUMBER THAT CAN TELL AN INTERRUPT FROM A DECISION

§75a established that `heartbeat_lease` reported failure **without returning through any of its own branches**.
`if ! heartbeat_lease; then` throws away the one fact that distinguishes the remaining explanations: the actual
status. A shell reports a signal-killed function as **128+N** — 143 SIGTERM, 130 SIGINT, 137 SIGKILL — and a
function that returns normally reports its own small number.

Captured it, keeping the condition identical:

```bash
heartbeat_lease; HB_RC=$?
if [ "$HB_RC" -ne 0 ]; then
```

That is the same test as `if ! heartbeat_lease`, with the number kept, and it is safe here because this script
sets `set -u` and `pipefail` but **not** `set -e` (checked, not assumed). The kill line gains `hbrc=`.

### Two independent checks, both green

```
$ bash -c 'f(){ return 143; }; f; r=$?; if [ $r -ne 0 ]; then echo captured_rc=$r; fi'
captured_rc=143

$ bash /root/bin/wake-dispatch.sh --selftest-lease
PASS  the store saying not-claimed loses the lease
PASS  a locked store with margin left keeps trying
PASS  a locked store exactly at the margin is lost
PASS  a locked store past the margin is lost
RESULT: 0 FAIL
```

The first proves the idiom carries a signal status; the second proves this round's edits (and §72's) did not
disturb the lease state machine — the dispatcher ships its own selftest, which is a good deal better than my
reading of it. `bash -n` clean, backup `wake-dispatch.sh.bak-hbrc-20261018`.

**PENDING, and I will not call it verified:** no release has run since the edit (72 releases, 10 failed, none
since 05:25), so the new call shape is unexercised in production. The next kill prints `hbrc=`, and that single
number ends a thread that has cost four rounds:

| `hbrc=` | verdict |
|---|---|
| `143` / `137` / `130` | the function was killed by a signal — the session's death took the heartbeat with it |
| `1` with `decision=lost` | a normal loss, and the earlier `unset` was a red herring |
| `unset` again | the kill block is reachable from somewhere this session has not found |

**The pattern across §63, §72 and this round is worth stating plainly:** each fix added a *fact* rather than a
theory, and each fact halved the remaining possibilities. Three rounds of that is cheaper than one round of
guessing at a 1,400-line script — and the two shifts lost in §68 are what guessing costs.

---

## 77. ROUND 82 — THE "UNKNOWN" KILLS WERE MY OWN EDITS: I WAS REWRITING A RUNNING BASH SCRIPT IN PLACE

The diagnostic from §76 fired at 05:26:46 and printed an **impossible** line:

```
ERROR lease for wake #1190 not renewed - killing the session to avoid a double release:
      unknown [hbrc=unset decision=unset rc=unset attempt=unset err=none]
```

`hbrc=unset` cannot happen in the code I wrote: `HB_RC=$?` sits on the line immediately above the `if`, in the
same block, with no subshell and no `unset` between. So the *code that ran* is not the code on disk.

### The evidence

```
running:   502935  started 05:19:02   (10m before this)
           517765  started 05:25:03   (51s BEFORE the patch)
the patch: /root/bin/wake-dispatch.sh written 05:25:54, same inode 2164595
```

**I edited a shell script while dispatchers were executing it, by truncating and rewriting the same inode.**
Bash does not read a script into memory: it reads it **incrementally by byte offset** as it executes. Truncating
and rewriting the file moves every subsequent line to a different offset, so a running instance reads whatever
now sits at the offset it expects — a **mixture of the old and new file**, and a mixture can contain states no
version of the source can produce. `hbrc=unset` is one. `decision=unset` at 05:24 was another. The `unknown` at
04:17 was a third.

Every one of those kills happened within about a minute of an in-place edit to this file: §63 (04:17), §72
(05:18-05:24), §76 (05:25). The three rounds of instrumentation were all chasing an artifact of the way the
instrument was installed.

### Retracting my own hypothesis, in public

§75a said: *"What is left is an interrupt: heartbeat_lease sleeps … and a signal makes `if ! heartbeat_lease` see
a non-zero status with none of its own bookkeeping done. That is a hypothesis."* **It is now retracted.** The
observations it explained were produced by editing the file under a live reader, and no signal is required.
A future session should re-observe on an instance started *after* a clean atomic deploy before concluding
anything about the lease state machine.

### What this changes about procedure — the durable part

**Never rewrite a running script in place. Publish by atomic rename.**

```
cp  /root/bin/wake-dispatch.sh /root/bin/wake-dispatch.sh.new
#   edit wake-dispatch.sh.new
bash -n /root/bin/wake-dispatch.sh.new && mv /root/bin/wake-dispatch.sh.new /root/bin/wake-dispatch.sh
```

`mv` gives the new file a **new inode**; every running instance keeps the inode it opened and completes on
consistent code, and every new instance picks up the new one. The same rule applies to `wake.py`, the sources,
and anything else a cron or a shift may be mid-way through.

**This is the session's most expensive class of error and the cheapest to prevent**, and it was invisible for
three rounds because each fix looked like it worked — the *deployment* was the bug, not the fix.

**Also worth naming:** my patch scripts write with `io.open(path, "w")`, which truncates in place. Every patch
this session used that idiom. The fix is the caller's `mv`, and it is now the documented procedure rather than a
habit.

---

## 78. ROUND 83 — THE FIX WAS DEMONSTRATED AND THEN PUT WHERE AGENTS READ IT

§77 diagnosed the impossible diagnostics and stated the procedure. This round proved it and moved the rule out of
this document, because a rule that lives only in an audit document is a rule with one reader.

### Demonstrated, not asserted

```
before:  inode 2164595                               two live dispatchers, fd 255 -> the file
re-publish:  cp -p wake-dispatch.sh wake-dispatch.sh.new
             bash -n wake-dispatch.sh.new && mv wake-dispatch.sh.new wake-dispatch.sh
after :  inode 2165354
         pid 502935 -> /root/bin/wake-dispatch.sh (deleted)
         pid 517765 -> /root/bin/wake-dispatch.sh (deleted)
         bash wake-dispatch.sh --selftest-lease  ->  RESULT: 0 FAIL
```

Both running instances now hold the **unlinked old inode** and will finish on consistent code; every new
instance reads the new file. The `(deleted)` marker in `/proc/<pid>/fd/255` is the isolation, visible from
outside. A running dispatcher's fd 255 pointing at *the same inode the editor is rewriting* was the whole
defect, and it took one `mv` to remove.

### And the rule now lives where the work happens

`AGENTS.md` gained **§8 — "Never rewrite a RUNNING script in place — publish by atomic rename"** (commit
`583a690d`), carrying the measured incident, the exact command form, the inode evidence above, and the
reason it is a rule rather than a note:

> the failures it produces look like defects in the code being deployed. They survive review, they survive
> `bash -n`, and they survive a passing selftest, because the code on disk IS correct — it is the running copy
> that is not.

`AGENTS.md` is injected into sessions working under `harness-config`, so this is the one surface that reaches
an agent *before* it edits a live script. The audit document keeps the narrative; the repo keeps the rule.

**What is still owed from this thread:** an observation of the lease path on an instance started *after* the
clean re-publish. The two survivors (502935, 517765) are running mixed code by construction, so any further
`unknown`/`unset` from them is history rather than signal — and that distinction has to be stated, because the
next session will otherwise read their lines as fresh evidence.

### 78a. The 93-session backfill reached zero, measured

While this round was working, the shift on item 561 finished the job:

```
ids still absent from dsh_sessions : 93 -> 37 -> 16 -> 0
select count(*) from dsh_sessions where source_machine='secratary'  :  525 -> 618   (DoD asked for >525)
newest secratary row            :  2026-10-18T05:31:18Z
```

Both clauses of the DoD are satisfied **by measurement, not by the shift's report**. Item 561 is still `running`
under `wake-dsh-archive:20261018`'s lease, so it was **not** closed from here — closing a row another worker
holds is the exact race §12 records (a settled row's verdict must not be overwritten). The shift that holds it
should close it; if it dies first, the next session can close it on this evidence.

**What remains is the recurrence, not the backlog:** item 586 records that the shipper must run *from the
authority* or the same gap refills daily, and `AGENTS.md` §1's trap 2 names the reason — a client-side task on a
frozen host is the only thing that was shipping.

---

## 79. ROUND 84 — THE FILTER MET REAL DATA, AND TWO LONG SESSIONS WERE NOT WEDGED

Two verifications, both of things this session changed, both on production rather than on a planted case.

### The streak filter discriminates on real contention

```
quiet: 15 probe(s), the write lock was free every time          x3
transient only: 1 of 15 probe(s) refused, but never 3 in a row - not recorded
```

That middle line is a **real** lock, caught and deliberately not written: one probe out of fifteen was refused
and it did not persist. Before §74 that would have appended a log line naming innocent holders; now it prints a
summary sentence and leaves `wake-lock.log` untouched (still holding only the 05:20 capture from the old
threshold). **The instrument now separates the two states it exists to separate, on live traffic, without being
shown a planted case.**

### Two 8- and 14-minute sessions were working, not stuck

Both surviving dispatchers looked suspicious: no log output since they started, well past the 100-460 s runs
seen earlier. They are fine, and the check is worth recording because "no output" reads like the estate's oldest
failure:

```
502935  14:35  do_wait   child: timeout ... wake-run.ps1 ... -TimeoutSec 2100   heartbeat: sleep 60
517765  08:34  do_wait   child: timeout ... wake-run.ps1 ... -TimeoutSec 2100   heartbeat: sleep 60
claimed: 1167 and 1170, leases to 05:53
```

- Both have a **live runner child** (the ssh to ZABZ-TECH with `TimeoutSec 2100`), so the session is running.
- Both have the heartbeat's `sleep 60`, so the lease loop is turning.
- The long duration is the runner's 35-minute ceiling, not a hang.

**And `1170` is one of the two** — the row refunded in §71a after a lock kill had left it at 2/2 and dead. It is
running normally now, which is the refund's proof arriving on its own.

**The distinction worth keeping:** "no log output" is not "stalled" when the work happens on the far side of an
ssh hop and the log is written at settle. A wedged dispatcher and a working one look identical from the log
alone — the process tree is what tells them apart, and it takes one `ps --ppid`.
