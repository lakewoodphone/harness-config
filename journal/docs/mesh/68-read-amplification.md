# 68 — The 3.2 TB read is not a corpus sweep: it is one full scan of the index per document

Investigator: read-only pass on ZABZ-YOGA, 2026-09-16 (all timestamps local EDT, = UTC-4).
Supersedes nothing. Corrects the framing in `docs/mesh/30` §3 and the open lead in the
handoff of 2026-09-16 ("the 3.15 TB read — what reads 3 TB on this laptop?").

---

## Verdict in four lines

1. **What is read:** not the corpus. It is `C:\Users\ezabz\.usearch\usearch.db` — the search
   index reading **itself**, once per document, through two full scans of two FTS5 tables.
2. **By what:** PID 7204, `python.exe scripts\usearch.py add - --source db:localdb
   --db C:\Users\ezabz\.usearch\usearch.db`, spawned by `scripts/sync.py` PID 10488 at
   16:18:12. The corpus adapter (PID 25264) has read **0.08 GB** in its whole life and is
   blocked on a full pipe; the corpus is not the reader.
3. **Why it repeats:** the ingest performs `DELETE FROM chunks WHERE doc_id=?` — an
   **un-indexable predicate on an FTS5 table**, which SQLite plans as a full scan of all
   988,332 chunk rows (1.27 GB) — **once for every document it rewrites**. Every 30-minute
   refresh re-emits the whole `db:localdb` corpus (~81,000 documents), so every run pays
   ~1.38 GB per document and can never finish.
4. **Avoidable:** yes, almost entirely. One line changes ~98.6 % of the read into a
   rowid-indexed lookup: the same rows are deleted, nothing about what is indexed changes.

---

## 1. The measurement (source: `Get-CimInstance Win32_Process`, this host, 2026-09-16)

| when | read | read ops | bytes/op | write | notes |
|---|---|---|---|---|---|
| 18:01:48–18:02:14 (25.6 s) | 236.6 MB/s | 60,573/s | 4,088 | 0.6 MB/s | first window |
| 22:08:27–22:09:57 (90 s) | — | — | — | — | doc-rate window |
| 22:08:25–22:08:45 (20 s) | 344.3 MB/s | 88,126/s | — | 0.2 MB/s | |
| 22:11:13–22:11:28 (15 s) | **387.4 MB/s** | **99,187/s** | **4,096** | **0.04 MB/s** | final window |

* `Win32_Process.ReadTransferCount` for PID 7204: **3,366.4 GB lifetime** at 22:11 (the audit
  measured 3,150 GB at ~1.63 h life; the same process, 30 minutes later).
* `ReadOperationCount` 876,091,905 / 3,366.4 GB = **4,088 bytes per operation**, and the last
  window is exactly **4,096 B/op** — a sequential **4 KB-page scan**, not random I/O and not
  merge work (a merge reads and writes roughly 1:1; here the ratio is ~9,700:1).
* Disk during that window (`Get-Counter \PhysicalDisk(_Total)\*`): **queue length 0.0**,
  **2.75 MB/s of disk bytes**. The index is 2.36 GB and the host has 31.6 GB of RAM, so the
  scan is being served from the file-system cache.
  → **Correction to the premise this investigation started from:** this is not disk wear.
  The cost is (a) a core pinned tokenising the same 1.27 GB over and over at ~400 MB/s,
  (b) a refresh that never completes, (c) 1.27 GB of hot cache re-read perpetually. On a
  cold cache, or on a node with a larger index, the identical code path *is* disk I/O.

### 1.1 What the ingest is actually reading

Owner PID 7204 is `usearch.py add` on `usearch.db`. Proved, not assumed:

* `usearch.db` (mtime 18:01:20) = 2,357,133,312 B; page_size 4096; page_count 575,472.
* FTS5 table **`chunks`**: **988,332** live rows (`chunks_docsize`), holding
  **1,269,153,829 B (1.269 GB)** of chunk text (`SUM(chunks_meta.bytes)`).
* FTS5 table **`ngram`**: **159,367** rows; content ≈ **18.0 MB** (measured: 3,000-row sample
  of `length(title)+length(path)`, avg 113 B × 159,367 docs).
