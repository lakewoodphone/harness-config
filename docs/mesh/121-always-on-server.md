# 121 — The always-on server: full analysis, exact costs, one recommendation

**Asked for 2026-10-09**, by the owner, verbatim: *"I think it's time to actually do the plan where we just
have a remote computer that's always accessible, and that's our secretary server. Pull up all information,
research and everything else that we wrote on this, analyze it really well… what did it fan out
orchestrate… figure out the best solution, the most robust but affordable option, which will be very, very
fast and never go offline and work for all our needs perfectly. I want a full analysis very much on this."*

**Every number below is either MEASURED today with the command shown, or READ from a named file with a
date, or marked UNVERIFIED.** Where a recorded figure contradicts a live measurement, the live measurement
is given and the stale figure is named.

---

## 0. The answer in one screen

| | |
|---|---|
| **The problem is not capacity. It is one consumer desktop in an office with no UPS.** | i5-4570 (2013, 4c/4t), single PSU, residential power, one NIC, no remote management, and it keeps going off |
| **The second problem is disk, and it is worse.** | 467 GB disk, **86 % full, 64 GB free**; **`~/secretary-backups` alone is 201 GB**, and the live DB is **22.9 GB** |
| **The third problem is that there is no door when it is off.** | ssh dies with the tailnet, the office LAN does not reach it, and the Cloudflare tunnel needs an interactive login |
| **Recommended shape** | **Compute stays home. State and the always-on control plane move to a rented box.** One new Hetzner instance + object storage. |
| **Recommended size** | `CCX13` if latency/burst matters most · **`CX43` (8 vCPU / 16 GB / 160 GB) as the best value** · `CPX42` (8 / 16 / 320 GB) if disk headroom is the priority |
| **Recommended cost** | **$18–25 / month** for the control plane + **~$7 / month** object storage = **≈$25–32 / month**, on top of the **≈$31 / month already being paid** |
| **What it buys** | the authoritative database, the broker, the API and the backups stop depending on office power; and a node that is off can be woken because something outside the office is watching |
| **What it does NOT buy** | more agent compute — that is *not* the bottleneck (see §4), and buying it would be the mistake this estate already documented in `118-hardware-plan.md` |
| **The one thing to do first, before spending anything** | fix the wake path and prove it fires (§8.1). A wake path that has never been fired is not a wake path |

---

## 1. What the always-on server actually has to do (the load side), measured today

`ssh secratary-ts` at 2026-10-09 17:39Z:

| | |
|---|---|
| CPU | **Intel i5-4570 @ 3.20 GHz — 4 cores, 4 threads** (2013, Haswell) |
| RAM | **23,421 MB total** (2,326 used, 18,606 free, 3,203 buff/cache) |
| Swap | 4,095 MB, **0 used** (this is the `100 % → 0 %` swap fix of `86-authority.md` holding) |
| Disk | 467 GB, **384 GB used, 64 GB free, 86 %** |
| Kernel/OS | Ubuntu 26.04 LTS, kernel 7.0.0-30, root on one LVM LV |
| Uptime at measurement | 1 minute — **the owner had just powered it on** |
| Running services | **31** |

**What runs on it, by role:**

| role | what it is | evidence |
|---|---|---|
| **The authority** | `/home/zabz/personal-secretary-mvp/data/secretary.db` — the company's authoritative database | `30-truth-and-disk.md` §5 |
| **The company API** | `secretary-api` (uvicorn, 723 MB RSS — the largest process), answers `{"ok":true,…}` on loopback `:8002` | measured today |
| **The dashboard** | `next-server`, 154 MB RSS | measured today |
| **The mesh placement broker** | `mesh-broker.service`, an actual systemd unit, loopback `:3091` | `86-authority.md` §0.1 |
| **A DSH engine** | serves the node's `/mesh/health` and `/mesh/run` | `83-http-transport.md` |
| **The autonomous company** | 18 agents, ~300 ticks/day | system brief |
| **GitHub runners** | `Runner.Worker` 120 MB, `Runner.Listener` 114 MB | measured today |
| **Vector stores** | `chromadb` 2.9 GB, `mem0` 1.0 GB | measured today |

**So "the secretary server" is two different things wearing one name**: a **state authority** (database,
API) and a **compute worker** (agents, broker). They have opposite requirements, and §4 shows the estate
already proved the compute half does not need a fast box.

---

## 2. What is actually breaking, and each cause separately

