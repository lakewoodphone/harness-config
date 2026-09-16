# 69 — The read-amplification fix, applied and measured on a copy

Follows `docs/mesh/68-read-amplification.md` (the diagnosis). This file records the change, the
before/after numbers, the integrity results, and what could not be verified.

Author: delegated agent. Host **ZABZ-YOGA**, 2026-09-16, all times local EDT (= UTC-4).
Repo: `C:\Users\ezabz\code\unified-search`, HEAD **dd66603**. File changed: `scripts/usearch.py`
only, mtime 18:26:08. **Nothing was committed** (owner commits). **No state-changing git command
was run.** The live index was never written to, and no process was restarted, killed or
reconfigured.

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
  full `db:localdb` sweep), the adapter state that never advances so every run is a full pass
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
