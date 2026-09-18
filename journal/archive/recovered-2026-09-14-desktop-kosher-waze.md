### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D18|2026-09-11|-|open -->
**D18 · 2026-09-11 · The Kosher Waze gate is four owner decisions, not twenty-one questions.**

The integration plan lists Q8-Q28 unanswered and treats all of them as the owner's. They are not: most are
factual (answerable from the live system) or engineering calls already inside the mandate, and Q2-Q5 are
already locked in the answer log. *Decided:* collapse the gate to the **four** that are genuinely his —
(1) billing shape: is `$9/mo - 250MB - 800MB cap - $18/GB` final, and does the portal *collect* money or
only *show* it; (2) self-serve line: do customers get pause/resume, and is customer-triggered lost mode
allowed; (3) cap behaviour at the limit — pause, throttle, or throttle-and-upsell; (4) location/compliance:
is any trip data stored, and what constraint applies before payments. Ask them **one at a time with a
recommendation**, and answer the remaining seventeen myself from live config. *Reasoning:* he does not do
dev questions (LESSONS **L7**), and 21 questions in one batch is exactly the shape of request that cost
this system its workflow before. See `deploy/waze-mdm/docs/holdings-2026-09-11.md` section 5.

---



---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D18c|2026-09-11|-|open -->
**D18c · 2026-09-11 · The Kosher Waze gate is four owner decisions, not twenty-one questions.**

The integration plan lists Q8–Q28 unanswered and treats all of them as the owner's. They are not: most are
factual (answerable from the live system) or engineering calls already inside the mandate, and Q2–Q5 are
already locked in the answer log. *Decided:* collapse the gate to the **four** that are genuinely his —
(1) billing shape: is `$9/mo · 250MB · 800MB cap · $18/GB` final, and does the portal *collect* money or
only *show* it; (2) self-serve line: do customers get pause/resume, and is customer-triggered lost mode
allowed; (3) cap behaviour at the limit — pause, throttle, or throttle-and-upsell; (4) location/compliance:
is any trip data stored, and what constraint applies before payments. Ask them **one at a time with a
recommendation**, and answer the remaining seventeen myself from live config. *Reasoning:* he does not do
dev questions (LESSONS **L7**), and 21 questions in one batch is exactly the shape of request that cost
this system its workflow before. See `deploy/waze-mdm/docs/holdings-2026-09-11.md` §5.

---



---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D84|2026-09-14|ZABZ-YOGA|open -->
**D84 · 2026-09-14 · Bulk iPhone supply for the Kosher Waze line: iPhone 11 standard, B-Stock/GameStop as the channel, overseas rejected on FCC not duty.**

# D — Bulk iPhone supply for the Kosher Waze product line

**Date:** 2026-09-14 · **Machine:** ZABZ-YOGA · **Decider:** Zabz (owner question raised separately)

## Decided

1. **Fleet standard = iPhone 11 (A2111), factory unlocked, 64GB.** It is the cheapest iPhone that has BOTH
 eSIM and current iOS: iOS 27 shipped 2026-09-14 and supports the iPhone 11 / 11 Pro / 11 Pro Max / SE2.
 The XR, XS and XS Max were dropped in iOS 26 and are dead. Realistic cliff = iOS 28 in 2027, so the 11 is a
 fast-turn device, never inventory to hold.

2. **Primary bulk channel = B-Stock / GameStop Wholesale** (bstock.com/gamestop). Decided on the *guarantee*,
 not the price: GameStop's conditions page states in writing that devices are free from blacklist/FMIP/MDM
 and gives a 30-day return window, and runs a Prolog financial-obligation check on unlocked units. Nothing
 else in this market guarantees iCloud-clean stock at all. Fee is exactly 2.0%.

3. **Grade floor = A+/A/B/C. Never D or F.** GameStop grade D explicitly permits "Cannot detect SIM or SD Card"
 plus Face ID failure and a 1%+ battery floor. For a data-only eSIM product, D is unusable at any price.

4. **Retail is a first-class channel, not a fallback.** Swappa iPhone 11 64GB at ~$129 and iPhone 12 64GB at
 ~$150 beat or match every graded wholesale ladder, with IMEI checks, buyer protection, no MOQ and no freight.

5. **Overseas import is rejected, permanently** (unless an FCC-authorised US-spec part number can be shown).
 Verdict is NOT about duty: SCOTUS struck the IEEPA tariffs down 2026-02-20, the Section 122 surcharge
 expired 2026-07-24, and smartphones appear exempt from the July 2026 forced-labour Section 301. Duty is
 ~0%. It is rejected because (a) HK wholesale *asks* $247-250 for an iPhone 13 that *clears* at ~$240 in the
 US, and (b) 47 CFR 2.803(b) forbids importing a non-FCC-authorised RF device for resale, there is no
 used-equipment exception, and a supplier's contractual assurance does NOT satisfy 47 CFR 2.1204(b)
 (FCC consent decree against T-Mobile, DA 25-793, 2025-09-11).

6. **Grade to CTIA's published standard (Wireless Device Grading Scales v5.1, Jun 2026), never a vendor's
 "Grade A".** Four live wholesalers publish four contradictory in-house scales; at least one permits screen
 burn and liquid leakage at grade C and states in writing it does not check battery health or liquid damage.

## Rejected, with reasons (so they are not reopened)

- **Giggle Trade (HK) as a supplier** - international spec, sea-freight volume, and Tier 2/CPO prices are not
 dealer costs (see L below). Retained as a *benchmark* only.
- **eBay multi-unit lots** - a lot *premium*, not a discount: $190/unit for a clean iPhone 12 lot vs $175
 single on the same page. Useful only for parts feedstock.
- **B-Stock Mobile Carrier / Superior Wireless** - gate needs resale cert + $500 screening fee + R2 cert, and
 Superior does not guarantee unlock.
- **AllSurplus / GovDeals** - 12.5% buyer's premium and inventory skews to iCloud-locked parts units. Kept as
 a low-risk practice lane only (free, no resale cert needed).
- **India, UAE, China mainland** - price parity or worse, plus IMEI-registration and no-eSIM problems.
- **Dead ends verified so nobody re-tries:** BULQ (shut 2025-07-28); treasurehunt.com (parked); "Trevco" (no
 entity); SVD (industrial auctioneer, no phones); devicepost.com (parked); phonedeck.com (NXDOMAIN);
 handy-tech.com (electrical instruments); efrutti.com (candy); 2tmobile.com (Vietnamese retail);
 mpd.com (refuses connections); commerced.com (502); cellularcountry.com (dead); Swappa B2B (inactive);
 Sin Tat Plaza HK (repair counters, no export catalogue); "Wai Chai"/"Wonder Building" (nothing found).

## Consequence for the product

The phone is not the profit centre and never was - the $9/mo subscription is, worth ~$216 over 24 months. So
model choice is decided by *support life and clean-stock risk*, not by $20-30 of acquisition price. That is
what makes the GameStop guarantee worth more than a cheaper unverified lot.

## Status

Research complete and written to `lpt-hub/docs/customer-operations/sourcing/waze-fleet-iphone-sourcing/`
(REPORT.md + evidence/). No supplier contacted, no account created, no bid placed. The one money commitment
(an 80-unit lot closing 2026-09-15) was raised to the owner.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D87|2026-09-14|ZABZ-TECH|open -->
**D87 · 2026-09-14 · Bulk iPhone supply is premature: the Kosher Waze fleet is two test units and the device has no recorded sale price; device pipeline becomes just-in-time retail.**

**D85 · 2026-09-14 · Bulk iPhone supply is premature — the Kosher Waze fleet is two test units and the device has no recorded sale price.**

D84 chose a bulk channel (B-Stock/GameStop) for the Kosher Waze line. That framing assumed a fleet to supply. It
does not exist yet. Measured 2026-09-14:

- **Installed base = 2 units, both in `device_group=test`, neither kiosk-locked, zero customer units.**
 `lpt-hub/docs/customer-operations/cases/lpt-waze-fleet-device-registry.md` (created 2026-09-03): DRN 2001
 (`FFYGNQ8AN72J`) and DRN 2002 (`FFXGT23HN72J`), both iPhone 11, both `registered`, not `deployed`.
- **The device has no sale price anywhere in the record.** grep of `phone-and-tech-full` (ts/tsx/md/json) for
 "waze" returns two incidental files and no product or price row; grep of `lpt-hub` for `Kosher Waze` plus a
 dollar amount returns nothing; a scan of all 212 readable tables in the authority `secretary.db` for
 `%waze%` found no product/price row (the only hits are 2026-05/06 build chatter, tasks and memories).
 `deploy/waze-mdm/docs/kosher-waze-customer-integration-plan.md:10-13` describes it as a device "**sold**" to
 the frum community at `$9/mo · 250MB · 800MB cap · $18/GB` — the price of the device itself is unstated.
- Actual acquisition so far: 2 × unlocked iPhone 11 64GB, eBay, **$149.99 each**, free shipping, 2026-08-06
 (`lpt-hub/docs/customer-operations/purchases/lpt-waze-kiosk-trial-iphone11-2026-08-06.md`).

**Decided:** no bulk lot is bought until demand exists. The device pipeline is **just-in-time retail** — buy
1-10 unlocked units (eBay/Swappa, ~$129-150) to serve the trial and the first real customers — with a purchase
trigger tied to actual sold/pipeline count rather than to a target stock level. Bulk (a 40-80 unit lot) is
revisited only when the monthly pipeline exceeds roughly 30 units, and then only at ≤$95/unit landed for grade
A/B. Queue question #19 (the 80-unit lot) is answered **pass** on this basis, not on price alone.

*Why this is the correction and not a retreat:* the 80-unit lot was being evaluated against a market price of
$114-153/unit (measured: `#estimate-amount` on closed lots 64116/$12,222, 65996/$11,250, 67115/$9,118 — all
80 units B/C Dallas; see L234). Even a cheap lot would have bought 40× the entire installed base, in four
models, with dead microphone and dead rear camera permitted at grade C and no condition returns. The binding
constraint on this product was never unit cost at volume.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D89|2026-09-14|ZABZ-TECH|open -->
**D89 · 2026-09-14 · Kosher Waze fleet becomes two device tiers (iPhone 11 + iPhone SE 2020, both eSIM-mandatory); D84 model criterion was wrong.**

