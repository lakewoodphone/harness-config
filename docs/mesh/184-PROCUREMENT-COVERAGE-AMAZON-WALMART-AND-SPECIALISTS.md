# 184 — Procurement coverage: Amazon, Walmart, Micro Center, B&H, Provantage and the refurb specialists

**Date of research:** 2026-10-12
**Host:** `zabz-tech` (Windows desktop node — same host as report 181)
**Repo written and committed in:** `C:\Users\ezabz\Code\harness-config`
**Scope:** research only. Nothing purchased, no seller contacted, no money committed.
**This report closes the gap named in `181-PROCUREMENT-64GB-RESEARCH.md` §4.0 and §9.** Nothing already concluded in 181 about eBay or Newegg is re-litigated here.

---

## 1. Bottom line

**No retailer newly covered in this pass beats the $469.99 eBay HP Z6 G4.** Not Amazon, not Walmart, not Micro Center, not B&H, not Provantage, and not one of the six refurb specialists.

**But the under-$300 question has a real, non-obvious answer, and it is a cautionary one.** Exactly one listing with **64 GB and a Xeon, under $300**, was found at any retailer: a **refurbished HP Z420 Tower at Walmart ($223.50–$258.00)**. Its own page, re-fetched three times on 2026-10-12, served **two different prices and an "Not available" availability string every time**, and the structured product record says **OUT_OF_STOCK with zero fulfillment options and no seller**. So the honest answer is:

> **Under $300 there is no 64 GB machine you can actually buy from a reputable retailer.** There is one listing that *advertises* it, and that listing is not purchasable and cannot be pinned to a price.

**The real floor is $358.99** — an Amazon Renewed **Dell Precision T5810, Xeon E5-2680 v3 (12C/24T), 64 GB DDR4, 480 GB SSD, no OS**, fetched from its own product page, "Only 6 left in stock", sold by Aventis Systems. That is a buyable machine. It is still **worse value than the $469.99 Z6 G4** — see §5.

**And on the Z420 itself:** it is a 2012 Sandy/Ivy-Bridge machine. HP's own QuickSpecs put its **Windows Idle (S0) draw at 50.0 W**, which is genuinely good, but its single-thread performance is roughly half the Z6 G4's and it caps out at 8 DIMMs / 64 GB with no real upgrade path. It is cheap because it is old, not because it is a bargain.

**Correction to report 181: none.** The recommendation stands, and this pass strengthens it — because the price floor for *any* 64 GB workstation at retail turned out to be higher than the Z6 G4, not lower.

---

## 2. Evidentiary standard (same as 181, deliberately)

Every price is tagged:

- **FETCHED** — read off the listing's or product's **own page**, retrieved and parsed by this session.
- **SEARCH-PAGE** — read off a search-results grid that this session retrieved, but the listing's own page was not opened.
- **SNIPPET-ONLY** — appeared only in a search-engine snippet. **No conclusion in this report rests on a snippet-only price.**

Prices observed **2026-10-12**. Where a page was re-fetched, the discrepancy is reported rather than smoothed over (§4.2) — that is the whole point of the marking scheme.

---

## 3. The candidate table — everything found across the newly covered retailers

Sorted by price. "Idle W" is a **published** figure where one exists, and **NOT FOUND** where none does. Nothing here is estimated silently.

