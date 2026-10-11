# 123 — The mesh: state of play, reconciled against what is true today

**Written 2026-10-09 ≈19:45Z from `zabz-tech`** (hostname `ZABZ-TECH`, tailnet `100.85.153.96`), on branch
`main` at `b84fa97`. This is a *reconciliation* document: its job is to name every claim in the older mesh
documents that is no longer true, and to state only what I measured myself.

**Provenance convention.** **MEASURED** = I ran the command in this session and the command is given.
**READ** = read out of a file or a git object, with the path and line. **NOT DETERMINED** = I tried and
could not, or I had no access. Nothing in this document is carried over from another document without
saying so.

**A note on the commands.** On this Windows node, `ssh <host> "<command>"` whose stdout is *piped* never
returns — a defect `PROGRAM.md:100-103` already records. Every remote measurement below was therefore run
through `Start-Process ssh -RedirectStandardOutput <file>`, and remote scripts were shipped base64-encoded
to avoid Windows argument-quoting damage. **The commands are quoted in the form that actually worked.**

---

## 0. The one-screen answer

| | |
|---|---|
| **Which machine is the authority?** | **`secratary` — the office desktop — still is, right now.** Its `secretary.db` was written at 19:35Z and `secretary-api` is serving. |
| **Which machine was meant to become the authority?** | **`secratary-cloud` — and it exists.** It is a real Hetzner box at **`178.156.194.1`**, hostname `secratary-cloud`, matching the `CCX13` recommendation in `121` §6 almost exactly. |
| **So is the migration done?** | **No. It has not started in the operational sense.** The cloud box has no tailnet, no Docker, no `mesh-broker`, no `secretary-api`, and nothing answering on any port but `22` and `53`. It holds a *copy* of the database that its own conversion script calls disposable. |
| **The broker** | Still **only** on `secratary`, loopback `127.0.0.1:3091`, reporting **5 nodes** and **77 read failures** out of 205 reads at 19:38Z. |
| **The offsite backup path** | **There is none.** `~/secretary-backups` is **176 G and local**, on the same 467 G office disk that is the complaint. No `rclone`, `restic`, `b2`, `aws`, `s3cmd` or `borg` exists on the authority. |
| **The single most dangerous open item** | The cloud box's `/root` holds **21.40 GiB** of database **plus a 10.83 GiB and growing WAL**, on a **75 G** disk that is already **48 % full**. |

---

## 1. What is STALE — one row per claim

