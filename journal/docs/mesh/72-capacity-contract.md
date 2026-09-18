# 72 — The capacity contract: `GET /mesh/capacity`, served by the gate

Stream S1 of the mesh program (docs/mesh/71-mesh-program.md). This file is the record of what the
route does, where every number in it comes from, and what was measured when it was shipped. The
interface itself is frozen in 71 §2.1 — this document describes an implementation of it, and a
disagreement between the two is a bug in this file, not a licence to change the schema.

Owner of the code: `scripts/phone-gate.py` (the `/mesh/capacity` route and its helpers),
`scripts/mesh-capacity-probe.ps1` (the checker), and this document.

## 1. Why it lives in the gate

The broker (S5, on the authority) must know, at the moment it decides, how much room each node has.
Every other place that answer could come from — a host plugin route, a new engine API, a settings
change — needs an **engine restart**, and on this fleet a restart ends every live session (P210,
measured; the restart would have killed the session that was building this). The gate already runs
on every gated node, already answers routes of its own before relaying, and restarts freely, so the
capacity surface ships there. **No engine restart is required or was performed anywhere.**

The route is answered by the gate and the connection closed, exactly like `/dsh-phone-mobile.css`:
the gate is a raw TCP relay that inspects the first request head and then becomes a pipe, so a
self-answered route has to be a complete HTTP response on one connection.

## 2. The schema, and where each field comes from

Every field is **measured or `null`**. Nothing is estimated, and a number that cannot be measured is
never rendered as `0` — a node that reported 0 free slots would be queued by the broker for ever,
which is worse than an honest absence.

| field | source | method | when it is `null` |
|---|---|---|---|
| `schema` | constant | `1` | never |
| `node` | this node's identity | `tailscale status --json` → `Self.DNSName` **minus the tailnet domain** (the DNS label — see §2.1), read with the bounded, process-group-killed call of §9.2 and cached once per process | falls back to `Self.HostName`, then to the OS hostname; `unknown` only if even that fails |
| `fqdn` | this node's identity | same call → `Self.DNSName`, trailing dot stripped | Tailscale cannot name this node and its own name is not qualified — and when it is null the node is named in `accepts.reason`, because a null with no cause is not reportable (§9.3) |
| `at` | clock | `time.gmtime()`, second precision, `Z` | never |
| `cpu.logical` | OS | `os.cpu_count()` | the call fails |
| `cpu.physical` | OS | Linux `/proc/cpuinfo` distinct (physical id, core id); macOS `sysctl hw.physicalcpu`; Windows one `Win32_Processor.NumberOfCores` query, cached for the life of the process | the platform read fails |
| `cpu.load1` | OS | `os.getloadavg()[0]` | **always on Windows** — Windows has no load average (see §5) |
| `mem.totalMiB` / `freeMiB` | OS | Windows `GlobalMemoryStatusEx`; Linux `/proc/meminfo` `MemAvailable`; **macOS `vm_stat` free+inactive+speculative+purgeable × `sysctl hw.pagesize`** — one field, one meaning, three readings (§5, §9.1) | the OS counter cannot be read |
| `mem.swapUsedPct` | OS | Windows `GetPerformanceInfo`: page-file committed / page-file size; Linux `SwapTotal`/`SwapFree`; macOS `sysctl vm.swapusage` | the platform read fails |
| `disk.workRoot` | config | `PHONE_GATE_WORK_ROOT`, else `~/code` when it exists, else `$HOME`, with `/` separators | never |
| `disk.freeGiB` | OS | `shutil.disk_usage(workRoot).free`, one decimal | the path cannot be stat'ed |
| `agents` | the engine | `GET /healthz` on `127.0.0.1:<engine-port>` with a session cookie the gate mints for itself → `sessions.agentLoopsRunning`, `sessions.live` | **the engine does not answer, or answers without plugin-health mounted (404), or the payload has no `sessions` block** |
| `governor` | the governor's lease directory, plus the budget arithmetic | `<root>/leases/slot-NN.lease` with `expiresAt` in the future = `inUse`; `<root>/waiters/*.wait` = `queued`; `budgetSlots` by the governor's own arithmetic — **computed even when no lease directory exists**, in which case `inUse`/`queued` are `0` by inference and `accepts.reason` says so | **the engine does not answer** |
| `accepts.oneShot` | protocol | `true` always — `ssh <node> dsh --profile headless` needs no engine on this node (71 §0, measured) | never false |
| `accepts.fleet` | derived | true when the engine answers, the slot budget is computable from `mem.freeMiB`, at least one slot is free, and `disk.freeGiB >= 20` | — |
| `accepts.maxChildren` | derived | `min(free slots, 12)`, or `0` when `fleet` is false | — |
| `accepts.reason` | derived | one line naming the restriction (**blockers**), or the derived number (**notes**), or `null` when neither applies | — |

### The node name (settled 2026-09-16, and it was wrong on this laptop)

`node` is the node's **Tailscale DNS label** — `Self.DNSName` minus the tailnet domain — and never
the ssh alias prefix. The reason is resolvability: the broker and `mesh-health.ps1` can only act on
a name MagicDNS answers to. Two nodes on this fleet show why the distinction is real, and the second
one was a live defect:

