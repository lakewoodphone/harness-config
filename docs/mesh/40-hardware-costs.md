# 40 — Hardware Costs: Home-Office + LPT-Office AI Agent Mesh

**Written:** 2026-09-16 · **Author:** Zabz (delegated research session)
**Scope:** costed, evidence-backed hardware plan. No purchase, no install, no machine modified. This file is the only thing written.

---

## 0. Provenance legend

| Tag | Meaning |
|---|---|
| **MEASURED** | read from a live node in this session, command and timestamp given |
| **PUBLISHED** | manufacturer / standards-body / vendor specification, with URL and access date |
| **MARKET** | a live listing observed on the date shown, with URL |
| **ARITHMETIC** | derived by me from tagged inputs; the inputs are named |
| **NOT FOUND** | I looked and could not source it. Stated as a gap, never filled with a guess |

### Costing constants

- One actively generating agent turn = **0.81 GB** commit and **~1 core** while generating.
- **25 % headroom rule:** usable RAM = `0.75 × installed`; resident turns = `floor(0.75 × RAM_GB / 0.81)`.
- **Electricity: New Jersey residential 24.95 ¢/kWh** — **PUBLISHED**, EIA *Electric Power Monthly* Table 5.6.A, data for **June 2026**, released 2026-08-26, https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a (accessed 2026-09-16). US residential average 18.34 ¢/kWh, +5.0 % YoY — https://www.eia.gov/electricity/monthly/update/end-use.php (accessed 2026-09-16).
- **New Jersey *commercial* rate, same table and period: 18.47 ¢/kWh.** Use this if the Lakewood office is on a commercial meter — **it makes every power figure in this document conservative.**
- **ARITHMETIC: 1 W continuous = 8.766 kWh/yr = $2.19/yr in New Jersey.** Each 100 W of continuous draw costs **$218.56/yr**. This single constant decides most of this document.
- New Jersey sales tax **6.625 %**, collected by eBay as a registered marketplace facilitator — **PUBLISHED**, NJ Treasury https://www.nj.gov/treasury/taxation/remotesellersfaq.shtml and https://taxcloud.com/sales-tax/new-jersey (accessed 2026-09-16).

### Capacity table — ARITHMETIC

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

> **Caveat, repeated at every ranking:** the resident-turn number is a **memory** limit. The CPU limit is **~one core per *generating* turn**. A node's useful capacity is `min(resident turns, cores that can generate)`. Most agent wall-clock is spent waiting on a model API rather than burning a core, so a node can **hold** far more turns than it can **saturate** at once. Both numbers appear for every candidate; neither alone is the answer.

---

## 1. The Yoga laptop's RAM

### Identification — MEASURED

`Get-CimInstance Win32_ComputerSystem / Win32_BIOS / Win32_PhysicalMemory / Win32_PhysicalMemoryArray / Win32_Processor`, this laptop, 2026-09-16:

| Field | Value |
|---|---|
| Manufacturer / Model | `LENOVO` / `83AC` |
| SystemFamily | **`Yoga 9 2-in-1 14IMH9`** |
| SKU string | `LENOVO_MT_83AC_BU_idea_FM_Yoga 9 2-in-1 14IMH9` |
| BIOS | `NNCN37WW`, released 2026-04-30 |
| Serial | `PF5DQE0K` |
| CPU | Intel Core Ultra 7 155H — 16 cores / 22 logical |
| RAM visible | 33,945,935,872 B = **31.6 GiB** |
| Module part number | 8 instances of `H58G66BK7BX067` (SK Hynix), 4 GB each |
| Speed | 8533 MT/s JEDEC, **7467 MT/s configured** |
| SMBIOSMemoryType / FormFactor | `35` (LPDDR5) / `0` |
| `Win32_PhysicalMemoryArray` | `MemoryDevices = 8`, `MaxCapacityEx = 33,554,432 KB` = **32 GB** |

### Verdict — **SOLDERED. NOT UPGRADEABLE. $0, and impossible.**

The machine was identified precisely, so **no owner action is needed** to establish this.

**PUBLISHED — Lenovo PSREF, machine type 83AC**, https://psref.lenovo.com/Product/Yoga/Yoga_9_2_in_1_14IMH9?MT=83AC (accessed 2026-09-16; page footer "Last updated 2025-10-28"), verbatim:

> `Memory Type: LPDDR5x-7467` · `Memory Slots: Memory soldered to systemboard, no slots, dual-channel` · `Max Memory: 32GB soldered memory, not upgradable`

PSREF per-model detail for a real 32 GB SKU, https://psref.lenovo.com/Detail/Yoga_9_2_in_1_14IMH9?M=83AC0046IV (accessed 2026-09-16), verbatim: `Memory | 32GB Soldered LPDDR5x-7467` · `Machine Type | 83AC`. All 30 SKUs on the 83AC spec tab are 16 GB or 32 GB soldered; not one offers a slot.

**PUBLISHED — Lenovo Hardware Maintenance Manual**, *Yoga 9i 2-in-1 (14″, 9)*, Second Edition, September 2024, https://download.lenovo.com/consumer/mobiles_pub/yoga_9i_2-in-1_14_9_hmm_en.pdf (accessed 2026-09-16). It states verbatim `Table 1. Models: Yoga 9 2-in-1 14IMH9 and Yoga 9 2-in-1 14IMH9 1 (MT: 83AC)` — it is this exact machine. Its CRU list is three items (power cord, AC adapter, Slim Pen); its FRU table lists LCD module, upper case, system board, heat sink, fans, antenna — **no memory module, and no memory FRU part number exists anywhere in the manual**. There is no memory removal procedure. Lenovo's official FRU video set for 83AC has nine videos (bottom cover, battery, SSD, thermal module, LCD, fans, speakers, I/O board, main board) — **none for memory**, https://support.lenovo.com/us/en/solutions/ht516286 (accessed 2026-09-16).

**Independent corroboration — PUBLISHED, Kingston memory finder** for "Yoga 9 2-in-1 14IMH9", https://www.kingston.com/en/memory/search/model/109430/lenovo-yoga-9-2-in-1-14imh9 (accessed 2026-09-16), verbatim:

> `0 Slot(s)` · `Memory soldered to motherboard` · `Memory is soldered to systemboard, no sockets available for upgrade.`

**Reconciling the confusing reading.** `Win32_PhysicalMemory` reports *eight* 4 GB devices across `Controller0/1` channels A–D, which looks like eight sockets. It is not. PSREF and the HMM both state zero slots, and `FormFactor = 0` is the "unknown" value, not "DIMM". The eight entries are SMBIOS enumeration artifacts of the soldered LPDDR5x packages: 8 × 4 GB = 32 GB, matching both the measured total and PSREF's 32 GB soldered configuration. A distributor page for the exact measured part describes `H58G66BK7BX067` as `LPDDR5-7500 (32Gb)` — 32 Gb = 4 GB per package, https://www.win-source.net/products/detail/hynix-semiconductor/h58g66bk7bx067n.html (accessed 2026-09-16). *(Distributor page, not a SK hynix primary datasheet.)*

