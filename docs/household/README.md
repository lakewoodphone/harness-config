# Household bills (the ones the landlord collects)

The household's electric and gas are billed to the **landlord**, who passes the amount to Yocheved,
who passes it to the owner. The running record is **not in this repository** — this GitHub remote is
public.

| What | Where |
|------|-------|
| Human ledger + provenance + running balance | `/root/accounting-data/household/utilities.md` (secratary-cloud) |
| Machine ledger (append one row per bill) | `/root/accounting-data/household/utilities.csv` |
| The unmodified screenshots the amounts come from | `/root/accounting-data/household/evidence/*.webp` |
| Structured rows, one per bill | `authority.db` → `doc_registry` where `kind='bill'` |
| The thing that nags | `authority.db` → `obligation_registry` row 11 (kind `bill`, overdue) |

When a new bill arrives: append to the CSV, copy the screenshot into `evidence/`, add a
`doc_registry` row through `app.services.doc_registry.add()`, and move the obligation's `due_date`
if the story changes. Recompute the balance from the CSV, never from memory. Never delete a row —
`status`/`paid_on` mark a payment.

**Do not copy amounts, the street address, or the landlord's name into this repo.**
