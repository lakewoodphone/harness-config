# 181 ΓÇö Procurement research: buy a 64 GB machine, or keep renting `secratary-cloud`?

**Date of research:** 2026-10-12
**Host:** `zabz-tech` (Windows desktop node)
**Scope:** research only. No purchase, no seller contact, no money committed.
**Target path note:** the task named `/root/code/harness-config/docs/mesh/`. That path does not exist on this host (this is the Windows desktop `zabz-tech`; there is no WSL and no `/root`). The same repository exists here at `C:\Users\ezabz\Code\harness-config`, and this report was written and committed there.

---

## 1. Bottom line

**Yes ΓÇö buying beats renting, and it beats it quickly.** A used HP Z6 G4 workstation with 64 GB RAM and a 20-core/40-thread Xeon Gold 6138, verified at **$469.99** on a fetched eBay listing page, pays for itself **in month 6** at a plausible 90 W idle, and **in month 7** even at a pessimistic 130 W idle. Over three years it costs roughly **$900ΓÇô$1,360 all-in including electricity**, against **$3,708** to keep renting ΓÇö a saving of about **$2,350ΓÇô$2,800**.

**But the reason the maths flipped is not that the cloud box was always overpriced.** It flipped in **June 2026**, when Hetzner raised CCX23 from **Γé¼31.49/month to Γé¼85.99/month (+173%)**, citing the DRAM shortage. At the old price (about $36/month), buying would *not* have paid back on a 3-year view. The owner's $102.99 is a real, current, list-price bill ΓÇö not a markup ΓÇö and it is now high enough that owning wins. Section 3 has the evidence.

**The honest caveat, stated plainly:** the $102.99 is not only paying for 4 vCPU and 16 GB. It is also paying for a public IP, DDoS protection, 2 TB of egress, redundant power and cooling, physical security, someone else replacing failed disks, and a box that answers at 2am. Buying transfers all of that onto the owner. Section 8 enumerates it. The recommendation is to buy **and run the new machine in parallel for one full month before cancelling anything.**

**On where to buy:** eBay decisively beats retail. Every 64 GB machine found on Newegg ΓÇö the one retail channel whose product pages were retrievable ΓÇö costs **$128ΓÇô$555 more** than the comparable eBay unit. Retail's advantage is a returns process and real stock; eBay's is price. Both are legitimate; the arithmetic below uses the eBay price.

---

## 2. Method and evidentiary standard

Every price below is tagged with how it was obtained:

- **FETCHED** ΓÇö the price was read off a listing page that this session actually retrieved and parsed.
- **SEARCH-PAGE** ΓÇö the price came from a fetched eBay *search results* page, i.e. the listing was rendered but its own detail page was not opened.
- **SNIPPET-ONLY** ΓÇö the price appeared only in a search-engine snippet. **No candidate in the final recommendation rests on a snippet-only price.**

This distinction was not theoretical. It caught a real error (Section 5.1).

---

## 3. What `secratary-cloud` actually is, and why it costs $102.99

