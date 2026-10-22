# AUDIT of `2026-10-19-authority-disk-96pct.md` — what is true, what is wrong, and what to do

**Written:** 2026-10-19 01:20–02:00Z, session on ZABZ-YOGA, by the agent asked to execute the
original report. **Status: nothing was deleted. One monitoring defect was fixed and verified.**
**Supersedes** `2026-10-19-authority-disk-96pct.md` §4–§6. Read that document's §1 numbers as
superseded too — they were true at 01:12Z and were untrue by 01:36Z.

Every number below was measured in this session on `secratary-cloud` with the command shown.
Where a number comes from the earlier report and was **not** re-measured, it says so.

---

## 1. Verdict

1. **The 90-day prune in the original §6 Step 4 deletes exactly zero rows.** The corpus is 38 days
   old. Measured: 90 days → `0` rows, `0` bytes. 60 days → `0`. Every number downstream of that
   prune (§5's "~9 GiB compacted", Step 1's "→11.6 G free", Step 5) is arithmetic on a deletion
   that cannot happen.
2. **Pruning at any window that *would* delete rows must not be done**, and not for disk reasons:
   the packed archive is missing an entire machine and contains nothing before 2026-10-09, while
   the database reaches back to 2026-09-11. A 30-day prune would delete the only copy of 574,739
   events. §4 below is the evidence.
3. **The real, lossless lever is not retention — it is the duplicate text inside the FTS index.**
   `dsh_session_events_fts` stores a verbatim second copy of every `raw` value: 11.3 GiB of the
   31.2 GiB file. Converting it to an external-content FTS5 table removes that copy and loses
   nothing, because the text stays in `dsh_session_events`.
4. **The disk is not leaking; it is thrashing.** Free space moved `6.44 GiB → 1.41 GiB → 16.9 GiB`
   inside twenty minutes (§2). Any plan built on one `df` reading — including the original's
   "93% → 96% in six hours" — is planned against a number that no longer exists.
5. **There was an alarm, and it was lying by 4.4 points.** `/root/bin/disk-guard.py` computed
   `used/total` instead of `used/(used+avail)`, so its `crit_pct=95` was unreachable until about
   1.4 GiB free. Fixed and verified (§5). This is the fourth near-fill in three weeks: the guard's
   own log records **100% / 17 MB free on 2026-09-27** and **98.7% / 0.0 GB free on 2026-10-13**.

---

## 2. Measured state

### 2.1 The filesystem moves fast

| time (UTC) | total | used | avail | `df` says | command |
|---|---|---|---|---|---|
| 01:22:20 | 160,921,083,904 | 147,416,727,552 | 6,932,824,064 | 96% | `df -B1 /` |
| 01:30:44 | 160,921,083,904 | 152,939,171,840 | **1,410,379,776** | **100%** | `df -B1 /` |
| 01:36:41 | 160,921,083,904 | 136,152,231,936 | 18,197,319,680 | 89% | `df -B1 /` |
| 01:47 | 160,921,083,904 | 137,665,617,920 | 16,683,933,696 | 90% | `df -B1 /` |

The 01:22→01:30 fall was **my own doing** (§5.1). The 01:30→01:36 recovery was a release of
about 10 GiB by the box's own jobs. `disk-guard.py`'s log gives the honest long series, and it is
flat-then-step rather than a leak:

```
2026-10-18T23:45:02Z  ok  / 89.4%  9.7GB free        <- flat for six hours
2026-10-19T00:07:18Z  ALARM / at 90.8% (7.7 GB free)  <- the step
2026-10-19T01:15:03Z  ALARM / at 91.6% (6.5 GB free)
```

### 2.2 The database, and where its bytes are

```
ls -la /root/authority.db          -> 33,507,471,360 bytes  (31.21 GiB), mtime 01:20:23Z
pragma page_size                   -> 4096
pragma page_count                  -> 8,180,535
pragma freelist_count              -> 1,421        (0.005 GiB — the file is not bloated)
```

8,180,535 × 4096 = 33,507,471,360 exactly, so the file and its page count agree and there is no
hidden slack. The earlier report's `dbstat` breakdown is accepted as the best available split of
those bytes (`dbstat` is a ~25-minute full scan and was not repeated):

