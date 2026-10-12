# 183 — The real mesh concurrency ceiling, and what actually caps it

**Measured 2026-10-12, 13:22–13:40Z, by a child agent running ON `zabz-tech` (Windows desktop, 32 logical / 24 physical cores, 65 GB RAM), driving `secratary-cloud` as the dispatcher over ssh.**
Broker: `secratary-cloud:/opt/mesh-broker` (PID 1097, `--host 127.0.0.1 --port 3091`), uptime 16 min at first contact. Repo HEAD read for this work: `8d48fd8` (authority `/root/code/harness-config`).

---

## 0. The answer

The owner is capped at ~10 because **the broker hardcodes a ceiling of 4 children per node**, and the cap is applied to every roster row while no row overrides it.

```
packages/mesh-broker/lib/config.js:40   export const DEFAULT_MAX_CHILDREN_PER_NODE = 4;
packages/mesh-broker/lib/config.js:125  maxChildren: childrenCap(entry.maxChildren, DEFAULT_MAX_CHILDREN_PER_NODE),
```

Three nodes answer today (`zabz-tech`, `zabz-yoga-1`, `zabz-tech-linux`), so the fleet ceiling is **3 × 4 = 12**. That is the whole of it.

**The binding constraint, in one sentence:** the broker's own per-node children cap of 4 — a single constant, applied uniformly — is 4.5× tighter than the slot arithmetic the same broker computes for the same node (18 free slots) and 3× tighter than the ceiling the node itself advertises (`accepts.maxChildren = 12`) and its own admission governor (`concurrency.limit = 8`).

This **corrects the premise the task was given.** `118-hardware-plan.md` records, from P332, that *"no cap on children per node exists anywhere."* That was true when it was written. The cap was added on **2026-09-18** (`packages/mesh-broker/test/children-cap.test.mjs` carries the measurement), and it is live. Any plan built on "there is no cap" is planning against a system that no longer exists.

---

## 1. Instruments, and the two that lied

| what | how |
|---|---|
| Live broker readings | `curl -s "http://127.0.0.1:3091/nodes?fresh=1"` **on secratary-cloud** (127.0.0.1 only) |
| Deployed roster | `cat /opt/mesh-broker/nodes.json` on secratary-cloud |
| A node's own decision | `curl -s https://<label>.tail93e6e6.ts.net/mesh/health` and `/mesh/capacity` |
| sshd limits | `sshd -T` on zabz-tech |
| The K-sweep | `/tmp/mesh183/sweep2.sh` on secratary-cloud, dispatching `ssh zabz-tech <child>`; sampler `C:\tmp\mesh183\sample*.tsv` on zabz-tech |

**Instrument lie 1 — the local ssh client.** `C:\Program Files\OpenSSH\ssh.exe` on `zabz-tech` **hangs forever**: no output, `-o ConnectTimeout=8` ignored, killed at 45 s. `C:\Program Files\Git\usr\bin\ssh.exe` to the same host completes in **307 ms**. Every early probe in this session hung because PATH `ssh` is the Windows one. The live MCP bridges on this box use the **Git** ssh (`C:/Program Files/Git/usr/bin/ssh.exe -T … secratary-cloud`), and a *pre-existing* hung Windows-OpenSSH process (`-n secratary-cloud`, PID 37676) was already resident when I arrived — so this is an estate condition, not something I created. **Any Windows dispatcher that resolves `ssh` on PATH hangs.** `mesh-run.mjs` defaults to `sshExe='ssh'` (`lib/ssh-transport.js:180`).

**Instrument lie 2 — a clock that changed units mid-run.** My first sweep printed `date +%s%3N` differences that were sometimes milliseconds and sometimes nanoseconds, producing absurd rows (a "probe" of 497469404 ms). I re-ran the whole sweep (`sweep2`) with `now_ms() { echo $(( $(date +%s%N) / 1000000 )); }` and only the corrected numbers appear below. `115-instruments.md` warns about exactly this class; it is worth adding "verify your timer's unit before you believe a ratio".

