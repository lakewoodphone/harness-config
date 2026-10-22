# 000 — DISK, DATABASES AND STORAGE: the single source of truth

**This file is the one place that answers "where does the data live, how big is it, what is
authoritative, what backs it up, and what is growing."** If another document disagrees with this
one, **this one wins and the other is corrected** — that rule exists because 31 documents currently
speak on this subject and five of them contradict each other (see §9).

| | |
|---|---|
| **Last measured** | 2026-10-19 15:25Z, by a session on ZABZ-YOGA |
| **Host it describes** | `secratary-cloud` — THE AUTHORITY (sole writer of the company database) |
| **Read this before** | any disk, database, retention, backup or "let's move X" decision |
| **Owner** | the estate; changes go through `journal.py append decisions` |

> **Rule 0.** Every number below was measured with the command shown. Nothing here is remembered.
> When you change something this file describes, change this file in the same commit.

---

## 1. The machine, as measured (2026-10-19, after the CCX23 → CCX33 rescale)

| | value | how measured |
|---|---|---|
| Provider / plan | Hetzner Cloud **CCX33** | `nproc`, `free -g`, `lsblk` |
| Location | **Ashburn, Virginia** (`us-east`, `ash-dc1`) | `curl ipinfo.io`, Hetzner metadata |
| Instance / IP | `169556315` / `178.156.194.1`, tailnet `100.73.176.126` | `curl 169.254.169.254/hetzner/v1/metadata` |
| CPU | **8 dedicated vCPU** (AMD EPYC-Milan) | `nproc` |
| RAM | **~31.3 GB** usable | `free -m` |
| Disk | `/dev/sda` 246 GB → `sda1` 245 GB → **ext4 225 GiB** | `lsblk -b`, `parted -s /dev/sda print`, `df -h /` |
| Used / free | **118 G used, 99 G free (55%)** | `df -h /` |
| Swap | 2 × 4 GB files, **0 B used** | `swapon --show` |
| Services | 29 running, 39 timers, 76 cron jobs / 252 crontab lines | `systemctl`, `crontab -l` |

The rescale **grew the partition and filesystem automatically** — the runbook's warning about
needing a Rescue-System resize did not apply here. Verified: partition 245,490,499,072 B, filesystem
241,566,183,424 B usable.

---

## 2. What is authoritative, what is derived — every database

### 2.1 THE source of truth

| | |
|---|---|
| path | **`/root/authority.db`** |
| size | **34,088,206,336 B (31.75 GiB)** |
| engine | SQLite, `journal_mode=WAL`, `page_size=4096`, `synchronous=NORMAL` |
| schema | **240 tables**, 8,856 `dsh_sessions`, 27,566 `memories`, 29,387 `tasks`, 2,749,996 `dsh_session_events` |
| writer | `company-api.service` (uvicorn, `127.0.0.1:8002`) — **the only long-lived writer** |
| off-site | yes — see §4 |

**Inside it, the shape that matters:** `dsh_session_events` plus its FTS index is ~89% of the file.
That one corpus is the whole disk story. Everything else in the database totals ~3 GiB.

### 2.2 The traps — files that look like the truth and are not

| path | size | what it is | verdict |
|---|---|---|---|
| `/opt/company/secretary.db` | **0 B** | decoy | never read |
| `/opt/company/data/secretary.db` | **1.9 MB** | the app's *default* path when no env var is set | **not the company** — if the API ever reports this, it is pointed at the wrong file |
| `/opt/company/data/harness-config.bak-*` | removed 2026-10-19 | stale repo copy | gone |

### 2.3 Derived — regenerable, never back these up as if they were data

| path | size | rebuilt from |
|---|---|---|
| `/root/.usearch/usearch.db` | was **10,851,082,240 B / 697,067 docs**; **deleted 2026-10-19T06:53Z** to save disk; ~64 MB now | `esearch` re-ingest of files, comms and mail |
| `/opt/company/data/chromadb/chroma.sqlite3` | ~2.4 GB | ChromaDB vectors |
| `/opt/company/data/mem0/chroma.sqlite3` | ~0.37 GB | mem0 |
| `/root/.fsearch/comms.db` | ~230 MB | comms index rebuild (every 30 min) |
| `dsh_session_events_fts*` | see §3 | `dsh_session_events` |