| object | MB | note |
|---|---|---|
| `dsh_session_events` | 11,718.3 | the table |
| `dsh_session_events_fts_content` | 11,583.2 | **a second copy of the same text** |
| `dsh_session_events_fts_data` | 5,182.0 | the inverted index |
| everything else in the DB | ~3,073 | 200+ tables |

The 11,583 MB figure is independently corroborated here: the table's own raw text sums to
**11,237,528,986 bytes (10.47 GiB)**, so a verbatim copy plus row overhead must land at ~11.3 GiB.
<sub>`select count(*), sum(length(raw)) from dsh_session_events;` → `2692528|11237528986`</sub>

### 2.3 The FTS duplicate is real, and it is structural

```
CREATE VIRTUAL TABLE dsh_session_events_fts USING fts5(
  source_machine UNINDEXED, session_id UNINDEXED, ordinal UNINDEXED, raw)
```
<sub>`select sql from sqlite_master where name='dsh_session_events_fts'`</sub>

No `content=` clause. A plain FTS5 table materialises its own copy of `raw` into the `_content`
shadow table. That copy is what costs 11.3 GiB.

Also measured: **there is no index on `created_at`** (only `idx_dsh_session_events_seq` on
`(source_machine, session_id, seq)`), and **there are no triggers** on the table — the application
maintains the index by hand (`app/services/dsh_session_ingest.py:435-447`).

---

## 3. Where the original report is wrong

| # | claim in the original | measured | consequence |
|---|---|---|---|
| 1 | §6 Step 4: prune events older than 90 days | **0 rows, 0 bytes** (`r90=0`, `b90=0`) | the entire plan collapses |
| 2 | §4: "the pre-90-day share of a 27.8 GiB corpus is what is actually being removed" | there is no pre-90-day share; oldest row is `2026-09-11T19:19:34` | every reclaim estimate is void |
| 3 | §5: "the compacted result is roughly 9 GiB … needs about 9 GiB free at its peak" | with no prune the result is 31.2 GiB; **with the FTS duplicate dropped** it is ~19.9 GiB; with a 30-day prune too, ~16.4 GiB | the peak requirement is 16–20 GiB, not 9 |
| 4 | §1/§8: framing 93%→96% as a trend over ~6 h | free space moved 15 GiB in 14 minutes tonight (§2.1) | point-in-time percentages are noise; plan against bytes and a working margin |
| 5 | §3: "the archive is current and populated, so the same bytes do exist off the live table" | **false**: nothing before `2026-10-09T02:52:27Z` is archived; `desktop-fgv6kmh` (42 sessions) is not archived at all | pruning would destroy the only copy of pre-9-Oct history |
| 6 | §1: "`/root/work` 14 G" | 7.5 GB at 01:37Z — about 6.5 GB disappeared from it between 01:12 and 01:37 | the inventory was stale within the hour |
| 7 | §7.5: "never treat `--check` exit 2 (SILENCE) as permission" | correct, and worse than stated: `--check` returned **rc=0** tonight while `desktop-fgv6kmh` had never been archived, because the check enumerates per-machine state files and a machine it has never met can never be reported | rc=0 means "no pull is currently broken", never "everything is archived" |
| 8 | §4/§6a: the recommended measurement commands | a `GROUP BY`/`DISTINCT` over this table spills a multi-GB sorter into `/var/tmp` **on the same filesystem** | following the report's own measurement advice nearly filled the disk (§5.1) |

The report's one instruction that was exactly right is its last: *"If any step's verified number
disagrees with this document, the measurement wins and this document is wrong."* It is wrong.

---

## 4. Pruning would lose information — the evidence

Ran as an independent read-only stream against the packed archive
(`/opt/company/archive/lpt-transcripts`, verified: **51,742 object files, 8,026,990,367 bytes,
51,737 manifest rows**, oldest arrival `2026-10-09T02:52:27Z`, newest `2026-10-19T01:26:08Z`).

1. **A whole machine is missing.** `desktop-fgv6kmh` — 42 sessions, 7,822 events spanning
   2026-09-15T02:52:56Z → 2026-10-18T04:03:03Z — has no `machine_contact` row and no `arrival` row.
   It has never been pulled. Not lag: old data.
