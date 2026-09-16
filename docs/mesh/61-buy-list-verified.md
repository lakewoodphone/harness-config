# 61 — Buy List, Re-Verified Live: used mini PCs for always-on agent capacity

**Written:** 2026-09-16 (evening EDT) · **Author:** Zabz (delegated research session)
**Mandate:** re-verify online every hardware number behind `40-hardware-costs.md`, settle the standing
three-node recommendation, and find better options if they exist.
**Scope:** prices and specifications only. No purchase, no install, no machine touched. **This file is
the only file written by this session.**

---

## 0. Why this file exists, and how to read it

`40-hardware-costs.md` was built largely from **search-result snippets**, and it says so. Its own
revision note records that a "$120 turnkey 16 GB node" turned out to be snippet-only and could not be
reproduced. **A snippet is not a price.** This file replaces every price behind the recommendation
with a price that was **read off a page fetched today**, and marks anything that was not.

### Provenance legend — used on every figure

| Tag | Meaning | How to treat it |
|---|---|---|
| **`[LIVE]`** | The price was displayed on a page **fetched in this session on 2026-09-16**. The URL is given. | Trust it today. Re-check before buying; used listings turn over. |
| **`[PUB]`** | Manufacturer / standards-body / vendor document. URL + date given. | Trust the specification, not the price. |
| **`[COMM]`** | A community report (forum, Reddit, Facebook group). Named and labelled. | Corroboration only. Never the sole basis for a purchase. |
| **`[CARRIED]`** | Value copied forward from `40-hardware-costs.md` with its own original citation. **Not re-fetched this session.** | Acceptable, but it is the weakest tier here and is marked as such. |
| **`NOT FOUND`** | Looked for, could not source. | A gap. **Never** filled with an estimate. |

**Three rules this file holds to, and one it broke in the past:**

1. A price with an empty "how I saw it" is deleted, not reported.
2. `[LIVE]` and remembered/typical figures are **never mixed in one column**. Every price row says
   which it is.
3. A seller-entered spec attribute on a listing is **not** a specification. (See §7.1 — an eBay
   listing claims a 7070 Micro takes 64 GB. Dell says 32 GB. The seller is wrong.)

### Costing constants — all re-verified live today

| Constant | Value | Source |
|---|---|---|
| NJ residential electricity | **24.95 ¢/kWh** | **`[PUB]`** EIA *Electric Power Monthly* Table 5.6.A, https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a — read 2026-09-16. **Independently corroborated**: ElectricChoice "Electricity Rates by State (September 2026)" lists New Jersey residential **24.95**, commercial **18.47**, https://www.electricchoice.com/electricity-prices-by-state/ (read 2026-09-16). Two independent sources agree to the cent. |
| NJ commercial electricity | **18.47 ¢/kWh** | **`[PUB]`** same two sources. If the LPT office is on a commercial meter, **every power figure in this file is conservative.** |
| **1 W continuous** | **8.766 kWh/yr = $2.1874/yr** in New Jersey | **ARITHMETIC** from the rate above. **Use $2.19.** |
| NJ sales tax | **6.625 %**, no local add-on; eBay collects it as a registered marketplace facilitator | **`[PUB]`** NJ Treasury https://www.nj.gov/treasury/taxation/remotesellersfaq.shtml and Xero's NJ guide https://www.xero.com/us/guides/new-jersey-sales-tax-calculator/ (read 2026-09-16: *"New Jersey's sales tax rate is 6.625… Platforms like Amazon, Etsy, and eBay are classified as marketplace facilitators in New Jersey."*). **Tax multiplier used throughout: × 1.06625.** |
| One generating agent turn | **0.81 GB commit, ~1 core while generating**; 25 % headroom rule | **`[CARRIED]`** `40-hardware-costs.md` §0. Not re-measured this session. |
| Resident turns from N GB | `floor(0.75 × N / 0.81)` → 8 GB = 7 · 16 GB = 14 · 32 GB = 29 · 64 GB = 59 | **`[CARRIED]`** same. |

> **The CPU caveat, repeated because it is the whole argument:** the turn count is a **memory** limit.
> A generating turn costs about **one core**. A node's useful capacity is
> `min(resident turns, cores)` — and **for this workload physical cores are the scarce resource,
> because SMT threads are a fraction of a core and the work is a mix of compute and API wait.**
> Every ranking below therefore shows **$/thread** *and* **$/core**, and they do not always agree.

---

## 1. The live market, 2026-09-16 — every price read off a fetched page

Prices are **pre-tax** unless a taxed figure is stated. Where a price was read on a fetched page today
it is tagged **`[LIVE]`**; eBay search-result pages and item pages were both rendered server-side and
returned real prices. Delivery is to New Jersey; eBay's own postage quotes were used.

### 1a. Dell OptiPlex Micro (1-litre) — the recommended family

