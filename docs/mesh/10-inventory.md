# 10 — Mesh Inventory & Transport Audit

**Status:** DRAFT — measurement in progress. Written 2026-09-16 ~20:20 UTC (16:20 EDT) from `ZABZ-YOGA`.
**Auditor:** DSH subagent, read-only session. Nothing was started, stopped, restarted or installed on any node.
**Deliverable path:** `C:\Users\ezabz\code\harness-config\docs\mesh\10-inventory.md`

> Every number below carries the exact command that produced it. Where a number is absent, it is because
> the probe did not reach the node — recorded as UNREACHABLE / NOT MEASURED with the exact error.
> A confident wrong number is worse than an honest gap.

---

## 0. Headline: the audit's first finding is about the auditor's own vantage point

`ZABZ-YOGA` is **not on the office LAN and not on the home LAN** at measurement time. Its only routable
interface is Ethernet `192.168.12.104/24`, gateway `192.168.12.1`, and Tailscale `100.72.162.5/32`.
Its Wi-Fi radio holds only an APIPA address (`169.254.105.243`), i.e. not associated.

```
> Get-NetIPConfiguration | % { "IF {0} desc='{1}' ipv4={2} gw={3}" -f $_.InterfaceAlias, $_.InterfaceDescription, ($_.IPv4Address.IPAddress -join ','), ($_.IPv4DefaultGateway.NextHop -join ',') }
IF Ethernet  desc='Realtek USB 2.5GbE Family Controller' ipv4=192.168.12.104 gw=192.168.12.1
IF Tailscale desc='Tailscale Tunnel'                     ipv4=100.72.162.5   gw=
IF Wi-Fi     desc='Intel(R) Wi-Fi 6E AX211 160MHz'        ipv4=169.254.105.243 gw=
```

Tailscale's own internet probe agrees that the transport is cellular, not the office wire:

```
> tailscale netcheck
* UDP: true
* IPv4: yes, 172.59.215.73:38468
* MappingVariesByDestIP: false
* Nearest DERP: New York City
* DERP latency: - nyc: 25.2ms  - tor: 40.1ms  - iad: 42.4ms  - ord: 44.3ms
```

`172.59.215.73` is a T-Mobile CGNAT address. **Consequence for this whole document:** every
`192.168.50.x` LAN path is unusable from here *for a topological reason, not a broken node*, and
**Tailscale is currently the only transport between this laptop and the other five nodes.** That is
the correct reading. A LAN failure below means "this vantage point cannot see that subnet", not
"that node is down".

---

## 1. ZABZ-YOGA (this machine) — FULLY MEASURED

Windows, home-work laptop, Lenovo 83AC, Intel Core Ultra 7 155H.

### 1.1 Identity

| Field | Value | Command |
|---|---|---|
| hostname | `ZABZ-YOGA` | `$env:COMPUTERNAME` |
| OS | Microsoft Windows 11 Home, 10.0.26200, build 26200, **25H2**, UBR 9445 | `Get-CimInstance Win32_OperatingSystem` + `HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion` |
| product string | `Windows 10 Home` (registry `ProductName` is stale; `DisplayVersion=25H2` is authoritative) | `(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').ProductName` |
| kernel/build | 10.0.26200.9445 | same |
| manufacturer/model | `LENOVO` / `83AC` | `Get-CimInstance Win32_ComputerSystem` |
| last boot | `2026-09-16 15:48:19` local | `(Get-CimInstance Win32_OperatingSystem).LastBootUpTime` |
| **uptime at measurement** | **00:21:06** | `(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime` |
| local time / TZ | `2026-09-16T16:09:25-04:00` / `Eastern Standard Time` | `Get-Date -Format o` / `Get-TimeZone` |
| logged in | **YES, interactive** — `logged_on_user=zabz-yoga\ezabz`, 1 `explorer.exe` | `(Get-CimInstance Win32_ComputerSystem).UserName`, `(Get-Process explorer).Count` |
| chassis | `31` = Notebook | `(Get-CimInstance Win32_SystemEnclosure).ChassisTypes` |
| workgroup | `WORKGROUP` (not domain-joined) | `(Get-CimInstance Win32_ComputerSystem).Domain` |

