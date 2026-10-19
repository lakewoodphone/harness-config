# The old work-order backlog - what is left for a human, 2026-10-14 (round 2)

The 2026-10-09 sweep filed 108 questions to the owner. **80 were still open.** As of this writing **32 remain**: 20 physical checks and 12 decisions.

Everything else was closed out of production: 29 record-decided rows, then 385, 386, 387, 388, 406, 414, 411, 412, 357 and 413 individually, plus **74 payment-reconciliation corrections** that were never owner questions at all (they were false verdicts written by an automated pass on 2026-10-14; see `lpt-ops/docs/payrecon.md`). Every write is in `/root/lpt-ops/audit/writes.jsonl`.


## 1. THE WALK LIST - one pass through the shop

These are not questions. Each is a physical fact about the shop floor, and asking the owner to answer twenty of them in conversation is the wrong instrument. Walk once, tick them off.

Five of these were already turned into physical checks by a concurrent session on 2026-10-14 (`journal/state/shelf-checks-2026-10-14.md`); they are marked **[also on the 12:19 list]** so the walk does not happen twice.

| queue id | order | the one thing to establish |
|---|---|---|
| 353 | WO2603290007 | This Kyocera screen-and-cable job sits in READY_FOR_PICKUP, which for you means done and paid, but its own workbook note says the walk-in kid DID NOT PAY and no payment was ever recorded - was the $105 collected, or is it still owed? |
| 356 | WO2604210010 | This Seagate drive was un-closed on 2026-10-08 (READY_FOR_PICKUP to AWAITING_PARTS to UNFIXABLE) with no reason recorded, yet the order says the data was intact, the drive had been ready since April and the customer was told it was in the p |
| 368 | WO2606160003 | This cancelled laptop-charging order has order-tagged texts from 2026-07-02 in which we gave a drop-off address and the customer replied 'I dropped it' - is there a laptop here for dovid auman that was never handed back when the job was can |
| 374 | WO2607200001 | The order was closed UNFIXABLE, but the customer's own SMS says they left their USB in a bag with their name and phone number in the hallway closet drop-off, and the order records no return of it. Is that USB still in the shop, and should s |
| 375 | WO2607210001 | WO2607210001 was cancelled on 2026-07-27 with no reason recorded, but the customer's texts on the file keep asking for an update on the GoPro camera - is the camera still on the shelf, and is this job dead? |
| 379 | WO26072412524 | WO26072412524 has read CANCELLED since 2026-07-30, yet the Pixel 6 was left disassembled on the bench and the screen cracked during the repair was never recorded as settled - is this job dead, and is the phone still here? |
| 380 | WO2607290002 | Nothing on this row says why or when the job was cancelled - there is no cancellation row and no note for it, while the last worked entries are the $150 quote and a 3m45s call to the customer - is the rabbi's IdeaPad still in the shop, and  |
| 382 | WO2608050001 | WO2608050001 for the four SD cards is CANCELLED with no notes and no charge, but the case file shows card 1 was recovered and card 4 got a conductive-pad repair attempt - was the customer told the outcome and given the cards back, and did w |
| 383 | WO26080512558 | WO26080512558 (Glick, Chipsbank CBM2199 USB drive) is UNFIXABLE, but the brief holds no message, no note of the customer being told, and no record of the drive being returned - is the drive still on the shelf, and has Glick been contacted a |
| 389 | WO2608110004 | WO2608110004 is CANCELLED with no note saying why, yet the calls show you ordered an adapter for his laptop and told him you had it - is this job dead, or does it need reopening? |
| 394 | WO26082712646 | Order 2785 was closed UNFIXABLE on 2026-08-29, but its own record says the customer was told a lab quote is the next step before any go-forward decision - do we still owe him that lab quote (so the job should be back on the open board), or  |
| 395 | WO26082712653 | Goldberger's Galaxy A54 reads CANCELLED, but the intake text still says the phone needs bench diagnosis and the lpt-hub case galaxy-a54-goldberger-2026-06-29 is open with a 349 quote - is that job dead and the phone back with the customer,  |
| 396 | WO26082712655 | Lachman dropped off a bag of customer drives for diagnosis and the order is CANCELLED with no outcome recorded and no case file - are those drives still in the shop, or did they go back to him? |
| 397 | WO26082712657 | Is Shimon Vogel's HP Compaq Elite 8300 Ultra Slim still in the shop? Its work order reads CANCELLED while the linked case file is open at 'parts' with a 65 quote for diagnosis plus CMOS battery, and no outcome is recorded anywhere. |
| 398 | WO26082712660 | Is Shimon Vogel's HP ProDesk 400 G4 Desktop Mini still in the shop? Diagnosis was done, a CR2032 CMOS battery was advised, and the order still reads CANCELLED with the case file open at 'waiting' - was the battery fitted and the machine ret |
| 400 | WO26082712665 | Jacobowitz's Kyocera E4610 was bench-confirmed to have motherboard damage from an earlier charging-port repair and the row says the repair-path decision was still pending - is that phone still in the shop, and is the job dead or was it sett |
| 403 | WO26082712677 | Was Kleimar's Moto G Play screen actually fitted and the phone made ready? The row reads READY_FOR_PICKUP and an SMS said completed, but the row itself says compatibility was still to be confirmed before install, the ledger has no READY_FOR |
| 405 | WO26082712684 | Is the A02s screen actually replaced? The order is marked READY_FOR_PICKUP and a pickup text went out on 2026-09-01, but the order's own text says the first screen came in defective and the job was waiting on the reordered part, and nothing |
| 420 | WO26092412722 | Has Devorah Goldberg's iPad actually been collected? The order was closed as finished on the strength of a note saying the title reads 'Customer collected 2026-09-24', but the case file says she was only notified and that it had not been co |
| 422 | WO26100812730 | Her note says the Kyocera E4610 is in the green bin in the shop, but her own text of 2026-10-07 23:09 says 'I have the phone with me can i bring it in and when?' - is this phone in the shop or still with her? |

