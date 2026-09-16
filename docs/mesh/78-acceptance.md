# 78 — The mesh acceptance harness

**Owner:** stream S7 (after S1–S6). **Files:** `scripts/mesh-e2e.ps1`, this document.
**Contract:** `docs/mesh/71-mesh-program.md` §4, verbatim; interfaces §2.
**Script written:** 2026-09-16, *before* most of the components existed, on purpose — a test
written after the thing it tests can always be adjusted until it passes, and then it has
measured nothing.

---

## 1. How to run it

```powershell
cd C:\Users\ezabz\code\harness-config
pwsh -NoProfile -File scripts\mesh-e2e.ps1
```

Useful variants:

```powershell
pwsh -File scripts\mesh-e2e.ps1 -Nodes zabz-yoga-1,zabz-tech      # a subset (accepts the ssh alias too: linux-pc-ts)
pwsh -File scripts\mesh-e2e.ps1 -SkipHermetic                     # live node steps only, no local broker+stub mesh
pwsh -File scripts\mesh-e2e.ps1 -Json                             # the full report on stdout
pwsh -File scripts\mesh-e2e.ps1 -Strict                           # exit non-zero on SKIP as well as FAIL
pwsh -File scripts\mesh-e2e.ps1 -BrokerUrl http://host:3091        # name the broker instead of discovering it
```

**Exit codes.** `0` = every step PASSed or SKIPped; `1` = at least one step FAILed; `2` = a SKIP
occurred *and* `-Strict` was given. §4 requires non-zero on FAIL and says nothing about SKIP, so
SKIP alone is exit 0 — but the run prints **INCOMPLETE: a SKIP is not a pass** so nobody reads a
green-looking exit as a finished mesh.

**Every run leaves evidence** in `~/.dsh/mesh/acceptance/<runId>/`: `report.json` (every step,
every node reading, every sub-case) plus the stub-gate and broker logs of the hermetic meshes.
Nothing is written inside the repository.

**It is safe to run while other streams work.** It restarts no engine, edits no repo file, and
kills only processes it started itself (stub gates, its own broker, its own ssh tunnel). The live
broker is asked exactly one question and the lease is released immediately.

---

## 2. What each step means, and what a real failure looks like

The six steps are §4's six checks, in §4's order, plus three `b` sub-steps that test the half of a
check that can be tested without a dispatcher. A `b` sub-step never claims the check it belongs to.

### The one rule that decides FAIL vs SKIP

> **Does the capability exist anywhere in the fleet yet?** If **no**, the step SKIPs and says
> exactly what would have to exist. If **yes**, then every gated node must have it, and a node
> that lacks it is a **FAIL**.

This is written down once, in the script, so it cannot drift. It is what stops a half-built mesh
from reading as either a disaster or a success.

### Step 1 — `S1` capacity is real (§4.1)

For each of the five nodes: fetch `https://<fqdn>/mesh/capacity`, check it against §2.1, then
check its numbers against a **direct measurement of the same OS counter taken at the same moment**
— `os.freemem()`/`os.totalmem()` on Windows, `/proc/meminfo` `MemAvailable` on Linux, via ssh for
remote nodes and directly for this laptop.

* **A real failure** looks like: `HTTP 200` but `mem.totalMiB` disagrees with the direct total
  (total memory is static, so any difference is a bug, not drift); or `mem.freeMiB` outside the
  tolerance; or a document the broker's own validator would reject — which is the case for
  `mem.freeMiB: null`, and it is not pedantry: `packages/mesh-broker/lib/capacity.js`
  `validateCapacity()` requires a number, so such a node is **invisible to placement** no matter
  what its `accepts` block claims.
* **A SKIP** looks like: nothing published on `:443` at all, so the node is not yet a gated node —
  or a well-formed document on a platform this harness has no independent reader for.

**The tolerance is measured, not chosen.** Six interleaved samples on ZABZ-YOGA at 2026-09-16T23:2xZ
gave `|gate − midpoint|` of 6, 3, 18, 4, 24, 6 MiB — a maximum of 24 MiB. The gate and the direct
reader read the *same* OS counter, so all of that difference is memory that moved between two
instants. The tolerance is therefore

```
max(256 MiB, 1% of totalMiB)
```

— about 10× the largest observed delta, with the 1%-of-total term for a bigger machine churning
more bytes per second. Both terms are far below the size of the mistakes this check exists to
catch (a stale reading, or `total` where `free` belongs, is out by thousands of MiB).