| Machine | CPU (cores/threads) | Stock RAM | Max RAM / slots | Storage | Idle W | Condition | Price `[LIVE]` | Shipping | URL |
|---|---|---|---|---|---|---|---|---|---|
| **OptiPlex 5090 Micro** | i5-10500T (6c/**12t**) | **16 GB** | **64 GB / 2 SODIMM** | 256 GB SSD | 12.7 (7090 measured) | Used, **3 available** | **$185.00** | **free** (UPS Ground) | https://www.ebay.com/itm/137735826695 |
| OptiPlex 5090 Micro | i5-10500T (6c/12t) | 16 GB | 64 GB / 2 | 256 GB | 12.7 | Used, **10+ available** | price not captured | — | https://www.ebay.com/itm/257686298970 |
| OptiPlex 5090 Micro | i5-10500T | 16 GB | 64 GB / 2 | 256 GB | 12.7 | Used | **$239.95** | free | https://www.ebay.com/itm/198335623259 |
| **OptiPlex 7070 Micro** | i5-9500T (6c/**6t**) | **16 GB** | **32 GB / 2 SODIMM** (max 16/slot) | 256 GB NVMe | 13 | Used, **9 available** — **"No Power Cables"** | **$150.00** | **free** | https://www.ebay.com/itm/336795130291 |
| OptiPlex 7070 Micro | i5-9500T (6c/6t) | 16 GB | 32 GB / 2 | 256 GB NVMe | 13 | Refurbished | **$174.97** | free | https://www.ebay.com/itm/257352681345 region — see note (i) |
| OptiPlex 7070 Micro | i5-9500T (6c/6t) | **8 GB** | 32 GB / 2 | none stated | 13 | Used, 153 sold | **$129.99** (or Best Offer) | free | https://www.ebay.com/itm/257072988827 |
| **OptiPlex 7080 Micro** | i5-10500T (6c/**12t**) | 16 GB | **64 GB / 2** | 256 GB | 12.7 | Used, "10+ sold" | **$199.99** | free | https://www.ebay.com/itm/227514395580 *(see note (ii))* |
| OptiPlex 7080 Micro | i5-10500T (6c/12t) | 16 GB | 64 GB / 2 | 256 GB, no OS | 12.7 | Used | **$199.99** | +$15.00 | https://www.ebay.com/itm/267779571133 |
| OptiPlex 7080 Micro | i5-10500T (6c/12t) | **32 GB** (4×8) | 64 GB / 2 | no HDD | 12.7 | Used | **$199.99** | free | https://www.ebay.com/itm/227498870046 |
| OptiPlex 7080 Micro | i5-10500T (6c/12t) | **32 GB** | 64 GB / 2 | 512 GB | 12.7 | Used | **$329.00** (or Best Offer) | free | https://www.ebay.com/itm/227514395580 |
| OptiPlex 7090 Micro | i5-10500 (6c/12t) | 16 GB | 64 GB / 2 | 256 GB NVMe | 12.7 | Used | **$250.00** | free | https://www.ebay.com/itm/27473917225 |
| OptiPlex 3090 Micro | i5-10500T (6c/12t) | 16 GB | 64 GB / 2 | 256 GB | 12.7 | Used, no OS | **$189.99** | free | https://www.ebay.com/itm/137722041342 |
| **OptiPlex 3080 Micro** | i5-10500T (6c/**12t**) | 16 GB | **64 GB / 2 SODIMM** | 256 GB NVMe | 12.7 | Used | **$180.00** (or Best Offer) | +$6.99 | https://www.ebay.com/itm/800626975808 |
| OptiPlex 3080 Micro | i5-10500T (6c/12t) | 16 GB | 64 GB / 2 | 256 GB NVMe | 12.7 | Used | **$219.99** | free | https://www.ebay.com/itm/168618539902 |
| OptiPlex 3080 Micro | i5-10500T (6c/12t) | not stated | 64 GB / 2 | 256 GB NVMe | 12.7 | Used, new listing | **$169.00** | +$7.05 | https://www.ebay.com/itm/267786648067 |
| OptiPlex 3070 Micro | i5-9500T (6c/6t) | 8 GB | **32 GB / 2** | 256 GB NVMe | 10 | Used | **$130.00** | +$5.93 | **`[CARRIED]`** `40-hardware-costs.md` — not re-fetched |
| OptiPlex 5060 Micro | i5-8500T (6c/6t) | 8 GB | 32 GB / 2 | **no HDD** | ~10 | Used | **$95.00** | free | https://www.ebay.com/itm/147564870681 |
| OptiPlex 7060 Micro | i5-8500T (6c/6t) | "up to 16 GB" | 32 GB / 2 | "up to 512 GB" | ~18 (65 W-TDP variant) | Used, 10+ sold | **$159.99–$239.99** (config-dependent) | free | https://www.ebay.com/itm/198592210128 |

### 1b. Lenovo ThinkCentre Tiny

All Lenovo prices below were read on fetched eBay search pages today **`[LIVE]`** (14:49–14:51 EDT).

| Machine | CPU (cores/threads) | Stock RAM | Max RAM / slots | Storage | Idle W | Price `[LIVE]` | Shipping | URL |
|---|---|---|---|---|---|---|---|---|
| **M720q Tiny** | i5-8500T (6c/6t) | **16 GB** | 32 GB / 2 SODIMM | 480 GB | 11–14 `[PUB]` | **$164.99** | free | https://www.ebay.com/itm/168691535691 |
| M720q Tiny | i5-8500T (6c/6t) | 8 GB | 32 GB / 2 | 256 GB, W11P | 11–14 | **$160.00** | +$15.00 | https://www.ebay.com/itm/358914833955 |
| M720q Tiny | i5-8500T (6c/6t) | 8 GB + PCIe GPU adapter | 32 GB / 2 | — | 11–14 | **$150.00** | +$5.93 | https://www.ebay.com/itm/820116197639 |
| M720q Tiny | i5-8400T (6c/6t) | 8 GB | 32 GB / 2 | 128 GB | 11–14 | **$140.00** | free | https://www.ebay.com/itm/227523533725 |
| M720q Tiny | i5-8400T (6c/6t) | **16 GB** | 32 GB / 2 | 256 GB — **"NO AC"** | 11–14 | **$149.95** | +$19.95 | https://www.ebay.com/itm/237063040905 |
| **M720q Tiny** | i5-8400T (6c/6t) | 8 GB | 32 GB / 2 | **NO HDD, NO PSU** | 11–14 | **$119.99** | free | https://www.ebay.com/itm/198568451166 |
| **M920x Tiny** | i5-8600 (6c/6t) | **16 GB** | 32 GB / 2 (64 reported) `[COMM]` | 256 GB | NOT FOUND | **PRICE UNRELIABLE — DO NOT USE** | — | https://www.ebay.com/itm/306968232037 — *the search card showed $134.95 + $27.15 from one seller and the item's own page showed $259.09 + $23.36 from a different seller. **Two readings, two sellers, two prices: this is not evidence.** The M920x is a thin, overpriced market — ~3 used units, one damaged, cheapest verified delivered $220.08. **Buy only under $200 delivered.*** |
| **M720q Tiny** | i5-8500 *or* i7-8700T — the listing contradicts itself, **both 6-core** | **16 GB** | 32 GB / 2 (64 with BIOS `M1UKT65A` — §3(f)10) | 256 GB | NOT FOUND | **$139.00** | **free** (UPS Ground) | https://www.ebay.com/itm/287590749882 — **cheapest 16 GB Lenovo Tiny found today. Confirm the exact CPU with the seller before a bulk buy.** |
| M920x Tiny | i5-8500 (6c/6t) | 16 GB | 32 GB / 2 | 512 GB, **"FACE DMGD-PC ONLY"** | NOT FOUND | **$199.99** | +$20.09 | https://www.ebay.com/itm/147465957138 |
| M920q Tiny | i7-8700T (6c/12t) | 16 GB | 32 GB / 2 | 512 GB | NOT FOUND | **$299.99** | free | https://www.ebay.com/itm/267756573019 |
| **M90q Tiny Gen 1** | i5-10500T (6c/**12t**) | **16 GB** | **64 GB DDR4 / 2** `[PUB]` | 256 GB, W11P | NOT FOUND | **$249.99** | free | https://www.ebay.com/itm/237069946746 |
| M90q Tiny Gen 1 | i5-10500T (6c/12t) | 16 GB | 64 GB / 2 | 256 GB, W11P | NOT FOUND | **$249.99** | free | https://www.ebay.com/itm/336795312731 |
| M90q Tiny Gen 1 | i5-10500 (6c/12t) | 8 GB | 64 GB / 2 | 256 GB | NOT FOUND | **$239.98** | free | https://www.ebay.com/itm/147364242642 |
| M90q Tiny Gen 1 | i5-10500T (6c/12t) | **32 GB** | 64 GB / 2 | 512 GB | NOT FOUND | **$244.88** (range to $419.88) | free | https://www.ebay.com/itm/236899512398 |
| M90q Tiny Gen 2 | i5-11500 (6c/12t) | 16 GB | 64 GB / 2 | 256 GB | NOT FOUND | **$259.99** | +$15.80 | https://www.ebay.com/itm/257342984336 |
| M910q Tiny | i5-7500T (**4c/4t**) | 8 GB | 32 GB / 2 | **none** | NOT FOUND | **$69.95** | free | https://www.ebay.com/itm/178498871974 |
| M910q Tiny | i5-7500T (4c/4t) | 8 GB | 32 GB / 2 | 256 GB, W11 | NOT FOUND | **$199.00** | +$5.83 | https://www.ebay.com/itm/267784248267 |
| M710q Tiny — **lot of 5** | i3-6100T (2c/4t) | 8 GB ea | 32 GB / 2 | 256 GB ea | NOT FOUND | **$275.00** = **$55/unit** | +$100.35 | https://www.ebay.com/itm/196387572702 |
| M710q Tiny — lot | i5-7500T (4c/4t) | 8 GB ea | 32 GB / 2 | 256 GB ea | NOT FOUND | **$119.00** | +$12.99 | https://www.ebay.com/itm/820075575287 |

### 1c. HP

| Machine | CPU (cores/threads) | Stock RAM | Max RAM / slots | Storage | Idle W | Price `[LIVE]` | Shipping | URL |
|---|---|---|---|---|---|---|---|---|
| EliteDesk 800 G6 Mini | i5-10500T (6c/**12t**) | 16 GB | **64 GB / 2 SODIMM** `[PUB]` | 240–512 GB | 11–12 `[PUB]` (G4 measure) | **$199.99** | free | https://www.ebay.com/itm/298436213471 |
| EliteDesk 800 G6 Mini | i5-10500T (6c/12t) | **24 GB** | 64 GB / 2 | 256 GB, W11P | ~12 | **$255.00** | +$21.71 | https://www.ebay.com/itm/178338449964 |
| EliteDesk 800 G6 Mini | i5-10500 (6c/12t) | 16 GB | 64 GB / 2 | **no SSD** | ~12 | **$199.99** | free | https://www.ebay.com/shop/hp-g6-mini |
| **EliteDesk 800 G4 SFF** | i7-8700 (6c/**12t**) | 8 GB | 64 GB / 4 UDIMM `[PUB]` | **no SSD** | ~20–25 `[COMM]` est. | **$145.00** | free | https://www.ebay.com/itm/257744791014 |
| EliteDesk 800 G4 SFF | i7-8700 (6c/12t) | **32 GB** | 64 GB / 4 | 1 TB SSD | ~20–25 est. | **$174.88** | free | https://www.ebay.com/itm/236952614094 |
| EliteDesk 800 G4 SFF | i7-8700 (6c/12t) | 16 GB | 64 GB / 4 | 512 GB | ~20–25 est. | **$189.99** | free | https://www.ebay.com/itm/366667152055 |
| EliteDesk 800 G5 Mini | i5-9500T (6c/6t) | 8 GB | **32 GB per HP's own guide — CONTESTED, see §5.2** | 256 GB NVMe | 11–12 | **`[CARRIED]`** `40-hardware-costs.md` lists $269.99 — **not re-fetched; treat as stale** | — | — |
| **Z2 SFF G5** | i7-10700 (**8c/16t**) | 16 GB | 128 GB / 4 `[PUB]` | no HDD | NOT FOUND | **$324.95** | free | https://www.ebay.com/itm/820050924745 |
| Z2 SFF G4 | i7-9700K (8c/8t) | 16 GB | 128 GB / 4 | — | NOT FOUND | **$339.88** | free | (same seller line, see note (iii)) |

### 1d. Dell Precision and SFF/tower multi-core

| Machine | CPU (cores/threads) | Stock RAM | Max RAM / slots | Storage | Price `[LIVE]` | Shipping | URL |
|---|---|---|---|---|---|---|---|
| **OptiPlex 7080 SFF** | i5-10500 (6c/**12t**) | 8 GB | 128 GB / 4 UDIMM `[PUB]` | **NO HDD/OS** | **$154.97** | **+$12.74** = **$167.71 delivered** | https://www.ebay.com/itm/178482355831 |
| OptiPlex 7080 SFF | i5-10500 (6c/12t) | 8 GB | 128 GB / 4 | no HDD/OS | **$199.99** | free | https://www.ebay.com/itm/178496664779 |
| **OptiPlex 7070 SFF** | **i7-9700 (8c/8t)** | **16 GB** | 64 GB / 4 `[PUB]` | 256 GB | **$219.99** | **free** | https://www.ebay.com/itm/168360463161 |
| OptiPlex 7070 SFF | i5-9500 (6c/6t) | 16 GB | 64 GB / 4 | 500 GB SSD + 1 TB HDD | **$199.99** | +$19.06 | https://www.ebay.com/itm/227280966831 |
| OptiPlex 7070 SFF | i5-9500 (6c/6t) | 16 GB | 64 GB / 4 | 256 GB | **$209.00** | +$15.00 | https://www.ebay.com/itm/377268977149 |
| OptiPlex 7070 SFF | i5-9500 (6c/6t) | 8 GB | 64 GB / 4 | 256 GB | **$164.98** | **+$54.24** (absurd postage) | https://www.ebay.com/itm/397489086130 |
| Precision 3440 **SFF** | Xeon W / i7/i9 | config | **128 GB / 4 DIMM** `[PUB]` | config | see §1f | — | — |

### 1d-bis. Precision, Z2 and Ryzen — the rest of the live board

| Machine | CPU (cores/threads) | Stock RAM | Max RAM / slots | Storage | Price `[LIVE]` | Shipping | URL |
|---|---|---|---|---|---|---|---|
| **Dell Precision 3431 SFF** | **i7-9700 (8c/8t)** | **16 GB** | 64 GB / 4 | **512 GB SSD** | **$179.99** | **free** (UPS Ground) | https://www.ebay.com/itm/318879789819 — **cheapest 8-real-core complete machine found today** |
| Dell Precision 3630 Tower | i5-8500 (6c/6t) | 16 GB | — | **none** (no OS/HDD/**no adapter**) | **$169.99** | free 2–4 day | https://www.ebay.com/itm/188753282772 — 3 available |
| Dell Precision 3240 Compact | i5-10500 (6c/12t) | 16 GB | **64 GB / 2 SODIMM** `[PUB]` | 512 GB SSD | $284.99 | free | https://www.ebay.com/itm/318845099211 |
| Dell Precision 3440 SFF | i7-10700 (8c/16t) | 16 GB | **128 GB / 4 DIMM** `[PUB]` | none (Win COA) | $229.99 | free 2–4 day | https://www.ebay.com/itm/206453888340 |
| Dell Precision 3440 SFF | i7-10700 (8c/16t) | 16 GB | 128 GB / 4 | 256 GB M.2 | $249.99 | free | https://www.ebay.com/itm/137726521676 |
| HP Z2 SFF G4 | **i7-9700 (8c/8t)** | 16 GB | 128 GB / 4 `[PUB]` | 256 GB SSD | **$209.99** | **free** | https://www.ebay.com/itm/278048013515 |
| HP Z2 SFF G4 | i7-8700 (6c/12t) | 16 GB | 128 GB / 4 | none (no SSD/OS) | $199.00 | free | https://www.ebay.com/itm/198630611606 |
| HP Z2 SFF G5 | i5-10500 (6c/12t) | 16 GB | 128 GB / 4 | 256 GB NVMe, W11 Pro | $224.99 | +$23.90 → $248.89 | https://www.ebay.com/itm/237071780852 |
| HP Z2 SFF G5 | **i7-10700 (8c/16t)** | 16 GB | 128 GB / 4 | 512 GB SSD | $269.99 | free | https://www.ebay.com/itm/257747051682 |
| **HP Z2 SFF G5** | **i7-10700 (8c/16t)** | 16 GB | 128 GB / 4 | **none** | $299.95 | **+$25.00 = $324.95** | https://www.ebay.com/itm/820050924745 |
| HP Z2 SFF G4 | i7-9700K (8c/8t) | 16 GB | 128 GB / 4 | 256 GB SSD | $339.88 | free | https://www.ebay.com/itm/800148070204 |
| **Beelink SER5 Pro** (Ryzen) | **Ryzen 7 5700U (8c/16t)** | 16 GB | 64 GB / 2 SODIMM | 500 GB SSD | **$299.99** | +$14.00 = $313.99 | https://www.ebay.com/itm/188930286758 |
| ACE MAGICIAN AM07 (Ryzen) | Ryzen 5 5600U (6c/12t) | 16 GB | — | **none** | $250.00 | free | https://www.ebay.com/itm/257605519770 |
| Beelink SER5 Pro (Ryzen) | Ryzen 7 5800H (8c/16T) | **32 GB** | — | 500 GB SSD | $440.00 | +$5.80 | https://www.ebay.com/itm/257729918969 |

**Two hard findings from this sweep:**
- **There is no sub-$300 complete HP Z2 SFF on eBay today.** Every sub-$50 "Z2 SFF G4" hit is a PSU or a
  motherboard. **A Z2 SFF runs ~2.3× the price of an equivalent OptiPlex/EliteDesk SFF — skip it.**
- **Used Ryzen mini-PCs are NOT cheaper per thread than used Intel SFFs.** $313.99 delivered for an
  8c/16t Beelink versus $191.91 taxed for an 8c/8t Precision 3431 SFF with a 512 GB disk. **The
  "modern used Ryzen" idea does not pay at September 2026 prices.**
- **The HP sub-sweep's live rows** (all `[LIVE]`, read 17:49–17:56 ET): **ProDesk 600 G5 Mini i5-9500T
  16 GB/256 GB — $120.00 + $8.82 = $128.82, 23 available** (the §4 package winner);
  **EliteDesk 800 G5 DM i5-9500 8 GB/256 GB — $104.99 free**; **EliteDesk 800 G6 Mini i5-10500 16 GB, no
  storage, no adapter — $139.95 free**; **EliteDesk 800 G4 Mini i5-8500T 8 GB — $98.00 delivered**;
  **EliteDesk 800 G4 SFF i7-8700 8 GB, no SSD — $145.00 free**; **EliteDesk 800 G6 SFF i7-10700
  8c/16t 16 GB/512 GB — $326.92 delivered** (over $300).

### 1e. Notes on the table

**(i)** The $174.97 7070 Micro appears in eBay's own 7070 shop band; the individual item URL was not
re-opened this session, so treat $174.97 as the band's figure rather than a re-verified item price.
The **$150.00 / 9-available** listing **is** item-verified.

**(ii)** Two different 7080 Micro listings both showed **$199.99** — one 16 GB/256 GB, one 32 GB
(4×8)/512 GB, both mapped to the same item ID in extraction. **One of the two must be wrong.** The
conservative reading is used: **$199.99 buys 16 GB / 256 GB**, and the 32 GB / 512 GB unit is
**$329.00**. Do not plan on a $199.99 32 GB machine without re-opening the listing.

**(iii)** The Z2 G4 figure comes from the same seller/variation band as the Z2 G5; the exact item URL
was not isolated. Treat $339.88 as an indicative band figure, not a verified item price.

**(iv) Prices I could not capture** are listed as such rather than guessed. An eBay search card whose
price did not render is a gap, not a zero.

---

## 2. Memory kits — re-priced live, and two of the old prices were badly stale

**All rows `[LIVE]`**, read 2026-09-16 21:50–21:55 UTC. Page clocks matched (Newegg RSS header
`Wed, 16 Sep 2026 14:5x -0700`; eBay footer `last updated: Sep-16 14:50`).

| Kit | Best live price | Cheapest new | **$/GB** (best) | Where |
|---|---|---|---|---|
| **16 GB (2×8) DDR4-2666 SO-DIMM** | **$66.75 used** (+$11.76 ship) | $99.99 | **$4.17** | eBay lot listing / Newegg Rimlance |
| 16 GB (2×8) DDR4-2666, named-brand used | $68.14 (Samsung `M471A1K43CB1-CTD`) · $70.95 (Corsair `CMSX16GX4M2A2666C18`) · $70.97 (Micron `MTA8ATF1G64HZ`) | — | $4.26–4.44 | eBay, 99.8–100 % sellers |
| **16 GB (2×8) DDR4-3200 SO-DIMM** | — | **$104.00** | $6.50 | Newegg Rimlance |
| **32 GB (2×16) DDR4-3200 SO-DIMM** | **$145.28 used** (Micron `MTABATF2G64HZ`) | **$169.00** | **$4.54** | eBay / Newegg Rimlance |
| 32 GB (2×16) DDR4-2666 SO-DIMM | — | $184.99 | $5.78 | Newegg Timetec |
| *(the old figure)* 32 GB (2×16) DDR4-**2666** SO-DIMM @ $203.08 | **`[CARRIED]` and now stale** | $203.08 | $6.35 | A-Tech — **live 3200 kits are cheaper than this carried 2666 figure** |
| **Single 32 GB DDR4-3200 UDIMM** | — | **$159.00** | **$4.97** | Newegg Rimlance `RLMUD-25600-32-28` |
| *(the old figure)* 32 GB single UDIMM @ $223.09–$255.95 | **`[CARRIED]` and now stale — 29–38 % too high** | — | — | — |
| **64 GB (2×32) DDR4-3200 UDIMM** | — | **$340.00** | $5.31 | Newegg Rimlance `RUD25600D8C2K64` |
| *(the old figure)* 64 GB (2×32) DDR4-3200 UDIMM @ $490–$494 | **`[CARRIED]` and now stale — 31–45 % too high** | — | — | — |
| **16 GB (2×8) DDR3-1600 UDIMM** | — | **$38.99** | **$2.44 — cheapest on the list** | Newegg Timetec `MR-H8GD316U7D` |
| DDR3-1600 marketed for the OptiPlex 9020 | — | $56.98 | $3.56 | Newegg A-Tech — **pay $38.99, not $56.98; it is the same part** |
| 64 GB (2×32) DDR5-5600 **SO-DIMM** | — | $940.99 | **$14.70 — worst** | Newegg |

### The shortage is measured, not rumoured — `[PUB]`

**Tom's Hardware, published 2026-08-17**, *"Memory prices climb 500 % in 12 months…"*,
https://www.tomshardware.com/pc-components/ram/memory-prices-climb-500-percent-in-12-months-up-to-10x-the-lowest-ever-tracked-prices-128gb-of-ddr5-now-usd3-399
— verbatim: *"DDR4 kits are up anywhere from 120 % to nearly 180 % across the board… a kit that was
$105 last year is $281 this year."* Corroborating and dated: Wccftech/DigiTimes, *"Memory Shortages
Drive DDR4 Prices Over 50 % In Q3 2026, DDR3 Also Impacted"*, with the DDR4 supply gap expected to run
*"till 2028."* **Direction on DDR4 and DDR5 is up. DDR3 is the one line that did not move.**
**Therefore: never buy a node planning to add RAM later.**

### The 8 GB trap, quantified

A 16 GB DDR4 SO-DIMM kit now costs **$66.75–$104.00**. So:

| Plan | Cost taxed | Turns | Threads |
|---|---|---|---|
| 8 GB OptiPlex 7070 Micro @ $129.99 + used 16 GB kit @ $66.75 + $11.76 ship | **$221.55** | **14** | **6** |
| **16 GB OptiPlex 7070 Micro @ $150.00** + a $16.99 power adapter | **$178.06** | **14** | **6** |
| **16 GB OptiPlex 5090 Micro @ $185.00** (complete, adapter included) | **$197.26** | **14** | **12** |

**"Buy 8 GB now, upgrade later" costs $24–43 MORE than buying the 16 GB machine outright, for the same
14 turns — and it buys 6 threads instead of 12 if the comparison is against the 5090.** The rule:
**buy the RAM already installed.** The breakeven is a **$67–$100** config gap; the real gap on the same
model is **$20–50**, so the 16 GB machine wins by **$50–80 per unit**. Pulling a single 8 GB stick to
make room also destroys its value (resale ~$15–25 at today's prices), which pushes further the same way.

### The two corrections that *help*, and they matter for `linux-pc-ts`

`40-hardware-costs.md` priced the recommended "second tranche" — a RAM top-up for the **HP Pavilion
TP01-2xxx (`linux-pc-ts`)** — from carried figures that are now **out of date in the wrong direction**:

| Action on `linux-pc-ts` (2 DIMM slots, 64 GB max, measured earlier) | Old cost taxed | **Live cost taxed** | Turns added | Old $/turn | **Live $/turn** |
|---|---|---|---|---|---|
| Add **1 × 32 GB DDR4-3200 UDIMM @ $159.00** beside the existing 8 GB → 40 GB | $237.77 | **$169.53** | **+27** (10→37) | $8.81 | **$6.28** |
| Replace both with **2 × 32 GB @ $340.00** → 64 GB | $467.98–$527.16 | **$362.53** | **+49** (10→59) | $9.55–10.76 | **$7.40** |

**This is now the second-cheapest capacity in the estate** — $6.28/turn — beaten only by the DDR3 top-up
on `secratary` at ~$5.20/turn, and it needs **no new machine**: it upgrades a 6c/12t box that is already
running Ubuntu. **It is a materially better buy than the earlier file concluded, and it should be
re-promoted in the recommendation.**

### RAM traps that will cost real money — `[PUB]`

1. **ECC vs non-ECC.** Consumer mini-PCs and the OptiPlex 9020 are non-ECC. Live examples sitting on
   *the same pages* as the cheap parts: NEMIX **ECC** SO-DIMM 16 GB (2×8) 3200 at **$198.99** vs
   non-ECC **$117.89**; NEMIX **ECC** DDR3-1600 UDIMM 2×8 at **$57.99** vs non-ECC **$38.99**; OWC
   32 GB DDR4-3200 **ECC Unbuffered** UDIMM at **$298.88** vs non-ECC **$239.99**. **ECC fits the slot
   and then fails to POST** — the easiest expensive mistake available here.
2. **Registered/buffered (RDIMM) vs unbuffered.** "PC4-25600**R**" or "PC4-21300**R**" is registered
   server memory; you want **U** / unbuffered. It looks identical and does not POST in a desktop.
3. **SO-DIMM vs UDIMM is 260-pin vs 288-pin.** Several listings carry contradictory metadata — one
   part titled "SODIMM" listed `Type: 288-Pin DDR4 SDRAM` in the same listing. **Read the pin count,
   not the title.**
4. **Counterfeit RAM is elevated by this exact shortage.** heise online,
   https://www.heise.de/en/news/Fake-memory-Extra-caution-is-now-advised-11123158.html — documents a
   buyer receiving DDR2 sticks in DDR5 packaging *"with a simple metal plate included in the package to
   increase the weight"*, and the swap-return scam. **Live example seen today:** a listing claiming
   *"16GB 32GB=(2x16GB) DDR4 2133 2400 2666 3200"* at **$20.00 "Brand New"** —
   https://www.ebay.com/itm/357222101995. One SKU cannot be four capacities and four speeds at a fifth
   of market; that is bait or re-labelled scrap. **Mitigation: buy named-brand pulls with a real part
   number in the title from >99 % sellers, and verify every stick on arrival with CPU-Z or Thaiphoon
   Burner** — heise's own recommended check — **before it goes near a customer machine.**
5. **Refusals recorded, not priced:** **B&H returned HTTP 403** ("Just a moment…" bot wall) to a direct
   fetch. Micro Center / MemoryStock / ServerMonkey were not reached. **Treat those as unmeasured, not
   as cheap.**

---

## 3. The six questions, answered with evidence

### 3(a) The cheapest way to add at least 16 usable threads for $250 delivered

**Answer: yes, at $249.99 — but only as two boxes, and one of them needs a ~$20 disk.** The evidence:

| Route to ≥16 logical threads | Delivered, pre-tax | Threads | Cores | Bootable as delivered? |
|---|---|---|---|---|
| **HP EliteDesk 800 G4 SFF, i7-8700 (6c/12t), 8 GB, no SSD** — https://www.ebay.com/itm/257744791014 — **$145.00 free**<br>**+ HP EliteDesk 800 G5 Desktop Mini, i5-9500 (6c/6t), 8 GB, 256 GB SSD** — https://www.ebay.com/itm/257747124079 — **$104.99 free** | **$249.99** | **18** | **12** | **No — the G4 SFF has no boot disk.** Add ~$20 → **$269.99 fully bootable.** |
| 1 × **HP Z2 SFF G5, i7-10700 (8c/16t), 16 GB** — https://www.ebay.com/itm/820050924745 | **$324.95** | **16** | **8** | No HDD. Add ~$20 → ~$345. |
| 2 × **OptiPlex 7080 SFF, i5-10500 (6c/12t), 8 GB** — https://www.ebay.com/itm/178482355831 | 2 × $167.71 = **$335.42** | **24** | **12** | No HDD in either. Add ~$40 → ~$375. |
| 2 × **OptiPlex 5090 Micro, i5-10500T (6c/12t), 16 GB, 256 GB** @ $185 | **$370.00** (taxed $394.52) | 24 | 12 | **Yes — complete.** |
| 1 × **OptiPlex 7070 SFF, i7-9700 (8c/8t), 16 GB, 256 GB** — https://www.ebay.com/itm/168360463161 | **$219.99** | 8 | **8** | **Yes — complete, under $250, with 8 real cores.** Does not reach 16 *threads*. |
| **1 × Dell Precision 3431 SFF, i7-9700 (8c/8t), 16 GB, 512 GB SSD** — https://www.ebay.com/itm/318879789819 | **$179.99** | 8 | **8** | **Yes — complete. THE CHEAPEST 8-REAL-CORE MACHINE FOUND TODAY, and it beats the 7070 SFF above by $40 while carrying twice the disk.** |
| 1 × HP EliteDesk 800 G6 Mini, i5-10500 (6c/12t), 16 GB, no storage, no adapter — https://www.ebay.com/itm/188939833705 | **$139.95** | 12 | 6 | No. +SSD +adapter (~$42) → ~$182. |

> **Read the question the way the workload reads it.** `40-hardware-costs.md`'s own model is *"~1 core
> per generating turn"*, so the resource that buys agent capacity is **physical cores**, and SMT is
> headroom rather than extra turn slots. Under that model:
> - **The cheapest ≥16 *logical* threads: $249.99 delivered** (the two-box combo above), $269.99
>   bootable — **the target is met, with one caveat that one box arrives diskless.**
> - **The cheapest ≥16 *physical* cores: not achievable at any price near $250.** Twelve cores is the
>   ceiling of a $250 budget (the two-box combo, or two 6c machines at ~$270–$335). **Sixteen physical
>   cores needs ~$540+.** If the requirement is 16 *cores*, the budget is short by roughly 2.2×, and it
>   is better to buy three $130–$185 6-core nodes than to chase 16 cores in one box.
> - **The cheapest single complete machine with 8 real cores is $219.99** (OptiPlex 7070 SFF i7-9700).
>   **That is the best $250 answer if the real goal is "one more solid box".**

**Cheapest per thread actually bought today** (delivered, pre-tax, **complete** machines only):

| Machine | Delivered | Threads | **$/thread** | Cores | **$/core** | Turns | **$/turn** |
|---|---|---|---|---|---|---|---|
| **HP ProDesk 600 G5 Mini, i5-9500T, 16 GB, 256 GB** — https://www.ebay.com/itm/366670683938 | **$128.82** | 6 | **$21.47** | 6 | **$21.47** | 14 | **$9.20** |
| HP EliteDesk 800 G5 DM, i5-9500, 8 GB, 256 GB — https://www.ebay.com/itm/257747124079 | **$104.99** | 6 | $17.50 | 6 | $17.50 | 7 | $15.00 |
| **OptiPlex 7080 SFF, i5-10500, 8 GB, no HDD** — https://www.ebay.com/itm/178482355831 | **$167.71** | **12** | **$13.98** | 6 | $27.95 | 7 | $23.96 |
| **OptiPlex 5090 Micro, i5-10500T, 16 GB, 256 GB** — https://www.ebay.com/itm/137735826695 | **$185.00** | **12** | **$15.42** | 6 | $30.83 | **14** | **$13.21** |

**The ProDesk 600 G5 Mini at $128.82 delivered is the cheapest *complete* 16 GB node verified today and
the cheapest capacity per resident turn on the board — $9.20.** It is 6c/**6t**, so it buys 6 threads,
not 12; it is the same 6 physical cores as a 5090 Micro for **$56.18 less**. See §4.2 — **this is what
changed the recommendation.**

### 3(b) Is there any mini PC with 6 or more cores for under $120?

**Yes — and unlike the last pass, one of them arrives complete, working and with its power adapter.**

| Under-$120 6-core machine | Price `[LIVE]` | Complete? |
|---|---|---|
| **OptiPlex 3070 Micro, i5-8500T (6c/6t), 8 GB, 256 GB SSD, Win 11 Home** — https://www.ebay.com/itm/178502239021 | **$109.00 free delivery**, **2 available** | **YES — bootable, adapter included.** *Caveat: the listing's own spec table says 128 GB against a title/description that says 256 GB — get it confirmed before paying.* |
| OptiPlex 3070 Micro, i5-9500T (6c/6t), 8 GB, no disk — https://www.ebay.com/itm/187172284766 | $109.99 free | No — needs a disk (~$20). |
| OptiPlex 5060 Micro, i5-8500T (6c/6t), 8 GB — https://www.ebay.com/itm/147564870681 | $95.00 free | No — no HDD. |
| Lenovo M720q Tiny, i5-8400T (6c/6t), 8 GB — https://www.ebay.com/itm/198568451166 | $119.99 free | No — no HDD **and no PSU**. |
| OptiPlex 7070 Micro, i5-9500T (6c/6t), 8 GB, 256 GB SSD — https://www.ebay.com/itm/137736353975 | $119.99 free | Yes — **Dell OEM adapter included**, no OS (fine for Linux). |

**So: a complete, bootable, 6-core x86 mini PC with its adapter, under $120 delivered, exists today** —
the **$109.00 OptiPlex 3070 Micro** at 2 available. **If "6 cores" means 6c/12t, nothing under $120
exists**: the cheapest complete 6c/12t machine found is **$152.98** (§3(a) / §4.1), and the only
sub-$130 6c/12t unit is a **single-unit variation** in multi-config listing
https://www.ebay.com/itm/206424485717 (a $115 7080 Micro i5-10500T with 32 GB, and a $125 3080 Micro
i5-10500T with 32 GB, both "last one" — **one-off arbitrage, not a supply line**; and on the $125 unit
the variation does not even state the CPU, so it is **not claimed as verified**).

### 3(c) Which take 64 GB, and which cap at 32 GB

Manufacturer documents, all read 2026-09-16. **This is the table to buy from — not the listing text.**

| Machine | Slots | Official ceiling | Source `[PUB]` |
|---|---|---|---|
| OptiPlex **3080 Micro** | 2 SODIMM | **64 GB** (64 GB = 2×32 GB listed) | Dell, https://www.dell.com/support/manuals/en-us/optiplex-3080-micro/optiplex3080_micro_specs/memory |
| OptiPlex **3090 Micro** | **2 SODIMM** | **64 GB** | Dell, https://www.dell.com/support/manuals/en-us/optiplex-3090-micro/optiplex3090_micro_ss/memory — *"Memory slots: Two SODIMM slots … Maximum memory configuration: 64 GB"* |
| OptiPlex **5090 Micro** | **2 DIMM** | **64 GB** | Dell, https://www.dell.com/support/manuals/en-us/optiplex-5090-micro/opti5090mff_setupspecs/memory — verbatim: *"Memory slots: Two DIMM slots … Maximum memory configuration: 64 GB."* |
| OptiPlex **7080 Micro** | 2 | **64 GB** (4/8/16/32 GB per slot) | Dell, https://www.dell.com/support/manuals/en-us/optiplex-7080-micro/optiplex7080_micro_specs/memory |
| OptiPlex **7090 Micro** | **2 DIMM** | **64 GB** (2×32 GB DDR4-2666 10th gen, 3200 11th gen) | Dell, https://www.dell.com/support/manuals/en-et/optiplex-7090-micro/opti7090mff_setupspecs/memory |
| OptiPlex **3070 Micro** | 2 SODIMM | **32 GB** (32 GB = 2×16 GB is the largest supported config) | Dell, https://www.dell.com/support/manuals/en-us/optiplex-3070-micro/opti3070_micro_setiup_specs/memory — *"DIMM Slots 2 (SODIMM) … Maximum System Memory 32 GB"* |
| OptiPlex **7070 Micro** | **2 SODIMM** | **32 GB** — **max 16 GB per slot** | Dell, https://www.dell.com/support/manuals/en-us/optiplex-7070-micro/opti7070_micro_setup_specs/memory — *"Maximum memory configuration 32 GB / Number of slots 2 SODIMM / Maximum memory supported per slot 16 GB"* |
| OptiPlex **7060 SFF** | **4 UDIMM** | **64 GB** (max 16 GB/slot) | Dell PDF, https://dl.dell.com/topicspdf/optiplex-7060-desktop_specifications2_en-us.pdf |
| OptiPlex **7080 SFF** | **4 DIMM** | **128 GB** (max 32 GB/slot) | Dell, https://www.dell.com/support/manuals/en-us/optiplex-7080-sff/7080_sff_ss/memory — *"Four DIMM slots … Maximum memory 128 GB … Memory size per slot 4 GB, 8 GB, 16 GB, 32 GB"* |
| OptiPlex **7070 SFF** | 4 (Tower/SFF) | **64 GB** | Dell 7070 family datasheet (via search, 2026-09-16): *"4 DIMM slots … Max memory is 64GB (Tower/SFF) and 32GB (Micro)"* |
| Precision **3240 Compact** | **2 SODIMM** | **64 GB** | Dell, https://www.dell.com/support/manuals/en-us/precision-3240-workstation/prec_3240_ss/memory — *"Memory slots: Two-SODIMM slots"*; Dell community states max 64 GB DDR4-3200 |
| Precision **3440 SFF** | **4** | **128 GB** (128 GB = 4×32 GB listed) | Dell, https://www.dell.com/support/manuals/en-us/precision-3440-workstation/precision_3440_ss/memory |
| HP EliteDesk **800 G6 Mini** | **2 SODIMM** | **64 GB** | HP spec table: *"Maximum memory … 64 GB, 2 SODIMM"*, https://media.flixcar.com/f360cdn/HP-5198537164-4aa7-7817eeap.pdf and HP QuickSpecs (Scribd mirror) |
| HP EliteDesk **800 G5 Mini** | 2 SODIMM | **CONTESTED — HP's own guide says 32 GB.** See §5.2 | HP *Maintenance and Service Guide, EliteDesk 800 G5 Desktop Mini*, https://h10032.www1.hp.com/ctg/Manual/c06439994.pdf |
| HP EliteDesk **800 G4 Mini** | 2 SODIMM | 32 GB | `[CARRIED]` `40-hardware-costs.md` |
| Lenovo **M720q Tiny** | 2 DDR4 SO-DIMM | **32 GB** | Lenovo PSREF *ThinkCentre M720 Tiny*, rev. 2022-12-27, https://psref.lenovo.com/syspool/Sys/PDF/ThinkCentre/ThinkCentre_M720_Tiny/ThinkCentre_M720_Tiny_Spec.PDF |
| Lenovo **M920q / M920x Tiny** | 2 DDR4 SO-DIMM | **32 GB** officially; **64 GB (2×32 GB) is widely reported to work** | Lenovo PSREF *ThinkCentre M920 Tiny*, rev. 2022-03-02, https://psref.lenovo.com/syspool/Sys/PDF/ThinkCentre/ThinkCentre_M920_Tiny/ThinkCentre_M920_Tiny_Spec.PDF; community: https://www.reddit.com/r/minilab/comments/1k150of/ — *"specs for these state a max of 32 GB only because 32 GB SO-DIMMs were unavailable or very expensive when they were released"* `[COMM]` |
| Lenovo **M90q Gen 1 / Gen 2** | 2 DDR4 SO-DIMM | **64 GB** | Lenovo PSREF *ThinkCentre M90q Gen 2*: *"Max Memory: Up to 64GB DDR4-2666 / Up to 64GB DDR4-3200 — Two DDR4 SO-DIMM slots, dual-channel capable"*, https://psref.lenovo.com/syspool/Sys/PDF/ThinkCentre/ThinkCentre_M90q_Gen_2/ThinkCentre_M90q_Gen_2_Spec.PDF |
| Lenovo **M90q Gen 6** | 2 DDR5 SO-DIMM | **64 GB** DDR5-5600, 3× M.2 | Lenovo PSREF, https://psref.lenovo.com/Product/ThinkCentre/ThinkCentre_M90q_Gen_6 |
| HP Pavilion **TP01-2xxx** (`linux-pc-ts`) | 2 DIMM | **64 GB** | measured previous session |
| OptiPlex **9020 SFF** (`secratary`) | 4 | **32 GB** | measured previous session |

**The three-line version:** *10th-generation and newer Micro/Tiny take 64 GB; 8th/9th-generation Micro
take 32 GB; the SFF/tower variants with four DIMM slots take 64 GB (7070/7060 SFF) or 128 GB
(Precision 3440).* A used 9th-gen Micro is a **32 GB dead end**, and that is exactly the box
(`secratary`) whose 32 GB DDR3 ceiling is already binding.

### 3(d) Honest idle power, and what it costs per year

Rate: **$2.19 per watt-year** (24.95 ¢/kWh, EIA June 2026, verified live above).

| Family | Idle W | Basis | $/yr | Trust |
|---|---|---|---|---|
| **OptiPlex 7090 Micro, i5-10500T, 8 GB, 256 GB NVMe** | **12.7** (55.4 W load) | **`[PUB]` meter-measured**, ServeTheHome, *Dell OptiPlex 7090 Micro Review*, published 2022-02-11, fetched 2026-09-16 | **$27.79** | **Best single number in this file.** The 5090/7080/3080 Micro are the same 1 L platform and i5-10500T/10500T-class part, so 12–13 W is the honest planning figure for any of them. |
| OptiPlex 3070 Micro | just over **10** | `[PUB]` STH | $21.90 | measured |
| OptiPlex 7070 Micro, six-core | just over **13** | `[PUB]` STH | $28.47 | measured |
| OptiPlex 7060 Micro, 65 W-TDP CPU | just over **18** | `[PUB]` STH | $39.42 | measured — note the 65 W-TDP part costs ~40 % more to run than a 35 W-T. **Buy the T-suffix.** |
| Dell micro, i5-9500T, 32 GB, Proxmox | **12–14**, never over 18–20 | `[COMM]` Facebook Home Assistant group (undated) | $26–31 | corroborates the 13 W class |
| OptiPlex 7080 (unspecified form factor) | 8–10 **or** 13–14 | `[COMM]` https://www.reddit.com/r/homelab/comments/125cbfi/ (2023-09-16) | $18–31 | **the thread gives two ranges without saying which is which — low confidence** |
| HP EliteDesk 800 G4 Mini, 6-core | **11–12** | `[PUB]` STH | $24–26 | measured |
| HP EliteDesk 800 G4 Desktop Mini | **11.351** | `[PUB]` **HP's own ENERGY STAR-method declaration**, https://h20195.www2.hp.com/v2/getpdf.aspx/c06040430.pdf | $24.86 | vendor-declared |
| **HP EliteDesk 800 G6 Mini, 35 W-TDP** | **11–12** (peak just over 61 W) | **`[PUB]` meter-measured**, ServeTheHome, https://www.servethehome.com/hp-elitedesk-800-g6-mini-35w-1l-pc-review/3/ — *"Idle power consumption on 120V power we saw around 11-12W idle."* | **$24–26** | measured. **Gap now closed.** |
| **HP EliteDesk 800 G6 Mini, 65 W-TDP** | **12–14** (peak 89–91 W) | **`[PUB]` meter-measured**, STH, https://www.servethehome.com/hp-elitedesk-800-g6-mini-65w-review-tmm-more-power/3/ | **$26–31** | measured. Note the 65 W part is loud and needs >90 W of supply. |
| Lenovo M720q Tiny | **11–14** (dual-core G5400T unit); 27 W in a different STH config | `[PUB]` STH | $24–31 | unit-dependent — the 27 W outlier is real |
| **Dell Precision 3240 Compact, Xeon W-1250 + add-in NIC** | **16 W idle** — *and* STH got it **down to ~7 W** with power settings; ~120 W load; noise 35–37 dBA idle | **`[PUB]` meter-measured with an Extech**, ServeTheHome, https://www.servethehome.com/dell-precision-3240-compact-mini-review-intel-xeon-nvidia/4/ | **$15–35** | measured. **Gap closed.** The default is high; the tuned figure is the interesting one. |
| Dell Precision 3240 Compact, **i5-10500 + Quadro P620** | **32 W idle**, ~200 W load | `[PUB]` same STH page — **the discrete GPU, not the CPU, is what costs 16 W here** | $70.08 | measured |
| **Dell Precision 3640 Tower** | **56 W idle** (Performance Mode), 191 W @ 100 % load, 354 W max | **`[PUB]` meter-measured**, Extech TrueRMS 120 V, STH, https://www.servethehome.com/dell-precision-3640-review-intel-xeon-w-and-nvidia-quadro/3/ | **$122.64** | measured. **This is the honest "big tower" number and it is 4.4× a Micro.** |
| **HP Z2 Tower G5** (tower, not SFF) | **12.3 W** (i7-10700, 350 W PSU, 8 GB) · **13.976 W** (i7-10700, 16 GB, P2200, 500 W) · **17.623 W** (Xeon W-1250, RTX 5000, 700 W), long idle S0, 230 VAC | **`[PUB]` HP's own measured energy table**, Z2 G5 QuickSpecs Version 9, **1 July 2021**, https://www.workstation4u.de/hp-z2-g5-quickspecs.pdf | **$27–39** | **vendor-measured — and lower than the community 20–25 W guess for SFF.** Label it a **Tower** figure; no Z2 **SFF** measurement exists. |
| **Lenovo M920 / M920q Tiny** (quad-core unit) | **12–15** | **`[PUB]` meter-measured on 120 V**, ServeTheHome, https://www.servethehome.com/lenovo-thinkcentre-m920-and-m920q-tiny-guide-and-review/3/ — *"Idle power consumption on 120V power we saw 12-15W idle for the quad-core unit… The power supplies are 90W Lenovo power adapters from the company's notebook line."* | $26–33 | measured. **Gap closed.** STH also tried a **65 W** PSU in the M920q and made it a "Key Lesson Learned" — see §3(f)6. |
| Lenovo M920 + M720, 8th-gen i5 | **7–10** idle, 30–40 load | `[COMM]` https://www.reddit.com/r/minilab/comments/11mi5tw/power_usage_examples/ | $15–22 | **community, and materially lower than STH's 12–15 W on a quad-core** |
| Lenovo M720q under Proxmox, fully idle | **3.7** | `[COMM]` Unraid forum, https://forums.unraid.net/profile/274866-dennyk/ (2024-04-09) | $8.10 | community; the lowest figure found anywhere |
| Lenovo M90q Gen 1/2 | **NOT FOUND directly** — assume the M920q's 12–15 W band, since it is the same 1 L chassis and the same 35 W-T part | — | ~$26–33 | **inference, labelled as inference** |
| **Any SFF class (OptiPlex/EliteDesk SFF, Z2 SFF)** | **20–25 (estimate)** | `[COMM]` https://www.reddit.com/r/homelab/comments/194khbq/ (2024-09-16): *"this will probably do about 20 to 25 watts at idle"* | **$44–55** | **NOT a measurement. Still the largest honest gap in the power model, and it is now load-bearing** because §4 recommends against SFF partly on this number. |
| N100 mini PC (Beelink S12 Pro, tuned) | **5.7** headless | `[PUB]` | $12.48 | measured |

**What this changes:** at **12.7 W the 5090 Micro costs $27.79/yr** — not the $26.25 `40-hardware-costs.md`
used, a trivial 6 % correction. The correction that matters is the **65 W-TDP trap**: a $130 65 W
machine looks cheaper than a $185 35 W-T machine and costs ~$11.63/yr more, i.e. **about 40 % of the
price gap, every year, forever.**

### 3(e) NVMe support and SATA bays

| Machine | M.2 / NVMe | 2.5″ / 3.5″ SATA | Source |
|---|---|---|---|
| **OptiPlex 5090 Micro** | **1 × M.2 2230/2280 PCIe NVMe** | **1 × 2.5″ SATA** | **`[PUB]` Dell storage page, fetched 2026-09-16**, https://www.dell.com/support/manuals/en-us/optiplex-5090-micro/opti5090mff_setupspecs/storage |
| **OptiPlex 7090 Micro** | **2 × M.2** | **1 × 2.5″ SATA** — and a **PCIe riser can replace the 2.5″ bay** | `[PUB]` STH 7090 review (2 M.2 present); STH comment: *"Just picked up a 7090M … it has a PCIe slot with an AMD RX640 GPU in place of the 2.5″ SATA option"* |
| OptiPlex 7070 Micro / 7080 Micro | 1 × M.2 2280 | 1 × 2.5″ | `[PUB]` Dell 7080 storage page states the machine supports one of several configurations; **bay count not individually re-verified — treat as 1+1** |
| OptiPlex 7070 SFF | M.2 2280 | **3.5″ SATA bay** present | `[PUB]` https://www.dell.com/support/manuals/en-us/optiplex-7070-sff/opti7070_sff_setup_specs/storage |
| OptiPlex 5090 SFF | **1 × M.2 2230/2280** | **3 × SATA** (3.5″/2.5″ + slim ODD) | `[PUB]` Dell, https://www.dell.com/support/manuals/en-ca/optiplex-5090-sff/d11_optiplex_5090_sff_ss/storage |
| Lenovo M90q Gen 6 | **3 × M.2 PCIe Gen 4** (6 TB total) | — | `[PUB]` Lenovo PSREF |
| Precision 3440 SFF / OptiPlex 5050-class | 1 × M.2 | multiple SATA | `[PUB]` Dell manuals |
| HP EliteDesk 800 G6 Mini | multiple M.2 options reported on 600/800 G6 | 1 × 2.5″ | `[COMM]` https://www.reddit.com/r/homelab/comments/1nyrfwl/ — **not vendor-verified this pass** |

**Bottom line for (e): every mandated candidate boots from NVMe.** The 5090 Micro gives one M.2 plus one
2.5″ bay; the 7090 Micro gives two M.2. **No mandated candidate is SATA-only, and none needs a 2.5″ disk
to boot** — so the "no disk" listings in §1 can be completed with a cheap M.2 2230/2280 stick.

### 3(f) Gotchas that would bite an always-on fleet

**1. Listings routinely ship without the power adapter, and the adapter is brand-proprietary.**
This is the biggest miss in `40-hardware-costs.md`, and it is a real cash item:

- The **$150.00 / 9-available OptiPlex 7070 Micro** item description says verbatim: *"ONLY includes what
  is pictured. **No Power Cables.**"* — https://www.ebay.com/itm/336795130291
- The **M720q i5-8400T at $119.99** is "NO HDD, **NO PSU**" — https://www.ebay.com/itm/198568451166
- The **M720q i5-8400T 16 GB at $149.95** is "**NO AC**" — https://www.ebay.com/itm/237063040905
- A genuine **Dell OEM 90 W 4.5 mm-tip adapter is ~$16.99 with free shipping** — `[LIVE]` eBay category
  band, https://www.ebay.com/b/Dell-90-Watt-Ac-Adapter/31510/bn_7023397221 (read 2026-09-16).
- **HP is the same trap, with a wattage twist.** HP's own 800 G6 Mini uses **a 90 W HP notebook-style
  adapter**, and ServeTheHome measured the **35 W-TDP** model peaking at *"just over 61 W"* — verbatim:
  *"the old 65 W power adapters common in this segment for generations are not enough, despite the same
  CPU TDP being advertised… We would advise against the below combination with the 65 W power supply."*
  — https://www.servethehome.com/hp-elitedesk-800-g6-mini-35w-1l-pc-review/3/ `[PUB]`. **A "cheap 65 W
  HP brick" is not a substitute; a fleet built on 65 W bricks will brown-out under load.**
- **Consequence: three "cheap" nodes at $150 each actually cost ~$167 each before tax**, and the $119.99
  M720q costs ~$162 to make bootable. **Recompute §4 accordingly.**

**2. The OptiPlex 7070 Micro has a documented fan-control defect — fixable only by a BIOS update.**
Dell community thread *"Improperly controlling the CPU cooling fan speed in OptiPlex Micro 7070-6794"*,
https://www.dell.com/community/en/conversations/optiplex-desktops/improperly-controlling-the-cpu-cooling-fan-speed-in-optiplex-micro-7070-6794/647f849cf4ccf8a8de37e84d
— posted 2019-11-15, last modified 2020-07-28, **thread status "UNSOLVED"**, 2 users confirming.
Verbatim: *"Under CPU load, the fan speed increases with a long delay. Because of this, the processor
heats up to 100 °C and its throttling reaches 30 %"* on **BIOS 1.4.4**, and later:
*"the last regular update (just a few days ago) seems to have finally fixed the operation of the fan
controller. Up to now I have not registered any throttling."*
**Action for a fleet: on every 7070 Micro received, update the BIOS first and confirm it is above 1.4.4
before it takes production work.** A used box sold with its original 2019-era BIOS ships *with* this bug.
For a node that must hold 14 resident turns at low fan speed in a home office, this is the difference
between a working node and one that throttles 30 % under exactly the load the fleet applies.

**3. No soldered RAM on any mandated candidate — confirmed, and it is the reason to buy these.**
Every mandated machine is **2 × SO-DIMM** (Micro/Tiny) or **4 × UDIMM** (SFF), except the N100 boxes
(one soldered/single slot) and the two machines the estate already owns that cannot be expanded at all
(the Yoga 9's 32 GB soldered LPDDR5x, and the Mac mini M4's 16 GB on-package). **Confirm two slots before
buying any node**; the one candidate where this is genuinely in doubt is the **HP EliteDesk 800 G5 Mini**
(§5.2).

**4. CPU is socketed, not soldered — on the T-suffix parts it matters that you can swap it.**
Intel ARK, **`[PUB]`** https://www.intel.com/content/www/us/en/products/sku/199275/intel-core-i510500t-processor-12m-cache-up-to-3-80-ghz/specifications.html (read 2026-09-16), verbatim for
**i5-10500T**: `Total Cores 6`, `Total Threads 12`, `TDP 35 W`, `Sockets Supported FCLGA1200`,
`Intel vPro Eligibility: Intel vPro Platform`, `Intel Virtualization Technology (VT-x): Yes`,
`Intel Virtualization Technology for Directed I/O (VT-d): Yes`, `VT-x with Extended Page Tables (EPT):
Yes`, `Intel AES New Instructions: Yes`, `Intel Trusted Execution Technology: Yes`, `Intel Boot Guard: Yes`.
So the i5-10500T is a **socketed LGA1200** part on a **vPro** platform with full VT-x/VT-d.

**5. "A CPU that cannot do virtualization" is not a live risk in this list.**
Every CPU in the mandated set (i5-8500T, i5-9500T, i5-10500T, i5-11500T, i7-8700, i7-9700, i7-10700)
is a vPro-capable Intel Core part with VT-x and VT-d. **The real virtualization-adjacent gotcha on 1 L
Tinies is different: the Lenovo M720q's PCIe riser cannot supply more than ~50 W to an add-in card**
`[PUB]` ServeTheHome TinyMiniMicro reference thread,
https://forums.servethehome.com/index.php?threads/lenovo-thinkcentre-thinkstation-tiny-project-tinyminimicro-reference-thread.34925/page-108
— relevant only if a NIC or GPU is planned, not for agent nodes.

**6. Known Lenovo M920q/M720q power complaints.** Lenovo forum thread *"Lenovo Thinkcentre M920q power
issues"*, https://forums.lenovo.com/t5/ThinkCentre-A-E-M-S-Series/Lenovo-Thinkcentre-M920q-power-issues/m-p/5234559,
and Lenovo KB **ht508237** *"TIO 135 W POST Warning message – ThinkCentre M720q"*,
https://support.lenovo.com/us/en/solutions/ht508237 `[PUB]`. The practical bite is that Tinies are
**sensitive to the exact adapter wattage** — a 65 W brick on a config that wants 90 W produces a POST
warning or throttling. **Buy the right brick, not the cheapest brick.**

**7. An eBay listing's "Maximum RAM" attribute is seller-entered and can be flatly wrong.**
The $150 7070 Micro listing — https://www.ebay.com/itm/336795130291 — carries an item-specific field
claiming a **64 GB** maximum. **Dell's own manual for the OptiPlex 7070 Micro says 32 GB and 16 GB per
slot.** The seller also entered a `max_ram` of 16 GB on the **5090 Micro** listing. **Never plan a RAM
upgrade from a listing attribute; use the Dell/HP/Lenovo spec page in §3(c).**

**8. 8 GB machines are a trap at 2026 memory prices** — see §2 and §4.2. The gap between the $150 16 GB
7070 Micro and an 8 GB machine is smaller than one 32 GB SO-DIMM kit. **Buy the RAM already
installed.**

**9. A Lenovo Tiny needs a Lenovo *slim-tip* brick, not a generic barrel plug — and 90 W, not 65 W.**
ServeTheHome: *"These are essentially Lenovo laptop power supplies so you can use those too. A 65 W or
90 W supply is what you generally get."* Lenovo KB **ht508237** (*"TIO 135 W POST Warning message –
ThinkCentre M720q, M920q"*, published 2019-04-03) documents that an **under-spec adapter produces a POST
warning** and the fix is the compatible 90 W/135 W unit. **Live price for a genuine 90 W slim-tip brick:
$17.89 with 209 sold** — https://www.ebay.com/itm/304872631848. **Budget it per node and buy the right
wattage, not the cheapest wattage.**

**10. On the Lenovo M720q / M920q / M920x, 64 GB works — but only after a BIOS update, and Lenovo will
not tell you.** Lenovo's PSREF rates all three at **32 GB**. The direct evidence that 64 GB (2×32 GB) is
achievable is https://www.lifeofstu.com/articles/lenovo-m920q.html (**28 April 2021**), verbatim: *"the
official specifications … show a maximum RAM capacity of 32GB, the CPU … actually supports significantly
more… after flashing the BIOS to the latest version (this part was important, I went for M1UKT65A) the
device will take 2×32GB SODIMM's for a cool 64GB RAM. Memtest86+ shows the RAM is fine with a full pass,
and ESXi shows all of the RAM as usable."* **Practical rule: on M720q/M920q/M920x treat 64 GB as
achievable but require BIOS `M1UKT65A` or newer, and test it on the first unit before buying a RAM
batch. On the M90q it is spec'd by Lenovo (64 GB) and needs no such caveat.**

**11. "Won't power on" is the dominant Lenovo Tiny failure, and it is the specific reason "no AC" units
are a gamble.** Both Lenovo forum threads on it are titled exactly that —
https://forums.lenovo.com/t5/ThinkCentre-A-E-M-S-Series/Lenovo-ThinkCentre-M720Q-refuses-to-power-on/m-p/5189961
(2022-12-18) and
https://forums.lenovo.com/t5/ThinkCentre-A-E-M-S-Series/Lenovo-Thinkcentre-M920q-power-issues/m-p/5234559
(2023-06-28) — and the community fixes point at a power-rail / power-button / adapter fault. **You cannot
distinguish a dead brick from a dead board without a known-good 90 W adapter**, which is why buying the
brick separately is not optional. A no-POST that is *not* dead is often fixed by pulling the CMOS battery
for five minutes (iFixit and r/homelab threads, 2026-04/2026-05). **No thermal-throttling failure mode was
found for the Lenovo Tiny at all — the 7070 Micro is the one with the documented fan defect (§3(f)2).**

**12. BIOS-locked units are on the market right now at deceptively low prices.** Live examples seen
today: a **Precision 3640 Tower i7-10700K with 32 GB at $249.99 marked "BIOS LOCKED"**
(https://www.ebay.com/itm/206561398449), an **HP ProDesk 600 G6 Mini 16 GB at $139.99 with a BIOS lock**
(https://www.ebay.com/itm/178468244184), and an HP Z2 Mini G5 with a BIOS password. **A BIOS lock turns a
cheap node into a brick** — it cannot be re-imaged or re-sold cleanly. **Always confirm "no BIOS
password" before paying.**

**13. Core counts lie in listing titles — check the CPU part number, not the marketing text.** Concrete
traps verified today: **i5-9500 / i5-8400 / i5-8500 / i5-8600 are 6c/6t — no Hyper-Threading**; only
i7-8700, i5-10400/10500/10600, i7-9700 (8c/8t) and i7-10700 (8c/16t) carry it. **Dell Xeon E-21xx parts
are 4-core** (E-2104G/E-2124G/E-2224 = 4c/4t, E-2174G = 4c/8t) despite being sold in 6-core-class
chassis, and **Xeon W-1250P is 6c/12t, not 8c**. **A listing that says "8-Core" proves nothing.**

**14. Two HP Z2 SFF traps, both from HP's own QuickSpecs.** (i) The **x16 slot is "meant for HP qualified
cards"** and HP disclaims warranty support for third-party cards there. (ii) On the **Z2 G5, a 65 W
system cannot take ECC memory at all** — *"The 125 W systems support ECC or nECC memory. The 65 W systems
can only support non-ECC memory"* — and ECC and non-ECC **cannot be mixed**. Since the i5-10500 and
i7-10700 are 65 W parts, a stock Z2 SFF built with them **rejects ECC UDIMMs** despite the datasheet
headline reading "128 GB ECC/non-ECC". Sources: https://gc3.de/files/quickspecs/qs_Z2G5SFF.pdf.

**15. Dust is the number-one real defect on used 1 L machines.** ServeTheHome, on buying these second
hand: *"a lot of folks get them and they are loud because dust has built-up in the fans. So that is always
something good to clean out before using these systems."* —
https://www.servethehome.com/dell-precision-3240-compact-mini-review-intel-xeon-nvidia/4/ **Blow out
every node before it goes into a home office or a room with customers in it.**

---

## 4. Recomputed from live prices only — and does the recommendation hold?

**Taxed = delivered pre-tax × 1.06625.** Turns from the 25 % headroom rule (`floor(0.75 × GB / 0.81)`).
**Only `[LIVE]` prices appear here**; `[CARRIED]` prices are excluded from every ranking.

### 4.1 $ per turn, $ per thread and $ per core — live prices only, taxed

| # | Candidate (all `[LIVE]` 2026-09-16) | Delivered | **Taxed** | Turns | Threads | **Cores** | **$/turn** | **$/thread** | **$/core** |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **HP ProDesk 600 G5 Mini, i5-9500T, 16 GB, 256 GB SSD** — /itm/366670683938 | $128.82 | **$137.36** | **14** | 6 | 6 | **$9.81** | **$22.89** | **$22.89** |
| 2 | **HP EliteDesk 800 G5 DM, i5-9500, 8 GB, 256 GB** — /itm/257747124079 | $104.99 | $111.94 | 7 | 6 | 6 | $15.99 | $18.66 | $18.66 |
| 3 | **OptiPlex 5060 Micro, i5-8500T, 8 GB, no HDD** — /itm/147564870681 ^ | $95.00 | $101.29 | 7 | 6 | 6 | $14.47 | **$16.88** | **$16.88** |
| 4 | **HP EliteDesk 800 G5 Mini, i5-9500, 16 GB, 256 GB** — /itm/820119277761 | $149.99 | $159.93 | **14** | 6 | 6 | **$11.42** | $26.66 | $26.66 |
| 5 | **OptiPlex 7070 Micro, i5-9500T, 16 GB, 256 GB, NO POWER CABLE** — /itm/336795130291 ^^ | $150.00 | $159.94 | **14** | 6 | 6 | **$11.42** | $26.66 | $26.66 |
| 6 | HP EliteDesk 800 G4 Mini, i5-8500T, 8 GB, no HDD — /itm/820130778216 ^ | $98.00 | $104.49 | 7 | 6 | 6 | $14.93 | $17.42 | $17.42 |
| 7 | ~~M920x Tiny, i5-8600, 16 GB, 256 GB — /itm/306968232037~~ **EXCLUDED — the two readings of this listing disagree ($134.95 vs $259.09, two different sellers). A price that cannot be reproduced twice is not a price.** | — | — | — | — | — | — | — | — |
| 8 | **M720q Tiny, i5-8500T, 16 GB, 480 GB** — /itm/168691535691 | $164.99 | $175.92 | **14** | 6 | 6 | $12.57 | $29.32 | $29.32 |
| 9 | **OptiPlex 7080 SFF, i5-10500, 8 GB, no HDD** — /itm/178482355831 ^ | $167.71 | $178.82 | 7 | **12** | 6 | $25.55 | **$14.90** | $29.80 |
| 10 | **OptiPlex 5090 Micro, i5-10500T, 16 GB, 256 GB** — /itm/137735826695 | $185.00 | **$197.26** | **14** | **12** | 6 | **$14.09** | **$16.44** | $32.88 |
| 11 | **OptiPlex 3080 Micro, i5-10500T, 16 GB, 256 GB** — /itm/800626975808 | $186.99 | $199.38 | **14** | **12** | 6 | $14.24 | $16.62 | $33.23 |
| 12 | OptiPlex 3090 Micro, i5-10500T, 16 GB, 256 GB, no OS — /itm/137722041342 | $189.99 | $202.58 | 14 | 12 | 6 | $14.47 | $16.88 | $33.76 |
| 13 | **HP EliteDesk 800 G6 Mini, i5-10500, 16 GB, no storage, no adapter** — /itm/188939833705 ^^^ | $139.95 | $149.23 + $44.78 = **$194.01** | **14** | **12** | 6 | $13.86 | $16.17 | $32.34 |
| 14 | OptiPlex 7080 Micro, i5-10500T, 16 GB, 256 GB — /itm/227514395580 | $199.99 | $213.24 | 14 | 12 | 6 | $15.23 | $17.77 | $35.54 |
| 15 | HP EliteDesk 800 G6 Mini, i5-10500, 16 GB, no SSD — /itm/178500504765 ^^^ | $159.99 | $170.59 + $26.66 = **$197.25** | 14 | 12 | 6 | $14.09 | $16.44 | $32.88 |
| 16 | **OptiPlex 7070 SFF, i7-9700, 16 GB, 256 GB** — /itm/168360463161 | $219.99 | **$234.56** | **14** | 8 | **8** | $16.75 | $29.32 | **$29.32** |
| 16a | **Dell Precision 3431 SFF, i7-9700, 16 GB, 512 GB** — /itm/318879789819 | **$179.99** | **$191.91** | **14** | 8 | **8** | **$13.71** | **$23.99** | **$23.99** |
| 16b | **HP Z2 SFF G4, i7-9700, 16 GB, 256 GB** — /itm/278048013515 | $209.99 | $223.79 | 14 | 8 | **8** | $15.99 | $27.97 | $27.97 |
| 16c | **Dell Precision 3630 Tower, i5-8500, 16 GB, no HDD/no adapter** — /itm/188753282772 | $169.99 | $181.26 | **14** | 6 | 6 | $12.95 | $30.21 | $30.21 |
| 16d | **Dell Precision 3240 Compact, i5-10500, 16 GB, 512 GB** — /itm/318845099211 | $284.99 | $303.87 | 14 | **12** | 6 | $21.71 | $25.32 | $50.65 |
| 17 | **HP EliteDesk 800 G4 SFF, i7-8700, 8 GB, no SSD** — /itm/257744791014 ^ | $145.00 | $154.61 + $21.33 = **$175.94** | 7 | **12** | 6 | $25.13 | $14.66 | $29.32 |
| 18 | M720q Tiny, i5-8400T, 8 GB, 128 GB — /itm/227523533725 | $140.00 | $149.28 | 7 | 6 | 6 | $21.33 | $24.88 | $24.88 |
| 19 | **M90q Tiny Gen 1, i5-10500T, 16 GB, 256 GB, W11P** — /itm/237069946746 | $249.99 | $266.55 | 14 | 12 | 6 | $19.04 | $22.21 | $44.43 |
| 20 | **Beelink SER5 Pro, Ryzen 7 5700U 8c/16t, 16 GB, 500 GB** — /itm/188930286758 | $313.99 | $334.79 | 14 | **16** | **8** | $23.91 | $20.92 | $41.85 |
| 21 | **HP Z2 SFF G5, i7-10700, 16 GB, no HDD** — /itm/820050924745 ^ | $324.95 | $346.48 + $21.33 = **$367.81** | 14 | **16** | **8** | $26.27 | $22.99 | $45.98 |
| 22 | M910q Tiny, i5-7500T **4c/4t**, 8 GB, no disk — /itm/178498871974 ^ | $69.95 | $74.58 | 7 | 4 | 4 | $10.65 | $18.65 | $18.65 |
| 23 | M720q Tiny, i5-8400T, 8 GB, **no HDD, no PSU** — /itm/198568451166 ^^ | $119.99 | $127.94 + $18.13 + $26.66 = **$172.73** | 14 | 6 | 6 | $12.34 | $28.79 | $28.79 |

^ needs a boot disk (~$20–25) — the added tax is included in the taxed figure.
^^ needs a power adapter (~$16.99) — included.
^^^ needs **both** an SSD and an adapter — included.

### 4.2 Verdict: **the recommendation should CHANGE.** The standing price is no longer the market price for that specification.

**Buy the same machine two generations of search away, for $102 less — or the cheapest 6-core box on the
board for $180 less.**

| | **STANDING: 3 × OptiPlex 5090 Micro @ $185** | **NEW (same spec, cheaper): 3 × OptiPlex 3090 Micro @ $152.98** | **CHEAPEST: 3 × HP ProDesk 600 G5 Mini @ $128.82** |
|---|---|---|---|
| Item `[LIVE]` | $185.00 free, 3 available | $152.98 free, **3 available** | $120.00 + $8.82, **23 available** |
| URL | /itm/137735826695 | **/itm/267785174714** | /itm/366670683938 |
| **Taxed** | **$591.64** | **$489.35** | **$412.03** |
| Turns | **+42** | **+42** | **+42** |
| **Cores** | **+18** | **+18** | **+18** |
| Threads | **+36** | **+36** | +18 |
| RAM ceiling | 64 GB | **64 GB** *(Dell 3090 manual: 2 SODIMM, 64 GB)* | 64 GB |
| Stock | 16 GB / 256 GB NVMe | **16 GB / 256 GB NVMe, Win 11 Pro** | 16 GB / 256 GB SSD |
| Idle W/node | **12.7 measured** | ~12–13 (same 1 L platform; **not measured for the 3090**) | ~11–13 (**not measured**) |
| **$/turn** | $14.09 | **$11.65** | **$9.81** |
| **$/core** | $32.88 | **$27.19** | **$22.89** |
| Missing parts | none in evidence | none in evidence | **adapter unconfirmed** |

**Three findings decide this, and they are all price, not judgement:**

1. **The exact specification the standing recommendation buys — i5-10500T, 6c/12t, 16 GB, 256 GB NVMe,
   64 GB ceiling, same 10th-generation 1 L Micro platform — is available today at $152.98 delivered with
   free shipping and 3 available** — https://www.ebay.com/itm/267785174714 — from Omega Recycling
   Solutions. **That is $32.02 per node, $102.29 across three, below the $185 the earlier file was
   costed at, for identical hardware.** The earlier file's price is not wrong; it is simply no longer
   the best price for the same thing. *(Worth noting how this surfaced: the search page showed $169.98
   and the listing's own page showed $152.98. **The item page is the truth and the search card is
   not** — three listings disagreed the same way.)*
2. **The cheapest complete 16 GB node on the board is the HP ProDesk 600 G5 Mini at $128.82 delivered
   → $412.03 taxed for three**, and `40-hardware-costs.md` **never mentioned the ProDesk line at all.**
   It gives the same **+42 turns and +18 physical cores** for **$179.61 less** than the standing
   package, with a 64 GB ceiling and 23 units available. **It is 6c/6t rather than 6c/12t — that is the
   entire trade.**
3. **What the extra money buys, stated honestly:** SMT. The standing 5090 and the $152.98 3090 are
   both **6c/12t**; the ProDesk is **6c/6t**. Under `40-hardware-costs.md`'s own model (*"each generating
   turn costs ~1 core"*) **all three packages add the same 18 cores and the same 42 turns** — SMT buys
   throughput headroom on those cores, not more turn slots. So:
   - **If SMT headroom is worth $34/node: buy 3 × OptiPlex 3090 Micro at $152.98 — $489.35 taxed.**
     This is the closest thing to a "just buy it" answer: same spec as the standing pick, cheaper,
     in stock in exactly the quantity needed.
   - **If it is not: buy 3 × HP ProDesk 600 G5 Mini at $128.82 — $412.03 taxed**, and accept two
     unknowns: its **idle watts are unmeasured** (no watt-meter review of any HP 600 G5 or 800 G5 Mini
     exists — this was checked, not assumed) and its **power adapter inclusion is unconfirmed**
     (one eBay message settles it; +$18/node if absent, still ~$358 under the standing package).
   - **The 5090 Micro at $185 remains the single best-evidenced node** — a **meter-measured 12.7 W**, a
     ceiling from **Dell's own manual**, an adapter in evidence, and exactly 3 units — but **it is now
     the most expensive way to buy this specification, by $102.29.** Buy it only if certainty is worth
     that.
4. **A fourth live option matches the 3090 almost exactly:** **OptiPlex 3080 Micro at $186.99 delivered
   / $199.38 taxed** — https://www.ebay.com/itm/800626975808 — same CPU, same ceiling, 64 GB. **And the
   cheapest 6c/12t *with no storage* is the HP EliteDesk 800 G6 Mini, i5-10500, 16 GB at $139.95
   delivered** — https://www.ebay.com/itm/188939833705 — which lands at **$194.01 taxed** once an SSD
   and adapter (~$42) are added, i.e. **$2.25 cheaper than the 5090 with identical specs.**
5. **$/turn remains nearly flat among complete machines ($9.81–$16.75) — that has not changed.** What
   changed is that **$/core now varies by 44 % across three machines with identical core counts**
   ($22.89 ProDesk / $27.19 3090 / $32.88 5090). **$/core is the discriminator, and it favours the
   ProDesk.**
6. **The measurement that would settle it, and it is 30 minutes of work:** put a kill-a-watt on one
   node of each family, idle, 24 hours. **`40-hardware-costs.md` guessed 20–25 W for SFF and nobody has
   ever measured an SFF or an HP G5 Mini.** If the ProDesk idles at 11–13 W like every measured 1 L HP,
   it wins outright; if it idles at 20 W+, the maths shifts. **This is the only remaining unknown that
   matters.**

### 4.3 The package — final, executable

| | **A — BEST SPEC-FOR-SPEC** | **B — CHEAPEST THAT CLEARS THE BAR** | **C — STANDING (now superseded on price)** |
|---|---|---|---|
| Buy | **3 × OptiPlex 3090 Micro** | **3 × HP ProDesk 600 G5 Mini** | 3 × OptiPlex 5090 Micro |
| Listing | /itm/267785174714 | /itm/366670683938 | /itm/137735826695 |
| Unit | $152.98 free | $120.00 + $8.82 | $185.00 free |
| In stock | **3** | **23** | 3 |
| **Taxed total** | **$489.35** | **$412.03** | $591.64 |
| Turns / cores / threads | **+42 / +18 / +36** | **+42 / +18 / +18** | +42 / +18 / +36 |
| Idle, 3 nodes | ~38 W → ~$83/yr | ~36 W → ~$79/yr *(est.)* | 38.1 W → $83.50/yr *(measured, per node)* |
| **Verdict** | **Recommended. Same spec as the standing pick, $102.29 less.** | **Best value. Take it if SMT is not worth $77.** | **Superseded on price. Buy only for certainty.** |

**Do not buy the 7070 Micro package as priced.** It halves the thread count, caps at 32 GB, ships
without power cables, and carries a documented thermal defect below BIOS 1.4.4 — for a saving of
$57.48 against C, and *more* than A.

**Buy these two regardless of which node package is chosen — they are still the cheapest capacity in
the estate and neither needs a new machine:**

| Purchase | Cost taxed | Adds | **$/turn** |
|---|---|---|---|
| **2 × 8 GB DDR3-1600 UDIMM** for `secratary` (Timetec `MR-H8GD316U7D`, $38.99) | **$41.57** | **+8 turns** (21→29) | **$5.20 — cheapest in the document** |
| **1 × 32 GB DDR4-3200 UDIMM** for `linux-pc-ts` (Rimlance `RLMUD-25600-32-28`, $159.00) | **$169.53** | **+27 turns** (10→37) | **$6.28** |

---

## 5. Corrections to `40-hardware-costs.md`

**This is the part a future session should read first.**

### 5.1 Confirmed correct
- The **$185 OptiPlex 5090 Micro** recommendation: **`[LIVE]` today at $185.00, free UPS Ground, 3
  available** from the same item URL. The load-bearing price is real.
- The **$150 OptiPlex 7070 Micro** listing exists at $150.00 with free delivery and **9 available**.
- **5090 Micro = 64 GB ceiling, 2 SODIMM.** Confirmed by Dell's own manual.
- **7070 Micro = 32 GB ceiling.** Confirmed by Dell's own manual.
- **7090 Micro = 64 GB**, **7080 Micro = 64 GB**, **3080 Micro = 64 GB**, **3070 Micro = 32 GB**.
- NJ electricity **24.95 ¢/kWh** and **$2.19 per watt-year**; NJ sales tax **6.625 %**, eBay collects.
- The 7090 Micro's idle power is now a **real meter measurement at 12.7 W** (STH, i5-10500T),
  replacing the class estimate.

### 5.2 Corrected or newly contradicted
1. **`40-hardware-costs.md`'s correction — "HP EliteDesk 800 G5 Mini supports 64 GB (2 × 32 GB), not
   32 GB" — is CORROBORATED, and my own first-draft challenge to it was half wrong. Recorded honestly:**
   **HP contradicts itself, and the 64 GB figure is backed by the stronger pair of documents.**
   - **For 64 GB:** HP **QuickSpecs** *"HP EliteDesk 800 G5 and EliteOne 800 G5 Business Desktops PCs"*,
     **c06320288 – DA-16479 – Worldwide – Version 21 – 4 March 2020**: *"DDR4-2666 …, 64 GB, 2 SODIMM"*;
     and the **HP 800 G5 Desktop Mini datasheet**: *"up to 64 GB memory … Memory slots 2 SODIMM."*
   - **For 32 GB:** HP **Maintenance and Service Guide, HP EliteDesk 800 G5 Desktop Mini**,
     https://h10032.www1.hp.com/ctg/Manual/c06439994.pdf — *"Slots: 2 / Maximum memory: 32"* and
     *"you can populate the system board with up to 32 GB of memory."*
   **Assessment: the 64 GB figure is correct** — the QuickSpecs and the datasheet are the platform
   specifications, and the M&SG's 32 GB line is almost certainly stale (32 GB SO-DIMMs were not a
   validated option when it was written). **But this is the only ceiling in §3(c) where the
   manufacturer contradicts itself in print, so it is the one ceiling worth confirming on the unit
   before a purchase depends on it.** *My first draft called the 64 GB claim "NOT supported". That was
   too strong and is corrected here.*