## 2. THE DECISIONS - 12 rows, each one line

These are the owner's because each turns on money, a live customer, or a physical handover - the three things no record can settle. The recommendation is already worked out, so the answer is a yes, a no, or a different number.


**359** (medium) - WO2604210131
- 359 asked: Is the TSL5 Tesla-module job dead? The order reads CANCELLED with no ledger row explaining it, a private note from 2026-05-20 says it was awaiting parts before the next bench step, the shop was still discussing the manufacturer timeline in June, and on 2026-09-02 the customer asked to collect the components he has with us.
- the sweep recommended: Reopen as AWAITING_PARTS - the only current note is that it is awaiting parts

**371** (medium) - WO2606290003
- 371 asked: WO2606290003 sits in UNFIXABLE, but the last thing we told this customer was that the iPhone 11 is fixable for $105 (charging-port flex, pay only if it works), and our own case file still shows the job in progress with money owed. Is this job actually dead, or should it be reopened?
- the sweep recommended: Reopen as AWAITING_APPROVAL at the quoted $105

**377** (medium) - WO26072412517
- 377 asked: WO26072412517 was closed 2026-08-18 with a note reading 'paid $1000 via cash', but the status row written at the same moment says 'still owes $250' against a quoted total of $1210 - how much was actually collected, and does this customer still owe a balance?
- the sweep recommended: Treat the $1000 recorded at closing as collected and bill the remaining $210 against the $1210 quote, after confirming with the customer.

**392** (medium) - WO2608130003
- 392 asked: Nothing on this order says what the LG Exalt repair cost or that anything was collected, yet the customer has asked 'How much is it' and been sent the Zelle/Stripe link - what should she be charged for this job?
- the sweep recommended: Set her charge at the shop's standard Exalt water-damage price, record it as the order total and collect it.

**417** (medium) - WO26091512714
- 417 asked: Chaya Brodie's laptop lead has not moved since 2026-09-20 - do you want the shop to keep chasing her with the sourced Dell Latitude 5320 at $382.83, or close the lead?
- the sweep recommended: Close the lead as CANCELLED - she was endorsed on an Apple machine the shop does not supply and has not come back.

**418** (medium) - WO26091812719
- 418 asked: Was the $120 plus tax for the Greenwald Acer charging-jack job ever collected on the 2026-10-06 call? The order was cancelled two days later with no reason and no payment is recorded.
- the sweep recommended: Check the 2026-10-06 card charge on the processor first, and if it was taken, record the payment on this order before the file closes.

**419** (medium) - WO26092412721
- 419 asked: What should be done with Nechama Gewirtz's Talk+Text flip phone? The assembly that was ordered arrived on 2026-09-21 but the display and touch do not respond, her note asks only for her contacts, and nothing has been quoted or touched in thirteen days.
- the sweep recommended: Call her once to pin the request down (contacts only), then quote or return the phone as it stands.

**421** (medium) - WO26100812726
- 421 asked: Was the cancellation of WO26100812726 deliberate, given the case file says the charging-port repair was finished on 2026-10-07 and the phone is out for pickup with 65 still uncollected?
- the sweep recommended: Treat the cancellation as an entry error: reinstate the order and collect the 65 when the phone is released.

**424** (medium) - WO2610080001,WO2610080002
- 424 asked: WO2610080001 and WO2610080002 are the same $15 'charge on the spot' FIG F52 battery sale for your own account, entered 44 seconds apart on 2026-10-08, and neither has a payment row - is this one sale entered twice, and was the $15 taken?
- the sweep recommended: Treat WO2610080002 as the duplicate and keep the earlier order WO2610080001.

**425** (medium) - WO2610080003,WO26100812725
- 425 asked: Are customer id 2802 on this order (no name, 848-525-8829) and id 2798 (Nechama Kenchitz, whose open water-damage repair WO26100812725 is on the same number) one customer to be merged?
- the sweep recommended: Merge id 2802 into id 2798 (Kenchitz) and confirm the 25 was collected, because payment row 3280 is only PENDING.

**427** (high) - (class-level)
- 427 asked: About thirty orders were closed with a note saying '$X paid by card/cash/zelle' but have no payment row at all, so the order says it was paid and the books show nothing received. Should I record a payment row against each order the close note names, or is the close note itself our record of the money?
- the sweep recommended: Treat the close note as the shop's record and leave the payment rows alone, but have me record the amount as the order total so the order is internally consistent and the discrepancy stops looking like a missing payment — and change the closing flow so a close note cannot say 'paid' without a method and an amount.

**428** (high) - (class-level)
- 428 asked: When a finished order has sat in 'out for pickup' for months, do you want me to start releasing those to a collected state, or is 'out for pickup' simply where an order lives forever once it is done?
- the sweep recommended: Leave the statuses alone — the seven-state design is two days old and correct — and instead have me keep a weekly list of anything in 'out for pickup' longer than 60 days so the shelf and the book get compared deliberately, rather than me guessing at 425 devices.