| # | Retailer | Machine | CPU | C/T | RAM | Storage | Price | Basis | URL | Idle W |
|---|---|---|---|---|---|---|---|---|---|---|
| **1** | **Walmart** | HP Z420 Tower (refurb) | Intel Xeon 3.60 GHz (**exact SKU not stated**) | n/s | **64 GB DDR4** | 120 GB SSD + Win 10 Pro | **$223.50** *(also served $258.00 — see §4.2)* | **FETCHED.** But the same page also returned `"Not available"` and the structured record says **OUT_OF_STOCK**, seller `null`, all three fulfillment modes `NOT_AVAILABLE` | [walmart.com/ip/865588126](https://www.walmart.com/ip/HP-Workstation-Z420-Tower-PC-Intel-Xeon-3-60GHz-64GB-120GB-SSD-Windows-10-Pro-REFUBISHED/865588126) | **50.0 W** — HP Z420 QuickSpecs, Windows Idle (S0) ([PDF](https://h30434.www3.hp.com/psg/attachments/psg/Business-PC-Workstation-POS/39701/1/2013.4%20Z420%20QuickSpecs%20v17.pdf)) |
| **2** | **Amazon** | Dell Precision **T5810** (Renewed) | Xeon E5-2680 v3 2.5 GHz | 12 / 24 | **64 GB DDR4** | 480 GB SSD + Quadro NVS 315, **no OS** | **$358.99** | **FETCHED** product page; "Only 6 left in stock"; seller **Aventis Systems** | [amazon.com/dp/B07V5KL5MK](https://www.amazon.com/dp/B07V5KL5MK) | **NOT FOUND** |
| **3** | **Amazon** | PCSP P520C Tower (Renewed) | Xeon **W-2145** | 8 / 16 | **16 GB** — *not 64* | none + P620 | $357.12 | **FETCHED** search page. **Listed for completeness only — it is not a 64 GB machine at any price.** | [amazon.com/dp/B0G7L29ZJD](https://www.amazon.com/dp/B0G7L29ZJD) | **NOT FOUND** |
| **4** | **Amazon** | PCSP Z2 G4 Tower (Renewed) | Xeon E-2124G | 4 / 4 | **16 GB** — *not 64* | 512 GB NVMe + Win 11 Pro | $374.28 | **FETCHED** search page. Not 64 GB. | [amazon.com/dp/B0BSB1F4DS](https://www.amazon.com/dp/B0BSB1F4DS) | **NOT FOUND** |
| **5** | **Amazon** | Dell Precision **5820** Tower (Renewed) | Xeon W-2123 3.6 GHz | 4 / 8 | **64 GB DDR4** | 1 TB NVMe + P2000 + Win 11 | **$500.00** | **FETCHED** product page; "Only 6 left in stock"; seller PC Server and Parts Certified Refurbished | [amazon.com/dp/B09SNSQ42R](https://www.amazon.com/dp/B09SNSQ42R) | **NOT FOUND** |
| **6** | **Back Market** | Dell Precision 5820 Tower (refurb) | Core i7 3.8 GHz | n/s | **64 GB** | 256 GB SSD | **$657.00** | **FETCHED** search page (own page not opened) | [backmarket.com](https://www.backmarket.com/en-us/search?q=Dell%20Precision%205820) | **NOT FOUND** |
| **7** | **Back Market** | Dell Precision 5820 (refurb) | Core i9 3.3 GHz | n/s | **64 GB** | 256 GB SSD | **$884.00** | **FETCHED** search page | same | **NOT FOUND** |
| **8** | **Micro Center** | HP Z2 G5 SFF Workstation (Refurbished) | Core i5-10600 3.3 GHz | 6 / 12 | **32 GB** — *not 64* | 2 TB + NVIDIA T400 | **$699.99** | **FETCHED** product page. **Micro Center's best refurbished workstation does not reach 64 GB.** | [microcenter.com/product/711099](https://www.microcenter.com/product/711099/hp-z2-g5-sff-workstation-(refurbished)) | **NOT FOUND** |
| **9** | **Micro Center** | Dell Precision 3431 SFF (Refurbished) | Core i5-9500 | 6 / 6 | **16 GB** | 512 GB | $349.99 | **FETCHED** product page | [microcenter.com/product/707191](https://www.microcenter.com/product/707191/dell-precision-3431-sff-workstation-desktop-(refurbished)) | **NOT FOUND** |
| **10** | **Wisetek Market** | Dell Precision 5820 Tower (Refurb — Fair) | Core i9-10900X 3.7 GHz | 10 / 20 | **64 GB DDR4** | 256 GB SSD + Win 11 Pro | **$789.00** | **FETCHED** product page. **Stock: Unavailable.** | [wisetekmarket.com](https://www.wisetekmarket.com/products/dell-precision-5820-tower-64gb-256gb-ssd-i9-10900x-3-70ghz-win11p-black-refurbished-fair) | **NOT FOUND** |
| **11** | **Back Market** | HP **Z8 G4** Workstation (refurb) | Xeon 1.8 GHz | n/s | **64 GB** | 2 TB SSD | **$1,458.00** | **FETCHED** search page | [backmarket.com](https://www.backmarket.com/en-us/search?q=workstation%2064GB) | **NOT FOUND** |
| **12** | **ServerMonkey** | Dell Precision **7920** Tower (refurb, **configurator**) | up to 2× Xeon Scalable | — | **64 GB DDR4 LRDIMM 2666** | none — barebones | **$1,980.00** | **FETCHED** product page. Base $1,340 (no CPU, no RAM, no drives) **+ $640 for the 64 GB LRDIMM option**. | [servermonkey.com](https://www.servermonkey.com/refurbished-dell-precision-7920-tower-workstation.html) | **NOT FOUND** |
| **13** | **Amazon** | Dell Precision **7920** Tower (Renewed) | 2× Xeon Gold 6136 | 24 / 48 | **64 GB DDR4** | no drives, no OS | **$1,996.95** | **FETCHED** product page; seller PCSP; **stock: "Currently unavailable"** | [amazon.com/dp/B0B3FBV1CM](https://www.amazon.com/dp/B0B3FBV1CM) | **NOT FOUND** |
| **14** | **Amazon** | Lenovo ThinkStation **P920** (Renewed) | 2× Xeon Gold 6136 | 24 / 48 | **64 GB DDR4** | 250 GB NVMe + P4000 + Win 11 Pro | **$2,449.50** | **FETCHED** product page; seller **Lenovo** | [amazon.com/dp/B0C4G1SL42](https://www.amazon.com/dp/B0C4G1SL42) | **NOT FOUND** |

**Rows 3 and 4 are recorded only to document what the search grid actually served.** They are 16 GB machines and the reasoning in 181 §4.1 about snippet prices cutting the other way applies: a "$357 Xeon workstation" is not a $357 64 GB workstation.

---

## 4. Retailer-by-retailer

### 4.1 Amazon — FETCHABLE, and the strongest of the new channels

Amazon product pages **were** retrievable in full this session (product title, buy-box price, seller name and stock string all parsed). This is a change from the *search-grid* experience: the plain HTML fetch returned only navigation chrome, and the pages had to be read through a rendering proxy.

**What Amazon actually stocks in this class is not competitive on price.** Renewed workstations with 64 GB start at **$358.99** (T5810, 12C, complete and bootable apart from an OS) and climb steeply:

| Amazon 64 GB machine | Price | vs. $469.99 Z6 G4 |
|---|---|---|
| Dell T5810, E5-2680 v3 **12C/24T**, 480 GB SSD | $358.99 | **$111 cheaper, but 12C vs 20C and two generations older** |
| Dell 5820, W-2123 **4C/8T**, 1 TB NVMe, Win 11 Pro | $500.00 | $30 more, **4 cores vs 20** |
| Dell 7920, 2× Gold 6136 **24C/48T**, no drives/OS | $1,996.95 | $1,527 more |
| Lenovo P920, 2× Gold 6136 **24C/48T**, 250 GB NVMe | $2,449.50 | $1,980 more |

**Amazon also confirms the empty-chassis pattern.** Both the 7920 and the P520c are sold as renewed barebones with *no CPU or no storage*. The 7920 above is the mirror image of the ServerMonkey 7920 — Amazon's comes with both CPUs and 64 GB but no drives; ServerMonkey's comes with drives but no CPU and no RAM.

**Two of the Amazon listings are not purchasable at the price shown.** The 7920 ($1,996.95, PCSP) reports **"Currently unavailable"**; the Walmart Z420 reports the same in structured form. They are reported because the price is real, but neither can be bought today.

### 4.2 Walmart — one phantom under-$300 listing, and a price that will not hold still

**This is the most important negative finding in the report.**

The Walmart 64 GB refurbished set is small (7 results reported by the store's own structured search). Only two entries are desktop workstations with 64 GB; the rest are mobile workstations (Precision 3561/7560/7760/7770, ZBook Power 15 G1) at $648–$1,599.

The one desktop that matters is **item 865588126, "HP Workstation Z420 Tower PC Intel Xeon 3.60GHz 64GB 120GB SSD Windows 10 Pro -REFUBISHED"**. It was re-fetched **three times** on 2026-10-12:

| Fetch | Price served | Availability served |
|---|---|---|
| 1st (rendered page) | **$223.50** | `In Stock` |
| 2nd (structured product record) | **`null`** | **`OUT_OF_STOCK`**; all three fulfillment modes `NOT_AVAILABLE`; seller `null`; `web_item_available: false` |
| 3rd (rendered page) | **$258.00** | **`Not available`** |

**Three fetches, two prices, and an availability string that contradicts the first read.** The structured record — which is what drives the storefront's own checkout — reports no price, no seller and no fulfillment path.

**This is the same failure mode report 181 caught twice** (§4.1): the $487 P520c whose page had become a 404, and the $619.88 P720 that the listing page served as $714.88. Walmart has now produced a third instance: **a listing that a search grid will surface as a $223.50 64 GB machine and that the storefront itself will not sell.** No recommendation can rest on it, and no conclusion about "under $300" can rest on it either — which is precisely why the answer in §6 is *no*.

**Aside, and it is a good one:** the other Walmart Z420-family listings are third-party "gaming tower" conversions with **GTX 1060 / GTX 1650** cards, 64 GB, and a stated **"1 YEAR WARRANTY"**. Same chassis, same era, but with a discrete GPU and a returns path. Their prices did not render (`0`/null), so **no price is asserted for them** — they are a lead, not a finding.

### 4.3 Micro Center — refurbished workstations stop at 32 GB

Micro Center's refurbished catalogue was enumerated directly:

- Full refurbished-workstation search: **15 results**, all desktops/optiplexes/elitedesks between **$329.99 and $799.99**. Largest RAM on any of them: **32 GB** (the $699.99 HP Z2 G5 SFF).
- The SFF Precision 3431 at $349.99 is **16 GB**, confirmed on its own page.
- A `workstation 64GB` search returns **new** AI workstations ($1,699.99–$15,999.99), Apple Mac mini/Studio, GPUs and memory kits — no refurbished 64 GB desktop.
- An `hp z420` search returns **no Z420 at all** — the only HP refurbished workstation in the result set is the same $699.99 Z2 G5.

**Micro Center does not have a 64 GB refurbished workstation in this class, at any price.** Its floor is 32 GB for $699.99, which is **$230 more than the Z6 G4 for 12 fewer cores and half the RAM.** Micro Center is not a contender here.

One structural note worth recording: Micro Center's search indexes return `robots: noindex, nofollow` and a fixed store scope, so a national availability claim is weaker than it looks. **In-store-only stock at a store the owner does not live near is not stock.**

### 4.4 B&H Photo — no used 64 GB workstation exists in the used department

- **New workstations** (`workstation 64GB`, sorted by relevance): **18 results, every one between $1,359 and $18,618.95.** The 64 GB-capable ones are current-generation HP Z2/Z6/Z8 G1i/G5, Lenovo P5 Gen 2, NextComputing and Minisforum. The cheapest HP tower is **$4,332.80**; the cheapest 64 GB machine of any kind is the Minisforum MS-A2 at **$1,979.00**.
- **Used department** (`sts=used`): **6 results total, $299.99–$849.99** — an HP ProDesk 400 G5 Mini, a Dell OptiPlex 3070, a ThinkCentre M90n, a Mac mini, an Acer Aspire and an MSI Trident. **Not one is a 64 GB workstation, and not one is a workstation at all.**

**B&H's used department, the thing the task specifically asked about, holds nothing in this class.** B&H is a new-channel retailer for professional buyers, and its pricing reflects that. Not a contender.

### 4.5 Provantage — a genuine dead end this pass

Provantage is a parts-and-systems distributor; its search is a QuickFind service. **It could not be made to return workstation results.** Three separate attempts (a keyword query, a `Z6G4` token, and an `HP Z6 G4` phrase) returned **unrelated accessory SKUs** — USB hubs, surge protectors, a Tripp Lite cable, an open-frame rack — and a Lenovo product URL returned from a search-engine index came back **HTTP 404** on direct fetch.

**I am recording this as NOT ESTABLISHED, not as "Provantage is expensive".** The honest statement is: *Provantage could not be searched successfully in this pass; nothing is claimed about its prices.* Its catalogue is dominated by current-generation Lenovo P5/P7 SKUs where the index was reachable, and this estate's target is 2017–2019 Xeon Scalable hardware that a distributor of that shape is unlikely to carry refurbished — but that is inference, and it is labelled as inference.

### 4.6 The refurb specialists

| Specialist | Outcome |
|---|---|
| **ServerMonkey** | Reachable. Configurator is transparent and is the **single best specification source found for these chassis**: Dell 7920 base **$1,340** with no CPU / no RAM / no drives, **+$640 for a 64 GB DDR4 LRDIMM kit**, CPU options itemised down to a `+$5` Xeon Silver 4114. **64 GB config lands at $1,980.** Over budget. Its workstations landing page is `Contact for pricing` throughout. |
| **PCLiquidations** | Reachable, but the 64 GB machine does not exist in its catalogue. Its HP refurbished desktops are EliteDesk/ProDesk minis and SFFs, **8–16 GB, $152.99–$390.98**. No workstation with 64 GB. |
| **Back Market** | **Reachable this pass — it was not last time.** Report 181 recorded Back Market as Cloudflare-403-blocked; on 2026-10-12 both search and product pages rendered. Result: **its cheapest 64 GB machine is $657** (Dell 5820, 64 GB, 256 GB SSD), with a $1,458 HP Z8 G4 at the top. **Every one of the five cheapest 5820 listings on Back Market is an 8 GB machine ($520.99–$541.99)** — 64 GB is the *expensive* variant, not the default. |
| **TigerDirect** | **Still retired.** Report 181 recorded the redirect to `td-sunset.html`. No listings exist; nothing changed. |
| **eBay Refurbished (official channel)** | The `/e/refurbished/refurbished-workstations` landing page renders but surfaces only **one** product card (a *laptop* — Certified Refurbished Dell Precision 5530, $500.00). The program's landing pages are marketing surfaces, not a searchable inventory; **the eBay findings in report 181 already cover the listings this program would badge.** No new machine found. |
| **Wisetek Market** | Reachable. Dell 5820, i9-10900X, 64 GB, 256 GB SSD, **$789.00 — stock: Unavailable.** |

---

## 5. Does anything beat the $469.99 eBay HP Z6 G4?

**No. Not one listing found in this pass beats it on the combination that matters — price, core count and RAM together.**

The specific runner-ups, ranked by how close they come:

| Rank | Machine | Price | Why it does not beat the Z6 G4 |
|---|---|---|---|
| **1** | **Amazon Dell Precision T5810, E5-2680 v3, 12C/24T, 64 GB, 480 GB SSD — $358.99** | $111 cheaper | **The only *buyable* machine under $400 with 64 GB.** But it is a Haswell-EP part two generations older on a DDR4-2133 platform, **12 cores against 20**, and it ships with no OS. On throughput per dollar it loses to the Z6 G4's 20C/40T. It is a legitimate fallback if the Z6 G4 sells and budget dominates — but it is a downgrade, not an upgrade. |
| **2** | Amazon Dell 5820, W-2123, **4C/8T**, 64 GB, 1 TB NVMe, Win 11 Pro — $500.00 | $30 more | **Four cores for $30 more than twenty.** The 5820 is a good chassis with a bad CPU here and only 4 DIMMs of headroom. Clearly worse. |
| **3** | Walmart HP Z420, 64 GB — $223.50–$258.00 | $211–$246 cheaper | **Not purchasable** (see §4.2), and a 2012 platform. Even if it were, its single-thread performance is roughly half the Z6 G4's and it has no meaningful upgrade path. |
| **4** | Back Market Dell 5820, i7, 64 GB — $657.00 | $187 more | More money, unspecified CPU, no published idle figure, and only 256 GB of storage. |
| **5** | ServerMonkey Dell 7920, 64 GB barebones — $1,980.00 | $1,510 more | Dual-socket ceiling, but a barebones chassis that needs CPU, RAM *and* drives. |
| **6** | Micro Center HP Z2 G5 SFF, **32 GB** — $699.99 | $230 more | **Half the RAM** and 6 cores. Not the same class of machine. |
| **7** | Amazon Dell 7920 / Lenovo P920 (24C/48T, 64 GB) — $1,996.95 / $2,449.50 | 4–5× the price | 4 more cores than the Z6 G4 for four times the money. |

**The clearest single statement:** the cheapest *retail, warrantied, buyable* 64 GB workstation found anywhere in this pass is **$358.99** (Amazon), and the best *value* 64 GB workstation found anywhere across both passes is still the **$469.99 eBay Z6 G4** — which buys **12 more cores, ECC RDIMM support, and a documented 15–23 dBA deskside noise figure** for **$111 more**.

---

## 6. The under-$300 question, answered explicitly

> **Question: is there any machine at 64 GB with a strong CPU for under $300 anywhere reputable?**
>
> **Answer: No.**
>
> - **One listing advertises it** — the Walmart HP Z420 at $223.50–$258.00. Its own page served **two different prices and "Not available" on three fetches**, and the storefront's structured record says **OUT_OF_STOCK, no seller, no fulfillment path**. It cannot be bought and its price cannot be pinned.
> - **Every other 64 GB machine found at any retailer, at any price, is $358.99 or more.**
>
> **The floor is $358.99**, and it is a specific, buyable, FETCHED machine: **Amazon Renewed Dell Precision T5810, Xeon E5-2680 v3 12C/24T, 64 GB DDR4, 480 GB SSD, Quadro NVS 315, no OS**, [amazon.com/dp/B07V5KL5MK](https://www.amazon.com/dp/B07V5KL5MK), "Only 6 left in stock, order soon", seller Aventis Systems.
>
> **If "strong CPU" is taken to mean "same class as the Z6 G4's 20C/40T Xeon Gold 6138", the floor rises to $469.99** — the eBay Z6 G4 itself, which remains the cheapest 20-core-class 64 GB machine in either research pass.

**Why the floor sits where it does — and it is not a coincidence.** A 64 GB DDR4 ECC RDIMM kit is now a large fraction of a used workstation's price. ServerMonkey, a volume refurbisher, charges **$640 for the 64 GB option alone** on a $1,340 barebones 7920 — 48% of the chassis. That is the DRAM shortage report 181 documented (TrendForce, +90–95% QoQ on Q1-2026 contract prices) showing up directly in a configurator's line items. **Any machine sold below $300 with 64 GB installed is selling the RAM below what the RAM is worth**, which is exactly the shape of a listing that has gone stale, sold out, or was mispriced to begin with. The Walmart Z420 is that listing.

---

## 7. Correction to report 181's recommendation

**None. The recommendation stands, unchanged, and this pass strengthens it.**

Report 181 recommended: **buy the HP Z6 G4, Xeon Gold 6138, 20C/40T, 64 GB, at $469.99 (eBay item 336423407903)**, 3-year TCO ≈ **$1,092** at 90 W vs **$3,708** renting, breakeven **month 6**.

What this pass adds to that:

1. **The competitive field did not produce a cheaper same-class machine.** Five new retailers and six specialists were covered; the cheapest 64 GB machine at any of them is **$358.99**, and it is a 12-core two-generations-older machine.
2. **The $469.99 price is more defensible than it looked, not less.** The nearest retail equivalent with more RAM headroom costs **$1,980** (ServerMonkey) or **$1,996.95** (Amazon). The Z6 G4 is **~4× cheaper than either.**
3. **Retail's one advantage — warranty and returns — is real but narrow here.** Amazon Renewed and ServerMonkey both carry a returns path; eBay Refurbished and Walmart marketplace do too. The owner is paying roughly **$1,500** for that path at ServerMonkey. That is not a good trade for a $500 used machine.
4. **One honest strengthening of the Z420 caveat.** Report 181 §8.3 warned that the recommended Z6 G4 ships with no SSD, GPU or OS. **That remains the one real hidden cost**, and this pass priced nothing for it — deliberately. It is noted again so the omission stays visible.

**The one thing this pass would add to the fallback list**, if the owner's budget tightened rather than loosened: **the $358.99 Amazon T5810 is a better fallback than the $499.99 eBay P520 at the same core count**, because it is $141 cheaper and has 12 cores against 6 — at the cost of being two generations older and shipping without an OS. **It does not displace the Z6 G4 and should not.** It is a budget-floor option, and its 3-year TCO at 90 W idle is **$358.99 × 1.06625 + $591.30 = $974**, against the Z6 G4's **$1,092** — a $118 saving over three years for 8 fewer cores.

---

## 8. What could not be found, and why

| Question | Status |
|---|---|
| **Does any retailer actively block automated reading?** | **Mostly no.** Amazon (product pages), Walmart (search + item pages), Micro Center, B&H, ServerMonkey, PCLiquidations, Back Market and Wisetek all rendered. **Back Market blocked report 181 with a Cloudflare 403 and did not block this session** — the block was transient/policy-dependent, not permanent. **Two real read failures:** (a) **Reddit** refused the Firecrawl reader outright ("we do not support this site"), so community kill-a-watt measurements for the Z6 G4 could not be read; (b) **Provantage's QuickFind** returned unrelated accessory SKUs for every workstation query and a search-engine-indexed Lenovo product URL 404'd (see §4.5). **eBay search grid** intermittently failed on retry, and its under-$300 filtered grid returned 16 GB machines under a 64 GB query — a relevance failure worth knowing about. |
| Idle watts — **HP Z420** | **FOUND — 50.0 W**, "Windows Idle (S0)", from HP's own Z420 QuickSpecs (66-page PDF, fetched in full). This is a genuine published figure and the only new idle measurement this pass produced. |
| Idle watts — Z6 G4, T5810, 5820, 7920, P920, P520, Back Market 5820, Micro Center Z2 G5 | **NOT FOUND.** No published or independently measured figure was located for any of them. Report 181's ENERGY STAR bracketing (§5.1 of 181: 132–139 W dual-socket, 38.6 W SFF, 6.2 W mini) remains the only real anchor, and the Reddit threads that might have supplied Z-series measurements are unreadable to this toolset. |
| Noise — any newly covered machine | **NOT FOUND.** No ISO 7779 figure located for the T5810, 5820, 7920, P920, Z420 or the Z2 G5. |
| **Walmart Z420's price and availability** | **NOT RESOLVABLE.** Two prices ($223.50 / $258.00) and an `OUT_OF_STOCK` structured record across three same-day fetches. Reported as a range with the contradiction surfaced, never as a finding. |
| **Provantage prices** | **NOT ESTABLISHED.** Search could not be made to return workstation results (see §4.5). No price is claimed. |
| Idle watts or price for the Walmart Z420-family "gaming tower" variants with GTX 1060/1650 and a stated 1-year warranty | **NOT FOUND.** Prices did not render (`0`/null) on the search grid. Flagged as a lead only. |
| Cost of the Z6 G4's missing SSD, GPU and OS | **NOT PRICED**, deliberately — same omission as 181, and stated plainly so it stays visible. |
| Whether Micro Center has 64 GB stock at a store the owner could reach | **NOT ESTABLISHED.** Micro Center's search is store-scoped and `noindex`; national availability could not be confirmed. |

---

## 9. Sources

**Newly covered candidates (all observed 2026-10-12)**
- Walmart, HP Z420 Tower, 64 GB, $223.50–$258.00, **not purchasable** — https://www.walmart.com/ip/HP-Workstation-Z420-Tower-PC-Intel-Xeon-3-60GHz-64GB-120GB-SSD-Windows-10-Pro-REFUBISHED/865588126
- Amazon, Dell Precision **T5810**, E5-2680 v3 12C/24T, 64 GB, 480 GB SSD, **$358.99** — https://www.amazon.com/dp/B07V5KL5MK
- Amazon, Dell Precision **5820**, W-2123, 64 GB, 1 TB NVMe, Win 11, **$500.00** — https://www.amazon.com/dp/B09SNSQ42R
- Amazon, Dell Precision **7920**, 2× Gold 6136, 64 GB, no drives, **$1,996.95** (currently unavailable) — https://www.amazon.com/dp/B0B3FBV1CM
- Amazon, Lenovo ThinkStation **P920**, 2× Gold 6136, 64 GB, 250 GB NVMe, **$2,449.50** — https://www.amazon.com/dp/B0C4G1SL42
- Amazon, PCSP **P520c**, W-2145, **16 GB**, $357.12 — https://www.amazon.com/dp/B0G7L29ZJD
- Amazon, PCSP **Z2 G4**, E-2124G, **16 GB**, $374.28 — https://www.amazon.com/dp/B0BSB1F4DS
- Amazon electronics search, `workstation 64GB RAM renewed` — https://www.amazon.com/s?k=workstation+64GB+RAM+renewed&i=electronics
- Walmart search, `workstation 64GB RAM refurbished` — https://www.walmart.com/search?q=workstation%2064GB%20RAM%20refurbished
- Walmart, **Restored HP Z640**, 8 GB, $239.00 — https://www.walmart.com/ip/5400515235
- Micro Center, refurbished workstation search — https://www.microcenter.com/search/search_results.aspx?Ntt=refurbished+workstation&N=4294967292
- Micro Center, **HP Z2 G5 SFF (Refurbished)**, 32 GB, $699.99 — https://www.microcenter.com/product/711099/hp-z2-g5-sff-workstation-(refurbished)
- Micro Center, Dell Precision 3431 SFF (Refurbished), 16 GB, $349.99 — https://www.microcenter.com/product/707191/dell-precision-3431-sff-workstation-desktop-(refurbished)
- Micro Center, `workstation 64GB` search — https://www.microcenter.com/search/search_results.aspx?Ntt=workstation+64GB
- B&H, new workstations `workstation 64GB` — https://www.bhphotovideo.com/c/search?q=workstation%2064GB
- B&H, **used department** — https://www.bhphotovideo.com/c/search?q=workstation&sts=used
- ServerMonkey, **Dell Precision 7920 Tower configurator**, base $1,340, **64 GB LRDIMM option +$640 → $1,980** — https://www.servermonkey.com/refurbished-dell-precision-7920-tower-workstation.html
- ServerMonkey, workstations index — https://www.servermonkey.com/workstations.html
- PCLiquidations, HP refurbished desktops (8–16 GB, $152.99–$390.98) — https://www.pcliquidations.com/hp-refurbished-desktops
- Back Market, **Dell Precision 5820 search**, cheapest 64 GB **$657.00** — https://www.backmarket.com/en-us/search?q=Dell%20Precision%205820
- Back Market, `workstation 64GB` search, **HP Z8 G4 64 GB $1,458.00** — https://www.backmarket.com/en-us/search?q=workstation%2064GB
- eBay Refurbished (official channel) landing page — https://www.ebay.com/e/refurbished/refurbished-workstations
- Wisetek Market, Dell 5820 i9-10900X 64 GB, **$789.00, Unavailable** — https://www.wisetekmarket.com/products/dell-precision-5820-tower-64gb-256gb-ssd-i9-10900x-3-70ghz-win11p-black-refurbished-fair
- Provantage, QuickFind search (returned unrelated SKUs — **NOT ESTABLISHED**) — https://www.provantage.com/service/searchsvcs/Q-HP%20Z6%20G4

**Idle power — the one new published figure**
- **HP Z420 Workstation QuickSpecs** (66 pp; Windows Idle (S0) = **50.0 W**) — https://h30434.www3.hp.com/psg/attachments/psg/Business-PC-Workstation-POS/39701/1/2013.4%20Z420%20QuickSpecs%20v17.pdf

**Inherited constants (unchanged from report 181, so the two reports are comparable)**
- NJ residential electricity **24.95 ¢/kWh**; 1 W = 8.766 kWh/yr ≈ **$2.19/yr**; 100 W ≈ **$219/yr** (EIA, June 2026 data, as supplied)
- NJ sales tax **6.625%** — https://www.nj.gov/treasury/taxation/businesses/salestax/index.shtml
- Cloud alternative **$102.99/month** (Hetzner CCX23, Ashburn VA)

---

*Research only. Nothing was purchased, no seller was contacted, no money was committed. The only file modified is this report. Report 181 remains the recommendation of record; this report closes its named coverage gap without changing its conclusion.*