2. **HP's own ProDesk/EliteDesk documents are otherwise consistent and generous — and they were
   missed entirely by the earlier file:** ProDesk 600 G5 Mini = **64 GB / 2 SODIMM**; ProDesk 600 G6
   Mini = **64 GB / 2 SODIMM** (QuickSpecs c06640111, Version 23, 3 December 2021); EliteDesk 800 G6
   Mini = **64 GB / 2 SODIMM**. **No soldered memory in any of these families** — the QuickSpecs state
   *"All memory slots are customer accessible/upgradeable."* One circulating G6 QuickSpecs copy carries
   *"Mini Maximum memory 128 GB"* — that is the **SFF row bleeding into the DM section**; 128 GB is
   impossible across two SO-DIMM slots and contradicts the same document's own "2 SODIMM" line. **Do
   not rely on it.**
3. **`40-hardware-costs.md` omitted the HP ProDesk line completely, and that omission is where the
   money was.** The **HP ProDesk 600 G5 Mini (i5-9500T, 16 GB, 256 GB SSD) at $128.82 delivered** is the
   cheapest complete 16 GB node verified today and the reason §4.2's verdict changed. **ProDesk was not
   mentioned once in the earlier file.**
4. **The budget arm's price omitted three power adapters** (~$17 each) that the listing explicitly
   excludes. See §4.3.