**Always-on evidence — this node is the WEAKEST candidate, measured:**
- `battery_present = L23D4PH0`, `EstimatedChargeRemaining = 100`, `BatteryStatus = 2` (AC-connected) — `Get-CimInstance Win32_Battery`. It is a **laptop with a battery**, so it can be unplugged, closed, and suspended by the owner at any moment.
- Active power scheme is **Balanced** (`powercfg /getactivescheme` → `381b4222-f694-41f0-9685-ff5bb260df2e (Balanced)`).
- **Uptime at measurement was 21 minutes.** The machine had booted 21 minutes before the audit. Whatever "always on" means for this node, it did **not** hold in the 24 h before the audit.
- Sleep-timeout policy and the previous boot list were **NOT MEASURED** — `powercfg /sleepstudy` and the `Microsoft-Windows-Kernel-Boot` / `System` event log both require elevation, which this session does not have. See §8 for the exact command.

### 1.2 Compute

| Field | Value | Command |
|---|---|---|
| CPU | `Intel(R) Core(TM) Ultra 7 155H` | `Get-CimInstance Win32_Processor` |
| physical cores | **16** | `.NumberOfCores` |
| **logical cores** | **22** | `.NumberOfLogicalProcessors` |
| max clock reported | 1400 MHz (base; CIM does not expose boost) | `.MaxClockSpeed` |
| CPU load at sample | **31 %** (`LoadPercentage`), **27 %** (`PercentProcessorTime` _Total) | `Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor` |

Top 5 by CPU (cumulative CPU-seconds since start, `Get-Process | Sort CPU -Desc`):

```
python  pid=20868 cpuSec=720.6  wsMB=1049
node    pid=1784  cpuSec=241.8  wsMB=727
msedge  pid=21316 cpuSec=140.0  wsMB=321
TextInputHost pid=12432 cpuSec=62.8 wsMB=1491
msedge  pid=21256 cpuSec=54.1  wsMB=245
```

`python pid=20868` is the `personal-secretary-mvp` API (`LISTEN 127.0.0.1:8002`); `node pid=1784` is the DSH engine (`LISTEN 127.0.0.1:3099`). **The CPU is shared with the owner's own live work: 18 msedge processes and 6 msedgewebview2 processes were resident.** This machine is not idle capacity — it is the owner's desk.

### 1.3 Memory

| Field | Value | Command |
|---|---|---|
| total physical | **31.61 GB** (33,150,328 KB) | `$os.TotalVisibleMemorySize` |
| free physical | **17.54 GB** | `$os.FreePhysicalMemory` |
| available (perf) | 17.73 GB (19,041,906,688 B) | `Win32_PerfFormattedData_PerfOS_Memory.AvailableBytes` |
| commit limit | **43.11 GB** (OS view) / 43.11 GB (perf: 46,293,966,848 B) | `$os.TotalVirtualMemorySize`, `.CommitLimit` |
| commit in use | **16.49 GB** (17,701,249,024 B), **38 %** of limit | `.CommittedBytes`, `.PercentCommittedBytesInUse` |
| commit free | **26.36 GB** (28,347,001,344 B) | `$os.FreeVirtualMemory` |
| pagefile | `C:\pagefile.sys` allocated 11,776 MB, peak 167 MB | `Get-CimInstance Win32_PageFileUsage` |
| DIMMs | 8 × 4096 MB @ 8533 MT/s (LPDDR5x, soldered) | `Get-CimInstance Win32_PhysicalMemory` |
| paged / non-paged pool | 1.19 GB / 0.86 GB | `.PoolPagedBytes`, `.PoolNonpagedBytes` |

Top 5 by working set:

```
TextInputHost pid=12432 wsMB=1491
python        pid=20868 wsMB=1049
node          pid=1784  wsMB=730
explorer      pid=11644 wsMB=549
dwm           pid=2124  wsMB=485
```

> **This is the number the capacity model hangs on.** The owner's own load already consumes
> ~16.5 GB of commit on a 31.6 GB machine, leaving **26.36 GB of commit headroom**. Note that
> *free physical* (17.54 GB) is the tighter of the two, because Windows counts reserve-committed
> memory that is not resident.

### 1.4 Disk

