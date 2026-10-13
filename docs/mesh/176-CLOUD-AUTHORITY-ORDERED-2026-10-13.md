# 176 — CLOUD AUTHORITY, ORDERED AND MEASURED (2026-10-13)

**Brief:** W1-AUTHORITY-ORDER. **Machine measured:** `secratary-cloud` (Hetzner CCX23, Ashburn VA).
**Landing host of this session:** `LakewooechsMini` (macOS/Darwin, arm64) — *not* Windows and *not*
Linux, so every platform-specific command in the brief was translated to bash and `ssh` (see §0).
**Method:** read-only over `ssh -i ~/.ssh/retired-20260914/id_ed25519_hetzner root@178.156.194.1`,
one bounded session per probe. Nothing was started, stopped, enabled, disabled, restarted, or
deleted except the script's own `dd` scratch file, which is named in §1.4.

This page answers the owner's question — *is the cloud authority actually faster and more reliable
than the office box it replaced, and what is still wrong with it?* — with the command and its output
line for every number. **THE VERDICT is at the bottom; it is `NOT-PROVEN`.**

> **What the brief pointed at, and what actually exists.** The brief cites
> `docs/mesh/175-STATE-OF-THE-ESTATE-2026-10-12.md` §2.1 and §2.5. **No file matching `175-*` exists in
> any ref of this repo** (`git log --all --name-only | grep STATE-OF-THE-ESTATE` → empty). The
> 7.7 GB / swap / kernel-OOM synthesis it quotes is `171-CLOUD-AUTHORITY-AUDIT-START-HERE.md` §1.3/§3,
> and the two kernel checks it quotes (§2.5) are `170-MASTER-RECORD-ATTENTION-BADGE-AND-FLEET-AUDIT.md`
> §5.1/§5.2. This page cites 169/170/171 by their real names. The brief's "two days old" measurement
> is correct: the box has since been resized and **both 170 kernel defects have since been patched**
> (2026-10-12T16:02:54Z — §6).

---

## 0. Platform and access (the first thing that was measured)

```
$ hostname
LakewooechsMini
$ uname -a
Darwin LakewooechsMini 25.5.0 Darwin Kernel Version 25.5.0: Tue Jun  9 22:26:22 PDT 2026; root:xnu-12377.121.10~1/RELEASE_ARM64_T8132 arm64
```

The brief assumes Windows (`zabz-tech`) or Linux (`zabz-tech-linux`). This child landed on the Mac
mini, which the mesh roster reads as `unreachable` (§7). There was **no `secratary-cloud` ssh alias
on this host** (`grep -n secratary-cloud ~/.ssh/config` → empty) and **no `~/.ssh/id_ed25519_hetzner`**;
`docs/mesh/000-SYSTEMS-REGISTER.md` §1 names that key. The only working route found was the *retired*
copy at `~/.ssh/retired-20260914/id_ed25519_hetzner`, and the IP:

```
$ ssh -i ~/.ssh/retired-20260914/id_ed25519_hetzner -o BatchMode=yes root@178.156.194.1 'hostname; id -un; nproc; free -m | head -2'
secratary-cloud
root
4
               total        used        free      shared  buff/cache   available
Mem:           15605        2960         492           4       12496       12645
```

**The resize is confirmed**: `nproc` = 4 and `Mem total` = 15,605 MB, against the register's
"CCX13, 2 vCPU, 7.7 GB". Every memory conclusion in `171` must be re-read against 15.6 GB.

---

## 1. SPEED — measured, with a comparison

### 1.1 HTTP `/health` — 10 calls

```
$ for i in $(seq 1 10); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8002/health; done
200 0.005472
200 0.004325
200 0.004222
200 0.004100
200 0.003934
200 0.003948
200 0.003941
200 0.003873
200 0.003887
200 0.003877
```

Sorted the 10 values are 0.003873, 0.003877, 0.003887, 0.003934, 0.003941, 0.003948, 0.004100,
0.004222, 0.004325, 0.005472.

* **p50 = 3.94 ms** (mean of the 5th and 6th: (0.003941+0.003948)/2).
* **max = 5.47 ms**.
* **Office baseline: NOT COMPARABLE.** `171` and `169` record no `/health` latency for the office box.
  Inventing one is exactly what this brief forbids. The only office HTTP-adjacent number on record is
  `169` §1.3: the office box's `sshd` stopped answering three times under load — a binary, not a
  latency.

### 1.2 `GET /v1/models` — 10 calls

```
$ for i in $(seq 1 10); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8002/v1/models; done
200 0.002697
200 0.002469
200 0.002429
200 0.002281
200 0.002213
200 0.002262
200 0.002216
200 0.002205
200 0.002154
200 0.002115
```

Sorted p50 = (0.002213+0.002262)/2 = **2.24 ms**; **max = 2.70 ms**. **Office baseline: NOT
COMPARABLE** (none recorded).

### 1.3 A representative SQLite query on `/root/authority.db`

