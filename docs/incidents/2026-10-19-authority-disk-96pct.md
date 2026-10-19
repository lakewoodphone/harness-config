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
| session-event payload size | **3,557 B average** `raw` per row, sampled from the newest 100,000 rows (339 MB) | `select avg(length(raw)) … where rowid > (select max(rowid)-100000 …)` |
| ⇒ extrapolated payload for all 2.69 M rows | **≈ 9.6 GB**, not the whole 31.2 GiB | arithmetic; **the rest is NOT yet attributed — see §4** |
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

## 4. What is still unmeasured — measure it before you prune

The newest-100k sample says session events are ≈ 9.6 GB of payload, and the file is 31.2 GiB, so
**about 19 GB is in tables that have not been sized yet.** The correct measurement is one pass of
SQLite's own page accounting:

```bash
ssh secratary-cloud 'sqlite3 /root/authority.db \
  "select name, round(sum(pgsize)/1048576.0,1) as mb
     from dbstat group by name order by sum(pgsize) desc limit 20;"'
```

That scans the whole file and takes **tens of minutes on 31 GiB** — run it in the background with
`nohup … &` and read the file later, do not run it while you are also vacuuming. A cheaper partial
answer, if you only need the prune target:

```bash
ssh secratary-cloud 'sqlite3 /root/authority.db \
  "select count(*) rows, round(sum(length(raw))/1073741824.0,2) gb
     from dsh_session_events where created_at < date(\"now\",\"-90 day\");"'
```

**Do not promise the owner a reclaimed figure before one of those two numbers is in hand.** The
31 G → ~11 G estimate in §6 is arithmetic on the sampled average and must be replaced by the measured
figure the moment you have it.

## 5. The ordering constraint that decides the whole plan

**Deleting rows from SQLite frees no disk space.** Freed pages go on the freelist and get reused by
new writes; the file only shrinks on `VACUUM`, and `VACUUM` builds a complete compacted copy before it
replaces the original, so it needs free space **roughly equal to the size of the compacted result**.
On a filesystem with 6.6 G free and a 31 G database, that is impossible.

Therefore: **free space elsewhere first, bring the database down second.** Any plan that starts with
the database will fail halfway through and leave a large temp file behind on a filesystem that has no
room for one.

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

Session `76d2fc46-8783-4c38-ad09-7061e722690d` (ZABZ-YOGA, `preset=zabz`), 2026-10-19 01:00–01:40Z.
Queue row **#711** ("The authority is 93% full … the search index is 10.4 GB of that and growing") was
filed by an earlier session; every number in §1 was re-measured live rather than taken from that row,
because the row was already 4 G out of date. The same session closed 31 queue rows and recorded the
owner's two standing rules of that night in `journal/state/in-flight.md`.
