# The autonomous wake system — audit, 2026-10-21

**Scope.** Everything that runs while no session is open: the flag store, the dispatcher, the fan-out,
the source loop, the work ledger, the cost ceiling, and the project loop that turns a roadmap into
shifts. Read on `secratary-cloud` (the authority) between 21:45Z and 22:20Z, live, with the command
that produced every number.

**Verdict in one line.** It works and it is well built — 150 releases today, 101 items closed at 0.060
USD each, no cap in force, both heartbeats fresh, the lease reaper running, the spend ceiling derived
from the live balance. It has three defects that quietly lose work, and one that grows without bound.
They are all measurable, and all four are fixed below.

---

## 1. What is measured healthy (so nobody "fixes" it)

| reading | value | source |
|---|---|---|
| releases today / backstop | **150 / 500** | `wake.py stats --json` |
| spend today / ceiling | **6.02 / 51.06 USD**, ceiling = balance 153.19 ÷ runway 3.0, clamped to 70 | `wake-budget.json` written 21:41:02Z by `wake_budget.py` |
| caps in force | **none** | `wake-caps-effective.json` 21:49:02Z |
| dispatcher / fan-out / sources heartbeats | 10.2 min / 0.2 min / 10.8 min | `autonomy-status.sh` 21:48:17Z |
| store rows | new 6, claimed 1, done 1018, failed 117, unverified 8, cancelled 85, dropped 16 | `wake.py stats --json` |
| selftest rows excluded from every count | 159, counted separately | same |
| ledger | todo 143, blocked 85, running 1, done 804, dropped 37 | `/root/work/work.db` |
| settled attempts carrying a proof | **1854 of 1901 (97.5 %)** | `autonomy-status.sh` VALUE line |
| reaper | ran and freed item 1039 on the last source tick | `sources.log` 21:37:01Z |
| lock watcher | 15 probes/tick, free every time | `wake-lock-cron.log` |
| releases, 11 days | **1231** — 1149 done (93.3 %), 68 failed (5.5 %), 14 unverified (1.1 %) | parsed from `wake-dispatch.log` |
| shift duration | median **356 s**, p90 **933 s**, longest success **2090 s** | the same |

The retry rule is real and does its job: a transient refusal is classified in `wake.py`
`_retryable_reason()` and refunds the attempt instead of spending the subject's life on it.

---

## 2. The four defects

### D-1 — A blocked item never comes back. The system measures it and does nothing.

`work.py due` lists every blocked item whose `revisit_at` has passed. `run-wake-sources.sh:288` runs it
every 30 minutes and **writes the count to a log nobody acts on**:

```
2026-10-21T21:37:01+00:00  ledger-due  8 item(s) past their revisit time: 337 … 457 …
```

**179 such lines** in `sources.log`; the same 8 items, the oldest **62.9 hours** past its revisit:

| item | project | p | overdue | blocker |
|---|---|---|---|---|
| 337 | housekeeping | 1 | 62.9 h | no decider for the per-message send yes; `ps_comms_waiting` = 15 customers |
| 457 | housekeeping | 2 | 62.9 h | the same blocker, filed a second time |
| 652 | housekeeping | 2 | 31.8 h | customer must bring the unit in; owner yes for a correction text |
| 296 | housekeeping | 3 | 31.8 h | DRN 2003 iPad has not checked in since 2026-10-18 — **machine-checkable** |
| 128 | housekeeping | 5 | 21.8 h | vendor order #828330 "re-verify 2026-10-21" |
| 120 | kosher-ai-filter | 4 | 21.2 h | no quiet Windows host — **machine-checkable** |
| 130 | housekeeping | 3 | 18.8 h | DRN 2001 offline — **machine-checkable** |
| 168 | housekeeping | 3 | 14.5 h | db leaked-transaction rollback, has a test |