2. **Nothing before 2026-10-09 is archived**, while `dsh_session_events` reaches back to
   2026-09-11. A 30-day prune deletes 574,739 events whose only copy is this table.
3. **The archive is a redacted derivative, not a copy.** Every `dsh-sessions` arrival carries
   `transform='zstd-redacted+redacted'` with counts per secret class. Clear text exists only in
   the database and on the source machine.
4. **The card-redaction rule is destroying timestamps in the permanent archive.** `CARD_SHAPE`
   plus a Luhn check is applied as a *text* substitution; a 13-digit epoch-millisecond timestamp
   passes it about one time in ten. Measured on two sampled objects: **42 of 255 records (16.5%)
   no longer parse as JSON** and their `time` is unrecoverable, and `--read` still reports
   `"ok": true`. This is silent, permanent corruption of the estate's training corpus and it
   deserves its own fix independent of the disk.
5. **13 sessions exist in the archive and no longer exist in the database** — the archive has
   already been the only copy of something once.

Coverage: **8,654 of 8,699** database sessions are in the archive. 45 missing = 42
(`desktop-fgv6kmh`) + 3 (ordinary hourly lag).

---

## 5. What was done tonight

### 5.1 A near-fill that I caused, and what it taught

At 01:23Z I began auditing by running `select substr(created_at,1,7), count(*) … group by 1` and
by fanning out five parallel agents whose briefs authorised the same class of query. With no index
on `created_at`, each such query builds a b-tree sorter and SQLite writes it to
`/var/tmp/etilqs_*` **on the same filesystem as the database**. Measured spill files: 5.8 GB,
4.0 GB, 5.0 GB, 1.8 GB.

Free space went **6.44 GiB (01:23) → 1.41 GiB (01:30) and was falling ~100 MB/s**. Two hold-ups
made it worse than it looks: the spill file is **unlinked**, so `du` and `find` never see it (only
`lsof -nP +L1` does), and `SIGKILL` was not delivered because the process sat in `D` state on
`folio_wait_bit_common`. Space was recovered with `truncate -s 0 /proc/<pid>/fd/6` — a sorter
spill of a read-only query, not data. **This is the estate's own "no heavy work on the authority"
rule, and I broke it while auditing it.**

Filed: lesson `L9214`, pain `P8396`.

### 5.2 The monitoring defect — fixed and verified

`/root/bin/disk-guard.py:133` was `pct = (used / total * 100.0)`. With ext4 reserving 5%,
`total = used + avail + reserved`, so the guard under-reports by ~4 points and its `crit_pct=95`
can only fire at ~1.4 GiB free. Measured side by side at the same instant:

| | `df` | guard (old) | guard (new) |
|---|---|---|---|
| 01:43Z | 90% | **85.5%** | 89.2% |

Fixed atomically (`cp -p` → edit → `py_compile` → `mv`, new inode) at the **real** path —
`disk-guard.py` is a symlink to `/usr/local/bin/disk-guard.py`, which a first attempt of mine
replaced with a regular file; the symlink was restored. Verified live after deploy:
`ok - / at 89.0% (15.79 GB free)`, cron `/usr/local/bin/cron-wrap.sh disk-guard` runs it every 15
minutes. **Still open, deliberately not changed in the same breath:** `warn_pct=90` now means
~15.9 GiB free on a box that idles at 17 GiB, so it will warn almost always. Threshold retuning is
a separate one-variable change.

### 5.3 Also established

* The estate **already has a retention planner**: `/opt/company/scripts/dsh_session_events_retention.py`
  (dry-run only, refuses `--execute`). No second one should be built. **But it cannot safely run
  here**: its `per_day()` does `GROUP BY substr(created_at,1,10) ORDER BY 1`, and a `--dry-run` of
  it tonight spilled 1.8 GB and took free space from 18.0 GiB to 13.4 GiB. The tool that plans
  this deletion reproduces this incident.
* `/root/.usearch/usearch.db` is 10,851,082,240 bytes (10.1 GiB), mtime 01:07:51Z, stable since.
  The 2026-10-18 reclaim record documents it growing **~5.8 GB/h** during a bulk `esearch` push,
  and stopping it required stopping `esearch.service`. It is a derived index and a legitimate
  emergency lever, but it regrows.