| doc (line) | claim as written | true today | how I know |
|---|---|---|---|
| `111-placement-design.md:27` | `secratary-ts` … free disk `134.8` GiB; "authority; 4 GiB swap **100 % full**" | `/` = **89 G avail, 81 % used**; swap = **12 MiB used of 4095 MiB** | MEASURED `ssh secratary-ts "df -h /; free -m"` 19:38Z |
| `114-node-capacity.md:44` | `secratary` free disk **134.8 GiB** | **89 G avail** | same command |
| `114-node-capacity.md:54` | "swap: **712–716 kB free** of 4 GiB — 0.017 %" | **4083 MiB free** of 4095 (12 used) — the `86-authority.md` fix is holding | `free -m` |
| `114-node-capacity.md:16` | `secratary` unit cost "**~181 MiB** RSS peak … one child only" | `secretary-api` **alone** is **2,647,492 KiB ≈ 2.52 GiB** RSS; the broker holds **3 live leases, all on `zabz-tech`** | `ps -eo pid,rss,etime,cmd --sort=-rss`; `curl 127.0.0.1:3091/healthz` |
| `121-always-on-server.md:40` | Disk 467 GB, **384 GB used, 64 GB free, 86 %** (its own measurement, 17:39Z *the same day*) | **359 G used, 89 G avail, 81 %** at 19:37Z — ~25 GB moved in two hours | `df -h /` over `ssh secratary-ts` |
| `121-always-on-server.md:50` | `secretary-api` "**723 MB RSS** — the largest process" | **2,647,492 KiB (2.52 GiB)**, still the largest | `ps -eo pid,rss --sort=-rss` |
| `121-always-on-server.md:20,73` | `~/secretary-backups` alone is **201 GB** | **176 G** | `du -sh /home/zabz/secretary-backups` |
| `121-always-on-server.md:43` | Running services **31** | **34** | `systemctl list-units --type=service --state=running --no-legend \| wc -l` |
| `121-always-on-server.md:20,78` | live DB **22.9 GB** | live `secretary.db` = **23,138,103,296 B = 21.55 GiB (23.14 GB)** + 64 MiB WAL. Doc `121` and the cloud copy are both ~1 % low | `stat -c '%s %n' …/secretary.db` |
| `121-always-on-server.md:154,212` | `CCX13` gives **80 GB** | `/dev/sda1` is **75 G** usable (76.3 G raw), 38 G avail | `df -h /; lsblk -o NAME,SIZE,ROTA` |
| `121-always-on-server.md:98-100` | "**Nothing** in `docs/mesh/` proposes moving the authority off the office box … **This is genuinely new**" | Superseded within hours: `122-cloud-authority-provision.md` exists on `origin/main`, and the box is built | `git ls-tree -r --name-only origin/main -- docs/mesh` |
| `121-always-on-server.md:310-311` (§9.6) | storage-box price "≈€3.50–4/TB-month … **not verified**" | **Still unverified.** I did not price object storage either | not measured — see §4 |
| `122-cloud-authority-provision.md:18` (P3) | "an ssh alias `secratary-cloud` in `~/.ssh/config` … done by: **me**" | **NOT DONE.** `ssh secratary-cloud` → `Could not resolve hostname secratary-cloud: No such host is known.` exit 255. No such stanza exists in `~/.ssh/config` | MEASURED, §2.3 |
| `122-cloud-authority-provision.md:16,34` | P1 "Ubuntu **24.04**"; §1a "Success: `secratary-cloud`, Ubuntu **24.04**, `2` cores, ~`7900` MB total, ~`75G` on `/`" | The box runs **Ubuntu 26.04.1 LTS**, kernel `7.0.0-30-generic`. The cores / RAM / disk halves of the check pass; the OS half does not | MEASURED `/etc/os-release`, `uname -r`, §2.2 |
| `122-cloud-authority-provision.md:19,44-59` | "Join the tailnet **BEFORE** provisioning"; P4 authkey; `tailscale status \| grep secratary-cloud` present and not offline | **NOT DONE.** `command -v tailscale` → ABSENT; `systemctl is-active tailscaled` → `inactive`; no `/var/lib/tailscale`. `tailscale status` here lists 10 entries and none is `secratary-cloud` | MEASURED on both ends, §2.2/§2.3 |
| `122-cloud-authority-provision.md:95` (4a) | "Docker + Compose … `docker ps` works" | **NOT DONE** — `command -v docker` → ABSENT | MEASURED |
| `122-cloud-authority-provision.md:96,101` (4b) | `mesh-broker.service` on the new box; "4b is the one that removes today's outage class" | **NOT DONE.** The cloud box listens on nothing but `22` and `53`. The broker still runs **only** on `secratary` | `ss -lntp` on both hosts |
| `122-cloud-authority-provision.md:98` (4d) | `secretary-api` + dashboard on the cloud box, `/health` on `127.0.0.1:8002` | **NOT DONE.** Nothing on `:8002` there. `secretary-api.service` is still active on `secratary` (`uvicorn --host 0.0.0.0 --port 8002`) | `ss -lntp`; `systemctl list-units` |
| `122-cloud-authority-provision.md:132-142` (§5d, §5e) | promote the copy to `/home/zabz/personal-secretary-mvp/data/secretary.db`, then the four-part writer switch | **Path not used and switch not thrown.** The cloud box has **no `/home/zabz`** (`/home` is empty) — the copy is `/root/authority.db`. The office DB was still being written at 19:35Z | `ls -la /home /root` on cloud; `stat` on office |
| `122-cloud-authority-provision.md:166` | "`db-growth.mjs` is sampling it" | **NOT CONFIRMED.** I found no such script in this checkout and observed no growth sampler | see §4 |
| `122-cloud-authority-provision.md:173` | "The 201 GB in `~/secretary-backups` **does not move to this box**" | Still true — and it is still **local**, 176 G on the office disk. No object storage was configured | `du -sh`; `command -v rclone restic b2 aws s3cmd borg` all ABSENT |
| `118-hardware-plan.md:34` (I5) | `zabz-tech-linux`: "20.9 GiB free, **95.2 % used**" | **Could not re-measure** — the node is off the tailnet. `120:58` records it offline from 15:36:32Z on 2026-10-09 | `tailscale status` |
| `PROGRAM.md:13-22` | "**Five** machines on a Tailscale tailnet … each able to run real agent turns" | The five-node *compute* roster is still right, but there is now a **sixth machine** — `secratary-cloud` — which exists, is reachable, and is **not on the tailnet at all** | `tailscale status` vs `ssh root@178.156.194.1 hostname` |
| `PROGRAM.md:5` | "Last updated **2026-09-18**" | The programme moved on 2026-10-09: `119`, `120`, `121`, `122` were all written that day and none is in this checkout | `git rev-list --left-right --count main...origin/main` → `0  23` |
| `119-mesh-fanout-audit.md:38` | "**119** documents under `docs/mesh/`" | **66** `.md` in the checked-out tree; **71** on `origin/main` | `Get-ChildItem docs\mesh\*.md`; `git ls-tree origin/main` |
| `PROGRAM.md:24` | the broker is "on `secratary`, port 3091" | **Still literally true** — but `119` §2.3 demotes it from veto to optimisation, and `122` §4b intends to move it | `curl 127.0.0.1:3091/healthz` |