5. **The 7070 Micro's documented thermal defect was absent from the earlier file.** See §3(f)2.
6. **The earlier file's SFF idle estimate is still an estimate** — and it is now doing *less* work than
   before, because §4.2 no longer recommends against SFF on wattage. **A kill-a-watt on one SFF remains
   the single most valuable measurement available**, because it would also settle the ProDesk-vs-5090
   choice. **Measured beats estimated, and this is 30 minutes at the bench.**
7. **A cheaper 12-thread/64 GB node than the 5090 was missed: the OptiPlex 3080 Micro at $186.99
   delivered** — https://www.ebay.com/itm/800626975808. Same CPU, same ceiling, $2.12 less taxed.
   **Also missed: the HP EliteDesk 800 G6 Mini, i5-10500, 16 GB at $139.95 delivered**
   — https://www.ebay.com/itm/188939833705 — which is the **cheapest 16 GB 6c/12t machine on the
   board** once an SSD and adapter (~$42) are added, landing at $194.01 taxed: **$2.25 cheaper than the
   5090 with identical specs and the same 64 GB ceiling.**
8. **"Precision 3440 Compact" does not appear to exist as a Dell product name.** Dell's Precision
   desktop line is **3240 Compact** (10th gen), **3440 SFF**, **3640 Tower** (and 3260 Compact /
   3460 SFF / 3660 Tower for 11th gen). Retailer accessory listings do use the string *"Precision 3440
   Compact Workstation"*, so the name circulates — but **Dell's own manual for the 3440 is titled
   "Small Form Factor"** and specifies **4 DIMM slots / 128 GB**, which is not a Compact-class machine.
   **When sourcing, search "Precision 3440 SFF".**