| node | ssh alias prefix | `Self.HostName` | `Self.DNSName` | `node` reported |
|---|---|---|---|---|
| ZABZ-YOGA (laptop) | `laptop`, `zabz-yoga` | `zabz-yoga` | `zabz-yoga-1.tail93e6e6.ts.net` | **`zabz-yoga-1`** |
| ZABZ-TECH | `zabz-tech` | `zabz-tech` | `zabz-tech.tail93e6e6.ts.net` | `zabz-tech` |
| secratary | `secratary` | `secratary` | `secratary.tail93e6e6.ts.net` | `secratary` |
| zabz-tech-linux | `linux-pc`, `hp-linux` | `zabz-tech-linux` | `zabz-tech-linux.tail93e6e6.ts.net` | `zabz-tech-linux` |

Measured 2026-09-16 23:31Z on the laptop, which is the row that made the rule load-bearing:
`Resolve-DnsName zabz-yoga.tail93e6e6.ts.net` → **DNS name does not exist**, and
`curl https://zabz-yoga.tail93e6e6.ts.net/mesh/capacity` → curl error 6, while `zabz-yoga-1` resolves
to 100.72.162.5 and answers 200. Tailscale appends the `-1` to the *DNS* name only, and `Self.HostName`
is not dependable in general either — the iPhone on this tailnet reports it as `localhost`. The gate
now takes the label, and `mesh-capacity-probe.ps1` enforces the invariant `node == fqdn.split(".")[0]`
on every node, so the next node whose two names disagree cannot ship quietly.

**Do not "fix" the gate to match an ssh alias.** `zabz-tech-linux`'s aliases are `linux-pc` and
`hp-linux`; its node name is `zabz-tech-linux` on purpose.

`governor.budgetSlots` reproduces the governor's own derivation rather than inventing a second one
(`packages/plugin-health/lib/governor.js:117-149`):

```
reserve = max(2 GiB, 12% of physical)          reserveMiB = 3885 on a 31.6 GiB laptop
usable  = max(0, freeBytes - reserve)
budget  = min(floor(usable / 160 MiB), 24), floored at 4
```

and `mem.freeMiB` uses the same counter node's `os.freemem()` uses, so this route and
`governor.mjs status` cannot disagree about the same machine in the same second.

**The lease directory is needed for `inUse`, not for the budget** (corrected 2026-09-16 23:40Z).
The first build required the directory and refused fleet placement without it. The broker measured
the cost within the hour: `zabz-tech-linux` and `secratary` — the two nodes the mesh was built to
use, 24 computed slots each — were excluded, and fleet-eligible capacity collapsed to the two
Windows machines. The budget is arithmetic on a memory measurement; the directory only counts how
many slots are taken. So when the engine answers and `mem.freeMiB` is readable, the gate reports
`budgetSlots` with `inUse: 0` when no lease directory exists anywhere it looks, and names the
inference in `accepts.reason`:

```json
"governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
"accepts": {"oneShot": true, "fleet": true, "maxChildren": 12,
            "reason": "slot budget computed from memory; no governor lease directory on this node, so inUse is reported as 0 and is not measured"}
```

That zero is an inference from the absence of the directory, not a number invented to fill a hole:
the governor creates its layout before it grants anything (`ensureLayout`, governor.js:100), so a
host with no lease directory has no holders and no waiters. And the rule that keeps it honest is the
one distinction this correction turns on:

* an **unmeasured budget** (no readable `mem.freeMiB`, or no engine) → `accepts.fleet: false` with
  that as the reason;
* an **unmeasured counter** (`inUse` with no directory) → `accepts.fleet: true`, `inUse: 0`, and the
  condition named in `reason`.

Refusing the second was the defect. `reason` on a `fleet: true` answer is a note, not a restriction;
the frozen `accepts` rule in 71 §2.1 was amended to say so, and that one sentence is the only change
made to the frozen interface by this stream.

**Residency and placement arithmetic is the broker's, not this route's** (71 §2.1, last bullet).
The gate owns no leases, stores no node state, and re-measures on every request; `accepts` is
advisory and the broker recomputes (71 §2.2).

## 3. The engine-down contract

The whole point of the route is that it keeps answering when a node is sick. With the engine down:

* `agents` is `null` and `governor` is `null` — **not** `0`, and not a stale lease count. A lease
  directory with no engine behind it describes holders that cannot be checked and renewals that have
  stopped, so it is refused rather than reported. This is the one place the route deliberately
  reports *less* than it could read, and it is what 71 §2.1 asks for.
* `accepts.oneShot` is still `true`, with `reason` naming the condition: a headless run needs no
  engine.
* `accepts.fleet` is `false`, `maxChildren` is `0`, and `reason` says why.
* Everything measured from the OS — `cpu`, `mem`, `disk` — is unaffected and still reported.

Measured on the shipped build (raw response, spare gate instance on `127.0.0.1:3087` with
`--engine-port 59999`, 2026-09-16 23:32:56Z):

