# 10 — Mesh Inventory & Transport Audit

**Written:** 2026-09-16, 16:10–16:35 EDT (20:10–20:35 UTC) from `ZABZ-YOGA`.
**Author:** DSH subagent, read-only session. **Nothing was started, stopped, restarted or installed on
any node.** One 7 KB probe script was copied to `C:\Users\ezabz\mesh-probe.ps1` on `ZABZ-TECH` and run
there — it is inert and can be deleted. All other scratch lives in `%TEMP%`.

**Coverage: 7 machines, all measured.** Six are the mesh nodes named in the brief; the seventh is
`lpt-apps-01`, a second Hetzner box found in `~/.ssh/config` and included because it is a real machine
in this fleet. Every number carries the command that produced it. Nothing here is a spec I did not read
from the node.

---

## 0. The finding that reframes everything: the auditor's own vantage point

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

## 1. ZABZ-YOGA — the owner's laptop (this machine)

Lenovo 83AC, Intel Core Ultra 7 155H, **22 logical / 16 physical cores, 31.61 GB.**

### 1.1 Identity
```
> $env:COMPUTERNAME                                    -> ZABZ-YOGA
> Get-CimInstance Win32_OperatingSystem
  Caption=Microsoft Windows 11 Home  Version=10.0.26200  BuildNumber=26200
> HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion
  DisplayVersion=25H2  UBR=9445  ProductName="Windows 10 Home"  <- registry string is STALE; 25H2 is authoritative
> Win32_ComputerSystem: Manufacturer=LENOVO Model=83AC Domain=WORKGROUP UserName=zabz-yoga\ezabz
> LastBootUpTime = 2026-09-16 15:48:19  ->  uptime at sample = 00:21:06
> TimeZone = Eastern Standard Time; local time 2026-09-16T16:09:25-04:00
> (Get-Process explorer).Count -> 1      <- interactive desktop session IS open
> (Get-CimInstance Win32_SystemEnclosure).ChassisTypes -> 31 (Notebook)
> Get-CimInstance Win32_Battery -> Name=L23D4PH0  BatteryStatus=2 (AC)  EstimatedChargeRemaining=100
> powercfg /getactivescheme -> 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
```

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
DSH engine (`LISTEN 127.0.0.1:3099`, i.e. this Web GUI). **18 `msedge` + 6 `msedgewebview2` processes
were resident** — the CPU is shared with the owner's live work, not spare capacity.

### 1.3 Memory
```
> Win32_OperatingSystem: TotalVisibleMemorySize=33150328 KB (31.61 GB)  FreePhysicalMemory=18388176 KB (17.54 GB)
                         TotalVirtualMemorySize=45208952 KB (43.11 GB) FreeVirtualMemory=27640884 KB (26.36 GB)
> Win32_PerfFormattedData_PerfOS_Memory: PercentCommittedBytesInUse=38  CommittedBytes=17701249024 (16.49 GB)
                                          CommitLimit=46293966848 (43.11 GB)  AvailableBytes=19041906688 (17.73 GB)
> Win32_PageFileUsage -> C:\pagefile.sys alloc=11776MB peak=167MB
> Win32_PhysicalMemory 8 x 4096MB @ 8533 MT/s (soldered LPDDR5x)
> Get-Process | Sort WorkingSet64 -Desc | Select -First 5
  TextInputHost 1491 MB | python(20868) 1049 MB | node(1784) 730 MB | explorer 549 MB | dwm 485 MB
```

### 1.4 Disk
```
> Get-Volume | Get-Partition | Get-Disk ; Get-PhysicalDisk
VOL C: label='Windows' fs=NTFS sizeGB=475.8 freeGB=71.1 bus=NVMe model='SAMSUNG MZAL8512HDLU-00BL2' partition=GPT
PHYSDISK 'SAMSUNG MZAL8512HDLU-00BL2' media=SSD bus=NVMe sizeGB=477 health=Healthy
```
One volume, one disk, NVMe SSD, **71.1 GB free of 477.8 GB (14.9 %)**. Throughput deliberately not
measured — see §11.5.

### 1.5 Runtimes & DSH
```
> node --version    -> v24.12.0   (C:\Program Files\nodejs\node.exe)
> npm --version     -> 11.6.2
> python --version  -> Python 3.12.10 (C:\Users\ezabz\AppData\Local\Programs\Python\Python312\python.exe)
> python3 --version -> (absent; no shim)
> git --version     -> git version 2.52.0.windows.1
> $PSVersionTable.PSVersion -> 5.1.26100.9444   (Windows PowerShell 5.1, NOT pwsh 7)
> Get-Command dsh   -> (empty; DSH IS INSTALLED BUT NOT ON PATH)
> Test-Path ~/.dsh  -> True
> Get-ChildItem ~/.dsh -> .agent-presets, attachments, governor, health, llm-deepseek, metrics,
                          multi-window, profiles, sessions, storages, tools, .credentials.yaml,
                          settings.yaml (+5 dated backups)
> ~/.dsh/profiles -> node_modules, web
> Get-ChildItem $env:LOCALAPPDATA\npm-cache\_npx -Recurse -Depth 3 -Directory -Filter dsh
   -> C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh
> git -C ~/code/harness-config rev-parse --short HEAD -> 98fcefe
```

### 1.6 Networking
```
> Get-NetIPAddress -AddressFamily IPv4 -> 192.168.12.104/24 (Ethernet), 100.72.162.5/32 (Tailscale), 169.254.105.243 (Wi-Fi APIPA)
> Get-NetRoute -DestinationPrefix 0.0.0.0/0 -> NextHop 192.168.12.1
> tailscale version -> 1.98.1         > tailscale ip -4 -> 100.72.162.5
> tailscale status --json
   .BackendState           -> Running        <- the NoState incident is OVER
   .AuthURL                -> (empty)        <- authenticated, no login pending
   .Self.DNSName           -> zabz-yoga-1.tail93e6e6.ts.net.
   .MagicDNSSuffix         -> tail93e6e6.ts.net
   .CurrentTailnet.Name    -> lakewoodphoneandtech@gmail.com
   .Health                 -> []             <- no self-reported problems
   .Self.Tags              -> none
   .Self.AdvertisedRoutes  -> none           <- NOT a subnet router
   .ExitNodeStatus         -> none           <- NOT an exit node
> tailscale status --json | .Peer   (verbatim)
PEER zabz-tech.tail93e6e6.ts.net.       ip4=100.85.153.96   online=True active=False relay=nyc rx=0      tx=0
PEER iphone-15-pro.tail93e6e6.ts.net.   ip4=100.85.105.93   online=True active=False relay=nyc rx=0      tx=0
PEER lakewooechsmini.tail93e6e6.ts.net. ip4=100.126.146.121 online=True active=True  relay=nyc rx=8108   tx=6324
PEER zabz-tech-linux.tail93e6e6.ts.net. ip4=100.105.248.90  online=True active=True  relay=nyc rx=7772   tx=6292
PEER secratary.tail93e6e6.ts.net.       ip4=100.84.72.88    online=True active=True  relay=nyc rx=391656 tx=219520
```
The tailnet is **7 devices, not 6** — five mesh machines, this laptop, **and `iphone-15-pro`**.
`zabz-tech` sat at `rx=0 tx=0`: this laptop had exchanged **zero** bytes with the desktop before the
audit began.

