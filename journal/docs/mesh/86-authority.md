# 86 — The authority: the broker becomes a service, and its swap stops reading 100%

**Program:** `docs/mesh/81-overnight-program.md` §0.8, §2, §3.2; stream **O5**.
**Reads:** `76-broker.md` (§1 the files, §6.4 the deploy lesson, §10 the amendments),
`79-elastic-cloud.md` §1 (what the authority is), `71-mesh-program.md` §2.1 and §2.2.
**Date:** 2026-09-17, 03:35–04:05Z. Every timestamp is UTC, taken from the machines' own clocks.
**Host:** `secratary` — Ubuntu 26.04 LTS, kernel 7.0.0-30-generic, 4 cores, 23,984,072 kB RAM,
Node v20.20.2, `sudo` NOPASSWD. Reached as `secratary-ts` with
`ssh -o BatchMode=yes -o ConnectTimeout=15`.

**Author:** stream O5, an agent session; **not** the owner. **Status: all three jobs done and
measured.** One thing is deliberately NOT done and §1.5 says why: **the authority was not
rebooted.**

**Provenance convention.** **MEASURED** = taken live by running the thing, with the command given.
**READ** = read out of source, with `path:line`. **DEV DECISION** = this stream's own call,
recorded here rather than escalated (development decisions are not owner decisions).
**UNVERIFIED** = stated as unknown, never as fact.

**What I did not do.** No engine was restarted. No data was destroyed: nothing under `/tmp` was
deleted, no file was rewritten in place, no `rm -rf`, no `git reset`, no commit. No other stream's
process was killed except the two that job 1 exists to replace (the hand-started broker) and my
own throwaway `systemd-run` probes. `personal-secretary-mvp` was not touched. The authority was not
rebooted.

---

## 0. The three answers in one paragraph each

1. **The broker is a systemd service now.** It was `node bin/mesh-broker.mjs --port 3091`, started
   by an agent at 00:01:38Z, pid in `/tmp/mesh-broker.pid`, log in `/tmp/mesh-broker.log` — a tmpfs
   path that a reboot empties. It is `mesh-broker.service`, `enabled`, running from
   `/home/zabz/mesh-broker` as `User=zabz`, logging to the journal. `systemctl restart` and
   `kill -9` both bring it back with a new MainPID and it answers afterwards (MEASURED, §1.5).
   **The reboot itself is UNVERIFIED** — five live agent SSH sessions from three other machines and
   a pending kernel upgrade made it a bad bet at 04:00Z, and §1.5 gives the evidence.
2. **The swap was not a leak, a service, or pressure. It was `/tmp`.** 4,095.9 MiB of a 4,096 MiB
   area was used; **69.2 MiB of it (1.7%) was any process's memory at all**, across 34 processes,
   the largest single holder being 14 MiB. `mincore(2)` over 19,855 files under `/tmp` found
   **3,895.8 MiB of them not resident** — i.e. in swap. Faulting those files back in reclaimed
   **4,023.6 MiB** and the swap went from **100.0% to 1.8%**, with the delta in `Shmem`
   (+4,024 MiB) equal to the swap freed to within 0.4 MiB. Nothing was deleted. `vm.swappiness`
   60 → 10, persisted. §2.
3. **The broker's reserve was the one node's number applied to four machines.** The gate's
   `max(2 GiB, 12% of physical)` is the governor's own rule (`governor.js:126`); `3885` is what it
   yields on the 31.6 GB laptop and nothing else. The broker now derives it **per node from that
   node's own `mem.totalMiB`**, prints the derivation in the rationale, and `3885` survives only as
   the fallback for a node that reports no total. On the 64 GB desktop the old literal
   under-reserved by **3,936 MiB** — ~24 slots of headroom claimed and not had. §3.

---

## 1. The broker stops being a hand-started process

### 1.1 What was there before (MEASURED 2026-09-17 03:35Z)

```
$ ps -eo pid,ppid,user,lstart,etime,rss,cmd | grep mesh-broker
1894245  1  zabz  Thu Sep 17 00:01:38 2026  03:33:47  39320  node bin/mesh-broker.mjs --port 3091
$ ls -la /tmp/mesh-broker.pid /tmp/mesh-broker.log
-rw-rw-r-- 1 zabz zabz    8 Sep 17 00:01 /tmp/mesh-broker.pid      -> "1894245"
-rw-rw-r-- 1 zabz zabz 1601 Sep 17 03:34 /tmp/mesh-broker.log
$ findmnt /tmp
/tmp  tmpfs  tmpfs  rw,nosuid,nodev,nr_inodes=1048576,inode64,usrquota
```

Four things were wrong with that, and only the first is about supervision:

* **ppid 1**: the process had already been orphaned; nothing would restart it.
* **`/tmp` is a tmpfs.** Both the pidfile and the log are gone on reboot *by construction* — the
  log could never have been evidence of anything that survived.
* The command line is **relative** (`bin/mesh-broker.mjs`), so the process was running whatever
  `/home/zabz/mesh-broker-run` happened to contain at 00:01:38Z. Nothing recorded which build that
  was.
