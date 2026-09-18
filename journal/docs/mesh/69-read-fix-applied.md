# 69 — The read-amplification fix, applied and measured on a copy

Follows `docs/mesh/68-read-amplification.md` (the diagnosis). This file records the change, the
before/after numbers, the integrity results, and what could not be verified.

**Two parts.** §1–§8 are the `chunks` delete, applied 2026-09-16 18:26, committed as `ee2f829`
(unified-search) and `add478a` (harness-config) — the owner verified it live: the orphaned 16:15
tree was reaped, the 18:45:47 tick ran the fixed code, and the chunk scan was gone. **§9 is PART 2,
the `ngram` delete** — the scan that then became the whole of the remaining read, applied the same
evening and **not yet committed**. Part 2's scope and provenance are stated at §9.0.

Author: delegated agent. Host **ZABZ-YOGA**, 2026-09-16, all times local EDT (= UTC-4).
Repo: `C:\Users\ezabz\code\unified-search`. **Nothing was committed by this agent** (owner commits).
**No state-changing git command was run.** The live index was never written to, and no process was
restarted, killed or reconfigured.

*(Part 1 below: HEAD was dd66603 and the only change was `scripts/usearch.py`.)*

---

## 1. The change

`DELETE FROM chunks WHERE doc_id=?` → `DELETE FROM chunks WHERE rowid IN (SELECT chunk_id FROM
chunks_meta WHERE doc_id=?)`, applied at all four sites, wrapped in one guarded helper plus one
extra column in each lookup. Plan, before and after, measured on the copy (2026-09-16):

```
BEFORE  EXPLAIN QUERY PLAN DELETE FROM chunks WHERE doc_id=?
        -> (3, 0, 199, 'SCAN chunks VIRTUAL TABLE INDEX 0:')                  <- full scan, no index

AFTER   EXPLAIN QUERY PLAN DELETE FROM chunks WHERE rowid IN
                            (SELECT chunk_id FROM chunks_meta WHERE doc_id=?)
        -> (3, 0, 33, 'SCAN chunks VIRTUAL TABLE INDEX 0:=')                   <- rowid EQUALITY
        -> (10, 7, 52, 'SEARCH chunks_meta USING COVERING INDEX idx_cm_doc (doc_id=?)')
```

The helper, verbatim:

```python
def delete_chunks_for_doc(con: sqlite3.Connection, doc_id: int,
                          expected_chunks: int | None) -> int:
    """Delete one document's rows from the FTS5 `chunks` table, through the rowid map.
    ... (see the file for the full docstring: the why, the measurements, and the guard) """
    con.execute("DELETE FROM chunks WHERE rowid IN "
                "(SELECT chunk_id FROM chunks_meta WHERE doc_id=?)", (doc_id,))
    n = con.execute("SELECT changes()").fetchone()[0]
    if expected_chunks is None or n != expected_chunks:
        sys.stderr.write(
            f"usearch: doc {doc_id}: {n} chunk row(s) deleted through chunks_meta but n_chunks="
            f"{expected_chunks}; falling back to the full-scan delete so none is left behind\n")
        con.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        n = con.execute("SELECT changes()").fetchone()[0]
    return n
```

Call sites converted, and the `docs` lookup each one needed:

| site | function | lookup change | delete change |
|---|---|---|---|
| `usearch.py:658` | `add_document` (hot path) | `SELECT id, sha, bytes` → `+ , n_chunks` | `delete_chunks_for_doc(con, oid, old["n_chunks"])` |
| `usearch.py:797` | `ingest_jsonl` prune loop | `SELECT id, external_id` → `+ , n_chunks` | `delete_chunks_for_doc(con, r["id"], r["n_chunks"])` |
| `usearch.py:852` | `delete_documents` | `SELECT id` → `SELECT id, n_chunks` | `delete_chunks_for_doc(con, oid, r["n_chunks"])` |
| `usearch.py:882` | `drop_source` | `SELECT id` → `SELECT id, n_chunks` | `delete_chunks_for_doc(con, r["id"], r["n_chunks"])` |

At the prune site the list comprehension changed from `gone = [r["id"] for r in have ...]` to
`gone = [r for r in have ...]` so the count travels with the id; `len(gone)` and `if gone:` still
read correctly.

### 1.1 The exact diff, with attribution

`git diff -- scripts/usearch.py` (against HEAD `dd66603`, uncommitted):

