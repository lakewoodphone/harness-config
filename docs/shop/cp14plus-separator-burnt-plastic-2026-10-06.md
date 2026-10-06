# Shop MECHANIC CP14+ screen separator — melted-plastic incident, verdict, and the no-cut cover fix

**Date:** 2026-10-06 · **Machine:** ZABZ-YOGA · **Owner:** Eliyahu · **Status:** closed, except the arrival test in §8.
**Question that opened it:** *"should i just throw it out?"*

---

## 1. The incident, in the owner's words

> *"the shop has a cp14 mechanic hot plate to remove screens / someone melted a plastic bag on it / i managed to scrape a
> lot off, but there is a big brown stain in middle, should i just throw it out?"*

> *"i feel like it can get on the next screen, should i just throw it out and buy a differnt one? is there another one
> that would prevent this in the future? how expensive is it anyways"*

> *"i may anyways want a better one and one that warns better when it's done heating"*

> *"i don't want to ever have to cut it, if it's hard to do i won't end up doing it"*

Four questions were asked: will it transfer onto the next screen, should it be replaced, is there a machine that prevents
this, and what does one cost. A fifth requirement was added later: whatever the fix is, it must need no cutting.

---

## 2. The machine, verified — and the one fact everything else follows from

MECHANIC **CP14 / CP14+**, a 14-inch LCD screen separator heating mat. Confirmed from four independent vendor listings
and the unit's own manual text (§13).

| | |
|---|---|
| Work area | 350 x 225 mm, 38 mm thick, 770 g |
| Power | 150 W |
| Temperature | 50-120°C; phone mode 10-120°C, tablet mode 10-90°C |
| **Heating surface** | **double-layer silicone heating plate — SILICONE, not metal** |
| Backlight | green LED dust-detection light *under* the heating surface |
| Other | USB 5 V output; settable countdown; audible "di" beeps on mode entry |

**The surface is silicone.** Two consequences, and neither is obvious from looking at it:

1. **Never abrade it.** No sandpaper, no wire brush, no razor blade at an angle. A metal plate could be sanded back to
   clean; this cannot.
2. **It is also the window the backlight shines through.** Abrading it does not merely scratch the finish, it destroys
   the dust-detection function. This is why the fix in §6 is a cover rather than a scrub.

---

## 3. Verdict on the stain

**Do not replace it.** A brown stain on a silicone mat is cosmetic plus a possible transfer risk. It is not structural.
The mat still reaches temperature, still heats evenly, and the plate is no more likely to fail because of it.

The only claim that would justify binning it — "it will get on the next screen" — is testable in two minutes, and the
test was never run (§4). The right sequence is: test it, clean it, cover it. Not replace it.

---

## 4. The transfer test — two minutes, and it is the only question that matters

Carbonised polymer can go tacky again at 80°C, so the risk is real but not automatic.

1. Heat the mat to 80°C.
2. Press a piece of clean glass onto the stain — an old screen protector or a dead LCD.
3. Lift it and look at the glass.

- **Smudge on the glass** → the residue transfers, and it will transfer to a customer's screen. Cover it before the next job.
- **Nothing on the glass** → inert carbon, harmless. Cover it anyway, because the next bag is the real problem.

**Not yet run.** Recorded as open in §12.

---

## 5. Cleaning procedure (if the residue is to be worked on at all)

1. Power to maximum (120°C) and let it stabilise for 10 minutes — the residue softens and loses its grip.
2. Scrape with a **plastic** razor blade or a wooden scraper held almost flat. Not a metal blade, not at an angle.
3. For the brown carbonised film: a melamine sponge (Magic Eraser) damp with IPA, light pressure. Do not use it dry and
   do not press hard — melamine is a micro-abrasive and the surface is soft.
4. **Never:** razor at an angle, sandpaper, wire brush, acetone soak (swells cured silicone), heat gun above ~200°C,
   oven cleaner (it does nothing to polyethylene anyway, and it attacks aluminium if the base is alloy).

The stain will lighten a great deal and may not vanish entirely. That is acceptable — §6 makes it irrelevant.

---

## 6. The fix: a PTFE cover sheet, and the arithmetic

### Why PTFE

PTFE (Teflon) has the lowest surface energy of any solid. **Nothing bonds to it.** A plastic bag that lands on a PTFE
sheet lifts off; the same bag fuses to silicone, which is exactly what happened. Service temperature is about 260°C, so a
120°C mat is a non-event. It is not part of the machine — it is a consumable that sits on top and gets replaced.

Most heat-press "Teflon sheets" are **woven PTFE-coated fibreglass**, not smooth film. That is the better kind here:
stiffer, it lies flat, and it grips the mat instead of sliding around. Smooth film is more prone to drifting.

### Thermal cost — the number that decided the purchase

Worst case, i.e. assuming *all* 150 W has to travel through the sheet:

