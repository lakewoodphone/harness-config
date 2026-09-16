# 40 — Hardware Costs: Home-Office + LPT-Office AI Agent Mesh

## CORRECTIONS APPLIED 2026-09-16 (verification pass — see 60-verification.md)

A second agent re-measured this document's load-bearing numbers against the machine's own longitudinal
record (`~/.dsh/metrics/harness-metrics.csv`, 477 rows, 2026-09-16 12:56:55–17:47:41Z) and against live
counters on `ZABZ-YOGA` at 21:44–21:56Z. **The costing constant this entire document is built on — "one
actively generating agent turn = 0.81 GB" — did not survive.** It is not a measurement made by this
document, or by any document in this wave: it is one line inherited from `docs/dsh-at-scale/PROGRAM.md:75`,
tagged PRIOR-MEASURED by `20-placement.md:665`, and then used here under the heading **"Costing
constants"** with no tag at all. The corrections below are applied in place; prose that used the old
constant is left visible and marked `[corrected 2026-09-16: was X]`, so the error stays legible.

| # | Old value (in this document) | Corrected value | Evidence |
|---|---|---|---|
| 1 | **0.81 GB commit per generating turn** (`:22`, `:23`), the basis of every "resident turns" number | **≈0.58 GB commit per extra node PROCESS** (r = 0.937), with an **idle commit floor of ≈17–18.4 GB already resident** before any work. "Generating turns" is not the unit this machine recorded; see `60-verification.md` §2.2 | least-squares over 477 rows of `~/.dsh/metrics/harness-metrics.csv`: `corr(commit_gb,node)=0.937`, slope `0.5754`; commit at `engines≤13` never exceeded 19.11 GB while the idle floor with 9–13 processes resident was 17.0–18.4 GB |
| 2 | **"Resident turns" as the capacity unit** (`:31–41`, `:270–274`, `:409`) | **The wrong unit on its own.** It is a MEMORY limit, and this document's own `:43` says capacity is `min(resident turns, cores that can generate)`. The corrected tables print **both** and take the `min`. `secratary` moves **21 → 4** | this document `:43` vs `:271`, which prints "Resident turns 21" and "Generating ceiling 4" in adjacent columns unreconciled; and `:329` ("requires 40–55 usable cores") |
| 3 | `31.6 GB → 29 resident turns` (`:37`) | **≈12 resident turns; 22 is the core ceiling** | `(0.75 × 31.61 − 18.0) / 0.58 = 12` |
| 4 | `8→7 / 16→14 / 32→29 / 64→59 / 128→118` (`:33–41`) | **5 / 11 / 23 / 46 / 92** — subtract the measured floor, then divide by 0.58 | same command; old formula `0.75×RAM/0.81`, corrected `(0.75×RAM − 18)/0.58` |
| 5 | `:274` "Resident turns **74**" over four nodes | **74 resident / ~30 generating** — the `min` of `:43` applied row by row (29→22, 21→4, 10→10, 14→10) | `60-verification.md` §2.4 |
| 6 | `:280` "Demand is 40–55 concurrent turns = **44.6 GB at 55 turns**" | **The demand figure is asserted, never measured, and is derived from the constant corrected in row 1.** Treat 40–55 as an unvalidated input until `sessions.agentLoopsRunning` in `/healthz` measures it | `60-verification.md` §2.3 and §6.2 — no document in the wave measures demand |
| 7 | "**1,596 %** disk time" (`20-placement.md:178`, `:716`, `:802`, `:845`; cross-referenced here) | **Not a possible reading of `\PhysicalDisk(_Total)\% Disk Time` on this machine — it has exactly ONE physical disk and ONE volume**, and no document in the wave names the counter it came from. **The underlying condition is real and was re-measured: 4.48 % avg in a quiet window, 97.31 % avg seven minutes later.** Cite the saturation and the queue length, never the 1,596 % | `Win32_DiskDrive` → 1 device; `Get-Volume` → 1 volume; `Get-Counter '\PhysicalDisk(_Total)\% Disk Time'` min 2.83 / avg 4.48 / max 6.15 at 21:46Z, **avg 97.31** at 21:53Z |
| 8 | `:329` "40–55 concurrent turns at ~1 core each requires 40–55 usable cores" | **The CORES conclusion STANDS** — it is the best-supported claim in this document. Only the per-turn memory constant behind it is corrected | `60-verification.md` §3 C6 |
| 9 | `:274` totals "**82.6 GB / 48 threads**" over four nodes | **Scope it explicitly.** The roster is SEVEN machines; measured total ≈155 GB (≈113 GB excluding the two Hetzner boxes, which have no `node`) | `20-placement.md:51–57`, `10-inventory.md:594–602` |
| 10 | soldered-RAM verdict (§1, `:67`) | **Stands, and gains independent evidence:** `Win32_PhysicalMemoryArray.MaxCapacityEx = 32 GB` equals exactly what is installed, so there is no headroom even if a slot existed | `(Get-CimInstance Win32_PhysicalMemoryArray).MaxCapacityEx` → `33554432` KB |

**What did NOT change, and this matters as much as what did.** The RAM-is-soldered verdict (§1), the
`secratary` OptiPlex 9020 identification and its DDR3 + i7-4790 upgrade arithmetic (§2), the used-workstation
and rack-server rejections (§5.2, §5.3), the electricity rate and every per-watt ranking (§3, §4), and the
**direction** of the recommendation — **cores, not RAM, bind** — all survive re-measurement. Row 8 is why:
§4 reaches the right conclusion by the right argument. What fails is the number this document attaches to a
turn, and therefore the size of the capacity it believes it is buying.

**One sentence you can rely on instead of the constant:** *on this machine, ≈18 GB of commit is already
resident before any work, and each further node process costs ≈0.58 GB; commit exceeds the 31.61 GB of
physical memory somewhere above ~45 node processes, and the machine has been observed at 36.49 GB commit
with 58 of them and 62,865 page-ins/s.*

---

**Written:** 2026-09-16 · **Author:** Zabz (delegated research session)
**Scope:** costed, evidence-backed hardware plan. No purchase, no install, no machine modified. This file is the only thing written.

> **Revision note, 2026-09-16.** This document was revised in place after a second verification pass returned prices read from **directly fetched** listing pages. Three first-draft claims were wrong and are corrected, marked inline where they appear: (1) a "$120 turnkey 16 GB node" was a **search snippet only** and could not be reproduced — the verified floor for a 16 GB node is **$150**, which changes the recommended purchase; (2) **HP EliteDesk 800 G5 Mini supports 64 GB, not 32 GB**; (3) the first draft said no published micro-PC noise figure existed — **HP publishes one (20 dB LpAm idle)**. All figures below that carry `[F]` were read on a fetched page; `[S]` marks snippet-only. **A number that could not be sourced is recorded as NOT FOUND rather than estimated.**

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