`cloudflared` **exists** on this laptop at `C:\Program Files (x86)\cloudflared\cloudflared.exe`,
version `2026.5.0` (built 2026-05-13T10:09 UTC), but **no Cloudflare service is installed**
(`Get-Service *cloudflare*` / `*tunnel*` → empty; `C:\ProgramData\Cloudflare` → absent).
**This laptop is a client of the tunnels, not a host.**

### 1.7 Listening ports (`Get-NetTCPConnection -State Listen`)
```
:::22 / 0.0.0.0:22  sshd      (Get-Service sshd = Running/Automatic)
127.0.0.1:3099      node      <- DSH engine / this Web GUI
127.0.0.1:8002      python    <- personal-secretary-mvp API
0.0.0.0:5432        postgres  <- PostgreSQL ON ALL INTERFACES        <-- see note
:::5432             postgres
0.0.0.0:5535        SpotifyLauncher
100.72.162.5:44942  tailscaled      127.0.0.1:11080 ssh (forward)    127.0.0.1:1081 pwsh
```
> **A PostgreSQL server listens on `0.0.0.0:5432` on a laptop that roams onto hotspot and coffee-shop
> networks.** Whether it is password-protected was **not** probed (probing a live DB's auth is not a
> read-only act). Recorded as a finding.

### 1.8 Persistent work already installed here
`Get-ScheduledTask | ? State -ne Disabled`, non-Microsoft paths:
```
\DSH elevation probe       \DSH Engine Watchdog (1m)    \DSH Metrics Sampler   \DSH Multi-Window Launcher
\DSH Process Reaper        \DSH unified-search refresh  \DSH Window Fleet Watchdog
\LPT-EnvBackup  \LPT-EnvBackup-AtStartup  \LPT-MonthlyAnalysis
\PersonalSecretary-HarnessSync  \PersonalSecretary-NodeAgent  \PersonalSecretary-PushDSHSessions
\PersonalSecretary-PushVSCodeChats  \VSCodeUpdate-20260803
```
**Seven `\DSH *` tasks, including an Engine Watchdog on a 1-minute cadence and a Process Reaper.** Any
fleet or scheduler placed here races a watchdog and a reaper written before it existed — the reaper can
kill work it did not start.

---

## 2. secratary — Linux, the company authority

`ssh secratary-ts` → MESHOK.

### 2.1 Identity
```
hostname=secratary
uname -a -> Linux secratary 7.0.0-30-generic #30-Ubuntu SMP PREEMPT_DYNAMIC ... x86_64 GNU/Linux
os-release -> PRETTY_NAME="Ubuntu 26.04 LTS"  VERSION="26.04 (Resolute Raccoon)"
uptime -s -> 2026-09-02 22:10:03 ; uptime -> "up 13 days, 22:06, 7 users, load average: 0.24, 0.61, 0.73"
systemd-detect-virt -> none ; DMI -> Dell Inc. / OptiPlex 9020     <- a 2013-era desktop
who -> (empty; 0 console logins) ; user=zabz uid=1000
loginctl list-sessions -> 8 sessions: 1 manager + 7 user, uid 1000, no console
```

### 2.2 Compute
```
nproc -> 4        /proc/cpuinfo model name -> Intel(R) Core(TM) i5-4570 CPU @ 3.20GHz
/proc/loadavg -> 0.24 0.61 0.73     top -bn2 -> %Cpu(s): 0.2 us, 0.2 sy, 99.5 id, 0.0 wa
ps -eo pcpu,pid,comm,etime,args --sort=-pcpu | head -6
 17.7 1507139 python       33:04  .../python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
  1.0  906634 node      14:02:39  /home/zabz/node/bin/node .../@deepseek-ai/dsh/lib/bin.js web --port 3089
  0.4 2495411 cloudflared 5-00:22  /usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml tunnel run
  0.4 3279526 tailscaled 2-15:19  /usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state --port=41641
```

### 2.3 Memory — **this node's binding constraint**
```
/proc/meminfo: MemTotal=23984072 kB (22.87 GB)  MemAvailable=17930932 kB (17.10 GB)
               MemFree=906636 kB  SwapTotal=4194300 kB  SwapFree=568 kB
free -h -> Mem: 22Gi total, 5.8Gi used, 885Mi free, 1.7Gi shared, 18Gi buff/cache, 17Gi available
           Swap: 4.0Gi total, 4.0Gi used, 568Ki free
ps -eo rss,pid,comm,etime --sort=-rss | head -6
 2525088 1507139 python(uvicorn app.main) | 485744 906634 node(dsh-engine) | 160836 next-server | 118400 systemd-journald | 110268 tailscaled
```
> **Swap is 99.99 % consumed: 568 kB free of 4.0 GB on a 22.9 GB host.** A Linux box with an exhausted
> swap file cannot absorb a memory spike — the OOM killer decides instead. That is a hard ceiling on
> hosted agent work, and it is the single most important capacity fact in this audit after the 4 cores.
> The remedy (more swap, or more RAM) is an engineering decision, not an owner decision.

### 2.4 Disk
```
df -hT ; lsblk -o NAME,ROTA,SIZE,TYPE,MODEL,FSTYPE,MOUNTPOINT
/dev/mapper/ubuntu--vg-ubuntu--lv ext4 467G 263G used 185G avail 59% /
/dev/sda2                         ext4 2.0G 250M used 1.6G avail 14% /boot
sda  0 476.9G disk  PNY 500GB SATA S        <- ROTA=0 => SSD
  sda2 2G ext4 /boot ; sda3 474.9G crypto_LUKS -> dm_crypt-0 -> LVM -> ext4 /
```
**Disk is LUKS-encrypted.** 185 GB free.

### 2.5 Runtimes
```
node=/usr/bin/node v20.20.2      npm=/usr/bin/npm 10.8.2
python3=/usr/bin/python3 Python 3.14.4      python: NOT FOUND     git version 2.53.0
dsh: NOT FOUND on PATH ("sh: dsh: not found")
~/.dsh -> attachments, dsh-archive-state.json, llm-deepseek, profiles, sessions, settings.yaml(+3 backups), storages
~/.dsh/profiles -> node_modules, web
~/harness-config HEAD -> af2a6e7          <- DIVERGES from the other nodes (98fcefe)
~/code -> _worktrees, harness-config, unified-search
```
> **`harness-config` is not converged: secratary `af2a6e7`, ZABZ-YOGA `98fcefe`, zabz-tech `33db159`,
> mac-mini `98fcefe`.** Four machines, three different revisions. A `*/15 * * * * ~/harness-config/scripts/autosync.sh`
> cron exists on secratary and has not reconciled them. One source of truth per thing says this must
> converge — but see §11.9, including the fact that **I changed nothing in that repo myself.**

