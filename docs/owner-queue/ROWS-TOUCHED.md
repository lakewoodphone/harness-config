# ROWS TOUCHED — every change, with its command and output

## 1. Resolved (sanctioned writes only)

Five rows, all `wake-balance`, all byte-identical to kept row `#444`. Verified
by exact normalised-question match (`INTAKE-QUANTIFIED.md` §D) and by the
queue's own `find_open_duplicate` returning `similarity 1.0`
(`INTAKE-QUANTIFIED.md` §H.1, read-only probe). This is the sanctioned
`owner-queue.py resolve … --dismissed` verb; no `sqlite3` write, no schema
change, no backup.

> Note: the brief's example syntax was
> `resolve <id> --status dismissed --why "<evidence>"`. The deployed CLI at
> `/root/bin/owner-queue.py` (sha256
> `183beb4731d7d3b205c053ebb253f2f15c220f54c8cf02e5e99e3cda262cf572`) does **not**
> accept `--status`/`--why`; `cmd_resolve` accepts `--how` (→ `resolved`) or
> `--dismissed` (→ `dismissed`). The first attempt exited 2 with
> `error: unrecognized arguments: --status …`. The working command is below.

```
$ for id in 334 429 433 440 442; do
    echo "=== resolve #$id ==="
    python3 /root/bin/owner-queue.py resolve "$id" --dismissed \
      "Exact duplicate (similarity 1.00 measured with app.owner_question_dedupe.find_open_duplicate against /root/authority.db) of kept pending row #444: identical question text, same source wake-balance. The emitter filed 6 identical pending rows for one condition; #444 is kept as the newest."
    echo "rc=$?"
  done
=== resolve #334 ===
#334 -> dismissed
rc=0
=== resolve #429 ===
#429 -> dismissed
rc=0
=== resolve #433 ===
#433 -> dismissed
rc=0
=== resolve #440 ===
#440 -> dismissed
rc=0
=== resolve #442 ===
#442 -> dismissed
rc=0
--STDERR--
```

Verification immediately after:

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT id,status,substr(resolution,1,60) FROM owner_decision_queue \
      WHERE id IN (334,429,433,440,442,444) ORDER BY id;"
334|dismissed|Exact duplicate (similarity 1.00 measured with app.owner_que
429|dismissed|Exact duplicate (similarity 1.00 measured with app.owner_que
433|dismissed|Exact duplicate (similarity 1.00 measured with app.owner_que
440|dismissed|Exact duplicate (similarity 1.00 measured with app.owner_que
442|dismissed|Exact duplicate (similarity 1.00 measured with app.owner_que
444|pending|
--STDERR--
```

**Kept: `#444`** (newest of the group — the same convention as
`scripts/collapse-owner-queue-duplicates.py`, which keeps the newest row and
marks the older copies). The kept row is item 5 on the one screen.

**Not touched:** `#445` ("the cloud authority is not on the tailnet") was already
`resolved` before this session, with the evidence `FALSE WHEN WRITTEN…`, so it
was not re-resolved:

```
$ sqlite3 'file:/root/authority.db?mode=ro' \
    "SELECT id,status,resolution FROM owner_decision_queue WHERE id=445;"
445|resolved|FALSE WHEN WRITTEN, and verified so. docs/mesh/175 state-of-the-estate section 5.2: …
--STDERR--
```

## 2. Left pending — genuinely his (the one screen)

Verified `status='pending'` at 21:24Z by
`SELECT id,status,severity FROM owner_decision_queue WHERE id IN
(228,207,448,449,279,261,303,284,439,444);` → `207|pending|high`,
`228|pending|high`, `261|pending|high`, `279|pending|high`, `284|pending|high`,
`303|pending|high`, `439|resolved|high`, `444|pending|high`,
`448|pending|medium`, `449|pending|high`.

| id | why it is his |
|---|---|
| 228 | overdue (>7d) business-subsidy decision — how much of his own money the business may keep taking; money + his own balance sheet |
| 207 | a live $85/month debit on a service he thought cancelled; deferral expires 2026-10-14 |
| 448 | resizing or capping the company's authoritative host — an irreversible spend decision |
| 449 | topping up the Telnyx account (money) so the Waze device can be sold |
| 444 | topping up the prepaid AI balance (money); no auto-recharge exists to switch on |
| 279 | Amex decline warning — credit standing |
| 261 | dropping a paid vendor / accepting a 5.5× cost failover — spend posture |
| 303 | moving the shop's customer-facing phone line — his customers |
| 284 | where a second copy of the Android signing key lives — security posture |

`#439` (`lpt-apps-01` disk) is now `resolved`, so it is **not** on the screen
even though `175` §5.1 listed it.

## 3. Left pending — NOT his, but not dismissed either

`175` §5.2 says the 90 `lpt-work-order-sweep` and 10 `lpt-board-walk-20261008`
rows are "mine to resolve out of his queue without asking him". **I did not
dismiss them**, because the brief forbids resolving a row I have not verified
myself, and proving 100 per-order payment questions wrong requires reading each
order against the comms archive and the order DB — more than the 30-minute
budget. A blanket dismissal on the strength of a document would be the same
class of defect as the rows themselves. They remain `pending` and are named as
the estate's, not his, in `ONE-SCREEN.md`.

Same for `#283` (broker one-writer vs Postgres): `175` §5.2 calls it a
development decision, but the choice is not mine to record without a measured
one-writer test, so it stays pending.
