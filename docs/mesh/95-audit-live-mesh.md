# 95 — Independent adversarial audit of the live mesh

**Auditor:** a delegated session, not the owner, not the author of any file under `docs/mesh/8x`.
**Owns:** this file only. Nothing else was edited; no engine was restarted; no process was killed.
**Measured from:** ZABZ-YOGA (home network), 2026-09-17 **13:04Z – 13:16Z**, over the tailnet and
over ssh to the office nodes. Every number below carries its command and its raw output.
**Contract audited against:** `81-overnight-program.md` §0 and §2, `71-mesh-program.md` §2 and §4,
`84-calibration.md`, `82-e2e-run.md`, `78-acceptance.md`.

**Method.** Assume the mesh does not work; try to falsify it. Several claims in those documents were
already overturned by later measurement, so a document is treated as a claim, never as evidence.
Where I could not verify something I say so. Where I contradict a document, the measurement is
quoted and the document is named.

**Scope limits I did not cross, on purpose:**

* **No fleet was dispatched.** That spends money and occupies another machine, and §0.3's six-child
  fleet is already recorded by O1 with raw output. I re-measured everything around it (the broker's
  decision, the transport's liveness, the dispatch records on disk) and re-dispatched nothing.
* **No engine was restarted, no gate was restarted, no process was killed.**
* I ran **exactly one** heavy thing: `scripts/mesh-e2e.ps1 -Strict` (§4.1 below), which starts and
  stops only its own stub gates. It was admitted through the host governor first
  (`admission_governor acquire --kind acceptance-harness` → `GRANTED slot 1`).

---

## 0. The verdict in one screen

| # | claim under audit | verdict | the measurement that decided it |
|---|---|---|---|
| 1 | every node answers a schema-1 capacity object matching an independent reading | **TRUE — 5/5**, and the `node == fqdn` first-label invariant holds on all five | §1.1, live 13:04:51–56Z, and `mesh-e2e.ps1` S1 PASS 5/5 at 13:11Z |
| 2 | the broker is a systemd service on the authority | **TRUE** | §2.1 — `active (running) since 03:54:31 UTC; 9h ago`, `enabled`, Main PID 2024394 |
| 3 | `GET /nodes?fresh=1` lists **every** node | **FALSE — it lists 4 of 5**; the Mac is not in the roster at all | §2.2 |
| 4 | `POST /place` for 6 children names a node with its arithmetic | **TRUE** | §2.3, 13:05:30Z, 13-line rationale with `floor((53764 − 7821)/160)` |
| 5 | the broker never refuses, even with every node excluded | **TRUE and stronger than claimed** — 200 with `position 4` | §2.4 |
| 6 | one engine per node, one `DSH_HOME` per node | **TRUE — 1 engine per node on all 5** | §3.1 |
| 7 | every node's `web` profile composes | **FALSE on the Mac Mini** — `--profile web --dump-config` exits **1** | §3.2 |
| 8 | every node's gate serves and every gate refuses a foreign device | **FALSE on `zabz-tech-linux`** — no allow-list file, so it is **fail-open**: a foreign device gets 200 and a signed-in session | §4.2 |
| 9 | the capacity probe, `mesh-health.ps1`, the acceptance steps can each fail | **partly false** — two instruments default to a node list written before two gated nodes existed, and one published field is a hardcoded literal | §5 |
| 10 | `journal.py check` is 0 errors | **TRUE** — `-- 0 error(s), 51 warning(s), 78 info`, exit 0 | §6.1 |
| 11 | every machine can `git pull --ff-only` again | **FALSE on the laptop** — `fatal: Not possible to fast-forward, aborting.`, exit **128** | §6.3 |
| 12 | **§0's definition of "fully built"** — `mesh-e2e.ps1 -Strict` exits 0 with zero SKIPs | **FALSE — exit 2, 5 PASS / 0 FAIL / 3 SKIP** | §4.1 |

**The single most important result: §0's own definition of done is not met by §0's own command.**
`pwsh -File scripts\mesh-e2e.ps1 -Strict` returns **exit 2** as I ran it, because S3, S4 and S5 SKIP.
This is not a new defect — `82-e2e-run.md` §0b shows exit 1 in all nine of its runs — but nobody has
stated the arithmetic plainly: the command §0 names cannot produce the result §0 requires, because
the three SKIPping steps need flags (`-DispatchFleet`, `-KillNodeHalf`) that §0 does not mention.

**And the mesh is running but not working.** The broker's last placement was logged at
`2026-09-17T04:12:42Z`; the newest dispatcher record on this laptop is
`~/.dsh/mesh/logs/2026-09-17T04-14-39-996Z.jsonl`, written 00:15 local. **Nine hours of idle.** The
processes are live; the workload is not. Every "live" claim below is about processes, not traffic.

---

## 1. Each node's capacity, against the node's own memory

### 1.1 The five capacity documents, verbatim (loopback via the gate where the gate is loopback-only)

```powershell
curl.exe -s --noproxy '*' --max-time 12 https://<node>.tail93e6e6.ts.net/mesh/capacity
```

```
zabz-yoga-1       200  4.42 s  {"schema":1,"node":"zabz-yoga-1","fqdn":"zabz-yoga-1.tail93e6e6.ts.net","at":"2026-09-17T13:04:51Z",
                              "cpu":{"logical":22,"physical":16,"load1":null},"mem":{"totalMiB":32373,"freeMiB":17253,"swapUsedPct":0.0},
                              "disk":{"workRoot":"C:/Users/ezabz/code","freeGiB":64.9},"agents":{"loopsRunning":7,"sessionsLive":12},
                              "governor":{"budgetSlots":24,"inUse":0,"queued":0},
                              "accepts":{"oneShot":true,"fleet":true,"maxChildren":12,"reason":null}}
zabz-tech         200  1.58 s  {"schema":1,"node":"zabz-tech","fqdn":"zabz-tech.tail93e6e6.ts.net","at":"2026-09-17T13:04:54Z",
                              "cpu":{"logical":32,"physical":24,"load1":null},"mem":{"totalMiB":65173,"freeMiB":53827,"swapUsedPct":0.0},
                              "disk":{"freeGiB":217.2},"agents":{"loopsRunning":0,"sessionsLive":0},
                              "governor":{"budgetSlots":24,"inUse":0,"queued":0},
                              "accepts":{"oneShot":true,"fleet":true,"maxChildren":12,"reason":null}}
zabz-tech-linux   200  0.30 s  {"schema":1,"node":"zabz-tech-linux",...,"cpu":{"logical":12,"physical":6,"load1":0.06},
                              "mem":{"totalMiB":11673,"freeMiB":10160,"swapUsedPct":15.2},"disk":{"freeGiB":20.9},"agents":null,
                              "governor":{"budgetSlots":24,...},"accepts":{...,"reason":"slot budget computed from memory; no governor
                              lease directory on this node, so inUse is reported as 0 and is not measured"}}
secratary         200  0.27 s  {"schema":1,"node":"secratary",...,"cpu":{"logical":4,"physical":4,"load1":0.62},
                              "mem":{"totalMiB":23422,"freeMiB":15718,"swapUsedPct":81.2},"disk":{"freeGiB":167.6},"agents":null,
                              "governor":{"budgetSlots":24,...},"accepts":{...,"reason":"...(as above)"}}
lakewooechsmini   200  0.27 s  {"schema":1,"node":"lakewooechsmini","fqdn":"lakewooechsmini.tail93e6e6.ts.net","at":"2026-09-17T13:04:56Z",
                              "cpu":{"logical":10,"physical":10,"load1":1.26},"mem":{"totalMiB":16384,"freeMiB":7067,"swapUsedPct":57.8},
                              "disk":{"workRoot":"/Users/lpt/code","freeGiB":46.1},"agents":null,
                              "governor":{"budgetSlots":24,"inUse":0,"queued":0},
                              "accepts":{"oneShot":true,"fleet":true,"maxChildren":12,"reason":null}}
```

*(Loopback on this laptop is `http://127.0.0.1:3086/mesh/capacity` — `tailscale serve` maps 443 →
3086, and `Get-NetTCPConnection` shows pid 19076 (`pythonw`) on 127.0.0.1:3086. A cold read of the
engine's own surface is 401; the capacity route is answered by the gate before the sign-in logic, so
it is the right door. `http://127.0.0.1:8443/...` does not exist — HTTP 000.)*

### 1.2 Do the numbers agree with an independent reading of that machine's own memory?

**`mesh-e2e.ps1` step S1 PASSes 5 of 5 at 13:11–13:12Z against a direct OS read**, so the schema and
the total-memory identity hold:

```
zabz-yoga-1       PASS HTTP 200  167 ms | freeMiB 15467 vs direct 15443 (delta 24 MiB, tolerance 324); total 32373 vs 32373
zabz-tech         PASS HTTP 200  223 ms | freeMiB 53706 vs direct 53509 (delta 197 MiB, tolerance 652); total 65173 vs 65173
secratary         PASS HTTP 200  233 ms | freeMiB 15664 vs direct 15663 (delta 1 MiB, tolerance 256);   total 23422 vs 23422
zabz-tech-linux   PASS HTTP 200  445 ms | freeMiB 10160 vs direct 10159 (delta 1 MiB, tolerance 256);   total 11673 vs 11673
LakewooechsMini   PASS HTTP 200  228 ms | freeMiB 6919 vs direct 6912 (delta 7 MiB, tolerance 256);     total 16384 vs 16384
```

I also checked the one number on `secratary` that a document makes a claim about, from the machine
itself rather than through the gate:

```
$ free -m                     →  Mem: 23421 total, 15627 available   Swap: 4095 total, 3326 used, 769 free
$ grep SwapTotal /proc/meminfo →  SwapTotal: 4194300 kB   SwapFree: 788208 kB
3326 / 4095 = 81.2 %          →  the gate's "swapUsedPct": 81.2 agrees exactly
```

**What that contradicts.** `packages/mesh-broker/nodes.json` still carries, in its `secratary` note,
*"Its swap is at 99.9% (measured repeatedly 2026-09-16), which halves its effective slots for
ranking."* The live `swapUsedPct` is **81.2 %**, and the broker's own `scoreTerms.swapApplied` is
**`false`** — so no penalty is being applied. The note is stale; the behaviour is correct. (It is a
comment, not code, so nothing is mis-scored — but it is exactly the kind of stale prose that a later
reader trusts instead of measuring.)

**One oddity I could not explain, stated rather than smoothed:** 3,326 MiB of that 4,095 MiB swap
file is in use, and the swap held by *live* processes is nowhere near it — the six largest
`VmSwap` values summed to about 46 MiB (`unattended-upgr` 14,468 kB, `networkd-dispat` 11,908 kB,
`python3` 7,348 kB, `code` 4,300 kB, `cloudflared` 1,912 kB, `systemd-resolve` 1,824 kB). So the
number is real at the kernel level but is not attributable to any process currently resident.
Whether that swap is reclaimable-by-`swapoff` is **not measured here**. It matters because 90 % is
the broker's penalty threshold and `secratary` is 8.8 points from it.

### 1.3 Does each node's `node` equal the first label of its `fqdn`?

**Yes, on all five**, from the §1.1 documents:

| node | `node` | `fqdn` first label | equal |
|---|---|---|---|
| `zabz-yoga-1` | `zabz-yoga-1` | `zabz-yoga-1` | ✅ |
| `zabz-tech` | `zabz-tech` | `zabz-tech` | ✅ |
| `zabz-tech-linux` | `zabz-tech-linux` | `zabz-tech-linux` | ✅ |
| `secratary` | `secratary` | `secratary` | ✅ |
| `lakewooechsmini` | `lakewooechsmini` | `lakewooechsmini` | ✅ |

`mesh-e2e.ps1` enforces this rather than assuming it (`scripts/mesh-e2e.ps1:449-452`:
`$label = ($doc.fqdn -split '\.')[0]; if ($doc.node -ne $label) { problems.Add(...) }`), so the check
that keeps it true is real.

**But the gate is the only thing that gets it right.** The v2 plugin's identity disagrees on the same
machine (§3.3) — and it is the one that will be pasted into a `MESH-HOST:` comparison.

### 1.4 What `accepts` actually says, and which of its fields is a measurement

`accepts.maxChildren` is **12 on every node in the fleet**, including the 4-core authority whose own
broker rationale prints `3 core slot(s) of 4 physical x 0.75`. It is a literal:

```
scripts/phone-gate.py:937   # The frozen example in 71 §2.1 shows `maxChildren: 12` beside `budgetSlots: 24`, so 12 is
scripts/phone-gate.py:939   MESH_MAX_CHILDREN = 12
scripts/phone-gate.py:1593      max_children = min(int(free_slots), MESH_MAX_CHILDREN)
```

`free_slots` on the gate's side is memory-derived (the gate's budget is floored at 4 and capped at
24 and is 24 on all five nodes), so `min(24, 12)` = 12 everywhere. **A documentation example became a
published per-node limit**, and the broker *consumes* it: the 999-child placement's rationale reads
`zabz-tech: accepts.maxChildren=12 < 999 child(ren)`. A field named as this node's measured
acceptance limit is a constant that no node computes.