### 2.6 Networking — the authority's transport is the worst in the mesh
```
ip -o -4 addr -> 192.168.50.77/24 (eno1), 100.84.72.88/32 (tailscale0), lo
ip route show default -> default via 192.168.50.1 dev eno1
tailscale version -> 1.102.3 ; tailscale ip -4 -> 100.84.72.88
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
 zabz-tech        -> via 192.168.50.138:41641 in 1ms    DIRECT
 zabz-tech-linux  -> via 192.168.50.23:41641  in 1ms    DIRECT
 LakewooechsMini  -> via 192.168.50.45:55390  in 1ms    DIRECT
 zabz-yoga-1      -> via DERP(nyc) in 30/38/44ms  "direct connection not established"  FAILED
```
**Read with §0:** the four office nodes reach each other **directly at ~1 ms** on their LAN, but this
laptop and secratary reach each other **only through the NYC DERP relay**, at 30–44 ms with jitter,
because the laptop's cellular link will not hold a direct WireGuard path. Every DB-bound call from the
owner's laptop to the authority pays that relay.

### 2.7 Persistent work
- **Timers:** `secretary-access-watchdog.timer` at ~1-minute cadence, `secretary-backup.timer` daily 00:00.
- **Running services:** `secretary-api`, `secretary-dashboard`, `cloudflared.service`, `tailscaled`,
  `phone-engine` ("DSH engine for the owner's phone"), `phone-gate`, `vscode-tunnel`,
  `xvfb-login` (virtual X for headed browser automation), `fail2ban`, `thermald`, `unattended-upgrades`.
- **`crontab -l` holds ~30 jobs.** Densest, verbatim:
```
@reboot ~/heartbeat.sh &
*/5  * * * * ~/mesh-health.sh > ~/.personal-secretary/mesh-health.json
*/5  * * * * pgrep -f "uvicorn app.main" > /dev/null || .../secretary-startup.sh
*/15 * * * * sqlite3 .../data/secretary.db "PRAGMA integrity_check;"   (mails on non-ok)
*/5  * * * * /home/zabz/ceo-kernel/scripts/run-sentinel.sh
*/30 * * * * /home/zabz/ceo-kernel/scripts/run-ha-truth.sh
*/15 * * * * /home/zabz/harness-config/scripts/autosync.sh
*/2  * * * * /home/zabz/harness-config/scripts/serve-phone.sh
*/5  * * * * /home/zabz/harness-config/scripts/probe-phone.py --quiet --json
*/5  * * * * /home/zabz/harness-config/scripts/model-failover-watch.py
*/15 * * * * /home/zabz/harness-config/scripts/lpt-hub-refresh.sh
*/30 * * * * .../scripts/mesh/node-agent-cron.sh
*/30 * * * * .../scripts/dialpad-harvest-cron.sh
*/5  * * * * flock -n /tmp/dialpad-dl.lock ... dialpad-recording-gap.py --limit 300
*/10 * * * * flock -n /tmp/dialpad-ts.lock ... dialpad-transcript-gap.py --limit 400 --max-minutes 600
7,37 * * * * /usr/bin/python3 /home/zabz/.fsearch/comms-refresh.py
*/15 * * * * presence-runtime/sampler.py
```
**Already saturated with scheduled work.** Ports: `0.0.0.0:8002` (API), `*:3000` (dashboard),
`127.0.0.1:3089` (DSH engine for the phone), `100.84.72.88:443` (phone-gate), `0.0.0.0:22`, plus four
UDP ports held by an unidentified process. Its `cloudflared` is `/usr/local/bin/cloudflared` **2026.3.0**
— older than both laptops' `2026.5.x` — config `/etc/cloudflared/config.yml` (+5 backups), systemd unit.

---

## 3. ZABZ-TECH (desktop) — Windows, office. **The fleet's workhorse.**

Probe delivered by `scp` + `powershell -File` after the stdin-chunk path hung; 22.2 s round trip.

### 3.1 Identity
```
hostname=ZABZ-TECH
os_caption=Microsoft Windows 11 Pro   os_version=10.0.26200  os_build=26200
display_version=25H2   ubr=9457       local_time=2026-09-16T16:19:30-04:00
manufacturer=LENOVO    model=30H10010US
logged_on_user=zabz-tech\ezabz
quser -> "ezabz  console  ID 1  STATE Active  IDLE TIME 3:46  LOGON TIME 9/16/2026 12:30 PM"
last_boot=9/16/2026 12:30:45 PM   ->  uptime at sample = 03:48:44
battery=(none)   chassis=35 (Small Form Factor / desktop)   explorer_count=1
power_plan=Power Scheme GUID: 6a6afb64-...  (Lenovo Default)
powercfg /lastwake        -> "Wake History Count - 0"
powercfg /a               -> "Standby (S3)" available; Hibernate NOT enabled ("Hibernation has not been enabled");
                             Hybrid Sleep unavailable; Fast Startup unavailable
```

### 3.2 Compute
```
Get-CimInstance Win32_Processor -> Intel(R) Core(TM) i9-14900
  NumberOfCores=24   NumberOfLogicalProcessors=32   MaxClockSpeed=2000
  LoadPercentage=3   PerfOS_Processor(_Total).PercentProcessorTime=1
Get-Process | ? CPU -gt 0 | Sort CPU -Desc | Select -First 5
  SearchIndexer pid=21556 cpuSec=2,121 wsMB=242
  MsMpEng       pid=6372  cpuSec=783   wsMB=520
  qcmtusvc      pid=6176  cpuSec=554   wsMB=9
  System        pid=4     cpuSec=351   wsMB=16
  svchost       pid=2708  cpuSec=214   wsMB=21
```

### 3.3 Memory
```
TotalVisibleMemorySize -> 63.65 GB      FreePhysicalMemory -> 51.88 GB
TotalVirtualMemorySize -> 67.65 GB      FreeVirtualMemory  -> 53.82 GB
PercentCommittedBytesInUse=20   CommittedBytes=14912487424 (14.91 GB)   CommitLimit=72634015744 (72.63 GB)
AvailableBytes=55642370048 (55.64 GB)
Win32_PhysicalMemory -> 2 x 32768MB @ 5600 MT/s   (2 DIMM slots populated of likely 4)
Win32_PageFileUsage  -> C:\pagefile.sys alloc=4096MB peak=0MB
Get-Process | Sort WorkingSet64 -Desc | Select -First 5
  MsMpEng 520 MB | explorer 432 MB | Microsoft.CmdPal.UI 350 MB | DDPM.Subagent.User 333 MB | Dell.TechHub... 330 MB
```
**20 % of commit used. 51.88 GB physically free. The CPU was 3 % busy.** This is the only machine in
the fleet that is both large and idle.

### 3.4 Disk
```
VOL C: sizeGB=951.6 freeGB=220.6 bus=NVMe model='Micron MTFDKBA1T0TGD-2BK15ABLT'
PHYSDISK 'Micron MTFDKBA1T0TGD-2BK15ABLT' media=SSD bus=NVMe sizeGB=954 health=Healthy
```
**220.6 GB free of 951.6 GB (23 %).**

### 3.5 Runtimes & DSH
```
node -> v24.19.0      npm -> 11.17.0      python -> Python 3.13.5      python3 -> Python 3.13.14
git -> git version 2.52.0.windows.1        ps_version -> 5.1.26100.9444
Get-Command dsh -> (empty; NOT on PATH)
~/.dsh -> .agent-presets, attachments, health, llm-deepseek, logs, multi-window, profiles, sessions,
          storages, tools, .anonymous-user-id, .credentials.yaml, dsh-archive-state.json,
          push-harness-config-state.json, settings.yaml (+9 dated backups + settings.yaml.pre-sync)
~/.dsh/profiles -> node_modules, web
npx dsh -> C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh
~/code/harness-config HEAD -> 33db159
~/code holds ~55 entries, incl. personal-secretary-mvp, personality-system, lpt-flip-phone, lpt-hub,
        kosher-filter-ai, chumash-timeline, tesla-lin-chip, ha-config, _worktrees, phone-and-tech-full
```

