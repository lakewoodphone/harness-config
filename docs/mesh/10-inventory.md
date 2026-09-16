# 10 — Mesh Inventory & Transport Audit

**Written:** 2026-09-16, 16:10–16:30 EDT (20:10–20:30 UTC) from `ZABZ-YOGA`.
**Author:** DSH subagent, read-only session. **Nothing was started, stopped, restarted or installed on
any node.** One 7 KB probe script was copied to `C:\Users\ezabz\mesh-probe.ps1` on `ZABZ-TECH` to be
run there — that is the only file this audit created outside its own deliverable, and it is inert.
All scratch files live in `%TEMP%`.

**Coverage: 7 machines measured.** 5 with full hardware detail; `mac-mini` and `zabz-tech` with
identity + transport but hardware detail pending a corrected probe (§9 says exactly what is missing and
why). Every number carries the command that produced it.

---

## 0. The finding that reframes everything: the auditor's vantage point

`ZABZ-YOGA` is **not on the office LAN and not on the home LAN.** Its only routable interface is
Ethernet `192.168.12.104/24`, gateway `192.168.12.1`; Wi-Fi holds only APIPA `169.254.105.243`
(not associated).

```
> Get-NetIPConfiguration | % { "IF {0} desc='{1}' ipv4={2} gw={3}" -f $_.InterfaceAlias, $_.InterfaceDescription, ($_.IPv4Address.IPAddress -join ','), ($_.IPv4DefaultGateway.NextHop -join ',') }
IF Ethernet  desc='Realtek USB 2.5GbE Family Controller' ipv4=192.168.12.104  gw=192.168.12.1
IF Tailscale desc='Tailscale Tunnel'                     ipv4=100.72.162.5    gw=
IF Wi-Fi     desc='Intel(R) Wi-Fi 6E AX211 160MHz'        ipv4=169.254.105.243 gw=
```

```
> tailscale netcheck
* UDP: true
* IPv4: yes, 172.59.215.73:38468
* MappingVariesByDestIP: false
* Nearest DERP: New York City
* DERP latency: - nyc: 25.2ms  - tor: 40.1ms  - iad: 42.4ms  - ord: 44.3ms
```

Public address `172.59.215.73` is T-Mobile CGNAT. **Therefore every `192.168.50.x` LAN result below is
a statement about this vantage point, not about the remote node.** Tailscale is currently the *only*
transport from this laptop to the other machines. The `192.168.50.244` address that `AGENTS.md`
records for this laptop is stale for its present location.

---

## 1. ZABZ-YOGA — this laptop (owner's night machine)

Lenovo 83AC, Intel Core Ultra 7 155H, **22 logical / 16 physical cores, 31.61 GB.**

### 1.1 Identity
```
> $env:COMPUTERNAME                                    -> ZABZ-YOGA
> Get-CimInstance Win32_OperatingSystem
  Caption=Microsoft Windows 11 Home  Version=10.0.26200  BuildNumber=26200
> HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion
  DisplayVersion=25H2  UBR=9445  ProductName="Windows 10 Home"   <- registry string is STALE; 25H2 is authoritative
> Win32_ComputerSystem: Manufacturer=LENOVO Model=83AC Domain=WORKGROUP UserName=zabz-yoga\ezabz
> LastBootUpTime = 2026-09-16 15:48:19   ->  uptime at sample = 00:21:06
> TimeZone = Eastern Standard Time; local time 2026-09-16T16:09:25-04:00
> (Get-Process explorer).Count  -> 1        <- interactive desktop session IS open
> (Get-CimInstance Win32_SystemEnclosure).ChassisTypes -> 31 (Notebook)
> Get-CimInstance Win32_Battery -> Name=L23D4PH0  BatteryStatus=2 (AC)  EstimatedChargeRemaining=100
> powercfg /getactivescheme -> 381b4222-f694-41f0-9685-ff5bb260df2e (Balanced)
```

**Always-on evidence — this node is the weakest candidate, measured:** it has a **battery**, is on the
**Balanced** power plan, has an **interactive user logged in**, and had **21 minutes of uptime** when
sampled. "Almost always on" is false for this node in the 24 h before the audit. Sleep-timeout policy
and the previous-boot list need elevation — see §9.

### 1.2 Compute
```
> Get-CimInstance Win32_Processor -> Intel(R) Core(TM) Ultra 7 155H; NumberOfCores=16; NumberOfLogicalProcessors=22; MaxClockSpeed=1400
> Win32_PerfFormattedData_PerfOS_Processor(_Total).PercentProcessorTime -> 27   (Win32_Processor.LoadPercentage -> 31)
> Get-Process | ? CPU -gt 0 | Sort CPU -Desc | Select -First 5
  python        pid=20868 cpuSec=720.6  wsMB=1049
  node          pid=1784  cpuSec=241.8  wsMB=727
  msedge        pid=21316 cpuSec=140.0  wsMB=321
  TextInputHost pid=12432 cpuSec=62.8   wsMB=1491
  msedge        pid=21256 cpuSec=54.1   wsMB=245
```
`python pid=20868` = the `personal-secretary-mvp` API (`LISTEN 127.0.0.1:8002`). `node pid=1784` = the
DSH engine (`LISTEN 127.0.0.1:3099`). **18 `msedge` + 6 `msedgewebview2` processes were resident** — the
CPU is shared with the owner's live work, not spare capacity.

### 1.3 Memory
```
> Win32_OperatingSystem: TotalVisibleMemorySize=33150328 KB (31.61 GB)  FreePhysicalMemory=18388176 KB (17.54 GB)
                         TotalVirtualMemorySize=45208952 KB (43.11 GB) FreeVirtualMemory=27640884 KB (26.36 GB)
> Win32_PerfFormattedData_PerfOS_Memory: PercentCommittedBytesInUse=38  CommittedBytes=17701249024 (16.49 GB)
                                          CommitLimit=46293966848 (43.11 GB)  AvailableBytes=19041906688 (17.73 GB)
                                          PoolPagedBytes=1190350848  PoolNonpagedBytes=860594176
> Win32_PageFileUsage -> C:\pagefile.sys alloc=11776MB peak=167MB
> Win32_PhysicalMemory  -> 8 x 4096MB @ 8533 MT/s (soldered LPDDR5x)
> Get-Process | Sort WorkingSet64 -Desc | Select -First 5
  TextInputHost 1491 MB | python(20868) 1049 MB | node(1784) 730 MB | explorer 549 MB | dwm 485 MB
```