### 1.1 Three things about the *checkout itself*, which the brief assumed otherwise

- **`docs/mesh/119`–`122` do not exist in the checked-out tree.** They exist on `origin/main`. Local `main`
  is **0 ahead / 23 behind**. I read them with
  `git show origin/main:docs/mesh/<file>` — no branch switch, no reset, no checkout.
- **Two different documents are numbered 119** on `origin/main`:
  `119-dispatcher-precondition.md` and `119-mesh-fanout-audit.md`. That is a live numbering collision.
- **`123` is already taken elsewhere.** Commit `77bfae1` adds `docs/mesh/123-load-experiment…` on nine other
  refs (though not on `origin/main`). This file therefore *also* collides by number. I did not rename it,
  because the filename was specified to me.

---

## 2. WHAT IS ACTUALLY TRUE TODAY

### 2.1 `tailscale status | head -20` — from this machine, 2026-10-09 19:33Z

```
100.85.153.96    zabz-tech              lakewoodphoneandtech@  windows  -
100.76.204.64    ipad-air-5th-gen-wifi  lakewoodphoneandtech@  iOS      offline, last seen 5h ago
100.119.73.69    iphone-11-1            lakewoodphoneandtech@  iOS      -
100.118.10.22    iphone-11              lakewoodphoneandtech@  iOS      offline, last seen 3h ago
100.85.105.93    iphone-15-pro          lakewoodphoneandtech@  iOS      -
100.73.102.5     iphone-se-gen-2        lakewoodphoneandtech@  iOS      offline, last seen 2d ago
100.126.146.121  lakewooechsmini        lakewoodphoneandtech@  macOS    offline, last seen 4h ago
100.84.72.88     secratary              lakewoodphoneandtech@  linux    active; direct 192.168.50.77:41641, tx 11668656 rx 9664188
100.105.248.90   zabz-tech-linux        lakewoodphoneandtech@  linux    -
100.72.162.5     zabz-yoga-1            lakewoodphoneandtech@  windows  active; relay "nyc", tx 2223400 rx 7200632
```

**Read this carefully: ten entries, and `secratary-cloud` is not one of them.** So `122` §2's success check
(`tailscale status | grep secratary-cloud`) **fails today**. Note also that `secratary` is currently
**active, direct** — the same node `120` recorded offline for two hours earlier today.

### 2.2 The `secratary-cloud` measurement

The command the brief asked for **does not work**, and that failure is itself a finding:

```
$ ssh secratary-cloud "nproc; free -m|head -2; df -h /|tail -1; lsblk -o NAME,SIZE,ROTA"
ssh: Could not resolve hostname secratary-cloud: No such host is known.        [exit 255]
```

The box is reachable by address instead. This is the **raw** output of
`ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 "<script>"` (base64-shipped; see the note at the top),
I took **two** readings, and I keep them separate rather than merging them, because they disagree and the
disagreement is itself evidence.

**Run A — 2026-10-09 19:37:30Z** (`hostname; nproc; free -m; df -h /; lsblk -o NAME,SIZE,ROTA; uptime; head -3 /etc/os-release`):