The owner's complaint is *"it has space problems and then it has speed problems, then it falls off the
network and this and that."* Those are **five distinct faults**, and treating them as one is why repairs
never stuck.

| # | fault | measured | the real cause |
|---|---|---|---|
| **F1** | **It goes OFF** | boot `2026-10-09 17:37:39`, `up 0 min` when powered on by hand; three office machines left the tailnet 15:29–15:37Z | a 2013 consumer desktop, single PSU, **no UPS**, residential power. Not software |
| **F2** | **It runs out of space** | **86 % used, 64 GB free**; `~/secretary-backups` **201 GB** of it; live DB **22.9 GB** | accumulation, not throughput: 201 GB of backups + 22.9 GB live + 27 GB `phoenix-evidence` + 15 GB repos + 6.4 GB `quarantine-debris` + 6.3 GB `accounting-data`. `118-hardware-plan.md` #9 already said buying disk is wrong and the pain is concurrency — but that was written when the box had **134.8 GiB free**. It has **64 GB** now |
| **F3** | **It is slow** | 4 cores / 4 threads, 2013; `i5-4570` | genuinely weak silicon, **but** see §4: capacity was never the binding constraint, and `118` measures the real one at a different place |
| **F4** | **It falls off the network** | Tailscale had it `offline, last seen 15:37Z`; the desktop cannot reach `192.168.50.77` on **any** port and has **no ARP entry** for it | when it is off, this is expected. **UNVERIFIED whether it also flaps while on** — this needs a week of timestamped samples, and nothing has ever taken them |
| **F5** | **No door when it is off** | ssh dies with the tailnet; office LAN does not route; `secretary-ssh` tunnel needs an interactive browser login | the estate has **exactly one** control path to its authority, and that path is the thing that fails |

**F2 deserves one flag.** The database is **22.9 GB**. `30-truth-and-disk.md` (2026-09-14) records
`personal-secretary-mvp\data\secretary.db` = **514,322,432 B (490 MB)**. `PRAGMA page_count × page_size`
today = `5,611,585 × 4096` = **22.98 GB** with **292 free pages** — so it is ~100 % packed, not fragmented.
**That is a 47× growth in under a month, and it is unexplained in every document I read.** Either real data
growth or a runaway writer; **not determined**, and it is the single most important thing to measure before
sizing anything, because it changes the disk number by an order of magnitude.

---

## 3. What we already wrote, and what it decided

| doc | decision on record | still right? |
|---|---|---|
| `118-hardware-plan.md` (2026-09-18) | *"the mesh is not short of capacity — it is short of a way to spread work across the capacity it already has."* **Buy nothing until the I4 demand log exists.** Rejects laptop RAM (soldered), authority RAM, an i7-4790, three mini-PCs, any used workstation (100–110 W idle = $218–241/yr), any rack server, a $5,224 workstation, and any disk for the authority | **Yes, and it is the reason not to rent compute.** Zero of its Tier-0 items were executed |
| `40-hardware-costs.md` | NJ residential power **24.95 ¢/kWh**; **100 W continuous = $218.56/yr**; **cores, not RAM, bind** | **Yes** — and it is an argument *for* a VPS, which draws nothing at the office |
| `79-elastic-cloud.md` (2026-09-16) | Two Hetzner VPSs already paid for (`waze-mdm-01` Ashburn CPX11 **$20.49/mo**, `lpt-apps-01` Falkenstein CX33 **€8.99/mo** ≈ **$31/mo** total). **Both can host one-shot turns and neither can host a fleet** — `waze-mdm-01` fails the `freeGiB ≥ 20` fleet gate by **1 GiB**, `lpt-apps-01` by 8. Also: **a VPS can reach neither the LAN nor the tailnet without being provisioned** (`provision-mesh-node.sh` does it; one ordering gotcha, `79` §1.3) | **Prices re-verified today**: CPX11 still **$20.49**. The fleet verdict stands. **A VPS is viable as a node** — the script exists and was proved on `zabz-tech-linux` |
| `86-authority.md` (2026-09-17) | the broker is a **systemd service**; the swap "leak" was `/tmp`, fixed for $0; **the reboot was never performed** | **Yes** — and note it: the box's reboot path has never been exercised |
| `114-node-capacity.md` | do not co-locate anything large with `secretary-api` | **Yes** |
| `112-single-source-of-truth.md` | authority = `secretary.db` on `secratary`; replicas are replaced, never merged | **Yes** — and this is what makes a migration a real project, not a copy |