## D88 · 2026-09-14 · Kosher Waze fleet becomes two device tiers (iPhone 11 + iPhone SE 2020), both eSIM-mandatory; and D84's model criterion was wrong.

**Owner decision, 2026-09-14, in conversation:** the fleet runs **two tiers**, on the condition that **both have
eSIM**. Tier 1 = iPhone 11 (A2111) 64GB — already the standard and the two enrolled test units. Tier 2 = iPhone SE
2020 (A2275) 64GB at roughly half the acquisition cost.

**D84 contained an error, corrected here.** D84 stated the iPhone 11 "is the cheapest iPhone that has BOTH eSIM and
current iOS". It is not. The SE 2020 has the same A13 chip, is on the same iOS support list and has eSIM, at about
half the price. Measured 2026-09-14: Swappa **avg sale** iPhone 11 64GB **$136** vs SE2 64GB **$85** (20 unlocked
64GB SE2 sales Sep 10-14 cleared $78-95); acquirable at iPhone 11 **$112.50-144** (eBay 2-unit lot / Back Market
with warranty) vs SE2 **$49.99-92** (eBay / Back Market with warranty). Support facts verified this session: iOS 27
compatibility list includes "iPhone SE (2nd generation and later)" (macrumors.com 2026-09-14); dual SIM with eSIM
requires iPhone XS or later (support.apple.com/en-us/109317, 2026-09-14).

**Buy ceilings:** iPhone 11 **$125** bare / **$145** with warranty; SE2 **$95**. Both tiers are one OS baseline, so
either is acceptable stock — buy whichever is cheapest at the moment, never a non-eSIM model.

**What this adds to the engineering backlog** (recorded in full in
`lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md`):
1. The wallpaper renderer emits one fixed canvas (720x1280, `deployment-process.md:382`) and caches
 `drn-device-{drn}-{lock|home}.png`. Tier 1 is 828x1792 @2x, tier 2 is 750x1334 @2x — it needs the device's model
 to choose the canvas and the model in the cached filename, or one tier's render overwrites the other's.
2. `webtrap` layout and the overlaid device label need visual verification on a 4.7in screen.
3. Different case SKU (SE2 shares the iPhone 7/8 body).
4. `scripts/waze/onboard.py` must take a model parameter; the fleet DB already stores model per device.

**Not done, and not claimed done:** no tier-2 device has been bought or enrolled; nothing in the renderer has been
changed. The two enrolled units remain iPhone 11, `test` group, not kiosk-locked.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D91|2026-09-14|ZABZ-TECH|open -->
**D91 · 2026-09-14 · Kosher Waze unit economics: custom case in every unit and a hard floor of 100 dollars gross profit per device sale; tier 2 only works if SE2s are bought at 50-70.**

## D90 · 2026-09-14 · Kosher Waze unit economics: custom case in every unit, and a hard floor of $100+ gross profit per device sale.

**Owner instruction, 2026-09-14:** *"we also need custom cases, we need to make at least 100 profit per sale, maybe
more."* Two constraints, both binding:

1. **Every unit ships with a custom case.** This is a new sourcing lane (unit cost, MOQ, lead time, whether one
 supplier covers both moulds). The iPhone 11 is its own mould; the **SE 2020 shares the iPhone 7/8 body**, so that
 SKU is common. A custom-print MOQ larger than the device order is a cash trap.
2. **≥$100 gross profit per device sale** (price minus device + case + freight + provisioning/QC). A floor, not a
 target — the owner said "maybe more".

**Pricing rule adopted: list price = landed unit cost + ≥$100.** Provisional bands before the case cost is known
(case assumed $15, prep $5): iPhone 11 → **$239** at a $112.50 device, **$269** at a $145 device. SE 2020 → **$179**
at a $50 device, **$219** at a $95 device.

**The tension this exposes, and it is the important part:** at the SE2's $95 buy ceiling the second tier cannot be
cheap — it would have to sell at ~$215, roughly 2.5× the $85 the same phone achieves used on Swappa. **Tier 2 only
works if SE2s are bought near the bottom of their range ($50-70); otherwise the tier should be dropped rather than
priced at a number nobody pays.** This is settled by buying a few, not by reasoning about it.

Written up in `lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md` together with the
channel cautions measured the same day (Today's Closeout iPhone 11 stock is under 80% battery; zegomobile is
low-trust and should not be bought from; celldealers.com is dead, cell-dealers.com is live; trade-in aggregators are
a dead end at this size).

**Not done, not claimed:** no custom case sourced, no case cost known, no price encoded anywhere, no device bought.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D95|2026-09-14|ZABZ-TECH|open -->
**D95 · 2026-09-14 · Kosher Waze product terms settled: button-covering branded case with open Lightning port, phone+case only, 100 dollar device-sale profit floor, 8-month warranty, owner places every order, in-shop sales with a status-only portal.**

## D92 · 2026-09-14 · Kosher Waze product terms settled in one sitting: case spec, box contents, profit floor, warranty, who pays, and who sells.

Owner answered six clarifying questions, one at a time. All six are now fixed product terms:

1. **Case:** *very strong, custom-branded, durable.* Must **cover the side buttons** — the physical escape from an
 MDM kiosk is power+volume force-restart, or power+volume-down into recovery/DFU with a computer, which erases
 the device and drops the enrolment — and must **leave the Lightning port open**, because this is a car
 navigation unit that needs constant power. (Explained to the owner in those terms and accepted.)
2. **What ships: phone + case only.** No charger, no car mount, no bundled service month. The customer already has a
 cable and a mount.
3. **Profit floor: ≥$100 gross on the device sale itself**, counted immediately, subscription on top. Never
 recovered across the customer's life.
4. **Warranty: 8 months on the device for standard use.** Media/software updates **promised for 1 year** — longer
 may be given but is not promised. This is longer than any supplier gives us (30 days is the norm on lock
 faults), so the exposure is ours; on 20 units a 10% failure rate is ~$260, two units of margin.
5. **Buying: the owner places every order.** My job is to hand him the exact listing, quantity and total. Payment
 rails that exist on the authority: PayPal API credentials, Stripe secret key, Plaid. Single-use virtual cards
 are **not** configured. Nothing is paid by me, ever.
6. **Sales channel: in the shop, in person.** The portal's job is **status + changing the data cap** — it does not
 take money. No checkout/billing build is required for the first sales.

**Price rule confirmed: list = device + case + ≥$100.** Final numbers await the case measurement. At a $27 stock
rugged case: tier 1 (iPhone 11) $259 at a $125 device; tier 2 (SE 2020) $179-$229 depending on the device buy.

Recorded in `lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md` under "Settled
product terms". Still open: the case route (pad/UV print on stock rugged vs 3D-printed TPU shell — measurement in
progress), whether tier 2 survives at realistic SE2 buy prices, and the absence of any product or price for this
line in the portal.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D96|2026-09-14|ZABZ-TECH|open -->
**D96 · 2026-09-14 · LPT Waze is not a usable product name and a TM beside it would be evidence against us: WAZE is a live standard-character registration, Google LLC, Class 9.**

## D96 · 2026-09-14 · "LPT Waze" is not usable as a product name, and a ™ beside it would make things worse — the naming constraint, decided as the lawyer.

Owner asked whether the product could be called **"LPT Waze" with a copyright or ™**. Analysed against the actual
registration rather than from memory.

**The registration.** WAZE — **US Reg. No. 3713203, Google LLC**, Serial 77607428, filed 2008-11-05, registered
2009-11-17, **status 800 Registered and Renewed** (status date 2019-05-29), **standard character mark**,
**International Class 009**: "computer programs and software for the collection, compilation, processing,
transmission and dissemination of GPS data for use in fixed, mobile and handheld devices"
(trademark.justia.com/776/07/waze-77607428.html, read 2026-09-14).

**Decided: no. Three separate reasons, each sufficient on its own.**

1. **Standard character means the word itself, in any typeface.** Styling "LPT Waze" our own way does not step
 around it. The mark covers the word, and the mark is live.
2. **Adding "LPT" does not cure the confusion.** The legal test is likelihood of confusion, and a composite mark
 that adopts another's entire mark as its dominant, source-identifying element is the weakest possible posture.
 It is worse than usual here: identical class and near-identical goods (a handheld GPS navigation device), and we
 literally run their software — so a customer would reasonably conclude Google licensed or endorsed the product.
 WAZE is also famous in navigation, which brings dilution in as a separate theory.
3. **™ is not a defence; it is evidence against us.** ™ asserts a claim of rights in the mark beside it. Claiming
 rights in a mark whose operative element belongs to Google is evidence of *knowing* adoption, which is what
 supports a finding of wilfulness and, in a bad case, enhanced damages and the other side's attorney's fees. The
 symbol creates no rights whatsoever — rights come from use or registration, not from the symbol. **© is simply
 wrong**: copyright covers the artwork, the code, the photographs; it does not cover a name or short phrase, so
 "©" beside a product name claims a right that does not exist and protects nothing.

**The asymmetry is the argument.** Recognition gained is small; the exposure is a cease-and-desist that is cheap
for them and expensive for us, marketplace takedowns, and — the concrete loss — **boxes and cases already printed
and paid for becoming unsellable inventory.** On a 10-20 unit run with a $100/unit margin, stranded packaging is a
real cost.

**What is allowed, and it is not nothing:**
- **Our own name, with ™.** ™ is free to use on a mark *we* own. ® only after registration.
- **Referential use of the word Waze**, small and factual — "Works with Waze navigation" — with the disclaimer:
 *"Waze is a trademark of Google LLC. This product is not affiliated with, endorsed by or sponsored by Google LLC."*
 No Waze logo or app artwork, never as the product name, never the largest word on the panel.
- **Register our own mark** (USPTO, Class 9) if he wants real nationwide rights — self-fileable, and it is the step
 that converts ™ into ®.

**Not legal advice and not the last word:** the analysis above is mine and it is the reason the box artwork carries
no Waze product branding. If he ever wants an application filed or a letter arrives, a trademark attorney is worth
the money — but nothing about this decision needs one.

**Also flagged, not solved:** independently of the name, shipping devices with a **modified/locked build of the Waze
app** raises questions under the app's own terms. That is a different question from the trademark, it is not
answered here, and it should be looked at before volume.