```diff
@@ -570,7 +570,47 @@ def validate_doc(d: dict) -> str | None:
     return None
 
 
-def add_document(con: sqlite3.Connection, d: dict, in_transaction: bool = False) -> int:
+def delete_chunks_for_doc(con: sqlite3.Connection, doc_id: int,
+                          expected_chunks: int | None) -> int:
+    """Delete one document's rows from the FTS5 `chunks` table, through the rowid map.
+ ... (43 added lines: the new helper and its docstring) ...
+def add_document(con: sqlite3.Connection, d: dict, in_transaction: bool = False,
+                 skip_unchanged: bool = False) -> int:
@@ -598,11 +638,24 @@
-        old = con.execute("SELECT id FROM docs WHERE source=? AND external_id=?",
+        # Look before deleting. ... (comment, pre-existing) ...
+        old = con.execute("SELECT id, sha, bytes, n_chunks FROM docs WHERE source=? AND external_id=?",
                           (source, external_id)).fetchone()
+        doc_sha = d.get("sha") or ""
+        if old and skip_unchanged and doc_sha and old["sha"] == doc_sha \
+                and old["bytes"] == len(text):
+            ... (pre-existing early return) ...
         if old:
             oid = old["id"]
-            con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))
+            delete_chunks_for_doc(con, oid, old["n_chunks"])
             con.execute("DELETE FROM chunks_meta WHERE doc_id=?", (oid,))
@@ -738,13 +790,14 @@
-            have = con.execute("SELECT id, external_id FROM docs WHERE source=?", (src_name,))
-            gone = [r["id"] for r in have if r["external_id"] not in seen]
-            for oid in gone:
-                con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))
+            have = con.execute(
+                "SELECT id, external_id, n_chunks FROM docs WHERE source=?", (src_name,))
+            gone = [r for r in have if r["external_id"] not in seen]
+            for r in gone:
+                delete_chunks_for_doc(con, r["id"], r["n_chunks"])
@@ -792,11 +845,11 @@
-                f"SELECT id FROM docs WHERE source=? AND external_id IN ({marks})",
+                f"SELECT id, n_chunks FROM docs WHERE source=? AND external_id IN ({marks})",
             for r in rows:
                 oid = r["id"]
-                con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))
+                delete_chunks_for_doc(con, oid, r["n_chunks"])
@@ -824,9 +877,9 @@
 def drop_source(con: sqlite3.Connection, source: str) -> int:
-    rows = con.execute("SELECT id FROM docs WHERE source=?", (source,)).fetchall()
+    rows = con.execute("SELECT id, n_chunks FROM docs WHERE source=?", (source,)).fetchall()
     for r in rows:
-        con.execute("DELETE FROM chunks WHERE doc_id=?", (r["id"],))
+        delete_chunks_for_doc(con, r["id"], r["n_chunks"])
```

**Attribution, because it matters.** The file was **already modified** when I started: a previous
pass had added the `skip_unchanged` parameter, the "look before deleting" comment, the
`old["sha"]/old["bytes"]` early return, and had moved `doc_sha` above the `INSERT`. That work is
*not mine* — the exact text is in `git diff` above and is reproduced here so nobody credits it to
this change. My edit is: the new helper, the four conversions, and `n_chunks` added to the four
`docs` lookups. `add_document`'s signature change at the top of the second hunk is the previous
pass, not mine.

### 1.2 Why the guard is not decoration

`changes()` after the fast delete must equal the chunk count recorded on the document
(`docs.n_chunks`). Any disagreement means `chunks_meta` is not a faithful map of `chunks` — an
orphan in either direction — and the helper falls back to the un-indexable statement, which is
slow but complete. `expected_chunks=None` ("unknown") is treated as a disagreement too. A stale
chunk left in the index is a wrong search result; a slow delete is merely slow.

**Named hole, not fixed:** a document whose recorded `n_chunks` is **0** while orphan `chunks` rows
carry its `doc_id` is invisible to both the fast path and the guard (`changes()=0 == expected 0`).
It is not reachable from `add_document` (the `n_chunks` update and the chunk inserts are in the
same transaction) and is not present in the live index today (§5), but the guard does not cover it.

---

## 2. Method — why nothing below was measured on the live index

The live index has a writer (PID 7204) and a tick every 30 minutes, and the owner's search depends
on it, so all destructive measurement happened on a copy.