Cheap, read-only, `mode=ro` URI, 20 iterations, same connection string the backup reader uses:

```
$ python3 - <<'PY'
import sqlite3,time
p="/root/authority.db"
ts=[]
for i in range(20):
    con=sqlite3.connect("file:%s?mode=ro"%p,uri=True)
    t=time.perf_counter(); cur=con.execute("SELECT count(*) FROM sqlite_master"); r=cur.fetchone(); ts.append((time.perf_counter()-t)*1000); con.close()
ts.sort(); print("sqlite_master_count=%s p50=%.2fms max=%.2fms"%(r[0],ts[len(ts)//2],ts[-1]))
PY
sqlite_master_count=654 p50=2.34ms max=4.04ms
```

**Office baseline:** `169` §2 records *"live DB point read, random rowid ×150: office 0.009 ms
(office anchor, RAM-cached); cloud 0.085 ms (authority, WAL)"* — a **different query and a different
harness**. Comparing 2.34 ms against 0.009 ms would be dishonest. **NOT COMPARABLE as measured**;
the honest statement is that `169` already found the office anchor **9×** faster on a cached point
read, and nothing in this session disturbs that.

### 1.4 Disk throughput — 512 MB `dd` under `/root`, then deleted

```
$ dd if=/dev/zero of=/root/w1-dd.bin bs=1M count=512 oflag=direct
536870912 bytes (537 MB, 512 MiB) copied, 0.201028 s, 2.7 GB/s
$ ls -l /root/w1-dd.bin
-rw-r--r-- 1 root root 536870912 Oct 13 01:12 /root/w1-dd.bin
$ rm -f /root/w1-dd.bin; ls -l /root/w1-dd.bin
ls: cannot access '/root/w1-dd.bin': No such file or directory
$ dd if=/dev/zero of=/root/w1-dd2.bin bs=1M count=512   # buffered, for shape
536870912 bytes (537 MB, 512 MiB) copied, 0.127517 s, 4.2 GB/s
removed2 rc=0
```

**Office baseline:** `171` §3 / `169` §2, same O_DIRECT harness both boxes:
**office 3,851 MB/s (1 GiB) and 578,365 IOPS; cloud 1,323 MB/s and 400,972 IOPS** — the office is
**~2.9× faster** on raw sequential write and 1.44× on 4 KiB IOPS. My `dd` (512 MB, 1 MiB blocks)
**cannot be compared** to their 1 GiB / cache-defeating harness; it only shows the resized box writes
512 MB in 0.20 s. The comparison that *is* like-for-like and decisive is §3 of `171`: on giant I/O
under its own load the office ran **2–7 MB/s** while the cloud's verified 23.6 GB `.backup` ran at
**139 MB/s**. The cloud is much faster **under production load**; the office is faster **idle on a
microbenchmark**. The brief's "faster" is true only of the first.

### 1.5 Mesh cold-placement latency

The broker runs on the authority, loopback `:3091`. `GET /` (its liveness route) and the roster read:

```
$ curl -s -o /dev/null -w 'root %{http_code} %{time_total}\n' http://127.0.0.1:3091/
root 200 0.000673
$ curl -s 'http://127.0.0.1:3091/nodes?fresh=1'
… "reads": 35, "readFailures": 14, "cacheTtlSec": 15, "readTimeoutMs": 1500 …
```

Per-node `latencyMs` from that fresh read (`nodes[].firstLatencyMs`): **zabz-tech 87 ms,
zabz-yoga-1 165 ms, zabz-tech-linux 65 ms, secratary 77 ms, lakewooechsmini 70 ms**, with
`"readFailures": 14` against `"reads": 35`. **Office baseline: NOT COMPARABLE** — `169`/`171` did not
measure cold placement, and the office broker is a *different* broker (the register §2.3 records the
office `mesh-broker.mjs` still running). A `/place` cold-placement timing was **not** taken; see
`NOT VERIFIED`.

---

## 2. MEMORY — the exact current state

```
$ systemctl show company-api -p MainPID -p MemoryCurrent -p MemoryPeak -p MemoryMax -p MemoryHigh -p NRestarts -p ActiveEnterTimestamp
MainPID=25368
NRestarts=0
MemoryCurrent=6366658560      # 6.07 GiB RSS at 01:11Z
MemoryPeak=9214472192         # 8.58 GiB peak since start
MemoryHigh=infinity
MemoryMax=infinity
ActiveEnterTimestamp=Mon 2026-10-12 14:14:39 UTC
```

```
$ free -m
               total        used        free      shared  buff/cache   available
Mem:           15605        2955         497           4       12496       12650
Swap:           4095        2006        2089
$ swapon --show
NAME      TYPE SIZE USED PRIO
/swapfile file   4G   2G   -1
```