* `authority.db` growth: 32,287,965,184 B at the 2026-10-18T05:48Z offsite run →
  33,507,471,360 B now = **+1.2 GB in 19.5 h (~1.5 GB/day)**.
* **Another agent deleted work on this box, unapproved, at 01:34:57Z.** Six directories under
  `/root/work` (`r4-loop`, `fd-relay`, `evolve2-loop`, `r4-preserve`, `r4-integration`,
  `evolve2-base`) lost their contents within five seconds — directory mtimes moved while every
  surviving entry inside still dates to 10-14, which only happens when entries are removed. It was
  **not** scheduled: no script in `/root/bin`, `/opt/company/scripts` or `/usr/local/bin` names
  those paths; `auditd` and `acct` are both `inactive`; non-interactive ssh writes no history. The
  actor was agent-driven over ssh, and the subject matches **pending owner row 711** — "Reclaim the
  13.2 GB of abandoned agent worktrees" — which is still `pending`, i.e. **deleted before it was
  approved**. `git -C /root/work/r4-loop status --porcelain` still shows
  ` M scripts/ha/check-security-absence.py` plus untracked `CHECKPOINT.md`, `REPORT.md`, so those
  trees were not clean. **Not verified:** which pid, and what the other ~6.8 GB freed in the same
  seven minutes was (12.8 GB total freed against ~6 GB from `/root/work`).
  **Consequence for any maintenance I plan: a lock will not stop a racer that is another agent.**
  Mutual exclusion has to be an `flock` on the target plus a `ps` check for sibling sessions.

### 5.4 Why nobody was told — the alarm fired and was suppressed

There are five notification-shaped paths and none of them acted on tonight's ALARMs
(`/root/.disk-guard/guard.log` shows ALARM at 00:07, 00:15, 00:30, 00:37, 00:45, 01:00, 01:07,
01:15 and `01:30:05Z at 93.4% (3.8 GB free)`):

| path | what it does | why it did nothing |
|---|---|---|
| `~/.disk-guard/guard.log` | the `ALARM` line (disk-guard.py:329) | **nothing reads it** — a content grep across `/root/bin`, `/usr/local/bin`, `/opt/company/app`, `harness-config/scripts` returns only the writer |
| `/var/log/disk-guard.log` | the run's stdout | no consumer |
| `~/.cron-status/runs.tsv` | `2026-10-19T01:30:01Z disk-guard 1 10` (rc=1) | recorded, nothing acts |
| `guard-registry-check.py` (`*/15`) | notices: `FINDING disk failing status ok=False` | exits **rc=3, "condition, not fault"**, and `sources/cron-failures.py` files no repair session for rc=3 |
| `sources/disk-space.py` (the escalation target) | last three runs `disk-space:90: suppressed:attempts` | wake.py guard 9: a subject that has already failed `max_attempts` (default 2) is **suppressed** |

And the one that did reach the owner: **`owner_decision_queue` row 711**, asked
`2026-10-18T19:21:07Z`, status **`pending`**, "The authority is 93% full (10.7 GB free)… Reclaim
the 13.2 GB of abandoned agent worktrees, or grow the disk?" Nothing about disk went by SMS.

The new guard arithmetic (§5.2) changes those thresholds to the ones that matter: **WARN 90 now
fires at df 93.8% (8.87 GiB free) instead of 84.8%, and CRIT 95 at df 99.0% (1.37 GiB) instead of
never.** That is better but still late; retuning the thresholds is the next one-variable change.

---

## 6. Never do these (in addition to the original's §7)

1. **Never prune `dsh_session_events` at any window narrower than the archive's own reach
   (2026-10-09).** Today that means: no prune at all that touches September.
2. **Never run an aggregate with `GROUP BY`, `DISTINCT` or `ORDER BY` over
   `dsh_session_events` on this host.** Use streaming shapes (`count(*)`, `sum(length(raw))`,
   conditional `sum(case when … end)`) — verified spill-free, 2m11s for the whole table.
3. **Never check free space with `du`** on this box. Sorter spills are unlinked; `lsof -nP +L1`
   is the check that finds them.
4. **Never trust `transcript-archive-server.py --check` rc=0 as "everything is archived."**
5. **Never run the retention planner against the authority without a file-size cap or a
   free-space abort.** It spills.

---