```json
{"schema": 1, "node": "zabz-yoga-1", "fqdn": "zabz-yoga-1.tail93e6e6.ts.net", "at": "2026-09-16T23:32:56Z",
 "cpu": {"logical": 22, "physical": 16, "load1": null},
 "mem": {"totalMiB": 32373, "freeMiB": 14804, "swapUsedPct": 0.0},
 "disk": {"workRoot": "C:/Users/ezabz/code", "freeGiB": 64.2},
 "agents": null, "governor": null,
 "accepts": {"oneShot": true, "fleet": false, "maxChildren": 0,
             "reason": "the engine on 127.0.0.1:59999 does not answer, so residency cannot be measured here: one-shot runs are accepted, fleets are not placed on this node"}}
```

`mesh-capacity-probe.ps1 -Local -Port 3087` validates that payload against the schema and passes.

## 4. Where it is deployed, and how to change it

| node | gate file | how it runs | restart |
|---|---|---|---|
| ZABZ-YOGA (laptop) | `C:\Users\ezabz\code\harness-config\scripts\phone-gate.py` | `pythonw.exe`, launched by the `DSH Phone Gate` scheduled task (every 5 min) | stop the process; the task restarts it, or `Start-ScheduledTask -TaskName 'DSH Phone Gate'` |
| ZABZ-TECH (desktop) | same path | same task, `C:\Python313\pythonw.exe` | same |
| secratary (authority) | `/home/zabz/harness-config/scripts/phone-gate.py` | systemd `phone-gate.service`, `/usr/bin/python3`, engine port 3089 | `sudo systemctl restart phone-gate` |
| zabz-tech-linux (`zabz-tech-linux`) | `/home/zabz/dsh-mesh/repo/scripts/phone-gate.py` — S2's node checkout, not this repo's path | systemd `phone-gate.service`, `/usr/bin/python3`, engine port 3099 | `sudo systemctl restart phone-gate` |

The gate reads nothing from the repository at request time that it does not already read for its
other routes, so **deploying a change is: copy the one file, restart the gate.** No engine is
touched, and none was.

**Do not start a Windows gate from inside an ssh or scheduled-session shell.** Measured
2026-09-16: the desktop's gate started from an ssh session lived about ten seconds and then
vanished with the session (its process tree went with the ssh channel), and tailscale Serve answered
502 until the `DSH Phone Gate` task started it again. Use the scheduled task.

## 5. Known limits, stated rather than hidden

* **`cpu.load1` is null on every Windows node.** Windows has no load average: node's own
  `os.loadavg()` returns `[0, 0, 0]` there, measured in this node's `/healthz` on a machine that was
  demonstrably busy. A literal `0` is the one value the broker must never see, because it reads as
  "idle", so the field is null and the broker's scoring (71 §2.2) does not use it.
* **`mem.freeMiB` on Windows is `ullAvailPhys`**, not a "usable" figure: it is what the governor's
  own budget reads, so the two agree, and it is not adjusted for standby or cache.
* **`swapUsedPct` is a page-file figure on Windows**, defined as page-file committed over page-file
  size. It is not the same thing as Linux's `SwapFree`; the two are only comparable in intent, and a
  broker must not compare them numerically across platforms.
* **`agents` needs plugin-health mounted on the node's engine.** Measured 2026-09-16: the laptop and
  desktop engines answer `/healthz`; **`secratary`'s engine returns 404 for it**, so `agents` is null
  on the authority. Mounting the plugin there is an engine restart (P210) and is not this stream's
  decision. A null `agents` means "not measured on this node", never "no agents".
* **`governor.inUse: 0` with no lease directory is an inference, and `reason` says so.** Neither
  `zabz-tech-linux` nor the authority has ever run a governor, so there is nothing to count. The
  field is not `null` because the *budget* is measurable and a fleet can be placed without the
  count; the count is not silently claimed, because the reason string carries it.
* **HEAD and non-GET requests are not answered here** and are relayed to the engine unchanged, the
  same as the stylesheet route.
* **CORS is deliberately not sent.** The callers are the broker and `mesh-run`, both server-side.
  The route is inside the gate's device allow-list, so it is exactly as exposed as the gate itself
  (71 §2.1) — all four tailnet devices that may be signed in are already listed in
  `scripts/phone-gate-allow.txt`, the authority included, so a broker on secratary can read every
  node.

## 6. How to check it

```powershell
# every gated node, schema-validated, with the raw JSON
pwsh -File scripts\mesh-capacity-probe.ps1 -Raw

# just this node, through its own gate
pwsh -File scripts\mesh-capacity-probe.ps1 -Local

# every tailnet peer, including nodes with no gate yet
pwsh -File scripts\mesh-capacity-probe.ps1 -All
```

Exit `0` when every targeted node passed, `1` when any failed or was unreachable. It checks the shape
(types, nullability, no unknown fields), the rules that carry meaning (`fleet:false` must name its
reason; `oneShot` must be true), and the identity invariant `node == fqdn's first label`. The probe
fetches with an `HttpClient` whose `UseProxy` is false — **the PAC proxy on this laptop invents a 502
for a tailnet name**, so a proxied fetch measures the proxy, not the node. For a human at a shell,
`curl --noproxy '*' https://<node>.tail93e6e6.ts.net/mesh/capacity` is the same thing.