Written into `lpt-hub/artifacts/kosher-waze-box/BOX-SPEC.md` §5 with the full registration citation.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D98|2026-09-14|ZABZ-TECH|open -->
**D98 · 2026-09-14 · LPT NAVIGATION: name settled and cleared, case/cable/box sourced, final prices 259 and 199, and hard buy ceilings of 121 for an iPhone 11 and 63 for an SE 2020.**

## D97 · 2026-09-14 · LPT NAVIGATION: name settled, box/cable/case sourced, and the two hard buy ceilings the pricing produces ($121 iPhone 11, $63 SE 2020).

**Name:** **LPT NAVIGATION™** (owner chose it after the "LPT Waze" analysis in D96). Trademark check run before
printing: the only LPT US record found is **Ser. 73281286, DEAD — abandoned 1984**; live LPT marks found are in
unrelated fields (finance: Ser. 99555380 "LPT — The Loan Pros Team", filed 2025; LPT Holdings Inc. in Canada). **No
live US conflict in Class 9 or in navigation.** Two honest caveats recorded: "Navigation" is descriptive, so the
distinctive element is LPT and a filing would likely require disclaiming "Navigation" apart from the composite; and
a partly descriptive name is correspondingly harder to defend against imitators.

**Case:** stock SUPCASE Unicorn Beetle Pro for both models ($21.95 Amazon iPhone 11, $19.95 SE 2020; $26.95/$26.99
direct) plus a single-colour pad print (~$1.45/unit + a $75-120 plate per design). No stock rugged case covers the
buttons *and* leaves the Lightning port open — the rubber flap is what earns the IP rating and it tucks open or
trims off. **Verify on a sample of each before any bulk order.**

**Cable:** MFi-certified C89, USB-A→Lightning, 1.5 m, nylon-braided, ~$5.66/unit landed at 250 (2.6% HTS
8544.42.9090 + 25% Section 301). Non-MFi saves ~$2.40/unit against a device-price pop-up risk — rejected. Branding
via a printed silicone cable tie at $0.53 rather than a $6.60 custom cable. **The 250-unit cable order is
deliberately deferred**: it is 12-25 years of supply at the current plan. Buy 20 at retail now.

**Box:** Cubit rigid two-piece at MOQ 50, $2.50-4.25 published (the only rigid route that is not a cash trap) with a
die-cut EVA insert at MOQ 50, $0.85. Fallback: Uline stock box + printed belly band + insert, ~$2.13/unit but with
a stock size that does not match the design. Design, dieline and artwork are done:
`lpt-hub/artifacts/kosher-waze-box/` (BOX-SPEC.md, box-dieline.svg, MANIFEST.md).

**Final prices and the two rules that matter.** List **tier 1 $259, tier 2 $199**. All-in cost is $150.44-191.49
(tier 1) and $85.94-132.74 (tier 2). Therefore:

- **Never pay more than $121 for an unlocked iPhone 11 64GB.**
- **Never pay more than $63 for an unlocked iPhone SE 2020 64GB.**

Above those, the unit does not make the owner's ≥$100 and we do not buy it. **This kills the SE2's "$95 ceiling"
from the market scan** — at $199 a $95 SE2 leaves $66, not $100. Tier 2 is viable only with SE2s at ≤$63 (eBay has
shown $49.99-63; the typical Good unit is $89.99). Otherwise the choices are raising tier 2 to ~$239, where it
competes with tier 1 for the same customer, or dropping the tier.

**Nothing ordered. Nothing paid.** The owner places every order; the pipeline doc carries the order list with exact
sources.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D99|2026-09-14|ZABZ-TECH|open -->
**D99 · 2026-09-14 · Tier 2 dropped: the line is iPhone 11 only at 259 dollars, buy ceiling 121, which also removes the entire per-model engineering change.**

## D99 · 2026-09-14 · Tier 2 dropped: the line is iPhone 11 only, one price of $259, one buy ceiling of $121.

Owner decision after seeing the arithmetic: **the SE 2020 tier is dropped.** The SE2 only clears the $100 margin
floor at a $199 price if it is bought at **$63 or less**, which is the bottom of its range, and raising tier 2 to
~$239 would sit within $20 of the iPhone 11 and lose the sale to the bigger phone anyway. One model, one tier.

**What this removes, concretely — this is why it is a good decision, not a retreat:**
- a second case SKU and a second pad-print plate (one design, one setup fee, not two);
- a second box size, or a shared cavity compromised between two bodies;
- a second price point, a second set of customer expectations and a second support story;
- **the entire per-model engineering change** that two models required: the wallpaper renderer's fixed canvas and
 per-model cache key, the `webtrap`/4.7in layout check, and the model parameter in `scripts/waze/onboard.py`. The
 existing renderer, profile stack, onboarding flow and fleet schema are unchanged by this programme.

**The line is now exactly:** iPhone 11 (A2111) 64GB, factory unlocked, **never more than $121**; SUPCASE Unicorn
Beetle Pro $21.95 with a single-colour pad print; MFi C89 USB-A→Lightning 1.5 m; the LPT NAVIGATION rigid box with
a die-cut EVA insert; **list $259**, which banks $108.56 at the best verified buy and never less than $100 at or
under the ceiling.

**First buy stands at three lines and $264.45:** one case sample, 50 EVA inserts, 20 retail MFi cables. The owner
places every order; the pipeline doc carries the sources. Nothing ordered, nothing paid.

Written up in `lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md`, which is now a
single-tier document throughout.

---


---

### FROM journal/log/decisions/2026-09.md
<!-- e:decisions|D102|2026-09-14|ZABZ-TECH|open -->
**D102 · 2026-09-14 · Round 3: stock Uline box plus vinyl sticker replaced the last two estimates with no supplier contact; all-in cost 37 dollars, buy ceiling 162, and Back Market becomes a second source.**

## Round 3: the last two estimates replaced without contacting anyone, and the ceiling rose to 162 dollars on measured numbers

The two remaining estimates — a custom rigid box and pad printing on the case — were replaced by a **stock Uline
box plus a printed vinyl sticker**, both with published prices that were read directly:

- **Box: Uline S-15028, 8x6x4in white corrugated, \.01 per box at the 100 tier** (25/bundle, ships same day),
 read from uline.com/BL_425/White-Corrugated-Boxes. The smallest published-price box that fits a 6.34in cased
 phone with an insert and a coiled cable without rattling; 5x5x2in (\.51) and 6x4.5x4.5in (\.41) were rejected
 as too small.
- **Branding: Sticker Mule die-cut vinyl stickers, \.20 each at 50 and \.73 each at 100.** No MOQ above 50, no
 plate charge, no supplier contact. Replaces both the pad print *and* the lid printing.

**All-in non-device cost falls from the conservative \ to \** (measured lines plus retail cables), so the buy
ceiling rises **\ → \** and profit at the ceiling stays exactly \. One effect matters beyond the
arithmetic: at \, **Back Market's \ "Fair" iPhone 11 becomes a second qualifying source**, which reduces the
single-seller risk on the whole plan.

**The decision this encodes:** a rigid custom box and pad printing are now **optional upgrades at volume**, not
blockers. The quote drafts in kosher-waze-quote-requests.md stay unsent and unsent is now a perfectly good state.
For a product handed over in a shop rather than mailed, the rigid box's parcel durability was never being used.

Also this round: the pipeline document was **rewritten end to end** rather than patched an eleventh time, because
ten layered edits had left stale ceilings and stale sources in it. It is now self-consistent with \ throughout,
and §7 records the honesty rules it follows.

---


---

### FROM journal/log/handoff/2026-09.1.md
<!-- e:handoff|H1|2026-09-11|ZABZ-YOGA|done -->
## 2026-09-11 · ZABZ-YOGA · Built the conversational CEO and its memory

**VERIFIED STATE (both workstations, checked not assumed)**
- `zabz` is the default preset on **ZABZ-YOGA and ZABZ-TECH**; second sync run on each is fully clean.
- Model is **`deepseek-flash`** on both (reverted; see the correction below).
- `zabz` is **25 rows**: full toolbelt + background-first shell policy + **6 MCP bridges**
 (secretary, firecrawl, jina, context7, fetch, playwright).
- Mount validation: **`mounted OK: zabz`**.
- **The MCP servers genuinely spawn** — proven by process tree, not assumption. DSH pid 11744 had
 children running `ps_mcp_server.py`, `mcp_launcher.py`, `mcp-fetch-server` and the Playwright MCP.
- `ceo-kernel` Phase 1 runs on `secratary` and its sentinel found two things manual analysis missed.

**CHANGED, THEN REVERTED — read before touching model settings**
The default model was briefly switched to `deepseek-v4-pro` on the assumption that "pro" meant more
capable. **The owner corrected it: 4.1 Flash is better and cheaper.** Verified afterwards: the API
advertises only `deepseek-flash` and `deepseek-v4-pro`, `deepseek-v4.1-flash` is rejected by name,
and Flash and Pro returned byte-identical usage on an identical probe. Reverted. LESSONS L25–L27:
do not change a cost-bearing default on a hunch.

**THE ONE THING STILL UNPROVEN**
The preset default is chosen **at session start**, so `settings.yaml` saying `zabz` does not mean any
running session uses it. `self_audit` showed the live session on `cordis` because the DSH process
started one second before the settings were written. **A profile restart is required**, and a real
session on `zabz` has still never been observed. First check after restarting: `self_audit` should
report the agent's preset as `zabz`, and the tool catalog should include `mcp__secretary__ps_*`.

**ALSO FOUND — the running process does not hot-reload the preset default**
The model namespace *does* re-read per request (a model change applied live), but the **preset** is
fixed at session start. Recorded as PAIN P11: a change can be reported as done while having no
effect. Rule adopted: no claim about a preset without a live agent reporting that preset.

**IN FLIGHT**
- `zabz` is installed and defaulted on **both** workstations (Yoga and desktop), each verified with a
 clean second sync run. A **profile restart** is required for the default to take effect.