- One actively generating agent turn = **0.81 GB** commit and **~1 core** while generating. `[corrected 2026-09-16: was 0.81 GB, unqualified. This line is NOT a measurement made by this document — it is inherited from `docs/dsh-at-scale/PROGRAM.md:75` and re-quoted. This machine's own sampler record REFUTES it as a marginal cost: commit tracks the node PROCESS count at ≈0.58 GB per process (r = 0.937, 477 rows of ~/.dsh/metrics/harness-metrics.csv), and the idle floor is ≈17–18.4 GB before any work. Use `(0.75 × RAM − 18) / 0.58` and treat the result as a MEMORY ceiling only. Source: 60-verification.md §2.2.]`
- **25 % headroom rule:** usable RAM = `0.75 × installed`; resident turns = `floor(0.75 × RAM_GB / 0.81)`. `[corrected 2026-09-16: was `floor(0.75 × RAM_GB / 0.81)`. Corrected: `floor((0.75 × RAM_GB − 18) / 0.58)`, because the old form assumes a node starts at ZERO commit and divides by a per-turn cost the sampler does not support. On this laptop the old form gives 29 and the corrected form gives 12. Source: 60-verification.md §2.2.]`
- **The unit is wrong on its own.** `[added 2026-09-16]` A "resident turn" is a MEMORY figure. §4 of this document — correctly — says the binding constraint is CORES, and `:43` below already states the rule: capacity is `min(resident turns, cores that can generate)`. Everywhere a resident-turn number appears below, read it as the memory half of a `min()`, never as capacity. `secratary` is the case that matters: **21 resident turns and 4 cores is 4 usable generations, not 21.** Source: 60-verification.md §2.4.
- **Electricity: New Jersey residential 24.95 ¢/kWh** — **PUBLISHED**, EIA *Electric Power Monthly* Table 5.6.A, data for **June 2026**, released 2026-08-26, https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a (accessed 2026-09-16). US residential average 18.34 ¢/kWh, +5.0 % YoY — https://www.eia.gov/electricity/monthly/update/end-use.php (accessed 2026-09-16).
- **New Jersey *commercial* rate, same table and period: 18.47 ¢/kWh.** Use this if the Lakewood office is on a commercial meter — **it makes every power figure in this document conservative.**
- **ARITHMETIC: 1 W continuous = 8.766 kWh/yr = $2.19/yr in New Jersey.** Each 100 W of continuous draw costs **$218.56/yr**. This single constant decides most of this document.
- New Jersey sales tax **6.625 %**, collected by eBay as a registered marketplace facilitator — **PUBLISHED**, NJ Treasury https://www.nj.gov/treasury/taxation/remotesellersfaq.shtml and https://taxcloud.com/sales-tax/new-jersey (accessed 2026-09-16).

### Capacity table — ARITHMETIC

> **RECOMPUTED 2026-09-16.** `[corrected 2026-09-16: this table was `0.75 × RAM / 0.81`, which assumes a node starts at zero commit.]`
> Two changes, both measured on `ZABZ-YOGA` and both from `~/.dsh/metrics/harness-metrics.csv` (477 rows,
> 2026-09-16 12:56:55–17:47:41Z), not from the brief:
>
> 1. **A resident floor of 18 GB is subtracted first.** An idle machine running this harness already holds
>    17.0–18.4 GB of commit with 9–13 node processes resident. Memory a node has already spent is not
>    capacity it can offer. **Unit assumed: one "resident process" = one DSH node process** (the sampler's
>    `node` column) — **not** a generating turn, because the sampler never recorded a generating-turn count
>    (`sessions.agentLoopsRunning` exists in `/healthz` and is unused for this). The 18 GB floor is
>    therefore itself a **lower bound**; on a node with a smaller baseline the ceiling is higher.
> 2. **0.58 replaces 0.81 GB.** Least-squares slope of commit on node-process count, r = 0.937.
>
> Corrected form: `resident processes = floor((0.75 × RAM_GB − 18) / 0.58)`.

| Installed RAM | Usable (75 %) | Resident processes **(corrected)** | was |
|---|---|---|---|
| 8 GB | 6.0 GB | **0** — the floor exceeds the usable budget; this node cannot hold one extra process | 7 |
| 12 GB | 9.0 GB | **0** — same | 11 |
| 16 GB | 12.0 GB | **0** — same. `linux-pc-ts` has 11.4 GB and measures 10.3 GB available, which is a *transient* reading, not headroom above a floor | 14 |
| 24 GB | 18.0 GB | **0** — exactly the floor. `secratary` is in this row and its real ceiling is its **4 cores** | 22 |
| 31.6 GB | 23.7 GB | **9** (`(23.7−18)/0.58`), and measured behaviour says **≤13** held 19.1 GB while 15+ crossed physical memory | 29 |
| 32 GB | 24.0 GB | **10** | 29 |
| 40 GB | 30.0 GB | **20** | 37 |
| 64 GB | 48.0 GB | **51** | 59 |
| 128 GB | 96.0 GB | **134** | 118 |

> **Read the 8–24 GB rows as the finding, not as an artefact.** `[added 2026-09-16]` If ≈18 GB is already
> resident, then **a 16 GB node has no capacity for even one more heavy process, and a 24 GB node has one
> core's worth and no memory** — which is exactly why `secratary` (23.4 GB, 4 cores) is a control plane and
> not a worker, and why the mac mini (16 GB, swap 92 % used) cannot be one either. The 18 GB floor is
> measured on THIS laptop with the full harness loaded; a bare Linux node would have a lower floor, and that
> is the single measurement that would most change this table. **It has not been taken.** `60-verification.md`
> §6.3 records it as the highest-value open measurement.