`governor.budgetSlots` is a constant too: **24 on all five nodes** (§1.1). §2.1 is explicit that it
is advisory and must not be consumed — and the broker does not consume it — but a reader looking at
five nodes sees one number, which is the shape §2.1 itself was written to avoid.

---

## 2. The broker

### 2.1 Is it alive as a systemd service on the authority?

**Yes.**

```
$ systemctl status mesh-broker --no-pager
● mesh-broker.service - mesh broker - placement decisions for the DSH mesh (never refuses; queues instead)
     Loaded: loaded (/etc/systemd/system/mesh-broker.service; enabled; preset: enabled)
     Active: active (running) since Thu 2026-09-17 03:54:31 UTC; 9h ago
   Main PID: 2024394 (node)
     CGroup: /system.slice/mesh-broker.service
             └─2024394 /usr/bin/node /home/zabz/mesh-broker/bin/mesh-broker.mjs --host 127.0.0.1 --port 3091 --config /home/zabz/mesh-broker/nodes.json

$ ss -ltnp | grep 3091
LISTEN 0 511 127.0.0.1:3091 0.0.0.0:* users:(("node",pid=2024394,fd=18))
```

`enabled` + loopback-only bind + 9 h uptime with zero restarts. `86-authority.md` §1.5 is honest that
**the reboot itself was not performed**; what I add is that the uptime is now long enough that the
service has survived nothing but time — the reboot claim is still unproven.

Last work it did, from its own journal: `place -> zabz-tech position=0 tier=fits fleet children=6` at
`04:12:42Z`, released 0.3 s later. Nothing since.

### 2.2 Does `GET /nodes?fresh=1` list every node with a current reading?

**No. Four of five. The Mac Mini is absent from the roster entirely.**