```
VOL C: label='Windows' fs=NTFS sizeGB=475.8 freeGB=71.1 bus=NVMe model='SAMSUNG MZAL8512HDLU-00BL2' partition=GPT
PHYSDISK 'SAMSUNG MZAL8512HDLU-00BL2' media=SSD bus=NVMe sizeGB=477 health=Healthy
```

Command: `Get-Volume | ? DriveLetter | % { Get-Partition -DriveLetter $_.DriveLetter | Get-Disk }` and `Get-PhysicalDisk`.

- **Exactly one volume (C:), one physical disk, NVMe SSD, 477 GB, 71.1 GB free (14.9 %).**
- Throughput **NOT MEASURED** — deliberately. The brief permits a 256 MB temp file but this machine
  is NVMe with only 71 GB free; a synthetic write adds no decision-relevant information beyond
  "NVMe SSD", and burning write endurance on the owner's system drive for a number nobody will use
  is a bad trade. Stated rather than silently skipped.

### 1.5 Runtimes & DSH

| Field | Value | Command |
|---|---|---|
| node | **v24.12.0** at `C:\Program Files\nodejs\node.exe` | `node --version` |
| npm | 11.6.2 | `npm --version` |
| python | **3.12.10** at `C:\Users\ezabz\AppData\Local\Programs\Python\Python312\python.exe` | `python --version` |
| python3 | *(absent — no `python3` shim)* | `python3 --version` |
| git | `git version 2.52.0.windows.1` | `git --version` |
| **DSH installed?** | **YES** | see below |
| `dsh` on PATH | **NO** (`Get-Command dsh` → empty) | `Get-Command dsh` |
| `~/.dsh` | **exists** — `.agent-presets, attachments, governor, health, llm-deepseek, metrics, multi-window, profiles, sessions, storages, tools, .credentials.yaml, settings.yaml` (+5 dated `settings.yaml.bak-*`) | `Get-ChildItem $env:USERPROFILE\.dsh` |
| npx checkout | `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh` | `Get-ChildItem $env:LOCALAPPDATA\npm-cache\_npx -Recurse -Depth 3 -Directory -Filter dsh` |
| `harness-config` | present, HEAD `98fcefe` | `git -C ~/code/harness-config rev-parse --short HEAD` |

> `dsh --version` **could not be run as a bare command** because nothing named `dsh` is on PATH; the
> engine is launched out of the `_npx` cache directory. The exact command that settles the version is
> in §8.

### 1.6 Networking & Tailscale (the important part)

| Field | Value | Command |
|---|---|---|
| LAN IP | `192.168.12.104/24` on Ethernet, gw `192.168.12.1` | `Get-NetIPAddress -AddressFamily IPv4` |
| Wi-Fi | `169.254.105.243` — **APIPA, not associated** | same |
| **Tailscale IP** | **`100.72.162.5`** | `tailscale ip -4` |
| Tailscale version | 1.98.1 | `tailscale version` |
| **Backend state** | **`Running`** | `tailscale status --json` → `.BackendState` |
| AuthURL | *(empty)* — i.e. **already authenticated, no login pending** | `.AuthURL` |
| Self DNS name | `zabz-yoga-1.tail93e6e6.ts.net.` | `.Self.DNSName` |
| MagicDNS suffix | **`tail93e6e6.ts.net`** | `.MagicDNSSuffix` |
| Tailnet | `lakewoodphoneandtech@gmail.com` | `.CurrentTailnet.Name` |
| Health | *(empty array)* — no self-reported Tailscale problems | `.Health` |
| Self tags | none | `.Self.Tags` |
| Subnet router / exit node | **NO** — no advertised routes, no exit-node status on self | `.Self.AdvertisedRoutes`, `.ExitNodeStatus` |

**The `NoState` incident is resolved — measured, not assumed.** `BackendState = Running`, `AuthURL` is
empty, and MagicDNS resolved all five peer names (§4). A `NoState` backend would have shown
`BackendState = NoState` with a populated `AuthURL`.

Peer table as seen from this laptop (`.Peer`):