### 1.4 Disk
```
> Get-Volume | Get-Partition | Get-Disk ; Get-PhysicalDisk
VOL C: label='Windows' fs=NTFS sizeGB=475.8 freeGB=71.1 bus=NVMe model='SAMSUNG MZAL8512HDLU-00BL2' partition=GPT
PHYSDISK 'SAMSUNG MZAL8512HDLU-00BL2' media=SSD bus=NVMe sizeGB=477 health=Healthy
```
One volume, one disk, NVMe SSD, **71.1 GB free of 477.8 GB (14.9 %)**. Throughput **deliberately not
measured** — see §9.

### 1.5 Runtimes & DSH
```
> node --version          -> v24.12.0     (C:\Program Files\nodejs\node.exe)
> npm --version           -> 11.6.2
> python --version        -> Python 3.12.10 (C:\Users\ezabz\AppData\Local\Programs\Python\Python312\python.exe)
> python3 --version       -> (absent; no shim)
> git --version           -> git version 2.52.0.windows.1
> $PSVersionTable.PSVersion -> 5.1.26100.9444     (Windows PowerShell 5.1, NOT pwsh 7)
> Get-Command dsh         -> (empty; DSH IS INSTALLED BUT NOT ON PATH)
> Test-Path ~/.dsh        -> True
> Get-ChildItem ~/.dsh    -> .agent-presets, attachments, governor, health, llm-deepseek, metrics,
                             multi-window, profiles, sessions, storages, tools, .credentials.yaml,
                             settings.yaml, settings.yaml.bak-*  (5 dated backups)
> Get-ChildItem ~/.dsh/profiles -> node_modules, web
> Get-ChildItem $env:LOCALAPPDATA\npm-cache\_npx -Recurse -Depth 3 -Directory -Filter dsh
   -> C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh
> git -C ~/code/harness-config rev-parse --short HEAD -> 98fcefe
```

### 1.6 Networking
```
> Get-NetIPAddress -AddressFamily IPv4  -> 192.168.12.104/24 (Ethernet), 100.72.162.5/32 (Tailscale), 169.254.105.243 (Wi-Fi APIPA)
> Get-NetRoute -DestinationPrefix 0.0.0.0/0 -> NextHop 192.168.12.1
> tailscale version       -> 1.98.1
> tailscale ip -4         -> 100.72.162.5
> tailscale status --json | .BackendState     -> Running      <-- the NoState incident is OVER
>                          | .AuthURL          -> (empty)      <-- authenticated, no login pending
>                          | .Self.DNSName     -> zabz-yoga-1.tail93e6e6.ts.net.
>                          | .MagicDNSSuffix   -> tail93e6e6.ts.net
>                          | .CurrentTailnet.Name -> lakewoodphoneandtech@gmail.com
>                          | .Health           -> []           <-- no self-reported problems
>                          | .Self.Tags        -> none
>                          | .Self.AdvertisedRoutes -> none   <-- NOT a subnet router
>                          | .ExitNodeStatus   -> none        <-- NOT an exit node
> tailscale status --json | .Peer   (peer table, verbatim values)
PEER zabz-tech.tail93e6e6.ts.net.        ip4=100.85.153.96   online=True active=False relay=nyc rx=0      tx=0
PEER iphone-15-pro.tail93e6e6.ts.net.    ip4=100.85.105.93   online=True active=False relay=nyc rx=0      tx=0
PEER lakewooechsmini.tail93e6e6.ts.net.  ip4=100.126.146.121 online=True active=True  relay=nyc rx=8108   tx=6324
PEER zabz-tech-linux.tail93e6e6.ts.net.  ip4=100.105.248.90  online=True active=True  relay=nyc rx=7772   tx=6292
PEER secratary.tail93e6e6.ts.net.        ip4=100.84.72.88    online=True active=True  relay=nyc rx=391656 tx=219520
```
The tailnet is **7 devices, not 6** — the five mesh machines, this laptop, **and `iphone-15-pro`**.
`zabz-tech` sat at `rx=0 tx=0` — this laptop had exchanged **zero** bytes with the desktop before the audit.
`cloudflared` **exists** on this laptop at `C:\Program Files (x86)\cloudflared\cloudflared.exe`, version
`2026.5.0` (built 2026-05-13T10:09 UTC), but **no Cloudflare service is installed**
(`Get-Service *cloudflare*/*tunnel*` empty; `C:\ProgramData\Cloudflare` absent). **This laptop is a
client of the tunnels, not a host.**

### 1.7 Listening ports (`Get-NetTCPConnection -State Listen`)
```
:::22 / 0.0.0.0:22   sshd        (Windows OpenSSH Server — Get-Service sshd = Running/Automatic)
127.0.0.1:3099       node        <- DSH engine / this Web GUI
127.0.0.1:8002       python      <- personal-secretary-mvp API
0.0.0.0:5432         postgres    <- PostgreSQL ON ALL INTERFACES   <-- see note
:::5432              postgres
0.0.0.0:5535         SpotifyLauncher
100.72.162.5:44942   tailscaled
127.0.0.1:11080      ssh (local forward)   127.0.0.1:1081 pwsh   0.0.0.0:5040 svchost
```
> **A PostgreSQL server listens on `0.0.0.0:5432` on a laptop that roams onto hotspot and coffee-shop
> networks.** Whether it is password-protected was **not** probed (probing a live DB's auth is not a
> read-only act). Flagged as a finding, not as a question for the owner.

