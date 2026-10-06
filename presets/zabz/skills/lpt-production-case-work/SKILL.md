---
name: lpt-production-case-work
description: Use whenever a Lakewood Phone & Tech work order, ticket, customer record or case file is read, discussed or changed. Covers which production database answered, how to pull a full case, and the write-back duty that every touched case must leave clearer than it was found.
---

# Working a Lakewood production case

This skill exists because the shop's record is the product. When a case is touched and
production is not updated, the next staff member opens an order that does not tell them what
happened — and the shop has lost customer data twice.

## 1. There are TWO production databases. Name which one answered.

Measured 2026-10-06 (journal **L3351**). Both carry `orders`, `customers`, `customer_notes`,
`repair_intake_cases` and `communications`, and they have diverged — `customer_notes` id 2747
is a note on work order 2940 in one and on work order 2811 in the other.

| store | what it is | fingerprint |
|---|---|---|
| `operational` | the older RDS the authority already calls `PHONE_TECH_FULL_DATABASE_URL`. **The shop's real and recent work orders are here.** | order numbers `WO{YYMMDD}{ticket#}` |
| `app` | `lpt_prod` on Hetzner, which is what `api.lakewoodphoneandtech.com` serves. Orders froze 2026-09-14. | order numbers `WO{YYMMDD}{sequence}` |

**Rules that follow, and they are not optional:**
- Never write the word "production" without naming which store.
- Never merge two stores' views of one order into one answer. `lpt ticket` asks both and labels
  each; if a case exists in one and not the other, that divergence IS the finding.
- The `app` store's `communications` is live and its `orders` are not. Freshness in one table
  is not freshness of the database — `website-comms-push.py` runs every 30 minutes and keeps
  the old database's comms warm, so **a database kept warm by a push job is not a database in
  use**.

## 2. Pull the case before you reason about it

```
lpt ticket <key>          # WO-number, ticket number, order id, phone number, or a name
lpt --json ticket <key>   # the same, machine-readable
lpt doctor                # which stores are reachable from here, and by which route
```

The answer contains the order, the customer, **every note** (both the `workOrderId` key and the
customer-only key), the status history, charges, `SUCCEEDED` payments only, deduplicated calls
and texts, the intake case, and the customer's other orders. Read it before you act; the notes
routinely contain the constraint that decides the job.

## 3. Three number spaces. A number from one never matches another.

- **work order** — `WO` + YYMMDD + sequence, e.g. `WO26092412722`.
- **ticket number** — a plain integer, roughly 1243–12722. It is an issuer row in `tickets`.
- **300 Data Recovery lab tickets** (e.g. `73890`) are **per-device** and live in the lab's own
  RepairShopr portal and in Gmail. They are not rows in either store (journal L1511). A lookup
  for one of those will always miss; do not conclude the record is lost.

## 4. Write-back is part of touching the case, not a follow-up

Before you finish with a case you have changed or learned something about:

1. **Append a note to production** that a staff member who has never seen this conversation can
   act on. It states what changed, what was found, what is now expected, and what is still
   unknown. If it supersedes an older note, say so **by id** — never edit or delete the old one.
2. **Set the status if it moved.** Read the allowed vocabulary from the database at runtime and
   set only a value that is in it. Never invent a status, and never hardcode the list.
3. **Leave it clearer than you found it.** Concretely: no note that only says "updated"; no
   duplicate of a note already there; every number sourced; every uncertainty named as an
   uncertainty. Production already carries duplicate notes (work order 2940 has the same intake
   text twice, one second apart) — do not add a third.
4. **Read it back.** A write you did not re-read is not verified. Quote what is now stored.
5. **A correction is a new note citing the old one.** There is no edit-note and no delete-note.

The exact commands and the safety rails (dry-run by default, audited, idempotency guard,
store named explicitly) live in `lpt-ops/docs/writes.md`.

## 5. Things that are true today and will bite you if you assume otherwise

- **There are ZERO photographs in either database.** `customer_notes.attachments` is non-null on
  976 rows and every value is an empty array; `orders.attachments` is null everywhere; the 21
  rows in `issue_intake_screenshots` are all soft-deleted and their storage path does not exist
  on the server. If someone asks for the pictures, say there are none and say why — do not
  promise to fetch what is not there.
- **`devices` is a 1-row dead end.** Device truth is `orders."deviceInfo"` (a jsonb, populated on
  358 of 595 orders). `imei` is populated on 1 order and `serial` on 1. Do not promise an IMEI
  lookup.
- **Money:** quoted is `orders.total`; money received is
  `sum(payment_transactions.amount) WHERE status::text = 'SUCCEEDED'`. `PENDING` rows are not
  money received — counting them overstates receipts by more than ten times.
- **Phone matching:** production stores `+17325036608`, so a naive string compare matches
  nothing. Compare the right ten digits:
  `right(regexp_replace(coalesce(phone,''), '[^0-9]', '', 'g'), 10)`.
- **Comms are mostly not linked to a work order.** Only about 1.3% of `communications` rows
  carry an `orderId`; the rest carry a `customerId`. A "no comms on this order" reading means
  the link is absent, not that the customer was never contacted — look at the customer's comms.

## 6. Record it where it survives

A decision about a case goes in the case's own record: the production note (above), the
`lpt-hub` case file when there is one, and — if it is a rule rather than a case — the harness
journal. Never leave a decision living only in a conversation.