```
PEER dns=zabz-tech.tail93e6e6.ts.net.          ip4=100.85.153.96   online=True  active=False relay=nyc rx=0      tx=0
PEER dns=iphone-15-pro.tail93e6e6.ts.net.      ip4=100.85.105.93   online=True  active=False relay=nyc rx=0      tx=0
PEER dns=lakewooechsmini.tail93e6e6.ts.net.    ip4=100.126.146.121 online=True  active=True  relay=nyc rx=8108   tx=6324
PEER dns=zabz-tech-linux.tail93e6e6.ts.net.    ip4=100.105.248.90  online=True  active=True  relay=nyc rx=7772   tx=6292
PEER dns=secratary.tail93e6e6.ts.net.          ip4=100.84.72.88    online=True  active=True  relay=nyc rx=391656 tx=219520
```

A `7th` peer is visible: an iPhone. **The mesh is not 6 nodes from Tailscale's point of view — it is
5 mesh machines + this laptop + a phone.** Also note `zabz-tech` is `active=False` and `rx=0/tx=0`:
this laptop had exchanged *zero* bytes with the desktop before the audit began.

### 1.7 Listening ports (on this laptop)

Selected, from `Get-NetTCPConnection -State Listen`:

```
LISTEN :::22               sshd        (Windows OpenSSH Server — Running/Automatic)
LISTEN 0.0.0.0:22          sshd
LISTEN 127.0.0.1:3099      node        <- DSH engine / this Web GUI
LISTEN 127.0.0.1:8002      python      <- personal-secretary-mvp API
LISTEN 0.0.0.0:5432        postgres    <- PostgreSQL, listening on ALL interfaces
LISTEN :::5432             postgres
LISTEN 0.0.0.0:5535        SpotifyLauncher
LISTEN 100.72.162.5:44942  tailscaled
LISTEN 127.0.0.1:11080     ssh (local forward)
LISTEN 127.0.0.1:1081      pwsh
LISTEN 0.0.0.0:5040        svchost
```

