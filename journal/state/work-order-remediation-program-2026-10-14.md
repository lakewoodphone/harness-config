# Work-order backlog remediation — program state, 2026-10-14

Owner's mandate, verbatim (2026-10-14): *"keep analyzing auditing and fixing this fully end to end
afer really thinking about this, and then build way more robust scripts and docs and fix evereything"*.
This file is the durable state of that program: what is fixed, what is not, and exactly where each
remaining piece lives. It is written for a session that has no memory of the one that made it.

---

## 1. What the backlog is

The **2026-10-09 sweep's leftovers**, not the 34 standing work orders. That sweep read all 641 shop
orders, changed 115 in production and filed 108 questions to the owner; **80 were still pending** in
`owner_decision_queue` (`source='lpt-work-order-sweep'`), mapping to 91 work orders.

Progress: **80 → 38 pending**. Resolved by this program: 29 record-decided rows, then 385, 386, 387,
388, 406, 414 individually, plus **74 payment-reconciliation corrections** that were never owner
questions at all.

## 2. Findings, each with its evidence

| # | finding | evidence |
|---|---|---|
| F1 | **The read path was broken by an interpreter mismatch.** `transport.py` used a bare `python3` on the authority, which has no psycopg2; writes worked because they used the app's venv. `doctor` reported the live store DOWN. | fixed, `lpt-ops` `07a84cb` |
| F2 | **`install.ps1` deployed the read helper to a directory literally named `~`.** Every remote path is quoted and a quoted tilde does not expand, so it reported `helper: deployed` having deployed nothing. | fixed, same commit |
| F3 | **74 live orders carry a false `COULD NOT BE RECONCILED` payment note**, because an automated pass searched the untaxed amount. 254 notes were written in 8 seconds on 2026-10-14. | `lpt-payrecon`, `docs/payrecon.md` |
| F4 | **Every completion notice since 2026-02-19 has failed.** All 300 `REPAIR_COMPLETED` rows are FAILED: 252 with *"Twilio has been removed or is not configured in this environment"* to 239 distinct customers, 48 with a Twilio number error before that. `lib/twilio.ts` is a NoOp stub that can only throw. **283 of 419 finished orders have no successful contact after the failed notice.** | **NOT FIXED** — see §4 |
| F5 | **`lpt-write status set` writes a FALSE reason into `order_status_history`**: `update_order` hardcodes *"Auto-updated by secretary reconciliation"*, so a deliberate owner-directed correction is recorded as an automatic sync. | **NOT FIXED** — see §4 |
| F6 | **The money record cannot confirm a payment.** 222 orders whose notes claim a payment have **no** `SUCCEEDED` row; **301 of 369** `payment_transactions` rows carry no `orderId`. | recorded, `D3151` |
| F7 | **Store divergence:** of the 91 questioned orders, 73 exist in both stores and **47 disagree on status** — the retired `app` archive still says `COMPLETED` where live says `READY_FOR_PICKUP`. | read `operational`, never merge |
| F8 | **`READY_FOR_PICKUP` is set by an automated reconciliation that has produced demonstrably false pickup states** (WO26081112580: set on a stale January SMS about a different phone). 419 orders rest at that status. | recorded on the orders |
| F9 | **A false rule about money is in the record, and the note it was derived from disproves it.** `READY_FOR_PICKUP` is an ASSERTION that a device is PAID FOR and on the shelf — not evidence that money was taken. `H3664` read the phrase as licensing "treat it as collected"; note 2885's own action was to **move an unpaid order OUT** to `AWAITING_PAYMENT` "so the receivable stays visible". Measured: **5 orders at `READY_FOR_PICKUP` carry an unpaid-balance note**, of which **2 are genuinely uncollected today** (`WO2608060002` ~160 since 2026-08-21; `WO2603290007` 105). Both are documented by other sessions; neither has been moved out of the paid-looking state. | `L3821` |
| F10 | **The no-op communication provider claimed success while sending nothing — and it is what the factory returns by DEFAULT.** `NoOpCommunicationProvider.sendMessage` returned `success: true` with a fabricated `noop-message-<ts>` id, and `isConfigured()` returned `true`. `getCommunicationProvider()` returns it whenever `COMMUNICATION_PROVIDER` is unset, which it is in the deployed backend. Same failure as F4 but silent instead of loud. **Fixed in PR #438** (commit `6d29446f7`). No production caller used the factory, so nothing depended on the lie. | `6d29446f7` |

## 3. Fixed and verified

* **`lpt-payrecon`** — a tax-aware reconciler: `lpt_ops/payrecon.py` (pure, 27 tests, the multiplier
  proved against 14 real charges), `bin/lpt-payrecon` (scan / corrections / correct), `docs/payrecon.md`.
