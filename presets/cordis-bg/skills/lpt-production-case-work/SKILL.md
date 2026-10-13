---
name: lpt-production-case-work
description: Use whenever a Lakewood Phone & Tech work order, ticket, customer record or case file is read, discussed or changed. Covers which production database answered, how to pull a full case, and the write-back duty that every touched case must leave clearer than it was found.
---

# Working a Lakewood production case

This skill exists because the shop's record is the product. When a case is touched and
production is not updated, the next staff member opens an order that does not tell them what
happened — and the shop has lost customer data twice.

## 1. There was TWO production databases. As of 2026-10-12 they are ONE. Name the store anyway.

Measured 2026-10-06 (journal **L3351**). Both carried `orders`, `customers`, `customer_notes`,
`repair_intake_cases` and `communications`, and they had diverged — `customer_notes` id 2747
is a note on work order 2940 in one and on work order 2811 in the other.

**RE-MEASURED 2026-10-12, and the split is GONE.** The two DSNs now resolve to the same host and
the same database:

```
ssh secratary-ts 'grep -E "^PHONE_TECH_FULL_DATABASE_URL=" ~/personal-secretary-mvp/.env'
  -> postgres://***:***@co8c1665c0p5k.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d5oq83veii4rlb
ssh secratary-ts 'ssh lpt-apps "docker exec lpt-backend printenv DATABASE_URL"'
  -> postgresql://***:***@co8c1665c0p5k.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d5oq83veii4rlb?sslmode=require
```