```
q  = 150 W / 0.07875 m²  = 1905 W/m²
ΔT = q · t / k,   k(PTFE) ≈ 0.25 W/(m·K)
```

| Sheet thickness | Heat lost through it |
|---|---|
| 0.13 mm | 1.0°C |
| 0.2 mm | 1.5°C |
| 1.0 mm | 7.6°C |

This is a ceiling, not an estimate: most of the 150 W heats the air around the device rather than the device, so the
real figure is lower. The sheet actually purchased states **0.13 mm** → about **1.0°C**, which is inside the noise.
**The dial stays at 80.** (An earlier instruction to set it to 90 was for a 1 mm worst case that does not apply.)

Note that PTFE conducts heat about as well as the silicone it sits on — same material family, same order of thickness.
The cover is effectively a second layer of the thing already there.

### Size rule — covers the mat with no cutting

The mat is 350 x 225 mm, so **any sheet at least 350 mm on one axis covers it whole.** No scissors are needed at all.

| Size | Actual | Verdict |
|---|---|---|
| 12 x 16 in | 305 x 406 mm | **the tidy fit** — 56 mm and 80 mm of margin, sits on the machine like it was made for it |
| 16 x 12 in | 406 x 305 mm | same thing rotated |
| 11 x 17 in | 279 x 432 mm | covers, less margin |
| 16 x 20 in | 406 x 508 mm | covers, but drapes about 150 mm off the end of the machine |

### What the owner actually does with it

Lay it on the mat once. It lives there. It is **not** a step repeated per repair — it is picked up to shake dust off or
swapped for the next one, and nothing else. Setup is one action, once, five seconds. Nothing is cut, taped or aligned.

---

## 7. The purchase

| | |
|---|---|
| Product | 3 Pack Teflon Sheet For Heat Press, 12 x 16 in (Ubrand) |
| ASIN | `B08T7ZPW8L` |
| URL | https://www.amazon.com/dp/B08T7ZPW8L |
| Price | USD 5.49 |
| Material | PTFE + glass fibre — the woven, stiff, non-sliding kind (§6) |
| Thickness | 0.13 mm, stated in the listing |
| Quantity | 3 sheets = 3 covers |
| Ships from / sold by | Amazon / Bo Vera |
| Delivery | free, **Tomorrow, October 7**; "order within 12 hrs 53 mins" at 10:10 ET 2026-10-06 |
| Rated | 4.7 / 5 over 2,416 ratings |
| Delivery location verified against | **Lakewood 08701**, set on the live Amazon page before reading any promise |

### Why not the sheets already on screen

The 16 x 20 4-pack (`B0DK5CQPP8`, USD 7.59) and the 16 x 20 3-pack (`B07H55M1ZR`, USD 6.71) were the only two of 30
search results offering a same-day window — but the live page showed that window is **gated**: *free Today 5-10 PM only
on qualifying orders over USD 25*, otherwise a USD 4.99 three-hour fee, otherwise tomorrow. They also drape off the
machine. The chosen 12 x 16 arrives free tomorrow with no minimum.

*Provenance caveat:* whether the order has actually been **placed** is not verified. The owner was on the signed-in
Amazon page at 10:10 ET; no order confirmation was observed. Confirm before treating §8 as pending.

---

## 8. Acceptance test on arrival — 60 seconds

Amazon's own review summary for `B08T7ZPW8L` flags **mixed feedback on the non-stick property**. It is a minority — 4.7
across 2,416 ratings — but non-stick is the entire point of the purchase, so test it rather than assume it:

1. Mat to 80°C with the sheet on it.
2. Drop a scrap of plastic bag on the sheet. Leave it two minutes — long enough to melt and bond if it is going to.
3. Lift it with tweezers.

- **Comes away clean** → done, this is the fix, permanent.
- **Sticks** → return it (free 30-day) and switch to the woven TransOurDream 16 x 20 4-pack, ASIN `B0DK5CQPP8`, USD 7.59.

---

## 9. Corrections made during this session

Recorded because each one was wrong first, and the record of a wrong answer is worth more than a tidy one.

1. **Thermal loss.** First told the owner "under a degree", based on a thickness of 0.1 mm that came from **no source at
   all** — an assumption presented as an answer. Corrected to a range after a listing showed 0.04 in (~1 mm) → 7.6°C,
   then corrected again when the purchased product stated 0.13 mm → 1.0°C. The original figure turned out right for this
   product, but it was right by luck, not evidence. **Correct order: read the spec, then quote the number.**
2. **Cutting.** Instructed the owner to cut the sheet to size and offered an optimisation ("two covers per sheet"). He
   answered: *"i don't want to ever have to cut it, if it's hard to do i won't end up doing it."* A fix the owner will
   not perform is not a fix. Corrected to a size that fits uncut.
