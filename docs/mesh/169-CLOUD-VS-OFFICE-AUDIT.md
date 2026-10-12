# 169 — CLOUD vs OFFICE: the honest audit

*(Number 158 was already taken twice — `158-WEBSITE-COMMS-PUSH-VERIFICATION.md`. This file was written as 158 on
disk and renamed before it was committed; nothing was overwritten.)*

**Author:** session on **ZABZ-YOGA** (Windows), 2026-10-12 03:15Z–04:05Z. **Asked by the owner, verbatim:**
*"seriously audit now and see if on every single metric the Cloud Secretary is an order of magnitude faster and
more robust. Did we stop old journal / database problems… is every single one of those things way faster and
fully fixed or not?"*

**Method.** Read-only on both hosts. Nothing was started, stopped, enabled, disabled or restarted anywhere.
The office box (`secratary-ts`) was touched with bounded commands only, per `131` Rule 1. Every number below
carries the machine, the command and the UTC time that produced it. Where a like-for-like reading was impossible
the row says so rather than being compared across.

**Comparison rule (state it, it changes the readings).** The office box is frozen: cron **masked**, API
**inactive**, load **0.04**. The cloud box is in production: API, dashboard, tunnel, 34 cron jobs, an offsite
backup and a 5.4 GB transcript ingest all running. So office numbers are an **idle 2013 desktop** and cloud
numbers are a **busy 2 vCPU VM**. An idle machine beating a busy one on a raw microbenchmark is not a win for
the idle machine.

---

## 0. THE SHORT ANSWER

**No — not on every metric, and not "an order of magnitude" uniformly.** The migration bought three real,
large wins and it has bought them. It also has (a) **one clear regression worse than the office box**, (b)
**problems that were not fixed but moved**, and (c) **an invariant the migration itself depends on that is
currently broken**: the rollback anchor has been written to and is no longer the cutover-point image.

| claim | verdict |
|---|---|
| "the old database problems are stopped" | **Largely yes, and it is the biggest win.** 657 `database is locked` events in the office journal's last 10 days (26–295/day, 75 on Oct 11 alone) vs **2 in 19 h** on the authority — and the authority is already in WAL. |
| "the old journal problems are stopped" | **The journal tooling was rebuilt before the migration and is better; the migration itself fixed nothing here.** It is now *slower per read* than the last measurement on the same laptop, because the repo grew to 3,489 entries. Not a cloud-vs-office question at all. |
| "way faster on every metric" | **No.** Raw storage on the office box is **2–3x faster than the cloud box per machine and faster per core**. The cloud's win is not speed, it is (i) surviving its own load and (ii) 20–70x throughput under production I/O where the office collapsed. |
| "more robust in every way" | **No.** Memory is strictly worse (`7.7 GB / 4 GB swap` + **1 kernel OOM kill of the API** vs `23 GB, 0 OOM kills ever`), and the safety net did not move: **no dead-man switch and no scheduled offsite backup cadence by cron**. |
| the office box is a clean rollback anchor | **FALSE as of 2026-10-11 22:33Z.** See §4. |

---

## 1. WHAT IS GENUINELY, DECISIVELY BETTER — measured tonight

### 1.1 Disk saturation under real workload: FIXED. This is the migration's whole justification.