| Fact | Value | Source |
|---|---|---|
| Hetzner CCX23 spec | 4 dedicated AMD vCPU / 16 GB RAM / **160 GB NVMe** | [hetzner.com/cloud/general-purpose](https://www.hetzner.com/cloud/general-purpose/) |
| CCX23 list price, Jul 2026 | **$101.49/mo** on-demand (730 h) | [spendark.com/instances/ccx23](https://spendark.com/instances/ccx23/) |
| CCX23 price **before June 2026** | Γé¼31.49/mo | [bex.co, 2026-07-20](https://bex.co/blog/2026/07/20/hetzner-2026-price-hikes-self-hosting-math) |
| CCX23 price **after 15 June 2026** | Γé¼85.99/mo ΓÇö **+173%** | same |
| US regions include | **2 TB traffic** (EU: 20 TB) | [hetzner.com/cloud/general-purpose](https://www.hetzner.com/cloud/general-purpose/) |

Two things worth flagging honestly:

1. **The owner's "2 TB traffic" detail identifies the region.** Hetzner's CCX23 includes 20 TB in EU locations but **2 TB** in the US locations (HIL1/ASH1). The stated 2 TB matches the US allowance, so this is a US-region box. That also explains why the USD figure ($101.49ΓÇô$102.99) sits above the EU euro price.
2. **The task's stated spec is slightly stale.** It says 80 GB disk; Hetzner's current CCX23 ships **160 GB NVMe**. This matters, because the disk ΓÇö not the CPU ΓÇö is plausibly the real constraint on a 24 GB-and-growing SQLite database.

### 3.1 The 2026 Hetzner hikes

Hetzner raised cloud prices **twice** in 2026:

- **1 April 2026:** a broad increase of up to 37%, applied to new orders **and every existing server** ΓÇö no grandfathering ([Hetzner press statement](https://www.hetzner.com/pressroom/statement-price-adjustment/)).
- **15 June 2026:** a targeted restructuring of the CPX and CCX lines. Existing contracts keep legacy pricing **until they are rescaled**; any resize converts that node to current pricing permanently ([Hetzner price-adjustment docs](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)).

The pass-through was wildly uneven by tier:

| SKU | Specs | Pre-hike | Post-hike | Change |
|---|---|---|---|---|
| CAX11 (ARM shared) | 2 vCPU / 4 GB | Γé¼4.49 | Γé¼5.99 | +33% |
| CX23 (Intel shared) | 2 vCPU / 4 GB | Γé¼3.99 | Γé¼5.49 | +38% |
| CCX13 (AMD dedicated) | 2 vCPU / 8 GB | Γé¼15.99 | Γé¼42.99 | +169% |
| **CCX23 (AMD dedicated)** | **4 vCPU / 16 GB** | **Γé¼31.49** | **Γé¼85.99** | **+173%** |

Shared-vCPU tiers absorbed the DRAM shock; dedicated-vCPU tiers took nearly all of it, because a dedicated tier is closer to the raw hardware bill for a core and the RAM behind it.

**This is the single most decision-relevant fact in the report.** The premise "I am paying $100+/month for a weak machine" is true *now* and was false nine months ago.

### 3.2 The DRAM shortage is real and corroborated

The task's premise about memory pricing checks out. **TrendForce raised its Q1-2026 DRAM contract-price forecast to +90ΓÇô95% quarter-on-quarter**, up from an earlier 55ΓÇô60% estimate; PC DRAM was projected **above +100%** and server DRAM above +60%. Published 2026-03-30 ([DigitalToday](https://www.digitaltoday.co.kr/en/view/43759/chip-prices-set-to-rise-again-amid-supply-shortage-and-higher-oil-costs)).

**Procurement consequence:** buy RAM already installed. A 64 GB DDR4-2666 ECC RDIMM kit bought separately in this market costs a large fraction of one of these whole machines. Every candidate recommended below has its 64 GB **already in it**.

---

## 4. Candidates

Prices observed **2026-10-12**. All eBay, all US sellers, all "Buy It Now" with free delivery unless noted.

| # | Make / model | Exact CPU | Cores/Threads | RAM | Storage | Price (USD) | Price basis | URL | Idle watts | Noise |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** | **HP Z6 G4 Workstation** | **1├ù Xeon Gold 6138** (2.0 GHz, 125 W TDP) | **20C / 40T** | **64 GB** DDR4-2666 ECC RDIMM | **none ΓÇö no SSD/GPU/OS** | **$469.99** | **FETCHED** ΓÇö 64 GB variation confirmed in the listing's own dropdown | [ebay.com/itm/336423407903](https://www.ebay.com/itm/336423407903) | **NOT FOUND** (no published or measured figure located) | **Idle 3.3 bels / 15 dB(A)** deskside, entry config; 3.8 bels / 23 dB(A) mid & high configs (HP QuickSpecs, ISO 7779) |
| **B** | **Lenovo ThinkStation P720** | **2├ù Xeon Gold 6148** (2.4 GHz, 150 W TDP) | **40C / 80T** | **64 GB** DDR4 | **1 TB SSD** + Quadro P4000 + Win 11 Pro | **$714.88** | **FETCHED** ΓÇö variation "6148, P4000, 64 GB, 1 TB SSD" | [ebay.com/itm/236603584348](https://www.ebay.com/itm/236603584348) | **NOT FOUND** | **NOT FOUND** |
| C | Lenovo ThinkStation P720 | 2├ù Xeon Gold 6150 (2.7 GHz, 165 W TDP) | 36C / 72T | 64 GB DDR4 | 1 TB SSD + P4000 + Win 11 Pro | $714.88 | FETCHED ΓÇö all variations same price | [ebay.com/itm/800708151673](https://www.ebay.com/itm/800708151673) | **NOT FOUND** | **NOT FOUND** |
| D | Dell Precision 5820 | Xeon W-2235 (3.8 GHz) | 6C / 12T | 64 GB | 960 GB SSD + RTX 2070, no OS | $660.00 | FETCHED search page | [ebay.com/itm/820135616854](https://www.ebay.com/itm/820135616854) | **NOT FOUND** | **NOT FOUND** |
| E | ~~Lenovo ThinkStation P520c~~ | ~~Xeon W-2140~~ | ~~8C / 16T~~ | ~~64 GB~~ | ~~1 TB SSD + 2 TB HDD~~ | ~~$487.00~~ | **WITHDRAWN ΓÇö listing page now returns HTTP 404; price not reproducible** | ~~[ebay.com/itm/190560902133](https://www.ebay.com/itm/190560902133)~~ | ΓÇö | ΓÇö |
| F | Lenovo ThinkStation P520 | Xeon W-2135 (3.7 GHz) | 6C / 12T | 64 GB | 512 GB SSD + K620 + **Win 11 Pro** | **$499.99** | **FETCHED** listing page, Good-Refurbished, free 2ΓÇô4 day delivery | [ebay.com/itm/307174416566](https://www.ebay.com/itm/307174416566) | **NOT FOUND** | **NOT FOUND** |
| G | Lenovo ThinkStation P520 | Xeon W-2225 | 4C / 8T | 64 GB | 1 TB NVMe + K620 | $504.00 | FETCHED search page | [ebay.com/itm/187971125861](https://www.ebay.com/itm/187971125861) | **NOT FOUND** | **NOT FOUND** |
| H | Lenovo ThinkStation P520 | Xeon W-2245 | 8C / 16T | 64 GB | 512 GB NVMe + P4000 | $720.91 | FETCHED search page | [ebay.com/itm/177777995801](https://www.ebay.com/itm/177777995801) | **NOT FOUND** | **NOT FOUND** |
| I | Dell Precision R7920 (**2U rack**) | 2├ù Xeon Gold 5120 | 28C / 56T | 64 GB | 8├ù LFF, GPU | $1,149.99 | FETCHED search page, Excellent-Refurbished | [ebay.com/itm/167503533177](https://www.ebay.com/itm/167503533177) | **NOT FOUND** (rack class reference 125ΓÇô252 W) | **NOT FOUND** |
| J | Dell Precision 7820 Tower | 2├ù Xeon Gold 6226 | 24C / 48T | **16 GB ΓÇö not 64** | 512 GB | $597.52 | FETCHED search page | [ebay.com/itm/397802924863](https://www.ebay.com/itm/397802924863) | **NOT FOUND** | **NOT FOUND** |

**Excluded, page not retrievable:** a "Dell Precision T7820 2├ù Gold 6130 64 GB" listing appeared at [ebay.com/itm/188137694058](https://www.ebay.com/itm/188137694058) but the listing page returned **HTTP 403** on direct fetch, so **no price for it is asserted here.**

### 4.0 Retail-channel results (Newegg)

A parallel research pass covered the retail channels. Newegg product pages **were** retrievable and are reported as FETCHED.

| # | Make / model | Exact CPU | Cores/Threads | RAM | Storage | Price | Basis | URL |
|---|---|---|---|---|---|---|---|---|
| K | Lenovo ThinkStation P520 | Xeon W-2135 (3.7 GHz) | 6C / 12T | 64 GB DDR4 | **none ΓÇö no HDD/GPU/OS** | **$597.98** | **FETCHED** product page (PCSP, in stock) | [newegg.com/p/2NS-000M-05VH1](https://www.newegg.com/p/2NS-000M-05VH1) |
| L | HP Z6 G4 | Xeon Silver 4114 (2.2 GHz) | 10C / 20T | 64 GB DDR4 | 512 GB SSD + FirePro W2100 + Win 11 | **$798.35** | **FETCHED** product page (PCSP, in stock) | [newegg.com/p/2NS-0006-3HW74](https://www.newegg.com/p/2NS-0006-3HW74) |
| M | HP Z840 | 2├ù Xeon E5-2687W v3 | 20C / 40T | 64 GB DDR4 | 512 GB SSD + Quadro M5000 + Win 10 Pro | **$1,025.25** | **FETCHED** product page (PCSP, in stock) | [newegg.com/hp-z-series-z840/p/1VK-001E-3PNG1](https://www.newegg.com/hp-z-series-z840/p/1VK-001E-3PNG1) |
| N | HP Z6 G4 | Xeon Gold 6148 | 20C / 40T | 64 GB | ΓÇö | $878.35 | **SEARCH-PAGE only** (Newegg grid price, own page not opened) | Newegg Z6 G4 family, sorted lowest first |
| O | HP Z6 G4 | **2├ù Xeon Gold 6152** | **44C / 88T** | 64 GB | ΓÇö | $1,068.17 | **SEARCH-PAGE only** (Newegg grid price, own page not opened) | Newegg Z6 G4 family, sorted lowest first |

**Newegg does not beat eBay.** Every Newegg 64 GB machine costs **more** than a comparable eBay unit ΓÇö from **$98 more** at the bottom of the range upward. The $597.98 Newegg P520 (6C/12T, no storage, no OS) is beaten by the **$469.99** eBay HP Z6 G4 with **20C/40T**, and by the **$499.99** eBay P520 with 6C/12T *including* storage, GPU and Windows 11 Pro at that price. Put directly: for **$98 less** than the Newegg barebones, eBay sells the same P520 model with a 512 GB SSD, a Quadro K620 and an activated Windows 11 Pro licence. Newegg's only advantage is that PCSP is a business seller with a returns process and stock rather than a one-off listing.

Candidate **O** ΓÇö a Z6 G4 with **2├ù Xeon Gold 6152 at 44C/88T for $1,068.17** ΓÇö is worth flagging as the **highest core count inside the $1,500 budget found anywhere in this pass**, but it rests on a grid price, not a verified product page, so it is **not** used for the recommendation. A dual-Xeon Z6 G4 is genuinely possible: HP's own QuickSpecs document the *2nd CPU & Memory Module* option, which "adds 2nd CPU socket and (6) DIMM slots".

**Channels that returned nothing usable:** TigerDirect is **retired** (redirects to `td-sunset.html`; no listings exist). Back Market returned **Cloudflare HTTP 403**. ServerMonkey's Precision 7920 configurator only reaches 64 GB at roughly **$1,990**, over budget. Amazon, Walmart, Micro Center, B&H and Provantage were still being checked when this report was written.

### 4.0.1 A Z6 G4 build gotcha worth knowing

Straight from HP's QuickSpecs: **"Z6 G4 configurations that include greater than 32 GB total system memory require the HP Z6 Memory Cooling Solution"** (CTO part `2JA81AV` / AMO part `2HW44AA`), as do configurations with a second CPU. A **64 GB** Z6 G4 therefore needs that cooling shroud. Any 64 GB Z6 G4 already in service (including the recommended listing) has presumably had it fitted at build; a machine being built up from a bare chassis would not. Not priced in this pass.

### 4.1 The snippet-price trap, caught in the act

Listing [ebay.com/itm/800708151673](https://www.ebay.com/itm/800708151673) (the P720 dual Gold 6150) appeared in the eBay search results at **$619.88**. On the **fetched listing page** the price is **$714.88** for every variation. The $619.88 figure is not reproducible at the listing.

That is a **$95 discrepancy on a $700 purchase**, and it is exactly the failure mode the task warned about. Every price used in the recommendation below is FETCHED; the SEARCH-PAGE rows are included for breadth and are labelled as such.

**It is not confined to eBay, and on Newegg it is worse ΓÇö the snippet price belonged to a different SKU entirely.** Three examples caught in the parallel retail pass:

| Search snippet said | The fetched product page actually served |
|---|---|
| "$602.00 T5820 64 GB" | a **96 GB** SKU, **out of stock**, no price |
| "$523.00 Precision T3420 64 GB" | a **16 GB** SKU at $294.44 (64 GB is a *paid option* on that listing) |
| "$1,116.00 T7920 64 GB" | a **192 GB** SKU, **out of stock**, no price |

In the middle case the snippet advertised a 64 GB machine and the page sold a 16 GB one. **A snippet-only price is not evidence of a price.** This report therefore treats snippet prices as leads to chase, never as findings ΓÇö which is why rows N and O above are explicitly marked SEARCH-PAGE and excluded from the recommendation.

**One further warning, and it caught this report's own drafting.** Candidate **E** ΓÇö a Lenovo ThinkStation P520c, Xeon W-2140, 64 GB, 1 TB SSD + 2 TB HDD at **$487.00** ΓÇö appeared on a *fetched eBay search results page* and was briefly drafted as the cheapest complete 64 GB machine found. Re-checking its own listing page returned **HTTP 404: the listing no longer exists.** The price was therefore withdrawn and candidate E struck from the recommendation.

So the failure mode is not limited to search-engine snippets: **an eBay search-results page can render a price for a listing that is already gone.** Even a genuinely fetched search page is evidence about the index, not about the listing. Accordingly:

- The **headline recommendation and all three fallbacks rest on prices read from the listings' own product pages**, re-checked on 2026-10-12.
- Rows marked **SEARCH-PAGE** in the table are retained for market breadth only, and none is load-bearing.

---

## 5. Idle power and noise ΓÇö what is actually known

### 5.1 Idle watts: NOT FOUND for the recommended machines ΓÇö but now bracketed by real measurements

This is the weakest part of the evidence, and it is worth saying so plainly rather than papering over it.

- **HP QuickSpecs for the Z6 G4** (71-page PDF, fetched in full) declares **noise** emissions in accordance with ISO 7779 / ISO 9296, but contains **no power-consumption table at all**. Its only wattage figures are per-add-in-card (e.g. the dual 10 GbE module at 5.5 W at 1 Gbps, 11.2 W at 10 Gbps).
- **ENERGY STAR's certified-computers product finder** does publish idle watts and TEC (kWh/yr) ΓÇö but its detail pages are **JavaScript-rendered** and return only "Loading product detailsΓÇª" to a plain fetch, and the `/export/pdf/download` endpoint returned **HTTP 404**.

**However**, the full ENERGY STAR dataset *is* downloadable directly, and querying it closed part of the gap. Source: **ENERGY STAR Certified Computers V9.0**, EPA, published on data.gov, catalog last checked 2026-10-11, dataset last updated 2026-10-10 ΓÇö CSV at `https://data.energystar.gov/api/v3/views/rxdj-2c88/export.csv?accessType=DOWNLOAD` (1,257,069 bytes; 1,839 rows; columns include **`Long Idle (watts)`** and **`Short Idle (watts)`**, which are measured, not modelled).

**The one 64 GB machine it covers:**

| Model | CPU | RAM | **Long Idle** | Short Idle | Sleep | Off | TEC |
|---|---|---|---|---|---|---|---|
| HP EliteDesk 800 G6 Desktop Mini PC | Core i9-10900T (10C/20T) | **64 GB** | **6.2 W** | **10.5 W** | 1.5 W | 0.9 W | 40.1 kWh/yr |

**And the anchors it gives for current-generation workstations**, which bracket what a Z6 G4 or P720 should be expected to draw:

| Model | CPU | **Long Idle** | TEC |
|---|---|---|---|
| HP Z8 Fury G6i (dual-socket class) | Xeon 698X | **138.7 W** | 84.5 kWh |
| Lenovo ThinkStation P5 Gen 2 | Xeon 678X | **132.4 W** | 82.8 kWh |
| Lenovo ThinkStation P4 | Ryzen 9 PRO 9965X3D | 66.2 W | 38.3 kWh |
| Lenovo ThinkStation P3 Ultra SFF G2 | Core Ultra 9 285K | 38.6 W | 22.4 kWh |
| Lenovo ThinkStation P3 Tiny Gen 2 | Core Ultra 9 285 | **12.4 W** | 11.7 kWh |

**What this buys the analysis.** It shows the 60/90/130 W sweep in Section 6 is anchored in reality rather than invented: a **large dual-socket workstation idles at 132ΓÇô139 W**, a compact SFF workstation at ~39 W, and a tiny at ~12 W. A single-socket 20-core Z6 G4 sits between the SFF and the dual-socket figures, which is exactly the 60ΓÇô130 W band tested. Notably, **the 130 W column ΓÇö the one that still pays back in month 7 ΓÇö is the *pessimistic* end, not the optimistic one.**

**But the recommended machines themselves remain NOT FOUND.** The V9.0 dataset only covers models certified under the current V9.0 specification (effective 2025-10-27), so it does not contain the 2017ΓÇô2019 Xeon Scalable machines; the broader historical dataset (`j7nq-iepp`) returns `authentication_required`. **No idle figure for the Z6 G4, P720, P520 or P520c is asserted anywhere in this report.**

The estate's own reference figures, which the task supplied, complete the picture:

| Class | Idle draw | Basis |
|---|---|---|
| HP EliteDesk 800 G6 Mini, 64 GB | **6.2 W long idle / 10.5 W short idle** | **ENERGY STAR measured (this pass)** |
| Dell OptiPlex 3070/7070 Micro | ~10ΓÇô13 W | estate reference |
| HP EliteDesk 800 G4 Mini | 11.35 W | published by HP |
| HP Z440-class workstation | 100ΓÇô110 W | estate reference |
| Rack server | 125ΓÇô252 W | estate reference |

Because the recommended machines sit between the Z440 class and the mini class, **Section 6 computes TCO as a function of wattage** rather than asserting a single figure. That way the conclusion can be checked against a real measurement later without redoing the analysis.

### 5.2 Noise: the Z6 G4 is genuinely quiet

Published by HP (ISO 7779 / ISO 9296), from the Z6 G4 QuickSpecs:

| Configuration | Idle ΓÇö Sound Power (LwAd, bels) | Idle ΓÇö Deskside Sound Pressure (LpAm, dBA) | HDD operating |
|---|---|---|---|
| Entry | **3.3** | **15** | 3.5 bels / 18 dBA |
| Mid-range | 3.8 | 23 | 3.9 bels / 23 dBA |
| High-end | 3.8 | 23 | 3.9 bels / 24 dBA |

**15ΓÇô23 dBA at the deskside is quieter than normal office conversation**, which matters because the machine sits in a customer-facing office. This is a real point in the Z6 G4's favour and it is vendor-published, not a guess.

No noise figure was found for the P720, the P520 or the R7920. The R7920 is a 2U rack unit and should be assumed loud; that is a caveat, not a measurement.

---

## 6. Three-year TCO, on one consistent basis

### 6.1 Constants actually used

| Constant | Value | Verified? |
|---|---|---|
| Rent | **$102.99/month** as given | Hetzner list $101.49/mo (spendark, Jul 2026) ΓÇö consistent |
| NJ residential electricity | 24.95 ┬ó/kWh | as supplied (EIA, June 2026) |
| ΓåÆ 1 W continuous | 8.766 kWh/yr Γëê **$2.19/yr** | as supplied |
| ΓåÆ 100 W continuous | **$219/yr** | as supplied |
| ΓåÆ **1 W, one month** | **$0.1825** | derived |
| NJ sales tax | **6.625%** | **VERIFIED** ΓÇö NJ Division of Taxation: "New Jersey assesses a 6.625% Sales Tax on sales of most tangible personal property" ([nj.gov](https://www.nj.gov/treasury/taxation/businesses/salestax/index.shtml), page updated 2026-09-28). A computer is tangible personal property. |

Formula used:

```
3-year TCO = (price ├ù 1.06625) + (idle_watts ├ù 2.19 ├ù 3)
           = (price ├ù 1.06625) + (idle_watts ├ù 6.57)
breakeven_months = (price ├ù 1.06625) / (102.99 ΓêÆ idle_watts ├ù 0.1825)
```

### 6.2 The required three-way comparison

**Basis: 3 years (36 months), idle draw stated explicitly, NJ sales tax included on purchases, no sales tax assumed on the cloud subscription.**

| | Purchase (taxed) | Idle W assumption | Electricity, 3 yr | **3-year TCO** |
|---|---|---|---|---|
| **1. Stay on `secratary-cloud`** | ΓÇö | ΓÇö | ΓÇö | **$3,707.64** (36 ├ù $102.99) |
| **2. Best value ΓÇö HP Z6 G4, 20C/40T, 64 GB ΓÇö $469.99** | $501.13 | 60 W (optimistic) | $394.20 | **$895.33** |
| | | **90 W (mid ΓÇö used for the headline)** | **$591.30** | **$1,092.43** |
| | | 130 W (pessimistic) | $854.10 | $1,355.23 |
| | | 200 W (very pessimistic) | $1,314.00 | $1,815.13 |
| **3. Best spec-in-budget ΓÇö Lenovo P720, 40C/80T, 64 GB, 1 TB SSD ΓÇö $714.88** | $762.24 | 60 W | $394.20 | **$1,156.44** |
| | | **90 W (mid)** | **$591.30** | **$1,353.54** |
| | | 130 W | $854.10 | $1,616.34 |
| | | 200 W | $1,314.00 | $2,076.24 |
| | | 250 W | $1,642.50 | $2,404.74 |

**Even the worst case in the table ΓÇö a 40-core dual-Xeon workstation pulling 250 W idle for three straight years ΓÇö still lands $1,300 under renting.** The conclusion is not fragile to the electricity assumption. That is the key robustness result: the rent-versus-buy decision is dominated by the *rent*, not by the *watts*.

### 6.2.1 The cheapest-to-run option, and why it barely matters

The single lowest measured idle draw found anywhere in this pass is the **HP EliteDesk 800 G6 Desktop Mini PC with 64 GB and a Core i9-10900T: 6.2 W long idle, 10.5 W short idle** (ENERGY STAR measured). At 6.2 W it costs about **$41 over three years** in electricity.

Set against the Z6 G4's 90 W scenario ($591 over three years), the mini saves roughly **$550** on power ΓÇö but it gives up the 20C/40T Xeon for a 10C/20T mobile-class part, and it takes SODIMM memory, the form factor most exposed to the DRAM shortage.

**No 64 GB price for that machine was found** (eBay listings for the EliteDesk 800 G6 Mini in this pass were 8ΓÇô16 GB units at $204.99ΓÇô$349.99), so it is **not costed here and not recommended** ΓÇö but the arithmetic is worth internalising: **saving 84 W of idle buys about $550 over three years, while the difference between buying and renting is about $2,600 over the same three years.** Optimising watts is a rounding error next to the rent-or-own decision. Do not let the power question drive this choice.

### 6.3 Assumptions, stated honestly

- The 60/90/130/200/250 W figures are **scenario inputs, not measurements**. No published or measured idle figure was found for any recommended machine (Section 5.1). They are presented as a sweep precisely so the reader can substitute a real wall-meter reading. The recommendation does not depend on which one is right.
- "Idle" is not the whole truth: the task correctly notes a nightly backup job will not idle. A realistic average draw sits above idle. **The 90 W column is the one used for the headline** as a deliberate mid-point between a true idle and a real average; the 130 W and 200 W columns bound the realistic average case.
- Sales tax is added to the purchase. No sales tax is assumed on the Hetzner subscription; if NJ did tax it, add **$245.64** over three years and the case for buying gets *stronger*.
- No allowance is made for the Z6 G4's **missing SSD, GPU and OS**. It ships with none. Budget an NVMe SSD and an OS separately ΓÇö **not priced in this pass**, and deliberately not invented.
- No allowance for out-of-warranty failure, spare parts, a UPS, or off-site backup. Section 8 covers these as new costs.

---

## 7. Payback: at what month does buying beat renting?

`breakeven_months = purchase_taxed / (102.99 ΓêÆ 0.1825 ├ù idle_W)`

**Row 2 ΓÇö HP Z6 G4, $469.99 ($501.13 taxed)**

| Idle W | Monthly electricity | Net monthly saving vs rent | Breakeven | Verdict |
|---|---|---|---|---|
| 60 W | $10.95 | $92.04 | **5.44 ΓåÆ month 6** | |
| **90 W** | **$16.43** | **$86.56** | **5.79 ΓåÆ month 6** | **headline** |
| 130 W | $23.73 | $79.26 | **6.32 ΓåÆ month 7** | |
| 200 W | $36.50 | $66.49 | 7.54 ΓåÆ month 8 | |
| 300 W | $54.75 | $48.24 | 10.39 ΓåÆ month 11 | |
| **335 W** | **$61.14** | **$41.85** | **11.98 ΓåÆ still month 12** | **the 12-month cliff** |

**Row 2 beats renting inside month 6ΓÇô7 on any plausible draw. It only fails the 12-month test above ~335 W idle ΓÇö which no single-socket workstation reaches.**

**Row 3 ΓÇö Lenovo P720, $714.88 ($762.24 taxed)**

| Idle W | Monthly electricity | Net monthly saving | Breakeven |
|---|---|---|---|
| 60 W | $10.95 | $92.04 | 8.28 ΓåÆ month 9 |
| **90 W** | **$16.43** | **$86.56** | **8.81 ΓåÆ month 9** |
| 130 W | $23.73 | $79.26 | 9.62 ΓåÆ month 10 |
| 200 W | $36.50 | $66.49 | 11.46 ΓåÆ month 12 |
| **216 W** | **$39.42** | **$63.57** | **11.99 ΓåÆ still month 12** |
| 250 W | $45.63 | $57.36 | 13.29 ΓåÆ month 14 ΓÇö **fails** |

**Does it survive after electricity is added? Yes, comfortably, for both.** Electricity is a real drag ΓÇö it adds roughly $394ΓÇô$854 over three years ΓÇö but it is between a tenth and a quarter of what renting the same three years costs. Adding electricity moves the Z6 G4's payback from month 5 (ignoring power) to **month 6ΓÇô7**; it does not threaten the conclusion.

### 7.1 Is any candidate under 12 months *including* electricity?

**Yes ΓÇö precisely named: the HP Z6 G4 Workstation with 1├ù Intel Xeon Gold 6138, 64 GB RAM, at $469.99 from eBay item 336423407903.** Payback **month 6** at 90 W idle, **month 7** at 130 W idle, and it stays inside 12 months all the way up to **335 W** idle.

The same is true of the cheaper 64 GB ThinkStation ΓÇö the **P520 with W-2135 at $499.99** (taxed $533.12) pays back in about **month 6ΓÇô7** ΓÇö and of the **P720 at $714.88** up to **216 W** idle. (The $487.00 P520c that briefly looked cheapest was withdrawn: its listing now 404s ΓÇö see Section 4.1.)

---

## 8. Three honest answers

### 8.1 Is there a candidate with payback under 12 months including electricity?

**Yes: the HP Z6 G4 / Xeon Gold 6138 / 64 GB at $469.99 (eBay item 336423407903, observed 2026-10-12).** Month 6 at 90 W, month 7 at 130 W, and it holds inside 12 months up to 335 W idle. Runner-up on payback and the most *complete* machine: **Lenovo ThinkStation P520 / W-2135 / 64 GB / 512 GB SSD / Win 11 Pro at $499.99** ([item 307174416566](https://www.ebay.com/itm/307174416566)), about month 6ΓÇô7 ΓÇö and unlike the Z6 G4 it needs no storage or OS added.

### 8.2 What does $102.99/month actually buy that a self-owned machine does not?

Stated fairly, and not as advocacy for either side:

- **A public, static, provider-owned IP address** with reverse DNS, that is not tied to a residential connection whose address can change and whose ISP may block inbound ports or forbid servers outright in its terms.
- **DDoS protection** at the network edge ΓÇö the provider absorbs volumetric attacks before they reach the machine. A self-hosted box on a shop's internet connection simply goes down, and takes the shop's phones and card terminal with it.
- **2 TB/month of egress** on a multi-homed datacentre uplink. The shop's own connection has an upload cap and a much narrower pipe, and it is shared with everything else the business does.
- **Redundant power** ΓÇö UPS and generator on the provider's side. **Redundant cooling** and a controlled environment. **Physical security**: locked racks, access control, staff on site.
- **Hardware failure response.** A failed disk or PSU at 3am is a Hetzner ticket and a hardware swap. Self-owned, it is the owner driving to the shop.
- **Someone else patching the host, the hypervisor and the network.** The owner patches the guest, not the platform.
- **The box answers at 2am when the shop is closed.** This is the one the task named and it is the most underrated. A cloud VM does not care that it is 2am, that the shop's power is out, that the ISP is down, or that the owner is asleep.

**Against that:** the box is now genuinely expensive to rent relative to its spec, the June 2026 hike was 173% in one step, the tier is exposed to further DRAM-driven increases, the 160 GB disk is small for a 24 GB growing database, and the dedicated-vCPU tier is precisely the tier Hetzner is repricing hardest. Renting has stopped being obviously cheap.

### 8.3 If he buys the best candidate ΓÇö what new recurring costs and new work does he personally take on?

**New recurring costs:**

1. **Electricity**: roughly **$11ΓÇô$24/month** at 60ΓÇô130 W idle, materially more under load. This is the cost the rent used to hide inside the subscription.
2. **Off-site backup.** Today the provider's infrastructure is implicitly the safety net. Self-owned, there is no equivalent until it is bought ΓÇö a Storage Box, B2 bucket or equivalent. **Not priced in this pass; it is a real new line item, not zero.**
3. **Domain / DNS** if he fronts the service with a tunnel. Small, but new.
4. **A UPS / battery backup**, or the machine dies with the shop's power. Not priced here.
5. **Spare parts and ideally a spare machine.** Used hardware out of warranty means a cold spare SSD, RAM and PSU, or a whole second box, to hit the uptime he currently gets for free.
6. **The Z6 G4 specifically ships with no SSD, no GPU and no OS** (item 336423407903). Those must be bought before it runs anything.

**New ongoing work, all of it his:**

- OS and kernel patching, and reboots he has to schedule himself.
- Monitoring: disk health/SMART, memory errors (ECC correctable-error counts matter on a 64 GB used workstation), temperatures, free space.
- Backup verification ΓÇö a backup nobody has test-restored is not a backup.
- **Physical presence.** A failed disk, a fan, a PSU, or a stuck boot is now a trip to the shop, at whatever hour it happens.
- **Being the DDoS and abuse-response team.** Residential or small-business internet does not absorb a volumetric attack; the whole shop's connectivity is the blast radius.
- **The migration itself**, and the risk window during it. This argues for running the new machine in parallel ΓÇö not cutting over ΓÇö for at least a full month.
- **The renewal decision.** He will now be choosing to spend his own time every time something breaks, rather than paying Hetzner to do it.

**A blunt point the owner may not want to hear, but should.** His workload is one SQLite database (~24 GB), one FastAPI process, and a nightly backup, with memory use of 3ΓÇô7 GB. **That is not a 40-core workload, and it is not even a 20-core workload.** The 64 GB is defensible as future-proofing while preinstalled RAM is far cheaper than postinstalled RAM in this market, and the 24 GB-and-growing database does argue for more headroom than 16 GB. But the performance gain he actually *feels* will come from **NVMe I/O and single-thread speed**, not from core count. The 40C/80T P720 (candidate B) is therefore the wrong purchase for him ΓÇö it is twice the money for cores he cannot use, and probably 2├ù the idle power. The **$469.99 Z6 G4 is both the cheapest and the best-matched recommendation**, and its 20C/40T is already several times more parallel throughput than this workload can consume. If he wants to spend more, the honest upgrade is *more RAM and better NVMe*, not more cores.

One counter-note for fairness: the CCX23's 4 vCPUs are modern AMD cores, and Xeon Gold 6138 is a 2017 Skylake-SP part at 2.0 GHz base. **The cloud box may well win on single-thread latency per request.** The workstation wins on parallel throughput, RAM headroom, disk capacity and I/O ΓÇö not on single-thread.

---

## 9. What could not be established (NOT FOUND)

Listed so the gaps are auditable rather than hidden:

| Question | Status |
|---|---|
| Idle watts, any recommended workstation (Z6 G4, P720, P520, P520c, Precision 5820, R7920) | **NOT FOUND** ΓÇö no published or independently measured figure located. HP's Z6 G4 QuickSpecs contains no power table; ENERGY STAR detail pages are JS-rendered and its PDF export returned 404. **Partially bracketed** by real ENERGY STAR measurements of other machines (Section 5.1); the historical dataset that would cover these models requires authentication. |
| Idle watts, HP EliteDesk 800 G6 Mini 64 GB | **FOUND** ΓÇö 6.2 W long idle, 10.5 W short idle (ENERGY STAR measured) |
| Price of a 64 GB HP EliteDesk 800 G6 Mini | **NOT FOUND** ΓÇö only 8ΓÇô16 GB units were found on eBay |
| Noise, P720 / P520 / P520c / Precision 5820 / R7920 | **NOT FOUND** |
| Price of the Z6 G4's required SSD, GPU and OS | **NOT FOUND / not priced** ΓÇö deliberately not invented |
| Cost of off-site backup, UPS, spare parts | **NOT FOUND / not priced** |
| Dell Precision T7820 2├ù Gold 6130 64 GB price | **NOT RETRIEVABLE** ΓÇö listing page returned HTTP 403 |
| Retail-channel prices (Newegg, Amazon, Micro Center, B&H, Walmart, Back Market, ServerMonkey, PCLiquidations, TigerDirect, Provantage) | **PARTIAL.** Newegg: covered, product pages fetched (Section 4.0). **Retired:** TigerDirect. **Blocked:** Back Market (Cloudflare 403). **Over budget:** ServerMonkey (64 GB 7920 Γëê $1,990). **Still outstanding:** Amazon, Walmart, Micro Center, B&H, PCLiquidations, Provantage |

---

## 10. Recommendation

**Buy the HP Z6 G4 Workstation with 1├ù Intel Xeon Gold 6138 (20C/40T) and 64 GB RAM at $469.99** ΓÇö eBay item [336423407903](https://www.ebay.com/itm/336423407903), price observed 2026-10-12 on a fetched listing page with the 64 GB variation confirmed in the listing's own dropdown. Add an NVMe SSD and an OS. Attach it to a UPS. Buy an off-site backup target on day one.

- **3-year TCO: ~$1,092** at 90 W (vs **$3,708** renting) ΓÇö a saving of roughly **$2,600**.
- **Breakeven: month 6.** Still inside 12 months even at 335 W idle.
- **Noise: published at 15ΓÇô23 dBA** ΓÇö quiet enough for a customer-facing office.
- **Sell the reasoning, not just the number:** this only became true in **June 2026**, when Hetzner raised CCX23 by **173%** on the DRAM shortage. At the pre-hike price the cloud box was the better deal.

**Do not cancel `secratary-cloud` on purchase.** Run the new machine in parallel for a full month, with the nightly backup job duplicated and one test restore completed, before cancelling. The $102.99 buys a public IP, DDoS absorption, 2 TB of egress, redundant power and cooling, physical security, and hardware response at 2am ΓÇö all of which become the owner's problem the day the subscription ends.

**If the $469.99 listing is gone when he reads this** ΓÇö it is a one-off used listing and may sell ΓÇö the fallback order is:

1. **Lenovo ThinkStation P520, Xeon W-2135, 64 GB, 512 GB SSD + K620 + Win 11 Pro ΓÇö $499.99** ([item 307174416566](https://www.ebay.com/itm/307174416566), verified on its own page 2026-10-12). Complete and ready to run ΓÇö no storage or OS to add. 6C/12T; payback about month 6ΓÇô7.
2. **Newegg P520, W-2135, 64 GB, no storage/OS ΓÇö $597.98** ([newegg.com/p/2NS-000M-05VH1](https://www.newegg.com/p/2NS-000M-05VH1)). The only *retail* option with a returns process and real stock, at the cost of 6C/12T and needing storage and an OS added.
3. **Lenovo ThinkStation P720, 2├ù Xeon Gold 6148, 40C/80T, 64 GB, 1 TB SSD ΓÇö $714.88** ([item 236603584348](https://www.ebay.com/itm/236603584348)). Only if he genuinely expects to grow into 40 cores; see the caution in Section 8.3.

All three still pay back inside 12 months including electricity. **The recommendation is not sensitive to which one he lands on ΓÇö it is sensitive to him still paying $102.99/month.**

---

## 11. Sources

**Cloud baseline**
- Hetzner CCX23 list price ΓÇö https://spendark.com/instances/ccx23/ (prices checked July 2026)
- Hetzner General Purpose (spec, US 2 TB traffic allowance) ΓÇö https://www.hetzner.com/cloud/general-purpose/
- Hetzner 2026 price hikes, CCX23 Γé¼31.49 ΓåÆ Γé¼85.99 (+173%) ΓÇö https://bex.co/blog/2026/07/20/hetzner-2026-price-hikes-self-hosting-math (2026-07-20)
- Hetzner April 2026 price statement ΓÇö https://www.hetzner.com/pressroom/statement-price-adjustment/
- Hetzner price-adjustment docs (15 June 2026, grandfathering/rescale) ΓÇö https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/

**Cost constants**
- NJ sales tax 6.625% ΓÇö https://www.nj.gov/treasury/taxation/businesses/salestax/index.shtml (page updated 2026-09-28)
- DRAM contract prices +90ΓÇô95% QoQ, Q1 2026 (TrendForce) ΓÇö https://www.digitaltoday.co.kr/en/view/43759/chip-prices-set-to-rise-again-amid-supply-shortage-and-higher-oil-costs (published 2026-03-30)

**Candidates (all observed 2026-10-12)**
- HP Z6 G4, Xeon Gold 6138, 64 GB, $469.99 ΓÇö https://www.ebay.com/itm/336423407903
- Lenovo ThinkStation P720, 2├ù Xeon Gold 6148, 64 GB, 1 TB SSD, $714.88 ΓÇö https://www.ebay.com/itm/236603584348
- Lenovo ThinkStation P720, 2├ù Xeon Gold 6150, 64 GB, $714.88 ΓÇö https://www.ebay.com/itm/800708151673 *(showed $619.88 in search snippet ΓÇö not reproducible)*
- Dell Precision 5820, W-2235, 64 GB, $660.00 ΓÇö https://www.ebay.com/itm/820135616854
- Lenovo ThinkStation P520, W-2135, 64 GB, **$499.99** ΓÇö https://www.ebay.com/itm/307174416566 *(verified on its own page 2026-10-12)*
- ~~Lenovo ThinkStation P520c, W-2140, 64 GB, $487.00 ΓÇö https://www.ebay.com/itm/190560902133~~ *(WITHDRAWN ΓÇö listing page returns HTTP 404; price not reproducible)*
- Lenovo ThinkStation P520, W-2225, 64 GB, $504.00 ΓÇö https://www.ebay.com/itm/187971125861
- Lenovo ThinkStation P520, W-2245, 64 GB, $720.91 ΓÇö https://www.ebay.com/itm/177777995801
- Dell Precision R7920, 2├ù Xeon Gold 5120, 64 GB, $1,149.99 ΓÇö https://www.ebay.com/itm/167503533177
- Dell Precision 7820, 2├ù Xeon Gold 6226, 16 GB, $597.52 ΓÇö https://www.ebay.com/itm/397802924863

**Retail channels (observed 2026-10-12)**
- Newegg, Lenovo P520 W-2135 64 GB ΓÇö https://www.newegg.com/p/2NS-000M-05VH1
- Newegg, HP Z6 G4 Xeon Silver 4114 64 GB ΓÇö https://www.newegg.com/p/2NS-0006-3HW74
- Newegg, HP Z840 2├ù E5-2687W v3 64 GB ΓÇö https://www.newegg.com/hp-z-series-z840/p/1VK-001E-3PNG1

**Specifications, noise, power**
- HP Z6 G4 Workstation QuickSpecs (71 pp; "Declared Noise Emissions", ISO 7779 / ISO 9296; full processor support table incl. Platinum 8180 28C; second CPU & memory riser) ΓÇö https://www.workstation4u.de/hp-z6-g4-quickspecs.pdf
- ENERGY STAR certified computers product finder (JS-rendered; no idle data retrievable this pass) ΓÇö https://www.energystar.gov/productfinder/product/certified-computers/
- **ENERGY STAR Certified Computers V9.0 dataset** (EPA, via data.gov; 1,839 rows; measured `Long Idle (watts)` / `Short Idle (watts)`; catalog checked 2026-10-11, dataset updated 2026-10-10) ΓÇö https://catalog.data.gov/dataset/energy-star-certified-computers-v9-0 ┬╖ CSV: https://data.energystar.gov/api/v3/views/rxdj-2c88/export.csv?accessType=DOWNLOAD

---

*Research only. Nothing was purchased, no seller was contacted, no money was committed, and no file outside this report was modified.*