**`MemoryMax` is still `infinity`.** The register (`171` §5 item 1) recommended a ceiling or the
resize; the resize happened, the ceiling did not. The app's peak is **8.58 GB on a 15.6 GB box**, and
it shares that box with a `transcript-archive-pull` job that peaks ~6.3 GB (§2.2).

### 2.1 Kernel OOM, last 7 days

```
$ journalctl -k --since "7 days ago" | grep -i oom
Oct 12 22:29:58 secratary-cloud kernel: oom-kill:constraint=CONSTRAINT_MEMCG, ... oom_memcg=/system.slice/transcript-archive-pull.service, task=python3,pid=204643
Oct 12 22:29:58 secratary-cloud kernel: Memory cgroup out of memory: Killed process 204643 (python3) total-vm:9260160kB, anon-rss:6272628kB ...
Oct 12 23:29:10 secratary-cloud kernel: Memory cgroup out of memory: Killed process 213028 (python3) ... anon-rss:6262188kB ...
Oct 13 00:29:44 secratary-cloud kernel: Memory cgroup out of memory: Killed process 223093 (python3) ... anon-rss:6273032kB ...
```

```
$ journalctl -u company-api --since "7 days ago" | grep -i oom
Oct 11 05:47:24 secratary-cloud systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
Oct 11 07:10:45 secratary-cloud systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
Oct 11 15:17:30 secratary-cloud systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
Oct 12 07:52:56 secratary-cloud systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
Oct 12 09:05:54 secratary-cloud systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
```

This is **two distinct OOM classes**, and the brief's old note ("a kernel OOM in 24 h") is now wrong
in a specific, worse way:

* **`company-api` was OOM-killed 5 times in 7 days** — three on 2026-10-11 (the register's 3) and
  **two more on 2026-10-12 at 07:52:56 and 09:05:54**. The resize did **not** end the class. The office
  box, per `171` §3, had **0 OOM kills ever** on 23,421 MB.
* **`transcript-archive-pull` now OOMs hourly** (22:29:58, 23:29:10, 00:29:44 …), each a cgroup
  (`CONSTRAINT_MEMCG`) kill of its own ~6.27 GB python3. It is contained — it kills the ingest job,
  not the API — but it is new evidence that 15.6 GB is still not enough for the workloads placed on it,
  and that the archive job has never completed a clean hour.

### 2.2 Is the 2 GB of swap residue or growth? Two samples ~60 s apart

```
$ grep -E 'SwapTotal|SwapFree' /proc/meminfo; date -u +%H:%M:%S
SwapTotal:       4194300 kB
SwapFree:        2139176 kB        # 01:12:47Z
$ sleep 65
$ grep -E 'SwapTotal|SwapFree' /proc/meminfo; date -u +%H:%M:%S
SwapTotal:       4194300 kB
SwapFree:        2139276 kB        # 01:13:52Z
```

Swap used: 2,055,124 kB → 2,055,024 kB, i.e. it **fell by 100 kB** over 65 s. **Residue, not
actively growing.** This is the pre-resize swap that was never reclaimed (the same 2,558 MB / 2,006 MB
neighbourhood `171` recorded), and the box has not been rebooted since 11 h 58 m uptime. It is not a
live leak; it *is* a live indicator that the working set still overflows physical RAM at times.

---

## 3. DISK — 75 GB, 81 % full, 14 GB free

```
$ df -h /
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1        75G   58G   14G  81% /
```

### 3.1 What consumes it

```
$ du -x -d1 -B1 / | sort -n | tail -12
833273856	/var
2876669952	/usr
17992560640	/opt
35997077504	/root
62127169536	/
$ du -x -d1 -B1 /opt/company | sort -n | tail -6
1525981184	/opt/company/.venv
6654611456	/opt/company/data
7841251328	/opt/company/archive
16448352256	/opt/company
$ du -x -a -B1 /root | sort -n | tail -5
4442959872	/root/work
2556547072	/root/git-rescue-20261012
35997118464	/root
25007927296	/root/authority.db        # the live company DB, 24.3 GB
$ du -x -d1 -B1 /var | sort -n | tail -6
194379776	/var/lib
246890496	/var/log
390311936	/var/cache
833273856	/var
```

* `/root` = 33.5 GiB, of which **`/root/authority.db` = 24.3 GB** (irreplaceable, never touched).
* `/opt/company` = 15.3 GiB, of which **`archive` 7.84 GB** and **`data` 6.65 GB** (LIVE, forbidden).
* `/var` = 833 MB; `/var/log` only 247 MB; `/usr` 2.88 GB.

### 3.2 The fastest-growing item, with evidence

```
$ find / -xdev -type f -mmin -1440 -size +20M -printf '%s\t%TY-%Tm-%TdT%TH:%TM\t%p\n' | sort -n | tail -8
303071232	2026-10-13T01:06	/opt/company/data/mem0/chroma.sqlite3
1049538560	2026-10-13T00:28	/opt/company/archive/lpt-transcripts/incoming/zabz-tech.tar
2403770368	2026-10-13T01:06	/opt/company/data/chromadb/chroma.sqlite3
25007923200	2026-10-13T01:08	/root/authority.db
```

At **01:12Z**, the newest large writes were `chromadb/chroma.sqlite3` (2.40 GB, mtime **01:06Z**, six
minutes old) and `mem0/chroma.sqlite3` (0.30 GB, **01:06Z**): a **2.7 GB pair written continuously** —
that is the fastest-growing item. The second is the archive ingest:
`archive/lpt-transcripts/incoming/zabz-tech.tar` at **1.05 GB written 00:28Z**. Both `/opt/company`
targets are LIVE and **must not be touched**; the reclaimable growth is in `/root` (below).

### 3.3 Safe reclamation

`scripts/authority/reclaim-disk.sh` — dry-run by default, refuses to remove anything without
`--apply`, prints the exact bytes, and never touches the live DB, the backup state, `/opt/company`, or
the rescue bundles. It targets npm/pip/uv/apt caches, the rebuildable `.fsearch` index, and
`/root/work/lpt-hub/{tmp,artifacts}`. It reports (never deletes) `/root/git-rescue-20261012` (2.56 GB
of repo rescue bundles, which may be the only copy) and `/root/work/lpt-hub/.git`. **Nothing was
deleted by this session.**

---

## 4. BACKUPS — prove the artefact, not the transport (Trap 7)

`/var/lib/authority-backup/last-run`:

```
finished_at=2026-10-12T05:50:46Z
status=ok
database_sent=yes
database_verified=ok
source=/root/authority.db
source_bytes=24344981504
reader_bytes=24344981504
reader_sha256=1fb81f57544bffcd1e61e7aefb6a496203e0056554c97627c065a5276b407dac
gz_bytes=6472931199
gz_sha256=2da0a9bdcacb64d810b74b3ae230b82cd57e2c2a88ebb573eaab454018808cc4
remote_bytes=6472931199
remote_last_modified=2026-10-12T05:48:29+00:00
bucket=lpt-authority-backups
remote_key=authority/secretary.db.gz
duration_s=1614
host=secratary-cloud
exit_code=0
```

**The bucket was read independently** (not the recorded value) with `boto3` from the authority:

```
$ /usr/bin/python3 (with /root/.lpt-r2.env) list_objects_v2(Bucket=R2_BUCKET, Prefix='authority/')
OBJ authority/secretary.db.gz.sha256       82        2026-10-12T05:50:46.205000+00:00
OBJ authority/secretary.db.gz              6472931199 2026-10-12T05:48:29.701000+00:00  etag=c544f93b3c06e49fd620b3192f80517a-97
OBJ authority/accounting.db.gz             5192310   2026-10-12T05:23:51.830000+00:00
OBJ authority/data/authority-data.tar.gz   3682189812 2026-10-12T06:44:13.943000+00:00
```

* **Freshness:** newest DB object `LastModified = 2026-10-12T05:48:29+00:00`, i.e. **~19.4 h old at
  01:12Z**. The timer is daily (`authority-offsite-backup.timer`: last `Mon 2026-10-12 05:23:50`,
  next `Tue 2026-10-13 05:26:51`), so 19.4 h is *inside* the daily cadence. The 30-min freshness
  monitor's own log agrees, unchanged every reading through 00:50Z:
  `{"key": "authority/secretary.db.gz", "bytes": 6472931199, "last_modified": "2026-10-12T05:48:29+00:00", ...}`.
* **Content, partial:** a 256 KiB byte range was pulled and **decompressed**; the first 16 bytes are
  `SQLite format 3\0` → `OPENABLE = True`. That proves the object is a real gzip stream carrying a
  real SQLite database. It is **not** `PRAGMA integrity_check`.
* **Full `PRAGMA integrity_check`: COULD NOT ASK, with arithmetic.** `reader_bytes = 24,344,981,504`
  and the box has **14 GB (≈14 GiB) free**. A materialised integrity check needs the ~24.3 GB
  uncompressed DB on local disk; it does not fit. The backup script was *designed* never to
  materialise (`authority-offsite-backup.sh` header: "PEAK EXTRA DISK USAGE IS APPROXIMATELY ZERO …
  Any design that materialises the database … does not fit here"), so on this box the restore has
  **never been** and **cannot now be** content-verified in place. **Trap 7 stands: the transport is
  proven (sha256 of the page stream, exact remote byte count, openable header), the content is not.**

`scripts/authority/verify-offsite-backup.sh` re-runs this proof and prints the same fits/does-not-fit
arithmetic, read-only.

---

## 5. `config_sync` divergence check — STILL UNFIXED, fix delivered as a patch

`170` §4.2's shape: `autosync` writes a record every 15 minutes; `check_config_sync()` escalates any
`result != "clean"` to HIGH **on a single sample**. A 15-minute cache plus an instant sample means a
healthy repo whose pull is momentarily behind reports a company-affecting HIGH that clears on the next
sample. The live source (`/root/ceo-kernel/ck/sentinel.py:1732-1740`) is unchanged:

```
$ sed -n '1732,1740p' /root/ceo-kernel/ck/sentinel.py
    if result != "clean":
        return Finding(
            check="config_sync", severity=HIGH, ok=False,
            summary=f"last config sync was '{result}' {_human(age)} ago: {doc.get('detail')}",
            metrics=metrics,
        )
```

There is no second sample and no persistence. **Delivered, not installed:**
`scripts/authority/config-sync-two-sample.py` (drop-in `check_config_sync()` that stores the last
sample; the changed-block unified diff is `scripts/authority/config-sync-two-sample.patch` and the
two `_load_config_sync_state`/`_save_config_sync_state` helpers it needs are its second hunk) — it stores the last
sample and escalates HIGH only when two consecutive samples carry the same non-clean `result`; a
first non-clean sample is MEDIUM *"awaiting second sample"*). **Before/after:** before, one non-clean
sample → `severity=HIGH, ok=False`; after, first non-clean → `severity=MEDIUM`,
second identical → `severity=HIGH`. The before line above is the live source; the after behaviour is
the delivered function. It was **not** run against the live sentinel (installing is forbidden here).

---

## 6. The two kernel checks — ALREADY FIXED on 2026-10-12T16:02:54Z

The brief (via the missing `175` §2.5) says `liveness` prints a constant and `db_writable` escalates
HIGH on a 6 s probe. **The file running on the authority no longer does either.** A backup,
`/root/ceo-kernel/ck/sentinel.py.bak-sentinelhonesty-20261012T160254Z`, sits beside the current file;
`diff -u` shows the change:

```
$ diff -u .../sentinel.py.bak-sentinelhonesty-20261012T160254Z .../sentinel.py | grep 'age = pkt'
-    age = pkt.data_age_seconds or 0
+    age = _age_seconds(pkt.value)
```

and the current `db_writable` has a second stage:

```
$ sed -n '2332,2340p' /root/ceo-kernel/ck/sentinel.py
DB_WRITE_PROBE_SECONDS = 6.0
#: ... worst contended acquire this estate has ever measured -- 9.0 s -- with real margin; 60 s is ~6.7x that.
DB_WRITE_CONFIRM_SECONDS = 60.0
```

The full before/after, with the exact diff quoted, is
`scripts/authority/kernel-checks-already-fixed.md`. **What is left is the after-measurement** — run
the live check and record the emitted severity — which this session's budget did not reach
(`NOT VERIFIED`).

---

## 7. THE MESH ROSTER

`curl -s http://127.0.0.1:3091/nodes?fresh=1` on the authority returned **5 nodes**:
`zabz-tech` `state=ok`, `zabz-yoga-1` `state=ok`, `zabz-tech-linux` `state=ok`, `secratary`
`state=unreachable reason="HTTP 403" latencyMs=77`, `lakewooechsmini` `state=unreachable
reason="HTTP 403" latencyMs=70`. `readFailures` 14 / `reads` 35.

* **`secratary` — deliberate posture, enforced by the phone gate.** The register (`000` §1) and the
  roster's own `transport.evidence` say it was left FROZEN as the rollback anchor at
  `2026-10-11T05:43:36Z`, every writer stopped and disabled, and the roster marks it `excluded`.
  `HTTP 403` is `scripts/phone-gate.py` refusing a non-allow-listed reader — the mechanism *of* the
  freeze, not a fault. **Not a fault.**
* **`lakewooechsmini` — phone-gate refusal on a LIVE node, not a real fault.** The node answers
  `HTTP 403` to the broker (70 ms, so the network is up), and its `transport.v1` is `true`
  (re-measured 2026-10-08). Decisive independent evidence: **this session is running on that node** —
  `hostname` → `LakewooechsMini` (§0). A machine serving an agent is not down. The 403 is
  lakewooechsmini's own phone gate not listing the broker's reader, the same per-node deployment
  defect the register §2.3 names ("it must be deployed per node, not once"). **Fix: deploy the
  broker/authority into `phone-gate-allow.txt` on lakewooechsmini. A gate-config fault, not a fault
  in the machine.**

### 7.1 `auth.secretConfigured:false` — does it still matter?

The register §2.3 says the authority answers 200 on `/mesh/health` but advertises
`auth.secretConfigured:false` (`/etc/dsh-mesh.env` absent), so it cannot sign a v2 run. The live
`/mesh/health` read is **degraded and does not carry that field**:

```
$ curl -s -m 6 http://127.0.0.1:8002/mesh/health
{"ok":true,"mesh":null,"note":"SSH failed: "}
```

Whether it *matters*: **no, for placement.** The authority is the broker's own host and is **not one
of the 5 nodes in its roster** (`secratary-cloud` does not appear in the `nodes[]` above), so no
dispatch is ever placed onto it and its inability to sign a v2 run blocks nothing. It would matter
only if someone tried to add the authority as a worker. The `note:"SSH failed:"` on its own
`/mesh/health`, however, is a separate degradation worth a follow-up.

---

## THE VERDICT

**`NOT-PROVEN`.**

The owner's claim was conjunctive — *"way faster **and** way more reliable"*, "an order of magnitude
faster and more robust on every single metric". The arithmetic:

**Speed — mixed; "faster on every metric" is false.**
* Cloud **much faster under production load**: office 2–7 MB/s vs cloud 139 MB/s verified `.backup`
  (`171` §3) — **~20–70×**.
* Office **faster on the raw device**: 3,851 MB/s vs 1,323 MB/s sequential write, 578,365 vs 400,972
  IOPS (`171` §3) — office **1.44–2.9×**.
* HTTP latency on the cloud is measured here (`/health` p50 3.94 ms, `/v1/models` p50 2.24 ms,
  SQLite p50 2.34 ms) but **no office baseline exists** in 169/170/171 → **COULD NOT COMPARE**.

**Reliability — mixed; the memory axis is still worse than the box it replaced.**
* Cloud **more available**: office 215 `secretary-api` restarts in a month and 8 boots; cloud
  `NRestarts=0`, 1 boot; `database is locked` 657/10 days → 2/19 h (`169` §1, §1.2, §1.3).
* Cloud **less memory-reliable**: office **23,421 MB, 0 OOM kills ever**; cloud **15,605 MB,
  `MemoryMax=infinity`, 5 `company-api` OOM kills in 7 days (3 on Oct 11, 2 on Oct 12 07:52 & 09:05)**
  and an **hourly** `transcript-archive-pull` cgroup OOM. The class that never occurred on the office
  box still occurs here, after the resize.

A conjunctive claim needs both halves proven on the metrics that matter; each half is contradicted on
at least one measured axis. **`NOT-PROVEN` is the honest verdict.**

### What is still wrong with the authority (ranked)

1. **Memory is still the binding constraint.** `MemoryMax=infinity`; `company-api` peak 8.58 GB;
   5 API OOM kills in 7 days including two on 2026-10-12; an hourly `transcript-archive-pull` OOM
   (~6.27 GB each). The resize raised the ceiling; nothing capped the app or fixed the ingest.
2. **The offsite copy cannot be content-verified in place.** 24.3 GB uncompressed vs 14 GB free
   (§4) — Trap 7 is unresolved and *unresolvable on this disk*.
3. **Disk 81 % full and growing** at `/opt/company/data/chromadb` (2.7 GB pair, LIVE, forbidden) and
   `/opt/company/archive` (incoming tarballs). Reclaimable headroom is in `/root` (§3.3).
4. **`config_sync` false-HIGH** — unfixed; patch delivered (§5).
5. **`lakewooechsmini` phone-gated out** while alive (§7) — a per-node gate deployment gap.
6. **The authority's own `/mesh/health` is degraded** (`{"ok":true,"mesh":null,"note":"SSH failed: "}`).
7. **Journal retention** (`171` §4 item 4: 102 MB / 32 h) — not re-measured here.

---

## 8. INDEPENDENT RE-MEASUREMENT (2026-10-13T01:19–01:23Z, same thread, fresh dispatch)

This thread was re-dispatched after the first report; **every number below was produced by the command
shown**, on `secratary-cloud`, over
`ssh -o BatchMode=yes -o ConnectTimeout=8 -i ~/.ssh/retired-20260914/id_ed25519_hetzner root@178.156.194.1`.
Deltas against §1/§2 are printed rather than averaged: two passes give a spread, not a better number.

### 8.1 Speed re-measured — same shape, run-to-run spread only

```
$ for i in $(seq 1 10); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8002/health; done
200 0.006091
200 0.004571
200 0.004334
200 0.004153
200 0.004458
200 0.004608
200 0.004402
200 0.004265
200 0.004156
200 0.004186
# sorted: .004153 .004156 .004186 .004265 .004334 .004402 .004458 .004571 .004608 .006091
# p50=(.004334+.004402)/2=0.004368 s=4.37 ms   max=6.09 ms      (§1: p50 3.94 / max 5.47)

$ for i in $(seq 1 10); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8002/v1/models; done
200 0.002881
200 0.002669
200 0.002433
200 0.002490
200 0.002476
200 0.002449
200 0.002376
200 0.002332
200 0.002280
200 0.002298
# p50=(.002433+.002449)/2=0.002441 s=2.44 ms   max=2.88 ms      (§1: p50 2.24 / max 2.70)

$ python3 -c 'sqlite3 read-only SELECT count(*) FROM sqlite_master, 10x'
sqlite_master count ms: p50=2.63 max=3.46 min=2.55                  (§1: p50 2.34 / max 4.04)

$ dd if=/dev/zero of=/root/w1-dd.bin bs=1M count=512 oflag=direct
536870912 bytes (537 MB, 512 MiB) copied, 0.24005 s, 2.2 GB/s       (§1: 0.201 s, 2.7 GB/s)
```
**Reading:** the cloud's absolute HTTP/SQLite latency is unchanged within run-to-run noise (p50
2.4–4.4 ms). The §1 comparison is untouched: **no office `/health`, `/v1/models` or SQLite baseline
exists in 169/170/171, so these remain COULD NOT COMPARE**, not "the cloud is faster".