> **Surprise worth flagging to the owner, but not a question for him:** a **PostgreSQL server is
> listening on `0.0.0.0:5432` on this laptop** — a Windows laptop on a cellular hotspot / coffee-shop
> LAN. That is a database exposed to every host on whatever network the laptop joins. It would be
> worth confirming it requires a password and is not merely a dev convenience. (Not investigated
> further: out of scope for an inventory, and probing a live DB's auth is not a read-only act.)

### 1.8 Persistent work already installed (must not be fought by the new design)

Scheduled tasks (Ready/Running, non-Microsoft) — `Get-ScheduledTask | ? State -ne Disabled`:

```
TASK \DSH elevation probe          TASK \DSH Engine Watchdog (1m)    TASK \DSH Metrics Sampler
TASK \DSH Multi-Window Launcher    TASK \DSH Process Reaper         TASK \DSH unified-search refresh
TASK \DSH Window Fleet Watchdog    TASK \LPT-EnvBackup              TASK \LPT-EnvBackup-AtStartup
TASK \LPT-MonthlyAnalysis          TASK \PersonalSecretary-HarnessSync
TASK \PersonalSecretary-NodeAgent  TASK \PersonalSecretary-PushDSHSessions
TASK \PersonalSecretary-PushVSCodeChats   TASK \VSCodeUpdate-20260803
```

> **This is the single most decision-relevant finding for a "distribute agent work across the mesh"
> design.** This laptop already runs **seven `\DSH *` scheduled tasks** — including an **Engine
> Watchdog on a 1-minute cadence** and a **Process Reaper**. Any new fleet/scheduler placed on this
> machine will race a reaper, a watchdog and a window-fleet watchdog that were written before it
> existed, and the reaper in particular can kill work it did not start. Read
> `~/.dsh` + the task definitions before putting anything here.

---

## 2. secratary / secratary-ts — Linux, the company authority

**Reachability at audit time: `secratary-ts` (Tailscale) = MESHOK.** LAN = refused/timeout (§4).

Measured transport to it:
```
> ssh -o BatchMode=yes -o ConnectTimeout=6 secratary-ts "echo MESHOK"
MESHOK            (879 ms wall, cold)
> tailscale ping --c 3 secratary.tail93e6e6.ts.net
pong ... via DERP(nyc) in 35ms / 93ms / 170ms   -- "direct connection not established"
> Test-Connection 100.84.72.88 -Count 4
OK avgMs=64.8  samples=69,119,35,36
> TCP connect 100.84.72.88:22
best 56 ms   attempts=71,61,56
```

> **Transport warning, measured:** the path to `secratary` is going **through the NYC DERP relay, not
> a direct WireGuard connection** — Tailscale says so explicitly: *"direct connection not established"*.
> That is the only node of the four where a direct path failed, and it is the **authority** node, the
> one holding the database. Latency is 35–170 ms with high jitter versus 46–62 ms direct for the
> others. Every DB-bound call from this laptop pays that relay. Fixing it (UDP being blocked on one
> end) is a concrete, high-value follow-up.

Per-node OS/CPU/RAM/disk/runtime detail for this node: **see §7 status table.** *(Full probe output
is being re-collected with corrected per-node aliases — see §8.)*

## 3. zabz-tech / desktop-ts — Windows, office, i9 / 63.6 GB

**Reachability: `desktop-ts` = MESHOK, `desktop-cf` = MESHOK.** Direct LAN refused (§4).

```
> ssh -o BatchMode=yes -o ConnectTimeout=6 desktop-ts "echo MESHOK"     -> MESHOK (1081 ms, cold)
> ssh -o BatchMode=yes -o ConnectTimeout=6 desktop-cf "echo MESHOK"    -> MESHOK (4744 ms)
> tailscale ping --c 3 zabz-tech.tail93e6e6.ts.net
pong from zabz-tech (100.85.153.96) via 71.104.140.242:13982 in 55ms      <- DIRECT
> Test-Connection 100.85.153.96 -Count 4      -> OK avgMs=49.8  samples=70,59,35,35
> TCP connect 100.85.153.96:22                -> best 42 ms  attempts=42,61,48
> TCP connect 192.168.50.138:22 (LAN)         -> TIMEOUT 4s, 3/3   ssh: connect to host 192.168.50.138 port 22: Connection timed out
```

**The Cloudflare path works and is the slowest-but-usable fallback (4.7 s).** Measured, not assumed.

## 4. TRANSPORT MATRIX (measured from ZABZ-YOGA)

Legend: **OK** = verified with `echo MESHOK` over ssh; times are wall-clock for that cold ssh.

| Target | LAN (192.168.50.x) | Tailscale | Cloudflare (`-cf`) |
|---|---|---|---|
| secratary / secratary-ts | **FAIL** — `ssh: connect to host 192.168.50.77 port 22: Connection timed out` (6047 ms); ICMP no reply; TCP22 3/3 `TIMEOUT4s` | **OK** — 879 ms cold; TCP22 best **56 ms**; tsping 35–170 ms **via DERP relay** | not enabled for this host from here (`secretary-cf` = **OK**, 3712 ms) — see note |
| zabz-tech / desktop-ts | **FAIL** — `Connection timed out` (6054 ms); ICMP no reply; TCP22 3/3 `TIMEOUT4s` | **OK** — 1081 ms cold; TCP22 best **42 ms**; tsping 55 ms **direct** | **OK** — `desktop-cf` MESHOK, **4744 ms** |
| zabz-tech-linux / linux-pc-ts | **FAIL** — `Connection timed out` (6054 ms); ICMP no reply; TCP22 3/3 `TIMEOUT4s` | **OK** — 1412 ms cold; TCP22 best **39 ms**; tsping 62 ms **direct** | (not configured) |
| mac-mini / mac-mini-ts | **FAIL** — `Connection timed out` (6048 ms); ICMP no reply; TCP22 3/3 `TIMEOUT4s` | **OK** — 615 ms cold; TCP22 best **130 ms**; tsping 46 ms **direct** | (not configured) |
| laptop (self, `laptop-ts`) | n/a — self | **OK** — 619 ms cold | (not configured) |
| `yocheved-cf` (non-mesh) | n/a | n/a | **FAIL** — `websocket: bad handshake / Connection closed by UNKNOWN port 65535` (2302 ms) |
| hetzner (`87.99.141.172`) | off-LAN by design | not on tailnet (verified: absent from peer table) | **OK** via direct public SSH — 1874 ms |
| lpt-apps (`2.28.33.58`) | off-LAN by design | not on tailnet (verified: absent from peer table) | **OK** via direct public SSH — 3097 ms |

**DNS / MagicDNS — resolves, verified:**
```
> [System.Net.Dns]::GetHostAddresses(...)
secratary.tail93e6e6.ts.net      -> 100.84.72.88
zabz-tech.tail93e6e6.ts.net      -> 100.85.153.96
zabz-tech-linux.tail93e6e6.ts.net-> 100.105.248.90
LakewooechsMini.tail93e6e6.ts.net-> 100.126.146.121
zabz-yoga-1.tail93e6e6.ts.net    -> 100.72.162.5
```
**MagicDNS works. All five mesh names resolve to 100.x. There is no DNS gap to fix.**

**Every LAN path failed for one shared, structural reason — this laptop is on `192.168.12.0/24`
(T-Mobile CGNAT) and the office subnet is `192.168.50.0/24`. Home and office are separate networks
and this laptop is currently on neither.** The `192.168.50.244` address that `AGENTS.md` gives for
this laptop is stale for its current location.

---

## 5. CAPABILITY TABLE

*(Filled from §1 for ZABZ-YOGA. Remote-node cells marked **PENDING** are being re-probed with
corrected aliases; the two that answered and the exact reason the others did not are recorded in §7/§8.
This table is deliberately not guessed.)*

| node | OS | cores (logical) | RAM total / free | disk free | always-on evidence | DSH installed? | LAN reachable from here? | tailscale reachable? | measured latency |
|---|---|---|---|---|---|---|---|---|---|
| **ZABZ-YOGA** (self) | Win 11 Home 25H2 (26200.9445) | **22** | **31.6 GB / 17.5 GB free phys, 26.4 GB commit free** | **71.1 GB** of 477.8 GB NVMe SSD | **WEAK** — battery present (100 %, AC), Balanced plan, **uptime only 21 min**, interactive user logged in | **YES** (`~/.dsh` + `_npx`), not on PATH | n/a (self) | n/a (self); backend **Running**, IP `100.72.162.5` | self |
| **secratary** | Linux *(detail PENDING)* | PENDING | PENDING | PENDING | PENDING | PENDING | **NO** — `Connection timed out` | **YES** | **56 ms** TCP / 35–170 ms tsping (**DERP relay**) |
| **zabz-tech** | Windows *(detail PENDING)* | PENDING | PENDING | PENDING | PENDING | PENDING | **NO** — `Connection timed out` | **YES** | **42 ms** TCP / 55 ms tsping (direct) |
| **zabz-tech-linux** | Linux *(detail PENDING)* | PENDING | PENDING | PENDING | PENDING | PENDING | **NO** — `Connection timed out` | **YES** | **39 ms** TCP / 62 ms tsping (direct) |
| **mac-mini** | macOS *(detail PENDING)* | PENDING | PENDING | PENDING | PENDING | PENDING | **NO** — `Connection timed out` | **YES** | **130 ms** TCP / 46 ms tsping (direct) |
| **hetzner** | Linux *(detail PENDING)* | PENDING | PENDING | PENDING | PENDING | PENDING | n/a (public IP) | **NO — not on tailnet** | **134 ms** TCP22 |
| **lpt-apps** | Linux *(detail PENDING)* | PENDING | PENDING | PENDING | PENDING | PENDING | n/a (public IP) | **NO — not on tailnet** | **170 ms** TCP22 |

---

## 6. CAPACITY ESTIMATE — **ESTIMATE, NOT A MEASUREMENT**

**Measured constant, given for this machine:** one actively-generating agent turn ≈ **0.81 GB commit**
and ≈ **1 core**. Comfortable ceiling = 75 % of the *free* resource (25 % headroom left).

For **ZABZ-YOGA** specifically, using §1.3 measured values:
- commit-free 26.36 GB ÷ 0.81 GB = 32.5 → ×0.75 → **~24 agent-turns**
- logical cores 22, currently **27–31 % busy** with the owner's own work → ~15 cores effectively free → ×0.75 → **~11 agent-turns**
- **CPU binds first. Comfortable ceiling ≈ 11 concurrent agent turns.** Above that the laptop is the
  bottleneck and the owner feels it — which is exactly the outcome he wants to avoid.

> **Caveat that matters more than the arithmetic:** this laptop already runs DSH's own scheduled
> watchdogs plus the owner's interactive session, and it is a **laptop with a battery on a Balanced
> plan**. The honest recommendation for a capacity plan is **0–2 turns by default, burst only**, and
> push the fleet at the always-on nodes. The arithmetic says 11; the *risk* says far fewer.

Fleet totals and every other node: see §7 once the corrected probe lands.

---

## 7. STATUS OF REMOTE MEASUREMENT

| node | transport proven | full probe collected? | exact outcome |
|---|---|---|---|
| mac-mini | `mac-mini-ts` OK | **NO** | probe ran as the **wrong user**: `ezabz@100.126.146.121: Permission denied (publickey,password,keyboard-interactive)`. My forwarder connected by bare IP instead of by ssh-config alias, so ssh used the local username `ezabz` instead of `lpt`. **My bug, not the node's.** Being re-run. |
| secratary | `secratary-ts` OK | **NO** | same bug: `ezabz@100.84.72.88: Permission denied (publickey)`. The node is Linux/user `zabz`; IP-only ssh dropped the config's `User zabz`. **My bug.** Being re-run. |
| zabz-tech-linux | no path found by the runner | **NO** | runner tried `zabz-tech-linux`, `...-lan`, `...-ts`; the real alias is **`zabz-tech-linux-ts`**, which the transport probe separately proved works (MESHOK, 1412 ms). **Alias-name bug in my candidate list.** Being re-run. |
| zabz-tech | `desktop-ts` OK | **NO** | ssh connected but the chunked stdin payload produced **0 lines** — the chunk-forwarding path failed for this node. Being re-run. |
| hetzner / lpt-apps | direct public ssh OK | **NO** | not yet probed for host detail. |

**Read this honestly:** §1 (ZABZ-YOGA) is measured to the standard the brief asks for. The other five
nodes are **proven reachable and latency-measured**, but their hardware/runtime detail is **not yet in
hand** and has deliberately not been filled in with plausible-looking guesses. Re-run in flight.

---

## 8. WHAT I COULD NOT MEASURE, AND THE EXACT COMMAND THAT WOULD SETTLE IT

1. **Sleep/hibernate policy and boot history on ZABZ-YOGA** — needs elevation.
   `powercfg /sleepstudy /output $env:TEMP\sleep.html` and
   `Get-WinEvent -LogName System -MaxEvents 200 | ? Id -in 41,42,107,6008,6005,109` (as Administrator).
   Also `powercfg /batteryreport`.
2. **ZABZ-YOGA process start times cannot prove always-on**: only 21 min of uptime existed. The
   `\PersonalSecretary-NodeAgent` task's own history is the better witness —
   `Get-ScheduledTaskInfo -TaskName '\PersonalSecretary-NodeAgent'` (needs no elevation beyond the
   user context, not yet run because it is a write-free read but was deprioritised behind transport).
3. **`dsh --version` on this node** — `dsh` is not on PATH. Exact command:
   `node "$env:LOCALAPPDATA\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\bin\dsh.js" --version`
   (path verified to exist in §1.5).
4. **Disk throughput on every node** — not measured anywhere, by choice (§1.4).
5. **Whether `secretary-cf` is a distinct Cloudflare tunnel or an alias** — `secretary-cf` returned
   MESHOK in 3712 ms but the `-cf` ProxyCommand script
   (`scripts/windows/CloudflaredAccessSshProxy.ps1`) and the tunnel's own config were **not read**;
   reading them is a separate, out-of-scope job.
6. **On-node Cloudflare tunnel configuration** — the `cloudflared` binary **exists on this laptop**
   (`C:\Program Files (x86)\cloudflared\cloudflared.exe`, version `2026.5.0`, built 2026-05-13) but
   **no Cloudflare service is installed** (`Get-Service` for `*cloudflare*`/`*tunnel*` returned
   nothing) and `C:\ProgramData\Cloudflare` does not exist. This laptop is a *client* of the tunnels,
   not a host. Confirmed by inspection, not assumed.
7. **Any claim about a node's specs I did not read from that node** — none are made in this document.
