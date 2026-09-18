# 93 — Transport concurrency: what each dispatch transport does at load, and the per-node ceiling

**Stream:** the transport-concurrency question — per-node safe concurrency, and the two transports'
different shapes. **Owns:** `packages/plugin-mesh-http/**`, this file.
**Written:** 2026-09-17 13:20Z–14:10Z, measuring **`zabz-tech`** (32 logical / 24 physical, 65,173 MiB,
otherwise idle) from the laptop over the tailnet.
**Author:** a delegated session, not the owner.
**Cost:** **29 child turns** against a 30-turn budget — 25 over the HTTP route (confirmed by the
node's own counter, §9) and 4 over ssh. Zero on ZABZ-YOGA's engine.

> **The headline.** v2's hard ceiling of one agent per node is gone. The route now admits
> **`min(cpu, mem, declared, hard)` = 8** concurrent children on `zabz-tech`, derived from that
> machine's own cores and commit, and a request beyond the limit **is not refused — it is given a
> position and served in arrival order**. Twelve simultaneous requests were measured: 8 admitted
> immediately, 4 queued at positions 1–4, **all 12 answered, 0 refused, 12/12 reporting the correct
> node**, and the target's own process list never showed more than **8** children. Nothing degraded:
> pagefile 0 % in every sample, disk queue 0, engine loop-lag maximum unchanged at 17 ms.
>
> **And the transports really do have different shapes.** v1 (ssh) has **no ceiling of its own** —
> measured: twelve concurrent ssh sessions all completed — but its limit is the *target's sshd*,
> whose `MaxStartups 10:30:100` is the compiled default (the config lines are commented out), so
> beyond ~10 simultaneous new connections the node may drop them and v1 will never know. v2's limit
> is enforced where the work is, and it reports what it did.

---

## 0. The answer in one screen

**(1) What is the real per-node ceiling, and why that number?** `zabz-tech`: **8**.
`limit = max(1, min(cpu, mem, declared, hard))`:

| term | value | how |
|---|---|---|
| `cpu` | **8** | `floor(32 logical × 0.42 ÷ 1.68)` — 13.44 logical CPUs of budget ÷ the measured cost of a tool-heavy turn |
| `mem` | 112 | `floor((52,976 − 7,821) ÷ 403)` |
| `declared` | 12 | the node's own capacity contract (`accepts.maxChildren`, `phone-gate.py:939`) |
| `hard` | 24 | the admission governor's own ceiling on this host |

`cpu` binds. Every constant is a measurement from `84-calibration.md`, cited in the response itself
(§2). Across the mesh the same function gives **8 / 5 / 1 / 3 / 1** (§2.2).

**(2) Does the route still refuse anything?** No — not for capacity. The only `429` left is
`node-queue-wait-exceeded`, a **wait budget** (780 s by default, deliberately shorter than a
dispatcher's own 900 s POST budget so the node always answers first).

**(3) Which transport wins?** **v2 is the default, for a single child and for a fleet.** v1 wins in
exactly three stated cases — a node with no route or no secret, a caller who deliberately wants a node
oversubscribed past its measured ceiling, and a route that cannot be reached. **It is explicitly not
chosen because the node is busy**, which is what the old fallback did and what would have moved a
child to another machine for no reason. §7 has the numbers.

---

## 1. What was built, in this package

| file | what changed |
|---|---|
| `lib/concurrency.js` | **new.** `deriveConcurrencyLimit()` — the arithmetic above, pure and testable; `readAvailableMemoryMiB()` (commit headroom from `/proc/meminfo` on POSIX, `os.freemem()` on Windows, and it says which it used); `createDeclaredCapacityReader()` — the node's own capacity contract over loopback, TTL-cached, single-flight, fail-soft |
| `lib/runner.js` | the single slot became **`maxConcurrent` + a FIFO**. Admission is **synchronous** and the slot is reserved in the same step it is tested (an `await` between the two would have let N simultaneous dispatchers all observe the same free slot — there is a test for it); `release()` hands the slot to the head of the queue inside the same step that frees it, so the queue can never over-admit |
| `lib/handler.js` | `POST /mesh/run` answers with **`queue: {position, waitedMs, limit}`**; `GET /mesh/health` publishes `concurrency` — the limit, every term, every input, and the source of every constant — and awaits one TTL-cached capacity read so the number it quotes is current |
| `lib/index.js` | `v0.2.0`; `readEnvConfig()` — every knob overridable by environment, explicit config wins; the ceiling follows the machine (re-read on mount, on every health call, on every dispatch) and can never exceed `hardCeiling` |
| `lib/node-identity.js` | rewritten — two measured defects fixed, §8 |
| `bin/mesh-dispatch.mjs` | the transport order became a **documented decision** (`-Transport v1\|v2\|auto`, `-PreferV1`); **a busy node no longer triggers a fallback** — it queues; the node's ceiling, identity state and the run's queue position are carried into the caller's record |
| `bin/mesh-http.mjs` | `check` and `probe` report the limit, its arithmetic, and whether the node's identity is corroborated |
| `test/mesh-http.test.mjs` | **36 tests, 36 pass** — including the queue's arrival order and visible positions, six simultaneous callers against two slots, the wait-budget expiry, the derivation's every branch, and both identity defects |
| `test/concurrency-sweep.mjs`, `test/run-level.mjs`, `test/sweep-sampler.ps1`, `test/ssh-file.ps1` | the measurement rig. Kept because every number below can be regenerated with them, and because two of them exist to work around defects that cost an hour each (§4) |

**Verified on both machines:** `node --test test/mesh-http.test.mjs` → `pass 36 / fail 0` on
ZABZ-YOGA (13:41Z) **and on `zabz-tech`** (13:33Z, with the shipped copy).

---

## 2. The arithmetic, stated so it can be checked without reading the source

### 2.1 The four terms, and the measurement behind each

```
cpu      = floor(logicalCpus × CPU_BUDGET_FRACTION / CPU_PER_TURN)
mem      = floor((availableMiB − reserveMiB) / COMMIT_PER_TURN_MIB)
declared = the node's own advertised fleet ceiling, when its gate answers  (else absent)
hard     = 24 — the admission governor's own slot ceiling on this host
limit    = max(1, min(cpu, mem, declared, hard))
```

| constant | value | source |
|---|---|---|
| `CPU_BUDGET_FRACTION` | 0.42 | **`84` §4.1/§4.3:** on `zabz-tech`, 8 tool-heavy turns occupied **41.5 % mean / 62.9 % max** of all 32 logical CPUs with commit at 16 % of its limit, the pagefile flat and the disk queue at 0–1 — the largest occupancy the program has ever measured without a fleet-sized cost |
| `CPU_PER_TURN` | 1.68 | **`84` §4.3:** a tool-heavy turn = 1.68 logical CPUs. The **worst** measured class, deliberately |
| `COMMIT_PER_TURN_MIB` | 403 | **`84` §3:** the level-mean fit, CI 270–533 |
| `reserveMiB` | `max(2048, 12 % of physical)` | **`84` §4.4** / `phone-gate.py:1110-1149` |
| `hard` | 24 | the governor's own ceiling ("clamped 4-24") |

**The unit trap this avoids, and the one it does not.** `84` §4.3 measured `CPU_PER_TURN` in *logical*
CPUs and validated `0.75 × physical cores` in *physical* ones, and §6.6 records that the
logical→physical conversion under SMT was never measured. A first version of this file multiplied a
logical-CPU budget by `0.75` (a physical-core fraction) and produced 14; that is a units error, and the
fix is to keep everything in the unit that was actually measured. **`84`'s `0.75 × physical` and this
rule's 8 are both inside `84`'s measured 14–39 band for "24 cores' worth of turns"** — 8 is the
conservative end, and it is the end anchored in a measurement rather than an extrapolation.

**What the memory term is, honestly.** On POSIX it is genuine commit headroom
(`CommitLimit − Committed_AS`) read from `/proc/meminfo` with no dependency. **On Windows there is no
such file and Node exposes no commit API**, so it falls back to `os.freemem()` — *free physical*, not
commit headroom — and the response names that (`availableSource`). It is tolerable for one measured
reason: `84` §5.3 found the memory term is 8× the CPU term on both measured nodes, so it never binds
there. On `lakewooechsmini` it does bind (§2.2), which is the case the term exists for.

### 2.2 Every node in the mesh, through the same function

Inputs measured 2026-09-17 13:32–13:56Z. `secratary` and `zabz-tech-linux` are Linux, so their memory
term is real commit headroom; the two Windows nodes and the Mac use free physical.

| node | logical CPUs | total MiB | available MiB | cpu | mem | declared | **limit** | binding | source of the numbers |
|---|---|---|---|---|---|---|---|---|---|
| `zabz-tech` | 32 | 65,173 | 52,976 | 8 | 112 | 12 | **8** | cpu | engine `/mesh/health` + gate `/mesh/capacity`, 13:32Z |
| `zabz-yoga-1` | 22 | 32,373 | 12,701 | 5 | 21 | 12 | **5** | cpu | `mesh-http.mjs check` on the laptop, 13:52Z |
| `secratary` | 4 | 23,422 | 5,168 | 1 | 5 | — | **1** | cpu | `nproc` + `/proc/meminfo`, 13:56Z |
| `zabz-tech-linux` | 12 | 11,673 | 4,675 | 3 | 6 | — | **3** | cpu | `nproc` + `/proc/meminfo`, 13:56Z |
| `lakewooechsmini` | 10 | 16,384 | 236 | 2 | **1** | — | **1** | **mem** | `sysctl` + `vm_stat`, 13:56Z |

Three things this table says that a constant could not:

* **`secratary` gets 1.** `84` §6.2 recorded that 8 concurrent turns on the authority's 4 cores is a
  **2× oversubscription** and could not measure it there. Nothing has to decide that now.
* **The Mac is limited by memory, not cores** — 236 MiB free physical, beside an engine that §5 of
  `83` measured with `swapUsedPct 58`. The memory term earns its place by binding on exactly the node
  that is a human's computer.
* **A big node is still held to what it published.** On a 128-core node the `cpu` term reaches 32 and
  the `declared` ceiling of 12 binds — v2 cannot accept more than the capacity contract advertises.

**The limit is a fleet-mix parameter, and one env var moves it.** These defaults assume the *worst*
turn class. A node operator who knows his fleet is model-bound sets
`MESH_HTTP_CPU_PER_TURN=0.62` (`84` §4.3's resident figure) and `zabz-tech` becomes
`min(21, 112, 12, 24) = 12`, with the `declared` ceiling binding. **Measured, not asserted** — the same
function, printed by the same script. Nothing in the code changes; the arithmetic is re-stated in
`/mesh/health` on the next capacity refresh.

**What that means for the owner's 55 agents.** With v2 across the three nodes that can currently
serve: **8 + 5 + 1 = 14 concurrent children**, and 55 flows through in ~4 waves with **nothing
refused**. `zabz-tech-linux` would add 3 (it has no route deployed — and see §10.5). That is the safe
answer, and it is a *throughput* answer rather than a concurrency one: a queue that drains is not a
ceiling, but a node running 55 children at once on 4 cores is a node that stops.

---

## 3. The contract a caller sees

`POST /mesh/run`, 200:

```json
{ "ok": true, "exitCode": 0, "host": "zabz-tech", "ms": 20758,
  "queue": { "position": 2, "waitedMs": 4758, "limit": 8 },
  "stdout": "MESH-HOST: zabz-tech\nSWEEP-OK zabz-tech\n", … }
```

`position: 0` means admitted immediately; anything else is the place it held in the node's FIFO and
how long it held it. **The position reported is the one it held WHEN IT ARRIVED**, not the renumbered
place it was later promoted to — a real defect the tests caught (the third arrival was being told it
had been first).

`GET /mesh/health` adds `concurrency` (limit, `terms`, `inputs`, `sources`, `note`, and the capacity
contract it read with the moment it read it), and `limits.maxConcurrent` / `maxQueueWaitSec` /
`refuseWhenFull`. `limits.oneRunAtATime` survives for a reader that only knows v0.1.0 and is **true
exactly when the derived ceiling happens to be 1** — on a node with a real capacity contract, false.

| status | reason | when |
|---|---|---|
| 200 / 504 / 502 | (a run) | as before; the body now carries `queue` |
| 429 | `node-queue-wait-exceeded` | the queue did not drain within `maxQueueWaitSec`. **Not a capacity refusal.** |
| 429 | `node-busy` | **only** when `refuseWhenFull` is set (off by default; v0.1.0's behaviour, kept, not defaulted) |

**A run is not cancelled when the client disconnects** (unchanged from v0.1.0, and now consequential):
a caller that gives up while the node is still running the child has paid for a turn whose answer
nobody saw. The default 780 s queue budget against a dispatcher's default 900 s POST budget is chosen
so the node always answers first.

---

## 4. The measurement method, and the three rig defects it exposed

**Load:** *N* identical real agent turns — `node <dsh>/lib/bin.js --profile headless "<prompt>"` on
the target, the exact command both transports issue — fired from one **synchronous** loop so the
concurrency is the caller's, not a queue's. The prompt does `Start-Sleep -Seconds 4 ; hostname` and
must report **two** lines, `MESH-HOST: <node>` and `SWEEP-OK <hostname>`.

**The target's side:** `test/sweep-sampler.ps1`, one counter set, one window, sampled every 3 s —
`\Memory\Committed Bytes`, `\Memory\Available MBytes`, `\Memory\Pages Input/sec`,
`\Paging File(_Total)\% Usage`, `\PhysicalDisk(_Total)\Current Disk Queue Length`,
`\Processor(_Total)\% Processor Time`, plus the **`--profile headless` process count from the target's
own process list** and the target engine's own `GET /healthz` loop lag. `Load`, `Pages free` and
`% Disk Time` are not used: `81` §3.6 records that each has already misled this program once.

**Three defects in my own rig, each found by a measurement that said nothing:**

1. **A `Start-Process`-detached sampler on the target is killed when the ssh session that launched it
   exits.** The CSV contained the header and nothing else, while the identical script inside a live
   session produced a row every four seconds. The remote program now runs the sampler in the
   **foreground** for a bounded number of seconds inside a session held open for the whole level, so
   there is nothing detached and nothing to clean up.
2. **`CounterSamples.Path` is machine-qualified** — `\\zabz-tech\memory\committed bytes` — so a lookup
   keyed on `\memory\committed bytes` returned nothing and **every memory, CPU and disk cell read 0**,
   while the loop lag and the child count (read differently) were correct. A row that is half zeroes
   looks like an idle machine. Fixed by stripping the machine prefix.
3. **The prompt let the child drop the proof-of-location line.** The first version ended *"reply with
   exactly one line: SWEEP-OK …"*, and the child obeyed the nearer instruction — a run with
   `meshHostLines: 0`, which `83` §8 identifies as the shape that reads as "a child that did not
   report". The line is now demanded in the same breath as the answer, and the level that first hit
   this (`v2-n1`) is reported as it was, not silently re-run.

A fourth, cheaper lesson: `--secret-file` was missing on the first `v2-n12` attempt and the driver
died **before dispatching anything** — 0 turns spent. The check was moved to argument parsing, where
it belongs, rather than at first use.

---

## 5. The raw tables

### 5.1 `v2-n12b` — twelve concurrent requests, `zabz-tech`, 13:53:04–13:53:33Z, limit 8

**Caller side** (`test/concurrency-sweep.mjs`, `--transport v2 --n 12`, through the gate at
`https://zabz-tech.tail93e6e6.ts.net/mesh/run`):

| # | ms | HTTP | exit | MESH-HOST | queue position | waited ms |
|---|---|---|---|---|---|---|
| 1 | 11,994 | 200 | 0 | ✓ | 0 | 0 |
| 2 | 11,856 | 200 | 0 | ✓ | 0 | 0 |
| 3 | 11,817 | 200 | 0 | ✓ | 0 | 0 |
| 4 | 10,951 | 200 | 0 | ✓ | 0 | 0 |
| 5 | 11,881 | 200 | 0 | ✓ | 0 | 0 |
| 6 | 12,674 | 200 | 0 | ✓ | 0 | 0 |
| 7 | 14,879 | 200 | 0 | ✓ | 0 | 0 |
| 8 | 20,243 | 200 | 0 | ✓ | **1** | 3,924 |
| 9 | 14,229 | 200 | 0 | ✓ | 0 | 0 |
| 10 | 20,758 | 200 | 0 | ✓ | **2** | 4,758 |
| 11 | 20,768 | 200 | 0 | ✓ | **4** | 4,815 |
| 12 | 20,992 | 200 | 0 | ✓ | **3** | 4,745 |

`requested 12 · answered 12 · reportedCorrectHost 12 · refused 0 · admittedImmediately 8 · queued 4 ·
maxQueuePosition 4 · wallMs min/mean/max 10,951 / 15,254 / 20,992 · level wall 21,222 ms`

Positions 3 and 4 belong to requests 12 and 11 respectively: **arrival order, not index order** — the
positions are a property of the queue and not of how a caller happened to number its requests.

**Target side** (`target.csv`, the target's own counters and process list; `headless` is
`--profile headless` processes on that machine):

| ts (UTC) | commit MiB | avail MB | pages-in/s | pagefile % | diskQ | CPU % of 32 | node procs | **headless** | loop p50/95/max |
|---|---|---|---|---|---|---|---|---|---|
| 13:53:04.537 | 14,153 | 52,993 | 0 | 0 | 0 | 0.3 | 2 | 0 | 2/15/17 |
| 13:53:05.592 | 14,164 | 52,990 | 0 | 0 | 0 | 17.5 | 2 | 0 | 2/15/17 |
| 13:53:08.678 | 14,162 | 52,983 | 0 | 0 | 0 | 1.9 | 2 | 0 | 2/15/17 |
| 13:53:09.702 | 14,160 | 52,985 | 0 | 0 | 0 | 10.6 | 2 | 0 | 2/15/17 |
| 13:53:12.782 | 14,720 | 52,653 | 4 | 0 | 0 | 26.5 | 9 | **7** | 2/15/17 |
| 13:53:13.810 | 14,889 | 52,533 | 0 | 0 | 0 | 22.2 | 9 | **7** | 2/15/17 |
| 13:53:16.880 | 16,259 | 51,233 | 2 | 0 | 0 | 22.2 | 10 | **7** | 2/15/17 |
| 13:53:17.909 | 16,764 | 50,831 | 4 | 0 | 0 | 20.9 | 16 | **8** | 2/15/17 |
| 13:53:20.978 | **17,090** | **50,552** | 2 | 0 | 0 | 0.6 | 17 | **8** | 2/15/17 |
| 13:53:22.027 | 16,665 | 50,884 | 2 | 0 | 0 | 7.9 | 12 | **8** | 2/15/17 |
| 13:53:25.110 | 15,625 | 51,796 | 6 | 0 | 0 | 17.5 | 8 | **5** | 2/15/17 |
| 13:53:26.133 | 15,422 | 51,895 | 4 | 0 | 0 | 12.5 | 7 | **4** | 2/15/17 |
| 13:53:29.219 | 15,655 | 51,739 | 1 | 0 | 0 | 0 | 10 | **4** | 2/15/17 |
| 13:53:30.265 | 15,570 | 51,802 | 1 | 0 | 0 | 10.5 | 9 | **4** | 2/15/17 |
| 13:53:33.343 | 14,189 | 52,955 | 0 | 0 | 0 | 11.9 | 2 | 0 | 2/15/16 |

(39 rows captured; the 25 not shown are the post-level tail and more baseline. Peak CPU 26.5 % is
8.5 logical CPUs; per-turn CPU from a 3 s instantaneous grid is a floor, not a mean.)

**The node's own log**, same window (verbatim, `~/.dsh/multi-window/logs/3099-20260917-093202.log`):

```
RUN local-... inFlight=6/8 queued=0 queuePosition=0 queueWaitedMs=0
RUN local-... inFlight=7/8 queued=0 queuePosition=0 queueWaitedMs=0
RUN local-... inFlight=8/8 queued=0 queuePosition=0 queueWaitedMs=0
QUEUE local-eyj414fj position=1 limit=8 queueDepth=1 inFlight=8
QUEUE local-nih6ucf7 position=2 limit=8 queueDepth=2 inFlight=8
QUEUE local-4ryscpe9 position=3 limit=8 queueDepth=3 inFlight=8
QUEUE local-vii50lvd position=4 limit=8 queueDepth=4 inFlight=8
DEQUEUE local-eyj414fj position=1 waitedMs=1800 limit=8
DEQUEUE local-nih6ucf7 position=1 waitedMs=2062 limit=8
DEQUEUE local-4ryscpe9 position=1 waitedMs=10486 limit=8
DEQUEUE local-vii50lvd position=1 waitedMs=10575 limit=8
```

and `mesh-http {"verdict":"ran", … "inFlightAfter":8,"queuedAfter":3,"meshHostLineSeen":true}` for
the first completions, stepping `inFlightAfter` 8 → 7 → 6 → 5 → 4 → 3 → 2 → 1 → 0. Every `END` line
reads `exit=0 timedOut=false spawnError=none`. The engine's own counters after the level:
`started=25 completed=25 failed=0 queued=8 queuePeak=4 maxInFlightSeen=8 maxQueueWaitMsSeen=10575`.

**`maxInFlightSeen = 8`.** The accounting and the operating system agree.

### 5.2 The prediction test, applied

`84` predicted, from its own fit, that an additional concurrent resident turn costs **403 MiB**
(CI 270–533) and that the first thing to degrade is the engine's loop-lag **maximum** (18 → 54 ms at 8
tool-heavy turns).

| quantity | `84`'s prediction | measured here (8 concurrent) | verdict |
|---|---|---|---|
| commit per turn | 403 MiB, CI 270–533 | peak Δ 2,930 MiB ÷ 8 = **366 MiB** | **inside the CI**, 9 % below the point estimate |
| available MBytes per turn | −410 MiB (cross-check) | peak Δ 2,436 MB ÷ 8 = **305 MB** | inside; a lower bound, see the caveat |
| pagefile % usage | 14.1 % and *does not move* | **0 % in all 39 rows** | does not move — same conclusion, different absolute (this node's pagefile state differs; `84` is a night earlier) |
| disk queue | max 1 | **0 in every loaded row** | flat |
| loop lag max | **18 → 54 ms** at 8 tool-heavy turns | **17 → 17 ms** | **did not move at all** |
| node processes per turn | 1.74 | peak 17 total ÷ 8 = **2.13**, i.e. +15 for 8 = **1.88/turn** | same shape |

**The caveat that makes this honest:** my prompt is a *tool-light* turn (a 4-second sleep and
`hostname`), not `84`'s tool-heavy one. So this measures the limit against a **resident** fleet, and it
does not test the tool-heavy worst case that `CPU_PER_TURN = 1.68` is drawn from. That is the
conservative direction — the limit of 8 is derived from the worst measured class and then measured
against the milder one — and it is why the same number is defensible for a mixed fleet.

**The level settled**: commit returned to 14,189 MiB, `headless` to 0, loop-lag max to 16 ms, within
13 s of the last child exiting. No cleanup was needed, which is the property `85-hygiene` asks for.

### 5.3 `v1-n4` — four concurrent ssh children, 13:49:32–13:49:49Z

One `ssh` per child, both streams to **files** (`70` §4.1: a Windows ssh client whose stdout is a pipe
does not exit), the remote program as `-EncodedCommand`.

| ts | commit MiB | avail MB | pages-in/s | diskQ | CPU % | node procs | **headless** | loop max |
|---|---|---|---|---|---|---|---|---|
| 13:49:32.610 | 13,646 | 53,265 | 0 | 0 | 9.2 | 2 | 0 | 18 |
| 13:49:36.692 | 13,783 | 53,130 | 0 | 0 | 0 | 2 | 0 | 16 |
| 13:49:40.773 | 15,165 | 52,086 | 2 | 0 | 19.4 | 6 | **4** | 16 |
| 13:49:44.902 | 15,657 | 51,691 | 13 | 0 | 21.2 | 10 | **4** | 16 |
| 13:49:49.005 | 13,721 | 53,207 | 0 | 0 | 6 | 2 | **0** | 17 |

Caller side: `requested 4 · answered 4 · reportedCorrectHost 4 · refused 0 · wallMs 9,701–10,919
(mean 10,214) · level wall 11,188 ms`. Δcommit over baseline **+2,011 MiB for 4 → 503 MiB/turn**
(and +1,519 → 380/turn one sample earlier): the same per-turn cost as v2, as it must be, because the
*work* is identical and only the transport differs. Loop-lag max **fell** 18 → 16 ms.

`v2-n1` (13:36Z, limit 8, one child): HTTP 200, exit 0, **9,389 ms**, `queue.position 0`. Its
`meshHostLines` is 0 — the prompt defect of §4.3, fixed afterwards, and not re-run.

### 5.4 The ssh ceiling, with no agent turns spent (13:55:29Z)

Twelve `ssh` sessions launched simultaneously from this laptop, each running
`Start-Sleep 6; count powershell processes; Start-Sleep 6`:

```
exitCodes = 0,0,0,0,0,0,0,0,0,0,0,0
wallSeconds = 15                       (12 × 12 s sequentially would be 144 s)
PEERS readings = 31,31,30,30,30,31,30,30,30,30,31,30
```

Every session saw ~30 sibling PowerShell processes, so all twelve were genuinely live at once. And on
the target:

```
#MaxStartups 10:30:100
#MaxSessions 10
#MaxAuthTries 6
```

**All three commented out — so sshd's compiled defaults are in force**: `MaxStartups 10:30:100` begins
dropping *unauthenticated* connections at random from the 11th (30 % probability, rising to 100 % at
the 100th). My twelve survived because key authentication is fast enough that the unauthenticated
queue never filled — but the margin is one connection and nothing in transport v1 knows the limit
exists. **This is the honest statement of v1's ceiling: it has no ceiling, and its limit is the
target's sshd, with a probabilistic failure mode that produces a 255 exit and no diagnostic.**

---

## 6. What the measurement decides

1. **The one-agent ceiling is gone, and the new ceiling is a number with arithmetic.** 8 on
   `zabz-tech`, from that machine's cores and commit, published with its terms and overridable by one
   environment variable.
2. **Nothing is refused.** Twelve requests, eight slots, twelve answers, in arrival order, with the
   positions visible in the responses and in the node's own log.
3. **The concurrency limit was observed, not assumed.** The target's process list counted 8 children
   at its peak and never 9; the node's own accounting reported `maxInFlightSeen = 8`.
4. **The calibration's prediction held**: 366 MiB/turn against a predicted 403 (CI 270–533), with the
   pagefile, the disk queue and the loop-lag maximum all unmoved.
5. **A busy node is no longer a reason to dispatch elsewhere.** The old dispatcher fell back to ssh
   when `runner.busy === true`; with a queue that would have moved a child to another machine for no
   reason, which is the duplicate `70` §4.2 exists to prevent. It now queues and records the position.

---

## 7. Which transport wins, for what

**The order is a decision, written in `bin/mesh-dispatch.mjs` and recorded in every run's `start`
line; it is not an accident of fallback.**

**Default: v2 — for a single child AND for a fleet.** The reasons, each with its evidence:

| | v2 (HTTP route) | v1 (ssh) |
|---|---|---|
| ceiling | **derived from the target's own capacity** (8 on `zabz-tech`), enforced where the work is | **none in the transport** — measured: 12 concurrent sessions all ran; the real limit is the target's sshd `MaxStartups 10:30:100`, and a drop is a 255 exit |
| over the ceiling | queues, in arrival order, position in the response | runs anyway; oversubscription is silent |
| failure modes | none measured; the child is a child of the engine, whose logon session already resolves the profile's bundles | the sshd reparse-point refusal (`70` §4.4, cost a night), the stdout-pipe hang (`70` §4.1), a client that holds the session open after the work is done (`70` §4.2), and a relayed flaky path to the Mac (`81` §2) |
| what it costs the caller | one signed POST through a **threaded** gate (one thread per connection, `phone-gate.py:2457`), so the gate is not a concurrency bottleneck | one `ssh` process per child on the caller, one sshd session + PowerShell + node + ~0.9 MCP node processes per child on the target |
| deploy cost | one engine restart per node | none |
| whether it says what it did | `queue.position`, `queue.waitedMs`, the limit, and the arithmetic behind it | nothing; a dropped connection is indistinguishable from a failed child |

**v1 wins, and only, when:**

1. **the node has no route, or has one with no secret** — measured today: `secratary`,
   `lakewooechsmini` and `zabz-tech-linux` all answer **404** on `/mesh/health`. They can only be
   dispatched to over ssh, and the dispatcher logs the fallback as its own phase with its reason;
2. **the caller deliberately wants a node oversubscribed past its measured ceiling** — the only way to
   put 55 children on the mesh *simultaneously* instead of in ~4 waves. This is now an explicit act
   (`-Transport v1` / `-PreferV1`) rather than a silent consequence, and it is the one thing to think
   hard about: on `secratary` (4 cores, limit 1) 11 children is an 11× oversubscription, and `84` §6.2
   already recorded that 8 there is 2×;
3. **the route cannot be reached at all** — a gate that is down, or a relayed path that is dropping.
   The two are distinguishable in the record (`404` versus a transport error), which is why the probe
   argument in `83` §3.2 still earns its keep.

**And explicitly NOT when the node is busy.** That was the v0.1.0 fallback, and with a queue it is
wrong: busy now means *"you have a position"*.

**What would settle the fleet question that this measurement cannot:** a **matched pair** — the same N
on the same node over both transports, back to back. That is the one comparison I could not afford
(§10.1), and it is what would let the doc say whether v2's admission costs anything against v1's raw
spawn rate at equal concurrency. Today the honest statement is: **at N = 12 v2 achieved 8 concurrent
plus a queue, v1 achieved 12 concurrent (measured at N = 4 for real children; at N = 12 for ssh
sessions without agent turns), and the per-turn cost of the work itself is the same ~370–500 MiB
either way.**

---

## 8. Two measured identity defects, found and fixed in `lib/node-identity.js`

**(1) A degraded tailnet read was cached for the life of the process.** On ZABZ-YOGA the engine
(pid 4880) started at **08:51:07** and `tailscale-ipn` started at **08:51:59** — 52 seconds later. The
boot read saw `Self.DNSName: ""`, `readTailnet()` *succeeded*, and the memoised value was never
re-read, so that engine reported `node: "zabz-yoga"`, `fqdn: ""` for its whole life. **A fresh process
on the same machine, reading the same file, returned `zabz-yoga-1.tail93e6e6.ts.net` at 13:06Z.** A
good read is still cached for the process (a tailnet name does not change under a running engine); a
**degraded one is now retried**, rate-limited to once per 15 s, so a boot-time gap heals instead of
becoming the node's name.

**(2) The reported source named a field that had not supplied the value.** `node` fell back to
`Self.HostName` while `nodeSource` still said `tailscale status --json Self.DNSName`. `nodeSource` is
now one of exactly three literals and is the one that produced `node`; `fqdn` is `null` when absent
rather than `""`; the contract invariant `node === fqdn.split(".")[0]` is enforced in one place
(`normalizeTailnet`) rather than trusted from the reader; and `identityDegraded` + `identityReason`
let a dispatcher decline to place work on a name the node cannot corroborate.

**And what is deliberately NOT done: the name is never guessed.** `tailscale status --json` also
carries `MagicDNSSuffix` (`tail93e6e6.ts.net`) and `Self.HostName` (`zabz-yoga`), so
`"<HostName>.<MagicDNSSuffix>"` looks like a free repair. It is wrong on this fleet: that machine's
real label is **`zabz-yoga-1`**. Constructing the name would produce a plausible, well-formed and
incorrect identity — the hazard `71` §2.6 records for `-Exclude "zabz-yoga"`. A name that cannot be
read is reported as absent, and there is a test that asserts the guess is not made.

**Both fixes take effect on the affected engine's next restart.** `zabz-tech`'s engine was restarted
for this stream and reports `identityDegraded: false` with the full fqdn. **The laptop's engine was
NOT restarted** (pid 4880 serves the owner's live work), so *its running route still reports
`node: "zabz-yoga"` and `fqdn: ""` until the owner's next restart.* That is a live, unfixed defect on
one machine, stated rather than hidden.

---

## 9. What it cost, what was left behind, and what was checked

**Turns: 29 of a 30 budget.** `v2-n1` 1 + `v2-n12` 12 + `v1-n4` 4 + `v2-n12b` 12. The target's own
counter independently confirms the HTTP half: **`started=25 completed=25 failed=0`**, i.e. exactly the
25 v2 children I claim (1 + 12 + 12); the 4 ssh children are not children of the engine and correctly
do not appear there. **No ZABZ-YOGA engine was touched.**

**One engine restart, on `zabz-tech` only**, and the readiness gate was satisfied immediately before
it: `established_on_3099=0`, the route answering `version=0.1.0`, nothing of the owner's running
(`agents.loopsRunning 0`, `sessionsLive 0`, and the only node processes the engine, the gate, an
alpine listener and another stream's session-sync job). Old pid 26140 → new pid 24556, same
hand-started command line, and 533 session files on that machine.

**Left behind, on `zabz-tech`:** the shipped package (junction already existed), the sampler CSV/err
files under `%TEMP%`, and the route's own artifacts under `~/.dsh/mesh/http/` — the node's record of
what it was asked (`71` §2.3). Nothing else. **Left behind on ZABZ-YOGA:** nothing outside this
package, `docs/mesh/93-`, and the four `83` corrections the manager asked for.

**Stray check, at the end:**

| where | what was looked for | found |
|---|---|---|
| `zabz-tech` | `--profile headless` children alive | **0** |
| `zabz-tech` | sampler processes alive | **0** |
| `zabz-tech` | node/python processes | 3, all pre-existing: the engine (24556), the gate (27472), the alpine listener (24984) |
| `zabz-tech` | route state | `limit=8 busy=false inFlight=0 queued=0`, `freeMiB 53,204` |
| ZABZ-YOGA | my driver / ssh children alive | none — the only three `ssh` processes belong to pre-existing tunnels (`secratary-ts`, started 08:52–09:12, not started by this stream) |
| ZABZ-YOGA | the target's secret copied here for signing | **deleted** (`%TEMP%\mesh-tech-secret.env` and its capture file removed; nothing was written under `C:\ProgramData`) |

**Provenance of every claim.** Counters: the target's `Get-Counter` set and its own process list via
`Win32_Process`, both sampled by `test/sweep-sampler.ps1` with each row stamped **after** its reads
(`84` §1.4.1's rule). Loop lag: the target engine's own `GET /healthz`, cookie minted from the
engine's launch token the way `phone-gate.py` mints it. Concurrency: the target's `--profile headless`
process count **and** the node's own `inFlight`/`QUEUE`/`DEQUEUE` log lines and `maxInFlightSeen`
counter — two independent sources, agreeing. Limits: `deriveConcurrencyLimit()` output, quoted
verbatim. Identity: `/mesh/health` bodies plus `tailscale status --json` and process start times.

---

## 10. What I could not verify, stated as refusals

1. **A matched pair at equal N.** v2 was measured at N = 12 and N = 1; v1 at N = 4 for real children
   and N = 12 for ssh sessions without agent turns. **The transports were never compared at the same N
   with the same work**, so no claim is made that either is faster per child. The 30-turn budget was
   the binding constraint: a matched pair at N = 12 would have cost 24 of the 29 turns spent, leaving
   nothing for the calibration test at the derived limit. *What would answer it:* two more levels,
   N = 8 each way, ~16 turns and ~3 minutes on an idle node.
2. **N = 2, 4 and 8 on v2, and N = 1, 8, 12 on v1, for real children.** Not run. The per-turn cost
   curve for those points is `84`'s, on the same node, 10 hours earlier, and this stream tested the
   point that mattered — the limit — rather than re-deriving the curve.
3. **The tool-heavy worst case at the limit.** My fleet ran a resident prompt; `84`'s tool-heavy
   level degraded loop lag at 8. **A tool-heavy fleet of 8 on `zabz-tech` is not claimed safe** — it
   is the case the constants are drawn from, and it is the one that should be measured next.
4. **`secratary`, `lakewooechsmini`, `zabz-tech-linux` under v2 load.** None has a route (all three
   answer 404), so their limits in §2.2 are **arithmetic, not measurement**, and are labelled as such.
   The authority is the node where the derivation matters most (4 cores → limit 1) and the one node
   that cannot be tested without deploying a route and restarting its engine.
5. **`zabz-tech-linux` has a Node runtime after all.** `62` §3.1 recorded no Node runtime there; at
   13:56Z `which node` answered **`/usr/local/bin/node`** on 12 logical CPUs with 4,675 MiB of commit
   headroom. That is another stream's document to correct and it may change the placement arithmetic.
   Not investigated further here.
6. **The Mac's memory term.** macOS has no `/proc/meminfo`, so `availableMiB` there is free physical
   (236 MiB) — which yields a limit of **1** by binding on memory. Whether free physical is the right
   substitute on macOS (`vm_stat` counts reclaimed-anytime inactive pages separately) is **not
   measured**, and it is the only node where the memory term decides anything.
7. **`refuseWhenFull` against a live node.** The gate is code and unit tests; producing it live would
   require the configuration the whole change exists to move away from.
8. **The queue under a real 55-child flow.** The deepest queue measured is 4. A 55-child burst on a
   14-slot mesh is the owner's actual workflow and it has not been run; what is measured is that the
   queue is FIFO, visible, and admitted the moment a slot frees.