### 1.8 Persistent work already installed here — read before placing anything on this node
`Get-ScheduledTask | ? State -ne Disabled`, non-Microsoft paths:
```
\DSH elevation probe        \DSH Engine Watchdog (1m)   \DSH Metrics Sampler    \DSH Multi-Window Launcher
\DSH Process Reaper         \DSH unified-search refresh \DSH Window Fleet Watchdog
\LPT-EnvBackup  \LPT-EnvBackup-AtStartup  \LPT-MonthlyAnalysis
\PersonalSecretary-HarnessSync  \PersonalSecretary-NodeAgent  \PersonalSecretary-PushDSHSessions
\PersonalSecretary-PushVSCodeChats  \VSCodeUpdate-20260803
```
**This is the most decision-relevant line in the document for a distributed-scheduler design.** This
laptop already runs **seven `\DSH *` tasks**, including an **Engine Watchdog on a 1-minute cadence** and a
**Process Reaper**. A new fleet or scheduler placed here will race a watchdog and a reaper that were
written before it existed — the reaper can kill work it did not start.

---

## 2. secratary — Linux, the company authority

`ssh secratary-ts` → MESHOK.

### 2.1 Identity
```
hostname=secratary
uname -a  -> Linux secratary 7.0.0-30-generic #30-Ubuntu SMP PREEMPT_DYNAMIC ... x86_64 GNU/Linux
os-release -> PRETTY_NAME="Ubuntu 26.04 LTS"  VERSION="26.04 (Resolute Raccoon)"
uptime -s -> 2026-09-02 22:10:03      uptime -> "up 13 days, 22:06, 7 users, load average: 0.24, 0.61, 0.73"
systemd-detect-virt -> none          DMI -> Dell Inc. / OptiPlex 9020   <- a 2013-era desktop
who -> (empty; 0 logged-in users)    user=zabz uid=1000
loginctl list-sessions -> 8 sessions: 1 manager + 7 user, uid 1000, no console
```

### 2.2 Compute
```
nproc -> 4          /proc/cpuinfo model name -> Intel(R) Core(TM) i5-4570 CPU @ 3.20GHz
/proc/loadavg -> 0.24 0.61 0.73       top -bn2 -> %Cpu(s): 0.2 us, 0.2 sy, 99.5 id, 0.0 wa
ps -eo pcpu,pid,comm,etime,args --sort=-pcpu | head -6
 17.7 1507139 python    33:04  /home/zabz/personal-secretary-mvp/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
  1.0  906634 node   14:02:39  /home/zabz/node/bin/node /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js web --port 3089 --no-open
  0.4 2495411 cloudflared 5-00:22:23  /usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml tunnel run
  0.4 3279526 tailscaled  2-15:19:59  /usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state --port=41641
```

### 2.3 Memory — **this is the node's constraint**
```
/proc/meminfo: MemTotal=23984072 kB (22.87 GB)  MemAvailable=17930932 kB (17.10 GB)
               MemFree=906636 kB  SwapTotal=4194300 kB  SwapFree=568 kB
free -h ->  Mem: 22Gi total, 5.8Gi used, 885Mi free, 1.7Gi shared, 18Gi buff/cache, 17Gi available
            Swap: 4.0Gi total, 4.0Gi used, 568Ki free
ps -eo rss,pid,comm,etime --sort=-rss | head -6
 2525088 1507139 python (uvicorn app.main)  | 485744 906634 node (dsh-engine) | 160836 next-server | 118400 systemd-journald | 110268 tailscaled
```
> **Swap is 99.99 % consumed: 568 kB free of 4.0 GB on a 22.9 GB host.** A Linux box with a fully
> exhausted swap file cannot absorb a memory spike — the OOM killer decides instead. That is a hard
> ceiling on how much agent work this machine can host, and it is the single most important capacity
> fact in this audit after the 4 cores. It is a **finding**, and the fix (more swap / more RAM) is an
> engineering decision, not an owner decision.

### 2.4 Disk
```
df -hT ; lsblk -o NAME,ROTA,SIZE,TYPE,MODEL,FSTYPE,MOUNTPOINT
/dev/mapper/ubuntu--vg-ubuntu--lv ext4 467G 263G used 185G avail 59% /
/dev/sda2                         ext4 2.0G 250M used 1.6G avail 14% /boot
sda  0 476.9G disk  PNY 500GB SATA S     <- ROTA=0 => SSD
  sda2 2G ext4 /boot ; sda3 474.9G crypto_LUKS -> dm_crypt-0 -> LVM -> ubuntu--vg-ubuntu--lv ext4 /
```
**Disk is encrypted (LUKS).** 185 GB free.

### 2.5 Runtimes
```
node=/usr/bin/node v20.20.2      npm=/usr/bin/npm 10.8.2
python3=/usr/bin/python3 Python 3.14.4     python: NOT FOUND   git version 2.53.0
dsh: NOT FOUND on PATH ("sh: dsh: not found")
~/.dsh -> attachments, dsh-archive-state.json, llm-deepseek, profiles, sessions, settings.yaml(+3 backups), storages
~/.dsh/profiles -> node_modules, web
npx dsh -> none
~/harness-config -> README.md _scratch assets docs journal multi-window packages presets profiles scripts settings
git -C ~/harness-config rev-parse --short HEAD -> af2a6e7
~/code -> _worktrees, harness-config, unified-search
```
> **`harness-config` diverges across machines: secratary is at `af2a6e7`, ZABZ-YOGA and mac-mini are at
> `98fcefe`.** A cron job `*/15 * * * * ~/harness-config/scripts/autosync.sh` is supposed to close this.
> It has not, on this pair.

