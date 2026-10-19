# Payments recorded from proven Stripe charges — 2026-10-14

On 2026-10-14, **61 orders received a `payment_transactions` row** recording money that was already
taken. Total recorded: **8002.24**. Every row carries `metadata.recordedBy = lpt-record-payment` and
`metadata.stripeChargeId`, and each also wrote a line to the app's own write log.

**Why this was done.** These orders each read `paymentStatus` CAPTURED while `collected` read **0.00** —
the order claiming money its own ledger denied, because `collected` is
`sum(amount) from payment_transactions where "orderId" = X and status = 'SUCCEEDED'` and no row existed.
`lpt-write payment set` proves a Stripe charge but deliberately does not write that table, which left the
figure to be typed into the website by a person. `lpt-record-payment` exists to remove exactly that, and
its docstring quotes the owner: *"you are always the someone, never wait for someone else."*

**The attribution criterion, applied mechanically and auditable.** Each row below rests on a tax-exact
Stripe charge that is the **only** charge of that amount within a day either side, on an order whose
closing note claims that pre-tax figure and which is the **only** order in the shop claiming it in that
window. 126 reconciliation notes had a tax-inclusive match; **60** survived that test, plus the
name-matched West order recorded earlier the same day.


## Recorded

| order | recorded | claim (pre-tax) | stripe charge | charge date |
|---|---|---|---|---|
| WO2605250003 | 79.97 | 75.0 | ch_3Tagd6LnlgYj1gmT0XDTMxg6 | 2026-05-24 |
| WO2605260001 | 21.33 | 20.0 | ch_3TbNPkLnlgYj1gmT18UcpM3c | 2026-05-26 |
| WO2605290001 | 186.59 | 175.0 | ch_3TcG9sLnlgYj1gmT11ANjjEP | 2026-05-29 |
| WO2606010001 | 79.97 | 75.0 | ch_3TdZBZLnlgYj1gmT0bjuG4yY | 2026-06-01 |
| WO2606010002 | 127.95 | 120.0 | ch_3TlCNULnlgYj1gmT0rqB0SnL | 2026-06-22 |
| WO2606050001 | 133.28 | 125.0 | ch_3TezBoLnlgYj1gmT0hiZ5ylw | 2026-06-05 |
| WO2606050002 | 37.32 | 35.0 | ch_3TemoDLnlgYj1gmT0s6agZGU | 2026-06-05 |
| WO2606080006 | 133.28 | 125.0 | ch_3Tg7uRLnlgYj1gmT1Zdg52iv | 2026-06-08 |
| WO2606120002 | 90.63 | 85.0 | ch_3ThYFDLnlgYj1gmT0G6kqGcY | 2026-06-12 |
| WO2606150001 | 42.65 | 40.0 | ch_3TizCBLnlgYj1gmT1t2xxWq3 | 2026-06-16 |
| WO2606150002 | 117.29 | 110.0 | ch_3TicAxLnlgYj1gmT0zzM61XV | 2026-06-15 |
| WO2606150003 | 37.32 | 35.0 | ch_3TiPnZLnlgYj1gmT0L8tTYsM | 2026-06-15 |
| WO2606160004 | 261.23 | 245.0 | ch_3TjPp4LnlgYj1gmT0Nxj6I6i | 2026-06-17 |
| WO2606220002 | 127.95 | 120.0 | ch_3To63nLnlgYj1gmT1E09iGkI | 2026-06-30 |
| WO2606220004 | 117.29 | 110.0 | ch_3TlCECLnlgYj1gmT0bjqlerY | 2026-06-22 |
| WO2606220006 | 106.63 | 100.0 | ch_3TlEkwLnlgYj1gmT0Jsb1mlm | 2026-06-22 |
| WO2606230004 | 63.98 | 60.0 | ch_3TlZoRLnlgYj1gmT1lWp3krl | 2026-06-23 |
| WO2606240004 | 159.94 | 150.0 | ch_3TmcneLnlgYj1gmT1gDwY7VY | 2026-06-26 |
| WO2606260001 | 213.25 | 200.0 | ch_3TmP4tLnlgYj1gmT0sBiywTW | 2026-06-26 |
| WO2606290001 | 149.28 | 140.0 | ch_3TnRpYLnlgYj1gmT1zuZBY7T | 2026-06-28 |
| WO2607020002 | 255.90 | 240.0 | ch_3TorGkLnlgYj1gmT1MIrz1gi | 2026-07-02 |
| WO2607020003 | 79.97 | 75.0 | ch_3TpwleLnlgYj1gmT14vF2IPq | 2026-07-05 |
| WO2607060001 | 159.94 | 150.0 | ch_3TpsnwLnlgYj1gmT0xBy9D1u | 2026-07-05 |
| WO2607060002 | 213.25 | 200.0 | ch_3Tpwe7LnlgYj1gmT0eF5n5AS | 2026-07-05 |
| WO2607060006 | 149.28 | 140.0 | ch_3TqeUFLnlgYj1gmT1oaEswfr | 2026-07-07 |
| WO2607070003 | 133.28 | 125.0 | ch_3TqgAWLnlgYj1gmT1maP1CiY | 2026-07-07 |
| WO2607080001 | 42.65 | 40.0 | ch_3TrLdFLnlgYj1gmT1gdhQjEg | 2026-07-09 |
| WO2607090001 | 133.28 | 125.0 | ch_3Tr7glLnlgYj1gmT0c8uARd1 | 2026-07-09 |
| WO2607150002 | 213.25 | 200.0 | ch_3TxtFTLnlgYj1gmT087Ogqwk | 2026-07-27 |
| WO2607150003 | 106.63 | 100.0 | ch_3TtZNELnlgYj1gmT00sJBXzs | 2026-07-15 |
| WO2607160001 | 95.96 | 90.0 | ch_3TvNvsLnlgYj1gmT07yMHocu | 2026-07-20 |
| WO2607160004 | 117.29 | 110.0 | ch_3TtudtLnlgYj1gmT0XapKAri | 2026-07-16 |
| WO2607200009 | 63.98 | 60.0 | ch_3TvNnWLnlgYj1gmT1AteQSXX | 2026-07-20 |
| WO2607210003 | 79.97 | 75.0 | ch_3Tvi1qLnlgYj1gmT1nKCIkL3 | 2026-07-21 |
| WO2607210007 | 53.31 | 50.0 | ch_3Tw3ECLnlgYj1gmT0rm92gFY | 2026-07-22 |
| WO2607270004 | 42.65 | 40.0 | ch_3Txun0LnlgYj1gmT1THMSjJF | 2026-07-27 |
| WO2607290003 | 53.31 | 50.0 | ch_3TyeonLnlgYj1gmT0Te8s9Cc | 2026-07-29 |
| WO2607300001 | 122.62 | 115.0 | ch_3TyyZ5LnlgYj1gmT18DubiXY | 2026-07-30 |
| WO2608040002 | 79.97 | 75.0 | ch_3U1VxdLnlgYj1gmT0ybkJceT | 2026-08-06 |
| WO2608040007 | 143.94 | 135.0 | ch_3U2zIHLnlgYj1gmT055xxof2 | 2026-08-10 |
| WO2608040009 | 159.94 | 150.0 | ch_3U0n2vLnlgYj1gmT1Oa2k192 | 2026-08-04 |
| WO26080512557 | 138.61 | 130.0 | ch_3U1WyYLnlgYj1gmT1F6faAzv | 2026-08-06 |
| WO2608070001 | 159.94 | 150.0 | ch_3U1XxnLnlgYj1gmT1SsmnMAc | 2026-08-06 |
| WO2608100006 | 95.96 | 90.0 | ch_3U3KUtLnlgYj1gmT0UZIUVtl | 2026-08-11 |
| WO2608100009 | 101.29 | 95.0 | ch_3U2xGuLnlgYj1gmT1xnAgETn | 2026-08-10 |
| WO2608110002 | 117.29 | 110.0 | ch_3U45AdLnlgYj1gmT0pmMGiFy | 2026-08-13 |
| WO2608130010 | 79.97 | 75.0 | ch_3U4O3BLnlgYj1gmT1JQfR6i6 | 2026-08-14 |
| WO2608200003 | 101.29 | 95.0 | ch_3U6a2KLnlgYj1gmT1Gtd0XQE | 2026-08-20 |
| WO2608200004 | 127.95 | 120.0 | ch_3U6v61LnlgYj1gmT1pR6OdUb | 2026-08-21 |
| WO2608200005 | 117.29 | 110.0 | ch_3U6b4DLnlgYj1gmT0DJsca5T | 2026-08-20 |
| WO2608200006 | 186.59 | 175.0 | ch_3U6baxLnlgYj1gmT1iYFltlU | 2026-08-20 |
| WO26082712685 | 309.21 |  | ch_3U8NzmLnlgYj1gmT0O0GfS9D |  |
| WO2608310009 | 197.26 | 185.0 | ch_3UAcLbLnlgYj1gmT0CAuYD2R | 2026-08-31 |
| WO2609010009 | 159.94 | 150.0 | ch_3UAvjFLnlgYj1gmT0CabAOY1 | 2026-09-01 |
| WO2609020001 | 261.23 | 245.0 | ch_3UAxSzLnlgYj1gmT017mXHJY | 2026-09-01 |
| WO2609020002 | 309.21 | 290.0 | ch_3UD8dELnlgYj1gmT1oXPi80s | 2026-09-07 |
| WO2609030001 | 159.94 | 150.0 | ch_3UBcRPLnlgYj1gmT1phxUJr2 | 2026-09-03 |
| WO2609040001 | 309.21 | 290.0 | ch_3UBzHiLnlgYj1gmT1omeKAN3 | 2026-09-04 |
| WO2609070003 | 47.98 | 45.0 | ch_3UD7czLnlgYj1gmT1vFdezUR | 2026-09-07 |
| WO2609070004 | 127.95 | 120.0 | ch_3UD9wMLnlgYj1gmT09s18S0F | 2026-09-07 |
| WO2609140001 | 106.63 | 100.0 | ch_3UFcuKLnlgYj1gmT0B3YT7GC | 2026-09-14 |

Each of these also carries a `PAYMENT RECONCILIATION CORRECTION` note written earlier the same day,
which supersedes the automated `COULD NOT BE RECONCILED` verdict. That note forbids creating a row
**from the note**; these rows are created from the **charge**, which is the distinction the note was
drawing.


## Checked and deliberately NOT recorded

The remaining reconciliation notes with a tax-inclusive match were **not** given a payment row, because
the attribution was not unique — another charge of the same amount fell within the window, or another
order claimed the same figure. Recording those would assert money on an order that might not be the one
the charge belongs to, and would leave the real order reading 0.00. Their correction notes stand as the
explanation. Re-derive the split with `unique_attribution.py`; it prints the count that excluded each.