For the node it runs on, the probe also compares `mem.freeMiB` and `disk.freeGiB` against a direct
OS read taken at that moment (71 §4.1), with tolerance: free memory moves between the two reads, so
the check catches a route reporting a *different machine*, not a megabyte.

For the engine-down case, without touching any real engine:

```powershell
$py = (Get-Command python.exe).Source
Start-Process $py -ArgumentList @(
  'C:\Users\ezabz\code\harness-config\scripts\phone-gate.py',
  '--listen-port','3087','--engine-port','59999') -PassThru
pwsh -File scripts\mesh-capacity-probe.ps1 -Local -Port 3087 -Raw   # -> PASS, agents/governor null
```

## 7. Evidence

### 7.1 The shipped build — all four gated nodes, 2026-09-16 23:32Z

Fetched from the laptop with the proxy off; `mesh-capacity-probe.ps1` validates every payload
against §2.1 (types, nullability, unknown fields, the `node == fqdn` label invariant, and
`fleet:false` with no reason). 5/5 targets `PASS` — loopback plus the four nodes. This is the run
against the bytes deployed on every node (gate sha256 `4ec735cd…1661`):

```
2026-09-16T23:32:41Z  host=ZABZ-YOGA  targets=5  failed=0
loopback           zabz-yoga-1.tail93e6e6.ts.net     schema=1  loops=9  slots=24  free=23   260ms  PASS
zabz-yoga-1 (self) zabz-yoga-1.tail93e6e6.ts.net     schema=1  loops=9  slots=24  free=23   182ms  PASS
zabz-tech          zabz-tech.tail93e6e6.ts.net       schema=1  loops=0  slots=24  free=24   325ms  PASS
zabz-tech-linux    zabz-tech-linux.tail93e6e6.ts.net schema=1  agents=null  slots=24  free=24   329ms  PASS
secratary          secratary.tail93e6e6.ts.net       schema=1  agents=null  slots=24  free=24   303ms  PASS
```

`accepts.fleet: true` and `maxChildren: 12` on all five targets. The node the governor fix was for,
raw (note `node` = the DNS label, and the reason carrying the `inUse` inference):

```json
{"schema": 1, "node": "zabz-tech-linux", "fqdn": "zabz-tech-linux.tail93e6e6.ts.net", "at": "2026-09-16T23:32:42Z",
 "cpu": {"logical": 12, "physical": 6, "load1": 0.02},
 "mem": {"totalMiB": 11673, "freeMiB": 10255, "swapUsedPct": 15.4},
 "disk": {"workRoot": "/home/zabz/code", "freeGiB": 20.8},
 "agents": null,
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12,
             "reason": "slot budget computed from memory; no governor lease directory on this node, so inUse is reported as 0 and is not measured"}}
```

and the authority, raw:

```json
{"schema": 1, "node": "secratary", "fqdn": "secratary.tail93e6e6.ts.net", "at": "2026-09-16T23:32:42Z",
 "cpu": {"logical": 4, "physical": 4, "load1": 0.16},
 "mem": {"totalMiB": 23422, "freeMiB": 17146, "swapUsedPct": 99.9},
 "disk": {"workRoot": "/home/zabz/code", "freeGiB": 183.9},
 "agents": null,
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12,
             "reason": "slot budget computed from memory; no governor lease directory on this node, so inUse is reported as 0 and is not measured"}}
```
 "cpu": {"logical": 4, "physical": 4, "load1": 0.3},
 "mem": {"totalMiB": 23422, "freeMiB": 17135, "swapUsedPct": 99.9},
 "disk": {"workRoot": "/home/zabz/code", "freeGiB": 184.0},
 "agents": null,
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12,
             "reason": "slot budget computed from memory; no governor lease directory on this node, so inUse is reported as 0 and is not measured"}}
```

The two Windows nodes, with a lease directory present (same run, so the laptop's `inUse` is measured
rather than inferred — and the laptop's `node` is the DNS label, `zabz-yoga-1`):

```json
{"node": "zabz-yoga-1", "cpu": {"logical": 22, "physical": 16, "load1": null},
 "mem": {"totalMiB": 32373, "freeMiB": 14984, "swapUsedPct": 0.0},
 "disk": {"workRoot": "C:/Users/ezabz/code", "freeGiB": 64.2},
 "agents": {"loopsRunning": 9, "sessionsLive": 16},
 "governor": {"budgetSlots": 24, "inUse": 1, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12, "reason": null}}

{"node": "zabz-tech", "cpu": {"logical": 32, "physical": 24, "load1": null},
 "mem": {"totalMiB": 65173, "freeMiB": 52229, "swapUsedPct": 0.0},
 "disk": {"workRoot": "C:/Users/ezabz/code", "freeGiB": 220.4},
 "agents": {"loopsRunning": 0, "sessionsLive": 1},
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12, "reason": null}}
```

The engine-down case still holds on the shipped build (spare gate on `127.0.0.1:3087`,
`--engine-port 59999`, 23:32:56Z, probe `PASS`):

```json
{"node": "zabz-yoga-1", "agents": null, "governor": null,
 "accepts": {"oneShot": true, "fleet": false, "maxChildren": 0,
             "reason": "the engine on 127.0.0.1:59999 does not answer, so residency cannot be measured here: one-shot runs are accepted, fleets are not placed on this node"}}
