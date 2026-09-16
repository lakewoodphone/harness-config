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
| `node` | this node's identity | `tailscale status --json` → `Self.DNSName` **minus the tailnet domain** (the DNS label — see §2.1), cached once per process | falls back to `Self.HostName`, then to the OS hostname; `unknown` only if even that fails |
| `fqdn` | this node's identity | same call → `Self.DNSName`, trailing dot stripped | Tailscale cannot name this node and its own name is not qualified |
| `at` | clock | `time.gmtime()`, second precision, `Z` | never |
| `cpu.logical` | OS | `os.cpu_count()` | the call fails |
| `cpu.physical` | OS | Linux `/proc/cpuinfo` distinct (physical id, core id); macOS `sysctl hw.physicalcpu`; Windows one `Win32_Processor.NumberOfCores` query, cached for the life of the process | the platform read fails |
| `cpu.load1` | OS | `os.getloadavg()[0]` | **always on Windows** — Windows has no load average (see §5) |
| `mem.totalMiB` / `freeMiB` | OS | Windows `GlobalMemoryStatusEx`; Linux `/proc/meminfo` `MemAvailable` (see §5) | the OS counter cannot be read |
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

Measured (raw response, spare gate instance on `127.0.0.1:3087` with `--engine-port 59999`):

```json
{"schema": 1, "node": "zabz-yoga", "fqdn": "zabz-yoga-1.tail93e6e6.ts.net", "at": "2026-09-16T23:16:36Z",
 "cpu": {"logical": 22, "physical": 16, "load1": null},
 "mem": {"totalMiB": 32373, "freeMiB": 15452, "swapUsedPct": 0.0},
 "disk": {"workRoot": "C:/Users/ezabz/code", "freeGiB": 63.7},
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

Exit `0` when every targeted node passed, `1` when any failed or was unreachable. The probe fetches
with an `HttpClient` whose `UseProxy` is false — **the PAC proxy on this laptop invents a 502 for a
tailnet name**, so a proxied fetch measures the proxy, not the node. For a human at a shell,
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

### 7.1 After the 23:40Z correction — all four gated nodes, 2026-09-16 23:27Z

Fetched from the laptop with the proxy off; `mesh-capacity-probe.ps1` validates every payload
against §2.1 (types, nullability, unknown fields, and `fleet:false` with no reason). 5/5 targets
`PASS` — loopback plus the four nodes:

```
2026-09-16T23:26:53Z  host=ZABZ-YOGA  targets=5  failed=0
loopback        zabz-yoga-1.tail93e6e6.ts.net      schema=1  loops=9  slots=24  free=23   109ms  PASS
zabz-yoga (self) zabz-yoga-1.tail93e6e6.ts.net     schema=1  loops=9  slots=24  free=23   285ms  PASS
zabz-tech       zabz-tech.tail93e6e6.ts.net        schema=1  loops=0  slots=24  free=24   311ms  PASS
zabz-tech-linux zabz-tech-linux.tail93e6e6.ts.net  schema=1  agents=null  slots=24  free=24   454ms  PASS
secratary       secratary.tail93e6e6.ts.net        schema=1  agents=null  slots=24  free=24   293ms  PASS
```

`accepts.fleet`, and the reason that carries the inference — the node the fix was for, raw:

```json
{"schema": 1, "node": "zabz-tech-linux", "fqdn": "zabz-tech-linux.tail93e6e6.ts.net", "at": "2026-09-16T23:27:01Z",
 "cpu": {"logical": 12, "physical": 6, "load1": 0.02},
 "mem": {"totalMiB": 11673, "freeMiB": 10252, "swapUsedPct": 15.4},
 "disk": {"workRoot": "/home/zabz/code", "freeGiB": 20.8},
 "agents": null,
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12,
             "reason": "slot budget computed from memory; no governor lease directory on this node, so inUse is reported as 0 and is not measured"}}
```

and the authority, raw:

```json
{"schema": 1, "node": "secratary", "fqdn": "secratary.tail93e6e6.ts.net", "at": "2026-09-16T23:27:01Z",
 "cpu": {"logical": 4, "physical": 4, "load1": 0.3},
 "mem": {"totalMiB": 23422, "freeMiB": 17135, "swapUsedPct": 99.9},
 "disk": {"workRoot": "/home/zabz/code", "freeGiB": 184.0},
 "agents": null,
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12,
             "reason": "slot budget computed from memory; no governor lease directory on this node, so inUse is reported as 0 and is not measured"}}
```

The two Windows nodes, with a lease directory present (laptop first, so its `inUse` is measured):

```json
{"node": "zabz-yoga", "cpu": {"logical": 22, "physical": 16, "load1": null},
 "mem": {"totalMiB": 32373, "freeMiB": 15025, "swapUsedPct": 0.0},
 "disk": {"workRoot": "C:/Users/ezabz/code", "freeGiB": 64.2},
 "agents": {"loopsRunning": 9, "sessionsLive": 15},
 "governor": {"budgetSlots": 24, "inUse": 1, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12, "reason": null}}

{"node": "zabz-tech", "cpu": {"logical": 32, "physical": 24, "load1": null},
 "mem": {"totalMiB": 65173, "freeMiB": 52235, "swapUsedPct": 0.0},
 "disk": {"workRoot": "C:/Users/ezabz/code", "freeGiB": 220.4},
 "agents": {"loopsRunning": 0, "sessionsLive": 1},
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12, "reason": null}}
```

The engine-down case still holds after the correction (spare gate on `127.0.0.1:3087`,
`--engine-port 59999`, 23:27:10Z, probe `PASS`):

```json
{"node": "zabz-yoga", "agents": null, "governor": null,
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
* The Mac mini: no gate deployed (S3's stream), so it is not a target of the default probe run.
  `-All` reports it as unreachable today.
* Nodes behind an engine that is up with plugin-health absent: `agents` is null by design, and the
  404 case was measured on the authority and on `zabz-tech-linux` only.
* Whether a fleet actually *runs* on `zabz-tech-linux` and the authority: this route only says the
  capacity is there. Nothing was dispatched by this stream.
* Load behaviour under a burst: the route was measured warm and cold, not with 30 concurrent
  callers (71 §6 is stream S7's test).
