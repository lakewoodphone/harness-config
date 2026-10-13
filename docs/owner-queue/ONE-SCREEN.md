# THE ONE SCREEN — the queue the owner is asked from, one at a time

Measured on the authority 2026-10-12 21:24Z. Every id below was verified
`status='pending'` by direct query before it was placed here. Each item is ONE
plain-language sentence with ONE recommendation. Nothing else belongs on this
screen; the estate answers or resolves everything not listed.

Order is "what bites first": money already leaving, then a dated debit, then the
box that carries the company, then money already stopped.

---

**1. #228 — the business is spending your personal money.** You are funding
Lakewood Phone & Tech at about $4,500/month out of your own accounts, 10.6 days
after the deferral you set expired, and the business already owes you ~$52,911.
*Recommendation: answer "zero subsidy by 1 January 2027" — the subsidy has already
halved on its own (from $6,608 to $3,987/month), so this is a deadline, not a
budget.*

**2. #207 — T-Mobile home internet was never cancelled and debits ~$85 on 19
October.** You are paying for a line the shop no longer needs, and the deferral
expires 2026-10-14 — in two days. *Recommendation: cancel it now; if the gateway
is still on site, that is the only thing to return.*

**3. #448 — the authority box cannot hold its own working set.** `company-api`
runs at 4.5 GB RSS / 5.7 GB peak against 7.7 GB of physical with 2.0 of 4.0 GB of
swap in use, `MemoryMax=infinity`, and one kernel OOM in the last 24 h — this is
the machine the whole estate answers from. *Recommendation: resize it to 4 vCPU /
16 GB — the alternative is capping the app and accepting that the company's own
services get killed under load.*

**4. #449 — the Telnyx account balance is −$0.01 and both SIMs are blocked.** The
Waze device is ready to sell except that the data line dies the moment a buyer
uses it. *Recommendation: top up the Telnyx account and unblock the two SIMs
today — it is the only thing standing between the device and a sale.*

**5. #444 — the prepaid AI balance is low.** The autonomous work stops when the
balance reaches the floor, and DeepSeek has no auto-recharge to switch on (its
own API FAQ documents PayPal, card, Alipay and WeChat Pay and nothing automatic).
*Recommendation: top up now at https://platform.deepseek.com/top_up — this is the
one row for that condition after five duplicate rows were dismissed.*

**6. #279 — Amex has warned that future transactions may be declined.** A failing
card on the company's vendor payments is a credit-standing decision, not an
engineering one. *Recommendation: name the card or account to fix and I will move
that vendor's recurring charges onto it.*

**7. #261 — Deep Infra has been dead since 2026-10-02 (card declined, HTTP 402),
and traffic silently fails over to DeepSeek direct at ~5.5× the cost.** *Recommendation:
drop Deep Infra and make the failover explicit and alerting rather than silent.*

**8. #303 — moving the shop's phone line off Dialpad.** The choice is a fast
Dialpad→Twilio unification or a longer migration that keeps the current numbers
and routing. *Recommendation: take the fast unification — the shop is losing
calls and the slow path has no advantage the shop can see.*

**9. #284 — the Android release signing key exists on one laptop only.** If that
laptop dies, every future Android release is dead with it. *Recommendation: put
the second copy on the vault — it is the one place this estate already treats as
canonical.*

---

*Not on this screen and staying pending because they are the estate's to resolve,
not his: the 90 `lpt-work-order-sweep` and 10 `lpt-board-walk-20261008` rows are
per-order payment/status questions answerable from the order database and the
179,608-record comms archive (they are an intake defect — see `README.md`), and
`#283` is a broker-architecture decision the estate already has a one-writer rule
for. These were NOT dismissed; they remain pending until each is verified, because
a dismissed row needs evidence and a single unverified blanket dismissal is the
same class of defect as the rows themselves.*
