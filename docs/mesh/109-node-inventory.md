# 109 — Measured mesh inventory (2026-09-18)

Deliverable 1 of the mesh goal. Produced by `_scratch/mesh-inventory/run-inventory.ps1`, which pipes a
read-only probe into each node over ssh and never writes anything remote. Raw readings (one JSON line
per node, including the unreachable text) are in `_scratch/mesh-inventory/inventory.jsonl`.

Re-run it before making any placement decision: every number below is a reading with a timestamp, and a
placement made from a stale row is the same class of error as reading a stale database.

Measured **2026-09-18 15:00Z from ZABZ-YOGA**. `sshMs` is the wall clock for the whole probe over ssh,
so it is a floor on the cost of reaching that node, not a ping.

| node | what | reachable | sshMs | cores | memTotalMiB | memFreeMiB | commitFreeMiB | cFreeGiB | node | dshOnPATH | engine:3099 | harness-config |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| laptop-ts | ZABZ-YOGA (laptop, this machine) | yes | 3373 | 22 | 32373 | 13678 | 20812 | 48.4 | v24.12.0 | no | yes | yes |
| desktop-ts | ZABZ-TECH (office desktop) | yes | 3348 | 32 | 65173 | 38761 | 39504 | 185.5 | v24.19.0 | no | yes | yes |
| secratary-ts | secratary (Linux authority) | yes | 734 | 4 | 23421 | 15349 | 3369 | 134.8 | v20.20.2 | no | no | yes |
| linux-pc-ts | zabz-tech-linux | yes | 1018 | 12 | 11673 | 10329 | 4666 | 20.9 | v22.23.2 | yes | yes | yes |
| mac-mini-ts | LakewooechsMini (macOS) | yes | 764 | 10 | 16384 | — | — | 46.0 | absent-on-PATH (v24.19.0 present) | no | **yes** | yes |

A dash means the node did not answer that field. It never means zero. **Two cells in the mac-mini row
were wrong and are corrected below** — the readings were real, the probe could not see the machine.

## Correction, 2026-09-18: the probe was wrong, not the machine

Workstream M3 re-measured `mac-mini-ts` and falsified two conclusions drawn from the row above. Both were
**probe defects on macOS**, and both have been fixed in `_scratch/mesh-inventory/probe.sh`.

1. **`node: absent` was a false negative.** sshd hands a non-interactive macOS session the PATH
   `/usr/bin:/bin:/usr/sbin:/sbin`. This machine keeps node in `/usr/local/bin` (`/usr/local/bin/node`
   → `/usr/local/lib/nodejs/node-v24.19.0-darwin-arm64/bin/node`, **v24.19.0**, Mach-O arm64, `-v`
   rc=0) and in `~/.local/node-v24.12.0-darwin-arm64/bin/node` (**v24.12.0**), the second added only by
   `.zshrc`/`.zprofile`, which a non-interactive ssh never reads. **Two working node runtimes exist and
   nothing needs installing.** The probe now falls back to the absolute locations and reports *which*
   path answered, so "no runtime" can no longer be confused with "no runtime on this PATH".
2. **`engine:3099 = no` was a false negative.** The probe asked `ss -ltn || netstat -ltn`; macOS has no
   `ss`, and BSD `netstat` does not take `-ltn`, so the count was 0 by error. `lsof -nP -iTCP:3099
   -sTCP:LISTEN` shows **pid 12458 listening on 127.0.0.1:3099** — a DSH engine, running under node
   v24.12.0, on a box up 45 days with load 1.8 and 46 GB free. The probe now uses `ss`, then `lsof`,
   then `netstat -an -p tcp`. **A DSH engine is already running on the mac mini.**

So `mac-mini-ts` is a **live, capable node**, not a stale row. It is the fifth compute node, and it is
already serving someone.

## What this changes about placement

1. **ZABZ-TECH is the only node with real room.** 32 cores, 38.8 GB free, 39.5 GB commit free, 185 GB
   disk — 2.8x the laptop's free physical memory. The broker already prefers it (measured: a probe child
   landed there and returned in 5.787 s while the laptop stayed flat). Nothing in the design should move
   work back onto the laptop while the desktop is up.

2. ~~**`secratary` cannot absorb agent work — it is nearly out of commit.**~~ **OVERSTATED. CORRECTED
   2026-09-18 by workstream M2.** The headline number was misleading in the direction that mattered.
   `vm.overcommit_memory = 0`, i.e. **heuristic mode: `CommitLimit`/`Committed_AS` are computed and
   reported but NOT enforced** — the kernel does not refuse an allocation because commit looks tight.
   So "3.4 GB commit free" never meant 3.4 GB usable. M2 measured `Committed_AS` at ~10.3–10.4 GB,
   **about 44 % of RAM**, and ~5.5 GB of *actual* free commit; and `MemAvailable` at 17.7 GB, which is
   real reclaimable RAM. The binding constraint is something else entirely.
   **What is actually scarce is SWAP: 4 GiB, 100 % full, 216 kB free.** With `vm.swappiness = 10` and
   nothing evictable left, there is **no reclaim buffer for anonymous memory** — a spike goes straight
   to the OOM killer. And the box's biggest tenant is a documented runaway: `secretary-api` (uvicorn)
   carries a drop-in (`20-memory-guard.conf`) that pins MemoryHigh 5 GB / MemoryMax 8 GB because it
   previously reached ~20 GB and the kernel's global OOM killer took the victim instead — 8 kills on
   2026-09-15 and 23 more on 2026-09-16. It was cycling through stop-sigterm/restart **during M2's
   probes**, which is why M2 could not reproduce this document's 15,349 MiB / 3,369 MiB sample: the
   numbers moved between readings because the tenant was being killed and restarted underneath them.
   **M2's verdict: `secratary` CAN host a long-lived agent child** — but it must stay modest (hundreds
   of MB, not GB), and the machine is one API runaway away from a global OOM. The correct rule is not
   "never place here" but "place small, watch the swap, and do not co-locate anything large with
   `secretary-api`". Note also that the 18-agent engine itself (`dsh-engine`, ~347 MB) is **not** the
   memory problem — the API is.