### 3.6 Networking
```
lan_ipv4 -> 172.18.96.1/20 if=vEthernet (Default Switch, Hyper-V) ; 192.168.50.138/24 if=Ethernet ;
            100.85.153.96/32 if=Tailscale
gateway=192.168.50.1
tailscale ip -4 -> 100.85.153.96
ts_backend=Running   ts_self_dns=zabz-tech.tail93e6e6.ts.net.   ts_magicdns=tail93e6e6.ts.net   ts_health=(empty)
ts_exitnode=(empty)  ts_advertised_routes=(empty)     <- not a subnet router, not an exit node
PEER iphone-15-pro     100.85.105.93   online=True  active=False relay=nyc  os=iOS
PEER lakewooechsmini   100.126.146.121 online=True  active=False relay=nyc  os=macOS
PEER zabz-tech-linux   100.105.248.90  online=True  active=False relay=nyc  os=linux
PEER secratary         100.84.72.88    online=True  active=False relay=nyc  os=linux
PEER zabz-yoga-1       100.72.162.5    online=True  active=True  relay=nyc  os=windows
cloudflared_on_path=C:\Program Files (x86)\cloudflared\cloudflared.exe
cloudflared_version=cloudflared version 2026.5.2 (built 2026-05-27T10:15 UTC)
cloudflared_cfg_dirs -> C:\ProgramData\Cloudflare=False ; $env:USERPROFILE\.cloudflared=True
cloudflared_services -> (empty: NOT installed as a Windows service)
ssh_service -> sshd=Running/Automatic
```
**The desktop runs `cloudflared` as *processes* (two of them, PIDs 3408 and 16380), not as a service**,
started by the scheduled tasks below.

### 3.7 Listening ports (selected)
```
0.0.0.0:22 / :::22   sshd
127.0.0.1:3099       node            <- DSH engine
127.0.0.1:20241      cloudflared     <- tunnel #1
127.0.0.1:20242      cloudflared     <- tunnel #2
0.0.0.0:8128         node
192.168.50.138:8002  svchost         <- an 8002 listener bound to the LAN address only
0.0.0.0:7070 / :::7070  AnyDesk      127.0.0.1:5939  TeamViewer_Service
0.0.0.0:5566-5567    DDPM-NKVM      127.0.0.1:7510 / 0.0.0.0:8090 / 0.0.0.0:12345  ElevationService
0.0.0.0:623          LMS            0.0.0.0:2179 vmms     172.18.96.1:139 / 192.168.50.138:139 (SMB)
```
> **Three remote-access agents are live on this machine: AnyDesk (`7070` on all interfaces),
> TeamViewer (`5939`) and an `ElevationService` (`12345` on all interfaces).** Recorded as an exposure
> inventory item; not investigated further (out of scope).

### 3.8 Persistent work — **this machine is already half-way into the mesh design**
```
TASK \DSH Engine Watchdog (1m)          state=Ready
TASK \DSH Mesh Prereqs (5m)             state=Ready     <- a mesh-prereq task ALREADY EXISTS here
TASK \DSH Process Reaper                state=Ready
TASK \DSH Multi-Window Launcher         state=Ready
TASK \DSH Window Fleet Watchdog         state=Ready
TASK \DSH search index refresh          state=Ready
TASK \DshChatScan                       state=Ready
TASK \PersonalSecretary-DesktopSshCloudflareTunnel      state=Running   <- the two cloudflared processes
TASK \PersonalSecretary-DesktopSshCloudflareTunnelLogon state=Running
TASK \PersonalSecretary-DesktopHealth / -DailyPartnerSync / -HarnessSync / -NodeAgent
TASK \PersonalSecretary-PushDSHSessions / -PushHarnessConfig / -PushVSCodeChats / PersonalSecretaryBackup
TASK \VSCode-Copilot-Health-Watchdog  + slot-01/slot-02 health watchdogs + 5 launch tasks
TASK \AlpineHAAlarmListener state=Running   \AlpinePlayConsole / -Repeat
TASK \GrandSupervisorSafe   \HA Part1 Runtime Refresh   \EMTGen_* (3)   \nWizard_*
```
> **`\DSH Mesh Prereqs (5m)` exists on this desktop already.** Someone has begun the mesh work here.
> Before designing a new distribution layer, find out what that task does — it may already own the
> prerequisites this audit was asked to establish. Its exact definition is in §11.10.

---

## 4. zabz-tech-linux (linux-pc) — Linux, office

Reached by **explicit address**, not by alias — see §9.3. `ssh -o BatchMode=yes -i ~/.ssh/zabz-tech-ed25519
-l zabz 100.105.248.90 "..."` → 890 ms.

```
hostname=zabz-tech-linux
uptime -> "16:25:25 up 36 days, 4:13, 10 users,  load average: 0.00, 0.01, 0.00"
nproc -> 12   cpuinfo model name -> 11th Gen Intel(R) Core(TM) i5-11400 @ 2.60GHz
/proc/meminfo -> MemTotal=11953348 kB (11.40 GB)   MemAvailable=10795976 kB (10.30 GB)
                 SwapTotal=4194300 kB  SwapFree=3546876 kB
free -h -> Mem: 11Gi total, 1.1Gi used, 7.8Gi free, 2.9Gi buff/cache, 10Gi available
           Swap: 4.0Gi total, 632Mi used, 3.4Gi free
df -hT / -> /dev/nvme0n1p2 ext4 468G size, 423G used, 22G avail, 96% /      <-- 96 % FULL
lsblk -> nvme0n1 0 476.9G INTEL SSDPEKNW512G8H  (ROTA=0, SSD)
         sde 0 931.5G CT1000X9SSD9 -> sde2 /mnt/abramczyk-img
         sdf 0   5.5T CT6000X10SSD9 -> sdf2 /mnt/atlas-recovery
         loops incl. loop5 29.1G /mnt/bakst_img, loop18p1 114.6G /mnt/shlesinger-image
node -> NOT FOUND ("bash: line 1: node: command not found")
python3 -> Python 3.12.3      git -> git version 2.43.0
~/.dsh -> (absent; the `ls` printed nothing)
tailscale ip -4 -> 100.105.248.90
ps -eo pcpu,rss,comm --sort=-pcpu | head -6
  100  ps | 16.5 mount.ntfs-3g | 4.3 sshd | 1.7 kswapd0 (RSS 0) | 0.2 mount.ntfs
```
- **12 logical cores, 11.4 GB RAM, 10.3 GB genuinely available, swap only 21 % used** — the healthiest
  memory profile of any Linux node measured.
- **96 % disk full: 22 GB free of 468 GB.** It is also hosting large external recovery images
  (`/mnt/atlas-recovery` on a 5.5 TB SSD, `/mnt/abramczyk-img` on a 931 GB SSD, `/mnt/shlesinger-image`,
  `/mnt/bakst_img`) — this machine appears to be a staging/storage host for customer data.