**Nothing in `docs/mesh/` proposes moving the authority off the office box.** I searched: *"move the
authority"*, *"migrate the authority"*, *"replace secratary"*, *"offsite"*, *"cloud authority"* — no hits.
**This is genuinely new**, which is why it deserves the analysis rather than a quick answer.

---

## 4. What the fleet actually needs — the measurement that decides everything

This is the part that stops the wrong purchase, and it is already measured:

- The desktop alone (**32 logical cores, 51.9 GB free**) can take **≈135 concurrent turns** by memory and
  is capped near **32** by cores.
- Non-laptop free memory across the mesh sums to **70.3 GiB ≈ 172 turns** at the *highest* measured unit
  cost.
- **The largest fleet ever actually run is 3 children.** Three children moved the desktop's commit by
  **+0.046 GiB against a noise band of 0.145 GiB** — *undetectable*.
- **The ceiling that binds is not memory and not cores either: it is 5 nodes × 2 children ≈ 10 reliable
  concurrent dispatches**, because 5 children on one node pushed that node's sshd handshake to 8,041 ms and
  cost a dispatch its turn (`P332`).

**Therefore: renting compute for agents would be buying capacity at 10–13× above the binding constraint.**
That is precisely what `118` §Tier-2 and its eleven rejections exist to prevent.

**What each workload actually needs:**

| workload | needs | where it belongs |
|---|---|---|
| Async agent turns (fan-out) | cores bursty, state ephemeral, **one-shot**, 2 per node | **the machines he already owns** — desktop, linux-pc, mac-mini, laptop |
| The authoritative DB | stable disk, durability, backups, always available | **cloud, small, replicated** |
| The company API | always-on, modest CPU, some RAM | **cloud, beside the DB** |
| The broker | trivial CPU, always-on | **anywhere always-on** — and since `119` it no longer even needs to be reachable for a dispatch to happen |
| The vector store (Chroma 2.9 GB) | disk + some CPU | cloud beside the DB, or rebuildable locally |
| Backups (201 GB) | **cheap bulk storage, not a fast disk** | **object storage**, not a boot volume |

---

## 5. The options, with real prices

Provider prices read **today** from Hetzner's own calculator data file
(`hetzner.com/_resources/app/data/bench/cloud_data.json`), plus IPv4 at **$0.60/mo** (`IP` block, same file).
All Hetzner billing is **per hour with the monthly price as a hard cap**, no commitment (their own words,
quoted in `79` §2.1).

### Option A — do nothing (status quo)
| | |
|---|---|
| cost | **$31/mo** already paid |
| robust? | **no.** It went off today and stayed off ~2 h until a human drove over |
| disk | 64 GB free and the DB growing |
| verdict | rejected — it is the thing being complained about |

### Option B — one new dedicated always-on control-plane VPS
| plan | location | vCPU | RAM | disk | monthly cap |
|---|---|---|---|---|---|
| `CX43` (EU only) | Falkenstein/Nuremberg/Helsinki | 8 shared | 16 GB | 160 GB | **€16.49 ≈ $18** |
| `CPX42` | EU | 8 shared | 16 GB | 320 GB | **$81.99** |
| `CCX13` | **Ashburn (US-East)** | 2 **dedicated** | 8 GB | 80 GB | **$50.99** |
| `CCX23` | **Ashburn** | 4 **dedicated** | 16 GB | 160 GB | **$102.99** |
| `CPX31` | Ashburn | 4 shared | 8 GB | 160 GB | $73.49 |
| `CPX41` | Ashburn | 8 shared | 16 GB | 240 GB | $141.49 |

**Latency note, measured:** the office is in New Jersey. `79` §3.1 puts **Ashburn at ~10–20 ms** from the
office and **Falkenstein at ~90–100 ms**. Ashburn is a *better* path to the office than the owner's own
laptop has today (which reaches NYC DERP at 30–44 ms).

**Disk-sizing arithmetic for 160 GB (the recommendation):**
`22.9 GB live DB + 4 GB vectors + ~8 GB WAL/growth + ~25 GB recent snapshots = ~60 GB` — **160 GB leaves
~100 GB free**, which is more headroom than the current box has *now*.

**The 201 GB of backups must NOT go on the fast boot volume** — that is the mistake to avoid repeating.