```
$ curl -s --noproxy '*' http://127.0.0.1:3091/nodes?fresh=1      # over ssh on secratary
"reads": 56, "readFailures": 1, "nodes": [ zabz-tech, zabz-yoga-1, zabz-tech-linux, secratary ]
```

Every listed node has a current reading: `state: "ok"`, `ageSec` 0–1, latencies 21/46/67/620 ms. So
the four that are listed are healthy and fresh. The fifth is not listed:

```
$ cat /home/zabz/mesh-broker/nodes.json
  "_excluded_on_purpose": { "lakewooechsmini": "... NOT in the roster: it does not answer GET /mesh/capacity.
   MEASURED 2026-09-16 23:30Z ... So there is no capacity surface there and the broker cannot read it;
   adding it would only produce an `unreachable` row. Add it to `nodes` the day its gate answers ..." }
```

**The condition the roster states for adding it has been met.** Measured today, from this laptop, and
also by the broker's own read path (the same URL shape):

```
$ curl -s https://lakewooechsmini.tail93e6e6.ts.net/mesh/capacity
{"schema":1,"node":"lakewooechsmini",...,"mem":{"totalMiB":16384,"freeMiB":7067,...},"accepts":{"oneShot":true,"fleet":true,...}}   200
```

and `mesh-e2e.ps1` S1 reads it at 228 ms as one of its 5 of 5. So the Mac answers, its memory reader
was fixed, and it is a published, gated node that the broker cannot see. `82-e2e-run.md` §3.4 called
this "stream O5's call"; O5 shipped changes to the roster and shipped a *comment* instead of the row.
**This is a live, one-line, unblocked defect.**

### 2.3 Does `POST /place` for a 6-child fleet name a node with its arithmetic?

**Yes — 13 rationale lines, and every term is printed.**

```powershell
curl -s -X POST -H 'content-type: application/json' \
  -d '{"task":{"kind":"fleet","children":6,"worktreeGiB":2}}' http://127.0.0.1:3091/place   # via ssh, 13:05:30Z
```

```
"node":"zabz-tech","position":0,"score":18,"eligible":2,"tier":"fits"
[1]  chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller, 0 switched off in the roster; tier=fits
[2]  zabz-tech: 18 slot(s) of at most 24: floor((53764 MiB free - 7821 MiB reserve) / 160 MiB) = 287 slot(s), capped at
     maxSlots=24 -> 24, reserve 7821 MiB = max(2048 MiB, 12% of the node's own 65173 MiB) ... minus governor.inUse=0 -> 24
[3]  zabz-tech: 18 free slot(s) of 24 (slots 18 = 24 raw - see above, minus 0 broker lease(s) running here; 0 queued)
[4]  zabz-tech: disk 217.2 GiB free on C:/Users/ezabz/code vs 25 GiB required (20 GiB fleet floor + 2 GiB declared
     worktree + 0.5 GiB/child x 6 child(ren)) -> gate passes
[6]  zabz-tech: 24 memory slot(s), 18 core slot(s) of 24 physical x 0.75 -> effective 18
[9]  position 0: 18 free slot(s) - 6 child(ren) = 12 >= 0 on a reachable node -> start now
[12] lease ... expires ..., ttl 900 s, reclaimed by the broker at expiry so a dead dispatcher cannot wedge the mesh
```

The per-node reserve is derived, not the frozen literal: `7821 MiB = max(2048, 12% × 65173)`,
`3885` on the laptop, `2811` on `secratary`, `2048` (floor) on `zabz-tech-linux` — exactly the
amendment §2.2 records. And a 12-child request names the same node with `17 free - 12 = 5 >= 0 ->
start now`, so the placement moves with the task rather than echoing a cached answer.

### 2.4 Does it still NEVER refuse? Forced with every node excluded

**Yes, and it is stronger than the claim: the nodes appear as "excluded by the caller" while still
being ranked, and the answer is a 200 with a queue position.**

```
POST /place  {"task":{"kind":"fleet","children":6,"worktreeGiB":2,
              "exclude":["zabz-tech","zabz-yoga-1","zabz-tech-linux","secratary"]}}
→ HTTP 200    "node":"zabz-tech"  "position":4  "tier":"queued"  "eligible":4  "excluded":4
              "blockedBy":["caller-excluded"]
              [9]  no node can start this now (the caller excluded it); zabz-tech is the best candidate ... ->
                   placed there, QUEUED rather than refused (the broker never refuses a placement)
              [10] position 4: ... queued because caller-excluded; 4 accepted job(s) ahead on zabz-tech
              "queue":[{"lease":"mu5jlkey-...","state":"running","waitsMs":235730}, ... 4 entries]
```

I also gave it an impossible request, `{"kind":"fleet","children":999,"worktreeGiB":2}`: **HTTP 200,
`position 5`, `tier":"queued"`**, with the reason printed twice over — `disk 217.2 GiB free vs
521.5 GiB required -> gate FAILS`, `accepts.maxChildren=12 < 999 child(ren)`, `14 free slot(s) - 999
child(ren) = -985 < 0`. Six frames of "this cannot run" and one placement. **The never-refuse rule
holds under the two hardest cases I could construct.**

I released the four leases I created (`POST /done`, all `{"ok":true,"released":true}`). Two one-shot
leases that were already on the broker (`mu5jn1t6-17e16-h/i`, `waitsMs` 166530) were **not** mine and
were left alone. Note what that means: those leases were issued by something other than me and are
still "running" — the broker's queue was carrying work I cannot attribute, which is itself a small
argument for the leases being visible in a report somewhere.

---

## 3. The engines

### 3.1 How many engines run on each node

**One per node. No one-writer violation found.**

| node | engine processes (`bin.js` with a subcommand) | `DSH_HOME` | engine path |
|---|---|---|---|
| `zabz-yoga-1` | **1** — pid 4880, `bin.js web --port 3099 --no-open`, started **08:51:07 today** | `C:\Users\ezabz\.dsh` | npm-cache npx checkout |
| `zabz-tech` | **1** — pid 26140, `bin.js web --port 3099 --no-open` | `C:\Users\ezabz\.dsh` | same |
| `zabz-tech-linux` | **1** — pid 3572114, up 49,454 s, `bin.js web --port 3099 --no-open --trusted-host zabz-tech-linux.tail93e6e6.ts.net` | `/home/zabz/.dsh` | `/home/zabz/dsh-engine` |
| `secratary` | **1** — pid 2147621, up 23,761 s, `bin.js web --port 3089 --no-open --trusted-host secratary.tail93e6e6.ts.net` | `/home/zabz/.dsh` | `/home/zabz/dsh-engine` |
| `lakewooechsmini` | **1** — pid 12458, up **308,320 s (3.6 days)** | `/Users/lpt/.dsh` | `/Users/lpt/.dsh-install` |

`~/.dsh/profiles` on each node holds `web`, `headless` and `node_modules` (plus `mesh` on the
laptop) — one home each. **No node has two engines on one `DSH_HOME`.**

**One process worth naming, and it is a leak, not a violation.** `zabz-yoga-1` also carries pid 4284,
alive since **09:13:51 today**: `node <dsh>/lib/bin.js --profile headless --help`. A `--help` does
not need to live for four hours. It is not an engine (no port, no `DSH_HOME` writer) and it does not
violate the one-writer rule, but it is a hung child from a session that has since ended, and nobody
noticed because nothing enumerates leftovers.

### 3.2 Does each node's profile compose? `dsh --profile web --dump-config`