```

### 7.2 The first run, before the correction (kept, because the defect is the record)

23:20:40Z, four targets, all `PASS` — and `secratary` reporting `fleet: false` for the reason that
turned out to be wrong. The two slow rows are the *first* request after a gate restart on that
machine (identity read, core count, token exchange, first `/healthz`); warm, the same route measured
laptop loopback 13–34 ms, laptop through Serve 65–72 ms, desktop loopback 13–42 ms, authority
through Serve 141–168 ms.

```
2026-09-16T23:20:40Z  host=ZABZ-YOGA  targets=4  failed=0
loopback          zabz-yoga-1.tail93e6e6.ts.net   schema=1  loops=9  slots=24  free=23   3495ms  PASS
zabz-yoga (self)  zabz-yoga-1.tail93e6e6.ts.net   schema=1  loops=9  slots=24  free=23    155ms  PASS
zabz-tech         zabz-tech.tail93e6e6.ts.net     schema=1  loops=0  slots=24  free=24    150ms  PASS
secratary         secratary.tail93e6e6.ts.net     schema=1  agents=null  gov=null     3175ms  PASS   <- fleet refused, wrongly
```

Two numbers worth someone's attention, both outside this stream: **the authority is running with its
swap 99.9 % used** (4092 of 4095 MiB, `free -m`), and **`zabz-tech-linux` has only 20.8 GiB free**
on its work root — above the 20 GiB fleet floor by 0.8 GiB, so one more build there takes it out of
fleet placement.

## 8. What this stream did not verify

* The broker's own reading of these payloads (S5) and `mesh-run`'s placement (S6) — both are other
  streams; this route has only been exercised by `curl` and by `mesh-capacity-probe.ps1`. The
  correction in §2 was made *because* the broker stream measured the consequence, which is the
  closest thing to an independent check this route has had.
* The Mac mini: ~~no gate deployed (S3's stream), so it is not a target of the default probe run.
  `-All` reports it as unreachable today.~~ **Superseded 2026-09-17:** S3 deployed a gate on it
  (`/Library/LaunchDaemons/com.lakewoodphone.mesh-gate.plist`, port 3086) and this stream measured
  it end to end — see §9. It is still not in the default probe's target list.
* Nodes behind an engine that is up with plugin-health absent: `agents` is null by design, and the
  404 case was measured on the authority and on `zabz-tech-linux` only.
* Whether a fleet actually *runs* on `zabz-tech-linux` and the authority: this route only says the
  capacity is there. Nothing was dispatched by this stream.
* Load behaviour under a burst: the route was measured warm and cold, not with 30 concurrent
  callers (71 §6 is stream S7's test).

---

## 9. 2026-09-17 — macOS measured at last: a memory reading, a hang-proof CLI call, and the real cause of `fqdn: null`

Written by S1 (this file's owner) against the defects `74-mac-mini.md` §7.3 and §4 reported. Every
number below carries the moment it was taken; all times are UTC. **Deployed file: sha256
`4cf9c268a63cf50f40b4573f117c8aecaf28729094ab0c121b647c4656f8632a` (121,763 B)**, copied to
`/Users/lpt/.dsh-gate/scripts/phone-gate.py` on the Mac mini at **00:18:37Z** and serving there since
(verified 00:18:38Z: `fqdn` and `physical` correct one second after restart, `reason: null`, six
requests, zero leaked processes). The measurements in §9.1–§9.4 were taken minutes earlier on the
immediately preceding build, `9f196b7b…5384` (121,327 B), which differs from this one **only in
comments**; the file it replaced is preserved on the Mac as `phone-gate.py.prev-20260917-0000`
(sha `4ec735cd…1661`, also recoverable from this repo's `HEAD:scripts/phone-gate.py`). Only the
**two** gates this stream touched were restarted — this laptop's and the Mac mini's; ZABZ-TECH, the
authority and `zabz-tech-linux` still run `4ec735cd…1661` until the manager syncs the file, which is
a copy-and-restart with no engine involved (`§4`). **No engine was restarted anywhere**, and nothing
was committed.

### 9.1 `mem.freeMiB` on macOS: one field, one meaning

`_memory_bytes()` had no darwin branch, so on every macOS node `mem.freeMiB` was `null` and the
broker could not score the node at all (`74` §7.3). It now has one:

```
total = sysctl -n hw.memsize
page  = sysctl -n hw.pagesize              # NOT assumed: 16384 on Apple Silicon, 4096 on Intel
free  = (Pages free + Pages inactive + Pages speculative + Pages purgeable) x page
```

**`freeMiB` means reclaimable memory on every platform, and the definition is the contract:**

| platform | counter | what it is |
|---|---|---|
| Windows | `GlobalMemoryStatusEx` → `ullAvailPhys` | what node's own `os.freemem()` reads, and therefore what the governor's budget is derived from; not adjusted for standby or cache |
| Linux | `/proc/meminfo` → `MemAvailable` | the kernel's own estimate of memory available to new work without swapping (`SC_AVPHYS_PAGES` only if `meminfo` cannot be read) |
| **macOS** | `vm_stat` free + inactive + speculative + purgeable × `hw.pagesize` | memory the OS will hand to a new process without paging something out first |

**What is deliberately NOT counted on macOS, and why it matters:** `Pages wired down` and the
compressor's `Pages occupied by compressor` are *in use*, not reclaimable (the compressor held
5.67 GB of real RAM on this machine at `74` §3.1's measurement), and `Pages active` is not free
either. Counting `Pages free` alone, which is the obvious thing to do and the wrong one, read
**3,897 pages = 60.9 MiB at 23:50:00Z** on a healthy 16 GB machine: it would declare a Mac
memory-dead while the OS was holding gigabytes of reclaimable cache, and the number would not mean
the same thing as `ullAvailPhys` or `MemAvailable`. If `hw.pagesize` cannot be read the function
returns `None` rather than assuming 4096 — a guess there is a silent 4× error in the one number
placement turns on — and if `Pages free` is absent the whole reading is refused, because a `0`
would be the confident wrong number this route exists to avoid.

Measured, same moment, both readings (`vm_stat` + `sysctl` by hand, the gate's own JSON in the same
second):

| moment | free | inactive | speculative | purgeable | pages × 16,384 B | gate `freeMiB` |
|---|---|---|---|---|---|---|
| 2026-09-16T23:59:07Z | 386,785 | 209,728 | 20,708 | 2,100 | 9,676.9 MiB | **9,677** (at 23:59:08Z) |
| 2026-09-17T00:10:41Z | 5,832 | 313,384 | 155,798 | 7,369 | 7,536.5 MiB | **7,536** (at 00:10:41Z) |

`totalMiB` is 16,384 on both readings (`hw.memsize` 17,179,869,184). `swapUsedPct` was **not
touched** and still works: 84.2 at 23:50Z, 60.9 after the machine's load changed — same
`sysctl vm.swapusage` path as before.

### 9.2 The tailnet CLI call: absolute path, own process group, kill the GROUP

`74` §4.2 named the hazard: `subprocess.run(["tailscale", …], timeout=10)` on macOS, where
`/usr/local/bin/tailscale` is a 68-byte shim (`#!/bin/sh` + `/Applications/Tailscale.app/Contents/MacOS/Tailscale "$@"`)
whose GUI binary may never answer a non-interactive call. **Both call sites in this file now go
through one helper** (`_tailscale_run`), which enforces three rules, because skipping any of them
brings the leak back:

