# The owner queue, read properly — 2026-10-14

**Why this file exists.** The badge told the owner *"158 [decisions] needing my attention."* He replied
*"so lets go through this together and knock things out one at a time."* Walking 158 rows one at a time
would be days of his life spent on work that is not his. This file is the reading that stops that: what
each row actually waits on, and whose it is.

Source: `owner_decision_queue` on the authority (`secratary-cloud`), read 2026-10-14 11:49–11:51 UTC via
`~/bin/owner-queue.py list --all --json` (502 rows). Mirror: `journal/state/owner-questions.md`.
Provenance per row is in the dump; the machine-readable copy of the queue used for this reading is at
`C:\Users\ezabz\code\lpt-queue-dump.json` (502 rows, 1,058,683 bytes, mtime 2026-10-14 11:51 local).

## 1. What the 158 actually are

| status | n |
|---|---|
| pending (the badge's number) | 162 |
| — of which not yet due (owner-named deferral still ahead) | 4 |
| — of which his day has passed, i.e. genuinely due | 6 |
| — live now | 158 |
| resolved / dismissed / answered (history) | 340 |

Severity of the 158: 1 critical, 40 high, 110 medium, 11 low. 155 of them were asked in October; the
oldest live row was asked 2026-09-16 (#78).

`source` on the rows is the tell. **80 of the 158 come from one bulk job, `lpt-work-order-sweep`** — one
sweep over the shop's history that emitted one owner-question per mis-stated work order.

## 2. Whose work is it

By the rule that the queue holds only money, customers, legal, family, irreversible things and real
taste — and that everything else is mine to finish without asking:

| bucket | n | example | who acts |
|---|---|---|---|
| **Owner, acted on today** | **6** | #207 T-Mobile; #493 Telnyx top-up | him |
| Owner, deferred to a day he named | 4 | #492 payroll (2026-10-16); #169 Felician (2026-10-30) | scheduled |
| Owner, money/legal/family/irreversible, not yet due | ~10 | #228 funding date; #284 signing-key location; #110 car; #206 DOL call | him |
| Work-order reconciliation | ~80 | #338–#425 sweep | **me** — reconcile from the terminal, Stripe, case file and the shelf |
| Engineering / dev decisions | ~45 | #283 broker writer; #501 deploy the `_db_lock` fix; #462 roll production forward | **me** |
| Standing configuration and policy | ~13 | #212 daily caps; #270 Stripe webhook; #336 counter iPad filter; #489 text-channel check | **me** |
| Duplicate / superseded / already answered | 2 | #239 explicitly superseded by #461 | **me** — close |

So: **about 20 rows were ever his; about 120 are mine wearing his name.** That is the whole reason the
badge reads 158. (This is P1 on the pain list — *"the owner's attention is spent on questions that are not
his"* — still open, still happening.)

## 3. His rows, in the order they actually matter

Not queue order. Order of what it costs to leave them.

| # | item | why now | recommendation |
|---|---|---|---|
| 493 | Telnyx is 0.01 overdrawn, both SIMs blocked for lack of funds, 5 new units cannot take a SIM | blocks every LPT NAVIGATION sale and the bench rehearsal | top up 50 USD |
| 207 | T-Mobile home internet: service already suspended for non-payment, overdue balance 105.00 | it is suspended *and* still on the books; the gateway is the open question | cancel by phone and return the gateway |
| 495 | prepaid AI balance, warn state (45.59 read 2026-10-14 11:4x, warning floor 75) | stops all autonomous work when it hits floor | top up at platform.deepseek.com |
| 465 | NJ ST-50 for Q3 2026, due 2026-10-20; register status UNRECORDED — filed or not is **unknown** | 6 days, penalty + interest | he deferred to 2026-10-16; it returns then |
| 492 | NJ payroll, no filer since Gusto cancelled 2026-10-08; NJ-927 06/2026 already 75 days late; 09/2026 due 2026-10-30 | 16 days on the second one | he deferred to 2026-10-16; it returns then |
| 228 | the business draws ~4,500/mo out of his personal accounts; measured gap 3,099.87/mo against 21,727 of capacity = 7.01 months, exhausted 2027-06 | it is the number behind every other money row | stop funding on a date he names |
| 473 | the authority's disk: 23.66 GiB database on 75 GB, 9.0 GB free; the weekly integrity check cannot run | it is the company's own records | enlarge the disk |
| 448 | the authority's memory: the API reached 14.3 GB anon and was OOM-killed 2026-10-14 05:35Z | see section 4 — this one turned out to be live | **fixed tonight, no decision needed** |
| 284 | the Android release signing key exists on one laptop only | loss is irreversible | name a second place |
| 261, 279 | recurring bills failing on cards: Deep Infra HTTP 402 since 2026-10-02 (traffic silently fails over to a lane 5.5x more expensive), plus an Amex payment failure | small now, structural later | unify on one card and fix it once |
| 303, 305 | Dialpad: ~1,260/yr avoidable spend and a phone-line decision | recurring spend | clean the account up |
| 110, 169, 206, 276, 312 | car service, Felician balance, NJ DOL call, responsa database, Yisroel's hours | his, not urgent | queued individually |

## 4. The live emergency found while reading this — and it is not in the queue

While checking the authority for this file, `company-api.service` was found **wedged**: every endpoint
(`/health`, `/docs`, `/v1/models`, `/v1/chat/completions`) returned `http=000` at an 8-second timeout, and
`/v1/models` had earlier returned `http=000` at 25.0 s.

Measured cause, not inferred:

- `memory.high` = 4 GiB, `memory.current` = 4.65 GiB → the cgroup is above its soft limit.
- `memory.events`: `high 1321123` (soft-limit throttling events), `max 433` (times it hit the hard limit).
- `memory.pressure`: **`full avg10=84.64`** — 84.6% of the last ten seconds the cgroup spent *not running*
  because of memory reclaim. That is the hang: the event loop and the autopilot thread are alive but
  stalled.
- Both the main thread and the `autopilot` thread sat in state `D` at
  `__mem_cgroup_handle_over_high` — the kernel's own over-soft-limit throttle.
- This is the same fault recorded at 2026-10-14 05:35:26Z in the kernel log: the service reached 14.3 GB
  anonymous and was killed by the **global** OOM killer.

A fix was authored for exactly this on 2026-10-14 (ledger item 165, drop-in
`40-malloc-arena.conf`, `MALLOC_ARENA_MAX=2`, with 31 of a possible 32 glibc arenas and ~1.7 GB of the
2.94 GB RSS measured in per-thread arenas). **It is effective only at the next restart, and no restart had
happened**, so it had never been tested.

**Action taken, 2026-10-14 11:55:27 UTC, and its measured result.** First a snapshot of the production
tree (`/root/company-api-restart-20261014T115527Z/`: `git-status.txt`, `uncommitted-tracked.diff` 11,228
lines, `HEAD.txt` = `561535b78173dcd78e95e2c65449b84db87cf7fb`, `mem-before.txt`), then
`systemctl restart company-api`.

The posture guard was run on the authority and allowed it (recorded, not assumed):
`guard-service-state.sh --host secratary-cloud --op restart` → `ALLOW: secratary-cloud is WRITABLE. THE
AUTHORITY. Sole writer of the company database at /root/authority.db.` exit 0.

| reading | before 11:55:27Z | after 11:58:51Z |
|---|---|---|
| `MemoryCurrent` | 4,641,349,632 (4.65 GB) | 1,261,244,416 (1.26 GB) |
| `/health` | `http=000` t=6.0 s (and t=8.0 s earlier) | `http=200` t=0.0057 s |
| `/v1/models` | `http=000` t=25.0 s | `http=200` t=0.0026 s |
| `/docs`, `/openapi.json`, `/v1/chat/completions` | `http=000` t=8.0 s | `/docs` `http=200` t=0.0006 s |
| cgroup `memory.pressure` | `full avg10=84.64` | `full avg10=0.00` (total 0) |
| `MALLOC_ARENA_MAX=2` in the process env | absent (0 matches) | present (1 match) |
| box memory free | 4,021 MiB free, 5,530 MiB swap used | 7,135 MiB free, 3,482 MiB swap used |

Readiness took **2 probes, about 10 seconds.** Total service interruption for a service that had already
been answering nothing for over 50 minutes is therefore ~10 s. New MainPID 815621, `NRestarts=0`. The
boot journal now carries the application's own INFO format again (`app.agent_bus`, `app.services.*`,
`app.main`) — which is the same evidence the kernel's `app_voice` check reads, and it was the check's own
subject before the restart.

**The unresolved part, which needs engineering and not a decision:** `run_once` runs on the API's own
event-loop path and logged `run_once timed out after 600s — ABANDONING it (the thread keeps running; it
cannot be killed)` at 2026-10-14 11:05:01. The abandon-and-continue design means one slow autopilot run
can stall the whole API. The restart cleared the symptom; the structural fix is to stop `run_once` from
being able to block the loop.

**Correction, 2026-10-14 12:2x UTC. The restart above was reported as a fix and was not one.** It
answered for about nine minutes and went dead again. The memory-cgroup throttle I measured is real and is
an *amplifier*; **the cause** is `_db_lock` held across SQLite calls by the autopilot thread, traced to
file and line and reproduced (5.700 s → 0.0014 s) — see `H3663`. Three fixes are built and not deployed:
`fix/autopilot-db-lock-shared-resource-20261014` (the cause) and `hk/153-bound-db-lock` +
`hk/168-prune-outside-lock` (the waiter). As of 12:15Z the service is `active` (MainPID 861944), `/health`
`http=200` at 1.45 s, and the write lock acquires **5/5 in 0.00 s** — up, not fixed.

**One correction to the kernel's own report, for the record.** `app_voice` fired HIGH with *"its INFO
narration is suppressed (root logger level or handlers)"* — and that conclusion was wrong. The logger was
fine; the loop was starved. The check's docstring already named this second cause (*"or a wedged loop"*)
and its summary text did not, so the report sent a reader to look at logging configuration instead of at
the process. **`app_voice`'s summary has been corrected and verified**: it now reads the unit's cgroup
`memory.pressure`, distinguishes a stalled process from a logging regression, and reports how many lines
came from the app at *any* level. On the incident it now reads: *"…throttled: … cgroup memory pressure full
avg10=84.64 … This is a STALLED PROCESS, not a logging regression."* Backup:
`/root/ceo-kernel/ck/sentinel.py.bak-voicepressure-20261014T120534Z`.

## 4b. What one batch of the queue actually cost, measured

Ten pending `lpt-work-order-sweep` rows (ids 338–347) were worked end to end by a mesh agent on
`zabz-tech-linux`. Result: **1 SOLVED from the record, 1 SOLVED-BY-CONVENTION, 1 STALE, 5
NEEDS-A-SHELF-CHECK, 2 genuinely the owner's.** Report: `journal/state/wo-sweep-pilot.md`. That is the
ratio to expect from the other 70: they are not 70 questions, they are a handful of questions plus a pile
of records and one walk through the shop.

The owner-approved payment reconciliation over the same period: **254 BILLING notes** written to
production (one per touched order, read back, idempotent), **0 `payment_transactions` rows created**,
48 of 126 card claims matched a Stripe charge and only 20 uniquely (16 verified within ±6 h), 77 matched
nothing and say so, and every cash/Zelle/check claim is marked *recorded at closing, not independently
verified*.


## 5. What I am doing about it (no decision needed)

1. **The 80 work-order rows** — reconcile each against the terminal, Stripe, the case file and the shelf;
   write the finding back to the production order as a note (never an edit of an old note); resolve the
   queue row. Where the amount exists only in the owner's memory and nowhere in any record, it is asked
   once with a recommended figure, not 80 times.
2. **The ~45 engineering rows** — deploy, merge, roll forward, close. The dev questions the owner has
   already told me are mine.
3. **The 2 superseded rows** — close with the reason.
4. **The queue's own defect** — a row that is not his should never have landed in his queue. Two rows
   (#218, #239) carry the note *"SEAT-OWNED, not an owner decision"* in their own deferral text, which
   means the workflow already knew and wrote it into the wrong table anyway.

## 6. What is still unknown

- Whether NJ ST-50 for Q3/2026 and NJ-927 for 06/2026 and 09/2026 have actually been filed. The register
  says `UNRECORDED`; that is a statement about our records, not about the portal. Only the portal — behind
  his login — can settle it. This is why both tax rows ask him and why neither could be closed by me.
- Whether the 400+ orders at `READY_FOR_PICKUP` have customers who were told to collect them. All 300
  `REPAIR_COMPLETED` notification rows in `communications` are `FAILED` (measured 2026-10-14, handoff
  H3659), the newest 2026-10-12.