* **74 false payment verdicts corrected** in production, each correction naming the note it supersedes
  and stating that it proves the *method* was wrong, not that the customer paid.
* **The SMS send path is off the dead Twilio stub** — `phone-and-tech-full` **PR #438** into `test`,
  branch `lpt/dialpad-sms-send-path-20261014`, commit `32b006ea3`. `SMSService.sendSMS` now sends via
  `DialpadCommunicationProvider`. Verified: typecheck exit 0, lint exit 0, `sms.service` 19 passed,
  `repair-notification.service` 39 passed. **NOT DEPLOYED — see §4.**
* **38 notes and 2 status changes** written for the backlog itself, every one read back, all in
  `/root/lpt-ops/audit/writes.jsonl`.
* **Rows 411 and 412 closed with processor evidence** (ledger seq 118, 119): 411's 150 was charged as
  159.94 and the order's 63.98 is 60 plus tax, an internal cost line rather than a price; 412's claimed
  100 has NO charge behind it while the two figures its intake contemplated (42.65 and 60.00) both
  exist that day, so it is recorded UNVERIFIED rather than collected or chased.
* **`lpt` reads work again from ZABZ-YOGA**, launchers regenerated, `doctor` names the interpreter.
* **The audit ledger hash-chain verifies**: `lpt-write audit --verify` → `{"ok": true, "checked": 121}`.
  Every write made today is intact and untampered.
* **3 payment rows recorded from PROVEN Stripe charges**, fixing orders that claimed the money while
  `collected` read 0.00 — `lpt-record-payment` 3319 (`WO26082712685`, 309.21), 3320 (`WO2609040001`,
  309.21), 3321 (`WO2609030001`, 159.94). Each read back `collected <amount> across 1 SUCCEEDED row(s)`,
  and each is followed by a **corrective note** because the earlier note on that order said the opposite.
* **58 more payment rows recorded** for the uniquely-attributed claims — see §3c. Database total for the
  day: **61 orders, 8002.24**, which reconciles with the 60-order list (7693.03) plus the name-matched
  West order (309.21). Audit record: `journal/state/payments-recorded-2026-10-14.md`.
* **`lpt-payrecon` now has a launcher** (it shipped without one — it had a doc and no command), verified
  by RUNNING it; **`lpt-record-payment`'s misleading off-authority error** now names the machine it wants;
  and **`README.md` carries a Tools index**, which is what would have prevented the miss below.
* Journal: `L3805` (read path), `L3821` (READY_FOR_PICKUP convention), `L3822` (the bin/ miss),
  `P3187` (false status reason, resolved), `P3188` (false reconciliation), `D3151`,
  `H3667`/`H3670`/`H3672`/`H3675`/`H3676`.

## 3b. A capability I denied existing — and the work that came from finding it

Notes written earlier in this program told staff *"DO NOT create a payment_transactions row from this
note"*, and a summary told the owner the same. **`bin/lpt-record-payment` had existed since 2026-10-12**
and does exactly that, guarded, from a proven charge. It was missed because `docs/` was searched and
`bin/` was not, and because the tool has no doc of its own and is (correctly) not on the launcher list,
being authority-side.

The original instruction was not wrong about the danger — a row invented from a prose claim IS the
defect this area keeps producing — it was **too broad**: it forbade the evidenced thing along with the
unevidenced one. *"Do not fabricate" must not become "do not record."* Recorded as `L3822`, with the
rule that **"is there a tool for this?" is answered by listing `bin/`, not by searching `docs/`.**

**Opportunity this leaves open, with its criterion:** the 74 payrecon-corrected orders each have a
candidate charge matched on **amount and timestamp only**. Recording payment rows for all of them would
assert money on attribution weaker than a name match, and two orders sharing an amount on one day could
both claim the same charge. A defensible subset is the **uniquely-identified** ones — exactly one order
claiming that figure on that date AND exactly one charge of that amount that day. That is a further
analysis pass, not a guess, and it is not done.

## 3c. The uniquely-attributed payments — DONE 2026-10-14

The criterion above was then applied mechanically (`unique_attribution.py`), and the window tightened
from "the same UTC day" to **±1 day on both sides** before anything was written, because a charge of the
same amount on an adjacent day could belong to the same closing note.

* 254 reconciliation notes contained a claim; **126** had a tax-inclusive match; **60** survived the
  uniqueness test (one charge of that amount in the window, one order claiming it).
* Applied one order per invocation through the authority-side tool, which guards against duplicates —
  and **the guard proved itself**: re-running refused the 3 trial orders and the 2 recorded by hand with
  *"already recorded: … has a SUCCEEDED row. Nothing to do."* No double-counting.