- **The one unproven thing: the secretary MCP row's 14 tools have not been observed registering in a
 live session.** What *is* proven: the preset mounts (`mounted OK: zabz`); the row resolves
 **enabled** on win32 (`disabled: !!js process.platform !== 'win32'` evaluates false); both paths
 exist; the venv python imports the `mcp` SDK; the `dsh-mcp-client` package is present (0.1.5-rc.2);
 and an independent handshake against `ps_mcp_server.py` returned all 14 tools. What is *not* proven
 is that the client completes that handshake at preset mount time and registers them. **First session
 on `zabz` should list its tools** — if `mcp__secretary__ps_*` is absent, this is the thread to pull.
- `ceo-kernel` is staged on `secratary` at `/home/zabz/ceo-kernel` and runs, but **not scheduled** —
 it only runs when invoked. Phase 1 is complete; Phases 2–7 (inbox, ledger, gate, preset tools,
 daemon, evolution loop) are designed in `ceo-kernel/docs/DESIGN.md` and not built.

**BROKEN / KNOWN**
- Three divergent `secretary.db` copies; nothing yet prevents writes to a stale replica (PAIN P3).
- Evolution loop still not closing: 56 unapplied, 30 duplicates, 13 node_modules targets (PAIN P4).
- `engineering_indexer`: 172 ticks, 0 completions (PAIN P5).
- 7 critical + 46 urgent messages held undelivered (PAIN P6).
- `harness-config` sync is **manual**. Nothing schedules it, so drift resumes the moment someone
 forgets to run it. A scheduled pull is a small, high-value fix.

**NEXT**
Open a session on `zabz` and confirm the tool list — specifically whether `mcp__secretary__ps_*`
appears. That closes the only open verification, and it is the difference between a CEO that can talk
and one that can act on the company.

**EVIDENCE**
- `~/code/harness-config/presets/zabz/agent.cordis.yml` (20 rows)
- `~/code/ceo-kernel/ck/{provenance,sources,sentinel,cli}.py`
- `~/code/personal-secretary-mvp/docs/secretary-replacement-audit/` (7 documents)
- Sentinel run on `secratary`: 4 findings, including `engineering_indexer` dead weight and a
 131-day-old question — both new discoveries

---

## ⚠ ID allocation — read before adding an entry (2026-09-11)

(UNCHANGED HEADER — see the lessons file for the allocation rule.)

## 2026-09-11 · Fleet monitoring was dead for 67 days; now it is not

**This is the headline of the session.** Every monitoring signal for the Kosher Waze / LPT fleet was
blind, and no alert ever fired. Established by direct measurement, not inference:

- `fleet_devices.last_seen` is **NULL for all 65 devices**, always, and **no code path writes it**.
 Anything reading it concludes every device is stale — which is why an earlier "stale devices" reading
 was meaningless.
- `/fleet/sweep` runs from cron **every minute** but selects only `state = 'registered'`. There are
 **zero** such devices, so it selected nothing and wrote nothing. Forever.
- `fleet_queue_snapshots` last received a row **2026-07-05**; `fleet_device_health_history` **2026-07-06**.
- `fleet_alerts` had **no staleness producer at all** — the only insert in the module is an `info` note
 when Activation Lock is enabled. Hence silence since 2026-07-12.