| | office `secratary` | cloud `secratary-cloud` |
|---|---|---|
| the 14.2 GB / ~200k-file `data/` rsync | **2–7 MB/s**, and it took the box off the network (`H3406`, 2026-10-11 02:14Z) | not re-run; the equivalent 23.1 GB DB stream runs at **~12 MB/s compressed / 21 MB/s source** nightly |
| 23.6 GB consistent `.backup` + verify | never completed reliably (2 newest office snapshots have **no `COMPLETE` marker**) | **175 s = 139 MB/s** on 2026-10-11 06:01→06:49Z, verified end-to-end |
| disk free | **35 GB / 467 GB, 93 % used** | 18 GB / 75 GB, 77 % used |
| what the disk pressure did | `journalctl` 3 documented occasions where **sshd stopped answering** while `tailscale ping` still answered (load 52 on 4 threads, `bo` 5,000–22,000 blocks/s) | `psi io full=24–34 %` at peak — busy, but **no outage in 19 h** |
| API restarts | `secretary-api` **215 start events** in the retained journal month (Oct 1–11), plus manual stop/starts | **`NRestarts=0`**, one API start (2026-10-12 01:22:01Z) |
| boots | 8 boots in the retained journal | 1 boot ever (2026-10-11 08:24:50Z) |

The office box was not a slow computer. It was a **93 %-full consumer SATA SSD behind LUKS, being asked to do
disk-queue-heavy work while also being the company**, and it fell over — three times, measurably. The cloud box
has more headroom *on the disk* and, critically, no measured outage.

### 1.2 The `database is locked` plague: 30x better, and it holds under load.

| | office (frozen) | cloud (authority) |
|---|---|---|
| event count, last 10 days / since cutover | **657** in Oct 1–11 (`journalctl -u secretary-api`, per day: 295, 254, 7, 7, 5, 13, 83, 9, 49, 26, **75**) | **2** (`journalctl -u company-api --since 2026-10-11`: 1 on Oct 11 21:08:47Z, 1 on Oct 12 01:10:03Z) |
| SQLite journal mode of the live DB | `delete` | **`wal`** |
| WAL file | `secretary.db-wal` = 0 B | moving (was why the older copy was believed) |

**And the office box was not idle-safe at the end either:** `secretary-api.service` itself reported
`7.4G memory peak, 1023.7M memory swap peak` when it was stopped at 20:23:21Z, and the office DB is currently
carrying **13,070 free pages (~51 MB)** of churn. The cloud copy carries **652**.

*Honest caveat:* the cloud currently runs **34** cron jobs to the office's **93**, so part of this win is "less
concurrent work", not only "better machine". It is still a real win — but it is not yet a win at full parity.

### 1.3 Availability: the strongest single number in the audit.

**19 h 09 m of continuous production service** (cloud, `uptime` 03:34Z), one boot, `company-api` `NRestarts=0`,
no service failures (`systemctl --failed` empty), public doors answering. The office box could not sustain that
under its own load; it was restarted 215 times in the month the journal retains.

---

## 2. WHERE IT IS NOT FASTER — measured, same harness both machines

`storage-bench.py` (O_DIRECT, cache-defeating) and `host-metrics.sh`, run ~03:18–03:35Z.

| metric | office `secratary` (idle) | cloud `secratary-cloud` (busy) | reading |
|---|---|---|---|
| CPU | 4 cores / 4 threads, i5-4570 3.2 GHz (2013) | **2 vCPU**, EPYC-Milan | office has 2x the cores |
| RAM | 23,421 MB, **22,188 MB available** | 7,742 MB, **~5,300 MB available**, swap 2,558/4,095 MB used | office 3x |
| sequential write, 1 GiB O_DIRECT | 3,851 MB/s (office) / 3,928 MB/s (256 MiB re-run at 03:35Z) | **1,323 MB/s** | office ~2.9x |
| random 16 KiB read over 1 GiB | 0.003 ms, 4,755 MB/s | 0.005 ms, 3,081 MB/s | office ~1.5x |
| random 4 KiB read IOPS | 578,365 | 400,972 | office 1.44x machine, cloud **1.25x per core** |
| giant-I/O on the real file | documented 2–7 MB/s under load | 139 MB/s verified `.backup` | cloud 20–70x |
| load / pressure now | 0.04, `psi io full=0` | 4.9–5.4, `psi io full=24–34 %` | office idle, cloud saturated |
| live DB point read, random rowid ×150 | 0.009 ms (office anchor, RAM-cached) | 0.085 ms (authority, WAL) | **office 9x** — but one is idle and one is running gzip + a 5.4 GB archive ingest |
| live DB `journal_mode` / freelist churn | `delete` / 13,070 free pages | **`wal`** / 652 free pages | cloud better |

