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

---

## 8. Round 2 of the follow-up, 2026-10-22 00:05-00:35Z

**The loop's overnight numbers, measured on the authority at 00:13Z.** These are the changes the
sources added last night doing their work while nobody was awake:

| reading | 2026-10-21 22:00Z | 2026-10-22 00:13Z | what moved it |
|---|---|---|---|
| PRs open into `test` | 11 (oldest 400 h) | **2, none over 24 h** | `sources/lpt-pr-age.py` filed once; the shift it woke merged and closed them |
| blocked ledger items past their revisit | 8 | **1** | the ledger-blockers shift, re-measuring each |
| blocked items citing a RESOLVED owner row | 22 | **8** | the same shift, working the STALE list |
| blocked items, total | 85 | **72** | re-measurement, not deletion |
| source runs exiting non-zero | every tick (roadmap-supply) | **none in the last two ticks** | the 24-hour grace window |

**The promotion gate, read rather than assumed.** `main` requires **four** contexts — `CI Validation
(PR Pre-Check)`, `Check for Phantom Dependencies`, `Build image and assert the sha label` and
`Validate PR Source (Test Branch Only)` — with `strict: true` and `enforce_admins: true`, so there is
no bypass. Two consequences that each cost a round:

1. A PR **from `test` itself can never be up to date with `main`** (main carries 13 commits test does
   not), and `strict` refuses a head that is behind. `land-pr.py` now reads the required set per base
   from `/branches/<base>/protection` instead of assuming one list.