**Substitution, stated plainly.** Real mesh children are `dsh --profile headless` turns, which cost model spend — forbidden by the task. So each child is a harmless, deterministic, terminating ssh child that prints `CHILD_START`, sleeps 8 s, prints `CHILD_DONE`, and exits. Nothing touches the database or a model. Two weights were run:

* **light** — `Write-Output "CHILD_START"; Start-Sleep -Seconds 8; Write-Output "CHILD_DONE"` (transport/process load only).
* **heavy** — the same, preceded by `$a = New-Object byte[] 314572800`, i.e. **each child holds 300 MiB**, emulating the estate's measured **~295 MiB commit per Windows child**. This is the honest stand-in for the memory term.

---

## 2. The K-sweep: children at increasing concurrency against ONE node (`zabz-tech`)

Launched simultaneously from secratary-cloud; `started` = child printed `CHILD_START`; `completed` = printed `CHILD_DONE`; probes are 3 sequential `ssh zabz-tech hostname` handshakes taken **while the K children were resident**.

| mode | K | launched | started | completed | ssh fail | probe handshakes (ms) | child wall min/max (ms) |
|---|---|---|---|---|---|---|---|
| light | 2 | 2 | 2 | 2 | 0 | 526 / 501 / 499 | 8567 / 8589 |
| light | 4 | 4 | 4 | 4 | 0 | 535 / 467 / 504 | 8556 / 8591 |
| light | 8 | 8 | 8 | 8 | 0 | 518 / 504 / 476 | 8609 / 8641 |
| light | 12 | 12 | **11** | 11 | **1** | 548 / 498 / 506 | 62 / 8717 |
| light | 16 | 16 | **14** | 14 | **2** | 497 / 482 / 495 | 56 / 8717 |
| heavy | 2 | 2 | 2 | 2 | 0 | 486 / 512 / 514 | 8541 / 8581 |
| heavy | 4 | 4 | 4 | 4 | 0 | 482 / 503 / 498 | 8563 / 8621 |
| heavy | 8 | 8 | 8 | 8 | 0 | 519 / 528 / 478 | 8660 / 8694 |
| heavy | 12 | 12 | **11** | 11 | **1** | 513 / 516 / 513 | 60 / 8736 |
| heavy | 16 | 16 | **13** | 13 | **3** | 509 / 486 / 516 | 46 / 8745 |

Four results, and they are unambiguous:

1. **Every child that started, completed.** 100 % in both modes at every K. There is no partial-failure, timeout or half-started child anywhere in this range.
2. **The failures are all the same, and they are at the door:** `kex_exchange_identification: read: Connection reset by peer`. Nothing failed inside a child's work; the ssh session never got established. A failed child dies in **46–62 ms**, not after a wait.
3. **The sshd handshake does not scale with K.** Baseline is **0.50 s** (`ssh zabz-tech hostname` ×3, idle). At K=16, with 13–14 resident children, it is still **0.49–0.52 s**. Across every row above, the whole range is **467–548 ms**. This is the direct measurement that retires the premise behind the cap.
4. **Resource headroom was enormous.** From the samplers on zabz-tech during the heavy sweep: free memory never fell below **31 297 MiB of 65 173 MiB**; peak CPU was **21 %**; sshd processes peaked at **37**; established port-22 sessions peaked at **18**. Sixteen 300 MiB children cost ~4.8 GB of a 33 GB free pool and did not move the CPU needle.

> **P332 is not reproducible as a resource ceiling.** `118-hardware-plan.md` records "five children on one node pushed its sshd handshake to 8,041 ms". At K=5-equivalent load today the handshake is **~0.50 s**, and at 3× that load it is **~0.50 s**. Whatever produced 8,041 ms in September, it was not five children of this shape — and the constant of 4 was then derived from it ("Four leaves that handshake the headroom it needs on the weakest machine in the roster", `config.js:33-38`). **A cap calibrated on the weakest node is applied to the strongest node in the fleet, and the strongest node is the one the ranking prefers.**