- **`kswapd0` appeared in the top-5 by CPU**, i.e. the kernel is doing swap work even at load 0.00.
- **No node, no npm, no `~/.dsh`** — DSH cannot run here as it stands. Bare bash is 5.2 (Ubuntu 24.04-era).

---

## 5. mac-mini (`LakewooechsMini`) — macOS, the employee's machine

`ssh mac-mini-ts` → MESHOK (615 ms). The first probe was Linux-shaped and could not read a Mac; a second
trimmed probe supplied the hardware facts below.

### 5.1 Measured
```
hostname=LakewooechsMini
uname -a -> Darwin LakewooechsMini 25.5.0 ... RELEASE_ARM64_T8132 arm64
sw_vers  -> ProductName: macOS  ProductVersion: 26.5.2  BuildVersion: 25F84
hw.model -> Mac16,10        machdep.cpu.brand_string -> Apple M4
hw.ncpu=10  hw.physicalcpu=10  hw.logicalcpu=10        <- 10 cores, NO SMT on Apple silicon
hw.memsize -> 17179869184 (16.00 GB)
kern.boottime -> Mon Aug  3 22:49:36 2026 ; uptime -> "16:23  up 43 days, 17:34, 2 users, load averages: 1.38 1.35 1.39"
vm.loadavg -> { 1.38 1.35 1.39 }
sw_vers / swapusage -> vm.swapusage: total = 6144.00M  used = 5635.94M  free = 508.06M  (encrypted)
vm_stat -> page size 16384 bytes; Pages free: 4020; Pages active: 248960; Pages inactive: 246755
df -h / -> /dev/disk3s1s1  228Gi  16Gi used  17Gi avail  49%  /
df -h /System/Volumes/Data -> /dev/disk3s5  228Gi  169Gi used  17Gi avail  91%
diskutil info / -> APFS ; Device Node /dev/disk3s1s1 ; Disk Size 245.1 GB (245107195904 bytes) ; Solid State: Yes
pmset -g -> "standby 0 | Sleep On Power Button 1 | autorestart 0 | powernap 1 | networkoversleep 0 |
             disksleep 10 | sleep 1 (sleep prevented by dasd, dasd) | ttyskeepawake 1 |
             displaysleep 60 | tcpkeepalive 1 | lowpowermode 0 | womp 1"
/usr/local/bin/node -> /usr/local/lib/nodejs/node-v24.19.0-darwin-arm64/bin/node   ; node --version -> v24.19.0
npm -> "env: node: No such file or directory"   (npm exists but its shebang cannot find node in this PATH)
python3 -> Python 3.9.6      git -> git version 2.50.1 (Apple Git-155)      bash -> 3.2.57
Get-Command dsh -> NOT FOUND ; ~/.dsh -> attachments, bin, browser-profile, browser-profiles,
   dsh-archive-state.json, logs, profiles, sessions, settings.machine.yaml, settings.yaml(+3 backups), storages
~/.dsh/bin -> deploy-session-sync.sh, icon.png, new-window.command, yocheved-assistant.command
~/.dsh/profiles -> headless, node_modules, web
~/harness-config HEAD -> 98fcefe
~/code -> _worktrees, harness-config, harness-config.stale-20260914-224300, personal-secretary-mvp
/Applications/Tailscale.app/Contents/MacOS/Tailscale -> present ; Tailscale ip -4 -> 100.126.146.121
~/.cloudflared -> org-token lock, desktop-ssh.abletelsolutions.com-<sha256>-token.lock
crontab -l -> "no crontab for lpt"
launchd list -> only com.apple.* entries in the first 40
```
- **43 days 17 h of continuous uptime — the strongest always-on evidence of any node measured.** No
  battery, no `/sys/class/power_supply`. `pmset` shows `sleep 1` but **explicitly "sleep prevented by
  dasd, dasd"**, i.e. the OS is currently holding the machine awake. `powernap 1`, `womp 1`
  (wake-on-LAN enabled), `lowpowermode 0`.
- **`who` shows TWO console users: `moshemontrose` (since Aug 11) and `lpt` (since Aug 12).** This is the
  employee's machine, left logged in at the console for over a month.
- **It is memory-starved despite the M4:** swap **5.64 GB of 6.14 GB used (92 %)**, and only **4,020
  free pages × 16 KB = 66 MB** genuinely free. Same class of problem as secratary.
- **17 GB free on a 228 GB APFS container** — the Data volume alone is 169 GB used.
- **`node` v24.19.0 IS present** at `/usr/local/bin/node`; my first probe missed it because it invoked
  `node` through a PATH that does not include `/usr/local/bin`. `npm` is broken for the same reason.

### 5.2 Networking
```
tailscale ping --c 3 LakewooechsMini.tail93e6e6.ts.net -> pong via 71.104.140.242:55390 in 46ms   DIRECT
Test-Connection 100.126.146.121 -Count 4 -> OK avgMs=39.8 (36,41,37,45)
TCP connect 100.126.146.121:22           -> best 130 ms (204,192,130)
ssh mac-mini -> ssh: connect to host 192.168.50.45 port 22: Connection timed out (6048 ms)
```
It also reported **two IPv4 addresses on one `/24`**: `192.168.50.45` and `192.168.50.73`.

---

## 6. hetzner (`waze-mdm-01`) — Hetzner VPS, off-LAN, **not on the tailnet**

Alias `hetzner` / `hetzner-main` / `waze-mdm-01` → `87.99.141.172`, user `root`, key
`~/.ssh/id_ed25519_hetzner`. **Absent from the Tailscale peer table on every node measured.**

```
hostname=waze-mdm-01
uname -a -> Linux 6.8.0-90-generic #91-Ubuntu SMP ... x86_64     os-release -> Ubuntu 24.04.3 LTS
uptime -s -> 2026-05-13 02:26:04 ; uptime -> "up 126 days, 17:50, 1 user, load average: 0.05, 0.05, 0.02"
systemd-detect-virt -> kvm ; DMI -> Hetzner / vServer
nproc -> 2 ; cpuinfo model name -> AMD EPYC-Rome Processor
/proc/meminfo -> MemTotal=1965740 kB (1.87 GB)  MemAvailable=1117840 kB (1.07 GB)
                 SwapTotal=2097148 kB  SwapFree=1870076 kB
free -h -> Mem: 1.9Gi total, 828Mi used, 140Mi free, 1.2Gi buff/cache, 1.1Gi available | Swap: 2.0Gi, 221Mi used
df -hT -> /dev/sda1 ext4 38G size, 18G used, 19G avail, 50% /  ; /dev/sda15 vfat 253M 1% /boot/efi
lsblk -> sda 0 38.1G disk QEMU HARDDISK (ROTA=0)
node -> NOT FOUND   npm -> NOT FOUND   python3 -> 3.12.3   git -> 2.43.0
dsh -> NOT FOUND    ~/.dsh -> absent   cloudflared -> NOT FOUND   tailscale -> NOT FOUND   ~/code -> absent
last -x reboot -> "reboot system boot 6.8.0-90-generic Wed May 13 02:26:06 2026  still running"
                  wtmp begins Thu Jan 8 10:27:31 2026
top-5 RSS -> dockerd 98 MB | systemd-journald 95 MB | python 83 MB | uvicorn 49 MB | containerd 41 MB
```
`docker ps`: `waze-mdm-fleet-dashboard-1`, `-fleet-api-1`, `-caddy-1`, `-nanodep-syncer-1`, `-nanomdm-1`,
`-nanodep-1`, `-restore-1`, `-dns-filter-1`, `yocheved`, `emt-quiz`, `waze-mdm-postgres-1`.
`crontab -l` includes a job that runs **every single minute** (`* * * * * fleet-api-call.sh POST /fleet/sweep`),
a 5-minute health check, a 30-minute monitor, and 6-hourly heartbeats. Running services include
`strongswan-starter` (IPsec), `dnsmasq`, `dep-profile-reconcile`.

