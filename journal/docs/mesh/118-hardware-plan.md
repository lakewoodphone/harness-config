# 118 — Costed hardware plan

> **Condensed by the orchestrator from workstream HW's full report** (run 2026-09-18). The full text, with
> the complete source table and every URL, is in that run's output. Nothing here adds a number the run did
> not produce; nothing here drops a decision or a rejection.

**The one sentence the whole plan turns on:** *the mesh is not short of capacity — it is short of a way to
spread work across the capacity it already has.* The plan follows from that, not from a shopping list.

## The arithmetic that says capacity is not the problem

- The desktop's own free memory alone buys **134.7 concurrent turns** (38.8 GiB ÷ 295 MiB/turn) and its 32
  logical processors cap it at about 32 *generating* turns.
- Every non-laptop node's free memory summed: 38.8 + 14.6 + 10.3 + 6.6 = **70.3 GiB** — **172.2 turns** at
  the *highest* unit cost measured anywhere (the laptop's 418 MiB), or **244.0** at the desktop's own.
- The largest fleet anyone has actually run on this mesh is **3 children**, and three children on the
  desktop moved commit by **+0.046 GiB** against a measured noise band of **0.145 GiB** — i.e. **32 % of
  the noise, undetectable**. They are 2.23 % of that node's free memory and 3.75 % of the mesh's 80
  generating threads.
- **The ceiling that actually binds is not memory.** Five children on one node pushed its sshd handshake to
  **8,041 ms** and cost a dispatch its turn (`P332`). Five nodes × 2 children = **~10 reliable concurrent
  children** against a memory ceiling of **134.7 on one node**. **That ratio, 10 vs 134.7, is the
  bottleneck** — plus a broker that concentrates children on the biggest node, because that is what its
  ranking is for.

## Tier 0 — $0, and worth more than every purchase below

| # | intervention | what it improves |
|---|---|---|
| **I1** | **Cap children per node at 2 in the broker, and spread fan-out deliberately** | the only *measured* capacity loss. 5 children → 8,041 ms handshake and a **20 % dispatch loss**. Raising the timeout to 25 s treats the symptom; nothing caps K and nothing has measured the handshake curve between 2 and 5. Moves reliable fan-out from `1 node × 3` to `5 nodes × 2 = 10` **for nothing** |
| **I2** | **Fix the `secretary-api` runaway on the authority** | 31 OOM kills in two days (8 on 09-15, 23 on 09-16) against a drop-in capping it at 5/8 GB, and **8,290 `database is locked` events in 7 days = 2.07 % of all log lines**. Software, not silicon |
| **I3** | **Swap on the authority** *(done 2026-09-18 by pruning `/tmp`, not by adding a file — swap went 0 free → 3.15 GB free with no service touched)* | `SwapFree` was **0.017 % free**; it is now 75 % free. The one child measured there drew **zero swap**, so swap is what a *runaway* consumes, not what an agent does |
| **I4** | **Instrument demand**: sample `sessions.agentLoopsRunning` at 1 Hz for a week, p50/p95/max | **the number every purchase must be sized against, and it has never been taken.** The last plan sized $675.86 of hardware against a demand figure recorded as *"asserted, never measured"* |
| **I5** | **Reclaim disk on `zabz-tech-linux`** | 20.9 GiB free, **95.2 % used** — the one thing that removes that node from a fan-out. Needs the occupancy breakdown first; do not buy a disk before it exists |
| **I6** | **Verify placement from the transport host, not the child's token** | the integrity of the only placement proof the mesh has (now implemented as the placement-nonce patch) |
| **I7** | **Correct two stale numbers the plan would otherwise inherit** | the "DERP-only" laptop path was **refuted the same day** (`direct 172.59.215.73:58707`, `pong in 38ms`), and the desktop's `185.5 GiB` disk figure measured **160.30 GiB** — a 25.2 GiB, 13.6 % gap on the same day |

## Tier 1 — the owner's laptop's RAM: **$0, because it does not exist**

**Rejected, impossible, not merely expensive.** Lenovo PSREF for machine type 83AC (the measured Yoga 9
2-in-1 14IMH9): *"Memory soldered to systemboard, no slots"*, *"Max Memory: 32GB soldered, not upgradable"*.
Kingston: **0 slots**. Independent measurement: `Win32_PhysicalMemoryArray.MaxCapacityEx = 32 GB` = exactly
what is installed — **zero headroom even if a slot existed**.

And the measurements do not justify it even hypothetically: three children cost **+1.081 GiB** against
**13.7 GiB free** — 7.9 %, leaving 12.6 GiB untouched. Its binding quantity is *"the owner is sitting at
it"*, and **no purchase removes that**.

## Tier 2 — the first thing that could be worth money, and it is gated

**One `Dell OptiPlex 5090 Micro`, i5-10500T (6c/12t), 16 GB, 256 GB SSD — $197.26 taxed** ($185.00 × NJ
6.625 %), listing read 2026-09-16, **not re-verified on 2026-09-18** (both re-fetch attempts failed: one
403, one 404-and-sold). Cheapest verified $/thread at **$16.44**.

**The gate: buy this only if the I4 demand log shows sustained concurrent generating turns above 32** —
the desktop's logical-processor count, the first ceiling that binds. Until then the desktop offers 32
threads at **$0 marginal**.

## What NOT to buy, and why the numbers say no

1. **Laptop RAM** — soldered, no slots, max = installed. **Unavailable at any price.**
2. **RAM for the authority** (16 GB DDR3 kit, $41.57) — a child there costs **181 MiB, 1.2 % of free RAM,
   drawing zero swap**. RAM is not what binds; **swap was**, and it is now fixed in software for $0.
3. **An i7-4790 for the authority** ($42.65) — the box measures **95–96 % CPU idle** and one child left
   both services `active` in 44/44 loaded samples. Doubling threads on an idle node improves nothing measured.
4. **Three used mini-PCs ($591.77)** — `$591.77 ÷ 36 threads = $16.44/thread` to raise a ceiling
   **13.5× higher** than the one that binds. Buy I1 first; then, if demand warrants, **one at a time**.
5. **Any used workstation** (HP Z440, $234.56) — **100–110 W idle = $218.56–240.41/yr**, so it repays its
   own purchase price in **1.007 years** and then keeps charging. 16–28 cores do not clear the mesh's
   existing 80 threads, and the demand it would serve is unmeasured.
6. **Any rack server** — 125–252 W idle = **$273–551/yr**, plus a **+14 to +19 dB** noise gap against a
   micro-PC, and it buys **2× the capacity required**.
7. **A 128 GB DDR5 workstation ($5,224.61)** — **$44.28/turn** against the desktop's **$0 marginal**, a
   ~44× premium for capacity 13× above what binds.
8. **Any RAM purchase, for any node, in this market** — DRAM contract prices **+90–95 % QoQ in Q1 2026**
   and **+58–63 % projected for Q2**; DDR4 up **>50 % in Q3**. The mesh has **70.3 GiB free outside the
   laptop** and no measurement showing it used.
9. **Any disk upgrade for the authority** — no M.2 slot on that generation, no NVMe boot on an 8-series
   chipset, already on a SATA SSD with 134.8 GiB free, and its measured pain is **8,290 SQLite lock events
   in 7 days** — concurrency, not throughput. **$0, in software.**
10. **A transport upgrade to fix the DERP relay** — the premise is refuted. Re-check at the moment of any
    decision, because the path is a *reading*, not a property.
11. **Any capacity purchase at all, before I4 exists.**

## What must be measured before any money is spent

The demand log (I4) gates everything; then: where 295 MiB/turn stops being linear on the desktop (the
instrument's `-Count` is hard-capped at 3); the sshd-handshake curve at K=1,2,3,4,5,8; the **idle commit
floor on a bare node** — the ≈18 GB floor is measured on the *loaded laptop* and `doc 40` calls its absence
*"the single measurement that would most change this table"*; laptop responsiveness under **CPU-active**
load at N=6–8 (the existing probe returned a null with *sleeping* children); the `zabz-tech-linux` disk
breakdown; whether `secretary-api` is still leaking; and whether the Windows, Linux and macOS commit
metrics count the same quantity.

## The staged plan

**This week, $0, in order:** I1 → I2 → I3 *(done)* → I4 → I5 → I6 → I7.
**First thing worth money: nothing, until I4 has produced a week of demand data.** If — and only if — that
log shows sustained concurrent generating turns above **32**, buy **one** OptiPlex 5090 at **$197.26**,
after re-fetching the price. **One node, not three: the measured problem is spread, not stock.**
**And if the demand log stays below ~10 — the fan-out the mesh already handles reliably at 2 children × 5
nodes — then the honest plan is to buy nothing at all.**