1. **An absolute path is resolved, once, and logged once** (`_tailscale_binary`). On darwin the
   order is `/opt/homebrew/bin/tailscale` (a real CLI that talks to the running `tailscaled`) →
   `/usr/local/bin/tailscale` → `/opt/local/bin/tailscale` → `/usr/bin/tailscale` → the bare name
   from PATH. `PHONE_GATE_TAILSCALE` pins one path for a node laid out differently and for testing.
   A wrapper around the GUI app is *used* when it is all a node has — rule 3 makes that safe — but
   the log says which binary and what it is, so a null `fqdn` has a readable cause. The log line is
   emitted at gate startup as well as on first use.
2. **The child leads its own process group** (`start_new_session=True`) and a timeout SIGKILLs the
   **group** (`_kill_tailscale_group`), then the child is reaped; `os.killpg` is absent on Windows
   and the fallback is the child alone.
3. **The wait is bounded** at `TAILSCALE_TIMEOUT = 10 s`, the result is cached for 60 s per process
   (`_TAILSCALE_SELF`), and a failure is a *value*, never an exception that reaches the route. When
   `fqdn` comes out null the route now says so in `accepts.reason`, as a note rather than a
   restriction: a node whose name cannot be read can still run work.

**Measured proof, on the Mac mini, 2026-09-17** — with a synthetic shim of exactly the real shim's
shape (a shell script that starts a long-lived grandchild holding the inherited stdout and never
answers), so no real Tailscale process or network extension was touched:

| what was run | measured |
|---|---|
| **old shape**: `subprocess.run([shim, …], timeout=3)` at 00:05:52Z | returned after **3.0 s** and left the grandchild **alive** (`grandchild=1` at 9 s) — the orphan `74` §4.1 counted thirteen of |
| **new shape**: a spare gate pinned to the same shim, request 1 at 00:12:20Z | `HTTP 200 in 10.0448 s`, `fqdn: null`, `node: lakewooechsmini` (hostname fallback) **and the reason string naming exactly that**; the log line `tailscale: status --json did not answer within 10s; killed process group 21170 and reaped it` |
| same, per-second sampler | shim and grandchild both present t+04…t+12, **both gone from t+13**, and `shim=0 grandchild=0` for the remaining 10 samples |
| same, requests 2 and 3 | `0.0143 s` and `0.0108 s` — a cached failure, so the route is never blocked twice for one cause |
| `_tailscale_run` called directly against the same shim | returned `None` after **10.01 s**, "killed process group 17730 and reaped it", **zero survivors** |

