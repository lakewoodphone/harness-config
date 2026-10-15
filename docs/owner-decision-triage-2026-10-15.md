# Owner-decision queue — triage, 2026-10-15

**Before: 127 open rows. After: 25 decisions + 4 shop-floor sheets.**

The queue had become a place where engineering work went to be forgotten. This triage asked one
question of every row — *is this actually his?* — and answered it with money, customers, legal
posture, family, irreversibility, and taste as the only tests.

Every one of the 127 rows has exactly one disposition. There are no unclassified rows and none
counted twice; the triage script asserts both (`sorted(set(rows) - covered)` must be empty and the
disposition total must equal 127).

| disposition | rows | what happened |
|---|---|---|
| **Mine** | 46 | decided, and the work filed to the work ledger with its own definition of done |
| **Shop-floor** | 45 | refiled onto one walkable sheet instead of 45 separate questions |
| **His** | 25 | left open, deduplicated and ordered, each with one recommendation |
| **Dismissed** | 10 | never needed him — duplicates, a stale premise, and what the posture file forbids |
| **Answered already** | 1 | #459: he had already answered it in his own text; it was recorded verbatim |

None of the 46 "mine" rows are claimed as *done*. They are **decided and tracked**: `work.py` holds
each with a title, a definition of done, and a link back to the queue row. The distinction matters —
a resolved row is an answer, not an achievement.

## The 46 that were mine

Merges and deploys (7), infrastructure and capacity (8), schedules and configuration (6), security and
credentials (5), bookkeeping classification (9), production-data reconciliation (6), product and
pricing rules (5). Full text, per row, with the decision and its reason: the queue rows themselves
(`owner_decision_queue.resolution`), and `work.py list --project <project>` for the filed work.

The single highest-leverage decision was **D-QT1** — the integration authority. It removed a whole
class at once: rows #237, #239, #441, #461, #474, #485, #498, #501, #503, #507 and #517 were all
variations of *"may I merge/deploy/restart?"*, and the honest answer was always yes. Deciding it also
returned **13 ledger items** to `todo` that had been parked waiting on those rows.

## The 10 dismissed

#239 (superseded by #461, by its own amendment) · #447 and #487 (the frozen office box — a masked unit
there is deliberate, and `host-posture.tsv` decides) · #493 (duplicate of #449) · #499 (duplicate of
#465) · #495, #508, #513 (duplicates of #514) · #473 and #504 (duplicates of #448).

## The 45 shop-floor rows

They were the same three questions asked 45 times: *is the device still here*, *what do we charge*,
and *was the money taken*. They are now one file:
**`lpt-hubdocs/customer-operations/shop-floor-2026-10-15.md`**, in four sections — SHELF (24),
PRICES (6), MONEY COLLECTED (9), SHOP RULES (6). The file is generated from the rows themselves, so
no line was dropped in the move, and each carries its work-order number so the row can be checked
before acting — the shop has moved since the 9 October sweep.

At the counter with that list: **about thirty minutes**, and then 45 rows close at once.

## The 25 that remain his

See `residual-2026-10-15.md`, or the answer in the conversation. Two carry hard deadlines:
**#492** (NJ payroll — NJ-927 for 06/2026 is 75 days late, 09/2026 due 30 October) and **#465** (NJ
ST-50 for Q3 2026, due 20 October). Two are legal: **#510** (Apple's ABM agreement, section 2.5) and
**#511** (the camera product's cloud upload).

---

## The mechanism, so the next session can repeat it

The queue is `owner_decision_queue` on `secratary-cloud:/root/authority.db`, driven by
`~/bin/owner-queue.py` (`list`, `resolve --how`, `resolve --dismissed`, `answer`, `defer`). Work goes
to `work.py add --from-json` with `--owner-row <id>`, so a resolved row and its work are linked and
`work.py lint-refs` can prove it.

**Two rules this run produced, both worth keeping:**

1. **Resolving a row strands the ledger items parked on it.** Nothing unblocks them automatically:
   `work.py lint-refs` reports them as `STALE` and exits 1, but nothing acts on that. After resolving
   rows, sweep the ledger for items whose `owner_row` just resolved and either clear the reference or
   close the item with the reason.
2. **Text never goes through a shell.** `work.py add --from-json` and arg-list `subprocess` calls
   (no `shell=True`) is what kept the amounts intact — a lesson this queue already paid for once (P265,
   three rows lost `$`+digits).

---

*Triage by Zabz, 2026-10-15. Rows read from `owner_decision_queue` where `status='pending'`
(dumped 2026-10-15T14:0xZ, 127 rows); result verified by an independent read after the run:
`pending` went 127 → 25.*