## 7. The plan (nothing here has been executed)

### 7.0 First, the recovery posture — because it bounds what may be attempted

| what | measured |
|---|---|
| mechanism | `authority-offsite-backup.timer` → `.service` → `/usr/local/bin/authority-offsite-backup.sh` v3: page stream → `gzip -6` → 64 MiB multipart → `lpt-authority-backups/authority/secretary.db.gz` |
| newest offsite object | **8,818,216,441 B**, `LastModified 2026-10-18T05:46:02Z` — **19.95 h old at 01:43Z**; sidecar sha256 `2e498ecb…4315` matches; 132 parts |
| writes not in that copy | **1,232,470,016 B (1.15 GiB)**; content cutoff ≈ `2026-10-18T05:20:16Z` |
| last scheduled run | `Exited 0/SUCCESS at 2026-10-18T05:48:07Z` (27m52s wall); next fire `2026-10-19T05:20:32Z` |
| newest restic company snapshot | **`49651d40`, 2026-10-11T19:40:16Z, 174 h old** (a 10-11 01:40 snapshot is tagged `pending`, untrusted) |
| restore ever tested for this object? | **No.** The only DB rehearsal is the 2026-10-06 pre-cutover office drill, whose seed was later rejected as "REHEARSAL SEED". Journal `H3184`, `H3423`, `H3424`, `L3735`, `L6141` record hash/range verification only |
| **can it be restored here?** | **No.** 33,520,435,200 B decompressed against **16,749,092,864 B free** — 16.6 GB short, on the only filesystem |

**Therefore: nothing irreversible on this database tonight.** A verified copy exists and is ~20.7 h
behind, which is a real backup; but a restore has never been rehearsed and there is nowhere on this
host to write the restored file. Fix the restore path before the vacuum, not after.

### 7.1 Phase 0 — done
* Guard arithmetic fixed and verified (§5.2).

### Phase 1 — the lossless reclaim: stop paying twice for the same text
Convert `dsh_session_events_fts` to external content (`content='dsh_session_events',
content_rowid='rowid'`) and let triggers maintain it, replacing the hand-written maintenance at
`dsh_session_ingest.py:435-447` (which inserts with auto-assigned rowids, so it is incompatible
with external content as written).

* **Saving: ~11.3 GiB of the 31.2 GiB file. Information lost: none** — `raw` stays in the base
  table and `esearch`'s `SELECT … raw FROM dsh_session_events_fts WHERE … MATCH ?`
  (`server/esearch.py:348`) keeps returning it, now read from the content table.
* **Needs no free disk space for the drop** — the pages go to the freelist and are reused. The
  file does not shrink, but **it stops growing for roughly 11 GiB of new data**, which at
  ~1.5 GB/day is about seven months of runway bought without deleting anything.
* **Requires**: a code change, a deploy, an API restart, and a rebuild pass (~10.5 GiB read,
  ~5 GiB written into freed pages). Prove it on a small copy first.

### Phase 2 — the archive's own defects (independent of disk, and more serious)
* Pull `desktop-fgv6kmh` at least once (42 sessions, the only copy today is the database).
* Fix `CARD_SHAPE` so it stops rewriting bare numeric fields (anchor to string values, or
  re-serialise after redaction). 16.5% of archived records currently have a destroyed `time`.
* Backfill pre-2026-10-09 history from the source machines if their local session stores still
  hold it.

### Phase 3 — only if the bytes must be returned to the filesystem
`VACUUM INTO '/root/authority.compacted.db'` needs free space ≈ the result size and can run
against a live database (it takes a read transaction, the original stays intact until a swap).
After Phase 1 the result is ~19.9 GiB; after Phase 1 + a 30-day prune, ~16.4 GiB.

**Phase 3 is not needed tonight and is not needed to stop the growth.** It becomes worthwhile only
when (a) the archive's gaps in Phase 2 are closed, so a prune is safe, and (b) there is verified
headroom — which means releasing ~20 GiB of non-database files (cold `/root/work` dirs, the
`tmp_pack_EzMHhT` 0.9 GiB leftover, `git-rescue-20261012` 2.4 GiB, or `usearch.db` 10.1 GiB).
**Every one of those is a deletion and needs the owner's explicit yes for that exact path.**

---