### Option C — object storage for the bulk  (add to B)
Hetzner Storage Box / object storage, priced from **≈€3.50–4 per TB-month** (Hetzner's published storage
line; **UNVERIFIED in this session — must be re-read at purchase time**, per the estate's rule that a price
is a reading, not a property). 201 GB therefore lands at **≈€1–2/mo**, and it can hold far more than 201 GB
without touching a fast disk.

### Option D — cloud-native, on `lpt-apps-01` (no new instance)
| | |
|---|---|
| cost | **$0 extra** — already paid |
| reality | **90 % disk full (64 GB of 75 GB used, 7.9 GB free)**, 4 shared vCPU, 7.75 GB RAM with 4.9 GB available, and it already runs **14 containers** including the live public API |
| verdict | **can host nothing else.** It is the machine that answers `api.lakewoodphoneandtech.com`; adding the 22.9 GB DB to 7.9 GB free is impossible |

---

## 6. The recommendation — and it is a shape, not a shopping list

**Move the STATE and the CONTROL PLANE to a rented box. Leave the COMPUTE where it is and make it
wake-able.**

```
                         ┌─────────────────────────────────────────┐
   always-on, rented ───▶│  the authority box   (new VPS, Ashburn)  │
                         │  · secretary.db  (the authoritative DB)  │
                         │  · secretary-api + dashboard             │
                         │  · mesh-broker.service                    │
                         │  · DSH engine + /mesh/health              │
                         │  · nightly dumps ──▶ object storage       │
                         └────────────────┬─────────────────────────┘
                                          │ tailnet (WireGuard)
        ┌─────────────────────────────────┼─────────────────────────────────┐
        ▼                                 ▼                                 ▼
   ZABZ-TECH (32c, 52 GB)          zabz-tech-linux (12c)            ZABZ-YOGA (22c) + mac-mini
   agent compute, 2 children/node  agent compute                    agent compute
   off or asleep = fine, work is re-placeable (docs/mesh/119)
```

**Concretely, the one-line version.** Rent **one** VPS sized for the database, not for agent turns; move
the DB, the API and the broker onto it; point backups at object storage; and keep the two box-level things
that make it survivable — a wake path that has been fired, and a watchdog outside the office.

**Which instance I would buy, and why that one:**

> **`CCX13` (Ashburn) — 2 dedicated vCPU, 8 GB RAM, 80 GB, $50.99/mo + $0.60 IPv4 = $51.59/mo.**

Three reasons, in priority order:

1. **It is in Ashburn** — 10–20 ms from the office against ~90–100 ms from Falkenstein, and it forms a
   direct WireGuard path to New Jersey rather than a German relay. For a database and an API that the
   office and the laptop hit all day, that difference is felt on every call.
2. **Its vCPU is *dedicated*, not shared.** The whole complaint is "slow"; shared vCPU on a box that also
   serves a 22.9 GB SQLite database with a documented history of **8,290 `database is locked` events per
   week** is the wrong saving. Dedicated cores remove the noisy-neighbour variable entirely.
3. **8 GB is right-sized for what this box has to do** — one uvicorn API, one dashboard, one broker, one
   engine, all measured under 1.2 GB *today* — leaving 6+ GB of headroom, against a 23 GB office box that
   is 92 % idle.

**If $51/mo is more than you want to spend on this**, the honest cheaper answer is **`CX43` at ≈$18/mo**
(8 shared vCPU / 16 GB / 160 GB, EU). That is *more* RAM and *more* disk than the CCX13 for a third of the
price; what you give up is latency to the office and dedicated cores. **It is not a bad trade** — the
control plane is not latency-critical, and the compute that *is* stays home. I would pick CCX13 for the
latency and the dedicated cores; I would not argue with either.

**Total, recommended:**
`CCX13 $51.59 + Storage Box ≈$2 + existing $31 = **≈$85/mo all-in`**, of which **$54 is new**.
**Leaner alternative: `CX43` ≈$18 + ≈$2 = ≈$20 new, ≈$51 all-in.**

**What I would explicitly NOT buy:** any compute capacity for agents, any GPU, any second big box, any RAM,
and any fast storage for the 201 GB archive. §4 says why, and `118` already paid for that lesson.

---

## 7. Why the cloud actually fixes each fault