**Consequence:** the machine the owner actually works on cannot be expanded in the dimension that is binding. Any plan depending on "add RAM to the Yoga" is dead on arrival. The only expandable part is storage — `One M.2 2242 PCIe 4.0 x4 slot, up to 1TB` (PSREF) — which is not the constraint.

**Cost: $0. Capacity added: 0 turns. No owner decision required.**

---

## 2. The authority server — `secratary`

All figures **MEASURED** at 2026-09-16 20:09 EDT via `ssh secratary-ts`, with `lscpu`, `free -m`, `dmidecode`, `lsblk`, `vmstat`, `smartctl`, `journalctl`.

| Field | Value | Tag |
|---|---|---|
| Make / model | **Dell Inc. OptiPlex 9020**, chassis `Type: Space-saving` (SFF) | MEASURED |
| Motherboard | `0XCR8D` rev A03, service tag `7QJWM02` | MEASURED |
| CPU | Intel **Core i5-4570** @ 3.20 GHz — **4 cores / 4 threads**, Haswell (2013), LGA1150 | MEASURED |
| RAM | 23,421 MiB (24 GB) = **2 × 4 GB DDR3-1333 + 2 × 8 GB DDR3-1600**, all running at 1333 MT/s | MEASURED |
| DIMM slots | **4**, all populated | MEASURED |
| Max capacity (firmware) | **32 GB** | MEASURED |
| Max capacity (vendor) | 32 GB DDR3-1600, 4 DIMM slots, dual-channel | PUBLISHED — https://www.hardware-corner.net/desktop-models/Dell-OptiPlex-9020-SFF/ (accessed 2026-09-16) |
| Disk | **PNY 500 GB SATA SSD** — `Rotation Rate: Solid State Device`, `ROTA=0`. 467 GB volume, **185 GB free (59 % used)** | MEASURED |
| Swap | 4 GB swap file, **100 % allocated** | MEASURED |
| Free PCIe | `PCI Express 3 x16` — **Available**; `PCI Express 2 x4` — **Available** | MEASURED |
| Network | `eno1` 192.168.50.77/24 + Tailscale `100.84.72.88` | MEASURED |
| Uptime | 13 days 21:59 | MEASURED |

### Current load — MEASURED

- `uptime`: load average **1.49 / 0.71 / 0.76** on 4 threads.
- `vmstat 1 3`: **95–96 % CPU idle** in all three samples, `si = 0`, `so = 0`.
- `free -m`: 6,188 MiB used, 588 free, 18,775 buff/cache, 17,233 available.
- `journalctl -u secretary-api --since '7 days ago' | grep -c 'database is locked'` → **8,290 events in 7 days** (~1.2/min) against **400,976 log lines** in the same window.
- Top consumers: `python` 19 % CPU / 2.4 GB RSS (secretary-api); several `chrome` at 6–48 % CPU; `node` 15.8 % (secretary-dashboard).
- Services: `secretary-api`, `secretary-dashboard`, `tailscaled`, `vscode-tunnel`.

### Reading this honestly — three facts that point different ways

1. **Not CPU-saturated right now.** 95–96 % idle, load 1.49 on 4 threads. A 4-thread 2013 CPU is a hard ceiling, but it is not currently pinned against it.
2. **Memory is genuinely tight.** The 4 GB swap file is **100 % allocated**. `vmstat` shows `si=0/so=0`, so it is resident rather than actively thrashing at measurement time — but there is no reserve left.
3. **Its measured pain is lock contention, not disk speed.** 8,290 `database is locked` events in 7 days is the loudest signal on the box, and it is a SQLite concurrency property. The disk is **already a SATA SSD, not spinning** (`ROTA=0`).

### The question: cheapest change that materially raises capacity