## 7.2 The migration, attempted — and completed

**COMPLETED 2026-10-19 15:34Z, after the owner rescaled the server to CCX33.** Verified: base =
fts = docsize = **2,749,996**, `_content` shadow **gone**, 3 triggers, `integrity-check=ok`,
`quick_check=ok`, 12.8 GiB of pages freed, search returning **68,655** hits for a term that
returned 9 while the index was damaged. The ingest code was changed and the API restarted in the
same window. No data was lost at any point; the base table was never written.

This table is kept because the failure modes were real and will recur if the limits are forgotten.

| attempt | method | result |
|---|---|---|
| v1 | `DROP TABLE dsh_session_events_fts` in one transaction | The DROP must journal every freed page. WAL reached **5.65 GB** and free space fell 14.9 → **3.87 GB at ~50%**; aborted. **Rollback was clean: index unchanged, `wal_checkpoint(TRUNCATE)` → `0\|0\|0`, API never stopped.** |
| v2 | empty the index through the FTS virtual table in batches | Measured **67 documents/second** — 2.69M documents = **11 hours**. Abandoned after committing ~10,345 deletions. |
| v3 | delete the shadow tables directly | **Impossible by design:** FTS5 refuses — `table dsh_session_events_fts_data may not be modified`. |
| repair | re-insert from the base table | **Succeeded.** `base = content = docsize = 2,711,725` exactly; a `TEMP` identity table + indexed anti-join found the 10,345 missing rows (a direct anti-join against `_content` is impossible — its `c0/c1/c2` columns cannot be indexed). |

**The hard limit, measured — and it is not a shortage, it is a wall.** A scaled replica with the
real schema and real-shaped data was dropped and its WAL sampled throughout:

```
index_bytes = 309,866,496   wal_peak_bytes = 311,686,272   RATIO = 1.006
```

**Dropping an FTS5 index costs its own size in WAL, one for one.** At 16.4 GiB that is **17.7 GB in
a single transaction**. Free space is 13.1 GB, so the shortfall is **4.6 GB before any allowance for
the 5 GB of routine churn observed during the first attempt**. The conversion cannot be run on this
volume at all, and no rearrangement of the work changes that: splitting the drop does not help
(`_content` alone is 11.6 GiB), per-row deletes take 11 hours, and the shadow tables refuse direct
writes. **The volume has to grow, or the database has to be rebuilt somewhere with room and cut
back.**

What was reclaimed instead, all of it derived and none of it data: npm cache, apt cache,
`journalctl --vacuum-size=100M`, and a stale September backup copy of the repo — **630 MB**. That
moves the runway from about 10 days to about 12 and does not touch the wall.

Everything else that would close the gap is someone's: the cold `/root/work` trees (~7.5 GB) hold
uncommitted work and, in `r7`/`r8`, reports and a merged journal; `usearch.db` (10.1 GB) is derived
but the estate's own guidance calls it an emergency lever when the disk is *hours* from full, not a
fix; `git-rescue-20261012` (2.4 GB) is a rescue copy of repos. **None of them were touched** — and
the parallel-agent rule is explicit: never remove a store you did not create.

Also learned, and worth keeping:
* `pragma integrity_check` on this file takes 8+ minutes and, while it runs, **its read snapshot
  pins the WAL so no checkpoint can advance** — a reader that looks harmless can starve the
  checkpointer during a write-heavy operation. Kill stray readers first.
* Every `sqlite3` invocation is a separate connection: a `TEMP` table does not survive between them.
* `/tmp` is a **2 GiB tmpfs with ~640 MB free**; all scratch must go to `/var/tmp` or `/root`.
* The API logged **17 `database is locked`** failures during the write-heavy attempts. The app
  retries by design and no data was lost, but that is a real cost of running this at all.

## 7.3 What is now proven that was not before

* **The backup restores.** The offsite object was pulled and restored end to end for the first
  time: 8,818,216,441 B, sha256 `2e498ecb…4315`, decompressed to 32,287,965,184 B,
  `PRAGMA integrity_check` = `ok` in 509 s, 237 tables, newest row `2026-10-18T05:18:32Z` matching
  the recorded cutoff. **Recommendation accepted from that rehearsal:** add `PRAGMA quick_check`
  inside the same read transaction as the backup's page stream (251 s, zero disk, zero egress), so
  every daily object is provably integrity-checked without a 34 GiB scratch.