> **Caveat, repeated at every ranking:** the resident-turn number is a **memory** limit. The CPU limit is **~one core per *generating* turn**. A node's useful capacity is `min(resident turns, cores that can generate)`. Most agent wall-clock is spent waiting on a model API rather than burning a core, so a node can **hold** far more turns than it can **saturate** at once. Both numbers appear for every candidate; neither alone is the answer. `[added 2026-09-16: this caveat was already correct and was, until now, not applied to the table directly above it or to the total at `:274`. The `min()` is the operating rule, not a footnote.]`

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
| **Dell OptiPlex 5090 Micro**, i5-10500T (**6C/12T**), 16 GB, 256 GB SSD `[F]` — https://www.ebay.com/itm/137735826695 | 3× the 9020's threads, native NVMe boot, **64 GB DIMM ceiling**, ~12 W idle | **$197.26** (MARKET $185.00, free delivery) | ~12 | 14 | **The best replacement for the 9020 found in this pass** — cheaper than the SFF options, quieter, and it doubles the RAM ceiling. Same part recommended as a mesh node in §4, so one purchase serves both purposes. |
| **Dell OptiPlex 7060 SFF**, i7-8700 (**6C/12T**), 16 GB, 256 GB NVMe, eBay Refurbished | 3× the 9020's threads, native NVMe boot, 4 UDIMM slots | **$379.68** (MARKET $356.37, https://www.ebay.com/itm/267490790433, accessed 2026-09-16). Also $169.95 for the **6 c / 6 t i5-8500** version + $55.57 ship (https://www.ebay.com/itm/327350158758) | ~20–25 W (community estimate — **no rigorous SFF measurement found**) | 14 | Superseded by the 5090 Micro above: same thread count, half the price, a quarter of the watts. |
| **HP EliteDesk 800 G4 SFF**, i7-8700 (6C/12T) | same class | **$138.61–$245.22** (MARKET, four listings at $129.99 / $175.00 / $189.99 / $229.97, https://www.ebay.com/shop/hp-elitedesk-800-g4-i7, accessed 2026-09-16) — cheapest 6C/12T SFF found | ~20–25 W (estimate) | 14 | Better value than the OptiPlex; take the $175 config with a drive. |
| **Stay and refresh the 9020** — +8 GB DDR3 ($41.57) + i7-4790 ($42.65) | 32 GB / 8 threads | **$84.22 total** | ~65 W (desktop class; **not measured**) | 29 | **Cheapest path by far.** Buys time; does not escape DDR3 or 2013 silicon. |

**Explicitly rejected: a used rack server.** Measured idle 125–252 W (item 5) = $273–551/yr forever, plus noise in a customer-facing office.

---

## 3. Cheap Linux nodes — what is actually available

All prices **MARKET**. `[F]` = the price was read on a page **fetched live on 2026-09-16**; `[S]` = a search-result snippet only, page not fetched. **This distinction matters and is the reason this table was rewritten once:** the first draft of this document carried a $120 turnkey 16 GB OptiPlex that turned out to be `[S]`-only. The **verified floor** for a bootable 16 GB node is **$150**, and the verified floor for any bootable node at all is **$130**.

### Candidate table — verified listings `[F]`

| Machine | Cores/threads | RAM | Storage | Price `[F]` | Idle W | Turns | RAM ceiling |
|---|---|---|---|---|---|---|---|
| **Dell OptiPlex 5090 Micro**, i5-10500T — https://www.ebay.com/itm/137735826695 | **6 c / 12 t** | **16 GB** | 256 GB SSD | **$185.00**, free delivery | ~12 | 14 | **64 GB** |
| **Dell OptiPlex 7070 Micro**, i5-9500T — https://www.ebay.com/itm/336795130291 | 6 c / 6 t | **16 GB** | 256 GB NVMe | **$150.00**, free delivery | ~13 | 14 | 32 GB |
| Dell OptiPlex 7070 Micro, i5-9500T — https://www.ebay.com/itm/800651936824 | 6 c / 6 t | 16 GB | 256 GB NVMe | $174.97, free delivery | ~13 | 14 | 32 GB |
| Dell OptiPlex 3070 Micro, i5-9500T — https://www.ebay.com/itm/407202058656 | 6 c / 6 t | 8 GB | 256 GB NVMe | $130.00 + $5.93 ship | ~10 | 7 | 32 GB |
| Dell OptiPlex 3070 Micro, i5-8500T — https://www.ebay.com/itm/188807871523 | 6 c / 6 t | 8 GB | none | $107.99, free delivery | ~10 | 7 | 32 GB |
| Dell OptiPlex 3070 Micro **lot of 2**, i5-9500T — https://www.ebay.com/itm/147500464130 | 6 c / 6 t | 8 GB ea | none | $199.99 (≈$107.50/unit) + $15 ship | ~10 | 7 ea | 32 GB |
| **HP EliteDesk 800 G6 Mini**, i5-10500T — https://www.ebay.com/itm/298680578058 | **6 c / 12 t** | 8 GB | 240 GB | $199.99, free delivery | 11–12 | 7 | **64 GB** |
| HP EliteDesk 800 G4 Mini, i5-8500T — https://www.ebay.com/itm/358395219402 | 6 c / 6 t | 8 GB | 256 GB | $180.00, free delivery | **11–12** | 7 | 32 GB |
| HP EliteDesk 800 G5 Mini, i5-9500T — https://www.ebay.com/itm/168372467225 | 6 c / 6 t | 8 GB | 256 GB NVMe | $269.99, free delivery | NOT FOUND | 7 | **64 GB** |
| Lenovo M920x Tiny, 8th gen — https://www.ebay.com/itm/287314080977 | 6 c / 6 t | **16 GB** | 256 GB NVMe | $249.99, free delivery | NOT FOUND | 14 | 32 GB (64 GB shown to work) |
| Lenovo M920q Tiny, i5-8500T — https://www.ebay.com/itm/178498867189 | 6 c / 6 t | 8 GB | none | $130.90, free delivery | 12–15 | 7 | 32 GB (64 GB shown to work) |
| Lenovo M720q Tiny, i5-8500T + PCIe riser — https://www.ebay.com/itm/820116197639 | 6 c / 6 t | — | — | $150.00 + $5.93 ship | 11–14 | — | 32 GB |
| Lenovo **M910q** Tiny, i5-7500T — https://www.ebay.com/itm/178498871974 | **4 c / 4 t** | 8 GB | none | $69.95, free delivery | NOT FOUND | 7 | 32 GB |
| Dell OptiPlex 7080 Micro — https://www.ebay.com/itm/198198969412 | 6 c / 6 t | **16 GB** | 128 GB | $309.95, free delivery | ~11 | 14 | **64 GB** |
| Dell OptiPlex **7060 SFF**, i5-8500 — https://www.ebay.com/itm/327350158758 | 6 c / 6 t | 16 GB | 256 GB NVMe | $169.95 + **$55.57** ship | NOT FOUND (SFF) | 14 | **64 GB, 4 UDIMM** |
| **GMKtec NucBox K8 Plus**, Ryzen 7 8845HS — https://www.gmktec.com/products/gmktec-nucbox-k8-plus-mini-pc-amd-ryzen%E2%84%A2-7-8845hs | **8 c / 16 t** | 32 GB DDR5 | 1 TB NVMe | **$399.99** | **8.5** wall-metered | 29 | **128 GB** |
| Minisforum MS-01, i9-13900H — https://store.minisforum.com/products/minisforum-ms-01-workstation | **14 c / 20 t** | barebone / 32 GB | 3 × M.2 | $679.00 / $1,183.00 | 25–29 | 29 @32 GB | 96 GB |
| FIREBAT AM02, **N100** — https://www.firebatpc.com/products/n100-intel-mini-pc-3-4ghz-am02-model | 4 c / 4 t | 16 GB LPDDR5 | 512 GB | $199.99, in stock | ~10 | 14 | 32 GB (1 slot) |
| GMKtec G3, **N100** — https://www.gmktec.com/products/nucbox-g3-most-cost-effective-mini-pc-with-intel-n100-processor | 4 c / 4 t | 16 GB | 512 GB | $169.99 — **SOLD OUT** | 10–11 (8.4 tuned) | 14 | 32 GB |
| Beelink Mini S12 Pro, **N100** — https://www.amazon.com/dp/B0DP2KFWW4 | 4 c / 4 t | 16 GB | 512 GB | $339.00 | **5.7** tuned | 14 | 32 GB (1 slot) |

**Snippet-only prices from the first draft, now demoted — do not rely on them:** a 16 GB OptiPlex 3070 Micro at "$120" and HP EliteDesk G5 units at "$79.00 / $97.99". These appeared only in eBay search snippets `[S]`; the same search pages also spawned a contradictory "$239.99 cheapest" claim elsewhere. **The verified numbers above supersede them.**

**Specification corrections found during verification:**
- **HP EliteDesk 800 G5 Mini supports 64 GB (2 × 32 GB) — not 32 GB.** The first draft said 32 GB; that was wrong.
- OptiPlex 3070 / 7070 / 7080 Micro: **2 SODIMM**, ceiling 32 GB (7070/3070) and **64 GB** (7080, 5090). OptiPlex 7060 **SFF**: **4 UDIMM, 64 GB**. Dell owner's manual: https://dl.dell.com/topicspdf/optiplex-3070-desktop_owners-manual5_en-us.pdf and https://dl.dell.com/topicspdf/optiplex-7060-desktop_specifications2_en-us.pdf (accessed 2026-09-16).
- **The killer number for the "buy 8 GB and upgrade later" plan:** a **32 GB (2 × 16 GB) DDR4-2666 SODIMM kit is $203.08** — https://www.newegg.com/a-tech-ddr4-laptop-memory-ram-32gb-ddr4-2666-cas-latency-cl19/p/0RM-0032-004K3 `[F]`, accessed 2026-09-16. **Pre-installed RAM is worth far more than the sticker gap between an 8 GB and a 16 GB node.**
- eBay **does** collect NJ sales tax as a marketplace facilitator, added at checkout; **6.625 % statewide with no local or county add-on**, and the Urban Enterprise Zone 3.3125 % rate does **not** apply to shipped orders — https://www.ebay.com/help/buying/paying-items/paying-taxes?id=4771 and https://www.nj.gov/treasury/taxation/salestax.shtml `[F]`, accessed 2026-09-16. Free shipping is common: eBay's free-shipping filter shows 956 of ~1,862 used "optiplex micro i5" listings. Where charged it is typically a flat ~$15 (USPS Ground Advantage, 3 lb Zone 4 = $13.70).

### Idle power — PUBLISHED, meter-measured

| Machine | Measured idle | Source |
|---|---|---|
| **HP EliteDesk 800 G4 Mini, 6-core** | **11–12 W** at 120 V | ServeTheHome, https://www.servethehome.com/hp-elitedesk-800-g4-mini-tinyminimicro-guide-review/3/ (accessed 2026-09-16) |
| **HP EliteDesk 800 G4 Desktop Mini** | **11.351 W**, "Normal Operation (Long idle)", 115 VAC — **HP's own ENERGY STAR-method declaration** | HP datasheet, https://h20195.www2.hp.com/v2/getpdf.aspx/c06040430.pdf (accessed 2026-09-16) |
| **Dell OptiPlex 3070 Micro** | **just over 10 W** at 120 V; STH assumes 9–12 W for this class | https://www.servethehome.com/project-tinyminimicro-dell-optiplex-3070-micro-review/2 (2020-07-31, accessed 2026-09-16) |
| Dell OptiPlex 7070 Micro, six-core | just over **13 W** | https://www.servethehome.com/dell-optiplex-7070-micro-project-tinyminimicro-guide-and-review/3 |
| Dell OptiPlex 7060 Micro, **65 W-TDP** CPU | just over **18 W** | https://www.servethehome.com/dell-optiplex-7060-micro-tinyminimicro-at-65w-tdp-cpu-overview/3 |
| **Lenovo ThinkCentre M720q Tiny** | **11–14 W** (STH unit was a dual-core G5400T); a separate STH page measured **27 W idle / 68 W load** on a different configuration; a repeatable community run reports **4–6 W** on an i5-8500T/32 GB in Proxmox. **Band: 11–27 W, unit-dependent.** | https://www.servethehome.com/lenovo-thinkcentre-m720q-tiny-tinyminimicro-feature/3/ and https://www.servethehome.com/lenovo-thinkcentre-m720q-tiny-compact-pc-review/4/ |
| **Beelink MINI S12 (N100)** | **8.2 W idle**, 22.5 W max | https://xdaforums.com/t/beelink-mini-s12-and-mini-s12-pro-review-budget-mini-pcs-that-checked-all-the-boxes.4562923 |
| **Beelink S12 Pro (N100)**, powersave-tuned | **5.7 W headless**, 10 W with 2 USB SSDs | https://windgate.net/beelink-s12-pro-intel-n100-powersave-optimization |
| Fanless N100/N200 appliance | **10.5–12 W** | https://www.servethehome.com/fanless-intel-n100-firewall-and-virtualization-appliance-review/4 |
| **Beelink SER7 (Ryzen 7 7840HS)** | **6–10 W idle**, 44–46 W sustained, 77–79 W peak | https://www.servethehome.com/beelink-ser7-review-a-smaller-and-cheaper-amd-ryzen-7-7840hs-mini-pc/4/ (2023-10-24) |
| **GMKtec K8 Plus (8845HS)** | **8.5 W wall-metered**; 90–95 W load (a separate report: 10–11 W idle) | https://liliputing.com/gmktec-nucbox-k8-review-amd-ryzen-7-8845hs-is-a-nuc-like-mini-pc and https://www.reddit.com/r/MiniPCs/comments/1in4nvs/ |
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

### Ranking — capacity per dollar, upfront (verified `[F]` prices only)

Price × 1.06625 for NJ tax; resident turns ÷ taxed price. **This table was rebuilt after verification.** The `[S]`-only prices in the first draft ($79–$120 for 16 GB nodes) are excluded — they could not be reproduced on a fetched page.

| Rank | Candidate `[F]` | Taxed price | Turns | **$/turn** | **$/thread** | Threads |
|---|---|---|---|---|---|---|
| 1 | **OptiPlex 7070 Micro, i5-9500T, 16 GB, 256 GB NVMe @ $150** | **$159.94** | 14 | **$11.42** | $26.66 | 6 |
| 2 | OptiPlex 7070 Micro, 16 GB @ $174.97 | $186.56 | 14 | $13.33 | $31.09 | 6 |
| 3 | **OptiPlex 5090 Micro, i5-10500T, 16 GB, 256 GB SSD @ $185** | **$197.26** | 14 | **$14.09** | **$16.44** | **12** |
| 4 | OptiPlex 7080 Micro, 16 GB @ $309.95 | $330.48 | 14 | $23.61 | $55.08 | 6 |
| 5 | Lenovo M920x, 16 GB, 256 GB NVMe @ $249.99 | $266.55 | 14 | $19.04 | $44.43 | 6 |
| 6 | FIREBAT AM02, N100, 16 GB LPDDR5, 512 GB @ $199.99 | $213.24 | 14 | $15.23 | $53.31 | 4 |
| 7 | GMKtec K8 Plus, 32 GB, 1 TB, new @ $399.99 | $426.49 | 29 | $14.71 | $26.66 | 16 |
| 8 | MS-01 barebone @ $679 (needs RAM to be useful) | $724.00 | 0 as shipped | — | — | 20 |
| 9 | **OptiPlex 3070 Micro, 8 GB, 256 GB NVMe @ $130 + $5.93 ship** | **$144.94** | **7** | **$20.71** | $24.16 | 6 |
| 10 | HP EliteDesk 800 G6 Mini, i5-10500T, **8 GB** @ $199.99 | $213.24 | 7 | $30.46 | $17.77 | **12** |
| 11 | HP EliteDesk 800 G5 Mini, **8 GB** @ $269.99 | $287.88 | 7 | $41.13 | $47.98 | 6 |
| 12 | OptiPlex 3070 Micro, 8 GB, **no disk** @ $107.99 | $115.14 | 7 | $16.45 | $19.19 | 6 |
| 13 | Lenovo M910q, i5-7500T **4 c / 4 t**, 8 GB, no disk @ $69.95 | $74.58 | 7 | $10.65 | $18.65 | 4 |

**Read this table two ways, because it contains a genuine tension:**

- **Cheapest per resident turn:** the M910q at $10.65, then the 7070 Micro at $11.42. But the M910q is a 4-core/4-thread 2017 CPU — it adds almost no generating capacity and sits at a 32 GB ceiling.
- **Cheapest per *thread*:** the **OptiPlex 5090 Micro at $16.44/thread** and the **EliteDesk 800 G6 Mini at $17.77/thread** — both **6 c / 12 t i5-10500T** machines. Every 8th/9th-gen 6 c / 6 t option costs **$19–48 per thread**.

**Since the binding constraint is cores (see §4), the right ranking is $/thread, and the 5090 Micro wins it.** It is also the only cheap verified node with a **64 GB ceiling**.

An 8 GB node is poor on both measures: $16.45 for 7 turns and **only 6 threads**, and fixing it means a **$203.08** 32 GB SODIMM kit — so the "cheap 8 GB box, upgrade later" plan costs more in total than buying 16 GB outright.

**On "no disk" units** (M910q $69.95, 3070 Micro $107.99, 3070 lot of 2): a boot disk must be added, and **SSD prices are elevated in the same 2026 shortage** — I obtained no firm citable SSD listing, so a disk is **NOT FOUND as a sourced figure**. Adding ~$35 to the $107.99 unit takes it to ~$152 taxed → ~$21.7/turn, i.e. **worse than the complete $130 8 GB unit and far worse than the $150 16 GB unit.** **Buy turnkey.**

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

### (a) 3–4 cheap used mini PCs — at VERIFIED prices

Two verified configurations, because the choice between them is the whole decision:

| | **3 × OptiPlex 5090 Micro** (i5-10500T, 6 c/**12 t**, 16 GB, 256 GB SSD) @ $185 | **3 × OptiPlex 7070 Micro** (i5-9500T, 6 c/6 t, 16 GB, 256 GB NVMe) @ $150 |
|---|---|---|
| Purchase `[F]` | 3 × $185 = $555 → **$591.64 taxed** | 3 × $150 = $450 → **$479.81 taxed** |
| Turns added | **+42** | +42 |
| **Physical cores added** | **+18** | +18 |
| **Threads added** | **+36** | +18 |
| RAM ceiling per node | **64 GB** | 32 GB |
| Idle power | 36 W → **$78.74/yr** | 39 W → $85.30/yr |
| 3-yr TCO | $591.64 + $236.21 = **$827.85** | $479.81 + $255.89 = **$735.70** |
| **$/turn upfront** | $14.09 | **$11.42** |
| **$/thread upfront** | **$16.44** | $26.66 |
| **3-yr $/turn** | $19.71 | **$17.52** |

**The 5090 costs $111.83 more and buys 18 extra threads and a doubling of the RAM ceiling.** Since §4's finding is that **cores, not RAM, bind**, that is the better purchase — and it is the only cheap verified node here whose 64 GB ceiling leaves room to grow when DDR prices recover. Take the 7070 only if cash is the hard constraint.

For reference, a 4-node variant of the 5090 (4 × $185 → $788.85 taxed) buys **+56 turns and +48 threads** at 48 W ($104.96/yr) — worth it only if measured demand exceeds ~70 turns, which it does not today.

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

**$/turn: $44 upfront plus electricity — roughly 2.4× the recommended package's $18.37 on 3-year TCO, and 3.3× its upfront $/turn, for a machine that provides only 24 physical cores against the 40–55 needed.**

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

### Electricity — PUBLISHED rate, ARITHMETIC totals

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

| Option | Upfront (taxed) | 3-yr electricity | Turns | **3-yr $/turn** | **Threads gained** |
|---|---|---|---|---|---|
| **3 × OptiPlex 7070 Micro (16 GB, 13 W) — budget route** | **$479.81** | $255.89 | 42 | **$17.52** | **18** |
| **RECOMMENDED: 3 × OptiPlex 5090 Micro + `secratary` refresh** | **$675.86** | $242.77 | 50 | **$18.37** | **40** |
| Used rack server, 128 GB @ $774.99 (125 W) | $826.33 | $820.14 | 118 | $13.95 | 16–28 |
| `secratary` refresh only: DDR3 + i7-4790 | $84.22 | ~$426 (65 W, est.) | 29 | $17.60 | 4 |
| **HP Z440, 32 GB @ $219.99 (105 W)** | **$234.56** | **$688.92** | 29 | **$31.84** | 8 |
| **One 128 GB DDR5 workstation, real listing @ $4,899.99 (~50 W)** | **$5,224.61** | $328 | 118 | **$47.06 — worst** | **28** |

**Two results fall out of this table, and they decide the recommendation:**

1. **Per-turn total cost of ownership is nearly flat across the cheap options** — $17.52 to $18.37 for the small-node routes, and $13.95 for a used rack server — because at 2026 prices RAM and cores dominate every route. **$/turn therefore does not discriminate.** The discriminators are upfront cash, **added threads**, watts, noise, resilience and maintenance.
2. **The flat $/turn hides a hard constraint: cores.** The measured demand is 40–55 concurrent turns and each generating turn costs ~1 core. The two big-machine options in this table hold 118 resident turns but provide only **24 and 16–28 cores**. The cheap-node route is the only one that scales cores linearly and in units the owner actually needs.

### Complexity — the cost with no invoice

**The update cadence is real and now sourced — PUBLISHED:** Canonical ships *"more than 3 [security] updates each day, and the most vital updates are prepared, tested and released within 24 hours"* (https://ubuntu.com/blog/securing-open-source-through-cve-prioritisation); Ubuntu by default installs security updates after 24 hours and normal updates after 7 days (https://documentation.ubuntu.com/security/security-updates, page dated 2026-07-03); a **kernel package update requires a reboot** to take effect, and with Livepatch a GA-kernel LTS needs upgrade+reboot **every 13 months** while an HWE kernel needs it at 13 months **then every 6 months**, plus *"unscheduled security maintenance windows may be required, to patch security vulnerabilities in glibc, libc, or CPU microcode"* (https://ubuntu.com/blog/how-often-do-you-apply-security-patches-on-linux). All accessed 2026-09-16.

**NO AUTHORITATIVE SOURCE EXISTS for a dollar figure on fleet maintenance burden; the following is engineering judgement, labelled as such.** Each node is a machine needing an OS install, a distro upgrade every 2 years (Ubuntu LTS), the patch cadence above, an unattended-upgrades policy, a reboot window, monitoring, a backup check, and physical space. That work is done by one seat (this one) with **no continuous memory**, so every node's state must be written down to survive. Patching, reboot windows and monitoring scale roughly linearly in N — and so does capacity, so overhead *per unit of capacity* is roughly flat. **The real N-penalty is the failure surface:** each node is an independent reboot and failure domain, and one reboot costs 1/N of fleet capacity if work is distributed, versus 100 % if everything sits on one box. Three nodes also mean three power bricks, three dust inlets, three network identities, and **three more chances for a node to be silently down while its capacity is still being counted**. One big machine is one thing to get right — a real advantage, and not large enough to beat (a) on dollars.

**What one big machine does not fix:** the owner's actual complaint is that *work lands on the Yoga*. Centralising on a single new box swaps one bottleneck for another with the same failure mode — everything queues in one place, and if that box is down, the whole mesh is down. Three cheap nodes are strictly more resilient. **That asymmetry, not $/turn, is the decisive argument for (a).**

### Recommendation

**Buy (a) plus the two cheap `secratary` top-ups from (c). Do not buy (b). Do not buy a workstation or a rack server.**

| # | Purchase | Detail | Cost taxed |
|---|---|---|---|
| 1 | **3 × Dell OptiPlex 5090 Micro** `[F]` — https://www.ebay.com/itm/137735826695 | **i5-10500T 6 c / 12 t, 16 GB, 256 GB SSD, 64 GB ceiling**, ~12 W idle, free delivery, $185 each | **$591.64** |
| 2 | **2 × 8 GB DDR3-1600** for `secratary` | Timetec 16 GB kit (2×8 GB), drop the 2 × 4 GB → 32 GB @ 1600 | **$41.57** |
| 3 | **Intel i7-4790** for `secratary` | LGA1150 drop-in, 4C/8T — doubles the tick loop's generating ceiling | **$42.65** |
| | **Total** | | **$675.86** |

**Budget variant, if cash is the constraint:** swap line 1 for **3 × OptiPlex 7070 Micro, i5-9500T, 16 GB, 256 GB NVMe at $150** `[F]` — https://www.ebay.com/itm/336795130291 — total **$564.03**, saving $111.83, and give up **18 threads** and half the RAM ceiling. Same 42 turns either way.

**Resulting mesh:** resident turns **74 → 124**; **threads 48 → 88** and **physical cores 36 → 54** (against a 40–55-turn demand, so the binding constraint is finally cleared with headroom); non-Yoga capacity **45 → 95 turns**, leaving the Yoga free to be the machine he works on. Added continuous draw ~37 W = **+$80.92/yr**. **3-year $/turn ≈ $18.37**; upfront $/turn **$13.52**.

**Why this package and not a bigger one:** it is the only route that adds **cores and turns together, in the ratio the demand actually needs**, at the lowest upfront cash, with the smallest electricity bill, silently, and with capacity purchasable one node at a time as need is measured. The workstation route spends **~8× more cash** and still delivers only **24 physical cores** against a 40–55 core requirement.

### Single best value for money

**One Dell OptiPlex 5090 Micro — i5-10500T (6 c / 12 t), 16 GB, 256 GB SSD, $185 free delivery — https://www.ebay.com/itm/137735826695** `[F]`, accessed 2026-09-16.

$197.26 taxed buys **14 resident turns AND 12 threads AND 16 GB already installed AND a 64 GB ceiling AND a complete bootable machine at ~12 W ($26.25/yr)**. At **$16.44 per thread** it is the cheapest verified way to buy the *scarce* resource — the next-best 6 c / 12 t option, the EliteDesk 800 G6 Mini, is $17.77/thread and comes with only 8 GB. Every 8th/9th-gen 6 c / 6 t alternative costs **$19–48 per thread**.

**Runner-up on pure $/turn:** the **OptiPlex 7070 Micro at $150** — $11.42/turn, the cheapest verified turn capacity available — but 6 c/6 t and a 32 GB ceiling, so it solves memory and not cores.

**Second tranche, only if the mesh is still tight:** a single 32 GB DDR4-3200 UDIMM into the HP Pavilion TP01-2xxx (`linux-pc-ts`) — **$237.77** for +27 turns on an existing 6C/12T box already running Ubuntu. Do this rather than a 4th node only if the goal is avoiding another machine to maintain; a 4th node costs less per turn, adds threads, and is the better raw buy.

**Do not buy a fourth node yet.** Add one only when measured resident turns in the non-Yoga mesh exceed ~90 — capacity that is not needed is electricity and maintenance paid for nothing.

---

## 5. What NOT to buy, and why

Each of these looks attractive and fails on a **measured** constraint.

**1. Any 8 GB machine.** The verified 8 GB turnkey node is the **OptiPlex 3070 Micro at $130 + $5.93 ship = $144.94 taxed** `[F]` — https://www.ebay.com/itm/407202058656 — which delivers **7 resident turns for $20.71/turn**, against the **OptiPlex 7070 Micro's 16 GB and 14 turns at $159.94 = $11.42/turn**. **Fifteen dollars more buys double the capacity.** Worse, "buy 8 GB now, upgrade later" is the single most expensive plan on the table: a **32 GB (2 × 16 GB) DDR4-2666 SODIMM kit is $203.08** today `[F]` — https://www.newegg.com/a-tech-ddr4-laptop-memory-ram-32gb-ddr4-2666-cas-latency-cl19/p/0RM-0032-004K3 — so an 8 GB node plus a 32 GB kit costs **$348** for 29 turns (**$12.00/turn**) and took two purchases instead of one, versus **$317.84** for two complete 16 GB 7070 Micros giving 28 turns and **12 threads instead of 6**. Also rejected: the earlier-seen 7-unit lot at $143/unit for 8 GB machines (https://www.ebay.com/itm/358793480712, $999.99, ended), whose headline price was *higher per unit* than a 16 GB machine bought singly. **8 GB is below the useful floor for a 40–55-turn demand.**

**2. A used workstation (HP Z440, Dell Precision T5820).** This is the most seductive trap in the whole document, because the upfront arithmetic looks like the best deal available: an HP Z440 with a **6-core/12-thread Xeon E5-1650 v3 and 32 GB DDR4** was listed at **$219.99** (MARKET, https://www.ebay.com/b/HP-Z440-Towers/179/bn_89095653) — and 32 GB of DDR4 *alone* costs $223–256 today, so the machine appears free. *(A subagent reported the same configuration at $112.05 from a browse band; I could not reproduce that figure and found $219.99 for the nearest comparable listing, so I use $219.99 and treat $112.05 as unverified.)* **It fails on measured idle power: the Z440 with this exact CPU draws about 100–110 W at idle** (PUBLISHED, above) = **$218–241/yr**, making its 3-year cost per turn **$31.84 — the second-worst option considered**, beaten only by a $4,899.99 DDR5 workstation, and *worse than a used rack server on total cost of ownership* because it holds only 29 turns against the rack server's 118. **Do not buy a used workstation for a mesh node. The DDR4 bundled inside it is not free; it is paid for monthly in electricity.**

**3. A used rack server (PowerEdge R730/R630, ProLiant DL360/DL380 Gen9).** Cheap to buy, rich in RAM. It fails on **measured idle power: 125–252 W realistically populated** (a tuned minimal 2 × E5-2650 v4 DL360 Gen9 measures 80 W over a 24 h run; a near-empty R730 measures 46.9 W on SPECpower — **do not budget either for a working node**), i.e. **$273–551/yr at idle**, before cooling — more than the purchase price of two complete used nodes, every year. It fails on **noise at load**: it is *not* much louder at idle (declared idle 23–28 dBA against a micro PC's declared 20 dB — both library-quiet), but loaded it reaches **39 dBA declared** on the DL360 Gen9 Performance profile, and Dell states any GPGPU configuration is *"about twice as loud"* as typical — a **+14 to +19 dB ≈ 25–80× sound power** gap. Sources: HPE https://support.hpe.com/hpesc/public/docDisplay?docId=c04442953, Dell https://i.dell.com/sites/csdocuments/Shared-Content_data-Sheets_Documents/en/Dell-13G-PowerEdge-Acoustical-Performance-and-Dependencies.pdf, HP micro-PC reference https://h20195.www2.hp.com/v2/getpdf.aspx/c06040430.pdf (all accessed 2026-09-16). Unsuitable for an office where customers walk in or a home office. And **0.94 turns/W against a micro PC's 1.40** — for 118 turns when he needs 40–55, so it also buys 2× the capacity required while providing only 16–28 cores.

**4. A disk upgrade for `secratary`.** The box is **already on a SATA SSD** (MEASURED: PNY 500 GB, `Rotation Rate: Solid State Device`, `ROTA=0`) with 185 GB free. It is **not** on spinning disk. The dominant failure signal is **8,290 `database is locked` events in 7 days** (MEASURED), a **SQLite concurrency** property, not sequential throughput. NVMe is also not cleanly available: no M.2 slot on this generation, and **Haswell 8-series chipsets have no firmware NVMe boot** (PUBLISHED), so an adapter card is a data disk at best behind a BIOS mod or a SATA bootloader. **Spend $0 here and fix the concurrency in software.**

**5. Any machine with soldered RAM, bought as an expandable node.** The measured lesson of this document: the two machines that *cannot* be expanded (the Yoga, 32 GB soldered LPDDR5x; the Mac mini M4, 16 GB soldered) are precisely the two that are now capacity dead ends — and the Yoga is the bottleneck that started this whole question. A 16 GB soldered box is **14 turns forever**. **Before buying any node, confirm it has two DIMM slots.** In this estate the expandable models are the HP Pavilion TP01-2xxx (2 slots, 64 GB max, MEASURED) and the OptiPlex 9020 SFF (4 slots, 32 GB max, MEASURED).

**6. ARM single-board computers (Raspberry Pi 5 16 GB, Orange Pi 5).** They look ideal — 16 GB for ~$120–160, a few watts — and the 0.81 GB/turn constant is architecture-independent so the capacity arithmetic appears to work. It fails on **workload compatibility**: this estate is x86 Linux with x86 `node_modules`, .NET and Windows-only tooling, and native Python wheels. An ARM node would need emulation, which consumes exactly the resource that is scarce (**CPU**). Its RAM is also **soldered**, so it repeats the Yoga's mistake in miniature. *Engineering judgement grounded in the estate's inventory; I did not benchmark an ARM node.*

> **If low power is the actual goal, buy x86 instead — an Intel N100 node.** Measured idle at the wall: **Beelink MINI S12 (N100) 8.2 W idle / 22.5 W max** (https://xdaforums.com/t/beelink-mini-s12-and-mini-s12-pro-review-budget-mini-pcs-that-checked-all-the-boxes.4562923) and **Beelink S12 Pro 5.7 W idle headless, 10 W with 2 USB SSDs after powersave tuning** (https://windgate.net/beelink-s12-pro-intel-n100-powersave-optimization) — all accessed 2026-09-16. That is **less than half a 6-core Tiny's 10–13 W**. Verified `[F]` prices: **be careful here** — the cheapest sticker, **GMKtec G3 (N100, 16 GB/512 GB) at $169.99, shows "Sold out"** (https://www.gmktec.com/products/nucbox-g3-most-cost-effective-mini-pc-with-intel-n100-processor), and Beelink S12 Pro is **$339.00** (https://www.amazon.com/dp/B0DP2KFWW4) while an N150 Beelink S13 is **$349.00** (https://www.newegg.com/p/1VK-01TK-001X6). **Exactly one N100 unit with 16 GB was verifiably in stock under $200 on 2026-09-16: the FIREBAT AM02 at $199.99** — https://www.firebatpc.com/products/n100-intel-mini-pc-3-4ghz-am02-model. At $213.24 taxed for 14 turns and **4 threads** it is **$53.31/thread** — versus $16.44/thread for the 6 c/12 t OptiPlex 5090 Micro. **N100 is the right answer on electricity and the wrong answer on cores and on $/thread.** A ≥$200 N100 node does not beat a $185 twelve-thread x86 node.

**7. Buying bare RAM as the primary strategy, at 2026 prices.** This is the trap the DRAM spike creates. **DDR4 rose more than 50 % in Q3 2026**, contract DRAM prices rose ~90–95 % QoQ in Q1 2026, and DDR3 rose with it (PUBLISHED, above). Verified `[F]`: a **32 GB DDR4-3200 UDIMM stick is $223–256**, a **32 GB (2 × 16 GB) DDR4-2666 SODIMM kit is $203.08**, and a **64 GB DDR4-3200 kit is $490–494**. Meanwhile a **complete 16 GB machine with 12 threads, a PSU, a chassis, a disk and a NIC is $185**. Per turn the bare stick is slightly cheaper ($7.5–8.8 against $14.09 for the 5090); per **thread** it adds **nothing at all**. **Buy whole used machines before buying RAM.** The only RAM purchases that clear the bar are the two small top-ups in the recommendation — and those clear it only because those machines already exist and their slots are already empty.

**8. Assuming the mesh's total RAM is the problem.** MEASURED: the four existing nodes already hold **74 resident turns** against a stated demand of 40–55. **Total memory is not the shortage.** The shortage is placement — the work lands on the one machine that cannot be upgraded — plus core count. Buying a huge single machine to add raw resident turns, when 74 already exist and are not being used, would be paying to solve a problem that is not the measured one.

**9. A modern high-core workstation with 64–128 GB DDR5.** Attractive because it is the "one machine to manage" answer and it has a real turns-per-watt advantage. It fails on **three measured constraints at once**: (i) **price** — a real current listing, i9-14900K with 128 GB DDR5 and 1 TB NVMe, is **$4,899.99** (https://www.newegg.com/p/3D5-002T-00S40, accessed 2026-09-16), which is **$44.28 per resident turn upfront** against **$13.52** for the recommended package — 3.3× worse, and worse than a used rack server on 3-year TCO; (ii) **cores** — its 24 physical cores cannot serve a 40–55-turn demand that spends ~1 core per generating turn, so the machine does **not** replace the mesh even after spending $5,000; (iii) **RAM is ~8× its 2025 price** and 128 GB of DDR5 alone is **$1,960–2,200** (2 × 64 GB kit at $979.99–1,099.99). It would be the right answer in a year when DDR5 is cheap again. **Do not buy it now.**

---

## NOT FOUND — stated gaps, not guesses

1. **A citable complete-build price for a 64 GB desktop** — a real 128 GB listing was found ($4,899.99) and a Dell Precision 3680 configuration exists (14th Gen Core, up to 24 cores/32 threads, 4 × DDR5 DIMM slots, 64 GB as 2 × 32 GB DDR5-4400, configurable to 128 GB — https://www.dell.com/en-us/shop/desktop-computers/precision-3680-tower-workstation/spd/precision-t3680-workstation, accessed 2026-09-16), but the US configurator is JS-rendered and carried no price. **The gap is immaterial: the constraint that rejects this route is cores, not price.**
2. **Meter-measured idle wattage for a 128 GB desktop workstation** — the 40–60 W figure is an **assumption**. Also **no rigorous measured idle exists for SFF-class** (as opposed to Micro) machines; the 20–25 W SFF figure is a community estimate. **No measured idle-wall-watts was found for an i5-8500T specifically** — the nearest are the 65 W-TDP 7060 Micro (18 W), the 6-core EliteDesk 800 G4 Mini (11–12 W) and the M720q (11–27 W).
3. **A firm citable SSD listing** to complete a "no disk" node (M910q $69.95, 3070 Micro $107.99). SSD prices are elevated in the same 2026 shortage and no price was verified, so no "no disk" node is costed as a finished node.
4. **Idle power or noise for a rack server in a realistically populated working configuration** — every vendor figure located is a minimal/entry config (SPECpower's near-empty R730 at 46.9 W, HPE's 70–80 W DL360 Gen9), and the populated community figures are snippet-only.
5. **A SK hynix primary datasheet for `H58G66BK7BX067`** — only distributor pages and third-party benchmark databases surfaced. Its identity as 32 Gb LPDDR5 rests on a distributor listing.
6. **Prices that were looked for and not found at all** — OptiPlex **5070 Micro** (no listing, no idle measurement), OptiPlex **7070 SFF**, **7080 SFF**, any **7090** listing, **HP ProDesk 600 G6 Mini**, **HP EliteDesk 800 G5 Mini** measured idle watts (anecdotes only), **ThinkCentre M910q** and **M920x** measured idle watts, **Samsung `M378B1G73`** 8 GB DDR3-1600, **Intel Xeon E3-1270 v3**, and live new prices for **Beelink SER5 (5560U)**, **Beelink SER7 (7840HS)**, **Minisforum UM480XT** and **Minisforum UM690** — every SKU of those was out of stock, so **no price was invented.** Also **no page-verified second-retailer DDR4 price** (B&H returned 403, Best Buy 422/403 to direct fetch; the Amazon $490.00 DDR4 figure **is** page-verified).
7. **Any published ops-hours comparison of N small Linux nodes versus 1 big one**, and **any small-business per-node cost of downtime** (the only figure found, ITIC 2024, is enterprise-scale: >90 % of mid-size and large enterprises put one hour of downtime above $300,000 — https://itic-corp.com/itic-2024-hourly-cost-of-downtime-report, cited only to show the number exists and **not transferable** to a two-person shop). Item 4's complexity analysis is therefore **engineering judgement**, labelled as such.

## Provenance of the measurements

All MEASURED values were taken in this session on 2026-09-16 (server measurements at 20:09 EDT) by the author, using `Get-CimInstance Win32_ComputerSystem/Win32_BIOS/Win32_PhysicalMemory/Win32_PhysicalMemoryArray/Win32_Processor` on the Yoga; and over `ssh secratary-ts` / `ssh mac-mini-ts` / `ssh linux-pc-ts`: `lscpu`, `dmidecode -t 1,2,3,4,9,16,17`, `free -m`, `swapon --show`, `lsblk`, `df -h`, `uptime`, `vmstat 1 3`, `smartctl -i`, `journalctl`, `sysctl hw.memsize`.

No machine was modified. No software was installed. Nothing was purchased. **This document is the only file written.**