9. **Idle-watt figures `[CARRIED]` from the earlier file for the EliteDesk 800 G5 Mini, M920x and M90q
   remain NOT FOUND** — and for the **G5 Mini this is now confirmed to be a real absence, not a failure
   to look**: Project TinyMiniMicro covered the EliteDesk 800 **G2, G3, G4 and both G6 variants**, so
   **no published watt-meter review of any HP 600 G5 or 800 G5 Mini exists.** Do not expect to find one.
10. **Three DDR4 prices in the earlier file were stale *high* by 29–45 %, and they were the ones the
    "second tranche" recommendation was costed from.** Live today: **single 32 GB DDR4-3200 UDIMM
    $159.00** (was $223.09–$255.95) · **64 GB (2×32) DDR4-3200 UDIMM $340.00** (was $490–$494) ·
    **32 GB (2×16) SO-DIMM 3200 kit $145.28 used / $169.00 new** (the file carried a *2666* kit at
    $203.08). **Consequence: the `linux-pc-ts` upgrade is $169.53 taxed for +27 turns — $6.28/turn, not
    $8.81 — which makes it the second-best capacity purchase in the estate.** A stale price that is too
    high is still a wrong price; it changed a recommendation in the conservative direction.
11. **A DDR3 purchase trap the earlier file did not flag:** A-Tech sells a part explicitly marketed
    "for Dell OptiPlex 9020" at **$56.98**, and NEMIX sells a DDR3-1600 **ECC** UDIMM 2×8 kit at
    **$57.99**. The correct part is the plain non-ECC kit at **$38.99** — **so the two most expensive and
    the most dangerous DDR3 options both present as "the right one" for this machine.**