---

## 3. The ceiling hierarchy on `zabz-tech`, strongest node, measured today

| # | ceiling | value | source |
|---|---|---|---|
| 1 | **broker roster cap** | **4** | `config.js:40` default, no row override; live `GET /nodes` |
| 2 | node's own admission governor | **8** | `/mesh/health` → `concurrency.limit: 8`, `binding: "cpu"` |
| 3 | node's declared max | 12 | `/mesh/capacity` → `accepts.maxChildren: 12` |
| 4 | CPU core term (24 physical × 0.75) | 18 | broker `scoreTerms.coreSlots: 18` |
| 5 | broker slot arithmetic | 24 → 18 effective | `slotArithmetic: "floor((32881 MiB free - 7821 MiB reserve) / 160 MiB) = 156 slot(s), capped at maxSlots=24 -> 24"` |
| 6 | memory at 295 MiB/child | **~105** | 31 297 MiB free ÷ 295 MiB (measured unit cost) |
| 7 | sshd simultaneous new connections | **~10 before random drop** | `sshd -T` → `maxstartups 10:30:100` |

The cap at row 1 is the smallest number in that table, and it is the only one that is a **constant in source code** rather than a measurement of the machine.

---

## 4. Each candidate constraint: did it bind?

**(a) sshd handshake time and its scaling with K — DID NOT BIND.** Flat at 467–548 ms from K=0 to K=16, both child weights (table §2). This is the candidate the estate believed was binding. It is not, at this load.

**(b) the node's own process/thread ceiling — DID NOT BIND.** 32 logical / 24 physical cores; 16 children plus 37 sshd processes and ~530 total processes on a machine already running 17 live agent sessions. Zero failures attributable to process or thread exhaustion; every started child completed. The node's own `/mesh/health` `hardCeiling: 24` was never approached.

**(c) memory — DID NOT BIND.** 16 heavy children × 300 MiB ≈ 4.8 GB against 31.3 GB free. Arithmetic ceiling ≈ 105 children at the estate's 295 MiB/child. The broker's own memory term is 24 slots, capped by the CPU term at 18.

**(d) the broker's ranking concentrating children on the biggest node — BOUND, and it is the mechanism by which the cap becomes a fleet ceiling.** The ranking prefers the strongest node (correctly). With the cap at 4, concentration means "the best node fills at 4", not "the best node takes 18". Live, all three reachable rows report `maxChildren: 4` regardless of size.

**(e) the dispatcher being serial — NOT the fleet cap, but worth naming precisely.** `bin/mesh-run.mjs` is a *single-run* instrument: it POSTs one `{kind:'fleet', children:N}` task to the broker (`mesh-run.mjs:259-260`) and then runs **one** local dsh process (`sshRunLocal`, `mesh-run.mjs:372`) whose own runtime spawns the children. It does not itself open N parallel ssh sessions. `lib/nodes.js` carries **no cap field at all** (only `ssh:` aliases and prose), so the dispatcher's node table cannot itself be the limiter. The real fan-out path is `lib/placement.js` → broker `freeSlots`.

**(f) an admission governor — BOUND, as the second ceiling.** Each node's `/mesh/health` publishes its own `concurrency.limit`: **zabz-tech 8**, **zabz-yoga-1 5**. It binds in the *direct-probe* path: `lib/failover-placement.js:71-77` reads exactly this field. So the two placement paths disagree — the broker path caps at **4**, the direct-probe path caps at **8/5**. `zabz-tech-linux` answers `/mesh/health` with **HTTP 404**, so on the direct-probe path it is invisible.

**(g) the node's gate or mesh HTTP surface rate-limiting — DID NOT BIND.** `/mesh/health` and `/mesh/capacity` answered in 93 ms and 63 ms while 14 children were resident. `limits.maxConcurrent: 8` with `refuseWhenFull: false` means the gate *queues*, never refuses.