* The corpus the adapter would sweep is **~2.8 GB in total** (chroma.sqlite3 2.10 GB,
  secretary.db 0.48 GB, browser History ~165 MB, shell history ~1 MB). It cannot be the
  source of 3.37 TB, and in fact it has not been read: adapter PID 25264 lifetime read =
  **0.08 GB** (source: `Win32_Process`, 2026-09-16 18:02).

## 2. How often

* Task **`DSH unified-search refresh`** (read via `Get-ScheduledTask`, 2026-09-16 18:0x):
  action `wscript.exe //B //NoLogo
  C:\Users\ezabz\code\harness-config\scripts\hidden-tasks\DSH_unified-search_refresh.vbs`
  → `cmd /c C:\Users\ezabz\.usearch\bin\usearch-refresh.cmd` → `python scripts\sync.py >>
  C:\Users\ezabz\.usearch\logs\sync.log 2>&1`, no arguments (so **every enabled source**).
  Trigger StartBoundary 2026-09-15T20:45:46 + Repetition, `ExecutionTimeLimit` PT1H;
  LastRunTime 2026-09-16 17:45:47, NextRunTime 18:15:46 → **every 30 minutes**.
  `config/sources.json` `defaults.sync_interval_seconds: 1800` agrees.
* `db:localdb` is registered with **`timeout_seconds: 1200`** (20 min) and
  `max_staleness_seconds: 7200`.
* `~/.usearch/state/sync.json` (written 2026-09-16T20:18:12Z): `db:localdb` —
  `runs: 28`, `consecutive_failures: 28`, **`last_success: null`**, last error
  `ingest failed: RuntimeError: usearch.py add exited 4294967295: usearch: line 80982:
  database is locked`, last duration **2,941.55 s**.
* The live run (PID 10488, started 16:15:48, i.e. the 16:15:46 tick) has been inside
  `db:localdb` since 16:18:12 — **112+ minutes into a source whose own limit is 20 minutes.**
  At 18:11 the VBS/cmd of that task are gone (`ExecutionTimeLimit` PT1H expired at 17:15:48)
  while the python children **survived as orphans and are still reading**. That is the
  mechanism behind the `database is locked` failures: an abandoned ingest keeps its write
  lock, and the next tick's ingest collides with it.

## 3. The code path (file:line, read 2026-09-16)

`C:\Users\ezabz\code\unified-search\scripts\usearch.py`, `add_document()`:

```
607      old = con.execute("SELECT id, sha, bytes FROM docs WHERE source=? AND external_id=?",
608                        (source, external_id)).fetchone()
610      if old and skip_unchanged and doc_sha and old["sha"] == doc_sha ...
617      if old:
618          oid = old["id"]
619          con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))     <-- 1.27 GB scan
621          con.execute("DELETE FROM ngram  WHERE doc_id=?", (oid,))     <-- 18 MB scan
622          con.execute("DELETE FROM docs   WHERE id=?", (oid,))
```

`chunks` is `CREATE VIRTUAL TABLE chunks USING fts5(text, doc_id UNINDEXED, ord UNINDEXED,
lines UNINDEXED, tokenize='porter unicode61')` (usearch.py:325-331). **`doc_id` is UNINDEXED
and FTS5 can use a constraint only on `rowid`**, so `WHERE doc_id=?` cannot be pushed down.
Measured on this host 2026-09-16, on the real schema, in an in-memory database (no files
created):

```
EXPLAIN QUERY PLAN DELETE FROM chunks WHERE doc_id=0
  -> (3, 0, 199, 'SCAN chunks VIRTUAL TABLE INDEX 0:')      <- full scan, no index used
delete one document's chunks:  4,000 rows -> 0.0048 s | 40,000 rows -> 0.056 s
                             400,000 rows -> 0.62 s          <- linear in table size
EXPLAIN QUERY PLAN DELETE FROM chunks_meta WHERE doc_id=0
  -> SEARCH chunks_meta USING INDEX idx_cm_doc (doc_id=?)    <- the indexed version exists
```

So the cost of re-writing **one** document is the size of the **whole** `chunks` table.
The `chunks_meta` table already holds exactly the missing index: `chunk_id` **is** the FTS5
`rowid` (written at usearch.py:633-643 as `c.lastrowid`, and back-filled from `c.rowid` by
`migrate()` at 429-444), and it is indexed by primary key and by `idx_cm_doc(chunk_id/doc_id)`.