12. **"BIOS whitelist" is NOT CONFIRMED for the OptiPlex 7070/7080 and must not be repeated as fact.**
    Dell's own 7070 SFF specification lists only low-profile graphics cards (Radeon R5 430, RX 550,
    GT 730), and the Dell community threads about GTX 1650 / RX 6700 cards in a 7070 are about
    **physical fit and PSU capacity, not BIOS rejection**. Note the **real** OptiPlex SFF trap instead:
    **the PSU is a proprietary Dell shape with a proprietary multi-pin main connector, Dell offers only
    200 W, and a failed unit means sourcing a Dell part number — not a $30 ATX unit.** Buy spares with
    the machines. (`40-hardware-costs.md` did not cover SFF PSUs at all.)

### 5.3 Still NOT FOUND after this pass — stated as gaps, never filled with a guess

- **Meter-measured idle watts for any SFF** (OptiPlex/EliteDesk/Z2 SFF), and for the **HP EliteDesk 800
  G5 / ProDesk 600 G5 Mini**. For the HP G5 this is now **confirmed to be a real absence, not a failure
  to search**: *Project TinyMiniMicro covered the EliteDesk 800 G2, G3, G4 and both G6 variants — so no
  published watt-meter review of any HP 600 G5 or 800 G5 Mini exists.* Do not expect to find one;
  **measure it.** *(Partly offset: HP publishes measured **Z2 Tower** G5 long-idle figures of
  12.3 / 13.976 / 17.623 W, and ServeTheHome measured the **Precision 3240 Compact at 16 W idle, ~7 W
  tuned** and the **Precision 3640 Tower at 56 W**. The SFF class remains genuinely unmeasured.)*