**A constraint not on the list, which DID bind: `sshd maxstartups`.** `sshd -T` on zabz-tech reports `maxstartups 10:30:100` — OpenSSH's default. Above 10 simultaneous unauthenticated connections sshd begins randomly dropping new ones. Measured onset: **0 losses at K=8, 1 loss at K=12, 2–3 losses at K=16**, always `kex_exchange_identification: read: Connection reset by peer`. This is a *per-node* door limit, and it is why a burst of 12+ simultaneous dispatches to one node loses children even though the machine is idle.

---

## 5. The placement code — does a per-node cap exist?

**Yes. It exists in three places, and they disagree.**

1. **The cap itself — `packages/mesh-broker/lib/config.js:40`**
   ```js
   export const DEFAULT_MAX_CHILDREN_PER_NODE = 4;
   ```
   Applied at **`config.js:125`**: `maxChildren: childrenCap(entry.maxChildren, DEFAULT_MAX_CHILDREN_PER_NODE)`. `childrenCap` (line 43) returns the default for absent/0/nonsense, *"never 'unlimited'"*.

2. **Enforcement — `packages/mesh-broker/lib/broker.js:352-356`**
   ```js
   const machineSlots = Math.max(0, arith.slots - running);
   const rowCap = Number.isInteger(node.maxChildren) && node.maxChildren > 0 ? node.maxChildren : null;
   const capSlots = rowCap === null ? machineSlots : Math.max(0, rowCap - onNode.length);
   const cappedByChildrenCap = capSlots < machineSlots;
   const freeSlots = cappedByChildrenCap ? capSlots : machineSlots;
   ```
   `freeSlots` is the number the dispatcher gates on: **`lib/placement.js:786-797`** reads `row.freeSlots` and requires `freeSlots >= children`.

3. **Also a hard admission gate — `broker.js:383`**
   ```js
   if (acceptsOk && task.kind === 'fleet' && maxChildren !== null && maxChildren < task.children) { … }
   ```
   With `accepts.maxChildren = 12` and a 50-child fleet task this reasons `accepts.maxChildren=12 < 50 child(ren)`. Note it reads the **node's** declared 12 here — so within one function the broker honours 12 for admission and clamps to 4 for placement.

4. **The other path — `packages/plugin-remote-fanout/lib/failover-placement.js:71-77`** reads `health.concurrency.limit` (8 on zabz-tech) — *"Never a guess"*. **No cap here**, and a different number from the broker's.

5. **`lib/node-probes.js`** — no cap; it is the read half (probes `/mesh/health` and `/mesh/capacity`).
6. **`lib/nodes.js`** — no cap field; `lib/pressure.js` — no per-node children cap (it computes commit/memory pressure only).

**Live proof, not inference** — `curl -s "http://127.0.0.1:3091/nodes?fresh=1"` on secratary-cloud, 2026-10-12T13:29:47Z:

```
zabz-tech          state=ok   maxChildren=4   machineSlots=18  freeSlots=18
zabz-yoga-1        state=ok   maxChildren=4   machineSlots=12  freeSlots=12
zabz-tech-linux    state=ok   maxChildren=4   machineSlots=4   freeSlots=4
secratary          state=unreachable  maxChildren=4
lakewooechsmini    state=unreachable  maxChildren=4
```

and `/opt/mesh-broker/nodes.json` sets `maxChildren` on **no row** (verified: `top-level maxChildren key present: False`, every row `maxChildren=None`). So every node takes the constant.

---

## 6. The realistic maximum on this fleet today, with the arithmetic

```
reachable nodes today (live broker)      = 3      zabz-tech, zabz-yoga-1, zabz-tech-linux
                                        (secratary = unreachable + excluded/frozen;
                                         lakewooechsmini = unreachable)

fleet ceiling = reachable × broker cap   = 3 × 4 = 12
practically usable                       ≈ 11     (MaxStartups drops ~1 in 12 at K=12)
```