3. **Delivery.** Told him a same-day item would arrive today; the live page then showed it gated behind a 25-dollar cart
   minimum. Every delivery promise quoted after that was read off the real page with the delivery ZIP set.

---

## 10. Options considered and rejected

| Option | Decision and why |
|---|---|
| Replace the CP14+ | **Rejected.** The whole unit is USD 40.01 at all-spares (plus ~USD 30 shipping, 14 working days from CN) or USD 39.99-45.99 in stock US at diyfixtool. It is not broken. |
| "A better one that prevents this" | **None exists.** The two categories are a silicone mat (soft, backlit, right for phones) and a metal plate (TBK-968 class, 400°C — scrapeable, but part of a wire-separating machine for glass-on-LCD, wrong for prying modern laminated screens). Prevention is a cover, not a different machine. |
| A unit that warns better when heating is done | **Already owned.** The CP14+ manual documents a settable countdown (double-click `M`) and audible beeps; the feature was sitting unused. No unit in this class documents a genuine reached-temperature beeper — the MECHANIC 361 Mini+ (USD 26.76, Martview) documents an *over*-temperature alarm only. A kitchen timer beats all of them. |
| Mijing FL-12 vacuum separator (USD 82.39) / TBK-968 (USD 77.66) | **Rejected.** Real capability, wrong capability — they hold a screen by vacuum for wire separation, which is not what this shop does. |
| A second CP14+ as a shelf spare | **Rejected by the owner,** but it is the correct way to spend here if he ever wants to: it stops a ruined bench tool stalling the shop for two weeks. |

---

## 11. What the owner decided

- **2026-10-06, first pass:** keep the unit, cover it, order nothing (he selected *"order nothing — clean it and cover
  it"*).
- **Then:** asked for a link, and for something that needs no cutting.
- **Final:** the 12 x 16 Ubrand 3-pack at USD 5.49, free delivery 2026-10-07. No replacement machine. No cover-cutting.
  No cart padding to reach the 25-dollar same-day minimum.

---

## 12. Open items

- [ ] **Arrival test (§8)** — the actual acceptance test of the whole fix. Expected from 2026-10-07, if the order was placed.
- [ ] **Transfer test (§4)** on the existing stain — never run. Still unknown whether the residue smears onto glass today.
- [ ] **The cover dims the green dust light.** The sheet is brown and only partly translucent. If that proves annoying,
      the alternative is a clear polyimide (Kapton) sheet instead.
- **Mesh, separate issue, do not conflate with this document:** `secratary` was unreachable from ZABZ-YOGA at
  2026-10-06 09:23 ET — `ssh: connect to host secratary.tail93e6e6.ts.net port 22: Connection timed out`. Both research
  subagents failed on that and the work was done in-thread. Logged as **P2857**. Consequence for this file:
  `harness-config` cannot be pushed while the authority is down, so this document is committed locally only.

---

## 13. Sources

All read 2026-10-06.

| Fact | Source |
|---|---|
| CP14+ is a double-layer silicone heating plate, 350 x 225 mm, 150 W, 50-120°C, green backlight, USB 5 V | https://www.bemax.com.my/showproducts/productid/6470700/cid/0/bemax-mechanic-lcd-screen-remover-cp14/ and https://gsmserver.com.ua/ru/heating-station-separator-mat-mechanic-cp14plus-350x225-mm-with-backlight-50-120-c/ |
| Countdown, audible beeps, phone mode 10-120°C, tablet mode 10-90°C | https://www.diyfixtool.com/products/cpb-heating-pad-phone-lcd-screen-separator-opening-repair-machine |
| Whole-unit price USD 40.01, CN warehouse, USD 30.04 shipping, 14 working days | https://all-spares.com/en/heating-station-separator-mat-mechanic-cp14plus-350x225-mm-with-backlight-50-120-c/ |
| In-stock US alternative USD 39.99-45.99 | https://www.diyfixtool.com/products/cpb-heating-pad-phone-lcd-screen-separator-opening-repair-machine |
| Mijing FL-12 USD 82.39; TBK-968 USD 77.66; MECHANIC 361 Mini+ USD 26.76 | https://www.martview.com/ |
| Purchased sheet: PTFE + glass fibre, 0.13 mm, 16 x 12 in, USD 5.49, tomorrow | https://www.amazon.com/dp/B08T7ZPW8L (owner's signed-in session, Lakewood 08701) |
| Same-day gating and the 16 x 20 alternatives | https://www.amazon.com/dp/B0DK5CQPP8 and https://www.amazon.com/dp/B07H55M1ZR (same session) |

---

## Related records

Journal: **L3347** (the surface is silicone; cleaning and cover method), **L3350** (the thickness correction and the
no-cut sizing rule), **D2928** (decision: keep and cover, not replace), **P2857** (mesh unreachable, no fan-out).
Same folder: `customer-data-retention.md`.
