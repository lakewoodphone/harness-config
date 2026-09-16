# 40 — Hardware Costs: Home-Office + LPT-Office AI Agent Mesh

**Written:** 2026-09-16 · **Author:** Zabz (delegated research session)
**Scope:** costed, evidence-backed hardware plan. No purchase, no install, no machine modified.

## 0. Provenance legend

Every number below is tagged. Nothing is estimated silently.

| Tag | Meaning |
|---|---|
| **MEASURED** | read from a live node during this session, with the command and timestamp |
| **PUBLISHED** | manufacturer / standards-body / vendor specification, with URL and access date |
| **MARKET** | a live listing observed on the date shown, with URL |
| **ARITHMETIC** | derived by me from tagged inputs; the inputs are named |
| **NOT FOUND** | I looked and could not source it. Stated as a gap, never filled with a guess |

**Costing constants used throughout** (the owner's own measured constants, supplied in the brief):

- One actively generating agent turn = **0.81 GB** commit and **~1 core** while generating.
- **25 % headroom rule:** usable RAM = `0.75 × installed`; capacity in turns = `floor(0.75 × RAM_GB / 0.81)`.
- A browser window = 325–566 MB (context only).

**Capacity table (ARITHMETIC, from the two constants above):**

| Installed RAM | Usable (75 %) | Resident turns |
|---|---|---|
| 8 GB | 6.0 GB | 7 |
| 12 GB | 9.0 GB | 11 |
| 16 GB | 12.0 GB | 14 |
| 24 GB | 18.0 GB | 22 |
| 31.6 GB | 23.7 GB | 29 |
| 32 GB | 24.0 GB | 29 |
| 40 GB | 30.0 GB | 37 |
| 64 GB | 48.0 GB | 59 |
| 128 GB | 96.0 GB | 118 |

> **Caveat, stated up front and repeated at every ranking:** the resident-turn number is a *memory* limit. The CPU limit is separate — roughly one core per *generating* turn. A node's useful capacity is `min(resident turns, cores available to generate)`. Most agent wall-clock is spent waiting on a model API rather than burning a core, so a node can *hold* many more turns than it can *saturate* at once. Both numbers are given for every candidate; neither alone is the answer.

---

## 1. The Yoga laptop's RAM

### Identification — MEASURED

Command: `Get-CimInstance Win32_ComputerSystem | Win32_BIOS | Win32_PhysicalMemory | Win32_PhysicalMemoryArray | Win32_Processor`, run on this laptop 2026-09-16.

| Field | Value |
|---|---|
| Manufacturer / Model | `LENOVO` / `83AC` |
| SystemFamily | **`Yoga 9 2-in-1 14IMH9`** |
| SKU string | `LENOVO_MT_83AC_BU_idea_FM_Yoga 9 2-in-1 14IMH9` |
| BIOS | `NNCN37WW`, released 2026-04-30 |
| Serial | `PF5DQE0K` |
| CPU | Intel Core Ultra 7 155H — 16 cores / 22 logical |
| RAM visible | 33,945,935,872 B = **31.6 GiB** |
| Module part number | 8 × `H58G66BK7BX067` (SK Hynix), 4 GB each |
| Reported speed | 8533 MT/s JEDEC, **7467 MT/s configured** |
| SMBIOSMemoryType / FormFactor | `35` (LPDDR5) / `0` |
| `Win32_PhysicalMemoryArray` | `MemoryDevices = 8`, `MaxCapacityEx = 33,554,432 KB` = **32 GB** |

### Verdict — **SOLDERED. NOT UPGRADEABLE. $0 and impossible.**

The machine was identified precisely, so no owner action is needed to establish this.

**PUBLISHED — Lenovo PSREF, machine type 83AC**, https://psref.lenovo.com/Product/Yoga/Yoga_9_2_in_1_14IMH9?MT=83AC (accessed 2026-09-16, page footer "Last updated 2025-10-28"), verbatim:

> `Memory Type: LPDDR5x-7467` · `Memory Slots: Memory soldered to systemboard, no slots, dual-channel` · `Max Memory: 32GB soldered memory, not upgradable`

The 32 GB SKU is the top of the range. PSREF per-model detail page, https://psref.lenovo.com/Detail/Yoga_9_2_in_1_14IMH9?M=83AC0046IV (accessed 2026-09-16), verbatim: `Memory | 32GB Soldered LPDDR5x-7467` · `Machine Type | 83AC`. All 30 SKUs on the 83AC spec tab are 16 GB or 32 GB soldered; not one offers a slot.

**PUBLISHED — Lenovo Hardware Maintenance Manual**, *Yoga 9i 2-in-1 (14″, 9)*, Second Edition, September 2024, https://download.lenovo.com/consumer/mobiles_pub/yoga_9i_2-in-1_14_9_hmm_en.pdf (accessed 2026-09-16). It states verbatim `Table 1. Models: Yoga 9 2-in-1 14IMH9 and Yoga 9 2-in-1 14IMH9 1 (MT: 83AC)` — so it is this exact machine. Its CRU list is three items (power cord, AC adapter, Slim Pen); its FRU category table lists LCD module, upper case, system board, heat sink, fans, antenna — **no memory module, and no memory FRU part number exists in the manual**. There is no memory removal procedure. Lenovo's official FRU video set for 83AC has nine videos (bottom cover, battery, SSD, thermal module, LCD, fans, speakers, I/O board, main board) — **none for memory**. https://support.lenovo.com/us/en/solutions/ht516286 (accessed 2026-09-16).

**Independent corroboration — PUBLISHED, Kingston memory finder** for "Yoga 9 2-in-1 14IMH9", https://www.kingston.com/en/memory/search/model/109430/lenovo-yoga-9-2-in-1-14imh9 (accessed 2026-09-16), verbatim:

> `0 Slot(s)` · `Memory soldered to motherboard` · `Memory is soldered to systemboard, no sockets available for upgrade.`

**Reconciling the confusing MEASURED reading.** `Win32_PhysicalMemory` reports *eight* 4 GB devices across `Controller0/1` channels A–D, which looks like eight sockets. It is not. PSREF and the HMM both state zero slots, and `FormFactor = 0` is the "unknown" value, not "DIMM". The eight entries are SMBIOS enumeration artifacts of the soldered LPDDR5x packages: 8 × 4 GB = 32 GB, matching both the measured total and PSREF's 32 GB soldered configuration. A distributor page for the exact measured part, `H58G66BK7BX067`, describes it as `LPDDR5-7500 (32Gb)` — 32 Gb = 4 GB per package, https://www.win-source.net/products/detail/hynix-semiconductor/h58g66bk7bx067n.html (accessed 2026-09-16). (Distributor page, not a SK hynix primary datasheet — see NOT FOUND.)

**Consequence for the plan:** the single machine the owner actually works on cannot be expanded in the dimension that is binding. Any plan that depends on "just add RAM to the Yoga" is dead on arrival. The only expandable part of this laptop is storage: `One M.2 2242 PCIe 4.0 x4 slot, up to 1TB` (PSREF) — which is not the constraint.

**Cost of this item: $0. Capacity added: 0 turns. Not a decision the owner needs to make.**

---

## 2. The authority server — `secratary`

All figures MEASURED at 2026-09-16 20:09 EDT via `ssh secratary-ts`, plus `lscpu`, `free -m`, `dmidecode`, `lsblk`, `vmstat`, `journalctl`.

### What it is

| Field | Value | Tag |
|---|---|---|
| Make / model | **Dell Inc. OptiPlex 9020**, chassis `Type: Space-saving` (SFF) | MEASURED |
| Motherboard | `0XCR8D` rev A03, service tag `7QJWM02` | MEASURED |
| CPU | Intel **Core i5-4570** @ 3.20 GHz — **4 cores / 4 threads**, Haswell (2013), LGA1150 | MEASURED |
| RAM installed | 23,421 MiB total (24 GB) = **2 × 4 GB DDR3-1333 + 2 × 8 GB DDR3-1600**, all running at 1333 MT/s | MEASURED |
| DIMM slots | **4**, all populated | MEASURED |
| Max capacity (firmware) | **32 GB** (`Maximum Capacity: 32 GB`) | MEASURED |
| Max capacity (vendor) | 32 GB DDR3-1600, 4 DIMM slots, dual-channel | PUBLISHED — https://www.hardware-corner.net/desktop-models/Dell-OptiPlex-9020-SFF/ (accessed 2026-09-16) |
| Disk | **PNY 500 GB SATA SSD** — `Rotation Rate: Solid State Device`, `ROTA=0`. 467 GB volume, **185 GB free (59 % used)** | MEASURED |
| Swap | 4 GB swap file, **100 % allocated** (`4G used, 0 free`) | MEASURED |
| Free PCIe slots | `PCI Express 3 x16` — **Available**; `PCI Express 2 x4` — **Available** | MEASURED |
| Network | `eno1` 192.168.50.77/24, plus Tailscale `100.84.72.88` | MEASURED |
| Uptime | 13 days 21:59 | MEASURED |

### Its current load — MEASURED

- `uptime`: load average **1.49 / 0.71 / 0.76** on 4 threads.
- `vmstat 1 3`: **95–96 % CPU idle** across all three samples, `si = 0`, `so = 0`.
- `free -m`: 6,188 MiB used, 588 MiB free, 18,775 MiB buff/cache, 17,233 MiB available.
- `journalctl -u secretary-api --since '7 days ago' | grep -c 'database is locked'` → **8,290 events in 7 days** (~1.2/min), against **400,976 log lines** in the same window.
- Top consumers: `python` 19 % CPU / 2.4 GB RSS (secretary-api), several `chrome` processes at 6–48 % CPU, `node` at 15.8 % (secretary-dashboard).
- Running services: `secretary-api`, `secretary-dashboard`, `tailscaled`, `vscode-tunnel`.

### Reading this honestly

Three things are true and they point in different directions:

1. **It is not CPU-saturated right now.** 95–96 % idle in the sampled window, load 1.49 on 4 threads. A 4-thread 2013 CPU is a hard ceiling, but it is not currently pinned against it.
2. **Its memory is genuinely tight.** The 4 GB swap file is **100 % allocated**. `vmstat` shows `si=0/so=0`, so this is resident rather than actively thrashing at the moment of measurement — but a fully-consumed swap file means there is no reserve left.
3. **Its measured pain is lock contention, not disk speed.** 8,290 `database is locked` events in 7 days is the loudest signal on the box, and it is a SQLite concurrency property. The disk is **already a SATA SSD, not spinning** (`ROTA=0`), so an "NVMe upgrade" is not the fix. See item 5.

### The question asked: cheapest change that materially raises capacity

| Option | Cost | Capacity effect | Verdict |
|---|---|---|---|
| **A. More RAM** — buy 2 × 8 GB DDR3-1600 UDIMM, pull the two 4 GB sticks → 4 × 8 GB = **32 GB at full 1600 MT/s** | MARKET: 8 GB DDR3/DDR3L-1600 UDIMM seen at **$19.99** and **$28.65** on Newegg listing pages, https://www.newegg.com/p/pl?d=8gb+pc3-12800+ddr3 and https://www.newegg.com/p/pl?d=8gb+ddr3 (accessed 2026-09-16); NEMIX 8 GB DDR3-1600 2Rx8 UDIMM, https://www.newegg.com/nemix-ram-ddr3-orignial-desktop-pc-240-pin-non-ecc-unbuffered-udimm-memory-8gb-ddr3-1600-cas-latency-cl11/p/0RN-004P-005M8 (accessed 2026-09-16). **2 sticks = $40–58**, +6.625 % NJ tax = **$42.65–61.85** | 24 → 32 GB = 22 → **29 resident turns (+8)**, and unlocks 1600 MT/s on all four slots. **+0 cores.** | **Cheapest capacity anywhere in this document at $5.33–7.73/turn** — but it buys only 8 turns and adds nothing to the 4-thread wall, and it is money into a 2013 dead-end platform. Worth doing only because the absolute sum is trivial and swap is fully allocated. |
| **B. NVMe / disk upgrade** | — | — | **Not the fix.** The disk is already a SATA SSD (MEASURED `ROTA=0`), not spinning. The 9020 has **no M.2 slot** (Haswell-generation OptiPlex); NVMe would need a PCIe adapter card in the free x16 slot, and this generation does not support booting from NVMe natively — an adapter is a data disk at best, typically requiring a bootloader workaround. *Engineering judgement, not a vendor citation; see notes.* The 8,290 lock events are SQLite concurrency, not raw disk throughput. **$0 recommended here.** |
| **C. Replace the box entirely** | See below | Removes the 4-thread ceiling and the 32 GB DDR3 ceiling at once | **This is the real answer if the goal is throughput, not turn count.** No RAM or disk change fixes a 4-core/4-thread 2013 CPU. |

**Answer to the question as asked:** the cheapest change that materially raises *resident-turn* capacity is **option A, $42.65–61.85 all-in for +8 turns** — but it is poor value in absolute terms and does not touch the binding limit. If "capacity" means the 18-agent tick loop's throughput, **option C is the only material change**, because the constraint is the CPU, not the RAM and not the disk.

### Replacement options — 2–3 candidates

The nearest **sourced** comparison point is a used HP EliteDesk 800 G5 Mini with an i5-9500 (6 c / 6 t), 16 GB, no HDD, seen at **$97.99** and **$129.60**, and the same class at **$199.99** refurbished with a 256 GB NVMe and free shipping — https://www.ebay.com/shop/hp-elitedesk-800-g5 and https://www.b/b/hp-mini-computer/bn_7024898108 (MARKET, accessed 2026-09-16). A 6-core i5-9500 at $98–130 is a straight upgrade on 4 cores, at 10 W idle versus the 9020's desktop-class draw.

**NOT FOUND:** a sourced current price for a used **6-core/12-thread SFF** box (i5-10500/10505 or i7-8700 class, OptiPlex 7070 SFF / EliteDesk 800 G6 SFF), which is the class I would actually recommend to replace the 9020 — it roughly triples thread count rather than adding 50 %. I did not find a listing I could cite in this pass, so I am stating the gap rather than naming a number. The arithmetic is linear in the price: at $150 → 2.4× the 9020's thread count for the cost of four months of a rack server's electricity.

**Explicitly not recommended: a used rack server.** See item 5 — measured idle 145–250 W makes it the most expensive option in the room, before noise.

---

## 3. Cheap Linux nodes — what is actually available

All prices MARKET, observed on live eBay US listing/search pages on **2026-09-16**. NJ sales tax **6.625 %** applies and eBay is a registered marketplace facilitator required to collect it — PUBLISHED, NJ Treasury, https://www.nj.gov/treasury/taxation/remotesellersfaq.shtml (accessed 2026-09-16); https://taxcloud.com/sales-tax/new-jersey (accessed 2026-09-16). Several listings advertise free shipping; where delivery was priced it was $9.99–$26.05.

### Candidate table

| # | Machine | Cores | RAM | Storage | Price (MARKET) | Idle W | Resident turns | CPU-generating turns |
|---|---|---|---|---|---|---|---|---|
| 1 | **Dell OptiPlex 3070 Micro**, i5-9500T, 16 GB, 128 GB SSD, refurb + **2-yr warranty**, free ship — https://www.ebay.com/itm/307071642280 | 6 c / 6 t | 16 GB | 128 GB | **$239.99** | ~10 W | 14 | 6 |
| 2 | **Dell OptiPlex 3070 Micro**, i5-9500T, 16 GB, 500 GB HDD, pre-owned, free ship — https://www.ebay.com/shop/dell-optiplex-3070-micro | 6 c / 6 t | 16 GB | 500 GB HDD | **$120.00** or Best Offer | ~10 W | 14 | 6 |
| 3 | **Dell OptiPlex 3060/3070**, i5-8500T/9500T, 16 GB, **no HDD** — https://www.ebay.com/shop/dell-optiplex-16-gb-ram | 6 c / 6 t | 16 GB | none | **$102.50** (4 bids, auction) / **$119.99** Buy-It-Now | ~10 W | 14 | 6 |
| 4 | **HP EliteDesk 800 G5 Mini**, i5-9500T, 16 GB, No HDD — https://www.ebay.com/itm/366490566850 | 6 c / 6 t | 16 GB | none | **$79.00** | ~10 W | 14 | 6 |
| 5 | **HP EliteDesk 800 G5 Mini**, i5-9500, 16 GB, No HDD — https://www.ebay.com/shop/hp-elitedesk-800-g5 | 6 c / 6 t | 16 GB | none | **$97.99** | ~10 W | 14 | 6 |
| 6 | **HP EliteDesk 800 G5 Mini** i5-9500T, 16 GB, 256 GB NVMe, very-good refurb, free ship — https://www.ebay.com/b/hp-mini-computer/bn_7024898108 | 6 c / 6 t | 16 GB | 256 GB NVMe | **$199.99** (was $249.99) | ~10 W | 14 | 6 |
| 7 | OptiPlex 3070 Micro, i5-9500T, 16 GB — https://www.ebay.com/shop/optiplex-3070-micro | 6 c / 6 t | 16 GB | varies | **$129.99** +$26.05 ship / **$159.00** +$9.99 ship | ~10 W | 14 | 6 |
| 8 | **Lot of 7** OptiPlex 3070 Micro, i5-9500T, **8 GB** — https://www.ebay.com/itm/358793480712 | 6 c / 6 t | 8 GB | varies | **$999.99** ended = **$143/unit** | ~10 W | **7** | 6 |
| 9 | Lenovo ThinkCentre M920q, i5-8500T, 32 GB, 512 GB M.2 — https://www.ebay.ca/sch/i.html?_nkw=thinkcentre+m920q | 6 c / 6 t | 32 GB | 512 GB | C$505 ≈ **US$365** | ~10 W | 29 | 6 |

**Idle power — PUBLISHED, measured on a meter:** ServeTheHome, *Project TinyMiniMicro: Dell OptiPlex 3070 Micro Review*, https://www.servethehome.com/project-tinyminimicro-dell-optiplex-3070-micro-review/2 (published 2020-07-31, accessed 2026-09-16), verbatim: *"Idle power consumption on 120V power we saw just over 10W idle for the quad-core units. We generally assume these nodes will use 9-12W idle."* Corroborated by an independent homelab measurement of an OptiPlex 3070m idling *"around 8-12 watts with a small load"*, https://static.xtremeownage.com/blog/2024/balancing-power-consumption-cost-the-true-price-of-efficiency (2024-06-07, accessed 2026-09-16). **A conflicting PUBLISHED figure exists** — a blog claims 15–20 W idle / 35–45 W load for an i5-8500T Micro, https://www.marginseye.com/blog/dell-optiplex-micro-review (2026-07-08, accessed 2026-09-16). I use **10 W** and flag the spread; the two meter-based sources agree with each other and disagree with the blog.

**Noise:** these are sub-1-litre chassis with a single 35 W-class TDP CPU and a small blower. Every source reviewed describes them as quiet under light load — e.g. ServeTheHome on the 3070 Micro: *"It sips power, is relatively quiet."* I found **no published dB(A) figure** for this class. See NOT FOUND.

**Shipping/tax reality:** NJ levies 6.625 % on these purchases and eBay collects it as a marketplace facilitator (PUBLISHED, above). Free shipping is common on the listings but not universal — budget $0–26 per unit.

### Rankings

**By capacity per dollar** (price × 1.06625 for NJ tax; resident turns ÷ taxed price):

| Rank | Candidate | Taxed price | Turns added | **$/turn** |
|---|---|---|---|---|
| 1 | HP EliteDesk 800 G5 Mini, i5-9500T, 16 GB, no HDD @ $79 | $84.23 | 14 | **$6.02** |
| 2 | OptiPlex 3060/3070, 16 GB, no HDD @ $102.50 (auction) | $109.29 | 14 | **$7.81** |
| 3 | HP EliteDesk 800 G5 Mini, i5-9500, 16 GB, no HDD @ $97.99 | $104.48 | 14 | **$7.46** |
| 4 | OptiPlex 3070 Micro, 16 GB, 500 GB HDD @ $120 | $127.95 | 14 | **$9.14** |
| 5 | OptiPlex 3060/3070, 16 GB, no HDD @ $119.99 | $127.94 | 14 | **$9.14** |
| 6 | ThinkCentre M920q, 32 GB, 512 GB @ ~US$365 | $389.18 | 29 | **$13.42** |
| 7 | OptiPlex 3070 Micro refurb + 2-yr warranty @ $239.99 | $255.89 | 14 | **$18.28** |
| 8 | **Lot of 7 × 8 GB @ $143/unit** | $152.47 | **7** | **$21.78** (worst) |

A "no HDD" unit needs a boot disk added — a 256 GB SATA SSD, currently **MARKET ~$30–45** (SSD prices are also elevated in the 2026 shortage; I did not obtain a firm citable listing, so treat $30–45 as an unpriced assumption, **NOT FOUND** as a sourced figure). Adding $35 lifts the $79 unit to ~$114 taxed-equivalent → ~$9.1/turn, level with the turnkey units. Buy the turnkey unit unless the no-HDD unit is the cheapest by more than the cost of a disk.

**By capacity per watt** (1 W continuous = 8.76 kWh/yr = **$2.06/yr** at $0.235/kWh — ARITHMETIC):

| Rank | Candidate | Turns/W |
|---|---|---|
| 1 | Any RAM upgrade to an existing box (+27 turns for ~+1 W) | ~27 turns/W |
| 2 | Micro PC @ 10 W: 14 turns ÷ 10 W | **1.40 turns/W** |
| 3 | One big machine, 128 GB / ~50 W idle: 118 ÷ 50 | 2.36 turns/W (see item 4) |
| 4 | Used rack server @ 145 W, ~29–59 turns | 0.20–0.41 turns/W |

Note the inversion: a **single large machine is more efficient per resident turn** than a fleet of small ones, because each small node carries its own ~6–8 W of platform overhead. That is an argument for the big machine on electricity, and it is not enough to overcome its 2026 RAM cost (item 4).

---

## 4. The honest arithmetic: many cheap nodes vs one big machine vs upgrading what he owns

### Where the fleet stands today — MEASURED

| Node | CPU | Cores/threads | RAM | Resident turns | CPU-generating turns |
|---|---|---|---|---|---|
| Yoga 9 14IMH9 (this laptop) | Ultra 7 155H | 16 c / 22 t | 31.6 GB | 29 | 22 |
| `secratary` (OptiPlex 9020 SFF) | i5-4570 | 4 c / 4 t | 23.4 GB | 21 | 4 |
| `linux-pc-ts` (**HP Pavilion Desktop TP01-2xxx**) | i5-11400 | 6 c / 12 t | 11.6 GB | 10 | 12 |
| `mac-mini-ts` (Apple M4) | M4 | 10 c | 16 GB | 14 | 10 |
| **Total** | | **48 threads** | **82.6 GB** | **74** | **48** |

> **Correction to the fleet inventory.** The brief describes `zabz-tech-linux` as "a macOS mini for his employee Yisroel". MEASURED on 2026-09-16, the host reachable as `linux-pc-ts` is running hostname `zabz-tech-linux`, `Linux 6.8.0-111-generic x86_64` — **Ubuntu on an HP Pavilion Desktop TP01-2xxx with an i5-11400**, not macOS and not a mini. Its `dmidecode` reports **2 DIMM slots (DIMM1: 8 GB Samsung M378A1G44AB0-CWE; DIMM2: 4 GB SK Hynix HMA851U6DJR6N-XN), DDR4-3200, `Maximum Capacity: 64 GB`**, and a 468 GB NVMe volume **96 % full**. The recorded inventory is stale; the measurement is the truth. This matters because it makes that machine the single best upgrade target in the estate.

**The real diagnosis.** Demand is 40–55 concurrent turns = 44.6 GB at 55 turns, which **alone exceeds the Yoga's 31.6 GB**. The mesh already holds 74 resident turns in aggregate, so total memory is not the shortage — **the shortage is that capacity is not where the work lands, and the Yoga cannot be expanded (item 1)**. Any hardware purchase is therefore about (i) creating *elsewhere* to put turns, and (ii) adding cores to run them.

### (a) 3–4 cheap used mini PCs

Using the $120–130 turnkey 16 GB units (candidates 2/4/5 above):

| | 3 nodes | 4 nodes |
|---|---|---|
| Purchase | 3 × $120 = $360 → **$383.85 taxed** | 4 × $120 = $480 → **$511.80 taxed** |
| Turns added | 3 × 14 = **+42** | **+56** |
| Cores added | **+18** (6 c each) | +24 |
| Idle power | 30 W → **$61.75/yr** | 40 W → $82.33/yr |
| 3-yr TCO | $383.85 + $185.25 = **$569.10** | $511.80 + $247.00 = **$758.80** |
| **$/turn** | **$9.14** | $9.14 |
| **turns/W** | 1.40 | 1.40 |
| Complexity | 3 more Linux boxes to patch, monitor, reboot, and house | 4 more |

### (b) One modern high-core desktop with 64–128 GB

RAM is the dominant and now pathological cost. **PUBLISHED/MARKET, 2026-09-16:**

- 32 GB DDR5-6000 kit (Corsair Vengeance RGB): **$454.99** — Newegg Insider, https://www.newegg.com/insider/best-ddr5-ram-kits-in-2026-and-why-prices-are-up (2026-07-31, accessed 2026-09-16).
- A Newegg bundle promo put 32 GB DDR5 at **$239.99** — Tom's Hardware, https://www.tomshardware.com/pc-components/score-32gb-of-ddr5-ram-from-only-usd240-in-these-newegg-hardware-bundles-for-intel-and-amd-gaming-pc-builds-huge-savings-on-premium-gigabyte-motherboards-coupled-with-popular-corsair-vengeance-memory (2026-06-15, accessed 2026-09-16).
- The spike itself: **DDR4 up more than 50 % in Q3 2026**, and *"DDR3 also impacted by higher costs"* — https://wccftech.com/memory-shortages-drive-ddr4-prices-over-50-in-q3-2026-ddr3-also-impacted-by-higher-costs (2026-07-08, accessed 2026-09-16); corroborated by https://www.tomshardware.com/pc-components/ram/memory-price-surge-begins-to-cool-as-consumers-hit-affordability-limit-ai-demand-still-keeps-dram-and-nand-prices-climbing-through-q3-2026 (2026-07-04, accessed 2026-09-16).

| RAM target | Cost at $239.99 per 32 GB | Cost at $454.99 per 32 GB | Resident turns |
|---|---|---|---|
| 64 GB | $479.98 | $909.98 | 59 |
| 128 GB | **$959.96** | **$1,819.96** | 118 |

**$/turn on RAM alone:** 128 GB → $959.96 ÷ 118 = **$8.14/turn** at the cheapest sourced DDR5 price, and **$15.42/turn** at the retail kit price — *before* CPU, motherboard, PSU, case, cooler, or storage.

**NOT FOUND:** a citable current price for the complete build (Ryzen 9 7950X or i9-14900K class, 128 GB, 2 TB NVMe). A Newegg listing exists for an "ASUS TUF GT501 — AMD Ryzen 9-7950X 16 core — RTX 5060 — 2TB NVMe — 32GB DDR5 — Win 11" (https://www.newegg.com/p/pl?d=ryzen+7950x, accessed 2026-09-16) but I did not capture its price, so I will not state one. The conclusion is robust without it: **≥$960 of the build is RAM at the best sourced price**, which is 2.5× the cost of four complete used nodes, and the machine adds **32 generating cores** against their 24 — a poor exchange.

**Cost of the (b) route:** ~$1,000–1,900+ for 118 resident turns, 32 cores, ~40–60 W idle (~$82–124/yr). **$/turn ≥ $8.1 and realistically $13–20.** One machine to manage. Its one real advantage is **turns per watt** (2.36 vs 1.40) — it is the most electrically efficient way to hold turns, because one power supply and one motherboard serve 118 turns instead of 14.

### (c) Upgrading what he already owns

| Target | Action | Cost (taxed) | Turns added | Cores added | **$/turn marginal** |
|---|---|---|---|---|---|
| **Yoga 9 14IMH9** | none possible — soldered (item 1) | **$0** | 0 | 0 | — |
| **`mac-mini-ts`** (Apple M4, 16 GB) | none possible — Apple silicon memory is soldered to the package; 16 GB → 14 turns, no growth path | **$0** | 0 | 0 | — |
| **`secratary`** OptiPlex 9020 SFF | 2 × 8 GB DDR3-1600, pull the 2 × 4 GB → **32 GB @ 1600** | **$42.65–61.85** | **+8** (21→29) | 0 | **$5.33–7.73** |
| **`linux-pc-ts`** HP Pavilion TP01-2xxx | add **1 × 32 GB DDR4-3200** alongside the existing 8 GB → **40 GB** | **$237.77** (at the cheapest sourced 32 GB stick price of $223) | **+27** (10→37) | 0 | **$8.81** |
| **`linux-pc-ts`** HP Pavilion TP01-2xxx | replace both with **2 × 32 GB** → **64 GB** | **$467.98–527.16** (64 GB kit at $438.95 / $493.89) | **+49** (10→59) | 0 | **$9.55–10.76** |

**DDR4-3200 pricing, MARKET/PUBLISHED, accessed 2026-09-16** (the spike makes this brutal — it must be stated plainly):

- **32 GB single UDIMM-3200:** Newegg listing pages show *"32GB Single DDR4 3200 MHz — More options from $255.95 – $404.00 Free Shipping"* (https://www.newegg.com/p/pl?d=32gb+ram+single+stick) and a *"32GB DDR4 3200MHz DIMM PC4-25600 UDIMM 288-Pin Dual Rank"* at **$223.09** (https://www.newegg.com/p/pl?d=128gb+ddr4+3200).
- **64 GB kit (2 × 32 GB) DDR4-3200:** Crucial `CT2K32G4DFD832A` at **$493.89** ("Listed on Newegg June 11, 2026", https://www.newegg.com/crucial-64gb-ddr4-3200-cas-latency-cl22-desktop-memory/p/N82E16820156238); **"From $438.95, 6 New"** (https://www.newegg.com/crucial-64gb-ddr4-3200/p/N82E16820156238?Item=9SIAM37K8B3495); Crucial Pro 64 GB from **$566.84** (https://www.newegg.com/crucial-pro-64gb-ddr4-3200-cas-latency-cl22-desktop-memory-black/p/N82E16820156327); Amazon third-party new **$541.95** as of 2026-07-09 and used **$454.99** as of 2026-07-07 (https://camelcamelcamel.com/product/B0C29W4G29).
- **32 GB kit (2 × 16 GB) DDR4-3200:** **$184.99–215.98** (https://www.newegg.com/p/pl?d=32gb+ddr4+3200) and $187.99 (https://www.newegg.com/p/pl?d=32+gb+ddr4+3200+ram) — but this does **not** fit the goal: replacing 8+4 with 2×16 yields 32 GB / 29 turns, +19 turns, ~$197 taxed = **$10.37/turn**.
- **8 GB DDR3-1600 UDIMM:** **$19.99–$28.65** (https://www.newegg.com/p/pl?d=8gb+pc3-12800+ddr3, https://www.newegg.com/p/pl?d=8gb+ddr3).

### Electricity

**PUBLISHED — New Jersey residential rate ≈ 23 ¢/kWh:** EnergySage, *"As of September 2026, the cost of electricity in New Jersey is 23 ¢/kilowatt-hour"*, https://www.energysage.com/local-data/electricity-cost/nj (2026-09-12, accessed 2026-09-16); ChooseEnergy gives **23.49 ¢/kWh**, https://www.chooseenergy.com/electricity-rates/new-jersey (2026-07-22, accessed 2026-09-16). For comparison the **US residential average is 18.34 ¢/kWh** as of September 2026, https://www.electricchoice.com/electricity-prices-by-state (accessed 2026-09-16). Primary source table: EIA *Electric Power Monthly*, Table 5.6.A, https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a (accessed 2026-09-16). **I use $0.235/kWh** and note the alternative rate: NJ commercial rates are lower than residential, so if the LPT-office nodes sit on a commercial meter the numbers below are conservative.

**ARITHMETIC — 1 W continuous = 8.76 kWh/yr = $2.06/yr at $0.235/kWh:**

| Device | Idle W | kWh/yr | $/yr | Source of the wattage |
|---|---|---|---|---|
| Micro PC (OptiPlex 3070 / EliteDesk class) | 10 | 87.6 | **$20.59** | PUBLISHED, ServeTheHome meter measurement |
| 3 micro PCs | 30 | 262.8 | **$61.75** | ARITHMETIC |
| One big desktop, 128 GB | 40–60 | 350–526 | **$82–124** | *assumption, not measured* — see note |
| Used rack server (PowerEdge R730) | 145–250 | 1,270–2,190 | **$298–515** | PUBLISHED, below |

**Rack-server idle draw — PUBLISHED, and this is the whole argument against them:** an R730 *"using ~145 w at basically idle"* (ServeTheHome forum, https://forums.servethehome.com/index.php?threads/dell-r730-vs-r720-power-usage.31985/, 2021-02-24); *"It idles at 100+ watts… Mine idles at 220 watts… idle usage down to 168w"* (r/homelab, https://www.reddit.com/r/homelab/comments/1lut5r6/r730_lower_power_consumption, 2025-09-16); *"power consumption at idle was about 321-336 [W]… After starting powerd++, power consumption has been between 196W and 210 watts"* (https://dan.langille.org/2024/01/29/using-powerd-to-reduce-power-consumption-on-a-dell-r730, 2024-01-29). A used R730 therefore burns **$298–660/yr at idle** in New Jersey — more than the purchase price of two complete used mini-PC nodes, every single year. All accessed 2026-09-16.

**Note on the big-desktop wattage:** I found **no meter-measured idle figure** for a 128 GB desktop workstation, so 40–60 W is an **assumption and is flagged as such**, not a sourced number. It does not change any ranking: even at 60 W it costs less to run than one rack server.

### Complexity — the cost that does not appear on an invoice

**NO AUTHORITATIVE SOURCE EXISTS for a dollar figure on fleet maintenance burden; the following is engineering judgement, labelled as such.** Each node added is a machine that needs an OS install, a distro upgrade every 2 years (Ubuntu LTS), security patches, an unattended-upgrades policy, a reboot window, monitoring, a backup check, and a physical place to live. That work is currently done by one seat (this one) that has no continuous memory, so every node's state must be *written down* to survive. Three nodes at ~19 W each also means three power bricks, three fan inlets to keep dust-free, and three network identities — and three chances for a single node to be silently down while its capacity is still being counted. One big machine is one thing to get right. This is a real cost and it is why (b) is a legitimate option despite the arithmetic — but it is not large enough to beat (a) on dollars.

**What one big machine does not fix:** the owner's actual complaint is that *work lands on the Yoga*. Centralising on a single new box swaps one bottleneck for another with the same failure mode — everything queues in one place, and if that box is down, the whole mesh is down. Three cheap nodes are strictly more resilient. That asymmetry, not the $/turn, is the decisive argument for (a).

### Recommendation

**Buy (a), plus the two cheap RAM top-ups from (c). Do not buy (b) now. Do not buy a rack server ever.**

| # | Purchase | Detail | Cost taxed |
|---|---|---|---|
| 1 | **3 × used 6-core / 16 GB micro PC** | Dell OptiPlex 3070 Micro or HP EliteDesk 800 G5 Mini, i5-9500T | 3 × ~$120 = **$383.85** |
| 2 | **1 × 32 GB DDR4-3200 UDIMM** into the existing HP Pavilion TP01 (`linux-pc-ts`) | 12 GB → 40 GB on a machine already running Ubuntu with an i5-11400 | **$237.77** |
| 3 | **2 × 8 GB DDR3-1600 UDIMM** into `secratary` | 24 GB → 32 GB @ 1600, relieves a 100 %-allocated swap file | **$42.65–61.85** |
| | **Total** | | **≈ $664–684** |

**Resulting mesh:** resident turns **74 → 151**; cores available to generate **48 → 66**; non-Yoga capacity **45 → 122 turns**, which covers the stated 40–55 concurrent demand with the 25 % headroom rule intact and leaves the Yoga free to be the machine he works on. Added continuous draw ~32 W = **+$66/yr**. **$/turn across the whole package ≈ $8.8.** Even instantiated at the *worst* observed prices (all three nodes at the $239.99 refurbished-with-warranty tier) the package is ~$1,000 and still beats route (b).

Buy the three nodes at warranty-bearing refurbished grade if the budget allows; the lot that failed (candidate 8) is a warning that a cheap headline price per unit often means 8 GB, not 16 GB.

**Do not buy a fourth node yet.** Add one only when measured resident turns in the non-Yoga mesh exceed ~90 (i.e. when the 25 % rule is actually breached) — capacity that is not needed is electricity and maintenance paid for nothing.

---

## 5. What NOT to buy, and why

Each of these looks attractive and fails on a **measured** constraint.

**1. Any 8 GB machine — including the lot that looks cheapest per unit.** The 7-unit OptiPlex 3070 Micro lot at **$999.99 = $143/unit** (MARKET, https://www.ebay.com/itm/358793480712) has 8 GB each: **7 resident turns** against 14 for a 16 GB unit bought singly for $120–130. That is **$21.78/turn** — the worst figure in this document — and the lot costs *more per unit* than a 16 GB machine bought individually. To fix it you must buy DDR4 separately, and at 2026 prices a 32 GB stick is **$223–256** (MARKET, Newegg), so each 8 GB node would cost $143 + $223 = $366 for 29 turns, versus $120 for 14 on a machine that already has what it needs. **8 GB is below the useful floor for this workload**; the measured demand is 40–55 concurrent turns and a 7-turn node cannot participate meaningfully.

**2. A used rack server (PowerEdge R730, ProLiant DL360 Gen9, etc.).** Attractive because used enterprise hardware is cheap to buy and rich in RAM. It fails on **measured idle power**: 145–250 W typical, up to 321–336 W pre-tuning — **$298–515/yr in electricity at idle, before cooling**, which exceeds the purchase price of two complete mini-PC nodes every year. It also fails on noise: 1U/2U servers use small high-RPM fans and are measured in tens of dB(A), unsuitable for an office where customers walk in or a home office. And it fails on the same axis as everything else here: **a rack server does not run the fleet's Windows-only tooling or its desktop-class workloads**. 0.2–0.4 turns/W against a micro PC's 1.40 is not a trade, it is a mistake.

**3. ARM single-board computers (Raspberry Pi 5 16 GB, Orange Pi 5, etc.).** They look like the ideal answer on paper — 16 GB for ~$120–160, a few watts — and the 0.81 GB/turn constant is architecture-independent, so the capacity arithmetic appears to work. It fails on **workload compatibility**: this estate includes an x86 Linux fleet, x86 `node_modules`, .NET and Windows-only tooling, and native Python wheels. An ARM node would need emulation to run any of it, and emulation consumes exactly the resource that is scarce (**CPU**). It also has **soldered RAM**, so like the Yoga it has no growth path — you would be buying the same "31.6 GB and no way up" mistake in miniature. *This is engineering judgement grounded in the estate's inventory, not a measurement; I did not benchmark an ARM node.*

**4. A disk upgrade for `secratary`.** The box is **already on a SATA SSD** (MEASURED: PNY 500 GB, `Rotation Rate: Solid State Device`, `ROTA=0`), with 185 GB free. It is **not** on spinning disk. The dominant failure signal on that machine is **8,290 `database is locked` events in 7 days** (MEASURED, `journalctl -u secretary-api`), which is a **SQLite concurrency** property, not raw sequential throughput. An NVMe upgrade would also be awkward to boot: the OptiPlex 9020 has no M.2 slot and Haswell does not support native NVMe boot, so an adapter card is a data disk at best with a bootloader workaround. **Do not spend money here expecting it to stop the lock events** — fix the concurrency in software instead.

**5. Any soldered-RAM machine bought as an expandable node.** The measured lesson of this document: the two machines that *cannot* be expanded (the Yoga, 32 GB soldered LPDDR5x; the Mac mini M4, 16 GB soldered) are precisely the two that are now capacity dead ends. A 16 GB soldered box is 14 turns **forever**. Before buying any node, confirm it has **two DIMM slots** — the HP Pavilion TP01-2xxx (2 slots, 64 GB max) and the OptiPlex 9020 SFF (4 slots, 32 GB max) are the models here that can grow.

**6. Buying bare RAM as the primary strategy, at 2026 prices.** This is the trap the DRAM spike creates. **DDR4 rose more than 50 % in Q3 2026** and DDR3 rose with it (PUBLISHED, above). A bare 32 GB DDR4-3200 stick costs **$223–256** and delivers 29 turns to a machine you must already own — but for **$120–130 you can buy a complete 16 GB machine with 6 cores, a PSU, a chassis, a disk and a NIC**. Per turn the bare stick is slightly cheaper ($7.7–8.8 vs $9.1); per *core* it adds nothing at all. **Buy whole used machines before buying RAM.** The only RAM purchases that clear the bar are the two small top-ups in the recommendation, and those clear it only because the machines already exist and the slots are already empty.

**7. Assuming the mesh's total RAM is the problem.** MEASURED: the four existing nodes already hold **74 resident turns** in aggregate, against a stated demand of 40–55. **Total memory is not the shortage.** The shortage is placement — the work lands on the one machine that cannot be upgraded — plus core count. Spending on a huge single machine to add raw resident turns, when 74 already exist and are not being used, would be paying to solve a problem that is not the measured one.

---

## NOT FOUND — stated gaps, not guesses

1. **A citable complete-build price for a 128 GB modern desktop** (Ryzen 9 7950X / i9-14900K class, 128 GB, 2 TB NVMe). A Newegg listing exists but I did not capture its price, so no total is stated. The RAM-only cost is sourced and sufficient to reject the option.
2. **A meter-measured idle wattage for a 128 GB desktop workstation.** The 40–60 W figure is an **assumption**, flagged as such. Also **no dB(A) measurement** for OptiPlex/EliteDesk/Tiny-class micro PCs under light load — all sources describe them qualitatively as quiet.
3. **A sourced current price for a used 6-core/12-thread SFF** (i5-10500/10505, i7-8700 class) — the box I would actually recommend to replace `secratary`. The nearest cited comparison points are the 6-core HP EliteDesk 800 G5 Mini listings at $97.99–$199.99 (MARKET, 2026-09-16).
4. **A firm citable listing for a 256 GB SSD** to complete a "no HDD" node. $30–45 is an **unpriced assumption**; SSD prices are also elevated in the same 2026 shortage.
5. **A SK hynix primary datasheet for `H58G66BK7BX067`.** Only distributor pages and third-party benchmark databases surfaced; the part's identity as 32 Gb LPDDR5 rests on a distributor listing.
6. **Any published maintenance-burden cost** for N Linux nodes vs 1. Item 4's complexity analysis is **engineering judgement**, labelled as such, because no authoritative source exists.

## Provenance of the measurements

All MEASURED values were taken in this session on 2026-09-16 (server measurements at 20:09 EDT) by the author, using:
`Get-CimInstance Win32_ComputerSystem/Win32_BIOS/Win32_PhysicalMemory/Win32_PhysicalMemoryArray/Win32_Processor` on the Yoga; and over `ssh secratary-ts` / `ssh mac-mini-ts` / `ssh linux-pc-ts`: `lscpu`, `dmidecode -t 1,2,3,4,9,16,17`, `free -m`, `swapon --show`, `lsblk`, `df -h`, `uptime`, `vmstat 1 3`, `smartctl -i`, `journalctl`, `sysctl hw.memsize`.

No machine was modified. No software was installed. Nothing was purchased. This document is the only file written.