```
secratary-cloud
--- nproc ---
2
--- free ---
               total        used        free      shared  buff/cache   available
Mem:            7742         906         289           4        6857        6835
--- df ---
/dev/sda1        75G   41G   32G  57% /
--- lsblk ---
NAME     SIZE ROTA
sda     76.3G    0
├─sda1    76G    0
├─sda14    1M    0
└─sda15  256M    0
sr0     1024M    0
--- uptime ---
 19:37:30 up  1:14,  2 users,  load average: 1.25, 1.34, 1.16
--- os ---
PRETTY_NAME="Ubuntu 26.04.1 LTS"
NAME="Ubuntu"
VERSION_ID="26.04"
```

**Run B — ≈19:39Z** (`command -v tailscale; systemctl is-active tailscaled; command -v docker; hdparm -tT /dev/sda; free -m; df -h /; uname -r; ss -lntp`):

```
secratary-cloud
--- tailscale present? ---
ABSENT: tailscale
no /var/lib/tailscale
inactive
--- docker ---
ABSENT: docker
--- disk read speed (hdparm -tT) ---
/dev/sda:
 Timing cached reads:   31116 MB in  1.99 seconds = 15633.82 MB/sec
 Timing buffered disk reads: 6056 MB in  3.00 seconds = 2018.38 MB/sec
--- free ---
               total        used        free      shared  buff/cache   available
Mem:            7742         891        5074           4        2079        6850
Swap:              0           0           0
--- df ---
/dev/sda1        75G   34G   38G  48% /
--- kernel ---
7.0.0-30-generic
--- listening ---
LISTEN 0 4096 0.0.0.0:22   0.0.0.0:*  users:(("sshd",pid=1318,fd=3),("systemd",pid=1,fd=69))
LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=502,fd=17))
LISTEN 0 4096 127.0.0.54:53   0.0.0.0:* users:(("systemd-resolve",pid=502,fd=19))
```

**The two runs disagree, and that is the finding.** Between them, roughly ninety seconds apart, `df` moved
from **41 G used / 32 G avail / 57 %** to **34 G used / 38 G avail / 48 %**, and free memory went from
**289 MiB** to **5074 MiB**. Something on that box is checkpointing and releasing several gigabytes at a
time. This is consistent with the `sqlite3` FTS conversion whose WAL I watched grow from 10.2 GiB to
10.83 GiB over the same window — **do not read either single reading as the box's steady state.**

**What that settles.** The box is real: **2 dedicated vCPU / 7742 MiB / 75 G NVMe / Ubuntu 26.04.1 LTS /
kernel 7.0.0-30-generic**, which matches `121` §6's `CCX13` recommendation on cores, RAM and disk. Note
**three deltas against what I was told**: the OS is **26.04.1**, not the **24.04** that `122` P1 and its §1a
success check require; `hdparm -tT /dev/sda` measured **2018.38 MB/s buffered** (cached 15633.82 MB/s), i.e.
*faster* than the "~1.1 GB/s" in my brief; and the box has **no swap configured at all** (`Swap: 0 0 0`),
while the office box it replaces has 4095 MiB (`121:39`). Neither `121` nor `122` mentions the new box's
swap at all — an omission, not a comparison.

**What that does not settle.** The box is **not provisioned**: `command -v tailscale` → ABSENT,
`command -v docker` → ABSENT, and `ss -lntp` shows **only `22` and `53`**. It has no `/home/zabz`.

### 2.3 The `secratary-ts` measurement — the live authority

`ssh secratary-ts "nproc; free -m|head -2; df -h /|tail -1; uptime"`, **2026-10-09 19:37Z**:

```
4
               total        used        free      shared  buff/cache   available
Mem:           23421        4387        1713          45       17744       19034
/dev/mapper/ubuntu--vg-ubuntu--lv  467G  359G   89G  81% /
 19:37:12 up  1:59, 11 users,  load average: 0.30, 0.61, 1.47
```

**`up 1:59` is the headline.** The office authority had been powered on for under two hours when I measured
it — consistent with `120` §0 (powered on by hand at 17:37:39Z). This is the fault the migration exists to
fix, and it is **still unfixed**.

### 2.4 The database, its size, and its composition