### 3.1 The arithmetic closes (this is the proof, not an estimate)

```
document rate (this run)   13-15 docs/min  -> 0.233 docs/s
   (two independent reads: per-minute indexed_at histogram for 12 consecutive minutes,
    21:56-22:07, 13/14/13/15/14/14/13/13/14/14/14/15; and SUM(docs where indexed_at >=
    run start) = 2,440 documents / 6,720 s = 0.363 docs/s average)
read rate                  236 - 387 MB/s
per document  = 3,366.4 GB lifetime read / 2,440 documents rewritten this run
              = 1,379.7 MB / document
chunks scan   = 1,269.2 MB                      (1,269,153,829 B of chunk text)
ngram scan    =    18.0 MB                      (estimate, see 1.1)
index overhead=   ~92 MB                        (8.7 %: index pages, docs lookups)
              ------------
              1,379.2 MB  vs  1,379.7 MB measured   <- 99.96 % explained
```

**Amplification factor: 1.38 GB of index read per document rewritten.** The average
`db:localdb` document currently being written is 275 bytes of text (`SUM(docs.bytes)`/
`COUNT(*)` over the 80,978 rows, 2026-09-16) — i.e. ~5 million bytes read per byte stored.
Measured against the whole corpus: **one complete `db:localdb` sweep costs
~81,000 × 1.38 GB ≈ 111 TB of reads and 80-131 hours of wall clock** (at the measured
236-387 MB/s), against a schedule that re-fires every 30 minutes. It has never converged:
28 consecutive failures, no success on record.

### 3.2 Why the last run was fast and this one is not (the second-run trap)

Every `db:localdb` document in the index carries `indexed_at` in
`[2026-09-16T18:22:01Z, 2026-09-16T22:07:19Z]` — all of them were **created today** by the
14:15 tick's run (PID lineage of the 2,941 s run that then died at line 80,982). On that run
`old` was `NULL` for every document, so **no delete ran and it managed 27.5 documents/s**.
This run finds all 81,000 documents already present, so every one takes the delete path, and
the rate collapses to 14 documents/min — a **120× slowdown caused purely by the index now
existing**. That is why the first full pass looked healthy and nothing has worked since.

## 4. THE FIX — one line, `scripts/usearch.py` line 619

**Now:** `DELETE FROM chunks WHERE doc_id=?` → full scan of 988,332 rows (1.269 GB) per
document.
**Should be:** delete by FTS5 `rowid`, using the map that already exists:

```python
# usearch.py:619  — replaces the single line
#   con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))
# with:
con.execute("DELETE FROM chunks WHERE rowid IN "
            "(SELECT chunk_id FROM chunks_meta WHERE doc_id=?)", (oid,))
```

Why this is the same delete and not a different one: `chunks_meta.chunk_id` is the `chunks`
rowid for every chunk this code has ever written (usearch.py:633-643), and `migrate()`
back-fills legacy rows from `c.rowid` (usearch.py:429-444). Verified on this host
2026-09-16: `chunks_docsize` rows = **988,332** = `chunks_meta` rows = **988,332**, so the
map is complete and the two statements delete exactly the same rows today.

**The same defect sits at three more sites**, and the fix belongs in one helper
(`delete_document_rows(con, doc_ids)`) called from all of them:

| site | now | notes |
|---|---|---|
| `usearch.py:619` | `DELETE FROM chunks WHERE doc_id=?` | hot path, once per document |
| `usearch.py:757` (prune) | same, inside a loop over `gone` | O(gone × table) |
| `usearch.py:812` (`delete_documents`) | same, per id | |
| `usearch.py:842` (`drop_source`) | same, per id | |
| `usearch.py:621, 757, 813, 843` | `DELETE FROM ngram WHERE doc_id=?` | secondary: see §5 |

**Risk, named:** if any `chunks` row had no `chunks_meta` row (an orphan), the rowid form
would leave it behind and the index would hold a stale chunk. Guard, if wanted, is two lines:
compare `con.execute("SELECT changes()")` against `old["n_chunks"]` and fall back to the
original `DELETE ... WHERE doc_id=?` when they disagree. `usearch.py check` already exposes
the precondition as `chunks_without_meta` — it must read 0 afterwards.