**12 is the answer, and ~10 is what the owner sees.** The missing 2 are the two dead rows.

What the same fleet would carry if each node were allowed what it says it can take:

```
broker machine slots   18 + 12 + 4   = 34
node governors          8 +  5 +  ?   = 13 + linux        (linux /mesh/health is 404, unknown)
node declared max      12 + 12 + 12   = 36
memory at 295 MiB      105 +  36 + 34 = 175
```
But you cannot bank on 34: the nodes' own governors bind at 8 and 5, and **sshd `maxstartups 10:30:100` starts shedding simultaneous connections above 10 per node**. So the honest figure is:

> **Today: 12 (observed ~10).**
> **With the smallest safe change (per-node caps set to each node's own governor): ~13–17, after which the two live nodes are limited by `maxstartups` at ~10–12 each, not by the broker.**
> **50 is not reachable on this fleet without either ~5 nodes carrying ~10 each, or raising the node governors — and those governors are calibration policy, not hardware (see §7).**

To be explicit about the "hardware is powerful" intuition: on `zabz-tech` alone the measured headroom at K=16 was 31.3 GB of 33 GB free, 21 % CPU, 0 process-ceiling failures. The machine is not the limit. **The limit is a constant.**

---

## 7. What to change, ordered by value per unit of risk

### 1. Set `maxChildren` per row instead of inheriting a flat 4 — highest value, lowest risk
* **File:** `packages/mesh-broker/nodes.json` (and the deployed `/opt/mesh-broker/nodes.json`).
* **Change:** `"maxChildren": 8` on `zabz-tech`, `5` on `zabz-yoga-1`, leave `zabz-tech-linux` and the two dead rows alone. These are not guesses — they are each node's **own** `/mesh/health` `concurrency.limit`.
* **Expected effect:** fleet ceiling **12 → 17**.
* **Verify:** `curl -s "http://127.0.0.1:3091/nodes?fresh=1"` shows the new per-row cap, then re-run the §2 sweep at K=16 in heavy mode and require no new failure class. `npm test` in `packages/mesh-broker` (`test/children-cap.test.mjs` pins the cap semantics).
* **Owner decision: yes for `zabz-yoga-1` only.** That is his own laptop; 5 is the ceiling its governor already computes from a 42 % CPU budget, but it is his responsiveness.

### 2. Raise `MaxStartups` on the Windows nodes — removes the real transport loss
* **File:** `C:\ProgramData\ssh\sshd_config` on each Windows node (`sshd -T` currently: `maxstartups 10:30:100`).
* **Change:** e.g. `MaxStartups 100:30:200`. This is the *only* thing that actually failed under load in §2.
* **Expected effect:** no child lost to simultaneous dispatch up to ~100 in flight; makes the ceiling in change 1 usable rather than probabilistic.
* **Verify:** re-run the K=16 sweep and require **16/16 start** in both modes (today: 14/16 light, 13/16 heavy).
* **Owner decision: yes — this touches service configuration.** I did not change it; the task forbids it.

### 3. Make the cap follow the machine instead of a constant
* **File:** `packages/mesh-broker/lib/config.js:40` (and `lib/broker.js:353`).
* **Change:** replace the flat default with the node's own published limit — read `concurrency.limit` from `/mesh/health` (the broker already has a bounded reader in `lib/capacity.js`; this is a second read of the same shape) and use `min(rowOverride ?? ∞, nodeLimit, machineSlots)`. Keep 4 as the floor for a node that publishes nothing, never as the ceiling for one that publishes 8.
* **Expected effect:** the cap stops being a fleet-wide constant; a 32-core desktop is no longer capped at the number chosen for the weakest machine.
* **Verify:** `test/children-cap.test.mjs` extended with "a node publishing `concurrency.limit: 8` and no row override places 8"; live `/nodes` shows per-node caps that differ.
* **Owner decision: no.** This is a development decision.

### 4. Fix `zabz-tech-linux` `/mesh/health` (HTTP 404)
* **Evidence:** `curl -s -w "HTTP=%{http_code}" https://zabz-tech-linux.tail93e6e6.ts.net/mesh/health` → **404** (while `/mesh/capacity` answers 200 and the broker reads it `state=ok`). The other two Windows nodes answer `/mesh/health` with the full document.
* **Consequence:** `lib/node-probes.js:78` probes `/mesh/health`, so when the broker is unreachable the direct-probe fallback silently sees only 2 nodes, and this node's own governor and limit are unknown to the mesh.
* **Verify:** `curl -s -o /dev/null -w "%{http_code}" https://zabz-tech-linux.tail93e6e6.ts.net/mesh/health` → 200.
* **Owner decision: only if it needs a service restart on that box.**

### 5. Restore `lakewooechsmini` (unreachable) — a whole node of capacity
`state=unreachable` in the live broker, so a 4th node (which its roster row says is v1-dispatchable) contributes **zero**. This is the same class of defect the roster's own `lakewooechsmini` note records being repaired once before on 2026-10-08 (identity drift). Worth a probe before any spending decision.

### 6. Windows dispatchers must not use PATH `ssh`
* **Evidence:** §1, instrument lie 1 — `C:\Program Files\OpenSSH\ssh.exe` hangs indefinitely with no timeout honoured; Git's ssh answers in 307 ms. A pre-existing hung Windows-OpenSSH process was resident on this box.
* **File:** `packages/plugin-remote-fanout/lib/ssh-transport.js:180` (`sshExe || 'ssh'`) and whatever Windows profile sets it.
* **Verify:** on a Windows node, `ssh -o BatchMode=yes -o ConnectTimeout=5 <node> hostname` returns within 5 s.

### Not recommended without the owner
Raising the node governors. `concurrency.limit` is `logicalCpus × 0.42 ÷ 1.68` — a **42 % CPU budget** and a **1.68 logical-CPU-per-tool-heavy-turn** figure, both from `84-calibration.md`. Those are deliberate human-factors calibrations ("the largest occupancy measured benign"), not hardware limits, and raising them is exactly the trade that degrades the owner's own machine while he is using it. That is his call, not a development decision.

---

## 8. What I did not measure, and what would settle it

* **No real `dsh` child was run** — deliberately, because they cost model spend and the task forbids it. The heavy child (300 MiB + 8 s) reproduces the memory term but not the CPU or the multi-second tool-call shape of a real turn. **A single real child at K=1, 4 and 8, with `Get-NodeSample.ps1` running, is the one missing measurement** and would confirm or retire the 42 %-budget calibration directly.
* **`zabz-yoga-1` and `zabz-tech-linux` were not swept.** Only `zabz-tech` was load-tested, as instructed. Since the cap applies to all three identically, the fleet figure follows from the cap — but the yoga sweep is the one that would price change 1 against the owner's laptop.
* **The broker was read, never written.** No service state, crontab or profile was changed on any host; the only files I created were scratch under `/tmp/mesh183` on secratary-cloud and `C:\tmp\mesh183` on zabz-tech, plus this document. Every child was waited on; a final check shows **0** ssh processes left from my work on zabz-tech and no `sweep2.sh` running on secratary-cloud.
* **`maxstartups` was inferred from `sshd -T` plus the failure signature** (`kex_exchange_identification: read: Connection reset by peer`), not from a direct manipulation of the parameter — which would have meant changing service configuration.

---

*Measured by a child agent on `zabz-tech`, 2026-10-12. Scratch: `secratary-cloud:/tmp/mesh183/` (`sweep.sh`, `sweep2.sh`, `sweep2.tsv`, `sweep2.log`), `zabz-tech:C:\tmp\mesh183\` (`sample.tsv`, `sample2.tsv`).*