That second term earned its place: on 2026-09-16T23:31Z `zabz-tech`'s free memory drifted
**183 MiB** during the read while the 32 GB laptop's drifted 22 MiB. A flat 256 MiB floor would
have produced a false FAIL on the busiest node in the fleet.

### Step 2 — `S2` placement decides (§4.2)

Five sub-cases:

| sub-case | how | what would make it FAIL |
|---|---|---|
| `live broker names a node` | the deployed broker is asked for a 6-child fleet | no node named; `rationale` without the slot arithmetic; or the broker reporting a task other than the one sent |
| `live lease released via /done` | `POST /done` releases it | a lease left on a real node — which perturbs every other stream's view of it |
| `names a node + slot arithmetic` | hermetic mesh, two 10-slot nodes | the `rationale` does not quote the gate's own measured `freeMiB` |
| `force one node to zero` | hermetic mesh, alpha 0 slots / beta 10 | the broker names the node with no room |
| `all nodes low → position > 0` | hermetic mesh, both at 0 slots | an error, or `position: 0` — §2.2 says a placement exists for every request |

The hermetic half is **not** a convenience. §4.2 says *"that node's capacity forced to 0"* and
§4.6 says *"a mesh with 5 slots"*; neither is something you can do to a live office desktop. The
stub gates come from S5 (`packages/mesh-broker/lib/stub-gate.js`), which built them for exactly
this. It also keeps §4.6's 30 leases off the live broker, where they would make real nodes look
busy for 15 minutes and mislead the other streams.

### Step 3 — `S3` work lands there (§4.3)

Needs a real 6-child fleet whose `MESH-HOST:` lines are matched against the node the broker named.
**This harness does not dispatch a fleet by itself** — that spends money and occupies other
people's machines, which is a decision rather than a default. `S3b` proves the part of §4.3 the
broker owes and which can be proven without dispatching: with two nodes free, two 6-child fleets
land on two *distinct* nodes.

### Step 4 — `S4` the client stays flat (§4.4)

Commit before/after (Windows `\Memory\Committed Bytes`) within ±1 GiB, and no new
`agentLoopsRunning` on the laptop's `/healthz` while the children run. Needs a dispatched fleet, so
it SKIPs without one. The before/after machinery is already in the script and is reported on every
run, so the moment a fleet can be dispatched this step is one flag away from being real. Baseline
noise measured across four runs of the harness itself: commit moved −0.40 to +0.35 GiB and
`agentLoopsRunning` moved 0 ± 1 — comfortably inside the tolerance, which is why ±1 GiB is the
right bar rather than a tighter one.

### Step 5 — `S5` a node can die (§4.5)

**§4.5 as written conflicts with this harness's own rules, and the conflict is the manager's to
resolve.** "Kill the chosen node's gate mid-run" means killing a gate *another stream deployed and
is running* on a node S7 does not own, while S7's brief says *never kill a process that is not a
gate you started*. Two sanctioned ways out: accept `S5b`, or have the manager authorise one named
pid on one named node. Until then the kill half is deliberately not executed — a green result is
worth less than the rule that stops it.

`S5b` tests the broker's half of §4.5, which is testable today and is the half §2.2 actually
specifies: (i) when a node's gate dies, the broker stops choosing that node and the next placement
succeeds elsewhere with **no manual repair**; (ii) an abandoned lease is **reclaimed at the
broker's own TTL** — the dead-dispatcher case, proved by never sending `POST /done` and watching
`leases.live` return to 0.

### Step 6 — `S6` queue, never amputate (§4.6)

A hermetic mesh with **exactly 5 slots**, then 30 genuinely concurrent `POST /place` calls.
Expected shape: 30 × HTTP 200, positions `0,0,0,0,0,5,6,…,29` — 5 running and 25 queued. Note the
script *proves* the mesh has 5 slots (by asking the broker to compute them) **before** trusting
the result; a stub with an implicit `governor.inUse` would quietly be a 3-slot mesh and the test
would pass while measuring the wrong thing.

---

## 3. Rules this harness obeys, and why each one is in the code

* **Proxy OFF on every HTTP call** (`HttpClientHandler.UseProxy = $false`). Measured: this laptop
  sets a proxy AutoConfigURL (a `.pac` file) and a proxy is fully capable of manufacturing a 502
  that has nothing to do with the node.
* **A timeout on every request**, and every HTTP call is retried three times on a *transport*
  failure (0/502/503/504). Measured 2026-09-16T23:18Z: `zabz-tech`'s published `/mesh/capacity`
  answered **502 once** and then **200 five times in a row** inside three minutes with no
  deployment change. A single 502 is evidence of nothing. A **404 is not retried** — it is a
  deterministic answer, not a blip.