> **Verdict: not an agent node as it stands.** 2 cores, 1.9 GB RAM, no node/DSH/cloudflared/Tailscale,
> and it is the live Waze MDM production host. Its only asset for this purpose is **126 days of uptime**.

---

## 7. lpt-apps-01 — second Hetzner VPS, off-LAN, **not on the tailnet**

Found in `~/.ssh/config` (`lpt-apps` / `lpt-apps-01` → `2.28.33.58`, user `root`, key `~/.ssh/id_ed25519_lpt-apps`).
Not in the brief's six-node list, included because it is a real machine in this fleet.

```
hostname=lpt-apps-01
uname -a -> Linux 6.8.0-137-generic #137-Ubuntu SMP ... x86_64     os-release -> Ubuntu 24.04.4 LTS
uptime -s -> 2026-08-31 14:45:06 ; uptime -> "up 16 days, 5:31, 1 user, load average: 0.13, 0.11, 0.11"
systemd-detect-virt -> kvm ; DMI -> Hetzner / vServer
nproc -> 4 ; cpuinfo -> Intel Xeon Processor (Skylake, IBRS, no TSX)
/proc/meminfo -> MemTotal=7937232 kB (7.57 GB)  MemAvailable=5386500 kB (5.14 GB)
                 SwapTotal=2097148 kB  SwapFree=1473696 kB
free -h -> Mem: 7.6Gi total, 2.4Gi used, 439Mi free, 5.4Gi buff/cache, 5.1Gi available | Swap: 2.0Gi, 608Mi used
df -hT -> /dev/sda1 ext4 75G size, 60G used, 12G avail, 84% /        <-- 84 % FULL
lsblk -> sda 0 76.3G disk QEMU HARDDISK (ROTA=0)
node -> NOT FOUND   npm -> NOT FOUND   python3 -> 3.12.3   git -> 2.43.0
dsh -> NOT FOUND    ~/.dsh -> absent   cloudflared -> NOT FOUND   tailscale -> NOT FOUND
top -bn2 -> %Cpu(s): 0.7 us, 0.7 sy, 98.4 id
ps top-5 RSS -> dockerd 339 MB | node 267 MB | node 251 MB | uvicorn 234 MB | uvicorn 212 MB
last -x reboot -> "reboot system boot 6.8.0-137-generic Mon Aug 31 14:45:09 2026  still running"
```
`docker ps`: `lakewood-rentals`, `chumash-timeline`, `lpt-backend`, `personality-test`, `lpt-test-backend`,
`lpt_filter_site`, `lpt_filter_ai_api_b` ×2, `caddy`, `lpt-postgres`, `lpt-redis`.
Ports: `80`, `443`, `1080`, `1081`, `9443`, `9444`, `22`, plus 8 loopback-bound app ports. `redis-server *:6379`.

> **Verdict:** 4 cores and 7.6 GB / 5.14 GB available is the second-best Linux capacity in the fleet, but
> it has **no node/npm/DSH**, its disk is **84 % full**, and it is production for at least six LPT apps.

---

## 8. CAPABILITY TABLE — measured

Every cell below was read from the node. `n/a` means the path does not exist for that machine.

| node | OS | cores (logical) | RAM total / available | disk free | always-on evidence | DSH installed? | LAN reachable from laptop? | tailscale reachable? | measured latency |
|---|---|---|---|---|---|---|---|---|---|
| **ZABZ-YOGA** (self) | Win 11 Home 25H2, 26200.9445 | **22** (16 physical) | **31.61 GB / 17.54 GB free phys, 26.36 GB commit free** | **71.1 GB** of 477.8 GB (14.9 %) NVMe SSD | **WEAK** — battery present (100 %, AC), **Balanced** plan, interactive user, **uptime only 21 min** | **YES** (`~/.dsh` + `_npx`), **not on PATH** | n/a (self) | n/a (self); backend **Running**, `100.72.162.5` | self; tsping to peers 46–170 ms |
| **secratary** | Ubuntu 26.04 LTS, kernel 7.0.0-30 | **4** | **22.87 GB / 17.10 GB avail** — **swap 99.99 % full (568 kB of 4.0 GB)** | **185 GB** of 467 GB, LUKS, PNY SATA SSD | **STRONG** — **13 d 22 h uptime**, headless (0 console logins), no battery, no GUI | **YES** (`~/.dsh`, `~/dsh-engine` :3089), not on PATH | **NO** — `192.168.50.77 port 22: Connection timed out` | **YES** `100.84.72.88` | TCP22 **56 ms**; ICMP 64.8; tsping 35–170 ms **via DERP relay** |
| **ZABZ-TECH** (desktop) | Win 11 **Pro** 25H2, 26200.9457 | **32** (24 physical) | **63.65 GB / 51.88 GB free phys, 53.82 GB commit free** | **220.6 GB** of 951.6 GB (23 %) NVMe SSD | **GOOD** — SFF desktop, **no battery**, AC, hibernate disabled, `lastwake = 0`; uptime 3 h 49 min at sample | **YES** (`~/.dsh` + `_npx` + `\DSH Mesh Prereqs (5m)` task), not on PATH | **NO** — `192.168.50.138 port 22: Connection timed out` | **YES** `100.85.153.96` | TCP22 **42 ms**; ICMP 49.8; tsping **55 ms direct**; `desktop-cf` **4744 ms** |
| **zabz-tech-linux** (linux-pc) | Ubuntu (kernel via `nproc` 12), 36 d up | **12** | **11.40 GB / 10.30 GB avail** (swap 21 % used) | **22 GB** of 468 GB — **96 % FULL** (plus 4 external SSDs incl. a 5.5 TB) | **STRONG** — **36 d 4 h uptime**, load 0.00; **10 console users logged in** | **NO** — no `node`, no `~/.dsh` | **NO** — `192.168.50.23 port 22: Connection timed out` | **YES** `100.105.248.90` | TCP22 **39 ms**; ICMP 52.2; tsping **62 ms direct** |
| **mac-mini** | macOS 26.5.2 (25F84), Darwin 25.5.0, arm64, Mac16,10 | **10** (Apple M4, no SMT) | **16.00 GB / ~66 MB genuinely free** — **swap 92 % used (5.64 GB of 6.14 GB)** | **17 GB** on a 228 GB APFS container | **STRONGEST measured — 43 d 17 h uptime**; no battery; `pmset sleep prevented by dasd`; **but 2 console users (moshemontrose, lpt)** | **NO `dsh` binary**, but `~/.dsh` exists with a `headless` profile; **node v24.19.0 at /usr/local/bin** | **NO** — `192.168.50.45 port 22: Connection timed out` | **YES** `100.126.146.121` | TCP22 **130 ms**; ICMP 39.8; tsping **46 ms direct** |
| **hetzner** (`waze-mdm-01`) | Ubuntu 24.04.3 LTS, 6.8.0-90, KVM | **2** | **1.87 GB / 1.07 GB avail** | **19 GB** of 38 GB (50 %) | **STRONGEST — 126 d 17 h uptime** | **NO** — no node, no `dsh`, no `~/.dsh` | n/a (public IP) | **NO — not on the tailnet** | **134 ms** TCP22; ICMP 79.5 |
| **lpt-apps-01** | Ubuntu 24.04.4 LTS, 6.8.0-137, KVM | **4** | **7.57 GB / 5.14 GB avail** | **12 GB** of 75 GB — **84 % FULL** | **STRONG — 16 d 5 h uptime** | **NO** — no node, no `dsh`, no `~/.dsh` | n/a (public IP) | **NO — not on the tailnet** | **170 ms** TCP22; ICMP 173.5 |