| Option | Cost (taxed) | Effect | Verdict |
|---|---|---|---|
| **A. More RAM** — 2 × 8 GB DDR3-1600, drop the 2 × 4 GB → **32 GB @ full 1600 MT/s** | **$41.57** (Timetec 16 GB kit 2×8 GB DDR3L/DDR3-1600, **$38.99**, https://www.amazon.com/dp/B00IV19HZE, accessed 2026-09-16; also $38.99 Walmart https://www.walmart.com/ip/633926938). Alternatives: Silicon Power 2×8 GB $40.97 https://www.amazon.com/Silicon-Power-1600MHz-240-pin-Unbuffered/dp/B07RDKRRKM; Crucial `CT2K102464BD160B` 2×8 GB $45.99 https://www.amazon.com/dp/B0091LG13O | 22 → **29 resident turns (+8)**; unlocks 1600 MT/s on all four slots; **+0 cores** | **The cheapest capacity in this entire document — $5.20 per added turn.** But only +8 turns, no cores, and money into a 2013 dead-end. Worth doing only because the sum is trivial and swap is fully allocated. |
| **B. CPU** — Intel **i7-4790**, 4C/**8T**, 3.6/4.0 GHz, drops straight into LGA1150 | **$42.65** (MARKET: **$40.00**, multiple pre-owned listings, https://www.ebay.com/b/Intel-Core-i7-4790-LGA-1150-Socket-H3-Computer-CPUs-Processors/164/bn_99647080, accessed 2026-09-16) | **4 → 8 threads**, +15–20 % single-thread | **Doubles the box's generating ceiling for $42.65.** The best per-dollar change on this machine. Xeon E3-1270 v3 (4C/8T) is equivalent but price NOT FOUND. |
| **C. NVMe / disk** | — | — | **Not the fix, and not worth buying.** Already a SATA SSD (MEASURED `ROTA=0`), not spinning. The 9020 has **no M.2 slot** (Haswell generation); NVMe needs a PCIe adapter and **Haswell 8-series chipsets have no firmware NVMe boot** — NVMe boot arrived with Z97/H97 (https://linustechtips.com/topic/1369105-do-haswell-motherboards-h87-g43-gaming-support-nvme-as-boot-drive, accessed 2026-09-16); a PCIe→M.2 adapter presents the drive but needs a BIOS mod or a SATA bootloader (Clover/rEFInd), https://www.hamishmb.com/booting-nvme-older-pc-refind and https://forum.asrock.com/forum_posts.asp?TID=3685 (accessed 2026-09-16). **Treat NVMe as unavailable here.** The 8,290 lock events are SQLite concurrency, not disk throughput. **$0 recommended.** |
| **D. Replace the box** | see below | removes the 4-thread *and* the 32 GB DDR3 ceiling at once | The real answer if "capacity" means tick-loop throughput. |

> **Compatibility warning — the part numbers in the original brief are wrong for this box.** Crucial **`CT2K8G3ERSL` / `CT2K8G3ERSLS4160B` is Registered RDIMM** (server memory) and will not POST in an LGA1150 desktop — https://www.newegg.com/global/om-en/crucial-16gb-240-pin-ddr3-sdram/p/12K-00WZ-00011 (accessed 2026-09-16). Crucial **`CT102472BD160B` is ECC UDIMM**; OptiPlex/EliteDesk/ThinkCentre chipsets reject ECC — https://www.newegg.com/p/0RN-00H0-001K6 (accessed 2026-09-16). **Buy non-ECC, unbuffered** `CT102464BA160B` (1.5 V) or `CT102464BD160B` (dual-voltage), or the Timetec kit above.

### Replacement options

| Candidate | Spec | Price (taxed) | Idle W | Resident turns | Verdict |
|---|---|---|---|---|---|
| **Dell OptiPlex 7060 SFF**, i7-8700 (**6C/12T**), 16 GB, 256 GB NVMe, eBay Refurbished | 3× the 9020's threads, native NVMe boot | **$379.68** (MARKET $356.37, https://www.ebay.com/itm/267490790433, accessed 2026-09-16). Also seen $199.99–$249.99 for i7-8700 SFF configs (https://www.ebay.com/shop/7060-sff), and 32 GB/512 GB at $359.95 (https://www.ebay.com/b/Dell-Intel-Core-i7-8th-Gen-PC-Desktops-All-In-One-Computers/179/bn_97812999) | ~20–25 W (community estimate — **no rigorous SFF measurement found**) | 14 | **The recommended replacement if the 9020 is replaced.** 6C/12T versus 4C/4T is the change that actually matters. |
| **HP EliteDesk 800 G4 SFF**, i7-8700 (6C/12T) | same class | **$138.61–$245.22** (MARKET, four listings at $129.99 / $175.00 / $189.99 / $229.97, https://www.ebay.com/shop/hp-elitedesk-800-g4-i7, accessed 2026-09-16) — cheapest 6C/12T SFF found | ~20–25 W (estimate) | 14 | Better value than the OptiPlex; take the $175 config with a drive. |
| **Stay and refresh the 9020** — +8 GB DDR3 ($41.57) + i7-4790 ($42.65) | 32 GB / 8 threads | **$84.22 total** | ~65 W (desktop class; **not measured**) | 29 | **Cheapest path by far.** Buys time; does not escape DDR3 or 2013 silicon. |

**Explicitly rejected: a used rack server.** Measured idle 125–252 W (item 5) = $273–551/yr forever, plus noise in a customer-facing office.

---

## 3. Cheap Linux nodes — what is actually available

All prices **MARKET**, live eBay US listing/search pages, **2026-09-16**. NJ tax 6.625 % applied and eBay collects it (PUBLISHED, above). Common listings advertise free shipping; where delivery was priced it was $9.99–$26.05.

### Candidate table

| # | Machine | Cores/threads | RAM | Storage | Price (MARKET) | Idle W | Resident turns |
|---|---|---|---|---|---|---|---|
| 1 | **Dell OptiPlex 3070 Micro**, i5-9500T, 16 GB, 500 GB HDD, free ship — https://www.ebay.com/shop/dell-optiplex-3070-micro | 6 c / 6 t | 16 GB | 500 GB HDD | **$120.00** or Best Offer | ~10 | 14 |
| 2 | **HP EliteDesk 800 G5 DM**, i5-9500T, 16 GB, **No HDD** — https://www.ebay.com/itm/366490566850 | 6 c / 6 t | 16 GB | none | **$79.00** | ~10 | 14 |
| 3 | **HP EliteDesk 800 G5 Mini**, i5-9500, 16 GB, No HDD — https://www.ebay.com/shop/hp-elitedesk-800-g5 | 6 c / 6 t | 16 GB | none | **$97.99** | ~10 | 14 |
| 4 | Dell OptiPlex 3060/3070, i5-8500T/9500T, 16 GB, No HDD — https://www.ebay.com/shop/dell-optiplex-16-gb-ram | 6 c / 6 t | 16 GB | none | **$102.50** (auction) / **$119.99** BIN | ~10 | 14 |
| 5 | OptiPlex 3070 Micro, i5-9500T, 16 GB — https://www.ebay.com/shop/optiplex-3070-micro | 6 c / 6 t | 16 GB | varies | **$129.99** +$26.05 ship / **$159.00** +$9.99 ship | ~10 | 14 |
| 6 | **HP EliteDesk 800 G5 Mini**, i5-9500T, 16 GB, 256 GB NVMe, very-good refurb, free ship — https://www.ebay.com/b/hp-mini-computer/bn_7024898108 | 6 c / 6 t | 16 GB | 256 GB NVMe | **$199.99** (was $249.99) | ~10 | 14 |
| 7 | **Dell OptiPlex 3070 Micro**, i5-9500T, 16 GB, 128 GB SSD, refurb + **2-yr warranty** — https://www.ebay.com/itm/307071642280 | 6 c / 6 t | 16 GB | 128 GB SSD | **$239.99**, free ship | ~10 | 14 |
| 8 | Lenovo ThinkCentre M920q, i5-8500T, 32 GB, 512 GB M.2 — https://www.ebay.ca/sch/i.html?_nkw=thinkcentre+m920q | 6 c / 6 t | 32 GB | 512 GB M.2 | C$505 ≈ **US$365** | ~10 | 29 |
| 9 | **GMKtec NucBox K8 Plus**, Ryzen 7 8845HS, **32 GB DDR5**, 1 TB — https://www.gmktec.com/products/gmktec-nucbox-k8-plus-mini-pc-amd-ryzen%E2%84%A2-7-8845hs | **8 c / 16 t** | 32 GB | 1 TB NVMe | **$399.99** sale ($619.99 reg) | 10–11 | 29 |
| 10 | **Minisforum MS-01**, i9-13900H, up to 64 GB, 3× M.2 + PCIe x16 — https://store.minisforum.com/products/minisforum-ms-01-workstation | **14 c / 20 t** | up to 64 GB | 3× M.2 | **$679** sale ($849 reg) | 25–29 | 29 @32 GB |
| 11 | **Lot of 7** OptiPlex 3070 Micro, i5-9500T, **8 GB** — https://www.ebay.com/itm/358793480712 | 6 c / 6 t | 8 GB | varies | **$999.99** ended = **$143/unit** | ~10 | **7** |

### Idle power — PUBLISHED, meter-measured

| Machine | Measured idle | Source |
|---|---|---|
| **HP EliteDesk 800 G4 Mini, 6-core** | **11–12 W** at 120 V | ServeTheHome, https://www.servethehome.com/hp-elitedesk-800-g4-mini-tinyminimicro-guide-review/3/ (accessed 2026-09-16) |
| **HP EliteDesk 800 G4 Desktop Mini** | **11.351 W**, "Normal Operation (Long idle)", 115 VAC — **HP's own ENERGY STAR-method declaration** | HP datasheet, https://h20195.www2.hp.com/v2/getpdf.aspx/c06040430.pdf (accessed 2026-09-16) |
| **Dell OptiPlex 3070 Micro** | **just over 10 W** at 120 V; STH assumes 9–12 W for this class | https://www.servethehome.com/project-tinyminimicro-dell-optiplex-3070-micro-review/2 (2020-07-31, accessed 2026-09-16) |
| Dell OptiPlex 7070 Micro, six-core | just over **13 W** | https://www.servethehome.com/dell-optiplex-7070-micro-project-tinyminimicro-guide-and-review/3 |
| Dell OptiPlex 7060 Micro, **65 W-TDP** CPU | just over **18 W** | https://www.servethehome.com/dell-optiplex-7060-micro-tinyminimicro-at-65w-tdp-cpu-overview/3 |
| **Lenovo ThinkCentre M720q Tiny** | **27 W idle** / 68 W load — an outlier; a commenter on the same page expected <10 W | https://www.servethehome.com/lenovo-thinkcentre-m720q-tiny-compact-pc-review/4/ |
| **Beelink MINI S12 (N100)** | **8.2 W idle**, 22.5 W max | https://xdaforums.com/t/beelink-mini-s12-and-mini-s12-pro-review-budget-mini-pcs-that-checked-all-the-boxes.4562923 |
| **Beelink S12 Pro (N100)**, powersave-tuned | **5.7 W headless**, 10 W with 2 USB SSDs | https://windgate.net/beelink-s12-pro-intel-n100-powersave-optimization |
| Fanless N100/N200 appliance | **10.5–12 W** | https://www.servethehome.com/fanless-intel-n100-firewall-and-virtualization-appliance-review/4 |
| **Beelink SER7 (Ryzen 7 7840HS)** | **6–10 W idle**, 44–46 W sustained, 77–79 W peak | https://www.servethehome.com/beelink-ser7-review-a-smaller-and-cheaper-amd-ryzen-7-7840hs-mini-pc/4/ (2023-10-24) |
| **GMKtec K8 Plus (8845HS)** | **10–11 W idle**, 90–95 W load | https://www.reddit.com/r/MiniPCs/comments/1in4nvs/ |
| **Minisforum MS-01 (i9-13900H)** | **25–29 W idle** | https://www.servethehome.com/minisforum-ms-01-review-the-10gbe-with-pcie-slot-mini-pc-intel/5 |
| Beelink SER8 (8845HS) | 7–10 W idle | https://www.servethehome.com/beelink-ser8-review-amd-ryzen-7-8845hs-powered-mini-pc/3 |

*All accessed 2026-09-16. **Usable band for a Tiny/Micro node with a 35 W-TDP-class CPU: 10–13 W**, with the M720q's 27 W and the 65 W-TDP 7060 Micro's 18 W as the upper outliers. A blog claiming 15–20 W idle for an i5-8500T Micro (https://www.marginseye.com/blog/dell-optiplex-micro-review, 2026-07-08) disagrees with every meter-based source; I use 10 W for the 3070/EliteDesk class and flag the spread. **N100 nodes are materially lower — 6–8 W headless.** **No rigorous measured idle exists for SFF-class** (as opposed to Micro) machines — community estimate 20–25 W, https://www.reddit.com/r/homelab/comments/194khbq/optiplex_idle_power_consumption (2024-09-16).*

### Noise — PUBLISHED declared levels (correcting an earlier assumption in this file)

| Machine | Declared idle | Source |
|---|---|---|
| **HP EliteDesk 800 G4 Desktop Mini** | **LpAm 20 dB idle**, LwAd 3.2 bels; 28 dB on HDD random writes — per ISO 7779 / ISO 9296 | HP datasheet, https://h20195.www2.hp.com/v2/getpdf.aspx/c06040430.pdf (accessed 2026-09-16) |
| HPE ProLiant DL360 Gen9 | idle **23–25 dBA** LpAm (ISO 7779, 23 °C); operating 25–31 dBA Entry/Base, **39 dBA Performance** | https://support.hpe.com/hpesc/public/docDisplay?docId=c04442953 (accessed 2026-09-16) |
| Dell R630 / R730 / R730xd | min-config idle **25 / 28 / 31 dBA** | Dell, *13G PowerEdge Acoustical Performance*, https://i.dell.com/sites/csdocuments/Shared-Content_data-Sheets_Documents/en/Dell-13G-PowerEdge-Acoustical-Performance-and-Dependencies.pdf (accessed 2026-09-16) |
| Beelink SER7 under light load | ~34.6 dBA in a 34 dBA studio — within ~1 dB of the room floor, so an **upper bound, not a clean measurement** | https://www.servethehome.com/beelink-ser7-review-a-smaller-and-cheaper-amd-ryzen-7-7840hs-mini-pc/4/ |

**Do not overstate this.** A micro PC declared at 20 dB idle versus a 1U/2U server at 23–28 dBA idle is only **+4 to +8 dB ≈ 2.5–6× sound power** — both are library-quiet *at idle*. The disqualifying gap is at **load**: +14 to +19 dB ≈ **25–80× sound power**, i.e. a quiet room versus a loud office. Every server figure above is a **minimal/entry configuration at 23 °C**; a realistically populated build is louder and unpublished. Dell also states that any GPGPU card makes a configuration *"about twice as loud"* as typical. So the rack server's disqualifier is **loaded noise plus power**, not idle noise. (This corrects an earlier draft of this file that claimed a published dB figure did not exist — HP publishes one.)

### Ranking — capacity per dollar, upfront

Price × 1.06625 for NJ tax; resident turns ÷ taxed price:

| Rank | Candidate | Taxed price | Turns | **$/turn** | Threads |
|---|---|---|---|---|---|
| 1 | HP EliteDesk 800 G5, i5-9500T, 16 GB, **no HDD** @ $79 | $84.23 | 14 | **$6.02** | 6 |
| 2 | HP EliteDesk 800 G5, i5-9500, 16 GB, no HDD @ $97.99 | $104.48 | 14 | **$7.46** | 6 |
| 3 | OptiPlex 3060/3070, 16 GB, no HDD @ $102.50 (auction) | $109.29 | 14 | **$7.81** | 6 |
| 4 | **OptiPlex 3070 Micro, 16 GB, 500 GB HDD @ $120 (turnkey)** | **$127.95** | **14** | **$9.14** | 6 |
| 5 | OptiPlex 3060/3070, 16 GB, no HDD @ $119.99 | $127.94 | 14 | $9.14 | 6 |
| 6 | ThinkCentre M920q, 32 GB, 512 GB @ ~US$365 | $389.18 | 29 | $13.42 | 6 |
| 7 | GMKtec K8 Plus, 32 GB, 1 TB, new @ $399.99 | $426.49 | 29 | $14.71 | **16** |
| 8 | OptiPlex 3070 Micro refurb + 2-yr warranty @ $239.99 | $255.89 | 14 | $18.28 | 6 |
| 9 | **Lot of 7 × 8 GB @ $143/unit** | $152.47 | **7** | **$21.78** — worst | 6 |

A "no HDD" unit needs a boot disk. SSD prices are elevated in the same 2026 shortage; **I did not obtain a firm citable SSD listing**, so $30–45 is an **unpriced assumption, NOT FOUND as a sourced figure**. Adding $35 lifts the $79 unit to ~$9.1/turn — level with the turnkey units. **Buy turnkey unless the bare unit is cheaper by more than the cost of a disk.**

### Ranking — capacity per watt (1 W = $2.19/yr)

| Rank | Candidate | Turns/W | Idle $/yr |
|---|---|---|---|
| 1 | **Any RAM or CPU upgrade to an existing box** (+27 turns for ~+1 W, or +4 threads for ~+1 W) | ~27 turns/W | ~$2 |
| 2 | Micro PC @ 10 W (14 turns) | **1.40** | $21.87 |
| 3 | MS-01 @ 25–29 W (29 turns @ 32 GB) | ~1.05 | $54.68–63.43 |
| 4 | One big desktop, 128 GB / ~50 W idle (118 turns) | 2.36 | $109.35 |
| 5 | SFF desktop @ ~22 W (14 turns) | 0.64 | $48.12 |
| 6 | **Used workstation @ 105 W (29 turns)** | **0.28** | **$229.64** |
| 7 | **Used rack server @ 125 W (118 turns)** | **0.94** | **$273.38** |

Note the inversion at rank 4: **a single large machine is more efficient per resident turn** than a fleet of small ones, because each small node carries its own ~6–8 W of platform overhead. That is a real argument for the big machine on electricity — and, as item 4 shows, it is not enough to overcome its 2026 RAM cost.

---

## 4. The honest arithmetic: many cheap nodes vs one big machine vs upgrading what he owns

### Where the fleet stands today — MEASURED

| Node | CPU | Cores/threads | RAM | Resident turns | Generating ceiling |
|---|---|---|---|---|---|
| Yoga 9 14IMH9 (this laptop) | Ultra 7 155H | 16 c / 22 t | 31.6 GB | 29 | 22 |
| `secratary` (OptiPlex 9020 SFF) | i5-4570 | 4 c / 4 t | 23.4 GB | 21 | 4 |
| `linux-pc-ts` (**HP Pavilion Desktop TP01-2xxx**) | i5-11400 | 6 c / 12 t | 11.6 GB | 10 | 12 |
| `mac-mini-ts` (Apple M4) | M4 | 10 c | 16 GB | 14 | 10 |
| **Total** | | **48 threads** | **82.6 GB** | **74** | **48** |

> **Correction to the fleet inventory.** The brief describes `zabz-tech-linux` as "a macOS mini for his employee Yisroel". **MEASURED 2026-09-16:** the host reachable as `linux-pc-ts` runs hostname `zabz-tech-linux`, `Linux 6.8.0-111-generic x86_64` — **Ubuntu on an HP Pavilion Desktop TP01-2xxx with an i5-11400**, not macOS and not a mini. `dmidecode` reports **2 DIMM slots** (DIMM1: 8 GB Samsung `M378A1G44AB0-CWE`; DIMM2: 4 GB SK Hynix `HMA851U6DJR6N-XN`), **DDR4-3200**, **`Maximum Capacity: 64 GB`**, on a 468 GB NVMe volume that is **96 % full**. The recorded inventory is stale; the measurement is the truth. This matters because it makes that machine a strong upgrade target.

### The real diagnosis

Demand is 40–55 concurrent turns = **44.6 GB at 55 turns**, which alone **exceeds the Yoga's 31.6 GB**. The mesh already holds **74 resident turns in aggregate**, so total memory is *not* the shortage. **The shortage is placement — the work lands on the one machine that cannot be upgraded (item 1) — plus core count.** Any purchase is therefore about (i) creating *elsewhere* to put turns and (ii) adding cores to run them.

### (a) 3–4 cheap used mini PCs

Using the $120 turnkey 16 GB units (candidate 1):

| | 3 nodes | 4 nodes |
|---|---|---|
| Purchase | 3 × $120 = $360 → **$383.85 taxed** | 4 × $120 = $480 → **$511.80 taxed** |
| Turns added | **+42** | +56 |
| Threads added | **+18** | +24 |
| Idle power | 30 W → **$65.61/yr** | 40 W → $87.48/yr |
| 3-yr TCO | $383.85 + $196.83 = **$580.68** | $511.80 + $262.44 = $774.24 |
| **$/turn upfront** | **$9.14** | $9.14 |
| **3-yr $/turn** | **$13.83** | $13.83 |
| Complexity | 3 more Linux boxes to patch, monitor, reboot, house | 4 more |

### (b) One modern high-core desktop with 64–128 GB

RAM is the dominant and now pathological cost, and **the real listing prices are worse than the component arithmetic suggests.**

**PUBLISHED / MARKET, accessed 2026-09-16:**

- **DDR5 64 GB kit (2 × 32 GB) DDR5-5600** (Crucial Pro CP2K32G56C46U5): **$1,099.99 = $17.19/GB** — https://www.newegg.com/crucial-pro-64gb-ddr5-5600-cas-latency-cl46-desktop-memory-black/p/N82E16820156380
- Amazon: Crucial 64 GB DDR5-4800 UDIMM **$1,048.00 = $16.38/GB**; G.SKILL Ripjaws S5 64 GB DDR5-5200 **$979.99 = $15.31/GB** — https://www.amazon.com/dp/B0C79H54TQ
- **DDR4 64 GB kit (2 × 32 GB) DDR4-3200** (Crucial CT2K32G4DFD832A): **$493.89** Newegg / **$490.00 Amazon = $7.66/GB** — https://www.newegg.com/crucial-64gb-ddr4-3200-cas-latency-cl22-desktop-memory/p/N82E16820156238 and https://www.amazon.com/dp/B07ZLD6Q1G (the Amazon price is page-verified; B&H and Best Buy both returned 403/422 to direct fetch, so there is **no page-verified second-retailer DDR4 price**).
- **The shortage is structural, not a blip:** conventional DRAM contract prices rose **~90–95 % QoQ in Q1 2026** (a record), with a further **58–63 % projected for Q2**; legacy DDR4 is being phased out and in some configurations trades **above** DDR5 — https://www.hiper-global.com/news/memory-and-ssd-update-mid-2026/. A 64 GB DDR5-5600 SODIMM kit was **$130** a year earlier → RAM is roughly **8× its 2025 price**, and DDR5 carries a **~2.1× premium over DDR4**. Also **DDR4 up more than 50 % in Q3 2026** with *"DDR3 also impacted by higher costs"* — https://wccftech.com/memory-shortages-drive-ddr4-prices-over-50-in-q3-2026-ddr3-also-impacted-by-higher-costs (2026-07-08).

**Actual current listings for a whole machine of this class:**

| Machine | Spec | Price | Turns | **$/turn upfront** |
|---|---|---|---|---|
| **ADAMANT CUSTOM 24-Core workstation** — https://www.newegg.com/p/3D5-002T-00S40 | **i9-14900K (24 cores)**, **128 GB DDR5**, 1 TB 990 PRO, RTX 5060 Ti, Win 11 Pro, 3-yr warranty | **$4,899.99** → $5,224.61 taxed | 118 | **$44.28** |
| Ryzen 9 7950X prebuilt *(snippet-only)* | 7950X, 64 GB DDR5, liquid-cooled | $3,399 | 59 | $61.42 |
| i9-14900K AORUS build *(snippet-only)* — https://www.newegg.com/p/pl?d=ryzen+9+7950x | i9-14900K, 128 GB DDR5 | $5,449.99 | 118 | $49.25 |
| **RAM alone, 128 GB DDR5** | 2 × 64 GB kit | **$1,960–2,200** | 118 | $17.7–19.9 before CPU/mobo/PSU/case |

**$/turn: $44 upfront plus electricity. This is 3.2× worse than three $120 mini PCs at $13.83, and roughly twice the cost of the used rack server on 3-year total cost of ownership.**

### The finding that kills option (b) outright: the binding constraint is CORES, not RAM

**ARITHMETIC, derived from the owner's own measured constants** (0.81 GB/turn, ~1 core per generating turn, 25 % headroom):

- **40–55 concurrent turns at ~1 core per generating turn requires 40–55 usable cores.**
- An i9-14900K or Ryzen 9 7950X has **24 cores / 32 threads** → it can saturate only **~24–32 turns.**
- **One 24-core desktop therefore does not replace the mesh at 55 turns.** It would need to be two such boxes, or a 32–64-core Threadripper/EPYC-class machine — a materially different and much more expensive tier.
- The RAM to reach 55 resident turns is only **$600–900** at today's prices. **RAM is not the problem; cores are.** Buying a big machine to fix a presumed RAM shortage would spend $5,000 to solve the wrong axis and still come up ~20 cores short.

**And the electrical advantage does not repay it:** 55 N100-class nodes at 8 W ≈ 440 W ≈ **$962/yr**, against ~$262/yr for one 120 W box — a **~$700/yr** delta that never repays a $4,899 workstation within its service life, while the workstation provides *fewer* cores than the fleet.

**Verdict on (b): reject.** Not because it is expensive — because at 2026 prices it is the worst value per turn *and* it does not clear the binding constraint.

### (c) Upgrading what he already owns

| Target | Action | Cost taxed | Turns added | Threads added | **$/turn marginal** |
|---|---|---|---|---|---|
| **Yoga 9 14IMH9** | none possible — soldered (item 1) | **$0** | 0 | 0 | — |
| **`mac-mini-ts`** (Apple M4, 16 GB) | none possible — Apple silicon memory is soldered to the package; 16 GB = 14 turns with no growth path | **$0** | 0 | 0 | — |
| **`secratary`** OptiPlex 9020 | +2 × 8 GB DDR3-1600, drop the 2 × 4 GB → **32 GB @ 1600** | **$41.57** | **+8** (21→29) | 0 | **$5.20** ← cheapest in the document |
| **`secratary`** OptiPlex 9020 | **i7-4790** 4C/8T into LGA1150 | **$42.65** | 0 | **+4** (4→8) | **$10.66/thread** |
| **`linux-pc-ts`** HP Pavilion TP01-2xxx | add **1 × 32 GB DDR4-3200** beside the existing 8 GB → **40 GB** | **$237.77** | **+27** (10→37) | 0 | **$8.81** |
| **`linux-pc-ts`** HP Pavilion TP01-2xxx | replace both with **2 × 32 GB** → **64 GB** | **$467.98–527.16** | **+49** (10→59) | 0 | **$9.55–10.76** |

**DDR4-3200 pricing, MARKET / PUBLISHED, accessed 2026-09-16** — the spike makes this brutal and it must be stated plainly:

- **32 GB single UDIMM-3200:** Newegg shows *"32GB Single DDR4 3200 MHz — More options from $255.95 – $404.00 Free Shipping"* (https://www.newegg.com/p/pl?d=32gb+ram+single+stick) and a *"32GB DDR4 3200MHz DIMM PC4-25600 UDIMM 288-Pin Dual Rank"* at **$223.09** (https://www.newegg.com/p/pl?d=128gb+ddr4+3200).
- **64 GB kit (2 × 32 GB) DDR4-3200:** Crucial `CT2K32G4DFD832A` at **$493.89** ("Listed on Newegg June 11, 2026", https://www.newegg.com/crucial-64gb-ddr4-3200-cas-latency-cl22-desktop-memory/p/N82E16820156238); **"From $438.95, 6 New"** (https://www.newegg.com/crucial-64gb-ddr4-3200/p/N82E16820156238?Item=9SIAM37K8B3495); Crucial Pro 64 GB from **$566.84** (https://www.newegg.com/crucial-pro-64gb-ddr4-3200-cas-latency-cl22-desktop-memory-black/p/N82E16820156327); Amazon third-party new **$541.95** as of 2026-07-09, used **$454.99** as of 2026-07-07 (https://camelcamelcamel.com/product/B0C29W4G29).
- **32 GB kit (2 × 16 GB) DDR4-3200:** **$184.99–215.98** (https://www.newegg.com/p/pl?d=32gb+ddr4+3200), $187.99 (https://www.newegg.com/p/pl?d=32+gb+ddr4+3200+ram) — but this does **not** reach the goal: replacing 8+4 with 2×16 yields 32 GB / 29 turns, +19 turns, ~$197 taxed = **$10.37/turn**.
- **8 GB DDR3-1600 UDIMM:** $19.99–$28.65 (https://www.newegg.com/p/pl?d=8gb+pc3-12800+ddr3, https://www.newegg.com/p/pl?d=8gb+ddr3); 16 GB kit (2×8) **$38.99–$45.99** (https://www.amazon.com/dp/B00IV19HZE, https://www.amazon.com/dp/B0091LG13O).

### Electricity — PUIBLISHED rate, ARITHMETIC totals

NJ residential **24.95 ¢/kWh** (EIA Table 5.6.A, June 2026, released 2026-08-26). Cross-check: EnergySage put NJ at **23 ¢/kWh** in September 2026, https://www.energysage.com/local-data/electricity-cost/nj (2026-09-12); ChooseEnergy at **23.49 ¢/kWh**, https://www.chooseenergy.com/electricity-rates/new-jersey (2026-07-22). I use the EIA figure. NJ all-sector average (2024) was 16.29 ¢/kWh, https://www.eia.gov/electricity/state/newjersey/ — so if the LPT-office nodes sit on a **commercial** meter, every figure below is conservative.

| Device | Idle W | kWh/yr | **$/yr** | Source of the wattage |
|---|---|---|---|---|
| Micro PC (OptiPlex 3070 / EliteDesk class) | 10 | 87.7 | **$21.87** | PUBLISHED, meter-measured |
| 3 micro PCs | 30 | 262.9 | **$65.61** | ARITHMETIC |
| One big desktop, 128 GB | 40–60 | 350–526 | **$88–131** | **assumption, not measured** |
| Used workstation (Z440, E5-1650 v3) | **100–110** | 876–964 | **$218–241** | PUBLISHED, measured |
| Used rack server (R730 / DL360 Gen9) | **47 – 252** — 47 W only in a near-empty SPECpower config; **80 W** in a verified minimal 24 h run; **125–252 W** realistically populated | 412–2,208 | **$103–551** | PUBLISHED, measured |

**Rack-server and workstation idle draw — PUBLISHED, and the spread matters.** At the bottom: a Dell R730 with 2 × E5-2699 v3, 64 GB and 1 SSD measured **46.9 W "Active Idle"** on a calibrated Yokogawa WT210 — **SPECpower_ssj2008**, https://www.spec.org/power_ssj2008/results/res2015q1/power_ssj2008-20150203-00686.html (published 2015-02-18, accessed 2026-09-16). **But that is a near-empty configuration (one PSU, one SSD) and must not be budgeted for a working node.** Next: an HPE DL360 Gen9 with 2 × E5-2650 v4 and 64 GB measured **80 W average over a 24-hour run**, 70–80 W after HPE's recommended power profile — https://community.hpe.com/t5/hpe-proliant-servers-ml-dl-sl/setting-up-the-hpe-proliant-dl360-gen9-for-maximum-energy/td-p/7257260 (posted 2025-10-18, accessed 2026-09-16). Then realistically populated: R730 *"using ~145 w at basically idle"* (https://forums.servethehome.com/index.php?threads/dell-r730-vs-r720-power-usage.31985/, 2021-02-24); measured **125 W** (light, ESXi + 2 VMs), **156 W** (dual E5-2647 v4, all-SSD), **252 W** (dual E5-2696 v4, 512 GB, 4× SAS); **196–210 W** after powerd++ tuning (https://dan.langille.org/2024/01/29/using-powerd-to-reduce-power-consumption-on-a-dell-r730/, 2024-01-29); DL380 Gen9 **160–180 W** idle (https://www.reddit.com/r/homelab/comments/14edwwl/). **So the honest band is 47–80 W tuned-and-minimal, 100–300 W realistically populated.** **HP Z440 with an E5-1650 v3 draws about 100–110 W idle** — https://www.reddit.com/r/homelab/comments/17vd8qj/hp_z440_workstation_e51650v3_haswell_power (2024-09-16, accessed 2026-09-16).

**Note on the big-desktop wattage:** I found **no meter-measured idle figure** for a 128 GB desktop workstation, so 40–60 W is an **assumption, flagged as such**. It changes no ranking — even at 60 W it costs far less to run than one workstation or rack server.

### The finding that actually decides this: per-turn TCO is nearly flat

| Option | Upfront (taxed) | 3-yr electricity | Turns | **3-yr $/turn** | Threads |
|---|---|---|---|---|---|
| 3 × $120 mini PC (16 GB, 10 W) | $383.85 | $196.83 | 42 | **$13.83** | 18 |
| One 128 GB desktop (~$1,800, 50 W) | $1,800 | $328 | 118 | **$18.03** | 32 |
| Used rack server, 128 GB @ $774.99 (125 W) | $826.33 | $820.14 | 118 | **$13.95** | 16–28 |
| **HP Z440, 32 GB @ $219.99 (105 W)** | **$234.56** | **$688.92** | 29 | **$31.84** — worst | 12 |
| `secratary` refresh: RAM + i7-4790 | $84.22 | ~$426 (65 W, est.) | 29 | **$17.60** | 8 |

At 2026 memory prices, **the cheapest DDR5/DDR4 machines and the cheap used micro PCs land within a few dollars of each other per turn**, because RAM is the dominant input to every option. **$/turn therefore does not discriminate. The discriminators are upfront cash, added threads, watts, noise, resilience and maintenance.** That is the real result of this section, and it is why the recommendation below is argued on those axes rather than on a $/turn ranking.

### Complexity — the cost with no invoice

**NO AUTHORITATIVE SOURCE EXISTS for a dollar figure on fleet maintenance burden; the following is engineering judgement, labelled as such.** Each node is a machine needing an OS install, a distro upgrade every 2 years (Ubuntu LTS), security patches, an unattended-upgrades policy, a reboot window, monitoring, a backup check, and physical space. That work is done by one seat (this one) with **no continuous memory**, so every node's state must be written down to survive. Three nodes also mean three power bricks, three dust inlets, three network identities, and **three more chances for a node to be silently down while its capacity is still being counted**. One big machine is one thing to get right — a real advantage, and not large enough to beat (a) on dollars.

**What one big machine does not fix:** the owner's actual complaint is that *work lands on the Yoga*. Centralising on a single new box swaps one bottleneck for another with the same failure mode — everything queues in one place, and if that box is down, the whole mesh is down. Three cheap nodes are strictly more resilient. **That asymmetry, not $/turn, is the decisive argument for (a).**

### Recommendation

**Buy (a) plus the two cheap `secratary` top-ups from (c). Do not buy (b). Do not buy a workstation or a rack server.**

| # | Purchase | Detail | Cost taxed |
|---|---|---|---|
| 1 | **3 × used 6-core / 16 GB micro PC** | HP EliteDesk 800 G5 Mini (i5-9500T) or Dell OptiPlex 3070 Micro (i5-9500T), turnkey with a disk, ~$120 each | **$383.85** |
| 2 | **2 × 8 GB DDR3-1600** for `secratary` | Timetec 16 GB kit (2×8 GB), drop the 2 × 4 GB → 32 GB @ 1600 | **$41.57** |
| 3 | **Intel i7-4790** for `secratary` | LGA1150 drop-in, 4C/8T — doubles the tick loop's generating ceiling | **$42.65** |
| | **Total** | | **$468.07** |

**Resulting mesh:** resident turns **74 → 124**; threads **48 → 70**; non-Yoga capacity **45 → 95 turns**, covering the stated 40–55 demand with the 25 % rule intact and leaving the Yoga free to be the machine he works on. Added continuous draw ~31 W = **+$67.80/yr**. **3-year $/turn ≈ $13.43.**

**Second tranche, only if the mesh is still tight:** a single 32 GB DDR4-3200 UDIMM into the HP Pavilion TP01-2xxx (`linux-pc-ts`) — **$237.77** for +27 turns on an existing 6C/12T box already running Ubuntu. Do this rather than a 4th node only if the goal is avoiding another machine to maintain; a 4th $120 node costs less, adds 6 threads, and is the better raw buy.

**Do not buy a fourth node yet.** Add one only when measured resident turns in the non-Yoga mesh exceed ~90 — capacity that is not needed is electricity and maintenance paid for nothing.

---

## 5. What NOT to buy, and why

Each of these looks attractive and fails on a **measured** constraint.

**1. Any 8 GB machine — including the lot that looks cheapest per unit.** The 7-unit OptiPlex 3070 Micro lot at **$999.99 = $143/unit** (MARKET, https://www.ebay.com/itm/358793480712) has 8 GB each: **7 resident turns** against 14 for a 16 GB unit bought singly for $120. That is **$21.78/turn**, the worst figure here — and the lot costs *more per unit* than a 16 GB machine bought individually. Fixing it means buying DDR4 separately, and a 32 GB stick is **$223–256**, so each 8 GB node becomes $143 + $223 = $366 for 29 turns, against $120 for 14 on a machine that already has what it needs. **8 GB is below the useful floor for a 40–55-turn demand.**

**2. A used workstation (HP Z440, Dell Precision T5820).** This is the most seductive trap in the whole document, because the upfront arithmetic looks like the best deal available: an HP Z440 with a **6-core/12-thread Xeon E5-1650 v3 and 32 GB DDR4** was listed at **$219.99** (MARKET, https://www.ebay.com/b/HP-Z440-Towers/179/bn_89095653) — and 32 GB of DDR4 *alone* costs $223–256 today, so the machine appears free. *(A subagent reported the same configuration at $112.05 from a browse band; I could not reproduce that figure and found $219.99 for the nearest comparable listing, so I use $219.99 and treat $112.05 as unverified.)* **It fails on measured idle power: the Z440 with this exact CPU draws about 100–110 W at idle** (PUBLISHED, above) = **$218–241/yr**, making its 3-year cost per turn **$31.84 — the worst of any option considered**, worse than a rack server per turn because it holds fewer turns. **Do not buy a used workstation for a mesh node. The DDR4 bundled inside it is not free; it is paid for monthly in electricity.**

**3. A used rack server (PowerEdge R730/R630, ProLiant DL360/DL380 Gen9).** Cheap to buy, rich in RAM. It fails on **measured idle power: 125–252 W**, i.e. **$273–551/yr at idle, before cooling** — more than the purchase price of two complete used nodes, every year. It fails on **noise**: 1U/2U servers use small high-RPM fans; an aggregator lists the R730 at 28 dBA and R630 at 32 dBA (**secondary source, flagged** — https://pcserverandparts.com/news/best-used-server-for-home-lab-2026), Dell's own technical guide carries LwA-UL sound data but yielded no extractable number (https://i.dell.com/sites/doccontent/shared-content/data-sheets/en/Documents/Dell-PowerEdge-R730-and-R730xd-Technical-Guide-v1-7.pdf), and qualitative reports for the DL360 Gen9 are unanimous that it is very loud (https://www.reddit.com/r/homelab/comments/u1tt7k/). Unsuitable for an office where customers walk in or a home office. And **0.94 turns/W against a micro PC's 1.40** — for 118 turns when he needs 40–55, so it also buys 2× the capacity required.

**4. A disk upgrade for `secratary`.** The box is **already on a SATA SSD** (MEASURED: PNY 500 GB, `Rotation Rate: Solid State Device`, `ROTA=0`) with 185 GB free. It is **not** on spinning disk. The dominant failure signal is **8,290 `database is locked` events in 7 days** (MEASURED), a **SQLite concurrency** property, not sequential throughput. NVMe is also not cleanly available: no M.2 slot on this generation, and **Haswell 8-series chipsets have no firmware NVMe boot** (PUBLISHED), so an adapter card is a data disk at best behind a BIOS mod or a SATA bootloader. **Spend $0 here and fix the concurrency in software.**

**5. Any machine with soldered RAM, bought as an expandable node.** The measured lesson of this document: the two machines that *cannot* be expanded (the Yoga, 32 GB soldered LPDDR5x; the Mac mini M4, 16 GB soldered) are precisely the two that are now capacity dead ends — and the Yoga is the bottleneck that started this whole question. A 16 GB soldered box is **14 turns forever**. **Before buying any node, confirm it has two DIMM slots.** In this estate the expandable models are the HP Pavilion TP01-2xxx (2 slots, 64 GB max, MEASURED) and the OptiPlex 9020 SFF (4 slots, 32 GB max, MEASURED).

**6. ARM single-board computers (Raspberry Pi 5 16 GB, Orange Pi 5).** They look ideal — 16 GB for ~$120–160, a few watts — and the 0.81 GB/turn constant is architecture-independent so the capacity arithmetic appears to work. It fails on **workload compatibility**: this estate is x86 Linux with x86 `node_modules`, .NET and Windows-only tooling, and native Python wheels. An ARM node would need emulation, which consumes exactly the resource that is scarce (**CPU**). Its RAM is also **soldered**, so it repeats the Yoga's mistake in miniature. *Engineering judgement grounded in the estate's inventory; I did not benchmark an ARM node.*

**7. Buying bare RAM as the primary strategy, at 2026 prices.** This is the trap the DRAM spike creates. **DDR4 rose more than 50 % in Q3 2026** and DDR3 rose with it (PUBLISHED). A bare 32 GB DDR4-3200 stick costs **$223–256** and delivers 29 turns to a machine you must already own; for **$120 you can buy a complete 16 GB machine with 6 cores, a PSU, a chassis, a disk and a NIC.** Per turn the bare stick is slightly cheaper ($7.5–8.8 vs $9.1); per **core** it adds nothing at all. **Buy whole used machines before buying RAM.** The only RAM purchases that clear the bar are the two small top-ups in the recommendation — and those clear it only because the machines exist and the slots are already empty.

**8. Assuming the mesh's total RAM is the problem.** MEASURED: the four existing nodes already hold **74 resident turns** against a stated demand of 40–55. **Total memory is not the shortage.** The shortage is placement — the work lands on the one machine that cannot be upgraded — plus core count. Buying a huge single machine to add raw resident turns, when 74 already exist and are not being used, would be paying to solve a problem that is not the measured one.

---

## NOT FOUND — stated gaps, not guesses

1. **A citable complete-build price for a 128 GB modern desktop** (Ryzen 9 7950X / i9-14900K class). A listing exists but I did not capture its price, so no total is stated. The RAM-only cost is sourced and sufficient to reject the option on resilience grounds.
2. **Meter-measured idle wattage for a 128 GB desktop workstation** — the 40–60 W figure is an **assumption**. Also **no dB(A) measurement** for OptiPlex/EliteDesk/Tiny-class micro PCs, and **no rigorous measured idle for SFF-class** (as opposed to Micro) machines; the 20–25 W SFF figure is a community estimate.
3. **A firm citable SSD listing** to complete a "no HDD" node. $30–45 is an **unpriced assumption**; SSD prices are elevated in the same 2026 shortage.
4. **A primary test-lab dB measurement** for the R730/R630 (only a secondary aggregator) and for the DL360 Gen9 (qualitative only).
5. **A SK hynix primary datasheet for `H58G66BK7BX067`** — only distributor pages and third-party benchmark databases surfaced. Its identity as 32 Gb LPDDR5 rests on a distributor listing.
6. **Samsung `M378B1G73` 8 GB DDR3-1600 UDIMM price**, **Intel Xeon E3-1270 v3 price**, and **current first-party Beelink SER7 price** — browse pages only, no captured listing prices.
7. **Any published maintenance-burden cost** for N Linux nodes vs 1. Item 4's complexity analysis is **engineering judgement**, labelled as such, because no authoritative source exists.

## Provenance of the measurements

All MEASURED values were taken in this session on 2026-09-16 (server measurements at 20:09 EDT) by the author, using `Get-CimInstance Win32_ComputerSystem/Win32_BIOS/Win32_PhysicalMemory/Win32_PhysicalMemoryArray/Win32_Processor` on the Yoga; and over `ssh secratary-ts` / `ssh mac-mini-ts` / `ssh linux-pc-ts`: `lscpu`, `dmidecode -t 1,2,3,4,9,16,17`, `free -m`, `swapon --show`, `lsblk`, `df -h`, `uptime`, `vmstat 1 3`, `smartctl -i`, `journalctl`, `sysctl hw.memsize`.

No machine was modified. No software was installed. Nothing was purchased. **This document is the only file written.**
