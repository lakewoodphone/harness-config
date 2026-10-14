# Shelf checks the owner's queue was hiding — 2026-10-14

Five rows in the owner's decision queue were not questions for him at all. They were **one walk through
the shop**. Source: the 2026-10-14 work-order pilot over `owner_decision_queue` ids 338–347
(`journal/state/wo-sweep-pilot.md`, run on `zabz-tech-linux`).

Each line names the device, the customer, the phone number and what to do when you find it. Read the
order before acting: production store `d5oq83veii4rlb`, `orders.orderNumber` as the key, and
`customer_notes.content` holds the history.

| # | look for | customer | tick when |
|---|---|---|---|
| 338 | **Samsung A509** — order `WO2512190001`, order id 1 | Mattis Klein, 848-329-1230 | Re-test charging. The record stops at reassembly (last note 2025-12-23 "Ringel put it back together"); the order is `UNFIXABLE` with **no status-history row and no outcome note at all**. If it charges, it is a finished repair needing a price and a customer notice. If it does not, add the failing-test note. If it is not here, tell the owner the outcome is lost. |
| 339 | **QIN F30** — `WO2512230001`, order id 37 | Elchonon Zelman, 347-642-1298 | Two records contradict: the April status history and note 1196 say the device is **not** in the shop; a business-line SMS in the customer's own thread says **"Correct, we have it."** Whichever is true, the customer is asking for data off it. If it is here, tell him the cancellation note was wrong and the data request is live. |
| 342 | **Galaxy Tab S6 Lite with the kosher-play filter** — `WO2601010001`, order id 74 | 929-454-4695 | The order says "Never came" (2026-01-21), but the shop later sent drop-off instructions and asked for the PIN, and the customer answered. If the tablet is here, open a fresh work order. If not, reply that the filter request is still open. The $50 in the workbook is a workbook figure, **not** a quote to him. |
| 345 | **Kyocera E4610 (water damaged)** — `WO2602130002`, order id 629 | Simi Roth, 718-698-4226 | The order is `CANCELLED` (auto-closed 2026-07-22 for never being picked up) yet note 1310 (2026-05-20) says it was still awaiting pickup, so it may still be here. The $50 recovery attempt was **never authorised** and no payment was ever taken. If it is here, ask the owner before contacting her or disposing. |
| 347 | **A loaner phone** — issued on `WO2602190001`, order id 760 | Zalmin Trabitzsky, 215-436-5006 | `orders.description` says "Took a loaner phone" and nothing anywhere records its return. Check the loaner shelf. If a loaner is missing, he has had it since February. |

## Why this list exists

The queue row asked the owner "is this device still in the shop?" for each of these. That is not his
question — it is a physical fact about the shop floor, and it should never have needed him. The rows are
now closed with the reason, and this list is the action.