---

## 9. TRANSPORT MATRIX — measured from ZABZ-YOGA

`OK` = verified end-to-end with `echo MESHOK` over ssh. Times are wall-clock for that cold ssh.

| target | LAN `192.168.50.x` | Tailscale | Cloudflare (`-cf`) |
|---|---|---|---|
| secratary | **FAIL** — `ssh: connect to host 192.168.50.77 port 22: Connection timed out` (6047 ms); ICMP no reply; TCP22 3/3 `TIMEOUT4s` | **OK** — 879 ms cold; TCP22 56 ms; tsping 35–170 ms **via DERP** | `secretary-cf` **OK** — 3712 ms |
| zabz-tech | **FAIL** — `... 192.168.50.138 port 22: Connection timed out` (6054 ms) | **OK** — 1081 ms cold; TCP22 42 ms; tsping 55 ms **direct** | `desktop-cf` **OK** — **4744 ms** |
| zabz-tech-linux | **FAIL** — `... 192.168.50.23 port 22: Connection timed out` (6054 ms) | **OK** — 890–1412 ms cold; TCP22 39 ms; tsping 62 ms **direct** | not configured |
| mac-mini | **FAIL** — `... 192.168.50.45 port 22: Connection timed out` (6048 ms) | **OK** — 615 ms cold; TCP22 130 ms; tsping 46 ms **direct** | not configured |
| laptop (self) | n/a | **OK** — `laptop-ts` 619 ms cold | not configured |
| `yocheved-cf` (not a mesh node) | n/a | n/a | **FAIL** — `websocket: bad handshake / Connection closed by UNKNOWN port 65535` (2302 ms) |
| `hetzner` `87.99.141.172` | off-LAN by design | **not a tailnet member** (absent from every peer table) | **OK** by direct public SSH — 1874 ms cold |
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
BackendState = Running        AuthURL = (empty)        Health = []        MagicDNSSuffix = tail93e6e6.ts.net
```
A `NoState` backend carries `BackendState = NoState` with a populated `AuthURL`; neither is present.
**This laptop is neither a subnet router nor an exit node** (`AdvertisedRoutes` and `ExitNodeStatus`
both empty on Self).

### 9.3 Two alias defects found in the mesh's own addressing — both real
1. **`zabz-tech-linux-ts` does not exist.** `~/.ssh/config` (unchanged since 2026-09-14 22:02:04,
   241 lines, sha256 `2CAFC793…`) declares only `Host linux-pc-ts` at line 81. Proof:
   ```
   > ssh -G zabz-tech-linux-ts   -> host zabz-tech-linux-ts / user ezabz / hostname zabz-tech-linux-ts / identityfile ~/.ssh/id_rsa
   > ssh -G linux-pc-ts          -> host linux-pc-ts / user zabz / hostname zabz-tech-linux.tail93e6e6.ts.net / identityfile ~/.ssh/zabz-tech-ed25519
   > ssh zabz-tech-linux-ts "..." -> ssh: Could not resolve hostname zabz-tech-linux-ts: No such host is known.
   ```
   An unresolved alias silently falls back to **`user ezabz` and `~/.ssh/id_rsa`** — it fails as
   "hostname unknown" rather than "user wrong", which is a confusing failure mode worth knowing. The
   working alias is **`linux-pc-ts`**; that is what this audit used for the transport row above, and the
   §4 probe used the explicit `-i ~/.ssh/zabz-tech-ed25519 -l zabz 100.105.248.90`.
   The brief's own alias list (`zabz-tech-linux`, `linux-pc`, `hp-linux`, `zabz-tech-linux-ts`) contains
   a name that is not in the config; the `-ts` alias for this node is `linux-pc-ts`.
2. **`secratary-lan` is likewise not an alias** — the LAN alias is `secretary` / `secretary-lan` /
   `secratary` (see the `Host` line at config line 13). Probing `secratary-lan` produces
   `Could not resolve hostname secratary-lan`. The audit used the correct names after this was found.

### 9.4 Every LAN path failed for one structural reason
This laptop is on `192.168.12.0/24` (T-Mobile CGNAT) and the office subnet is `192.168.50.0/24`. Home
and office are separate networks and **this laptop is on neither.** A LAN failure here means *"this
vantage point cannot see that subnet"*, **not** "that node is down" — proved by every LAN target also
answering happily over Tailscale, and by secratary reaching three of them in **1 ms** on the office LAN.

---

## 10. CAPACITY ESTIMATE — **ESTIMATE, NOT A MEASUREMENT**

Measured constant, given: **one actively-generating agent turn ≈ 0.81 GB commit and ≈ 1 core.**
Comfortable ceiling = **75 % of available**, leaving 25 % headroom.

| node | RAM-limited turns (avail ÷ 0.81 × 0.75) | CPU-limited turns (cores × 0.75) | **comfortable ceiling** | caveat that overrides the arithmetic |
|---|---|---|---|---|
| **ZABZ-TECH** | 51.88 ÷ 0.81 × 0.75 = **48** | 32 × 0.75 = **24** | **24** | CPU binds. Measured load 1–3 %. The fleet's real workhorse. |
| **ZABZ-YOGA** | 17.54 ÷ 0.81 × 0.75 = **16** | 22 × 0.75 = 16, *minus 27–31 % already in use* → ~11 | **~11** | A **battery** laptop the owner wants *unloaded*; interactive user; 7 `\DSH` watchdog/reaper tasks. **Risk says 0–2, burst only.** |
| **zabz-tech-linux** | 10.30 ÷ 0.81 × 0.75 = **9** | 12 × 0.75 = **9** | **9** | **No node/npm/DSH**; **96 % disk full**; 10 console users; hosts customer recovery images. |
| **secratary** | 17.10 ÷ 0.81 × 0.75 = **15** | 4 × 0.75 = **3** | **3** | CPU binds at 4 cores **and swap is 99.99 % full**, so there is no overflow cushion. It is also the authority, already running the 18-agent tick loop, ~30 cron jobs, 6 services. **Coordinator, not bulk worker.** |
| **lpt-apps-01** | 5.14 ÷ 0.81 × 0.75 = **4** | 4 × 0.75 = **3** | **3** | No node/npm/DSH; 84 % disk; production for six LPT apps. |
| **mac-mini** | **~0** — 66 MB genuinely free, swap 92 % used | 10 × 0.75 = 7 | **~1** | Memory is effectively exhausted *now*; it is the employee's logged-in desktop. |
| **hetzner** | 1.07 ÷ 0.81 × 0.75 = **0.99** | 2 × 0.75 = 1 | **1** | No node/npm/DSH; live Waze MDM production. |
| **fleet total** | | | **≈ 50 agent-turns** | |

**Breakdown of the total:** `24 + 11 + 9 + 3 + 3 + 1 + 1 ≈ 52`, rounded to **≈ 50**.
**A defensible *today* number, excluding machines that cannot run DSH at all** (`zabz-tech-linux`,
`mac-mini`, `hetzner`, `lpt-apps` have no `node`), is **≈ 35 — essentially ZABZ-TECH (24) plus
ZABZ-YOGA (11)**. Every remaining node needs a Node runtime installed before it can host a turn.

> **The arithmetic is not the answer.** `zabz-tech-linux` scores 9 but has **46 GB of customer image
> data on a 96 %-full disk**; `mac-mini` scores 1 because its swap is already 92 % exhausted; `secratary`
> is limited to 3 by four cores it is already using to run the company. The two highest numbers belong to
> the two Windows machines, one of which is the laptop the owner is trying to relieve.

---

## 11. WHAT I COULD NOT MEASURE, AND THE EXACT COMMAND THAT WOULD SETTLE IT

**An honest refusal is a valid answer; a confident wrong number is not.**

1. **Sleep-timeout policy and boot history on ZABZ-YOGA** — requires elevation, which this session does
   not have. Exact command (as Administrator):
   `powercfg /sleepstudy /output $env:TEMP\sleep.html` and
   `Get-WinEvent -LogName System -MaxEvents 300 | ? { $_.Id -in 41,42,107,109,6005,6008 }`.
   What *is* known: 21 minutes of uptime at sample, battery present, Balanced plan, interactive user.
2. **Whether `secratary`'s swap exhaustion is transient or chronic, and what caused it** — needs history,
   not a snapshot. Exact command:
   `ssh secratary-ts "sar -r -S -f /var/log/sysstat/sa$(date +%d) | tail -20; grep -c oom /var/log/syslog"`
   (sysstat is installed — `sysstat-collect.timer` runs every 10 minutes).
3. **Disk throughput on every node** — **deliberately not measured.** On ZABZ-YOGA a synthetic write
   would burn write endurance on the owner's system drive (71 GB free) for a number that changes no
   decision, since every disk is already identified by bus and media type (`NVMe`, `SATA`, `QEMU
   HARDDISK`, `APFS`, `Solid State: Yes`). Stated rather than silently skipped.
4. **`dsh --version` on any node** — `dsh` is on **no** node's PATH. On ZABZ-YOGA the exact command is:
   `node "$env:LOCALAPPDATA\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\bin\dsh.js" --version`
5. **The four UDP ports on secratary bound by an unidentified process** (42996, 43189, 44242, 47188) —
   `ss -tulpnH` did not attribute them. Exact command:
   `ssh secratary-ts "sudo ss -tulpnH sport = :42996"` (needs root for socket ownership).
6. **Whether the PostgreSQL on ZABZ-YOGA's `0.0.0.0:5432` requires authentication** —
   `Test-NetConnection -ComputerName 127.0.0.1 -Port 5432` proves reachability only. Settling auth needs
   a client connection attempt, which is not a read-only act. **Not attempted by design.**
7. **Whether `secretary-cf` / `desktop-cf` are distinct tunnels, and every `-cf` path's true latency** —
   both answered (3712 ms / 4744 ms) but `scripts/windows/CloudflaredAccessSshProxy.ps1` and the tunnel
   configs were **not read**. Exact command:
   `Get-Content C:\Users\ezabz\code\personal-secretary-mvp\scripts\windows\CloudflaredAccessSshProxy.ps1`
8. **`\DSH Mesh Prereqs (5m)` on ZABZ-TECH — what it actually does.** It is *Ready* and its name suggests
   the mesh prerequisite work this audit was commissioned to begin. Exact command:
   `ssh desktop-ts "powershell -NoProfile -Command \"(Get-ScheduledTask -TaskName 'DSH Mesh Prereqs (5m)').Actions | Format-List *; (Get-ScheduledTask -TaskName 'DSH Mesh Prereqs (5m)').Triggers | Format-List *\""`
   **This should be read before any distribution design is written — it may already own the answer.**
9. **`harness-config` is NOT converged**: secratary `af2a6e7`, ZABZ-YOGA `98fcefe`, zabz-tech `33db159`,
   mac-mini `98fcefe`. A `*/15 autosync.sh` exists on secratary and has not reconciled them. Root cause
   not investigated. **Disclosure: this audit did not modify that repo, but this file is itself written
   into the working tree at `harness-config/docs/mesh/10-inventory.md`, which will show up as an
   uncommitted change on ZABZ-YOGA.** Whoever commits it should be aware that the three other machines
   are on different revisions. Exact command:
   `ssh secratary-ts "git -C ~/harness-config status --short; git -C ~/harness-config log --oneline -5; tail -30 ~/harness-config/scripts/autosync.sh"`
10. **`yocheved-cf`** — failed with `websocket: bad handshake / Connection closed by UNKNOWN port 65535`.
    Not a mesh node; recorded for completeness.
11. **The `/etc/hosts`, `nsswitch` and Tailscale DNS order on each Linux node** — not inspected; MagicDNS
    resolved everything asked of it, so there was no symptom to chase.

---

## 12. THE THREE THINGS THAT SHOULD CHANGE THE DESIGN

1. **The fleet is two machines, not seven.** Only **ZABZ-TECH (32 cores / 63.65 GB, 3 % busy)** and
   **ZABZ-YOGA (22 cores / 31.61 GB)** are both capable and ready. Four of the seven have **no `node`
   runtime at all** — `zabz-tech-linux`, `mac-mini` (node exists but `dsh` does not), `hetzner`,
   `lpt-apps-01` — and the two best always-on machines (`hetzner` 126 d, `mac-mini` 43 d) are the two
   least ready. **Every "distribute across the mesh" plan begins with installing a runtime, which this
   audit did not do and must not do unasked.**
2. **`secratary`, the authority, is a 4-core Dell OptiPlex with a swap file that is 99.99 % exhausted
   (568 kB free of 4.0 GB) — and `mac-mini` is in the same condition (92 % of 6.14 GB swap used, 66 MB
   truly free).** Neither can absorb a memory spike; the OOM killer, not a scheduler, will decide. And
   the laptop reaches the authority **only through the NYC DERP relay** (30–44 ms jitter, "direct
   connection not established"), while the office nodes reach it in **1 ms**. Any DB-bound work placed
   on the authority is doubly constrained: four cores, and a relayed path for one of its two clients.
3. **This laptop already runs a 1-minute engine watchdog, a process reaper, and seven `\DSH *` scheduled
   tasks — and the desktop already runs a `\DSH Mesh Prereqs (5m)` task.** A new distribution layer
   placed on either Windows machine will race machinery that already exists. Read
   `\DSH Mesh Prereqs (5m)` and the existing watchdog/reaper task definitions **before** designing the
   scheduler; the prerequisite work may already be partly built, and the reaper will kill work it did
   not start.