**No — it fails on the Mac Mini, and the failure is exact and one line old.**

```
zabz-yoga-1        $ node <dsh>/lib/bin.js --profile web --dump-config   →  exit 0
zabz-tech          ...                                                  →  exit 0
zabz-tech-linux    ...                                                  →  exit 0   (also headless: exit 0)
secratary          ...                                                  →  exit 0
lakewooechsmini    $ node /Users/lpt/.dsh-install/.../dsh/lib/bin.js --profile web --dump-config
Error: dsh: profile bundle "dsh-mesh-broker" declares no dsh.bundle in its package.json
    at loadProfileDirectory (file:///Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js:849:25)
    at prepareProfile  (file:///Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/profile-boot-Dk-7KqJc.js:208:18)
    at runCli         (file:///Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js:162:4)
Node.js v24.12.0                                                    →  exit 1
```

The cause, read from the machine:

```
$ cat /Users/lpt/.dsh/profiles/web/package.json
  "bundles": [ "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app",
               "dsh-mesh-broker",                       ← the row that breaks it
               "dsh-plugin-attention", ... "dsh-plugin-windows" ]

$ stat -f "%Sm %N" ~/.dsh/profiles/web/package.json
2026-09-17T08:48:28   ~/.dsh/profiles/web/package.json          ← written today, 4h25m ago

$ cat ~/.dsh/profiles/web/node_modules/dsh-mesh-broker/package.json
{ "name":"dsh-mesh-broker","version":"0.1.0","main":"lib/broker.js","type":"module", ... }   ← no "dsh" field at all
```

`packages/mesh-broker` is the **broker service**, not a Cordis plugin: its `package.json` has no
`dsh.bundle` marker, so the profile loader rejects the whole bundle list. The other four nodes do
**not** list it (`zabz-yoga-1` and `zabz-tech` have `dsh-mesh-broker` present in
`profiles/web/node_modules` but not in `bundles`; `zabz-tech-linux` has neither).

**Consequence, and why it is the finding I would act on first:** the Mac's engine (pid 12458) has
been up 3.6 days and booted *before* that row was written, so it is running on a profile that **can
no longer be booted**. Any restart of that node's engine — reboot, crash, a hygiene action, the next
`mesh-restart-at-0700` window — leaves it with no engine, and the failure will look like "the Mac
went away", not "a bundle row is wrong". The row was written at **08:48:28 today**, in the same
minute-range as a batch of `scripts/mesh-*.ps1` files modified at `08:47:45`
(`mesh-provider-install.ps1`, `mesh-restart-at-0700.ps1`, `mesh-hygiene.*`, `mesh-e2e.ps1`), i.e. by
the provider-mount work, and it landed on the one node whose `web` profile had not already been
reconciled.

`--profile headless` still exits 0 on the Mac, so the Mac remains dispatchable as a **worker**;
what is broken is its **resident engine**.

### 3.3 The engines that were restarted, and what they now serve

The laptop's engine pid changed from the `1784` that `81` §2's standing rule protects to **pid 4880
at 08:51:07 today** — so the restart window `71` §5 said the v2 transport needed **was taken**. That
is verifiable in the live route:

```
$ curl -s https://zabz-yoga-1.tail93e6e6.ts.net/mesh/health
{"ok":true,"service":"mesh-http","protocol":"mesh-http-v1","version":"0.1.0","route":"/mesh/run",
 "host":"zabz-yoga","node":"zabz-yoga","nodeSource":"tailscale status --json Self.DNSName","fqdn":"",
 "auth":{"scheme":"hmac-sha256-over(timestamp,nonce,body)","secretConfigured":true,
         "secretPath":"C:/ProgramData/dsh-mesh.env","skewSeconds":120,"secretBytes":64},
 "limits":{"oneRunAtATime":true,...}}                                                → HTTP 200

$ curl -s https://zabz-tech.tail93e6e6.ts.net/mesh/health
{"node":"zabz-tech","fqdn":"zabz-tech.tail93e6e6.ts.net", ... same shape ...}          → HTTP 200

zabz-tech-linux → HTTP 404      secratary → HTTP 404      lakewooechsmini → HTTP 404

$ curl -s -X POST -H 'content-type: application/json' -d '{}' https://zabz-yoga-1.../mesh/run
{"ok":false,"reason":"bad-timestamp-header","status":401,...,"authenticated":false}   → HTTP 401
```

So the v2 route is **live on 2 of 5 nodes** and correctly refuses an unauthenticated POST.

**The defect in it is already documented and is still live.** On the laptop the route reports
`"node":"zabz-yoga"` (`os.hostname()`) with `"fqdn":""`, while claiming
`nodeSource: "tailscale status --json Self.DNSName"`. I confirmed the source data is available:

```
$ tailscale status --json → Self.DNSName = 'zabz-yoga-1.tail93e6e6.ts.net.'   Self.HostName = 'zabz-yoga'
$ tailscale status --json → found at C:\Program Files\Tailscale\tailscale.exe   (machine PATH contains C:\Program Files\Tailscale\)
```

`docs/mesh/91-resident-dispatch-proof.md` §395–401 records exactly this and calls it "a stream that
owns that package"'s to fix. **I reproduce it at 13:13:45Z and it is unfixed**; `91` is also
**untracked** (`?? docs/mesh/91-resident-dispatch-proof.md` in `git status`), so the record of it
exists on one disk. This is the §2.1 naming trap live, in the field a `MESH-HOST:` comparison will
use: a child on this laptop reports `zabz-yoga`, the roster name is `zabz-yoga-1`, and
`82-e2e-run.md` §3.6 Case A is the failure that produces.

### 3.4 What the restart window did **not** fix

`82-e2e-run.md` §10.3 and `78-acceptance.md` §6 both list `secratary` and `zabz-tech-linux` as
unproven workers. `secratary`'s roster note ("no `headless` profile to load") is now **stale**:

```
$ ls -la ~/.dsh/profiles/          # on secratary
drwxrwxr-x  headless/    Sep 17 03:57        ← created at 03:57 today
drwxrwxr-x  node_modules/
drwxrwxr-x  web/         Sep 17 13:00
```