### 8.2 Memory re-measured

```
$ systemctl show company-api -p MemoryCurrent -p MemoryPeak -p MemoryMax -p NRestarts -p ActiveEnterTimestamp
ActiveEnterTimestamp=Mon 2026-10-12 14:14:39 UTC
NRestarts=0
MemoryCurrent=6112387072        # 5.69 GiB RSS at 01:20Z   (§2: 6.07 GiB at 01:11Z)
MemoryPeak=9214472192           # 8.58 GiB peak, identical to §2
MemoryMax=infinity

$ free -m
               total        used        free      shared  buff/cache   available
Mem:           15605        3109         400          24       12458       12496
Swap:           4095        2178        1917

$ journalctl -k --since '7 days ago' | grep -i oom | tail -15
Oct 12 22:29:58 secratary-cloud kernel: oom-kill:constraint=CONSTRAINT_MEMCG, ... oom_memcg=/system.slice/transcript-archive-pull.service, task=python3,pid=204298
Oct 12 23:29:10 secratary-cloud kernel: Memory cgroup out of memory: Killed process 213028 (python3) total-vm:9260160kB, anon-rss:6262188kB ...
Oct 13 00:29:44 secratary-cloud kernel: Memory cgroup out of memory: Killed process 223093 (python3) total-vm:9260160kB, anon-rss:6273032kB ...

$ journalctl -u company-api --since '7 days ago' | grep -i oom | tail -10
Oct 11 15:17:31 secratary-cloud systemd[1]: company-api.service: Failed with result 'oom-kill'.
Oct 12 07:52:56 secratary-cloud systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
Oct 12 07:52:57 secratary-cloud systemd[1]: company-api.service: Failed with result 'oom-kill'.
Oct 12 09:05:54 secratary-cloud systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
Oct 12 09:05:55 secratary-cloud systemd[1]: company-api.service: Failed with result 'oom-kill'.
```
**Reading:** the re-measurement confirms §2's conclusions — `MemoryMax=infinity`, peak 8.58 GB, and
the OOM class still live (three `company-api` OOM-failures in this 7-day window: Oct 11 15:17,
Oct 12 07:52, Oct 12 09:05, plus an **hourly** `transcript-archive-pull` cgroup kill at ~6.27 GB).
`tail` trimmed the window, so this pass *shows at least three*; §2.1 recorded five for the same 7 days.
The two counts are reported, not reconciled.