**Read the comparison rule before the table.** The office column is a frozen machine whose SSD is 93 % full; the
cloud column was measured while it was simultaneously (i) streaming a 23 GB database backup, (ii) ingesting a
3.5 GB transcript tarball, and (iii) running the API. Under that condition the cloud is within 1.3–2x of an
otherwise idle machine — that is not a demonstration that the cloud is faster, and it is not a demonstration
that it is slower. **What is demonstrated is that the cloud does all of that at once without falling over, which
the office box provably could not.**

---

## 3. THE REGRESSION: MEMORY. It is worse, and it has already cost an outage.

| | office (historical) | cloud (now) |
|---|---|---|
| RAM | 23,421 MB | **7,742 MB** |
| swap in use | 995 MB (frozen; 1,023.7 MB peak recorded by systemd) | **2,558 MB of 4,095 MB (62 %)** |
| kernel OOM kills, all time | **0** | **1** — and it killed the company API |
| cgroup ceiling on the API | `MemoryMax=8G` (office unit) | **`MemoryMax=infinity`, `MemoryHigh=infinity`** |
| API RSS right now | — | 1,089,756 kB (13.7 %) + `VmSwap` 1,815,968 kB |

The kill (`journalctl -k`, `secratary-cloud`):
```
Oct 11 15:17:30 secratary-cloud kernel: Out of memory: Killed process 1069 (python)
  total-vm:16461904kB anon-rss:7457924kB  UID:0  oom_score_adj:0
```
`165` §6 records two more the same day (`05:47:24Z` rss 7,544,976 kB, `07:10:45Z` rss 7,121,188 kB) — three in
one day, all killing `company-api`, all **global OOM** (`CONSTRAINT_NONE`), i.e. the kernel picked the victim and
nothing capped it. Tonight's live picture is the same pressure without the kill: `si/so` non-zero on every
`vmstat` sample, `Mem free 141–425 MB`, `psi io full avg10=24–34 %`.

**Why the API peaks at ~7.5 GB is still unexplained, and it is the most important open question in this audit.**
What is measured: systemd recorded the **same 7.4 GB peak on the office box** (`secretary-api.service: Consumed
28min 33.033s CPU time over 1h 19min 9.939s wall clock time, 7.4G memory peak, 1023.7M memory swap peak`,
20:23:21Z) — so this is not obviously a new leak, it is the application's real size. `sar` shows the shape at the
15:17:30Z kill: `15:00:13 kbmemfree 1,718,872` → `15:10:02 kbmemfree **322,000**` → kill → `15:20:07 kbmemfree
3,066,780` (the freed memory is the killed API). The same morning the box had already killed it at 05:47:24Z
(anon-rss 7,544,976 kB) and 07:10:45Z (7,121,188 kB), so the interval between kills is measured at **~1.5 h, then
`165` §6's 5–8 h**. Right now (04:00Z) the API is `VmRSS 1,403,796 kB` + `VmSwap 1,594,180 kB` ≈ 3.0 GB committed
after 2 h 27 m, with the day's swap holding 35–52 % used. Every one of those was a **global OOM**
(`CONSTRAINT_NONE`), i.e. the kernel chose the victim.

**The application's own memory store is the first place to look, and it is on the same disk:** `/opt/company/data/chromadb`
= **2.9 GB** and `/opt/company/data/mem0` = **1.1 GB** (measured `du -sh`). Not proven to be what the API holds in
RAM — but a 24 GB SQLite database plus a 4 GB in-process vector store is where a 7.5 GB anonymous peak plausibly
comes from, and that is checkable.