2. A promotion cut at a **stable sha** (PR #602, `promote/test-20261022`) is refused by the repo's own
   source gate, whose rule is a NAME plus a content assertion: the head must be `test` or
   `guardian/promote-test-to-main*`, and every non-merge commit it would add to `main` must already be
   contained in `origin/test`. Closed with that reason, and re-cut the sanctioned way: `origin/test`
   with `origin/main` merged in — 0 conflicts, 0 behind — as PR #603.

**`--strict-all` exists because the required set is not the safety set.** Neither `main`'s four
contexts nor `test`'s three include the frontend or backend shards, so a red shard merges and deploys.
On 2026-10-21 that is exactly what happened. For a `main` promotion the lander now requires every
completed check to be success or skipped, with two named exceptions that cannot have a verdict on a PR
head: a `cancelled` run, and `Deploy verification tests` (it verifies a deployment; on a PR it is
killed by concurrency, exit 143).

**F1-16 is done, and the shard that blocked the promotion was the proof of it.** Measured on the
deployed test host at 00:50Z, after `b52fcd423` deployed:

| route | bytes | title | canonical |
|---|---|---|---|
| `/intake` | 8,613 | Start a Repair | `/intake` |
| `/kiosk` | 8,610 | Drop-Off Kiosk | `/kiosk` |
| `/login` | 8,579 | Staff Sign In | `/login` |
| `/customer-portal/login` | 8,685 | Customer Portal Sign In | `/customer-portal/login` |
| `/` (for comparison) | 86,692 | — | `/` |

Four routes that served the homepage document now serve their own. `PUBLIC_DOCUMENT_PATHS` grew
13 → 18, and that is why Test Frontend (Shard 3/4) was red on the promotion: `routeDecision.test.ts`
asserted the old count **and** that `/customer-portal/login` was `SERVE_APP`. Both were true before the
fix and false after — **the test failed on an improvement**. Replaced the count with the contract (a
floor plus the four named routes) and ticked F1-16 in the roadmap from the deployed measurement, in one
PR (#604, merged `14920fdb0`). Ledger #901 closed `done` on that measurement (attempt 2122) — its first
close, on 2026-10-21, came from commit ancestry and was false.

**The general shape, and it is the third time tonight:** a test that encodes a *number* rather than a
*contract* fails the moment the system improves, and the failure arrives looking exactly like a
regression. Two of the three red shards in this batch were that shape (`Redirecting…`, and `13`).

**The promotion is blocked by a jammed gate, and the gate is now diagnosed and being repaired.**

`main` requires four contexts with `strict: true` and `enforce_admins: true`, so there is no bypass.
On promotion PR #605 (head `8af61f528`, run 39704415549) **every real job concluded success** — Detect
Changed Files, all four frontend shards, all three backend shards, both linters, type checking, runtime
imports, scripts smoke — plus the other three required workflows. The only failures were the two
aggregators, and the log shows why:

```
if [[ "success" != "success" ]]; then
  echo "::error::detect-changes concluded 'success'; change detection did not succeed..."
  exit 1
```

A condition that reads false while its own body runs means the two sides print identically and do not
compare equal. A gate that cannot pass jams **every** promotion to main — which is why production has
stayed on `afaddedcc` while test carried D23, the lead form, the payment step and F1-16.

Not bypassed: main has `enforce_admins`, and widening a gate to make it work is forbidden. Repair:
strip whitespace from the value before comparing it and print it between delimiters so the difference
the log hid becomes visible; the gate still refuses anything but `success`. PR #606, filed against
`test` because `Validate PR Source (Test Branch Only)` correctly refuses any non-merge commit on a
promotion branch that is not already on `test` — the first attempt, committed straight onto the
promotion branch, was refused by exactly that rule (measured, not guessed).

Ledger **#1106** (p1) carries the measurement, and **#1094** the earlier red-shard diagnosis.

**What is proven and waiting, on test only:**

| claim | measured on the deployed test host |
|---|---|
| D23, no public prices | 0 currency figures on all 13 indexable routes |
| G1-1 lead form | `lead-name`/`lead-need`/`lead-phone` on `/`, `/screen-repair`, `/phone-repair` |
| payment on create | `CreateWorkOrderPage-Dlly9bvu.js` carries the settle step; `StaffNewOrderMoney-*` the surface |
| F1-16 | the four routes serve their own 8.6 kB documents, not the 86.6 kB homepage |

---

## 9. Where the promotion actually stands, 2026-10-22 02:30Z

**Production has not moved: `main` is `afaddedcc`, `test` is `eaad63fe2`.** Everything the owner asked for
is proven on test and none of it is live. The chain that blocks it was found by reading job logs, not by
guessing, and every link is now fixed except the last:

1. **`CI Validation (PR Pre-Check)` is a required context on `main`, and its aggregator depends on every
   other job in its workflow** — including `Deploy verification tests`, which is deliberately run for
   promotions (`if: github.base_ref == 'main'`). So a `main` promotion fails when *any* of them fails.
2. **That job failed on F1-16's own fallout.** Its fixture writes every `PUBLIC_DOCUMENT_PATHS` entry at
   `dist/<path>.html` and created only `dist/assets`; F1-16 added `/customer-portal/login`, so five
   subtests died with `ENOENT …/dist/customer-portal/login.html`. Fixed on PR #608 (create the parent
   directory per path) — waiting on CI.
3. **A cancelled job is a failed required context.** On PR #608's first run `Validate Runtime Imports`
   was `cancelled` by concurrency while four of my branches ran at once; the aggregator blocks on
   `failure` OR `cancelled`, correctly, and the required context went red for a reason that has nothing
   to do with the code. Re-ran the failed jobs.
4. **Two workflows of mine were aimed at a gate that could not move.** A promotion cut at a stable sha
   (PR #602) is refused by `Validate PR Source (Test Branch Only)`; a promotion whose head *is* `test`
   (PR #594) can never be up to date with `main` (13 commits). Both closed with their reasons; the
   sanctioned flow is `guardian/promote-test-to-main-<date>` = `origin/test` with `origin/main` merged
   in, which is PR #607.

Also fixed en route and landed on `test`: **the pre-check's own guard** (PR #606). Its rendered
condition read `[[ "success" != "success" ]]` and its body still ran — a comparison of two values that
print the same. It now strips whitespace and prints the value between delimiters, so the next reader can
see the difference the log hid. The gate still refuses anything but `success`.

**Honest summary of the night:** the loop, the ledger and the roadmap reconciliation are measurably
better — 11 open PRs to 2, 8 blocked items past revisit to 1, 22 stale references to 8, zero failing
sources — and three of my own changes turned out to be what was blocking production, each found by
reading a job log rather than a diff. The last mile is one CI run away and it is a fixture, not a
feature.

---

## 10. Round 3, 2026-10-22 03:30-04:40Z — the promotion's last two inches, and the loop fixing them itself

**The fixture fix landed** (PR #608, `fee5cb8a5`): the deploy-verify suite creates the parent directory
for every public document, so `/customer-portal/login` no longer dies with `ENOENT`. Its own run went
green on the first undisturbed attempt — after two failed attempts that were **my re-runs cancelling
its jobs**, which is now a rule in `AGENTS.md` §9.

**Then the same class of defect showed up twice more, and one of them was fixed by the loop itself.**

* `verify-deploy-wait.test.mjs` asserted the wait's own output against the literal `/1\/13 document(s)/`
  and `at all 13 public documents`. F1-16 took the table from 13 to 18, so the host under test printed
  `1/18` and both assertions failed — **on an improvement**.
* While I was reading it, the loop had already done the same work: `test` head `7f0b85505` carries
  `857220ea4 Merge pull request #610 from lakewoodphone/hk/496-promotion-gate-count`. A shift filed,
  wrote and merged the widening (`1/${PATHS.length}`), which is the wake system doing exactly what it
  exists to do — and the third time tonight that a red check turned out to be a test encoding a number
  rather than a contract (`Redirecting…`, `13` documents, `13` again).

The promotion branch was updated onto that head (`56527e497`, 0 conflicts, 0 behind `main`) and the
lander is re-running the full suite with `--strict-all`.

**The count, three times in one night, is the finding worth keeping:** a test that asserts a NUMBER
about the system fails whenever the system improves, and the failure is indistinguishable from a
regression. Assert the contract — "every document in the table", "the table contains these four" — and
the test survives the improvement it was written to protect.

---

## 11. Round 3 close, 2026-10-22 05:10Z — the promotion is one class of test behind, and the class is F1-16's footprint

**Landed on `test` this round:** the deploy-verify fixture (#608, `fee5cb8a5`), the Count widening that
the loop had already done itself (#610, `857220ea4`), my `Button` adoption on the settle step (#611,
`6bd666a14`), and the portal's two raw buttons (#612, `a5f0777e6`). `test` head `a5f0777e6`, `main`
still `afaddedcc`.

**What each red check turned out to be — all four the same shape, three of them mine:**

| red check | the real cause | who wrote it |
|---|---|---|
| Test Frontend 3/4 | `routeDecision.test.ts` asserted 13 documents and `SERVE_APP` for a route that is now a document | my roadmap tick exposed it |
| Deploy verification | the fixture created `dist/assets` but not a nested `dist/customer-portal/` | my F1-16 fallout |
| Test Frontend 2/4 | `primitive-guard`: a raw `<button>` in the settle step, then two more in the portal | my #596, then the U5-1 merge |
| Test Frontend 1/4 | five `CustomerLoginGoogleStart` assertions that the login is app-rendered at `/customer-portal/login` | F1-16's footprint |

**Filed: #1129 (p1).** Its DoD deliberately requires the fix to answer the question the tests cannot:
*does `/customer-portal/login` still work end-to-end on the deployed test host* — a document that
hydrates into the login surface — and quote the rendered control, not just a green run. A test that is
made green without that measurement would hide a customer-facing break behind a passing suite.

**What is proven on test and waiting on that one class:** D23 (0 currency figures on 13 routes), the
lead form (G1-1), the payment step on the create page, F1-16 (four documents of their own). Production
unchanged.

**The pattern worth carrying forward, now three times in one night:** a test that encodes a NUMBER or a
SHAPE about the system fails when the system improves, and the failure looks exactly like a regression.
`Redirecting…`, `13` documents, `13` again, and now "the login route renders the app". Assert the
contract; every one of these would then have survived the change it was written to protect.

---

## 12. THE 2026-10-22 BATCH IS LIVE ON PRODUCTION — 07:10Z

`main` `cff4cd2ad`, deployed `cff4cd2ad172` (`/assets/index-IKrZ_5Qr.js`). Six landing cycles in one
night, each one a red check of the same class, and the last of them was mine: my `Button` import in
`PortalApprovalActions.tsx` was one directory short (`../../ui/primitives` instead of
`../../../components/ui/primitives`), which broke module resolution for a whole chunk and showed up as
**five customer-portal login test failures** — not, as first filed in #1129, as a routing regression.
That correction matters: the deployed `/customer-portal/login` had been serving its own 8,685-byte
document with its own title and canonical all along.

**Measured on the deployed host at 07:10Z (`/root/_wakeaudit/verify-production.py`):**

| claim | reading |
|---|---|
| **G1-2 (D23) no public price** | **PASS — 0 currency figures on all 13 indexable routes** |
| **payment on the create page** | **PASS — in `CreateWorkOrderPage-2n1cGckA.js`** |
| G1-1 lead form | 3/3 fields on `/` and `/screen-repair`; **0/3 on `/phone-repair`** |
| F1-16 | the four routes serve their own 8.6 kB documents (homepage 86.6 kB) |

G1-2 is **ticked from the production measurement** (roadmap RULE 4) and G1-1 is narrowed to the one
page that is missing the form — filed as **#1142**, with the question the fix must settle (is
`/phone-repair` retired under D24, or live and needing the form?).

**Two blockers closed with their measurements:** #1094 (the promotion's red shard) and #1106 (the
pre-check chain) — attempts 2264 and 2265.

**The systemic change that stopped this class recurring:** the primitive guard now runs inside
`lint-frontend`, which is in the aggregator's `needs` and therefore gates `CI Validation (PR
Pre-Check)` at PR time (PR #616). Three separate raw-`<button>` violations had reached `test` because
the guard lived only in the shards, which are not required. It cost one CI cycle per violation
discovered at promotion; it now costs seconds at the PR.

**What the six cycles actually were, in order:** the deploy-verify fixture could not create a nested
document path (#608) → the document count was hardcoded at 13 (#610, fixed by the loop itself) → my
settle step and the portal used raw buttons (#611, #612) → my Button import was one level short
(#615) → `StaffOrderNextAction` had another raw button, now gated at PR time (#616) → the portal's
fail-closed test asserted the old redirect target, which U5-1 had improved (#617).

---

## 13. Round 5 — "shifts close what they open", measured, and the half of it the loop was missing

**The measurement that started it** (attempts in the previous 24 h, `/root/work/work.db`):

```
attempts=475  exit0=268 (56%)  no-proof=125 (26.3%)
by state_after:  todo 192 | done 167 | None 49 | blocked 37 | dropped 22 | running 8
```

192 of 475 attempts left the item in `todo` and **49 attempts were never closed at all**
(`state_after` NULL). The samples name the cause: `reaper — lease expired (held by
zabz-orchestrator until …)`. A shift claimed an item, was killed before its close step, and
`work.py reap` returned the **item** to todo and wrote its own recovery row — but the **original
attempt** stayed open for ever. So the ledger could not answer *"what happened to this attempt"*,
which is the exact question every proof/closability number is built on.

**Fixed:** `work.py reap` now closes the abandoned attempt in the same transaction, with the reason
and the holder, and reports `attempts_closed` in its output. `work.py selftest` passes.

**Proven on a throwaway copy, never production** (the estate has polluted this ledger before with a
test that wrote to a real store):

```
before: ended_at=None state_after=None
reap:   reaped {"attempts_closed": 1, "count": 1, "items": [1145], ...}
after : ended_at='2026-10-22T07:22:47Z' state_after='todo'
        did=worked for a while and then the session died | CLOSED BY THE REAPER: the lease expired
        (held by proof-worker until 2026-10-22T06:00:00Z) before the shift closed it
RESULT: PASS - the abandoned attempt is closed with its reason
```

**Why this is the right half of the problem to fix in the loop, not in the shift.** A session killed at
its bound cannot run a close step; making the *prompt* ask harder cannot fix that. What can be fixed is
the ledger's honesty: every attempt now ends with a state and a reason, whichever process ended it. The
retry is unchanged — the item goes back to todo and the next shift starts fresh, which is what it wants.

The other half — *why* so many shifts are killed mid-item — is the 45-minute envelope: 16 releases in 11
days died at the wall before it was raised to 45 minutes on 2026-10-21, and the retry rate is the
number to watch next.

---

## 14. Round 6 — the lead form was missing on TEN pages, not one, and a sample is not a set

**The correction that matters.** After batch 2 deployed (`581d4dae35df`) the three-page check read
`/` 3/3, `/screen-repair` 3/3, `/phone-repair` 3/3 and I was one step from ticking G1-1. Walking the
**sitemap** instead — the set the search engine sees — said something different:

```
/                     3/3     /battery-replacement  0/3     /tablet-repair      0/3
/phone-repair         3/3     /laptop-repair        0/3     /kosher-flip-phones 0/3
/screen-repair        3/3     /data-recovery        0/3     /kosher-waze        0/3
                                                             /find-a-computer    0/3
                                                             /contact            0/3
                                                             /privacy, /terms    0/3
```

**Ten of thirteen indexable routes had no lead form.** The earlier sample of three pages answered a
question nobody asked, and the sentence I wrote from it ("absent from `/phone-repair`") was true and
badly incomplete. This is the same defect as `D5` and the same as the freshness readings: *a reading
is only as good as the set it was taken from.*

**Landed:** `fix/lead-form-service-pages-20261022` (PR #621, `e38c2cc8e`) puts the same
`LeadRequestForm` on battery-replacement, laptop-repair, data-recovery, tablet-repair,
kosher-flip-phones, kosher-waze, find-a-computer and contact — each carrying its own `location`, and
each import path **derived from that file's own footer import** rather than copy-pasted, which is the
mistake that broke module resolution in `PortalApprovalActions` on 2026-10-22. `/privacy` and `/terms`
are deliberately left alone: legal documents, and the shared footer carries the phone, hours and
address on every page. The judgement is recorded rather than silent.

**Batch 3 opened as PR #622** with every check required. G1-1 gets ticked only after the same sitemap
walk passes on production.

**The exception, recorded.** `ComputerFinderPage` keeps its own form. Shard 3/4 caught the duplicate
with `Found multiple elements with the text of: Your name` — the finder already asks for a name and a
phone (`cf-name`), and a lead form beside it is a second chooser, not a second chance. PR #623
(`fc183df0d`). So the final set is: the lead form on every indexable **service** page, the finder on
its own questionnaire, and `/privacy` + `/terms` with the footer's contact details. That is the
judgement `D5` cannot make and a human can.

---

## 15. Round 7 — G1-1 done from a sitemap walk, and a gate that cannot fail found underneath it

**Batch 3 shipped.** `main` `63ef0c67d`, deployed `63ef0c67dc34`. The walk of `sitemap.xml` on
production, not a sample:

```
10 of 13 routes carry the lead form   (/, /phone-repair, /screen-repair, /battery-replacement,
                                       /laptop-repair, /data-recovery, /tablet-repair,
                                       /kosher-flip-phones, /kosher-waze, /contact)
13 of 13 offer Call and Text          (a tel: link and an sms: link on every route, measured)
/find-a-computer                      its own questionnaire - the exception, caught by Shard 3/4
/privacy, /terms                      the footer's contact details
POST /api/computer-request            400 on an empty body at the API host: it exists and validates
```

**G1-1 is ticked from that** (PR #625, `a2c0ecec2`) and ledger **#1142** closed on the same measurement
(attempt 2295). The three-page sample that reported `3/3, 3/3, 0/3` was wrong by nine pages.

**Then the typecheck gate.** Writing the *ten* locations into the component made the compiler speak:

```
$ npx tsc --noEmit -p frontend/tsconfig.json     (on main 63ef0c67d)
src/pages/BatteryReplacementPage.tsx(85,46): error TS2322: Type '"battery-replacement"' is not
assignable to type 'LeadRequestLocation'.   ... and six more
```

**Seven real type errors were live on main**, and `TypeScript Type Checking` concluded **success** on the
very PRs that introduced them. The job's own line is
`pnpm -w run typecheck:frontend:json || echo "Frontend typecheck completed with issues"` — the failure
is swallowed there on purpose, and the aggregator is meant to read the error count out of
`ci-artifacts/typecheck/*.json`. Whatever that chain does, the measured outcome is a green check over
seven errors — **the same shape as the jammed pre-check gate**, and worse than it, because Vite strips
types without checking so production served them.

Fixed the errors (`d570a46ad`; the same tsc command now reports **0**), and filed the gate itself as
**#1157** with a DoD that requires a planted TS2322 to turn the check red — proving the chain rather
than one step.

**The lesson, stated for the third time tonight:** a gate that has never been seen to fail is not a
gate. The pre-check jammed on a comparison of two identical-looking values; this one swallows its
subprocess failure and reports on an artifact nobody verified. Both were green over a real defect.

---

## 16. Round 8 — the typecheck gate: two links fixed, the proof failed, the item stays open

**What was found** (round 7): seven TS2322 errors live on `main` while `TypeScript Type Checking` was
green on the PRs that introduced them. **What round 8 did:** chase every link between the compiler and
the verdict, and refuse to call it fixed without a proof.

| link | state | what it was |
|---|---|---|
| `.github/workflows/pr-precheck.yml` | **fixed, #626 (`ad330dc20`)** | `pnpm ... typecheck:frontend:json \|\| echo "..."` — the failure swallowed, the step's status became the echo’s 0 |
| `scripts/ci/collect-tsc.mjs` | **fixed, #628 (`b2ed5155b`)** | printed `❌ TypeScript found N type errors` and then `process.exit(0)` with the comment *"let the CI workflow handle validation"* |
| the compiler invocation itself | **unidentified** | `npx tsc --noEmit --pretty false` in `frontend/` reports **0 errors** in CI for a file that reports a TS2322 locally |

**The proof, and it failed.** Proof PR **#627** planted one line in `PhoneRepairPage.tsx`:

```ts
const plantedTypeError: number = 'this is a string'
```

With both fixes merged into its head (`c8a92a127`), the run reads:

```
backend typecheck rc=0
frontend typecheck rc=0
TypeScript analysis completed with no errors.
📊 Summary: 0 errors, 0 warnings
→ TypeScript Type Checking: success
→ CI Validation (PR Pre-Check): success
```

So **the gate is still open**, and #1157 stays open with that measurement. The branch was closed
unmerged after serving its purpose: it proved the gate is open, which is worth more than a plausible
fix.

**Two links that could not fail, found and closed anyway — and one left honest.** This is the fourth
gate defect tonight (pre-check jam, typecheck swallow, collector lie, aggregator reading an unverified
artifact) and the only one where the proof did not come good. A fix without a proof is a claim.

**Round 9 — the second proof failed too, and it narrowed the defect to one reading away.**

Proof PR #631 removed the merge-hides-the-plant hypothesis by using a **brand-new file**,
`frontend/src/proof/planted-type-error.ts`, which is inside `frontend/tsconfig.json`'s `include: ['src']`
and exists on one branch only. The CI typecheck job still reported:

```
📊 Summary: 0 errors, 0 warnings
backend typecheck rc=0
frontend typecheck rc=0
```

While the **same collector, on this host, with the same file present**:

```
📊 Summary: 9 errors, 0 warnings
❌ TypeScript found 9 type errors
exit=1
```

and its artifact names eight `.tsx` files including `src/pages/PhoneRepairPage.tsx`. So the two links
fixed in round 8 are **proven at the collector**, and the remaining link is that **the CI job does not
compile the tree the PR contains** — or is skipped in a way that still reports success. That is a
bigger finding than a swallowed exit: the frontend typecheck may be checking almost nothing, which is
consistent with seven real errors having reached production.

#1157 carries the whole chain and one concrete next reading: a temporary step printing `git rev-parse
HEAD`, `ls frontend/src/proof`, and `npx tsc --noEmit --listFiles | wc -l` inside the job, compared with
the local 9-errors/8-files. **One reading will decide it; a plausible explanation will not**, so the item
stays open.

**The D5 classification, added to §16's neighbour at 11:20Z.** 45 orphans: **16** carry a roadmap ID
that v3 retired (`F0-5..F1-9`, `L1-3`, `L1-4`, `U1-1`, `U3-1`, `U4-5..U4-7`, `F1-8`), **0** are rename
drift, and **29** carry no ID — several plainly belong to another project (`#540` SOCKS/DNS data plane,
`#572` rentals PRs) and were filed here because lpt-website was the selected project at the time.

The reconciler can see the disagreement but cannot settle it: every row needs one judgement — *was the
box retired because the work landed, or retired by mistake?* That is #1058, and its DoD now forbids the
two ways of making the number go away without answering it (a blanket close, a raised threshold) and
requires the reconciler's own next run to read **D5 0 / VERDICT CLEAN**.

---

## 17. Round 10 — the gate went red, and the ten rounds close with a measured ledger

**#1157 is PROVEN FIXED.** A planted `TS2322` in a brand-new file
(`frontend/src/proof/planted-type-error.ts`), on a PR cut from the fixed `test` — run #689:

```
📊 Summary: 0 errors, 0 warnings (tsc exit 0, reference-build exit 0)   <- backend
📊 Summary: 1 errors, 0 warnings (tsc exit 2, reference-build exit 0)   <- frontend, the plant
backend typecheck rc=0
frontend typecheck rc=1
→ TypeScript Type Checking: failure
→ PR Pre-Check Summary: failure
→ CI Validation (PR Pre-Check): failure
```

Three links were closed to get there: the workflow's `|| echo` (#626), the collector's
`process.exit(0)` after printing an error count (#628), and the reference-build exit the collector now
also reports. **Two earlier proof attempts failed** (#627, #631) and were closed unmerged rather than
dressed up — that refusal is why the third means something. The PR was closed unmerged; the gate is
what was being proved.

**The loop's own instrument now tells the two kinds of drift apart.** `lpt-reconcile.py` D5 read one
number (45) that mixed two problems; it now prints:

```
D5 live-row-with-no-box   : 45  (16 retired-id, 29 unfiled)
D5a retired-id            : #833(F1-1), #854(U4-6), #855(U4-7), #856(U4-5), #829(F0-5), #830(F0-6) …
D5b unfiled               : #540, #1046, #1047, #1048, #1052, #1053, #1056, #1102, #572 …
```

and the JSON carries `d5_counts`. A retired-id row needs one judgement (*did the box go because the
work landed, or by mistake?*); an unfiled row needs another (*which project owns this?*). One number
made both look like drift.

**What the ten rounds leave behind, honestly:**

| leg of the objective | state |
|---|---|
| blocked work re-tests itself | **done, rounds 1–2** (`due --reopen`, `ledger-blockers.py`, 8 → 1 overdue) |
| shifts close what they open | **done** — the reaper now closes the abandoned attempt too (49 in 24 h were never closed), proven on a throwaway copy |
| the ledger reconciles with the roadmap | **instrument done, work owned** — D5 is now split and countable; the 45 rows are **#1058**, whose DoD forbids a blanket close |
| every defect fixed with a measured proof | **all but the reconciliation rows**, each of which is classified and filed |
| documented, committed, pushed | yes — audit §1–17, journal handoffs H12218…H12240, everything on `offsite` |