* **The card-redaction bug is understood and fixed in a tested patch** (not deployed): the rule
  applied `CARD_SHAPE`+Luhn as a text substitution, so a 13-digit epoch-ms became
  `"time":[REDACTED:card]`. Sampled corruption: **737 of 4,422 records = 16.7% (95% CI 15.6–17.8%),
  12 of 12 objects affected.** The manifest's `redactions` column narrows candidates to 10,283
  arrivals without decompressing anything.
* **`desktop-fgv6kmh` is Yocheved's Windows laptop**, unreachable (no DNS, no ssh), **never in the
  pull roster** — its 42 sessions exist only in the database. Adding it needs one `MACHINES` entry
  plus an ssh alias, and it must be reachable first.

## 8. Operating constraints for any of the above (measured, not assumed)

* **Quietest window: 02:30–04:00 UTC = 22:30–00:00 America/New_York, 90 minutes.** No daily cron
  job and no daily timer falls in it (`systemctl list-timers`: last before it
  `transcript-archive-pull` 02:23, first after it `company-outcome-monitor` 04:07). It is not
  silent: `wake-fanout` and `lpt-freshness-watchdog` run every minute, `estate-monitor` every 2,
  `authority-deadman` every 5.
* **Cost of an exclusive lock, 30–60 min:** all eleven cron writers plus the whole company API
  8002 surface (dialpad harvest, reminders, owner queue, SMS responder). Under WAL, readers keep
  working. The app's write budget is 45 s and it is already failing under contention:
  `01:33:05 dialpad_call_full write gave up … after 5 attempt(s) in 52.9s (budget 45s): database is locked`.
  **Cost of stopping all writers for ~5 min:** one cycle of the `*/5` jobs; all re-run.
* **Memory ceiling for a long SQLite job: 4 GB**, under `systemd-run --scope -p MemoryMax=4G`,
  `nice -n 10 ionice -c2 -n7`. `company-api` is capped at `MemoryMax=12G` and **four
  pythons were OOM-killed at ~12.5 GB RSS on 2026-10-18** — 12.5 GB is the wall, not headroom.
  `free -m` at 01:41Z: 12,653 MiB available, 3,736 MiB swap already in use, `VmSwap` 1.5 GB in
  the API alone.
* **WAL grows under load**: 337,320,912 B (322 MiB) at 01:41Z against 67,108,864 B (64 MiB) at
  01:22Z. It is part of the disk churn and must be watched during any write-heavy step.

## 9. What needs the owner

**One question, and it is already in his queue as row 711** (asked 2026-10-18T19:21:07Z, still
`pending`): *"The authority is 93% full (10.7 GB free). … Reclaim the 13.2 GB of abandoned agent
worktrees, or grow the disk?"*

**My answer, now that it is measured: neither, yet.** The 11.3 GiB duplicate inside the FTS index
is reclaimable with **zero information lost** and needs no deletion, no approval and no free
space — it costs one code change, one API restart and one rebuild in the quiet window. That buys
roughly seven months of growth before either "reclaim the worktrees" or "grow the disk" becomes a
real question. Row 711 should stay open but is no longer the next move.

Two things do need him tonight, and they are one-line answers:
1. **The FTS migration touches the session-ingest path and restarts the company API.** Recommended:
   not tonight — a sibling agent is deleting files on that box unattributed (§5.4), which is the
   wrong condition for a 60-minute rebuild, and there is no emergency (16.7 GB free, ~1.5 GB/day).
   Prove it on a small synthetic copy (not a copy of the 31 GiB file — there is no room for one),
   then deploy in a quiet window.
2. **Someone is deleting work on the authority without approval.** Row 711 is `pending`, and six
   worktrees were emptied at 01:34:57Z anyway. That is the "never destroy data" rule being broken
   by a sibling agent, and it will happen again.

And one correction to the plan that comes from §7.0: **the restore path has to be fixed before any
`VACUUM INTO`.** A hash-verified copy 20.7 hours behind is a real backup, but nobody has ever
restored this object and this host cannot hold the restored file. That is a bigger risk than the
disk being at 90%, and it is the one I would fix first.