3. **`mac-mini-ts` is usable, and the way it failed is the more valuable lesson.** It has 10 cores,
   16 GB, 46 GB free, a 45-day uptime — and a working DSH engine on 3099. The only thing standing
   between it and accepting a child from the mesh is that the non-interactive PATH does not contain the
   node that already exists. **A node's absence from a list, and a capability's absence from a
   non-interactive environment, are two different facts; conflating them produced a wrong conclusion in
   the first version of this document.**

4. **`linux-pc-ts` is the tightest disk on the mesh (20.9 GB free) and the only node with `dsh` on PATH.**
   The second fact is why its row was re-verified on 2026-09-17 and why it is the working Linux dispatch
   path; the first is why it should not be given artifact-heavy work.

5. **`dshOnPATH` is false on the laptop, the desktop, secratary and the mac mini.** Those use the
   interpreter form (`node <dsh>/lib/bin.js`) with the credential coming from the dispatching process
   environment, so **`dsh` on PATH is not a capability flag and must not be used as one** by any
   placement logic. M3's finding is the same lesson one layer down: `node` on PATH is not a capability
   flag either.

6. **The laptop is not currently under memory pressure** (13.7 GB free, 20.8 GB commit free). The
   "0.403 GB per running turn, ~111 turns before it pages" figure is a ceiling for a loaded machine,
   not a statement about now. Placement must read the live number, which this probe provides.

## Still to measure (not in this pass)

- The mesh's own **latency matrix** (node-to-node). Workstream M1 attempted this from `desktop-ts` and
  **failed**: its own ssh to another node hung at connect and the child exited 255 with no final
  message. That is itself a finding — **node-to-node ssh from the desktop is not reliable, while
  laptop-to-node ssh answered every node in under 3.4 s.** A scheduler cannot assume any node can reach
  any other; reachability is directed and has to be measured per direction.
- **Cost of a child turn per node** measured end to end, not inferred from `sshMs`. First datum:
  449,151 ms (7.5 minutes) for M3's child on `desktop-ts`, exit 0 — and that is past the old 300 s
  ceiling, which is the timeout fix verified by observation rather than by config.
- ~~Whether `secratary`'s commit pressure is structural or a leak.~~ **ANSWERED by M2**: neither, as
  framed. The commit figures are advisory (`vm.overcommit_memory = 0`); the scarce resource is the
  **fully consumed 4 GiB swap**; and the one tenant with a runaway history is `secretary-api`, bounded
  by a cgroup drop-in at 5/8 GB. What remains unmeasured: whether `secretary-api` is still leaking —
  M2 declined to call it a leak from RSS-vs-age alone, since its 3.35 GB sits inside the 1.8–3.6 GB
  warm footprint its own guard documents. That needs its restart history read, not another snapshot.
- **A node is not isolated just because a child could not reach another node from it — and this was
  nearly written down the wrong way.** A child on `desktop-ts` reported all five aliases HANGing,
  *including the self-hop*, and concluded "treat `zabz-tech` as isolated over ssh; no node is
  reachable at any cost". **That is false, and it was falsified by two siblings in the same hour**
  (one measured `secratary` over ssh, one measured `mac-mini-ts` over ssh, both returning full
  reports), and then by direct reproduction from the laptop:
  | from `desktop-ts` to | reported hostname | wall clock |
  |---|---|---|
  | `mac-mini-ts` | LakewooechsMini | 205 ms |
  | `linux-pc-ts` | zabz-tech-linux | 315 ms |
  | `secratary-ts` | secratary | 522 ms |
  | `laptop-ts` | zabz-yoga | 1069 ms |
  All four work, and all four are fast. **The real defect is in how the ssh client's output is
  captured:** on that node, an ssh whose **stdout is a pipe** — inline `& ssh`, or `Start-Job { & ssh }`
  — never returns and consumes its whole timeout, while the same command with
  `Start-Process -RedirectStandardOutput <file>` completes in under 1.1 s. M2 found this independently
  and routed every probe that way; the child that reported "isolated" used `Start-Job` and read its own
  wrapper's failure as a property of the network.
  **For a scheduler:** node-to-node work is available in both directions; what must be avoided is a
  brief that asks a Windows child to capture another process's stdout through a pipe. And for the
  record: this is the **fourth** false conclusion this mesh produced from a probe's inability to look,
  in one session, after `node` on PATH, `engine:3099` on macOS, and `secratary`'s commit figures.
- **The child-turn ceiling fix is verified by observation, not by config**: M3 ran 449,151 ms and M2
  ran 503,943 ms, both `exit = 0`, both on `desktop-ts`. Both are past the old 300,000 ms ceiling that
  killed five fleets on 2026-09-17.