So the `dispatch.v1: null` in both `nodes.json` and the live `/nodes` payload ("UNMEASURED … there is
no `headless` profile to load") describes a state that stopped being true at 03:57Z. The broker is
ranking a node as *unmeasured* when it has been measurable for nine hours. I did **not** dispatch to
it to settle whether it works (that is money and another machine); what I can say is that the stated
reason for `null` is no longer a fact.

---

## 4. The gates, and whether the allow-list still refuses

### 4.1 Does every node's gate serve, and is it published?

**All five, yes.** `tailscale serve status` on the laptop and on `zabz-tech-linux` both read
`https://<node>.tail93e6e6.ts.net (tailnet only) |-- / proxy http://127.0.0.1:3086`; `ss -ltnp`
confirms tailscaled on `100.84.72.88:443` (authority) and `100.105.248.90:443` (linux), and the gate
listening on `127.0.0.1:3086` on each. Capacity answers 200 on all five (§1.1).

**Gate revisions differ across the fleet.** Same content on three nodes, not on the other two:

| node | the gate that is *running* | sha256 | note |
|---|---|---|---|
| `zabz-yoga-1` | `...\harness-config\scripts\phone-gate.py` (121,763 B, 00:18:13Z) | `4cf9c268…632a` | canonical |
| `zabz-tech` | same (121,763 B, 00:21:14Z) | `4cf9c268…632a` | canonical |
| `secratary` | `/home/zabz/harness-config/scripts/phone-gate.py` (121,763 B, 00:21:10Z) | `4cf9c268…632a` | canonical |
| `lakewooechsmini` | `/Users/lpt/.dsh-gate/scripts/phone-gate.py` (121,765 B, Sep 16 20:21 local) | `9e6a8650…9545` | **older revision** |
| `zabz-tech-linux` | `/home/zabz/dsh-mesh/repo/scripts/phone-gate.py` (**105,940 B**, Sep 16 19:30) | `4ec735cd…1661` | **a third revision** |

The linux node's running gate is **not** the copy in its `harness-config` checkout
(`/home/zabz/code/harness-config/scripts/phone-gate.py` is 40,206 B, Sep 15 — a *fourth* file, and a
stale checkout whose `HEAD` is `f14bfde`, while the laptop is at `ef02d55`).

### 4.2 Does the device allow-list still refuse a foreign device?

**It does on four nodes. On `zabz-tech-linux` there is no allow-list at all, and the gate is
fail-open — which is a live security hole, not a cosmetic one.**

The gate's rule (`scripts/phone-gate.py:2212-2217`):

```python
allow, restricted = allowed_devices()
if device and restricted and device not in allow:
    note(f"{method} {path} client=... -> REFUSED: not in {ALLOW_FILE.name}; ...")
    client.sendall(forbidden_response(device))
```

`ALLOW_FILE = Path(__file__).resolve().parent / "phone-gate-allow.txt"` — **beside the script that is
running**, not beside the repo copy. And `allowed_devices()` returns `(frozenset(), False)` when the
file is missing, logging `phone-gate: NO DEVICE RESTRICTION — ... does not exist`.

Tested by sending the header on loopback, against the employee's Mac address
(`100.126.146.121`, deliberately absent from every list) — **a node that HAS the allow-list file,
and the node whose file was installed late**:

```
zabz-yoga-1   curl -H "X-Forwarded-For: 100.126.146.121" http://127.0.0.1:3086/mesh/capacity
              → HTTP 403  "<h1 ...>This node does not sign in this device</h1><p>... came from
                            <code>100.126.146.121</code>.</p> ..."                     ✅ refused
              curl -H "X-Forwarded-For: 100.85.105.93"  http://127.0.0.1:3086/mesh/capacity
              → HTTP 200  (a listed device)                                            ✅ allowed
              curl -H "X-Forwarded-For: 100.126.146.121" http://127.0.0.1:3086/
              → HTTP 403                                                               ✅ refused

lakewooechsmini  same three probes → 403 / 200 / 403                                ✅ refused
                 $ ls -la /Users/lpt/.dsh-gate/scripts/phone-gate-allow.txt
                 -rw-r--r-- 3053 B  Sep 16 20:21      (list: yoga-1, iphone, tech, secratary, tech-linux)

zabz-tech-linux  curl -H "X-Forwarded-For: 100.126.146.121" http://127.0.0.1:3086/mesh/capacity
              → HTTP 200  {"schema":1,"node":"zabz-tech-linux", ...}                   ❌ NOT refused
              curl                          http://127.0.0.1:3086/mesh/capacity
              → HTTP 200
              curl -H "X-Forwarded-For: 100.126.146.121" http://127.0.0.1:3086/
              → HTTP 200  <!doctype html><html lang="en"><head><base href="/"><script>(()=>{
                            const pendingQueue=[] window.__ModuleLoader__={ ...        ❌ SIGNED IN
              $ ls -la /home/zabz/dsh-mesh/repo/scripts/phone-gate-allow.txt
              ls: cannot access '...': No such file or directory                        ← the cause
```

**What this means.** `tailscale serve` appends the caller's address to `X-Forwarded-For`, so the
header on a real tailnet request carries the real device. Because `restricted` is `False` on that
node, the branch is never taken and **every device on the tailnet is signed in automatically** on
`zabz-tech-linux` — including `100.126.146.121`, the employee's Mac, which every other node in the
fleet names in a comment and deliberately excludes. And it is not only the capacity route: `GET /`
returned the engine application HTML with a session, which is the "shell as the owner" exposure the
allow-list's own header describes (*"full engine control, a shell as the owner"*).

The device allow-list is therefore a control that **exists on 4 of 5 gated nodes**, and the node it
is missing on is the one added most recently (`73-linux-pc-node.md`) whose gate was deployed to a
non-repo directory. Its file lives in the *other* checkout (`/home/zabz/code/harness-config/scripts/`
— also without the file) and in neither place where the running gate would look.

*(I did not fix it. The header of the allow file says who is allowed to decide that, and this file
owns only itself.)*

---

## 5. The instruments — which of them can fail?

The question is not "does the check pass", it is "would this check go red if the thing it names were
broken". For each instrument I looked for the state in which it reports success while the thing it
names is false.

### 5.1 `scripts/mesh-health.ps1` — **can pass with a gated node unchecked**

```powershell
param(
    [string[]]$Nodes = @('zabz-yoga-1', 'zabz-tech', 'secratary'),   # ← 3 of the 5 gated nodes
```

Its own synopsis says *"One command that answers 'can I actually use each node from here, right
now?'"* and it exits 0 when nothing is `FAIL`. The default list predates `zabz-tech-linux` and the
Mac Mini becoming gated nodes, so **`pwsh -File scripts\mesh-health.ps1` reports healthy without ever
reading the two nodes that are newest — one of which (§4.2) is fail-open and one of which (§3.2)
cannot boot.** A green `mesh-health` is therefore not evidence about the fleet; it is evidence about
three specific nodes. This is the same class as the three checks found overnight: the check is sound,
its **domain** is silently narrower than the claim on its front page.

`-Nodes` takes an explicit list, so the fix is a default nobody will re-derive. The file's own
comment notes that `/healthz` 404/503-on-POSIX were added so mounting a health surface would not make
a Linux node look worse — the domain was widened for what to *accept* and never for *whom to ask*.

### 5.2 `scripts/mesh-capacity-probe.ps1` — **same defect, one node further along**

```powershell
# The nodes this program has deployed a gate on. ... `zabz-tech-linux` was added 2026-09-16 when
# stream S2 brought that node up — before that, a probe could pass while a third of the mesh's
# capacity was invisible to the broker.
$GatedNodes = @('zabz-yoga', 'zabz-tech', 'secratary', 'zabz-tech-linux')
```

By default the probe enumerates tailnet peers and keeps only those in `$GatedNodes`. **The Mac Mini
is not in that list**, so `pwsh -File scripts\mesh-capacity-probe.ps1` passes while the Mac's
capacity is never read — the exact failure the comment above it records as *already having happened
once* with `zabz-tech-linux`. `-All` targets every peer; the default does not. This is the "assume at
least one more exists" finding: the program fixed this mistake for one node and left it standing for
the next one.

### 5.3 `scripts/mesh-e2e.ps1` — the steps can fail, but the *contract* cannot be met

The six steps do fail when they should: `82-e2e-run.md` §0b shows S1, S2, S3, S4 and S5b all going
red at least once for real causes, and I re-ran it:

```
$ pwsh -NoProfile -File scripts\mesh-e2e.ps1 -Strict -Json        # 13:11:26Z
{"runId":"20260917T131126Z","host":"ZABZ-YOGA",
 "counts":{"pass":5,"fail":0,"skip":3},
 "steps":[ S1 PASS, S2 PASS, S3 SKIP, S3b PASS, S4 SKIP, S5 SKIP, S5b PASS, S6 PASS ]}
EXIT=2
```

`S1` is genuinely strong: it reads all five nodes, enforces `node == fqdn`'s first label
(`mesh-e2e.ps1:449-452`), reports both macOS meanings of "free"
(`freeMiB 6919 vs direct 6912 … 6912 MiB reclaimable (the counter the gate reads) vs 133 MiB as
Pages free alone`), and compares `mem.totalMiB` to a direct read. It caught a live spec violation on
this laptop once already. `S6` proves the 5-slot mesh *before* trusting the 30 placements. `S3b` and
`S5b` are hermetic and reproducible.

**The finding is about §0, not the script.** §0 says the mesh is DONE when `mesh-e2e.ps1 -Strict`
exits **0 with zero SKIPs**. The command §0 names does not pass `-DispatchFleet` or `-KillNodeHalf`,
so S3/S4/S5 SKIP unconditionally, so `-Strict` exits **2** — every time, on any mesh, forever. Even
with `-DispatchFleet`, `82-e2e-run.md` §5 and the step's own detail text state that no run has ever
been failed by killing a gate under a live child, so S5's own PASS condition is explicitly deferred
to a standalone script. **§0's success criterion is not reachable by §0's own command**, and the
documents never say so in one sentence.

### 5.4 The capacity contract — one field that cannot vary, and one that cannot see the load

* `accepts.maxChildren` is `12` on all five nodes (§1.4) — a literal, from a doc example.
* `governor.budgetSlots` is `24` on all five nodes (§1.4) — the advisory number §2.1 warns not to
  consume.
* `agents` is `null` on three of five and *resident-engine only* where it exists, and — measured in
  the source rather than in the prose — **it has no effect on any placement.** `loopsRunning` appears
  in the broker exactly twice:

  ```
  packages/mesh-broker/lib/broker.js:407   loopsRunning: finite(doc?.agents?.loopsRunning),
  packages/mesh-broker/lib/broker.js:698   lines.push(`${chosen.node}: load1 ${...} on ${...} logical cpu(s), ${chosen.loopsRunning ?? 'unknown'} agent loop(s) running`);
  ```

  and **nowhere in `packages/mesh-broker/lib/scoring.js`**. Line 407 reads it into the node view,
  line 698 prints it as a rationale sentence, and the slot arithmetic contains no `agents` term. So a
  node running 8 loops and one running 0 score identically: the number is *reported*, never
  *consumed*. That is the same shape `60-verification.md` §1.7 called "the arithmetic is decorative"
  — a published measurement that cannot move a decision. `84-calibration.md` §5.2 proved a dispatched
  fleet is invisible to the field; this is the stronger statement, that even a *visible* number here
  changes nothing.

### 5.5 `harness-verify.ps1` — present, not audited

`scripts/harness-verify.ps1` (19,821 B, mtime 08:47:45 today) exists and is part of the 08:47 batch.
I did not run it: it is not named in `81` §0's definition of done, not named in `71` §2/§4, and
nothing in the acceptance path invokes it. **"Cannot be checked as a mesh instrument because no mesh
claim depends on it"** — if it *is* load-bearing for something, that dependency is not written down
anywhere under `docs/mesh/`, which is itself the finding.

---

## 6. The journal, and the repository

### 6.1 `journal.py check` — 0 errors

```
$ python3 journal/tools/journal.py check          # on secratary, /home/zabz/code/harness-config
-- 0 error(s), 51 warning(s), 78 info
check_exit=0
```

Warnings are dangling refs and legacy-id headings (`WARN H83 (handoff) has an empty body`,
`WARN dangling ref D103 (cited by D104)`, `INFO entries/lessons/L264.md: heading carries the legacy
id L4`). **0 errors, and `check` exits 0 only on a real error** — so the record is structurally sound
on the machine that owns it.

### 6.2 The entry count is accounted for

```
$ python3 journal/tools/journal.py status
HANDOFF H396 · 2026-09-16 17:47 UTC · secratary · Insurance session closed out ...
ENTRIES handoff:304  lessons:587  pain:178  decisions:176  wins:155   (total 1400)
OPEN PAIN 142
$ find journal/entries -name '*.md' | wc -l        # on secratary
1616
```

304 + 587 + 178 + 176 + 155 = **1400 by kind**, against **1616 files** on disk. The difference is 216
and it is **not explained by this page** — the counts line and the file count are different metrics,
and nothing says so. `89-integration.md` §2 accounted for 1,576 at `7708e2d`; the tree has grown 40
files since. I could not reconcile 1400 against 1616 from the tools I was given, and I am recording
that rather than picking the flattering number.

**A stale claim in the always-read page, worth one line:** `journal/NOW.md` opens
`Updated: 2026-09-14 (late session, ZABZ-YOGA)` and says **"707 entries (23:38 UTC)"**. The live
count is 1400 by kind / 1616 files. `NOW.md` is the one file every session reads first, and its
"Updated" date is three days old.

### 6.3 Can this tree `git pull --ff-only`? **No — verified by running it**

The brief said the fork was resolved hours ago. It was, and it **re-diverged at 09:07 this morning**.

```
$ git fetch origin
$ git rev-list --left-right --count HEAD...origin/master
1	1
$ git merge-base --is-ancestor HEAD origin/master ; echo $?
1
$ git pull --ff-only
hint: Diverging branches can't be fast-forwarded, you need to either:
hint: 	git merge --no-ff
hint: or:
hint: 	git rebase
fatal: Not possible to fast-forward, aborting.
pull_exit=128
$ git log --oneline origin/master..HEAD   →  ef02d55 tools: pick up the gap-closing round's fixes
$ git log --oneline HEAD..origin/master   →  595c778 tools: the gap-closing round's fixes to the fleet clocks
$ git log -1 --format='%H %ad %an %s' --date=iso HEAD          → ef02d55  2026-09-17 09:07:48 -0400  Zabz
$ git log -1 --format='%H %ad %an %s' --date=iso origin/master → 595c778  2026-09-17 09:07:51 -0400  zabz68
$ git show --stat --oneline ef02d55   →  scripts/website-comms-push.py | 173 ++++++++++++  1 file changed, 167 insertions(+), 6 deletions(-)
$ git show --stat --oneline 595c778   →  scripts/website-comms-push.py | 173 ++++++++++++  1 file changed, 167 insertions(+), 6 deletions(-)
```

**The two commits are the same change, made three seconds apart by two different machines**, and the
content is already reconciled:

```
$ git diff --stat HEAD origin/master      →  (empty output)
$ git cherry -v origin/master HEAD        →  - ef02d55 tools: pick up the gap-closing round's fixes
```

The leading `-` in `git cherry` means the patch is already present upstream, and `git diff` between
the two tips is empty. **So the divergence is a duplicate commit with no content difference** — the
laptop autosynced and committed the same round of work that `zabz68` had already pushed three seconds
earlier. It is not data loss and it is not the id-collision blocker `89-integration.md` §4 documents
(that was a dirty working tree; this is a `behind 1` commit graph).

**The authority is fine and can fast-forward**, so this is a laptop-only condition:

```
secratary:  git rev-list --left-right --count HEAD...origin/master  →  0	1
            git merge-base --is-ancestor HEAD origin/master ; echo $?  →  0        # ff is possible
```

`git status` on the laptop is also carrying a large uncommitted working set — ten modified tracked
files including `packages/plugin-mesh-http/lib/*.js`, `profiles/web/cordis.patch.yml`, and dozens of
untracked files including `docs/mesh/91-resident-dispatch-proof.md` (the proof of the resident
dispatch claim, on one disk, uncommitted). **A `--ff-only` repair is available and cheap** (the trees
are identical, so a `merge --no-ff` of `origin/master` into `master`, or `git reset --hard
origin/master` — forbidden by §2 — is not even needed to preserve anything), **but §2 says commit
nothing**, and this file owns only itself. Recorded, not performed.

---

## 7. Three plain questions, answered with numbers

### (a) If the owner opened 10 windows and ran ~55 agents across the laptop and desktop right now, what would actually happen, step by step?

**First, the mesh would not be consulted for most of it — and that is the point.** A `subagent` call
inside a window is local to the engine that window belongs to; only `subagent_remote` (mounted since
the 08:51 boot, `91`), `-profile mesh` dispatches and `mesh-run` go through the broker. So step 1 is:
**10 windows open 10 resident sessions in two engines — 1 on the laptop (pid 4880) and 1 on the
desktop (pid 26140) — and if the agents are plain `subagent` calls, all 55 land on the machine that
owns the window and nothing consults the broker.** Only if they are `subagent_remote` does step 2
happen.

**Step 2, if they are remote: the broker places all 55 on `zabz-tech`, because it cannot see the
load.** Live at 13:05:30Z the rationale read, for a 6-child fleet, `zabz-tech: 24 memory slot(s), 18
core slot(s) of 24 physical x 0.75 -> effective 18` and `load1 not measured ... 0 agent loop(s)
running`. At 13:04:51Z the laptop was reporting `loopsRunning: 7, sessionsLive: 12`, and its own
broker score is 12 slots of 18. The score is `min(memorySlots, coreSlots)`; `memorySlots` is
**pinned at 24 on every node** because it caps at `freeMiB ≥ 3885 + 24×160 = 7,725 MiB` and every
node clears that by thousands (`84-calibration.md` §5.3, reproduced in §1.1/§2.3 here). So
placement is decided by `floor(physical cores × 0.75)` alone — desktop 18, laptop 12, authority 3,
linux 4 — plus the broker's own leases. **A node running 8 headless children scores identically to
an idle one.** The 55 agents would be split in that ratio, not by who is busy.

**Step 3, the laptop, with numbers.** `\Memory\Committed Bytes` = **23,710 MiB** against a commit
limit of **44,149 MiB** (12,994 MiB of RAM free, 32,373 MiB physical), measured here at 13:13Z. At
the measured cost of **403 MiB of commit per additional concurrent turn** (`84-calibration.md` §3,
95 % CI 270–530), 55 turns on the laptop alone = `55 × 403 = 22,165 MiB` more commit → **45,875 MiB
against a 44,149 MiB limit.** That is past the limit: allocation failures, and
`swapUsedPct = (45875 − 32373) / (44149 − 32373) = 114 %` — i.e. far beyond the 90 % that halves a
node's score. CPU is the other half: a turn costs **0.62 logical CPUs model-bound** and **1.68
tool-heavy** (§4.3), so 55 turns want **34–92 logical CPUs** against 22 available — a **1.5× to 4.2×
oversubscription** on the machine that also serves the owner's screen. The last measured comparable,
`84-calibration.md` §1.1: with **6 agent loops** on this laptop, commit went 27.11 → 29.92 → **34.72
GiB** in fifteen minutes and the admission governor's own budget hit its **floor of 4 slots** with
3,408 MiB of RAM free.

**Step 4, the desktop, with numbers.** 64 GiB physical, 53,764 MiB free at 13:05Z, commit limit 69,269
MiB, 0 loops running. The same 55 turns add 22,165 MiB of commit against an idle floor near 20,500
MiB → ~42.7 GiB of a 69.3 GiB limit, and 34–92 logical CPUs against 32 — a **1.1× to 2.9×
oversubscription**. `84-calibration.md` measured this exact machine flat and benign **through 8
concurrent turns** (commit 20,491 → 23,499 MiB, pagefile 14.1 % in all 83 samples, disk queue max 1)
with only loop-lag `max` moving, **18 → 54 ms**. 55 turns is 7× the highest measured point, which
`84-calibration.md` §6.3 names as unmeasured.

**So the honest answer is: the desktop absorbs it and gets 2–3× slower with visibly worse tail
latency; the laptop falls over.** And the mesh does nothing to prevent that, because the two facts it
would need — how loaded a node is, and how much a turn really costs — are respectively invisible
(`agents.loopsRunning` reads 0 while a dispatched fleet runs, `84` §5.2) and unmodelled (the score is
a core count). What would stop it is the owner's own tool, not the mesh: the admission governor,
which answers GRANTED/QUEUED from this host's free memory and caps at 24; measured here as
`budget: 14170 MiB free - 3885 MiB reserved = 10285 MiB usable / 160 MiB per slot = 64 slot(s),
capped at maxSlots=24`.

### (b) What is the single most likely thing to break in the next 24 hours, and what is the evidence?

**The Mac Mini's engine will not come back if it restarts, and a restart is the ordinary way that
node breaks.** Evidence, all from the machine, all reproducible in two seconds:

1. `node /Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web --dump-config`
   → **exit 1**, `Error: dsh: profile bundle "dsh-mesh-broker" declares no dsh.bundle in its
   package.json`.
2. `~/.dsh/profiles/web/package.json` lists `dsh-mesh-broker` in `dsh.profile.bundles`; its
   `mdtime` is **2026-09-17T08:48:28** — 4h25m before this audit.
3. The installed package at `~/.dsh/profiles/web/node_modules/dsh-mesh-broker/package.json` has **no
   `dsh` field** — it is the broker *service*, which the profile loader cannot mount. The other four
   nodes do not list it.
4. That node runs **exactly one** engine (pid 12458, up **308,320 s = 3.6 days**), so it booted
   before the row existed and is running a profile that can no longer boot. There is no second
   engine to fall back to and no supervision that would report it — the node would simply stop
   answering `/mesh/capacity` and the broker would file it `unreachable`.

**What would falsify this:** a restart of pid 12458 that succeeds. That is a five-minute test on a
machine no one is using, and it is the single cheapest high-value action on this list.

**Runner-up, because it needs no trigger at all:** the laptop cannot `git pull --ff-only`
(§6.3, `fatal: Not possible to fast-forward, aborting.`, exit 128), and the tree that carries the
journal, the mesh docs and the dispatch records is the one that cannot be updated. The repair is
content-free (`git diff HEAD origin/master` is empty), but until it happens every machine-local fix
is copied by hand — which is precisely the condition `87-harness-fork.md` was written to end.

**Third, already broken and therefore not "breaking":** `zabz-tech-linux`'s gate signs in every
device on the tailnet (§4.2). It is not a future risk, it is a present exposure, and the only thing
that changes is who notices.

### (c) What does this mesh do that the owner would NOT expect, for better or worse?

**Worse, in the order I would care about them:**

1. **An allow-list that exists on four of five nodes, missing exactly where a second person's machine
   is on the tailnet.** `GET /` on `zabz-tech-linux` returns the engine application with a session to
   a device every other node explicitly refuses (§4.2). The owner believes the allow-list is a fleet
   control; it is a per-directory file next to whichever `phone-gate.py` is running.
2. **Placement is blind to real load.** The score is `floor(physical cores × 0.75)` and nothing else:
   the memory term is pinned at its 24 cap on all five nodes, and `agents.loopsRunning` — which reads
   0 while 8 dispatched children consume 3 GiB and 41.5 % of a machine's CPUs (`84` §5.2) — is read
   into the broker at `broker.js:407`, printed at `broker.js:698`, and used by `scoring.js`
   **nowhere at all** (§5.4). The laptop was reporting `loopsRunning: 7`, `sessionsLive: 12` and 23.7
   GiB committed at 13:13Z while its own placement score stayed at 12 slots of 18. *"Route work to
   the most empty part of the mesh"* is, today, *"route work to the node with the most physical
   cores"*.
3. **A node that advertises capacity it cannot use.** `accepts.maxChildren` is a hardcoded `12`
   everywhere (`phone-gate.py:939`), so the 4-core authority tells a caller it can take 12 children
   while the broker's own rationale for that node says `3 core slot(s) of 4 physical x 0.75`. The
   number came from the JSON example in §2.1.
4. **A macOS node can out-score a Linux node with more genuinely free RAM.** The Mac reports
   `freeMiB: 7067` of 16 GiB where the *actually* free number is `133 MiB`; the gate's number is
   "reclaimable" on darwin and "available" on Windows/Linux, and the contract has no field that says
   which (§1.1, and `82` §1.1's honest note). The broker cannot tell the difference.
5. **The mesh's own v2 identity disagrees with its capacity identity on the same machine.** The gate
   says `node: "zabz-yoga-1"`; `/mesh/health` on the same laptop says `node: "zabz-yoga"` with
   `fqdn: ""` while claiming the source that would have produced `zabz-yoga-1` (§3.3). The one field
   a `MESH-HOST:` check will use is the wrong one.
6. **A nine-hour gap that reads as "live".** The broker's last placement is `04:12:42Z`; the newest
   dispatcher record is `04-14-39-996Z`. Running processes are not running work.

**Better, and genuinely so:**

7. **Never-refuse is real, not aspirational.** I forced it twice — every node caller-excluded
   (`position 4`, HTTP 200) and a 999-child fleet against a 12-child limit and a 521 GiB disk
   requirement (`position 5`, HTTP 200) — and both answers printed the arithmetic that refused them
   *and placed them anyway*. There is no code path I could find that returns a refusal.
8. **The rationale is auditable.** Thirteen lines per placement naming `freeMiB`, the per-node
   reserve and *why* it is that reserve (`derived` / `floor`), the core term and its basis, the disk
   floor per child, the transport's measured state, and the lease's own expiry. A caller can redo
   the arithmetic rather than trust it. That is rare and it is the reason this audit could be
   adversarial in an afternoon.
9. **A resident session really does dispatch work to another machine.** `/mesh/health` answers 200 on
   two nodes with HMAC configured (`secretConfigured: true`, 64-byte secret) and refuses an
   unauthenticated `POST /mesh/run` with `401 bad-timestamp-header` — and `91` records the child
   reporting `MESH-HOST: zabz-tech` from a resident window, matched against the provider's own
   location check. The sentence *"the mesh routes your agents across the mesh"* is true for the
   configuration `profiles/web/cordis.patch.yml` now carries.
10. **The broker is a supervised, loopback-only, self-healing service** that has been up 9 hours and
    re-reads every node rather than trusting a heartbeat table — which is why none of the staleness
    in this audit was able to hide behind a cached node state.

---

## 8. What I could not verify, and what would verify it

| not verified | why | what would unblock it |
|---|---|---|
| §0.3's six-child fleet, today | it spends money and occupies another machine; `82` §3 already has raw output for 03:47Z | `pwsh -File scripts\mesh-run.ps1 -Prompt "<task printing MESH-HOST:>" -Children 6 -Json`, then match each `MESH-HOST:` against the broker's choice |
| §0.5's fleet-death half | `82` §5 states it was never staged; staging it takes a real node out of the mesh | a named node + pid and an authorised knowingly-failing run |
| Whether `secratary` and `zabz-tech-linux` can take a v1 child | the stated reason (`no headless profile on secratary`) became false at 03:57Z; the measurement would be a real dispatch | one `dsh --profile headless` turn on each, with its `MESH-HOST:` line |
| the Mac's engine surviving a restart | restarting it needs the owner's machine and could end a session | restart pid 12458 once, on a machine nobody is using, and read `--profile web --dump-config` first (it already fails) |
| `secratary`'s 3,326 MiB of swap | no process holds it; whether it is reclaimable is a different measurement | `swapoff -a && swapon -a` during a window, or `/proc/pressure/memory` sampled across the change |
| the 216-entry gap between `journal.py status` (1400 by kind) and `find` (1616 files) | the tools I was given do not expose the reconciliation | `journal.py stats` / `journal.py doctor` on the authority |
| `harness-verify.ps1`'s subject | no mesh claim under `docs/mesh/` depends on it | whoever owns it naming what it is for |
| the laptop's `git pull --ff-only` repaired | §2 says commit nothing, and this file owns only itself | a `merge --no-ff` of `origin/master` (the trees are identical, so there is nothing to resolve) |

---

## 9. Provenance

Every command in this file was run from **ZABZ-YOGA** between **2026-09-17T13:04Z and 13:16Z** unless
marked `# on secratary` / over ssh to a named node; the ssh targets were
`secratary-ts`, `zabz-tech-ts`, `linux-pc-ts`, `mac-mini-ts`, each
`-o BatchMode=yes -o ConnectTimeout=15`, and every HTTP call used `--noproxy '*'` because this
laptop's `.pac` proxy invents 502s.

* Capacity documents: `curl` to `https://<node>.tail93e6e6.ts.net/mesh/capacity` and
  `http://127.0.0.1:3086/mesh/capacity`, 13:04:51–56Z.
* Broker: `systemctl status mesh-broker`, `ss -ltnp`, `curl http://127.0.0.1:3091/{nodes?fresh=1,healthz,place,done}`
  over ssh, 13:05:30Z and 13:09:25Z; roster read from `/home/zabz/mesh-broker/nodes.json`.
* Engines/profiles: `Win32_Process` command lines and `ps -eo`, `ls ~/.dsh/profiles`,
  `<node> <dsh>/lib/bin.js --profile web --dump-config`, 13:06–13:08Z.
* Gates: `sha256sum`/`Get-FileHash` of the running gate, `tailscale serve status`, `ss -ltnp`, and the
  allow-list probes with `-H "X-Forwarded-For: 100.126.146.121"` at 13:06:37Z (laptop) and
  13:07:09Z (linux) and on the Mac.
* Instruments: `pwsh -File scripts\mesh-e2e.ps1 -Strict -Json` at 13:11:26Z
  (report `~/.dsh/mesh/acceptance/20260917T131126Z/report.json`, `EXIT=2`); source read of
  `scripts/mesh-health.ps1`, `scripts/mesh-capacity-probe.ps1`, `scripts/phone-gate.py`.
* Journal and git: `journal.py check` / `status` / `find journal/entries` on the authority at
  13:10Z; `git fetch`, `rev-list --left-right --count`, `merge-base --is-ancestor`,
  `git pull --ff-only`, `git cherry -v`, `git diff --stat` on the laptop at 13:11Z.
* Commit charge: `Get-Counter '\Memory\Committed Bytes'`, `'\Memory\Commit Limit'`,
  `'\Memory\Available MBytes'`, `Win32_OperatingSystem` at 13:13Z.

**Nothing else was edited.** No commit, no push, no branch, no `git reset`, no engine restart, no
gate restart, no process killed, no fleet dispatched. The only writes on this machine were this file
and four `POST /done` calls releasing leases **this audit created**.