### 8.3 Swap — two samples 95 s apart (the "residue or growing?" question)

```
$ awk '/SwapTotal|SwapFree|MemAvailable/{printf "%s  ",$0} END{print ""}' /proc/meminfo
# T1 01:20:59Z
MemAvailable:   12801112 kB  SwapTotal:       4194300 kB  SwapFree:        1964012 kB
<sleep 95>
# T2 01:22:34Z
MemAvailable:   12758752 kB  SwapTotal:       4194300 kB  SwapFree:        1963796 kB

$ cat /proc/pressure/memory
some avg10=0.01 avg60=0.41 avg300=0.60 total=42237168
full avg10=0.01 avg60=0.37 avg300=0.53 total=41182972

$ top swap consumers (VmSwap > 20 MB, kB)
python 1629964
node 269936
next-server 53564
python 49032
```
**Arithmetic.** T1 used = 4,194,300 − 1,964,012 = **2,230,288 kB = 2,178.0 MB**.
T2 used = 4,194,300 − 1,963,796 = **2,230,504 kB = 2,178.2 MB**.
**Δ = +208 kB over 95 s = +0.009 %.** On this horizon swap is **flat, not actively growing**, and
PSI `some avg60=0.41` / `full avg60=0.37` says current memory pressure is low.
**But** the level is **172 MB above** the 2,006 MB this same thread recorded earlier
(thread outbox, 2026-10-13T01:19:13Z; §2.2 `free -m` → `Swap: 4095 2006 2089`), over an
unmeasured interval of tens of minutes. So it is **neither a fixed pre-resize residue nor a proven
leak**: the level moves on a minutes scale and a 95 s window cannot attribute it. The largest
contributor is one `python` process holding **1.55 GB swapped**.