| what | value | command |
|---|---|---|
| live DB on `secratary` | `23,138,103,296` B = **21.55 GiB** | `ssh secratary-ts "stat -c '%s %n' /home/zabz/personal-secretary-mvp/data/secretary.db"` |
| live WAL / SHM | `67,108,864` / `131,072` B | `ls -la …/secretary.db*` |
| copy on `secratary-cloud` | `22,981,234,688` B = **21.40 GiB** at `/root/authority.db` | `ls -la /root` |
| its WAL | `11,631,398,632` B = **10.83 GiB** and **growing** (10.2 GiB eleven minutes earlier) | same |
| composition | `dsh_session_events` 7.28 GB + `fts_content` 7.20 GB + `fts_data` 2.92 GB = **17.40 GB of 20.61 GB** | READ `fts-convert.sh` header, quoting a 2026-10-07 `dbstat` |
| FTS row parity | `rows=1797992 fts_docs=1797992`, `hits(the)=618059`, rowid/key mismatches **0** | READ `/root/fts-convert.out` |

**The composition is the important part and it is a defect, not growth.** The corpus is stored **twice** —
once in `dsh_session_events.raw` and again inside the FTS5 index — because the virtual table was created
without `content=`. `fts-convert.sh` (READ on the cloud box) says so in its own header and names the audit
as **`D2954`, `docs/mesh/121`**. Two of those three identifiers resolve on `origin/main`; the audit id
`D2954` I did not chase.

### 2.5 The broker — location, roster, and health

`ssh secratary-ts "curl -s http://127.0.0.1:3091/healthz"` and `…/nodes?fresh=1`, **19:38Z**:

```
{ "ok": true, "schema": 1, "at": "2026-10-09T19:38:42.079Z", "startedAt": "2026-10-09T18:11:44.482Z",
  "uptimeSec": 5218, "nodes": 5, "reads": 205, "readFailures": 77, "cacheTtlSec": 15,
  "readTimeoutMs": 1500, "leaseTtlSec": 900,
  "leases": { "live": 3, "running": 3, "queued": 0, "byNode": { "zabz-tech": 3 }, "oldestAgeSec": 752 } }
```

**The broker is on `secratary` and nowhere else.** Its own health line reports **5 nodes** and, in the same
breath, **77 read failures out of 205 reads — a 37.6 % failure rate**. `119` §7 records that three nodes
were `unreachable` during its own direct-probe runs. The roster row I retrieved for `zabz-tech` shows
`maxChildren: 4`, `childrenRunning: 2`, `slots: 18` (basis: physical cores), `memorySlots: 24`, and
`accepts.maxChildren: 12` — i.e. **the broker's own two caps disagree with each other**, which `PROGRAM.md`
P332 already flags as "no cap on children per node exists anywhere".

### 2.6 Backups — the offsite path does not exist

| claim | measurement | command |
|---|---|---|
| `~/secretary-backups` | **176 G**, on the office `~/`, i.e. the same physical disk | `ssh secratary-ts "du -sh /home/zabz/secretary-backups"` |
| newest member | `20261009T181506Z` — a working, recent, **local** backup chain | `ls -la /home/zabz/secretary-backups` |
| other bulk | `phoenix-evidence` 27 G, `quarantine-debris` 6.4 G, `accounting-data` 6.3 G | `du -sh` |
| offsite tooling | `rclone`, `restic`, `b2`, `aws`, `s3cmd`, `borg` — **all ABSENT** | `for t in …; do command -v $t; done` |
| cron | `monitor-hetzner-backups`, `prune-backups …/secretary-backups`, `backup-phoenix-evidence` — **all local** | `crontab -l \| grep -i backup` |

**So `122` §6a ("nightly dump → object storage") is unbuilt, and the estate's only copy of 176 G of history
sits on the machine that goes off.** That is the single most important gap this document found.

### 2.7 This machine, for the record

`(Get-CimInstance Win32_Processor).NumberOfLogicalProcessors` → **32** (Intel i9-14900, 24 physical cores);
`Win32_ComputerSystem.TotalPhysicalMemory` → `68,339,048,448` B = **63.65 GiB**; free physical memory
**38,274,772 KiB ≈ 36.5 GiB**; `C:` 951.6 GB (245 GB free), `D:` 1863.0 GB (923.6 GB free). This
**confirms** `PROGRAM.md:18`'s "32 cores, 63.6 GB" and supersedes `121` §4's "51.9 GB free".

---

## 3. WHAT IS UNSETTLED