### 2.4 Source data that lives ONLY here — back these up deliberately

| path | size | note |
|---|---|---|
| `/root/accounting-data/live/accounting.db` | ~0.97 GB | the ledger; already streamed by the offsite job |
| `/root/mail-archive/*/archive.db` (×5) | ~1.17 GB | **explicitly excluded from backups — likely the only copy** |
| `/root/.cfo` | ~1.3 GB | CFO state and backups |
| `/root/.dsh` | ~0.97 GB | the phone engine's local DSH home (raw session history) |
| `/root/bin` | 25 MB, **516 scripts** | many are the only copy; cron targets |
| `/opt/company/data/dialpad` | ~1.4 GB | comms mirror |
| `/opt/company/archive/lpt-transcripts` | 7.48 GiB, 51,742 objects | **the permanent transcript archive** |

### 2.5 Off-box and outside this disk

`phone-and-tech-full` on **Heroku/RDS** is the shop's own source of truth and appears in no disk
document before this one. It is not backed up by anything described here.

---

## 3. The one real problem: `dsh_session_events` and its index

```
CREATE VIRTUAL TABLE dsh_session_events_fts USING fts5(
  source_machine UNINDEXED, session_id UNINDEXED, ordinal UNINDEXED, raw)
```

**No `content=` clause.** FTS5 therefore keeps its **own second copy of every `raw`** in a shadow
table called `dsh_session_events_fts_content`, beside the real index in `_data`. The same text is
stored twice:

| object | size |
|---|---|
| `dsh_session_events` | 11.7 GiB |
| `dsh_session_events_fts_content` — **the duplicate** | 11.3 GiB |
| `dsh_session_events_fts_data` — the actual index | 5.1 GiB |
| everything else in the database | ~3.1 GiB |

**Growth: ~1.28 GB/day**, from ingested agent sessions (2.75M events as of 2026-10-19).

**The fix**, proven twice on rehearsal copies and then executed on the live database on
2026-10-19: convert the index to external content (`content='dsh_session_events',
content_rowid='rowid'`) and maintain it with three triggers. The duplicate disappears; the text stays
in the base table; `SELECT raw` through the index keeps working; `snippet()` and `rank` keep working.
**Information lost: none.**

**DONE 2026-10-19 15:34Z.** Verified independently afterwards:

```
objects|8   (fts, _data, _idx, _docsize, _config + 3 triggers)
content_shadow|0            <- the duplicate is gone
base|2749996 = fts|2749996 = docsize|2749996
integrity-check=ok
freelist|3352593 pages = 12.8 GiB now reusable inside the file
match 'dialpad'|68655      (was 9 while the index was empty)
```

All three triggers were proved live with a marked test row that was then removed: insert indexed,
update pulled the old text out and put the new in, delete removed the entry. **Ingest code changed
in the same window** — `app/services/dsh_session_ingest.py` no longer writes the index by hand and
no longer reads `_content` (which no longer exists); the triggers are the whole contract.

| | measured before the conversion |
|---|---|
| WAL required to drop the 16.4 GiB index | **17.7 GB in one transaction** — measured at exactly **1.006× the index size** on a scaled replica |
| bulk rebuild rate | **41,585 rows/s** synthetic; **7,500 rows/s** on the real corpus (all 2.75M in **364 s**) |
| per-document delete rate | **~65 rows/s** — why emptying it row-by-row is an 11-hour job and must never be attempted |
| does the file shrink? | **No.** Freed pages go to the freelist and are reused. The win is that **the file stops growing** for ~12.8 GiB of new writes (~10 months at 1.28 GB/day). Only `VACUUM INTO` returns bytes to the filesystem — worth doing in a quiet window, not urgent with 99 GB free. |

**There is already a converter in the estate: `/root/fts-convert.sh`** (2026-10-09, from audit
D2954). Use it or the audited equivalent; do not write a third. Its header's premise ("the DB is a
disposable copy, the authority is on the office box") is **stale — that was true before the
2026-10-11 cutover, and the opposite is true now.**

**Two operational facts learned the hard way:**
* **Never interrupt the DROP.** An earlier attempt was killed mid-statement and left the index at
  1,304 documents against 2,749,996 rows — recoverable (rebuild it) but it silently killed search.
  When the DROP is finished the file's pages are already on the freelist, so a *re-run* drops it
  instantly: that is what made the successful run cheap.