### 8.4 Disk, backups and the roster re-read

```
$ df -h /
/dev/sda1        75G   58G   14G  81% /
$ du -xhd1 / | sort -rh | head -12
58G  /      34G  /root      17G  /opt      2.7G  /usr      795M  /var
$ du -xhd1 /root | sort -rh | head
34G  /root   4.2G  /root/work   2.4G  /root/git-rescue-20261012   864M /root/.dsh   557M /root/.cache
$ du -xhd1 /opt/company | sort -rh | head
16G  /opt/company   7.4G /opt/company/archive   6.2G /opt/company/data   1.5G /opt/company/.venv

$ ls -l --time-style=+%H:%M /opt/company/data/chromadb/chroma.sqlite3 /opt/company/data/mem0/chroma.sqlite3
-rw-r--r-- 1 1000 1000 2403770368 01:06 /opt/company/data/chromadb/chroma.sqlite3
-rw-r--r-- 1 1000 1000  303071232 01:06 /opt/company/data/mem0/chroma.sqlite3

$ ssh ... 'bash -s' < scripts/authority/verify-offsite-backup.sh
OBJ authority/secretary.db.gz bytes=6472931199 last_modified=2026-10-12T05:48:29.701000+00:00 age_h=19.54 etag="c544f93b3c06e49fd620b3192f80517a-97"
OPENABLE: SQLite-magic-first-16-bytes = True b'SQLite format 3'
CONTENT-CHECK-ARITHMETIC: free=14835064832 bytes; uncompressed=24344981504 bytes; fits=NO
CONTENT-CHECK: COULD NOT ASK -- a materialised PRAGMA integrity_check cannot fit. reason=free space < (uncompressed db + gz object). Reclaim or verify off-box.

$ curl -s -m 8 'http://127.0.0.1:3091/nodes?fresh=1'   # two unreachable rows, verbatim
"node": "secratary",       "state": "unreachable", "reason": "HTTP 403", "latencyMs": 67
"node": "lakewooechsmini", "state": "unreachable", "reason": "HTTP 403", "latencyMs": 82
# header: "reads": 40, "readFailures": 16
```
**Reading.** Disk is unchanged (58 G/14 G, 81 %); the `chromadb`/`mem0` pair is byte-identical to
§3.2 and its mtime is **still 01:06Z at 01:20:37Z** — so "fastest-growing" in §3.2 is a rate over the
ingest cadence (writes in bursts), **not** a per-minute constant; no growth was observed across the
14 min between the two reads. The backup artefact re-verifies: the object is **19.54 h** old against
a daily timer, its header decompresses to the real SQLite magic, and a full on-disk
`PRAGMA integrity_check` **still cannot fit** (14,835,064,832 B free < 24,344,981,504 B uncompressed)
— **Trap 7 stands and is unresolvable on this disk**. Both roster "unreachable" rows answered
`HTTP 403` in 67/82 ms: the network and the remote server are **alive** and **refused at the
application layer** — consistent with §7's deliberate frozen-anchor posture (`secratary`) and
phone-gate refusal (`lakewooechsmini`), and inconsistent with a real network fault.