**Also in this column:** the missing safety net. `authority-deadman.timer` and
`authority-offsite-backup.timer` exist and are **enabled** (measured: deadman next 03:39:31Z, offsite next
2026-10-12 05:29:33Z) — but the **cron** layer has no `deadman`, no `push-db-offsite`, no
`company-offsite-push`, no `report-offsite-age` counterpart for the authority's own copy, and the office's
`company-offsite-push` (6-hourly restic to R2) has no equivalent at all. "The backup timer exists" and "the
backup chain is proven" are different statements; only the first is true tonight.

---

## 4. THE INVARIANT THAT IS BROKEN: the rollback anchor has been written to

`131` Rule 1 froze the office box **read-only** and Rule 2 made `/root/authority.db` the only writer. Measured
tonight:

| fact | evidence | when |
|---|---|---|
| the office DB **grew 393 MB after the freeze** | `stat` → `23,691,915,264 B` vs the cutover's `23,622,823,936 B`; mtime **2026-10-11 22:33:19Z**, unchanged since (verified twice, 5 h apart) | 22:33Z Oct 11 |
| a `.db-shm` was touched tonight | `secretary.db-shm` mtime **2026-10-12 03:18Z** (a shared-memory *read* by a process that still has the DB open; the DB file itself did not move) | 03:18Z Oct 12 |
| `family_chat.db` was written after the freeze too | `family_chat.db-shm` 2026-10-12 00:02Z, `-wal` 2026-10-12 00:00Z | 00:00Z Oct 12 |
| processes on the "frozen" box, still running | **`mesh-broker.mjs` started 2026-10-11 23:34:48Z** (i.e. *after* the freeze, and it is the placement broker the register says is stopped), `phone-gate.py`, `phone-redirector.py`, a GitHub Actions runner, `networkd-dispatcher`, `fail2ban` | 23:34Z Oct 11 |
| `.sms-inbox` was still working | `wake-dispatch.log` mtime 20:34Z, `inbox.db` 20:34Z, `integrator.log` 20:23Z | Oct 11 |
| cron itself is still properly masked | `systemctl is-enabled cron` → **masked**, `is-active` → inactive, `/etc/systemd/system/cron.service -> /dev/null` | 03:34Z Oct 12 |

So the freeze holds in the way that matters most (no second API, cron masked, DB not advancing since 22:33Z) —
**but it is not the cutover-point image, and a rollback to it now returns 393 MB of rows the authority does not
have.** That is exactly the failure shape `142-ANCHOR-WRITE-NOTICE.md` was written about, and it recurred.

---

## 5. TWO CONCRETE DEFECTS FOUND WHILE MEASURING (both on the cloud box, both cheap)

1. **A health monitor reporting on the wrong machine's script — FIXED during this audit.** The crontab ran
   `/usr/local/bin/report-offsite-age.sh` — the **office** script — whose `VENV_PY` default is
   `$HOME/personal-secretary-mvp/.venv/bin/python`, an interpreter that **does not exist on the cloud box**. The
   job therefore failed every other run (`/root/report-offsite-age.log` 03:00:02Z and 03:30:07Z:
   `{"error": "no boto3: No module named 'boto3'"}`) and **still reported "reported to the vault"** — `164` §5's
   "green while blind" class again, in the watchdog for the backups.
   The two files are **byte-identical**: the interpreter comes from environment only. What works is the systemd
   path — `authority-report-offsite-age.timer` (`OnBootSec=5min`, `OnUnitActiveSec=30min`, next 03:43:01Z) whose
   service sets `VENV_PY=/usr/bin/python3` (boto3 1.40.72 present) and `VAULT_KEY=/root/.ssh/id_ed25519_hetzner`;
   its journal shows real successful runs at 02:12:58Z, 02:42:59Z and 03:13:04Z with real object readings.
   **Action taken (2026-10-12 03:5xZ, cloud box, crontab backed up to
   `/root/crontab.before-audit-20261012T04.bak`):** the redundant cron line was removed — exactly one line,
   diff-verified — leaving the working timer as the single mechanism. No service was started, stopped or
   restarted; cron jobs now number **33**.
   *Still to do: reconcile the installed script back into the repo (`scripts/mesh/`), and add a
   `set -o pipefail`-proof failure path so a report that could not read the bucket never says "reported to the
   vault".*