* **No engine is restarted and no foreign process is killed.** Every `Stop-Process` in the script
  is applied to a PID it captured from its own `Start-Process`. §0 of the program is why: a mounted
  bundle cannot hot-load and an engine restart ends live sessions, and the owner's session on this
  laptop is live.
* **Every number carries a source and a date**, and the source *revision* is recorded too: each run
  fingerprints `packages/mesh-broker` (SHA-256 over its `.js`/`.mjs`/`.json`, plus the git HEAD)
  **at the start and at the end**, and warns if it moved mid-run.
* **`SKIP` is honest only when the dependency genuinely does not exist**, and every SKIP says
  exactly what would have to exist for it to run.

---

## 4. Defects this harness found in itself, and the guards that now prevent them

Three of these produced a **green run that was wrong**, which is the failure mode this document
exists to make impossible to repeat. A fourth was introduced *by the fix for the others* and
caught only because the final shipped script was actually executed.

**1. Every POST sent an empty body.** `Invoke-Json` had a local `$body = ''` — and PowerShell
variable names are case-insensitive, so that *was* the `-Body` parameter. The broker's
never-refuse rule turned each dropped "6-child fleet" into a 1-child one-shot, and four sub-cases
PASSED while testing a task nobody asked for.
*Guard:* the local was renamed, **and** every placement assertion now checks the task the broker
**echoes back** (`kind`/`children` in the response, §2.2). A dropped body is now a loud FAIL
instead of a silent change of subject.

**2. A null dereference masqueraded as a data problem.** `$nz.doc.nodes[0]` was read without
checking that the read had succeeded, so a failed `GET /nodes?fresh=1` was reported as *"the test
mesh has −1 slot(s)"* — sending the reader after the wrong problem entirely.
*Guard:* every dereference is guarded, a failed pre-condition read reports the read's actual
error, and `Start-HermeticMesh` no longer considers a mesh ready until it can answer
`GET /nodes?fresh=1` — `/healthz` only proves the listener is up.

**3. A FAIL carried an empty error.** The broker answered `/nodes` with HTTP 500 and
`{"error":"effective is not defined"}`; the harness printed only `HTTP 500: `.
*Guard:* a non-200 now carries an excerpt of the server's own body, so a FAIL names its cause.

**4. A mixed result was unexplained.** The hermetic mesh runs `packages/mesh-broker` straight from
the working tree, so a stream editing it mid-run means different sub-cases test different
revisions. Measured: run `20260916T233552Z` failed two sub-cases with `effective is not defined` at
23:36:41 and passed two others, because `broker.js` was rewritten at 23:36:49.
*Guard:* the source fingerprint above, captured at both ends, with a printed warning. A mixed
PASS/FAIL among hermetic sub-cases must now be read as "the tree moved" until a re-run on a still
tree says otherwise.