* **`pragma quick_check` on this file takes ~4 minutes and returns `ok`** — use it, not
  `integrity_check`, which is slower and pins the WAL for the duration.

---

## 4. Backups — what actually runs, and what is dead

### 4.1 Cloudflare R2 (the offsite store)

| | |
|---|---|
| buckets | **`lpt-authority-backups`** — 22 objects, **31.58 GiB** · **`psm-backups`** — 2,711 objects, **36.83 GiB** |
| total | **68.41 GiB** |
| **cost** | **~$1.10/month** gross, ~$0.95 after the 10 GB-month free tier. **Egress is free.** |
| credentials | `/root/.lpt-r2.env` (600, bucket-scoped, read+write). `ListBuckets` is denied by design. |
| lifecycle rules | **not verified** (AccessDenied) and no script references one — the cost trend is monotonic |

**Live legs:**

| leg | schedule | last real run (measured) | verdict |
|---|---|---|---|
| database → `authority/secretary.db.gz` | daily ~05:20Z via `authority-offsite-backup.timer` | **2026-10-19T05:49:03Z**, exit 0, sha256 verified, `sqlite_magic=ok`, 9,285,999,695 B gz, 1,701 s | **healthy** |
| `/opt/company/data` → `authority/data/authority-data.tar.gz` | daily 06:30Z | **2026-10-19T07:11:27Z**, 110,838 entries | healthy |
| cold archive → `cold-archive/20261019T145927Z/` | one-off, manual | 2026-10-19T15:02Z, 6,143,027,851 B, sha256 `c499ddf2…` | verified |

**Dead legs — these are the finding:**

| leg | state |
|---|---|
| **restic `company-offsite`** (the 6-hourly tarball) | **DEAD. Newest snapshot `49651d40` = 2026-10-11T19:40:16Z — 186 hours (7.75 days) old.** Its producer lived on the office box, which is frozen. `company-offsite-status.log` has printed `CRITICAL … 186h old (limit 30h)` hourly since 2026-10-12 and **nothing pages.** |
| the freshness monitor | `authority-report-offsite-age.sh` HEADs **one key** and writes "fresh" — it cannot see the restic leg at all. This is the 2026-10-16 failure class repeating. |
| an unowned restic repo at `psm-backups` root | live, **different password**, written 2026-10-19T03:30Z, **no script references it** |

**Not in R2 at all:** `/root/mail-archive` (2.6 GB, likely sole copy), the transcript archive's
current state, the HA instance's automatic backup (Pi-only), and `mac-mini` / `zabz-tech-linux`
which have no restic.

### 4.2 Restore — proven for the first time on 2026-10-19

The offsite object was restored end to end: 8,818,216,441 B, sha256 verified, decompressed to
32,287,965,184 B, `PRAGMA integrity_check` = **`ok` in 509 s**, 237 tables, newest row
`2026-10-18T05:18:32Z`. **RPO is 24 hours, not 6** — the daily leg is the only live one.

> **Standing recommendation:** add `PRAGMA quick_check` inside the same read transaction as the
> backup's page stream (measured 251 s, zero disk, zero egress). That makes every daily object
> provably integrity-checked without a 34 GiB scratch copy.

---

## 5. Monitoring — fixed 2026-10-19

`/usr/local/bin/disk-guard.py`, every 15 min via cron, writes `/root/.disk-guard/status.json` and
`guard.log`.

**It was wrong by ~4 points.** It computed `used / total`; `df` computes `used / (used + available)`.
With ~6.57 GB of ext4 reserved blocks, `WARN 90` actually fired at df 93.8% and `CRIT 95` at df
**99.0%** — unreachable before zero. Fixed to `used / (used + free)` and verified live.

**Still true and still dangerous:** the ALARM line goes to a log **nothing reads**;
`guard-registry-check` exits rc=3 ("condition, not fault") which files no repair;
`sources/disk-space.py` is the real escalation and it reports **`suppressed:attempts`** once its
retry budget is spent. Tonight's alarms were raised and suppressed, and the owner learned about the
disk from a queue row instead.

---

## 6. The whole estate — every disk we pay for, measured 2026-10-19