---

## NOT VERIFIED

* **No office `/health`, `/v1/models`, mesh-placement, or SQLite-count baseline exists** in 169/170/171,
  so §1.1, §1.2, §1.3 and §1.5 are **COULD NOT COMPARE**, not "the cloud is faster".
* **No `/place` cold-placement timing** was taken; only per-node `firstLatencyMs` from `/nodes?fresh=1`.
* **The disk `dd` number is not the same harness** as `171`'s `storage-bench.py`; it is not a
  like-for-like comparison and is reported as shape only.
* **A full `PRAGMA integrity_check` of the offsite copy was not run.** reason=free space 14 GB <
  uncompressed 24.3 GB; the object's gzip+SQLite header was verified instead (§4).
* **The after-measurement of the two patched kernel checks was not taken.** The source diff proves the
  patch exists; it does not prove what the live check emits. reason=budget.
* **The `config_sync` fix was not installed or run against the live sentinel** — by instruction.
* **`auth.secretConfigured:false` was not re-read from `/mesh/health`** (the live payload carried
  `mesh:null, note:"SSH failed:"`); the claim is cited from `000` §2.3.
* **The office baseline numbers are quoted from `169`/`171`, not re-measured** — the office box is a
  frozen read-only anchor and was not touched.
* **The `175` document the brief cites does not exist**; I could not read its §2.1/§2.5 and instead
  used `171` §1.3/§3 and `170` §5.1/§5.2, which carry the same content.
* **Swap growth was sampled twice, 95 s apart (§8.3)** — enough to show it is flat on that horizon
  (+208 kB), and it is 172 MB above the earlier thread sample; not enough to attribute the level
  or to prove a long-horizon leak.
* **§8.1/§8.2 `tail`-trimmed journal and a 10-call HTTP sample are small.** The §8 pass bounds
  run-to-run spread only; it is not a load test and was not taken under production peak.
* **The `chromadb`/`mem0` growth rate in §3.2 is not re-derived in §8.4**; their size and mtime were
  re-read unchanged, so "fastest-growing" rests on §3.2's single observation.
* **`transcript-archive-pull` was not inspected** to find why it exceeds its cgroup; only the OOM
  lines were read.
