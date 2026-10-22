> ## ⚠ SUPERSEDED — DO NOT EXECUTE §4–§6
>
> **Read `2026-10-19-authority-disk-96pct-AUDIT.md` before acting on anything below.**
> An audit at 01:20–02:00Z on 2026-10-19 re-measured every number here. Findings:
> **the 90-day prune in §6 Step 4 deletes 0 rows** (the corpus is 38 days old, oldest row
> `2026-09-11T19:19:34`), so every reclaim figure downstream of it is void; pruning at any
> window that *would* delete rows is unsafe because the packed archive holds **nothing before
> 2026-10-09** and has never pulled the machine `desktop-fgv6kmh` (42 sessions, database only);
> and §5's "~9 GiB at peak" is wrong — the real requirement is 16–20 GiB. The lossless lever is
> not retention but the 11.3 GiB duplicate copy of the same text inside `dsh_session_events_fts`.
> §1's percentages were also stale within the hour: free space moved 6.44 GiB → 1.41 GiB →
> 16.9 GiB inside twenty minutes. The audit document is the current record.

# The authority is at 96% full — measured state, plan, and what needs the owner

**Written:** 2026-10-19 01:40Z, session `76d2fc46` on ZABZ-YOGA (owner's laptop), during a queue session
that found this as queue row **#711** and stopped the queue work for it.
**Host:** `secratary-cloud` — THE AUTHORITY, the sole writer of `/root/authority.db`.
**Status: NOTHING HAS BEEN DELETED.** The owner asked for this document so another agent can execute
it. **Every deletion in §6 needs his explicit per-action yes first** (`AGENTS.md` §4, `never destroy
data`). Read §7 before you type anything.

---

## 1. Measured state

Everything in this table was read on `secratary-cloud` in the session above, with the command shown.

| what | number | command that produced it |
|---|---|---|
| root filesystem | **150 G total, 138 G used, 6.6 G free, 96% used** | `df -h /` (01:12Z) |
| the same filesystem when queue row #711 was filed, ~5.9 h earlier | 93% used, 10.7 G free | `owner-queue.py queue` row title |
| ⇒ consumed in roughly six hours | **4.1 G** | the two lines above |
| `/root/authority.db` | **31.2 GiB** | `ls -la /root/authority.db` → 33,507,471,360 B |
| pages / freelist | 4,096 B pages × 8,180,535 pages; freelist **1,732 pages = 0.01 GiB** | `pragma page_size; pragma page_count; pragma freelist_count;` |
| ⇒ live data inside the file | **31.20 GiB — the file is not bloated** | arithmetic from the line above |
| `-wal` / `-shm` | 64 MiB / 224 KiB | `ls -la /root/authority.db*` |
| biggest table by row count | `dsh_session_events` = **2,692,243** rows | `select max(rowid) from dsh_session_events;` |
| next largest tables | `dialpad_sms_cache` 1,125,907 · `activity_log` 333,147 · `tick_telemetry` 34,767 · `memories` 27,208 · `dialpad_call_full` 14,894 · `dsh_sessions` 8,690 | same query per table |
| `dsh_session_events` size | **11,718.3 MB (11.4 GiB)** | `dbstat` grouped by name (§4) |
| its full-text index | `dsh_session_events_fts_content` **11,583.2 MB** + `dsh_session_events_fts_data` **5,182.0 MB** = **16.4 GiB** | same |
| ⇒ session events **plus** their search index | **27.8 GiB of 31.2 GiB — 89% of the database** | arithmetic |
| next largest, for scale | `procedural_experiences` 579.5 MB · `dialpad_stats_record` 371.2 MB · `memory_vectors_vector_chunks00` 318.4 MB · `work_sessions` 156.7 MB · `job_queue` 104.3 MB · `kg_nodes` 82.7 MB | same |
| disk consumers elsewhere | `/root/work` 14 G · `/root/.usearch/usearch.db` **10.1 G** · `/root/repos` 7.1 G · `/root/mail-archive` 2.6 G · `/root/git-rescue-20261012` 2.4 G · `/root/_hk569_wt` 2.1 G | `du -xhd1 /root`, `find /root -size +2G` |
| cold agent work dirs (all newest file **2026-10-16 08:42**) | `r4-preserve` 1.9 G · `r4-loop` 1.3 G · `r4-integration` 1.3 G · `fd-relay` 291 M · `fd-egress` 102 M · `r4-loop-basecheck` 70 M · `evolve3-wedge` 81 M ⇒ **≈ 5.0 G** | `for d in /root/work/*/; do du -sh; find -printf %TY…; done` |
| `/opt` is **not** the problem | largest: `chromadb` 2.2 G, `mem0` 0.3 G, `briefings` 0.1 G | bounded `find -printf %s` per dir |
| archive staging is **not** the problem | `incoming/` = 187 files, 0.02 G | `find …/incoming -type f -printf %s` |

## 2. Why this matters more than any queue item

`/root/authority.db` is the company's authoritative database on the authority host — the single writer.
At 100% the failure is not graceful: SQLite writes fail, ingestion stops, the agents' tick loop starts
throwing, and the queue stops being fed. Two other things live on the same filesystem: the archived
transcripts (`/opt/company/archive/lpt-transcripts`, 51,669 objects) and the search index the whole
estate searches with. A full disk takes all three out at once.

## 3. What has been ruled out (so you do not re-investigate it)

* **The database is not bloated.** The freelist is 1,732 pages — 0.01 GiB. A `VACUUM` today would
  reclaim essentially nothing without a delete happening first.
* **The WAL is not the problem** (64 MiB).
* **`/opt` is not the problem** (largest dir 2.2 G) and the archive's staging area is 0.02 G.
* **The archive is current and populated**, so the same bytes do exist off the live table:
  `manifest.sqlite` 56 MB, mtime 00:59Z; `objects/` 256 shards; **51,669 manifest rows**; the
  00:23Z pull logged `"members": 0, "new_objects": 0, "note": "nothing new to send"`. Before you
  prune anything, re-run the archive's own check (§6 step 3) — a pull that succeeded yesterday does
  not by itself prove a given machine's history is in there.

## 4. What is big — measured with SQLite's own page accounting

The measurement ran as a background job on the authority (it scans the whole 31 GiB file; it took
roughly 25 minutes) and **it was run to completion before this document was handed over**:

```bash
ssh secratary-cloud 'sqlite3 /root/authority.db \
  "select name, round(sum(pgsize)/1048576.0,1) as mb
     from dbstat group by name order by sum(pgsize) desc limit 20;"'
```

Result, complete, in MB:

| object | MB | what it is |
|---|---|---|
| `dsh_session_events` | **11,718.3** | every event of every DSH session, from six machines, with its `raw` payload |
| `dsh_session_events_fts_content` | **11,583.2** | the full-text index — **a second copy of the same text** |
| `dsh_session_events_fts_data` | **5,182.0** | the FTS b-tree for that copy |
| `procedural_experiences` | 579.5 | |
| `dialpad_stats_record` | 371.2 | |
| `memory_vectors_vector_chunks00` | 318.4 | |
| `sqlite_autoindex_dsh_session_events_1` / `idx_dsh_session_events_seq` | 170.4 / 170.1 | |
| `gateway_trace_span` | 163.5 | |
| `work_sessions` | 156.7 | |
| `job_queue` | 104.3 | |
| `kg_nodes` | 82.7 | |

**The finding that decides the plan: the session-event corpus and its search index are 27.8 GiB of the
31.2 GiB file — 89%.** Nothing else in the database is large enough to matter. Two consequences worth
telling the owner:

1. Pruning old events shrinks **all three** of those objects together (deleting a row removes its FTS
   content), so the reclaim is proportionally larger than the row count alone suggests.
2. The estate pays **16.4 GiB to full-text-search its own session events** — a second copy of text it
   already stores. Beyond retention, the real architectural lever is whether that index needs to cover
   the whole corpus or only the recent window. That is a design decision, not a disk emergency;
   record it, do not bundle it into this job.

A cheaper measurement, if you only need the prune target, and the one to quote the owner from:

```bash
ssh secratary-cloud 'sqlite3 /root/authority.db \
  "select count(*) rows, round(sum(length(raw))/1073741824.0,2) gb
     from dsh_session_events where created_at < date(\"now\",\"-90 day\");"'
```

**Do not promise the owner a reclaimed figure before one of those two numbers is in hand.** §6's
31 G → ~9 G figure is arithmetic from the dbstat breakdown and must be replaced by the measured
`rows_to_go` / `gb` the moment you have it.

## 5. The ordering constraint that decides the whole plan

**Deleting rows from SQLite frees no disk space.** Freed pages go on the freelist and get reused by
new writes; the file only shrinks on `VACUUM`, and `VACUUM` builds a complete compacted copy before it
replaces the original, so it needs free space **roughly equal to the size of the compacted result**.
On a filesystem with 6.6 G free and a 31 G database, that is impossible.

Therefore: **free space elsewhere first, bring the database down second.** Any plan that starts with
the database will fail halfway through and leave a large temp file behind on a filesystem that has no
room for one.

The arithmetic after the dbstat breakdown (§4), for a 90-day retention: the compacted result is
roughly **9 GiB** (31.2 GiB today, of which the pre-90-day share of a 27.8 GiB corpus is what is
actually being removed), so the `VACUUM` needs about **9 GiB free at its peak**. Step 1 frees ~5 G and
takes free space to ~11.6 G — feasible, but with under 3 G of margin on a filesystem where a failed
vacuum is expensive. Two ways to buy margin, both non-destructive: move
`/root/.usearch/usearch.db` (10.1 G, derived, regrows) to another host for the duration, or run
`VACUUM INTO '/root/authority.compacted.db'` and swap it in with `mv` once it verifies — same peak
cost, but the original stays intact until the moment you swap.

## 6. The plan

Each step names its own verification and its own rollback. Stop at the first step that does not verify.

### Step 1 — free the cold work dirs (~5.0 G, non-destructive in effect but still a deletion)

These are agent iteration directories whose newest file is **2026-10-16 08:42** — three days cold, and
none of them is referenced by a running service (verify that yourself in step 1a).

```bash
# 1a. prove nothing is using them right now
ssh secratary-cloud 'lsof +D /root/work 2>/dev/null | head; ls -ld /root/work/*/ | head -20'
# 1b. archive them first if the owner prefers packing over deletion (R2 bucket already used for the
#     offsite database copy — confirm the bucket and a working token before you rely on it):
ssh secratary-cloud 'cd /root/work && tar --zstd -cf /root/work-r4-archive-20261019.tar.zst \
   r4-preserve r4-loop r4-integration r4-loop-basecheck fd-relay fd-egress evolve3-wedge \
   && ls -l /root/work-r4-archive-20261019.tar.zst'
# 1c. only with the owner's explicit yes, and only after 1b says the tar is complete and readable:
ssh secratary-cloud 'zstd -t /root/work-r4-archive-20261019.tar.zst && rm -rf \
   /root/work/r4-preserve /root/work/r4-loop /root/work/r4-integration \
   /root/work/r4-loop-basecheck /root/work/fd-relay /root/work/fd-egress /root/work/evolve3-wedge'
# 1d. verify
ssh secratary-cloud 'df -h / | tail -1; du -sh /root/work'
```

Expected: free space 6.6 G → **≈ 11.6 G**. Rollback: unpack the tar (`tar --zstd -xf … -C /root/work`).
**If the tar is larger than the free space, compress-then-delete in one pipeline per directory instead,
still verifying the archive before each `rm`.**

### Step 2 — attribute the 4.1 G that appeared in ~6 h

Do this **before** the vacuum, because a leak that outruns the reclaim makes the whole exercise a
week's work repeated forever.

```bash
# baseline now …
ssh secratary-cloud 'date -u; df -B1 / | tail -1; sqlite3 /root/authority.db
  "select \"pages\",(select * from pragma_page_count);
   select \"events\",(select max(rowid) from dsh_session_events);"'
# … wait 30+ minutes with normal load, then repeat identically and subtract.
# Who is writing:
ssh secratary-cloud 'lsof /root/authority.db 2>/dev/null | head -20; ls -l /root/authority.db-wal'
# A backfill shows up as one ingest run with a huge "new" count:
ssh secratary-cloud 'sqlite3 /root/authority.db "select source,ran_at,days,fetched,queued,dropped,new
   from owner_queue_ingest_run order by rowid desc limit 30;"'
```

Known candidate: the transcript/session push (`/root/authority.db` → `dsh_session_events`, hourly from
six machines) and any script that ran with a wide `--days` window. Unknown writers are a finding in
themselves; write down what you conclude, with the two timestamps that show it.

### Step 3 — prove the archive covers what you are about to prune

```bash
ssh secratary-cloud 'systemctl list-timers transcript-archive-pull.timer --no-pager | head -3;
  systemctl status transcript-archive-pull.service --no-pager | head -6;
  ls -l /opt/company/archive/lpt-transcripts/manifest.sqlite;
  TRANSCRIPT_ARCHIVE_ROOT=/opt/company/archive/lpt-transcripts \
  TRANSCRIPT_STATE_DIR=/var/lib/transcript-archive \
  python3 /opt/company/archive/tools/transcript-archive-server.py --check; echo "check rc=$?"'
```

`--check` exits **1 on GAP** (a machine's own newest source file is newer than anything archived from
it — real data loss risk) and **2 on SILENCE** (a machine that used to report has stopped; from the
authority a powered-off laptop is indistinguishable from a broken pull, so it is not health). **Do not
prune while `--check` reports GAP for any machine**, and say plainly which of the two you got.
See `AGENTS.md` §1 for the four traps in this area — including that the store's path is
`/opt/company/archive/lpt-transcripts` and that a `du` on this host reports `0` for it (measured
2026-10-19); use `find -printf %s` sums or the manifest, never `du`, to size it.

### Step 4 — prune session events older than the retention the owner chooses

Retention is **his** number, not yours. Whatever he picks (90 days is the working proposal):

```bash
# 4a. measure exactly what would go (this is the number to quote him, before deleting):
ssh secratary-cloud 'sqlite3 /root/authority.db
  "select count(*) rows_to_go, round(sum(length(raw))/1073741824.0,2) gb_raw
     from dsh_session_events where created_at < date(\"now\",\"-90 day\");
   select \"remaining\", count(*) from dsh_session_events where created_at >= date(\"now\",\"-90 day\");"'
# 4b. delete in bounded batches so a failure does not hold a long write lock:
ssh secratary-cloud 'for i in $(seq 1 40); do n=$(sqlite3 /root/authority.db
  "delete from dsh_session_events where rowid in
     (select rowid from dsh_session_events where created_at < date(\"now\",\"-90 day\") limit 50000);
   select changes();"); echo "batch $i deleted $n"; [ "$n" = "0" ] && break; sleep 1; done'
# 4c. verify: rows gone, file unchanged (this is the point — no space is freed yet)
ssh secratary-cloud 'sqlite3 /root/authority.db "select count(*) from dsh_session_events;
  pragma freelist_count;"; df -h / | tail -1'
```

### Step 5 — compact, now that there is room

```bash
ssh secratary-cloud 'sqlite3 /root/authority.db "pragma integrity_check;" | head -3'   # before
ssh secratary-cloud 'systemctl list-units --type=service --state=running | grep -Ei "secretary|wake|ingest|dsh-push" '
# VACUUM takes an exclusive lock: do it in a quiet window, and know |free| must exceed the result size.
ssh secratary-cloud 'time sqlite3 /root/authority.db "vacuum;" ; echo "vacuum rc=$?"'
ssh secratary-cloud 'ls -l /root/authority.db; df -h / | tail -1; sqlite3 /root/authority.db "pragma integrity_check;" | head -3'
```

Verification is three numbers: file size down, `pragma integrity_check` = `ok`, and `df` free space up by
roughly the file-size reduction. Rollback: there is none for a VACUUM — which is why step 4a is
measured first and why you take the offsite copy check in §3 seriously. **A backup of the database
exists offsite (Cloudflare R2, per `AGENTS.md` §0) — confirm its age before step 5, and do not run
step 5 if the newest copy is older than the data you would lose.**

### Step 6 — report

Give the owner: `df` before/after of every step, the measured `rows_to_go` and `gb_raw` from 4a, the
VACUUM result and `integrity_check`, and whatever you concluded about the 4.1 G. If any step's
verified number disagrees with this document, **the measurement wins and this document is wrong** —
say so in the report rather than silently following it.

## 7. Never do these

1. **Never `rm` anything in this plan without the owner's explicit yes for that exact command on that
   exact path.** He has been asked; as of 2026-10-19 01:40Z he has **not** answered — he asked for
   this document instead. A task-level "deal with it" is not approval of a specific deletion.
2. **Never `VACUUM` before free space exists** (§5). A half-finished vacuum on a full disk is worse
   than the disk being full.
3. **Never delete `/root/authority.db`, and never restore over it** — one writer, and it is the
   authority.
4. **Never touch `secratary` (the office box).** It is the FROZEN ROLLBACK ANCHOR: cron masked on
   purpose, nothing there may be started, stopped, unmasked, enabled or restarted. Read
   `settings/machines/host-posture.tsv` before touching any host's service state.
5. **Never prune a table whose bytes you have not proved are in the archive**, and never treat
   `--check` exit 2 (SILENCE) as permission — it is a refusal to answer.
6. **Never rewrite a running script in place** to fix any of this (`AGENTS.md` §8: copy, edit the copy,
   `mv` — bash reads scripts by byte offset and a truncate-and-write executes a mixture of old and
   new).
7. **Do not delete the search index to buy space** and call it fixed: `/root/.usearch/usearch.db` is a
   *derived* 10.1 G index that regrows on the next build. It is a legitimate emergency lever (§9) when
   the disk is hours from full, not a fix.

## 8. The decisions that are the owner's

1. **Retention for `dsh_session_events`** — how many days stay live in the authority database while the
   packed archive keeps everything forever. Proposal: **90 days**.
2. **The cold work dirs** — delete, or pack to R2 first and then delete.
3. **Whether the authority gets more disk instead**, which buys years and costs money. The estate's
   pattern so far is a 150 G volume; 31 G of it is one table.

## 9. If the disk fills completely before the plan runs

In order, cheapest and least destructive first: (a) `rm /root/work-r4-archive-*.tar.zst` if step 1b
ran, (b) move `/root/.usearch/usearch.db` (10.1 G) to another host or delete it — search degrades until
it rebuilds, nothing is lost, (c) `journalctl --vacuum-size=200M`, `docker system prune` if dockerd
runs here, (d) the oldest cold work dirs from step 1. Do **not** delete anything under
`/opt/company/archive/` — that is the only copy of the packed corpus.

## 10. Provenance

Session `76d2fc46-8783-4c38-ad09-7061e722690d` (ZABZ-YOGA, `preset=zabz`), 2026-10-19 01:00–02:00Z.
Queue row **#711** ("The authority is 93% full … the search index is 10.4 GB of that and growing") was
filed by an earlier session; every number in §1 was re-measured live rather than taken from that row,
because the row was already 4 G out of date. The same session closed 31 queue rows and recorded the
owner's two standing rules of that night in `journal/state/in-flight.md`.

**Correction inside this document's own history, kept deliberately.** The first draft of §1 and §4
carried an *estimate* — 3,557 B average `raw`, extrapolated to ≈ 9.6 GB — taken from a 100,000-row
sample, and said the remaining ~19 GB was unattributed. A `dbstat` pass completed minutes later and
disproved it: the table is 11,718.3 MB and its FTS index is another 16.4 GiB. §1 and §4 above now carry
the measured numbers. The estimate was wrong in both directions at once — it under-sized the events by
1.8 GB and missed a 16.4 GiB index entirely — which is the reason the measurement rule in this estate
says the number that decides the branch must be the measured one, and why this note stays.