**On the real machine, after the live gate was restarted** (`sudo launchctl kickstart -k
system/com.lakewoodphone.mesh-gate`, 6 capacity requests, 2026-09-17 00:10:41Z): the tailscale-family
process counts were **identical before and after** —
`app(Tailscale)=0  cli(tailscale)=0  shim=0  daemon(tailscaled)=1  nesessionmanager=1` — with
`tailscaled` 0.1 % CPU and `nesessionmanager` 0.0 % CPU in the same window. The number to beat was
**thirteen** spinning clients and a `nesessionmanager` pinned at **33.5 % of a core** (`74` §4.3);
today's count is zero clients and an idle host. No engine was restarted at any point.

**One correction to the brief's account, measured:** on this Mac the *real* `/usr/local/bin/tailscale`
answered in full when tested directly (00:05:49Z, `rc=0`, 9,940 bytes of `status --json` under a
`perl alarm` bound) — the shim does not hang *always*, and it did not hang here. `74` §4.1's thirteen
hung clients are real and its causal story for the CPU is real, but the hang is state-dependent; the
repo's obligation is the same either way, and the fix removes it for both states. Likewise,
`subprocess.run` on CPython 3.9.6 and 3.12 does **not** wait for EOF for ever — it returns after its
timeout and leaves the grandchild — so the durable defect was the **orphan**, not a blocked caller.

### 9.3 Why the Mac's `fqdn` was null — and it was not the shim

The `"fqdn": null` recorded in `74` §7.3 had a different cause, found while proving §9.2 and fixed
here. `_MESH_CACHE` used `identityAt: 0.0` and `physicalAt: 0.0` as "not read yet" sentinels, then
tested `(now - at) < 60` to decide whether to skip a fresh read. **`0.0` is indistinguishable from
"read at time zero", so the skip was taken whenever the clock itself was younger than 60 seconds.**
On Windows and Linux `time.monotonic()` is time since boot and that window is long over before a gate
starts, which is why it never showed there.

Measured on this Mac (macOS 26.5.2, Apple Python 3.9.6, 2026-09-17 00:09Z): `time.monotonic()` reads
**0.004 in a fresh process**, advances at exactly **1.0 s/s** (4.01 s over a 4.0 s sleep), and its
origin is reset per process. Therefore **every gate process on macOS spent its first ~60 seconds
reporting `node` as the OS hostname, `fqdn: null` and `cpu.physical: null`, without calling the
tailnet CLI at all.** Two payloads from the *same* Mac gate process (pid 14801, started 19:59:05Z)
show it: at **19:59:06Z** `"fqdn": null, "physical": null`, and at **00:01:20Z** (135 s of process
life) `"fqdn": "lakewooechsmini.tail93e6e6.ts.net", "physical": 10`. A unit test with a 0.004-second
clock reproduces both sides: the old sentinel produced **0 CLI calls** and `('zabz-yoga', None)`;
the new one produces **1 call** and the correct name.

**Fix:** the sentinels are `None`, and "never attempted" is tested as such. After the fix, **2
seconds after a kickstart** (00:10:41Z) the node already reported its tailnet name and its core
count — the window that produced every null in `74` §7.3 is gone. The same payload carries
`"reason": null`, i.e. no caveat at all.

### 9.4 The Mac mini's capacity, verbatim, and what the broker scores it

`GET /mesh/capacity` on `https://lakewooechsmini.tail93e6e6.ts.net` from ZABZ-YOGA, through Tailscale
Serve, 2026-09-17 00:11:54Z (HTTP 200 in 7.2 s cold, ~0.02 s warm on the node itself):

```json
{"schema": 1, "node": "lakewooechsmini", "fqdn": "lakewooechsmini.tail93e6e6.ts.net", "at": "2026-09-17T00:11:54Z",
 "cpu": {"logical": 10, "physical": 10, "load1": 1.63},
 "mem": {"totalMiB": 16384, "freeMiB": 7708, "swapUsedPct": 60.9},
 "disk": {"workRoot": "/Users/lpt/code", "freeGiB": 46.0},
 "agents": null,
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12, "reason": null}}
```

The same object 2 s after the gate restart (00:10:41Z) read `freeMiB: 7536`, and the hand measurement
in that second computed 7,536.5 MiB (§9.1). `agents` is null because that node's engine answers 404
for `/healthz` — pre-existing, and `74` §7.3's `agents` field is unchanged.

**What the frozen broker formula (`71` §2.2, `reserveMiB = 3885`) scores with these numbers:**
`floor((7536 − 3885) / 160) = 22` slots; with the 9,677 MiB reading of 23:59:08Z it is
`floor((9677 − 3885) / 160) = 36 → capped at 24`. So **on 2026-09-17 the node is 22–24 slots, not
zero** — and this is a change in the machine's *state*, not a disagreement with `74` §3.1: the live
Chrome session that held ~7.1 GB has been closed since that audit (measured 2026-09-17 00:01Z: **2**
Chrome processes, compressor 87,126–101,905 pages against `74` §3.1's 369,740, `Pages free` 386,785
against 3,897, swap 60.9 % against 84.3 %, and uptime 43 d 21 h — **no reboot**). This is exactly the
change `74` §6.1 predicted would make the node fleet-eligible ("free pages ~6 GB → `slots` ≈ 13"),
and it is the node's own work that changed, not this route's arithmetic.