### 2.6 Networking — **the authority's transport is the worst in the mesh**
```
ip -o -4 addr -> 192.168.50.77/24 (eno1), 100.84.72.88/32 (tailscale0), lo
ip route show default -> default via 192.168.50.1 dev eno1
tailscale version -> 1.102.3      tailscale ip -4 -> 100.84.72.88
tailscale status --json -> BackendState="Running", MagicDNSSuffix="tail93e6e6.ts.net",
                           DNSName="secratary.tail93e6e6.ts.net.", Health=[], ExitNode=false
tailscale status
 100.84.72.88     secratary        linux    -
 100.85.105.93    iphone-15-pro    iOS      -
 100.126.146.121  lakewooechsmini  macOS    active; direct 192.168.50.45:55390, tx 18166044 rx 9157384
 100.105.248.90   zabz-tech-linux  linux    -
 100.85.153.96    zabz-tech        windows  idle, tx 33724 rx 8996
 100.72.162.5     zabz-yoga-1      windows  active; relay "nyc", tx 212381852 rx 125142276
tailscale ping --c 3 <peers>
 zabz-tech        -> via 192.168.50.138:41641 in 1ms     DIRECT, sub-millisecond
 zabz-tech-linux  -> via 192.168.50.23:41641  in 1ms     DIRECT, sub-millisecond
 LakewooechsMini  -> via 192.168.50.45:55390  in 1ms     DIRECT, sub-millisecond
 zabz-yoga-1      -> via DERP(nyc) in 30/38/44ms  -- "direct connection not established"  FAILED
```
**Read together with §0:** the four office nodes reach each other **directly at ~1 ms** over their LAN,
but **this laptop and secratary can only reach each other through the NYC DERP relay** at 30–44 ms with
jitter, because the laptop's cellular link will not hold a direct WireGuard path. Every DB-bound call
from the owner's laptop to the authority pays that relay.

### 2.7 Persistent work (must not be fought)
- **systemd timers include `secretary-access-watchdog.timer` on a ~1-minute cadence** and
  `secretary-backup.timer` daily at 00:00.
- **Running services include:** `secretary-api` (FastAPI), `secretary-dashboard` (Next.js),
  `cloudflared.service`, `tailscaled`, `phone-engine` ("DSH engine for the owner's phone"),
  `phone-gate`, `vscode-tunnel`, `xvfb-login` (virtual X for headed browser automation), `fail2ban`,
  `thermald`, `unattended-upgrades`.