| host | plan / location | disk | used | free | what it is |
|---|---|---|---|---|---|
| **`secratary-cloud`** | **CCX33** / Ashburn | **225 GiB** | 118 G | **99 G (55%)** | THE AUTHORITY |
| `lpt-apps-01` | CX33 / Falkenstein | 75 G | **65 G** | **6.8 G (91%)** | Caddy front door, R2 credential holder, restic vault — **swapping, do not add load** |
| `lpt-survivor-01` | CX33 / Falkenstein | 75 G | 8.2 G | **64 G (12%)** | the standby. **Idle — the best host in the estate for cold copies** |
| `waze-mdm-01` | CPX11 / Ashburn | 38 G | 26 G | 11 G (72%) | production MDM, not ours to reconfigure |

**Cost: 177.46 EUR / 208.86 USD per month**, including four IPv4 addresses. The authority alone is
**165.99 USD — 79.5% of the bill.** The June 2026 Hetzner adjustment roughly doubled CCX33, and a
rescale on or after that date bills at the new price, so the CCX23→CCX33 move also moved that line
to current pricing.

### 6.1 Duplication — bytes paid for more than once

| what | where | size |
|---|---|---|
| **git worktrees of the same repos** | authority | **29.4 GB across 130 worktrees** — 83 share `/opt/company/.git` (10.0 G), 23 share `phone-and-tech-full` (13.5 G), 19 share `harness-config` (1.5 G), 2 share `lpt-hub` (4.2 G) |
| harness-config history | authority `.git` 2.0 G + lpt-apps bare repo 2.5 G | 4.5 GB |
| company repo object store | authority 8.3 G + survivor 0.29 G | 8.6 GB |
| the company database | authority 34 G · survivor **620 MB from 2026-10-11** · R2 8.65 GiB | survivor is **8 days stale — not a usable failover duplicate** |

### 6.2 Waste that can be reclaimed without losing anything

| host | item | size | risk |
|---|---|---|---|
| lpt-apps-01 | **docker images, 70% reclaimable** | **25.92 GB** | none — `docker image prune` |
| lpt-apps-01 | build cache | 9.02 GB | none — `docker builder prune` |
| lpt-apps-01 | `/tmp` old seeds and drill read-backs | 6.8 GB | check age first |
| authority | `*.bak-*` older than 3 days | 0.61 GB (1,809 files) | none |
| authority | swap files, **0 B used** | **8 GB** | none with 27 GB RAM free |
| authority | caches (`.local`, `.npm`, `.fsearch`, `.faindex`, `.usearch`) | 3.65 GB | `.dsh` may hold sessions — check first |
| waze-mdm-01 | images + build cache + journal | 13.8 GB | not ours |

### 6.3 Never on the root volume

Docker/containerd images and build cache — `lpt-apps` is 91% full because 43 GB of containerd and
9 GB of buildkit sit on its root disk. Also: `/tmp` build and restore seeds, rotating `*.bak-*`,
rescue bundles, the transcript archive beyond a hot window, more than about a dozen concurrent
worktrees, and **an unbounded WAL** — tonight's reached 18 GB and swung the free-space reading by
14 GB in twenty minutes.

### 6.4 What we pay for and are not using

| resource | paid for | currently | change worth making |
|---|---|---|---|
| **RAM** | 32 GB | `company-api` capped at **MemoryMax=12G**, peaking 9.9G; `esearch` capped at **1536M** while holding a 10 GB index; 27 GB available | raise the API cap; give esearch several GB. **The cap was written when this box had 7.7 GB** |
| **disk** | 225 GiB | **99 GB free** | reclaim the 8 GB of swap files; `VACUUM INTO` once in a quiet window to return the 12.8 GiB of freed pages |
| **SQLite cache** | — | `cache_size` = **64 MB per connection** against a 34 GB database | raise it; there is memory to spend |
| **esearch index** | — | deleted 06:53Z to save disk; 1,705 docs; `esearch-health ok:false` | **rebuild it** — the disk pressure that forced its deletion no longer exists |
| **lpt-survivor-01** | a whole 75 GB server | 8.2 GB used, load 0.00 | it is the estate's idle cold-storage host |

---

## 7. Operating rules that keep this from recurring