And `work.py lint-refs` reports **STALE=22 ORPHAN=1**: twenty-two blocked items whose `blocked_on` cites
an owner-queue row that has since been **resolved**. Both findings are logged every 30 minutes and
consumed by nothing. This is roadmap box **D1-5**, and it is the single most expensive number in the
loop's own scoreboard.

*Why it is not simply an auto-release.* The 2026-10-18 note in `run-wake-sources.sh` records the
measurement that stopped it: item 292 cites resolved row 295 and that row's answer was *"I walk them,
not you"* — auto-releasing would have handed a shift work the owner had claimed for himself. So the
sweep must put the item in front of a shift that re-reads the blocker, not flip a bit.

### D-2 — The 35-minute wall cuts live work, and the retry pays for it twice.

16 of the 68 failures in 11 days sit at **2100-2104 s** — the runner's own bound, killing a session
that was still working ("LOST: the bound cut the session while it was working"). Seven **successful**
shifts finished between 1800 and 2090 s, so the wall sits *inside* the distribution of good work, not
above it. A timed-out shift's 35 minutes are gone, the item goes back to `new` after a 600 s retry, and
the next session starts from zero.

Arithmetic: p90 = 933 s, longest success = 2090 s, wall = 2100 s. The wall is the p99 of the
distribution, which means a shift that is merely slow is indistinguishable from one that is wedged.

### D-3 — A session that never started still spends the item's attempt.

At **13:08:19Z and 13:08:20Z today** two releases died in 13 seconds with

```
model: FAIL-LOUD UNRESOLVED - refusing to boot … api.deepseek.com … HttpClient.Timeout of 8 seconds
```

The system failed loudly, which is correct. But the dispatcher recorded `ssh hop failed (rc=1) … but the
session's out-file was recovered`, and `_retryable_reason()` excludes any line containing
"out-file was recovered" — so **no work was attempted and the attempt was still spent**. `max_attempts`
is 2. A model-gateway outage of a few minutes can therefore permanently kill items that were never
looked at. The same shape will hit every queued flag the next time the resolver is down.

### D-4 — The desktop accumulates two files per release, forever, and nothing removes them.

`wake-dispatch.log` says of every release, in its own words: *"kept on the desktop; names are unique per
release, so they cannot collide and need no cleanup"*. Measured on `zabz-tech-ts`:

```
2,472 wake-prompt-*.txt + 2,472 wake-out-*.txt = 238.3 MB
```

at ~150 releases/day, **+300 files/day**, and nothing will ever delete one. The content duplicates what
the session archive already holds (DSH sessions are pushed hourly to `authority.db` and the raw
transcript archive), so retention is safe; unbounded growth is not.

---

## 3. What is idle, and why that is correct

`project-keepalive` suppresses five projects honestly: `prod-db-sync` has **33 non-terminal items, all
blocked with a revisit in the future**, `cfo` 10, `lpt-sync` 6, `rental-system` 1. That is a guard
working, not a stall, and `autonomy-status.sh` says so in words.

One number to watch rather than fix: **~25 of the 85 blocked rows cite one of two owner rows**
(`#810`, `#868` — "may a shift land on origin/master"). They are distinct pieces of work behind one
decision, so they are not duplicates, but when that row is answered they all become claimable at once,
while `roadmap-supply` refills lpt-website at 3 boxes a pass. The per-project cap (3/day per project)
is what keeps that from becoming a burst.

## 4. Two readings that mislead

* `autonomy-status.sh` prints **"dispatcher heartbeat 10.2 min"**, but the heartbeat file is written by
  `wake-dispatch.sh` *when a release happens*. It is a **last-release** age, not liveness. The true
  liveness reading is the fan-out log age beside it (0.2 min). A quiet dispatcher and a dead one
  produce the same number under that label.
* `project-keepalive` reported **"lpt-website … 29 item(s) remaining"** while the ledger holds **87
  todo** rows for that project. Both are computed from the same store and they disagree, so one of the
  two counts something other than what the word says. (87 todo vs 43 roadmap boxes: the v2→v3 rename
  left ~30 stale titles behind, which is the reconciliation job `lpt-reconcile.timer` reports as 0
  because it compares boxes, not prose.)