**If `freeMiB` ever falls below the broker's reserve, that is the correct answer and it will not be
massaged.** Below 3,885 MiB the broker's frozen formula yields ≤ 0 slots and the node is ineligible
for even one child; the gate would still report `governor.budgetSlots` ≥ 4 and `accepts.fleet: true`,
because the gate reproduces the **governor's** arithmetic, whose reserve is `max(2 GiB, 12 % of
physical)` = 2,048 MiB on a 16 GB host and whose budget is floored at 4
(`MESH_GOVERNOR_MIN_SLOTS`). The two reserves are frozen in two different places (`71` §2.1 and
§2.2), the divergence is a property of the interface rather than of this build, and it is stated here
so that the broker stream and the manager can see it: **the gate's `accepts` is advisory and the
broker recomputes** (`71` §2.1, last bullet). `mem.freeMiB` is also volatile — 9,677 → 8,234 → 7,536
MiB within eleven minutes of measurement on a machine doing other work — which is the argument for
re-reading at decision time rather than caching (`71` §5).

### 9.5 What this round did NOT verify

* **Nothing was dispatched to the Mac.** No one-shot turn, no fleet; only the route was measured. The
  broker's and `mesh-run`'s behaviour on this node is S5's and S6's to measure.
* **The real shim's hang was not reproduced** (it answered fully at 00:05:49Z — §9.2), so the
  timeout path is proven against a synthetic shim of the same shape, not against the real one. *Why*
  it hangs for some sessions and not others is not explained here.
* **The transport to the Mac is worse than `74` §7.4 recorded.** During this work the node went
  **offline** to the tailnet while staying up on the office LAN (`tailscale status` → "offline, last
  seen 4m ago" at 23:56Z; `secratary` pinged its LAN address with 0 % loss at 23:55Z), and ssh
  handshakes to it and to `secratary` timed out repeatedly (23:56, 23:58, 00:00, 00:03, 00:09Z) while
  `tailscale ping` answered in 24–63 ms and raw TCP to port 22 succeeded. Two capacity reads through
  Serve took 0.17 s warm and 7.2 s cold. The retry behaviour `71` §2.3 specifies is necessary, and on
  this path the *connect* is what stalls, so a 10-second connect timeout is not enough.
* **The Mac's memory state is a moving target** (§9.4): the 22–24-slot reading is a reading, not a
  property of the node.
* **The Mac gate has no device allow-list.** Its own log says it, twice, at 20:01:54 and 20:10:41
  local: `NO DEVICE RESTRICTION — /Users/lpt/.dsh-gate/scripts/phone-gate-allow.txt does not exist;
  every device on the tailnet will be signed in automatically.` That is S3's deployment, it is a
  security posture rather than a capacity defect, and it was reported rather than changed.
* **`scripts/phone-redirector.py:44` still has the old shape** — `["tailscale", "status", "--json"]`
  with `timeout=10` and no process group, exactly as `74` §4.2 lists it. It is not a file this stream
  owns, and it is the remaining place where the orphan of §9.2 can still be created.

### 9.6 Windows and Linux, unchanged

`mesh-capacity-probe.ps1` (default targets, 2026-09-17 00:11:47Z): **5/5 PASS, exit 0** — loopback and
`zabz-yoga-1` 84/153 ms, `zabz-tech` 166 ms, `zabz-tech-linux` 142 ms, `secratary` 655 ms, all
`schema=1`, all `fleet: true`, `maxChildren: 12`, with the loopback row's `mem.freeMiB` within 30 MiB
of a direct OS read. The laptop's own payload before and after the change has the identical field set
and the identical meanings (`node` `zabz-yoga-1`, `physical` 16, `load1` null on Windows, `agents`
from `/healthz`, `governor.inUse` 1 from a real lease directory, `reason` null), and the engine-down
contract is byte-identical to §3's recorded example (`agents`/`governor` null, `oneShot: true`,
`fleet: false`, `maxChildren: 0`, the same reason sentence) on a spare gate at `--engine-port 59999`.
The only behavioural change on those platforms is the None sentinel of §9.3, which restores the
intended first-read behaviour on any host whose clock is younger than a minute.

One Windows observation, for the record: the first request after a gate restart pays the cold cost
and can lose the WMI race. Measured on the laptop after a clean restart (2026-09-17 00:13:26Z):
`t+3 s → HTTP 200 in 3.49 s, physical=16, fqdn correct`, then `0.02–0.03 s` for every later request;
in one earlier restart (00:11:24Z) the first request reported `"physical": null` and the field read 16
within the following minute. That self-healing null is pre-existing — the pre-change baseline showed
the same pattern (23:57:29Z null → 23:57:59Z 16) — and it is schema-legal (`physical` may be null), so
the probe passes either way. It is noted rather than fixed: it belongs to the platform read, not to
this change.