1. **Never `GROUP BY` / `DISTINCT` / `ORDER BY` over `dsh_session_events` on this host.** It spills
   a multi-GB sorter into `/var/tmp`, **on the database's own filesystem**, and the spill file is
   unlinked so `du` cannot see it. Streaming aggregates (`count(*)`, `sum(length(raw))`,
   `conditional sum(case…)`) are safe and were measured at 2m11s for the whole table.
2. **`lsof -nP +L1` is the check that finds a spill** — never `du`.
3. **`/tmp` is a 2 GiB tmpfs.** All scratch goes to `/var/tmp` or `/root`.
4. **A `TEMP` table does not survive between `sqlite3` invocations** — one process, or a heredoc.
5. **`pragma integrity_check` pins the WAL**: while it runs, no checkpoint can advance, so a
   harmless-looking reader can starve a writer. Kill stray readers before write-heavy work.
6. **Dropping a large FTS index requires WAL equal to its size in one transaction.** Budget ~2× the
   index size in free space before you start.
7. **`du` under-reports `/opt/company/archive`** (12 MB reported against 7.48 GiB real). Size it with
   `find -printf %s` or the manifest.
8. **Only one writer.** The office box `secratary` is the FROZEN rollback anchor — see
   `settings/machines/host-posture.tsv`.

---

## 8. Change log

| date | change |
|---|---|
| 2026-10-19 | This document created; consolidates 31 documents into one. |
| 2026-10-19 | Rescale CCX23 → CCX33 (8 vCPU / 32 GB / 225 GiB); partition and filesystem grew automatically; ~2 min outage; DB byte-identical. |
| 2026-10-19 | `disk-guard.py` percentage fixed (`used/(used+free)`). |
| 2026-10-19 | 13 GB of cold work trees, rescue bundles and abandoned workdirs archived to R2 `cold-archive/20261019T145927Z/` (sha256 `c499ddf2…`, verified twice) and removed locally. |
| 2026-10-19 | `usearch.db` (10.85 GB) deleted at 06:53Z to free disk — search degraded since. |
| 2026-10-19 | An interrupted FTS conversion left `dsh_session_events_fts_content` at 1,304 rows against a 2,749,996-row base table. **Base data intact; index rebuildable (§3).** |

---

## 9. Contradictions this document resolves

| claim | where it was | truth |
|---|---|---|
| CCX13, 2 vCPU, 7.7 GB, 75 GB | `000-SYSTEMS-REGISTER.md:22` | **CCX33, 8 vCPU, 32 GB, 225 GiB** — the register is stale |
| bucket `lakewood-rentals-media` | register §3 vs §2.2, 69 lines apart | **`lpt-authority-backups`** (and `psm-backups` for restic) |
| company DB = "`secretary.db` on the authority" | register §113 | `/root/authority.db`; `/opt/company/data/secretary.db` is a 1.9 MB app default |
| growth ~300 MB/day | `RECLAIM-…T0945Z:54` | **~1.28 GB/day** |
| growth ~2.1 GB/day | `RECLAIM-…1550Z:45` | ~1.28 GB/day measured |
| "the 6-hourly offsite run" | `RECLAIM-…T0945Z:61` | daily 05:20Z; the 6-hourly restic leg is **dead** |
| 25.63 GiB `authority.db.pre-remediation-*` is protected | `sources/README.md:164` | **removed 2026-10-15**; the directory is 15 MB |
| 160 GB is the CCX ceiling | a session's own wrong conclusion, 2026-10-19 | CCX33/43/53/63 give **240 / 360 / 600 / 960 GB** |

---

## 10. Where this document is advertised

A file nobody opens is the defect this estate keeps paying for. These five places must point here:

1. `docs/mesh/000-SYSTEMS-REGISTER.md` — header line.
2. `AGENTS.md` §1 (the archive section) — one line.
3. `/opt/company/AGENTS.md` — one line.
4. `/root/bin/sources/disk-space.py` — the wake source that fires at 90%: the agent woken by it must
   be told to read this file.
5. The `estate-systems` skill — one line under "before you design anything".

**Structural note:** `docs/mesh/` has **16 colliding numeric prefixes** (three files numbered 133,
134, 135, 137…), so "docs/mesh/134" does not name a document. Prefer this file's name, not a number.