* `deploy/mesh-broker.service` (stream S5's proposal) pointed at
  `WorkingDirectory=/home/zabz/mesh-broker` and `/home/zabz/mesh-broker/bin/mesh-broker.mjs`.
  **That path did not exist** — the deployed copy lived in `/home/zabz/mesh-broker-run`, and the
  unit had never been installed. `/home/zabz/mesh-broker-run/mesh-broker/` also exists: a nested
  copy left by the `scp -r` footgun `76-broker.md` §6.4 records.

### 1.2 The unit, and every change from the S5 proposal

Installed sha256 **`c9a1e8f8f052c572644077d0e9b8b4ea7b286dd9f6297b4f2b07c8ba2cd421aa`** at
`/etc/systemd/system/mesh-broker.service` (identical to
`packages/mesh-broker/deploy/mesh-broker.service` in the tree — checked, §1.3).

| change | why |
|---|---|
| `ExecStart` gains `--host 127.0.0.1 --port 3091 --config /home/zabz/mesh-broker/nodes.json` | Absolute, explicit, and no dependence on the process's cwd or on a code default. The owner's decision is that a placed job must not be requestable from the tailnet; naming the bind in the unit is how that decision is visible where it is enforced. |
| `After=network-online.target tailscaled.service` | The broker reads each node **through the tailnet**. It was previously ordered only against the network, so on a boot where `tailscaled` is slower, its first reads would all fail and it would look like a dark mesh for the first 15 s (the cache window). |
| `User=zabz` / `Group=zabz` added | The S5 proposal had `User=zabz`; the group is explicit so the file modes below are unambiguous. |
| `StandardOutput=journal` + `SyslogIdentifier=mesh-broker` | The log must outlive a reboot and be readable beside the unit that produced it. `/tmp` cannot do that. |
| `RestartSec=2`, `Restart=always` kept | Kept from the proposal. A SIGKILL is restarted (MEASURED, §1.5). |
| **The rate limit is deliberately NOT disabled** (`StartLimitIntervalSec=0` was considered and rejected) | A single crash always restarts. A broker that dies five times in ten seconds is broken code; on the company's 4-core authority a bounded stop-and-report beats an unbounded restart loop. `systemctl status` says which happened. |
| Hardening kept: `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, `ProtectSystem=strict`, `ProtectHome=read-only`, `ProtectKernel*`, `ProtectControlGroups/Clock/Hostname`, `RestrictNamespaces/Realtime/SUIDSGID`, `LockPersonality`, `RemoveIPC`, `SystemCallArchitectures=native`, `UMask=0027`, `CapabilityBoundingSet=` | READ: the broker reads one JSON file, makes TCP requests, and holds a few kilobytes in memory. It needs no capability, no device and no writable path. (This is why there is no `StateDirectory=` and no writable mount: **it stores nothing** — §2.2's "nothing it can go stale on" is unchanged.) |
| `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK` | Egress TCP + DNS. NOT `AF_PACKET`/`AF_RAW`: it has no business opening raw sockets. |
| **REMOVED: `IPAddressDeny=any` + `IPAddressAllow=localhost`** | It broke the service. See §1.4 — this is the most important line in this document. |
| `ProtectProc=invisible` / `ProcSubset=pid` considered and NOT used | Not measured to be safe with Node's own `/proc` reads (`os.cpus()`, interface enumeration), and it protects against nothing the owner asked for. An untested sandbox knob is where §1.4 came from. |
| `Documentation=` points at `/home/zabz/mesh-broker/PROVENANCE.md` | The deployed copy carries its own manifest and points back at the source of truth. |

### 1.3 How it was installed, and what "verified" means here

`packages/mesh-broker/deploy/install-authority.sh` (new, this stream) does the whole thing
idempotently and **proves the copy rather than trusting the exit code**:

```
tar -czf o5-broker.tgz -C <harness-config>/packages mesh-broker      # on the laptop
scp o5-broker.tgz secratary-ts:/tmp/ && ssh secratary-ts "tar -xzf /tmp/o5-broker.tgz -C /home/zabz/o5-staging"
ssh secratary-ts "sudo bash /home/zabz/o5-staging/mesh-broker/deploy/install-authority.sh /home/zabz/o5-staging/mesh-broker"
```

The script: (1) copies the tree with `install(1)` — never `scp -r` — into
`/home/zabz/mesh-broker`; (2) writes `PROVENANCE.md` with the sha256 of every deployed file, taken
**from the deployed copy**; (3) runs the package's 60 tests **from the deployed path**; (4) retires
the hand-started broker and the `/tmp` pidfile; (5) installs, enables and restarts the unit; (6)
asserts the listening pid **is** the systemd `MainPID` and that the bind is `127.0.0.1` only; (7)
tries the LAN and tailnet addresses and fails if either answers; (8) asks the four verbs and
asserts the service **can read the mesh**; (9) restarts and SIGKILLs it.

Two independent hash comparisons, because a copy that drifts silently is a copy nobody can trust:

* `deploy/verify-deploy.sh <source-tree>` — re-hashes both trees, the installed unit, and the
  running process's own `cmdline`; output ends
  `NO DRIFT: the deployed tree, the installed unit and the running process all agree.` It also
  prints `running : pid 1991785: /usr/bin/node /home/zabz/mesh-broker/bin/mesh-broker.mjs --host
  127.0.0.1 --port 3091 --config /home/zabz/mesh-broker/nodes.json`.
* A laptop-side comparison of `Get-FileHash` against the deployed `sha256sum` output:
  `files local=20 remote=20` … `IDENTICAL: every one of 20 files matches byte-for-byte between this
  laptop and the authority`.

The script's own final line: **`20 passed, 0 failed`**.

### 1.4 Loopback: what enforces it, and the hardening that had to be removed

The owner's decision — *a placed job must not be requestable by any device on an allow-all
tailnet* — is enforced by the **bind**, and verified three ways on every install:

```
LISTEN 0  511  127.0.0.1:3091  0.0.0.0:*  users:(("node",pid=1991466,fd=18))
PASS  a request to this host's own LAN address (192.168.50.77) does NOT get through (curl exit 7)
PASS  a request to the tailnet address (100.84.72.88) does NOT get through (curl exit 7)
PASS  tailscale serve publishes nothing on 3091     # it publishes 3086 -> the gate, and nothing else
```

**The unit first shipped with `IPAddressDeny=any` + `IPAddressAllow=localhost`, and that was
wrong.** `IPAddressDeny`/`Allow` apply to **egress as well as ingress**, so the broker could no
longer reach a single node. MEASURED, the service's own `GET /nodes?fresh=1` immediately after
that install:

```
reads 8 readFailures 8
  zabz-tech          unreachable  attempts=2 latency=4001 elapsed=5503
         timed out after 4000 ms (hard wall-clock deadline)
  zabz-yoga-1        unreachable  attempts=2 latency=4001 elapsed=5503
  zabz-tech-linux    unreachable  attempts=2 latency=4000 elapsed=5504
  secratary          unreachable  attempts=2 latency=4001 elapsed=5504
```

Resolved by a controlled experiment rather than by reasoning — a throwaway unit with the same two
options:

```
$ systemd-run --pipe -q -p IPAddressDeny=any -p IPAddressAllow=localhost \
    /usr/bin/curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 \
    https://zabz-tech.tail93e6e6.ts.net/mesh/capacity
000                                   # blocked
$ curl -s -o /dev/null -w '%{http_code}\n' https://zabz-tech.tail93e6e6.ts.net/mesh/capacity   # outside the sandbox
200                                   # so the host's egress is fine; the sandbox is the cause
$ systemd-run --pipe -q -p IPAddressDeny=any -p IPAddressAllow=localhost \
    /usr/bin/curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3086/mesh/capacity
200                                   # loopback is unaffected, which is why the blind spot was easy to miss
```

`SocketBindDeny=any` + `SocketBindAllow=127.0.0.1:3091` — the one option that *would* have
restricted the bind without touching traffic — is not usable on this systemd. Every documented
spelling is rejected:

```
SocketBindAllow=:3091 / 127.0.0.1:3091 / ipv4:127.0.0.1 / ipv4:127.0.0.1:3091 / tcp:127.0.0.1:3091
  -> Failed to parse SocketBindAllow= value '<x>': Invalid argument
```

**The lesson, and it is the reason this section exists.** The first install reported
**19 passed, 1 failed** — and the one failure was a bug in my own grep (`"released":true` against a
pretty-printed `"released": true`). Everything else was green: the port, the loopback rule, all
four verbs, the restart, the SIGKILL. **And the broker could not see a single node.** A sandbox rule
that disables the service's only job is not hardening, and "the port answers" is not the assertion
that matters. `install-authority.sh` step 8 now asserts *"the service can READ the mesh"* by name
and fails the install if no node answers. It is the assertion whose absence let a blind broker pass.

Residual risk, stated: this leaves a future edit of `--host` unprotected by the kernel. That edit
fails step 6 (`the listening pid IS the systemd MainPID` + `bound to 127.0.0.1 only`) and step 7
(the LAN/tailnet probes) of `install-authority.sh`, loudly and by name, on the next install.

### 1.5 It comes back on its own — and the reboot, which was NOT performed

**Supervised restart and a crash (MEASURED, from the install run):**

```
PASS  systemctl restart: MainPID 1991466 -> 1991681
PASS  answers after a supervised restart
   sending SIGKILL to 1991681 (the crash systemd cannot distinguish from a fault)
PASS  SIGKILL: MainPID 1991681 -> 1991785, service active
PASS  answers after the SIGKILL restart
journal: Sep 17 03:45:21 secratary systemd[1]: Started mesh-broker.service ...
         Sep 17 03:45:21 secratary mesh-broker[1991785]: mesh-broker listening on http://127.0.0.1:3091  (port 3091)
```

**Boot wiring, MEASURED:** `UnitFileState=enabled` and
`/etc/systemd/system/multi-user.target.wants/mesh-broker.service -> /etc/systemd/system/mesh-broker.service`.
That symlink plus a unit whose `ExecStart` names absolute paths is the mechanism that starts it at
boot. **That the mechanism works has not been executed — it is UNVERIFIED, and it is the one line
of §0's definition of done this stream did not close.**

**Why the reboot was not performed.** The brief permits it *"IF you have first confirmed by listing
what is running that the reboot is safe for the company's services"*. Listing what was running at
03:35–03:47Z:

* **Five established SSH sessions from three other machines**, i.e. other agents' work in flight:
  `ss -tnp state established '( sport = :22 )'` shows `100.72.162.5` (this laptop, `zabz-yoga-1`)
  four times, `100.85.153.96` (`zabz-tech`) once, and `100.126.146.121` (`lakewooechsmini`); three
  of them are running `ps_mcp_server.py`, and one had **4,076 bytes sitting in its receive queue**,
  i.e. streaming output at that moment.
* **Another stream is driving the broker this minute.** The journal shows a placement that is not
  mine, `03:42:43.698Z place -> zabz-tech position=1 tier=queued fleet children=6
  lease=mu4zhu5u-16l6b-2-e98ac35b`, **2 ms after** this stream's own `children=2` placement. (It is
  also a live demonstration of §9 of `76-broker.md`: my `systemctl restart` replaced the process
  between that placement and its `/done`, so the `/done` at `03:42:44.263Z` — logged by the *new*
  pid — answered `released=false`. A restart costs live leases; that is by design, and the other
  stream should know it was this stream's restart that did it, not a fault.)
* **A reboot would APPLY a pending kernel upgrade.** `/var/run/reboot-required` names
  `linux-image-7.0.0-31-generic`, `linux-base`, `libc6`; the running kernel is `7.0.0-30-generic`.
  A reboot is therefore not "prove the unit comes back", it is "change the kernel of the company's
  authoritative server, unattended, at 04:00Z".
* There is **no IPMI/console path from here**, and the box is on the office LAN. If a new kernel
  failed to boot, the company is down until a human is physically at it — while the owner is
  asleep and the shop opens at 12:30.

The asymmetry is what decided it: the upside of the test is one verified line; the downside is the
authoritative server not coming back with nobody awake to fix it. The brief's own fallback is
taken: restart + SIGKILL are measured, and the reboot is stated as unverified.

**What a reboot would additionally test**, for whoever does it with a console in reach: that
`WantedBy=multi-user.target` + the symlink actually start the unit; that `tailscaled` is up before
the broker's first read (the `After=` ordering); and that nothing in the unit depends on state that
only existed in the running boot. If the authority is ever rebooted for other reasons, the
verification is `systemctl is-active mesh-broker && curl -s 127.0.0.1:3091/healthz` and the
`/nodes` read-failure count.

**Everything else on the box was already enabled and came through untouched** —
`secretary-api`, `secretary-dashboard`, `phone-engine`, `phone-gate`, `cloudflared`, `tailscaled`,
`vscode-tunnel`, `xvfb-login`, `cron`, `ssh`, `ufw` are all `enabled` (MEASURED with
`systemctl is-enabled`), `systemctl list-jobs` was empty, there were **zero failed units**, and the
next `secretary-backup.timer` firing was 2 h 23 min away with no backup in flight. (All still
`active` after this stream's work; the one failed unit at the end of the session was my own
throwaway `systemd-run` probe, and it was cleared with `systemctl reset-failed`.)

### 1.6 The files a reader will look for

| path | what |
|---|---|
| `packages/mesh-broker/deploy/mesh-broker.service` | the unit, installed; sha256 in §1.2 |
| `packages/mesh-broker/deploy/install-authority.sh` | the idempotent install + 20 assertions |
| `packages/mesh-broker/deploy/verify-deploy.sh` | the anti-drift check (tree vs installed unit vs running process) |
| `packages/mesh-broker/deploy/authority-swap-probe.py` | **new** — `mincore(2)` + `VmSwap` over every pid and every file under `/tmp`: *whose* memory is in swap (§2.2) |
| `packages/mesh-broker/deploy/authority-swap-fix.py` | **new** — faults the swapped tmpfs pages back in and sets `vm.swappiness`, with a `MemAvailable` guard, deleting nothing (§2.4) |
| `packages/mesh-broker/deploy/secratary-smoke.sh` | **changed**: if the unit is installed it now *uses the service* instead of starting a second broker on 3091. The old behaviour would have died of `EADDRINUSE` and then had every curl answered by the service — `76-broker.md` §6.4's "green while proving nothing", one layer up |
| `/home/zabz/mesh-broker/` on the authority | the deployed tree + `PROVENANCE.md` |
| `/home/zabz/o5-staging/mesh-broker/` | the reference tree `verify-deploy.sh` compares against |
| `/tmp/mesh-broker.pid.retired-by-o5-<ts>` | the retired pidfile — **moved, not deleted**: it is what `secratary-smoke.sh` would `kill`, and pids get reused |
| `/home/zabz/mesh-broker-run/` | **now superseded and stale.** Left in place: it is not this stream's to delete, and other streams may still be pointed at it |

---

## 2. The authority's swap

### 2.1 The answer in one line

**4,095.9 of 4,096 MiB was used, and 4,026.7 MiB of it belonged to no process: it was `/tmp`.** It
is the "swapped out long ago and never needs to come back" case, not a leak — and the swap is now
**1.8% used**, with nothing deleted and no service touched.

### 2.2 What holds it — the measurement

Two independent readings, because the whole question is *whose* memory it is, and `free(1)` cannot
answer that.

**Reading 1 — process anonymous memory in swap** (`VmSwap:` in `/proc/<pid>/status`, every pid,
MEASURED 03:42:32Z):

```
=== process ANONYMOUS memory in swap: 70,840 kB (69.2 MiB) across 34 process(es) ===
     14,448 kB  pid 1288     /usr/bin/python3 /usr/share/unattended-upgrades/unattended-upgrade-shutdown
     14,120 kB  pid 1228     /usr/bin/python3 /usr/bin/networkd-dispatcher --run-startup-triggers
      7,360 kB  pid 2515526  python3 /home/zabz/harness-config/scripts/phone-redirector.py --port 3087
      4,316 kB  pid 3279526  /usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state ...
      4,300 kB  pid 1587     /home/zabz/.local/bin/code tunnel --name ezabz-secretary ...
      2,592 kB  pid 2020610  /usr/libexec/fwupd/fwupd
      2,052 kB  pid 2495411  /usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml tunnel run
      ... 27 more, the rest under 2 MiB each ...

  swap used minus process VmSwap = 4,123,340 kB (4,026.7 MiB)
```

**Reading 2 — how much of `/tmp` is not in RAM.** `mincore(2)` per page over every regular file
≥ 4 KiB under `/tmp` (`packages/mesh-broker/deploy/authority-swap-probe.py`, run as root, MEASURED
03:42:32Z):

```
  files measured      : 19,855  (0 could not be mapped, skipped)
  bytes on the tmpfs  : 6,229,033,582  (5940.5 MiB)
  RESIDENT in RAM     : 2,144,041,844  (2044.7 MiB)
  NOT resident (=swap): 4,084,991,738  (3895.8 MiB)

  the 20 files holding the most swapped-out pages
     184.9 MiB swapped of  185.0 MiB  /tmp/comms-test.db
      35.0 MiB swapped of   35.1 MiB  /tmp/mob/liveprof/optimization_guide_model_store/.../model.tflite
      34.8 MiB swapped of   35.1 MiB  /tmp/mob/prof1/optimization_guide_model_store/.../model.tflite
      22.2 MiB swapped of   22.2 MiB  /tmp/wt-green/lpt-hub/docs/.../tools/apktool.jar
      20.7 MiB swapped of   20.7 MiB  /tmp/mob/prof1/WidevineCdm/.../libwidevinecdm.so
      19.1 MiB swapped of   19.2 MiB  /tmp/ha-config/.git/objects/pack/pack-069bd686...pack
       4.7 MiB each, x 10                /tmp/tmp*.db-wal          (SQLite WAL files from other sessions)

  process anon in swap      :       70,840 kB
  tmpfs files in swap       :    3,989,250 kB
  swap used (authoritative) :    4,194,180 kB
  accounted for             :    4,060,090 kB (96.8% of used swap)
```

`SwapCached` 139,256 kB and `SwapTotal` 4,194,300 kB / `SwapFree` 116 kB complete the picture:
**100.0% used, 0.1 MiB free.**

### 2.3 What it is NOT

* **Not a leak.** A leak shows up as process anonymous memory that keeps growing. The 34 processes
  that hold *any* swap hold 69.2 MiB between them, and the largest single holder is 14 MiB. The
  read was repeated twice, 10 minutes apart, with the same shape.
* **Not a company service.** `secretary-api` (the 3.4 GB uvicorn process, the biggest thing on the
  box) held **0 kB** of swap. `personal-secretary-mvp`'s four `ps_mcp_server.py` processes held
  0 kB. Nothing of the company's was evicted; the company's own runtime is resident.
* **Not active pressure.** `vmstat 1 5` sampled at 03:35Z showed `si/so` of `9/44` once (from the
  sampling window's own churn) and `0/0` for the remaining four samples. `free -m` showed
  `available 16,104 MiB` of 23,421 MiB with `buff/cache 12,639 MiB`. The kernel had 12.6 GB of
  reclaimable cache sitting beside a full swap area and had chosen not to touch it.
* **It IS what `76-broker.md` §10.2 assumed it was — `secratary` reports
  `mem.swapUsedPct 100.0`** — and the broker's halving of its slots was therefore *correct on the
  number*. What the number did not say is that the memory was cold files rather than pressure; §2.4
  is the difference between the two, measured.

### 2.4 The fix: what was changed, and the proof

Three ways to reclaim it were considered. Two were rejected:

1. **Delete the stale `/tmp` scratch** — the durable fix, and **NOT performed**: it is other
   sessions' and other streams' work (`/tmp/wt-green` is a git worktree, `/tmp/mob/prof1` and
   `/tmp/phone-layout-check-profile` are browser profiles the phone gate uses *this minute*,
   `/tmp/ha-config` is a checkout), `rm -rf` is forbidden without a per-action yes for that exact
   thing, and an unread `find -delete` at 04:00Z on a live company server is how data is lost.
2. **`swapoff` / `mkswap` / `swapon`** — reclaims everything, but it must allocate all 4 GiB at once
   and it removes the memory outlet entirely for the duration. Real risk on the authoritative
   server, with no upside over (3).
3. **Read the files back in.** ✅ Faulting a swapped-out tmpfs page in **frees its swap slot** and
   returns the page to RAM. It is incremental, interruptible, cannot OOM-kill a service (the pages
   it pulls in stay swappable), and destroys nothing.

`packages/mesh-broker/deploy/authority-swap-fix.py` (run as root at 03:45:34Z; it refuses to run if
`MemAvailable` is not at least twice the swap to be reclaimed — it saw 15,800 MiB available and
proceeded):

```
before: swap used 4,194,152 kB (4095.9 MiB) of 4,194,300 kB | MemFree 1317 MiB  MemAvailable 15800 MiB | Shmem 1994 MiB
read 5984 MiB from 36,615 file(s) under /tmp in 57.8 s (0 unreadable, skipped). Nothing was written and nothing was deleted.
after : swap used    73,992 kB (  72.3 MiB) of 4,194,300 kB | MemFree  518 MiB  MemAvailable 12099 MiB | Shmem 6018 MiB
REclaimed by faulting the pages back in: 4,120,160 kB (4023.6 MiB)

vm.swappiness is 60; setting it to 10
final : swap used 73,992 kB (72.3 MiB) ... Shmem 6018 MiB
net swap change from start: 4,120,160 kB (4023.6 MiB); swap is now 1.8% used
```

**The proof that it was tmpfs and not something else.** `Shmem` rose by 6,018 − 1,994 = **4,024
MiB** while swap fell by **4,023.6 MiB**. Those are the same number to within 0.4 MiB, and they
have to be: the pages that left swap entered shared-memory accounting. Nothing else in the machine
moved by a comparable amount.

**The second change: `vm.swappiness` 60 → 10**, persisted in
`/etc/sysctl.d/99-mesh-authority-swap.conf` (reversible with `sysctl -w vm.swappiness=60` and
`rm`). The mechanism is not mysterious: 12.6 GB of clean page cache was sitting unused while the
kernel evicted cold tmpfs pages to swap, because 60 is the desktop default. This is the change that
makes the reclaim stick — without it the next memory-pressure event would refill the swap area with
the same cold files.

### 2.4.1 The trade, stated honestly, because "swap fixed" is half the sentence

Faulting the pages back in moved memory from swap to RAM; it did not create any. The authority now
has 4 GiB of free swap **and 4 GiB less free RAM**:

| | before the reclaim | after |
|---|---|---|
| `Swap used` | 4,095.9 MiB (100.0%) | 72.3 MiB (1.8%) |
| `MemFree` | 5,722 MiB (03:35Z) / 1,317 MiB (03:45Z) | 977 MiB |
| `MemAvailable` | 16,104 MiB (03:35Z) / 15,800 MiB (03:45Z) | 12,254 MiB |
| `Shmem` (the tmpfs, resident) | 1,994 MiB | 6,018 MiB |

So this is **not** "the machine got 4 GiB of headroom"; it is "the machine's headroom moved from a
swap area full of dead files back to where the broker can measure it". What makes it a net win:

* the broker's ranking was reading a number that described a tuning artefact, and the authority was
  scored at 1 slot instead of its real 3 (`§2.4`'s table);
* a full swap area is **no outlet at all** — the kernel had 12.6 GB of cache to drop and could not
  use swap once it was full, which is the condition that turns a spike into an OOM kill;
* nothing was deleted, so the trade is reversible in either direction.

**And the residual truth is still the tmpfs.** With `/tmp` a 12 GiB tmpfs holding 5.9 GB of cold
scratch, the machine has to put those pages *somewhere*: either RAM (what I chose) or swap (what it
was doing). Neither is free. **The only fix that creates headroom is making `/tmp` smaller**, which
is §2.5's job and needs the owner's yes.

**Swap is not a fixed number — it is a running process, and the reader should treat it that way.**
The sequence, measured: 72.3 MiB (1.8%) immediately after the reclaim at 03:47Z; **271 MiB (6.6%)**
by 03:50Z; then **flat** — five samples 20 s apart went `277612, 277612, 277604, 277596, 277596` kB
with `vmstat`'s `si`/`so` columns at `0 0` throughout. So the ~200 MiB that reappeared under the
machine's ordinary workload (other streams' probes, the browser profiles under `/tmp`) **settled**,
it did not continue. That is normal small-scale page-out and it is nowhere near the 90% threshold —
but it is the reason the DoD's claim is *"not at 100%"* rather than *"empty"*. **A future reader who
finds this section should re-measure before quoting 1.8%**, with the one-liner
`awk '/^SwapTotal:/{t=$2} /^SwapFree:/{f=$2} END{print (t-f)/1024" MiB used, "(t-f)*100/t"%"}' /proc/meminfo`.

**Verified afterwards (MEASURED 03:47Z):**

```
$ free -m
               total        used        free      shared  buff/cache   available
Mem:           23421       11407         417        6017       17993       12014
Swap:           4095          72        4023
$ vmstat 1 5 | tail -3        # si/so are 0 0, 0 0, 0 0
$ systemctl is-active secretary-api secretary-dashboard phone-engine phone-gate tailscaled cloudflared
active active active active active active
```

**And the point of the whole thing, in the broker's own numbers.** `GET /nodes?fresh=1` before and
after the fix:

| node | slots before | slots after | memorySlots | coreSlots | swapUsedPct | halved | reserve |
|---|---|---|---|---|---|---|---|
| `zabz-tech` | 18 | 18 | 24 | 18 | 0 | false | 7821 |
| `zabz-yoga-1` | 12 | 12 | 22 | 12 | 0 | false | 3885 |
| `zabz-tech-linux` | 4 | 4 | 24 | 4 | 15.3 | false | 2048 |
| **`secratary`** | **1** | **3** | 24 | 3 | **1.8** | **false** | 2811 |

The authority was losing two thirds of its placeable capacity to a swap area full of cold scratch.
Its own rationale line now reads:

```
secratary: 3 free slot(s) of 24, 24 memory slot(s), 3 core slot(s) of 4 physical x 0.75 -> effective 3, 1 after 2 child(ren), transport v1 unmeasured
```

### 2.5 What I deliberately did not do, and what would make this permanent

* **Nothing was deleted.** 23,706 files under `/tmp` are older than 2026-09-16T00:00Z and 8,841 are
  newer than 2026-09-17T00:00Z — `/tmp` is in active use *and* full of stale scratch, and telling
  those two apart safely is a per-action decision, not a batch one. `du -sh /tmp` is still 5.9 G.
* **`/tmp` is a 12 GiB tmpfs** — systemd's default is half of RAM, and on a 23 GB host that is
  12 GiB of scratch allowed to compete with the Kubernetes-free but still memory-hungry API, the
  DSH engine and the browser profiles the phone gate keeps there. It self-cleans at 10 days
  (`systemd-tmpfiles-clean.timer`, which ran 5 h before this session), so it will settle around
  5-6 GB and stay there.
* **The durable fixes, in the order I would do them, all needing the owner's yes because they
  destroy data or change what the machine can do:**
  1. Delete `/tmp` scratch older than ~2 days **that no process has open** (`lsof +D /tmp`), and
     lower the `tmpfiles.d` age for `/tmp` from 10 d to 2 d so it stays clean. Recovers ~4-5 GiB of
     tmpfs and the RAM behind it.
  2. Cap the `/tmp` tmpfs (`tmp.mount` `size=`). Not done: a 5.9 GB directory under a 4 GiB cap
     fails writes with `ENOSPC`, which would break whichever stream is mid-write — that is a change
     to attempt knowingly, not opportunistically.
  3. Consider whether `secratary` should run fleets at all (§3 of `81-overnight-program.md` says its
     transport is `null`), because 4 cores is 3 slots.
* **Would the swap refill?** Under real memory pressure, yes — that is what swap is for. What is
  fixed is that it no longer fills with *cold files* while reclaimable cache sits idle, and that a
  full area with cold contents can be reclaimed in a minute without deleting anything. If
  `swapUsedPct` reads high again,
  `python3 packages/mesh-broker/deploy/authority-swap-probe.py` answers "whose memory is it" in
  about a minute, and `…/authority-swap-fix.py` reclaims it without touching a byte of data. Both
  are in the repo rather than in a scratch drawer on one laptop, because a diagnostic that only
  exists on the machine that ran it is not a diagnostic.

---

## 3. One reserve, not two

### 3.1 The two numbers

* `71-mesh-program.md` §2.1, on the gate: *`min(floor((freeMiB - reserve) / 160), 24)`,
  `reserve = max(2 GiB, 12% of physical)`, floored at 4* — reported as `governor.budgetSlots`.
* `71-mesh-program.md` §2.2, on the broker: `memorySlots = min(floor((freeMiB - 3885) / 160), 24)`
  — the literal `3885` (READ: `lib/scoring.js:50` before this stream's change).

Both claimed to be the governor's arithmetic. `READ packages/plugin-health/lib/governor.js`:

```js
 77  const RESERVE_FRACTION = 0.12;
 78  const RESERVE_MIN_BYTES = 2 * 1024 * 1024 * 1024;
126  const reserveBytes = Math.max(RESERVE_MIN_BYTES, Math.round(totalBytes * RESERVE_FRACTION));
```

`totalBytes` is **that host's** RAM (`os.totalmem()`, governor.js:124). The reserve is therefore a
**per-host** quantity, and `3885` is what it produces on exactly one machine: 12% of a 31.6 GB
laptop. (§2.2's own comment said so — *"12% of 31.6 GB"* — which is why this is a one-node number
rather than an arbitrary one.)

### 3.2 The measurement, on the four nodes that exist

MEASURED 2026-09-17 03:36Z and 03:45Z from each node's own §2.1 document — `mem.totalMiB` is a
field the gate has been reporting all along:

| node | `mem.totalMiB` | governor's own reserve | frozen `3885` | difference | the node's own reading |
|---|---|---|---|---|---|
| `zabz-tech-linux` | 11,673 | **2,048** (the 2 GiB floor binds) | 3885 | over-reserved by 1,837 MiB | 6 physical cores |
| `secratary` | 23,422 | **2,811** | 3885 | over-reserved by 1,074 MiB | 4 physical cores |
| `zabz-yoga-1` | 32,373 | **3,885** | 3885 | **exact** | 16 physical cores |
| `zabz-tech` | 65,173 | **7,821** | 3885 | **UNDER-reserved by 3,936 MiB** | 24 physical cores |

### 3.3 The decision

**The gate's derivation is right and the broker now has it — per node, from that node's own
`mem.totalMiB`. `governor.budgetSlots` is advisory and unconsumed. `3885` survives only as the
documented fallback for a node that reports no total memory.**

Why the broker owns the arithmetic rather than consuming the gate's number, in the words of the
frozen contract itself: §2.1's last rule already says *"Residency/budget arithmetic belongs to the
BROKER, not here: the gate reports measurements only."* And the gate's number is unusable as an
input even if it were wanted, because `governor.js:131-132` **caps it at 24 and floors it at 4**:
consuming it would turn "this node has no measurable headroom" into *4 slots*, and would hide the
difference between a 64 GB desktop and a 24-core one behind the same cap. The broker needs the
uncapped arithmetic, so it derives it.

Why per node rather than one global number: the broker's job is to rank **heterogeneous** nodes
against each other. A reserve that is 1.8 GiB too large on one node and 3.9 GiB too small on
another does not rank them, it mis-ranks them — and the direction of the error on `zabz-tech` is the
dangerous one, because that is the node work actually lands on (it won this stream's placement at
03:45:14Z with `score 18`).

### 3.4 The code change — DECLARED, because it is outside this stream's file scope

The brief allows `packages/mesh-broker/lib/**` **only if the decision requires a code change**, and
it does: the decision *is* a change to the arithmetic. It is two files.

**`lib/scoring.js`**
* `RESERVE_MIB = 3885` is **kept and still exported** — now documented as the fallback and as the
  value `max(2 GiB, 12% of physical)` yields on a 31.6 GB machine.
* Added `RESERVE_MIN_MIB = 2048` and `RESERVE_FRACTION = 0.12` (READ: `governor.js:77-78`).
* Added `reserveMiB(reading)`: `max(2048, round(mem.totalMiB x 1048576 x 0.12)) / 1048576`, computed
  on **bytes** so it is byte-identical to `governor.js:126` rather than merely close. It returns
  `basis` — `derived` | `floor` (the 2 GiB minimum bound it) | `fallback` (no `mem.totalMiB`) — and
  a rationale line naming the total it used.
* `slotArithmetic()` subtracts that reserve instead of the literal and pushes the derivation into
  `arithmetic`, so it reaches `POST /place`'s rationale and `GET /nodes`'s `slotArithmetic` for free.

**`lib/broker.js`** — `view.scoreTerms` gains `reserveMiB` and `reserveBasis` (per node, on every
`/nodes` row). The exported `broker.config.reserveMiB: RESERVE_MIB` scalar was **replaced** by a
`reserveRule` object: nothing in the tree or in any test read that field, and a scalar named
`reserveMiB` would now say the opposite of what the broker does. *(If a caller outside this repo
read `broker.config.reserveMiB`, it is a JS-API field, not a `§2.2` field, and it was never served
over HTTP.)*

**`test/scoring.test.mjs` — two assertions, DECLARED.** The §2.2 worked-example test scores the
§2.1 sample reading, which reports `mem.totalMiB: 65156`, so under the new rule *that fixture's own
reserve is 7,819 MiB* and its intermediate `beforeCap` is 269 instead of 294. Its **published score
is unchanged at 9** (`maxSlots=24` is what binds), which is why the worked example can keep pinning
the contract. I updated the two assertions that hardcoded the single-node constant — `beforeCap
294 → 269`, and the reserve string → the derived value — and **strengthened** them by asserting
`reserveMiB == 7819` and `reserveBasis == 'derived'` explicitly. This is the only test file I
touched, it is outside the declared scope, and the alternative was handing over a red suite.

`npm run verify` clean; **`npm test` → `tests 60  pass 60  fail 0`** on this laptop (Node v24.12.0),
and **`# tests 60 # pass 60 # fail 0`** on the authority (Node v20.20.2) from the deployed copy. The
other 58 tests are untouched and still pass, including the §4.2 acceptance tests that assert the
frozen `3885 MiB reserve` in a rationale — they drive stub gates whose default `totalMiB: 32373`
yields exactly 3885, which is not a coincidence: the stub was built as a 31.6 GB machine.

**Live, through the service, after the change** (MEASURED 03:45Z, from `POST /place`'s rationale):

```
zabz-tech: 18 slot(s) of at most 24: floor((48329 MiB free - 7821 MiB reserve) / 160 MiB) = 253 slot(s),
           capped at maxSlots=24 -> 24, reserve 7821 MiB = max(2048 MiB, 12% of the node's own 65173 MiB)
           (the governor's own derivation, governor.js:126), minus governor.inUse=0 -> 24
```

### 3.5 The documents corrected

* **`71-mesh-program.md` §2.2** — the frozen formula now reads
  `reserveMiB = max(2048, round(0.12 x mem.totalMiB)) // governor.js:126, PER NODE`, with the
  measurement, the per-node table, the fallback rule and the `scoreTerms` fields named. (This is
  the edit job 3 asks for by name: *"correct the clause in the program document"*.)
* **`71-mesh-program.md` §2.1** — the bullet that printed the gate's formula now says
  `governor.budgetSlots` is **advisory, and must not be consumed**, with the reason (floored at 4,
  capped at 24). The rule *"Residency/budget arithmetic belongs to the BROKER"* gains the one
  parenthetical exception that bullet creates.
* **`81-overnight-program.md` §3 item 2 is CLOSED by this document** and is **not** edited in that
  file: §4 of `81` says a premise found wrong should be corrected *in the stream's own document*,
  and the verdict is the paragraph above. **The item is decided; do not re-litigate it.**
* **`76-broker.md` is NOT edited**, deliberately. Its §3 (*"`3885 MiB` reserve and `24` maxSlots are
  the governor's own derivation … so they are literals in `scoring.js`"*) and §10.3's table are now
  stale on that one point. The program's own doctrine is that a record that was right when it was
  written is corrected by a NEW entry citing the old one, not by rewriting it — this section is that
  entry. **For the integrator: `76-broker.md` §3 line 119-121 and §10.3's table want a one-line
  pointer to here, and that is a manager's edit, not mine.**

### 3.6 What this does NOT fix

* **`max(2 GiB, 12% of physical)` is itself a questionable shape**: it makes a fixed cost — the
  browser, the editor, the engine — scale with how much RAM the box has. 2,811 MiB held back for
  "everything that is not a tool process" on a 23 GB server, and 7,821 MiB on the 64 GB desktop, are
  generous by any reading. A cap would need a measurement (`zabz-tech` under a real fleet, which is
  stream O3's job), and inventing a constant here would be the opposite of what this program is for.
  The broker now at least **reproduces the governor's own number for the node in front of it**
  instead of asserting one machine's number everywhere, and publishes it per node so the day the
  shape is fixed the change is visible in one place.
* **`mem.totalMiB` is trusted as reported.** A node that lies about its RAM gets the reserve for the
  RAM it claims. The fallback is 3885, the most conservative of the four values in play.
* The `3885` in `lib/stub-gate.js`'s `freeMiBForSlots()` (`freeMiB = 3885 + slots x 160`) is
  **correct as it stands** and was left alone: the stub's default `totalMiB` is 32373, so its own
  derived reserve is exactly 3885 and the two agree by construction.

---

## 4. Files this stream changed

**Owned and changed:**

| file | change |
|---|---|
| `packages/mesh-broker/deploy/mesh-broker.service` | rewritten: explicit loopback bind + roster, `After=tailscaled`, journal logging, `SyslogIdentifier`, the hardening set, the deliberate rate-limit decision. `IPAddressDeny/Allow` removed with the measurement in the header. sha256 `c9a1e8f8f052c572644077d0e9b8b4ea7b286dd9f6297b4f2b07c8ba2cd421aa` |
| `packages/mesh-broker/deploy/install-authority.sh` | **new** — the install and its 20 assertions |
| `packages/mesh-broker/deploy/verify-deploy.sh` | **new** — the anti-drift check |
| `packages/mesh-broker/deploy/authority-swap-probe.py` | **new** — the "whose memory is in swap" measurement (§2.2) |
| `packages/mesh-broker/deploy/authority-swap-fix.py` | **new** — the reclaim that deletes nothing (§2.4) |
| `packages/mesh-broker/deploy/secratary-smoke.sh` | uses the installed service instead of starting a second broker on 3091 |
| `docs/mesh/86-authority.md` | this document |

**Outside the owned scope, DECLARED, and each one required by a job:**

| file | why it was necessary |
|---|---|
| `packages/mesh-broker/lib/scoring.js` | job 3 cannot be done without changing the arithmetic (§3.4) |
| `packages/mesh-broker/lib/broker.js` | to publish the reserve that was used, per node (§3.4) |
| `packages/mesh-broker/test/scoring.test.mjs` | two assertions hardcoded the constant the decision removes; the suite would otherwise be red (§3.4) |
| `docs/mesh/71-mesh-program.md` §2.2 + §2.1 | job 3: *"correct the clause in the program document"* (§3.5) |

**Written on the authority, outside the repo:** `/home/zabz/mesh-broker/**` (the deployed tree and
its `PROVENANCE.md`), `/home/zabz/o5-staging/mesh-broker/**` (the reference tree),
`/etc/systemd/system/mesh-broker.service` + the `multi-user.target.wants` symlink,
`/etc/sysctl.d/99-mesh-authority-swap.conf`, and `/tmp/o5-*.sh|py|out|json` (probes and their
output). `journal.py` entries for this stream.

**Nothing was committed.**

---

## 5. What could not be verified

* **The reboot.** §1.5 — restart and SIGKILL are measured; the boot path is reasoned from
  `UnitFileState=enabled` plus the `WantedBy` symlink and is **not executed**. This is the one item
  of §0.8 this stream leaves open, and the reason is in §1.5.
* **`systemd-analyze verify` on this unit is not a clean signal**: it printed two unrelated warnings
  about `/usr/lib/systemd/system/xfs_scrub_all.service` (`CPUAccounting= has been removed and is
  ignored`) and nothing about `mesh-broker.service`. So the unit's syntax is proven by *installing
  and running it*, not by the verifier.
* **Whether `/tmp` would refill the swap under a real fleet.** Not measured; there was no fleet to
  run, and running one is stream O3's job. What is measured is that the *cause* is tmpfs, that the
  reclaim works, and that swappiness is now 10.
* **The reclaim's durability at 07:00Z.** Measured at 1.8% at 03:47Z. A later reader should re-check
  `SwapFree`; the probe script is the way to ask why it moved.
* **`secratary`'s transport is still `null`** (`81` §3 item 3) and untouched by this stream: the
  broker still cannot dispatch to the authority. The authority now scores 3 slots instead of 1, which
  makes it a more attractive target than it was — but its `dispatch.v1` is still unmeasured, so the
  broker ranks it below nodes that can take the work, correctly.
* **The whole fleet's behaviour under a real six-child dispatch** — untouched here; that is O1's
  acceptance run.

## 6. Premises in the brief that turned out to be wrong

1. **"`secretary-api`, postgres, the dashboard, the gates"** — **there is no PostgreSQL on the
   authority.** `systemctl is-active postgresql` → `inactive`; `sudo -u postgres psql` → *user
   'postgres' not found*; no postgres unit file exists. The authoritative database is SQLite
   (`~/personal-secretary-mvp/data/secretary.db`, integrity-checked by a `*/15` cron). The reboot
   decision was therefore never about postgres, and any future "check the database survives" step
   for this host should check the SQLite file and the `sqlite3 PRAGMA integrity_check` cron, not a
   cluster.
2. **"its swap is at 100%, which is … the reason the broker halves its slots"** — true of the
   number, false of the implication. The area was full of *cold tmpfs files*, not of anyone's
   working memory: the broker was reading a tuning artefact and calling it pressure. It happened to
   rank the node about right for the wrong reason. That is worth knowing before the next threshold
   is set on `swapUsedPct`, which is a *level* and not a *rate* — `76-broker.md` §10.2 already says
   so, and this is the measurement that makes it concrete.
3. **"`/tmp` pid file and log" as the problem** — accurate, and worse than stated: `/tmp` on this
   host is a **tmpfs**, so both files are lost on reboot *by construction*, and the log could not
   have been evidence of anything that survived. The hand-started process also ran with a relative
   `bin/mesh-broker.mjs` from `/home/zabz/mesh-broker-run`, so nothing recorded which build was
   live; the deployed copy carries a sha256 manifest now.