---

## 5. The fixes, each with the measurement that proves it

Every edit was published by atomic rename (`os.replace` → new inode) after a syntax check, with a
timestamped `.bak` beside the file, so a dispatcher mid-run keeps the inode it opened (AGENTS.md §8).

### F-1 — The blocker sweep is now scheduled, and the residue becomes a shift

Three parts, because two tools already existed and nothing ran them:

1. **`work.py due --reopen`** — the only transition out of `blocked` for a date-gated item. Written on
   2026-10-21 and referenced by **no cron, no source and no script** (`grep -rn resweep|reopen` →
   nothing). The source loop now calls it and logs what it reopened, and stays silent when the answer
   is "none", which is the expected shape.
2. **`work.py resweep`** — re-tests machine-checkable blockers. Same story: built, never scheduled. Its
   own dry run: `85 blocked item(s), 3 tested, 0 cleared, 1 still blocked, 2 unknown`, and 81 rows
   `(no machine-checkable condition)`. It now runs every 30 minutes and its one-line verdict is logged.
3. **`sources/ledger-blockers.py` (new, 9,975 B)** — covers the 81 that no probe can settle. It files
   **one flag a day** (subject carries the UTC date) whose prompt carries the exact item list and
   three permitted closes, and forbids the failure that caused this: *an item may not be closed
   `blocked` with the same `blocked_on` text it already had*. Measured on its first dry run against
   the live ledger:

   ```
   {"due": 8, "stale": 22, "owner_rows": [336,462,502,810,813,814,865,868],
    "worst_overdue_hours": 63.0, "priority": "high", "prompt_bytes": 4991,
    "subject": "ledger-blockers:20261021"}
   ```

   `priority: high` because a p1 item is due and the worst is 63 h overdue — which is the rule that
   bypasses the night gate, so the overnight window is spent on the work that has been waiting longest.

### F-2 — The shift envelope: 1800 s → 2700 s (and the derived bounds follow)

`wake-budget-env.sh` now exports `WAKE_TURN_CAP_SEC=2700`. Proof — the dispatcher's own plan against a
**throwaway copy** of the store (`SMS_INBOX_DB=/tmp/…`, one done row planted as eligible, copy deleted
afterwards; the production store was never opened for writing):

```
2. timeout -k 30 3060 ssh … -TimeoutSec 3000
   (lease 1200s, heartbeat every 60s, hard timeout 3060s, runner self-bound 3000s, child-turn cap 2700s)
```

Before the change the same line read `timeout -k 30 2160 … -TimeoutSec 2100 … (hard timeout 2160s,
runner self-bound 2100s, child-turn cap 1800s)` — which is the 2100 s wall that 16 releases died on.

### F-3 — A session that never started no longer spends the item's attempt

`wake-dispatch.sh` has a new branch ahead of the generic "hop failed but the out-file was recovered"
case: when the runner exits **3** and its own words contain `refusing to boot` or `FAIL-LOUD
UNRESOLVED`, the release is recorded as

```
the session never started: the runner refused to boot after 13s (runner exit 3) - model: FAIL-LOUD
UNRESOLVED … No work was attempted, so the item's attempt is refunded and it retries later.
```

and `wake.py` matches the first line as retryable, with a **1800 s** backoff instead of the transport
600 s (so a three-hour model outage costs about two retries an hour per subject instead of eighteen,
and no subject is ever spent). The raw out-file is deliberately *not* quoted into the line, because
that is what carried "out-file was recovered" and suppressed the retry.

Proof against the real recorded text and the module's own classifier:

```
reason: the session never started          delay: 1800
transport delay: 600
recovered-hop still excluded: None
wake retry-classifier selfcheck: 11 cases, 0 failed      selftest_retryable rc: 0
MATCH: the branch would take this release   (the 2026-10-21 13:08 out-file text)
```