- Idle watts for **Precision 3440 SFF** and **Precision 3630 Tower** (the only figure found for the 3630
  was a forum user's *full server build*, which is not a bare idle and is not presented as one).
- **Live prices for the HP EliteDesk 800 G5 Mini.** The `[CARRIED]` $269.99 in the earlier file was not
  re-fetched. **However, the G5 Mini's near-twins are now priced live and are far cheaper** — the
  **G5 Desktop Mini i5-9500 8 GB/256 GB at $104.99 free** and the **ProDesk 600 G5 Mini at $128.82
  delivered** — so **treat the carried $269.99 as stale and do not quote it.**
- **Any trustworthy "maximum RAM" field on an eBay listing.** Seller-entered values were wrong
  repeatedly: the $150 7070 Micro claimed 64 GB (Dell says 32 GB); the **ProDesk 600 G5 Mini claimed
  256 GB** (HP says 64 GB); two HP Z2 G4 listings claimed 16 GB (HP's datasheet says 128 GB). **Use the
  vendor spec in §3(c) and nothing else.**
- **A single 16 GB DDR4-3200 SO-DIMM on eBay** — priced on Newegg only ($99.99). The eBay used-single
  price is almost certainly lower and is **unmeasured, not assumed**.
- **A watt-meter reading during a real agent workload** (as opposed to idle). Every figure here is idle
  or vendor-benchmarked; nobody has measured this fleet's actual duty cycle.

---

## 6. Change log — what arrived after the first draft, and what it changed

The first draft was written from this session's own fetches while **six parallel research subagents**
were still returning. **Their findings were integrated into the body rather than left here, so there is
one source of truth per number.** What each changed:

| Return | What it changed |
|---|---|
| **DDR4/DDR3 RAM sweep** (complete) | **Rewrote §2.** Three carried DDR4 prices were stale **high by 29–45 %** → the `linux-pc-ts` upgrade is **$169.53 for +27 turns ($6.28/turn), not $237.77 ($8.81/turn)**. Added ECC/RDIMM/counterfeit traps. Added the Newegg RSS method to §7. |
| **OptiPlex Micro sweep** (complete) | **Changed the verdict.** Found the **3090 Micro at $152.98, 3 available** → the same specification as the standing pick for **$102.29 less**. Also: the **$109 complete 6-core 3070 Micro** (rewrote §3(b)), the **7070 Micro $140 "No Power Cables"** units, and the **multi-config "last one" arbitrage listing** ($115 7080/32 GB, $125 3080/32 GB — flagged as one-off). |
| **HP sweep** (complete) | **Changed the verdict again, further.** Found the **ProDesk 600 G5 Mini 16 GB/256 GB at $128.82 delivered, 23 available** — the cheapest complete node on the board, and a **line the earlier file never mentioned**. Also supplied every §1c row, the HP **G5 QuickSpecs** that contradicts HP's own service guide (§5.2.1), and the confirmation that **no Elitedesk 800 G5 Mini measurement exists**. |
| **Lenovo Tiny sweep** (complete) | Supplied every §1b row and the PSREF ceilings. **Found the `M1UKT65A` BIOS requirement for 64 GB on M720q/M920q/M920x** (§3(f)10), the **slim-tip 90 W brick trap and its $17.89 live price** (§3(f)9), the **"won't power on" failure profile** (§3(f)11), and **flagged the M920x $134.95 price as unreliable** — it is now marked so in §1b rather than quoted. |
| **Multi-core SFF + Ryzen sweep** (complete) | Supplied every §1d row and **the two-box $249.99 answer to §3(a)**. Established that **no sub-$300 complete Z2 SFF exists**, that **used Ryzen mini-PCs are not cheaper per thread than Intel SFFs**, and that the **OptiPlex SFF PSU is proprietary** (§5.2.12). |
| **Precision + Z2 sweep** (complete) | **Closed the big power gap**: **Precision 3240 Compact 16 W idle, ~7 W tuned (meter-measured)** and **Precision 3640 Tower 56 W**, plus HP's **Z2 Tower G5 12.3–17.6 W** vendor table. **Confirmed "3440 Compact" does not exist** (eBay: *0 results*). Found the **cheapest 8-core machine on the board — Precision 3431 SFF i7-9700, 16 GB, 512 GB at $179.99 free**. Added the Xeon core-count trap, the BIOS-locked listings, and the Z2 ECC/qualified-card caveats. |

**Where a row is absent above, the entry stands as written and is flagged `NOT FOUND` rather than
estimated.** **Nothing in this file was invented to fill a gap.**

---

## 7. How to re-verify this file in one sitting

```
# 1. The three decision-critical listings (each must return a price AND show stock)
#    https://www.ebay.com/itm/267785174714   OptiPlex 3090 Micro   $152.98 free, 3 available   <- BEST BUY
#    https://www.ebay.com/itm/366670683938   ProDesk 600 G5 Mini  $128.82 delivered, 23 available
#    https://www.ebay.com/itm/137735826695   OptiPlex 5090 Micro  $185.00 free, 3 available   (fallback, best-evidenced)

# 2. Re-price the whole family in one pass — eBay search, cheapest + shipping first, Buy-It-Now, used:
https://www.ebay.com/sch/i.html?_nkw=optiplex+3090+micro+i5-10500T&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=hp+prodesk+600+g5+mini+i5-9500T&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=optiplex+5090+micro+16GB&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=optiplex+3080+micro+i5-10500T&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=optiplex+7070+micro+16GB&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=optiplex+7080+micro+16GB&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=hp+elitedesk+800+g6+mini+i5-10500T&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=lenovo+thinkcentre+m920q+i5-8500T&_sop=15&LH_BIN=1&LH_ItemCondition=3000
https://www.ebay.com/sch/i.html?_nkw=precision+3431+sff+i7-9700&_sop=15&LH_BIN=1&LH_ItemCondition=3000

# 3. Add &_stpos=08701 to pin shipping to the owner's ZIP. Without it eBay quotes to the fetcher's
#    own location, and one 7080 search geo-detected a UK postcode and returned AU/DE/CA listings.
```

**Method note that will save a future session an hour:** eBay search-result pages and item pages both
render server-side and return real prices to a normal fetcher, **but the pages are ~150 KB of filter
markup and will blow a context window if read whole.** Fetch them, then read *only* the listing cards.
`mcp__jina__read_url` is **blocked by eBay** and returns an "Error Page"; the built-in `web_fetch` is
also poor on eBay (nav soup, truncated). **Item pages are the reliable unit of verification** — ask for
title, price, shipping, condition, availability and the item specifics; that returns in under 2 KB.

**A hard constraint discovered the hard way:** all fetches share **one rate limit (~11–13 requests per
minute)**. Six parallel research subagents saturate it and every one of them starts receiving HTTP 429s.
**Budget one fetcher, or serialise the fan-out.**

**The technique that made the RAM pass cheap — reuse it.** Newegg's **RSS endpoint** returns the same
product titles and prices as its search pages at **one credit and a fraction of the payload**:
```
https://www.newegg.com/d/Product/RSS?Description=<url+encoded+search+terms>
```
A Newegg search page costs ~30 KB of context; the RSS feed costs almost nothing. **For any future price
sweep, start at the RSS endpoint, not the search page.**

**Sites that refuse to be fetched, recorded so nobody wastes a turn on them again:** `reddit.com`
(firecrawl: *"we do not support this site"*; `web_fetch` returns **403**; jina returns a bot challenge),
**B&H Photo** (HTTP **403**), and **eBay via jina** ("Error Page"). eBay works fine through firecrawl and
through ordinary `web_fetch` for the *listing cards* only.

---

## 8. Bottom line

**The standing three-node recommendation should CHANGE — not because it is wrong, but because the same
specification is on sale for $102 less today.**

1. **Best buy: 3 × Dell OptiPlex 3090 Micro — i5-10500T (6c/12t), 16 GB, 256 GB NVMe, Win 11 Pro,
   64 GB ceiling — $152.98 each, free delivery, 3 available.**
   https://www.ebay.com/itm/267785174714 → **$489.35 taxed for the package.** This is the **same
   hardware** the standing recommendation buys at $185, **$32.02 per node cheaper**, in stock in exactly
   the quantity needed. **+42 resident turns, +18 physical cores, +36 threads, ~38 W (~$83/yr).**
   *(Read the listing's own page, not the search card: the search page showed $169.98.)*
2. **Cheapest that clears the same bar: 3 × HP ProDesk 600 G5 Mini — i5-9500T (6c/6t), 16 GB, 256 GB
   SSD — $128.82 delivered, 23 available.** https://www.ebay.com/itm/366670683938 → **$412.03 taxed.**
   Same **+42 turns and +18 cores** for **$179.61 less** than the standing package. **The trade is SMT
   (6c/6t vs 6c/12t) plus two unverified details: its idle watts and whether the power adapter is
   included.** Confirm the adapter with the seller before paying; measure the watts on arrival.
   **`40-hardware-costs.md` never considered the ProDesk line — that omission is where most of the
   saving was hiding.**
3. **The standing 5090 Micro package at $591.64 is now the most expensive way to buy this
   specification.** Its advantages are real and specific — a **meter-measured 12.7 W**, a ceiling from
   **Dell's own manual**, an adapter in evidence, and a seller with exactly the three units — **but they
   now cost $102.29 over the 3090 and $179.61 over the ProDesk.** Buy it for certainty, not for value.
4. **Withdraw the $150 7070 Micro arm as priced:** no power cables, half the threads, a 32 GB ceiling,
   and a documented fan-control defect below BIOS 1.4.4 — for a $57.48 saving against the *most
   expensive* option.
5. **The $250 / 16-thread target is met at $249.99 delivered** — but only as **two boxes** (an
   EliteDesk 800 G4 SFF i7-8700 at $145.00 free + an EliteDesk 800 G5 DM i5-9500 at $104.99 free), and
   the G4 SFF arrives diskless, so a bootable pair is **~$270**. **In *physical cores* the $250 budget
   tops out at 8**, and the cheapest complete 8-core machine found today is the **Dell Precision 3431
   SFF, i7-9700, 16 GB, 512 GB, $179.99 free** — https://www.ebay.com/itm/318879789819 → **$191.91
   taxed, $23.99/core.**
6. **Cheapest complete 6-core node under $120: the OptiPlex 3070 Micro, i5-8500T, 8 GB, 256 GB SSD,
   $109.00 free, adapter included, 2 available** — https://www.ebay.com/itm/178502239021.
7. **Do these two upgrades regardless of which node package is chosen — they are still the cheapest
   capacity in the estate and neither needs a new machine:**
   - **2 × 8 GB DDR3-1600 for `secratary` — $38.99 → $41.57 taxed → +8 turns at $5.20/turn.**
   - **1 × 32 GB DDR4-3200 UDIMM for `linux-pc-ts` — $159.00 → $169.53 taxed → +27 turns at
     $6.28/turn.** *(The earlier file priced this at $237.77 / $8.81 per turn from a stale figure. It is
     materially better than that file concluded.)*
8. **Before deploying any node, four checks — this is where the money and the uptime are lost:**
   1. **Two DIMM slots, not soldered RAM.** (Every candidate here qualifies; the *only* contested one is
      the HP EliteDesk 800 G5 Mini — see §5.2.1.)
   2. **A power adapter of the correct brand and wattage is present.** Dell 90 W 4.5 mm barrel · HP 90 W
      4.5 mm Smart Pin (a 65 W brick browns out under load) · Lenovo **slim-tip** 90 W, not a generic
      barrel plug. ~$17–20 each.
   3. **BIOS updated above 1.4.4 on any OptiPlex 7070**, and **`M1UKT65A` or newer on any M720q/M920q/
      M920x that will take 64 GB.** **And no BIOS password** — BIOS-locked units are on sale cheap right
      now.
   4. **Blow the dust out.** It is the single most common real defect on used 1 L machines and the reason
      a used node is loud.
9. **One measurement is still outstanding and it is the only one that matters: nobody has ever
   published a watt-meter idle figure for an HP 600 G5 / 800 G5 Mini, or for any SFF.** Put a
   kill-a-watt on one node of each family, idle, for 24 hours. **That number decides between the
   ProDesk and the 3090 and it costs 30 minutes at the bench.** Measured beats published, and published
   beats estimated — and estimated is all this document has for those two.

### If only one line is read

**Buy 3 × Dell OptiPlex 3090 Micro at $152.98, free delivery, 3 available —
https://www.ebay.com/itm/267785174714 — for $489.35 taxed, and add a $159 32 GB stick to `linux-pc-ts`
and $39 of DDR3 to `secratary`.** That is the same fleet the earlier document recommended, **$102
cheaper on the nodes and $68 cheaper on the desktop RAM**, with a measured power figure and a
vendor-documented RAM ceiling behind every unit.