**Snapshot.** `%TEMP%\zabz-usearch-fixcopy\` — a raw copy of `usearch.db` + `usearch.db-wal`
(3.7 s at 18:23:50; `usearch.db-shm` was locked by the live writer and was left out, SQLite
recreates it). Copy: 2,357,526,528 B db + 29,853,552 B wal. **Deleted immediately after the last measurement on
it (before 18:32); absence confirmed at 18:34:02 (`Test-Path` false).**

*First attempt failed, and the failure is worth recording:* I tried sqlite3's backup API first, as
the "consistent snapshot" method. Against this live writer it **restarts in a loop** — after ~7
minutes it had read **111 GB** and written **56 GB** with a **0-byte** destination. It was killed
(only that process; PID 7204/10488/25264 were untouched). With an ingest committing every few
seconds, the backup API cannot snapshot this index.

**Snapshot validated, not assumed.** Counts on the copy equal the live read-only counts taken at
the same minute: `docs` 159,367 / `chunks_docsize` 988,332 / `chunks_meta` 988,332.
`PRAGMA quick_check(1)` = **ok** in 61.3 s, so no page is torn. Its page cache was then warm, which
is the same condition the live scan runs under (doc 68 §1: the live scan is served from cache —
disk was 2.75 MB/s while the process read at 237-387 MB/s).

**The document.** `docs.id` 71920 in the snapshot, `source` `db:localdb`, `external_id`
`db:secretary-local:memories:487`, kind `memory`, `n_chunks` 1, 1,192 characters. Its single chunk
text **is** the document text (`length(text)` 1192 == `docs.bytes` 1192, measured), so the JSONL
line fed back to the CLI is the true original document, 1,353 bytes.

---

## 3. Measured before/after, one already-indexed document

Both numbers by the same route: `python usearch.py add - --source db:localdb --db <copy>` fed the
same 1,353-byte line for the same document, on the same copy, cache warm, 2026-09-16 18:26–18:29.
"Before" is the file as I found it; "after" is the file as it is now.

| measurement | before | after |
|---|---|---|
| statement `DELETE ... chunks` for one document, in a transaction, rolled back | **1.391 s**, **3.528 s** (`changes()`=1) | **0.0004 s**, **0.0002 s** (`changes()`=1) |
| end-to-end `usearch.py add -` for that document | **1.56 s**, **1.57 s** | **0.34 s**, **0.34 s** |

Context for the end-to-end number, measured in the same session: `python -c pass` **0.082 s**; a
document that does **not** already exist, so no delete runs at all, **0.11 s**. So the post-fix
0.34 s is not delete-bound — it is interpreter start, opening a 2.36 GB database, the write path
and the checkpoint. **Doc 68's predicted "<0.2 s after" is not reproduced as a whole-process
number**; the statement that doc described is 0.0004 s. The honest summary is: the delete went from
~1.4 s to ~0.0004 s (**~3,500-7,000x**) and a whole CLI invocation went from ~1.57 s to 0.34 s
(**4.6x**), with the remainder being fixed process and write-path cost.

**Residual, deliberately not fixed in this change:** `DELETE FROM ngram WHERE doc_id=?` is the same
un-indexable shape and is still there. Measured on the same copy: **0.037 s / 0.040 s** per
document (`ngram` 159,368 rows). It is not the dominant term, and doc 68 §5 records that fixing it
needs a rowid mapping that does not exist yet plus a rebuild — a behaviour change, so it stays a
proposal.

---

## 4. The guard, exercised through the real code path

On the copy: take the JSONL line for a document **first**, then delete that document's
`chunks_meta` row so a `chunks` row is left with no metadata row (`chunks_without_meta`=1,
`docs.n_chunks`=1), then re-ingest it with the fixed code.

```
induced: chunks_meta rows now 0 | chunks rows 1 | docs.n_chunks 1
$ ... usearch.py add - --source db:localdb --db <copy>
  | usearch: doc 71921: 0 chunk row(s) deleted through chunks_meta but n_chunks=1; falling back
  |   to the full-scan delete so none is left behind
  | {"rows": 1, "written": 1, "errors": 0, "source": "db:localdb"}
doc 164233 {'n_chunks': 1, 'chunk_rows': 1, 'meta_rows': 1}
global chunks_without_meta: 0 | orphan_chunks: 0 | chunk_count_mismatch: 0
```

The fallback fires, and the index comes out consistent — nothing is left behind.

### 4.1 All four converted sites exercised (not just the hot one)

| site | how it was driven | result |
|---|---|---|
| `:658` `add_document` | the before/after runs and the guard test above | written=1, invariants clean |
| `:797` prune | `add --prune --verbose` over a stream that omitted one document of the source | `usearch: pruned 1 vanished documents from zz:libtest` |
| `:852` `delete_documents` | called in-process (`sys.dont_write_bytecode=True`, so no `.pyc` was written into the repo) | returned 1, document gone, invariants clean |
| `:882` `drop_source` | `usearch.py drop --source zz:libtest` | `dropped 1 document(s) from source zz:libtest` |

After all four: `chunks_without_meta` 0, `orphan_chunks` 0, `chunk_count_mismatch` 0, and for the
test source 0 docs and 0 chunk rows left behind. `ast.parse` on the edited file: OK.

---

## 5. Integrity results

### 5.1 The copy, after the new delete

`python usearch.py check --sample 0 --db <copy>` — run twice: once right after the new delete ran,
and again after all four paths had been exercised. Both:

```
OK   C:\Users\ezabz\AppData\Local\Temp\zabz-usearch-fixcopy\usearch.db
  fts_integrity_rank           True
  orphan_chunks                0
  orphan_chunks_meta           0
  chunk_count_mismatch         0
  chunks_without_meta          0
  documents_hash_verified      0
  documents_hash_mismatched    0