**5. A fix that broke what it was fixing.** A stub gate once failed to report its URL, and the
"obvious" fix — replacing `Get-Content -Raw` with `[System.IO.File]::ReadAllText` — made the
hermetic mesh fail **deterministically**, because `ReadAllText` threw `MethodInvocationException`
against every one of six files held by a `Start-Process -RedirectStandardOutput` child, while
`Get-Content -Raw` returned all six. Measured, 3 rounds × 2 gates.
*Guard:* the reader is `Get-Content -Raw` with a retry loop (and the measurement is recorded in the
function's comment), a stub gate that fails to start now reports its exit code and stderr, and the
whole harness is re-run after every edit. This one is the argument for that last habit.

**6. The harness leaked its own processes — and my first diagnosis of it was half wrong.** Cleanup
ran only on the last line of the script. A background run whose stdout pipe failed kept running for
many minutes, and its stub gates were *legitimately alive* while it did; a sweep found six of my
processes listening and I killed them, which killed that run's children out from under it. One
(`mesh-stub-gate --node solo --slots 5`, step 6's) was a genuine leak that outlived its run and
survived a `finally` that had already printed its cleanup line.
*Guard, and deliberately structural rather than a better explanation:* every hermetic mesh is now
**registered** and stopped in a `finally`, plus a backstop that kills every process whose **parent
is this script** — ownership by parentage, which does not depend on having remembered to record a
PID anywhere. Verified: a clean-slate run now ends with **zero** leaked processes.
Two further lessons from the same five minutes. First, "the harness printed a cleanup line" is not
evidence that nothing leaked; enumerate the machine's own listeners. Second, I wrote `$pid` while
removing the leaks — a **read-only PowerShell automatic variable** — so the first cleanup attempt
killed nothing whatsoever, in the same session as lesson 1 above about automatic variables.

---

## 5. Baseline status — what the mesh actually is on 2026-09-16

Eleven runs were made between 23:25Z and 23:45Z (the first four were used to debug the harness
itself — see §4). The authoritative run is
**`20260916T234527Z`, started 2026-09-16T23:45:27Z from ZABZ-YOGA** (report at
`~/.dsh/mesh/acceptance/20260916T234527Z/report.json`), against §4 as committed at
`71-mesh-program.md` (git `071b65a`, broker source fingerprint `C6916EEC43CF9925`).

| step | status | what decided it |
|---|---|---|
| `S1` capacity is real | **FAIL** | 4 of 5 nodes answer a schema-1 object whose numbers agree with a direct measurement; **`LakewooechsMini` FAILs** |
| `S2` placement decides | **PASS** | 5 of 5 sub-cases |
| `S3` work lands there | SKIP | needs a dispatched fleet; `mesh-run.ps1` landed at 19:36:59 but the harness does not fire fleets by itself |
| `S3b` broker spreads across 2 nodes | **PASS** | two 6-child fleets → `alpha` then `beta` |
| `S4` client stays flat | SKIP | no fleet dispatched, so no children to be flat during |
| `S5` a node can die | SKIP | the kill half conflicts with S7's own rules — see §2, step 5 |
| `S5b` broker half of §4.5 | **PASS** | 2 of 2: gate death → broker avoids the node; abandoned lease reclaimed in 3181 ms against a 3000 ms TTL |
| `S6` queue, never amputate | **PASS** | 30/30 HTTP 200 against exactly 5 slots; 25 positions > 0 (max 29); zero non-200 |

**4 PASS · 1 FAIL · 3 SKIP.** Exit code **1**, because one step failed.

**Reproduced.** Re-run at 23:49:22Z (`20260916T234922Z`) with the shipped script, after the cleanup
fix, it returned the *same* verdicts — 4 PASS / 1 FAIL / 3 SKIP — with the same single failure. Two
independent runs agreeing on every step is worth more than either one alone; only the free-memory
figures and the live mesh's free-slot counts differ between them.

**And then the mesh moved again, mid-session.** The last run, `20260916T235146Z` at 23:51:46Z,
returned **4 PASS / 0 FAIL / 4 SKIP, exit 0** — S1 flipped from FAIL to SKIP because
`LakewooechsMini`'s gate stopped answering on `:443` entirely, i.e. S1 was redeploying that node at
the moment of measurement. The other four nodes all PASSed with deltas of +80, +65, −5 and +6 MiB.
So within twenty minutes the same check moved FAIL → SKIP for the same node, for a reason that has
nothing to do with the harness. **Read `report.json`, or re-run — never quote this table.**

Per-node readings (step 1, live gates at 23:45Z):

| node | HTTP | gate `freeMiB` | direct | Δ | tolerance |
|---|---|---|---|---|---|
| `zabz-yoga-1` | 200 | 14911 | 14899 | +12 | 324 |
| `zabz-tech` | 200 | 51690 | 51654 | +36 | 652 |
| `secratary` | 200 | 16987 | 17024 | −37 | 256 |
| `zabz-tech-linux` | 200 | 10238 | 10234 | +4 | 256 |
| `LakewooechsMini` | 200 | `null` | — | — | — |

`mem.totalMiB` matched the direct total **exactly** on all four measurable nodes (32373, 65173,
23422, 11673).

**The mesh was close to saturated during this run.** The live broker reported
`zabz-tech` 15 free slots, `zabz-yoga-1` 12, `zabz-tech-linux` 4, `secratary` 1 — so only **one**
node was eligible to start a 6-child fleet (`eligible=1`), where the 23:37Z run had four. The
other streams were consuming the mesh while the harness measured it. That is not a fault; it is
why every number in this section carries a timestamp.

### The one live failure, precisely

`https://LakewooechsMini.tail93e6e6.ts.net/mesh/capacity` answers `200` with
`"mem": {"totalMiB": null, "freeMiB": null, "swapUsedPct": 84.3}` and
`"accepts": {"oneShot": true, "fleet": false, "reason": "free memory could not be measured on this
node…"}`.

The gate is honest — its `reason` says exactly what it cannot measure — but the consequence is not
cosmetic: `packages/mesh-broker/lib/capacity.js` `validateCapacity()` requires `mem.freeMiB` to be
a number, so **the broker cannot see this node at all**. It will be reported `unreachable` forever,
including for the one-shot runs its own `accepts` block says it would accept. S1's macOS memory
reader (`scripts/phone-gate.py` `_memory_bytes()`, the non-Windows branch) does not produce a
number on darwin. **Fix belongs to S1**: either measure it (`sysctl hw.memsize` for total;
`vm_stat`/`host_statistics64` for free) or get the broker to tolerate a `null` for `oneShot`.

### The harness caught two live regressions during this session

Recorded because it is the evidence that the harness works:

* **23:31:18Z** — step 1 FAILed `zabz-yoga-1`: the gate named itself `zabz-yoga` where §2.1 (revised
  that same evening) requires the DNS label `zabz-yoga-1`. By **23:37:46Z** the field read
  `zabz-yoga-1` and the node PASSed. The harness caught a live spec violation and then watched it
  get fixed.
* **23:32:55Z and 23:35:52Z** — the hermetic steps FAILed with
  `{"error":"effective is not defined"}` from `packages/mesh-broker/lib/broker.js`: `nodeView()`
  used a bare `effective` that only `evaluate()` defined. S5 fixed it at 23:36:49 by adding
  `const effective = effectiveSlots(arith)` inside `nodeView`. **S7 owns neither of those files and
  changed neither** — the harness only reported them.

---

## 6. What could NOT be verified, and exactly what would unblock it

| not verified | why | what would unblock it |
|---|---|---|
| §4.3 work lands there | needs a live 6-child dispatch | `pwsh -File scripts\mesh-run.ps1 -Prompt "<task printing MESH-HOST:>" -Children 6 -Json`, then match each `MESH-HOST:` line against the broker's choice |
| §4.4 the client stays flat | needs the same dispatch | the commit/`agentLoopsRunning` bracket is already implemented; it needs a fleet to bracket |
| §4.5 kill a gate mid-run | **rule conflict** — see §2 step 5 | the manager authorising one named pid on one named node, or accepting `S5b` |
| §4.1 the agreement half on macOS | the Mac's gate publishes no memory number, so there is nothing to compare | S1 fixing the darwin reader; then the darwin reader in `mesh-e2e.ps1` is exercised for the first time |
| whether §2.2's frozen scoring is still frozen | `broker.js` now implements `coreSlots`/`swapApplied`/"effective slots" and refers to an "AMENDMENT 4" that appears **nowhere** in `docs/mesh/` | the manager confirming whether §2.2 was amended. S7 did not encode the frozen formula as an assertion, because inventing an acceptance criterion beyond §4 is the same error as redefining success |
| the macOS direct-memory reader | never exercised (see above) | as above |

Two observations that are **not** §4 failures but that the manager should have:

1. **The broker's 1500 ms read timeout can mark a live node unreachable.** Measured live at
   23:31:18Z: the deployed broker reported `zabz-yoga: unreachable (timed out after 1500 ms (hard
   wall-clock deadline))` while this laptop's own gate was answering in 89–232 ms — the laptop was
   simply *busy* running this harness. Separately, `zabz-tech`'s first tailnet read took **7342 ms**
   (`attempts: 1`, so that is one request, not retry arithmetic). A busy node and a dead node are
   indistinguishable at 1500 ms, and the mesh's whole promise is routing to the emptiest node.
2. **§2.2's slot score is memory-only**, so it cannot tell a 4-core authority from a 22-core laptop.
   Measured: the live broker scored `secratary` (4 cores, "hopeless as a fleet worker" per its own
   roster note) at 24 slots and the 22-core laptop at 23, and in one run *chose* `secratary`. The
   owner's mandate was to route to "the most empty part of the mesh that will run fastest". This is
   §2.2's frozen arithmetic and S7 did not change it — but note that `broker.js` now carries a
   `coreSlots` term, which suggests S5 reached the same conclusion.

---

## 7. Provenance

* Every figure above came from a run of `scripts/mesh-e2e.ps1` on **ZABZ-YOGA**, or from a live
  HTTP/ssh reading taken during this session; each is stamped with its UTC time in the text or in
  `report.json`.
* Node roster and FQDNs: `~/.ssh/config` and `tailscale status`, read 2026-09-16.
* The gate's own measurement sources: `scripts/phone-gate.py` (read 2026-09-16, lines 690–1150).
* Broker scoring and validation: `packages/mesh-broker/lib/{scoring,capacity,broker,leases}.js`
  (read 2026-09-16).
* Spec: `docs/mesh/71-mesh-program.md` §2 and §4, at git `97dc2ea`.
* This document was written at **2026-09-16T23:4xZ**. The mesh is moving fast — five streams were
  writing at once during this session — so **re-run the harness** before quoting any status from §5.
  A number in this file is a measurement with a date, not a property of the system.
