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
| mac-mini-ts | LakewooechsMini (macOS) | yes | 764 | 10 | 16384 | — | — | 46.0 | **absent** | no | no | yes |

A dash means the node did not answer that field. It never means zero.

## What this changes about placement

1. **ZABZ-TECH is the only node with real room.** 32 cores, 38.8 GB free, 39.5 GB commit free, 185 GB
   disk. It is 2.8x the laptop's free physical memory. The broker already prefers it (measured today:
   a probe child landed there and returned in 5.787 s while the laptop stayed flat). Nothing in the
   design should move work back onto the laptop while the desktop is up.

2. **`secratary` cannot absorb agent work — it is nearly out of commit.** 3.4 GB commit free on a
   22.9 GB box, and it is the authority that every other node queries plus the always-on company
   engine (18 agents, ~300 ticks/day). It is the *last* place to add a child, not the first. Its
   4 cores and node v20.20.2 make it a poor compute target as well. This is a constraint the node
   table in `lib/nodes.js` does not carry, and it is exactly the kind of fact that decides a placement.
   The knob that would let it participate is a measured, enforced ceiling — not a name in a list.

3. **`mac-mini-ts` cannot host a DSH child at all: node is absent.** Its row in `lib/nodes.js` says the
   INTERPRETER form was measured working on 2026-09-17 against `/usr/local/bin/node`; today there is no
   node on PATH. Either the row is stale or the runtime was removed. Until it is resolved the objective's
   "mac mini" node is a name that cannot run anything — a node that claims capability it does not have,
   which is the same failure class as the 2026-09-17 `zabz-tech-linux` "no Node runtime yet" note.

4. **`linux-pc-ts` is the tightest disk on the mesh (20.9 GB free) and the only node with `dsh` on PATH.**
   The second fact is why its row was re-verified on 2026-09-17 and is the working Linux dispatch path;
   the first is why it should not be given artifact-heavy work.

5. **`dshOnPATH` is false on the laptop, the desktop and secratary.** This is expected — those three use
   the interpreter form (`node <dsh>/lib/bin.js`) with the credential coming from the dispatching
   process environment — but it means **`dsh` on PATH is not a capability flag and must not be used as
   one** by any placement logic.

6. **The laptop is not currently under memory pressure** (13.7 GB free, 20.8 GB commit free). The
   "0.403 GB per running turn, ~111 turns before it pages" figure is a ceiling for a loaded machine,
   not a statement about now. Placement must read the live number, which this probe provides.

## Still to measure (not in this pass)

- The mesh's own **latency matrix** (node-to-node), which decides whether a child should be placed by
  capacity or by proximity to the data it needs.
- **Cost of a child turn per node** measured end to end, not inferred from sshMs.
- Whether `secratary`'s commit pressure is structural or a leak in the running engine (3.4 GB free is
  low enough that it should be explained, not merely respected).