So `operational` (what `lpt-write` and the authority's `PHONE_TECH_FULL_*` call it) **is** the
store `api.lakewoodphoneandtech.com` serves. `lpt-write doctor` says the same thing in its own
words: *"store operational … the DSN the authority already calls production"*.

| store | what it is | fingerprint |
|---|---|---|
| the RDS `d5oq83veii4rlb` on `co8c1665c0p5k…rds.amazonaws.com` | **the only one.** Both `PHONE_TECH_FULL_DATABASE_URL` and the deployed `lpt-backend` point here. Recent orders through 2026-10-11 measured, and new ones created 2026-10-12. | order numbers in **both** shapes, `WO{YYMMDD}{ticket#}` and `WO{YYMMDD}{sequence}` |
| `lpt_prod` on Hetzner | **no longer reachable from the paths above.** Do not go looking for it as "the app store"; the app does not use it. If you find a second store answering, that is a NEW divergence and it is the finding — measure it, do not assume this table. |

**The rule that survives the change, and it is the one that matters:** still say which store
answered, and still compare when an order exists in one reading and not another. A single store
makes that cheap; it does not make it unnecessary.

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

- **Intake photographs DO exist — in R2, not in the database.** `repair_intake_case_photos` holds
  one row per photograph (measured 2026-10-11: 16 rows on `operational`, 1 on `app`) and the bytes
  are in Cloudflare R2 under `repair-intake/<case uuid>/<position>.<ext>`, written BEFORE the row
  so a row implies an object; `bin/lpt-storage-audit.sh` on `lpt-apps` re-checks that in both
  directions afterwards. `lpt photos <key>` prints each row with its sha256 and key. What holds
  nothing is the OLDER path: the 21 `issue_intake_screenshots` rows are all soft-deleted with no
  storage path on the server, and `customer_notes.attachments` (non-null on 976 rows) and
  `orders.attachments` are empty or null everywhere. So never say "there are no pictures" — say
  which table you looked in. (Corrected 2026-10-11: this bullet used to read "ZERO photographs in
  either database", and `lpt photos` printed "no photograph exists in this store" for
  WO26100812738, which has four.)
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

## 7. "Fully synced" is not one write — the link lives in six homes and each verifier reads a different one

Measured 2026-10-11 on WO26100812739 (Elimelech Weinreb). This is the defect that makes a fully
linked case still read as missing.

| where the case→order link lives | who actually reads it |
|---|---|
| `workflow.orderNumber` | `tools/customer/audit.py` C11 **and** `scripts/sync-health-audit.py` |
| `references.orderNumber` | `audit.py` C11 **only** — `sync-health-audit.py` ignores it |
| `references.productionOrder.orderNumber` | `audit.py` C11 **and** `sync-health-audit.py` |
| `references.websiteOrder.orderId` | the push tool's duplicate guard (`lpt-sync-to-production.py`, `doubles.py`) |
| `references.workOrderId` + `ticketNumber` | the sync contract's matcher order; `tools/case-index/doubles.py` |
| the case file's front-matter `work_order:` | `lptcase`, the case index, every human |

**Consequence, measured.** The Weinreb case had a case file, a live production order, a valid
schema-passing sync record, three photographs and two notes on the order — and
`sync-health-audit.py` still listed `WO26100812739` as *"recent active prod order with NO lpt-hub
case"*, because the record carried none of the fields that verifier reads. Writing
`workflow.orderNumber` and `references.productionOrder` moved the reverse-gap count from 16 to 15.
Its older sibling `WO26100812731` (Gestetner) has `references.websiteOrder` and every matcher and
is still counted, for the same reason.

**Why the whole 2026-10-08 intake batch is in this state:** the push tool writes the order id
back into a sync record **only for an order it created itself**. Orders created the other way —
`lpt-write order create`, as all of that day's were — write nothing back, so the record is born
unlinked and stays that way until someone does it by hand.

**So, after touching a case, do all of this, in this order:**

1. Write the order link in *every* home above, not one of them. The cheap version is four fields:
   `workflow.orderNumber` + `workflow.orderId`, `references.orderNumber` + `references.workOrderId`
   + `references.ticketNumber`, `references.productionOrder`, `references.websiteOrder`, and the
   front-matter `work_order:`. Set `references.productionOrder.linkedBy` honestly — say it was a
   hand backfill and why, so the next reader knows it was not the push tool.
2. Validate the record against `docs/customer-operations/CUSTOMER_CASE_SYNC_RECORD.schema.json`.
3. Read it back and run the three readings, leaving each count no worse:

```
python scripts/sync-health-audit.py --days 21             # personal-secretary-mvp: three-way drift + the reverse gap
python scripts/lpt-sync-to-production.py --dry-run-all    # the AUTHORITATIVE per-record push decision (read-only)
ssh secratary-ts '/home/zabz/personal-secretary-mvp/.venv/bin/python3 \
    /home/zabz/repos/lpt-hub/tools/customer/audit.py'     # the four-surface verifier; exits non-zero on real drift
```

`audit.py` must run on the authority — the only host that reaches all four surfaces (hub clone,
production Postgres, the secretary SQLite, the website). Its C11 count is a **proxy that
over-reports**, and the sync tool's own verdict outranks it: `--dry-run-all` is what decides.
4. Commit and push `lpt-hub`. Unpushed case work cannot be seen by any other machine, and
   `lptcase check` prints that warning on every run until it is pushed.

Two traps in this area, both hit for real: the identifier `createdAt` is camelCase, and PowerShell
strips embedded double quotes when handing an argument to a native command, so
`lpt sql --store operational 'select max("createdAt") from orders'` comes back as
`column "createdat" does not exist` — use `to_jsonb(orders)->>'createdAt'`, or run the SQL from a
file. And a sync record can be perfectly valid JSON that a strict reader still cannot open; read a
whole directory with `utf-8-sig` when you are checking a batch.

## 8. Before you quote a speed, and before you put a customer's data on media

The procedure is `lpt-hub/docs/customer-operations/recovered-data-delivery-to-customer-media.md`
(Windows) plus `lpt-hub/scripts/customer-operations/copy-to-stick-linux.sh` (the Linux bench).
**Read §7 of that doc before copying customer data to media.**

**Five rules for any throughput claim, on any device.** All five were learned on 2026-10-13, when
one USB stick produced four different "speeds" and three were wrong:

1. **A short write measures the cache, not the medium.** A 300 MiB `dd` reported 17 MB/s; the same
   stick sustained 19.9 MB/s on one 4 GB file and 1–3 MB/s on a folder of 1,812 files. Quote the
   transfer size, block size, whether O_DIRECT was used, and what else was on the device — or the
   number is not a measurement and any estimate built on it is fiction.
2. **`pkill -f <pattern>` kills itself.** The pattern appears in pkill's own command line, so it
   killed itself and left three `rsync` children writing for another half hour while the next
   "clean" measurement was taken. Use `pkill -x rsync` / `pgrep -x dd`, or kill by PID, and then
   **prove** the device is idle with `pgrep -ax` and `fuser -m <mount>`.
3. **`echo "$(date -u) rc=$?"` reports `date`'s exit status, not the command's.** A killed copier
   printed `rc=0` and a 6 %-complete copy looked finished. Capture `rc=$?` on its own line, first.
4. **A read straight after a write measures RAM.** A "3.5 GB/s read" was page cache. Verify after
   unmounting, reading the medium.
5. **A copier's progress line counts page-cache bytes; only `/sys/block/<dev>/stat` counts the
   medium.** When they disagree the kernel is right: a copier reporting 26 MB/s while the device
   receives 2 MB/s is describing the cache, not the stick.

**The verification contract never changes:** flush by unmounting (that is where the real write cost
appears), remount read-only, then compare file count, byte total **and per-file sha256** against the
verified source. **A copy with no PASS lines is not a delivered copy** — and do not tell the owner a
device is slow until `ps` and `fuser` say the device is idle.