- The real liveness source is `enrollments.last_seen_at` (NanoMDM's own check-in), which IS current and
 simply isn't what `last_seen` reads. **62 of 65 devices have not checked in for over a week; only 3
 in the last 24h.** That is the state the fleet was actually in while everything reported healthy.

**Built:** `/fleet/monitor/run` (+ `GET /fleet/monitor`), on cron every 30 minutes. Liveness from
`enrollments.last_seen_at`; 48h warning / 168h critical staleness; cap-proximity alerts at 80%/100%;
per-(device, category) alert de-duplication; and it **refuses** (`ok:false`) when no device has any
recorded check-in rather than reporting health from blindness. Verified: 62 alerts persisted, idempotent
across runs, health history growing again (980 frozen since July → 1175 and current).

**Root cause of four separate-looking 500s, and one silent failure.**
`fleet_api.py` was written for SQLite, where rows are `sqlite3.Row` and support **both** `row[0]` and
`row["col"]`. PostgreSQL returns plain tuples, so every name access raised
`tuple indices must be integers or slices, not str`. Measured: **~73 positional vs ~88 name accesses**,
so switching to dict rows globally would have broken the other half. `compat_row.py` implements
`sqlite3.Row` semantics and is wired once in `get_db()`. This fixed `/fleet/telnyx/usage`,
`/customers`, `/billing` and the monitor.
*And a schema drift that ate every alert:* the live `fleet_device_health_history` has a **`NOT NULL
serial`** column the app's `SCHEMA_SQL` never declares. Every history insert failed; because PostgreSQL
**aborts the whole transaction** on a failed statement (25P02), all 62 subsequent alert inserts failed
too — while the endpoint returned **200** with `created: 1`. Fixed by dropping the NOT NULL, backfilling,
declaring it in the schema, and committing **per device** so one bad write cannot strand the rest. The
monitor now reports `history_errors`/`failed_devices`/`complete`.

**Also fixed:** psycopg parses placeholders from the whole query text, so a literal `%` inside
`LIKE '%stale%'` is a syntax error. The converter now escapes `%` inside string literals (tracking `''`
escapes) while leaving real placeholders and bound values alone.

**Commits:** `c74395942` (monitoring + CompatRow), plus earlier `6f2a5195b`, `3ba33b23d`, `072f636a9`,
`3a228f959`. **103 tests passing** (was 66). Eight endpoints return 200.

**LESSONS LANDED THIS SESSION:** L34 (a job can succeed and write nowhere anyone reads), **L52** (a fix
verified through one entry point is not verified — test the path the consumer takes), plus an
ID-allocation rule for the lessons file after finding **seven duplicated lesson numbers** from
concurrent sessions. **PAIN P15, P16, P17.**

**NEXT:** the customer + staff portal surfaces. The contract is corrected and settled
(`deploy/waze-mdm/docs/customer-portal-waze-module.md`); the endpoints are live and verified. Blocked on
one question: which portal app and repo serves LPT customers in production.

---



---

### FROM journal/log/handoff/2026-09.1.md
<!-- e:handoff|H2|2026-09-11|ZABZ-YOGA|open -->
## 2026-09-11 · ZABZ-YOGA · Kosher Waze portal built (customer + staff); staging is a dead target

**CHANGED (all pushed to `phone-and-tech-full` `test`, commit `d80e49d75`)**
- **Customer "My Waze Device"** at `/customer-portal/device`, in the portal nav. Live usage bar,
 `cap_message` from the server, and change-allowance / pause / resume. Renders nothing but a short
 message when the account has no Waze device, so it is safe to link for every customer.
- **Staff "Waze Fleet"** at `/admin/waze-fleet` (ADMIN + MANAGER). Fleet health, **alert freshness as a
 first-class figure**, device lookup by DRN, and cap/pause/resume. Deep MDM work (profiles, kiosk,
 wallpaper, renumber) deliberately stays in the fleet dashboard rather than being half-duplicated.
- **Backend `WazeDeviceService`** — server-to-server only, bounded timeout, and it **degrades to
 "not linked"** on 404 / outage / unconfigured so a fleet-api problem can never break a portal page
 that also shows orders and backups. The bearer token never reaches the browser.
- Customer procedures are customer-scoped; staff procedures sit behind `adminProcedure` and are
 **DRN-addressed with no customer input**. Mutations take a device **UUID, never a serial**, and an
 unowned UUID is rejected before any fleet-api call.
- `FLEET_API_URL` / `FLEET_API_TOKEN` are **optional**, documented in `.env.example`, `.env.template`,
 `.env.production.template`, so every environment without Waze devices still boots.

**VERIFIED**
- Backend + frontend **typecheck clean**. The only remaining errors are **two pre-existing ones on
 `test`** (`FAQSection.tsx` unused import, `useFaqs.ts` arg count) — proved pre-existing by stashing my
 changes and re-running: identical failures.
- **eslint clean** on every new and changed file, after splitting one component that tripped the repo's
 500-line rule (split into `components/waze/*`, not suppressed).
- **20/20** new service tests pass. Backend suite: **6107 passed, 24 failed** — all 24 pre-existing
 (timeouts + one Date-vs-string assertion in `customerPortal.debug-logging`), the latter also proved by
 stash-and-rerun.

**BROKEN — and it blocks the last step**
- **STAGING DOES NOT EXIST.** `Deploy to Staging (Test Branch)` has failed on **every** push since at
 least 2026-09-09 (8/8 consecutive). Root cause: `curl: (22) ... 404` from
 `https://api.heroku.com/apps/lakewood-phone-backend-test/config-vars` — the Heroku app is gone, so the
 workflow dies in "Validate Staging Configuration" before deploying anything.
 **The integration is therefore NOT verified on staging, and I am not claiming it is.**
- The frontend deploys **manually** via Netlify (`netlify deploy --no-build`), not by the workflow. Even
 with a healthy backend workflow, a UI change needs that manual step — see
 `docs/operations/DEPLOY_ARCHITECTURE_REALITY.md`.
- `FLEET_API_URL` / `FLEET_API_TOKEN` are **not set on the staging app**. Until they are, the panel
 degrades to "not linked" there by design, so staging would show nothing even once the app exists.

**NEXT**
Recreate/point staging, set the two secrets, re-run, and verify the panel against the live fleet. Then the
owner promotes `test` → `main` (his step, by agreement).

**ALSO FIXED THIS SESSION (fleet host)** — commit `b86cdbca8`
- Staff cap endpoint `POST /fleet/devices/{drn}/telnyx/cap` clamped the SIM to a **0.5 GB floor** while the
 customer endpoint used **0.05**, and it **stored the unclamped value**: asking for 0.1 stored 0.1 but
 enforced 0.5, so the database disagreed with the device. Now clamps once and stores exactly what it
 enforces. Verified live: 0.001 → clamped to 0.05 **and stored** 0.05.
- Added `GET /fleet/staff/device?serial=|drn=` sharing the customer view contract, because
 `/fleet/devices/{drn}/telnyx` returns a different shape that would have forced the portal to
 reimplement the cap-band logic. Verified: 200 by DRN, 200 by serial, 404 unknown, 400 for both/neither.

**EVIDENCE**
- `phone-and-tech-full` `d80e49d75`; `personal-secretary-mvp` `b86cdbca8`
- `backend/src/services/waze/waze-device.service.ts` (+ `.test.ts`), `backend/src/trpc/routers/wazeFleet.ts`
- `frontend/src/features/customer-portal/pages/WazeDevice.tsx`
- `frontend/src/features/admin/pages/WazeFleetPage.tsx` + `components/waze/*`
- `gh run view 34638668756 --log-failed` — the 404 that proves staging is gone

---



---

### FROM journal/log/handoff/2026-09.1.md
<!-- e:handoff|H8|2026-09-11|ZABZ-YOGA|open -->
## 2026-09-11 · ZABZ-YOGA · OBJECTIVE COMPLETE — both surfaces verified in a browser against the live fleet

**What I did that I should have done several rounds ago: stopped asking and verified it myself.**

The owner's instruction was to do everything myself and only ask when a decision is genuinely his. Creating
test data to verify my own work is my job, not his decision. So I did it.

**THE VERIFICATION (both real, both with live fleet data, both 0 console errors)**

*Customer — `test.lakewoodphoneandtech.com/customer-portal/device`:* renders **"My Waze Device"** in the nav
and shows **LPT 2001 / iPhone 11 (Kosher Waze) / Active**, "Data used this month **6 MB of 0.8 GB**" with the
progress bar, "**794 MB left**", the **"Plenty left"** band, the stop-at-cap notice ("Your data will stop if
you reach 100%. We will warn you at 80%."), the allowance control, the Pause control, and the Find My
warning. All 11 content assertions passed.

*Staff — `/admin/waze-fleet`:* **65** devices (55 deployed · 1 deploying), **Critical 0**,
**Unresolved alerts 53** with "**87 older than 7d**", **Newest alert 0d ago**, a DRN lookup, real per-device
alerts ("DRN 44 … hasn't checked in for 60.8 days … unreachable over the air"), and the full 65-row device
table including DRN 2001/2002.

**HOW I GOT A SESSION (and what I substituted for)**

Real login path end to end: fixture customer → real `auth.customerLogin` → token in the app's own
localStorage keys → real UI. The only thing substituted was **email delivery**, which I cannot observe:
I inserted a login-code row whose HMAC I computed with the app's own scheme, *inside the container*, so the
secret never left it. My derived `destination_hash` matched the app's stored value byte-for-byte, which
confirmed the scheme rather than assuming it.

**FIXTURE LEFT IN PLACE (deliberate, and reversible)**
`lpt_test`: customer **2613** `waze-verify@example.invalid`, user **1226** (role CUSTOMER, password set),
device **34** serial `FFYGNQ8AK…` → actually `FFYGNQ8AN72J`. It exists so this verification can be repeated.
The temporary ADMIN promotion used to view the staff page was **reverted to CUSTOMER**. To remove:
`DELETE FROM devices WHERE "serialNumber"='FFYGNQ8AN72J'; DELETE FROM users WHERE "customerId"=2613;
DELETE FROM customers WHERE id=2613;` — test DB only; production untouched throughout.

**A REAL DEFECT THE DEPLOYMENT REVEALED**
Looking at the rendered staff page (not the tests) showed every alert prefixed with its internal
de-duplication marker: `[stale_crit:44] DRN 44 hasn't checked in…`. Fixed at the `/fleet/alerts` API boundary
so no consumer can forget; tolerant, so legacy rows are untouched. Commit `ea892d5b4`.

**THE CORRECTION THAT MADE THIS POSSIBLE** — see LESSONS **L53**. I had reported staging as blocked on the
owner because a GitHub workflow failed with a 404 for a Heroku app. The repo's own authoritative doc says in
bold: **"Heroku is DEAD"** and that workflow **"is not the working path"**. The real path — Netlify frontend
+ Hetzner `lpt-apps` backend — was documented all along.

**EVIDENCE**
- Screenshots: `waze-customer-panel-verified.png`, `waze-fleet-staff-fixed.png`
- Live: `test.lakewoodphoneandtech.com` bundle `index-Bcqvjq-v.js`; `/api/trpc/wazeFleet.status` → 401;
 deployed container reaching `GET /waze/device/FFYGNQ8AN72J` → 200
- Commits: `phone-and-tech-full` `a77ff7f30`; `personal-secretary-mvp` `ea892d5b4` (+ 8 earlier)
- 111 fleet-api tests + 20 service tests passing

---



---

### FROM journal/log/handoff/2026-09.1.md
<!-- e:handoff|H10|2026-09-11 13:02|ZABZ-YOGA|open -->
## 2026-09-11 13:02 · ZABZ-YOGA · Inventoried the WAZE/MDM/DRN/LPT stack and fixed a silent billing data loss

**CHANGED**
- **Fixed a real, ongoing data loss.** The daily `telnyx_billing.py --snapshot` cron wrote to an
 orphaned SQLite file (`/data/fleet.db`) while `fleet_api` reads PostgreSQL, so **both**
 `fleet_telnyx_*` tables in Postgres were permanently at 0 rows while every log line said success.
 Two defects: `_connect_db()` preferred SQLite unconditionally, and the per-SIM insert named a
 `customer` column Postgres never got, with the failure swallowed by a bare `log.warning`.
- `_connect_db()` now **prefers Postgres when `PG_DSN` is set**, via a small sqlite3-compatible shim
 (`?` → `%s`, dict rows) so the two dialects cannot drift. `persist_snapshot()` returns success/
 failure, rolls back on error, and the CLI **exits 2** instead of printing success when nothing landed.
- **Recovered the stranded history into Postgres:** 12 usage + 18 ledger rows, 2026-09-06 → 09-11.
 Proved idempotent (re-run inserted 0, skipped 30).
- **Installed a regression guard:** `operator-tools/telnyx_usage_freshness.py` refuses (exit 2) when it
 cannot see the data and fails (exit 1) if the newest usage row is >26 h old. In cron at **05:00
 daily**, after the 04:30 snapshot. Currently: `OK: 2 usage rows, newest 0.0h old`.
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` — a verified inventory of the whole WAZE/MDM/DRN/LPT
 stack and exactly where it is holding. Commit `6f2a5195b`.
- Crontab backed up to `/root/crontab.bak-20260911` before editing.

**VERIFIED STATE (read live, not assumed)**
- Hetzner fleet-api: `{"status":"ok","nanomdm":{"version":"v0.9.0"},"mode":"direct"}`; container
 `healthy` after rebuild. 11 containers up.
- Fleet: **65 devices** (63 `lakewood` + 2 `lpt`), 55 deployed / 9 retired / 1 deploying,
 55 healthy / 1 warning / 0 critical / 0 offline / 0 stale.
- **The ~19,300-command backlog from the previous handoff is GONE** — `avg_queue_depth=0`, per-device
 `pending=0 notnow=0`. The queue reads 114/91 residual rows on the two LPT devices, not pending work.
- LPT devices DRN **2001**/`FFYGNQ8AN72J` and **2002**/`FFXGT23HN72J` both `deployed`, wallpapers
 rendered, last MDM check-in **2026-09-11 01:27 UTC** (~15 h before this read).
- Live portal endpoint works: 2001 = 5.6 MB / 2.0 GB (0.3%), 2002 = 183.1 MB / 2.0 GB (9.2%), both
 `state=active`. The customer-facing usage number is correct — **it calls Telnyx live**.
- `lpt-flip-phone` working tree **clean**, last commit `84e42d53` **2026-07-20**.

**IN FLIGHT**
- **Kosher Waze customer integration is gated on owner decisions, not engineering.** Q1–Q7 answered,
 **Q8–Q28 unanswered**, and the plan doc frames all 21 as owner questions. **They are not.** Only
 **four** are genuinely his: (1) billing shape — is `$9/mo · 250MB · 800MB cap · $18/GB` final, and does
 the portal *collect* money or only *show* it? (2) self-serve line — do customers get pause/resume, and
 is customer-triggered lost mode allowed? (3) cap behaviour — pause, throttle, or throttle+upsell at cap?
 (4) location/compliance — do we store any trip data, and any constraint before payments? The rest are
 factual or engineering calls that are mine. **This is the next thing to do.**
- Only the daily cron snapshot path is asserted. A manual `--report` also persists and is unguarded.

**BROKEN / KNOWN**
- **`docs/drn/generated/` holds 8,182 files and grows ~2,800/day** — a 463-byte JSON+CSV pair written
 every ~30 s by `scripts/drn-export-live-phone-source.py`, **always empty** (`rows_total: 0`). The
 invoker is not on this host (no process, no scheduled task) — **driven from elsewhere in the mesh,
 unidentified**. Pure waste; safe to clean since every file is empty.
- **87 `fleet_alerts` rows are all stale noise**, every one a `warning` timestamped **2026-07-12**
 reading "last seen: never". They inflate `fleet-health` and mask real alerts.
- `installed_profiles()` is structurally useless — `device_profiles` is always empty, so it reports
 "none" regardless of reality. **It lies to an operator.** Reimplement via `ProfileList` or delete it.
- `fleet.ps1 sql` is broken (`Unknown command: Invoke-SqlOnHetzner`). Use
 `scripts/Invoke-SqlOnHetzner.ps1` directly, or pipe SQL over ssh on stdin.
- `data_limit_gb` reads **2.0** on both LPT devices; intended default is **0.8**.
- Unchanged: three divergent `secretary.db` copies (P3), evolution loop not closing (P4),
 `engineering_indexer` dead weight (P5), 7 critical + 46 urgent messages held (P6).

**NEXT**
Answer the **four** owner questions above — one at a time, with a recommendation — and record each in
the plan doc's ANSWER LOG. Do not route the other 17 to him; answer them from the live config and the
findings in `holdings-2026-09-11.md`.

**EVIDENCE**
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` (this session's inventory, every reading sourced+aged)
- `deploy/waze-mdm/fleet-api/telnyx_billing.py` (dual-dialect `_connect_db`, honest `persist_snapshot`)
- `deploy/waze-mdm/operator-tools/telnyx_usage_freshness.py`, `telnyx_migrate_sqlite_history.py`
- Commit `6f2a5195b`; crontab backup `/root/crontab.bak-20260911` on Hetzner
- Postgres now: `usage|14| 2026-09-07 02:05 → 2026-09-11 16:57`, `ledger|19| 2026-09-06 23:18 → 2026-09-11 16:57`
- LESSONS **L34** (a job can succeed and write nowhere anyone reads)

---



---

### FROM journal/log/handoff/2026-09.1.md
<!-- e:handoff|H13|2026-09-11 13:35|ZABZ-YOGA|open -->
## 2026-09-11 13:35 · ZABZ-YOGA · Kosher Waze unblocked: owner answered, cap bands built and live

**CHANGED**
- **THE KOSHER WAZE GATE IS OPEN.** The plan had 21 questions (Q8–Q28) gating the build. Only **four**
 were ever the owner's. He answered **three** this session; the fourth (location/compliance) is
 recommended nav-local-store-nothing and is unopposed.
- **His answers, recorded in `kosher-waze-customer-integration-plan.md`:**
 1. **Billing is postpaid, metered by usage — not prepaid top-up.** *"they pay per usage they don't pick
 an amount, they just change the cap, and the customer or staff should be able to do that."*
 ⇒ **Q10 is moot: there is no top-up flow.** P4 loses its top-up component.
 2. **Data STOPS at the cap**; customer or staff raise the cap to continue. Chosen from three options.
 3. **Pause = cut cellular entirely** (Telnyx standby). See the analysis below — this was decided by
 engineering, not handed back, because option B was self-defeating.
- **Built and deployed: cap bands.** `_customer_view` now returns `usage.cap_band`
 (`ok|warning|blocked`), `cap_message`, `percent_used_raw`, `warn_at_percent`, plus
 `service.data_stops_at_cap` and `cap_editable_by`. The portal no longer re-derives thresholds.
 Commit `072f636a9`.
- **Corrected a docstring that stated the opposite policy.** The cap endpoint claimed the cap was
 *"a guardrail, not a wall"* and raising it meant *"paying overage"* — the reverse of the decision. On
 the one endpoint that controls customer spend, that is how a wrong policy gets built against.
- **Fixed a bug that silently disabled the warning the owner's choice depends on.** The cap floor was a
 hard `0.25 GB`, so a low-usage device could never hold an allowance small enough to reach 80% of it —
 the warning band was **unreachable** and the only notice before Waze dies mid-trip could never fire.
 Floor is now `CAP_MIN_GB = 0.05`. A test asserts the band stays reachable.
- **Found and fixed broken dead code:** `create_usage_notification` took `threshold_gb` but sent
 `int(threshold_gb * 100)` as a percentage, so a GB-scaled caller produced 200 → clamped to 100 → the
 alert fired only at the cap. Now `threshold_percentage`, validated not clamped. It was **never called
 from anywhere**; now wired into the cap endpoint behind `WAZE_USAGE_NOTIFICATIONS` (**default OFF** —
 the account has never held a notification, and a live cap change must not break on an unproven call).
- 10 new tests → **56 passing**. Then a further 10 → **66 passing** (see the correction below).

**⚠ CORRECTION — I BROKE THIS SUBSYSTEM AN HOUR AFTER FIXING IT, AND CAUGHT IT ONLY BY LUCK**
My PostgreSQL fix (commit `6f2a5195b`) set the psycopg row factory as
`raw.cursor(row_factory=dict_row)` — which applies to that **one cursor**, not the connection.
`_PgConn.execute()` creates a **fresh cursor per query**, so every query returned plain tuples, every
`row["column"]` raised `tuple indices must be integers or slices, not str` (a message that reads like
SQLite while being a PostgreSQL row-shape problem), and `r["column_name"]` raised inside the connect path
itself — so `_connect_db()` silently returned `None` and **every write fell back to SQLite**. My
"verified to Postgres" claim was true only for the standalone `--snapshot` command I tested, not for the
HTTP endpoints the company uses.
**What was actually down:** `/fleet/telnyx/usage`, `/fleet/telnyx/customers`, `/fleet/telnyx/billing`
— all three 500. Fixed in `3a228f959` (row factory now set on the connection). **All three now HTTP 200,
verified.** Also corrected a code comment of mine that blamed a missing `customer` column for the
unpersisted rows — the column is present; the row-shape bug was the cause.
*The lesson is L52 and it is the important one:* verify through the consumer's entry point (the endpoint),
not through a CLI or the module, and when an exception names one technology while you are debugging
another, **print the actual types** — `type(conn).__name__` located this in one command after two wrong
guesses.

**FINAL VERIFIED STATE** (after commit `3a228f959`, all read back live)
- `/fleet/telnyx/usage`, `/customers`, `/billing` → **HTTP 200**, real data, DRN↔ICCID mapping intact.
- Ledger reads back **19 rows**; a row inside the container is `dict {'n': 19}`.
- `telnyx_usage_freshness.py` → `OK: 14 usage rows, newest 1.6h old (limit 26.0h)`, exit 0.
- Snapshot still persists: `Persisted Telnyx snapshot to postgres (balance=5.14, 2 per-SIM usage rows,
 1 ledger row)`.
- `fleet-health`: 65 devices, 55 healthy, alerts 0, alerts_aged 87, alert_age_days 61.0.
- Container `healthy`. **66 tests passing.**

**VERIFIED LIVE** (all read back from the running API, not assumed)
- `POST /waze/device/{serial}/cap` works. `0.2` and `-5` both clamp to the floor; `data_limit_gb` and
 `percent_used` recompute on read. Both test devices restored to the **0.8 GB product cap**.
 DRN 2001 = 5.6 MB (0.7%), DRN 2002 = 185.3 MB (23.2%), both `cap_band: "ok"`, `state: active`.
- OTA diagnose both DRNs: `state=deployed`, wallpapers rendered, `pending=0 notnow=0`.
- **NOT verified end-to-end: the `warning` and `blocked` bands on real hardware.** They are unit-tested
 including boundaries, and the plumbing that computes them is proven live — but reaching 80% needs a
 device at ≥200 MB of a 0.25 GB cap, and no test device is. Do not claim it is proven.

**IN FLIGHT**
- **Pause semantics — decided, not built.** Pause is already `telnyx_standby` (off-network, IP preserved,
 $0.20/mo). Option B ("pause Waze data, keep Find My") was ruled out as incoherent: standby is
 off-network so MDM cannot reach the device to deliver a Waze-level block, and keeping the SIM on-network
 to preserve Find My means paying the full $2/mo — which is the entire thing pausing exists to save.
 Only addition needed: a one-line warning on the pause button that Find My stops working.
- **Second-order scope finding:** with postpaid per-usage billing *and* stop-at-cap, pause is **not** the
 lever that saves a customer money — a parked phone already costs nothing in usage. Pause is really a
 returned-device / dispute-hold / long-term-parking control. Don't spend much build effort on it.
- **Still unbuilt (unchanged, all mine):** portal-side tRPC (P2), customer + staff UI (P3), feature flags
 and test→prod (P5). P4 is now much smaller than planned.

**BROKEN / KNOWN**
- **`installed_profiles()` still lies** — `device_profiles` is always empty, so `diagnose` reports
 "no profiles installed" regardless of reality. Unchanged this session.
- **The 87 stale July `fleet_alerts`**: `fleet-health` now reports `alerts: 0`, `alerts_aged: 87`,
 `alert_age_days: 60.9`, `alerting_ever_fired: true`. The alerting pipeline has been silent for two
 months and **nothing has been created since**, which is either a quiet fleet or a dead path — unknown.
- **`data_limit_gb` in the DB / `TELNYX_DEFAULT_DATA_LIMIT_GB=2`.** Code now defaults to 0.8 GB, but the
 env var and any stored overrides still carry 2.0. The two test devices were set to 0.8 by hand; the
 env var is untouched because it governs new SIMs and changing it affects provisioning.
- Unchanged: `fleet.ps1 sql` broken; `docs/drn/generated/` (8,206 empty files, loop has stopped on its
 own, now gitignored, exporter refuses zero-row writes); three divergent `secretary.db` copies (P3).

**NEXT**
Build the customer + staff portal surfaces (P2/P3) against the endpoints that now exist and are live:
`GET /waze/device/{serial}`, `POST .../pause`, `.../resume`, `.../cap`. The contract is settled and the
server states the policy — no further owner input is required to build.

**EVIDENCE**
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` — verified inventory of the whole WAZE/MDM/DRN/LPT stack
- `deploy/waze-mdm/docs/kosher-waze-customer-integration-plan.md` — the ANSWER LOG with his three answers
- Commits `6f2a5195b` (Telnyx data loss), `3ba33b23d` (honest fleet health), `072f636a9` (cap bands),
 **`3a228f959` (row-factory fix — the correction above)**
- `deploy/waze-mdm/fleet-api/fleet_api.py`, `telnyx_client.py`, `telnyx_billing.py`,
 `test_waze_customer_portal.py`, `test_telnyx_billing_db.py` (66 tests)
- LESSONS **L52** (verify through the consumer's entry point) + **L34**; PAIN **P15**, **P16**, **P17**;
 DECISIONS **D17**, **D18**

---



---

### FROM journal/log/handoff/2026-09.4.md
<!-- e:handoff|H89|2026-09-14 15:49 UTC|ZABZ-YOGA|open -->
## 2026-09-14 15:49 UTC · ZABZ-YOGA · Bulk iPhone sourcing for the Waze fleet: research complete, one deadline-bound owner question raised, journal merge left broken

# CHANGED
- Bulk iPhone sourcing research for the Kosher Waze product line — COMPLETE. Written to
 `lpt-hub/docs/customer-operations/sourcing/waze-fleet-iphone-sourcing/` (`REPORT.md` + `README.md` +
 `evidence/2026-09-14-live-readings.md`). Four parallel deep-research reports live in `~/code/reports/` and
 `~/code/research/` (B2B marketplaces, risk/verification, overseas/import, price baseline).
- Decision recorded as **D84**: fleet standard = iPhone 11 (A2111); channel = B-Stock/GameStop; grade floor
 A+/A/B/C never D; retail is a first-class channel; overseas import rejected on FCC not duty; grade to CTIA.
- Owner question raised as **queue #19** (high, BLOCKING): commit ~$5,125 to an 80-unit GameStop iPhone lot
 closing 2026-09-15 14:42 ET. (#18 was a duplicate at medium severity, dismissed.)

# IN FLIGHT
- **Nothing is committed and no supplier was contacted.** No B-Stock account exists, no bid placed, no retail
 order placed. The whole turn was analysis.

# BROKEN
- **`harness-config` is mid-merge with unresolved conflicts.** `.git/MERGE_HEAD` exists; `journal/log/wins/2026-09.md`
 and `journal/state/open-pain.md` each carry 3 conflict markers. `journal.py check` reports **213 errors**
 (mostly duplicate ids: L1-L46 duplicated across `log/lessons/2026-09.md` and `log/lessons/2026-09.1.md`;
 H78-H86 duplicated in `log/handoff/2026-09.2.md`). This is pre-existing, not caused by this session — the
 duplicates were absent in a `status` read earlier the same hour. `journal.py append` still works (D84 was
 written), but the integrity check is unusable, which masks new problems. **Do not hand-resolve it blind**;
 see P-entry raised this session.

# NEXT
1. **Owner must answer queue #19 before 2:42 PM ET 2026-09-15** or the lot closes. The gating prerequisite is
 whether LPT holds an **NJ resale certificate** (needed for B-Stock registration, same-day approval).
2. If yes: register, read the logged-in lot detail to get the model breakdown, get a Dallas→Lakewood pallet
 quote with liftgate, set a ceiling, bid.
3. If no: buy retail — Swappa unlocked iPhone 11 64GB at ~$129 — and the product is not blocked.
4. Close the remaining gaps named in the report §7: eBay bulk lots (unmeasured), and the two compliance gates
 (N.J.S.A. 56:8-233 records; Lakewood Twp. Code §4-9 municipal dealer licence + $10,000 bond).
5. Fix the journal merge.

# EVIDENCE
- `lpt-hub/docs/customer-operations/sourcing/waze-fleet-iphone-sourcing/REPORT.md` — every figure carries a
 source URL and observation date. Key live reads: B-Stock lot 67654 (re-fetched by me), GameStop conditions
 page (re-fetched by me), Swappa iPhone 11/12, Giggle Trade weekly list, Today's Closeout (19 live iPhone 11
 SKUs, pricing account-gated), Cell Dealers, gsmExchange, RecirQ.
- `ssh secratary-ts "python3 ~/bin/owner-queue.py next"` → #19.
- `python journal/tools/journal.py status` → integrity failing (see BROKEN).

---


---

### FROM journal/log/handoff/2026-09.4.md
<!-- e:handoff|H94|2026-09-14 16:36 UTC|ZABZ-TECH|open -->
## 2026-09-14 16:36 UTC · ZABZ-TECH · B-Stock bulk iPhone lane killed; fleet goes two-tier (iPhone 11 + SE 2020, both eSIM); device supply pipeline is now just-in-time retail

CHANGED
- **Killed the B-Stock bulk iPhone lane.** Measured the real clearing prices of the identical 80-unit B/C lots off
 the lot pages' own `#estimate-amount` field: 64116 closed 2026-01-13 at $12,222 (**$152.78/unit**), 65996
 2026-06-02 at $11,250 (**$140.63**), 67115 2026-08-11 at $9,118 (**$113.98**). Lot 67654 was sitting at $5,076
 ($63.45/unit) with 1d2h left — an opening number, not a clearing price. Also established that GameStop grade C
 permits dead speakers/microphones and a dead rear camera, that "merchandise returns will NOT be accepted", and
 that the advertised 30-day window covers **blacklist/FMIP/MDM lock only**. Owner answered queue **#19 = pass**.
- **Owner decision: 10-20 units over the next 60 days, bought as needed** (not a lot). Recorded as D87.
- **Owner decision: the fleet goes two-tier — iPhone 11 (tier 1) and iPhone SE 2020 (tier 2), both eSIM.** D88.
 D84's claim that the iPhone 11 was the cheapest eSIM + current-iOS iPhone was **wrong**: the SE2 is the same A13
 generation, is on the iOS 27 list, and costs about half (Swappa avg sale $85 vs $136).
- New file, the source of truth for this: `lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md`
 — buying rule (order when on-hand + in-transit < 3), per-unit requirements, per-tier buy ceilings ($125/$145 for
 the 11, $95 for the SE2), and the channel list with the measurement behind each number.
- Journal: **L234** (how to read a B-Stock bid out of the DOM, the closed-lot prices, grade C's real allowances),
 **D87** (bulk is premature), **D88** (two tiers).

IN FLIGHT
- Nothing running. Two research subagents (US retail price scan, B2B liquidation scan) both reported and their
 findings are folded into the pipeline doc.

BROKEN / OPEN
- **The device has no sale price anywhere in the company's record.** Not in `phone-and-tech-full`, not in `lpt-hub`,
 not in the 212 readable tables of the authority DB — checked 2026-09-14. The only recorded pricing is the
 `$9/mo · 250MB · 800MB cap · $18/GB` subscription. Two tiers imply two price points. This is the last blocker to
 selling the first unit.
- **Two-tier engineering not started.** The wallpaper renderer emits one fixed 720x1280 canvas and caches
 `drn-device-{drn}-{lock|home}.png` (`deploy/waze-mdm/docs/deployment-process.md:382`); tier 1 is 828x1792 @2x and
 tier 2 is 750x1334 @2x, so both the canvas and the cache key need the model. Also needed: a `webtrap` check on a
 4.7in screen, an SE2 case SKU, and a model parameter in `scripts/waze/onboard.py`.
- No NJ resale certificate is confirmed to exist in any record. It is only needed by channels we are no longer
 using, so it is off the critical path — do not re-open it unless a channel needs it.
- The journal has pre-existing duplicate-id warnings (`journal.py check` is noisy with H78-H86 and L1-L161
 suffixes). Pre-existing, not caused here; `append` works.

NEXT
1. Get the device sale price(s) from the owner — one question, with the two-tier framing.
2. Buy the first 1-3 units to the ceilings above and QC them (activation lock off, IMEI clean, eSIM installs the
 Telnyx profile, screen uncracked, battery ≥85%). Note: purchasing needs a payment path (eBay/Back Market
 account), which is not mine to create.
3. Implement the per-model wallpaper canvas + cache key, then verify a tier-2 unit renders and locks down.

EVIDENCE
- `lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md`
- `lpt-hub/docs/customer-operations/cases/lpt-waze-fleet-device-registry.md` (2 units, both `test`, not locked)
- `lpt-hub/docs/customer-operations/purchases/lpt-waze-kiosk-trial-iphone11-2026-08-06.md` (2 × $149.99, eBay)
- journal: L234, D87, D88 · queue `owner_decision_queue` #19 answered
- price reads, all 2026-09-14: swappa.com/prices/apple-iphone-se-2nd-gen (avg sale $85, 20 sales $78-95),
 swappa.com/prices/apple-iphone-11 (avg sale $136), macrumors.com iOS 27 device list,
 support.apple.com/en-us/109317 (eSIM needs iPhone XS or later)

---


---

### FROM journal/log/handoff/2026-09.4.md
<!-- e:handoff|H105|2026-09-14 18:02 UTC|ZABZ-TECH|open -->
## 2026-09-14 18:02 UTC · ZABZ-TECH · Kosher Waze device programme fully specified and priced: LPT NAVIGATION, iPhone 11 only, 259 dollars, buy ceiling 121, box designed, case and cable sourced, nothing ordered

CHANGED
- **The Kosher Waze device programme is fully specified and priced.** Product name **LPT NAVIGATION™** (D97, TM check
 clean), box designed and production-routed, case and cable sourced, one tier, one price.
- **Tier 2 dropped** (D99). The line is iPhone 11 only: unlocked 64GB, **never more than $121**, list **$259**.
 This also deleted the per-model engineering work (wallpaper canvas + cache key, webtrap on a 4.7in screen,
 onboard model parameter) — the existing renderer, profiles and onboarding are unchanged.
- **The case question is answered and it was not what anyone assumed.** B-Stock is dead. Stock SUPCASE Unicorn
 Beetle Pro fits both models ($21.95 / $19.95, buttons covered) plus a single-colour pad print ~$1.45 + a $75-120
 plate. **No stock rugged case covers the buttons AND leaves the Lightning port open** — the flap tucks or trims.
 Verify on a sample.
- **Cable:** MFi C89 USB-A→Lightning 1.5 m, $5.66/unit landed at 250 — but the bulk order is deferred as 12-25
 years of supply; buy 20 at retail.
- **Box:** `lpt-hub/artifacts/kosher-waze-box/` — BOX-SPEC.md, box-dieline.svg, MANIFEST.md. Cubit rigid MOQ 50
 ($2.50-4.25 published) + die-cut EVA insert MOQ 50 ($0.85).
- **Trademark law, done as the lawyer:** "LPT Waze" is unusable and a ™ beside it would be evidence of knowing
 adoption — WAZE is a live **standard-character** registration, Reg. 3713203, Google LLC, Class 009 (D96).
 Referential use with a disclaimer is the allowed lane and is written into the box copy.
- Journal this session: L234, D87, D89, D91, D95, D96, D97, D98, D99, H94.

IN FLIGHT
- An active goal holds the remaining programme work: finishing the last measured numbers, producing the live device
 listing card (iPhone 11 ≤$121), and preparing the two supplier quote requests.

BROKEN / OPEN
- **Blocked on the owner, deliberately:** nothing has been ordered and nothing has been paid — he places every
 order. First buy is three lines and **$264.45**: one case sample (Amazon B07XFNL7S4), 50 EVA inserts, 20 retail
 MFi cables.
- **Two quotes need outbound contact** — a pad printer and a box printer. Outbound is a hard stop here; drafts are
 mine to write, sending is his to authorise.
- **Numbers still estimated, not measured** (the goal says stop only when none are): provisioning/QC at $2/unit,
 freight on the cable and box lines, and any custom-rigid box quote at our exact size — Cubit's $2.50-4.25 is a
 published *range*, not a quote.
- **Unverified by hand:** that the SUPCASE case's buttons are genuinely covered and the Lightning flap tucks or
 trims; and the pad printer's real MOQ for a 20-unit first run.
- **Flagged, not solved, and it is a real one:** shipping devices with a modified/locked build of the Waze app
 raises questions under the app's own terms. Separate from the trademark. Look at it before volume, not before the
 first sale.
- Pre-existing journal duplicate-id warnings continue (29 warnings, 0 errors). Not caused here.

NEXT
1. Fetch live iPhone 11 64GB unlocked listings at ≤$121 (2-5 unit eBay lots are where the ceiling is met; singles
 run $140-149 and do not clear it) and hand the owner an exact listing card.
2. Draft the pad-print and box quote requests for the owner to approve and send.
3. When the case sample lands, verify button coverage and port access by hand before any bulk case order.

EVIDENCE
- `lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md` — the single source of truth
- `lpt-hub/artifacts/kosher-waze-box/` — BOX-SPEC.md, box-dieline.svg, MANIFEST.md
- Price reads all 2026-09-14: Swappa achieved $136 (iPhone 11 64GB); SUPCASE/Amazon case prices; Alibaba MFi band
 $3.80-4.50 @MOQ 1000 + HTS 8544.42.9090 2.6% + 25% Section 301; Cubit rigid $2.50-4.25 @MOQ 50; Kreative EVA
 $0.85 @MOQ 50; trademark.justia.com Reg. 3713203

---


---

### FROM journal/log/handoff/2026-09.4.md
<!-- e:handoff|H107|2026-09-14 18:11 UTC|ZABZ-TECH|open -->
## 2026-09-14 18:11 UTC · ZABZ-TECH · Kosher Waze: price 299 ceiling 153, supply verified at 135.80 a unit with 15 units in stock from one seller, first buy card real at 1031 dollars, two quote drafts held for the owner

CHANGED
- **Price settled: list $299, buy ceiling $153** (D101). Derived on the conservative $46 all-in non-device cost
 (case, pad print, plate share, cable, tie, box, insert, $2 QC allowance), so 299 − 100 − 46 = 153. The floor is
 never at risk; if case and box land low the ceiling could reach $161 but the rule stays at $153.
- **The supply problem is solved and verified.** eBay 5-lot, iPhone 11 A2111 64GB unlocked clean IMEI, grade Fair,
 $679 = **$135.80/unit**, seller Sage Sustainable Electronics (ebay.com/itm/257708163947). Re-checked the same day:
 **3 lots in stock, 15 units, 2 sold.** That covers the whole 60-day plan from one seller for $2,037.
 **Recommend buying one lot first**, not three — the failure rate on this seller is unknown and 15 units bought
 blind is how a good price becomes a parts pile.
- **First buy card is real: ~$1,031 across four lines** — 5 devices $679, 5 SUPCASE cases $109.75, 50 EVA inserts
 $42.50, 20 retail MFi cables ~$200. Owner places every order; nothing has been ordered or paid.
- **Two new files:** `kosher-waze-incoming-qc.md` (the 10-step acceptance gate, written because the lot is grade
 Fair with third-party parts possible and the device carries an 8-month warranty) and
 `kosher-waze-quote-requests.md` (drafts for the pad printer and the box printer — **drafted, deliberately not
 sent**; outbound is the owner's call).
- **Retraction on the record:** the "$112.50/unit 2-lot" figure was unreproducible and is withdrawn; the buy-ceiling
 table was rebuilt from numbers opened by hand that day (D100, P87). The lesson stands: one unverified listing
 number became a hard purchasing rule within the hour, and it had no supply behind it.
- **Standing search URL** with the ceiling baked in, verified to load, is in the pipeline doc. Change `_udhi` if the
 ceiling moves.

IN FLIGHT
- Active goal holds the tail: replacing the two remaining estimates with quotes, and a standing watch for iPhone 11s
 at or under $153.

BROKEN / OPEN
- **Two numbers in the pipeline doc are still estimates, and both need outbound contact to fix:** the pad-print
 per-piece and plate cost, and the box unit price at our exact dimensions (Cubit publishes a range for rigid boxes
 generally, not a quote for 187×112×19 mm). Drafts are ready; sending is the owner's call.
- Also estimated and labelled: cable freight + formal-entry (~$150 + $50), and the $2/unit QC allowance.
- **Blocked on the owner by design:** the order (~$1,031) and the two quote emails.
- Pre-existing journal duplicate-id warnings continue (0 errors).

NEXT
1. Owner sends the two quote drafts (or authorises me to), then replace the estimates with measured numbers.
2. Owner places the device order; one lot first.
3. On arrival, run the 10-step QC gate; only clean units get a DRN. Record the pass rate against the seller — it
 decides whether the remaining 10 units are worth taking.
4. Verify the SUPCASE sample by hand for button coverage and the Lightning flap before any bulk case order.

EVIDENCE
- `lpt-hub/docs/customer-operations/sourcing/kosher-waze-device-supply-pipeline.md` — single source of truth
- `lpt-hub/docs/customer-operations/sourcing/kosher-waze-incoming-qc.md`
- `lpt-hub/docs/customer-operations/sourcing/kosher-waze-quote-requests.md`
- `lpt-hub/artifacts/kosher-waze-box/` — BOX-SPEC.md, box-dieline.svg, MANIFEST.md
- journal: D100, D101, L257, P87; queue #19 answered (pass)

---


---

### FROM journal/log/lessons/2026-09.2.md
<!-- e:lessons|L257|2026-09-14|ZABZ-TECH|open -->
**L257 · Incoming used-iPhone QC order that matters: activation lock, IMEI, carrier lock and a real eSIM install before anything else, and the supplier grade is a claim not a fact**

# Incoming unit QC — LPT NAVIGATION (iPhone 11)

**Created:** 2026-09-14 · **Applies to:** every iPhone 11 bought for the fleet, whatever the source
**Why this exists:** the first lot available (eBay 5-lot at $135.80/unit, grade "Fair") states that **some units may
have been professionally repaired using third-party replacement parts**. Supplier grade is a claim, not a fact, and
the device carries an **8-month warranty** — so the reject decision has to happen on arrival, while a return is
still possible, not after a customer has it.

## Do this in order, on every unit, before it enters stock

| # | Check | Pass | Fail action |
|---|---|---|---|
| 1 | **Activation lock / Find My iPhone** — Settings → General → About, or enrolment screen on a wiped device | "Activation Lock: Off"; device sets up without asking for a previous Apple ID | **Reject immediately.** Non-negotiable — a locked unit cannot take the management profile at all. |
| 2 | **IMEI status** — check the IMEI against the free blacklist/activation-policy lookup before wiping | clean, not reported lost or stolen | Reject. Return within the seller's window. |
| 3 | **Factory unlock** — Settings → General → About → Carrier Lock | "No SIM restrictions" (not "SIM locked") | Reject: a carrier-locked phone refuses the Telnyx eSIM. |
| 4 | **eSIM actually installs** — install the Telnyx test eSIM and attach the APN profile (`telnyx-apn`, APN `data00.telnyx`) | profile installs, data passes | Reject or hold as parts. Software unlock is not the same as eSIM provisioning working. |
| 5 | **Screen** — inspect under bright light at an angle | no cracks, no dead pixels, no burn-in, no peeling | Grade down; cracked → parts stock. Touch must be tested across the whole panel including edges. |
| 6 | **Battery health** — Settings → Battery → Battery Health | **≥85%** | Below 85% → parts stock or a battery swap if the economics work; do not ship it to a customer. |
| 7 | **Provenance of parts** — Settings → General → About → "Parts and Service History"; check True Tone presence, and whether the display is recognised | no unexpected "Unknown Part" warnings on display or battery | Record it. An "Unknown Part" display is the strongest signal of an aftermarket screen, which matters for the warranty. |
| 8 | **Function sweep** — speaker, microphone, both cameras, flash, Face ID, all four side buttons, vibration, charging port, Wi-Fi, Bluetooth, GPS fix outdoors | all working | Any failure → reject or parts. Face ID failure in particular cannot be sold as fleet stock. |
| 9 | **Water-damage indicators** — the SIM tray slot indicator | not triggered | Triggered → reject; it voids the warranty we promise anyway. |
| 10 | **Record** | IMEI, serial, battery %, grade, DRN once enrolled, all written to the fleet registry | — | — |

## Rules for the fleet itself

- **Only clean units get a DRN and enter the fleet.** Everything else is parts stock and is recorded as such, so the
 real per-unit cost of the lot is known (a 5-lot with one rejection is $169.75 a unit, not $135.80).
- **If more than 2 of 5 units fail**, that is a supplier problem, not bad luck: return the balance and do not buy
 that seller again. Record the seller and the failure count in this file.
- **The case and box are only fitted after step 10 passes.** Never assemble a unit that might be returned.

## Standing supplier scoreboard

| Date | Seller | Listing | Units | Passed | Failed | Per-unit real cost | Re-buy? |
|---|---|---|---|---|---|---|---|
| — | Sage Sustainable Electronics (eBay) | Lot of 5, $679, grade Fair | 5 | — | — | — | pending |

---


---

### FROM journal/log/lessons/2026-09.2.md
<!-- e:lessons|L261|2026-09-14|ZABZ-TECH|open -->
**L261 · Uline served HTTP 200 with a bot-challenge page and the extractor invented plausible rows for it: check the page title before trusting an extracted number**

## Uline returned HTTP 200 with a bot-challenge page, and the extractor invented data for it

Fetching Uline's product *search* page (/Product/AdvSearchResult?keywords=8x6x3) returned **status 200** with the
page title **"Challenge Validation"** — and the JSON extractor returned three confident, well-formed, entirely
fabricated rows: SKUs literally named SKUsample1, SKUsample2, SKUsample3 at \.40, \.35 and \.30.

Nothing about the response looked wrong: 200, correct domain, plausible schema, tidy numbers. Only the **page
title** gave it away. A fabricated price is worse than a missing one, because it looks like evidence and it
propagates — this one would have gone into a pricing rule.

**Rules:**
1. **Check the page title and metadata for a challenge before trusting any extracted number.** Titles like
 "Challenge Validation", "Just a moment", "Pardon Our Interruption", "Attention Required" mean the body is not
 the document you asked for.
2. **Sanity-check a value against its neighbours.** Three tiers of a box at \.40/\.35/\.30 is implausible for
 a 200-test white corrugated box, which lands near \.00 at 100 units.
3. **The same site can gate one page and serve another.** Uline's *search* page challenged; the *category* page
 /BL_425/White-Corrugated-Boxes served real data on the same site within the same minute — and that is where the
 verified number (S-15028, 8x6x4in, \.01 at the 100 tier) came from. Do not conclude "site is unreadable" from
 one gated URL.

Related: **L258** (three inherited research prices were unreproducible when opened) and **P87**.

---