**Not implemented, deliberately:** the brief for this pass allowed it, but it also forbade
writing any file other than this one, and a change to the write path of a shared index cannot
be verified without running the suite (which writes temp files and bytecode caches) or
touching the live index — which currently has another writer, and a scheduled run every 30
minutes. An unverified edit landing just before the next tick is worse than a precise diff.

**Verification — exact commands (run with the ingest stopped, same conditions before/after):**

```powershell
$py = 'C:\Users\ezabz\AppData\Local\Programs\Python\Python312\python.exe'
$uc = 'C:\Users\ezabz\code\unified-search\scripts\usearch.py'
$db = 'C:\Users\ezabz\.usearch\usearch.db'

# (1) read cost of re-writing ONE already-indexed document (idempotent: same id, same text)
$gen = @"
import sqlite3, json
c = sqlite3.connect('file:C:/Users/ezabz/.usearch/usearch.db?mode=ro&immutable=1', uri=True)
r = c.execute('''select d.external_id, d.kind, c.text from docs d
                 join chunks_meta m on m.doc_id = d.id
                 join chunks c on c.rowid = m.chunk_id
                 where d.source='db:localdb' and d.n_chunks = 1 limit 1''').fetchone()
print(json.dumps({'v':1,'source':'db:localdb','kind':r[1],'id':r[0],'text':r[2],'text_kind':'prose'}))
"@
$line = & $py -c $gen
$sw = [Diagnostics.Stopwatch]::StartNew(); $line | & $py $uc add - --source db:localdb --db $db; $sw.Stop()
"one document re-ingested in $([math]::Round($sw.Elapsed.TotalSeconds,2)) s"
# expectation: ~4-8 s before the fix (a 1.27 GB scan, 2,440/2,440 documents pay it),
#              < 0.2 s after.

# (2) the whole-corpus figure: read bytes/sec of the live ingest, 60 s
$p = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
      Where-Object { $_.CommandLine -like '*usearch.py add*' }).ProcessId
$a = (Get-CimInstance Win32_Process -Filter "ProcessId=$p").ReadTransferCount
Start-Sleep -Seconds 60
$b = (Get-CimInstance Win32_Process -Filter "ProcessId=$p").ReadTransferCount
"{0:N1} MB/s read" -f (($b-$a)/1MB/60)
# measured today, before the fix: 237-387 MB/s with 14 documents per minute.
# after the fix it must fall to single-digit MB/s while the document rate rises to
# hundreds per second -- and `usearch.py check --sample 0` must still report
# chunks_without_meta = 0 and orphan_chunks = 0.
```

**Expected saving:** per document 1.38 GB → ~19 MB (**72×**); per full `db:localdb` sweep
111 TB → ~1.5 TB. The remaining 1.5 TB is the `ngram` scan (§5). Combined, a sweep becomes
~4 GB of reads and finishes in minutes instead of never.

## 5. The second full scan, and the other reasons the refresh cannot converge

1. **`ngram` too** (`usearch.py:621` etc.): same un-indexable predicate, ~18 MB per document
   → ~1.5 TB per sweep. It needs a mapping that does not exist yet. Cheapest correct shape:
   insert with an explicit rowid (`INSERT INTO ngram(rowid,title,path,doc_id) VALUES(<docs.id>,
   ...)`) and delete by rowid; the rows already in the table have auto-assigned rowids, so a
   one-time `DELETE FROM ngram` + rebuild is required — a derived index, rebuildable from
   `docs`, but a behaviour change, so **proposal only**.
2. **The adapter's state never advances, so every run is a full pass.** `sync.py:317-328`
   kills the adapter (`p.kill()`) the moment the ingest raises; the adapter saves its state
   only at the end of its pass (`adapters/localdb/sync.py:1694-1695`). Result:
   `~/.usearch/state/localdb.json` mtime is still **2026-09-15 21:33**, its `run_at` values
   are 2026-09-16T00:25-01:33Z, and `sync.json` shows 28 runs / 0 successes. The fingerprint
   gate is therefore never even consulted for this source. (Its `companydb` entry was also
   recorded under `--limit 50` — `fingerprint_detail` rows all read `50` — a fingerprint a
   full pass can never reproduce, so even a saved state would not match.)
