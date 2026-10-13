# INTAKE QUANTIFIED — commands run and their verbatim output

All commands ran on the authority `secratary-cloud` via
`ssh -i ~/.ssh/retired-20260914/id_ed25519_hetzner -o BatchMode=yes root@178.156.194.1`
at **2026-10-12 21:15–21:24Z**, wrapped in a bounded runner that reports the
ssh exit and prints `--STDERR--` (empty in every case below). Every database
handle is the read-only URI `file:/root/authority.db?mode=ro`. Nothing here
writes to the database.

## A. Host

```
$ hostname; uname -a
secratary-cloud
Linux secratary-cloud 7.0.0-38-generic #38-Ubuntu SMP PREEMPT_DYNAMIC Fri Sep  4 09:10:14 UTC 2026 x86_64 GNU/Linux
--STDERR--
```

## B. Status counts

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT status, COUNT(*) FROM owner_decision_queue GROUP BY status;"
answered|37
dismissed|59
pending|157
resolved|197
--STDERR--
```
(exit 0; `dismissed` is 59 before the five dismissals in `ROWS-TOUCHED.md`, 64 after.)

## C. Pending by source — the generator list

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT source, COUNT(*) FROM owner_decision_queue \
      WHERE status='pending' GROUP BY source ORDER BY 2 DESC;"
lpt-work-order-sweep|90
|16
lpt-board-walk-20261008|10
wake-balance|6
shop-intake|4
zabz: owner-alert + accounting session 2026-10-09|1
zabz-yoga session 2026-10-05, robustness work on the Yoga to zabz-tech link|1
zabz-yoga session 2026-10-04|1
work_order_quarantine:seed_account_balance_monitor|1
research fleet 2026-10-06; lpt-hub/docs/operations/dialpad-to-twilio-2026-10-06.md|1
research fleet 2026-10-06; lpt-hub/docs/operations/dialpad-spend-and-build-vs-buy-2026-10-06.md|1
owner_message_queue#2563|1
owner_message_queue#2562|1
order-feed-refresh|1
lpt-ops session 2026-10-06, orphan audit of the repair-intake prefix|1
lpt-hub case iphone-whatsapp-business-kramer-7339980915-2026-10-06|1
lpt-audit-surface 20261006T172843Z.json|1
ledger-397|1
kosher-filter-ai session 2026-10-05, production deploy measurements|1
kosher-filter-ai session 2026-10-05, Android signed-release lane|1
keepalive-cfo|1
halacha repo sheilot/0002 (opened 2026-10-04), carried into the queue 2026-10-05 alongside ruling 0002|1
dsh-shift-20261005T0222Z / work item 403|1
docs/mesh/159-MESH-POST-MIGRATION.md (commit 8cdaccbd, H3570)|1
desk paper intake 2026-09-25, items 7 and 8|1
cfo-shift:cluster=desc purchase interest charge|1
cfo-shift:cluster=desc plan fee alipay|1
cfo-shift:cluster=desc npgs main|1
cfo-shift:cluster=desc mobile|1
cfo-income-extraction-2026-10-01|1
attention-sweep:bc45c8c83d27ebd4|1
Zabz attention sweep 2026-10-05 - Stripe API read of /v1/webhook_endpoints on the live account|1
SECRATARY-CLOUD 2026-10-12, sell-ready session; live Telnyx API via /fleet/telnyx/billing on mdm.abletelsolutions.com|1
Observed 2026-09-30 in the browser: EmployerResponse3 intake page, EmployerResponse2 intake page, both refusal banners; NJ DOL FAQ pages; N.J.A.C. 12:17-5.1; lpt-hub/docs/operations/payroll/Weinberg-2026-09-28/NJ-DOL-BC28-ANSWER.md|1
Bank ledger /home/zabz/accounting-data/live/accounting.db (mtime 2026-09-30 04:31 UTC); journal D330 (2026-09-20, the owner's verbatim words); reminders 452; tasks 26305 (wrongly closed) and 27215 (reopened)|1
146-AUDIT-SURFACES|1
--STDERR--
```

## D. Duplication by normalised question

```
$ sqlite3 -separator '|' 'file:/root/authority.db?mode=ro' \
    "SELECT COUNT(*) c, source, substr(replace(replace(question,char(10),' '),char(13),' '),1,110) q \
      FROM owner_decision_queue WHERE status='pending' \
      GROUP BY lower(trim(question)) HAVING c>1 ORDER BY c DESC LIMIT 25;"
6|wake-balance|The prepaid AI balance is low. Top it up so the autonomous work does not stop?
--STDERR--
```

This is the whole duplicate set: **one condition, six pending rows**
(`334, 429, 433, 440, 442, 444`). The 90 work-order rows are *not* textually
duplicated with each other; each names a different order. Their defect is
granularity (one rule became 90 questions), not repetition, which is why the fix
for them is the sweep guard and not a `DISTINCT`.

## E. Age of the pending queue

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT CASE WHEN julianday('now')-julianday(asked_at) < 1 THEN '<1d' \
                 WHEN julianday('now')-julianday(asked_at) < 3 THEN '1-3d' \
                 WHEN julianday('now')-julianday(asked_at) < 7 THEN '3-7d' \
                 ELSE '>7d' END b, COUNT(*) \
       FROM owner_decision_queue WHERE status='pending' GROUP BY b;"
