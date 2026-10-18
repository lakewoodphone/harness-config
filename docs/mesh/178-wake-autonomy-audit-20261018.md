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