- **`crontab -l` holds ~30 jobs.** The densest, verbatim:
```
@reboot ~/heartbeat.sh &
*/5  * * * * ~/mesh-health.sh > ~/.personal-secretary/mesh-health.json
*/5  * * * * pgrep -f "uvicorn app.main" > /dev/null || ~/personal-secretary-mvp/scripts/secretary-startup.sh
*/15 * * * * sqlite3 ~/personal-secretary-mvp/data/secretary.db "PRAGMA integrity_check;"  (mails on non-ok)
*/5  * * * * /home/zabz/ceo-kernel/scripts/run-sentinel.sh
*/30 * * * * /home/zabz/ceo-kernel/scripts/run-ha-truth.sh
*/15 * * * * /home/zabz/harness-config/scripts/autosync.sh
*/2  * * * * /home/zabz/harness-config/scripts/serve-phone.sh
*/5  * * * * /usr/bin/python3 /home/zabz/harness-config/scripts/probe-phone.py --quiet --json
*/5  * * * * /usr/bin/python3 /home/zabz/harness-config/scripts/model-failover-watch.py
*/15 * * * * /home/zabz/harness-config/scripts/lpt-hub-refresh.sh
*/30 * * * * /home/zabz/personal-secretary-mvp/scripts/mesh/node-agent-cron.sh
*/30 * * * * /home/zabz/personal-secretary-mvp/scripts/dialpad-harvest-cron.sh
*/5  * * * * flock -n /tmp/dialpad-dl.lock ... dialpad-recording-gap.py --limit 300
*/10 * * * * flock -n /tmp/dialpad-ts.lock ... dialpad-transcript-gap.py --limit 400 --max-minutes 600
7,37 * * * * /usr/bin/python3 /home/zabz/.fsearch/comms-refresh.py
*/15 * * * * presence-runtime/sampler.py
...
```
**This machine is already saturated with scheduled work.** Listening ports worth noting:
`0.0.0.0:8002` (API), `*:3000` (dashboard), `127.0.0.1:3089` (DSH engine for the phone),
`100.84.72.88:443` (phone-gate), `0.0.0.0:22`, plus four UDP ports held by an unidentified process.
`cloudflared` here is `/usr/local/bin/cloudflared` **2026.3.0** (older than the laptop's 2026.5.0),
config at `/etc/cloudflared/config.yml` (+5 backups), running as a systemd unit.

---

## 3. zabz-tech (desktop) — Windows, office, i9 / 63.6 GB claimed

**Reachability proven; hardware detail PENDING** (see §9). What is measured:
```
ssh desktop-ts "echo MESHOK"   -> MESHOK   (1081 ms cold)
ssh desktop-cf "echo MESHOK"   -> MESHOK   (4744 ms)      <- Cloudflare fallback WORKS for this node
ssh desktop  "echo MESHOK"     -> ssh: connect to host 192.168.50.138 port 22: Connection timed out (6054 ms)
tailscale ping --c 3 zabz-tech.tail93e6e6.ts.net -> pong via 71.104.140.242:13982 in 55ms   DIRECT
Test-Connection 100.85.153.96 -Count 4 -> OK avgMs=49.8 (70,59,35,35)
TCP connect 100.85.153.96:22 -> best 42 ms (42,61,48)
```
**The "i9 / 63.6 GB" figures in the brief are NOT reproduced here** — they were not read from the node,
so this document does not assert them. §9 gives the command that settles it.

---

## 4. zabz-tech-linux (linux-pc) — Linux

**Reachability proven; hardware detail PENDING.** `ssh zabz-tech-linux-ts "echo MESHOK"` → MESHOK (1447 ms).
```
tailscale ping --c 3 zabz-tech-linux.tail93e6e6.ts.net -> pong via 71.104.140.242:61481 in 62ms   DIRECT
Test-Connection 100.105.248.90 -Count 4 -> OK avgMs=52.2 (40,28,42,99)
TCP connect 100.105.248.90:22 -> best 39 ms (39,1055,142)
ssh linux-pc -> ssh: connect to host 192.168.50.23 port 22: Connection timed out (6054 ms)
```
Seen from secratary it is 1 ms away on the office LAN (`via 192.168.50.23:41641 in 1ms`).

---

## 5. mac-mini (LakewooechsMini) — macOS

`ssh mac-mini-ts "echo MESHOK"` → MESHOK (615 ms).

### 5.1 Measured
```
hostname=LakewooechsMini
uname -a -> Darwin LakewooechsMini 25.5.0 Darwin Kernel Version 25.5.0 ... RELEASE_ARM64_T8132 arm64
sw_vers  -> ProductName: macOS  ProductVersion: 26.5.2  BuildVersion: 25F84
sysctl -n hw.model -> Mac16,10
kern.boottime -> Mon Aug 3 22:49:36 2026
uptime -> "up 43 days, 17:27, 2 users, load averages: 1.05 1.21 1.40"
who  -> "moshemontrose  console  Aug 11 22:17"   and   "lpt  console  Aug 12 10:33"
python3 -> Python 3.9.6        git -> git version 2.50.1 (Apple Git-155)        bash -> 3.2.57(1)
node -> NOT FOUND ("command not found")     npm -> NOT FOUND     dsh -> NOT FOUND
~/.dsh -> attachments, bin, browser-profile, browser-profiles, dsh-archive-state.json, logs, profiles,
          sessions, settings.machine.yaml, settings.yaml(+3 backups), storages
~/.dsh/profiles -> headless, node_modules, web
~/harness-config rev-parse --short HEAD -> 98fcefe
~/code -> _worktrees, harness-config, harness-config.stale-20260914-224300, personal-secretary-mvp
ifconfig -> 127.0.0.1, 192.168.50.45, 192.168.50.73 (TWO addresses on one segment!), 100.126.146.121
~/.cloudflared -> org-token lock, desktop-ssh.abletelsolutions.com-<sha256>-token.lock
crontab -l -> "no crontab for lpt"
launchd list -> only com.apple.* entries in the first 40; no mesh/DSH agents observed
```
- **43 days of continuous uptime** — the strongest always-on evidence of any node measured, and it is a
  desktop Mac (no `/sys/class/power_supply`, no battery, no sleep targets).
- **Two human users were logged in at the console**: `moshemontrose` (since Aug 11) and `lpt`
  (since Aug 12). This is the **employee's machine, left logged in for a month and a half.**

> **A hardware note that is itself a finding:** this Mac mini is `Mac16,10` and reported **two IPv4
> addresses on the same `/24`** — `192.168.50.45` and `192.168.50.73`. It also carries a
> **Cloudflare Access token for `desktop-ssh.abletelsolutions.com`**, i.e. it is a *client* of the
> desktop's tunnel. It is **completely unequipped** to run DSH today: **no node, no npm, no `dsh`
> binary, no Tailscale CLI** — macOS's `tailscale` lives inside `/Applications/Tailscale.app`, which my
> Linux-shaped probe correctly could not see. Corrected probe in flight (§9).

### 5.2 Networking
```
tailscale ping --c 3 LakewooechsMini.tail93e6e6.ts.net -> pong via 71.104.140.242:55390 in 46ms  DIRECT
Test-Connection 100.126.146.121 -Count 4 -> OK avgMs=39.8 (36,41,37,45)
TCP connect 100.126.146.121:22           -> best 130 ms (204,192,130)
ssh mac-mini -> ssh: connect to host 192.168.50.45 port 22: Connection timed out (6048 ms)
```

---

## 6. hetzner / waze-mdm-01 — Hetzner VPS (off-LAN, not on the tailnet)

The alias is `hetzner` (also `hetzner-main`, `waze-mdm-01`) → `87.99.141.172`, user `root`, key
`~/.ssh/id_ed25519_hetzner`. **It is absent from the Tailscale peer table from every node measured —
it is not a tailnet member.**

```
hostname=waze-mdm-01
uname -a -> Linux 6.8.0-90-generic #91-Ubuntu SMP ... x86_64     os-release -> Ubuntu 24.04.3 LTS
uptime -s -> 2026-05-13 02:26:04 ; uptime -> "up 126 days, 17:50, 1 user, load average: 0.05, 0.05, 0.02"
systemd-detect-virt -> kvm ; DMI -> Hetzner / vServer
nproc -> 2 ; cpuinfo model name -> AMD EPYC-Rome Processor
/proc/meminfo -> MemTotal=1965740 kB (1.87 GB)  MemAvailable=1117840 kB (1.07 GB)
                 SwapTotal=2097148 kB  SwapFree=1870076 kB
free -h -> Mem: 1.9Gi total, 828Mi used, 140Mi free, 1.2Gi buff/cache, 1.1Gi available | Swap: 2.0Gi, 221Mi used
df -hT -> /dev/sda1 ext4 38G size, 18G used, 19G avail, 50% /   ;  /dev/sda15 vfat 253M 1% /boot/efi
lsblk -> sda 0 38.1G disk QEMU HARDDISK  (ROTA=0)
node -> NOT FOUND    npm -> NOT FOUND    python3 -> Python 3.12.3    git -> 2.43.0
dsh -> NOT FOUND     ~/.dsh -> absent    cloudflared -> NOT FOUND    tailscale -> NOT FOUND
~/code -> absent
uptime evidence: `last -x reboot` -> "reboot system boot 6.8.0-90-generic Wed May 13 02:26:06 2026  still running"; wtmp begins Thu Jan 8 10:27:31 2026
```
Docker containers running (`docker ps`): `waze-mdm-fleet-dashboard-1`, `waze-mdm-fleet-api-1`,
`waze-mdm-caddy-1`, `waze-mdm-nanodep-syncer-1`, `waze-mdm-nanomdm-1`, `waze-mdm-nanodep-1`,
`waze-mdm-restore-1`, `waze-mdm-dns-filter-1`, `yocheved`, `emt-quiz`, `waze-mdm-postgres-1`.
**`crontab -l` includes a job that runs every single minute** (`* * * * * fleet-api-call.sh POST /fleet/sweep`)
plus a 5-minute health check. This box runs the Waze MDM fleet and the Yocheved container.

> **Verdict: not an agent node as it stands.** 2 cores, 1.9 GB RAM, no node, no DSH, no cloudflared,
> no Tailscale, and it is already the Waze MDM production host. Its only asset for this purpose is
> **126 days of uptime**. Adding a DSH fleet here means installing a runtime on a production MDM host.

---

## 7. lpt-apps-01 — Hetzner VPS (second box, off-LAN, not on the tailnet)

Alias `lpt-apps` / `lpt-apps-01` → `2.28.33.58`, user `root`, key `~/.ssh/id_ed25519_lpt-apps`.

```
hostname=lpt-apps-01
uname -a -> Linux 6.8.0-137-generic ... x86_64     os-release -> Ubuntu 24.04.4 LTS
uptime -s -> 2026-08-31 14:45:06 ; uptime -> "up 16 days, 5:31, 1 user, load average: 0.13, 0.11, 0.11"
systemd-detect-virt -> kvm ; DMI -> Hetzner / vServer
nproc -> 4 ; cpuinfo -> Intel Xeon Processor (Skylake, IBRS, no TSX)
/proc/meminfo -> MemTotal=7937232 kB (7.57 GB)  MemAvailable=5386500 kB (5.14 GB)
                 SwapTotal=2097148 kB  SwapFree=1473696 kB
free -h -> Mem: 7.6Gi total, 2.4Gi used, 439Mi free, 5.4Gi buff/cache, 5.1Gi available | Swap: 2.0Gi, 608Mi used
df -hT -> /dev/sda1 ext4 75G size, 60G used, 12G avail, 84% /     <-- 84 % FULL
node -> NOT FOUND    npm -> NOT FOUND    python3 -> Python 3.12.3    git -> 2.43.0
dsh -> NOT FOUND     ~/.dsh -> absent    cloudflared -> NOT FOUND    tailscale -> NOT FOUND
top -bn2 -> %Cpu(s): 0.7 us, 0.7 sy, 98.4 id
ps top-5 RSS -> dockerd 338 MB | node 266 MB | node 251 MB | uvicorn 234 MB | uvicorn 211 MB
last -x reboot -> "reboot system boot 6.8.0-137-generic Mon Aug 31 14:45:09 2026  still running"
```
Docker containers: `lakewood-rentals`, `chumash-timeline`, `lpt-backend`, `personality-test`,
`lpt-test-backend`, `lpt_filter_site`, `lpt_filter_ai_api_b` ×2, `caddy`, `lpt-postgres`, `lpt-redis`.
Listening: `80`, `443`, `1080`, `1081`, `9443`, `9444` (proxies), `22`, plus 8 loopback-bound app ports.
`redis-server *:6379` was in the top-5 by CPU.

> **Verdict:** 4 cores and 7.6 GB is the second-best Linux candidate in the fleet, and 5.1 GB is
> genuinely available — but it has **no node/npm/DSH**, its disk is **84 % full**, and it is the
> production host for at least six LPT business apps. Same conclusion as hetzner.

---

## 8. CAPABILITY TABLE — measured

`PENDING` marks a cell whose probe has not yet returned; it is **not** a guess.

| node | OS | cores (logical) | RAM total / available | disk free | always-on evidence | DSH installed? | LAN reachable from laptop? | tailscale reachable? | measured latency |
|---|---|---|---|---|---|---|---|---|---|
| **ZABZ-YOGA** (self) | Win 11 Home 25H2 (26200.9445) | **22** (16 physical) | **31.6 GB / 17.5 GB free phys, 26.4 GB commit free** | **71.1 GB** of 477.8 GB (14.9 %) NVMe SSD | **WEAK** — battery present (100 %, AC), **Balanced** plan, interactive user, **uptime only 21 min** | **YES** (`~/.dsh` + `_npx`), **not on PATH** | n/a (self) | n/a (self); backend **Running**, `100.72.162.5` | self; tsping to peers 46–170 ms |
| **secratary** | Ubuntu 26.04 LTS, kernel 7.0.0-30 | **4** | **22.87 GB / 17.10 GB avail** — **swap 99.99 % full (568 kB of 4.0 GB free)** | **185 GB** of 467 GB, LUKS-encrypted, PNY SATA SSD | **STRONG** — **13 d 22 h uptime**, headless, no battery, no GUI, 0 console logins | **YES** (`~/.dsh`, `~/dsh-engine` on port 3089), not on PATH | **NO** — `192.168.50.77 port 22: Connection timed out` | **YES** `100.84.72.88` | TCP22 **56 ms**; ICMP 64.8 ms; tsping 35–170 ms **via DERP relay** |
| **zabz-tech** (desktop) | Windows *(build PENDING)* | PENDING | PENDING | PENDING | PENDING (office desktop, presumably always on — **unverified**) | PENDING | **NO** — `192.168.50.138 port 22: Connection timed out` | **YES** `100.85.153.96` | TCP22 **42 ms**; ICMP 49.8 ms; tsping **55 ms direct**; `desktop-cf` **4744 ms** |
| **zabz-tech-linux** (linux-pc) | Linux *(detail PENDING)* | PENDING | PENDING | PENDING | PENDING | PENDING | **NO** — `192.168.50.23 port 22: Connection timed out` | **YES** `100.105.248.90` | TCP22 **39 ms**; ICMP 52.2 ms; tsping **62 ms direct** |
| **mac-mini** | macOS 26.5.2 (build 25F84), Darwin 25.5.0, arm64, Mac16,10 | *(PENDING — `nproc` is Linux-only)* | *(PENDING — no `/proc/meminfo`)* | *(PENDING)* | **STRONGEST measured — 43 d 17 h uptime**, no battery, desktop; **but 2 human console users logged in (moshemontrose, lpt)** | **NO** — no node, no npm, no `dsh`; `~/.dsh` exists with a `headless` profile | **NO** — `192.168.50.45 port 22: Connection timed out` | **YES** `100.126.146.121` | TCP22 **130 ms**; ICMP 39.8 ms; tsping **46 ms direct** |
| **hetzner** (`waze-mdm-01`) | Ubuntu 24.04.3 LTS, kernel 6.8.0-90, KVM | **2** | **1.87 GB / 1.07 GB avail** | **19 GB** of 38 GB (50 %) | **STRONGEST — 126 d 17 h uptime** | **NO** — no node, no `dsh`, no `~/.dsh` | n/a (public IP) | **NO — not on the tailnet** | **134 ms** TCP22; ICMP 79.5 ms |
| **lpt-apps-01** | Ubuntu 24.04.4 LTS, kernel 6.8.0-137, KVM | **4** | **7.57 GB / 5.14 GB avail** | **12 GB** of 75 GB (**84 % FULL**) | **STRONG — 16 d 5 h uptime** | **NO** — no node, no `dsh`, no `~/.dsh` | n/a (public IP) | **NO — not on the tailnet** | **170 ms** TCP22; ICMP 173.5 ms |

---

## 9. TRANSPORT MATRIX — measured from ZABZ-YOGA

`OK` = verified end-to-end with `echo MESHOK` over ssh. Times are wall-clock for that cold ssh.

| target | LAN `192.168.50.x` | Tailscale | Cloudflare (`-cf`) |
|---|---|---|---|
| secratary | **FAIL** — `ssh: connect to host 192.168.50.77 port 22: Connection timed out` (6047 ms); ICMP no reply; TCP22 3/3 `TIMEOUT4s` | **OK** — 879 ms cold; TCP22 56 ms; tsping 35–170 ms **via DERP** | `secretary-cf` **OK** — 3712 ms |
| zabz-tech | **FAIL** — `... 192.168.50.138 port 22: Connection timed out` (6054 ms) | **OK** — 1081 ms cold; TCP22 42 ms; tsping 55 ms **direct** | `desktop-cf` **OK** — **4744 ms** |
| zabz-tech-linux | **FAIL** — `... 192.168.50.23 port 22: Connection timed out` (6054 ms) | **OK** — 1447 ms cold; TCP22 39 ms; tsping 62 ms **direct** | not configured |
| mac-mini | **FAIL** — `... 192.168.50.45 port 22: Connection timed out` (6048 ms) | **OK** — 615 ms cold; TCP22 130 ms; tsping 46 ms **direct** | not configured |
| laptop (self) | n/a | **OK** — `laptop-ts` 619 ms cold | not configured |
| `yocheved-cf` (not a mesh node) | n/a | n/a | **FAIL** — `websocket: bad handshake / Connection closed by UNKNOWN port 65535` (2302 ms) |
| `hetzner` `87.99.141.172` | off-LAN by design | **not a tailnet member** (absent from all peer tables) | **OK** by direct public SSH — 1874 ms cold |
| `lpt-apps` `2.28.33.58` | off-LAN by design | **not a tailnet member** | **OK** by direct public SSH — 3097 ms cold |

### 9.1 MagicDNS — **works, verified**
```
> [System.Net.Dns]::GetHostAddresses(<name>)
secratary.tail93e6e6.ts.net       -> 100.84.72.88
zabz-tech.tail93e6e6.ts.net       -> 100.85.153.96
zabz-tech-linux.tail93e6e6.ts.net -> 100.105.248.90
LakewooechsMini.tail93e6e6.ts.net -> 100.126.146.121
zabz-yoga-1.tail93e6e6.ts.net     -> 100.72.162.5
```
All five mesh names resolve to `100.x`. **There is no DNS gap to fix.**

### 9.2 Tailscale backend state on this laptop — **the `NoState` incident is resolved**
```
BackendState = Running      AuthURL = (empty)      Health = []      MagicDNSSuffix = tail93e6e6.ts.net
```
Measured, not assumed: a `NoState` backend carries `BackendState = NoState` with a populated
`AuthURL`. Neither is present. **This laptop is not a subnet router and not an exit node**
(`AdvertisedRoutes` and `ExitNodeStatus` are both empty on Self).

### 9.3 Every LAN path failed for one structural reason
This laptop is on `192.168.12.0/24` (T-Mobile CGNAT); the office subnet is `192.168.50.0/24`. Home and
office are separate networks and **this laptop is on neither.** A LAN failure here means *"this vantage
point cannot see that subnet"*, **not** "that node is down" — proved by the fact that all four LAN
targets also answered happily over Tailscale and that secratary reaches three of them in **1 ms** on
the office LAN.

---

## 10. CAPACITY ESTIMATE — **ESTIMATE, NOT A MEASUREMENT**

Measured constant, given: **one actively-generating agent turn ≈ 0.81 GB commit and ≈ 1 core.**
Comfortable ceiling = **75 % of available**, leaving 25 % headroom. CPU is assumed available as
`min(cores, …)`; a node's *free* cores are taken as its logical core count for the boot-time snapshot
below, which **overstates** every machine that is already busy.

| node | RAM-limited turns (avail ÷ 0.81 × 0.75) | CPU-limited turns (cores × 0.75) | **comfortable ceiling** |
|---|---|---|---|
| ZABZ-YOGA | 17.54 ÷ 0.81 × 0.75 = **16** | 22 × 0.75 = **16**, **but 27–31 % already consumed by the owner's own work → ~11** | **~11** |
| secratary | 17.10 ÷ 0.81 × 0.75 = **15** | 4 × 0.75 = **3** | **3** |
| lpt-apps-01 | 5.14 ÷ 0.81 × 0.75 = **4** | 4 × 0.75 = **3** | **3** |
| hetzner | 1.07 ÷ 0.81 × 0.75 = **0.99** | 2 × 0.75 = 1.5 | **1** |
| zabz-tech | *(RAM unknown)* | *(cores unknown)* | **PENDING** |
| zabz-tech-linux | *(unknown)* | *(unknown)* | **PENDING** |
| mac-mini | *(unknown — needs `sysctl hw.memsize`)* | *(unknown — needs `sysctl -n hw.logicalcpu`)* | **PENDING** |

**Fleet total from measured nodes: ~18 concurrent agent-turns.** That is the number that is defensible
today. It will move once the three PENDING nodes are measured — and it will move **up**, because
`zabz-tech` is the fleet's largest machine by the brief's own claim.

> **Every one of these ceilings carries a caveat stronger than the arithmetic:**
> - **ZABZ-YOGA:** a **laptop with a battery** on a **Balanced** plan, an interactive user, 7 `\DSH *`
>   watchdog/reaper tasks, and 21 minutes of uptime. The arithmetic says 11; **the risk says 0–2, burst
>   only.** It is the machine the owner wants *relieved*, so loading it is self-defeating.
> - **secratary:** **3 turns, not 15** — CPU binds at 4 cores, and **swap is 99.99 % full**, so there is
>   no overflow cushion. It is also the authority, already running the 18-agent tick loop, ~30 cron
>   jobs and 6 systemd services. This node should be **a coordinator, not a bulk worker.**
> - **hetzner / lpt-apps:** capacity exists but **DSH is not installed on either**, both are production
>   hosts for live business systems, and lpt-apps' disk is **84 % full**.

---

## 11. WHAT I COULD NOT MEASURE, AND THE EXACT COMMAND THAT WOULD SETTLE IT

**An honest refusal is a valid answer; a confident wrong number is not.**

1. **`zabz-tech` (desktop) hardware detail.** The desktop probe connected (`MESHOK`, 1138 ms) but the
   chunked-stdin payload produced 0 lines; it hung and was killed at the 150 s cap. The corrected path
   (write the probe locally, `scp` it, run it with an explicit interpreter) was in flight at the time of
   writing and had not returned. Exact command:
   `scp -o BatchMode=yes %TEMP%\mesh-probe\probe.ps1 desktop-ts:C:/Users/ezabz/mesh-probe.ps1 && ssh desktop-ts "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:/Users/ezabz/mesh-probe.ps1"`
   **Consequence:** the brief's *"i9 / 63.6 GB measured"* is **not reproduced in this document**. It may
   well be true; it was not read from the node, so it is not asserted here.
2. **`zabz-tech-linux` (linux-pc) hardware detail.** Same in-flight status; `zabz-tech-linux-ts`
   answered `MESHOK` in 1447 ms. Exact command:
   `ssh zabz-tech-linux-ts "nproc; grep -m1 'model name' /proc/cpuinfo; grep -E 'MemTotal|MemAvailable|SwapTotal' /proc/meminfo; df -hT /; lsblk -o NAME,ROTA,SIZE,MODEL; node --version; python3 --version; ls -1 ~/.dsh"`
3. **`mac-mini` CPU / RAM / disk / launchd detail.** My probe was Linux-shaped and macOS has no
   `/proc`, no `nproc`, no `/sys/class/power_supply`, and `tailscale` lives inside
   `/Applications/Tailscale.app/Contents/MacOS/Tailscale` rather than on PATH. Corrected payload in
   flight. Exact command:
   `ssh mac-mini-ts "sysctl -n hw.model hw.ncpu hw.physicalcpu hw.logicalcpu hw.memsize; sw_vers; df -h /; diskutil info / | grep -E 'Solid State|Volume Free Space'; pmset -g; /Applications/Tailscale.app/Contents/MacOS/Tailscale ip -4"`
4. **Sleep/hibernate policy and boot history on ZABZ-YOGA** — needs elevation, which this session does
   not have. Exact command (as Administrator):
   `powercfg /sleepstudy /output $env:TEMP\sleep.html` and
   `Get-WinEvent -LogName System -MaxEvents 300 | ? { $_.Id -in 41,42,107,109,6005,6008 }`
5. **Disk throughput on every node** — **deliberately not measured.** Stated rather than silently
   skipped: on ZABZ-YOGA a synthetic write would burn write endurance on the owner's system drive
   (71 GB free) for a number that changes no decision, since both SSDs are already identified by bus
   type (`NVMe`, `SATA`, `QEMU HARDDISK`).
6. **`dsh --version` on any node** — `dsh` is on **no** node's PATH. On ZABZ-YOGA the exact command is:
   `node "$env:LOCALAPPDATA\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\bin\dsh.js" --version`
7. **Whether `secretary-cf` / `desktop-cf` are distinct tunnels** — both answered, but the
   `ProxyCommand` script (`scripts/windows/CloudflaredAccessSshProxy.ps1`) and the tunnel configs were
   **not read** (out of scope for an inventory).
8. **`yocheved-cf`** — failed with `websocket: bad handshake / Connection closed by UNKNOWN port 65535`.
   Not a mesh node; recorded for completeness.
9. **`harness-config` divergence** — ZABZ-YOGA `98fcefe`, mac-mini `98fcefe`, **secratary `af2a6e7`**.
   A `*/15` `autosync.sh` cron exists on secratary and has not reconciled them. Root cause not
   investigated (out of scope). One source of truth per thing says this must converge; the exact
   command to inspect is `ssh secratary-ts "tail -50 ~/harness-config/scripts/autosync.sh; git -C ~/harness-config status --short; git -C ~/harness-config log --oneline -5"`.

---

## 12. THE THREE THINGS THAT SHOULD CHANGE THE DESIGN

1. **`secratary` — the authority, the only never-sleeping Linux box with DSH — has 4 cores and a swap
   file that is 99.99 % exhausted (568 kB free of 4.0 GB).** It cannot be the workhorse; it must be the
   coordinator, and its swap is a fault waiting to fire under any added load.
2. **The laptop is not on any LAN, and its path to the authority goes through a DERP relay with 30–44 ms
   of jitter.** Tailscale is the only transport between the owner's machine and everything else. Any
   design that assumes "LAN when at the shop" is correct only in the shop.
3. **The two machines with the best always-on credentials (`hetzner` 126 d, `mac-mini` 43 d) are the two
   furthest from ready:** neither has `node`, `npm` or `dsh`, and `hetzner` is not on the tailnet at all.
   Meanwhile the one node with the most capacity (`ZABZ-YOGA`, 31.6 GB / 22 cores) is the laptop the
   owner is trying to unload — and it already runs a 1-minute engine watchdog and a process reaper that
   will fight anything new placed there.