1-3d|8
3-7d|125
<1d|3
>7d|21
--STDERR--

$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT MIN(asked_at), MAX(asked_at) FROM owner_decision_queue WHERE status='pending';"
2026-09-16T19:40:24.471918+00:00|2026-10-12T18:25:58.627078+00:00
--STDERR--
```

The bulk sits in the 3–7 day band — exactly the 2026-10-08/09 sweep week — while
`#228`, the item that is genuinely his and blocking, is in `>7d`.

## F. Rows filed since `175`'s 05:20Z cut

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT COUNT(*) FROM owner_decision_queue \
      WHERE status='pending' AND asked_at > '2026-10-12T05:20';"
2
--STDERR--
```

The two are `#448` (authority memory) and `#449` (Telnyx/Waze). Both are in
`ONE-SCREEN.md`; `175` §5.1 could not have carried them.

## G. The queue tool itself

```
$ python3 /root/bin/owner-queue.py list | head -1
157 row(s)
$ python3 /root/bin/owner-queue.py next
==============================================================================
QUEUE #228  [high]  asked 2026-10-01T14:29
BLOCKING  Any plan for paying yourself, and the owner-loan repayment schedule.
DEFERRAL EXPIRED 2026-10-09  (his day has passed and it is still unanswered)
...
```

The queue's own head is already the one item that is his — the defect is 151
rows behind it.

## H. The filing code for each of the top three

### H.1 `lpt-work-order-sweep` (90) and `lpt-board-walk-20261008` (10)

The literal source strings exist nowhere on the authority as code:

```
$ find /root /opt/company /usr/local/bin -xdev -type f -size -8M -not -name "authority.db" \
    -not -path "*/node_modules/*" -not -path "*/.venv/*" -not -path "*/.git/*" -print0 \
  | xargs -0 grep -Il "lpt-work-order-sweep"
/root/code/harness-config/journal/entries/handoff/H3576.md
/root/code/harness-config/journal/entries/pain/P2936.md
/root/code/harness-config/docs/mesh/175-STATE-OF-THE-ESTATE-2026-10-12.md
--STDERR--

$ ...same for "lpt-board-walk"
/root/code/harness-config/journal/entries/handoff/H3330.md
/root/code/harness-config/journal/entries/handoff/H3576.md
/root/code/harness-config/journal/entries/pain/P2936.md
/root/code/harness-config/docs/mesh/175-STATE-OF-THE-ESTATE-2026-10-12.md
--STDERR--
```

These were one-shot agent sweeps; the producing scripts did not survive. The
**durable code that files every one of those rows** is the sanctioned add path:

```
/root/bin/owner-queue.py, cmd_add (line 433), insert at line 547:
    _insert = (
        """INSERT INTO owner_decision_queue
           (asked_at, question, context, options_json, recommendation, severity,
            blocks, source, age_days, status)
           VALUES (?,?,?,?,?,?,?,?,?, 'pending')""",
```

and the duplicate check that should have stopped the wake-balance repeats
(line 512) depends on a module that can be skipped:

```
        try:
            sys.path.insert(0, "/home/zabz/personal-secretary-mvp")
            from app.owner_question_dedupe import (
                find_open_duplicate,
                find_prior_answer,
            )
            ...
        except Exception as _exc:  # never block a genuine add on this check
            print("add: duplicate check skipped (%s)" % _exc, file=sys.stderr)
```

That module (`/opt/company/app/owner_question_dedupe.py`) did in fact get it
right when probed read-only today:

```
$ python3 - <<'PY'
import sys
sys.path.insert(0,"/home/zabz/personal-secretary-mvp")
from app.owner_question_dedupe import find_open_duplicate
q="The prepaid AI balance is low. Top it up so the autonomous work does not stop?"
print(find_open_duplicate("/root/authority.db", q))
PY
{'source_table': 'owner_decision_queue', 'row_id': 444, 'question': 'The prepaid AI balance is low. Top it up so the autonomous work does not stop?', 'status': 'pending', 'asked_at': '2026-10-11T03:41:02.592030+00:00', 'similarity': 1.0}
rc=0
--STDERR--
```

— but its file mtime is **2026-10-12 16:11Z**, after the six rows. Patch 0001
makes the same guarantee inside `owner-queue.py` without an importable module and
without the silent `except`.

### H.2 `wake-balance` (6)

```
/root/bin/wake-balance.py:188
    args = ["add",
            "--question", question,
            ...
            "--source", "wake-balance"]
    try:
        rc, txt = _run_add(q, args, allow_duplicate=False)
```
called by cron `41 * * * * /usr/local/bin/cron-wrap.sh wake-balance … --guard --warn 75 --repeat-hours 12`.
`mark_warned(state, bal)` is called only when `rc == 0` (line 214-ish), so a
refusal left the 12-hour marker unset and the next hourly tick tried again. Patch
0002 makes the guard read the queue first and treat "already pending" as done.