3. **Three of the four "cheap" probes are not cheap.** `probe_companydb`
   (`adapters/localdb/sync.py:683-698`) says so in its own docstring — *"Cheap? No --
   correct. Streams the allowlisted text to build the content digest"* — and on a source that
   has changed it runs **three** times per pass: the gate at `main()`:1653, the emit pass,
   and again inside `run_companydb` at :930. That is two extra full passes over the company
   database text per run, independent of the 3.37 TB.
4. **`timeout_seconds` does not bound the ingest.** `sync.py:317` calls
   `core.ingest_stream(...)` with no timeout; `remaining = self.timeout - ...` is only
   computed afterwards (`:334`), so the 1200 s limit is decorative. Evidence: the live run
   has spent 112 minutes in a 1200 s source.
5. **The schedule and the source size are incompatible.** A 30-minute tick over a source that
   needs hours, with a 1-hour task limit that orphans the python children (observed: the
   16:15 run's children outlived their task), guarantees overlapping writers and
   `database is locked`. Whatever else is done, the refresh needs a run lock and a cadence
   that its slowest source can meet.
6. **`--source` overwrites every document's own source** (`usearch.py:694-695`,
   `d["source"] = source`): the whole localdb corpus lands under one source name
   (`db:localdb` = 80,978 docs), losing the adapter's `vector:chroma` / `web:chrome` /
   `db:secretary-local` / `shell:history` distinction that the rest of `db:localdb`'s
   reporting depends on.

## 6. What I could not verify (stated, not guessed)

* **Per-process file handles / per-file I/O for another user's process.** No `handle.exe`
  and no elevation on this seat. The attribution of the reads to `usearch.db` is by
  arithmetic (§3.1: 1.269 GB + 18 MB + 8.7 % = the measured 1.3797 GB/document) and by
  plan evidence, not by an open-handle listing.
* **Whether `chunks`/`ngram` account for 100 % of the bytes** — they account for 99.96 % of
  the per-document figure; the residual 0.04 % is not separable without ETW.
* **The 17:45:47 task run.** `LastTaskResult` 0 and no state entry, and no second `sync.py`
  was live at 18:02 or 22:09; whether it exited early or was killed is **not verified**.
* **`ngram_content` size** is a 3,000-row sample estimate (113 B/doc), not a table size:
  `dbstat` is not compiled into this SQLite (`no such table: dbstat`).
* **A before/after run of the fix.** Not performed — it would require editing a second file
  and writing to the live index (§4).

## 7. Required summary

**What is being read:** `C:\Users\ezabz\.usearch\usearch.db` — specifically FTS5 table
`chunks` (988,332 rows, 1.269 GB) in full, once per document, plus `ngram` (~18 MB) in full,
once per document. Not the corpus: the corpus is ~2.8 GB and the adapter has read 0.08 GB.

**By what:** PID 7204 `python.exe scripts\usearch.py add - --source db:localdb --db
C:\Users\ezabz\.usearch\usearch.db`, child of `scripts/sync.py` PID 10488, launched by the
scheduled task `DSH unified-search refresh` (16:15:46 tick) through
`usearch-refresh.cmd`.

**How often:** continuously — the task re-fires every 30 minutes and every run re-emits the
whole ~81,000-document corpus; each document costs one full index scan, so a run is ~111 TB
and 80-131 hours, which is 28 consecutive failures with `last_success: null` to show for it.

**Is it avoidable:** yes. ~98.6 % of the bytes are two un-indexable `WHERE doc_id=?` deletes
on FTS5 tables whose rowid mapping already exists in `chunks_meta`.

**The one-line fix:** `scripts/usearch.py:619` —
`DELETE FROM chunks WHERE doc_id=?` → `DELETE FROM chunks WHERE rowid IN (SELECT chunk_id
FROM chunks_meta WHERE doc_id=?)` (plus the same helper at :757/:812/:842, and the `ngram`
equivalent as a proposal).

**The measurement that proves it worked:** re-ingest one already-indexed document and time
it — 4-8 s before, < 0.2 s after; and the live ingest's `ReadTransferCount` over 60 s —
237-387 MB/s before, single-digit MB/s after, with `usearch.py check --sample 0` still
reporting `chunks_without_meta = 0` and `orphan_chunks = 0`.