exit code: 0
```

### 5.2 Is the mapping really a bijection? (asked of the data, not assumed)

The safety of the change rests on `chunks_meta.chunk_id` being the `chunks` rowid for **every**
chunk. On the copy, in both directions (988,333 = my own two test documents on top of 988,332):

| query | result |
|---|---|
| `chunks_docsize` rows (= one per `chunks` row) | 988,333 |
| `chunks_meta` rows | 988,333 |
| `chunks` rows whose rowid has no `chunks_meta` row | **0** |
| `chunks_meta` rows whose `chunk_id` has no `chunks` row (the reverse direction) | **0** |
| rows where the `chunks_meta` row for a rowid disagrees about `doc_id` | **0** |

### 5.3 The live database, read-only — and why the full check was NOT run against it

Run read-only (`file:...?mode=ro`, no writes possible) at **2026-09-16 18:30:23**:

| query | result | time |
|---|---|---|
| `docs` | 159,367 | 0.3 s |
| `chunks_docsize` | 988,332 | 0.7 s |
| `chunks_meta` | 988,332 | 0.5 s |
| `orphan_chunks` | **0** | 9.8 s |
| `orphan_chunks_meta` | **0** | 0.5 s |
| `chunk_count_mismatch` | **0** | 0.8 s |
| `chunks_without_meta` | **0** | 16.8 s |

Those are the exact queries `integrity_check()` runs (`usearch.py:905-917`). Together with
`chunks_docsize` = `chunks_meta` = 988,332 and `chunk_id` being the PRIMARY KEY of `chunks_meta`,
`chunks_without_meta = 0` makes the map a **total injection from a 988,332-row set into a
988,332-row set, i.e. a bijection** — no meta row can be missing a chunk row either. So on the
live index today the two statements delete exactly the same rows, which is what §5.2 confirms
directly on the copy. **The precondition holds on the live index.**

**`usearch.py check` was deliberately NOT run against the live database.** The brief's parenthetical
("`check` does not write") is **wrong for its `fts_integrity_rank` probe**, and I measured that
rather than trusting either claim: on the copy, with one connection holding `BEGIN IMMEDIATE`, the
probe

```sql
INSERT INTO chunks(chunks, rank) VALUES('integrity-check', 1)
```

was **BLOCKED — `database is locked`** after its busy timeout. It needs the write lock, and the live
ingest holds that lock. Running it live would either stall 60 s and report an error, or take the
live write lock away from the running ingest — which the brief forbids. So:

* **not verified on the live index:** `fts_integrity_rank` (the FTS5 internal-index consistency
  probe). It is **True** on the snapshot (§5.1), which is the same database as of 18:23.
* everything else in the check was run against live read-only, in §5.3, with the same SQL.

---

## 6. What I could not verify

1. **`fts_integrity_rank` on the live index** — needs a write lock the live ingest holds (§5.3).
   Verified `True` on the snapshot instead.
2. **The live index running the fixed code.** The change is on disk since 18:26:08, and
   `sync.py:810-815` spawns `usearch.py add` as a **subprocess**, so a new process reads the new
   file — no restart is needed, which is confirmed from source. But the ingest running right now
   (PID 7204, started 16:18:12) loaded the old code and keeps it until it exits.
3. **Whether the next tick actually succeeds.** `NextRunTime` was **18:45:46** (`LastRunTime`
   18:15:47, `LastTaskResult` 0, read 18:33). PID 7204 is an **abandoned** child of the 16:15:46
   run that outlived its 1-hour task limit and still holds a write lock (doc 68 §2) — so the first
   post-fix tick can still fail with `database is locked` **even though the code it runs is fixed**.
   The fix does not free the current blocked run.
4. **Per-document read bytes of the live ingest after the fix.** Requires a post-fix run; the
   before value (doc 68: 1,379.7 MB/document, 237-387 MB/s) stands until then. My own 30 s window
   agrees with it: **360 MB/s**, 18:32:51 → 18:33:21, PID 7204.
5. **PID 7204's absolute `ReadTransferCount`** — my readings were **non-monotonic**
   (3,732 GB at 18:30:23 → 4,068 GB at ~18:31 → 3,793 GB at 18:32:51 on the same PID). I therefore
   use only *window* rates and report no absolute lifetime figure from my own samples; doc 68's
   3,366 GB at 22:11 UTC stands as its own measurement.
6. **The `n_chunks = 0` orphan case** in §1.2 — named, not reachable in the live index today, not
   fixed.

## 7. What this does and does not buy

* **Removed:** the full 1,269,153,829 B scan of `chunks` per re-indexed document — the whole of the
  1.38 GB/document read amplification that doc 68 §3.1 accounted for (1.269 GB chunks + 18 MB ngram
  + ~8.7 % overhead = the measured 1,379.7 MB). Measured here: 1.391 s → **0.0004 s** for that
  statement, on a warm cache, at the same index size.
* **Remains, and this fix does not touch it:** the `ngram` scan (~0.04 s/document, ~1.5 TB across a
  full `db:localdb` sweep — **PART 2, §9, removed this one too**; §9.7 lists what is still left), the
  adapter state that never advances so every run is a full pass
  (`sync.py:317-328` kills the adapter before it saves), `timeout_seconds` that does not bound the
  ingest, and a 30-minute tick over a source that needs longer (doc 68 §5). **The refresh is much
  cheaper per document but is not yet bounded**, and I would not claim it converges on the strength
  of this change alone.

## 8. Provenance

Every number above was produced in this session on this host on 2026-09-16 between 18:14 and
18:33 local, by the commands shown. Live-index facts come from a **read-only** connection
(`mode=ro`) and from `Get-CimInstance`/`Get-Item`/`Get-ScheduledTaskInfo`; live counts are stamped
**18:30:23**. Copy facts come from `%TEMP%\zabz-usearch-fixcopy\usearch.db`, snapshot taken
18:23:50, `quick_check` ok, deleted before 18:32 and confirmed absent at 18:34:02. The live
database's own size/mtime moved during the session (2,357,133,312 B at 18:15:28 → 2,357,526,528 B at 18:31:24) — that is the ingest's own
checkpointing; I opened it read-only only, and wrote nothing to it.

Not done, deliberately, because the brief scoped it: no `ngram` change; no restart, kill or
reconfigure; no scheduled-task change; no committing; no journal entry (exactly one new file was
allowed — `journal.py append handoff` for this belongs to the parent session).

---

# PART 2 — the `ngram` delete

## 9.0 What was asked, what was found, and the provenance

After Part 1 landed, the owner measured the live run again: **125.5 MB/s of reads from a
70-second-old process** (2,510 MB in 20 s) with the chunk delete gone. I reproduced that
independently before touching anything: PID **8940** (`usearch.py add - --source db:localdb`, started
18:46:20, running the Part 1 code) read at **124 MB/s over a 30.1 s window at 19:03–19:05**,
lifetime 132.4 GB. This needs to be said plainly, because it frames Part 2: *the running process
loaded its code before Part 2 existed, so nothing below is in effect for it — the first process that
can show the difference is the next `usearch.py add`, i.e. the 19:15:46 tick.*

**Establishing the shape first, as asked.** Answered from the data, not assumed, on a snapshot at
18:50:

1. **No companion mapping exists.** Every object whose name contains `ngram` is the FTS5 virtual
   table and its five shadows — `ngram`, `ngram_config`, `ngram_content`, `ngram_data`,
   `ngram_docsize`, `ngram_idx`. `chunks` has `chunks_meta`; `ngram` has nothing. Confirmed
   independently by the full table list.
2. **The plan is the defect.** `EXPLAIN QUERY PLAN DELETE FROM ngram WHERE doc_id=?` →
   `SCAN ngram VIRTUAL TABLE INDEX 0:`. `ngram.doc_id` is `UNINDEXED`, and FTS5 can only push down a
   constraint on `rowid`.
3. **Exactly one `ngram` row per document** — the invariant the guard rests on. Measured live:
   159,507 docs = 159,507 `ngram` rows = 159,507 `ngram_docsize` rows, **0** doc_ids with more than
   one, **0** `ngram` rows without a document. (At 19:03: 159,600 = 159,600.) Since the map is total
   (no orphans) and injective (no doc with two) between two equal-sized sets, it is a bijection.
4. **Rows are INSERTED in exactly one place**: `usearch.py` `add_document` — the only
   `INSERT INTO ngram` in the repo. So the insert path is fully visible and capturable, which is what
   makes the fix possible at all.
5. **But `ngram` rows are DELETED in three places, not one.** Two adapters issue the delete with
   their own SQL, reaching past the "adapters never write SQL" contract (the same exception
   `delete_documents` was built for):
   `adapters/files/sync.py:392-393` (`prune_docs`) and `adapters/journal/sync.py:526-527`
   (`prune_missing`). They cannot maintain a mapping they do not know about, so the map has to
   reconcile itself. **They also each carry the Part 1 `chunks` defect too** — `DELETE FROM chunks
   WHERE doc_id=?` at files:392 and journal:526 — which is the next un-indexed full scan of a 1.27 GB
   table per vanished document. See §9.7.
6. **Nothing enumerates tables and assumes a fixed set.** The three tests that enumerate
   `sqlite_master` (`tests/test_usearch_core.py:526`, `:554`, `:700`) use `assertIn` per name, not an
   exact set; no test asserts the exact set of `integrity_check` keys (checked by grep). Adding a
   table and three keys is safe.

**Scope and provenance.** File changed: `scripts/usearch.py` only, in the working tree, **uncommitted**
— `git diff --stat` is `1 file changed, 165 insertions(+), 9 deletions(-)`, HEAD still `ee2f829`.
The live index was never written to: every live reading below used a `mode=ro` URI connection, and
my only other live action was reading counters from `Get-CimInstance`. No process was restarted,
killed or reconfigured; **I never took the write lock** (so: I worked on a copy, and waited for
nothing). The copy is deleted and confirmed absent.

## 9.1 Getting a trustworthy copy (the Part 1 method did not survive contact)

Two new lessons about copying this index while its writer runs, both measured tonight:

* **The sqlite3 backup API cannot snapshot it** (Part 1, §2): against a live writer it restarts in a
  loop — 111 GB read and 56 GB written for a 0-byte destination. Killed.
* **A raw file copy is not reliably consistent either.** Copy #2 (18:49, `usearch.db` + `-wal`,
  7.7 s) **failed `PRAGMA quick_check`**: `Tree 8 page 22371 cell 73: Rowid 1168231115683 out of
  order`, in `chunks_data` (root page 8). That looked like corruption, so I tested the database
  itself rather than the copy: **the live index passes `quick_check(1)` = ok in 85.9 s (read-only)**.
  The copy was torn — by copying a WAL database while it checkpoints. A torn copy is worse than no
  copy, because it would have made every integrity number below a lie.
* **What works: `VACUUM INTO` over a read-only connection.** One stable read snapshot, no restart
  semantics, no writes to the source: 2.36 GB → **2,332,286,976 B in 23.3 s**, then
  `quick_check(1)` = **ok in 56.0 s**. Counts matched the live database taken at the same minute
  (159,514 docs / 988,506 / 988,506 / 159,514 / 159,514), and the five existing invariants were all
  **0** on the copy. VACUUM compacts, so the copy's page layout differs from the live file — noted
  where it could matter, and immaterial for a statement whose cost is a full scan of one table.

## 9.2 The change

The mapping the diagnosis said would have to be created, created — plus the guard, plus one thing
the brief did not ask for and the live index needs (§9.5):

```sql
CREATE TABLE IF NOT EXISTS ngram_meta (
    ngram_id INTEGER PRIMARY KEY,        -- the FTS5 `ngram` rowid, the only key FTS5 deletes by
    doc_id   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nm_doc ON ngram_meta(doc_id);
```

* `add_document` captures the rowid FTS5 assigned (`ng.lastrowid`) and writes the map row **in the
  same transaction as the ngram row**, so a crash cannot produce an unmapped row.
* The delete becomes
  `DELETE FROM ngram WHERE rowid IN (SELECT ngram_id FROM ngram_meta WHERE doc_id=?)` at all four
  sites (`add_document`, prune, `delete_documents`, `drop_source`), each followed by
  `DELETE FROM ngram_meta WHERE doc_id=?`.
* **The guard, as specified**: `expected = COUNT(*) FROM ngram_meta WHERE doc_id=?`, then
  `SELECT changes()` after the fast delete; any disagreement — or `expected < 1` — prints a stderr
  line and re-runs the original `DELETE FROM ngram WHERE doc_id=?`. A stale ngram row is a wrong
  search result; a slow delete is only slow.
* `SCHEMA_VERSION` 1 → 2, and `migrate()` reports `ngram_backfilled` / `ngram_stale_removed`
  (kept separate from the existing `backfilled`, which means chunks — the migration tests assert on
  that one).
* `integrity_check` gains `ngram_without_meta`, `ngram_meta_without_ngram`, `orphan_ngram`.

**Deviation from the brief's sketch, stated:** I named the column `ngram_id` rather than `rowid`
(a literal `rowid` column shadows SQLite's own, and `chunks_meta` sets the house style with
`chunk_id`) and typed `doc_id INTEGER` rather than `TEXT` because `ngram.doc_id` holds `docs.id`.
Functionally identical to what was asked.

**Alternatives considered and rejected** (recorded so this is not re-litigated):
* *Insert with an explicit rowid equal to `docs.id`* — then no map is needed at all
  (`DELETE FROM ngram WHERE rowid=?`). Rejected because the 159,600 rows already in the table have
  auto-assigned rowids, so it requires a **destructive one-time `DELETE FROM ngram` + rebuild of a
  live derived index**, during which the trigram rung returns nothing. The additive table needs no
  deletion of index rows and no downtime.
* *Store the ngram rowid on the `docs` row (`ALTER TABLE docs ADD COLUMN ngram_id`)* — one row per
  document makes the doc row a natural home, and it dies with the doc row. Rejected as more invasive
  to the most-read table for no functional gain, and it needs `UPDATE ... FROM` for the back-fill.

## 9.3 Measured, before and after — per-document READ BYTES, the diagnosis's own method

The single-document CLI timing is **not** sensitive enough here (`usearch.py add` costs 0.12–0.16 s
of fixed process and write-path time, against a 0.09 s scan), so I measured what doc 68 measured:
the read bytes of the ingest process. One long-lived `usearch.py add` fed 200 already-indexed
`db:localdb` documents over stdin, its `ReadTransferCount` sampled through
`GetProcessIoCounters` (same units and method as doc 68 §1), with a zero-document run as the floor.

| measurement (clean copy, warm cache, **the same 200 documents**) | BEFORE | AFTER |
|---|---|---|
| floor, 0 documents | 1.0 MB read, 0.07 s | 32.7 MB read, 0.02 MB written, 0.29 s (map complete) |
| same floor, map **missing** (the one-time adoption) | — | 33.0 MB read, **8.11 MB written, 0.32 s** |
| 200 documents: **read** | **2,877.4 MB** | **41.6 MB** / **53.1 MB** |
| 200 documents: read operations | 702,349 | 10,028 / 12,816 |
| 200 documents: bytes per read op | **4,097** (a 4 KB page scan) | 4,150 / 4,138 |
| 200 documents: wall clock | **14.03 s** | **0.70 s / 0.74 s** |
| **net read per document** | **14.39 MB** (3,512 read ops) | **44.6 KB / 101.7 KB** |

**Net reduction: 140×–320× per document**, and 20× on wall clock for the same 200 documents. The
residual 45–102 KB/document is the *write path's own page reads* — the indexed `docs`,
`chunks_meta`, `ngram_meta` and FTS5 inserts each have to read the pages they modify. There is no
longer any scan; 100 KB per document is what indexing a document costs.

Statement level, same document, in a transaction and rolled back:

| | BEFORE | AFTER |
|---|---|---|
| `DELETE FROM ngram` for one document | 0.0899 / 0.0823 s (also measured 0.0419 / 0.0370 s later on the same warm copy — cache state moves this figure by 2×) | **0.00021 / 0.00006 s** |
| `changes()` | 1 | 1 |
| plan | `SCAN ngram VIRTUAL TABLE INDEX 0:` | `SCAN ngram VIRTUAL TABLE INDEX 0:=` + `SEARCH ngram_meta USING COVERING INDEX idx_nm_doc (doc_id=?)` |

**The one number that got worse, and it is not hidden.** Single-document end-to-end through the CLI
for the same already-indexed document: **0.141 / 0.120 s before → 0.352 / 0.272 s after**. The cause
is stated in row 2 of the table above: the map-integrity check in `init_db` reads ~33 MB per
**process**, so a process that indexes ONE document pays it in full. A refresh process indexes
~81,000 documents, so it amortises to **~0.4 KB and ~3 µs per document**. Anyone measuring this fix
with a single document will see it as a regression; that is the wrong unit. The reason the check is
there at all is §9.5.

## 9.4 The guard, and the honest note about when it fires

Exercised through the real code path on the copy, plus directly, because the end-to-end route turned
out to pre-empt it:

* **End-to-end, injected before the process started** (removed a document's map row; added a stale
  map row pointing at a nonexistent rowid): in both cases the re-ingest came out clean —
  `ngram_without_meta` 0, `ngram_meta_without_ngram` 0, one ngram row and one map row per document —
  **with no fallback message**. Cause: `init_db` reconciles the map at process start, so by the time
  `add_document` ran there was nothing left to disagree about. That is the designed behaviour and the
  faster outcome, but it means this route does not exercise the guard.
* **Directly, with the discrepancy injected after `init_db`** — branch 1 (map stale: 1 map row for
  2 ngram rows) → fast delete `changes()=0` ≠ `expected=1` → fallback fired, slow delete removed
  **2** rows, 0 left. A fast-path-only implementation would have deleted nothing and left two stale
  ngram rows behind. Branch 2 (`expected < 1`) → fallback fired and returned 0. Both stderr lines are
  in the transcript: `usearch: doc 168505: 0 ngram row(s) deleted through ngram_meta but the map
  records 1; falling back to the full-scan delete so none is left behind`.
* **The out-of-band writers** — issued `DELETE FROM ngram WHERE doc_id=?` exactly as
  `adapters/files/sync.py` does: `ngram_meta_without_ngram` went to 1, then
  `ensure_ngram_map()` returned `{'backfilled': 0, 'stale_removed': 1}` and the count returned to
  **0**. The map survives the two adapters that write SQL directly.

## 9.5 Why `init_db` reconciles the map (and not just `migrate`)

`migrate()` runs only on `usearch.py upgrade`, and **the ingest never calls it** (`cmd_add` calls
`init_db`). A back-fill that lived only in `migrate()` would have left this fix inert until a human
remembered a command, and every re-indexed document would have kept paying the full scan — a fix
that is correct and does nothing. `init_db` is the one function every writer path calls (`cmd_add`,
`cmd_init`, `sync.py:1666/179/623/711/881`, `seed_local_tree.py`, `selftest.py`), so that is where
the map is reconciled. Two consequences, both measured:

* **It is idempotent and cheap**: two counting queries, `0` written, when the map is whole (32.7 MB
  read, 0.29 s — see §9.3).
* **It repairs what the two direct-SQL adapters break** (§9.0 item 5), which no insert-time mapping
  can prevent.

## 9.6 Integrity

**Copy** (`check --sample 0`, run twice — after the new delete, and again after all four sites and
the guard tests had been exercised): **OK, exit 0**, every key zero and `fts_integrity_rank` True —
`orphan_chunks 0, orphan_chunks_meta 0, chunk_count_mismatch 0, chunks_without_meta 0,
ngram_without_meta 0, ngram_meta_without_ngram 0, orphan_ngram 0`. Row counts on the copy:
`ngram_docsize` 159,515 = `ngram_meta` 159,515 = `docs` 159,515, with 0 documents holding two ngram
rows.

**Live, read-only, 2026-09-16 19:03:35** (before the fix can have run anywhere):

| query | result | time |
|---|---|---|
| `docs` | 159,600 | 1.1 s |
| `chunks_docsize` / `chunks_meta` | 988,602 / 988,602 | 0.0 s |
| `ngram` / `ngram_docsize` | 159,600 / 159,600 | 0.0 s |
| `orphan_chunks` | **0** | 59.0 s |
| `chunks_without_meta` | **0** | 6.5 s |
| `chunk_count_mismatch` | **0** | 1.0 s |
| `orphan_ngram` | **0** | 0.4 s |
| doc_ids with more than one `ngram` row | **0** | 0.2 s |
| `ngram_meta` exists / `schema_version` | **no / 1** | — |

So on the live index the ngram mapping is a bijection *by the counting argument* (§9.0 item 3), and
it will be recorded as one by the next writer.

### 9.6.1 An index with no `ngram_meta` yet must not look broken

The live index is exactly that state right now, and `check` on it would have reported
`ngram_without_meta: 159,600` — a "problem" that needs no action and heals itself inside one ingest
tick. A health check that cries wolf is a health check nobody runs (the function's own docstring
says so). So those two keys report `None` — the check framework's existing "not applicable" —
whenever the table does not exist, with the reason written to stderr instead. Measured on the copy
with `ngram_meta` dropped:

```
OK   ...usearch.db
  fts_integrity_rank True   orphan_chunks 0   chunks_without_meta 0
  ngram_without_meta None   ngram_meta_without_ngram None   orphan_ngram 0
exit code: 0
stderr: usearch: ngram_meta does not exist on this index yet, so the ngram map invariants cannot be
        evaluated. The next writer creates and fills it (init_db -> ensure_ngram_map); until then a
        re-indexed document scans the whole ngram table instead of deleting one row.
```

and then the writer heals it — `usearch.py init` → `schema v2` → the same check reads
`ngram_without_meta 0`, `ngram_meta_without_ngram 0`, **OK, exit 0**. That is precisely the sequence
the live index is about to go through at 19:15:46, and it is why I could verify the unmigrated path
without touching it.

### 9.6.2 Functional checks beyond the invariants

* **Suites**: `tests/test_usearch_core.py` **87 tests OK** and `tests/test_end_to_end.py`
  **28 tests OK**, run **twice** — once after the fix and again after the `integrity_check`
  tolerance edit. These build their own indexes and never touch `~/.usearch`.
* **All four converted sites exercised for ngram**: prune (`usearch: pruned 1 vanished documents`,
  leaving 1 doc = 1 ngram row = 1 map row); `delete_documents` (returned 1, source's ngram and map
  rows both fell by one); `drop_source` (`dropped 2 document(s)`, 0 ngram rows and 0 map rows left
  behind); `add_document` (all of §9.3 and §9.4).
* **The trigram rung still answers**: `ngram MATCH '"covery"'` returned document ids
  `[5264, 7427, 7626, 7627, 9089]`, exactly the ids a `LIKE '%covery%'` over title/path returns —
  so the index still maps rowids to the right documents after this change.
* `ast.parse` OK, and the schema's own guard test still passes (no comment line contains a statement
  separator).

## 9.7 The residual: what is left, and the next amplifier

**Prediction for the live ingest** (labelled as a prediction — no post-fix live run exists yet): the
read per re-indexed document falls from **14.39 MB to 45–102 KB**, so the 124–125.5 MB/s measured on
the current process should become **roughly 0.4–3 MB/s**, i.e. single-digit MB/s, and a full
`db:localdb` sweep's read cost falls from **~1.17 TB** (81,000 × 14.39 MB) to **~4–8 GB**, plus the
one-time ~33 MB map adoption. The process should stop being read-bound at all; the remaining cost is
the write path and the adapter, not the index.

**What is NOT fixed, and is now the largest remaining scan:** the two adapters that delete with their
own SQL —

* `adapters/files/sync.py:392` — `DELETE FROM chunks WHERE doc_id=?` (**1.27 GB full scan per
  vanished file**), and `:393` — the same for `ngram` (now an 18 MB full scan per vanished file);
* `adapters/journal/sync.py:526` — the same two statements.

Neither has the rowid mapping available to it (`chunks_meta` / `ngram_meta` are keyed by the rowid,
and both are reachable through the same helper shape), so the complete fix is for those two
`prune_*` functions to call the shared helpers — `delete_chunks_for_doc` / `delete_ngram_for_doc`
plus their meta deletes — instead of issuing SQL. I did **not** change them: they are outside
`usearch.py`, the brief for this pass named `usearch.py`, and a change to two more files on a live
index is a separate, verifiable increment. Their cost is proportional to the number of documents
that vanish per run, not to the corpus, so they are a real but far smaller amplifier than the sweep
was.

Everything else in doc 68 §5 also still stands (the adapter state that never advances, the
decorative `timeout_seconds`, the 30-minute cadence over a source that needs longer).

## 9.8 What I could not verify

1. **The fix running against the live index.** The process alive at 19:05 (PID 8940, started 18:46:20)
   loaded its code before this change and keeps the old `ngram` delete. The first process that can
   show it is the next tick — `NextRunTime` 19:15:46 (`LastRunTime` 18:45:47, `LastTaskResult`
   **267009 = still running** at 19:05). **If that 18:45 run is still alive at 19:15, the new tick
   can fail with `database is locked` before it ever reaches a document** — the same collision doc 68
   §2 describes, and not something this change addresses. The confirmation to run afterwards is 30 s
   of `ReadTransferCount` on the new PID (it should read in single-digit MB/s, not 124 MB/s).
2. **The residual live rate.** Predicted from measured per-document bytes, not measured.
3. **`fts_integrity_rank` on the live database** — its probe needs the write lock (Part 1, §5.3), so
   it was verified on the copy and the live run is unverified.
4. **The ~33 MB per-process map-integrity read.** Measured once, on the copy. It is 0.03 % of a
   single pre-fix sweep and amortises to ~0.4 KB/document across 81,000, so I did not optimise it —
   but it is new recurring I/O and it is the reason a one-document CLI run is slower (§9.3).
   A cheaper trigger would need a flag that the two direct-SQL adapters can invalidate, which is
   exactly what the scan is for.
5. **The two adapter sites in §9.7** — unchanged, therefore still scanning.

## 9.9 Provenance (Part 2)

Every number above was produced on this host on 2026-09-16 between 18:38 and 19:06, by the commands
and code shown. The snapshot used for all destructive work was
`%TEMP%\zabz-ngram-clean\usearch.db`, taken 18:53:08 with `VACUUM INTO` over a read-only connection,
`quick_check` ok in 56.0 s, **deleted at 19:06 and confirmed absent**. A first raw-copy attempt
(`%TEMP%\zabz-ngram-fixcopy`, 18:49) was discarded because it failed `quick_check` (§9.1) and was
removed before the second snapshot was taken. Live figures come from `mode=ro` connections (invariants
and counts, stamped 19:03:35), from `Get-CimInstance` (process counters and the 124 MB/s window,
19:03–19:05) and from `Get-ScheduledTaskInfo` (19:05). No write of any kind was made to
`C:\Users\ezabz\.usearch\usearch.db`; its size/mtime movement during the session (2,360,856,576 B at
18:50 → 2,366,541,824 B at 19:05:30) is the running ingest's own checkpointing. `git status` shows
`M scripts/usearch.py` and nothing else; the `tests/` suites were run with
`PYTHONDONTWRITEBYTECODE=1` and no bytecode was written into the repo.