### F-4 — Staging retention on the desktop

New `C:\Users\ezabz\bin\wake-prune.ps1` (dry-run unless `-Apply`) and
`/root/bin/wake-staging-prune.sh` in the source loop, at most once a week (a state file, so 335 of 336
ticks cost a `stat` and no ssh). Retention 30 days; the content duplicates the archived session.

Measured before: **4,944 files / 237.5 MB**, oldest 2026-09-17. First run: `older than 30 day(s): 28
file(s), 1.9 MB → removed 28 of 28 → staging now 4,916 file(s), 235.6 MB`. Nothing newer than
2026-09-21 was touched, and nothing the archive does not already hold.

### F-5 — One reading that could not distinguish two states

`autonomy-status.sh` printed `dispatcher heartbeat 10.2 min` for a file written **when a release
happens** — so a quiet, correctly gated dispatcher and a dead one read the same. It now prints

```
liveness : last release 2.3 min ago | fan-out tick 0.5 min (LIVENESS) | sources 20.0 min
```

## 6. Still open, and deliberately not touched tonight

* **87 todo items against 43 roadmap boxes** for `lpt-website`. The v2→v3 rename left stale titles in
  the ledger; `lpt-reconcile` reports 0 because it compares boxes, not prose. This is the next
  reconciliation job, and it is lpt-website work, not wake-system work.
* **~25 blocked rows behind owner rows #810/#868** ("may a shift land on origin/master"). One decision,
  not twenty-five. When it is answered they all become claimable at once; the per-project cap bounds
  that, and `ledger-blockers.py` will now put the oldest in front of a shift daily.
* **`project-keepalive` said "29 item(s) remaining"** while the ledger holds 87 todo. Not yet
  diagnosed; both numbers come from the same store, so one of them counts something other than what
  the word says. Recorded here rather than guessed at.


---

## 7. Ten-round follow-up, 2026-10-21 22:10-22:45Z

**Round 1 — the first fix verified itself.** Every one of the eight overdue blockers was closed by
the shift with a proof-carrying attempt (`work.py show <id>`), and `work.py due` now answers *"no
blocked item is past its revisit time"*. Item 457 was dropped as a duplicate of 337; 337 became one
owner-queue row with a date; 296 became row #924; 130 was proven done (the iPad HAD checked in six
days earlier than the stored measurement said).

**Round 2 — the reconciler was closing items on commit ancestry, which is how it lied.** Twelve boxes
were `done`-in-ledger, unchecked-in-roadmap. Measuring each on BOTH deployed hosts after
`lpt-deploy-status.py --live` confirmed `deployed test dfa92f05bdd6 MATCH`:

| box | production | test | verdict |
|---|---|---|---|
| F1-11 | 301 × 3 | 301 × 3 | **ticked** |
| F1-12 | 5,905 visible chars, no error | same | **ticked** |
| F1-18 | 21 questions in the body, 22 aria-controls all resolve | same | **ticked** |
| F0-15 | route table, 126 tests | — | **ticked** |
| D1-5 | due 8 → 0 | — | **ticked** |
| G1-1 | form absent | lead-name/lead-need/lead-phone present | **promotion-blocked** |
| G1-2 | figures 1/1/8/8/8/8/9 on seven routes | 0 on all 13 | **promotion-blocked** |
| F1-16 | homepage document | homepage document | **FALSE done — reopened** |

`/intake`, `/kiosk`, `/login` and `/customer-portal/login` still answer 86,692 bytes with the
homepage title and canonical `/`, differing from `/` by 8 lines. Item #901 had been closed by
`lpt-reconcile` because commit 49c2efbf8 is an ancestor of `origin/test`. **A merge is proof of
integration, not of behaviour.** Two guards were added and are live hourly:

- **D1b** — an item whose own DoD names the deployed host (`deployed|served|no-JS|curl|document|…`)
  is split out of D1 and is never auto-closed from ancestry.