* **Database state, verified by aggregate query: 61 orders, 8002.24.** That reconciles with the
  arithmetic: 60-order list 7693.03 + the name-matched West order 309.21 = 8002.24.

**Each correction note forbids creating a row "from this note".** These rows are created from the
**charge**, carrying `metadata.stripeChargeId` — which is the distinction the note was drawing.
*"Do not fabricate" must not become "do not record."*

**Orders checked and deliberately NOT recorded** are stated in the audit record rather than left silent:
they failed the uniqueness test, so a row would have asserted money on an order that might not be the
one the charge belongs to, while leaving the real order reading 0.00. Their correction notes stand.

### 3d. The attribution rule is a TOOL now, and it found a bug in itself

The analysis behind §3c lived in a scratch script outside any repo, which is exactly what the owner's
*"robust long term use tools docs and scripts, this isn't a one-time thing"* rules out. It is now
`lpt_ops/payrecon.py` (three pure functions, 7 new tests, 34 total) + `bin/lpt-payrecon attributable`
and `record --apply` + `docs/payrecon.md`. `lpt-ops` **`8d6cef6`**, pushed.

**And the tool immediately caught a scope error in the work it was written to describe.** Its first
version scoped itself to the notes that said `COULD NOT BE RECONCILED` — the failed verdicts — and found
**50** recordable orders. The question is "which orders claim a card payment with no row behind it", and
that is just as true of an order whose verdict said `PROBABLE`, so the correct scope is **every
reconciliation note**. It finds **60** and **7693.03** — which is what was actually recorded.
**A tool that disagrees with the action taken is worse than no tool**, and the check is now written
into the docs: compare the tool's total against the database.

**The window is measured in CALENDAR DAYS, not elapsed hours, and that is load-bearing.** 30 hours apart
is 1 day on the calendar and more than 1 in elapsed time, and that single case flips a match to a
non-match. A test pins it, because the alternative silently changes which orders qualify.




## 4. The one fix not yet made, and the one that needs the owner

### F4 — the completion notice: FIXED ON A BRANCH, NOT DEPLOYED

**The target list now exists**, so the re-notify decision is answerable rather than abstract:
**`journal/state/orders-never-successfully-notified-2026-10-14.md`** — **283 orders**, oldest failed
notice **2025-12-25**, newest **2026-10-09**, in bands: **131 over 120 days, 119 between 60 and 120,
33 under 60**. It carries its own caveat in the file: it is a **FLOOR, not a population count** — only
about 1.3 % of `communications` carry an `orderId`, and a customer may have been telephoned (the dialer
records calls against the customer, not the order) — so "no successful message recorded" is *"no written
notice we can prove"*, not *"never told"*.

`phone-and-tech-full` **PR #438**. `SMSService.sendSMS` called `lib/twilio.ts`, a NoOp stub whose every
method throws the exact string carried by the 252 failed rows. It now sends through
`DialpadCommunicationProvider`, instantiated directly — the pattern the three other working senders in
that codebase already use, and not via `getCommunicationProvider()` which logs without sending unless
`COMMUNICATION_PROVIDER=dialpad` (it is unset in the deployed backend).

**Deploying it restores AUTOMATIC outbound SMS to customers on every status change.** That is an
outbound-communications change and it is the owner's call, not a merge decision. Separately, the 283
orders whose completion notice failed need a decision about re-notifying, and that needs the owner's
approval of the exact message text before anything sends.

### F5 — the status writer recorded a false reason: FIXED 2026-10-14

`update_order` hardcoded `reason = f"Auto-updated by secretary reconciliation (confidence: …)"`, so a
status change made deliberately on the owner's instruction was recorded as an automatic sync — untrue
in the direction that matters, and true of two live rows from today (`WO2604210130`, `WO2608100001`).

**Done:** `update_order` now takes an optional `reason` and writes it, defaulting to the old string so
every existing caller is unchanged. Live file patched with a timestamped backup and `py_compile` before
the move; sha256 `25f5c987…` → `cf868e71…`; parameter and reason expression re-read afterwards.
`write_helper.py` passes `--reason` through and the ledger's `history_reason_stored` now reports what
the row actually carries. `lpt-ops` **`651b74b`**, pushed. Dry run on the live database shows the text
in the history INSERT params. `tests/test_writes.py`: 7 failed / 42 passed, **the same 7 with the change
stashed** — pre-existing, not mine. Pain `P3187` resolved.

**RESIDUAL RISK — CLOSED 2026-10-14 (round 2).** The addition was for a few hours present **only** in
the live file, which is hand-patched and uncommitted by instruction; re-applying the patch would have
**silently dropped** it with **no test failing**. It is now carried in `PATCH_EDITS` and mirrored in
`docs/writes.md`, with `test_the_document_carries_the_same_patch` — which failed loudly the moment the
pairs were added without the document — as the guard. `lpt-ops` **`f8fc866`**, pushed.
`tests/test_writes.py` back to 7 failed / 42 passed, the same 7 as with everything stashed.