| open decision | why it is open | the doc that owns it |
|---|---|---|
| **Does the authority actually move?** | `121`/`122` plan it; the box exists; **nothing has switched**. The office DB was still being written at 19:35Z | `121` §6, §8 (Stages 3–5); `122` §5e; `112-single-source-of-truth.md` |
| **Does the tailnet get joined first, or is the order already known to be wrong?** | `122` P3/P4 call it "me"; measured absent. `122` §0 line 21-24 also warns the provisioner needs the authority over the tailnet — so P3/P4 block §3 | `122` §0, §2 |
| **Is `/root/authority.db` the same database as `secretary.db`?** | Same size class, different name and path; `fts-convert.sh` calls it disposable. **I did not verify identity** — the conversion is mid-write and I would not disturb it | `122` §5c makes this check mandatory |
| **Where does the 10.83 GiB WAL go?** | The cloud disk is 48 % full with the WAL still growing; `122` §7 sized 160 GB, and the box has 75 G | `122` §7 |
| **What is the DB's growth rate?** | `121` §2 measured a **47× growth in under a month** (490 MB → 22.9 GB) and explicitly calls it unexplained and the thing to measure first. `122` §7 says "fix that before moving it" | `121` §2, §8 Stage 0.2; `122` §7 |
| **Does the Wake-on-LAN path fire?** | `120` §1 line 46-49: built, documented, **never fired** | `120` §1; `121` §8 Stage 0.1 |
| **Does `secratary` flap while powered on?** | `121` §9.2 — needs a week of samples; none exist | `121` §9.2 |
| **Does object storage get bought, and at what price?** | `121` §9.6 marks the price UNVERIFIED; I did not price it either | `121` §5 Option C, §9.6; `122` §6a |
| **Does the resident engine use the failover placer?** | `119` §7: **NOT VERIFIED** — takes effect on next engine start (P210). The repo's working tree shows `plugin-remote-fanout/lib/index.js` and `provider.js` modified but uncommitted | `119` §7, §8 |
| **What is the cross-node v2 secret store?** | `119` §5: **NOT BUILT**; a decision with a recommendation, not an oversight | `119` §5 |
| **Can a remote child ever be two-way?** | `119` §6: **impossible in this engine**; the mailbox thread is the substitute | `119` §6; `110-subagent-visibility.md` |

---

## 4. What I could NOT determine — stated plainly

1. **Whether `/root/authority.db` is a copy of `secretary.db` or a different database.** They are the same
   size class and `fts-convert.sh` implies a copy, but I did not run the `integrity_check` + table-count
   comparison `122` §5c demands, because a `sqlite3` conversion was actively writing the file. **Do not
   treat them as identical on my authority.**
2. **Whether the fts-convert finished, succeeded, or is safe to interrupt.** Its output ends mid-conversion
   at "--- THE CONVERSION ---" and the WAL was still growing when I left.
3. **What `zabz-tech-linux` and `lakewooechsmini` look like now.** Both are off the tailnet; `118:34`'s disk
   figure for the former could not be re-measured.
4. **`db-growth.mjs`.** `122:166` says it is sampling the database. I did not find it in this checkout and
   did not find evidence it is running. **This is a claim I could neither confirm nor refute.**
5. **The audit id `D2954`**, cited by `fts-convert.sh` and attributed to `docs/mesh/121`. `121` does not
   contain that id. I did not locate it.
6. **Any page of the object-storage price question**, and therefore any all-in monthly cost.
7. **Whether the 176 G of backups is unique.** `121` §9.4 says it was never inventoried; it still has not
   been.
8. **The brief's premise, partly.** I was told "the new always-on cloud box was provisioned … to become the
   authority, replacing an ageing office desktop". The box **is** provisioned. It has **not** become the
   authority, and the office desktop **has not** been replaced — as of 19:38Z on 2026-10-09 the office box
   is still serving the company.

---

## 5. What I deliberately did not do

- **I did not switch branches, reset, or check out anything.** Everything from `origin/main` was read with
  `git show origin/main:<path>`.
- **I did not touch `secratary-cloud`'s database.** I read `stat`/`ls` only; the `sqlite3` conversion
  process was left alone.
- **I did not verify the `hdparm` number against a real write benchmark**, because that writes a file to a
  box whose disk is 48 % full and mid-migration.
- **I did not re-measure the other four nodes** (`zabz-yoga-1`, `zabz-tech-linux`, `lakewooechsmini`, and
  the iOS devices). Two are offline.
- **I did not resolve the `119` and `123` numbering collisions**, because the filename was specified.
- I created exactly one file under `docs/`: this one. The remote measurement commands wrote scratch output
  under `%TEMP%` on this machine only, and the mesh outbox under `~/.dsh-mesh-mailboxes/` is transport, not
  an estate artefact.