2. **The offsite backup script streams the live database in 4 KiB pages.** `/run/authority-offsite/helpers/read-pages.py`
   was measured doing `pread` at page size (4,096 B) with `gzip -6` consuming **13 m 12 s of CPU in 23 m 43 s**
   and the run taking **1858 s**. It is correct (its verify step streams the object back and matches sha256 on
   both ends) and it never materialises a second copy — both good. But it competes with the API for the same
   single disk for half an hour each night. A 1–4 MiB read buffer is a one-line change that removes most of it.
   (Measured from `ps` + the log; the buffer size is inferred from `read-pages.py` doing page-sized reads at
   4,096 B and `pages=5370` for a 22 MB ledger file.)

---

## 6. THE FULL PARITY LEDGER — 59 of 93 office jobs have no cloud counterpart

Measured inventory: office `.cron-status/runs.tsv` holds **93 distinct job names**; the cloud crontab holds
**34** (`crontab -l | grep -oE 'cron-wrap.sh <name>'`).

**Ported (34):** ai-gateway-health, comms-refresh, comms-refresh-2, config-sync-status, cron-script-guard,
cron-target-guard, db-integrity-check, dialpad-harvest-cron, dialpad-recording-gap, dialpad-sms-harvest-cron,
dialpad-transcript-gap, disk-guard, fa-index-refresh, family-chat-watchdog, guard-registry, journal-commit,
lpt-deploy-drift, lpt-freshness-watchdog, mirror-owner-sms, monitor-hetzner-backups, production-comms-freshness,
prune-backups, reconcile-sent-status, report-offsite-age, site-uptime-check-cron, sms-inbox, stripe-key-watch,
tmpfs-reaper, website-comms-push-cron.

**Missing and named as critical:** `deadman` (the only external witness), `company-offsite-push` (the 6-hourly
restic chain), `push-db-offsite`, `push-dsh-sessions`, `transcript-archive` (superseded by the
`transcript-archive-pull.timer`, last run 03:23Z — verify), `run-sentinel`, `sentinel`-family, `sampler`,
`mesh-health`, `mesh-placement-monitor`, `nightly-plaid-sync`, `daily-finance-sync-cron`, `plaid-sync-catchup`,
`dialpad-call-fresh`, `owner-ask`, `owner-attention-digest`, `promote-owner-texts`, `supplier-order-ingest`,
`supplier-delivery-watch`, `order-feed-refresh`, `cfo-*` (3), `chip-resume`, `nightly` reconciliation family,
`serve-phone`/`serve-phone-2`/`probe-phone`, the `selftest-*` family, `wake-*` family, `run-ha-truth`,
`run-ha-behaviour`, `engine-watch`, `model-failover-watch`, `store-write-check`, `tree-integrity-check`,
`git-health-check`, `hours-drift`, `wake-balance`, `wake-cost`, `wake-fanout`, `profile-gate`, `work-integrator`,
`lpt-*` (5), `p0-phoenix`-family (3), `box-health-check`, `audit`, `auto-categorize`, `capture-test`,
`text-channel-check`, `text-line-check`, `sync`, `reconcile-sms-status`, `heartbeat`, `node-agent-cron`,
`secretary-startup`, `converge-authority`, `pain-check`, `lpt-hub-refresh`, `company-outcome-monitor`,
`run-wake-sources`, `check-*` (3).

Some of those are redundant with the in-process autopilot (80 ticks measured in 24 h) — but "some" is a
suspicion, not a measurement, and the ones that are *not* redundant are the safety net: **deadman, the offsite
push chain, the finance syncs, the sentinel, and the mesh probes.**