**Still to confirm end-to-end:** the fix is verified at PLAN level (the dry run shows the reason in the
history INSERT parameters) and in the patched source, but the actual write has not yet executed on a
real status change. The ledger's `history_reason_stored` field is the check: on the next real
`lpt-write status set --reason …`, it must equal the text given. Manufacturing a status change to prove
it would be worse than the gap.

## 5. The remaining rows — 32, and how they finish

**80 → 32.** 20 physical checks and 12 decisions, in
`journal/state/work-order-backlog-residual-2026-10-14.md`.

The 29 record-decided rows, then **385, 386, 387, 388, 406, 414, 411, 412, 357, 413, 360, 361**
individually, plus **74 payment-reconciliation corrections** that were never owner questions at all.

**360 and 361 were resolved in round 7 under the objective's own directive** for cash/Zelle rows —
*"recorded honestly as unverifiable rather than chased"*:
* **360** — closed as PAID with an invoice emailed 2026-05-14, but the amount was never entered
  anywhere. That is a **missing figure on a settled order, not a debt**; nothing owed, not chased.
* **361** — the customer's own message proves a **60 Zelle was sent** but not what it paid for;
  whether it settled this Qin job or another of his, and whether the Qin was 75 or 60, is
  unestablishable. UNVERIFIED, not chased, and deliberately **not** attributed as a payment row.

**377 was examined and NOT closed, because it is the opposite of those two.** Its own description
itemises three drives to a stated total of **1210**, and the closing note records **1000 paid in cash**
— so the arithmetic gives **210 outstanding**, while a status row written the same minute says
*"still owes 250"*. That is a **real receivable on a B2B customer** (contact Moshe Bachrach), not an
unverifiable one, and whether to pursue it is the owner's. The arithmetic and the contradiction are now
recorded on the order; the row stays open on purpose.

Round-2 closures, each with processor or record evidence:
* **411** — the 150 was charged as **159.94** on 2026-09-03 15:20:49, eleven minutes before the closing
  note; the order's 63.98 total is 60 + tax, an internal cost line, not a price.
* **412** — the claimed **100 has no charge behind it**; **42.65** (= 40 + tax) and a flat **60.00** both
  exist that day, the two figures the intake contemplated. Recorded UNVERIFIED.
* **357** — a priced deliverable and a customer arriving for it, but no money recorded anywhere and a
  door hand-over leaves no row. UNVERIFIED, not chased.
* **413** — the 50 is an entry to correct, not a second charge: one back cover cannot be paid twice, and
  the same job was reconciled to 65 on 2026-09-14.

**The 14 decisions are genuinely the owner's** — each turns on money, a live customer, or a physical
hand-over. They cannot be "finished" by me without inventing an answer, and pretending otherwise is the
failure this whole program exists to stop. They are listed with recommendations and should be brought
**one at a time**. The 20 physical checks are **one walk list, not twenty questions**.




## 5. The 38 remaining rows — how to finish them

The backlog is now **not** a question-and-answer exercise, and it should not be run as one:

1. **Card claims** — do not ask the owner. Run `lpt-payrecon scan`; a tax-inclusive match settles it.
   Affected rows: 353, 411, 412, 418, 421, 427.
2. **Cash / Zelle / cheque claims** — genuinely unestablishable. Apply the owner's 2026-10-14 ruling
   (see `D3151`): record as UNVERIFIED, neither owed nor settled, **not to be chased**, and never
   fabricate a `payment_transactions` row. Rows: 357, 360, 361, 377, 385, 413, 427.
3. **Physical facts** — never ask in conversation. The 21 remaining shelf checks go on one walk list
   (`journal/state/work-order-backlog-residual-2026-10-14.md`), merged with the five the concurrent
   session already produced in `journal/state/shelf-checks-2026-10-14.md`.
4. **Genuine decisions** — the only ones worth the owner's attention: 359, 386, 387, 388, 392, 417,
   418, 419, 421, 424, 425, 427, 428.

## 6. Two traps this program paid for

* **A concurrent session worked the same backlog at 12:19 on this machine** (`H3664`), closing ten
  rows including three this program also resolved, and filing its own shelf list. P13 is live: check
  for another worker before claiming a backlog, and reconcile counts rather than assuming.
* **A bare `4294967295` from ssh on Windows is a launch/termination fault, not the remote command's
  exit status.** It appears under ssh contention and is indistinguishable from a store being down.
  `P3182`.