- **D4** — ledger `done` whose commits are not ancestors of `origin/test`, bounded to the last 3
  days and to tokens `git` itself confirms (the first run reported 50, because `20261020` parsed as a
  sha). Current reading: **14**, which is a worklist of squash-merges and unlanded closes.

**Round 3 — the promotion.** Three more `done` items were reopened the same way (#959, #976, #980:
their branches are pushed and NOT ancestors of `origin/test`). PR #594 (`test` → `main`, 94 commits,
49 files) is open with the full CI as the second read RULE 1b requires; G1-1 and G1-2 cannot be ticked
until it lands.

**Round 4 — no PR lives past a day.** Eleven PRs were open into `test`: four green and unmerged (one
12 days old), five with red checks, one 16 days old with no CI. Four were brought up to date with
`test` in worktrees (#583 → `1c0d40f2d`, #564 → `19b809b84`, #563 → `3d83f9a19`); #355 conflicts in 23
files and cannot be merged mechanically. New source `sources/lpt-pr-age.py` files **one flag a day**
while any PR is older than 24 h, with GitHub's own state per PR. First run:
`open=11 old=9 oldest=400.2h red=5 priority=high`.

**Round 5 — the owner's live defect, which outranks the audit.** Reported from the counter: no way to
take a payment on the work-order creation page, and opening a work order bounced back to the list.
Both measured and fixed on branch `lpt/owner-pay-on-create-20261021` (PR #596):

- `CreateWorkOrderPage` replaced itself with `<div>Redirecting…</div>` on create. It now holds the
  page and mounts `StaffNewOrderMoney` (the same `StaffOrderChargePanel`, in deposit mode) against the
  id the server returned, with the customer id read back from the created order.
- `readQueueDeepLinkFromLocation()` was called ONLY from a `useState` initialiser, so
  `/work-orders?order=<id>` arriving by client-side navigation left the queue on screen and the id
  was read by nobody. That is the bounce, exactly as described. The page now re-reads it, seeded with
  the id it already handled so closing a job does not reopen it.

**Round 6 — a non-zero exit that fired every half hour, closed properly.** `roadmap-supply --project
kosher-ai-filter` exited **1 on every tick** (21:07, 21:37, 22:37, 22:44Z) with `LEDGER-UNMAPPED`:
live ledger rows named by no roadmap item and not in the dated coverage snapshot. Two were closed
with dated `ledger_title_rules`; **seven new ones appeared inside the same half hour** because a shift
was filing the follow-ups it discovered while working that programme (#1077-#1080 in one tick). A check
whose failure list is refilled faster than it can be registered is not detecting a gap — it is
detecting that work is happening, and it teaches everyone to ignore a non-zero exit.

The fix keeps the finding and drops the churn: `ledger_live_rows()` now carries `created_at`, and a row
younger than **24 h** is reported as `LEDGER-UNMAPPED-NEW` and does **not** fail the run, while a row
still outside the register a day later still exits 1. Re-measured: `7 outside the register (0 over 24
hours old, 7 inside the grace window)`, **exit 0**, selfcheck 23/23. The first attempt inserted the
helper on the `def` line and broke the module (NameError, caught by the next run, not by the compile
check) — restored from the tagged backup and re-inserted above the definition; that is why every edit
here publishes by atomic rename with a `.bak-<tag>-<stamp>` beside it.

**Round 7 — the ledger and the roadmap disagree in a way nothing measured.** `lpt-reconcile` reported
D1/D2/D3 and (after round 2) D4. It could not see the other direction: **41 of 94 live lpt-website
ledger rows are named by no current v3 box**. The v2→v3 rewrite renamed boxes, the mapping is
regenerated FROM the document, so the new text matches and the old ledger titles are orphans — still
claimable, so a shift can spend a night on work the document no longer holds. `#1058` ("Reconcile the
fifteen v2 ledger items that no v3 box owns") has been sitting `todo` for days beside them.

Added **D5** to `lpt-reconcile` — report-only, because matching an old title to its v3 successor needs
the diff in front of you and closing the wrong one loses work that was asked for. Live at 23:06Z:

```
D1 open-but-landed 0 | D1b landed-but-host-claim 1 (#901 needs the host measured)
D2 box-ticked-ledger-open 0 | D5 live-row-with-no-box 41 | D4 done-but-not-landed 14
```

That is the honest shape of the lpt-website loop tonight: the machinery is right, and there is a
backlog of ledger hygiene that only a shift with the document open can clear.

**Round 8 — his payment fix landed, and the proof is in the served bundle.** PR #596 merged as
`b52fcd423` at 23:12Z after the full 14-check run (0 failures). Test deploy run #176 shipped it:
`deployed test b52fcd423ae2 (/assets/index-BsIhP2a2.js) MATCH`. Measured on the deployed host, not in
the repo — the entry bundle's own chunk list was walked and the new settle screen was found where it
must be:

```
SETTLE SCREEN FOUND in CreateWorkOrderPage-Dlly9bvu.js   ("Loading the payment options…")
money surface    in StaffNewOrderMoney-tE33ir6K.js
```

Two refusals on the way, both worth recording because they cost a round each:
- `PUT /pulls/N/merge` answered **405 "3 of 3 required status checks are expected"** twice while all
  three required contexts read `success`. Branch protection is `strict: true`, and GitHub words a
  *behind-the-base* refusal with the same sentence it uses for a missing check. `scripts/lpt/land-pr.py`
  now does update → wait for the three named contexts → merge, and prints `behind=` beside `required=`
  so the next reader can tell which one refused.
- The same script, asked to promote `test` → `main`, tried to *push* `refs/heads/test` (GH006, refused
  by protection). A promotion's head IS the protected branch; the push step is now skipped for it.

**Round 9 — the promotion is blocked by a red shard, and that is now a filed item, not a silence.**
PR #594 (`test` → `main`, 29 checks) has **Test Frontend (Shard 1/4) = failure** on head `2b71f827c`
(run 39694895145). The annotation carries only `Process completed with exit code 1` and
`No files were found with the provided path: ci-artifacts/test/` — the failing test is not named
anywhere a reader can see, so it has to be read out of the job log. Filed as **ledger #1094, p1**, with
that measurement as its why and a DoD that requires the test to be named from the log rather than
guessed.

Consequence, stated plainly: until that shard is green, **production does not carry** D23 (no public
prices — the site still prints figures on seven routes), the lead form (G1-1), or the payment-on-create
fix. All three are live on test and waiting on the same one thing.

**Round 10 — the red shard was ours, and the log named it.** The annotation showed only `exit code 1`;
the job log (fetched by stripping the Authorization header on the S3 redirect — forwarding it returns
`InvalidAuthenticationInfo`) named it in one line:

```
FAIL src/features/work-orders/pages/__tests__/CreateWorkOrderPage.unsaved-changes.test.tsx
  > should NOT show unsaved changes...
```

It asserted the placeholder `Redirecting…` that **PR #596 removed on purpose**. So the promotion was
not blocked by a pre-existing failure: it was blocked by **my own regression**, shipped to `test`
with a green 14-check run because the test that covered the old behaviour was in the shard set that
skipped on the PR. Fixed on `fix/owner-pay-test-20261021` (`4622c1986`, PR #600): the same test now
asserts the new surface — form gone, payment step up, open-the-order button present because the mock
returns no order body — and the behaviour under test (no unsaved-changes dialog after a create) is
unchanged. Ledger **#1094** carries the diagnosis so no shift has to re-derive it.

**What that taught, in the file's own terms:** `ci-artifacts/test/` was empty for the shard, so the
failure arrived with no report attached and no test name. The lesson is not "read harder" — it is that
**a shard which uploads nothing cannot be diagnosed from the check that ran it**, and the log is the
only place the name exists.