**Cron failure rate, last 24 h:** cloud 2,676 ok / **476 non-zero (15.1 %)** across 3,152 runs, led by
`dialpad-recording-gap 156`, `dialpad-transcript-gap 78`, `cron-target-guard 77`, `guard-registry 76`,
`ai-gateway-health 37`, `production-comms-freshness 32`. The office's long-run baseline over 96,078 recorded
runs is **6,149 rc1 + 2,293 rc3 = 9.1 % non-zero** — with the same leaders (`dialpad-recording-gap 1,349`,
`mesh-placement-monitor 1,089`, `text-channel-check 784`). **So the chronic-failure population travelled with
the migration; the rate did not improve and, on these numbers, it is slightly worse.** Whether the excess is
"more work" or "the same defects with fewer jobs to hide behind" was not determined.

---

## 7. WHAT I COULD NOT MEASURE, and why that matters

- **The cloud box has 32 hours of journal** (`journalctl --list-boots`: 2026-10-09 18:23Z → now). Anything
  earlier is gone. The office box keeps 1.7 GB of journal; the cloud keeps 102 MB. **A shorter journal is a
  robustness loss nobody asked for:** the next incident older than a day is un-diagnosable on the box.
- **No stopwatch on the *old* Throttler claim.** The throttling the owner experienced is visible as incident
  shape (sshd dead while the network answers, 3 times) but there is no recorded number for "throttled" as a
  service. My raw throughput numbers are the office box **idle**; the 2–7 MB/s is from `H3406` under load.
- **The office API's latency could not be measured** (it is stopped; starting it would break Rule 1). The only
  recorded pre-cutover reading is the broker's own probe timing out after 4,000 ms while `zabz-tech` answered in
  57 ms.
- **Why the API reaches 7.5 GB** was not determined. That is the question the sizing decision turns on.

---

## 8. THE RANKED LIST

1. **Memory is the binding constraint and it is worse than the office box.** 7.7 GB, 62 % swap, one kernel OOM
   kill of the API in 19 h, and no cgroup ceiling. Everything else on this list is smaller than this.
2. **The safety net did not move.** No dead-man switch in cron, no scheduled offsite cadence at parity with the
   office (`company-offsite-push` 6-hourly restic has no cloud equivalent), and the freshness monitor for the
   one backup that does run is pointed at the office's script.
3. **59 of 93 cron jobs have no cloud counterpart**, including the finance syncs, the sentinel, and the mesh
   probes.
4. **The rollback anchor is contaminated** — 393 MB of post-cutover rows, and it is still running processes
   (a mesh broker started *after* the freeze).
5. **The journal problem the owner remembers was a tooling problem, fixed before the migration, and the fix is
   slowly losing to growth** (status 598 ms tonight, target 400 ms; entries 3,489).
6. **Chronic cron failures travelled unchanged** (15.1 % vs the office's 9.1 %).
7. **The journal window on the authority is 32 h** — a real diagnostic regression against the office box's 1.7 GB.
8. **Two cheap defects** (§5): the mis-wired offsite-age cron and the 4 KiB page loop in the backup reader.

## 9. WHAT IS ACTUALLY, HONESTLY TRUE

The company is **much harder to knock over than it was**: the disk-starvation outage class that took sshd down
three times on the office box has **not recurred**, the lock storm dropped from **657 events in 10 days to 2 in
19 hours**, the database is in **WAL**, the backups are **verified end to end** rather than "probably fine", and
the box has run **19 hours of production with zero API restarts**. That is a real improvement and it is the one
the migration was bought for.

It is **not** "an order of magnitude faster on every metric" — on raw storage the office box is *faster*, and the
honest win is *throughput under load* and *availability*. And it is **not** "everything fixed": memory is worse,
the safety net is thinner, 59 jobs are still missing, and the rollback image moved.