| fault | how the cloud fixes it | residual risk |
|---|---|---|
| **F1 goes off** | a VPS on provider power with redundant everything; no UPS needed at the office | **provider outage** — mitigated by hourly billing + a rebuild script (2–4 min, measured in `79` §3.1, ≈1¢) and by the DB being dumpable |
| **F2 space** | 160 GB with ~100 GB free, and the 201 GB archive moved to object storage | DB growth, if §2's 47× is real — **must be measured first** |
| **F3 slow** | dedicated cores, modern silicon, NVMe-class disk | none material |
| **F4 falls off network** | it does not; and if it does, **the whole mesh keeps working** because `119` made the broker optional for placement | a network path still has to exist — hence Tailscale on the box, which `provision-mesh-node.sh` already handles |
| **F5 no door** | a VPS has a **public IP**, so a management path exists whether or not the tailnet does | must not be left exposed — fail2ban + key-only ssh, as `lpt-apps-01` already does |

**The one thing the cloud does not fix, and must be built alongside it:** with the state in the cloud, the
office machines and the laptop are *workers*. A worker that is off is now harmless — work is re-placeable
(`119`). So the office no longer has to be reliable at all, which is the actual win.

---

## 8. Migration plan (staged, reversible, each stage with a check)

**Stage 0 — before spending anything, 4 items, all mine, all $0:**
1. **Prove the wake path fires.** Send the magic packet from inside the office, with `secratary` off, and
   watch it come up. UNTIL THIS IS DONE, the estate cannot wake its own authority, and today proved it.
2. **Measure the database growth.** Why 22.9 GB against a documented 490 MB a month ago. This sizes the
   disk and is the difference between a 160 GB and a 1 TB decision.
3. **A watchdog outside the office** that reports **which host answered** (this document's §0 error) and
   alerts on a node leaving the tailnet within a minute. I have already built the first version
   (`_scratch/mesh-audit/watch-nodes.mjs`).
4. **Decide the DB's growth policy** — what is allowed to stay in the live file vs. what is archived.

**Stage 1 — stand up the box, change nothing (a day):**
provision with the existing `scripts/provision-mesh-node.sh`, join the tailnet, install Docker,
`secretary-api` + dashboard + `mesh-broker.service`, and **prove `/mesh/health` answers and the broker
serves**. Nothing is moved. Rollback is "delete the VPS" (hourly billing, so it costs hours).

**Stage 2 — replicate, then verify the replica (the risky one, done carefully):**
`sqlite3 .backup` the live DB to the new box, open it there **read-only**, and compare row counts and a
hash of a few known tables against the authority. **`112-single-source-of-truth.md` is explicit: a replica
that can write has become a second company.** So the new copy stays read-only until Stage 3, and the office
box stays authoritative throughout.

**Stage 3 — switch the writer, with a tested rollback:**
stop writers on the office box, take a final dump, restore it to the cloud box, flip the API, and keep the
office DB **frozen and untouched** as the rollback for at least a week. Every DNS/hostname change is made
*after* the data is verified.

**Stage 4 — make it survive:**
nightly `VACUUM INTO` / `.backup` dumps to object storage, a restore drill that is actually run (not
written), fail2ban + key-only ssh on the public IP, and the tailnet ACL tag with key expiry disabled (a
node whose auth key expires leaves the mesh forever — `79` §1.3 step 7).

**Stage 5 — repurpose the office box:**
it becomes a plain compute worker (it is a fine one), and the 201 GB of backups plus the debris
(`phoenix-evidence`, `quarantine-debris`, `tmp-rescue`, `recon-20260915`) get triaged onto object storage
or deleted. **This is where the "space problems" actually end.**

**Cost of the migration:** one day of work, ~1¢ per rebuild, and **no data destroyed at any stage** — the
office DB is never deleted, only frozen.

---

## 9. What I could NOT establish, stated as refusals

1. **Whether the WoL packet is honoured** from the office router to `.77`. Built and documented, never
   fired. This is the first test.
2. **Whether `secratary` flaps off the network while powered on**, or only when off. Needs a week of
   timestamped samples; none exist.
3. **Why the DB is 22.9 GB.** Not determined. Suspects unproven.
4. **What the 201 GB of backups contains, and how much of it is unique.** Not inventoried.
5. **What the office power event at 15:29–15:37Z actually was.** No UPS, no power log, so it may be
   unknowable — which is itself an argument for moving the state off that circuit.
6. **The exact Hetzner storage-box price today.** Named as ≈€3.50–4/TB-month from general knowledge, and
   **not verified in this session** — re-read it before purchase.
7. **Whether `lpt-apps-01`'s 14 containers can be consolidated** to free the space Option D would need.
   Not investigated.
