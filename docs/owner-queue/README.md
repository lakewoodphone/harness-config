# W6 — owner-queue intake defect: measured, fixed as patches, and triaged

Ran on **LakewooechsMini** (macOS, `uname -a`: Darwin 25.5.0 arm64), reading the
authority `secratary-cloud` (Linux 7.0.0-38, `178.156.194.1`, Tailscale
`100.73.176.126`) READ-ONLY. All authority access was
`ssh -i ~/.ssh/retired-20260914/id_ed25519_hetzner root@178.156.194.1`, every
database read through `sqlite3 'file:/root/authority.db?mode=ro'`. The only writes
were the five sanctioned `owner-queue.py resolve … --dismissed` calls recorded in
`ROWS-TOUCHED.md`.

Measurement window: **2026-10-12 21:15–21:24Z** (the brief's `175` was written
05:20Z; everything below is re-measured, not quoted).

## 1. The intake defect, quantified

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT status, COUNT(*) FROM owner_decision_queue GROUP BY status;"
answered|37
dismissed|64
pending|152
resolved|197
```

After the five duplicate dismissals below, **152 pending**. Before them, 157.
`175` §2.7 measured 162 at 05:20Z; the difference is normal churn (two new rows
were filed after 05:20Z, and four were closed).

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT source, COUNT(*) FROM owner_decision_queue \
      WHERE status='pending' GROUP BY source ORDER BY 2 DESC;"
lpt-work-order-sweep|90
|16
lpt-board-walk-20261008|10
wake-balance|6
shop-intake|4
... 30 one-off sources with 1 each
```

### The top three generators

| # | source | pending | what it is | the code that files it |
|---|---|---|---|---|
| 1 | `lpt-work-order-sweep` | **90** | one nightly sweep, 2026-10-09 01:26–01:27Z, filing one raw per-order "was this paid / did this get collected?" row per work order | `/root/bin/owner-queue.py add`, one call per order. **No persistent sweep script survives on the authority** — the source label is a session string; the literal `lpt-work-order-sweep` appears only in journal `H3576`/`P2936` and `175`. The durable filing path is `owner-queue.py add` (patch 0001), and the pattern fix is `owner-queue-sweep.py` (patch 0003). |
| 2 | `lpt-board-walk-20261008` | **10** | one board walk, 2026-10-08 03:23:15–03:23:16Z (ten rows in 1.0 s — one loop) | same path, `owner-queue.py add` |
| 3 | `wake-balance` | **6** | the SAME question six times: *"The prepaid AI balance is low…"* | `/root/bin/wake-balance.py:188` `args = ["add", …]` → `_run_add()` at line 197; the 90-minute cron `41 * * * * … wake-balance --guard` |

Rows #1/#2 are 100 of 157 pending (64 %); with #3 it is 106/157 (68 %). `P2936`
said 118/162 (73 %); re-measured today it is **106/157**. The table is the
pre-dismissal reading; after the five duplicate `wake-balance` dismissals in
`ROWS-TOUCHED.md`, `wake-balance` holds 1 pending and the total is 152.

The six `wake-balance` rows are byte-identical: `334, 429, 433, 440, 442, 444`,
all `pending`, all the same `question`. The `find_open_duplicate` check that
should have stopped them exists (`/opt/company/app/owner_question_dedupe.py`,
`owner-queue.py` line 512) but the module only reached the authority on
**2026-10-12 16:11Z**, after all six were filed.

## 2. What is fixed here (patches, not installed)

See `scripts/owner-queue/README.md` for target paths and before/after. Short form:

| patch | target | fixes |
|---|---|---|
| `0001-owner-queue-hard-pending-dedupe.patch` | `/root/bin/owner-queue.py` | a **hard, local** pending-duplicate refusal on normalised question text — one condition, one pending row. Does not depend on a module that can fail to import. |
| `0002-wake-balance-pending-guard.patch` | `/root/bin/wake-balance.py` | asks the queue read-only before filing; "already pending" is success, and it marks the 12-hour marker so the hourly cron stops re-attempting. |
| `0003-owner-queue-sweep.patch` (+ `owner-queue-sweep.py`) | new `/root/bin/owner-queue-sweep.py` | bulk-intake guard: a sweep must supply a stable `subject` (the rule), is grouped to **one question per subject**, refuses a raw subject-less row, and caps a run at 3 subjects. |

**Do not install any of them** — they are delivered as patches for review.

## 3. What the queue should look like once intake is fixed

* **One condition = one pending row.** Enforced by 0001. The six wake-balance
  rows become one; the next depleted balance updates nothing and files nothing
  while a row is pending.
* **A sweep files a rule, not N orders.** Enforced by 0003. The 90 work-order
  rows should have been **~3 shop rules** (the P2936 worked example: *a finished
  order in READY_FOR_PICKUP with no payment row is collected unless the case file
  says otherwise*), each with the order numbers in `context`.
* **For the count to stop growing**, three things must change beyond the patches:
  1. the two sweep *callers* must be re-pointed at `owner-queue-sweep.py`
     (the one-shot scripts are gone; whatever re-runs a sweep must be changed);
  2. `owner-queue.py add` must stay the only write path, and
     `OWNER_QUEUE_ALLOW_DUPLICATE=1` must not be a blanket escape (0001 keeps the
     escape but only for a *deliberate* re-add after a row is closed);
  3. a question whose recommendation cannot be computed from a cited reading
     should never be filed — `P2936` failure mode 3, which no patch can enforce
     mechanically and is a review rule for generators.
* A healthy steady state is the honest queue: **the ~10 items in `ONE-SCREEN.md`**
  plus whatever the owner defers. Everything else is the estate's to resolve.

## 4. Files

* `ONE-SCREEN.md` — the ≤10 items genuinely his, one sentence + one recommendation each, in biting order.
* `INTAKE-QUANTIFIED.md` — every SQL command with its verbatim output.
* `ROWS-TOUCHED.md` — every row resolved (command + output) and the rows left pending and why.
* `../scripts/owner-queue/README.md` — patch inventory, target paths, before/after.
* `../scripts/owner-queue/*.patch` — the three patches.
* `../scripts/owner-queue/owner-queue-sweep.py` — the new sweep guard source.
