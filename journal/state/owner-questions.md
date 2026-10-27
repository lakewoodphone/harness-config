# OWNER QUESTIONS — open only

Updated: 2026-10-26

**Generated** from `owner_decision_queue` on the authority by `tools/journal.py questions`.
That table is the single source of truth for what is waiting on the owner; this is a mirror,
so a session with no route to the authority still reads the truth instead of re-asking.
Do not add a question here: add it there.
Two sections: the phone queue, and CUSTOMER OPERATIONS (computer review only — never texted).
Provenance: 738 row(s) read, 17 pending (14 phone, 3 customer-ops), generated 2026-10-26 21:19 UTC on ZABZ-TECH.

| # | Asked | Sev | Question | My recommendation |
|---|---|---|---|---|
| 511 | 2026-10-14 | high | The camera product's entire difference from what already exists is that it uploads the customer's photos to a cloud store we control - and every seller in this market advertises the ABSENCE of connectivity as the kosher feature (one of them calls local-only storage "actually a feature for many users"). Before we spend anything on it: is a camera that uploads to the cloud acceptable, or should it b | Ask one rav you trust before I spend a dollar on this - one conversation, and it decides whether the product has a differentiator at all. If the answer is no cloud, the honest alternative is a device that still beats wha |
| 850 | 2026-10-20 | high | Rotate the live SerpAPI key? It was printed into a session transcript tonight and must be treated as exposed. | Rotate BOTH keys in their dashboards. Then tell me and I will swap them into /opt/company/.env and the DSH credential stores, reload the API, and verify with a live call each (a search for SerpAPI is optional if we keep  |
| 110 | 2026-09-18 | medium | The 2022 Elantra needs about $400 of work and setup right now: the IVT transmission fluid is overdue, plus the Bluelink/OBD odometer setup is half done. | A. The IVT is the single most expensive failure mode this car has (adjacent-year Elantras have failed in the 80k range at ~$4,800 out of pocket), it is past its severe-duty 60,000-mile interval, and there is no service h |
| 169 | 2026-09-25 | medium | The Fall 2026 Felician balance is 5,758 after aid. Who owns paying it. | Owner pays, system holds it. A payment from here would be family money going out, and the portal is not reachable. On request the balance gets verified without sending anything. |
| 299 | 2026-10-06 | medium | How long should we keep customer device photos, and who may see them after the repair is done? | 12 months from intake with open and disputed jobs exempt. It covers a warranty claim and a chargeback window, which is what the photos are actually for, and it stops the shop accumulating other people's device photograph |
| 725 | 2026-10-19 | medium | Money due in the next three weeks: what is left to pay, and when? | No decision needed tonight. Pay all four in full on the usual bill run; the earliest non-auto-pay deadline is Amex on Nov 4, and nothing here is on auto-pay except US Mobile. |
| 806 | 2026-10-19 | medium | Anti-reset: whose Google account should be the anchor that can set up a sealed phone after a factory reset - the parent, the shop, or a shop Google Workspace account? | The parent's own Google account, never the shop's. Keep 1 shop Workspace account for stock and loaner devices only: one shop credential over customer handsets is a fleet-wide brick risk and blocks resale. |
| 862 | 2026-10-20 | medium | May a shift use one sacrificial Android 15+ handset for the five anti-reset device tests, and which handset? | Use a shop-owned, already-unsellable Android 15+ handset and connect it with USB debugging to zabz-yoga-ts; do not risk a customer device. |
| 883 | 2026-10-20 | medium | The leaked GitHub token is still live and is still the only credential that can read lakewoodphone/lpt-hub. Only your account can issue a replacement or revoke it. Do you want to issue a fine-grained token for lpt-hub so I can swap it in and kill the old one? | Yes. Issue it for lakewoodphone/lpt-hub with Contents read/write and Metadata read; I will install it, verify the repo, restart company-api in a window, then revoke the old token. I have already removed the old token fro |
| 924 | 2026-10-21 | medium | Run one small card payment on a shop counter device so I can prove the new web filter does not break Stripe? | Run it on the counter iPad (DRN 2003) - it applied the profile most recently (2026-10-20T16:24Z), so it is the device that still has to prove a Stripe charge goes through with the filter on. Any small real sale is enough |
| 962 | 2026-10-24 | medium | Techloq billed the 36.99 renewal to Chase 3929 on 10/22 even though your written cancellation went in on 10/21 at 01:35Z and the vendor acknowledged it a minute later. Do you want to file the Chase dispute (the pack is ready at /root/work/917-dispute-pack-20261024.md) or should I chase a Techloq refund instead? | File the Chase dispute: the cancellation predates the renewal and the vendor ack proves it, so the charge is outside Techloq own terms; Chase is one filing and covers you if the vendor stalls. |
| 1043 | 2026-10-26 | medium | The owner-walk now replays 16 steps and fails on regressions, but the one thing it cannot do is a signed-in production staff load - do you want it to have a staff login for that? | Give the walk a dedicated read-only staff test login (its own account, not yours), so the daily instrument measures the real prod desk instead of a mocked API; until then I would treat the live test deploy as the coverag |
| 1047 | 2026-10-26 | medium | Promote PR #686 (test head 099d27238d) to production now? The 285 and 8 dollar figures stay exactly as they are at the counter - the change only stops the public /kosher-waze page printing them. | Promote now. The figures do not change; the only effect is that the public page stops printing them, which is your standing D23/D29 rule, and production is still printing them today. |
| 934 | 2026-10-22 | low | Knox Guard is not bought and its dead code path is deleted. Do you want to buy Knox Guard for Samsung devices, or is the VPN/DNS lane enough? | A. Do not buy it yet. The VPN lane covers every handset, there is no Samsung pilot, and a licence adds a vendor dependency before the first customer ships. Revisit when a dealer asks for the faster lane. |

## CUSTOMER OPERATIONS — computer review only, never texted

Owner instruction, 2026-10-25: these are his, but they stay off SMS. Work this
section only when he chooses to sit down with it; `owner-queue.py knock --section
customer-ops` is the walk. Senders exclude this section.

| # | Asked | Sev | Question | My recommendation |
|---|---|---|---|---|
| 1033 | 2026-10-26 | high | May I open a GitHub Support request to remove the merged PR refs 5, 6, 7 and 8 that still serve three customer BitLocker keys? The repository history itself is already purged; these refs are immutable and only GitHub can remove them. | Yes - open the request. The git history you authorised is already clean; these four refs are the last copies of the keys on origin, and leaving them means any org member who fetches refs/pull/* can still read them. |
| 1037 | 2026-10-26 | high | Text him the jack is due today and to bring the laptop by? | Send it Monday morning, after the box is actually in hand — it answers his 18:50Z screenshot and delivers the 'we could let you know' we promised, with no money in it and no claim that the part landed before it has. |
| 1004 | 2026-10-25 | medium | Yaakov Openhiemer (order 728) was over-collected 40.00: the 40.00 cash paid the 40.00 repair and the 40.00 check was a duplicate. The check refund has never been issued and there is no address on file. Do you approve issuing the 40.00 check refund, and should it be handed to him at the counter or mailed after we get an address? | Refund the 40.00 by check at the counter: the check is the duplicate and he is local with a mobile on file, while mailing needs an address we do not have and an outbound text you would have to approve. |

Closed since the queue opened: 721. Answered questions move to `entries/decisions/` with the owner's own words.
